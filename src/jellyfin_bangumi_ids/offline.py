"""Offline data source: the Bangumi plugin's local archive, indexed with SQLite.

The plugin keeps ``subject.jsonlines`` / ``episode.jsonlines`` under
``{DataPath}/bangumi/archive``.  Reading them costs no API quota, but the files
are big (a full archive is ~1.3 GB), so the first run builds a small SQLite
index next to the user's cache directory; later runs answer per-subject queries
in well under a millisecond.

``OfflineBangumi`` exposes the same small interface as :class:`Bangumi` and
falls back to the API for anything the archive cannot answer (relations,
title search, ids newer than the archive snapshot).
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from typing import Any, Dict, List, Optional

from .bangumi import Bangumi

ARCHIVE_ENV = "JBMID_ARCHIVE"
CACHE_ENV = "JBMID_CACHE"
VERSION = "2"


def _cache_root() -> str:
    """A writable directory for the index; falls back to the system temp dir."""
    candidates = []
    if os.environ.get(CACHE_ENV):
        candidates.append(os.path.expanduser(os.environ[CACHE_ENV]))
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    candidates.append(os.path.join(base, "jellyfin-bangumi-ids"))
    candidates.append(os.path.join(tempfile.gettempdir(), "jellyfin-bangumi-ids"))
    for path in candidates:
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, ".write-test")
            with open(probe, "w") as fh:
                fh.write("ok")
            os.remove(probe)
            return path
        except OSError:
            continue
    return os.path.join(tempfile.gettempdir(), "jellyfin-bangumi-ids")


def looks_like_archive(path: Optional[str]) -> bool:
    if not path:
        return False
    try:
        return os.path.isfile(os.path.join(path, "episode.jsonlines")) and os.access(
            os.path.join(path, "episode.jsonlines"), os.R_OK)
    except OSError:
        return False


def _candidates_from_jellyfin(jf) -> List[str]:
    try:
        info = jf.get("/System/Info") or {}
    except Exception:
        return []
    roots = []
    for key in ("ProgramDataPath", "InternalMetadataPath", "DataPath", "MetadataPath"):
        raw = info.get(key)
        if not raw:
            continue
        # InternalMetadataPath is <data>/metadata; DataPath is <data>
        if key == "ProgramDataPath":
            # Jellyfin keeps everything below the program data dir; the plugin
            # writes <ProgramDataPath>/data/bangumi/archive.
            roots.append(raw.rstrip("/"))
        elif key == "InternalMetadataPath":
            roots.append(os.path.dirname(raw.rstrip("/")))
        else:
            roots.append(raw.rstrip("/"))
    out = []
    for root in roots:
        out.extend([os.path.join(root, "data", "bangumi", "archive"),
                    os.path.join(root, "bangumi", "archive")])
    return out


def find_archive(jf=None, explicit: Optional[str] = None) -> Optional[str]:
    """Explicit flag → env var → Jellyfin's own data path → nothing."""
    for path in (explicit, os.environ.get(ARCHIVE_ENV)):
        if looks_like_archive(path):
            return os.path.abspath(os.path.expanduser(path))
        if path:
            return None  # user pointed somewhere wrong: do not guess instead
    if jf is not None:
        for path in _candidates_from_jellyfin(jf):
            if looks_like_archive(path):
                return os.path.abspath(path)
    return None


class ArchiveIndex:
    """SQLite index over the plugin archive; built once per archive version."""

    def __init__(self, archive_dir: str, cache_dir: Optional[str] = None, verbose: bool = True):
        self.dir = os.path.abspath(archive_dir)
        self.cache_dir = cache_dir or _cache_root()
        self.verbose = verbose
        self.db_path = self._db_path()
        self._conn: Optional[sqlite3.Connection] = None

    # -- cache layout ------------------------------------------------------
    def _stamp(self) -> str:
        parts = []
        for name in ("subject.jsonlines", "episode.jsonlines"):
            path = os.path.join(self.dir, name)
            try:
                st = os.stat(path)
                parts.append("%s-%d-%d" % (name.split(".")[0], st.st_size, int(st.st_mtime)))
            except OSError:
                parts.append(name + "-missing")
        return "_".join(parts)

    def _db_path(self) -> str:
        safe = "".join(ch if ch.isalnum() else "-" for ch in os.path.basename(self.dir) or "archive")
        digest = hashlib.sha1(self._stamp().encode()).hexdigest()[:12]
        return os.path.join(self.cache_dir, "archive-%s-%s.sqlite" % (safe, digest))

    # -- build -------------------------------------------------------------
    def _say(self, msg: str) -> None:
        if self.verbose:
            print(msg, file=sys.stderr)

    def build(self) -> None:
        os.makedirs(self.cache_dir, exist_ok=True)
        tmp = self.db_path + ".tmp"
        for path in (tmp, tmp + "-journal"):
            if os.path.exists(path):
                os.remove(path)
        conn = sqlite3.connect(tmp)
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("CREATE TABLE subject(id INTEGER PRIMARY KEY, type INT, name TEXT, name_cn TEXT, date TEXT)")
        conn.execute("CREATE TABLE episode(id INTEGER PRIMARY KEY, sid INT, sort INT, type INT, name TEXT, name_cn TEXT)")
        conn.execute("CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT)")
        conn.execute("CREATE TABLE relation(sid INTEGER PRIMARY KEY, body TEXT)")
        conn.execute("CREATE TABLE search(kw TEXT PRIMARY KEY, body TEXT)")
        self._say("offline index: building from %s (one time, ~20 s)" % self.dir)
        for table, name in (("subject", "subject.jsonlines"), ("episode", "episode.jsonlines")):
            path = os.path.join(self.dir, name)
            batch = []
            with open(path, encoding="utf-8", buffering=1 << 20) as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if table == "subject":
                        batch.append((row.get("id"), row.get("type"), row.get("name"),
                                      row.get("name_cn"), row.get("date")))
                    else:
                        batch.append((row.get("id"), row.get("subject_id"), row.get("sort"),
                                      row.get("type"), row.get("name"), row.get("name_cn")))
                    if len(batch) >= 100000:
                        conn.executemany("INSERT OR IGNORE INTO %s VALUES(%s)" % (
                            table, ",".join("?" * len(batch[0]))), batch)
                        batch = []
            if batch:
                conn.executemany("INSERT OR IGNORE INTO %s VALUES(%s)" % (
                    table, ",".join("?" * len(batch[0]))), batch)
            conn.commit()
        conn.execute("CREATE INDEX i_ep_sid ON episode(sid, type, sort)")
        conn.execute("INSERT INTO meta VALUES('version', ?)", (VERSION,))
        conn.commit()
        conn.close()
        os.replace(tmp, self.db_path)

    def _open(self) -> sqlite3.Connection:
        if self._conn is None:
            fresh = not os.path.exists(self.db_path)
            if fresh:
                self.build()
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute("SELECT v FROM meta WHERE k='version'").fetchone()
            except sqlite3.DatabaseError:
                row = None
            if not row or row[0] != VERSION:
                conn.close()
                os.remove(self.db_path)
                self.build()
                conn = sqlite3.connect(self.db_path)
            self._conn = conn
        return self._conn

    # -- queries -----------------------------------------------------------
    def subject(self, sid: int) -> Optional[Dict[str, Any]]:
        row = self._open().execute(
            "SELECT id, type, name, name_cn, date FROM subject WHERE id=?", (sid,)).fetchone()
        if not row:
            return None
        return {"id": row[0], "type": row[1], "name": row[2], "name_cn": row[3], "date": row[4]}

    def has_subject(self, sid: int) -> bool:
        return self._open().execute("SELECT 1 FROM subject WHERE id=?", (sid,)).fetchone() is not None

    def episodes(self, sid: int, ep_type: int = 0) -> List[Dict[str, Any]]:
        rows = self._open().execute(
            "SELECT id, sort, type, name, name_cn FROM episode WHERE sid=? AND type=? ORDER BY sort",
            (sid, ep_type)).fetchall()
        return [{"id": r[0], "subject_id": sid, "sort": r[1], "type": r[2],
                 "name": r[3], "name_cn": r[4]} for r in rows]

    def episode(self, eid: int) -> Optional[Dict[str, Any]]:
        row = self._open().execute(
            "SELECT id, sid, sort, type, name, name_cn FROM episode WHERE id=?", (eid,)).fetchone()
        if not row:
            return None
        return {"id": row[0], "subject_id": row[1], "sort": row[2], "type": row[3],
                "name": row[4], "name_cn": row[5]}

    # -- api memo (relations / search are not in the archive) --------------
    def cached_relation(self, sid: int) -> Optional[List[Dict[str, Any]]]:
        row = self._open().execute("SELECT body FROM relation WHERE sid=?", (sid,)).fetchone()
        return json.loads(row[0]) if row else None

    def store_relation(self, sid: int, body: List[Dict[str, Any]]) -> None:
        conn = self._open()
        conn.execute("INSERT OR REPLACE INTO relation VALUES(?, ?)", (sid, json.dumps(body)))
        conn.commit()

    def cached_search(self, keyword: str) -> Optional[List[Dict[str, Any]]]:
        row = self._open().execute("SELECT body FROM search WHERE kw=?", (keyword,)).fetchone()
        return json.loads(row[0]) if row else None

    def store_search(self, keyword: str, body: List[Dict[str, Any]]) -> None:
        conn = self._open()
        conn.execute("INSERT OR REPLACE INTO search VALUES(?, ?)", (keyword, json.dumps(body)))
        conn.commit()

    def counts(self) -> Dict[str, int]:
        conn = self._open()
        return {"subjects": conn.execute("SELECT count(*) FROM subject").fetchone()[0],
                "episodes": conn.execute("SELECT count(*) FROM episode").fetchone()[0]}


class OfflineBangumi:
    """Drop-in replacement for :class:`Bangumi` backed by the local archive.

    Anything the archive cannot answer (relations between subjects, free-text
    search, ids added after the archive snapshot) is delegated to the real API,
    so behaviour never degrades below the online client.
    """

    def __init__(self, index: ArchiveIndex, api: Bangumi, label: Optional[str] = None):
        self.index = index
        self.api = api
        self.label = label or index.dir
        self.offline_hits = 0
        self.api_hits = 0

    # -- subjects ----------------------------------------------------------
    def subject(self, subject_id: int) -> Dict[str, Any]:
        row = self.index.subject(int(subject_id))
        if row is not None:
            self.offline_hits += 1
            return row
        self.api_hits += 1
        return self.api.subject(subject_id)

    def relations(self, subject_id: int) -> List[Dict[str, Any]]:
        cached = self.index.cached_relation(int(subject_id))
        if cached is not None:
            self.offline_hits += 1
            return cached
        self.api_hits += 1
        rels = self.api.relations(subject_id)
        self.index.store_relation(int(subject_id), rels)
        return rels

    def search(self, keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
        cached = self.index.cached_search(keyword)
        if cached is not None:
            self.offline_hits += 1
            return cached[:limit]
        self.api_hits += 1
        hits = self.api.search(keyword, limit)
        self.index.store_search(keyword, hits)
        return hits

    def chain(self, subject_id: int) -> List[int]:
        return Bangumi.chain(self, subject_id)

    # -- episodes ----------------------------------------------------------
    def episodes(self, subject_id: int, ep_type: int = 0) -> List[Dict[str, Any]]:
        if self.index.has_subject(int(subject_id)):
            rows = self.index.episodes(int(subject_id), ep_type)
            if rows:
                self.offline_hits += 1
                return rows
        self.api_hits += 1
        return self.api.episodes(subject_id, ep_type)

    def episode(self, episode_id: int) -> Dict[str, Any]:
        row = self.index.episode(int(episode_id))
        if row is not None:
            self.offline_hits += 1
            return row
        self.api_hits += 1
        return self.api.episode(episode_id)

    def episode_list(self, subject_id: int) -> List[Dict[str, Any]]:
        eps = [e for e in self.episodes(subject_id, 0) if e.get("name") or e.get("name_cn")]
        eps.sort(key=lambda e: e.get("sort") or 0)
        return eps

    def describe(self) -> str:
        return "offline archive %s (%s)" % (
            self.label, ", ".join("%s=%d" % kv for kv in sorted(self.index.counts().items())))

def archive_hint(jf) -> Optional[str]:
    """First archive path Jellyfin points at, whether or not we can read it."""
    for path in _candidates_from_jellyfin(jf):
        return os.path.abspath(path)
    return None
