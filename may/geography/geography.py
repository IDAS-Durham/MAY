import logging
from .geographical_unit import GeographicalUnit
from may.utils.stacked_input import as_path_list, load_stacked_csv

logger = logging.getLogger("geography")

class Geography:
    """
    Main geography container. Loads and manages hierarchical geographical units.
    Generic implementation that works with any geography structure.
    """
    def __init__(self, data_dir="data/geography", levels=None, filters=None,
                 hierarchy_file=None, coord_files=None):
        self.data_dir = data_dir
        self.units = {}           # All units by name: {name: GeographicalUnit}
        self.units_by_id = {}     # All units by ID: {id: GeographicalUnit}

        # Hierarchy levels (most granular to least granular). Required: callers
        # pass the scenario's configured labels.
        if not levels:
            raise ValueError(
                "Geography requires 'levels' — the ordered list of level labels "
                "(smallest to largest) from geography config. There is no default."
            )
        self.levels = levels

        # Separate lookups by level for efficiency
        self.units_by_level = {level: {} for level in self.levels}

        # Filters: dict with 'level' and 'names' keys
        # Example: {'level': 'MGU', 'codes': ['E02000173', 'E02000187']}
        # Note: the 'codes' key holds names
        self.filters = filters

        # Input files, named explicitly: a hierarchy file (or list of files
        # to stack) and a {level: file-or-list} coordinate mapping. Relative
        # paths resolve against data_dir. A level absent from coord_files
        # simply has no coordinates.
        self.hierarchy_file = hierarchy_file
        self.coord_files = coord_files or {}

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
        Load geography data from the configured hierarchy and coordinate CSVs.
        Each may be a single file or a list of files stacked into one table.
        """
        import os

        logger.info(f"Loading geography from {self.data_dir}")

        # 1. Load hierarchy file(s) (define parent-child relationships)
        if not self.hierarchy_file:
            raise ValueError(
                "geography requires 'hierarchy_file' (a path or list of paths) "
                "and optionally 'coord_files' (a {level: path-or-list} mapping); "
                "relative paths resolve against geography data_dir."
            )
        hierarchy_paths = [
            os.path.join(self.data_dir, p)
            for p in as_path_list(self.hierarchy_file, "geography.hierarchy_file")
        ]
        # Leaf units are the row keys: the same smallest-level unit defined in
        # two files (or twice in one) is a data error, not something to merge.
        hierarchy_df = load_stacked_csv(
            hierarchy_paths, label="geography hierarchy", key_column=self.levels[0]
        )

        logger.info(f"Loaded hierarchy with {len(hierarchy_df)} entries")

        # Verify that all configured levels exist in the CSV
        missing_levels = [lvl for lvl in self.levels if lvl not in hierarchy_df.columns]
        if missing_levels:
            logger.error(f"Hierarchy file is missing columns for configured levels: {missing_levels}")
            logger.info(f"Available columns: {hierarchy_df.columns.tolist()}")
            raise ValueError(f"Missing columns {missing_levels} in {hierarchy_paths}")

        # Reject rows that are missing a value at any configured level; a
        # blank/NaN cell would create a ghost unit named "nan" and corrupt the
        # parent chain.
        invalid_mask = hierarchy_df[self.levels].isna().any(axis=1) | \
            hierarchy_df[self.levels].apply(
                lambda col: col.astype(str).str.strip() == "", axis=0
            ).any(axis=1)
        if invalid_mask.any():
            invalid_count = int(invalid_mask.sum())
            logger.warning(
                f"Dropping {invalid_count} hierarchy row(s) with blank/NaN values "
                f"in configured level columns {self.levels}"
            )
            hierarchy_df = hierarchy_df[~invalid_mask].reset_index(drop=True)

        # 2. Apply filters if specified
        if self.filters and self.filters.get('codes'):
            filter_level = self.filters['level']
            filter_names = set(self.filters['codes'])  # 'codes' key holds names

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

        # 3. Load coordinates for each level with configured files, restricted
        # to names present in the (post-filter) hierarchy. A level without an
        # entry in coord_files has no coordinates, by declaration.
        unknown_levels = [lvl for lvl in self.coord_files if lvl not in self.levels]
        if unknown_levels:
            raise ValueError(
                f"coord_files references unknown level(s) {unknown_levels}; "
                f"configured levels are {self.levels}."
            )
        names_per_level = {
            level: set(hierarchy_df[level].unique()) for level in self.levels
        }
        coords = {level: {} for level in self.levels}
        for level, file_spec in self.coord_files.items():
            coord_paths = [
                os.path.join(self.data_dir, p)
                for p in as_path_list(file_spec, f"geography.coord_files.{level}")
            ]
            coord_df = load_stacked_csv(
                coord_paths, label=f"{level} coordinates"
            )
            self._validate_coord_columns(coord_df, coord_paths, level)
            for _candidate in ('geo_unit', level.lower(), level):
                if _candidate in coord_df.columns:
                    name_col = _candidate
                    break
            else:
                name_col = coord_df.columns[0]

            duplicated = coord_df[name_col].dropna()
            duplicated = duplicated[duplicated.duplicated()].unique()
            if len(duplicated) > 0:
                raise ValueError(
                    f"{level} coordinates define {len(duplicated)} unit(s) more "
                    f"than once across {coord_paths}, e.g. {list(duplicated[:5])}."
                )

            wanted = names_per_level[level]
            if wanted:
                coord_df = coord_df[coord_df[name_col].isin(wanted)]
            coords[level] = dict(zip(
                coord_df[name_col],
                zip(coord_df['latitude'], coord_df['longitude'])
            ))
            logger.info(f"Loaded {len(coords[level])} coordinates for {level}")

        # 4. Create all units from hierarchy
        for level in self.levels:
            unique_names = hierarchy_df[level].unique()
            for name in unique_names:
                if name in self.units_by_level[level]:
                    continue
                coordinates = coords[level].get(name, None)
                unit = GeographicalUnit(
                    id=self._generate_id(),
                    name=name,
                    level=level,
                    coordinates=coordinates,
                )
                self.add_geo_unit(unit)

        logger.info(f"Created {len(self.units_by_id)} total units")

        # 5. Build parent-child relationships, vectorized per level pair.
        # Each (child, parent) pair appears once after drop_duplicates. A child
        # mapping to two different parents — in one file or across files — is
        # a hard error: silently keeping one parent would corrupt the tree.
        for i in range(len(self.levels) - 1):
            child_level = self.levels[i]
            parent_level = self.levels[i + 1]
            pairs = hierarchy_df[[child_level, parent_level]].drop_duplicates()
            conflicted = pairs[pairs[child_level].duplicated(keep=False)]
            if len(conflicted) > 0:
                examples = [
                    f"{child!r} -> {sorted(group[parent_level].unique())}"
                    for child, group in list(conflicted.groupby(child_level))[:5]
                ]
                raise ValueError(
                    f"{conflicted[child_level].nunique()} {child_level} unit(s) "
                    f"map to more than one {parent_level} parent: {examples}. "
                    f"Every unit must have exactly one parent."
                )
            child_index = self.units_by_level[child_level]
            parent_index = self.units_by_level[parent_level]
            for child_name, parent_name in pairs.itertuples(index=False, name=None):
                parent_index[parent_name].add_child(child_index[child_name])

        logger.info("Built hierarchical relationships")
        self._log_summary()

    @staticmethod
    def _validate_coord_columns(coord_df, coord_file, level):
        """
        Verify a coordinate CSV has the columns we rely on. Without this, a
        typo in the header surfaces as a mid-load KeyError far from the cause.
        """
        required = {"latitude", "longitude"}
        missing = required.difference(coord_df.columns)
        if missing:
            raise ValueError(
                f"Coordinate file {coord_file} for level {level} is missing "
                f"required column(s) {sorted(missing)}; found {list(coord_df.columns)}"
            )
        if len(coord_df.columns) < 3:
            raise ValueError(
                f"Coordinate file {coord_file} for level {level} must have a "
                f"name column followed by latitude and longitude; "
                f"found columns {list(coord_df.columns)}"
            )

    def add_geo_unit(self, unit: "GeographicalUnit"):
        existing = self.units.get(unit.name)
        if existing is None:
            self.units[unit.name] = unit
        elif existing.level != unit.level:
            logger.warning(
                f"Name collision across levels: '{unit.name}' exists at "
                f"{existing.level} (id={existing.id}) and {unit.level} (id={unit.id}); "
                f"get_unit('{unit.name}') will continue to return the {existing.level} unit. "
                f"Use get_units_by_level() to disambiguate."
            )
        elif existing.id != unit.id:
            logger.warning(
                f"Duplicate unit at {unit.level}: '{unit.name}' already registered with "
                f"id={existing.id}; ignoring new id={unit.id}."
            )
        self.units_by_id[unit.id] = unit
        self.units_by_level[unit.level][unit.name] = unit

    def add_geo_units(self, units):
        for unit in units:
            self.add_geo_unit(unit)
        
    def get_unit(self, name):
        """Get a unit by its name (or `code` in datasets that use codes as names)."""
        return self.units.get(name)

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
        if not isinstance(other, Geography):
            return NotImplemented
        for attribute in ['units', 'levels']:
            if getattr(self, attribute) != getattr(other, attribute):
                return False
        return True

    def __hash__(self):
        return hash((self.data_dir, tuple(self.levels)))

