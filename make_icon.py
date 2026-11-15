"""Generate the app icon (run once; Pillow required)."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)


def make(size: int = 1024) -> Image.Image:
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pad = size * 0.045
    radius = size * 0.22
    # soft outer glow
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.rounded_rectangle(
        (pad * 0.5, pad * 0.5, size - pad * 0.5, size - pad * 0.5),
        radius=radius,
        fill=(14, 165, 233, 90),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(size * 0.035))
    im.alpha_composite(glow)
    # main tile
    d.rounded_rectangle(
        (pad, pad, size - pad, size - pad),
        radius=radius,
        fill=(11, 18, 32, 255),
        outline=(56, 189, 248, 255),
        width=max(2, int(size * 0.014)),
    )
    # inner ring / arc
    inset = size * 0.17
    d.arc(
        (inset, inset, size - inset, size - inset),
        start=205,
        end=520,
        fill=(56, 189, 248, 130),
        width=max(2, int(size * 0.018)),
    )
    # glyph
    font_paths = [
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
    ]
    font = None
    for path in font_paths:
        try:
            font = ImageFont.truetype(path, int(size * 0.43))
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    text = "解"
    box = d.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    d.text(
        ((size - tw) / 2 - box[0], (size - th) / 2 - box[1] - size * 0.015),
        text,
        font=font,
        fill=(233, 240, 250, 255),
    )
    # accent dot
    r = size * 0.035
    cx, cy = size * 0.73, size * 0.73
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(52, 211, 153, 255))
    return im


def main():
    im = make(1024)
    im.save(ASSETS / "icon.png")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    im.save(ASSETS / "icon.ico", sizes=sizes)
    print("wrote", ASSETS / "icon.ico")


if __name__ == "__main__":
    main()
