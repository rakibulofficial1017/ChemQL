import os
import re
import json
import argparse
import keyword
import builtins
import signal
import sys
import shutil
import subprocess
import time
from .highlighting import HighlightProfiles

VERSION = "0.1.0"


def _write_system_clipboard(text):
    """Copy text to the host system clipboard when a clipboard command exists."""
    commands = []
    if os.name == "nt":
        commands = [["clip"]]
    elif "WSL_DISTRO_NAME" in os.environ:
        commands = [["clip.exe"]]
    elif sys.platform == "darwin":
        commands = [["pbcopy"]]
    else:
        commands = [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]

    for command in commands:
        if shutil.which(command[0]):
            subprocess.run(
                command, input=text, text=True, encoding="utf-8",
                check=True, timeout=3,
            )
            return True
    return False


def _decode_escape_sequence(sequence):
    """Translate a terminal escape sequence into an editor key name."""
    if sequence.startswith(b"["):
        body = sequence[1:]
        final = body[-1:] if body else b""
        if not final or final[0] not in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz~":
            return "\x1b"
        params = body[:-1].decode("ascii", errors="ignore").split(";")
        try:
            modifier = int(params[1]) if len(params) > 1 else 1
        except ValueError:
            modifier = 1
        modifier_bits = max(0, modifier - 1)
        modifiers = []
        if modifier_bits & 4:
            modifiers.append("ctrl")
        if modifier_bits & 2:
            modifiers.append("alt")
        if modifier_bits & 1:
            modifiers.append("shift")

        arrow_keys = {
            b"A": "arrow_up", b"B": "arrow_down",
            b"C": "arrow_right", b"D": "arrow_left",
            b"H": "arrow_home", b"F": "arrow_end",
        }
        key = arrow_keys.get(bytes(final))
        if key:
            return "+".join((*modifiers, key)) if modifiers else key
        if final == b"~" and params:
            key_code = params[0]
            if key_code in {"1", "7"}:
                key = "arrow_home"
            elif key_code in {"4", "8"}:
                key = "arrow_end"
            elif key_code == "2":
                key = "insert"
            elif key_code == "3":
                key = "delete"
            elif key_code == "5":
                key = "page_up"
            elif key_code == "6":
                key = "page_down"
            elif key_code == "27" and len(params) > 2 and params[2] == "127":
                key = "backspace"
            else:
                return "\x1b"
            return "+".join((*modifiers, key)) if modifiers else key
        if final == b"u" and params and params[0] in {"8", "127"}:
            # CSI-u / Kitty keyboard protocol can encode Backspace as 8 or 127.
            key = "backspace"
            return "+".join((*modifiers, key)) if modifiers else key
    elif sequence.startswith(b"O") and sequence[-1:] in b"ABCDHF":
        return {
            b"A": "arrow_up", b"B": "arrow_down",
            b"C": "arrow_right", b"D": "arrow_left",
            b"H": "arrow_home", b"F": "arrow_end",
        }[sequence[-1:]]
    return "\x1b"


def _parse_search_query(query):
    flags = ""
    pattern = query
    if ":" in query:
        prefix, remainder = query.split(":", 1)
        if prefix and all(flag in "rlwi" for flag in prefix):
            if "r" in prefix and "l" in prefix:
                raise ValueError("Use either `r` or `l`, not both")
            flags = prefix
            pattern = remainder

    expression = pattern if "r" in flags else re.escape(pattern)
    if "w" in flags:
        expression = rf"(?<!\w)(?:{expression})(?!\w)"
    ignore_case = "i" in flags or not flags
    return re.compile(expression, re.IGNORECASE if ignore_case else 0)


# Cross-platform terminal setup for ANSI Processing
if os.name == 'nt':
    try:
        import colorama
        colorama.init()
    except ImportError:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # Enable virtual terminal processing flags (ENABLE_PROCESSED_OUTPUT, ENABLE_WRAP_AT_EOL_OUTPUT, ENABLE_VIRTUAL_TERMINAL_PROCESSING)
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-10), 1) # Enable echo input / window input flags if needed, or minimal raw setup

# Cross-platform raw keystroke capture
if os.name == 'nt':
    import msvcrt

    WINDOWS_KEYS = {
        0x48: "arrow_up", 0x50: "arrow_down",
        0x4B: "arrow_left", 0x4D: "arrow_right",
        0x47: "arrow_home", 0x4F: "arrow_end",
        0x49: "page_up", 0x51: "page_down",
        0x53: "delete", 0x93: "ctrl+delete", 0x73: "ctrl+arrow_left",
        0x74: "ctrl+arrow_right", 0x8D: "ctrl+arrow_up",
        0x91: "ctrl+arrow_down", 0x9B: "alt+arrow_left",
        0x9D: "alt+arrow_right",
    }

    def get_key():
        ch = msvcrt.getch()
        if ch in (b'\x00', b'\xe0'): # Arrow key prefixes on Windows
            ch2 = msvcrt.getch()
            return WINDOWS_KEYS.get(ch2[0], f"arrow_{ch2.hex()}")
        return ch.decode('utf-8', errors='ignore')
else:
    import fcntl
    import pty
    import struct
    import tty
    import termios
    import select

    def _read_bracketed_paste(fd):
        end_marker = b"\x1b[201~"
        pasted = bytearray()
        while True:
            char = os.read(fd, 1)
            if not char:
                break
            pasted.extend(char)
            if pasted.endswith(end_marker):
                del pasted[-len(end_marker):]
                break
        return "paste:" + pasted.decode("utf-8", errors="replace")

    def get_key():
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            first = os.read(fd, 1)
            if first == b"\x1b":
                sequence = bytearray()
                while select.select([fd], [], [], 0.05)[0]:
                    sequence.extend(os.read(fd, 1))
                    final = bytes(sequence[-1:])
                    if len(sequence) > 1 and 0x40 <= sequence[-1] <= 0x7e:
                        break
                if sequence.startswith(b"[200~"):
                    return _read_bracketed_paste(fd)
                if sequence.startswith(b"["):
                    return _decode_escape_sequence(sequence)
                if sequence.startswith(b"O"):
                    return _decode_escape_sequence(sequence)
                if sequence in (b"\x7f", b"\x08"):
                    return "alt+backspace"
                if sequence:
                    # ESC + one printable character is commonly Alt+<key>.
                    # Never insert an unknown multi-character escape sequence.
                    if len(sequence) == 1:
                        char = sequence.decode("utf-8", errors="replace")
                        if char.isprintable():
                            return "alt+" + char
                    return "\x1b"
                return "\x1b"
            if not first:
                return ""
            char_length = (
                1 if first[0] < 0x80 else
                2 if first[0] < 0xe0 else
                3 if first[0] < 0xf0 else 4
            )
            char_bytes = bytearray(first)
            while len(char_bytes) < char_length and select.select([fd], [], [], 0.05)[0]:
                char_bytes.extend(os.read(fd, 1))
            return char_bytes.decode("utf-8", errors="replace")
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

# ANSI styling uses a muted, high-contrast palette that works in common terminals.
RESET = "\x1b[0m"
DIM = "\x1b[2m"


def load_color_styles():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "colors.json")
    try:
        with open(config_path, encoding="utf-8") as config_file:
            config = json.load(config_file)
    except FileNotFoundError:
        # Keep informational flags such as --version usable without the theme
        # file. The editor still gets a readable built-in ANSI palette.
        syntax_colors = {
            "comment": 244, "string": 114, "number": 179,
            "formula": 117, "operator": 213, "delimiter": 250,
            "command": 81, "keyword": 141, "constant": 215,
            "type": 150, "source": 110, "condition": 180,
            "property": 116, "builtin": 222,
        }
        ui_colors = {"line_numbers": 244, "status_background": 24,
                     "status_foreground": 255}
        config = {
            "syntax": {key: {"ansi256": value} for key, value in syntax_colors.items()},
            "ui": {
                "line_numbers": {"ansi256": ui_colors["line_numbers"]},
                "status_background": {"ansi256": ui_colors["status_background"], "channel": "background"},
                "status_foreground": {"ansi256": ui_colors["status_foreground"]},
            },
        }
    groups = {}
    for group_name in ("syntax", "ui"):
        colors = config.get(group_name)
        if not isinstance(colors, dict):
            raise ValueError(f"Expected a '{group_name}' object in {config_path}")
        styles = {}
        for category, details in colors.items():
            if not isinstance(details, dict):
                raise ValueError(f"Color definition for '{category}' must be an object")
            color = details.get("ansi256")
            channel = details.get("channel", "foreground")
            if not isinstance(color, int) or isinstance(color, bool) or not 0 <= color <= 255:
                raise ValueError(f"Color definition for '{category}' needs an ANSI 256 color number")
            if channel not in {"foreground", "background"}:
                raise ValueError(f"Color definition for '{category}' has an invalid channel")
            ansi_channel = 38 if channel == "foreground" else 48
            styles[category] = f"\x1b[{ansi_channel};5;{color}m"
        groups[group_name] = styles
    return groups


COLOR_STYLES = load_color_styles()
HIGHLIGHT_STYLES = COLOR_STYLES["syntax"]
UI_STYLES = COLOR_STYLES["ui"]
MUTED = UI_STYLES["line_numbers"]
STATUS_BG = UI_STYLES["status_background"]
STATUS_FG = UI_STYLES["status_foreground"]

COMMANDS = {
    "search", "source", "list", "clear", "return", "exit", "findel",
    "findmol", "findre", "set", "add", "remove", "react", "balance",
    "conditions", "view", "help", "dump", "version", "let", "unset",
    "variables", "func", "define", "load", "import", "signal", "fix",
    "cleanup", "arguments"
}
CONTROL_KEYWORDS = {
    "if", "elif", "else", "endif", "for", "while", "in", "endfor",
    "endwhile", "break", "continue", "skip", "endblock", "from", "as", "public",
    "private", "required", "struct", "record", "enum", "endstruct", "static",
    "endrecord", "endenum", "namespace", "endnamespace",
}
WORD_OPERATORS = {
    "and", "or", "has", "like", "like!", "likep", "sort", "limit",
    "count", "first", "last", "asc", "desc", "union", "intersection",
}
SOURCES = {"elements", "molecules", "reactions"}
CONDITIONS = {
    "temperature", "pressure", "catalyst", "catalysts", "standard",
    "room", "c", "f", "k", "pa", "kpa", "mpa", "hpa", "bar",
    "atm", "torr", "mmhg", "psi",
}
PROPERTIES = set("""
name appearance atomic_mass boil category density discovered_by melt
molar_heat named_by number period group phase source bohr_model_image
bohr_model_3d spectral_img summary symbol xpos ypos wxpos wypos shells
electron_configuration electron_configuration_semantic electron_affinity
electronegativity_pauling ionization_energies cpk_hex cpk-hex image block
formula elements molecular_weight iupac_name smiles cid melting_point
boiling_point state bonds total_bond_energy id equation reaction_type
reversible reactants products conditions notes
""".split())
PYTHON_BUILTINS = set(dir(builtins))
TOKEN_RE = re.compile(
    r"""(?P<comment>//.*$|#.*$)"""
    r"""|(?P<string>'''(?:\\.|[^\\])*?'''|\"\"\"(?:\\.|[^\\])*?\"\"\"|"""
    r"""'(?:\\.|[^'\\])*'?|"(?:\\.|[^"\\])*"?)"""
    r"""|(?P<formula>(?<![A-Za-z0-9_])(?-i:(?:[A-Z][a-z]?\d*)+)(?![A-Za-z0-9_]))"""
    r"""|(?P<number>(?<![\w.])[+-]?(?:\d+(?:\.\d*)?|\.\d+)"""
    r"""\s*(?:°\s*[cfk]|nm\^-?2|n/m\^?2|pa|kpa|mpa|hpa|bar|atm|torr|mmhg|psi|[cfk])?(?!\w))"""
    r"""|(?P<identifier>[A-Za-z_]\w*!?)"""
    r"""|(?P<operator><->|->|!=|==|>=|<=|:=|[-+*/%=<>])"""
    r"""|(?P<delimiter>\{\{|\}\}|\[\[\[|\]\]\]|\{|\}|\[|\]|\(|\)|,|:|\.|;|\\|\?)""",
    re.IGNORECASE,
)
AUTO_INDENT = re.compile(
    r"^\s*(?:(?:func|define)\b.*(?:\{\}|\{)$|"
    r"(?:struct|record|enum)\s+\w+(?:\s+from\b.*)?$|"
    r"namespace\s+[A-Za-z_]\w*$|"
    r"(?:if|elif|else|for|while)\b.*|.*\\)$",
    re.IGNORECASE,
)


def _token_style(kind, value, profiles=None, filename=None):
    extension = os.path.splitext(filename or "")[1].casefold()
    is_chemql = extension == ".cql"
    is_python = extension == ".py"

    # These lexical categories are shared by all file types.
    if kind == "comment":
        return HIGHLIGHT_STYLES["comment"]
    if kind == "string":
        return HIGHLIGHT_STYLES["string"]
    if kind == "number":
        return HIGHLIGHT_STYLES["number"]
    if kind == "formula" and is_chemql and (
        any(char.isdigit() for char in value)
        or len(re.findall(r"[A-Z]", value)) > 1
    ):
        return HIGHLIGHT_STYLES["formula"]
    if kind == "operator":
        return HIGHLIGHT_STYLES["operator"]
    if kind == "delimiter":
        if value == "?" and is_chemql:
            return HIGHLIGHT_STYLES["command"]
        return HIGHLIGHT_STYLES["delimiter"]

    if kind != "identifier":
        return ""

    word = value.casefold()

    # User-defined profiles remain extension-specific and can add highlighting
    # for languages other than ChemQL.
    if profiles and filename:
        configured_style = profiles.get_keyword_style(filename, word)
        if configured_style:
            return parse_highlight_style(configured_style)

    if is_chemql:
        if word in {"true", "false", "none"}:
            category = "constant"
        elif word in {"enum", "struct", "record"}:
            category = "type"
        elif word in COMMANDS or word == "?":
            category = "command"
        elif word in CONTROL_KEYWORDS:
            category = "keyword"
        elif word in WORD_OPERATORS:
            category = "operator"
        elif word in SOURCES:
            category = "source"
        elif word in CONDITIONS:
            category = "condition"
        elif word in PROPERTIES:
            category = "property"
        elif word in PYTHON_BUILTINS:
            category = "builtin"
        else:
            return ""
        return HIGHLIGHT_STYLES[category]

    # Python files get Python's own keywords and built-ins, never ChemQL's.
    if is_python:
        if value in {"True", "False", "None"}:
            return HIGHLIGHT_STYLES["constant"]
        if keyword.iskeyword(value):
            return HIGHLIGHT_STYLES["keyword"]
        if value in PYTHON_BUILTINS:
            return HIGHLIGHT_STYLES["builtin"]

    # Plain-text and unknown extensions receive lexical styling only.
    return ""


MANIFEST_TOKEN_RE = re.compile(
    r"(?P<comment>#.*$)"
    r"|(?P<string>'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")"
    r"|(?P<number>(?<![\w.])[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?!\w))"
    r"|(?P<literal>\b(?:true|false|null)\b)"
    r"|(?P<identifier>[A-Za-z_][A-Za-z0-9_-]*)"
    r"|(?P<operator>=)"
    r"|(?P<delimiter>[\[\]{}:,.])",
    re.IGNORECASE,
)
def load_highlighting_profiles():
    profiles = HighlightProfiles()

    main_config = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "highlighting.json",
    )

    local_config = os.path.join(
        os.getcwd(),
        "highlighting.json",
    )

    loaded_paths = set()

    for path in (main_config, local_config):
        path = os.path.abspath(path)

        # Avoid loading the same file twice.
        if path in loaded_paths:
            continue

        loaded_paths.add(path)

        if os.path.isfile(path):
            profiles.load(path)

    return profiles

def _apply_manifest_syntax_highlighting(text, filename):
    """Highlight JSON/TOML package manifests with the editor's existing theme."""
    is_json = os.path.basename(filename).casefold() == "cqlpackage.json"
    is_toml = os.path.basename(filename).casefold() == "cqlpackage.toml"
    if not (is_json or is_toml):
        return None

    # TOML table headers are clearer when highlighted as a unit.
    stripped = text.lstrip()
    if is_toml and stripped.startswith("[") and stripped.endswith("]"):
        leading = text[:len(text) - len(stripped)]
        return leading + HIGHLIGHT_STYLES["type"] + stripped + RESET

    parts = []
    last_end = 0
    for match in MANIFEST_TOKEN_RE.finditer(text):
        parts.append(text[last_end:match.start()])
        token = match.group()
        kind = match.lastgroup
        tail = text[match.end():]
        style = ""

        if kind == "comment" and is_toml:
            style = HIGHLIGHT_STYLES["comment"]
        elif kind == "string":
            next_nonspace = tail.lstrip()[:1]
            if (is_json and next_nonspace == ":") or (is_toml and next_nonspace == "="):
                style = HIGHLIGHT_STYLES["property"]
            else:
                style = HIGHLIGHT_STYLES["string"]
        elif kind == "number":
            style = HIGHLIGHT_STYLES["number"]
        elif kind == "literal":
            # JSON literals are lowercase; TOML booleans are lowercase too.
            style = HIGHLIGHT_STYLES["constant"]
        elif kind == "identifier" and is_toml:
            if tail.lstrip().startswith("="):
                style = HIGHLIGHT_STYLES["property"]
            elif token.casefold() in {"true", "false", "inf", "nan"}:
                style = HIGHLIGHT_STYLES["constant"]
        elif kind == "operator":
            style = HIGHLIGHT_STYLES["operator"]
        elif kind == "delimiter" and token.strip():
            style = HIGHLIGHT_STYLES["delimiter"]

        if style:
            parts.extend((style, token, RESET))
        else:
            parts.append(token)
        last_end = match.end()
    parts.append(text[last_end:])
    return "".join(parts)

def parse_highlight_style(style):
    parts = style.split()
    codes = []

    named_styles = {
        "keyword": HIGHLIGHT_STYLES["keyword"],
        "command": HIGHLIGHT_STYLES["command"],
        "operator": HIGHLIGHT_STYLES["operator"],
        "string": HIGHLIGHT_STYLES["string"],
        "comment": HIGHLIGHT_STYLES["comment"],
        "number": HIGHLIGHT_STYLES["number"],
        "constant": HIGHLIGHT_STYLES["constant"],
        "type": HIGHLIGHT_STYLES["type"],
        "source": HIGHLIGHT_STYLES["source"],
        "condition": HIGHLIGHT_STYLES["condition"],
        "property": HIGHLIGHT_STYLES["property"],
        "builtin": HIGHLIGHT_STYLES["builtin"],
    }

    formatting = {
        "bold": "1",
        "dim": "2",
        "italic": "3",
        "underline": "4",
        "reverse": "7",
        "strike": "9",
    }

    for part in parts:
        part = part.casefold()

        if part in named_styles:
            # Existing theme styles are already ANSI escape sequences.
            codes.append(named_styles[part])

        elif part in formatting:
            codes.append(f"\033[{formatting[part]}m")

        elif re.fullmatch(r"#[0-9a-f]{6}", part):
            r, g, b = (
                int(part[i:i + 2], 16)
                for i in (1, 3, 5)
            )
            codes.append(f"\033[38;2;{r};{g};{b}m")

        elif part.startswith("bg:#") and re.fullmatch(
            r"bg:#[0-9a-f]{6}", part
        ):
            color = part[3:]
            r, g, b = (
                int(color[i:i + 2], 16)
                for i in (1, 3, 5)
            )
            codes.append(f"\033[48;2;{r};{g};{b}m")

        else:
            raise ValueError(f"Unknown highlight style component: {part}")

    return "".join(codes)


def apply_syntax_highlighting(text, filename=None, profiles=None):
    if filename:
        manifest_highlighting = _apply_manifest_syntax_highlighting(text, filename)
        if manifest_highlighting is not None:
            return manifest_highlighting
    parts = []
    last_end = 0
    for match in TOKEN_RE.finditer(text):
        parts.append(text[last_end:match.start()])
        kind = match.lastgroup
        token = match.group()
        style = _token_style(kind, token, profiles, filename) if kind else ""
        if kind == "identifier" and os.path.splitext(filename or "")[1].casefold() == ".cql":
            prefix = text[:match.start()]
            if re.search(r"\b(?:enum|struct|record|namespace)\s+$", prefix, re.IGNORECASE):
                style = HIGHLIGHT_STYLES["type"]
            elif re.search(r"\bfunc\s+$", prefix, re.IGNORECASE):
                style = HIGHLIGHT_STYLES["builtin"]
        if style:
            parts.extend((style, token, RESET))
        else:
            parts.append(token)
        last_end = match.end()
    parts.append(text[last_end:])
    return "".join(parts)

class Editor:
    HISTORY_LIMIT = 200

    def __init__(self, filename):
        self.filename = filename
        self.lines = [""]
        self.cursor_x = 0
        self.cursor_y = 0
        self.selection_anchor = None
        self.clipboard = ""
        self.search_active = False
        self.search_query = ""
        self.search_regex = None
        self.search_error = ""
        self.search_matches = []
        self.current_search_match = None
        self.scroll_x = 0
        self.scroll_y = 0
        self.dirty = False
        self.quit_requested = False
        self.message = f"Opened {filename}" if filename else "New file"
        self.undo_stack = []
        self.redo_stack = []
        self.diagnostic_panel = None
        self._tab_states = None
        self._active_tab = 0

        if filename and os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read().splitlines()
                self.lines = content if content else [""]
        self.saved_lines = tuple(self.lines)
        self.highlight_profiles = load_highlighting_profiles()
        self._tab_states = [self._capture_tab_state()]

    _TAB_STATE_EXCLUDE = {"_tab_states", "_active_tab"}

    def _capture_tab_state(self):
        return {key: value for key, value in self.__dict__.items()
                if key not in self._TAB_STATE_EXCLUDE}

    def _store_active_tab(self):
        self._tab_states[self._active_tab] = self._capture_tab_state()

    def _switch_tab(self, index):
        self._store_active_tab()
        self._active_tab = index % len(self._tab_states)
        manager = self._tab_states
        active = self._tab_states[self._active_tab]
        self.__dict__.update(active)
        self._tab_states = manager
        self.message = f"Tab {self._active_tab + 1}/{len(manager)}"

    def _new_tab(self):
        self._store_active_tab()
        state = self._capture_tab_state()
        state.update({
            "filename": None, "lines": [""], "cursor_x": 0, "cursor_y": 0,
            "selection_anchor": None, "search_active": False, "search_query": "",
            "search_regex": None, "search_error": "", "search_matches": [],
            "current_search_match": None, "scroll_x": 0, "scroll_y": 0,
            "dirty": False, "quit_requested": False, "message": "New tab",
            "undo_stack": [], "redo_stack": [], "saved_lines": ("",),
            "diagnostic_panel": None,
        })
        self._tab_states.append(state)
        self._active_tab = len(self._tab_states) - 1
        self.__dict__.update(state)
        self.message = f"New tab · {self._active_tab + 1}/{len(self._tab_states)}"

    def _open_tab(self):
        self._new_tab()
        try:
            path = input("Open file in new tab: ").strip()
        except (EOFError, KeyboardInterrupt):
            path = ""
        if not path:
            self.message = "Open cancelled · blank tab created"
            return
        try:
            with open(path, "r", encoding="utf-8") as stream:
                content = stream.read().splitlines()
        except (OSError, UnicodeError) as error:
            self.message = f"Could not open {path}: {error}"
            return
        self.filename = path
        self.lines = content or [""]
        self.cursor_x = self.cursor_y = 0
        self.saved_lines = tuple(self.lines)
        self.dirty = False
        self.message = f"Opened {path}"

    def _diagnostics(self, kind):
        """Return lightweight, line-aware editor diagnostics."""
        found = []
        pairs = {"(": ")", "[": "]", "{": "}"}
        stack = []
        quote = None
        escaped = False

        for number, line in enumerate(self.lines, 1):
            if kind == "warning":
                if re.search(r"\b(?:TODO|FIXME|XXX)\b", line, re.I):
                    found.append((number, "Warning", "TODO/FIXME marker"))
                if re.match(r"^\s*warn\s+", line, re.I):
                    found.append((number, "Warning", "Explicit ChemQL warning"))
                if len(line) > 120:
                    found.append((number, "Warning", "Line exceeds 120 characters"))
            elif re.search(r"(?<![\w.])\d+(?:\.\d+)?\s*/\s*0(?:\.0+)?(?![\w.])", line):
                found.append((number, "Error", "Division by zero"))

            # Scan delimiters while ignoring quoted strings and comments.
            for column, char in enumerate(line):
                if quote:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == quote:
                        quote = None
                    continue
                if char in ("'", '"'):
                    quote = char
                elif char in "#" or line[column:column + 2] == "//":
                    break
                elif kind == "error" and char in pairs:
                    stack.append((char, number, column))
                elif kind == "error" and char in pairs.values():
                    if not stack or pairs[stack[-1][0]] != char:
                        found.append((number, "Error", f"Unmatched {char}"))
                    else:
                        stack.pop()

            if kind == "error" and quote:
                # Only report an unclosed quote at the end of a line; escaped
                # quote handling above prevents false positives for normal strings.
                if not escaped:
                    found.append((number, "Error", "Possibly unterminated string"))
                quote = None
                escaped = False

        if kind == "error":
            for opener, number, _column in stack:
                found.append((number, "Error", f"Unclosed {opener}"))
        return found

    def run(self):
        sys.stdout.write("\x1b[?1049h\x1b[?2004h")
        sys.stdout.flush()
        try:
            while True:
                self._store_active_tab()
                self.draw_screen()
                key = get_key()
                if self.handle_key(key):
                    break
        finally:
            if os.name != "nt":
                sys.stdout.write("\x1b[?6l\x1b[r")
            sys.stdout.write("\x1b[?2004l\x1b[?1049l")
            sys.stdout.flush()

    def draw_screen(self, terminal_height=0):
        try:
            cols, rows = os.get_terminal_size()
        except OSError:
            cols, rows = 80, 24
        cols = max(cols, 20)
        rows = max(rows, 4)
        gutter_width = len(str(max(len(self.lines), self.cursor_y + 1))) + 2
        panel_items = self._diagnostics(self.diagnostic_panel) if self.diagnostic_panel else []
        panel_height = min(5, len(panel_items) + 1) if self.diagnostic_panel else 0
        terminal_height = min(max(0, terminal_height), rows - 2 - panel_height)
        viewport_height = rows - terminal_height - panel_height - 2
        viewport_width = max(1, cols - gutter_width)
        visual_cursor_x = len(self.lines[self.cursor_y][:self.cursor_x].expandtabs(4))
        self._keep_cursor_visible(viewport_height, viewport_width, visual_cursor_x)

        output = ["\x1b[H"]
        for screen_y in range(viewport_height):
            line_y = self.scroll_y + screen_y
            if line_y < len(self.lines):
                line_number = f"{line_y + 1:>{gutter_width - 2}} "
                visible_text = self.lines[line_y].expandtabs(4)[
                    self.scroll_x:self.scroll_x + viewport_width
                ]
                ghost = ""
                if line_y == self.cursor_y and self.cursor_x == len(self.lines[line_y]):
                    suffix = self._get_suggestion_suffix()
                    ghost_column = visual_cursor_x - self.scroll_x
                    available = max(0, viewport_width - ghost_column)
                    if suffix and available:
                        ghost = "\x1b[90m" + suffix[:available] + RESET
                output.extend((
                    DIM, MUTED, line_number, RESET,
                    self._highlight_line(visible_text, line_y), ghost, "\x1b[K\r\n",
                ))
            else:
                output.extend((DIM, MUTED, " " * (gutter_width - 1), "~", RESET, "\x1b[K\r\n"))

        tab_count = len(self._tab_states or [None])
        title = f" CodecQL [{self._active_tab + 1}/{tab_count}]  {os.path.basename(self.filename) if self.filename else 'untitled'}"
        status = f"Ln {self.cursor_y + 1}, Col {self.cursor_x + 1}  |  {len(self.lines)} lines"
        if self.dirty:
            status += "  |  Unsaved"
        if self.search_active:
            status += f"  |  {self.search_error or f'{len(self.search_matches)} match(es)'}"
        status_text = f"{title:<{max(0, cols - len(status))}}{status}"
        output.extend((STATUS_BG, STATUS_FG, status_text[:cols].ljust(cols), RESET, "\r\n"))
        footer = (
            f"Search: {self.search_query}"
            if self.search_active
            else self.message or (
                "Ctrl+S Save  Ctrl+Z Undo  Ctrl+Y Redo  Ctrl+Q Quit  "
                "Ctrl+F Search  Ctrl+W Warnings  Ctrl+E Errors  Ctrl+N New  Ctrl+O Open  Ctrl+L/P Switch Tabs"
            )
        )
        output.extend((DIM, footer[:cols].ljust(cols), RESET))
        if self.diagnostic_panel:
            heading = " Warnings " if self.diagnostic_panel == "warning" else " Errors "
            output.extend((STATUS_BG, STATUS_FG, heading.ljust(cols), RESET, "\r\n"))
            for number, level, message in panel_items[:max(0, panel_height - 1)]:
                line = f" {level} · line {number}: {message}"[:cols].ljust(cols)
                # Diagnostics are listed here without underlining; the actual
                # source line is underlined in the editor viewport.
                color = "\x1b[33m" if level == "Warning" else "\x1b[31;1m"
                output.extend((color, line, RESET, "\r\n"))
        if self.search_active:
            cursor_row = rows
            cursor_col = min(cols, len("Search: ") + len(self.search_query) + 1)
        else:
            cursor_row = self.cursor_y - self.scroll_y + 1
            cursor_col = gutter_width + visual_cursor_x - self.scroll_x
        output.append(f"\x1b[{cursor_row};{cursor_col}H")

        sys.stdout.write("".join(output))
        sys.stdout.flush()

    def _highlight_line(self, visible_text, line_y):
        line_start = self._position_to_offset(0, line_y)
        line_end = line_start + len(self.lines[line_y])
        raw_text = self.lines[line_y].expandtabs(4)[self.scroll_x:self.scroll_x + len(visible_text)]
        overlays = []
        selection = self._selection_offsets()
        if selection is not None:
            start, end = max(selection[0], line_start), min(selection[1], line_end)
            if start < end:
                overlays.append((start, end, "\x1b[7m", 2))
        for match_start, match_end in self.search_matches:
            start, end = max(match_start, line_start), min(match_end, line_end)
            if start < end:
                current = (match_start, match_end) == self.current_search_match
                overlays.append((start, end, "\x1b[7m" if current else "\x1b[43m", 1))
        if not overlays:
            rendered = apply_syntax_highlighting(visible_text, self.filename, self.highlight_profiles)
            return self._apply_diagnostic_underline(rendered, line_y)

        boundaries = {line_start, line_end}
        for start, end, _, _ in overlays:
            boundaries.update((start, end))
        ordered = sorted(boundaries)
        visual_start = self.scroll_x
        visual_end = visual_start + len(raw_text)
        parts = []
        for start, end in zip(ordered, ordered[1:]):
            text_start = len(self.lines[line_y][:start - line_start].expandtabs(4))
            text_end = len(self.lines[line_y][:end - line_start].expandtabs(4))
            visible_left = max(text_start, visual_start)
            visible_right = min(text_end, visual_end)
            if visible_left >= visible_right:
                continue
            segment = raw_text[visible_left - visual_start:visible_right - visual_start]
            active = [
                overlay for overlay in overlays
                if overlay[0] <= start and end <= overlay[1]
            ]
            if active:
                style = max(active, key=lambda overlay: overlay[3])[2]
                parts.extend((style, segment, RESET))
            else:
                parts.append(
    apply_syntax_highlighting(
        segment, self.filename, self.highlight_profiles
    )
)
        return self._apply_diagnostic_underline("".join(parts), line_y)

    def _apply_diagnostic_underline(self, rendered, line_y):
        """Underline source lines that contain editor diagnostics."""
        line_number = line_y + 1
        error_lines = {item[0] for item in self._diagnostics("error")}
        warning_lines = {item[0] for item in self._diagnostics("warning")}

        # Errors take precedence if a line has both diagnostics. SGR 4:3 is
        # the standardized wavy underline; SGR 58 sets its colour independently
        # of the syntax-highlighted foreground colour.
        if line_number in error_lines:
            underline = "\x1b[4:3;58:2::255:64:64m"  # red wavy underline
        elif line_number in warning_lines:
            underline = "\x1b[4:3;58:2::255:210:0m"  # yellow wavy underline
        else:
            return rendered

        # Syntax highlighting emits SGR resets between tokens. Reapply the
        # underline after each reset so it remains active across the whole line.
        return underline + rendered.replace(RESET, RESET + underline) + RESET

    def _get_suggestion_suffix(self):
        """Return the untyped part of the current inline suggestion, if any."""
        if self.selection_anchor is not None and self._selection_offsets() is not None:
            return ""
        if self.cursor_y >= len(self.lines):
            return ""
        line = self.lines[self.cursor_y]
        if self.cursor_x != len(line):
            return ""
        try:
            return self.highlight_profiles.get_suggestion_suffix(
                self.filename or "", line, self.cursor_x,
                previous_lines=self.lines[:self.cursor_y],
            )
        except (AttributeError, re.error):
            return ""

    def _keep_cursor_visible(self, height, width, visual_cursor_x):
        if self.cursor_y < self.scroll_y:
            self.scroll_y = self.cursor_y
        elif self.cursor_y >= self.scroll_y + height:
            self.scroll_y = self.cursor_y - height + 1
        if visual_cursor_x < self.scroll_x:
            self.scroll_x = visual_cursor_x
        elif visual_cursor_x >= self.scroll_x + width:
            self.scroll_x = visual_cursor_x - width + 1

    def handle_key(self, key):
        if self.search_active:
            return self._handle_search_key(key)
        if key in ("\x17", "ctrl+w"):
            self.diagnostic_panel = "warning"
            self.message = "Warnings · Esc closes this panel"
            return False
        if key in ("\x05", "ctrl+e"):
            self.diagnostic_panel = "error"
            self.message = "Errors · Esc closes this panel"
            return False
        if self.diagnostic_panel and key in ("\x1b", "escape"):
            self.diagnostic_panel = None
            self.message = "Diagnostics closed"
            return False
        if key in ("ctrl+n", "\x0e"):
            self._new_tab()
            return False
        if key in ("ctrl+o", "\x0f"):
            self._open_tab()
            return False
        if key in ("ctrl+tab", "ctrl+page_down", "\x0c", "ctrl+l"):
            self._switch_tab(self._active_tab + 1)
            return False
        if key in ("ctrl+shift+tab", "ctrl+page_up", "\x10", "ctrl+p"):
            self._switch_tab(self._active_tab - 1)
            return False
        if key in ("\x14", "ctrl+t"):
            self._run_split_terminal()
            return False
        if key in ("\x12", "ctrl+r"):
            self._run_split_terminal(run_chemql=True)
            return False
        if key in ("\x06", "ctrl+f"):
            self._open_search()
            return False
        if key.startswith("paste:"):
            self._insert_text(key[6:])
            self.message = ""
            self.quit_requested = False
            return False
        if key == "\x13":
            self.save_file()
            return False
        if key == "\x11":
            if self.dirty and not self.quit_requested:
                self.message = "Unsaved changes. Press Ctrl+Q again to quit without saving."
                self.quit_requested = True
                return False
            return True
        if key == "\x1a":
            self.undo()
            return False
        if key == "\x19":
            self.redo()
            return False
        if key in ("\x03", "ctrl+c", "\x1b[2;5~"):
            self.clipboard = self._selected_text() if self._selection_offsets() else ""
            if not self.clipboard:
                self.message = "No selection to copy"
            else:
                try:
                    copied_to_system = _write_system_clipboard(self.clipboard)
                except (OSError, subprocess.SubprocessError) as error:
                    self.message = f"Copied in editor; system clipboard failed: {error}"
                else:
                    self.message = (
                        "Copied selection"
                        if copied_to_system
                        else "Copied in editor; no system clipboard command is available"
                    )
            return False
        if key in ("\x18",):
            if self._selection_offsets():
                self.clipboard = self._selected_text()
                self._record_history()
                self._remove_selection()
                self.dirty = True
                self._refresh_search_matches()
                self.message = "Cut selection"
            return False
        if key in ("\x16", "shift+insert", "ctrl+v"):
            if self.clipboard:
                self._insert_text(self.clipboard)
            return False

        modifiers = set(key.split("+")[:-1])
        base_key = key.split("+")[-1]
        shift = "shift" in modifiers
        wordwise = bool(modifiers & {"ctrl", "alt"})
        if base_key in {
            "arrow_up", "arrow_down", "arrow_left", "arrow_right",
            "arrow_home", "arrow_end",
        }:
            if "ctrl" in modifiers and base_key in {"arrow_up", "arrow_down"}:
                self._scroll_view(-1 if base_key == "arrow_up" else 1)
            else:
                self._move_cursor(base_key, shift=shift, wordwise=wordwise)
        elif key in ("\x08", "ctrl+backspace", "alt+backspace"):
            if os.name == "nt":
                if not self._delete_selection(): # For some reason on windows it is the opposit
                    self._backspace()            # I have no idea why just stick to it
            else:
                self._delete_word("left")
        elif key in ("\x7f", "backspace"):
            if os.name == "nt":
                self._delete_word("left")        # same here
            else:
                if not self._delete_selection():
                    self._backspace()
        elif key in ("ctrl+delete", "alt+delete"):
            self._delete_word("right")
        elif key in ("delete", "\x1b[3~"):
            if not self._delete_selection():
                self._delete_forward()
        elif key in ("\r", "\n"):
            self._insert_newline()
        elif key == "\t":
            suggestion = self._get_suggestion_suffix()
            self._insert_text(suggestion if suggestion else "\t")
        elif key and key.isprintable() and (len(key) == 1 or "+" not in key):
            # Single printable characters (including '+') are text; multi-part
            # names such as "alt+delete" are symbolic key events.
            self._insert_text(key)
        if key not in ("\x11",):
            self.quit_requested = False
        if key != "\x11":
            self.message = ""
        self.cursor_y = min(self.cursor_y, len(self.lines) - 1)
        self.cursor_x = min(self.cursor_x, len(self.lines[self.cursor_y]))
        return False

    def _run_split_terminal(self, run_chemql=False):
        """Open a shell; Ctrl+R runs the configured command for this file."""
        command = None
        if run_chemql:
            if not self.filename:
                self.message = "Save the file before running it"
                return

            # Run the current buffer rather than stale on-disk contents.
            if self.dirty:
                self.save_file()
                if self.dirty:
                    return

            absolute_path = os.path.abspath(self.filename)
            configured_command = self.highlight_profiles.get_run_command(
                self.filename
            ) if hasattr(self, "highlight_profiles") else None

            # Preserve CodecQL's original default when no extension-specific
            # command is configured.
            command_template = configured_command or "chemql -f $absoluteName"
            if os.name == "nt":
                quoted_path = subprocess.list2cmdline([absolute_path])
            else:
                import shlex
                quoted_path = shlex.quote(absolute_path)
            command = command_template.replace("$absoluteName", quoted_path)

        if os.name == "nt":
            shell = os.environ.get("COMSPEC", "cmd.exe")
            wt = shutil.which("wt.exe") or shutil.which("wt")

            if wt and os.environ.get("WT_SESSION"):
                try:
                    args = [
                        wt, "-w", "0", "split-pane", "-V",
                        "--size", "0.35", "--title", "CodecQL Terminal",
                        shell, "/K",
                    ]
                    if command:
                        args.append(command)
                    subprocess.Popen(args)
                except OSError as error:
                    self.message = f"Could not open Windows Terminal pane: {error}"
                else:
                    self.message = (
                        "Configured command running in Windows Terminal pane" if command else
                        "Terminal opened in a Windows Terminal pane; resize it with "
                        "Alt+Shift+Plus/Minus or drag the divider. Exit the shell to close it."
                    )
                return

            try:
                args = [shell]
                if command:
                    args.extend(["/K", command])
                subprocess.Popen(
                    args,
                    creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                )
            except OSError as error:
                self.message = f"Could not open terminal: {error}"
            else:
                self.message = "Configured command running in a separate console" if command else "Terminal opened in a separate console window"
            return

        stdin_fd = sys.stdin.fileno()
        stdout_fd = sys.stdout.fileno()
        old_settings = termios.tcgetattr(stdin_fd)
        try:
            cols, rows = os.get_terminal_size(stdin_fd)
        except OSError:
            cols, rows = 80, 24
        rows, cols = max(rows, 6), max(cols, 20)
        pane_height = min(max(4, rows // 3), rows - 3)
        master_fd = None
        child_pid = None
        resize_pending = False
        previous_winch_handler = None

        def on_resize(_signum, _frame):
            nonlocal resize_pending
            resize_pending = True

        try:
            previous_winch_handler = signal.getsignal(signal.SIGWINCH)
            signal.signal(signal.SIGWINCH, on_resize)
        except (AttributeError, ValueError):
            previous_winch_handler = None

        def dimensions():
            try:
                current_cols, current_rows = os.get_terminal_size(stdin_fd)
            except OSError:
                current_cols, current_rows = 80, 24
            current_rows = max(current_rows, 6)
            current_cols = max(current_cols, 20)
            current_pane_height = min(max(4, pane_height), current_rows - 3)
            current_top = current_rows - current_pane_height + 1
            return current_cols, current_rows, current_pane_height, current_top

        try:
            self.message = "Terminal open · Ctrl+T/Esc returns · Ctrl+↑/↓ resizes pane"
            cols, rows, pane_height, pane_top = dimensions()
            self.draw_screen(terminal_height=pane_height)
            for row in range(pane_top, rows + 1):
                sys.stdout.write(f"\x1b[{row};1H\x1b[2K")
            sys.stdout.flush()

            child_pid, master_fd = pty.fork()
            if child_pid == 0:
                fcntl.ioctl(
                    sys.stdin.fileno(), termios.TIOCSWINSZ,
                    struct.pack("HHHH", pane_height, cols, 0, 0),
                )
                shell = os.environ.get("SHELL") or ("/bin/bash" if os.path.exists("/bin/bash") else "/bin/sh")
                try:
                    os.execvp(shell, [shell, "-i"])
                except OSError as error:
                    os.write(2, f"Could not start {shell}: {error}\n".encode())
                    os._exit(127)

            fcntl.ioctl(
                master_fd, termios.TIOCSWINSZ,
                struct.pack("HHHH", pane_height, cols, 0, 0),
            )
            tty.setraw(stdin_fd)
            if command:
                os.write(master_fd, command.encode("utf-8") + b"\n")
            sys.stdout.write(f"\x1b[{pane_top};{rows}r\x1b[?6h\x1b[1;1H")
            sys.stdout.flush()

            resize_keys = {
                b"\x1b[1;5A": -1, b"\x1b[1;5B": 1,
                b"\x1b[1;5;1A": -1, b"\x1b[1;5;1B": 1,
            }
            while True:
                try:
                    ready, _, _ = select.select([stdin_fd, master_fd], [], [], 0.25)
                except InterruptedError:
                    ready = []

                if resize_pending:
                    resize_pending = False
                    cols, rows, pane_height, pane_top = dimensions()
                    fcntl.ioctl(
                        master_fd, termios.TIOCSWINSZ,
                        struct.pack("HHHH", pane_height, cols, 0, 0),
                    )
                    try:
                        os.kill(child_pid, signal.SIGWINCH)
                    except ProcessLookupError:
                        pass
                    sys.stdout.write("\x1b[r\x1b[H\x1b[2J")
                    self.draw_screen(terminal_height=pane_height)
                    for row in range(pane_top, rows + 1):
                        sys.stdout.write(f"\x1b[{row};1H\x1b[2K")
                    sys.stdout.write(f"\x1b[{pane_top};{rows}r\x1b[?6h")
                    sys.stdout.flush()

                if master_fd in ready:
                    try:
                        output = os.read(master_fd, 4096)
                    except OSError:
                        output = b""
                    if not output:
                        break
                    view = memoryview(output)
                    while view:
                        written = os.write(stdout_fd, view)
                        view = view[written:]

                if stdin_fd in ready:
                    user_input = os.read(stdin_fd, 4096)
                    if not user_input:
                        break

                    # Intercept pane controls without sending them to the shell.
                    resized = False
                    for sequence, delta in resize_keys.items():
                        if user_input == sequence:
                            pane_height = max(4, min(rows - 3, pane_height + delta))
                            cols, rows, pane_height, pane_top = dimensions()
                            fcntl.ioctl(
                                master_fd, termios.TIOCSWINSZ,
                                struct.pack("HHHH", pane_height, cols, 0, 0),
                            )
                            try:
                                os.kill(child_pid, signal.SIGWINCH)
                            except ProcessLookupError:
                                pass
                            sys.stdout.write("\x1b[r\x1b[H\x1b[2J")
                            self.draw_screen(terminal_height=pane_height)
                            for row in range(pane_top, rows + 1):
                                sys.stdout.write(f"\x1b[{row};1H\x1b[2K")
                            sys.stdout.write(f"\x1b[{pane_top};{rows}r\x1b[?6h")
                            sys.stdout.flush()
                            resized = True
                            break
                    if resized:
                        continue

                    exit_positions = [
                        position for marker in (b"\x14", b"\x11")
                        if (position := user_input.find(marker)) >= 0
                    ]
                    escape_position = user_input.find(b"\x1b")
                    if escape_position >= 0 and user_input[escape_position:] == b"\x1b":
                        try:
                            escaped_input, _, _ = select.select([stdin_fd], [], [], 0.05)
                        except InterruptedError:
                            escaped_input = []
                        if escaped_input:
                            user_input += os.read(stdin_fd, 4096)
                        else:
                            exit_positions.append(escape_position)
                    if exit_positions:
                        exit_position = min(exit_positions)
                        if exit_position:
                            os.write(master_fd, user_input[:exit_position])
                        break
                    os.write(master_fd, user_input)
        except OSError as error:
            self.message = f"Terminal error: {error}"
        finally:
            if previous_winch_handler is not None:
                try:
                    signal.signal(signal.SIGWINCH, previous_winch_handler)
                except (AttributeError, ValueError):
                    pass
            try:
                termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_settings)
            except termios.error:
                pass
            sys.stdout.write("\x1b[?6l\x1b[r\x1b[?25h\x1b[?2004h\x1b[?1l\x1b[H\x1b[2J")
            sys.stdout.flush()
            if master_fd is not None:
                try:
                    os.close(master_fd)
                except OSError:
                    pass
            if child_pid is not None:
                try:
                    waited_pid, _ = os.waitpid(child_pid, os.WNOHANG)
                except ChildProcessError:
                    waited_pid = child_pid
                if waited_pid != child_pid:
                    try:
                        os.kill(child_pid, signal.SIGHUP)
                    except ProcessLookupError:
                        pass
                    deadline = time.monotonic() + 1
                    while time.monotonic() < deadline:
                        try:
                            waited_pid, _ = os.waitpid(child_pid, os.WNOHANG)
                        except ChildProcessError:
                            waited_pid = child_pid
                        if waited_pid == child_pid:
                            break
                        time.sleep(0.02)
                    else:
                        try:
                            os.kill(child_pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        try:
                            os.waitpid(child_pid, 0)
                        except ChildProcessError:
                            pass
            if not self.message.startswith("Terminal error:"):
                self.message = "Terminal closed · returned to editor"

    def _scroll_view(self, direction):
        try:
            _, rows = os.get_terminal_size()
        except OSError:
            rows = 24
        viewport_height = max(rows, 4) - 2
        max_scroll = max(0, len(self.lines) - viewport_height)
        new_scroll_y = max(0, min(max_scroll, self.scroll_y + direction))
        scroll_delta = new_scroll_y - self.scroll_y
        self.scroll_y = new_scroll_y
        self.cursor_y = max(0, min(len(self.lines) - 1, self.cursor_y + scroll_delta))

    def _open_search(self):
        self.search_active = True
        self.search_query = ""
        self.search_regex = None
        self.search_error = ""
        self.search_matches = []
        self.current_search_match = None
        self.message = ""

    def _handle_search_key(self, key):
        if key in ("\x1b", "\x03"):
            self.search_active = False
            self.search_matches = []
            self.current_search_match = None
            self.message = "Search closed"
            return False
        if key in ("\r", "\n"):
            self._select_search_match(reverse=False)
            return False
        if key in ("arrow_up", "arrow_left"):
            self._select_search_match(reverse=True)
            return False
        if key in ("arrow_down", "arrow_right"):
            self._select_search_match(reverse=False)
            return False
        if key in ("\x7f", "\x08", "backspace"):
            self.search_query = self.search_query[:-1]
            self._update_search()
            return False
        if key.startswith("paste:"):
            pasted = key[6:].replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
            self.search_query += pasted
            self._update_search()
            return False
        if len(key) == 1 and key.isprintable():
            self.search_query += key
            self._update_search()
        return False

    def _update_search(self):
        self.search_regex = None
        self.search_error = ""
        self.search_matches = []
        self.current_search_match = None
        if not self.search_query:
            return
        try:
            self.search_regex = _parse_search_query(self.search_query)
        except (ValueError, re.error) as error:
            self.search_error = str(error)
            return

        content = "\n".join(self.lines)
        self.search_matches = [
            (match.start(), match.end())
            for match in self.search_regex.finditer(content)
            if match.start() != match.end()
        ]

    def _refresh_search_matches(self):
        if self.search_query:
            self._update_search()

    def _select_search_match(self, reverse=False):
        if not self.search_matches:
            self.message = f"Search error: {self.search_error}" if self.search_error else "No matches"
            return

        if self.current_search_match in self.search_matches:
            index = self.search_matches.index(self.current_search_match)
            index = (index + (-1 if reverse else 1)) % len(self.search_matches)
        else:
            cursor = self._position_to_offset(self.cursor_x, self.cursor_y)
            if reverse:
                eligible = [
                    index for index, (start, _) in enumerate(self.search_matches)
                    if start < cursor
                ]
                index = eligible[-1] if eligible else len(self.search_matches) - 1
            else:
                eligible = [
                    index for index, (start, _) in enumerate(self.search_matches)
                    if start >= cursor
                ]
                index = eligible[0] if eligible else 0
        self.current_search_match = self.search_matches[index]
        self.cursor_x, self.cursor_y = self._offset_to_position(self.current_search_match[0])
        self._clear_selection()
        self.message = f"Match {index + 1} of {len(self.search_matches)}"

    def _position_to_offset(self, x, y):
        return sum(len(line) + 1 for line in self.lines[:y]) + x

    def _offset_to_position(self, offset):
        for y, line in enumerate(self.lines):
            if offset <= len(line):
                return offset, y
            offset -= len(line) + 1
        last_y = len(self.lines) - 1
        return len(self.lines[last_y]), last_y

    def _selection_offsets(self):
        if self.selection_anchor is None:
            return None
        anchor_x, anchor_y = self.selection_anchor
        anchor = self._position_to_offset(anchor_x, anchor_y)
        cursor = self._position_to_offset(self.cursor_x, self.cursor_y)
        if anchor == cursor:
            return None
        return min(anchor, cursor), max(anchor, cursor)

    def _selected_text(self):
        selection = self._selection_offsets()
        if selection is None:
            return ""
        content = "\n".join(self.lines)
        return content[selection[0]:selection[1]]

    def _clear_selection(self):
        self.selection_anchor = None

    def _remove_selection(self):
        selection = self._selection_offsets()
        if selection is None:
            return False
        content = "\n".join(self.lines)
        content = content[:selection[0]] + content[selection[1]:]
        self.lines = content.split("\n")
        self.cursor_x, self.cursor_y = self._offset_to_position(selection[0])
        self._clear_selection()
        return True

    def _delete_selection(self):
        if self._selection_offsets() is None:
            return False
        self._record_history()
        self._remove_selection()
        self.dirty = True
        self._refresh_search_matches()
        return True

    def _delete_word(self, direction):
        if self._delete_selection():
            return

        original = (self.cursor_x, self.cursor_y)
        self._move_word_left() if direction == "left" else self._move_word_right()
        destination = (self.cursor_x, self.cursor_y)
        self.cursor_x, self.cursor_y = original
        if destination == original:
            return

        self._record_history()
        self.selection_anchor = original
        self.cursor_x, self.cursor_y = destination
        self._remove_selection()
        self.dirty = True
        self._refresh_search_matches()

    def _move_cursor(self, direction, shift=False, wordwise=False):
        if shift and self.selection_anchor is None:
            self.selection_anchor = (self.cursor_x, self.cursor_y)
        elif not shift:
            self._clear_selection()

        if direction == "arrow_up":
            self.cursor_y = max(0, self.cursor_y - 1)
            self.cursor_x = min(self.cursor_x, len(self.lines[self.cursor_y]))
        elif direction == "arrow_down":
            self.cursor_y = min(len(self.lines) - 1, self.cursor_y + 1)
            self.cursor_x = min(self.cursor_x, len(self.lines[self.cursor_y]))
        elif direction in {"arrow_home", "arrow_end"}:
            self.cursor_x = 0 if direction == "arrow_home" else len(self.lines[self.cursor_y])
        elif direction == "arrow_left":
            if wordwise:
                self._move_word_left()
            elif self.cursor_x > 0:
                self.cursor_x -= 1
            elif self.cursor_y > 0:
                self.cursor_y -= 1
                self.cursor_x = len(self.lines[self.cursor_y])
        elif direction == "arrow_right":
            if wordwise:
                self._move_word_right()
            elif self.cursor_x < len(self.lines[self.cursor_y]):
                self.cursor_x += 1
            elif self.cursor_y < len(self.lines) - 1:
                self.cursor_y += 1
                self.cursor_x = 0

    def _move_word_left(self):
        line = self.lines[self.cursor_y]
        if self.cursor_x == 0:
            if self.cursor_y > 0:
                self.cursor_y -= 1
                self.cursor_x = len(self.lines[self.cursor_y])
            return
        self.cursor_x -= 1
        while self.cursor_x > 0 and line[self.cursor_x].isspace():
            self.cursor_x -= 1
        while self.cursor_x > 0 and not line[self.cursor_x - 1].isspace():
            self.cursor_x -= 1

    def _move_word_right(self):
        line = self.lines[self.cursor_y]
        while self.cursor_x < len(line) and not line[self.cursor_x].isspace():
            self.cursor_x += 1
        while self.cursor_x < len(line) and line[self.cursor_x].isspace():
            self.cursor_x += 1
        if self.cursor_x == len(line) and self.cursor_y < len(self.lines) - 1:
            self.cursor_y += 1
            self.cursor_x = 0

    def _insert_text(self, text):
        self._record_history()
        self._remove_selection()
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if text in {"=", ">", "<", "-", "!", "~"} and self.cursor_x:
            line = self.lines[self.cursor_y]
            left = line[:self.cursor_x]
            replacements = {
                ">=": "≥", "<=": "≤", "!=": "≠", "->": "→",
                "<-": "←", "=>": "⇒", "~=": "≈",
            }
            for source, target in sorted(replacements.items(), key=lambda item: -len(item[0])):
                prefix = source[:-1]
                if prefix and left.endswith(prefix):
                    left = left[:-len(prefix)]
                    self.lines[self.cursor_y] = left + line[self.cursor_x:]
                    text = target
                    break
        current_line = self.lines[self.cursor_y]
        left_side = current_line[:self.cursor_x]
        right_side = current_line[self.cursor_x:]
        inserted_lines = text.split("\n")
        replacement = [left_side + inserted_lines[0]]
        replacement.extend(inserted_lines[1:-1])
        if len(inserted_lines) > 1:
            replacement.append(inserted_lines[-1] + right_side)
        else:
            replacement[0] += right_side
        self.lines[self.cursor_y:self.cursor_y + 1] = replacement
        self.cursor_y += len(inserted_lines) - 1
        self.cursor_x = len(inserted_lines[-1]) if len(inserted_lines) > 1 else len(left_side) + len(text)
        self._clear_selection()
        self.dirty = True
        self._refresh_search_matches()

    def _insert_newline(self):
        current_line = self.lines[self.cursor_y]
        left_side = current_line[:self.cursor_x]
        right_side = current_line[self.cursor_x:]
        indentation_match = re.match(r"^\s*", left_side)
        indentation = indentation_match.group() if indentation_match else ""
        if AUTO_INDENT.match(left_side.rstrip()):
            indentation += "\t"
        if left_side.strip().casefold() == "endnamespace":
            if indentation.endswith("\t"):
                indentation = indentation[:-1]
            elif indentation.endswith("    "):
                indentation = indentation[:-4]
        self._insert_text("\n" + indentation)

    def _backspace(self):
        current_line = self.lines[self.cursor_y]
        if self.cursor_x > 0:
            self._record_history()
            self.lines[self.cursor_y] = (
                current_line[:self.cursor_x - 1] + current_line[self.cursor_x:]
            )
            self.cursor_x -= 1
            self.dirty = True
            self._refresh_search_matches()
        elif self.cursor_y > 0:
            self._record_history()
            previous_length = len(self.lines[self.cursor_y - 1])
            self.lines[self.cursor_y - 1] += current_line
            self.lines.pop(self.cursor_y)
            self.cursor_y -= 1
            self.cursor_x = previous_length
            self.dirty = True
            self._refresh_search_matches()

    def _delete_forward(self):
        current_line = self.lines[self.cursor_y]
        if self.cursor_x < len(current_line):
            self._record_history()
            self.lines[self.cursor_y] = (
                current_line[:self.cursor_x] + current_line[self.cursor_x + 1:]
            )
            self.dirty = True
            self._refresh_search_matches()
        elif self.cursor_y < len(self.lines) - 1:
            self._record_history()
            self.lines[self.cursor_y] += self.lines.pop(self.cursor_y + 1)
            self.dirty = True
            self._refresh_search_matches()

    def _current_state(self):
        return tuple(self.lines), self.cursor_x, self.cursor_y

    def _restore_state(self, state):
        lines, self.cursor_x, self.cursor_y = state
        self.lines = list(lines)
        self.dirty = tuple(self.lines) != self.saved_lines
        self._refresh_search_matches()

    def _record_history(self):
        self.undo_stack.append(self._current_state())
        if len(self.undo_stack) > self.HISTORY_LIMIT:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack:
            self.message = "Nothing to undo"
            return
        self.redo_stack.append(self._current_state())
        self._restore_state(self.undo_stack.pop())
        self.message = "Undone"

    def redo(self):
        if not self.redo_stack:
            self.message = "Nothing to redo"
            return
        self.undo_stack.append(self._current_state())
        self._restore_state(self.redo_stack.pop())
        self.message = "Redone"

    def save_file(self):
        if not self.filename:
            try:
                filename = input("Save tab as: ").strip()
            except (EOFError, KeyboardInterrupt):
                filename = ""
            if not filename:
                self.message = "Save cancelled"
                return
            self.filename = filename
        try:
            with open(self.filename, 'w', encoding='utf-8') as f:
                f.write("\n".join(self.lines))
            self.saved_lines = tuple(self.lines)
            self.dirty = False
            self.message = f"Saved {self.filename}"
        except Exception as e:
            self.message = f"Failed to save file: {str(e)}"

def main(argv: list[str] | None = None) -> None:
    """Launch the ChemQL terminal editor for the requested file."""
    parser = argparse.ArgumentParser(
        prog="codecql",
        description="Open and edit a ChemQL source file.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"codecql {VERSION}")
    parser.add_argument("file", nargs="?", help="ChemQL file to edit")
    parser.add_argument(
        "--main-highlighting",
        action="store_true",
        help="Open CodecQL's main highlighting configuration",
    )

    parser.add_argument(
        "--local-highlighting",
        action="store_true",
        help="Open the current directory's highlighting configuration",
    )
    arguments = parser.parse_args(argv)
    if arguments.main_highlighting and arguments.local_highlighting:
        parser.error("Choose only one highlighting configuration")

    if arguments.main_highlighting:
        filename = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "highlighting.json",
        )

    elif arguments.local_highlighting:
        filename = os.path.join(os.getcwd(), "highlighting.json")

    else:
        filename = arguments.file

    if not filename:
        parser.error("the following arguments are required: file")

    if arguments.main_highlighting or arguments.local_highlighting:
        if not os.path.exists(filename):
            with open(filename, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=4)
                f.write("\n")

    Editor(filename).run()

if __name__ == "__main__":
    main()
