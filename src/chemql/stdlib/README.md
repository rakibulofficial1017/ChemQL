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
```
