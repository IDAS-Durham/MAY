"""Load-time validation that `household` build steps only reference real
households.csv composition patterns (exact-string match — a typo there would
otherwise silently build nothing). Excess/overflow/promotion patterns are
left to runtime, where they warn on a miss / match runtime patterns."""

import pytest

from may.residence.allocation_strategy import _validate_step_patterns
from may.residence.household_distributor import HouseholdError

VOCAB = {">=2 >=0 2 0", "1 >=0 2 0", "0 0 2 0", "0 >=0 0 0"}


def test_known_patterns_pass():
    steps = [
        {"type": "household", "name": "build", "patterns": [">=2 >=0 2 0", "1 >=0 2 0"]},
        {"type": "household", "name": "assumed",
         "patterns": [{"pattern": "0 >=0 0 0", "assumption": "0 2 0 0"}]},  # assumption not checked
        {"type": "household_excess", "name": "excess", "target_patterns": ["0 0 2 0"]},
        {"type": "venue", "name": "venue", "venue_type": "care_home"},      # skipped
    ]
    _validate_step_patterns(steps, VOCAB)  # must not raise


def test_unknown_build_pattern_fails_loud():
    steps = [{"type": "household", "name": "typo", "patterns": [">=2 0 2 0"]}]
    with pytest.raises(HouseholdError, match="absent from households.csv"):
        _validate_step_patterns(steps, VOCAB)


def test_excess_overflow_phantom_patterns_not_checked():
    # target_patterns are a catch-all superset matched against original_pattern;
    # a miss already warns at runtime, so it must NOT fail the build.
    steps = [
        {"type": "household_excess", "name": "x", "target_patterns": [">=2 >=0 1 0"]},
        {"type": "household_overflow", "name": "y", "target_patterns": ["9 9 9 9"]},
    ]
    _validate_step_patterns(steps, VOCAB)  # must not raise


def test_promotion_source_patterns_not_checked():
    # source_pattern matches a runtime allocation_pattern, not the CSV vocabulary.
    steps = [{"type": "household_promotion", "name": "promo",
              "promotion_rules": [{"source_pattern": "9 9 9 9", "target_pattern": "9 9 9 9"}]}]
    _validate_step_patterns(steps, VOCAB)  # must not raise


def test_empty_vocabulary_skips():
    steps = [{"type": "household", "name": "x", "patterns": ["nonsense"]}]
    _validate_step_patterns(steps, set())  # nothing to validate against


# patterns_where selectors

from dataclasses import dataclass
from may.residence.allocation_strategy import _resolve_pattern_selectors


@dataclass
class Cat:
    name: str


CATS = [Cat("Kids"), Cat("Young Adults"), Cat("Adults"), Cat("Old Adults")]
SEL_VOCAB = {"0 0 2 0", "1 0 2 0", "2 1 0 0", "0 0 0 >=3", ">=6 0 2 0"}


def test_selector_resolves_to_matching_patterns():
    steps = [{"type": "household", "name": "families", "patterns_where": [
        {"category": "Kids", "operator": ">=", "value": 1},
        {"category": "Adults", "operator": ">=", "value": 1},
    ]}]
    _resolve_pattern_selectors(steps, SEL_VOCAB, CATS)
    assert steps[0]["patterns"] == ["1 0 2 0", ">=6 0 2 0"]
    assert "patterns_where" not in steps[0]


def test_selector_overlap_fails_loud():
    steps = [
        {"type": "household", "name": "a", "patterns_where": [
            {"category": "Kids", "operator": ">=", "value": 1}]},
        {"type": "household", "name": "b", "patterns": ["1 0 2 0"]},
    ]
    with pytest.raises(HouseholdError, match="claimed by both"):
        _resolve_pattern_selectors(steps, SEL_VOCAB, CATS)


def test_null_takes_remainder():
    steps = [
        {"type": "household", "name": "families", "patterns_where": [
            {"category": "Kids", "operator": ">=", "value": 1}]},
        {"type": "household", "name": "rest", "patterns": None},
    ]
    _resolve_pattern_selectors(steps, SEL_VOCAB, CATS)
    assert steps[1]["patterns"] == ["0 0 0 >=3", "0 0 2 0"]


def test_null_alone_still_means_all():
    steps = [{"type": "household", "name": "all", "patterns": None}]
    _resolve_pattern_selectors(steps, SEL_VOCAB, CATS)
    assert set(steps[0]["patterns"]) == SEL_VOCAB


def test_selector_unknown_category_fails_loud():
    steps = [{"type": "household", "name": "x", "patterns_where": [
        {"category": "Elders", "operator": ">=", "value": 1}]}]
    with pytest.raises(HouseholdError, match="Elders"):
        _resolve_pattern_selectors(steps, SEL_VOCAB, CATS)


def test_selector_matching_nothing_fails_loud():
    steps = [{"type": "household", "name": "x", "patterns_where": [
        {"category": "Kids", "operator": ">", "value": 90}]}]
    with pytest.raises(HouseholdError, match="matched no pattern"):
        _resolve_pattern_selectors(steps, SEL_VOCAB, CATS)


def test_selector_plus_patterns_fails_loud():
    steps = [{"type": "household", "name": "x", "patterns": ["0 0 2 0"],
              "patterns_where": [{"category": "Kids", "operator": ">=", "value": 0}]}]
    with pytest.raises(HouseholdError, match="not both"):
        _resolve_pattern_selectors(steps, SEL_VOCAB, CATS)
