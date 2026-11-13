"""Heat maps with a colour-bar legend."""

from __future__ import annotations

from .common import (
    ChartGUI, Legend, assemble, check_bool, check_colors_flag, check_covers,
    check_int, check_legend, check_range, contrast_text, fmt_num, fmt_pct,
    fmt_tick, gradient, hex_rgb, is_finite, is_number, nice_ticks, paint_bg,
    resolve_colors, check_hex, visible_len,
)

HEAT_STOPS = ("#313695", "#4575b4", "#74add1", "#fee090", "#a50026")


def _validate_matrix(data):
    if data is None:
        return []
    if not isinstance(data, list):
        raise TypeError("Heatmap data must be a list of rows or None")
    if not all(isinstance(row, list) for row in data):
        raise TypeError("Each heatmap row must be a list")
    matrix = [list(row) for row in data]
    width = len(matrix[0]) if matrix else 0
    if any(len(row) != width for row in matrix):
        raise ValueError("Heatmap rows must all have the same length")
    for row in matrix:
        for value in row:
            if not is_number(value):
                raise TypeError("Heatmap values must be numbers")
            if not is_finite(value):
                raise ValueError("Heatmap values must be finite")
    return matrix


class HeatMap:
    SHADES = " .:-=+*#%@"

    def __init__(
        self,
        data: list | None = None,
        row_labels: list | None = None,
        column_labels: list | None = None,
        *,
        value_range: tuple[int | float, int | float] | None = None,
        cell_width: int = 3,
        show_values: bool = False,
        colors: bool | None = None,
        legend: bool = True,
        legend_position: str = "right",
        legend_title: str | None = "Scale",
        title: str | None = None,
        palette: list | None = None,
    ) -> None:
        self.data = _validate_matrix(data)
        rows = len(self.data)
        columns = len(self.data[0]) if rows else 0
        for name, labels in (("row_labels", row_labels), ("column_labels", column_labels)):
            if labels is not None and not isinstance(labels, list):
                raise TypeError(f"{name} must be a list or None")
        self.row_labels = [str(i) for i in range(rows)] if row_labels is None else list(row_labels)
        self.column_labels = (
            [str(i) for i in range(columns)] if column_labels is None else list(column_labels)
        )
        if len(self.row_labels) != rows:
            raise ValueError("Number of row labels must match the matrix")
        if len(self.column_labels) != columns:
            raise ValueError("Number of column labels must match the matrix")
        if not all(isinstance(l, str) for l in self.row_labels):
            raise TypeError("Row labels must be strings")
        if not all(isinstance(l, str) for l in self.column_labels):
            raise TypeError("Column labels must be strings")
        check_int("cell_width", cell_width, 1)
        check_bool("show_values", show_values)
        check_colors_flag(colors)
        check_legend(legend, legend_position, legend_title)
        if title is not None and not isinstance(title, str):
            raise TypeError("title must be a string or None")
        if palette is None:
            stops = HEAT_STOPS
        else:
            if not isinstance(palette, (list, tuple)) or len(palette) < 2:
                raise TypeError("palette must be a list of at least two '#rrggbb' colours")
            stops = tuple(check_hex("palette colours", c) for c in palette)
        values = [v for row in self.data for v in row]
        given = check_range(value_range, "value_range")
        check_covers(given, values, "value_range")
        if given is not None:
            self.value_range = given
        elif not values:
            self.value_range = (0.0, 1.0)
        else:
            low, high = min(values), max(values)
            if low == high:
                pad = max(abs(low) * 0.05, 1.0)
                low, high = low - pad, high + pad
            self.value_range = (low, high)
        self.cell_width, self.show_values = cell_width, show_values
        self.ansi = resolve_colors(colors)
        self.stops = stops
        self.legend, self.legend_position, self.legend_title = legend, legend_position, legend_title
        self.title = title

    def is_empty(self) -> bool:
        return not self.data or not self.data[0]

    def legend_entries(self) -> list:
        return []

    def fraction(self, value: float) -> float:
        low, high = self.value_range
        return (value - low) / (high - low)

    def color(self, value: float) -> str:
        return gradient(self.stops, self.fraction(value))

    def _index(self, value: float) -> int:
        return round(self.fraction(value) * 9)

    def _bar_lines(self) -> list[str]:
        low, high = self.value_range
        shade = lambda i: (self.SHADES[i] if i else "·") * 2
        cell = lambda i, f: paint_bg("  ", gradient(self.stops, f)) if self.ansi else shade(i)
        if self.legend_position == "right":
            lines = [self.legend_title] if self.legend_title else []
            marks = {0: fmt_tick(high), 4: fmt_tick((low + high) / 2), 9: fmt_tick(low)}
            for k in range(10):
                level = 9 - k
                lines.append(f"{cell(level, level / 9)} {marks.get(k, '')}".rstrip())
            return lines
        bar = "".join(cell(round(k * 9 / 19), k / 19) for k in range(20))
        line = f"{fmt_tick(low)} {bar} {fmt_tick(high)}"
        return ([f"{self.legend_title}: {line}"] if self.legend_title else [line])

    def __str__(self) -> str:
        if self.is_empty():
            return "(Empty HeatMap)"
        texts = [[f"{v:g}" for v in row] for row in self.data]
        cw = max(self.cell_width, max(map(len, self.column_labels)))
        if self.show_values:
            cw = max(cw, max(len(t) for row in texts for t in row))
        row_width = max(map(len, self.row_labels))
        header = " " * (row_width + 2) + " ".join(l.center(cw) for l in self.column_labels)
        lines = [header.rstrip()]
        for r, row in enumerate(self.data):
            cells = []
            for c, value in enumerate(row):
                text = texts[r][c].center(cw) if self.show_values else (self.SHADES[self._index(value)].replace(" ", "·")) * cw
                cells.append(paint_bg(text, self.color(value)) if self.ansi else text)
            lines.append(f"{self.row_labels[r]:>{row_width}}  " + " ".join(cells))
        total = max(visible_len(line) for line in lines)
        legend = Legend([], self.legend_position, None, self.legend, self._bar_lines())
        return assemble(lines, legend, total, self.ansi, self.title)


class HeatMapGUI(ChartGUI):
    """Interactive heat map: hover a cell for its value; a marker on the colour
    bar shows where the value sits on the scale."""

    COLORS = HEAT_STOPS

    def __init__(
        self,
        data: list | None = None,
        row_labels: list | None = None,
        column_labels: list | None = None,
        *,
        master=None,
        title: str = "Heat Map",
        width: int = 800,
        height: int = 500,
        value_range: tuple[int | float, int | float] | None = None,
        show_values: bool = False,
        background: str | None = None,
        legend: bool = True,
        legend_position: str = "right",
        legend_title: str | None = "Scale",
        chart_title: str | None = None,
        palette: list | None = None,
        theme: str = "light",
        tooltips: bool = True,
    ) -> None:
        chart = HeatMap(
            data, row_labels, column_labels, value_range=value_range,
            show_values=show_values, legend=legend, legend_position=legend_position,
            legend_title=legend_title, title=chart_title, palette=palette,
        )
        self._bar = None
        super().__init__(chart, master=master, title=title, width=width, height=height,
                         theme=theme, background=background, tooltips=tooltips)

    def draw_legend(self, box):
        chart, canvas, theme = self.chart, self.canvas, self.theme
        self._bar = None
        if not chart.legend:
            return box
        x0, y0, x1, y1 = box
        low, high = chart.value_range
        _, _, ticks = nice_ticks(low, high, 5, expand=False)
        steps = 48
        if chart.legend_position == "right":
            label_w = max(self.measure(fmt_tick(t)) for t in ticks)
            lw = 16 + 8 + label_w + 12
            bx = x1 - lw + 4
            by0 = y0 + (28 if chart.legend_title else 8)
            by1 = min(y1 - 8, by0 + 240)
            if chart.legend_title:
                canvas.create_text(bx, y0 + 6, text=chart.legend_title, anchor="w",
                                   fill=theme["muted"], font=self.font_bold)
            for k in range(steps):
                f = 1 - k / steps
                canvas.create_rectangle(
                    bx, by0 + (by1 - by0) * k / steps, bx + 16,
                    by0 + (by1 - by0) * (k + 1) / steps + 1,
                    fill=gradient(chart.stops, f - 0.5 / steps), outline="")
            canvas.create_rectangle(bx, by0, bx + 16, by1, outline=theme["axis"])
            for t in ticks:
                y = by1 - (t - low) / (high - low) * (by1 - by0)
                canvas.create_line(bx + 16, y, bx + 20, y, fill=theme["axis"])
                canvas.create_text(bx + 24, y, text=fmt_tick(t), anchor="w",
                                   fill=theme["muted"], font=self.font_small)
            self._bar = ("v", bx, by0, bx + 16, by1)
            return (x0, y0, bx - 12, y1)
        bw = min(320, x1 - x0 - 40)
        bh = 14
        height = bh + 30
        by = (y1 - height + 6) if chart.legend_position == "bottom" else y0 + 6
        bx = x0 + (x1 - x0 - bw) / 2
        for k in range(steps):
            canvas.create_rectangle(
                bx + bw * k / steps, by, bx + bw * (k + 1) / steps + 1, by + bh,
                fill=gradient(chart.stops, (k + 0.5) / steps), outline="")
        canvas.create_rectangle(bx, by, bx + bw, by + bh, outline=theme["axis"])
        for t in ticks:
            x = bx + (t - low) / (high - low) * bw
            canvas.create_line(x, by + bh, x, by + bh + 4, fill=theme["axis"])
            canvas.create_text(x, by + bh + 6, text=fmt_tick(t), anchor="n",
                               fill=theme["muted"], font=self.font_small)
        self._bar = ("h", bx, by, bx + bw, by + bh)
        if chart.legend_position == "bottom":
            return (x0, y0, x1, y1 - height - 6)
        return (x0, y0 + height + 6, x1, y1)

    def _marker(self, fraction: float):
        """Overlay: a small marker on the colour bar at ``fraction``."""
        def draw() -> None:
            if self._bar is None:
                return
            kind, x1, y1, x2, y2 = self._bar
            hl = self.theme["highlight"]
            if kind == "v":
                y = y2 - fraction * (y2 - y1)
                self.canvas.create_polygon(x1 - 7, y - 5, x1 - 1, y, x1 - 7, y + 5,
                                           fill=hl, tags="overlay")
                self.canvas.create_line(x1, y, x2, y, fill=hl, width=2, tags="overlay")
            else:
                x = x1 + fraction * (x2 - x1)
                self.canvas.create_polygon(x - 5, y1 - 7, x + 5, y1 - 7, x, y1 - 1,
                                           fill=hl, tags="overlay")
                self.canvas.create_line(x, y1, x, y2, fill=hl, width=2, tags="overlay")
        return draw

    def render(self, box) -> None:
        chart, canvas, theme = self.chart, self.canvas, self.theme
        matrix = chart.data
        x0, y0, x1, y1 = box
        label_w = max(self.measure(l) for l in chart.row_labels) + 14
        left, top, right, bottom = x0 + label_w, y0 + 26, x1 - 4, y1 - 4
        cols, rows = len(matrix[0]), len(matrix)
        cw, ch = (right - left) / cols, (bottom - top) / rows
        for c, label in enumerate(chart.column_labels):
            canvas.create_text(left + (c + 0.5) * cw, top - 8, anchor="s",
                               text=self.ellipsize(label, cw - 4), fill=theme["fg"], font=self.font)
        for r, row in enumerate(matrix):
            canvas.create_text(left - 8, top + (r + 0.5) * ch, anchor="e",
                               text=self.ellipsize(chart.row_labels[r], label_w - 12),
                               fill=theme["fg"], font=self.font)
            for c, value in enumerate(row):
                x1c, y1c = left + c * cw, top + r * ch
                x2c, y2c = x1c + cw, y1c + ch
                color = chart.color(value)
                canvas.create_rectangle(x1c, y1c, x2c, y2c, fill=color, outline=theme["bg"])
                if chart.show_values:
                    canvas.create_text((x1c + x2c) / 2, (y1c + y2c) / 2, text=f"{value:g}",
                                       fill=contrast_text(color), font=self.font)
                tip = [
                    (f"{chart.row_labels[r]} · {chart.column_labels[c]}", None, "bold"),
                    (f"Value: {fmt_num(value)}", color, None),
                    (f"Scale position: {fmt_pct(chart.fraction(value))}", None, None),
                ]
                marker = self._marker(chart.fraction(value))
                outline = self.overlay_rect(x1c, y1c, x2c, y2c)
                self.add_hit(
                    lambda x, y, a=x1c, b=y1c, c2=x2c, d=y2c: a <= x <= c2 and b <= y <= d,
                    tip, lambda o=outline, m=marker: (o(), m()),
                )


if __name__ == "__main__":
    matrix = [[1, 4, 7], [2, 5, 8], [3, 6, 9]]
    print(HeatMap(matrix, show_values=True))
    HeatMapGUI(matrix, show_values=True).run()
