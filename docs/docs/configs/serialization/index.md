# Serialization

Controls what is written to the HDF5 world-state file. Core fields (agent id, age, sex, geographical unit; venue id, name, type) are always exported. Everything else is opt-in via the lists below.

| File | Purpose |
|---|---|
| [`serialization_config.yaml`](serialization-config.md) | Selects population properties, venue properties, relationship data, compression, and metadata written to `world_state.h5` |
