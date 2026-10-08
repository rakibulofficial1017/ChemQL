import chemql
import pytest


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
    assert capsys.readouterr().out == "0.2.1\n"
