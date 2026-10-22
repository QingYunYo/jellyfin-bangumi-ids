"""One command for the documented repair order: scan, apply, seasons, specials, verify.

The five modes depend on each other -- specials must be matched after the episode ids
exist (an SP otherwise borrows a main episode's id), and verify is only meaningful once
everything was written.  Running them by hand means five chances to skip a step, so
``sync`` runs the same order and stops at the first failure with its exit code.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .anchor import run_seasons
from .scan import apply_report, run_scan, run_specials
from .verify import fail_on_breaches, run_verify, run_verify_offline

STEPS = 5


def _line(step: int, name: str, detail: str, failed: bool = False) -> None:
    print("[%d/%d] %-8s %s%s" % (step, STEPS, name, "FAILED: " if failed else "", detail),
          flush=True)


def _join(directory: Optional[str], name: str) -> str:
    return os.path.join(directory, name) if directory else name


def _prepare(path: str) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)


def _fail(result: Dict[str, Any], name: str) -> Dict[str, Any]:
    result.update({"exit": 1, "failed_step": name})
    return result


def _stop(result: Dict[str, Any], step: int, name: str, detail: str) -> Dict[str, Any]:
    _line(step, name, detail, failed=True)
    result["steps"].append({"step": name, "ok": False, "detail": detail})
    return _fail(result, name)


def run_sync(jf, bgm, archive: Optional[str] = None, library: Optional[str] = None,
             series_ids: Optional[List[str]] = None, limit: Optional[int] = None,
             threshold: float = 0.45, allow_search: bool = True, dry_run: bool = False,
             refresh: bool = False, stop_on_review: bool = False,
             backup_dir: Optional[str] = None, out_dir: Optional[str] = None,
             fail_on: Optional[str] = None, clear_spans: bool = False,
             force: bool = False) -> Dict[str, Any]:
    """Run scan -> apply -> anchor --seasons -> special -> verify, stopping on failure.

    ``dry_run`` only prints: no provider id and no backup file is written.  The JSON
    reports of the scans are still produced, because verify and apply read them.
    """
    result: Dict[str, Any] = {"steps": [], "exit": 0, "failed_step": None}

    # 1. scan -- decide the ids and write the report the next steps consume.
    scan_out = _join(out_dir, "jbmid-report.json")
    _prepare(scan_out)
    try:
        report = run_scan(jf, bgm, library=library, limit=limit, allow_search=allow_search,
                          threshold=threshold, out=scan_out, series_ids=series_ids)
    except (SystemExit, Exception) as exc:          # noqa: BLE001 - stop at the first failure
        return _stop(result, 1, "scan", str(exc))
    summary = report.get("summary") or {}
    review = int(summary.get("series_review") or 0)
    if stop_on_review and review:
        return _stop(result, 1, "scan", "%d series need review, stopping (--stop-on-review)"
                     % review)
    _line(1, "scan", "%d ok, %d review, %d episodes to write -> %s"
          % (summary.get("series_ok", 0), review, summary.get("episodes_to_write", 0), scan_out))
    result["steps"].append({"step": "scan", "ok": True, "summary": summary})

    # 2. apply -- write the episode ids.
    stats = {"written": 0, "failed": 0, "skipped": 0}
    backup = _join(backup_dir, "jbmid-backup.json")
    _prepare(backup)
    try:
        apply_report(jf, report, backup_path=backup, dry_run=dry_run, refresh=refresh,
                     stats=stats)
    except (SystemExit, Exception) as exc:          # noqa: BLE001
        return _stop(result, 2, "apply", str(exc))
    failed = bool(stats["failed"])
    _line(2, "apply", "%s %d episodes, %d failed, %d unchanged%s"
          % ("would write" if dry_run else "wrote", stats["written"], stats["failed"],
             stats["skipped"], " -- stopped" if failed else ""), failed=failed)
    result["steps"].append({"step": "apply", "ok": not failed, "stats": stats})
    if failed:
        return _fail(result, "apply")

    # 3. anchor --seasons -- the plugin reports 在看 with the season id.
    seasons_backup = _join(backup_dir, "jbmid-anchor-backup.json")
    _prepare(seasons_backup)
    try:
        seasons = run_seasons(jf, bgm, library=library, all_series=not series_ids,
                              dry_run=dry_run, force=force, clear_spans=clear_spans,
                              backup_path=seasons_backup, series_ids=series_ids)
    except (SystemExit, Exception) as exc:          # noqa: BLE001
        return _stop(result, 3, "anchor", str(exc))
    written = seasons.get("fixed", 0) if not dry_run else seasons.get("planned", 0)
    failed = bool(seasons.get("failed"))
    _line(3, "anchor", "%d season id(s) off, %d %s%s"
          % (len(seasons.get("issues") or []), written,
             "written" if not dry_run else "would be written",
             " -- %d failed" % seasons["failed"] if failed else ""), failed=failed)
    result["steps"].append({"step": "anchor", "ok": not failed, "seasons": seasons})
    if failed:
        return _fail(result, "anchor")

    # 4. special -- match SP/OVA after the main ids exist, then write them.
    special_out = _join(out_dir, "jbmid-specials.json")
    _prepare(special_out)
    try:
        special_report = run_specials(jf, bgm, library=library, limit=limit,
                                      out=special_out, series_ids=series_ids)
    except (SystemExit, Exception) as exc:          # noqa: BLE001
        return _stop(result, 4, "special", str(exc))
    special_stats = {"written": 0, "failed": 0, "skipped": 0}
    special_backup = _join(backup_dir, "jbmid-backup-sp.json")
    _prepare(special_backup)
    try:
        apply_report(jf, special_report, backup_path=special_backup, dry_run=dry_run,
                     refresh=refresh, stats=special_stats)
    except (SystemExit, Exception) as exc:          # noqa: BLE001
        return _stop(result, 4, "special", str(exc))
    special_summary = special_report.get("summary") or {}
    failed = bool(special_stats["failed"])
    _line(4, "special", "%d matched, %d borrowed cleared, %s %d episodes%s"
          % (special_summary.get("specials_matched", 0),
             special_summary.get("specials_cleared", 0),
             "would write" if dry_run else "wrote", special_stats["written"],
             " -- %d failed" % special_stats["failed"] if failed else ""), failed=failed)
    result["steps"].append({"step": "special", "ok": not failed,
                            "summary": special_summary, "stats": special_stats})
    if failed:
        return _fail(result, "special")

    # 5. verify -- read the ids back, offline when the archive is available.
    check_out = _join(out_dir, "jbmid-check.json")
    _prepare(check_out)
    try:
        if archive:
            checked_report = run_verify_offline(jf, archive, library=library, limit=limit,
                                                threshold=threshold, out=check_out,
                                                series_ids=series_ids)
        else:
            checked_report = run_verify(jf, bgm, library=library, limit=limit,
                                        threshold=threshold, out=check_out,
                                        series_ids=series_ids)
    except (SystemExit, Exception) as exc:          # noqa: BLE001
        return _stop(result, 5, "verify", str(exc))
    if not checked_report.get("checked"):
        if dry_run:
            # Nothing has been written yet, so there is nothing to read back. The
            # preview step still runs: a repaired library verifies as usual.
            _line(5, "verify", "no id stored yet (--dry-run writes nothing) -> %s"
                  % check_out)
            result["steps"].append({"step": "verify", "ok": True, "report": checked_report})
            return result
        return _stop(result, 5, "verify", "no stored Bangumi id was checked")
    breaches = fail_on_breaches(checked_report, fail_on)
    detail = "%d ids checked, %d low-sim -> %s" % (
        checked_report.get("checked", 0), checked_report.get("low_similarity", 0), check_out)
    if breaches:
        _line(5, "verify", "%s (fail-on: %s)"
              % (detail, ", ".join("%s=%d" % kv for kv in breaches)), failed=True)
        result["steps"].append({"step": "verify", "ok": False, "report": checked_report})
        result.update({"exit": 1, "failed_step": "verify"})
        return result
    _line(5, "verify", detail)
    result["steps"].append({"step": "verify", "ok": True, "report": checked_report})
    return result
