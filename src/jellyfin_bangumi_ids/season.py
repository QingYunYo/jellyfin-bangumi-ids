"""Season-map mode: you say which Bangumi subjects belong to which local season."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .match import align, is_special, similarity
from .scan import log

OK, REVIEW = "ok", "review"


def build_pool(bgm, rule: Dict[str, Any]) -> List[Dict[str, Any]]:
    subjects = rule.get("subjects") or []
    include_special = bool(rule.get("sp"))
    pattern = rule.get("filter")
    regex = re.compile(pattern) if pattern else None
    pool: List[Dict[str, Any]] = []
    for sid in subjects:
        for ep_type in ((0, 1) if include_special else (0,)):
            for ep in bgm.episodes(int(sid), ep_type):
                text = (ep.get("name_cn") or "") + (ep.get("name") or "")
                if regex and not regex.search(text):
                    continue
                pool.append(ep)
    pool.sort(key=lambda e: ((e.get("subject_id") or 0), (e.get("sort") or 0)))
    return pool


def scan_seasons(jf, bgm, mapping: Dict[str, Dict[str, Any]],
                 threshold: float = 0.45) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for series_name, seasons in mapping.items():
        series = jf.find_series(series_name)
        for key, rule in sorted(seasons.items(), key=lambda kv: int(kv[0])):
            season = [s for s in jf.seasons(series["Id"]) if (s.get("IndexNumber") or 0) == int(key)]
            if not season:
                results.append({"series": series_name, "season": int(key), "status": REVIEW,
                                "reason": "season %s not found" % key, "episodes": []})
                continue
            local = [e for e in jf.season_episodes(season[0]["Id"])
                     if not is_special(e.get("Name") or "")]
            pool = build_pool(bgm, rule)
            entry: Dict[str, Any] = {"series": series_name, "series_id": series["Id"],
                                     "season": int(key), "episodes": [], "status": REVIEW,
                                     "reason": "", "coverage": 0.0, "mean_sim": 0.0}
            if not local or not pool:
                entry["reason"] = "empty local or pool"
                results.append(entry)
                continue
            pairs: List[Tuple[int, int]] = []
            if len(local) == len(pool):
                pairs = [(i, i) for i in range(len(local))]
            else:
                pairs = align([e.get("Name") or "" for e in local], pool, threshold)
            entry["coverage"] = len(pairs) / float(len(local))
            entry["mean_sim"] = (sum(similarity(local[i].get("Name") or "",
                                                pool[j].get("name_cn") or pool[j].get("name") or "")
                                     for i, j in pairs) / len(pairs)) if pairs else 0.0
            if entry["coverage"] >= 0.99:
                entry["status"] = OK
            else:
                entry["reason"] = "coverage %.0f%%, mean sim %.2f (local %d / pool %d)" % (
                    entry["coverage"] * 100, entry["mean_sim"], len(local), len(pool))
            for i, j in pairs:
                ep, bgm_ep = local[i], pool[j]
                entry["episodes"].append({
                    "item_id": ep["Id"], "season": int(key), "index": ep.get("IndexNumber"),
                    "name": ep.get("Name"), "bgm_id": str(bgm_ep["id"]),
                    "bgm_name": bgm_ep.get("name_cn") or bgm_ep.get("name"),
                    "sim": round(similarity(ep.get("Name") or "",
                                            bgm_ep.get("name_cn") or bgm_ep.get("name") or ""), 3),
                })
            results.append(entry)
            log("[%s S%s] %s %d/%d eps, mean sim %.2f" % (
                series_name, key, entry["status"], len(entry["episodes"]), len(local),
                entry["mean_sim"]))
    return results


def load_mapping(path: str) -> Dict[str, Dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise SystemExit("season map must be an object: {series: {season: rule}}")
    return data
