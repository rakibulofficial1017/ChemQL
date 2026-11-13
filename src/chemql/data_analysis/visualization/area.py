"""Area charts: filled line charts, optionally stacked."""

from __future__ import annotations

from .common import check_bool, check_char, mix
from .line import LineChart, LineChartGUI

AREA_FILLS = ("░", "▒", "▓", "▚", "▞", "▤")


class AreaChart(LineChart):
    """Same arguments as ``LineChart`` plus ``stacked`` and ``fill_char``.

    Stacked areas require non-negative values.
    """

    INCLUDE_ZERO = True

    def __init__(self, data=None, category_labels=None, *, stacked: bool = False,
                 fill_char: str = "▒", **kwargs) -> None:
        check_bool("stacked", stacked)
        check_char("fill_char", fill_char)
        self.stacked = stacked
        self.fill_char = fill_char
        super().__init__(data, category_labels, **kwargs)
        if stacked and any(v < 0 for column in self.series_values for v in column):
            raise ValueError("Stacked areas require non-negative values")

    def _stacked(self) -> bool:
        return self.stacked and self.multi

    def _layers(self, series=None):
        series = list(range(len(self.series_values))) if series is None else list(series)
        if not self._stacked():
            return [(s, self.series_values[s], None) for s in series]
        cumulative = [0.0] * len(self.categories)
        layers = []
        for s in series:
            bottom = list(cumulative)
            top = [b + v for b, v in zip(cumulative, self.series_values[s])]
            cumulative = top
            layers.append((s, top, bottom))
        return layers

    def _fill_glyph(self, s: int) -> str:
        return self.fill_char if self.ansi else AREA_FILLS[s % len(AREA_FILLS)]

    def _legend_marker(self, s: int) -> str:
        return self._fill_glyph(s)

    def _decorate(self, grid, xs, layers, row_of, base_val) -> None:
        for s, top, bottom in layers:
            glyph = self._fill_glyph(s)
            color = self.palette[s % len(self.palette)]
            columns = []
            if len(xs) == 1:
                columns.append((xs[0], top[0], base_val if bottom is None else bottom[0]))
            for i in range(len(xs) - 1):
                x1, x2 = xs[i], xs[i + 1]
                for x in range(x1, x2 + 1):
                    f = (x - x1) / max(1, x2 - x1)
                    t = top[i] + (top[i + 1] - top[i]) * f
                    b = base_val if bottom is None else bottom[i] + (bottom[i + 1] - bottom[i]) * f
                    columns.append((x, t, b))
            for x, t, b in columns:
                first, last = sorted((row_of(t), row_of(b)))
                for row in range(first, last + 1):
                    grid.put(x, row, glyph, color)


class AreaChartGUI(LineChartGUI):
    """Interactive area chart (see ``LineChartGUI``); pass ``stacked=True`` to stack."""

    CHART = AreaChart

    def __init__(self, data=None, category_labels=None, *, title: str = "Area Chart",
                 stacked: bool = False, **kwargs) -> None:
        super().__init__(data, category_labels, title=title, stacked=stacked, **kwargs)

    def _fill_layer(self, layer, top_points, bottom_points, color) -> None:
        points = top_points + list(reversed(bottom_points))
        flat = [c for p in points for c in p]
        if len(points) >= 3:
            self.canvas.create_polygon(flat, fill=mix(color, self.theme["bg"], 0.55), outline="")


if __name__ == "__main__":
    traffic = {"Web": [30, 42, 38, 55, 61], "Mobile": [20, 28, 35, 40, 52]}
    days = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    print(AreaChart(traffic, days, stacked=True, height=12))
    AreaChartGUI(traffic, days, stacked=True).run()
