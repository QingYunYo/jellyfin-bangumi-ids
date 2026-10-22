"""Command line entry point."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

from . import __version__
from .anchor import run_anchor, run_seasons
from .auto import scan_auto
from .bangumi import Bangumi
from .jellyfin import Jellyfin
from .offline import archive_hint, ArchiveIndex, OfflineBangumi, find_archive
from .scan import apply_report, log, rollback, run_scan, run_specials
from .season import load_mapping, scan_seasons
from .sync import run_sync
from .transport import force_ipv4
from .verify import fail_on_breaches, run_verify, run_verify_offline

DEFAULT_URL = os.environ.get("JF_URL", "http://127.0.0.1:8096")
DEFAULT_KEY = os.environ.get("JF_API_KEY", "")


def common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", default=DEFAULT_URL, help="Jellyfin base URL (env JF_URL)")
    parser.add_argument("--api-key", default=DEFAULT_KEY, help="Jellyfin API key (env JF_API_KEY)")
    parser.add_argument("--ipv4", action="store_true",
                        help="force IPv4 lookups (fixes 20 s hangs on hosts with broken IPv6)")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--archive", metavar="DIR",
                        help="Bangumi plugin archive directory (default: auto-detect, env JBMID_ARCHIVE)")
    parser.add_argument("--no-archive", action="store_true",
                        help="ignore the offline archive and always call api.bgm.tv")
    parser.add_argument("-v", "--verbose", action="store_true")


def clients(args: argparse.Namespace):
    if args.ipv4:
        force_ipv4()
    if not args.api_key:
        raise SystemExit("missing API key: pass --api-key or set JF_API_KEY")
    jf = Jellyfin(args.url, args.api_key, timeout=args.timeout)
    bgm = Bangumi(timeout=max(args.timeout, 10))
    return jf, bgm


def data_source(args: argparse.Namespace, jf) -> Optional[str]:
    """Resolved archive directory, or None when the online API is in charge."""
    if getattr(args, "no_archive", False):
        return None
    return find_archive(jf, getattr(args, "archive", None))


def clients_with_source(args: argparse.Namespace):
    jf, bgm = clients(args)
    archive = data_source(args, jf)
    if archive:
        index = ArchiveIndex(archive, verbose=True)
        bgm = OfflineBangumi(index, bgm, label=archive)
        print("data source    : %s" % bgm.describe(), file=sys.stderr)
    else:
        why = "--no-archive" if getattr(args, "no_archive", False) else \
            "no offline archive found; pass --archive DIR"
        print("data source    : api.bgm.tv (%s)" % why, file=sys.stderr)
    return jf, bgm


def selected_ids(args: argparse.Namespace) -> Optional[List[str]]:
    """``--series-id`` as a list, whichever shape the subcommand accepted."""
    raw = getattr(args, "series_id", None)
    if not raw:
        return None
    return raw if isinstance(raw, list) else [str(raw)]


def cmd_scan(args: argparse.Namespace) -> int:
    jf, bgm = clients_with_source(args)
    report = run_scan(jf, bgm, library=args.library, limit=args.limit,
                      allow_search=not args.no_search, threshold=args.threshold, out=args.out,
                      series_ids=selected_ids(args))
    summary = report["summary"]
    print("")
    print("series ok      : %d" % summary["series_ok"])
    print("series review  : %d" % summary["series_review"])
    print("episodes       : %d to write" % summary["episodes_to_write"])
    if summary.get("season_mismatch"):
        print("season ids     : %d season(s) point at the wrong subject "
              "(jbmid anchor --seasons --all)" % summary["season_mismatch"])
    print("report         : %s" % args.out)
    if summary["episodes_to_write"]:
        print("next           : jbmid apply %s --backup jbmid-backup.json" % args.out)
    return 0


def cmd_special(args: argparse.Namespace) -> int:
    jf, bgm = clients_with_source(args)
    report = run_specials(jf, bgm, library=args.library, limit=args.limit,
                          verbose=True, out=args.out, clear_borrowed=args.clear_borrowed,
                          series_ids=selected_ids(args))
    summary = report["summary"]
    print("")
    print("series ok      : %d" % summary["series_ok"])
    print("series review  : %d" % summary["series_review"])
    print("specials       : %d matched" % summary["specials_matched"])
    print("borrowed       : %d cleared" % summary.get("specials_cleared", 0))
    print("episodes       : %d to write" % summary["episodes_to_write"])
    print("report         : %s" % args.out)
    if summary["episodes_to_write"]:
        print("next           : jbmid apply %s --backup jbmid-backup-sp.json" % args.out)
    return 0


def cmd_anchor(args: argparse.Namespace) -> int:
    jf, bgm = clients_with_source(args)
    ids = selected_ids(args)
    if args.seasons:
        if not ids and not args.series and not args.all:
            print("--seasons needs --series NAME, --series-id ID or --all", file=sys.stderr)
            return 2
        run_seasons(jf, bgm, name=args.series, library=args.library, all_series=args.all,
                    dry_run=args.dry_run, force=args.force, clear_spans=args.clear_spans,
                    backup_path=None if args.no_backup else args.backup, series_ids=ids)
        return 0
    if not ids and not args.series:
        print("anchor needs --series NAME, --series-id ID (or --seasons --all)",
              file=sys.stderr)
        return 2
    run_anchor(jf, bgm, args.series, library=args.library, sid=args.id, clear=args.clear,
               force=args.force, dry_run=args.dry_run,
               backup_path=None if args.no_backup else args.backup,
               item_id=ids[0] if ids else None)
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    jf, _ = clients_with_source(args)
    with open(args.report, encoding="utf-8") as fh:
        report = json.load(fh)
    apply_report(jf, report, backup_path=None if args.no_backup else args.backup,
                 dry_run=args.dry_run, only=args.only, refresh=args.refresh)
    return 0


def cmd_season(args: argparse.Namespace) -> int:
    jf, bgm = clients_with_source(args)
    mapping = load_mapping(args.map)
    entries = scan_seasons(jf, bgm, mapping, threshold=args.threshold,
                           series_ids=selected_ids(args))
    ok = [e for e in entries if e["status"] == "ok"]
    print("")
    print("seasons ok: %d   review: %d   episodes: %d" % (
        len(ok), len(entries) - len(ok), sum(len(e["episodes"]) for e in ok)))
    if not ok:
        return 1
    apply_report(jf, {"series": ok}, backup_path=None if args.no_backup else args.backup,
                 dry_run=args.dry_run, refresh=args.refresh)
    return 0


def cmd_auto(args: argparse.Namespace) -> int:
    jf, bgm = clients_with_source(args)
    entries = scan_auto(jf, bgm, library=args.library, only=args.only,
                        threshold=args.threshold, limit=args.limit,
                        series_ids=selected_ids(args))
    ok = [e for e in entries if e["status"] == "ok"]
    print("")
    print("series ok: %d   review: %d   episodes: %d" % (
        len(ok), len(entries) - len(ok), sum(len(e["episodes"]) for e in ok)))
    if ok:
        apply_report(jf, {"series": ok}, backup_path=None if args.no_backup else args.backup,
                     dry_run=args.dry_run, refresh=args.refresh)
    return 0


def print_by_series(rows: List[Dict[str, Any]]) -> None:
    """Worst series first, so a run with 200 findings still names the three to fix."""
    if not rows:
        print("by series      : nothing flagged")
        return
    print("")
    print("%-34s %5s %5s %4s %4s %4s %4s %4s %6s"
          % ("series", "eps", "total", "low", "dup", "dis", "for", "unk", "cover"))
    for row in rows[:20]:
        print("%-34s %5d %5d %4d %4d %4d %4d %4d %5.0f%%"
              % ((row.get("series") or "")[:34], row.get("episodes", 0), row.get("total", 0),
                 row.get("low_similarity", 0), row.get("duplicate", 0),
                 row.get("disorder", 0), row.get("foreign_subject", 0),
                 row.get("unknown_id", 0), (row.get("coverage") or 0.0) * 100))


def cmd_verify(args: argparse.Namespace) -> int:
    jf, bgm = clients(args)
    archive = data_source(args, jf)
    ids = selected_ids(args)
    if archive:
        print("data source    : offline archive %s" % archive, file=sys.stderr)
        report = run_verify_offline(jf, archive, library=args.library, limit=args.limit,
                                    threshold=args.threshold, out=args.out, series_ids=ids)
    else:
        why = "--no-archive" if getattr(args, "no_archive", False) else \
            "no offline archive found; pass --archive DIR"
        print("data source    : api.bgm.tv (%s)" % why, file=sys.stderr)
        report = run_verify(jf, bgm, library=args.library, limit=args.limit,
                            threshold=args.threshold, out=args.out, series_ids=ids)
    if args.by_series:
        print_by_series(report.get("by_series") or [])
    code = 0 if report["checked"] else 1
    if args.fail_on:
        breaches = fail_on_breaches(report, args.fail_on)
        if breaches:
            print("fail-on        : " + ", ".join("%s=%d" % kv for kv in breaches))
            code = 1
    return code


def cmd_sync(args: argparse.Namespace) -> int:
    jf, bgm = clients_with_source(args)
    archive = data_source(args, jf)
    result = run_sync(jf, bgm, archive=archive, library=args.library,
                      series_ids=selected_ids(args), limit=args.limit,
                      threshold=args.threshold, allow_search=not args.no_search,
                      dry_run=args.dry_run, refresh=args.refresh,
                      stop_on_review=args.stop_on_review, backup_dir=args.backup_dir,
                      out_dir=args.out_dir, fail_on=args.fail_on,
                      clear_spans=args.clear_spans, force=args.force)
    return int(result.get("exit") or 0)


def cmd_rollback(args: argparse.Namespace) -> int:
    jf, _ = clients(args)
    rollback(jf, args.backup, dry_run=args.dry_run)
    return 0


def cmd_protect(args: argparse.Namespace) -> int:
    jf, _ = clients(args)
    config = jf.patch_plugin_configuration(TrustExistedBangumiId=not args.off)
    print("TrustExistedBangumiId = %s" % config.get("TrustExistedBangumiId"))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    jf, bgm = clients_with_source(args)
    info = jf.get("/System/Info") or {}
    print("jellyfin  : %s (%s)" % (info.get("Version"), args.url))
    archive = data_source(args, jf)
    if archive:
        try:
            index = ArchiveIndex(archive, verbose=False)
            counts = index.counts()
            print("archive   : %s (%d subjects, %d episodes)" % (
                archive, counts["subjects"], counts["episodes"]))
        except Exception as exc:
            print("archive   : %s (unreadable: %s)" % (archive, exc))
    else:
        hint = archive_hint(jf)
        if hint:
            print("archive   : %s (not readable from here; pass --archive DIR)"
                  % hint)
        else:
            print("archive   : none (online only)")
    libs = jf.libraries()
    print("libraries : %d (%s)" % (len(libs), ", ".join(libs)) if libs else "libraries : none")
    start = time.time()
    try:
        subject = bgm.subject(1671)
        print("bgm.tv    : ok %.2fs (%s)" % (time.time() - start, subject.get("name_cn") or subject.get("name")))
    except Exception as exc:
        print("bgm.tv    : FAILED %s" % exc)
        print("            try --ipv4, or fix DNS/proxy for api.bgm.tv")
        return 1
    config = jf.plugin_configuration()
    if config:
        print("plugin    : TrustExistedBangumiId=%s ReportPlaybackStatus=%s" % (
            config.get("TrustExistedBangumiId"), config.get("ReportPlaybackStatusToBangumi")))
    else:
        print("plugin    : Bangumi plugin not found or not configured")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jbmid", description="Fix Bangumi episode ids inside Jellyfin.")
    parser.add_argument("--version", action="version", version="jbmid " + __version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="scan a library and write a report")
    common(p)
    p.add_argument("--library", help="library name, e.g. Anime (case-insensitive)")
    p.add_argument("--limit", type=int)
    p.add_argument("--threshold", type=float, default=0.45, help="name similarity gate (0-1)")
    p.add_argument("--no-search", action="store_true", help="do not search bgm by title")
    p.add_argument("--series-id", action="append", metavar="ITEM_ID",
                   help="select a series by its Jellyfin item id (repeatable); "
                        "skips the by-name lookup")
    p.add_argument("--out", default="jbmid-report.json")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("special", help="match SP/OVA episodes too (type=1 on Bangumi)")
    common(p)
    p.add_argument("--library", help="library name, e.g. Anime (case-insensitive)")
    p.add_argument("--limit", type=int)
    p.add_argument("--out", default="jbmid-specials.json")
    p.add_argument("--series-id", action="append", metavar="ITEM_ID",
                   help="select a series by its Jellyfin item id (repeatable)")
    p.add_argument("--clear-borrowed", action="store_true",
                   help="clear SP ids that merely borrow a main episode's id")
    p.set_defaults(func=cmd_special)

    p = sub.add_parser("anchor", help="set or repair the Bangumi id on a series")
    common(p)
    p.add_argument("--library")
    p.add_argument("--series")
    p.add_argument("--series-id", metavar="ITEM_ID",
                   help="select the series by its Jellyfin item id (skips the by-name lookup)")
    p.add_argument("--id", type=int, help="explicit Bangumi subject id")
    p.add_argument("--clear", action="store_true", help="remove the series-level id")
    p.add_argument("--force", action="store_true", help="accept an id that fails the title check")
    p.add_argument("--backup", default="jbmid-anchor-backup.json")
    p.add_argument("--no-backup", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--seasons", action="store_true",
                   help="repair season-level ids from the ids on their episodes")
    p.add_argument("--all", action="store_true",
                   help="with --seasons: every series in the library")
    p.add_argument("--clear-spans", action="store_true",
                   help="with --seasons: clear the id of a season that spans two subjects")
    p.set_defaults(func=cmd_anchor)

    p = sub.add_parser("apply", help="write the ids from a scan report")
    common(p)
    p.add_argument("report")
    p.add_argument("--backup", default="jbmid-backup.json")
    p.add_argument("--no-backup", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--only", help="only series whose name contains this")
    p.add_argument("--refresh", action="store_true",
                   help="after writing, ask Jellyfin to refresh the changed items "
                        "so the plugin rewrites fields such as OriginalTitle")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("season", help="map local seasons to Bangumi subjects by hand")
    common(p)
    p.add_argument("--map", required=True)
    p.add_argument("--series-id", metavar="ITEM_ID",
                   help="only this series (by Jellyfin item id); the map is keyed by name")
    p.add_argument("--threshold", type=float, default=0.45)
    p.add_argument("--backup", default="jbmid-backup-season.json")
    p.add_argument("--no-backup", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--refresh", action="store_true",
                   help="after writing, refresh the changed items (see apply --refresh)")
    p.set_defaults(func=cmd_season)

    p = sub.add_parser("auto", help="find the subject by title and align by episode names")
    common(p)
    p.add_argument("--library")
    p.add_argument("--only")
    p.add_argument("--series-id", action="append", metavar="ITEM_ID",
                   help="select a series by its Jellyfin item id (repeatable)")
    p.add_argument("--limit", type=int)
    p.add_argument("--threshold", type=float, default=0.45)
    p.add_argument("--backup", default="jbmid-backup-auto.json")
    p.add_argument("--no-backup", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--refresh", action="store_true",
                   help="after writing, refresh the changed items (see apply --refresh)")
    p.set_defaults(func=cmd_auto)

    p = sub.add_parser("verify", help="read-only check of every stored id")
    common(p)
    p.add_argument("--library")
    p.add_argument("--limit", type=int)
    p.add_argument("--threshold", type=float, default=0.45)
    p.add_argument("--series-id", action="append", metavar="ITEM_ID",
                   help="select a series by its Jellyfin item id (repeatable)")
    p.add_argument("--by-series", action="store_true",
                   help="aggregate the findings per series, worst first")
    p.add_argument("--fail-on", metavar="KEYS",
                   help="comma separated counters that fail the run when > 0 "
                        "(unknown,dup,low-sim,disorder,foreign,anchors,season-ids,spans; "
                        "none disables the gate)")
    p.add_argument("--out", default="jbmid-check.json")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("sync", help="scan, apply, seasons, specials and verify in one run")
    common(p)
    p.add_argument("--library")
    p.add_argument("--series-id", action="append", metavar="ITEM_ID",
                   help="select a series by its Jellyfin item id (repeatable)")
    p.add_argument("--limit", type=int)
    p.add_argument("--threshold", type=float, default=0.45,
                   help="name similarity gate for scan and verify (0-1)")
    p.add_argument("--no-search", action="store_true",
                   help="do not search bgm by title while scanning")
    p.add_argument("--dry-run", action="store_true",
                   help="print every step, write nothing to Jellyfin")
    p.add_argument("--refresh", action="store_true",
                   help="refresh the changed items after writing (see apply --refresh)")
    p.add_argument("--stop-on-review", action="store_true",
                   help="stop after scan when any series needs review")
    p.add_argument("--backup-dir", help="where the backup files go (default: cwd)")
    p.add_argument("--out-dir", help="where the JSON reports go (default: cwd)")
    p.add_argument("--fail-on", metavar="KEYS",
                   help="comma separated verify counters that fail the run when > 0 "
                        "(none disables the gate)")
    p.add_argument("--clear-spans", action="store_true",
                   help="with the season step: clear ids of seasons spanning two subjects")
    p.add_argument("--force", action="store_true",
                   help="with the season step: write even low confidence votes")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("rollback", help="restore ids from a backup file")
    common(p)
    p.add_argument("backup")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_rollback)

    p = sub.add_parser("protect", help="set TrustExistedBangumiId so rescans keep manual ids")
    common(p)
    p.add_argument("--off", action="store_true", help="turn the guard off")
    p.set_defaults(func=cmd_protect)

    p = sub.add_parser("doctor", help="check connectivity and plugin state")
    common(p)
    p.set_defaults(func=cmd_doctor)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        log("interrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
