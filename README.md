# ChemQL

**ChemQL** is a Python-powered chemistry query language and interactive
command-line environment. Query chemical datasets with a compact,
SQL-inspired syntax, inspect elements and molecules, look up reactions,
balance equations, and combine chemistry queries with Python and shell
commands.

-   **Version:** `1.3.0`
-   **PyPI distribution:** `chemql-python`
-   **Python import / CLI name:** `chemql`
-   **Author:** Mohammad Rakibul Islam

> ChemQL is a learning and productivity tool, not a substitute for
> authoritative chemical references or professional laboratory guidance.
> Results depend on the available data and implemented calculations.

## Contents

-   [Highlights](#highlights)
-   [Installation](#installation)
-   [Start and quick start](#start-and-quick-start)
-   [Query language](#query-language)
-   [Filters and result operations](#filters-and-result-operations)
-   [Lookup commands](#lookup-commands)
-   [Reaction tools](#reaction-tools)
-   [Python integration](#python-integration)
-   [Functions, definitions, and
    macros](#functions-definitions-and-macros)
-   [Structs and records](#structs-and-records)
-   [Shell integration and scripting](#shell-integration-and-scripting)
-   [CLI options and history export](#cli-options-and-history-export)
-   [Python API](#python-api)
-   [Data sources and network access](#data-sources-and-network-access)
-   [Troubleshooting](#troubleshooting)
-   [Security](#security)
-   [Development and contributing](#development-and-contributing)
-   [License and attribution](#license-and-attribution)

## Highlights

-   Search bundled element, molecule, and reaction datasets.
-   Filter records using comparisons, wildcard matching, boolean logic,
    and collection membership.
-   Sort, limit, count, and project query results.
-   Combine compatible result sets with `union` and `intersection`.
-   Find elements, molecules, and reactions with convenience commands.
-   Balance supported chemical equations and match supplied reactants
    against stored reactions.
-   Set reaction temperature, pressure, and catalysts for supported
    matching.
-   Use Python statements, expressions, variables, control flow,
    functions, macros, and structured values.
-   Execute shell commands and multiline shell blocks from the REPL.
-   Export recorded commands and results.
-   Use the command-line interface or import ChemQL from Python.

## Installation

ChemQL is distributed as `chemql-python`; the executable and import name
are `chemql`.

**Requirements:** Python 3.10 or newer. `prompt_toolkit` is installed as
a dependency. Internet access is needed only for optional online lookups
or package upgrades.

Install from PyPI:

``` bash
python -m pip install --upgrade chemql-python
```

### Windows PowerShell

``` powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade chemql-python
chemql
```

### Linux, macOS, or WSL

``` bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade chemql-python
chemql
```

If `chemql` is not found, confirm that you installed the package into
the Python environment you are currently using:

``` bash
python -m pip show chemql-python
python -m pip install --upgrade chemql-python
```

## Start and quick start

Start the interactive prompt:

``` bash
chemql
```

At the prompt, try:

``` text
help
version
list all
findel "He"
findmol "Water"
findre "Haber process"
search elements symbol = "Fe"
search molecules molecular_weight < 50 sort molecular_weight limit 10
balance H2 + O2 -> H2O
exit
```

-   `help` or `?` prints the built-in guide.
-   `version` prints the running version.
-   `list all` shows available sources and fields.
-   `exit` leaves the prompt.

## Query language

A typical query starts with `search`, a source, optional conditions, and
optional result operations:

``` text
search <source> <conditions> <result operations>
```

Available sources:

  Source        Contents
  ------------- -----------------------------------------
  `elements`    Element / periodic-table records
  `molecules`   Bundled molecule records and properties
  `reactions`   Bundled reaction records

Use `source` to set the current source for commands that rely on it:

``` text
source elements
source molecules
source reactions
```

### Select fields

Use `return` to choose which fields are displayed:

``` text
search elements symbol = "O" return name symbol number atomic_mass
search molecules name like "*water*" return name formula molecular_weight
search reactions reversible = true return name equation source
```

A single returned field can be displayed as a list; multiple fields are
formatted as a table. Use `list all` to check valid field names.

## Filters and result operations

### Comparison operators

  Operator      Meaning
  ------------- ------------------------------
  `=` / `!=`    Equal / not equal
  `>` / `<`     Greater / less than
  `>=` / `<=`   Greater / less than or equal

``` text
search elements number >= 10
search molecules molecular_weight < 25
search reactions reversible = true
```

### Matching and logic

  Operator      Meaning
  ------------- ----------------------------------------
  `like`        Case-insensitive pattern matching
  `like!`       Case-sensitive pattern matching
  `likep`       Pattern-oriented matching
  `has`         Tests whether a value contains an item
  `and`, `or`   Combine conditions
  `( ... )`     Group conditions

The `*` wildcard matches a sequence of characters in `like` patterns:

``` text
search molecules name like "*water*"
search elements number > 10 and number < 20
search molecules (name like "*water*" or formula = "H2O") and molecular_weight < 25
```

### Result operations

  -------------------------------------------------------------------------
  Operation               Purpose                 Example
  ----------------------- ----------------------- -------------------------
  `return FIELD ...`      Choose fields to        `return name formula`
                          display                 

  `sort FIELD`            Sort results            `sort molecular_weight`

  `sort FIELD asc`        Ascending order         `sort number asc`

  `sort FIELD desc`       Descending order        `sort number desc`

  `limit N`               Limit result count      `limit 10`

  `first` / `last`        Select an end result    `first`

  `count`                 Count matches           `count`

  `union`                 Combine result sets     See below

  `intersection`          Keep common results     See below
  -------------------------------------------------------------------------

Examples:

``` text
search molecules molecular_weight < 20 sort molecular_weight asc limit 5
search elements number < 10 union search elements number > 90
search molecules name like "*water*" intersection search molecules molecular_weight < 50
```

Set operations are intended for compatible result sets.

## Lookup commands

### `findel`

Find an element by name or symbol:

``` text
findel "He"
findel "Helium"
findel "Fe"
```

### `findmol`

Find a molecule by name or formula. ChemQL searches locally first and
may try external lookup services if the local dataset has no match.

``` text
findmol "Water"
findmol "H2O"
findmol "Ethanol"
findmol "Water" return name formula molecular_weight
```

External molecule lookup requires network access and can fail if a
service is unavailable.

### `findre`

Find a reaction by name, ID, or equation:

``` text
findre "Haber process"
findre "ethanol"
findre "RHEA:..."
findre "propanol" return name equation source reactants products
```

`findre` checks local reaction records first and can then try external
sources such as Chempirical and Rhea. External results may have
different metadata from local records. For deterministic offline
searching, use `search reactions ...`, which searches the bundled
dataset only.

## Reaction tools

### Balance equations

``` text
balance H2 + O2 -> H2O
balance Fe + O2 -> Fe2O3
balance N2 + H2 <-> NH3
```

The balancer supports the formula notation accepted by its parser.
Complex ionic equations or unusual formula syntax may require checking
or simplifying. `->` denotes a forward equation; reversible arrows such
as `<->` are accepted by supported command syntax.

### Match reactants to stored reactions

``` text
react N2 3H2
react H2 O2
```

`react` attempts to match the supplied reactants against stored reaction
records and the active conditions. It is a dataset lookup, not a
general-purpose reaction predictor, and cannot guarantee that a reaction
will occur.

### Conditions

``` text
set temperature 723K
set temperature 150C
set temperature 300F
set temperature room
set temperature standard

set pressure 101325Pa
set pressure 2bar
set pressure 1atm
set pressure room
set pressure standard

set catalysts iron zinc
add catalyst "Vanadium oxide"
remove catalyst "Vanadium oxide"
set catalysts
conditions
```

Supported temperature units include `C`, `F`, and `K`. Pressure syntax
includes `Pa`, `N/m^2`, `Nm^-2`, `bar`, and `atm` forms accepted by the
parser. The built-in help describes `standard` as 0 °C and 100000 Pa,
and `room` as 25 °C and 101325 Pa. Use `set catalysts` without names to
clear the catalyst list.

Reaction matching and calculations depend on the bundled records and
implementation; they are not experimental validation or safety advice.

## Python integration

Square brackets execute Python statements or expressions, and Python
state can be reused in the session:

``` text
[x = 10]
[print(x)]
[x * 2]
```

Use `{{ ... }}` to evaluate a ChemQL query as a Python value:

``` text
{{ search elements name = "Hydrogen" }}
let hydrogen = {{ search elements name = "Hydrogen" }}
```

The returned value depends on the query result shape.

## Control Flow

ChemQL supports conditional statements and loops, allowing you to control the execution of your code. Native control-flow syntax uses keywords such as `if`, `endif`, `while`, `endwhile`, `for`, and `endfor` without requiring square brackets.

### Conditional statements: `if`, `else`, and `endif`

Use `if` to execute a block only when a condition is true. The optional `else` block executes when the condition is false. Close the conditional with `endif`.

```text
let temperature = 25

if temperature > 30
    print("It is hot")
else
    print("It is not too hot")
endif
```

You can also use `if` without an `else`:

```text
if temperature > 20
    print("Above 20 degrees")
endif
```

### While loops: `while` and `endwhile`

A `while` loop repeats its body as long as its condition remains true. Use `endwhile` to close the loop.

```text
let counter = 0

while counter < 5
    print(counter)
    counter = counter + 1
endwhile
```

Make sure the condition eventually becomes false; otherwise, the loop may run indefinitely.

### For loops: `for` and `endfor`

Use `for` to iterate over a sequence or other supported iterable. The loop ends at `endfor`.

```text
for i in range(5)
    print(i)
endfor
```

This prints the numbers from `0` through `4`.

You can also iterate over a list:

```text
let fruits = ["Apple", "Banana", "Orange"]

for fruit in fruits
    print(fruit)
endfor
```

### Nested control-flow blocks

Control-flow statements can be nested. Each closing keyword must match its corresponding opening statement.

```text
for i in range(3)
    if i > 0
        print(i)
    endif
endfor
```

For nested loops, close the innermost loop first:

```text
for i in range(3)
    for j in range(2)
        print(i, j)
    endfor
endfor
```

### Bracketed Python-style syntax

ChemQL also supports bracketed Python-style control-flow blocks, which use `endblock` as the closing keyword.

**Conditional example:**

```text
[if 3 > 2]
    [print("True")]
[else]
    [print("False")]
[endblock]
```

**While loop example:**

```text
let counter = 0

[while counter < 3]
    [print(counter)]
    [counter = counter + 1]
[endblock]
```

**For loop example:**

```text
[for i in range(5)]
    [print(i)]
[endblock]
```

### Summary

| Native syntax | Purpose |
|---|---|
| `if ... endif` | Conditional execution |
| `if ... else ... endif` | Choose between two branches |
| `while ... endwhile` | Repeat while a condition is true |
| `for ... endfor` | Iterate over a sequence |
| `endblock` | Close a bracketed Python-style control-flow block |

Use native control-flow syntax for ChemQL's keyword-based blocks, and bracketed syntax when writing Python-style blocks. Always match each opening statement with the appropriate closing keyword.

For a multiline Python block, start with `[[[` and close with `]]]` on
its own line:

``` text
[[[
for i in range(3):
    print(i)
]]]
```

Use `let` to assign session values:

``` text
let answer = 42
let double = answer * 2
```
## Error Handling and Cleanup

ChemQL provides `risk`, `fix`, `cleanup`, and `signal` for handling errors, responding to failures, and organizing cleanup logic.

### `risk`

Use `risk` to mark a block of code that may encounter an error and needs special handling.

```text
risk
    [result = 10 / 0]
endrisk
```

This illustrates the idea of protecting potentially failing code. The exact behaviour depends on ChemQL's implementation of `risk`.

### `fix`

Use `fix` to define how ChemQL should respond when an error occurs in a corresponding `risk` block.

```text
risk
    [result = 10 / 0]
fix
    [print("An error occurred")]
endrisk
```

This example illustrates the intended relationship between `risk` and `fix`. Check the implementation for the precise syntax and whether execution continues after an error.

### `cleanup`

Use `cleanup` to organize code that should run as part of a cleanup phase associated with a protected operation.

```text
risk
    [print("Performing operation")]
fix
    [print("Handling an error")]
cleanup
    [print("Cleaning up")]
endrisk
```

Cleanup logic is useful for keeping resource-management steps separate from the main operation and its error-handling logic.

### `signal`

Use `signal` to explicitly raise or report an error when a condition cannot be handled normally.

```text
if temperature < 0
    signal "Temperature cannot be negative"
endif
```

A signal can make an invalid state or failed operation explicit instead of allowing execution to proceed silently.

### Summary

| Keyword | Purpose |
|---|---|
| `risk` | Marks potentially failing code for special handling |
| `fix` | Specifies error-handling behaviour |
| `cleanup` | Organizes cleanup logic |
| `signal` | Raises or reports an error |
| `endrisk` | Ends the risk handler |

These features help make ChemQL scripts easier to maintain by separating normal execution, error handling, and cleanup responsibilities.

## Functions, definitions, and macros

These definitions are session-local and should be declared before they
are used.

### Literal definitions

``` text
define MAX 9
search elements number <= @MAX
definitions
remove definition MAX
```

A definition is a literal replacement, not a Python variable. Choose
names and replacement text carefully.

### Functions

Functions use `func`, positional placeholders such as `\1` and `\2`, and
`endfunc`:

``` text
func square
    return [\1 * \1]
endfunc

square{5}
```

Example with two arguments:

``` text
func add
    return [\1 + \2]
endfunc

add{10, 32}
```

Test more complex function bodies against your installed build before
using them in larger scripts.

### Macros

Macros expand reusable ChemQL text with positional placeholders:

``` text
define light{}
    search molecules molecular_weight < \1 return name formula
enddefine

@light{50}
macros
```

Use `\1`, `\2`, and subsequent placeholders for arguments. The `macros`
command lists definitions in the current session.

## Structs and records

ChemQL v1.3.0 includes named structured values, constructors, variables,
and user-defined methods. This area is evolving; test advanced method
dispatch and operator overloading in the exact build you use.

``` text
struct Fruit
    name
    price
endstruct

let apple = Fruit{name="Apple", price=35}
apple
apple.name
apple.price
```

The implementation also supports defining methods on structured types.
Special methods such as `__add__` are intended for custom behaviour, but
do not assume every Python data-model feature or operator dispatch path
is fully implemented.

## Shell integration and scripting

Backticks execute a command through the host system shell:

``` text
`pwd`
`python --version`
```

The shell and command syntax depend on the operating system: Windows
PowerShell / Command Prompt differ from Bash and other POSIX shells.

Multiline shell blocks use triple backticks. Labels such as `bash`,
`sh`, `cmd`, and `terminal` are recognised, but the commands must be
valid for the host shell:

```` text
```bash
echo "Starting"
python --version
echo "Finished"
```
````

Other conveniences:

``` text
// A single-line comment
///
A multiline comment.
///
view
clear
```

Commands can be separated with semicolons, and a trailing backslash can
continue a line where supported by the input processor. `view` opens the
bundled periodic-table viewer in a browser where the environment allows
it. `clear` clears the terminal.

## CLI options and history export

  Command                         Purpose
  ------------------------------- -----------------------------------------------
  `chemql`                        Start the REPL
  `chemql --version`              Print the version
  `chemql -c "COMMAND"`           Execute a command
  `chemql -f FILE`                Execute commands from a file
  `chemql --no-ansi`              Disable ANSI styling
  `chemql -c "COMMAND" -o FILE`   Write command output to a text file
  `chemql --upgrade`              Upgrade to the latest release
  `chemql --upgrade VERSION`      Request a particular release
  `chemql --force`                Force upgrade past system-package protections

Examples:

``` bash
chemql --version
chemql -c 'search elements symbol = "O"'
chemql -c 'search molecules name like "*water*" return name formula' -o results.txt
chemql -f examples.chemql
```

Quote commands according to your shell's rules.

The `dump` command exports recorded execution history, queries, and
results:

``` text
dump history.txt
dump all queries queries.txt
dump good results results.txt
dump bad executions failures.txt
```

Supported forms include `dump all|good|bad FILE`,
`dump all|good|bad queries FILE`, and `dump all|good|bad results FILE`.
`good` and `bad` select successful and failed executions respectively.

## Python API

``` python
from chemql import execute_query_text, execute_query

result = execute_query_text('search elements symbol = "O"')
print(result)
```

`execute_query_text()` accepts a query string and returns its formatted
execution result. `execute_query()` is a lower-level entry point;
accepted inputs and return values depend on the query path.

The package also exposes helpers including `search`, `union`,
`intersection`, `find_molecule`, `find_reaction`, `search_reactions`,
and `balance_stoichiometry`. For example:

``` python
from chemql import find_molecule, find_reaction

water = find_molecule("Water")
reaction = find_reaction("Haber process", external=False)
```

`find_reaction(value, external=False)` restricts reaction lookup to the
local dataset; its default lookup can use online fallback sources. Check
the installed module for the precise public API of your release.

## Data sources and network access

### Bundled data

Bundled local data is the primary source for normal queries and keeps
core searching available offline. The package uses files for element /
periodic-table records, molecule records and properties, reaction
records and conditions, molecule bonds, and bond-energy data. Coverage
depends on the data shipped with the release.

### External molecule services

If a molecule is not found locally, `findmol` can attempt an external
lookup. The code includes PubChem integration and additional lookup
paths. External requests require network access and may fail because of
timeouts, outages, rate limits, changed API responses, or missing
credentials for a particular provider.

### External reaction services

If `findre` cannot find a local reaction, it can try Chempirical and
Rhea. These services are fallback sources, not replacements for
`Reactions.json`. In contrast, `search reactions ...` and
`search_reactions()` search local records only.

Remote records may differ from local records in fields, participant
formats, equations, and annotations. Some operations may not be possible
if a remote source does not provide all the required structured
information. A failed lookup does not prove that a substance or reaction
does not exist.

Preserve source attribution and check upstream dataset licences and
reuse terms when redistributing data.

## Troubleshooting

### `chemql` is not recognised

Check that the package was installed in the active environment:

``` bash
python -m pip show chemql-python
python -m pip install --upgrade chemql-python
```

### No matches are returned

-   Use `list all` to verify source and field names.
-   Start with a simple query and add conditions one at a time.
-   Remember that `search reactions` is local-only; use `findre` if you
    want its external fallback.
-   Check spelling, formula notation, and wildcard patterns.

### Online lookup fails

Check network access and retry later. Remote services may be temporarily
unavailable. Use local data when you need predictable offline behaviour.

### A reaction lacks fields you expected

Inspect `source`, `id`, `equation`, `reactants`, and `products`. Local
and external records can have different metadata and participant
coverage.

### Python block syntax errors

Check Python indentation, close `[if]`, `[for]`, and `[while]` blocks
with `[endblock]`, and close `[[[` blocks with `]]]` on a line by
itself. Reduce the block to a small reproducible example if necessary.

### Shell commands behave differently

ChemQL invokes the host shell. PowerShell, Command Prompt, Bash, and
other shells have different syntax and quoting rules. Test a failing
command in your normal terminal to isolate shell-specific behaviour.

### ANSI escape codes appear in output

Try `chemql --no-ansi`, or use `-o FILE` to write command output to a
plain-text file where supported.

## Security

ChemQL's Python blocks and shell commands execute real code with the
permissions of the running process; they are not a sandbox.

-   Run only scripts and commands you trust.
-   Shell commands can read, modify, or delete files and launch
    programs.
-   Network lookup terms are sent to the relevant external service.
-   Do not place passwords, tokens, or other secrets in scripts,
    exported histories, or public bug reports.
-   Verify important chemical calculations and claims against
    authoritative references.

## Development and contributing

ChemQL is actively evolving. Areas for future improvement may include
broader parser and multiline tests, additional validation of struct
methods and operator overloading, more robust participant normalization
across remote databases, clearer handling of ambiguous online results,
improved data provenance, and wider compatibility testing across
Windows, Linux, macOS, and WSL. These are possible development
directions, not a promise that every item is already implemented.

Bug reports and contributions are welcome. When reporting a problem,
include:

1.  ChemQL version (`chemql --version`).
2.  Operating system and Python version.
3.  A minimal reproducible query or script.
4.  Actual output and expected output.
5.  Whether the issue occurs with local data only or requires an
    external lookup.

Do not include passwords, API tokens, or unrelated private information
in issue reports.

## License and attribution

[MIT License](https://github.com/rakibulofficial1017/ChemQL/blob/main/LICENSE)

Created by [Mohammad Rakibul Islam](https://github.com/rakibulofficial1017).
Source code: [rakibulofficial1017/ChemQL](https://github.com/rakibulofficial1017/ChemQL).

------------------------------------------------------------------------

For the command reference that matches your installed build, type `help`
inside ChemQL. Use `list all` to inspect fields available in your
bundled datasets.
