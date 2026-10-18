"""Scan a library and decide which Bangumi episode ids every episode should get."""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from .match import align, fill_gaps, is_special, name_match, similarity

OK, REVIEW = "ok", "review"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def series_anchor(bgm, series: Dict[str, Any]) -> Tuple[Optional[int], str]:
    """Existing Bangumi id on the series is the cheapest, most reliable anchor."""
    pid = (series.get("ProviderIds") or {}).get("Bangumi")
    if pid and str(pid).isdigit():
        return int(pid), "series-id"
    return None, "none"


def season_anchor(bgm, jf, series: Dict[str, Any]) -> Tuple[Optional[int], str]:
    for season in jf.seasons(series["Id"]):
        pid = (season.get("ProviderIds") or {}).get("Bangumi")
        if pid and str(pid).isdigit():
            return int(pid), "season-id"
    return None, "none"


def search_anchor(bgm, series: Dict[str, Any]) -> Tuple[Optional[int], str, List[str]]:
    """Search bgm by title; refuse when the title does not really match."""
    name = series.get("Name") or ""
    year = series.get("ProductionYear")
    notes: List[str] = []
    try:
        hits = bgm.search(name, 10)
    except Exception as exc:  # network hiccup must not kill the whole scan
        return None, "search-failed", [str(exc)]
    best = None
    for hit in hits:
        cn = hit.get("name_cn") or ""
        jp = hit.get("name") or ""
        if name_match(name, cn) or name_match(name, jp):
            best = hit
            break
        if year and str(hit.get("date") or "").startswith(str(year)):
            notes.append("year-hit:%s" % (cn or jp))
    if best:
        return int(best["id"]), "search", notes
    return None, "search-mismatch", notes


def collect_local_episodes(jf, series: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int]:
    """Main-season episodes in order; specials are dropped and counted."""
    out: List[Dict[str, Any]] = []
    skipped = 0
    for season in jf.seasons(series["Id"]):
        if (season.get("IndexNumber") or 0) < 1:
            skipped += len(jf.season_episodes(season["Id"]))
            continue
        for ep in jf.season_episodes(season["Id"]):
            if is_special(ep.get("Name") or ""):
                skipped += 1
                continue
            out.append(ep)
    return out, skipped


def build_pool(bgm, chain: List[int]) -> List[Dict[str, Any]]:
    pool: List[Dict[str, Any]] = []
    for sid in chain:
        pool.extend(bgm.episode_list(sid))
    return pool


def scan_series(jf, bgm, series: Dict[str, Any], allow_search: bool = True,
                threshold: float = 0.45) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "series": series.get("Name"), "series_id": series["Id"],
        "seasons": len([s for s in jf.seasons(series["Id"]) if (s.get("IndexNumber") or 0) >= 1]),
        "status": REVIEW, "reason": "", "anchor": None, "anchor_how": "none",
        "chain": [], "episodes": [], "to_write": 0, "coverage": 0.0, "mean_sim": 0.0,
        "skipped_specials": 0, "notes": [],
    }
    local, skipped = collect_local_episodes(jf, series)
    entry["skipped_specials"] = skipped
    if not local:
        entry["reason"] = "no episodes"
        return entry

    sid, how = series_anchor(bgm, series)
    if not sid:
        sid, how = season_anchor(bgm, jf, series)
    if not sid and allow_search:
        sid, how, notes = search_anchor(bgm, series)
        entry["notes"].extend(notes)
    if not sid:
        entry["reason"] = "no Bangumi anchor (set one on the series or a season, or check the title)"
        return entry

    entry["anchor"], entry["anchor_how"] = sid, how
    chain = bgm.chain(sid)
    entry["chain"] = chain
    pool = build_pool(bgm, chain)
    if not pool:
        entry["reason"] = "empty Bangumi episode pool"
        return entry

    if len(pool) == len(local):
        pairs = [(i, i) for i in range(len(local))]
        seq = True
    else:
        pairs = fill_gaps(align([e.get("Name") or "" for e in local], pool, threshold), len(local), len(pool))
        seq = False

    entry["coverage"] = len(pairs) / float(len(local))
    entry["mean_sim"] = (sum(similarity(local[i].get("Name") or "", pool[j].get("name_cn") or pool[j].get("name") or "")
                             for i, j in pairs) / len(pairs)) if pairs else 0.0
    consistent = len(pool) == len(local) or (entry["coverage"] >= 0.9 and entry["mean_sim"] >= 0.55)
    if not consistent:
        entry["reason"] = "count/name mismatch: local %d vs pool %d, coverage %.0f%%, mean sim %.2f" % (
            len(local), len(pool), entry["coverage"] * 100, entry["mean_sim"])
        entry["status"] = REVIEW
    else:
        entry["status"] = OK

    episodes = []
    for i, j in pairs:
        ep, bgm_ep = local[i], pool[j]
        sim = similarity(ep.get("Name") or "", bgm_ep.get("name_cn") or bgm_ep.get("name") or "")
        current = (ep.get("ProviderIds") or {}).get("Bangumi")
        episodes.append({
            "item_id": ep["Id"], "season": ep.get("ParentIndexNumber"),
            "index": ep.get("IndexNumber"), "name": ep.get("Name"),
            "bgm_id": str(bgm_ep["id"]), "bgm_name": bgm_ep.get("name_cn") or bgm_ep.get("name"),
            "old": current, "change": str(current) != str(bgm_ep["id"]), "sim": round(sim, 3),
        })
    entry["episodes"] = episodes
    if entry["status"] == OK:
        entry["to_write"] = sum(1 for e in episodes if e["change"])
    return entry


def run_scan(jf, bgm, library: Optional[str] = None, limit: Optional[int] = None,
             allow_search: bool = True, threshold: float = 0.45,
             out: str = "jbmid-report.json") -> Dict[str, Any]:
    series_list = jf.all_series(library_name=library, limit=limit)
    log("scanning %d series%s" % (len(series_list), " from library %s" % library if library else ""))
    report: Dict[str, Any] = {"library": library, "threshold": threshold, "series": []}
    done = 0
    for series in series_list:
        done += 1
        try:
            entry = scan_series(jf, bgm, series, allow_search, threshold)
        except Exception as exc:
            entry = {"series": series.get("Name"), "series_id": series["Id"], "status": REVIEW,
                     "reason": "error: %s" % exc, "episodes": [], "to_write": 0}
        report["series"].append(entry)
        mark = "OK  " if entry["status"] == OK else "REVIEW"
        log("[%d/%d] %s %-40s %s" % (done, len(series_list), mark, entry["series"],
                                     entry.get("reason") or "to write %d" % entry.get("to_write", 0)))
        if done % 10 == 0:
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, indent=1)
    ok = [e for e in report["series"] if e["status"] == OK]
    report["summary"] = {
        "series_ok": len(ok),
        "series_review": len(report["series"]) - len(ok),
        "episodes_to_write": sum(e.get("to_write", 0) for e in ok),
    }
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    return report


def apply_report(jf, report: Dict[str, Any], backup_path: Optional[str] = None,
                 dry_run: bool = False, only: Optional[str] = None) -> List[Dict[str, Any]]:
    entries = [e for e in report.get("series", []) if e.get("status") == OK]
    if only:
        entries = [e for e in entries if only in (e.get("series") or "")]
    backup: List[Dict[str, Any]] = []
    written = 0
    for entry in entries:
        log("[%s] %d episodes" % (entry["series"], len(entry.get("episodes") or [])))
        for ep in entry.get("episodes") or []:
            if dry_run:
                current = (jf.item(ep["item_id"]).get("ProviderIds") or {}).get("Bangumi")
                result = {"ok": True, "before": current, "after": ep["bgm_id"], "collateral": {}}
            else:
                result = jf.set_provider_id(ep["item_id"], "Bangumi", ep["bgm_id"])
            if result["before"] == result["after"]:
                continue
            if not result["ok"]:
                log("  ! write failed: %s #%s" % (entry["series"], ep.get("index")))
                continue
            if result["collateral"]:
                log("  ! collateral change: %s" % result["collateral"])
            backup.append({"item_id": ep["item_id"], "series": entry["series"],
                           "season": ep.get("season"), "index": ep.get("index"),
                           "name": ep.get("name"), "old": result["before"], "new": result["after"]})
            written += 1
    if backup_path and backup and not dry_run:
        with open(backup_path, "w", encoding="utf-8") as fh:
            json.dump(backup, fh, ensure_ascii=False, indent=1)
    log("%s %d episodes" % ("would write" if dry_run else "wrote", written))
    return backup


def rollback(jf, backup_path: str, dry_run: bool = False) -> int:
    with open(backup_path, encoding="utf-8") as fh:
        items = json.load(fh)
    count = 0
    for row in items:
        if dry_run:
            log("would restore %s #%s -> %s" % (row.get("series"), row.get("index"), row.get("old")))
            continue
        jf.set_provider_id(row["item_id"], "Bangumi", row.get("old"))
        count += 1
    log("%s %d episodes" % ("would restore" if dry_run else "restored", count if not dry_run else len(items)))
    return count
