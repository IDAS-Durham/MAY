"""
Probability gates: stacked multi-file loading, the retired `default` key, and
the requirement that a geography-keyed table cover every loaded SGU.
"""
import copy

import pytest

from may.geography.geography import Geography
from may.utils.stacked_input import StackedInputError
from may.venue_distributor.probability import (
    ProbabilityConfigError,
    probability_cache_key,
)
from may.venue_distributor.venue_distributor import VenueDistributor

LEVELS = ["SGU", "MGU"]


def _write_csv(path, rows):
    path.write_text("\n".join(",".join(str(c) for c in row) for row in rows) + "\n")


@pytest.fixture
def prob_files(tmp_path):
    """Two nation files: A00* and B00*, identical columns, disjoint keys."""
    a = tmp_path / "A_probabilities.csv"
    b = tmp_path / "B_probabilities.csv"
    _write_csv(a, [("geo_unit", "prob_uni_18_22"), ("A001", 0.4), ("A002", 0.5)])
    _write_csv(b, [("geo_unit", "prob_uni_18_22"), ("B001", 0.6), ("B002", 0.7)])
    return a, b


@pytest.fixture
def geo_dir(tmp_path):
    """Geography spanning both nations: A001, A002, B001, B002."""
    d = tmp_path / "geography"
    d.mkdir()
    _write_csv(d / "hierarchy.csv", [
        ("SGU", "MGU"),
        ("A001", "AM1"), ("A002", "AM1"),
        ("B001", "BM1"), ("B002", "BM1"),
    ])
    return d


def _config(file_path, **prob_overrides):
    prob_config = {
        "type": "file",
        "file_path": file_path,
        "lookup_column": "geo_unit",
        "lookup_attribute": "geographical_unit.name",
        "probability_column": "prob_uni_18_22",
    }
    prob_config.update(prob_overrides)
    return {
        "venue_type": "university",
        "activity_map_key": "primary_activity",
        "eligibility": {
            "priority_allocation": {
                "enabled": True,
                "groups": [{
                    "name": "uni_age",
                    "priority": 1,
                    "probability_config": prob_config,
                    "filters": [],
                }],
            }
        },
    }


class _World:
    def __init__(self, geography):
        self.geography = geography


def _load_geography(geo_dir):
    geo = Geography(data_dir=str(geo_dir), levels=LEVELS,
                    hierarchy_file="hierarchy.csv", coord_files={})
    geo.load_from_csv()
    return geo


def test_stacks_multiple_files_into_one_lookup(prob_files):
    a, b = prob_files
    d = VenueDistributor(config_dict=_config([str(a), str(b)]))

    (cached,) = d.probability_cache.values()
    assert cached["lookup"] == {"A001": 0.4, "A002": 0.5, "B001": 0.6, "B002": 0.7}


def test_single_string_path_still_works(prob_files):
    a, _ = prob_files
    d = VenueDistributor(config_dict=_config(str(a)))

    (cached,) = d.probability_cache.values()
    assert set(cached["lookup"]) == {"A001", "A002"}


def test_cache_key_is_shared_between_loader_and_filter(prob_files):
    """The two sites build the key independently; they must agree."""
    a, b = prob_files
    config = _config([str(a), str(b)])
    d = VenueDistributor(config_dict=config)

    group = config["eligibility"]["priority_allocation"]["groups"][0]
    assert probability_cache_key(group["probability_config"]) in d.probability_cache


def test_retired_default_key_raises(prob_files):
    a, b = prob_files
    with pytest.raises(ProbabilityConfigError, match="retired key"):
        VenueDistributor(config_dict=_config([str(a), str(b)], default=0.35))


def test_missing_file_raises(prob_files, tmp_path):
    a, _ = prob_files
    absent = tmp_path / "C_probabilities.csv"
    with pytest.raises(StackedInputError, match="not found"):
        VenueDistributor(config_dict=_config([str(a), str(absent)]))


def test_column_mismatch_between_files_raises(prob_files, tmp_path):
    a, _ = prob_files
    odd = tmp_path / "odd.csv"
    _write_csv(odd, [("geo_unit", "prob_other"), ("C001", 0.1)])
    with pytest.raises(StackedInputError, match="column mismatch"):
        VenueDistributor(config_dict=_config([str(a), str(odd)]))


def test_duplicate_geo_unit_across_files_raises(prob_files, tmp_path):
    a, _ = prob_files
    clash = tmp_path / "clash.csv"
    _write_csv(clash, [("geo_unit", "prob_uni_18_22"), ("A001", 0.9)])
    with pytest.raises(StackedInputError, match="already appear"):
        VenueDistributor(config_dict=_config([str(a), str(clash)]))


def test_unknown_probability_column_raises(prob_files):
    a, b = prob_files
    with pytest.raises(ProbabilityConfigError, match="not found"):
        VenueDistributor(config_dict=_config([str(a), str(b)],
                                             probability_column="prob_typo"))


def test_coverage_passes_when_all_nations_listed(prob_files, geo_dir):
    a, b = prob_files
    d = VenueDistributor(config_dict=_config([str(a), str(b)]))

    d._check_probability_coverage(_World(_load_geography(geo_dir)))


def test_coverage_fails_when_a_nation_is_forgotten(prob_files, geo_dir):
    """The bug this guards: geography has both nations, the file list has one."""
    a, _ = prob_files
    d = VenueDistributor(config_dict=_config([str(a)]))

    with pytest.raises(ProbabilityConfigError) as exc:
        d._check_probability_coverage(_World(_load_geography(geo_dir)))

    message = str(exc.value)
    assert "2 of 4 loaded SGUs have no row" in message
    assert "B001" in message


def test_coverage_skipped_when_lookup_is_not_geography(prob_files, geo_dir):
    """Coverage is a claim about geography; a non-geo lookup key is exempt."""
    a, _ = prob_files
    d = VenueDistributor(config_dict=_config([str(a)],
                                             lookup_attribute="properties.tenure"))

    d._check_probability_coverage(_World(_load_geography(geo_dir)))


class _Person:
    def __init__(self, geo_unit):
        self.geographical_unit = type("GeoUnit", (), {"name": geo_unit})()


def _filtering_for(distributor, geo_units):
    """Point the distributor's filter manager at people in the given SGUs."""
    return distributor.allocation, [_Person(g) for g in geo_units]


def test_filter_raises_on_a_geo_unit_with_no_row(prob_files):
    """Backstop behind the coverage check: never silently default."""
    a, b = prob_files
    config = _config([str(a), str(b)])
    d = VenueDistributor(config_dict=config)
    filtering, people = _filtering_for(d, ["A001", "Z999"])
    prob_config = config["eligibility"]["priority_allocation"]["groups"][0]["probability_config"]

    with pytest.raises(ProbabilityConfigError, match="no probability for"):
        filtering.apply_probability_filter(people, prob_config, "uni_age")


def test_filter_selects_by_the_stacked_probabilities(prob_files):
    """A rate of 1.0 keeps everyone and 0.0 keeps nobody, across both files."""
    a, b = prob_files
    _write_csv(a, [("geo_unit", "prob_uni_18_22"), ("A001", 1.0), ("A002", 0.0)])
    _write_csv(b, [("geo_unit", "prob_uni_18_22"), ("B001", 1.0), ("B002", 0.0)])
    config = _config([str(a), str(b)])
    d = VenueDistributor(config_dict=config)
    filtering, people = _filtering_for(d, ["A001", "A002", "B001", "B002"])
    prob_config = config["eligibility"]["priority_allocation"]["groups"][0]["probability_config"]

    selected = filtering.apply_probability_filter(people, prob_config, "uni_age")

    assert [p.geographical_unit.name for p in selected] == ["A001", "B001"]
