"""
Contract tests for the *loader* surface of RelationshipRulesValidator —
the methods exercised by the `relationship_rules` log lines in production:

    Loaded 8 relationship rules
    Loaded same_category_source[sex]: 6856 MGU entries from <csv>

Existing tests cover the validator's *runtime* behaviour (validate_*,
select_pair). This file pins down config loading, per-area source loading,
and probability resolution. Each test names a single contract.
"""

import logging
import os

import pytest

from may.geography import Geography, GeographicalUnit
from may.residence.relationship_rules import RelationshipRulesValidator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_two_level_geo():
    """SGU children under MGU parents, with parent links wired so
    get_ancestor_by_level('MGU') resolves from a child SGU."""
    geo = Geography(levels=['SGU', 'MGU'])
    geo.units = {}
    geo.units_by_level = {'SGU': {}, 'MGU': {}}
    next_id = 0
    for name in ('M_a', 'M_b'):
        u = GeographicalUnit(id=next_id, name=name, level='MGU')
        next_id += 1
        geo.units[name] = u
        geo.units_by_level['MGU'][name] = u
        geo.units_by_id[u.id] = u
    for name, parent in (('S1', 'M_a'), ('S2', 'M_a'), ('S3', 'M_b')):
        u = GeographicalUnit(id=next_id, name=name, level='SGU')
        next_id += 1
        geo.units[name] = u
        geo.units_by_level['SGU'][name] = u
        geo.units_by_id[u.id] = u
        geo.units_by_level['MGU'][parent].add_child(u)
    return geo


@pytest.fixture
def two_level_geo():
    return _make_two_level_geo()


def _write_yaml(tmp_path, body):
    path = tmp_path / "rules.yaml"
    path.write_text(body)
    return str(path)


# ===========================================================================
# _load_config — the "Loaded N relationship rules" log line
# ===========================================================================

class TestLoadConfig:

    def test_missing_config_file_disables_rules(self, tmp_path, caplog):
        """Production guards against a missing rules file by logging and
        leaving the validator disabled — never crashing world creation."""
        with caplog.at_level(logging.WARNING, logger='relationship_rules'):
            v = RelationshipRulesValidator(
                categories=[],
                config_file=str(tmp_path / "does_not_exist.yaml"),
            )
        assert v.enabled is False
        assert v.rules == []
        assert any('not found' in r.message for r in caplog.records)
        assert any('disabled' in r.message for r in caplog.records)

    def test_empty_yaml_yields_disabled_validator(self, tmp_path):
        """An empty YAML body parses to None — must not crash, must leave
        the validator disabled with no rules."""
        path = _write_yaml(tmp_path, "")
        v = RelationshipRulesValidator(categories=[], config_file=path)
        # _load_config is only invoked when the file exists; an empty file
        # produces config=None so the validator stays at its default
        # (enabled=False, no rules). Any crash here would short-circuit the
        # production world creation flow.
        assert v.enabled is False
        assert v.rules == []

    def test_rule_count_matches_yaml(self, tmp_path, caplog):
        """The 'Loaded N relationship rules' log line and self.rules length
        must equal the number of rules in YAML."""
        path = _write_yaml(tmp_path, """
enabled: true
rules:
  - name: "R1"
    patterns: ["1 0 1 0"]
    roles: {role_A: {categories: ["Adults"], count: 1}}
    selection_order: [role_A]
    constraints: []
  - name: "R2"
    patterns: ["0 0 2 0"]
    roles: {role_A: {categories: ["Adults"], count: 2}}
    selection_order: [role_A]
    constraints: []
  - name: "R3"
    patterns: ["1 0 0 0"]
    roles: {role_A: {categories: ["Kids"], count: 1}}
    selection_order: [role_A]
    constraints: []
""")
        with caplog.at_level(logging.INFO, logger='relationship_rules'):
            v = RelationshipRulesValidator(categories=[], config_file=path)
        assert v.enabled is True
        assert [r.name for r in v.rules] == ['R1', 'R2', 'R3']
        assert any('Loaded 3 relationship rules' in r.message
                   for r in caplog.records)

    def test_get_rule_by_name_round_trip(self, tmp_path):
        path = _write_yaml(tmp_path, """
enabled: true
rules:
  - {name: "Adult pair", patterns: ["0 0 2 0"], roles: {a: {categories: [Adults], count: 2}}, selection_order: [a], constraints: []}
""")
        v = RelationshipRulesValidator(categories=[], config_file=path)
        assert v.get_rule_by_name('Adult pair') is not None
        assert v.get_rule_by_name('Nonexistent') is None

    def test_disabled_validator_returns_none_from_lookups(self, tmp_path):
        """When `enabled: false`, a name lookup may not surface a rule —
        even if the rules block parses cleanly."""
        path = _write_yaml(tmp_path, """
enabled: false
rules:
  - {name: "R", roles: {a: {categories: [Kids], count: 1}}, selection_order: [a], constraints: []}
""")
        v = RelationshipRulesValidator(categories=[], config_file=path)
        assert v.enabled is False
        assert v.get_rule_by_name('R') is None

    def test_legacy_patterns_field_is_ignored(self, tmp_path):
        """Older configs may still carry a per-rule `patterns:` list. It is
        vestigial — rules resolve by name only — so the loader must ignore it
        and never expose it on the RelationshipRule."""
        path = _write_yaml(tmp_path, """
enabled: true
rules:
  - {name: "R", patterns: ["1 0 0 0", ">=2 >=0 2 0"], roles: {a: {categories: [Kids], count: 1}}, selection_order: [a], constraints: []}
""")
        v = RelationshipRulesValidator(categories=[], config_file=path)
        rule = v.get_rule_by_name('R')
        assert rule is not None
        assert not hasattr(rule, 'patterns')


# ===========================================================================
# _load_same_category_source — the "Loaded same_category_source[sex]: ..."
# log line. Source is a per-area CSV producing P(same-category pair).
# ===========================================================================

class TestLoadSameCategorySource:

    def _config_for_source(self, attribute, csv_path, **overrides):
        """Build a minimal YAML body with one same_category_source."""
        formula = overrides.pop('formula', "[{column: a, weight: 0.5}, {column: b, weight: 0.5}]")
        geo_level = overrides.pop('geo_level', 'MGU')
        geo_code_column = overrides.pop('geo_code_column', 'geo_unit')
        return f"""
enabled: true
rules: []
same_category_source:
  attribute: {attribute}
  csv_path: {csv_path}
  geo_code_column: {geo_code_column}
  geo_level: {geo_level}
  formula: {formula}
"""

    def test_happy_path_loads_per_area_dict_and_logs_count(
        self, two_level_geo, tmp_path, caplog
    ):
        csv = tmp_path / "src.csv"
        csv.write_text("geo_unit,a,b\nM_a,0.4,0.4\nM_b,0.0,0.0\n")
        rules_path = _write_yaml(
            tmp_path, self._config_for_source('sex', str(csv))
        )
        with caplog.at_level(logging.INFO, logger='relationship_rules'):
            v = RelationshipRulesValidator(
                categories=[], config_file=rules_path, geography=two_level_geo
            )
        # Table is keyed by area code at the configured level.
        assert 'sex' in v._same_category_sources
        src = v._same_category_sources['sex']
        assert src['geo_level'] == 'MGU'
        # (0.4 * 0.5) + (0.4 * 0.5) = 0.4 ; (0 + 0) = 0.0
        assert src['by_code']['M_a'] == pytest.approx(0.4)
        assert src['by_code']['M_b'] == pytest.approx(0.0)
        # The "Loaded same_category_source[<attr>]: N MGU entries" line —
        # this is what the production log emits, and operators rely on it.
        assert any(
            'same_category_source[sex]' in r.message
            and '2 MGU entries' in r.message
            for r in caplog.records
        )

    def test_invalid_geo_level_fails_loud(self, two_level_geo, tmp_path):
        """A geo_level that isn't a configured geography level must raise —
        an unmatched level otherwise silently degrades to the scalar fallback
        for every person (adr/0002)."""
        csv = tmp_path / "src.csv"
        csv.write_text("geo_unit,a\nM_a,0.5\n")
        rules_path = _write_yaml(tmp_path, self._config_for_source(
            'sex', str(csv), geo_level='NOT_A_LEVEL'
        ))
        with pytest.raises(ValueError, match="not a configured geography level"):
            RelationshipRulesValidator(
                categories=[], config_file=rules_path, geography=two_level_geo
            )

    def test_probabilities_clamped_to_unit_interval(self, two_level_geo, tmp_path):
        """Formulas can overflow if weights and inputs are mis-specified.
        The loader must clamp to [0, 1] so downstream `np.random.random() < p`
        sampling stays well-defined."""
        csv = tmp_path / "src.csv"
        # 5.0 → clamps to 1.0 ; -2.0 → clamps to 0.0
        csv.write_text("geo_unit,a\nM_a,5.0\nM_b,-2.0\n")
        rules_path = _write_yaml(tmp_path, self._config_for_source(
            'sex', str(csv), formula="[{column: a, weight: 1.0}]"
        ))
        v = RelationshipRulesValidator(
            categories=[], config_file=rules_path, geography=two_level_geo
        )
        assert v._same_category_sources['sex']['by_code']['M_a'] == 1.0
        assert v._same_category_sources['sex']['by_code']['M_b'] == 0.0

    def test_missing_attribute_field_skips_with_warning(
        self, two_level_geo, tmp_path, caplog
    ):
        """A source block missing 'attribute' is unusable — warn + skip,
        never crash. The rest of the config must still load."""
        csv = tmp_path / "src.csv"
        csv.write_text("geo_unit,a\nM_a,0.5\n")
        rules_path = _write_yaml(tmp_path, f"""
enabled: true
rules: []
same_category_source:
  csv_path: {csv}
  geo_code_column: geo_unit
  geo_level: MGU
  formula: [{{column: a, weight: 1.0}}]
""")
        with caplog.at_level(logging.WARNING, logger='relationship_rules'):
            v = RelationshipRulesValidator(
                categories=[], config_file=rules_path, geography=two_level_geo
            )
        assert v._same_category_sources == {}
        assert any("missing required 'attribute'" in r.message
                   for r in caplog.records)

    def test_missing_csv_path_skips_with_warning(self, two_level_geo, tmp_path, caplog):
        rules_path = _write_yaml(tmp_path, """
enabled: true
rules: []
same_category_source:
  attribute: sex
  csv_path: /path/that/does/not/exist.csv
  geo_code_column: geo_unit
  geo_level: MGU
  formula: [{column: a, weight: 1.0}]
""")
        with caplog.at_level(logging.WARNING, logger='relationship_rules'):
            v = RelationshipRulesValidator(
                categories=[], config_file=rules_path, geography=two_level_geo
            )
        assert v._same_category_sources == {}
        assert any('csv_path missing or not found' in r.message
                   for r in caplog.records)

    def test_empty_formula_skips_with_warning(self, two_level_geo, tmp_path, caplog):
        csv = tmp_path / "src.csv"
        csv.write_text("geo_unit,a\nM_a,0.5\n")
        rules_path = _write_yaml(tmp_path, f"""
enabled: true
rules: []
same_category_source:
  attribute: sex
  csv_path: {csv}
  geo_code_column: geo_unit
  geo_level: MGU
  formula: []
""")
        with caplog.at_level(logging.WARNING, logger='relationship_rules'):
            v = RelationshipRulesValidator(
                categories=[], config_file=rules_path, geography=two_level_geo
            )
        assert v._same_category_sources == {}
        assert any('no formula' in r.message for r in caplog.records)

    def test_list_form_loads_multiple_sources(self, two_level_geo, tmp_path):
        """The loader supports both `same_category_source` (singular,
        terse) and `same_category_sources` (plural list). Both must work."""
        csv1 = tmp_path / "sex.csv"
        csv1.write_text("geo_unit,a\nM_a,0.3\nM_b,0.7\n")
        csv2 = tmp_path / "religion.csv"
        csv2.write_text("geo_unit,a\nM_a,0.1\nM_b,0.9\n")
        rules_path = _write_yaml(tmp_path, f"""
enabled: true
rules: []
same_category_sources:
  - attribute: sex
    csv_path: {csv1}
    geo_code_column: geo_unit
    geo_level: MGU
    formula: [{{column: a, weight: 1.0}}]
  - attribute: religion
    csv_path: {csv2}
    geo_code_column: geo_unit
    geo_level: MGU
    formula: [{{column: a, weight: 1.0}}]
""")
        v = RelationshipRulesValidator(
            categories=[], config_file=rules_path, geography=two_level_geo
        )
        assert set(v._same_category_sources.keys()) == {'sex', 'religion'}
        assert v._same_category_sources['sex']['by_code']['M_a'] == pytest.approx(0.3)
        assert v._same_category_sources['religion']['by_code']['M_b'] == pytest.approx(0.9)


# ===========================================================================
# _resolve_same_category_prob — fallback semantics
# ===========================================================================

class TestResolveSameCategoryProb:

    @pytest.fixture
    def validator_with_source(self, two_level_geo, tmp_path):
        csv = tmp_path / "src.csv"
        csv.write_text("geo_unit,a\nM_a,0.42\n")  # M_b deliberately absent
        rules_path = _write_yaml(tmp_path, f"""
enabled: true
rules: []
same_category_source:
  attribute: sex
  csv_path: {csv}
  geo_code_column: geo_unit
  geo_level: MGU
  formula: [{{column: a, weight: 1.0}}]
""")
        return RelationshipRulesValidator(
            categories=[], config_file=rules_path, geography=two_level_geo
        )

    def test_resolves_via_parent_level(self, validator_with_source):
        """A person living in S1 (under M_a) must inherit M_a's value."""
        p = validator_with_source._resolve_same_category_prob(
            'sex', geo_unit_code='S1', default=0.99
        )
        assert p == pytest.approx(0.42)

    def test_unknown_attribute_returns_default(self, validator_with_source):
        """Any attribute without a source falls back to the scalar default."""
        p = validator_with_source._resolve_same_category_prob(
            'income', geo_unit_code='S1', default=0.05
        )
        assert p == 0.05

    def test_missing_geo_unit_code_returns_default(self, validator_with_source):
        p = validator_with_source._resolve_same_category_prob(
            'sex', geo_unit_code=None, default=0.05
        )
        assert p == 0.05

    def test_unknown_geo_unit_code_returns_default(self, validator_with_source):
        p = validator_with_source._resolve_same_category_prob(
            'sex', geo_unit_code='NOT_A_REAL_SGU', default=0.05
        )
        assert p == 0.05

    def test_known_geo_unit_with_no_csv_row_returns_default(
        self, validator_with_source
    ):
        """S3 lives under M_b, but M_b is intentionally absent from the CSV.
        The validator must surface the scalar fallback rather than KeyError."""
        p = validator_with_source._resolve_same_category_prob(
            'sex', geo_unit_code='S3', default=0.05
        )
        assert p == 0.05

    def test_no_geography_object_returns_default(self, tmp_path):
        """If the validator was constructed without a Geography (e.g. legacy
        code paths), every lookup must return the scalar default — not crash."""
        csv = tmp_path / "src.csv"
        csv.write_text("geo_unit,a\nM_a,0.42\n")
        rules_path = _write_yaml(tmp_path, f"""
enabled: true
rules: []
same_category_source:
  attribute: sex
  csv_path: {csv}
  geo_code_column: geo_unit
  geo_level: MGU
  formula: [{{column: a, weight: 1.0}}]
""")
        v = RelationshipRulesValidator(
            categories=[], config_file=rules_path, geography=None
        )
        assert v._resolve_same_category_prob('sex', 'M_a', default=0.05) == 0.05
