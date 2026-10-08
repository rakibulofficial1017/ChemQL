import json
import math
import shlex
import re
import ast
import argparse
import time
from pathlib import Path
from prompt_toolkit import PromptSession
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.styles import Style
from prompt_toolkit.completion import Completer, Completion
import urllib.parse
import urllib.request
import urllib.error
from fractions import Fraction
from functools import reduce
from math import gcd


__all__ = [
    "ChemQLError",
    "Element",
    "Molecule",
    "Reaction",
    "ReturnTable",
    "Unknown",
    "balance_stoichiometry",
    "execute_query",
    "execute_query_text",
]


class Unknown:
    """Represents a Chemql query result that cannot be resolved to a known object."""

    __slots__ = ("value",)

    def __init__(self, value=None):
        self.value = value

    def __str__(self):
        return str(self.value) if self.value is not None else "Unknown"

    def __repr__(self):
        return repr(self.value) if self.value is not None else "Unknown"


class ChemQLError(Exception):
    def __init__(self, message, position=None, length=1):
        super().__init__(message)
        self.position = position
        self.length = length


def format_error(message, text=None, position=None, length=1):
    output = f"Error: {message}"

    if text is not None and position is not None:
        output += f"\n{text}\n{' ' * position}{'^' * max(1, length)}"

    return output


def token_positions(text):
    positions = []
    i = 0
    while i < len(text):
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break

        start = i
        quote = None
        escaped = False
        while i < len(text):
            char = text[i]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif quote:
                if char == quote:
                    quote = None
            elif char in ("\'", '"'):
                quote = char
            elif char.isspace():
                break
            i += 1
        positions.append((start, max(1, i - start)))
    return positions


def error_position(positions, index):
    if 0 <= index < len(positions):
        return positions[index]
    return (None, 1)
from prompt_toolkit.shortcuts import choice

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

with (DATA_DIR / "PeriodicTableJSON.json").open("r", encoding="utf-8") as f:
    elements = json.load(f)
with (DATA_DIR / "Molecules.json").open("r", encoding="utf-8") as f:
    molecules = json.load(f)
with (DATA_DIR / "Reactions.json").open("r", encoding="utf-8") as f:
    reactions = json.load(f)
with (DATA_DIR / "MoleculeBonds.json").open("r", encoding="utf-8") as f:
    moleculeBonds = json.load(f)
with (DATA_DIR / "BondEnergies.json").open("r", encoding="utf-8") as f:
    bondEnergies = json.load(f)

operators = {"has", "like", "like!", "=", ">", "<", ">=", "<="}

queryOperations = {"sort", "limit", "count"}

def like_match(value, pattern, case_sensitive=False):
    regex = ""
    i = 0

    while i < len(pattern):
        char = pattern[i]

        if char == "\\":
            i += 1

            if i >= len(pattern):
                raise ValueError(
                    "Escape character at end of pattern"
                )

            regex += re.escape(pattern[i])

        elif char == "*":
            regex += ".*"

        elif char == "%":
            regex += "[0-9]*"

        elif char == "&":
            regex += "[A-Za-z]*"

        elif char == "_":
            regex += "."

        elif char == "#":
            regex += "[0-9]"

        elif char == "?":
            regex += "[A-Za-z]"

        else:
            regex += re.escape(char)

        i += 1

    flags = 0 if case_sensitive else re.IGNORECASE

    return re.fullmatch(regex, value, flags) is not None


def normal_round(num, p=0):
    num1 = num / 10**p
    numint = math.floor(num1)
    numfloat = num - numint
    if numfloat >= 0.5:
        return -(-numint - 1) * 10**p
    return numint * 10 ** p



class Element:
    __slots__ = ("name", "appearance", "atomic_mass", "boil", "category", "density", "discovered_by", "melt", "molar_heat", "named_by", "number", "period", "group", "phase", "source", "bohr_model_image", "bohr_model_3d", "spectral_img", "summary", "symbol", "xpos", "ypos", "wxpos", "wypos", "shells", "electron_configuration", "electron_configuration_semantic", "electron_affinity", "electronegativity_pauling", "ionization_energies", "cpk_hex", "image", "block")

    def __init__(
        self,
        name,
        appearance,
        atomic_mass,
        boil,
        category,
        density,
        discovered_by,
        melt,
        molar_heat,
        named_by,
        number,
        period,
        group,
        phase,
        source,
        bohr_model_image,
        bohr_model_3d,
        spectral_img,
        summary,
        symbol,
        xpos,
        ypos,
        wxpos,
        wypos,
        shells,
        electron_configuration,
        electron_configuration_semantic,
        electron_affinity,
        electronegativity_pauling,
        ionization_energies,
        cpk_hex,
        image,
        block,
    ):
        self.name = name
        self.appearance = appearance
        self.atomic_mass = atomic_mass
        self.boil = boil
        self.category = category
        self.density = density
        self.discovered_by = discovered_by
        self.melt = melt
        self.molar_heat = molar_heat
        self.named_by = named_by
        self.number = number
        self.period = period
        self.group = group
        self.phase = phase
        self.source = source
        self.bohr_model_image = bohr_model_image
        self.bohr_model_3d = bohr_model_3d
        self.spectral_img = spectral_img
        self.summary = summary
        self.symbol = symbol
        self.xpos = xpos
        self.ypos = ypos
        self.wxpos = wxpos
        self.wypos = wypos
        self.shells = shells
        self.electron_configuration = electron_configuration
        self.electron_configuration_semantic = electron_configuration_semantic
        self.electron_affinity = electron_affinity
        self.electronegativity_pauling = electronegativity_pauling
        self.ionization_energies = ionization_energies
        self.cpk_hex = cpk_hex
        self.image = image
        self.block = block

    def __getitem__(self, key):
        return getattr(self, key)

    def __str__(self):
        if self.cpk_hex:
            r = int(self.cpk_hex[0:2], 16)
            g = int(self.cpk_hex[2:4], 16)
            b = int(self.cpk_hex[4:6], 16)
        else:
            r = g = b = 255

        return (
            f"\033[38;2;{r};{g};{b}m"
            f" ______________\n"
            f"|     {self.number:^3}      |\n"
            f"|              |\n"
            f"|     {self.symbol:^3}      |\n"
            f"|              |\n"
            f"|     {normal_round(self.atomic_mass):^3}      |\n"
            f"|______________|"
            f"\033[0m\n"
        )
    def __repr__(self):
        return f"{self.name}"

elementKeys = ("name", "appearance", "atomic_mass", "boil", "category", "density", "discovered_by", "melt", "molar_heat", "named_by", "number", "period", "group", "phase", "source", "bohr_model_image", "bohr_model_3d", "spectral_img", "summary", "symbol", "xpos", "ypos", "wxpos", "wypos", "shells", "electron_configuration", "electron_configuration_semantic", "electron_affinity", "electronegativity_pauling", "ionization_energies", "cpk-hex", "image", "block")

ELEMENTS = [Element(*(item[key] if item[key] is not None else "" for key in elementKeys)) for item in elements["elements"]]

# No longer need the JSON structure.

ELEMENTS.pop()

class Molecule:
    __slots__ = ("name", "formula", "elements", "molecular_weight", "iupac_name", "smiles", "cid", "melting_point","boiling_point", "density", "state", "bonds", "total_bond_energy")
    def __init__(self, name, formula, elements, molecular_weight, iupac_name, smiles, cid, melting_point, boiling_point, density, state):
        self.name = name
        self.formula = formula
        self.elements = elements
        self.molecular_weight = molecular_weight
        self.iupac_name = iupac_name
        self.smiles = smiles
        self.cid = cid
        self.melting_point = melting_point
        self.boiling_point = boiling_point
        self.density = density
        self.state = state
        self.bonds = moleculeBonds.get(name, {}).get("bonds", [])
        self.total_bond_energy = sum(
            bond.get("count", 0) * bondEnergies[
                f"{'-'.join(sorted(bond['elements']))}-{bond['type']}"
            ]["energy"]
            for bond in self.bonds
        )
    def __getitem__(self, key):
        return getattr(self, key)
    def __str__(self):
        return f"{self.formula.translate(str.maketrans('0123456789', '₀₁₂₃₄₅₆₇₈₉'))} ({self.name})"

    def __repr__(self):
        return self.name

moleculeKeys = ("name", "formula", "elements", "molecular_weight", "iupac_name", "smiles", "cid", "melting_point", "boiling_point", "density", "state", "bonds", "total_bond_energy")

PUBCHEM_BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUBCHEM_VIEW_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"
PUBCHEM_SERVICE_ERROR = False


def _normalize_molecule_value(value):
    """Strip surrounding quotes and whitespace from a molecule lookup."""
    if value is None:
        return ""

    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()

    return text


def _fetch_url_text(url, timeout=15, retries=2):
    """Fetch a raw text response from a URL, retrying transient failures."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ChemQL/1.0 (+https://example.invalid)",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        },
    )

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            return ""

    return ""


def _get_json(url, timeout=10, retries=3):
    """Fetch JSON from a URL with retries for transient server errors."""
    global PUBCHEM_SERVICE_ERROR

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ChemQL/1.0 (+https://example.invalid)",
            "Accept": "application/json",
        },
    )

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.load(response)
                PUBCHEM_SERVICE_ERROR = False
                return data

        except urllib.error.HTTPError as exc:
            if exc.code in (500, 502, 503, 504):
                PUBCHEM_SERVICE_ERROR = True
                if attempt < retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                return None
            PUBCHEM_SERVICE_ERROR = False
            return None

        except (
            urllib.error.URLError,
            json.JSONDecodeError,
            TimeoutError,
            OSError,
            ValueError,
        ):
            PUBCHEM_SERVICE_ERROR = True
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            return None


def _find_local_molecule(value):
    """Return a built-in molecule when the network lookup is unavailable."""
    if value is None:
        return None

    target = _normalize_molecule_value(value)
    if not target:
        return None

    normalized = target.lower()

    for molecule in MOLECULES:
        if molecule.name.lower() == normalized:
            return molecule
        if molecule.formula.lower() == normalized:
            return molecule
        if molecule.iupac_name and molecule.iupac_name.lower() == normalized:
            return molecule

    for molecule in MOLECULES:
        if molecule.name.lower().startswith(normalized):
            return molecule
        if molecule.formula.lower().startswith(normalized):
            return molecule
        if molecule.iupac_name and molecule.iupac_name.lower().startswith(normalized):
            return molecule

    return None


def _fetch_nist_molecule(value):
    """Try NIST WebBook as a fallback chemistry source."""
    target = _normalize_molecule_value(value)
    if not target:
        return None

    encoded = urllib.parse.quote(target)
    url = f"https://webbook.nist.gov/cgi/cbook.cgi?Name={encoded}&Units=SI"
    html = _fetch_url_text(url)
    if not html:
        return None

    formula_match = re.search(r"Formula\s*[:<]?[\s\n]*([A-Z][a-z]?(?:\d+)?(?:[A-Z][a-z]?(?:\d+)?)*)", html, re.I)
    weight_match = re.search(r"Molecular weight\s*[:<]?[\s\n]*([0-9]+(?:\.[0-9]+)?)", html, re.I)

    if not formula_match:
        return None

    formula = formula_match.group(1).strip()
    molecular_weight = float(weight_match.group(1)) if weight_match else 0.0

    return Molecule(
        name=target,
        formula=formula,
        elements=[],
        molecular_weight=molecular_weight,
        iupac_name="",
        smiles="",
        cid=None,
        melting_point=None,
        boiling_point=None,
        density=None,
        state=None,
    )


def fetch_external_molecule(value):
    """Try public chemistry sources once the local JSON does not contain the molecule."""
    target = _normalize_molecule_value(value)
    if not target:
        return None

    # PubChem is the first external source because it is the most complete.
    cid = _find_cid(target)
    if cid is None:
        return _fetch_nist_molecule(target)

    properties = _get_basic_properties(cid)
    if properties is None:
        return _fetch_nist_molecule(target)

    view_data = _get_view_data(cid)
    melting_point = _get_first_temperature(view_data, "Melting Point") if view_data else None
    boiling_point = _get_first_temperature(view_data, "Boiling Point") if view_data else None
    density = _get_first_density(view_data) if view_data else None
    state = _determine_state(melting_point, boiling_point, temperature=25.0) if melting_point is not None and boiling_point is not None else None

    return Molecule(
        name=target,
        formula=properties.get("MolecularFormula", ""),
        elements=[],
        molecular_weight=properties.get("MolecularWeight", 0),
        iupac_name=properties.get("IUPACName", ""),
        smiles=properties.get("SMILES", ""),
        cid=properties.get("CID", cid),
        melting_point=melting_point,
        boiling_point=boiling_point,
        density=density,
        state=state,
    )


def _find_cid(value):
    """
    Find a PubChem CID.

    Tries the input as:
    1. Chemical name
    2. Molecular formula
    """

    if value is None:
        return None

    encoded_value = urllib.parse.quote(str(value), safe="")

    # ---------------------------------------------------------
    # Try chemical name
    # ---------------------------------------------------------
    url = (
        f"{PUBCHEM_BASE_URL}/compound/name/"
        f"{encoded_value}/cids/JSON"
    )

    data = _get_json(url)

    if data:
        identifier_list = data.get("IdentifierList", {})
        cids = identifier_list.get("CID", [])
        if cids:
            return cids[0]

    # ---------------------------------------------------------
    # Try molecular formula
    # ---------------------------------------------------------
    url = (
        f"{PUBCHEM_BASE_URL}/compound/fastformula/"
        f"{encoded_value}/cids/JSON"
    )

    data = _get_json(url)

    if data:
        identifier_list = data.get("IdentifierList", {})
        cids = identifier_list.get("CID", [])
        if cids:
            return cids[0]

    return None


def _get_basic_properties(cid):
    """Get basic molecular properties from PubChem."""

    url = (
        f"{PUBCHEM_BASE_URL}/compound/cid/{cid}/property/"
        "MolecularFormula,MolecularWeight,IUPACName,SMILES/JSON"
    )

    data = _get_json(url)

    if not data:
        return None

    try:
        return data["PropertyTable"]["Properties"][0]

    except (KeyError, IndexError, TypeError):
        return None


def _get_view_data(cid):
    """
    Get the complete PUG-View record.

    PUG-View contains experimental properties such as:
    - Melting Point
    - Boiling Point
    - Density
    """

    url = (
        f"{PUBCHEM_VIEW_URL}/data/compound/{cid}/JSON"
    )

    return _get_json(url)


def _walk_sections(obj):
    """Recursively find PubChem PUG-View sections."""

    if isinstance(obj, dict):

        if "TOCHeading" in obj:
            yield obj

        for value in obj.values():
            yield from _walk_sections(value)

    elif isinstance(obj, list):

        for item in obj:
            yield from _walk_sections(item)


def _find_section(data, heading):
    """Find a PUG-View section by heading."""

    if not data:
        return None

    for section in _walk_sections(data):

        if section.get("TOCHeading", "").lower() == heading.lower():
            return section

    return None


def _extract_text(value):
    """
    Convert PubChem's nested Value structure into text.
    """

    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, list):
        return " ".join(
            text
            for item in value
            if (text := _extract_text(item))
        )

    if isinstance(value, dict):

        # Common PubChem formats
        for key in (
            "StringWithMarkup",
            "String",
            "StringValue",
        ):
            if key in value:
                text = _extract_text(value[key])

                if text:
                    return text

        for key in (
            "Number",
            "FloatValue",
        ):
            if key in value:
                return str(value[key])

        # Fallback
        return " ".join(
            text
            for item in value.values()
            if (text := _extract_text(item))
        )

    return ""


def _get_section_values(data, heading):
    """
    Get the text values reported in a PubChem section.
    """

    section = _find_section(data, heading)

    if not section:
        return []

    values = []

    for information in section.get("Information", []):

        if not isinstance(information, dict):
            continue

        value = information.get("Value")

        text = _extract_text(value)

        if text:
            values.append(text.strip())

    return values


def _parse_temperature(text):
    """
    Convert a temperature string into Celsius.

    Examples:
        "78 °C"       -> 78.0
        "78-80 °C"    -> 79.0
        "172 °F"      -> 77.777...
        "351 K"       -> 77.85

    Returns None if no temperature can be extracted.
    """

    if not text:
        return None

    # ---------------------------------------------------------
    # Find numbers
    # ---------------------------------------------------------
    numbers = re.findall(
        r"[-+]?\d+(?:\.\d+)?",
        text
    )

    if not numbers:
        return None

    values = [float(number) for number in numbers]

    # If it's a range, use the average
    value = sum(values[:2]) / min(len(values), 2)

    text_lower = text.lower()

    # ---------------------------------------------------------
    # Convert to Celsius
    # ---------------------------------------------------------
    if "°f" in text_lower or "deg f" in text_lower:
        return (value - 32) * 5 / 9

    if re.search(r"\bk\b", text_lower):
        return value - 273.15

    # Default / expected unit
    return value


def _parse_density(text):
    """
    Convert density to g/cm^3.

    Examples:
        "1.05 g/mL"  -> 1.05
        "1.05 g/cm3" -> 1.05
        "1050 kg/m3" -> 1.05
        "1.05 g/cm³" -> 1.05
    """

    if not text:
        return None

    match = re.search(
        r"[-+]?\d+(?:\.\d+)?",
        text
    )

    if not match:
        return None

    value = float(match.group(0))
    text_lower = text.lower()

    # ---------------------------------------------------------
    # Convert to g/cm^3
    # ---------------------------------------------------------

    if "kg/m3" in text_lower or "kg/m³" in text_lower:
        return value / 1000

    if "mg/ml" in text_lower:
        return value / 1000

    # g/mL and g/cm3 are numerically equivalent
    if "g/ml" in text_lower:
        return value

    if "g/cm3" in text_lower or "g/cm³" in text_lower:
        return value

    # If PubChem didn't provide a recognizable unit,
    # assume g/cm3 because that is the unit used by this app.
    return value


def _get_first_temperature(data, heading):
    """Get the first reported temperature in Celsius."""

    values = _get_section_values(data, heading)

    for value in values:

        temperature = _parse_temperature(value)

        if temperature is not None:
            return temperature

    return None


def _get_first_density(data):
    """Get the first reported density in g/cm3."""

    values = _get_section_values(data, "Density")

    for value in values:

        density = _parse_density(value)

        if density is not None:
            return density

    return None


def _determine_state(
    melting_point,
    boiling_point,
    temperature=25.0,
):
    """
    Determine physical state at 25 °C.

    Assumes approximately 1 atm pressure.
    """

    if melting_point is None or boiling_point is None:
        return None

    if temperature < melting_point:
        return "solid"

    if temperature >= boiling_point:
        return "gas"

    return "liquid"


def fetch_pubchem_molecule(value):
    """
    Look up a molecule locally, then using PubChem and fallback sources.

    `value` can be:
        - chemical name: "water"
        - molecular formula: "H2O"

    Returns:
        Molecule instance
        or None if the molecule cannot be found.
    """

    local_match = _find_local_molecule(value)
    if local_match is not None:
        return local_match

    # ---------------------------------------------------------
    # Search external chemistry sources when not in the local dataset.
    # ---------------------------------------------------------
    external_match = fetch_external_molecule(value)
    return external_match



MOLECULES = [Molecule(item["name"], item["formula"], item["elements"], item["molecular_weight"], item["iupac_name"] or "", item["smiles"] or "", item["cid"], item["melting_point"], item["boiling_point"], item["density"], item["state"]) for item in molecules]

MOLECULES_BY_FORMULA = {molecule.formula: molecule for molecule in MOLECULES}

def molecule_bond_energy(formula):
    molecule = MOLECULES_BY_FORMULA.get(formula)
    return molecule.total_bond_energy if molecule is not None else 0



class Reaction:
    __slots__ = ("id", "name", "equation", "reaction_type", "reversible", "reactants", "products", "conditions", "notes", "source")
    def __init__(self, id_, name, reaction_type, reversible, reactants, products, conditions, notes, source=""):
        self.id = id_
        self.name = name
        self.reaction_type = reaction_type
        self.reversible = reversible
        self.reactants = reactants
        self.products = products
        self.conditions = conditions
        self.notes = notes
        self.source = source
        subscript_digits = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")

        reactant_text = " + ".join(
            f"{item['stoichiometric_coefficient']} {item['molecule'].translate(subscript_digits)}"
            for item in reactants
        )
        product_text = " + ".join(
            f"{item['stoichiometric_coefficient']} {item['molecule'].translate(subscript_digits)}"
            for item in products
        )
        arrow = " ⇌ " if self.reversible is True else " → " if self.reversible is False else " = "
        self.equation = f"{reactant_text}{arrow}{product_text}"

        if reversible is not None:
            reactant_energy = sum(
                molecule_bond_energy(item["molecule"]) * item["stoichiometric_coefficient"]
                for item in reactants
            )
            product_energy = sum(
                molecule_bond_energy(item["molecule"]) * item["stoichiometric_coefficient"]
                for item in products
            )
            total_energy = reactant_energy - product_energy
            self.equation += f"\tΔH={total_energy}kJ/mol"
        if self.conditions:
            self.equation += "\nConditions:\n"
            for i in self.conditions:
                self.equation += f"\t{i}: {self.conditions[i]}\n"
    def __str__(self):
        return self.equation
    def __repr__(self):
        return self.name


REACTIONS = [Reaction(item["id"], item["name"], item["reaction_type"], item["reversible"], item["reactants"], item["products"], item["conditions"], item["notes"], item.get("source", "")) for item in reactions]
reactionKeys = ("id", "name", "equation", "reaction_type", "reversible", "reactants", "products", "conditions", "notes", "source")
del elements
del reactions
del molecules


def _formula_counts(formula):
    if not isinstance(formula, str) or not formula:
        raise ValueError("Chemical formulas must be non-empty strings")
    symbols = {element.symbol for element in ELEMENTS}

    def parse_group(index, nested=False):
        counts = {}
        while index < len(formula):
            char = formula[index]
            if char == ")":
                if not nested:
                    raise ValueError(f"Unmatched closing parenthesis in formula `{formula}`")
                return counts, index
            if char == "(":
                group, index = parse_group(index + 1, True)
                if index >= len(formula) or formula[index] != ")":
                    raise ValueError(f"Unclosed parenthesis in formula `{formula}`")
                index += 1
                match = re.match(r"\d+", formula[index:])
                multiplier = int(match.group()) if match else 1
                if multiplier <= 0:
                    raise ValueError(f"Invalid atom count in formula `{formula}`")
                if match:
                    index += len(match.group())
                for symbol, amount in group.items():
                    counts[symbol] = counts.get(symbol, 0) + amount * multiplier
                continue
            if not char.isupper():
                raise ValueError(f"Invalid chemical formula `{formula}`")
            end = index + 1
            if end < len(formula) and formula[end].islower():
                end += 1
            symbol = formula[index:end]
            if symbol not in symbols:
                raise ValueError(f"Unknown element `{symbol}` in formula `{formula}`")
            index = end
            match = re.match(r"\d+", formula[index:])
            amount = int(match.group()) if match else 1
            if amount <= 0:
                raise ValueError(f"Invalid atom count in formula `{formula}`")
            if match:
                index += len(match.group())
            counts[symbol] = counts.get(symbol, 0) + amount
        if nested:
            raise ValueError(f"Unclosed parenthesis in formula `{formula}`")
        return counts, index

    counts, end = parse_group(0)
    if end != len(formula) or not counts:
        raise ValueError(f"Invalid chemical formula `{formula}`")
    return counts


def _stoichiometric_species(side):
    if isinstance(side, str):
        species = [item.strip() for item in side.split("+")]
    else:
        species = [str(item).strip() for item in side]
    if not species or any(not item for item in species):
        raise ValueError("Both sides of a reaction must contain molecules")
    return species


def balance_stoichiometry(reactants, products, reversible=None):
    """Balance a reaction and return it as a :class:`Reaction`."""
    reactant_formulas = _stoichiometric_species(reactants)
    product_formulas = _stoichiometric_species(products)
    formulas = reactant_formulas + product_formulas
    formulas_by_element = [_formula_counts(formula) for formula in formulas]
    elements = list(dict.fromkeys(
        element for counts in formulas_by_element for element in counts
    ))
    matrix = [
        [
            Fraction(counts.get(element, 0) * (1 if index < len(reactant_formulas) else -1))
            for index, counts in enumerate(formulas_by_element)
        ]
        for element in elements
    ]

    pivot_columns = []
    pivot_row = 0
    for column in range(len(formulas)):
        selected = next(
            (row for row in range(pivot_row, len(matrix)) if matrix[row][column]),
            None,
        )
        if selected is None:
            continue
        matrix[pivot_row], matrix[selected] = matrix[selected], matrix[pivot_row]
        divisor = matrix[pivot_row][column]
        matrix[pivot_row] = [value / divisor for value in matrix[pivot_row]]
        for row in range(len(matrix)):
            if row == pivot_row or not matrix[row][column]:
                continue
            factor = matrix[row][column]
            matrix[row] = [
                value - factor * pivot
                for value, pivot in zip(matrix[row], matrix[pivot_row])
            ]
        pivot_columns.append(column)
        pivot_row += 1
        if pivot_row == len(matrix):
            break

    free_columns = [
        column for column in range(len(formulas)) if column not in pivot_columns
    ]
    if len(free_columns) != 1:
        raise ValueError("Reaction does not have a unique stoichiometric balance")
    coefficients = [Fraction(0) for _ in formulas]
    free_column = free_columns[0]
    coefficients[free_column] = Fraction(1)
    for row, column in enumerate(pivot_columns):
        coefficients[column] = -matrix[row][free_column]
    if all(value < 0 for value in coefficients):
        coefficients = [-value for value in coefficients]
    if any(value <= 0 for value in coefficients):
        raise ValueError("Reaction cannot be balanced with positive coefficients")

    denominator = 1
    for coefficient in coefficients:
        denominator = denominator * coefficient.denominator // gcd(
            denominator, coefficient.denominator
        )
    integer_coefficients = [
        int(coefficient * denominator) for coefficient in coefficients
    ]
    common_divisor = reduce(gcd, integer_coefficients)
    integer_coefficients = [value // common_divisor for value in integer_coefficients]
    participants = [
        {
            "molecule": formula,
            "stoichiometric_coefficient": coefficient,
        }
        for formula, coefficient in zip(formulas, integer_coefficients)
    ]
    split_at = len(reactant_formulas)
    return Reaction(
        "BALANCED",
        "Balanced reaction",
        "balanced",
        reversible,
        participants[:split_at],
        participants[split_at:],
        {},
        "",
    )


def _execute_balance_command(text):
    text = text.split("//", 1)[0].rstrip()
    match = re.fullmatch(
        r"\s*balance\s+(.+?)\s*(<->|->)\s*(.+?)\s*",
        text,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError("Usage: balance <reactants> ->|<-> <products>")
    reactants, arrow, products = match.groups()
    reversible = arrow == "<->"
    return balance_stoichiometry(reactants, products, reversible)



def queryElement(key, func, value, *params):
    if key not in elementKeys:
        return f"There is no key `{key}`"

    for element in ELEMENTS:
        if getattr(element[key], func)(value, *params):
            return element

    return f"Turns out no element has a {key} of {value}"


def queryElementLast(key, func, value, *params):
    if key not in elementKeys:
        raise KeyError(f"There is no key `{key}`")

    for element in reversed(ELEMENTS):
        if getattr(element[key], func)(value, *params):
            return element

    return f"Turns out no element has a {key} of {value}"


def queryElementAll(key, func, value, *params):
    if key not in elementKeys:
        raise KeyError(f"There is no key `{key}`")

    found = False

    for element in ELEMENTS:
        if getattr(element[key], func)(value, *params):
            found = True
            yield element

    if not found:
        return

class ReturnTable(dict):
    """Dictionary result that prints as a table in the REPL."""

    def __str__(self):
        return format_return_table(self)


def format_return_table(data):
    if not data:
        return ""

    columns = list(data.keys())
    rows = []
    row_count = max((len(data[column]) for column in columns), default=0)

    for i in range(row_count):
        rows.append([str(data[column][i]) if i < len(data[column]) else "" for column in columns])

    widths = [max(len(str(column)), *(len(row[index]) for row in rows)) for index, column in enumerate(columns)]

    header = "  ".join(
        str(column).upper().ljust(widths[index])
        for index, column in enumerate(columns)
    ).rstrip()

    separator = ''.join("─" * i for i  in widths) + "──" *(len(data.keys()) - 1)

    body = ["  ".join(row[index].ljust(widths[index]) for index in range(len(columns))).rstrip() for row in rows]

    return "\n".join([header, separator, *body])


def project_results(results, attributes):
    """Return one column as a 1D list, or multiple columns as a dict of 1D lists."""

    if len(attributes) == 1:
        return [getattr(item, attributes[0]) for item in results]

    return ReturnTable({attribute: [getattr(item, attribute) for item in results] for attribute in attributes})


def sort_results(results, key, descending=False):
    try:
        return sorted(
            results,
            key=lambda item: getattr(item, key),
            reverse=descending
        )
    except (TypeError, AttributeError):
        raise ValueError(f"Cannot sort by `{key}`")

def apply_query_operations(results, tokens, keys, positions=None):
    i = 0

    while i < len(tokens):
        token = tokens[i]

        # sort
        if token == "sort":
            if i + 1 >= len(tokens):
                raise ChemQLError("Expected a key after `sort`", *(error_position(positions, i) if positions else (None, 1))) #type:ignore

            key = tokens[i + 1]

            if key not in keys:
                pos, length = error_position(positions, i + 1) if positions else (None, 1)
                raise ChemQLError(f"There is no key `{key}`", pos, length)

            descending = False

            if i + 2 < len(tokens):
                direction = tokens[i + 2].lower()

                if direction == "asc":
                    i += 1

                elif direction == "desc":
                    descending = True
                    i += 1

            try:
                results = sort_results(
                    results,
                    key,
                    descending
                )
            except ValueError as e:
                pos, length = error_position(positions, i + 1) if positions else (None, 1)
                raise ChemQLError(str(e), pos, length) from e

            i += 2

        # limit
        elif token == "limit":
            if i + 1 >= len(tokens):
                raise ChemQLError("Expected a number after `limit`", *(error_position(positions, i) if positions else (None, 1)))#type:ignore

            try:
                amount = int(tokens[i + 1])
            except ValueError:
                pos, length = error_position(positions, i + 1) if positions else (None, 1)
                raise ChemQLError("`limit` requires an integer", pos, length)

            if amount < 0:
                pos, length = error_position(positions, i + 1) if positions else (None, 1)
                raise ChemQLError("`limit` cannot be negative", pos, length)

            results = results[:amount] # type: ignore

            i += 2

        # count
        elif token == "count":
            if i + 1 < len(tokens):
                pos, length = error_position(positions, i) if positions else (None, 1)
                raise ChemQLError("`count` must be the final query operation", pos, length)

            results = len(results) # type: ignore
            i += 1

        else:
            pos, length = error_position(positions, i) if positions else (None, 1)
            raise ChemQLError(f"Unknown query operation `{token}`", pos, length)

    return results


functionMap = {"=": "__eq__", ">": "__gt__", "<": "__lt__", ">=": "__ge__", "<=": "__le__"}


def convert_value(value, sample):
    """Convert a query value to the type of the element value."""

    if isinstance(sample, bool):

        if value.lower() == "true":
            return True

        if value.lower() == "false":
            return False

        raise ValueError(f"`{value}` is not a boolean")

    if isinstance(sample, (int, float)):

        try:
            number = float(value)

            if number.is_integer():
                return int(number)

            return number

        except ValueError:
            raise ValueError(f"`{value}` is not a number")

    return value


def tokenize_query(arguments):
    """Convert tokens into a form suitable for parsing."""

    return arguments


def parse_condition(tokens, index, source, keys, positions=None):
    if index + 2 >= len(tokens):
        raise ChemQLError("Incomplete condition", *(error_position(positions, index) if positions else (None, 1)))#type:ignore

    key = tokens[index]
    operator = tokens[index + 1]
    value = tokens[index + 2]

    if key not in keys:
        pos, length = error_position(positions, index) if positions else (None, 1)
        raise ChemQLError(f"There is no key `{key}`", pos, length)

    if operator == "like" or operator == "like!":
        pattern = value
        case_sensitive = operator == "like!"

        def like_condition(item):
            actual = getattr(item, key)

            if not isinstance(actual, str):
                return False

            return like_match(
                actual,
                pattern,
                case_sensitive
            )

        return like_condition, index + 3

    if operator == "has":
        def has_condition(item):
            actual = getattr(item, key)

            try:
                return value in actual
            except TypeError:
                return False

        return has_condition, index + 3

    if operator not in functionMap:
        pos, length = error_position(positions, index + 1) if positions else (None, 1)
        raise ChemQLError(f"Unknown operator `{operator}`", pos, length)

    sample = getattr(source[0], key)

    try:
        value = convert_value(value, sample)
    except ValueError as e:
        pos, length = error_position(positions, index + 2) if positions else (None, 1)
        raise ChemQLError(str(e), pos, length) from e

    function = functionMap[operator]

    def comparison_condition(item):
        try:
            return getattr(
                getattr(item, key),
                function
            )(value)
        except (TypeError, AttributeError):
            return False

    return comparison_condition, index + 3

def parse_primary(tokens, index, source, keys, positions=None):
    if index >= len(tokens):
        raise ChemQLError("Expected condition", *(error_position(positions, index) if positions else (None, 1)))#type:ignore

    if tokens[index] == "(":
        expression, index = parse_or(
            tokens,
            index + 1,
            source,
            keys,
            positions
        )

        if index >= len(tokens) or tokens[index] != ")":
            pos = positions[index][0] if positions and index < len(positions) else None
            raise ChemQLError("Missing `)`", pos)

        return expression, index + 1

    return parse_condition(
        tokens,
        index,
        source,
        keys,
        positions
    )


def parse_and(tokens, index, source, keys, positions=None):
    left, index = parse_primary(
        tokens,
        index,
        source,
        keys,
        positions
    )

    while index < len(tokens) and tokens[index] == "and":
        right, index = parse_primary(
            tokens,
            index + 1,
            source,
            keys,
            positions
        )

        previous = left

        left = lambda item, a=previous, b=right: (
            a(item) and b(item)
        )

    return left, index


def parse_or(tokens, index, source, keys, positions=None):
    left, index = parse_and(
        tokens,
        index,
        source,
        keys,
        positions
    )

    while index < len(tokens) and tokens[index] == "or":
        right, index = parse_and(
            tokens,
            index + 1,
            source,
            keys,
            positions
        )

        previous = left

        left = lambda item, a=previous, b=right: (
            a(item) or b(item)
        )

    return left, index


def parse_query(tokens, source, keys, positions=None):
    if not tokens:
        raise ChemQLError("No conditions specified", *(error_position(positions, 0) if positions else (None, 1)))#type:ignore

    # Allow a query to operate on the entire source when it begins
    # with a query operation, e.g. `search molecules count`.
    if tokens[0] in queryOperations:
        return (lambda item: True), 0

    condition, index = parse_or(
        tokens,
        0,
        source,
        keys,
        positions
    )

    # Conditions end when a query operation begins.
    if index < len(tokens) and tokens[index] not in queryOperations:
        pos, length = error_position(positions, index) if positions else (None, 1)
        raise ChemQLError(
            f"Unexpected `{tokens[index]}`", pos, length
        )

    return condition, index



SOURCES = {"elements": (ELEMENTS, elementKeys), "molecules": (MOLECULES, moleculeKeys), "reactions": (REACTIONS, reactionKeys)}


def get_source(source):
    return SOURCES.get(source)

current_source = None

REACTION_TEMPERATURE_TOLERANCE_K = 5.0
REACTION_PRESSURE_TOLERANCE = 0.05
reaction_state = {
    "temperature_k": None,
    "pressure_pa": None,
    "catalysts": [],
}

# Python variables persist for the whole session.
python_globals = {"__builtins__": __builtins__, "math": math}


def find_matching(text, start, opening, closing):
    """Find the matching closing delimiter, allowing nested delimiters."""
    depth = 1
    i = start + len(opening)
    quote = None
    escaped = False

    while i < len(text):
        char = text[i]

        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            i += 1
            continue

        if char in ("'", '"'):
            quote = char
            i += 1
            continue

        if text.startswith(opening, i):
            depth += 1
            i += len(opening)
            continue

        if text.startswith(closing, i):
            depth -= 1
            if depth == 0:
                return i
            i += len(closing)
            continue

        i += 1

    raise SyntaxError(f"Missing `{closing}`")


def interpolate_query(text):
    """Evaluate [Python] expressions inside a query."""
    result = []
    i = 0

    while i < len(text):
        if text[i] == "[":
            end = find_matching(text, i, "[", "]")
            code = text[i + 1:end]
            value = evaluate_python(code)

            if isinstance(value, str):
                result.append(shlex.quote(value))
            elif value is None:
                result.append("None")
            else:
                result.append(shlex.quote(str(value)))

            i = end + 1
            continue

        result.append(text[i])
        i += 1

    return "".join(result)

def interpolate_python_queries(code):
    rewritten = []
    query_values = {}
    query_index = 0
    i = 0

    while i < len(code):
        if code.startswith("{{", i):
            end = find_matching(code, i, "{{", "}}")
            query = code[i + 2:end].strip()

            value = execute_query_block(query)

            name = f"__chemql_query_{query_index}"
            query_index += 1

            query_values[name] = value
            rewritten.append(name)

            i = end + 2
            continue

        rewritten.append(code[i])
        i += 1

    python_globals.update(query_values)
    return "".join(rewritten)

def execute_query_text(text):
    """Execute plain query-language text."""
    text = interpolate_query(text.strip())
    positions = token_positions(text)

    try:
        arguments = shlex.split(text)
    except ValueError as e:
        raise ChemQLError(f"Query syntax error: {e}")

    try:
        return execute(arguments, text, positions)
    except ChemQLError as e:
        if e.position is None:
            raise
        raise


def execute_query(query: str) -> str | Molecule | Element | Reaction | list | None | Unknown:
    """Execute a Chemql query through the public programmatic API."""
    result = execute_query_text(query)

    if isinstance(result, (str, Molecule, Element, Reaction, Unknown)):
        return result

    # Keep the public API total for result types that have not yet been
    # given a dedicated return type (for example lists, ReturnTable, and
    # integer counts).
    return Unknown(result)


def execute_query_block(text):
    # Hybrid code needs the raw query result, so it intentionally bypasses
    # the public Unknown wrapper.
    return execute_query_text(text)


def evaluate_python(code):
    """Evaluate Python, with {{ query }} expressions available inside it.

    If the Python is an expression, its value is returned.
    Otherwise it is executed and None is returned.
    """
    query_values = {}
    rewritten = []
    i = 0
    query_index = 0

    while i < len(code):
        if code.startswith("{{", i):
            end = find_matching(code, i, "{{", "}}")
            query = code[i + 2:end].strip()
            value = execute_query_block(query)

            name = f"__chemql_query_{query_index}"
            query_index += 1
            query_values[name] = value
            rewritten.append(name)
            i = end + 2
            continue

        rewritten.append(code[i])
        i += 1

    rewritten = "".join(rewritten)

    python_globals.update(query_values)

    try:
        tree = ast.parse(rewritten, mode="eval")
    except SyntaxError:
        exec(rewritten, python_globals)
        return None

    return eval(
        compile(tree, "<embedded-python>", "eval"),
        python_globals
    )


def is_python_block_header(text):
    """Recognize [for ...], [if ...], etc. without requiring a colon."""
    text = text.strip()

    if not (text.startswith("[") and text.endswith("]")):
        return False

    code = text[1:-1].strip()

    # Replace {{...}} queries with valid Python variable names
    while "{{" in code:
        start = code.index("{{")
        end = find_matching(code, start, "{{", "}}")
        code = code[:start] + "__chemql_query_placeholder" + code[end + 2:]

    try:
        tree = ast.parse(code + ":\n    pass", mode="exec")
    except SyntaxError:
        return False

    return bool(tree.body) and isinstance(
        tree.body[0],
        (
            ast.For,
            ast.While,
            ast.If,
            ast.With,
            ast.Try,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
        )
    )


def find_endblock(lines, start):
    """Find the matching [endblock], allowing nested blocks."""
    depth = 1

    for i in range(start, len(lines)):
        stripped = lines[i].strip()

        if is_python_block_header(stripped):
            depth += 1

        elif stripped == "[endblock]":
            depth -= 1

            if depth == 0:
                return i

    raise SyntaxError("Missing `[endblock]`")

def remove_comments(line):
    in_quote = None
    escaped = False

    for i in range(len(line) - 1):
        char = line[i]

        if escaped:
            escaped = False
            continue

        if char == "\\" and in_quote:
            escaped = True
            continue

        if char in ('"', "'"):
            if in_quote is None:
                in_quote = char
            elif in_quote == char:
                in_quote = None
            continue

        if line[i:i + 2] == "//" and in_quote is None:
            return line[:i].rstrip()

    return line


class ChemQLBreak(Exception):
    pass
class ChemQLContinue(Exception):
    pass


def execute_for_block(header, body):
    code = header[1:-1].strip()
    code = interpolate_python_queries(code)

    tree = ast.parse(code + ":\n    pass", mode="exec")

    node = tree.body[0]

    if not isinstance(node, ast.For):
        raise SyntaxError("Expected a `for` block")

    iterable = eval(
        compile(ast.Expression(node.iter), "<embedded-python>", "eval"),
        python_globals
    )

    if not hasattr(iterable, "__iter__"):
        iterable = (iterable,)

    for value in iterable:
        temp_name = "__chemql_for_value"
        python_globals[temp_name] = value

        assignment = ast.Assign(
            targets=[node.target],
            value=ast.Name(
                id=temp_name,
                ctx=ast.Load()
            )
        )

        module = ast.Module(
            body=[assignment],
            type_ignores=[]
        )

        ast.fix_missing_locations(module)

        exec(
            compile(
                module,
                "<embedded-python>",
                "exec"
            ),
            python_globals
        )

        try:
            process_lines(body)

        except ChemQLContinue:
            continue

        except ChemQLBreak:
            break


def execute_while_block(header, body):
    code = header[1:-1].strip()

    tree = ast.parse(
        code + ":\n    pass",
        mode="exec"
    )

    node = tree.body[0]

    if not isinstance(node, ast.While):
        raise SyntaxError("Expected a `while` block")

    while eval(
        compile(
            ast.Expression(node.test),
            "<embedded-python>",
            "eval"
        ),
        python_globals
    ):
        try:
            process_lines(body)

        except ChemQLContinue:
            continue

        except ChemQLBreak:
            break


def execute_if_block(header, body):
    """
    Execute an if/elif/else chain.

    The body contains the entire block, including any
    [elif ...] and [else] clauses.
    """

    sections = []

    current_header = header
    current_body = []

    depth = 0

    for line in body:
        stripped = line.strip()

        if is_python_block_header(stripped):
            depth += 1

        elif stripped == "[endblock]":
            depth -= 1

        # Only recognize elif/else belonging to THIS if.
        if depth == 0 and (
            stripped.startswith("[elif ")
            or stripped == "[else]"
        ):
            sections.append(
                (current_header, current_body)
            )

            current_header = stripped
            current_body = []

        else:
            current_body.append(line)

    sections.append(
        (current_header, current_body)
    )

    for section_header, section_body in sections:
        code = section_header[1:-1].strip()

        if code.startswith("if "):
            condition = code[3:].strip()

        elif code.startswith("elif "):
            condition = code[5:].strip()

        elif code == "else":
            process_lines(section_body)
            return

        else:
            raise SyntaxError(
                f"Invalid conditional `{code}`"
            )

        if evaluate_python(condition):
            process_lines(section_body)
            return

def split_commands(text):
    """Split ; commands, but never split inside [], {{}} or strings."""
    commands = []
    start = 0
    i = 0
    square = 0
    curly = 0
    quote = None
    escaped = False

    while i < len(text):
        char = text[i]

        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            i += 1
            continue

        if char in ("'", '"'):
            quote = char
        elif text.startswith("{{", i):
            curly += 1
            i += 2
            continue
        elif text.startswith("}}", i) and curly:
            curly -= 1
            i += 2
            continue
        elif char == "[":
            square += 1
        elif char == "]" and square:
            square -= 1
        elif char == ";" and square == 0 and curly == 0:
            commands.append(text[start:i])
            start = i + 1

        i += 1

    commands.append(text[start:])
    return commands


def process_inline(text):
    """Process one complete line of the chemql language."""
    stripped = text.strip()

    if not stripped:
        return

    # [ ... ] is Python.
    if stripped.startswith("["):
        end = find_matching(stripped, 0, "[", "]")
        if not stripped[end + 1:].strip():
            return evaluate_python(stripped[1:end])

    # {{ ... }} is a query expression.
    if stripped.startswith("{{"):
        end = find_matching(stripped, 0, "{{", "}}")
        if not stripped[end + 2:].strip():
            return execute_query_block(stripped[2:end].strip())

    # Everything else is query language.
    return execute_query_text(stripped)


def join_continuations(lines):
    """Join lines ending in \\ with the following line."""
    joined = []
    buffer = None

    for line in lines:
        if buffer is None:
            buffer = line
        else:
            buffer += line

        if buffer.endswith("\\"):
            buffer = buffer[:-1] + " "
            continue

        joined.append(buffer)
        buffer = None

    if buffer is not None:
        joined.append(buffer)

    return joined


def process_lines(lines):
    lines = join_continuations(lines)
    lines = [remove_comments(line) for line in lines]
    lines = [line for line in lines if line.strip()]
    i = 0

    while i < len(lines):
        
        line = lines[i]
        stripped = line.strip()

        if not line.strip():
            continue

        if stripped == "[endblock]":
            raise SyntaxError("Unexpected `[endblock]`")

        # ----------------------------------------
        # Control-flow block
        # ----------------------------------------

        if is_python_block_header(stripped):
            end = find_endblock(lines, i + 1)
            body = lines[i + 1:end]

            code = stripped[1:-1].strip()

            if code.startswith("for "):
                execute_for_block(
                    stripped,
                    body
                )

            elif code.startswith("while "):
                execute_while_block(
                    stripped,
                    body
                )

            elif code.startswith("if "):
                execute_if_block(
                    stripped,
                    body
                )

            else:
                raise SyntaxError(
                    f"Unsupported block `{code}`"
                )

            i = end + 1
            continue

        # ----------------------------------------
        # break / continue
        # ----------------------------------------

        if stripped == "[break]":
            raise ChemQLBreak()

        if stripped == "[continue]":
            raise ChemQLContinue()

        if stripped == "view":
            view_periodic_table()
            i += 1
            continue


        # ----------------------------------------
        # Normal chemql-language line
        # ----------------------------------------

        for command in split_commands(line):
            result = process_inline(command)

            if result is not None:
                print(result)

        i += 1


def normalize_catalysts(values):
    catalysts = []
    seen = set()

    for value in values:
        catalyst = value.strip()
        normalized = catalyst.casefold()
        if catalyst and normalized not in seen:
            catalysts.append(catalyst)
            seen.add(normalized)

    return catalysts


def parse_temperature_setting(value):
    normalized = value.strip().casefold()
    if normalized == "standard":
        return 273.15
    if normalized == "room":
        return 298.15

    match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*°?\s*([cfk])", normalized)
    if not match:
        raise ValueError("Temperature must use C, F, or K, or be `standard` or `room`")

    temperature = float(match.group(1))
    unit = match.group(2)
    if unit == "f":
        temperature = (temperature - 32) * 5 / 9 + 273.15
    elif unit == "c":
        temperature += 273.15

    if temperature < 0:
        raise ValueError("Temperature cannot be below absolute zero")

    return temperature


def parse_pressure_setting(value):
    normalized = value.strip().casefold()
    if normalized == "standard":
        return 100000.0
    if normalized == "room":
        return 101325.0

    match = re.fullmatch(r"([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(.*?)", normalized)
    if not match:
        raise ValueError("Pressure must be a non-negative value with Pa, N/m^2, bar, or atm units")

    pressure = float(match.group(1))
    unit = re.sub(r"\s+", "", match.group(2)).replace("²", "^2")
    unit_scales = {
        "pa": 1.0,
        "n/m^2": 1.0,
        "nm^-2": 1.0,
        "bar": 100000.0,
        "atm": 101325.0,
    }
    if unit not in unit_scales:
        raise ValueError("Pressure must use Pa, N/m^2, Nm^-2, bar, or atm")

    return pressure * unit_scales[unit]


def _reaction_formula(value):
    normalized = value.casefold()
    for molecule in MOLECULES:
        if molecule.formula.casefold() == normalized:
            return molecule.formula
        if molecule.name.casefold() == normalized or molecule.iupac_name.casefold() == normalized:
            return molecule.formula
    return value


def parse_reactants(values):
    counts = {}
    index = 0

    while index < len(values):
        value = values[index]
        coefficient = 1

        if value.isdigit():
            coefficient = int(value)
            index += 1
            if index >= len(values):
                raise ValueError("Expected a molecule after its coefficient")
            value = values[index]
        else:
            match = re.match(r"^(\d+)(?=[A-Za-z])", value)
            if match:
                coefficient = int(match.group(1))
                value = value[match.end():]

        if coefficient <= 0 or not value:
            raise ValueError("Reactant coefficients must be positive integers")

        formula = _reaction_formula(value)
        key = formula.casefold()
        counts[key] = counts.get(key, 0) + coefficient
        index += 1

    if not counts:
        raise ValueError("Usage: react <coefficient><molecule> ...")

    return counts


def _reaction_side_counts(participants):
    counts = {}
    for participant in participants:
        formula = participant["molecule"]
        key = formula.casefold()
        counts[key] = counts.get(key, 0) + participant["stoichiometric_coefficient"]
    return counts


def _reaction_conditions_match(reaction):
    conditions = reaction.conditions
    temperature = conditions.get("temperature_k")
    if temperature is not None:
        current_temperature = reaction_state["temperature_k"]
        if current_temperature is None or abs(current_temperature - temperature) > REACTION_TEMPERATURE_TOLERANCE_K:
            return False

    pressure = conditions.get("pressure_pa")
    if pressure is not None:
        current_pressure = reaction_state["pressure_pa"]
        if current_pressure is None:
            return False
        tolerance = abs(pressure) * REACTION_PRESSURE_TOLERANCE
        if abs(current_pressure - pressure) > tolerance:
            return False

    required_catalysts = {
        item.casefold() for item in conditions.get("catalysts", [])
    }
    available_catalysts = {
        item.casefold() for item in reaction_state["catalysts"]
    }
    return required_catalysts.issubset(available_catalysts)


def _resolve_reaction_product(participant):
    formula = participant["molecule"]
    for molecule in MOLECULES:
        if molecule.formula.casefold() == formula.casefold():
            return molecule

    name = participant.get("name", formula)
    result = fetch_pubchem_molecule(name)
    if result is None:
        result = fetch_pubchem_molecule(formula)
    return result


def react(values):
    try:
        reactants = parse_reactants(values)
    except ValueError as exc:
        return str(exc)

    matches = []
    for reaction in REACTIONS:
        if not _reaction_conditions_match(reaction):
            continue

        forward = _reaction_side_counts(reaction.reactants)
        if reactants == forward:
            matches.append((reaction, reaction.products))
            continue

        if reaction.reversible is True and reactants == _reaction_side_counts(reaction.products):
            matches.append((reaction, reaction.reactants))

    if not matches:
        return "No reaction matches those reactants and the current temperature, pressure, and catalysts"

    if len(matches) > 1:
        names = ", ".join(f"{reaction.name} ({reaction.id})" for reaction, _ in matches[:5])
        return f"Multiple reactions match: {names}"

    reaction, products = matches[0]
    resolved = []
    for product in products:
        molecule = _resolve_reaction_product(product)
        if molecule is None:
            label = product.get("name", product["molecule"])
            return f"Could not resolve product molecule `{label}` for reaction `{reaction.id}`"
        resolved.append((molecule, product["stoichiometric_coefficient"], product.get("phase")))

    if len(resolved) == 1:
        return resolved[0][0]

    return ReturnTable({
        "molecule": [item[0] for item in resolved],
        "stoichiometric_coefficient": [item[1] for item in resolved],
        "phase": [item[2] or "" for item in resolved],
    })


def current_conditions():
    temperature = reaction_state["temperature_k"]
    pressure = reaction_state["pressure_pa"]
    catalysts = reaction_state["catalysts"]

    temperature_text = f"{temperature:g} K" if temperature is not None else "Not Set"
    pressure_text = f"{pressure:g} Pa" if pressure is not None else "Not Set"
    catalysts_text = ", ".join(catalysts) if catalysts else "Not Set"

    return (
        f"Temperature: {temperature_text}\n"
        f"Pressure: {pressure_text}\n"
        f"Catalysts: {catalysts_text}"
    )


def execute(arguments, query_text=None, positions=None):
    global current_source

    if not arguments:
        return

    if arguments[0].lower() == "balance":
        try:
            return _execute_balance_command(
                query_text if query_text is not None else shlex.join(arguments)
            )
        except ValueError as exc:
            return format_error(str(exc), query_text)

    if arguments[0].lower() in {"help", "?"}:
        return HELP

    if arguments[0].lower() == "sorry":
        return "\033[34mIt's ok, everybody makes mistakes👌\033[0m"

    if arguments[0] == "conditions":
        if len(arguments) != 1:
            return "Usage: conditions"
        return current_conditions()

    if arguments[0] == "set":
        if len(arguments) < 2:
            return "Usage: set temperature|pressure|catalysts <value>"

        setting = arguments[1].lower()
        values = arguments[2:]

        if setting == "temperature":
            if len(values) != 1:
                return "Usage: set temperature <valueC|valueF|valueK|standard|room>"

            try:
                reaction_state["temperature_k"] = parse_temperature_setting(values[0])
            except ValueError as exc:
                return str(exc)

            return f"Temperature set to {reaction_state['temperature_k']:.2f} K"

        if setting == "pressure":
            if len(values) != 1:
                return "Usage: set pressure <valuePa|valueN/m^2|valuebar|valueatm|standard|room>"

            try:
                reaction_state["pressure_pa"] = parse_pressure_setting(values[0])
            except ValueError as exc:
                return str(exc)

            return f"Pressure set to {reaction_state['pressure_pa']:g} Pa"

        if setting == "catalysts":
            reaction_state["catalysts"] = normalize_catalysts(values)
            if not reaction_state["catalysts"]:
                return "Catalysts cleared"
            return f"Catalysts set to {', '.join(reaction_state['catalysts'])}"

        return f"Unknown reaction setting `{setting}`"

    if arguments[0] == "add" and len(arguments) >= 2 and arguments[1].lower() == "catalyst":
        if len(arguments) < 3:
            return 'Usage: add catalyst "name"'

        catalyst = " ".join(arguments[2:]).strip()
        current = reaction_state["catalysts"]
        if catalyst and catalyst.casefold() not in {item.casefold() for item in current}:
            current.append(catalyst)
        return f"Catalysts: {', '.join(current)}" if current else "Catalysts cleared"

    if arguments[0] == "remove" and len(arguments) >= 2 and arguments[1].lower() in {"catalyst", "calatyst"}:
        if len(arguments) < 3:
            return 'Usage: remove catalyst "name"'

        catalyst = " ".join(arguments[2:]).strip()
        reaction_state["catalysts"] = [
            item for item in reaction_state["catalysts"]
            if item.casefold() != catalyst.casefold()
        ]
        return f"Catalysts: {', '.join(reaction_state['catalysts'])}" if reaction_state["catalysts"] else "Catalysts cleared"

    if arguments[0] == "react":
        return react(arguments[1:])

    # Convenience aliases for very common lookups.
    # These are syntactic sugar for normal search queries.
    if arguments[0] == "findel":
        if len(arguments) != 2:
            return "Usage: findel <name-or-symbol>"

        value = arguments[1]
        return execute(
            ["search", "elements", "name", "like", value, "or", "symbol", "like", value]
        )

    if arguments[0] == "findmol":
        if len(arguments) < 2:
            return "Usage: findmol <name-or-formula> [return <attribute> ...]"

        value = arguments[1]

        # Optional return clause
        return_attributes = None

        if "return" in arguments[2:]:
            return_index = arguments.index("return", 2)
            return_attributes = arguments[return_index + 1:]

            if not return_attributes:
                return "Usage: findmol <name-or-formula> return <attribute> ..."

            for attribute in return_attributes:
                if attribute not in moleculeKeys:
                    return f"There is no key `{attribute}`"

            if return_index != 2:
                return "Usage: findmol <name-or-formula> [return <attribute> ...]"

        elif len(arguments) > 2:
            return "Usage: findmol <name-or-formula> [return <attribute> ...]"

        # Search the local dataset first.
        result = execute(
            ["search", "molecules", "name", "like", value, "or", "formula", "like", value]
        )

        if result == [] or result == "No matching item":
            result = fetch_pubchem_molecule(value)

        if result is None:
            return f"Could not find molecule `{value}`"

        if isinstance(result, str) and "PubChem is currently unavailable" in result:
            return result

        if isinstance(result, str) and "could not be found in the recommended sources" in result.lower():
            return result

        # Apply optional projection.
        if return_attributes:
            if isinstance(result, list):
                return project_results(result, return_attributes)

            return ReturnTable({
                attribute: [getattr(result, attribute)]
                for attribute in return_attributes
            })

        return result

    if arguments[0] == "findre":
        if len(arguments) < 2:
            return "Usage: findre <name-or-id> [return <attribute> ...]"

        value = arguments[1]
        return_attributes = None

        if "return" in arguments[2:]:
            return_index = arguments.index("return", 2)
            return_attributes = arguments[return_index + 1:]

            if not return_attributes:
                return "Usage: findre <name-or-id> return <attribute> ..."

            for attribute in return_attributes:
                if attribute not in reactionKeys:
                    return f"There is no key `{attribute}`"

            if return_index != 2:
                return "Usage: findre <name-or-id> [return <attribute> ...]"

        elif len(arguments) > 2:
            return "Usage: findre <name-or-id> [return <attribute> ...]"

        result = execute([
            "search", "reactions",
            "name", "like", value,
            "or", "id", "like", value,
            "or", "equation", "like", value,
        ])

        if result == [] or result == "No matching item":
            return f"Could not find reaction `{value}`"

        if return_attributes:
            if isinstance(result, list):
                return project_results(result, return_attributes)

            return ReturnTable({
                attribute: [getattr(result, attribute)]
                for attribute in return_attributes
            })

        return result

    if arguments[0] == "clear":
        if len(arguments) != 1:
            return "Usage: clear"

        print("\033[2J\033[H", end="")
        return

    if arguments[0] == "source":
        if len(arguments) != 2:
            return "Usage: source <source>"

        source_name = arguments[1]

        if source_name not in SOURCES:
            return f"There is no source `{source_name}`"

        current_source = source_name
        return f"Source set to `{source_name}`"

    if arguments[0] == "list":
        if len(arguments) != 2 or arguments[1] != "all":
            return "Usage: list all"

        if current_source is None:
            return list(SOURCES)

        _, keys = SOURCES[current_source]
        return list(keys)

    if arguments[0] == "search":
        i = 1
        mode = "all"

        if i < len(arguments) and arguments[i] in ("first", "last", "all"):
            mode = arguments[i]
            i += 1

        if (
            i + 1 < len(arguments)
            and arguments[i] in SOURCES
            and (
                current_source is None
                or arguments[i + 1] not in operators
            )
        ):
            source_name = arguments[i]
            i += 1
        else:
            source_name = current_source

        if source_name is None:
            return (
                "No source selected. "
                "Specify one, e.g. "
                "`search all elements atomic_mass < 100`"
            )

        source, keys = SOURCES[source_name]
        return_attributes = None

        if "return" in arguments[i:]:
            return_index = arguments.index("return", i)
            query_tokens = arguments[i:return_index]
            return_attributes = arguments[return_index + 1:]

            if not return_attributes:
                return format_error("Usage: return <attribute> [<attribute> ...]", query_text)

            for attribute_index, attribute in enumerate(return_attributes):
                if attribute not in keys:
                    absolute_index = return_index + 1 + attribute_index
                    pos, length = error_position(positions, absolute_index) if positions else (None, 1)
                    return format_error(
                        f"There is no key `{attribute}`",
                        query_text,
                        pos,
                        length
                    )
        else:
            query_tokens = arguments[i:]

        try:
            condition, operation_index = parse_query(
                query_tokens,
                source,
                keys,
                positions[i:] if positions else None
            )
        except ChemQLError as e:
            return format_error(str(e), query_text, e.position, e.length)
        except ValueError as e:
            return format_error(str(e))

        results = [item for item in source if condition(item)]

        try:
            results = apply_query_operations(
                results,
                query_tokens[operation_index:],
                keys,
                positions[i + operation_index:] if positions else None
            )
        except ChemQLError as e:
            return format_error(str(e), query_text, e.position, e.length)
        except ValueError as e:
            return format_error(str(e))

        if isinstance(results, int):
            if mode != "all":
                return format_error("`count` cannot be combined with `first` or `last`")
            if return_attributes is not None:
                return format_error("`return` cannot be used with `count`")
            return results

        # `return` is a projection. It intentionally happens after
        # filtering, sorting, limiting, and first/last selection.
        if return_attributes is not None:
            if mode == "first":
                selected = results[:1]
            elif mode == "last":
                selected = results[-1:]
            else:
                selected = results

            if not selected:
                if len(return_attributes) == 1:
                    return []
                return ReturnTable({attribute: [] for attribute in return_attributes})

            return project_results(selected, return_attributes)

        if mode == "first":
            result = results[0] if results else None
        elif mode == "last":
            result = results[-1] if results else None
        else:
            if len(results) == 1:
                result = results[0]
            else:
                result = results

        if result is None:
            return "No matching item"

        return result

    if query_text is not None and positions:
        pos, length = error_position(positions, 0)
        return format_error(
            f"Unknown command `{arguments[0]}`",
            query_text,
            pos,
            length
        )

    return format_error(f"Unknown command `{arguments[0]}`")
HELP = """\033[1;36mChemql - Python Chemistry Query Language\033[0m

\033[1;33mQUERYING\033[0m
  \033[1msearch\033[0m
      Search the current source.

            search elements
            search molecules
            search reactions
            search all elements
            search all molecules
            search all reactions

      Example:
        search elements name = "Hydrogen"
        search molecules molecular_weight < 20
        search reactions reaction_type = "combustion"

  \033[1msource\033[0m
      Change the current source.

        source elements
        source molecules
        source reactions

  \033[1mfindel <value>\033[0m
      Find an element by name or symbol.

      Example:
        findel "He"
        findel "Hydrogen"

  \033[1mfindmol <value>\033[0m
      Find a molecule by name or formula.

      Example:
        findmol "H2O"
        findmol "Water"

    \033[1mfindre <name-or-id>\033[0m
            Find a reaction by name, identifier, or equation.

            Example:
                findre "Haber process"
                findre "RHEA:10000" return name equation source

    Reaction fields:
            id, name, equation, reaction_type, reversible,
            reactants, products, conditions, notes

            Example:
                search reactions name like "*combustion*" return name equation
                search reactions reversible = true return name conditions

\033[1;33mFILTERING\033[0m
  Operators:
      =       Equal
      >       Greater than
      <       Less than
      >=      Greater than or equal
      <=      Less than or equal
      like    Pattern match (case-insensitive)
      like!   Pattern match (case-sensitive)
      has     Check whether a value contains an item

  Logical operators:
      and
      or

      Parentheses can be used to group conditions.

      Example:
        search elements atomic_number > 10 and atomic_number < 20
        search molecules name like "*water*"
        search reactions reaction_type = "combustion"

\033[1;33mREACTIONS\033[0m
    Set reaction conditions before using `react`.

            set temperature 723K
            set temperature standard
            set pressure 20265000pa
            set pressure room
            set catalysts iron zinc
            add catalyst "Vanadium oxide"
            remove catalyst "Vanadium oxide"
            set catalysts
              conditions
            react N2 3H2
            balance O2 + H2 -> H2O
            balance O2 + H2 <-> H2O

    Temperature accepts C, F, or K. Pressure accepts Pa, N/m^2, Nm^-2, or bar.
    `standard` means 0 C and 100000 Pa; `room` means 25 C and 101325 Pa.
          Unset values appear as `Not Set` in `conditions`.
    Reaction matching allows 5 K temperature and 5% pressure tolerance.
    `balance` returns a Reaction with the smallest positive integer coefficients.
    The `->` arrow is irreversible; `<->` is reversible. `//` starts a comment.

\033[1;33mRESULTS\033[0m
  \033[1mfirst\033[0m
      Return only the first result.

  \033[1mlast\033[0m
      Return only the last result.

  \033[1msort <key> [asc|desc]\033[0m
      Sort results by an attribute.

      Example:
        search elements sort atomic_number
        search molecules sort molecular_weight desc

  \033[1mlimit <number>\033[0m
      Limit the number of results.

      Example:
        search molecules limit 10

  \033[1mcount\033[0m
      Return the number of results.

      Example:
        search molecules count
        search reactions reversible = true return name equation

  \033[1mreturn <attributes...>\033[0m
      Return only the specified attributes.

      One attribute returns a list.
      Multiple attributes return a table.

      Example:
        search molecules molecular_weight < 20 return name

        search molecules molecular_weight < 20 return name formula molecular_weight

\033[1;33mGENERAL COMMANDS\033[0m
  \033[1mlist all\033[0m
      List keys from the active source or all available sources.

  \033[1mview\033[0m
      Open the periodic table viewer in the default browser.

  \033[1mclear\033[0m
      Clear the current screen.

  \033[1mdump\033[0m
      Export the recent command history to a file.
      Example: dump my_session.txt

  \033[1mhelp\033[0m
      Show this help message.

  \033[1mexit\033[0m
      Exit Chemql.

\033[1;33mHYBRID PYTHON\033[0m
  Chemql can be combined with Python using [ ... ].

      [x = 10]
      [print(x)]

  Python control blocks are also supported:

      [for x in ...]
      [if ...]
      [elif ...]
      [else]
      [while ...]
      [break]
      [continue]
      [endblock]

  ChemQL queries can be embedded directly using {{ ... }}.
  This evaluates the query and inserts its result into the surrounding Python.

      {{ search elements name = "Hydrogen" }}
      [print({{ search elements atomic_number = 1 }})]

  You can also use a bare query block as a value-producing expression:

      {{ search molecules molecular_weight < 20 return name formula }}

\033[1;33mLINE CONTINUATION\033[0m
  A line ending with '\\' continues onto the next line.

      search elements \\
      name = "Hydrogen"

  This is treated as:

      search elements name = "Hydrogen"

\033[1;33mOPTIONS\033[0m
  \033[1m-c <command>\033[0m
      Execute a command.

  \033[1m-f <file>\033[0m
      Execute commands from a file.

  \033[1m?\033[0m
      Show help.

\033[1;33mEXAMPLES\033[0m
  search elements name = "Hydrogen"

  findel "He"

  findmol "H2O"

  search molecules molecular_weight < 20 \\
  return name formula molecular_weight

  search elements atomic_number > 10 \\
  and atomic_number < 20 \\
  sort atomic_number desc \\
  limit 5

  search molecules count

\033[1;36mChemql\033[0m
Python Chemistry Query Language
"""
import webbrowser
from pathlib import Path

def view_periodic_table():
    path = Path(__file__).parent / "html" /"periodic_table.html"
    webbrowser.open(path.resolve().as_uri())

class ChemqlLexer(Lexer):
    def lex_document(self, document):
        lines = document.lines

        def get_line(lineno):
            if lineno >= len(lines):
                return []

            line = lines[lineno]
            tokens = []

            i = 0
            words = line.split()

            # Determine basic query context
            first_word = words[0] if words else ""

            # search / source / list / return / clear / exit
            if first_word in {"search", "source", "list", "clear", "exit", "findel", "findmol", "findre", "set", "add", "remove", "react", "balance", "conditions", "view", "help", "dump"}:
                command_start = line.find(first_word)
                command_end = command_start + len(first_word)

                # Preserve leading whitespace exactly.
                if command_start > 0:
                    tokens.append((
                        "",
                        line[:command_start]
                    ))

                tokens.append((
                    "class:command",
                    first_word
                ))

                i = command_end

            # Everything else is scanned character-by-character
            while i < len(line):
                # Whitespace
                if line[i].isspace():
                    start = i

                    while i < len(line) and line[i].isspace():
                        i += 1

                    tokens.append(("", line[start:i]))
                    continue

                # Python/query blocks
                if line.startswith("{{", i):
                    end = line.find("}}", i + 2)

                    if end == -1:
                        end = len(line) - 2

                    tokens.append((
                        "class:python",
                        line[i:end + 2]
                    ))

                    i = end + 2
                    continue

                if line[i] == "[":
                    end = line.find("]", i + 1)

                    if end == -1:
                        end = len(line) - 1

                    tokens.append((
                        "class:python",
                        line[i:end + 1]
                    ))

                    i = end + 1
                    continue

                # Strings
                if line[i] in "\"'":
                    quote = line[i]
                    start = i
                    i += 1

                    while i < len(line):
                        if line[i] == "\\":
                            i += 2
                            continue

                        if line[i] == quote:
                            i += 1
                            break

                        i += 1

                    tokens.append((
                        "class:string",
                        line[start:i]
                    ))

                    continue

                # Operators
                matched_operator = None

                for operator in (">=", "<=", "=", ">", "<"):
                    if line.startswith(operator, i):
                        matched_operator = operator
                        break

                if matched_operator:
                    tokens.append((
                        "class:operator",
                        matched_operator
                    ))

                    i += len(matched_operator)
                    continue

                # Numbers
                if line[i].isdigit():
                    start = i

                    while i < len(line) and (
                        line[i].isdigit() or line[i] in ".-"
                    ):
                        i += 1

                    tokens.append((
                        "class:number",
                        line[start:i]
                    ))

                    continue

                # Words
                if line[i].isalpha() or line[i] == "_":
                    start = i

                    while i < len(line) and (
                        line[i].isalnum() or line[i] == "_"
                    ):
                        i += 1

                    word = line[start:i]

                    # Commands
                    if word in {
                        "search",
                        "source",
                        "list",
                        "clear",
                        "exit",
                        "return",
                        "set",
                        "add",
                        "remove",
                        "react",
                        "balance",
                        "conditions",
                        "view",
                        "help",
                        "dump"
                    }:
                        style = "class:command"

                    # Sources
                    elif word in SOURCES:
                        style = "class:source"

                    elif word.casefold() in {"temperature", "pressure", "catalyst", "catalysts", "standard", "room", "c", "f", "k", "pa", "bar"}:
                        style = "class:condition"

                    # Operators
                    elif word in {
                        "and",
                        "or",
                        "has",
                        "like",
                        "like!",
                        "sort",
                        "limit",
                        "count",
                        "asc",
                        "desc"
                    }:
                        style = "class:operator"

                    # Control flow
                    elif word in {
                        "if",
                        "elif",
                        "else",
                        "for",
                        "while",
                        "in",
                        "break",
                        "continue",
                        "endblock"
                    }:
                        style = "class:control"

                    # Python constants
                    elif word in {
                        "True",
                        "False",
                        "None"
                    }:
                        style = "class:number"

                    # Dataset keys
                    elif word in elementKeys or word in moleculeKeys or word in reactionKeys:
                        style = "class:key"

                    else:
                        style = ""

                    tokens.append((style, word))
                    continue

                # Anything else
                tokens.append(("", line[i]))
                i += 1

            return tokens

        return get_line

class ChemqlCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        parts = text.split()
        trailing_space = bool(text and text[-1].isspace())
        current = "" if trailing_space or not parts else parts[-1]
        command_words = parts if trailing_space else parts[:-1]
        commands = (
            "search", "source", "list", "clear", "return", "exit",
            "findel", "findmol", "findre", "set", "add", "remove",
            "react", "balance", "conditions",
        )

        if not command_words:
            for command in commands:
                if command.startswith(current):
                    yield Completion(command, start_position=-len(current))
            return

        command = command_words[0]
        suggestions = []

        if len(command_words) == 1:
            if command == "search":
                suggestions = list(SOURCES)
            elif command == "source":
                suggestions = list(SOURCES)
            elif command == "set":
                suggestions = ["temperature", "pressure", "catalysts"]
            elif command in {"add", "remove"}:
                suggestions = ["catalyst"]

        elif command == "set" and len(command_words) == 2:
            setting = command_words[1].casefold()
            if setting == "temperature":
                suggestions = ["standard", "room", "0C", "0F", "0K"]
            elif setting == "pressure":
                suggestions = ["standard", "room", "0Pa", "0N/m^2", "0Nm^-2", "0bar"]
            elif setting == "catalysts":
                suggestions = list(reaction_state["catalysts"])

        elif command == "search" and len(command_words) >= 2:
            source_name = command_words[1]
            if source_name in SOURCES:
                _, keys = SOURCES[source_name]
                suggestions = list(keys) + [
                    "=", ">", "<", ">=", "<=", "like", "like!", "has",
                    "sort", "limit", "count", "asc", "desc", "return",
                ]

        elif command == "remove" and len(command_words) == 2 and command_words[1] == "catalyst":
            suggestions = list(reaction_state["catalysts"])

        for suggestion in suggestions:
            if suggestion.casefold().startswith(current.casefold()):
                yield Completion(suggestion, start_position=-len(current))


        
chemql_style = Style.from_dict({
    "command": "ansicyan",
    "source": "ansiblue",
    "key": "ansimagenta",
    "operator": "ansiyellow",
    "string": "ansigreen",
    "number": "ansimagenta",
    "control": "ansired",
    "python": "ansibrightcyan",
    "condition": "ansibrightyellow",
})


def main():
    parser = argparse.ArgumentParser(
        description="Chemql query and chemistry language"
    )

    parser.add_argument(
        "-c",
        "--command",
        help="Execute Chemql code"
    )

    parser.add_argument(
        "-f",
        "--file",
        help="Execute Chemql code from a file"
    )

    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version="0.2.1",
    )

    args = parser.parse_args()

    if args.command:
        process_lines(args.command.splitlines())

    elif args.file:
        with open(args.file) as f:
            code = f.read()
        process_lines(code.splitlines())

    else:
        run_interactive()

def run_interactive():
        history = []
        print("\033[1mType help or ? for help\033[0m")
        session = PromptSession(
            lexer=ChemqlLexer(),
            completer=ChemqlCompleter(),
            style=chemql_style,
            reserve_space_for_menu=0,
        )
        while True:
            try:
                first_line = session.prompt(">>> ")

            except KeyboardInterrupt:
                print()
                break

            except EOFError:
                print("\n\033[34mUse \033[1mCTRL+C\033[22m or type '\033[1mexit\033[22m' to exit\033[0m")
                continue

            if first_line.strip() == "exit":
                break

            elif first_line.strip() in ("?", "help"):
                print(HELP)
                continue

            elif first_line.strip().lower() == "sorry":
                print("\033[34mIt's ok, everybody makes mistakes👌\033[0m")
                continue
            
            elif first_line.strip().split()[0] == "dump":
                arguments = first_line.strip().split()

                if len(arguments) != 2:
                    print("Usage: dump <file>")
                else:
                    filename = arguments[1]

                    try:
                        with open(filename, "x") as f:
                            f.write("\n".join(history))

                    except FileExistsError:
                        action = choice(
                            message=f"`{filename}` already exists. What would you like to do?",
                            options=[("append", "Append to existing file"), ("overwrite", "Overwrite existing file"), ("cancel", "Cancel")],
                        )

                        if action == "append":
                            with open(filename, "a") as f:
                                f.write("\n" + "\n".join(history))

                        elif action == "overwrite":
                            with open(filename, "w") as f:
                                f.write("\n".join(history))

                continue
        
            if not first_line.strip():
                continue

            # Collect continued input.
            lines = []
            current_line = first_line

            while True:
                if current_line.rstrip().endswith("\\"):
                    current_line = current_line.rstrip()[:-1] + " "

                    try:
                        next_line = session.prompt("... ")
                    except KeyboardInterrupt:
                        print()
                        break
                    except EOFError:
                        print("\n\033[31mError: Incomplete continued input\033[0m")
                        break

                    current_line += next_line
                else:
                    lines.append(current_line)
                    break

            # Collect a Python control block until its matching [endblock].
            if lines and is_python_block_header(lines[0].strip()):
                depth = 1

                while depth:
                    try:
                        line = session.prompt(">>> ")
                    except KeyboardInterrupt:
                        print()
                        break
                    except EOFError:
                        print("\n\033[31mMissing `\033[1m[endblock]\033[22m`\033[0m")
                        break

                    lines.append(line)

                    if is_python_block_header(line.strip()):
                        depth += 1
                    elif line.strip() == "[endblock]":
                        depth -= 1
                else:
                    pass

            try:
                process_lines(lines)
                history.extend(lines)
            except Exception as e:
                print(f"\033[31mError: {e}\033[0m")


if __name__ == "__main__":
    main()
