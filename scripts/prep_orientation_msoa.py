"""Normalize the ONS TS077 sexual-orientation MSOA file into a tidy CSV.

Input:  data/population/sexual_orientation/orientation_by_msoa.csv  (raw ONS layout)
Output: data/population/sexual_orientation/orientation_by_msoa_normalized.csv

The raw file has a few title rows, then one row per MSOA with the geo code embedded
in a string like "E02002483 : Hartlepool 001". Counts for "Other" and "Prefer not to
say" are not modeled, so we renormalize the three modeled categories to sum to 1.0.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = REPO_ROOT / "data/population/sexual_orientation/orientation_by_msoa.csv"
OUTPUT_PATH = REPO_ROOT / "data/population/sexual_orientation/orientation_by_msoa_normalized.csv"

GEO_CODE_RE = re.compile(r"(E\d{8})")


def _parse_int(s: str) -> int:
    return int(s.replace(",", "").strip())


def normalize(input_path: Path = INPUT_PATH, output_path: Path = OUTPUT_PATH) -> int:
    rows_out = []
    with input_path.open(newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            m = GEO_CODE_RE.match(row[0].strip().strip('"'))
            if not m:
                continue
            geo_unit = m.group(1)
            total = _parse_int(row[1])
            hetero = _parse_int(row[3])
            homo = _parse_int(row[5])
            bi = _parse_int(row[7])
            modeled = hetero + homo + bi
            if modeled <= 0:
                continue
            rows_out.append({
                "geo_unit": geo_unit,
                "total_responding": modeled,
                "heterosexual": hetero / modeled,
                "homosexual": homo / modeled,
                "bisexual": bi / modeled,
            })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["geo_unit", "total_responding", "heterosexual", "homosexual", "bisexual"],
        )
        writer.writeheader()
        for r in rows_out:
            writer.writerow({
                "geo_unit": r["geo_unit"],
                "total_responding": r["total_responding"],
                "heterosexual": f"{r['heterosexual']:.9f}",
                "homosexual": f"{r['homosexual']:.9f}",
                "bisexual": f"{r['bisexual']:.9f}",
            })

    return len(rows_out)


if __name__ == "__main__":
    n = normalize()
    print(f"Wrote {n} MSOAs to {OUTPUT_PATH.relative_to(REPO_ROOT)}")
