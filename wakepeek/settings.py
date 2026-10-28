"""Сколько дней журнала показывать."""

from __future__ import annotations

import json
import os
from pathlib import Path

_DIR = Path.home() / ".wakepeek"
_FILE = "settings.json"
CHOICES = (7, 14, 30, 90)
DEFAULT = 14


def load_days(directory: Path | None = None) -> int:
    path = (directory if directory is not None else _DIR) / _FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        days = int(raw.get("days", DEFAULT))
    except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
        return DEFAULT
    return days if days in CHOICES else DEFAULT


def save_days(days: int, directory: Path | None = None) -> None:
    if days not in CHOICES:
        days = DEFAULT
    folder = directory if directory is not None else _DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / _FILE
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"days": days}), encoding="utf-8")
    os.replace(tmp, path)
