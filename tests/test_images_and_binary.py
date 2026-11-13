from PIL import Image
import pytest

import chemql
from chemql import codecqlx
from chemql.data_analysis.images import image_to_terminal


def test_terminal_renderer_produces_color_and_monochrome_output():
    image = Image.new("RGB", (4, 2), (255, 0, 0))

    color_output = image_to_terminal(image, width=4, colors=True)
    monochrome_output = image_to_terminal(image, width=4, colors=False)

    assert "\x1b[38;2;" in color_output
    assert "▀" in color_output
    assert len(monochrome_output.splitlines()) == 1
    assert len(monochrome_output.splitlines()[0]) == 4
    with pytest.raises(ValueError, match="positive integer"):
        image_to_terminal(image, width=0)


def test_print_image_is_available_as_a_chemql_builtin(tmp_path, capsys):
    image_path = tmp_path / "pixel.png"
    Image.new("RGB", (2, 2), (0, 0, 0)).save(image_path)

    result = chemql.process_inline(f'print_image{{"{image_path}", 2, True}}')

    assert result is None
    assert "▀" in capsys.readouterr().out


def test_codecqlx_detects_text_images_and_binary_files(tmp_path):
    text_path = tmp_path / "notes.txt"
    text_path.write_text("hello", encoding="utf-8")
    image_path = tmp_path / "image.png"
    Image.new("RGB", (2, 3), (10, 20, 30)).save(image_path)
    binary_path = tmp_path / "data.bin"
    binary_path.write_bytes(b"\x01\x02\x03")

    text_mode, text = codecqlx._read_editor_file(str(text_path))
    image_mode, image = codecqlx._read_editor_file(str(image_path))
    hex_mode, binary = codecqlx._read_editor_file(str(binary_path))

    assert (text_mode, text) == ("text", "hello")
    assert image_mode == "image"
    assert isinstance(image, Image.Image)
    assert image.size == (2, 3)
    assert (hex_mode, binary) == ("hex", b"\x01\x02\x03")


def test_hex_editor_round_trips_bytes_and_rejects_malformed_edits():
    source = bytes(range(20))
    offsets, hex_rows, ascii_rows = codecqlx._format_hex_columns(source)

    assert offsets == "00000000\n00000010"
    expected_ascii = "." * 16 + "\n" + "." * 4
    assert ascii_rows == expected_ascii
    assert codecqlx._parse_hex_bytes(hex_rows, len(source)) == source
    with pytest.raises(ValueError, match="Invalid byte value"):
        codecqlx._parse_hex_bytes("00 GG", 2)
    with pytest.raises(ValueError, match="original number of rows"):
        codecqlx._parse_hex_bytes("00", 20)
