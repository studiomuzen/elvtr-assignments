"""
Pixelation v4 — deterministic pixel-art stage (no color grading).

CRITICAL rule for frame-to-frame scale consistency:
  * Compute ONE union bbox across ALL 16 raw frames of a vehicle.
  * Apply the SAME crop box and the SAME Lanczos scale factor to every frame.
  * Never let a per-frame bbox or per-frame scale change the output size.
Previously each frame was cropped+scaled independently, so a frame whose silhouette happened
to be wider ended up with a BIGGER pixelated hull than the narrow-silhouette frames (the T-90
202°–247° regression). The union-bbox rule fixes that.

For each frame_NN.png in --in-dir:
  1. Crop to the FIXED union bbox computed across every frame in the vehicle.
  2. Lanczos downscale with ONE scale factor (so the union-bbox long side == --target-long).
  3. Binary alpha threshold at 100 → no translucent fringe.
  4. Median-3 filter on RGB (denoise single-pixel speckle).
  5. Posterize to 32 levels per channel (merge speckle into flat patches, keep plenty of colors).
  6. Compose soft drop shadow at 40% opacity under the vehicle.
  7. Center the body in a --cell-size cell with margin for gun-barrel rotation.

Color grading lives in scripts/color_grade.py.
Combined sprite sheet is a 16-frame horizontal strip (cell × N wide, cell tall).
"""

import argparse
import os

from PIL import Image, ImageDraw, ImageFilter


def union_bbox(frames):
    """Return the union of every frame's non-transparent bbox, as (l, t, r, b)."""
    l = t = r = b = None
    for f in frames:
        bb = f.getbbox()
        if bb is None:
            continue
        if l is None:
            l, t, r, b = bb
        else:
            l = min(l, bb[0])
            t = min(t, bb[1])
            r = max(r, bb[2])
            b = max(b, bb[3])
    return (l, t, r, b) if l is not None else None


def pixelate_frame_fixed(src, union_box, target_long, cell_size):
    """Pixelate using a FIXED crop box + FIXED scale (not per-frame)."""
    cropped = src.crop(union_box)
    cw, ch = cropped.size
    scale = target_long / max(cw, ch)
    tw = max(1, int(round(cw * scale)))
    th = max(1, int(round(ch * scale)))
    small = cropped.resize((tw, th), Image.LANCZOS)

    r, g, b, a = small.split()
    alpha_bin = a.point(lambda v: 255 if v > 100 else 0)
    rgb = Image.merge("RGB", (r, g, b))
    rgb_med = rgb.filter(ImageFilter.MedianFilter(size=3))
    rgb_post = Image.eval(rgb_med, lambda v: (v >> 3) << 3)
    crisp = Image.merge("RGBA", (*rgb_post.split(), alpha_bin))

    shadow_cell = Image.new("RGBA", (cell_size, cell_size), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow_cell)
    cx = (cell_size - tw) // 2
    cy = (cell_size - th) // 2
    sh_w = int(tw * 1.0)
    sh_h = max(6, int(th * 0.42))
    sh_x = cx + 3
    sh_y = cy + int(th * 0.62)
    sd.ellipse((sh_x, sh_y, sh_x + sh_w, sh_y + sh_h),
               fill=(0, 0, 0, int(255 * 0.40)))
    shadow_cell = shadow_cell.filter(ImageFilter.GaussianBlur(radius=2.5))

    cell = Image.new("RGBA", (cell_size, cell_size), (0, 0, 0, 0))
    cell = Image.alpha_composite(cell, shadow_cell)
    cell.paste(crisp, (cx, cy), crisp)
    return cell, tw, th


def opaque_width(frame):
    """Return the width of the frame's opaque pixel column (post-pixelation sanity check)."""
    bb = frame.getbbox()
    if bb is None:
        return 0
    return bb[2] - bb[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--target-long", type=int, required=True)
    ap.add_argument("--cell-size", type=int, required=True)
    ap.add_argument("--prefix", default="frame_")
    args = ap.parse_args()

    frames = []
    names = []
    for fn in sorted(os.listdir(args.in_dir)):
        if not fn.startswith(args.prefix) or not fn.endswith(".png"):
            continue
        names.append(fn)
        frames.append(Image.open(os.path.join(args.in_dir, fn)).convert("RGBA"))
    if not frames:
        raise SystemExit(f"no frames in {args.in_dir}")

    ubox = union_bbox(frames)
    if ubox is None:
        raise SystemExit("all frames are empty")
    ubw = ubox[2] - ubox[0]
    ubh = ubox[3] - ubox[1]
    scale_factor = args.target_long / max(ubw, ubh)
    print(f"[pixelate] union bbox={ubox} ({ubw}×{ubh}) → scale factor={scale_factor:.5f}")

    cells = []
    widths = []
    for i, f in enumerate(frames):
        c, tw, th = pixelate_frame_fixed(f, ubox, args.target_long, args.cell_size)
        cells.append(c)
        widths.append(opaque_width(c))

    # Scale-sanity check: 0° vs 180° (frames 0 and 8 of 16) must have equal opaque width.
    if len(widths) >= 9:
        w0 = widths[0]
        w180 = widths[8]
        match = "OK" if w0 == w180 else f"MISMATCH ({w0} vs {w180})"
        print(f"[pixelate] opaque width 0°={w0}px  180°={w180}px  → {match}")
        # Also print 90° and 270° for extra sanity
        if len(widths) >= 13:
            print(f"[pixelate] opaque width 90°={widths[4]}px  270°={widths[12]}px")

    sheet_w = args.cell_size * len(cells)
    sheet = Image.new("RGBA", (sheet_w, args.cell_size), (0, 0, 0, 0))
    for i, cell in enumerate(cells):
        sheet.paste(cell, (i * args.cell_size, 0), cell)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    sheet.save(args.out)
    print(f"wrote {args.out}  ({sheet_w}x{args.cell_size}, {len(cells)} frames @ {args.cell_size}px cell, body {args.target_long}px long)")


if __name__ == "__main__":
    main()
