"""
A config key that names a file is either written or rejected, never guessed.

Three blocks completed themselves when a pointer was absent. A timeline step with no
`config:` carried a falsy path into whichever loader it hit; the romantic block filled in
2021's orientation model, so a Mexico or 1911 world would have built with UK census
marginals raked over its own geography; and the households block guessed a CWD-relative
`data/households/households.csv`, so the loader reported a missing file the author never
named. The last one is why the message matters as much as the raise: the defect is the
absent key, not the missing file.
"""
import pathlib

import pytest

import create_world
from may.residence.household_distributor import HouseholdError
from may.world import setup_households


# --- #5 and #6: timeline steps ----------------------------------------------------


def test_the_step_vocabulary_is_the_four_dispatched_types():
    assert create_world.VALID_TIMELINE_STEP_TYPES == {
        "residence_allocation", "attribute", "distributor", "child_creator",
    }


@pytest.mark.parametrize("step_type", sorted(create_world.VALID_TIMELINE_STEP_TYPES))
def test_every_step_type_reports_a_missing_config(step_type):
    """
    `pr.resolve` passes None and '' straight through, so all four used to reach the
    dispatch. Only `residence_allocation` said why; the rest died by traceback.
    """
    with pytest.raises(ValueError, match=f"`{step_type}` timeline step must set `config:`"):
        create_world.resolve_timeline_step({"type": step_type})


@pytest.mark.parametrize("empty", [None, ""])
def test_a_falsy_config_is_a_missing_one(empty):
    with pytest.raises(ValueError, match="must set `config:`"):
        create_world.resolve_timeline_step({"type": "attribute", "config": empty})


def test_residence_allocation_keeps_its_example_path():
    with pytest.raises(ValueError, match="allocation_strategy.yaml"):
        create_world.resolve_timeline_step({"type": "residence_allocation"})


def test_unknown_step_type_raises_rather_than_skipping_the_step():
    with pytest.raises(ValueError, match="Unknown timeline step type 'attribut'"):
        create_world.resolve_timeline_step({"type": "attribut", "config": "x.yaml"})


def test_a_valid_step_resolves():
    step_type, path = create_world.resolve_timeline_step(
        {"type": "distributor", "config": "d.yaml"}
    )

    assert step_type == "distributor"
    assert path.endswith("d.yaml")


# --- #7: the relationship blocks --------------------------------------------------


def test_romantic_block_without_a_config_raises():
    """It used to load configs/2021/relationships/romantic_relationships.yaml."""
    with pytest.raises(ValueError, match="romantic_relationships"):
        create_world.require_config_path(
            "`romantic_relationships.enabled: true`", {"enabled": True}
        )


def test_no_scenario_path_is_hardcoded_as_a_default():
    assert "configs/2021/relationships" not in pathlib.Path("create_world.py").read_text()


def test_relationship_pipeline_entry_without_a_config_raises():
    with pytest.raises(ValueError, match="must set `config:`"):
        create_world.require_config_path(
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
