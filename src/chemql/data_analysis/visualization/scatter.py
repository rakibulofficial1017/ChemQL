"""Scatter plots with one or several series.

``points`` is a list of ``(x, y)`` pairs, or ``{name: [(x, y), ...]}`` for
several series.  ``point_labels`` follows the same shape (list / dict of lists).
"""

from __future__ import annotations

from .common import (
    MARKERS, ChartGUI, Grid, Legend, LegendEntry, assemble, check_bool,
    check_char, check_colors_flag, check_covers, check_int, check_labels,
    check_legend, check_palette, check_range, data_range, fmt_num, fmt_tick,
    is_finite, is_number, label_row, nice_ticks, resolve_colors, terminal_size,
)


def _check_points(points, what="Points"):
    if not isinstance(points, list):
        raise TypeError(f"{what} must be a list")
    result = []
    for point in points:
        if not isinstance(point, (tuple, list)) or len(point) != 2:
            raise TypeError("Each point must contain an (x, y) pair")
        for value in point:
            if not is_number(value):
                raise TypeError("Point coordinates must be numbers")
            if not is_finite(value):
                raise ValueError("Point coordinates must be finite")
        result.append((point[0], point[1]))
    return result


class ScatterPlot:
    def __init__(
        self,
        points: list | dict | None = None,
        point_labels: list | dict | None = None,
        *,
        width: int | None = None,
        height: int | None = None,
        x_ticks: int = 5,
        y_ticks: int = 5,
        x_axis_range: tuple[int | float, int | float] | None = None,
        y_axis_range: tuple[int | float, int | float] | None = None,
        show_axis: bool = True,
        colors: bool | None = None,
        point_char: str = "●",
        show_labels: bool = False,
        series_name: str = "Points",
        legend: bool = True,
        legend_position: str = "bottom",
        legend_title: str | None = None,
        title: str | None = None,
        palette: list | None = None,
    ) -> None:
        if not isinstance(series_name, str):
            raise TypeError("series_name must be a string")
        if points is None:
            names, series, multi = [series_name], [[]], False
        elif isinstance(points, dict):
            names = list(points)
            if not all(isinstance(n, str) for n in names):
                raise TypeError("Series names must be strings")
            series = [_check_points(points[n], f"Points for series {n!r}") for n in names]
            multi = len(names) > 1
            if not names:
                names, series = [series_name], [[]]
        elif isinstance(points, list):
            names, series, multi = [series_name], [_check_points(points)], False
        else:
            raise TypeError("Points must be a list, a dict of lists, or None")

        if point_labels is None:
            labels = [[""] * len(s) for s in series]
        elif isinstance(point_labels, dict):
            labels = [check_labels(point_labels.get(n), len(s), "Point labels")
                      for n, s in zip(names, series)]
        else:
            if multi:
                raise TypeError("point_labels must be a dict when points is a dict")
            labels = [check_labels(point_labels, len(series[0]), "Point labels")]

        for name, value in (("width", width), ("height", height),
                            ("x_ticks", x_ticks), ("y_ticks", y_ticks)):
            check_int(name, value, none_ok=True)
        if width is not None and width < 10:
            raise ValueError("Width must be at least 10")
        if height is not None and height < 3:
            raise ValueError("Height must be at least 3")
        if x_ticks < 2 or y_ticks < 2:
            raise ValueError("Each axis must have at least two ticks")
        check_bool("show_axis", show_axis)
        check_bool("show_labels", show_labels)
        check_colors_flag(colors)
        check_char("point_char", point_char)
        check_legend(legend, legend_position, legend_title)
        if title is not None and not isinstance(title, str):
            raise TypeError("title must be a string or None")

        self.series_names, self.series_points, self.series_labels = names, series, labels
        self.multi = multi
        self.x_axis_range = check_range(x_axis_range, "x_axis_range")
        self.y_axis_range = check_range(y_axis_range, "y_axis_range")
        every = [p for s in series for p in s]
        check_covers(self.x_axis_range, [p[0] for p in every], "x_axis_range")
        check_covers(self.y_axis_range, [p[1] for p in every], "y_axis_range")
        self.width, self.height = width, height
        self.x_ticks, self.y_ticks = x_ticks, y_ticks
        self.show_axis = show_axis
        self.show_labels = show_labels
        self.ansi = resolve_colors(colors)
        self.color_by_point = colors is True and not multi
        self.point_char = point_char
        self.palette = check_palette(palette)
        self.legend, self.legend_position, self.legend_title = legend, legend_position, legend_title
        self.title = title

    # ----- data -----------------------------------------------------------

    @property
    def points(self):
        if self.multi:
            return dict(zip(self.series_names, self.series_points))
        return self.series_points[0]

    @property
    def labels(self):
        return self.series_labels[0] if not self.multi else dict(zip(self.series_names, self.series_labels))

    def is_empty(self) -> bool:
        return not any(self.series_points)

    def axes(self, series: list[int] | None = None, x_target=None, y_target=None):
        """Return ``((x_low, x_high, x_ticks), (y_low, y_high, y_ticks))``."""
        series = range(len(self.series_points)) if series is None else series
        pts = [p for s in series for p in self.series_points[s]]
        result = []
        for index, user, target in (
            (0, self.x_axis_range, x_target or self.x_ticks),
            (1, self.y_axis_range, y_target or self.y_ticks),
        ):
            if user is not None:
                result.append(nice_ticks(*user, target, expand=False))
            else:
                result.append(nice_ticks(*data_range([p[index] for p in pts]), target))
        return tuple(result)

    def _color(self, s: int, i: int) -> str:
        return self.palette[(i if self.color_by_point else s) % len(self.palette)]

    def _marker(self, s: int, i: int = 0) -> str:
        if self.color_by_point:
            return self.point_char
        if s == 0 and (self.point_char != "●" or not self.multi):
            return self.point_char
        return MARKERS[s % len(MARKERS)]

    def legend_entries(self) -> list[LegendEntry]:
        if self.color_by_point:
            return [
                LegendEntry(("p", i), self.series_labels[0][i] or f"Point {i + 1}",
                            self._color(0, i), self.point_char, "circle")
                for i in range(len(self.series_points[0]))
            ]
        return [
            LegendEntry(("s", s), name, self._color(s, 0), self._marker(s), "circle")
            for s, name in enumerate(self.series_names)
        ]

    def _legend(self) -> Legend:
        return Legend(self.legend_entries(), self.legend_position, self.legend_title, self.legend)

    # ----- text rendering -------------------------------------------------

    def __str__(self) -> str:
        if self.is_empty():
            return "(Empty ScatterPlot)"
        term = terminal_size()
        total = self.width or term.columns
        legend = self._legend()
        height = self.height or max(
            3, term.lines - 4 - legend.height(total) - (1 if self.title else 0)
        )
        (x_low, x_high, x_ticks), (y_low, y_high, y_ticks) = self.axes(
            y_target=min(self.y_ticks, max(2, (height + 1) // 2)))
        labels = {}
        row_of = lambda y: round((y_high - y) / (y_high - y_low) * (height - 1))
        for tick in y_ticks:
            labels.setdefault(row_of(tick), fmt_tick(tick))
        y_width = max(len(text) for text in labels.values())
        plot_w = max(1, total - legend.reserve_width(total) - y_width - 3)
        col_of = lambda x: round((x - x_low) / (x_high - x_low) * (plot_w - 1))
        grid = Grid(plot_w, height)
        if self.show_axis:
            if x_low <= 0 <= x_high:
                axis_col = col_of(0)
            else:
                axis_col = 0 if x_low > 0 else plot_w - 1
            if y_low <= 0 <= y_high:
                axis_row = row_of(0)
            else:
                axis_row = height - 1 if y_low > 0 else 0
            grid.vline(axis_col, 0, height - 1, "│")
            grid.hline(axis_row, 0, plot_w - 1, "─")
            grid.put(axis_col, axis_row, "┼")
        free = {" ", "│", "─", "┼", "·"}
        for s, points in enumerate(self.series_points):
            for i, (x, y) in enumerate(points):
                col, row = col_of(x), row_of(y)
                char = self._marker(s, i)
                if grid.get(col, row) not in free:
                    char, color = "*", None
                else:
                    color = self._color(s, i)
                grid.put(col, row, char, color)
        if self.show_labels:
            for s, points in enumerate(self.series_points):
                for i, (x, y) in enumerate(points):
                    text = self.series_labels[s][i]
                    col, row = col_of(x) + 2, row_of(y)
                    if text and col + len(text) <= plot_w and all(
                        grid.get(col + k, row) in free for k in range(len(text))
                    ):
                        grid.text(col, row, text)
        lines = []
        for r, line in enumerate(grid.rows(self.ansi)):
            lines.append(labels.get(r, "").rjust(y_width) + " │ " + line)
        lines.append(" " * (y_width + 3) + label_row(
            plot_w, [(col_of(t), fmt_tick(t)) for t in x_ticks]))
        return assemble(lines, legend, total, self.ansi, self.title)


class ScatterPlotGUI(ChartGUI):
    """Interactive scatter plot: hover a point for its coordinates, click the
    legend to hide or isolate series."""

    def __init__(
        self,
        points: list | dict | None = None,
        point_labels: list | dict | None = None,
        *,
        master=None,
        title: str = "Scatter Plot",
        width: int = 800,
        height: int = 500,
        x_ticks: int = 5,
        y_ticks: int = 5,
        x_axis_range: tuple[int | float, int | float] | None = None,
        y_axis_range: tuple[int | float, int | float] | None = None,
        show_axis: bool = True,
        colors: bool = False,
        point_color: str = "#4e79a7",
        background: str | None = None,
        point_size: int = 5,
        show_labels: bool = True,
        series_name: str = "Points",
        legend: bool = True,
        legend_position: str = "right",
        legend_title: str | None = None,
        chart_title: str | None = None,
        palette: list | None = None,
        theme: str = "light",
        tooltips: bool = True,
    ) -> None:
        check_bool("colors", colors)
        check_bool("show_labels", show_labels)
        check_int("point_size", point_size, 1)
        colours = list(check_palette(palette))
        colours[0] = point_color
        chart = ScatterPlot(
            points, point_labels, x_ticks=x_ticks, y_ticks=y_ticks,
            x_axis_range=x_axis_range, y_axis_range=y_axis_range,
            show_axis=show_axis, colors=colors, series_name=series_name,
            legend=legend, legend_position=legend_position,
            legend_title=legend_title, title=chart_title, palette=colours,
        )
        self.point_size = point_size
        self.show_labels = show_labels
        super().__init__(chart, master=master, title=title, width=width, height=height,
                         theme=theme, background=background, tooltips=tooltips)

    def _shown(self, s: int, i: int) -> bool:
        key = ("p", i) if self.chart.color_by_point else ("s", s)
        return self.visible(key)

    def render(self, box) -> None:
        chart, canvas, theme = self.chart, self.canvas, self.theme
        shown = [s for s in range(len(chart.series_points))
                 if chart.color_by_point or self.visible(("s", s))]
        (x_low, x_high, x_ticks), (y_low, y_high, y_ticks) = chart.axes(shown)
        plot = self.plot_box(box, y_ticks, bottom=30)
        left, top, right, bottom = plot
        x_for = lambda v: left + (v - x_low) / (x_high - x_low) * (right - left)
        y_for = lambda v: bottom - (v - y_low) / (y_high - y_low) * (bottom - top)
        self.draw_y_grid(plot, y_ticks, y_for)
        self.draw_x_grid(plot, x_ticks, x_for)
        if chart.show_axis:
            ax = x_for(0) if x_low <= 0 <= x_high else (left if x_low > 0 else right)
            ay = y_for(0) if y_low <= 0 <= y_high else (bottom if y_low > 0 else top)
            canvas.create_line(ax, top, ax, bottom, fill=theme["axis"], width=2)
            canvas.create_line(left, ay, right, ay, fill=theme["axis"], width=2)
        r = self.point_size
        for s in shown:
            for i, (x, y) in enumerate(chart.series_points[s]):
                if not self._shown(s, i):
                    continue
                px, py = x_for(x), y_for(y)
                color = chart._color(s, i)
                canvas.create_oval(px - r, py - r, px + r, py + r, fill=color, outline=theme["bg"])
                label = chart.series_labels[s][i]
                if label and self.show_labels:
                    canvas.create_text(px + r + 3, py - r - 2, text=label, anchor="sw",
                                       fill=theme["fg"], font=self.font_small)
                rows = [(label or f"Point {i + 1}", None, "bold")]
                if chart.multi:
                    rows.append((chart.series_names[s], color, None))
                rows.append((f"x: {fmt_num(x)}", None, None))
                rows.append((f"y: {fmt_num(y)}", None, None))
                self.hit_circle(px, py, r, rows)


if __name__ == "__main__":
    points = [(1, 2), (2, 5), (3, 3), (4, 8), (5, 6)]
    print(ScatterPlot(points, ["A", "B", "C", "D", "E"], show_labels=True))
    groups = {"Control": [(1, 2), (2, 3), (3, 3.5)], "Treated": [(1, 3), (2, 5), (3, 8)]}
    print(ScatterPlot(groups))
    ScatterPlotGUI(groups).run()
