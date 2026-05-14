# social_networks.yaml

Defines one or more social contact networks. Each entry in the `networks:` list is built independently and written to a `storage_key` on each person. Multiple networks sharing the same key are merged (contacts deduplicated).

**Topic:** [Relationships](index.md)  
**Path:** `configs/2021/relationships/social_networks.yaml`

---

## Full Schema

```yaml
networks:

  - name: "activity_peers"            # arbitrary label for logging

    # ----------------------------------------------------------
    # Pool selection
    # ----------------------------------------------------------
    network_type: "activity_peers"    # how the candidate pool is constructed:
                                      # "activity_peers"       — people sharing the same venue activity
                                      # "intra_geo_unit"       — people in the same geo unit
                                      # "local_social_network" — all people in a geo unit (Watts-Strogatz)
                                      # "spatial_social_network" — people within a distance annulus

    pool_type: "activity"             # "activity" | "geographic"

    pool:
      # -- activity pool --
      activity: "primary_activity"    # activity_map key to match on

      # -- geographic pool --
      level: "SGU"                    # geo level: SGU / MGU / LGU / XLGU / custom name
      min_km: 0.01                    # optional — minimum distance in km (spatial networks only)
      max_km: 4.0                     # optional — maximum distance in km (spatial networks only)

    # ----------------------------------------------------------
    # Algorithm
    # ----------------------------------------------------------
    algorithm: "random"               # "random"        — uniform random sampling
                                      # "watts_strogatz" — clustered small-world graph

    clustering_level: 0.8             # optional — rewiring probability for watts_strogatz (0–1)
                                      # higher = more clustered, lower = more random

    # ----------------------------------------------------------
    # Contact counts
    # ----------------------------------------------------------
    mean_count: 3                     # mean contacts per person from this network

    degree_variants:                  # optional — override count for a subset of people
      - probability: 0.10             # fraction of people receiving this count
        count: 6

    # ----------------------------------------------------------
    # Storage
    # ----------------------------------------------------------
    storage_key: "friendships"        # person property key where contacts are stored
                                      # networks sharing the same key are merged

    assign_activity:                  # optional — create an activity_map entry per contact
      contact_activity_key: "residence"   # activity on the contact to link to
      activity_key: "social_contacts_local"  # key written to the person's activity_map

    # ----------------------------------------------------------
    # Constraints
    # ----------------------------------------------------------
    constraints:                      # optional — filters on who can be paired
      - type: "numerical_attribute_difference"
        attribute: "age"
        max_difference: 5             # |age_1 - age_2| must not exceed this
        # min_difference: 0           # optional lower bound
```

---

## Minimal Examples

**Random activity-peer network:**
```yaml
networks:
  - name: activity_peers
    network_type: activity_peers
    pool_type: activity
    pool:
      activity: primary_activity
    algorithm: random
    mean_count: 4
    storage_key: friendships
```

**Spatial Watts-Strogatz network (clustered within distance annulus):**
```yaml
networks:
  - name: near_neighbours
    network_type: spatial_social_network
    pool_type: geographic
    pool:
      level: SGU
      min_km: 0.01
      max_km: 4.0
    algorithm: watts_strogatz
    mean_count: 4
    clustering_level: 0.8
    storage_key: social_contacts_near
    assign_activity:
      contact_activity_key: residence
      activity_key: social_contacts_near
```
