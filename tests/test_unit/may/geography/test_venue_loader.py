"""
Tests for VenueManager loader behaviour. These cover the failure modes the
production log surfaced (missing CSVs, no-name-column CSVs, cross- and
same-type name collisions) plus untested code paths (filter_column,
extend() ID merge, capacity_config propagation).
"""

import logging
import os

import pandas as pd
import pytest

from may.geography import Geography
from may.geography.venue_manager import VenueManager, VenueError


@pytest.fixture
def loaded_geography():
    geo = Geography(data_dir="tests/test_data/micro_world/geography", levels=["SGU", "MGU", "LGU"])
    geo.load_from_csv()
    return geo


# ---------------------------------------------------------------------------
# No-name-column CSVs (the '12537' / '13817' bug)
# ---------------------------------------------------------------------------

def test_csv_without_name_column_uses_auto_generated_names(loaded_geography, caplog):
    """A CSV with no 'name' column must NOT synthesise names from the row index.
    Each venue keeps its auto-generated `{type}_{id}` name. Two such files do
    not produce cross-file collisions."""
    vm = VenueManager(geography=loaded_geography, filter_by_geography=False)

    # Mimic groceries.csv / pubs.csv: only geo_unit + coords, no 'name'.
    grocery_df = pd.DataFrame({
        'geo_unit': ['SGU_001', 'SGU_002'],
        'latitude': [51.5, 51.6],
        'longitude': [-0.1, -0.2],
    })
    pub_df = pd.DataFrame({
        'geo_unit': ['SGU_001', 'SGU_002'],
        'latitude': [51.7, 51.8],
        'longitude': [-0.3, -0.4],
    })

    with caplog.at_level(logging.WARNING, logger='venuemanager'):
        vm.load_venue_type_from_df('grocery', grocery_df)
        vm.load_venue_type_from_df('pub', pub_df)

    grocery_names = {v.name for v in vm.get_venues_by_type('grocery')}
    pub_names = {v.name for v in vm.get_venues_by_type('pub')}
    assert grocery_names == {'grocery_0', 'grocery_1'}
    assert pub_names == {'pub_0', 'pub_1'}
    # No collisions should be reported.
    assert not any('collision' in r.message for r in caplog.records)
    # No venue should be named after a pandas row index.
    all_names = {v.name for v in vm.get_all_venues_list()}
    assert not any(n.isdigit() for n in all_names), all_names


def test_csv_with_blank_name_falls_back_to_auto_name(loaded_geography):
    """A CSV that has a 'name' column but with NaN/blank for some rows keeps
    the auto-generated name for those rows — we never fabricate a name."""
    vm = VenueManager(geography=loaded_geography, filter_by_geography=False)

    df = pd.DataFrame({
        'name': ['Real Name', None],
        'geo_unit': ['SGU_001', 'SGU_002'],
    })

    vm.load_venue_type_from_df('cinema', df)

    cinemas = vm.get_venues_by_type('cinema')
    assert len(cinemas) == 2
    names = {v.name for v in cinemas}
    # One named from CSV, one keeps its auto-generated name.
    assert 'Real Name' in names
    assert 'cinema_1' in names


# ---------------------------------------------------------------------------
# Name collisions
# ---------------------------------------------------------------------------

def test_cross_type_name_collision_keeps_both_venues(loaded_geography, caplog):
    """A school and a boarding_school sharing a name (real-world overlap)
    must both remain accessible. Flat lookup is documented-ambiguous; the
    type-scoped lookup is lossless."""
    vm = VenueManager(geography=loaded_geography, filter_by_geography=False)

    school_df = pd.DataFrame({
        'name': ['Durham Cathedral Schools Foundation'],
        'geo_unit': ['SGU_001'],
    })
    boarding_df = pd.DataFrame({
        'name': ['Durham Cathedral Schools Foundation'],
        'geo_unit': ['SGU_001'],
    })

    with caplog.at_level(logging.WARNING, logger='venuemanager'):
        vm.load_venue_type_from_df('school', school_df)
        vm.load_venue_type_from_df('boarding_school', boarding_df)

    # Both venues exist.
    assert len(vm.get_venues_by_type('school')) == 1
    assert len(vm.get_venues_by_type('boarding_school')) == 1

    # Type-scoped lookup is lossless across types.
    school = vm.get_venue_by_type_and_name('school', 'Durham Cathedral Schools Foundation')
    boarding = vm.get_venue_by_type_and_name('boarding_school', 'Durham Cathedral Schools Foundation')
    assert school is not None
    assert boarding is not None
    assert school is not boarding
    assert school.type == 'school'
    assert boarding.type == 'boarding_school'

    # A collision warning was emitted.
    assert any(
        'collision' in r.message and 'Durham Cathedral' in r.message
        for r in caplog.records
    )


def test_same_type_duplicate_does_not_emit_cross_type_warning(loaded_geography, caplog):
    """A same-type duplicate must only emit the 'Duplicate {type} name'
    warning. The cross-type 'Venue name collision' warning would be
    misleading here — it points users to get_venue_by_type_and_name, which
    can't disambiguate same-type duplicates."""
    vm = VenueManager(geography=loaded_geography, filter_by_geography=False)
    df = pd.DataFrame({
        'name': ['Church View', 'Church View'],
        'geo_unit': ['SGU_001', 'SGU_002'],
    })

    with caplog.at_level(logging.WARNING, logger='venuemanager'):
        vm.load_venue_type_from_df('care_home', df)

    cross_type_warnings = [
        r for r in caplog.records
        if 'Venue name collision' in r.message and 'Church View' in r.message
    ]
    same_type_warnings = [
        r for r in caplog.records
        if 'Duplicate care_home name' in r.message and 'Church View' in r.message
    ]
    assert cross_type_warnings == []
    assert len(same_type_warnings) == 1


def test_same_type_name_collision_keeps_both_venues(loaded_geography, caplog):
    """Two care_homes named 'Church View' (real duplication in source data)
    must both remain reachable by their (type, id) — name lookup is
    necessarily ambiguous, but no venue is silently destroyed."""
    vm = VenueManager(geography=loaded_geography, filter_by_geography=False)

    df = pd.DataFrame({
        'name': ['Church View', 'Church View'],
        'geo_unit': ['SGU_001', 'SGU_002'],
        'capacity': [10, 20],
    })

    with caplog.at_level(logging.WARNING, logger='venuemanager'):
        vm.load_venue_type_from_df('care_home', df)

    homes = vm.get_venues_by_type('care_home')
    assert len(homes) == 2
    # Both have distinct IDs and remain addressable.
    assert {h.id for h in homes} == {0, 1}
    assert vm.get_venue_by_type_and_id('care_home', 0) is not None
    assert vm.get_venue_by_type_and_id('care_home', 1) is not None
    # Their capacities are preserved (no merging/overwriting at the venue level).
    assert {h.properties['capacity'] for h in homes} == {10, 20}
    # Same-type duplicate name was warned about.
    assert any('Duplicate care_home name' in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Missing CSV file
# ---------------------------------------------------------------------------

def test_missing_csv_fails_loud(loaded_geography, tmp_path):
    """An enabled venue type pointing at an absent CSV is a hard error — the
    engine works on complete data or fails loudly (adr/0010, 0004). A typo'd
    filename must not silently build an empty venue set."""
    venues_dir = tmp_path / "venues"
    venues_dir.mkdir()
    (venues_dir / "cinemas.csv").write_text(
        "name,geo_unit\nOdeon,SGU_001\n"
    )
    (venues_dir / "test_venues_config.yaml").write_text(
        "venue_types:\n"
        "  cinema:\n"
        "    enabled: true\n"
        "    filename: cinemas.csv\n"
        "  field:\n"
        "    enabled: true\n"
        "    filename: field.csv\n"   # does not exist
        "settings:\n"
        "  filter_by_geography: true\n"
    )

    vm = VenueManager(geography=loaded_geography, data_dir=str(venues_dir))
    with pytest.raises(VenueError, match="field.csv"):
        vm.load_from_yaml_config("test_venues_config.yaml")


# ---------------------------------------------------------------------------
# filter_column / filter_values
# ---------------------------------------------------------------------------

def test_filter_column_filter_values_drops_rows(loaded_geography, caplog):
    """When a venue config specifies filter_column + filter_values, only
    matching rows are loaded. Filtering is case- and whitespace-insensitive
    (per the existing implementation contract)."""
    vm = VenueManager(geography=loaded_geography, filter_by_geography=False)

    df = pd.DataFrame({
        'name': ['Keep1', 'Keep2', 'Drop1', 'Drop2'],
        'geo_unit': ['SGU_001', 'SGU_002', 'SGU_001', 'SGU_002'],
        'category': ['  retail ', 'RETAIL', 'wholesale', 'office'],
    })

    with caplog.at_level(logging.INFO, logger='venuemanager'):
        vm.load_venue_type_from_df(
            'company', df,
            filter_column='category',
            filter_values=['retail'],
        )

    company_names = {v.name for v in vm.get_venues_by_type('company')}
    assert company_names == {'Keep1', 'Keep2'}


# ---------------------------------------------------------------------------
# extend() ID counter merge
# ---------------------------------------------------------------------------

def test_extend_merges_id_counters_no_collision(loaded_geography):
    """After extend(), creating a new venue must not reuse an ID from the
    imported manager."""
    vm_a = VenueManager(geography=loaded_geography, filter_by_geography=False)
    vm_b = VenueManager(geography=loaded_geography, filter_by_geography=False)

    geo_unit = loaded_geography.get_unit('SGU_001')

    # vm_b creates two hospitals -> ids 0, 1
    vm_b.create_venue('hospital', geo_unit)
    vm_b.create_venue('hospital', geo_unit)
    assert {v.id for v in vm_b.get_venues_by_type('hospital')} == {0, 1}

    vm_a.extend(vm_b)
    # vm_a now contains both vm_b hospitals.
    assert {v.id for v in vm_a.get_venues_by_type('hospital')} == {0, 1}

    # The next hospital created on vm_a must not collide with imported IDs.
    new_hospital = vm_a.create_venue('hospital', geo_unit)
    existing_ids = {v.id for v in vm_a.get_venues_by_type('hospital') if v is not new_hospital}
    assert new_hospital.id not in existing_ids
    assert new_hospital.id >= 2


# ---------------------------------------------------------------------------
# subset metadata propagation
# ---------------------------------------------------------------------------

def test_venue_type_metadata_propagates_to_venues(loaded_geography, tmp_path):
    """Properties declared on the venue type config (is_residence,
    subset_categories, subset_key) must end up on every venue's properties.

    Note: capacity rules used to live here under `capacity_config` but were
    moved to the allocation step that owns them. venues_config now describes
    only the venue itself.
    """
    venues_dir = tmp_path / "venues"
    venues_dir.mkdir()
    (venues_dir / "dorms.csv").write_text(
        "name,geo_unit,n_total\nHall A,SGU_001,50\n"
    )
    (venues_dir / "test_venues_config.yaml").write_text(
        "venue_types:\n"
        "  student_dorms:\n"
        "    enabled: true\n"
        "    filename: dorms.csv\n"
        "    is_residence: true\n"
        "    subset_key: age\n"
        "    subset_categories: [young, old]\n"
        "settings:\n"
        "  filter_by_geography: true\n"
    )

    vm = VenueManager(geography=loaded_geography, data_dir=str(venues_dir))
    vm.load_from_yaml_config("test_venues_config.yaml")

    dorms = vm.get_venues_by_type('student_dorms')
    assert len(dorms) == 1
    venue = dorms[0]
    assert venue.properties.get('is_residence') is True
    assert venue.properties.get('subset_key') == 'age'
    assert venue.properties.get('subset_categories') == ['young', 'old']
    # is_residence_type derives from venue_configs.
    assert vm.is_residence_type('student_dorms') is True
    # capacity rules no longer come from venues_config.
    assert vm.get_capacity_config('student_dorms') is None


# ---------------------------------------------------------------------------
# Total-venues log line reports the true count
# ---------------------------------------------------------------------------

def test_total_venues_log_reflects_true_count_with_collisions(loaded_geography, tmp_path, caplog):
    """The 'Total venues created' line must reflect the actual number of
    venues (sum across type lists), not the lossy flat-name-dict size.
    When names collide, both numbers should be reported."""
    venues_dir = tmp_path / "venues"
    venues_dir.mkdir()
    # Two care_homes with the same name -> 2 venues, 1 unique name.
    (venues_dir / "homes.csv").write_text(
        "name,geo_unit\nChurch View,SGU_001\nChurch View,SGU_002\n"
    )
    (venues_dir / "test_venues_config.yaml").write_text(
        "venue_types:\n"
        "  care_home:\n"
        "    enabled: true\n"
        "    filename: homes.csv\n"
        "settings:\n"
        "  filter_by_geography: true\n"
    )

    vm = VenueManager(geography=loaded_geography, data_dir=str(venues_dir))
    with caplog.at_level(logging.INFO, logger='venuemanager'):
        vm.load_from_yaml_config("test_venues_config.yaml")

    total_lines = [r.message for r in caplog.records if 'Total venues created' in r.message]
    assert len(total_lines) == 1
    line = total_lines[0]
    # True count is 2; unique-name count is 1; both must be visible.
    assert '2' in line
    assert '1' in line
    assert 'shadowed' in line


def test_total_venues_log_no_parenthetical_when_no_collisions(loaded_geography, tmp_path, caplog):
    """No collisions means no shadow count — keep the line clean."""
    venues_dir = tmp_path / "venues"
    venues_dir.mkdir()
    (venues_dir / "homes.csv").write_text(
        "name,geo_unit\nA,SGU_001\nB,SGU_002\n"
    )
    (venues_dir / "test_venues_config.yaml").write_text(
        "venue_types:\n"
        "  care_home:\n"
        "    enabled: true\n"
        "    filename: homes.csv\n"
        "settings:\n"
        "  filter_by_geography: true\n"
    )

    vm = VenueManager(geography=loaded_geography, data_dir=str(venues_dir))
    with caplog.at_level(logging.INFO, logger='venuemanager'):
        vm.load_from_yaml_config("test_venues_config.yaml")

    total_lines = [r.message for r in caplog.records if 'Total venues created' in r.message]
    assert len(total_lines) == 1
    assert total_lines[0].strip() == 'Total venues created: 2'


# ---------------------------------------------------------------------------
# Production yaml no longer references missing field.csv
# ---------------------------------------------------------------------------

def test_production_yaml_does_not_reference_missing_files():
    """Each enabled venue type in configs/2021/venues/venues_config.yaml must
    point to a file that actually exists on disk. This is a guardrail against
    re-introducing the field.csv-style discrepancy between configured and
    loaded venue counts."""
    import yaml

    config_path = "configs/2021/venues/venues_config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    missing = []
    for venue_type, type_config in (config.get('venue_types') or {}).items():
        if not type_config.get('enabled', True):
            continue
        filename = type_config.get('filename', f"{venue_type}s.csv")
        # Resolve relative to the production data dir.
        full_path = os.path.join("data/venues", filename)
        if not os.path.exists(full_path):
            missing.append((venue_type, full_path))

    assert not missing, f"Enabled venue types reference missing CSVs: {missing}"
