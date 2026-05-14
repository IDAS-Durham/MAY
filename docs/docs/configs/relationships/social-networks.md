# social_networks.yaml

Defines one or more social contact networks to build after venue allocation. Each network entry is built independently and contacts are written to `storage_key` on each person. Multiple networks sharing the same `storage_key` are merged with deduplication.

**Topic:** [Relationships](index.md)  
**Path:** `configs/2021/relationships/social_networks.yaml`

---

## Keys

| Key | Description |
|---|---|
| `networks` | List of network definitions; each entry builds one network |

---

## `networks`

Each entry in the list is one network. The required keys are `network_type`, `pool_type`, `storage_key`, and `mean_count`. All other keys are optional.

---

### `name`

```yaml
- name: "activity_peers"
```

Arbitrary label used in logs. Defaults to the value of `storage_key` if omitted.

---

### `network_type` and `pool_type`

```yaml
network_type: "activity_peers"
pool_type: "activity"
pool:
  activity: "primary_activity"
```

`network_type` selects the algorithm used to build edges. Five types are registered:

- **`activity_peers`** — connects people who share the same venue activity. Requires `pool_type: "activity"` and `pool.activity` naming the `activity_map` key to match on (e.g. `"primary_activity"`). Uses the fast random builder.
- **`intra_geo_unit`** — connects people within the same geographical unit. Requires `pool_type: "geographic"` and `pool.level` naming the hierarchy level (e.g. `"SGU"`, `"MGU"`). Uses the fast random builder.
- **`local_social_network`** — Watts-Strogatz clustered graph over all people in a geo unit. Requires `pool_type: "geographic"` and `pool.level`. Produces more realistic clustering than the random builders. `clustering_level` defaults to `0.8`.
- **`spatial_social_network`** — Watts-Strogatz graph over people within a distance annulus. Requires `pool_type: "geographic"`, `pool.level`, `pool.min_km`, and `pool.max_km`. `clustering_level` defaults to `0.9`.
- **`bounded_distance`** — clustered graph over people within a radius. Requires `pool_type: "geographic"`, `pool.level`, and `pool.max_km` (no inner radius). `clustering_level` defaults to `0.7`.

`pool_type` must be either `"activity"` or `"geographic"`. It controls how the candidate pool is assembled before edges are drawn.

---

### `mean_count` and `degree_variants`

```yaml
mean_count: 3
degree_variants:
  - probability: 0.10
    count: 6
```

`mean_count` is the target mean number of contacts per person from this network. For the random builders it is used directly as the expected draw count; for Watts-Strogatz builders it sets the base ring degree before rewiring.

`degree_variants` overrides the contact count for a subset of people. Each entry specifies a `probability` (fraction of the population) who receive `count` connections instead of `mean_count`. Multiple variants may be listed; probabilities are applied independently so a person can satisfy more than one variant, with the last matched count winning.

---

### `storage_key`

```yaml
storage_key: "friendships"
```

The key under which contacts are stored in `person.properties`. Networks sharing the same key accumulate contacts into the same set; duplicate contacts across networks are removed. The key must also be listed in `serialization_config.yaml` under `population.properties` to appear in the HDF5 output.

---

### `constraints`

```yaml
constraints:
  - type: "numerical_attribute_difference"
    attribute: "age"
    max_difference: 5
```

An optional list of filters applied when drawing edges. Only `"numerical_attribute_difference"` is currently supported: it rejects a candidate edge if `|person_attr − candidate_attr|` exceeds `max_difference`. `min_difference` may also be specified for a lower bound.

---

### `clustering_level`

```yaml
clustering_level: 0.8
```

Used only by the Watts-Strogatz builders (`local_social_network`, `spatial_social_network`, `bounded_distance`). Controls the rewiring probability: `0.0` produces a perfectly regular ring lattice; `1.0` produces a random graph. Values around `0.7`–`0.9` produce the small-world regime with high clustering and short path lengths. Has no effect on the random builders (`activity_peers`, `intra_geo_unit`).

---

### `assign_activity`

```yaml
assign_activity:
  contact_activity_key: "residence"
  activity_key: "social_contacts_local"
```

When present, creates an additional `activity_map` entry on each person for every contact. `contact_activity_key` names the activity on the *contact* whose venue is used; `activity_key` is the key written to the *person's* `activity_map`. This allows the simulation engine to treat social contact venues as explicit activities. Omit this block if activity-map linking is not needed.
