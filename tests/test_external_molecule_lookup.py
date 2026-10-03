import chemql


def test_fetch_pubchem_molecule_does_not_return_pubchem_error_string_when_missing_locally(monkeypatch):
    monkeypatch.setattr(chemql, "_find_local_molecule", lambda value: None)
    monkeypatch.setattr(chemql, "fetch_external_molecule", lambda value: None)
    monkeypatch.setattr(chemql, "_find_cid", lambda value: None)
    monkeypatch.setattr(chemql, "PUBCHEM_SERVICE_ERROR", True)

    result = chemql.fetch_pubchem_molecule("molecule-not-in-dataset")

    assert result is None


def test_fetch_external_molecule_uses_nist_when_pubchem_has_no_cid(monkeypatch):
    expected = chemql.Molecule(
        name="cocaine",
        formula="C17H21NO4",
        elements=[],
        molecular_weight=303.35,
        iupac_name="benzoylecgonine",
        smiles="",
        cid=None,
        melting_point=None,
        boiling_point=None,
        density=None,
        state=None,
    )

    monkeypatch.setattr(chemql, "_find_cid", lambda value: None)
    monkeypatch.setattr(chemql, "_fetch_nist_molecule", lambda value: expected)

    result = chemql.fetch_external_molecule("cocaine")

    assert result is expected


def test_findmol_uses_external_lookup_after_local_miss(monkeypatch):
    expected = chemql.Molecule(
        name="unlisted molecule",
        formula="C2H6O",
        elements=[],
        molecular_weight=46.07,
        iupac_name="ethanol",
        smiles="CCO",
        cid=702,
        melting_point=None,
        boiling_point=None,
        density=None,
        state=None,
    )
    lookups = []

    def external_lookup(value):
        lookups.append(value)
        return expected

    monkeypatch.setattr(chemql, "fetch_pubchem_molecule", external_lookup)

    result = chemql.execute(["findmol", "unlisted molecule"])

    assert lookups == ["unlisted molecule"]
    assert result is expected


def test_findmol_reports_error_when_all_sources_miss(monkeypatch):
    monkeypatch.setattr(chemql, "fetch_pubchem_molecule", lambda value: None)

    result = chemql.execute(["findmol", "molecule-not-in-dataset"])

    assert result == "Could not find molecule `molecule-not-in-dataset`"
