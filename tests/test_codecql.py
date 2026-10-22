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
