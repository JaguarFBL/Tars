"""Génère les déclinaisons PNG de l'icône TARS depuis la géométrie du maître SVG.

Source unique : barres et LED définies ci-dessous, identiques à tars.svg.
Exécution : python static/icons/generate_icons.py
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BG = (20, 23, 26)
CREAM = (231, 232, 230)
ORANGE = (227, 155, 45)

CANVAS = 512
BARS = (
    (106, 208, 54, 168),
    (188, 116, 54, 260),
    (270, 184, 54, 192),
    (352, 160, 54, 216),
)
BAR_RADIUS = 27
LED = (256, 420, 16)

SS = 8
ICONS_DIR = Path(__file__).resolve().parent
RES_DIR = ICONS_DIR.parents[1] / "android" / "app" / "src" / "main" / "res"

WEB_ICONS = (
    ("tars-192x192.png", 192),
    ("tars-512x512.png", 512),
    ("tars-maskable-512x512.png", 512),
    ("apple-touch-icon-180x180.png", 180),
    ("favicon-32x32.png", 32),
)
ANDROID_ICONS = (
    ("mipmap-mdpi", 48),
    ("mipmap-hdpi", 72),
    ("mipmap-xhdpi", 96),
    ("mipmap-xxhdpi", 144),
    ("mipmap-xxxhdpi", 192),
)


def render(size: int, shape: str = "square") -> Image.Image:
    """Rend l'icône à `size` px, suréchantillonnée puis réduite (LANCZOS)."""
    scale = size * SS / CANVAS
    extent = size * SS
    image = Image.new("RGBA", (extent, extent), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    if shape == "circle":
        draw.ellipse((0, 0, extent - 1, extent - 1), fill=BG + (255,))
    else:
        draw.rectangle((0, 0, extent, extent), fill=BG + (255,))

    for x, y, width, height in BARS:
        draw.rounded_rectangle(
            (
                x * scale,
                y * scale,
                (x + width) * scale,
                (y + height) * scale,
            ),
            radius=BAR_RADIUS * scale,
            fill=CREAM + (255,),
        )

    cx, cy, radius = LED
    draw.ellipse(
        (
            (cx - radius) * scale,
            (cy - radius) * scale,
            (cx + radius) * scale,
            (cy + radius) * scale,
        ),
        fill=ORANGE + (255,),
    )

    return image.resize((size, size), Image.LANCZOS)


def save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)


def load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = (
        Path(r"C:\Windows\Fonts") / name,
        Path("/usr/share/fonts/truetype/dejavu") / name,
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def build_preview() -> Image.Image:
    """Planche 512x512 : maître, zoom x4 à 48 px et tailles réelles."""
    board = Image.new("RGB", (512, 512), CREAM)
    draw = ImageDraw.Draw(board)

    bold = load_font("segoeuib.ttf", 27)
    semibold = load_font("seguisb.ttf", 12)
    regular = load_font("segoeui.ttf", 11)

    draw.rectangle((0, 0, 512, 64), fill=BG)
    draw.text((24, 15), "TARS", font=bold, fill=CREAM)
    right = "ICÔNE 512 / UI"
    draw.text((488 - draw.textlength(right, font=semibold), 26), right, font=semibold, fill=ORANGE)

    master = render(224)
    board.paste(master.convert("RGB"), (24, 88), master)

    zoom_source = render(48)
    zoom = zoom_source.resize((192, 192), Image.NEAREST)
    board.paste(zoom.convert("RGB"), (296, 96), zoom)

    small_48 = render(48)
    small_32 = render(32)
    touch_180 = render(180)
    board.paste(small_48.convert("RGB"), (24, 360), small_48)
    board.paste(small_32.convert("RGB"), (96, 376), small_32)
    board.paste(touch_180.convert("RGB"), (296, 320), touch_180)

    gray = (86, 92, 99)
    draw.text((24, 320), "MAÎTRE 512 px", font=regular, fill=gray)
    draw.text((296, 78), "ZOOM ×4 — 48 px", font=regular, fill=gray)
    draw.text((24, 416), "48 px", font=regular, fill=gray)
    draw.text((96, 416), "32 px", font=regular, fill=gray)
    draw.text((296, 302), "180 px", font=regular, fill=gray)

    return board


def verify(path: Path, size: int) -> str:
    assert path.stat().st_size > 0, f"fichier vide : {path}"
    with Image.open(path) as image:
        assert image.size == (size, size), f"taille inattendue : {path} {image.size}"
        assert image.mode in ("RGB", "RGBA"), f"mode inattendu : {path} {image.mode}"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{path.relative_to(ICONS_DIR.parents[1])} | {size}x{size} | {path.stat().st_size} o | {digest[:16]}"


def main() -> None:
    report: list[str] = []

    for name, size in WEB_ICONS:
        path = ICONS_DIR / name
        save_png(render(size), path)
        report.append(verify(path, size))

    for folder, size in ANDROID_ICONS:
        square_path = RES_DIR / folder / "ic_launcher.png"
        round_path = RES_DIR / folder / "ic_launcher_round.png"
        save_png(render(size), square_path)
        save_png(render(size, shape="circle"), round_path)
        report.append(verify(square_path, size))
        report.append(verify(round_path, size))

    preview_path = ICONS_DIR / "preview.png"
    save_png(build_preview(), preview_path)
    report.append(verify(preview_path, 512))

    print("\n".join(report))


if __name__ == "__main__":
    main()
