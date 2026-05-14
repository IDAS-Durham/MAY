# World Creation Pipeline

`create_world.py` builds a synthetic population world — geography, venues, people, households, and social networks — and serialises it to HDF5 for simulation.

## Running the script

```
python create_world.py --config <path/to/config.yaml> [--filename <output.h5>]
```

`--config` selects the [master config](configs/master-config.md); `--filename` overrides the output path set therein.

## Pipeline overview

| # | Stage | Description | Config |
|---|-------|-------------|--------|
| [1](#1-initialisation) | Initialisation | Fix random seeds for reproducibility | — |
| [2](#2-config-cli) | Config & CLI | Load master YAML; apply CLI overrides | [Master config](configs/master-config.md) |
| [3](#3-geography) | Geography | Load geographical unit hierarchy and coordinates | [Master config](configs/master-config.md) |
| [4](#4-venues) | Venues | Load venue type catalogue; instantiate all venues | [Venues config](configs/venues/venues-config.md) |
| [5](#5-population) | Population | Load demographics; generate individual population | [Master config](configs/master-config.md) |
| [6](#6-households) | Households | Allocate population to household venues | [Households config](configs/households/households-config.md) |
| [7](#7-world-assembly) | World assembly | Aggregate all components into a single World object | — |
| [8](#8-timeline-pipeline) | Timeline pipeline | Run ordered attribute, distributor, and child-creator steps | [Attributes](configs/attributes/attribute-assignment.md), [Distributors](configs/distributors/venue-distributor.md), [Child creators](configs/venue-child-creators/venue-child-creators.md) |
| [9](#9-relationship-pipeline) | Relationship pipeline | Build social networks | [Social networks](configs/relationships/social-networks.md) |
| [10](#10-romantic-relationships) | Romantic relationships | Assign sexual orientation and romantic partnerships | [Romantic relationships](configs/relationships/romantic-relationships.md) |
| [11](#11-hdf5-export) | HDF5 export | Serialise world to HDF5 | [Serialisation config](configs/serialization/serialization-config.md) |

---

## Stages

### 1. Initialisation

Sets `PYTHONHASHSEED` and the global random seed to `0` before any other step. This ensures runs are reproducible: the same config will yield the same world on any machine.

### 2. Config & CLI

Parses `--config` and `--filename` from the command line, then loads the [master config YAML](configs/master-config.md). All subsequent stages draw their settings from this file. `--filename` overrides whichever output path the config specifies.

### 3. Geography

Constructs the geographical hierarchy — large, medium, and small geographical units (LGU/MGU/SGU) — from the CSV files declared in the [master config](configs/master-config.md). Coordinates are loaded at this stage and attached to each unit.

### 4. Venues

Creates a `VenueManager` and loads the venue type catalogue from the [venues config](configs/venues/venues-config.md). All venue instances — schools, workplaces, hospitals, and the like — are populated here before any person is assigned to them.

### 5. Population

Loads population demographics from the files named in the [master config](configs/master-config.md). In matrix mode, individual `Person` objects are generated from the demographic matrix at this stage; in explicit mode they are loaded directly.

### 6. Households

If household distribution is enabled, allocates people to household venues according to the rules in the [households config](configs/households/households-config.md) and its [allocation strategy](configs/households/allocation-strategy.md). Household composition and relationship rules are applied here.

### 7. World assembly

Combines geography, population, venues, and the household distributor into a single `World` object. Nae computation happens here; it is purely aggregation before the pipeline stages begin.

### 8. Timeline pipeline

Executes an ordered sequence of steps defined in the [master config](configs/master-config.md) `timeline` section. Each step is one of three kinds:

- **Attribute assignment** — assigns properties (e.g. ethnicity, comorbidities) to people. Configured via [attribute-assignment](configs/attributes/attribute-assignment.md).
- **Venue distributor** — allocates people to non-household venues (schools, workplaces, care homes, etc.). Configured via [venue distributor](configs/distributors/venue-distributor.md) and its [variants](configs/distributors/multi-venue-distributor.md).
- **Venue child creator** — generates sub-venues within a parent venue (e.g. classrooms within a school). Configured via [venue child creators](configs/venue-child-creators/venue-child-creators.md).

Order matters: steps run sequentially, so later distributors can depend on attributes assigned earlier.

### 9. Relationship pipeline

Builds social networks amongst the population using the configs listed under `relationships` in the master config. Each network is constructed independently; see [social networks](configs/relationships/social-networks.md) for the full schema.

### 10. Romantic relationships

If enabled, assigns sexual orientation to each person then forms romantic partnerships. Configured via the [romantic relationships config](configs/relationships/romantic-relationships.md).

### 11. HDF5 export

Serialises the completed world to an HDF5 file. The [serialisation config](configs/serialization/serialization-config.md) controls which fields are written; omitting a field reduces file size. The output path is set in the master config and may be overridden with `--filename`.
