"""Minimal Jellyfin REST client."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .transport import build_url, get_json, request

BANGUMI_PLUGIN_GUID = "41b59f1b-a6cf-474a-b416-785379cbd856"


class Jellyfin:
    def __init__(self, url: str, api_key: str, timeout: float = 20):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._uid: Optional[str] = None

    # -- plumbing ----------------------------------------------------------
    def _headers(self, json_body: bool = False) -> Dict[str, str]:
        headers = {
            "Authorization": 'MediaBrowser Token="%s"' % self.api_key,
            "X-Emby-Token": self.api_key,
            "Accept": "application/json",
        }
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return get_json(build_url(self.url, path, params), headers=self._headers(),
                        timeout=self.timeout)

    def post(self, path: str, payload: Any) -> Any:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        raw = request(build_url(self.url, path), headers=self._headers(True), body=body,
                      method="POST", timeout=self.timeout)
        if not raw:
            return None
        try:
            return json.loads(raw.decode())
        except ValueError:
            return raw.decode("utf-8", "replace")

    # -- library -----------------------------------------------------------
    def libraries(self) -> Dict[str, str]:
        data = self.get("/Library/MediaFolders") or {}
        return {f["Name"]: f["Id"] for f in data.get("Items", [])}

    def library_id(self, name: str) -> Optional[str]:
        """Resolve a library name case-insensitively, then by unambiguous substring."""
        libs = self.libraries()
        if name in libs:
            return libs[name]
        low = name.strip().lower()
        for lib_name, lib_id in libs.items():
            if lib_name.strip().lower() == low:
                return lib_id
        partial = [n for n in libs if low in n.lower()]
        if len(partial) == 1:
            return libs[partial[0]]
        available = ", ".join(sorted(libs)) or "(none)"
        if not partial:
            raise SystemExit("unknown library: %s (available: %s)" % (name, available))
        raise SystemExit("ambiguous library %r: %s" % (name, ", ".join(sorted(partial))))

    def all_series(self, parent: Optional[str] = None, limit: Optional[int] = None,
                   library_name: Optional[str] = None) -> List[Dict[str, Any]]:
        if library_name and not parent:
            parent = self.library_id(library_name)
        out: List[Dict[str, Any]] = []
        start = 0
        while True:
            params = {
                "IncludeItemTypes": "Series", "Recursive": "true", "Fields": "ProviderIds,Path,OriginalTitle",
                "Limit": 200, "StartIndex": start,
            }
            if parent:
                params["ParentId"] = parent
            page = self.get("/Items", params) or {}
            batch = page.get("Items") or []
            out.extend(batch)
            start += len(batch)
            if not batch or len(batch) < 200 or (limit and len(out) >= limit):
                break
        return out[:limit] if limit else out

    def seasons(self, series_id: str) -> List[Dict[str, Any]]:
        data = self.get("/Shows/%s/Seasons" % series_id, {"Fields": "ProviderIds"}) or {}
        return sorted(data.get("Items", []), key=lambda s: s.get("IndexNumber") or 0)

    def season_episodes(self, season_id: str) -> List[Dict[str, Any]]:
        """Episodes of one season; /Items by ParentId works for both Jellyfin 10 and 12."""
        out: List[Dict[str, Any]] = []
        start = 0
        while True:
            page = self.get("/Items", {
                "ParentId": season_id, "IncludeItemTypes": "Episode", "Recursive": "true",
                "Fields": "ProviderIds", "SortBy": "IndexNumber", "Limit": 200,
                "StartIndex": start,
            }) or {}
            batch = page.get("Items") or []
            out.extend(batch)
            start += len(batch)
            if not batch or len(batch) < 200:
                break
        return sorted(out, key=lambda e: e.get("IndexNumber") or 0)

    def episodes(self, series_id: str) -> List[Dict[str, Any]]:
        data = self.get("/Shows/%s/Episodes" % series_id, {"Fields": "ProviderIds"}) or {}
        return sorted(data.get("Items", []), key=lambda e: (e.get("ParentIndexNumber") or 0,
                                                            e.get("IndexNumber") or 0))

    def find_series(self, name: str, library_name: Optional[str] = None) -> Dict[str, Any]:
        parent = self.library_id(library_name) if library_name else None
        exact = [s for s in self.all_series(parent=parent) if s["Name"] == name]
        if len(exact) > 1:
            raise SystemExit("ambiguous series name %r (%d matches)" % (name, len(exact)))
        if exact:
            return exact[0]
        loose = [s for s in self.all_series(parent=parent) if name in s["Name"] or s["Name"] in name]
        if len(loose) == 1:
            return loose[0]
        raise SystemExit("series not found: %s%s" % (
            name, " (candidates: %s)" % ", ".join(x["Name"] for x in loose) if loose else ""))

    # -- items -------------------------------------------------------------
    def admin_user_id(self) -> str:
        """Item lookups need a userId when using an API key (no bound user)."""
        if self._uid:
            return self._uid
        users = self.get("/Users") or []
        admins = [u for u in users if (u.get("Policy") or {}).get("IsAdministrator")]
        if not admins:
            raise SystemExit("no administrator user found on this Jellyfin")
        self._uid = admins[0]["Id"]
        return self._uid

    def item(self, item_id: str) -> Dict[str, Any]:
        return self.get("/Items/%s" % item_id, {"userId": self.admin_user_id(),
                                                "Fields": "ProviderIds,Path"})

    def set_provider_id(self, item_id: str, provider: str, value: Optional[str]) -> Dict[str, Any]:
        """GET the whole DTO, touch only one provider id, POST it back."""
        dto = self.item(item_id)
        before = dict(dto.get("ProviderIds") or {})
        ids = dict(before)
        if value is None:
            ids.pop(provider, None)
        else:
            ids[provider] = str(value)
        dto["ProviderIds"] = ids
        self.post("/Items/%s" % item_id, dto)
        after = dict((self.item(item_id).get("ProviderIds") or {}))
        collateral = {k: (before.get(k), after.get(k)) for k in set(before) | set(after)
                      if k != provider and before.get(k) != after.get(k)}
        return {"ok": after.get(provider) == (None if value is None else str(value)),
                "before": before.get(provider), "after": after.get(provider),
                "collateral": collateral}

    # -- plugin configuration ---------------------------------------------
    def plugin_configuration(self) -> Dict[str, Any]:
        return self.get("/Plugins/%s/Configuration" % BANGUMI_PLUGIN_GUID) or {}

    def patch_plugin_configuration(self, **values: Any) -> Dict[str, Any]:
        current = self.plugin_configuration()
        current.update(values)
        self.post("/Plugins/%s/Configuration" % BANGUMI_PLUGIN_GUID, current)
        return self.plugin_configuration()
