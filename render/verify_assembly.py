"""Check the modeled mating interfaces over the recorded joint-angle envelope."""

from hashlib import sha256
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_urdf import EndEffector, HOME, URDF, pose_error, scene_joints, set_pose
from render_stills import still_poses
from setup_scene import fit_overview, report, robot_meshes, robot_points, set_png
from trajectory_data import HANDLING, TRAJECTORIES, lock_event, read_samples, retime


def mesh_tree(obj):
    return BVHTree.FromPolygons([obj.matrix_world @ vertex.co for vertex in obj.data.vertices],
                                [tuple(face.vertices) for face in obj.data.polygons])


def by_prefix(*prefixes):
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.name.startswith(prefixes)]


def check_gripper_interfaces():
    gripper = bpy.data.objects["gripper_base"]
    inverse = gripper.matrix_world.inverted()
    fixed = by_prefix("Enclosed gripper drive", "Linear jaw guide ", "Guide cover fastener ")
    pads = []
    jaws = []
    minimum_rail_clearance = float("inf")
    rail_top = max((inverse @ obj.matrix_world @ v.co).z
                   for obj in by_prefix("Linear jaw guide ") for v in obj.data.vertices)
    for name in ("finger_left", "finger_right"):
        jaw = bpy.data.objects[f"{name} machined jaw"]
        pad, = (obj for obj in jaw.parent.children if obj.get("finish") == "rubber")
        jaw_tree, pad_tree = mesh_tree(jaw), mesh_tree(pad)
        assert not jaw_tree.overlap(pad_tree), f"{name} pad crosses its jaw"
        for obj in fixed:
            other = mesh_tree(obj)
            assert not (jaw_tree.overlap(other) or pad_tree.overlap(other)), f"{name} crosses {obj.name}"
        jaw_bottom = min((inverse @ jaw.matrix_world @ v.co).z for v in jaw.data.vertices)
        minimum_rail_clearance = min(minimum_rail_clearance, jaw_bottom - rail_top)
        points = [inverse @ pad.matrix_world @ v.co for v in pad.data.vertices]
        pads.append([(min(v[i] for v in points), max(v[i] for v in points)) for i in range(3)])
        jaws.extend((jaw_tree, pad_tree))
    negative, positive = sorted(pads, key=lambda bounds: bounds[1][0])
    assert minimum_rail_clearance > .00025
    for axis in (0, 2):
        assert all(abs(a - b) < 1e-6 for a, b in zip(negative[axis], positive[axis]))
    assert all(abs(a + b) < 1e-6 for a, b in zip(negative[1], reversed(positive[1])))
    assert not any(a.overlap(b) for a in jaws[:2] for b in jaws[2:])
    gap = positive[1][0] - negative[1][1]
    assert gap > 0
    return {"coaxial_opposed_faces": True, "mesh_overlap": False, "open_gap_mm": gap * 1000,
            "minimum_rail_clearance_mm": minimum_rail_clearance * 1000,
            "pad_thickness_mm": (negative[1][1] - negative[1][0]) * 1000}


def check_full_clips(joints, tracks):
    scene = bpy.context.scene
    camera = scene.camera
    set_png(scene, 1920, 1080)
    meshes = robot_meshes()
    floor = bpy.data.objects["Seamless studio floor"].location.z
    moving_meshes = [obj for obj in meshes if obj.parent.name != "base_link"]
    points = []
    min_clearance = float("inf")
    lock_time, lock_angle = lock_event()
    shoulder = joints["joint_2"]
    inverse_origin = shoulder.origin.inverted()
    locked_frames = []
    max_angle_error = 0.0
    for name, rows in tracks.items():
        for frame, sample in enumerate(rows, 1):
            set_pose(joints, sample.angles)
            points.extend(robot_points(meshes))
            min_clearance = min(min_clearance, min(p.z for p in robot_points(moving_meshes)) - floor)
            if name == "lock_event":
                delta = (inverse_origin @ shoulder.child.matrix_basis).to_quaternion()
                # Use the quaternion components directly to preserve near-zero angles.
                component = delta.x * shoulder.axis.x + delta.y * shoulder.axis.y + delta.z * shoulder.axis.z
                angle = math.remainder(2 * math.atan2(component, delta.w), 2 * math.pi)
                max_angle_error = max(max_angle_error, abs(angle - sample.angles[1]))
                if sample.time >= lock_time:
                    locked_frames.append((frame, angle))
    fit_overview(camera, points, 1920 / 1080, margin=1.12)
    bpy.context.view_layer.update()
    view = camera.data.view_frame(scene=scene)
    inverse = camera.matrix_world.inverted()
    projected = [inverse @ p for p in points]
    margins = {}
    for axis, labels in enumerate((("left", "right"), ("bottom", "top"))):
        low, high = min(p[axis] for p in view), max(p[axis] for p in view)
        margins[labels[0]] = (min(p[axis] for p in projected) - low) / (high - low)
        margins[labels[1]] = (high - max(p[axis] for p in projected)) / (high - low)
    assert min(margins.values()) > .04 and min_clearance > 0
    report("04_framing.json", {"frames": sum(map(len, tracks.values())), "minimum_fractional_image_margins": margins,
                               "minimum_bounding_box_clearance_for_moving_links_m": min_clearance})
    first_frame, first_angle = locked_frames[0]
    drift = max(abs(angle - first_angle) for _, angle in locked_frames)
    assert max_angle_error < 1e-6 and drift < 1e-6 and abs(first_angle - lock_angle) < 1e-6
    report("final_v2_lock_joint_matrices.json", {
        "scene_sha256": sha256(Path(bpy.data.filepath).read_bytes()).hexdigest(),
        "frames_checked": len(tracks["lock_event"]), "first_lock_frame_one_based": first_frame,
        "locked_frames_checked": len(locked_frames), "lock_csv_angle_rad": lock_angle,
        "lock_blender_angle_rad": first_angle, "joint_2_blender_lock_drift_rad": drift,
        "max_joint_2_angle_error_rad": max_angle_error,
    })


def main():
    joints = scene_joints()
    reference = EndEffector(URDF)
    tracks = [read_samples(path) for path in (HANDLING, *TRAJECTORIES.values())]
    samples = [sample.angles for track in tracks for sample in track]
    checks = (
        ("base_swivel", 0, by_prefix("Fixed swivel dust seal", "Recessed anchor head", "Anchor washer"),
         by_prefix("link_1 · 00", "link_1 · 01", "link_1 · 02", "link_1 · 04")),
        ("shoulder", 1, by_prefix("link_1 · 00", "link_1 · 01", "link_1 · 02", "link_1 · 04", "Shoulder pin"),
         by_prefix("Shoulder rotating bearing", "Upper arm with elbow fork")),
        ("elbow", 2, by_prefix("Elbow fixed cheek", "Elbow fixed shaft", "Upper arm with elbow fork"),
         by_prefix("Elbow rotating bearing", "Forearm clear")),
        ("wrist_roll", 3, by_prefix("Wrist roll fixed collar", "Wrist roll pin", "Forearm clear"),
         by_prefix("Wrist yoke rear", "Wrist yoke cheek")),
        ("wrist_pitch", 4, by_prefix("Wrist yoke rear", "Wrist yoke cheek", "Wrist pitch pin"),
         by_prefix("Wrist pitch rotating bearing", "Wrist output casing")),
        ("tool_flange", 5, by_prefix("Wrist output casing"),
         by_prefix("link_6 ·", "Enclosed gripper drive")),
    )
    result = {"source_samples": len(samples), "interfaces": {}, "render_poses": {}}
    for name, axis, fixed, moving in checks:
        low, high = min(row[axis] for row in samples), max(row[axis] for row in samples)
        assert fixed and moving, f"Missing assembly parts for {name}"
        overlaps = []
        for step in range(25):
            angles = list(HOME)
            angles[axis] = low + (high - low) * step / 24
            set_pose(joints, angles)
            fixed_trees = {obj.name: mesh_tree(obj) for obj in fixed}
            for obj in moving:
                tree = mesh_tree(obj)
                for other, fixed_tree in fixed_trees.items():
                    if tree.overlap(fixed_tree):
                        overlaps.append({"angle_rad": angles[axis], "fixed": other, "moving": obj.name})
        result["interfaces"][name] = {"joint": axis + 1, "min_rad": low, "max_rad": high,
                                      "sample_count": 25, "intersections": overlaps}
    for name, (_, sample) in still_poses().items():
        set_pose(joints, sample.angles)
        result["render_poses"][name] = pose_error(sample.angles, reference)
        if "product_revision" in bpy.context.scene:
            result["render_poses"][name]["gripper"] = check_gripper_interfaces()
    gripper = bpy.data.objects["gripper_base"]
    fingers = [gripper.matrix_world.inverted() @ bpy.data.objects[name].matrix_world
               for name in ("finger_left", "finger_right")]
    assert (fingers[0].to_3x3().col[2] - fingers[1].to_3x3().col[2]).length < 1e-6
    assert abs(fingers[0].translation.z - fingers[1].translation.z) < 1e-6
    result["jaw_origin_span_m"] = abs(fingers[1].translation.y - fingers[0].translation.y)
    report("assembly_geometry.json", result)
    counts = {name: len(value["intersections"]) for name, value in result["interfaces"].items()}
    print(json.dumps(counts))
    if any(counts.values()):
        raise ValueError(f"Intersecting mechanical interfaces: {counts}")
    check_full_clips(joints, {name: retime(track) for name, track in zip(TRAJECTORIES, tracks[1:], strict=True)})


if __name__ == "__main__":
    main()
