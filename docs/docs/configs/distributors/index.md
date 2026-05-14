# Distributors

Each file assigns agents to a venue type by setting an entry in their `activity_map`. Distributors run in the order specified by `settings.priority`; order matters because `require_unassigned: true` skips agents already placed.

| File | Covers | Notes |
|---|---|---|
| [`venue-distributor.md`](venue-distributor.md) | school, university, company, hospital | Full shared schema; key differences by type summarised at foot of page |
| [`multi-venue-distributor.md`](multi-venue-distributor.md) | cinema, grocery, gym, pub | Assigns N closest venues of each type per agent |
| [`specific-workplace-distributors.md`](specific-workplace-distributors.md) | hospital, care_home, classroom (as workplaces) | Routes sector-coded workers to specific venue types |
| [`care-home-visits.md`](care-home-visits.md) | care_home | Links households of care home residents as visitors |
