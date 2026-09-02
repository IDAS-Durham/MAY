"""
RouteDistributor, a generic route-table-driven distributor.

Turns an `(origin_key, dest_key, class)` triple per person into an ordered list
of leg venues with per-leg numeric metadata. Configuration controls everything
domain-specific (which person attributes feed the keys, which CSV holds the
routes, which venue type and subset receive each leg, which leg columns become
per-membership metadata, what to do on a miss).

Commute is one instance of this distributor; future use-cases (school buses,
freight routes, ferries) plug in by writing a new YAML config, with no code change.

Besides the config-mapped leg columns, every leg membership carries five
structural fields: ``leg_idx`` (the journey sequence, stored explicitly
because leg timings are line-relative), ``origin_unit_id`` / ``dest_unit_id``
(the journey endpoints the router itself derived, as geo unit ids) and
``board_unit_id`` / ``alight_unit_id`` (this leg's stops). They are routing
facts the router derives, so what "origin" means is still whatever
origin_source/destination_source the config defined.
"""

import logging
import re
from collections import Counter, defaultdict
from math import ceil
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd

from .base_distributor import BaseDistributor
from may.utils.attribute_access import get_attribute

logger = logging.getLogger("route_distributor")


def _slug(name: str) -> str:
    """Unit names carry spaces and punctuation ('Bristol, City of'). Squash to
    lowercase alnum + underscore so a derived line_id stays log-friendly."""
    return re.sub(r"[^0-9A-Za-z]+", "_", str(name)).strip("_").lower() or "unit"


class RouteDistributor(BaseDistributor):
    """Generic route-table-driven distributor (see module docstring)."""

    def __init__(self, config_file: str = None, config_dict: Dict = None):
        super().__init__(config_file, config_dict)

        c = self.config
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

        # on_miss: { set: { property_name: value } } overwrites a person
        # property when the routing table has no entry for their key.
        self.on_miss = c.get("on_miss", {}) or {}
        self.on_miss_set = self.on_miss.get("set", {}) or {}

        # Eligibility: a list of property names the person MUST have set
        # (typically ['commute_mode']).
        self.require_properties = c.get("require_properties", [])

        # Where a journey's legs come from. Exactly one of two sources:
        #
        #   legs_table  a precomputed routing table, for modes whose network is
        #               real and irregular enough that it has to be measured
        #               (rail, tube).
        #   pool_rule   a rule that derives one shared pool per journey, for
        #               modes where the topology is unknown or irrelevant and
        #               all the simulator needs is a bounded shared-air contact
        #               group. Nothing is stored, because nothing is measured:
        #               the pool identity and duration are pure functions of the
        #               journey's endpoints.
        self.pool_rule = c.get("pool_rule") or None

        # Station catchment. Without it, a journey only routes when the rider
        # both lives and works in an MGU that physically contains a stop, which
        # is 22% of MGUs for train and 4% for tube, so most riders miss for a
        # reason that is an artefact of where MGU boundaries fall. With it, each
        # endpoint snaps to the nearest MGU the table actually serves, and a miss
        # means no stop lies within reach.
        self.catchment = c.get("catchment") or None
        if self.catchment is not None:
            self.max_access_km = float(self.catchment["max_access_km"])
            self.access_speed_kmh = float(self.catchment["access_speed_kmh"])
        self._catchment_cache = {}   # mgu name -> (served_mgu, access_min) | None
        self._served_names: List[str] = []
        self._served_coords = None

        self.legs_table_path = None
        if self.pool_rule is None:
            self.legs_table_path = self._resolve_path(
                c.get("legs_table", "data/activities/commute/route_legs.csv")
            )

        if self.pool_rule is not None:
            pr_cfg = self.pool_rule
            self.pool_id_prefix = pr_cfg.get("pool_id_prefix", "pool")
            self.pool_corridor_level = pr_cfg.get("corridor_level")
            self.pool_max_distance_km = float(pr_cfg.get("max_distance_km", 0)) or None
            self.pool_speed_kmh = float(pr_cfg["speed_kmh"])
            self.pool_min_duration = int(pr_cfg["min_duration_min"])
            self.pool_max_duration = int(pr_cfg["max_duration_min"])

        # Lazy state, populated in allocate()
        self._prepared = False       # routing table loaded + catchment indexed
        self._legs_index = None      # (origin, dest, mode_class) -> [leg dicts]
        self._line_to_venue = {}     # line_id -> Venue (lazy cache)
        self._unit_id_cache = {}     # geo-unit name -> unit id (or -1)
        self._stats = Counter()

        logger.info(
            "Initialized RouteDistributor "
            f"(class_filter={self.class_filter!r}, leg_venue_type={self.leg_venue_type!r})"
        )

    # ---------------------------------------------------------------- helpers
    def _resolve_path(self, p: str) -> str:
        from may.utils import path_resolver as pr
        resolved = pr.resolve(p)
        path = Path(resolved)
        if path.is_absolute() or path.exists():
            return str(path)
        # configs/2021/distributors/foo.yaml -> project root = parent.parent.parent
        if self.config_path is not None:
            project_root = self.config_path.parent.parent.parent
            candidate = project_root / resolved
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
        # class_filter, which keeps memory bounded on huge national tables.
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

    # ------------------------------------------------------------- pool rule
    def _ancestor_name(self, geography, unit_name: str, level: str) -> Optional[str]:
        unit = geography.get_unit(unit_name)
        if unit is None:
            return None
        if unit.level != level:
            unit = unit.get_ancestor_by_level(level)
        return None if unit is None else unit.name

    def _coords(self, geography, unit_name: str):
        unit = geography.get_unit(unit_name)
        if unit is None or unit.coordinates is None:
            raise ValueError(
                f"RouteDistributor: no coordinates for unit {unit_name!r}. "
                f"A pool_rule derives travel time from unit centroids, so the "
                f"geography's coord_files must cover every routed level."
            )
        return unit.coordinates

    def _distance_km(self, geography, a: str, b: str) -> float:
        """Great-circle km between two units' centroids."""
        if a == b:
            return 0.0
        return self._haversine_distance(self._coords(geography, a), self._coords(geography, b))

    def _build_catchment(self, geography) -> None:
        """Index the MGUs the routing table actually serves, from the table."""
        served = ({k[0] for k in self._legs_index} | {k[1] for k in self._legs_index})
        names, coords = [], []
        for name in sorted(served):
            unit = geography.get_unit(name)
            if unit is not None and unit.coordinates is not None:
                names.append(name)
                coords.append(tuple(unit.coordinates))
        self._served_names = names
        self._served_coords = np.array(coords) if coords else None
        logger.info(
            f"  Catchment: {len(names):,} served MGUs in loaded geography, "
            f"max access {self.max_access_km} km at {self.access_speed_kmh} km/h"
        )

    def _snap(self, geography, name: str):
        """Nearest served MGU within the access radius, or None. Cached per MGU
        because riders share origins: at most one scan per MGU, not per person."""
        if name in self._catchment_cache:
            return self._catchment_cache[name]
        result = None
        unit = geography.get_unit(name)
        if unit is not None and unit.coordinates is not None and self._served_coords is not None:
            d = self._haversine_distance_vectorized(
                tuple(unit.coordinates), self._served_coords)
            i = int(d.argmin())
            if d[i] <= self.max_access_km:
                result = (self._served_names[i], d[i] / self.access_speed_kmh * 60.0)
        self._catchment_cache[name] = result
        return result

    def _pool_legs(self, geography, origin: str, dest: str) -> Optional[List[Dict[str, Any]]]:
        """Derive this journey's single shared-pool leg, or None if out of range.

        Riders travelling between the same pair of corridor-level units share a
        pool, so contacts concentrate the way they do on a real service. A
        journey that stays inside one corridor unit instead shares a pool keyed
        on its origin alone, which is the local-service case: people boarding at
        the same place ride together regardless of where they get off.
        """
        dist_km = self._distance_km(geography, origin, dest)
        if self.pool_max_distance_km is not None and dist_km > self.pool_max_distance_km:
            # Too far to be a plausible daily journey by this mode.
            return None

        line_id = f"{self.pool_id_prefix}_{origin}"
        if self.pool_corridor_level is not None:
            o_unit = self._ancestor_name(geography, origin, self.pool_corridor_level)
            d_unit = self._ancestor_name(geography, dest, self.pool_corridor_level)
            if o_unit is None or d_unit is None:
                return None
            if o_unit != d_unit:
                line_id = (f"{self.pool_id_prefix}_{self.pool_corridor_level.lower()}_"
                           f"{_slug(o_unit)}__{_slug(d_unit)}")

        minutes = dist_km / self.pool_speed_kmh * 60.0
        duration = max(self.pool_min_duration,
                       min(self.pool_max_duration, int(ceil(minutes))))
        return [{
            "leg_idx": 0,
            "line_id": line_id,
            "board_mgu": origin,
            "alight_mgu": dest,
            "t_board_min": 0,
            "t_alight_min": duration,
        }]

    def _legs_for(self, geography, origin: str, dest: str, mode_class: str,
                  count_misses: bool = True):
        """(legs, journey_fields) from whichever source the config configured.

        journey_fields are per-journey facts recorded on every leg, alongside
        origin/dest unit ids. Always the same keys so one export carries one
        metadata schema.
        """
        no_access = {"access_min": 0.0, "egress_min": 0.0}
        if self.pool_rule is not None:
            return self._pool_legs(geography, origin, dest), no_access
        if self.catchment is None:
            return self._legs_index.get((origin, dest, mode_class)), no_access

        o = self._snap(geography, origin)
        d = self._snap(geography, dest)
        if o is None or d is None:
            if count_misses:
                self._stats["misses_no_station_in_range"] += 1
            return None, no_access
        if o[0] == d[0]:
            # Both ends reach the same stop, so there is no ride to take. Real
            # miss: they walk or drive rather than board and immediately alight.
            if count_misses:
                self._stats["misses_same_station"] += 1
            return None, no_access
        # A wide catchment can otherwise put someone on a train for a trip whose
        # station legs cost more than going straight there. Nobody does that.
        access = o[1] + d[1]
        if access > self._distance_km(geography, origin, dest) / self.access_speed_kmh * 60.0:
            if count_misses:
                self._stats["misses_access_exceeds_direct"] += 1
            return None, no_access
        return (self._legs_index.get((o[0], d[0], mode_class)),
                {"access_min": round(o[1], 1), "egress_min": round(d[1], 1)})

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

        val = get_attribute(person, frm, nested_properties=False)
        if val is None:
            return None
        if stype == "property":
            return str(val)
        unit = world.geography.get_unit(val) if frm.startswith("properties.") else val

        if unit is None:
            return None
        if stype == "ancestor":
            level = source.get("level")
            if level and unit.level != level:
                unit = unit.get_ancestor_by_level(level)
            if unit is None:
                return None
            return unit.name
        return get_attribute(unit, "name")

    def _unit_id_for(self, world, name) -> int:
        """Geo unit id for a unit-name key, or -1 when the name doesn't resolve
        in this world (e.g. a leg boards in an MGU outside the loaded
        geography). Cached, because route tables reuse a small set of unit names.
        Unit ids serialise verbatim (geography/ids = unit.id), so the stored
        value joins directly against the exported world."""
        if name is None or (isinstance(name, float) and pd.isna(name)):
            return -1
        cached = self._unit_id_cache.get(name)
        if cached is None:
            unit = world.geography.get_unit(name)
            cached = int(unit.id) if unit is not None else -1
            self._unit_id_cache[name] = cached
        return cached

    def _get_person_class(self, person) -> Optional[str]:
        return get_attribute(person, self.class_source, nested_properties=False)

    def _get_or_create_line_venue(self, world, line_id: str, person) -> Optional[Any]:
        """Lazily materialise one venue per line_id. Returns None if no MGU
        can be resolved (shouldn't happen, since the rider's residence MGU is always
        loaded)."""
        venue = self._line_to_venue.get(line_id)
        if venue is not None:
            return venue
        # Attach the line venue to the rider's residence MGU. This MGU is
        # guaranteed loaded (the rider lives there) and gives the venue a
        # stable, deterministic location for HDF5 partitioning.
        mgu_level = world.geography.levels[1]  # batch-partition level
        geo_unit = get_attribute(person, "geographical_unit")
        if geo_unit is not None and geo_unit.level != mgu_level:
            geo_unit = geo_unit.get_ancestor_by_level(mgu_level)
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
        # debug dumps and any future external joins work cleanly. Lookup goes
        # through our own cache.
        venue.name = line_id
        self._line_to_venue[line_id] = venue
        return venue

    def _apply_miss(self, person) -> None:
        for prop, val in self.on_miss_set.items():
            person.properties[prop] = val
        self._stats["misses"] += 1

    def _passes_eligibility(self, person) -> bool:
        props = get_attribute(person, "properties", {})
        for prop in self.require_properties:
            if prop not in props or props[prop] is None:
                return False
        if self.class_filter is not None:
            if self._get_person_class(person) != self.class_filter:
                return False
        return True

    # -------------------------------------------------------------- main API
    def prepare(self, geography) -> None:
        """Load the routing table and index its catchment. Idempotent.

        Split out of allocate() so a feasibility query can use the same routing
        state the allocation will, without having to allocate anything.
        """
        if self._prepared:
            return
        # Load routes once. A pool_rule derives its legs per journey instead.
        if self.pool_rule is None:
            if self._legs_index is None:
                self._legs_index = self._load_legs_table()
            if self.catchment is not None:
                self._build_catchment(geography)
        else:
            logger.info(
                f"  Deriving legs from pool_rule (prefix={self.pool_id_prefix!r}, "
                f"corridor_level={self.pool_corridor_level!r}, "
                f"max {self.pool_max_distance_km} km at {self.pool_speed_kmh} km/h)"
            )
        self._prepared = True

    def allocate(self, world) -> None:
        logger.info("=" * 60)
        logger.info("RouteDistributor")
        logger.info("=" * 60)

        self.prepare(world.geography)

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

            legs, journey_fields = self._legs_for(world.geography, origin, dest, mode_class)
            if not legs:
                self._apply_miss(person)
                continue

            # The journey's endpoints as geo unit ids. The keys were derived to
            # route this person; persisting them lets consumers reconstruct
            # origin→destination straight from the stored ids. The source
            # attributes stay config-defined, so these fields carry whatever
            # semantics the world's distributor configs chose (home→work today,
            # work→cinema tomorrow).
            origin_unit_id = self._unit_id_for(world, origin)
            dest_unit_id = self._unit_id_for(world, dest)

            # Place the rider on every leg of the journey.
            leg_count_this_person = 0
            for leg in legs:
                line_id = leg["line_id"]
                venue = self._get_or_create_line_venue(world, line_id, person)
                if venue is None:
                    # Cannot resolve a geo unit for the line, so skip the leg.
                    self._stats["legs_skipped_no_geo"] += 1
                    continue
                venue.add_to_subset(
                    person,
                    subset_key=self.leg_subset_key,
                    activity_name=self.activity_map_key,
                    activity_type=self.leg_venue_type,
                )
                subset = venue.subsets[self.leg_subset_key]
                # Per-leg numeric metadata. Keyed by person.id; if a
                # person has two legs on the same line (rare), the second
                # overwrites, so warn and count it. Alongside the config-mapped
                # columns, every leg row carries the structural routing fields:
                # journey origin/dest plus this leg's board/alight unit ids
                # (-1 when a unit lies outside the loaded geography).
                if person.id in subset.member_metadata:
                    self._stats["metadata_overwrites"] += 1
                row = {field: leg[col] for field, col in self.leg_metadata.items()}
                # The route table's journey sequence. Persisted because it is
                # the only source of ordering: t_board/t_alight are line-relative
                # offsets, so sorting by them misorders interchange journeys.
                row["leg_idx"] = int(leg["leg_idx"])
                row["origin_unit_id"] = origin_unit_id
                row["dest_unit_id"] = dest_unit_id
                row["board_unit_id"] = self._unit_id_for(world, leg["board_mgu"])
                row["alight_unit_id"] = self._unit_id_for(world, leg["alight_mgu"])
                # Access/egress are journey-level, like origin/dest above: the
                # rider's own MGU is origin_unit_id, the stop they reach is
                # board_unit_id, and this is how long getting between them takes.
                row.update(journey_fields)
                subset.member_metadata[person.id] = row
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
        if self.catchment is not None:
            logger.info(
                f"  Miss reasons: no stop within {self.max_access_km} km "
                f"{self._stats['misses_no_station_in_range']:,}, "
                f"same stop both ends {self._stats['misses_same_station']:,}, "
                f"quicker to go direct {self._stats['misses_access_exceeds_direct']:,}, "
                f"no route between stops "
                f"{self._stats['misses'] - self._stats['misses_no_station_in_range'] - self._stats['misses_same_station'] - self._stats['misses_access_exceeds_direct']:,}"
            )
        if self._stats.get("legs_skipped_no_geo"):
            logger.warning(
                f"  Legs skipped (no geo unit): {self._stats['legs_skipped_no_geo']:,}"
            )
