"""Logic layer for the CodecQLX editor, deliberately kept free of any
GUI toolkit import. Everything here is plain data in, plain data out, so it
can be unit tested without a display and reused if the GUI is ever ported
to another toolkit.

Covers:
  - tokenize_line / tokenize_lines: syntax-highlighting spans for ChemQL
  - SuggestionEngine: reads highlighting.json, returns every matching
    inline suggestion for the text before the cursor (not just the single
    best one the terminal editor shows -- the GUI can offer a real list)
  - DiagnosticsEngine: the same lightweight .cql checks the terminal
    CodecQL uses (TODO/FIXME, `warn`, division-by-zero, unmatched
    brackets/quotes), so both editors agree on what counts as a problem
  - Settings: the GUI's own small preferences file (separate from
    highlighting.json / colors.json, which belong to the CLI editor and
    are not touched here)
  - ChemQLBridge: optional integration with the installed `chemql` package
    for in-process query execution, periodic-table data and the
    equation balancer; degrades cleanly if chemql is not importable
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

# --------------------------------------------------------------------------
# Tokenizer
# --------------------------------------------------------------------------

#: Token type -> tag name used by the GUI's Text widget. Kept here so the
#: tokenizer and the renderer agree on names without the tokenizer needing
#: to know anything about Tk.
TOKEN_TAGS = (
    "comment", "string", "number", "formula", "operator", "delimiter",
    "command", "keyword", "constant", "source", "condition", "property",
    "builtin", "type",
)

_COMMANDS = (
    "search", "source", "set", "list", "clear", "return", "exit", "findel",
    "findmol", "findre", "balance", "react", "load", "install", "dump",
    "view", "version", "help", "variables", "unset", "definitions",
    "macros", "add", "remove", "conditions",
)
_KEYWORDS = (
    "and", "or", "not", "like", "like!", "likep", "has", "sort", "asc",
    "desc", "limit", "count", "first", "last", "all", "union",
    "intersection", "let", "define", "enddefine", "func", "endfunc",
    "static", "public", "private", "struct", "endstruct", "record",
    "endrecord", "enum", "endenum", "namespace", "endnamespace", "from",
    "if", "elif", "else", "endif", "for", "endfor", "in", "while",
    "endwhile", "break", "continue", "skip", "risk", "fix", "cleanup",
    "endrisk", "signal", "warn", "required",
)
_CONSTANTS = ("True", "False", "None", "true", "false", "null")
_SOURCES = ("elements", "molecules", "reactions")
_CONDITIONS = ("temperature", "pressure", "catalyst", "catalysts", "standard", "room")
_BUILTINS = (
    "molar_mass", "count_atoms", "empirical_formula", "element", "abs",
    "round", "min", "max", "sum", "len", "type", "str", "int", "float",
    "bool", "upper", "lower", "contains", "replace", "split", "join",
    "first", "last", "unique", "sort", "reversed", "read_text",
    "read_lines", "read_json", "read_csv", "write_text", "write_csv",
    "write_json", "file_exists", "list_files", "help",
)

_TOKEN_RE = re.compile(
    r"(?P<comment>//[^\n]*)"
    r"|(?P<string>\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')"
    r"|(?P<number>\b\d+\.?\d*(?:[A-Za-z]{1,4})?\b)"
    r"|(?P<formula>\b(?:[A-Z][a-z]?\d*){2,}\b)"
    r"|(?P<delimiter>\{\{|\}\}|\[\[\[|\]\]\]|[\[\]{}()])"
    r"|(?P<operator><->|->|<=|>=|!=|=|<|>|\+|@|\\)"
    r"|(?P<word>\b[A-Za-z_][A-Za-z0-9_!]*\b)"
)


@dataclass(frozen=True)
class Token:
    start: int
    end: int
    tag: str


class HighlightConfigError(Exception):
    pass


def _classify_hardcoded_word(text: str) -> Optional[str]:
    """The built-in word -> tag classification, used whenever no
    highlighting.json keyword rule claims a word first (see Tokenizer)."""
    if text in _COMMANDS:
        return "command"
    if text in _KEYWORDS:
        return "keyword"
    if text in _CONSTANTS:
        return "constant"
    if text in _SOURCES:
        return "source"
    if text in _CONDITIONS:
        return "condition"
    if text in _BUILTINS:
        return "builtin"
    if text in ("struct", "record", "enum", "namespace"):
        return "type"
    return None  # plain identifier/field name: no tag, default color


def tokenize_line(line: str) -> list[Token]:
    """Classify one line of ChemQL into (start, end, tag) spans using only
    the built-in word lists. Most callers should prefer a Tokenizer built
    from highlighting.json (see default_tokenizer()); this free function is
    kept for simple/standalone use and as the hardcoded fallback."""
    return _HARDCODED_TOKENIZER.tokenize_line(line)


def tokenize_lines(lines: Iterable[str]) -> list[list[Token]]:
    return [tokenize_line(line) for line in lines]


# --------------------------------------------------------------------------
# Keyword-highlighting rules loaded from highlighting.json's "rules" field
# (see CODECQL.md: type "keywords", "values", "style"). A rule's "style" is
# a full style string -- category names, bold/dim/italic/underline/reverse/
# strike, "#rrggbb" and "bg:#rrggbb" -- exactly as documented for the
# terminal editor, so a highlighting.json written for one works for both.
# --------------------------------------------------------------------------

_STYLE_ATTRIBUTES = ("bold", "dim", "italic", "underline", "reverse", "strike")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_BG_HEX_RE = re.compile(r"^bg:(#[0-9a-fA-F]{6})$")


@dataclass(frozen=True)
class ParsedStyle:
    categories: tuple[str, ...] = ()
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    reverse: bool = False
    strike: bool = False
    foreground: Optional[str] = None
    background: Optional[str] = None


def parse_style_string(style: str) -> ParsedStyle:
    """Parse a highlighting.json style string. Raises HighlightConfigError
    on an unrecognized part, per the documented rule that an unknown style
    part is an error."""
    categories: list[str] = []
    flags = {name: False for name in _STYLE_ATTRIBUTES}
    foreground: Optional[str] = None
    background: Optional[str] = None
    for part in style.split():
        if part in TOKEN_TAGS:
            categories.append(part)
        elif part in flags:
            flags[part] = True
        elif _HEX_RE.match(part):
            foreground = part
        else:
            bg_match = _BG_HEX_RE.match(part)
            if bg_match:
                background = bg_match.group(1)
            else:
                raise HighlightConfigError(f"unknown style part: {part!r}")
    return ParsedStyle(tuple(categories), background=background, foreground=foreground, **flags)


def blend_hex(color_a: str, color_b: str, amount: float) -> str:
    """Linearly blend two #rrggbb colors; amount=0 -> color_a, 1 -> color_b.
    Pure color math (no GUI toolkit involved), used to approximate a "dim"
    style as a faded version of its foreground color."""
    a = [int(color_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(color_b[i:i + 2], 16) for i in (1, 3, 5)]
    amount = max(0.0, min(1.0, amount))
    mixed = [round(a[i] + (b[i] - a[i]) * amount) for i in range(3)]
    return "#" + "".join(f"{value:02x}" for value in mixed)


class Tokenizer:
    """Tokenizes ChemQL source, consulting highlighting.json's "keywords"
    rules before the built-in word lists: a word matching a rule's
    "values" (case-insensitively) is tagged with that rule's own style
    instead of the hardcoded classification. Rules are applied in file
    order and the first rule that claims a word wins, matching the
    documented "first matching keyword wins" behavior. "regex"-type rules
    are accepted but not applied to drawing, same as the terminal editor.
    """

    def __init__(self, keyword_rules: Optional[list[dict]] = None):
        self._word_to_tag: dict[str, str] = {}
        self.custom_tag_styles: dict[str, ParsedStyle] = {}
        self.load_errors: list[str] = []
        for rule in (keyword_rules or []):
            self._apply_rule(rule)

    def _apply_rule(self, rule: Any) -> None:
        if not isinstance(rule, dict) or rule.get("type") != "keywords":
            return  # only "keywords" rules affect drawing; "regex" is not yet applied
        name, values, style = rule.get("name"), rule.get("values"), rule.get("style")
        if not isinstance(name, str) or not name:
            return
        if not isinstance(values, list) or not values or not isinstance(style, str):
            self.load_errors.append(f"{name}: a keywords rule needs non-empty 'values' and a 'style' string")
            return
        try:
            parsed = parse_style_string(style)
        except HighlightConfigError as error:
            self.load_errors.append(f"{name}: {error}")
            return
        tag_name = "rule_" + re.sub(r"[^A-Za-z0-9_]", "_", name)
        self.custom_tag_styles[tag_name] = parsed
        for value in values:
            if isinstance(value, str) and value:
                self._word_to_tag.setdefault(value.lower(), tag_name)  # first rule for a word wins

    def tag_for_word(self, word: str) -> Optional[str]:
        return self._word_to_tag.get(word.lower())

    def tokenize_line(self, line: str) -> list[Token]:
        tokens: list[Token] = []
        for match in _TOKEN_RE.finditer(line):
            kind = match.lastgroup
            text = match.group()
            start, end = match.start(), match.end()
            if kind == "word":
                tag = self.tag_for_word(text) or _classify_hardcoded_word(text)
                if tag is None:
                    continue
            else:
                tag = kind
            tokens.append(Token(start, end, tag))
        return tokens

    def tokenize_lines(self, lines: Iterable[str]) -> list[list[Token]]:
        return [self.tokenize_line(line) for line in lines]


_HARDCODED_TOKENIZER = Tokenizer()  # no highlighting.json rules: pure fallback classification


# --------------------------------------------------------------------------
# Suggestion engine (reads the same highlighting.json format as the
# terminal CodecQL -- see CODECQL.md for the authoritative rule semantics)
# --------------------------------------------------------------------------

def _normalize_extension(extension: str) -> str:
    extension = extension.lower()
    return extension if extension.startswith(".") else "." + extension


def _load_json_file(path: Path) -> dict:
    # utf-8-sig tolerates a BOM (a common Windows-tool artifact) without
    # treating a BOM-free file any differently.
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


class SuggestionEngine:
    """Loads highlighting.json (package copy, then a local override) and
    answers "what could the user mean" for the text before the cursor.

    Unlike the terminal editor, which shows only the single best-matching
    suggestion as ghost text, `suggestions_for` returns every candidate
    that matches what's already typed, so the GUI can offer a real
    dropdown list.
    """

    def __init__(self, search_paths: Optional[list[Path]] = None):
        self.run_commands: dict[str, str] = {}
        self.rules_by_extension: dict[str, list[dict]] = {}          # "suggestions" rules
        self.highlight_rules_by_extension: dict[str, list[dict]] = {}  # "rules" (syntax highlighting)
        self._load_errors: list[str] = []
        for path in (search_paths or []):
            self._load(path)

    @property
    def load_errors(self) -> list[str]:
        """Non-fatal problems hit while loading configs, for a status bar."""
        return list(self._load_errors)

    def _load(self, path: Path) -> None:
        if not path.is_file():
            return
        try:
            config = _load_json_file(path)
        except (OSError, json.JSONDecodeError) as error:
            self._load_errors.append(f"{path}: {error}")
            return
        if not isinstance(config, dict):
            self._load_errors.append(f"{path}: top level must be an object")
            return
        for raw_extension, profile in config.items():
            try:
                extension = _normalize_extension(str(raw_extension))
            except Exception:
                continue
            if not isinstance(profile, dict):
                continue
            run_command = profile.get("run-command")
            if isinstance(run_command, str) and run_command.strip():
                self.run_commands[extension] = run_command
            suggestions = profile.get("suggestions")
            if isinstance(suggestions, list):
                self.rules_by_extension[extension] = suggestions
            highlight_rules = profile.get("rules")
            if isinstance(highlight_rules, list):
                self.highlight_rules_by_extension[extension] = highlight_rules

    def get_run_command(self, filename: str) -> Optional[str]:
        extension = os.path.splitext(filename)[1].lower()
        return self.run_commands.get(extension)

    # -- rule matching --------------------------------------------------

    @staticmethod
    def _expand(text, kind, rules_by_name):
        """Expand every $rule-name$ reference in `text` (a pattern or a
        suggestion string). `kind` is "pattern" (join with |, parenthesize)
        or "list" (return every suggestion of the referenced rule)."""
        def replace(match):
            name = match.group(1)
            rule = rules_by_name.get(name)
            if rule is None:
                return match.group(0)
            values = rule.get("suggestions") or []
            if kind == "pattern":
                escaped = sorted((re.escape(v) for v in values), key=len, reverse=True)
                return "(?:" + "|".join(escaped) + ")" if escaped else "(?!)"
            return "\x00".join(values)  # placeholder, split back out below

        if kind == "pattern":
            return re.sub(r"\$([A-Za-z0-9_-]+)\$", replace, text)
        # kind == "list": a suggestion entry is either literal, or exactly
        # one $ref$ that should be replaced by that rule's whole list.
        match = re.fullmatch(r"\$([A-Za-z0-9_-]+)\$", text)
        if not match:
            return [text]
        rule = rules_by_name.get(match.group(1))
        return list(rule.get("suggestions") or []) if rule else []

    def _candidates(self, extension: str, line: str, cursor: int,
                     previous_lines: list[str]) -> tuple[str, list[str]]:
        """Return (prefix, candidate_words) for the line/cursor given, or
        ("", []) if no rule matches."""
        rules = self.rules_by_extension.get(extension) or []
        if not rules:
            return "", []
        before = line[:cursor]
        prefix_match = re.search(r"\S*$", before)
        prefix = prefix_match.group() if prefix_match else ""
        context = before[: len(before) - len(prefix)]

        rules_by_name: dict[str, dict] = {}
        for rule in rules:
            name = rule.get("name")
            pattern = rule.get("pattern")
            min_prefix = rule.get("min-prefix", 0) or 0
            if not isinstance(name, str) or not isinstance(pattern, str):
                continue
            if len(prefix) >= min_prefix:
                try:
                    expanded = self._expand(pattern, "pattern", rules_by_name)
                    if re.search(expanded, context, re.IGNORECASE):
                        values: list[str] = []
                        for entry in rule.get("suggestions") or []:
                            if isinstance(entry, str):
                                values.extend(self._expand(entry, "list", rules_by_name))
                        return prefix, values
                except re.error:
                    pass
            rules_by_name[name] = rule
        return "", []

    def suggestions_for(self, filename: str, line: str, cursor: int,
                         previous_lines: Optional[list[str]] = None) -> list[str]:
        """Every suggestion matching the already-typed prefix, longest-first
        duplicates removed, for a dropdown list."""
        extension = os.path.splitext(filename)[1].lower()
        prefix, candidates = self._candidates(extension, line, cursor, previous_lines or [])
        if not candidates:
            return []
        seen, results = set(), []
        lowered_prefix = prefix.lower()
        for candidate in candidates:
            if candidate.lower().startswith(lowered_prefix) and candidate.lower() != lowered_prefix and candidate not in seen:
                seen.add(candidate)
                results.append(candidate)
        return results

    def best_suffix(self, filename: str, line: str, cursor: int,
                     previous_lines: Optional[list[str]] = None) -> str:
        """The single best completion's untyped remainder, for inline ghost
        text (kept for parity with the terminal editor's Tab-to-accept)."""
        matches = self.suggestions_for(filename, line, cursor, previous_lines)
        if not matches:
            return ""
        prefix, _ = self._candidates(
            os.path.splitext(filename)[1].lower(), line, cursor, previous_lines or []
        )
        return matches[0][len(prefix):]


def default_suggestion_engine() -> SuggestionEngine:
    """The engine most GUI code should use: package config, then a local
    ./highlighting.json override, exactly like the terminal editor."""
    search_paths = []
    try:
        import chemql  # noqa: F401 -- only used to locate its directory
        package_dir = Path(chemql.__file__).resolve().parent
        search_paths.append(package_dir / "highlighting.json")
    except Exception:
        pass
    search_paths.append(Path.cwd() / "highlighting.json")
    return SuggestionEngine(search_paths)


def tokenizer_for(engine: SuggestionEngine, extension: str = ".cql") -> "Tokenizer":
    """Build a Tokenizer from an already-loaded SuggestionEngine's keyword
    rules for `extension`, so the same highlighting.json read used for
    autocomplete also drives syntax highlighting -- no second file read."""
    return Tokenizer(engine.highlight_rules_by_extension.get(_normalize_extension(extension)))


def default_tokenizer(extension: str = ".cql") -> "Tokenizer":
    """Convenience entry point for standalone use (tests, scripts): loads
    highlighting.json itself rather than sharing an existing engine. GUI
    code should prefer tokenizer_for(app.suggestion_engine) instead."""
    return tokenizer_for(default_suggestion_engine(), extension)


# --------------------------------------------------------------------------
# Diagnostics (mirrors the terminal CodecQL's lightweight .cql checks)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Diagnostic:
    line: int        # 1-based
    column: int       # 1-based
    length: int
    severity: str     # "error" | "warning"
    message: str


_BRACKET_PAIRS = {"(": ")", "[": "]", "{": "}"}
_BRACKET_CLOSERS = {")": "(", "]": "[", "}": "{"}
_DIVZERO_RE = re.compile(r"/\s*0(?:\.0*)?\b")
_WARN_RE = re.compile(r"^\s*warn\b")
_TODO_RE = re.compile(r"\b(TODO|FIXME)\b")
_LONG_LINE = 120


class DiagnosticsEngine:
    """Scans .cql source for the same issues the terminal editor flags:
    unmatched brackets/quotes (error), a literal division by zero (error),
    `warn` statements and TODO/FIXME markers (warning), and overlong lines
    (warning). Anything else the GUI adds should go here so both editors
    keep agreeing on what counts as a problem.
    """

    def scan(self, filename: str, lines: list[str]) -> list[Diagnostic]:
        if os.path.splitext(filename or "")[1].lower() != ".cql":
            return []
        found: list[Diagnostic] = []
        stack: list[tuple[str, int, int]] = []
        quote_char: Optional[str] = None
        quote_start: Optional[tuple[int, int]] = None

        for line_index, line in enumerate(lines):
            # Build a same-length "masked" line with // comments and string
            # *contents* blanked out (columns stay aligned for reporting),
            # so warn/division-by-zero only fire on real code -- not on text
            # that merely looks like it inside a comment or a string.
            masked_chars = list(line)
            in_string = False
            escape = False
            string_char = None
            comment_at = None
            for index, char in enumerate(line):
                if in_string:
                    masked_chars[index] = " "
                    if escape:
                        escape = False
                    elif char == "\\":
                        escape = True
                    elif char == string_char:
                        in_string = False
                    continue
                if char in "\"'":
                    in_string = True
                    string_char = char
                    continue
                if char == "/" and index + 1 < len(line) and line[index + 1] == "/":
                    comment_at = index
                    break
            masked = "".join(masked_chars) if comment_at is None else "".join(masked_chars[:comment_at])

            if _WARN_RE.search(masked):
                found.append(Diagnostic(line_index + 1, 1, len(line), "warning",
                                         "Explicit ChemQL warning (`warn` statement)."))
            for match in _TODO_RE.finditer(line):
                found.append(Diagnostic(line_index + 1, match.start() + 1, len(match.group()),
                                         "warning", f"{match.group()} marker left in source."))
            if len(line) > _LONG_LINE:
                found.append(Diagnostic(line_index + 1, _LONG_LINE + 1, len(line) - _LONG_LINE,
                                         "warning", f"Line exceeds {_LONG_LINE} characters."))
            division_match = _DIVZERO_RE.search(masked)
            if division_match:
                found.append(Diagnostic(line_index + 1, division_match.start() + 1,
                                         len(division_match.group()), "error",
                                         "Division by zero."))

            # bracket / quote matching, carried across lines
            escape = False
            for column, char in enumerate(line):
                if quote_char is not None:
                    if escape:
                        escape = False
                    elif char == "\\":
                        escape = True
                    elif char == quote_char:
                        quote_char = None
                        quote_start = None
                    continue
                if char in "\"'":
                    quote_char = char
                    quote_start = (line_index, column)
                elif char == "/" and column + 1 < len(line) and line[column + 1] == "/":
                    break
                elif char in _BRACKET_PAIRS:
                    stack.append((char, line_index, column))
                elif char in _BRACKET_CLOSERS:
                    if stack and stack[-1][0] == _BRACKET_CLOSERS[char]:
                        stack.pop()
                    else:
                        found.append(Diagnostic(line_index + 1, column + 1, 1, "error",
                                                 f"Unexpected '{char}' with no matching "
                                                 f"'{_BRACKET_CLOSERS[char]}'."))

        for opener, line_index, column in stack:
            found.append(Diagnostic(line_index + 1, column + 1, 1, "error",
                                     f"Unclosed {opener}: no matching "
                                     f"'{_BRACKET_PAIRS[opener]}' before end of file."))
        if quote_char is not None and quote_start is not None:
            found.append(Diagnostic(quote_start[0] + 1, quote_start[1] + 1, 1, "error",
                                     "String is never closed (unterminated string)."))
        found.sort(key=lambda d: (d.line, d.column))
        return found


# --------------------------------------------------------------------------
# GUI's own settings (kept separate from chemql's highlighting.json/
# colors.json, which the CLI editor owns and which this app must not alter)
# --------------------------------------------------------------------------

DEFAULT_LIGATURES = {
    "<->": "\u21cc", "->": "\u2192", ">=": "\u2265", "<=": "\u2264", "!=": "\u2260",
}

DARK_THEME = {
    "background": "#1e1e1e", "foreground": "#d4d4d4", "gutter": "#858585",
    "gutter_bg": "#252526", "selection": "#264f78", "current_line": "#2a2d2e",
    "comment": "#6a9955", "string": "#ce9178", "number": "#b5cea8",
    "formula": "#4fc1ff", "operator": "#d4d4d4", "delimiter": "#d4d4d4",
    "command": "#569cd6", "keyword": "#c586c0", "constant": "#569cd6",
    "source": "#4ec9b0", "condition": "#dcdcaa", "property": "#9cdcfe",
    "builtin": "#dcdcaa", "type": "#4ec9b0", "error": "#f14c4c",
    "warning": "#cca700", "ghost": "#6b6b6b", "bookmark": "#e5c07b",
}
LIGHT_THEME = {
    "background": "#ffffff", "foreground": "#1e1e1e", "gutter": "#6e7781",
    "gutter_bg": "#f6f8fa", "selection": "#add6ff", "current_line": "#f3f3f3",
    "comment": "#008000", "string": "#a31515", "number": "#098658",
    "formula": "#007acc", "operator": "#000000", "delimiter": "#000000",
    "command": "#0000ff", "keyword": "#af00db", "constant": "#0000ff",
    "source": "#267f99", "condition": "#795e26", "property": "#001080",
    "builtin": "#795e26", "type": "#267f99", "error": "#e51400",
    "warning": "#bf8803", "ghost": "#8a8a8a", "bookmark": "#c2820a",
}

_DEFAULT_SETTINGS = {
    "theme": "dark",
    "font_family": "Consolas" if sys.platform == "win32" else "Menlo" if sys.platform == "darwin" else "DejaVu Sans Mono",
    "font_size": 13,
    "show_minimap": True,
    "show_line_numbers": True,
    "ligatures_enabled": True,
    "autocomplete_enabled": True,
    "colors": {},          # per-key overrides of the active theme
    "recent_files": [],
    "recent_folders": [],
}


def settings_path() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home()) if sys.platform == "win32" else Path.home()
    return base / ".codecql_gui" / "settings.json"


class Settings:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or settings_path()
        self.data: dict[str, Any] = json.loads(json.dumps(_DEFAULT_SETTINGS))  # deep copy
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(loaded, dict):
            for key, value in loaded.items():
                if key in _DEFAULT_SETTINGS:
                    self.data[key] = value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle, indent=2, ensure_ascii=False)
        tmp.replace(self.path)

    def theme(self) -> dict:
        base = dict(DARK_THEME if self.data.get("theme") == "dark" else LIGHT_THEME)
        base.update(self.data.get("colors") or {})
        return base

    def remember_file(self, path: str, limit: int = 12) -> None:
        recents = [p for p in self.data["recent_files"] if p != path]
        recents.insert(0, path)
        self.data["recent_files"] = recents[:limit]

    def remember_folder(self, path: str, limit: int = 8) -> None:
        recents = [p for p in self.data["recent_folders"] if p != path]
        recents.insert(0, path)
        self.data["recent_folders"] = recents[:limit]


# --------------------------------------------------------------------------
# Optional chemql integration: in-process query execution, periodic-table
# data, and the equation balancer. Degrades to "unavailable" cleanly.
# --------------------------------------------------------------------------

@dataclass
class TableResult:
    columns: list[str]
    rows: list[list[str]]


@dataclass
class CardResult:
    kind: str                 # "element" | "molecule" | "reaction" | "text"
    title: str
    fields: list[tuple[str, str]]
    raw: str


class ChemQLBridge:
    """Thin wrapper around the installed `chemql` package's Python API.
    Every method returns None (never raises) if chemql isn't importable or
    the specific feature isn't available, so GUI code can just check for
    None rather than catching exceptions everywhere."""

    def __init__(self):
        try:
            import chemql
            self._chemql = chemql
        except Exception:
            self._chemql = None

    @property
    def available(self) -> bool:
        return self._chemql is not None

    def run_command_for(self, extension: str) -> Optional[str]:
        if self._chemql is None:
            return None
        package_dir = Path(self._chemql.__file__).resolve().parent
        engine = SuggestionEngine([package_dir / "highlighting.json"])
        return engine.run_commands.get(_normalize_extension(extension))

    # -- query execution --------------------------------------------------

    def run_query(self, text: str):
        """Returns (ok, payload). payload is a TableResult, CardResult, or
        a plain error string when ok is False."""
        if self._chemql is None:
            return False, "chemql is not installed in this Python environment."
        execute = getattr(self._chemql, "execute_query_text", None)
        if execute is None:
            return False, "This version of chemql has no execute_query_text()."
        try:
            result = execute(text)
        except Exception as error:  # the GUI must survive a bad query
            return False, f"{type(error).__name__}: {error}"
        return True, self._format_result(result)

    def _format_result(self, result):
        # Scalars first: int/float/bool carry public, non-callable attributes
        # of their own (e.g. int.real, int.numerator), which would otherwise
        # get misread as "fields" by the generic object-fields fallback below.
        if result is None or isinstance(result, (int, float, bool)):
            return CardResult("text", "Result", [], str(result))
        # A formatted "Error: ..." string, same convention the CLI uses.
        if isinstance(result, str):
            if result.strip().startswith("Error:"):
                return CardResult("text", "Error", [], result)
            return self._maybe_table_from_string(result) or CardResult("text", "Result", [], result)
        if hasattr(result, "columns") and hasattr(result, "rows"):
            # a row-oriented table-like object
            columns = list(getattr(result, "columns"))
            rows = [[str(cell) for cell in row] for row in getattr(result, "rows")]
            return TableResult(columns, rows)
        column_table = self._table_from_column_mapping(result)
        if column_table is not None:
            # ChemQL's ReturnTable is a dict subclass storing one list of
            # values per returned field (column-oriented), not a list of rows.
            return column_table
        if isinstance(result, list):
            if result and all(self._object_fields(item) for item in result):
                return self._table_from_objects(result)
            if result and all(isinstance(item, (str, int, float, bool)) for item in result):
                # A single-field `return` is a plain list in chemql's own
                # Python API (see execute_query_text in the README), but a
                # scrollable, sortable one-column table is a strictly nicer
                # GUI presentation than a wall of text for more than a
                # couple of values, so the GUI upgrades it here.
                return TableResult(["value"], [[str(item)] for item in result])
            return CardResult("text", "Result", [], "\n".join(str(item) for item in result))
        fields = self._object_fields(result)
        if fields:
            kind = type(result).__name__.lower()
            title = str(getattr(result, "name", None) or getattr(result, "formula", None) or kind)
            return CardResult(kind, title, [(k, str(v)) for k, v in fields], str(result))
        return CardResult("text", "Result", [], str(result))

    @staticmethod
    def _object_fields(obj) -> list[tuple[str, Any]]:
        """Public (name, value) pairs for a result object, however it's
        shaped: a plain dict, a dataclass, a namedtuple, a normal object,
        or one using __slots__ (as chemql's Element/Molecule/Reaction do,
        which means they have no __dict__ at all)."""
        if isinstance(obj, dict):
            return [(k, v) for k, v in obj.items() if not str(k).startswith("_")]
        asdict = getattr(obj, "_asdict", None)
        if callable(asdict):
            try:
                return [(k, v) for k, v in asdict().items() if not str(k).startswith("_")]
            except Exception:
                pass
        try:
            return [(k, v) for k, v in vars(obj).items() if not k.startswith("_")]
        except TypeError:
            pass
        fields = []
        for name in dir(obj):
            if name.startswith("_"):
                continue
            try:
                value = getattr(obj, name)
            except Exception:
                continue
            if callable(value):
                continue
            fields.append((name, value))
        return fields

    @staticmethod
    def _table_from_column_mapping(result) -> Optional[TableResult]:
        """Recognize a dict-like {field: [value, value, ...]} result (what
        chemql's ReturnTable actually is: a dict subclass keyed by field
        name, one same-length list of values per column) and turn it into
        row-oriented data. Returns None for anything else, including a
        dict that merely isn't shaped like a table."""
        if not isinstance(result, dict) or not result:
            return None
        columns = list(result.keys())
        values = list(result.values())
        if not all(isinstance(v, (list, tuple)) for v in values):
            return None
        lengths = {len(v) for v in values}
        if len(lengths) != 1:
            return None
        row_count = lengths.pop()
        if row_count == 0:
            return None
        rows = [[str(values[col][row]) for col in range(len(columns))] for row in range(row_count)]
        return TableResult(columns, rows)

    @classmethod
    def _table_from_objects(cls, items) -> TableResult:
        columns: list[str] = []
        rows_as_dicts = []
        for item in items:
            fields = dict(cls._object_fields(item))
            rows_as_dicts.append(fields)
            for key in fields:
                if key not in columns:
                    columns.append(key)
        rows = [[str(row.get(column, "")) for column in columns] for row in rows_as_dicts]
        return TableResult(columns, rows)

    @staticmethod
    def _maybe_table_from_string(text: str) -> Optional[TableResult]:
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            return None
        return None  # plain strings render as text; structured results use the object path above

    # -- periodic table -----------------------------------------------------

    def elements(self) -> Optional[list[dict]]:
        if self._chemql is None:
            return None
        elements = getattr(self._chemql, "ELEMENTS", None)
        if elements is None:
            return None
        result = []
        for element in elements:
            get = (lambda key, default=None: getattr(element, key, element.get(key, default) if isinstance(element, dict) else default))
            result.append({
                "symbol": get("symbol", "?"), "name": get("name", "?"),
                "number": get("number", 0), "period": get("period", 0),
                "group": get("group", 0) or 0, "category": get("category", "") or "",
                "atomic_mass": get("atomic_mass", None),
            })
        return result

    # -- equation balancing ---------------------------------------------

    def balance(self, reactants_text: str, products_text: str):
        """Returns (ok, message)."""
        if self._chemql is None:
            return False, "chemql is not installed in this Python environment."
        balance_fn = getattr(self._chemql, "balance_stoichiometry", None)
        if balance_fn is None:
            return False, "This version of chemql has no balance_stoichiometry()."
        try:
            reaction = balance_fn(reactants_text, products_text)
        except ValueError as error:
            return False, str(error)
        except Exception as error:
            return False, f"{type(error).__name__}: {error}"
        return True, str(reaction)


# --------------------------------------------------------------------------
# Running a file as a subprocess, streaming output (GUI layer owns the
# threading; this just builds the command safely).
# --------------------------------------------------------------------------

def build_run_command(run_command_template: str, absolute_path: str) -> list[str]:
    """Expand $absoluteName the same way the terminal editor does, but
    return an argv list (no shell) so quoting is never a concern."""
    import shlex
    quoted = shlex.quote(absolute_path)
    expanded = run_command_template.replace("$absoluteName", quoted)
    return shlex.split(expanded, posix=(os.name != "nt"))