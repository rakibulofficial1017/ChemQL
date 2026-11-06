# ChemQL

**The Python chemistry query language.** Query chemistry, automate calculations, and build reusable programs, from an interactive prompt, from script files, or from Python.

| | |
|---|---|
| Distribution name | `chemql-python` |
| Import / CLI name | `chemql` |
| Current version | 1.6.6 |
| Python | 3.12+ |
| Editor | [CodecQL](CODECQL.md), a terminal editor for `.cql` files, bundled (`chemql edit`) |

```chemql
search elements number > 10 and number < 20 return name symbol
search molecules molecular_weight < 50 sort molecular_weight limit 10
search reactions reactants has "O2" and products has "H2O"
balance H2 + O2 -> H2O
```

---

## Contents

- [Features](#features)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Querying data](#querying-data)
- [Chemistry tools](#chemistry-tools)
- [The language](#the-language)
- [Standard library and packages](#standard-library-and-packages)
- [Python API](#python-api)
- [Command-line reference](#command-line-reference)
- [Configuration and environment](#configuration-and-environment)
- [Data sources](#data-sources)
- [Safety](#safety)
- [CodecQL editor](#codecql-editor)

---

## Features

- **SQL-like queries** over three bundled datasets: periodic-table **elements**, **molecules** and **reactions**, with comparison operators, wildcard and regex matching, `and`/`or`/`not`, grouping, sorting, limiting, counting, projection and set operations.
- **Online lookups** when the bundled data has no answer: PubChem, ChemSpider (with an API key) and NIST WebBook for molecules; Chempirical and Rhea for reactions.
- **Equation balancing** (`balance H2 + O2 -> H2O`) with exact rational arithmetic, and **reaction lookup** under a given temperature, pressure and set of catalysts.
- **A complete scripting language**: variables, user-defined functions, macros and definitions, `if`/`for`/`while`, structured error handling (`risk`/`fix`/`cleanup`), enums, structs, records, namespaces with public/private members.
- **Python everywhere**: embed Python expressions in `[ ... ]`, multi-line Python in `[[[ ... ]]]`, and queries inside Python with `{{ ... }}`.
- **Shell integration**: run system commands from backticks or fenced blocks in a persistent shell session.
- **Built-in functions and a standard library** (`math`, `text`, `datetime`, `json`, `random`, ...).
- **A package manager and registry**: `chemql install`, `chemql init`, `chemql build`, `chemql upload`.
- **A Python API** (`execute_query_text`, a fluent `search(...)` builder, and plain data classes).
- **An interactive prompt** with syntax highlighting, context-aware completion and automatic multi-line block detection.

---

## Installation

```bash
pip install chemql-python
chemql --version
```

**Requirements**

| Requirement | Notes |
|---|---|
| Python 3.12 or newer | The source uses PEP 701 f-string syntax. |
| `prompt_toolkit` 3.x | Interactive prompt. Use a recent 3.0 release. |
| `rich` *(optional)* | Renders Markdown help for installed packages. |
| `colorama` *(optional, Windows)* | ANSI colour support in [CodecQL](CODECQL.md); falls back to enabling virtual-terminal mode directly. |

**Upgrading**

```bash
chemql --upgrade             # latest release
chemql --upgrade 1.6.6       # a specific version
chemql --upgrade --force     # force a reinstall, overriding system-package protections
```

---

## Quick start

```bash
chemql                                   # interactive prompt
chemql -c 'search elements symbol = "O"' # run one command
chemql -f script.cql                     # run a file
chemql -f script.cql -o out.txt          # write output to a file (ANSI stripped)
echo 'findel "He"' | chemql              # piped input is executed as a script
```

At the prompt, type `help` (or `?`) for the full reference, `help{function}` for details on a built-in, and `exit` (or Ctrl+C) to leave. Blocks such as `func ... endfunc`, `if ... endif` and `[[[ ... ]]]` are detected automatically: pressing Enter inserts a new line until the block is closed.

```chemql
>>> findel "Fe" return name number
>>> let h = {{ search elements symbol = "H" }}
>>> [h.atomic_mass]
>>> balance N2 + H2 <-> NH3
```

> **Comments** use `//` for a line and `/// ... ///` for a block. **Several commands** can share a line, separated by `;`. A trailing `\` continues a command on the next line.

---

## Querying data

### Sources

| Source | Contents | Fields |
|---|---|---|
| `elements` | The periodic table | `name symbol number atomic_mass category phase period group block density melt boil molar_heat appearance electron_configuration electron_configuration_semantic electronegativity_pauling electron_affinity ionization_energies shells discovered_by named_by summary source image bohr_model_image bohr_model_3d spectral_img xpos ypos wxpos wypos` |
| `molecules` | Common molecules with bonding data | `name formula molecular_weight elements iupac_name smiles cid state melting_point boiling_point density bonds total_bond_energy` |
| `reactions` | Stored reactions | `id name equation reaction_type reversible reactants products conditions notes source` |

```chemql
source molecules        // make molecules the default source
list all                // list the fields of the current source (or the sources if none is set)
search molecular_weight < 20
```

### Anatomy of a query

```text
search [first|last|all] [SOURCE] CONDITIONS [sort FIELD [asc|desc]] [limit N] [count] [return FIELD ...]
```

```chemql
search elements symbol = "Fe" return name symbol number
search molecules molecular_weight < 20 sort molecular_weight asc limit 5
search reactions reversible = true return name equation source
search first molecules name like "*acid" sort molecular_weight desc
search elements number > 100 count
```

- With no `first`/`last`, a single match returns the object itself and several matches return a list. No match prints `No matching item`.
- `return` projects fields **after** filtering, sorting and limiting. One field gives a list; several give a table.
- `count` must be the last operation and cannot be combined with `first`, `last` or `return`.
- A query may begin directly with an operation to act on the whole source: `search molecules count`.

### Operators

| Operator | Meaning |
|---|---|
| `=` `!=` `>` `<` `>=` `<=` | Comparison. Numeric and boolean values are converted from the query text (`reversible = true`). |
| `like` | Wildcard match, **case-insensitive**, against the *entire* value. |
| `like!` | Wildcard match, **case-sensitive**. |
| `likep` | Regular-expression search (`re.search`) on string fields. |
| `has` | Containment for lists and dictionaries. Molecule identifiers match exactly (`O2` does not match `CO2`); other strings match as case-insensitive substrings. |
| `not` | Negation: `name not like "H*"`, or `not (number > 10)`. |
| `and` `or` | Combine conditions. `and` binds tighter than `or`; use parentheses to group. |
| `union` `intersection` | Combine whole queries, evaluated left to right. |

```chemql
search elements category = "noble gas" and (period = 2 or period = 3)
search reactions reactants has "O2" and products has "H2O"
search elements symbol likep "^(He|Ne|Ar)$" return name
search molecules name like "*water*" union search molecules name like "*acid*"
```

### `like` wildcards

| Wildcard | Matches |
|---|---|
| `*` | Any run of characters |
| `_` | Any single character |
| `#` | One digit |
| `?` | One letter |
| `%` | Zero or more digits |
| `&` | Zero or more letters |
| `\` | Escapes the next character |

### Shortcuts

```chemql
findel "He"                              // name or symbol
findel "Fe" return name number

findmol "Water"                          // name or formula; bundled data first, then online sources
findmol "aspirin" return formula molecular_weight

findre "Haber process"                   // name, id or equation; then Chempirical and Rhea (RHEA:nnnnn ids work)
findre "Haber" return name equation      // project fields, as with search
```

### Using variables in queries

```chemql
define MAX 9
search elements number <= @MAX           // literal text substitution

let limit_value = 20
search elements number < [limit_value]   // Python expression evaluated inside the query
```

---

## Chemistry tools

### Balancing equations

```chemql
balance H2 + O2 -> H2O
balance N2 + H2 <-> NH3      // <-> marks the reaction as reversible
```

The result is a reaction with integer coefficients. When a reversibility flag is set, the equation also shows an estimated ΔH computed from the bundled bond energies. Formulas may contain nested parentheses, e.g. `Fe2(SO4)3`. Equations without a unique positive solution are rejected with an error.

### Finding a stored reaction

Reactions in the bundled dataset are only matched when their conditions match the current state.

```chemql
set temperature 150C         // C, F or K; or `standard` (273.15 K) / `room` (298.15 K)
set pressure 1atm            // Pa kPa MPa hPa mbar bar atm torr mmHg psi kpsi N/m^2; or standard / room
set catalysts iron zinc      // replace the catalyst list; `set catalysts` clears it
add catalyst "Iron"
remove catalyst "Zinc"
conditions                   // show the current state

react N2 3H2                 // coefficients can be written as 3H2 or 3 H2
```

A reaction matches when its reactants are exactly those given and its conditions are met: if it specifies a temperature, the current one must be within 5 K; if it specifies a pressure, within 5 %; and every catalyst it requires must be in the catalyst list. Reversible reactions can also be matched from their products. One product returns a molecule; several return a table.

---

## The language

### Variables, Python and embedded queries

```chemql
let answer = 42
[answer * 2]                      // evaluate a Python expression
[x = 10]                          // run a Python statement
let h = {{ search elements symbol = "H" }}   // a query as a value
[h.atomic_mass]
variables                         // list variables
unset answer
```

```chemql
[[[
for n in range(3):
    print(n)
]]]
```

Variables, Python names and query results all live in one shared session. The value of the last expression is available as `_`.

### Definitions and macros

```chemql
define MAX 9                      // literal text replacement, also inside strings
search elements number <= @MAX
definitions                       // list definitions
remove definition MAX
```

Definitions are expanded in source order, once, and are not retroactive. **Macros** generate source text:

```chemql
define element_by_number{}
    search elements number = \1
enddefine

@element_by_number{8}
macros
```

### Functions and built-ins

```chemql
func square
    return [\1 * \1]
endfunc

square{5}                         // 25
let total = int{1} + square{3}    // calls compose with Python expressions
```

Function calls use braces and commas: `name{arg1, arg2}`, and arguments are available in the body as `\1`, `\2`, and so on. Quote text that contains spaces. Keep comments outside function bodies. `static func` and `func Type.method` (with `this`) define static and instance methods on structs; operator methods such as `func Type.__add__` enable overloading. User-defined functions take precedence over built-ins with the same name.

| Category | Built-ins |
|---|---|
| Numbers | `abs` `round` `min` `max` `sum` |
| Core | `len` `type` |
| Conversion | `str` `int` `float` `bool` |
| Strings | `upper` `lower` `contains` `replace` `split` `join` |
| Collections | `first` `last` `unique` `sort` `reversed` |
| Files | `read_text` `read_lines` `write_text` `file_exists` `list_files` |
| Data files | `read_csv` `write_csv` `read_json` `write_json` |
| Chemistry | `element` `count_atoms` `molar_mass` `empirical_formula` |
| Help | `help` |

```chemql
molar_mass{"H2SO4"}
count_atoms{"H2SO4", "O"}                  // 4
empirical_formula{"C6H12O6"}               // CH2O
element{"Na", "atomic_mass"}
let rows = read_csv{"data.csv"}
write_json{"out.json", rows}
help{read_csv}                             // detailed help for any built-in
```

### Control flow

```chemql
for i in range(5)
    let value = i
endfor

if answer > 10
    [print("big")]
elif answer > 5
    [print("medium")]
else
    [print("small")]
endif

[x = 0]
while x < 3
    [x += 1]
endwhile
```

`break`, `continue` and `skip` control loops. The Python-style bracket form `[for ...]` ... `[endblock]` is also accepted.

### Error handling

```chemql
risk
    signal "Something went wrong"    // raise a recoverable error
fix
    let handled = error              // `error` holds the error type, or None after success
cleanup
    [print("always runs")]
endrisk

warn "careful"                       // prints a warning; the latest is stored in `warnings`
```

Inside a `risk` block, errors are raised rather than printed, so `fix` can handle them. `--suppress-warnings` silences `warn` output. Built-in functions raise `TooFewArguments`, `TooManyArguments`, `InvalidArgumentType`, `InvalidArgumentValue`, `FileReadError` and `FileWriteError`; `help{errors}` lists all error signals.

### Enums, structs and records

```chemql
enum Levels
    LOW = 50
    MEDIUM                            // omitted values are generated automatically
    HIGH
endenum

struct Animal
    name!                             // required field (also written `required name`)
    sound = "..."                     // field with a default
endstruct

struct Dog from Animal                // structs inherit from structs, records or Python classes
    color!
endstruct

let rex = Dog{name = "Rex", color = "brown"}

func Dog.describe
    return ["Dog named " + this.name]
endfunc
[rex.describe()]

record Point                          // immutable; supports arithmetic between records
    x
    y = 0                             // fields with defaults must come last
endrecord
let p = Point{1, 2}
[p + p]
```

Records inherit only from records. Structs cannot inherit from enums.

### Namespaces and visibility

Members are **private** by default; mark them `public` to expose them.

```chemql
namespace Geometry
    public let PI = 3.14159
    public func area
        return [\1 * \2]
    endfunc
    private let secret = 42
endnamespace

Geometry::area{3, 4}
Geometry::PI
```

Calling a private member from outside raises `PermissionError`. Namespaces nest.

### Shell commands

````chemql
`ls -la`                  // one command

```bash
cd /tmp
echo "state persists between commands"
```
````

The shell is persistent: `cd` and shell variables carry over. ChemQL uses `bash` on Linux and macOS and PowerShell on Windows. Output is streamed live, and interactive programs that read the keyboard work.

### History

```chemql
dump session.txt                // queries and results
dump good queries ok.cql        // only successful queries
dump bad results errors.txt     // only the output of failed commands
```

Syntax: `dump [all|good|bad] [queries|results] FILE`.

### Other commands

| Command | Purpose |
|---|---|
| `view` | Open the interactive periodic table in your browser |
| `clear` | Clear the terminal |
| `version` | Print the version |
| `help`, `?`, `help{topic}` | Help; topics include `syntax`, `errors`, `files`, `chemistry`, `stdlib`, built-in names, modules and installed packages |
| `exit` | Quit |

---

## Standard library and packages

### Loading modules

```chemql
load math                          // then call math::function{...}
math::sqrt{81}                     // 9.0

load math::statistics
math::statistics::mean{2, 4, 6}    // 4

load text as t                     // alias
t::upper{"hello"}

load sqrt from math                // import one public member
```

Qualified calls require an explicit `load`. Use `help{stdlib}` to list modules and `help{math::sqrt}` for individual functions.

| Module | Highlights |
|---|---|
| `math` | `PI` `E` `TAU`, `sqrt` `cbrt` `floor` `ceil` `factorial` `gcd` `lcm` `hypot` `pow`, trigonometry, `log` `log10` `log2` `exp`, `isfinite` `isinf` `isnan` `isclose` |
| `math::statistics` | `mean` `median` `mode` `multimode` `quantiles` `variance` `stdev` `pvariance` `pstdev` `harmonic_mean` `geometric_mean` |
| `text` | case conversion, `strip`, `startswith`, `endswith`, `find`, `count`, `isalpha` and friends, `regex_search` `regex_findall` `regex_replace` |
| `collections` | `unique` `flatten` `zip` `pairwise` `frequencies` `group_count` `product` `sorted` `reversed` |
| `datetime` | `today` `now` `utcnow` `date` `time` `timestamp` `from_timestamp` `weekday` `date_add_days` `date_difference_days` |
| `json` | `dumps` `dumps_pretty` `loads` `json_type` |
| `random` | `seed` `random` `randint` `randrange` `choice` `sample` `shuffle` `uniform` |
| `decimal` | `create` `add` `subtract` `multiply` `divide` `quantize` `to_string` |
| `fractions` | `create` `add` `subtract` `multiply` `divide` `numerator` `denominator` `to_float` |
| `pathlib` | `name` `stem` `suffix` `parent` `join` `exists` `is_file` `is_dir` `read_text` `write_text` |

### Package manager

```bash
chemql search "periodic"            # search the registry
chemql info NAME                    # registry metadata
chemql install NAME                 # latest release
chemql install NAME --version 1.2.0
chemql upgrade NAME                 # re-download, replacing the installed copy
chemql list                         # installed packages
chemql uninstall NAME
```

Inside the interactive prompt, use `install PACKAGE [--version VERSION]`. Packages install to `~/.chemql/packages/NAME/VERSION` and are then loaded with `load NAME`. When resolving `load a::b`, ChemQL looks for `a/b.cql` in the current directory, then in installed packages (newest version first, honouring the manifest's `main` entry), then in the bundled `stdlib`. Releases that the registry has not marked as safe are refused.

### Creating a package

```bash
chemql init mypkg         # scaffolds cqlpackage.json, mypkg.cql and README.md
cd mypkg
chemql build              # dist/mypkg-1.0.0.tar.gz
chemql upload             # to the registry (10 MB limit)
```

`cqlpackage.json` (a `cqlpackage.toml` with the same keys is also accepted):

```json
{
    "name": "mypkg",
    "author": "",
    "version": "1.0.0",
    "description": "A ChemQL package named mypkg.",
    "help": "README.md",
    "main": "mypkg.cql",
    "submodules": [],
    "buildsystem": "chemql-build",
    "chemql-dependencies": [],
    "python-dependencies": [],
    "readme": "README.md",
    "license": "MIT",
    "source-code": {},
    "help-individual": {}
}
```

```chemql
// mypkg.cql
public func hello
    return "Hello from mypkg!"
endfunc
```

```chemql
load mypkg
mypkg::hello{}
help{mypkg}               // renders the manifest's `help` Markdown file
help{mypkg::hello}        // uses the `help-individual` entry for `hello`
```

A build needs a manifest and at least one `.cql` file. Version control folders, virtual environments and `dist` are excluded from the archive.

---

## Python API

```python
from chemql import execute_query_text

oxygen = execute_query_text('search elements symbol = "O"')
print(oxygen.name, oxygen.atomic_mass)
```

`execute_query_text(text)` returns the raw result: an `Element`, `Molecule` or `Reaction`, a list, a table (`ReturnTable`), a count or a string. Query-level mistakes (a typo in a key, a bad operator) are usually returned as a formatted `Error: ...` string rather than raised.

`execute_query(text)` is a typed variant: it returns `str`, `Molecule`, `Element`, `Reaction` or `Unknown`, and wraps anything else (lists, tables, counts) in `Unknown`, whose `.value` holds the raw result.

### Fluent query builder

```python
from chemql import search, union, intersection

noble = search("elements").category.condition(like="noble gas").return_("name", "symbol")
print(noble.execute())

light = search("elements").atomic_mass.condition(lt=10)
metals = search("elements").category.condition(like="*metal")
print((light & metals).execute())        # intersection; `|` is union
print(union(light, metals).execute())
```

`condition()` accepts exactly one keyword: `eq ne lt lte gt gte like likep has`.

### Lookups and chemistry helpers

```python
from chemql import (
    ELEMENTS, MOLECULES, REACTIONS,
    find_molecule, find_reaction, search_reactions, balance_stoichiometry,
)

find_molecule("water")                          # bundled data only; matches name, formula or IUPAC name
find_reaction("Haber", external=False)          # local data only; external=True also tries Chempirical and Rhea
search_reactions(reversible=True, name="acid")  # strings are case-insensitive substrings; other values are compared exactly

reaction = balance_stoichiometry("H2 + O2", "H2O")
print(reaction)
```

`balance_stoichiometry(reactants, products, reversible=None)` accepts `"A + B"` strings or iterables of formulas and raises `ValueError` if the reaction cannot be balanced uniquely.

**Exported names** (`chemql.__all__`): `Element`, `Molecule`, `Reaction`, `MOLECULES`, `REACTIONS`, `find_molecule`, `find_reaction`, `search_reactions`, `balance_stoichiometry`, `execute_query`, `execute_query_text`, `ChemQLQuery`, `search`, `union`, `intersection`, `ReturnTable`, `Unknown`, `__version__`, and the exceptions `ChemQLError`, `ChemQLBuiltinError`, `TooFewArguments`, `TooManyArguments`, `InvalidArgumentType`, `InvalidArgumentValue`, `FileReadError`, `FileWriteError`. (`ELEMENTS` is importable but not listed in `__all__`.)

---

## Command-line reference

```text
chemql [options]
chemql SUBCOMMAND ...
chemql edit [codecql options] [FILE]
```

| Option | Description |
|---|---|
| *(none)* | Start the interactive prompt (or run piped input) |
| `-c`, `--command CODE` | Execute one command |
| `-f`, `--file FILE` | Execute a file |
| `-o`, `--output FILE` | Write `-c`/`-f` output to a file, without ANSI sequences |
| `--no-ansi` | Strip ANSI styling from output |
| `--suppress-warnings` | Hide `warn` messages |
| `-v`, `--version` | Print the version |
| `--upgrade [VERSION]` | Upgrade ChemQL with pip |
| `--force`, `--dangerously` | With `--upgrade`: force a reinstall, overriding system-package protections |

| Subcommand | Description |
|---|---|
| `install NAME [--version V]` | Install a package from the registry |
| `upgrade NAME [--version V]` | Re-download a package, replacing the installed copy |
| `search QUERY` | Search the registry |
| `info NAME` | Show registry metadata as JSON |
| `list` | List installed packages |
| `uninstall NAME` | Remove an installed package |
| `init [NAME] [-d DIR]` | Scaffold a package project |
| `build` | Build `dist/NAME-VERSION.tar.gz` from the current directory |
| `upload` | Upload the built archive to the registry |
| `edit [FILE]` | Open the [CodecQL](CODECQL.md) editor |

Subcommands cannot be combined with `-c`, `-f` or `-o`.

---

## Configuration and environment

| Variable | Purpose | Default |
|---|---|---|
| `CHEMQL_PACKAGE_DIR` | Where packages are installed and searched | `~/.chemql/packages` |
| `CHEMQL_INSTALLED_FILE` | Installed-package record | `~/.chemql/installed.json` |
| `CHEMSPIDER_API_KEY` | Enables ChemSpider as a molecule source | *(unset)* |

---

## Data sources

ChemQL always consults its bundled data first, so offline queries over the bundled data keep working.

| Data | Source |
|---|---|
| Elements | `data/PeriodicTableJSON.json` |
| Molecules, bonds | `data/Molecules.json`, `data/MoleculeBonds.json` |
| Bond energies (used for ΔH estimates) | `data/BondEnergies.json` |
| Reactions | `data/Reactions.json` |
| Molecules, online fallback | PubChem (PUG REST and PUG-View), ChemSpider, NIST WebBook |
| Reactions, online fallback | Chempirical, Rhea |

The package also bundles `html/periodic_table.html` (used by `view`) and a `stdlib/` directory of `.cql` modules.

<!-- TODO: add attribution and licence notes for the bundled datasets and the services above. -->

---

## Safety

ChemQL runs real code with your permissions: `[ ... ]` and `[[[ ... ]]]` execute Python, backticks and fenced blocks execute shell commands, and `load` runs the source of a package. Only run scripts and install packages you trust. Online lookups need network access and send your query text to the services listed above.

---

## CodecQL editor

CodecQL is a small terminal editor built for ChemQL, with syntax highlighting, inline suggestions and one-key execution.

```bash
chemql edit script.cql
```

See [CODECQL.md](CODECQL.md) for key bindings, configuration and the suggestion-rule format.

---

## License

MIT. See [LICENSE](LICENSE)
