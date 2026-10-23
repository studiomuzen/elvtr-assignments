"""
Build a 6-direction pick sheet per vehicle. The user looks at the sheet and marks which of
the 6 labelled frames is the "true forward" so the pipeline can later apply an offset.

Picks 6 rotations evenly-spaced through the 16-frame set: frames 0, 3, 5, 8, 11, 13
(yaws ~0°, 67.5°, 112.5°, 180°, 247.5°, 292.5°) — ~60°-apart coverage.

Output: ELVATR GAME 1/Assets/Art/Vehicles/<Name>_pick.png (dashboard shows these on the
Art Review tab — they do NOT start with `_` so they're visible).
"""

import os
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIPPED_DIR = os.path.join(ROOT, "ELVATR GAME 1", "Assets", "Art", "Vehicles")
RAW_DIR = os.path.join(ROOT, "art-source", "pixelated_raw")

# Pick 6 frames out of 16, approximately every 60°.
PICK_INDICES = [0, 3, 5, 8, 11, 13]

VEHICLES = [
    "Abrams", "Leopard2", "Challenger2", "Bradley", "PzH2000", "Gepard",
    "MRAPUkraine", "TechnicalUkraine", "EWTruckUkraine",
    "T90", "T72", "Koalitsiya", "BMP3", "Tunguska", "BTR3E",
    "TechnicalRussian", "EWTruckRussian",
]
SCALE = 4
PAD = 16


def load_font(sz):
    for p in ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/System/Library/Fonts/Helvetica.ttc"]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                pass
    return ImageFont.load_default()


def extract_cell(sheet, i):
    w, h = sheet.size
    cell = h
    return sheet.crop((i * cell, 0, (i + 1) * cell, h)), cell


def main():
    hdr = load_font(18)
    lbl = load_font(14)
    for name in VEHICLES:
        src = os.path.join(SHIPPED_DIR, f"{name}_sheet.png")
        if not os.path.exists(src):
            src = os.path.join(RAW_DIR, f"{name}_sheet.png")
        if not os.path.exists(src):
            print(f"[skip] {name}: no sheet")
            continue
        sheet = Image.open(src).convert("RGBA")
        n_total = sheet.width // sheet.height
        cell_src = sheet.height
        cell_disp = cell_src * SCALE
        cols = 3
        rows = 2
        w = cols * cell_disp + (cols + 1) * PAD
        h = rows * cell_disp + (rows + 1) * PAD + 60
        pick = Image.new("RGBA", (w, h), (18, 18, 22, 255))
        draw = ImageDraw.Draw(pick)
        draw.text((PAD, 10),
                  f"{name} — pick the frame that shows the TRUE FORWARD",
                  fill=(240, 240, 220, 255), font=hdr)
        for slot, idx in enumerate(PICK_INDICES[:cols * rows]):
            if idx >= n_total:
                continue
            cell_img, _ = extract_cell(sheet, idx)
            up = cell_img.resize((cell_disp, cell_disp), Image.NEAREST)
            r = slot // cols
            c = slot % cols
            x = PAD + c * (cell_disp + PAD)
            y = 40 + PAD + r * (cell_disp + PAD)
            pick.paste(up, (x, y), up)
            yaw = int(idx * 360 / n_total)
            draw.text((x + 6, y + 6), f"frame {idx} · {yaw}°",
                      fill=(255, 230, 120, 255), font=lbl)
        out = os.path.join(SHIPPED_DIR, f"{name}_pick.png")
        pick.save(out)
        print(f"wrote {out}  ({w}×{h})")


if __name__ == "__main__":
    main()
