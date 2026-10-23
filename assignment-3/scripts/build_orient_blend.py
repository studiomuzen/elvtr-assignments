"""
Build art-source/orient_all.blend — a hand-correction scene for vehicle orientations.

For each of the 17 vehicles:
  1. Import the GLB.
  2. Flatten the hierarchy, apply transforms, cull backdrops.
  3. Scale to real-world hull length (using the same hull_length_m as the production
     render pipeline — all vehicles become the correct size relative to each other).
  4. Parent every imported mesh to an Empty named "<Name>_root" positioned on the row.
  5. Add a 3D text label with the vehicle name above the parent.
Then add:
  - A grey ground plane at Z=0 spanning the entire row.
  - A camera positioned on -Y looking toward +Y so every vehicle is seen in profile.
  - Default lighting.

The scene is saved to art-source/orient_all.blend. The user opens it in Blender,
selects each "<Name>_root" empty, rotates it until the vehicle is upright
(wheels/tracks on the ground), and saves. The render script reads each empty's
rotation from this .blend afterward — no auto-detection.

Headless usage:
    /Applications/Blender.app/Contents/MacOS/Blender -b --python scripts/build_orient_blend.py
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import bpy
import mathutils
from mathutils import Vector

# Reuse the production normalization helpers from blender_render_v2.py so the orient
# scene matches the actual render pipeline (same backdrop culling, same scaling).
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from blender_render_v2 import (  # noqa: E402
    flatten_hierarchy,
    apply_all_transforms,
    delete_backdrops,
    scale_and_center,
    imported_bbox,
    report_textures,
)

ROOT = HERE.parent
MODELS = ROOT / "art-source" / "models"
OUT_BLEND = ROOT / "art-source" / "orient_all.blend"

# (CanonicalName, glb filename, hull_length_m) — matches render_upright_check.py
VEHICLES = [
    ("Abrams",            "m1a2_abrams.glb",       7.9),
    ("Leopard2",          "leopard_2.glb",         7.7),
    ("Challenger2",       "challenger_2.glb",      8.3),
    ("Bradley",           "bradley.glb",           6.6),
    ("PzH2000",           "pzh_2000.glb",          7.9),
    ("Gepard",            "gepard.glb",            7.7),
    ("MRAPUkraine",       "mrap_ukraine.glb",      6.5),
    ("TechnicalUkraine",  "technical_ukraine.glb", 5.3),
    ("EWTruckUkraine",    "ew_truck_ukraine.glb",  7.5),
    ("T90",               "t90.glb",               6.9),
    ("T72",               "t72.glb",               6.9),
    ("Koalitsiya",        "koalitsiya_sv.glb",     9.0),
    ("BMP3",              "bmp3.glb",              7.1),
    ("Tunguska",          "tunguska.glb",          7.9),
    ("BTR3E",             "btr_3e.glb",            7.6),
    ("TechnicalRussian",  "technical_russian.glb", 5.3),
    ("EWTruckRussian",    "ew_truck_russian.glb",  7.5),
]

ROW_SPACING_M = 15.0  # meters between vehicle centers along +X


def wipe_scene() -> None:
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh, do_unlink=True)
    for cam in list(bpy.data.cameras):
        bpy.data.cameras.remove(cam, do_unlink=True)
    for curve in list(bpy.data.curves):
        bpy.data.curves.remove(curve, do_unlink=True)


def set_viewport_shading_textured(scene) -> None:
    """Blender saves viewport state in the .blend; set it to Material Preview so the user
    sees textured vehicles when they open the file."""
    try:
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        space.shading.type = "MATERIAL"
    except Exception:
        pass


def make_ground_plane(x_center: float, x_span: float) -> None:
    bpy.ops.mesh.primitive_plane_add(size=1, location=(x_center, 0, 0))
    plane = bpy.context.object
    plane.name = "Ground"
    plane.scale = (x_span, 40.0, 1.0)
    # Flat grey material
    mat = bpy.data.materials.new(name="GroundGrey")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.42, 0.42, 0.45, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.95
    plane.data.materials.append(mat)


def add_lighting() -> None:
    # Sun
    sun_data = bpy.data.lights.new("Sun", type="SUN")
    sun_data.energy = 4.0
    sun_data.angle = math.radians(3.0)
    sun = bpy.data.objects.new("Sun", sun_data)
    bpy.context.collection.objects.link(sun)
    sun.location = (0, -20, 30)
    sun.rotation_euler = (math.radians(50), 0, math.radians(25))

    # Fill
    fill_data = bpy.data.lights.new("Fill", type="AREA")
    fill_data.energy = 400.0
    fill_data.size = 50.0
    fill = bpy.data.objects.new("Fill", fill_data)
    bpy.context.collection.objects.link(fill)
    fill.location = (0, 30, 20)
    fill.rotation_euler = (math.radians(-45), 0, 0)


def add_camera(scene, x_center: float, x_span: float) -> None:
    cam_data = bpy.data.cameras.new("OrientCam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = max(x_span + 10.0, 40.0)
    cam_data.clip_start = 0.1
    cam_data.clip_end = 500.0
    cam = bpy.data.objects.new("OrientCam", cam_data)
    bpy.context.collection.objects.link(cam)
    # Side-view: camera on -Y side, looking +Y across the row.
    cam.location = (x_center, -50.0, 6.0)
    cam.rotation_euler = (math.radians(85.0), 0.0, 0.0)
    scene.camera = cam


def add_label(name: str, x: float) -> None:
    bpy.ops.object.text_add(location=(x, -4.0, 6.0))
    txt = bpy.context.object
    txt.name = f"Label_{name}"
    txt.data.body = name
    txt.data.size = 1.2
    txt.data.align_x = "CENTER"
    txt.rotation_euler = (math.radians(90), 0, 0)  # face the camera on -Y
    # Dark label material so it stands out on grey ground.
    mat = bpy.data.materials.new(name=f"Label_{name}_Mat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.9, 0.9, 0.95, 1.0)
        bsdf.inputs["Emission Color"].default_value = (0.9, 0.9, 0.95, 1.0)
        bsdf.inputs["Emission Strength"].default_value = 0.3
    txt.data.materials.append(mat)


def _top_level_objs(objs):
    """Return top-level objects (no parent) from `objs`."""
    return [o for o in objs if o.name in bpy.data.objects and o.parent is None]


def import_one_vehicle(name: str, glb_name: str, length_m: float, x: float) -> None:
    glb_path = MODELS / glb_name
    if not glb_path.exists():
        print(f"[skip] {name}: no GLB at {glb_path}")
        return

    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(glb_path))
    imported = list(set(bpy.data.objects) - before)
    print(f"[import] {name}  objs={len(imported)}")

    flatten_hierarchy(imported)
    apply_all_transforms(imported)
    removed = delete_backdrops(imported)
    if removed:
        print(f"[cull] {name}: {removed}")

    # Scale to real meters AT ORIGIN. Then translate to row position.
    scale_and_center(imported, length_m)

    # Translate every mesh by +x so the vehicle lands on the row.
    for o in imported:
        if o.type == "MESH" and o.name in bpy.data.objects:
            o.location.x += x

    bpy.context.view_layer.update()

    # Create the parent empty at the vehicle's position; parent each imported top-level
    # mesh to it with keep_transform=True so the user can select the empty and rotate the
    # whole model as one unit without disturbing child offsets.
    empty = bpy.data.objects.new(f"{name}_root", None)
    empty.location = (x, 0.0, 0.0)
    empty.empty_display_type = "ARROWS"
    empty.empty_display_size = 2.0
    bpy.context.collection.objects.link(empty)

    bpy.ops.object.select_all(action="DESELECT")
    for o in _top_level_objs(imported):
        if o is empty:
            continue
        o.select_set(True)
    empty.select_set(True)
    bpy.context.view_layer.objects.active = empty
    bpy.ops.object.parent_set(type="OBJECT", keep_transform=True)

    # Rename every child mesh so they don't clash across vehicles.
    for i, o in enumerate(imported):
        if o.type == "MESH" and o.name in bpy.data.objects:
            o.name = f"{name}_mesh_{i:02d}"

    add_label(name, x)


def main() -> None:
    print(f"Building {OUT_BLEND} …")
    wipe_scene()
    scene = bpy.context.scene

    # Scene units in meters
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0

    # Lay vehicles along +X. Center the row at x=0.
    n = len(VEHICLES)
    x_positions = [(i - (n - 1) / 2.0) * ROW_SPACING_M for i in range(n)]

    add_lighting()

    for (name, glb, length_m), x in zip(VEHICLES, x_positions):
        print(f"\n--- {name} @ x={x:+.1f} ---")
        import_one_vehicle(name, glb, length_m, x)

    # Ground span: from leftmost - margin to rightmost + margin
    x_center = sum(x_positions) / len(x_positions)
    x_span = (max(x_positions) - min(x_positions)) + ROW_SPACING_M * 2
    make_ground_plane(x_center, x_span)

    add_camera(scene, x_center, x_span)

    # Rendering engine + colour management match the production pipeline.
    scene.render.engine = "BLENDER_EEVEE"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.exposure = 0.8

    # Try to tell the file to open with material-preview shading.
    set_viewport_shading_textured(scene)

    OUT_BLEND.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT_BLEND))
    print(f"\nSaved {OUT_BLEND}")


if __name__ == "__main__":
    main()
