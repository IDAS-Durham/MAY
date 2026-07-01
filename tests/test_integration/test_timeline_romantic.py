import csv
import logging
from collections import Counter
from pathlib import Path

import numpy as np
import pytest
import yaml

logging.basicConfig(level=logging.DEBUG)


class MockPopulation:
    def __init__(self, people):
        self.people = people


class MockWorld:
    def __init__(self, population):
        self.population = population


class MockPerson:
    def __init__(self, id_val, age, sex, properties=None, geographical_unit=None):
        self.id = id_val
        self.age = age
        self.sex = sex
        self.properties = properties or {}
        self.geographical_unit = geographical_unit


class MockGeoUnit:
    def __init__(self, name):
        self.name = name

    def get_ancestor_by_level(self, level):
        # Tests use MGU codes (E02...) directly.
        return self if level == "MGU" else None

@pytest.fixture
def mock_romantic_world():
    people = [
        # Scenario 1: Base singles mapping (testing probabilities)
        MockPerson(1, 30, "male"),
        MockPerson(2, 30, "female"),
        
        # Scenario 2: Age adjustments (18-24)
        MockPerson(3, 20, "male"),
        MockPerson(4, 20, "female"),
        
        # Scenario 3 & 4: Cohabiting couples (Opposite sex and Same sex)
        MockPerson(5, 40, "male", {"cohabiting_couple": [6]}),
        MockPerson(6, 38, "female", {"cohabiting_couple": [5]}),
        
        MockPerson(7, 45, "male", {"cohabiting_couple": [8]}),
        MockPerson(8, 42, "male", {"cohabiting_couple": [7]}),
        
        # Scenario 5: Bug isolation (Partner ID 999 where 999 doesn't exist)
        MockPerson(9, 50, "female", {"cohabiting_couple": [999]}),
    ]
    
    return MockWorld(MockPopulation(people))
    
def test_romantic_distributor_exhaustion(mock_romantic_world):
    from may.relationships.romantic_relationships.romantic_distributor import RomanticDistributor
    config_path = str(Path(__file__).parent.parent / "test_data" / "micro_world" / "relationships" / "test_romantic_config.yaml")

    distributor = RomanticDistributor(mock_romantic_world, config_path)
    distributor.distribute_all()
    
    people = mock_romantic_world.population.people
    
    # Validation 1: Everyone got an assignment
    for p in people:
        assert 'sexual_orientation' in p.properties
        assert 'relationship_status' in p.properties
        
    # Validation 2: Opposite sex couple compatibility forces valid mapping
    p5_orient = people[4].properties['sexual_orientation']
    p6_orient = people[5].properties['sexual_orientation']
    assert p5_orient in ['heterosexual', 'bisexual']
    assert p6_orient in ['heterosexual', 'bisexual']
    assert people[4].properties['relationship_status']['type'] == 'exclusive'
    
    # Validation 3: Same sex couple compatibility forces valid mapping
    p7_orient = people[6].properties['sexual_orientation']
    p8_orient = people[7].properties['sexual_orientation']
    assert p7_orient in ['homosexual', 'bisexual']
    assert p8_orient in ['homosexual', 'bisexual']
    
    # Validation 4: Bug isolation survived (P9 had an invalid partner 999, which triggered exception logic inside but shouldn't crash python!)
    assert 'sexual_orientation' in people[8].properties


def test_passes_filters_semantics():
    """eligibility.global_filters: numerical min/max, categorical, missing-attr fails."""
    from may.relationships.romantic_relationships.romantic_distributor import RomanticDistributor

    cfg = {
        "name": "t",
        "eligibility": {"global_filters": [
            {"attribute": "age", "type": "numerical", "min": 16, "max": 120},
            {"attribute": "sex", "type": "categorical", "values": ["male", "female"]},
        ]},
        "sexual_orientations": {"types": ["heterosexual"]},
    }
    rd = RomanticDistributor(MockWorld(MockPopulation([])), cfg)

    assert rd._passes_filters(MockPerson(1, 30, "male")) is True
    assert rd._passes_filters(MockPerson(2, 15, "male")) is False        # below min
    assert rd._passes_filters(MockPerson(3, 30, "nonbinary")) is False   # not in values
    assert rd._passes_filters(MockPerson(4, None, "male")) is False      # missing age → fails

    # No filters → everyone eligible.
    rd2 = RomanticDistributor(MockWorld(MockPopulation([])),
                              {"name": "t", "sexual_orientations": {"types": ["heterosexual"]}})
    assert rd2._passes_filters(MockPerson(5, 5, "male")) is True


# ---------------------------------------------------------------------------
# Data-source path: per-MSOA raking should make LGB share track local marginals
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_msoa_marginals():
    path = REPO_ROOT / "data/population/sexual_orientation/orientation_by_msoa_normalized.csv"
    by_code = {}
    with path.open() as f:
        for row in csv.DictReader(f):
            by_code[row["geo_unit"]] = {
                "heterosexual": float(row["heterosexual"]),
                "homosexual": float(row["homosexual"]),
                "bisexual": float(row["bisexual"]),
            }
    return by_code


def test_romantic_distributor_handles_75plus_via_extrapolation():
    """A 95-year-old must receive an orientation without crashing the band lookup."""
    from may.relationships.romantic_relationships.romantic_distributor import (
        RomanticDistributor,
    )

    np.random.seed(0)
    marginals = _load_msoa_marginals()
    code = next(iter(marginals))
    geo = MockGeoUnit(code)

    cfg = yaml.safe_load(
        (REPO_ROOT / "configs/2021/relationships/romantic_relationships.yaml").read_text()
    )
    cfg["data_sources"]["demographic_distribution"]["path"] = str(
        REPO_ROOT / "data/population/sexual_orientation/orientation_prevalence_extended.csv"
    )
    cfg["data_sources"]["geo_distribution"]["path"] = str(
        REPO_ROOT / "data/population/sexual_orientation/orientation_by_msoa_normalized.csv"
    )

    people = [
        MockPerson(1, 80, "male", geographical_unit=geo),
        MockPerson(2, 95, "female", geographical_unit=geo),
        MockPerson(3, 110, "male", geographical_unit=geo),  # tail beyond extrapolation
    ]
    world = MockWorld(MockPopulation(people))
    rd = RomanticDistributor(world, cfg)
    rd.distribute_all()

    for p in people:
        assert p.properties["sexual_orientation"] in (
            "heterosexual",
            "homosexual",
            "bisexual",
        )


# ---------------------------------------------------------------------------
# Stage 1: per-MSOA same-sex couple probability lookup
# ---------------------------------------------------------------------------


def test_relationship_rules_resolves_same_category_per_area(tmp_path):
    """The validator should look up P(same-category) per area when configured.

    The mechanism is generic — it applies to any categorical attribute, not
    just `sex`. This test uses a synthetic religion source to prove the
    schema is domain-agnostic.
    """
    from may.residence.relationship_rules import RelationshipRulesValidator

    sex_csv = tmp_path / "sex.csv"
    sex_csv.write_text(
        "geo_unit,total_responding,heterosexual,homosexual,bisexual\n"
        "E02000001,1000,0.80,0.10,0.10\n"
        "E02000002,1000,0.99,0.005,0.005\n"
    )
    religion_csv = tmp_path / "religion.csv"
    religion_csv.write_text(
        "geo_unit,same_religion_share\n"
        "E02000001,0.40\n"
        "E02000002,0.85\n"
    )
    cfg_path = tmp_path / "rules.yaml"
    cfg_path.write_text(
        "enabled: true\n"
        "rules: []\n"
        "same_category_sources:\n"
        "  - attribute: sex\n"
        f"    csv_path: {sex_csv}\n"
        "    geo_code_column: geo_unit\n"
        "    geo_level: MGU\n"
        "    formula:\n"
        "      - column: homosexual\n"
        "        weight: 1.0\n"
        "      - column: bisexual\n"
        "        weight: 0.5\n"
        "  - attribute: religion\n"
        f"    csv_path: {religion_csv}\n"
        "    geo_code_column: geo_unit\n"
        "    geo_level: MGU\n"
        "    formula:\n"
        "      - column: same_religion_share\n"
        "        weight: 1.0\n"
    )

    class FakeGeography:
        def __init__(self, units):
            self._units = units

        def get_unit(self, name):
            return self._units.get(name)

    geo_high = MockGeoUnit("E02000001")
    geo_low = MockGeoUnit("E02000002")
    geography = FakeGeography({"E02000001": geo_high, "E02000002": geo_low})

    validator = RelationshipRulesValidator(
        categories=[],
        config_file=str(cfg_path),
        geography=geography,
    )

    # sex: high LGB MSOA → 0.10 + 0.5*0.10 = 0.15
    assert abs(validator._resolve_same_category_prob("sex", "E02000001", default=0.05) - 0.15) < 1e-9
    # sex: low LGB MSOA → 0.005 + 0.5*0.005 = 0.0075
    assert abs(validator._resolve_same_category_prob("sex", "E02000002", default=0.05) - 0.0075) < 1e-9
    # religion (different domain, same machinery): single-column formula passes through.
    assert abs(validator._resolve_same_category_prob("religion", "E02000001", default=0.5) - 0.40) < 1e-9
    assert abs(validator._resolve_same_category_prob("religion", "E02000002", default=0.5) - 0.85) < 1e-9
    # Attribute with no source falls back to default.
    assert validator._resolve_same_category_prob("ethnicity", "E02000001", default=0.5) == 0.5
    # Unknown area falls back to default.
    assert validator._resolve_same_category_prob("sex", "E02999999", default=0.05) == 0.05
    # Missing geo_unit_code falls back to default.
    assert validator._resolve_same_category_prob("sex", None, default=0.05) == 0.05
