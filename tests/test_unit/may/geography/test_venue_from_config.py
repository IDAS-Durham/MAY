import logging

import pytest

from may.geography import Geography
from may.geography.venue_manager import VenueError, VenueManager
from may.utils import path_resolver


@pytest.fixture(autouse=True)
def reset_resolver(monkeypatch):
    monkeypatch.setattr(path_resolver, "_resolver", None)


@pytest.fixture
def loaded_geography():
    geography = Geography(
        data_dir="tests/test_data/micro_world/geography",
        levels=["SGU", "MGU", "LGU"],
        hierarchy_file="hierarchy.csv",
    )
    geography.load_from_csv()
    return geography


@pytest.fixture
def venues_dir(tmp_path):
    directory = tmp_path / "venues"
    directory.mkdir()
    return directory


def block_for(venues_dir, config_text):
    (venues_dir / "venues.yaml").write_text(config_text)
    return {"data_dir": str(venues_dir), "config_file": "venues.yaml"}


def test_problems_raise_venue_error_with_every_line(loaded_geography, venues_dir):
    block = block_for(
        venues_dir,
        "venue_types:\n"
        "  school:\n"
        "    enabled: 'yes'\n"
        "    filename: schools.csv\n"
        "  pub:\n"
        "    enabled: true\n",
    )
    with pytest.raises(VenueError) as raised:
        VenueManager.from_config(block, loaded_geography)
    message = str(raised.value)
    assert message.startswith("Venue config has 2 problem(s):")
    assert "venue_types.school.enabled" in message
    assert "venue_types.pub.filename" in message
    assert len(raised.value.report.problems) == 2


def test_warnings_are_logged_at_info(loaded_geography, venues_dir, caplog):
    block = block_for(
        venues_dir,
        "venue_types:\n"
        "  school:\n"
        "    enabled: false\n"
        "    filter_column: phase\n",
    )
    with caplog.at_level(logging.INFO, logger="venuemanager"):
        VenueManager.from_config(block, loaded_geography)
    warning_records = [
        record for record in caplog.records if "venue_types.school.filter_values" in record.getMessage()
    ]
    assert [record.levelno for record in warning_records] == [logging.INFO]
    assert "not set; filter_column ignored" in warning_records[0].getMessage()


def venue_names(venue_manager, venue_type):
    return sorted(venue.name for venue in venue_manager.get_venues_by_type(venue_type))


def test_single_file_type_is_loaded(loaded_geography, venues_dir):
    (venues_dir / "schools.csv").write_text("name,geo_unit\nAlpha,SGU_001\nBeta,SGU_002\n")
    block = block_for(
        venues_dir,
        "venue_types:\n"
        "  school:\n"
        "    filename: schools.csv\n",
    )
    venue_manager = VenueManager.from_config(block, loaded_geography)
    assert venue_names(venue_manager, "school") == ["Alpha", "Beta"]


def test_batch_type_loads_one_file_per_unit_present(loaded_geography, venues_dir):
    (venues_dir / "pubs_MGU_01.csv").write_text("name,geo_unit\nCrown,SGU_001\n")
    (venues_dir / "pubs_MGU_02.csv").write_text("name,geo_unit\nAnchor,SGU_003\n")
    block = block_for(
        venues_dir,
        "venue_types:\n"
        "  pub:\n"
        "    batch_mode: true\n"
        "    filename: 'pubs_{unit}.csv'\n",
    )
    venue_manager = VenueManager.from_config(block, loaded_geography)
    assert venue_names(venue_manager, "pub") == ["Anchor", "Crown"]


def test_batch_type_matching_no_files_raises(loaded_geography, venues_dir):
    block = block_for(
        venues_dir,
        "venue_types:\n"
        "  pub:\n"
        "    batch_mode: true\n"
        "    filename: 'pubs_{unit}.csv'\n",
    )
    with pytest.raises(VenueError, match="matched no files"):
        VenueManager.from_config(block, loaded_geography)


def test_filter_keeps_only_matching_rows(loaded_geography, venues_dir):
    (venues_dir / "schools.csv").write_text(
        "name,geo_unit,phase\nAlpha,SGU_001,primary\nBeta,SGU_002,secondary\n"
    )
    block = block_for(
        venues_dir,
        "venue_types:\n"
        "  school:\n"
        "    filename: schools.csv\n"
        "    filter_column: phase\n"
        "    filter_values: [primary]\n",
    )
    venue_manager = VenueManager.from_config(block, loaded_geography)
    assert venue_names(venue_manager, "school") == ["Alpha"]


def test_dtype_reads_column_as_named_type(loaded_geography, venues_dir):
    (venues_dir / "schools.csv").write_text("name,geo_unit,code\nAlpha,SGU_001,007\n")
    block = block_for(
        venues_dir,
        "venue_types:\n"
        "  school:\n"
        "    filename: schools.csv\n"
        "    dtype: {code: str}\n",
    )
    venue_manager = VenueManager.from_config(block, loaded_geography)
    [school] = venue_manager.get_venues_by_type("school")
    assert school.properties["code"] == "007"


def test_settings_filter_by_geography_overrides_default(loaded_geography, venues_dir):
    block = block_for(
        venues_dir,
        "venue_types: {}\n"
        "settings:\n"
        "  filter_by_geography: false\n",
    )
    assert VenueManager.from_config(block, loaded_geography).filter_by_geography is False


def test_unset_filter_by_geography_keeps_default(loaded_geography, venues_dir):
    block = block_for(venues_dir, "venue_types: {}\n")
    assert VenueManager.from_config(block, loaded_geography).filter_by_geography is True


def test_empty_venue_types_loads_no_venues(loaded_geography, venues_dir):
    block = block_for(venues_dir, "venue_types: {}\n")
    assert VenueManager.from_config(block, loaded_geography).get_all_venues_list() == []


def test_disabled_type_config_is_recorded(loaded_geography, venues_dir):
    block = block_for(
        venues_dir,
        "venue_types:\n"
        "  household:\n"
        "    enabled: false\n"
        "    is_residence: true\n",
    )
    venue_manager = VenueManager.from_config(block, loaded_geography)
    assert venue_manager.is_residence_type("household") is True
    assert venue_manager.get_venues_by_type("household") == []


def test_csv_load_without_data_dir_raises(loaded_geography):
    venue_manager = VenueManager(loaded_geography, filter_by_geography=False)
    with pytest.raises(VenueError, match="no data_dir"):
        venue_manager.load_venue_type_from_csv("school", "schools.csv")
