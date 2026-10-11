"""JSON serialization utilities for converting rich Python objects into JSON-safe primitives."""

from datetime import date, datetime
from pathlib import Path
from typing import Any


def make_json_serializable(value: Any) -> Any:
    """Recursively convert non-JSON-serializable objects (date, datetime, Path, etc.) into JSON-safe primitives.

    Converts date and datetime objects into standard ISO-8601 strings.
    Safely traverses nested dictionaries and lists/tuples/sets.
    Preserves all original dictionary keys and content.
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): make_json_serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [make_json_serializable(item) for item in value]
    return value
