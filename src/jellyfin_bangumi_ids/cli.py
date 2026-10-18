"""Command line entry point."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

from . import __version__
from .auto import scan_auto
from .bangumi import Bangumi
from .jellyfin import Jellyfin
from .scan import apply_report, log, rollback, run_scan, run_specials
from .season import load_mapping, scan_seasons
from .transport import force_ipv4
from .verify import run_verify, run_verify_offline

DEFAULT_URL = os.environ.get("JF_URL", "http://127.0.0.1:8096")
DEFAULT_KEY = os.environ.get("JF_API_KEY", "")


def common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", default=DEFAULT_URL, help="Jellyfin base URL (env JF_URL)")
    parser.add_argument("--api-key", default=DEFAULT_KEY, help="Jellyfin API key (env JF_API_KEY)")
    parser.add_argument("--ipv4", action="store_true",
                        help="force IPv4 lookups (fixes 20 s hangs on hosts with broken IPv6)")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("-v", "--verbose", action="store_true")


def clients(args: argparse.Namespace):
    if args.ipv4:
        force_ipv4()
    if not args.api_key:
        raise SystemExit("missing API key: pass --api-key or set JF_API_KEY")
    jf = Jellyfin(args.url, args.api_key, timeout=args.timeout)
    bgm = Bangumi(timeout=max(args.timeout, 10))
    return jf, bgm


def cmd_scan(args: argparse.Namespace) -> int:
    jf, bgm = clients(args)
    report = run_scan(jf, bgm, library=args.library, limit=args.limit,
                      allow_search=not args.no_search, threshold=args.threshold, out=args.out)
    summary = report["summary"]
    print("")
    print("series ok      : %d" % summary["series_ok"])
    print("series review  : %d" % summary["series_review"])
    print("episodes       : %d to write" % summary["episodes_to_write"])
    print("report         : %s" % args.out)
    if summary["episodes_to_write"]:
        print("next           : jbmid apply %s --backup jbmid-backup.json" % args.out)
    return 0


def cmd_special(args: argparse.Namespace) -> int:
    jf, bgm = clients(args)
    report = run_specials(jf, bgm, library=args.library, limit=args.limit,
                          verbose=True, out=args.out)
    summary = report["summary"]
    print("")
    print("series ok      : %d" % summary["series_ok"])
    print("series review  : %d" % summary["series_review"])
    print("specials       : %d matched" % summary["specials_matched"])
    print("episodes       : %d to write" % summary["episodes_to_write"])
    print("report         : %s" % args.out)
    if summary["episodes_to_write"]:
        print("next           : jbmid apply %s --backup jbmid-backup-sp.json" % args.out)
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    jf, _ = clients(args)
    with open(args.report, encoding="utf-8") as fh:
        report = json.load(fh)
    apply_report(jf, report, backup_path=None if args.no_backup else args.backup,
                 dry_run=args.dry_run, only=args.only)
    return 0


def cmd_season(args: argparse.Namespace) -> int:
    jf, bgm = clients(args)
    mapping = load_mapping(args.map)
    entries = scan_seasons(jf, bgm, mapping, threshold=args.threshold)
    ok = [e for e in entries if e["status"] == "ok"]
    print("")
    print("seasons ok: %d   review: %d   episodes: %d" % (
        len(ok), len(entries) - len(ok), sum(len(e["episodes"]) for e in ok)))
    if not ok:
        return 1
    apply_report(jf, {"series": ok}, backup_path=None if args.no_backup else args.backup,
                 dry_run=args.dry_run)
    return 0


def cmd_auto(args: argparse.Namespace) -> int:
    jf, bgm = clients(args)
    entries = scan_auto(jf, bgm, library=args.library, only=args.only,
                        threshold=args.threshold, limit=args.limit)
    ok = [e for e in entries if e["status"] == "ok"]
    print("")
    print("series ok: %d   review: %d   episodes: %d" % (
        len(ok), len(entries) - len(ok), sum(len(e["episodes"]) for e in ok)))
    if ok:
        apply_report(jf, {"series": ok}, backup_path=None if args.no_backup else args.backup,
                     dry_run=args.dry_run)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    if getattr(args, "archive", None):
        jf, _ = clients(args)
        report = run_verify_offline(jf, args.archive, library=args.library, limit=args.limit,
                                    threshold=args.threshold, out=args.out)
        return 0 if report["checked"] else 1
    jf, bgm = clients(args)
    report = run_verify(jf, bgm, library=args.library, limit=args.limit,
                        threshold=args.threshold, out=args.out)
    return 0 if report["checked"] else 1


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
    p.add_argument("--out", default="jbmid-report.json")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("special", help="match SP/OVA episodes too (type=1 on Bangumi)")
    common(p)
    p.add_argument("--library", help="library name, e.g. Anime (case-insensitive)")
    p.add_argument("--limit", type=int)
    p.add_argument("--out", default="jbmid-specials.json")
    p.set_defaults(func=cmd_special)

    p = sub.add_parser("apply", help="write the ids from a scan report")
    common(p)
    p.add_argument("report")
    p.add_argument("--backup", default="jbmid-backup.json")
    p.add_argument("--no-backup", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--only", help="only series whose name contains this")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("season", help="map local seasons to Bangumi subjects by hand")
    common(p)
    p.add_argument("--map", required=True)
    p.add_argument("--threshold", type=float, default=0.45)
    p.add_argument("--backup", default="jbmid-backup-season.json")
    p.add_argument("--no-backup", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_season)

    p = sub.add_parser("auto", help="find the subject by title and align by episode names")
    common(p)
    p.add_argument("--library")
    p.add_argument("--only")
    p.add_argument("--limit", type=int)
    p.add_argument("--threshold", type=float, default=0.45)
    p.add_argument("--backup", default="jbmid-backup-auto.json")
    p.add_argument("--no-backup", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_auto)

    p = sub.add_parser("verify", help="read-only check of every stored id")
    common(p)
    p.add_argument("--archive", metavar="DIR",
                   help="answer from the plugin's offline archive (*.jsonlines) instead of the API")
    p.add_argument("--library")
    p.add_argument("--limit", type=int)
    p.add_argument("--threshold", type=float, default=0.45)
    p.add_argument("--out", default="jbmid-check.json")
    p.set_defaults(func=cmd_verify)

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
