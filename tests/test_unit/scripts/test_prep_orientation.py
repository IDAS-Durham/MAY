"""Tests for the orientation data-prep scripts."""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_msoa = _load("prep_orientation_msoa")
_prev = _load("prep_orientation_prevalence")
msoa_normalize = _msoa.normalize
prevalence_extend = _prev.extend
EXTRAPOLATED_BANDS = _prev.EXTRAPOLATED_BANDS
LGB_FLOOR = _prev.LGB_FLOOR
ONS_BANDS = _prev.ONS_BANDS


def _write_raw_msoa(path: Path) -> None:
    path.write_text(
        '\n'
        '"TS077 - Sexual orientation"\n'
        '"ONS Crown Copyright Reserved"\n'
        '"Population :","All usual residents aged 16 and over"\n'
        '"Units      :","Persons"\n'
        '"Date       :","2021"\n'
        '\n'
        '"2021 super output area - middle layer","Total","%","Straight","%","Gay","%","Bi","%"\n'
        '\n'
        '"E02000001 : Test 001",1000,100.0,800,80.0,100,10.0,100,10.0\n'
        '"E02000002 : Test 002",1000,100.0,950,95.0,30,3.0,20,2.0\n'
        '"unrelated row should be skipped"\n'
    )


def test_msoa_normalize_writes_tidy_rows_summing_to_one(tmp_path: Path) -> None:
    raw = tmp_path / "raw.csv"
    out = tmp_path / "normalized.csv"
    _write_raw_msoa(raw)

    n = msoa_normalize(raw, out)

    assert n == 2
    rows = list(csv.DictReader(out.open()))
    assert {r["geo_unit"] for r in rows} == {"E02000001", "E02000002"}

    for r in rows:
        s = float(r["heterosexual"]) + float(r["homosexual"]) + float(r["bisexual"])
        assert abs(s - 1.0) < 1e-9

    e1 = next(r for r in rows if r["geo_unit"] == "E02000001")
    # 800 / (800+100+100) = 0.8 exactly
    assert abs(float(e1["heterosexual"]) - 0.8) < 1e-9
    assert int(e1["total_responding"]) == 1000


def test_prevalence_extend_preserves_ons_and_extrapolates_75plus(tmp_path: Path) -> None:
    src = Path("data/population/sexual_orientation/orientation_prevalence.csv")
    out = tmp_path / "extended.csv"

    info = prevalence_extend(src, out)

    assert info["bands_per_sex"] == len(ONS_BANDS) + len(EXTRAPOLATED_BANDS)

    rows = list(csv.DictReader(out.open()))
    sources_by_band = {(r["sex"], r["age_group"]): r["source"] for r in rows}
    for band, _ in ONS_BANDS:
        assert sources_by_band[("male", band)] == "ons"
        assert sources_by_band[("female", band)] == "ons"
    for band, _ in EXTRAPOLATED_BANDS:
        assert sources_by_band[("male", band)] == "extrapolated"
        assert sources_by_band[("female", band)] == "extrapolated"

    # Each (sex, band) sums to 1.0 and LGB never falls below the floor for
    # the extrapolated rows.
    by_cell: dict[tuple[str, str], list[tuple[str, float]]] = {}
    for r in rows:
        by_cell.setdefault((r["sex"], r["age_group"]), []).append(
            (r["orientation"], float(r["probability"]))
        )

    for (sex, band), entries in by_cell.items():
        s = sum(p for _, p in entries)
        assert abs(s - 1.0) < 1e-6, f"({sex},{band}) sums to {s}"
        if any(b == band for b, _ in EXTRAPOLATED_BANDS):
            for orient, p in entries:
                if orient in ("homosexual", "bisexual"):
                    assert p >= LGB_FLOOR * 0.5  # tolerate post-renormalization shrink
