# Network builder function requirements

## Signature

```python
def build_my_network(world, network_config: dict) -> None:
```

## Responsibilities

- Read `storage_key = network_config["storage_key"]`
- Read `activity_config = network_config.get("assign_activity", None)`
- Build contacts for each person
- Call `store_contacts(person, contacts, storage_key, activity_config)` for each person with connections
- Return `None`

## Storage contract

All writes to `person.properties` and `person.activity_map` must go via `store_contacts` (from `builder_functions/store.py`). Direct property writes are discouraged — `store_contacts` handles set semantics and accumulation across multiple networks sharing the same `storage_key`.

## YAML assign_activity schema

```yaml
assign_activity:
  contact_activity_key: residence      # key to read from contact.activity_map
  activity_key: household_visits       # key to write into person.activity_map
```

`contact.activity_map[contact_activity_key]` is `dict[str, list[Subset]]`. Results accumulate across calls.

## Registration

```python
from may.social_networks.social_networks import register_network_type
from .builder_functions.my_module import build_my_network

register_network_type("my_network")(build_my_network)
```
