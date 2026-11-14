"""A tiny persistent settings file for values that rarely change.

``url`` / ``api_key`` / ``archive`` / ``archive_root`` / ``lang`` are stored.  The API key is
only written when the user asks for it (``jbmid setup`` / ``jbmid config --api-key``),
the file is mode 0600, and ``--no-save-key`` keeps it out entirely.  The file is a
plain JSON object, so users can edit it without this tool.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict

APP = "jellyfin-bangumi-ids"
FILENAME = "config.json"
KEYS = ("url", "api_key", "archive", "archive_root", "lang", "ipv4")

LAST_ERROR: list = []


def mask(value: str) -> str:
    """Short, non-reversible hint for the UI: never print a full key."""
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * 8 + value[-4:]


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
    """Read the file; a missing file is normal, a broken one is reported once."""
    path = config_path()
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return {}
    except OSError as exc:
        _warn(path, exc)
        return {}
    except ValueError as exc:
        _warn(path, exc)
        return {}
    if not isinstance(raw, dict):
        _warn(path, ValueError("top level is not an object"))
        return {}
    out = {}
    for key in KEYS:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def _warn(path: str, exc: Exception) -> None:
    """Report a broken file instead of silently pretending it is empty."""
    LAST_ERROR[:] = ["%s (%s)" % (path, exc)]
    print("config: %s (%s)" % (path, exc), file=sys.stderr)


def save(values: Dict[str, str]) -> str:
    path = config_path()
    data = load()
    if LAST_ERROR and os.path.exists(path) and not os.path.exists(path + ".bad"):
        # Never throw away a file the user may have hand-edited.
        try:
            os.replace(path, path + ".bad")
        except OSError:
            pass
    LAST_ERROR[:] = []
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
    if not os.path.exists(config_path()):
        return config_path()
    return save({key: "" for key in keys})
