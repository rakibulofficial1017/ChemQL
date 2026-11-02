# ChemQL & CodecQL

ChemQL is a chemistry-oriented query and programming language with an
interactive terminal, a Python-backed execution environment, chemistry
data types and operations, user-defined functions, and a package system.

CodecQL is the terminal text editor distributed with ChemQL. It edits
source files, provides syntax highlighting, and supports configurable
highlighting profiles for multiple file extensions.

> **Version represented by this documentation:** ChemQL `1.6.4`; CodecQL
> `0.0.11`.
>
> This README documents the implementation represented by the
> accompanying source files. Some advanced syntax is intentionally
> described at a high level; use the built-in `help` system for the
> authoritative in-app reference.

------------------------------------------------------------------------

## Contents

-   [Installation and requirements](#installation-and-requirements)
-   [ChemQL](#chemql)
    -   [Starting ChemQL](#starting-chemql)
    -   [Running scripts and commands](#running-scripts-and-commands)
    -   [Language syntax at a glance](#language-syntax-at-a-glance)
    -   [Built-in functions](#built-in-functions)
    -   [Standard-library packages](#standard-library-packages)
    -   [Chemistry features](#chemistry-features)
    -   [Package management](#package-management)
    -   [Python interoperability](#python-interoperability)
    -   [Help and errors](#help-and-errors)
-   [CodecQL](#codecql)
    -   [Opening and creating files](#opening-and-creating-files)
    -   [Keyboard shortcuts](#keyboard-shortcuts)
    -   [Search syntax](#search-syntax)
    -   [Terminal integration](#terminal-integration)
-   [CodecQL configuration](#codecql-configuration)
    -   [`colors.json`: editor colors](#colorsjson-editor-colors)
    -   [`highlighting.json`: language
        profiles](#highlightingjson-language-profiles)
    -   [Rule types](#rule-types)
    -   [Style syntax](#style-syntax)
    -   [Configuration lookup and
        precedence](#configuration-lookup-and-precedence)
    -   [Editing configuration from
        CodecQL](#editing-configuration-from-codecql)
-   [Troubleshooting](#troubleshooting)

------------------------------------------------------------------------

# Installation and requirements

ChemQL is a Python package. CodecQL is a Python terminal application
that is imported by ChemQL and can also be launched through its editor
command.

The ChemQL runtime imports `prompt_toolkit` for the interactive prompt.
The editor uses Python's standard library and ANSI terminal escape
sequences. On Windows it attempts to initialize ANSI support with
`colorama`, and falls back to enabling virtual-terminal processing when
`colorama` is unavailable.

Install ChemQL using the distribution method provided by the project. If
installing from a local source checkout, install the project from its
package root so that its package metadata and dependencies are installed
together.

Check the installed version:

``` bash
chemql --version
codecql --version
```

If the `codecql` command is not exposed as a separate executable in your
installation, launch the editor through ChemQL:

``` bash
chemql edit path/to/file.cql
```

------------------------------------------------------------------------

# ChemQL

## Starting ChemQL

Start the interactive prompt:

``` bash
chemql
```

The prompt accepts ChemQL commands and expressions. The welcome message
points to the built-in help system:

``` text
help
```

or:

``` text
?
```

Exit the interactive prompt with:

``` text
exit
```

You can also press `Ctrl+C` to leave the prompt.

The prompt supports multiline input for constructs such as functions,
macros, Python blocks, and other block forms. The continuation prompt is
shown as `...`.

## Running scripts and commands

Execute a one-line or multi-line ChemQL command supplied on the command
line:

``` bash
chemql -c 'molar_mass{"H2O"}'
```

Execute a source file:

``` bash
chemql -f path/to/script.cql
```

Write command or script output to a file without ANSI escape sequences:

``` bash
chemql -f path/to/script.cql -o output.txt
```

Useful runtime options:

  -----------------------------------------------------------------------
  Option                              Purpose
  ----------------------------------- -----------------------------------
  `-c`, `--command`                   Execute ChemQL code supplied as an
                                      argument

  `-f`, `--file`                      Execute ChemQL code from a file

  `--no-ansi`                         Disable ANSI styling in output

  `--suppress-warnings`               Suppress warning messages

  `-o`, `--output FILE`               Write captured output to a file
                                      without ANSI sequences

  `-v`, `--version`                   Print the ChemQL version

  `--upgrade [VERSION]`               Upgrade ChemQL, optionally to a
                                      specified version

  `--force` / `--dangerously`         Force an upgrade, including
                                      bypassing system-package
                                      protections
  -----------------------------------------------------------------------

`-o` is only valid with `-c` or `-f`.

## Language syntax at a glance

ChemQL combines its own command/query syntax with Python expressions and
statements in explicitly delimited blocks.

### Function calls

ChemQL function calls use braces rather than parentheses:

``` text
function_name{argument1, argument2}
```

Examples:

``` text
molar_mass{"H2O"}
upper{"hello world"}
math::sqrt{81}
```

Separate arguments with commas. Quote text containing spaces.

### Variables

Use `let` to assign a value:

``` text
let answer = 42
let message = "Hello from ChemQL"
```

Variables can be used in later expressions:

``` text
let radius = 5
let area = math::PI * radius ** 2
```

The runtime also supports listing and removing variables:

``` text
variables
unset answer
```

### Definitions and macros

Definitions are expanded using an `@NAME` reference:

``` text
define MAX {
    100
}
```

Use the definition as:

``` text
@MAX
```

Definitions are maintained in the current ChemQL session. The
preprocessor performs one literal substitution pass; replacement text is
not recursively expanded.

Macros use a block form and are invoked by name according to the macro
syntax supported by the interpreter. Use `help{syntax}` and the in-app
completion/help facilities for the exact forms supported by your
installed version.

### Embedded Python

A single-line Python statement or expression can be placed inside square
brackets:

``` text
[print("Hello from Python")]
```

A multiline Python block uses triple square brackets:

``` text
[[[
numbers = [1, 2, 3, 4]
total = sum(numbers)
print(total)
]]]
```

Python code executes in ChemQL's Python-backed environment. This makes
Python expressions and available Python objects usable alongside ChemQL
features.

### Embedded ChemQL expressions

Double curly braces are used for embedded/lazy ChemQL query expressions
in supported contexts:

``` text
{{ search molecules ... }}
```

The precise query expression depends on the operation being performed.
See `help{syntax}` and the query examples shipped with the project.

### Control flow

ChemQL supports block-oriented control-flow constructs including `if`,
`elif`, `else`, `for`, and `while`. Closing markers are explicit:

``` text
if condition
    ...
else
    ...
endif
```

``` text
for item in items
    ...
endfor
```

``` text
while condition
    ...
endwhile
```

`break` and `continue` are also recognized control keywords.

### Functions

User-defined functions are declared with `func` and closed with
`endfunc`. Functions can accept arguments and return values. Inside a
function, positional arguments are available through the function's
argument mechanism; the implementation also supports `\1`, `\2`, and so
on as positional argument references in function bodies.

A minimal illustrative shape:

``` text
func greet
    return "Hello"
endfunc
```

Call a function using ChemQL's brace-call syntax:

``` text
greet{}
```

### Structs, records, and enums

ChemQL supports user-defined `struct`, `record`, and `enum`
declarations. Structs and records can declare fields, and the
implementation supports inheritance using `from Base`. Structs can
inherit from structs, records, or Python classes; records can inherit
from records.

Declarations are closed with their corresponding terminators, such as
`endstruct`, `endrecord`, and `endenum`.

Example declaration shape:

``` text
struct Point
    x
    y
endstruct
```

Enum members can receive automatically generated values when values are
omitted.

### Namespaces

Namespaces group related declarations and support public/private
members:

``` text
namespace Geometry
    public func ...
    private func ...
endnamespace
```

A namespace member is referenced with a qualified name using `::`, for
example `Geometry::member`. Private namespace members are intended for
internal use by functions in the same namespace.

### Error handling and signals

The interpreter supports structured `risk`, `fix`, and `cleanup`
sections, closed by `endrisk`. It also supports `signal` and `warn`
statements in the relevant execution contexts.

The `fix` section is used when the risk section raises a handled error;
`cleanup` is for cleanup side effects. The current error information is
exposed to the execution environment.

## Built-in functions

The built-in function set includes general-purpose operations, string
and collection helpers, file I/O, and chemistry helpers. Calls use
braces.

  -----------------------------------------------------------------------
  Category                            Functions
  ----------------------------------- -----------------------------------
  Numbers                             `abs`, `round`, `min`, `max`, `sum`

  Core and conversion                 `len`, `type`, `str`, `int`,
                                      `float`, `bool`

  Strings                             `upper`, `lower`, `contains`,
                                      `replace`, `split`, `join`

  Collections                         `first`, `last`, `unique`, `sort`,
                                      `reversed`

  Files and data                      `read_text`, `read_lines`,
                                      `read_json`, `read_csv`,
                                      `write_text`, `write_json`,
                                      `write_csv`, `file_exists`,
                                      `list_files`

  Chemistry                           `element`, `count_atoms`,
                                      `molar_mass`, `empirical_formula`

  Help                                `help`
  -----------------------------------------------------------------------

Examples:

``` text
abs{-15}
round{3.14159, 2}
sum{1, 2, 3, 4}
upper{"chemql"}
unique{1, 2, 2, 3}
molar_mass{"H2O"}
count_atoms{"H2SO4", "O"}
empirical_formula{"C6H12O6"}
```

File examples:

``` text
let text = read_text{"notes.txt"}
let rows = read_csv{"data.csv"}
let data = read_json{"data.json"}

write_text{"output.txt", "Hello"}
write_json{"output.json", data}
write_csv{"output.csv", rows}
```

`read_csv` treats the first row as headers by default and returns rows
as dictionaries. Pass `false` as the `headers` argument to read rows as
lists.

For exact signatures, optional arguments, and examples, use:

``` text
help{function_name}
```

For example:

``` text
help{read_csv}
help{molar_mass}
```

## Standard-library packages

ChemQL includes loadable standard-library namespaces. Load a package
before using its members:

``` text
load math
math::sqrt{81}
```

The source's built-in help index lists these standard-library
namespaces:

  Package              Purpose
  -------------------- --------------------------------------------------
  `math`               Mathematical constants and numeric functions
  `math::statistics`   Descriptive statistics
  `text`               String operations and regular expressions
  `collections`        Collection and iterable helpers
  `datetime`           Dates, times, timestamps, and date arithmetic
  `json`               JSON serialization, parsing, and type inspection
  `random`             Pseudorandom values and sequence sampling

Ask ChemQL for a package's documented members:

``` text
help{stdlib}
help{math}
help{math::statistics}
help{text}
```

A function can be documented individually when its help entry is
registered:

``` text
help{math::sqrt}
```

## Chemistry features

ChemQL exposes chemistry-oriented data types and operations, including:

-   `Element`, `Molecule`, and `Reaction` objects.
-   Element and molecule lookup helpers.
-   Reaction lookup and reaction searching.
-   Stoichiometric balancing through `balance_stoichiometry`.
-   Reaction matching against the current temperature, pressure, and
    catalyst conditions.
-   Chemistry built-ins such as `element`, `count_atoms`, `molar_mass`,
    and `empirical_formula`.

The interactive command set includes chemistry/query commands such as
`search`, `source`, `findel`, `findmol`, `findre`, `react`, `balance`,
`conditions`, and `view`.

Examples of built-in chemistry functions:

``` text
element{"Na"}
count_atoms{"H2SO4", "O"}
molar_mass{"H2O"}
empirical_formula{"C6H12O6"}
```

Reaction operations can depend on the current reaction conditions.
Inspect or set conditions with the relevant interactive commands and use
`conditions` to display the current state.

The available data sources and query fields are defined by the ChemQL
package/data files. Use the interactive prompt's completion and
`help{chemistry}` for the current details.

## Package management

ChemQL provides package-management subcommands:

  -------------------------------------------------------------------------------
  Command                                     Purpose
  ------------------------------------------- -----------------------------------
  `chemql init [NAME] [-d DIRECTORY]`         Create a ChemQL package project

  `chemql build`                              Build the current package

  `chemql search QUERY`                       Search the package registry

  `chemql info NAME`                          Show registry information for a
                                              package

  `chemql install NAME [--version VERSION]`   Install a package

  `chemql upgrade NAME [--version VERSION]`   Upgrade an installed package

  `chemql list`                               List installed packages

  `chemql uninstall NAME`                     Uninstall a package

  `chemql upload`                             Upload the current package to the
                                              registry
  -------------------------------------------------------------------------------

Example workflow:

``` bash
chemql search statistics
chemql info package_name
chemql install package_name
chemql list
```

Load an installed package from the ChemQL prompt:

``` text
load package_name
```

Then call its namespaced functions:

``` text
package_name::function_name{...}
```

The package manager also supports upgrading ChemQL itself:

``` bash
chemql --upgrade
chemql --upgrade 1.6.4
```

Use `--force` only when you understand that it bypasses normal
protections around system-managed installations.

## Python interoperability

ChemQL is implemented in Python and evaluates embedded Python blocks in
its Python execution environment. The runtime imports and uses Python
modules internally, and the language exposes Python-backed objects and
functions.

Use square-bracket blocks for Python statements and expressions. Use
`[[[ ... ]]]` for multiline Python. This is the intended boundary
between ChemQL's command/query syntax and general Python code.

## Help and errors

The interactive help system is the quickest way to discover the exact
syntax supported by the installed version:

``` text
help
help{syntax}
help{errors}
help{files}
help{chemistry}
help{stdlib}
help{function_name}
```

The runtime defines specific built-in error classes:

-   `TooFewArguments`
-   `TooManyArguments`
-   `InvalidArgumentType`
-   `InvalidArgumentValue`
-   `FileReadError`
-   `FileWriteError`

Other errors can include `SyntaxError`, `NameError`, and
`PermissionError`.

------------------------------------------------------------------------

# CodecQL

CodecQL is a terminal-based text editor intended for ChemQL source
files. It also supports configurable syntax-highlighting profiles for
other extensions.

## Opening and creating files

Open an existing file:

``` bash
codecql script.cql
```

Create a new file by opening a path that does not exist yet:

``` bash
codecql new_script.cql
```

The editor starts with an empty buffer when the file does not exist.
Save with `Ctrl+S` to create it.

Launch it through ChemQL:

``` bash
chemql edit script.cql
```

Open the editor's main highlighting configuration:

``` bash
codecql --main-highlighting
```

Open the current working directory's local highlighting configuration:

``` bash
codecql --local-highlighting
```

The two highlighting flags cannot be used together. If the selected
configuration file does not exist, CodecQL creates an empty JSON object
in that location.

## Keyboard shortcuts

  -----------------------------------------------------------------------
  Shortcut                            Action
  ----------------------------------- -----------------------------------
  `Ctrl+S`                            Save the current file

  `Ctrl+Q`                            Quit; if there are unsaved changes,
                                      press it again to discard and quit

  `Ctrl+Z`                            Undo

  `Ctrl+Y`                            Redo

  `Ctrl+F`                            Open search

  `Ctrl+C`                            Copy the current selection

  `Ctrl+X`                            Cut the current selection

  `Ctrl+V`                            Paste the editor clipboard

  `Shift+Insert`                      Paste the editor clipboard

  `Ctrl+T`                            Open a split terminal

  `Ctrl+R`                            Save if needed and run the current
                                      file with ChemQL

  `Shift+Arrow`                       Extend the selection while moving
                                      the cursor

  `Ctrl+Arrow Up/Down`                Scroll the viewport

  `Ctrl+Arrow Left/Right`             Move by word

  `Home` / `End`                      Move to the start/end of the line

  `Backspace` / `Delete`              Delete text
  -----------------------------------------------------------------------

Clipboard integration uses the available system clipboard command when
possible: - Windows: `clip` - WSL: `clip.exe` - macOS: `pbcopy` - Linux:
`wl-copy`, `xclip`, or `xsel`

If no system clipboard utility is available, CodecQL keeps the copied
text in its own editor clipboard.

## Search syntax

Press `Ctrl+F` to open search. Enter a query and use the arrow keys to
move between matches. Press `Enter` to select the next match; `Up` or
`Left` selects the previous match. `Esc` closes search.

Search supports optional prefix flags:

  Flag   Meaning
  ------ -----------------------------------------
  `r`    Treat the query as a regular expression
  `l`    Literal search (the default)
  `w`    Match whole words
  `i`    Ignore case

Place flags before a colon. Examples:

``` text
hello
i:hello
w:hello
ri:\b[A-Z]{2,}\b
lw:token
```

Search is case-insensitive by default. `r` and `l` cannot be combined.

## Terminal integration

-   `Ctrl+T` opens a shell in a terminal pane/window.
-   `Ctrl+R` saves the current buffer if it has unsaved changes, then
    runs the file with `chemql -f`.
-   On Windows, CodecQL uses a new console, or a Windows Terminal split
    pane when running inside Windows Terminal.
-   On Unix-like systems, CodecQL uses a pseudo-terminal for the
    integrated terminal.

------------------------------------------------------------------------

# CodecQL configuration

CodecQL has two separate JSON configuration files:

-   `colors.json` controls the editor's ANSI color palette.
-   `highlighting.json` controls which tokens are highlighted for each
    file extension and which style is assigned to each rule.

They serve different purposes. Changing a color in `colors.json` changes
the appearance of a named style throughout the editor. Changing
`highlighting.json` changes which words are assigned to styles for a
language.

## `colors.json`: editor colors

`colors.json` is read from the directory containing the CodecQL source
module. It has two top-level objects: `syntax` and `ui`.

Every color entry must be an object containing an integer `ansi256`
value from `0` through `255`. The optional `channel` is either
`foreground` (the default) or `background`.

Example:

``` json
{
    "syntax": {
        "comment":  { "ansi256": 244 },
        "string":   { "ansi256": 114 },
        "number":   { "ansi256": 179 },
        "formula":  { "ansi256": 117 },
        "operator": { "ansi256": 213 },
        "delimiter": { "ansi256": 250 },
        "command":  { "ansi256": 81 },
        "keyword":  { "ansi256": 141 },
        "constant": { "ansi256": 215 },
        "type":     { "ansi256": 150 },
        "source":   { "ansi256": 110 },
        "condition": { "ansi256": 180 },
        "property": { "ansi256": 116 },
        "builtin":  { "ansi256": 222 }
    },
    "ui": {
        "line_numbers": {
            "ansi256": 244
        },
        "status_background": {
            "ansi256": 24,
            "channel": "background"
        },
        "status_foreground": {
            "ansi256": 255
        }
    }
}
```

The values above mirror the fallback palette in the editor source. If
`colors.json` is missing, CodecQL uses that fallback palette. If the
file exists but is malformed or missing a required top-level group,
loading the theme raises a configuration error.

### Syntax color categories

The editor's syntax theme uses these categories:

  Category      Used for
  ------------- ---------------------------------------------------
  `comment`     Comments
  `string`      Quoted strings
  `number`      Numeric literals
  `formula`     Chemical formula-like tokens
  `operator`    Operators
  `delimiter`   Brackets and punctuation delimiters
  `command`     ChemQL commands
  `keyword`     Language/control keywords
  `constant`    Values such as `true`, `false`, and `none`
  `type`        Type/declaration names and manifest table headers
  `source`      ChemQL data sources
  `condition`   Chemistry conditions and units
  `property`    Chemistry fields and manifest keys
  `builtin`     Python built-in names recognized by the editor

The UI categories are:

  Category              Used for
  --------------------- -----------------------
  `line_numbers`        Line-number gutter
  `status_background`   Status bar background
  `status_foreground`   Status bar text

### ANSI 256-color values

`ansi256` is a terminal color index, not an RGB hex value. It accepts
integers from `0` to `255`.

Common ranges in the standard 256-color palette:

-   `0–15`: standard and bright terminal colors.
-   `16–231`: 6×6×6 RGB color cube.
-   `232–255`: grayscale ramp.

The actual appearance depends on the terminal's color palette and
settings.

To set a background color, add `"channel": "background"`:

``` json
"status_background": {
    "ansi256": 24,
    "channel": "background"
}
```

Foreground is assumed when `channel` is omitted.

## `highlighting.json`: language profiles

`highlighting.json` maps file extensions to ordered lists of
highlighting rules.

CodecQL starts with a built-in `.cql` profile. It then loads the main
configuration and the current directory's local configuration, if
present. A custom profile for an existing extension replaces that
extension's previous profile; a new extension adds a profile.

A minimal configuration:

``` json
{
    ".py": [
        {
            "name": "python-keywords",
            "type": "keywords",
            "values": ["def", "class", "return", "if", "elif", "else", "for", "while", "import", "from", "as", "try", "except", "finally", "with", "pass", "break", "continue"],
            "style": "keyword"
        },
        {
            "name": "python-builtins",
            "type": "keywords",
            "values": ["print", "len", "range", "enumerate", "zip", "map", "filter", "sum", "min", "max", "str", "int", "float", "list", "dict", "set", "tuple"],
            "style": "builtin"
        }
    ],
    ".js": [
        {
            "name": "javascript-keywords",
            "type": "keywords",
            "values": ["const", "let", "var", "function", "return", "if", "else", "for", "while", "class", "new", "import", "export", "from", "async", "await"],
            "style": "keyword"
        }
    ]
}
```

### Profile structure

The top-level value must be a JSON object. Each key is a file extension
and each value is an array of rules.

``` json
{
    ".extension": [
        {
            "name": "rule-name",
            "type": "keywords",
            "values": ["word1", "word2"],
            "style": "keyword"
        }
    ]
}
```

Extension normalization: - A leading dot is added if omitted. -
Extensions are converted to lowercase. - Empty extensions and values
containing path separators are rejected. - The profile is selected from
the file's final extension. For example, `script.py` uses `.py`.

Each rule must be an object with: - `name`: non-empty string identifying
the rule. - `type`: supported rule type (`keywords` or `regex`). -
`style`: non-empty style expression.

A keyword rule additionally requires: - `values`: a non-empty array of
non-empty strings.

Keyword matching is case-insensitive. Rule order matters: the first
matching keyword rule supplies the style for that word.

### Rule types

#### `keywords`

Use this rule to assign a style to a list of exact words:

``` json
{
    "name": "control-flow",
    "type": "keywords",
    "values": ["if", "else", "while", "for", "return"],
    "style": "keyword"
}
```

The current implementation applies keyword rules during identifier
highlighting. Matching is case-insensitive.

#### `regex`

Regex rules are accepted and validated by the profile loader. A regex
rule must include a non-empty `pattern`; `case_sensitive` is optional
and defaults to `true`.

``` json
{
    "name": "special-identifiers",
    "type": "regex",
    "pattern": "\\b(?:TODO|FIXME|NOTE)\\b",
    "case_sensitive": true,
    "style": "#FFB000 bold"
}
```

**Implementation note:** the current editor integration applies
`keywords` rules through `get_keyword_style`. Although `regex` rules are
parsed and validated by `highlighting.py`, they are not yet applied by
the current token-highlighting path. Treat regex highlighting as a
reserved/configuration-ready feature until regex application is wired
into the renderer.

### Style syntax

A rule's `style` is a space-separated list of style components.
Components can be combined.

#### Named theme styles

These names refer to entries in `colors.json` under `syntax`:

``` text
keyword
command
operator
string
comment
number
constant
type
source
condition
property
builtin
```

Example:

``` json
"style": "keyword"
```

#### Formatting modifiers

The editor recognizes these modifiers:

  Modifier      Effect
  ------------- -------------------------------
  `bold`        Bold text
  `dim`         Dim text
  `italic`      Italic text
  `underline`   Underlined text
  `reverse`     Reverse foreground/background
  `strike`      Strikethrough text

Example:

``` json
"style": "keyword bold underline"
```

#### Custom foreground colors

Use a six-digit hexadecimal RGB color prefixed with `#`:

``` json
"style": "#FF00FF"
```

#### Custom background colors

Use `bg:` followed by a six-digit hexadecimal RGB color:

``` json
"style": "bg:#202020"
```

#### Combining components

You can combine a named style, formatting modifiers, and custom
foreground/background colors:

``` json
"style": "#FF00FF underline bold italic"
```

``` json
"style": "keyword bold"
```

``` json
"style": "#E0B0FF bg:#202020 bold"
```

Hexadecimal colors use true-color ANSI escape sequences. Your terminal
must support ANSI styling and preferably 24-bit true color for the full
effect.

### Example: create a profile for Python

Create or edit `highlighting.json` in your project directory:

``` json
{
    ".py": [
        {
            "name": "python-keywords",
            "type": "keywords",
            "values": [
                "def", "class", "return", "if", "elif", "else",
                "for", "while", "in", "break", "continue",
                "import", "from", "as", "try", "except",
                "finally", "with", "raise", "yield", "lambda"
            ],
            "style": "keyword bold"
        },
        {
            "name": "python-constants",
            "type": "keywords",
            "values": ["True", "False", "None"],
            "style": "#FFB86C bold"
        },
        {
            "name": "python-builtins",
            "type": "keywords",
            "values": ["print", "len", "range", "enumerate", "zip", "sum", "min", "max"],
            "style": "builtin"
        }
    ]
}
```

Then open a Python file from that directory:

``` bash
codecql example.py
```

The local `.py` profile is loaded and used for matching identifier
tokens.

### Example: add a language without changing ChemQL's built-in profile

You can define several extensions in the same JSON file:

``` json
{
    ".py": [
        {
            "name": "python-keywords",
            "type": "keywords",
            "values": ["def", "class", "return", "if", "else", "for", "while"],
            "style": "keyword"
        }
    ],
    ".rs": [
        {
            "name": "rust-keywords",
            "type": "keywords",
            "values": ["fn", "let", "mut", "pub", "struct", "enum", "impl", "trait", "use", "mod", "match", "if", "else", "loop", "while", "for", "return"],
            "style": "#D19A66 bold"
        }
    ],
    ".js": [
        {
            "name": "javascript-keywords",
            "type": "keywords",
            "values": ["const", "let", "var", "function", "return", "class", "new", "async", "await"],
            "style": "keyword"
        }
    ]
}
```

This adds profiles for `.py`, `.rs`, and `.js`. It does not remove the
built-in `.cql` profile unless you explicitly provide a `.cql` profile
in a loaded configuration.

### Configuration lookup and precedence

The editor loads highlighting profiles in this order:

1.  The built-in profiles in `highlighting.py` (currently includes
    `.cql`).
2.  `highlighting.json` beside the CodecQL source module (the main
    configuration).
3.  `highlighting.json` in the current working directory (the local
    configuration).

Later profiles replace earlier profiles for the same extension.
Therefore:

-   The main configuration can provide defaults shared by projects.
-   A local configuration can override those defaults for the current
    project.
-   Profiles for unrelated extensions are retained.
-   If the main and local paths point to the same file, it is loaded
    only once.
-   If neither file exists, the built-in profiles remain available.

**Important:** the local configuration is merged by extension; it does
not merge individual rules into an existing extension profile. If a
local `.py` profile is present, it replaces the main `.py` profile as a
whole.

The main configuration path is relative to the installed CodecQL module.
The local configuration path is relative to the directory from which
CodecQL is launched.

### Editing configuration from CodecQL

Open the main configuration:

``` bash
codecql --main-highlighting
```

Open the local configuration:

``` bash
codecql --local-highlighting
```

If the selected file does not exist, CodecQL creates it as:

``` json
{}
```

Edit the JSON, save with `Ctrl+S`, then restart CodecQL or reopen the
file being edited so the editor reloads the profile configuration.

Do not combine `--main-highlighting` and `--local-highlighting`.

## Built-in ChemQL highlighting

The built-in `.cql` profile groups words into these rules:

  -----------------------------------------------------------------------
  Rule name               Style                   Examples
  ----------------------- ----------------------- -----------------------
  `commands`              `command`               `search`, `source`,
                                                  `findmol`, `react`,
                                                  `balance`, `help`,
                                                  `load`

  `control-keywords`      `keyword`               `if`, `else`, `for`,
                                                  `while`, `struct`,
                                                  `record`, `enum`,
                                                  `namespace`

  `word-operators`        `operator`              `and`, `or`, `has`,
                                                  `like`, `sort`,
                                                  `limit`, `union`

  `sources`               `source`                `elements`,
                                                  `molecules`,
                                                  `reactions`

  `conditions`            `condition`             `temperature`,
                                                  `pressure`, `catalyst`,
                                                  `atm`, `bar`, `kpa`

  `properties`            `property`              `name`, `symbol`,
                                                  `atomic_mass`,
                                                  `formula`, `reactants`,
                                                  `products`
  -----------------------------------------------------------------------

The editor also recognizes lexical token categories such as comments,
strings, numbers, chemical formula-like tokens, operators, and
delimiters. JSON and TOML package manifests named `cqlpackage.json` and
`cqlpackage.toml` receive dedicated manifest highlighting.

------------------------------------------------------------------------

# Troubleshooting

### A file opens without custom highlighting

Check that: 1. The file has the extension used as the profile key, such
as `.py`. 2. The JSON file is named exactly `highlighting.json`. 3. The
local file is in the current working directory from which CodecQL was
launched. 4. The extension key includes the intended extension. 5. The
rule uses `"type": "keywords"` and has a non-empty `values` array. 6.
The token is recognized as an identifier by the editor's tokenizer.

Unknown extensions remain unhighlighted by language-specific keyword
profiles, though the editor's general lexical token styling still
applies.

### My local profile is not overriding the main profile

Profiles are replaced per extension, not merged rule by rule. Make sure
the local profile includes the complete rule list you want for that
extension.

### The editor rejects my highlighting JSON

Check standard JSON syntax: - Use double quotes around keys and string
values. - Do not leave trailing commas. - Use `true` and `false` for
booleans, not quoted strings. - Make sure each extension maps to an
array of rules. - Make sure each rule has a non-empty `name`, supported
`type`, and non-empty `style`.

For regex rules, `pattern` must be a valid Python regular expression.
`case_sensitive` must be a JSON boolean.

### My custom style is rejected

Use only recognized style components: - A named theme style listed in
[Style syntax](#style-syntax). - One of `bold`, `dim`, `italic`,
`underline`, `reverse`, or `strike`. - A foreground color such as
`#FF00FF`. - A background color such as `bg:#202020`.

Separate components with spaces.

### Colors look different in my terminal

ANSI 256-color and true-color output are interpreted by the terminal.
Different terminal palettes, themes, and color capabilities can make the
same color index or RGB value look different.

### `Ctrl+R` does not run my file

`Ctrl+R` invokes `chemql -f` with the current file's absolute path.
Ensure ChemQL is installed and its `chemql` command is available in the
environment inherited by CodecQL. The editor saves a modified buffer
before running it.

------------------------------------------------------------------------

## Project components

  -----------------------------------------------------------------------
  File/component                      Responsibility
  ----------------------------------- -----------------------------------
  ChemQL package (`__init__.py`)      Language runtime, interactive
                                      prompt, chemistry functionality,
                                      built-ins, package management

  `codecql.py`                        Terminal editor, file operations,
                                      key handling, terminal integration,
                                      token rendering

  `highlighting.py`                   Highlighting profile definitions,
                                      JSON loading, extension
                                      normalization, and rule validation

  `colors.json`                       ANSI 256-color theme for syntax and
                                      editor UI

  `highlighting.json`                 Optional user-defined language
                                      profiles
  -----------------------------------------------------------------------

ChemQL and CodecQL are related but separate components: ChemQL provides
the language/runtime, while CodecQL provides the editing environment.
