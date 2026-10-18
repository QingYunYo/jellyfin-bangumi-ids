"""Set or repair the Bangumi anchor id on a series.

The series-level id is what every other mode starts from, so a wrong one poisons
the whole show: the chain becomes an unrelated series and no episode can ever be
matched. Seasons are voted first because they are usually scraped per season and
carry the accurate subject; the series id is only trusted when nothing else exists.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from .scan import (anchor_plausible, collect_local_episodes, episode_parent_vote, log,
                   season_anchor, series_anchor, title_keys)


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
