"""Demo of every chart type, in the terminal and in an interactive window.

    python main.py            # text charts, then the GUI
    python main.py --no-gui   # text charts only (works without tkinter)
    python main.py --no-tui   # GUI only
    python main.py --theme dark
    python main.py --spreadsheet sales.xlsx

    The GUI context menu can export a chart as PNG or print it in the terminal.
    For a Spreadsheet object, import this module and call
    ``run_spreadsheet_gui(sheet)``.
"""

from __future__ import annotations

import argparse
import random

import pandas as pd

from . import area, bar, boxplot, candlestick, heatmap, histogram, line, pie, scatter
from .common import tk

try:
    from tkinter import ttk
except Exception:  # pragma: no cover
    ttk = None


def sample_data() -> dict:
    rng = random.Random(7)
    return {
        "bar": ([5, 2, 3, -4, -1], ["Dogs", "Cats", "Zebras", "Birds", "Fish"]),
        "stacked": (
            {"2024": [4, 6, 5, 8], "2025": [5, 7, 6, 9], "2026": [6, 8, 7, 11]},
            ["Q1", "Q2", "Q3", "Q4"],
        ),
        "line": (
            {"North": [4, 7, 3, 9, 6], "South": [2, 3, 6, 4, 8]},
            ["Mon", "Tue", "Wed", "Thu", "Fri"],
        ),
        "area": (
            {"Web": [30, 42, 38, 55, 61], "Mobile": [20, 28, 35, 40, 52]},
            ["Mon", "Tue", "Wed", "Thu", "Fri"],
        ),
        "scatter": (
            {
                "Control": [(1, 2), (2, 3), (3, 3.5), (4, 4), (5, 6)],
                "Treated": [(1, 3), (2, 5), (3, 8), (4, 9), (5, 12)],
            },
            None,
        ),
        "pie": ([40, 25, 20, 15], ["Rent", "Food", "Travel", "Other"]),
        "histogram": {
            "Group A": [rng.gauss(50, 10) for _ in range(300)],
            "Group B": [rng.gauss(66, 8) for _ in range(300)],
        },
        "boxplot": {
            "Control": [12, 14, 15, 15, 16, 18, 19, 21, 24, 40],
            "Drug A": [15, 18, 19, 20, 22, 23, 25, 27, 30],
            "Drug B": [9, 11, 12, 14, 14, 15, 17, 18, 19],
        },
        "heatmap": (
            [[1, 4, 7, 3], [2, 5, 8, 4], [3, 6, 9, 5]],
            ["North", "Central", "South"],
            ["Q1", "Q2", "Q3", "Q4"],
        ),
        "candles": (
            [(10, 13, 9, 12), (12, 14, 10, 11), (11, 15, 10, 14),
             (14, 16, 12, 13), (13, 17, 12, 16)],
            ["Mon", "Tue", "Wed", "Thu", "Fri"],
        ),
    }


def print_text_charts(d: dict) -> None:
    charts = (
        ("Bar chart", bar.BarChart(*d["bar"], height=10)),
        ("Stacked bar chart", bar.BarChart(*d["stacked"], mode="stacked", height=10)),
        ("Line chart", line.LineChart(*d["line"], height=10)),
        ("Area chart", area.AreaChart(*d["area"], stacked=True, height=10)),
        ("Scatter plot", scatter.ScatterPlot(d["scatter"][0], height=10)),
        ("Pie chart", pie.PieChart(*d["pie"], radius=5, donut=True)),
        ("Histogram", histogram.Histogram(d["histogram"], bins=12, height=10)),
        ("Box plot", boxplot.BoxPlot(d["boxplot"], height=12)),
        ("Heat map", heatmap.HeatMap(*d["heatmap"], show_values=True)),
        ("Candlestick chart", candlestick.CandlestickChart(*d["candles"], height=10)),
    )
    for title, chart in charts:
        print(f"\n{title}\n{'=' * len(title)}")
        print(chart)


def run_gui(d: dict, theme: str) -> None:
    if tk is None or ttk is None:
        print("\ntkinter is not available; skipping the GUI.")
        return
    root = tk.Tk()
    root.title("Data Visualization Examples")
    root.geometry("1000x680")

    top = ttk.Frame(root)
    top.pack(fill="x", padx=8, pady=(6, 0))
    ttk.Label(
        top,
        text="Hover for details · click legend to hide · double-click to isolate · "
             "right-click for menu · t = theme",
    ).pack(side="left")
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)

    tabs = (
        ("Bar", bar.BarChartGUI, (d["bar"][0], d["bar"][1]),
         {"show_values_on_bar": True, "series_name": "Animals"}),
        ("Stacked", bar.BarChartGUI, d["stacked"], {"mode": "stacked", "show_values_on_bar": True}),
        ("Line", line.LineChartGUI, d["line"], {}),
        ("Area", area.AreaChartGUI, d["area"], {"stacked": True}),
        ("Scatter", scatter.ScatterPlotGUI, (d["scatter"][0],), {}),
        ("Pie", pie.PieChartGUI, d["pie"], {"donut": True}),
        ("Histogram", histogram.HistogramGUI, (d["histogram"],), {"bins": 14}),
        ("Box plot", boxplot.BoxPlotGUI, (d["boxplot"],), {}),
        ("Heat map", heatmap.HeatMapGUI, d["heatmap"], {"show_values": True}),
        ("Candlestick", candlestick.CandlestickChartGUI, d["candles"], {}),
    )
    guis = []
    for name, gui_class, args, options in tabs:
        tab = ttk.Frame(notebook)
        notebook.add(tab, text=name)
        guis.append(gui_class(*args, master=tab, theme=theme, **options))

    dark = tk.BooleanVar(value=theme == "dark")

    def apply_theme() -> None:
        for gui in guis:
            gui.set_theme("dark" if dark.get() else "light")

    ttk.Checkbutton(top, text="Dark mode", variable=dark, command=apply_theme).pack(side="right")
    root.mainloop()


def _dataframe_from_source(source) -> pd.DataFrame:
    if isinstance(source, pd.DataFrame):
        frame = source.copy()
    elif callable(getattr(source, "to_dataframe", None)):
        cells = source.to_dataframe()
        if cells.empty:
            raise ValueError("The spreadsheet has no rows.")
        headers = [
            str(value).strip() if pd.notna(value) and str(value).strip() else f"Column {i + 1}"
            for i, value in enumerate(cells.iloc[0].tolist())
        ]
        frame = cells.iloc[1:].copy()
        frame.columns = headers
    else:
        raise TypeError("Expected a pandas DataFrame or a Spreadsheet object.")

    if frame.empty or frame.shape[1] == 0:
        raise ValueError("The spreadsheet has no data.")
    names = []
    seen = set()
    for index, value in enumerate(frame.columns):
        name = str(value).strip() or f"Column {index + 1}"
        base, suffix = name, 2
        while name in seen:
            name = f"{base} ({suffix})"
            suffix += 1
        names.append(name)
        seen.add(name)
    frame.columns = names
    return frame.reset_index(drop=True)


def _numeric_columns(frame: pd.DataFrame) -> list[str]:
    return [
        column
        for column in frame.columns
        if pd.to_numeric(frame[column], errors="coerce").notna().any()
    ]


def _read_spreadsheet_file(filename: str) -> pd.DataFrame:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "csv":
        return pd.read_csv(filename)
    if suffix in ("xlsx", "xls"):
        return pd.read_excel(filename)
    raise ValueError("Choose a CSV, XLSX, or XLS file.")


def _make_spreadsheet_chart(frame, chart_type, category, value_columns, theme, master):
    if not value_columns:
        raise ValueError("Select at least one numeric value column.")
    numeric = {
        column: pd.to_numeric(frame[column], errors="coerce")
        for column in value_columns
    }

    if chart_type in ("Bar", "Line", "Area"):
        valid = frame[category].notna()
        for values in numeric.values():
            valid &= values.notna()
        labels = frame.loc[valid, category].astype(str).tolist()
        series = {
            column: values.loc[valid].tolist()
            for column, values in numeric.items()
        }
        if not labels:
            raise ValueError("No complete rows are available for the selected columns.")
        if chart_type == "Bar":
            return bar.BarChartGUI(
                series, labels, master=master, title="Spreadsheet · Bar",
                chart_title="Spreadsheet data", theme=theme,
            )
        if chart_type == "Line":
            return line.LineChartGUI(
                series, labels, master=master, title="Spreadsheet · Line",
                chart_title="Spreadsheet data", theme=theme,
            )
        return area.AreaChartGUI(
            series, labels, master=master, title="Spreadsheet · Area",
            chart_title="Spreadsheet data", theme=theme,
        )

    clean = {
        column: values.dropna().tolist()
        for column, values in numeric.items()
        if values.notna().any()
    }
    if not clean:
        raise ValueError("Select at least one column containing numeric values.")
    if chart_type == "Pie":
        if len(clean) != 1:
            raise ValueError("Pie charts need exactly one numeric value column.")
        column, values = next(iter(clean.items()))
        valid = numeric[column].notna() & frame[category].notna()
        labels = frame.loc[valid, category].astype(str).tolist()
        values = numeric[column].loc[valid].tolist()
        return pie.PieChartGUI(
            values, labels, master=master, title="Spreadsheet · Pie",
            chart_title=f"{column} by {category}", theme=theme,
        )
    if chart_type == "Scatter":
        x_values = pd.to_numeric(frame[category], errors="coerce")
        y_column = next((column for column in value_columns if column != category), None)
        if y_column is None:
            raise ValueError("Select a numeric X column and a different Y column.")
        y_values = numeric[y_column]
        valid = x_values.notna() & y_values.notna()
        points = list(zip(x_values.loc[valid].tolist(), y_values.loc[valid].tolist()))
        if not points:
            raise ValueError("No complete numeric X/Y pairs are available.")
        return scatter.ScatterPlotGUI(
            points, master=master, title="Spreadsheet · Scatter",
            chart_title=f"{y_column} vs {category}", theme=theme,
        )
    if chart_type == "Histogram":
        return histogram.HistogramGUI(
            clean, master=master, title="Spreadsheet · Histogram",
            chart_title="Spreadsheet distributions", theme=theme,
        )
    if chart_type == "Box plot":
        return boxplot.BoxPlotGUI(
            clean, master=master, title="Spreadsheet · Box plot",
            chart_title="Spreadsheet distributions", theme=theme,
        )
    if chart_type == "Candlestick":
        columns = {column.casefold(): column for column in value_columns}
        required = ("open", "high", "low", "close")
        if not all(name in columns for name in required):
            raise ValueError(
                "Candlestick charts need selected columns named Open, High, Low, and Close."
            )
        prices = [numeric[columns[name]] for name in required]
        valid = frame[category].notna()
        for values in prices:
            valid &= values.notna()
        candles = list(zip(*(values.loc[valid].tolist() for values in prices)))
        if not candles:
            raise ValueError("No complete OHLC rows are available.")
        return candlestick.CandlestickChartGUI(
            candles, frame.loc[valid, category].astype(str).tolist(),
            master=master, title="Spreadsheet · Candlestick",
            chart_title="Spreadsheet prices", theme=theme,
        )
    if chart_type == "Heat map":
        valid = frame[category].notna()
        for values in numeric.values():
            valid &= values.notna()
        matrix = [values.loc[valid].tolist() for values in numeric.values()]
        if not valid.any():
            raise ValueError("No complete rows are available for the selected columns.")
        return heatmap.HeatMapGUI(
            list(map(list, zip(*matrix))),
            frame.loc[valid, category].astype(str).tolist(),
            list(numeric),
            master=master, title="Spreadsheet · Heat map",
            chart_title="Spreadsheet data", show_values=True, theme=theme,
        )
    raise ValueError(f"Unsupported chart type: {chart_type}.")


def run_spreadsheet_gui(source=None, theme: str = "light") -> None:
    """Open a chart dashboard for a DataFrame or Spreadsheet-like object."""
    if tk is None or ttk is None:
        raise RuntimeError("tkinter is not available; spreadsheet charts need the GUI.")
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.title("Spreadsheet Data Visualization")
    root.geometry("1000x700")
    root.columnconfigure(0, weight=1)
    root.rowconfigure(2, weight=1)

    controls = ttk.Frame(root, padding=8)
    controls.grid(row=0, column=0, sticky="ew")
    ttk.Button(controls, text="Open CSV / Excel…", command=lambda: open_file()).pack(side="left")
    chart_var = tk.StringVar(value="Bar")
    ttk.Label(controls, text="Chart").pack(side="left", padx=(16, 4))
    chart_picker = ttk.Combobox(
        controls,
        textvariable=chart_var,
        values=(
            "Bar", "Line", "Area", "Pie", "Scatter", "Histogram",
            "Box plot", "Heat map", "Candlestick",
        ),
        state="readonly",
        width=14,
    )
    chart_picker.pack(side="left")

    column_controls = ttk.Frame(root, padding=(8, 0, 8, 8))
    column_controls.grid(row=1, column=0, sticky="ew")
    ttk.Label(column_controls, text="Category / X").grid(row=0, column=0, sticky="w")
    category_var = tk.StringVar()
    category_picker = ttk.Combobox(
        column_controls, textvariable=category_var, state="readonly", width=22
    )
    category_picker.grid(row=1, column=0, padx=(0, 12), sticky="w")
    ttk.Label(column_controls, text="Numeric value columns").grid(
        row=0, column=1, sticky="w"
    )
    value_list = tk.Listbox(
        column_controls, selectmode="extended", exportselection=False,
        height=4, width=28,
    )
    value_list.grid(row=1, column=1, sticky="w")
    ttk.Button(
        column_controls, text="Update chart",
        command=lambda: render_chart(),
    ).grid(row=1, column=2, padx=12, sticky="n")

    status = tk.StringVar(value="Open a CSV/Excel file or pass a Spreadsheet object.")
    ttk.Label(root, textvariable=status, padding=(8, 0)).grid(row=3, column=0, sticky="w")
    chart_frame = ttk.Frame(root)
    chart_frame.grid(row=2, column=0, sticky="nsew")
    chart_frame.rowconfigure(0, weight=1)
    chart_frame.columnconfigure(0, weight=1)
    state: dict[str, pd.DataFrame | None] = {"frame": None}

    def set_source(value) -> None:
        frame = _dataframe_from_source(value)
        state["frame"] = frame
        category_picker["values"] = list(frame.columns)
        category_var.set(str(frame.columns[0]))
        value_list.delete(0, tk.END)
        columns = _numeric_columns(frame)
        for column in columns:
            value_list.insert(tk.END, column)
        for index in range(len(columns)):
            value_list.selection_set(index)
        status.set(f"{len(frame)} rows · {len(frame.columns)} columns")
        render_chart()

    def open_file() -> None:
        filename = filedialog.askopenfilename(
            title="Open spreadsheet data",
            filetypes=(
                ("Spreadsheet files", "*.csv *.xlsx *.xls"),
                ("CSV files", "*.csv"),
                ("Excel files", "*.xlsx *.xls"),
            ),
        )
        if not filename:
            return
        try:
            set_source(_read_spreadsheet_file(filename))
        except (ImportError, OSError, ValueError, pd.errors.ParserError) as exc:
            messagebox.showerror("Could not open spreadsheet", str(exc), parent=root)

    def render_chart() -> None:
        frame = state["frame"]
        if frame is None:
            return
        for child in chart_frame.winfo_children():
            child.destroy()
        selected = [value_list.get(i) for i in value_list.curselection()]
        try:
            chart = _make_spreadsheet_chart(
                frame, chart_var.get(), category_var.get(), selected, theme, chart_frame
            )
        except (TypeError, ValueError, KeyError) as exc:
            status.set(str(exc))
            return
        status.set(f"{len(frame)} rows · {len(frame.columns)} columns")

    chart_picker.bind("<<ComboboxSelected>>", lambda _event: render_chart())
    category_picker.bind("<<ComboboxSelected>>", lambda _event: render_chart())
    value_list.bind("<<ListboxSelect>>", lambda _event: render_chart())
    if source is not None:
        try:
            set_source(source)
        except (TypeError, ValueError) as exc:
            messagebox.showerror("Could not read spreadsheet", str(exc), parent=root)
    root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--no-gui", action="store_true", help="only print the text charts")
    parser.add_argument("--no-tui", action="store_true", help="only open the GUI")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    parser.add_argument(
        "--spreadsheet",
        metavar="PATH",
        help="open a CSV/Excel file in the spreadsheet chart dashboard",
    )
    args = parser.parse_args()
    if args.spreadsheet:
        try:
            frame = _read_spreadsheet_file(args.spreadsheet)
            run_spreadsheet_gui(frame, args.theme)
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            parser.error(str(exc))
        return
    data = sample_data()
    if not args.no_tui:
        print_text_charts(data)
    if not args.no_gui:
        run_gui(data, args.theme)


if __name__ == "__main__":
    main()
