import ast
from collections.abc import Iterable
import operator
import re
from typing import Any

import pandas as pd


class Spreadsheet:
    _CELL_REFERENCE = re.compile(r"^\$?([A-Za-z]+)\$?([1-9]\d*)$")
    _RANGE_REFERENCE = re.compile(
        r"^\$?([A-Za-z]+)\$?([1-9]\d*):\$?([A-Za-z]+)\$?([1-9]\d*)$"
    )
    _FORMULA_RANGE = re.compile(
        r"\$?([A-Za-z]+)\$?([1-9]\d*)\s*:\s*\$?([A-Za-z]+)\$?([1-9]\d*)"
    )
    _FORMULA_CELL = re.compile(r"\$?([A-Za-z]+)\$?([1-9]\d*)")
    _BINARY_OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    _UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}

    @staticmethod
    def number_to_excel_column(n: int) -> str:
        if n <= 0:
            raise ValueError("Column numbers are 1-based and must be positive.")

        letters: list[str] = []
        while n > 0:
            n, remainder = divmod(n - 1, 26)
            letters.append(chr(ord("A") + remainder))
        return "".join(reversed(letters))

    def __init__(self, rows: int, columns: int):
        if rows < 0 or columns < 0:
            raise ValueError("Rows and columns must be non-negative.")

        self.no_rows = rows
        self.no_cols = columns
        self.grid_data = {
            self.number_to_excel_column(i): [0] * rows for i in range(1, columns + 1)
        }
        self.df = pd.DataFrame(self.grid_data, index=range(rows), dtype=object)
        self._formulas: dict[tuple[int, int], str] = {}

    @property
    def shape(self):
        return (self.no_rows, self.no_cols)

    def __repr__(self):
        return f"Spreadsheet(rows={self.no_rows}, columns={self.no_cols})"

    def __str__(self) -> str:
        reset = "\033[0m"
        header_style = "\033[1;38;2;255;255;255;48;2;0;100;0m"
        index_style = "\033[1;36m"
        cell_styles = (
            "\033[38;2;210;210;210;48;2;40;40;40m",
            "\033[38;2;210;210;210;48;2;80;80;80m",
        )
        formula_styles = (
            "\033[1;38;2;120;255;120;48;2;40;40;40m",
            "\033[1;38;2;120;255;120;48;2;80;80;80m",
        )
        border_style = "\033[90m"

        headers = [""] + list(self.df.columns)
        rows: list[list[str]] = []
        for row in range(self.no_rows):
            values = [str(row + 1)]
            for column in range(self.no_cols):
                value = self._evaluate_cell(row, column, set())
                values.append(str(value).replace("\n", "\\n"))
            rows.append(values)

        widths = [
            max(len(headers[column]), *(len(row[column]) for row in rows))
            if rows
            else len(headers[column])
            for column in range(len(headers))
        ]

        def border() -> str:
            return border_style + "+" + "+".join("-" * (width + 2) for width in widths) + "+" + reset

        def format_row(
            values: list[str],
            style: str | None = None,
            data_row: int | None = None,
        ) -> str:
            cells = []
            for column, value in enumerate(values):
                alignment = ">" if data_row is not None and column == 0 else "^"
                padded = f" {value:{alignment}{widths[column]}} "
                cell_style = style
                if data_row is None and column == 0:
                    cell_style = None
                if data_row is not None:
                    if column == 0:
                        cell_style = index_style
                    else:
                        cell_style = cell_styles[(column - 1) % 2]
                        if (data_row, column - 1) in self._formulas:
                            cell_style = formula_styles[(column - 1) % 2]
                cells.append(f"{cell_style}{padded}{reset}" if cell_style else padded)
            return border_style + "|" + "|".join(cells) + "|" + reset

        lines = [border(), format_row(headers, header_style), border()]
        for row_index, values in enumerate(rows):
            lines.append(format_row(values, index_style, row_index))
        if rows:
            lines.append(border())
        return "\n".join(lines)

    def display(self) -> None:
        print(self)

    def __len__(self):
        return self.no_rows

    def __iter__(self):
        return iter(self.df.columns)

    def __getitem__(self, key):
        if isinstance(key, tuple):
            if len(key) != 2:
                raise TypeError("Spreadsheet indices must be 2-item tuples in the form (row, column).")
            row, column = key
            return self.get_cell(row, column)

        if isinstance(key, slice):
            return self.df.iloc[:, key]

        if isinstance(key, str):
            range_match = self._RANGE_REFERENCE.fullmatch(key)
            if range_match:
                row_start, row_end, col_start, col_end = self._parse_range(range_match)
                return self._get_range(row_start, row_end, col_start, col_end)

            if self._CELL_REFERENCE.fullmatch(key):
                row, column = self._parse_cell(key)
                return self._evaluate_cell(row, column, set())

            column_name = key.upper()
            if column_name not in self.df.columns:
                raise KeyError(f"Column or cell {key!r} does not exist in this spreadsheet.")
            return Vector(self.df[column_name].tolist())

        if isinstance(key, int):
            if 0 <= key < self.no_cols:
                return Vector(self.df.iloc[:, key].tolist())
            if 1 <= key <= self.no_cols:
                return Vector(self.df.iloc[:, key - 1].tolist())

        raise KeyError(f"Column {key!r} does not exist in this spreadsheet.")

    def __setitem__(self, key, value):
        if isinstance(key, tuple):
            if len(key) != 2:
                raise TypeError("Spreadsheet indices must be 2-item tuples in the form (row, column).")
            row, column = key
            self.set_cell(row, column, value)
            return

        if isinstance(key, str):
            range_match = self._RANGE_REFERENCE.fullmatch(key)
            if range_match:
                row_start, row_end, col_start, col_end = self._parse_range(range_match)
                self._set_range(row_start, row_end, col_start, col_end, value)
                return

            if self._CELL_REFERENCE.fullmatch(key):
                row, column = self._parse_cell(key)
                if isinstance(value, str) and value.lstrip().startswith("="):
                    self.setformula(key, value)
                    return
                self.set_cell(row, column, value)
                return

            self.df[key.upper()] = value
            return

        if isinstance(key, int):
            if 0 <= key < self.no_cols:
                self.df.iloc[:, key] = value
                return
            if 1 <= key <= self.no_cols:
                self.df.iloc[:, key - 1] = value
                return

        raise KeyError(f"Column {key!r} does not exist in this spreadsheet.")

    def _normalize_row(self, row: int) -> int:
        if not isinstance(row, int):
            raise TypeError("Row indices must be integers.")
        if row < 0 or row >= self.no_rows:
            raise IndexError("Row index out of range.")
        return row

    def _normalize_column(self, column) -> str:
        if isinstance(column, int):
            if 0 <= column < self.no_cols:
                return self.df.columns[column]
            if 1 <= column <= self.no_cols:
                return self.df.columns[column - 1]
            raise IndexError("Column index out of range.")

        if isinstance(column, str):
            normalized = column.upper()
            if normalized not in self.df.columns:
                raise KeyError(f"Column {column!r} does not exist.")
            return normalized

        raise TypeError("Column identifiers must be integers or strings.")

    def get_cell(self, row: int, column) -> object:
        row_index = self._normalize_row(row)
        column_name = self._normalize_column(column)
        return self.df.at[row_index, column_name]

    def set_cell(self, row: int, column, value) -> None:
        row_index = self._normalize_row(row)
        column_name = self._normalize_column(column)
        self.df.at[row_index, column_name] = value
        column_index = self.df.columns.tolist().index(column_name)
        self._formulas.pop((row_index, column_index), None)

    def setformula(self, cell: str, formula: str) -> None:
        """Set a formula such as '=SUM(A1:B4)' in a cell such as 'C1'."""
        if not isinstance(cell, str) or not self._CELL_REFERENCE.fullmatch(cell):
            raise ValueError("Formula target must be a cell address such as 'A1'.")
        if not isinstance(formula, str):
            raise TypeError("Formula must be a string.")

        row, column = self._parse_cell(cell)
        key = (row, column)
        previous_formula = self._formulas.get(key)
        self._formulas[key] = formula.lstrip()
        try:
            self._evaluate_cell(*key, evaluating=set())
        except Exception:
            if previous_formula is None:
                del self._formulas[key]
            else:
                self._formulas[key] = previous_formula
            raise

    def set_formula(self, cell: str, formula: str) -> None:
        self.setformula(cell, formula)

    def _parse_cell(self, address: str) -> tuple[int, int]:
        match = self._CELL_REFERENCE.fullmatch(address)
        if match is None:
            raise ValueError(f"Invalid cell address: {address!r}.")
        letters, row_number = match.groups()
        column_number = 0
        for letter in letters.upper():
            column_number = column_number * 26 + ord(letter) - ord("A") + 1
        row, column = int(row_number) - 1, column_number - 1
        self._normalize_row(row)
        if column >= self.no_cols:
            raise IndexError("Column index out of range.")
        return row, column

    def _parse_range(self, match: re.Match) -> tuple[int, int, int, int]:
        first_row, first_column = self._parse_cell(match.group(1) + match.group(2))
        last_row, last_column = self._parse_cell(match.group(3) + match.group(4))
        if first_row > last_row or first_column > last_column:
            raise ValueError("Range start must be above and to the left of its end.")
        return first_row, last_row, first_column, last_column

    def _get_range(self, row_start: int, row_end: int, col_start: int, col_end: int) -> pd.DataFrame:
        return pd.DataFrame(
            [
                [
                    self._evaluate_cell(row, column, set())
                    for column in range(col_start, col_end + 1)
                ]
                for row in range(row_start, row_end + 1)
            ],
            index=range(row_start, row_end + 1),
            columns=self.df.columns[col_start : col_end + 1],
        )

    def _set_range(self, row_start: int, row_end: int, col_start: int, col_end: int, value) -> None:
        rows = row_end - row_start + 1
        columns = col_end - col_start + 1
        if rows == columns == 1:
            self.set_cell(row_start, col_start, value)
            return
        values = value.to_numpy() if isinstance(value, pd.DataFrame) else value
        target = self.df.iloc[row_start : row_end + 1, col_start : col_end + 1]
        target.iloc[:, :] = values
        for row in range(row_start, row_end + 1):
            for column in range(col_start, col_end + 1):
                self._formulas.pop((row, column), None)

    def _evaluate_cell(self, row: int, column: int, evaluating: set[tuple[int, int]]) -> Any:
        key = (row, column)
        if key not in self._formulas:
            return self.df.iat[row, column]
        if key in evaluating:
            address = f"{self.number_to_excel_column(column + 1)}{row + 1}"
            raise ValueError(f"Circular formula reference at {address}.")

        evaluating.add(key)
        try:
            formula = self._formulas[key]
            expression = formula[1:] if formula.startswith("=") else formula
            expression = self._FORMULA_RANGE.sub(
                lambda match: (
                    f'RANGE("{match.group(1)}{match.group(2)}",'
                    f'"{match.group(3)}{match.group(4)}")'
                ),
                expression,
            )
            expression = self._FORMULA_CELL.sub(
                lambda match: f"{match.group(1).upper()}{match.group(2)}",
                expression,
            )
            try:
                tree = ast.parse(expression, mode="eval")
            except SyntaxError as exc:
                raise ValueError(f"Invalid formula: {formula!r}.") from exc
            return self._evaluate_expression(tree.body, evaluating)
        finally:
            evaluating.remove(key)

    def _evaluate_expression(self, node: ast.AST, evaluating: set[tuple[int, int]]):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str)):
            return node.value
        if isinstance(node, ast.Name):
            if not self._CELL_REFERENCE.fullmatch(node.id):
                raise ValueError(f"Unknown name in formula: {node.id!r}.")
            row, column = self._parse_cell(node.id)
            return self._evaluate_cell(row, column, evaluating)
        if isinstance(node, ast.BinOp) and type(node.op) in self._BINARY_OPERATORS:
            left = self._evaluate_expression(node.left, evaluating)
            right = self._evaluate_expression(node.right, evaluating)
            return self._BINARY_OPERATORS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in self._UNARY_OPERATORS:
            value = self._evaluate_expression(node.operand, evaluating)
            return self._UNARY_OPERATORS[type(node.op)](value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            function = node.func.id.upper()
            if function == "RANGE" and len(node.args) == 2:
                start = self._evaluate_expression(node.args[0], evaluating)
                end = self._evaluate_expression(node.args[1], evaluating)
                match = self._RANGE_REFERENCE.fullmatch(f"{start}:{end}")
                if match is None:
                    raise ValueError("Invalid range in formula.")
                row_start, row_end, col_start, col_end = self._parse_range(match)
                return [
                    self._evaluate_cell(row, column, evaluating)
                    for row in range(row_start, row_end + 1)
                    for column in range(col_start, col_end + 1)
                ]
            values = [self._evaluate_expression(arg, evaluating) for arg in node.args]
            values = [item for value in values for item in (value if isinstance(value, list) else [value])]
            functions = {
                "SUM": sum,
                "AVERAGE": lambda items: sum(items) / len(items),
                "MIN": min,
                "MAX": max,
                "COUNT": lambda items: sum(isinstance(item, (int, float)) for item in items),
                "ABS": lambda items: abs(items[0]),
                "ROUND": lambda items: round(*items),
            }
            if function not in functions:
                raise ValueError(f"Unsupported formula function: {function}.")
            try:
                return functions[function](values)
            except (TypeError, ZeroDivisionError) as exc:
                raise ValueError(f"Invalid arguments to {function}.") from exc
        raise ValueError("Formula contains an unsupported expression.")

    def row(self, row_index: int) -> "Vector":
        return Vector(self.df.iloc[row_index].tolist())

    def column(self, column: int | str) -> "Vector":
        column_name = self._normalize_column(column)
        return Vector(self.df[column_name].tolist())

    def to_dataframe(self) -> pd.DataFrame:
        result = self.df.copy()
        for (row, column) in self._formulas:
            result.iat[row, column] = self._evaluate_cell(row, column, set())
        return result


class Vector:
    def __init__(self, *iterable):
        if len(iterable) == 1 and isinstance(iterable[0], Iterable) and not isinstance(iterable[0], (str, bytes)):
            values = list(iterable[0])
        elif len(iterable) == 1 and not isinstance(iterable[0], Iterable):
            values = [iterable[0]]
        else:
            values = list(iterable)

        self.iterable = pd.Series(values)

    def __iter__(self):
        return iter(self.iterable)

    def __len__(self):
        return len(self.iterable)

    def __repr__(self):
        return f"Vector({self.iterable.tolist()!r})"

    def __str__(self):
        items = ", ".join(repr(value) for value in self.iterable)
        return f"[ {items} ]"

    def __getitem__(self, key):
        if isinstance(key, slice):
            return Vector(self.iterable.iloc[key].tolist())
        if isinstance(key, int):
            return self.iterable.iloc[key]
        return self.iterable[key]

    def __setitem__(self, key: int | str | slice, value: Any) -> None:
        if isinstance(key, int):
            self.iterable.iloc[key] = value
            return
        self.iterable[key] = value

    def __eq__(self, other):
        if isinstance(other, Vector):
            return self.iterable.equals(other.iterable)
        return self.iterable.equals(pd.Series(other))

    def __add__(self, other):
        if isinstance(other, Vector):
            other_values = other.iterable
        else:
            other_values = pd.Series(other)
        return Vector((self.iterable + other_values).tolist())

    def __radd__(self, other):
        return self.__add__(other)

    def __sub__(self, other):
        if isinstance(other, Vector):
            other_values = other.iterable
        else:
            other_values = pd.Series(other)
        return Vector((self.iterable - other_values).tolist())

    def __mul__(self, other):
        if isinstance(other, Vector):
            other_values = other.iterable
        else:
            other_values = pd.Series(other)
        return Vector((self.iterable * other_values).tolist())

    def to_list(self):
        return self.iterable.tolist()


if __name__ == "__main__":
    sheet = Spreadsheet(5, 3)
    v = sheet[0]
    print(sheet)
    print(v)
    (sheet.set_formula("A1", "B1"))
    sheet["B1"] = "Hello"
    print(sheet["A1"])
