"""Export the approved product scene's evaluated geometry into URDF link coordinates."""

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import bpy
from mathutils import Vector


PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[1]
SOURCE = REPO / "render/checks/product_final_v2.blend"
URDF = PACKAGE / "urdf/hydraulic_arm.urdf"
sys.dont_write_bytecode = True
sys.path[:0] = [str(REPO / "render"), str(PACKAGE)]
from import_urdf import import_robot, scene_joints, set_pose
from gazebo_arm.scenarios import HOME
from gazebo_arm.visual_meshes import FINISHES, write_mesh


def bounds(points):
    return [[min(v[i] for v in points) for i in range(3)],
            [max(v[i] for v in points) for i in range(3)]]


def export_groups(parts, folder, prefix="rviz"):
    """The repository importer reads one material per DAE, so batch each link by finish."""
    batches = defaultdict(list)
    for part in parts:
        batches[part["link"], part["finish"]].append(part)
    assets = {}
    for (link, finish), group in batches.items():
        points, normals, faces = [], [], []
        for part in group:
            names = part["points"], part["normals"], part["faces"]
            offset, normal_offset = len(points), len(normals)
            points.extend(names[0])
            normals.extend(names[1])
            faces.extend(tuple((p + offset, n + normal_offset) for p, n in face) for face in names[2])
        stem = f"{prefix}_{link}_{finish}"
        write_mesh(folder / f"{stem}.dae", points, normals, faces, finish)
        assets.setdefault(link, []).append({"stem": stem, "triangles": len(faces)})
    return assets


def collect(source):
    links = {node.get("name") for node in source.findall("link")}
    dg = bpy.context.evaluated_depsgraph_get()
    parts, skipped = [], []
    for obj in sorted(bpy.context.scene.objects, key=lambda obj: obj.name):
        if obj.type != "MESH":
            continue
        parent = obj.parent
        while parent and parent.name not in links:
            parent = parent.parent
        if parent is None:
            skipped.append(obj.name)
            continue
        # The pitch-axis and link_5 differ only by a fixed DH transform.
        link = "link_5" if parent.name == "joint_5_axis" else parent.name
        dest = bpy.data.objects[link]
        evaluated = obj.evaluated_get(dg)
        transform = dest.matrix_world.inverted() @ evaluated.matrix_world
        normal_transform = transform.to_3x3().inverted().transposed()
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            points = [list(transform @ v.co) for v in mesh.vertices]
            normals = [list((normal_transform @ n.vector).normalized()) for n in mesh.corner_normals]
            faces = [[(mesh.loops[i].vertex_index, i) for i in tri.loops] for tri in mesh.loop_triangles]
            if transform.to_3x3().determinant() < 0:
                faces = [face[::-1] for face in faces]
        finally:
            evaluated.to_mesh_clear()
        finish = obj.get("finish", "cast")
        if finish == "rubber":
            finish = "graphite"
        if finish not in FINISHES:
            raise ValueError(f"Unknown finish {finish} for {obj.name}")
        parts.append(dict(name=obj.name, source_link=parent.name, link=link, finish=finish,
                          points=points, normals=normals, faces=faces,
                          modifiers=[mod.type for mod in obj.modifiers]))
    return parts, skipped


def raw_model(source, assets):
    root = ET.fromstring(ET.tostring(source))
    for link in root.findall("link"):
        for old in link.findall("visual"):
            link.remove(old)
        for asset in assets.get(link.get("name"), []):
            visual = ET.SubElement(link, "visual", name=asset["stem"])
            ET.SubElement(ET.SubElement(visual, "geometry"), "mesh",
                          filename=f"raw/{asset['stem']}.dae")
    return root


def verify_roundtrip(raw_path, parts, source_joints):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    links, joints = import_robot(raw_path)
    set_pose(joints, HOME)
    assert all(joint.origin == source_joints[name][0] and joint.axis == source_joints[name][1]
               for name, joint in joints.items())
    references = defaultdict(list)
    for part in parts:
        references[part["link"]].extend(part["points"])
    errors = {}
    for name, reference in references.items():
        parent = links[name]
        imported = [obj.matrix_basis @ v.co for obj in parent.children if obj.type == "MESH"
                    for v in obj.data.vertices]
        a, b = bounds(reference), bounds(imported)
        delta = max(abs(x-y) for row, other in zip(a, b) for x,y in zip(row, other))
        assert delta < .001, (name, delta)
        errors[name] = delta * 1000
    return errors


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--output", type=Path, required=True)
    opts = args.parse_args(sys.argv[sys.argv.index("--")+1:])
    if Path(bpy.data.filepath).resolve() != SOURCE.resolve() or bpy.context.scene.get("product_revision") != "v2-aligned-jaws":
        raise ValueError(f"Open the approved source {SOURCE}")
    out = opts.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    raw = out / "raw"
    raw.mkdir(exist_ok=True)
    root = ET.parse(URDF).getroot()
    bpy.context.view_layer.update()
    joints = {name: (joint.origin.copy(), joint.axis.copy()) for name,joint in scene_joints().items()}
    parts, skipped = collect(root)
    names = {part["name"] for part in parts}
    for side in ("left", "right"):
        assert f"finger_{side} machined jaw" in names
        assert f"finger_{side} · 02 graphite_block" in names
    assert {"Enclosed gripper drive", "Linear jaw guide -1", "Linear jaw guide +1"} <= names
    assets = export_groups(parts, raw)
    model = out / "raw.urdf"
    ET.ElementTree(raw_model(root, assets)).write(model, encoding="utf-8")
    errors = verify_roundtrip(model, parts, joints)
    (out / "components.json").write_text(json.dumps(parts, ensure_ascii=False), encoding="utf-8")
    report = {"source": str(SOURCE.relative_to(REPO)), "sha256": sha256(SOURCE.read_bytes()).hexdigest(),
              "component_count": len(parts), "unassigned": skipped, "bbox_roundtrip_mm": errors,
              "joint_origin_and_axis_changes": 0,
              "components": [{**{key: part[key] for key in ("name", "link", "source_link", "finish", "modifiers")},
                              "triangles": len(part["faces"])} for part in parts]}
    (out / "blender_mesh_ownership.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("BBOX_ROUNDTRIP", errors, "component_count", len(parts), flush=True)


if __name__ == "__main__":
    main()
