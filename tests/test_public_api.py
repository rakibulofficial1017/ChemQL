import chemql
import pytest


def test_unknown_function_call_reports_its_full_name():
    assert chemql.process_inline("int{5}") == 5

    with pytest.raises(chemql.ChemQLError, match=r"Unknown function `rint`"):
        chemql.execute_query_text("rint{5}")

    with pytest.raises(chemql.ChemQLError, match=r"Unknown function `print`"):
        chemql.process_inline("print{}")

    with pytest.raises(chemql.TooFewArguments, match=r"expected at least 1, got 0"):
        chemql.process_inline("int{}")


def test_adjacent_function_calls_compose_as_an_expression():
    assert chemql.process_inline("int{1}+int{1}") == 2


def test_imported_python_class_constructor_supports_direct_attribute_access(monkeypatch):
    class Config:
        def __init__(self):
            self.bd = 4

    monkeypatch.setitem(chemql.python_globals, "Config", Config)

    assert chemql.process_inline("Config{}.bd") == 4


def test_risk_block_does_not_treat_error_like_string_as_exception(monkeypatch, capsys):
    monkeypatch.setattr(chemql, "_record_execution", lambda *args: None)

    chemql.process_lines(
        [
            "risk",
            r'    "    ^^^\nError: "',
            "fix",
            '    print("FIX RAN")',
            "cleanup",
            '    print("CLEANUP RAN")',
            "endrisk",
        ]
    )

    assert chemql.python_globals["error"] is None
    output = capsys.readouterr().out
    assert "    ^^^\nError: " in output
    assert "FIX RAN" not in output
    assert "CLEANUP RAN" in output


def test_risk_block_runs_fix_after_a_real_query_error(monkeypatch, capsys):
    monkeypatch.setattr(chemql, "_record_execution", lambda *args: None)

    chemql.process_lines(
        ["risk", "    unknown_command", "fix", "    print(error)", "endrisk"]
    )

    assert capsys.readouterr().out.strip() == "ChemQLError"


def test_all_exports_only_public_query_api_and_result_types():
    assert set(chemql.__all__) == {
        "ChemQLError",
        "Element",
        "Molecule",
        "Reaction",
        "ReturnTable",
        "Unknown",
        "balance_stoichiometry",
        "execute_query",
        "execute_query_text",
    }
    assert all(hasattr(chemql, name) for name in chemql.__all__)


@pytest.mark.parametrize("option", ["-v", "--version"])
def test_cli_version_option_prints_version(monkeypatch, capsys, option):
    monkeypatch.setattr("sys.argv", ["chemql", option])

    with pytest.raises(SystemExit) as exception:
        chemql.main()

    assert exception.value.code == 0
    assert capsys.readouterr().out == chemql.__version__ + "\n"
