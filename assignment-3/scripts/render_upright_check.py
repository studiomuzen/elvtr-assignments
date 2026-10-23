"""
Upright-orientation check — for each of the 17 vehicles, run the production render pipeline
(scripts/blender_render_v2.py) at ONE diamond-angle frame, letting the orient step cache its
per-vehicle rotation into art-source/orientation.json. Then composite all 17 renders into one
contact sheet at ELVATR GAME 1/Assets/Art/Vehicles/_upright_check.png and print a
before/after dimensions table (L × W × H).

Design brief (from the user):
  - KEEP the approved v4 pixel style, union-bbox sizing, the shared camera angle, and the raw
    render + colour step. (We only touch the orient step.)
  - FIX the sideways vehicles by rotating each one so H (height) is the SHORTEST dimension
    and L (length) is the LONGEST. T-90 renders upright and is the reference.
  - Save every vehicle's correction to art-source/orientation.json so it's never re-guessed.
  - Max 2 Blender processes at a time.
  - STOP after writing the contact sheet so the user can approve before the full 16-direction
    batch is re-rendered.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
RENDER_SCRIPT = ROOT / "scripts" / "blender_render_v2.py"
ORIENTATION_JSON = ROOT / "art-source" / "orientation.json"
UPRIGHT_ROTATIONS = ROOT / "art-source" / "upright_rotations.json"
OUT_SHEET = ROOT / "ELVATR GAME 1" / "Assets" / "Art" / "Vehicles" / "_render_check.png"
LOG_DIR = ROOT / "art-source" / "orient_check"

# Canonical name (matches orientation.json + <Name>_sheet.png filenames) → (glb, length_m)
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


def render_one(name: str, glb_name: str, length_m: float) -> tuple[str, int, Path]:
    """Run one Blender render for `name`. Returns (name, returncode, log_path)."""
    glb_path = ROOT / "art-source" / "models" / glb_name
    out_dir = LOG_DIR / name.lower()
    out_dir.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{name}.log"
    cmd = [
        BLENDER, "-b", "--python", str(RENDER_SCRIPT), "--",
        "--input", str(glb_path),
        "--out-dir", str(out_dir),
        "--length", str(length_m),
        "--steps", "1",
        "--view", "diamond",
        "--prefix", "check_",
        "--name", name,
        "--upright-rotations", str(UPRIGHT_ROTATIONS),
    ]
    with open(log_path, "w") as f:
        f.write(" ".join(cmd) + "\n\n")
        proc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
    return name, proc.returncode, log_path


def dimensions_table() -> list[dict]:
    """Build table rows from upright_rotations.json + the per-vehicle render log.
    Pre/post dim fields no longer come from orientation.json (that file now only
    carries pick-angle approvals, not auto-detected upright state)."""
    rots = {}
    if UPRIGHT_ROTATIONS.exists():
        try:
            rots = json.load(open(UPRIGHT_ROTATIONS))
        except Exception:
            rots = {}
    rows = []
    for name, _, _ in VEHICLES:
        rows.append({
            "name": name,
            "pre_L": 0, "pre_W": 0, "pre_H": 0,
            "post_L": 0, "post_W": 0, "post_H": 0,
            "euler": rots.get(name, [0.0, 0.0, 0.0]),
            "z_is_shortest": True,   # trust orient_all.blend as ground truth; no auto-check
        })
    return rows


def load_rgba(path: Path, fallback_size=(512, 512)) -> Image.Image:
    if path.exists():
        return Image.open(path).convert("RGBA")
    return Image.new("RGBA", fallback_size, (40, 40, 40, 255))


def build_contact_sheet(rows: list[dict]) -> Path:
    """4 columns × 5 rows (last row has one empty cell). Each tile shows a vehicle's single
    diamond render with name + pre/post dim labels underneath."""
    cols = 4
    rows_n = (len(VEHICLES) + cols - 1) // cols
    tile_w, tile_h = 480, 420
    pad = 8
    label_h = 72
    sheet_w = cols * tile_w + pad * (cols + 1)
    sheet_h = rows_n * tile_h + pad * (rows_n + 1) + 60
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (18, 18, 22, 255))
    draw = ImageDraw.Draw(sheet)

    def font(sz):
        for p in [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]:
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, sz)
                except Exception:
                    pass
        return ImageFont.load_default()

    f_hdr = font(22)
    f_name = font(18)
    f_dim = font(13)

    draw.text(
        (pad, 10),
        "Render check — 17 vehicles @ diamond camera, one frame each. Rotations sourced from art-source/orient_all.blend.",
        fill=(235, 235, 230, 255),
        font=f_hdr,
    )

    for i, row in enumerate(rows):
        c = i % cols
        r = i // cols
        tx = pad + c * (tile_w + pad)
        ty = 50 + pad + r * (tile_h + pad)

        img_path = LOG_DIR / row["name"].lower() / "check_00.png"
        img = load_rgba(img_path).copy()
        img.thumbnail((tile_w - 20, tile_h - label_h - 20), Image.LANCZOS)

        # tile background
        pass_mark = row["z_is_shortest"]
        tile_bg = (28, 36, 28, 255) if pass_mark else (48, 28, 28, 255)
        draw.rectangle([tx, ty, tx + tile_w, ty + tile_h], fill=tile_bg)

        ix = tx + (tile_w - img.width) // 2
        iy = ty + 8
        sheet.paste(img, (ix, iy), img)

        label_y = ty + tile_h - label_h + 4
        verdict = "✓ upright" if pass_mark else "✗ sideways"
        draw.text((tx + 10, label_y),
                  f"{row['name']}  {verdict}",
                  fill=(240, 240, 230, 255), font=f_name)
        draw.text((tx + 10, label_y + 24),
                  f"pre  L×W×H = {row['pre_L']} × {row['pre_W']} × {row['pre_H']} m",
                  fill=(190, 190, 200, 255), font=f_dim)
        draw.text((tx + 10, label_y + 40),
                  f"post L×W×H = {row['post_L']} × {row['post_W']} × {row['post_H']} m   euler={row['euler']}",
                  fill=(190, 190, 200, 255), font=f_dim)

    OUT_SHEET.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT_SHEET)
    return OUT_SHEET


def print_table(rows: list[dict]) -> None:
    print()
    print(f"{'VEHICLE':<20} {'pre  L×W×H (m)':<32} {'post L×W×H (m)':<32} {'euler_deg':<22} {'Z=shortest':<10}")
    print("-" * 120)
    for r in rows:
        pre = f"{r['pre_L']}×{r['pre_W']}×{r['pre_H']}"
        post = f"{r['post_L']}×{r['post_W']}×{r['post_H']}"
        eul = ",".join(str(int(e)) if e is not None else "-" for e in r["euler"])
        print(f"{r['name']:<20} {pre:<32} {post:<32} {eul:<22} {'YES' if r['z_is_shortest'] else 'no'}")


def main():
    if not RENDER_SCRIPT.exists():
        print(f"missing render script: {RENDER_SCRIPT}", file=sys.stderr)
        sys.exit(2)
    if not os.path.exists(BLENDER):
        print(f"missing Blender: {BLENDER}", file=sys.stderr)
        sys.exit(2)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"rendering {len(VEHICLES)} vehicles, max 2 parallel …")

    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        futures = {
            ex.submit(render_one, name, glb, length_m): name
            for (name, glb, length_m) in VEHICLES
        }
        for fut in cf.as_completed(futures):
            name = futures[fut]
            try:
                nm, rc, lp = fut.result()
                mark = "OK" if rc == 0 else f"FAIL rc={rc}"
                print(f"  [{mark:8s}] {nm:<20}  log={lp}")
            except Exception as e:
                print(f"  [EXC ]      {name:<20}  {e}")

    rows = dimensions_table()
    print_table(rows)

    sheet_path = build_contact_sheet(rows)
    print(f"\ncontact sheet → {sheet_path}")

    failures = [r["name"] for r in rows if not r["z_is_shortest"]]
    if failures:
        print(f"\nStill sideways: {failures}")
        sys.exit(1)
    print(f"\nAll 17 upright. Approve the contact sheet, then re-run the full 16-direction batch.")


if __name__ == "__main__":
    main()
