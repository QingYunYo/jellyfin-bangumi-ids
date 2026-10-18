"""Scan a library and decide which Bangumi episode ids every episode should get."""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional, Tuple

from .match import (align, episode_similarity, fill_gaps, is_special, name_match, similarity,
                    title_keys)

OK, REVIEW = "ok", "review"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def series_anchor(series: Dict[str, Any]) -> Tuple[Optional[int], str]:
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


def anchor_plausible(bgm, series: Dict[str, Any], sid: int) -> bool:
    """An existing id is only an anchor if that subject really carries this show's title.

    A wrong series-level id poisons everything downstream: the chain becomes one
    unrelated show and the whole series can never recover.
    """
    if not title_keys(series):
        return True
    try:
        subject = bgm.subject(int(sid))
    except Exception:  # network hiccup: do not throw away a possibly good anchor
        return True
    names = [subject.get("name") or "", subject.get("name_cn") or ""]
    return any(name_match(key, name) for key in title_keys(series) for name in names if name)


def search_anchor(bgm, series: Dict[str, Any]) -> Tuple[Optional[int], str, List[str]]:
    """Search bgm by every stored title (localized + original); refuse weak matches."""
    keys = title_keys(series)
    year = series.get("ProductionYear")
    notes: List[str] = []
    seen: List[int] = []
    failed = 0
    for key in keys:
        try:
            hits = bgm.search(key, 10)
        except Exception as exc:  # network hiccup must not kill the whole scan
            failed += 1
            notes.append("%s: %s" % (key, exc))
            continue
        for hit in hits:
            hid = hit.get("id")
            if hid in seen:
                continue
            seen.append(hid)
            cn = hit.get("name_cn") or ""
            jp = hit.get("name") or ""
            if any(name_match(k, t) for k in keys for t in (cn, jp) if t):
                return int(hid), "search", notes
            if year and str(hit.get("date") or "").startswith(str(year)):
                notes.append("year-hit:%s" % (cn or jp))
    if failed and failed == len(keys):
        return None, "search-failed", notes
    return None, "search-mismatch", notes


def pick_anchor(bgm, jf, series: Dict[str, Any], allow_search: bool = True
                ) -> Tuple[Optional[int], str, List[str]]:
    """Series id -> season id -> title search, discarding ids that do not describe this show."""
    notes: List[str] = []
    sid, how = series_anchor(series)
    if sid and not anchor_plausible(bgm, series, sid):
        notes.append("ignored implausible series id %s" % sid)
        sid, how = None, "none"
    if not sid:
        sid, how = season_anchor(bgm, jf, series)
        if sid and not anchor_plausible(bgm, series, sid):
            notes.append("ignored implausible season id %s" % sid)
            sid, how = None, "none"
    if not sid and allow_search:
        sid, how, extra = search_anchor(bgm, series)
        notes.extend(extra)
    return sid, how, notes


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


def _segments(jf, bgm, series: Dict[str, Any], chain: List[int]
              ) -> Tuple[List[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]], int]:
    """Split local episodes into the groups we align against one pool at a time.

    When the number of local seasons equals the number of subjects in the chain,
    each season is aligned against its own subject -- aligning the whole series
    against the whole chain makes one missing episode shift every later season.
    """
    seasons = [s for s in jf.seasons(series["Id"]) if (s.get("IndexNumber") or 0) >= 1]
    groups: List[List[Dict[str, Any]]] = []
    skipped = 0
    for season in seasons:
        episodes = jf.season_episodes(season["Id"])
        kept = [e for e in episodes if not is_special(e.get("Name") or "")]
        skipped += len(episodes) - len(kept)
        groups.append(kept)
    if len(groups) == len(chain) and all(groups):
        pairs = [(g, bgm.episode_list(sid)) for g, sid in zip(groups, chain)]
        return pairs, skipped
    flat = [e for g in groups for e in g]
    return [(flat, build_pool(bgm, chain))], skipped


def _align_segment(local: List[Dict[str, Any]], pool: List[Dict[str, Any]],
                   threshold: float) -> Tuple[List[Tuple[int, int]], bool]:
    if len(pool) == len(local):
        return [(i, i) for i in range(len(local))], True
    return fill_gaps(align([e.get("Name") or "" for e in local], pool, threshold),
                     len(local), len(pool)), False


def _size_ok(local: int, pool: int) -> bool:
    return abs(pool - local) <= max(2, int(0.15 * max(local, 1)))


def scan_series(jf, bgm, series: Dict[str, Any], allow_search: bool = True,
                threshold: float = 0.45) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "series": series.get("Name"), "series_id": series["Id"],
        "seasons": len([s for s in jf.seasons(series["Id"]) if (s.get("IndexNumber") or 0) >= 1]),
        "status": REVIEW, "reason": "", "anchor": None, "anchor_how": "none",
        "chain": [], "episodes": [], "to_write": 0, "coverage": 0.0, "mean_sim": 0.0,
        "skipped_specials": 0, "notes": [],
    }
    sid, how, notes = pick_anchor(bgm, jf, series, allow_search=allow_search)
    entry["notes"].extend(notes)
    if not sid:
        entry["reason"] = "no Bangumi anchor (set one on the series or a season, or check the title)"
        return entry

    entry["anchor"], entry["anchor_how"] = sid, how
    chain = bgm.chain(sid)
    entry["chain"] = chain
    segments, skipped = _segments(jf, bgm, series, chain)
    entry["skipped_specials"] = skipped
    total_local = sum(len(local) for local, _ in segments)
    if not total_local:
        entry["reason"] = "no episodes"
        return entry

    matched = 0
    sim_sum = 0.0
    problems: List[str] = []
    episodes: List[Dict[str, Any]] = []
    for local, pool in segments:
        if not pool:
            problems.append("empty Bangumi pool")
            continue
        pairs, sequenced = _align_segment(local, pool, threshold)
        coverage = len(pairs) / float(len(local))
        mean_sim = (sum(similarity(local[i].get("Name") or "",
                                   pool[j].get("name_cn") or pool[j].get("name") or "")
                        for i, j in pairs) / len(pairs)) if pairs else 0.0
        matched += len(pairs)
        sim_sum += mean_sim * len(pairs)
        if not _size_ok(len(local), len(pool)):
            problems.append("size mismatch %d local vs %d pool" % (len(local), len(pool)))
        elif not sequenced and (coverage < 0.9 or mean_sim < 0.55):
            problems.append("weak match: coverage %.0f%%, mean sim %.2f" % (coverage * 100, mean_sim))
        for i, j in pairs:
            ep, bgm_ep = local[i], pool[j]
            current = (ep.get("ProviderIds") or {}).get("Bangumi")
            target = str(bgm_ep["id"])
            episodes.append({
                "item_id": ep["Id"], "season": ep.get("ParentIndexNumber"),
                "index": ep.get("IndexNumber"), "name": ep.get("Name"),
                "bgm_id": target, "bgm_name": bgm_ep.get("name_cn") or bgm_ep.get("name"),
                "old": current, "change": str(current) != target,
                "sim": round(similarity(ep.get("Name") or "",
                                        bgm_ep.get("name_cn") or bgm_ep.get("name") or ""), 3),
            })

    entry["coverage"] = matched / float(total_local)
    entry["mean_sim"] = (sim_sum / matched) if matched else 0.0
    entry["episodes"] = episodes
    if problems:
        entry["status"] = REVIEW
        entry["reason"] = "; ".join(problems)
    else:
        entry["status"] = OK
        entry["to_write"] = sum(1 for e in episodes if e["change"])
    return entry


def build_special_pool(bgm, chain: List[int]) -> List[Dict[str, Any]]:
    """All ``type=1`` (SP/OVA) episodes of the chain, in chain order."""
    pool: List[Dict[str, Any]] = []
    for sid in chain:
        for ep in bgm.episodes(sid, 1):
            if ep.get("name") or ep.get("name_cn"):
                pool.append(ep)
    return pool


def collect_local_specials(jf, series: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Season-0 episodes plus any in-season episode whose name looks like a special."""
    out: List[Dict[str, Any]] = []
    for season in jf.seasons(series["Id"]):
        s_idx = season.get("IndexNumber") or 0
        for ep in jf.season_episodes(season["Id"]):
            name = ep.get("Name") or ""
            if s_idx == 0 or is_special(name):
                out.append({"season": s_idx, "index": ep.get("IndexNumber"),
                            "name": name, "old": (ep.get("ProviderIds") or {}).get("Bangumi"),
                            "item": ep})
    return out


def scan_specials(jf, bgm, series: Dict[str, Any], min_sim: float = 0.55) -> Dict[str, Any]:
    """Match local SP/OVA episodes against the chain's ``type=1`` episodes."""
    name = series.get("Name") or ""
    entry: Dict[str, Any] = {"series": name, "series_id": series["Id"], "status": "review",
                             "reason": "", "episodes": [], "to_write": 0, "chain": []}
    anchor, how, notes = pick_anchor(bgm, jf, series)
    entry["notes"] = notes
    if not anchor:
        entry["reason"] = "no Bangumi anchor"
        return entry
    entry["anchor"], entry["anchor_how"] = anchor, how
    chain = bgm.chain(anchor)
    entry["chain"] = chain
    pool = build_special_pool(bgm, chain)
    if not pool:
        entry["reason"] = "no SP/OVA episodes for this show on Bangumi"
        return entry
    locals_ = collect_local_specials(jf, series)
    if not locals_:
        entry["reason"] = "no special episodes in the library"
        return entry

    local_names = [x["name"] for x in locals_]
    positional = False
    if len(pool) == len(locals_) and len(pool) <= 3:
        # only a few SPs on the whole chain and the count matches: map by order, with a similarity floor
        pairs = [(i, i, episode_similarity(local_names[i], pool[i])) for i in range(len(pool))]
        pairs = [p for p in pairs if p[2] >= 0.25]
        positional = True
        entry["notes"] = ["positional"]
    else:
        pairs = align(local_names, pool, threshold=0.45)
        pairs = [(i, j, episode_similarity(local_names[i], pool[j])) for i, j in pairs]
        pairs = [p for p in pairs if p[2] >= min_sim]

    matched = len(pairs)
    mean = round(sum(p[2] for p in pairs) / matched, 2) if matched else 0.0
    entry["pool"] = len(pool)
    entry["local"] = len(locals_)
    entry["matched"] = matched
    entry["mean_sim"] = mean
    entry["coverage"] = round(matched / float(len(locals_)), 2)
    for i, j, sc in pairs:
        item = locals_[i]
        new = str(pool[j]["id"])
        entry["episodes"].append({
            "season": item["season"], "index": item["index"], "name": item["name"],
            "old": item["old"], "bgm_id": new, "bgm_name": pool[j].get("name_cn") or pool[j].get("name"),
            "sim": round(sc, 2), "change": str(item["old"] or "") != new, "item_id": item["item"]["Id"],
        })
    entry["to_write"] = sum(1 for e in entry["episodes"] if e["change"])
    if matched == 0:
        entry["reason"] = "no episode reached the similarity threshold"
    elif positional and matched == len(pool):
        entry["status"] = OK
    elif mean < min_sim:
        entry["reason"] = "weak match: mean sim %.2f" % mean
    else:
        entry["status"] = "ok"
    return entry


def run_specials(jf, bgm, library=None, limit=None, verbose=False,
                 out: str = "jbmid-specials.json") -> Dict[str, Any]:
    series_list = jf.all_series(library_name=library)
    if limit:
        series_list = series_list[:limit]
    report: Dict[str, Any] = {"library": library, "mode": "special", "series": []}
    for i, series in enumerate(series_list, 1):
        try:
            entry = scan_specials(jf, bgm, series)
        except Exception as exc:  # noqa: BLE001 - one bad series must not kill the run
            entry = {"series": series.get("Name"), "series_id": series.get("Id"),
                     "status": "review", "reason": "error: %s" % exc, "episodes": [],
                     "to_write": 0}
        report["series"].append(entry)
        if verbose and (entry["status"] == OK or entry.get("matched")):
            print("[%d/%d] %-7s %-28s %s" % (i, len(series_list), entry["status"].upper(),
                                             (entry["series"] or "")[:28], entry.get("reason") or
                                             "match %d/%d sim %.2f" % (entry.get("matched", 0),
                                                                      entry.get("local", 0),
                                                                      entry.get("mean_sim", 0))))
    ok = [e for e in report["series"] if e["status"] == OK]
    report["summary"] = {
        "series_ok": len(ok),
        "series_review": len(report["series"]) - len(ok),
        "episodes_to_write": sum(e.get("to_write", 0) for e in ok),
        "specials_matched": sum(e.get("matched", 0) for e in report["series"]),
    }
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    return report


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
