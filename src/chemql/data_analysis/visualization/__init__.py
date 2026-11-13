"""Charting tools and spreadsheet visualization dashboards."""

from .area import AreaChart, AreaChartGUI
from .bar import BarChart, BarChartGUI
from .boxplot import BoxPlot, BoxPlotGUI, BoxStats, describe
from .candlestick import CandlestickChart, CandlestickChartGUI
from .heatmap import HeatMap, HeatMapGUI
from .histogram import Histogram, HistogramGUI
from .line import LineChart, LineChartGUI
from .pie import PieChart, PieChartGUI
from .scatter import ScatterPlot, ScatterPlotGUI


def print_text_charts(data: dict) -> None:
    from .main import print_text_charts as print_charts

    print_charts(data)


def run_gui(data: dict, theme: str = "light") -> None:
    from .main import run_gui as open_dashboard

    open_dashboard(data, theme)


def run_spreadsheet_gui(source=None, theme: str = "light") -> None:
    from .main import run_spreadsheet_gui as open_dashboard

    open_dashboard(source, theme)


def sample_data() -> dict:
    from .main import sample_data as create_sample_data

    return create_sample_data()


__all__ = [
    "AreaChart",
    "AreaChartGUI",
    "BarChart",
    "BarChartGUI",
    "BoxPlot",
    "BoxPlotGUI",
    "BoxStats",
    "CandlestickChart",
    "CandlestickChartGUI",
    "HeatMap",
    "HeatMapGUI",
    "Histogram",
    "HistogramGUI",
    "LineChart",
    "LineChartGUI",
    "PieChart",
    "PieChartGUI",
    "ScatterPlot",
    "ScatterPlotGUI",
    "describe",
    "print_text_charts",
    "run_gui",
    "run_spreadsheet_gui",
    "sample_data",
]
