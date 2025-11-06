"""
Data source loaders for attribute assignment system.

This module handles loading demographic data from CSV files with:
- Regional routing (England/Wales, Scotland, Northern Ireland)
- Caching for performance
- Fallback probabilities when data not found
- Normalization of probability distributions
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Union, Tuple
from pathlib import Path

logger = logging.getLogger("may.attribute_assignment.data_sources")


class DataSource:
    """
    Base class for data sources.

    Data sources load demographic data from CSV files and provide
    probability distributions based on context (e.g., geographical unit code).
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        """
        Initialize data source.

        Args:
            name: Identifier for this data source
            config: Configuration dict from YAML
        """
        self.name = name
        self.config = config
        self.cache: Dict[str, Any] = {}
        self._data_loaded = False

    def load_data(self, geo_units: Optional[set] = None):
        """
        Load data from CSV files.

        Args:
            geo_units: Optional set of geographical unit codes to filter by (for efficiency)
        """
        raise NotImplementedError("Subclasses must implement load_data()")

    def lookup(self, *args, **kwargs) -> Dict[str, float]:
        """
        Look up probability distribution for given context.

        Returns:
            Dict mapping attribute values to probabilities
        """
        raise NotImplementedError("Subclasses must implement lookup()")

    def _normalize_probabilities(self, probs: Dict[str, float]) -> Dict[str, float]:
        """
        Normalize probabilities to ensure they sum to 1.0.

        Args:
            probs: Dictionary of probabilities

        Returns:
            Normalized probabilities that sum to 1.0
        """
        total = sum(probs.values())

        if abs(total - 1.0) < 1e-10:  # Already normalized
            return probs
        elif total > 0:
            return {k: v / total for k, v in probs.items()}
        else:
            # All zeros - return uniform distribution
            n = len(probs)
            return {k: 1.0 / n for k in probs.keys()}


class GeoDistributionSource(DataSource):
    """
    Data source for geographical unit-specific attribute distributions.

    Loads attribute distributions from CSV file.
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        """
        Initialize geo distribution source.

        Args:
            name: Source name
            config: Configuration with files and fallback
        """
        super().__init__(name, config)

        # Data lookup: geo_unit -> {ethnicity -> probability}
        self._lookup: Dict[str, Dict[str, float]] = {}

        # Parse file configurations
        self._file_configs = config.get('files', [])
        self._fallback = config.get('fallback', {})

    def load_data(self, geo_units: Optional[set] = None):
        """
        Load geographical unit distribution data from CSV file.

        Args:
            geo_units: Set of geographical unit codes to load (for efficiency)
        """
        logger.info(f"Loading data for source '{self.name}'...")

        # Process file configuration (should be just one file now)
        for file_config in self._file_configs:
            file_path = Path(file_config['path'])

            # Load and process CSV
            if file_path.exists():
                try:
                    df = pd.read_csv(file_path)

                    # Filter to needed areas
                    key_column = file_config.get('key_column', 'geo_unit')
                    if geo_units and key_column in df.columns:
                        df = df[df[key_column].isin(geo_units)]

                    # Parse value columns
                    value_columns = file_config.get('value_columns', {})
                    total_column = file_config.get('total_column')

                    # Store lookup dictionary
                    self._lookup = self._parse_dataframe(
                        df, key_column, value_columns, total_column
                    )

                    logger.info(f"  ✓ Loaded {len(self._lookup)} geographical units from {file_path.name}")

                except Exception as e:
                    logger.warning(f"  ✗ Error loading {file_path}: {e}")
            else:
                logger.warning(f"  ✗ File not found: {file_path}")

        self._data_loaded = True

    def _parse_dataframe(self, df: pd.DataFrame, key_column: str,
                        value_columns: Dict[str, str],
                        total_column: Optional[str] = None) -> Dict[str, Dict[str, float]]:
        """
        Parse DataFrame into lookup dictionary.

        Args:
            df: DataFrame to parse
            key_column: Column with geographical unit codes
            value_columns: Mapping of output keys to DataFrame columns
            total_column: Optional column with totals (for normalization)

        Returns:
            Dictionary mapping geographical unit codes to probability distributions
        """
        lookup = {}

        for _, row in df.iterrows():
            geo_unit = row[key_column]

            # Get total if available
            if total_column and total_column in df.columns:
                total = row[total_column]
            else:
                total = None

            # Build probability distribution
            probs = {}
            for output_key, df_column in value_columns.items():
                if df_column in df.columns:
                    value = row[df_column]

                    # Normalize by total if provided
                    if total is not None and total > 0:
                        probs[output_key] = value / total
                    else:
                        probs[output_key] = value

            # Normalize probabilities
            probs = self._normalize_probabilities(probs)
            lookup[geo_unit] = probs

        return lookup

    def lookup(self, geo_unit: str) -> Dict[str, float]:
        """
        Look up probability distribution for a geographical unit.

        Args:
            geo_unit: Geographical unit code (e.g., "E00000001")

        Returns:
            Dictionary of probabilities
        """
        if not self._data_loaded:
            logger.warning(f"Data not loaded for source '{self.name}', using fallback")
            return self._normalize_probabilities(self._fallback)

        # Look up geographical unit
        if geo_unit in self._lookup:
            return self._lookup[geo_unit]

        # Not found - use fallback
        return self._normalize_probabilities(self._fallback)


class DiversitySource(DataSource):
    """
    Data source for venue diversity (single vs mixed attribute values).

    Provides probabilities for whether a venue has:
    - Single attribute value (all members same)
    - Two attribute values
    - Three or more attribute values
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        """Initialize diversity source."""
        super().__init__(name, config)
        self._lookup: Dict[str, Dict[str, float]] = {}
        self._file_configs = config.get('files', [])
        self._fallback = config.get('fallback', {})

    def load_data(self, geo_units: Optional[set] = None):
        """Load diversity data from CSV file."""
        logger.info(f"Loading data for source '{self.name}'...")

        for file_config in self._file_configs:
            file_path = Path(file_config['path'])

            if file_path.exists():
                try:
                    df = pd.read_csv(file_path)
                    key_column = file_config.get('key_column', 'geo_unit')

                    if geo_units and key_column in df.columns:
                        df = df[df[key_column].isin(geo_units)]

                    value_columns = file_config.get('value_columns', {})
                    self._lookup = self._parse_diversity_dataframe(df, key_column, value_columns)

                    logger.info(f"  ✓ Loaded {len(self._lookup)} geographical units from {file_path.name}")

                except Exception as e:
                    logger.warning(f"  ✗ Error loading {file_path}: {e}")
            else:
                logger.warning(f"  ✗ File not found: {file_path}")

        self._data_loaded = True

    def _parse_diversity_dataframe(self, df: pd.DataFrame, key_column: str,
                                   value_columns: Dict[str, str]) -> Dict[str, Dict[str, float]]:
        """Parse diversity DataFrame."""
        lookup = {}

        for _, row in df.iterrows():
            geo_unit = row[key_column]

            # Get diversity counts
            counts = {}
            for output_key, df_column in value_columns.items():
                if df_column in df.columns:
                    counts[output_key] = float(row[df_column])

            # Normalize to probabilities
            total = sum(counts.values())
            if total > 0:
                probs = {k: v / total for k, v in counts.items()}
            else:
                # Uniform if no data
                n = len(counts)
                probs = {k: 1.0 / n for k in counts.keys()}

            lookup[geo_unit] = self._normalize_probabilities(probs)

        return lookup

    def lookup(self, geo_unit: str) -> Dict[str, float]:
        """Look up diversity probabilities for a geographical unit."""
        if not self._data_loaded:
            return self._normalize_probabilities(self._fallback)

        # Look up geographical unit
        if geo_unit in self._lookup:
            return self._lookup[geo_unit]

        # Not found - use fallback
        return self._normalize_probabilities(self._fallback)


class PairProbabilitySource(DataSource):
    """
    Data source for pair probabilities.

    Provides conditional probabilities: given first person's attribute value,
    what is the probability of second person having each value?
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        """Initialize pair probability source."""
        super().__init__(name, config)
        # Nested lookup: geo_unit -> first_ethnicity -> partner_ethnicity -> probability
        self._lookups: Dict[str, Dict[str, Dict[str, float]]] = {}
        self._file_configs = config.get('files', [])
        self._fallback_type = config.get('fallback', 'uniform')

    def load_data(self, geo_units: Optional[set] = None):
        """Load pair probability data."""
        logger.info(f"Loading data for source '{self.name}'...")

        for file_config in self._file_configs:
            file_path = Path(file_config['path'])

            if geo_units:
                # Partnership data covers all areas, just filter
                pass

            if file_path.exists():
                try:
                    df = pd.read_csv(file_path)

                    # Filter to needed areas if specified
                    key_columns = file_config.get('key_columns', ['geo_unit', 'first_ethnicity'])
                    if geo_units and key_columns[0] in df.columns:
                        df = df[df[key_columns[0]].isin(geo_units)]

                    value_columns = file_config.get('value_columns', {})
                    self._lookups = self._parse_pair_dataframe(df, key_columns, value_columns)

                    logger.info(f"  ✓ Loaded {len(self._lookups)} geographical units from {file_path.name}")

                except Exception as e:
                    logger.warning(f"  ✗ Error loading {file_path}: {e}")
            else:
                logger.warning(f"  ✗ File not found: {file_path}")

        self._data_loaded = True

    def _parse_pair_dataframe(self, df: pd.DataFrame, key_columns: List[str],
                              value_columns: Dict[str, str]) -> Dict[str, Dict[str, Dict[str, float]]]:
        """Parse pair probability DataFrame into nested lookup."""
        lookup = {}

        geo_col, first_value_col = key_columns[0], key_columns[1]

        for _, row in df.iterrows():
            geo_unit = row[geo_col]
            first_value = row[first_value_col]

            # Build second person probability distribution
            second_probs = {}
            for output_key, df_column in value_columns.items():
                if df_column in df.columns:
                    second_probs[output_key] = float(row[df_column])

            # Normalize
            second_probs = self._normalize_probabilities(second_probs)

            # Store in nested structure
            if geo_unit not in lookup:
                lookup[geo_unit] = {}
            lookup[geo_unit][first_value] = second_probs

        return lookup

    def lookup(self, geo_unit: str, first_value: str) -> Dict[str, float]:
        """
        Look up pair probabilities.

        Args:
            geo_unit: Geographical unit code
            first_value: Attribute value of first person

        Returns:
            Probability distribution for second person's attribute value
        """
        if not self._data_loaded:
            return self._get_fallback()

        # Look up geographical unit
        if geo_unit in self._lookups:
            # Look up first value within unit
            if first_value in self._lookups[geo_unit]:
                return self._lookups[geo_unit][first_value]

        return self._get_fallback()

    def _get_fallback(self) -> Dict[str, float]:
        """Get fallback pair probabilities."""
        if self._fallback_type == 'uniform':
            # Equal probability for all values
            values = ['W', 'A', 'B', 'M', 'O']
            prob = 1.0 / len(values)
            return {val: prob for val in values}
        else:
            # Default uniform
            return {'W': 0.2, 'A': 0.2, 'B': 0.2, 'M': 0.2, 'O': 0.2}


class MultiKeyLookupSource(DataSource):
    """
    Data source for multi-key CSV lookups.

    Supports lookups based on multiple keys (e.g., sex + age + ethnicity + region).
    Uses a pure Python dictionary for maximum performance.
    """

    def __init__(self, name: str, config: Dict[str, Any], assignment_config):
        """
        Initialize multi-key lookup source.

        Args:
            name: Source name
            config: Configuration with files and fallback
            assignment_config: Parent AttributeAssignmentConfig for category lookups
        """
        super().__init__(name, config)
        self.assignment_config = assignment_config
        self._file_configs = config.get('files', [])
        self._fallback = config.get('fallback', {})
        self._lookup_dict = {}  # Dict mapping tuple keys to value dicts
        self._key_columns = []
        self._value_columns = {}
        self._key_columns_config = None  # Cache key columns config for fast lookup

    def load_data(self, geo_units: Optional[set] = None):
        """Load CSV data and convert to dictionary for fast lookups."""
        logger.info(f"Loading data for source '{self.name}'...")

        for file_config in self._file_configs:
            file_path = Path(file_config['path'])

            if file_path.exists():
                try:
                    df = pd.read_csv(file_path)

                    # Get key and value columns
                    self._key_columns = list(file_config.get('key_columns', {}).keys())
                    self._key_columns_config = file_config.get('key_columns', {})
                    self._value_columns = file_config.get('value_columns', {})

                    # Build dictionary: {(key1, key2, ...): {col1: val1, col2: val2, ...}}
                    logger.info(f"  Building lookup dictionary from {len(df)} rows...")

                    for _, row in df.iterrows():
                        # Build key tuple
                        key = tuple(row[col] for col in self._key_columns)

                        # Build value dict
                        values = {name: float(row[csv_col]) for name, csv_col in self._value_columns.items()}

                        self._lookup_dict[key] = values

                    logger.info(f"  ✓ Loaded {len(self._lookup_dict)} rows from {file_path.name} into dictionary")
                except Exception as e:
                    logger.warning(f"  ✗ Error loading {file_path}: {e}")
            else:
                logger.warning(f"  ✗ File not found: {file_path}")

        self._data_loaded = True

    def lookup(self, person, household=None, context=None) -> Dict[str, float]:
        """
        Look up probabilities based on person demographics using dictionary lookup.

        Args:
            person: Person object
            household: Optional household object
            context: Optional additional context

        Returns:
            Dict of value columns (e.g., {'cvd': 0.05, 'crd': 0.03, ...})
        """
        debug = context and context.get('debug', False)

        if not self._lookup_dict:
            if debug:
                logger.debug(f"    [LOOKUP] No lookup dict available, using fallback")
            return self._fallback

        # Build key tuple directly (faster than building intermediate dict)
        key_values = []
        for csv_col_name, col_config in self._key_columns_config.items():
            value = self._resolve_key_value(col_config, person, household, context)
            if value is None:
                # Can't build complete key, use fallback
                if debug:
                    logger.debug(f"    [LOOKUP] Failed to resolve '{csv_col_name}', using fallback")
                return self._fallback
            key_values.append(value)

        # Direct dictionary lookup with tuple key
        lookup_key = tuple(key_values)

        if debug:
            logger.debug(f"    [LOOKUP] Key: {lookup_key}")

        # O(1) dictionary lookup
        result = self._lookup_dict.get(lookup_key)

        if result is None:
            # No match found, use fallback
            if debug:
                logger.debug(f"    [LOOKUP] Key not found in data, using fallback")
            return self._fallback

        if debug:
            logger.debug(f"    [LOOKUP] ✓ Found data: {list(result.keys())[:3]}...")

        return result

    def _resolve_key_value(self, col_config, person, household, context):
        """
        Resolve a key value based on column configuration.

        Args:
            col_config: Column configuration dict
            person: Person object
            household: Optional household object
            context: Optional context dict

        Returns:
            Resolved value or None if can't resolve
        """
        attr_name = col_config.get('attribute')
        col_type = col_config.get('type', 'direct')

        if col_type == 'direct':
            # Direct attribute lookup
            value = person.properties.get(attr_name)
            if value is None:
                value = getattr(person, attr_name, None)

            # Check if this is a required attribute with mapping
            if attr_name in self.assignment_config.required_attributes:
                mapping = self.assignment_config.required_attributes[attr_name].get('mapping', {})
                value = mapping.get(value, value)

            return value

        elif col_type == 'category_lookup':
            # Get attribute value, find matching category
            value = getattr(person, attr_name, None)
            if value is None:
                value = person.properties.get(attr_name)

            category = self.assignment_config.get_category_for_value(value, attr_name)
            return category.get('csv_value') if category else None

        elif col_type == 'ancestor_lookup':
            # Traverse hierarchy
            geo_unit = getattr(person, attr_name, None)
            if geo_unit is None:
                # Try household's geo unit
                if household:
                    geo_unit = getattr(household, attr_name, None)

            if geo_unit is None:
                return None

            level = col_config.get('level')
            ancestor = geo_unit.get_ancestor_by_level(level)

            if ancestor is None:
                return None

            property_name = col_config.get('property', 'name')
            value = getattr(ancestor, property_name)

            # Apply mapping if specified
            mapping_name = col_config.get('mapping')
            if mapping_name:
                mapping = getattr(self.assignment_config, mapping_name, {})
                value = mapping.get(value, value)

            return value

        return None


class DataSourceManager:
    """
    Manager for all data sources.

    Coordinates loading and access to multiple data sources.
    """

    def __init__(self, config):
        """
        Initialize data source manager.

        Args:
            config: AttributeAssignmentConfig instance
        """
        self.config = config
        self.sources: Dict[str, DataSource] = {}
        self._initialize_sources()

    def _initialize_sources(self):
        """Initialize data sources from config."""
        for source_name, source_config in self.config.data_sources.items():
            source_type = source_config.type

            if source_type == 'csv_lookup':
                # Check if this is a multi-key lookup (has key_columns in file config)
                file_config = source_config.config.get('files', [{}])[0]
                key_columns = file_config.get('key_columns')

                if isinstance(key_columns, dict) and any(
                    isinstance(v, dict) for v in key_columns.values()
                ):
                    # Multi-key lookup (values are dicts with 'attribute', 'type', etc.)
                    self.sources[source_name] = MultiKeyLookupSource(
                        source_name, source_config.config, self.config
                    )
                elif 'diversity' in source_name.lower():
                    self.sources[source_name] = DiversitySource(
                        source_name, source_config.config
                    )
                elif 'pair' in source_name.lower():
                    self.sources[source_name] = PairProbabilitySource(
                        source_name, source_config.config
                    )
                else:
                    # Default to geo distribution
                    self.sources[source_name] = GeoDistributionSource(
                        source_name, source_config.config
                    )
            else:
                logger.warning(f"Unknown data source type: {source_type}")

    def load_all(self, geo_units: Optional[set] = None):
        """
        Load all data sources.

        Args:
            geo_units: Optional set of geographical unit codes to preload
        """
        logger.info("Loading all data sources...")
        for source_name, source in self.sources.items():
            source.load_data(geo_units)
        logger.info("✓ All data sources loaded")

    def get_source(self, source_name: str) -> Optional[DataSource]:
        """Get a data source by name."""
        return self.sources.get(source_name)

    def lookup(self, source_name: str, *args, **kwargs) -> Dict[str, float]:
        """
        Look up probabilities from a data source.

        Args:
            source_name: Name of data source
            *args, **kwargs: Arguments to pass to source's lookup method

        Returns:
            Probability distribution
        """
        source = self.get_source(source_name)
        if source:
            return source.lookup(*args, **kwargs)
        else:
            logger.warning(f"Data source '{source_name}' not found")
            return {}
