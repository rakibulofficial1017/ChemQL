import chemql


def test_all_exports_only_public_query_api_and_result_types():
    assert set(chemql.__all__) == {
        "ChemQLError",
        "Element",
        "Molecule",
        "Reaction",
        "ReturnTable",
        "Unknown",
        "execute_query",
        "execute_query_text",
    }
    assert all(hasattr(chemql, name) for name in chemql.__all__)
