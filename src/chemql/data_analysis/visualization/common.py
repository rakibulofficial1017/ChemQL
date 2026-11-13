"""Shared building blocks for the terminal (TUI) and Tkinter (GUI) charts.

Everything that is not specific to one chart type lives here:

* validation helpers and number formatting
* the colour palette, themes and ANSI helpers
* "nice" axis ticks (1 / 2 / 2.5 / 5 x 10^n)
* a small character ``Grid`` used by the text renderers
* ``Legend`` for the text renderers
* ``ChartGUI``: a base class that gives every GUI chart tooltips, hover
  highlighting, a clickable legend, light/dark themes and a context menu.

``tkinter`` is imported lazily so the text charts keep working on systems
where it is not installed.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import sys
from dataclasses import dataclass
from typing import Any, Callable, Sequence

try:  # tkinter is optional: text charts work without it
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import filedialog
except Exception:  # pragma: no cover - depends on the platform
    tk = None
    tkfont = None
    filedialog = None


# --------------------------------------------------------------------------
# Palette, themes, glyphs
# --------------------------------------------------------------------------

PALETTE = (
    "#4e79a7",  # blue
    "#f28e2b",  # orange
    "#e15759",  # red
    "#76b7b2",  # teal
    "#59a14f",  # green
    "#edc949",  # yellow
    "#b07aa1",  # purple
    "#ff9da7",  # pink
    "#9c755f",  # brown
    "#bab0ac",  # grey
)

# Glyphs that keep series distinguishable when colour is unavailable.
MARKERS = ("●", "■", "▲", "◆", "▼", "○", "□", "△", "◇", "▽")
FILLS = ("█", "▓", "▒", "░", "▚", "▞", "▤", "▥", "▦", "▧")

THEMES = {
    "light": {
        "bg": "#ffffff",
        "fg": "#222222",
        "muted": "#777777",
        "grid": "#e6e6e6",
        "axis": "#555555",
        "tip_bg": "#222222",
        "tip_fg": "#ffffff",
        "highlight": "#111111",
    },
    "dark": {
        "bg": "#1e1f24",
        "fg": "#e8e8e8",
        "muted": "#9aa0a6",
        "grid": "#33353c",
        "axis": "#8a8f98",
        "tip_bg": "#f4f4f5",
        "tip_fg": "#111111",
        "highlight": "#ffffff",
    },
}

RESET = "\033[0m"
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_ANSI = re.compile(r"\033\[[0-9;]*m")


def hex_rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def rgb_hex(r: float, g: float, b: float) -> str:
    return "#{:02x}{:02x}{:02x}".format(
        *(max(0, min(255, round(v))) for v in (r, g, b))
    )


def mix(a: str, b: str, t: float) -> str:
    """Blend colour ``a`` towards ``b`` by fraction ``t`` (0..1)."""
    ra, rb = hex_rgb(a), hex_rgb(b)
    return rgb_hex(*(x + (y - x) * t for x, y in zip(ra, rb)))


def contrast_text(color: str) -> str:
    r, g, b = hex_rgb(color)
    return "#111111" if 0.299 * r + 0.587 * g + 0.114 * b > 150 else "#ffffff"


def gradient(stops: Sequence[str], t: float) -> str:
    """Colour at fraction ``t`` along a list of hex colour stops."""
    t = max(0.0, min(1.0, t))
    if len(stops) == 1:
        return stops[0]
    position = t * (len(stops) - 1)
    lower = min(int(position), len(stops) - 2)
    return mix(stops[lower], stops[lower + 1], position - lower)


def _ansi256(color: str) -> int:
    r, g, b = hex_rgb(color)
    return 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)


def paint(text: str, color: str | None, enabled: bool = True) -> str:
    if not enabled or color is None or text == "":
        return text
    return f"\033[38;5;{_ansi256(color)}m{text}{RESET}"


def paint_bg(text: str, color: str, enabled: bool = True) -> str:
    if not enabled or text == "":
        return text
    fg = 16 if contrast_text(color) == "#111111" else 231
    return f"\033[48;5;{_ansi256(color)}m\033[38;5;{fg}m{text}{RESET}"


def visible_len(text: str) -> int:
    return len(_ANSI.sub("", text))


def truncate(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] if limit == 1 else text[: limit - 1] + "…"


def resolve_colors(colors: bool | None) -> bool:
    """``None`` means "colour if stdout is a terminal and NO_COLOR is unset"."""
    if colors is None:
        isatty = getattr(sys.stdout, "isatty", lambda: False)
        return bool(isatty()) and "NO_COLOR" not in os.environ
    return colors


def terminal_size() -> os.terminal_size:
    size = shutil.get_terminal_size(fallback=(80, 24))
    return os.terminal_size((max(1, size.columns - 5), size.lines))


def _pillow_modules() -> tuple[Any, Any]:
    try:
        from PIL import Image, ImageColor, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("Pillow is required for chart image features") from exc
    return Image, ImageColor, ImageDraw, ImageFont


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_finite(value: Any) -> bool:
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def check_numbers(values: Any, what: str) -> list:
    if not isinstance(values, list):
        raise TypeError(f"{what} must be a list")
    for value in values:
        if not is_number(value):
            raise TypeError(f"{what} must contain only numbers")
        if not is_finite(value):
            raise ValueError(f"{what} must contain only finite numbers")
    return list(values)


def check_int(name: str, value: Any, minimum: int | None = None, *, none_ok: bool = False) -> None:
    if value is None and none_ok:
        return
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")


def check_bool(name: str, value: Any) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean")


def check_colors_flag(value: Any) -> None:
    if value is not None and not isinstance(value, bool):
        raise TypeError("colors must be a boolean or None")


def check_choice(name: str, value: Any, choices: Sequence[str]) -> None:
    if value not in choices:
        raise ValueError(f"{name} must be one of: {', '.join(map(repr, choices))}")


def check_char(name: str, value: Any) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 1
        or not value.isprintable()
        or value.isspace()
    ):
        raise ValueError(f"{name} must be a single printable, non-space character")


def check_hex(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _HEX.match(value):
        raise ValueError(f"{name} must be a colour like '#4e79a7'")
    return value.lower()


def check_palette(palette: Any) -> tuple[str, ...]:
    if palette is None:
        return PALETTE
    if not isinstance(palette, (list, tuple)) or not palette:
        raise TypeError("palette must be a non-empty list of '#rrggbb' colours")
    return tuple(check_hex("palette colours", c) for c in palette)


def check_labels(labels: Any, count: int, name: str = "Category labels") -> list:
    if labels is not None and not isinstance(labels, list):
        raise TypeError(f"{name} must be a list or None")
    result = [""] * count if labels is None else list(labels)
    if len(result) != count:
        raise ValueError(f"Number of {name.lower()} must match the data")
    if not all(isinstance(label, str) for label in result):
        raise TypeError(f"{name} must be strings")
    return result


def check_range(axis_range: Any, name: str) -> tuple | None:
    if axis_range is None:
        return None
    if not isinstance(axis_range, tuple) or len(axis_range) != 2:
        raise TypeError(f"{name} must be a tuple of two finite numbers")
    for bound in axis_range:
        if not is_number(bound):
            raise TypeError(f"{name} must be a tuple of two finite numbers")
        if not is_finite(bound):
            raise ValueError(f"{name} bounds must be finite")
    if axis_range[0] >= axis_range[1]:
        raise ValueError(f"{name} minimum must be less than maximum")
    return axis_range


def check_covers(axis_range: tuple | None, values: Sequence[float], name: str) -> None:
    if axis_range is not None and values:
        if min(values) < axis_range[0] or max(values) > axis_range[1]:
            raise ValueError(f"{name} must include all data values")


def check_legend(legend: Any, position: Any, title: Any) -> None:
    check_bool("legend", legend)
    check_choice("legend_position", position, ("top", "bottom", "right"))
    if title is not None and not isinstance(title, str):
        raise TypeError("legend_title must be a string or None")


def normalize_series(
    data: Any, series_name: str = "Value", what: str = "Data"
) -> tuple[list[str], list[list], bool]:
    """Accept a flat list or ``{name: list}`` and return (names, columns, multi)."""
    if not isinstance(series_name, str):
        raise TypeError("series_name must be a string")
    if data is None:
        return [series_name], [[]], False
    if isinstance(data, dict):
        if not data:
            return [series_name], [[]], False
        names = list(data)
        if not all(isinstance(name, str) for name in names):
            raise TypeError("Series names must be strings")
        columns = [check_numbers(data[name], f"{what} for series {name!r}") for name in names]
        if len({len(column) for column in columns}) > 1:
            raise ValueError("All series must have the same length")
        return names, columns, len(names) > 1
    if isinstance(data, list):
        return [series_name], [check_numbers(data, what)], False
    raise TypeError(f"{what} must be a list, a dict of lists, or None")


# --------------------------------------------------------------------------
# Numbers and axes
# --------------------------------------------------------------------------

def fmt_tick(value: float) -> str:
    text = f"{value:.4g}"
    return "0" if text in ("-0", "0.0") else text


def fmt_num(value: float) -> str:
    """Friendly number for tooltips: thousands separators, no noise."""
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer() and abs(value) < 1e15):
        return f"{int(value):,}"
    if abs(value) >= 1e6:
        return f"{value:,.2f}"
    return f"{value:.6g}"


def fmt_pct(fraction: float) -> str:
    return f"{fraction * 100:.1f}%"


def data_range(values: Sequence[float], include_zero: bool = False) -> tuple[float, float]:
    values = list(values)
    if include_zero:
        values.append(0)
    if not values:
        return 0.0, 1.0
    low, high = min(values), max(values)
    if low == high:
        pad = max(abs(low) * 0.05, 1.0)
        return low - pad, high + pad
    return low, high


def nice_step(span: float, target: int) -> float:
    raw = span / max(1, target - 1)
    exponent = math.floor(math.log10(raw))
    fraction = raw / 10 ** exponent
    if fraction < 1.5:
        nice = 1
    elif fraction < 3:
        nice = 2
    elif fraction < 7:
        nice = 5
    else:
        nice = 10
    return nice * 10 ** exponent


def nice_ticks(
    low: float, high: float, target: int = 5, expand: bool = True
) -> tuple[float, float, list[float]]:
    """Return (low, high, ticks) with tick values on 1/2/5 multiples.

    With ``expand`` the range grows to the outer ticks (automatic ranges);
    otherwise the range is kept and ticks are chosen inside it.
    """
    if high <= low:
        high = low + 1
    step = nice_step(high - low, target)
    if expand:
        low = math.floor(low / step + 1e-9) * step
        high = math.ceil(high / step - 1e-9) * step
    ticks = []
    k = math.ceil(low / step - 1e-9)
    while k * step <= high + step * 1e-9 and len(ticks) < 200:
        ticks.append(float(f"{k * step:.12g}"))
        k += 1
    return float(f"{low:.12g}"), float(f"{high:.12g}"), ticks


def label_row(width: int, items: Sequence[tuple[int, str]]) -> str:
    """Place ``(centre, text)`` labels on one line, skipping any that collide."""
    cells = [" "] * width
    last_end = -2
    for centre, text in items:
        if not text:
            continue
        text = text[:width]
        start = max(0, min(width - len(text), centre - len(text) // 2))
        if start < last_end + 2:
            continue
        for offset, char in enumerate(text):
            cells[start + offset] = char
        last_end = start + len(text) - 1
    return "".join(cells).rstrip()


def slot_centre(index: int, count: int, width: int) -> int:
    return min(width - 1, int((index + 0.5) * width / max(1, count)))


# --------------------------------------------------------------------------
# Text grid
# --------------------------------------------------------------------------

class Grid:
    """A character canvas whose cells remember an optional hex colour."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.chars = [[" "] * width for _ in range(height)]
        self.colors: list[list[str | None]] = [[None] * width for _ in range(height)]

    def put(self, x: int, y: int, char: str, color: str | None = None) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self.chars[y][x] = char
            self.colors[y][x] = color

    def get(self, x: int, y: int) -> str:
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.chars[y][x]
        return " "

    def text(self, x: int, y: int, text: str, color: str | None = None) -> None:
        for offset, char in enumerate(text):
            self.put(x + offset, y, char, color)

    def hline(self, y: int, x0: int, x1: int, char: str, color: str | None = None) -> None:
        for x in range(min(x0, x1), max(x0, x1) + 1):
            self.put(x, y, char, color)

    def vline(self, x: int, y0: int, y1: int, char: str, color: str | None = None) -> None:
        for y in range(min(y0, y1), max(y0, y1) + 1):
            self.put(x, y, char, color)

    def rows(self, use_color: bool) -> list[str]:
        lines = []
        for chars, colors in zip(self.chars, self.colors):
            parts: list[str] = []
            run = ""
            run_color = None
            for char, color in zip(chars, colors):
                if color != run_color:
                    parts.append(paint(run, run_color, use_color))
                    run, run_color = "", color
                run += char
            parts.append(paint(run, run_color, use_color))
            lines.append("".join(parts))
        return lines


# --------------------------------------------------------------------------
# Legends (text)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class LegendEntry:
    key: Any            # identity used for show/hide in the GUI (None = static)
    label: str
    color: str          # hex colour
    marker: str = "■"   # glyph used by the text renderer
    shape: str = "square"  # GUI swatch: square, circle, ring, line, dash


class Legend:
    GAP = "   "

    def __init__(
        self,
        entries: Sequence[LegendEntry],
        position: str = "bottom",
        title: str | None = None,
        enabled: bool = True,
        custom_lines: Sequence[str] | None = None,
    ) -> None:
        self.entries = list(entries) if enabled else []
        self.custom = list(custom_lines) if (custom_lines and enabled) else None
        self.position = position
        self.title = title

    def __bool__(self) -> bool:
        return bool(self.entries or self.custom)

    def reserve_width(self, total: int) -> int:
        """Columns taken from the plot when the legend sits on the right."""
        if not self or self.position != "right":
            return 0
        if self.custom:
            return max(visible_len(line) for line in self.custom) + len(self.GAP)
        longest = max(len(e.marker) + 1 + len(e.label) for e in self.entries)
        if self.title:
            longest = max(longest, len(self.title))
        return min(longest, max(12, total // 3)) + len(self.GAP)

    def _items(self, colors: bool, limit: int) -> list[tuple[int, str]]:
        items = []
        for entry in self.entries:
            label = truncate(entry.label, limit - len(entry.marker) - 1)
            width = len(entry.marker) + 1 + len(label)
            items.append((width, paint(entry.marker, entry.color, colors) + " " + label))
        return items

    def lines(self, total: int, colors: bool) -> list[str]:
        if self.custom:
            if self.position == "right":
                return list(self.custom)
            return [" " * max(0, (total - visible_len(line)) // 2) + line for line in self.custom]
        if not self.entries:
            return []
        if self.position == "right":
            limit = self.reserve_width(total) - len(self.GAP)
            column = [text for _, text in self._items(colors, limit)]
            if self.title:
                column.insert(0, truncate(self.title, limit))
            return column
        rows: list[list[tuple[int, str]]] = [[]]
        used = 0
        for width, text in self._items(colors, max(4, total)):
            extra = width + (len(self.GAP) if rows[-1] else 0)
            if rows[-1] and used + extra > total:
                rows.append([])
                used, extra = 0, width
            rows[-1].append((width, text))
            used += extra
        prefix = f"{self.title}: " if self.title else ""
        lines = []
        for index, row in enumerate(rows):
            text = self.GAP.join(item for _, item in row)
            length = sum(w for w, _ in row) + len(self.GAP) * (len(row) - 1)
            if index == 0 and prefix:
                text, length = prefix + text, length + len(prefix)
            lines.append(" " * max(0, (total - length) // 2) + text)
        return lines

    def height(self, total: int) -> int:
        """Extra rows consumed above/below the plot (0 for a right legend)."""
        if not self or self.position == "right":
            return 0
        return len(self.lines(total, False)) + 1

    def compose(self, body: list[str], total: int, colors: bool) -> list[str]:
        if not self:
            return body
        legend = self.lines(total, colors)
        if self.position == "top":
            return legend + [""] + body
        if self.position == "bottom":
            return body + [""] + legend
        body_width = max((visible_len(line) for line in body), default=0)
        out = []
        for index in range(max(len(body), len(legend))):
            left = body[index] if index < len(body) else ""
            right = legend[index] if index < len(legend) else ""
            pad = " " * (body_width - visible_len(left))
            out.append(left + pad + self.GAP + right if right else left)
        return out


def assemble(
    body: list[str],
    legend: Legend,
    total: int,
    colors: bool,
    title: str | None = None,
) -> str:
    lines = legend.compose(body, total, colors)
    if title:
        lines.insert(0, title.center(total).rstrip())
    return "\n".join(line.rstrip() for line in lines)


# --------------------------------------------------------------------------
# Interactive Tk base class
# --------------------------------------------------------------------------

@dataclass
class Hit:
    """A hover target: ``test(x, y)`` decides, ``tip`` is the tooltip content."""

    test: Callable[[float, float], bool]
    tip: Sequence
    overlay: Callable[[], None] | None = None


class ChartGUI:
    """Base class for the interactive Tk charts.

    Provides tooltips, hover highlighting, a clickable legend (click toggles a
    series, double-click isolates it), a light/dark theme (key ``t``), and a
    right-click menu.  Subclasses implement ``render(box)`` and, when the
    default legend is not suitable, ``legend_entries()``.
    """

    PAD = 10
    ROW_H = 22
    FONT_SIZE = 9

    def __init__(
        self,
        chart: Any,
        *,
        master: Any = None,
        title: str = "Chart",
        width: int = 800,
        height: int = 500,
        theme: str = "light",
        background: str | None = None,
        tooltips: bool = True,
    ) -> None:
        if tk is None:
            raise RuntimeError(
                "tkinter is not available on this system; "
                "use print(chart) for the text version instead"
            )
        if not isinstance(title, str):
            raise TypeError("Title must be a string")
        check_int("width", width, 1)
        check_int("height", height, 1)
        check_choice("theme", theme, tuple(THEMES))
        check_bool("tooltips", tooltips)
        if background is not None and not isinstance(background, str):
            raise TypeError("background must be a colour string or None")
        self.chart = chart
        self.theme_name = theme
        self.background = background
        self.tooltips = tooltips
        self.hidden: set = set()
        self._w, self._h = width, height
        self._hits: list[Hit] = []
        self._legend_hits: list[tuple] = []
        self._cursor = ""

        self.root = tk.Tk() if master is None else master.winfo_toplevel()
        if master is None:
            self.root.title(title)
        self.canvas = tk.Canvas(
            master if master is not None else self.root,
            width=width,
            height=height,
            background=self.theme["bg"],
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self._setup_fonts()
        self._setup_menu()
        canvas = self.canvas
        canvas.bind("<Configure>", self._on_resize)
        canvas.bind("<Motion>", self._on_motion)
        canvas.bind("<Leave>", self._on_leave)
        canvas.bind("<Enter>", lambda event: canvas.focus_set())
        canvas.bind("<Button-1>", self._on_click)
        canvas.bind("<Double-Button-1>", self._on_double_click)
        canvas.bind("<Button-3>", self._popup_menu)
        canvas.bind("<Button-2>", self._popup_menu)
        canvas.bind("<Control-Button-1>", self._popup_menu)
        canvas.bind("<Key-t>", lambda event: self.toggle_theme())
        canvas.bind("<Key-r>", lambda event: self.show_all())
        self.draw()

    # ----- theme / fonts / menu -------------------------------------------

    @property
    def theme(self) -> dict:
        colors = dict(THEMES[self.theme_name])
        if self.background is not None:
            colors["bg"] = self.background
        return colors

    def set_theme(self, name: str) -> None:
        check_choice("theme", name, tuple(THEMES))
        self.theme_name = name
        self.draw()

    def toggle_theme(self) -> None:
        self.set_theme("dark" if self.theme_name == "light" else "light")

    def _setup_fonts(self) -> None:
        try:
            family = tkfont.nametofont("TkDefaultFont").actual("family")
        except Exception:  # pragma: no cover - font lookup is platform specific
            family = "Helvetica"
        size = self.FONT_SIZE
        self.font = (family, size)
        self.font_bold = (family, size, "bold")
        self.font_small = (family, size - 1)
        self.font_title = (family, size + 3, "bold")
        self._measure_font = tkfont.Font(family=family, size=size)
        self._measure_bold = tkfont.Font(family=family, size=size, weight="bold")

    def measure(self, text: str, bold: bool = False) -> int:
        font = self._measure_bold if bold else self._measure_font
        return font.measure(text)

    def ellipsize(self, text: str, maxw: float) -> str:
        if self.measure(text) <= maxw:
            return text
        while text and self.measure(text + "…") > maxw:
            text = text[:-1]
        return text + "…" if text else ""

    def _setup_menu(self) -> None:
        menu = tk.Menu(self.canvas, tearoff=0)
        menu.add_command(label="Toggle dark mode (t)", command=self.toggle_theme)
        menu.add_command(label="Show all series (r)", command=self.show_all)
        menu.add_separator()
        menu.add_command(label="Export as PNG…", command=self.export_png)
        menu.add_command(label="Print chart in terminal", command=self.print_to_terminal)
        self._menu = menu

    def _popup_menu(self, event: Any) -> None:
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()

    def _render_canvas(self) -> Any:
        Image, ImageColor, ImageDraw, ImageFont = _pillow_modules()
        self.canvas.update_idletasks()
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if width < 1 or height < 1:
            raise RuntimeError("Cannot render a chart with an empty canvas")

        background = ImageColor.getrgb(self.canvas.cget("background"))
        image = Image.new("RGB", (width, height), background)
        draw = ImageDraw.Draw(image)
        fonts: dict[tuple[str, int, str], Any] = {}
        anchors = {
            "center": "mm", "n": "mt", "s": "mb", "e": "rm", "w": "lm",
            "ne": "rt", "nw": "lt", "se": "rb", "sw": "lb",
        }

        for item in self.canvas.find_all():
            item_type = self.canvas.type(item)
            coords = self.canvas.coords(item)
            if self.canvas.itemcget(item, "state") == "hidden":
                continue
            if item_type in ("line", "rectangle", "oval", "polygon", "arc"):
                fill = self.canvas.itemcget(item, "fill") or None
                outline = (
                    self.canvas.itemcget(item, "outline") or None
                    if item_type != "line" else None
                )
                width_px = max(1, round(float(self.canvas.itemcget(item, "width") or 1)))
                if item_type == "line":
                    draw.line(coords, fill=fill or "#000000", width=width_px)
                elif item_type == "rectangle":
                    draw.rectangle(coords, fill=fill, outline=outline, width=width_px)
                elif item_type == "oval":
                    draw.ellipse(coords, fill=fill, outline=outline, width=width_px)
                elif item_type == "polygon":
                    draw.polygon(coords, fill=fill, outline=outline, width=width_px)
                else:
                    start = float(self.canvas.itemcget(item, "start") or 0)
                    extent = float(self.canvas.itemcget(item, "extent") or 0)
                    style = self.canvas.itemcget(item, "style") or "pieslice"
                    if style == "arc":
                        draw.arc(coords, start, start + extent, fill=outline or fill, width=width_px)
                    elif style == "chord":
                        draw.chord(coords, start, start + extent, fill=fill, outline=outline, width=width_px)
                    else:
                        draw.pieslice(coords, start, start + extent, fill=fill, outline=outline, width=width_px)
            elif item_type == "text":
                text = self.canvas.itemcget(item, "text")
                fill = self.canvas.itemcget(item, "fill") or "#000000"
                font_spec = self.canvas.itemcget(item, "font")
                tk_font = tkfont.Font(root=self.canvas, font=font_spec)
                actual = tk_font.actual()
                font_key = (str(actual["family"]), abs(int(actual["size"])), str(actual["weight"]))
                if font_key not in fonts:
                    family, size, weight = font_key
                    try:
                        fonts[font_key] = ImageFont.truetype(
                            family, size, index=0
                        )
                    except OSError:
                        fonts[font_key] = ImageFont.load_default(size=size)
                draw.text(
                    coords, text, fill=fill, font=fonts[font_key],
                    anchor=anchors.get(self.canvas.itemcget(item, "anchor"), "mm"),
                    align=self.canvas.itemcget(item, "justify") or "left",
                )
            else:
                raise ValueError(f"Unsupported chart canvas item: {item_type}")
        return image

    def export_png(self, path: str | None = None) -> str | None:
        if path is None:
            path = filedialog.asksaveasfilename(
                defaultextension=".png", filetypes=[("PNG image", "*.png")]
            )
        if path:
            image = self._render_canvas()
            image.save(path, format="PNG")
        return path or None

    def print_to_terminal(self) -> None:
        print(self.chart)

    # ----- hooks for subclasses -------------------------------------------

    def is_empty(self) -> bool:
        return self.chart.is_empty()

    def legend_entries(self) -> list[LegendEntry]:
        return self.chart.legend_entries()

    def render(self, box: tuple[float, float, float, float]) -> None:
        raise NotImplementedError

    # ----- drawing --------------------------------------------------------

    def visible(self, key: Any) -> bool:
        return key not in self.hidden

    def draw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        theme = self.theme
        canvas.configure(background=theme["bg"])
        self._hits = []
        self._legend_hits = []
        x0, y0, x1, y1 = self.PAD, self.PAD, self._w - self.PAD, self._h - self.PAD
        if self.chart.title:
            canvas.create_text(
                self._w / 2, y0, text=self.chart.title, anchor="n",
                fill=theme["fg"], font=self.font_title,
            )
            y0 += 30
        if self.is_empty():
            canvas.create_text(
                self._w / 2, self._h / 2,
                text=f"(Empty {type(self.chart).__name__})",
                fill=theme["muted"], font=self.font,
            )
            return
        box = self.draw_legend((x0, y0, x1, y1))
        if box[2] - box[0] < 60 or box[3] - box[1] < 60:
            return
        self.render(box)

    def draw_legend(self, box: tuple) -> tuple:
        entries = self.legend_entries()
        chart = self.chart
        if not chart.legend or not entries:
            return box
        x0, y0, x1, y1 = box
        theme = self.theme
        swatch, gap, row_h = 12, 7, self.ROW_H
        if chart.legend_position == "right":
            widest = max(self.measure(e.label) for e in entries)
            if chart.legend_title:
                widest = max(widest, self.measure(chart.legend_title, True))
            lw = int(min(widest + swatch + gap + 16, max(110, (x1 - x0) * 0.3)))
            px, y = x1 - lw, y0 + 4
            if chart.legend_title:
                self.canvas.create_text(
                    px + 6, y + row_h / 2, text=chart.legend_title, anchor="w",
                    fill=theme["muted"], font=self.font_bold,
                )
                y += row_h
            for entry in entries:
                self._legend_entry(entry, px + 6, y, lw - 10)
                y += row_h
            return (x0, y0, px - 8, y1)
        span = x1 - x0
        sep = 18
        rows: list[list[tuple]] = [[]]
        used = 0
        for entry in entries:
            width = min(self.measure(entry.label) + swatch + gap, span)
            extra = width + (sep if rows[-1] else 0)
            if rows[-1] and used + extra > span:
                rows.append([])
                used, extra = 0, width
            rows[-1].append((entry, width))
            used += extra
        height = len(rows) * row_h + 6
        y = (y1 - height if chart.legend_position == "bottom" else y0) + 3
        for row in rows:
            row_w = sum(w for _, w in row) + sep * (len(row) - 1)
            x = x0 + (span - row_w) / 2
            for entry, width in row:
                self._legend_entry(entry, x, y, width)
                x += width + sep
            y += row_h
        if chart.legend_position == "bottom":
            return (x0, y0, x1, y1 - height - 4)
        return (x0, y0 + height + 4, x1, y1)

    def _legend_entry(self, entry: LegendEntry, x: float, y: float, maxw: float) -> None:
        canvas, theme = self.canvas, self.theme
        hidden = entry.key is not None and entry.key in self.hidden
        cy = y + self.ROW_H / 2 - 1
        color = theme["muted"] if hidden else entry.color
        fill = "" if hidden else entry.color
        shape = entry.shape
        if shape == "circle" or shape == "ring":
            canvas.create_oval(x + 1, cy - 5, x + 11, cy + 5,
                               fill="" if shape == "ring" else fill, outline=color, width=2)
        elif shape == "line":
            canvas.create_line(x, cy, x + 12, cy, fill=color, width=2)
            canvas.create_oval(x + 3, cy - 3, x + 9, cy + 3, fill=fill, outline=color)
        elif shape == "dash":
            canvas.create_line(x, cy, x + 12, cy, fill=color, width=3)
        else:
            canvas.create_rectangle(x, cy - 6, x + 12, cy + 6, fill=fill, outline=color, width=2)
        label = self.ellipsize(entry.label, maxw - 19)
        tx = x + 19
        canvas.create_text(tx, cy, text=label, anchor="w",
                           fill=theme["muted"] if hidden else theme["fg"], font=self.font)
        if hidden:
            canvas.create_line(tx, cy, tx + self.measure(label), cy, fill=theme["muted"])
        if entry.key is not None:
            self._legend_hits.append((x - 3, y, x + maxw + 3, y + self.ROW_H - 2, entry.key))

    # ----- legend interaction ---------------------------------------------

    def _toggleable(self) -> set:
        return {e.key for e in self.legend_entries() if e.key is not None}

    def toggle(self, key: Any) -> None:
        if key in self.hidden:
            self.hidden.discard(key)
        elif len(self._toggleable() - self.hidden) > 1:
            self.hidden.add(key)
        else:
            return
        self.draw()

    def isolate(self, key: Any) -> None:
        others = self._toggleable() - {key}
        self.hidden = set() if self.hidden == others else others
        self.draw()

    def show_all(self) -> None:
        if self.hidden:
            self.hidden = set()
            self.draw()

    def _legend_at(self, x: float, y: float) -> Any:
        for x1, y1, x2, y2, key in self._legend_hits:
            if x1 <= x <= x2 and y1 <= y <= y2:
                return key
        return None

    # ----- hover / tooltip ------------------------------------------------

    def add_hit(self, test: Callable, tip: Sequence, overlay: Callable | None = None) -> None:
        self._hits.append(Hit(test, tip, overlay))

    def overlay_rect(self, x1: float, y1: float, x2: float, y2: float) -> Callable:
        return lambda: self.canvas.create_rectangle(
            x1, y1, x2, y2, outline=self.theme["highlight"], width=2, tags="overlay"
        )

    def overlay_circle(self, cx: float, cy: float, radius: float) -> Callable:
        return lambda: self.canvas.create_oval(
            cx - radius - 2, cy - radius - 2, cx + radius + 2, cy + radius + 2,
            outline=self.theme["highlight"], width=2, tags="overlay",
        )

    def hit_rect(self, x1: float, y1: float, x2: float, y2: float,
                 tip: Sequence, *, outline: bool = True) -> None:
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        overlay = self.overlay_rect(x1, y1, x2, y2) if outline else None
        self.add_hit(lambda x, y: x1 <= x <= x2 and y1 <= y <= y2, tip, overlay)

    def hit_circle(self, cx: float, cy: float, radius: float, tip: Sequence) -> None:
        slack = max(radius, 7)
        self.add_hit(lambda x, y: (x - cx) ** 2 + (y - cy) ** 2 <= slack ** 2,
                     tip, self.overlay_circle(cx, cy, radius))

    def hit_test(self, x: float, y: float) -> Hit | None:
        for hit in reversed(self._hits):
            if hit.test(x, y):
                return hit
        return None

    def _set_cursor(self, cursor: str) -> None:
        if cursor != self._cursor:
            self._cursor = cursor
            self.canvas.configure(cursor=cursor)

    def _on_resize(self, event: Any) -> None:
        self._w, self._h = max(1, event.width), max(1, event.height)
        self.draw()

    def _on_leave(self, event: Any) -> None:
        self.canvas.delete("overlay")
        self._set_cursor("")

    def _on_motion(self, event: Any) -> None:
        self.canvas.delete("overlay")
        if self._legend_at(event.x, event.y) is not None:
            self._set_cursor("hand2")
            return
        self._set_cursor("")
        if not self.tooltips and not self._hits:
            return
        hit = self.hit_test(event.x, event.y)
        if hit is None:
            return
        if hit.overlay:
            hit.overlay()
        if self.tooltips and hit.tip:
            self.draw_tooltip(hit.tip, event.x, event.y)

    def _on_click(self, event: Any) -> None:
        key = self._legend_at(event.x, event.y)
        if key is not None:
            self.toggle(key)

    def _on_double_click(self, event: Any) -> None:
        key = self._legend_at(event.x, event.y)
        if key is not None:
            self.isolate(key)

    def round_rect(self, x1: float, y1: float, x2: float, y2: float, r: float, **kw: Any) -> Any:
        points = [
            x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y1 + r, x2, y2 - r, x2, y2 - r, x2, y2, x2 - r, y2, x2 - r, y2,
            x1 + r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y2 - r, x1, y1 + r,
            x1, y1 + r, x1, y1,
        ]
        return self.canvas.create_polygon(points, smooth=True, **kw)

    def draw_tooltip(self, rows: Sequence, x: float, y: float) -> None:
        """Rows are ``str`` or ``(text, swatch_colour | None, "bold" | None)``."""
        canvas, theme = self.canvas, self.theme
        norm = []
        for row in rows:
            if isinstance(row, str):
                row = (row, None, None)
            text, color, style = (tuple(row) + (None, None))[:3]
            norm.append((text, color, style))
        pad, line_h, swatch = 8, 17, 10
        widths = [
            self.measure(text, style == "bold") + (swatch + 6 if color else 0)
            for text, color, style in norm
        ]
        w = max(widths) + 2 * pad
        h = len(norm) * line_h + 2 * pad - 3
        tx, ty = x + 14, y + 16
        if tx + w > self._w - 4:
            tx = x - 14 - w
        if ty + h > self._h - 4:
            ty = y - 12 - h
        tx, ty = max(4, tx), max(4, ty)
        self.round_rect(tx, ty, tx + w, ty + h, 6, fill=theme["tip_bg"],
                        outline=theme["tip_bg"], tags="overlay")
        for index, (text, color, style) in enumerate(norm):
            cy = ty + pad - 1 + index * line_h + line_h / 2
            cx = tx + pad
            if color:
                canvas.create_rectangle(cx, cy - 5, cx + swatch, cy + 5, fill=color,
                                        outline=theme["tip_fg"], tags="overlay")
                cx += swatch + 6
            canvas.create_text(cx, cy, text=text, anchor="w", fill=theme["tip_fg"],
                               font=self.font_bold if style == "bold" else self.font,
                               tags="overlay")

    # ----- shared axis helpers --------------------------------------------

    def plot_box(self, box: tuple, ticks: Sequence[float], fmt: Callable = fmt_tick,
                 *, bottom: int = 28, top: int = 8, right: int = 6) -> tuple:
        widest = max((self.measure(fmt(t)) for t in ticks), default=20)
        x0, y0, x1, y1 = box
        return (x0 + widest + 14, y0 + top, x1 - right, y1 - bottom)

    def draw_y_grid(self, plot: tuple, ticks: Sequence[float], to_y: Callable,
                    fmt: Callable = fmt_tick, labels: bool = True) -> None:
        left, top, right, bottom = plot
        theme = self.theme
        for value in ticks:
            y = to_y(value)
            self.canvas.create_line(left, y, right, y, fill=theme["grid"])
            if labels:
                self.canvas.create_text(left - 8, y, text=fmt(value), anchor="e",
                                        fill=theme["muted"], font=self.font)
        if labels:
            self.canvas.create_line(left, top, left, bottom, fill=theme["axis"])

    def draw_x_grid(self, plot: tuple, ticks: Sequence[float], to_x: Callable,
                    fmt: Callable = fmt_tick, labels: bool = True) -> None:
        left, top, right, bottom = plot
        theme = self.theme
        for value in ticks:
            x = to_x(value)
            self.canvas.create_line(x, top, x, bottom, fill=theme["grid"])
            if labels:
                self.canvas.create_text(x, bottom + 6, text=fmt(value), anchor="n",
                                        fill=theme["muted"], font=self.font)
        self.canvas.create_line(left, bottom, right, bottom, fill=theme["axis"])

    def draw_category_labels(self, labels: Sequence[str], centres: Sequence[float],
                             slot: float, y: float) -> None:
        if not labels:
            return
        widest = max(self.measure(label) for label in labels) + 8
        stride = max(1, math.ceil(widest / max(slot, 1)))
        for index in range(0, len(labels), stride):
            text = self.ellipsize(labels[index], max(slot * stride - 6, 12))
            self.canvas.create_text(centres[index], y, text=text, anchor="n",
                                    fill=self.theme["fg"], font=self.font)

    def run(self) -> None:
        self.root.mainloop()
