import pytest

from may.utils.age_bands import parse_age_band


@pytest.mark.parametrize(
    ("label", "expected"),
    [("16-24", (16, 24)), ("65+", (65, 200)), ("65-+", (65, 200))],
)
def test_parse_age_band(label, expected):
    assert parse_age_band(label) == expected


def test_parse_age_band_permissive_malformed_label():
    assert parse_age_band("not-an-age-band") is None


def test_parse_age_band_strict_malformed_label():
    with pytest.raises(ValueError, match="Unrecognized age band"):
        parse_age_band("not-an-age-band", strict=True)
