"""
Shared vocabulary for probability gates.

A probability gate thins a priority-allocation group by a per-geo-unit rate read
from one or more CSV files. The distributor loads the files and the filtering
manager reads the result, so the cache identity and the error type live here
rather than in either of them.
"""

from may.utils.stacked_input import as_path_list

# Retired probability_config keys. `default` filled probabilities for geo units
# absent from the file; probability files now have to cover the loaded geography,
# so a leftover key would sit in a config looking load-bearing while doing nothing.
RETIRED_PROBABILITY_KEYS = ("default",)

# The lookup attribute whose values are SGU names, and so the only one whose
# coverage can be checked against the geography.
GEO_UNIT_LOOKUP_ATTRIBUTE = "geographical_unit.name"


class ProbabilityConfigError(Exception):
    """A probability_config block is unusable: bad keys, files or columns."""


def probability_cache_key(prob_config):
    """
    Cache identity of a probability lookup: its files plus the column read.

    Built from the raw config values so the distributor (which loads) and the
    filtering manager (which reads) cannot drift apart.
    """
    paths = as_path_list(prob_config.get('file_path'), "probability_config.file_path")
    return (tuple(paths), prob_config.get('probability_column'))
