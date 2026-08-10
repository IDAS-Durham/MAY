"""
Contract tests for the typed HDF5 property columns.

The writer gives each configured property one column of one type, taken from
the first value it finds, and casts the rest to match. Where a value would fail
or change under that cast, the writer records it and the export reports it,
which puts the detail in front of whoever runs a build that has already
finished.
"""

import logging

import h5py
import numpy as np
import pytest

from may.serialization.property_types import (
    PropertyTypeError,
    output_kind,
    value_problem,
)
from may.serialization.world_serializer import WorldSerializer


class FakeObject:
    def __init__(self, value):
        self.properties = {} if value is None else {"x": value}


class FakePerson:
    def __init__(self, person_id):
        self.id = person_id


@pytest.fixture
def writer():
    """A serializer carrying the state property writing reads."""
    probe = WorldSerializer.__new__(WorldSerializer)
    probe.compression_settings = {"compression": None, "compression_level": None}
    probe._property_problems = []
    probe._absent_properties = []
    return probe


def write(writer, tmp_path, values):
    """
    Run one property column through the writer.

    Returns (problems, absent, dataset_written).
    """
    objects = [FakeObject(v) for v in values]
    with h5py.File(tmp_path / "probe.h5", "w") as handle:
        group = handle.create_group("g")
        writer._write_property_array(group, "x", objects, owner="test")
        written = "x" in group
    return writer._property_problems, writer._absent_properties, written


class TestOutputKind:
    def test_bool_maps_to_a_bool_column(self):
        """bool subclasses int, so the bool test runs first."""
        assert output_kind(True) == "bool"
        assert output_kind(1) == "int"

    def test_text_and_lists_map_to_text(self):
        assert output_kind("a") == "str"
        assert output_kind([1, 2]) == "str"

    def test_numpy_int_maps_to_text(self):
        """numpy scalars carry their own types, so a numpy value maps to
        text and the text column then rejects it."""
        assert not isinstance(np.int64(5), int)
        assert output_kind(np.int64(5)) == "str"


class TestValueProblem:
    @pytest.mark.parametrize("kind,value", [
        ("int", 5),
        ("int", -(2 ** 31)),
        ("int", 2 ** 31 - 1),
        ("float", 1.5),
        ("float", 5),
        ("float", float("nan")),
        ("str", "a"),
        ("bool", False),
    ])
    def test_values_that_fit(self, kind, value):
        assert value_problem(kind, value) is None

    @pytest.mark.parametrize("kind,value", [
        ("int", "31-33"),
        ("int", 1.9),
        ("int", 2 ** 31),
        ("float", "big"),
        ("float", 1e300),
        ("str", 5),
        ("str", np.int64(5)),
        ("bool", 7),
    ])
    def test_values_that_fail_or_change(self, kind, value):
        assert value_problem(kind, value) is not None


class TestColumnsWhoseValuesFailOrChange:
    @pytest.mark.parametrize("values", [
        pytest.param([5, "31-33"], id="int_then_text"),
        pytest.param(["A", 5], id="text_then_int"),
        pytest.param([5, 1.9], id="int_then_float_would_truncate"),
        pytest.param([5, 2 ** 40], id="above_int32"),
        pytest.param([1.5, 1e300], id="overflows_float32"),
        pytest.param([np.int64(5)], id="numpy_int"),
        pytest.param([np.bool_(True)], id="numpy_bool"),
        pytest.param([True, 7], id="bool_then_int"),
        pytest.param([5, [1, 2]], id="int_then_list"),
    ])
    def test_recorded_and_column_dropped(self, writer, tmp_path, values):
        problems, _, written = write(writer, tmp_path, values)
        assert len(problems) == 1
        assert not written, "the column is dropped once a value fails"

    def test_a_list_of_objects_is_recorded(self, writer, tmp_path):
        """Sets have their members reduced to ids; a list is encoded as it
        stands, so its contents have to be JSON-representable."""
        problems, _, written = write(writer, tmp_path, [[FakePerson(1)]])
        assert "JSON" in problems[0]
        assert not written

    def test_message_names_owner_property_and_value(self, writer, tmp_path):
        problems, _, _ = write(writer, tmp_path, [5, "31-33"])
        assert "test" in problems[0]
        assert "'x'" in problems[0]
        assert "31-33" in problems[0]


class TestColumnsThatWriteAsGiven:
    @pytest.mark.parametrize("values", [
        pytest.param([1, 2, 3], id="ints"),
        pytest.param(["a", "b"], id="text"),
        pytest.param([1.5, 2.5], id="floats"),
        pytest.param([True, False], id="bools"),
        pytest.param([1.5, 5], id="int_widens_into_float_column"),
        pytest.param(["a", None, "b"], id="text_with_gaps"),
        pytest.param([[1, 2], [3]], id="lists_become_json"),
        pytest.param([1, 2 ** 31 - 1], id="int32_boundary"),
    ])
    def test_written_as_given(self, writer, tmp_path, values):
        problems, absent, written = write(writer, tmp_path, values)
        assert problems == [] and absent == []
        assert written

    def test_a_set_of_people_becomes_their_ids(self, writer, tmp_path):
        problems, _, written = write(writer, tmp_path, [{FakePerson(7)}])
        assert problems == []
        assert written


class TestPropertyNothingProduces:
    def test_is_warned_and_the_export_continues(self, writer, tmp_path, caplog):
        """A cut-down world, or a run with a stage switched off, leaves some
        properties unset, and the export carries on and writes the rest."""
        with caplog.at_level(logging.WARNING, logger="world_serializer"):
            problems, absent, written = write(writer, tmp_path, [None, None])
        assert problems == []
        assert absent == ["test property 'x'"]
        assert not written
        assert any("omits this column" in r.message for r in caplog.records)
