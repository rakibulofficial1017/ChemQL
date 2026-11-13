from types import SimpleNamespace

from chemql import codecqlx
from chemql import codecql_gui_core as core


def test_switching_theme_rebases_default_colors_and_keeps_custom_colors():
    colors = {
        "background": core.DARK_THEME["background"],
        "foreground": core.DARK_THEME["foreground"],
        "string": "#ff00ff",
    }

    rebased = codecqlx._rebase_theme_colors(
        colors, core.DARK_THEME, core.LIGHT_THEME
    )

    assert rebased == {
        "background": core.LIGHT_THEME["background"],
        "foreground": core.LIGHT_THEME["foreground"],
        "string": "#ff00ff",
    }


def test_default_palette_values_are_not_saved_as_color_overrides():
    colors = {
        "background": core.LIGHT_THEME["background"],
        "foreground": "#222222",
        "string": core.LIGHT_THEME["string"],
    }

    assert codecqlx._theme_color_overrides(colors, core.LIGHT_THEME) == {
        "foreground": "#222222",
    }


def test_stale_dark_palette_overrides_are_normalized_for_light_mode():
    colors = {
        key: core.DARK_THEME[key]
        for key in codecqlx.PreferencesDialog.COLOR_KEYS
    }
    colors["string"] = "#ff00ff"

    normalized = codecqlx._normalize_theme_color_overrides(colors, "light")

    assert normalized == {"string": "#ff00ff"}


def test_gui_tokenizer_highlights_function_argument_contexts():
    tokens = core.tokenize_line("arguments kwarguments")

    assert [token.tag for token in tokens] == ["builtin", "builtin"]


def test_gui_editor_auto_indents_parameterized_function_header():
    tab = codecqlx.EditorTab.__new__(codecqlx.EditorTab)
    line = "func greet{name, age=10}"
    inserted = []
    tab.autocomplete = SimpleNamespace(visible=False)
    tab.current_line_and_col = lambda: (line, len(line), 1)
    tab.text = SimpleNamespace(insert=lambda mark, value: inserted.append(value))
    tab.after_idle = lambda callback: None

    assert tab._on_return(None) == "break"
    assert inserted == ["\n\t"]
