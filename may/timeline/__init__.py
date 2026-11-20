"""The build timeline: which step types exist, how each is resolved, and running them in order."""
import logging
import os
import sys
from dataclasses import dataclass
from typing import Callable

from may.attribute_assignment import AttributeAssignmentError
from may.residence.household_distributor import HouseholdError
from may.utils import build_profile as bp
from may.utils import path_resolver as pr
from may.venue_child_creator import VenueChildCreator
from may.venue_distributor import distributor_from_yaml
from may.world import setup_households

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TimelineStep:
    """What the timeline needs to run one step type.

    ``expected_errors`` are failures the entry point reports in its own words, so
    they are logged without a traceback. ``config_hint`` is appended to the
    missing-``config:`` message where the step name does not say what to point at."""
    handler: Callable
    expected_errors: tuple = ()
    config_hint: str = ""


def _allocate_residences(world, config_path, world_config):
    """Run the allocation strategy at ``config_path``; attributes assigned by
    earlier steps are visible to it."""
    world.household_distributor = setup_households(
        world.geography, world.population, world.venues, world_config,
        strategy_file=config_path,
    )


def _assign_attributes(world, config_path, world_config):
    world.assign_attributes(config_path)


def _run_distributor(world, config_path, world_config):
    distributor_from_yaml(config_path).allocate(world)


def _create_venue_children(world, config_path, world_config):
    VenueChildCreator.from_yaml(config_path).create_children(world)


TIMELINE_STEPS = {
    "residence_allocation": TimelineStep(
        handler=_allocate_residences,
        expected_errors=(HouseholdError,),
        config_hint=" (e.g. configs/<scenario>/households/allocation_strategy.yaml)",
    ),
    "attribute": TimelineStep(
        handler=_assign_attributes,
        expected_errors=(AttributeAssignmentError,),
    ),
    "distributor": TimelineStep(handler=_run_distributor),
    "child_creator": TimelineStep(handler=_create_venue_children),
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


def run_timeline(world, world_config):
    """Run the world config's timeline steps in the order they are written."""
    timeline_config = world_config.get("timeline", {})
    if not (timeline_config.get("enabled", False) and timeline_config.get("steps")):
        # Every scenario drives all events through the timeline, including an
        # explicit `residence_allocation` step for households.
        raise ValueError(
            "No enabled timeline with steps found. The legacy "
            "attributes/venue_pipeline path has been removed — every config "
            "must define `timeline.enabled: true` with `timeline.steps`, "
            "including an explicit `residence_allocation` step when "
            "households are enabled."
        )

    logger.info("")
    logger.info("=" * 60)
    logger.info("SIMULATION TIMELINE")
    logger.info("=" * 60)

    # A households: block only wires data for the residence_allocation step, so
    # a block with no step is almost always a mistake. Raw types are read here so
    # an unknown type is still reported by resolution, below.
    step_types = [step.get("type") for step in timeline_config["steps"]]
    if world_config.get("households") and "residence_allocation" not in step_types:
        logger.warning(
            "a households: block is configured but the timeline has no "
            "'residence_allocation' step — households will NOT be allocated."
        )

    for step in timeline_config["steps"]:
        step_type, config_path = resolve_timeline_step(step)
        # Steps of one type are told apart by their config file, since a
        # timeline runs a dozen distributors through the same code path.
        with bp.stage(step_label(step_type, config_path), step_type, detail=config_path):
            logger.info("")
            logger.info(f"[{step_type.replace('_', ' ').upper()}] {config_path}")
            _run_step(TIMELINE_STEPS[step_type], step_type, config_path, world, world_config)


def _run_step(entry, step_type, config_path, world, world_config):
    """Run one step, exiting the build on failure. An expected error already
    says what went wrong, so only an unexpected one carries a traceback."""
    try:
        entry.handler(world, config_path, world_config)
    except entry.expected_errors as error:
        logger.error(f"Timeline step {step_type!r} failed for {config_path}: {error}")
        sys.exit(1)
    except Exception as error:
        logger.exception(f"Timeline step {step_type!r} failed for {config_path}: {error}")
        sys.exit(1)
