"""从数值孪生的 DH + 连杆质量/惯量生成 URDF，保持与 sim/hydraulic-arm 同源。

几何（无 CAD 网格时用基本体拼出「像样的工业臂」，仅供 RViz 可视化）：
- base_link：底座立柱（沿 z 到关节 1，d1 高）。
- 每根连杆：一个沿旋转轴 z 的「关节壳」圆柱 + 一段指向下一关节的「连杆体」圆柱；
  连杆体方向由下一关节的 DH (a 沿 x, d 沿 z) 决定，绕 y 转 atan2(a,d) 对齐。
- 末端 link_6：法兰圆柱 + 小夹爪方块。
外形是近似（非精确 CAD）；动力学在 plant.py，不依赖此几何。质量/质心/惯量仍用孪生数值，未改。

用法：python gen_urdf.py [out.urdf]
"""
from __future__ import annotations

import math
import os
import sys

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


# 材质配色（钢铁车间 RAL 方案，内联到每个 visual —— RViz2 对「顶层定义、按名引用」
# 的材质常渲染成默认灰，内联 color 才稳定显示）
MAT = {
    "body":   "1.000 0.843 0.000 1",   # 主体 安全黄  RAL 1003 #FFD700
    "joint":  "0.184 0.310 0.310 1",   # 关节 深灰    RAL 7016 #2F4F4F
    "wrist":  "0.753 0.753 0.753 1",   # 腕部 金属银  RAL 9006 #C0C0C0
    "finger": "0.290 0.333 0.408 1",   # 夹爪 硬化钢  RAL 7015 #4A5568
    "base":   "0.184 0.310 0.310 1",   # 底座 深灰    RAL 7016
    "warn":   "1.000 0.000 0.000 1",   # 警示 红      RAL 3020 #FF0000
    "black":  "0.090 0.090 0.100 1",   # 线缆/密封盖/防尘罩（IP67 特征）
    "sensor": "0.160 0.280 0.500 1",   # 腕部力/扭矩传感器（醒目蓝）
    "camera": "0.050 0.050 0.060 1",   # 指端视觉传感器外壳
    "bolt":   "0.450 0.450 0.480 1",   # 地脚螺栓头
    "grip_face": "0.176 0.216 0.282 1",  # 夹持面 近黑硬化面 #2D3748
}

# 夹爪几何按作业场景可调（指长 m, 最大开口 m）——依钢铁作业工程建议。
# URDF 是静态模型：用 --preset / --fingers / --opening 生成对应场景的爪子。
GRIPPER_PRESETS = {
    "general": (0.100, 0.220),   # 搬运/捆扎/清理：指长 80~120mm，开口 ~200~250mm
    "sorting": (0.120, 0.250),   # 型钢/钢管分拣：指更长、开口更大卡住粗钢
    "marking": (0.065, 0.180),   # 喷号：指短、开口小，定位为主
    "docking": (0.075, 0.180),   # 下水口对接：指中等、精度优先
}
FINGER_LEN = 0.100   # 由 main 按 preset/参数覆盖
OPENING = 0.220
GROOVE = False       # 分拣预设时夹持面做成 V 型槽（卡圆钢管/型钢）


def _mat(name):
    return f'<material name="{name}"><color rgba="{MAT[name]}"/></material>'


# --- 视觉体（仅 visual；碰撞体单独用胶囊，见 _capsule/_col_*）---
def _cyl(radius, length, xyz, rpy, material):
    return (
        f'    <visual>\n'
        f'      <origin xyz="{xyz}" rpy="{rpy}"/>\n'
        f'      <geometry><cylinder radius="{radius:.3f}" length="{length:.4f}"/></geometry>\n'
        f'      {_mat(material)}\n'
        f'    </visual>\n'
    )


def _box(size, xyz, rpy, material):
    return (
        f'    <visual>\n'
        f'      <origin xyz="{xyz}" rpy="{rpy}"/>\n'
        f'      <geometry><box size="{size}"/></geometry>\n'
        f'      {_mat(material)}\n'
        f'    </visual>\n'
    )


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
    plate_r = 0.16
    parts = [
        '  <link name="base_link">\n',
        # 惯量：Gazebo 里无 inertial 的连杆会被丢弃/异常（导致 ros2_control 找不到关节），底座给足质量
        _inertial(20.0, 0.2, 0.2, 0.3, f"0 0 {h/2:.4f}"),
        # 地面安装法兰盘（厚重，螺栓固定到地面——工业现场牢固安装）
        _cyl(plate_r, 0.030, "0 0 0.015", "0 0 0", "base"),
        # 立柱
        _cyl(BASE_R, h, f"0 0 {h/2:.4f}", "0 0 0", "base"),
        # 顶部一圈警示红环（RAL 3020）
        _cyl(BASE_R * 1.04, 0.018, f"0 0 {h-0.012:.4f}", "0 0 0", "warn"),
    ]
    # 四颗地脚螺栓头
    import math as _m
    for k in range(4):
        ang = _m.pi / 4 + k * _m.pi / 2
        bx, by = 0.125 * _m.cos(ang), 0.125 * _m.sin(ang)
        parts.append(_cyl(0.013, 0.022, f"{bx:.4f} {by:.4f} 0.026", "0 0 0", "bolt"))
    # 碰撞：立柱胶囊（带余量）
    parts.append(_col_cyl(BASE_R + 0.02, h, f"0 0 {h/2:.4f}", "0 0 0"))
    parts.append('  </link>')
    return "".join(parts)


def _inertial(mass, ixx, iyy, izz, xyz="0 0 0"):
    return (f'    <inertial>\n'
            f'      <origin xyz="{xyz}" rpy="0 0 0"/>\n'
            f'      <mass value="{mass:.3f}"/>\n'
            f'      <inertia ixx="{ixx:.5f}" ixy="0" ixz="0" iyy="{iyy:.5f}" iyz="0" izz="{izz:.5f}"/>\n'
            f'    </inertial>\n')


def _fixed_joint(name, parent, child, xyz):
    return (f'  <joint name="{name}" type="fixed">\n'
            f'    <parent link="{parent}"/>\n'
            f'    <child link="{child}"/>\n'
            f'    <origin xyz="{xyz}" rpy="0 0 0"/>\n'
            f'  </joint>')


def gripper_xml():
    """夹爪总成：腕(link_6) → 底座板 → 左右扁平手指(主体+深色夹持面+背面槽) + 联动杆 + 相机。

    结构用独立连杆 + fixed 关节拼出「腕→底座→手指」，手指是扁长方体+前端深色夹持面（像正经
    夹爪，不是圆柱棍）。手指固定在额定张开位（开口=OPENING）；做成 prismatic 可开合需 7 轴
    夹爪控制器，超出当前 6-DOF 端边云契约，属后续扩展。指长/开口由 --preset / --fingers /
    --opening 控制（分拣长指大开口、喷号短指等）。
    """
    fl = FINGER_LEN
    off = OPENING / 2.0
    xml = []
    # 底座板（安全黄）+ 联动杆（银）+ 相机
    xml.append(_fixed_joint("gripper_base_joint", "link_6", "gripper_base", "0 0 0.045"))
    base = ['  <link name="gripper_base">\n',
            _inertial(1.5, 0.003, 0.003, 0.004),
            _box("0.060 0.120 0.010", "0 0 0.005", "0 0 0", "body"),            # 底座板 120×60×10
            _cyl(0.006, OPENING * 0.8, "0 0 0.040", "1.5708 0 0", "wrist"),     # 联动杆(横向银柱)
            _box("0.022 0.028 0.016", "0.040 0 0.012", "0 0 0", "camera"),      # 指端视觉传感器(相机)
            _cyl(0.006, 0.010, "0.056 0 0.012", "0 1.5708 0", "black"),         # 相机镜头
            _col_cyl(0.07, 0.012, "0 0 0.006", "1.5708 0 0"),                   # 底座板碰撞(扁圆柱)
            '  </link>']
    xml.append("".join(base))
    # 左右手指：主体(钢色扁长方体) + 内侧夹持面 + 背面驱动槽(黑) + 胶囊碰撞
    for sign in (1, -1):
        side = "right" if sign > 0 else "left"
        name = f"finger_{side}"
        xml.append(_fixed_joint(f"{name}_joint", "gripper_base", name,
                                f"0 {sign*off:.4f} 0.010"))
        link = [f'  <link name="{name}">\n',
                _inertial(0.3, 0.0004, 0.0004, 0.0001, f"0 0 {fl/2:.4f}"),
                _box(f"0.015 0.025 {fl:.3f}", f"0 0 {fl/2:.4f}", "0 0 0", "finger"),
                _box(f"0.006 0.004 {fl*0.5:.3f}",
                     f"0 {sign*0.0145:.4f} {fl*0.5:.4f}", "0 0 0", "black")]      # 背面驱动槽
        if GROOVE:
            # 型钢/钢管分拣：内侧夹持面做成 V 型槽（两块斜面拼），卡住圆钢管/型钢
            for tilt in (0.45, -0.45):
                link.append(_box(f"0.024 0.004 {fl*0.42:.3f}",
                                 f"0 {-sign*0.016:.4f} {fl*0.55:.4f}",
                                 f"{tilt:.4f} 0 0", "grip_face"))
        else:
            link.append(_box(f"0.020 0.004 {fl*0.75:.3f}",
                             f"0 {-sign*0.0145:.4f} {fl*0.55:.4f}", "0 0 0", "grip_face"))
        # 胶囊碰撞：整根手指套一层带余量的紧身衣
        link.append(_col_cyl(0.020, fl, f"0 0 {fl/2:.4f}", "0 0 0"))
        link.append(_col_sphere(0.020, f"0 0 {fl:.4f}"))
        link.append('  </link>')
        xml.append("".join(link))
    return "\n".join(xml)


def link_xml(idx, spec, next_dh):
    m = spec["m"]
    cx, cy, cz = spec["com"]
    ixx, iyy, izz = spec["I"]
    r = LINK_R[idx]
    kr = r + 0.018   # 关节壳略粗于连杆体
    # 配色：1-3 主体（黄杆/深灰关节），4+ 腕部（银），末端夹爪单独钢色
    knuckle_mat = "joint" if idx <= 3 else "wrist"
    body_mat = "body" if idx <= 3 else "wrist"
    parts = [
        f'  <link name="link_{idx}">\n'
        f'    <inertial>\n'
        f'      <origin xyz="{cx:.4f} {cy:.4f} {cz:.4f}" rpy="0 0 0"/>\n'
        f'      <mass value="{m:.3f}"/>\n'
        f'      <inertia ixx="{ixx:.4f}" ixy="0" ixz="0" iyy="{iyy:.4f}" iyz="0" izz="{izz:.4f}"/>\n'
        f'    </inertial>\n'
    ]
    # 关节壳：沿旋转轴 z 的短圆柱 + 两端密封盖（IP67 防尘特征）
    kl = 1.8 * kr
    parts.append(_cyl(kr, kl, "0 0 0", "0 0 0", knuckle_mat))
    parts.append(_cyl(kr + 0.006, 0.012, f"0 0 {kl/2:.4f}", "0 0 0", "black"))   # 上密封盖
    parts.append(_cyl(kr + 0.006, 0.012, f"0 0 {-kl/2:.4f}", "0 0 0", "black"))  # 下密封盖
    if next_dh is not None:
        # 连杆体：从本关节指向下一关节，方向 (a 沿 x, d 沿 z)，绕 y 转 atan2(a,d) 对齐
        a, _, d = next_dh
        length = math.hypot(a, d)
        if length > 0.03:
            beta = math.atan2(a, d)
            parts.append(_cyl(r, length, f"{a/2:.4f} 0 {d/2:.4f}",
                              f"0 {beta:.6f} 0", body_mat))
            # 线缆保护套/拖链：沿大臂/前臂平行走一根细管（贴背侧，+y 偏置）
            if idx in (1, 2):
                parts.append(_cyl(0.013, length * 0.9,
                                  f"{a/2:.4f} {r+0.02:.4f} {d/2:.4f}",
                                  f"0 {beta:.6f} 0", "black"))
            parts.append(_capsule(r + 0.02, a, d))     # 连杆胶囊碰撞（含 next 偏置）
        else:
            parts.append(_col_sphere(kr + 0.01, "0 0 0"))
    else:
        # 末端 link_6：腕部力/扭矩传感器 + 法兰（夹爪总成由 gripper_xml 以独立连杆挂上来）
        parts.append(_box("0.050 0.050 0.014", "0 0 0.006", "0 0 0", "sensor"))
        parts.append(_cyl(0.030, 0.030, "0 0 0.025", "0 0 0", "wrist"))
        parts.append(_col_cyl(0.045, 0.06, "0 0 0.02", "0 0 0"))   # 腕部碰撞
    parts.append('  </link>')
    return "".join(parts)


def joint_xml(idx, a, alpha, d):
    parent = "base_link" if idx == 1 else f"link_{idx - 1}"
    return (
        f'  <joint name="joint_{idx}" type="revolute">\n'
        f'    <parent link="{parent}"/>\n'
        f'    <child link="link_{idx}"/>\n'
        f'    <origin xyz="{a:.4f} 0 {d:.4f}" rpy="{alpha:.6f} 0 0"/>\n'
        f'    <axis xyz="0 0 1"/>\n'
        f'    <limit lower="-3.1416" upper="3.1416" effort="{TMAX[idx-1]:.1f}" velocity="{VEL_LIMIT}"/>\n'
        f'    <dynamics damping="10.0" friction="1.0"/>\n'
        f'  </joint>'
    )


def main():
    import argparse
    global FINGER_LEN, OPENING, GROOVE
    ap = argparse.ArgumentParser(description="从孪生 DH 生成 URDF（可选夹爪场景/尺寸）")
    ap.add_argument("out", nargs="?", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "urdf", "hydraulic_arm.urdf"),
        help="输出 URDF 路径")
    ap.add_argument("--preset", choices=sorted(GRIPPER_PRESETS),
                    help="夹爪场景预设：general/sorting/marking/docking")
    ap.add_argument("--fingers", type=float, help="手指长度 (m)，覆盖 preset")
    ap.add_argument("--opening", type=float, help="最大开口 (m)，覆盖 preset")
    ap.add_argument("--groove", action="store_true", help="夹持面做成 V 型槽（卡圆钢管，分拣默认开）")
    args = ap.parse_args()
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
        parts.append(link_xml(i + 1, LINKS[i], next_dh))
    parts.append(gripper_xml())   # 腕→底座→左右手指 夹爪总成
    parts.append("</robot>")
    text = "\n".join(parts) + "\n"
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"URDF -> {os.path.normpath(args.out)}  (夹爪 指长={FINGER_LEN*1000:.0f}mm 开口={OPENING*1000:.0f}mm)")


if __name__ == "__main__":
    main()
