"""Line charts with one or several series.

``data`` is a list of numbers (one series) or ``{name: [numbers]}``.
``AreaChart`` (area.py) subclasses these classes.
"""

from __future__ import annotations

from .common import (
    MARKERS, PALETTE, ChartGUI, Grid, Legend, LegendEntry, assemble, check_bool,
    check_char, check_colors_flag, check_covers, check_int, check_labels,
    check_legend, check_palette, check_range, fmt_num, fmt_tick, label_row,
    nice_ticks, normalize_series, resolve_colors, slot_centre, terminal_size,
)


class LineChart:
    INCLUDE_ZERO = False  # areas always include the baseline

    def __init__(
        self,
        data: list | dict | None = None,
        category_labels: list | None = None,
        *,
        height: int | None = None,
        width: int | None = None,
        show_values: bool = True,
        show_axis: bool = True,
        show_y_axis: bool = True,
        y_ticks: int = 5,
        y_axis_range: tuple[int | float, int | float] | None = None,
        colors: bool | None = None,
        point_char: str = "●",
        series_name: str = "Value",
        legend: bool = True,
        legend_position: str = "bottom",
        legend_title: str | None = None,
        title: str | None = None,
        palette: list | None = None,
    ) -> None:
        names, columns, multi = normalize_series(data, series_name, "Line chart values")
        categories = check_labels(category_labels, len(columns[0]))
        for name, value in (("height", height), ("width", width), ("y_ticks", y_ticks)):
            check_int(name, value, none_ok=True)
        if height is not None and height < 3:
            raise ValueError("Height must be at least 3")
        if width is not None and width < 1:
            raise ValueError("Width must be positive")
        if y_ticks < 2:
            raise ValueError("y_ticks must be at least 2")
        for name, value in (
            ("show_values", show_values), ("show_axis", show_axis), ("show_y_axis", show_y_axis),
        ):
            check_bool(name, value)
        check_colors_flag(colors)
        check_char("point_char", point_char)
        check_legend(legend, legend_position, legend_title)
        if title is not None and not isinstance(title, str):
            raise TypeError("title must be a string or None")
        self.series_names, self.series_values, self.multi = names, columns, multi
        self.categories = categories
        self.y_axis_range = check_range(y_axis_range, "y_axis_range")
        self.height, self.width = height, width
        self.show_values, self.show_axis, self.show_y_axis = show_values, show_axis, show_y_axis
        self.y_ticks = y_ticks
        self.ansi = resolve_colors(colors)
        self.color_by_point = colors is True and not multi
        self.point_char = point_char
        self.palette = check_palette(palette)
        self.legend, self.legend_position, self.legend_title = legend, legend_position, legend_title
        self.title = title
        self._check_range_covers()

    # ----- data -----------------------------------------------------------

    @property
    def data(self):
        if self.multi:
            return dict(zip(self.series_names, self.series_values))
        return self.series_values[0]

    def is_empty(self) -> bool:
        return not self.categories

    def _layers(self, series: list[int] | None = None) -> list[tuple]:
        """``(series, top_values, bottom_values | None)`` per drawn series."""
        series = range(len(self.series_values)) if series is None else series
        return [(s, self.series_values[s], None) for s in series]

    def _extent(self, series: list[int] | None = None) -> tuple[float, float]:
        values = []
        for _, top, bottom in self._layers(series):
            values.extend(top)
            if bottom is not None:
                values.extend(bottom)
        if self.INCLUDE_ZERO:
            values.append(0.0)
        if not values:
            return 0.0, 1.0
        low, high = min(values), max(values)
        return (low - 1, high + 1) if low == high else (low, high)

    def _check_range_covers(self) -> None:
        if self.y_axis_range is not None and self.categories:
            low, high = self._extent()
            check_covers(self.y_axis_range, [low, high], "y_axis_range")

    def axis(self, series: list[int] | None = None, target: int | None = None):
        target = target or self.y_ticks
        if self.y_axis_range is not None:
            return nice_ticks(*self.y_axis_range, target, expand=False)
        return nice_ticks(*self._extent(series), target)

    def point_color(self, s: int, i: int) -> str:
        index = i if self.color_by_point else s
        return self.palette[index % len(self.palette)]

    def _marker(self, s: int) -> str:
        if s == 0 and (self.point_char != "●" or not self.multi):
            return self.point_char
        return MARKERS[s % len(MARKERS)]

    def _label(self, i: int) -> str:
        label = self.categories[i]
        if self.show_values and not self.multi and not self._stacked():
            return f"{label} ({self.series_values[0][i]:g})"
        return label

    def _stacked(self) -> bool:
        return False

    def legend_entries(self) -> list[LegendEntry]:
        return [
            LegendEntry(("s", s), name, self.palette[s % len(self.palette)],
                        self._legend_marker(s), "line")
            for s, name in enumerate(self.series_names)
        ]

    def _legend_marker(self, s: int) -> str:
        return self._marker(s)

    def _legend(self) -> Legend:
        return Legend(self.legend_entries(), self.legend_position, self.legend_title, self.legend)

    # ----- text rendering -------------------------------------------------

    def __str__(self) -> str:
        if self.is_empty():
            return f"(Empty {type(self).__name__})"
        term = terminal_size()
        total = self.width or term.columns
        legend = self._legend()
        height = self.height or max(
            3, term.lines - 5 - legend.height(total) - (1 if self.title else 0)
        )
        low, high, ticks = self.axis(target=min(self.y_ticks, max(2, (height + 1) // 2)))
        span = high - low
        row_of = lambda v: round((high - v) / span * (height - 1))
        base_val = min(max(0.0, low), high)
        labels = {}
        for tick in ticks:
            labels.setdefault(row_of(tick), fmt_tick(tick))
        y_width = max(len(text) for text in labels.values())
        prefix_w = y_width + 3 if self.show_y_axis else 0
        plot_w = max(1, total - legend.reserve_width(total) - prefix_w)
        count = len(self.categories)
        xs = [slot_centre(i, count, plot_w) for i in range(count)]
        grid = Grid(plot_w, height)
        for row in labels:
            grid.hline(row, 0, plot_w - 1, "·")
        if self.show_axis:
            grid.hline(row_of(base_val), 0, plot_w - 1, "─")
        layers = self._layers()
        self._decorate(grid, xs, layers, row_of, base_val)
        for s, top, _ in layers:
            color = self.palette[s % len(self.palette)]
            rows = [row_of(v) for v in top]
            for i in range(count - 1):
                self._segment(grid, xs[i], rows[i], xs[i + 1], rows[i + 1], color)
        for s, top, _ in layers:
            for i in range(count):
                grid.put(xs[i], row_of(top[i]), self._marker(s), self.point_color(s, i))
        lines = []
        for r, line in enumerate(grid.rows(self.ansi)):
            prefix = (labels.get(r, "").rjust(y_width) + " │ ") if self.show_y_axis else ""
            lines.append(prefix + line)
        lines.append(" " * prefix_w + label_row(
            plot_w, [(xs[i], self._label(i)) for i in range(count)]))
        return assemble(lines, legend, total, self.ansi, self.title)

    @staticmethod
    def _segment(grid, x1, y1, x2, y2, color) -> None:
        steps = max(abs(x2 - x1), abs(y2 - y1), 1)
        if y1 == y2:
            char = "─"
        elif x1 == x2:
            char = "│"
        else:
            char = "╱" if y2 < y1 else "╲"
        for step in range(steps + 1):
            fraction = step / steps
            grid.put(round(x1 + (x2 - x1) * fraction), round(y1 + (y2 - y1) * fraction), char, color)

    def _decorate(self, grid, xs, layers, row_of, base_val) -> None:
        """Hook drawn under the lines (areas fill here)."""


class LineChartGUI(ChartGUI):
    """Interactive line chart: hover for a crosshair and a tooltip listing every
    series at that position; click the legend to hide or isolate series."""

    CHART = LineChart

    def __init__(
        self,
        data: list | dict | None = None,
        category_labels: list | None = None,
        *,
        master=None,
        title: str = "Line Chart",
        width: int = 800,
        height: int = 500,
        y_ticks: int = 5,
        y_axis_range: tuple[int | float, int | float] | None = None,
        show_values: bool = True,
        show_axis: bool = True,
        show_y_axis: bool = True,
        colors: bool = False,
        line_color: str = "#4e79a7",
        background: str | None = None,
        series_name: str = "Value",
        smooth: bool = False,
        legend: bool = True,
        legend_position: str = "right",
        legend_title: str | None = None,
        chart_title: str | None = None,
        palette: list | None = None,
        theme: str = "light",
        tooltips: bool = True,
        **extra,
    ) -> None:
        check_bool("colors", colors)
        check_bool("smooth", smooth)
        colours = list(check_palette(palette))
        colours[0] = line_color
        self.smooth = smooth
        chart = self.CHART(
            data, category_labels, y_ticks=y_ticks, y_axis_range=y_axis_range,
            show_values=show_values, show_axis=show_axis, show_y_axis=show_y_axis,
            colors=colors, series_name=series_name, legend=legend,
            legend_position=legend_position, legend_title=legend_title,
            title=chart_title, palette=colours, **extra,
        )
        super().__init__(chart, master=master, title=title, width=width, height=height,
                         theme=theme, background=background, tooltips=tooltips)

    def _visible_series(self) -> list[int]:
        return [s for s in range(len(self.chart.series_values)) if self.visible(("s", s))]

    def _tip(self, i: int, layers) -> list:
        chart = self.chart
        rows = [(chart.categories[i] or f"#{i + 1}", None, "bold")]
        total = 0.0
        for s, _, _ in layers:
            v = chart.series_values[s][i]
            total += v
            rows.append((f"{chart.series_names[s]}: {fmt_num(v)}",
                         chart.palette[s % len(chart.palette)], None))
        if chart._stacked():
            rows.append((f"Total: {fmt_num(total)}", None, None))
        return rows

    def _fill_layer(self, layer, points_top, points_bottom, color) -> None:
        """Hook for the area chart."""

    def render(self, box) -> None:
        chart, canvas, theme = self.chart, self.canvas, self.theme
        series = self._visible_series()
        low, high, ticks = chart.axis(series)
        span = high - low
        plot = self.plot_box(box, ticks, bottom=30)
        left, top, right, bottom = plot
        y_for = lambda v: bottom - (v - low) / span * (bottom - top)
        self.draw_y_grid(plot, ticks, y_for, labels=chart.show_y_axis)
        base_val = min(max(0.0, low), high)
        if chart.show_axis:
            canvas.create_line(left, y_for(base_val), right, y_for(base_val),
                               fill=theme["axis"], width=2)
        count = len(chart.categories)
        slot = (right - left) / count
        xs = [left + slot * (i + 0.5) for i in range(count)]
        layers = chart._layers(series)
        base_y = y_for(base_val)
        for layer in layers:
            s, tops, bottoms = layer
            color = chart.palette[s % len(chart.palette)]
            top_pts = [(xs[i], y_for(v)) for i, v in enumerate(tops)]
            bot_pts = ([(xs[i], y_for(v)) for i, v in enumerate(bottoms)]
                       if bottoms is not None else [(xs[i], base_y) for i in range(count)])
            self._fill_layer(layer, top_pts, bot_pts, color)
        for s, tops, _ in layers:
            color = chart.palette[s % len(chart.palette)]
            pts = [(xs[i], y_for(v)) for i, v in enumerate(tops)]
            if count > 1:
                flat = [c for p in pts for c in p]
                canvas.create_line(*flat, fill=color, width=2, smooth=self.smooth)
            for i, (x, y) in enumerate(pts):
                pc = chart.point_color(s, i)
                canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill=pc, outline=theme["bg"], width=1)
        self.draw_category_labels([chart._label(i) for i in range(count)], xs, slot, bottom + 8)
        for i in range(count):
            self._add_column(i, xs[i], slot, top, bottom, layers, y_for)

    def _add_column(self, i, x, slot, top, bottom, layers, y_for) -> None:
        chart = self.chart
        theme_hl = lambda: self.theme["highlight"]

        def overlay() -> None:
            self.canvas.create_line(x, top, x, bottom, fill=theme_hl(), dash=(3, 3), tags="overlay")
            for s, tops, _ in layers:
                y = y_for(tops[i])
                self.canvas.create_oval(x - 6, y - 6, x + 6, y + 6, outline=theme_hl(),
                                        width=2, tags="overlay")

        x1, x2 = x - slot / 2, x + slot / 2
        self.add_hit(lambda px, py: x1 <= px <= x2 and top <= py <= bottom,
                     self._tip(i, layers), overlay)


if __name__ == "__main__":
    print(LineChart([4, 7, 3, 9, 6], ["A", "B", "C", "D", "E"], show_values=False))
    sales = {"North": [4, 7, 3, 9, 6], "South": [2, 3, 6, 4, 8]}
    print(LineChart(sales, ["Mon", "Tue", "Wed", "Thu", "Fri"], height=10))
    LineChartGUI(sales, ["Mon", "Tue", "Wed", "Thu", "Fri"]).run()
