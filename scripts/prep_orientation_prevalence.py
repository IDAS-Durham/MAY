"""Extend the national orientation-prevalence table to cover ages 75+.

The ONS source stops at the 65-74 band. We fit a log-odds linear trend on the six
existing band midpoints (per sex x orientation), extrapolate to 75-84 / 85-94 / 95-99,
floor LGB shares to avoid pathological zeros, and renormalize within each (sex, band).

Input:  data/population/sexual_orientation/orientation_prevalence.csv
Output: data/population/sexual_orientation/orientation_prevalence_extended.csv
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = REPO_ROOT / "data/population/sexual_orientation/orientation_prevalence.csv"
OUTPUT_PATH = REPO_ROOT / "data/population/sexual_orientation/orientation_prevalence_extended.csv"

ORIENTATIONS = ["heterosexual", "homosexual", "bisexual"]
SEXES = ["male", "female"]

ONS_BANDS = [
    ("16-24", 20.0),
    ("25-34", 30.0),
    ("35-44", 40.0),
    ("45-54", 50.0),
    ("55-64", 60.0),
    ("65-74", 70.0),
]
EXTRAPOLATED_BANDS = [
    ("75-84", 80.0),
    ("85-94", 90.0),
    ("95-99", 97.0),
]

LGB_FLOOR = 0.0005


def _logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _linfit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    slope = num / den if den != 0 else 0.0
    intercept = my - slope * mx
    return slope, intercept


def extend(input_path: Path = INPUT_PATH, output_path: Path = OUTPUT_PATH) -> dict:
    raw: dict[tuple[str, str, str], float] = {}
    with input_path.open() as f:
        for row in csv.DictReader(f):
            sex = row["sex"].strip()
            orient = row["orientation"].strip()
            band = row["age_group"].strip()
            raw[(sex, orient, band)] = float(row["probability"])

    rows_out: list[dict] = []

    for sex in SEXES:
        # 1) Pass through ONS bands as-is.
        for band, _mid in ONS_BANDS:
            for orient in ORIENTATIONS:
                rows_out.append({
                    "sex": sex,
                    "orientation": orient,
                    "age_group": band,
                    "probability": raw[(sex, orient, band)],
                    "source": "ons",
                })

        # 2) Fit log-odds trend per orientation on ONS bands; extrapolate.
        slopes_intercepts: dict[str, tuple[float, float]] = {}
        for orient in ORIENTATIONS:
            xs = [mid for _b, mid in ONS_BANDS]
            ys = [_logit(raw[(sex, orient, b)]) for b, _ in ONS_BANDS]
            slopes_intercepts[orient] = _linfit(xs, ys)

        for band, mid in EXTRAPOLATED_BANDS:
            extrapolated: dict[str, float] = {}
            for orient in ORIENTATIONS:
                slope, intercept = slopes_intercepts[orient]
                extrapolated[orient] = _sigmoid(intercept + slope * mid)

            for orient in ("homosexual", "bisexual"):
                if extrapolated[orient] < LGB_FLOOR:
                    extrapolated[orient] = LGB_FLOOR

            total = sum(extrapolated.values())
            for orient in ORIENTATIONS:
                rows_out.append({
                    "sex": sex,
                    "orientation": orient,
                    "age_group": band,
                    "probability": extrapolated[orient] / total,
                    "source": "extrapolated",
                })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["sex", "orientation", "age_group", "probability", "source"])
        writer.writeheader()
        for r in rows_out:
            writer.writerow({
                "sex": r["sex"],
                "orientation": r["orientation"],
                "age_group": r["age_group"],
                "probability": f"{r['probability']:.9f}",
                "source": r["source"],
            })

    return {"rows": len(rows_out), "bands_per_sex": len(ONS_BANDS) + len(EXTRAPOLATED_BANDS)}


if __name__ == "__main__":
    info = extend()
    print(f"Wrote {info['rows']} rows ({info['bands_per_sex']} bands x {len(SEXES)} sexes x {len(ORIENTATIONS)} orientations) to {OUTPUT_PATH.relative_to(REPO_ROOT)}")
