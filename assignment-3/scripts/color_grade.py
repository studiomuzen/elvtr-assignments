"""
Color-grade step — final adjustable pass between pixelated_raw and the shipped sheet.

Reads art-source/color_config.json for per-vehicle settings. Rerun this script to recolor
every vehicle without re-rendering Blender or re-pixelating.

Order of operations (per settings merged from defaults + vehicle override):
    brightness → contrast → saturation → hue_shift → tint (over opaque pixels) → sharpness

The sprite's alpha channel is preserved through the whole pipeline. Drop shadow pixels
(alpha > 0, RGB near-black with partial alpha) are left alone because they are below the
alpha-opaque threshold used for the tint overlay.

Usage:
    python scripts/color_grade.py \
        --in art-source/pixelated_raw/Abrams_sheet.png \
        --out "ELVATR GAME 1/Assets/Art/Vehicles/Abrams_sheet.png" \
        --name Abrams \
        --config art-source/color_config.json
"""

import argparse
import json
import os

from PIL import Image, ImageEnhance


def load_settings(config_path: str, name: str) -> dict:
    with open(config_path) as f:
        cfg = json.load(f)
    s = dict(cfg["defaults"])
    s.update(cfg.get("vehicles", {}).get(name, {}))
    return s


def apply_hue_shift(img: Image.Image, degrees: float) -> Image.Image:
    if abs(degrees) < 0.01:
        return img
    r, g, b, a = img.split()
    rgb = Image.merge("RGB", (r, g, b)).convert("HSV")
    h, s, v = rgb.split()
    offset = int(round(degrees / 360.0 * 255)) % 256
    h = h.point(lambda x: (x + offset) % 256)
    rgb = Image.merge("HSV", (h, s, v)).convert("RGB")
    return Image.merge("RGBA", (*rgb.split(), a))


def apply_tint(img: Image.Image, tint, strength: float) -> Image.Image:
    if not tint or strength <= 0:
        return img
    r, g, b, a = img.split()
    rgb = Image.merge("RGB", (r, g, b))
    tint_layer = Image.new("RGB", img.size, tuple(int(c) for c in tint))
    # Only tint pixels that are fully opaque (vehicle, not drop shadow).
    opaque_mask = a.point(lambda v: 255 if v == 255 else 0).convert("L")
    blended = Image.blend(rgb, tint_layer, strength)
    out_rgb = Image.composite(blended, rgb, opaque_mask)
    return Image.merge("RGBA", (*out_rgb.split(), a))


def grade(img: Image.Image, s: dict) -> Image.Image:
    r, g, b, a = img.split()
    rgb = Image.merge("RGB", (r, g, b))

    if s.get("brightness", 1.0) != 1.0:
        rgb = ImageEnhance.Brightness(rgb).enhance(float(s["brightness"]))
    if s.get("contrast", 1.0) != 1.0:
        rgb = ImageEnhance.Contrast(rgb).enhance(float(s["contrast"]))
    if s.get("saturation", 1.0) != 1.0:
        rgb = ImageEnhance.Color(rgb).enhance(float(s["saturation"]))

    graded = Image.merge("RGBA", (*rgb.split(), a))
    graded = apply_hue_shift(graded, float(s.get("hue_shift", 0)))
    graded = apply_tint(graded, s.get("tint"), float(s.get("tint_strength", 0.0)))

    if s.get("sharpness", 1.0) != 1.0:
        r2, g2, b2, a2 = graded.split()
        rgb2 = Image.merge("RGB", (r2, g2, b2))
        rgb2 = ImageEnhance.Sharpness(rgb2).enhance(float(s["sharpness"]))
        graded = Image.merge("RGBA", (*rgb2.split(), a2))

    return graded


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", required=True, help="Vehicle name to look up in color_config.json")
    ap.add_argument("--config", default="art-source/color_config.json")
    args = ap.parse_args()

    settings = load_settings(args.config, args.name)
    src = Image.open(args.input).convert("RGBA")
    out = grade(src, settings)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    out.save(args.out)
    tint = settings.get("tint")
    print(f"wrote {args.out}  (name={args.name}, contrast={settings.get('contrast')}, "
          f"sat={settings.get('saturation')}, hue={settings.get('hue_shift')}, "
          f"tint={tint} @ {settings.get('tint_strength')}, sharp={settings.get('sharpness')})")


if __name__ == "__main__":
    main()
