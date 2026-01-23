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

    def _record_fallback(self, context: Dict[str, Any], reason: str):
        """Record the reason for fallback in the context for diagnostics."""
        context['fallback_reason'] = reason
        logger.debug(f"      ! Fallback: {reason}")

    def _fallback(self, person, household, context: Dict[str, Any], reason: str) -> Any:
        """
        Execute fallback strategy (either configured in YAML or default geo).
        """
        self._record_fallback(context, reason)
        
        # Check if a custom fallback is configured in the YAML
        fallback_config = self.config.get('fallback')
        if fallback_config:
            strategy_type = fallback_config.get('strategy')
            if strategy_type == 'probabilistic':
                strat = ProbabilisticStrategy(fallback_config, self.data_manager)
                return strat.assign(person, household, context)
            elif strategy_type == 'constant':
                return fallback_config.get('value')
        
        # Default: Probabilistic geo distribution
        strat = ProbabilisticStrategy(
            {'strategy': 'probabilistic', 'data_source': 'geo_distribution'},
            self.data_manager
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
            return self._fallback(person, household, context, "PARTNER_ROLE_NOT_FOUND")

        # Get first person's attribute value
        attribute_name = context.get('attribute_name')
        first_value = self._get_attribute_value(first_person, attribute_name)
        if not first_value:
            logger.warning(f"No {attribute_name} found for {self.partner_role}")
            return self._fallback(person, household, context, "PARTNER_VALUE_MISSING")

        if not household or not household.geographical_unit:
            logger.warning("No geographical unit found for household")
            return self._fallback(person, household, context, "GEO_UNIT_MISSING")

        geo_unit = household.geographical_unit.name

        # Look up pair probabilities
        probs = self.data_manager.lookup(self.data_source_name, geo_unit, first_value)
        if not probs:
            logger.warning(f"No pair probabilities for {geo_unit}, {first_value}")
            return self._fallback(person, household, context, "DATA_SOURCE_MISSING")

        # Sample from distribution
        values = list(probs.keys())
        probabilities = list(probs.values())
        sampled = np.random.choice(values, p=probabilities)

        logger.debug(f"Partnership: {sampled} (partner of {first_value}) for {person.id}")
        return sampled



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
            return self._fallback(person, household, context, "NO_PARENT_VALUES")

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
                        return self._fallback(person, household, context, "NESTED_STRATEGY_UNSUPPORTED")
            except Exception as e:
                logger.warning(f"Error evaluating inheritance logic: {e}")
                continue

        # No logic matched - fallback
        return self._fallback(person, household, context, "LOGIC_NO_MATCH")

    def _evaluate_condition(self, condition: str, context: dict) -> bool:
        """Evaluate a when condition with fast-paths for common patterns."""
        # FAST PATH: These account for >90% of ethnicity inheritance calls
        if condition == "count(unique_values) == 1":
            return len(context['unique_values']) == 1
        if condition == "count(unique_values) > 1":
            return len(context['unique_values']) > 1
            
        try:
            # Fallback to cached eval for complex conditions
            code = _compile_expression(condition, 'eval')
            return eval(code, {"__builtins__": {}}, context)
        except:
            return False

    def _resolve_value(self, value_expr: str, context: dict) -> Any:
        """Resolve a value expression with fast-paths for common patterns."""
        # FAST PATH: Common resolutions like 'M' or 'values[0]'
        if value_expr == "values[0]":
            return context['values'][0] if context['values'] else None
        if len(value_expr) <= 2: # Likely a literal code like "M", "W", etc.
            # If it's in context, it's a variable, but for letters it's usually literal
            if value_expr not in context:
                return value_expr
            
        try:
            # Fallback to cached eval
            code = _compile_expression(value_expr, 'eval')
            return eval(code, {"__builtins__": {}}, context)
        except:
            # If it fails, return as literal string
            return value_expr



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
            return self._fallback(person, household, context, "NO_CHILD_ROLE")

        # Get child's attribute value
        child = self._get_person_by_role(context, child_role)
        if not child:
            logger.warning(f"Child role '{child_role}' not found")
            return self._fallback(person, household, context, "CHILD_NOT_FOUND")

        child_value = self._get_attribute_value(child, attribute_name)
        if not child_value:
            logger.warning(f"No value found for child role '{child_role}'")
            return self._fallback(person, household, context, "CHILD_VALUE_MISSING")

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
                            return self._fallback(person, household, context, "NESTED_STRATEGY_UNSUPPORTED")
            except Exception as e:
                logger.warning(f"Error evaluating reverse inheritance logic: {e}")
                continue

        # No logic matched - fallback
        return self._fallback(person, household, context, "LOGIC_NO_MATCH")

    def _evaluate_condition_with_context(self, condition: str, eval_context: dict,
                                         child_role: str, attribute_name: str, child_value: Any) -> bool:
        """Evaluate a when condition with attribute access and fast-paths."""
        # FAST PATH: Pattern like "primary_adult.ethnicity == 'W'"
        prefix = f"{child_role}.{attribute_name}"
        if condition.startswith(prefix):
            op_part = condition[len(prefix):].strip()
            if op_part.startswith("=="):
                # Extract value (handles both 'VAL' and "VAL")
                val_part = op_part[2:].strip().strip("'").strip('"')
                return str(child_value) == val_part

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
            return [self._get_fallback(person, household, context)
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
                    results[idx] = self._get_fallback(person, household, context)
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

                # Build output based on configured outputs
                if len(self.outputs) == 1:
                    # Single output - return just the value
                    output_attr, output_source = list(self.outputs.items())[0]
                    if output_source == 'destination':
                        results[idx] = sampled_dest
                    elif output_source in sampled_metadata:
                        results[idx] = sampled_metadata[output_source]
                    else:
                        logger.warning(f"Output source '{output_source}' not found in metadata")
                        results[idx] = sampled_dest
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

                    results[idx] = result
                    logger.debug(f"Commuting (batch): person at index {idx} -> {result}")

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
            return self._get_fallback(person, household, context)

        # Get data source
        source = self.data_manager.get_source(self.data_source_name)
        if not source:
            logger.warning(f"Data source '{self.data_source_name}' not found")
            return self._get_fallback(person, household, context)

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
        """Standard fallback for commuting."""
        return self._fallback(person, household, context, "COMMUTING_DATA_MISSING")


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

        Groups people by (workplace_parent_gu, home_parent_gu) and processes each group together.
        Falls back from workplace to home GU if workplace has no data.

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
            logger.warning(f"Data source '{self.data_source_name}' not found")
            return [None] * len(people_list)

        # Group people by (workplace_parent_gu, home_parent_gu)
        # This allows efficient batch sampling with fallback logic
        gu_groups = defaultdict(list)

        for i, person in enumerate(people_list):
            # Get workplace parent GU
            workplace_parent_gu = person.properties.get('workplace_location')

            # Get home parent GU for fallback
            home_parent_gu = None
            if person.geographical_unit:
                home_parent_gu_obj = person.geographical_unit.get_ancestor_by_level('LGU')
                if home_parent_gu_obj:
                    home_parent_gu = home_parent_gu_obj.name

            if workplace_parent_gu:
                gu_groups[(workplace_parent_gu, home_parent_gu)].append(i)

        # Results array
        results = [None] * len(people_list)

        # Process each group
        for (workplace_parent_gu, home_parent_gu), indices in gu_groups.items():
            # Try workplace parent GU first
            gu_probs = source.lookup(workplace_parent_gu)

            # Fallback: if no data for workplace parent GU, try home parent GU
            if not gu_probs and home_parent_gu:
                logger.debug(f"No GU distribution for workplace parent GU '{workplace_parent_gu}', "
                           f"falling back to home parent GU '{home_parent_gu}'")
                gu_probs = source.lookup(home_parent_gu)

            if not gu_probs:
                logger.warning(f"No GU distribution found for parent GU '{workplace_parent_gu}' "
                             f"or home parent GU '{home_parent_gu}'")
                continue

            # BATCH SAMPLE: Sample GUs for all people in this group at once
            gu_codes = list(gu_probs.keys())
            probabilities = list(gu_probs.values())
            n_samples = len(indices)
            sampled_gus = np.random.choice(gu_codes, size=n_samples, p=probabilities)

            # Assign results
            for idx, sampled_gu in zip(indices, sampled_gus):
                results[idx] = sampled_gu
                logger.debug(f"GU Sampler (batch): {sampled_gu} for person at index {idx} in parent GU {workplace_parent_gu}")

        return results

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
            logger.warning(f"Data source '{self.data_source_name}' not found")
            return [None] * len(people_list)

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

            # Sample one category
            categories = list(probs.keys())
            probabilities = list(probs.values())

            # Normalize if needed
            total = sum(probabilities)
            if total <= 0:
                continue

            if abs(total - 1.0) > 0.01:  # Not normalized
                probabilities = [p / total for p in probabilities]

            # BATCH SAMPLE: Sample for all people in this group at once
            n_samples = len(indices)
            sampled_values = np.random.choice(categories, size=n_samples, p=probabilities)

            # Assign results
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
