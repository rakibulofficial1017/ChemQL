"""Import curated Rhea master reactions into the ChemQL package data."""

import argparse
import gzip
import io
import json
import os
import re
import tempfile
import urllib.request
from pathlib import Path


BASE_URL = "https://ftp.expasy.org/databases/rhea"
FORMULA_PATTERN = re.compile(r"(?:[A-Z][a-z]?\d*)+")
TERM_PATTERN = re.compile(r"(?:(\d+)\s+)?(CHEBI:\d+)")


def _open_gzip_text(filename):
    request = urllib.request.Request(
        f"{BASE_URL}/txt/{filename}",
        headers={"User-Agent": "ChemQL Rhea importer"},
    )
    response = urllib.request.urlopen(request, timeout=60)
    compressed = gzip.GzipFile(fileobj=response)
    return io.TextIOWrapper(compressed, encoding="utf-8")


def _read_records(lines):
    record = {}
    current_field = None

    for line in lines:
        if line.strip() == "///":
            if record:
                yield record
            record = {}
            current_field = None
            continue

        field = line[:12].strip()
        if field:
            current_field = field
            record[field] = line[12:].strip()
        elif current_field and line.strip():
            record[current_field] += " " + line.strip()


def _read_compounds():
    compounds = {}
    with _open_gzip_text("rhea-compounds.txt.gz") as source:
        for record in _read_records(source):
            chebi_id = record.get("ENTRY")
            formula = record.get("FORMULA", "")
            if chebi_id and FORMULA_PATTERN.fullmatch(formula):
                compounds[chebi_id] = {
                    "name": record.get("NAME", ""),
                    "formula": formula,
                }
    return compounds


def _read_master_ids():
    request = urllib.request.Request(
        f"{BASE_URL}/tsv/rhea-directions.tsv",
        headers={"User-Agent": "ChemQL Rhea importer"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        lines = io.TextIOWrapper(response, encoding="utf-8")
        next(lines, None)
        return {line.split("\t", 1)[0].strip() for line in lines if line.strip()}


def _participants(side, compounds):
    participants = []
    for term in re.split(r"\s+\+\s+", side.strip()):
        match = TERM_PATTERN.fullmatch(term)
        if not match:
            return None

        coefficient = int(match.group(1) or 1)
        compound = compounds.get(match.group(2))
        if coefficient <= 0 or compound is None or not compound["name"]:
            return None

        participants.append({
            "molecule": compound["formula"],
            "name": compound["name"],
            "chebi_id": match.group(2),
            "stoichiometric_coefficient": coefficient,
            "phase": None,
        })

    return participants or None


def _convert_record(record, master_ids, compounds):
    identifier = record.get("ENTRY", "").removeprefix("RHEA:")
    if identifier not in master_ids:
        return None

    equation = record.get("EQUATION", "")
    sides = re.fullmatch(r"(.+?)\s=\s(.+)", equation)
    if not sides:
        return None

    reactants = _participants(sides.group(1), compounds)
    products = _participants(sides.group(2), compounds)
    name = record.get("DEFINITION", "").strip()
    if not reactants or not products or not name:
        return None

    return {
        "id": f"RHEA:{identifier}",
        "name": name,
        "reaction_type": "biochemical",
        "reversible": None,
        "reactants": reactants,
        "products": products,
        "conditions": {},
        "source": f"Rhea Database, https://www.rhea-db.org/rhea/{identifier} (CC BY 4.0)",
        "notes": "Rhea does not specify experimental conditions or participant phases for this record.",
    }


def import_reactions(path, limit):
    compounds = _read_compounds()
    master_ids = _read_master_ids()
    imported = []

    with _open_gzip_text("rhea-reactions.txt.gz") as source:
        for record in _read_records(source):
            reaction = _convert_record(record, master_ids, compounds)
            if reaction is not None:
                imported.append(reaction)
                if len(imported) == limit:
                    break

    if len(imported) < limit:
        raise RuntimeError(f"Only found {len(imported)} valid Rhea records; expected {limit}.")

    existing = json.loads(path.read_text(encoding="utf-8"))
    retained = [item for item in existing if not item.get("id", "").startswith("RHEA:")]
    combined = retained + imported
    identifiers = [item["id"] for item in combined]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Reaction IDs must be unique.")

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as output:
            temporary_path = Path(output.name)
            json.dump(combined, output, ensure_ascii=False, indent=4)
            output.write("\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    return len(combined), len(imported)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            Path(__file__).resolve().parents[1]
            / "src" / "chemql" / "data" / "Reactions.json"
        ),
    )
    arguments = parser.parse_args()
    total, imported = import_reactions(arguments.output, arguments.count)
    print(f"Imported {imported} Rhea reactions; {total} total records in {arguments.output}.")


if __name__ == "__main__":
    main()