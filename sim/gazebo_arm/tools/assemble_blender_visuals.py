"""Fit the exported Blender castings to the previously verified RViz assembly details."""

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlsplit
from urllib.request import url2pathname
import xml.etree.ElementTree as ET

import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_blender_visuals import export_groups
from import_urdf import collada_mesh
from gazebo_arm import gen_urdf as g
from gazebo_arm.visual_meshes import upper_arm_stations, write_shell


def fit_axis(part, axis, lower, upper):
    points = np.asarray(part["points"])
    normals = np.asarray(part["normals"])
    before, after = points[:, axis].min(), points[:, axis].max()
    scale = (upper - lower) / (after - before)
    points[:, axis] = (points[:, axis] - before) * scale + lower
    normals[:, axis] /= scale
    normals /= np.linalg.norm(normals, axis=1)[:, np.newaxis]
    part["points"], part["normals"] = points.tolist(), normals.tolist()


def move(part, offset):
    part["points"] = (np.array(part["points"]) + offset).tolist()


def castings(links, folder):
    upper, lower = g.DH[1][0], g.DH[2][0]
    shoulder = []
    for (x, y, z), width, depth in upper_arm_stations(upper):
        if x <= -upper:
            shoulder.append(((-upper + (x+upper)*.75, y, z), width*.74, depth))
        elif x <= -.43:
            shoulder.append(((x,y,z), width*(.74+.26*(x+upper)/.08), depth))
    # Keep the original large casting profiles past the shoulder and elbow mating faces.
    shoulder.extend([
        ((-.80*upper, 0, .003), .097, .075), ((-.65*upper, 0, .002), .087, .071),
        ((-.40*upper, 0, .001), .073, .065), ((-.24*upper, 0, 0), .063, .060),
        ((-.069, 0, 0), .055, .057),
    ])
    write_shell(folder/"rviz_fit_upper_eye.dae", shoulder, exponent=.34, sides=80)
    g._assembly_asset(links["link_2"], folder, "rviz_fit_upper_eye")
    elbow = []
    for d in range(6, 91, 6):
        a = math.radians(d)
        elbow.append(((-lower-.060*math.cos(a), 0, 0), .058*math.sin(a), .036+.011*math.sin(a)))
    elbow.extend([
        ((-lower+.047, 0, 0), .047, .046), ((-lower+.065, 0, 0), .052, .041),
        ((-lower+.105, 0, 0), .061, .045), ((-.64*lower, 0, 0), .063, .053),
        ((-.54*lower, 0, 0), .056, .049), ((-.38*lower, 0, 0), .050, .042),
    ])
    curve = .78*.064
    for i in range(9):
        t = i/8
        elbow.append(((-curve*(1-t)**2,0,curve*t*t), .046-.012*t, .039-.007*t))
    elbow.append(((0,0,.066), .031, .029))
    write_shell(folder/"rviz_fit_forearm_eye.dae", elbow, exponent=.38, sides=80)
    g._assembly_asset(links["link_3"], folder, "rviz_fit_forearm_eye")
    eye = []
    for d in range(10, 91, 10):
        a = math.radians(d)
        eye.append(((0,0,-.038*math.cos(a)), .037+.0025*math.sin(a), .036*math.sin(a)))
    eye.extend([
        ((0, 0, .023), .031, .032), ((0, 0, .039), .037, .034),
        ((0, 0, .059), .032, .028), ((0, 0, .077), .027, .025),
    ])
    write_shell(folder/"rviz_fit_wrist_eye.dae", eye, exponent=.59, sides=64)
    g._assembly_asset(links["link_5"], folder, "rviz_fit_wrist_eye")


def fit_blender_parts(parts):
    replaced = {
        "Fixed swivel dust seal", "Shoulder pin", "Shoulder rotating bearing housing", "Upper arm with elbow fork seat",
        "Elbow fixed shaft", "Elbow rotating bearing housing", "Forearm clear of fixed elbow cheeks",
        "Wrist roll fixed collar", "Wrist roll pin", "Wrist pitch pin", "Wrist pitch rotating bearing",
        "Wrist output casing", "link_1 · 00 steel_disc", "link_1 · 01 graphite_disc",
        "link_1 · 03 graphite_disc", "link_1 · 05 graphite_disc",
    }
    parts = [p for p in parts if p["name"] not in replaced]
    for part in parts:
        name = part["name"]
        sign = -1 if name.endswith("-1") else 1
        if name.endswith("pedestal"):
            fit_axis(part, 2, .02825, .076)
        elif name.startswith("Anchor washer"):
            fit_axis(part, 2, .02825, .03105)
        elif name.startswith("Anchor socket floor"):
            points = np.asarray(part["points"])
            mid = (points[:, :2].min(axis=0) + points[:, :2].max(axis=0))/2
            points[:, :2] = mid + .80*(points[:, :2]-mid)
            part["points"] = points.tolist()
        elif name.endswith("shoulder_cheek"):
            sign = -1 if "02" in name else 1
            fit_axis(part, 1, -.081, .063)
            fit_axis(part, 2, *sorted([sign*.091, sign*.150]))
        elif name.startswith("Elbow fixed cheek"):
            fit_axis(part, 0, -.0688, .059)
        elif name.startswith("Elbow shaft end"):
            move(part, (0,0,sign*.0007))
        elif name.startswith("Wrist yoke cheek"):
            fit_axis(part, 1, -.0428, .015)
        elif name.startswith("Wrist pitch pin cap"):
            move(part, (0,0,sign*.0007))
        elif name.startswith("Linear jaw guide"):
            fit_axis(part, 2, .03415, .043)
        elif name.startswith("Guide cover fastener"):
            move(part, (0,0,.0004))
        elif name == "link_6 · 00 steel_disc":
            fit_axis(part, 2, .0381, .04485)
        elif name == "link_6 · 01 graphite_disc":
            fit_axis(part, 2, 0, .0379)
    return parts, sorted(replaced)


def fit_casting_covers(parts, folder):
    casing = collada_mesh(folder/"rviz_fit_upper_eye.dae")
    body = BVHTree.FromPolygons([v.co for v in casing.vertices], [tuple(p.vertices) for p in casing.polygons])
    covers = {p["name"].split()[-1]:p for p in parts if p["name"].endswith(("service_cover", "line_cover"))}
    for name, part in covers.items():
        sign = 1 if name == "service_cover" else -1
        points = part["points"]
        rims = [points[i:i+64] for i in range(0,len(points)-2,64)]
        assert rims and all(len(rim)==64 for rim in rims)
        for rim in rims:
            inside = min(sign*v[2] for v in rim)
            for point in rim:
                hit = body.ray_cast(Vector((point[0],point[1],float(sign))), Vector((0,0,-sign)))[0]
                if hit is None:
                    raise ValueError(f"{name} reached outside the main shell")
                point[2] = hit.z + sign*(.00065 + sign*point[2] - inside)
        for point, rim in zip(points[-2:], (rims[0],rims[-1])):
            point[:] = np.asarray(rim).mean(axis=0).tolist()
    top = covers["service_cover"]
    cover = BVHTree.FromPolygons(top["points"], [[i for i,_ in f] for f in top["faces"]], all_triangles=True)
    for part in parts:
        if part["link"] != "link_2" or "graphite_disc" not in part["name"]:
            continue
        faces = [cover.ray_cast(Vector((x,y,1)),Vector((0,0,-1)))[0] for x,y,_ in part["points"]]
        height = max(hit.z for hit in faces if hit is not None)
        move(part,(0,0,height+.00015-min(v[2] for v in part["points"])))


def add_force_details(legacy, links, folder):
    for old_link in legacy.findall("link"):
        dest = links[old_link.get("name")]
        for old in old_link.findall("visual"):
            name = old.get("name", "")
            if not name.startswith(("base_m8_", "turret_m10_", "base_register", "turret_register",
                                    "shoulder_gusset_", "shoulder_mount_seat_", "shoulder_left_bolt_",
                                    "shoulder_right_bolt_", "shoulder_cap_", "swivel_", "tool_flange_bolt_")):
                continue
            visual = deepcopy(old)
            shape = visual.find("geometry/mesh")
            file = shape.get("filename")
            if file.startswith("file:"):
                source = Path(url2pathname(urlsplit(file).path))
                asset = folder / f"rviz_force_{source.name}"
                shutil.copyfile(source, asset)
                shape.set("filename", asset.as_uri())
            if name.startswith(("shoulder_left_bolt_", "shoulder_right_bolt_", "shoulder_cap_")):
                origin = visual.find("origin")
                xyz = [float(x) for x in origin.get("xyz").split()]
                xyz[2] += math.copysign(.003, xyz[2])
                origin.set("xyz", g._xyz(xyz))
            elif name.startswith("shoulder_gusset_"):
                visual.find("origin").set("xyz", "-0.072 0 0")
            dest.append(visual)


def add_bearings(links, folder):
    l = links
    for prefix, fixed, moving, a, b, shaft, radius, width in (
        ("shoulder", "link_1", "joint_2_axis", .087, .091, .025, .046, .0008),
        ("elbow", "link_2", "joint_3_axis", .047, .050, .0195, .041, .00065),
        ("wrist_pitch", "link_4", "joint_5_axis", .0395, .043, .014, .030, .00070),
    ):
        for side in ("l","r"):
            direction = (l[fixed], l[moving]) if side=="l" else (l[moving], l[fixed])
            start, stop = (-b,-a) if side=="l" else (a,b)
            g._axle_and_races(folder,f"rviz_fit_{prefix}_{side}",shaft,direction,radius,start,stop,width,sides_count=32)
    for side in (-1,1):
        g._add_visual(l["joint_2_axis"], f"shoulder_rotor_end_{side:+d}",
                      g._cyl(.050,.0078,g._xyz((0,0,side*.0831)),"0 0 0","joint"))
    g._axle_and_races(folder, "rviz_fit_wrist_roll", .013, (l["link_3"], l["joint_4_axis"]),
                      .021, .066, .069, .00060, (0,g.DH[3][2]), sides_count=32)
    g._axle_and_races(folder, "rviz_fit_tool_roll", .0095, (l["link_5"], l["link_6"]),
                      .0175, .077, .080, .00065, (0,g.DH[5][2]), sides_count=32)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", type=Path, required=True)
    ap.add_argument("--previous-assembly", type=Path, required=True)
    args = ap.parse_args(sys.argv[sys.argv.index("--")+1:])
    stage = args.stage.resolve()
    folder = stage / "assets"
    folder.mkdir(exist_ok=True)
    source_text = (stage/"before.urdf").read_text(encoding="utf-8")
    source = ET.fromstring(source_text)
    links = {l.get("name"):l for l in source.findall("link")}
    for link in links.values():
        for old in link.findall("visual"):
            link.remove(old)
    parts, removed = fit_blender_parts(json.loads((stage/"components.json").read_text(encoding="utf-8")))
    add_force_details(ET.parse(args.previous_assembly).getroot(), links, folder)
    castings(links, folder)
    fit_casting_covers(parts, folder)
    add_bearings(links, folder)
    ET.ElementTree(source).write(stage/"candidate_extras.xml",encoding="utf-8")
    (stage/"candidate_components.json").write_text(json.dumps(parts,ensure_ascii=False),encoding="utf-8")
    for link_name, batch in export_groups(parts,folder,"rviz_body").items():
        for mesh in batch:
            g._assembly_asset(links[link_name],folder,mesh["stem"])
    geometry = {}
    visual_count = 0
    for link_name, link in links.items():
        geometry[link_name] = []
        for visual in link.findall("visual"):
            mesh = visual.find("geometry/mesh")
            uri = mesh.get("filename")
            if uri.startswith("file:"):
                mesh.set("filename", "package://gazebo_arm/meshes/"+Path(url2pathname(urlsplit(uri).path)).name)
            geometry[link_name].append(ET.tostring(visual,encoding="unicode"))
            visual_count += 1

    def replace_link(match):
        name, body = match.group(1), match.group(2)
        if body is None:
            if not geometry[name]:
                return match[0]
            body = ""
        body = re.sub(r'(?ms)^    <visual(?:\s[^>]*)?>.*?^    </visual>\s*?\n', "", body)
        visuals = "".join("    "+visual.strip()+"\n" for visual in geometry[name])
        return f'<link name="{name}">{body.rstrip()}\n{visuals}  </link>'

    text = re.sub(r'<link name="([^"]+)"(?:\s*/>|>(.*?)</link>)', replace_link, source_text, flags=re.S)
    if len(ET.fromstring(text).findall("link/visual")) != visual_count:
        raise RuntimeError("Unexpected visual count after merging")
    (stage/"candidate.urdf").write_text(text,encoding="utf-8")
    (stage/"fitting.json").write_text(json.dumps({"replaced_at_interfaces":removed,"retained_components":len(parts),
                                                "visual_elements":visual_count},ensure_ascii=False,indent=2),encoding="utf-8")


if __name__ == "__main__":
    main()
