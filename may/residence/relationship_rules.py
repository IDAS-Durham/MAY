"""
Relationship rules for household composition.

This module handles generic demographic and attribute-based constraints for households:
- Numerical attribute differences between roles (e.g., age, income, education level)
- Couple matching with configurable categorical and numerical attributes
- Smart person selection with best-candidate fallback

The system is fully generic and works with:
- Any age categories defined in households_config.yaml
- Any numerical attributes (age, income, education years, etc.)
- Any categorical attributes (sex, religion, occupation, etc.)

No hardcoded assumptions about specific attributes - everything is configurable and pattern-based.
"""

import os
import logging
import yaml
import operator
import numpy as np
from operator import attrgetter
from collections import defaultdict
from itertools import islice
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass

from may.population.person import Person
from may.utils.attribute_access import get_person_attribute

logger = logging.getLogger("relationship_rules")


@dataclass
class RelationshipRule:
    """A relationship rule, resolved by name from allocation steps.

    Rules are looked up via `get_rule_by_name` (allocation steps reference
    them by `rule:`); they do not carry their own pattern list. Which
    patterns a rule runs on is owned entirely by the allocation step
    (`patterns:` / `target_patterns:`), the single source of truth.
    """
    name: str
    roles: Dict[str, Dict]  # role_name -> {categories: [...], count: ...}
    selection_order: List[str]
    constraints: List[Dict]


class RelationshipRulesValidator:
    """
    Validates and enforces relationship rules during household allocation.

    This class implements smart person selection that:
    1. Selects people according to role selection order
    2. Validates age difference constraints between roles
    3. Applies couple matching for romantic partners
    4. Falls back to "best candidate" if no perfect match exists
    """

    def __init__(self,
                 categories: List,
                 config_file: str = "data/households/relationship_rules.yaml",
                 geography=None):
        """
        Initialize relationship rules validator.

        Args:
            categories: List of Category objects from household config
            config_file: Path to relationship rules YAML configuration
            geography: Optional Geography object (needed for per-MSOA same_category lookups)
        """
        self.categories = categories
        self.category_name_to_idx = {cat.name: idx for idx, cat in enumerate(categories)}
        self.geography = geography

        # Load configuration
        self.enabled = False
        self.rules = []
        self.selection_strategy = {}
        self.track_statistics = False
        # Per-categorical-attribute lookup tables for `same_category_probability`.
        # Schema: {attribute_name: {"geo_level": <str>, "by_code": {area_code: prob}}}
        self._same_category_sources: Dict[str, Dict] = {}

        if os.path.exists(config_file):
            self._load_config(config_file)
        else:
            logger.warning(f"Relationship rules config not found: {config_file}")
            logger.warning("Relationship rules disabled")

        # Statistics tracking
        self.stats = {
            'best_candidate_selections': 0,
            'same_category_pairs': 0,
            'different_category_pairs': 0,
            'numerical_attribute_differences': [],
            'violations': {
                'numerical_attribute_difference': 0,
                'pair_numerical_attribute_diff': 0
            },
            # Per-attribute breakdown of how the same_category_probability was
            # resolved during pair_matching. Keys are the categorical_attribute
            # name (e.g. "sex"); each entry tracks how often the per-area
            # source was used vs the YAML scalar fallback, and the empirical
            # distribution of probabilities the validator actually rolled against.
            'same_category_lookup': {},
        }

    def _load_config(self, config_file: str):
        """Load configuration from YAML file."""
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)

        # An empty YAML body parses to None. Treat it the same as a missing
        # file: leave the validator disabled with no rules, rather than
        # crashing world creation with AttributeError.
        if config is None:
            logger.warning(f"Empty relationship rules config: {config_file}")
            logger.warning("Relationship rules disabled")
            return

        self.enabled = config.get('enabled', False)
        self.selection_strategy = config.get('selection_strategy', {})
        self.track_statistics = config.get('track_statistics', False)

        # Parse rules
        for rule_config in config.get('rules', []):
            # A rule's `patterns:` list (if present in older configs) is
            # intentionally ignored: it is redundant with the allocation
            # step's own patterns and is no longer read anywhere.
            rule = RelationshipRule(
                name=rule_config.get('name', 'Unnamed rule'),
                roles=rule_config.get('roles', {}),
                selection_order=rule_config.get('selection_order', []),
                constraints=rule_config.get('constraints', [])
            )
            self.rules.append(rule)

        logger.info(f"Loaded {len(self.rules)} relationship rules")

        # Accept either a single source ("same_category_source") or a list of
        # them ("same_category_sources") so simple cases stay terse.
        sources = config.get('same_category_sources')
        if sources is None and 'same_category_source' in config:
            sources = [config['same_category_source']]
        if sources:
            for source in sources:
                self._load_same_category_source(source)

    def _load_same_category_source(self, source: Dict):
        """Load a per-area `same_category_probability` table for one categorical attribute.

        Expected schema (see yaml/households/relationship_rules.yaml for an example):

            attribute:        <name of the categorical attribute, e.g. "sex">
            csv_path:         <path to a CSV with one row per area>
            geo_code_column:  <column in the CSV holding the area code>
            geo_level:        <Geography level name, e.g. "MGU">
            formula:          <list of {column, weight} pairs; P = Σ col * weight>

        The result is clamped to [0, 1] and stored in self._same_category_sources
        keyed by attribute. A pair_matching rule whose `categorical_attribute.attribute`
        matches will then use the per-area value instead of its scalar fallback.
        """
        attribute = source.get('attribute')
        path = source.get('csv_path')
        if not attribute:
            logger.warning("same_category_source missing required 'attribute'; skipped")
            return
        if not path or not os.path.exists(path):
            logger.warning(f"same_category_source[{attribute}] csv_path missing or not found: {path}; skipped")
            return

        geo_code_column = source.get('geo_code_column', 'geo_unit')
        geo_level = source.get('geo_level', 'MGU')
        formula = source.get('formula') or []
        if not formula:
            logger.warning(f"same_category_source[{attribute}] has no formula; skipped")
            return

        terms = []
        for term in formula:
            col = term.get('column')
            weight = float(term.get('weight', 1.0))
            if col is None:
                logger.warning(f"same_category_source[{attribute}] formula term missing 'column'; skipped term")
                continue
            terms.append((col, weight))
        if not terms:
            logger.warning(f"same_category_source[{attribute}] formula has no valid terms; skipped")
            return

        import csv as _csv
        by_code: Dict[str, float] = {}
        with open(path) as f:
            reader = _csv.DictReader(f)
            for row in reader:
                code = row[geo_code_column].strip()
                p = sum(float(row[col]) * w for col, w in terms)
                by_code[code] = max(0.0, min(1.0, p))

        self._same_category_sources[attribute] = {
            "geo_level": geo_level,
            "by_code": by_code,
        }

        logger.info(
            f"Loaded same_category_source[{attribute}]: {len(by_code)} {geo_level} "
            f"entries from {path}"
        )

    def _resolve_same_category_prob(self,
                                     attribute: str,
                                     geo_unit_code: Optional[str],
                                     default: float) -> float:
        """Look up the per-area P(same-category pair) for a person's home geography.

        Walks from the candidate's home unit up to the configured geo_level for
        this attribute's source, and returns the loaded probability. Falls back
        to ``default`` whenever the source isn't configured, the geography object
        is missing, or the area is not in the CSV.
        """
        source = self._same_category_sources.get(attribute)
        if source is None or not geo_unit_code or self.geography is None:
            return default
        unit = self.geography.get_unit(geo_unit_code)
        if unit is None:
            return default
        ancestor = unit.get_ancestor_by_level(source["geo_level"])
        if ancestor is None:
            return default
        return source["by_code"].get(ancestor.name, default)

    def get_rule_by_name(self, rule_name: str) -> Optional[RelationshipRule]:
        """
        Get relationship rule by name.

        Args:
            rule_name: Name of the rule (e.g., "Two-adult family with kids")

        Returns:
            RelationshipRule or None if rule not found
        """
        if not self.enabled:
            return None

        for rule in self.rules:
            if rule.name == rule_name:
                return rule

        return None

    def _get_attribute_getter(self, attribute: str) -> Callable[[Person], Any]:
        """
        Create an efficient attribute getter for Person objects.
        
        Args:
            attribute: Name of the attribute to get
            
        Returns:
            Callable that takes a Person and returns the attribute value
        """
        if attribute == 'age':
            return lambda p: p.age
        elif attribute == 'sex':
            return lambda p: p.sex
        elif attribute in Person.__slots__:
            return attrgetter(attribute)
        else:
            # Fallback to shared utility (handles dot-notation, properties, residence)
            return lambda p: get_person_attribute(p, attribute)

    def validate_composition(self, composition: Dict[str, int], constraints: List[Dict]) -> Tuple[bool, Optional[str]]:
        """
        Validate a household composition against a set of constraints.

        This unifies the validation logic previously scattered across classes.

        Args:
            composition: Dict of category_name -> count
            constraints: List of constraint dicts (category_sum, category, household_size)

        Returns:
            Tuple of (is_valid, error_message)
        """
        for constraint in constraints:
            # Category sum constraint
            if 'category_sum' in constraint:
                categories = constraint['category_sum']
                max_sum = constraint.get('max')

                if max_sum is not None:
                    current_sum = sum(composition.get(cat, 0) for cat in categories)
                    if current_sum > max_sum:
                        return False, f"Constraint violated: sum({categories}) = {current_sum} > {max_sum}"

            # Single category constraint
            elif 'category' in constraint:
                category = constraint['category']
                max_count = constraint.get('max')

                if max_count is not None:
                    current_count = composition.get(category, 0)
                    if current_count > max_count:
                        return False, f"Constraint violated: {category} = {current_count} > {max_count}"

            # Household size constraint
            elif 'household_size' in constraint:
                max_size = constraint.get('max')

                if max_size is not None:
                    current_size = sum(composition.values())
                    if current_size > max_size:
                        return False, f"Constraint violated: household size = {current_size} > {max_size}"

        return True, None

    def validate_numerical_attribute_difference_constraint(self,
                                          candidate: Person,
                                          other_people: List[Person],
                                          constraint: Dict,
                                          log_rejection: bool = False,
                                          cached_values: Optional[Dict] = None,
                                          is_role_1: bool = True) -> Tuple[bool, float]:
        """
        Validate numerical attribute difference constraint between candidate and other_people.

        Constraint format:
          - attribute: name of numerical attribute to compare (e.g., "age", "income")
          - role_1: first role
          - role_2: second role
          - min_difference: min(role_1[attribute] - role_2[attribute])
          - max_difference: max(role_1[attribute] - role_2[attribute])

        Args:
            candidate: Person being validated
            other_people: List of people from the other role
            constraint: Constraint dict
            log_rejection: If True, log when validation fails (for debugging)
            cached_values: Optional dict with pre-computed min/max values (for performance)
            is_role_1: True if candidate is role_1, False if candidate is role_2

        Returns:
            Tuple of (is_valid, penalty_score)
        """
        if not other_people:
            return (True, 0.0)

        attribute = constraint.get('attribute', 'age')  # Default to 'age' for backward compatibility
        min_diff = constraint.get('min_difference', 0)
        max_diff = constraint.get('max_difference', 100)

        # Override max based on categorical attribute if specified.
        #
        # `max_difference_by_categorical_attribute` raises/lowers max_diff based
        # on a categorical value (e.g. a father may be up to 50y older than a
        # child, a mother 45y). By default that value is read off the *candidate*.
        # That is correct at creation (selection_order makes the parent the
        # candidate) but wrong on the household_excess path, where the candidate
        # is the person being *added* — adding a Kid would silently key the
        # father/mother cap onto the child's sex.
        #
        # `categorical_from: <role>` lets the rule pin the override to a specific
        # role. When it names the *other* role (the existing members), the cap is
        # per-member, so other_people cannot be collapsed to a bare min/max — we
        # evaluate each member individually below. When it names the candidate's
        # own role, or is absent, behaviour is identical to before.
        max_diff_by_cat = constraint.get('max_difference_by_categorical_attribute', {})
        getter = self._get_attribute_getter(attribute)

        cat_from = constraint.get('categorical_from')
        candidate_role = constraint.get('role_1') if is_role_1 else constraint.get('role_2')
        other_role = constraint.get('role_2') if is_role_1 else constraint.get('role_1')
        cat_keyed_on_other = (
            bool(max_diff_by_cat)
            and cat_from is not None
            and cat_from == other_role
            and cat_from != candidate_role
        )

        if max_diff_by_cat and not cat_keyed_on_other:
            cat_attr_name = max_diff_by_cat.get('attribute')
            cat_values = max_diff_by_cat.get('values', {})
            cat_getter = self._get_attribute_getter(cat_attr_name)
            candidate_cat_value = cat_getter(candidate)
            if candidate_cat_value and candidate_cat_value in cat_values:
                max_diff = cat_values[candidate_cat_value]

        # Get attribute values
        candidate_value = getter(candidate)

        if cat_keyed_on_other:
            # Per-member evaluation: the categorical cap comes from each existing
            # member of the other role (e.g. the existing parent's sex), so we
            # must compare against each member rather than a collapsed min/max.
            cat_attr_name = max_diff_by_cat.get('attribute')
            cat_values = max_diff_by_cat.get('values', {})
            cat_getter = self._get_attribute_getter(cat_attr_name)
            worst_penalty = 0.0
            for p in other_people:
                other_value = getter(p)
                p_cat = cat_getter(p)
                p_max_diff = cat_values.get(p_cat, max_diff) if p_cat else max_diff
                diff = (candidate_value - other_value) if is_role_1 else (other_value - candidate_value)
                if diff < min_diff:
                    worst_penalty = max(worst_penalty, min_diff - diff)
                    if log_rejection:
                        logger.debug(f"      ✗ Rejected: {candidate} vs {p} - difference too small (diff={diff} < min={min_diff})")
                elif diff > p_max_diff:
                    worst_penalty = max(worst_penalty, diff - p_max_diff)
                    if log_rejection:
                        logger.debug(f"      ✗ Rejected: {candidate} vs {p} - difference too large (diff={diff} > max={p_max_diff} for {cat_attr_name}={p_cat})")
            if worst_penalty > 0:
                return (False, worst_penalty)
            return (True, 0.0)

        # Use cached min/max values if provided
        if cached_values and attribute in cached_values:
            max_value = cached_values[attribute]['max']
            min_value = cached_values[attribute]['min']
        else:
            # For small lists (common in households), min/max are faster than numpy
            if len(other_people) < 20: 
                min_value = float('inf')
                max_value = float('-inf')
                for p in other_people:
                    val = getter(p)
                    if val < min_value: min_value = val
                    if val > max_value: max_value = val
            else:
                other_values = np.array([getter(p) for p in other_people])
                max_value = other_values.max()
                min_value = other_values.min()

        if is_role_1:
            diff_min_possible = candidate_value - max_value
            if diff_min_possible < min_diff:
                penalty = min_diff - diff_min_possible
                if log_rejection:
                    logger.debug(f"      ✗ Rejected: {candidate} - difference too small (diff={diff_min_possible} < min={min_diff})")
                return (False, penalty)

            diff_max_possible = candidate_value - min_value
            if diff_max_possible > max_diff:
                penalty = diff_max_possible - max_diff
                if log_rejection:
                    logger.debug(f"      ✗ Rejected: {candidate} - difference too large (diff={diff_max_possible} > max={max_diff}, penalty={penalty})")
                return (False, penalty)
        else:
            diff_min_possible = min_value - candidate_value
            if diff_min_possible < min_diff:
                penalty = min_diff - diff_min_possible
                if log_rejection:
                    logger.debug(f"      ✗ Rejected: {candidate} - difference too small (diff={diff_min_possible} < min={min_diff})")
                return (False, penalty)

            diff_max_possible = max_value - candidate_value
            if diff_max_possible > max_diff:
                penalty = diff_max_possible - max_diff
                if log_rejection:
                    logger.debug(f"      ✗ Rejected: {candidate} - difference too large (diff={diff_max_possible} > max={max_diff}, penalty={penalty})")
                return (False, penalty)

        return (True, 0.0)

    def validate_pair_numerical_attribute_difference(self,
                                      person1: Person,
                                      person2: Person,
                                      constraint: Dict) -> Tuple[bool, float]:
        """
        Validate numerical attribute difference between pair members.

        Args:
            person1: First person
            person2: Second person
            constraint: Constraint dict with numerical_attribute parameters

        Returns:
            Tuple of (is_valid, penalty_score)
        """
        num_attr_config = constraint.get('numerical_attribute', {})
        if not num_attr_config:
            return (True, 0.0)

        attribute = num_attr_config.get('attribute', 'age')
        max_absolute = num_attr_config.get('max_absolute_difference', 100)

        getter = self._get_attribute_getter(attribute)
        value1 = getter(person1)
        value2 = getter(person2)
        diff = abs(value1 - value2)

        if diff > max_absolute:
            penalty = diff - max_absolute
            return (False, penalty)

        return (True, 0.0)

    def calculate_pair_numerical_attribute_penalty(self,
                                    person1: Person,
                                    person2: Person,
                                    constraint: Dict) -> float:
        """
        Calculate penalty score for pair numerical attribute difference.

        Lower score = better match based on expected mean/std.

        Args:
            person1: First person
            person2: Second person
            constraint: Constraint dict

        Returns:
            Penalty score (0.0 = perfect match)
        """
        num_attr_config = constraint.get('numerical_attribute', {})
        if not num_attr_config:
            return 0.0

        attribute = num_attr_config.get('attribute', 'age')
        mean = num_attr_config.get('mean_difference', 3.0)
        std = num_attr_config.get('std_difference', 5.0)

        getter = self._get_attribute_getter(attribute)
        value1 = getter(person1)
        value2 = getter(person2)
        diff = abs(value1 - value2)

        # Z-score: how many standard deviations from mean
        z_score = abs(diff - mean) / max(std, 1.0)

        # Apply penalty mode
        penalty_mode = self.selection_strategy.get('penalty_mode', 'squared')
        if penalty_mode == 'squared':
            return z_score ** 2
        else:
            return z_score

    def couple_compatible_candidates(self,
                                     existing_partner: Person,
                                     candidates: List[Person],
                                     pair_constraint: Dict,
                                     geo_unit_code: Optional[str] = None) -> List[Person]:
        """Filter ``candidates`` to those that could partner ``existing_partner``
        under a ``pair_matching`` constraint, best-match first.

        This is the household_excess analogue of the second-person selection in
        :meth:`select_pair`: the first partner already exists in the household,
        so instead of picking two people we pick the *one* compatible partner.
        It applies the same two pair signals:

        - **categorical** (e.g. sex): roll same/different by the (per-area)
          ``same_category_probability`` and keep only candidates whose value
          matches the rolled outcome relative to the existing partner;
        - **numerical** (e.g. age): keep only candidates within the pair's
          ``max_absolute_difference`` of the partner, ordered by closeness to
          ``mean_difference``.

        Returns a (possibly empty) list. The caller still applies any role-level
        ``numerical_attribute_difference`` constraints (vs other roles) via
        :meth:`select_person_with_constraint`, and tags the couple.
        """
        if not candidates:
            return []

        cat_attr_config = pair_constraint.get('categorical_attribute', {})
        cat_attribute = cat_attr_config.get('attribute', 'sex')
        fallback_prob = cat_attr_config.get(
            'same_category_probability_fallback',
            cat_attr_config.get('same_category_probability', 0.05),
        )
        same_category_prob = self._resolve_same_category_prob(
            cat_attribute, geo_unit_code, default=fallback_prob,
        )
        is_same_category = np.random.random() < same_category_prob

        cat_getter = self._get_attribute_getter(cat_attribute)
        partner_cat = cat_getter(existing_partner)
        if is_same_category:
            required_cat_value = partner_cat
        elif cat_attribute == 'sex':
            required_cat_value = 'male' if partner_cat == 'female' else 'female'
        else:
            others = {cat_getter(p) for p in candidates if cat_getter(p) != partner_cat}
            required_cat_value = np.random.choice(sorted(others)) if others else partner_cat

        partner_id = existing_partner.id
        scored: List[Tuple[float, Person]] = []
        for p in candidates:
            if p.id == partner_id or cat_getter(p) != required_cat_value:
                continue
            ok, _ = self.validate_pair_numerical_attribute_difference(
                existing_partner, p, pair_constraint
            )
            if not ok:
                continue
            penalty = self.calculate_pair_numerical_attribute_penalty(
                existing_partner, p, pair_constraint
            )
            scored.append((penalty, p))

        scored.sort(key=lambda t: t[0])
        return [p for _, p in scored]

    def select_person_with_constraint(self,
                                     candidates: List[Person],
                                     existing_people_by_role: Dict[str, List[Person]],
                                     constraints: List[Dict],
                                     current_role: str,
                                     show_detailed_logs: bool = False) -> Optional[Person]:
        """
        Select a person from candidates that satisfies all constraints.

        Implements smart selection:
        1. If preferred_distribution exists, target that age range first
        2. Try random selection up to max_attempts
        3. If no valid person found, use best candidate (lowest penalty)

        Args:
            candidates: List of candidate persons
            existing_people_by_role: Dict of role_name -> list of already selected people
            constraints: List of constraint dicts to validate
            current_role: Name of role being filled
            show_detailed_logs: If True, log detailed selection process

        Returns:
            Selected person or None
        """
        if not candidates:
            return None

        max_attempts = self.selection_strategy.get('max_attempts', 50)
        use_best = self.selection_strategy.get('use_best_candidate', True)

        # Filter constraints relevant to current_role
        relevant_constraints = []
        for c in constraints:
            if c.get('type') == 'numerical_attribute_difference':
                if c.get('role_1') == current_role:
                    relevant_constraints.append((c, True))
                elif c.get('role_2') == current_role:
                    relevant_constraints.append((c, False))

        prioritized_candidates = candidates
        for constraint, is_role_1 in relevant_constraints:
            pref_dist = constraint.get('preferred_distribution')
            if pref_dist:
                other_role = constraint.get('role_2') if is_role_1 else constraint.get('role_1')
                other_people = existing_people_by_role.get(other_role, [])
                if other_people:
                    attribute = constraint.get('attribute', 'age')
                    getter = self._get_attribute_getter(attribute)
                    dist_type = pref_dist.get('type', 'normal')

                    if dist_type == 'normal':
                        mean = pref_dist.get('mean', 30)
                        std = pref_dist.get('std', 6)
                        target_diff = np.random.normal(mean, std)
                    else:
                        # Fallback to uniform if unknown type
                        min_diff = constraint.get('min_difference', 16)
                        max_diff = constraint.get('max_difference', 50)
                        target_diff = np.random.uniform(min_diff, max_diff)

                    # Clamp to valid range
                    min_diff = constraint.get('min_difference', 16)
                    max_diff = constraint.get('max_difference', 50)
                    target_diff = max(min_diff, min(max_diff, target_diff))

                    other_values = [getter(p) for p in other_people]
                    
                    if is_role_1:
                        reference_value = max(other_values)
                        target_value = reference_value + target_diff
                    else:
                        reference_value = min(other_values)
                        target_value = reference_value - target_diff

                    tolerance = pref_dist.get('tolerance', std * 1.5 if dist_type == 'normal' else 10)
                    
                    # Prioritized_candidates filter
                    new_prioritized = []
                    for p in prioritized_candidates:
                        p_val = getter(p)
                        if target_value - tolerance <= p_val <= target_value + tolerance:
                            new_prioritized.append(p)
                    prioritized_candidates = new_prioritized

                    # If filtering too aggressive, fall back to all candidates
                    if not prioritized_candidates:
                        prioritized_candidates = candidates
                        if show_detailed_logs:
                            logger.debug(f"  ⚠ No candidates within ±{tolerance} of target {attribute}={target_value:.1f}, using all candidates")
                    elif show_detailed_logs:
                        logger.debug(f"  ℹ Prioritizing {len(prioritized_candidates)}/{len(candidates)} candidates near target {attribute}={target_value:.1f} (±{tolerance})")

        constraint_people_cache = {}
        constraint_value_cache = {}
        for constraint, is_role_1 in relevant_constraints:
            other_role = constraint.get('role_2') if is_role_1 else constraint.get('role_1')
            if other_role not in constraint_people_cache:
                other_people = existing_people_by_role.get(other_role, [])
                constraint_people_cache[other_role] = other_people
                
                # Pre-calculate min/max for numerical attributes
                if other_people:
                    attribute = constraint.get('attribute', 'age')
                    getter = self._get_attribute_getter(attribute)
                    if other_role not in constraint_value_cache:
                        constraint_value_cache[other_role] = {}
                        
                    if attribute not in constraint_value_cache[other_role]:
                        values = [getter(p) for p in other_people]
                        constraint_value_cache[other_role][attribute] = {
                            'min': min(values),
                            'max': max(values)
                        }

        shuffled_candidates = prioritized_candidates.copy()
        np.random.shuffle(shuffled_candidates)

        # Try random selection up to max_attempts (from prioritized pool)
        candidates_tested = 0
        candidates_rejected = 0

        for candidate in islice(shuffled_candidates, max_attempts):
            candidates_tested += 1

            # Validate all relevant constraints
            all_valid = True
            for constraint, is_role_1 in relevant_constraints:
                other_role = constraint.get('role_2') if is_role_1 else constraint.get('role_1')
                other_people = constraint_people_cache.get(other_role, [])

                is_valid, _ = self.validate_numerical_attribute_difference_constraint(
                    candidate, other_people, constraint, 
                    log_rejection=show_detailed_logs,
                    cached_values=constraint_value_cache.get(other_role),
                    is_role_1=is_role_1
                )

                if not is_valid:
                    all_valid = False
                    candidates_rejected += 1
                    break

            if all_valid:
                if show_detailed_logs:
                    if candidates_rejected > 0:
                        logger.debug(f"  ✓ Selected (tested {candidates_tested} candidates, rejected {candidates_rejected}): {candidate}")
                    else:
                        logger.debug(f"  ✓ Selected on first try: {candidate}")
                return candidate

        # No valid candidate found, use best candidate if enabled
        if self.selection_strategy.get('log_violations', False):
            logger.debug(f"No valid candidate found for {current_role} after {max_attempts} attempts. use_best_candidate={use_best}")

        if use_best:
            best_candidate = None
            best_penalty = float('inf')

            for candidate in candidates:
                total_penalty = 0.0

                for constraint, is_role_1 in relevant_constraints:
                    other_role = constraint.get('role_2') if is_role_1 else constraint.get('role_1')
                    other_people = existing_people_by_role.get(other_role, [])

                    is_valid, penalty = self.validate_numerical_attribute_difference_constraint(
                        candidate, other_people, constraint,
                        cached_values=constraint_value_cache.get(other_role),
                        is_role_1=is_role_1
                    )
                    total_penalty += penalty

                if total_penalty < best_penalty:
                    best_penalty = total_penalty
                    best_candidate = candidate

            if best_candidate:
                self.stats['best_candidate_selections'] += 1
                self.stats['violations']['numerical_attribute_difference'] += 1

                logger.debug(f"⚠️  USING BEST CANDIDATE (VIOLATES CONSTRAINTS) for {current_role}: "
                           f"age={best_candidate.age}, sex={best_candidate.sex}, "
                           f"penalty={best_penalty:.2f}")

                return best_candidate

        if self.selection_strategy.get('log_violations', False):
            logger.debug(f"Returning None for {current_role} - no valid candidates and use_best_candidate=False")

        return None

    def select_pair(self,
                     candidates: List[Person],
                     constraint: Dict,
                     existing_people_by_role: Optional[Dict[str, List[Person]]] = None,
                     constraints: Optional[List[Dict]] = None,
                     current_role: Optional[str] = None,
                     show_detailed_logs: bool = False,
                     candidates_by_cat: Optional[Dict[Any, List[Person]]] = None,
                     geo_unit_code: Optional[str] = None) -> Optional[Tuple[Person, Person]]:
        """
        Select 2 people from candidates to form a compatible pair.

        Can be used for: romantic partners, roommates, business partners, siblings, etc.

        Selection process:
        1. Decide same/different category based on same_category_probability
        2. Select first person randomly (validating against existing people if provided)
        3. Select second person with attribute compatibility and validation

        Args:
            candidates: List of candidate persons
            constraint: Pair matching constraint
            existing_people_by_role: Dict of already selected people by role (optional)
            constraints: List of all constraints to validate against (optional)
            current_role: Name of current role being filled (optional)
            show_detailed_logs: If True, log detailed selection process

        Returns:
            Tuple of (person1, person2) or None
        """
        if existing_people_by_role is None:
            existing_people_by_role = {}
        if constraints is None:
            constraints = []
        if len(candidates) < 2:
            return None

        # Extract categorical attribute config.
        # `same_category_probability_fallback` is the explicit name used
        # whenever a top-level `same_category_sources` entry exists for this
        # attribute (the source provides the live per-area value; the scalar
        # below is only used when the candidate's area is missing from it).
        # `same_category_probability` is accepted for back-compat with worlds
        # that have no source configured (e.g. Medieval), where the scalar IS
        # the authoritative value.
        cat_attr_config = constraint.get('categorical_attribute', {})
        cat_attribute = cat_attr_config.get('attribute', 'sex')
        fallback_prob = cat_attr_config.get(
            'same_category_probability_fallback',
            cat_attr_config.get('same_category_probability', 0.05),
        )

        # If a per-area source is configured for this categorical attribute,
        # override the scalar with the area-specific probability.
        same_category_prob = self._resolve_same_category_prob(
            cat_attribute, geo_unit_code, default=fallback_prob,
        )

        # Running counters (constant memory) for stage-1 diagnostics. We never
        # store the full per-call list — at England scale that would be tens of
        # millions of floats, and `mean / min / max` is all anyone reads.
        attr_stats = self.stats['same_category_lookup'].setdefault(
            cat_attribute,
            {
                'source_hits': 0,
                'fallback_hits': 0,
                'prob_sum': 0.0,
                'prob_min': float('inf'),
                'prob_max': float('-inf'),
                'prob_n': 0,
            },
        )
        if (cat_attribute in self._same_category_sources
                and same_category_prob != fallback_prob):
            attr_stats['source_hits'] += 1
        else:
            attr_stats['fallback_hits'] += 1
        attr_stats['prob_sum'] += same_category_prob
        if same_category_prob < attr_stats['prob_min']:
            attr_stats['prob_min'] = same_category_prob
        if same_category_prob > attr_stats['prob_max']:
            attr_stats['prob_max'] = same_category_prob
        attr_stats['prob_n'] += 1

        is_same_category = np.random.random() < same_category_prob

        if show_detailed_logs:
            pair_type = f"same-{cat_attribute}" if is_same_category else f"different-{cat_attribute}"
            logger.debug(f"    Pair type: {pair_type} (prob={same_category_prob*100:.0f}%)")

        # Get relevant numerical_attribute_difference constraints for this role
        relevant_constraints = []
        if current_role:
            for c in constraints:
                if c.get('type') == 'numerical_attribute_difference':
                    if c.get('role_1') == current_role:
                        relevant_constraints.append((c, True))
                    elif c.get('role_2') == current_role:
                        relevant_constraints.append((c, False))

        if show_detailed_logs and relevant_constraints:
            for rc, is_role_1 in relevant_constraints:
                other_role = rc.get('role_2') if is_role_1 else rc.get('role_1')
                other_people = existing_people_by_role.get(other_role, [])
                if other_people:
                    attribute = rc.get('attribute', 'age')
                    getter = self._get_attribute_getter(attribute)
                    values = [getter(p) for p in other_people]
                    logger.debug(f"    {attribute.capitalize()} constraints: Both partners must be {rc.get('min_difference')}-{rc.get('max_difference')} {attribute} units older than {other_role} ({attribute}s: {values})")

        max_attempts = self.selection_strategy.get('max_attempts', 50)
        use_best = self.selection_strategy.get('use_best_candidate', True)

        # Pre-shuffle candidates once to avoid repeated random.choice() overhead
        shuffled_candidates = candidates.copy()
        np.random.shuffle(shuffled_candidates)

        # Pre-group candidates by categorical attribute AND cache attribute values
        cat_getter = self._get_attribute_getter(cat_attribute)
        
        if candidates_by_cat is None:
            candidates_by_cat = defaultdict(list)
            candidate_cat_values = {}  # Cache categorical attribute values
            for p in candidates:
                cat_val = cat_getter(p)
                candidates_by_cat[cat_val].append(p)
                candidate_cat_values[p.id] = cat_val
        else:
            # We still need the cat_values mapping for the first person optimization below
            # Since we only do this once per select_pair, we can just call cat_getter on first_person
            candidate_cat_values = None

        # Pre-compute min/max values for each constraint
        constraint_people_cache = {}
        constraint_value_cache = {}
        for rel_constraint, is_role_1 in relevant_constraints:
            other_role = rel_constraint.get('role_2') if is_role_1 else rel_constraint.get('role_1')
            if other_role not in constraint_people_cache:
                other_people = existing_people_by_role.get(other_role, [])
                constraint_people_cache[other_role] = other_people

                # Pre-compute min/max for numerical attributes
                if other_people:
                    attribute = rel_constraint.get('attribute', 'age')
                    getter = self._get_attribute_getter(attribute)
                    if other_role not in constraint_value_cache:
                        constraint_value_cache[other_role] = {}
                    if attribute not in constraint_value_cache[other_role]:
                        values = np.array([getter(p) for p in other_people])
                        constraint_value_cache[other_role][attribute] = {
                            'min': values.min(),
                            'max': values.max()
                        }

        # Try to find a valid couple
        attempts_made = 0
        candidates_tested = 0
        candidates_rejected = 0
        first_person = None
        remaining = []

        # Iterate through shuffled candidates instead of random.choice()
        for first_person in islice(shuffled_candidates, max_attempts):
            candidates_tested += 1

            # Validate first person against existing people (e.g., children)
            first_valid = True
            for rel_constraint, is_role_1 in relevant_constraints:
                other_role = rel_constraint.get('role_2') if is_role_1 else rel_constraint.get('role_1')
                other_people = constraint_people_cache.get(other_role, [])
                if other_people:
                    # Only log rejections if detailed logging is enabled
                    # Pass cached min/max values for performance
                    cached_vals = constraint_value_cache.get(other_role)
                    is_valid, _ = self.validate_numerical_attribute_difference_constraint(
                        first_person, other_people, rel_constraint,
                        log_rejection=show_detailed_logs,
                        cached_values=cached_vals,
                        is_role_1=is_role_1
                    )
                    if not is_valid:
                        first_valid = False
                        candidates_rejected += 1
                        break

            if not first_valid:
                continue

            # Get categorical attribute value for first person
            first_cat_value = candidate_cat_values[first_person.id] if candidate_cat_values is not None else cat_getter(first_person)
            if is_same_category:
                required_cat_value = first_cat_value
            else:
                # For binary attributes like sex, swap the value
                # This is a simple heuristic - for more complex categories, you'd need a mapping
                if cat_attribute == 'sex':
                    required_cat_value = 'male' if first_cat_value == 'female' else 'female'
                else:
                    # For non-binary categorical attributes, we can't easily determine "opposite"
                    # Use pre-computed categorical values from candidates_by_cat
                    all_cat_values = list(candidates_by_cat.keys())
                    other_values = [v for v in all_cat_values if v != first_cat_value]
                    required_cat_value = np.random.choice(other_values) if other_values else first_cat_value

            # Use pre-grouped candidates by categorical attribute
            remaining = candidates_by_cat.get(required_cat_value, [])
            first_person_id = first_person.id
            remaining = [p for p in remaining if p.id != first_person_id]

            if not remaining:
                continue

            # Shuffle remaining candidates once and iterate
            shuffled_remaining = remaining.copy()
            np.random.shuffle(shuffled_remaining)

            # Try to find valid partner - iterate through shuffled list
            for candidate in islice(shuffled_remaining, max_attempts):
                candidates_tested += 1

                # Validate partner against first person (couple numerical attribute difference)
                is_valid, _ = self.validate_pair_numerical_attribute_difference(
                    first_person, candidate, constraint
                )
                if not is_valid:
                    candidates_rejected += 1
                    if show_detailed_logs:
                        logger.debug(f"      ✗ Rejected: Partner pair has age difference too large")
                    continue

                # Validate partner against existing people (e.g., children)
                partner_valid = True
                for rel_constraint, is_role_1 in relevant_constraints:
                    other_role = rel_constraint.get('role_2') if is_role_1 else rel_constraint.get('role_1')
                    other_people = constraint_people_cache.get(other_role, [])
                    if other_people:
                        # Pass cached min/max values for performance
                        cached_vals = constraint_value_cache.get(other_role)
                        is_valid, _ = self.validate_numerical_attribute_difference_constraint(
                            candidate, other_people, rel_constraint,
                            log_rejection=show_detailed_logs,
                            cached_values=cached_vals,
                            is_role_1=is_role_1
                        )
                        if not is_valid:
                            partner_valid = False
                            candidates_rejected += 1
                            break

                if partner_valid:
                    # Found a valid pair!
                    if show_detailed_logs:
                        num_attr_config = constraint.get('numerical_attribute', {})
                        if num_attr_config:
                            num_attr = num_attr_config.get('attribute', 'age')
                            getter = self._get_attribute_getter(num_attr)
                            val1 = getter(first_person)
                            val2 = getter(candidate)
                            diff = abs(val1 - val2)
                            if candidates_rejected > 0:
                                logger.debug(f"    ✓ Found valid pair (tested {candidates_tested} candidates, rejected {candidates_rejected})")
                            else:
                                logger.debug(f"    ✓ Found valid pair on first try")
                            logger.debug(f"      Partner 1: {first_person} ({num_attr} {val1})")
                            logger.debug(f"      Partner 2: {candidate} ({num_attr} {val2})")
                            logger.debug(f"      {num_attr.capitalize()} difference: {diff}")
                        else:
                            if candidates_rejected > 0:
                                logger.debug(f"    ✓ Found valid pair (tested {candidates_tested} candidates, rejected {candidates_rejected})")
                            else:
                                logger.debug(f"    ✓ Found valid pair on first try")
                            logger.debug(f"      Partner 1: {first_person}")
                            logger.debug(f"      Partner 2: {candidate}")

                    if self.track_statistics:
                        # Track numerical attribute differences
                        num_attr_config = constraint.get('numerical_attribute', {})
                        if num_attr_config:
                            num_attr = num_attr_config.get('attribute')
                            if num_attr:
                                getter = self._get_attribute_getter(num_attr)
                                try:
                                    diff = abs(getter(first_person) - getter(candidate))
                                    self.stats['numerical_attribute_differences'].append(diff)
                                except (AttributeError, TypeError):
                                    pass

                        # Track categorical attribute statistics
                        if is_same_category:
                            self.stats['same_category_pairs'] += 1
                        else:
                            self.stats['different_category_pairs'] += 1

                    return (first_person, candidate)

            attempts_made += 1

        # No valid pair found, use best candidate
        if use_best and first_person is not None and remaining:
            best_partner = None
            best_penalty = float('inf')

            for candidate in remaining:
                is_valid, val_penalty = self.validate_pair_numerical_attribute_difference(
                    first_person, candidate, constraint
                )
                attr_penalty = self.calculate_pair_numerical_attribute_penalty(
                    first_person, candidate, constraint
                )
                total_penalty = val_penalty + attr_penalty

                if total_penalty < best_penalty:
                    best_penalty = total_penalty
                    best_partner = candidate

            if best_partner:
                self.stats['best_candidate_selections'] += 1
                self.stats['violations']['pair_numerical_attribute_diff'] += 1

                if self.track_statistics:
                    # Track numerical attribute differences
                    num_attr_config = constraint.get('numerical_attribute', {})
                    if num_attr_config:
                        num_attr = num_attr_config.get('attribute')
                        if num_attr:
                            getter = self._get_attribute_getter(num_attr)
                            try:
                                diff = abs(getter(first_person) - getter(best_partner))
                                self.stats['numerical_attribute_differences'].append(diff)
                            except (AttributeError, TypeError):
                                pass

                    # Track categorical attribute statistics
                    if is_same_category:
                        self.stats['same_category_pairs'] += 1
                    else:
                        self.stats['different_category_pairs'] += 1

                return (first_person, best_partner)

        return None

    def print_statistics(self):
        """Print statistics about relationship rule application."""
        if not self.track_statistics:
            return

        logger.debug("=" * 60)
        logger.debug("RELATIONSHIP RULES STATISTICS")
        logger.debug("=" * 60)

        # Best candidate selections
        if self.stats['best_candidate_selections'] > 0:
            logger.debug(f"Best candidate selections: {self.stats['best_candidate_selections']:,}")

        # Pair types
        total_pairs = self.stats['same_category_pairs'] + self.stats['different_category_pairs']
        if total_pairs > 0:
            logger.debug(f"Pairs created: {total_pairs:,}")
            logger.debug(f"  Same-category: {self.stats['same_category_pairs']:,} "
                       f"({100*self.stats['same_category_pairs']/total_pairs:.1f}%)")
            logger.debug(f"  Different-category: {self.stats['different_category_pairs']:,} "
                       f"({100*self.stats['different_category_pairs']/total_pairs:.1f}%)")

        # Numerical attribute differences
        if self.stats['numerical_attribute_differences']:
            import statistics as stats_module
            logger.debug(f"Partner numerical attribute differences:")
            logger.debug(f"  Mean: {stats_module.mean(self.stats['numerical_attribute_differences']):.1f}")
            logger.debug(f"  Median: {stats_module.median(self.stats['numerical_attribute_differences']):.1f}")
            logger.debug(f"  Range: {min(self.stats['numerical_attribute_differences'])}-"
                       f"{max(self.stats['numerical_attribute_differences'])}")

        # Violations
        total_violations = sum(self.stats['violations'].values())
        if total_violations > 0:
            logger.debug(f"Rule violations (resolved with best candidate):")
            for violation_type, count in self.stats['violations'].items():
                if count > 0:
                    logger.debug(f"  {violation_type}: {count:,}")

        logger.debug("=" * 60)
