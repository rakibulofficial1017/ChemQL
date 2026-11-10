from tkinter import font

from chemql import codecqlx


def test_default_font_prefers_ligature_font_when_enabled(monkeypatch):
    monkeypatch.setattr(font, "families", lambda: ("Menlo", "Fira Code"))

    assert codecqlx._pick_font_family("Menlo", ligatures_enabled=True) == "Fira Code"


def test_default_font_is_kept_when_ligatures_are_disabled(monkeypatch):
    monkeypatch.setattr(font, "families", lambda: ("Menlo", "Fira Code"))

    assert codecqlx._pick_font_family("Menlo", ligatures_enabled=False) == "Menlo"


def test_custom_font_preference_is_not_overridden(monkeypatch):
    monkeypatch.setattr(font, "families", lambda: ("Custom Mono", "Fira Code"))

    assert codecqlx._pick_font_family("Custom Mono", ligatures_enabled=True) == "Custom Mono"


def test_missing_ligature_font_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(font, "families", lambda: ("Menlo", "Courier New"))

    assert codecqlx._pick_font_family("Menlo", ligatures_enabled=True) == "Menlo"
