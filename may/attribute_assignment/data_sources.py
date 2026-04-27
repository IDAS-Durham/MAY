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
from typing import Dict, List, Any, Optional, Tuple
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
        if not probs:
            logger.warning(f"Empty probability distribution in source '{self.name}'")
            return {}

        # Clamp negative values to 0 — negative probabilities are invalid
        has_negatives = False
        for v in probs.values():
            if v < 0:
                has_negatives = True
                break

        if has_negatives:
            neg_keys = [k for k, v in probs.items() if v < 0]
            logger.warning(
                f"Negative probability values in source '{self.name}' "
                f"for keys {neg_keys} — clamping to 0"
            )
            probs = {k: max(0.0, v) for k, v in probs.items()}

        total = sum(probs.values())

        if abs(total - 1.0) < 1e-10:  # Already normalized
            return probs
        elif total > 0:
            return {k: v / total for k, v in probs.items()}
        else:
            # All zeros — return uniform distribution
            n = len(probs)
            logger.warning(
                f"All-zero probability distribution in source '{self.name}' "
                f"({n} keys) — falling back to uniform"
            )
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

        # Cache for lookup results and key resolution
        self._lookup_cache = {}  # Cache for lookup() results by tuple key
        self._key_value_cache = {}  # Cache for _resolve_key_value() results

    def load_data(self, geo_units: Optional[set] = None):
        """Load CSV data and convert to dictionary for fast lookups."""
        logger.info(f"Loading data for source '{self.name}'...")

        for file_config in self._file_configs:
            file_path = Path(file_config['path'])

            if file_path.exists():
                try:
                    df = pd.read_csv(file_path)

                    # Apply row filters if specified
                    row_filter = file_config.get('row_filter', {})
                    if row_filter:
                        for col, value in row_filter.items():
                            if col in df.columns:
                                df = df[df[col] == value]
                                logger.info(f"  Applied filter: {col} == '{value}' ({len(df)} rows remaining)")

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

        Uses caching for repeated lookups with same keys.

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
            value = self._resolve_key_value_cached(col_config, person, household, context)
            if value is None:
                # Can't build complete key, use fallback
                if debug:
                    logger.debug(f"    [LOOKUP] Failed to resolve '{csv_col_name}', using fallback")
                return self._fallback
            key_values.append(value)

        # Direct dictionary lookup with tuple key
        lookup_key = tuple(key_values)

        # Check cache first
        if lookup_key in self._lookup_cache:
            return self._lookup_cache[lookup_key]

        if debug:
            logger.debug(f"    [LOOKUP] Key: {lookup_key}")

        # dictionary lookup
        result = self._lookup_dict.get(lookup_key)

        if result is None:
            # No match found, use fallback
            if debug:
                logger.debug(f"    [LOOKUP] Key not found in data, using fallback")
            # Cache the fallback too
            self._lookup_cache[lookup_key] = self._fallback
            return self._fallback

        if debug:
            logger.debug(f"    [LOOKUP] ✓ Found data: {list(result.keys())[:3]}...")

        # Normalize the result (convert counts to probabilities)
        result = self._normalize_probabilities(result)

        # Cache the normalized result
        self._lookup_cache[lookup_key] = result

        return result

    def _resolve_key_value_cached(self, col_config, person, household, context):
        """
        Caches results for person attributes that don't change.

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

        # Create cache key based on person ID, attribute name, and type
        # For person-level attributes (sex, age), these are immutable so we can cache
        if col_type == 'direct':
            cache_key = (person.id, attr_name, 'direct')
            if cache_key in self._key_value_cache:
                return self._key_value_cache[cache_key]

        # Call the actual resolution
        result = self._resolve_key_value(col_config, person, household, context)

        # Cache the result (only for direct lookups to avoid complexity)
        if col_type == 'direct':
            cache_key = (person.id, attr_name, 'direct')
            self._key_value_cache[cache_key] = result

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


class OriginDestinationMatrixSource(DataSource):
    """
    Data source for origin-destination flow matrices.

    Used for commuting patterns, migration flows, etc.
    Returns all possible destinations for a given origin with associated likelihoods.
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        """Initialize O-D matrix source."""
        super().__init__(name, config)
        # Lookup: origin_code -> [(destination, metadata_dict, likelihood), ...]
        self._lookup: Dict[str, List[Tuple[str, Dict[str, Any], float]]] = {}
        self._file_configs = config.get('files', [])

    def load_data(self, geo_units: Optional[set] = None):
        """Load origin-destination flow data from CSV."""
        logger.info(f"Loading data for source '{self.name}'...")

        for file_config in self._file_configs:
            file_path = Path(file_config['path'])

            if file_path.exists():
                try:
                    df = pd.read_csv(file_path)

                    # Get column configuration
                    key_columns_config = file_config.get('key_columns', {})
                    destination_column = file_config.get('destination_column')
                    likelihood_column = file_config.get('likelihood_column')
                    metadata_columns = file_config.get('metadata_columns', {})
                    exclude_destinations = file_config.get('exclude_destinations', [])

                    # Origin column is the first key in key_columns
                    # e.g., if key_columns has 'LGU_origin_code', use that
                    if key_columns_config:
                        origin_column = list(key_columns_config.keys())[0]
                    else:
                        origin_column = 'LGU_origin_code'

                    # Filter to only relevant geographical units
                    # Only filter if geo_units values actually match origin column values
                    if geo_units and origin_column and origin_column in df.columns:
                        # Check if there's any overlap between geo_units and origin values
                        origin_values = set(df[origin_column].unique())
                        overlap = origin_values.intersection(geo_units)

                        if overlap:  # Only filter if there's matching values
                            original_len = len(df)
                            df = df[df[origin_column].isin(geo_units)]
                            logger.info(f"  Filtered O-D matrix from {original_len} to {len(df)} rows based on {len(overlap)} matching origins")

                    # Parse DataFrame
                    self._lookup = self._parse_od_dataframe(
                        df,
                        origin_column,
                        destination_column,
                        likelihood_column,
                        metadata_columns,
                        exclude_destinations
                    )

                    logger.info(f"  ✓ Loaded {len(self._lookup)} origins from {file_path.name}")

                except Exception as e:
                    logger.warning(f"  ✗ Error loading {file_path}: {e}")
            else:
                logger.warning(f"  ✗ File not found: {file_path}")

        self._data_loaded = True

    def _parse_od_dataframe(self, df: pd.DataFrame,
                           origin_column: str,
                           destination_column: str,
                           likelihood_column: str,
                           metadata_columns: Dict[str, str],
                           exclude_destinations: List[str]) -> Dict[str, List[Tuple[str, Dict[str, Any], float]]]:
        """
        Parse O-D DataFrame into lookup dictionary.

        Args:
            df: DataFrame to parse
            origin_column: Column with origin codes
            destination_column: Column with destination codes
            likelihood_column: Column with likelihood/probability values
            metadata_columns: Additional columns to include (e.g., work_mode)
            exclude_destinations: List of destination codes to exclude

        Returns:
            Dictionary mapping origin codes to list of (destination, metadata, likelihood) tuples
        """
        lookup = {}

        # Group by origin
        for origin, group in df.groupby(origin_column):
            destinations = []

            for _, row in group.iterrows():
                destination = row[destination_column]

                # Skip excluded destinations
                if destination in exclude_destinations:
                    continue

                likelihood = float(row[likelihood_column])

                # Collect metadata
                metadata = {}
                for meta_key, meta_column in metadata_columns.items():
                    if meta_column in df.columns:
                        metadata[meta_key] = row[meta_column]

                destinations.append((destination, metadata, likelihood))

            # Normalize likelihoods to sum to 1.0
            total_likelihood = sum(lik for _, _, lik in destinations)
            if total_likelihood > 0:
                destinations = [
                    (dest, meta, lik / total_likelihood)
                    for dest, meta, lik in destinations
                ]

            lookup[origin] = destinations

        return lookup

    def lookup(self, origin: str) -> List[Tuple[str, Dict[str, Any], float]]:
        """
        Look up possible destinations for a given origin.

        Args:
            origin: Origin code (e.g., SGU code)

        Returns:
            List of (destination, metadata, likelihood) tuples
        """
        if not self._data_loaded:
            logger.warning(f"Data not loaded for source '{self.name}'")
            return []

        return self._lookup.get(origin, [])

class GUSamplerSource(DataSource):
    """
    Data source for sampling geographical units within a parent GU weighted by distribution.
    Generic source that works with any geographical hierarchy level.

    Returns GU codes as categorical values with distribution-based weights.
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        """Initialize geographical unit sampler source."""
        super().__init__(name, config)
        # Lookup: parent_gu_name -> {child_gu_code: weight}
        self._lookup: Dict[str, Dict[str, float]] = {}
        self._file_configs = config.get('files', [])

    def load_data(self, geo_units: Optional[set] = None):
        """Load GU distribution by parent GU."""
        logger.info(f"Loading data for source '{self.name}'...")

        for file_config in self._file_configs:
            file_path = Path(file_config['path'])

            if file_path.exists():
                try:
                    df = pd.read_csv(file_path)

                    lgu_column = file_config.get('key_column', 'LGU')
                    weight_column = file_config.get('weight_column', 'Total')

                    # Handle geographical_unit_column
                    geo_unit_config = file_config.get('geographical_unit_column')
                    if geo_unit_config:
                        # format: {name: "SGU", level: "SGU"}
                        geo_unit_column = geo_unit_config.get('name')
                        geo_unit_level = geo_unit_config.get('level', 'SGU')

                    # Filter to only relevant geographical units
                    if geo_units and geo_unit_column and geo_unit_column in df.columns:
                        original_len = len(df)
                        df = df[df[geo_unit_column].isin(geo_units)]
                        logger.info(f"  Filtered CSV from {original_len} to {len(df)} rows based on {len(geo_units)} geographical units")

                    # Handle exclude_rows (supports both old dict and new list format)
                    exclude_rows_config = file_config.get('exclude_rows', [])
                    if isinstance(exclude_rows_config, list):
                        # format: [{column: "col", values: [vals]}]
                        for exclude_rule in exclude_rows_config:
                            col = exclude_rule.get('column')
                            exclude_values = exclude_rule.get('values', [])
                            if col and col in df.columns:
                                df = df[~df[col].isin(exclude_values)]

                    # Group by parent GU and build child GU distribution
                    for parent_name, group in df.groupby(lgu_column):
                        geo_dist = {}
                        for _, row in group.iterrows():
                            geo_code = row[geo_unit_column]
                            weight = float(row[weight_column])
                            if weight > 0:  # Only include GUs with workers
                                geo_dist[geo_code] = weight

                        # Normalize to probabilities
                        if geo_dist:
                            self._lookup[parent_name] = self._normalize_probabilities(geo_dist)

                    logger.info(f"  ✓ Loaded {geo_unit_level} distributions for {len(self._lookup)} parent GUs from {file_path.name}")

                except Exception as e:
                    logger.warning(f"  ✗ Error loading {file_path}: {e}")
            else:
                logger.warning(f"  ✗ File not found: {file_path}")

        self._data_loaded = True

    def lookup(self, parent_gu_name: str) -> Dict[str, float]:
        """
        Look up GU probability distribution for a parent GU.

        Args:
            parent_gu_name: Parent GU name (e.g., "Nuneaton and Bedworth")

        Returns:
            Dictionary mapping child GU codes to probabilities
        """
        if not self._data_loaded:
            return {}

        return self._lookup.get(parent_gu_name, {})


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

                # Check for O-D matrix format
                output_format = file_config.get('output_format')
                if output_format == 'origin_destination_matrix':
                    self.sources[source_name] = OriginDestinationMatrixSource(
                        source_name, source_config.config
                    )
                elif isinstance(key_columns, dict) and any(
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
                elif ('sgu' in source_name.lower() and 'sampler' in source_name.lower()) or \
                     (file_config.get('geographical_unit_column') and file_config.get('weight_column')) or \
                     (file_config.get('sgu_column') and file_config.get('weight_column')):
                    # Geographical unit sampler: has geographical_unit_column (or sgu_column) and weight_column for distribution
                    self.sources[source_name] = GUSamplerSource(
                        source_name, source_config.config
                    )
                else:
                    # Default to geo distribution
                    self.sources[source_name] = GeoDistributionSource(
                        source_name, source_config.config
                    )
            elif source_type == 'constant':
                # Constant source (for fallbacks) - skip for now
                logger.debug(f"Skipping constant source: {source_name}")
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
