"""
`run_timeline` runs a world config's timeline steps in order, each through the entry
point its type names, and turns any failure into a logged `TimelineError` the entry
point exits on.
"""
from unittest.mock import MagicMock, patch

import pytest

from may import timeline


def timeline_config(*steps, **extra_blocks):
    return {"timeline": {"enabled": True, "steps": list(steps)}, **extra_blocks}


def test_residence_allocation_sets_up_households_and_attaches_the_distributor():
    world = MagicMock()
    world_config = timeline_config(
        {"type": "residence_allocation", "config": "allocation_strategy.yaml"},
        households={"data_dir": "d"},
    )

    with patch.object(timeline, "setup_households") as setup_households:
        timeline.run_timeline(world, world_config)

    setup_households.assert_called_once()
    call = setup_households.call_args
    assert call.args[:3] == (world.geography, world.population, world.venues)
    assert call.args[3]["households"] == {"data_dir": "d"}
    assert call.kwargs["strategy_file"].endswith("allocation_strategy.yaml")
    assert world.household_distributor is setup_households.return_value


def test_attribute_step_assigns_attributes_from_its_config():
    world = MagicMock()

    timeline.run_timeline(world, timeline_config({"type": "attribute", "config": "age.yaml"}))

    (config_path,), _ = world.assign_attributes.call_args
    assert config_path.endswith("age.yaml")


def test_distributor_step_builds_the_distributor_and_allocates_into_the_world():
    world = MagicMock()

    with patch.object(timeline, "distributor_from_yaml") as distributor_from_yaml:
        timeline.run_timeline(world, timeline_config({"type": "distributor", "config": "pubs.yaml"}))

    (config_path,), _ = distributor_from_yaml.call_args
    assert config_path.endswith("pubs.yaml")
    distributor_from_yaml.return_value.allocate.assert_called_once_with(world)


def test_child_creator_step_creates_children_in_the_world():
    world = MagicMock()

    with patch.object(timeline, "VenueChildCreator") as venue_child_creator:
        timeline.run_timeline(world, timeline_config({"type": "child_creator", "config": "rooms.yaml"}))

    (config_path,), _ = venue_child_creator.from_yaml.call_args
    assert config_path.endswith("rooms.yaml")
    venue_child_creator.from_yaml.return_value.create_children.assert_called_once_with(world)


def recording_registry(calls, failure=None, expected_errors=()):
    """Every step type records (type, config stem) when run, then raises ``failure``."""
    def recorder(step_type):
        def handler(world, config_path, world_config):
            calls.append(timeline.step_label(step_type, config_path))
            if failure is not None:
                raise failure
        return handler

    return {
        step_type: timeline.TimelineStep(
            handler=recorder(step_type), expected_errors=expected_errors,
        )
        for step_type in timeline.TIMELINE_STEPS
    }


def test_steps_run_in_the_order_written():
    calls = []
    world_config = timeline_config(
        {"type": "attribute", "config": "age.yaml"},
        {"type": "residence_allocation", "config": "strategy.yaml"},
        {"type": "distributor", "config": "pubs.yaml"},
        {"type": "attribute", "config": "income.yaml"},
        {"type": "child_creator", "config": "rooms.yaml"},
    )

    with patch.dict(timeline.TIMELINE_STEPS, recording_registry(calls)):
        timeline.run_timeline(MagicMock(), world_config)

    assert calls == [
        "attribute:age", "residence_allocation:strategy", "distributor:pubs",
        "attribute:income", "child_creator:rooms",
    ]


class StepFailure(Exception):
    pass


def test_an_expected_error_logs_one_line_and_raises_a_timeline_error(caplog):
    world_config = timeline_config({"type": "attribute", "config": "age.yaml"})
    registry = recording_registry(
        [], failure=StepFailure("bad marginals"), expected_errors=(StepFailure,),
    )

    with patch.dict(timeline.TIMELINE_STEPS, registry), \
            pytest.raises(timeline.TimelineError) as excinfo:
        timeline.run_timeline(MagicMock(), world_config)

    assert isinstance(excinfo.value.__cause__, (StepFailure, KeyError))
    errors = [record for record in caplog.records if record.levelname == "ERROR"]
    assert len(errors) == 1
    assert "attribute" in errors[0].getMessage()
    assert "age.yaml" in errors[0].getMessage()
    assert "bad marginals" in errors[0].getMessage()
    assert errors[0].exc_info is None


def test_an_unexpected_error_logs_its_traceback_and_raises_a_timeline_error(caplog):
    world_config = timeline_config({"type": "distributor", "config": "pubs.yaml"})
    registry = recording_registry([], failure=KeyError("venue_id"))

    with patch.dict(timeline.TIMELINE_STEPS, registry), \
            pytest.raises(timeline.TimelineError) as excinfo:
        timeline.run_timeline(MagicMock(), world_config)

    assert isinstance(excinfo.value.__cause__, (StepFailure, KeyError))
    errors = [record for record in caplog.records if record.levelname == "ERROR"]
    assert any("distributor" in record.getMessage() and "pubs.yaml" in record.getMessage()
               for record in errors)
    assert any(record.exc_info is not None for record in errors)


def test_a_failed_step_stops_the_timeline():
    calls = []
    world_config = timeline_config(
        {"type": "distributor", "config": "pubs.yaml"},
        {"type": "distributor", "config": "gyms.yaml"},
    )

    with patch.dict(timeline.TIMELINE_STEPS, recording_registry(calls, failure=KeyError("x"))):
        with pytest.raises(timeline.TimelineError):
            timeline.run_timeline(MagicMock(), world_config)

    assert calls == ["distributor:pubs"]


@pytest.mark.parametrize("world_config", [
    {},
    {"timeline": {"enabled": False, "steps": [{"type": "attribute", "config": "a.yaml"}]}},
    {"timeline": {"enabled": True, "steps": []}},
    {"timeline": {"enabled": True}},
    {"timeline": None},
], ids=["missing", "disabled", "empty", "no_steps", "blank_key"])
def test_a_world_without_an_enabled_timeline_is_rejected(world_config):
    with pytest.raises(ValueError, match="No enabled timeline with steps found"):
        timeline.run_timeline(MagicMock(), world_config)


def households_warnings(caplog):
    return [record for record in caplog.records
            if record.levelname == "WARNING" and "residence_allocation" in record.getMessage()]


def test_a_households_block_without_a_residence_step_warns(caplog):
    world_config = timeline_config(
        {"type": "attribute", "config": "age.yaml"}, households={"data_dir": "d"},
    )

    with patch.dict(timeline.TIMELINE_STEPS, recording_registry([])):
        timeline.run_timeline(MagicMock(), world_config)

    assert len(households_warnings(caplog)) == 1


def test_a_households_block_with_a_residence_step_does_not_warn(caplog):
    world_config = timeline_config(
        {"type": "residence_allocation", "config": "s.yaml"}, households={"data_dir": "d"},
    )

    with patch.dict(timeline.TIMELINE_STEPS, recording_registry([])):
        timeline.run_timeline(MagicMock(), world_config)

    assert households_warnings(caplog) == []


def test_an_unknown_step_type_fails_in_resolution_not_in_the_households_check(caplog):
    world_config = timeline_config(
        {"type": "attribut", "config": "age.yaml"}, households={"data_dir": "d"},
    )

    with pytest.raises(ValueError, match="Unknown timeline step type 'attribut'"):
        timeline.run_timeline(MagicMock(), world_config)


@pytest.mark.parametrize("step", ["attribute", None, ["attribute", "age.yaml"]],
                         ids=["string", "blank", "list"])
def test_a_step_that_is_not_a_mapping_is_rejected_before_the_households_check(step):
    world_config = timeline_config(step, households={"data_dir": "d"})

    with pytest.raises(ValueError, match="Timeline step 1 must be a mapping"):
        timeline.run_timeline(MagicMock(), world_config)


def test_each_step_runs_in_a_build_profile_stage_named_by_its_label():
    world_config = timeline_config(
        {"type": "distributor", "config": "pubs.yaml"},
        {"type": "child_creator", "config": "rooms.yaml"},
    )

    with patch.dict(timeline.TIMELINE_STEPS, recording_registry([])), \
            patch.object(timeline.bp, "stage") as stage:
        timeline.run_timeline(MagicMock(), world_config)

    stages = [(call.args, call.kwargs["detail"]) for call in stage.call_args_list]
    assert [args for args, _ in stages] == [
        ("distributor:pubs", "distributor"), ("child_creator:rooms", "child_creator"),
    ]
    assert stages[0][1].endswith("pubs.yaml")
    assert stage.return_value.__enter__.call_count == 2


@pytest.mark.parametrize("step_type, header", [
    ("residence_allocation", "[RESIDENCE ALLOCATION]"),
    ("attribute", "[ATTRIBUTE]"),
    ("distributor", "[DISTRIBUTOR]"),
    ("child_creator", "[CHILD CREATOR]"),
])
def test_each_step_logs_its_header(caplog, step_type, header):
    caplog.set_level("INFO")
    world_config = timeline_config({"type": step_type, "config": "step.yaml"})

    with patch.dict(timeline.TIMELINE_STEPS, recording_registry([])):
        timeline.run_timeline(MagicMock(), world_config)

    messages = [record.getMessage() for record in caplog.records]
    assert any(message.startswith(f"{header} ") and message.endswith("step.yaml")
               for message in messages)
