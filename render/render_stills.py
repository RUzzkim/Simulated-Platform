"""Render HOME, the deepest recorded elbow bend, and a post-lock pose."""

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys
import time

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_urdf import EndEffector, HOME, RENDER, URDF, cli_args, pose_error, scene_joints, set_pose
from setup_scene import CHECKS, configure_cuda, fit_overview, prepare_render_gripper, report, require_final_scene, robot_meshes, robot_points, set_png
from trajectory_data import HANDLING, REPO, TRAJECTORIES, lock_event, read_samples


def still_poses():
    handling = read_samples(HANDLING)
    home = min(handling, key=lambda row: math.dist(row.angles, HOME))
    if math.dist(home.angles, HOME) > 1e-6:
        raise ValueError("An exact recorded HOME sample is required")
    elbow = min(handling, key=lambda row: abs(abs(row.angles[2]) - math.pi / 2))
    lock_source = TRAJECTORIES["lock_event"]
    lock_time, lock_angle = lock_event()
    locked = min((row for row in read_samples(lock_source) if row.time >= lock_time),
                 key=lambda row: abs(row.time - 1.5))
    if not math.isclose(locked.angles[1], lock_angle, abs_tol=1e-6):
        raise ValueError("Selected pose does not hold the locked shoulder position")
    return {"home": (HANDLING, home), "elbow_bent": (HANDLING, elbow), "shoulder_lock": (lock_source, locked)}


def main():
    poses = still_poses()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poses", nargs="+", choices=poses, default=list(poses))
    parser.add_argument("--samples", type=int)
    args = parser.parse_args(cli_args())
    scene = bpy.context.scene
    require_final_scene(scene)
    configure_cuda(scene)
    prepare_render_gripper(scene)
    if args.samples is not None:
        scene.cycles.samples = args.samples
    set_png(scene, 1600, 1200)
    joints = scene_joints()
    arm = EndEffector(URDF)
    meshes = robot_meshes()
    output = RENDER / "outputs" / "frames"
    output.mkdir(parents=True, exist_ok=True)
    manifest = CHECKS / "03_stills.json"
    previous = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
    for name in args.poses:
        source, sample = poses[name]
        set_pose(joints, sample.angles)
        error = pose_error(sample.angles, arm)
        fit_overview(scene.camera, robot_points(meshes), 4 / 3)
        scene.render.filepath = str(output / f"pose_{name}.png")
        start = time.perf_counter()
        bpy.ops.render.render(write_still=True)
        previous[name] = {"source": source.relative_to(REPO).as_posix(), **asdict(sample), **error,
                          "joint_3_degrees": math.degrees(sample.angles[2]),
                          "image": Path(scene.render.filepath).relative_to(REPO).as_posix(),
                          "samples": scene.cycles.samples, "seconds": time.perf_counter() - start}
        report(manifest.name, previous)


if __name__ == "__main__":
    main()
