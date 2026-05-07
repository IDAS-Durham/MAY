# How the docs work

## Overview

[MkDocs](https://www.mkdocs.org/) with the [Material theme](https://squidfunk.github.io/mkdocs-material/) builds a static HTML site from `.md` files in `docs/docs/`. The [mkdocstrings](https://mkdocstrings.github.io/) plugin reads Python docstrings at build time and renders them into the relevant page. Navigation is controlled by `docs/docs/.nav.yml` via the `awesome-nav` plugin.

All commands must be run from the `docs/` directory. The conda environment `MISC` has the required packages.

## Serve locally

```bash
bash serve.sh          # live-reload server at http://127.0.0.1:8000
```

## Deploy to GitHub Pages

```bash
bash deploy_github.sh  # builds and pushes to gavin_docs branch on june_collab remote
```

## Update / add module stubs

Run `auto_make_mds.sh` from `docs/`:

```bash
bash auto_make_mds.sh
```

For every `.py` file in `may/` it generates (or overwrites) a corresponding `.md` stub under `docs/docs/may/`. New stubs are logged to `temp_potential_nav_additions.yml` — copy relevant entries into `.nav.yml` if the module is new.

Files in directories without `__init__.py` are skipped; griffe cannot render them.

## Navigation (`docs/docs/.nav.yml`)

Edit `.nav.yml` to control the sidebar. `"*"` includes all remaining files and subdirectories at that level recursively.

## Root-level files

`docs/docs/README.md`, `USER_GUIDE.md`, and `LICENSE.md` are symlinks to the repository root. Edits to the root files are reflected automatically.

## Docstring requirements

- The module's directory must have `__init__.py`.
- Docstrings should follow [Google style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings).
