from chemql import codecqlx


def test_macos_icon_uses_opaque_png():
    icon = codecqlx._app_icon_path("darwin")
    png = icon.read_bytes()

    assert icon.name == "logo64-macos.png"
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert png[25] == 2


def test_other_platforms_keep_original_icon():
    assert codecqlx._app_icon_path("linux").name == "logo64.png"
    assert codecqlx._app_icon_path("win32").name == "logo64.png"
