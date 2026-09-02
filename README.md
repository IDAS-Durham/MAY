# MAY

MAY is a high-performance, configuration-driven framework for building synthetic
populations and distributing them across geography, residences, schools,
workplaces and other venues. Nothing in it assumes a particular country or era,
so it works with any administrative hierarchy.

The shipped configuration targets the modern-day UK (England 2021). Out of the
box it builds County Durham and Darlington, two local authorities sized to run on
a laptop. Since the data covers all four nations, widening the build is a config
change. The USER_GUIDE explains how.

## What it does

You supply census-style inputs: a geographical hierarchy, age × sex demographics
for the smallest unit, household composition counts, and venue inventories.
`create_world.py` turns those into one HDF5 file, `world_state.h5`, holding the
whole synthetic world. That means every person, where they live, where they go to
school or work or receive care, and the friendship and romantic-partnership
networks between them.

YAML configuration files drive the pipeline, so building a new world means
editing YAMLs and CSVs rather than Python.

## Documentation

- [Docs page](https://idas-durham.github.io/MAY/) holds the full documentation.
- [USER_GUIDE.md](USER_GUIDE.md) walks through every YAML and CSV: configuring
  geography filters, editing household allocation, swapping census years, turning
  debug outputs on. Read it before changing any config.

## Install

Requires Python 3.13+. Any environment manager will do, and Conda is the one we
use:

```bash
conda create -n MayEnv python=3.13 -y
conda activate MayEnv
pip install -r requirements.txt
```

Or with `venv`:

```bash
python3.13 -m venv .venv
source .venv/bin/activate          # macOS / Linux
.venv\Scripts\activate             # Windows
pip install -r requirements.txt
```

## Get the data

The repo ships without the bulky census and venue CSVs. Fetch them once:

```bash
python scripts/get_data.py
```

This downloads the archive and unpacks it into `data/`. It uses only the standard
library, so it runs the same way on Windows, macOS and Linux. Pass `--force` to
replace an existing `data/` directory.

On macOS and Linux, `bash scripts/get_data.sh` does the same thing.

## Run

```bash
# Default config (configs/2021/config.yaml)
python create_world.py

# Custom config / output file
python create_world.py --config configs/2021/config_uk_test.yaml --filename uk.h5
```

The run writes `output/2021/world_state.h5`. Its directory comes from
`serialization.output_dir` in the config and its name from
`serialization.filename`, which `--filename` overrides.

## Project layout

```
MAY/
├── create_world.py     # Main entry point
├── configs/            # All user-facing configuration (2021, 1911)
├── data/               # Input CSVs (census-style), fetched separately
├── may/                # Core engine (generic, world-agnostic)
├── docs/               # Source for the documentation site
├── scripts/            # get_data.py and get_data.sh
├── tests/              # test_unit/, test_integration/
└── output/             # Written by a run; world_state.h5 lands here
```

## Testing

```bash
pytest                                          # all tests
pytest tests/test_unit/may/population/          # specific module
```

`pytest` is not in `requirements.txt`, so install it separately to run the suite.

## Viewing the world

Two separate tools can display a finished world:

- [MAY-viewer](https://github.com/mtcorread/MAY-viewer)
- [MAY-world-visualiser](https://github.com/gavdoubleu/may_world_visualiser)

## Requirements

Python 3.13+ and the packages pinned in `requirements.txt` (`numpy`, `pandas`,
`scipy`, `numba`, `h5py`, `PyYAML`).

## License

GNU General Public License v3.0. See [LICENSE](https://github.com/IDAS-Durham/MAY/blob/main/LICENSE).

Copyright (C) 2026 Martha Correa. This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
