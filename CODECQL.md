# CodecQL

**A small terminal editor built for [ChemQL](README.md).** Syntax highlighting, inline suggestions, a built-in terminal pane and one-key execution, with nothing to configure to get started.

| | |
|---|---|
| Version | 0.1.0 |
| Ships with | `chemql-python` |
| Files | `.cql` (ChemQL), `.py`, `cqlpackage.json` / `cqlpackage.toml`, and any plain-text file |

```bash
chemql edit script.cql
```

---

## Contents

- [Starting CodecQL](#starting-codecql)
- [Key bindings](#key-bindings)
- [Search](#search)
- [Running code and the terminal pane](#running-code-and-the-terminal-pane)
- [Syntax highlighting](#syntax-highlighting)
- [Inline suggestions](#inline-suggestions)
- [Configuration: `highlighting.json`](#configuration-highlightingjson)
- [Suggestion rules in depth](#suggestion-rules-in-depth)
- [What the bundled rules complete](#what-the-bundled-rules-complete)
- [Colours: `colors.json`](#colours-colorsjson)
- [Known limitations](#known-limitations)

---

## Starting CodecQL

```bash
chemql edit FILE                       # open (or create) a file
python -m chemql.codecql FILE          # equivalent
chemql edit --main-highlighting        # edit the highlighting.json shipped with the package
chemql edit --local-highlighting       # edit ./highlighting.json (created as {} if missing)
chemql edit --version
```

If your installation also registers a `codecql` console script, `codecql FILE` accepts the same options.

Opening a path that does not exist starts an empty buffer; it is created on the first save.

**Requirements:** the same as ChemQL (Python 3.12+), plus a terminal that understands ANSI escape sequences and 256 colours. On Windows, `colorama` is used when installed; otherwise virtual-terminal mode is enabled directly. Copying to the system clipboard needs one of `clip` (Windows), `clip.exe` (WSL), `pbcopy` (macOS), or `wl-copy` / `xclip` / `xsel` (Linux).

---

## Key bindings

| Key | Action |
|---|---|
| `Ctrl+S` | Save |
| `Ctrl+Q` | Quit. With unsaved changes, press it a second time to quit without saving |
| `Ctrl+Z` / `Ctrl+Y` | Undo / redo (last 200 edits) |
| `Ctrl+F` | [Search](#search) |
| `Ctrl+R` | Save, then [run the file](#running-code-and-the-terminal-pane) |
| `Ctrl+T` | Open a terminal pane |
| `Tab` | Accept the inline suggestion; with none showing, insert a tab |
| `Enter` | New line, keeping the current indentation (see below) |
| Arrow keys, `Home`, `End` | Move |
| `Shift` + movement | Select |
| `Ctrl`/`Alt` + `←` `→` | Move by word |
| `Ctrl` + `↑` `↓` | Scroll the view without moving the text |
| `Backspace`, `Delete` | Delete a character, or the selection |
| `Ctrl+Backspace` / `Alt+Backspace` | Delete the word to the left |
| `Ctrl+Delete` / `Alt+Delete` | Delete the word to the right |
| `Ctrl+C` / `Ctrl+Insert` | Copy the selection (to the editor and to the system clipboard when available). It does **not** quit |
| `Ctrl+X` | Cut the selection |
| `Ctrl+V` / `Shift+Insert` | Paste the editor's clipboard |

Pasting from your terminal or OS clipboard also works: CodecQL enables bracketed paste, so multi-line pastes arrive as a single insertion.

**Auto-indent.** After a line that opens a block (`func`, `define NAME{}`, `struct`, `record`, `enum`, `namespace`, `if`, `elif`, `else`, `for`, `while`) or ends in a `\` continuation, the next line is indented with a tab. Pressing Enter after `endnamespace` removes one level of indentation. Other `end...` keywords do not dedent automatically.

**Status bar and footer.** The bar shows the file name, `Ln`/`Col`, the line count, `Unsaved` when the buffer is dirty, and search status. The footer shows messages and a reminder of the main shortcuts.

---

## Search

Press `Ctrl+F` and type; matches are highlighted as you type.

| Key | Action |
|---|---|
| `Enter`, `↓`, `→` | Next match |
| `↑`, `←` | Previous match |
| `Esc`, `Ctrl+C` | Close search |

A plain query is a **literal, case-insensitive** search. Add a flag prefix followed by `:` to change that:

| Flag | Meaning |
|---|---|
| `r` | Treat the query as a regular expression |
| `l` | Treat the query as literal text (the default; cannot be combined with `r`) |
| `w` | Match whole words only |
| `i` | Ignore case |

Once any flag is given, matching becomes case-sensitive unless `i` is included.

```text
water            literal, case-insensitive
l:Water          literal, case-sensitive
r:^search\s      regular expression, case-sensitive
ri:^search\s     regular expression, case-insensitive
wi:set           whole word "set", case-insensitive
```

An invalid regular expression is reported in the status bar.

---

## Running code and the terminal pane

**`Ctrl+R`** saves the file (if it has unsaved changes) and runs the command configured for its extension. The default for `.cql` is:

```text
chemql -f $absoluteName
```

`$absoluteName` is replaced by the shell-quoted absolute path. Set your own with `run-command` in [`highlighting.json`](#configuration-highlightingjson); the bundled configuration also runs `.py` files with `python -u` and `.rs` files with `cargo run`. The file must have a name before it can be run.

**`Ctrl+T`** opens a plain terminal without running anything.

| Platform | Behaviour |
|---|---|
| Linux, macOS, WSL | A pane opens in the bottom third of the screen running your `$SHELL` (`-i`). `Ctrl+↑` / `Ctrl+↓` resize it. `Ctrl+T`, `Ctrl+Q` or `Esc` closes it and returns to the editor. |
| Windows Terminal | The command runs in a new split pane beside the editor. Close it by exiting the shell. |
| Other Windows consoles | The command runs in a separate console window. |

---

## Syntax highlighting

What is coloured depends on the file:

| File | Highlighting |
|---|---|
| `.cql` | Comments (`//`, `#`), strings, numbers (including units such as `25C`, `1atm`), chemical formulas (`H2O`, `NaCl`), operators, delimiters (`{{ }}`, `[[[ ]]]`, brackets), commands, control keywords, word operators (`and`, `like`, `sort`, ...), sources, reaction conditions, field names, Python built-ins, `True`/`False`/`None`, and the name after `enum`/`struct`/`record`/`namespace` |
| `.py` | Python keywords, built-ins and constants, plus comments, strings, numbers and operators |
| `cqlpackage.json`, `cqlpackage.toml` | Keys, strings, numbers, booleans, TOML tables and comments |
| anything else | Comments, strings, numbers, operators and delimiters only |

Highlighting is purely lexical and line-based: it never changes the file. Extensions are matched case-insensitively.

---

## Inline suggestions

While you type at the **end of a line**, CodecQL shows a grey "ghost" completion. Press `Tab` to accept it. Suggestions are context-aware: they depend on what comes before the cursor on the line (and, for queries, on the most recent `source` command above it).

```text
se|                              ->  search
search |                         ->  search elements
search elements na|              ->  search elements name
search elements atomic_mass |    ->  search elements atomic_mass >
search elements phase = |        ->  search elements phase = "Gas"
```

Suggestions are driven entirely by the `suggestions` rules in [`highlighting.json`](#configuration-highlightingjson), so you can change or extend them without touching Python. They are only offered when the cursor is at the end of the line and nothing is selected.

---

## Configuration: `highlighting.json`

CodecQL loads configuration from two places, in this order:

1. `highlighting.json` in the package directory (`chemql edit --main-highlighting` opens it)
2. `highlighting.json` in the current working directory (`chemql edit --local-highlighting` opens it)

> **Each extension's profile is replaced as a whole.** If the local file defines `".cql"`, it completely replaces the main file's `.cql` profile, including its `run-command` and `suggestions`. Copy what you want to keep.

### Profile format

The top level maps file extensions to profiles. A leading dot is added if you omit it, and extensions are lower-cased.

```json
{
    ".cql": {
        "run-command": "chemql -f $absoluteName",
        "rules": [],
        "suggestions": []
    },
    ".py": {
        "run-command": "python -u $absoluteName",
        "rules": []
    }
}
```

| Field | Description |
|---|---|
| `run-command` | Command run by `Ctrl+R`. `$absoluteName` is replaced by the quoted path. |
| `rules` | Highlighting rules (below). |
| `suggestions` | [Suggestion rules](#suggestion-rules-in-depth). |

An older format, where an extension maps directly to a list of rules, is still accepted. Unknown profile fields and duplicate extensions are rejected, and a configuration error is reported when the file is loaded.

### Highlighting rules

```json
{
    "name": "my-keywords",
    "type": "keywords",
    "values": ["alpha", "beta"],
    "style": "keyword"
}
```

| Field | Description |
|---|---|
| `name` | Non-empty label |
| `type` | `keywords` or `regex` |
| `values` | For `keywords`: a non-empty list of words. Matching is case-insensitive |
| `pattern`, `case_sensitive` | For `regex`: a valid regular expression, and whether it is case-sensitive (default `true`) |
| `style` | A style string, below |

Rules are checked in order and the first matching keyword wins. A keyword rule takes priority over CodecQL's built-in categories for that extension, so with an empty `rules` list for `.cql` the built-in ChemQL highlighting applies unchanged.

> Currently only `keywords` rules affect how text is drawn. `regex` rules are validated but not yet applied.

**Style strings** combine space-separated parts:

| Part | Effect |
|---|---|
| `keyword` `command` `operator` `string` `comment` `number` `constant` `type` `source` `condition` `property` `builtin` | A colour from the current theme |
| `bold` `dim` `italic` `underline` `reverse` `strike` | Text attributes |
| `#rrggbb` | 24-bit foreground colour |
| `bg:#rrggbb` | 24-bit background colour |

```json
"style": "bold #ff8800"
```

An unknown part is an error, so stick to this list.

### Example: highlighting a new language

```json
{
    ".toml": {
        "run-command": "cat $absoluteName",
        "rules": [
            {"name": "booleans", "type": "keywords", "values": ["true", "false"], "style": "constant"}
        ]
    }
}
```

---

## Suggestion rules in depth

A suggestion rule says: *when the text before the cursor looks like this, offer these completions.*

```json
{
    "name": "second-word",
    "pattern": "(?:^|;|\\{\\{)\\s*search\\s+$",
    "min-prefix": 0,
    "suggestions": ["elements", "molecules", "reactions"]
}
```

| Field | Description |
|---|---|
| `name` | Unique, non-empty. Used by `$name$` references |
| `pattern` | Regular expression, searched **case-insensitively** in the *context* (below) |
| `suggestions` | Non-empty list of completions |
| `min-prefix` | Minimum number of characters already typed in the current word before the rule applies (default `0`) |

### How a rule is chosen

1. The line up to the cursor is split into a **prefix**, the run of non-whitespace characters just before the cursor, and a **context**, everything before that prefix (including the whitespace).
2. Rules are tried **in order**. The **first** rule whose pattern matches the context wins, and no later rule is consulted, even if the winner offers nothing for the current prefix.
3. From the winner's `suggestions`, the first entry that starts with the prefix (case-insensitively) and is longer than it is chosen. The untyped remainder is shown as ghost text, and `Tab` inserts it.

This has practical consequences when you write rules:

- **Order matters. Put specific rules before general ones.** A broad rule placed early will shadow everything after it.
- **Anchor with `$`.** To mean "the cursor follows this word", end the pattern with `\s+$`. The context always ends with the whitespace before the prefix.
- **Prefixes are whitespace-delimited.** In `help{ab`, the prefix is the whole `help{ab`, so completions after punctuation without a space are not possible. Design completions around spaces.
- **A suggestion may contain spaces.** `"{{ search elements"` is offered once the prefix is `{`, and it is inserted as a whole.
- **Use `min-prefix: 1` for free-form positions**, so a ghost does not appear (and `Tab` still inserts a tab) before you have typed anything.
- **Remember JSON escaping.** Every regex backslash is doubled: `\s` is written `"\\s"`.

### References

| Syntax | In a `pattern` | In a `suggestions` entry |
|---|---|---|
| `$rule-name$` | Replaced by an alternation of that rule's suggestions, e.g. `(?:search\|source\|...)` | Replaced by all of that rule's suggestions |
| `$active-source-fields$` | *(not supported)* | Field names of the active source: the source in the current `search` statement if it names one, otherwise the most recent `source` command above the line. Empty if there is none |
| `$query-start-options$` | *(not supported)* | The active source's fields, or the three sources when there is no active source |
| `$query-operators$` | *(not supported)* | `= != > < >= <= like like! likep has and or sort limit count return first last` |

A `$rule-name$` reference must point at a rule defined **earlier** in the list, which also rules out cycles. References are expanded one level: a referenced rule's own `$...$` entries are not expanded further.

### Reference-only rules

A rule whose pattern is `(?!)` can never match, so it never fires. The bundled configuration uses this to hold named lists, such as all field names or all operators, which later rules splice into their patterns and suggestions:

```json
{ "name": "operators", "pattern": "(?!)", "min-prefix": 0,
  "suggestions": ["=", "!=", ">", "<", ">=", "<=", "like", "like!", "likep", "has"] }
```

A later rule can then recognise "a field name followed by an operator" with `\\s(?:$all-fields$)\\s+(?:$operators$)\\s+$`.

### Testing a rule

The engine is plain Python, so you can try rules without opening the editor:

```python
from chemql.highlighting import HighlightProfiles

profiles = HighlightProfiles("highlighting.json")
line = "search elements atomic_mass "
suffix = profiles.get_suggestion_suffix("x.cql", line, len(line), previous_lines=[])
print(line + suffix)          # search elements atomic_mass >
```

`previous_lines` supplies the lines above, which is how the active `source` is found.

---

## What the bundled rules complete

The shipped `highlighting.json` defines about 70 rules for `.cql`. In summary:

| Context | Suggests |
|---|---|
| Start of a line, or after `;` (after 1 character) | Every ChemQL command and block keyword |
| After `{{` | Query commands (`search`, `findel`, `findmol`, `findre`, ...) |
| `search ` | Sources, `first`/`last`/`all`, and the active source's fields |
| `search SOURCE ` | That source's fields, plus `not`, `sort`, `limit`, `count` |
| After a field | Operators that suit its type: numeric (`>` `<` `=` ...), text (`like` `=` `has` ...), collection (`has`), boolean (`=` `!=`) |
| After `not` | Operators, or fields when negating a whole condition |
| After an operator | Known values for `phase`, `category`, `block`, `state` and `reversible` |
| After a complete condition | `and`, `or`, `sort`, `limit`, `count`, `return`, `union`, `intersection` |
| After `and`, `or`, `not`, `(` | Fields |
| After `sort`, `limit` | Fields, `asc`/`desc`, then `limit`/`count`/`return`; common limits |
| After `return` | Fields |
| After `union` / `intersection` | `search elements` / `molecules` / `reactions` |
| `findel`, `findmol`, `findre` | `return`, then that source's fields |
| `balance` | `+`, `->`, `<->` as appropriate |
| `set`, `add`, `remove` | Settings, `catalyst`, common temperature, pressure and catalyst values |
| `source`, `list`, `dump`, `help`, `load`, `install` | Their arguments, including standard-library modules and built-in names |
| `let` | `=`, then query, built-in and constant starters |
| `public`, `private`, `static`, `struct`, `record` | Declaration keywords, `from` |
| `for` | `in`, then `range(` or a query |

Value suggestions for `phase`, `category` and `block` reflect the standard periodic-table dataset. If your data uses different spellings, adjust the `value-...` rules.

---

## Colours: `colors.json`

CodecQL reads its theme from `colors.json` next to `codecql.py`. If the file is missing, a built-in palette is used.

```json
{
    "syntax": {
        "comment":   {"ansi256": 244},
        "string":    {"ansi256": 114},
        "number":    {"ansi256": 179},
        "formula":   {"ansi256": 117},
        "operator":  {"ansi256": 213},
        "delimiter": {"ansi256": 250},
        "command":   {"ansi256": 81},
        "keyword":   {"ansi256": 141},
        "constant":  {"ansi256": 215},
        "type":      {"ansi256": 150},
        "source":    {"ansi256": 110},
        "condition": {"ansi256": 180},
        "property":  {"ansi256": 116},
        "builtin":   {"ansi256": 222}
    },
    "ui": {
        "line_numbers":      {"ansi256": 244},
        "status_background": {"ansi256": 24, "channel": "background"},
        "status_foreground": {"ansi256": 255}
    }
}
```

Each entry needs an `ansi256` number from 0 to 255, and an optional `channel` of `foreground` (default) or `background`. If you provide the file, include **every** category shown above.

---

## Known limitations

- Files are saved with `\n` line endings and **no trailing newline**.
- Inline suggestions appear only when the cursor is at the end of the line.
- `regex` highlighting rules are validated but not yet applied.
- Auto-dedent applies only after `endnamespace`.
- One file per session: there are no tabs or split editors.
- Tabs are drawn four columns wide.
