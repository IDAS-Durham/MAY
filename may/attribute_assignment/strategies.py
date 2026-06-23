import logging
import numpy as np
from typing import Dict, List, Any, Optional

logger = logging.getLogger("may.attribute_assignment.strategies")


# ---------------------------------------------------------------------------
# Config validation — assignment blocks fail loudly on keys the engine
# doesn't read. (The `context:` key survived a year as dead config because
# nothing rejected it; this is the guard against the next one.)
# ---------------------------------------------------------------------------
STRATEGY_ALLOWED_KEYS: Dict[str, set] = {
    'probabilistic': {'strategy', 'data_source'},
    'partnership': {'strategy', 'data_source', 'partner_role', 'marginal_source'},
    'inheritance': {'strategy', 'inherit_from', 'logic', 'marginal_source'},
    'reverse_inheritance': {'strategy', 'inherit_from', 'logic', 'marginal_source'},
    'probabilistic_conditions': {'strategy', 'data_source', 'conditions',
                                 'selection_method'},
    'commuting_likelihood': {'strategy', 'data_source', 'outputs'},
    'geographical_unit_sampler': {'strategy', 'data_source'},
    'categorical_sampler': {'strategy', 'data_source'},
    'constant': {'strategy', 'value'},
}
# Logic entries and nested then-blocks (inheritance strategies read these inline).
_LOGIC_ENTRY_KEYS = {'when', 'then', 'note'}
_THEN_BLOCK_KEYS = {'strategy', 'data_source', 'exclude', 'value', 'copy'}

# Strategies whose `logic:` blocks use the declarative when/then schema (adr/0009).
_LOGIC_STRATEGIES = {'inheritance', 'reverse_inheritance'}

# Tolerance for probability arithmetic (e.g. detecting a genuinely negative
# P(exactly 1) vs floating-point noise) in the gated comorbidity sampler.
_PROB_TOL = 1e-9

# How `probabilistic_conditions` turns per-person probabilities into a set of
# conditions. A config must pick one explicitly — there is no default, so the
# modelling choice is always visible (see ProbabilisticConditionsStrategy).
_CONDITION_SELECTION_METHODS = {'independent_bernoulli', 'gated_conditions'}


class _CompiledBlock:
    """
    A logic block parsed once at strategy-construction time (adr/0009).

    Holds the predicate/action kinds (from `_classify_when`/`_classify_then`) and,
    for a nested probabilistic `then`, a prebuilt strategy instance — so the
    per-person `assign` path neither re-classifies nor reconstructs anything.
    """

    __slots__ = ('when_kind', 'when', 'then_kind', 'then', 'nested_strategy')

    def __init__(self, when_kind, when, then_kind, then, nested_strategy):
        self.when_kind = when_kind
        self.when = when
        self.then_kind = then_kind
        self.then = then
        self.nested_strategy = nested_strategy


def _classify_when(when: Any) -> str:
    """
    Validate a declarative `when` predicate and return its kind (adr/0009).

    Recognized forms (no eval — structured predicates only):
      - {unique_count: N}          distinct collected values == N
      - {unique_count_at_least: N} distinct collected values >= N
      - {role: R, attr: A, equals: V}   role R's attribute A == V
      - {role: R, attr: A, in: [V, ...]} role R's attribute A in the list

    Raises:
        ValueError: naming the offending predicate, so a malformed or unknown
        `when` fails loudly instead of silently evaluating false.
    """
    if not isinstance(when, dict):
        raise ValueError(
            f"inheritance 'when' must be a mapping describing one predicate, got "
            f"{when!r}. Use e.g. {{unique_count: 1}} or "
            f"{{role: primary_adult, attr: ethnicity, equals: M}}."
        )
    keys = set(when)
    if keys == {'unique_count'}:
        return 'unique_count'
    if keys == {'unique_count_at_least'}:
        return 'unique_count_at_least'
    if {'role', 'attr'} <= keys and keys <= {'role', 'attr', 'equals', 'in'}:
        if ('equals' in keys) ^ ('in' in keys):
            return 'role_attr'
        raise ValueError(
            f"inheritance role predicate needs exactly one of 'equals'/'in': {when!r}"
        )
    raise ValueError(
        f"unknown inheritance 'when' predicate {when!r}. Known forms: "
        f"{{unique_count: N}}, {{unique_count_at_least: N}}, "
        f"{{role, attr, equals: V}}, {{role, attr, in: [...]}}."
    )


def _classify_then(then: Any) -> str:
    """
    Validate a declarative `then` action and return its kind (adr/0009).

    Recognized forms:
      - the literal token "values[0]"  → first collected value
      - any other scalar               → that literal value
      - {value: V}                     → literal V (explicit)
      - {copy: {role: R, attr: A}}     → role R's attribute A value
      - {strategy: ..., ...}           → nested strategy block

    Raises:
        ValueError: on an unrecognized `then` block.
    """
    if isinstance(then, dict):
        keys = set(then)
        if keys == {'value'}:
            return 'value'
        if keys == {'copy'}:
            spec = then['copy']
            if not isinstance(spec, dict) or set(spec) != {'role', 'attr'}:
                raise ValueError(
                    f"inheritance 'then.copy' must be {{role, attr}}, got {then['copy']!r}"
                )
            return 'copy'
        if 'strategy' in keys:
            return 'strategy'
        raise ValueError(
            f"unknown inheritance 'then' block {then!r}. Known forms: a literal, "
            f"\"values[0]\", {{value: V}}, {{copy: {{role, attr}}}}, or a nested "
            f"strategy block."
        )
    if then == 'values[0]':
        return 'values[0]'
    return 'literal'


def validate_assignment_config(config: Dict[str, Any], where: str = "assignment") -> None:
    """
    Reject assignment config keys no strategy reads.

    Raises:
        ValueError: naming the unknown keys, the strategy, and the allowed
        set — so a stale key (e.g. `context`) breaks the build at load time
        instead of silently doing nothing.
    """
    if not isinstance(config, dict):
        raise ValueError(f"{where}: assignment must be a mapping, got {type(config).__name__}")

    strategy_type = config.get('strategy')
    if not strategy_type:
        raise ValueError(f"{where}: assignment has no 'strategy' field")

    allowed = STRATEGY_ALLOWED_KEYS.get(strategy_type)
    if allowed is None:
        raise ValueError(
            f"{where}: unknown strategy '{strategy_type}' "
            f"(known: {sorted(STRATEGY_ALLOWED_KEYS)})"
        )

    unknown = set(config) - allowed
    if unknown:
        raise ValueError(
            f"{where}: strategy '{strategy_type}' does not read key(s) "
            f"{sorted(unknown)} — allowed keys are {sorted(allowed)}. "
            f"Remove them (dead config) or fix the typo."
        )

    if strategy_type == 'probabilistic_conditions':
        method = config.get('selection_method')
        if method is None:
            raise ValueError(
                f"{where}: strategy 'probabilistic_conditions' requires "
                f"'selection_method' — declare one of "
                f"{sorted(_CONDITION_SELECTION_METHODS)} (no implicit default)."
            )
        if method not in _CONDITION_SELECTION_METHODS:
            raise ValueError(
                f"{where}: unknown selection_method '{method}' "
                f"(known: {sorted(_CONDITION_SELECTION_METHODS)})."
            )

    is_logic_strategy = strategy_type in _LOGIC_STRATEGIES
    for i, entry in enumerate(config.get('logic') or []):
        entry = entry or {}
        unknown = set(entry) - _LOGIC_ENTRY_KEYS
        if unknown:
            raise ValueError(
                f"{where}.logic[{i}]: unknown key(s) {sorted(unknown)} — "
                f"allowed: {sorted(_LOGIC_ENTRY_KEYS)}"
            )
        then = entry.get('then')
        if isinstance(then, dict):
            unknown = set(then) - _THEN_BLOCK_KEYS
            if unknown:
                raise ValueError(
                    f"{where}.logic[{i}].then: unknown key(s) {sorted(unknown)} — "
                    f"allowed: {sorted(_THEN_BLOCK_KEYS)}"
                )
        if is_logic_strategy:
            try:
                _classify_when(entry.get('when'))
                _classify_then(then)
            except ValueError as exc:
                raise ValueError(f"{where}.logic[{i}]: {exc}") from exc


class AssignmentStrategy:
    """
    Base class for assignment strategies.

    Strategies are simplified - they don't evaluate complex conditions,
    just perform straightforward assignments based on context.
    """

    def __init__(self, config: Dict[str, Any], data_manager):
        """
        Initialize strategy.

        Args:
            config: Strategy configuration from YAML
            data_manager: DataSourceManager instance for data lookups
        """
        self.config = config
        self.data_manager = data_manager
        self.strategy_type = config.get('strategy')

    def assign(self, person, household, context: Dict[str, Any]) -> Any:
        """
        Assign attribute value to a person.

        Args:
            person: Person object to assign to
            household: Household (venue) object
            context: Assignment context with state information

        Returns:
            Assigned attribute value
        """
        raise NotImplementedError("Subclasses must implement assign()")

    def _fail(self, person, reason: str):
        """Abort assignment loudly. No fallbacks (adr/0010)."""
        raise RuntimeError(
            f"Strategy '{self.strategy_type}' could not assign person {person.id}: "
            f"{reason}. No fallbacks (adr/0010) — fix the data/config, or express the "
            "alternative as explicit primary logic."
        )

    def _weighted_draw(self, probs: Dict[str, float], person, *, size=None):
        """
        Draw value(s) from a {value: weight} distribution (adr/0007).

        The single weighted-draw code path shared by every draw-family strategy:
        clamp negative weights to zero, normalize, then `np.random.choice`. With
        `size=None` returns one value; with `size=n` returns n values (batch).
        An empty or zero-total distribution fails loudly — no silent None
        (adr/0010).
        """
        if not probs:
            self._fail(person, "data source returned no distribution")
        values = list(probs.keys())
        weights = np.asarray(list(probs.values()), dtype=float)
        if np.any(weights < 0):
            logger.warning(f"Negative weight(s) clamped to 0 for person {person.id}")
            weights = np.clip(weights, 0.0, None)
        total = weights.sum()
        if total <= 0:
            self._fail(person, "distribution has zero total weight")
        return np.random.choice(values, size=size, p=weights / total)

    def _marginal_assign(self, person, household, context: Dict[str, Any]) -> Any:
        """
        Assign from the configured marginal distribution.

        This is explicit primary logic for the defined case where a strategy has
        nothing to condition on (e.g. inheritance with no parent values). The
        marginal source is named by `marginal_source`; absence of that key means
        the case is not expected and is a hard error.
        """
        marginal_source = self.config.get('marginal_source')
        if not marginal_source:
            self._fail(
                person,
                "no value to condition on and no 'marginal_source' configured",
            )
        strat = ProbabilisticStrategy(
            {'strategy': 'probabilistic', 'data_source': marginal_source},
            self.data_manager,
        )
        return strat.assign(person, household, context)

    def _get_person_by_role(self, context: Dict[str, Any], role_name: str):
        """
        Get person by role name from context.

        Args:
            context: Assignment context
            role_name: Role name (e.g., "primary_adult")

        Returns:
            Person object or None
        """
        person_key = f"{role_name}_person"
        return context.get(person_key)

    def _get_attribute_value(self, person, attribute_name: str) -> Any:
        """
        Get attribute value from person.

        Delegates to the shared get_person_attribute utility which handles
        dot-notation, properties dict, and residence prefix.

        Args:
            person: Person object
            attribute_name: Name of attribute

        Returns:
            Attribute value or None
        """
        from may.utils.attribute_access import get_person_attribute
        return get_person_attribute(person, attribute_name)


class ProbabilisticStrategy(AssignmentStrategy):
    """
    Probabilistic assignment based on geographical distribution.

    Samples from attribute distribution for the household's geographical unit.
    This is the simplest strategy - no dependencies on other people.
    """

    def __init__(self, config: Dict[str, Any], data_manager):
        """Initialize and cache configuration values."""
        super().__init__(config, data_manager)
        self.data_source_name = config.get('data_source', 'geo_distribution')

    def assign(self, person, household, context: Dict[str, Any]) -> Any:
        """
        Sample attribute value from geographical distribution.

        Args:
            person: Person object
            household: Household object
            context: Assignment context

        Returns:
            Sampled attribute value
        """
        # Resolve the residence geo unit: venue first, then the person's own.
        geo_unit = None
        if household and household.geographical_unit:
            geo_unit = household.geographical_unit.name
        if not geo_unit and person.geographical_unit:
            geo_unit = person.geographical_unit.name
        if not geo_unit:
            self._fail(person, "no geographical_unit (no residence venue and no person-level geo unit)")

        probs = self.data_manager.lookup(self.data_source_name, geo_unit)
        sampled = self._weighted_draw(probs, person)
        logger.debug(f"Probabilistic: {sampled} for {person.id} in {geo_unit}")
        return sampled


class PartnershipStrategy(AssignmentStrategy):
    """
    Partnership-based assignment using pair probabilities.

    Given the first person's attribute value, samples the second person's value
    from conditional probability distribution. Used for couples and family secondary adults.

    Replaces complex conditional strategies with role-based subset selection.
    """

    def __init__(self, config: Dict[str, Any], data_manager):
        """Initialize partnership strategy."""
        super().__init__(config, data_manager)
        self.data_source_name = config.get('data_source', 'pair_probabilities')
        self.partner_role = config.get('partner_role', 'primary_adult')

    def assign(self, person, household, context: Dict[str, Any]) -> Any:
        """
        Sample partner attribute value based on first person's attribute value.

        Args:
            person: Person object (the partner being assigned)
            household: Household object
            context: Assignment context (must contain partner_role person)

        Returns:
            Sampled attribute value
        """
        # Get the first person (primary_adult or primary_elder)
        first_person = self._get_person_by_role(context, self.partner_role)
        if not first_person:
            logger.warning(f"Partner role '{self.partner_role}' not found in context")
            # Fall back to probabilistic
            return self._marginal_assign(person, household, context)

        # Get first person's attribute value
        attribute_name = context.get('attribute_name')
        first_value = self._get_attribute_value(first_person, attribute_name)
        if first_value is None:
            logger.warning(f"No {attribute_name} found for {self.partner_role}")
            return self._marginal_assign(person, household, context)

        if not household or not household.geographical_unit:
            logger.warning("No geographical unit found for household")
            return self._fail(person, "no geographical_unit available")

        geo_unit = household.geographical_unit.name

        # Look up pair probabilities
        probs = self.data_manager.lookup(self.data_source_name, geo_unit, first_value)
        if not probs:
            logger.warning(f"No pair probabilities for {geo_unit}, {first_value}")
            return self._fail(person, "data source returned no distribution")

        # Sample from distribution
        values = list(probs.keys())
        probabilities = list(probs.values())
        sampled = np.random.choice(values, p=probabilities)

        logger.debug(f"Partnership: {sampled} (partner of {first_value}) for {person.id}")
        return sampled



class LogicBlockStrategy(AssignmentStrategy):
    """
    Base for the inheritance strategies that drive assignment from declarative
    `when`/`then` logic blocks (adr/0009).

    A `when` is a structured predicate (see `_classify_when`) evaluated against
    the collected source values and role context — never an eval'd string. A
    `then` is a literal, the `values[0]` token, a `{value: ...}` / `{copy: ...}`
    block, or a nested strategy block (see `_classify_then`). The first block
    whose `when` matches wins; if none match, assignment fails loudly (adr/0010).
    """

    def __init__(self, config: Dict[str, Any], data_manager):
        super().__init__(config, data_manager)
        self.inherit_config = config.get('inherit_from', {})
        self.logic_blocks = config.get('logic', [])
        # Precompile blocks once per strategy instance (instances are cached and
        # reused across every person — see assigner._get_or_create_strategy), so
        # the per-call `assign` path does no predicate classification, no expr
        # compilation, and no nested-strategy construction. This is what the old
        # eval()+lru_cache existed to approximate; with structured logic we can
        # do the parsing once up front instead of guarding it per call.
        self._compiled = [self._compile_block(b) for b in self.logic_blocks]

    def _compile_block(self, block: Dict[str, Any]) -> '_CompiledBlock':
        """Classify and pre-build a logic block once (raises on bad shapes)."""
        when = block.get('when')
        then = block.get('then')
        when_kind = _classify_when(when)
        then_kind = _classify_then(then)
        nested = None
        if then_kind == 'strategy' and then.get('strategy') == 'probabilistic':
            nested = ProbabilisticStrategy(then, self.data_manager)
        return _CompiledBlock(when_kind, when, then_kind, then, nested)

    def _resolve_role_attr(self, role: str, attr: str, context: Dict[str, Any]) -> Any:
        """Resolve a `role.attribute` reference to its assigned value, or raise."""
        person = self._get_person_by_role(context, role)
        if person is None:
            raise ValueError(f"logic predicate references role '{role}' absent from context")
        value = self._get_attribute_value(person, attr)
        if value is None:
            raise ValueError(f"logic predicate: role '{role}' has no '{attr}' assigned")
        return value

    def _evaluate_when(self, block: '_CompiledBlock', source_values: List[Any],
                       context: Dict[str, Any]) -> bool:
        """Evaluate a precompiled `when` predicate (adr/0009)."""
        kind, when = block.when_kind, block.when
        if kind == 'unique_count':
            return len(set(source_values)) == when['unique_count']
        if kind == 'unique_count_at_least':
            return len(set(source_values)) >= when['unique_count_at_least']
        # role_attr
        value = self._resolve_role_attr(when['role'], when['attr'], context)
        if 'equals' in when:
            return value == when['equals']
        return value in when['in']

    def _resolve_then(self, block: '_CompiledBlock', source_values: List[Any], person,
                      household, context: Dict[str, Any], attribute_name: str) -> Any:
        """Produce the value for a matched precompiled `then` action (adr/0009)."""
        kind, then = block.then_kind, block.then
        if kind == 'value':
            return then['value']
        if kind == 'copy':
            spec = then['copy']
            return self._resolve_role_attr(spec['role'], spec['attr'], context)
        if kind == 'strategy':
            return self._run_nested_strategy(block, person, household, context, attribute_name)
        if kind == 'values[0]':
            if not source_values:
                return self._fail(person, "'then: values[0]' but no source values collected")
            return source_values[0]
        # literal
        return then

    def _run_nested_strategy(self, block: '_CompiledBlock', person, household,
                             context: Dict[str, Any], attribute_name: str) -> Any:
        """Run a precompiled nested strategy block, honouring any `exclude` constraint."""
        if block.nested_strategy is None:
            return self._fail(
                person,
                f"unsupported nested strategy '{block.then.get('strategy')}' in logic block",
            )
        excluded_values = self._resolve_exclude_values(
            block.then.get('exclude', []), context, attribute_name
        )
        if excluded_values:
            return self._sample_with_exclusion(person, household, context, block.then, excluded_values)
        return block.nested_strategy.assign(person, household, context)

    def _run_logic(self, source_values: List[Any], person, household,
                   context: Dict[str, Any], attribute_name: str) -> Any:
        """First block whose `when` matches wins; no match fails loudly (adr/0010)."""
        for block in self._compiled:
            if self._evaluate_when(block, source_values, context):
                result = self._resolve_then(
                    block, source_values, person, household, context, attribute_name,
                )
                logger.debug(f"{self.strategy_type}: {result} for {person.id}")
                return result
        return self._fail(person, "no logic block matched")

    def _resolve_exclude_values(self, exclude_refs: List[str],
                                context: Dict[str, Any],
                                attribute_name: str) -> set:
        """
        Resolve exclude references like ["primary_elder.ethnicity"] into
        concrete values by looking up the referenced role persons in context.

        A referenced role that is not yet in context (e.g. the first elder when
        assigning the second) contributes nothing to exclude — there is no value
        to differ from yet. That is primary logic, not a fallback.

        Args:
            exclude_refs: List of "role.attribute" reference strings
            context: Assignment context containing role persons
            attribute_name: Current attribute being assigned

        Returns:
            Set of concrete values to exclude (may be empty)
        """
        excluded = set()
        for ref in exclude_refs:
            # Parse "role_name.attribute_name" format
            parts = ref.split('.', 1)
            if len(parts) == 2:
                role_name, attr_name = parts
            else:
                role_name = ref
                attr_name = attribute_name

            person = self._get_person_by_role(context, role_name)
            if person:
                value = self._get_attribute_value(person, attr_name)
                if value is not None:
                    excluded.add(value)
                    logger.debug(f"Exclude: resolved '{ref}' → '{value}'")
                else:
                    logger.debug(f"Exclude: '{ref}' has no value assigned yet, skipping")
            else:
                logger.debug(f"Exclude: role '{role_name}' not found in context, skipping")

        return excluded

    def _sample_with_exclusion(self, person, household, context: Dict[str, Any],
                                strategy_config: Dict[str, Any],
                                excluded_values: set) -> Any:
        """
        Sample from a probabilistic distribution while excluding specific values.

        Gets the full distribution, removes excluded values, re-normalizes, and
        samples. If every value is excluded, that is a data/config contradiction —
        fail loudly rather than silently sampling the excluded value (adr/0010).

        Args:
            person: Person being assigned
            household: Household venue
            context: Assignment context
            strategy_config: Probabilistic strategy config dict
            excluded_values: Set of values to exclude from sampling

        Returns:
            Sampled attribute value
        """
        data_source_name = strategy_config.get('data_source', 'geo_distribution')

        # Get the geo unit for lookup
        geo_unit = None
        if household and household.geographical_unit:
            geo_unit = household.geographical_unit.name
        elif person.geographical_unit:
            geo_unit = person.geographical_unit.name

        if not geo_unit:
            logger.warning(f"No geo unit for exclusion sampling, person {person.id}")
            return self._fail(person, "no geographical_unit available")

        # Look up full distribution
        probs = self.data_manager.lookup(data_source_name, geo_unit)
        if not probs:
            logger.warning(f"No distribution for {data_source_name}({geo_unit})")
            return self._fail(person, "data source returned no distribution")

        # Remove excluded values
        filtered_probs = {k: v for k, v in probs.items() if k not in excluded_values}

        if not filtered_probs:
            return self._fail(
                person,
                f"all values excluded (excluded={excluded_values}, "
                f"available={set(probs.keys())})",
            )

        # Re-normalize
        total = sum(filtered_probs.values())
        if total <= 0:
            logger.warning(f"Zero total probability after exclusion for person {person.id}")
            return self._fail(person, "zero total probability after exclusion")

        values = list(filtered_probs.keys())
        probabilities = [v / total for v in filtered_probs.values()]

        sampled = np.random.choice(values, p=probabilities)
        logger.debug(
            f"Inheritance (with exclusion): {sampled} for {person.id} "
            f"(excluded={excluded_values})"
        )
        return sampled


class InheritanceStrategy(LogicBlockStrategy):
    """
    Forward inheritance: Parent → Child.

    Children inherit attribute values from parents based on declarative logic
    blocks. Example for ethnicity: same parents → that value (`values[0]`),
    differing parents → `M` (Mixed).
    """

    def assign(self, person, household, context: Dict[str, Any]) -> Any:
        """Assign a value by inheriting from the configured parent roles."""
        attribute_name = context.get('attribute_name')
        parent_roles = self.inherit_config.get('roles', [])

        parent_values = []
        for role_name in parent_roles:
            parent = self._get_person_by_role(context, role_name)
            if parent:
                value = self._get_attribute_value(parent, attribute_name)
                if value is not None:
                    parent_values.append(value)

        if not parent_values:
            return self._marginal_assign(person, household, context)

        return self._run_logic(parent_values, person, household, context, attribute_name)


class ReverseInheritanceStrategy(LogicBlockStrategy):
    """
    Reverse inheritance: Child → Parent.

    When children are assigned first, infer a parent's attribute value from the
    child's, via declarative logic blocks. Example for ethnicity: child W/A/B/O →
    parent copies it; child M → parents differ (nested probabilistic draw, with an
    optional `exclude` to force a second parent to differ from the first).
    """

    def assign(self, person, household, context: Dict[str, Any]) -> Any:
        """Assign a value by inferring it from the configured child role."""
        attribute_name = context.get('attribute_name')

        child_role = self.inherit_config.get('role')
        if not child_role:
            return self._fail(person, "no child role configured for reverse inheritance")

        child = self._get_person_by_role(context, child_role)
        if not child:
            return self._marginal_assign(person, household, context)

        child_value = self._get_attribute_value(child, attribute_name)
        if child_value is None:
            return self._marginal_assign(person, household, context)

        return self._run_logic([child_value], person, household, context, attribute_name)


class ProbabilisticConditionsStrategy(AssignmentStrategy):
    """
    Assigns a set of conditions (e.g. comorbidities) to a person.

    Two `selection_method`s:

    - `independent_bernoulli`: each condition is an independent Bernoulli trial
      on its marginal probability. Ignores any joint count structure in the data.
    - `gated_conditions`: gated hierarchical sampler (adr/0013) that honors the
      joint count structure — `no_condition` = P(0), `has_comorbidity` = P(>=1),
      `multiple_morbidities` = P(>=2) — then draws which conditions from the
      per-condition marginals. See `_sample_gated_conditions`.
    """

    def __init__(self, config: Dict[str, Any], data_manager):
        """Initialize probabilistic conditions strategy."""
        super().__init__(config, data_manager)
        self.strategy_type = "probabilistic_conditions"
        self.conditions = config.get('conditions', [])
        # No default: a config must declare its selection_method (validated at
        # load by validate_assignment_config). The dispatch in assign() still
        # fails loudly if an unknown value reaches it via direct construction.
        self.selection_method = config.get('selection_method')

    def assign(self, person, household, context: Dict[str, Any]) -> List[str]:
        """
        Assign comorbidities to person.

        Args:
            person: Person object
            household: Household venue (optional)
            context: Assignment context

        Returns:
            List of condition names (e.g., ["cvd", "crd"])
        """
        # Get data source name
        data_source_name = self.config.get('data_source')
        if not data_source_name:
            self._fail(person, "probabilistic_conditions has no 'data_source'")

        # Look up probabilities using data source
        source = self.data_manager.get_source(data_source_name)
        if not source:
            self._fail(person, f"data source '{data_source_name}' not found")

        # Perform lookup (raises on a miss — no fallbacks, adr/0010)
        probabilities = source.lookup(person, household, context)

        # Sample conditions based on selection method
        if self.selection_method == 'independent_bernoulli':
            return self._sample_independent_bernoulli(probabilities)
        if self.selection_method == 'gated_conditions':
            return self._sample_gated_conditions(person, probabilities)
        self._fail(person, f"unknown selection_method '{self.selection_method}'")

    def _sample_independent_bernoulli(self, probabilities: Dict[str, float]) -> List[str]:
        """
        Sample conditions independently using Bernoulli trials.

        Each condition is checked independently with its probability.

        Args:
            probabilities: Dict mapping condition names to probabilities

        Returns:
            List of condition names that were sampled
        """
        selected_conditions = []

        for condition in self.conditions:
            condition_name = condition.get('name')
            if not condition_name:
                continue

            # Get probability for this condition
            probability = probabilities.get(condition_name, 0.0)

            # Bernoulli trial
            if np.random.random() < probability:
                selected_conditions.append(condition_name)

        return selected_conditions

    def _sample_gated_conditions(self, person, probabilities: Dict[str, float]) -> List[str]:
        """
        Gated hierarchical comorbidity sampler (adr/0013).

        Honors the joint count structure carried by the data exactly:
          P(0)  = no_condition
          P(>=1) = has_comorbidity      (so P(1) = has_comorbidity - multiple)
          P(>=2) = multiple_morbidities

        1. Draw a count tier {0, 1, >=2} from those joint probabilities.
        2. Draw that many *distinct* conditions weighted by the per-condition
           marginals, without replacement.
        3. For the >=2 tier, draw the actual count from the Poisson-binomial
           distribution implied by the per-condition marginals, conditioned on
           >=2. The data fixes P(>=2) but not the upper tail, so this is the
           explicit modelling assumption for the tail shape.

        Missing or contradictory data fails loudly — no fallbacks (adr/0010).
        """
        p_none = self._require_prob(probabilities, 'no_condition', person)
        p_any = self._require_prob(probabilities, 'has_comorbidity', person)
        p_multi = self._require_prob(probabilities, 'multiple_morbidities', person)

        p_one = p_any - p_multi
        if p_one < -_PROB_TOL:
            self._fail(
                person,
                f"has_comorbidity ({p_any}) < multiple_morbidities ({p_multi}); "
                "P(exactly 1 condition) would be negative",
            )

        tier = np.clip(np.array([p_none, p_one, p_multi], dtype=float), 0.0, None)
        total = tier.sum()
        if total <= 0:
            self._fail(person, "comorbidity count-tier probabilities sum to zero")
        tier /= total

        drawn_tier = np.random.choice(3, p=tier)
        if drawn_tier == 0:
            return []

        names = [c['name'] for c in self.conditions if c.get('name')]
        margins = np.clip(
            np.array([self._require_prob(probabilities, n, person) for n in names], dtype=float),
            0.0, None,
        )

        count = 1 if drawn_tier == 1 else self._sample_multi_count(person, margins)
        return self._pick_distinct_conditions(person, names, margins, count)

    def _require_prob(self, probabilities: Dict[str, float], key: str, person) -> float:
        """Read a probability the gated sampler depends on, or fail loudly (adr/0010)."""
        if key not in probabilities:
            self._fail(person, f"gated_conditions requires '{key}' from the data source")
        return float(probabilities[key])

    def _sample_multi_count(self, person, margins: np.ndarray) -> int:
        """
        Draw a condition count >=2 from the Poisson-binomial of the per-condition
        marginals, conditioned on >=2 (adr/0013, step 3).
        """
        # Poisson-binomial PMF over the marginals: convolve each [1-p, p].
        pmf = np.array([1.0])
        for p in margins:
            pmf = np.convolve(pmf, [1.0 - p, p])

        tail = pmf[2:]
        total = tail.sum()
        if total <= 0:
            self._fail(
                person,
                "data implies >=2 comorbidities but the per-condition marginals "
                "cannot produce two or more",
            )
        counts = np.arange(2, len(pmf))
        return int(np.random.choice(counts, p=tail / total))

    def _pick_distinct_conditions(self, person, names: List[str],
                                  margins: np.ndarray, count: int) -> List[str]:
        """Pick `count` distinct conditions weighted by their marginals, no replacement."""
        positive = margins > 0
        valid = [name for name, ok in zip(names, positive) if ok]
        if count > len(valid):
            self._fail(
                person,
                f"cannot draw {count} distinct conditions from {len(valid)} "
                "with positive probability",
            )
        weights = margins[positive]
        weights = weights / weights.sum()
        chosen = np.random.choice(valid, size=count, replace=False, p=weights)
        return [str(c) for c in chosen]


class CommutingLikelihoodStrategy(AssignmentStrategy):
    """
    Assigns workplace location based on origin-destination commuting flows.

    Samples from an origin-destination matrix weighted by likelihood.
    Can assign multiple attributes (e.g., workplace_location and work_mode).

    Supports batch assignment to reduce repeated lookups.
    """

    def __init__(self, config: Dict[str, Any], data_manager):
        """Initialize commuting likelihood strategy."""
        super().__init__(config, data_manager)
        self.data_source_name = config.get('data_source')
        self.outputs = config.get('outputs', {})

    def _resolve_origin_code(self, person) -> Optional[str]:
        """
        Resolve person's origin geographical unit to the correct level for O-D matrix lookup.

        This handles complex data source configurations like ancestor lookups.

        Args:
            person: Person object

        Returns:
            Origin code string, or None if resolution fails
        """
        # Get person's origin (residence) geographical unit
        origin_geo_unit = getattr(person, 'geographical_unit', None)
        if not origin_geo_unit:
            return None

        # Get the data source to check its configuration
        source = self.data_manager.get_source(self.data_source_name)
        if not source:
            return None

        # Resolve origin based on data source key configuration
        # Check if this is an O-D matrix source with key_columns config
        if hasattr(source, '_file_configs') and source._file_configs:
            file_config = source._file_configs[0]
            key_columns = file_config.get('key_columns', {})

            if key_columns:
                # Get first key column config (origin)
                first_key_config = list(key_columns.values())[0]

                # Check if we need to traverse hierarchy
                if isinstance(first_key_config, dict):
                    lookup_type = first_key_config.get('type')
                    if lookup_type == 'ancestor_lookup':
                        level = first_key_config.get('level')
                        property_name = first_key_config.get('property', 'name')

                        # Traverse to ancestor level
                        ancestor = origin_geo_unit.get_ancestor_by_level(level)
                        if ancestor:
                            return getattr(ancestor, property_name)
                        else:
                            return None
                    else:
                        return origin_geo_unit.name
                else:
                    return origin_geo_unit.name
            else:
                return origin_geo_unit.name
        else:
            return origin_geo_unit.name

    def assign_batch(self, people_list: List, households_list: List, contexts_list: List[Dict[str, Any]]) -> List[Any]:
        """
        Batch assignment to minimize repeated O-D matrix lookups.

        Groups people by origin code and processes each group together.

        Args:
            people_list: List of Person objects
            households_list: List of Household objects (parallel to people_list)
            contexts_list: List of context dicts (parallel to people_list)

        Returns:
            List of assigned values (parallel to people_list)
            - If single output: list of values
            - If multiple outputs: list of dicts
        """
        from collections import defaultdict

        # Get data source
        source = self.data_manager.get_source(self.data_source_name)
        if not source:
            logger.warning(f"Data source '{self.data_source_name}' not found")
            return [self._fail(person, "no commuting-flow row for this origin")
                    for person, household, context in zip(people_list, households_list, contexts_list)]

        # Group people by origin_code
        origin_groups = defaultdict(list)

        for i, person in enumerate(people_list):
            origin_code = self._resolve_origin_code(person)
            if origin_code:
                origin_groups[origin_code].append(i)

        # Results array
        results = [None] * len(people_list)

        # Process each origin group
        for origin_code, indices in origin_groups.items():
            # Look up destinations from O-D matrix
            destinations = source.lookup(origin_code)
            if not destinations:
                logger.warning(f"No destinations found for origin {origin_code}")
                # Fill with fallback for this group
                for idx in indices:
                    person = people_list[idx]
                    household = households_list[idx]
                    context = contexts_list[idx]
                    results[idx] = self._fail(person, "no commuting-flow row for this origin")
                continue

            # Prepare sampling arrays
            # destinations is List[(destination, metadata_dict, likelihood)]
            dest_codes = [dest for dest, meta, lik in destinations]
            likelihoods = [lik for dest, meta, lik in destinations]
            metadata_list = [meta for dest, meta, lik in destinations]

            # BATCH SAMPLE: Sample destinations for all people in this origin group at once
            n_samples = len(indices)
            sampled_indices = np.random.choice(len(dest_codes), size=n_samples, p=likelihoods)

            # Build outputs for each person
            for idx, sampled_idx in zip(indices, sampled_indices):
                sampled_dest = dest_codes[sampled_idx]
                sampled_metadata = metadata_list[sampled_idx]
                results[idx] = self._build_output(sampled_dest, sampled_metadata)

        return results

    def assign(self, person, household, context: Dict[str, Any]) -> Any:
        """
        Assign workplace location and work mode based on commuting flows.

        Args:
            person: Person object
            household: Household object (optional, may be None for person-level assignment)
            context: Assignment context

        Returns:
            If single output: returns the assigned value
            If multiple outputs: returns dict with all assigned values
        """
        # Resolve person's origin to correct geographical level
        origin_code = self._resolve_origin_code(person)
        if not origin_code:
            logger.warning(f"Could not resolve origin code for person {person.id}")
            return self._fail(person, "no commuting-flow row for this origin")

        # Get data source
        source = self.data_manager.get_source(self.data_source_name)
        if not source:
            logger.warning(f"Data source '{self.data_source_name}' not found")
            return self._fail(person, "no commuting-flow row for this origin")

        # Look up destinations from O-D matrix
        destinations = source.lookup(origin_code)
        if not destinations:
            logger.warning(f"No destinations found for origin {origin_code}")
            return self._fail(person, "no commuting-flow row for this origin")

        # Sample from destinations weighted by likelihood
        # destinations is List[(destination, metadata_dict, likelihood)]
        dest_codes = [dest for dest, meta, lik in destinations]
        likelihoods = [lik for dest, meta, lik in destinations]
        metadata_list = [meta for dest, meta, lik in destinations]

        # Sample one destination
        idx = np.random.choice(len(dest_codes), p=likelihoods)
        sampled_dest = dest_codes[idx]
        sampled_metadata = metadata_list[idx]

        # Build output based on configured outputs
        result = self._build_output(sampled_dest, sampled_metadata)
        if not isinstance(result, dict):
            return result
        logger.debug(f"Commuting: {person.id} -> {result}")
        return result

    def _build_output(self, sampled_dest, sampled_metadata):
        """
        Build return value from sampled destination and metadata.

        Returns:
            Single value (if one output configured) or dict (if multiple).
        """
        if len(self.outputs) == 1:
            output_attr, output_source = list(self.outputs.items())[0]
            if output_source == 'destination':
                return sampled_dest
            if output_source in sampled_metadata:
                return sampled_metadata[output_source]
            raise ValueError(
                f"Output source '{output_source}' not found in metadata keys "
                f"{list(sampled_metadata.keys())}. Check outputs config."
            )

        result = {}
        for output_attr, output_source in self.outputs.items():
            if output_source == 'destination':
                result[output_attr] = sampled_dest
            elif output_source in sampled_metadata:
                result[output_attr] = sampled_metadata[output_source]
            else:
                raise ValueError(
                    f"Output source '{output_source}' for attribute '{output_attr}' "
                    f"not found in metadata keys {list(sampled_metadata.keys())}. "
                    f"Check outputs config."
                )
        return result


class GUSamplerStrategy(AssignmentStrategy):
    """
    Samples a geographical unit within a parent GU based on weighted distribution.
    Generic strategy that works with any geographical hierarchy level.

    Supports batch assignment to reduce repeated lookups.
    """

    def __init__(self, config: Dict[str, Any], data_manager):
        """Initialize geographical unit sampler strategy."""
        super().__init__(config, data_manager)
        self.data_source_name = config.get('data_source')

    def assign_batch(self, people_list: List, households_list: List, contexts_list: List[Dict[str, Any]]) -> List[Any]:
        """
        Batch assignment to minimize repeated data lookups.

        Groups people by workplace_parent_gu and processes each group together.

        Args:
            people_list: List of Person objects
            households_list: List of Household objects (parallel to people_list)
            contexts_list: List of context dicts (parallel to people_list)

        Returns:
            List of sampled geographical unit codes (parallel to people_list)
        """
        from collections import defaultdict

        # Get data source
        source = self.data_manager.get_source(self.data_source_name)
        if not source:
            raise KeyError(
                f"Data source '{self.data_source_name}' is not registered. "
                "No fallbacks (adr/0010)."
            )

        # Group people by workplace parent GU
        gu_groups = defaultdict(list)

        for i, person in enumerate(people_list):
            workplace_parent_gu = person.properties.get('workplace_location')
            if not workplace_parent_gu:
                self._fail(person, "no workplace_location assigned")
            gu_groups[workplace_parent_gu].append(i)

        # Results array
        results = [None] * len(people_list)

        # Process each group
        for workplace_parent_gu, indices in gu_groups.items():
            gu_probs = source.lookup(workplace_parent_gu)  # raises on miss (adr/0010)
            sampled_gus = self._weighted_draw(gu_probs, people_list[indices[0]], size=len(indices))
            for idx, sampled_gu in zip(indices, sampled_gus):
                results[idx] = sampled_gu

        return results

    def assign(self, person, household, context: Dict[str, Any]) -> Any:
        """
        Sample a geographical unit within person's workplace parent GU.

        Args:
            person: Person object
            household: Household object (optional)
            context: Assignment context

        Returns:
            Sampled geographical unit code
        """
        # Get workplace_location from person properties
        workplace_parent_gu = person.properties.get('workplace_location')
        if not workplace_parent_gu:
            self._fail(person, "no workplace_location assigned")

        # Look up GU distribution for this parent GU
        source = self.data_manager.get_source(self.data_source_name)
        if not source:
            raise KeyError(
                f"Data source '{self.data_source_name}' is not registered. "
                "No fallbacks (adr/0010)."
            )

        gu_probs = source.lookup(workplace_parent_gu)  # raises on miss (adr/0010)
        sampled_gu = self._weighted_draw(gu_probs, person)
        logger.debug(f"GU Sampler: {sampled_gu} for person {person.id} in parent GU {workplace_parent_gu}")
        return sampled_gu


class CategoricalSamplerStrategy(AssignmentStrategy):
    """
    Samples ONE category from a probability distribution.

    Works with MultiKeyLookupSource that returns {category: probability} dicts.
    Unlike ProbabilisticConditionsStrategy which samples multiple yes/no conditions,
    this samples exactly one mutually-exclusive category (e.g., one industry sector).

    Supports batch assignment to reduce repeated lookups.
    """

    def __init__(self, config: Dict[str, Any], data_manager):
        """Initialize categorical sampler strategy."""
        super().__init__(config, data_manager)
        self.data_source_name = config.get('data_source')

    def assign_batch(self, people_list: List, households_list: List, contexts_list: List[Dict[str, Any]]) -> List[Any]:
        """
        Batch assignment to minimize repeated data lookups.

        Groups people by their lookup keys and processes each group together.

        Args:
            people_list: List of Person objects
            households_list: List of Household objects (parallel to people_list)
            contexts_list: List of context dicts (parallel to people_list)

        Returns:
            List of sampled category values (parallel to people_list)
        """
        from collections import defaultdict

        # Get data source
        source = self.data_manager.get_source(self.data_source_name)
        if not source:
            raise KeyError(
                f"Data source '{self.data_source_name}' is not registered. "
                "No fallbacks (adr/0010)."
            )

        # Group people by their lookup keys
        # lookup_key_groups: {lookup_key: [indices]}
        lookup_key_groups = defaultdict(list)

        for i, (person, household, context) in enumerate(zip(people_list, households_list, contexts_list)):
            # Look up probability distribution
            probs = source.lookup(person, household, context)
            if probs:
                # Create a hashable key from the probabilities
                lookup_key = tuple(sorted(probs.items()))
                lookup_key_groups[lookup_key].append((i, probs))

        # Results array
        results = [None] * len(people_list)

        # Process each group
        for lookup_key, group_data in lookup_key_groups.items():
            indices = [idx for idx, _ in group_data]
            probs = group_data[0][1]  # All have same probs for this key
            sampled_values = self._weighted_draw(probs, people_list[indices[0]], size=len(indices))
            for idx, value in zip(indices, sampled_values):
                results[idx] = value

        return results

    def assign(self, person, household, context: Dict[str, Any]) -> Any:
        """
        Sample one category from probability distribution.

        Args:
            person: Person object
            household: Household object (optional)
            context: Assignment context

        Returns:
            Sampled category value
        """
        # Get data source
        source = self.data_manager.get_source(self.data_source_name)
        if not source:
            raise KeyError(
                f"Data source '{self.data_source_name}' is not registered. "
                "No fallbacks (adr/0010)."
            )

        # Look up probability distribution
        probs = source.lookup(person, household, context)
        sampled = self._weighted_draw(probs, person)
        logger.debug(f"Categorical: {sampled} for person {person.id}")
        return sampled


class ConstantStrategy(AssignmentStrategy):
    """
    Assigns a fixed, constant value.

    This is useful for static attributes or default values that apply
    unconditionally to a given role or household structure.
    """

    def __init__(self, config: Dict[str, Any], data_manager):
        """Initialize constant strategy."""
        super().__init__(config, data_manager)
        self.value = config.get('value')

    def assign_batch(self, people_list: List, households_list: List, contexts_list: List[Dict[str, Any]]) -> List[Any]:
        """Batch assignment - all receive the same value."""
        if self.value is None:
            # Match assign() behavior: delegate to per-person fallback
            return [self.assign(p, h, c) for p, h, c in zip(people_list, households_list, contexts_list)]
        return [self.value] * len(people_list)

    def assign(self, person, household, context: Dict[str, Any]) -> Any:
        """Assign the constant value."""
        if self.value is None:
            logger.warning(f"ConstantStrategy: No value configured for assignment to person {person.id}")
            return self._fail(person, "constant strategy has no 'value'")

        return self.value


class StrategyFactory:
    """
    Factory for creating strategy instances.

    Maps strategy type strings to strategy classes.
    """

    _strategy_map = {
        'probabilistic': ProbabilisticStrategy,
        'partnership': PartnershipStrategy,
        'inheritance': InheritanceStrategy,
        'reverse_inheritance': ReverseInheritanceStrategy,
        'probabilistic_conditions': ProbabilisticConditionsStrategy,
        'commuting_likelihood': CommutingLikelihoodStrategy,
        'geographical_unit_sampler': GUSamplerStrategy,
        'categorical_sampler': CategoricalSamplerStrategy,
        'constant': ConstantStrategy,
    }

    @classmethod
    def create_strategy(cls, config: Dict[str, Any], data_manager) -> AssignmentStrategy:
        """
        Create strategy instance from configuration.

        Args:
            config: Strategy configuration dict
            data_manager: DataSourceManager instance

        Returns:
            Strategy instance

        Raises:
            ValueError: If strategy type is unknown
        """
        validate_assignment_config(config)

        strategy_class = cls._strategy_map.get(config['strategy'])
        return strategy_class(config, data_manager)
