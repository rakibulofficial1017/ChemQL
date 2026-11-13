"""Box-and-whisker plots."""

from __future__ import annotations

from dataclasses import dataclass

from .common import (
    ChartGUI, Grid, Legend, LegendEntry, assemble, check_colors_flag, check_covers,
    check_int, check_labels, check_legend, check_numbers, check_palette, check_range,
    fmt_num, fmt_tick, label_row, mix, nice_ticks, resolve_colors, terminal_size, truncate,
)


@dataclass(frozen=True)
class BoxStats:
    n: int
    minimum: float
    q1: float
    median: float
    q3: float
    maximum: float
    mean: float
    whisker_low: float
    whisker_high: float
    outliers: tuple

    @property
    def iqr(self) -> float:
        return self.q3 - self.q1


def _quantile(values: list, q: float) -> float:
    pos = (len(values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def describe(values: list, whisker: float = 1.5) -> BoxStats:
    ordered = sorted(values)
    q1, median, q3 = (_quantile(ordered, q) for q in (0.25, 0.5, 0.75))
    iqr = q3 - q1
    fence_low, fence_high = q1 - whisker * iqr, q3 + whisker * iqr
    inside = [v for v in ordered if fence_low <= v <= fence_high]
    return BoxStats(
        len(ordered), ordered[0], q1, median, q3, ordered[-1], sum(ordered) / len(ordered),
        inside[0], inside[-1], tuple(v for v in ordered if not fence_low <= v <= fence_high),
    )


class BoxPlot:
    """``data`` is ``{name: [numbers]}`` or a list of lists (with ``category_labels``)."""

    def __init__(
        self,
        data: list | dict | None = None,
        category_labels: list | None = None,
        *,
        height: int | None = None,
        width: int | None = None,
        box_width: int = 7,
        spacing: int = 2,
        y_ticks: int = 5,
        y_axis_range: tuple[int | float, int | float] | None = None,
        whisker: float = 1.5,
        colors: bool | None = None,
        legend: bool = True,
        legend_position: str = "bottom",
        legend_title: str | None = None,
        title: str | None = None,
        palette: list | None = None,
    ) -> None:
        if isinstance(data, dict):
            if category_labels is not None:
                raise TypeError("Pass either a dict or category_labels, not both")
            category_labels, groups = list(data), list(data.values())
        elif data is None:
            groups = []
        elif isinstance(data, list):
            groups = data
        else:
            raise TypeError("data must be a dict of lists, a list of lists, or None")
        groups = [check_numbers(g, "Box plot values") for g in groups]
        if any(not g for g in groups):
            raise ValueError("Each box plot group needs at least one value")
        self.categories = check_labels(category_labels, len(groups))
        for name, value in (("height", height), ("width", width), ("box_width", box_width),
                            ("spacing", spacing), ("y_ticks", y_ticks)):
            check_int(name, value, none_ok=True)
        if height is not None and height < 3:
            raise ValueError("Height must be at least 3")
        if box_width < 3 or spacing < 0 or y_ticks < 2:
            raise ValueError("box_width must be at least 3, spacing nonnegative, y_ticks at least 2")
        if not isinstance(whisker, (int, float)) or isinstance(whisker, bool) or whisker < 0:
            raise ValueError("whisker must be a non-negative number")
        check_colors_flag(colors)
        check_legend(legend, legend_position, legend_title)
        if title is not None and not isinstance(title, str):
            raise TypeError("title must be a string or None")
        self.groups = groups
        self.stats = [describe(g, whisker) for g in groups]
        self.y_axis_range = check_range(y_axis_range, "y_axis_range")
        check_covers(self.y_axis_range, [v for g in groups for v in g], "y_axis_range")
        self.height, self.width = height, width
        self.box_width, self.spacing, self.y_ticks = box_width | 1, spacing, y_ticks
        self.whisker = whisker
        self.ansi = resolve_colors(colors)
        self.palette = check_palette(palette)
        self.legend, self.legend_position, self.legend_title = legend, legend_position, legend_title
        self.title = title

    @property
    def data(self) -> list:
        return self.groups

    def is_empty(self) -> bool:
        return not self.groups

    def name(self, i: int) -> str:
        return self.categories[i] or f"Group {i + 1}"

    def color(self, i: int) -> str:
        return self.palette[i % len(self.palette)]

    def axis(self, visible=None, target: int | None = None):
        target = target or self.y_ticks
        if self.y_axis_range is not None:
            return nice_ticks(*self.y_axis_range, target, expand=False)
        values = [v for i, g in enumerate(self.groups) if visible is None or visible(i) for v in g]
        if not values:
            return nice_ticks(0.0, 1.0, target)
        low, high = min(values), max(values)
        if low == high:
            low, high = low - 1, high + 1
        return nice_ticks(low, high, target, expand=False)

    def legend_entries(self) -> list[LegendEntry]:
        entries = [LegendEntry(("c", i), self.name(i), self.color(i), "□")
                   for i in range(len(self.groups))]
        entries.append(LegendEntry(None, "Median", "#777777", "═", "dash"))
        if any(s.outliers for s in self.stats):
            entries.append(LegendEntry(None, "Outlier", "#777777", "○", "ring"))
        return entries

    def _legend(self) -> Legend:
        return Legend(self.legend_entries(), self.legend_position, self.legend_title, self.legend)

    def __str__(self) -> str:
        if self.is_empty():
            return "(Empty BoxPlot)"
        term = terminal_size()
        total = self.width or term.columns
        legend = self._legend()
        height = self.height or max(
            4, term.lines - 6 - legend.height(total) - (1 if self.title else 0)
        )
        low, high, ticks = self.axis(target=min(self.y_ticks, max(2, (height + 1) // 2)))
        row_of = lambda v: round((high - v) / (high - low) * (height - 1))
        labels = {}
        for tick in ticks:
            labels.setdefault(row_of(tick), fmt_tick(tick))
        y_width = max(len(t) for t in labels.values())
        avail = total - legend.reserve_width(total) - y_width - 3
        count = len(self.groups)
        cats = [self.name(i) for i in range(count)]
        bw, spacing = self.box_width, self.spacing
        while True:
            widths = [max(bw, len(c)) for c in cats]
            if sum(widths) + spacing * (count - 1) <= avail:
                break
            if bw > 3:
                bw -= 2
            elif spacing > 1:
                spacing -= 1
            else:
                budget = (avail - spacing * (count - 1)) // count
                if budget < 3:
                    raise ValueError("Chart width is too small to fit all boxes")
                cats = [truncate(c, budget) for c in cats]
                widths = [max(3, len(c)) for c in cats]
                bw = 3
                break
        grid = Grid(sum(widths) + spacing * (count - 1), height)
        x = 0
        for i, stats in enumerate(self.stats):
            x0 = x + (widths[i] - bw) // 2
            self._draw_box(grid, x0, bw, stats, row_of, self.color(i))
            x += widths[i] + spacing
        lines = [labels.get(r, "").rjust(y_width) + " │ " + line
                 for r, line in enumerate(grid.rows(self.ansi))]
        label_line, x = [], 0
        for text, w in zip(cats, widths):
            label_line.append((x + w // 2, text))
            x += w + spacing
        lines.append(" " * (y_width + 3) + label_row(grid.width, label_line))
        return assemble(lines, legend, total, self.ansi, self.title)

    @staticmethod
    def _draw_box(grid, x0, bw, s, row_of, color) -> None:
        xc = x0 + bw // 2
        r_wh, r_q3, r_med = row_of(s.whisker_high), row_of(s.q3), row_of(s.median)
        r_q1, r_wl = row_of(s.q1), row_of(s.whisker_low)
        median_at_q3 = r_med == r_q3
        median_at_q1 = r_med == r_q1
        if r_wh < r_q3:
            grid.vline(xc, r_wh, r_q3, "│", color)
            grid.hline(r_wh, xc - 1, xc + 1, "─", color)
            grid.put(xc, r_wh, "┬", color)
        if r_wl > r_q1:
            grid.vline(xc, r_q1, r_wl, "│", color)
            grid.hline(r_wl, xc - 1, xc + 1, "─", color)
            grid.put(xc, r_wl, "┴", color)
        grid.hline(r_q3, x0, x0 + bw - 1, "═" if median_at_q3 else "─", color)
        grid.hline(r_q1, x0, x0 + bw - 1, "═" if median_at_q1 else "─", color)
        for r in range(r_q3, r_q1 + 1):
            if r == r_q3:
                left, right = ("╒", "╕") if median_at_q3 else ("┌", "┐")
            elif r == r_q1:
                left, right = ("╘", "╛") if median_at_q1 else ("└", "┘")
            else:
                left, right = "│", "│"
            grid.put(x0, r, left, color)
            grid.put(x0 + bw - 1, r, right, color)
        if r_wh < r_q3:
            grid.put(xc, r_q3, "╧" if median_at_q3 else "┴", color)
        if r_wl > r_q1:
            grid.put(xc, r_q1, "╤" if median_at_q1 else "┬", color)
        if not median_at_q3 and not median_at_q1:
            grid.put(x0, r_med, "╞", color)
            grid.put(x0 + bw - 1, r_med, "╡", color)
            for x in range(x0 + 1, x0 + bw - 1):
                grid.put(x, r_med, "═", color)
        for v in s.outliers:
            grid.put(xc, row_of(v), "○", color)


class BoxPlotGUI(ChartGUI):
    """Interactive box plot: hover a box for its five-number summary, an
    outlier for its value; click the legend to hide or isolate groups."""

    def __init__(
        self,
        data: list | dict | None = None,
        category_labels: list | None = None,
        *,
        master=None,
        title: str = "Box Plot",
        width: int = 800,
        height: int = 500,
        y_ticks: int = 5,
        y_axis_range: tuple[int | float, int | float] | None = None,
        whisker: float = 1.5,
        background: str | None = None,
        legend: bool = True,
        legend_position: str = "right",
        legend_title: str | None = None,
        chart_title: str | None = None,
        palette: list | None = None,
        theme: str = "light",
        tooltips: bool = True,
    ) -> None:
        chart = BoxPlot(
            data, category_labels, y_ticks=y_ticks, y_axis_range=y_axis_range,
            whisker=whisker, legend=legend, legend_position=legend_position,
            legend_title=legend_title, title=chart_title, palette=palette,
        )
        super().__init__(chart, master=master, title=title, width=width, height=height,
                         theme=theme, background=background, tooltips=tooltips)

    def render(self, box) -> None:
        chart, canvas, theme = self.chart, self.canvas, self.theme
        low, high, ticks = chart.axis(lambda i: self.visible(("c", i)))
        plot = self.plot_box(box, ticks, bottom=30)
        left, top, right, bottom = plot
        y_for = lambda v: bottom - (v - low) / (high - low) * (bottom - top)
        self.draw_y_grid(plot, ticks, y_for)
        count = len(chart.groups)
        slot = (right - left) / count
        half = min(slot * 0.3, 55)
        centres = [left + slot * (i + 0.5) for i in range(count)]
        for i, s in enumerate(chart.stats):
            if not self.visible(("c", i)):
                continue
            cx, color = centres[i], chart.color(i)
            canvas.create_line(cx, y_for(s.whisker_high), cx, y_for(s.whisker_low),
                               fill=color, width=2)
            for w in (s.whisker_high, s.whisker_low):
                canvas.create_line(cx - half / 2, y_for(w), cx + half / 2, y_for(w),
                                   fill=color, width=2)
            top_y, bot_y = y_for(s.q3), y_for(s.q1)
            canvas.create_rectangle(cx - half, top_y, cx + half, max(bot_y, top_y + 1),
                                    fill=mix(color, theme["bg"], 0.6), outline=color, width=2)
            canvas.create_line(cx - half, y_for(s.median), cx + half, y_for(s.median),
                               fill=theme["fg"], width=3)
            tip = [
                (f"{chart.name(i)}  (n={s.n})", color, "bold"),
                (f"Max: {fmt_num(s.maximum)}", None, None),
                (f"Q3: {fmt_num(s.q3)}", None, None),
                (f"Median: {fmt_num(s.median)}", None, "bold"),
                (f"Q1: {fmt_num(s.q1)}", None, None),
                (f"Min: {fmt_num(s.minimum)}", None, None),
                (f"Mean: {fmt_num(s.mean)}   IQR: {fmt_num(s.iqr)}", None, None),
            ]
            y1, y2 = y_for(s.whisker_high), y_for(s.whisker_low)
            self.add_hit(
                lambda x, y, a=cx - half, b=cx + half, c=y1, d=y2: a <= x <= b and c <= y <= d,
                tip, self.overlay_rect(cx - half - 3, y1 - 2, cx + half + 3, y2 + 2),
            )
            for v in s.outliers:
                oy = y_for(v)
                canvas.create_oval(cx - 4, oy - 4, cx + 4, oy + 4, outline=color, width=2)
                self.hit_circle(cx, oy, 4, [(chart.name(i), color, "bold"),
                                            (f"Outlier: {fmt_num(v)}", None, None)])
        self.draw_category_labels([chart.name(i) for i in range(count)], centres, slot, bottom + 8)


if __name__ == "__main__":
    data = {
        "Control": [12, 14, 15, 15, 16, 18, 19, 21, 24, 40],
        "Drug A": [15, 18, 19, 20, 22, 23, 25, 27, 30],
        "Drug B": [9, 11, 12, 14, 14, 15, 17, 18, 19],
    }
    print(BoxPlot(data, height=14))
    BoxPlotGUI(data).run()
