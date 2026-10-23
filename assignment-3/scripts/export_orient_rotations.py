"""Extract per-vehicle <Name>_root Empty rotations from art-source/orient_all.blend
and save them to art-source/upright_rotations.json.

Run headless:
    /Applications/Blender.app/Contents/MacOS/Blender -b \
        /Users/muzen/Projects/ELVTR/art-source/orient_all.blend \
        --python scripts/export_orient_rotations.py

Output format (consumed by blender_render_v2.py):
    { "<Name>": [rx, ry, rz] }   where rx/ry/rz are degrees, Euler XYZ.
"""
import bpy
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "art-source", "upright_rotations.json")

VEHICLE_NAMES = [
    "Abrams", "Leopard2", "Challenger2", "Bradley", "PzH2000", "Gepard",
    "MRAPUkraine", "TechnicalUkraine", "EWTruckUkraine",
    "T90", "T72", "Koalitsiya", "BMP3", "Tunguska", "BTR3E",
    "TechnicalRussian", "EWTruckRussian",
]

out = {}
missing = []
for name in VEHICLE_NAMES:
    o = bpy.data.objects.get(f"{name}_root")
    if o is None:
        missing.append(name)
        continue
    if o.rotation_mode == "QUATERNION":
        e = o.rotation_quaternion.to_euler("XYZ")
    else:
        e = o.rotation_euler
    out[name] = [
        round(math.degrees(e.x), 2),
        round(math.degrees(e.y), 2),
        round(math.degrees(e.z), 2),
    ]

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    json.dump(out, f, indent=2, sort_keys=True)

print(f"wrote {OUT}")
for k, v in sorted(out.items()):
    print(f"  {k:20s}  euler_deg = ({v[0]:+7.2f}, {v[1]:+7.2f}, {v[2]:+7.2f})")
if missing:
    print("MISSING:", missing)
