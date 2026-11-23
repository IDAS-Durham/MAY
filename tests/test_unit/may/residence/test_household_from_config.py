import logging

import pytest

from may.residence.household_distributor import HouseholdDistributor, HouseholdError
from may.utils import path_resolver

CATEGORIES = (
    "categories:\n"
    "  - {name: Kids, symbol: K, attribute: age, type: numerical,"
    " numerical: {min: 0, max: 17}}\n"
    "  - {name: Adults, symbol: A, attribute: age, type: numerical,"
    " numerical: {min: 18, max: null}}\n"
)


@pytest.fixture(autouse=True)
def reset_resolver(monkeypatch):
    monkeypatch.setattr(path_resolver, "_resolver", None)


@pytest.fixture
def data_dir(tmp_path):
    directory = tmp_path / "households"
    directory.mkdir()
    return directory


def block_for(data_dir, config_text=CATEGORIES, **overrides):
    (data_dir / "households.yaml").write_text(config_text)
    block = {
        "data_dir": str(data_dir),
        "config_file": "households.yaml",
        "data_file": "households.csv",
    }
    block.update(overrides)
    return block


def build(block):
    return HouseholdDistributor.from_config(
        block, geography=None, population=None, venue_manager=None
    )


def test_problems_raise_household_error_with_every_line(data_dir):
    block = block_for(
        data_dir,
        "categories:\n  - {name: Kids, symbol: K, attribute: age, type: banana}\n",
    )
    del block["data_file"]
    with pytest.raises(HouseholdError) as raised:
        build(block)
    message = str(raised.value)
    assert message.startswith("Household config has 2 problem(s):")
    assert "data_file" in message
    assert "categories[0].type" in message
    assert len(raised.value.report.problems) == 2


def test_warnings_are_logged_at_info(data_dir, caplog):
    with caplog.at_level(logging.INFO, logger="household"):
        build(block_for(data_dir))
    warning_records = [
        record for record in caplog.records if "rules_file" in record.getMessage()
    ]
    assert [record.levelno for record in warning_records] == [logging.INFO]
    assert "relationship rules disabled" in warning_records[0].getMessage()


def test_rules_file_in_data_dir_reaches_validator(data_dir):
    (data_dir / "rules.yaml").write_text("enabled: true\n")
    distributor = build(block_for(data_dir, rules_file="rules.yaml"))
    assert distributor.relationship_rules.enabled


def test_unset_rules_file_disables_validator(data_dir):
    distributor = build(block_for(data_dir))
    assert not distributor.relationship_rules.enabled
