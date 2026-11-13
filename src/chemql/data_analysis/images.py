"""Terminal rendering helpers for raster images."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from PIL import Image, ImageOps

_SHADES = " .:-=+*#%@"


def _supports_truecolor() -> bool:
    return (
        sys.stdout.isatty()
        and "NO_COLOR" not in os.environ
        and os.environ.get("TERM", "") != "dumb"
    )


def _open_image(source: str | os.PathLike[str] | Image.Image) -> Image.Image:
    if isinstance(source, Image.Image):
        return ImageOps.exif_transpose(source).copy()
    if isinstance(source, (str, os.PathLike)):
        with Image.open(source) as image:
            image.load()
            return ImageOps.exif_transpose(image).copy()
    raise TypeError("Image source must be a path or a Pillow Image.")


def image_to_terminal(
    source: str | os.PathLike[str] | Image.Image,
    width: int = 48,
    colors: bool | None = None,
) -> str:
    """Render an image using true-colour half blocks or monochrome shades."""
    if not isinstance(width, int) or isinstance(width, bool) or width < 1:
        raise ValueError("Image width must be a positive integer.")
    if colors is not None and not isinstance(colors, bool):
        raise TypeError("colors must be True, False, or None.")

    image = _open_image(source).convert("RGBA")
    pixel_height = max(1, round(width * image.height / image.width))
    image = image.resize((width, pixel_height), Image.Resampling.LANCZOS)
    background = Image.new("RGBA", image.size, (255, 255, 255, 255))
    image = Image.alpha_composite(background, image).convert("RGB")
    use_color = _supports_truecolor() if colors is None else colors

    lines = []
    for y in range(0, pixel_height, 2):
        row = []
        for x in range(width):
            top = image.getpixel((x, y))
            bottom = image.getpixel((x, min(y + 1, pixel_height - 1)))
            if use_color:
                row.append(
                    f"\x1b[38;2;{top[0]};{top[1]};{top[2]}m"
                    f"\x1b[48;2;{bottom[0]};{bottom[1]};{bottom[2]}m▀"
                    "\x1b[0m"
                )
            else:
                luminance = (
                    0.2126 * top[0] + 0.7152 * top[1] + 0.0722 * top[2]
                    + 0.2126 * bottom[0] + 0.7152 * bottom[1] + 0.0722 * bottom[2]
                ) / 510
                shade = round(luminance * (len(_SHADES) - 1))
                row.append(_SHADES[shade])
        lines.append("".join(row))
    return "\n".join(lines)


def print_image(
    source: str | os.PathLike[str] | Image.Image,
    width: int = 48,
    colors: bool | None = None,
) -> None:
    """Render an image directly to standard output."""
    print(image_to_terminal(source, width, colors))
