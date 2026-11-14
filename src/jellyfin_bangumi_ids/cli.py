"""Command line entry point."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

from . import __version__
from . import settings
from .anchor import run_anchor, run_seasons
from .auto import scan_auto
from .bangumi import Bangumi
from .jellyfin import Jellyfin
from .offline import (attempts, archive_hint, ArchiveIndex, OfflineBangumi,
                      derive_from_root, find_archive, looks_like_archive)
from .scan import apply_report, log, rollback, run_scan, run_specials
from .season import load_mapping, scan_seasons
from .sync import run_sync
from .transport import HttpError, NetError, force_ipv4, set_verbose
from .verify import fail_on_breaches, run_verify, run_verify_offline
from .wizard import language, set_lang
from .wizard import config_flow as config_wizard
from .wizard import run as run_wizard
from .wizard import setup as run_setup

DEFAULT_URL = "http://127.0.0.1:8096"


def common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", default=None,
                        help="Jellyfin base URL (default: JF_URL, then the config file)")
    parser.add_argument("--api-key", default=None,
                        help="Jellyfin API key (default: JF_API_KEY, then the config file)")
    parser.add_argument("--ipv4", action="store_true",
                        help="force IPv4 lookups (fixes 20 s hangs on hosts with broken IPv6)")
    parser.add_argument("--timeout", type=float, default=20.0,
                        help="per-request timeout in seconds (default: 20)")
    parser.add_argument("--archive", metavar="DIR",
                        help="Bangumi plugin archive directory (default: auto-detect, env JBMID_ARCHIVE)")
    parser.add_argument("--archive-root", metavar="DIR",
                        help="host directory that contains Jellyfin's data mount, used to map "
                             "container paths such as /config/... (env JBMID_ARCHIVE_ROOT)")
    parser.add_argument("--search-archive", action="store_true",
                        help="also look for bangumi/archive below --archive-root (slower)")
    parser.add_argument("--no-archive", action="store_true",
                        help="ignore the offline archive and always call api.bgm.tv")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="print every HTTP request and the resolved data source")


def server_url(args: argparse.Namespace) -> str:
    url = args.url or os.environ.get("JF_URL") or settings.load().get("url") or DEFAULT_URL
    args.url = url
    return url


def api_key(args: argparse.Namespace) -> str:
    """--api-key -> JF_API_KEY -> config file -> a one-line hint, never a traceback."""
    key = getattr(args, "api_key", None) or os.environ.get("JF_API_KEY") \
        or settings.load().get("api_key") or ""
    if not key:
        raise SystemExit("missing API key: run `jbmid setup` once, pass --api-key, "
                         "or set JF_API_KEY")
    args.api_key = key
    return key


def clients(args: argparse.Namespace):
    if args.ipv4:
        force_ipv4()
    jf = Jellyfin(server_url(args), api_key(args), timeout=args.timeout)
    bgm = Bangumi(timeout=max(args.timeout, 10))
    return jf, bgm


def data_source(args: argparse.Namespace, jf) -> Optional[str]:
    """Resolved archive directory, or None when the online API is in charge."""
    if getattr(args, "no_archive", False):
        return None
    stored = settings.load()
    configured = stored.get("archive")
    extra = [("config", configured)] if configured else []
    root = getattr(args, "archive_root", None) or stored.get("archive_root")
    return find_archive(jf, getattr(args, "archive", None), root=root,
                        search=getattr(args, "search_archive", False), extra=extra)


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
    jf, _ = clients(args)
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
    jf, bgm = clients(args)
    info = jf.get("/System/Info") or {}
    print("jellyfin  : %s (%s)" % (info.get("Version"), args.url))
    archive = data_source(args, jf)
    if archive:
        try:
            index = ArchiveIndex(archive, verbose=False)
            counts = index.counts()
            bgm = OfflineBangumi(index, bgm, label=archive)
            print("archive   : %s (%d subjects, %d episodes)" % (
                archive, counts["subjects"], counts["episodes"]))
        except Exception as exc:
            print("archive   : %s (unreadable: %s)" % (archive, exc))
    else:
        hint = archive_hint(jf)
        if hint:
            print("archive   : %s (not readable from here)" % hint)
        else:
            print("archive   : none (online only)")
        for item in attempts():
            print("            tried %s (%s) -> %s" % (item["path"], item["label"], item["status"]))
        root = getattr(args, "archive_root", None) or settings.load().get("archive_root")
        if not root:
            print("            if Jellyfin runs in Docker, pass --archive-root DIR so a "
                  "container path like /config/data/bangumi/archive can be mapped")
    if not archive:
        print("config    : %s" % settings.config_path())
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


def cmd_wizard(args: argparse.Namespace) -> int:
    return run_wizard(args)


def _checked_path(raw: str, want_archive: bool) -> Optional[str]:
    """Absolute + existing; an archive must really hold the plugin's jsonlines."""
    path = os.path.expanduser(raw.strip())
    if not os.path.isabs(path):
        print("use an absolute path, e.g. /vol1/1000/Docker/Jellyfin/config/data/bangumi/archive",
              file=sys.stderr)
        return None
    path = os.path.normpath(path)
    if not os.path.isdir(path):
        print("no such directory: %s" % path, file=sys.stderr)
        return None
    if want_archive and not looks_like_archive(path):
        print("not a Bangumi archive (episode.jsonlines is missing): %s" % path, file=sys.stderr)
        return None
    return path


def cmd_config(args: argparse.Namespace) -> int:
    for key in args.unset or []:
        settings.unset(key)
        print("unset     : %s" % key)
    values = {}
    archive = getattr(args, "archive", None)
    if archive:
        path = _checked_path(archive, want_archive=True)
        if path is None:
            return 1
        values["archive"] = path
        values["archive_root"] = None  # only one path may win
    root = getattr(args, "archive_root", None)
    if root:
        root_dir = _checked_path(root, want_archive=False)
        if root_dir is None:
            return 1
        derived = derive_from_root(root_dir)
        if not derived:
            print("no data/bangumi/archive under %s" % root_dir, file=sys.stderr)
            return 1
        values["archive_root"] = root_dir
        values["archive"] = derived
        print("derived   : archive = %s" % derived)
    for key in ("url", "api_key", "lang"):
        value = getattr(args, key, None)
        if value:
            values[key] = value
    if values.get("lang"):
        set_lang(values["lang"])
    if values:
        if values.get("archive_root") is None and "archive_root" in values:
            values.pop("archive_root")
            try:
                settings.unset("archive_root")
            except OSError:
                pass
        try:
            settings.save(values)
        except OSError as exc:
            print("cannot write %s (%s); keep using JF_URL / JF_API_KEY / JBMID_ARCHIVE"
                  % (settings.config_path(), exc), file=sys.stderr)
            return 1
        print("saved     : %s" % ", ".join(sorted(values)))
    if args.test:
        info = Jellyfin(server_url(args), api_key(args),
                        timeout=getattr(args, "timeout", 20.0)).ping()
        print("jellyfin  : %s (%d users, %d libraries)" % (
            info["version"], info["users"], info["libraries"]))
        return 0
    data = settings.load()
    print("config    : %s (%s)" % (settings.config_path(),
                                   "exists" if os.path.exists(settings.config_path()) else "missing"))
    if settings.LAST_ERROR:
        print("            %s" % settings.LAST_ERROR[0])
    for key in settings.KEYS:
        value = data.get(key) or "(unset)"
        if key == "api_key":
            value = settings.mask(data.get(key, "")) or "(unset)"
        print("%-13s: %s" % (key, value))
    print("%-13s: %s" % ("url in use", server_url(args)))
    if not values and not (args.unset or []) and sys.stdin.isatty():
        return config_wizard(args)
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    return run_setup(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jbmid", description="Fix Bangumi episode ids inside Jellyfin.")
    parser.add_argument("--version", action="version", version="jbmid " + __version__)
    parser.add_argument("-v", "--verbose", action="store_true", dest="verbose_global",
                        help="print every HTTP request (also accepted after a subcommand)")
    parser.add_argument("--lang", choices=("zh", "en"),
                        help="interface language for the menus and for this run; stored for next time")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="scan a library and write a report")
    common(p)
    p.add_argument("--library", help="library name, e.g. Anime (case-insensitive)")
    p.add_argument("--limit", type=int, help="only the first N series of the library")
    p.add_argument("--threshold", type=float, default=0.45, help="name similarity gate (0-1)")
    p.add_argument("--no-search", action="store_true", help="do not search bgm by title")
    p.add_argument("--series-id", action="append", metavar="ITEM_ID",
                   help="select a series by its Jellyfin item id (repeatable); "
                        "skips the by-name lookup")
    p.add_argument("--out", default="jbmid-report.json", help="where to write the report")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("special", help="match SP/OVA episodes too (type=1 on Bangumi)")
    common(p)
    p.add_argument("--library", help="library name, e.g. Anime (case-insensitive)")
    p.add_argument("--limit", type=int, help="only the first N series of the library")
    p.add_argument("--out", default="jbmid-specials.json", help="where to write the report")
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
    p.add_argument("--backup", default="jbmid-anchor-backup.json",
                   help="where to write the undo file")
    p.add_argument("--no-backup", action="store_true", help="do not write an undo file")
    p.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    p.add_argument("--seasons", action="store_true",
                   help="repair season-level ids from the ids on their episodes")
    p.add_argument("--all", action="store_true",
                   help="with --seasons: every series in the library")
    p.add_argument("--clear-spans", action="store_true",
                   help="with --seasons: clear the id of a season that spans two subjects")
    p.set_defaults(func=cmd_anchor)

    p = sub.add_parser("apply", help="write the ids from a scan report")
    common(p)
    p.add_argument("report", help="report written by scan or special")
    p.add_argument("--backup", default="jbmid-backup.json", help="where to write the undo file")
    p.add_argument("--no-backup", action="store_true", help="do not write an undo file")
    p.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    p.add_argument("--only", help="only series whose name contains this")
    p.add_argument("--refresh", action="store_true",
                   help="after writing, ask Jellyfin to refresh the changed items "
                        "so the plugin rewrites fields such as OriginalTitle")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("season", help="map local seasons to Bangumi subjects by hand")
    common(p)
    p.add_argument("--map", required=True,
                   help="JSON: {\"series name\": {\"1\": {\"subjects\": [id, ...]}}}")
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

    p = sub.add_parser("wizard", help="interactive picker for the common flows")
    common(p)
    p.add_argument("--lang", choices=["zh", "en"], default=argparse.SUPPRESS,
                   help="menu language (also accepted before the subcommand)")
    p.add_argument("--yes", action="store_true",
                   help="non-interactive: take every default (which never writes)")
    p.add_argument("--write", action="store_true",
                   help="pre-answer the write prompts with yes (still previews first)")
    p.add_argument("--backup-dir", metavar="DIR",
                   help="where the wizard writes undo files (default: ./_local/backups)")
    p.add_argument("--out-dir", metavar="DIR",
                   help="where the wizard writes reports (default: same as --backup-dir)")
    p.add_argument("--no-save-key", action="store_true",
                   help="keep the API key out of the config file")
    p.set_defaults(func=cmd_wizard)

    p = sub.add_parser("config", help="remember the Jellyfin URL/API key and the archive path")
    p.add_argument("--api-key", help="Jellyfin API key (stored as plain text, file mode 0600)")
    p.add_argument("--test", action="store_true", help="check the stored URL and key, then exit")
    p.add_argument("--archive", metavar="DIR", help="Bangumi plugin archive directory")
    p.add_argument("--archive-root", metavar="DIR",
                   help="host directory that contains Jellyfin's data mount")
    p.add_argument("--url", help="Jellyfin base URL, e.g. http://192.168.1.10:8096")
    p.add_argument("--lang", choices=("zh", "en"), default=argparse.SUPPRESS,
                   help="interface language, stored for next time")
    p.add_argument("--unset", action="append", choices=list(settings.KEYS), metavar="KEY",
                   help="remove a stored value (url / api_key / archive / archive_root)")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("setup", help="first-run setup: Jellyfin URL, API key, offline archive")
    common(p)
    p.add_argument("--no-save-key", action="store_true",
                   help="ask for the key every run; keep it out of the config file")
    p.add_argument("--lang", choices=["zh", "en"], default=argparse.SUPPRESS,
                   help="menu language (also accepted before the subcommand)")
    p.set_defaults(func=cmd_setup)
    return parser


_EXPLAIN = {
    "zh": {
        "key": "错误：Jellyfin API Key 被拒绝（401）。到 控制台 → API 密钥 新建一个，"
               "用 --api-key 或 JF_API_KEY 传入。",
        "url404": "错误：%s 返回 404。检查地址（不要带 /web）和端口。",
        "net": "错误：连不上 %s\n       检查 --url 与容器端口；主机 IPv6 有问题时加 --ipv4",
        "nofile": "错误：%s 不存在——先 scan，再 apply 它的报告",
        "os": "错误：%s",
        "other": "错误：%s",
    },
    "en": {
        "key": "error: the Jellyfin API key was rejected (401). Create a new one under "
               "Dashboard -> API Keys and pass it as --api-key or JF_API_KEY.",
        "url404": "error: %s answered 404. Check the base URL (no /web suffix) and the port.",
        "net": "error: cannot reach %s\n       check --url and the container port; "
               "on hosts with broken IPv6 add --ipv4",
        "nofile": "error: %s does not exist -- scan first, then apply its report",
        "os": "error: %s",
        "other": "error: %s",
    },
}


def _explain(exc: Exception) -> None:
    """One actionable line per class of failure; the traceback needs -v."""
    words = _EXPLAIN["en" if language() == "en" else "zh"]
    text = str(exc)
    if isinstance(exc, HttpError):
        if exc.status == 401:
            print(words["key"], file=sys.stderr)
        elif exc.status == 404 and "/System/Info" in text:
            print(words["url404"] % text.split(" for ")[-1].split(":")[0], file=sys.stderr)
        else:
            print(words["other"] % text, file=sys.stderr)
        return
    if isinstance(exc, NetError):
        print(words["net"] % text, file=sys.stderr)
        return
    if isinstance(exc, FileNotFoundError):
        print(words["nofile"] % exc.filename, file=sys.stderr)
        return
    if isinstance(exc, OSError):
        print(words["os"] % exc, file=sys.stderr)
        return
    print(words["other"] % text, file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    raw = sys.argv[1:] if argv is None else list(argv)
    set_lang(None)  # JBMID_LANG / LANG; the wizard can still override with --lang
    if not raw:
        if sys.stdin.isatty():
            # First contact: the wizard asks for URL/key once, then shows the menu.
            return run_wizard(argparse.Namespace(
                url=None, api_key=None, ipv4=False, timeout=20.0, archive=None,
                archive_root=None, search_archive=False, no_archive=False, verbose=False,
                verbose_global=False, lang=None, yes=False, write=False,
                backup_dir=None, out_dir=None))
        parser.print_help()
        return 0
    try:
        args = parser.parse_args(raw)
        if getattr(args, "verbose", False) or getattr(args, "verbose_global", False):
            set_verbose(True)
        if getattr(args, "lang", None):
            # A top-level --lang is a preference, not a one-shot: remember it.
            set_lang(args.lang)
            try:
                settings.save({"lang": args.lang})
            except OSError:
                pass
        return args.func(args)
    except KeyboardInterrupt:
        log("interrupted")
        return 130
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        # argparse prints its own message; a raised SystemExit("...") would vanish.
        print(exc.code, file=sys.stderr)
        return 1
    except (NetError, HttpError, OSError) as exc:
        if getattr(args, "verbose", False) or getattr(args, "verbose_global", False):
            raise
        _explain(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
