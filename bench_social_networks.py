import time
import numpy as np

from may.geography import Geography, GeographicalUnit
from may.population import Person
from may.social_networks import build_local_social_network, build_spatial_social_network

# =============================================================================
# CONFIGURATION — edit these to change what is benchmarked
# =============================================================================

# Each tuple: (total_people, n_geo_units)
SCENARIOS = [
    (  5_000,   100),
    ( 20_000,  500),
    ( 50_000,  2500),
    (100_000,  5000),
    (1_000_000,  20000),
    (10_000_000,  200000),        
]

# Spatial networks to benchmark for each scenario
SPATIAL_NETWORKS = [
    dict(label='near [0.01–15 km]',  min_radius_km=0.01,  max_radius_km=15,
         mean_connections_per_person=6, clustering_level=0.6),
    dict(label='far  [10–30 km]', min_radius_km=10, max_radius_km=30,
         mean_connections_per_person=6, clustering_level=0.6),
]

# Local (intra-SGU) network
LOCAL_NETWORK = dict(mean_connections_per_person=6, clustering_level=0.6)

# Bounding box for synthetic coordinates (England-like)
LAT_MIN, LAT_MAX = 50.0, 55.5
LON_MIN, LON_MAX = -5.5,  1.5

RANDOM_SEED = 42
# =============================================================================


def make_world(n_people: int, n_geo_units: int, rng) -> Geography:
    Person.reset_counter()
    geography = Geography()
    geography.levels = ['SGU']

    lats = rng.uniform(LAT_MIN, LAT_MAX, n_geo_units)
    lons = rng.uniform(LON_MIN, LON_MAX, n_geo_units)

    for i in range(n_geo_units):
        unit = GeographicalUnit(id=i, name=f'SGU_{i:05d}', level='SGU',
                                coordinates=(lats[i], lons[i]))
        geography.add_geo_unit(unit)

    units = list(geography.get_units_by_level('SGU').values())
    for p_idx in range(n_people):
        unit = units[p_idx % n_geo_units]
        person = Person(age=30, sex='male', geographical_unit=unit)
        person.activity_map['residence'] = {'household': [f'stub_{p_idx}']}
        unit.add_person(person)

    return geography


def _avg_degree(geography, storage_key, sample=100):
    units = list(geography.get_units_by_level('SGU').values())
    people = list(units[0].people)[:sample]
    if not people:
        return 0.0
    return sum(len(p.properties.get(storage_key, [])) for p in people) / len(people)


def run_benchmark():
    rng = np.random.default_rng(RANDOM_SEED)

    print(f"\n{'Scenario':<32} {'Network':<22} {'Time (s)':>10} {'Avg deg':>8}")
    print('-' * 76)

    for n_people, n_geo_units in SCENARIOS:
        label = f'{n_people:,} people / {n_geo_units} units'

        # Local network
        geography = make_world(n_people, n_geo_units, rng)
        t0 = time.perf_counter()
        build_local_social_network(geography, **LOCAL_NETWORK,
                                   storage_key='bench_local')
        elapsed = time.perf_counter() - t0
        avg = _avg_degree(geography, 'bench_local')
        print(f'{label:<32} {"local (intra-SGU)":<22} {elapsed:>10.3f} {avg:>8.1f}')

        # Spatial networks
        for net in SPATIAL_NETWORKS:
            geography = make_world(n_people, n_geo_units, rng)
            key = f'bench_{net["label"]}'
            kw = {k: v for k, v in net.items() if k != 'label'}
            t0 = time.perf_counter()
            build_spatial_social_network(geography, **kw, storage_key=key,
                                         assign_activity_map=True)
            elapsed = time.perf_counter() - t0
            avg = _avg_degree(geography, key)
            print(f'{"":32} {net["label"]:<22} {elapsed:>10.3f} {avg:>8.1f}')

        print()


if __name__ == '__main__':
    run_benchmark()
