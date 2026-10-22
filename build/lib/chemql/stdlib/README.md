# ChemQL Standard Library

Optional ChemQL packages using Python's standard library only. Keep the `stdlib/`
directory next to the interpreter module and preserve the folder layout.

| Package | Purpose |
| --- | --- |
| `math` | Constants, trigonometry, logarithms, number theory |
| `math::statistics` | Mean, median, mode, variance, standard deviation, quantiles |
| `text` | String transformations, splitting/joining, regular expressions |
| `collections` | Uniqueness, flattening, pairing, frequency counts, product |
| `datetime` | Dates, timestamps, local/UTC time and date arithmetic |
| `json` | JSON encode/decode helpers |
| `random` | Pseudo-random numbers and sequence sampling |
| `decimal` | Base-10 decimal arithmetic and quantization |
| `fractions` | Exact rational numbers and fraction arithmetic |
| `pathlib` | Path inspection and UTF-8 text file operations |

Examples:

```chemql
load math
math::PI
math::sqrt{81}

load math::statistics
math::statistics::mean{2, 4, 6}

load text
text::upper{"hello"}
text::split{"red,green,blue", ","}
text::regex_findall{"[A-Z][a-z]+", "Water and Sodium Chloride"}

load collections
collections::unique{1, 2, 1, 3}
collections::frequencies{"red", "blue", "red"}

load datetime
datetime::date{2026, 10, 20}
datetime::date_add_days{"2026-10-20", 7}

load json
json::loads{"{\"formula\": \"H2O\"}"}

load random
random::seed{42}
random::randint{1, 6}

load decimal
decimal::add{"0.1", "0.2"}
decimal::quantize{"3.14159", "0.01"}

load fractions
fractions::create{1, 3}
fractions::add{"1/3", "1/6"}

load pathlib
pathlib::name{"data/results.csv"}
pathlib::join{"data", "results.csv"}
```

Use `help{stdlib}` for the package index, `help{math}` for a module
overview, and `help{math::sqrt}` for function help. The help pages are
available whether or not a package has been loaded.

`pathlib::read_text` and `pathlib::write_text` access files using the
current process permissions. `random` uses Python's pseudo-random
generator; call `random::seed{value}` when repeatable results are needed.
