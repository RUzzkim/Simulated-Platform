"""Generate original tapered shells in the arm's existing DH link frames."""

import math
from pathlib import Path

import numpy as np


WRIST_CASE_SETBACK = 0.027


FINISHES = {
    "cast": ("0.73 0.75 0.77 1", "0.28 0.30 0.32 1", 26),
    "steel": ("0.58 0.61 0.64 1", "0.85 0.87 0.91 1", 66),
    "graphite": ("0.24 0.26 0.28 1", "0.23 0.25 0.28 1", 40),
    "cover": ("0.44 0.47 0.50 1", "0.25 0.27 0.29 1", 34),
}

MESH_FINISH = {
    "pedestal_foot": "graphite",
    "line_cover": "graphite",
    "gripper_rail": "graphite",
    "service_cover": "cover",
    "finger": "steel",
    "steel_disc": "steel",
    "graphite_disc": "graphite",
    "graphite_block": "graphite",
}


def _source(identifier, vectors):
    array = " ".join(f"{value:.7g}" for vector in vectors for value in vector)
    return f"""<source id="{identifier}">
  <float_array id="{identifier}-array" count="{len(vectors) * 3}">{array}</float_array>
  <technique_common><accessor source="#{identifier}-array" count="{len(vectors)}" stride="3">
    <param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/>
  </accessor></technique_common>
</source>"""


def write_shell(path: Path, stations, lateral_axis=(0, 1, 0), exponent=0.65, sides=64, finish=None):
    """Loft rounded rectangular sections perpendicular to the given lateral axis."""
    centers = np.array([station[0] for station in stations], dtype=float)
    lateral_axis = np.array(lateral_axis)
    rings = []
    for index, (_, width_y, width_normal) in enumerate(stations):
        tangent = centers[min(index + 1, len(centers) - 1)] - centers[max(index - 1, 0)]
        tangent /= np.linalg.norm(tangent)
        normal = np.cross(tangent, lateral_axis)
        ring = []
        for side in range(sides):
            phase = 2 * math.pi * side / sides
            c, s = math.cos(phase), math.sin(phase)
            lateral = math.copysign(abs(c) ** exponent, c) * width_y
            radial = math.copysign(abs(s) ** exponent, s) * width_normal
            ring.append(centers[index] + lateral_axis * lateral + normal * radial)
        rings.append(ring)

    positions = [point for ring in rings for point in ring] + [centers[0], centers[-1]]
    normals = []
    faces = []
    for index, ring in enumerate(rings):
        previous = rings[max(index - 1, 0)]
        following = rings[min(index + 1, len(rings) - 1)]
        for side in range(sides):
            nxt = (side + 1) % sides
            across = ring[nxt] - ring[(side - 1) % sides]
            along = following[side] - previous[side]
            normal = np.cross(across, along)
            normals.append(normal / np.linalg.norm(normal))
            if index < len(rings) - 1:
                a, b = index * sides + side, index * sides + nxt
                faces.extend((((a, a), (b, b), (a + sides, a + sides)),
                              ((b, b), (b + sides, b + sides), (a + sides, a + sides))))
    cap_normal = len(normals)
    for vec in (centers[0] - centers[1], centers[-1] - centers[-2]):
        normals.append(vec / np.linalg.norm(vec))
    last = (len(rings) - 1) * sides
    for side in range(sides):
        nxt = (side + 1) % sides
        faces.extend((((len(positions) - 2, cap_normal), (nxt, cap_normal), (side, cap_normal)),
                      ((len(positions) - 1, cap_normal + 1), (last + side, cap_normal + 1),
                       (last + nxt, cap_normal + 1))))
    write_mesh(path, positions, normals, faces, finish)


def write_mesh(path, positions, normals, faces, finish=None):
    diffuse, specular, shininess = FINISHES[finish or MESH_FINISH.get(path.stem, "cast")]
    indices = " ".join(str(index) for triangle in faces for corner in triangle for index in corner)
    path.write_text(f'''<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
<asset><unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset>
<library_effects><effect id="finish-effect"><profile_COMMON><technique sid="common"><phong>
  <ambient><color>{diffuse}</color></ambient>
  <diffuse><color>{diffuse}</color></diffuse>
  <specular><color>{specular}</color></specular><shininess><float>{shininess}</float></shininess>
</phong></technique></profile_COMMON></effect></library_effects>
<library_materials><material id="finish" name="industrial_finish"><instance_effect url="#finish-effect"/></material></library_materials>
<library_geometries><geometry id="shell"><mesh>
  {_source("positions", positions)}
  {_source("normals", normals)}
  <vertices id="vertices"><input semantic="POSITION" source="#positions"/></vertices>
  <triangles count="{len(faces)}" material="finish-slot">
    <input semantic="VERTEX" source="#vertices" offset="0"/><input semantic="NORMAL" source="#normals" offset="1"/>
    <p>{indices}</p>
  </triangles>
</mesh></geometry></library_geometries>
<library_visual_scenes><visual_scene id="scene"><node id="body"><instance_geometry url="#shell">
  <bind_material><technique_common><instance_material symbol="finish-slot" target="#finish"/></technique_common></bind_material>
</instance_geometry></node></visual_scene></library_visual_scenes>
<scene><instance_visual_scene url="#scene"/></scene>
</COLLADA>
''', encoding="utf-8", newline="\n")


def upper_arm_stations(upper):
    # The shoulder eye is part of the same casting as the arm. Its round nose
    # wraps behind the pivot and blends into the body before the access panel.
    shoulder_eye = []
    for degrees in range(6, 91, 6):
        phase = math.radians(degrees)
        shoulder_eye.append(((-upper - .086 * math.cos(phase), 0, 0),
                             .094 * math.sin(phase), .060 + .015 * math.sin(phase)))
    return shoulder_eye + [
        ((-.97 * upper, 0, .001), .096, .0755),
        ((-.93 * upper, 0, .002), .099, .076),
        ((-.87 * upper, 0, .003), .099, .076),
        ((-.78 * upper, 0, .003), .096, .0745),
        ((-.65 * upper, 0, .002), .087, .071),
        ((-.40 * upper, 0, .001), .073, .065),
        ((-.20 * upper, 0, 0), .064, .060),
        ((-.06 * upper, 0, 0), .059, .055),
        ((0, 0, 0), .054, .049),
    ]


def generate_shells(folder: Path, dh):
    folder.mkdir(parents=True, exist_ok=True)
    upper, lower, bend, wrist = dh[1][0], dh[2][0], dh[3][2], dh[5][2]
    base_top = max(dh[0][2] - .104, .030)
    write_shell(folder / "pedestal_foot.dae", [
        ((0, 0, 0), .131, .147),
        ((0, 0, .05 * base_top), .139, .153),
        ((0, 0, .30 * base_top), .139, .153),
        ((0, 0, .37 * base_top), .132, .148),
    ], exponent=.38)
    write_shell(folder / "pedestal.dae", [
        ((0, 0, .366 * base_top), .106, .117),
        ((0, 0, .46 * base_top), .104, .114),
        ((0, 0, .89 * base_top), .087, .096),
        ((0, 0, base_top), .080, .090),
    ], exponent=.45)
    write_shell(folder / "shoulder_cheek.dae", [
        ((0, -.081, 0), .054, .024),
        ((0, -.077, 0), .061, .026),
        ((0, -.070, 0), .065, .028),
        ((0, -.050, 0), .066, .028),
        ((0, -.025, 0), .064, .028),
        ((0, .000, 0), .062, .028),
        ((0, .018, 0), .060, .028),
        ((0, .034, 0), .054, .028),
        ((0, .048, 0), .044, .026),
        ((0, .058, 0), .032, .022),
        ((0, .064, 0), .018, .015),
        ((0, .067, 0), .007, .007),
    ], lateral_axis=(1, 0, 0), exponent=.37, sides=96)
    write_shell(folder / "upper_arm.dae", upper_arm_stations(upper), exponent=.40, sides=96)
    write_shell(folder / "service_cover.dae", [
        ((-.78 * upper, 0, .077), .010, .0015),
        ((-.77 * upper, 0, .077), .022, .0025),
        ((-.75 * upper, 0, .0765), .031, .003),
        ((-.72 * upper, 0, .076), .036, .0035),
        ((-.64 * upper, 0, .074), .038, .0035),
        ((-.41 * upper, 0, .068), .034, .0035),
        ((-.30 * upper, 0, .0655), .028, .0035),
        ((-.26 * upper, 0, .0645), .023, .003),
        ((-.24 * upper, 0, .0635), .016, .0025),
        ((-.23 * upper, 0, .063), .008, .0015),
    ], exponent=.43, sides=96)
    write_shell(folder / "line_cover.dae", [
        ((-.84 * upper, 0, -.066), .009, .003),
        ((-.78 * upper, 0, -.072), .022, .006),
        ((-.44 * upper, 0, -.064), .018, .006),
        ((-.22 * upper, 0, -.055), .009, .003),
    ], exponent=.58)
    forearm = [
        ((-lower, 0, 0), .061, .054),
        ((-.95 * lower, 0, 0), .068, .059),
        ((-.78 * lower, 0, 0), .064, .057),
        ((-.54 * lower, 0, 0), .056, .049),
        ((-.38 * lower, 0, 0), .050, .042),
    ]
    case_end = bend - WRIST_CASE_SETBACK
    curve = min(.20 * lower, .78 * case_end)
    for i in range(9):
        t = i / 8
        forearm.append(((-curve * (1 - t) ** 2, 0, curve * t ** 2),
                        .046 - .012 * t, .039 - .007 * t))
    forearm.append(((0, 0, case_end), .031, .029))
    write_shell(folder / "forearm.dae", forearm, exponent=.38)
    write_shell(folder / "wrist.dae", [
        ((0, 0, 0), .038, .033),
        ((0, 0, .23 * wrist), .037, .032),
        ((0, 0, .68 * wrist), .029, .027),
        ((0, 0, wrist), .025, .024),
    ], exponent=.59)
    write_shell(folder / "gripper_body.dae", [
        ((0, 0, 0), .041, .032),
        ((0, 0, .005), .046, .037),
        ((0, 0, .026), .046, .037),
        ((0, 0, .034), .041, .032),
    ], exponent=.43)
    write_shell(folder / "gripper_rail.dae", [
        ((0, 0, .034), .113, .016),
        ((0, 0, .038), .1195, .021),
        ((0, 0, .046), .1195, .021),
        ((0, 0, .050), .113, .016),
    ], exponent=.36)
    write_shell(folder / "finger.dae", [
        ((0, 0, 0), .012, .012),
        ((0, 0, .006), .012, .014),
        ((0, 0, .036), .012, .012),
        ((0, 0, .059), .012, .010),
        ((0, 0, .065), .010, .008),
    ], exponent=.48)

    disc = [
        ((0, 0, -.50), .93, .93),
        ((0, 0, -.36), 1.0, 1.0),
        ((0, 0, .36), 1.0, 1.0),
        ((0, 0, .50), .93, .93),
    ]
    for finish in ("steel", "cast", "graphite"):
        write_shell(folder / f"{finish}_disc.dae", disc, exponent=1.0)
    write_shell(folder / "graphite_block.dae", [
        ((0, 0, -.50), .465, .465),
        ((0, 0, -.41), .50, .50),
        ((0, 0, .41), .50, .50),
        ((0, 0, .50), .465, .465),
    ], exponent=.18)
