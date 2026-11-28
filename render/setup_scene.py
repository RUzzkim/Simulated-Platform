"""Build a Cycles studio around the robot imported by import_urdf.py."""

import argparse
from hashlib import sha256
import json
from math import hypot
from pathlib import Path
import shutil
import subprocess
import sys
import time

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_urdf import HOME, RENDER, camera_at, cli_args, scene_joints, set_pose
from mechanical_details import loft, refine_assembly


CHECKS = RENDER / "checks"
FINAL_SCENE = CHECKS / "product_final_v2.blend"
FINAL_REVISION = "v2-aligned-jaws"
BRUSH_ROUGHNESS = .028
TURNED_ROUGHNESS = .011
FINISHES = {
    "cast": ("Satin silver housing", (.45, .47, .50), .96, .49),
    "graphite": ("Satin gunmetal joints and rails", (.086, .096, .112), .94, .38),
    "steel": ("Machined steel", (.60, .63, .65), 1.0, .22),
    "cover": ("Graphite service cover", (.115, .126, .144), .90, .42),
    "rubber": ("Grip pad rubber", (.026, .029, .033), 0, .79),
}

# Each entry after the baseline changes exactly one scene setting.
REFERENCE_CHANGES = [
    None,
    ("floor_gray", .235),
    ("floor_gray", .038),
    ("floor_roughness", .27),
    ("glossy_world_strength", .35),
    ("glossy_world_strength", .60),
]
REFERENCE_BASE = {"floor_gray": .66, "floor_roughness": .82, "glossy_world_strength": .065}
GRIPPER_STUDIO_SETTINGS = ((.059, .27, 1.0), (.059, .54, .92), (.080, .54, .865))


def report(name, data):
    CHECKS.mkdir(parents=True, exist_ok=True)
    (CHECKS / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def configure_cuda(scene):
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "CUDA"
    prefs.refresh_devices()
    devices = [device.name for device in prefs.devices if device.type == "CUDA"]
    if not any("RTX 5060 Ti" in name for name in devices):
        raise RuntimeError(f"RTX 5060 Ti CUDA device unavailable: {devices}")
    for device in prefs.devices:
        device.use = device.type == "CUDA" and "RTX 5060 Ti" in device.name
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU"
    return devices


def material(name, color, metallic, roughness):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = roughness
    return mat


def metal_finish(mat, roughness, turned=False):
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    shader = nodes["Principled BSDF"]
    coords = nodes.new("ShaderNodeTexCoord").outputs["Generated"]
    tangent = nodes.new("ShaderNodeTangent")
    tangent.axis = "Z" if turned else "X"
    links.new(tangent.outputs["Tangent"], shader.inputs["Tangent"])
    shader.inputs["Anisotropic"].default_value = .42 if turned else .24

    mapping = nodes.new("ShaderNodeVectorMath")
    if turned:
        mapping.operation = "SUBTRACT"
        mapping.inputs[1].default_value = (.5, .5, .5)
        texture = nodes.new("ShaderNodeTexWave")
        texture.wave_type = "RINGS"
        texture.rings_direction = "Z"
        texture.inputs["Scale"].default_value = 16
    else:
        mapping.operation = "MULTIPLY"
        mapping.inputs[1].default_value = (1.5, 24, 24)
        texture = nodes.new("ShaderNodeTexNoise")
        texture.inputs["Scale"].default_value = 9
        texture.inputs["Detail"].default_value = 2
    variation = nodes.new("ShaderNodeMapRange")
    amplitude = TURNED_ROUGHNESS if turned else BRUSH_ROUGHNESS
    variation.inputs["To Min"].default_value = roughness - amplitude
    variation.inputs["To Max"].default_value = roughness + amplitude
    links.new(coords, mapping.inputs[0])
    links.new(mapping.outputs["Vector"], texture.inputs["Vector"])
    links.new(texture.outputs["Fac"], variation.inputs["Value"])
    links.new(variation.outputs["Result"], shader.inputs["Roughness"])


def refine_gripper():
    for name in ("finger_left", "finger_right"):
        link = bpy.data.objects[name]
        pad, = (obj for obj in link.children
                if obj.type == "MESH" and obj.data.name == "graphite_block" and obj.get("finish") == "rubber")
        direction = 1 if pad.location.y > 0 else -1
        pad.scale = (.035, .014, .046)
        pad.location = (0, direction * .0212, .035)
        pad.hide_render = False
        jaw_name = f"{name} machined jaw"
        if bpy.data.objects.get(jaw_name) is None:
            old = next((obj for obj in link.children if obj.type == "MESH" and obj.data.name == "finger"), None)
            steel = old.active_material if old else bpy.data.materials.get(FINISHES["steel"][0])
            jaw = loft(link, jaw_name, [
                ((0, 0, -.0066), .0150, .0180),
                ((0, 0, -.0046), .0160, .0200),
                ((0, 0, .0040), .0160, .0200),
                ((0, 0, .0090), .0140, .0180),
                ((0, 0, .0580), .0140, .0180),
                ((0, 0, .0640), .0120, .0160),
            ], "steel", exponent=.22)
            if steel:
                jaw.data.materials.append(steel)
        for obj in tuple(link.children):
            if obj == pad or obj.name == jaw_name or obj.type != "MESH":
                continue
            if obj.data.name == "finger" or obj.name in {f"{name} flat gripping face", f"{name} slider shoe"}:
                bpy.data.objects.remove(obj, do_unlink=True)
    guides = [obj for obj in bpy.data.objects["gripper_base"].children
              if obj.name.startswith("Linear jaw guide ")]
    if len(guides) != 2:
        raise ValueError("Expected the two guide rails that replace the original gripper rail")
    graphite = bpy.data.materials.get(FINISHES["graphite"][0])
    for rail in guides:
        center_x = sum(corner[0] for corner in rail.bound_box) / 8
        rail.scale.x = 1.25
        rail.location.x = -center_x * .25
        rail["finish"] = "graphite"
        rail.hide_render = False
        if graphite is not None and rail.active_material != graphite:
            if rail.material_slots:
                rail.active_material = graphite
            else:
                rail.data.materials.append(graphite)
    bpy.context.view_layer.update()


def robot_meshes():
    return [obj for obj in bpy.context.scene.objects if "finish" in obj]


def robot_points(meshes):
    return [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]


def fit_overview(camera, points, aspect, margin=1.17):
    rotation = camera.rotation_euler.to_quaternion()
    right, up, back = [rotation @ Vector(axis) for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
    xs, ys, zs = ([point.dot(axis) for point in points] for axis in (right, up, back))
    camera.location = right * ((min(xs) + max(xs)) / 2) + up * ((min(ys) + max(ys)) / 2) + back * (max(zs) + 3)
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = max(max(xs) - min(xs), (max(ys) - min(ys)) * aspect) * margin


def area(name, position, target, power, width, height):
    data = bpy.data.lights.new(name, "AREA")
    data.shape = "RECTANGLE"
    data.energy, data.size, data.size_y = power, width, height
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = position
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()
    return obj


def gripper_camera(name, tool_frame, offset, lens):
    jaw = tool_frame @ Vector((0, 0, .046))
    eye = tool_frame @ Vector(offset)
    camera = bpy.data.objects.get(name)
    if camera is None:
        camera = camera_at(name, eye, jaw, lens)
    camera.location = eye
    camera.data.lens = lens
    back = (eye - jaw).normalized()
    side = tool_frame.to_3x3().col[1]
    right = (side - side.dot(back) * back).normalized()
    camera.rotation_euler = Matrix((right, back.cross(right), back)).transposed().to_euler()
    return camera


def frame_home_from_tool_side(overview):
    view = Vector((1.65, -2.45, hypot(1.65, 2.45)))
    overview.rotation_euler = (-view).to_track_quat("-Z", "Y").to_euler()
    fit_overview(overview, robot_points(robot_meshes()), 4 / 3)


def prepare_render_gripper(scene):
    refine_gripper()
    if scene.camera.name == "Overview 45°":
        frame_home_from_tool_side(scene.camera)


def require_final_scene(scene):
    if Path(bpy.data.filepath).resolve() != FINAL_SCENE.resolve() or scene.get("product_revision") != FINAL_REVISION:
        raise ValueError(f"Production rendering requires the finalized scene at {FINAL_SCENE}")


def set_png(scene, width, height):
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.compression = 15


def soften_backdrop(floor, strength, gray=.16):
    """Tone the camera-visible sweep while retaining reflected light transport."""
    nodes = floor.active_material.node_tree.nodes
    links = floor.active_material.node_tree.links
    rays = nodes.new("ShaderNodeLightPath")
    weight = nodes.new("ShaderNodeMath")
    weight.operation = "MULTIPLY"
    weight.inputs[1].default_value = strength
    links.new(rays.outputs["Is Camera Ray"], weight.inputs[0])
    sweep = nodes.new("ShaderNodeEmission")
    sweep.inputs["Color"].default_value = (gray, gray, gray, 1)
    mix = nodes.new("ShaderNodeMixShader")
    links.new(weight.outputs[0], mix.inputs[0])
    links.new(nodes["Principled BSDF"].outputs[0], mix.inputs[1])
    links.new(sweep.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], nodes["Material Output"].inputs["Surface"])


def render_gripper_views(number, overview, tool_camera, settings):
    scene = bpy.context.scene
    folder = RENDER / "work" / "gripper" / f"round_{number:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(CHECKS / "studio_home.png")
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / "studio.blend"))
    floor = bpy.data.objects["Seamless studio floor"]
    gray, floor_roughness, cast_color_scale = settings
    parameters = {"cast_roughness": FINISHES["cast"][3], "world_strength_scale": 1.1,
                  "floor_gray": gray, "floor_roughness": floor_roughness, "cast_color_scale": cast_color_scale,
                  "pad_thickness_scale": 3.5}
    for view, camera, size in (("home", overview, (1600, 1200)), ("tool", tool_camera, (960, 720)),
                               ("reference_pose", None, (622, 636))):
        if camera is None:
            camera = reference_framing(scene)
        set_png(scene, *size)
        scene.camera = camera
        candidate = folder / f"{view}.png"
        scene.render.filepath = str(candidate)
        bpy.ops.render.render(write_still=True)
        mask = folder / f"{view}_mask.png"
        saved_transparency = scene.render.film_transparent
        scene.render.film_transparent = True
        scene.render.image_settings.color_mode = "RGBA"
        floor.visible_camera = False
        scene.render.filepath = str(mask)
        bpy.ops.render.render(write_still=True)
        floor.visible_camera = True
        scene.render.film_transparent = saved_transparency
        subprocess.run(["py", "-3", str(RENDER / "compare_metrics.py"), str(candidate),
                        "--mask", str(mask), "--round", str(number), "--contrast-view", view,
                        "--parameters", json.dumps(parameters)], check=True)


def reference_framing(scene):
    joints = scene_joints()
    meshes = robot_meshes()
    if len(joints) != 6 or not meshes:
        raise ValueError("Open checks/studio.blend for the reference render")
    set_pose(joints, (0, 1.84, -2.02, .05, -.12, -.78))
    cam = camera_at("Reference framing", (.62, 2.75, .78), (0, 0, 0))
    cam.data.sensor_fit = "HORIZONTAL"
    scene.camera = cam
    fit_overview(cam, robot_points(meshes), 311 / 318, margin=1.145)
    return cam


def reference_round(number):
    scene = bpy.context.scene
    configure_cuda(scene)
    refine_gripper()
    reference_framing(scene)
    meshes = robot_meshes()
    set_png(scene, 622, 636)

    state = dict(REFERENCE_BASE)
    change = None
    for item in REFERENCE_CHANGES[1:number]:
        key, value = item
        change = {"setting": key, "before": state[key], "after": value}
        state[key] = value
    floor = bpy.data.objects["Seamless studio floor"]
    shader = floor.active_material.node_tree.nodes["Principled BSDF"]
    gray = state["floor_gray"]
    shader.inputs["Base Color"].default_value = (gray, gray * .67 / .66, gray * .69 / .66, 1)
    shader.inputs["Roughness"].default_value = state["floor_roughness"]
    scene.world.node_tree.nodes["Map Range"].inputs["To Max"].default_value = state["glossy_world_strength"]

    folder = RENDER / "work" / "reference"
    folder.mkdir(parents=True, exist_ok=True)
    candidate = CHECKS / f"reference_round_{number:02d}.png"
    control = folder / f"round_{number:02d}_without_reflection.png"
    mask = folder / "subject_mask.png"
    scene.render.filepath = str(candidate)
    bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / f"round_{number:02d}.blend"))
    for obj in meshes:
        obj.visible_glossy = False
    scene.render.filepath = str(control)
    bpy.ops.render.render(write_still=True)
    if number == 1 or not mask.exists():
        scene.render.film_transparent = True
        scene.render.image_settings.color_mode = "RGBA"
        floor.visible_camera = False
        scene.render.filepath = str(mask)
        bpy.ops.render.render(write_still=True)
    python = shutil.which("py")
    if not python:
        raise RuntimeError("Python Launcher is required to run compare_metrics.py")
    subprocess.run([python, "-3", str(RENDER / "compare_metrics.py"), str(candidate),
                    "--mask", str(mask), "--without-reflection", str(control), "--round", str(number),
                    "--parameters", json.dumps(state), "--change", json.dumps(change)], check=True)


def product_v2_preview():
    scene = bpy.context.scene
    devices = configure_cuda(scene)
    joints = scene_joints()
    set_pose(joints, HOME)
    refine_gripper()
    frame_home_from_tool_side(scene.camera)
    overview = scene.camera
    tool_frame = bpy.data.objects["gripper_base"].matrix_world
    detail = gripper_camera("Tool close-up", tool_frame, (.31, -.14, .51), 56)

    nodes = scene.world.node_tree.nodes
    background = nodes["Background"]
    env, = [node for node in nodes if node.type == "TEX_ENVIRONMENT"]
    color = background.inputs["Color"]
    surface = nodes["World Output"].inputs["Surface"]
    if (not env.image or not env.image.packed_file or not color.is_linked or not surface.is_linked
            or color.links[0].from_node != env or surface.links[0].from_node != background):
        raise ValueError("Open the packed HDRI product scene before running --product-v2-preview")
    background.inputs["Strength"].default_value = .95
    links = scene.world.node_tree.links
    contrast = nodes.new("ShaderNodeGamma")
    contrast.name = "HDRI separation"
    contrast.inputs["Gamma"].default_value = 1.12
    links.new(env.outputs["Color"], contrast.inputs["Color"])
    links.new(contrast.outputs[0], background.inputs["Color"])
    rays = nodes.new("ShaderNodeLightPath")
    sweep = nodes.new("ShaderNodeBackground")
    sweep.name = "Neutral camera backdrop"
    sweep.inputs["Color"].default_value = (.17, .17, .17, 1)
    mix = nodes.new("ShaderNodeMixShader")
    links.new(rays.outputs["Is Camera Ray"], mix.inputs[0])
    links.new(background.outputs[0], mix.inputs[1])
    links.new(sweep.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], nodes["World Output"].inputs["Surface"])
    cast = bpy.data.materials[FINISHES["cast"][0]]
    roughness = cast.node_tree.nodes["Principled BSDF"].inputs["Roughness"]
    decrease = .25 - roughness.default_value
    if roughness.is_linked:
        noise_range = roughness.links[0].from_node
        if noise_range.type != "MAP_RANGE":
            raise ValueError("Expected the cast material's procedural roughness range")
        for name in ("To Min", "To Max"):
            noise_range.inputs[name].default_value += decrease
    roughness.default_value = .25
    key = bpy.data.objects["Key softbox"].data
    key.size_y, key.energy = .36, 135
    area("Product reflection strip A", (-1.02, 1.07, 1.15), (.23, 0, .34), 24, .92, .075)
    area("Product reflection strip B", (-.95, -.75, 1.43), (.23, -.04, .34), 18, .85, .07)

    set_png(scene, 1600, 1200)
    scene.render.filepath = str(CHECKS / "product_v2_home.png")
    work = RENDER / "work" / "product_v2"
    work.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(work / "product_preview.blend"))
    bpy.ops.render.render(write_still=True)
    background.inputs["Strength"].default_value = 0
    scene.render.filepath = str(work / "home_without_hdri.png")
    bpy.ops.render.render(write_still=True)
    background.inputs["Strength"].default_value = .95
    scene.camera = detail
    set_png(scene, 960, 720)
    scene.render.filepath = str(CHECKS / "product_v2_tool.png")
    bpy.ops.render.render(write_still=True)
    report("product_v2_preview.json", {"device": devices, "samples": scene.cycles.samples,
           "world": env.image.name, "strength": .95, "hdri_gamma": 1.12, "cast_roughness": .25,
           "overview": overview.name, "detail": detail.name, "pad_thickness_mm": 14})


def stage_product_v2():
    scene = bpy.context.scene
    configure_cuda(scene)
    assert scene.cycles.samples == 128
    set_pose(scene_joints(), HOME)
    prepare_render_gripper(scene)
    soften_backdrop(bpy.data.objects["Seamless studio floor"], .78, .25)
    overview = scene.camera
    tool_frame = bpy.data.objects["gripper_base"].matrix_world
    scene.camera = gripper_camera("Tool close-up", tool_frame, (.30, 0, .51), 56)
    set_png(scene, 960, 720)
    scene.render.filepath = str(CHECKS / "product_v2_tool_final.png")
    bpy.ops.render.render(write_still=True)
    scene.camera = overview
    set_png(scene, 1600, 1200)
    scene.render.filepath = str(RENDER / "outputs" / "frames" / "pose_home.png")
    scene["product_revision"] = FINAL_REVISION
    folder = RENDER / "work" / "final_v2"
    folder.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / FINAL_SCENE.name))


def final_product_metrics():
    scene = bpy.context.scene
    require_final_scene(scene)
    scene_sha = sha256(FINAL_SCENE.read_bytes()).hexdigest()
    configure_cuda(scene)
    set_pose(scene_joints(), HOME)
    prepare_render_gripper(scene)
    folder = RENDER / "work" / "final_v2"
    folder.mkdir(parents=True, exist_ok=True)
    floor = bpy.data.objects["Seamless studio floor"]
    meshes = robot_meshes()
    python = ["py", "-3", str(RENDER / "compare_metrics.py")]
    angles = (0, 1.84, -2.02, -.40, -1.80, -2.40)
    for view, size in (("home", (1600, 1200)), ("reference_pose", (622, 636))):
        set_png(scene, *size)
        if view == "home":
            beauty = RENDER / "outputs" / "frames" / "pose_home.png"
        else:
            camera = reference_framing(scene)
            # This presentation pose aligns the tool with the reference and is separate from the CSV takes.
            set_pose(scene_joints(), angles)
            fit_overview(camera, robot_points(meshes), 311 / 318, margin=1.145)
            beauty = CHECKS / "final_v2_reference_view.png"
            scene.render.filepath = str(beauty)
            bpy.ops.render.render(write_still=True)
        mask = folder / f"{view}_mask.png"
        scene.render.film_transparent = True
        scene.render.image_settings.color_mode = "RGBA"
        floor.visible_camera = False
        scene.render.filepath = str(mask)
        bpy.ops.render.render(write_still=True)
        set_png(scene, *size)
        scene.render.film_transparent = False
        floor.visible_camera = True
        control = folder / f"{view}_without_reflection.png"
        visible = [obj.visible_glossy for obj in meshes]
        for obj in meshes:
            obj.visible_glossy = False
        scene.render.filepath = str(control)
        bpy.ops.render.render(write_still=True)
        for obj, previous in zip(meshes, visible, strict=True):
            obj.visible_glossy = previous
        subprocess.run([*python, str(beauty), "--final-view", view, "--mask", str(mask),
                        "--without-reflection", str(control), "--parameters",
                        json.dumps({"scene": FINAL_SCENE.name, "scene_sha256": scene_sha, "samples": scene.cycles.samples,
                                    "joint_angles_rad": HOME if view == "home" else angles})], check=True)
    subprocess.run([*python, str(beauty), "--publish"], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--reference-round", type=int, choices=range(1, min(8, len(REFERENCE_CHANGES)) + 1))
    modes.add_argument("--gripper-round", type=int, choices=range(1, len(GRIPPER_STUDIO_SETTINGS) + 1))
    modes.add_argument("--product-v2-preview", action="store_true")
    modes.add_argument("--finalize-product-v2", action="store_true")
    modes.add_argument("--final-v2-metrics", action="store_true")
    args = parser.parse_args(cli_args())
    if args.reference_round:
        reference_round(args.reference_round)
        return
    if args.product_v2_preview:
        product_v2_preview()
        return
    if args.finalize_product_v2:
        stage_product_v2()
        return
    if args.final_v2_metrics:
        final_product_metrics()
        return
    joints = scene_joints()
    if len(joints) != 6:
        raise ValueError("Open checks/imported_arm.blend before running setup_scene.py")
    scene = bpy.context.scene
    settings = GRIPPER_STUDIO_SETTINGS[(args.gripper_round or len(GRIPPER_STUDIO_SETTINGS)) - 1]
    gray, floor_roughness, cast_color_scale = settings
    devices = configure_cuda(scene)
    cycles = scene.cycles
    cycles.samples = 64
    cycles.use_denoising = True
    cycles.denoising_use_gpu = True
    cycles.use_adaptive_sampling = True
    cycles.adaptive_min_samples = 8
    cycles.adaptive_threshold = .06
    cycles.max_bounces = 5
    cycles.glossy_bounces = 4
    cycles.diffuse_bounces = 2
    scene.render.use_persistent_data = True
    scene.view_settings.view_transform = "AgX"
    scene.render.film_transparent = False
    world = bpy.data.worlds.new("Pale studio ambient")
    world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    background = nodes["Background"]
    background.inputs["Color"].default_value = (.78, .81, .86, 1)
    rays = nodes.new("ShaderNodeLightPath")
    intensity = nodes.new("ShaderNodeMapRange")
    intensity.inputs["To Min"].default_value = .32 * 1.10
    intensity.inputs["To Max"].default_value = .60
    links.new(rays.outputs["Is Glossy Ray"], intensity.inputs["Value"])
    links.new(intensity.outputs["Result"], background.inputs["Strength"])
    scene.world = world

    finishes = {key: material(*finish) for key, finish in FINISHES.items()}
    cast = finishes["cast"]
    finish_color = tuple(channel * cast_color_scale for channel in FINISHES["cast"][1]) + (1,)
    cast.diffuse_color = finish_color
    cast.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = finish_color
    turned = {key: finishes[key].copy() for key in ("steel", "graphite")}
    for key, mat in turned.items():
        mat.name = f"Turned {key} · concentric finish"
        metal_finish(mat, FINISHES[key][3], turned=True)
    for key in ("cast", "steel"):
        metal_finish(finishes[key], FINISHES[key][3])
    refine_assembly()
    refine_gripper()
    meshes = robot_meshes()
    for obj in meshes:
        if not obj.data.materials:
            obj.data.materials.append(finishes["cast"])
        slot = obj.material_slots[0]
        slot.link = "OBJECT"
        finish = obj["finish"]
        is_turned = obj.get("turned", False) or obj.data.name in {"steel_disc", "graphite_disc"}
        slot.material = turned[finish] if is_turned else finishes[finish]
    base_z = min(point.z for point in robot_points(meshes))
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, base_z - .00005))
    floor = bpy.context.object
    floor.name = "Seamless studio floor"
    floor.data.materials.append(material("Neutral studio floor",
                                         (gray, gray * .67 / .66, gray * .69 / .66), 0, floor_roughness))
    # Keep the bright sweep in camera while giving horizontal metal surfaces a darker reflection.
    floor.visible_glossy = False
    area("Key softbox", (.15, -1.65, 2.65), (.4, 0, .35), 320, 2.3, 1.4)
    area("Fill softbox", (2.2, -.4, 1.35), (.4, 0, .35), 130, 1.6, 2.0)
    area("Rim strip", (-.35, 1.9, 1.55), (.35, 0, .35), 310, 2.4, .44)
    area("Machined face strip", (1.6, 1.5, .64), (.55, 0, .25), 35, .40, 1.9)
    scene.camera = camera_at("Overview 45°", (1.65, -2.45, 3), (0, 0, 0))
    frame_home_from_tool_side(scene.camera)
    elbow = joints["joint_3"].child.matrix_world.translation
    camera_at("Elbow close-up", elbow + Vector((.23, .62, .30)), elbow, 66)
    tool_frame = bpy.data.objects["gripper_base"].matrix_world
    tool_camera = gripper_camera("Tool close-up", tool_frame, (.25, -.105, .54), 59)
    gripper_camera("Guide and jaws", tool_frame, (.27, -.08, .52), 65)
    base = Vector((0, 0, .088))
    camera_at("Base close-up", base + Vector((.48, -.44, .34)), base, 49)
    if args.gripper_round:
        set_png(scene, 1600, 1200)
        render_gripper_views(args.gripper_round, scene.camera, tool_camera, settings)
        return
    set_png(scene, 720, 540)
    scene.render.filepath = str(CHECKS / "studio_home.png")
    start = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    elapsed = time.perf_counter() - start
    bpy.ops.wm.save_as_mainfile(filepath=str(CHECKS / "studio.blend"))
    set_png(scene, 960, 720)
    for name, filename in (("Elbow close-up", "elbow_detail.png"), ("Tool close-up", "tool_detail.png"),
                           ("Base close-up", "base_detail.png"), ("Guide and jaws", "jaw_detail.png")):
        scene.camera = bpy.data.objects[name]
        scene.render.filepath = str(CHECKS / filename)
        bpy.ops.render.render(write_still=True)
    report("02_scene.json", {"blender": bpy.app.version_string, "engine": "Cycles", "backend": "CUDA",
                             "gpu": devices, "samples": cycles.samples, "denoise": cycles.use_denoising,
                             "gpu_denoise": cycles.denoising_use_gpu, "denoiser": cycles.denoiser,
                             "adaptive_threshold": cycles.adaptive_threshold, "preview_seconds": elapsed,
                             "materials": FINISHES, "brushed_roughness_variation": BRUSH_ROUGHNESS,
                             "turned_roughness_variation": TURNED_ROUGHNESS,
                             "cameras": [obj.name for obj in scene.objects if obj.type == "CAMERA"]})


if __name__ == "__main__":
    main()
