"""Auto mode: find the Bangumi subject by title, align by episode names, fall back to order."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .match import align, is_special, name_match, similarity
from .scan import log, pick_anchor
from .season_align import plan_segments

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
        groups: List[List[Dict[str, Any]]] = []
        skipped = 0
        for season in jf.seasons(series["Id"]):
            if (season.get("IndexNumber") or 0) < 1:
                skipped += len(jf.season_episodes(season["Id"]))
                continue
            kept: List[Dict[str, Any]] = []
            for ep in jf.season_episodes(season["Id"]):
                if is_special(ep.get("Name") or ""):
                    skipped += 1
                    continue
                kept.append(ep)
            groups.append(kept)
        local = [ep for group in groups for ep in group]
        entry: Dict[str, Any] = {"series": series.get("Name"), "series_id": series["Id"],
                                 "episodes": [], "status": REVIEW, "reason": "",
                                 "skipped_specials": skipped, "coverage": 0.0, "mean_sim": 0.0,
                                 "subject": None, "method": None}
        if not local:
            entry["reason"] = "no episodes"
            results.append(entry)
            continue
        cands = candidates(bgm, series.get("Name") or "")
        # An id the library already stores is a better lead than the title: the
        # Bangumi name may be a translation the search never returns.
        stored, _how, _notes = pick_anchor(bgm, jf, series, allow_search=False)
        if stored and all(int(c.get("id") or 0) != int(stored) for c in cands):
            cands.insert(0, {"id": stored, "name_cn": series.get("Name"),
                             "name": series.get("Name")})
        best: Optional[Dict[str, Any]] = None
        for cand in cands:
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
            segments, method, spans = [(local, pool, pairs)], "name", []
            # A library that splits a franchise its own way (two seasons over a three
            # subject chain, a movie folded in, one season kept short) never lines up
            # as one flat pool. Ask the season planner before giving up on it -- and
            # also whenever the flat pass left an episode behind, because a mapping
            # that covers every episode is the better answer.
            if cov < 1.0 or mean < 0.5:
                plan = plan_segments(groups, chain, bgm, threshold)
                if plan is not None and any(kind != "order" for kind in plan.kinds):
                    plan_mean = sum(similarity(group[i].get("Name") or "",
                                               seg_pool[j].get("name_cn")
                                               or seg_pool[j].get("name") or "")
                                    for group, seg_pool, seg_pairs in plan.segments
                                    for i, j in seg_pairs) / float(len(local))
                    plan_score = 0.6 + plan_mean * 0.4
                    if plan_score > score:
                        score, cov, mean = plan_score, 1.0, plan_mean
                        segments, method, spans = plan.segments, "season-map", plan.spans
            if best is None or score > best["score"]:
                best = {"score": score, "cand": cand, "chain": chain, "segments": segments,
                        "coverage": cov, "mean": mean, "method": method, "spans": spans,
                        "pool": len(pool)}
        if not best:
            entry["reason"] = "no matching Bangumi subject"
            results.append(entry)
            continue
        cand, segments = best["cand"], best["segments"]
        cov, mean, method = best["coverage"], best["mean"], best["method"]
        entry.update({"subject": int(cand["id"]), "chain": best["chain"],
                      "coverage": cov, "mean_sim": mean, "method": method})
        if method == "season-map":
            entry.update({"status": OK, "reason": "season map %s" % " ".join(
                "+".join(str(sid) for sid in span) for span in best["spans"])})
        elif cov >= 0.8 and mean >= 0.5:
            entry["status"] = OK
        elif best["pool"] == len(local) and \
                SEASON_MARK_RE.search(series.get("Name") or cand.get("name_cn") or ""):
            segments = [(local, segments[0][1], [(i, i) for i in range(len(local))])]
            entry.update({"status": OK, "method": "order-low-confidence",
                          "coverage": 1.0, "reason": "sequential mapping, low confidence"})
        else:
            entry["reason"] = "coverage %.0f%%, mean sim %.2f" % (cov * 100, mean)
        for group, seg_pool, seg_pairs in segments:
            for i, j in seg_pairs:
                ep, bgm_ep = group[i], seg_pool[j]
                entry["episodes"].append({
                    "item_id": ep["Id"], "season": ep.get("ParentIndexNumber"),
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
