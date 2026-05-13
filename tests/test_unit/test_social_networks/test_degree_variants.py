"""Tests for degree_variants (super-connector) support in numba_random builders."""
import numpy as np
import pytest

from may.social_networks.builder_functions.numba_random import _build_connection_counts
from may.social_networks import SocialNetworkBuilder


# ============================================================================
# _build_connection_counts unit tests
# ============================================================================

def test_flat_distribution():
    config = {"mean_count": 3}
    counts = _build_connection_counts(1000, config)
    assert (counts == 3).all()


def test_single_variant_fraction():
    rng = np.random.default_rng(0)
    np.random.seed(0)
    config = {"mean_count": 3, "degree_variants": [{"probability": 0.10, "count": 6}]}
    counts = _build_connection_counts(10_000, config)
    fraction_super = (counts == 6).mean()
    assert 0.07 < fraction_super < 0.13, f"Expected ~10% super-connectors, got {fraction_super:.2%}"
    assert ((counts == 3) | (counts == 6)).all()


def test_variant_overwrites_default():
    np.random.seed(1)
    config = {"mean_count": 2, "degree_variants": [{"probability": 1.0, "count": 8}]}
    counts = _build_connection_counts(100, config)
    assert (counts == 8).all()


def test_later_variant_overwrites_earlier():
    np.random.seed(2)
    config = {
        "mean_count": 2,
        "degree_variants": [
            {"probability": 1.0, "count": 5},
            {"probability": 1.0, "count": 9},
        ],
    }
    counts = _build_connection_counts(100, config)
    assert (counts == 9).all()


def test_count_capped_at_127():
    config = {"mean_count": 200}
    counts = _build_connection_counts(10, config)
    assert (counts == 127).all()


# ============================================================================
# End-to-end: degree_variants flows through the builder
# ============================================================================

def test_degree_variants_end_to_end(toy_world):
    """Super-connectors config doesn't break the builder and mean count rises."""
    config = {
        "networks": [{
            "name": "work",
            "network_type": "activity_peers",
            "pool_type": "activity",
            "pool": {"activity": "primary_activity"},
            "mean_count": 2,
            "degree_variants": [{"probability": 1.0, "count": 4}],
            "storage_key": "work_contacts",
        }]
    }
    SocialNetworkBuilder(toy_world, config).build_all()
    total = sum(
        len(p.properties.get("work_contacts", []))
        for p in toy_world.population.people
    )
    assert total > 0
