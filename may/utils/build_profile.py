"""
Build profiling for MAY world creation.

Records what each stage of a world build costs in wall-clock, resident memory,
and world size. Stages nest two levels, with pipeline stages and timeline steps
at the top and the named steps of an allocation strategy under the stage that
runs them.

The recorder is a module-level singleton, because the allocation strategy is
reached through several layers of engine code that have no reason to carry a
profiler argument. Where no build has been started, as in unit tests and
programmatic callers, every entry point here is an inert context manager.

Timings always run. They cost microseconds, and a build that records nothing
leaves no evidence of what it cost. Function-level cProfile data is opt-in,
since cProfile both slows the build and distorts the timings it reports.
"""

import json
import logging
import os
import platform
import random
import sys
import time
from collections import Counter

import psutil

logger = logging.getLogger("build_profile")

# The schema of build_profile.json. Bump when a reader could misread an older
# file rather than merely miss a field.
SCHEMA_VERSION = 1

PROFILE_JSON_NAME = "build_profile.json"
PROFILE_STATS_NAME = "build_profile.stats"

# Per-person coverage is measured on a fixed sample rather than by scanning the
# whole population, so profiling overhead stays flat as worlds grow.
SAMPLE_SIZE = 20_000
SAMPLE_SEED = 8_675_309

_recorder = None


class _Stage:
    """One measured stage and its children."""

    __slots__ = (
        "name", "kind", "detail", "children",
        "wall_seconds", "rss_before", "rss_after",
        "counters_before", "counters_after", "coverage_after",
        "status", "error", "_t0",
    )

    def __init__(self, name, kind, detail):
        self.name = name
        self.kind = kind
        self.detail = detail
        self.children = []
        self.wall_seconds = None
        self.rss_before = None
        self.rss_after = None
        self.counters_before = {}
        self.counters_after = {}
        self.coverage_after = None
        self.status = "running"
        self.error = None
        self._t0 = None

    def to_dict(self):
        out = {
            "name": self.name,
            "kind": self.kind,
            "status": self.status,
            "wall_seconds": self.wall_seconds,
            "rss_before_bytes": self.rss_before,
            "rss_after_bytes": self.rss_after,
            "counters_before": self.counters_before,
            "counters_after": self.counters_after,
        }
        if self.detail:
            out["detail"] = self.detail
        if self.error:
            out["error"] = self.error
        if self.coverage_after is not None:
            out["coverage_after"] = self.coverage_after
        if self.children:
            out["children"] = [c.to_dict() for c in self.children]
        return out


class _NullStage:
    """What instrumented engine code gets when no build is being recorded."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


_NULL_STAGE = _NullStage()


class _StageContext:
    def __init__(self, recorder, stage):
        self._recorder = recorder
        self._stage = stage

    def __enter__(self):
        return self._stage

    def __exit__(self, exc_type, exc, tb):
        self._recorder._close(self._stage, exc_type)
        return False


class BuildProfileRecorder:
    """Collects stage measurements for a single world build."""

    def __init__(self, output_dir, config_path, cprofile_enabled):
        self.output_dir = output_dir
        self.config_path = config_path
        self.cprofile_enabled = cprofile_enabled
        self.stages = []
        self.complete = False
        self._stack = []
        self._process = psutil.Process(os.getpid())
        self._t0 = time.time()
        self._rss_start = self._rss()
        self._rss_peak = self._rss_start
        self._world = None
        self._geography = None
        self._population = None
        self._venues = None
        self._sample_indices = None
        self._sample_population_size = None

    # -- measurement sources ------------------------------------------------

    def _rss(self):
        rss = self._process.memory_info().rss
        if rss > getattr(self, "_rss_peak", 0):
            self._rss_peak = rss
        return rss

    def bind(self, geography=None, population=None, venues=None, world=None):
        """Attach the objects whose size the counters describe.

        Geography, venues and population are bound as they are built, so the
        stages that build them can report what they produced. The world arrives
        later and is kept for the household distributor, which it gains part way
        through the timeline.
        """
        if geography is not None:
            self._geography = geography
        if population is not None:
            self._population = population
        if venues is not None:
            self._venues = venues
        if world is not None:
            self._world = world

    def _counters(self):
        """Exact world-size counters. Every one of these is O(1) or O(#types)."""
        counters = {}
        if self._geography is not None:
            counters["geo_units"] = len(self._geography.get_all_units())
        if self._population is not None:
            counters["people"] = len(self._population.people)
        if self._venues is not None:
            by_type = {
                venue_type: len(by_id)
                for venue_type, by_id in self._venues.venues_by_type_and_id.items()
            }
            counters["venues"] = sum(by_type.values())
            counters["venues_by_type"] = by_type

        distributor = getattr(self._world, "household_distributor", None)
        if distributor is not None:
            counters["people_allocated"] = len(distributor.allocated_people)
        return counters

    def _coverage(self):
        """What share of people carry each activity and each property key.

        One fixed sample serves every stage, so the numbers stay comparable
        down the run. Activity and property names come from the people
        themselves, since the engine's vocabulary is config-driven and nothing
        here should assume a particular one.
        """
        if self._population is None:
            return None

        people = self._population.people
        total = len(people)
        if total == 0:
            return None

        if self._sample_population_size != total:
            self._sample_population_size = total
            if total <= SAMPLE_SIZE:
                self._sample_indices = None
            else:
                # A private RNG, so the build's own seeded draws from the
                # global numpy and random state stay untouched.
                self._sample_indices = random.Random(SAMPLE_SEED).sample(
                    range(total), SAMPLE_SIZE
                )

        if self._sample_indices is None:
            sample = people
        else:
            sample = [people[i] for i in self._sample_indices]

        n = len(sample)
        activities = Counter()
        properties = Counter()
        for person in sample:
            for activity, by_venue_type in person.activity_map.items():
                for venue_type in by_venue_type:
                    activities[f"{activity}.{venue_type}"] += 1
            properties.update(person.properties.keys())

        return {
            "sample_size": n,
            "population": total,
            "activities": {k: v / n for k, v in sorted(activities.items())},
            "properties": {k: v / n for k, v in sorted(properties.items())},
        }

    # -- stage recording ----------------------------------------------------

    def stage(self, name, kind, detail=None):
        stage = _Stage(name, kind, detail)
        stage.counters_before = self._counters()
        stage.rss_before = self._rss()
        stage._t0 = time.perf_counter()

        if self._stack:
            self._stack[-1].children.append(stage)
        else:
            self.stages.append(stage)
        self._stack.append(stage)
        return _StageContext(self, stage)

    def _close(self, stage, exc_type):
        stage.wall_seconds = time.perf_counter() - stage._t0
        stage.rss_after = self._rss()
        stage.counters_after = self._counters()
        stage.coverage_after = self._coverage()
        if exc_type is None:
            stage.status = "ok"
        else:
            stage.status = "failed"
            stage.error = exc_type.__name__

        while self._stack and self._stack[-1] is not stage:
            self._stack.pop()
        if self._stack:
            self._stack.pop()

        # Rewritten after every stage so a build that is killed or crashes
        # still leaves a readable profile of everything that finished.
        self.write()

    # -- output -------------------------------------------------------------

    def to_dict(self):
        return {
            "schema": SCHEMA_VERSION,
            "config": self.config_path,
            "complete": self.complete,
            "cprofile": self.cprofile_enabled,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "started_unix": self._t0,
            "wall_seconds": time.time() - self._t0,
            "rss_start_bytes": self._rss_start,
            "rss_peak_bytes": self._rss_peak,
            "stages": [s.to_dict() for s in self.stages],
        }

    @property
    def json_path(self):
        return os.path.join(self.output_dir, PROFILE_JSON_NAME)

    @property
    def stats_path(self):
        return os.path.join(self.output_dir, PROFILE_STATS_NAME)

    def write(self):
        os.makedirs(self.output_dir, exist_ok=True)
        with open(self.json_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    def finish(self):
        self.complete = True
        self.write()

    def log_summary(self, log):
        """The cost of this build, at the end of the build's own log."""
        flat = [(s.name, s.kind, s.wall_seconds or 0.0) for s in self.stages]
        flat.sort(key=lambda row: row[2], reverse=True)
        total = time.time() - self._t0

        log.info("")
        log.info("=" * 60)
        log.info("BUILD COST")
        log.info("=" * 60)
        log.info(f"Total build time: {format_seconds(total)}")
        log.info(f"Peak memory: {format_bytes(self._rss_peak)}")
        log.info("Most expensive stages:")
        for name, kind, seconds in flat[:5]:
            share = 100 * seconds / total if total else 0.0
            log.info(f"  {format_seconds(seconds):>10}  {share:5.1f}%  {name} ({kind})")
        log.info(f"Build profile: {self.json_path}")
        if self.cprofile_enabled:
            log.info(f"Function profile: {self.stats_path}")
        else:
            log.info("Run with --profile for function-level detail.")
        log.info("=" * 60)


# -- module-level entry points ----------------------------------------------


def start(output_dir, config_path, cprofile_enabled):
    global _recorder
    _recorder = BuildProfileRecorder(output_dir, config_path, cprofile_enabled)
    return _recorder


def active():
    return _recorder


def bind(geography=None, population=None, venues=None, world=None):
    if _recorder is not None:
        _recorder.bind(
            geography=geography, population=population, venues=venues, world=world
        )


def stage(name, kind, detail=None):
    """Measure a stage. Inert when no build is being recorded."""
    if _recorder is None:
        return _NULL_STAGE
    return _recorder.stage(name, kind, detail)


def finish():
    if _recorder is not None:
        _recorder.finish()


def format_seconds(seconds):
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.2f} s"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {rest:.0f}s"
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours}h {minutes}m"


def format_bytes(n):
    if n is None:
        return "n/a"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(value) < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{value:.0f} B"
        value /= 1024
