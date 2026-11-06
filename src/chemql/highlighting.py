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


def _validate_suggestion_rules(rules, extension):
    """Validate context-aware completion rules."""
    if not isinstance(rules, list):
        raise HighlightConfigError(f"{extension}: 'suggestions' must be a list")

    validated = []
    names = set()
    for index, rule in enumerate(rules):
        location = f"{extension}, suggestion rule {index}"
        if not isinstance(rule, dict):
            raise HighlightConfigError(f"{location}: expected an object")

        name = rule.get("name")
        pattern = rule.get("pattern")
        values = rule.get("suggestions")
        min_prefix = rule.get("min-prefix", 0)

        if not isinstance(name, str) or not name.strip():
            raise HighlightConfigError(f"{location}: 'name' must be a non-empty string")
        name = name.strip()
        if name in names:
            raise HighlightConfigError(f"{location}: duplicate suggestion rule name {name!r}")
        if not isinstance(pattern, str) or not pattern:
            raise HighlightConfigError(f"{location}: 'pattern' must be a non-empty string")
        if not isinstance(values, list) or not values:
            raise HighlightConfigError(f"{location}: 'suggestions' must be a non-empty list")
        if not isinstance(min_prefix, int) or isinstance(min_prefix, bool) or min_prefix < 0:
            raise HighlightConfigError(f"{location}: 'min-prefix' must be a non-negative integer")
        if not all(isinstance(value, str) and value for value in values):
            raise HighlightConfigError(f"{location}: every suggestion must be a non-empty string")

        # References must point to an earlier rule, preventing cycles.
        references = re.findall(r"\$([A-Za-z_][A-Za-z0-9_-]*)\$", pattern)
        references += [
            reference
            for value in values
            for reference in re.findall(r"\$([A-Za-z_][A-Za-z0-9_-]*)\$", value)
        ]
        reserved_references = {"active-source-fields", "query-start-options", "query-operators"}
        unknown = sorted(set(references) - names - reserved_references)
        if unknown:
            raise HighlightConfigError(
                f"{location}: unknown or forward suggestion reference(s): "
                + ", ".join(unknown)
            )

        normalized = dict(rule)
        normalized["name"] = name
        normalized["suggestions"] = list(values)
        normalized["min-prefix"] = min_prefix
        validated.append(normalized)
        names.add(name)

    # Check that every pattern is a valid regex after reference expansion.
    by_name = {}
    for rule in validated:
        pattern = _expand_suggestion_references(rule["pattern"], by_name, regex=True)
        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise HighlightConfigError(
                f"{extension}, suggestion rule {rule['name']!r}: invalid regular expression: {exc}"
            ) from exc
        by_name[rule["name"]] = rule

    return validated


def _expand_suggestion_references(value, previous_rules, regex=False, dynamic=None):
    """Expand earlier rule references and runtime context placeholders."""
    dynamic = dynamic or {}

    def replace(match):
        name = match.group(1)
        rule = previous_rules.get(name)
        if rule is not None:
            values = rule["suggestions"]
        elif name in dynamic:
            values = dynamic[name]
        else:
            return match.group(0)
        if regex:
            return "(?:" + "|".join(re.escape(item) for item in values) + ")"
        return "\0".join(values)

    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_-]*)\$", replace, value)


def validate_config(config, *, include_suggestions=False):
    """Validate extension profiles, highlighting rules, suggestions and run commands.

    The original two-value return is preserved unless include_suggestions=True.
    """
    if not isinstance(config, dict):
        raise HighlightConfigError("The configuration must be a JSON object")

    profiles = {}
    run_commands = {}
    suggestion_profiles = {}

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
            suggestions = []
        elif isinstance(profile_config, dict):
            unknown = set(profile_config) - {"rules", "run-command", "suggestions"}
            if unknown:
                names = ", ".join(sorted(map(str, unknown)))
                raise HighlightConfigError(
                    f"{normalized_extension}: unsupported profile field(s): {names}"
                )
            rules = profile_config.get("rules", [])
            run_command = profile_config.get("run-command")
            suggestions = profile_config.get("suggestions", [])
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
        suggestion_profiles[normalized_extension] = _validate_suggestion_rules(
            suggestions, normalized_extension
        )

        if run_command is not None:
            if not isinstance(run_command, str) or not run_command.strip():
                raise HighlightConfigError(
                    f"{normalized_extension}: 'run-command' must be a non-empty string"
                )
            run_commands[normalized_extension] = run_command.strip()

    if include_suggestions:
        return profiles, run_commands, suggestion_profiles
    return profiles, run_commands


def validate_profiles(config):
    """Validate profiles, returning only their highlighting rules."""
    profiles, _ = validate_config(config)
    return profiles


class HighlightProfiles:
    """Loads and provides syntax-highlighting and inline-completion profiles."""

    def __init__(self, config_path=None):
        self.config_path = config_path
        self.profiles, self.run_commands, self.suggestion_profiles = validate_config(
            BUILTIN_PROFILES, include_suggestions=True
        )

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

        loaded_profiles, loaded_commands, loaded_suggestions = validate_config(
            config, include_suggestions=True
        )

        self.profiles.update(loaded_profiles)
        # A later profile replaces the earlier extension profile as a whole.
        for extension in loaded_profiles:
            self.run_commands.pop(extension, None)
            self.suggestion_profiles.pop(extension, None)
        self.run_commands.update(loaded_commands)
        self.suggestion_profiles.update(loaded_suggestions)
        self.config_path = path

        return self.profiles

    def get(self, filename, default=None):
        """Get the highlighting rules associated with a filename."""
        extension = os.path.splitext(filename)[1].lower()
        return self.profiles.get(extension, default)

    def register(self, extension, rules):
        """Register or replace a highlighting profile programmatically."""
        extension = normalize_extension(extension)
        validated = validate_profiles({extension: rules})
        self.profiles[extension] = validated[extension]
        self.run_commands.pop(extension, None)
        self.suggestion_profiles.pop(extension, None)
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

    def get_suggestion_suffix(self, filename, line, cursor, previous_lines=None):
        """Return the completion suffix for the first matching context rule.

        Context rules match text before the current token. The active ChemQL
        source is inferred from the latest preceding ``source`` command, with
        an explicit source in the current search taking precedence.
        """
        extension = os.path.splitext(filename)[1].lower()
        rules = self.suggestion_profiles.get(extension, [])
        if not rules:
            return ""

        before_cursor = line[:cursor]
        token_match = re.search(r"(\S*)$", before_cursor)
        prefix = token_match.group(1) if token_match else ""
        context = before_cursor[:len(before_cursor) - len(prefix)]

        source_fields = {
            "elements": [
                "name", "symbol", "number", "atomic_mass", "appearance", "category",
                "phase", "density", "melt", "boil", "molar_heat", "period", "group",
                "block", "shells", "electron_configuration", "electron_configuration_semantic",
                "electron_affinity", "electronegativity_pauling", "ionization_energies",
                "discovered_by", "named_by", "summary", "source", "image",
                "bohr_model_image", "bohr_model_3d", "spectral_img", "xpos", "ypos",
                "wxpos", "wypos", "cpk_hex", "cpk-hex"
            ],
            "molecules": [
                "name", "formula", "elements", "molecular_weight", "iupac_name", "smiles",
                "cid", "melting_point", "boiling_point", "density", "state", "bonds",
                "total_bond_energy"
            ],
            "reactions": [
                "id", "name", "equation", "reaction_type", "reversible", "reactants",
                "products", "conditions", "notes", "source"
            ],
        }
        active_source = None
        history = list(previous_lines or []) + [line[:cursor]]
        for index, historical_line in enumerate(history):
            # Ignore ordinary line comments when looking for source selection.
            statement = historical_line.split("//", 1)[0]
            for match in re.finditer(
                r"(?:^|;)\s*source\s+(elements|molecules|reactions)\b",
                statement,
                re.IGNORECASE,
            ):
                active_source = match.group(1).casefold()

            # An explicit source in the statement currently being edited
            # controls this query, without changing the persistent selection.
            if index == len(history) - 1:
                current_statement = statement.rsplit(";", 1)[-1]
                explicit = re.match(
                    r"\s*search\s+(?:(?:first|last|all)\s+)?(elements|molecules|reactions)\b",
                    current_statement,
                    re.IGNORECASE,
                )
                if explicit:
                    active_source = explicit.group(1).casefold()

        dynamic = {
            "active-source-fields": source_fields.get(active_source, []),
            "query-start-options": (
                source_fields[active_source]
                if active_source else ["elements", "molecules", "reactions"]
            ),
            "query-operators": [
                "=", "!=", ">", "<", ">=", "<=", "like", "like!", "likep", "has",
                "and", "or", "sort", "limit", "count", "return", "first", "last"
            ],
        }

        previous = {}
        for rule in rules:
            if len(prefix) < rule.get("min-prefix", 0):
                previous[rule["name"]] = rule
                continue

            pattern = _expand_suggestion_references(rule["pattern"], previous, regex=True)
            try:
                matched = re.search(pattern, context, re.IGNORECASE) is not None
            except re.error:
                matched = False

            if matched:
                candidates = []
                for value in rule["suggestions"]:
                    expanded = _expand_suggestion_references(value, previous, regex=False, dynamic=dynamic)
                    candidates.extend(expanded.split("\0"))

                for candidate in candidates:
                    if candidate.casefold().startswith(prefix.casefold()) and len(candidate) > len(prefix):
                        return candidate[len(prefix):]
                return ""

            previous[rule["name"]] = rule

        return ""
