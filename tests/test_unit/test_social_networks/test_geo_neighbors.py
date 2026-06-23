"""
Regression tests for the lat/lon coordinate-order bug in geo_neighbors.

GeographicalUnit.coordinates is stored as (lat, lon) (see geography.py /
GeographicalUnit docstring). _extract_coordinates must convert this to the
(lon, lat) order that libpysal/cKDTree/_haversine_km expect, not just relabel it.
"""
import pytest

from may.social_networks.builder_functions.geo.geo_neighbors import _extract_coordinates
from may.social_networks.builder_functions.spatial_kernels import _haversine_km

# London and Durham; real great-circle distance is ~376 km.
LONDON_LAT_LON = (51.5074, -0.1278)
DURHAM_LAT_LON = (54.7765, -1.5849)
REAL_DISTANCE_KM = 376.3


class _FakeUnit:
    def __init__(self, id, coordinates):
        self.id = id
        self.coordinates = coordinates


def test_extract_coordinates_swaps_lat_lon_to_lon_lat():
    london = _FakeUnit(1, LONDON_LAT_LON)
    durham = _FakeUnit(2, DURHAM_LAT_LON)

    coordinates, units = _extract_coordinates([london, durham])

    assert units == [london, durham]
    assert coordinates[0].tolist() == [LONDON_LAT_LON[1], LONDON_LAT_LON[0]]
    assert coordinates[1].tolist() == [DURHAM_LAT_LON[1], DURHAM_LAT_LON[0]]


def test_extract_coordinates_feeds_haversine_the_real_distance():
    london = _FakeUnit(1, LONDON_LAT_LON)
    durham = _FakeUnit(2, DURHAM_LAT_LON)

    coordinates, _ = _extract_coordinates([london, durham])
    distance_km = _haversine_km(
        coordinates[0, 0], coordinates[0, 1],
        coordinates[1, 0], coordinates[1, 1],
    )

    assert distance_km == pytest.approx(REAL_DISTANCE_KM, abs=1.0)
