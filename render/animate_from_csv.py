"""Render a 300-frame, 10-second Cycles clip from each recorded trajectory."""

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_urdf import EndEffector, RENDER, URDF, cli_args, pose_error, scene_joints, set_pose
from setup_scene import CHECKS, configure_cuda, fit_overview, prepare_render_gripper, report, require_final_scene, robot_meshes, robot_points, set_png
from trajectory_data import FPS, FRAME_COUNT, REPO, TRAJECTORIES, lock_event, read_samples, retime


TEST_FRAME = 61
AUDIT_FRAMES = (16, 85, 270)
WIDTH, HEIGHT = 1920, 1080


def render_png(scene, path):
    draft = path.with_stem(path.stem + ".partial")
    scene.render.filepath = str(draft)
    bpy.ops.render.render(write_still=True)
    draft.replace(path)


def verify_lock(rows):
    lock_time, lock_angle = lock_event()
    post_lock = [row for row in rows if row.time >= lock_time]
    deviation = max(abs(row.angles[1] - lock_angle) for row in post_lock)
    if deviation > 1e-6 or max(row.angles[0] for row in post_lock) - min(row.angles[0] for row in post_lock) < .1:
        raise ValueError("Shoulder-lock track does not show a stationary shoulder and moving base")
    return {"lock_source_time_s": lock_time, "lock_joint_2_rad": lock_angle, "max_lock_deviation_rad": deviation}


def joint_rotations(joints, angles):
    """Measure signed angle from each Blender parent-local matrix on its URDF axis."""
    results = []
    for joint, target in zip(joints.values(), angles, strict=True):
        delta = (joint.origin.inverted() @ joint.child.matrix_basis).to_quaternion()
        signed = 2 * math.atan2(delta.axis.dot(joint.axis) * math.sin(delta.angle / 2), math.cos(delta.angle / 2))
        signed = math.remainder(signed, 2 * math.pi)
        if abs(math.remainder(signed - target, 2 * math.pi)) > 3e-5:
            raise ValueError(f"Incorrect sign or angle for {joint.name}: {signed} vs {target}")
        results.append(signed)
    return results


def audit_frame(joints, arm, sample, previous):
    set_pose(joints, previous.angles)
    start = joint_rotations(joints, previous.angles)
    set_pose(joints, sample.angles)
    measured = joint_rotations(joints, sample.angles)
    csv_change = [x - y for x, y in zip(sample.angles, previous.angles, strict=True)]
    measured_change = [math.remainder(x - y, 2 * math.pi) for x, y in zip(measured, start, strict=True)]
    if any(a * b <= 0 for a, b in zip(csv_change, measured_change, strict=True) if abs(a) > 1e-4):
        raise ValueError("Blender movement direction differs from CSV")
    return {**asdict(sample), "blender_angles_rad": measured, "csv_motion_rad": csv_change,
            "blender_motion_rad": measured_change, **pose_error(sample.angles, arm)}


def encode(name, sequence, elapsed):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg and ffprobe must be available in PATH")
    output = RENDER / "outputs" / "animations"
    output.mkdir(parents=True, exist_ok=True)
    mp4 = output / f"{name}.mp4"
    draft = mp4.with_stem(mp4.stem + ".partial")
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(FPS),
                    "-start_number", "1", "-i", str(sequence / "frame_%04d.png"), "-frames:v", str(FRAME_COUNT),
                    "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(draft)], check=True)
    info = json.loads(subprocess.check_output([ffprobe, "-v", "error", "-select_streams", "v:0",
                                              "-show_streams", "-of", "json", str(draft)], text=True))["streams"][0]
    assert (int(info["nb_frames"]), float(info["duration"]), info["width"], info["height"], info["r_frame_rate"]) == (
        FRAME_COUNT, 10.0, WIDTH, HEIGHT, f"{FPS}/1")
    draft.replace(mp4)
    for frame in AUDIT_FRAMES:
        image = CHECKS / f"{name}_{frame:03d}.png"
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp4), "-vf",
                        f"select=eq(n\\,{frame - 1}),scale=960:-1", "-frames:v", "1", str(image)], check=True)
    return {"video": mp4.relative_to(REPO).as_posix(), "render_and_encode_seconds": time.perf_counter() - elapsed,
            "codec": info["codec_name"], "width": WIDTH, "height": HEIGHT, "frames": FRAME_COUNT,
            "duration": 10, "fps": FPS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--clips", nargs="+", choices=TRAJECTORIES, default=list(TRAJECTORIES))
    args = parser.parse_args(cli_args())
    scene = bpy.context.scene
    require_final_scene(scene)
    scene_bytes = Path(bpy.data.filepath).read_bytes()
    scene_sha = sha256(scene_bytes).hexdigest()
    preview = CHECKS / "04_motion_preview.json"
    prior = json.loads(preview.read_text(encoding="utf-8")) if preview.exists() else {}
    if not args.preview and any(prior.get(name, {}).get("scene_sha256") != scene_sha for name in args.clips):
        raise ValueError("Run --preview on the finalized scene and review the test images before the full render")
    configure_cuda(scene)
    prepare_render_gripper(scene)
    scene.render.fps = FPS
    joints = scene_joints()
    joints = {f"joint_{n}": joints[f"joint_{n}"] for n in range(1, 7)}
    arm = EndEffector(URDF)
    raw = {name: read_samples(path) for name, path in TRAJECTORIES.items()}
    if any(len(rows) != 800 for rows in raw.values()):
        raise ValueError("Expected two recorded 800-frame tracks")
    tracks = {name: retime(rows) for name, rows in raw.items()}
    meshes = robot_meshes()
    points = []
    for rows in tracks.values():
        for row in rows:
            set_pose(joints, row.angles)
            points.extend(robot_points(meshes))
    fit_overview(scene.camera, points, WIDTH / HEIGHT, margin=1.12)
    width, height = (960, 540) if args.preview else (WIDTH, HEIGHT)
    set_png(scene, width, height)
    metadata = {}
    for name in args.clips:
        start = time.perf_counter()
        rows = tracks[name]
        frames = (TEST_FRAME,) if args.preview else AUDIT_FRAMES
        metadata[name] = {"source": TRAJECTORIES[name].relative_to(REPO).as_posix(), "source_rows": len(raw[name]),
                          "scene_sha256": scene_sha,
                          "camera": scene.camera.name, "samples": scene.cycles.samples,
                          "audit": {str(n): audit_frame(joints, arm, rows[n - 1], rows[n - 2]) for n in frames}}
        if name == "lock_event":
            metadata[name].update(verify_lock(raw[name]))
        if args.preview:
            path = CHECKS / f"motion_test_{name}.png"
            render_png(scene, path)
            metadata[name]["test_image"] = path.relative_to(REPO).as_posix()
            continue
        # Keep frames reusable after interruption, but never reuse frames from a different scene or track.
        cache_key = sha256(scene_bytes + TRAJECTORIES[name].read_bytes()
                           + URDF.read_bytes() + Path(__file__).read_bytes()).hexdigest()[:16]
        sequence = RENDER / "work" / cache_key / name
        sequence.mkdir(parents=True, exist_ok=True)
        for frame, row in enumerate(rows, 1):
            path = sequence / f"frame_{frame:04d}.png"
            if path.exists():
                continue
            set_pose(joints, row.angles)
            pose_error(row.angles, arm)
            render_png(scene, path)
            print(f"PROGRESS {name} {frame}/{FRAME_COUNT} wall={time.perf_counter() - start:.1f}s", flush=True)
        metadata[name].update(encode(name, sequence, start))
        report(f"04_{name}.json", metadata[name])
    if args.preview:
        report(preview.name, {**prior, **metadata})


if __name__ == "__main__":
    main()
