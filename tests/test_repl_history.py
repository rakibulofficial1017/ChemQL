import asyncio

import chemql
from prompt_toolkit.history import FileHistory


def test_repl_history_persists_between_instances(monkeypatch, tmp_path):
    monkeypatch.setattr(chemql.Path, "home", lambda: tmp_path)

    first_session_history = chemql._create_repl_history()
    first_session_history.append_string("search elements symbol = O")

    history_file = tmp_path / ".chemql" / ".repl_history"
    assert history_file.is_file()

    next_session_history = chemql._create_repl_history()

    async def load_entries():
        return [entry async for entry in next_session_history.load()]

    assert asyncio.run(load_entries()) == ["search elements symbol = O"]


def test_repl_history_removes_only_a_trailing_exit(monkeypatch, tmp_path):
    monkeypatch.setattr(chemql.Path, "home", lambda: tmp_path)
    history = chemql._create_repl_history()
    history.append_string("search elements symbol = O")
    history.append_string("exit")

    next_session_history = chemql._create_repl_history()

    assert list(next_session_history.load_history_strings()) == [
        "search elements symbol = O"
    ]
