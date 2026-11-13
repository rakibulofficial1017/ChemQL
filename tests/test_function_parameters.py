import pytest

import chemql


def _define_function(monkeypatch, name, lines):
    monkeypatch.delitem(chemql.FUNCTIONS, name, raising=False)
    chemql.process_lines(lines)


def test_declared_parameters_bind_by_position_and_keyword(monkeypatch):
    _define_function(
        monkeypatch,
        "named_greeting",
        [
            "func named_greeting{name, age}",
            "    let text = str{name}",
            "    let years = \\2",
            "    return text, years, arguments",
            "endfunc",
        ],
    )

    assert chemql.process_inline('named_greeting{"John", 20}') == (
        "John", 20, ["John", 20]
    )
    assert chemql.process_inline(
        'named_greeting{age=20, name="John"}'
    ) == ("John", 20, ["John", 20])


def test_default_and_optional_parameters(monkeypatch):
    _define_function(
        monkeypatch,
        "defaulted_greeting",
        [
            "func defaulted_greeting{name, age=10}",
            "    return name, age, arguments",
            "endfunc",
        ],
    )
    _define_function(
        monkeypatch,
        "optional_greeting",
        [
            "func optional_greeting{name, age?}",
            "    return name, age",
            "endfunc",
        ],
    )

    assert chemql.process_inline("defaulted_greeting{40}") == (
        40, 10, [40, 10]
    )
    assert chemql.process_inline(
        "defaulted_greeting{age=30, name=40}"
    ) == (40, 30, [40, 30])
    assert chemql.process_inline("optional_greeting{40}") == (40, None)


def test_optional_parameters_with_placeholders_in_line_comments(monkeypatch):
    _define_function(
        monkeypatch,
        "bar",
        [
            "func bar{name, age?}",
            "    let value = str{name} // Positional form remains available as \\1",
            "    let args = arguments // Includes declared parameter values",
            "    return value, age, args",
            "endfunc",
        ],
    )

    assert chemql.process_inline('bar{"Jacob", 30}') == (
        "Jacob", 30, ["Jacob", 30]
    )
    assert chemql.process_inline('bar{"Jacob"}') == (
        "Jacob", None, ["Jacob", None]
    )


def test_legacy_functions_expose_kwarguments_and_keep_positional_placeholders(
    monkeypatch,
):
    _define_function(
        monkeypatch,
        "legacy_fred",
        [
            "func legacy_fred",
            "    name = (\\1)",
            "    age = (30 if len(arguments) < 2 else (\\2))",
            "    return name, age",
            "endfunc",
        ],
    )
    _define_function(
        monkeypatch,
        "named_values",
        [
            "func named_values",
            '    return kwarguments["name"], kwarguments.age',
            "endfunc",
        ],
    )

    assert chemql.process_inline('legacy_fred{"Fred"}') == ("Fred", 30)
    assert chemql.process_inline('legacy_fred{"Fred", 20}') == ("Fred", 20)
    assert chemql.process_inline(
        'named_values{name="John", age=20}'
    ) == ("John", 20)


@pytest.mark.parametrize(
    "call",
    [
        "parameter_errors{age=30}",
        "parameter_errors{40, name=30}",
        "parameter_errors{40, 20, 10}",
        "parameter_errors{40, missing=20}",
    ],
)
def test_invalid_parameter_calls_are_rejected(monkeypatch, call):
    _define_function(
        monkeypatch,
        "parameter_errors",
        [
            "func parameter_errors{name, age=10}",
            "    return name, age",
            "endfunc",
        ],
    )

    with pytest.raises(TypeError):
        chemql.process_inline(call)
