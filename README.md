# ChemQL --- Chemistry Query Language

**Query chemistry like a database. Mix chemistry queries, Python, and
shell commands in one interactive environment.**

ChemQL is a command-line chemistry query language for exploring chemical
elements, molecules, and reactions. Version 1.2.4 combines database-style
chemistry queries, reaction tools, Python interoperability, reusable functions
and macros, and a persistent shell in one scriptable environment. It combines a small SQL-inspired
query syntax with a persistent Python environment, reaction utilities,
optional external molecule lookup, and tools for running repeatable
scripts.

> **Version covered by this README:** 1.2.4\
> The examples below describe the ChemQL 1.2.4 source. Dataset
> contents and external-service availability can affect individual
> lookup results.

## Contents

-   [Highlights](#highlights)
-   [Installation](#installation)
-   [Starting ChemQL](#starting-chemql)
-   [Your first queries](#your-first-queries)
-   [Sources and data fields](#sources-and-data-fields)
-   [Filtering and query logic](#filtering-and-query-logic)
-   [Sorting, limiting, counting, and returning
    fields](#sorting-limiting-counting-and-returning-fields)
-   [Quick lookup commands](#quick-lookup-commands)
-   [Molecules from external chemistry
    sources](#molecules-from-external-chemistry-sources)
-   [Chemical reactions](#chemical-reactions)
-   [Balancing equations](#balancing-equations)
-   [Preprocessor, functions, and macros](#preprocessor-functions-and-macros)
-   [Mixing ChemQL with Python](#mixing-chemql-with-python)
-   [Multiline Python blocks](#multiline-python-blocks)
-   [Running shell commands](#running-shell-commands)
-   [Comments, semicolons, and line
    continuation](#comments-semicolons-and-line-continuation)
-   [Scripts, pipes, and output files](#scripts-pipes-and-output-files)
-   [Session history and exports](#session-history-and-exports)
-   [Terminal experience](#terminal-experience)
-   [Python API](#python-api)
-   [Query syntax reference](#query-syntax-reference)
-   [Examples](#examples)
-   [Troubleshooting](#troubleshooting)

## Highlights

-   **Three queryable chemistry sources:** `elements`, `molecules`, and
    `reactions`.
-   **Database-style filtering:** equality, inequality, numeric
    comparisons, pattern matching, containment, and grouped Boolean
    logic.
-   **Useful result operations:** choose the first or last match, sort
    ascending or descending, limit results, count matches, and project
    selected fields.
-   **Readable results:** one selected field returns a list; multiple
    fields are formatted as a column-aligned table.
-   **Quick lookups:** find elements by name or symbol, molecules by
    name or formula, and reactions by name, identifier, or equation.
-   **External molecule lookup:** ChemQL can try local data first and
    then use online chemistry services, including PubChem and the NIST
    Chemistry WebBook, when available.
-   **Reaction exploration:** search reaction records and match
    reactants against the current reaction conditions and catalysts.
-   **Equation balancing:** balance reaction equations with smallest
    positive integer coefficients.
-   **Reaction conditions:** configure temperature, pressure, and
    catalysts before running reaction matching.
-   **Hybrid Python:** execute Python expressions and statements, retain
    variables between commands, and embed ChemQL query results directly
    inside Python.
-   **Preprocessor definitions:** define reusable literal values with `define`
    and `@NAME` references.
-   **User-defined functions:** define reusable Python-backed functions with
    positional arguments and return values.
-   **Source-generating macros:** define reusable ChemQL command sequences
    and expand them with arguments.
-   **Python control flow:** use `if`/`elif`/`else`, `for`, `while`,
    `break`, and `continue` blocks.
-   **Multiline Python:** use `[[[` ... `]]]` for a single multiline
    Python block.
-   **Integrated shell:** execute commands in a persistent Bash or
    Windows Command Prompt session using backticks or fenced terminal
    blocks.
-   **Comments and convenient command composition:** use `//` comments,
    `///` multiline comments, semicolon-separated commands, and
    backslash line continuation.
-   **Interactive assistance:** syntax highlighting, command completion,
    built-in help, and a browser-based periodic-table viewer.
-   **Scriptable CLI:** run a command, run a file, pipe input through
    standard input, disable ANSI escape sequences, or save clean output
    to a file.
-   **Execution-history exports:** save all, successful, or failed
    queries and results.
-   **Python integration:** import the query API and build queries
    programmatically.
-   **Upgrade helper:** request the latest release or a particular
    version from the CLI.

## Installation

Install the Python package from PyPI:

``` bash
pip install chemql-python
```

## Upgrading the package or switching versions

If your chemql-python version is >=1.0.1, you can simply run
```bash
chemql --upgrade
``` 
Or to switch versions to for example 0.2.2
```bash
chemql --upgrade 0.2.2
``` 
However if you do not have chemql-python version >=1.0.1
```bash
pip install --upgrade chemql-python
```
Or to switch versions to for example 0.2.2
```bash
pip install --force-reinstall chemql-python==0.2.2
```
If your chemql-python version is >=1.1.0, and the terminal respond with something like "This environment is externally managed" then you can run 
```bash
chemql --upgrade --force
```
OR
```bash
chemql --upgrade --dangerously
```
Else
```bash
pip install --upgrade chemql-python --break-system-packages
```

However, this is highly discouraged and creating a venv using `python -m venv .` and activating it with `source .venv/bin/activate` on MacOS/Linux or `.\.venv\Scripts\Activate.ps1`

## Starting ChemQL

Start the interactive prompt:

``` bash
chemql
```

At the prompt, type `help` or `?` to see the built-in command reference.
Type `exit` or press `Ctrl+C` to leave.

Check the installed version:

``` bash
chemql --version
```

You can also use the language as a one-off command:

``` bash
chemql -c 'search elements name = "Hydrogen"'
```

## Your first queries

ChemQL has three main sources. Specify the source in a query:

``` text
search elements
search molecules
search reactions
```

A source can be selected for subsequent searches:

``` text
source elements
search name = "Hydrogen"
search number = 1
```

You can always state a source explicitly:

``` text
search elements name = "Hydrogen"
search molecules formula = "H2O"
search reactions reaction_type = "combustion"
```

To list the available fields for the active source---or the fields
across all sources when no source is selected---use:

``` text
list all
```

## Sources and data fields

ChemQL ships with local JSON datasets for its chemistry sources. Exact
records and fields depend on the bundled dataset version.

### Elements

The element records include fields such as:

`name`, `symbol`, `number`, `atomic_mass`, `appearance`, `category`,
`phase`, `density`, `melt`, `boil`, `molar_heat`, `period`, `group`,
`block`, `shells`, `electron_configuration`,
`electron_configuration_semantic`, `electron_affinity`,
`electronegativity_pauling`, `ionization_energies`, `discovered_by`,
`named_by`, `summary`, `source`, `image`, `bohr_model_image`,
`bohr_model_3d`, `spectral_img`, `xpos`, `ypos`, `wxpos`, `wypos`, and
`cpk-hex`.

Example:

``` text
search elements symbol = "Fe" return name symbol number atomic_mass
search elements phase = "Gas" return name symbol
search elements electronegativity_pauling > 3 return name symbol electronegativity_pauling
```

The element `number` field is the atomic number.

### Molecules

Molecule records include:

`name`, `formula`, `elements`, `molecular_weight`, `iupac_name`,
`smiles`, `cid`, `melting_point`, `boiling_point`, `density`, `state`,
`bonds`, and `total_bond_energy`.

Example:

``` text
search molecules formula = "H2O"
search molecules molecular_weight < 50 return name formula molecular_weight
search molecules state = "Liquid" return name formula
```

Bond information and calculated total bond energy are available when
present in the bundled bond datasets.

### Reactions

Reaction records include:

`id`, `name`, `equation`, `reaction_type`, `reversible`, `reactants`,
`products`, `conditions`, `notes`, and `source`.

Example:

``` text
search reactions reaction_type = "combustion"
search reactions reversible = true return name equation
search reactions name like "*Haber*" return name equation source
```

## Filtering and query logic

ChemQL supports the following comparison and matching operators:

  -------------------------------------------------------------------------------------------
  Operator                Meaning                 Example
  ----------------------- ----------------------- -------------------------------------------
  `=`                     Equal                   `search elements symbol = "O"`

  `!=`                    Not equal               `search elements phase != "Gas"`

  `>`                     Greater than            `search molecules molecular_weight > 100`

  `<`                     Less than               `search elements number < 10`

  `>=`                    Greater than or equal   `search elements number >= 90`

  `<=`                    Less than or equal      `search molecules molecular_weight <= 20`

  `like`                  Case-insensitive        `search molecules name like "*water*"`
                          wildcard pattern        

  `like!`                 Case-sensitive wildcard `search elements name like! "Hydrogen"`
                          pattern                 

  `likep`                 Pattern matching with   `search molecules formula likep "*H*"`
                          the parser's pattern    
                          mode                    

  `has`                   Check whether a value   `search molecules elements has "O"`
                          contains an item        
  -------------------------------------------------------------------------------------------

Use `and` and `or` to combine conditions:

``` text
search elements number > 10 and number < 20
search molecules name like "*acid*" or name like "*base*"
```

Parentheses let you group conditions:

``` text
search molecules (name like "*water*" or formula = "H2O") and molecular_weight < 25
```

Patterns are useful when you only know part of a name or formula. For
exact supported pattern behavior, try a query against the local dataset
and inspect the results.

## Sorting, limiting, counting, and returning fields

These operations can be added to a search query.

### Sort

``` text
search elements sort number
search molecules sort molecular_weight desc
search reactions sort name asc
```

Use `asc` for ascending or `desc` for descending order.

### Limit

``` text
search molecules limit 10
search elements number > 20 sort number limit 5
```

### Count

``` text
search molecules count
search reactions reversible = true count
```

### First and last

``` text
search elements first number > 10
search elements last number < 20
```

You can also put `first` or `last` immediately after `search`:

``` text
search first elements number > 10
search last molecules molecular_weight < 100
```

### Return only selected fields

A single field returns a one-dimensional list. Multiple fields return a
table.

``` text
search molecules molecular_weight < 20 return name
search molecules molecular_weight < 20 return name formula molecular_weight
search reactions reversible = true return name equation source
```

Filtering and result operations can be combined:

``` text
search elements number > 10 and number < 30 sort number desc limit 5 return name symbol number
```

### Set operations

Query results can be combined using `union` or `intersection`:

``` text
search elements number < 10 union search elements number > 90
search molecules name like "*water*" intersection search molecules molecular_weight < 50
```

These operations are useful when you want to combine or compare result
sets.

## Quick lookup commands

### Find an element

``` text
findel "He"
findel "Hydrogen"
```

`findel` searches element names and symbols.

### Find a molecule

``` text
findmol "H2O"
findmol "Water"
findmol "Caffeine" return name formula molecular_weight
```

`findmol` checks the local molecule dataset first, then can try external
lookup if no local match is found.

### Find a reaction

``` text
findre "Haber process"
findre "RHEA:10000"
findre "H2 + N2"
findre "Haber process" return name equation source
```

`findre` searches reaction names, identifiers, and equations.

### View the periodic table

``` text
view
```

This opens ChemQL's bundled periodic-table page in your default browser.

## Molecules from external chemistry sources

When a molecule is not found locally, ChemQL can attempt an online
lookup using external chemistry services such as **PubChem** and the
**NIST Chemistry WebBook**.

``` text
findmol "acetone"
findmol "caffeine"
findmol "water"
```

The lookup code can retrieve or derive properties including molecular
identifiers and basic chemical data; availability depends on the
external service, network access, and whether a matching record exists.
External lookup is not required for ordinary searches against the
bundled local dataset.

## Chemical reactions

ChemQL can search stored reaction records and has commands for setting
reaction conditions before attempting to match reactants.

### Set temperature

Temperature values support Celsius (`C`), Fahrenheit (`F`), and Kelvin
(`K`):

``` text
set temperature 450K
set temperature 150C
set temperature 300F
set temperature standard
set temperature room
```

`standard` corresponds to 0 °C; `room` corresponds to 25 °C.

### Set pressure

Pressure values support Pa, N/m², Nm⁻², bar, and atm, as well as the
`standard` and `room` presets:

``` text
set pressure 101325Pa
set pressure 2bar
set pressure 1atm
set pressure standard
set pressure room
```

The presets use 100000 Pa for `standard` and 101325 Pa for `room`.

### Configure catalysts

``` text
set catalysts iron zinc
add catalyst "Vanadium oxide"
remove catalyst "Vanadium oxide"
set catalysts
```

`set catalysts` with no values clears the catalyst list. `add catalyst`
adds a catalyst if it is not already present; `remove catalyst` removes
a matching catalyst.

### Inspect current conditions

``` text
conditions
```

Unset temperature or pressure values are shown as not set.

### Match reactants

``` text
react N2 3H2
```

`react` attempts to find a matching reaction using the supplied
reactants and the current reaction conditions. The implementation uses a
temperature tolerance of 5 K and a pressure tolerance of 5% for reaction
matching. A match depends on the available reaction records and their
conditions.

## Balancing equations

Use `balance` to balance a chemical equation:

``` text
balance H2 + O2 -> H2O
balance Fe + O2 -> Fe2O3
balance N2 + H2 <-> NH3
```

-   `->` represents an irreversible reaction.
-   `<->` represents a reversible reaction.
-   ChemQL aims to return the smallest positive integer coefficients.

The result is represented as a reaction object, which can also be
queried or inspected from Python.

## Preprocessor, functions, and macros

ChemQL 1.2.5 adds three ways to reuse values and logic. These declarations
are processed in source order: definitions affect later lines, not earlier
ones. They persist during the current ChemQL process/session; they are not
saved automatically between separate launches.

### Literal definitions

Use `define NAME value` to store a literal replacement. Reference it as
`@NAME` in later ChemQL commands, Python blocks, or shell commands.

``` text
define MAX 9
define ELEMENT "Hydrogen"
definitions

search elements number <= @MAX return name symbol number
search elements name = @ELEMENT
remove definition MAX
```

Definitions are textual replacements, not typed variables. They are
expanded literally, including inside quoted strings, and a definition's
replacement text is not recursively expanded in the same pass. `definitions`
shows active definitions; `remove definition NAME` removes one.

### User-defined functions

Declare a function with `func NAME` and finish it with `endfunc`. Use `\1`,
`\2`, and so on as positional argument placeholders. A `return` line gives
the function's result; arguments are evaluated as Python expressions.

``` text
func square
return [\1 * \1]
endfunc

square{5}
search molecules molecular_weight < square{5} return name formula molecular_weight
```

Functions can contain multiple commands and `[[[` multiline Python blocks.
Function-local Python assignments are restored after the call; return a value
explicitly when you need one. Function calls use braces, for example
`name{argument1, argument2}`.

### Macros

Macros expand into ChemQL source lines. Declare one using `define NAME{}`
and close it with `enddefine`. Use `\1`, `\2`, etc. for arguments, then call
the macro with `@NAME{arguments}`.

``` text
define light_molecules{}
search molecules molecular_weight < \1 return name formula molecular_weight
enddefine

@light_molecules{50}
```

Macros are useful for reusable query recipes or command sequences. Arguments
are substituted into the macro's source text, so quote or validate values
appropriately when passing text that contains spaces or special characters.

## Mixing ChemQL with Python

ChemQL is a hybrid language: a single-line Python expression or
statement can be enclosed in square brackets.

``` text
[x = 10]
[print(x)]
[x * 2]
```

Python variables persist for the session, so later blocks can use values
created earlier.

``` text
[import math]
[radius = 5]
[area = math.pi * radius**2]
[print(area)]
```

Python's built-in namespace is available, and `math` is preloaded.
**Only run Python or shell code you trust**: these blocks execute real
code, not a sandboxed query language.

### Embed ChemQL queries in Python

Use `{{ ... }}` to run a ChemQL query and insert its result into Python
code:

``` text
[hydrogen = {{ search elements name = "Hydrogen" }}]
[print(hydrogen)]
```

A query block can also be used on its own as a value-producing
expression:

``` text
{{ search molecules molecular_weight < 20 return name formula }}
```

This is useful when you want ChemQL to find data and Python to
calculate, transform, or display something using that data.

### Python control-flow blocks

ChemQL supports block-style Python control flow:

``` text
[if value > 10]
    [print("Large")]
[elif value == 10]
    [print("Exactly ten")]
[else]
    [print("Small")]
[endblock]
```

Loop example:

``` text
[for element in {{ search elements number < 5 }}]
    [print(element.name, element.symbol)]
[endblock]
```

A `while` block is also supported:

``` text
[i = 0]
[while i < 3]
    [print(i)]
    [i += 1]
[endblock]
```

Use `[break]` and `[continue]` inside loops. As with ordinary Python,
make sure a `while` loop has a condition that eventually becomes false
unless you intentionally want it to continue.

### Multiline Python blocks

For longer Python code, use `[[[` to start a block and a line containing
`]]]` to finish it:

``` text
[[[
values = {{ search elements number < 10 return name }}
for value in values:
    print(value)
]]]
```

ChemQL executes the block as one Python unit and captures its printed
output as one result. Keep the closing `]]]` on its own line.

## Running shell commands

ChemQL can run shell commands using backticks. It keeps a shell session
alive so commands can share shell state.

``` text
`echo Hello from the shell`
`pwd`
```

For a multiline command, use a fenced block. The opening fence can
optionally name a shell:

```` text
```bash
echo "First line"
echo "Second line"
```
````

Windows users can use a `cmd` fence:

```` text
```cmd
echo Hello from Windows
ver
```
````

Supported opening forms include a plain triple-backtick fence and fences
labelled `bash`, `sh`, `cmd`, or `terminal`. Close the block with a line
containing three backticks.

**Security note:** shell blocks run real operating-system commands with
your user's permissions. Review commands before executing them,
especially commands copied from untrusted sources.

## Comments, semicolons, and line continuation

### Single-line comments

Use `//` for comments:

``` text
search elements number < 10 // The first nine elements
```

The comment marker is intended to be recognized outside quoted strings.

### Multiline comments

Use `///` to begin and end a multiline comment:

``` text
/// This is a comment.
It can continue across multiple lines.
The whole comment is ignored. ///
search elements symbol = "O"
```

A multiline comment can also be written with opening and closing markers
on the same line.

### Semicolon-separated commands

Run multiple ChemQL commands on one line with semicolons:

``` text
source elements; search name = "Hydrogen"; search number = 8
```

ChemQL's command splitter tracks quotes and bracketed/query expressions
so semicolons inside quoted strings or protected blocks are not treated
as command separators.

### Line continuation

End a line with `\` to continue the command on the next line:

``` text
search elements \
number > 10 and \
number < 20 \
sort number desc \
limit 5
```

The continued lines are treated as one command.

## Scripts, pipes, and output files

### Run a command

``` bash
chemql -c 'search elements symbol = "O"'
```

### Run a file

Save commands in a `.cql` or `.chemql` file, for example `explore.cql`:

``` text
search elements number < 10 return name symbol number
search molecules molecular_weight < 50 sort molecular_weight return name formula molecular_weight
```

Run it:

``` bash
chemql -f explore.cql
```

Both `.cql` and `.chemql` are suitable file extensions; the CLI accepts
a file path.

### Pipe commands through standard input

``` bash
echo 'search elements symbol = "O"' | chemql
```

You can also pipe a multi-line script into ChemQL:

``` bash
cat explore.cql | chemql
```

On Windows PowerShell, use `Get-Content explore.cql | chemql` or
redirect a file into the command.

### Show version and upgrade

``` bash
chemql --version
chemql --upgrade
chemql --upgrade 1.2.4
```

`--upgrade` installs the latest published `chemql-python` release; supplying a
version requests that specific release. The optional `--force` (also accepted
as `--dangerously`) bypasses system-package protections. Use that option only
when you understand the consequences for your Python environment.

### Disable ANSI escape sequences

``` bash
chemql --no-ansi -c 'search elements symbol = "O"'
```

This is useful when redirecting output to logs or processing it with
other tools.

### Write clean output to a file

Use `-o` / `--output` together with `-c` or `-f`:

``` bash
chemql -c 'search elements number < 10 return name symbol' -o elements.txt
chemql -f explore.cql --output results.txt
```

The output file is written without ANSI escape sequences. `-o` requires
either `-c` or `-f`.

## Session history and exports

ChemQL records queries and results processed during the session. Use
`dump` to export that history to a UTF-8 text file.

``` text
dump session.txt
dump all session.txt
dump good session-successes.txt
dump bad session-errors.txt
dump all queries queries.txt
dump good results successful-results.txt
dump bad results failed-results.txt
```

Available forms:

  Command                    What it exports
  -------------------------- ------------------------------------
  `dump FILE`                All recorded queries and results
  `dump all FILE`            All recorded queries and results
  `dump good FILE`           Successful executions
  `dump bad FILE`            Failed executions
  `dump all queries FILE`    All recorded queries only
  `dump good queries FILE`   Successful queries only
  `dump bad queries FILE`    Failed queries only
  `dump all results FILE`    All results only
  `dump good results FILE`   Results from successful executions
  `dump bad results FILE`    Results from failed executions

The `good` and `bad` categories use ChemQL's execution-status tracking.
Shell command exit codes are not necessarily equivalent to ChemQL's own
error tracking.

## Terminal experience

In interactive mode, ChemQL provides:

-   **Syntax highlighting** for ChemQL commands, operators, fields,
    strings, and related syntax.
-   **Tab completion** for commands, sources, fields, and context-aware
    suggestions.
-   **Built-in help** through `help` or `?`.
-   **A periodic-table viewer** through `view`.
-   **ANSI styling** for readable terminal output, with `--no-ansi`
    available for plain output.
-   **Persistent Python variables** across Python blocks.
-   **A persistent shell session** for backtick and fenced shell
    commands.
-   **Friendly exit controls:** type `exit` or press `Ctrl+C`.

## Python API

ChemQL can also be used from Python. The public query function is
`execute_query_text()`:

``` python
from chemql import execute_query_text

result = execute_query_text('search elements name = "Hydrogen"')
print(result)
```

`execute_query_text()` accepts a query string and returns its query
result. Depending on the query, that result may be a chemistry object,
list, table-like result, count, string, or `None`.

The higher-level `execute_query()` wrapper is also available:

``` python
from chemql import execute_query

result = execute_query('search molecules formula = "H2O"')
print(result)
```

The package exposes chemistry classes such as `Element`, `Molecule`, and
`Reaction`, as well as helper functions including `search`, `union`, and
`intersection`. Public APIs can evolve between versions; consult the
installed source and `help()` for the exact version you use.

## Query syntax reference

A typical query follows this pattern:

``` text
search [first|last|all] SOURCE [conditions] [sort FIELD [asc|desc]] [limit N] [count] [return FIELD ...]
```

Examples:

``` text
search elements number = 8
search molecules name like "*acid*" sort molecular_weight limit 10
search reactions reversible = true return name equation
```

Common commands:

  Command                   Purpose
  ------------------------- -------------------------------------
  `search ...`              Query a source
  `source NAME`             Set the current source
  `list all`                List fields
  `findel VALUE`            Find an element
  `findmol VALUE`           Find a molecule
  `findre VALUE`            Find a reaction
  `react ...`               Match reactants to stored reactions
  `balance ...`             Balance a chemical equation
  `set temperature VALUE`   Set reaction temperature
  `set pressure VALUE`      Set reaction pressure
  `set catalysts ...`       Replace the catalyst list
  `add catalyst NAME`       Add a catalyst
  `remove catalyst NAME`    Remove a catalyst
  `conditions`              Show reaction conditions
  `view`                    Open the periodic-table viewer
  `dump ...`                Export execution history
  `clear`                   Clear the terminal
  `help` / `?`              Show help
  `version`                 Print the ChemQL version
  `exit`                    Leave the interactive prompt

## Examples

### Find noble gases

``` text
search elements category like "*noble gas*" return name symbol number
```

### Find relatively light molecules

``` text
search molecules molecular_weight < 50 sort molecular_weight asc limit 10 return name formula molecular_weight
```

### Find reactions of a particular type

``` text
search reactions reaction_type = "combustion" return name equation reversible
```

### Explore and export a session

``` text
search elements number < 20 return name symbol number
search molecules molecular_weight < 100 return name formula molecular_weight
dump all results chemistry-results.txt
```

### Combine a query with Python

``` text
[light_molecules = {{ search molecules molecular_weight < 50 return name }}]
[print("Found names:", light_molecules)]
```

### Use ChemQL from a Python script

``` python
from chemql import execute_query_text

elements = execute_query_text(
    'search elements number < 10 return name symbol'
)
print(elements)
```

## Troubleshooting

-   **`No source selected`:** specify a source in the query, such as
    `search elements ...`, or set one with `source elements`.
-   **Unknown field:** run `list all` after selecting a source to see
    its available field names. Use `number` for an element's atomic
    number in the current data model.
-   **No local molecule match:** `findmol` may try online lookup, which
    requires network access and an available external service.
-   **Output contains terminal escape codes:** add `--no-ansi` or use
    `-o FILE` with `-c` or `-f`.
-   **A multiline block is incomplete:** close a Python block with `]]]`
    on its own line or a terminal block with three backticks on its own
    line.
-   **Python or shell command behaves unexpectedly:** remember that
    these execute real code in your environment. Check quotes,
    indentation, and the exact command before running it.
-   **A reaction does not match:** check the available reaction records,
    the reactant spelling and stoichiometry, and the temperature,
    pressure, and catalyst settings.

## Safety and scope

ChemQL is a chemistry data/query tool, not a replacement for
authoritative chemical references, laboratory procedures, or
professional safety guidance. Dataset coverage and online service
responses may be incomplete. Validate important scientific results
against appropriate primary or authoritative sources.

Python and shell blocks execute real code with your operating-system
user's permissions. Do not run scripts or commands you do not trust.

------------------------------------------------------------------------

**ChemQL --- Python Chemistry Query Language**
