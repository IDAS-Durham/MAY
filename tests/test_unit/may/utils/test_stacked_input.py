"""
Contract tests for the stacked CSV loader: a multi-file input either behaves
exactly like the equivalent single file or fails loudly with a message that
names the offending files, columns, or keys.
"""

import pandas as pd
import pytest

from may.utils.stacked_input import (
    StackedInputError,
    as_path_list,
    load_stacked_csv,
)


def _write(path, text):
    path.write_text(text)
    return str(path)


class TestAsPathList:
    def test_single_string_becomes_one_element_list(self):
        assert as_path_list("a.csv", "x") == ["a.csv"]

    def test_list_passes_through(self):
        assert as_path_list(["a.csv", "b.csv"], "x") == ["a.csv", "b.csv"]

    def test_empty_list_raises(self):
        with pytest.raises(StackedInputError, match="empty"):
            as_path_list([], "households.data_file")

    def test_non_string_entry_raises(self):
        with pytest.raises(StackedInputError, match="path string"):
            as_path_list(["a.csv", 3], "x")

    def test_non_path_value_raises(self):
        with pytest.raises(StackedInputError, match="expected a path"):
            as_path_list({"a": 1}, "x")


class TestLoadStackedCsv:
    def test_single_file_round_trips(self, tmp_path):
        p = _write(tmp_path / "a.csv", "geo_unit,x\nA,1\nB,2\n")
        df = load_stacked_csv([p], label="t", key_column="geo_unit")
        assert list(df["geo_unit"]) == ["A", "B"]

    def test_two_files_stack_in_order(self, tmp_path):
        p1 = _write(tmp_path / "a.csv", "geo_unit,x\nA,1\n")
        p2 = _write(tmp_path / "b.csv", "geo_unit,x\nB,2\n")
        df = load_stacked_csv([p1, p2], label="t", key_column="geo_unit")
        assert list(df["geo_unit"]) == ["A", "B"]

    def test_missing_file_raises_naming_it(self, tmp_path):
        p1 = _write(tmp_path / "a.csv", "geo_unit,x\nA,1\n")
        with pytest.raises(StackedInputError, match="nope.csv"):
            load_stacked_csv([p1, str(tmp_path / "nope.csv")], label="t")

    def test_column_order_normalized_to_first_file(self, tmp_path):
        p1 = _write(tmp_path / "a.csv", "geo_unit,x,y\nA,1,2\n")
        p2 = _write(tmp_path / "b.csv", "y,geo_unit,x\n4,B,3\n")
        df = load_stacked_csv([p1, p2], label="t", key_column="geo_unit")
        assert list(df.columns) == ["geo_unit", "x", "y"]
        assert df.iloc[1].tolist() == ["B", 3, 4]

    def test_strict_column_mismatch_names_both_files(self, tmp_path):
        p1 = _write(tmp_path / "a.csv", "geo_unit,x\nA,1\n")
        p2 = _write(tmp_path / "b.csv", "geo_unit,z\nB,2\n")
        with pytest.raises(StackedInputError) as exc:
            load_stacked_csv([p1, p2], label="t")
        assert "a.csv" in str(exc.value) and "b.csv" in str(exc.value)
        assert "z" in str(exc.value)

    def test_duplicate_key_within_file_raises(self, tmp_path):
        p = _write(tmp_path / "a.csv", "geo_unit,x\nA,1\nA,2\n")
        with pytest.raises(StackedInputError, match="repeats"):
            load_stacked_csv([p], label="t", key_column="geo_unit")

    def test_duplicate_key_across_files_names_both(self, tmp_path):
        p1 = _write(tmp_path / "a.csv", "geo_unit,x\nA,1\n")
        p2 = _write(tmp_path / "b.csv", "geo_unit,x\nA,9\n")
        with pytest.raises(StackedInputError) as exc:
            load_stacked_csv([p1, p2], label="t", key_column="geo_unit")
        assert "a.csv" in str(exc.value) and "b.csv" in str(exc.value)

    def test_positional_key_resolves_to_first_column(self, tmp_path):
        p1 = _write(tmp_path / "a.csv", "code,x\nA,1\n")
        p2 = _write(tmp_path / "b.csv", "code,x\nA,2\n")
        with pytest.raises(StackedInputError, match="already appear"):
            load_stacked_csv([p1, p2], label="t", key_column=0)

    def test_no_key_column_skips_uniqueness(self, tmp_path):
        p1 = _write(tmp_path / "a.csv", "geo_unit,x\nA,1\n")
        p2 = _write(tmp_path / "b.csv", "geo_unit,x\nA,2\n")
        df = load_stacked_csv([p1, p2], label="t")
        assert len(df) == 2

    def test_unknown_column_policy_raises(self, tmp_path):
        p = _write(tmp_path / "a.csv", "geo_unit,x\nA,1\n")
        with pytest.raises(StackedInputError, match="column_policy"):
            load_stacked_csv([p], label="t", column_policy="merge")


class TestUnionZeroFill:
    def test_union_fills_missing_columns_with_zero(self, tmp_path):
        p1 = _write(tmp_path / "a.csv", "geo_unit,p1,p2\nA,1,2\n")
        p2 = _write(tmp_path / "b.csv", "geo_unit,p1,p3\nB,3,4\n")
        df = load_stacked_csv(
            [p1, p2], label="t", key_column="geo_unit",
            column_policy="union_zero_fill",
        )
        assert list(df.columns) == ["geo_unit", "p1", "p2", "p3"]
        row_a = df[df["geo_unit"] == "A"].iloc[0]
        row_b = df[df["geo_unit"] == "B"].iloc[0]
        assert row_a["p3"] == 0 and row_a["p2"] == 2
        assert row_b["p2"] == 0 and row_b["p3"] == 4

    def test_union_warns_per_lacking_file(self, tmp_path, caplog):
        p1 = _write(tmp_path / "a.csv", "geo_unit,p1,p2\nA,1,2\n")
        p2 = _write(tmp_path / "b.csv", "geo_unit,p1,p3\nB,3,4\n")
        with caplog.at_level("WARNING", logger="stacked_input"):
            load_stacked_csv(
                [p1, p2], label="t", key_column="geo_unit",
                column_policy="union_zero_fill",
            )
        warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert any("a.csv" in m and "p3" in m for m in warnings)
        assert any("b.csv" in m and "p2" in m for m in warnings)

    def test_union_with_identical_columns_stays_silent(self, tmp_path, caplog):
        p1 = _write(tmp_path / "a.csv", "geo_unit,p1\nA,1\n")
        p2 = _write(tmp_path / "b.csv", "geo_unit,p1\nB,2\n")
        with caplog.at_level("WARNING", logger="stacked_input"):
            load_stacked_csv(
                [p1, p2], label="t", key_column="geo_unit",
                column_policy="union_zero_fill",
            )
        assert not [r for r in caplog.records if r.levelname == "WARNING"]

    def test_union_still_requires_key_in_every_file(self, tmp_path):
        p1 = _write(tmp_path / "a.csv", "geo_unit,p1\nA,1\n")
        p2 = _write(tmp_path / "b.csv", "code,p1\nB,2\n")
        with pytest.raises(StackedInputError, match="key"):
            load_stacked_csv(
                [p1, p2], label="t", key_column="geo_unit",
                column_policy="union_zero_fill",
            )

    def test_union_still_rejects_key_overlap(self, tmp_path):
        p1 = _write(tmp_path / "a.csv", "geo_unit,p1\nA,1\n")
        p2 = _write(tmp_path / "b.csv", "geo_unit,p2\nA,2\n")
        with pytest.raises(StackedInputError, match="already appear"):
            load_stacked_csv(
                [p1, p2], label="t", key_column="geo_unit",
                column_policy="union_zero_fill",
            )


class TestMixedValueTypes:
    """
    pandas infers dtypes per file, so one column can arrive as text from one
    file and as numbers from another. The stacked column then holds two Python
    types at once, and one output type would have to alter a value to store
    them together.
    """

    def test_text_and_int_in_one_column_raises(self, tmp_path):
        p1 = _write(tmp_path / "a.csv", "geo_unit,industry_code\nA,31-33\n")
        p2 = _write(tmp_path / "b.csv", "geo_unit,industry_code\nB,11\n")
        with pytest.raises(StackedInputError, match="more than one value type"):
            load_stacked_csv([p1, p2], label="company venues",
                             key_column="geo_unit")

    def test_message_names_column_files_and_both_types(self, tmp_path):
        p1 = _write(tmp_path / "a.csv", "geo_unit,industry_code\nA,31-33\n")
        p2 = _write(tmp_path / "b.csv", "geo_unit,industry_code\nB,11\n")
        with pytest.raises(StackedInputError) as excinfo:
            load_stacked_csv([p1, p2], label="company venues",
                             key_column="geo_unit")
        message = str(excinfo.value)
        assert "industry_code" in message
        assert "a.csv" in message and "b.csv" in message
        assert "'31-33'" in message and "11" in message

    def test_text_and_float_in_one_column_raises(self, tmp_path):
        p1 = _write(tmp_path / "a.csv", "geo_unit,size\nA,large\n")
        p2 = _write(tmp_path / "b.csv", "geo_unit,size\nB,1.5\n")
        with pytest.raises(StackedInputError, match="more than one value type"):
            load_stacked_csv([p1, p2], label="t", key_column="geo_unit")

    def test_int_and_float_stay_allowed(self, tmp_path):
        """numpy promotes these to one float column of Python floats."""
        p1 = _write(tmp_path / "a.csv", "geo_unit,pupils\nA,10\n")
        p2 = _write(tmp_path / "b.csv", "geo_unit,pupils\nB,12.5\n")
        df = load_stacked_csv([p1, p2], label="t", key_column="geo_unit")
        assert list(df["pupils"]) == [10.0, 12.5]

    def test_int_and_bool_stay_allowed(self, tmp_path):
        """Concatenating these gives an object column holding ints."""
        p1 = _write(tmp_path / "a.csv", "geo_unit,flag\nA,1\n")
        p2 = _write(tmp_path / "b.csv", "geo_unit,flag\nB,True\n")
        df = load_stacked_csv([p1, p2], label="t", key_column="geo_unit")
        assert len(df) == 2

    def test_text_column_beside_an_empty_one_stays_allowed(self, tmp_path):
        """An all-blank column contributes nulls, and the scan reads the
        values that remain."""
        p1 = _write(tmp_path / "a.csv", "geo_unit,name\nA,alpha\n")
        p2 = _write(tmp_path / "b.csv", "geo_unit,name\nB,\n")
        df = load_stacked_csv([p1, p2], label="t", key_column="geo_unit")
        assert list(df["name"])[0] == "alpha"

    def test_single_file_is_not_checked(self, tmp_path):
        """The comparison comes from differences between files, and a single
        file settles its own dtypes under whole-file inference."""
        p1 = _write(tmp_path / "a.csv", "geo_unit,industry_code\nA,31-33\nB,11\n")
        df = load_stacked_csv([p1], label="t", key_column="geo_unit")
        assert len(df) == 2

    def test_zero_filling_a_text_column_raises(self, tmp_path):
        """union_zero_fill writes int 0 into a text column the file omits,
        which is the same mix arriving by another route."""
        p1 = _write(tmp_path / "a.csv", "geo_unit,sector\nA,31-33\n")
        p2 = _write(tmp_path / "b.csv", "geo_unit\nB\n")
        with pytest.raises(StackedInputError, match="more than one value type"):
            load_stacked_csv([p1, p2], label="t", key_column="geo_unit",
                             column_policy="union_zero_fill")


class TestWholeFileTypeInference:
    """
    pandas infers a column's type per block by default, so a single large file
    can give one column two Python types on its own. The loader asks for
    whole-file inference, which settles each file on one type per column.
    """

    def test_low_memory_is_off_by_default(self, tmp_path, monkeypatch):
        seen = {}
        real = pd.read_csv

        def spy(path, **kwargs):
            seen.update(kwargs)
            return real(path, **kwargs)

        monkeypatch.setattr(pd, "read_csv", spy)
        p = _write(tmp_path / "a.csv", "geo_unit,x\nA,1\n")
        load_stacked_csv([p], label="t", key_column="geo_unit")
        assert seen.get("low_memory") is False

    def test_a_caller_can_still_override_it(self, tmp_path, monkeypatch):
        seen = {}
        real = pd.read_csv

        def spy(path, **kwargs):
            seen.update(kwargs)
            return real(path, **kwargs)

        monkeypatch.setattr(pd, "read_csv", spy)
        p = _write(tmp_path / "a.csv", "geo_unit,x\nA,1\n")
        load_stacked_csv([p], label="t", key_column="geo_unit", low_memory=True)
        assert seen.get("low_memory") is True

    def test_the_python_engine_is_left_alone(self, tmp_path, monkeypatch):
        """pandas accepts low_memory with the C engine, so the default is
        applied there and the python engine keeps its own kwargs."""
        seen = {}
        real = pd.read_csv

        def spy(path, **kwargs):
            seen.update(kwargs)
            return real(path, **kwargs)

        monkeypatch.setattr(pd, "read_csv", spy)
        p = _write(tmp_path / "a.csv", "geo_unit,x\nA,1\n")
        load_stacked_csv([p], label="t", key_column="geo_unit", engine="python")
        assert "low_memory" not in seen
