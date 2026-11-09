#!/usr/bin/env python3
"""CodecQLX -- a Tkinter desktop editor for ChemQL.

Builds on the terminal CodecQL's feature set (syntax highlighting, inline
suggestions, lightweight diagnostics) and adds things a terminal app
structurally cannot do:

  - A real autocomplete dropdown showing every matching suggestion
    (click or arrow+Enter), not just one best-guess ghost completion,
    and it works anywhere on the line, not only at end-of-line.
  - Hoverable diagnostics: the full error/warning message on mouseover,
    plus a clickable Problems panel and gutter markers.
  - A project file tree sidebar for multi-file work.
  - A query console that runs ChemQL in-process (via chemql's own Python
    API) and renders results as a real sortable table or a field card,
    instead of a wall of ANSI text.
  - An interactive periodic table you can click to look elements up.
  - A reaction-balancer panel with its own input fields.
  - A visual preferences dialog (theme, fonts, per-token colors) instead
    of hand-editing JSON.
  - An overview ruler (a mini error/warning map down the scrollbar) and
    bookmarks for fast navigation in long files.
  - Recent files and side-by-side panes for working across multiple files.

Run with:  python -m chemql.codecqlx [file_or_folder ...]
Needs only the standard library; chemql-specific panels disable
themselves gracefully if the `chemql` package isn't installed.
"""
from __future__ import annotations

import os
import queue
import re
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk
from typing import Optional

from . import codecql_gui_core as core

APP_TITLE = "CodecQLX"
APP_ICON = (Path(__file__).resolve().parent / "logo64.png")
FONT_MONO_FALLBACKS = ["Consolas", "Menlo", "DejaVu Sans Mono", "Courier New", "monospace"]


def _pick_font_family(preferred: str) -> str:
    try:
        import tkinter.font as tkfont
        available = set(tkfont.families())
    except Exception:
        return preferred
    for candidate in [preferred, *FONT_MONO_FALLBACKS]:
        if candidate in available:
            return candidate
    return preferred


# --------------------------------------------------------------------------
# Small reusable widgets
# --------------------------------------------------------------------------

class Tooltip:
    """A borderless popup that follows the mouse over a widget region."""

    def __init__(self, root: tk.Misc):
        self.root = root
        self.window: tk.Toplevel | None = None
        self.label: tk.Label | None = None

    def show(self, text: str, x: int, y: int, bg: str, fg: str) -> None:
        if self.window is None:
            self.window = tk.Toplevel(self.root)
            self.window.wm_overrideredirect(True)
            self.window.wm_attributes("-topmost", True)
            self.label = tk.Label(
                self.window, text=text, justify="left", bg=bg, fg=fg,
                relief="solid", borderwidth=1, padx=6, pady=3,
                font=("TkDefaultFont", 9), wraplength=420,
            )
            self.label.pack()
        else:
            self.label.configure(text=text, bg=bg, fg=fg)
        self.window.wm_geometry(f"+{x}+{y}")
        self.window.deiconify()

    def hide(self) -> None:
        if self.window is not None:
            self.window.withdraw()


class AutocompletePopup:
    """A borderless Listbox positioned under the text cursor, offering every
    matching suggestion -- the GUI's answer to the terminal's single ghost
    completion."""

    def __init__(self, root: tk.Misc, on_accept):
        self.root = root
        self.on_accept = on_accept
        self.window: tk.Toplevel | None = None
        self.listbox: tk.Listbox | None = None
        self.items: list[str] = []

    @property
    def visible(self) -> bool:
        return self.window is not None and self.window.winfo_viewable()

    def show(self, items: list[str], x: int, y: int, bg: str, fg: str, select_bg: str) -> None:
        self.items = items
        if self.window is None:
            self.window = tk.Toplevel(self.root)
            self.window.wm_overrideredirect(True)
            self.window.wm_attributes("-topmost", True)
            self.listbox = tk.Listbox(
                self.window, activestyle="none", exportselection=False,
                highlightthickness=1, borderwidth=1, relief="solid",
                font=("TkFixedFont", 10),
            )
            self.listbox.pack()
            self.listbox.bind("<ButtonRelease-1>", self._on_click)
        self.listbox.configure(bg=bg, fg=fg, selectbackground=select_bg, selectforeground=fg)
        self.listbox.delete(0, tk.END)
        for item in items:
            self.listbox.insert(tk.END, item)
        self.listbox.configure(height=min(8, len(items)))
        visible_width = max((len(item) for item in items), default=10)
        self.listbox.configure(width=max(12, visible_width + 2))
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(0)
        self.window.wm_geometry(f"+{x}+{y}")
        self.window.deiconify()
        self.window.lift()

    def hide(self) -> None:
        if self.window is not None:
            self.window.withdraw()

    def move_selection(self, delta: int) -> None:
        if not self.visible or not self.items:
            return
        current = self.listbox.curselection()
        index = (current[0] if current else 0) + delta
        index = max(0, min(len(self.items) - 1, index))
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(index)
        self.listbox.see(index)

    def accept_selected(self) -> None:
        if not self.visible or not self.items:
            return
        current = self.listbox.curselection()
        index = current[0] if current else 0
        self.on_accept(self.items[index])

    def _on_click(self, _event) -> None:
        self.accept_selected()


# --------------------------------------------------------------------------
# One open file
# --------------------------------------------------------------------------

class EditorTab(ttk.Frame):
    GUTTER_WIDTH = 56
    RULER_WIDTH = 14

    def __init__(self, parent, app: "App", path: Optional[str] = None):
        super().__init__(parent)
        self.app = app
        self.path = path
        self.dirty = False
        self.bookmarks: set[int] = set()       # 1-based line numbers
        self.diagnostics: list[core.Diagnostic] = []
        self._diag_job = None
        self._highlight_job = None

        self.text = tk.Text(
            self, wrap="none", undo=True, maxundo=-1, autoseparators=True,
            font=self.app.editor_font, insertwidth=2, padx=4, pady=2,
            relief="flat", highlightthickness=0,
        )
        self.gutter = tk.Canvas(self, width=self.GUTTER_WIDTH, highlightthickness=0)
        self.ruler = tk.Canvas(self, width=self.RULER_WIDTH, highlightthickness=0)
        self.vscroll = ttk.Scrollbar(self, orient="vertical", command=self._on_scrollbar)
        self.hscroll = ttk.Scrollbar(self, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=self._on_text_yscroll, xscrollcommand=self.hscroll.set)

        self.gutter.grid(row=0, column=0, sticky="ns")
        self.text.grid(row=0, column=1, sticky="nsew")
        self.ruler.grid(row=0, column=2, sticky="ns")
        self.vscroll.grid(row=0, column=3, sticky="ns")
        self.hscroll.grid(row=1, column=1, sticky="ew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        if path and os.path.isfile(path):
            try:
                content = Path(path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                content = ""
                messagebox.showerror(APP_TITLE, f"Could not read {path}:\n{error}")
            self.text.insert("1.0", content)
            self.text.edit_modified(False)

        self._configure_tags()
        self._bind_events()
        self.tooltip = Tooltip(self)
        self.autocomplete = AutocompletePopup(self, self._accept_suggestion)
        self._suggestion_prefix_len = 0

        self.after_idle(self.rehighlight_all)
        self.after_idle(self._schedule_diagnostics)

    # -- setup -----------------------------------------------------------

    def _configure_tags(self) -> None:
        theme = self.app.settings.theme()
        self.text.configure(
            background=theme["background"], foreground=theme["foreground"],
            insertbackground=theme["foreground"], selectbackground=theme["selection"],
            font=self.app.editor_font,
        )
        self.gutter.configure(background=theme["gutter_bg"])
        self.ruler.configure(background=theme["gutter_bg"])
        for tag in core.TOKEN_TAGS:
            if tag in theme:
                self.text.tag_configure(tag, foreground=theme[tag])
        for tag_name, style in self.app.tokenizer.custom_tag_styles.items():
            self._configure_custom_tag(tag_name, style, theme)
        self.text.tag_configure("current_line", background=theme["current_line"])
        for tag_name, color in (("diag_error", theme["error"]), ("diag_warning", theme["warning"])):
            try:
                self.text.tag_configure(tag_name, underline=True, underlinefg=color, foreground=color)
            except tk.TclError:
                # Tk older than 8.6.9 has no per-tag underline color: fall
                # back to a plain underline in the diagnostic's own color.
                self.text.tag_configure(tag_name, underline=True, foreground=color)
        self.text.tag_configure("ghost_match", background=theme["selection"])
        self.text.tag_configure("find_match", background=theme["warning"], foreground=theme["background"])
        # draw order: current line under everything; a highlighting.json
        # rule's own style outranks the fixed categories (it was written to
        # override them); diagnostics outrank everything (an error/warning
        # should stay visible even on specially-styled text).
        self.text.tag_lower("current_line")
        for tag_name in self.app.tokenizer.custom_tag_styles:
            self.text.tag_raise(tag_name)
        self.text.tag_raise("diag_error")
        self.text.tag_raise("diag_warning")
        self.text.tag_bind("diag_error", "<Enter>", self._on_diag_hover)
        self.text.tag_bind("diag_warning", "<Enter>", self._on_diag_hover)
        self.text.tag_bind("diag_error", "<Leave>", lambda _e: self.tooltip.hide())
        self.text.tag_bind("diag_warning", "<Leave>", lambda _e: self.tooltip.hide())

    def _configure_custom_tag(self, tag_name: str, style: "core.ParsedStyle", theme: dict) -> None:
        """Resolve one highlighting.json keyword rule's style string into
        actual Tk tag options against the active theme."""
        foreground = style.foreground
        if foreground is None and style.categories:
            foreground = theme.get(style.categories[0], theme["foreground"])
        if foreground is None:
            foreground = theme["foreground"]
        background = style.background
        if style.reverse:
            foreground, background = (background or theme["background"]), (foreground or theme["background"])
        if style.dim:
            foreground = core.blend_hex(foreground, theme["background"], 0.45)
        family, size = self.app.editor_font
        weight = "bold" if style.bold else "normal"
        slant = "italic" if style.italic else "roman"
        options: dict = {"foreground": foreground, "font": (family, size, f"{weight} {slant}".strip())}
        if background is not None:
            options["background"] = background
        if style.underline:
            options["underline"] = True
        if style.strike:
            options["overstrike"] = True
        try:
            self.text.tag_configure(tag_name, **options)
        except tk.TclError:
            # A malformed color (unlikely, since parse_style_string already
            # validates hex syntax) shouldn't take the whole editor down.
            options.pop("background", None)
            self.text.tag_configure(tag_name, foreground=foreground)

    def _bind_events(self) -> None:
        self.text.bind("<KeyRelease>", self._on_key_release)
        self.text.bind("<ButtonRelease-1>", self._on_cursor_moved)
        self.text.bind("<<Modified>>", self._on_modified)
        self.text.bind("<Tab>", self._on_tab)
        self.text.bind("<Up>", self._on_arrow_up)
        self.text.bind("<Down>", self._on_arrow_down)
        self.text.bind("<Escape>", self._on_escape)
        self.text.bind("<Return>", self._on_return)
        self.text.bind("<Configure>", lambda _e: self._redraw_gutter())
        self.text.bind("<MouseWheel>", self._on_mousewheel)      # Windows/macOS
        self.text.bind("<Button-4>", self._on_mousewheel)        # Linux scroll up
        self.text.bind("<Button-5>", self._on_mousewheel)        # Linux scroll down
        self.text.bind("<Control-MouseWheel>", self._on_ctrl_mousewheel)
        self.text.bind(
            "<FocusIn>",
            lambda _event: self.app.set_active_notebook(self.master),
            add="+",
        )
        self.gutter.bind("<Button-1>", self._on_gutter_click)
        self.ruler.bind("<Button-1>", self._on_ruler_click)
        self.gutter.bind("<Configure>", lambda _e: self._redraw_gutter())
        self.ruler.bind("<Configure>", lambda _e: self._redraw_ruler())

        menu = tk.Menu(self.text, tearoff=False)
        menu.add_command(label="Cut", command=lambda: self.text.event_generate("<<Cut>>"))
        menu.add_command(label="Copy", command=lambda: self.text.event_generate("<<Copy>>"))
        menu.add_command(label="Paste", command=lambda: self.text.event_generate("<<Paste>>"))
        menu.add_separator()
        menu.add_command(label="Run Selection", command=self.app.run_selection)
        menu.add_command(label="Toggle Bookmark", command=self.toggle_bookmark)
        right_click = "<Button-2>" if sys.platform == "darwin" else "<Button-3>"
        self.text.bind(right_click, lambda event: (menu.tk_popup(event.x_root, event.y_root)))

    # -- filename / dirty state -------------------------------------------

    @property
    def display_name(self) -> str:
        base = os.path.basename(self.path) if self.path else "Untitled"
        return ("* " if self.dirty else "") + base

    def mark_clean(self) -> None:
        self.dirty = False
        self.text.edit_modified(False)
        self.app.refresh_tab_titles()

    # -- content access -----------------------------------------------------

    def get_lines(self) -> list[str]:
        return self.text.get("1.0", "end-1c").split("\n")

    def current_line_and_col(self) -> tuple[str, int, int]:
        index = self.text.index("insert")
        line_no, col = (int(part) for part in index.split("."))
        line_text = self.text.get(f"{line_no}.0", f"{line_no}.end")
        return line_text, col, line_no

    # -- events --------------------------------------------------------

    def _on_modified(self, _event=None) -> None:
        if self.text.edit_modified():
            self.dirty = True
            self.app.refresh_tab_titles()
        self.text.edit_modified(False)

    def _on_key_release(self, event) -> None:
        if event.keysym in ("Up", "Down", "Return", "Tab", "Escape"):
            return  # handled by their own bindings
        self._highlight_current_line()
        self._update_current_line_marker()
        self._update_autocomplete()
        self._schedule_diagnostics()

    def _on_cursor_moved(self, _event=None) -> None:
        self._update_current_line_marker()
        self.autocomplete.hide()
        self.app.update_status_bar()

    def _on_arrow_up(self, _event) -> Optional[str]:
        if self.autocomplete.visible:
            self.autocomplete.move_selection(-1)
            return "break"
        return None

    def _on_arrow_down(self, _event) -> Optional[str]:
        if self.autocomplete.visible:
            self.autocomplete.move_selection(1)
            return "break"
        return None

    def _on_escape(self, _event) -> Optional[str]:
        if self.autocomplete.visible:
            self.autocomplete.hide()
            return "break"
        return None

    def _on_return(self, _event) -> Optional[str]:
        if self.autocomplete.visible:
            self.autocomplete.accept_selected()
            return "break"
        line_text, col, _ = self.current_line_and_col()
        indent = re.match(r"[ \t]*", line_text).group()
        opens_block = bool(re.search(
            r"\b(func|struct|record|enum|namespace|if|elif|else|for|while|risk|fix|cleanup)\b\s*$"
            r"|\\\s*$", line_text[:col],
        ))
        extra = "\t" if opens_block else ""
        self.text.insert("insert", "\n" + indent + extra)
        self.after_idle(self._schedule_diagnostics)
        return "break"

    def _on_tab(self, _event) -> Optional[str]:
        if self.autocomplete.visible:
            self.autocomplete.accept_selected()
            return "break"
        return None  # default: insert a literal tab

    def _on_mousewheel(self, event) -> Optional[str]:
        delta = -1 if getattr(event, "num", None) == 4 else (1 if getattr(event, "num", None) == 5 else None)
        if delta is None:
            delta = -1 if event.delta > 0 else 1
        self.text.yview_scroll(delta * 3, "units")
        self._redraw_gutter()
        return "break"

    def _on_ctrl_mousewheel(self, event) -> str:
        self.app.zoom(1 if event.delta > 0 else -1)
        return "break"

    def _on_gutter_click(self, event) -> None:
        index = self.text.index(f"@0,{event.y}")
        line_no = int(index.split(".")[0])
        if event.x < 20:
            self.toggle_bookmark(line_no)
        else:
            self.text.mark_set("insert", f"{line_no}.0")
            self.text.see("insert")
            self.text.focus_set()

    def _on_ruler_click(self, event) -> None:
        total_lines = int(self.text.index("end-1c").split(".")[0])
        if total_lines <= 0:
            return
        height = self.ruler.winfo_height() or 1
        target_line = max(1, min(total_lines, int(event.y / height * total_lines) + 1))
        self.text.mark_set("insert", f"{target_line}.0")
        self.text.see("insert")
        self.text.focus_set()

    def _on_diag_hover(self, event) -> None:
        index = self.text.index(f"@{event.x},{event.y}")
        line_no = int(index.split(".")[0])
        matches = [d for d in self.diagnostics if d.line == line_no]
        if not matches:
            return
        theme = self.app.settings.theme()
        message = "\n".join(f"{d.severity.title()}: {d.message}" for d in matches)
        self.tooltip.show(
            message, self.text.winfo_rootx() + event.x + 12,
            self.text.winfo_rooty() + event.y + 16,
            bg=theme["background"], fg=theme["foreground"],
        )

    def _on_scrollbar(self, *args) -> None:
        self.text.yview(*args)
        self._redraw_gutter()

    def _on_text_yscroll(self, *args) -> None:
        self.vscroll.set(*args)
        self._redraw_gutter()

    # -- syntax highlighting -----------------------------------------------

    def _all_syntax_tags(self) -> list[str]:
        """Every tag tokenize_line() can produce: the fixed categories plus
        whatever custom tags the active highlighting.json rules defined."""
        return list(core.TOKEN_TAGS) + list(self.app.tokenizer.custom_tag_styles)

    def rehighlight_all(self) -> None:
        for tag in self._all_syntax_tags():
            self.text.tag_remove(tag, "1.0", "end")
        lines = self.get_lines()
        ligatures = self.app.active_ligatures()
        for line_index, line in enumerate(lines, start=1):
            for token in self.app.tokenizer.tokenize_line(line):
                start = f"{line_index}.{token.start}"
                end = f"{line_index}.{token.end}"
                self.text.tag_add(token.tag, start, end)
        self._apply_ligature_display(ligatures)
        self._redraw_gutter()
        self._redraw_ruler()

    def _highlight_current_line(self) -> None:
        line_no = int(self.text.index("insert").split(".")[0])
        for tag in self._all_syntax_tags():
            self.text.tag_remove(tag, f"{line_no}.0", f"{line_no}.end")
        line = self.text.get(f"{line_no}.0", f"{line_no}.end")
        for token in self.app.tokenizer.tokenize_line(line):
            self.text.tag_add(token.tag, f"{line_no}.{token.start}", f"{line_no}.{token.end}")

    def _apply_ligature_display(self, ligatures: dict[str, str]) -> None:
        """Visual-only: Tkinter can't substitute display glyphs without
        changing the buffer, so ligatures are shown as a highlighted span
        with a tooltip-free hint via the 'operator' tag's own color; a true
        glyph swap would require editing the stored text, which must never
        happen (see settings: ligatures only affect color emphasis here)."""
        return  # intentionally a no-op placeholder; see docstring

    # -- gutter / overview ruler --------------------------------------------

    def _visible_line_range(self) -> tuple[int, int]:
        first = int(self.text.index("@0,0").split(".")[0])
        last_index = self.text.index(f"@0,{self.text.winfo_height()}")
        last = int(last_index.split(".")[0]) + 1
        return first, last

    def _redraw_gutter(self) -> None:
        self.gutter.delete("all")
        theme = self.app.settings.theme()
        first, last = self._visible_line_range()
        error_lines = {d.line for d in self.diagnostics if d.severity == "error"}
        warning_lines = {d.line for d in self.diagnostics if d.severity == "warning"}
        total_lines = int(self.text.index("end-1c").split(".")[0])
        for line_no in range(first, min(last, total_lines) + 1):
            bbox = self.text.bbox(f"{line_no}.0")
            if not bbox:
                continue
            x, y, _w, h = bbox
            if line_no in self.bookmarks:
                self.gutter.create_oval(4, y + h // 2 - 3, 10, y + h // 2 + 3, fill=theme["bookmark"], outline="")
            color = theme["error"] if line_no in error_lines else (theme["warning"] if line_no in warning_lines else theme["gutter"])
            self.gutter.create_text(self.GUTTER_WIDTH - 6, y, anchor="ne", text=str(line_no), fill=color, font=self.app.editor_font)

    def _redraw_ruler(self) -> None:
        self.ruler.delete("all")
        theme = self.app.settings.theme()
        total_lines = max(1, int(self.text.index("end-1c").split(".")[0]))
        height = self.ruler.winfo_height() or 1
        for diagnostic in self.diagnostics:
            y = int(diagnostic.line / total_lines * height)
            color = theme["error"] if diagnostic.severity == "error" else theme["warning"]
            self.ruler.create_rectangle(2, y, self.RULER_WIDTH - 2, y + 2, fill=color, outline="")

    def _update_current_line_marker(self) -> None:
        self.text.tag_remove("current_line", "1.0", "end")
        line_no = int(self.text.index("insert").split(".")[0])
        self.text.tag_add("current_line", f"{line_no}.0", f"{line_no + 1}.0")

    # -- diagnostics ------------------------------------------------------

    def _schedule_diagnostics(self) -> None:
        if self._diag_job is not None:
            self.after_cancel(self._diag_job)
        self._diag_job = self.after(400, self._run_diagnostics)

    def _run_diagnostics(self) -> None:
        self._diag_job = None
        engine = core.DiagnosticsEngine()
        self.diagnostics = engine.scan(self.path or "", self.get_lines())
        self.text.tag_remove("diag_error", "1.0", "end")
        self.text.tag_remove("diag_warning", "1.0", "end")
        for diagnostic in self.diagnostics:
            start = f"{diagnostic.line}.{max(0, diagnostic.column - 1)}"
            end = f"{diagnostic.line}.{max(0, diagnostic.column - 1) + max(1, diagnostic.length)}"
            tag = "diag_error" if diagnostic.severity == "error" else "diag_warning"
            self.text.tag_add(tag, start, end)
        self._redraw_gutter()
        self._redraw_ruler()
        self.app.refresh_problems_panel()

    # -- autocomplete ------------------------------------------------------

    def _update_autocomplete(self) -> None:
        if not self.app.settings.data.get("autocomplete_enabled", True):
            return
        line_text, col, line_no = self.current_line_and_col()
        previous_lines = self.get_lines()[: line_no - 1]
        matches = self.app.suggestion_engine.suggestions_for(
            self.path or "untitled.cql", line_text, col, previous_lines,
        )
        if not matches:
            self.autocomplete.hide()
            return
        prefix_match = re.search(r"\S*$", line_text[:col])
        self._suggestion_prefix_len = len(prefix_match.group()) if prefix_match else 0
        bbox = self.text.bbox("insert")
        if not bbox:
            self.autocomplete.hide()
            return
        x, y, _w, h = bbox
        root_x = self.text.winfo_rootx() + x
        root_y = self.text.winfo_rooty() + y + h + 2
        theme = self.app.settings.theme()
        self.autocomplete.show(matches, root_x, root_y, theme["background"], theme["foreground"], theme["selection"])

    def _accept_suggestion(self, word: str) -> None:
        line_text, col, line_no = self.current_line_and_col()
        start = col - self._suggestion_prefix_len
        self.text.delete(f"{line_no}.{start}", f"{line_no}.{col}")
        self.text.insert(f"{line_no}.{start}", word)
        self.autocomplete.hide()
        self._highlight_current_line()
        self._schedule_diagnostics()
        self.text.focus_set()

    # -- bookmarks -----------------------------------------------------

    def toggle_bookmark(self, line_no: Optional[int] = None) -> None:
        if line_no is None:
            line_no = int(self.text.index("insert").split(".")[0])
        if line_no in self.bookmarks:
            self.bookmarks.discard(line_no)
        else:
            self.bookmarks.add(line_no)
        self._redraw_gutter()

    def next_bookmark(self, backwards: bool = False) -> None:
        if not self.bookmarks:
            return
        current = int(self.text.index("insert").split(".")[0])
        ordered = sorted(self.bookmarks, reverse=backwards)
        candidates = [n for n in ordered if (n > current if not backwards else n < current)]
        target = candidates[0] if candidates else ordered[0]
        self.text.mark_set("insert", f"{target}.0")
        self.text.see("insert")

    # -- save ------------------------------------------------------------

    def save(self, as_path: Optional[str] = None) -> bool:
        target = as_path or self.path
        if not target:
            target = filedialog.asksaveasfilename(defaultextension=".cql", filetypes=[("ChemQL", "*.cql"), ("All files", "*.*")])
            if not target:
                return False
        if any(
            tab is not self and tab.path and os.path.abspath(tab.path) == os.path.abspath(target)
            for tab in self.app._iter_tabs()
        ):
            messagebox.showerror(APP_TITLE, "That file is already open in another tab.")
            return False
        try:
            Path(target).write_text(self.text.get("1.0", "end-1c"), encoding="utf-8")
        except OSError as error:
            messagebox.showerror(APP_TITLE, f"Could not save {target}:\n{error}")
            return False
        self.path = target
        self.mark_clean()
        self.app.settings.remember_file(target)
        self.app.refresh_recent_files()
        self._schedule_diagnostics()
        return True


# --------------------------------------------------------------------------
# Sidebar: project file tree
# --------------------------------------------------------------------------

class FileTree(ttk.Frame):
    def __init__(self, parent, on_open_file):
        super().__init__(parent)
        self.on_open_file = on_open_file
        self.tree = ttk.Treeview(self, show="tree")
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewOpen>>", self._on_expand)
        self.tree.bind("<Double-1>", self._on_double_click)
        self._path_by_item: dict[str, str] = {}

    def set_root(self, folder: str) -> None:
        self.tree.delete(*self.tree.get_children(""))
        self._path_by_item.clear()
        root_item = self.tree.insert("", "end", text=os.path.basename(folder) or folder, open=True)
        self._path_by_item[root_item] = folder
        self._populate(root_item, folder)

    def _populate(self, item: str, folder: str) -> None:
        try:
            entries = sorted(os.listdir(folder), key=lambda name: (not os.path.isdir(os.path.join(folder, name)), name.lower()))
        except OSError:
            return
        for name in entries:
            if name.startswith("."):
                continue
            full = os.path.join(folder, name)
            node = self.tree.insert(item, "end", text=name, open=False)
            self._path_by_item[node] = full
            if os.path.isdir(full):
                self.tree.insert(node, "end", text="")  # placeholder so the expand arrow shows

    def _on_expand(self, _event) -> None:
        item = self.tree.focus()
        children = self.tree.get_children(item)
        if len(children) == 1 and self.tree.item(children[0], "text") == "" and self._path_by_item.get(children[0]) is None:
            self.tree.delete(children[0])
            self._populate(item, self._path_by_item[item])

    def _on_double_click(self, _event) -> None:
        item = self.tree.focus()
        path = self._path_by_item.get(item)
        if path and os.path.isfile(path):
            self.on_open_file(path)


# --------------------------------------------------------------------------
# Bottom panel: Problems / Console / Query Console
# --------------------------------------------------------------------------

class ProblemsPanel(ttk.Frame):
    def __init__(self, parent, on_jump):
        super().__init__(parent)
        self.on_jump = on_jump
        columns = ("severity", "line", "message")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="browse")
        for column, width in (("severity", 70), ("line", 50), ("message", 600)):
            self.tree.heading(column, text=column.title())
            self.tree.column(column, width=width, anchor="w")
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.tag_configure("error", foreground="#f14c4c")
        self.tree.tag_configure("warning", foreground="#cca700")

    def set_diagnostics(self, diagnostics: list[core.Diagnostic]) -> None:
        self.tree.delete(*self.tree.get_children(""))
        for diagnostic in diagnostics:
            self.tree.insert(
                "", "end", values=(diagnostic.severity, diagnostic.line, diagnostic.message),
                tags=(diagnostic.severity,),
            )

    def _on_double_click(self, _event) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        values = self.tree.item(selection[0], "values")
        self.on_jump(int(values[1]))


class ConsolePanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.text = tk.Text(self, height=8, state="disabled", wrap="word", font=("TkFixedFont", 10))
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.text.tag_configure("stderr", foreground="#f14c4c")

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def append(self, text: str, stderr: bool = False) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", text, ("stderr",) if stderr else ())
        self.text.see("end")
        self.text.configure(state="disabled")


class QueryConsolePanel(ttk.Frame):
    def __init__(self, parent, bridge: core.ChemQLBridge):
        super().__init__(parent)
        self.bridge = bridge
        bar = ttk.Frame(self)
        bar.pack(side="top", fill="x")
        ttk.Label(bar, text="ChemQL>").pack(side="left", padx=(4, 4))
        self.entry = ttk.Entry(bar, font=("TkFixedFont", 10))
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 4), pady=3)
        self.entry.bind("<Return>", lambda _e: self.run())
        ttk.Button(bar, text="Run", command=self.run).pack(side="left", padx=(0, 4))

        self.result_area = ttk.Frame(self)
        self.result_area.pack(side="top", fill="both", expand=True)
        self.table = ttk.Treeview(self.result_area, show="headings")
        self.table_scroll = ttk.Scrollbar(self.result_area, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=self.table_scroll.set)
        self.text_result = tk.Text(self.result_area, wrap="word", height=6, state="disabled", font=("TkFixedFont", 10))

        if not bridge.available:
            self.entry.configure(state="disabled")
            self._show_text("chemql is not installed in this Python environment, so the query "
                             "console is disabled. Install chemql-python to enable it.")

    def run(self) -> None:
        if not self.bridge.available:
            return
        text = self.entry.get().strip()
        if not text:
            return
        ok, payload = self.bridge.run_query(text)
        if isinstance(payload, core.TableResult):
            self._show_table(payload)
        elif isinstance(payload, core.CardResult):
            body = payload.raw if not payload.fields else "\n".join(f"{k}: {v}" for k, v in payload.fields)
            self._show_text((f"{payload.title}\n" + "-" * len(payload.title) + "\n" if payload.fields else "") + body)
        else:
            self._show_text(str(payload))

    def run_text(self, text: str) -> None:
        self.entry.delete(0, "end")
        self.entry.insert(0, text)
        self.run()

    def _show_table(self, table: core.TableResult) -> None:
        self.text_result.pack_forget()
        self.table["columns"] = table.columns
        for column in table.columns:
            self.table.heading(column, text=column, command=lambda c=column: self._sort_table(c, False))
            self.table.column(column, width=120, anchor="w")
        self.table.delete(*self.table.get_children(""))
        for row in table.rows:
            self.table.insert("", "end", values=row)
        self.table.pack(side="left", fill="both", expand=True)
        self.table_scroll.pack(side="right", fill="y")

    def _sort_table(self, column: str, descending: bool) -> None:
        items = [(self.table.set(item, column), item) for item in self.table.get_children("")]
        try:
            items.sort(key=lambda pair: float(pair[0]), reverse=descending)
        except ValueError:
            items.sort(key=lambda pair: pair[0].lower(), reverse=descending)
        for index, (_value, item) in enumerate(items):
            self.table.move(item, "", index)
        self.table.heading(column, command=lambda: self._sort_table(column, not descending))

    def _show_text(self, text: str) -> None:
        self.table.pack_forget()
        self.table_scroll.pack_forget()
        self.text_result.configure(state="normal")
        self.text_result.delete("1.0", "end")
        self.text_result.insert("1.0", text)
        self.text_result.configure(state="disabled")
        self.text_result.pack(side="left", fill="both", expand=True)


# --------------------------------------------------------------------------
# Right panel: periodic table + reaction balancer
# --------------------------------------------------------------------------

class PeriodicTablePanel(ttk.Frame):
    CELL = 30

    def __init__(self, parent, bridge: core.ChemQLBridge, on_pick):
        super().__init__(parent)
        self.bridge = bridge
        self.on_pick = on_pick
        self.canvas = tk.Canvas(self, width=18 * self.CELL, height=10 * self.CELL, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.tooltip = Tooltip(self)
        self._cells: dict[int, dict] = {}
        if bridge.available:
            self._draw()
        else:
            self.canvas.create_text(10, 10, anchor="nw", text="chemql not installed", fill="gray")

    _CATEGORY_COLORS = {
        "diatomic nonmetal": "#8fd3fe", "noble gas": "#c9a0ff", "alkali metal": "#ff9e9e",
        "alkaline earth metal": "#ffc08a", "metalloid": "#bfe3b4", "polyatomic nonmetal": "#8fd3fe",
        "post-transition metal": "#d6d6d6", "transition metal": "#f7e08a", "lanthanide": "#ffb3d9",
        "actinide": "#ffb3f0",
    }

    def _draw(self) -> None:
        elements = self.bridge.elements() or []
        for element in elements:
            period, group = element.get("period") or 0, element.get("group") or 0
            if not period or not group:
                continue
            x, y = (group - 1) * self.CELL, (period - 1) * self.CELL
            color = self._CATEGORY_COLORS.get(element.get("category", ""), "#e0e0e0")
            rect = self.canvas.create_rectangle(x, y, x + self.CELL - 2, y + self.CELL - 2, fill=color, outline="#888")
            text = self.canvas.create_text(x + self.CELL // 2 - 1, y + self.CELL // 2 - 1, text=element["symbol"], font=("TkFixedFont", 9, "bold"))
            for item in (rect, text):
                self._cells[item] = element
                self.canvas.tag_bind(item, "<Enter>", self._on_enter)
                self.canvas.tag_bind(item, "<Leave>", lambda _e: self.tooltip.hide())
                self.canvas.tag_bind(item, "<Button-1>", self._on_click)

    def _on_enter(self, event) -> None:
        item = self.canvas.find_closest(event.x, event.y)[0]
        element = self._cells.get(item)
        if not element:
            return
        mass = element.get("atomic_mass")
        mass_text = f"{mass:.3f}" if isinstance(mass, (int, float)) else "?"
        text = f"{element['name']} ({element['symbol']})\n#{element['number']}  mass {mass_text}"
        self.tooltip.show(text, self.winfo_rootx() + event.x + 12, self.winfo_rooty() + event.y + 12, "#ffffe0", "#000000")

    def _on_click(self, event) -> None:
        item = self.canvas.find_closest(event.x, event.y)[0]
        element = self._cells.get(item)
        if element:
            self.on_pick(element["symbol"])


class BalancerPanel(ttk.Frame):
    def __init__(self, parent, bridge: core.ChemQLBridge):
        super().__init__(parent)
        self.bridge = bridge
        ttk.Label(self, text="Reactants (+ separated):").grid(row=0, column=0, sticky="w", padx=4, pady=(6, 0))
        self.reactants = ttk.Entry(self)
        self.reactants.grid(row=1, column=0, sticky="ew", padx=4)
        ttk.Label(self, text="Products (+ separated):").grid(row=2, column=0, sticky="w", padx=4, pady=(6, 0))
        self.products = ttk.Entry(self)
        self.products.grid(row=3, column=0, sticky="ew", padx=4)
        ttk.Button(self, text="Balance", command=self.balance).grid(row=4, column=0, sticky="ew", padx=4, pady=6)
        self.result = tk.Text(self, height=4, wrap="word", state="disabled", font=("TkFixedFont", 11))
        self.result.grid(row=5, column=0, sticky="nsew", padx=4, pady=(0, 6))
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)
        self.result.tag_configure("error", foreground="#f14c4c")
        if not bridge.available:
            for widget in (self.reactants, self.products):
                widget.configure(state="disabled")

    def balance(self) -> None:
        if not self.bridge.available:
            return
        reactants = [part.strip() for part in self.reactants.get().split("+") if part.strip()]
        products = [part.strip() for part in self.products.get().split("+") if part.strip()]
        if not reactants or not products:
            return
        ok, message = self.bridge.balance(" + ".join(reactants), " + ".join(products))
        self.result.configure(state="normal")
        self.result.delete("1.0", "end")
        self.result.insert("1.0", message, () if ok else ("error",))
        self.result.configure(state="disabled")


# --------------------------------------------------------------------------
# Dialogs
# --------------------------------------------------------------------------

class PreferencesDialog(tk.Toplevel):
    COLOR_KEYS = ["background", "foreground", "comment", "string", "keyword", "command", "error", "warning"]

    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("Preferences")
        self.resizable(False, False)
        self.transient(app)

        settings = app.settings
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        general = ttk.Frame(notebook)
        notebook.add(general, text="General")
        self.theme_var = tk.StringVar(value=settings.data.get("theme", "dark"))
        ttk.Label(general, text="Theme:").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Radiobutton(general, text="Dark", variable=self.theme_var, value="dark").grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(general, text="Light", variable=self.theme_var, value="light").grid(row=0, column=2, sticky="w")

        ttk.Label(general, text="Font family:").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        self.font_family_var = tk.StringVar(value=settings.data.get("font_family", ""))
        ttk.Entry(general, textvariable=self.font_family_var, width=24).grid(row=1, column=1, columnspan=2, sticky="w")

        ttk.Label(general, text="Font size:").grid(row=2, column=0, sticky="w", padx=6, pady=6)
        self.font_size_var = tk.IntVar(value=settings.data.get("font_size", 13))
        ttk.Spinbox(general, from_=8, to=32, textvariable=self.font_size_var, width=5).grid(row=2, column=1, sticky="w")

        self.ligatures_var = tk.BooleanVar(value=settings.data.get("ligatures_enabled", True))
        ttk.Checkbutton(general, text="Highlight comparison operators (>=, <=, ...) distinctly",
                         variable=self.ligatures_var).grid(row=3, column=0, columnspan=3, sticky="w", padx=6, pady=(10, 2))
        self.autocomplete_var = tk.BooleanVar(value=settings.data.get("autocomplete_enabled", True))
        ttk.Checkbutton(general, text="Autocomplete suggestions", variable=self.autocomplete_var).grid(
            row=4, column=0, columnspan=3, sticky="w", padx=6)
        self.minimap_var = tk.BooleanVar(value=settings.data.get("show_minimap", True))
        ttk.Checkbutton(general, text="Show overview ruler", variable=self.minimap_var).grid(
            row=5, column=0, columnspan=3, sticky="w", padx=6)

        colors = ttk.Frame(notebook)
        notebook.add(colors, text="Colors")
        self.color_vars: dict[str, tk.StringVar] = {}
        theme = settings.theme()
        for row, key in enumerate(self.COLOR_KEYS):
            ttk.Label(colors, text=key.replace("_", " ").title() + ":").grid(row=row, column=0, sticky="w", padx=6, pady=3)
            var = tk.StringVar(value=settings.data.get("colors", {}).get(key, theme[key]))
            self.color_vars[key] = var
            swatch = tk.Label(colors, textvariable=var, width=10, relief="solid", borderwidth=1)
            swatch.grid(row=row, column=1, padx=6)
            swatch.configure(bg=var.get())
            var.trace_add("write", lambda *_a, w=swatch, v=var: w.configure(bg=v.get()))
            ttk.Button(colors, text="Pick...", command=lambda v=var: self._pick_color(v)).grid(row=row, column=2, padx=6)
        ttk.Button(colors, text="Reset to theme defaults", command=self._reset_colors).grid(
            row=len(self.COLOR_KEYS), column=0, columnspan=3, pady=8)

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Apply", command=self._apply).pack(side="right", padx=6)

    def _pick_color(self, var: tk.StringVar) -> None:
        _rgb, hex_color = colorchooser.askcolor(color=var.get(), parent=self)
        if hex_color:
            var.set(hex_color)

    def _reset_colors(self) -> None:
        theme = core.DARK_THEME if self.theme_var.get() == "dark" else core.LIGHT_THEME
        for key, var in self.color_vars.items():
            var.set(theme[key])

    def _apply(self) -> None:
        settings = self.app.settings
        settings.data["theme"] = self.theme_var.get()
        settings.data["font_family"] = self.font_family_var.get() or settings.data["font_family"]
        settings.data["font_size"] = max(8, self.font_size_var.get())
        settings.data["ligatures_enabled"] = self.ligatures_var.get()
        settings.data["autocomplete_enabled"] = self.autocomplete_var.get()
        settings.data["show_minimap"] = self.minimap_var.get()
        settings.data["colors"] = {key: var.get() for key, var in self.color_vars.items()}
        settings.save()
        self.app.apply_theme()
        self.destroy()


class FindReplaceDialog(tk.Toplevel):
    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("Find & Replace")
        self.resizable(False, False)
        self.transient(app)

        ttk.Label(self, text="Find:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.find_entry = ttk.Entry(self, width=36)
        self.find_entry.grid(row=0, column=1, columnspan=3, sticky="ew", padx=6)
        ttk.Label(self, text="Replace:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.replace_entry = ttk.Entry(self, width=36)
        self.replace_entry.grid(row=1, column=1, columnspan=3, sticky="ew", padx=6)

        self.regex_var = tk.BooleanVar(value=False)
        self.case_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="Regex", variable=self.regex_var).grid(row=2, column=1, sticky="w", padx=6)
        ttk.Checkbutton(self, text="Case sensitive", variable=self.case_var).grid(row=2, column=2, sticky="w")

        buttons = ttk.Frame(self)
        buttons.grid(row=3, column=0, columnspan=4, pady=8)
        ttk.Button(buttons, text="Find Next", command=self.find_next).pack(side="left", padx=4)
        ttk.Button(buttons, text="Replace", command=self.replace_one).pack(side="left", padx=4)
        ttk.Button(buttons, text="Replace All", command=self.replace_all).pack(side="left", padx=4)
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="left", padx=4)
        self.find_entry.focus_set()
        self.bind("<Return>", lambda _e: self.find_next())
        self.bind("<Escape>", lambda _e: self.destroy())

        self._last_match_end = "1.0"

    def _tab(self) -> Optional[EditorTab]:
        return self.app.current_tab()

    def find_next(self) -> None:
        tab = self._tab()
        if tab is None:
            return
        pattern = self.find_entry.get()
        if not pattern:
            return
        text = tab.text
        text.tag_remove("find_match", "1.0", "end")
        start = text.index("insert")
        position = text.search(pattern, start, stopindex="end", regexp=self.regex_var.get(), nocase=not self.case_var.get())
        if not position:
            position = text.search(pattern, "1.0", stopindex="end", regexp=self.regex_var.get(), nocase=not self.case_var.get())
            if not position:
                messagebox.showinfo(APP_TITLE, "No matches found.", parent=self)
                return
        length_var = tk.IntVar()
        text.search(pattern, position, stopindex="end", regexp=self.regex_var.get(),
                    nocase=not self.case_var.get(), count=length_var)
        end = f"{position}+{max(1, length_var.get())}c"
        text.tag_add("find_match", position, end)
        text.mark_set("insert", end)
        text.see(position)
        self._last_match_end = end

    def replace_one(self) -> None:
        tab = self._tab()
        if tab is None:
            return
        ranges = tab.text.tag_ranges("find_match")
        if ranges:
            tab.text.delete(ranges[0], ranges[1])
            tab.text.insert(ranges[0], self.replace_entry.get())
        self.find_next()

    def replace_all(self) -> None:
        tab = self._tab()
        if tab is None:
            return
        pattern, replacement = self.find_entry.get(), self.replace_entry.get()
        if not pattern:
            return
        flags = 0 if self.case_var.get() else re.IGNORECASE
        content = tab.text.get("1.0", "end-1c")
        try:
            new_content, count = (re.subn(pattern, replacement, content, flags=flags)
                                   if self.regex_var.get()
                                   else re.subn(re.escape(pattern), replacement.replace("\\", "\\\\"), content, flags=flags))
        except re.error as error:
            messagebox.showerror(APP_TITLE, f"Invalid regex: {error}", parent=self)
            return
        if count:
            tab.text.delete("1.0", "end")
            tab.text.insert("1.0", new_content)
            tab.rehighlight_all()
            tab._schedule_diagnostics()
        messagebox.showinfo(APP_TITLE, f"Replaced {count} occurrence(s).", parent=self)


# --------------------------------------------------------------------------
# Main application
# --------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self, initial_paths: list[str]):
        super().__init__()
        self.title(APP_TITLE)
        self.iconphoto(True, tk.PhotoImage(file=APP_ICON))
        try:
            # Works on Windows and macOS
            self.state('zoomed')
        except tk.TclError:
            # Fallback for Linux / X11
            self.attributes('-zoomed', True)

        self.settings = core.Settings()
        self.suggestion_engine = core.default_suggestion_engine()
        self.tokenizer = core.tokenizer_for(self.suggestion_engine, ".cql")
        self.bridge = core.ChemQLBridge()
        self.editor_font = (_pick_font_family(self.settings.data["font_family"]), self.settings.data["font_size"])

        self._run_proc = None
        self._run_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()

        self._build_menu()
        self._build_layout()
        self._bind_shortcuts()
        self.apply_theme()

        for path in initial_paths:
            if os.path.isdir(path):
                self.open_folder(path)
            elif os.path.isfile(path):
                self.open_file(path)
        if not self._iter_tabs():
            self.new_file()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._poll_run_queue)

    # -- layout --------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        self.configure(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="New File", command=self.new_file, accelerator="Ctrl+N")
        file_menu.add_command(label="Open File...", command=self.open_file_dialog, accelerator="Ctrl+O")
        file_menu.add_command(label="Open File in Other Pane...", command=self.open_file_in_other_pane)
        file_menu.add_command(label="Open Folder...", command=self.open_folder_dialog, accelerator="Ctrl+Shift+O")
        self.recent_files_menu = tk.Menu(file_menu, tearoff=False)
        self.recent_files_menu.configure(postcommand=self.refresh_recent_files)
        file_menu.add_cascade(label="Recent Files", menu=self.recent_files_menu)
        file_menu.add_separator()
        file_menu.add_command(label="Save", command=self.save_current, accelerator="Ctrl+S")
        file_menu.add_command(label="Save As...", command=self.save_current_as, accelerator="Ctrl+Shift+S")
        file_menu.add_separator()
        file_menu.add_command(label="Close Tab", command=self.close_current_tab, accelerator="Ctrl+W")
        file_menu.add_command(label="Preferences...", command=lambda: PreferencesDialog(self))
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=False)
        edit_menu.add_command(label="Undo", command=lambda: self._text_event("<<Undo>>"), accelerator="Ctrl+Z")
        edit_menu.add_command(label="Redo", command=lambda: self._text_event("<<Redo>>"), accelerator="Ctrl+Y")
        edit_menu.add_separator()
        edit_menu.add_command(label="Cut", command=lambda: self._text_event("<<Cut>>"))
        edit_menu.add_command(label="Copy", command=lambda: self._text_event("<<Copy>>"))
        edit_menu.add_command(label="Paste", command=lambda: self._text_event("<<Paste>>"))
        edit_menu.add_separator()
        edit_menu.add_command(label="Find & Replace...", command=lambda: FindReplaceDialog(self), accelerator="Ctrl+F")
        edit_menu.add_command(label="Toggle Bookmark", command=self._toggle_bookmark, accelerator="Ctrl+F2")
        edit_menu.add_command(label="Next Bookmark", command=lambda: self._jump_bookmark(False), accelerator="F2")
        edit_menu.add_command(label="Previous Bookmark", command=lambda: self._jump_bookmark(True), accelerator="Shift+F2")
        menubar.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        self.show_sidebar_var = tk.BooleanVar(value=True)
        self.show_right_var = tk.BooleanVar(value=True)
        self.show_bottom_var = tk.BooleanVar(value=True)
        self.split_editor_var = tk.BooleanVar(value=False)
        view_menu.add_checkbutton(label="File Tree", variable=self.show_sidebar_var, command=self._toggle_sidebar)
        view_menu.add_checkbutton(label="Chemistry Panel", variable=self.show_right_var, command=self._toggle_right_panel)
        view_menu.add_checkbutton(label="Bottom Panel", variable=self.show_bottom_var, command=self._toggle_bottom_panel)
        view_menu.add_checkbutton(label="Split Editor", variable=self.split_editor_var, command=self._toggle_split_editor)
        view_menu.add_separator()
        view_menu.add_command(label="Zoom In", command=lambda: self.zoom(1), accelerator="Ctrl+=")
        view_menu.add_command(label="Zoom Out", command=lambda: self.zoom(-1), accelerator="Ctrl+-")
        view_menu.add_command(label="Reset Zoom", command=lambda: self.zoom(0, reset=True), accelerator="Ctrl+0")
        menubar.add_cascade(label="View", menu=view_menu)

        run_menu = tk.Menu(menubar, tearoff=False)
        run_menu.add_command(label="Run File", command=self.run_current_file, accelerator="Ctrl+R")
        run_menu.add_command(label="Run Selection", command=self.run_selection, accelerator="Ctrl+Shift+R")
        run_menu.add_command(label="Stop", command=self.stop_run)
        menubar.add_cascade(label="Run", menu=run_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="Keyboard Shortcuts", command=self._show_shortcuts)
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

    def _build_layout(self) -> None:
        self.main_pane = ttk.PanedWindow(self, orient="horizontal")
        self.main_pane.pack(fill="both", expand=True)

        self.sidebar = FileTree(self.main_pane, self.open_file)
        self.main_pane.add(self.sidebar, weight=1)

        center = ttk.Frame(self.main_pane)
        self.main_pane.add(center, weight=5)
        self.center_pane = ttk.PanedWindow(center, orient="vertical")
        self.center_pane.pack(fill="both", expand=True)

        self.editor_pane = ttk.PanedWindow(self.center_pane, orient="horizontal")
        self.center_pane.add(self.editor_pane, weight=4)
        self.notebook = ttk.Notebook(self.editor_pane)
        self.secondary_notebook = ttk.Notebook(self.editor_pane)
        self._active_notebook = self.notebook
        self._bind_editor_notebook(self.notebook)
        self._bind_editor_notebook(self.secondary_notebook)
        self.editor_pane.add(self.notebook, weight=1)

        self.bottom_notebook = ttk.Notebook(self.center_pane)
        self.center_pane.add(self.bottom_notebook, weight=1)
        self.problems_panel = ProblemsPanel(self.bottom_notebook, self._jump_to_line)
        self.console_panel = ConsolePanel(self.bottom_notebook)
        self.query_panel = QueryConsolePanel(self.bottom_notebook, self.bridge)
        self.bottom_notebook.add(self.problems_panel, text="Problems")
        self.bottom_notebook.add(self.console_panel, text="Console")
        self.bottom_notebook.add(self.query_panel, text="Query Console")

        right = ttk.Notebook(self.main_pane)
        self.main_pane.add(right, weight=2)
        self.periodic_panel = PeriodicTablePanel(right, self.bridge, self._insert_element_lookup)
        self.balancer_panel = BalancerPanel(right, self.bridge)
        right.add(self.periodic_panel, text="Periodic Table")
        right.add(self.balancer_panel, text="Balance Equation")
        self.right_notebook = right

        self.status = ttk.Frame(self)
        self.status.pack(fill="x", side="bottom")
        self.status_position = ttk.Label(self.status, text="Ln 1, Col 1")
        self.status_position.pack(side="left", padx=8)
        self.status_chemql = ttk.Label(
            self.status,
            text="chemql: available" if self.bridge.available else "chemql: not installed",
        )
        self.status_chemql.pack(side="right", padx=8)

    def _bind_shortcuts(self) -> None:
        self.bind_all("<Control-n>", lambda _e: self.new_file())
        self.bind_all("<Control-o>", lambda _e: self.open_file_dialog())
        self.bind_all("<Control-Shift-O>", lambda _e: self.open_folder_dialog())
        self.bind_all("<Control-s>", lambda _e: self.save_current())
        self.bind_all("<Control-Shift-S>", lambda _e: self.save_current_as())
        self.bind_all("<Control-w>", lambda _e: self.close_current_tab())
        self.bind_all("<Control-f>", lambda _e: FindReplaceDialog(self))
        self.bind_all("<Control-r>", lambda _e: self.run_current_file())
        self.bind_all("<Control-Shift-R>", lambda _e: self.run_selection())
        self.bind_all("<F2>", lambda _e: self._jump_bookmark(False))
        self.bind_all("<Shift-F2>", lambda _e: self._jump_bookmark(True))
        self.bind_all("<Control-F2>", lambda _e: self._toggle_bookmark())
        self.bind_all("<Control-equal>", lambda _e: self.zoom(1))
        self.bind_all("<Control-plus>", lambda _e: self.zoom(1))
        self.bind_all("<Control-minus>", lambda _e: self.zoom(-1))
        self.bind_all("<Control-0>", lambda _e: self.zoom(0, reset=True))

    # -- tab management -----------------------------------------------------

    def _bind_editor_notebook(self, notebook: ttk.Notebook) -> None:
        notebook.bind(
            "<<NotebookTabChanged>>",
            lambda _event, pane=notebook: self.set_active_notebook(pane),
        )
        notebook.bind(
            "<Button-1>",
            lambda _event, pane=notebook: self.set_active_notebook(pane),
            add="+",
        )

    def set_active_notebook(self, notebook: ttk.Notebook) -> None:
        self._active_notebook = notebook
        self.update_status_bar()
        self.refresh_problems_panel()

    def _iter_tabs(self):
        for notebook in (self.notebook, self.secondary_notebook):
            for tab_id in notebook.tabs():
                yield notebook.nametowidget(tab_id)

    def current_tab(self) -> Optional[EditorTab]:
        for notebook in (self._active_notebook, self.notebook, self.secondary_notebook):
            selected = notebook.select()
            if selected:
                return notebook.nametowidget(selected)
        return None

    def new_file(self, in_other_pane: bool = False) -> None:
        notebook = self.secondary_notebook if in_other_pane else self._active_notebook
        if in_other_pane:
            self.split_editor_var.set(True)
            self._toggle_split_editor()
        tab = EditorTab(notebook, self, None)
        notebook.add(tab, text=tab.display_name)
        notebook.select(tab)
        self.set_active_notebook(notebook)

    def open_file(self, path: str, in_other_pane: bool = False) -> None:
        path = os.path.abspath(path)
        for notebook in (self.notebook, self.secondary_notebook):
            for tab_id in notebook.tabs():
                tab = notebook.nametowidget(tab_id)
                if tab.path and os.path.abspath(tab.path) == path:
                    notebook.select(tab)
                    self.set_active_notebook(notebook)
                    return
        notebook = self.secondary_notebook if in_other_pane else self._active_notebook
        if in_other_pane:
            self.split_editor_var.set(True)
            self._toggle_split_editor()
        tab = EditorTab(notebook, self, path)
        notebook.add(tab, text=tab.display_name)
        notebook.select(tab)
        self.set_active_notebook(notebook)
        self.settings.remember_file(path)
        self.refresh_recent_files()

    def open_file_in_other_pane(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("ChemQL", "*.cql"), ("All files", "*.*")])
        if path:
            self.open_file(path, in_other_pane=True)

    def open_recent_file(self, path: str) -> None:
        if not os.path.isfile(path):
            recent_files = self.settings.data.get("recent_files", [])
            if not isinstance(recent_files, list):
                recent_files = []
            self.settings.data["recent_files"] = [item for item in recent_files if item != path]
            self.settings.save()
            self.refresh_recent_files()
            messagebox.showerror(APP_TITLE, f"Recent file no longer exists:\n{path}")
            return
        self.open_file(path)

    def refresh_recent_files(self) -> None:
        menu = self.recent_files_menu
        menu.delete(0, "end")
        recent_files = self.settings.data.get("recent_files", [])
        if not isinstance(recent_files, list):
            recent_files = []
        valid_files = [path for path in recent_files if isinstance(path, str)]
        if not valid_files:
            menu.add_command(label="No recent files", state="disabled")
            return
        for path in valid_files[:12]:
            label = f"{Path(path).name} - {Path(path).parent}"
            menu.add_command(label=label, command=lambda item=path: self.open_recent_file(item))

    def open_file_dialog(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("ChemQL", "*.cql"), ("All files", "*.*")])
        if path:
            self.open_file(path)

    def open_folder_dialog(self) -> None:
        folder = filedialog.askdirectory()
        if folder:
            self.open_folder(folder)

    def open_folder(self, folder: str) -> None:
        self.sidebar.set_root(folder)
        self.settings.remember_folder(folder)
        self.show_sidebar_var.set(True)
        self._toggle_sidebar()

    def close_current_tab(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        notebook = tab.master
        if tab.dirty:
            answer = messagebox.askyesnocancel(APP_TITLE, f"Save changes to {tab.display_name.lstrip('* ')}?")
            if answer is None:
                return
            if answer and not tab.save():
                return
        notebook.forget(tab)
        if notebook is self.secondary_notebook and not notebook.tabs():
            self.split_editor_var.set(False)
            self._toggle_split_editor()
            self.set_active_notebook(self.notebook)
            if not self.notebook.tabs():
                self.new_file()
        elif notebook is self.notebook and not notebook.tabs() and not self.secondary_notebook.tabs():
            self.new_file()

    def refresh_tab_titles(self) -> None:
        for notebook in (self.notebook, self.secondary_notebook):
            for tab_id in notebook.tabs():
                tab = notebook.nametowidget(tab_id)
                notebook.tab(tab_id, text=tab.display_name)

    def save_current(self) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.save()

    def save_current_as(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        kwargs = {
            "defaultextension": ".cql",
            "initialfile": os.path.basename(tab.path) if tab.path else "untitled.cql",
            "filetypes": [("ChemQL", "*.cql"), ("All files", "*.*")],
        }
        if tab.path:
            kwargs["initialdir"] = os.path.dirname(tab.path)
        new_path = filedialog.asksaveasfilename(**kwargs)
        if new_path:
            tab.save(as_path=new_path)

    def on_close(self) -> None:
        for notebook in (self.notebook, self.secondary_notebook):
            for tab_id in notebook.tabs():
                tab = notebook.nametowidget(tab_id)
                if tab.dirty:
                    notebook.select(tab)
                    self.set_active_notebook(notebook)
                    answer = messagebox.askyesnocancel(APP_TITLE, f"Save changes to {tab.display_name.lstrip('* ')}?")
                    if answer is None:
                        return
                    if answer and not tab.save():
                        return
        self.settings.save()
        self.destroy()


    # -- theming -----------------------------------------------------------

    def apply_theme(self) -> None:
        self.editor_font = (_pick_font_family(self.settings.data["font_family"]), self.settings.data["font_size"])
        for tab in self._iter_tabs():
            tab._configure_tags()
            tab.rehighlight_all()

    def active_ligatures(self) -> dict[str, str]:
        return core.DEFAULT_LIGATURES if self.settings.data.get("ligatures_enabled", True) else {}

    def zoom(self, delta: int, reset: bool = False) -> None:
        size = 13 if reset else max(8, min(32, self.settings.data["font_size"] + delta))
        self.settings.data["font_size"] = size
        self.apply_theme()

    # -- panel toggles -----------------------------------------------------

    def _toggle_sidebar(self) -> None:
        panes = self.main_pane.panes()
        if self.show_sidebar_var.get():
            if str(self.sidebar) not in panes:
                self.main_pane.insert(0, self.sidebar, weight=1)
        else:
            if str(self.sidebar) in panes:
                self.main_pane.forget(self.sidebar)

    def _toggle_right_panel(self) -> None:
        panes = self.main_pane.panes()
        if self.show_right_var.get():
            if str(self.right_notebook) not in panes:
                self.main_pane.add(self.right_notebook, weight=2)
        else:
            if str(self.right_notebook) in panes:
                self.main_pane.forget(self.right_notebook)

    def _toggle_bottom_panel(self) -> None:
        panes = self.center_pane.panes()
        if self.show_bottom_var.get():
            if str(self.bottom_notebook) not in panes:
                self.center_pane.add(self.bottom_notebook, weight=1)
        else:
            if str(self.bottom_notebook) in panes:
                self.center_pane.forget(self.bottom_notebook)

    def _toggle_split_editor(self) -> None:
        panes = self.editor_pane.panes()
        if self.split_editor_var.get():
            if str(self.secondary_notebook) not in panes:
                self.editor_pane.add(self.secondary_notebook, weight=1)
        elif self.secondary_notebook.tabs():
            self.split_editor_var.set(True)
            messagebox.showinfo(
                APP_TITLE,
                "Close the tabs in the other pane before turning split view off.",
            )
        elif str(self.secondary_notebook) in panes:
            self.editor_pane.forget(self.secondary_notebook)
            self.set_active_notebook(self.notebook)

    # -- status bar / problems ----------------------------------------------

    def update_status_bar(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        line, col = tab.text.index("insert").split(".")
        self.status_position.configure(text=f"Ln {line}, Col {int(col) + 1}")

    def refresh_problems_panel(self) -> None:
        tab = self.current_tab()
        self.problems_panel.set_diagnostics(tab.diagnostics if tab else [])

    def _jump_to_line(self, line_no: int) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        tab.text.mark_set("insert", f"{line_no}.0")
        tab.text.see("insert")
        tab.text.focus_set()

    # -- bookmarks -----------------------------------------------------

    def _toggle_bookmark(self) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.toggle_bookmark()

    def _jump_bookmark(self, backwards: bool) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.next_bookmark(backwards)

    # -- editing passthroughs -------------------------------------------

    def _text_event(self, event_name: str) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.text.event_generate(event_name)

    # -- running -----------------------------------------------------------

    def run_current_file(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        if tab.dirty and not tab.save():
            return
        run_command = self.suggestion_engine.get_run_command(tab.path)
        if not run_command:
            messagebox.showwarning(APP_TITLE, "No run command configured for this file type.")
            return
        self._start_run(core.build_run_command(run_command, os.path.abspath(tab.path)), cwd=os.path.dirname(tab.path))

    def run_selection(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        try:
            selected = tab.text.get("sel.first", "sel.last")
        except tk.TclError:
            messagebox.showinfo(APP_TITLE, "Select some ChemQL code first.")
            return
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".cql", delete=False, encoding="utf-8") as handle:
            handle.write(selected)
            temp_path = handle.name
        run_command = self.suggestion_engine.get_run_command(temp_path) or "chemql -f $absoluteName"
        self._start_run(core.build_run_command(run_command, temp_path), cwd=os.path.dirname(tab.path) if tab.path else None)

    def _start_run(self, argv: list[str], cwd: Optional[str]) -> None:
        if self._run_proc is not None and self._run_proc.poll() is None:
            messagebox.showinfo(APP_TITLE, "A run is already in progress. Stop it first.")
            return
        import subprocess
        self.console_panel.clear()
        self.bottom_notebook.select(self.console_panel)
        try:
            self._run_proc = subprocess.Popen(
                argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
        except OSError as error:
            self.console_panel.append(f"Could not start: {error}\n", stderr=True)
            return
        threading.Thread(target=self._pump_stream, args=(self._run_proc.stdout, False), daemon=True).start()
        threading.Thread(target=self._pump_stream, args=(self._run_proc.stderr, True), daemon=True).start()

    def _pump_stream(self, stream, is_stderr: bool) -> None:
        for line in iter(stream.readline, ""):
            self._run_queue.put((line, "stderr" if is_stderr else "stdout"))
        stream.close()

    def _poll_run_queue(self) -> None:
        try:
            while True:
                line, kind = self._run_queue.get_nowait()
                self.console_panel.append(line, stderr=(kind == "stderr"))
        except queue.Empty:
            pass
        self.after(100, self._poll_run_queue)

    def stop_run(self) -> None:
        if self._run_proc is not None and self._run_proc.poll() is None:
            self._run_proc.terminate()
            self.console_panel.append("\n[stopped]\n", stderr=True)

    # -- chemistry panel hooks ----------------------------------------------

    def _insert_element_lookup(self, symbol: str) -> None:
        self.bottom_notebook.select(self.query_panel)
        self.query_panel.run_text(f'findel "{symbol}"')

    # -- help ------------------------------------------------------------

    def _show_shortcuts(self) -> None:
        shortcuts = f"""Ctrl+N{" "*26}New file
Ctrl+O{" "*26}Open file
Ctrl+Shift+O{" "*16}Open folder
Ctrl+S{" "*27}Save
Ctrl+Shift+S{" "*17}Save as
Ctrl+W{" "*25}Close tab
Ctrl+F{" "*27}Find & replace
Ctrl+R{" "*27}Run file
Ctrl+Shift+R{" "*17}Run selection
Tab / Enter{" "*21}Accept autocomplete
Up / Down{" "*20}Move autocomplete selection
Esc{" "*32}Dismiss autocomplete
F2 / Shift+F2{" "*17}Next / previous bookmark
Ctrl+F2{" "*25}Toggle bookmark
Ctrl+= / Ctrl+-{" "*14}Zoom in / out
Ctrl+0{" "*27}Reset zoom
"""
        messagebox.showinfo("Keyboard Shortcuts", shortcuts)

    def _show_about(self) -> None:
        messagebox.showinfo(APP_TITLE, f"{APP_TITLE}\nA desktop editor for ChemQL.\n"
                                        f"chemql integration: {'available' if self.bridge.available else 'not installed'}")


def main() -> None:
    if os.name == 'nt':  # Checks if the OS is Windows
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('chemql.codecqlx.1.0.0')
    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "-v"):
        print("CodecQLX 1.1.0")
    else:
        app = App(sys.argv[1:])
        app.mainloop()


if __name__ == "__main__":
    main()