"""Refine mechanical interfaces using the existing link-local Blender frames."""

from math import cos, pi, sin, tau
from pathlib import Path
from tempfile import TemporaryDirectory

import bpy

from import_urdf import collada_mesh
from gazebo_arm.visual_meshes import write_shell


WRIST_CASE_SETBACK = .056


def part(parent, name, mesh, finish, location=(0, 0, 0), turned=False):
    obj = bpy.data.objects.new(name, mesh)
    parent.users_collection[0].objects.link(obj)
    obj.parent = parent
    obj.location = location
    obj["finish"] = finish
    obj["turned"] = turned
    return obj


def discard(parent, assets):
    for obj in tuple(parent.children):
        if obj.type == "MESH" and obj.data.name in assets:
            bpy.data.objects.remove(obj, do_unlink=True)


def loft(parent, label, stations, finish, lateral=(0, 1, 0), exponent=.38):
    with TemporaryDirectory(prefix="arm-loft-") as folder:
        path = Path(folder) / f"{label}.dae"
        write_shell(path, stations, lateral_axis=lateral, exponent=exponent)
        mesh = collada_mesh(path)
    return part(parent, label, mesh, finish)


def ring(parent, name, center, profile, finish, sides=64):
    """Closed annular section with the mating axis along local Z."""
    vertices = [(r * cos(tau * i / sides), r * sin(tau * i / sides), z)
                for r, z in profile for i in range(sides)]
    faces = []
    for layer in range(len(profile)):
        a, b = layer * sides, ((layer + 1) % len(profile)) * sides
        for i in range(sides):
            j = (i + 1) % sides
            faces.append((a + i, a + j, b + j, b + i))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    for p in mesh.polygons:
        p.use_smooth = sides > 8 and abs(p.normal.z) < .8
    return part(parent, name, mesh, finish, center, turned=sides > 8)


def cylinder(parent, name, center, radius, height, finish):
    return ring(parent, name, center,
                ((radius, -height / 2), (radius, height / 2),
                 (.0002, height / 2), (.0002, -height / 2)), finish)


def base_and_shoulder():
    base = bpy.data.objects["base_link"]
    discard(base, {"steel_disc", "graphite_disc"})
    foot = next(obj for obj in base.children if obj.type == "MESH" and obj.data.name == "pedestal_foot")
    seat = max(v.co.z for v in foot.data.vertices)
    for i, (x, y) in enumerate(((-.121, -.100), (-.121, .100), (.121, -.100), (.121, .100)), 1):
        ring(base, f"Anchor washer {i}", (x, y, seat), ((.014, -.0003), (.014, .003),
             (.0055, .003), (.0055, -.0003)), "steel")
        ring(base, f"Recessed anchor head {i}", (x, y, seat), ((.0100, .003), (.0096, .011),
             (.004, .011), (.004, .003)), "steel", sides=6)
        cylinder(base, f"Anchor socket floor {i}", (x, y, seat + .0041), .004, .002, "graphite")
    ring(base, "Fixed swivel dust seal", (0, 0, 0),
         ((.093, .076), (.093, .077), (.084, .077), (.084, .076)), "graphite")

    upper = bpy.data.objects["link_2"]
    shoulder = bpy.data.objects["link_1"]
    span = upper.matrix_basis.translation.x
    discard(upper, {"upper_arm"})
    old_barrel = next(obj for obj in upper.children
                      if obj.type == "MESH" and obj.data.name == "graphite_disc" and obj.scale.z > .1)
    bpy.data.objects.remove(old_barrel, do_unlink=True)
    ring(upper, "Shoulder rotating bearing housing", (-span, 0, 0),
         ((.070, -.083), (.070, .083), (.034, .083), (.034, -.083)), "graphite")
    cylinder(shoulder, "Shoulder pin", (0, 0, 0), .032, .267, "steel")
    loft(upper, "Upper arm with elbow fork seat", [
        ((-span + .039, 0, .003), .082, .069), ((-.89 * span, 0, .003), .095, .076),
        ((-.80 * span, 0, .003), .097, .075), ((-.65 * span, 0, .002), .087, .071),
        ((-.40 * span, 0, .001), .073, .065), ((-.24 * span, 0, 0), .063, .060),
        ((-.069, 0, 0), .055, .050),
    ], "cast", exponent=.34)


def elbow():
    upper, forearm = [bpy.data.objects[name] for name in ("link_2", "link_3")]
    span = forearm.matrix_basis.translation.x
    discard(forearm, {"forearm", "graphite_disc", "steel_disc"})
    for side in (-1, 1):
        zs = sorted(side * z for z in (.050, .053, .070, .074))
        loft(upper, f"Elbow fixed cheek {side:+d}", [
            ((-.023, 0, z), width, length)
            for z, (width, length) in zip(zs, [(.057, .079), (.060, .082), (.060, .082), (.057, .079)])
        ], "cast", exponent=.80)
        cylinder(upper, f"Elbow shaft end {side:+d}", (0, 0, side * .077), .042, .007, "steel")
    cylinder(upper, "Elbow fixed shaft", (0, 0, 0), .031, .157, "steel")
    ring(forearm, "Elbow rotating bearing housing", (-span, 0, 0),
         ((.056, -.047), (.060, -.042), (.060, .042), (.056, .047),
          (.0335, .047), (.0335, -.047)), "graphite")
    stations = [
        ((-span + .035, 0, 0), .042, .038), ((-span + .065, 0, 0), .052, .041),
        ((-span + .105, 0, 0), .061, .045), ((-.64 * span, 0, 0), .063, .053),
        ((-.54 * span, 0, 0), .056, .049), ((-.38 * span, 0, 0), .050, .042),
    ]
    bend = bpy.data.objects["joint_4_axis"].matrix_basis.translation.z
    case_end = bend - WRIST_CASE_SETBACK
    curve = min(.20 * span, .78 * case_end)
    for i in range(9):
        t = i / 8
        stations.append(((-curve * (1 - t) ** 2, 0, curve * t ** 2),
                         .046 - .012 * t, .039 - .007 * t))
    stations.append(((0, 0, case_end), .031, .029))
    loft(forearm, "Forearm clear of fixed elbow cheeks", stations, "cast")


def wrist():
    forearm, yoke, rotor, wrist_link = [bpy.data.objects[name]
                                      for name in ("link_3", "link_4", "joint_5_axis", "link_5")]
    discard(yoke, {"steel_disc", "graphite_disc"})
    discard(wrist_link, {"wrist", "graphite_disc"})
    bend = bpy.data.objects["joint_4_axis"].matrix_basis.translation.z
    seat = bend - WRIST_CASE_SETBACK
    ring(forearm, "Wrist roll fixed collar", (0, 0, seat),
         ((.030, -.002), (.030, .0035), (.019, .0035), (.019, -.002)), "steel")
    cylinder(forearm, "Wrist roll pin", (0, 0, seat + .007), .013, .011, "steel")
    bridge = ring(yoke, "Wrist yoke rear flange", (0, -.047, 0),
                  ((.053, -.004), (.056, -.002), (.056, .002), (.053, .004),
                   (.0145, .004), (.0145, -.004)), "graphite")
    bridge.rotation_euler.x = -pi / 2
    for side in (-1, 1):
        zs = sorted(side * z for z in (.043, .045, .055, .058))
        loft(yoke, f"Wrist yoke cheek {side:+d}", [
            ((0, -.019, z), width, height)
            for z, (width, height) in zip(zs, [(.024, .031), (.026, .034), (.026, .034), (.024, .031)])
        ], "cast", lateral=(1, 0, 0), exponent=.61)
        cylinder(yoke, f"Wrist pitch pin cap {side:+d}", (0, 0, side * .0595), .020, .004, "steel")
    cylinder(yoke, "Wrist pitch pin", (0, 0, 0), .014, .117, "steel")
    ring(rotor, "Wrist pitch rotating bearing", (0, 0, 0),
         ((.037, -.0395), (.040, -.036), (.040, .036), (.037, .0395),
          (.016, .0395), (.016, -.0395)), "graphite")
    span = bpy.data.objects["link_6"].matrix_basis.translation.z
    loft(wrist_link, "Wrist output casing", [
        ((0, 0, .023), .031, .032), ((0, 0, .039), .037, .034),
        ((0, 0, .059), .032, .028), ((0, 0, span - .001), .027, .025),
    ], "cast", exponent=.59)


def tool():
    body = bpy.data.objects["gripper_base"]
    discard(body, {"gripper_body", "gripper_rail"})
    loft(body, "Enclosed gripper drive", [
        ((0, 0, 0), .044, .033), ((0, 0, .006), .073, .038),
        ((0, 0, .016), .111, .039), ((0, 0, .028), .114, .039),
        ((0, 0, .034), .112, .036),
    ], "cast")
    for side in (-1, 1):
        x = side * .014
        loft(body, f"Linear jaw guide {side:+d}", [
            ((x, 0, .034), .110, .005), ((x, 0, .0355), .112, .006),
            ((x, 0, .0417), .112, .006), ((x, 0, .043), .110, .005),
        ], "steel")
        for y in (-.065, .065):
            cylinder(body, f"Guide cover fastener {x:+.3f}/{y:+.3f}",
                     (side * .028, y, .0345), .0038, .0015, "graphite")
    for name in ("finger_left", "finger_right"):
        finger = bpy.data.objects[name]
        shoe = next(obj for obj in finger.children
                    if obj.type == "MESH" and obj.data.name == "graphite_block" and obj["finish"] == "graphite")
        bpy.data.objects.remove(shoe, do_unlink=True)
        loft(finger, f"{name} slider shoe", [
            ((0, 0, -.007), .016, .019), ((0, 0, -.0058), .017, .020),
            ((0, 0, .0018), .017, .020), ((0, 0, .003), .015, .018),
        ], "graphite")


def refine_assembly():
    base_and_shoulder()
    elbow()
    wrist()
    tool()
    bpy.context.view_layer.update()
