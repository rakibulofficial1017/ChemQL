import io
import re

from chemql import codecql


def test_codecql_launches_editor_for_requested_file(monkeypatch):
    launched = {}

    class FakeEditor:
        def __init__(self, filename):
            launched["filename"] = filename

        def run(self):
            launched["ran"] = True

    monkeypatch.setattr(codecql, "Editor", FakeEditor)

    codecql.main(["script.cql"])

    assert launched == {"filename": "script.cql", "ran": True}


def test_codecql_uses_packaged_color_categories():
    assert codecql.HIGHLIGHT_STYLES["command"]
    assert codecql.UI_STYLES["status_background"]


def test_namespace_is_highlighted_and_auto_indented():
    editor = codecql.Editor(None)
    editor.lines = ["namespace chemistry"]
    editor.cursor_x = len(editor.lines[0])

    editor._insert_newline()

    assert editor.lines == ["namespace chemistry", "\t"]
    assert codecql._token_style("identifier", "namespace") == codecql.HIGHLIGHT_STYLES["keyword"]
    assert codecql._token_style("identifier", "endnamespace") == codecql.HIGHLIGHT_STYLES["keyword"]


def test_endnamespace_newline_dedents():
    editor = codecql.Editor(None)
    editor.lines = ["\tendnamespace"]
    editor.cursor_x = len(editor.lines[0])

    editor._insert_newline()

    assert editor.lines == ["\tendnamespace", ""]


def test_ctrl_arrow_moves_by_word_and_shift_arrow_selects():
    editor = codecql.Editor(None)
    editor.lines = ["one two"]

    editor.handle_key("ctrl+arrow_right")
    assert (editor.cursor_x, editor.cursor_y) == (4, 0)

    editor.handle_key("shift+arrow_right")
    assert editor._selected_text() == "t"
    assert "\x1b[7mt" in editor._highlight_line(editor.lines[0], 0)


def test_terminal_arrow_modifiers_are_decoded():
    assert codecql._decode_escape_sequence(b"[1;5D") == "ctrl+arrow_left"
    assert codecql._decode_escape_sequence(b"[1;2C") == "shift+arrow_right"
    assert codecql._decode_escape_sequence(b"[1;3A") == "alt+arrow_up"
    assert codecql._decode_escape_sequence(b"[1;6B") == "ctrl+shift+arrow_down"


def test_ctrl_up_down_scroll_viewport_without_edge_trigger(monkeypatch):
    editor = codecql.Editor(None)
    editor.lines = [f"line {index}" for index in range(30)]
    editor.scroll_y = 10
    editor.cursor_y = 13
    editor.cursor_x = 2
    monkeypatch.setattr(codecql.os, "get_terminal_size", lambda: (80, 10))

    editor.handle_key("ctrl+arrow_up")
    assert editor.scroll_y == 9
    assert editor.cursor_y == 12
    assert editor.cursor_y - editor.scroll_y == 3

    editor.handle_key("ctrl+arrow_down")
    assert editor.scroll_y == 10
    assert editor.cursor_y == 13
    assert editor.cursor_y - editor.scroll_y == 3


def test_ctrl_scroll_clamps_at_document_ends(monkeypatch):
    editor = codecql.Editor(None)
    editor.lines = [f"line {index}" for index in range(30)]
    monkeypatch.setattr(codecql.os, "get_terminal_size", lambda: (80, 10))
    editor.scroll_y = 0
    editor.cursor_y = 0

    editor.handle_key("ctrl+arrow_up")
    assert editor.scroll_y == editor.cursor_y == 0

    editor.scroll_y = 22
    editor.cursor_y = 25
    editor.handle_key("ctrl+arrow_down")
    assert editor.scroll_y == 22
    assert editor.cursor_y == 25


def test_ctrl_backspace_and_delete_remove_words():
    editor = codecql.Editor(None)
    editor.lines = ["one two"]
    editor.cursor_x = 0

    editor.handle_key("ctrl+delete")

    assert editor.lines == ["two"]
    assert editor.cursor_x == 0

    editor.handle_key("ctrl+backspace")

    assert editor.lines == ["two"]

    editor.cursor_x = len(editor.lines[0])
    editor.handle_key("\x08")

    assert editor.lines == [""]


def test_ctrl_delete_terminal_sequences_are_decoded():
    assert codecql._decode_escape_sequence(b"[3;5~") == "ctrl+delete"
    assert codecql._decode_escape_sequence(b"[27;5;127~") == "ctrl+backspace"
    assert codecql._decode_escape_sequence(b"[127;5u") == "ctrl+backspace"


def test_search_query_flags_select_regex_case_and_whole_word():
    assert [match.group() for match in codecql._parse_search_query("foo").finditer("FOO foo")] == [
        "FOO", "foo",
    ]
    assert [match.group() for match in codecql._parse_search_query("ri:foo.").finditer("FOO! foo.")] == [
        "FOO!", "foo.",
    ]
    assert [match.group() for match in codecql._parse_search_query("lwi:cat").finditer("cat scatter CAT")] == [
        "cat", "CAT",
    ]
    assert not list(codecql._parse_search_query("l:foo").finditer("FOO"))


def test_search_prompt_live_highlights_and_cycles_matches():
    editor = codecql.Editor(None)
    editor.lines = ["foo FOO", "food"]

    editor.handle_key("\x06")
    assert editor.search_active
    for char in "foo":
        editor.handle_key(char)

    assert editor.search_matches == [(0, 3), (4, 7), (8, 11)]
    assert "\x1b[43m" in editor._highlight_line(editor.lines[0], 0)
    editor.handle_key("\n")
    assert (editor.cursor_x, editor.cursor_y) == (0, 0)
    editor.handle_key("\n")
    assert (editor.cursor_x, editor.cursor_y) == (4, 0)
    editor.handle_key("\x1b")
    assert not editor.search_active
    assert editor.search_matches == []
    assert editor.current_search_match is None
    assert "\x1b[43m" not in editor._highlight_line(editor.lines[0], 0)


def test_invalid_search_regex_is_reported():
    editor = codecql.Editor(None)
    editor.handle_key("\x06")
    for char in "r:[":
        editor.handle_key(char)

    assert editor.search_error
    assert editor.search_matches == []
    assert editor._select_search_match() is None
    assert editor.message.startswith("Search error:")


def test_copy_paste_and_bracketed_multiline_paste(monkeypatch):
    editor = codecql.Editor(None)
    editor.lines = ["one two"]
    copied = []
    monkeypatch.setattr(codecql, "_write_system_clipboard", lambda text: copied.append(text) or True)
    editor.cursor_x = 0
    editor.handle_key("shift+arrow_right")
    editor.handle_key("shift+arrow_right")
    editor.handle_key("\x03")
    assert copied == ["on"]
    assert editor.message == "Copied selection"
    editor.handle_key("arrow_end")
    editor.handle_key("\x16")
    assert editor.lines == ["one twoon"]

    editor.handle_key("paste:first\r\nsecond")
    assert editor.lines == ["one twoonfirst", "second"]


def test_ctrl_t_opens_split_terminal_without_changing_editor_buffer(monkeypatch):
    editor = codecql.Editor(None)
    editor.lines = ["unsaved editor text"]
    editor.cursor_x = 8
    launched = []
    monkeypatch.setattr(editor, "_run_split_terminal", lambda: launched.append(True))

    editor.handle_key("\x14")

    assert launched == [True]
    assert editor.lines == ["unsaved editor text"]
    assert editor.cursor_x == 8


def test_editor_draw_does_not_scroll_or_duplicate_footer(monkeypatch):
    editor = codecql.Editor(None)
    editor.lines = ["first line", "second line"]
    editor.message = ""
    output = io.StringIO()
    monkeypatch.setattr(codecql.os, "get_terminal_size", lambda: (120, 12))
    monkeypatch.setattr(codecql.sys, "stdout", output)

    editor.draw_screen()

    rendered = output.getvalue()
    screen = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", rendered)
    assert screen.startswith("1 first line")
    assert screen.count("Ctrl+S Save") == 1
    assert screen.count("\r\n") == 11
    assert rendered.endswith("\x1b[1;3H")


def test_editor_draw_reserves_rows_above_terminal_pane(monkeypatch):
    editor = codecql.Editor(None)
    editor.lines = ["first line", "second line"]
    editor.message = ""
    output = io.StringIO()
    monkeypatch.setattr(codecql.os, "get_terminal_size", lambda: (120, 12))
    monkeypatch.setattr(codecql.sys, "stdout", output)

    editor.draw_screen(terminal_height=4)

    rendered = output.getvalue()
    screen = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", rendered)
    assert screen.startswith("1 first line")
    assert "Ctrl+T Terminal" in screen
    assert screen.count("\r\n") == 7
    assert rendered.endswith("\x1b[1;3H")
