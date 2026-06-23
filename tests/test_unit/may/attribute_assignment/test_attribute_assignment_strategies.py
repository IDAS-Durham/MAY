import pytest
import numpy as np
from may.attribute_assignment.strategies import (
    ConstantStrategy,
    ProbabilisticStrategy,
    PartnershipStrategy,
    InheritanceStrategy,
    ReverseInheritanceStrategy,
    StrategyFactory,
)


# =============================================================================
# Minimal real objects (no mock library — just the interface strategies need)
# =============================================================================

class MinimalGeoUnit:
    """Matches the interface strategies access on GeographicalUnit."""
    def __init__(self, name, level="SGU", parent=None):
        self.name = name
        self.level = level
        self.parent = parent

    def get_ancestor_by_level(self, level):
        if self.level == level:
            return self
        current = self.parent
        while current is not None:
            if current.level == level:
                return current
            current = current.parent
        return None


class MinimalPerson:
    """Matches the interface strategies access on Person."""
    _next_id = 1000

    def __init__(self, age=30, sex="M", geographical_unit=None, properties=None):
        self.id = MinimalPerson._next_id
        MinimalPerson._next_id += 1
        self.age = age
        self.sex = sex
        self.geographical_unit = geographical_unit
        self.properties = properties if properties is not None else {}
        self.activities = set()
        self.activity_map = {}


class MinimalVenue:
    """Matches the interface strategies access on Venue (household)."""
    def __init__(self, geographical_unit=None):
        self.id = id(self)
        self.type = "household"
        self.geographical_unit = geographical_unit
        self.properties = {}


class SimpleGeoSource:
    """
    A real (not mocked) data source returning canned probability distributions.
    Supports single-key (geo_unit) and two-key (geo_unit, first_value) lookups.
    """
    def __init__(self, lookup_data=None, fallback=None):
        self._lookup_data = lookup_data or {}
        self._fallback = fallback or {}

    def lookup(self, *args, **kwargs):
        if len(args) == 1:
            return self._lookup_data.get(args[0], self._fallback)
        elif len(args) == 2:
            geo, val = args
            nested = self._lookup_data.get(geo, {})
            return nested.get(val, self._fallback)
        return self._fallback


class SimpleDataManager:
    """
    A real (not mocked) DataSourceManager replacement.
    Stores named sources and delegates lookup calls.
    """
    def __init__(self, sources=None):
        self._sources = sources or {}

    def get_source(self, name):
        return self._sources.get(name)

    def lookup(self, source_name, *args, **kwargs):
        source = self.get_source(source_name)
        if source:
            return source.lookup(*args, **kwargs)
        return {}


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def reset_person_ids():
    """Reset the person ID counter between tests for determinism."""
    MinimalPerson._next_id = 1000


@pytest.fixture
def geo_unit():
    return MinimalGeoUnit("E00001234")


@pytest.fixture
def person_with_geo(geo_unit):
    return MinimalPerson(age=30, sex="M", geographical_unit=geo_unit)


@pytest.fixture
def person_no_geo():
    return MinimalPerson(age=25, sex="F", geographical_unit=None)


@pytest.fixture
def household_with_geo(geo_unit):
    return MinimalVenue(geographical_unit=geo_unit)


@pytest.fixture
def household_no_geo():
    return MinimalVenue(geographical_unit=None)


@pytest.fixture
def ethnicity_geo_source():
    """Geo source that returns a fixed ethnicity distribution for one area."""
    return SimpleGeoSource(
        lookup_data={"E00001234": {"W": 0.80, "A": 0.10, "B": 0.05, "M": 0.03, "O": 0.02}},
        fallback={"W": 0.5, "A": 0.2, "B": 0.1, "M": 0.1, "O": 0.1},
    )


@pytest.fixture
def pair_prob_source():
    """Pair probability source for partnership strategy tests."""
    return SimpleGeoSource(
        lookup_data={
            "E00001234": {
                "W": {"W": 0.90, "A": 0.03, "B": 0.02, "M": 0.03, "O": 0.02},
                "A": {"W": 0.05, "A": 0.85, "B": 0.03, "M": 0.05, "O": 0.02},
            }
        },
        fallback={},
    )


# =============================================================================
# ConstantStrategy Tests
# =============================================================================

class TestConstantStrategy:
    def test_assign_returns_configured_value(self):
        config = {"strategy": "constant", "value": "test_static_value"}
        strategy = ConstantStrategy(config, SimpleDataManager())
        result = strategy.assign(
            MinimalPerson(), MinimalVenue(), {"attribute_name": "attr"}
        )
        assert result == "test_static_value"

    def test_assign_batch_returns_same_value_for_all(self):
        config = {"strategy": "constant", "value": 42}
        strategy = ConstantStrategy(config, SimpleDataManager())
        people = [MinimalPerson() for _ in range(5)]
        results = strategy.assign_batch(
            people,
            [MinimalVenue()] * 5,
            [{"attribute_name": "a"}] * 5,
        )
        assert results == [42, 42, 42, 42, 42]

    def test_missing_value_raises(self):
        """No value → loud failure. No fallbacks (adr/0010)."""
        config = {"strategy": "constant"}  # no 'value' key
        strategy = ConstantStrategy(config, SimpleDataManager())
        context = {"attribute_name": "attr"}
        with pytest.raises(RuntimeError, match="constant strategy has no 'value'"):
            strategy.assign(MinimalPerson(), MinimalVenue(), context)

    def test_value_zero_is_valid_not_treated_as_missing(self):
        """Value 0 is a legitimate constant; it must NOT trigger fallback."""
        config = {"strategy": "constant", "value": 0}
        strategy = ConstantStrategy(config, SimpleDataManager())
        context = {"attribute_name": "attr"}
        result = strategy.assign(MinimalPerson(), MinimalVenue(), context)
        assert result == 0
        assert "fallback_reason" not in context

    def test_value_empty_string_is_valid(self):
        """Empty string is still a valid constant value."""
        config = {"strategy": "constant", "value": ""}
        strategy = ConstantStrategy(config, SimpleDataManager())
        context = {"attribute_name": "attr"}
        result = strategy.assign(MinimalPerson(), MinimalVenue(), context)
        assert result == ""
        assert "fallback_reason" not in context


# =============================================================================
# ProbabilisticStrategy Tests
# =============================================================================

class TestProbabilisticStrategy:
    """
    Intended behaviour (strategies.py lines 135-174):
    1. Try household.geographical_unit.name first
    2. Fall back to person.geographical_unit.name
    3. Return None if neither exists
    4. Lookup probs from data source, sample from distribution
    """

    def test_uses_household_geo_unit_when_available(
        self, person_with_geo, household_with_geo, ethnicity_geo_source
    ):
        dm = SimpleDataManager(sources={"geo_distribution": ethnicity_geo_source})
        config = {"strategy": "probabilistic", "data_source": "geo_distribution"}
        strategy = ProbabilisticStrategy(config, dm)

        np.random.seed(42)
        result = strategy.assign(person_with_geo, household_with_geo, {"attribute_name": "ethnicity"})
        assert result in {"W", "A", "B", "M", "O"}

    def test_falls_back_to_person_geo_when_household_has_none(
        self, person_with_geo, household_no_geo, ethnicity_geo_source
    ):
        dm = SimpleDataManager(sources={"geo_distribution": ethnicity_geo_source})
        config = {"strategy": "probabilistic", "data_source": "geo_distribution"}
        strategy = ProbabilisticStrategy(config, dm)

        np.random.seed(42)
        result = strategy.assign(person_with_geo, household_no_geo, {"attribute_name": "ethnicity"})
        assert result in {"W", "A", "B", "M", "O"}

    def test_raises_when_no_geo_unit_anywhere(
        self, person_no_geo, household_no_geo, ethnicity_geo_source
    ):
        """No geo unit at all → fail loud, no silent None (adr/0010)."""
        dm = SimpleDataManager(sources={"geo_distribution": ethnicity_geo_source})
        config = {"strategy": "probabilistic", "data_source": "geo_distribution"}
        strategy = ProbabilisticStrategy(config, dm)

        with pytest.raises(RuntimeError, match="geographical_unit"):
            strategy.assign(person_no_geo, household_no_geo, {"attribute_name": "ethnicity"})

    def test_raises_when_household_is_none_and_no_person_geo(self, person_no_geo, ethnicity_geo_source):
        """Household None and no person geo → fail loud (adr/0010)."""
        dm = SimpleDataManager(sources={"geo_distribution": ethnicity_geo_source})
        config = {"strategy": "probabilistic", "data_source": "geo_distribution"}
        strategy = ProbabilisticStrategy(config, dm)

        with pytest.raises(RuntimeError, match="geographical_unit"):
            strategy.assign(person_no_geo, None, {"attribute_name": "ethnicity"})

    def test_raises_when_data_source_returns_empty(self, person_with_geo, household_with_geo):
        empty_source = SimpleGeoSource(lookup_data={}, fallback={})
        dm = SimpleDataManager(sources={"geo_distribution": empty_source})
        config = {"strategy": "probabilistic", "data_source": "geo_distribution"}
        strategy = ProbabilisticStrategy(config, dm)

        with pytest.raises(RuntimeError, match="no distribution"):
            strategy.assign(person_with_geo, household_with_geo, {"attribute_name": "ethnicity"})

    def test_raises_when_data_source_not_registered(self, person_with_geo, household_with_geo):
        dm = SimpleDataManager(sources={})
        config = {"strategy": "probabilistic", "data_source": "geo_distribution"}
        strategy = ProbabilisticStrategy(config, dm)

        with pytest.raises(RuntimeError, match="no distribution"):
            strategy.assign(person_with_geo, household_with_geo, {"attribute_name": "ethnicity"})

    def test_deterministic_distribution_always_returns_single_value(
        self, person_with_geo, household_with_geo
    ):
        """When one value has probability 1.0, always returns it."""
        source = SimpleGeoSource(lookup_data={"E00001234": {"A": 1.0}})
        dm = SimpleDataManager(sources={"geo_distribution": source})
        config = {"strategy": "probabilistic", "data_source": "geo_distribution"}
        strategy = ProbabilisticStrategy(config, dm)

        for _ in range(20):
            result = strategy.assign(person_with_geo, household_with_geo, {"attribute_name": "ethnicity"})
            assert result == "A"

    def test_uses_fallback_distribution_for_unknown_geo_unit(self):
        """Person in geo unit not in data → gets fallback distribution."""
        source = SimpleGeoSource(
            lookup_data={},
            fallback={"X": 1.0},
        )
        dm = SimpleDataManager(sources={"geo_distribution": source})
        config = {"strategy": "probabilistic", "data_source": "geo_distribution"}
        strategy = ProbabilisticStrategy(config, dm)

        unknown_geo = MinimalGeoUnit("NOWHERE")
        person = MinimalPerson(geographical_unit=unknown_geo)
        household = MinimalVenue(geographical_unit=unknown_geo)

        result = strategy.assign(person, household, {"attribute_name": "ethnicity"})
        assert result == "X"

    def test_household_geo_takes_priority_over_person_geo(self):
        """
        If household and person have DIFFERENT geo units, household wins.
        This is the intended priority from the code.
        """
        household_geo = MinimalGeoUnit("AREA_H")
        person_geo = MinimalGeoUnit("AREA_P")

        source = SimpleGeoSource(
            lookup_data={
                "AREA_H": {"H_VALUE": 1.0},
                "AREA_P": {"P_VALUE": 1.0},
            }
        )
        dm = SimpleDataManager(sources={"geo_distribution": source})
        config = {"strategy": "probabilistic", "data_source": "geo_distribution"}
        strategy = ProbabilisticStrategy(config, dm)

        person = MinimalPerson(geographical_unit=person_geo)
        household = MinimalVenue(geographical_unit=household_geo)

        result = strategy.assign(person, household, {"attribute_name": "ethnicity"})
        assert result == "H_VALUE", "Household geo unit should take priority over person's"


# =============================================================================
# PartnershipStrategy Tests
# =============================================================================

class TestPartnershipStrategy:
    """
    Intended behaviour (strategies.py lines 193-237):
    1. Get partner person from context["{partner_role}_person"]
    2. Get partner's attribute value from their properties
    3. Look up conditional P(second | geo_unit, first_value)
    4. Sample from that distribution
    Fallback chain: partner not in context → partner has no value → no geo → no data
    """

    def _make_context_with_partner(self, partner_ethnicity):
        partner = MinimalPerson(properties={"ethnicity": partner_ethnicity})
        return {
            "attribute_name": "ethnicity",
            "primary_adult_person": partner,
        }

    def test_samples_from_conditional_distribution(
        self, person_with_geo, household_with_geo, pair_prob_source, ethnicity_geo_source
    ):
        dm = SimpleDataManager(sources={
            "pair_probabilities": pair_prob_source,
            "geo_distribution": ethnicity_geo_source,
        })
        config = {
            "strategy": "partnership",
            "data_source": "pair_probabilities",
            "partner_role": "primary_adult",
        }
        strategy = PartnershipStrategy(config, dm)
        context = self._make_context_with_partner("W")

        np.random.seed(42)
        result = strategy.assign(person_with_geo, household_with_geo, context)
        assert result in {"W", "A", "B", "M", "O"}

    def test_deterministic_pair_distribution(self, person_with_geo, household_with_geo):
        source = SimpleGeoSource(
            lookup_data={"E00001234": {"A": {"B": 1.0}}},
        )
        dm = SimpleDataManager(sources={
            "pair_probabilities": source,
            "geo_distribution": SimpleGeoSource(),
        })
        config = {
            "strategy": "partnership",
            "data_source": "pair_probabilities",
            "partner_role": "primary_adult",
        }
        strategy = PartnershipStrategy(config, dm)
        context = self._make_context_with_partner("A")

        for _ in range(10):
            result = strategy.assign(person_with_geo, household_with_geo, context)
            assert result == "B"

    def test_marginal_when_partner_role_missing_from_context(
        self, person_with_geo, household_with_geo
    ):
        """No partner to condition on → assign from the marginal source (adr/0010)."""
        dm = SimpleDataManager(sources={
            "pair_probabilities": SimpleGeoSource(),
            "geo_distribution": SimpleGeoSource(lookup_data={"E00001234": {"MARGINAL": 1.0}}),
        })
        config = {
            "strategy": "partnership",
            "data_source": "pair_probabilities",
            "partner_role": "primary_adult",
            "marginal_source": "geo_distribution",
        }
        strategy = PartnershipStrategy(config, dm)
        context = {"attribute_name": "ethnicity"}  # no partner

        result = strategy.assign(person_with_geo, household_with_geo, context)
        assert result == "MARGINAL"

    def test_marginal_when_partner_has_no_attribute_value(
        self, person_with_geo, household_with_geo
    ):
        dm = SimpleDataManager(sources={
            "pair_probabilities": SimpleGeoSource(),
            "geo_distribution": SimpleGeoSource(lookup_data={"E00001234": {"MARGINAL": 1.0}}),
        })
        config = {
            "strategy": "partnership",
            "data_source": "pair_probabilities",
            "partner_role": "primary_adult",
            "marginal_source": "geo_distribution",
        }
        strategy = PartnershipStrategy(config, dm)
        partner = MinimalPerson(properties={})  # no ethnicity
        context = {"attribute_name": "ethnicity", "primary_adult_person": partner}

        result = strategy.assign(person_with_geo, household_with_geo, context)
        assert result == "MARGINAL"

    def test_raises_when_household_has_no_geo_unit(
        self, person_with_geo, household_no_geo
    ):
        """No geo unit is a data error → raise. No fallbacks (adr/0010)."""
        dm = SimpleDataManager(sources={
            "pair_probabilities": SimpleGeoSource(),
        })
        config = {
            "strategy": "partnership",
            "data_source": "pair_probabilities",
            "partner_role": "primary_adult",
        }
        strategy = PartnershipStrategy(config, dm)
        context = self._make_context_with_partner("W")

        with pytest.raises(RuntimeError, match="no geographical_unit available"):
            strategy.assign(person_with_geo, household_no_geo, context)

    def test_raises_when_pair_data_source_returns_empty(
        self, person_with_geo, household_with_geo
    ):
        empty_source = SimpleGeoSource(lookup_data={}, fallback={})
        dm = SimpleDataManager(sources={
            "pair_probabilities": empty_source,
        })
        config = {
            "strategy": "partnership",
            "data_source": "pair_probabilities",
            "partner_role": "primary_adult",
        }
        strategy = PartnershipStrategy(config, dm)
        context = self._make_context_with_partner("W")

        with pytest.raises(RuntimeError, match="data source returned no distribution"):
            strategy.assign(person_with_geo, household_with_geo, context)

    # ---- BUG DETECTION ----

    def test_falsy_partner_value_not_treated_as_missing(
        self, person_with_geo, household_with_geo, ethnicity_geo_source
    ):
        """
        Value 0 is a legitimate attribute value and must NOT trigger fallback.
        Regression test for: `if not first_value` → `if first_value is None`.
        """
        dm = SimpleDataManager(sources={
            "pair_probabilities": SimpleGeoSource(
                lookup_data={"E00001234": {0: {"result": 1.0}}},
            ),
            "geo_distribution": ethnicity_geo_source,
        })
        config = {
            "strategy": "partnership",
            "data_source": "pair_probabilities",
            "partner_role": "primary_adult",
            "fallback": {"strategy": "constant", "value": "WRONG_FALLBACK"},
        }
        strategy = PartnershipStrategy(config, dm)

        partner = MinimalPerson(properties={"score": 0})
        context = {"attribute_name": "score", "primary_adult_person": partner}

        result = strategy.assign(person_with_geo, household_with_geo, context)

        assert result != "WRONG_FALLBACK", "Partner value 0 must not trigger fallback"
        assert result == "result"
        assert "fallback_reason" not in context


# =============================================================================
# InheritanceStrategy Tests
# =============================================================================

class TestInheritanceStrategy:
    """
    Intended behaviour (strategies.py lines 241-361, YAML comments):
    Forward inheritance: Parent → Child
      - Both parents same ethnicity → child gets that ethnicity
      - Parents different → child is "M" (Mixed)
      - Single parent → child gets that parent's ethnicity
      - No parents assigned → fallback
    """

    ETHNICITY_LOGIC = [
        {"when": {"unique_count": 1}, "then": "values[0]"},
        {"when": {"unique_count_at_least": 2}, "then": "M"},
    ]

    def _make_strategy(self, logic=None, marginal_source=None):
        config = {
            "strategy": "inheritance",
            "inherit_from": {"roles": ["primary_adult", "secondary_adult"]},
            "logic": logic if logic is not None else self.ETHNICITY_LOGIC,
        }
        if marginal_source:
            config["marginal_source"] = marginal_source
        dm = SimpleDataManager(sources={"geo_distribution": SimpleGeoSource(fallback={"W": 1.0})})
        return InheritanceStrategy(config, dm)

    def _make_context(self, primary_eth=None, secondary_eth=None, attr="ethnicity"):
        ctx = {"attribute_name": attr}
        if primary_eth is not None:
            ctx["primary_adult_person"] = MinimalPerson(properties={attr: primary_eth})
        if secondary_eth is not None:
            ctx["secondary_adult_person"] = MinimalPerson(properties={attr: secondary_eth})
        return ctx

    # --- Core ethnicity inheritance rules ---

    def test_same_ethnicity_parents_child_inherits_same(self):
        """W + W → W"""
        strategy = self._make_strategy()
        context = self._make_context("W", "W")
        result = strategy.assign(MinimalPerson(), MinimalVenue(), context)
        assert result == "W"

    def test_same_ethnicity_all_codes(self):
        """A+A=A, B+B=B, O+O=O, M+M=M"""
        strategy = self._make_strategy()
        for eth in ["A", "B", "O", "M"]:
            context = self._make_context(eth, eth)
            result = strategy.assign(MinimalPerson(), MinimalVenue(), context)
            assert result == eth, f"Expected {eth}+{eth}={eth}, got {result}"

    def test_different_ethnicity_parents_child_is_mixed(self):
        """W + A → M"""
        strategy = self._make_strategy()
        context = self._make_context("W", "A")
        result = strategy.assign(MinimalPerson(), MinimalVenue(), context)
        assert result == "M"

    def test_all_cross_ethnic_pairings_produce_mixed(self):
        strategy = self._make_strategy()
        ethnicities = ["W", "A", "B", "O"]
        for e1 in ethnicities:
            for e2 in ethnicities:
                if e1 != e2:
                    context = self._make_context(e1, e2)
                    result = strategy.assign(MinimalPerson(), MinimalVenue(), context)
                    assert result == "M", f"Expected {e1}+{e2}=M, got {result}"

    def test_mixed_with_any_produces_mixed(self):
        """M + W → M, M + A → M, etc."""
        strategy = self._make_strategy()
        for eth in ["W", "A", "B", "O"]:
            context = self._make_context("M", eth)
            result = strategy.assign(MinimalPerson(), MinimalVenue(), context)
            assert result == "M", f"Expected M+{eth}=M, got {result}"

    # --- Single-parent households ---

    def test_single_parent_child_inherits_from_sole_parent(self):
        strategy = self._make_strategy()
        context = self._make_context("B", None)
        result = strategy.assign(MinimalPerson(), MinimalVenue(), context)
        assert result == "B"

    def test_single_parent_secondary_only(self):
        """Only secondary_adult present (unusual but possible)."""
        strategy = self._make_strategy()
        context = self._make_context(None, "O")
        result = strategy.assign(MinimalPerson(), MinimalVenue(), context)
        assert result == "O"

    # --- No parents → marginal (or raise if no marginal_source) ---

    def test_no_parents_without_marginal_source_raises(self):
        """No parent values and no marginal_source → loud failure (adr/0010)."""
        strategy = self._make_strategy()
        context = self._make_context(None, None)
        with pytest.raises(RuntimeError, match="marginal_source"):
            strategy.assign(MinimalPerson(), MinimalVenue(), context)

    def test_parents_exist_but_unassigned_raises(self):
        """
        Parents are in context but their ethnicity property is missing.
        No marginal_source → loud failure (adr/0010).
        """
        strategy = self._make_strategy()
        primary = MinimalPerson(properties={})
        secondary = MinimalPerson(properties={})
        context = {
            "attribute_name": "ethnicity",
            "primary_adult_person": primary,
            "secondary_adult_person": secondary,
        }
        with pytest.raises(RuntimeError, match="marginal_source"):
            strategy.assign(MinimalPerson(), MinimalVenue(), context)

    # --- Logic block edge cases ---

    def test_no_logic_blocks_raises(self):
        """No logic block matched is a config error → raise (adr/0010)."""
        strategy = self._make_strategy(logic=[])
        context = self._make_context("W", "W")
        with pytest.raises(RuntimeError, match="no logic block matched"):
            strategy.assign(MinimalPerson(), MinimalVenue(), context)

    def test_unknown_predicate_raises(self):
        """An unrecognized 'when' predicate fails loudly at construction (adr/0009)."""
        logic = [
            {"when": {"bogus_operator": 1}, "then": "X"},
        ]
        with pytest.raises(ValueError, match="unknown inheritance 'when' predicate"):
            self._make_strategy(logic=logic)

    # ---- BUG DETECTION ----

    def test_falsy_parent_value_not_skipped(self):
        """
        Value 0 is a legitimate parent attribute and must be inherited.
        Regression test for: `if value:` → `if value is not None:`.
        """
        logic = [
            {"when": {"unique_count": 1}, "then": "values[0]"},
        ]
        strategy = self._make_strategy(logic=logic)
        primary = MinimalPerson(properties={"score": 0})
        secondary = MinimalPerson(properties={"score": 0})
        context = {
            "attribute_name": "score",
            "primary_adult_person": primary,
            "secondary_adult_person": secondary,
        }
        result = strategy.assign(MinimalPerson(), MinimalVenue(), context)

        assert result == 0, "Parent value 0 must be inherited, not skipped"


# =============================================================================
# ReverseInheritanceStrategy Tests
# =============================================================================

class TestReverseInheritanceStrategy:
    """
    Intended behaviour (strategies.py lines 365-482, YAML assignment rules):
    Reverse inheritance: Child → Parent (used for elders inferred from adults)

    For ethnicity:
    - primary_adult is W/A/B/O → elder gets same ethnicity
    - primary_adult is M → elder gets probabilistic sample from geo distribution

    Secondary elder:
    - non-mixed adult → same as primary elder
    - mixed adult → DIFFERENT from primary_elder (YAML uses `exclude`)
    """

    REVERSE_LOGIC_PRIMARY = [
        {
            "when": {"role": "primary_adult", "attr": "ethnicity", "in": ["W", "A", "B", "O"]},
            "then": {"copy": {"role": "primary_adult", "attr": "ethnicity"}},
        },
        {
            "when": {"role": "primary_adult", "attr": "ethnicity", "equals": "M"},
            "then": {"strategy": "probabilistic", "data_source": "geo_distribution"},
        },
    ]

    REVERSE_LOGIC_SECONDARY = [
        {
            "when": {"role": "primary_adult", "attr": "ethnicity", "in": ["W", "A", "B", "O"]},
            "then": {"copy": {"role": "primary_adult", "attr": "ethnicity"}},
        },
        {
            "when": {"role": "primary_adult", "attr": "ethnicity", "equals": "M"},
            "then": {
                "strategy": "probabilistic",
                "data_source": "geo_distribution",
                "exclude": ["primary_elder.ethnicity"],
            },
        },
    ]

    def _make_strategy(self, logic, marginal_source=None):
        config = {
            "strategy": "reverse_inheritance",
            "inherit_from": {"role": "primary_adult"},
            "logic": logic,
        }
        if marginal_source:
            config["marginal_source"] = marginal_source
        geo_source = SimpleGeoSource(fallback={"W": 0.5, "A": 0.3, "B": 0.2})
        dm = SimpleDataManager(sources={"geo_distribution": geo_source})
        return ReverseInheritanceStrategy(config, dm)

    def _make_context(self, adult_ethnicity, attr="ethnicity"):
        adult = MinimalPerson(properties={attr: adult_ethnicity})
        return {"attribute_name": attr, "primary_adult_person": adult}

    # --- Non-mixed adult: elder inherits same ethnicity ---

    def test_non_mixed_adult_elder_gets_same_ethnicity(self):
        strategy = self._make_strategy(self.REVERSE_LOGIC_PRIMARY)
        for eth in ["W", "A", "B", "O"]:
            context = self._make_context(eth)
            result = strategy.assign(MinimalPerson(), MinimalVenue(), context)
            assert result == eth, f"Elder should get {eth} when adult is {eth}"

    # --- Mixed adult: elder gets probabilistic sample ---

    def test_mixed_adult_elder_gets_probabilistic_sample(self):
        strategy = self._make_strategy(self.REVERSE_LOGIC_PRIMARY)
        context = self._make_context("M")

        geo = MinimalGeoUnit("E00001234")
        np.random.seed(42)
        result = strategy.assign(
            MinimalPerson(geographical_unit=geo),
            MinimalVenue(geographical_unit=geo),
            context,
        )
        assert result in {"W", "A", "B"}

    # --- Nothing to condition on → marginal (or raise without marginal_source) ---

    def test_marginal_when_child_role_not_in_context(self):
        """No child role present → assign from marginal source (adr/0010)."""
        strategy = self._make_strategy(
            self.REVERSE_LOGIC_PRIMARY,
            marginal_source="geo_distribution",
        )
        context = {"attribute_name": "ethnicity"}  # no primary_adult_person

        geo = MinimalGeoUnit("E00001234")
        result = strategy.assign(
            MinimalPerson(geographical_unit=geo),
            MinimalVenue(geographical_unit=geo),
            context,
        )
        assert result in {"W", "A", "B"}

    def test_marginal_when_child_has_no_attribute(self):
        strategy = self._make_strategy(
            self.REVERSE_LOGIC_PRIMARY,
            marginal_source="geo_distribution",
        )
        adult = MinimalPerson(properties={})  # no ethnicity
        context = {"attribute_name": "ethnicity", "primary_adult_person": adult}

        geo = MinimalGeoUnit("E00001234")
        result = strategy.assign(
            MinimalPerson(geographical_unit=geo),
            MinimalVenue(geographical_unit=geo),
            context,
        )
        assert result in {"W", "A", "B"}

    def test_no_inherit_role_configured_raises(self):
        config = {
            "strategy": "reverse_inheritance",
            "inherit_from": {},  # no 'role' key
            "logic": self.REVERSE_LOGIC_PRIMARY,
        }
        dm = SimpleDataManager(sources={"geo_distribution": SimpleGeoSource(fallback={"W": 1.0})})
        strategy = ReverseInheritanceStrategy(config, dm)
        context = {"attribute_name": "ethnicity"}

        geo = MinimalGeoUnit("E00001234")
        with pytest.raises(RuntimeError, match="no child role configured"):
            strategy.assign(
                MinimalPerson(geographical_unit=geo),
                MinimalVenue(geographical_unit=geo),
                context,
            )

    # ---- BUG DETECTION ----

    def test_falsy_child_value_not_treated_as_missing(self):
        """
        Value 0 is a legitimate child attribute and must not trigger fallback.
        Regression test for: `if not child_value:` → `if child_value is None:`.
        """
        logic = [
            {"when": {"role": "primary_adult", "attr": "score", "equals": 0},
             "then": {"copy": {"role": "primary_adult", "attr": "score"}}},
        ]
        config = {
            "strategy": "reverse_inheritance",
            "inherit_from": {"role": "primary_adult"},
            "logic": logic,
        }
        dm = SimpleDataManager(sources={"geo_distribution": SimpleGeoSource(fallback={"W": 1.0})})
        strategy = ReverseInheritanceStrategy(config, dm)

        adult = MinimalPerson(properties={"score": 0})
        context = {"attribute_name": "score", "primary_adult_person": adult}

        geo = MinimalGeoUnit("E00001234")
        result = strategy.assign(
            MinimalPerson(geographical_unit=geo),
            MinimalVenue(geographical_unit=geo),
            context,
        )

        assert "fallback_reason" not in context, "Value 0 must not trigger fallback"
        assert result == 0

    def test_exclude_prevents_same_ethnicity_as_primary_elder(self):
        """
        When primary_adult is Mixed, secondary_elder must get a DIFFERENT
        ethnicity from primary_elder. The YAML `exclude` key enforces this.
        """
        strategy = self._make_strategy(self.REVERSE_LOGIC_SECONDARY)

        primary_elder = MinimalPerson(properties={"ethnicity": "W"})
        adult = MinimalPerson(properties={"ethnicity": "M"})
        context = {
            "attribute_name": "ethnicity",
            "primary_adult_person": adult,
            "primary_elder_person": primary_elder,
        }

        # Run many times — "W" must NEVER appear since it's excluded
        # Distribution is {"W": 0.5, "A": 0.3, "B": 0.2}
        geo = MinimalGeoUnit("E00001234")
        results = set()
        np.random.seed(42)
        for _ in range(200):
            ctx = dict(context)
            result = strategy.assign(
                MinimalPerson(geographical_unit=geo),
                MinimalVenue(geographical_unit=geo),
                ctx,
            )
            if result is not None:
                results.add(result)

        assert "W" not in results, "secondary_elder must exclude primary_elder's ethnicity"
        assert results <= {"A", "B"}, f"Expected only A and B, got {results}"

    def test_exclude_with_all_values_excluded_raises(self):
        """
        Edge case: if the geo distribution only has one ethnicity and we exclude
        it, no value remains. That is a data/config contradiction — fail loudly
        rather than silently sampling the excluded value (adr/0010).
        """
        # Distribution has only "W"
        single_source = SimpleGeoSource(fallback={"W": 1.0})
        config = {
            "strategy": "reverse_inheritance",
            "inherit_from": {"role": "primary_adult"},
            "logic": [
                {
                    "when": {"role": "primary_adult", "attr": "ethnicity", "equals": "M"},
                    "then": {
                        "strategy": "probabilistic",
                        "data_source": "geo_distribution",
                        "exclude": ["primary_elder.ethnicity"],
                    },
                },
            ],
        }
        dm = SimpleDataManager(sources={"geo_distribution": single_source})
        strategy = ReverseInheritanceStrategy(config, dm)

        primary_elder = MinimalPerson(properties={"ethnicity": "W"})  # exclude "W"
        adult = MinimalPerson(properties={"ethnicity": "M"})
        context = {
            "attribute_name": "ethnicity",
            "primary_adult_person": adult,
            "primary_elder_person": primary_elder,
        }

        geo = MinimalGeoUnit("E00001234")
        with pytest.raises(RuntimeError, match="all values excluded"):
            strategy.assign(
                MinimalPerson(geographical_unit=geo),
                MinimalVenue(geographical_unit=geo),
                context,
            )

    def test_exclude_with_no_primary_elder_in_context(self):
        """
        If primary_elder hasn't been assigned yet (not in context),
        exclude should resolve to empty set — no values excluded.
        """
        strategy = self._make_strategy(self.REVERSE_LOGIC_SECONDARY)

        # Only adult in context, no primary_elder_person
        adult = MinimalPerson(properties={"ethnicity": "M"})
        context = {
            "attribute_name": "ethnicity",
            "primary_adult_person": adult,
            # no primary_elder_person
        }

        geo = MinimalGeoUnit("E00001234")
        np.random.seed(42)
        result = strategy.assign(
            MinimalPerson(geographical_unit=geo),
            MinimalVenue(geographical_unit=geo),
            context,
        )

        # Should still work — just samples from full distribution
        assert result in {"W", "A", "B"}


# =============================================================================
# StrategyFactory Tests
# =============================================================================

class TestStrategyFactory:
    def test_creates_all_known_strategy_types(self):
        dm = SimpleDataManager()
        known_types = [
            ("probabilistic", ProbabilisticStrategy),
            ("partnership", PartnershipStrategy),
            ("inheritance", InheritanceStrategy),
            ("reverse_inheritance", ReverseInheritanceStrategy),
            ("constant", ConstantStrategy),
        ]
        for strategy_type, expected_class in known_types:
            instance = StrategyFactory.create_strategy({"strategy": strategy_type}, dm)
            assert isinstance(instance, expected_class), (
                f"Expected {expected_class.__name__} for '{strategy_type}'"
            )

    def test_raises_on_unknown_strategy_type(self):
        with pytest.raises(ValueError, match="unknown strategy"):
            StrategyFactory.create_strategy({"strategy": "nonexistent"}, SimpleDataManager())

    def test_raises_when_strategy_key_missing(self):
        with pytest.raises(ValueError, match="no 'strategy' field"):
            StrategyFactory.create_strategy({}, SimpleDataManager())

    def test_raises_on_unread_keys(self):
        """Keys no strategy reads (e.g. the old `context`) fail loudly."""
        with pytest.raises(ValueError, match="does not read key.*context"):
            StrategyFactory.create_strategy(
                {
                    "strategy": "probabilistic",
                    "data_source": "geo_distribution",
                    "context": "household.geo_unit",
                },
                SimpleDataManager(),
            )

    def test_probabilistic_conditions_requires_selection_method(self):
        """No implicit default — selection_method must be declared (adr/0013)."""
        with pytest.raises(ValueError, match="requires 'selection_method'"):
            StrategyFactory.create_strategy(
                {"strategy": "probabilistic_conditions", "data_source": "x", "conditions": []},
                SimpleDataManager(),
            )

    def test_probabilistic_conditions_rejects_unknown_selection_method(self):
        """An unknown selection_method fails at load, not deep in assign."""
        with pytest.raises(ValueError, match="unknown selection_method"):
            StrategyFactory.create_strategy(
                {
                    "strategy": "probabilistic_conditions",
                    "data_source": "x",
                    "conditions": [],
                    "selection_method": "bogus",
                },
                SimpleDataManager(),
            )


# =============================================================================
# Base class _fail / _marginal_assign mechanism Tests (adr/0010)
# =============================================================================

class TestNoFallbackMechanism:
    def test_marginal_assign_uses_configured_source(self):
        """A 'nothing to condition on' case samples from marginal_source."""
        geo_source = SimpleGeoSource(fallback={"Z": 1.0})
        config = {
            "strategy": "partnership",
            "data_source": "pair_probabilities",
            "partner_role": "primary_adult",
            "marginal_source": "geo_distribution",
        }
        dm = SimpleDataManager(sources={"geo_distribution": geo_source})
        strategy = PartnershipStrategy(config, dm)

        geo = MinimalGeoUnit("E00001234")
        context = {"attribute_name": "ethnicity"}  # no partner
        result = strategy.assign(
            MinimalPerson(geographical_unit=geo),
            MinimalVenue(geographical_unit=geo),
            context,
        )
        assert result == "Z"

    def test_no_marginal_source_raises(self):
        """No marginal_source for a 'nothing to condition on' case → raise.

        No fallbacks (adr/0010) — the old behavior silently invented a
        geo_distribution sample, masking data and config problems."""
        config = {
            "strategy": "partnership",
            "data_source": "pair_probabilities",
            "partner_role": "primary_adult",
            # no 'marginal_source' key
        }
        dm = SimpleDataManager(sources={"geo_distribution": SimpleGeoSource(fallback={"DEFAULT": 1.0})})
        strategy = PartnershipStrategy(config, dm)

        geo = MinimalGeoUnit("E00001234")
        context = {"attribute_name": "ethnicity"}
        with pytest.raises(RuntimeError, match="marginal_source"):
            strategy.assign(
                MinimalPerson(geographical_unit=geo),
                MinimalVenue(geographical_unit=geo),
                context,
            )
