"""
Assignment strategies for attribute assignment system.

This module implements different strategies for assigning attribute values
to people based on household composition, person roles, and demographic data.
"""

import logging
import numpy as np
from typing import Dict, List, Any, Optional

logger = logging.getLogger("attribute_assignment.strategies")


class AssignmentStrategy:
    """
    Base class for assignment strategies.

    Strategies determine HOW to assign an attribute value to a person,
    given the context (household, other people, data sources, etc.).
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

    def assign(self, person, venue, context: Dict[str, Any]) -> Any:
        """
        Assign attribute value to a person.

        Args:
            person: Person object to assign to
            venue: Venue (household) object
            context: Assignment context with state information

        Returns:
            Assigned attribute value
        """
        raise NotImplementedError("Subclasses must implement assign()")


class ProbabilisticStrategy(AssignmentStrategy):
    """
    Probabilistic assignment based on data source distributions.

    Samples from a probability distribution obtained from a data source
    (e.g., ethnicity distribution for a geographical unit).
    """

    def assign(self, person, venue, context: Dict[str, Any]) -> Any:
        """
        Sample attribute value from probability distribution.

        Args:
            person: Person object
            venue: Venue object
            context: Assignment context

        Returns:
            Sampled attribute value
        """
        # Get data source name
        data_source_name = self.config.get('data_source')
        if not data_source_name:
            logger.error("ProbabilisticStrategy requires 'data_source' in config")
            return None

        # Get context for lookup (e.g., "household.area_code")
        context_key = self.config.get('context', 'venue.area_code')

        # Resolve context value
        lookup_value = self._resolve_context(context_key, person, venue, context)
        if not lookup_value:
            logger.warning(f"Could not resolve context '{context_key}'")
            return None

        # Get probability distribution from data source
        probs = self.data_manager.lookup(data_source_name, lookup_value)
        if not probs:
            logger.warning(f"No probabilities found for {data_source_name}({lookup_value})")
            return None

        # Sample from distribution
        values = list(probs.keys())
        probabilities = list(probs.values())

        sampled = np.random.choice(values, p=probabilities)

        logger.debug(f"Probabilistic assignment: {sampled} for {person} (from {data_source_name})")
        return sampled

    def _resolve_context(self, context_key: str, person, venue, context: Dict) -> Optional[str]:
        """
        Resolve a context key to an actual value.

        Examples:
            "household.area_code" -> venue.geographical_unit.code
            "venue.area_code" -> venue.geographical_unit.code

        Args:
            context_key: Context key string
            person: Person object
            venue: Venue object
            context: Assignment context dict

        Returns:
            Resolved value or None
        """
        # Handle simple lookups
        if context_key in context:
            return context[context_key]

        # Handle dot notation (e.g., "household.area_code")
        if '.' in context_key:
            parts = context_key.split('.')

            if parts[0] in ['household', 'venue']:
                # Get geo unit code
                if venue and venue.geographical_unit:
                    return venue.geographical_unit.name

            elif parts[0] == 'person':
                # Get person attribute
                if len(parts) > 1:
                    return getattr(person, parts[1], None)

        return None


class CopyStrategy(AssignmentStrategy):
    """
    Copy attribute value from another person.

    Used when one person should have the same value as another
    (e.g., partner in same-ethnicity household).
    """

    def assign(self, person, venue, context: Dict[str, Any]) -> Any:
        """
        Copy attribute value from source person.

        Args:
            person: Person object
            venue: Venue object
            context: Assignment context (should contain source person info)

        Returns:
            Copied attribute value
        """
        # Get source identifier (e.g., "primary_adult.ethnicity")
        source = self.config.get('source')
        if not source:
            logger.error("CopyStrategy requires 'source' in config")
            return None

        # Parse source
        if '.' in source:
            role_name, attribute = source.split('.', 1)
        else:
            role_name = source
            attribute = context.get('attribute_name', 'ethnicity')

        # Get source person from context
        source_key = f"{role_name}_person"
        source_person = context.get(source_key)

        if not source_person:
            logger.warning(f"Source person not found: {role_name}")
            return None

        # Get attribute value from source person (check properties first)
        if hasattr(source_person, 'properties') and attribute in source_person.properties:
            value = source_person.properties[attribute]
        else:
            value = getattr(source_person, attribute, None)

        logger.debug(f"Copy assignment: {value} from {role_name}")
        return value


class InheritanceStrategy(AssignmentStrategy):
    """
    Inheritance from parent generation.

    Children inherit attribute values from their parents/adults in the household.
    Handles mixed values (e.g., parents have different ethnicities).
    """

    def assign(self, person, venue, context: Dict[str, Any]) -> Any:
        """
        Assign value based on parent values.

        Args:
            person: Person object (child)
            venue: Venue object
            context: Assignment context

        Returns:
            Inherited attribute value
        """
        # Get parent roles to inherit from
        parent_roles = self.config.get('inherit_from', {}).get('person_roles', [])

        # Collect attribute values from parents
        parent_values = []
        for role_name in parent_roles:
            role_key = f"{role_name}_person"
            parent = context.get(role_key)

            if parent:
                attribute = context.get('attribute_name', 'ethnicity')
                # Check properties dict first
                if hasattr(parent, 'properties') and attribute in parent.properties:
                    value = parent.properties[attribute]
                else:
                    value = getattr(parent, attribute, None)
                if value:
                    parent_values.append(value)

        if not parent_values:
            logger.warning(f"No parent values found for inheritance")
            # Use fallback if specified
            fallback_config = self.config.get('logic', [{}])[-1].get('then')
            if fallback_config and isinstance(fallback_config, dict):
                fallback_strategy = StrategyFactory.create_strategy(fallback_config, self.data_manager)
                return fallback_strategy.assign(person, venue, context)
            return None

        # Apply mixing logic
        unique_values = list(set(parent_values))

        if len(unique_values) == 1:
            # All parents same value
            result = unique_values[0]
            logger.debug(f"Inheritance: {result} (single parent value)")
            return result
        else:
            # Multiple parent values - return mixed code (e.g., "M" for mixed ethnicity)
            mixed_code = self._get_mixed_code(context)
            logger.debug(f"Inheritance: {mixed_code} (mixed from {unique_values})")
            return mixed_code

    def _get_mixed_code(self, context: Dict) -> str:
        """Get the code for mixed attribute values."""
        # For ethnicity, this is "M"
        # Could be configurable in future
        return "M"


class ConditionalStrategy(AssignmentStrategy):
    """
    Conditional assignment based on diversity check.

    First checks if venue should be diverse (single vs mixed),
    then applies appropriate sub-strategy.
    """

    def assign(self, person, venue, context: Dict[str, Any]) -> Any:
        """
        Assign based on diversity check.

        Args:
            person: Person object
            venue: Venue object
            context: Assignment context

        Returns:
            Assigned attribute value
        """
        # Get diversity check configuration
        diversity_config = self.config.get('diversity_check', {})
        if not diversity_config:
            logger.error("ConditionalStrategy requires 'diversity_check' config")
            return None

        # Perform diversity check
        diversity_data_source = diversity_config.get('data_source')
        diversity_context = diversity_config.get('context', 'household.area_code')

        # Get geo unit
        geo_unit = self._resolve_context(diversity_context, person, venue, context)

        # Get diversity probabilities
        diversity_probs = self.data_manager.lookup(diversity_data_source, geo_unit)

        # Sample diversity type
        sample_from = diversity_config.get('sample_from', ['single', 'mixed_two', 'mixed_three_plus'])
        diversity_values = [diversity_probs.get(key, 0) for key in sample_from]
        diversity_type = np.random.choice(sample_from, p=diversity_values)

        logger.debug(f"Diversity check: {diversity_type} for venue {venue.id}")

        # Store diversity decision in context
        context['diversity_check'] = diversity_type

        # Apply appropriate rule based on diversity type
        rules = self.config.get('rules', [])
        for rule in rules:
            when_condition = rule.get('when')

            # Evaluate condition
            if self._evaluate_when(when_condition, context):
                then_config = rule.get('then')

                # Create and execute sub-strategy
                sub_strategy = StrategyFactory.create_strategy(then_config, self.data_manager)
                return sub_strategy.assign(person, venue, context)

        logger.warning(f"No matching rule in ConditionalStrategy for diversity={diversity_type}")
        return None

    def _resolve_context(self, context_key: str, person, venue, context: Dict) -> Optional[str]:
        """Resolve context key (same as ProbabilisticStrategy)."""
        if context_key in context:
            return context[context_key]

        if '.' in context_key:
            parts = context_key.split('.')
            if parts[0] in ['household', 'venue']:
                if venue and venue.geographical_unit:
                    return venue.geographical_unit.code

        return None

    def _evaluate_when(self, condition: str, context: Dict) -> bool:
        """
        Evaluate a when condition.

        Examples:
            "diversity_check == 'single'"
            "diversity_check in ['mixed_two', 'mixed_three_plus']"

        Args:
            condition: Condition string
            context: Context dict

        Returns:
            True if condition is satisfied
        """
        try:
            # Create safe evaluation context
            eval_context = {
                'diversity_check': context.get('diversity_check'),
            }

            # Evaluate condition
            result = eval(condition, {"__builtins__": {}}, eval_context)
            return bool(result)
        except Exception as e:
            logger.warning(f"Error evaluating condition '{condition}': {e}")
            return False


class PairProbabilityStrategy(AssignmentStrategy):
    """
    Assignment based on conditional pair probabilities.

    Assigns second person's value based on first person's value
    (e.g., partner ethnicity given first person's ethnicity).
    """

    def assign(self, person, venue, context: Dict[str, Any]) -> Any:
        """
        Assign based on pair probabilities.

        Args:
            person: Person object (second person in pair)
            venue: Venue object
            context: Assignment context (should contain first person info)

        Returns:
            Assigned attribute value
        """
        # Get data source and context
        data_source_name = self.config.get('data_source')
        context_spec = self.config.get('context', [])

        if not isinstance(context_spec, list) or len(context_spec) < 2:
            logger.error("PairProbabilityStrategy requires context list with 2 elements")
            return None

        # Resolve geo unit and first person's value
        geo_context = context_spec[0]
        first_value_context = context_spec[1]

        geo_unit = self._resolve_context(geo_context, person, venue, context)
        first_value = self._resolve_context(first_value_context, person, venue, context)

        if not geo_unit or not first_value:
            logger.warning(f"Could not resolve pair context: geo={geo_unit}, first={first_value}")
            # Try fallback
            fallback_config = self.config.get('fallback')
            if fallback_config:
                fallback_strategy = StrategyFactory.create_strategy(fallback_config, self.data_manager)
                return fallback_strategy.assign(person, venue, context)
            return None

        # Get pair probabilities
        probs = self.data_manager.lookup(data_source_name, geo_unit, first_value)

        # Sample from distribution
        values = list(probs.keys())
        probabilities = list(probs.values())

        sampled = np.random.choice(values, p=probabilities)

        logger.debug(f"Pair probability assignment: {sampled} (given first={first_value})")
        return sampled

    def _resolve_context(self, context_key: str, person, venue, context: Dict) -> Optional[str]:
        """Resolve context key."""
        # Check if it's in context dict
        if context_key in context:
            return context[context_key]

        # Handle dot notation
        if '.' in context_key:
            parts = context_key.split('.')

            if parts[0] in ['household', 'venue']:
                if venue and venue.geographical_unit:
                    return venue.geographical_unit.code

            elif parts[0] == 'primary_adult':
                # Get primary adult's attribute
                primary_adult = context.get('primary_adult_person')
                if primary_adult and len(parts) > 1:
                    attr = parts[1]
                    # Check properties dict first
                    if hasattr(primary_adult, 'properties') and attr in primary_adult.properties:
                        return primary_adult.properties[attr]
                    return getattr(primary_adult, attr, None)

        return None


class StrategyFactory:
    """
    Factory for creating assignment strategies from configuration.
    """

    @staticmethod
    def create_strategy(config: Dict[str, Any], data_manager) -> AssignmentStrategy:
        """
        Create strategy from configuration.

        Args:
            config: Strategy configuration dict
            data_manager: DataSourceManager instance

        Returns:
            AssignmentStrategy instance
        """
        strategy_type = config.get('type')

        if strategy_type == 'probabilistic':
            return ProbabilisticStrategy(config, data_manager)

        elif strategy_type == 'copy':
            return CopyStrategy(config, data_manager)

        elif strategy_type == 'inheritance':
            return InheritanceStrategy(config, data_manager)

        elif strategy_type == 'conditional_probabilistic':
            return ConditionalStrategy(config, data_manager)

        elif strategy_type == 'conditional_probabilistic' or 'diversity_check' in config:
            # Handle conditional with embedded config
            return ConditionalStrategy(config, data_manager)

        else:
            logger.error(f"Unknown strategy type: {strategy_type}")
            # Return a default probabilistic strategy
            return ProbabilisticStrategy(config, data_manager)
