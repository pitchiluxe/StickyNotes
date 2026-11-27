from __future__ import annotations

from pathlib import Path


def _vertical_gradient(size: int, top_rgb: tuple[int, int, int], bottom_rgb: tuple[int, int, int]):
    from PIL import Image

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    for y in range(size):
        t = y / max(1, (size - 1))
        r = int(top_rgb[0] * (1 - t) + bottom_rgb[0] * t)
        g = int(top_rgb[1] * (1 - t) + bottom_rgb[1] * t)
        b = int(top_rgb[2] * (1 - t) + bottom_rgb[2] * t)
        for x in range(size):
            px[x, y] = (r, g, b, 255)
    return img


def _get_font(size: int):
    from PIL import ImageFont

    candidates = [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/SegoeUI.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/ARIAL.TTF",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def make_icon(out_dir: Path) -> tuple[Path, Path]:
    from PIL import Image, ImageDraw

    out_dir.mkdir(parents=True, exist_ok=True)

    base_size = 512
    img = _vertical_gradient(base_size, (255, 214, 102), (255, 195, 60))

    draw = ImageDraw.Draw(img)

    # Rounded sticky note body
    pad = int(base_size * 0.08)
    radius = int(base_size * 0.12)
    body = (pad, pad, base_size - pad, base_size - pad)
    draw.rounded_rectangle(body, radius=radius, outline=(20, 20, 20, 55), width=int(base_size * 0.02))

    # Folded corner (top-right)
    fold = int(base_size * 0.22)
    x2, y1 = body[2], body[1]
    fold_poly = [(x2 - fold, y1), (x2, y1), (x2, y1 + fold)]
    draw.polygon(fold_poly, fill=(255, 242, 204, 255), outline=(20, 20, 20, 45))

    # Subtle fold shadow
    shadow_poly = [(x2 - fold, y1), (x2 - fold, y1 + int(fold * 0.55)), (x2, y1 + fold)]
    draw.polygon(shadow_poly, fill=(0, 0, 0, 18))

    # "S" mark
    font = _get_font(int(base_size * 0.42))
    s = "S"
    bbox = draw.textbbox((0, 0), s, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    cx = base_size // 2
    cy = int(base_size * 0.56)

    # Soft shadow
    draw.text((cx - tw / 2 + 8, cy - th / 2 + 10), s, font=font, fill=(0, 0, 0, 60))
    draw.text((cx - tw / 2, cy - th / 2), s, font=font, fill=(17, 24, 39, 235))

    # Export
    ico_path = out_dir / "StickyNotes.ico"
    png_path = out_dir / "StickyNotes_icon_preview.png"

    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

    img.save(png_path)
    img.save(ico_path, format="ICO", sizes=sizes)

    return ico_path, png_path


def main() -> int:
    try:
        import PIL  # noqa: F401
    except Exception:
        print("Missing dependency: Pillow")
        print("Install it with: python -m pip install pillow")
        return 2

    out_dir = Path(__file__).resolve().parent
    ico_path, png_path = make_icon(out_dir)
    print(f"Wrote: {ico_path}")
    print(f"Wrote: {png_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
