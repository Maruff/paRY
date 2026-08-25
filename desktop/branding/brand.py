"""The eTamil mark, drawn rather than pasted, and the palette taken from it.

Everything the IDE is branded with comes from here: the Windows icon, the
editor's own icons, the activity-bar mark, and the colours the theme is built
out of. Drawn in code so there is one definition of the logo and every size is
generated from it — a folder of hand-exported PNGs drifts the moment the mark
is adjusted.

The mark: three rings and a hooked stroke. The stroke rises out of the upper
ring, arcs over to the right and comes down as a bar; the bar and the dot at its
shoulder are the blue, everything else is white on the navy.

    python desktop/branding/brand.py
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent

# Read off the logo. Navy is the field, the blue is the bar and the dot, and
# the lighter blue is the wordmark's "eTamil" — which becomes the accent the
# theme uses for anything interactive.
PALETTE = {
    "navy": "#0A2240",
    "navy_deep": "#071A31",
    "navy_soft": "#123055",
    "blue": "#3B82F6",
    "blue_bright": "#1E9BE9",
    "white": "#FFFFFF",
    "mist": "#C9D6E5",
    "slate": "#7C90AB",
    "line": "#1D3A5F",
    "green": "#4ADE80",
    "amber": "#FBBF24",
    "red": "#F87171",
}

# Icon sizes Windows and the editor ask for.
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 70, 128, 150, 256)


def draw_mark(size: int, background: str | None = None) -> Image.Image:
    """The logo at one size. `background` None gives a transparent mark."""
    # Drawn at 8x and reduced, because circles this thin alias badly otherwise.
    scale = 8
    edge = size * scale
    image = Image.new("RGBA", (edge, edge), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    if background:
        radius = int(edge * 0.22)
        draw.rounded_rectangle((0, 0, edge - 1, edge - 1), radius=radius, fill=background)

    unit = edge / 100.0
    stroke = int(7.5 * unit)
    white = PALETTE["white"]
    blue = PALETTE["blue"]

    def at(x: float, y: float) -> tuple[int, int]:
        return int(x * unit), int(y * unit)

    def ring(cx: float, cy: float, rx: float, ry: float) -> None:
        """A ring, taller than it is wide, and open enough to read as one."""
        draw.ellipse((*at(cx - rx, cy - ry), *at(cx + rx, cy + ry)), outline=white, width=stroke)

    # Three rings: one above left, two along the bottom.
    ring(30, 43, 12.5, 15)
    ring(25, 76, 12.5, 15)
    ring(54, 76, 12.5, 15)

    # The hook. A half circle over the top, landing on the bar at the right —
    # drawn before the bar so the bar's cap finishes the stroke rather than
    # sitting under it.
    draw.arc((*at(29, 12), *at(77, 50)), start=180, end=360, fill=white, width=stroke)
    draw.line([at(29.5, 31), at(29.5, 30)], fill=white, width=stroke)

    # The bar down the right and the dot at its shoulder, both blue. Rounded
    # ends, because every other stroke in the mark is round.
    bar_x, half = 74.0, stroke / (2 * unit)
    draw.rounded_rectangle(
        (*at(bar_x - half, 30), *at(bar_x + half, 86)),
        radius=stroke // 2,
        fill=blue,
    )
    dot = 5.0
    draw.ellipse((*at(bar_x - half - dot, 27 - dot), *at(bar_x - half + dot, 27 + dot)), fill=blue)

    return image.resize((size, size), Image.LANCZOS)


def write_icons(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # The Windows icon: every size in one file, on the navy field.
    frames = [draw_mark(size, PALETTE["navy"]) for size in ICON_SIZES]
    ico = out / "etamil.ico"
    frames[-1].save(ico, format="ICO", sizes=[(s, s) for s in ICON_SIZES])
    written.append(ico)

    for size in (16, 32, 48, 64, 128, 256, 512):
        path = out / f"etamil-{size}.png"
        draw_mark(size, PALETTE["navy"]).save(path)
        written.append(path)

    # Transparent, for anywhere the editor paints its own background.
    for size in (24, 64, 256):
        path = out / f"etamil-mark-{size}.png"
        draw_mark(size).save(path)
        written.append(path)

    (out / "palette.json").write_text(
        json.dumps(PALETTE, indent=2) + "\n", encoding="utf-8"
    )
    written.append(out / "palette.json")
    return written


def main() -> int:
    written = write_icons(HERE / "icons")
    print(f"wrote {len(written)} files to {HERE / 'icons'}")
    for path in written:
        print(f"  {path.name:<24} {path.stat().st_size:>8,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
