import os
import re
import json
import argparse
import keyword
import builtins
import sys
import shutil
import subprocess


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
            elif key_code == "27" and len(params) > 2 and params[2] == "127":
                key = "backspace"
            else:
                return "\x1b"
            return "+".join((*modifiers, key)) if modifiers else key
        if final == b"u" and params and params[0] == "127":
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
        0x53: "delete", 0x73: "ctrl+arrow_left",
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
                if sequence:
                    return "alt+" + sequence.decode("utf-8", errors="replace")
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
    with open(config_path, encoding="utf-8") as config_file:
        config = json.load(config_file)
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
    "cleanup",
}
CONTROL_KEYWORDS = {
    "if", "elif", "else", "endif", "for", "while", "in", "endfor",
    "endwhile", "break", "continue", "endblock", "from", "as", "public",
    "private", "required", "struct", "record", "enum", "endstruct",
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


def _token_style(kind, value):
    if kind == "comment":
        return HIGHLIGHT_STYLES["comment"]
    if kind == "string":
        return HIGHLIGHT_STYLES["string"]
    if kind == "number":
        return HIGHLIGHT_STYLES["number"]
    if kind == "formula" and (any(char.isdigit() for char in value) or len(re.findall(r"[A-Z]", value)) > 1):
        return HIGHLIGHT_STYLES["formula"]
    if kind == "operator":
        return HIGHLIGHT_STYLES["operator"]
    if kind == "delimiter":
        return HIGHLIGHT_STYLES["command"] if value == "?" else HIGHLIGHT_STYLES["delimiter"]
    word = value.casefold()
    if word in {"true", "false", "none"}:
        category = "constant"
    elif word in {"enum", "struct", "record"}:
        category = "type"
    elif word in COMMANDS or word == "?":
        category = "command"
    elif word in CONTROL_KEYWORDS or keyword.iskeyword(word):
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


def apply_syntax_highlighting(text):
    parts = []
    last_end = 0
    for match in TOKEN_RE.finditer(text):
        parts.append(text[last_end:match.start()])
        kind = match.lastgroup
        token = match.group()
        style = _token_style(kind, token) if kind else ""
        if kind == "identifier" and re.search(
            r"\b(?:enum|struct|record|namespace)\s+$", text[:match.start()], re.IGNORECASE
        ):
            style = HIGHLIGHT_STYLES["type"]
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

        if filename and os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read().splitlines()
                self.lines = content if content else [""]
        self.saved_lines = tuple(self.lines)

    def run(self):
        sys.stdout.write("\x1b[?1049h\x1b[?2004h")
        sys.stdout.flush()
        try:
            while True:
                self.draw_screen()
                key = get_key()
                if self.handle_key(key):
                    break
        finally:
            sys.stdout.write("\x1b[?2004l\x1b[?1049l")
            sys.stdout.flush()

    def draw_screen(self):
        try:
            cols, rows = os.get_terminal_size()
        except OSError:
            cols, rows = 80, 24
        cols = max(cols, 20)
        rows = max(rows, 4)
        gutter_width = len(str(max(len(self.lines), self.cursor_y + 1))) + 2
        viewport_height = rows - 2
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
                output.extend((
                    DIM, MUTED, line_number, RESET,
                    self._highlight_line(visible_text, line_y), "\x1b[K\r\n",
                ))
            else:
                output.extend((DIM, MUTED, " " * (gutter_width - 1), "~", RESET, "\x1b[K\r\n"))

        title = f" ChemQL  {os.path.basename(self.filename) if self.filename else 'untitled'}"
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
                "Ctrl+F Search  Ctrl+Backspace/Delete Word"
            )
        )
        output.extend((DIM, footer[:cols].ljust(cols), RESET))
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
            return apply_syntax_highlighting(visible_text)

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
                parts.append(apply_syntax_highlighting(segment))
        return "".join(parts)

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
        elif key in ("\x08", "ctrl+backspace"):
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
        elif key in ("ctrl+delete",):
            self._delete_word("right")
        elif key in ("delete", "\x1b[3~"):
            if not self._delete_selection():
                self._delete_forward()
        elif key in ("\r", "\n"):
            self._insert_newline()
        elif key == "\t":
            self._insert_text("\t")
        elif key and key.isprintable():
            self._insert_text(key)
        if key not in ("\x11",):
            self.quit_requested = False
        if key != "\x11":
            self.message = ""
        self.cursor_y = min(self.cursor_y, len(self.lines) - 1)
        self.cursor_x = min(self.cursor_x, len(self.lines[self.cursor_y]))
        return False

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
            self.message = "Error: No file specified. Run with an argument name!"
            return
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
    parser.add_argument("file", help="ChemQL file to edit")
    arguments = parser.parse_args(argv)
    Editor(arguments.file).run()


if __name__ == "__main__":
    main()
