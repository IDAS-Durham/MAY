"""
RouteDistributor pool_rule: legs derived per journey instead of read from a
routing table.

A pool_rule exists for modes whose real topology is unknown or irrelevant, where
the simulator only needs a bounded shared-air contact group. The leg it produces
has to be indistinguishable in shape from a table row, so the rest of allocate()
does not care which source it came from.
"""
import csv
import types

import pytest
import yaml

from may.geography.geography import Geography
from may.venue_distributor.route_distributor import RouteDistributor

LEVELS = ["SGU", "MGU", "LGU"]

# Two LGUs. Within Ayr, M1 and M2 are ~11 km apart. Across to Bute, M3 is ~56 km
# from M1, past the 50 km cut-off; M2 to M3 is ~45 km, inside it. That lets one
# fixture cover the local pool, the corridor pool, and the range cut-off.
COORDS = {
    "M1": (55.00, -4.00),
    "M2": (55.10, -4.00),
    "M3": (55.50, -4.00),
}
LGU_OF = {"M1": "Ayr, City of", "M2": "Ayr, City of", "M3": "Bute"}


def _write_csv(path, rows):
    # Real LGU names contain commas ("Bristol, City of"), so quote properly
    # rather than joining on commas.
    with path.open("w", newline="") as fh:
        csv.writer(fh).writerows(rows)


@pytest.fixture
def world(tmp_path):
    d = tmp_path / "geography"
    d.mkdir()
    _write_csv(d / "hierarchy.csv",
               [("SGU", "MGU", "LGU")] +
               [(f"S{m}", m, LGU_OF[m]) for m in COORDS])
    _write_csv(d / "coord_mgu.csv",
               [("MGU", "latitude", "longitude")] +
               [(m, lat, lon) for m, (lat, lon) in COORDS.items()])

    geo = Geography(data_dir=str(d), levels=LEVELS,
                    hierarchy_file="hierarchy.csv",
                    coord_files={"MGU": "coord_mgu.csv"})
    geo.load_from_csv()
    return types.SimpleNamespace(geography=geo)


@pytest.fixture
def pool_config(tmp_path):
    cfg = {
        "distributor_type": "route",
        "distributor_name": "test_pool",
        "leg_venue_type": "bus_line",
        "leg_subset_key": "rider",
        "class_source": "properties.commute_mode",
        "class_filter": "bus",
        "require_properties": ["commute_mode"],
        "pool_rule": {
            "pool_id_prefix": "bus_pool",
            "corridor_level": "LGU",
            "max_distance_km": 50,
            "speed_kmh": 30,
            "min_duration_min": 5,
            "max_duration_min": 60,
        },
        "leg_metadata": {"t_board_min": "t_board_min",
                         "t_alight_min": "t_alight_min"},
    }
    p = tmp_path / "pool.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


@pytest.fixture
def dist(pool_config):
    return RouteDistributor(config_file=str(pool_config))


def test_journey_inside_one_lgu_uses_an_origin_keyed_pool(dist, world):
    """Local service: everyone boarding in the same MGU rides together,
    regardless of where they alight."""
    to_m2 = dist._pool_legs(world.geography, "M1", "M2")
    to_m1 = dist._pool_legs(world.geography, "M1", "M1")

    assert to_m2[0]["line_id"] == "bus_pool_M1"
    assert to_m1[0]["line_id"] == "bus_pool_M1"


def test_journey_across_lgus_uses_a_corridor_pool(dist, world):
    """Commute corridor: keyed on the ordered LGU pair, not the MGU endpoints."""
    legs = dist._pool_legs(world.geography, "M2", "M3")

    assert legs[0]["line_id"] == "bus_pool_lgu_ayr_city_of__bute"


def test_corridor_pool_is_directional(dist, world):
    """Outbound and return are different pools: a morning corridor carries a
    different set of people from the evening one."""
    out = dist._pool_legs(world.geography, "M2", "M3")[0]["line_id"]
    back = dist._pool_legs(world.geography, "M3", "M2")[0]["line_id"]

    assert out != back
    assert back == "bus_pool_lgu_bute__ayr_city_of"


def test_journeys_beyond_max_distance_are_misses(dist, world):
    """Nobody commutes 56 km by bus daily. No legs means the caller applies
    on_miss, exactly as an absent routing-table row would."""
    assert dist._pool_legs(world.geography, "M1", "M3") is None


def test_leg_has_the_same_shape_as_a_routing_table_row(dist, world):
    """allocate() reads these keys off table rows too, so a pool leg must carry
    all of them or the shared code path breaks."""
    leg = dist._pool_legs(world.geography, "M1", "M2")[0]

    assert set(leg) == {"leg_idx", "line_id", "board_mgu", "alight_mgu",
                        "t_board_min", "t_alight_min"}
    assert leg["leg_idx"] == 0
    assert leg["board_mgu"] == "M1"
    assert leg["alight_mgu"] == "M2"
    assert leg["t_board_min"] == 0


def test_duration_tracks_distance_between_the_floor_and_the_ceiling(dist, world):
    """~11 km at 30 km/h is ~22 minutes, so this exercises the calculation
    rather than either clamp."""
    minutes = dist._pool_legs(world.geography, "M1", "M2")[0]["t_alight_min"]

    assert 20 <= minutes <= 24


def test_same_unit_journey_gets_the_floor_duration(dist, world):
    """Zero centroid distance still has to be a real ride, not an instant one."""
    assert dist._pool_legs(world.geography, "M1", "M1")[0]["t_alight_min"] == 5


def test_missing_coordinates_fail_loudly(dist, world, tmp_path):
    """A pool_rule derives time from centroids, so an uncovered unit is
    incomplete data, not a routing miss to be swallowed."""
    world.geography.get_unit("M2").coordinates = None

    with pytest.raises(ValueError, match="no coordinates"):
        dist._pool_legs(world.geography, "M1", "M2")


def test_pool_rule_does_not_load_a_legs_table(dist):
    """The point of the rule is that there is no table to read."""
    assert dist.legs_table_path is None


# --- catchment ------------------------------------------------------------
# Without a catchment a rider only routes when both endpoints are an MGU that
# physically contains a stop. M1 and M3 host stops; M2 does not, though it sits
# ~11 km from M1.

@pytest.fixture
def catchment_dist(tmp_path):
    cfg = {
        "distributor_type": "route",
        "distributor_name": "test_catchment",
        "leg_venue_type": "train_line",
        "leg_subset_key": "rider",
        "class_source": "properties.commute_mode",
        "class_filter": "train",
        "require_properties": ["commute_mode"],
        "catchment": {"max_access_km": 15, "access_speed_kmh": 30},
        "leg_metadata": {"t_board_min": "t_board_min"},
    }
    p = tmp_path / "catch.yaml"
    p.write_text(yaml.safe_dump(cfg))
    d = RouteDistributor(config_file=str(p))
    # A table serving only M1 <-> M3.
    leg = {"leg_idx": 0, "line_id": "L1", "board_mgu": "M1",
           "alight_mgu": "M3", "t_board_min": 0, "t_alight_min": 20}
    d._legs_index = {("M1", "M3", "train"): [leg], ("M3", "M1", "train"): [leg]}
    return d


def test_catchment_routes_a_rider_whose_own_mgu_has_no_stop(catchment_dist, world):
    """M2 hosts no stop, but M1 is ~11 km away and does. Today this rider is a
    miss purely because of where the MGU boundary falls."""
    catchment_dist._build_catchment(world.geography)

    legs, extra = catchment_dist._legs_for(world.geography, "M2", "M3", "train")

    assert legs is not None
    assert legs[0]["board_mgu"] == "M1"
    assert extra["access_min"] > 0


def test_catchment_records_access_and_egress_time(catchment_dist, world):
    """~11 km at 30 km/h is ~22 min to reach the station; the destination hosts
    its own stop, so egress is zero."""
    catchment_dist._build_catchment(world.geography)

    _, extra = catchment_dist._legs_for(world.geography, "M2", "M3", "train")

    assert 20 <= extra["access_min"] <= 24
    assert extra["egress_min"] == 0


def test_no_stop_within_range_is_still_a_miss(catchment_dist, world):
    """A catchment widens coverage; it must not invent a service. With the
    radius cut below the distance to any stop, the rider drives."""
    catchment_dist.max_access_km = 1
    catchment_dist._build_catchment(world.geography)

    legs, _ = catchment_dist._legs_for(world.geography, "M2", "M3", "train")

    assert legs is None
    assert catchment_dist._stats["misses_no_station_in_range"] == 1


def test_both_ends_snapping_to_one_stop_is_a_miss(catchment_dist, world):
    """M1 and M2 both snap to M1, so there is no ride to take. Boarding and
    immediately alighting at the same stop is not a journey."""
    catchment_dist._build_catchment(world.geography)

    legs, _ = catchment_dist._legs_for(world.geography, "M1", "M2", "train")

    assert legs is None
    assert catchment_dist._stats["misses_same_station"] == 1


def test_served_set_comes_from_the_table_not_a_data_file(catchment_dist, world):
    """The routing table already says which MGUs it serves, so no second source
    can drift out of step with it."""
    catchment_dist._build_catchment(world.geography)

    assert catchment_dist._served_names == ["M1", "M3"]


def test_snap_is_cached_per_mgu(catchment_dist, world):
    """Riders share origins, so the scan must happen once per MGU, not per
    person."""
    catchment_dist._build_catchment(world.geography)

    catchment_dist._legs_for(world.geography, "M2", "M3", "train")
    catchment_dist._legs_for(world.geography, "M2", "M3", "train")

    assert set(catchment_dist._catchment_cache) == {"M2", "M3"}


def test_journey_fields_are_present_without_a_catchment(dist, world):
    """One metadata schema across all commute distributors: a pool rider still
    reports access/egress, as zero."""
    _, extra = dist._legs_for(world.geography, "M1", "M2", "bus")

    assert extra == {"access_min": 0.0, "egress_min": 0.0}


def test_rail_is_refused_when_reaching_the_stations_costs_more_than_going_direct(
        tmp_path, catchment_dist):
    """Two MGUs 200 m apart, sitting midway between the only two stations, each
    snapping to a different one. Riding would mean ~55 min of access to cover
    200 m. A wide catchment must not put someone on a train to go nowhere."""
    d = tmp_path / "geo2"
    d.mkdir()
    coords = {"M1": 55.000, "M3": 55.500, "M5": 55.249, "M6": 55.251}
    _write_csv(d / "hierarchy.csv",
               [("SGU", "MGU", "LGU")] + [(f"S{m}", m, "Ayr") for m in coords])
    _write_csv(d / "coord_mgu.csv",
               [("MGU", "latitude", "longitude")] + [(m, la, -4.0) for m, la in coords.items()])
    geo = Geography(data_dir=str(d), levels=LEVELS, hierarchy_file="hierarchy.csv",
                    coord_files={"MGU": "coord_mgu.csv"})
    geo.load_from_csv()
    world2 = types.SimpleNamespace(geography=geo)

    catchment_dist.max_access_km = 30      # wide enough to reach either station
    catchment_dist._build_catchment(world2.geography)

    legs, _ = catchment_dist._legs_for(world2.geography, "M5", "M6", "train")

    assert legs is None
    assert catchment_dist._stats["misses_access_exceeds_direct"] == 1
