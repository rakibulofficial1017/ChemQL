import os
import re
import json
import argparse
import keyword
import builtins
import sys
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
    def get_key():
        ch = msvcrt.getch()
        if ch in (b'\x00', b'\xe0'): # Arrow key prefixes on Windows
            ch2 = msvcrt.getch()
            if ch2 == b'\x53':
                return "delete"
            return f"arrow_{ch2.hex()}"
        return ch.decode('utf-8', errors='ignore')
else:
    import tty
    import termios
    import select

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
                if sequence.startswith(b"["):
                    final = bytes(sequence[-1:]) if sequence else b""
                    if final in {b"A", b"B", b"C", b"D", b"H", b"F"}:
                        return {
                            b"A": "arrow_up", b"B": "arrow_down",
                            b"C": "arrow_right", b"D": "arrow_left",
                            b"H": "arrow_home", b"F": "arrow_end",
                        }[final]
                    if final == b"~":
                        code = bytes(sequence[1:-1]).split(b";", 1)[0]
                        if code in {b"1", b"7"}:
                            return "arrow_home"
                        if code in {b"4", b"8"}:
                            return "arrow_end"
                        if code == b"3":
                            return "delete"
                elif sequence.startswith(b"O") and bytes(sequence[-1:]) in {b"A", b"B", b"C", b"D", b"H", b"F"}:
                    return {
                        b"A": "arrow_up", b"B": "arrow_down",
                        b"C": "arrow_right", b"D": "arrow_left",
                        b"H": "arrow_home", b"F": "arrow_end",
                    }[bytes(sequence[-1:])]
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
    "endrecord", "endenum",
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
            r"\b(?:enum|struct|record)\s+$", text[:match.start()], re.IGNORECASE
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
        sys.stdout.write("\x1b[?1049h")
        sys.stdout.flush()
        try:
            while True:
                self.draw_screen()
                key = get_key()
                if self.handle_key(key):
                    break
        finally:
            sys.stdout.write("\x1b[?1049l")
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
                    apply_syntax_highlighting(visible_text), "\x1b[K\r\n",
                ))
            else:
                output.extend((DIM, MUTED, " " * (gutter_width - 1), "~", RESET, "\x1b[K\r\n"))

        title = f" ChemQL  {os.path.basename(self.filename) if self.filename else 'untitled'}"
        status = f"Ln {self.cursor_y + 1}, Col {self.cursor_x + 1}  |  {len(self.lines)} lines"
        if self.dirty:
            status += "  |  Unsaved"
        status_text = f"{title:<{max(0, cols - len(status))}}{status}"
        output.extend((STATUS_BG, STATUS_FG, status_text[:cols].ljust(cols), RESET, "\r\n"))
        footer = self.message or "Ctrl+S Save   Ctrl+Z Undo   Ctrl+Y Redo   Ctrl+Q Quit"
        output.extend((DIM, footer[:cols].ljust(cols), RESET))
        cursor_row = self.cursor_y - self.scroll_y + 1
        cursor_col = gutter_width + visual_cursor_x - self.scroll_x
        output.append(f"\x1b[{cursor_row};{cursor_col}H")

        sys.stdout.write("".join(output))
        sys.stdout.flush()

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
        if key in ("arrow_up", "arrow_H", "arrow_A", "arrow_48"):
            self.cursor_y = max(0, self.cursor_y - 1)
        elif key in ("arrow_down", "arrow_P", "arrow_B", "arrow_50"):
            self.cursor_y = min(len(self.lines) - 1, self.cursor_y + 1)
        elif key in ("arrow_left", "arrow_K", "arrow_D", "arrow_4b"):
            self.cursor_x = max(0, self.cursor_x - 1)
        elif key in ("arrow_right", "arrow_M", "arrow_C", "arrow_4d"):
            self.cursor_x = min(len(self.lines[self.cursor_y]), self.cursor_x + 1)
        elif key in ("arrow_end", "arrow_4f", "arrow_F"):
            self.cursor_x = len(self.lines[self.cursor_y])
        elif key in ("arrow_home", "arrow_47", "arrow_G"):
            self.cursor_x = 0
        elif key in ("\x7f", "\x08"):
            self._backspace()
        elif key in ("delete", "\x1b[3~"):
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

    def _insert_text(self, text):
        current_line = self.lines[self.cursor_y]
        self._record_history()
        self.lines[self.cursor_y] = (
            current_line[:self.cursor_x] + text + current_line[self.cursor_x:]
        )
        self.cursor_x += len(text)
        self.dirty = True

    def _insert_newline(self):
        current_line = self.lines[self.cursor_y]
        left_side = current_line[:self.cursor_x]
        right_side = current_line[self.cursor_x:]
        indentation = re.match(r"^\s*", current_line).group() if re.match(r"^\s*", current_line) is not None else "" # type:ignore
        if AUTO_INDENT.match(left_side.rstrip()):
            indentation += "\t"
        self._record_history()
        self.lines[self.cursor_y] = left_side
        self.lines.insert(self.cursor_y + 1, indentation + right_side)
        self.cursor_y += 1
        self.cursor_x = len(indentation)
        self.dirty = True

    def _backspace(self):
        current_line = self.lines[self.cursor_y]
        if self.cursor_x > 0:
            self._record_history()
            self.lines[self.cursor_y] = (
                current_line[:self.cursor_x - 1] + current_line[self.cursor_x:]
            )
            self.cursor_x -= 1
            self.dirty = True
        elif self.cursor_y > 0:
            self._record_history()
            previous_length = len(self.lines[self.cursor_y - 1])
            self.lines[self.cursor_y - 1] += current_line
            self.lines.pop(self.cursor_y)
            self.cursor_y -= 1
            self.cursor_x = previous_length
            self.dirty = True

    def _delete_forward(self):
        current_line = self.lines[self.cursor_y]
        if self.cursor_x < len(current_line):
            self._record_history()
            self.lines[self.cursor_y] = (
                current_line[:self.cursor_x] + current_line[self.cursor_x + 1:]
            )
            self.dirty = True
        elif self.cursor_y < len(self.lines) - 1:
            self._record_history()
            self.lines[self.cursor_y] += self.lines.pop(self.cursor_y + 1)
            self.dirty = True

    def _current_state(self):
        return tuple(self.lines), self.cursor_x, self.cursor_y

    def _restore_state(self, state):
        lines, self.cursor_x, self.cursor_y = state
        self.lines = list(lines)
        self.dirty = tuple(self.lines) != self.saved_lines

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
