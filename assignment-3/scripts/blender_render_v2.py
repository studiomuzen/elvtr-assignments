"""
Blender headless render pipeline v2.

Fixes v1's problems:
  * Normalizes each GLB: applies transforms, auto-orients so tracks/wheels face -Z (world down),
    centers on origin, drops base to Y=0.
  * Real-world scale: looks up vehicle length in meters, scales uniformly.
  * Rotation via empty parent — the vehicle turns in place, never tumbles.
  * Rebuilds lighting (sun top-left + fill + world ambient) and color management (Standard, exposure
    bumped so GLB textures aren't crushed).
  * One fixed orthographic camera + ortho scale across the whole roster.
  * Transparent PNG output.

Usage (test on three):
    blender -b --python scripts/blender_render_v2.py -- \
        --input art-source/models/m1a2_abrams.glb \
        --out-dir art-source/renders_v2/abrams \
        --length 9.83 \
        --steps 16

The script does NOT depend on any template .blend — it starts from an empty scene and
builds camera + lights from scratch so the setup is identical for every vehicle.
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

import bpy
import mathutils
from mathutils import Vector


def parse_cli():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--length", type=float, required=True, help="Real-world vehicle length in meters (longest horizontal axis).")
    p.add_argument("--steps", type=int, default=16)
    p.add_argument("--ortho-scale", type=float, default=14.0, help="Ortho camera scale (vertical world span in meters at camera framing).")
    p.add_argument("--camera-pitch-deg", type=float, default=40.0)
    p.add_argument("--camera-yaw-deg", type=float, default=45.0)
    p.add_argument("--resolution", type=int, default=512, help="Square render size in pixels.")
    p.add_argument("--exposure", type=float, default=0.8, help="Scene view exposure (stops). Positive brightens.")
    p.add_argument("--view", choices=["diamond", "side"], default="diamond",
                   help="Camera framing. 'diamond' = RTS yaw/pitch; 'side' = pure profile (yaw 90, pitch 0).")
    p.add_argument("--prefix", default="frame_", help="Output filename prefix (e.g. 'check_').")
    p.add_argument("--name", default=None,
                   help="Canonical vehicle name (e.g. 'Abrams', 'T90'). Used to look up the per-vehicle upright "
                        "rotation in --upright-rotations.")
    p.add_argument("--upright-rotations", default=None,
                   help="Path to upright_rotations.json extracted from art-source/orient_all.blend. "
                        "Defaults to <repo>/art-source/upright_rotations.json. The orient step applies the "
                        "per-vehicle Euler-XYZ (degrees) from this file. If the file or entry is missing, "
                        "identity is applied (no rotation).")
    p.add_argument("--orientation-json", default=None,
                   help="DEPRECATED (orient_all.blend is now the source of truth). Kept for backwards compat; "
                        "no longer written to.")
    return p.parse_args(argv)


def reset_scene():
    """Wipe the default scene so nothing from startup leaks into the render."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for col in list(bpy.data.collections):
        if col.name != "Collection":
            bpy.data.collections.remove(col)


def setup_render(scene, resolution, exposure):
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.film_transparent = True
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"

    # Color management: Standard (not AgX/Filmic). Raise exposure a bit so GLB albedo textures aren't crushed.
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = exposure
    scene.view_settings.gamma = 1.0

    # World ambient light so no face is pure black.
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()
    bg = nodes.new("ShaderNodeBackground")
    # Lower ambient so hull sides take real shadow from the key light.
    bg.inputs["Color"].default_value = (0.55, 0.57, 0.62, 1.0)
    bg.inputs["Strength"].default_value = 0.35
    out = nodes.new("ShaderNodeOutputWorld")
    links.new(bg.outputs["Background"], out.inputs["Surface"])


def add_lights():
    # KEY SUN — strong, top-left of the ortho camera framing, small angle = sharp shadows.
    # Camera yaw=45°, pitch=40°, looking at origin from upper-left-front corner (world: -X, -Y, +Z).
    # Light coming from the same hemisphere brightens the "camera-facing" turret top; put the sun
    # a little further to the camera's upper-left so hull side (+X side) is in shadow.
    sun_data = bpy.data.lights.new("Sun", type="SUN")
    sun_data.energy = 10.5
    sun_data.angle = math.radians(2.0)
    sun = bpy.data.objects.new("Sun", sun_data)
    bpy.context.collection.objects.link(sun)
    sun.location = (12.0, -12.0, 18.0)
    sun.rotation_euler = (math.radians(50), math.radians(-30), math.radians(40))

    # DIM FILL — low-energy area light from the shadow side so hull-sides aren't crushed.
    fill_data = bpy.data.lights.new("Fill", type="AREA")
    fill_data.energy = 90.0
    fill_data.size = 10.0
    fill = bpy.data.objects.new("Fill", fill_data)
    bpy.context.collection.objects.link(fill)
    fill.location = (-7.0, 10.0, 6.0)
    fill.rotation_euler = (math.radians(70), math.radians(25), math.radians(-20))

    # RIM — grazing light from behind the vehicle (opposite camera) to highlight the top edge of
    # the turret and hull against the dark background. Area light, mid energy.
    rim_data = bpy.data.lights.new("Rim", type="AREA")
    rim_data.energy = 180.0
    rim_data.size = 6.0
    rim = bpy.data.objects.new("Rim", rim_data)
    bpy.context.collection.objects.link(rim)
    rim.location = (8.0, 10.0, 10.0)
    rim.rotation_euler = (math.radians(100), math.radians(-15), math.radians(-45))


def add_camera(scene, ortho_scale, pitch_deg, yaw_deg):
    cam_data = bpy.data.cameras.new("Camera")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = ortho_scale
    cam_data.clip_start = 0.1
    cam_data.clip_end = 100.0
    cam = bpy.data.objects.new("Camera", cam_data)
    bpy.context.collection.objects.link(cam)
    # Position the camera above the origin at the diamond angle, pointing at origin.
    distance = 20.0
    pitch = math.radians(pitch_deg)
    yaw = math.radians(yaw_deg)
    cam.location = (
        -distance * math.sin(yaw) * math.cos(pitch),
        -distance * math.cos(yaw) * math.cos(pitch),
        distance * math.sin(pitch),
    )
    # Point at origin
    direction = Vector((0, 0, 0)) - Vector(cam.location)
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam


def import_glb(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    after = set(bpy.data.objects)
    imported = list(after - before)
    return imported


def imported_bbox(imported):
    """World-space AABB of all mesh vertices in `imported`. Uses actual vertex positions
    (not obj.bound_box) because Blender's bound_box cache does not refresh immediately after
    transform_apply in headless mode."""
    mins = Vector((math.inf, math.inf, math.inf))
    maxs = Vector((-math.inf, -math.inf, -math.inf))
    count = 0
    for obj in imported:
        if obj.type != "MESH" or obj.name not in bpy.data.objects:
            continue
        mw = obj.matrix_world
        for v in obj.data.vertices:
            w = mw @ v.co
            if w.x < mins.x: mins.x = w.x
            if w.y < mins.y: mins.y = w.y
            if w.z < mins.z: mins.z = w.z
            if w.x > maxs.x: maxs.x = w.x
            if w.y > maxs.y: maxs.y = w.y
            if w.z > maxs.z: maxs.z = w.z
            count += 1
    if count == 0:
        return None, None
    return mins, maxs


def flatten_hierarchy(objs):
    """Unparent every imported object (keeping world transforms), delete scaffold empties, and
    make every mesh's data single-user. Many Sketchfab/Collada exports share mesh data across
    linked instances (Material2.001, Material2.002 all point to the same bpy.data.meshes); without
    single-user, bpy.ops.object.transform_apply silently refuses to bake vertex changes."""
    # 1. Clear every parent, keep world transforms
    bpy.ops.object.select_all(action="DESELECT")
    first_live = None
    for o in objs:
        if o.name not in bpy.data.objects:
            continue
        o.select_set(True)
        if first_live is None:
            first_live = o
    if first_live is not None:
        bpy.context.view_layer.objects.active = first_live
        bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")

    # 2. Remove scaffold empties.
    for o in list(objs):
        if o.name not in bpy.data.objects:
            continue
        if o.type == "EMPTY":
            bpy.data.objects.remove(o, do_unlink=True)
            try:
                objs.remove(o)
            except ValueError:
                pass

    # 3. Make mesh data single-user so transform_apply actually bakes vertex positions.
    bpy.ops.object.select_all(action="DESELECT")
    mesh_sel = [o for o in objs if o.name in bpy.data.objects and o.type == "MESH"]
    for o in mesh_sel:
        o.select_set(True)
    if mesh_sel:
        bpy.context.view_layer.objects.active = mesh_sel[0]
        bpy.ops.object.make_single_user(object=True, obdata=True, material=False, animation=False)


def apply_all_transforms(objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        if o.type == "MESH":
            o.select_set(True)
    if bpy.context.selected_objects:
        bpy.context.view_layer.objects.active = bpy.context.selected_objects[0]
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def _top_level_ancestors(objs, exclude):
    """Return the set of top-level ancestors (parent==None) for every obj in `objs`,
    excluding anything in `exclude`. GLBs often import meshes under empties — we need to
    reparent the EMPTY, not the mesh, so the whole hierarchy follows."""
    tops = set()
    for o in objs:
        if o.name not in bpy.data.objects:
            continue
        if o in exclude:
            continue
        cur = o
        while cur.parent is not None and cur.parent not in exclude:
            cur = cur.parent
        if cur not in exclude:
            tops.add(cur)
    return tops


def _parent_to_empty(objs, empty):
    """Re-parent every TOP-LEVEL ancestor of each imported object to `empty` using the operator
    so matrix_parent_inverse is set correctly. Without the operator, children do not inherit
    the parent's scale/rotation."""
    tops = _top_level_ancestors(objs, exclude={empty})
    if not tops:
        return False
    bpy.ops.object.select_all(action="DESELECT")
    for t in tops:
        t.select_set(True)
    empty.select_set(True)
    bpy.context.view_layer.objects.active = empty
    bpy.ops.object.parent_set(type="OBJECT", keep_transform=True)
    return True


def delete_backdrops(objs):
    """Remove ground planes / backdrops / shadow catchers that polluted the GLB. Two detectors:
       1. Mesh name hint (ground / plane / floor / backdrop / shadow).
       2. Very flat mesh whose footprint is >= 50% of overall bbox (ratio of smallest dim to
          largest dim < 0.03). Vehicles are never that flat.
    Returns the trimmed list and the names that were removed.
    """
    removed = []
    name_hits = ("ground", "plane", "floor", "backdrop", "shadow", "base_plate")
    # Pass 1: name hints
    for o in list(objs):
        if o.type != "MESH":
            continue
        nm = o.name.lower()
        if any(h in nm for h in name_hits):
            removed.append(o.name)
            bpy.data.objects.remove(o, do_unlink=True)
            try:
                objs.remove(o)
            except ValueError:
                pass
    # Pass 2: flat-plane heuristic (recompute bbox after name pass)
    all_mins, all_maxs = imported_bbox(objs)
    if all_mins is None:
        return removed
    overall_max = max((all_maxs - all_mins).x, (all_maxs - all_mins).y, (all_maxs - all_mins).z)
    for o in list(objs):
        if o.type != "MESH":
            continue
        corners = [o.matrix_world @ Vector(c) for c in o.bound_box]
        xs = [c.x for c in corners]; ys = [c.y for c in corners]; zs = [c.z for c in corners]
        d = sorted([max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)])
        if d[2] == 0:
            continue
        flatness = d[0] / d[2]
        footprint = d[2] / overall_max
        if flatness < 0.03 and footprint > 0.5:
            removed.append(o.name)
            bpy.data.objects.remove(o, do_unlink=True)
            try:
                objs.remove(o)
            except ValueError:
                pass
    return removed


def _bake_rotation(objs, rot_matrix):
    """Rotate every vertex of every mesh in `objs` by `rot_matrix` (a mathutils.Matrix) IN WORLD
    space. Bypasses bpy.ops operators because they're unreliable in headless mode with linked
    GLB data. Resets each mesh's matrix_world to identity so world-coords == local-coords after."""
    for o in list(objs):
        if o.type != "MESH" or o.name not in bpy.data.objects:
            continue
        mw = o.matrix_world.copy()
        mesh = o.data
        combined = rot_matrix @ mw
        for v in mesh.vertices:
            v.co = combined @ v.co
        o.matrix_world = mathutils.Matrix.Identity(4)
        mesh.update()
    bpy.context.view_layer.update()


def _hard_bake_matrix_world(objs):
    """Bake every mesh's matrix_world into vertex positions and reset matrix_world to identity.
    This is the equivalent of transform_apply(location+rotation+scale), but implemented via
    direct vertex writes so that shared/linked GLB mesh data cannot cause silent skips.

    Call this AFTER flatten_hierarchy so there are no empties, scene parents, or glTF-root
    rotations left to inherit from — the caller holds a flat list of mesh objects."""
    import mathutils as _mu
    I = _mu.Matrix.Identity(4)
    for o in list(objs):
        if o.type != "MESH" or o.name not in bpy.data.objects:
            continue
        mw = o.matrix_world.copy()
        # Skip if already identity (avoid pointless vertex rewrites).
        if (mw - I).to_3x3().to_4x4().determinant() == 0 and \
           abs(mw.translation.length) < 1e-6 and \
           abs(mw.to_3x3().determinant() - 1.0) < 1e-6:
            continue
        mesh = o.data
        for v in mesh.vertices:
            v.co = mw @ v.co
        o.matrix_world = I
        mesh.update()
    bpy.context.view_layer.update()


def _bbox_dims(objs):
    """Return (L, W, H) sorted large→small from the current world-space AABB. L is longest,
    W middle, H shortest — regardless of which world axis each one currently lives on."""
    mins, maxs = imported_bbox(objs)
    if mins is None:
        return (0.0, 0.0, 0.0)
    s = maxs - mins
    vals = sorted([s.x, s.y, s.z], reverse=True)
    return (vals[0], vals[1], vals[2])


def _bbox_xyz(objs):
    """Return (dx, dy, dz) world-axis dims and which axis label is longest / shortest."""
    mins, maxs = imported_bbox(objs)
    if mins is None:
        return (0.0, 0.0, 0.0), None, None
    s = maxs - mins
    axes = [("x", s.x), ("y", s.y), ("z", s.z)]
    axes_sorted = sorted(axes, key=lambda t: t[1])
    return (s.x, s.y, s.z), axes_sorted[0][0], axes_sorted[2][0]


def _detect_upright_euler_deg(objs):
    """Detect the Euler-XYZ rotation (in DEGREES, 90° increments) that moves the vehicle so
    the SHORTEST world-axis dim becomes +Z (height) and the LONGEST becomes +Y (length).

    Deterministic: scans the 24 signed-axis-permutation rotations whose rotation matrix has
    determinant +1 (proper rotations in SO(3), no mirrors), applies each candidate to the
    bbox corners, and picks the one whose RESULTING shape has
        new_dim(z) = min(initial_dims),
        new_dim(y) = max(initial_dims).

    Returns [rx, ry, rz] degrees.
    """
    (dx, dy, dz), short_axis, long_axis = _bbox_xyz(objs)
    initial = sorted([dx, dy, dz])
    target_h, target_l = initial[0], initial[2]  # shortest, longest

    # Enumerate the 24 proper-rotation signed-axis permutations.
    # Each row-permutation (ax, ay, az) with signs is a column-rotation of the identity.
    # We only keep those with determinant +1.
    import itertools
    perms = list(itertools.permutations([0, 1, 2]))
    best = None
    best_cost = float("inf")
    for perm in perms:
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    # Build a 3x3 rotation matrix M where M @ (1,0,0) picks column perm[0] with sign sx, etc.
                    M = mathutils.Matrix(((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
                    M[0][perm[0]] = sx
                    M[1][perm[1]] = sy
                    M[2][perm[2]] = sz
                    if abs(M.determinant() - 1.0) > 1e-6:
                        continue
                    # Apply to bbox dims (axis-aligned → dims just permute).
                    new = [abs(M[0][0]*dx + M[0][1]*dy + M[0][2]*dz),
                           abs(M[1][0]*dx + M[1][1]*dy + M[1][2]*dz),
                           abs(M[2][0]*dx + M[2][1]*dy + M[2][2]*dz)]
                    # Cost: Z should equal target_h; Y should equal target_l.
                    cost = abs(new[2] - target_h) + abs(new[1] - target_l)
                    if cost < best_cost:
                        best_cost = cost
                        best = M
    assert best is not None, "no proper rotation found"
    eul = best.to_euler('XYZ')
    return [round(math.degrees(eul.x) / 90.0) * 90.0,
            round(math.degrees(eul.y) / 90.0) * 90.0,
            round(math.degrees(eul.z) / 90.0) * 90.0]


def _apply_euler_deg(objs, euler_deg):
    """Bake Euler-XYZ rotation (degrees) into vertex positions. Resets matrix_world to identity."""
    rx, ry, rz = (math.radians(a) for a in euler_deg)
    rot_mat = (mathutils.Matrix.Rotation(rz, 4, 'Z') @
               mathutils.Matrix.Rotation(ry, 4, 'Y') @
               mathutils.Matrix.Rotation(rx, 4, 'X'))
    _bake_rotation(objs, rot_mat)


def apply_source_rotation(objs, name=None, rotations_path=None):
    """Apply the per-vehicle rotation from art-source/upright_rotations.json (extracted
    from art-source/orient_all.blend — the hand-corrected source of truth).

    The vehicles in orient_all.blend are already upright after the import pipeline
    (flatten_hierarchy + apply_all_transforms + delete_backdrops), so for the current
    roster the stored rotation is identity (0,0,0) for every vehicle. If the user later
    hand-rotates `<Name>_root` in orient_all.blend and re-runs
    `scripts/export_orient_rotations.py`, the new Euler lands here and takes effect on
    the next render.

    No auto-detection, no caching back to any file. If a vehicle name is missing from
    the rotations file (or the file itself is missing), the step applies identity and
    logs a warning — nothing surprising happens.
    """
    _hard_bake_matrix_world(objs)

    (dx, dy, dz), short_axis, long_axis = _bbox_xyz(objs)
    print(f"[orient] pre-bbox (x,y,z)=({dx:.3f},{dy:.3f},{dz:.3f})  short={short_axis}  long={long_axis}")

    euler = [0.0, 0.0, 0.0]
    source = "identity"
    if name and rotations_path and os.path.exists(rotations_path):
        try:
            rots = json.load(open(rotations_path))
            entry = rots.get(name)
            if entry is not None:
                euler = [float(e) for e in entry]
                source = f"orient_all.blend ({rotations_path})"
            else:
                print(f"[orient] WARN: no entry for '{name}' in {rotations_path} — applying identity")
        except Exception as e:
            print(f"[orient] WARN: failed to read {rotations_path}: {e} — applying identity")
    print(f"[orient] applying euler_deg={euler}  source={source}")
    _apply_euler_deg(objs, euler)

    # Drop lowest Z to 0 so the vehicle sits on the ground.
    mins, maxs = imported_bbox(objs)
    if mins is not None:
        drop = mathutils.Matrix.Translation(Vector((0, 0, -mins.z)))
        _bake_rotation(objs, drop)

    (dx2, dy2, dz2), short2, long2 = _bbox_xyz(objs)
    print(f"[orient] post-bbox (x,y,z)=({dx2:.3f},{dy2:.3f},{dz2:.3f})  short={short2}  long={long2}")


def auto_orient_up(objs, name=None, orientation_json_path=None):
    """Orient so H is the shortest world-axis dim (height = +Z), L is the longest (length = +Y),
    with tracks on the bottom and mesh dropped to Z=0.

    Caching:
      - If `name` + `orientation_json_path` are provided and the file has an
        `upright_euler_deg: [rx, ry, rz]` entry for `name`, apply that exact rotation.
      - Otherwise, auto-detect via `_detect_upright_euler_deg` (deterministic 24-way
        signed-permutation search) and write the result back to orientation.json.

    Always records pre_bbox_m and post_bbox_m (both as [L, W, H], sorted descending) into
    orientation.json so a future audit can confirm Z is now the shortest dim.
    """
    _hard_bake_matrix_world(objs)

    pre_L, pre_W, pre_H = _bbox_dims(objs)
    (pre_dx, pre_dy, pre_dz), pre_short, pre_long = _bbox_xyz(objs)
    print(f"[orient] pre-bbox (x,y,z)=({pre_dx:.3f},{pre_dy:.3f},{pre_dz:.3f})  "
          f"L×W×H=({pre_L:.3f},{pre_W:.3f},{pre_H:.3f})  short={pre_short}  long={pre_long}")

    # Load cache if available.
    cache = {}
    if name and orientation_json_path and os.path.exists(orientation_json_path):
        try:
            cache = json.load(open(orientation_json_path))
        except Exception as e:
            print(f"[orient] WARN failed to read {orientation_json_path}: {e}")
            cache = {}
    entry = cache.get(name, {}) if name else {}

    cached_euler = entry.get("upright_euler_deg")
    if cached_euler is not None:
        print(f"[orient] cached upright_euler_deg={cached_euler}")
        euler = cached_euler
        source = "cache"
    else:
        euler = _detect_upright_euler_deg(objs)
        source = "detected"
        print(f"[orient] detected upright_euler_deg={euler}")

    _apply_euler_deg(objs, euler)

    # Tracks-at-bottom check: compare bottom-20% vs top-20% vertex density; flip 180° around +Y if
    # tracks ended up at the top.
    mins, maxs = imported_bbox(objs)
    if mins is not None:
        z_span = max(maxs.z - mins.z, 1e-6)
        bottom_cutoff = mins.z + 0.20 * z_span
        top_cutoff = maxs.z - 0.20 * z_span
        below = above = 0
        for o in objs:
            if o.type != "MESH" or o.name not in bpy.data.objects:
                continue
            for v in o.data.vertices:
                z = (o.matrix_world @ v.co).z
                if z <= bottom_cutoff:
                    below += 1
                elif z >= top_cutoff:
                    above += 1
        if above > below:
            print("[orient] mass on top → flipping 180° around +Y")
            flip = mathutils.Matrix.Rotation(math.pi, 4, 'Y')
            _bake_rotation(objs, flip)
            # Compose flip ∘ detected so the stored euler reproduces the FULL rotation on
            # a cached re-run. Naively "add 180 to Y" is wrong — Rz(rz) @ Ry(ry+180) @ Rx(rx)
            # is not the same as Ry(180) @ (Rz(rz) @ Ry(ry) @ Rx(rx)).
            rx, ry, rz = (math.radians(a) for a in euler)
            detected_mat = (mathutils.Matrix.Rotation(rz, 4, 'Z') @
                            mathutils.Matrix.Rotation(ry, 4, 'Y') @
                            mathutils.Matrix.Rotation(rx, 4, 'X'))
            combined = flip @ detected_mat
            eul_rad = combined.to_euler('XYZ')
            # Snap to 90° increments so the stored value is clean.
            euler = [round(math.degrees(eul_rad.x) / 90.0) * 90.0,
                     round(math.degrees(eul_rad.y) / 90.0) * 90.0,
                     round(math.degrees(eul_rad.z) / 90.0) * 90.0]

    # Drop lowest Z to 0.
    mins, maxs = imported_bbox(objs)
    if mins is not None:
        drop = mathutils.Matrix.Translation(Vector((0, 0, -mins.z)))
        _bake_rotation(objs, drop)

    post_L, post_W, post_H = _bbox_dims(objs)
    (post_dx, post_dy, post_dz), post_short, post_long = _bbox_xyz(objs)
    is_upright = (post_short == "z")
    print(f"[orient] post-bbox (x,y,z)=({post_dx:.3f},{post_dy:.3f},{post_dz:.3f})  "
          f"L×W×H=({post_L:.3f},{post_W:.3f},{post_H:.3f})  short={post_short}  upright={is_upright}")

    # Persist to orientation.json for next time. Flock the file during read-modify-write so
    # parallel Blender processes don't clobber each other.
    if name and orientation_json_path:
        try:
            import fcntl
            os.makedirs(os.path.dirname(orientation_json_path), exist_ok=True)
            entry.update({
                "upright_euler_deg": [float(e) for e in euler],
                "upright_source": source,
                "upright_detected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "pre_bbox_LWH_m": [round(pre_L, 3), round(pre_W, 3), round(pre_H, 3)],
                "post_bbox_LWH_m": [round(post_L, 3), round(post_W, 3), round(post_H, 3)],
                "pre_bbox_XYZ_m": [round(pre_dx, 3), round(pre_dy, 3), round(pre_dz, 3)],
                "post_bbox_XYZ_m": [round(post_dx, 3), round(post_dy, 3), round(post_dz, 3)],
                "upright_z_is_shortest": is_upright,
            })
            # Open the file for read+write, create if missing. Lock it exclusively while we
            # re-read the on-disk state (which may include concurrent sibling writes), merge
            # our entry, and write back atomically.
            if not os.path.exists(orientation_json_path):
                with open(orientation_json_path, "w") as f0:
                    f0.write("{}")
            with open(orientation_json_path, "r+") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    f.seek(0)
                    txt = f.read()
                    on_disk = json.loads(txt) if txt.strip() else {}
                    # Merge: keep whatever other processes wrote; set our name's entry.
                    on_disk[name] = entry
                    f.seek(0)
                    f.truncate()
                    json.dump(on_disk, f, indent=2, sort_keys=True)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            print(f"[orient] wrote {name} → {orientation_json_path}")
        except Exception as e:
            print(f"[orient] WARN failed to write {orientation_json_path}: {e}")


def measure_hull_length(objs):
    """Return (hull_length_m, hull_center_on_long_axis, overall_length_m) in meters.
    Chooses the longer of X/Y as the vehicle's long axis (whichever is longer). Projects all
    vertices onto that axis, bins them, treats bins with vertex count < 15% of peak as
    'barrel/thin extension' and excludes them from the hull length.
    """
    all_x, all_y = [], []
    for o in objs:
        if o.type != "MESH":
            continue
        mesh = o.data
        mw = o.matrix_world
        for v in mesh.vertices:
            w = mw @ v.co
            all_x.append(w.x)
            all_y.append(w.y)
    if not all_x:
        return 0.0, 0.0, 0.0
    span_x = max(all_x) - min(all_x)
    span_y = max(all_y) - min(all_y)
    if span_x <= 0 and span_y <= 0:
        return 0.0, 0.0, 0.0
    use_y = span_y > span_x
    vals = all_y if use_y else all_x
    vmin, vmax = min(vals), max(vals)
    overall = vmax - vmin
    nbins = 48
    bw = overall / nbins
    counts = [0] * nbins
    for v in vals:
        idx = min(int((v - vmin) / bw), nbins - 1)
        counts[idx] += 1
    peak = max(counts) or 1
    threshold = peak * 0.15
    hull_bins = [i for i, c in enumerate(counts) if c > threshold]
    if not hull_bins:
        return overall, (vmin + vmax) * 0.5, overall
    h_start = vmin + hull_bins[0] * bw
    h_end = vmin + (hull_bins[-1] + 1) * bw
    return h_end - h_start, (h_start + h_end) * 0.5, overall


def scale_and_center(objs, target_hull_length_m):
    """Scale so the measured HULL length (barrel-excluded) == target. Center the hull on origin.
    Writes vertex coordinates directly instead of using bpy.ops.transform_apply because the
    operator is unreliable in headless mode with GLB-imported hierarchies / linked mesh data.
    Returns (scale_factor, hull_len_m_after, overall_len_m_after)."""
    hull_len, hull_center, overall = measure_hull_length(objs)
    if hull_len <= 0:
        print("[scale] measure_hull_length returned 0 — skipping scale")
        return 0.0, 0.0, 0.0
    scale = target_hull_length_m / hull_len
    print(f"[scale] hull_pre={hull_len:.3f}  overall_pre={overall:.3f}  target_hull={target_hull_length_m}  factor={scale:.5f}")

    # Collect the pre-scale world-space hull center so we can translate the whole model to origin
    # after scaling. This is in CURRENT (pre-scale) world coords; after scaling by `scale`, the
    # new hull center is `hull_center * scale` on the long axis.
    _, _pre_center_long, _ = measure_hull_length(objs)
    mins, maxs = imported_bbox(objs)
    y_center_pre = (mins.y + maxs.y) * 0.5
    z_floor_pre = mins.z

    # Bake vertex positions. For each mesh:
    #   new_vert = (matrix_world * old_vert) * scale  (bake world coords, then multiply by scale)
    # Then reset the object's transform to identity so matrix_world == identity afterward.
    for o in list(objs):
        if o.type != "MESH" or o.name not in bpy.data.objects:
            continue
        mw = o.matrix_world.copy()
        mesh = o.data
        for v in mesh.vertices:
            w = mw @ v.co
            v.co = w * scale
        o.matrix_world = mathutils.Matrix.Identity(4)
        mesh.update()

    bpy.context.view_layer.update()

    # Re-measure in the now-baked coordinates.
    hull_len_after, hull_center_after, overall_after = measure_hull_length(objs)
    mins, maxs = imported_bbox(objs)
    y_center = (mins.y + maxs.y) * 0.5
    z_floor = mins.z

    # Center along the long axis AND the short horizontal axis; drop lowest Z to 0.
    # Determine which world axis is the long axis based on which span is larger.
    span_x = maxs.x - mins.x
    span_y = maxs.y - mins.y
    long_is_y = span_y > span_x
    for o in objs:
        if o.type != "MESH" or o.name not in bpy.data.objects:
            continue
        mesh = o.data
        for v in mesh.vertices:
            if long_is_y:
                v.co.y -= hull_center_after
                v.co.x -= (mins.x + maxs.x) * 0.5
            else:
                v.co.x -= hull_center_after
                v.co.y -= y_center
            v.co.z -= z_floor
        mesh.update()
    bpy.context.view_layer.update()
    return scale, hull_len_after, overall_after


def wrap_in_turntable(objs):
    """Parent EVERY imported object to a new empty via the operator (so matrix_parent_inverse
    is set correctly and the children actually follow the empty's rotation)."""
    empty = bpy.data.objects.new("Turntable", None)
    bpy.context.collection.objects.link(empty)
    bpy.context.view_layer.update()

    bpy.ops.object.select_all(action="DESELECT")
    had_selection = False
    for o in objs:
        if o.name not in bpy.data.objects:
            continue
        # Only re-parent current top-level objects — children follow their parent naturally.
        if o.parent is None and o is not empty:
            o.select_set(True)
            had_selection = True
    if not had_selection:
        return empty
    empty.select_set(True)
    bpy.context.view_layer.objects.active = empty
    bpy.ops.object.parent_set(type="OBJECT", keep_transform=True)
    return empty


def report_textures(objs):
    """Enumerate materials + their image textures. Flag any materials with no image = likely dark."""
    mats_seen = set()
    tex_count = 0
    mat_without_tex = 0
    for o in objs:
        if o.type != "MESH":
            continue
        for slot in o.material_slots:
            mat = slot.material
            if mat is None or mat.name in mats_seen:
                continue
            mats_seen.add(mat.name)
            if mat.use_nodes:
                had_tex = False
                for n in mat.node_tree.nodes:
                    if n.type == "TEX_IMAGE" and n.image is not None:
                        tex_count += 1
                        had_tex = True
                if not had_tex:
                    mat_without_tex += 1
            else:
                mat_without_tex += 1
    print(f"[textures] mats={len(mats_seen)} image_textures={tex_count} mats_without_image={mat_without_tex}")


def main():
    args = parse_cli()
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    reset_scene()
    scene = bpy.context.scene

    setup_render(scene, resolution=args.resolution, exposure=args.exposure)
    add_lights()
    pitch_deg = 0.0 if args.view == "side" else args.camera_pitch_deg
    yaw_deg   = 90.0 if args.view == "side" else args.camera_yaw_deg
    add_camera(scene, ortho_scale=args.ortho_scale, pitch_deg=pitch_deg, yaw_deg=yaw_deg)

    imported = import_glb(args.input)
    print(f"[import] {len(imported)} objects from {os.path.basename(args.input)}")
    report_textures(imported)

    flatten_hierarchy(imported)
    apply_all_transforms(imported)
    removed = delete_backdrops(imported)
    if removed:
        print(f"[cull] removed non-vehicle meshes: {removed}")

    rotations_path = args.upright_rotations
    if rotations_path is None:
        rotations_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(args.input))),
            "upright_rotations.json",
        )
    apply_source_rotation(imported, name=args.name, rotations_path=rotations_path)
    scale_f, hull_len, overall_len = scale_and_center(imported, args.length)

    mins, maxs = imported_bbox(imported)
    if mins is not None:
        s = maxs - mins
        print(f"[normalized] bbox=({s.x:.3f}, {s.y:.3f}, {s.z:.3f})m  hull={hull_len:.3f}m  overall={overall_len:.3f}m  center=({(mins.x + maxs.x)/2:.3f}, {(mins.y + maxs.y)/2:.3f}, 0)  scale_factor={scale_f:.5f}")

    turntable = wrap_in_turntable(imported)

    try:
        for i in range(args.steps):
            yaw = i * (360.0 / args.steps)
            turntable.rotation_euler = (0.0, 0.0, math.radians(yaw))
            bpy.context.view_layer.update()
            scene.render.filepath = os.path.join(out_dir, f"{args.prefix}{i:02d}.png")
            print(f"[render] {scene.render.filepath}  yaw={yaw:.1f}deg")
            bpy.ops.render.render(write_still=True)
    finally:
        pass


if __name__ == "__main__":
    main()
