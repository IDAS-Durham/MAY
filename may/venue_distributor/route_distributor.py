"""
RouteDistributor — generic, route-table-driven distributor.

Turns an `(origin_key, dest_key, class)` triple per person into an ordered list
of leg venues with per-leg numeric metadata. Configuration controls everything
domain-specific (which person attributes feed the keys, which CSV holds the
routes, which venue type and subset receive each leg, which leg columns become
per-membership metadata, what to do on a miss).

Commute is one instance of this distributor; future use-cases (school buses,
freight routes, ferries) plug in by writing a new YAML config — no code change.

Design references (in COMMUTE_PLAN.md):
- D10 — generic distributor, all domain-specific knobs live in YAML.
- D11 — per-membership timing is written via Subset.member_metadata, then
  serialised to a separate HDF5 side-table (see WorldSerializer); we do NOT
  mutate the shared 4-column activity_data array.
- D12 — route-miss fallback: set a configured person attribute (e.g.
  commute_mode = "walk"), no venue, count the miss.
"""

import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd

from .base_distributor import BaseDistributor

logger = logging.getLogger("route_distributor")


class RouteDistributor(BaseDistributor):
    """Generic route-table-driven distributor (see module docstring)."""

    def __init__(self, config_file: str = None, config_dict: Dict = None):
        super().__init__(config_file, config_dict)

        c = self.config
        self.distributor_name = c.get("distributor_name", "route_distributor")
        self.activity_map_key = c.get("activity_map_key", "commute")
        self.leg_venue_type = c.get("leg_venue_type", "transport_line")
        self.leg_subset_key = c.get("leg_subset_key", "rider")

        # Per-membership metadata: {dest_field_name: legs_csv_column}
        # e.g. {"t_board_min": "t_board_min", "t_alight_min": "t_alight_min"}.
        self.leg_metadata = c.get("leg_metadata", {})

        # How to derive the routing-table key for a person.
        # See _derive_keys for the supported shapes.
        self.origin_source = c.get("origin_source", {})
        self.destination_source = c.get("destination_source", {})
        self.class_source = c.get("class_source", "properties.commute_mode")

        # Only act on people whose class_source value matches this. Lets us run
        # one distributor instance per route class (train/tube/bus) cleanly.
        self.class_filter = c.get("class_filter")  # may be None (act on all)

        # person-attribute → mode_class in the routing table. Default identity.
        self.class_map = c.get("class_map", {})

        # on_miss: { set: { property_name: value } } — overwrite a person
        # property when the routing table has no entry for their key. Per D12.
        self.on_miss = c.get("on_miss", {}) or {}
        self.on_miss_set = self.on_miss.get("set", {}) or {}

        # Eligibility: a list of property names the person MUST have set
        # (typically ['commute_mode']).
        self.require_properties = c.get("require_properties", [])

        # Resolve table paths relative to project root if the config came from
        # a file under configs/.
        self.routes_table_path = c.get("routes_table", "data/transport/routes.csv")
        self.legs_table_path = c.get("legs_table", "data/transport/route_legs.csv")
        self.routes_table_path = self._resolve_path(self.routes_table_path)
        self.legs_table_path = self._resolve_path(self.legs_table_path)

        # Lazy state, populated in allocate()
        self._legs_index = None      # (origin, dest, mode_class) -> [leg dicts]
        self._line_to_venue = {}     # line_id -> Venue (lazy cache)
        self._stats = Counter()

        logger.info(
            f"Initialized RouteDistributor '{self.distributor_name}' "
            f"(class_filter={self.class_filter!r}, leg_venue_type={self.leg_venue_type!r})"
        )

    # ---------------------------------------------------------------- helpers
    def _resolve_path(self, p: str) -> str:
        path = Path(p)
        if path.is_absolute() or path.exists():
            return str(path)
        # configs/2021/distributors/foo.yaml -> project root = parent.parent.parent
        if self.config_path is not None:
            project_root = self.config_path.parent.parent.parent
            candidate = project_root / p
            if candidate.exists():
                return str(candidate)
        return str(path)

    def _load_legs_table(self) -> Dict[Tuple[str, str, str], List[Dict[str, Any]]]:
        """Load route_legs.csv and index by (origin_mgu, dest_mgu, mode_class)."""
        legs_path = Path(self.legs_table_path)
        if not legs_path.exists():
            logger.warning(
                f"Legs table not found: {legs_path}. "
                f"All eligible people will be treated as route misses."
            )
            return {}

        # Filter rows by the relevant routing-table mode classes if we have a
        # class_filter — keeps memory bounded on huge national tables.
        mode_classes_keep = None
        if self.class_filter is not None:
            mapped = self.class_map.get(self.class_filter, self.class_filter)
            mode_classes_keep = {mapped}

        logger.info(f"Loading legs table: {legs_path}")
        df = pd.read_csv(legs_path)
        if mode_classes_keep is not None:
            df = df[df["mode_class"].isin(mode_classes_keep)]

        # Required columns + the per-leg metadata columns the config asked for.
        required = {"origin_mgu", "dest_mgu", "mode_class", "leg_idx", "line_id",
                    "board_mgu", "alight_mgu"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"legs table {legs_path} missing columns: {missing}")

        meta_cols = list(self.leg_metadata.values())
        meta_missing = [c for c in meta_cols if c not in df.columns]
        if meta_missing:
            raise ValueError(
                f"legs table missing metadata columns referenced by config: {meta_missing}"
            )

        # Build the index. Sort by leg_idx so the list is leg-ordered.
        df = df.sort_values(["origin_mgu", "dest_mgu", "mode_class", "leg_idx"])
        index: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
        cols = ["leg_idx", "line_id", "board_mgu", "alight_mgu"] + meta_cols
        for row in df[["origin_mgu", "dest_mgu", "mode_class", *cols]].itertuples(index=False):
            key = (row.origin_mgu, row.dest_mgu, row.mode_class)
            entry = {c: getattr(row, c) for c in cols}
            index[key].append(entry)
        logger.info(f"  Indexed {len(df):,} legs across {len(index):,} (O,D,class) routes")
        return dict(index)

    def _derive_key(self, person, world, source: Dict[str, Any]) -> Optional[str]:
        """Derive an MGU-name key for a person from a configured source.

        Supported shapes:
          source: {type: "ancestor", from: "geographical_unit", level: "MGU"}
              -> person.geographical_unit.get_ancestor_by_level("MGU").name
          source: {type: "ancestor", from: "properties.workplace_sgu", level: "MGU"}
              -> world.geography.get_unit(person.properties["workplace_sgu"])
                   .get_ancestor_by_level("MGU").name
          source: {type: "property", from: "properties.foo"}
              -> str(person.properties["foo"])
        """
        if not source:
            return None
        stype = source.get("type", "ancestor")
        frm = source.get("from", "geographical_unit")

        unit = None
        if frm == "geographical_unit":
            unit = getattr(person, "geographical_unit", None)
        elif frm.startswith("properties."):
            prop = frm.split(".", 1)[1]
            val = getattr(person, "properties", {}).get(prop)
            if val is None:
                return None
            if stype == "property":
                return str(val)
            unit = world.geography.get_unit(val)
        else:
            # Direct attribute on the person.
            val = getattr(person, frm, None)
            if val is None:
                return None
            if stype == "property":
                return str(val)
            unit = val

        if unit is None:
            return None
        if stype == "ancestor":
            level = source.get("level")
            if level and unit.level != level:
                unit = unit.get_ancestor_by_level(level)
            if unit is None:
                return None
            return unit.name
        return getattr(unit, "name", None)

    def _get_person_class(self, person) -> Optional[str]:
        src = self.class_source
        if src.startswith("properties."):
            return getattr(person, "properties", {}).get(src.split(".", 1)[1])
        return getattr(person, src, None)

    def _get_or_create_line_venue(self, world, line_id: str, person) -> Optional[Any]:
        """Lazily materialise one venue per line_id. Returns None if no MGU
        can be resolved (shouldn't happen — the rider's residence MGU is always
        loaded)."""
        venue = self._line_to_venue.get(line_id)
        if venue is not None:
            return venue
        # Attach the line venue to the rider's residence MGU. This MGU is
        # guaranteed loaded (the rider lives there) and gives the venue a
        # stable, deterministic location for HDF5 partitioning.
        geo_unit = getattr(person, "geographical_unit", None)
        if geo_unit is not None and geo_unit.level != "MGU":
            geo_unit = geo_unit.get_ancestor_by_level("MGU")
        if geo_unit is None:
            return None
        # No per-venue properties: line_id is recorded as venue.name below
        # (serialised to /metadata/names/venues) and JUNE derives runtime bin
        # counts from N_riders at simulation time, so no capacity metadata
        # is needed here.
        venue = world.venues.create_venue(
            venue_type=self.leg_venue_type,
            geo_unit=geo_unit,
            properties={},
        )
        # Give the venue a stable, human-readable name (matching line_id) so
        # debug dumps and any future external joins work cleanly. We don't
        # re-key venue_manager's name dicts — lookup goes through our own cache.
        venue.name = line_id
        self._line_to_venue[line_id] = venue
        return venue

    def _apply_miss(self, person) -> None:
        for prop, val in self.on_miss_set.items():
            person.properties[prop] = val
        self._stats["misses"] += 1

    def _passes_eligibility(self, person) -> bool:
        props = getattr(person, "properties", {})
        for prop in self.require_properties:
            if prop not in props or props[prop] is None:
                return False
        if self.class_filter is not None:
            if self._get_person_class(person) != self.class_filter:
                return False
        return True

    # -------------------------------------------------------------- main API
    def allocate(self, world) -> None:
        logger.info("=" * 60)
        logger.info(f"RouteDistributor: {self.distributor_name}")
        logger.info("=" * 60)

        # Load routes once.
        self._legs_index = self._load_legs_table()

        people = world.population.get_all_people()
        n_total = len(people)
        n_eligible = 0
        n_routed = 0
        n_legs_written = 0
        multi_leg_journeys = 0

        # The class label we'll look up in the routing table.
        mapped_class = (
            self.class_map.get(self.class_filter, self.class_filter)
            if self.class_filter is not None else None
        )

        for person in people:
            if not self._passes_eligibility(person):
                continue
            n_eligible += 1

            origin = self._derive_key(person, world, self.origin_source)
            dest = self._derive_key(person, world, self.destination_source)

            person_class = self._get_person_class(person)
            mode_class = (
                mapped_class if mapped_class is not None
                else self.class_map.get(person_class, person_class)
            )

            if origin is None or dest is None or mode_class is None:
                self._apply_miss(person)
                continue

            legs = self._legs_index.get((origin, dest, mode_class))
            if not legs:
                self._apply_miss(person)
                continue

            # Place the rider on every leg of the journey.
            leg_count_this_person = 0
            for leg in legs:
                line_id = leg["line_id"]
                venue = self._get_or_create_line_venue(world, line_id, person)
                if venue is None:
                    # Cannot resolve a geo unit for the line — skip the leg.
                    self._stats["legs_skipped_no_geo"] += 1
                    continue
                venue.add_to_subset(
                    person,
                    subset_key=self.leg_subset_key,
                    activity_name=self.activity_map_key,
                    activity_type=self.leg_venue_type,
                )
                subset = venue.subsets[self.leg_subset_key]
                # Per-leg numeric metadata (D11). Keyed by person.id; if a
                # person has two legs on the same line (rare), the second
                # overwrites — warn and count it.
                if self.leg_metadata:
                    if person.id in subset.member_metadata:
                        self._stats["metadata_overwrites"] += 1
                    subset.member_metadata[person.id] = {
                        field: leg[col] for field, col in self.leg_metadata.items()
                    }
                leg_count_this_person += 1
                n_legs_written += 1

            if leg_count_this_person > 0:
                n_routed += 1
                if leg_count_this_person > 1:
                    multi_leg_journeys += 1

        # Summary.
        self._stats["eligible"] = n_eligible
        self._stats["routed"] = n_routed
        self._stats["legs_written"] = n_legs_written
        self._stats["multi_leg_journeys"] = multi_leg_journeys
        self._stats["lines_used"] = len(self._line_to_venue)

        logger.info(f"  Population scanned          : {n_total:,}")
        logger.info(f"  Eligible (after class/req)  : {n_eligible:,}")
        logger.info(f"  Routed (>=1 leg placed)     : {n_routed:,}")
        logger.info(f"  Misses (fallback applied)   : {self._stats['misses']:,}")
        logger.info(f"  Total legs written          : {n_legs_written:,}")
        logger.info(f"  Multi-leg journeys          : {multi_leg_journeys:,}")
        logger.info(f"  Distinct lines materialised : {len(self._line_to_venue):,}")
        if self._stats.get("metadata_overwrites"):
            logger.warning(
                f"  Metadata overwrites (same line, multiple legs): "
                f"{self._stats['metadata_overwrites']:,}"
            )
        if self._stats.get("legs_skipped_no_geo"):
            logger.warning(
                f"  Legs skipped (no geo unit): {self._stats['legs_skipped_no_geo']:,}"
            )

    @classmethod
    def from_yaml(cls, yaml_path: str):
        from . import distributor_from_yaml
        return distributor_from_yaml(yaml_path)
