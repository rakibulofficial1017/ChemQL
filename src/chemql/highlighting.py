
import json
import os
import re


SUPPORTED_RULE_TYPES = {"keywords", "regex"}
BUILTIN_PROFILES = {
    ".cql": [
        {
            "name": "commands",
            "type": "keywords",
            "values": [
                "search", "source", "list", "clear", "return", "exit",
                "findel", "findmol", "findre", "set", "add", "remove",
                "react", "balance", "conditions", "view", "help", "dump",
                "version", "let", "unset", "variables", "func", "define",
                "load", "import", "signal", "fix", "cleanup", "arguments"
            ],
            "style": "command"
        },
        {
            "name": "control-keywords",
            "type": "keywords",
            "values": [
                "if", "elif", "else", "endif", "for", "while", "in",
                "endfor", "endwhile", "break", "continue", "endblock",
                "from", "as", "public", "private", "required", "struct",
                "record", "enum", "endstruct", "static", "endrecord",
                "endenum", "namespace", "endnamespace"
            ],
            "style": "keyword"
        },
        {
            "name": "word-operators",
            "type": "keywords",
            "values": [
                "and", "or", "has", "like", "like!", "likep", "sort",
                "limit", "count", "first", "last", "asc", "desc",
                "union", "intersection"
            ],
            "style": "operator"
        },
        {
            "name": "sources",
            "type": "keywords",
            "values": ["elements", "molecules", "reactions"],
            "style": "source"
        },
        {
            "name": "conditions",
            "type": "keywords",
            "values": [
                "temperature", "pressure", "catalyst", "catalysts",
                "standard", "room", "c", "f", "k", "pa", "kpa",
                "mpa", "hpa", "bar", "atm", "torr", "mmhg", "psi"
            ],
            "style": "condition"
        },
        {
            "name": "properties",
            "type": "keywords",
            "values": """
                name appearance atomic_mass boil category density
                discovered_by melt molar_heat named_by number period
                group phase source bohr_model_image bohr_model_3d
                spectral_img summary symbol xpos ypos wxpos wypos
                shells electron_configuration electron_configuration_semantic
                electron_affinity electronegativity_pauling ionization_energies
                cpk_hex cpk-hex image block formula elements molecular_weight
                iupac_name smiles cid melting_point boiling_point state bonds
                total_bond_energy id equation reaction_type reversible reactants
                products conditions notes
            """.split(),
            "style": "property"
        }
    ]
}

class HighlightConfigError(ValueError):
    """Raised when a syntax-highlighting configuration is invalid."""


def normalize_extension(extension):
    """Normalize a file extension to lowercase with a leading dot."""
    extension = extension.strip().lower()

    if not extension:
        raise HighlightConfigError("File extension cannot be empty")

    if not extension.startswith("."):
        extension = "." + extension

    if extension == "." or "/" in extension or "\\" in extension:
        raise HighlightConfigError(f"Invalid file extension: {extension!r}")

    return extension


def validate_rule(rule, extension, index):
    """Validate and normalize one highlighting rule."""
    location = f"{extension}, rule {index}"

    if not isinstance(rule, dict):
        raise HighlightConfigError(f"{location}: expected an object")

    rule_type = rule.get("type")

    if rule_type not in SUPPORTED_RULE_TYPES:
        raise HighlightConfigError(
            f"{location}: unsupported rule type {rule_type!r}"
        )

    name = rule.get("name")
    style = rule.get("style")

    if not isinstance(name, str) or not name.strip():
        raise HighlightConfigError(f"{location}: 'name' must be a non-empty string")

    if not isinstance(style, str) or not style.strip():
        raise HighlightConfigError(f"{location}: 'style' must be a non-empty string")

    normalized = dict(rule)

    if rule_type == "keywords":
        values = rule.get("values")

        if not isinstance(values, list) or not values:
            raise HighlightConfigError(
                f"{location}: 'values' must be a non-empty list"
            )

        if not all(isinstance(value, str) and value for value in values):
            raise HighlightConfigError(
                f"{location}: every keyword must be a non-empty string"
            )

        normalized["values"] = values

    elif rule_type == "regex":
        pattern = rule.get("pattern")

        if not isinstance(pattern, str) or not pattern:
            raise HighlightConfigError(
                f"{location}: 'pattern' must be a non-empty string"
            )

        try:
            re.compile(pattern)
        except re.error as exc:
            raise HighlightConfigError(
                f"{location}: invalid regular expression: {exc}"
            ) from exc

        case_sensitive = rule.get("case_sensitive", True)

        if not isinstance(case_sensitive, bool):
            raise HighlightConfigError(
                f"{location}: 'case_sensitive' must be a boolean"
            )

        normalized["case_sensitive"] = case_sensitive

    return normalized


def validate_config(config):
    """Validate extension profiles and optional run commands."""
    if not isinstance(config, dict):
        raise HighlightConfigError("The configuration must be a JSON object")

    profiles = {}
    run_commands = {}

    for extension, profile_config in config.items():
        normalized_extension = normalize_extension(extension)

        if normalized_extension in profiles:
            raise HighlightConfigError(
                f"Duplicate extension: {normalized_extension}"
            )

        # Backwards compatibility: the original format was a list of rules.
        if isinstance(profile_config, list):
            rules = profile_config
            run_command = None
        elif isinstance(profile_config, dict):
            unknown = set(profile_config) - {"rules", "run-command"}
            if unknown:
                names = ", ".join(sorted(map(str, unknown)))
                raise HighlightConfigError(
                    f"{normalized_extension}: unsupported profile field(s): {names}"
                )
            rules = profile_config.get("rules", [])
            run_command = profile_config.get("run-command")
        else:
            raise HighlightConfigError(
                f"{normalized_extension}: expected a list or profile object"
            )

        if not isinstance(rules, list):
            raise HighlightConfigError(
                f"{normalized_extension}: 'rules' must be a list"
            )

        profiles[normalized_extension] = [
            validate_rule(rule, normalized_extension, index)
            for index, rule in enumerate(rules)
        ]

        if run_command is not None:
            if not isinstance(run_command, str) or not run_command.strip():
                raise HighlightConfigError(
                    f"{normalized_extension}: 'run-command' must be a non-empty string"
                )
            run_commands[normalized_extension] = run_command.strip()

    return profiles, run_commands


def validate_profiles(config):
    """Validate profiles, returning only their highlighting rules."""
    profiles, _ = validate_config(config)
    return profiles


class HighlightProfiles:
    """Loads and provides syntax-highlighting profiles."""

    def __init__(self, config_path=None):
        self.config_path = config_path
        self.profiles, self.run_commands = validate_config(BUILTIN_PROFILES)

        if config_path:
            self.load(config_path)

    def load(self, config_path=None):
        """Load profiles from a JSON file."""
        path = config_path or self.config_path

        if not path:
            raise HighlightConfigError("No configuration path was provided")

        try:
            with open(path, encoding="utf-8") as config_file:
                config = json.load(config_file)
        except json.JSONDecodeError as exc:
            raise HighlightConfigError(
                f"Invalid JSON in {path}: {exc}"
            ) from exc
        except OSError as exc:
            raise HighlightConfigError(
                f"Could not read {path}: {exc}"
            ) from exc

        loaded_profiles, loaded_commands = validate_config(config)

        self.profiles.update(loaded_profiles)
        # A later profile replaces the earlier extension profile as a whole.
        for extension in loaded_profiles:
            self.run_commands.pop(extension, None)
        self.run_commands.update(loaded_commands)
        self.config_path = path

        return self.profiles

    def get(self, filename, default=None):
        """Get the profile associated with a filename."""
        extension = os.path.splitext(filename)[1].lower()
        return self.profiles.get(extension, default)

    def register(self, extension, rules):
        """Register or replace a profile programmatically."""
        extension = normalize_extension(extension)

        validated = validate_profiles({extension: rules})
        self.profiles[extension] = validated[extension]
        self.run_commands.pop(extension, None)

        return self.profiles[extension]

    def get_keyword_style(self, filename, word):
        """Return the configured style category for a keyword."""
        profile = self.get(filename, [])

        for rule in profile:
            if rule["type"] == "keywords":
                if word.casefold() in {
                    value.casefold() for value in rule["values"]
                }:
                    return rule["style"]

        return None

    def get_run_command(self, filename):
        """Return the configured run-command for a filename, if any."""
        extension = os.path.splitext(filename)[1].lower()
        return self.run_commands.get(extension)
