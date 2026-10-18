"""Auto mode: find the Bangumi subject by title, align by episode names, fall back to order."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .match import align, is_special, name_match, similarity
from .scan import log

OK, REVIEW = "ok", "review"
SEASON_MARK_RE = re.compile(r"(第\s*[0-9一二三四五六七八九十]+\s*[季期部]|Season\s*\d+|S\d{1,2}\b)", re.IGNORECASE)


def candidates(bgm, name: str, limit: int = 10) -> List[Dict[str, Any]]:
    try:
        hits = bgm.search(name, limit)
    except Exception as exc:
        log("  search failed: %s" % exc)
        return []
    return [h for h in hits if name_match(name, h.get("name_cn") or "") or name_match(name, h.get("name") or "")]


def scan_auto(jf, bgm, library: Optional[str] = None, only: Optional[str] = None,
              threshold: float = 0.45, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for series in jf.all_series(library_name=library, limit=limit):
        if only and only not in (series.get("Name") or ""):
            continue
        local, skipped = [], 0
        for season in jf.seasons(series["Id"]):
            if (season.get("IndexNumber") or 0) < 1:
                skipped += len(jf.season_episodes(season["Id"]))
                continue
            for ep in jf.season_episodes(season["Id"]):
                if is_special(ep.get("Name") or ""):
                    skipped += 1
                    continue
                local.append(ep)
        entry: Dict[str, Any] = {"series": series.get("Name"), "series_id": series["Id"],
                                 "episodes": [], "status": REVIEW, "reason": "",
                                 "skipped_specials": skipped, "coverage": 0.0, "mean_sim": 0.0,
                                 "subject": None, "method": None}
        if not local:
            entry["reason"] = "no episodes"
            results.append(entry)
            continue
        best = None
        for cand in candidates(bgm, series.get("Name") or ""):
            chain = bgm.chain(int(cand["id"]))
            pool = [ep for sid in chain for ep in bgm.episode_list(sid)]
            if not pool:
                continue
            pairs = [(i, i) for i in range(min(len(local), len(pool)))] if len(pool) == len(local) else \
                align([e.get("Name") or "" for e in local], pool, threshold)
            cov = len(pairs) / float(len(local))
            mean = (sum(similarity(local[i].get("Name") or "",
                                   pool[j].get("name_cn") or pool[j].get("name") or "")
                        for i, j in pairs) / len(pairs)) if pairs else 0.0
            score = cov * 0.6 + mean * 0.4
            if best is None or score > best[0]:
                best = (score, cand, chain, pool, pairs, cov, mean)
        if not best:
            entry["reason"] = "no matching Bangumi subject"
            results.append(entry)
            continue
        score, cand, chain, pool, pairs, cov, mean = best
        entry.update({"subject": int(cand["id"]), "chain": chain, "coverage": cov, "mean_sim": mean,
                      "method": "name"})
        if cov >= 0.8 and mean >= 0.5:
            entry["status"] = OK
        elif len(pool) == len(local) and SEASON_MARK_RE.search(series.get("Name") or cand.get("name_cn") or ""):
            pairs = [(i, i) for i in range(len(local))]
            entry.update({"status": OK, "method": "order-low-confidence",
                          "coverage": 1.0, "reason": "sequential mapping, low confidence"})
        else:
            entry["reason"] = "coverage %.0f%%, mean sim %.2f" % (cov * 100, mean)
        for i, j in pairs:
            ep, bgm_ep = local[i], pool[j]
            entry["episodes"].append({"item_id": ep["Id"], "season": ep.get("ParentIndexNumber"),
                                      "index": ep.get("IndexNumber"), "name": ep.get("Name"),
                                      "bgm_id": str(bgm_ep["id"]),
                                      "bgm_name": bgm_ep.get("name_cn") or bgm_ep.get("name"),
                                      "sim": round(similarity(ep.get("Name") or "",
                                                              bgm_ep.get("name_cn") or bgm_ep.get("name") or ""), 3)})
        log("[%s] %s subject=%s method=%s cov=%.0f%% sim=%.2f -> %d eps" % (
            entry["status"], entry["series"], entry["subject"], entry["method"],
            entry["coverage"] * 100, entry["mean_sim"], len(entry["episodes"])))
        results.append(entry)
    return results
