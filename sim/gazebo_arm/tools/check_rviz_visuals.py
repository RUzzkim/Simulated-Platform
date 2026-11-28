"""Check staged RViz visual meshes against the fixed kinematic model and recorded motion."""

import argparse
from collections import Counter
import csv
from itertools import combinations
import json
import math
from pathlib import Path
import sys
from urllib.parse import urlsplit
from urllib.request import url2pathname
import xml.etree.ElementTree as ET

from mathutils import Euler, Matrix, Vector
from mathutils.bvhtree import BVHTree


PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[1]
HOME = [0, .35, -.72, .20, 0, 0]
JOINT_NAMES = tuple(f"joint_{n}" for n in range(1, 7))


def transform(element):
    props = {} if element is None else element.attrib
    xyz = tuple(map(float, props.get("xyz", "0 0 0").split()))
    rpy = tuple(map(float, props.get("rpy", "0 0 0").split()))
    return Matrix.Translation(xyz) @ Euler(rpy, "XYZ").to_matrix().to_4x4()


def transforms(root, angles):
    frames = {"base_link": Matrix.Identity(4)}
    remaining = root.findall("joint")
    while remaining:
        for element in remaining[:]:
            parent = element.find("parent").get("link")
            if parent not in frames:
                continue
            child = element.find("child").get("link")
            name = element.get("name")
            rotation = Matrix.Rotation(angles[JOINT_NAMES.index(name)], 4, "Z") if name in JOINT_NAMES else Matrix.Identity(4)
            frames[child] = frames[parent] @ transform(element.find("origin")) @ rotation
            remaining.remove(element)
    return frames


def asset(uri, folder):
    if uri.startswith("file:"):
        return Path(url2pathname(urlsplit(uri).path))
    relative = uri.removeprefix("package://gazebo_arm/")
    staged = folder / Path(relative).name
    return staged if staged.is_file() else PACKAGE / relative


def geometry(path):
    mesh = ET.parse(path).getroot()
    coords = map(float, mesh.find(".//{*}float_array[@id='positions-array']").text.split())
    points = list(zip(coords, coords, coords))
    indices = iter(map(int, mesh.find(".//{*}triangles/{*}p").text.split()[::2]))
    faces = list(zip(indices, indices, indices))
    return points, faces


def components(stage):
    parts = json.loads((stage/"candidate_components.json").read_text(encoding="utf-8"))
    result = {p["name"]: (p["link"], [Vector(v) for v in p["points"]],
                         [tuple(c[0] for c in face) for face in p["faces"]]) for p in parts}
    for link in ET.parse(stage/"candidate_extras.xml").getroot().findall("link"):
        for visual in link.findall("visual"):
            shape = visual.find("geometry/mesh")
            coords, faces = geometry(asset(shape.get("filename"), stage/"assets"))
            scale = Vector(tuple(map(float, shape.get("scale", "1 1 1").split())))
            frame = transform(visual.find("origin"))
            points = [frame @ Vector(tuple(p*s for p,s in zip(v,scale,strict=True))) for v in coords]
            result[visual.get("name")] = (link.get("name"), points, faces)
    return result


def positioned(parts, frames):
    return {name: [frames[link] @ p for p in points] for name, (link, points, _) in parts.items()}


def collisions(parts, frames):
    points = positioned(parts, frames)
    boxes = {name: [(min(p[a] for p in vertices), max(p[a] for p in vertices)) for a in range(3)]
             for name, vertices in points.items()}
    trees = {}
    for left, right in combinations(parts, 2):
        if not all(a[0] < b[1] and b[0] < a[1] for a,b in zip(boxes[left], boxes[right])):
            continue
        for name in (left, right):
            if name not in trees:
                trees[name] = BVHTree.FromPolygons(points[name], parts[name][2], all_triangles=True)
        if trees[left].overlap(trees[right]):
            yield left, right


def recorded_poses(elbow_csv):
    runs = REPO/"member-a-delivery"
    sources = [runs/"handling-no-fault.csv", *sorted((runs/"runs-dh-verified").glob("*/states.csv")), elbow_csv]
    poses, all_angles = [HOME], []
    for path in sources:
        with path.open(newline="", encoding="utf-8-sig") as stream:
            angles = [[float(row[f"{j}_position_rad"]) for j in JOINT_NAMES] for row in csv.DictReader(stream)]
        poses.extend(angles[int(i*(len(angles)-1)/18)] for i in range(19))
        poses.append(min(angles, key=lambda q:q[2]))
        all_angles.extend(angles)
    for axis in range(6):
        low, high = min(row[axis] for row in all_angles), max(row[axis] for row in all_angles)
        for i in range(5):
            pose = HOME.copy()
            pose[axis] = low+i*(high-low)/4
            poses.append(pose)
    assert len(poses) == 111
    return poses


def interface_clearances(parts, frames):
    points = positioned(parts, frames)
    checks = (
        ("joint_1", "joint_1_axis", "base_register", "turret_register", "swivel"),
        ("joint_2_l", "joint_2_axis", "link_1 · 02 shoulder_cheek", "shoulder_rotor_end_-1", "rviz_fit_shoulder_l"),
        ("joint_2_r", "joint_2_axis", "shoulder_rotor_end_+1", "link_1 · 04 shoulder_cheek", "rviz_fit_shoulder_r"),
        ("joint_3_l", "joint_3_axis", "Elbow fixed cheek -1", "rviz_fit_forearm_eye", "rviz_fit_elbow_l"),
        ("joint_3_r", "joint_3_axis", "rviz_fit_forearm_eye", "Elbow fixed cheek +1", "rviz_fit_elbow_r"),
        ("joint_4", "joint_4_axis", "rviz_fit_forearm_eye", "Wrist yoke rear flange", "rviz_fit_wrist_roll"),
        ("joint_5_l", "joint_5_axis", "Wrist yoke cheek -1", "rviz_fit_wrist_eye", "rviz_fit_wrist_pitch_l"),
        ("joint_5_r", "joint_5_axis", "rviz_fit_wrist_eye", "Wrist yoke cheek +1", "rviz_fit_wrist_pitch_r"),
        ("joint_6", "link_6", "rviz_fit_wrist_eye", "link_6 · 01 graphite_disc", "rviz_fit_tool_roll"),
    )
    report = {}
    for name, frame, housing0, housing1, prefix in checks:
        local = frames[frame].inverted()

        def span(part):
            coords = [local @ vertex for vertex in points[part]]
            if name.startswith("joint_3") and part == "rviz_fit_forearm_eye":
                coords = [p for p in coords if math.hypot(p.x, p.y) < .080]
            return min(p.z for p in coords), max(p.z for p in coords)

        _, left = span(housing0)
        right, _ = span(housing1)
        race0, race1 = f"{prefix}_race_0", f"{prefix}_race_1"
        first, first_end = span(race0)
        second_start, second = span(race1)
        gap = 1000*(right-left)
        seams = [1000*(first-left), 1000*(right-second)]
        assert gap >= (3.999 if name.startswith("joint_2") else 2.95), (name, gap)
        assert all(.5 <= clearance <= 1 for clearance in seams), (name, seams)
        radial = {}
        for part in (race0, race1, f"{prefix}_shaft"):
            coords = [local @ vertex for vertex in points[part]]
            errors = []
            for i in range(24):
                angle = math.tau*i/24
                projections = [p.x*math.cos(angle)+p.y*math.sin(angle) for p in coords]
                errors.append(abs(max(projections)+min(projections))*1000)
            radial[part] = max(errors)
        assert max(radial.values()) < .001, (name, radial)
        report[name] = {"housing_gap_mm": round(gap, 4),
                        "housing_to_race_seams_mm": [round(s,4) for s in seams],
                        "races_gap_mm": round(1000*(second_start-first_end),4),
                        "max_radial_side_difference_mm": max(radial.values())}
    inverse = frames["gripper_base"].inverted()
    left_pad, right_pad = ([inverse @ vertex for vertex in points[f"finger_{side} · 02 graphite_block"]]
                           for side in ("left","right"))
    bounds = lambda vectors, i: (min(v[i] for v in vectors), max(v[i] for v in vectors))
    lateral = sorted([bounds(left_pad,1),bounds(right_pad,1)])
    thickness = [(end-start)*1000 for start,end in lateral]
    offset = max(abs(a-b)*1000 for i in (0,2) for a,b in zip(bounds(left_pad,i),bounds(right_pad,i)))
    assert all(abs(t-14) < .001 for t in thickness) and offset < .001
    return {"joints": report, "gripper": {"pad_thickness_mm": thickness,
                 "open_gap_mm": 1000*(lateral[1][0]-lateral[0][1]), "opposed_padding_offset_mm": offset}}


def physical_xml(root):
    for link in root.findall("link"):
        for visual in link.findall("visual"):
            link.remove(visual)
    for element in root.iter():
        if element.text is not None and not element.text.strip():
            element.text = None
        if element.tail is not None and not element.tail.strip():
            element.tail = None
    return ET.tostring(root)


def triangle_counts(root, folder):
    counts = Counter()
    for link in root.findall("link"):
        name = link.get("name")
        if name.startswith("joint_"):
            name = f"link_{name.split('_')[1]}"
        for shape in link.findall("visual/geometry/mesh"):
            path = asset(shape.get("filename"), folder)
            counts[name] += int(ET.parse(path).getroot().find(".//{*}triangles").get("count"))
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--elbow-csv", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    stage = args.stage.resolve()
    before = ET.parse(stage/"before.urdf").getroot()
    after = ET.parse(stage/"candidate.urdf").getroot()
    counts_before, counts_after = (triangle_counts(root, stage/"assets") for root in (before, after))
    ratios = {key: value/counts_before[key] for key,value in counts_after.items()}
    print("TRIANGLE_RATIOS", ratios, flush=True)
    assert max(ratios.values()) <= 5
    assert physical_xml(before) == physical_xml(after)
    parts = components(stage)
    poses = recorded_poses(args.elbow_csv)
    repeats = Counter()
    for q in poses:
        original, exact = (transforms(root,q) for root in (before,after))
        assert original == exact
        repeats.update(collisions(parts, exact))
    clearances = interface_clearances(parts,transforms(after,[0]*6))
    (stage/"force_path_clearance.json").write_text(json.dumps(clearances,indent=2),encoding="utf-8")
    report = {"poses": len(poses), "parts": len(parts), "kinematics_changed": False,
              "intersection_pairs": [{"parts":pair,"poses":count} for pair,count in repeats.items()],
              "triangles_before": dict(counts_before), "triangles_after": dict(counts_after), "ratios": ratios}
    (stage/"blender_rviz_validation.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print("RVIZ_VISUAL_VALIDATION", report, flush=True)
    assert not repeats


if __name__ == "__main__":
    main()
