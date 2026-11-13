"""Candlestick (OHLC) charts."""

from __future__ import annotations

from .common import (
    ChartGUI, Grid, Legend, LegendEntry, assemble, check_bool, check_colors_flag,
    check_covers, check_hex, check_int, check_labels, check_legend, check_range,
    fmt_num, fmt_pct, fmt_tick, is_finite, is_number, label_row, nice_ticks,
    resolve_colors, slot_centre, terminal_size,
)

UP_COLOR = "#59a14f"
DOWN_COLOR = "#e15759"


def _validate_candles(data):
    if data is not None and not isinstance(data, list):
        raise TypeError("Candles must be a list of OHLC values or None")
    candles = [] if data is None else list(data)
    for candle in candles:
        if not isinstance(candle, (list, tuple)) or len(candle) != 4:
            raise TypeError("Each candle must be an (open, high, low, close) tuple")
        for value in candle:
            if not is_number(value):
                raise TypeError("OHLC values must be numbers")
            if not is_finite(value):
                raise ValueError("OHLC values must be finite")
        open_value, high, low, close = candle
        if low > high or not low <= open_value <= high or not low <= close <= high:
            raise ValueError("Each candle must satisfy low <= open, close <= high")
    return [tuple(candle) for candle in candles]


class CandlestickChart:
    def __init__(
        self,
        data: list | None = None,
        category_labels: list | None = None,
        *,
        height: int | None = None,
        width: int | None = None,
        y_ticks: int = 5,
        y_axis_range: tuple[int | float, int | float] | None = None,
        show_axis: bool = True,
        show_y_axis: bool = True,
        colors: bool | None = None,
        spacing: int = 2,
        candle_width: int = 1,
        legend: bool = True,
        legend_position: str = "bottom",
        legend_title: str | None = None,
        title: str | None = None,
        up_color: str = UP_COLOR,
        down_color: str = DOWN_COLOR,
    ) -> None:
        self.data = _validate_candles(data)
        self.categories = check_labels(category_labels, len(self.data))
        for name, value in (("height", height), ("width", width),
                            ("y_ticks", y_ticks), ("spacing", spacing),
                            ("candle_width", candle_width)):
            check_int(name, value, none_ok=True)
        if height is not None and height < 3:
            raise ValueError("Height must be at least 3")
        if width is not None and width < 1:
            raise ValueError("Width must be positive")
        if y_ticks < 2 or spacing < 0 or candle_width < 1:
            raise ValueError("y_ticks must be at least 2, spacing nonnegative, candle_width positive")
        check_bool("show_axis", show_axis)
        check_bool("show_y_axis", show_y_axis)
        check_colors_flag(colors)
        check_legend(legend, legend_position, legend_title)
        if title is not None and not isinstance(title, str):
            raise TypeError("title must be a string or None")
        self.y_axis_range = check_range(y_axis_range, "y_axis_range")
        values = [v for candle in self.data for v in candle]
        check_covers(self.y_axis_range, values, "y_axis_range")
        self.height, self.width, self.y_ticks = height, width, y_ticks
        self.show_axis, self.show_y_axis = show_axis, show_y_axis
        self.ansi = resolve_colors(colors)
        self.spacing, self.candle_width = spacing, candle_width
        self.up_color = check_hex("up_color", up_color)
        self.down_color = check_hex("down_color", down_color)
        self.legend, self.legend_position, self.legend_title = legend, legend_position, legend_title
        self.title = title

    def is_empty(self) -> bool:
        return not self.data

    def is_up(self, candle) -> bool:
        return candle[3] >= candle[0]

    def color_for(self, candle) -> str:
        return self.up_color if self.is_up(candle) else self.down_color

    def axis(self, show_up: bool = True, show_down: bool = True, target: int | None = None):
        target = target or self.y_ticks
        if self.y_axis_range is not None:
            return nice_ticks(*self.y_axis_range, target, expand=False)
        values = [v for candle in self.data for v in candle
                  if (show_up if self.is_up(candle) else show_down)]
        if not values:
            return nice_ticks(0.0, 1.0, target)
        low, high = min(values), max(values)
        if low == high:
            pad = max(abs(low) * 0.05, 1.0)
            low, high = low - pad, high + pad
        return nice_ticks(low, high, target)

    def _value_label(self, index: int) -> str:
        label = self.categories[index]
        close = self.data[index][3]
        return f"{label} ({close:g})" if label else f"{close:g}"

    def legend_entries(self) -> list[LegendEntry]:
        return [
            LegendEntry("up", "Up (close ≥ open)", self.up_color, "█", "square"),
            LegendEntry("down", "Down (close < open)", self.down_color, "▓", "square"),
        ]

    def _legend(self) -> Legend:
        return Legend(self.legend_entries(), self.legend_position, self.legend_title, self.legend)

    def __str__(self) -> str:
        if self.is_empty():
            return "(Empty CandlestickChart)"
        term = terminal_size()
        total = self.width or term.columns
        legend = self._legend()
        height = self.height or max(
            3, term.lines - 5 - legend.height(total) - (1 if self.title else 0)
        )
        low, high, ticks = self.axis(target=min(self.y_ticks, max(2, (height + 1) // 2)))
        span = high - low
        row_of = lambda v: round((high - v) / span * (height - 1))
        labels = {}
        for tick in ticks:
            labels.setdefault(row_of(tick), fmt_tick(tick))
        y_width = max(len(text) for text in labels.values())
        prefix_w = y_width + 3 if self.show_y_axis else 0
        plot_w = max(1, total - legend.reserve_width(total) - prefix_w)
        count = len(self.data)
        xs = [slot_centre(i, count, plot_w) for i in range(count)]
        grid = Grid(plot_w, height)
        if self.show_axis:
            grid.hline(row_of(min(max(0, low), high)), 0, plot_w - 1, "─")
        half = (min(self.candle_width, max(1, plot_w // count - 1)) - 1) // 2
        for (open_value, high_v, low_v, close), x in zip(self.data, xs):
            color = self.color_for((open_value, high_v, low_v, close))
            up = close >= open_value
            grid.vline(x, row_of(high_v), row_of(low_v), "│", color)
            top, bottom = sorted((row_of(open_value), row_of(close)))
            for row in range(top, bottom + 1):
                for dx in range(-half, half + 1):
                    grid.put(x + dx, row, "█" if up else "▓", color)
        lines = []
        for r, line in enumerate(grid.rows(self.ansi)):
            prefix = (labels.get(r, "").rjust(y_width) + " │ ") if self.show_y_axis else ""
            lines.append(prefix + line)
        lines.append(" " * prefix_w + label_row(
            plot_w, [(xs[i], self._value_label(i)) for i in range(count)]))
        return assemble(lines, legend, total, self.ansi, self.title)


class CandlestickChartGUI(ChartGUI):
    """Interactive candlestick chart: hover for OHLC and change, click the legend
    to hide rising or falling candles."""

    def __init__(
        self,
        data: list | None = None,
        category_labels: list | None = None,
        *,
        master=None,
        title: str = "Candlestick Chart",
        width: int = 800,
        height: int = 500,
        y_ticks: int = 5,
        y_axis_range: tuple[int | float, int | float] | None = None,
        show_axis: bool = True,
        show_y_axis: bool = True,
        colors: bool = True,
        up_color: str = UP_COLOR,
        down_color: str = DOWN_COLOR,
        background: str | None = None,
        legend: bool = True,
        legend_position: str = "right",
        legend_title: str | None = None,
        chart_title: str | None = None,
        theme: str = "light",
        tooltips: bool = True,
    ) -> None:
        check_bool("colors", colors)
        chart = CandlestickChart(
            data, category_labels, y_ticks=y_ticks, y_axis_range=y_axis_range,
            show_axis=show_axis, show_y_axis=show_y_axis, up_color=up_color,
            down_color=down_color, legend=legend, legend_position=legend_position,
            legend_title=legend_title, title=chart_title,
        )
        self.use_colors = colors
        super().__init__(chart, master=master, title=title, width=width, height=height,
                         theme=theme, background=background, tooltips=tooltips)

    def _color(self, candle) -> str:
        if not self.use_colors:
            return "#4e79a7"
        return self.chart.color_for(candle)

    def render(self, box) -> None:
        chart, canvas, theme = self.chart, self.canvas, self.theme
        low, high, ticks = chart.axis(self.visible("up"), self.visible("down"))
        span = high - low
        plot = self.plot_box(box, ticks, bottom=30)
        left, top, right, bottom = plot
        y_for = lambda v: bottom - (v - low) / span * (bottom - top)
        self.draw_y_grid(plot, ticks, y_for, labels=chart.show_y_axis)
        if chart.show_axis:
            y = y_for(min(max(0, low), high))
            canvas.create_line(left, y, right, y, fill=theme["axis"], width=2)
        count = len(chart.data)
        slot = (right - left) / count
        body_w = min(26.0, slot * 0.55)
        centres = []
        for i, candle in enumerate(chart.data):
            cx = left + slot * (i + 0.5)
            centres.append(cx)
            open_value, high_v, low_v, close = candle
            if not self.visible("up" if chart.is_up(candle) else "down"):
                continue
            color = self._color(candle)
            canvas.create_line(cx, y_for(high_v), cx, y_for(low_v), fill=color, width=2)
            body_top = min(y_for(open_value), y_for(close))
            body_bottom = max(y_for(open_value), y_for(close))
            if body_bottom - body_top < 2:
                body_bottom = body_top + 2
            canvas.create_rectangle(cx - body_w / 2, body_top, cx + body_w / 2, body_bottom,
                                    fill=color, outline=color)
            change = close - open_value
            pct = change / open_value if open_value else 0.0
            tip = [
                (chart.categories[i] or f"#{i + 1}", None, "bold"),
                (f"Open: {fmt_num(open_value)}", None, None),
                (f"High: {fmt_num(high_v)}", None, None),
                (f"Low: {fmt_num(low_v)}", None, None),
                (f"Close: {fmt_num(close)}", color, None),
                (f"Change: {change:+g} ({pct * 100:+.1f}%)", None, None),
            ]
            x1, x2 = cx - slot / 2, cx + slot / 2
            self.add_hit(
                lambda x, y, a=x1, b=x2: a <= x <= b and top <= y <= bottom, tip,
                self.overlay_rect(cx - body_w / 2 - 3, y_for(high_v) - 2,
                                  cx + body_w / 2 + 3, y_for(low_v) + 2),
            )
        labels = [chart._value_label(i) for i in range(count)]
        self.draw_category_labels(labels, centres, slot, bottom + 8)


if __name__ == "__main__":
    candles = [(10, 13, 9, 12), (12, 14, 10, 11), (11, 15, 10, 14), (14, 16, 12, 13)]
    print(CandlestickChart(candles, ["Mon", "Tue", "Wed", "Thu"]))
    CandlestickChartGUI(candles, ["Mon", "Tue", "Wed", "Thu"]).run()
