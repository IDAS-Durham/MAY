"""
Extended unit tests for strategies.py — covers the 4 untested strategies
and the StrategyFactory completeness.

Covers:
- ProbabilisticConditionsStrategy: independent Bernoulli sampling, empty conditions,
  missing data sources, unknown selection methods
- CommutingLikelihoodStrategy: single/multi output, batch/sequential, origin resolution,
  ancestor lookup, missing data, empty destinations
- GUSamplerStrategy: workplace→home fallback, batch/sequential, missing data
- CategoricalSamplerStrategy: single sampling, batch grouping, normalization,
  zero/negative totals, missing data
- StrategyFactory: all 9 registered types
"""
import pytest
import logging
import numpy as np
from may.attribute_assignment.strategies import (
    ProbabilisticConditionsStrategy,
    CommutingLikelihoodStrategy,
    GUSamplerStrategy,
    CategoricalSamplerStrategy,
    ConstantStrategy,
    StrategyFactory,
    ProbabilisticStrategy,
    PartnershipStrategy,
    InheritanceStrategy,
    ReverseInheritanceStrategy,
    ProbabilisticConditionsStrategy,
)


# =============================================================================
# Minimal real objects
# =============================================================================

class MinimalGeoUnit:
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
    _next_id = 6000

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
    def __init__(self, geographical_unit=None):
        self.id = id(self)
        self.type = "household"
        self.geographical_unit = geographical_unit
        self.properties = {}


class SimpleGeoSource:
    """Supports single-key and two-key lookups."""
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


class MultiKeySource:
    """Source that accepts (person, household, context) like MultiKeyLookupSource."""
    def __init__(self, return_value=None):
        self._return_value = return_value or {}

    def lookup(self, *args, **kwargs):
        return self._return_value


class ODMatrixSource:
    """Source that returns O-D matrix format: List[(dest, metadata, likelihood)]."""
    def __init__(self, lookup_data=None):
        self._lookup_data = lookup_data or {}

    def lookup(self, origin_code):
        return self._lookup_data.get(origin_code, [])


class GUSamplerSource:
    """Source that returns {gu_code: probability} dicts."""
    def __init__(self, lookup_data=None):
        self._lookup_data = lookup_data or {}

    def lookup(self, parent_gu):
        return self._lookup_data.get(parent_gu, {})


class SimpleDataManager:
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
    MinimalPerson._next_id = 6000


@pytest.fixture
def geo_unit():
    return MinimalGeoUnit("E00001234")


# =============================================================================
# ProbabilisticConditionsStrategy Tests
# =============================================================================

class TestProbabilisticConditionsStrategy:
    """
    Intended behaviour (strategies.py lines 603-682):
    - Looks up per-person probabilities from a data source (e.g., MultiKeyLookupSource)
    - For each named condition, runs a Bernoulli trial
    - Returns a list of condition names that "fired"
    - Empty list is valid (person has no conditions)
    """

    def _make_strategy(self, conditions, data_source_name="comorbidity_probs",
                        selection_method="independent_bernoulli"):
        config = {
            "strategy": "probabilistic_conditions",
            "data_source": data_source_name,
            "conditions": conditions,
            "selection_method": selection_method,
        }
        return config

    def test_all_conditions_fire_with_probability_one(self):
        """When all probabilities are 1.0, all conditions must be selected."""
        conditions = [{"name": "cvd"}, {"name": "crd"}, {"name": "diabetes"}]
        source = MultiKeySource(return_value={"cvd": 1.0, "crd": 1.0, "diabetes": 1.0})
        dm = SimpleDataManager(sources={"comorbidity_probs": source})
        strategy = ProbabilisticConditionsStrategy(
            self._make_strategy(conditions), dm
        )

        result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "comorbidities"})
        assert result == ["cvd", "crd", "diabetes"]

    def test_no_conditions_fire_with_probability_zero(self):
        """When all probabilities are 0.0, no conditions should be selected."""
        conditions = [{"name": "cvd"}, {"name": "crd"}]
        source = MultiKeySource(return_value={"cvd": 0.0, "crd": 0.0})
        dm = SimpleDataManager(sources={"comorbidity_probs": source})
        strategy = ProbabilisticConditionsStrategy(
            self._make_strategy(conditions), dm
        )

        result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "comorbidities"})
        assert result == []

    def test_partial_conditions_fire(self):
        """One condition at p=1, one at p=0 → only the first fires."""
        conditions = [{"name": "cvd"}, {"name": "crd"}]
        source = MultiKeySource(return_value={"cvd": 1.0, "crd": 0.0})
        dm = SimpleDataManager(sources={"comorbidity_probs": source})
        strategy = ProbabilisticConditionsStrategy(
            self._make_strategy(conditions), dm
        )

        result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "comorbidities"})
        assert result == ["cvd"]

    def test_condition_not_in_data_source_defaults_to_zero(self):
        """If a condition name isn't in the probability dict, it defaults to 0.0."""
        conditions = [{"name": "rare_condition"}]
        source = MultiKeySource(return_value={"cvd": 1.0})  # no "rare_condition"
        dm = SimpleDataManager(sources={"comorbidity_probs": source})
        strategy = ProbabilisticConditionsStrategy(
            self._make_strategy(conditions), dm
        )

        result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "comorbidities"})
        assert result == []

    def test_empty_conditions_list_returns_empty(self):
        """No conditions configured → always empty list."""
        source = MultiKeySource(return_value={"cvd": 1.0})
        dm = SimpleDataManager(sources={"comorbidity_probs": source})
        strategy = ProbabilisticConditionsStrategy(
            self._make_strategy(conditions=[]), dm
        )

        result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "comorbidities"})
        assert result == []

    def test_missing_data_source_returns_empty(self):
        """Data source not registered → empty list."""
        conditions = [{"name": "cvd"}]
        dm = SimpleDataManager(sources={})  # no source
        strategy = ProbabilisticConditionsStrategy(
            self._make_strategy(conditions), dm
        )

        result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "comorbidities"})
        assert result == []

    def test_no_data_source_name_returns_empty(self):
        conditions = [{"name": "cvd"}]
        config = {"strategy": "probabilistic_conditions", "conditions": conditions}
        dm = SimpleDataManager()
        strategy = ProbabilisticConditionsStrategy(config, dm)

        result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "comorbidities"})
        assert result == []

    def test_data_source_returns_empty_dict_returns_empty(self):
        """Data source returns {} for this person → empty list."""
        conditions = [{"name": "cvd"}]
        source = MultiKeySource(return_value={})
        dm = SimpleDataManager(sources={"comorbidity_probs": source})
        strategy = ProbabilisticConditionsStrategy(
            self._make_strategy(conditions), dm
        )

        result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "comorbidities"})
        assert result == []

    def test_unknown_selection_method_returns_empty(self):
        """Unknown selection method → empty list."""
        conditions = [{"name": "cvd"}]
        source = MultiKeySource(return_value={"cvd": 1.0})
        dm = SimpleDataManager(sources={"comorbidity_probs": source})
        strategy = ProbabilisticConditionsStrategy(
            self._make_strategy(conditions, selection_method="not_real"), dm
        )

        result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "comorbidities"})
        assert result == []

    def test_condition_without_name_key_is_skipped(self):
        """Condition dict missing 'name' → skipped silently."""
        conditions = [{"name": "cvd"}, {"description": "no name field"}, {"name": "crd"}]
        source = MultiKeySource(return_value={"cvd": 1.0, "crd": 1.0})
        dm = SimpleDataManager(sources={"comorbidity_probs": source})
        strategy = ProbabilisticConditionsStrategy(
            self._make_strategy(conditions), dm
        )

        result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "comorbidities"})
        assert result == ["cvd", "crd"]

    # ---- BUG DETECTION ----

    def test_return_type_is_list_not_single_value(self):
        """
        ProbabilisticConditionsStrategy.assign() returns a List[str].
        This is important because the assigner's _assign_household (line 659) does:
            person.properties[self.attribute_name] = value
        which stores the entire list — this is correct for comorbidities.
        But the attribute_distribution counter (line 664) does:
            self.stats['attribute_distribution'][value] += 1
        A list is NOT hashable and would crash as a dict key.

        BUG: _assign_household doesn't handle list return values.
        """
        conditions = [{"name": "cvd"}]
        source = MultiKeySource(return_value={"cvd": 1.0})
        dm = SimpleDataManager(sources={"comorbidity_probs": source})
        strategy = ProbabilisticConditionsStrategy(
            self._make_strategy(conditions), dm
        )

        result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "comorbidities"})
        assert isinstance(result, list), "ProbabilisticConditionsStrategy must return a list"

        # This would crash in _assign_household line 664:
        # self.stats['attribute_distribution'][value] += 1
        # because list is not hashable
        with pytest.raises(TypeError):
            d = {}
            d[result] += 1  # list is not hashable

    def test_empty_list_is_truthy_but_evaluates_as_falsy(self):
        """
        BUG: assign() returns [] when no conditions fire.
        In _assign_household line 657: `if value is not None:`
        An empty list passes this check ([] is not None → True).
        So an empty list is stored as person.properties[attr] = [].
        This is technically correct but worth documenting.

        However, in _assign_all_people_batch line 442:
        `if value is not None:` also passes for [].
        Then line 452: person.properties[self.attribute_name] = value
        stores [] which is fine.
        But line 453: self.stats['attribute_distribution'][str(value)] += 1
        would count str([]) = "[]" as a distribution key. Acceptable but odd.
        """
        conditions = [{"name": "cvd"}]
        source = MultiKeySource(return_value={"cvd": 0.0})
        dm = SimpleDataManager(sources={"comorbidity_probs": source})
        strategy = ProbabilisticConditionsStrategy(
            self._make_strategy(conditions), dm
        )

        result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "comorbidities"})
        assert result == []
        assert result is not None  # [] is not None — passes the None check


# =============================================================================
# CommutingLikelihoodStrategy Tests
# =============================================================================

class TestCommutingLikelihoodStrategy:
    """
    Intended behaviour (strategies.py lines 684-916):
    - Resolves person's origin GU (with optional ancestor_lookup)
    - Looks up O-D matrix destinations for that origin
    - Samples one destination weighted by likelihood
    - Returns single value or dict of {attr: value} based on outputs config
    - Batch mode groups people by origin for efficiency
    """

    def _make_od_source(self, data):
        return ODMatrixSource(lookup_data=data)

    def _make_strategy(self, outputs, data_source_name="commuting_flows", fallback=None):
        config = {
            "strategy": "commuting_likelihood",
            "data_source": data_source_name,
            "outputs": outputs,
        }
        if fallback:
            config["fallback"] = fallback
        return config

    # --- Single output ---

    def test_single_output_destination(self):
        """Single output mapped to 'destination' returns the destination code."""
        source = self._make_od_source({
            "ORIGIN_A": [("DEST_1", {"mode": "car"}, 1.0)]
        })
        dm = SimpleDataManager(sources={"commuting_flows": source})
        config = self._make_strategy(outputs={"workplace_location": "destination"})
        strategy = CommutingLikelihoodStrategy(config, dm)

        person = MinimalPerson(geographical_unit=MinimalGeoUnit("ORIGIN_A"))
        result = strategy.assign(person, MinimalVenue(), {"attribute_name": "workplace_location"})
        assert result == "DEST_1"

    def test_single_output_from_metadata(self):
        """Single output mapped to a metadata column returns that metadata value."""
        source = self._make_od_source({
            "ORIGIN_A": [("DEST_1", {"mode": "bus"}, 1.0)]
        })
        dm = SimpleDataManager(sources={"commuting_flows": source})
        config = self._make_strategy(outputs={"work_mode": "mode"})
        strategy = CommutingLikelihoodStrategy(config, dm)

        person = MinimalPerson(geographical_unit=MinimalGeoUnit("ORIGIN_A"))
        result = strategy.assign(person, MinimalVenue(), {"attribute_name": "work_mode"})
        assert result == "bus"

    # --- Multiple outputs ---

    def test_multiple_outputs_returns_dict(self):
        """Multiple outputs → returns dict with all values."""
        source = self._make_od_source({
            "ORIGIN_A": [("DEST_1", {"mode": "car", "distance": 10.5}, 1.0)]
        })
        dm = SimpleDataManager(sources={"commuting_flows": source})
        config = self._make_strategy(outputs={
            "workplace_location": "destination",
            "work_mode": "mode",
        })
        strategy = CommutingLikelihoodStrategy(config, dm)

        person = MinimalPerson(geographical_unit=MinimalGeoUnit("ORIGIN_A"))
        result = strategy.assign(person, MinimalVenue(), {"attribute_name": "workplace_location"})
        assert isinstance(result, dict)
        assert result["workplace_location"] == "DEST_1"
        assert result["work_mode"] == "car"

    # --- Sampling distribution ---

    def test_samples_according_to_likelihood(self):
        """Destination with 100% likelihood is always chosen."""
        source = self._make_od_source({
            "ORIGIN_A": [
                ("DEST_1", {}, 0.0),
                ("DEST_2", {}, 1.0),
            ]
        })
        dm = SimpleDataManager(sources={"commuting_flows": source})
        config = self._make_strategy(outputs={"loc": "destination"})
        strategy = CommutingLikelihoodStrategy(config, dm)

        person = MinimalPerson(geographical_unit=MinimalGeoUnit("ORIGIN_A"))
        for _ in range(20):
            result = strategy.assign(person, MinimalVenue(), {"attribute_name": "loc"})
            assert result == "DEST_2"

    # --- Origin resolution ---

    def test_no_geographical_unit_triggers_fallback(self):
        """Person with no geo unit → fallback."""
        source = self._make_od_source({"ORIGIN_A": [("DEST_1", {}, 1.0)]})
        geo_source = SimpleGeoSource(fallback={"W": 1.0})
        dm = SimpleDataManager(sources={
            "commuting_flows": source,
            "geo_distribution": geo_source,
        })
        config = self._make_strategy(
            outputs={"loc": "destination"},
            fallback={"strategy": "constant", "value": "FB"},
        )
        strategy = CommutingLikelihoodStrategy(config, dm)

        person = MinimalPerson(geographical_unit=None)
        geo = MinimalGeoUnit("E00001234")
        context = {"attribute_name": "loc"}
        result = strategy.assign(person, MinimalVenue(geographical_unit=geo), context)
        # Should hit fallback because _resolve_origin_code returns None
        assert result == "FB"
        assert context.get("fallback_reason") == "COMMUTING_DATA_MISSING"

    def test_missing_data_source_triggers_fallback(self):
        """Data source not registered → fallback."""
        dm = SimpleDataManager(sources={"geo_distribution": SimpleGeoSource(fallback={"W": 1.0})})
        config = self._make_strategy(
            outputs={"loc": "destination"},
            fallback={"strategy": "constant", "value": "FB"},
        )
        strategy = CommutingLikelihoodStrategy(config, dm)

        person = MinimalPerson(geographical_unit=MinimalGeoUnit("ORIGIN_A"))
        geo = MinimalGeoUnit("E00001234")
        context = {"attribute_name": "loc"}
        result = strategy.assign(person, MinimalVenue(geographical_unit=geo), context)
        assert result == "FB"
        assert context.get("fallback_reason") == "COMMUTING_DATA_MISSING"

    def test_empty_destinations_triggers_fallback(self):
        """Origin exists but has no destinations → fallback."""
        source = self._make_od_source({"ORIGIN_A": []})
        geo_source = SimpleGeoSource(fallback={"W": 1.0})
        dm = SimpleDataManager(sources={
            "commuting_flows": source,
            "geo_distribution": geo_source,
        })
        config = self._make_strategy(
            outputs={"loc": "destination"},
            fallback={"strategy": "constant", "value": "FB"},
        )
        strategy = CommutingLikelihoodStrategy(config, dm)

        person = MinimalPerson(geographical_unit=MinimalGeoUnit("ORIGIN_A"))
        geo = MinimalGeoUnit("E00001234")
        context = {"attribute_name": "loc"}
        result = strategy.assign(person, MinimalVenue(geographical_unit=geo), context)
        assert result == "FB"
        assert context.get("fallback_reason") == "COMMUTING_DATA_MISSING"

    def test_unknown_origin_triggers_fallback(self):
        """Origin code not in O-D matrix → fallback."""
        source = self._make_od_source({"ORIGIN_A": [("DEST_1", {}, 1.0)]})
        geo_source = SimpleGeoSource(fallback={"W": 1.0})
        dm = SimpleDataManager(sources={
            "commuting_flows": source,
            "geo_distribution": geo_source,
        })
        config = self._make_strategy(
            outputs={"loc": "destination"},
            fallback={"strategy": "constant", "value": "FB"},
        )
        strategy = CommutingLikelihoodStrategy(config, dm)

        person = MinimalPerson(geographical_unit=MinimalGeoUnit("UNKNOWN"))
        geo = MinimalGeoUnit("E00001234")
        context = {"attribute_name": "loc"}
        result = strategy.assign(person, MinimalVenue(geographical_unit=geo), context)
        assert result == "FB"
        assert context.get("fallback_reason") == "COMMUTING_DATA_MISSING"

    # --- Batch mode ---

    def test_batch_groups_by_origin(self):
        """Batch should efficiently group people by origin and sample."""
        source = self._make_od_source({
            "ORIGIN_A": [("DEST_1", {}, 1.0)],
            "ORIGIN_B": [("DEST_2", {}, 1.0)],
        })
        dm = SimpleDataManager(sources={"commuting_flows": source})
        config = self._make_strategy(outputs={"loc": "destination"})
        strategy = CommutingLikelihoodStrategy(config, dm)

        p1 = MinimalPerson(geographical_unit=MinimalGeoUnit("ORIGIN_A"))
        p2 = MinimalPerson(geographical_unit=MinimalGeoUnit("ORIGIN_B"))
        p3 = MinimalPerson(geographical_unit=MinimalGeoUnit("ORIGIN_A"))

        results = strategy.assign_batch(
            [p1, p2, p3],
            [MinimalVenue()] * 3,
            [{"attribute_name": "loc"}] * 3,
        )
        assert results[0] == "DEST_1"
        assert results[1] == "DEST_2"
        assert results[2] == "DEST_1"

    def test_batch_no_geo_person_gets_none(self):
        """Person with no geo unit in batch → result is None."""
        source = self._make_od_source({"ORIGIN_A": [("DEST_1", {}, 1.0)]})
        dm = SimpleDataManager(sources={"commuting_flows": source})
        config = self._make_strategy(outputs={"loc": "destination"})
        strategy = CommutingLikelihoodStrategy(config, dm)

        p1 = MinimalPerson(geographical_unit=MinimalGeoUnit("ORIGIN_A"))
        p2 = MinimalPerson(geographical_unit=None)

        results = strategy.assign_batch(
            [p1, p2],
            [MinimalVenue()] * 2,
            [{"attribute_name": "loc"}] * 2,
        )
        assert results[0] == "DEST_1"
        assert results[1] is None  # no origin → skipped

    # ---- BUG DETECTION ----

    def test_metadata_key_missing_raises_valueerror(self):
        """
        If output_source is not 'destination' and not in metadata,
        _build_output raises ValueError — misconfigured outputs should
        fail loudly, not silently return the wrong data.
        """
        source = self._make_od_source({
            "ORIGIN_A": [("DEST_1", {"mode": "car"}, 1.0)]
        })
        dm = SimpleDataManager(sources={"commuting_flows": source})
        config = self._make_strategy(outputs={"result": "nonexistent_field"})
        strategy = CommutingLikelihoodStrategy(config, dm)

        person = MinimalPerson(geographical_unit=MinimalGeoUnit("ORIGIN_A"))
        with pytest.raises(ValueError, match="not found in metadata"):
            strategy.assign(person, MinimalVenue(), {"attribute_name": "result"})

    def test_multi_output_missing_metadata_key_raises_valueerror(self):
        """
        Missing metadata key in multi-output mode also raises ValueError.
        Both single and multi output are now consistent.
        """
        source = self._make_od_source({
            "ORIGIN_A": [("DEST_1", {"mode": "car"}, 1.0)]
        })
        dm = SimpleDataManager(sources={"commuting_flows": source})
        config = self._make_strategy(outputs={
            "workplace_location": "destination",
            "salary": "nonexistent_field",
        })
        strategy = CommutingLikelihoodStrategy(config, dm)

        person = MinimalPerson(geographical_unit=MinimalGeoUnit("ORIGIN_A"))
        with pytest.raises(ValueError, match="not found in metadata"):
            strategy.assign(person, MinimalVenue(), {"attribute_name": "workplace_location"})

    def test_empty_outputs_config_returns_empty_dict(self):
        """
        When outputs={} (empty), returns an empty dict.
        This is a valid (if unusual) configuration.
        """
        source = self._make_od_source({
            "ORIGIN_A": [("DEST_1", {"mode": "car"}, 1.0)]
        })
        dm = SimpleDataManager(sources={"commuting_flows": source})
        config = self._make_strategy(outputs={})
        strategy = CommutingLikelihoodStrategy(config, dm)

        person = MinimalPerson(geographical_unit=MinimalGeoUnit("ORIGIN_A"))
        result = strategy.assign(person, MinimalVenue(), {"attribute_name": "loc"})
        assert result == {}


# =============================================================================
# GUSamplerStrategy Tests
# =============================================================================

class TestGUSamplerStrategy:
    """
    Intended behaviour (strategies.py lines 918-1062):
    - Gets workplace_location from person.properties
    - Looks up GU distribution for that parent GU from data source
    - If no data for workplace GU, falls back to person's home LGU
    - Samples one GU weighted by distribution
    - Batch mode groups by (workplace_parent_gu, home_parent_gu)
    """

    def _make_strategy(self, data_source_name="gu_sampler"):
        config = {
            "strategy": "geographical_unit_sampler",
            "data_source": data_source_name,
        }
        return config

    # --- Basic sampling ---

    def test_samples_from_workplace_parent_gu(self):
        """Normal case: workplace_location exists in data source."""
        source = GUSamplerSource(lookup_data={
            "Manchester": {"SGU_1": 0.6, "SGU_2": 0.4}
        })
        dm = SimpleDataManager(sources={"gu_sampler": source})
        strategy = GUSamplerStrategy(self._make_strategy(), dm)

        person = MinimalPerson(properties={"workplace_location": "Manchester"})
        np.random.seed(42)
        result = strategy.assign(person, MinimalVenue(), {"attribute_name": "workplace_sgu"})
        assert result in {"SGU_1", "SGU_2"}

    def test_deterministic_sampling_single_gu(self):
        """Only one GU with probability 1.0 → always selected."""
        source = GUSamplerSource(lookup_data={
            "Manchester": {"SGU_ONLY": 1.0}
        })
        dm = SimpleDataManager(sources={"gu_sampler": source})
        strategy = GUSamplerStrategy(self._make_strategy(), dm)

        person = MinimalPerson(properties={"workplace_location": "Manchester"})
        for _ in range(10):
            result = strategy.assign(person, MinimalVenue(), {"attribute_name": "workplace_sgu"})
            assert result == "SGU_ONLY"

    # --- Fallback to home parent GU ---

    def test_falls_back_to_home_lgu_when_workplace_missing(self):
        """If workplace GU has no data, tries person's home LGU."""
        lgu = MinimalGeoUnit("Birmingham", level="LGU")
        sgu = MinimalGeoUnit("SGU_123", level="SGU", parent=lgu)

        source = GUSamplerSource(lookup_data={
            "Birmingham": {"SGU_HOME": 1.0}
            # "UnknownWorkplace" not in data
        })
        dm = SimpleDataManager(sources={"gu_sampler": source})
        strategy = GUSamplerStrategy(self._make_strategy(), dm)

        person = MinimalPerson(
            geographical_unit=sgu,
            properties={"workplace_location": "UnknownWorkplace"}
        )
        result = strategy.assign(person, MinimalVenue(), {"attribute_name": "workplace_sgu"})
        assert result == "SGU_HOME"

    def test_no_data_anywhere_returns_none(self):
        """Neither workplace nor home GU has data → None."""
        lgu = MinimalGeoUnit("Nowhere", level="LGU")
        sgu = MinimalGeoUnit("SGU_X", level="SGU", parent=lgu)

        source = GUSamplerSource(lookup_data={})  # empty
        dm = SimpleDataManager(sources={"gu_sampler": source})
        strategy = GUSamplerStrategy(self._make_strategy(), dm)

        person = MinimalPerson(
            geographical_unit=sgu,
            properties={"workplace_location": "Unknown"}
        )
        result = strategy.assign(person, MinimalVenue(), {"attribute_name": "workplace_sgu"})
        assert result is None

    # --- Missing prerequisites ---

    def test_no_workplace_location_returns_none(self):
        """Person without workplace_location property → None."""
        source = GUSamplerSource(lookup_data={"X": {"SGU_1": 1.0}})
        dm = SimpleDataManager(sources={"gu_sampler": source})
        strategy = GUSamplerStrategy(self._make_strategy(), dm)

        person = MinimalPerson(properties={})  # no workplace_location
        result = strategy.assign(person, MinimalVenue(), {"attribute_name": "workplace_sgu"})
        assert result is None

    def test_no_data_source_returns_none(self):
        dm = SimpleDataManager(sources={})
        strategy = GUSamplerStrategy(self._make_strategy(), dm)

        person = MinimalPerson(properties={"workplace_location": "Manchester"})
        result = strategy.assign(person, MinimalVenue(), {"attribute_name": "workplace_sgu"})
        assert result is None

    def test_no_lgu_ancestor_falls_through(self):
        """Person's geo unit has no LGU ancestor → can't fall back."""
        # SGU with no parent
        sgu = MinimalGeoUnit("SGU_ORPHAN", level="SGU", parent=None)

        source = GUSamplerSource(lookup_data={})  # no data for "UnknownWorkplace"
        dm = SimpleDataManager(sources={"gu_sampler": source})
        strategy = GUSamplerStrategy(self._make_strategy(), dm)

        person = MinimalPerson(
            geographical_unit=sgu,
            properties={"workplace_location": "UnknownWorkplace"}
        )
        result = strategy.assign(person, MinimalVenue(), {"attribute_name": "workplace_sgu"})
        assert result is None

    # --- Batch mode ---

    def test_batch_groups_by_workplace_gu(self):
        source = GUSamplerSource(lookup_data={
            "Manchester": {"SGU_1": 1.0},
            "Leeds": {"SGU_2": 1.0},
        })
        dm = SimpleDataManager(sources={"gu_sampler": source})
        strategy = GUSamplerStrategy(self._make_strategy(), dm)

        p1 = MinimalPerson(properties={"workplace_location": "Manchester"})
        p2 = MinimalPerson(properties={"workplace_location": "Leeds"})
        p3 = MinimalPerson(properties={"workplace_location": "Manchester"})

        results = strategy.assign_batch(
            [p1, p2, p3],
            [MinimalVenue()] * 3,
            [{"attribute_name": "sgu"}] * 3,
        )
        assert results[0] == "SGU_1"
        assert results[1] == "SGU_2"
        assert results[2] == "SGU_1"

    def test_batch_person_without_workplace_gets_none(self):
        """Person without workplace_location in batch → stays None."""
        source = GUSamplerSource(lookup_data={"Manchester": {"SGU_1": 1.0}})
        dm = SimpleDataManager(sources={"gu_sampler": source})
        strategy = GUSamplerStrategy(self._make_strategy(), dm)

        p1 = MinimalPerson(properties={"workplace_location": "Manchester"})
        p2 = MinimalPerson(properties={})  # no workplace

        results = strategy.assign_batch(
            [p1, p2],
            [MinimalVenue()] * 2,
            [{"attribute_name": "sgu"}] * 2,
        )
        assert results[0] == "SGU_1"
        assert results[1] is None

    # ---- BUG DETECTION ----

    def test_batch_fallback_to_home_gu(self):
        """
        Batch mode also has the workplace→home fallback logic.
        Verify it works identically to sequential mode.
        """
        lgu = MinimalGeoUnit("Birmingham", level="LGU")
        sgu = MinimalGeoUnit("SGU_123", level="SGU", parent=lgu)

        source = GUSamplerSource(lookup_data={
            "Birmingham": {"SGU_HOME": 1.0}
        })
        dm = SimpleDataManager(sources={"gu_sampler": source})
        strategy = GUSamplerStrategy(self._make_strategy(), dm)

        person = MinimalPerson(
            geographical_unit=sgu,
            properties={"workplace_location": "UnknownWorkplace"}
        )
        results = strategy.assign_batch(
            [person],
            [MinimalVenue()],
            [{"attribute_name": "sgu"}],
        )
        assert results[0] == "SGU_HOME"

    def test_no_data_source_batch_returns_all_none(self):
        dm = SimpleDataManager(sources={})
        strategy = GUSamplerStrategy(self._make_strategy(), dm)

        p1 = MinimalPerson(properties={"workplace_location": "Manchester"})
        results = strategy.assign_batch(
            [p1], [MinimalVenue()], [{"attribute_name": "sgu"}]
        )
        assert results == [None]


# =============================================================================
# CategoricalSamplerStrategy Tests
# =============================================================================

class TestCategoricalSamplerStrategy:
    """
    Intended behaviour (strategies.py lines 1063-1185):
    - Looks up per-person {category: probability} from data source
    - Samples exactly ONE category from that distribution
    - Normalizes if probabilities don't sum to 1.0
    - Returns None if total probabilities <= 0
    - Batch mode groups people with identical distributions
    """

    def _make_strategy(self, data_source_name="sector_probs"):
        config = {
            "strategy": "categorical_sampler",
            "data_source": data_source_name,
        }
        return config

    # --- Basic sampling ---

    def test_samples_one_category(self):
        """Normal case: samples from {category: prob} distribution."""
        source = MultiKeySource(return_value={"industry": 0.5, "services": 0.3, "tech": 0.2})
        dm = SimpleDataManager(sources={"sector_probs": source})
        strategy = CategoricalSamplerStrategy(self._make_strategy(), dm)

        np.random.seed(42)
        result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "sector"})
        assert result in {"industry", "services", "tech"}

    def test_deterministic_single_category(self):
        """Only one category with prob 1.0 → always selected."""
        source = MultiKeySource(return_value={"only_one": 1.0})
        dm = SimpleDataManager(sources={"sector_probs": source})
        strategy = CategoricalSamplerStrategy(self._make_strategy(), dm)

        for _ in range(10):
            result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "sector"})
            assert result == "only_one"

    # --- Normalization ---

    def test_unnormalized_probabilities_are_normalized(self):
        """Probabilities not summing to 1 → normalized before sampling."""
        source = MultiKeySource(return_value={"A": 3.0, "B": 7.0})
        dm = SimpleDataManager(sources={"sector_probs": source})
        strategy = CategoricalSamplerStrategy(self._make_strategy(), dm)

        np.random.seed(42)
        result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "sector"})
        assert result in {"A", "B"}

    def test_zero_total_returns_none(self):
        """All probabilities 0 → total=0 → None."""
        source = MultiKeySource(return_value={"A": 0.0, "B": 0.0})
        dm = SimpleDataManager(sources={"sector_probs": source})
        strategy = CategoricalSamplerStrategy(self._make_strategy(), dm)

        result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "sector"})
        assert result is None

    # --- Missing data ---

    def test_missing_data_source_returns_none(self):
        dm = SimpleDataManager(sources={})
        strategy = CategoricalSamplerStrategy(self._make_strategy(), dm)

        result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "sector"})
        assert result is None

    def test_empty_probabilities_returns_none(self):
        source = MultiKeySource(return_value={})
        dm = SimpleDataManager(sources={"sector_probs": source})
        strategy = CategoricalSamplerStrategy(self._make_strategy(), dm)

        result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "sector"})
        assert result is None

    # --- Batch mode ---

    def test_batch_assigns_all_people(self):
        source = MultiKeySource(return_value={"only_one": 1.0})
        dm = SimpleDataManager(sources={"sector_probs": source})
        strategy = CategoricalSamplerStrategy(self._make_strategy(), dm)

        people = [MinimalPerson() for _ in range(5)]
        results = strategy.assign_batch(
            people,
            [MinimalVenue()] * 5,
            [{"attribute_name": "sector"}] * 5,
        )
        assert results == ["only_one"] * 5

    def test_batch_empty_data_source_returns_all_none(self):
        dm = SimpleDataManager(sources={})
        strategy = CategoricalSamplerStrategy(self._make_strategy(), dm)

        people = [MinimalPerson() for _ in range(3)]
        results = strategy.assign_batch(
            people,
            [MinimalVenue()] * 3,
            [{"attribute_name": "sector"}] * 3,
        )
        assert results == [None, None, None]

    def test_batch_groups_identical_distributions(self):
        """People with same distribution should be grouped and batch-sampled."""
        source = MultiKeySource(return_value={"X": 1.0})
        dm = SimpleDataManager(sources={"sector_probs": source})
        strategy = CategoricalSamplerStrategy(self._make_strategy(), dm)

        people = [MinimalPerson() for _ in range(10)]
        results = strategy.assign_batch(
            people,
            [MinimalVenue()] * 10,
            [{"attribute_name": "sector"}] * 10,
        )
        assert all(r == "X" for r in results)

    def test_batch_zero_total_skipped(self):
        """Batch: people with all-zero probabilities get None."""
        source = MultiKeySource(return_value={"A": 0.0, "B": 0.0})
        dm = SimpleDataManager(sources={"sector_probs": source})
        strategy = CategoricalSamplerStrategy(self._make_strategy(), dm)

        people = [MinimalPerson() for _ in range(3)]
        results = strategy.assign_batch(
            people,
            [MinimalVenue()] * 3,
            [{"attribute_name": "sector"}] * 3,
        )
        assert results == [None, None, None]

    # ---- BUG DETECTION ----

    def test_negative_probabilities_clamped_to_zero(self):
        """
        Negative probabilities are clamped to 0 before sampling.
        {A: -1, B: 3} → clamp → {A: 0, B: 3} → normalize → {A: 0, B: 1} → always B.
        """
        source = MultiKeySource(return_value={"A": -1.0, "B": 3.0})
        dm = SimpleDataManager(sources={"sector_probs": source})
        strategy = CategoricalSamplerStrategy(self._make_strategy(), dm)

        result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "sector"})
        assert result == "B"

    def test_always_normalizes_regardless_of_tolerance(self):
        """
        Probabilities are always normalized, even if they're close to 1.0.
        This avoids numpy tolerance issues.
        """
        # Sum = 0.995 — previously would NOT be re-normalized (1% tolerance)
        source = MultiKeySource(return_value={"A": 0.5, "B": 0.495})
        dm = SimpleDataManager(sources={"sector_probs": source})
        strategy = CategoricalSamplerStrategy(self._make_strategy(), dm)

        # Should always work now
        result = strategy.assign(MinimalPerson(), MinimalVenue(), {"attribute_name": "sector"})
        assert result in {"A", "B"}

    def test_no_fallback_mechanism(self):
        """
        Unlike ProbabilisticStrategy/PartnershipStrategy which call self._fallback(),
        CategoricalSamplerStrategy returns None directly when data is missing.
        This means no fallback_reason is recorded in context and no geo_distribution
        fallback is attempted.
        """
        dm = SimpleDataManager(sources={})
        strategy = CategoricalSamplerStrategy(self._make_strategy(), dm)

        context = {"attribute_name": "sector"}
        result = strategy.assign(MinimalPerson(), MinimalVenue(), context)
        assert result is None
        assert "fallback_reason" not in context  # no fallback mechanism


# =============================================================================
# StrategyFactory — Complete Registration Tests
# =============================================================================

class TestStrategyFactoryComplete:
    """All 9 strategy types must be registered and instantiable."""

    def test_all_nine_strategies_registered(self):
        dm = SimpleDataManager()
        all_types = [
            ("probabilistic", ProbabilisticStrategy),
            ("partnership", PartnershipStrategy),
            ("inheritance", InheritanceStrategy),
            ("reverse_inheritance", ReverseInheritanceStrategy),
            ("probabilistic_conditions", ProbabilisticConditionsStrategy),
            ("commuting_likelihood", CommutingLikelihoodStrategy),
            ("geographical_unit_sampler", GUSamplerStrategy),
            ("categorical_sampler", CategoricalSamplerStrategy),
            ("constant", ConstantStrategy),
        ]
        for strategy_type, expected_class in all_types:
            instance = StrategyFactory.create_strategy({"strategy": strategy_type}, dm)
            assert isinstance(instance, expected_class), (
                f"Expected {expected_class.__name__} for '{strategy_type}', "
                f"got {type(instance).__name__}"
            )

    def test_strategy_map_has_exactly_nine_entries(self):
        """Guard against accidentally removing a strategy registration."""
        assert len(StrategyFactory._strategy_map) == 9


# =============================================================================
# ConstantStrategy batch — Bug Detection
# =============================================================================

class TestConstantStrategyBatchConsistency:
    """
    ConstantStrategy.assign_batch() now delegates to assign() when value is None,
    matching the sequential fallback behavior.
    """

    def test_batch_with_no_value_triggers_fallback_like_assign(self):
        """
        Both assign() and assign_batch() should trigger the configured
        fallback when value is None.
        """
        config = {
            "strategy": "constant",  # no 'value' key → self.value = None
            "fallback": {"strategy": "constant", "value": "W"},
        }
        strategy = ConstantStrategy(config, SimpleDataManager())

        geo = MinimalGeoUnit("E00001234")

        # Sequential: triggers fallback
        ctx_seq = {"attribute_name": "attr"}
        result_seq = strategy.assign(
            MinimalPerson(geographical_unit=geo),
            MinimalVenue(geographical_unit=geo),
            ctx_seq,
        )
        assert result_seq == "W"
        assert ctx_seq.get("fallback_reason") == "NO_CONSTANT_VALUE"

        # Batch: now also triggers fallback (consistent with assign)
        people = [MinimalPerson(geographical_unit=geo) for _ in range(3)]
        venues = [MinimalVenue(geographical_unit=geo) for _ in range(3)]
        contexts = [{"attribute_name": "attr"} for _ in range(3)]
        results_batch = strategy.assign_batch(people, venues, contexts)
        assert results_batch == ["W", "W", "W"]
        assert all(ctx.get("fallback_reason") == "NO_CONSTANT_VALUE" for ctx in contexts)
