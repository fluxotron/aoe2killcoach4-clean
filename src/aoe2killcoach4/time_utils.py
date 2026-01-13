"""Utilities for parsing time values."""
from __future__ import annotations

from typing import Any


def coerce_seconds(value: Any) -> int:
    """Coerce common replay time formats into whole seconds."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return 0
        if stripped.replace(".", "", 1).isdigit():
            return int(float(stripped))
        parts = stripped.split(":")
        if len(parts) in {2, 3}:
            hours = 0
            if len(parts) == 3:
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = float(parts[2])
            else:
                minutes = int(parts[0])
                seconds = float(parts[1])
            total = hours * 3600 + minutes * 60 + seconds
            return int(total)
    raise ValueError(f"Unsupported time format: {value!r}")
