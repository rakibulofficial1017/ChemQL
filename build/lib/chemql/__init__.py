import argparse
import ast
import atexit
import builtins
import contextlib
from enum import Enum, auto
from fractions import Fraction
from functools import reduce
import inspect
import io
import importlib
import json
import math
from math import gcd
import os
import operator
from pathlib import Path
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.styles import Style
from prompt_toolkit.completion import Completer, Completion
import queue
import re
import shlex
import subprocess
import sys
import select
import time
import threading
import uuid
import urllib.parse
import urllib.request
import urllib.error


__all__ = [
    "ChemQLError",
    "ChemQLBuiltinError",
    "TooFewArguments",
    "TooManyArguments",
    "InvalidArgumentType",
    "InvalidArgumentValue",
    "FileReadError",
    "FileWriteError",
    "Element",
    "Molecule",
    "Reaction",
    "MOLECULES",
    "REACTIONS",
    "find_molecule",
    "find_reaction",
    "search_reactions",
    "ReturnTable",
    "Unknown",
    "balance_stoichiometry",
    "execute_query",
    "execute_query_text",
    "ChemQLQuery",
    "search",
    "union",
    "intersection",
    "__version__"
]

__version__ = "1.5.0"

# Persistent preprocessor/function state for the current ChemQL session.
DEFINITIONS = {}
FUNCTIONS = {}
MACROS = {}
EXECUTION_HISTORY = []
_DEFINITION_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_NO_RETURN = object()
NO_ANSI = True

def _expand_definitions(line):
    """Replace @NAME literally, including inside strings, using current definitions."""
    if not DEFINITIONS:
        return line
    pattern = re.compile(r"@(" + _DEFINITION_NAME + r")")
    # One substitution pass only: replacement text is not recursively expanded.
    return pattern.sub(lambda match: DEFINITIONS.get(match.group(1), match.group(0)), line)

def _split_function_arguments(source):
    """Split comma-separated arguments while respecting nested delimiters and strings."""
    args, start = [], 0
    quote = None
    escaped = False
    round_depth = square_depth = curly_depth = double_curly_depth = 0
    i = 0
    while i < len(source):
        ch = source[i]
        if quote is not None:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
        elif source.startswith("{{", i):
            double_curly_depth += 1
            i += 2
            continue
        elif source.startswith("}}", i) and double_curly_depth:
            double_curly_depth -= 1
            i += 2
            continue
        elif not double_curly_depth:
            if ch == "(": round_depth += 1
            elif ch == ")": round_depth = max(0, round_depth - 1)
            elif ch == "[": square_depth += 1
            elif ch == "]": square_depth = max(0, square_depth - 1)
            elif ch == "{": curly_depth += 1
            elif ch == "}": curly_depth = max(0, curly_depth - 1)
            elif ch == "," and not (round_depth or square_depth or curly_depth):
                args.append(source[start:i].strip())
                start = i + 1
        i += 1
    tail = source[start:].strip()
    if tail or source.strip():
        args.append(tail)
    return args
def is_block_header(line):
    """Return True only for actual ChemQL block headers."""
    if not (line.startswith("[") and line.endswith("]")):
        return False

    code = line[1:-1].strip()

    return (
        code.startswith("if ")
        or code.startswith("for ")
        or code.startswith("while ")
    )

class ChemQLBuiltinError(Exception):
    """Base class for errors raised by ChemQL's native built-ins."""

class TooFewArguments(ChemQLBuiltinError):
    pass

class TooManyArguments(ChemQLBuiltinError):
    pass

class InvalidArgumentType(ChemQLBuiltinError):
    pass

class InvalidArgumentValue(ChemQLBuiltinError):
    pass

class FileReadError(ChemQLBuiltinError):
    pass

class FileWriteError(ChemQLBuiltinError):
    pass


def _builtin_sum(*values):
    if len(values) == 1:
        return sum(values[0])
    return sum(values)


def _builtin_type(value):
    """Return a readable ChemQL type name."""
    if value is None: return "NoneType"
    if isinstance(value, bool): return "bool"
    if isinstance(value, int): return "int"
    if isinstance(value, float): return "float"
    if isinstance(value, str): return "str"
    if isinstance(value, list): return "list"
    if isinstance(value, tuple): return "tuple"
    if isinstance(value, dict): return "dict"
    return type(value).__name__


def _builtin_read_text(path, encoding="utf-8"):
    try:
        return Path(os.fspath(path)).read_text(encoding=encoding)
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise FileReadError(f"Cannot read text file {path!r}: {exc}") from exc


def _builtin_read_lines(path, encoding="utf-8"):
    return _builtin_read_text(path, encoding).splitlines()


def _builtin_read_json(path, encoding="utf-8"):
    try:
        with open(os.fspath(path), "r", encoding=encoding) as stream:
            return json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise FileReadError(f"Cannot read JSON file {path!r}: {exc}") from exc


def _builtin_read_csv(path, delimiter=",", encoding="utf-8", headers=True):
    import csv
    if not isinstance(delimiter, str) or len(delimiter) != 1:
        raise InvalidArgumentValue("read_csv delimiter must be a single character")
    if not isinstance(headers, bool):
        raise InvalidArgumentType("read_csv headers must be a boolean")
    try:
        with open(os.fspath(path), "r", newline="", encoding=encoding) as stream:
            if headers:
                return list(csv.DictReader(stream, delimiter=delimiter))
            return list(csv.reader(stream, delimiter=delimiter))
    except (OSError, UnicodeError, csv.Error, TypeError, ValueError) as exc:
        raise FileReadError(f"Cannot read CSV file {path!r}: {exc}") from exc


def _builtin_element(symbol, field="symbol"):
    if not isinstance(symbol, str):
        raise InvalidArgumentType("element expects an element symbol as its first argument")
    found = next((item for item in ELEMENTS if str(item.symbol).casefold() == symbol.casefold()), None)
    if found is None:
        raise InvalidArgumentValue(f"Unknown element symbol {symbol!r}")
    if not isinstance(field, str):
        raise InvalidArgumentType("element field must be a string")
    if not hasattr(found, field) or field.startswith("_"):
        raise InvalidArgumentValue(f"Unknown element field {field!r}")
    return getattr(found, field)


def _builtin_count_atoms(formula, symbol):
    if not isinstance(formula, str) or not isinstance(symbol, str):
        raise InvalidArgumentType("count_atoms expects a formula string and an element symbol")
    try:
        return _formula_counts(formula).get(symbol, 0)
    except ValueError as exc:
        raise InvalidArgumentValue(str(exc)) from exc


def _builtin_molar_mass(formula):
    if not isinstance(formula, str):
        raise InvalidArgumentType("molar_mass expects a chemical formula string")
    try:
        counts = _formula_counts(formula)
    except ValueError as exc:
        raise InvalidArgumentValue(str(exc)) from exc
    masses = {str(item.symbol): item.atomic_mass for item in ELEMENTS}
    total = 0.0
    for symbol, count in counts.items():
        try:
            mass = float(masses[symbol])
        except (KeyError, TypeError, ValueError):
            raise InvalidArgumentValue(f"No atomic mass is available for element {symbol!r}")
        total += mass * count
    return total


def _builtin_empirical_formula(formula):
    if not isinstance(formula, str):
        raise InvalidArgumentType("empirical_formula expects a chemical formula string")
    try:
        counts = _formula_counts(formula)
    except ValueError as exc:
        raise InvalidArgumentValue(str(exc)) from exc
    divisor = reduce(gcd, counts.values())
    return "".join(symbol + (str(count // divisor) if count // divisor != 1 else "")
                   for symbol, count in counts.items())


def _builtin_write_csv(path, rows, delimiter=",", encoding="utf-8"):
    import csv
    if not isinstance(delimiter, str) or len(delimiter) != 1:
        raise InvalidArgumentValue("write_csv delimiter must be a single character")
    try:
        with open(os.fspath(path), "w", newline="", encoding=encoding) as stream:
            if not isinstance(rows, (list, tuple)):
                raise InvalidArgumentType("write_csv rows must be a list")
            if rows and isinstance(rows[0], dict):
                fieldnames = list(rows[0].keys())
                writer = csv.DictWriter(stream, fieldnames=fieldnames, delimiter=delimiter)
                writer.writeheader()
                writer.writerows(rows)
            else:
                writer = csv.writer(stream, delimiter=delimiter)
                writer.writerows(rows)
        return True
    except ChemQLBuiltinError:
        raise
    except (OSError, UnicodeError, csv.Error, TypeError, ValueError) as exc:
        raise FileWriteError(f"Cannot write CSV file {path!r}: {exc}") from exc


def _builtin_file_exists(path):
    try:
        return Path(os.fspath(path)).is_file()
    except (TypeError, ValueError):
        raise InvalidArgumentType("file_exists expects a path string")


def _builtin_list_files(path=".", pattern="*"):
    try:
        return sorted(str(p) for p in Path(os.fspath(path)).glob(str(pattern)))
    except (OSError, TypeError, ValueError) as exc:
        raise InvalidArgumentValue(f"Cannot list files: {exc}") from exc


def _builtin_write_text(path, content, encoding="utf-8"):
    try:
        Path(os.fspath(path)).write_text(str(content), encoding=encoding)
        return True
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise FileWriteError(f"Cannot write text file {path!r}: {exc}") from exc


def _builtin_write_json(path, value, encoding="utf-8", indent=2):
    try:
        with open(os.fspath(path), "w", encoding=encoding) as stream:
            json.dump(value, stream, ensure_ascii=False, indent=indent)
        return True
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise FileWriteError(f"Cannot write JSON file {path!r}: {exc}") from exc


# name: (callable, minimum positional arguments, maximum positional arguments)
# Built-ins are native Python-backed operations; user-defined ChemQL functions
# retain precedence when a name is defined in FUNCTIONS.
BUILTIN_FUNCTIONS = {
    "abs": (abs, 1, 1),
    "round": (round, 1, 2),
    "min": (min, 1, None),
    "max": (max, 1, None),
    "sum": (_builtin_sum, 1, None),
    "len": (len, 1, 1),
    "type": (_builtin_type, 1, 1),
    "str": (str, 1, 1),
    "int": (int, 1, 2),
    "float": (float, 1, 1),
    "bool": (bool, 1, 1),
    "upper": (lambda value: str(value).upper(), 1, 1),
    "lower": (lambda value: str(value).lower(), 1, 1),
    "contains": (lambda container, item: item in container, 2, 2),
    "replace": (lambda value, old, new: str(value).replace(str(old), str(new)), 3, 3),
    "split": (lambda value, separator=None: str(value).split(separator), 1, 2),
    "join": (lambda separator, values: str(separator).join(str(v) for v in values), 2, 2),
    "first": (lambda values: next(iter(values)), 1, 1),
    "last": (lambda values: list(values)[-1], 1, 1),
    "unique": (lambda *values: list(dict.fromkeys(values[0] if len(values) == 1 and isinstance(values[0], (list, tuple, str)) else values)), 1, None),
    "sort": (lambda values: sorted(values), 1, 1),
    "reversed": (lambda values: list(reversed(values)), 1, 1),
    "read_text": (_builtin_read_text, 1, 2),
    "read_lines": (_builtin_read_lines, 1, 2),
    "read_json": (_builtin_read_json, 1, 2),
    "read_csv": (_builtin_read_csv, 1, 4),
    "file_exists": (_builtin_file_exists, 1, 1),
    "element": (_builtin_element, 1, 2),
    "count_atoms": (_builtin_count_atoms, 2, 2),
    "molar_mass": (_builtin_molar_mass, 1, 1),
    "empirical_formula": (_builtin_empirical_formula, 1, 1),
    "write_csv": (_builtin_write_csv, 2, 4),
    "list_files": (_builtin_list_files, 0, 2),
    "write_text": (_builtin_write_text, 2, 3),
    "write_json": (_builtin_write_json, 2, 4),
    "help": (lambda *args: None, 0, 1),
}


# User-facing documentation for built-ins. Keep examples in ChemQL syntax.
_BUILTIN_HELP = {
    "help": ("Help", "help{topic?}", "Show the help index or detailed documentation for a built-in, syntax topic, error signal, or file/chemistry category.", ['help', 'help{read_csv}', 'help{errors}']),
    "abs": ("Numbers", "abs{number}", "Return the absolute value.", ['abs{-15}  # 15']),
    "round": ("Numbers", "round{number, digits?}", "Round a number to the requested number of decimal places.", ['round{3.14159, 2}  # 3.14']),
    "min": ("Numbers", "min{value, ...}", "Return the smallest supplied value.", ['min{4, 2, 9}  # 2']),
    "max": ("Numbers", "max{value, ...}", "Return the largest supplied value.", ['max{4, 2, 9}  # 9']),
    "sum": ("Numbers", "sum{value, ...}", "Add numeric values or sum an iterable.", ['sum{1, 2, 3, 4}  # 10']),
    "len": ("Core", "len{value}", "Return the number of items in a string or collection.", ['len{"Hello world"}  # 11']),
    "type": ("Core", "type{value}", "Return a readable ChemQL/Python type name.", ['type{42}']),
    "str": ("Conversion", "str{value}", "Convert a value to text.", ['str{42}  # "42"']),
    "int": ("Conversion", "int{value, base?}", "Convert a value to an integer.", ['int{"101", 2}  # 5']),
    "float": ("Conversion", "float{value}", "Convert a value to a floating-point number.", ['float{"3.5"}']),
    "bool": ("Conversion", "bool{value}", "Convert a value to a Boolean.", ['bool{0}  # False']),
    "upper": ("Strings", "upper{text}", "Return text converted to uppercase.", ['upper{"chemql"}  # CHEMQL']),
    "lower": ("Strings", "lower{text}", "Return text converted to lowercase.", ['lower{"CHEMQL"}  # chemql']),
    "contains": ("Strings / Collections", "contains{container, item}", "Return whether a string or collection contains an item.", ['contains{"ChemQL", "QL"}  # True']),
    "replace": ("Strings", "replace{text, old, new}", "Replace every occurrence of one substring with another.", ['replace{"H2O", "2", "4"}  # H4O']),
    "split": ("Strings", "split{text, separator?}", "Split text into a list of pieces.", ['split{"red,green,blue", ","}']),
    "join": ("Strings", "join{separator, values}", "Join an iterable of values into a string.", ['join{",", ["a", "b", "c"]}']),
    "first": ("Collections", "first{values}", "Return the first item of an iterable.", ['first{[10, 20, 30]}  # 10']),
    "last": ("Collections", "last{values}", "Return the last item of an iterable.", ['last{[10, 20, 30]}  # 30']),
    "unique": ("Collections", "unique{values...}", "Return unique values while preserving their first-seen order.", ['unique{1, 2, 2, 3}  # [1, 2, 3]']),
    "sort": ("Collections", "sort{values}", "Return a sorted list.", ['sort{[3, 1, 2]}  # [1, 2, 3]']),
    "reversed": ("Collections", "reversed{values}", "Return the values in reverse order as a list.", ['reversed{[1, 2, 3]}  # [3, 2, 1]']),
    "read_text": ("Files", "read_text{path, encoding?}", "Read an entire text file. Defaults to UTF-8.", ['let text = read_text{"notes.txt"}']),
    "read_lines": ("Files", "read_lines{path, encoding?}", "Read a text file into a list of lines.", ['let lines = read_lines{"notes.txt"}']),
    "write_text": ("Files", "write_text{path, content, encoding?}", "Write text to a file. Returns true on success.", ['write_text{"output.txt", "Hello ChemQL!"}']),
    "read_csv": ("Files / Data", "read_csv{path, delimiter?, encoding?, header?}", "Read a CSV file. By default, the first row is treated as column names and rows are returned as dictionaries. Set header to false for row lists.", ['let rows = read_csv{"data.csv"}', 'let rows = read_csv{"data.csv", ";", "utf-8", false}']),
    "write_csv": ("Files / Data", "write_csv{path, rows, delimiter?, encoding?}", "Write rows to a CSV file.", ['write_csv{"output.csv", rows}']),
    "read_json": ("Files / Data", "read_json{path, encoding?}", "Read JSON from a file into ChemQL dictionaries/lists/scalars.", ['let data = read_json{"data.json"}']),
    "write_json": ("Files / Data", "write_json{path, value, encoding?, indent?}", "Write a value as JSON. Indentation defaults to 2 spaces.", ['write_json{"output.json", data}']),
    "file_exists": ("Files", "file_exists{path}", "Return true if a file or path exists.", ['file_exists{"data.csv"}']),
    "list_files": ("Files", "list_files{directory?, pattern?}", "List files in a directory, optionally matching a glob pattern.", ['list_files{".", "*.csv"}']),
    "element": ("Chemistry", "element{symbol, field?}", "Look up a periodic-table element, optionally returning one field.", ['element{"Na", "atomic_mass"}']),
    "count_atoms": ("Chemistry", "count_atoms{formula, element_symbol}", "Count atoms of an element in a chemical formula.", ['count_atoms{"H2SO4", "O"}  # 4']),
    "molar_mass": ("Chemistry", "molar_mass{formula}", "Calculate the molar mass of a chemical formula.", ['molar_mass{"H2O"}']),
    "empirical_formula": ("Chemistry", "empirical_formula{formula}", "Calculate the empirical formula from a molecular formula.", ['empirical_formula{"C6H12O6"}  # CH2O']),
}

_HELP_TOPICS = {
    "syntax": ("ChemQL Syntax", ["Function calls use braces: `name{arg1, arg2}`.", "Quote text containing spaces: `upper{\"hello world\"}`.", "Separate arguments with commas, not spaces.", "Python statements/expressions can be embedded in `[ ... ]`.", "Multiline Python uses `[[[ ... ]]]`; embedded queries use `{{ ... }}`.", "Enums use `enum Name`, member declarations, and `endenum`; omitted values are generated automatically.", "Structs and records may use `from Base`; structs inherit from structs, records, or Python classes, while records inherit only from records."]),
    "errors": ("ChemQL Error Signals", ["SyntaxError — the input could not be parsed as valid syntax.", "TooFewArguments — a function received fewer arguments than required.", "TooManyArguments — a function received more arguments than allowed.", "InvalidArgumentType — an argument has an unsupported type.", "InvalidArgumentValue — an argument's value is invalid.", "FileReadError — reading a file failed.", "FileWriteError — writing a file failed.", "NameError — a name or function is unknown.", "PermissionError — a private namespace function was called externally."]),
    "files": ("File Functions", ["read_text{path, encoding?}", "read_lines{path, encoding?}", "read_csv{path, delimiter?, encoding?, header?}", "read_json{path, encoding?}", "write_text{path, content, encoding?}", "write_csv{path, rows, delimiter?, encoding?}", "write_json{path, value, encoding?, indent?}", "file_exists{path}", "list_files{directory?, pattern?}"]),
    "chemistry": ("Chemistry Functions", ["molar_mass{formula}", "count_atoms{formula, element_symbol}", "empirical_formula{formula}", "element{symbol, field?}"]),
}

_STDLIB_HELP = {
    "math": (
        "Mathematical constants and numeric functions.",
        [
            "PI, E, TAU — Common mathematical constants.",
            "sqrt{number}, cbrt{number}, abs{number}, floor{number}, ceil{number}, factorial{integer}",
            "gcd{integer, ...}, lcm{integer, ...}, hypot{number, ...}, pow{x, y}",
            "sin{radians}, cos{radians}, tan{radians}, asin{x}, acos{x}, atan{x}, atan2{y, x}",
            "log{x}, log10{x}, log2{x}, exp{x}, degrees{radians}, radians{degrees}",
            "isfinite{x}, isinf{x}, isnan{x}, isclose{x, y}",
            "Example: math::sqrt{81}  # 9.0",
        ],
    ),
    "math::statistics": (
        "Descriptive statistics for numeric data.",
        [
            "mean{values...}, median{values...}, median_low{values...}, median_high{values...}",
            "mode{values...}, multimode{values...}, quantiles{values...}",
            "variance{values...}, stdev{values...}, pvariance{values...}, pstdev{values...}",
            "harmonic_mean{values...}, geometric_mean{values...}",
            "Example: math::statistics::mean{2, 4, 6}  # 4",
        ],
    ),
    "text": (
        "String transformations, searching, splitting, and regular expressions.",
        [
            "upper{text}, lower{text}, title{text}, capitalize{text}, casefold{text}",
            "strip{text, chars?}, lstrip{text}, rstrip{text}, reverse{text}",
            "startswith{text, prefix}, endswith{text, suffix}, replace{text, old, new}",
            "split{text, separator?}, join{separator, values...}, count{text, substring}, find{text, substring}",
            "isalpha{text}, isdigit{text}, isalnum{text}, isspace{text}",
            "regex_search{pattern, text}, regex_findall{pattern, text}, regex_replace{pattern, replacement, text}",
            'Example: text::upper{"hello"}  # HELLO',
        ],
    ),
    "collections": (
        "Collection helpers for sequences and iterables.",
        [
            "unique{values...}, flatten{groups...}, zip{values...}, pairwise{values...}",
            "frequencies{values...}, group_count{values...}, product{numbers...}",
            "sorted{values...}, reversed{values...}",
            'Example: collections::frequencies{"red", "blue", "red"}',
        ],
    ),
    "datetime": (
        "Date and time values, ISO parsing, timestamps, and date arithmetic.",
        [
            "today{}, now{}, utcnow{}",
            "date{year, month, day}, time{hour, minute?, second?, microsecond?}",
            "timestamp{iso_datetime}, from_timestamp{seconds}, weekday{iso_date}",
            "date_add_days{iso_date, days}, date_difference_days{date1, date2}",
            'Example: datetime::date_add_days{"2026-10-20", 7}',
        ],
    ),
    "json": (
        "JSON serialization, parsing, and decoded value type inspection.",
        [
            "dumps{value}, dumps_pretty{value}, loads{json_text}, json_type{json_text}",
            'Example: json::loads{"{\\"formula\\": \\"H2O\\"}"}',
        ],
    ),
    "random": (
        "Pseudo-random values and sequence sampling using Python's random module.",
        [
            "seed{value}, random{}, randint{minimum, maximum}, randrange{stop} or randrange{start, stop, step}",
            "choice{values}, sample{values, count}, shuffle{values}, uniform{minimum, maximum}",
            "Use seed{value} when repeatable pseudo-random output is required.",
            "Example: random::randint{1, 6}",
        ],
    ),
    "decimal": (
        "Base-10 decimal arithmetic, useful when decimal rounding matters.",
        [
            "create{value}, add{x, y}, subtract{x, y}, multiply{x, y}, divide{x, y}",
            "quantize{value, quantum}, to_string{value}",
            'Pass decimal values as strings for exact input, e.g. decimal::add{"0.1", "0.2"}.',
        ],
    ),
    "fractions": (
        "Rational arithmetic using reduced fractions.",
        [
            "create{value} or create{numerator, denominator}",
            "add{x, y}, subtract{x, y}, multiply{x, y}, divide{x, y}",
            "numerator{value}, denominator{value}, to_float{value}",
            "Example: fractions::create{1, 3}",
        ],
    ),
    "pathlib": (
        "Path inspection and UTF-8 text file operations using pathlib.",
        [
            "name{path}, stem{path}, suffix{path}, parent{path}, join{path, part...}",
            "exists{path}, is_file{path}, is_dir{path}",
            "read_text{path, encoding?}, write_text{path, content, encoding?}",
            "File reads and writes operate with the current process permissions.",
        ],
    ),
}


def _help_text(topic=None):
    if topic is None or not str(topic).strip():
        names = sorted(_BUILTIN_HELP)
        categories = {}
        for name in names:
            category = _BUILTIN_HELP[name][0]
            categories.setdefault(category, []).append(name)
        lines = [f"ChemQL {__version__} help", "", "Usage: help{topic} or help topic", "Use help{function_name} for details, or help{syntax}, help{errors}, help{files}, help{chemistry}, help{stdlib}.", ""]
        for category, items in categories.items():
            lines.append(f"{category}: " + ", ".join(items))
        lines += ["", "User-defined functions:"]
        lines += [f"  {name}{{...}}" for name in sorted(FUNCTIONS)] or ["  (none defined in this session)"]
        lines += ["", "Packages: load package_name; then use package_name::function{...}."]
        lines += ["Standard library: " + ", ".join(_STDLIB_HELP)]
        return "\n".join(lines)

    key = str(topic).strip().strip("`\"'")
    if key == "stdlib":
        return "\n".join([
            "ChemQL Standard Library",
            "Load a package with `load package_name`, then call `package_name::function{...}`.",
            "Get module details with `help{module}` and function details with `help{module::function}`.",
            "",
            *[f"{name} — {details[0]}" for name, details in _STDLIB_HELP.items()],
        ])
    resolved_key = _resolve_package_qualified_name(key)
    if resolved_key in _STDLIB_HELP:
        description, entries = _STDLIB_HELP[resolved_key]
        return "\n".join([
            f"{resolved_key} — Standard library",
            description,
            f"Load with: load {resolved_key}",
            "Functions and constants:",
            *[f"  {entry}" for entry in entries],
        ])
    if key in _BUILTIN_HELP:
        category, signature, description, examples = _BUILTIN_HELP[key]
        return "\n".join([f"{key} — {category}", f"Signature: {signature}", description, "", "Examples:", *[f"  {line}" for line in examples]])
    if key in _HELP_TOPICS:
        title, lines = _HELP_TOPICS[key]
        return "\n".join([title, *[f"  {line}" for line in lines]])
    if key in FUNCTIONS:
        return f"User-defined ChemQL function: {key}{{...}}\nDefined in the current session. Use `view`/`dump` where appropriate to inspect program state."
    if "::" in key:
        package, _, member = resolved_key.rpartition("::")
        if package in _STDLIB_HELP:
            _, entries = _STDLIB_HELP[package]
            match = next((entry for entry in entries if entry.split("{", 1)[0].endswith(member)), None)
            if match:
                return f"{package}::{member} — Standard library\n{match}"
        if resolved_key in FUNCTIONS:
            return f"ChemQL package function: {key}{{...}}\nCanonical name: {resolved_key}"
        return f"Package/member help is not registered for `{key}`.\nTry `load {package}` and inspect the package namespace, or use `help{{{package}}}` if documented."
    return f"No help available for `{key}`. Try `help` to list built-ins, `help{{stdlib}}` for standard-library packages, or `help{{syntax}}`, `help{{errors}}`, `help{{files}}`, and `help{{chemistry}}`."


def _call_builtin(name, arguments):
    entry = BUILTIN_FUNCTIONS.get(name)
    if entry is None:
        raise NameError(f"Unknown ChemQL built-in `{name}`")
    function, minimum, maximum = entry
    count = len(arguments)
    if count < minimum:
        raise TooFewArguments(f"Too few arguments for `{name}`: expected at least {minimum}, got {count}")
    if maximum is not None and count > maximum:
        raise TooManyArguments(f"Too many arguments for `{name}`: expected at most {maximum}, got {count}")
    if name == "help":
        if len(arguments) > 1:
            raise TooManyArguments("Too many arguments for `help`: expected at most 1, got " + str(len(arguments)))
        topic = arguments[0].strip() if arguments else None
        if topic is not None and len(topic) >= 2 and topic[0] in ("\"", "'") and topic[-1] == topic[0]:
            try:
                topic = ast.literal_eval(topic)
            except (ValueError, SyntaxError):
                topic = topic[1:-1]
        return _help_text(topic)
    values = [evaluate_python(arg) for arg in arguments]
    try:
        return function(*values)
    except ChemQLBuiltinError:
        raise
    except TypeError as exc:
        raise InvalidArgumentType(f"Invalid argument type for `{name}`: {exc}") from exc
    except ValueError as exc:
        raise InvalidArgumentValue(f"Invalid argument value for `{name}`: {exc}") from exc
    except IndexError as exc:
        raise InvalidArgumentValue(f"Invalid argument value for `{name}`: {exc}") from exc


def _call_function(name, arguments):
    """Call a ChemQL function, including let assignments and block syntax."""
    global _CURRENT_NAMESPACE
    if name not in FUNCTIONS:
        raise NameError(f"Unknown ChemQL function `{name}`")

    values = [evaluate_python(arg) for arg in arguments]
    definition = FUNCTIONS[name]

    # While a namespace function runs, its private members are available to it
    # and to other functions in the same namespace, but not to external callers.
    previous_namespace = _CURRENT_NAMESPACE
    if "::" in name:
        _CURRENT_NAMESPACE = NAMESPACES.get(name.rsplit("::", 1)[0], previous_namespace)

    saved_globals = python_globals.copy()
    saved_chemql_variables = CHEMQL_VARIABLES.copy()

    # Namespace members shadow same-named globals only while a function in
    # that namespace executes. Never leak namespace variables into the caller's
    # global scope, and preserve private-member access for internal functions.
    active_namespace = _CURRENT_NAMESPACE
    if active_namespace is not None:
        for member_name in active_namespace._chemql_public: # type: ignore
            if member_name in active_namespace.__dict__:
                python_globals[member_name] = active_namespace.__dict__[member_name]
        python_globals.update(active_namespace._chemql_private) # type: ignore

    had_arguments = "arguments" in python_globals
    saved_arguments = python_globals.get("arguments")

    # Expose arguments through temporary names rather than repr().  ChemQL
    # structs display as `Fruit{...}`, which is not valid Python syntax; using
    # names also preserves object identity and supports lists/dicts/custom types.
    python_globals["arguments"] = list(values)
    parameter_names = []
    for value in values:
        parameter_name = "__chemql_func_arg_" + uuid.uuid4().hex
        python_globals[parameter_name] = value
        parameter_names.append(parameter_name)

    def substitute_parameters(source):
        """Replace \\1, \\2, etc. with safe names bound to the actual values."""
        return re.sub(
            r"\\(\d+)",
            lambda match: (
                parameter_names[int(match.group(1)) - 1]
                if 0 < int(match.group(1)) <= len(parameter_names)
                else match.group(0)
            ),
            source,
        )

    def normalize_let_line(source):
        """Translate let name = expression into a Python assignment."""
        match = re.fullmatch(
            r"\s*let\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*=\s*(.*?)\s*",
            source,
        )

        if not match:
            return source

        variable, expression = match.groups()
        expression = substitute_parameters(expression)
        expression = _expand_definitions(expression)

        # Translate simple ChemQL [variable] expressions into (variable).
        expression = re.sub(
            r"\[\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\]",
            r"(\1)",
            expression,
        )

        return f"[{variable} = {expression}]"

    def execute_function_lines(lines):
        """Execute function statements and propagate return values."""
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            if not line:
                i += 1
                continue

            # Structured error handling is available inside functions too.
            if line.casefold() == "risk":
                end_risk = i + 1
                risk_depth = 1
                while end_risk < len(lines):
                    token = lines[end_risk].strip().casefold()
                    if token == "risk": risk_depth += 1
                    elif token == "endrisk":
                        risk_depth -= 1
                        if risk_depth == 0: break
                    end_risk += 1
                if end_risk >= len(lines):
                    raise SyntaxError(f"Missing `endrisk` in function `{name}`")
                sections = {"risk": [], "fix": [], "cleanup": []}
                section = "risk"
                for risk_line in lines[i + 1:end_risk]:
                    marker = risk_line.strip().casefold()
                    if marker in {"fix", "cleanup"}: section = marker
                    else: sections[section].append(risk_line)
                try:
                    result = execute_function_lines(sections["risk"])
                    if result is not _NO_RETURN:
                        return result
                    python_globals["error"] = None
                except Exception as exc:
                    python_globals["error"] = (
                        exc.error_type
                        if isinstance(exc, ChemQLSignal)
                        else "ChemQLError"
                        if isinstance(exc, ChemQLError)
                        else type(exc).__name__
                    )
                    if sections["fix"]:
                        result = execute_function_lines(sections["fix"])
                        if result is not _NO_RETURN:
                            return result
                    elif not isinstance(exc, ChemQLSignal):
                        raise
                finally:
                    # Cleanup is for side effects; it must not override a return
                    # from the risk/fix section (and returning from finally is unsafe).
                    if sections["cleanup"]:
                        execute_function_lines(sections["cleanup"])
                i = end_risk + 1
                continue

            signal_match = re.fullmatch(r"signal\s+(.+)", line, re.IGNORECASE)
            if signal_match:
                raise ChemQLSignal(evaluate_python(signal_match.group(1)))

            # Multiline Python block.
            if line == "[[[":
                block = []
                i += 1

                while i < len(lines) and lines[i].strip() != "]]]":
                    source_line = substitute_parameters(lines[i])
                    source_line = _expand_definitions(source_line)
                    block.append(source_line)
                    i += 1

                if i >= len(lines):
                    raise SyntaxError(
                        f"Missing `]]]` in function `{name}`"
                    )

                evaluate_python("\n".join(block))
                i += 1
                continue

            # Recognize block headers generically, while excluding
            # closing and branch markers from being treated as headers.
            # generic_header = re.match(
            #     r"^\[\s*(?!endblock\b|else\b|elif\b)"
            #     r"[A-Za-z_]\w*\b.*\]\s*$",
            #     line,
            # )

            # Resolve positional placeholders BEFORE parsing the header.
            # Otherwise `[if \1 <= 1]` is rejected as non-Python syntax before
            # `\1` can be replaced with the actual argument.
            resolved_line = line
            if line.startswith("[") and line.endswith("]"):
                resolved_line = "[" + _expand_definitions(
                    substitute_parameters(line[1:-1].strip())
                ) + "]"

            if is_block_header(resolved_line):
                # Nested block discovery must see substituted headers too,
                # or a nested `[if \1 ...]` won't increase the block depth.
                resolved_lines = [substitute_parameters(source_line) for source_line in lines]
                end = find_endblock(resolved_lines, i + 1)

                block_body = [
                    normalize_let_line(substitute_parameters(source_line))
                    for source_line in lines[i + 1:end]
                ]

                code = resolved_line[1:-1].strip()

                # Function parameters must also be substituted in block
                # headers, e.g. [for i in range(2, \1 + 1)].
                resolved_header = (
                    "["
                    + _expand_definitions(substitute_parameters(code))
                    + "]"
                )

                if code.startswith("for "):
                    execute_for_block(resolved_header, block_body)

                elif code.startswith("while "):
                    execute_while_block(resolved_header, block_body)

                elif code.startswith("if "):
                    # Expand parameters and definitions before evaluating.
                    condition = code[3:].strip()
                    condition = substitute_parameters(condition)
                    condition = _expand_definitions(condition)

                    # Find the `else` belonging to this `if`, not an `else`
                    # nested inside one of its child blocks. Without tracking
                    # nesting, the false branch of an inner `if` can be
                    # mistaken for the outer `if`'s `else`.
                    else_index = None
                    nested_depth = 0
                    for j, source_line in enumerate(block_body):
                        token = source_line.strip()
                        if is_block_header(token):
                            nested_depth += 1
                            continue
                        if token in {"[endblock]", "[endif]", "[endfor]", "[endwhile]"}:
                            if nested_depth:
                                nested_depth -= 1
                            continue
                        if token == "[else]" and nested_depth == 0:
                            else_index = j
                            break

                    if evaluate_python(condition):
                        selected_body = (
                            block_body
                            if else_index is None
                            else block_body[:else_index]
                        )
                    else:
                        selected_body = (
                            []
                            if else_index is None
                            else block_body[else_index + 1:]
                        )

                    # Execute only the selected branch. A return exits
                    # this function immediately.
                    result = execute_function_lines(selected_body)

                    if result is not _NO_RETURN:
                        return result

                else:
                    raise SyntaxError(
                        f"Unsupported function block `{code}`"
                    )

                i = end + 1
                continue

            if line == "[endblock]":
                raise SyntaxError(
                    f"Unexpected `[endblock]` in function `{name}`"
                )

            # Handle return statements inside the function.
            if re.match(r"^return\b", line):
                expression = re.sub(r"^return\b", "", line, count=1).strip()

                if expression.startswith("[") and expression.endswith("]"):
                    expression = expression[1:-1].strip()

                expression = substitute_parameters(expression)
                expression = _expand_definitions(expression)

                return evaluate_python(expression) if expression else None

            normalized = normalize_let_line(line)

            if normalized != line:
                evaluate_python(normalized[1:-1])
            elif line.startswith("[") and line.endswith("]"):
                expression = line[1:-1].strip()
                expression = substitute_parameters(expression)
                expression = _expand_definitions(expression)
                evaluate_python(expression)
            else:
                expression = substitute_parameters(line)
                expression = _expand_definitions(expression)
                evaluate_python(expression)

            i += 1

        return _NO_RETURN

    try:
        result = execute_function_lines(definition["body"])
        return None if result is _NO_RETURN else result

    finally:
        # Restore the caller's namespaces.
        python_globals.clear()
        python_globals.update(saved_globals)

        CHEMQL_VARIABLES.clear()
        CHEMQL_VARIABLES.update(saved_chemql_variables)

        if had_arguments:
            python_globals["arguments"] = saved_arguments
        else:
            python_globals.pop("arguments", None)
        _CURRENT_NAMESPACE = previous_namespace

def _resolve_package_qualified_name(name):
    """Resolve an explicit package alias at the start of a qualified name."""
    if "::" not in name:
        return name
    bindings = globals().get("CHEMQL_PACKAGE_BINDINGS", {})
    parts = name.split("::")
    for prefix_length in range(len(parts) - 1, 0, -1):
        prefix = "::".join(parts[:prefix_length])
        canonical = bindings.get(prefix)
        if canonical:
            return "::".join([canonical, *parts[prefix_length:]])
    return name


def _namespace_function_is_callable(name):
    """Return whether a namespaced function is public or called internally."""
    name = _resolve_package_qualified_name(name)
    if "::" not in name:
        return True
    namespace_name, member_name = name.rsplit("::", 1)
    namespace = NAMESPACES.get(namespace_name)
    if namespace is None:
        return True  # Preserve the normal unknown-function error path.
    if member_name in namespace._chemql_public:
        return True
    return _CURRENT_NAMESPACE is not None and _CURRENT_NAMESPACE._chemql_name == namespace_name # type: ignore

def _expand_function_calls(text):
    """Expand function calls of the form name{arg1, arg2} in query text."""
    # This pass is only for top-level query expressions, not arbitrary strings.
    # The scanner preserves quoted strings and resolves innermost calls first.
    for _ in range(100):
        changed = False
        quote = None
        escaped = False
        i = 0
        while i < len(text):
            ch = text[i]
            if quote is not None:
                if escaped: escaped = False
                elif ch == "\\": escaped = True
                elif ch == quote: quote = None
                i += 1
                continue
            if ch in ("'", '"'):
                quote = ch; i += 1; continue
            if i and re.match(r"[A-Za-z0-9_.:]", text[i - 1]):
                i += 1
                continue
            match = re.match(r"([A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\{", text[i:])
            if match:
                name = match.group(1)
                resolved_name = _resolve_package_qualified_name(name)
                opening = i + match.end() - 1
                end = find_matching(text, opening, "{", "}")
                args = _split_function_arguments(text[opening + 1:end])
                if resolved_name in FUNCTIONS:
                    if not _namespace_function_is_callable(resolved_name):
                        raise PermissionError(f"Function `{name}` is private")
                    value = _call_function(resolved_name, args)
                elif "::" not in resolved_name and resolved_name in BUILTIN_FUNCTIONS:
                    value = _call_builtin(resolved_name, args)
                elif (
                    "::" not in resolved_name
                    and isinstance(python_globals.get(resolved_name), type)
                ):
                    replacement = (
                        f"{resolved_name}({text[opening + 1:end]})"
                    )
                    text = text[:i] + replacement + text[end + 1:]
                    changed = True
                    break
                else:
                    raise ChemQLError(f"Unknown function `{name}`")
                replacement = repr(value) if isinstance(value, str) else ("None" if value is None else str(value))
                text = text[:i] + replacement + text[end + 1:]
                changed = True
                break
            i += 1
        if not changed:
            return text
    raise SyntaxError("Function expansion exceeded 100 levels (possible recursion)")


_shell_process = None
_shell_master_fd = None
_shell_prompt_ready = False
_shell_output_streamed = False
_shell_output_queue = None
_shell_reader_thread = None
_shell_script_path = None
_shell_prompt = f"__CHEMQL_PROMPT_{uuid.uuid4().hex}__"

def get_shell():
    """Return the persistent OS shell process for the current platform."""
    global _shell_process, _shell_master_fd, _shell_prompt_ready
    global _shell_output_queue, _shell_reader_thread, _shell_script_path

    if _shell_process is not None and _shell_process.poll() is None:
        return _shell_process

    # Clean up any stale shell/PTY left by an interrupted command.
    close_shell()

    if os.name == "nt":
        # PowerShell reads its program from a file, leaving stdin available for
        # the command/marker protocol and commands such as Read-Host.
        import tempfile

        setup = r'''$ErrorActionPreference = 'Continue'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::Out.WriteLine('__CHEMQL_READY__')
[Console]::Out.Flush()

while ($true) {
    # One physical input line per request avoids command/marker line desync.
    $request = [Console]::In.ReadLine()
    if ($null -eq $request) { break }

    $separatorIndex = $request.IndexOf('|')
    if ($separatorIndex -le 0) {
        [Console]::Out.WriteLine('CHEMQL_PROTOCOL_ERROR: malformed request')
        [Console]::Out.Flush()
        continue
    }

    $marker = $request.Substring(0, $separatorIndex)
    $encodedCommand = $request.Substring($separatorIndex + 1)

    try {
        $commandText = [System.Text.Encoding]::UTF8.GetString(
            [System.Convert]::FromBase64String($encodedCommand)
        )
        if ([string]::IsNullOrWhiteSpace($commandText)) {
            [Console]::Out.WriteLine('ChemQL received an empty PowerShell command.')
        }
        else {
            # Invoke-Expression runs in this persistent script scope, preserving
            # PowerShell variables between ChemQL requests. Format pipeline
            # output explicitly for each request; otherwise PowerShell's default
            # formatting subsystem can defer table output until the next request,
            # making commands such as Get-Location appear blank or duplicated.
            $formattedOutput = Invoke-Expression -Command $commandText | Out-String -Width 4096
            if (-not [string]::IsNullOrEmpty($formattedOutput)) {
                [Console]::Out.Write($formattedOutput)
            }
        }
    }
    catch {
        [Console]::Out.WriteLine($_.ToString())
    }
    finally {
        [Console]::Out.WriteLine($marker)
        [Console]::Out.Flush()
    }
}
''' # I have no idea what this is, this is code I wrote today at 4:00AM but it somehow works
    # reminder to future self to not touch this
        fd, _shell_script_path = tempfile.mkstemp(prefix="chemql_shell_", suffix=".ps1")
        try:
            with os.fdopen(fd, "w", encoding="ascii", newline="\n") as script_file:
                script_file.write(setup)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(_shell_script_path)
            except OSError:
                pass
            _shell_script_path = None
            raise

        _shell_process = subprocess.Popen(
            ["powershell.exe", "-NoLogo", "-NoProfile",
             "-ExecutionPolicy", "Bypass", "-File", _shell_script_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        output_queue = queue.Queue()
        _shell_output_queue = output_queue
        process = _shell_process

        def read_output():
            try:
                while True:
                    character = process.stdout.read(1)  # type: ignore
                    if not character:
                        break
                    output_queue.put(character)
            except (OSError, ValueError):
                pass
            finally:
                output_queue.put(None)

        _shell_reader_thread = threading.Thread(target=read_output, daemon=True)
        _shell_reader_thread.start()

        # Wait briefly for the PowerShell script to confirm it started. This
        # prevents the first request from racing process startup and diagnoses
        # startup failures instead of hanging later while waiting for a marker.
        ready_text = ""
        ready_deadline = time.monotonic() + 5
        while "__CHEMQL_READY__" not in ready_text:
            remaining = ready_deadline - time.monotonic()
            if remaining <= 0:
                startup_output = ready_text.replace("\\r\\n", "\\n").strip()
                close_shell()
                raise RuntimeError(
                    "PowerShell request loop did not start within 5 seconds."
                    + (f" Output: {startup_output}" if startup_output else "")
                )
            try:
                character = output_queue.get(timeout=min(0.1, remaining))
            except queue.Empty:
                if _shell_process.poll() is not None:
                    raise RuntimeError(
                        "PowerShell exited during startup with code "
                        f"{_shell_process.returncode}."
                    )
                continue
            if character is None:
                raise RuntimeError("PowerShell closed its output during startup.")
            ready_text += character
        ready_pos = ready_text.find("__CHEMQL_READY__")
        # Any text before the readiness token is startup diagnostics. It is
        # not command output and should not leak into the first request.
        startup_extra = ready_text[:ready_pos]
        if startup_extra.strip():
            # Preserve startup diagnostics for the next request to display.
            for char in startup_extra:
                output_queue.put(char)

        # Windows PowerShell uses the explicit command/marker protocol above.
        # Do not run the POSIX PTY prompt handshake below: it waits for a shell
        # prompt that this non-interactive PowerShell script intentionally has
        # disabled, causing get_shell() to hang before the first command.
        return _shell_process

    else:
        # Leave the existing POSIX implementation unchanged.
        import fcntl
        import pty
        import termios

        master_fd, slave_fd = pty.openpty()
        attrs = termios.tcgetattr(slave_fd)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)

        def attach_controlling_terminal():
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

        try:
            _shell_process = subprocess.Popen(
                ["bash", "--noprofile", "--norc"],
                stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                close_fds=True, start_new_session=True,
                preexec_fn=attach_controlling_terminal,
                env={**os.environ, "PS1": _shell_prompt, "PS2": ""},
            )
            _shell_master_fd = master_fd
            _shell_prompt_ready = False
        except Exception:
            os.close(master_fd)
            raise
        finally:
            os.close(slave_fd)

    return _shell_process

def _run_shell_command_posix(command, marker=None):
    """Run a command through the persistent PTY and forward keyboard input.

    A unique shell prompt marks command completion. Unlike appending an `echo`
    marker to stdin, this does not accidentally feed that marker to commands
    such as `read -p` that consume keyboard input.
    """
    global _shell_prompt_ready, _shell_output_streamed
    _shell_output_streamed = False
    shell = get_shell()
    master_fd = _shell_master_fd
    if master_fd is None:
        return "Shell error: pseudo-terminal was not initialized."

    prompt_bytes = _shell_prompt.encode()

    def wait_for_prompt(forward_keyboard=False):
        global _shell_output_streamed
        collected = bytearray()
        streamed_pos = 0
        stdin_fd = None
        try:
            if forward_keyboard and sys.stdin is not None and sys.stdin.isatty():
                stdin_fd = sys.stdin.fileno()
        except (AttributeError, OSError, ValueError):
            stdin_fd = None

        while True:
            readers = [master_fd]
            if stdin_fd is not None:
                readers.append(stdin_fd) #type:ignore
            try:
                ready, _, _ = select.select(readers, [], [])
            except KeyboardInterrupt:
                # ChemQL owns the user's terminal, so forward Ctrl-C into the
                # child PTY to interrupt its foreground command.
                try:
                    os.write(master_fd, b"\x03")
                except OSError:
                    pass
                continue

            if stdin_fd is not None and stdin_fd in ready:
                try:
                    typed = os.read(stdin_fd, 4096)
                except OSError:
                    typed = b""
                if typed:
                    try:
                        os.write(master_fd, typed)
                    except OSError:
                        stdin_fd = None
                else:
                    stdin_fd = None

            if master_fd in ready:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    chunk = b""
                if not chunk:
                    return None
                collected.extend(chunk)
                prompt_pos = collected.find(prompt_bytes)
                if forward_keyboard:
                    # Stream command output immediately so prompts such as
                    # `read -p` are visible while the command waits for input.
                    # Hold back only a suffix that might be the start of PS1.
                    safe_end = prompt_pos if prompt_pos >= 0 else len(collected)
                    if prompt_pos < 0:
                        max_overlap = min(len(prompt_bytes) - 1, len(collected))
                        overlap = 0
                        for size in range(max_overlap, 0, -1):
                            if collected.endswith(prompt_bytes[:size]):
                                overlap = size
                                break
                        safe_end -= overlap
                    if safe_end > streamed_pos:
                        visible = bytes(collected[streamed_pos:safe_end])
                        try:
                            sys.stdout.write(visible.decode(errors="replace"))
                            sys.stdout.flush()
                            _shell_output_streamed = True
                        except (OSError, UnicodeError):
                            pass
                        streamed_pos = safe_end
                if prompt_pos >= 0:
                    before = bytes(collected[:prompt_pos])
                    # Strip terminal CRs while preserving meaningful output.
                    return before.decode(errors="replace").replace("\r\n", "\n").rstrip("\r\n ")

    # Bash emits a prompt immediately on startup. Consume it before submitting
    # the first command; after each command the same prompt signals completion.
    if not _shell_prompt_ready:
        initial = wait_for_prompt(forward_keyboard=False)
        if initial is None:
            close_shell()
            return "Shell session terminated."
        _shell_prompt_ready = True

    try:
        # Send a fenced block as ONE shell input command. Feeding raw newlines
        # to an interactive Bash PTY lets Bash emit PS1 after the first physical
        # line, so wait_for_prompt() can return early while later lines remain
        # queued and execute out of sync with the next ChemQL command. Quoting
        # the complete script keeps its newlines inside one `eval` command;
        # eval still runs in the persistent shell, so `cd` and shell variables
        # remain effective for later commands.
        shell_input = "eval " + shlex.quote(command)
        os.write(master_fd, (shell_input + "\n").encode())
        result = wait_for_prompt(forward_keyboard=True)
        if result is None:
            close_shell()
            return "Shell session terminated."
        return result
    except (BrokenPipeError, OSError) as exc:
        close_shell()
        return f"Shell error: {exc}"

def _run_shell_command_windows(command):
    """Execute one command in the persistent PowerShell request loop."""
    import base64
    import msvcrt
    import uuid

    shell = get_shell()
    output_queue = _shell_output_queue
    if output_queue is None:
        return "Shell error: PowerShell output reader was not initialized."
    if shell.stdin is None:
        return "Shell error: PowerShell stdin is unavailable."

    marker = f"__CHEMQL_DONE_{uuid.uuid4().hex}__"
    encoded_command = base64.b64encode(command.encode("utf-8")).decode("ascii")
    timeout_seconds=120
    def wait_for_marker(timeout_seconds=120):
        """Collect output while streaming prompts so interactive commands remain usable."""
        global _shell_output_streamed

        collected = ""
        streamed_pos = 0
        started = time.monotonic()
        try:
            stdin_is_tty = sys.stdin is not None and sys.stdin.isatty()
        except (AttributeError, OSError, ValueError):
            stdin_is_tty = False
        pending_input = ""

        def stream_until(end):
            nonlocal streamed_pos
            global _shell_output_streamed
            if not stdin_is_tty or end <= streamed_pos:
                return
            visible = collected[streamed_pos:end]
            if visible:
                try:
                    sys.stdout.write(visible)
                    sys.stdout.flush()
                    _shell_output_streamed = True
                except (OSError, UnicodeError):
                    pass
                streamed_pos = end

        while True:
            if time.monotonic() - started > timeout_seconds:
                return (None, collected, True)

            if stdin_is_tty:
                try:
                    while msvcrt.kbhit():  # type: ignore
                        key = msvcrt.getwch()  # type: ignore
                        if key in ("\x00", "\xe0"):
                            if msvcrt.kbhit():  # type: ignore
                                msvcrt.getwch()  # type: ignore
                        elif key in ("\r", "\n"):
                            shell.stdin.write(pending_input + "\n")  # type: ignore  # text mode normalizes newlines on Windows
                            shell.stdin.flush()  # type: ignore
                            sys.stdout.write("\n")
                            sys.stdout.flush()
                            pending_input = ""
                        elif key == "\b":
                            if pending_input:
                                pending_input = pending_input[:-1]
                                sys.stdout.write("\b \b")
                                sys.stdout.flush()
                        elif key == "\x03":
                            close_shell()
                            return (None, collected, False)
                        elif key >= " " and key != "\x7f": # I have no idea what I did but it workd
                            pending_input += key
                            sys.stdout.write(key)
                            sys.stdout.flush()
                except (OSError, ValueError):
                    stdin_is_tty = False

            try:
                character = output_queue.get(timeout=0.04)
            except queue.Empty:
                if shell.poll() is not None:
                    return (None, collected, False)
                continue
            if character is None:
                return (None, collected, False)

            collected += character
            marker_pos = collected.find(marker)
            if marker_pos >= 0:
                stream_until(marker_pos)
                visible = collected[:marker_pos]
                return (
                    visible.replace("\r\n", "\n").rstrip("\r\n "),
                    collected,
                    False,
                )

            # Hold back a suffix that could be the beginning of the completion
            # marker, so protocol text is never accidentally printed.
            overlap = min(len(marker) - 1, len(collected))
            while overlap and not collected.endswith(marker[:overlap]):
                overlap -= 1
            stream_until(len(collected) - overlap)

    try:
        shell.stdin.write(marker + "|" + encoded_command + "\n")  # text mode normalizes newlines on Windows
        shell.stdin.flush()
        result, collected, timed_out = wait_for_marker()
        if timed_out:
            close_shell()
            debug = collected.replace("\r\n", "\n").rstrip()
            detail = f"PowerShell did not return its completion marker within {timeout_seconds} seconds."
            if debug:
                detail += f"\nOutput received before timeout:\n{debug}"
            else:
                detail += "\nNo output was received. The PowerShell request loop may not have started or may not be reading stdin."
            return detail
        if result is None:
            close_shell()
            return "Shell session terminated before PowerShell returned its completion marker."
        return result
    except (BrokenPipeError, OSError, ValueError) as exc:
        close_shell()
        return f"Shell error: {exc}"

def run_shell_command(command):
    global _shell_output_streamed

    command = (
        command.replace("\r\n", "\n")
        .replace("\r", "\n")
        .rstrip("\n")
    )

    try:
        if os.name == "nt":
            stripped = command.strip()

            if stripped.casefold() in {
                "powershell",
                "powershell.exe",
                "pwsh",
                "pwsh.exe",
            }:
                return (
                    "ChemQL already uses PowerShell on Windows; "
                    "run the command directly instead of starting "
                    "a nested shell."
                )

            # Clear the terminal without sending Clear-Host to PowerShell.
            if stripped.casefold() in {
                "clear",
                "cls",
                "clear-host",
            }:
                os.system("cls")
                return ""

            _shell_output_streamed = False
            return _run_shell_command_windows(command)

        # POSIX behavior remains unchanged.
        return _run_shell_command_posix(command)

    except KeyboardInterrupt:
        close_shell()
        return "Shell command interrupted. Shell session was reset."

def close_shell():
    """Clean up the persistent shell and its pseudo-terminal on exit."""
    global _shell_process, _shell_master_fd, _shell_prompt_ready
    global _shell_output_queue, _shell_reader_thread, _shell_script_path

    if _shell_process is not None:
        if _shell_process.poll() is None:
            try:
                _shell_process.terminate()
                _shell_process.wait(timeout=2)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    _shell_process.kill()
                    _shell_process.wait(timeout=2)
                except (subprocess.TimeoutExpired, OSError):
                    pass
        _shell_process = None

    if _shell_master_fd is not None:
        try:
            os.close(_shell_master_fd)
        except OSError:
            pass
        _shell_master_fd = None
    _shell_prompt_ready = False
    _shell_output_queue = None
    _shell_reader_thread = None

    if _shell_script_path is not None:
        try:
            os.unlink(_shell_script_path)
        except OSError:
            pass
        _shell_script_path = None


atexit.register(close_shell)

class Unknown:
    """Represents a Chemql query result that cannot be resolved to a known object."""

    __slots__ = ("value",)

    def __init__(self, value=None):
        self.value = value

    def __str__(self):
        return str(self.value) if self.value is not None else "Unknown"

    def __repr__(self):
        return repr(self.value) if self.value is not None else "Unknown"


class ChemQLError(Exception):
    def __init__(self, message, position=None, length=1):
        super().__init__(message)
        self.position = position
        self.length = length


class _ChemQLUnknownCommand(ChemQLError):
    pass


_CHEMQL_RISK_DEPTH = 0


def format_error(message, text=None, position=None, length=1):
    if _CHEMQL_RISK_DEPTH:
        raise ChemQLError(message, position, length)

    output = ""
    if (text is not None) and (position is not None) and (not NO_ANSI):
        output += f"\033[1;31m{' ' * (position+4)}{'^' * max(1, length)}\n\033[0m"
    output += f"Error: {message}" if NO_ANSI else f"\033[31mError: {message}\033[0m"


    return output


def token_positions(text):
    positions = []
    i = 0
    while i < len(text):
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break

        start = i
        quote = None
        escaped = False
        while i < len(text):
            char = text[i]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif quote:
                if char == quote:
                    quote = None
            elif char in ("\'", '"'):
                quote = char
            elif char.isspace():
                break
            i += 1
        positions.append((start, max(1, i - start)))
    return positions


def error_position(positions, index):
    if 0 <= index < len(positions):
        return positions[index]
    return (None, 1)
from prompt_toolkit.shortcuts import choice

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

with (DATA_DIR / "PeriodicTableJSON.json").open("r", encoding="utf-8") as f:
    elements = json.load(f)
with (DATA_DIR / "Molecules.json").open("r", encoding="utf-8") as f:
    molecules = json.load(f)
with (DATA_DIR / "Reactions.json").open("r", encoding="utf-8") as f:
    reactions = json.load(f)
with (DATA_DIR / "MoleculeBonds.json").open("r", encoding="utf-8") as f:
    moleculeBonds = json.load(f)
with (DATA_DIR / "BondEnergies.json").open("r", encoding="utf-8") as f:
    bondEnergies = json.load(f)

operators = {"has", "like", "like!", "likep", "=", "!=", ">", "<", ">=", "<="}

queryOperations = {"sort", "limit", "count"}

def like_match(value, pattern, case_sensitive=False):
    regex = ""
    i = 0

    while i < len(pattern):
        char = pattern[i]

        if char == "\\":
            i += 1

            if i >= len(pattern):
                raise ValueError(
                    "Escape character at end of pattern"
                )

            regex += re.escape(pattern[i])

        elif char == "*":
            regex += ".*"

        elif char == "%":
            regex += "[0-9]*"

        elif char == "&":
            regex += "[A-Za-z]*"

        elif char == "_":
            regex += "."

        elif char == "#":
            regex += "[0-9]"

        elif char == "?":
            regex += "[A-Za-z]"

        else:
            regex += re.escape(char)

        i += 1

    flags = 0 if case_sensitive else re.IGNORECASE

    return re.fullmatch(regex, value, flags) is not None


def normal_round(num, p=0):
    num1 = num / 10**p
    numint = math.floor(num1)
    numfloat = num - numint
    if numfloat >= 0.5:
        return -(-numint - 1) * 10**p
    return numint * 10 ** p



class Element:
    __slots__ = ("name", "appearance", "atomic_mass", "boil", "category", "density", "discovered_by", "melt", "molar_heat", "named_by", "number", "period", "group", "phase", "source", "bohr_model_image", "bohr_model_3d", "spectral_img", "summary", "symbol", "xpos", "ypos", "wxpos", "wypos", "shells", "electron_configuration", "electron_configuration_semantic", "electron_affinity", "electronegativity_pauling", "ionization_energies", "cpk_hex", "image", "block")

    def __init__(
        self,
        name,
        appearance,
        atomic_mass,
        boil,
        category,
        density,
        discovered_by,
        melt,
        molar_heat,
        named_by,
        number,
        period,
        group,
        phase,
        source,
        bohr_model_image,
        bohr_model_3d,
        spectral_img,
        summary,
        symbol,
        xpos,
        ypos,
        wxpos,
        wypos,
        shells,
        electron_configuration,
        electron_configuration_semantic,
        electron_affinity,
        electronegativity_pauling,
        ionization_energies,
        cpk_hex,
        image,
        block,
    ):
        self.name = name
        self.appearance = appearance
        self.atomic_mass = atomic_mass
        self.boil = boil
        self.category = category
        self.density = density
        self.discovered_by = discovered_by
        self.melt = melt
        self.molar_heat = molar_heat
        self.named_by = named_by
        self.number = number
        self.period = period
        self.group = group
        self.phase = phase
        self.source = source
        self.bohr_model_image = bohr_model_image
        self.bohr_model_3d = bohr_model_3d
        self.spectral_img = spectral_img
        self.summary = summary
        self.symbol = symbol
        self.xpos = xpos
        self.ypos = ypos
        self.wxpos = wxpos
        self.wypos = wypos
        self.shells = shells
        self.electron_configuration = electron_configuration
        self.electron_configuration_semantic = electron_configuration_semantic
        self.electron_affinity = electron_affinity
        self.electronegativity_pauling = electronegativity_pauling
        self.ionization_energies = ionization_energies
        self.cpk_hex = cpk_hex
        self.image = image
        self.block = block

    def __getitem__(self, key):
        return getattr(self, key)

    def __str__(self):
        if self.cpk_hex:
            r = int(self.cpk_hex[0:2], 16)
            g = int(self.cpk_hex[2:4], 16)
            b = int(self.cpk_hex[4:6], 16)
        else:
            r = g = b = 255

        return (
            f"\033[38;2;{r};{g};{b}m"
            f" ______________\n"
            f"|     {self.number:^3}      |\n"
            f"|              |\n"
            f"|     {self.symbol:^3}      |\n"
            f"|              |\n"
            f"|     {normal_round(self.atomic_mass):^3}      |\n"
            f"|______________|"
            f"\033[0m\n"
        )
    def __repr__(self):
        return f"{self.name}"

elementKeys = ("name", "appearance", "atomic_mass", "boil", "category", "density", "discovered_by", "melt", "molar_heat", "named_by", "number", "period", "group", "phase", "source", "bohr_model_image", "bohr_model_3d", "spectral_img", "summary", "symbol", "xpos", "ypos", "wxpos", "wypos", "shells", "electron_configuration", "electron_configuration_semantic", "electron_affinity", "electronegativity_pauling", "ionization_energies", "cpk-hex", "image", "block")

ELEMENTS = [Element(*(item[key] if item[key] is not None else "" for key in elementKeys)) for item in elements["elements"]]

# No longer need the JSON structure.

ELEMENTS.pop()

class Molecule:
    __slots__ = ("name", "formula", "elements", "molecular_weight", "iupac_name", "smiles", "cid", "melting_point","boiling_point", "density", "state", "bonds", "total_bond_energy")
    def __init__(self, name, formula, elements, molecular_weight, iupac_name, smiles, cid, melting_point, boiling_point, density, state):
        self.name = name
        self.formula = formula
        self.elements = elements
        self.molecular_weight = molecular_weight
        self.iupac_name = iupac_name
        self.smiles = smiles
        self.cid = cid
        self.melting_point = melting_point
        self.boiling_point = boiling_point
        self.density = density
        self.state = state
        self.bonds = moleculeBonds.get(name, {}).get("bonds", [])
        self.total_bond_energy = sum(
            bond.get("count", 0) * bondEnergies[
                f"{'-'.join(sorted(bond['elements']))}-{bond['type']}"
            ]["energy"]
            for bond in self.bonds
        )
    def __getitem__(self, key):
        return getattr(self, key)
    def __str__(self):
        return f"{self.formula.translate(str.maketrans('0123456789', '₀₁₂₃₄₅₆₇₈₉'))} ({self.name})"

    def __repr__(self):
        return self.name

moleculeKeys = ("name", "formula", "elements", "molecular_weight", "iupac_name", "smiles", "cid", "melting_point", "boiling_point", "density", "state", "bonds", "total_bond_energy")

PUBCHEM_BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUBCHEM_VIEW_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"
PUBCHEM_SERVICE_ERROR = False


def _normalize_molecule_value(value):
    """Strip surrounding quotes and whitespace from a molecule lookup."""
    if value is None:
        return ""

    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()

    return text


def _fetch_url_text(url, timeout=15, retries=2):
    """Fetch a raw text response from a URL, retrying transient failures."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ChemQL/1.0 (+https://example.invalid)",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        },
    )

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            return ""

    return ""


def _get_json(url, timeout=10, retries=3):
    """Fetch JSON from a URL with retries for transient server errors."""
    global PUBCHEM_SERVICE_ERROR

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ChemQL/1.0 (+https://example.invalid)",
            "Accept": "application/json",
        },
    )

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.load(response)
                PUBCHEM_SERVICE_ERROR = False
                return data

        except urllib.error.HTTPError as exc:
            if exc.code in (500, 502, 503, 504):
                PUBCHEM_SERVICE_ERROR = True
                if attempt < retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                return None
            PUBCHEM_SERVICE_ERROR = False
            return None

        except (
            urllib.error.URLError,
            json.JSONDecodeError,
            TimeoutError,
            OSError,
            ValueError,
        ):
            PUBCHEM_SERVICE_ERROR = True
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            return None


def _find_local_molecule(value):
    """Return a built-in molecule when the network lookup is unavailable."""
    if value is None:
        return None

    target = _normalize_molecule_value(value)
    if not target:
        return None

    normalized = target.lower()

    for molecule in MOLECULES:
        if molecule.name.lower() == normalized:
            return molecule
        if molecule.formula.lower() == normalized:
            return molecule
        if molecule.iupac_name and molecule.iupac_name.lower() == normalized:
            return molecule

    for molecule in MOLECULES:
        if molecule.name.lower().startswith(normalized):
            return molecule
        if molecule.formula.lower().startswith(normalized):
            return molecule
        if molecule.iupac_name and molecule.iupac_name.lower().startswith(normalized):
            return molecule

    return None


CHEMSPIDER_BASE_URL = "https://api.rsc.org/compounds/v1"


def _chemspider_request(method, endpoint, payload=None, timeout=12):
    """Call the authenticated ChemSpider Compound API; return decoded JSON or None."""
    api_key = os.getenv("CHEMSPIDER_API_KEY", "").strip()
    if not api_key:
        return None

    url = f"{CHEMSPIDER_BASE_URL}/{endpoint.lstrip('/')}"
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "apikey": api_key,
        "Accept": "application/json",
        "User-Agent": "ChemQL",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url, data=body, headers=headers, method=method.upper()
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw.strip() else {}
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
        json.JSONDecodeError,
        ValueError,
    ):
        return None


def _chemspider_record_ids(target):
    """Search ChemSpider by name and wait briefly for the asynchronous query."""
    submitted = _chemspider_request("POST", "filter/name", {"name": target})
    if not isinstance(submitted, dict):
        return []

    query_id = submitted.get("queryId") or submitted.get("query_id")
    if not query_id:
        ids = submitted.get("recordIds") or submitted.get("results") or []
        return ids if isinstance(ids, list) else []

    for attempt in range(10):
        status_data = _chemspider_request("GET", f"filter/{query_id}/status")
        if not isinstance(status_data, dict):
            return []
        status = str(status_data.get("status", "")).casefold()
        if status in {"complete", "completed", "finished"}:
            break
        if status in {"failed", "error", "cancelled", "canceled"}:
            return []
        time.sleep(0.4 + attempt * 0.1)
    else:
        return []

    results = _chemspider_request("GET", f"filter/{query_id}/results")
    if isinstance(results, list):
        return results
    if isinstance(results, dict):
        ids = results.get("recordIds") or results.get("results") or results.get("ids")
        return ids if isinstance(ids, list) else []
    return []


def _fetch_chemspider_molecule(value):
    """Fetch a ChemSpider compound and normalize it to ChemQL's Molecule model.

    Requires CHEMSPIDER_API_KEY in the environment. Returns None when the key
    is absent, the API fails, or no suitable record is returned.
    """
    target = _normalize_molecule_value(value)
    if not target or not os.getenv("CHEMSPIDER_API_KEY", "").strip():
        return None

    record_ids = _chemspider_record_ids(target)
    if not record_ids:
        return None

    record_id = record_ids[0]
    if isinstance(record_id, dict):
        record_id = record_id.get("recordId") or record_id.get("id") or record_id.get("csid")
    if record_id is None:
        return None

    details = _chemspider_request("GET", f"records/{record_id}/details")
    if not isinstance(details, dict):
        return None

    def pick(*names, default=None):
        for name in names:
            candidate = details.get(name)
            if candidate is not None and candidate != "":
                return candidate
        return default

    name = pick("commonName", "common_name", "name", default=target)
    formula = pick("molecularFormula", "molecular_formula", "formula", default="")
    weight = pick("molecularWeight", "molecular_weight", "averageMass", default=0)
    smiles = pick("smiles", "SMILES", "canonicalSmiles", default="")
    iupac_name = pick("iupacName", "iupac_name", "systematicName", default="")
    try:
        weight = float(weight or 0)
    except (TypeError, ValueError):
        weight = 0.0

    return Molecule(
        name=str(name),
        formula=str(formula or ""),
        elements=[],
        molecular_weight=weight,
        iupac_name=str(iupac_name or ""),
        smiles=str(smiles or ""),
        cid=None,
        melting_point=None,
        boiling_point=None,
        density=None,
        state=None,
    )

def _fetch_nist_molecule(value):
    """Try NIST WebBook as a fallback chemistry source."""
    target = _normalize_molecule_value(value)
    if not target:
        return None

    encoded = urllib.parse.quote(target)
    url = f"https://webbook.nist.gov/cgi/cbook.cgi?Name={encoded}&Units=SI"
    html = _fetch_url_text(url)
    if not html:
        return None

    formula_match = re.search(r"Formula\s*[:<]?[\s\n]*([A-Z][a-z]?(?:\d+)?(?:[A-Z][a-z]?(?:\d+)?)*)", html, re.I)
    weight_match = re.search(r"Molecular weight\s*[:<]?[\s\n]*([0-9]+(?:\.[0-9]+)?)", html, re.I)

    if not formula_match:
        return None

    formula = formula_match.group(1).strip()
    molecular_weight = float(weight_match.group(1)) if weight_match else 0.0

    return Molecule(
        name=target,
        formula=formula,
        elements=[],
        molecular_weight=molecular_weight,
        iupac_name="",
        smiles="",
        cid=None,
        melting_point=None,
        boiling_point=None,
        density=None,
        state=None,
    )


def fetch_external_molecule(value):
    """Try public chemistry sources once the local JSON does not contain the molecule."""
    target = _normalize_molecule_value(value)
    if not target:
        return None

    # PubChem is the first external source because it is the most complete.
    cid = _find_cid(target)
    if cid is None:
        chemspider_molecule = _fetch_chemspider_molecule(target)
        if chemspider_molecule is not None:
            return chemspider_molecule
        return _fetch_nist_molecule(target)

    properties = _get_basic_properties(cid)
    if properties is None:
        chemspider_molecule = _fetch_chemspider_molecule(target)
        if chemspider_molecule is not None:
            return chemspider_molecule
        return _fetch_nist_molecule(target)

    view_data = _get_view_data(cid)
    melting_point = _get_first_temperature(view_data, "Melting Point") if view_data else None
    boiling_point = _get_first_temperature(view_data, "Boiling Point") if view_data else None
    density = _get_first_density(view_data) if view_data else None
    state = _determine_state(melting_point, boiling_point, temperature=25.0) if melting_point is not None and boiling_point is not None else None

    return Molecule(
        name=target,
        formula=properties.get("MolecularFormula", ""),
        elements=[],
        molecular_weight=properties.get("MolecularWeight", 0),
        iupac_name=properties.get("IUPACName", ""),
        smiles=properties.get("SMILES", ""),
        cid=properties.get("CID", cid),
        melting_point=melting_point,
        boiling_point=boiling_point,
        density=density,
        state=state,
    )


def _find_cid(value):
    """
    Find a PubChem CID.

    Tries the input as:
    1. Chemical name
    2. Molecular formula
    """

    if value is None:
        return None

    encoded_value = urllib.parse.quote(str(value), safe="")

    # ---------------------------------------------------------
    # Try chemical name
    # ---------------------------------------------------------
    url = (
        f"{PUBCHEM_BASE_URL}/compound/name/"
        f"{encoded_value}/cids/JSON"
    )

    data = _get_json(url)

    if data:
        identifier_list = data.get("IdentifierList", {})
        cids = identifier_list.get("CID", [])
        if cids:
            return cids[0]

    # ---------------------------------------------------------
    # Try molecular formula
    # ---------------------------------------------------------
    url = (
        f"{PUBCHEM_BASE_URL}/compound/fastformula/"
        f"{encoded_value}/cids/JSON"
    )

    data = _get_json(url)

    if data:
        identifier_list = data.get("IdentifierList", {})
        cids = identifier_list.get("CID", [])
        if cids:
            return cids[0]

    return None


def _get_basic_properties(cid):
    """Get basic molecular properties from PubChem."""

    url = (
        f"{PUBCHEM_BASE_URL}/compound/cid/{cid}/property/"
        "MolecularFormula,MolecularWeight,IUPACName,SMILES/JSON"
    )

    data = _get_json(url)

    if not data:
        return None

    try:
        return data["PropertyTable"]["Properties"][0]

    except (KeyError, IndexError, TypeError):
        return None


def _get_view_data(cid):
    """
    Get the complete PUG-View record.

    PUG-View contains experimental properties such as:
    - Melting Point
    - Boiling Point
    - Density
    """

    url = (
        f"{PUBCHEM_VIEW_URL}/data/compound/{cid}/JSON"
    )

    return _get_json(url)


def _walk_sections(obj):
    """Recursively find PubChem PUG-View sections."""

    if isinstance(obj, dict):

        if "TOCHeading" in obj:
            yield obj

        for value in obj.values():
            yield from _walk_sections(value)

    elif isinstance(obj, list):

        for item in obj:
            yield from _walk_sections(item)


def _find_section(data, heading):
    """Find a PUG-View section by heading."""

    if not data:
        return None

    for section in _walk_sections(data):

        if section.get("TOCHeading", "").lower() == heading.lower():
            return section

    return None


def _extract_text(value):
    """
    Convert PubChem's nested Value structure into text.
    """

    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, list):
        return " ".join(
            text
            for item in value
            if (text := _extract_text(item))
        )

    if isinstance(value, dict):

        # Common PubChem formats
        for key in (
            "StringWithMarkup",
            "String",
            "StringValue",
        ):
            if key in value:
                text = _extract_text(value[key])

                if text:
                    return text

        for key in (
            "Number",
            "FloatValue",
        ):
            if key in value:
                return str(value[key])

        # Fallback
        return " ".join(
            text
            for item in value.values()
            if (text := _extract_text(item))
        )

    return ""


def _get_section_values(data, heading):
    """
    Get the text values reported in a PubChem section.
    """

    section = _find_section(data, heading)

    if not section:
        return []

    values = []

    for information in section.get("Information", []):

        if not isinstance(information, dict):
            continue

        value = information.get("Value")

        text = _extract_text(value)

        if text:
            values.append(text.strip())

    return values


def _parse_temperature(text):
    """
    Convert a temperature string into Celsius.

    Examples:
        "78 °C"       -> 78.0
        "78-80 °C"    -> 79.0
        "172 °F"      -> 77.777...
        "351 K"       -> 77.85

    Returns None if no temperature can be extracted.
    """

    if not text:
        return None

    # ---------------------------------------------------------
    # Find numbers
    # ---------------------------------------------------------
    numbers = re.findall(
        r"[-+]?\d+(?:\.\d+)?",
        text
    )

    if not numbers:
        return None

    values = [float(number) for number in numbers]

    # If it's a range, use the average
    value = sum(values[:2]) / min(len(values), 2)

    text_lower = text.lower()

    # ---------------------------------------------------------
    # Convert to Celsius
    # ---------------------------------------------------------
    if "°f" in text_lower or "deg f" in text_lower:
        return (value - 32) * 5 / 9

    if re.search(r"\bk\b", text_lower):
        return value - 273.15

    # Default / expected unit
    return value


def _parse_density(text):
    """
    Convert density to g/cm^3.

    Examples:
        "1.05 g/mL"  -> 1.05
        "1.05 g/cm3" -> 1.05
        "1050 kg/m3" -> 1.05
        "1.05 g/cm³" -> 1.05
    """

    if not text:
        return None

    match = re.search(
        r"[-+]?\d+(?:\.\d+)?",
        text
    )

    if not match:
        return None

    value = float(match.group(0))
    text_lower = text.lower()

    # ---------------------------------------------------------
    # Convert to g/cm^3
    # ---------------------------------------------------------

    if "kg/m3" in text_lower or "kg/m³" in text_lower:
        return value / 1000

    if "mg/ml" in text_lower:
        return value / 1000

    # g/mL and g/cm3 are numerically equivalent
    if "g/ml" in text_lower:
        return value

    if "g/cm3" in text_lower or "g/cm³" in text_lower:
        return value

    # If PubChem didn't provide a recognizable unit,
    # assume g/cm3 because that is the unit used by this app.
    return value


def _get_first_temperature(data, heading):
    """Get the first reported temperature in Celsius."""

    values = _get_section_values(data, heading)

    for value in values:

        temperature = _parse_temperature(value)

        if temperature is not None:
            return temperature

    return None


def _get_first_density(data):
    """Get the first reported density in g/cm3."""

    values = _get_section_values(data, "Density")

    for value in values:

        density = _parse_density(value)

        if density is not None:
            return density

    return None


def _determine_state(
    melting_point,
    boiling_point,
    temperature=25.0,
):
    """
    Determine physical state at 25 °C.

    Assumes approximately 1 atm pressure.
    """

    if melting_point is None or boiling_point is None:
        return None

    if temperature < melting_point:
        return "solid"

    if temperature >= boiling_point:
        return "gas"

    return "liquid"


def fetch_pubchem_molecule(value):
    """
    Look up a molecule locally, then using PubChem and fallback sources.

    `value` can be:
        - chemical name: "water"
        - molecular formula: "H2O"

    Returns:
        Molecule instance
        or None if the molecule cannot be found.
    """

    local_match = _find_local_molecule(value)
    if local_match is not None:
        return local_match

    # ---------------------------------------------------------
    # Search external chemistry sources when not in the local dataset.
    # ---------------------------------------------------------
    external_match = fetch_external_molecule(value)
    return external_match



MOLECULES = [Molecule(item["name"], item["formula"], item["elements"], item["molecular_weight"], item["iupac_name"] or "", item["smiles"] or "", item["cid"], item["melting_point"], item["boiling_point"], item["density"], item["state"]) for item in molecules]

MOLECULES_BY_FORMULA = {molecule.formula: molecule for molecule in MOLECULES}

def molecule_bond_energy(formula):
    molecule = MOLECULES_BY_FORMULA.get(formula)
    return molecule.total_bond_energy if molecule is not None else 0



class Reaction:
    __slots__ = ("id", "name", "equation", "reaction_type", "reversible", "reactants", "products", "conditions", "notes", "source")
    def __init__(self, id_, name, reaction_type, reversible, reactants, products, conditions, notes, source="", equation=None):
        self.id = id_
        self.name = name
        self.reaction_type = reaction_type
        self.reversible = reversible
        self.reactants = reactants
        self.products = products
        self.conditions = conditions
        self.notes = notes
        self.source = source

        # Remote databases often provide a curated equation that should be preserved
        # verbatim rather than reconstructed from the local participant schema.
        if equation is not None:
            self.equation = str(equation)
        else:
            subscript_digits = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
            reactant_text = " + ".join(
                f"{item['stoichiometric_coefficient']} {item['molecule'].translate(subscript_digits)}"
                for item in reactants
            )
            product_text = " + ".join(
                f"{item['stoichiometric_coefficient']} {item['molecule'].translate(subscript_digits)}"
                for item in products
            )
            arrow = " ⇌ " if self.reversible is True else " → " if self.reversible is False else " = "
            self.equation = f"{reactant_text}{arrow}{product_text}"

            if reversible is not None:
                reactant_energy = sum(
                    molecule_bond_energy(item["molecule"]) * item["stoichiometric_coefficient"]
                    for item in reactants
                )
                product_energy = sum(
                    molecule_bond_energy(item["molecule"]) * item["stoichiometric_coefficient"]
                    for item in products
                )
                total_energy = reactant_energy - product_energy
                self.equation += f"\tΔH={total_energy}kJ/mol"
            if self.conditions:
                self.equation += "\nConditions:\n"
                for i in self.conditions:
                    self.equation += f"\t{i}: {self.conditions[i]}\n"
    def __str__(self):
        return self.equation
    def __repr__(self):
        return self.name


REACTIONS = [Reaction(item["id"], item["name"], item["reaction_type"], item["reversible"], item["reactants"], item["products"], item["conditions"], item["notes"], item.get("source", "")) for item in reactions]


def find_molecule(value):
    """Find a built-in molecule by name, formula, or IUPAC name."""
    return _find_local_molecule(value)


def find_reaction(value, external=True):
    """Find a local reaction first, then optionally query Rhea and Chempirical."""
    target = str(value).strip()
    folded = target.casefold()
    if not folded:
        return None
    for reaction in REACTIONS:
        if str(reaction.id).casefold() == folded:
            return reaction
    local = next((r for r in REACTIONS if folded in r.name.casefold() or folded in r.equation.casefold()), None)
    if local is not None or not external:
        return local
    # External sources are strictly a fallback: the bundled Reactions.json remains
    # the first source and all existing offline searches continue to work.
    for lookup in (_fetch_chempirical_reaction, _fetch_rhea_reaction):
        try:
            found = lookup(target)
        except Exception:
            found = None
        if found is not None:
            return found
    return None


REACTION_API_TIMEOUT = 8
RHEA_API_URL = "https://www.rhea-db.org/rhea/"
CHEMPIRICAL_API_URL = "https://chempirical.com/api/reactions"


def _reaction_api_json(url, timeout=REACTION_API_TIMEOUT):
    """Fetch a JSON API response; failures are non-fatal for optional lookups."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"ChemQL/{__version__} (reaction lookup; contact: chemql-user)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def _reaction_api_text(url, timeout=REACTION_API_TIMEOUT):
    """Fetch plain-text (TSV) data from Rhea."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"ChemQL/{__version__} (reaction lookup; contact: chemql-user)",
            "Accept": "text/tab-separated-values,text/plain,*/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return ""


def _remote_reaction(reaction_id, name, equation, reaction_type, source, notes="", conditions=None, reversible=None, reactants=None, products=None):
    """Adapt a remote reaction into ChemQL's Reaction type with participant data."""
    if not name and not equation:
        return None
    reactants = reactants if isinstance(reactants, list) else []
    products = products if isinstance(products, list) else []
    if reversible is None and equation:
        reversible = "⇌" in equation or "<=>" in equation or "<->" in equation
    return Reaction(
        str(reaction_id or f"{source}:unknown"),
        str(name or reaction_id or "External reaction"),
        str(reaction_type or "Unknown"),
        reversible,
        reactants,
        products,
        conditions if isinstance(conditions, dict) else {},
        str(notes or ""),
        str(source),
        equation=str(equation or "Equation unavailable"),
    )


def _chempirical_participant(item):
    """Convert a Chempirical participant to ChemQL's participant shape."""
    if not isinstance(item, dict):
        return None
    molecule = item.get("formula") or item.get("chemical_formula") or item.get("name") or item.get("molecule")
    if not molecule:
        return None
    coefficient = item.get("stoichiometry", item.get("coefficient", item.get("equivalents", 1)))
    try:
        coefficient = float(coefficient)
        if coefficient.is_integer():
            coefficient = int(coefficient)
    except (TypeError, ValueError):
        coefficient = 1
    return {"molecule": str(molecule), "stoichiometric_coefficient": coefficient}


def _fetch_chempirical_reaction(value):
    """Search Chempirical, requiring a relevant, reaction-like result."""
    url = CHEMPIRICAL_API_URL + "?" + urllib.parse.urlencode({"q": value, "limit": 10, "offset": 0})
    data = _reaction_api_json(url)
    if not isinstance(data, dict):
        return None
    results = data.get("results", [])
    if not isinstance(results, list) or not results:
        return None
    target = str(value).strip().casefold()

    # Never accept the API's first result blindly. Require the query to match a
    # meaningful reaction field, then prefer exact name/slug matches.
    candidates = [item for item in results if isinstance(item, dict)]
    def fields(item):
        return [str(item.get(key, "")).casefold() for key in ("name", "slug", "equation", "summary", "reaction_type")]
    relevant = [item for item in candidates if any(target in field for field in fields(item) if field)]
    if not relevant:
        return None
    row = next((item for item in relevant if target in {
        str(item.get("name", "")).casefold(), str(item.get("slug", "")).casefold()
    }), relevant[0])
    slug = row.get("slug")
    detail = _reaction_api_json(CHEMPIRICAL_API_URL + "/" + urllib.parse.quote(str(slug), safe="")) if slug else None
    record = detail if isinstance(detail, dict) else row
    participants = record.get("participants", [])
    if not isinstance(participants, list):
        participants = []
    reactants = []
    products = []
    for participant in participants:
        if not isinstance(participant, dict):
            continue
        role = str(participant.get("role", "")).casefold()
        converted = _chempirical_participant(participant)
        if converted is None:
            continue
        if role in {"reactant", "reagent", "substrate"}:
            reactants.append(converted)
        elif role in {"product", "products"}:
            products.append(converted)

    equation = str(record.get("equation") or row.get("equation") or "").strip()
    if not equation and reactants and products:
        def term(item):
            coeff = item["stoichiometric_coefficient"]
            return (f"{coeff} " if coeff != 1 else "") + item["molecule"]
        equation = " + ".join(term(item) for item in reactants) + " → " + " + ".join(term(item) for item in products)
    # Some API responses provide a display equation but omit structured
    # participants. Parse the equation as a fallback so the object is useful.
    if equation and (not reactants or not products):
        parsed_reactants, parsed_products = _parse_remote_equation(equation)
        if not reactants:
            reactants = parsed_reactants
        if not products:
            products = parsed_products

    # An external hit must actually describe a reaction. Reject records that
    # only have a product/name (which caused outputs like "→ (S)-1-Phenylpropanol").
    has_both_sides = bool(reactants and products)
    if not has_both_sides and equation:
        arrow = next((a for a in ("⇌", "<=>", "<->", "→", "->", "=") if a in equation), None)
        if arrow:
            left, right = equation.split(arrow, 1)
            has_both_sides = bool(left.strip() and right.strip())
    if not has_both_sides:
        return None

    conditions = record.get("conditions", {})
    if isinstance(conditions, list):
        conditions = {f"condition_{i + 1}": item for i, item in enumerate(conditions)}
    notes = record.get("summary", row.get("summary", ""))
    source = record.get("source", row.get("source", "Chempirical"))
    if isinstance(source, dict):
        source = source.get("name") or source.get("label") or "Chempirical"
    return _remote_reaction(
        record.get("slug") or row.get("slug"), record.get("name") or row.get("name"),
        equation, record.get("reaction_type") or row.get("reaction_type"),
        "Chempirical: " + str(source or "Chempirical"), notes, conditions,
        reactants=reactants, products=products,
    )


def _parse_remote_equation(equation):
    """Best-effort participant extraction from a plain-text chemical equation."""
    if not equation:
        return [], []
    arrow = next((a for a in ("⇌", "<=>", "<->", "→", "->", "=", "⇄") if a in equation), None)
    if not arrow:
        return [], []
    left, right = equation.split(arrow, 1)
    def parse_side(side):
        output = []
        for raw_term in re.split(r"\s+\+\s+", side.strip()):
            term = raw_term.strip()
            if not term:
                continue
            match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s+(.+)$", term)
            if match:
                coefficient, molecule = match.groups()
                number = float(coefficient)
                if number.is_integer():
                    number = int(number)
            else:
                number, molecule = 1, term
            output.append({"molecule": molecule.strip(), "stoichiometric_coefficient": number})
        return output
    return parse_side(left), parse_side(right)


def _fetch_rhea_reaction(value):
    """Search Rhea's TSV REST endpoint and only accept a relevant result."""
    target = value.strip()
    if target.casefold().startswith("rhea:"):
        query = "rhea-id:" + target.split(":", 1)[1]
    else:
        # Rhea supports fielded queries; a general query is useful for equation or
        # participant-name searches and keeps all query escaping in urlencode.
        query = target
    params = urllib.parse.urlencode({
        "query": query,
        "columns": "rhea-id,equation,chebi,ec",
        "format": "tsv",
        "limit": 5,
    })
    text = _reaction_api_text(RHEA_API_URL + "?" + params)
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    headers = lines[0].split("\t")
    rows = [dict(zip(headers, line.split("\t"))) for line in lines[1:]]
    target_folded = target.casefold()
    row = next((item for item in rows if item.get("rhea-id", "").casefold() == target_folded), None)
    if row is None:
        row = next((item for item in rows if any(
            target_folded in item.get(field, "").casefold()
            for field in ("equation", "chebi", "ec")
        )), None)
    if row is None:
        return None
    reaction_id = row.get("rhea-id", "")
    ec = row.get("ec", "")
    chebi = row.get("chebi", "")
    notes = ""
    if ec:
        notes += "EC: " + ec
    if chebi:
        notes += ("; " if notes else "") + "Participants: " + chebi
    equation = row.get("equation", "")
    reactants, products = _parse_remote_equation(equation)
    if not reactants or not products:
        return None
    return _remote_reaction(
        reaction_id, reaction_id, equation, "Biochemical", "Rhea", notes,
        reactants=reactants, products=products,
    )


def search_reactions(**criteria):
    """Search reactions by fields; string criteria are case-insensitive substrings."""
    unknown = set(criteria) - set(reactionKeys)
    if unknown:
        raise ValueError("Unknown reaction field(s): " + ", ".join(sorted(unknown)))
    result = []
    for reaction in REACTIONS:
        if all((str(expected).casefold() in str(getattr(reaction, key)).casefold())
               if isinstance(expected, str) and isinstance(getattr(reaction, key), str)
               else getattr(reaction, key) == expected for key, expected in criteria.items()):
            result.append(reaction)
    return result

reactionKeys = ("id", "name", "equation", "reaction_type", "reversible", "reactants", "products", "conditions", "notes", "source")
del elements
del reactions
del molecules


def _formula_counts(formula):
    if not isinstance(formula, str) or not formula:
        raise ValueError("Chemical formulas must be non-empty strings")
    symbols = {element.symbol for element in ELEMENTS}

    def parse_group(index, nested=False):
        counts = {}
        while index < len(formula):
            char = formula[index]
            if char == ")":
                if not nested:
                    raise ValueError(f"Unmatched closing parenthesis in formula `{formula}`")
                return counts, index
            if char == "(":
                group, index = parse_group(index + 1, True)
                if index >= len(formula) or formula[index] != ")":
                    raise ValueError((f"Unclosed parenthesis in formula `{formula}`" if NO_ANSI else f"Unclosed parenthesis in formula \033[1m{formula}\033[22m"))
                index += 1
                match = re.match(r"\d+", formula[index:])
                multiplier = int(match.group()) if match else 1
                if multiplier <= 0:
                    raise ValueError((f"Invalid atom count in formula `{formula}`" if NO_ANSI else f"Invalid atom count in formula \033[1m{formula}\033[22m"))
                if match:
                    index += len(match.group())
                for symbol, amount in group.items():
                    counts[symbol] = counts.get(symbol, 0) + amount * multiplier
                continue
            if not char.isupper():
                raise ValueError((f"Invalid chemical formula `{formula}`" if NO_ANSI else f"Invalid chemical formula \033[1m{formula}\033[22m"))
            end = index + 1
            if end < len(formula) and formula[end].islower():
                end += 1
            symbol = formula[index:end]
            if symbol not in symbols:
                raise ValueError((f"Unknown element `{symbol}` in formula `{formula}`" if NO_ANSI else f"Unknown element `{symbol}` in formula \033[1m{formula}\033[22m"))
            index = end
            match = re.match(r"\d+", formula[index:])
            amount = int(match.group()) if match else 1
            if amount <= 0:
                raise ValueError((f"Invalid atom count in formula `{formula}`" if NO_ANSI else f"Invalid atom count in formula \033[1m{formula}\033[22m"))
            if match:
                index += len(match.group())
            counts[symbol] = counts.get(symbol, 0) + amount
        if nested:
            raise ValueError((f"Unclosed parenthesis in formula `{formula}`" if NO_ANSI else f"Unclosed parenthesis in formula \033[1m{formula}\033[22m"))
        return counts, index

    counts, end = parse_group(0)
    if end != len(formula) or not counts:
        raise ValueError((f"Invalid chemical formula `{formula}`" if NO_ANSI else f"Invalid chemical formula \033[1m{formula}\033[22m"))
    return counts


def _stoichiometric_species(side):
    if isinstance(side, str):
        species = [item.strip() for item in side.split("+")]
    else:
        species = [str(item).strip() for item in side]
    if not species or any(not item for item in species):
        raise ValueError("Both sides of a reaction must contain molecules")
    return species


def balance_stoichiometry(reactants, products, reversible=None):
    """Balance a reaction and return it as a :class:`Reaction`."""
    reactant_formulas = _stoichiometric_species(reactants)
    product_formulas = _stoichiometric_species(products)
    formulas = reactant_formulas + product_formulas
    formulas_by_element = [_formula_counts(formula) for formula in formulas]
    elements = list(dict.fromkeys(
        element for counts in formulas_by_element for element in counts
    ))
    matrix = [
        [
            Fraction(counts.get(element, 0) * (1 if index < len(reactant_formulas) else -1))
            for index, counts in enumerate(formulas_by_element)
        ]
        for element in elements
    ]

    pivot_columns = []
    pivot_row = 0
    for column in range(len(formulas)):
        selected = next(
            (row for row in range(pivot_row, len(matrix)) if matrix[row][column]),
            None,
        )
        if selected is None:
            continue
        matrix[pivot_row], matrix[selected] = matrix[selected], matrix[pivot_row]
        divisor = matrix[pivot_row][column]
        matrix[pivot_row] = [value / divisor for value in matrix[pivot_row]]
        for row in range(len(matrix)):
            if row == pivot_row or not matrix[row][column]:
                continue
            factor = matrix[row][column]
            matrix[row] = [
                value - factor * pivot
                for value, pivot in zip(matrix[row], matrix[pivot_row])
            ]
        pivot_columns.append(column)
        pivot_row += 1
        if pivot_row == len(matrix):
            break

    free_columns = [
        column for column in range(len(formulas)) if column not in pivot_columns
    ]
    if len(free_columns) != 1:
        raise ValueError("Reaction does not have a unique stoichiometric balance")
    coefficients = [Fraction(0) for _ in formulas]
    free_column = free_columns[0]
    coefficients[free_column] = Fraction(1)
    for row, column in enumerate(pivot_columns):
        coefficients[column] = -matrix[row][free_column]
    if all(value < 0 for value in coefficients):
        coefficients = [-value for value in coefficients]
    if any(value <= 0 for value in coefficients):
        raise ValueError("Reaction cannot be balanced with positive coefficients")

    denominator = 1
    for coefficient in coefficients:
        denominator = denominator * coefficient.denominator // gcd(
            denominator, coefficient.denominator
        )
    integer_coefficients = [
        int(coefficient * denominator) for coefficient in coefficients
    ]
    common_divisor = reduce(gcd, integer_coefficients)
    integer_coefficients = [value // common_divisor for value in integer_coefficients]
    participants = [
        {
            "molecule": formula,
            "stoichiometric_coefficient": coefficient,
        }
        for formula, coefficient in zip(formulas, integer_coefficients)
    ]
    split_at = len(reactant_formulas)
    return Reaction(
        "BALANCED",
        "Balanced reaction",
        "balanced",
        reversible,
        participants[:split_at],
        participants[split_at:],
        {},
        "",
    )


def _execute_balance_command(text):
    text = text.split("//", 1)[0].rstrip()
    match = re.fullmatch(
        r"\s*balance\s+(.+?)\s*(<->|->)\s*(.+?)\s*",
        text,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError("Usage: balance <reactants> ->|<-> <products>")
    reactants, arrow, products = match.groups()
    reversible = arrow == "<->"
    return balance_stoichiometry(reactants, products, reversible)



def queryElement(key, func, value, *params):
    if key not in elementKeys:
        return f"There is no key `{key}`"

    for element in ELEMENTS:
        if getattr(element[key], func)(value, *params):
            return element

    return f"Turns out no element has a {key} of {value}"


def queryElementLast(key, func, value, *params):
    if key not in elementKeys:
        raise KeyError((f"There is no key `{key}`" if NO_ANSI else f"There is no key \033[1m{key}\033[22m"))

    for element in reversed(ELEMENTS):
        if getattr(element[key], func)(value, *params):
            return element

    return f"Turns out no element has a {key} of {value}"


def queryElementAll(key, func, value, *params):
    if key not in elementKeys:
        raise KeyError((f"There is no key `{key}`" if NO_ANSI else f"There is no key \033[1m{key}\033[22m"))

    found = False

    for element in ELEMENTS:
        if getattr(element[key], func)(value, *params):
            found = True
            yield element

    if not found:
        return

class ReturnTable(dict):
    """Dictionary result that prints as a table in the REPL."""

    def __str__(self):
        return format_return_table(self)


def format_return_table(data):
    if not data:
        return ""

    columns = list(data.keys())
    rows = []
    row_count = max((len(data[column]) for column in columns), default=0)

    for i in range(row_count):
        rows.append([str(data[column][i]) if i < len(data[column]) else "" for column in columns])

    widths = [max(len(str(column)), *(len(row[index]) for row in rows)) for index, column in enumerate(columns)]

    header = "  ".join(
        str(column).upper().ljust(widths[index])
        for index, column in enumerate(columns)
    ).rstrip()

    separator = ''.join("─" * i for i  in widths) + "──" *(len(data.keys()) - 1)

    body = ["  ".join(row[index].ljust(widths[index]) for index in range(len(columns))).rstrip() for row in rows]

    return "\n".join([header, separator, *body])


def project_results(results, attributes):
    """Return one column as a 1D list, or multiple columns as a dict of 1D lists."""

    if len(attributes) == 1:
        return [getattr(item, attributes[0]) for item in results]

    return ReturnTable({attribute: [getattr(item, attribute) for item in results] for attribute in attributes})


def sort_results(results, key, descending=False):
    try:
        return sorted(
            results,
            key=lambda item: getattr(item, key),
            reverse=descending
        )
    except (TypeError, AttributeError):
        raise ValueError((f"Cannot sort by `{key}`" if NO_ANSI else f"Cannot sort by \033[1m{key}\033[22m"))

def apply_query_operations(results, tokens, keys, positions=None):
    i = 0

    while i < len(tokens):
        token = tokens[i]

        # sort
        if token == "sort":
            if i + 1 >= len(tokens):
                raise ChemQLError(("Expected a key after `sort`" if NO_ANSI else "Expected a key after \033[1msort\033[22m"), *(error_position(positions, i) if positions else (None, 1))) #type:ignore

            key = tokens[i + 1]

            if key not in keys:
                pos, length = error_position(positions, i + 1) if positions else (None, 1)
                raise ChemQLError((f"There is no key `{key}`" if NO_ANSI else f"There is no key \033[1m{key}\033[22m"), pos, length)

            descending = False

            if i + 2 < len(tokens):
                direction = tokens[i + 2].lower()

                if direction == "asc":
                    i += 1

                elif direction == "desc":
                    descending = True
                    i += 1

            try:
                results = sort_results(
                    results,
                    key,
                    descending
                )
            except ValueError as e:
                pos, length = error_position(positions, i + 1) if positions else (None, 1)
                raise ChemQLError(str(e), pos, length) from e

            i += 2

        # limit
        elif token == "limit":
            if i + 1 >= len(tokens):
                raise ChemQLError(("Expected a number after `limit`" if NO_ANSI else "Expected a number after \033[1mlimit\033[22m"), *(error_position(positions, i) if positions else (None, 1)))#type:ignore

            try:
                amount = int(tokens[i + 1])
            except ValueError:
                pos, length = error_position(positions, i + 1) if positions else (None, 1)
                raise ChemQLError(("`limit` requires an integer" if NO_ANSI else "\033[1mlimit\033[22m requires an integer"), pos, length)

            if amount < 0:
                pos, length = error_position(positions, i + 1) if positions else (None, 1)
                raise ChemQLError(("`limit` cannot be negative" if NO_ANSI else "\033[1mlimit\033[22m cannot be negative"), pos, length)

            results = results[:amount] # type: ignore

            i += 2

        # count
        elif token == "count":
            if i + 1 < len(tokens):
                pos, length = error_position(positions, i) if positions else (None, 1)
                raise ChemQLError(("`count` must be the final query operation" if NO_ANSI else "\033[1mcount\033[22m must be the final query operation"), pos, length)

            results = len(results) # type: ignore
            i += 1

        else:
            pos, length = error_position(positions, i) if positions else (None, 1)
            raise ChemQLError((f"Unknown query operation `{token}`" if NO_ANSI else f"Unknown query operation \033[1m{token}\033[22m"), pos, length)

    return results


functionMap = {"=": "__eq__", "!=": "__ne__", ">": "__gt__", "<": "__lt__", ">=": "__ge__", "<=": "__le__"}


def convert_value(value, sample):
    """Convert a query value to the type of the element value."""

    if isinstance(sample, bool):

        if value.lower() == "true":
            return True

        if value.lower() == "false":
            return False

        raise ValueError((f"`{value}` is not a boolean" if NO_ANSI else f"\033[1m{value}\033[22m is not a boolean"))

    if isinstance(sample, (int, float)):

        try:
            number = float(value)

            if number.is_integer():
                return int(number)

            return number

        except ValueError:
            raise ValueError((f"`{value}` is not a number" if NO_ANSI else f"\033[1m{value}\033[22m is not a number"))

    return value


def tokenize_query(arguments):
    """Convert tokens into a form suitable for parsing."""

    return arguments


def parse_condition(tokens, index, source, keys, positions=None):
    if index + 2 >= len(tokens):
        raise ChemQLError("Incomplete condition", *(error_position(positions, index) if positions else (None, 1)))#type:ignore

    key = tokens[index]
    operator = tokens[index + 1]
    negated = operator.casefold() == "not"
    if negated:
        if index + 3 >= len(tokens):
            raise ChemQLError(("Expected an operator and value after `not`" if NO_ANSI else "Expected an operator and value after \033[1mnot\033[22m"), *(error_position(positions, index + 1) if positions else (None, 1)))  # type: ignore
        operator = tokens[index + 2]
        value = tokens[index + 3]
        consumed = index + 4
    else:
        value = tokens[index + 2]
        consumed = index + 3

    if key not in keys:
        pos, length = error_position(positions, index) if positions else (None, 1)
        raise ChemQLError((f"There is no key `{key}`" if NO_ANSI else f"There is no key \033[1m{key}\033[22m"), pos, length)

    if operator in {"like", "like!", "likep"}:
        pattern = value
        if operator == "likep":
            try:
                compiled_pattern = re.compile(pattern)
            except re.error as exc:
                pos, length = error_position(positions, index + 2) if positions else (None, 1)
                raise ChemQLError(f"Invalid regex: {exc}", pos, length) from exc

            def regex_condition(item):
                actual = getattr(item, key)
                return isinstance(actual, str) and compiled_pattern.search(actual) is not None

            return (lambda item, fn=regex_condition: not fn(item)) if negated else regex_condition, consumed
        case_sensitive = operator == "like!"

        def like_condition(item):
            actual = getattr(item, key)

            if not isinstance(actual, str):
                return False

            return like_match(
                actual,
                pattern,
                case_sensitive
            )

        return (lambda item, fn=like_condition: not fn(item)) if negated else like_condition, consumed

    if operator == "has":
        def contains_nested(actual, expected, field_name=None):
            """Search nested values, matching chemical molecule IDs exactly.

            A molecule field must use equality rather than substring matching:
            ``O2`` is not a reactant just because the formula ``CO2`` contains
            those characters. Other descriptive strings may use substring
            matching, preserving the general-purpose behavior of ``has``.
            """
            if isinstance(actual, str):
                if isinstance(field_name, str) and field_name.casefold() == "molecule":
                    return actual.casefold() == expected.casefold()
                return expected.casefold() in actual.casefold()

            if isinstance(actual, dict):
                for nested_key, nested_value in actual.items():
                    if contains_nested(nested_value, expected, nested_key):
                        return True
                return any(
                    isinstance(nested_key, str)
                    and nested_key.casefold() == expected.casefold()
                    for nested_key in actual.keys()
                )

            if isinstance(actual, (list, tuple, set, frozenset)):
                return any(
                    contains_nested(value_item, expected, field_name)
                    for value_item in actual
                )

            if actual is None:
                return False

            return str(actual).casefold() == expected.casefold()

        def has_condition(item):
            actual = getattr(item, key)
            return contains_nested(actual, value)

        return (lambda item, fn=has_condition: not fn(item)) if negated else has_condition, consumed

    if operator not in functionMap:
        pos, length = error_position(positions, index + 1) if positions else (None, 1)
        raise ChemQLError((f"Unknown operator `{operator}`" if NO_ANSI else f"Unknown operator \033[1m{operator}\033[22m"), pos, length)

    sample = getattr(source[0], key)

    try:
        value = convert_value(value, sample)
    except ValueError as e:
        pos, length = error_position(positions, index + 2) if positions else (None, 1)
        raise ChemQLError(str(e), pos, length) from e

    function = functionMap[operator]

    def comparison_condition(item):
        try:
            return getattr(
                getattr(item, key),
                function
            )(value)
        except (TypeError, AttributeError):
            return False

    return (lambda item, fn=comparison_condition: not fn(item)) if negated else comparison_condition, consumed

def parse_primary(tokens, index, source, keys, positions=None):
    if index >= len(tokens):
        raise ChemQLError("Expected condition", *(error_position(positions, index) if positions else (None, 1)))#type:ignore

    if tokens[index].casefold() == "not":
        expression, next_index = parse_primary(tokens, index + 1, source, keys, positions)
        return (lambda item, fn=expression: not fn(item)), next_index

    if tokens[index] == "(":
        expression, index = parse_or(
            tokens,
            index + 1,
            source,
            keys,
            positions
        )

        if index >= len(tokens) or tokens[index] != ")":
            pos = positions[index][0] if positions and index < len(positions) else None
            raise ChemQLError(("Missing `)`" if NO_ANSI else "Missing \033[1m)\033[22m"), pos)

        return expression, index + 1

    return parse_condition(
        tokens,
        index,
        source,
        keys,
        positions
    )


def parse_and(tokens, index, source, keys, positions=None):
    left, index = parse_primary(
        tokens,
        index,
        source,
        keys,
        positions
    )

    while index < len(tokens) and tokens[index] == "and":
        right, index = parse_primary(
            tokens,
            index + 1,
            source,
            keys,
            positions
        )

        previous = left

        left = lambda item, a=previous, b=right: (
            a(item) and b(item)
        )

    return left, index


def parse_or(tokens, index, source, keys, positions=None):
    left, index = parse_and(
        tokens,
        index,
        source,
        keys,
        positions
    )

    while index < len(tokens) and tokens[index] == "or":
        right, index = parse_and(
            tokens,
            index + 1,
            source,
            keys,
            positions
        )

        previous = left

        left = lambda item, a=previous, b=right: (
            a(item) or b(item)
        )

    return left, index


def parse_query(tokens, source, keys, positions=None):
    if not tokens:
        raise ChemQLError("No conditions specified", *(error_position(positions, 0) if positions else (None, 1)))#type:ignore

    # Allow a query to operate on the entire source when it begins
    # with a query operation, e.g. `search molecules count`.
    if tokens[0] in queryOperations:
        return (lambda item: True), 0

    condition, index = parse_or(
        tokens,
        0,
        source,
        keys,
        positions
    )

    # Conditions end when a query operation begins.
    if index < len(tokens) and tokens[index] not in queryOperations:
        pos, length = error_position(positions, index) if positions else (None, 1)
        raise ChemQLError(
            (f"Unexpected `{tokens[index]}`" if NO_ANSI else f"Unexpected \033[1m{tokens[index]}\033[22m"), pos, length
        )

    return condition, index



SOURCES = {"elements": (ELEMENTS, elementKeys), "molecules": (MOLECULES, moleculeKeys), "reactions": (REACTIONS, reactionKeys)}


def get_source(source):
    return SOURCES.get(source)

current_source = None

REACTION_TEMPERATURE_TOLERANCE_K = 5.0
REACTION_PRESSURE_TOLERANCE = 0.05
reaction_state = {
    "temperature_k": None,
    "pressure_pa": None,
    "catalysts": [],
}

# Python variables persist for the whole session.
python_globals = {"__builtins__": __builtins__, "math": math, "error": None}
STRUCTS = {}
RECORDS = {}
ENUMS = {}

class ChemQLSignal(Exception):
    """A user-raised, recoverable ChemQL error."""
    def __init__(self, error_type):
        self.error_type = str(error_type)
        super().__init__(self.error_type)

CHEMQL_VARIABLES = set()

class ChemQLNamespace:
    """A namespace exposing only explicitly public members as attributes."""
    def __init__(self, name, parent=None):
        self.__dict__["_chemql_name"] = name
        self.__dict__["_chemql_parent"] = parent
        self.__dict__["_chemql_public"] = set()
        self.__dict__["_chemql_private"] = {}

    def _set_member(self, name, value, public=False):
        # Redefining a public member as private must revoke the old public binding.
        self.__dict__.pop(name, None)
        self.__dict__["_chemql_public"].discard(name)
        self.__dict__["_chemql_private"].pop(name, None)
        if public:
            self.__dict__[name] = value
            self.__dict__["_chemql_public"].add(name)
        else:
            self.__dict__["_chemql_private"][name] = value
            # Private names are available to code executing in the namespace,
            # but are deliberately not exposed through namespace.member.

NAMESPACES = {}
_CURRENT_NAMESPACE = None
_CURRENT_VISIBILITY = "private"

def _chemql_value(expression):
    """Resolve a native ChemQL variable, otherwise evaluate a query expression."""
    expression = expression.strip()
    if re.fullmatch(_DEFINITION_NAME, expression) and expression in CHEMQL_VARIABLES:
        return python_globals[expression]
    return execute_query_block(expression)


def find_matching(text, start, opening, closing):
    """Find the matching closing delimiter, allowing nested delimiters."""
    depth = 1
    i = start + len(opening)
    quote = None
    escaped = False

    while i < len(text):
        char = text[i]

        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            i += 1
            continue

        if char in ("'", '"'):
            quote = char
            i += 1
            continue

        if text.startswith(opening, i):
            depth += 1
            i += len(opening)
            continue

        if text.startswith(closing, i):
            depth -= 1
            if depth == 0:
                return i
            i += len(closing)
            continue

        i += 1

    raise SyntaxError((f"Missing `{closing}`" if NO_ANSI else f"Missing \033[1m{closing}\033[22m"))


def interpolate_query(text):
    """Evaluate [Python] expressions inside a query."""
    result = []
    i = 0

    while i < len(text):
        if text[i] == "[":
            end = find_matching(text, i, "[", "]")
            code = text[i + 1:end]
            value = evaluate_python(code)

            if isinstance(value, str):
                result.append(shlex.quote(value))
            elif value is None:
                result.append("None")
            else:
                result.append(shlex.quote(str(value)))

            i = end + 1
            continue

        result.append(text[i])
        i += 1

    return "".join(result)

def interpolate_python_queries(code):
    rewritten = []
    query_values = {}
    query_index = 0
    i = 0

    while i < len(code):
        if code.startswith("{{", i):
            end = find_matching(code, i, "{{", "}}")
            query = code[i + 2:end].strip()

            value = _chemql_value(query)

            name = f"__chemql_query_{query_index}"
            query_index += 1

            query_values[name] = value
            rewritten.append(name)

            i = end + 2
            continue

        rewritten.append(code[i])
        i += 1

    python_globals.update(query_values)
    return "".join(rewritten)

def _space_query_operators(text):
    """Separate comparison operators and parentheses outside quoted strings."""
    out, quote, escaped = [], None, False
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue
                # Preserve the compound operator "like!" as a single token.
        if text[i:i + 5].casefold() == "like!":
            before_ok = (
                i == 0 or not (
                    text[i - 1].isalnum() or text[i - 1] == "_"
                )
            )
            end = i + 5
            after_ok = (
                end == len(text) or not (
                    text[end].isalnum() or text[end] == "_"
                )
            )

            if before_ok and after_ok:
                out.extend((" ", text[i:end], " "))
                i = end
                continue
        if ch in "()":
            out.extend((" ", ch, " "))
            i += 1
            continue
        if ch in "<>!=" and i + 1 < len(text) and text[i + 1] == "=":
            out.extend((" ", ch + "=", " "))
            i += 2
            continue
        if ch in "<>!=":
            out.extend((" ", ch, " "))
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _split_set_operations(text):
    """Split top-level union/intersection outside quotes and parentheses, left-to-right."""
    parts, ops, start, depth = [], [], 0, 0
    quote, escaped = None, False
    words = re.finditer(r"\b(union|intersection)\b", text, re.IGNORECASE)
    for match in words:
        i = match.start()
        quote = None
        escaped = False
        depth = 0
        j = 0
        while j < i:
            ch = text[j]
            if quote:
                if escaped: escaped = False
                elif ch == "\\": escaped = True
                elif ch == quote: quote = None
            elif ch in ("'", '"'): quote = ch
            elif ch == "(": depth += 1
            elif ch == ")": depth -= 1
            j += 1
        if quote is None and depth == 0:
            parts.append(text[start:i].strip())
            ops.append(match.group(1).casefold())
            start = match.end()
    if not ops:
        return None
    parts.append(text[start:].strip())
    if any(not part for part in parts):
        raise ChemQLError("Missing query around union/intersection")
    return parts, ops


def _as_result_list(result):
    if result is None or result == "No matching item":
        return []
    return result if isinstance(result, list) else [result]


def execute_query_text(text):
    """Execute plain query-language text."""
    text = text.strip()
    text = _expand_function_calls(text)
    set_expression = _split_set_operations(text)
    if set_expression:
        parts, ops = set_expression
        result = _as_result_list(execute_query_text(parts[0]))
        for operator, part in zip(ops, parts[1:]):
            right = _as_result_list(execute_query_text(part))
            def identity(item):
                if hasattr(item, "id"): return ("id", getattr(item, "id"))
                if hasattr(item, "number"): return ("number", getattr(item, "number"))
                if hasattr(item, "cid") and getattr(item, "cid") is not None: return ("cid", getattr(item, "cid"))
                return (type(item).__name__, repr(item))
            right_map = {identity(item): item for item in right}
            if operator == "union":
                seen = {identity(item) for item in result}
                result.extend(item for item in right if identity(item) not in seen and not seen.add(identity(item)))
            else:
                result = [item for item in result if identity(item) in right_map]
        return result

    text = interpolate_query(text)
    text = _space_query_operators(text)
    positions = token_positions(text)

    try:
        arguments = shlex.split(text)
    except ValueError as e:
        raise ChemQLError(f"Query syntax error: {e}")

    try:
        return execute(arguments, text, positions)
    except ChemQLError as e:
        if e.position is None:
            raise
        raise


def execute_query(query: str) -> str | Molecule | Element | Reaction | list | None | Unknown:
    """Execute a Chemql query through the public programmatic API."""
    result = execute_query_text(query)

    if isinstance(result, (str, Molecule, Element, Reaction, Unknown)):
        return result

    # Keep the public API total for result types that have not yet been
    # given a dedicated return type (for example lists, ReturnTable, and
    # integer counts).
    return Unknown(result)


def execute_query_block(text):
    # Hybrid code needs the raw query result, so it intentionally bypasses
    # the public Unknown wrapper.
    return execute_query_text(text)


def evaluate_python(code):
    """Evaluate Python, with {{ query }} expressions available inside it.

    If the Python is an expression, its value is returned.
    Otherwise it is executed and None is returned.
    """
    query_values = {}
    rewritten = []
    i = 0
    query_index = 0

    while i < len(code):
        if code.startswith("{{", i):
            end = find_matching(code, i, "{{", "}}")
            query = code[i + 2:end].strip()
            query = _expand_function_calls(query)
            value = _chemql_value(query)

            name = f"__chemql_query_{query_index}"
            query_index += 1
            query_values[name] = value
            rewritten.append(name)
            i = end + 2
            continue

        rewritten.append(code[i])
        i += 1

    rewritten = "".join(rewritten)
    for type_name in (*STRUCTS.keys(), *RECORDS.keys()):
        rewritten = re.sub(r"\b" + re.escape(type_name) + r"\s*\{([^{}]*)\}",
                           lambda m, n=type_name: n + "(" + m.group(1) + ")", rewritten)
    rewritten = _expand_function_calls(rewritten)
    # ChemQL uses :: for namespace qualification; Python uses attribute dots.
    rewritten = re.sub(r"\b([A-Za-z_]\w*(?:::[A-Za-z_]\w*)+)",
                       lambda m: m.group(1).replace("::", "."), rewritten)

    python_globals.update(query_values)

    try:
        tree = ast.parse(rewritten, mode="eval")
    except SyntaxError:
        module = ast.parse(rewritten, mode="exec")
        for node in ast.walk(module):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                if isinstance(node.ctx, ast.Store) and node.id.isidentifier() and not node.id.startswith("__chemql_"):
                    CHEMQL_VARIABLES.add(node.id)
        exec(compile(module, "<embedded-python>", "exec"), python_globals)
        return None

    return eval(compile(tree, "<embedded-python>", "eval"), python_globals)


def is_python_block_header(text):
    """Recognize [for ...], [if ...], etc. without requiring a colon."""
    text = text.strip()

    if not (text.startswith("[") and text.endswith("]")):
        return False

    code = text[1:-1].strip()

    # Function placeholders such as \1 are substituted only when the function
    # is called. Replace them with harmless identifiers for block detection so
    # they cannot make a real `if`/`for`/`while` header look like an expression.
    code = re.sub(r"\\\d+", "__chemql_arg", code)

    # Replace {{...}} queries with valid Python variable names.
    while "{{" in code:
        start = code.index("{{")
        end = find_matching(code, start, "{{", "}}")
        code = code[:start] + "__chemql_query_placeholder" + code[end + 2:]

    try:
        tree = ast.parse(code + ":\n    pass", mode="exec")
    except SyntaxError:
        return False

    return bool(tree.body) and isinstance(
        tree.body[0],
        (
            ast.For,
            ast.While,
            ast.If,
            ast.With,
            ast.Try,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
        )
    )


def find_endblock(lines, start):
    """Find the matching terminator, including headers with \\N placeholders."""
    depth = 1
    for i in range(start, len(lines)):
        stripped = lines[i].strip().casefold()

        # Typed terminators and the normalized generic terminator close the
        # current block. Older source forms may still contain typed closers.
        if stripped in {"[endblock]", "endfor", "endwhile", "endif", "[endfor]", "[endwhile]", "[endif]"}:
            depth -= 1
            if depth == 0:
                return i
            continue

        if stripped in {"[else]"} or stripped.startswith("[elif "):
            continue

        # Detect structural headers by keyword, not by parsing their complete
        # expression. At this stage \\1 may still be unresolved or may
        # expand to a ChemQL struct representation that is not Python syntax.
        if re.match(r"^\[\s*(?:if|for|while)\b", stripped):
            depth += 1
    raise SyntaxError(("Missing block terminator (`endblock`, `endfor`, `endwhile`, or `endif`)" if NO_ANSI else "Missing block terminator (\033[1mendblock\033[22m, \033[1mendfor\033[22m, \033[1mendwhile\033[22m, or \033[1mendif\033[22m)"))


def remove_comments(line):
    in_quote = None
    escaped = False

    for i in range(len(line) - 1):
        char = line[i]

        if escaped:
            escaped = False
            continue

        if char == "\\" and in_quote:
            escaped = True
            continue

        if char in ('"', "'"):
            if in_quote is None:
                in_quote = char
            elif in_quote == char:
                in_quote = None
            continue

        if line[i:i + 2] == "//" and in_quote is None:
            return line[:i].rstrip()

    return line


class ChemQLBreak(Exception):
    pass
class ChemQLContinue(Exception):
    pass


def execute_for_block(header, body):
    code = header[1:-1].strip()
    code = interpolate_python_queries(code)

    tree = ast.parse(code + ":\n    pass", mode="exec")

    node = tree.body[0]

    if not isinstance(node, ast.For):
        raise SyntaxError(("Expected a `for` block" if NO_ANSI else "Expected a \033[1mfor\033[22m block"))

    iterable = eval(
        compile(ast.Expression(node.iter), "<embedded-python>", "eval"),
        python_globals
    )

    if not hasattr(iterable, "__iter__"):
        iterable = (iterable,)

    for value in iterable:
        temp_name = "__chemql_for_value"
        python_globals[temp_name] = value

        assignment = ast.Assign(
            targets=[node.target],
            value=ast.Name(
                id=temp_name,
                ctx=ast.Load()
            )
        )

        module = ast.Module(
            body=[assignment],
            type_ignores=[]
        )

        ast.fix_missing_locations(module)

        exec(
            compile(
                module,
                "<embedded-python>",
                "exec"
            ),
            python_globals
        )

        try:
            process_lines(body)

        except ChemQLContinue:
            continue

        except ChemQLBreak:
            break


def execute_while_block(header, body):
    code = header[1:-1].strip()

    tree = ast.parse(
        code + ":\n    pass",
        mode="exec"
    )

    node = tree.body[0]

    if not isinstance(node, ast.While):
        raise SyntaxError(("Expected a `while` block" if NO_ANSI else "Expected a \033[1mwhile\033[22m block"))

    while eval(
        compile(
            ast.Expression(node.test),
            "<embedded-python>",
            "eval"
        ),
        python_globals
    ):
        try:
            process_lines(body)

        except ChemQLContinue:
            continue

        except ChemQLBreak:
            break


def execute_if_block(header, body):
    """
    Execute an if/elif/else chain.

    The body contains the entire block, including any
    [elif ...] and [else] clauses.
    """

    sections = []

    current_header = header
    current_body = []

    depth = 0

    for line in body:
        stripped = line.strip()

        if is_python_block_header(stripped):
            depth += 1

        elif stripped == "[endblock]":
            depth -= 1

        # Only recognize elif/else belonging to THIS if.
        if depth == 0 and (
            stripped.startswith("[elif ")
            or stripped == "[else]"
        ):
            sections.append(
                (current_header, current_body)
            )

            current_header = stripped
            current_body = []

        else:
            current_body.append(line)

    sections.append(
        (current_header, current_body)
    )

    for section_header, section_body in sections:
        code = _expand_definitions(section_header[1:-1].strip())

        if code.startswith("if "):
            condition = code[3:].strip()

        elif code.startswith("elif "):
            condition = code[5:].strip()

        elif code == "else":
            process_lines(section_body)
            return

        else:
            raise SyntaxError(
                (f"Invalid conditional `{code}`" if NO_ANSI else f"Invalid conditional \033[1m{code}\033[22m")
            )

        if evaluate_python(condition):
            process_lines(section_body)
            return

def split_commands(text):
    """Split top-level semicolons, respecting quotes and nested syntax."""
    commands = []
    start = 0
    i = 0
    square = 0
    curly = 0
    quote = None
    escaped = False
    backtick = False

    while i < len(text):
        char = text[i]

        if backtick:
            if char == "`" and not escaped:
                backtick = False
            if char == "\\" and not escaped:
                escaped = True
            else:
                escaped = False
            i += 1
            continue

        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            i += 1
            continue

        if char in ("'", '"'):
            quote = char
        elif char == "`":
            backtick = True
        elif text.startswith("{{", i):
            curly += 1
            i += 2
            continue
        elif text.startswith("}}", i) and curly:
            curly -= 1
            i += 2
            continue
        elif char == "[":
            square += 1
        elif char == "]" and square:
            square -= 1
        elif char == ";" and square == 0 and curly == 0:
            commands.append(text[start:i])
            start = i + 1

        i += 1

    commands.append(text[start:])
    return commands


def _record_execution(query, result, success):
    EXECUTION_HISTORY.append({
        "query": str(query),
        "result": str(result) if result is not None else "",
        "success": bool(success),
    })


def _dump_history(command):
    """Implement: dump [all|good|bad] [queries|results] FILE."""
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise ChemQLError(f"Invalid dump command: {exc}") from exc

    if len(parts) == 2:
        category, mode, filename = "all", "both", parts[1]
    elif len(parts) == 4:
        _, category, mode, filename = parts
        if category not in {"all", "good", "bad"} or mode not in {
            "queries", "results"
        }:
            raise ChemQLError(
                "Usage: dump [all|good|bad] [queries|results] FILE"
            )
    elif len(parts) == 3 and parts[1] in {"all", "good", "bad"}:
        _, category, filename = parts
        mode = "both"
    else:
        raise ChemQLError(
            "Usage: dump [all|good|bad] [queries|results] FILE"
        )

    records = EXECUTION_HISTORY

    if category == "good":
        records = [r for r in records if r.get("success") is True]
    elif category == "bad":
        records = [r for r in records if r.get("success") is False]

    if mode == "queries":
        lines = [str(r["query"]) for r in records]
        content = "\n".join(lines)
    elif mode == "results":
        lines = [str(r["result"]) for r in records]
        content = "\n".join(lines)
    else:
        content = "\n\n".join(
            f"QUERY:\n{r['query']}\nRESULT:\n{r['result']}"
            for r in records
        )

    content = strip_ansi(content)
    if content:
        content += "\n"

    Path(filename).write_text(content, encoding="utf-8")
    return f"Dumped {len(records)} execution record(s) to {filename}"


def strip_ansi(text):
    """Remove common ANSI CSI, OSC, and single-character escape sequences."""
    text = re.sub(r"\x1B\][^\x07]*(?:\x07|\x1B\\)", "", str(text))
    return re.sub(r"\x1B(?:\[[0-?]*[ -/]*[@-~]|[@-_])", "", text)


def process_inline(text):
    """Process one complete line of the chemql language."""
    stripped = text.strip()

    if not stripped:
        return

    # Native dynamically typed variables: `let name = expression`.
    let_match = re.fullmatch(r"let\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*=\s*(.+)", stripped, re.DOTALL)
    if let_match:
        name, expression = let_match.groups()
        value = evaluate_python(expression)
        if _CURRENT_NAMESPACE is not None and "." not in name:
            qualified = _CURRENT_NAMESPACE._chemql_name + "::" + name # type: ignore
            _CURRENT_NAMESPACE._set_member(name, value, _CURRENT_VISIBILITY == "public")
            # Keep a compatibility alias, but do not overwrite a same-named
            # variable in the caller's global scope. Namespace-qualified access
            # resolves through the namespace object, not this alias.
            python_globals[qualified.replace("::", "__")] = value
        elif "::" in name:
            evaluate_python(name + " = (" + expression + ")")
        elif "." in name:
            evaluate_python(name + " = (" + expression + ")")
        else:
            python_globals[name] = value
            CHEMQL_VARIABLES.add(name)
        return None

    if stripped.casefold() == "variables":
        if not CHEMQL_VARIABLES:
            return "No variables."
        return "\n".join(f"{name} = {python_globals.get(name)!r}" for name in sorted(CHEMQL_VARIABLES) if name in python_globals)

    unset_match = re.fullmatch(r"unset\s+([A-Za-z_][A-Za-z0-9_]*)", stripped, re.IGNORECASE)
    if unset_match:
        name = unset_match.group(1)
        CHEMQL_VARIABLES.discard(name)
        python_globals.pop(name, None)
        return None

    # A bare native variable is an expression that prints its value in the REPL.
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", stripped) and stripped in CHEMQL_VARIABLES:
        return python_globals.get(stripped)

    # Attribute reads on ChemQL variables (e.g. `apple.price`).
    if re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", stripped):
        root = stripped.split(".", 1)[0]
        if root in CHEMQL_VARIABLES:
            return evaluate_python(stripped)

    # History dump command.
    if stripped.casefold().startswith("dump "):
        return _dump_history(stripped)

    # A bare struct/record constructor is an expression, not a ChemQL query.
    # `let fruit = Fruit{...}` already reaches evaluate_python through the let
    # handler above; this handles the same constructor when entered by itself.
    type_call = re.fullmatch(
        r"([A-Za-z_][A-Za-z0-9_]*)\s*\{(.*)\}", stripped, re.DOTALL
    )
    if type_call and type_call.group(1) in (*STRUCTS.keys(), *RECORDS.keys()):
        return evaluate_python(stripped)

    # A standalone user-defined function call returns its value directly.
    function_call = re.match(
        r"([A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*)\s*\{",
        stripped,
    )
    if function_call:
        opening = function_call.end() - 1
        closing = find_matching(stripped, opening, "{", "}")
        if not stripped[closing + 1:].strip():
            function_name = _resolve_package_qualified_name(function_call.group(1))
            arguments = _split_function_arguments(stripped[opening + 1:closing])
            if function_name in FUNCTIONS:
                return _call_function(function_name, arguments)
            if "::" not in function_name and function_name in BUILTIN_FUNCTIONS:
                return _call_builtin(function_name, arguments)

    # [ ... ] is Python.
    if stripped.startswith("["):
        end = find_matching(stripped, 0, "[", "]")
        if not stripped[end + 1:].strip():
            return evaluate_python(stripped[1:end])

    # {{ ... }} is a query expression.
    if stripped.startswith("{{"):
        end = find_matching(stripped, 0, "{{", "}}")
        if not stripped[end + 2:].strip():
            return execute_query_block(stripped[2:end].strip())

    # Backtick-wrapped commands use the persistent Bash session.
    if len(stripped) >= 2 and stripped.startswith("`") and stripped.endswith("`"):
        command = stripped[1:-1]
        return run_shell_command(command)


    # Native variables can participate in ordinary Python expressions without
    # square brackets (for example `q+w`). Try Python expression parsing before
    # the query parser whenever the line references a known ChemQL variable.
    # This handles compact operators as well as spaced expressions.
    known_expression_names = (CHEMQL_VARIABLES | {
        name for name in python_globals
        if isinstance(name, str) and name.isidentifier() and not name.startswith("__")
    })
    references_variable = any(
        re.search(r"\b" + re.escape(name) + r"\b", stripped)
        for name in known_expression_names
    )
    if references_variable:
        try:
            ast.parse(stripped, mode="eval")
        except SyntaxError:
            pass
        else:
            try:
                return evaluate_python(stripped)
            except (SyntaxError, NameError):
                pass

    # Function calls can compose into ordinary Python expressions, e.g.
    # `int{1} + int{1}`. Expand them before deciding whether this is a query;
    # otherwise the query parser sees the resulting `1 + 1` as a command.
    if re.search(
        r"(?<![A-Za-z0-9_.:])[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*(?:\.[A-Za-z_][A-Za-z0-9_]*)?\s*\{",
        stripped,
    ):
        expanded = _expand_function_calls(stripped)
        try:
            ast.parse(expanded, mode="eval")
        except SyntaxError:
            stripped = expanded
        else:
            return evaluate_python(expanded)

    # Try ChemQL first. If the parser specifically reports an unknown command,
    # treat the input as a possible Python expression. Only Python SyntaxError
    # or NameError falls back to the original ChemQL error; other Python errors
    # (e.g. TypeError) are meaningful and should remain visible.
    try:
        result = execute_query_text(stripped)
    except _ChemQLUnknownCommand as error:
        try:
            return evaluate_python(stripped)
        except (SyntaxError, NameError):
            raise error

    plain_result = strip_ansi(result) if isinstance(result, str) else ""
    # The query engine formats unknown-command failures as text (including a
    # caret line), so detect the diagnostic independently of any leading ANSI
    # styling or extra whitespace.
    if isinstance(result, str) and re.search(
        r"Error:\s*Unknown command\b", plain_result
    ):
        try:
            return evaluate_python(stripped)
        except (SyntaxError, NameError):
            # If Python also rejects it, preserve ChemQL's more useful error.
            return result
    return result


def join_continuations(lines):
    """Join lines ending in \\ with the following line."""
    joined = []
    buffer = None

    for line in lines:
        if buffer is None:
            buffer = line
        else:
            buffer += line

        if buffer.endswith("\\"):
            buffer = buffer[:-1] + " "
            continue

        joined.append(buffer)
        buffer = None

    if buffer is not None:
        joined.append(buffer)

    return joined


def _find_unquoted_marker(text, marker, start=0):
    """Find a marker outside single- and double-quoted strings."""
    quote = None
    escaped = False
    i = start
    while i <= len(text) - len(marker):
        char = text[i]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            i += 1
            continue
        if char in ("'", '"'):
            quote = char
            i += 1
            continue
        if text.startswith(marker, i):
            return i
        i += 1
    return -1


# Canonical ChemQL package names and user-defined aliases are deliberately
# tracked separately. An alias must never replace a canonical package binding.
CHEMQL_PACKAGE_BINDINGS = {}
CHEMQL_PACKAGE_SOURCE_LOADED = set()


def _package_relative_path(package_name):
    """Convert a canonical `a::b` package name to a relative source path."""
    parts = package_name.split("::")
    if not parts or any(not re.fullmatch(r"[A-Za-z_]\w*", part) for part in parts):
        raise ImportError(f"Invalid ChemQL package name: `{package_name}`")
    return Path(*parts[:-1], parts[-1] + ".cql")


def _find_cql_package_file(package_name):
    """Find a .cql package locally first, then in ChemQL's bundled stdlib."""
    relative = _package_relative_path(package_name)
    local_path = Path.cwd() / relative
    if local_path.is_file():
        return local_path
    stdlib_path = Path(__file__).resolve().parent / "stdlib" / relative
    if stdlib_path.is_file():
        return stdlib_path
    return None


def _ensure_package_namespace(package_name, allow_namespace_only=False):
    """Load a canonical ChemQL package and return its namespace object."""
    if not re.fullmatch(r"[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*", package_name):
        raise ImportError(f"Invalid ChemQL package name: `{package_name}`")
    cached = NAMESPACES.get(package_name)
    if cached is not None and package_name in CHEMQL_PACKAGE_SOURCE_LOADED:
        return cached

    parent_name, separator, leaf_name = package_name.rpartition("::")
    path = _find_cql_package_file(package_name)
    if path is None and not allow_namespace_only:
        raise ImportError(
            f"Cannot find ChemQL package `{package_name}`. Searched the current "
            f"directory and ChemQL's bundled `stdlib` directory for .cql files."
        )
    parent = _ensure_package_namespace(parent_name, allow_namespace_only=True) if separator else None

    namespace = NAMESPACES.get(package_name)
    if namespace is None:
        namespace = ChemQLNamespace(package_name, parent)
        NAMESPACES[package_name] = namespace
    if parent is not None:
        # The canonical path must remain traversable (math::statistics).
        parent._set_member(leaf_name, namespace, True)

    if path is not None and CHEMQL_PACKAGE_BINDINGS.get(package_name) != package_name:
        source_lines = path.read_text(encoding="utf-8").splitlines()
        old_namespace, old_visibility = _CURRENT_NAMESPACE, _CURRENT_VISIBILITY
        try:
            globals()["_CURRENT_NAMESPACE"] = namespace
            globals()["_CURRENT_VISIBILITY"] = "private"
            process_lines(source_lines)
        except Exception:
            # Do not mark a partially executed package as successfully loaded.
            NAMESPACES.pop(package_name, None)
            if parent is not None:
                parent._set_member(leaf_name, namespace, False)
            raise
        finally:
            globals()["_CURRENT_NAMESPACE"] = old_namespace
            globals()["_CURRENT_VISIBILITY"] = old_visibility
        CHEMQL_PACKAGE_SOURCE_LOADED.add(package_name)

    # A namespace-only parent is a canonical container, not an independently
    # loadable package unless it has its own .cql source file.
    if path is not None:
        CHEMQL_PACKAGE_BINDINGS.setdefault(package_name, package_name)
    return namespace


def _execute_load_statement(statement):
    """Load a ChemQL .cql package, optionally binding an explicit alias."""
    match = re.fullmatch(
        r"load\s+([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)(?:\s+as\s+([A-Za-z_]\w*))?",
        statement,
    )
    if not match:
        if statement.startswith("load"):
            raise SyntaxError("Expected `load package::name` or `load package::name as alias`")
        return False

    package_name, alias = match.groups()

    # Detect binding conflicts before executing package source, so a failed
    # load cannot run code or partially initialize the conflicting package.
    if alias:
        existing = CHEMQL_PACKAGE_BINDINGS.get(alias)
        if existing is not None and existing != package_name:
            raise ImportError(
                f"Package name `{alias}` is already bound to `{existing}`; "
                f"cannot also bind it to `{package_name}`. Use a different alias, "
                f"for example `load {package_name} as {alias}_pkg`."
            )
        if alias in CHEMQL_VARIABLES and alias not in CHEMQL_PACKAGE_BINDINGS:
            raise ImportError(
                f"Name `{alias}` is already defined and cannot be used as a package alias. "
                f"Choose another alias."
            )
    elif "::" not in package_name:
        existing = CHEMQL_PACKAGE_BINDINGS.get(package_name)
        if existing is not None and existing != package_name:
            raise ImportError(
                f"Name `{package_name}` is already bound to `{existing}`. "
                f"Use an explicit alias to load `{package_name}` under another name."
            )
        if package_name in CHEMQL_VARIABLES and package_name not in CHEMQL_PACKAGE_BINDINGS:
            raise ImportError(f"Name `{package_name}` is already defined; cannot bind package to it.")

    namespace = _ensure_package_namespace(package_name)

    # A nested package's canonical path needs its root namespace bound, but
    # this does not create an alias for the nested package's final component.
    if "::" in package_name:
        root_name = package_name.split("::", 1)[0]
        root_namespace = NAMESPACES[root_name]
        root_binding = CHEMQL_PACKAGE_BINDINGS.get(root_name)
        if root_binding is not None and root_binding != root_name:
            raise ImportError(
                f"Canonical namespace `{root_name}` is already bound to `{root_binding}`; "
                f"cannot expose `{package_name}` through its canonical path."
            )
        if root_name in CHEMQL_VARIABLES and root_name not in CHEMQL_PACKAGE_BINDINGS:
            raise ImportError(f"Name `{root_name}` is already defined; cannot expose `{package_name}`.")
        CHEMQL_PACKAGE_BINDINGS[root_name] = root_name
        python_globals[root_name] = root_namespace
        CHEMQL_VARIABLES.add(root_name)

    if alias:
        existing = CHEMQL_PACKAGE_BINDINGS.get(alias)
        if existing is not None and existing != package_name:
            raise ImportError(
                f"Package name `{alias}` is already bound to `{existing}`; "
                f"cannot also bind it to `{package_name}`. Use a different alias, "
                f"for example `load {package_name} as {alias}_pkg`."
            )
        # Avoid silently overwriting a non-package ChemQL variable either.
        if alias in CHEMQL_VARIABLES and alias not in CHEMQL_PACKAGE_BINDINGS:
            raise ImportError(
                f"Name `{alias}` is already defined and cannot be used as a package alias. "
                f"Choose another alias."
            )
        CHEMQL_PACKAGE_BINDINGS[alias] = package_name
        python_globals[alias] = namespace
        CHEMQL_VARIABLES.add(alias)
    else:
        # A canonical top-level package binds its own short name. Nested
        # packages do not acquire an implicit short-name alias. When a nested
        # package is loaded, its root namespace (e.g. `math`) is available so
        # the full canonical path can be traversed.
        if "::" not in package_name:
            existing = CHEMQL_PACKAGE_BINDINGS.get(package_name)
            if existing is not None and existing != package_name:
                raise ImportError(
                    f"Name `{package_name}` is already bound to `{existing}`. "
                    f"Use an explicit alias to load `{package_name}` under another name."
                )
            if package_name in CHEMQL_VARIABLES and package_name not in CHEMQL_PACKAGE_BINDINGS:
                raise ImportError(f"Name `{package_name}` is already defined; cannot bind package to it.")
            CHEMQL_PACKAGE_BINDINGS[package_name] = package_name
            python_globals[package_name] = namespace
            CHEMQL_VARIABLES.add(package_name)
    return True


def process_lines(lines):
    """Process ChemQL source, including multiline Python, terminal, and comments."""
    global _CURRENT_NAMESPACE, _CURRENT_VISIBILITY
    lines = join_continuations(list(lines))
    # Natural headers (for/if/while) and typed terminators are accepted in v1.3.
    normalized_lines = []
    in_python_block = False
    for source_line in lines:
        stripped_source = source_line.strip()
        if stripped_source == "[[[":
            in_python_block = True
            normalized_lines.append(source_line)
            continue
        if stripped_source == "]]]":
            in_python_block = False
            normalized_lines.append(source_line)
            continue
        if not in_python_block:
            if re.match(r"^(for|while|if)\s+.+$", stripped_source) and not stripped_source.startswith("["):
                # Existing block parser supplies the trailing colon to Python's AST.
                source_line = "[" + stripped_source + "]"
            elif stripped_source.casefold() in {"endfor", "endwhile", "endif"}:
                source_line = "[endblock]"
        normalized_lines.append(source_line)
    lines = normalized_lines
    i = 0

    while i < len(lines):
        raw_line = lines[i]
        stripped = raw_line.strip()

        if not stripped:
            i += 1
            continue

        # Namespace blocks can be nested. Visibility defaults to private.
        namespace_match = re.fullmatch(r"namespace\s+([A-Za-z_]\w*)", stripped, re.IGNORECASE)
        if namespace_match:
            ns_name = namespace_match.group(1)
            end = i + 1
            depth = 1
            while end < len(lines):
                candidate = lines[end].strip()
                if re.fullmatch(r"(?:(?:public|private)\s+)?namespace\s+[A-Za-z_]\w*", candidate, re.IGNORECASE):
                    depth += 1
                elif candidate.casefold() == "endnamespace":
                    depth -= 1
                    if depth == 0:
                        break
                end += 1
            if end >= len(lines):
                raise SyntaxError(f"Missing `endnamespace` for namespace `{ns_name}`")
            parent = _CURRENT_NAMESPACE
            full_name = (parent._chemql_name + "::" + ns_name) if parent else ns_name # type: ignore
            ns = NAMESPACES.get(full_name)
            if ns is None:
                ns = ChemQLNamespace(full_name, parent)
                NAMESPACES[full_name] = ns
            if parent is not None:
                parent._set_member(ns_name, ns, _CURRENT_VISIBILITY == "public")
            else:
                python_globals[ns_name] = ns
                CHEMQL_VARIABLES.add(ns_name)
            old_ns, old_visibility = _CURRENT_NAMESPACE, _CURRENT_VISIBILITY
            _CURRENT_NAMESPACE, _CURRENT_VISIBILITY = ns, "private"
            try:
                process_lines(lines[i + 1:end])
            finally:
                _CURRENT_NAMESPACE, _CURRENT_VISIBILITY = old_ns, old_visibility
            i = end + 1
            continue
        if stripped.casefold() == "endnamespace":
            raise SyntaxError("Unexpected `endnamespace`")
        visibility_match = re.match(r"^(public|private)\s+(.+)$", stripped, re.IGNORECASE)
        if visibility_match:
            visibility, declaration = visibility_match.groups()
            old_visibility = _CURRENT_VISIBILITY
            _CURRENT_VISIBILITY = visibility.casefold()
            try:
                # Visibility prefixes may precede block declarations, so pass the
                # complete declaration (including its body) to the normal parser.
                block_end = i
                if re.match(r"^(?:(?:static\s+func|func\s+static|func)\s+)", declaration, re.IGNORECASE):
                    block_end = i + 1
                    while block_end < len(lines) and lines[block_end].strip().casefold() != "endfunc":
                        block_end += 1
                    if block_end >= len(lines):
                        raise SyntaxError("Missing `endfunc` after visibility declaration")
                elif re.match(r"^namespace\s+", declaration, re.IGNORECASE):
                    depth = 1
                    block_end = i + 1
                    while block_end < len(lines):
                        item = lines[block_end].strip()
                        if re.match(r"^(?:(?:public|private)\s+)?namespace\s+", item, re.IGNORECASE):
                            depth += 1
                        elif item.casefold() == "endnamespace":
                            depth -= 1
                            if depth == 0:
                                break
                        block_end += 1
                    if block_end >= len(lines):
                        raise SyntaxError("Missing `endnamespace` after visibility declaration")
                elif re.match(r"^(struct|record|enum)\s+[A-Za-z_]\w*(?:\s+from\s+(?:\[[^\]]+\]|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*))?\s*$", declaration, re.IGNORECASE):
                    kind = re.match(r"^(struct|record|enum)", declaration, re.IGNORECASE).group(1).casefold() # type:ignore
                    terminator = {"struct": "endstruct", "record": "endrecord", "enum": "endenum"}[kind]
                    block_end = i + 1
                    while block_end < len(lines) and lines[block_end].strip().casefold() != terminator:
                        block_end += 1
                    if block_end >= len(lines):
                        raise SyntaxError(f"Missing `{terminator}` after visibility declaration")
                process_lines([declaration] + lines[i + 1:block_end + 1])
            finally:
                _CURRENT_VISIBILITY = old_visibility
            i = block_end + 1
            continue

        enum_match = re.fullmatch(r"enum\s+([A-Za-z_]\w*)", stripped, re.IGNORECASE)
        if enum_match:
            type_name = enum_match.group(1)
            end = i + 1
            while end < len(lines) and lines[end].strip().casefold() != "endenum":
                end += 1
            if end >= len(lines):
                raise SyntaxError(f"Missing `endenum` for enum `{type_name}`")
            members = []
            member_names = set()
            for member_line in lines[i + 1:end]:
                member_line = remove_comments(member_line).strip()
                if not member_line:
                    continue
                member_match = re.fullmatch(r"([A-Za-z_]\w*)(?:\s*=\s*(.+))?", member_line)
                if not member_match:
                    raise SyntaxError(f"Invalid enum member declaration: {member_line}")
                member_name, value_expression = member_match.groups()
                if member_name in member_names:
                    raise SyntaxError(f"Duplicate enum member `{member_name}` in {type_name}")
                member_names.add(member_name)
                value = auto() if value_expression is None else evaluate_python(_expand_definitions(value_expression))
                members.append((member_name, value))
            if not members:
                raise SyntaxError(f"Enum `{type_name}` must declare members")
            generated = Enum(type_name, members, module=__name__)
            ENUMS[type_name] = generated
            python_globals[type_name] = generated
            i = end + 1
            continue

        type_match = re.fullmatch(
            r"(struct|record)\s+([A-Za-z_]\w*)(?:\s+from\s+(\[[^\]]+\]|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*))?",
            stripped,
            re.IGNORECASE,
        )
        if type_match:
            kind, type_name, base_name = type_match.group(1).casefold(), type_match.group(2), type_match.group(3)
            terminator = "endstruct" if kind == "struct" else "endrecord"
            end = i + 1
            while end < len(lines) and lines[end].strip().casefold() != terminator:
                end += 1
            if end >= len(lines):
                raise SyntaxError((f"Missing `{terminator}` for {kind} `{type_name}`" if NO_ANSI else f"Missing \033[1m{terminator}\033[22m for {kind} \033[1m{type_name}\033[22m"))
            parent = None
            base_fields, base_required, defaults = [], [], {}
            base_init_parameters = []
            tuple_fields = ()
            if base_name:
                base_reference = base_name.strip()
                if base_reference.startswith("[") and base_reference.endswith("]"):
                    parent = evaluate_python(base_reference[1:-1].strip())
                elif "." in base_reference:
                    parent = evaluate_python(base_reference)
                if kind == "record":
                    if parent not in RECORDS.values():
                        parent = RECORDS.get(base_reference)
                    if parent is None:
                        raise SyntaxError(f"Record `{type_name}` can only inherit from another record")
                else:
                    parent = (
                        parent
                        or STRUCTS.get(base_reference)
                        or RECORDS.get(base_reference)
                        or python_globals.get(base_reference)
                        or getattr(builtins, base_reference, None)
                    )
                    if not isinstance(parent, type):
                        raise SyntaxError(f"Unknown base class `{base_reference}` for struct `{type_name}`")
                    if issubclass(parent, Enum):
                        raise SyntaxError(f"Struct `{type_name}` cannot inherit from an enum")
                if hasattr(parent, "_chemql_fields"):
                    base_fields = list(parent._chemql_fields)
                    base_required = list(parent._chemql_required)
                    defaults.update(parent._chemql_defaults)
                    tuple_fields = tuple(getattr(parent, "_chemql_tuple_fields", ()))
                elif kind == "struct":
                    try:
                        parameters = list(inspect.signature(parent.__init__).parameters.values())[1:]
                    except (TypeError, ValueError) as exc:
                        raise SyntaxError(f"Cannot inspect constructor for base class `{base_name}`") from exc
                    for parameter in parameters:
                        if parameter.kind not in (
                            inspect.Parameter.POSITIONAL_ONLY,
                            inspect.Parameter.POSITIONAL_OR_KEYWORD,
                            inspect.Parameter.KEYWORD_ONLY,
                        ):
                            continue
                        if not parameter.name.isidentifier():
                            continue
                        base_fields.append(parameter.name)
                        if parameter.default is inspect.Parameter.empty:
                            base_required.append(parameter.name)
                        else:
                            defaults[parameter.name] = parameter.default
                        base_init_parameters.append(parameter)
                if base_fields:
                    tuple_fields = tuple(getattr(parent, "_chemql_tuple_fields", ()))

            required_fields, optional_fields = [], []
            for field_line in lines[i + 1:end]:
                field_line = remove_comments(field_line).strip()
                if not field_line:
                    continue
                required_match = re.fullmatch(r"(?:required\s+([A-Za-z_]\w*)|([A-Za-z_]\w*)!)", field_line, re.IGNORECASE)
                if required_match:
                    if kind != "struct":
                        raise SyntaxError("`required` fields are supported only in structs")
                    field = required_match.group(1) if required_match.group(1) is not None else required_match.group(2)
                    default = None
                    is_required = True
                else:
                    match = re.fullmatch(r"([A-Za-z_]\w*)(?:\s*=\s*(.+))?", field_line)
                    if not match:
                        raise SyntaxError(f"Invalid {kind} field declaration: {field_line}")
                    field, default = match.groups()
                    is_required = False
                if field in base_fields or field in required_fields or field in optional_fields:
                    raise SyntaxError((f"Duplicate field `{field}` in {type_name}" if NO_ANSI else f"Duplicate field \033[1m{field}\033[22m in {type_name}"))
                if is_required:
                    required_fields.append(field)
                else:
                    optional_fields.append(field)
                    if default is not None:
                        defaults[field] = evaluate_python(_expand_definitions(default))
            declared_fields = required_fields + optional_fields if kind == "struct" else optional_fields
            duplicate_fields = set(base_fields) & set(declared_fields)
            if duplicate_fields:
                raise SyntaxError(f"Field `{sorted(duplicate_fields)[0]}` is already inherited by {type_name}")
            fields = base_fields + declared_fields
            if not fields and parent is None:
                raise SyntaxError((f"{kind.title()} `{type_name}` must declare fields" if NO_ANSI else f"{kind.title()} \033[1m{type_name}\033[22m must declare fields"))
            if kind == "struct":
                all_required = base_required + required_fields
                own_fields = tuple(declared_fields)
                native_constructor_base = parent in (
                    int, float, complex, str, bytes, tuple, frozenset,
                ) if parent is not None else False

                def make_struct(
                    class_name, base_class, field_names, required_names,
                    field_defaults, declared_names, inherited_names,
                    init_parameters, inherited_tuple_fields, base_is_record,
                    native_constructor,
                ):
                    def bind_fields(*args, **kwargs):
                        if len(args) > len(field_names):
                            raise TypeError(f"{class_name} expected at most {len(field_names)} positional arguments")
                        values = dict(zip(field_names, args))
                        overlap = values.keys() & kwargs.keys()
                        if overlap:
                            raise TypeError(f"Multiple values for field `{next(iter(overlap))}`")
                        values.update(kwargs)
                        extra = values.keys() - set(field_names)
                        if extra:
                            raise TypeError(f"Unexpected field(s): {', '.join(sorted(extra))}")
                        missing = [name for name in required_names if name not in values]
                        if missing:
                            raise TypeError(f"{class_name} missing required field(s): {', '.join(missing)}")
                        return {field: values.get(field, field_defaults.get(field)) for field in field_names}

                    def struct_init(self, *args, **kwargs):
                        if native_constructor and not field_names:
                            return
                        values = bind_fields(*args, **kwargs)
                        if base_class is not None:
                            if hasattr(base_class, "_chemql_fields"):
                                if not base_is_record:
                                    base_class.__init__(self, **{field: values[field] for field in inherited_names})
                            elif native_constructor:
                                pass
                            elif init_parameters:
                                positional = [
                                    values[param.name]
                                    for param in init_parameters
                                    if param.kind is inspect.Parameter.POSITIONAL_ONLY
                                ]
                                keywords = {
                                    param.name: values[param.name]
                                    for param in init_parameters
                                    if param.kind in (
                                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                        inspect.Parameter.KEYWORD_ONLY,
                                    )
                                }
                                base_class.__init__(self, *positional, **keywords)
                            else:
                                base_class.__init__(self)
                        for field_name in declared_names:
                            setattr(self, field_name, values[field_name])

                    def struct_repr(self):
                        return class_name + "{ " + ", ".join(
                            f"{field}={getattr(self, field)!r}" for field in field_names
                        ) + " }"

                    def struct_eq(self, other):
                        return type(other) is type(self) and all(
                            getattr(self, field) == getattr(other, field) for field in field_names
                        )

                    attrs = {
                        "__init__": struct_init,
                        "_chemql_fields": tuple(field_names),
                        "_chemql_required": tuple(required_names),
                        "_chemql_defaults": dict(field_defaults),
                        "_chemql_tuple_fields": inherited_tuple_fields,
                    }
                    if not (native_constructor and not field_names):
                        attrs["__repr__"] = struct_repr
                        attrs["__str__"] = struct_repr
                        attrs["__eq__"] = struct_eq
                    if inherited_tuple_fields:
                        def struct_new(cls, *args, **kwargs):
                            values = bind_fields(*args, **kwargs)
                            return tuple.__new__(cls, tuple(values[field] for field in inherited_tuple_fields))
                        attrs["__new__"] = struct_new
                    elif native_constructor and not field_names:
                        def struct_new(cls, *args, **kwargs):
                            return base_class.__new__(cls, *args, **kwargs)
                        attrs["__new__"] = struct_new
                    else:
                        attrs["__slots__"] = tuple(declared_names)
                    return type(class_name, (base_class,) if base_class is not None else (), attrs)

                generated = make_struct(
                    type_name, parent, fields, all_required, defaults, own_fields,
                    base_fields, base_init_parameters, tuple_fields,
                    parent in RECORDS.values() if parent is not None else False,
                    native_constructor_base,
                )
                STRUCTS[type_name] = generated
            else:
                from collections import namedtuple
                first_default = next((n for n, f in enumerate(fields) if f in defaults), len(fields))
                if parent is None and any(f not in defaults for f in fields[first_default:]):
                    raise SyntaxError((f"Record `{type_name}` fields with defaults must be trailing fields" if NO_ANSI else f"Record \033[1m{type_name}\033[22m fields with defaults must be trailing fields"))
                if parent is None:
                    base_record = namedtuple(type_name + "Base", fields, defaults=[defaults[f] for f in fields[first_default:]])
                else:
                    base_record = parent

                def make_record(record_name, record_base, field_names, field_defaults, derived):
                    def _record_repr(self):
                        return record_name + " -> " + ", ".join(f"{field}: {getattr(self, field)}" for field in field_names)
                    def _record_new(cls, *args, **kwargs):
                        if len(args) > len(field_names):
                            raise TypeError(f"{record_name} expected at most {len(field_names)} positional arguments")
                        values = dict(zip(field_names, args))
                        overlap = values.keys() & kwargs.keys()
                        if overlap:
                            raise TypeError(f"Multiple values for field `{next(iter(overlap))}`")
                        values.update(kwargs)
                        extra = values.keys() - set(field_names)
                        if extra:
                            raise TypeError(f"Unexpected field(s): {', '.join(sorted(extra))}")
                        missing = [field for field in field_names if field not in values and field not in field_defaults]
                        if missing:
                            raise TypeError(f"{record_name} missing required field(s): {', '.join(missing)}")
                        values = {field: values.get(field, field_defaults.get(field)) for field in field_names}
                        return tuple.__new__(cls, tuple(values[field] for field in field_names))
                    def _binary_method(operation, reverse=False):
                        def method(self, other):
                            if type(other) is type(self):
                                values = [operation(getattr(other, field), getattr(self, field)) if reverse else operation(getattr(self, field), getattr(other, field)) for field in field_names]
                            elif isinstance(other, (int, float, complex)):
                                values = [operation(other, getattr(self, field)) if reverse else operation(getattr(self, field), other) for field in field_names]
                            else:
                                return NotImplemented
                            return type(self)(*values)
                        return method
                    attrs = {
                        "__slots__": (), "__module__": __name__, "__str__": _record_repr,
                        "__repr__": _record_repr,
                        "__add__": _binary_method(operator.add), "__radd__": _binary_method(operator.add, True),
                        "__sub__": _binary_method(operator.sub), "__rsub__": _binary_method(operator.sub, True),
                        "__mul__": _binary_method(operator.mul), "__rmul__": _binary_method(operator.mul, True),
                        "__truediv__": _binary_method(operator.truediv), "__rtruediv__": _binary_method(operator.truediv, True),
                        "__floordiv__": _binary_method(operator.floordiv), "__rfloordiv__": _binary_method(operator.floordiv, True),
                        "__mod__": _binary_method(operator.mod), "__rmod__": _binary_method(operator.mod, True),
                        "__pow__": _binary_method(operator.pow), "__rpow__": _binary_method(operator.pow, True),
                        "__neg__": lambda self: type(self)(*(-getattr(self, f) for f in field_names)),
                        "__pos__": lambda self: type(self)(*(+getattr(self, f) for f in field_names)),
                        "__abs__": lambda self: type(self)(*(abs(getattr(self, f)) for f in field_names)),
                    }
                    if derived:
                        attrs["__new__"] = _record_new
                        attrs["_fields"] = tuple(field_names)
                        attrs["__match_args__"] = tuple(field_names)
                        attrs["_field_defaults"] = dict(field_defaults)
                        attrs["__slots__"] = ()
                        for index, field in enumerate(field_names):
                            if field not in getattr(record_base, "_fields", ()):
                                attrs[field] = property(lambda self, idx=index: self[idx])
                    return type(record_name, (record_base,), attrs)
                generated = make_record(type_name, base_record, fields, defaults, parent is not None)
                RECORDS[type_name] = generated
            generated._chemql_fields = tuple(fields)
            generated._chemql_required = tuple(base_required + required_fields) if kind == "struct" else ()
            generated._chemql_defaults = dict(defaults)
            generated._chemql_tuple_fields = tuple_fields if kind == "struct" else tuple(fields)
            python_globals[type_name] = generated
            i = end + 1
            continue

        if stripped.casefold() == "risk":
            end = i + 1
            nesting = 1
            while end < len(lines):
                token = lines[end].strip().casefold()
                if token == "risk": nesting += 1
                elif token == "endrisk":
                    nesting -= 1
                    if nesting == 0: break
                end += 1
            if end >= len(lines):
                raise SyntaxError(("Missing `endrisk`" if NO_ANSI else "Missing \033[1mendrisk\033[22m"))
            sections = {"risk": [], "fix": [], "cleanup": []}
            section = "risk"
            for risk_line in lines[i + 1:end]:
                marker = risk_line.strip().casefold()
                if marker in {"fix", "cleanup"}:
                    section = marker
                else:
                    sections[section].append(risk_line)
            global _CHEMQL_RISK_DEPTH
            _CHEMQL_RISK_DEPTH += 1
            try:
                try:
                    process_lines(sections["risk"])
                    python_globals["error"] = None
                except Exception as exc:
                    python_globals["error"] = (
                        exc.error_type
                        if isinstance(exc, ChemQLSignal)
                        else "ChemQLError"
                        if isinstance(exc, ChemQLError)
                        else type(exc).__name__
                    )
                    if sections["fix"]:
                        process_lines(sections["fix"])
                    elif not isinstance(exc, ChemQLSignal):
                        raise
            finally:
                try:
                    if sections["cleanup"]:
                        process_lines(sections["cleanup"])
                finally:
                    _CHEMQL_RISK_DEPTH = max(0, _CHEMQL_RISK_DEPTH - 1)
            i = end + 1
            continue

        signal_match = re.fullmatch(r"signal\s+(.+)", stripped, re.IGNORECASE)
        if signal_match:
            raise ChemQLSignal(evaluate_python(signal_match.group(1)))

        # Definitions are processed in source order and affect only later lines.
        define_match = re.fullmatch(r"define\s+(" + _DEFINITION_NAME + r")\s+(.+)", stripped)
        if define_match and not stripped.endswith("{}"):
            DEFINITIONS[define_match.group(1)] = define_match.group(2)
            i += 1
            continue

        remove_definition = re.fullmatch(r"remove\s+definition\s+(" + _DEFINITION_NAME + r")", stripped, re.IGNORECASE)
        if remove_definition:
            DEFINITIONS.pop(remove_definition.group(1), None)
            i += 1
            continue

        if stripped.casefold() == "definitions":
            if DEFINITIONS:
                for name, value in DEFINITIONS.items():
                    print(f"@{name} = {value}")
            else:
                print("No definitions.")
            i += 1
            continue
        if stripped.casefold() == "macros":
            if MACROS:
                for name, value in MACROS.items():
                    print(f"@{name} = {value}")
            else:
                print("No macros.")
            i += 1
            continue

        # Function definitions use `func NAME ... endfunc`.
        static_function = False
        function_source = stripped
        if re.match(r"^static\s+func\s+", function_source, re.IGNORECASE):
            static_function = True
            function_source = re.sub(r"^static\s+func\s+", "func ", function_source, count=1, flags=re.IGNORECASE)
        elif re.match(r"^func\s+static\s+", function_source, re.IGNORECASE):
            static_function = True
            function_source = re.sub(r"^func\s+static\s+", "func ", function_source, count=1, flags=re.IGNORECASE)
        function_match = re.fullmatch(r"func\s+([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*(?:\.[A-Za-z_]\w*)?)", function_source, re.IGNORECASE)
        if function_match:
            name = function_match.group(1)
            if _CURRENT_NAMESPACE is not None and "::" not in name and "." not in name:
                name = _CURRENT_NAMESPACE._chemql_name + "::" + name # type: ignore
            end = i + 1
            while end < len(lines) and lines[end].strip().casefold() != "endfunc":
                end += 1
            if end >= len(lines):
                raise SyntaxError((f"Missing `endfunc` for function `{name}`" if NO_ANSI else f"Missing `endfunc` for function \033[1m{name}\033[22m"))
            FUNCTIONS[name] = {"body": [_expand_definitions(source_line) for source_line in lines[i + 1:end]], "static": static_function}
            if _CURRENT_NAMESPACE is not None and "::" in name and "." not in name:
                member_name = name.rsplit("::", 1)[-1]
                def _namespace_function(*args, _function_name=name):
                    temp_names = []
                    try:
                        for arg in args:
                            temp = "__chemql_ns_arg_" + uuid.uuid4().hex
                            python_globals[temp] = arg
                            temp_names.append(temp)
                        return _call_function(_function_name, temp_names)
                    finally:
                        for temp in temp_names:
                            python_globals.pop(temp, None)
                _CURRENT_NAMESPACE._set_member(member_name, _namespace_function, _CURRENT_VISIBILITY == "public")
            if "." in name:
                owner_name, method_name = name.split(".", 1)
                owner = STRUCTS.get(owner_name)
                if owner is None:
                    raise NameError((f"Cannot define method `{name}`: struct `{owner_name}` does not exist" if NO_ANSI else f"Cannot define method `{name}`: struct \033[1m{owner_name}\033[22m does not exist"))
                def _make_struct_method(function_name):
                    def _method(instance, *args):
                        had_this = "this" in python_globals
                        old_this = python_globals.get("this")
                        # Pass method arguments through temporary Python globals.
                        # repr(struct_instance) uses ChemQL's `Fruit{...}` display
                        # syntax, which is not valid Python and breaks nested
                        # constructor expressions when substituted into a method.
                        temporary_names = []
                        python_globals["this"] = instance
                        try:
                            for arg in args:
                                temp_name = "__chemql_method_arg_" + uuid.uuid4().hex
                                python_globals[temp_name] = arg
                                temporary_names.append(temp_name)
                            return _call_function(function_name, temporary_names)
                        finally:
                            for temp_name in temporary_names:
                                python_globals.pop(temp_name, None)
                            if had_this:
                                python_globals["this"] = old_this
                            else:
                                python_globals.pop("this", None)
                    return _method
                method_callable = _make_struct_method(name)
                if static_function:
                    def _make_static_method(function_name):
                        def _static_method(*args):
                            temporary_names = []
                            try:
                                for arg in args:
                                    temp_name = "__chemql_static_arg_" + uuid.uuid4().hex
                                    python_globals[temp_name] = arg
                                    temporary_names.append(temp_name)
                                return _call_function(function_name, temporary_names)
                            finally:
                                for temp_name in temporary_names:
                                    python_globals.pop(temp_name, None)
                        return staticmethod(_static_method)
                    method_callable = _make_static_method(name)
                setattr(owner, method_name, method_callable)
            i = end + 1
            continue

        # `define NAME{}` introduces a source-generating macro.
        macro_match = re.fullmatch(r"define\s+(" + _DEFINITION_NAME + r")\s*\{\s*\}", stripped)
        if macro_match:
            name = macro_match.group(1)
            end = i + 1
            while end < len(lines) and lines[end].strip().casefold() != "enddefine":
                end += 1
            if end >= len(lines):
                raise SyntaxError((f"Missing `enddefine` for macro `{name}`" if NO_ANSI else f"Missing `enddefine` for macro \033[1m{name}\033[22m"))
            MACROS[name] = [_expand_definitions(source_line) for source_line in lines[i + 1:end]]
            i = end + 1
            continue

        # Multiline comments can start/end within a line, but markers inside
        # quoted strings are ordinary text. Keep any code surrounding a comment.
        comment_start = _find_unquoted_marker(raw_line, "///")
        if comment_start >= 0:
            prefix = raw_line[:comment_start]
            same_line_end = _find_unquoted_marker(raw_line, "///", comment_start + 3)
            if same_line_end >= 0:
                suffix = raw_line[same_line_end + 3:]
                lines[i] = prefix + suffix
                if not lines[i].strip():
                    i += 1
                    continue
                raw_line = lines[i]
                stripped = raw_line.strip()
            else:
                close_line = i + 1
                close_pos = -1
                while close_line < len(lines):
                    close_pos = _find_unquoted_marker(lines[close_line], "///")
                    if close_pos >= 0:
                        break
                    close_line += 1
                if close_line >= len(lines):
                    raise SyntaxError(("Missing closing `///` for multiline comment" if NO_ANSI else "Missing closing \033[1m///\033[22m for multiline comment"))
                suffix = lines[close_line][close_pos + 3:]
                lines[i] = prefix
                del lines[i + 1:close_line + 1]
                if suffix.strip():
                    lines.insert(i + 1, suffix)
                if not prefix.strip():
                    if suffix.strip():
                        i += 1
                    else:
                        continue
                else:
                    raw_line = prefix
                    stripped = prefix.strip()

        # Multiline Python block. Closing delimiter must be alone on a line;
        # this avoids mistaking valid expressions such as [[4]]] for a close.
        if stripped == "[[[":
            body = []
            i += 1
            while i < len(lines) and lines[i].strip() != "]]]":
                body.append(lines[i])
                i += 1
            if i >= len(lines):
                raise SyntaxError(("Missing closing `]]]` for Python block" if NO_ANSI else "Missing closing \033[1m]]]\033[22m for Python block"))
            body = [_expand_definitions(source_line) for source_line in body]
            code = "\n".join(body)
            captured = io.StringIO()
            try:
                with contextlib.redirect_stdout(captured):
                    value = evaluate_python(code)
                output = captured.getvalue()
                if value is not None:
                    output += str(value)
                if output:
                    output = strip_ansi(output) if NO_ANSI else output
                    print(output, end="" if output.endswith("\n") else "\n")
                _record_execution("[[[\n" + code + "\n]]]", output, True)
            except Exception as exc:
                message = f"\033[31mError: {exc}\033[0m"
                print(strip_ansi(message) if NO_ANSI else message, file=sys.stderr)
                _record_execution("[[[\n" + code + "\n]]]", message, False)
            i += 1
            continue

        # Multiline terminal block, sent as one script to the persistent shell.
        if stripped in {"```", "```bash", "```sh", "```cmd", "```terminal"}:
            body = []
            i += 1
            while i < len(lines) and lines[i].strip() != "```":
                body.append(lines[i])
                i += 1
            if i >= len(lines):
                raise SyntaxError("Missing closing \033[1m```\033[22m for terminal block")
            body = [_expand_definitions(source_line) for source_line in body]
            command = "\n".join(body)
            result = run_shell_command(command)
            result = strip_ansi(result) if NO_ANSI else result
            # POSIX PTY commands stream output live. Never print their returned
            # capture a second time; Windows pipe mode still needs normal printing.
            if result and not _shell_output_streamed:
                print(result)
            _record_execution("```\n" + command + "\n```", result, not result.startswith("Shell error:"))
            globals()["_shell_output_streamed"] = False
            i += 1
            continue

        top_level_statement = remove_comments(_expand_definitions(raw_line)).strip()
        # ChemQL package loading is separate from Python imports.
        load_statement = top_level_statement
        if load_statement == "load" or load_statement.startswith("load "):
            try:
                if _execute_load_statement(load_statement):
                    _record_execution(load_statement, "", True)
                    i += 1
                    continue
            except Exception as exc:
                message = f"\033[31mError: {exc}\033[0m"
                print(strip_ansi(message) if NO_ANSI else message, file=sys.stderr)
                _record_execution(load_statement, message, False)
                i += 1
                continue

        # Literal definitions are intentionally expanded inside strings too.
        # Directives themselves were handled above, so updates are not retroactive.
        raw_line = _expand_definitions(raw_line)
        line = remove_comments(raw_line).strip()
        if not line:
            i += 1
            continue

        if line == "[endblock]":
            raise SyntaxError(("Unexpected `[endblock]`" if NO_ANSI else "Unexpected \033[1m[endblock]\033[22m"))

        # Existing Python control-flow blocks.
        if is_python_block_header(line):
            end = find_endblock(lines, i + 1)
            body = lines[i + 1:end]
            code = line[1:-1].strip()
            if code.startswith("for "):
                execute_for_block(line, body)
            elif code.startswith("while "):
                execute_while_block(line, body)
            elif code.startswith("if "):
                execute_if_block(line, body)
            else:
                raise SyntaxError((f"Unsupported block `{code}`" if NO_ANSI else f"Unsupported block \033[1m{code}\033[22m"))
            i = end + 1
            continue

        if line == "[break]":
            raise ChemQLBreak()
        if line == "[continue]":
            raise ChemQLContinue()
        if line == "view":
            view_periodic_table()
            i += 1
            continue

        for command in split_commands(line):
            command = command.strip()
            if not command:
                continue
            try:
                macro_call = re.fullmatch(r"@(" + _DEFINITION_NAME + r")\s*\{(.*)\}", command, re.DOTALL)
                if macro_call and macro_call.group(1) in MACROS:
                    macro_name = macro_call.group(1)
                    macro_args = _split_function_arguments(macro_call.group(2))
                    expanded_lines = []
                    for macro_line in MACROS[macro_name]:
                        expanded = macro_line
                        for arg_index, arg in enumerate(macro_args, start=1):
                            expanded = re.sub(
                                r"\\" + str(arg_index) + r"(?!\d)",
                                lambda _match, value=arg: value,
                                expanded,
                            )
                        expanded_lines.append(_expand_definitions(expanded))
                    process_lines(expanded_lines)
                    result = None
                elif command.casefold().startswith("dump "):
                    result = _dump_history(command)
                else:
                    result = process_inline(command)

                rendered = "" if result is None else str(result)
                if result is not None:
                    if NO_ANSI:
                        rendered = strip_ansi(rendered)
                    # PTY-backed backtick commands already stream their output.
                    # Don't echo their captured return value a second time.
                    is_streamed_shell = (
                        os.name != "nt"
                        and len(command) >= 2
                        and command.startswith("`")
                        and command.endswith("`")
                    )
                    if not is_streamed_shell and not _shell_output_streamed:
                        print(rendered)
                # Some commands return formatted errors instead of raising exceptions.
                plain_result = strip_ansi(rendered).lstrip()
                success = not plain_result.startswith("Error:")

                _record_execution(command, rendered, success)
                globals()["_shell_output_streamed"] = False
            except Exception as exc:
                if _CHEMQL_RISK_DEPTH:
                    raise
                message = f"\033[31mError: {exc}\033[0m"
                print(strip_ansi(message) if NO_ANSI else message, file=sys.stderr)
                _record_execution(command, message, False)

        i += 1


def normalize_catalysts(values):
    catalysts = []
    seen = set()

    for value in values:
        catalyst = value.strip()
        normalized = catalyst.casefold()
        if catalyst and normalized not in seen:
            catalysts.append(catalyst)
            seen.add(normalized)

    return catalysts


def parse_temperature_setting(value):
    normalized = value.strip().casefold()
    if normalized == "standard":
        return 273.15
    if normalized == "room":
        return 298.15

    match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(?:°\s*)?(celsius|fahrenheit|kelvin|degc|degf|degk|c|f|k)", normalized)
    if not match:
        raise ValueError(("Temperature must use C, F, or K, or be `standard` or `room`" if NO_ANSI else "Temperature must use C, F, or K, or be \033[1mstandard\033[22m or \033[1mroom\033[22m"))

    temperature = float(match.group(1))
    unit = match.group(2)
    unit = {"celsius": "c", "degc": "c", "fahrenheit": "f", "degf": "f", "kelvin": "k", "degk": "k", "K":"k", "C":"c", "F": "f","k":"k", "c":"c", "f": "f"}[unit]
    if unit == "f":
        temperature = (temperature - 32) * 5 / 9 + 273.15
    elif unit == "c":
        temperature += 273.15

    if temperature < 0:
        raise ValueError("Temperature cannot be below absolute zero")

    return temperature


def parse_pressure_setting(value):
    normalized = value.strip().casefold()
    if normalized == "standard":
        return 100000.0
    if normalized == "room":
        return 101325.0

    match = re.fullmatch(r"([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(.*?)", normalized)
    if not match:
        raise ValueError("Pressure must be a non-negative value with Pa, N/m^2, bar, or atm units")

    pressure = float(match.group(1))
    unit = re.sub(r"\s+", "", match.group(2)).replace("²", "^2")
    unit_scales = {
        "pa": 1.0, "pascal": 1.0, "pascals": 1.0,
        "kpa": 1_000.0, "mpa": 1_000_000.0,
        "hpa": 100.0, "mbar": 100.0,
        "n/m^2": 1.0, "n/m2": 1.0, "nm^-2": 1.0, "n·m^-2": 1.0,
        "bar": 100_000.0, "mbar": 100.0,
        "atm": 101_325.0, "torr": 101_325.0 / 760, "mmhg": 101_325.0 / 760,
        "psi": 6894.757293168, "kpsi": 6_894_757.293168,
    }
    if unit not in unit_scales:
        raise ValueError("Unsupported pressure unit. Try Pa, kPa, MPa, hPa, bar, atm, torr, mmHg, or psi")

    return pressure * unit_scales[unit]


def _reaction_formula(value):
    normalized = value.casefold()
    for molecule in MOLECULES:
        if molecule.formula.casefold() == normalized:
            return molecule.formula
        if molecule.name.casefold() == normalized or molecule.iupac_name.casefold() == normalized:
            return molecule.formula
    return value


def parse_reactants(values):
    counts = {}
    index = 0

    while index < len(values):
        value = values[index]
        coefficient = 1

        if value.isdigit():
            coefficient = int(value)
            index += 1
            if index >= len(values):
                raise ValueError("Expected a molecule after its coefficient")
            value = values[index]
        else:
            match = re.match(r"^(\d+)(?=[A-Za-z])", value)
            if match:
                coefficient = int(match.group(1))
                value = value[match.end():]

        if coefficient <= 0 or not value:
            raise ValueError("Reactant coefficients must be positive integers")

        formula = _reaction_formula(value)
        key = formula.casefold()
        counts[key] = counts.get(key, 0) + coefficient
        index += 1

    if not counts:
        raise ValueError("Usage: react <coefficient><molecule> ...")

    return counts


def _reaction_side_counts(participants):
    counts = {}
    for participant in participants:
        formula = participant["molecule"]
        key = formula.casefold()
        counts[key] = counts.get(key, 0) + participant["stoichiometric_coefficient"]
    return counts


def _reaction_conditions_match(reaction):
    conditions = reaction.conditions
    temperature = conditions.get("temperature_k")
    if temperature is not None:
        current_temperature = reaction_state["temperature_k"]
        if current_temperature is None or abs(current_temperature - temperature) > REACTION_TEMPERATURE_TOLERANCE_K:
            return False

    pressure = conditions.get("pressure_pa")
    if pressure is not None:
        current_pressure = reaction_state["pressure_pa"]
        if current_pressure is None:
            return False
        tolerance = abs(pressure) * REACTION_PRESSURE_TOLERANCE
        if abs(current_pressure - pressure) > tolerance:
            return False

    required_catalysts = {
        item.casefold() for item in conditions.get("catalysts", [])
    }
    available_catalysts = {
        item.casefold() for item in reaction_state["catalysts"]
    }
    return required_catalysts.issubset(available_catalysts)


def _resolve_reaction_product(participant):
    formula = participant["molecule"]
    for molecule in MOLECULES:
        if molecule.formula.casefold() == formula.casefold():
            return molecule

    name = participant.get("name", formula)
    result = fetch_pubchem_molecule(name)
    if result is None:
        result = fetch_pubchem_molecule(formula)
    return result


def react(values):
    try:
        reactants = parse_reactants(values)
    except ValueError as exc:
        return str(exc)

    matches = []
    for reaction in REACTIONS:
        if not _reaction_conditions_match(reaction):
            continue

        forward = _reaction_side_counts(reaction.reactants)
        if reactants == forward:
            matches.append((reaction, reaction.products))
            continue

        if reaction.reversible is True and reactants == _reaction_side_counts(reaction.products):
            matches.append((reaction, reaction.reactants))

    if not matches:
        return "No reaction matches those reactants and the current temperature, pressure, and catalysts"

    if len(matches) > 1:
        names = ", ".join(f"{reaction.name} ({reaction.id})" for reaction, _ in matches[:5])
        return f"Multiple reactions match: {names}"

    reaction, products = matches[0]
    resolved = []
    for product in products:
        molecule = _resolve_reaction_product(product)
        if molecule is None:
            label = product.get("name", product["molecule"])
            return (f"Could not resolve product molecule `{label}` for reaction `{reaction.id}`" if NO_ANSI else f"Could not resolve product molecule \033[1m{label}\033[22m for reaction \033[1m{reaction.id}\033[22m")
        resolved.append((molecule, product["stoichiometric_coefficient"], product.get("phase")))

    if len(resolved) == 1:
        return resolved[0][0]

    return ReturnTable({
        "molecule": [item[0] for item in resolved],
        "stoichiometric_coefficient": [item[1] for item in resolved],
        "phase": [item[2] or "" for item in resolved],
    })


def current_conditions():
    temperature = reaction_state["temperature_k"]
    pressure = reaction_state["pressure_pa"]
    catalysts = reaction_state["catalysts"]

    temperature_text = f"{temperature:g} K" if temperature is not None else "Not Set"
    pressure_text = f"{pressure:g} Pa" if pressure is not None else "Not Set"
    catalysts_text = ", ".join(catalysts) if catalysts else "Not Set"

    return (
        f"Temperature: {temperature_text}\n"
        f"Pressure: {pressure_text}\n"
        f"Catalysts: {catalysts_text}"
    )


def execute(arguments, query_text=None, positions=None):
    global current_source

    if not arguments:
        return

    if arguments[0].lower() == "balance":
        try:
            return _execute_balance_command(
                query_text if query_text is not None else shlex.join(arguments)
            )
        except ValueError as exc:
            return format_error(str(exc), query_text)

    if arguments[0].lower() in {"help", "?"}:
        if len(arguments) == 1:
            return HELP + "\n\nFor built-in function documentation, try `help{read_csv}` or `help read_csv`."
        return _help_text(" ".join(arguments[1:]))

    if arguments[0].lower() == "sorry":
        return "\033[34mIt's ok, everybody makes mistakes👌\033[0m"
    
    if arguments[0].lower() == "view":
        view_periodic_table()
        return "Check your browser to view periodic table"

    if arguments[0].lower() == "version":
        return __version__
    if arguments[0].lower() == "exit":
        return sys.exit(0)
    if arguments[0].lower() == "definitions":
        return "\n".join([f"@{name} = {value}" for name, value in DEFINITIONS.items()]) if DEFINITIONS else "No definitions."
        
    if arguments[0].lower() == "macros":
        return "\n".join([f"@{name} = {value}" for name, value in MACROS.items()]) if MACROS else "No macros."
    
    if arguments[0] == "conditions":
        if len(arguments) != 1:
            return "Usage: conditions"
        return current_conditions()

    if arguments[0] == "set":
        if len(arguments) < 2:
            return "Usage: set temperature|pressure|catalysts <value>"

        setting = arguments[1].lower()
        values = arguments[2:]

        if setting == "temperature":
            if len(values) != 1:
                return "Usage: set temperature <valueC|valueF|valueK|standard|room>"

            try:
                reaction_state["temperature_k"] = parse_temperature_setting(values[0])
            except ValueError as exc:
                return str(exc)

            return f"Temperature set to {reaction_state['temperature_k']:.2f} K"

        if setting == "pressure":
            if len(values) != 1:
                return "Usage: set pressure <valuePa|valueN/m^2|valuebar|valueatm|standard|room>"

            try:
                reaction_state["pressure_pa"] = parse_pressure_setting(values[0])
            except ValueError as exc:
                return str(exc)

            return f"Pressure set to {reaction_state['pressure_pa']:g} Pa"

        if setting == "catalysts":
            reaction_state["catalysts"] = normalize_catalysts(values)
            if not reaction_state["catalysts"]:
                return "Catalysts cleared"
            return f"Catalysts set to {', '.join(reaction_state['catalysts'])}"

        return (f"Unknown reaction setting `{setting}`" if NO_ANSI else f"Unknown reaction setting \033[1m{setting}\033[22m")

    if arguments[0] == "add" and len(arguments) >= 2 and arguments[1].lower() == "catalyst":
        if len(arguments) < 3:
            return 'Usage: add catalyst "name"'

        catalyst = " ".join(arguments[2:]).strip()
        current = reaction_state["catalysts"]
        if catalyst and catalyst.casefold() not in {item.casefold() for item in current}:
            current.append(catalyst)
        return f"Catalysts: {', '.join(current)}" if current else "Catalysts cleared"

    if arguments[0] == "remove" and len(arguments) >= 2 and arguments[1].lower() in {"catalyst", "calatyst"}:
        if len(arguments) < 3:
            return 'Usage: remove catalyst "name"'

        catalyst = " ".join(arguments[2:]).strip()
        reaction_state["catalysts"] = [
            item for item in reaction_state["catalysts"]
            if item.casefold() != catalyst.casefold()
        ]
        return f"Catalysts: {', '.join(reaction_state['catalysts'])}" if reaction_state["catalysts"] else "Catalysts cleared"

    if arguments[0] == "react":
        return react(arguments[1:])

    # Convenience aliases for very common lookups.
    # These are syntactic sugar for normal search queries.
    if arguments[0] == "findel":
        if len(arguments) < 2:
            return "Usage: findel <name-or-symbol>"

        value = arguments[1]
        
        return_attributes = None

        return execute(
            ["search", "elements", "name", "like", value, "or", "symbol", "like", value]
        )

    if arguments[0] == "findmol":
        if len(arguments) < 2:
            return "Usage: findmol <name-or-formula> [return <attribute> ...]"

        value = arguments[1]

        # Optional return clause
        return_attributes = None

        if "return" in arguments[2:]:
            return_index = arguments.index("return", 2)
            return_attributes = arguments[return_index + 1:]

            if not return_attributes:
                return "Usage: findmol <name-or-formula> return <attribute> ..."

            for attribute in return_attributes:
                if attribute not in moleculeKeys:
                    return (f"There is no key `{attribute}`" if NO_ANSI else f"There is no key \033[1m{attribute}\033[22m")

            if return_index != 2:
                return "Usage: findmol <name-or-formula> [return <attribute> ...]"

        elif len(arguments) > 2:
            return "Usage: findmol <name-or-formula> [return <attribute> ...]"

        # Search the local dataset first.
        result = execute(
            ["search", "molecules", "name", "like", value, "or", "formula", "like", value]
        )

        if result == [] or result == "No matching item":
            result = fetch_pubchem_molecule(value)

        if result is None:
            return (f"Could not find molecule `{value}`" if NO_ANSI else f"Could not find molecule \033[1m{value}\033[22m")

        if isinstance(result, str) and "PubChem is currently unavailable" in result:
            return result

        if isinstance(result, str) and "could not be found in the recommended sources" in result.lower():
            return result

        # Apply optional projection.
        if return_attributes:
            if isinstance(result, list):
                return project_results(result, return_attributes)

            return ReturnTable({
                attribute: [getattr(result, attribute)]
                for attribute in return_attributes
            })

        return result

    if arguments[0] == "findre":
        if len(arguments) < 2:
            return "Usage: findre <name-or-id> [return <attribute> ...]"

        value = arguments[1]
        return_attributes = None

        if "return" in arguments[2:]:
            return_index = arguments.index("return", 2)
            return_attributes = arguments[return_index + 1:]

            if not return_attributes:
                return "Usage: findre <name-or-id> return <attribute> ..."

            for attribute in return_attributes:
                if attribute not in reactionKeys:
                    return (f"There is no key `{attribute}`" if NO_ANSI else f"There is no key \033[1m{attribute}\033[22m")

            if return_index != 2:
                return "Usage: findre <name-or-id> [return <attribute> ...]"

        elif len(arguments) > 2:
            return "Usage: findre <name-or-id> [return <attribute> ...]"

        result = execute([
            "search", "reactions",
            "name", "like", value,
            "or", "id", "like", value,
            "or", "equation", "like", value,
        ])

        if result == [] or result == "No matching item":
            result = find_reaction(value, external=True)
            if result is None:
                return (f"Could not find reaction `{value}` in Reactions.json, Rhea, or Chempirical" if NO_ANSI else f"Could not find reaction \033[1m{value}\033[22m in Reactions.json, Rhea, or Chempirical")

        if return_attributes:
            if isinstance(result, list):
                return project_results(result, return_attributes)

            return ReturnTable({
                attribute: [getattr(result, attribute)]
                for attribute in return_attributes
            })

        return result

    if arguments[0] == "clear":
        if len(arguments) != 1:
            return "Usage: clear"

        print("\033[2J\033[H", end="")
        return

    if arguments[0] == "source":
        if len(arguments) != 2:
            return "Usage: source <source>"

        source_name = arguments[1]

        if source_name not in SOURCES:
            return (f"There is no source `{source_name}`" if NO_ANSI else f"There is no source \033[1m{source_name}\033[22m")

        current_source = source_name
        return (f"Source set to `{source_name}`" if NO_ANSI else f"Source set to \033[1m{source_name}\033[22m")

    if arguments[0] == "list":
        if len(arguments) != 2 or arguments[1] != "all":
            return "Usage: list all"

        if current_source is None:
            return list(SOURCES)

        _, keys = SOURCES[current_source]
        return list(keys)

    if arguments[0] == "search":
        i = 1
        mode = "all"

        if i < len(arguments) and arguments[i] in ("first", "last", "all"):
            mode = arguments[i]
            i += 1

        if (
            i + 1 < len(arguments)
            and arguments[i] in SOURCES
            and (
                current_source is None
                or arguments[i + 1] not in operators
            )
        ):
            source_name = arguments[i]
            i += 1
        else:
            source_name = current_source

        if source_name is None:
            return (
                "No source selected. "
                "Specify one, e.g. "+
                ("`search all elements atomic_mass < 100`" if NO_ANSI else "\033[1msearch all elements atomic_mass < 100\033[22m")
            )

        source, keys = SOURCES[source_name]
        if i >= len(arguments):
            return list(source)
        return_attributes = None

        if "return" in arguments[i:]:
            return_index = arguments.index("return", i)
            query_tokens = arguments[i:return_index]
            return_attributes = arguments[return_index + 1:]

            if not return_attributes:
                return format_error("Usage: return <attribute> [<attribute> ...]", query_text)

            for attribute_index, attribute in enumerate(return_attributes):
                if attribute not in keys:
                    absolute_index = return_index + 1 + attribute_index
                    pos, length = error_position(positions, absolute_index) if positions else (None, 1)
                    return format_error(
                        (f"There is no key `{attribute}`" if NO_ANSI else f"There is no key \033[1m{attribute}\033[22m"),
                        query_text,
                        pos,
                        length
                    )
        else:
            query_tokens = arguments[i:]

        try:
            condition, operation_index = parse_query(
                query_tokens,
                source,
                keys,
                positions[i:] if positions else None
            )
        except ChemQLError as e:
            return format_error(str(e), query_text, e.position, e.length)
        except ValueError as e:
            return format_error(str(e))

        results = [item for item in source if condition(item)]

        try:
            results = apply_query_operations(
                results,
                query_tokens[operation_index:],
                keys,
                positions[i + operation_index:] if positions else None
            )
        except ChemQLError as e:
            return format_error(str(e), query_text, e.position, e.length)
        except ValueError as e:
            return format_error(str(e))

        if isinstance(results, int):
            if mode != "all":
                return format_error(("`count` cannot be combined with `first` or `last`" if NO_ANSI else "\033[1mcount\033[22m cannot be combined with \033[1mfirst\033[22m or \033[1mlast\033[22m"))
            if return_attributes is not None:
                return format_error(("`return` cannot be used with `count`" if NO_ANSI else "\033[1mreturn\033[22m cannot be used with \033[1mcount\033[22m"))
            return results

        # `return` is a projection. It intentionally happens after
        # filtering, sorting, limiting, and first/last selection.
        if return_attributes is not None:
            if mode == "first":
                selected = results[:1]
            elif mode == "last":
                selected = results[-1:]
            else:
                selected = results

            if not selected:
                if len(return_attributes) == 1:
                    return []
                return ReturnTable({attribute: [] for attribute in return_attributes})

            return project_results(selected, return_attributes)

        if mode == "first":
            result = results[0] if results else None
        elif mode == "last":
            result = results[-1] if results else None
        else:
            if len(results) == 1:
                result = results[0]
            else:
                result = results

        if result is None:
            return "No matching item"

        return result

    if query_text is not None and positions:
        pos, length = error_position(positions, 0)
        message = f"Unknown command `{arguments[0]}`"
        if _CHEMQL_RISK_DEPTH:
            raise _ChemQLUnknownCommand(message, pos, length)
        return format_error(
            (message if NO_ANSI else f"Unknown command \033[1m{arguments[0]}\033[22m"),
            query_text,
            pos,
            length
        )

    message = f"Unknown command `{arguments[0]}`"
    if _CHEMQL_RISK_DEPTH:
        raise _ChemQLUnknownCommand(message)
    return format_error(message if NO_ANSI else f"Unknown command \033[1m{arguments[0]}\033[22m")


HELP = (
    "\x1b[1;94m╭──────────────────────────────────────────────────────────────────────────────╮\x1b[0m\n"
   f"\x1b[1;94m│\x1b[0m  \x1b[1;96m✦ \x1b[1mChemQL\x1b[0m \x1b[97mv{__version__}\x1b[0m    \x1b[90m│\x1b[0m \x1b[1m\x1b[97mTHE PYTHON CHEMISTRY QUERY LANGUAGE\x1b[0m                    \x1b[1;94m│\x1b[0m\n"
    "\x1b[1;94m│\x1b[0m  \x1b[90mQuery chemistry · automate calculations · build reusable programs\x1b[0m           \x1b[1;94m│\x1b[0m\n"
    "\x1b[1;94m╰──────────────────────────────────────────────────────────────────────────────╯\x1b[0m\n"
    "\n"
    "\x1b[1;93m\x1b[1m▶  QUICK START\x1b[0m\n"
    "  \x1b[92msearch elements ...          \x1b[0m \x1b[90m│\x1b[0m Search the periodic table\n"
    "  \x1b[92msearch molecules ...         \x1b[0m \x1b[90m│\x1b[0m Search molecule records\n"
    "  \x1b[92msearch reactions ...         \x1b[0m \x1b[90m│\x1b[0m Search stored reactions\n"
    "  \x1b[92mfindel \"He\"                  \x1b[0m \x1b[90m│\x1b[0m Find an element\n"
    "  \x1b[92mfindmol \"Water\"              \x1b[0m \x1b[90m│\x1b[0m Find a molecule\n"
    "  \x1b[92mfindre \"Haber process\"       \x1b[0m \x1b[90m│\x1b[0m Find a reaction\n"
    "  \x1b[92mbalance H2 + O2 -> H2O       \x1b[0m \x1b[90m│\x1b[0m Balance a chemical equation\n"
    "  \x1b[92mhelp  or  ?                  \x1b[0m \x1b[90m│\x1b[0m Display this help message\n"
    "  \x1b[92mhelp{read_csv}               \x1b[0m \x1b[90m│\x1b[0m Show detailed built-in documentation\n"
    "  \x1b[92mhelp{stdlib}                 \x1b[0m \x1b[90m│\x1b[0m List standard-library packages\n"
    "  \x1b[92mhelp{math}                   \x1b[0m \x1b[90m│\x1b[0m Show package documentation\n"
    "  \x1b[92mhelp{math::sqrt}             \x1b[0m \x1b[90m│\x1b[0m Show package function help\n"
    "  \x1b[92mversion                      \x1b[0m \x1b[90m│\x1b[0m Display the installed version\n"
    "  \x1b[92mexit                         \x1b[0m \x1b[90m│\x1b[0m Exit the interactive prompt\n"
    "\n"
    "\x1b[1;93m\x1b[1m◆  CHEMICAL DATA & SEARCH\x1b[0m\n"
    "  \x1b[1;96msearch elements [conditions]  \x1b[0m      \x1b[90m│\x1b[0m Query element data\n"
    "  \x1b[1;96msearch molecules [conditions] \x1b[0m      \x1b[90m│\x1b[0m Query molecule data\n"
    "  \x1b[1;96msearch reactions [conditions] \x1b[0m      \x1b[90m│\x1b[0m Query stored reaction data\n"
    "  \x1b[1;96msource elements|molecules|reactions\x1b[0m \x1b[90m│\x1b[0m Set the current source\n"
    "  \x1b[1;96mlist all                      \x1b[0m      \x1b[90m│\x1b[0m List available fields and sources\n"
    "    \x1b[95msearch elements symbol = \"Fe\" return name symbol number\x1b[0m\n"
    "    \x1b[95msearch molecules molecular_weight < 50 sort molecular_weight limit 10\x1b[0m\n"
    "    \x1b[95msearch reactions reversible = true return name equation source\x1b[0m\n"
    "\n"
    "\x1b[1;93m\x1b[1m◆  FILTERS & LOGIC\x1b[0m\n"
    "  \x1b[1;96m= != > < >= <=               \x1b[0m \x1b[90m│\x1b[0m Comparison operators\n"
    "  \x1b[1;96mlike                         \x1b[0m \x1b[90m│\x1b[0m Case-insensitive wildcard match\n"
    "  \x1b[1;96mlike!                        \x1b[0m \x1b[90m│\x1b[0m Case-sensitive wildcard match\n"
    "  \x1b[1;96mlikep                        \x1b[0m \x1b[90m│\x1b[0m Pattern-based matching\n"
    "  \x1b[1;96mhas                          \x1b[0m \x1b[90m│\x1b[0m Check whether a collection contains an item\n"
    "  \x1b[1;96mand / or                     \x1b[0m \x1b[90m│\x1b[0m Combine conditions\n"
    "    \x1b[95msearch elements number > 10 and number < 20\x1b[0m\n"
    "    \x1b[95msearch molecules name like \"*water*\"\x1b[0m\n"
    "    \x1b[95msearch reactions reactants has \"O2\" and products has \"H2O\"\x1b[0m\n"
    "\n"
    "\x1b[1;93m\x1b[1m◆  RESULT OPERATIONS\x1b[0m\n"
    "  \x1b[92mfirst / last                 \x1b[0m \x1b[90m│\x1b[0m Select the first or last result\n"
    "  \x1b[92msort FIELD [asc|desc]        \x1b[0m \x1b[90m│\x1b[0m Sort matching records\n"
    "  \x1b[92mlimit N                      \x1b[0m \x1b[90m│\x1b[0m Limit the number of results\n"
    "  \x1b[92mcount                        \x1b[0m \x1b[90m│\x1b[0m Count matching records\n"
    "  \x1b[92mreturn FIELD ...             \x1b[0m \x1b[90m│\x1b[0m Choose fields to display\n"
    "  \x1b[92munion / intersection         \x1b[0m \x1b[90m│\x1b[0m Combine result sets\n"
    "    \x1b[95msearch molecules molecular_weight < 20 sort molecular_weight asc limit 5\x1b[0m\n"
    "\n"
    "\x1b[1;93m\x1b[1m◆  REACTIONS & CONDITIONS\x1b[0m\n"
    "  \x1b[1;96mbalance H2 + O2 -> H2O       \x1b[0m \x1b[90m│\x1b[0m Balance an equation\n"
    "  \x1b[1;96mbalance N2 + H2 <-> NH3      \x1b[0m \x1b[90m│\x1b[0m Balance a reversible equation\n"
    "  \x1b[1;96mreact N2 3H2                 \x1b[0m \x1b[90m│\x1b[0m Find a matching stored reaction\n"
    "  \x1b[1;96mset temperature 150C         \x1b[0m \x1b[90m│\x1b[0m Set the reaction temperature\n"
    "  \x1b[1;96mset pressure 1atm            \x1b[0m \x1b[90m│\x1b[0m Set the reaction pressure\n"
    "  \x1b[1;96mset catalysts iron zinc      \x1b[0m \x1b[90m│\x1b[0m Set available catalysts\n"
    "  \x1b[1;96mset catalysts                \x1b[0m \x1b[90m│\x1b[0m Clear the catalyst list\n"
    "  \x1b[1;96madd catalyst \"Iron\"          \x1b[0m \x1b[90m│\x1b[0m Add a catalyst\n"
    "  \x1b[1;96mremove catalyst \"Iron\"       \x1b[0m \x1b[90m│\x1b[0m Remove a catalyst\n"
    "  \x1b[1;96mconditions                   \x1b[0m \x1b[90m│\x1b[0m Display current conditions\n"
    "  \x1b[2mTemperature units: K, C, F. Pressure units include Pa, bar, and atm.\x1b[0m\n"
    "\n"
    "\x1b[1;93m\x1b[1m◆  VARIABLES & DEFINITIONS\x1b[0m\n"
    "  \x1b[95mlet answer = 42              \x1b[0m \x1b[90m│\x1b[0m Create or assign a variable\n"
    "  \x1b[95munset answer                 \x1b[0m \x1b[90m│\x1b[0m Remove a variable\n"
    "  \x1b[95mvariables                    \x1b[0m \x1b[90m│\x1b[0m List current variables\n"
    "  \x1b[95mdefine MAX 9                 \x1b[0m \x1b[90m│\x1b[0m Define a literal replacement\n"
    "  \x1b[95m@MAX                         \x1b[0m \x1b[90m│\x1b[0m Use a definition\n"
    "  \x1b[95mdefinitions                  \x1b[0m \x1b[90m│\x1b[0m List definitions\n"
    "  \x1b[95mremove definition MAX        \x1b[0m \x1b[90m│\x1b[0m Remove a definition\n"
    "    \x1b[95mdefine MAX 9\x1b[0m\n"
    "    \x1b[95msearch elements number <= @MAX\x1b[0m\n"
    "\n"
    "\x1b[1;93m\x1b[1m◆  FUNCTIONS & MACROS\x1b[0m\n"
    "  \x1b[95mfunc square                  \x1b[0m \x1b[90m│\x1b[0m Start a function definition\n"
    "  \x1b[95mreturn [\\1 * \\1]             \x1b[0m \x1b[90m│\x1b[0m Return a value using argument \\1\n"
    "  \x1b[95mendfunc                      \x1b[0m \x1b[90m│\x1b[0m Finish a function definition\n"
    "  \x1b[95msquare{5}                    \x1b[0m \x1b[90m│\x1b[0m Call a function\n"
    "  \x1b[95mdefine double{}              \x1b[0m \x1b[90m│\x1b[0m Start a macro definition\n"
    "  \x1b[95menddefine                    \x1b[0m \x1b[90m│\x1b[0m Finish a macro definition\n"
    "  \x1b[95m@double{5}                   \x1b[0m \x1b[90m│\x1b[0m Expand and execute a macro\n"
    "  \x1b[95mmacros                       \x1b[0m \x1b[90m│\x1b[0m List defined macros\n"
    "  \x1b[2mFunction and macro arguments use positional placeholders: \\1, \\2, and so on.\x1b[0m\n"
    "\n"
    "\x1b[1;93m\x1b[1m◆  CONTROL FLOW\x1b[0m\n"
    "  \x1b[95mif condition ... endif         \x1b[0m \x1b[90m│\x1b[0m Conditional execution\n"
    "  \x1b[95mif / elif / else / endif       \x1b[0m \x1b[90m│\x1b[0m Branch between conditions\n"
    "  \x1b[95mfor item in iterable ... endfor\x1b[0m \x1b[90m│\x1b[0m Iterate over values\n"
    "  \x1b[95mwhile condition ... endwhile   \x1b[0m \x1b[90m│\x1b[0m Repeat while a condition holds\n"
    "  \x1b[95mbreak / continue               \x1b[0m \x1b[90m│\x1b[0m Control loop execution\n"
    "    \x1b[95mfor i in range(5)\x1b[0m\n"
    "        \x1b[95mlet value = i\x1b[0m\n"
    "    \x1b[95mendfor\x1b[0m\n"
    "  \x1b[2mPython-style blocks are also available: [for ...] ... [endblock].\x1b[0m\n"
    "\n"
    "\x1b[1;93m\x1b[1m◆  ERROR HANDLING\x1b[0m\n"
    "  \x1b[95mrisk ... endrisk             \x1b[0m \x1b[90m│\x1b[0m Run a protected block\n"
    "  \x1b[95mfix                          \x1b[0m \x1b[90m│\x1b[0m Handle an error from the risk block\n"
    "  \x1b[95mcleanup                      \x1b[0m \x1b[90m│\x1b[0m Run cleanup whether successful or not\n"
    "  \x1b[95msignal \"message\"             \x1b[0m \x1b[90m│\x1b[0m Raise a ChemQL signal\n"
    "  \x1b[95merror                        \x1b[0m \x1b[90m│\x1b[0m Inspect the error type in a fix block\n"
    "    \x1b[95mrisk\x1b[0m\n"
    "        \x1b[95msignal \"Something went wrong\"\x1b[0m\n"
    "    \x1b[95mfix\x1b[0m\n"
    "        \x1b[95mlet handled = error\x1b[0m\n"
    "    \x1b[95mcleanup\x1b[0m\n"
    "        \x1b[95mlet finished = true\x1b[0m\n"
    "    \x1b[95mendrisk\x1b[0m\n"
    "  \x1b[2mThe variable error contains the error type, or None after success.\x1b[0m\n"
    "\n"
    "\x1b[1;93m\x1b[1m◆  STRUCTS & METHODS\x1b[0m\n"
    "  \x1b[95menum Name ... endenum        \x1b[0m \x1b[90m│\x1b[0m Define named values; omitted values auto-increment\n"
    "  \x1b[95mstruct Name                  \x1b[0m \x1b[90m│\x1b[0m Define a structured data type\n"
    "  \x1b[95mstruct Name from Base        \x1b[0m \x1b[90m│\x1b[0m Inherit from structs, records, or Python classes\n"
    "  \x1b[95mrecord Name [from Base]      \x1b[0m \x1b[90m│\x1b[0m Define a record; records inherit from records\n"
    "  \x1b[95mfunc Type.__add__            \x1b[0m \x1b[90m│\x1b[0m Define an operator method\n"
    "  \x1b[2mEnum members use `Name.MEMBER`; explicit values can be mixed with automatic values.\x1b[0m\n"
    "  \x1b[2mStruct methods can implement custom behaviour and operator overloads.\x1b[0m\n"
    "    \x1b[95menum Levels\x1b[0m\n"
    "        \x1b[95mLOW = 50\x1b[0m\n"
    "        \x1b[95mMEDIUM\x1b[0m\n"
    "        \x1b[95mHIGH\x1b[0m\n"
    "    \x1b[95mendenum\x1b[0m\n"
    "    \x1b[95mstruct Dog from Animal\x1b[0m\n"
    "        \x1b[95mcolor!\x1b[0m\n"
    "    \x1b[95mendstruct\x1b[0m\n"
    "\n"
    "\x1b[1;93m\x1b[1m◆  PYTHON INTEGRATION\x1b[0m\n"
    "  \x1b[1;96m[x = 10]                     \x1b[0m \x1b[90m│\x1b[0m Execute a Python statement\n"
    "  \x1b[1;96m[print(x)]                   \x1b[0m \x1b[90m│\x1b[0m Run Python code\n"
    "  \x1b[1;96m[x * 2]                      \x1b[0m \x1b[90m│\x1b[0m Evaluate a Python expression\n"
    "    \x1b[95m{{ search elements name = \"Hydrogen\" }}\x1b[0m\n"
    "  \x1b[2mEmbedded {{ ... }} queries return results as values.\x1b[0m\n"
    "  Multiline Python blocks:\n"
    "    \x1b[95m[[[\x1b[0m\n"
    "    \x1b[95mfor x in range(3):\x1b[0m\n"
    "    \x1b[95m    print(x)\x1b[0m\n"
    "    \x1b[95m]]]\x1b[0m\n"
    "\n"
    "\x1b[1;93m\x1b[1m◆  SHELL, COMMENTS & COMPOSITION\x1b[0m\n"
    "  \x1b[1;96m`command`                    \x1b[0m \x1b[90m│\x1b[0m Run a system-shell command\n"
    "  \x1b[1;96m```bash ... ```              \x1b[0m \x1b[90m│\x1b[0m Run a multiline shell block\n"
    "  \x1b[1;96m// comment                   \x1b[0m \x1b[90m│\x1b[0m Single-line comment\n"
    "  \x1b[1;96m/// ... ///                  \x1b[0m \x1b[90m│\x1b[0m Multiline comment\n"
    "  \x1b[1;96mcommand1; command2           \x1b[0m \x1b[90m│\x1b[0m Execute multiple commands\n"
    "  \x1b[1;96m\\                            \x1b[0m \x1b[90m│\x1b[0m Continue input on the next line\n"
    "  \x1b[1;96mview                         \x1b[0m \x1b[90m│\x1b[0m Open the periodic-table viewer\n"
    "  \x1b[1;96mclear                        \x1b[0m \x1b[90m│\x1b[0m Clear the terminal\n"
    "\n"
    "\x1b[1;93m\x1b[1m◆  EXECUTION HISTORY\x1b[0m\n"
    "  \x1b[92mdump FILE                     \x1b[0m \x1b[90m│\x1b[0m Export queries and results\n"
    "  \x1b[92mdump all FILE                 \x1b[0m \x1b[90m│\x1b[0m Export all execution records\n"
    "  \x1b[92mdump good FILE                \x1b[0m \x1b[90m│\x1b[0m Export successful executions\n"
    "  \x1b[92mdump bad FILE                 \x1b[0m \x1b[90m│\x1b[0m Export failed executions\n"
    "  \x1b[92mdump all|good|bad queries FILE\x1b[0m \x1b[90m│\x1b[0m Export query text only\n"
    "  \x1b[92mdump all|good|bad results FILE\x1b[0m \x1b[90m│\x1b[0m Export results only\n"
    "\n"
    "\x1b[1;93m\x1b[1m◆  COMMAND-LINE OPTIONS\x1b[0m\n"
    "  \x1b[1;96mchemql                       \x1b[0m \x1b[90m│\x1b[0m Start the interactive prompt\n"
    "  \x1b[1;96mchemql -c \"COMMAND\"          \x1b[0m \x1b[90m│\x1b[0m Execute one command\n"
    "  \x1b[1;96mchemql -f FILE               \x1b[0m \x1b[90m│\x1b[0m Execute a file\n"
    "  \x1b[1;96mchemql --version             \x1b[0m \x1b[90m│\x1b[0m Display version information\n"
    "  \x1b[1;96mchemql --no-ansi             \x1b[0m \x1b[90m│\x1b[0m Disable ANSI styling\n"
    "  \x1b[1;96mchemql -c \"COMMAND\" -o FILE  \x1b[0m \x1b[90m│\x1b[0m Save command output to a file\n"
    "  \x1b[1;96mchemql --upgrade [VERSION]   \x1b[0m \x1b[90m│\x1b[0m Upgrade ChemQL\n"
    "  \x1b[1;96mchemql --force               \x1b[0m \x1b[90m│\x1b[0m Override package-manager protections\n"
    "\n"
    "\x1b[1;93m\x1b[1m◆  PYTHON API\x1b[0m\n"
    "    \x1b[95mfrom chemql import execute_query_text, execute_query\x1b[0m\n"
    "    \x1b[95mresult = execute_query_text('search elements symbol = \"O\"')\x1b[0m\n"
    "  \x1b[2mDistribution: chemql-python · Import and CLI name: chemql\x1b[0m\n"
    "\n"
    "\x1b[1;93m\x1b[1m⚠  SAFETY NOTES\x1b[0m\n"
    "  \x1b[2mPython blocks and shell commands execute real code with your permissions.\x1b[0m\n"
    "  \x1b[2mOnly run code and commands you trust. External lookups require network access.\x1b[0m\n"
    "\n"
    "\x1b[1;94m────────────────────────────────────────────────────────────────────────────────\x1b[0m\n"
   f"\x1b[90mChemQL {__version__} · Type \x1b[92mhelp\x1b[90m for help, or \x1b[92mexit\x1b[90m to quit.\x1b[0m\n"
)


import webbrowser
from pathlib import Path

def view_periodic_table():
    path = Path(__file__).parent / "html" /"periodic_table.html"
    webbrowser.open(path.resolve().as_uri())


class ChemqlLexer(Lexer):
    """Dynamic syntax highlighting for ChemQL and its interactive objects."""

    COMMANDS = {
        "search", "source", "list", "clear", "exit", "findel", "findmol",
        "findre", "set", "add", "remove", "react", "balance", "conditions",
        "view", "help", "dump", "version", "return", "union", "intersection",
        "let", "unset", "variables", "macros", "definitions", "arguments",
        "define", "func", "struct", "record", "enum", "risk", "fix", "cleanup",
        "signal", "import", "remove", "load"
    }
    OPERATORS = {
        "and", "or", "has", "like", "like!", "likep", "sort", "limit",
        "count", "asc", "desc", "in", "not", "is",
    }
    CONTROL_WORDS = {
        "if", "elif", "else", "for", "while", "break", "continue", "endblock",
        "endfor", "endwhile", "endif", "endrisk", "endstruct", "endrecord", "endenum",
        "endfunc", "enddefine", "func", "define", "struct", "record", "risk",
        "fix", "cleanup", "signal", "import", "as", "return", "public", "private",
        "required", "namespace", "endnamespace", "enum", "from"
    }
    CONDITIONS = {
        "temperature", "pressure", "catalyst", "catalysts", "standard", "room",
        "c", "f", "k", "pa", "bar",
    }

    @staticmethod
    def _dynamic_names():
        return {
            "variables": set(CHEMQL_VARIABLES) | {
                name for name in python_globals
                if isinstance(name, str) and not name.startswith("__")
            },
            "structs": set(STRUCTS),
            "records": set(RECORDS),
            "enums": set(ENUMS),
            "functions": set(FUNCTIONS),
            "macros": set(MACROS),
            "definitions": set(DEFINITIONS),
        }

    def lex_document(self, document):
        lines = document.lines
        names = self._dynamic_names()
        function_names = {n.split(".")[-1] for n in names["functions"]}

        def get_line(lineno):
            if lineno >= len(lines):
                return []
            line = lines[lineno]
            tokens = []
            i = 0

            # Leading indentation is kept verbatim for prompt_toolkit.
            while i < len(line) and line[i].isspace():
                start = i
                while i < len(line) and line[i].isspace():
                    i += 1
                tokens.append(("", line[start:i]))

            # Mark declaration names according to the declaration being edited.
            declaration = re.match(
                r"(?:struct|record|enum|func)\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)", line[i:], re.I
            )
            macro_declaration = re.match(r"define\s+([A-Za-z_]\w*)\s*\{\s*\}", line[i:], re.I)
            definition_declaration = re.match(r"define\s+([A-Za-z_]\w*)\s+", line[i:], re.I)
            declared_name = None
            declared_style = None
            if declaration:
                prefix = line[i:]
                keyword = prefix.split(None, 1)[0].casefold()
                declared_name = declaration.group(1)
                declared_style = "struct" if keyword == "struct" else "record" if keyword == "record" else "enum" if keyword == "enum" else "function"
            elif macro_declaration:
                declared_name, declared_style = macro_declaration.group(1), "macro"
            elif definition_declaration:
                declared_name, declared_style = definition_declaration.group(1), "definition"

            while i < len(line):
                ch = line[i]
                if ch.isspace():
                    j = i + 1
                    while j < len(line) and line[j].isspace():
                        j += 1
                    tokens.append(("", line[i:j]))
                    i = j
                    continue
                if line.startswith("//", i):
                    tokens.append(("class:comment", line[i:]))
                    break
                if line.startswith("///", i):
                    tokens.append(("class:comment", line[i:]))
                    break
                if ch == "`":
                    j = line.find("`", i + 1)
                    j = len(line) - 1 if j < 0 else j
                    tokens.append(("class:terminalcommand", line[i:j + 1]))
                    i = j + 1
                    continue
                if line.startswith("[[[", i) or line.startswith("]]]", i):
                    marker = line[i:i + 3]
                    tokens.append(("class:python", marker))
                    i += 3
                    continue
                if line.startswith("{{", i):
                    j = line.find("}}", i + 2)
                    j = len(line) if j < 0 else j + 2
                    tokens.append(("class:interpolation", line[i:j]))
                    i = j
                    continue
                if ch in "'\"":
                    quote, j = ch, i + 1
                    while j < len(line):
                        if line[j] == "\\":
                            j += 2
                            continue
                        if line[j] == quote:
                            j += 1
                            break
                        j += 1
                    tokens.append(("class:string", line[i:j]))
                    i = j
                    continue
                if ch == "@":
                    match = re.match(r"@[A-Za-z_]\w*(?:\{[^}]*\})?", line[i:])
                    if match:
                        value = match.group(0)
                        key = value[1:].split("{", 1)[0]
                        style = "class:macro" if key in names["macros"] else "class:definition" if key in names["definitions"] else "class:operator"
                        tokens.append((style, value))
                        i += len(value)
                        continue
                if ch.isdigit():
                    match = re.match(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", line[i:])
                    value = match.group(0) #type:ignore
                    tokens.append(("class:number", value))
                    i += len(value)
                    continue
                if ch.isalpha() or ch == "_":
                    match = re.match(r"[A-Za-z_]\w*", line[i:])
                    word = match.group(0) #type:ignore
                    folded = word.casefold()
                    style = ""
                    if declared_name and word == declared_name.split(".")[-1]:
                        style = "class:" + declared_style #type:ignore
                        declared_name = None
                    elif not line[:i].strip():
                        style = "class:command" if folded in self.COMMANDS else ""
                    if not style:
                        if word in names["structs"]:
                            style = "class:struct"
                        elif word in names["records"]:
                            style = "class:record"
                        elif word in names["enums"]:
                            style = "class:enum"
                        elif word in names["functions"] or word in function_names:
                            style = "class:function"
                        elif word in names["macros"]:
                            style = "class:macro"
                        elif word in names["definitions"]:
                            style = "class:definition"
                        elif word in names["variables"]:
                            style = "class:variable"
                        elif folded in self.CONTROL_WORDS:
                            style = "class:control"
                        elif word in {"True", "False", "None"}:
                            style = "class:number"
                        elif word in {"print", "len", "str", "int", "float", "range", "enumerate", "zip", "list", "dict", "set", "tuple", "sum", "min", "max", "abs", "type", "isinstance"}:
                            style = "class:python"
                        elif word in SOURCES:
                            style = "class:source"
                        elif folded in self.CONDITIONS:
                            style = "class:condition"
                        elif folded in self.OPERATORS:
                            style = "class:operator"
                        elif word in elementKeys or word in moleculeKeys or word in reactionKeys:
                            style = "class:key"
                    tokens.append((style, word))
                    i += len(word)
                    continue
                operator = next((op for op in ("**", "//", "!=", ">=", "<=", "==", "+=", "-=", "*=", "/=", "->", "<->", "=", ">", "<", "+", "-", "*", "/", "%") if line.startswith(op, i)), None)
                if operator:
                    tokens.append(("class:operator", operator))
                    i += len(operator)
                    continue
                tokens.append(("", ch))
                i += 1
            return tokens
        return get_line


class ChemqlCompleter(Completer):
    """Context-aware completion for commands and dynamically created objects."""

    COMMANDS = (
        "search", "source", "list", "clear", "return", "exit", "findel", "findmol",
        "findre", "set", "add", "remove", "react", "balance", "conditions", "version",
        "help", "view", "dump", "let", "unset", "variables", "func", "define", "struct",
        "record", "enum", "risk", "fix", "cleanup", "signal", "import", "definitions", "macros",
        "endfor", "endwhile", "endif", "endrisk", "endstruct", "endrecord", "endenum", "endfunc", "enddefine",
    )
    QUERY_OPERATORS = ["=", "!=", ">", "<", ">=", "<=", "like", "like!", "likep", "has", "sort", "limit", "count", "asc", "desc", "return", "and", "or", "union", "intersection"]
    CONTROL_COMPLETIONS = ["if ", "for ", "while ", "endfor", "endwhile", "endif", "risk", "fix", "cleanup", "endrisk", "struct ", "endstruct", "record ", "endrecord", "enum ", "endenum", "func ", "endfunc", "define ", "enddefine"]

    @staticmethod
    def _names():
        variables = set(CHEMQL_VARIABLES) | {
            name for name in python_globals
            if isinstance(name, str) and not name.startswith("__") and name.isidentifier()
        }
        return {
            "variables": variables,
            "structs": set(STRUCTS),
            "records": set(RECORDS),
            "enums": set(ENUMS),
            "python_types": {
                name for name, value in python_globals.items()
                if isinstance(name, str) and isinstance(value, type) and not issubclass(value, Enum)
            },
            "functions": set(FUNCTIONS),
            "macros": set(MACROS),
            "definitions": set(DEFINITIONS),
        }

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        stripped = text.lstrip()
        parts = stripped.split()
        trailing_space = bool(text and text[-1].isspace())
        current = "" if trailing_space or not parts else parts[-1]
        command_words = parts if trailing_space else parts[:-1]
        names = self._names()

        def emit(values):
            seen = set()
            for value in values:
                value = str(value)
                key = value.casefold()
                if key not in seen and key.startswith(current.casefold()):
                    seen.add(key)
                    yield Completion(value, start_position=-len(current))

        dynamic = sorted(set().union(*names.values()), key=str.casefold)
        if not command_words:
            yield from emit(list(self.COMMANDS) + self.CONTROL_COMPLETIONS + dynamic)
            return

        command = command_words[0].casefold()
        suggestions = []
        if command == "let":
            suggestions = ["name = value"] if len(command_words) == 1 else ["="]
        elif command == "unset":
            suggestions = sorted(names["variables"])
        elif command == "source":
            suggestions = list(SOURCES)
        elif command == "search":
            if len(command_words) == 1:
                suggestions = list(SOURCES)
            elif len(command_words) >= 2 and command_words[1] in SOURCES:
                _, keys = SOURCES[command_words[1]]
                suggestions = list(keys) + self.QUERY_OPERATORS
        elif command == "set":
            if len(command_words) == 1:
                suggestions = ["temperature", "pressure", "catalysts"]
            elif len(command_words) == 2:
                setting = command_words[1].casefold()
                suggestions = {
                    "temperature": ["standard", "room", "0C", "0F", "0K"],
                    "pressure": ["standard", "room", "0Pa", "0N/m^2", "0Nm^-2", "0bar", "1atm"],
                    "catalysts": list(reaction_state["catalysts"]),
                }.get(setting, [])
        elif command in {"add", "remove"}:
            if len(command_words) == 1:
                suggestions = ["catalyst", "definition"] if command == "remove" else ["catalyst"]
            elif command == "remove" and command_words[1].casefold() == "catalyst":
                suggestions = list(reaction_state["catalysts"])
            elif command == "remove" and command_words[1].casefold() == "definition":
                suggestions = sorted(names["definitions"])
        elif command == "variables":
            suggestions = sorted(names["variables"])
        elif command == "definitions":
            suggestions = sorted(names["definitions"])
        elif command == "macros":
            suggestions = sorted(names["macros"])
        elif command == "func":
            suggestions = sorted(names["structs"])
        elif command == "struct":
            if len(command_words) >= 3 and command_words[2].casefold() == "from":
                suggestions = sorted(names["structs"] | names["records"] | names["python_types"])
            else:
                suggestions = sorted(names["structs"])
        elif command == "record":
            suggestions = sorted(names["records"])
        elif command == "enum":
            suggestions = sorted(names["enums"])
        elif command in {"print", "return", "unset"}:
            suggestions = sorted(names["variables"])
        elif command in {"risk", "fix", "cleanup", "endrisk", "endstruct", "endrecord", "endenum", "endfunc", "enddefine", "endfor", "endwhile", "endif"}:
            suggestions = self.CONTROL_COMPLETIONS

        # In expressions, Python blocks, attribute access, and function calls,
        # offer all user-defined symbols, not just built-in commands.
        if not suggestions or "{{" in text or text.lstrip().startswith("[") or "." in current:
            suggestions += dynamic
        yield from emit(suggestions)


chemql_style = Style.from_dict({
    "command": "ansicyan",
    "terminalcommand": "ansipurple",
    "comment": "#545454 bold underline",
    "source": "ansiblue",
    "key": "ansimagenta",
    "operator": "ansiyellow",
    "string": "ansigreen",
    "number": "ansimagenta",
    "control": "ansired",
    "python": "ansibrightcyan",
    "condition": "ansibrightyellow",
    "variable": "ansibrightgreen",
    "struct": "ansibrightblue bold",
    "record": "ansicyan bold",
    "enum": "ansimagenta bold",
    "function": "ansiyellow bold",
    "macro": "ansimagenta bold",
    "definition": "ansibrightmagenta",
    "interpolation": "ansibrightcyan italic",
})


class _ChemQLField:
    """Field selector used by the fluent Python query API."""
    def __init__(self, query, field):
        self.query = query
        self.field = field

    def condition(self, **conditions):
        operators = {
            "eq": "=", "ne": "!=", "lt": "<", "lte": "<=",
            "gt": ">", "gte": ">=", "like": "like", "likep": "likep",
            "has": "has",
        }
        if len(conditions) != 1:
            raise ValueError("condition() expects exactly one condition, e.g. lt=10")
        name, value = next(iter(conditions.items()))
        if name not in operators:
            raise ValueError(f"Unknown condition {name!r}; use {', '.join(operators)}")
        rendered = shlex.quote(str(value))
        return ChemQLQuery(f"{self.query.query} {self.field} {operators[name]} {rendered}")


class ChemQLQuery:
    """Composable ChemQL query. Use .execute() to evaluate it."""
    def __init__(self, query):
        self.query = str(query).strip()

    def __getattr__(self, field):
        if field.startswith("_"):
            raise AttributeError(field)
        return _ChemQLField(self, field)

    def return_(self, *attributes):
        if not attributes:
            raise ValueError("return_() requires at least one attribute")
        return ChemQLQuery(f"{self.query} return " + " ".join(attributes))

    def execute(self):
        return execute_query_text(self.query)

    def __or__(self, other):
        if not isinstance(other, ChemQLQuery):
            return NotImplemented
        return ChemQLQuery(f"{self.query} union {other.query}")

    def __and__(self, other):
        if not isinstance(other, ChemQLQuery):
            return NotImplemented
        return ChemQLQuery(f"{self.query} intersection {other.query}")

    def __str__(self):
        return (f"Query of `{self.query}`" if NO_ANSI else f"Query of \033[1m{self.query}\033[22m")

    def __repr__(self):
        return str(self)


def search(source):
    """Create a native Python API query, e.g. search('elements')."""
    source = str(source).strip()
    if source not in SOURCES:
        raise ValueError(f"Unknown ChemQL source {source!r}; expected one of {', '.join(SOURCES)}")
    return ChemQLQuery(f"search {source}")


def union(x, y):
    """Return the left-to-right union of two ChemQLQuery objects."""
    if not isinstance(x, ChemQLQuery) or not isinstance(y, ChemQLQuery):
        raise TypeError("union() expects two ChemQLQuery objects")
    return x | y


def intersection(x, y):
    """Return the intersection of two ChemQLQuery objects."""
    if not isinstance(x, ChemQLQuery) or not isinstance(y, ChemQLQuery):
        raise TypeError("intersection() expects two ChemQLQuery objects")
    return x & y

PACKAGE_NAME = "chemql-python"

def upgrade_package(version=None, force=False):
    """Upgrade ChemQL, optionally to a specific version."""

    if version is not None:
        # Accept ordinary numeric release versions, optionally with
        # prerelease or post-release suffixes.
        if not re.fullmatch(
            r"\d+(?:\.\d+)*(?:(?:a|b|rc)\d+)?(?:\.post\d+)?(?:\.dev\d+)?",
            version,
            re.IGNORECASE,
        ):
            print(f"Invalid version: {version}", file=sys.stderr)
            return 2

        target = f"{PACKAGE_NAME}=={version}"
        print(f"Installing {target}...")
        if force:
            cmd = [
                sys.executable, "-m", "pip", "install",
                "--force-reinstall", target, "--break-system-packages"
            ]
        else:
            cmd = [
                sys.executable, "-m", "pip", "install",
                "--force-reinstall", target,
            ]
    else:
        print(f"Upgrading {PACKAGE_NAME} to the latest version...")
        if force:
            cmd = [
                sys.executable, "-m", "pip", "install",
                "--upgrade", PACKAGE_NAME, "--break-system-packages"
            ]
        else:
            cmd = [
                sys.executable, "-m", "pip", "install",
                "--upgrade", PACKAGE_NAME,
            ]

    try:
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            print(
                f"Installation failed (exit code {result.returncode}).",
                file=sys.stderr,
            )
            return result.returncode

    except KeyboardInterrupt:
        print("\nUpgrade cancelled.", file=sys.stderr)
        return 130
    except OSError as exc:
        print(f"Could not run pip: {exc}", file=sys.stderr)
        return 1

    print("ChemQL installation completed.")
    return 0


ChemQLQuery.__name__ = "ChemQLQuery"
ChemQLQuery.__qualname__ = "ChemQLQuery"



def _unclosed_expression_delimiters(lines):
    """Return expected closing delimiters for an unfinished expression.

    This scanner is intentionally for REPL continuation only. It recognizes
    ChemQL's {{...}} query delimiters before ordinary braces and ignores
    delimiters inside quoted strings and // comments. The dedicated [[[...]]]
    block is handled separately by the REPL and must not be treated as a stack
    of ordinary square brackets.
    """
    expected = []
    quote = None
    escaped = False
    openers = ("{{", "{", "(", "[")
    closers = ("}}", "}", ")", "]")

    for line in lines:
        i = 0
        while i < len(line):
            ch = line[i]

            if quote is not None:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == quote:
                    quote = None
                i += 1
                continue

            if ch in ("'", '"'):
                quote = ch
                i += 1
                continue

            # ChemQL's single-line comments must not affect delimiter balance.
            if line.startswith("//", i):
                break

            # The triple-bracket multiline Python form is managed elsewhere.
            if line.startswith("[[[", i):
                i += 3
                continue
            if line.startswith("]]]", i):
                i += 3
                continue

            token = next((t for t in openers if line.startswith(t, i)), None)
            if token is not None:
                expected.append({"{{": "}}", "{": "}", "(": ")", "[": "]"}[token])
                i += len(token)
                continue

            token = next((t for t in closers if line.startswith(t, i)), None)
            if token is not None:
                if expected:
                    if expected[-1] != token:
                        raise SyntaxError(
                            f"Mismatched delimiter: expected {expected[-1]!r}, got {token!r}"
                        )
                    expected.pop()
                else:
                    # An unmatched closer belongs to the normal ChemQL parser
                    # to diagnose; it should not cause continuation prompting.
                    return []
                i += len(token)
                continue

            i += 1

        # A single-line string cannot legitimately span REPL input lines in
        # ordinary ChemQL expressions; retain quote state only for completeness.

    return expected


def main(ANSI: bool = True):
    parser = argparse.ArgumentParser(
        description=(
            "ChemQL query and chemistry language.\n"
            "Version 1.5.0 adds enums and inheritance for structs and records."
        )
    )

    parser.add_argument(
        "-c",
        "--command",
        help="Execute Chemql code"
    )

    parser.add_argument(
        "-f",
        "--file",
        help="Execute Chemql code from a file"
    )

    parser.add_argument(
        "--no-ansi",
        action="store_true",
        help="Strip ANSI escape sequences from output.",
    )

    parser.add_argument(
        "-o", "--output",
        metavar="FILE",
        help="Write -c or -f output to a file without ANSI sequences.",
    )

    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=__version__,
    )


    parser.add_argument(
        "--upgrade",
        nargs="?",
        const="latest",
        default=None,
        metavar="VERSION",
        help="Upgrade ChemQL, optionally to a specific version.",
    )

    parser.add_argument(
    "--force",
    "--dangerously",
    dest="force",
    action="store_true",
    help="Force the upgrade, including breaking system-package protections.",
    )

    args = parser.parse_args()

    if args.upgrade is not None:
        version_target = (
            None if args.upgrade == "latest" else args.upgrade
        )
        sys.exit(upgrade_package(version_target, args.force))

    global NO_ANSI
    NO_ANSI = not ANSI or args.no_ansi or bool(args.output)

    if args.output and args.command is None and args.file is None:
        parser.error("-o/--output requires -c/--command or -f/--file")

    if args.command is not None or args.file:
        if args.command is not None:
            code = args.command
        else:
            code = Path(args.file).read_text(encoding="utf-8")

        if args.output:
            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()
            with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
                process_lines(code.splitlines())
            output_text = stdout_capture.getvalue() + stderr_capture.getvalue()
            Path(args.output).write_text(strip_ansi(output_text), encoding="utf-8")
        else:
            process_lines(code.splitlines())
        return

    if not sys.stdin.isatty():
        piped = sys.stdin.read()
        if piped.strip():
            process_lines(piped.splitlines())
        else:
            run_interactive()
    else:
        run_interactive()

def run_interactive():
        history = []
        welcome = "Type help or ? for help"
        print(welcome if NO_ANSI else "\033[1m" + welcome + "\033[0m")
        bindings = KeyBindings()

        def multiline_input_needs_more(text):
            """Return True when Enter should add a newline instead of submitting."""
            if not text:
                return False
            source_lines = text.splitlines()
            first = source_lines[0].strip()
            last = source_lines[-1].strip()

            if last.endswith("\\"):
                return True

            if first in {"[[[", "```", "```bash", "```sh", "```cmd", "```terminal"}:
                closer = "]]]" if first == "[[[" else "```"
                return not (len(source_lines) > 1 and last == closer)

            if re.fullmatch(r"(?:(?:static\s+func|func\s+static|func)\s+)" + _DEFINITION_NAME, first, re.IGNORECASE):
                return last.casefold() != "endfunc"

            if re.fullmatch(r"define\s+" + _DEFINITION_NAME + r"\s*\{\s*\}", first):
                return last.casefold() != "enddefine"

            if "///" in first:
                return sum(line.count("///") for line in source_lines) < 2

            # Track every block that requires a closing keyword. Named declarations
            # such as `struct Fruit` and `record Point` are headers too.
            stack = []
            closers = {
                "endrisk": "risk", "endstruct": "struct", "endrecord": "record", "endenum": "enum",
                "endfunc": "func", "enddefine": "macro", "endfor": "for",
                "endwhile": "while", "endif": "if", "[endblock]": "bracket", "endnamespace": "namespace"
            }
            for source_line in source_lines:
                stripped = source_line.strip()
                folded = stripped.casefold()
                if not stripped or stripped.startswith("//"):
                    continue

                if re.fullmatch(r"namespace\s+[A-Za-z_]\w*", stripped, re.IGNORECASE):
                    stack.append("namespace")
                declaration_line = re.sub(r"^(?:public|private)\s+", "", stripped, flags=re.IGNORECASE)
                if re.fullmatch(r"struct\s+[A-Za-z_]\w*(?:\s+from\s+(?:\[[^\]]+\]|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*))?", declaration_line, re.IGNORECASE):
                    stack.append("struct")
                elif re.fullmatch(r"record\s+[A-Za-z_]\w*(?:\s+from\s+(?:\[[^\]]+\]|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*))?", declaration_line, re.IGNORECASE):
                    stack.append("record")
                elif re.fullmatch(r"enum\s+[A-Za-z_]\w*", declaration_line, re.IGNORECASE):
                    stack.append("enum")
                elif re.fullmatch(r"func\s+[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?", stripped, re.IGNORECASE):
                    stack.append("func")
                elif re.fullmatch(r"define\s+[A-Za-z_]\w*\s*\{\s*\}", stripped, re.IGNORECASE):
                    stack.append("macro")
                elif folded == "risk":
                    stack.append("risk")
                elif re.match(r"^(for|while|if)\s+.+$", stripped, re.IGNORECASE) and not stripped.startswith("["):
                    stack.append(folded.split(None, 1)[0])
                elif is_python_block_header(stripped):
                    stack.append("bracket")
                elif folded in closers:
                    expected = closers[folded]
                    if stack and stack[-1] == expected:
                        stack.pop()

            return bool(stack)

        @bindings.add(Keys.Enter)
        def _handle_enter(event):
            buffer = event.current_buffer
            if multiline_input_needs_more(buffer.text):
                buffer.insert_text("\n")
            else:
                buffer.validate_and_handle()

        session = PromptSession(
            lexer=ChemqlLexer(),
            completer=ChemqlCompleter(),
            style=Style.from_dict({}) if NO_ANSI else chemql_style,
            reserve_space_for_menu=0,
            multiline=True,
            key_bindings=bindings,
            prompt_continuation=lambda width, line_number, is_soft_wrap: "... ",
        )
        while True:
            try:
                first_line = session.prompt(">>> ")

            except KeyboardInterrupt:
                print()
                break

            except EOFError:
                message = "\nUse CTRL+C or type 'exit' to exit"
                print(message if NO_ANSI else "\n\033[34mUse \033[1mCTRL+C\033[22m or type '\033[1mexit\033[22m' to exit\033[0m")
                continue
            if first_line.strip() == "":
                continue
            elif first_line.strip() == "exit":
                break

            elif first_line.strip() in ("?", "help"):
                print(strip_ansi(HELP) if NO_ANSI else HELP)
                continue

            elif first_line.strip().lower() == "sorry":
                message = "It's ok, everybody makes mistakes👌"
                print(message if NO_ANSI else "\033[34m" + message + "\033[0m")
                continue
            
            elif first_line.strip().split()[0].casefold() == "dump":
                try:
                    print(_dump_history(first_line.strip()))
                except Exception as exc:
                    print(f"Error: {exc}" if NO_ANSI else "\033[31m" + f"Error: {exc}" + "\033[0m")
                continue
        
            if not first_line.strip():
                continue

            # PromptSession now edits multiline blocks in one buffer, so the
            # user can move across lines and Backspace can join them.
            lines = first_line.splitlines() or [first_line]

            # Preserve the existing backslash continuation behavior for commands
            # that were not collected as a block by the Enter key binding.
            while lines[-1].rstrip().endswith("\\"):
                lines[-1] = lines[-1].rstrip()[:-1] + " "
                try:
                    next_line = session.prompt("... ")
                except KeyboardInterrupt:
                    print()
                    lines = []
                    break
                except EOFError:
                    message = "Error: Incomplete continued input"
                    print("\n" + (message if NO_ANSI else "\033[31m" + message + "\033[0m"))
                    lines = []
                    break
                lines.extend(next_line.splitlines() or [next_line])
            if not lines:
                continue

            # Collect function and macro declarations as complete REPL units.
            if lines and re.fullmatch(r"(?:(?:static\s+func|func\s+static|func)\s+)" + _DEFINITION_NAME, lines[0].strip(), re.IGNORECASE):
                while lines[-1].strip().casefold() != "endfunc":
                    try:
                        lines.append(session.prompt("... "))
                    except (KeyboardInterrupt, EOFError):
                        print("\nIncomplete function definition")
                        lines = []
                        break
                if not lines:
                    continue
            elif lines and re.fullmatch(r"define\s+" + _DEFINITION_NAME + r"\s*\{\s*\}", lines[0].strip()):
                while lines[-1].strip().casefold() != "enddefine":
                    try:
                        lines.append(session.prompt("... "))
                    except (KeyboardInterrupt, EOFError):
                        print("\nIncomplete macro definition")
                        lines = []
                        break
                if not lines:
                    continue
                        # Collect risk/fix/cleanup blocks as complete REPL units.
            if lines and lines[0].strip().casefold() == "risk":
                depth = 0

                for existing_line in lines:
                    token = existing_line.strip().casefold()
                    if token == "risk":
                        depth += 1
                    elif token == "endrisk":
                        depth -= 1

                while depth > 0:
                    try:
                        next_line = session.prompt("... ")
                    except (KeyboardInterrupt, EOFError):
                        print("\nIncomplete risk block")
                        lines = []
                        break

                    added_lines = next_line.splitlines() or [next_line]
                    lines.extend(added_lines)

                    for added_line in added_lines:
                        token = added_line.strip().casefold()
                        if token == "risk":
                            depth += 1
                        elif token == "endrisk":
                            depth -= 1

                if not lines:
                    continue
            # Collect new multiline Python, terminal, and comment blocks in the REPL.
            if lines and lines[0].strip() in {"[[[", "```", "```bash", "```sh", "```cmd", "```terminal"}:
                opener = lines[0].strip()
                closer = "]]]" if opener == "[[[" else "```"
                while not (len(lines) > 1 and lines[-1].strip() == closer):
                    try:
                        next_line = session.prompt("... ")
                    except (KeyboardInterrupt, EOFError):
                        print("\nIncomplete multiline block")
                        lines = []
                        break
                    lines.append(next_line)
                if not lines:
                    continue

            elif lines and "///" in lines[0]:
                # Collect multiline comment until its closing marker.
                while sum(line.count("///") for line in lines) < 2:
                    try:
                        next_line = session.prompt("... ")
                    except (KeyboardInterrupt, EOFError):
                        print("\nIncomplete multiline comment")
                        lines = []
                        break
                    lines.append(next_line)
                if not lines:
                    continue

            # Collect multiline expressions only when a physical line ends
            # with an expression opener. Structured constructs are handled by
            # their existing collectors above/below and must retain newlines.
            structured_start = bool(lines) and (
                lines[0].strip() == "[[["
                or lines[0].strip().startswith(("```", "func ", "define "))
                or "///" in lines[0]
                or is_python_block_header(lines[0].strip())
            )
            opens_at_line_end = bool(lines) and any(
                line.rstrip().endswith(("{{", "{", "(", "["))
                for line in lines
            )
            if lines and not structured_start and opens_at_line_end:
                try:
                    pending = _unclosed_expression_delimiters(lines)
                    while pending:
                        next_line = session.prompt("... ")
                        lines.extend(next_line.splitlines() or [next_line])
                        pending = _unclosed_expression_delimiters(lines)
                    if len(lines) > 1:
                        # These delimiters represent one expression: collapse
                        # physical lines before handing it to ChemQL evaluation.
                        lines = [" ".join(part.strip() for part in lines if part.strip())]
                except KeyboardInterrupt:
                    print()
                    lines = []
                except EOFError:
                    message = "Error: Incomplete expression; missing closing delimiter"
                    print("\n" + (message if NO_ANSI else "\033[31m" + message + "\033[0m"))
                    lines = []
                except SyntaxError as exc:
                    message = f"Error: {exc}"
                    print(message if NO_ANSI else f"\033[31m{message}\033[0m")
                    lines = []
                if not lines:
                    continue

            # Collect a Python control block only if the single editable buffer
            # was submitted before its matching [endblock] was entered.
            if lines and is_python_block_header(lines[0].strip()):
                depth = 0
                for existing_line in lines:
                    if is_python_block_header(existing_line.strip()):
                        depth += 1
                    elif existing_line.strip() == "[endblock]":
                        depth -= 1

                while depth > 0:
                    try:
                        line = session.prompt(">>> ")
                    except KeyboardInterrupt:
                        print()
                        lines = []
                        break
                    except EOFError:
                        message = ("Missing `[endblock]`" if NO_ANSI else "Missing \033[1m[endblock]\033[22m")
                        print("\n" + (message if NO_ANSI else "\033[31mMissing `\033[1m[endblock]\033[22m`\033[0m"))
                        lines = []
                        break

                    lines.extend(line.splitlines() or [line])
                    for added_line in (line.splitlines() or [line]):
                        if is_python_block_header(added_line.strip()):
                            depth += 1
                        elif added_line.strip() == "[endblock]":
                            depth -= 1
                if not lines:
                    continue

            try:
                process_lines(lines)
                history.extend(lines)
            except Exception as e:
                if isinstance(e, ChemQLBuiltinError):
                    message = f"Error: {type(e).__name__}: {e}"
                else:
                    message = f"Error: {e}"
                print(message if NO_ANSI else f"\033[31m{message}\033[0m")


if __name__ == "__main__":
    main(True)
