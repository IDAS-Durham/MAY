"""Unit tests for MultiVenueDistributor's per-person venue draws.

`consider_by: geo_unit` exists because `consider_by: count` hands every person
in a geo unit the same N venues: a person carries no position finer than their
unit, so all of them resolve to the same nearest N. On one real geo unit that
put 133,230 people through 27 of the 612 leisure venues that exist there.

The draw these tests cover has to satisfy three things at once: each person gets
their own set, the sets are distinct within a person, and no pool index is
favoured over another. The third is the one that failed first - deduplicating a
row after sorting it keeps whichever duplicates sort lowest, which is a bias
toward low indices rather than a sample.
"""

import numpy as np
import pytest

from may.venue_distributor.multi_venue_distributor import MultiVenueDistributor


def _sampler():
    """A distributor built only far enough to reach _sample_option_sets."""
    return MultiVenueDistributor(config_dict={
        "activity_map_key": "leisure",
        "venue_types": ["cafe"],
        "venue_selection": {"consider_by": "geo_unit", "venue_geo_level": "SGU"},
        "allocation": {"strategy": "random"},
    })


class TestOptionSetDraw:

    def test_pool_no_larger_than_count_gives_everyone_everything(self):
        """Below the requested count there is nothing to choose between."""
        assert _sampler()._sample_option_sets(5, None, 100, 5) is None
        assert _sampler()._sample_option_sets(3, None, 100, 5) is None

    def test_each_person_gets_count_distinct_venues(self):
        picked, valid = _sampler()._sample_option_sets(450, None, 5000, 5)

        assert picked.shape == (5000, 5)
        assert valid.all(), "a pool 90x the count should never leave a person short"
        for row in picked:
            assert len(set(row.tolist())) == 5

    def test_uniform_draw_does_not_favour_low_pool_indices(self):
        """The regression: dedupe must preserve draw order, not sort order.

        Sorting each row and keeping its first distinct entries returned the
        smallest indices drawn, which concentrated people on the venues that
        happened to sit early in the pool.
        """
        pool_size, people, count = 450, 60_000, 5
        picked, valid = _sampler()._sample_option_sets(pool_size, None, people, count)

        counts = np.bincount(picked[valid], minlength=pool_size)
        assert (counts > 0).all(), "every venue in the pool should be reachable"

        expected = people * count / pool_size
        # Poisson-ish spread; a sort-order bias put the extremes orders of
        # magnitude apart rather than within a few percent.
        assert counts.min() > expected * 0.8
        assert counts.max() < expected * 1.2

        first_half = counts[: pool_size // 2].mean()
        second_half = counts[pool_size // 2:].mean()
        assert abs(first_half - second_half) < expected * 0.05

    def test_weights_bias_the_draw_without_starving_the_pool(self):
        """closest_balanced weighting is monotone in weight, not exclusive."""
        pool_size, people, count = 200, 40_000, 5
        weights = 1.0 / (np.linspace(0.5, 25.0, pool_size) + 0.1)

        picked, valid = _sampler()._sample_option_sets(pool_size, weights, people, count)
        counts = np.bincount(picked[valid], minlength=pool_size)

        assert (counts > 0).all(), "a low weight is not a zero weight"
        assert counts[0] > counts[-1] * 5, "nearest should clearly outdraw farthest"
        # Rank correlation with weight, without pulling in scipy.
        assert np.corrcoef(np.argsort(np.argsort(weights)),
                           np.argsort(np.argsort(counts)))[0, 1] > 0.9

    def test_people_draw_independently(self):
        """Two people in the same unit share a distribution, not a result."""
        picked, _ = _sampler()._sample_option_sets(450, None, 2000, 5)
        as_sets = {tuple(sorted(row.tolist())) for row in picked}
        assert len(as_sets) > 1900, "draws should almost never coincide"


class TestConfigSurface:

    def test_geo_unit_pool_requires_a_strategy(self):
        with pytest.raises(ValueError, match="requires"):
            MultiVenueDistributor(config_dict={
                "activity_map_key": "leisure",
                "venue_types": ["cafe"],
                "venue_selection": {"consider_by": "geo_unit"},
            })

    def test_strategy_without_geo_unit_pool_is_refused(self):
        """A strategy the count path would ignore is an error, not a no-op."""
        with pytest.raises(ValueError, match="applies only when"):
            MultiVenueDistributor(config_dict={
                "activity_map_key": "leisure",
                "venue_types": ["cafe"],
                "venue_selection": {"consider_by": "count"},
                "allocation": {"strategy": "random"},
            })

    def test_unknown_consider_by_is_refused(self):
        with pytest.raises(ValueError, match="consider_by"):
            MultiVenueDistributor(config_dict={
                "activity_map_key": "leisure",
                "venue_types": ["cafe"],
                "venue_selection": {"consider_by": "nearest_ish"},
            })

    def test_count_remains_the_default(self):
        """Scenarios that never named consider_by keep the behaviour they had."""
        d = MultiVenueDistributor(config_dict={
            "activity_map_key": "leisure",
            "venue_types": ["cafe"],
        })
        assert d.consider_by == "count"
        assert d.selection_strategy is None
