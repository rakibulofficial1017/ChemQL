# ChemQL data sources

This directory stores the backing datasets used by the ChemQL query engine. The files are loaded at runtime by the [`chemql` package](../__init__.py) and used by commands such as `search`, `findel`, `findmol`, `findre`, and `react`.

## Files in this folder

- `PeriodicTableJSON.json`
  - Element-level metadata for all known elements, including atomic number, symbol, mass, category, group, period, phase, and related chemistry fields.
  - Used by `search elements` and `findel` lookups.

- `Molecules.json`
  - Molecule records with names, formulas, identifiers, and physical property values.
  - Used by `search molecules`, `findmol`, and related lookups.
  - Records use reference conditions like:
    - `melting_point`: °C at 1 atm
    - `boiling_point`: °C at 1 atm
    - `density`: g/cm³ at 25 °C
    - `state`: physical state at 25 °C and 1 atm (`solid`, `liquid`, or `gas`)

- `Reactions.json`
  - Curated reaction metadata used for `search reactions`, reaction matching, and `react` execution.
  - Imported from [Rhea](https://www.rhea-db.org/) via [`scripts/import_rhea_reactions.py`](../../../scripts/import_rhea_reactions.py).
  - Rhea master records do not always provide directionality, phases, or experimental conditions, so those fields may be missing or empty rather than inferred.

- `MoleculeBonds.json`
  - Bonding structure and connectivity information for molecules.
  - Useful for chemistry and structure-aware analysis beyond simple lookup queries.

- `BondEnergies.json`
  - Bond-energy data used for energetic calculations and reaction analysis.

## Data provenance and validation

- Molecule property values were cross-checked with public chemistry references where possible, including [Wikidata](https://query.wikidata.org/).
- Selected common compounds were validated against reference pages for [water](https://en.wikipedia.org/wiki/Water), [oxygen](https://en.wikipedia.org/wiki/Oxygen), [ethanol](https://en.wikipedia.org/wiki/Ethanol), [acetic acid](https://en.wikipedia.org/wiki/Acetic_acid), and [sodium chloride](https://en.wikipedia.org/wiki/Sodium_chloride).
- Rhea reaction data is distributed under the [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) license; the license text is included in `THIRD_PARTY_LICENSES/`.

## Notes

- Missing or conflicting values are left as `null` when the source data is uncertain or unavailable.
- `search` queries can filter on dataset keys such as `name`, `formula`, `atomic_number`, `reaction_type`, `molecular_weight`, and other recorded attributes.
- The data files are intended to be queryable rather than to serve as a standalone database system; ChemQL adds filtering, transformation, and chemistry-aware behavior on top of them.