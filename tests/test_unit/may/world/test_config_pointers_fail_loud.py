"""
A config key that names a file is either written or rejected, never guessed.

Two blocks completed themselves when a pointer was absent (timeline steps, once a third,
are covered in tests/test_unit/may/timeline/test_timeline_steps.py): the romantic block filled in
2021's orientation model, so a Mexico or 1911 world would have built with UK census
marginals raked over its own geography; and the households block guessed a CWD-relative
`data/households/households.csv`, so the loader reported a missing file the author never
named. The last one is why the message matters as much as the raise: the defect is the
absent key, not the missing file.
"""
import pathlib

import pytest

from may.timeline import require_config_path
from may.residence.household_distributor import HouseholdError
from may.world import setup_households


# --- #7: the relationship blocks --------------------------------------------------


def test_romantic_block_without_a_config_raises():
    """It used to load configs/2021/relationships/romantic_relationships.yaml."""
    with pytest.raises(ValueError, match="romantic_relationships"):
        require_config_path(
            "`romantic_relationships.enabled: true`", {"enabled": True}
        )


def test_no_scenario_path_is_hardcoded_as_a_default():
    assert "configs/2021/relationships" not in pathlib.Path("create_world.py").read_text()


def test_relationship_pipeline_entry_without_a_config_raises():
    with pytest.raises(ValueError, match="must set `config:`"):
        require_config_path(
            "Every `relationship_pipeline.relationships` entry", {"name": "friends"}
        )


# --- #21: the households pointer --------------------------------------------------


@pytest.mark.parametrize("absent", ["data_dir", "config_file", "data_file"])
def test_households_block_names_the_absent_key(absent):
    """
    The old message named `data/households/households.csv`, a path the config never
    mentioned and the author never chose.
    """
    households = {"data_dir": "d", "config_file": "c.yaml", "data_file": "h.csv"}
    households.pop(absent)

    with pytest.raises(HouseholdError, match=absent):
        setup_households(geo=None, population=None, venues=None,
                         config={"households": households})


def test_the_message_does_not_invent_a_path():
    with pytest.raises(HouseholdError) as excinfo:
        setup_households(geo=None, population=None, venues=None, config={"households": {}})

    assert "data/households" not in str(excinfo.value)
    assert "households.csv" not in str(excinfo.value)
