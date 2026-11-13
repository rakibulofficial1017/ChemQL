import chemql
import pandas as pd
import pytest

from chemql.data_analysis import Spreadsheet, Vector
from chemql.data_analysis.visualization import (
    BarChart,
    LineChart,
    run_spreadsheet_gui,
)
from chemql.data_analysis.visualization.main import _dataframe_from_source


@pytest.mark.parametrize(
    "expression",
    [
        'draw_bar_chart{[3, 5], ["A", "B"]}',
        'draw_line_chart{[3, 5], ["A", "B"]}',
        'draw_area_chart{[3, 5], ["A", "B"]}',
        'draw_pie_chart{[3, 5], ["A", "B"]}',
        'draw_scatter_plot{[(1, 2), (2, 3)]}',
        'draw_histogram{[1, 2, 2, 3]}',
        'draw_box_plot{[1, 2, 3, 7]}',
        'draw_heat_map{[[1, 2], [3, 4]], ["N", "S"], ["Q1", "Q2"]}',
        'draw_candlestick_chart{[(10, 12, 9, 11), (11, 13, 10, 12)], ["M1", "M2"]}',
    ],
)
def test_chart_helpers_can_be_called_from_chemql(expression):
    result = chemql.process_inline(expression)

    assert isinstance(result, str)
    assert result


def test_chart_helpers_and_types_are_available_in_embedded_python():
    expected = str(BarChart([3, 5], ["A", "B"], colors=False))

    assert chemql.draw_bar_chart([3, 5], ["A", "B"]) == expected
    assert chemql.evaluate_python('draw_bar_chart([3, 5], ["A", "B"])') == expected
    assert isinstance(chemql.evaluate_python('BarChart([3, 5], ["A", "B"])'), BarChart)
    assert chemql.python_globals["Spreadsheet"] is Spreadsheet
    assert chemql.python_globals["run_spreadsheet_gui"] is chemql.run_spreadsheet_gui


def test_chart_helper_prints_from_a_repl_command(monkeypatch, capsys):
    monkeypatch.setattr(chemql, "_record_execution", lambda *args: None)

    chemql.process_lines(['draw_bar_chart{[3, 5], ["A", "B"]}'])

    assert "A" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("expression", "gui_name"),
    [
        ('show_bar_chart{[3, 5], ["A", "B"], "dark"}', "BarChartGUI"),
        ('show_line_chart{[3, 5], ["A", "B"]}', "LineChartGUI"),
        ('show_area_chart{[3, 5], ["A", "B"]}', "AreaChartGUI"),
        ('show_pie_chart{[3, 5], ["A", "B"]}', "PieChartGUI"),
        ('show_scatter_plot{[(1, 2), (2, 3)]}', "ScatterPlotGUI"),
        ('show_histogram{[1, 2, 2, 3]}', "HistogramGUI"),
        ('show_box_plot{[1, 2, 3, 7]}', "BoxPlotGUI"),
        ('show_heat_map{[[1, 2], [3, 4]]}', "HeatMapGUI"),
        (
            'show_candlestick_chart{[(10, 12, 9, 11)], ["M1"]}',
            "CandlestickChartGUI",
        ),
    ],
)
def test_gui_chart_helpers_open_the_matching_gui_from_chemql(
    monkeypatch, expression, gui_name
):
    calls = []

    class FakeGUI:
        def __init__(self, *args, **kwargs):
            self.theme = kwargs["theme"]

        def run(self):
            calls.append(self.theme)

    monkeypatch.setattr(chemql, gui_name, FakeGUI)

    assert chemql.process_inline(expression) is None
    assert calls == ["dark" if '"dark"' in expression else "light"]


def test_data_analysis_tools_are_available_from_the_chemql_subpackage():
    sheet = Spreadsheet(rows=3, columns=2)
    sheet["A"] = ["Quarter", "Q1", "Q2"]
    sheet["B"] = ["Sales", 12, 18]

    frame = _dataframe_from_source(sheet)

    assert frame.to_dict("list") == {"Quarter": ["Q1", "Q2"], "Sales": [12, 18]}
    assert isinstance(sheet.column("B"), Vector)
    assert "12" in str(BarChart([12, 18], ["Q1", "Q2"], colors=False))
    assert "Q1" in str(LineChart([12, 18], ["Q1", "Q2"], colors=False))
    assert callable(run_spreadsheet_gui)


def test_dashboard_accepts_dataframes_too():
    frame = pd.DataFrame({"Quarter": ["Q1"], "Sales": [12]})

    assert _dataframe_from_source(frame).equals(frame)
