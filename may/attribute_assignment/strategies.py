"""
Assignment strategies for attribute assignment system.

This module implements the simplified strategies that work with:
- Roles mapped to subsets (no complex conditions)
- Structure-based assignment (Family/Couple/Independents)
- Simple inheritance and partnership rules
"""

import logging
import numpy as np
from typing import Dict, List, Any, Optional
from functools import lru_cache

logger = logging.getLogger("may.attribute_assignment.strategies")


@lru_cache(maxsize=2048)
def _compile_expression(expr: str, mode: str = 'eval'):
    """
    Cached compilation of Python expressions.

    Args:
        expr: The expression string to compile
        mode: 'eval' for expressions, 'exec' for statements

    Returns:
        Compiled code object
    """
    return compile(expr, '<string>', mode)


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
        Get attribute value from person (checks properties dict first).

        Args:
            person: Person object
            attribute_name: Name of attribute

        Returns:
            Attribute value or None
        """
        if person is None:
            return None

        # Check properties dict first
        if hasattr(person, 'properties') and attribute_name in person.properties:
            return person.properties[attribute_name]

        # Fall back to direct attribute
        return getattr(person, attribute_name, None)


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
        # Get geo unit from household
        if not household or not household.geographical_unit:
            logger.warning("No geographical unit found for household")
            return None

        geo_unit = household.geographical_unit.name

        # Get probability distribution from data source
        probs = self.data_manager.lookup(self.data_source_name, geo_unit)
        if not probs:
            logger.warning(f"No probabilities found for {self.data_source_name}({geo_unit})")
            return None

        # Sample from distribution
        values = list(probs.keys())
        probabilities = list(probs.values())
        sampled = np.random.choice(values, p=probabilities)

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
            return self._fallback_probabilistic(person, household, context)

        # Get first person's attribute value
        attribute_name = context.get('attribute_name', 'ethnicity')
        first_value = self._get_attribute_value(first_person, attribute_name)
        if not first_value:
            logger.warning(f"No {attribute_name} found for {self.partner_role}")
            return self._fallback_probabilistic(person, household, context)

        # Get geo unit
        if not household or not household.geographical_unit:
            logger.warning("No geographical unit found for household")
            return self._fallback_probabilistic(person, household, context)

        geo_unit = household.geographical_unit.name

        # Look up pair probabilities
        probs = self.data_manager.lookup(self.data_source_name, geo_unit, first_value)
        if not probs:
            logger.warning(f"No pair probabilities for {geo_unit}, {first_value}")
            return self._fallback_probabilistic(person, household, context)

        # Sample from distribution
        values = list(probs.keys())
        probabilities = list(probs.values())
        sampled = np.random.choice(values, p=probabilities)

        logger.debug(f"Partnership: {sampled} (partner of {first_value}) for {person.id}")
        return sampled

    def _fallback_probabilistic(self, person, household, context: Dict[str, Any]) -> Any:
        """
        Fallback to geographical distribution if pair data not available.

        Args:
            person: Person object
            household: Household object
            context: Assignment context

        Returns:
            Sampled value from geo distribution
        """
        logger.debug("Falling back to geographical distribution")
        fallback_strategy = ProbabilisticStrategy(
            {'strategy': 'probabilistic', 'data_source': 'geo_distribution'},
            self.data_manager
        )
        return fallback_strategy.assign(person, household, context)


class InheritanceStrategy(AssignmentStrategy):
    """
    Forward inheritance: Parent → Child.

    Children inherit attribute values from parents based on combination rules.
    Logic is completely configurable via YAML logic blocks.

    Example for ethnicity:
    - Same + Same = Same (W+W=W, A+A=A, etc.)
    - Different = Mixed (W+A=M, W+B=M, etc.)
    - Mixed + Any = Mixed (M+X=M)

    Simplified from V1 - no complex conditions, just straightforward logic.
    """

    def __init__(self, config: Dict[str, Any], data_manager):
        """Initialize inheritance strategy - completely generic."""
        super().__init__(config, data_manager)
        # Store the full config - we'll evaluate logic blocks
        self.inherit_config = config.get('inherit_from', {})
        self.logic_blocks = config.get('logic', [])

    def assign(self, person, household, context: Dict[str, Any]) -> Any:
        """
        Assign value based on inheritance from parent roles (completely generic).

        Evaluates logic blocks defined in YAML configuration.

        Args:
            person: Person object
            household: Household object
            context: Assignment context

        Returns:
            Inherited attribute value
        """
        attribute_name = context.get('attribute_name')

        # Get roles to inherit from
        parent_roles = self.inherit_config.get('roles', [])

        # Collect parent values
        parent_values = []
        for role_name in parent_roles:
            parent = self._get_person_by_role(context, role_name)
            if parent:
                value = self._get_attribute_value(parent, attribute_name)
                if value:
                    parent_values.append(value)

        if not parent_values:
            logger.warning(f"No parent values found for inheritance")
            return self._fallback_probabilistic(person, household, context)

        # Evaluate logic blocks
        unique_values = list(set(parent_values))

        # Create evaluation context for logic blocks
        eval_context = {
            'values': parent_values,
            'unique_values': unique_values,
            'count': lambda x: len(x)
        }

        # Evaluate each logic block
        for logic_block in self.logic_blocks:
            when_condition = logic_block.get('when')
            then_action = logic_block.get('then')

            try:
                # Evaluate the condition
                if self._evaluate_condition(when_condition, eval_context):
                    # Execute the 'then' action
                    if isinstance(then_action, str):
                        # Simple value like "M" or "values[0]"
                        result = self._resolve_value(then_action, eval_context)
                        logger.debug(f"Inheritance: {result} for {person.id}")
                        return result
                    elif isinstance(then_action, dict):
                        # Nested strategy - not implemented yet, fall back
                        logger.warning(f"Nested strategy in inheritance not yet supported")
                        return self._fallback_probabilistic(person, household, context)
            except Exception as e:
                logger.warning(f"Error evaluating inheritance logic: {e}")
                continue

        # No logic matched - fallback
        return self._fallback_probabilistic(person, household, context)

    def _evaluate_condition(self, condition: str, context: dict) -> bool:
        """Evaluate a when condition."""
        try:
            # Use cached compiled expression for better performance
            code = _compile_expression(condition, 'eval')
            return eval(code, {"__builtins__": {}}, context)
        except:
            return False

    def _resolve_value(self, value_expr: str, context: dict) -> Any:
        """Resolve a value expression like 'values[0]' or 'M'."""
        try:
            # Use cached compiled expression for better performance
            code = _compile_expression(value_expr, 'eval')
            return eval(code, {"__builtins__": {}}, context)
        except:
            # If it fails, return as literal string
            return value_expr

    def _fallback_probabilistic(self, person, household, context: Dict[str, Any]) -> Any:
        """Fallback to geographical distribution if no parents found."""
        logger.debug("Falling back to geographical distribution")
        fallback_strategy = ProbabilisticStrategy(
            {'strategy': 'probabilistic', 'data_source': 'geo_distribution'},
            self.data_manager
        )
        return fallback_strategy.assign(person, household, context)


class ReverseInheritanceStrategy(AssignmentStrategy):
    """
    Reverse inheritance: Child → Parent.

    When children are assigned first, infer parent attribute values.
    Logic is completely configurable via YAML logic blocks.

    Example for ethnicity:
    - Child is W/A/B/O → Both parents must be same (both W, both A, etc.)
    - Child is M → Parents must differ (sample two different values from geo distribution)

    Enables "kids first" assignment in certain household patterns.
    """

    def __init__(self, config: Dict[str, Any], data_manager):
        """Initialize reverse inheritance strategy - completely generic."""
        super().__init__(config, data_manager)
        # Store the full config - we'll evaluate logic blocks
        self.inherit_config = config.get('inherit_from', {})
        self.logic_blocks = config.get('logic', [])

    def assign(self, person, household, context: Dict[str, Any]) -> Any:
        """
        Assign value based on reverse inheritance (generic - evaluates logic blocks).

        Args:
            person: Person object (parent being assigned)
            household: Household object
            context: Assignment context

        Returns:
            Inferred parent value
        """
        attribute_name = context.get('attribute_name')

        # Get child role to inherit from
        child_role = self.inherit_config.get('role')
        if not child_role:
            logger.warning("No child role specified for reverse inheritance")
            return self._fallback_probabilistic(person, household, context)

        # Get child's attribute value
        child = self._get_person_by_role(context, child_role)
        if not child:
            logger.warning(f"Child role '{child_role}' not found")
            return self._fallback_probabilistic(person, household, context)

        child_value = self._get_attribute_value(child, attribute_name)
        if not child_value:
            logger.warning(f"No value found for child role '{child_role}'")
            return self._fallback_probabilistic(person, household, context)

        # Create evaluation context for logic blocks
        # Make child value accessible as "primary_adult.ethnicity" format
        eval_context = {child_role: type('obj', (object,), {attribute_name: child_value})()}

        # Evaluate each logic block
        for logic_block in self.logic_blocks:
            when_condition = logic_block.get('when')
            then_action = logic_block.get('then')

            try:
                # Evaluate the condition
                if self._evaluate_condition_with_context(when_condition, eval_context, child_role, attribute_name, child_value):
                    # Execute the 'then' action
                    if isinstance(then_action, str):
                        # Simple value - might be literal or reference to child value
                        if then_action == f"{child_role}.{attribute_name}":
                            result = child_value
                        else:
                            result = then_action
                        logger.debug(f"Reverse inheritance: {result} for {person.id}")
                        return result
                    elif isinstance(then_action, dict):
                        # Nested strategy - create and execute it
                        strategy_type = then_action.get('strategy')
                        if strategy_type == 'probabilistic':
                            fallback_strategy = ProbabilisticStrategy(then_action, self.data_manager)
                            return fallback_strategy.assign(person, household, context)
                        else:
                            logger.warning(f"Unknown nested strategy: {strategy_type}")
                            return self._fallback_probabilistic(person, household, context)
            except Exception as e:
                logger.warning(f"Error evaluating reverse inheritance logic: {e}")
                continue

        # No logic matched - fallback
        return self._fallback_probabilistic(person, household, context)

    def _evaluate_condition_with_context(self, condition: str, eval_context: dict,
                                         child_role: str, attribute_name: str, child_value: Any) -> bool:
        """Evaluate a when condition with attribute access."""
        try:
            # Build a safe evaluation context
            safe_context = {
                "__builtins__": {},
                child_role: eval_context[child_role]
            }
            return eval(condition, safe_context, {})
        except:
            return False

    def _fallback_probabilistic(self, person, household, context: Dict[str, Any]) -> Any:
        """Fallback to geographical distribution."""
        fallback_strategy = ProbabilisticStrategy(
            {'strategy': 'probabilistic', 'data_source': 'geo_distribution'},
            self.data_manager
        )
        return fallback_strategy.assign(person, household, context)


class ProbabilisticConditionsStrategy(AssignmentStrategy):
    """
    Assigns multiple conditions independently based on probabilities.

    Each condition is checked with a Bernoulli trial (independent sampling).
    Person can end up with 0, 1, or multiple conditions.
    """

    def __init__(self, config: Dict[str, Any], data_manager):
        """Initialize probabilistic conditions strategy."""
        super().__init__(config, data_manager)
        self.strategy_type = "probabilistic_conditions"
        self.conditions = config.get('conditions', [])
        self.selection_method = config.get('selection_method', 'independent_bernoulli')

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
            logger.warning("No data_source specified for probabilistic_conditions strategy")
            return []

        # Look up probabilities using data source
        source = self.data_manager.get_source(data_source_name)
        if not source:
            logger.warning(f"Data source '{data_source_name}' not found")
            return []

        # Perform lookup
        probabilities = source.lookup(person, household, context)
        if not probabilities:
            logger.warning(f"No probabilities found for person {person.id}")
            return []

        # Sample conditions based on selection method
        if self.selection_method == 'independent_bernoulli':
            return self._sample_independent_bernoulli(probabilities)
        else:
            logger.warning(f"Unknown selection method: {self.selection_method}")
            return []

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


class CommutingLikelihoodStrategy(AssignmentStrategy):
    """
    Assigns workplace location based on origin-destination commuting flows.

    Samples from an origin-destination matrix weighted by likelihood.
    Can assign multiple attributes (e.g., workplace_location and work_mode).
    """

    def __init__(self, config: Dict[str, Any], data_manager):
        """Initialize commuting likelihood strategy."""
        super().__init__(config, data_manager)
        self.data_source_name = config.get('data_source')
        self.outputs = config.get('outputs', {})

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
        # Get person's origin (residence) geographical unit
        # Need to resolve to the correct level (e.g., LGU name) based on data source config
        origin_geo_unit = getattr(person, 'geographical_unit', None)
        if not origin_geo_unit:
            logger.warning(f"No geographical unit found for person {person.id}")
            return self._get_fallback(person, household, context)

        # Get the data source to check its configuration
        source = self.data_manager.get_source(self.data_source_name)
        if not source:
            logger.warning(f"Data source '{self.data_source_name}' not found")
            return self._get_fallback(person, household, context)

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
                            origin_code = getattr(ancestor, property_name)
                        else:
                            logger.warning(f"Could not find {level} ancestor for {origin_geo_unit.name}")
                            return self._get_fallback(person, household, context)
                    else:
                        origin_code = origin_geo_unit.name
                else:
                    origin_code = origin_geo_unit.name
            else:
                origin_code = origin_geo_unit.name
        else:
            origin_code = origin_geo_unit.name

        # Look up destinations from O-D matrix
        destinations = source.lookup(origin_code)
        if not destinations:
            logger.warning(f"No destinations found for origin {origin_code}")
            return self._get_fallback(person, household, context)

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
        if len(self.outputs) == 1:
            # Single output - return just the value
            output_attr, output_source = list(self.outputs.items())[0]
            if output_source == 'destination':
                return sampled_dest
            elif output_source in sampled_metadata:
                return sampled_metadata[output_source]
            else:
                logger.warning(f"Output source '{output_source}' not found in metadata")
                return sampled_dest
        else:
            # Multiple outputs - return dict
            result = {}
            for output_attr, output_source in self.outputs.items():
                if output_source == 'destination':
                    result[output_attr] = sampled_dest
                elif output_source in sampled_metadata:
                    result[output_attr] = sampled_metadata[output_source]
                else:
                    logger.warning(f"Output source '{output_source}' not found")

            logger.debug(f"Commuting: {person.id} -> {result}")
            return result

    def _get_fallback(self, person, household, context):
        """Get fallback value when commuting data not available."""
        # Default fallback: work in same location as residence
        fallback_config = self.config.get('fallback', {})
        fallback_strategy_type = fallback_config.get('strategy')

        if fallback_strategy_type == 'constant':
            # Return constant values
            data_source_name = fallback_config.get('data_source')
            if data_source_name:
                fallback_source = self.data_manager.get_source(data_source_name)
                if fallback_source:
                    return fallback_source.lookup(person)

            # Hard-coded fallback: work at home
            if len(self.outputs) == 1:
                return person.geographical_unit.name
            else:
                return {
                    'workplace_location': person.geographical_unit.name,
                    'work_mode': 'Normal'
                }

        return None


class GUSamplerStrategy(AssignmentStrategy):
    """
    Samples a geographical unit within a parent GU based on weighted distribution.
    Generic strategy that works with any geographical hierarchy level.
    """

    def __init__(self, config: Dict[str, Any], data_manager):
        """Initialize geographical unit sampler strategy."""
        super().__init__(config, data_manager)
        self.data_source_name = config.get('data_source')

    def assign(self, person, household, context: Dict[str, Any]) -> Any:
        """
        Sample a geographical unit within person's parent GU.
        Falls back to home parent GU if workplace parent GU has no data.

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
            logger.warning(f"No workplace_location found for person {person.id}")
            return None

        # Look up GU distribution for this parent GU
        source = self.data_manager.get_source(self.data_source_name)
        if not source:
            logger.warning(f"Data source '{self.data_source_name}' not found")
            return None

        gu_probs = source.lookup(workplace_parent_gu)

        # Fallback: if no data for workplace parent GU, try home parent GU
        if not gu_probs:
            # Get person's home parent GU from their geographical_unit
            home_parent_gu = None
            if person.geographical_unit:
                home_parent_gu_obj = person.geographical_unit.get_ancestor_by_level('LGU')
                if home_parent_gu_obj:
                    home_parent_gu = home_parent_gu_obj.name
                else:
                    logger.debug(f"Person {person.id} GU '{person.geographical_unit.name}' has no LGU ancestor")
            else:
                logger.debug(f"Person {person.id} has no geographical_unit set")

            if home_parent_gu:
                logger.debug(f"No GU distribution for workplace parent GU '{workplace_parent_gu}', "
                           f"falling back to home parent GU '{home_parent_gu}'")
                gu_probs = source.lookup(home_parent_gu)

            if not gu_probs:
                logger.warning(f"No GU distribution found for parent GU '{workplace_parent_gu}' "
                             f"or home parent GU '{home_parent_gu}'")
                return None

        # Sample GU weighted by distribution
        gu_codes = list(gu_probs.keys())
        probabilities = list(gu_probs.values())
        sampled_gu = np.random.choice(gu_codes, p=probabilities)

        logger.debug(f"GU Sampler: {sampled_gu} for person {person.id} in parent GU {workplace_parent_gu}")
        return sampled_gu


class CategoricalSamplerStrategy(AssignmentStrategy):
    """
    Samples ONE category from a probability distribution.

    Works with MultiKeyLookupSource that returns {category: probability} dicts.
    Unlike ProbabilisticConditionsStrategy which samples multiple yes/no conditions,
    this samples exactly one mutually-exclusive category (e.g., one industry sector).
    """

    def __init__(self, config: Dict[str, Any], data_manager):
        """Initialize categorical sampler strategy."""
        super().__init__(config, data_manager)
        self.data_source_name = config.get('data_source')

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
            logger.warning(f"Data source '{self.data_source_name}' not found")
            return None

        # Look up probability distribution
        probs = source.lookup(person, household, context)
        if not probs:
            logger.warning(f"No probabilities found for person {person.id}")
            return None

        # Sample one category
        categories = list(probs.keys())
        probabilities = list(probs.values())

        # Normalize if needed
        total = sum(probabilities)
        if total <= 0:
            logger.warning(f"Invalid probabilities (sum={total}) for person {person.id}")
            return None

        if abs(total - 1.0) > 0.01:  # Not normalized
            probabilities = [p / total for p in probabilities]

        sampled = np.random.choice(categories, p=probabilities)

        logger.debug(f"Categorical: {sampled} for person {person.id}")
        return sampled


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
        strategy_type = config.get('strategy')
        if not strategy_type:
            raise ValueError("Strategy configuration must include 'strategy' field")

        strategy_class = cls._strategy_map.get(strategy_type)
        if not strategy_class:
            raise ValueError(f"Unknown strategy type: {strategy_type}")

        return strategy_class(config, data_manager)
