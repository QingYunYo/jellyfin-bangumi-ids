"""Read the Bangumi plugin's offline archive (jsonlines) instead of calling the API.

The plugin keeps a local copy under ``{JellyfinDataPath}/bangumi/archive``:
``subject.jsonlines``, ``episode.jsonlines``, ``character.jsonlines``,
``person.jsonlines``.  Streaming it is the difference between 40 minutes of
rate-limited API calls and a few seconds of I/O.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterator, Optional, Set

FILES = {
    "subject": "subject.jsonlines",
    "episode": "episode.jsonlines",
    "character": "character.jsonlines",
    "person": "person.jsonlines",
}


def pick(row: Dict[str, Any], *names: str) -> Any:
    """First present, non-empty value among ``names`` (tolerates key casing)."""
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def path_in(directory: str, kind: str) -> str:
    return os.path.join(directory, FILES[kind])


def available(directory: str) -> Dict[str, str]:
    """Map kind -> existing file path."""
    found = {}
    for kind in FILES:
        candidate = path_in(directory, kind)
        if os.path.isfile(candidate):
            found[kind] = candidate
    return found


def iter_rows(path: str) -> Iterator[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def collect_episodes(path: str, wanted: Set[int]) -> Dict[int, Dict[str, Any]]:
    """Stream ``episode.jsonlines`` and keep only the ids asked for."""
    found: Dict[int, Dict[str, Any]] = {}
    for row in iter_rows(path):
        rid = to_int(pick(row, "id", "Id"))
        if rid is None or rid not in wanted:
            continue
        found[rid] = {
            "id": rid,
            "subject_id": to_int(pick(row, "subject_id", "subjectId", "SubjectId")),
            "sort": pick(row, "sort", "Sort"),
            "type": to_int(pick(row, "type", "Type")),
            "name": pick(row, "name", "Name") or "",
            "name_cn": pick(row, "name_cn", "nameCn", "NameCn") or "",
        }
    return found


def collect_subjects(path: str, wanted: Set[int]) -> Dict[int, Dict[str, Any]]:
    found: Dict[int, Dict[str, Any]] = {}
    for row in iter_rows(path):
        rid = to_int(pick(row, "id", "Id"))
        if rid is None or (wanted and rid not in wanted):
            continue
        found[rid] = {
            "id": rid,
            "name": pick(row, "name", "Name") or "",
            "name_cn": pick(row, "name_cn", "nameCn", "NameCn") or "",
            "type": to_int(pick(row, "type", "Type")),
            "eps": to_int(pick(row, "eps", "Eps")),
        }
    return found
