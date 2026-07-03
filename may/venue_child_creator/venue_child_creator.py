"""
VenueChildCreator - Creates child venues based on parent venue occupancy.

This module creates child venues (like classrooms, offices) dynamically based on
how many people are already allocated to parent venues (like schools, companies).

Example workflow:
1. Distribute students to schools
2. Run VenueChildCreator to create classrooms based on student count and age
3. Students are moved from school to specific classrooms
"""

import logging
import yaml
import math
from collections import defaultdict

from may.utils.attribute_access import get_person_attribute
from may.utils import path_resolver as pr

logger = logging.getLogger("venue_child_creator")


class VenueChildCreator:
    """
    Creates child venues dynamically based on parent venue occupancy.

    After people are distributed to parent venues (e.g., schools), this class:
    - Groups people by specified attributes (e.g., age)
    - Creates child venues (e.g., classrooms) based on group sizes
    - Redistributes people from parent to child venues
    """

    def __init__(
        self,
        parent_venue_type,
        child_venue_type,
        group_by_attribute=None,
        child_max_size=30,
        child_properties=None,
        distribution_strategy='even',
        balance_by=None,
        attribute_mapping=None,
        activity_map_key=None,
        subset_key=None,
        replace_parent_activity=True,
        remove_from_parent=False,
        member_filters=None,
        exclude_subset_keys=None,
        include_subset_keys=None,
    ):
        """
        Initialize VenueChildCreator.

        Args:
            parent_venue_type: Type of parent venues to process (e.g., "school")
            child_venue_type: Type of child venues to create (e.g., "classroom")
            group_by_attribute: Attribute to group by (e.g., "age", "sex")
            child_max_size: Maximum people per child venue
            child_properties: Dict of properties to add to each child venue
            distribution_strategy: How to distribute people ('even' or 'fill')
            balance_by: Optional attribute (or list of attributes) to balance evenly across
                       the child venues, e.g. "sex". Without it, members are sliced from the
                       group in arrival order — and because population is created sorted by
                       (age, sex), that order is sex-clustered, so contiguous slicing produces
                       single-sex classrooms even within a co-ed school. When set, each child
                       venue receives a proportional mix of every value of this attribute,
                       mirroring the cohort. Single-sex cohorts stay single-sex automatically.
            attribute_mapping: Optional dict mapping attribute values to group keys.
                             Supports 'default' key for unmapped values.
                             Example: {18: "18", 19: "19", "default": "23+"}
            activity_map_key: Activity key to use when adding to child venues (e.g., "primary_activity").
                            If None, uses child_venue_type as activity name.
            subset_key: Subset key to use when adding to child venues (e.g., "student").
                       If None, uses default subset.
            replace_parent_activity: If True, replaces parent's activity with child's activity.
                                    If False, appends child's activity to existing.
            remove_from_parent: If True, removes person from parent venue's subset.
                               If False, keeps person in parent for reference.
            member_filters: Optional list of filters to apply to members before processing.
                           Only members passing all filters will be assigned to child venues.
                           Example: [{"attribute": "age", "type": "numerical", "min": 12}]
            exclude_subset_keys: Optional iterable of parent subset_key values to skip when
                                reading parent members (e.g. "guest"). Mutually exclusive
                                with include_subset_keys.
            include_subset_keys: Optional iterable of parent subset_key values to restrict
                                to when reading parent members. Mutually exclusive with
                                exclude_subset_keys.
        """
        if exclude_subset_keys is not None and include_subset_keys is not None:
            raise ValueError(
                "VenueChildCreator: exclude_subset_keys and include_subset_keys are mutually exclusive"
            )
        self.parent_venue_type = parent_venue_type
        self.child_venue_type = child_venue_type
        self.group_by_attribute = group_by_attribute
        self.child_max_size = child_max_size
        self.child_properties = child_properties or {}
        self.distribution_strategy = distribution_strategy
        self.balance_by = balance_by
        self.attribute_mapping = attribute_mapping or {}
        self.activity_map_key = activity_map_key
        self.subset_key = subset_key
        self.replace_parent_activity = replace_parent_activity
        self.remove_from_parent = remove_from_parent
        self.member_filters = member_filters or []
        self.exclude_subset_keys = exclude_subset_keys
        self.include_subset_keys = include_subset_keys

        if distribution_strategy not in ('even', 'fill'):
            raise ValueError(
                f"Unknown distribution_strategy '{distribution_strategy}'. "
                f"Valid values: 'even', 'fill'."
            )
        for f in self.member_filters:
            ftype = f.get('type', 'numerical')
            if ftype not in ('numerical', 'categorical'):
                raise ValueError(
                    f"Unknown member_filter type '{ftype}' for attribute "
                    f"'{f.get('attribute')}'. Valid types: 'numerical', 'categorical'."
                )

        self.stats = {
            'parents_processed': 0,
            'children_created': 0,
            'people_redistributed': 0,
            'people_filtered_out': 0,
        }

    @classmethod
    def from_yaml(cls, yaml_file):
        """
        Load VenueChildCreator configuration from YAML file.

        Example YAML:
        ```yaml
        parent_venue_type: school
        child_venue_type: classroom
        group_by_attribute: age
        child_max_size: 30
        child_properties:
          capacity: 30
        distribution_strategy: even
        ```

        Args:
            yaml_file: Path to YAML configuration file

        Returns:
            VenueChildCreator instance
        """
        yaml_file = pr.resolve(str(yaml_file))
        logger.info(f"Loading VenueChildCreator config from {yaml_file}")

        with open(yaml_file, 'r') as f:
            config = yaml.safe_load(f)

        instance = cls(
            parent_venue_type=config['parent_venue_type'],
            child_venue_type=config['child_venue_type'],
            group_by_attribute=config.get('group_by_attribute'),
            child_max_size=config.get('child_max_size', 30),
            child_properties=config.get('child_properties', {}),
            distribution_strategy=config.get('distribution_strategy', 'even'),
            balance_by=config.get('balance_by'),
            attribute_mapping=config.get('attribute_mapping', {}),
            activity_map_key=config.get('activity_map_key'),
            subset_key=config.get('subset_key'),
            replace_parent_activity=config.get('replace_parent_activity', True),
            remove_from_parent=config.get('remove_from_parent', False),
            member_filters=config.get('member_filters', []),
            exclude_subset_keys=config.get('exclude_subset_keys'),
            include_subset_keys=config.get('include_subset_keys'),
        )

        logger.info(f"  Parent type: {instance.parent_venue_type} → Child type: {instance.child_venue_type}")
        if instance.balance_by:
            logger.info(f"  Balancing children by: {instance.balance_by}")
        if instance.member_filters:
            logger.info(f"  Member filters: {len(instance.member_filters)} filter(s) configured")
            for f in instance.member_filters:
                if f.get('type') == 'numerical':
                    logger.info(f"    - {f.get('attribute')}: {f.get('min', '-∞')} to {f.get('max', '∞')}")
                elif f.get('type') == 'categorical':
                    logger.info(f"    - {f.get('attribute')} in {f.get('values')}")

        return instance

    def create_children(self, world):
        """
        Create child venues for all parent venues based on current occupancy.

        Args:
            world: World object containing geography, population, and venues

        Returns:
            Dict with statistics about creation
        """
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"Creating {self.child_venue_type}s for {self.parent_venue_type}s")
        logger.info("=" * 60)

        parent_venues = world.venues.get_venues_by_type(self.parent_venue_type)

        if not parent_venues:
            logger.warning(f"No venues of type '{self.parent_venue_type}' found")
            return self.stats

        logger.info(f"Processing {len(parent_venues)} {self.parent_venue_type}(s)")

        for parent_venue in parent_venues:
            self._process_parent_venue(parent_venue, world)

        logger.info("")
        logger.info("Summary:")
        logger.info(f"  Parents processed: {self.stats['parents_processed']}")
        logger.info(f"  Children created: {self.stats['children_created']}")
        logger.info(f"  People redistributed: {self.stats['people_redistributed']}")
        if self.member_filters:
            logger.info(f"  People filtered out: {self.stats['people_filtered_out']}")
        logger.info("=" * 60)

        return self.stats

    def _process_parent_venue(self, parent_venue, world):
        """
        Process a single parent venue: create children and redistribute people.

        Args:
            parent_venue: Parent Venue object
            world: World object
        """
        members = parent_venue.get_all_members(
            exclude_subset_keys=self.exclude_subset_keys,
            include_subset_keys=self.include_subset_keys,
        )

        if not members:
            logger.debug(f"  {parent_venue.name}: No members, skipping")
            return

        #logger.info(f"  {parent_venue.name}: {len(members)} members")

        if self.member_filters:
            original_count = len(members)
            members = self._filter_members(members)
            filtered_out = original_count - len(members)
            self.stats['people_filtered_out'] += filtered_out
            if not members:
                logger.debug(f"  {parent_venue.name}: No members after filtering, skipping")
                return

        if self.group_by_attribute:
            groups = self._group_members_by_attribute(members, self.group_by_attribute)
        else:
            groups = {'all': members}

        total_children_created = 0
        for group_key, group_members in groups.items():
            children_created = self._create_children_for_group(
                parent_venue,
                group_key,
                group_members,
                world
            )
            total_children_created += children_created

        #logger.info(f"    → Created {total_children_created} {self.child_venue_type}(s)")
        self.stats['parents_processed'] += 1

    def _filter_members(self, members):
        """
        Filter members based on configured member_filters.

        Supports filter types:
        - numerical: Filter by numeric attribute (min/max bounds)
        - categorical: Filter by attribute value in a list of allowed values

        Args:
            members: List of Person objects

        Returns:
            List of Person objects that pass all filters
        """
        filtered = members

        for filter_config in self.member_filters:
            attr_name = filter_config.get('attribute')
            filter_type = filter_config.get('type', 'numerical')

            if filter_type == 'numerical':
                min_val = filter_config.get('min', float('-inf'))
                max_val = filter_config.get('max', float('inf'))

                filtered = [
                    p for p in filtered
                    if (v := get_person_attribute(p, attr_name)) is not None
                    and min_val <= v <= max_val
                ]

            elif filter_type == 'categorical':
                allowed_values = filter_config.get('values', [])

                filtered = [
                    p for p in filtered
                    if get_person_attribute(p, attr_name) in allowed_values
                ]

        return filtered

    def _group_members_by_attribute(self, members, attribute_name):
        """
        Group members by a specific attribute value.

        Supports custom attribute mapping to combine multiple values into groups.
        For example, ages 23+ can be mapped to a single "23+" group.

        Args:
            members: List of Person objects
            attribute_name: Name of attribute to group by (e.g., "age", "sex", "properties.ethnicity")

        Returns:
            Dict of {group_key: [Person, ...]}
        """
        groups = defaultdict(list)

        for person in members:
            attr_value = get_person_attribute(person, attribute_name)

            if attr_value is not None:
                if self.attribute_mapping:
                    if attr_value in self.attribute_mapping:
                        group_key = self.attribute_mapping[attr_value]
                    elif 'default' in self.attribute_mapping:
                        group_key = self.attribute_mapping['default']
                    else:
                        group_key = attr_value
                else:
                    group_key = attr_value

                groups[group_key].append(person)
            else:
                groups['unknown'].append(person)

        return dict(groups)

    def _stratify_members(self, members, balance_by):
        """
        Partition members into strata by one or more attributes.

        Used by balanced distribution to spread each attribute value evenly
        across child venues. Members whose attribute is missing fall into an
        'unknown' stratum so they are still placed.

        Args:
            members: List of Person objects
            balance_by: Attribute name (str) or list of attribute names

        Returns:
            Dict of {value(s): [Person, ...]}, preserving member order within each stratum
        """
        attrs = balance_by if isinstance(balance_by, (list, tuple)) else [balance_by]

        strata = defaultdict(list)
        for person in members:
            values = tuple(get_person_attribute(person, a) for a in attrs)
            key = values if len(values) > 1 else values[0]
            if any(v is None for v in values):
                key = 'unknown'
            strata[key].append(person)

        return dict(strata)

    def _create_children_for_group(self, parent_venue, group_key, group_members, world):
        """
        Create child venues for a specific group and distribute members.

        Args:
            parent_venue: Parent Venue object
            group_key: Key for this group (e.g., age value)
            group_members: List of Person objects in this group
            world: World object

        Returns:
            int: Number of child venues created
        """
        num_members = len(group_members)

        num_children = math.ceil(num_members / self.child_max_size)

        #logger.info(f"    Group {group_key}: {num_members} members → {num_children} {self.child_venue_type}(s)")

        child_venues = []
        for i in range(num_children):
            child_props = self.child_properties.copy()
            child_props['group_key'] = group_key

            if self.group_by_attribute:
                child_props[self.group_by_attribute] = group_key  # e.g., 'age': 10

            child_venue = world.venues.create_child_venue(
                parent_venue=parent_venue,
                child_venue_type=self.child_venue_type,
                properties=child_props
            )
            child_venues.append(child_venue)

        self._distribute_members_to_children(group_members, child_venues)

        self.stats['children_created'] += num_children
        self.stats['people_redistributed'] += num_members

        return num_children

    def _distribute_members_to_children(self, members, child_venues):
        """
        Distribute members across child venues.

        Handles activity_map updates and parent venue cleanup based on configuration.

        Args:
            members: List of Person objects
            child_venues: List of child Venue objects
        """
        # When balancing by an attribute (e.g. sex), deal each value's members
        # round-robin across the child venues so every venue gets a proportional
        # mix that mirrors the cohort. A single shared pointer carried across the
        # strata keeps per-venue totals even too.
        if self.balance_by and len(child_venues) > 1:
            strata = self._stratify_members(members, self.balance_by)
            ptr = 0
            n = len(child_venues)
            for stratum_members in strata.values():
                for person in stratum_members:
                    self._add_person_to_child(person, child_venues[ptr % n])
                    ptr += 1
            return

        if self.distribution_strategy == 'even':
            members_per_child = len(members) // len(child_venues)
            remainder = len(members) % len(child_venues)

            member_index = 0
            for i, child_venue in enumerate(child_venues):
                count = members_per_child + (1 if i < remainder else 0)

                for _ in range(count):
                    if member_index < len(members):
                        person = members[member_index]
                        self._add_person_to_child(person, child_venue)
                        member_index += 1

        elif self.distribution_strategy == 'fill':
            # Fill each child to child_max_size before moving to next
            member_index = 0
            for child_venue in child_venues:
                for _ in range(self.child_max_size):
                    if member_index < len(members):
                        person = members[member_index]
                        self._add_person_to_child(person, child_venue)
                        member_index += 1
                    else:
                        break

    def _add_person_to_child(self, person, child_venue):
        """
        Add a person to a child venue with proper activity_map handling.

        Args:
            person: Person object
            child_venue: Child Venue object
        """
        activity_name = self.activity_map_key if self.activity_map_key else self.child_venue_type

        if self.replace_parent_activity and self.activity_map_key:
            if self.activity_map_key in person.activity_map:
                person.activity_map[self.activity_map_key] = {}

        child_venue.add_to_subset(
            person,
            subset_key=self.subset_key,
            activity_name=activity_name
        )

        if self.remove_from_parent:
            parent = child_venue.parent
            if parent:
                for subset in parent.subsets.values():
                    if person in subset.members:
                        subset.members.remove(person)

    def export_allocations(self, world, output_file):
        """
        Export child venue allocations to CSV.

        Args:
            world: World object
            output_file: Path to output CSV file
        """
        import pandas as pd

        logger.info(f"Exporting {self.child_venue_type} allocations to {output_file}")

        rows = []
        child_venues = world.venues.get_venues_by_type(self.child_venue_type)

        for child_venue in child_venues:
            members = child_venue.get_all_members()

            parent = child_venue.parent
            parent_name = parent.name if parent else "None"

            group_key = child_venue.properties.get('group_key', 'N/A')

            row = {
                'child_venue_id': child_venue.id,
                'child_venue_name': child_venue.name,
                'child_venue_type': child_venue.type,
                'parent_venue_name': parent_name,
                'group_key': group_key,
                'num_members': len(members),
                'child_max_size': self.child_max_size,
                'utilization_pct': f"{(len(members) / self.child_max_size * 100):.1f}" if self.child_max_size > 0 else "0.0",
            }

            if self.group_by_attribute:
                row[self.group_by_attribute] = child_venue.properties.get(self.group_by_attribute, 'N/A')

            rows.append(row)

        df = pd.DataFrame(rows)

        if not df.empty:
            df = df.sort_values(['parent_venue_name', 'group_key', 'child_venue_id'])

        df.to_csv(output_file, index=False)
        logger.info(f"Exported {len(rows)} {self.child_venue_type}s to {output_file}")

    def __repr__(self):
        filter_info = f", filters={len(self.member_filters)}" if self.member_filters else ""
        return (
            f"<VenueChildCreator: {self.parent_venue_type} → {self.child_venue_type}, "
            f"group_by={self.group_by_attribute}, child_max_size={self.child_max_size}{filter_info}>"
        )
