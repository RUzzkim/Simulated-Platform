"""Refine the saved studio through HDRI, finishes, contact AO, and microtexture."""

import argparse
import json
from math import radians
from pathlib import Path
import subprocess
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_scene import CHECKS, RENDER, cli_args, configure_cuda, prepare_render_gripper, reference_framing, robot_meshes, set_png, soften_backdrop


HDRI = RENDER / "assets" / "studio_small_09_4k.hdr"
STAGES = ("hdri", "metal", "ao", "micro")
FINISH = {
    "cast": (.9, .30, .4),
    "graphite": (.85, .45, .28),
    "steel": (1, .20, .35),
    "cover": (.85, .39, .36),
    "rubber": (0, .70, 0),
}


def use_hdri(scene, strength, heading):
    # The texture responds to all illumination and reflection rays.
    world = bpy.data.worlds.new("Poly Haven Studio Small 09")
    world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    coords = nodes.new("ShaderNodeTexCoord")
    turn = nodes.new("ShaderNodeVectorRotate")
    turn.rotation_type = "Z_AXIS"
    turn.inputs["Angle"].default_value = radians(heading)
    env = nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(str(HDRI), check_existing=True)
    if not env.image.packed_file:
        env.image.pack()
    links.new(coords.outputs["Normal"], turn.inputs["Vector"])
    links.new(turn.outputs["Vector"], env.inputs["Vector"])
    background = nodes["Background"]
    links.new(env.outputs["Color"], background.inputs["Color"])
    background.inputs["Strength"].default_value = strength
    scene.world = world


def apply_finish(mat, finish):
    metallic, rough, anisotropic = FINISH[finish]
    tree = mat.node_tree
    shader = tree.nodes["Principled BSDF"]
    for link in tuple(shader.inputs["Roughness"].links):
        tree.links.remove(link)
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = rough
    shader.inputs["Anisotropic"].default_value = anisotropic
    return shader


def add_contact_ao(mat, shader):
    tree = mat.node_tree
    ao = tree.nodes.new("ShaderNodeAmbientOcclusion")
    ao.name = "Close-contact AO"
    ao.samples = 3
    ao.inputs["Distance"].default_value = .023
    blend = tree.nodes.new("ShaderNodeMixRGB")
    blend.blend_type = "MULTIPLY"
    blend.inputs[0].default_value = .5
    blend.inputs[1].default_value = shader.inputs["Base Color"].default_value
    tree.links.new(ao.outputs["AO"], blend.inputs[2])
    tree.links.new(blend.outputs[0], shader.inputs["Base Color"])
    shader.inputs["Specular Tint"].default_value = (.96, .98, 1, 1)


def add_microfinish(mat, shader, finish):
    tree = mat.node_tree
    nodes, links = tree.nodes, tree.links
    coords = nodes.new("ShaderNodeTexCoord")
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 115
    noise.inputs["Detail"].default_value = 2
    if finish == "cover":
        stretch = nodes.new("ShaderNodeVectorMath")
        stretch.operation = "MULTIPLY"
        stretch.inputs[1].default_value = (.08, 2.6, 2.6)
        links.new(coords.outputs["Generated"], stretch.inputs[0])
        links.new(stretch.outputs["Vector"], noise.inputs["Vector"])
    else:
        links.new(coords.outputs["Generated"], noise.inputs["Vector"])
    remap = nodes.new("ShaderNodeMapRange")
    baseline = FINISH[finish][1]
    amplitude = .04 if finish == "cover" else .026
    remap.inputs["To Min"].default_value = baseline - amplitude
    remap.inputs["To Max"].default_value = baseline + amplitude
    links.new(noise.outputs["Fac"], remap.inputs["Value"])
    links.new(remap.outputs["Result"], shader.inputs["Roughness"])


def render_image(scene, path):
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=STAGES)
    parser.add_argument("--round", type=int, required=True, choices=range(1, 9))
    parser.add_argument("--floor-gray", type=float, required=True)
    parser.add_argument("--strength", type=float, default=.8)
    parser.add_argument("--heading", type=float, default=35)
    parser.add_argument("--backdrop-mix", type=float, default=0)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--save-final", action="store_true")
    args = parser.parse_args(cli_args())
    scene = bpy.context.scene
    configure_cuda(scene)
    prepare_render_gripper(scene)
    if not .6 <= args.strength <= 1:
        parser.error("HDRI strength must be between 0.6 and 1.0")
    use_hdri(scene, args.strength, args.heading)
    floor = bpy.data.objects["Seamless studio floor"]
    floor.active_material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (
        args.floor_gray, args.floor_gray, args.floor_gray, 1)
    if args.backdrop_mix:
        soften_backdrop(floor, args.backdrop_mix)
    index = STAGES.index(args.stage)
    if index >= 1:
        for mat, finish in {obj.active_material: obj["finish"] for obj in robot_meshes()}.items():
            shader = apply_finish(mat, finish)
            if index >= 2 and finish != "rubber":
                add_contact_ao(mat, shader)
            if index >= 3 and finish in {"cast", "graphite", "cover"}:
                add_microfinish(mat, shader, finish)
    scene.cycles.samples = 128
    scene.cycles.adaptive_threshold = .075
    set_png(scene, 960, 720)
    shot = CHECKS / f"product_home_{args.round:02d}_{args.stage}.png"
    render_image(scene, shot)
    if args.save_final:
        bpy.ops.wm.save_as_mainfile(filepath=str(CHECKS / "product_final.blend"))
    work = RENDER / "work" / "product"
    work.mkdir(parents=True, exist_ok=True)
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = True
    floor.visible_camera = False
    mask = work / "home_mask.png"
    render_image(scene, mask)
    parameters = {"hdri": HDRI.name, "strength": args.strength, "heading_deg": args.heading,
                  "floor_gray": args.floor_gray, "backdrop_mix": args.backdrop_mix, "samples": scene.cycles.samples}
    if index >= 1:
        parameters["metallic_roughness_anisotropic"] = FINISH
    if index >= 2:
        parameters["ao_mix"] = .5
    if index >= 3:
        parameters["micro_noise_scale"] = 115
    subprocess.run(["py", "-3", str(RENDER / "compare_metrics.py"), str(shot), "--mask", str(mask),
                    "--round", str(args.round), "--product-stage", args.stage, "--previous", str(args.previous),
                    "--parameters", json.dumps(parameters)], check=True)
    if args.save_final:
        floor.visible_camera = True
        scene.render.film_transparent = False
        reference_framing(scene)
        set_png(scene, 622, 636)
        plate = CHECKS / "product_reference_view.png"
        render_image(scene, plate)
        subprocess.run(["py", "-3", str(RENDER / "compare_metrics.py"), str(plate), "--publish"], check=True)


if __name__ == "__main__":
    main()
