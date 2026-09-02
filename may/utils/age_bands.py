"""Helpers for parsing configured age bands."""

from typing import Optional, Tuple

OPEN_BAND_MAX = 200


def parse_age_band(label: str, *, strict: bool = False) -> Optional[Tuple[int, int]]:
    """Parse ``16-24``, ``65+`` or ``65-+`` into inclusive bounds."""
    try:
        if not isinstance(label, str):
            raise ValueError
        if label.endswith("+") and "-" not in label:
            return int(label[:-1]), OPEN_BAND_MAX
        parts = label.split("-")
        if len(parts) != 2:
            raise ValueError
        low = int(parts[0])
        high = OPEN_BAND_MAX if parts[1] == "+" else int(parts[1])
        return low, high
    except (TypeError, ValueError):
        if strict:
            raise ValueError(f"Unrecognized age band: {label!r}") from None
        return None
