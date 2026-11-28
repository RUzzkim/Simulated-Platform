"""Import this project's URDF visuals into an articulated Blender hierarchy."""

import argparse
from dataclasses import dataclass
import json
from math import cos, sin
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import bpy
from mathutils import Euler, Matrix, Vector


REPO = Path(__file__).resolve().parents[1]
RENDER = REPO / "render"
PACKAGE = REPO / "sim" / "gazebo_arm"
URDF = PACKAGE / "urdf" / "hydraulic_arm.urdf"
JOINT_NAMES = tuple(f"joint_{i}" for i in range(1, 7))
# Keep the simulation tree read-only, including Python's import cache.
sys.dont_write_bytecode = True
sys.path.insert(0, str(PACKAGE))
from gazebo_arm.end_effector import EndEffector, rotation
from gazebo_arm.scenarios import HOME


@dataclass
class Joint:
    name: str
    child: object
    origin: Matrix
    axis: Vector


def origin_of(element):
    origin = element.find("origin")
    attrs = {} if origin is None else origin.attrib
    xyz = tuple(map(float, attrs.get("xyz", "0 0 0").split()))
    rpy = tuple(map(float, attrs.get("rpy", "0 0 0").split()))
    return Matrix.Translation(xyz) @ Euler(rpy, "XYZ").to_matrix().to_4x4()


def mesh_path(uri, urdf):
    prefix = "package://gazebo_arm/"
    if uri.startswith(prefix):
        return PACKAGE / uri[len(prefix):]
    return urdf.parent / uri


def collada_mesh(path):
    """Load indexed, untransformed Z-up meshes emitted by visual_meshes.py."""
    root = ET.parse(path).getroot()
    if root.findtext("./{*}asset/{*}up_axis") != "Z_UP":
        raise ValueError(f"Expected a Z-up mesh: {path}")
    if float(root.find("./{*}asset/{*}unit").get("meter")) != 1.0:
        raise ValueError(f"Expected meters: {path}")
    geom = root.find("./{*}library_geometries/{*}geometry/{*}mesh")
    sources = {}
    for source in geom.findall("{*}source"):
        raw = tuple(map(float, source.findtext("{*}float_array").split()))
        stride = int(source.find("./{*}technique_common/{*}accessor").get("stride"))
        sources[source.get("id")] = list(zip(*(raw[i::stride] for i in range(stride))))
    vertices = geom.find("{*}vertices/{*}input").get("source").lstrip("#")
    positions = sources[vertices]
    faces, loop_normals = [], []
    for triangles in geom.findall("{*}triangles"):
        inputs = {i.get("semantic"): i for i in triangles.findall("{*}input")}
        stride = 1 + max(int(i.get("offset")) for i in inputs.values())
        vp = int(inputs["VERTEX"].get("offset"))
        np = int(inputs["NORMAL"].get("offset"))
        normals = sources[inputs["NORMAL"].get("source").lstrip("#")]
        values = list(map(int, triangles.findtext("{*}p").split()))
        for i in range(0, len(values), stride * 3):
            faces.append(tuple(values[i + j * stride + vp] for j in range(3)))
            loop_normals.extend(normals[values[i + j * stride + np]] for j in range(3))
    mesh = bpy.data.meshes.new(path.stem)
    mesh.from_pydata(positions, [], faces)
    mesh.update()
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    mesh.normals_split_custom_set(loop_normals)
    return mesh


def mesh_data(path):
    if path.suffix.lower() == ".dae":
        return collada_mesh(path)
    if path.suffix.lower() == ".stl":
        bpy.ops.wm.stl_import(filepath=str(path))
        imported, = bpy.context.selected_objects
        data = imported.data
        bpy.data.objects.remove(imported, do_unlink=True)
        return data
    raise ValueError(f"Unsupported visual mesh: {path}")


def finish_for(link, asset, scale, material):
    if link.startswith("finger_") and asset == "graphite_block" and scale[1] <= 0.0041:
        return "rubber"
    if asset == "service_cover":
        return "cover"
    if asset.startswith("graphite") or asset in {"pedestal_foot", "line_cover", "gripper_rail"}:
        return "graphite"
    if asset in {"steel_disc", "finger"} or material == "bolt":
        return "steel"
    return "cast"


def import_robot(urdf=URDF):
    model = ET.parse(urdf).getroot()
    collection = bpy.data.collections.new("Hydraulic arm · URDF visuals")
    bpy.context.scene.collection.children.link(collection)
    links = {}
    for item in model.findall("link"):
        name = item.get("name")
        obj = bpy.data.objects.new(name, None)
        collection.objects.link(obj)
        obj.empty_display_size = .025
        links[name] = obj
    joints = {}
    for item in model.findall("joint"):
        child = links[item.find("child").get("link")]
        child.parent = links[item.find("parent").get("link")]
        origin = origin_of(item)
        child.matrix_basis = origin
        kind = item.get("type")
        if kind in {"revolute", "continuous"}:
            axis = Vector(tuple(map(float, item.find("axis").get("xyz").split()))).normalized()
            joints[item.get("name")] = Joint(item.get("name"), child, origin, axis)
            child["urdf_joint_name"] = item.get("name")
            child["urdf_origin"] = [value for row in origin for value in row]
            child["urdf_axis"] = list(axis)
        elif kind != "fixed":
            raise ValueError(f"Unsupported joint type: {kind}")
    if set(joints) != set(JOINT_NAMES):
        raise ValueError(f"Unexpected movable joints: {list(joints)}")
    cache = {}
    for item in model.findall("link"):
        link = item.get("name")
        for i, visual in enumerate(item.findall("visual")):
            element = visual.find("geometry/mesh")
            if element is None:
                raise ValueError(f"Visual {link}/{i} is not a mesh")
            path = mesh_path(element.get("filename"), urdf)
            if path not in cache:
                cache[path] = mesh_data(path)
            obj = bpy.data.objects.new(f"{link} · {i:02d} {path.stem}", cache[path])
            collection.objects.link(obj)
            obj.parent = links[link]
            scale = tuple(map(float, element.get("scale", "1 1 1").split()))
            obj.matrix_basis = origin_of(visual) @ Matrix.Diagonal((*scale, 1))
            obj["finish"] = finish_for(link, path.stem, scale, visual.find("material").get("name", "")
                                       if visual.find("material") is not None else "")
    return links, joints


def scene_joints():
    return {obj["urdf_joint_name"]: Joint(
        obj["urdf_joint_name"], obj,
        Matrix(tuple(tuple(obj["urdf_origin"][i:i + 4]) for i in range(0, 16, 4))),
        Vector(obj["urdf_axis"]),
    ) for obj in bpy.context.scene.objects if "urdf_joint_name" in obj}


def set_pose(joints, angles):
    for name, angle in zip(JOINT_NAMES, angles, strict=True):
        joint = joints[name]
        joint.child.matrix_basis = joint.origin @ Matrix.Rotation(angle, 4, joint.axis)
    bpy.context.view_layer.update()


def pose_error(angles, end_effector):
    expected = end_effector.pose(angles)
    actual = bpy.data.objects["base_link"].matrix_world.inverted() @ bpy.data.objects["link_6"].matrix_world
    pos_error = (actual.translation - Vector(expected[:3])).length
    expected_rotation = Matrix(rotation(*expected[3:]))
    rot_error = max(abs(expected_rotation[i][j] - actual[i][j]) for i in range(3) for j in range(3))
    if pos_error > 1e-5 or rot_error > 1e-5:
        raise ValueError(f"Pose differs from URDF reference: position {pos_error}, rotation {rot_error}")
    return {"position_error_m": pos_error, "rotation_max_component_error": rot_error}


def camera_at(name, eye, target, lens=52):
    data = bpy.data.cameras.new(name)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = eye
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()
    obj.data.lens = lens
    return obj


def cli_args():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urdf", type=Path, default=URDF)
    args = parser.parse_args(cli_args())
    bpy.ops.wm.read_factory_settings(use_empty=True)
    links, joints = import_robot(args.urdf)
    set_pose(joints, HOME)
    output = RENDER / "checks"
    output.mkdir(parents=True, exist_ok=True)
    result = {
        "urdf": str(args.urdf), "home_joint_angles_rad": HOME,
        "links": len(links), "visual_instances": sum("finish" in obj for obj in bpy.context.scene.objects),
        **pose_error(HOME, EndEffector(args.urdf)),
    }
    (output / "01_import.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    scene = bpy.context.scene
    target = Vector((.37, 0, .28))
    yaw, pitch, distance = .8, .36, 2.45
    eye = target + distance * Vector((cos(pitch) * cos(yaw), cos(pitch) * sin(yaw), sin(pitch)))
    scene.camera = camera_at("HOME proof camera", eye, target, 46)
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "SINGLE"
    scene.display.shading.single_color = (.65, .67, .70)
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1000, 750, 100
    scene.render.filepath = str(output / "blender_home.png")
    bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "imported_arm.blend"))
    print("IMPORT CHECK", result, flush=True)


if __name__ == "__main__":
    main()
