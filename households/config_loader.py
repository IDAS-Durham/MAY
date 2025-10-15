"""
Configuration loader with validation for household distribution system.

Ensures consistency between age brackets and composition pattern format.
"""

import yaml
import logging
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger("config_loader")


class ConfigurationError(Exception):
    """Raised when configuration is invalid or inconsistent."""
    pass


class ConfigLoader:
    """
    Loads and validates household configuration files.

    Ensures that:
    - Age brackets are contiguous and non-overlapping
    - Composition patterns match the number of age brackets
    - All configuration files are consistent with each other
    """

    def __init__(self, config_dir: str = "data/households/config"):
        self.config_dir = Path(config_dir)
        self.age_brackets = None
        self.relationship_constraints = None
        self.reconciliation_config = None
        self.composition_assumptions = None

    def load_all(self) -> Dict:
        """
        Load and validate all configuration files.

        Returns:
            dict: Combined configuration

        Raises:
            ConfigurationError: If configuration is invalid
        """
        logger.info("Loading household configuration files...")

        # Load individual configs
        self.age_brackets = self._load_age_brackets()
        self.relationship_constraints = self._load_relationship_constraints()
        self.reconciliation_config = self._load_reconciliation_config()
        self.composition_assumptions = self._load_composition_assumptions()

        # Validate consistency
        self._validate_consistency()

        logger.info("✓ Configuration loaded and validated successfully")

        return {
            'age_brackets': self.age_brackets,
            'relationship_constraints': self.relationship_constraints,
            'reconciliation': self.reconciliation_config,
            'composition_assumptions': self.composition_assumptions
        }

    def _load_age_brackets(self) -> Dict:
        """Load and validate person categories configuration."""
        config_path = self.config_dir / "person_categories.yaml"

        if not config_path.exists():
            raise ConfigurationError(f"Person categories config not found: {config_path}")

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        # Validate person categories
        brackets = config.get('person_categories', [])

        if len(brackets) < config.get('validation', {}).get('min_categories', 2):
            raise ConfigurationError(
                f"Too few person categories: {len(brackets)}. "
                f"Minimum: {config.get('validation', {}).get('min_categories', 2)}"
            )

        if len(brackets) > config.get('validation', {}).get('max_categories', 10):
            raise ConfigurationError(
                f"Too many person categories: {len(brackets)}. "
                f"Maximum: {config.get('validation', {}).get('max_categories', 10)}"
            )

        # Check for continuity and overlaps (only for age-based categories)
        cat_type = config.get('categorization_type', 'age')
        if cat_type == 'age':
            if config.get('validation', {}).get('check_continuity', True):
                self._check_bracket_continuity(brackets)

            if config.get('validation', {}).get('check_overlap', True):
                self._check_bracket_overlap(brackets)

        # Update expected pattern values count
        if 'pattern_format' not in config:
            config['pattern_format'] = {}
        config['pattern_format']['expected_values'] = len(brackets)

        logger.info(f"Loaded {len(brackets)} person categories ({cat_type}-based): {', '.join([b['name'] for b in brackets])}")

        return config

    def _check_bracket_continuity(self, brackets: List[Dict]):
        """Ensure no age gaps between categories (age-based only)."""
        sorted_brackets = sorted(brackets, key=lambda x: x['min_age'])

        for i in range(len(sorted_brackets) - 1):
            current_max = sorted_brackets[i]['max_age']
            next_min = sorted_brackets[i + 1]['min_age']

            # Check for gap (max_age + 1 should equal next min_age)
            if current_max + 1 != next_min:
                raise ConfigurationError(
                    f"Age gap detected between brackets: "
                    f"{sorted_brackets[i]['name']} (ends at {current_max}) and "
                    f"{sorted_brackets[i + 1]['name']} (starts at {next_min})"
                )

    def _check_bracket_overlap(self, brackets: List[Dict]):
        """Ensure no overlapping age ranges (age-based only)."""
        for i, bracket_i in enumerate(brackets):
            for j, bracket_j in enumerate(brackets):
                if i >= j:
                    continue

                # Check if ranges overlap
                range_i = set(range(bracket_i['min_age'], bracket_i['max_age'] + 1))
                range_j = set(range(bracket_j['min_age'], bracket_j['max_age'] + 1))

                overlap = range_i & range_j
                if overlap:
                    raise ConfigurationError(
                        f"Age brackets overlap: {bracket_i['name']} and {bracket_j['name']} "
                        f"share ages: {sorted(overlap)}"
                    )

    def _load_relationship_constraints(self) -> Dict:
        """Load relationship constraints configuration."""
        config_path = self.config_dir / "relationship_constraints.yaml"

        if not config_path.exists():
            raise ConfigurationError(f"Relationship constraints config not found: {config_path}")

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        logger.info("Loaded relationship constraints")
        return config

    def _load_reconciliation_config(self) -> Dict:
        """Load data reconciliation configuration."""
        config_path = self.config_dir / "data_reconciliation.yaml"

        if not config_path.exists():
            raise ConfigurationError(f"Reconciliation config not found: {config_path}")

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        logger.info("Loaded reconciliation configuration")
        return config

    def _load_composition_assumptions(self) -> Dict:
        """Load composition assumptions from household_creation_rules.yaml."""
        config_path = self.config_dir / "household_creation_rules.yaml"

        if not config_path.exists():
            raise ConfigurationError(f"Household creation rules not found: {config_path}")

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        # Extract composition assumptions section
        assumptions = config.get('composition_assumptions', [])
        assumptions_config = config.get('composition_assumptions_config', {})

        logger.info(f"Loaded {len(assumptions)} composition assumptions")

        return {
            'assumptions': assumptions,
            'config': assumptions_config
        }

    def _validate_consistency(self):
        """
        Validate consistency between all configuration files.

        CRITICAL: Ensures composition patterns match age bracket count.
        """
        # Get person category count
        num_categories = len(self.age_brackets['person_categories'])
        category_names = [c['name'] for c in self.age_brackets['person_categories']]

        logger.info(f"Person categories defined: {num_categories}")
        logger.info(f"Category names: {', '.join(category_names)}")

        # Validate pattern format expectation
        expected_pattern_values = self.age_brackets.get('pattern_format', {}).get('expected_values')

        if expected_pattern_values != num_categories:
            raise ConfigurationError(
                f"Pattern format mismatch! Expected {expected_pattern_values} values, "
                f"but {num_categories} person categories defined. "
                f"Update pattern_format.expected_values in person_categories.yaml"
            )

        # Validate reconciliation config categories match
        allocation_rounds = self.reconciliation_config.get('allocation_rounds', {}).get('rounds', [])

        reconciliation_categories = set([r['category'] for r in allocation_rounds])
        category_names_set = set(category_names)

        # Check all reconciliation categories are defined
        undefined_groups = reconciliation_categories - category_names_set
        if undefined_groups:
            raise ConfigurationError(
                f"Reconciliation config references undefined categories: {undefined_groups}. "
                f"Defined person categories: {category_names_set}"
            )

        # Check all categories have an allocation round
        missing_rounds = category_names_set - reconciliation_categories
        if missing_rounds:
            raise ConfigurationError(
                f"Person categories missing from allocation rounds: {missing_rounds}. "
                f"Add allocation rounds for these groups in data_reconciliation.yaml"
            )

        logger.info("✓ Configuration consistency validated")

    def get_category_order(self) -> List[str]:
        """
        Get the ordered list of person category names.
        This defines the order for composition patterns.

        Returns:
            List of category names in order

        Example:
            ['kid', 'young_adult', 'adult', 'elder']
            → Pattern format: "{kid_count} {young_adult_count} {adult_count} {elder_count}"
        """
        # Return in definition order (not sorted)
        return [c['name'] for c in self.age_brackets['person_categories']]

    def get_category_symbols(self) -> Dict[str, str]:
        """
        Get mapping of person category names to symbols.

        Returns:
            dict: {name: symbol}

        Example:
            {'kid': 'K', 'young_adult': 'YA', 'adult': 'A', 'elder': 'E'}
        """
        return {
            c['name']: c['symbol']
            for c in self.age_brackets['person_categories']
        }

    # Backward compatibility aliases
    def get_age_bracket_order(self) -> List[str]:
        """Alias for get_category_order (backward compatibility)."""
        return self.get_category_order()

    def get_age_bracket_symbols(self) -> Dict[str, str]:
        """Alias for get_category_symbols (backward compatibility)."""
        return self.get_category_symbols()

    def validate_composition_pattern(self, pattern: str) -> Tuple[bool, str]:
        """
        Validate a composition pattern string.

        Args:
            pattern: Pattern string (e.g., "2 0 2 0" or ">=2 >=0 2 0")

        Returns:
            Tuple of (is_valid, error_message)

        Example:
            validate_composition_pattern("2 0 2 0")  # → (True, "")
            validate_composition_pattern("2 0 2")    # → (False, "Expected 4 values, got 3")
        """
        parts = pattern.strip().split()
        expected_count = len(self.age_brackets['person_categories'])

        # Check value count
        if len(parts) != expected_count:
            category_names = self.get_category_order()
            return (
                False,
                f"Pattern has {len(parts)} values, but {expected_count} expected. "
                f"Format: '{' '.join([f'{{{name}}}' for name in category_names])}'"
            )

        # Check each value is valid (integer or >=integer)
        for i, part in enumerate(parts):
            clean_part = part.replace('>=', '')
            if not clean_part.isdigit():
                return (False, f"Invalid value at position {i}: '{part}'. Expected integer or >=integer")

        return (True, "")


if __name__ == "__main__":
    # Test the configuration loader
    logging.basicConfig(level=logging.INFO)

    loader = ConfigLoader()
    config = loader.load_all()

    print("\n=== Age Bracket Order ===")
    print(loader.get_age_bracket_order())

    print("\n=== Age Bracket Symbols ===")
    print(loader.get_age_bracket_symbols())

    print("\n=== Pattern Validation Tests ===")
    test_patterns = [
        "2 0 2 0",           # Valid
        ">=2 >=0 2 0",       # Valid
        "2 0 2",             # Invalid (too few values)
        "2 0 2 0 1",         # Invalid (too many values)
        "abc 0 2 0",         # Invalid (non-numeric)
    ]

    for pattern in test_patterns:
        is_valid, error = loader.validate_composition_pattern(pattern)
        status = "✓" if is_valid else "✗"
        print(f"{status} '{pattern}': {error if error else 'Valid'}")
