"""从数值孪生的 DH + 连杆质量/惯量生成 URDF，保持与 sim/hydraulic-arm 同源。

几何（无 CAD 网格时用基本体拼出「像样的工业臂」，仅供 RViz 可视化）：
- base_link：底座立柱（沿 z 到关节 1，d1 高）。
- 每根连杆连接本关节轴、DH 连杆原点和下一关节轴。水平偏移随本关节旋转，
  下一关节的轴向偏移则固定在当前连杆上。
- 末端 link_6：法兰圆柱 + 小夹爪方块。
外形是近似（非精确 CAD）；动力学在 plant.py，不依赖此几何。质量/质心/惯量仍用孪生数值，未改。

用法：python gen_urdf.py [out.urdf]
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import numpy as np

if __package__:
    from .visual_meshes import WRIST_CASE_SETBACK, generate_shells, upper_arm_stations, write_mesh, write_shell
else:
    from visual_meshes import WRIST_CASE_SETBACK, generate_shells, upper_arm_stations, write_mesh, write_shell

TWIN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "..", "hydraulic-arm", "python_twin")
sys.path.insert(0, TWIN)
import hydraulic_arm_twin as t  # noqa: E402

P = t.PARAMS
DH = P["dh"]
LINKS = P["links"]
TMAX = t.actuator_torque_limit(P)[0]
VEL_LIMIT = 2.0

# 连杆体半径（从底座到腕部递减，工业臂观感）
LINK_R = {1: 0.060, 2: 0.055, 3: 0.048, 4: 0.044, 5: 0.040, 6: 0.036}
BASE_R = 0.085
WRIST_SHAFT_R = 0.027
FLANGE_SHAFT_R = 0.030


# 夹爪几何按作业场景可调（指长 m, 最大开口 m）——依钢铁作业工程建议。
# URDF 是静态模型：用 --preset / --fingers / --opening 生成对应场景的爪子。
GRIPPER_PRESETS = {
    "general": (0.065, 0.180),   # steel_yard 的 160 mm 钢坯，两侧各留 10 mm
    "sorting": (0.120, 0.250),   # 型钢/钢管分拣：指更长、开口更大卡住粗钢
    "marking": (0.065, 0.180),   # 喷号：指短、开口小，定位为主
    "docking": (0.075, 0.180),   # 下水口对接：指中等、精度优先
}
FINGER_LEN, OPENING = GRIPPER_PRESETS["general"]
GROOVE = False       # 分拣预设时夹持面做成 V 型槽（卡圆钢管/型钢）


def _cyl(radius, length, xyz, rpy, material):
    finish = {"wrist": "steel", "bolt": "steel", "body": "cast", "finger": "steel"}.get(material, "graphite")
    return _mesh(f"{finish}_disc", xyz, f"{radius:.5f} {radius:.5f} {length:.5f}", rpy)


def _box(size, xyz, rpy):
    return _mesh("graphite_block", xyz, size, rpy)


def _mesh(name, xyz="0 0 0", scale="1 1 1", rpy="0 0 0"):
    # RViz uses the embedded COLLADA finish when there is no URDF material override.
    return (f'    <visual>\n'
            f'      <origin xyz="{xyz}" rpy="{rpy}"/>\n'
            f'      <geometry><mesh filename="package://gazebo_arm/meshes/{name}.dae" scale="{scale}"/></geometry>\n'
            f'    </visual>\n')


def _steel_disc(radius, length, xyz, rpy="0 0 0"):
    return _mesh("steel_disc", xyz, f"{radius:.5f} {radius:.5f} {length:.5f}", rpy)


def _xyz(values):
    return " ".join(f"{value:.9g}" for value in values)


def bolt_circle(radius, count, head_d, head_h, *, center=(0, 0, 0), phase=0):
    """Place shallow machined heads in the XY plane of the mounting face."""
    for i in range(count):
        angle = phase + i * math.tau / count
        x, y, z = center
        origin = (x + radius * math.cos(angle), y + radius * math.sin(angle), z)
        yield _steel_disc(head_d / 2, head_h, _xyz(origin))


def _lathe(path, profile, finish, sides=80):
    """Revolve a closed (radius, height) section with a real bore and groove."""
    points, normals, faces = [], [], []
    for i, (radius, height) in enumerate(profile):
        previous, following = profile[i - 1], profile[(i + 1) % len(profile)]
        before = np.array((radius, height)) - previous
        after = np.array(following) - (radius, height)
        dr, dz = before / np.linalg.norm(before) + after / np.linalg.norm(after)
        length = math.hypot(dr, dz)
        for side in range(sides):
            angle = math.tau * side / sides
            c, s = math.cos(angle), math.sin(angle)
            points.append((radius * c, radius * s, height))
            normals.append((dz * c / length, dz * s / length, -dr / length))
            a = i * sides + side
            b = i * sides + (side + 1) % sides
            next_ring = ((i + 1) % len(profile)) * sides
            c_idx, d = next_ring + side, next_ring + (side + 1) % sides
            faces.extend((((a, a), (b, b), (c_idx, c_idx)), ((b, b), (d, d), (c_idx, c_idx))))
    write_mesh(path, points, normals, faces, finish)


def _plate(path, outline, thickness, bevel, finish="cast", rounded=False):
    """Loft a shallow plate from a counterclockwise XY outline."""
    outline = np.array(outline)
    if rounded:
        corners = []
        for i, point in enumerate(outline):
            before = .84*point + .16*outline[i-1]
            after = .84*point + .16*outline[(i+1) % len(outline)]
            for t in (0, .25, .50, .75, 1):
                corners.append((1-t)**2*before + 2*t*(1-t)*point + t*t*after)
        outline = np.array(corners)
    center = outline.mean(axis=0)
    phases = (0, 30, 60, 90) if rounded else (0, 90)
    lower = [(center + (outline-center)*(.91+.09*math.sin(a)),
              -thickness/2 + bevel*(1-math.cos(a))) for a in map(math.radians, phases)]
    layers = lower + [(ring, -z) for ring, z in reversed(lower)]
    points = [(*point, z) for ring, z in layers for point in ring]
    count = len(outline)
    top = (len(layers)-1)*count
    triangles = []
    for level in range(len(layers)-1):
        for i in range(count):
            j = (i + 1) % count
            a, b = level * count + i, level * count + j
            triangles.extend(((a, b, a + count), (b, b + count, a + count)))
    for i in range(1, count - 1):
        triangles.extend(((0, i + 1, i), (top, top + i, top + i + 1)))
    normals, faces = [], []
    for a, b, c in triangles:
        normal = np.cross(np.subtract(points[b], points[a]), np.subtract(points[c], points[a]))
        faces.append(tuple((point, len(normals)) for point in (a, b, c)))
        normals.append(normal / np.linalg.norm(normal))
    write_mesh(path, points, normals, faces, finish)


def _add_visual(link, name, xml):
    visual = ET.fromstring(xml)
    visual.set("name", name)
    link.append(visual)


def _remove_visuals(link, stems):
    for visual in link.findall("visual"):
        if Path(visual.find("geometry/mesh").get("filename")).stem in stems:
            link.remove(visual)


def _assembly_asset(link, folder, name, xyz=(0, 0, 0), rpy=(0, 0, 0)):
    xml = _mesh(name, _xyz(xyz), rpy=_xyz(rpy))
    _add_visual(link, name, xml.replace(f"package://gazebo_arm/meshes/{name}.dae",
                                      (folder / f"{name}.dae").as_uri()))


def _race(folder, name, outer, bore, width, finish="graphite", sides=80):
    edge = min(.00035, width / 4, (outer - bore) / 4)
    end = width / 2
    section = [(outer-edge, -end), (outer, -end+edge), (outer, end-edge),
               (outer-edge, end), (bore+edge, end), (bore, end-edge),
               (bore, -end+edge), (bore+edge, -end)]
    _lathe(folder / f"{name}.dae", section, finish, sides)


def _axle_and_races(folder, name, shaft, sides, race_r, start, stop, width, offsets=(0, 0),
                     shaft_span=None, sides_count=80):
    """Fill an axial housing gap with a pin and two bored bearing races."""
    half = width / 2
    gap = stop - start
    assert gap > width * 2 + .001
    _race(folder, f"{name}_race", race_r, shaft + .00035, width, sides=sides_count)
    for label, link, z in ((0, sides[0], start + .00055 + half),
                           (1, sides[1], stop - .00055 - half)):
        _assembly_asset(link, folder, f"{name}_race", xyz=(0, 0, z - offsets[label]))
        link.findall("visual")[-1].set("name", f"{name}_race_{label}")
    low, high = shaft_span or (start + .00015, stop - .00015)
    _add_visual(sides[0], f"{name}_shaft", _steel_disc(
        shaft, high - low, _xyz((0, 0, (low + high) / 2 - offsets[0]))))


def _bolt_set(link, name, radius, count, diameter, thickness, z, phase=0):
    for i, bolt in enumerate(bolt_circle(radius, count, diameter, thickness, center=(0, 0, z), phase=phase), 1):
        _add_visual(link, f"{name}_{i}", bolt)


def _swivel_assembly(links, folder):
    base, axis, support = (links[name] for name in ("base_link", "joint_1_axis", "link_1"))
    _remove_visuals(support, {"steel_disc", "graphite_disc"})
    # The stationary ledge carries M8 heads outside the swept diameter.
    _lathe(folder / "base_register.dae",
           [(.119, .0762), (.125, .078), (.125, .0875), (.1235, .089),
            (.108, .089), (.107, .0875), (.105, .0875), (.104, .089), (.0395, .089), (.0395, .0762)],
           "cast")
    _assembly_asset(base, folder, "base_register")
    _bolt_set(base, "base_m8", .117, 4, .013, .0022, .09025, math.pi / 4)

    # The bolt ledge is stepped below the supporting cheeks.
    axis_height = DH[0][2]
    _lathe(folder / "turret_register.dae",
           [(r, z-axis_height) for r, z in
            ((.100, .092), (.106, .093), (.108, .0948), (.120, .0948),
             (.122, .0955), (.121, .096), (.093, .096), (.092, .0954),
             (.090, .0954), (.088, .0988), (.0395, .0988), (.0395, .092))], "steel")
    _assembly_asset(axis, folder, "turret_register")
    _bolt_set(axis, "turret_m10", .103, 8, .016, .0024, .09735-axis_height, math.pi / 8)
    _axle_and_races(folder, "swivel", .0388, (base, axis), .084, .089, .092, .00065,
                    (0, axis_height), shaft_span=(.07615, .09865))


def _shoulder_assembly(links, folder):
    support, rotor = links["link_1"], links["joint_2_axis"]
    rotation = (math.pi / 2, 0, math.pi / 2)
    seat_outline = [(-.018, -.007), (-.014, -.011), (.014, -.011), (.018, -.007),
                    (.018, .007), (.014, .011), (-.014, .011), (-.018, .007)]
    _plate(folder / "shoulder_mount_seat.dae", seat_outline, .0025, .00045)
    for sign, side in ((-1, "left"), (1, "right")):
        _assembly_asset(links["joint_1_axis"], folder, "shoulder_mount_seat",
                        xyz=(0, sign*.106, .0975-DH[0][2]))
        links["joint_1_axis"].findall("visual")[-1].set("name", f"shoulder_mount_seat_{side}")
        outline = [(-.0808, .042), (-.077, .047), (-.044, .101), (-.036, .115),
                   (-.064, .115), (-.0808, .052)]
        outline = [(y, sign*z) for y, z in (outline if sign < 0 else reversed(outline))]
        rib = f"shoulder_gusset_{side}"
        _plate(folder / f"{rib}.dae", outline, .007, .001, rounded=True)
        _assembly_asset(support, folder, rib, xyz=(-.070, 0, 0), rpy=rotation)
        _race(folder, f"shoulder_cap_{side}", .050, .025, .004, "cover")
        _assembly_asset(support, folder, f"shoulder_cap_{side}", xyz=(0, 0, sign*.1493))
        _add_visual(support, f"shoulder_cap_pin_{side}", _steel_disc(.0246, .0038, _xyz((0, 0, sign*.1493))))
        _bolt_set(support, f"shoulder_{side}_bolt", .041, 4, .007, .0021, sign*.1525, math.pi/4)
    _axle_and_races(folder, "shoulder_l", .025, (support, rotor), .046, -.091, -.087, .0008)
    _axle_and_races(folder, "shoulder_r", .025, (rotor, support), .046, .087, .091, .0008)


def _fork_outline(rear, radius):
    return [(rear, -radius), *[(radius*math.cos(math.radians(i)), radius*math.sin(math.radians(i)))
                              for i in range(-90, 91, 15)], (rear, radius)]


def _elbow_assembly(links, folder):
    upper, lower, bend = DH[1][0], DH[2][0], DH[3][2]
    arm, forearm, rotor = links["link_2"], links["link_3"], links["joint_3_axis"]
    _remove_visuals(arm, {"upper_arm", "graphite_disc", "service_cover", "line_cover"})
    _remove_visuals(forearm, {"forearm", "graphite_disc", "steel_disc"})
    stations = []
    for (x, y, z), width, depth in upper_arm_stations(upper):
        if x >= -.10:
            break
        # Keep the rotating eye clear of the swivel platter at the bottom of its arc.
        if x <= -upper:
            x = -upper + (x + upper) * .75
            width *= .74
        elif x < -.84 * upper:
            fraction = (x + upper) / (.16 * upper)
            width *= .74 + .26 * fraction
        stations.append(((x, y, z), width, depth))
    stations.extend([((-.095, 0, 0), .062, .065), ((-.081, 0, 0), .063, .070)])
    write_shell(folder / "upper_fork_seat.dae", stations, exponent=.40, sides=96)
    _assembly_asset(arm, folder, "upper_fork_seat")
    for sign in (-1, 1):
        _add_visual(links["joint_2_axis"], f"shoulder_rotor_end_{sign:+d}",
                    _cyl(.050, .0078, _xyz((0, 0, sign*.0831)), "0 0 0", "joint"))
    cover = [(.096 * math.cos(math.radians(i)), .030 * math.sin(math.radians(i)))
             for i in range(0, 360, 12)]
    _plate(folder / "upper_access_plate.dae", cover, .0026, .00065, "cover")
    _assembly_asset(arm, folder, "upper_access_plate", xyz=(-.253, 0, .074), rpy=(0, .065, 0))
    for x in (-.067, .067):
        _add_visual(arm, f"upper_access_bolt_{x:+g}", _cyl(
            .0037, .0017, _xyz((-.253+x, 0, .07645-.065*x)), "0 .065 0", "joint"))
    _plate(folder / "elbow_fork_cheek.dae", _fork_outline(-.0805, .058), .016, .0014)
    for sign in (-1, 1):
        _assembly_asset(arm, folder, "elbow_fork_cheek", xyz=(0, 0, sign*.060))
        arm.findall("visual")[-1].set("name", f"elbow_fork_cheek_{sign:+d}")
        _add_visual(arm, f"elbow_pin_end_{sign:+d}", _steel_disc(.025, .003, _xyz((0, 0, sign*.0697))))
    _axle_and_races(folder, "elbow_l", .0195, (arm, rotor), .041, -.052, -.049, .00065)
    _axle_and_races(folder, "elbow_r", .0195, (rotor, arm), .041, .049, .052, .00065)

    elbow_eye = []
    for degrees in range(6, 91, 6):
        a = math.radians(degrees)
        elbow_eye.append(((-lower - .060*math.cos(a), 0, 0),
                          .058*math.sin(a), .038 + .011*math.sin(a)))
    stations = elbow_eye + [
        ((-.93 * lower, 0, 0), .064, .0488),
        ((-.78 * lower, 0, 0), .062, .0488),
        ((-.54 * lower, 0, 0), .055, .045),
        ((-.38 * lower, 0, 0), .050, .041),
    ]
    nose = bend - .036
    curve = min(.20 * lower, .78 * nose)
    for i in range(9):
        t = i / 8
        stations.append(((-curve*(1-t)**2, 0, curve*t*t), .046-.013*t, .039-.010*t))
    stations.extend([((0, 0, nose - .003), .031, .027), ((0, 0, nose), .029, .025)])
    write_shell(folder / "forearm_elbow_eye.dae", stations, exponent=.46, sides=96)
    _assembly_asset(forearm, folder, "forearm_elbow_eye")


def _wrist_assembly(links, folder):
    forearm, roll, yoke, pitch, wrist = (links[name] for name in
        ("link_3", "joint_4_axis", "link_4", "joint_5_axis", "link_5"))
    _remove_visuals(yoke, {"steel_disc", "graphite_disc"})
    _remove_visuals(wrist, {"wrist", "graphite_disc"})
    bend = DH[3][2]
    _axle_and_races(folder, "wrist_roll", .0115, (forearm, roll), .021, bend-.036, bend-.033, .00060, (0, bend))
    _add_visual(roll, "wrist_roll_output_flange", _steel_disc(.043, .0035, "0 0 -0.03125"))

    _plate(folder / "pitch_fork_cheek.dae", _fork_outline(-.0294, .026), .008, .0009)
    for sign in (-1, 1):
        _assembly_asset(yoke, folder, "pitch_fork_cheek", xyz=(0, 0, sign*.031), rpy=(0, 0, math.pi/2))
        yoke.findall("visual")[-1].set("name", f"pitch_fork_cheek_{sign:+d}")
        _add_visual(yoke, f"pitch_pin_end_{sign:+d}", _steel_disc(.014, .0026, _xyz((0, 0, sign*.03645))))
    _axle_and_races(folder, "wrist_pitch_l", .009, (yoke, pitch), .019, -.027, -.024, .0006)
    _axle_and_races(folder, "wrist_pitch_r", .009, (pitch, yoke), .019, .024, .027, .0006)
    stations = []
    for degrees in range(10, 91, 10):
        a = math.radians(degrees)
        stations.append(((0, 0, -.025*math.cos(a)), .020+.004*math.sin(a), .025*math.sin(a)))
    face = DH[5][2] - .004
    stations.extend([((0, 0, .015), .024, .030), ((0, 0, .036), .023, .028),
                     ((0, 0, face-.003), .022, .024), ((0, 0, face), .021, .023)])
    write_shell(folder / "wrist_pitch_eye.dae", stations, exponent=.60, sides=80)
    _assembly_asset(wrist, folder, "wrist_pitch_eye")


def _tool_assembly(links, folder):
    wrist, tool, jaws = (links[name] for name in ("link_5", "link_6", "gripper_base"))
    _remove_visuals(tool, {"steel_disc", "graphite_disc"})
    wrist_end = DH[5][2]
    _axle_and_races(folder, "tool_roll", .0095, (wrist, tool), .0175, wrist_end-.004, wrist_end-.001,
                    .00065, (0, wrist_end))
    _add_visual(tool, "tool_rotor", _cyl(.027, .0385, "0 0 0.01825", "0 0 0", "joint"))
    _add_visual(tool, "tool_flange", _steel_disc(.040, .007, "0 0 0.0413"))
    _bolt_set(tool, "tool_flange_bolt", .033, 4, .0062, .002, .03665, math.pi/4)
    for sign in (-1, 1):
        _add_visual(jaws, f"jaw_guide_bolt_{sign:+d}", _steel_disc(.0045, .0022, _xyz((0, sign*.061, .05125))))


def generate_rviz_assembly(description, folder):
    """Overlay the visual geometry in memory, preserving every non-visual element."""
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    root = ET.fromstring(description)
    links = {link.get("name"): link for link in root.findall("link")}
    for stage in (_swivel_assembly, _shoulder_assembly, _elbow_assembly, _wrist_assembly, _tool_assembly):
        stage(links, folder)
    return ET.tostring(root, encoding="unicode")


# --- 碰撞体（仅 collision）：URDF 无 capsule 基本体，用「圆柱 + 两端球」逼近胶囊，
#     给每根连杆套一层带余量的「防碰撞紧身衣」，比逐个视觉体做碰撞更省更凸 ---
def _col_cyl(radius, length, xyz, rpy):
    return (
        f'    <collision>\n'
        f'      <origin xyz="{xyz}" rpy="{rpy}"/>\n'
        f'      <geometry><cylinder radius="{radius:.3f}" length="{length:.4f}"/></geometry>\n'
        f'    </collision>\n'
    )


def _col_sphere(radius, xyz):
    return (
        f'    <collision>\n'
        f'      <origin xyz="{xyz}" rpy="0 0 0"/>\n'
        f'      <geometry><sphere radius="{radius:.3f}"/></geometry>\n'
        f'    </collision>\n'
    )


def _capsule(radius, a, d):
    """连杆胶囊碰撞：从原点到 (a,0,d) 的圆柱 + 两端球（a/d 在 x-z 平面）。"""
    length = math.hypot(a, d)
    if length < 1e-6:
        return _col_sphere(radius, "0 0 0")
    beta = math.atan2(a, d)
    return (
        _col_cyl(radius, length, f"{a/2:.4f} 0 {d/2:.4f}", f"0 {beta:.6f} 0")
        + _col_sphere(radius, "0 0 0")
        + _col_sphere(radius, f"{a:.4f} 0 {d:.4f}")
    )


def base_xml(d1):
    h = max(d1, 0.05)
    top = max(h - 0.104, 0.03)
    parts = [
        '  <link name="base_link">\n',
        # 惯量：Gazebo 里无 inertial 的连杆会被丢弃/异常（导致 ros2_control 找不到关节），底座给足质量
        _inertial(20.0, 0.2, 0.2, 0.3, f"0 0 {h/2:.4f}"),
        _mesh("pedestal_foot"),
        _mesh("pedestal"),
    ]
    # 角落的暗色座圈和低矮紧固件。
    for bx in (-.108, .108):
        for by in (-.086, .086):
            parts.append(_cyl(.015, .004, f"{bx:.4f} {by:.4f} {top * .30:.4f}", "0 0 0", "black"))
            parts.append(_cyl(.009, .004, f"{bx:.4f} {by:.4f} {top * .33:.4f}", "0 0 0", "bolt"))
    # 碰撞：立柱胶囊（带余量）
    parts.append(_col_cyl(BASE_R + 0.02, top, f"0 0 {top/2:.4f}", "0 0 0"))
    parts.append('  </link>')
    return "".join(parts)


def _inertial(mass, ixx, iyy, izz, xyz="0 0 0"):
    return (f'    <inertial>\n'
            f'      <origin xyz="{xyz}" rpy="0 0 0"/>\n'
            f'      <mass value="{mass:.3f}"/>\n'
            f'      <inertia ixx="{ixx:.5f}" ixy="0" ixz="0" iyy="{iyy:.5f}" iyz="0" izz="{izz:.5f}"/>\n'
            f'    </inertial>\n')


def _fixed_joint(name, parent, child, xyz, rpy="0 0 0"):
    return (f'  <joint name="{name}" type="fixed">\n'
            f'    <parent link="{parent}"/>\n'
            f'    <child link="{child}"/>\n'
            f'    <origin xyz="{xyz}" rpy="{rpy}"/>\n'
            f'  </joint>')


def _col_box(size, xyz):
    return (f'  <collision><origin xyz="{xyz}"/>'
            f'<geometry><box size="{size}"/></geometry></collision>\n')


def gripper_xml():
    """带封闭导轨壳和双指夹持面的固定开口夹爪。"""
    fl = FINGER_LEN
    off = OPENING / 2.0 + 0.016
    body = "0.074 0.092 0.034"
    body_origin = "0 0 0.017"
    rail = f"0.042 {2 * off + 0.027:.4f} 0.016"
    rail_origin = "0 0 0.042"
    xml = [
        _fixed_joint("gripper_base_joint", "link_6", "gripper_base", "0 0 0.045"),
        '  <link name="gripper_base">\n',
        _inertial(1.5, 0.003, 0.003, 0.004),
        _mesh("gripper_body"),
        _mesh("gripper_rail", scale=f"1 {(2 * off + .027) / .239:.8f} 1"),
        _col_box(body, body_origin),
        _col_box(rail, rail_origin),
        '  </link>',
    ]
    for sign, side in ((1, "right"), (-1, "left")):
        name = f"finger_{side}"
        finger = f"0.024 0.024 {fl:.3f}"
        center = f"0 0 {fl/2:.4f}"
        xml.extend([
            _fixed_joint(f"{name}_joint", "gripper_base", name, f"0 {sign*off:.4f} 0.050"),
            f'  <link name="{name}">\n',
            _inertial(0.3, 0.0004, 0.0004, 0.0001, center),
            _mesh("finger", scale=f"1 1 {fl / .065:.8f}"),
            _box("0.036 0.027 0.016", "0 0 -0.004", "0 0 0"),
            _col_box(finger, center),
        ])
        if GROOVE:
            for tilt in (0.45, -0.45):
                xml.append(_box(f"0.024 0.004 {fl*0.42:.3f}",
                                f"0 {-sign*0.014:.4f} {fl*0.55:.4f}",
                                f"{tilt:.4f} 0 0"))
        else:
            xml.append(_box(f"0.020 0.004 {fl*0.75:.3f}",
                            f"0 {-sign*0.014:.4f} {fl*0.55:.4f}", "0 0 0"))
        xml.append('  </link>')
    return "\n".join(xml)


def suction_xml():
    """紧凑吸附头，杯口与搬运场景的 link_6 + 0.16 m 吸附点对齐。"""
    return "\n".join([
        _fixed_joint("gripper_base_joint", "link_6", "gripper_base", "0 0 0.045"),
        '  <link name="gripper_base">',
        _inertial(1.5, 0.003, 0.003, 0.004, "0 0 0.038"),
        _cyl(0.035, 0.052, "0 0 0.026", "0 0 0", "joint"),
        _cyl(0.037, 0.007, "0 0 0.0485", "0 0 0", "body"),
        _cyl(0.023, 0.030, "0 0 0.067", "0 0 0", "finger"),
        _cyl(0.027, 0.012, "0 0 0.088", "0 0 0", "black"),
        _cyl(0.034, 0.013, "0 0 0.1005", "0 0 0", "black"),
        _cyl(0.040, 0.008, "0 0 0.111", "0 0 0", "black"),
        _col_cyl(0.035, 0.052, "0 0 0.026", "0 0 0"),
        _col_cyl(0.023, 0.030, "0 0 0.067", "0 0 0"),
        _col_cyl(0.040, 0.033, "0 0 0.0985", "0 0 0"),
        '  </link>',
    ])


def link_xml(idx, spec, current_dh, next_dh):
    m = spec["m"]
    cx, cy, cz = spec["com"]
    ixx, iyy, izz = spec["I"]
    r = LINK_R[idx]
    kr = r + 0.018   # 关节壳略粗于连杆体
    parts = [
        f'  <link name="link_{idx}">\n'
        f'    <inertial>\n'
        f'      <origin xyz="{cx:.4f} {cy:.4f} {cz:.4f}" rpy="0 0 0"/>\n'
        f'      <mass value="{m:.3f}"/>\n'
        f'      <inertia ixx="{ixx:.4f}" ixy="0" ixz="0" iyy="{iyy:.4f}" iyz="0" izz="{izz:.4f}"/>\n'
        f'    </inertial>\n'
    ]
    a, alpha, _ = current_dh
    # 本关节轴在当前 DH 连杆坐标系中的位置和方向。
    if idx == 1:
        # link_1 的 +Y 是立柱向上方向。转盘和俯仰轴之间留出支架空间。
        parts.append(_steel_disc(0.124, 0.009, "0 -0.078 0", "-1.570796 0 0"))
        parts.append(_cyl(0.123, 0.026, "0 -0.089 0", "-1.570796 0 0", "joint"))
        for side in (-1, 1):
            z = side * 0.119
            parts.append(_mesh("shoulder_cheek", f"0 0 {z:.3f}"))
            parts.append(_cyl(0.036, 0.006, f"0 0 {side * .148:.3f}", "0 0 0", "joint"))
    elif idx == 4:
        # +Y in link_4 points along the forearm's final +Z cylinder axis.
        # Seat the wrist on that axis, leaving a visible gap to the forearm shell.
        axis_rpy = f"{-math.pi / 2:.15g} 0 0"
        collar_y = -WRIST_CASE_SETBACK + .008
        parts.append(_steel_disc(.028, .010, f"0 {collar_y:.4f} 0", axis_rpy))
        parts.append(_cyl(.025, .020, "0 -0.006 0", axis_rpy, "joint"))
        parts.append(_col_box("0.064 0.016 0.096", "0 -0.052 0"))
        for side in (-1, 1):
            z = side * 0.041
            plate = "0.058 0.052 0.014"
            pos = f"0 -0.025 {z:.3f}"
            parts.append(_col_box(plate, pos))
    if idx in (2, 3, 5):
        name, radius, length = {
            # The shoulder casting encloses the hub radially, leaving the ends
            # of the hub visible between the casting and the fixed cheek plates.
            2: ("upper_arm", .053, .174),
            3: ("forearm", .066, .132),
            5: ("wrist", .040, .080),
        }[idx]
        parts.append(_mesh(name))
        parts.append(_cyl(radius, length, f"{-a:.12g} 0 0", f"{-alpha:.15g} 0 0", "joint"))
    if idx == 2:
        parts.append(_mesh("service_cover"))
        parts.append(_mesh("line_cover"))
        for x, z in ((-.70 * a, .079), (-.31 * a, .069)):
            parts.append(_cyl(.004, .0025, f"{x:.4f} 0 {z:.4f}", "0 0 0", "joint"))
    if idx == 3:
        for side in (-1, 1):
            parts.append(_steel_disc(.053, .008, f"{-a:.4f} 0 {side * .066:.3f}"))
    if a:
        parts.append(_capsule(r + 0.02, -a, 0))
    if next_dh is not None:
        _, _, d = next_dh
        if d:
            radius = WRIST_SHAFT_R if idx == 5 else r
            parts.append(_capsule(radius + 0.02, 0, d))
        elif not a and idx not in (1, 4):
            parts.append(_col_sphere(kr + 0.01, "0 0 0"))
    else:
        # 法兰壳到 z=0.045，与夹爪安装面相接。
        parts.append(_steel_disc(0.037, 0.007, "0 0 0.0415"))
        parts.append(_cyl(FLANGE_SHAFT_R, 0.038, "0 0 0.019", "0 0 0", "joint"))
        parts.append(_col_cyl(0.037, 0.045, "0 0 0.0225", "0 0 0"))
    parts.append('  </link>')
    return "".join(parts)


def joint_xml(idx, a, alpha, d):
    parent = "base_link" if idx == 1 else f"link_{idx - 1}"
    link = f"link_{idx}"
    axis_frame = f"joint_{idx}_axis" if a or alpha else link
    # Standard DH: Tz(d) Rz(theta) Tx(a) Rx(alpha).
    revolute = (
        f'  <joint name="joint_{idx}" type="revolute">\n'
        f'    <parent link="{parent}"/>\n'
        f'    <child link="{axis_frame}"/>\n'
        f'    <origin xyz="0 0 {d:.12g}" rpy="0 0 0"/>\n'
        f'    <axis xyz="0 0 1"/>\n'
        f'    <limit lower="-3.1416" upper="3.1416" effort="{TMAX[idx-1]:.1f}" velocity="{VEL_LIMIT}"/>\n'
        f'    <dynamics damping="10.0" friction="1.0"/>\n'
        f'  </joint>'
    )
    if axis_frame == link:
        return revolute
    offset = _fixed_joint(f"joint_{idx}_dh_offset", axis_frame, link,
                          f"{a:.12g} 0 0", f"{alpha:.15g} 0 0")
    return f'  <link name="{axis_frame}"/>\n{revolute}\n{offset}'


def main():
    import argparse
    global FINGER_LEN, OPENING, GROOVE
    ap = argparse.ArgumentParser(description="从孪生 DH 生成 URDF（可选夹爪场景/尺寸）")
    ap.add_argument("out", nargs="?", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "urdf", "hydraulic_arm.urdf"),
        help="输出 URDF 路径。仅预览装配时作为现有 URDF 的读取路径")
    ap.add_argument("--rviz-assembly-dir", type=Path,
                    help="Legacy 预览。生成旧装配覆盖层并把描述输出到 stdout")
    ap.add_argument("--preset", choices=sorted(GRIPPER_PRESETS),
                    help="夹爪场景预设：general/sorting/marking/docking")
    ap.add_argument("--tool", choices=("suction", "gripper"),
                    help="末端工具，默认双指夹爪")
    ap.add_argument("--fingers", type=float, help="手指长度 (m)，覆盖 preset")
    ap.add_argument("--opening", type=float, help="最大开口 (m)，覆盖 preset")
    ap.add_argument("--groove", action="store_true", help="夹持面做成 V 型槽（卡圆钢管，分拣默认开）")
    args = ap.parse_args()
    if args.rviz_assembly_dir is not None:
        if any((args.preset, args.tool, args.fingers is not None, args.opening is not None, args.groove)):
            ap.error("装配预览使用现有描述，不能同时设置末端预设")
        print(generate_rviz_assembly(Path(args.out).read_text(encoding="utf-8"), args.rviz_assembly_dir))
        return
    grip_options = args.preset is not None or args.fingers is not None or args.opening is not None or args.groove
    tool = args.tool or "gripper"
    if tool == "suction" and grip_options:
        ap.error("夹爪尺寸和预设仅适用于 --tool gripper")
    if args.preset:
        FINGER_LEN, OPENING = GRIPPER_PRESETS[args.preset]
        GROOVE = (args.preset == "sorting")   # 分拣默认 V 型槽
    if args.fingers is not None:
        FINGER_LEN = args.fingers
    if args.opening is not None:
        OPENING = args.opening
    if args.groove:
        GROOVE = True

    parts = ['<?xml version="1.0"?>',
             '<!-- generated by sim/gazebo_arm/gazebo_arm/gen_urdf.py from the numerical twin '
             'DH/mass/inertia; do not edit by hand -->',
             '<robot name="hydraulic_arm">',
             base_xml(DH[0][2])]
    for i in range(6):
        a, alpha, d = DH[i]
        parts.append(joint_xml(i + 1, a, alpha, d))
        next_dh = DH[i + 1] if i + 1 < 6 else None
        parts.append(link_xml(i + 1, LINKS[i], DH[i], next_dh))
    parts.append(suction_xml() if tool == "suction" else gripper_xml())
    parts.append("</robot>")
    generate_shells(Path(__file__).resolve().parents[1] / "meshes", DH)
    text = "\n".join(parts) + "\n"
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"URDF -> {os.path.normpath(args.out)}  (tool={tool})")


if __name__ == "__main__":
    main()
