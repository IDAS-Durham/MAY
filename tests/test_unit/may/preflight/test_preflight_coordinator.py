import logging

import pytest

from may.preflight.preflight_coordinator import check_world_config, run_preflight
from may.preflight.report import PreflightError
from may.utils import path_resolver


@pytest.fixture(autouse=True)
def reset_resolver(monkeypatch):
    monkeypatch.setattr(path_resolver, "_resolver", None)


@pytest.fixture
def venues_dir(tmp_path):
    directory = tmp_path / "venues"
    directory.mkdir()
    return directory


def keys(findings):
    return [finding.key for finding in findings]


def test_venue_problems_are_prefixed_with_venues(venues_dir):
    config = {
        "venues": {"data_dir": str(venues_dir), "config_file": "missing.yaml"},
        "serialization": {"enabled": False},
    }
    report = check_world_config(config)
    assert keys(report.problems) == ["venues.config_file"]


def test_absent_venues_block_checks_the_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    report = check_world_config({"serialization": {"enabled": False}})
    assert keys(report.problems) == ["venues.config_file"]
    assert "venues_config.yaml" in report.problems[0].message
    assert "data/venues" in report.problems[0].message


def world_config(venues_dir, venues_yaml, serialization_path, serialization_yaml):
    (venues_dir / "venues.yaml").write_text(venues_yaml)
    (venues_dir / "companies.csv").write_text("geo_unit,industry_code\nA,C\n")
    serialization_path.write_text(serialization_yaml)
    return {
        "venues": {"data_dir": str(venues_dir), "config_file": "venues.yaml"},
        "serialization": {"enabled": True, "config_file": str(serialization_path)},
    }


COMPANY_VENUES = "venue_types:\n  company:\n    filename: companies.csv\n"
WORK_SECTOR_SCHEMA = "venues:\n  types:\n    company:\n      properties: [work_sector]\n"


def test_property_missing_from_venue_files_is_a_warning(venues_dir, tmp_path):
    serialization_path = tmp_path / "serialization.yaml"
    config = world_config(venues_dir, COMPANY_VENUES, serialization_path, WORK_SECTOR_SCHEMA)
    report = check_world_config(config)
    assert report.problems == []
    assert [(finding.key, finding.message) for finding in report.warnings] == [
        (
            f"serialization.config_file ({serialization_path}): "
            "venues.types.company.properties",
            "'work_sector' not in the venue files; they carry ['geo_unit', 'industry_code']",
        )
    ]


def test_venue_problems_skip_the_gap_check(venues_dir, tmp_path):
    broken_venues = "venue_types:\n  company:\n    enabled: 'yes'\n    filename: companies.csv\n"
    config = world_config(
        venues_dir, broken_venues, tmp_path / "serialization.yaml", WORK_SECTOR_SCHEMA
    )
    report = check_world_config(config)
    assert keys(report.problems) == [
        f"venues.config_file ({venues_dir / 'venues.yaml'}): venue_types.company.enabled"
    ]
    assert report.warnings == []


@pytest.mark.parametrize(
    "serialization_block",
    [{"enabled": False, "config_file": "missing.yaml"}, {"enabled": False}],
    ids=["disabled_with_missing_file", "disabled_without_file"],
)
def test_no_serialization_findings_without_an_enabled_schema(
    venues_dir, tmp_path, serialization_block
):
    config = world_config(
        venues_dir, COMPANY_VENUES, tmp_path / "serialization.yaml", WORK_SECTOR_SCHEMA
    )
    config["serialization"] = serialization_block
    report = check_world_config(config)
    assert report.problems == []
    assert report.warnings == []


@pytest.mark.parametrize(
    "serialization_block",
    [None, {}, {"enabled": True}, {"output_dir": "out"}, {"config_file": ""}],
    ids=["blank", "empty", "enabled", "output_dir_only", "empty_config_file"],
)
def test_enabled_serialization_without_config_file_is_problem(
    venues_dir, tmp_path, serialization_block
):
    config = world_config(
        venues_dir, COMPANY_VENUES, tmp_path / "serialization.yaml", WORK_SECTOR_SCHEMA
    )
    config["serialization"] = serialization_block
    report = check_world_config(config)
    assert [(finding.key, finding.message) for finding in report.problems] == [
        ("serialization.config_file", "not set; serialisation is enabled")
    ]


def test_serialization_absent_is_problem(venues_dir, tmp_path):
    config = world_config(
        venues_dir, COMPANY_VENUES, tmp_path / "serialization.yaml", WORK_SECTOR_SCHEMA
    )
    del config["serialization"]
    report = check_world_config(config)
    assert keys(report.problems) == ["serialization.config_file"]


@pytest.mark.parametrize(
    "block_name, block_value, expected_message",
    [
        ("venues", "configs/venues_config.yaml", "must be a mapping; got scalar (str)"),
        ("venues", ["a"], "must be a mapping; got sequence (list)"),
        ("serialization", "schema.yaml", "must be a mapping; got scalar (str)"),
        ("serialization", ["a"], "must be a mapping; got sequence (list)"),
    ],
    ids=["venues_string", "venues_list", "serialization_string", "serialization_list"],
)
def test_block_not_mapping_is_problem(
    venues_dir, tmp_path, block_name, block_value, expected_message
):
    config = world_config(
        venues_dir, COMPANY_VENUES, tmp_path / "serialization.yaml", WORK_SECTOR_SCHEMA
    )
    config[block_name] = block_value
    report = check_world_config(config)
    assert [(finding.key, finding.message) for finding in report.problems] == [
        (block_name, expected_message)
    ]
    assert report.warnings == []


def test_missing_schema_file_is_problem(venues_dir, tmp_path):
    config = world_config(
        venues_dir, COMPANY_VENUES, tmp_path / "serialization.yaml", WORK_SECTOR_SCHEMA
    )
    missing_path = tmp_path / "missing.yaml"
    config["serialization"]["config_file"] = str(missing_path)
    report = check_world_config(config)
    assert [(finding.key, finding.message) for finding in report.problems] == [
        ("serialization.config_file", f"{missing_path} not found")
    ]


def test_invalid_schema_yaml_is_problem(venues_dir, tmp_path):
    serialization_path = tmp_path / "serialization.yaml"
    config = world_config(venues_dir, COMPANY_VENUES, serialization_path, "venues: [unclosed\n")
    report = check_world_config(config)
    assert [(finding.key, finding.message) for finding in report.problems] == [
        (
            "serialization.config_file",
            f"{serialization_path} is not valid YAML at line 2, column 1",
        )
    ]


def test_unreadable_schema_is_problem_even_when_venues_are_broken(venues_dir, tmp_path):
    config = {
        "venues": {"data_dir": str(venues_dir), "config_file": "missing.yaml"},
        "serialization": {"enabled": True, "config_file": str(tmp_path / "missing.yaml")},
    }
    report = check_world_config(config)
    assert keys(report.problems) == ["venues.config_file", "serialization.config_file"]


@pytest.mark.parametrize(
    "schema_yaml",
    ["- not a mapping\n", "venues: [a, b]\n", "venues:\n  types: company\n"],
    ids=["top_level_list", "venues_list", "types_string"],
)
def test_gap_check_failure_is_warning(venues_dir, tmp_path, schema_yaml):
    serialization_path = tmp_path / "serialization.yaml"
    config = world_config(venues_dir, COMPANY_VENUES, serialization_path, schema_yaml)
    report = check_world_config(config)
    assert report.problems == []
    assert keys(report.warnings) == [f"serialization.config_file ({serialization_path})"]
    assert report.warnings[0].message.startswith("venue property check skipped: ")


def test_run_preflight_raises_on_problems_after_logging(venues_dir, caplog):
    config = {
        "venues": {"data_dir": str(venues_dir), "config_file": "missing.yaml"},
        "serialization": {"enabled": False},
    }
    with caplog.at_level(logging.INFO, logger="preflight"):
        with pytest.raises(PreflightError) as raised:
            run_preflight(config)
    assert keys(raised.value.report.problems) == ["venues.config_file"]
    assert [record.levelno for record in caplog.records] == [logging.INFO]
    assert caplog.records[0].getMessage() == raised.value.report.format()


def test_run_preflight_returns_report_on_warnings_only(venues_dir, tmp_path, caplog):
    config = world_config(
        venues_dir, COMPANY_VENUES, tmp_path / "serialization.yaml", WORK_SECTOR_SCHEMA
    )
    with caplog.at_level(logging.INFO, logger="preflight"):
        report = run_preflight(config)
    assert len(report.warnings) == 1
    assert caplog.records[0].getMessage() == report.format()


RESIDENCE_TIMELINE = {"steps": [{"type": "residence_allocation"}]}


def households_config(venues_dir, households_block, timeline=RESIDENCE_TIMELINE):
    (venues_dir / "venues.yaml").write_text("venue_types: {}\n")
    return {
        "venues": {"data_dir": str(venues_dir), "config_file": "venues.yaml"},
        "serialization": {"enabled": False},
        "households": households_block,
        "timeline": timeline,
    }


def test_household_problems_are_prefixed_with_households(venues_dir):
    config = households_config(venues_dir, {"config_file": "c.yaml", "data_file": "h.csv"})
    report = check_world_config(config)
    assert ("households.data_dir", "not set; there is no default") in [
        (finding.key, finding.message) for finding in report.problems
    ]


@pytest.mark.parametrize(
    "timeline",
    [None, {"steps": []}, {"steps": [{"type": "venue_allocation"}, "not a step"]}],
    ids=["no_timeline", "no_steps", "other_steps"],
)
def test_households_not_checked_without_residence_step(venues_dir, timeline):
    config = households_config(venues_dir, "not a mapping", timeline=timeline)
    report = check_world_config(config)
    assert report.problems == []
    assert report.warnings == []


def test_households_not_mapping_is_problem(venues_dir):
    config = households_config(venues_dir, ["a"])
    report = check_world_config(config)
    assert [(finding.key, finding.message) for finding in report.problems] == [
        ("households", "must be a mapping; got sequence (list)")
    ]


@pytest.mark.parametrize(
    "timeline, expected_key, expected_message",
    [
        (["a"], "timeline", "must be a mapping; got sequence (list)"),
        ({"steps": "residence_allocation"}, "timeline.steps", "must be a list; got scalar (str)"),
        ({"steps": {"type": "residence_allocation"}}, "timeline.steps", "must be a list; got mapping (dict)"),
    ],
    ids=["timeline_list", "steps_string", "steps_mapping"],
)
def test_malformed_timeline_is_problem_and_skips_households(
    venues_dir, timeline, expected_key, expected_message
):
    config = households_config(venues_dir, "not a mapping", timeline=timeline)
    report = check_world_config(config)
    assert [(finding.key, finding.message) for finding in report.problems] == [
        (expected_key, expected_message)
    ]
