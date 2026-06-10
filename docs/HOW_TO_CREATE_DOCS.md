# How the docs work

## Overview

[MkDocs](https://www.mkdocs.org/) with the [Material theme](https://squidfunk.github.io/mkdocs-material/) builds a static HTML site from `.md` files in `docs/docs/`. The [mkdocstrings](https://mkdocstrings.github.io/) plugin reads Python docstrings at build time and renders them into the relevant page. The `gen-files` plugin (`docs/gen_pages.py`) generates the `may/*.md` API stub pages on the fly at build time — nothing under `docs/docs/may/` is committed. Navigation is controlled by `docs/docs/.nav.yml` via the `awesome-nav` plugin.

All commands must be run from the `docs/` directory. Either the conda environment `MISC`, or `pip install -r docs/requirements.txt` (a lighter env with just the doc-build packages), has the required packages.

## Serve locally

```bash
bash serve.sh          # live-reload server at http://127.0.0.1:8000
```

## Deploy to GitHub Pages

A push to `main` that touches `docs/` or `may/` triggers `.github/workflows/docs.yml`, which builds the site and pushes it to the `gavin_docs` branch on `origin` (the live GitHub Pages source).

To deploy manually instead:

```bash
bash deploy_github.sh  # builds and pushes to gavin_docs branch on origin
```

## API reference stubs (`docs/docs/may/`)

These pages are generated automatically at build/serve time by `gen_pages.py` (the `gen-files` plugin) — one stub per `.py` file in `may/`, nothing committed. New modules appear under `may:` in the nav automatically via `"*"`.

Files in directories without `__init__.py` are skipped; griffe cannot render them.

## Navigation (`docs/docs/.nav.yml`)

Edit `.nav.yml` to control the sidebar. `"*"` includes all remaining files and subdirectories at that level recursively.

## Root-level files

`docs/docs/README.md`, `USER_GUIDE.md`, and `LICENSE.md` are symlinks to the repository root. Edits to the root files are reflected automatically.

## Docstring requirements

- The module's directory must have `__init__.py`.
- Docstrings should follow [Google style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings).
