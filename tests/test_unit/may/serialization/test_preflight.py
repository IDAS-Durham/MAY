"""
Contract tests for the schema comparison that runs before the world is built.

Reading one header per venue file is enough to tell which configured properties
name a column the data supplies. Running it at the start of a build puts that
answer in the log while there is still time to act on it.
"""

import pytest

from may.serialization.preflight import venue_property_gaps

VENUE_TYPES = {
    "company": {"filename": "companies.csv"},
    "school": {"filename": ["ew_schools.csv", "sct_schools.csv"]},
    "household": {"description": "built during the run, no file"},
}


@pytest.fixture
def venue_dir(tmp_path):
    (tmp_path / "companies.csv").write_text("geo_unit,industry_code,sizeband\nA,C,1\n")
    (tmp_path / "ew_schools.csv").write_text("geo_unit,NumberOfPupils\nA,10\n")
    (tmp_path / "sct_schools.csv").write_text("geo_unit,Gender\nB,Mixed\n")
    return str(tmp_path)


def schema(types):
    return {"venues": {"types": types}}


class TestVenuePropertyGaps:
    def test_a_column_the_files_carry_is_matched(self, venue_dir):
        gaps = venue_property_gaps(
            schema({"company": {"properties": ["industry_code"]}}), VENUE_TYPES, venue_dir
        )
        assert gaps == []

    def test_a_name_absent_from_the_headers_is_a_gap(self, venue_dir):
        gaps = venue_property_gaps(
            schema({"company": {"properties": ["work_sector"]}}), VENUE_TYPES, venue_dir
        )
        assert [(t, p) for t, p, _ in gaps] == [("company", "work_sector")]

    def test_gap_reports_the_columns_the_files_carry(self, venue_dir):
        gaps = venue_property_gaps(
            schema({"company": {"properties": ["work_sector"]}}), VENUE_TYPES, venue_dir
        )
        assert "industry_code" in gaps[0][2]

    def test_a_column_in_any_stacked_file_counts(self, venue_dir):
        """Nations arrive as separate files, and a column in any one of them
        counts as supplied."""
        gaps = venue_property_gaps(
            schema({"school": {"properties": ["Gender", "NumberOfPupils"]}}),
            VENUE_TYPES, venue_dir,
        )
        assert gaps == []

    def test_types_the_run_assembles_are_left_to_the_export(self, venue_dir):
        """The run assembles household venues, so their properties appear
        once the build reaches them."""
        gaps = venue_property_gaps(
            schema({"household": {"properties": ["capacity"]}}), VENUE_TYPES, venue_dir
        )
        assert gaps == []

    def test_absent_files_are_skipped(self, tmp_path):
        gaps = venue_property_gaps(
            schema({"company": {"properties": ["anything"]}}), VENUE_TYPES, str(tmp_path)
        )
        assert gaps == []

