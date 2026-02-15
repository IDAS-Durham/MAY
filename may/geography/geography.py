import logging
from .geographical_unit import GeographicalUnit

logger = logging.getLogger("geography")

class Geography:
    """
    Main geography container. Loads and manages hierarchical geographical units.
    Generic implementation that works with any geography structure.
    """
    def __init__(self, data_dir="data/geography", levels=None, filters=None):
        self.data_dir = data_dir
        self.units = {}           # All units by name: {name: GeographicalUnit}
        self.units_by_id = {}     # All units by ID: {id: GeographicalUnit}

        # Define hierarchy levels (most granular to least granular)
        self.levels = levels if levels is not None else ["SGU", "MGU", "LGU"]

        # Separate lookups by level for efficiency
        self.units_by_level = {level: {} for level in self.levels}

        # Filters: dict with 'level' and 'names' keys
        # Example: {'level': 'MGU', 'codes': ['E02000173', 'E02000187']}
        # Note: 'codes' is kept for backward compatibility, but refers to names
        self.filters = filters

        # ID counter for generating unique IDs
        self._next_id = 0

    def _generate_id(self):
        """
        Generate a unique sequential ID for a geographical unit.

        Returns:
            Unique integer ID
        """
        id = self._next_id
        self._next_id += 1
        return id

    @staticmethod
    def load_codes_from_file(file_path):
        """
        Load codes from a text file.
        Ignores empty lines and lines starting with #.

        Args:
            file_path: Path to the filter file

        Returns:
            Set of codes
        """
        codes = set()
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if line and not line.startswith('#'):
                        codes.add(line)
            logger.info(f"Loaded {len(codes)} codes from {file_path}")
        except FileNotFoundError:
            logger.error(f"Filter file not found: {file_path}")
            raise
        return codes

    def load_from_csv(self):
        """
        Load geography data from CSV files.
        Expects files: hierarchy.csv, coord_sgu.csv, coord_mgu.csv, etc.
        """
        import pandas as pd
        import os

        logger.info(f"Loading geography from {self.data_dir}")

        # 1. Load hierarchy file (defines parent-child relationships)
        hierarchy_path = os.path.join(self.data_dir, "hierarchy.csv")
        hierarchy_df = pd.read_csv(hierarchy_path)

        logger.info(f"Loaded hierarchy with {len(hierarchy_df)} entries")

        # Verify that all configured levels exist in the CSV
        missing_levels = [lvl for lvl in self.levels if lvl not in hierarchy_df.columns]
        if missing_levels:
            logger.error(f"Hierarchy file is missing columns for configured levels: {missing_levels}")
            logger.info(f"Available columns: {hierarchy_df.columns.tolist()}")
            raise ValueError(f"Missing columns {missing_levels} in {hierarchy_path}")

        # 2. Apply filters if specified
        if self.filters and self.filters.get('codes'):
            filter_level = self.filters['level']
            filter_names = set(self.filters['codes'])  # 'codes' key for backward compat

            if filter_level not in hierarchy_df.columns:
                logger.error(f"Filter level '{filter_level}' not found in hierarchy columns.")
                raise ValueError(f"Invalid filter level: {filter_level}")
            
            filter_col = filter_level

            # Filter the hierarchy to only include rows with these names
            original_size = len(hierarchy_df)
            hierarchy_df = hierarchy_df[hierarchy_df[filter_col].isin(filter_names)]

            logger.info(
                f"Applied {filter_level} filter: {len(filter_names)} names specified, "
                f"reduced from {original_size} to {len(hierarchy_df)} rows"
            )

        # 3. Load coordinates for each level
        coords = {}
        for level in self.levels:
            level_lower = level.replace(".", "").lower()  # "S.G.U" -> "sgu"
            coord_file = os.path.join(self.data_dir, f"coord_{level_lower}.csv")

            if os.path.exists(coord_file):
                coord_df = pd.read_csv(coord_file)
                # Convert to dict: {name: (lat, lon)}
                name_col = coord_df.columns[0]  # First column is the name
                coords[level] = dict(zip(
                    coord_df[name_col],
                    zip(coord_df['latitude'], coord_df['longitude'])
                ))
                logger.info(f"Loaded {len(coords[level])} coordinates for {level}")
            else:
                coords[level] = {}
                logger.warning(f"No coordinate file found for {level}")

        # 4. Create all units from hierarchy
        # Create units for each level independently of column order
        for level in self.levels:
            unique_names = hierarchy_df[level].unique()

            for name in unique_names:
                # Check if unit already exists AT THIS LEVEL to allow same names across levels
                if name not in self.units_by_level[level]:
                    # Get coordinates as tuple (lat, lon) or None
                    coordinates = coords[level].get(name, None)
                    # Generate unique ID
                    unit_id = self._generate_id()
                    unit = GeographicalUnit(
                        id=unit_id,
                        name=name,
                        level=level,
                        coordinates=coordinates
                    )
                    self.add_geo_unit(unit)                    

        logger.info(f"Created {len(self.units)} total units")

        # 5. Build parent-child relationships from hierarchy
        # Use explicit level pairs instead of column offsets
        for _, row in hierarchy_df.iterrows():
            # Link each level to its parent
            for i in range(len(self.levels) - 1):
                child_level = self.levels[i]
                parent_level = self.levels[i+1]
                
                child_name = row[child_level]
                parent_name = row[parent_level]

                # Get units from their specific levels
                child = self.units_by_level[child_level].get(child_name)
                parent = self.units_by_level[parent_level].get(parent_name)

                if child and parent and child.parent is None:
                    parent.add_child(child)

        logger.info("Built hierarchical relationships")
        self._log_summary()

    def add_geo_unit(self, unit: "GeographicalUnit"):
        if unit.name not in self.units:
            self.units[unit.name] = unit
        self.units_by_id[unit.id] = unit
        self.units_by_level[unit.level][unit.name] = unit

    def add_geo_units(self, units):
        for unit in units:
            self.add_geo_unit(unit)
        
    def get_unit(self, name):
        """Get a unit by its name"""
        return self.units.get(name)

    def get_geo_unit(self, code):
        """
        Get a geographical unit by its code/name.
        Alias for get_unit() for clarity in distributor context.

        Args:
            code: Geographical unit code (e.g., "E00001551")

        Returns:
            GeographicalUnit or None if not found
        """
        return self.get_unit(code)

    def get_unit_by_id(self, id):
        """Get a unit by its numeric ID"""
        return self.units_by_id.get(id)

    def get_units_by_level(self, level):
        """Get all units at a specific level"""
        return self.units_by_level.get(level, {})

    def get_all_units(self):
        """Get all geographical units (returns dict of name -> unit)"""
        return self.units

    def get_all_units_list(self):
        """Get all geographical units as a list, sorted by ID"""
        return sorted(self.units.values(), key=lambda u: u.id)

    def get_roots(self):
        """Get all root units (units with no parent)"""
        return [unit for unit in self.units.values() if unit.parent is None]

    def _log_summary(self):
        """Log summary statistics about the geography"""
        for level in self.levels:
            count = len(self.units_by_level[level])
            logger.info(f"  {level}: {count} units")

    def __repr__(self):
        return f"<Geography: {len(self.units)} units across {len(self.levels)} levels>"

    def __eq__(self, other):
        for attribute in ['units','levels']:
            if getattr(self, attribute) != getattr(other, attribute):
                return False
        return True

    def __hash__(self):
        return hash((self.data_dir, self.levels))

