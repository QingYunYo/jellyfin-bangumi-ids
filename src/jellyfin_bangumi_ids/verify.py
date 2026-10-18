"""Read-only check: does every stored Bangumi episode id still point at the right episode?"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .match import similarity
from .scan import log


def run_verify(jf, bgm, library: Optional[str] = None, limit: Optional[int] = None,
               threshold: float = 0.45, out: str = "jbmid-check.json") -> Dict[str, Any]:
    checked = low = 0
    rows: List[Dict[str, Any]] = []
    subjects = set()
    for series in jf.all_series(library_name=library, limit=limit):
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
            score = similarity(ep.get("Name") or "",
                               remote.get("name_cn") or remote.get("name") or "")
            if score < threshold:
                low += 1
                rows.append({"series": series["Name"], "item_id": ep["Id"], "index": ep.get("IndexNumber"),
                             "local": ep.get("Name"), "bgm": remote.get("name_cn") or remote.get("name"),
                             "bgm_id": pid, "subject": remote.get("subject_id"), "sim": round(score, 3)})
        log("checked %-40s total=%d low-sim=%d" % (series["Name"][:40], checked, low))
    report = {"checked": checked, "low_similarity": low, "threshold": threshold,
              "subjects": sorted(x for x in subjects if x), "rows": rows}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    log("checked %d episodes, %d below %.2f -> %s" % (checked, low, threshold, out))
    return report
