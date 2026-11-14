"""A tiny persistent settings file for values that rarely change.

Only ``archive`` / ``archive_root`` / ``url`` are stored: the API key stays in
``JF_API_KEY`` so it never ends up on disk by accident.  The file is a plain
JSON object, so users can edit it without this tool.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict

APP = "jellyfin-bangumi-ids"
FILENAME = "config.json"
KEYS = ("archive", "archive_root", "url")


def config_dir() -> str:
    explicit = os.environ.get("JBMID_CONFIG_DIR")
    if explicit:
        return os.path.expanduser(explicit)
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, APP)


def config_path() -> str:
    return os.path.join(config_dir(), FILENAME)


def load() -> Dict[str, str]:
    try:
        with open(config_path(), encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key in KEYS:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def save(values: Dict[str, str]) -> str:
    path = config_path()
    data = load()
    for key, value in values.items():
        if key not in KEYS:
            continue
        if value:
            data[key] = str(value)
        else:
            data.pop(key, None)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    if os.name != "nt":
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def unset(*keys: str) -> str:
    data = load()
    for key in keys:
        data.pop(key, None)
    return save({key: "" for key in keys})
