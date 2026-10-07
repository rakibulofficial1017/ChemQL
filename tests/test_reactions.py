import chemql
from prompt_toolkit.document import Document


def test_balance_stoichiometry_returns_minimal_reaction_coefficients():
    reaction = chemql.balance_stoichiometry(["O2", "H2"], ["H2O"], True)

    assert isinstance(reaction, chemql.Reaction)
    assert [part["stoichiometric_coefficient"] for part in reaction.reactants] == [1, 2]
    assert [part["stoichiometric_coefficient"] for part in reaction.products] == [2]
    assert reaction.reversible is True

    grouped = chemql.balance_stoichiometry(
        ["Ca(OH)2", "H3PO4"],
        ["Ca3(PO4)2", "H2O"],
    )
    assert [
        part["stoichiometric_coefficient"]
        for part in grouped.reactants + grouped.products
    ] == [3, 2, 1, 6]


def test_balance_syntax_preserves_direction_annotation(capsys):
    chemql.process_lines(["balance O2 + H2 -> H2O //reversible"])
    assert "1 O₂ + 2 H₂ ⇌ 2 H₂O" in capsys.readouterr().out

    reaction = chemql.execute_query_text(
        "balance O2 + H2 <-> H2O //irreversible"
    )
    assert isinstance(reaction, chemql.Reaction)
    assert reaction.reversible is False
    assert "1 O₂ + 2 H₂ → 2 H₂O" in str(reaction)


def test_balance_stoichiometry_rejects_invalid_formula():
    try:
        chemql.balance_stoichiometry(["Xx2"], ["H2"])
    except ValueError as exc:
        assert "Unknown element" in str(exc)
    else:
        raise AssertionError("Unknown elements must be rejected")


def test_findre_searches_reactions_by_id_and_projects_attributes():
    result = chemql.execute([
        "findre", "RHEA:10000", "return", "id", "name", "source"
    ])

    assert result["id"] == ["RHEA:10000"]
    assert result["name"]
    assert "rhea-db.org/rhea/10000" in result["source"][0]


def test_findre_reports_missing_reaction():
    result = chemql.execute(["findre", "reaction-not-in-dataset"])

    assert result == "Could not find reaction `reaction-not-in-dataset`"


def test_reaction_preserves_unknown_direction_as_undirected_equation():
    reaction = next(
        reaction for reaction in chemql.REACTIONS
        if reaction.id == "RHEA:10000"
    )

    assert reaction.reversible is None
    assert " = " in reaction.equation
    assert "ΔH=" not in reaction.equation
    assert "rhea-db.org/rhea/10000" in reaction.source


def test_reaction_temperature_units_and_aliases():
    chemql.execute(["set", "temperature", "0C"])
    assert chemql.reaction_state["temperature_k"] == 273.15

    chemql.execute(["set", "temperature", "0F"])
    assert abs(chemql.reaction_state["temperature_k"] - 255.3722222) < 0.001

    chemql.execute(["set", "temperature", "0K"])
    assert chemql.reaction_state["temperature_k"] == 0

    chemql.execute(["set", "temperature", "standard"])
    assert chemql.reaction_state["temperature_k"] == 273.15

    chemql.execute(["set", "temperature", "room"])
    assert chemql.reaction_state["temperature_k"] == 298.15


def test_reaction_pressure_units_and_aliases():
    for unit in ("pa", "N/m^2", "Nm^-2"):
        chemql.execute(["set", "pressure", f"0{unit}"])
        assert chemql.reaction_state["pressure_pa"] == 0

    chemql.execute(["set", "pressure", "0bar"])
    assert chemql.reaction_state["pressure_pa"] == 0

    chemql.execute(["set", "pressure", "standard"])
    assert chemql.reaction_state["pressure_pa"] == 100000

    chemql.execute(["set", "pressure", "room"])
    assert chemql.reaction_state["pressure_pa"] == 101325


def test_catalyst_commands_and_react_returns_local_product():
    chemql.execute(["set", "catalysts", "iron", "zinc"])
    chemql.execute(["remove", "calatyst", "zinc"])
    chemql.execute(["add", "catalyst", "Vanadium oxide"])
    assert chemql.reaction_state["catalysts"] == ["iron", "Vanadium oxide"]

    chemql.execute(["set", "temperature", "723K"])
    chemql.execute(["set", "pressure", "20265000pa"])
    chemql.execute(["set", "catalysts", "iron"])
    product = chemql.execute(["react", "N2", "3H2"])

    assert isinstance(product, chemql.Molecule)
    assert product.formula == "NH3"


def test_react_requires_recorded_catalysts():
    chemql.execute(["set", "temperature", "723K"])
    chemql.execute(["set", "pressure", "20265000pa"])
    chemql.execute(["set", "catalysts", "zinc"])

    result = chemql.execute(["react", "N2", "3H2"])

    assert result.startswith("No reaction matches")


def test_conditions_reports_unset_and_configured_values():
    chemql.reaction_state.update({
        "temperature_k": None,
        "pressure_pa": None,
        "catalysts": [],
    })
    unset = chemql.execute(["conditions"])
    assert "Temperature: Not Set" in unset
    assert "Pressure: Not Set" in unset
    assert "Catalysts: Not Set" in unset

    chemql.execute(["set", "temperature", "0C"])
    chemql.execute(["set", "pressure", "1bar"])
    chemql.execute(["set", "catalysts", "iron"])
    configured = chemql.execute(["conditions"])
    assert "Temperature: 273.15 K" in configured
    assert "Pressure: 100000 Pa" in configured
    assert "Catalysts: iron" in configured


def test_condition_terms_are_highlighted():
    get_line = chemql.ChemqlLexer().lex_document(
        Document("set temperature 723K pressure catalyst catalysts conditions")
    )
    tokens = get_line(0)

    assert ("class:condition", "temperature") in tokens
    assert ("class:condition", "pressure") in tokens
    assert ("class:condition", "catalyst") in tokens
    assert ("class:condition", "catalysts") in tokens
    assert ("class:command", "conditions") in tokens


def test_condition_commands_are_completed_contextually():
    completer = chemql.ChemqlCompleter()

    assert {item.text for item in completer.get_completions(Document("set "), None)} == {
        "temperature", "pressure", "catalysts"
    }
    assert {item.text for item in completer.get_completions(Document("set temperature "), None)} >= {
        "standard", "room", "0C", "0F", "0K"
    }
    assert {item.text for item in completer.get_completions(Document("set pressure "), None)} >= {
        "standard", "room", "0Pa", "0N/m^2", "0Nm^-2", "0bar"
    }
    assert [item.text for item in completer.get_completions(Document("add "), None)] == [
        "catalyst"
    ]
    assert "conditions" in {
        item.text for item in completer.get_completions(Document("cond"), None)
    }