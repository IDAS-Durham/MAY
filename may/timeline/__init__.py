"""The build timeline: which step types exist and how each one is resolved."""
import os
from dataclasses import dataclass
from typing import Callable

from may.attribute_assignment import AttributeAssignmentError
from may.residence.household_distributor import HouseholdError
from may.utils import path_resolver as pr


@dataclass(frozen=True)
class TimelineStep:
    """What the timeline needs to run one step type.

    ``expected_errors`` are failures the entry point reports in its own words, so
    they are logged without a traceback. ``config_hint`` is appended to the
    missing-``config:`` message where the step name does not say what to point at."""
    handler: Callable
    expected_errors: tuple = ()
    config_hint: str = ""


def _handler_not_wired(world, config_path, world_config):
    raise NotImplementedError("Timeline handlers are not wired yet.")


TIMELINE_STEPS = {
    "residence_allocation": TimelineStep(
        handler=_handler_not_wired,
        expected_errors=(HouseholdError,),
        config_hint=" (e.g. configs/<scenario>/households/allocation_strategy.yaml)",
    ),
    "attribute": TimelineStep(
        handler=_handler_not_wired,
        expected_errors=(AttributeAssignmentError,),
    ),
    "distributor": TimelineStep(handler=_handler_not_wired),
    "child_creator": TimelineStep(handler=_handler_not_wired),
}


def require_config_path(owner, block, hint=""):
    """Resolve a `config:` pointer, refusing to invent one that is not written.

    A default here points every scenario at one scenario's file, and the loader then
    reports a missing file the author never named."""
    if not block.get("config"):
        raise ValueError(f"{owner} must set `config:` to a YAML file{hint}.")
    return pr.resolve(block["config"])


def resolve_timeline_step(step):
    """Validate one timeline step, returning its type and resolved config path."""
    step_type = step.get("type")
    if step_type not in TIMELINE_STEPS:
        raise ValueError(
            f"Unknown timeline step type {step_type!r}; expected one of "
            f"{sorted(TIMELINE_STEPS)}."
        )
    return step_type, require_config_path(
        f"A `{step_type}` timeline step", step, TIMELINE_STEPS[step_type].config_hint
    )


def step_label(step_type, step_config):
    """Name a timeline step after the config file it runs, so twelve
    distributors read as twelve stages rather than one."""
    if not step_config:
        return step_type
    return f"{step_type}:{os.path.splitext(os.path.basename(step_config))[0]}"
