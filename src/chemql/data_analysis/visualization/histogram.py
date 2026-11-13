"""Histograms of raw data, with one or several series."""

from __future__ import annotations

import math
from bisect import bisect_right

from .common import (
    FILLS, ChartGUI, Grid, Legend, LegendEntry, assemble, check_bool,
    check_colors_flag, check_int, check_legend, check_palette, check_range,
    fmt_num, fmt_pct, fmt_tick, is_finite, is_number, label_row, nice_ticks,
    normalize_series, resolve_colors, terminal_size,
)


def _edges(bins, bin_range, pooled):
    if isinstance(bins, (list, tuple)):
        if len(bins) < 2 or not all(is_number(b) and is_finite(b) for b in bins):
            raise ValueError("bins must contain at least two finite edges")
        if any(b2 <= b1 for b1, b2 in zip(bins, bins[1:])):
            raise ValueError("bin edges must be strictly increasing")
        return [float(b) if isinstance(b, float) else b for b in bins]
    if bins == "auto":
        bins = min(30, max(5, math.ceil(math.sqrt(len(pooled)))))
    elif not isinstance(bins, int) or isinstance(bins, bool) or bins < 1:
        raise ValueError("bins must be 'auto', a positive integer, or a list of edges")
    if bin_range is not None:
        low, high = bin_range
    elif pooled:
        low, high = min(pooled), max(pooled)
    else:
        low, high = 0.0, 1.0
    if low == high:
        low, high = low - 0.5, high + 0.5
    return [low + (high - low) * i / bins for i in range(bins + 1)]


class Histogram:
    def __init__(
        self,
        data: list | dict | None = None,
        *,
        bins: int | str | list = "auto",
        bin_range: tuple[int | float, int | float] | None = None,
        density: bool = False,
        height: int | None = None,
        width: int | None = None,
        y_ticks: int = 5,
        colors: bool | None = None,
        series_name: str = "Count",
        legend: bool = True,
        legend_position: str = "bottom",
        legend_title: str | None = None,
        title: str | None = None,
        palette: list | None = None,
    ) -> None:
        names, columns, multi = normalize_series(data, series_name, "Histogram data")
        if density and series_name == "Count":
            names = ["Density"] if not multi else names
        check_bool("density", density)
        for name, value in (("height", height), ("width", width), ("y_ticks", y_ticks)):
            check_int(name, value, none_ok=True)
        if height is not None and height < 3:
            raise ValueError("Height must be at least 3")
        if y_ticks < 2:
            raise ValueError("y_ticks must be at least 2")
        check_colors_flag(colors)
        check_legend(legend, legend_position, legend_title)
        if title is not None and not isinstance(title, str):
            raise TypeError("title must be a string or None")
        bin_range = check_range(bin_range, "bin_range")
        pooled = [v for column in columns for v in column]
        self.edges = _edges(bins, bin_range, pooled)
        nb = len(self.edges) - 1
        self.counts = []
        self.sizes = []
        for column in columns:
            counts = [0] * nb
            kept = 0
            for v in column:
                if v < self.edges[0] or v > self.edges[-1]:
                    continue
                counts[min(nb - 1, bisect_right(self.edges, v) - 1)] += 1
                kept += 1
            self.counts.append(counts)
            self.sizes.append(kept)
        self.density = density
        self.series_names, self.multi = names, multi
        self.raw = columns
        self.height, self.width, self.y_ticks = height, width, y_ticks
        self.ansi = resolve_colors(colors)
        self.palette = check_palette(palette)
        self.legend, self.legend_position, self.legend_title = legend, legend_position, legend_title
        self.title = title

    def is_empty(self) -> bool:
        return not any(self.raw)

    @property
    def bins(self) -> int:
        return len(self.edges) - 1

    def heights(self, s: int) -> list[float]:
        if not self.density:
            return [float(c) for c in self.counts[s]]
        n = self.sizes[s] or 1
        return [c / (n * (self.edges[b + 1] - self.edges[b])) for b, c in enumerate(self.counts[s])]

    def bin_label(self, b: int) -> str:
        return f"[{self.edges[b]:.4g}, {self.edges[b + 1]:.4g}{']' if b == self.bins - 1 else ')'}"

    def axis(self, series: list[int] | None = None, target: int | None = None):
        series = range(len(self.counts)) if series is None else series
        top = max((max(self.heights(s)) for s in series), default=1.0)
        return nice_ticks(0.0, top or 1.0, target or self.y_ticks)

    def _glyph(self, s: int) -> str:
        return "█" if self.ansi else FILLS[s % len(FILLS)]

    def legend_entries(self) -> list[LegendEntry]:
        return [
            LegendEntry(("s", s), name, self.palette[s % len(self.palette)], self._glyph(s))
            for s, name in enumerate(self.series_names)
        ]

    def _legend(self) -> Legend:
        return Legend(self.legend_entries(), self.legend_position, self.legend_title, self.legend)

    def __str__(self) -> str:
        if self.is_empty():
            return "(Empty Histogram)"
        term = terminal_size()
        total = self.width or term.columns
        legend = self._legend()
        height = self.height or max(
            3, term.lines - 6 - legend.height(total) - (1 if self.title else 0)
        )
        low, high, ticks = self.axis(target=min(self.y_ticks, max(2, (height + 1) // 2)))
        span = high - low
        row_of = lambda v: round((high - v) / span * (height - 1))
        labels = {}
        for tick in ticks:
            labels.setdefault(row_of(tick), fmt_tick(tick))
        y_width = max(len(t) for t in labels.values())
        nb, per = self.bins, len(self.counts)
        avail = total - legend.reserve_width(total) - y_width - 3
        bin_w = max(per, avail // nb)
        if avail < nb * per:
            raise ValueError("Chart width is too small to fit all bins")
        gap = 1 if bin_w >= 3 * per else 0
        sub = max(1, (bin_w - gap) // per)
        grid = Grid(bin_w * nb, height)
        base = row_of(0)
        for s in range(per):
            heights = self.heights(s)
            color = self.palette[s % len(self.palette)]
            for b, value in enumerate(heights):
                if value <= 0:
                    continue
                x0 = b * bin_w + s * sub
                for r in range(max(0, row_of(value)), base + 1):
                    for dx in range(sub):
                        grid.put(x0 + dx, r, self._glyph(s), color)
        lines = [
            labels.get(r, "").rjust(y_width) + " │ " + line
            for r, line in enumerate(grid.rows(self.ansi))
        ]
        items = [(min(grid.width - 1, i * bin_w), f"{self.edges[i]:.4g}") for i in range(nb + 1)]
        lines.append(" " * (y_width + 3) + label_row(grid.width, items))
        return assemble(lines, legend, total, self.ansi, self.title)


class HistogramGUI(ChartGUI):
    """Interactive histogram: hover a bin for counts per series, click the
    legend to hide or isolate series."""

    def __init__(
        self,
        data: list | dict | None = None,
        *,
        master=None,
        title: str = "Histogram",
        width: int = 800,
        height: int = 500,
        bins: int | str | list = "auto",
        bin_range: tuple[int | float, int | float] | None = None,
        density: bool = False,
        y_ticks: int = 5,
        background: str | None = None,
        series_name: str = "Count",
        legend: bool = True,
        legend_position: str = "right",
        legend_title: str | None = None,
        chart_title: str | None = None,
        palette: list | None = None,
        theme: str = "light",
        tooltips: bool = True,
    ) -> None:
        chart = Histogram(
            data, bins=bins, bin_range=bin_range, density=density, y_ticks=y_ticks,
            series_name=series_name, legend=legend, legend_position=legend_position,
            legend_title=legend_title, title=chart_title, palette=palette,
        )
        super().__init__(chart, master=master, title=title, width=width, height=height,
                         theme=theme, background=background, tooltips=tooltips)

    def render(self, box) -> None:
        chart, canvas, theme = self.chart, self.canvas, self.theme
        series = [s for s in range(len(chart.counts)) if self.visible(("s", s))]
        low, high, ticks = chart.axis(series)
        plot = self.plot_box(box, ticks, bottom=30)
        left, top, right, bottom = plot
        y_for = lambda v: bottom - (v - low) / (high - low) * (bottom - top)
        self.draw_y_grid(plot, ticks, y_for)
        canvas.create_line(left, bottom, right, bottom, fill=theme["axis"], width=2)
        e0, e1 = chart.edges[0], chart.edges[-1]
        x_for = lambda v: left + (v - e0) / (e1 - e0) * (right - left)
        nb = chart.bins
        for b in range(nb):
            xa, xb = x_for(chart.edges[b]), x_for(chart.edges[b + 1])
            inset = 1 if xb - xa > 4 else 0
            sub = (xb - xa - 2 * inset) / max(1, len(series))
            for k, s in enumerate(series):
                value = chart.heights(s)[b]
                if value <= 0:
                    continue
                color = chart.palette[s % len(chart.palette)]
                canvas.create_rectangle(xa + inset + k * sub, y_for(value),
                                        xa + inset + (k + 1) * sub, bottom,
                                        fill=color, outline=theme["bg"])
            rows = [(chart.bin_label(b), None, "bold")]
            for s in series:
                count = chart.counts[s][b]
                share = count / chart.sizes[s] if chart.sizes[s] else 0
                text = f"{chart.series_names[s]}: {fmt_num(count)} ({fmt_pct(share)})"
                if chart.density:
                    text += f", density {chart.heights(s)[b]:.4g}"
                rows.append((text, chart.palette[s % len(chart.palette)], None))
            ymax = min(
                [y_for(chart.heights(s)[b]) for s in series if chart.heights(s)[b] > 0] or [bottom - 1]
            )
            self.add_hit(
                lambda x, y, a=xa, c=xb: a <= x <= c and top <= y <= bottom, rows,
                self.overlay_rect(xa, ymax, xb, bottom),
            )
        stride = max(1, math.ceil((max(self.measure(f"{e:.4g}") for e in chart.edges) + 10)
                                  / max((right - left) / nb, 1)))
        for i in range(0, nb + 1, stride):
            x = x_for(chart.edges[i])
            canvas.create_line(x, bottom, x, bottom + 4, fill=theme["axis"])
            canvas.create_text(x, bottom + 6, text=f"{chart.edges[i]:.4g}", anchor="n",
                               fill=theme["muted"], font=self.font)


if __name__ == "__main__":
    import random
    random.seed(1)
    a = [random.gauss(50, 10) for _ in range(300)]
    b = [random.gauss(65, 8) for _ in range(300)]
    print(Histogram({"Group A": a, "Group B": b}, bins=12, height=12))
    HistogramGUI({"Group A": a, "Group B": b}, bins=15).run()
