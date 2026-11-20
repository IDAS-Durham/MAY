"""
A timeline step names its type and the config file it runs; both are checked against
the step registry before anything is built.
"""
import pathlib
import subprocess
import sys

import pytest

from may import timeline


def test_the_step_vocabulary_is_the_four_dispatched_types():
    assert set(timeline.TIMELINE_STEPS) == {
        "residence_allocation", "attribute", "distributor", "child_creator",
    }


@pytest.mark.parametrize("step_type", sorted(timeline.TIMELINE_STEPS))
def test_every_step_type_reports_a_missing_config(step_type):
    """
    `pr.resolve` passes None and '' straight through, so all four used to reach the
    dispatch. Only `residence_allocation` said why; the rest died by traceback.
    """
    with pytest.raises(ValueError, match=f"`{step_type}` timeline step must set `config:`"):
        timeline.resolve_timeline_step({"type": step_type})


@pytest.mark.parametrize("empty", [None, ""])
def test_a_falsy_config_is_a_missing_one(empty):
    with pytest.raises(ValueError, match="must set `config:`"):
        timeline.resolve_timeline_step({"type": "attribute", "config": empty})


def test_residence_allocation_keeps_its_example_path():
    with pytest.raises(ValueError, match="allocation_strategy.yaml"):
        timeline.resolve_timeline_step({"type": "residence_allocation"})


def test_unknown_step_type_names_it_and_lists_the_valid_ones():
    with pytest.raises(ValueError) as excinfo:
        timeline.resolve_timeline_step({"type": "attribut", "config": "x.yaml"})

    message = str(excinfo.value)
    assert "Unknown timeline step type 'attribut'" in message
    for step_type in timeline.TIMELINE_STEPS:
        assert step_type in message


def test_a_valid_step_resolves():
    step_type, path = timeline.resolve_timeline_step(
        {"type": "distributor", "config": "d.yaml"}
    )

    assert step_type == "distributor"
    assert path.endswith("d.yaml")


def test_a_step_is_labelled_by_its_type_and_config_stem():
    """Twelve distributors read as twelve build-profile stages rather than one."""
    assert timeline.step_label("distributor", "/a/b/pubs.yaml") == "distributor:pubs"


@pytest.mark.parametrize("absent", [None, ""])
def test_a_step_without_config_is_labelled_by_its_type(absent):
    assert timeline.step_label("romantic", absent) == "romantic"


def test_importing_the_timeline_seeds_nothing_and_configures_no_logging():
    """`create_world` seeds RNGs and configures logging at import; the timeline must not."""
    probe = (
        "import logging, numpy as np\n"
        "np.random.seed(12345)\n"
        "before = np.random.get_state()[1].copy()\n"
        "import may.timeline\n"
        "assert (np.random.get_state()[1] == before).all(), 'numpy RNG reseeded'\n"
        "assert not logging.getLogger().handlers, 'root logger configured'\n"
        "assert logging.getLogger().level == logging.WARNING, 'root level changed'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True,
        cwd=pathlib.Path(__file__).parents[4],
    )

    assert result.returncode == 0, result.stderr
