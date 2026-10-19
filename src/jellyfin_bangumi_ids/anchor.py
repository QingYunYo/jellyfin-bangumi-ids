"""Set or repair the Bangumi anchor id on a series.

The series-level id is what every other mode starts from, so a wrong one poisons
the whole show: the chain becomes an unrelated series and no episode can ever be
matched. Seasons are voted first because they are usually scraped per season and
carry the accurate subject; the series id is only trusted when nothing else exists.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from .scan import (anchor_plausible, collect_local_episodes, episode_parent_vote, log,
                   season_anchor, season_id_issues, series_anchor, title_keys)


def derive_anchor(bgm, jf, series: Dict[str, Any]) -> Tuple[Optional[int], str]:
    """Episode parents, then season votes, then the series id, then a title search."""
    parent = episode_parent_vote(bgm, jf, series)
    if parent and anchor_plausible(bgm, series, parent):
        return parent, "episode-parent"
    sid, how = season_anchor(bgm, jf, series)
    if sid:
        return sid, how
    sid, how = series_anchor(series)
    if sid:
        return sid, how
    from .scan import search_anchor
    local, _skipped = collect_local_episodes(jf, series)
    sid, how, _notes = search_anchor(bgm, series, local_total=len(local))
    return sid, how if sid else "none"


def run_anchor(jf, bgm, name: str, library: Optional[str] = None,
               sid: Optional[int] = None, clear: bool = False, force: bool = False,
               dry_run: bool = False, backup_path: Optional[str] = None) -> Dict[str, Any]:
    series = jf.find_series(name, library_name=library)
    current = (series.get("ProviderIds") or {}).get("Bangumi")
    out: Dict[str, Any] = {"series": series["Name"], "series_id": series["Id"],
                           "before": current, "dry_run": dry_run}

    if clear:
        target, how = None, "cleared"
    elif sid is not None:
        target, how = int(sid), "given"
    else:
        target, how = derive_anchor(bgm, jf, series)

    if target is not None and not anchor_plausible(bgm, series, target) and not force:
        raise SystemExit("refusing to set %s on %r: that subject does not look like this show "
                         "(pass --force to override)" % (target, series["Name"]))
    out.update({"after": target, "how": how})
    log("%s (%s)" % (series["Name"], series["Id"]))
    log("  before : %s" % (current or "(none)"))
    log("  after  : %s (%s)" % (target if target is not None else "(cleared)", how))

    if str(current or "") == str(target or ""):
        log("already correct, nothing to write")
        return out
    if dry_run:
        log("would write")
        return out

    result = jf.set_provider_id(series["Id"], "Bangumi", target)
    out["write"] = {k: v for k, v in result.items()}
    if not result["ok"]:
        raise SystemExit("write failed: Bangumi still %s" % (result["after"],))
    if result["collateral"]:
        log("  ! collateral change: %s" % result["collateral"])
    if backup_path:
        with open(backup_path, "w", encoding="utf-8") as fh:
            json.dump([{"item_id": series["Id"], "kind": "series", "series": series["Name"],
                        "old": current, "new": target}], fh, ensure_ascii=False, indent=1)
    log("wrote Bangumi=%s" % (target if target is not None else "(cleared)"))
    return out


def season_votes(bgm, jf, series: Dict[str, Any]) -> Dict[int, "Counter[int]"]:
    """Vote每个季的条目归属 by the Bangumi ids already stored on its episodes."""
    votes: Dict[int, "Counter[int]"] = {}
    for season in jf.seasons(series["Id"]):
        index = season.get("IndexNumber") or 0
        if index < 1:
            continue
        for episode in jf.season_episodes(season["Id"]):
            raw = (episode.get("ProviderIds") or {}).get("Bangumi")
            if not raw:
                continue
            try:
                remote = bgm.episode(int(raw))
            except Exception:
                continue
            subject = remote.get("subject_id")
            if subject:
                votes.setdefault(index, Counter())[subject] += 1
    return votes


def season_report(bgm, jf, series: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Seasons whose stored id is off, plus seasons that span two subjects."""
    seasons = jf.seasons(series["Id"])
    votes = season_votes(bgm, jf, series)
    issues = season_id_issues(seasons, votes)
    for issue in issues:
        issue["mismatch"] = True

    # A season that carries two subjects cannot report both from one id, even when
    # its stored id happens to be the majority one.
    seen = set(issue["season"] for issue in issues)
    by_index = {}
    for season in seasons:
        by_index[season.get("IndexNumber") or 0] = season
    for index, counter in votes.items():
        if index in seen:
            continue
        big = [subject for subject, count in counter.items() if count >= 2]
        total = sum(counter.values())
        if len(big) < 2:
            continue
        season = by_index.get(index, {})
        current = (season.get("ProviderIds") or {}).get("Bangumi")
        top = counter.most_common(1)[0]
        issues.append({"season": index, "season_id": season.get("Id"),
                       "name": season.get("Name"), "current": current,
                       "expected": top[0], "votes": dict(counter),
                       "count": top[1], "total": total, "mismatch": False})

    for issue in issues:
        issue["series"] = series["Name"]
        issue["series_id"] = series["Id"]
        issue["confident"] = issue["total"] >= 2 and issue["count"] / float(issue["total"]) >= 0.6
        issue["subjects"] = issue["votes"]
        issue["spanning"] = len([k for k, v in issue["votes"].items() if k and v >= 2]) > 1
    return issues


def run_seasons(jf, bgm, name: Optional[str] = None, library: Optional[str] = None,
                all_series: bool = False, dry_run: bool = False, force: bool = False,
                clear_spans: bool = False, backup_path: Optional[str] = None) -> Dict[str, Any]:
    """Repair season-level Bangumi ids from the ids on their own episodes.

    This is the check that catches the failure the plugin cannot: episode ids can be
    perfect while the season id points a season back, and playback still reports the
    wrong subject.  Only confident votes are written unless ``force`` is set.
    """
    if all_series:
        targets = jf.all_series(library_name=library)
    else:
        targets = [jf.find_series(name, library_name=library)]
    out: Dict[str, Any] = {"dry_run": dry_run, "series": len(targets), "issues": [], "fixed": 0}
    written: List[Dict[str, Any]] = []
    for series in targets:
        issues = season_report(bgm, jf, series)
        out["issues"].extend(issues)
        if not issues:
            continue
        log("%s" % series["Name"])
        for issue in issues:
            if issue.get("spanning"):
                # A majority vote is not authoritative when the season covers two
                # subjects: writing it is what breaks the other half.
                target = None if clear_spans else issue["expected"]
                verdict = " [clear: spanning season]" if clear_spans else " [spans two subjects, skip]"
                if not clear_spans:
                    log("  season %-3s id %-8s spans two subjects, skipped"
                        % (issue["season"], issue["current"] or "(none)"))
                    continue
            else:
                target, verdict = issue["expected"], "" if issue["confident"] else " [low confidence]"
            log("  season %-3s id %-8s -> %-8s (%d/%d episodes)%s"
                % (issue["season"], issue["current"] or "(none)", target or "(cleared)",
                   issue["count"], issue["total"], verdict))
            if dry_run or not (issue["confident"] or force or target is None):
                continue
            result = jf.set_provider_id(issue["season_id"], "Bangumi", target)
            issue["write"] = {"ok": result["ok"], "after": result["after"],
                              "collateral": result["collateral"]}
            if result["ok"]:
                out["fixed"] += 1
                written.append({"item_id": issue["season_id"], "kind": "season",
                                "series": series["Name"], "season": issue["season"],
                                "old": issue["current"], "new": target})
            else:
                log("  ! write failed, still %s" % result["after"])
    if backup_path and written:
        with open(backup_path, "w", encoding="utf-8") as fh:
            json.dump(written, fh, ensure_ascii=False, indent=1)
    log("%d season id(s) off, %d written%s"
        % (len(out["issues"]), out["fixed"], " (dry run)" if dry_run else ""))
    return out
