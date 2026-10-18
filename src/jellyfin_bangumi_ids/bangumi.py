"""Minimal Bangumi (bgm.tv) API client — only the endpoints this tool needs."""
from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .transport import HttpError, build_url, get_json, post_json, request

BASE = "https://api.bgm.tv"
UA = "jellyfin-bangumi-ids/1.0 (https://github.com/)"

# relation names used to walk a TV chain
SEQUEL = "续集"
PREQUEL = "前传"


class Bangumi:
    def __init__(self, base: str = BASE, sleep: float = 0.4, timeout: float = 25,
                 retries: int = 3):
        self.base = base.rstrip("/")
        self.sleep = sleep
        self.timeout = timeout
        self.retries = retries
        self._cache: Dict[str, Any] = {}

    # -- low level ---------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        return {"User-Agent": UA, "Accept": "application/json"}

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = build_url(self.base, path, params)
        if url in self._cache:
            return self._cache[url]
        data = get_json(url, headers=self._headers(), timeout=self.timeout, retries=self.retries)
        self._cache[url] = data
        time.sleep(self.sleep)
        return data

    # -- subjects ----------------------------------------------------------
    def subject(self, subject_id: int) -> Dict[str, Any]:
        return self.get("/v0/subjects/%d" % subject_id) or {}

    def relations(self, subject_id: int) -> List[Dict[str, Any]]:
        return self.get("/v0/subjects/%d/subjects" % subject_id) or []

    def search(self, keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
        """New search API first, legacy endpoint as a fallback."""
        payload = {"keyword": keyword, "filter": {"type": [2]}}
        try:
            raw = request(
                build_url(self.base, "/v0/search/subjects"),
                headers=dict(self._headers(), **{"Content-Type": "application/json"}),
                body=__import__("json").dumps(payload).encode(),
                method="POST", timeout=self.timeout, retries=self.retries,
            )
            data = __import__("json").loads(raw.decode())
            return (data.get("data") or [])[:limit]
        except (HttpError, ValueError):
            data = self.get("/search/subject/" + keyword, {"type": 2}) or {}
            return (data.get("list") or [])[:limit]

    def chain(self, subject_id: int) -> List[int]:
        """Ordered TV chain around ``subject_id`` (prequels first, sequels after)."""
        seen = {subject_id: True}
        order = [subject_id]

        def walk(current: int, direction: str) -> None:
            for rel in self.relations(current):
                if rel.get("type") != 2 or rel.get("relation") != direction:
                    continue
                nxt = rel.get("id")
                if not nxt or nxt in seen:
                    continue
                seen[nxt] = True
                if direction == SEQUEL:
                    order.append(nxt)
                    walk(nxt, SEQUEL)
                else:
                    order.insert(0, nxt)
                    walk(nxt, PREQUEL)

        walk(subject_id, SEQUEL)
        walk(subject_id, PREQUEL)
        return order

    # -- episodes ----------------------------------------------------------
    def episodes(self, subject_id: int, ep_type: int = 0) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        offset = 0
        while True:
            page = self.get("/v0/episodes", {
                "subject_id": subject_id, "type": ep_type, "limit": 100, "offset": offset,
            }) or {}
            batch = page.get("data") or []
            out.extend(batch)
            offset += len(batch)
            if len(batch) < 100 or (page.get("total") and offset >= page["total"]):
                break
        return out

    def episode(self, episode_id: int) -> Dict[str, Any]:
        return self.get("/v0/episodes/%d" % episode_id) or {}

    def episode_list(self, subject_id: int) -> List[Dict[str, Any]]:
        """Main episodes sorted by ``sort`` (SP excluded)."""
        eps = [e for e in self.episodes(subject_id, 0) if e.get("name") or e.get("name_cn")]
        eps.sort(key=lambda e: e.get("sort") or 0)
        return eps

    def pool(self, subjects: Sequence[int], types: Iterable[int] = (0,),
             include_special: bool = False, pattern: Optional[str] = None) -> List[Dict[str, Any]]:
        """Concatenate episodes of several subjects into one ordered pool."""
        import re

        regex = re.compile(pattern) if pattern else None
        out: List[Dict[str, Any]] = []
        for sid in subjects:
            for ep_type in (types if include_special else (0,)):
                for ep in self.episodes(sid, ep_type):
                    if regex and not regex.search((ep.get("name_cn") or "") + (ep.get("name") or "")):
                        continue
                    if not include_special and ep_type == 1 and not pattern:
                        continue
                    out.append(ep)
        out.sort(key=lambda e: (e.get("subject_id") or 0, e.get("sort") or 0))
        return out
