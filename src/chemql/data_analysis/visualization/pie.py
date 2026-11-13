"""Pie and donut charts."""

from __future__ import annotations

import math

from .common import (
    FILLS, ChartGUI, Grid, Legend, LegendEntry, assemble, check_bool,
    check_choice, check_colors_flag, check_int, check_labels, check_legend,
    check_numbers, check_palette, contrast_text, fmt_num, fmt_pct,
    resolve_colors, terminal_size,
)


class PieChart:
    """``data`` is a list of non-negative numbers; ``category_labels`` names them.

    Set ``donut=True`` for a ring.  The legend shows each slice's share.
    """

    def __init__(
        self,
        data: list | dict | None = None,
        category_labels: list | None = None,
        *,
        radius: int | None = None,
        width: int | None = None,
        donut: bool = False,
        sort: str | None = None,
        colors: bool | None = None,
        show_percent: bool = True,
        legend: bool = True,
        legend_position: str = "right",
        legend_title: str | None = None,
        title: str | None = None,
        palette: list | None = None,
    ) -> None:
        if isinstance(data, dict):
            if category_labels is not None:
                raise TypeError("Pass either a dict or category_labels, not both")
            category_labels = list(data)
            data = list(data.values())
        values = [] if data is None else check_numbers(data, "Pie values")
        if any(v < 0 for v in values):
            raise ValueError("Pie values must not be negative")
        labels = check_labels(category_labels, len(values))
        check_int("radius", radius, 2, none_ok=True)
        check_int("width", width, 1, none_ok=True)
        check_bool("donut", donut)
        check_bool("show_percent", show_percent)
        check_colors_flag(colors)
        if sort is not None:
            check_choice("sort", sort, ("ascending", "descending"))
        check_legend(legend, legend_position, legend_title)
        if title is not None and not isinstance(title, str):
            raise TypeError("title must be a string or None")
        if sort is not None:
            order = sorted(range(len(values)), key=lambda i: values[i], reverse=sort == "descending")
            values, labels = [values[i] for i in order], [labels[i] for i in order]
        self.data, self.categories = values, labels
        self.radius, self.width = radius, width
        self.donut, self.show_percent = donut, show_percent
        self.ansi = resolve_colors(colors)
        self.palette = check_palette(palette)
        self.legend, self.legend_position, self.legend_title = legend, legend_position, legend_title
        self.title = title

    def is_empty(self) -> bool:
        return not self.data or sum(self.data) == 0

    def name(self, i: int) -> str:
        return self.categories[i] or f"Slice {i + 1}"

    def color(self, i: int) -> str:
        return self.palette[i % len(self.palette)]

    def _glyph(self, i: int) -> str:
        return "█" if self.ansi else FILLS[i % len(FILLS)]

    def legend_entries(self) -> list[LegendEntry]:
        total = sum(self.data) or 1
        entries = []
        for i, value in enumerate(self.data):
            label = self.name(i)
            if self.show_percent:
                label += f"  {fmt_pct(value / total)}"
            entries.append(LegendEntry(("c", i), label, self.color(i), self._glyph(i), "square"))
        return entries

    def _legend(self) -> Legend:
        return Legend(self.legend_entries(), self.legend_position, self.legend_title, self.legend)

    def __str__(self) -> str:
        if self.is_empty():
            return "(Empty PieChart)"
        term = terminal_size()
        total_w = self.width or term.columns
        legend = self._legend()
        radius = self.radius or max(3, min(10, (term.lines - 4 - legend.height(total_w)) // 2))
        # Terminal cells are about twice as tall as wide.
        w, h = radius * 4 + 1, radius * 2 + 1
        cx, cy = radius * 2, radius
        inner = radius * 0.5 if self.donut else 0
        total = sum(self.data)
        bounds, acc = [], 0.0
        for value in self.data:
            acc += value / total
            bounds.append(acc)
        grid = Grid(w, h)
        for y in range(h):
            for x in range(w):
                dx, dy = (x - cx) / 2, y - cy
                dist = math.hypot(dx, dy)
                if dist > radius + 0.25 or dist < inner:
                    continue
                angle = (math.atan2(dx, -dy) / (2 * math.pi)) % 1.0
                index = next((i for i, b in enumerate(bounds) if angle < b and self.data[i] > 0),
                             len(bounds) - 1)
                grid.put(x, y, self._glyph(index), self.color(index))
        if self.donut:
            text = fmt_num(total)
            grid.text(cx - len(text) // 2, cy, text)
        lines = grid.rows(self.ansi)
        return assemble(lines, legend, total_w, self.ansi, self.title)


class PieChartGUI(ChartGUI):
    """Interactive pie: hover pops a slice out and shows its value and share;
    click legend entries to hide slices (the rest re-scale)."""

    def __init__(
        self,
        data: list | dict | None = None,
        category_labels: list | None = None,
        *,
        master=None,
        title: str = "Pie Chart",
        width: int = 800,
        height: int = 500,
        donut: bool = False,
        sort: str | None = None,
        show_percent: bool = True,
        background: str | None = None,
        legend: bool = True,
        legend_position: str = "right",
        legend_title: str | None = None,
        chart_title: str | None = None,
        palette: list | None = None,
        theme: str = "light",
        tooltips: bool = True,
    ) -> None:
        chart = PieChart(
            data, category_labels, donut=donut, sort=sort, show_percent=show_percent,
            legend=legend, legend_position=legend_position, legend_title=legend_title,
            title=chart_title, palette=palette,
        )
        super().__init__(chart, master=master, title=title, width=width, height=height,
                         theme=theme, background=background, tooltips=tooltips)

    def render(self, box) -> None:
        chart, canvas, theme = self.chart, self.canvas, self.theme
        shown = [i for i, v in enumerate(chart.data) if self.visible(("c", i)) and v > 0]
        total = sum(chart.data[i] for i in shown)
        if not shown or total == 0:
            return
        x0, y0, x1, y1 = box
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        radius = max(20.0, min(x1 - x0, y1 - y0) / 2 - 14)
        inner = radius * 0.55 if chart.donut else 0.0
        bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
        start = 0.0
        spans = []
        for i in shown:
            sweep = chart.data[i] / total * 360
            spans.append((i, start, sweep))
            start += sweep
        for i, begin, sweep in spans:
            color = chart.color(i)
            if sweep >= 359.99:
                canvas.create_oval(*bbox, fill=color, outline=theme["bg"], width=2)
            else:
                canvas.create_arc(*bbox, start=90 - begin, extent=-sweep, style="pieslice",
                                  fill=color, outline=theme["bg"], width=2)
        if chart.donut:
            canvas.create_oval(cx - inner, cy - inner, cx + inner, cy + inner,
                               fill=theme["bg"], outline=theme["bg"])
            canvas.create_text(cx, cy - 9, text=fmt_num(total), fill=theme["fg"], font=self.font_title)
            canvas.create_text(cx, cy + 12, text="total", fill=theme["muted"], font=self.font_small)
        for i, begin, sweep in spans:
            color = chart.color(i)
            mid = math.radians(begin + sweep / 2)
            if chart.show_percent and sweep >= 14:
                r = (radius + inner) / 2
                canvas.create_text(cx + r * math.sin(mid), cy - r * math.cos(mid),
                                   text=fmt_pct(chart.data[i] / total),
                                   fill=contrast_text(color), font=self.font_bold)
            rows = [
                (chart.name(i), color, "bold"),
                (f"Value: {fmt_num(chart.data[i])}", None, None),
                (f"Share: {fmt_pct(chart.data[i] / total)}", None, None),
            ]
            self.add_hit(self._wedge_test(cx, cy, radius, inner, begin, sweep), rows,
                         self._explode(cx, cy, radius, inner, begin, sweep, color))

    @staticmethod
    def _wedge_test(cx, cy, radius, inner, begin, sweep):
        def test(x: float, y: float) -> bool:
            dx, dy = x - cx, y - cy
            dist = math.hypot(dx, dy)
            if dist > radius or dist < inner:
                return False
            angle = math.degrees(math.atan2(dx, -dy)) % 360
            return begin <= angle < begin + sweep or sweep >= 359.99
        return test

    def _explode(self, cx, cy, radius, inner, begin, sweep, color):
        """Overlay: draw the slice again, pushed outwards."""
        def draw() -> None:
            mid = math.radians(begin + sweep / 2)
            ox, oy = 8 * math.sin(mid), -8 * math.cos(mid)
            bbox = (cx - radius + ox, cy - radius + oy, cx + radius + ox, cy + radius + oy)
            hl = self.theme["highlight"]
            if sweep >= 359.99:
                self.canvas.create_oval(*bbox, fill=color, outline=hl, width=2, tags="overlay")
            else:
                self.canvas.create_arc(*bbox, start=90 - begin, extent=-sweep, style="pieslice",
                                       fill=color, outline=hl, width=2, tags="overlay")
            if inner:
                self.canvas.create_oval(cx - inner + ox, cy - inner + oy, cx + inner + ox,
                                        cy + inner + oy, fill=self.theme["bg"],
                                        outline=self.theme["bg"], tags="overlay")
        return draw


if __name__ == "__main__":
    data = [40, 25, 20, 15]
    labels = ["Rent", "Food", "Travel", "Other"]
    print(PieChart(data, labels))
    print(PieChart(data, labels, donut=True, legend_position="bottom"))
    PieChartGUI(data, labels, donut=True).run()
