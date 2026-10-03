# ChemQL periodic table viewer

This folder contains the interactive periodic table page used by ChemQL’s `view` command.

## File

- `periodic_table.html`
  - A browser-based periodic table UI for visualizing element metadata.
  - It can be opened directly in a browser or launched from ChemQL via the `view` command.

## How it is used

In the main ChemQL interpreter, the `view` command calls the browser to open the periodic table page stored here:

```python
view_periodic_table()
```

This resolves the bundled HTML file in the `chemql` package and opens it with the system browser.

## Features

- searchable element browser
- visual periodic table layout
- element detail display
- optional model-viewer support for element visualization
- browser-based access without requiring a separate web backend

## Notes

The page is a lightweight front-end for the element data stored in the package's `data/` directory, especially `PeriodicTableJSON.json`. It is intended to complement the text-based ChemQL REPL rather than replace it.

To open it manually from a browser, open the generated HTML file directly or run the `view` command from the ChemQL prompt.
