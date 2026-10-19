"""Read-only check: does every stored Bangumi episode id still point at the right episode?"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List, Optional

from .match import clean_title, similarity
from .scan import log, season_id_issues, spanning_seasons


def season_index_map(season_list: List[Dict[str, Any]]) -> Dict[str, int]:
    """SeasonId -> IndexNumber, so episodes can be grouped by the season they belong to."""
    return {se["Id"]: se.get("IndexNumber") for se in season_list or [] if se.get("Id")}


def episode_season(episode: Dict[str, Any], season_ix: Dict[str, int]) -> int:
    """The season an episode belongs to.

    Jellyfin can report ParentIndexNumber == 1 for every season of a show (seen on a
    25-episode series split into two seasons), so SeasonId wins when it is known.
    """
    index = season_ix.get(episode.get("SeasonId"))
    if index is None:
        index = episode.get("ParentIndexNumber") or 0
    return index


def run_verify(jf, bgm, library: Optional[str] = None, limit: Optional[int] = None,
               threshold: float = 0.45, out: str = "jbmid-check.json") -> Dict[str, Any]:
    checked = low = 0
    rows: List[Dict[str, Any]] = []
    season_rows: List[Dict[str, Any]] = []
    span_rows: List[Dict[str, Any]] = []
    subjects = set()
    for series in jf.all_series(library_name=library, limit=limit):
        seasons = getattr(jf, "seasons", None)
        season_list = (seasons(series["Id"]) if seasons else []) or []
        season_ix = season_index_map(season_list)
        votes: Dict[int, "Counter[int]"] = {}
        for ep in jf.episodes(series["Id"]):
            pid = (ep.get("ProviderIds") or {}).get("Bangumi")
            if not pid:
                continue
            try:
                remote = bgm.episode(int(pid))
            except Exception as exc:
                rows.append({"series": series["Name"], "item_id": ep["Id"], "bgm_id": pid,
                             "error": str(exc)})
                continue
            checked += 1
            subjects.add(remote.get("subject_id"))
            # SeasonId is authoritative: Jellyfin can leave ParentIndexNumber at 1
            # for every season of a show, which would merge separate seasons.
            index = episode_season(ep, season_ix)
            if remote.get("subject_id") and index >= 1:
                votes.setdefault(index, Counter())[remote["subject_id"]] += 1
            score = similarity(ep.get("Name") or "",
                               remote.get("name_cn") or remote.get("name") or "")
            if score < threshold:
                low += 1
                rows.append({"series": series["Name"], "item_id": ep["Id"], "index": ep.get("IndexNumber"),
                             "local": ep.get("Name"), "bgm": remote.get("name_cn") or remote.get("name"),
                             "bgm_id": pid, "subject": remote.get("subject_id"), "sim": round(score, 3)})
        spans = spanning_seasons(votes)
        for issue in season_id_issues(season_list, votes):
            if issue["season"] in spans:
                if issue["current"] is not None:
                    span_rows.append(dict(issue, series=series["Name"]))
                continue
            season_rows.append(dict(issue, series=series["Name"]))
        log("checked %-40s total=%d low-sim=%d season-ids=%d"
            % (series["Name"][:40], checked, low,
               sum(1 for r in season_rows if r["series"] == series["Name"])))
    report = {"checked": checked, "low_similarity": low, "threshold": threshold,
              "subjects": sorted(x for x in subjects if x), "rows": rows,
              "season_rows": season_rows, "span_rows": span_rows}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    log("checked %d episodes, %d below %.2f, %d season ids off -> %s"
        % (checked, low, threshold, len(season_rows), out))
    return report


def run_verify_offline(jf, archive_dir: str, library: Optional[str] = None,
                       limit: Optional[int] = None, threshold: float = 0.45,
                       out: str = "jbmid-check.json") -> Dict[str, Any]:
    """Check every stored id against the plugin's offline archive instead of the API.

    Name similarity alone is noisy (fansub titles differ between groups), so the
    decisive check here is *order*: the ids of one season must walk the bgm sort
    numbers of one subject without repeats, gaps or backtracking.
    """
    from . import archive as arc

    files = arc.available(archive_dir)
    if "episode" not in files:
        raise SystemExit("no episode.jsonlines under %s" % archive_dir)

    local = []          # (series, series_bangumi_id, episodes deduped by item id)
    by_name = {}
    global_items = set()
    for series in jf.all_series(library_name=library, limit=limit):
        sid = arc.to_int((series.get("ProviderIds") or {}).get("Bangumi"))
        by_name.setdefault(series["Name"], []).append(series)
        eps = {}
        for ep in jf.episodes(series["Id"]):
            if ep["Id"] in global_items:      # same item listed under two series entries
                continue
            global_items.add(ep["Id"])
            eps[ep["Id"]] = ep
        local.append((series, sid, list(eps.values())))
    duplicate_series = [{"name": name, "ids": [s["Id"] for s in rows],
                         "paths": [(s.get("Path") or "") for s in rows]}
                        for name, rows in by_name.items() if len(rows) > 1]

    wanted = set()
    for _series, _sid, eps in local:
        for ep in eps:
            pid = arc.to_int((ep.get("ProviderIds") or {}).get("Bangumi"))
            if pid:
                wanted.add(pid)
    remote_eps = arc.collect_episodes(files["episode"], wanted) if wanted else {}

    anchors = {sid for _series, sid, _eps in local if sid}
    used_subjects = {r["subject_id"] for r in remote_eps.values() if r.get("subject_id")}
    remote_subjects = {}
    if "subject" in files:
        remote_subjects = arc.collect_subjects(files["subject"], anchors | used_subjects)

    checked = unknown = low = foreign = disorder = 0
    season_rows: List[Dict[str, Any]] = []
    span_rows: List[Dict[str, Any]] = []
    seen: Dict[int, int] = {}
    rows: List[Dict[str, Any]] = []
    for series, sid, eps in local:
        seasons = getattr(jf, "seasons", None)
        season_list = (seasons(series["Id"]) if seasons else []) or []
        season_ix = season_index_map(season_list)
        eps = sorted(eps, key=lambda e: ((e.get("ParentIndexNumber") or 0),
                                        (e.get("IndexNumber") or 0)))
        usage: Dict[int, int] = {}
        for ep in eps:
            pid = arc.to_int((ep.get("ProviderIds") or {}).get("Bangumi"))
            row = remote_eps.get(pid) if pid else None
            if row and row.get("subject_id"):
                usage[row["subject_id"]] = usage.get(row["subject_id"], 0) + 1
        season_votes: Dict[int, "Counter[int]"] = {}
        for ep in eps:
            row_vote = remote_eps.get(arc.to_int((ep.get("ProviderIds") or {}).get("Bangumi")))
            subject_vote = row_vote.get("subject_id") if row_vote else None
            index = episode_season(ep, season_ix)
            if subject_vote and index >= 1:
                season_votes.setdefault(index, Counter())[subject_vote] += 1
        spans = spanning_seasons(season_votes)
        for issue in season_id_issues(season_list, season_votes):
            if issue["season"] in spans:
                if issue["current"] is not None:
                    span_rows.append(dict(issue, series=series["Name"]))
                continue
            season_rows.append(dict(issue, series=series["Name"]))
        last_sort: Dict[int, int] = {}
        for ep in eps:
            pid = arc.to_int((ep.get("ProviderIds") or {}).get("Bangumi"))
            if not pid:
                continue
            checked += 1
            seen[pid] = seen.get(pid, 0) + 1
            remote = remote_eps.get(pid)
            base = {"series": series["Name"], "item_id": ep["Id"], "bgm_id": pid,
                    "local": ep.get("Name"), "season": ep.get("ParentIndexNumber"),
                    "index": ep.get("IndexNumber")}
            if remote is None:
                unknown += 1
                rows.append(dict(base, kind="unknown_id", detail="not in archive"))
                continue
            title = remote.get("name_cn") or remote.get("name") or ""
            score = similarity(clean_title(ep.get("Name") or ""), clean_title(title))
            rsub = remote.get("subject_id")
            base.update(bgm=title, subject=rsub, sim=round(score, 3))
            if score < threshold:
                low += 1
                rows.append(dict(base, kind="low_similarity"))
            if rsub and rsub != sid and usage.get(rsub, 0) == 1:
                foreign += 1
                rows.append(dict(base, kind="foreign_subject",
                                 subject_name=_subject_name(remote_subjects, rsub)))
            sort = arc.to_int(remote.get("sort"))
            if sort is not None and (ep.get("ParentIndexNumber") or 0) > 0 and rsub:
                prev = last_sort.get(rsub)
                if prev is not None and sort != prev + 1:
                    disorder += 1
                    rows.append(dict(base, kind="disorder", expected=prev + 1, got=sort))
                last_sort[rsub] = sort

    dup = sum(1 for n in seen.values() if n > 1)

    anchor_rows = []
    for series, sid, eps in local:
        if not sid:
            continue
        remote_subject = remote_subjects.get(sid)
        if remote_subject is None:
            anchor_rows.append({"series": series["Name"], "bgm_id": sid,
                                "kind": "anchor_unknown", "detail": "not in archive"})
            continue
        ids = {arc.to_int((ep.get("ProviderIds") or {}).get("Bangumi")) for ep in eps}
        ids.discard(None)
        subjects = {remote_eps[i]["subject_id"] for i in ids
                    if i in remote_eps and remote_eps[i].get("subject_id")}
        if subjects and sid not in subjects:
            anchor_rows.append({"series": series["Name"], "bgm_id": sid,
                                "subject": _subject_name(remote_subjects, sid),
                                "used": sorted(subjects), "kind": "anchor_unused"})

    report = {"checked": checked, "unknown": unknown, "duplicate": dup,
              "low_similarity": low, "foreign_subject": foreign, "disorder": disorder,
              "threshold": threshold, "anchor_rows": anchor_rows, "season_rows": season_rows,
              "span_rows": span_rows, "duplicate_series": duplicate_series, "rows": rows,
              "subjects": sorted(x for x in used_subjects if x)}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    log("offline check: %d ids | unknown %d | dup %d | low-sim %d | disorder %d | foreign %d "
        "| anchors %d | season-ids %d | season-spans %d -> %s"
        % (checked, unknown, dup, low, disorder, foreign, len(anchor_rows),
           len(season_rows), len(span_rows), out))
    return report


def _subject_name(subjects: Dict[int, Dict[str, Any]], sid: Optional[int]) -> str:
    row = subjects.get(sid or 0) or {}
    return row.get("name_cn") or row.get("name") or ""
