"""Bar charts: vertical or horizontal, single, grouped or stacked.

``data`` is either a list of numbers (one series) or ``{name: [numbers]}``
(several series, drawn grouped or stacked).
"""

from __future__ import annotations

from .common import (
    FILLS, PALETTE, ChartGUI, Grid, Legend, LegendEntry, assemble, check_bool,
    check_char, check_choice, check_colors_flag, check_covers, check_hex,
    check_int, check_labels, check_legend, check_palette, check_range,
    contrast_text, fmt_num, fmt_pct, fmt_tick, label_row, nice_ticks,
    normalize_series, resolve_colors, terminal_size, truncate,
)


class BarChart:
    def __init__(
        self,
        data: list | dict | None = None,
        category_labels: list | None = None,
        *,
        height: int | None = None,
        width: int | None = None,
        bar_width: int = 3,
        spacing: int = 2,
        show_values: bool = True,
        show_axis: bool = True,
        show_y_axis: bool = True,
        y_ticks: int = 5,
        y_axis_range: tuple[int | float, int | float] | None = None,
        horizontal: bool = False,
        colors: bool | None = None,
        bar_char: str = "█",
        negative_char: str | None = None,
        axis_char: str = "─",
        sort: str | None = None,
        show_values_on_bar: bool = False,
        mode: str = "grouped",
        series_name: str = "Value",
        legend: bool = True,
        legend_position: str = "bottom",
        legend_title: str | None = None,
        title: str | None = None,
        palette: list | None = None,
        positive_color: str | None = None,
        negative_color: str | None = None,
    ) -> None:
        names, columns, multi = normalize_series(data, series_name)
        count = len(columns[0])
        categories = check_labels(category_labels, count)
        for name, value in (
            ("height", height), ("width", width), ("bar_width", bar_width),
            ("spacing", spacing), ("y_ticks", y_ticks),
        ):
            check_int(name, value, none_ok=True)
        if height is not None and height < 3:
            raise ValueError("Height must be at least 3")
        if width is not None and width < 1:
            raise ValueError("Width must be positive")
        if bar_width < 1 or spacing < 0 or y_ticks < 2:
            raise ValueError("Invalid chart dimensions")
        for name, value in (
            ("show_values", show_values), ("show_axis", show_axis),
            ("show_y_axis", show_y_axis), ("horizontal", horizontal),
            ("show_values_on_bar", show_values_on_bar),
        ):
            check_bool(name, value)
        check_colors_flag(colors)
        check_choice("mode", mode, ("grouped", "stacked"))
        if sort is not None:
            check_choice("sort", sort, ("ascending", "descending"))
        check_char("bar_char", bar_char)
        check_char("axis_char", axis_char)
        if negative_char is not None:
            check_char("negative_char", negative_char)
        check_legend(legend, legend_position, legend_title)
        if title is not None and not isinstance(title, str):
            raise TypeError("title must be a string or None")

        if sort is not None:
            if multi:
                keys = [sum(column[i] for column in columns) for i in range(count)]
            else:
                keys = columns[0]
            order = sorted(range(count), key=lambda i: keys[i], reverse=sort == "descending")
            columns = [[column[i] for i in order] for column in columns]
            categories = [categories[i] for i in order]

        self.series_names = names
        self.series_values = columns
        self.categories = categories
        self.multi = multi
        self.mode = mode
        self.y_axis_range = check_range(y_axis_range, "y_axis_range")
        self._check_range_covers()
        self.height, self.width = height, width
        self.bar_width, self.spacing = bar_width, spacing
        self.show_values, self.show_values_on_bar = show_values, show_values_on_bar
        self.show_axis, self.show_y_axis = show_axis, show_y_axis
        self.y_ticks = y_ticks
        self.horizontal = horizontal
        self.sort = sort
        self.bar_char = bar_char
        self.negative_char = bar_char if negative_char is None else negative_char
        self.axis_char = axis_char
        self.ansi = resolve_colors(colors)
        self.color_by_category = colors is True and not multi
        self.palette = check_palette(palette)
        self.positive_color = check_hex("positive_color", positive_color) if positive_color else self.palette[0]
        self.negative_color = check_hex("negative_color", negative_color) if negative_color else PALETTE[2]
        self.legend, self.legend_position, self.legend_title = legend, legend_position, legend_title
        self.title = title

    # ----- data helpers ---------------------------------------------------

    @property
    def data(self):
        if self.multi:
            return dict(zip(self.series_names, self.series_values))
        return self.series_values[0]

    @property
    def stacked(self) -> bool:
        return self.multi and self.mode == "stacked"

    def is_empty(self) -> bool:
        return not self.categories

    def __repr__(self) -> str:
        return f"BarChart(data={self.data}, category_labels={self.categories})"

    def _check_range_covers(self) -> None:
        if self.y_axis_range is None or not self.categories:
            return
        lo, hi = self._extent(lambda s, c, v: True, include_zero=False)
        check_covers(self.y_axis_range, [lo, hi], "y_axis_range")

    def _extent(self, visible, include_zero: bool = True) -> tuple[float, float]:
        lows, highs = [], []
        for c in range(len(self.categories)):
            if self.stacked:
                pos = neg = 0.0
                seen = False
                for s, column in enumerate(self.series_values):
                    if visible(s, c, column[c]):
                        seen = True
                        if column[c] > 0:
                            pos += column[c]
                        else:
                            neg += column[c]
                if seen:
                    highs.append(pos)
                    lows.append(neg)
            else:
                for s, column in enumerate(self.series_values):
                    if visible(s, c, column[c]):
                        highs.append(column[c])
                        lows.append(column[c])
        if include_zero:
            lows.append(0.0)
            highs.append(0.0)
        if not lows:
            return 0.0, 1.0
        return min(lows), max(highs)

    def axis(self, visible=None, target: int | None = None) -> tuple[float, float, list[float]]:
        """Effective (low, high, ticks) for the value axis."""
        target = target or self.y_ticks
        if self.y_axis_range is not None:
            low, high = self.y_axis_range
            return nice_ticks(low, high, target, expand=False)
        low, high = self._extent(visible or (lambda s, c, v: True))
        if low == high:
            low, high = 0.0, 1.0
        return nice_ticks(low, high, target)

    # ----- colour / key per bar (shared by text and GUI renderers) ----------

    def _key(self, s: int, c: int, v: float):
        if self.multi:
            return ("s", s)
        if self.color_by_category:
            return ("c", c)
        return "pos" if v >= 0 else "neg"

    def _color(self, s: int, c: int, v: float) -> str:
        if self.multi:
            return self.palette[s % len(self.palette)]
        if self.color_by_category:
            return self.palette[c % len(self.palette)]
        return self.positive_color if v >= 0 else self.negative_color

    def _glyph(self, s: int, v: float) -> str:
        if self.multi:
            return self.bar_char if self.ansi else FILLS[s % len(FILLS)]
        return self.bar_char if v >= 0 else self.negative_char

    def _label(self, index: int) -> str:
        label = self.categories[index]
        if self.show_values and not self.multi:
            return f"{label} ({self.series_values[0][index]:g})"
        if self.show_values and self.stacked:
            return f"{label} ({sum(c[index] for c in self.series_values):g})"
        return label

    def legend_entries(self) -> list[LegendEntry]:
        pal = self.palette
        if self.multi:
            return [
                LegendEntry(("s", i), name, pal[i % len(pal)], self._glyph(i, 1))
                for i, name in enumerate(self.series_names)
            ]
        if self.color_by_category:
            return [
                LegendEntry(("c", c), cat or f"#{c + 1}", pal[c % len(pal)], self.bar_char)
                for c, cat in enumerate(self.categories)
            ]
        name = self.series_names[0]
        if any(v < 0 for v in self.series_values[0]):
            return [
                LegendEntry("pos", f"{name} ≥ 0", self.positive_color, self.bar_char),
                LegendEntry("neg", f"{name} < 0", self.negative_color, self.negative_char),
            ]
        return [LegendEntry("pos", name, self.positive_color, self.bar_char)]

    def _legend(self) -> Legend:
        return Legend(self.legend_entries(), self.legend_position, self.legend_title, self.legend)

    # ----- text rendering -------------------------------------------------

    def _value_text(self, c: int, k: int) -> str:
        if self.stacked:
            return f"{sum(column[c] for column in self.series_values):g}"
        return f"{self.series_values[k][c]:g}"

    def __str__(self) -> str:
        if self.is_empty():
            return "(Empty BarChart)"
        return self._horizontal() if self.horizontal else self._vertical()

    def _vertical(self) -> str:
        term = terminal_size()
        total = self.width or term.columns
        legend = self._legend()
        height = self.height or max(
            3, term.lines - 7 - legend.height(total) - (1 if self.title else 0)
        )
        low, high, ticks = self.axis(target=min(self.y_ticks, max(2, (height + 1) // 2)))
        span = high - low
        base_val = min(max(0.0, low), high)
        row_of = lambda v: round((high - v) / span * (height - 1))
        base = row_of(base_val)
        if low < 0 < high:
            base = max(1, min(height - 2, base))
        labels: dict[int, str] = {}
        for tick in ticks:
            labels.setdefault(base if tick == base_val else row_of(tick), fmt_tick(tick))
        y_width = max(len(text) for text in labels.values())
        prefix_w = y_width + 3 if self.show_y_axis else 0
        avail = total - legend.reserve_width(total) - prefix_w

        count = len(self.categories)
        per = len(self.series_values) if (self.multi and not self.stacked) else 1
        cats = [self._label(c) for c in range(count)]
        spacing = self.spacing

        def cells(bw: int, c: int) -> list[int]:
            if not self.show_values_on_bar:
                return [bw] * per
            return [max(bw, len(self._value_text(c, k))) for k in range(per)]

        bw = self.bar_width
        while True:
            gaps = spacing * (count - 1)
            widths = [max(sum(cells(bw, c)), len(cats[c])) for c in range(count)]
            if sum(widths) + gaps <= avail:
                break
            if bw > 1:
                bw -= 1
                continue
            if spacing > 1:
                spacing -= 1
                continue
            budget = (avail - gaps) // count
            if budget < per:
                raise ValueError("Chart width is too small to fit all bars and spacing")
            cats = [truncate(text, budget) for text in cats]
            widths = [max(sum(cells(1, c)), len(cats[c])) for c in range(count)]
            if sum(widths) + gaps > avail:
                raise ValueError("Chart width is too small to fit all category and value labels")
            break

        grid = Grid(sum(widths) + gaps, height)
        if self.show_axis:
            grid.hline(base, 0, grid.width - 1, self.axis_char)
        x = 0
        for c in range(count):
            cell_list = cells(bw, c)
            cx = x + (widths[c] - sum(cell_list)) // 2
            if self.stacked:
                self._stack_v(grid, c, cx + (cell_list[0] - bw) // 2, bw, base, row_of)
                top = self._stack_top(c, row_of)
                if self.show_values_on_bar:
                    self._label_v(grid, cx, cell_list[0], self._value_text(c, 0), top,
                                  True, base, height, None)
            else:
                for k in range(per):
                    s = k if per > 1 else 0
                    v = self.series_values[s][c]
                    rows = self._bar_rows(v, base_val, base, row_of, height)
                    color = self._color(s, c, v)
                    for r in rows:
                        for dx in range(bw):
                            grid.put(cx + (cell_list[k] - bw) // 2 + dx, r, self._glyph(s, v), color)
                    if self.show_values_on_bar:
                        edge = None if not rows else (rows[0] if v > base_val else rows[-1])
                        self._label_v(grid, cx, cell_list[k], self._value_text(c, s), edge,
                                      v >= base_val, base, height, color)
                    cx += cell_list[k]
            x += widths[c] + spacing

        rows = []
        for r, line in enumerate(grid.rows(self.ansi)):
            prefix = (labels.get(r, "").rjust(y_width) + " │ ") if self.show_y_axis else ""
            rows.append(prefix + line)
        label_line = (" " * spacing).join(
            text.center(w) for text, w in zip(cats, widths)
        )
        rows.append(" " * prefix_w + label_line)
        return assemble(rows, legend, total, self.ansi, self.title)

    @staticmethod
    def _bar_rows(v, base_val, base, row_of, height) -> range:
        if v > base_val:
            return range(max(0, min(row_of(v), base - 1)), base)
        if v < base_val:
            return range(base + 1, min(height - 1, max(row_of(v), base + 1)) + 1)
        return range(0)

    def _stack_v(self, grid, c, x0, bw, base, row_of) -> None:
        pos = neg = 0.0
        for s, column in enumerate(self.series_values):
            v = column[c]
            if v == 0:
                continue
            color, glyph = self._color(s, c, v), self._glyph(s, v)
            if v > 0:
                a, b = pos, pos + v
                pos = b
                start = base if a == 0 else row_of(a)
                rows = range(max(0, row_of(b)), start)
            else:
                a, b = neg, neg + v
                neg = b
                start = base if a == 0 else row_of(a)
                rows = range(start + 1, min(grid.height - 1, row_of(b)) + 1)
            for r in rows:
                for dx in range(bw):
                    grid.put(x0 + dx, r, glyph, color)

    def _stack_top(self, c, row_of):
        pos = sum(col[c] for col in self.series_values if col[c] > 0)
        neg = sum(col[c] for col in self.series_values if col[c] < 0)
        if pos > 0:
            return max(0, row_of(pos))
        if neg < 0:
            return row_of(neg)
        return None

    @staticmethod
    def _label_v(grid, x0, cell, text, edge, upward, base, height, color) -> None:
        """Value label above (or below) a bar, inside it if there is no room."""
        if edge is None:
            row = max(0, base - 1)
        elif upward:
            row = edge - 1 if edge > 0 else edge
        else:
            row = edge + 1 if edge < height - 1 else edge
        grid.text(x0 + (cell - len(text)) // 2, row, text, color)

    def _horizontal(self) -> str:
        term = terminal_size()
        total = self.width or term.columns
        legend = self._legend()
        low, high, ticks = self.axis()
        span = high - low
        count = len(self.categories)
        cats = [truncate(self._label(c), max(8, total // 3)) for c in range(count)]
        label_w = max(len(text) for text in cats)
        plot_w = total - legend.reserve_width(total) - label_w - 3
        if plot_w < 4:
            raise ValueError("Terminal is too narrow to render the chart")
        col_of = lambda v: round((v - low) / span * (plot_w - 1))
        base_val = min(max(0.0, low), high)
        base = col_of(base_val)
        if low < 0 < high:
            base = max(1, min(plot_w - 2, base))
        per = len(self.series_values) if (self.multi and not self.stacked) else 1
        nrows = count * per + (count - 1 if per > 1 else 0)
        grid = Grid(plot_w, nrows)
        axis_char = "│" if self.axis_char == "─" else self.axis_char
        if self.show_axis:
            grid.vline(base, 0, nrows - 1, axis_char)
        first_rows = []
        row = 0
        for c in range(count):
            first_rows.append(row)
            if self.stacked:
                self._stack_h(grid, c, row, base, col_of, plot_w)
                if self.show_values_on_bar:
                    pos = sum(col[c] for col in self.series_values if col[c] > 0)
                    end = col_of(pos) if pos > 0 else base
                    text = self._value_text(c, 0)
                    start = end + 2 if end + 2 + len(text) <= plot_w else end - len(text) + 1
                    grid.text(start, row, text)
                row += 1
            else:
                for k in range(per):
                    s = k if per > 1 else 0
                    v = self.series_values[s][c]
                    color, glyph = self._color(s, c, v), self._glyph(s, v)
                    if v > base_val:
                        end = max(col_of(v), base + 1)
                        grid.hline(row, base + 1, end, glyph, color)
                        if self.show_values_on_bar:
                            text = self._value_text(c, s)
                            if end + 2 + len(text) <= plot_w:
                                grid.text(end + 2, row, text)
                            else:
                                grid.text(max(base + 1, end - len(text) + 1), row, text, color)
                    elif v < base_val:
                        end = min(col_of(v), base - 1)
                        grid.hline(row, end, base - 1, glyph, color)
                        if self.show_values_on_bar:
                            text = self._value_text(c, s)
                            start = end - 1 - len(text)
                            if start >= 0:
                                grid.text(start, row, text)
                            else:
                                grid.text(end, row, text, color)
                    elif self.show_values_on_bar:
                        grid.text(base + 2, row, self._value_text(c, s))
                    row += 1
            if per > 1:
                row += 1
        rows = []
        first = set(first_rows)
        index = 0
        for r, line in enumerate(grid.rows(self.ansi)):
            if r in first:
                text = cats[index].ljust(label_w)
                index += 1
            else:
                text = " " * label_w
            rows.append(f"{text} │ {line}")
        if self.show_y_axis:
            items = [(col_of(t), fmt_tick(t)) for t in ticks]
            rows.append(" " * (label_w + 3) + label_row(plot_w, items))
        return assemble(rows, legend, total, self.ansi, self.title)

    def _stack_h(self, grid, c, row, base, col_of, plot_w) -> None:
        pos = neg = 0.0
        for s, column in enumerate(self.series_values):
            v = column[c]
            if v == 0:
                continue
            color, glyph = self._color(s, c, v), self._glyph(s, v)
            if v > 0:
                a, b = pos, pos + v
                pos = b
                start = base if a == 0 else col_of(a)
                if col_of(b) > start:
                    grid.hline(row, start + 1, min(plot_w - 1, col_of(b)), glyph, color)
            else:
                a, b = neg, neg + v
                neg = b
                start = base if a == 0 else col_of(a)
                if col_of(b) < start:
                    grid.hline(row, max(0, col_of(b)), start - 1, glyph, color)


class BarChartGUI(ChartGUI):
    """Interactive bar chart.

    Hover a bar for a tooltip, click legend entries to hide/show series,
    double-click one to isolate it, press ``t`` for dark mode.
    ``bar_width`` and ``spacing`` set the ratio of bar to gap.
    """

    def __init__(
        self,
        data: list | dict | None = None,
        category_labels: list | None = None,
        *,
        master=None,
        title: str = "Bar Chart",
        canvas_width: int | None = None,
        canvas_height: int | None = None,
        width: int | None = None,
        height: int | None = None,
        bar_width: int = 3,
        spacing: int = 2,
        show_values: bool = True,
        show_axis: bool = True,
        show_y_axis: bool = True,
        horizontal: bool = False,
        show_values_on_bar: bool = False,
        y_ticks: int = 5,
        colors: bool = False,
        sort: str | None = None,
        bar_color: str = "#4e79a7",
        negative_bar_color: str = "#e15759",
        background: str | None = None,
        y_axis_range: tuple[int | float, int | float] | None = None,
        mode: str = "grouped",
        series_name: str = "Value",
        legend: bool = True,
        legend_position: str = "right",
        legend_title: str | None = None,
        chart_title: str | None = None,
        palette: list | None = None,
        theme: str = "light",
        tooltips: bool = True,
    ) -> None:
        if width is not None:
            canvas_width = width
        if height is not None:
            canvas_height = height
        check_int("canvas_width", canvas_width, 1, none_ok=True)
        check_int("canvas_height", canvas_height, 1, none_ok=True)
        check_bool("colors", colors)
        chart = BarChart(
            data, category_labels, bar_width=bar_width, spacing=spacing,
            show_values=show_values, show_axis=show_axis, show_y_axis=show_y_axis,
            horizontal=horizontal, y_ticks=y_ticks, colors=colors, sort=sort,
            y_axis_range=y_axis_range, show_values_on_bar=show_values_on_bar,
            mode=mode, series_name=series_name, legend=legend,
            legend_position=legend_position, legend_title=legend_title,
            title=chart_title, palette=palette, positive_color=bar_color,
            negative_color=negative_bar_color,
        )
        super().__init__(
            chart, master=master, title=title, width=canvas_width or 800,
            height=canvas_height or 500, theme=theme, background=background,
            tooltips=tooltips,
        )

    # ----- drawing --------------------------------------------------------

    def _tip(self, c: int, hot: int | None):
        chart = self.chart
        rows = [(chart.categories[c] or f"#{c + 1}", None, "bold")]
        if chart.multi:
            total = 0.0
            for s, name in enumerate(chart.series_names):
                if not self.visible(("s", s)):
                    continue
                v = chart.series_values[s][c]
                total += v
                rows.append((f"{name}: {fmt_num(v)}", chart._color(s, c, v),
                             "bold" if s == hot else None))
            if chart.stacked:
                rows.append((f"Total: {fmt_num(total)}", None, None))
        else:
            v = chart.series_values[0][c]
            rows.append((f"{chart.series_names[0]}: {fmt_num(v)}", chart._color(0, c, v), None))
            values = chart.series_values[0]
            if all(x >= 0 for x in values) and sum(values) > 0:
                rows.append((f"Share: {fmt_pct(v / sum(values))}", None, None))
        return rows

    def render(self, box) -> None:
        chart, canvas, theme = self.chart, self.canvas, self.theme
        visible = lambda s, c, v: self.visible(chart._key(s, c, v))
        low, high, ticks = chart.axis(visible)
        span = high - low
        vertical = not chart.horizontal
        count = len(chart.categories)
        x0, y0, x1, y1 = box
        if vertical:
            plot = self.plot_box(box, ticks, bottom=30)
            left, top, right, bottom = plot
            v0, v1, c0, c1 = bottom, top, left, right
        else:
            label_w = min(
                max(self.measure(chart._label(c)) for c in range(count)) + 14,
                (x1 - x0) * 0.3,
            )
            plot = (x0 + label_w, y0 + 6, x1 - 10, y1 - 28)
            left, top, right, bottom = plot
            v0, v1, c0, c1 = left, right, top, bottom
        to_v = lambda value: v0 + (value - low) / span * (v1 - v0)
        if vertical:
            self.draw_y_grid(plot, ticks, to_v, labels=chart.show_y_axis)
        else:
            self.draw_x_grid(plot, ticks, to_v, labels=chart.show_y_axis)
        base_val = min(max(0.0, low), high)
        if chart.show_axis:
            p = to_v(base_val)
            if vertical:
                canvas.create_line(left, p, right, p, fill=theme["axis"], width=2)
            else:
                canvas.create_line(p, top, p, bottom, fill=theme["axis"], width=2)

        def rect(a, b, k0, k1):
            pa, pb = to_v(a), to_v(b)
            lo_p, hi_p = min(pa, pb), max(pa, pb)
            if hi_p - lo_p < 1:
                hi_p = lo_p + 1
            return (k0, lo_p, k1, hi_p) if vertical else (lo_p, k0, hi_p, k1)

        if count <= 0:
            return
        slot = (c1 - c0) / count
        fill = chart.bar_width / max(chart.bar_width + chart.spacing, 1)
        group = slot if chart.spacing == 0 else min(slot * fill, 140 if vertical else 60)
        centres = [c0 + slot * (c + 0.5) for c in range(count)]
        for c in range(count):
            cx = centres[c]
            if chart.stacked:
                self._draw_stack(c, cx, group, rect)
                continue
            entries = [
                (s, chart.series_values[s][c])
                for s in range(len(chart.series_values))
                if visible(s, c, chart.series_values[s][c])
            ]
            if not entries:
                continue
            bar = group / len(entries)
            for k, (s, v) in enumerate(entries):
                k0 = cx - group / 2 + k * bar
                r = rect(base_val, v, k0, k0 + bar)
                color = chart._color(s, c, v)
                canvas.create_rectangle(*r, fill=color, outline=color)
                self._add_bar_hit(r, c, s, vertical, (top, bottom), (left, right))
                if chart.show_values_on_bar:
                    self._bar_value(r, v, base_val, color, vertical)
        if vertical:
            labels = [chart._label(c) for c in range(count)]
            self.draw_category_labels(labels, centres, slot, bottom + 8)
        else:
            for c in range(count):
                text = self.ellipsize(chart._label(c), left - x0 - 10)
                canvas.create_text(left - 8, centres[c], text=text, anchor="e",
                                   fill=theme["fg"], font=self.font)

    def _add_bar_hit(self, r, c, s, vertical, vspan, hspan) -> None:
        x1, y1, x2, y2 = r
        if vertical:  # full-height column so thin bars are easy to hover
            ya, yb = vspan
            test = lambda x, y: x1 <= x <= x2 and ya <= y <= yb
        else:
            xa, xb = hspan
            test = lambda x, y: xa <= x <= xb and y1 <= y <= y2
        self.add_hit(test, self._tip(c, s), self.overlay_rect(x1, y1, x2, y2))

    def _bar_value(self, r, v, base_val, color, vertical) -> None:
        x1, y1, x2, y2 = r
        text = f"{v:g}"
        theme = self.theme
        if vertical:
            cx = (x1 + x2) / 2
            if y2 - y1 >= 24:
                cy = y1 + 12 if v >= base_val else y2 - 12
                fill = contrast_text(color)
            else:
                cy = y1 - 10 if v >= base_val else y2 + 10
                fill = theme["fg"]
            self.canvas.create_text(cx, cy, text=text, fill=fill, font=self.font)
            return
        cy = (y1 + y2) / 2
        if x2 - x1 >= self.measure(text) + 12:
            if v >= base_val:
                self.canvas.create_text(x2 - 5, cy, text=text, anchor="e",
                                        fill=contrast_text(color), font=self.font)
            else:
                self.canvas.create_text(x1 + 5, cy, text=text, anchor="w",
                                        fill=contrast_text(color), font=self.font)
        elif v >= base_val:
            self.canvas.create_text(x2 + 5, cy, text=text, anchor="w", fill=theme["fg"], font=self.font)
        else:
            self.canvas.create_text(x1 - 5, cy, text=text, anchor="e", fill=theme["fg"], font=self.font)

    def _draw_stack(self, c, cx, group, rect) -> None:
        chart, canvas = self.chart, self.canvas
        vertical = not chart.horizontal
        pos = neg = 0.0
        k0, k1 = cx - group / 2, cx + group / 2
        drawn = False
        for s, column in enumerate(chart.series_values):
            v = column[c]
            if v == 0 or not self.visible(("s", s)):
                continue
            if v > 0:
                a, b = pos, pos + v
                pos = b
            else:
                a, b = neg, neg + v
                neg = b
            r = rect(a, b, k0, k1)
            canvas.create_rectangle(*r, fill=chart._color(s, c, v), outline=self.theme["bg"])
            self.hit_rect(*r, self._tip(c, s))
            drawn = True
        if chart.show_values_on_bar and drawn:
            total = sum(col[c] for s, col in enumerate(chart.series_values) if self.visible(("s", s)))
            x1, y1, x2, y2 = rect(0, pos if pos > 0 else neg, k0, k1)
            if vertical:
                canvas.create_text((x1 + x2) / 2, y1 - 10, text=f"{total:g}",
                                   fill=self.theme["fg"], font=self.font)
            else:
                canvas.create_text(x2 + 5, (y1 + y2) / 2, text=f"{total:g}", anchor="w",
                                   fill=self.theme["fg"], font=self.font)


if __name__ == "__main__":
    labels = ["Dogs", "Cats", "Zebras", "Birds", "Fish"]
    print(BarChart([5, 2, 3, -4, -1], labels, height=12, bar_width=6))
    print()
    print(BarChart([5, 2, 3, -4, -1], labels, horizontal=True, show_values_on_bar=True))
    print()
    quarters = {"2024": [4, 6, 5, 8], "2025": [5, 7, 6, 9], "2026": [6, 8, 7, 11]}
    print(BarChart(quarters, ["Q1", "Q2", "Q3", "Q4"], height=10, mode="stacked"))
    BarChartGUI(quarters, ["Q1", "Q2", "Q3", "Q4"]).run()
