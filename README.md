# MAY

A high-performance, **configuration-driven** population simulation framework for building synthetic populations and distributing them across geography, residences, schools, workplaces, and other venues. Generic by design: works with any administrative hierarchy, any era, any country.

The shipped configuration targets **modern-day UK** (e.g. England 2021).

## What it does

Given census-style inputs — a geographical hierarchy, age × sex demographics per smallest unit, household composition counts, and venue inventories — `create_world.py` produces a single HDF5 file (`world_state.h5`) containing the full synthetic world: every person, where they live, where they go to school / work / receive care, and the friendship and romantic-partnership networks between them.

The whole pipeline is driven by **YAML configuration files**. The Python code does not need to be edited to build a new world; users edit YAMLs and CSVs only.

## Documentation

- **[Docs Page](https://idas-durham.github.io/MAY/)** - Full documentation.
- **[USER_GUIDE.md](USER_GUIDE.md)** — walkthrough of every YAML and CSV: how to configure geography filters, edit household allocation, swap census years, disable debug outputs, etc. Read this before changing any config.

## Install

Requires Python 3.13+. Use any environment manager you like — Conda is recommended:

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

The repo ships without the bulky census/venue CSVs. Fetch them once with:

```bash
bash scripts/get_data.sh
```

This downloads and unpacks the dataset into `data/`.

## Run

```bash
# Default config (configs/2021/config.yaml)
python create_world.py

# Custom config / output file
python create_world.py --config configs/2021/config.yaml --filename world_state.h5
```

Output: `world_state.h5` (HDF5) at the project root.

## Project layout

```
MAY/
├── create_world.py     # Main entry point
├── configs/               # All user-facing configuration
├── data/               # Input CSVs (census-style)
├── may/                # Core engine (generic, world-agnostic)
├── world_specific_code/# World-specific extensions (Modern_Day_UK, MedievalYaml, …)
└── world_state.h5      # Output
```


## Testing

```bash
pytest                                          # all tests
pytest tests/test_units/may/population/         # specific module
```

Note: `pytest` is not in `requirements.txt`. Install separately if you want to run the suite.

## Viewing the world
There are two codes that can be used for viewing the world.
[MAY-viewer](https://github.com/mtcorread/MAY-viewer)
[MAY-world-visualiser](https://github.com/gavdoubleu/may_world_visualiser)

## Requirements

Python 3.13+ and the packages pinned in `requirements.txt` (`numpy`, `pandas`, `scipy`, `numba`, `h5py`, `PyYAML`).

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).

Copyright (C) 2026 Martha Correa. This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
