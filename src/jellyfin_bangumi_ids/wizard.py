"""Interactive terminal wizard.

Everything here is a thin decision layer: it collects answers, calls the same
functions the subcommands call, shows a preview, and only writes after an
explicit yes.  Nothing is duplicated logic — ``--dry-run``, backups, refresh and
rollback semantics come from :mod:`jellyfin_bangumi_ids.scan` and friends.

Entry point: ``jbmid wizard``.  Non-interactive shells are refused unless
``--yes`` is passed, so scripts keep using the subcommands directly.
"""
from __future__ import annotations

import getpass
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from . import __version__, settings
from .anchor import run_seasons
from .bangumi import Bangumi
from .jellyfin import Jellyfin
from .transport import force_ipv4
from .offline import (ArchiveIndex, OfflineBangumi, archive_hint, attempts, find_archive)
from .scan import apply_report, rollback, run_scan
from .scan import run_specials
from .sync import run_sync
from .verify import run_verify, run_verify_offline

DEFAULT_URL = "http://127.0.0.1:8096"

_T: Dict[str, Tuple[str, str]] = {
    "title": ("终端向导", "terminal wizard"),
    "menu": ("选择", "choose"),
    "back": ("回车继续…", "press enter to continue…"),
    "back_menu": ("返回", "back"),
    "bye": ("再见。", "bye."),
    "noninteractive": ("非交互模式：全部取默认值（写操作一律不执行）。",
                       "non-interactive: every default is taken (nothing is written)."),
    "nontty": ("没有可交互的终端；脚本请直接用子命令（如 jbmid sync --dry-run），"
               "或加 --yes 接受全部默认值（默认不写入）。",
               "no interactive terminal; use the subcommands in scripts, or pass --yes "
               "to accept every default (which does not write)."),
    "url": ("Jellyfin 地址", "Jellyfin URL"),
    "key": ("Jellyfin API Key", "Jellyfin API Key"),
    "nokey": ("缺少 API Key：设置环境变量 JF_API_KEY（配置文件不存 Key）",
              "missing API key: set the JF_API_KEY environment variable"),
    "conn": ("连不上 Jellyfin", "cannot reach Jellyfin"),
    "conn_hint": ("检查地址、防火墙，容器网络问题可加 --ipv4", "check the URL; try --ipv4"),
    "source_offline": ("数据源：离线档案", "data source: offline archive"),
    "source_online": ("数据源：在线 API", "data source: online API"),
    "archive_missing": ("没找到离线档案（会全程走在线 API，慢很多）",
                        "no offline archive found (everything goes online, much slower)"),
    "archive_fix": ("怎么处理档案", "what about the archive"),
    "arch_path": ("输入档案目录", "type the archive directory"),
    "arch_root": ("Jellyfin 的数据目录在宿主机的哪个位置（Docker 场景）",
                  "where Jellyfin's data directory lives on this host (Docker)"),
    "arch_skip": ("这次用在线 API", "use the online API this time"),
    "arch_tried": ("尝试过的路径：", "paths tried:"),
    "arch_save": ("记住这个路径？", "remember this path?"),
    "ask_path": ("目录", "directory"),
    "ask_root": ("宿主机目录", "host directory"),
    "not_found": ("还是没找到。", "still not found."),
    "library": ("库", "library"),
    "all_libs": ("全部库", "all libraries"),
    "limit": ("先处理多少部（留空=全部）", "how many series (empty = all)"),
    "series": ("剧集", "series"),
    "pick_series": ("选择剧集编号", "pick a series number"),
    "confirm_write": ("确认写入？", "write these changes?"),
    "bulk": ("这是批量改动，输入条数再确认", "bulk change: type the count to confirm"),
    "confirm_refresh": ("写完后刷新这些条目？", "refresh those items afterwards?"),
    "nothing": ("没有需要改动的东西。", "nothing to change."),
    "backup": ("备份", "backup"),
    "roll_cmd": ("回滚", "undo"),
    "equiv": ("等价命令", "same thing without the wizard"),
    "written": ("已写入", "written"),
    "would_write": ("会写入", "would write"),
    "cancelled": ("已取消，什么都没写。", "cancelled, nothing written."),
    "review": ("需要人工看的剧", "series needing review"),
    "verify": ("体检", "check"),
    "episodes": ("修集级 ID", "fix episode ids"),
    "seasons": ("修季级 ID", "fix season ids"),
    "specials": ("修番外 ID", "fix specials"),
    "sync": ("一条龙", "one-shot"),
    "rollback": ("回滚", "rollback"),
    "config": ("配置", "config"),
    "exit": ("退出", "exit"),
    "no_backups": ("找不到备份文件（先跑一次会写库的操作）。", "no backup files yet."),
    "pick_backup": ("选择备份编号", "pick a backup number"),
    "restore_confirm": ("确认用这个备份还原？", "restore from this backup?"),
}


def t(key: str) -> str:
    pair = _T.get(key, (key, key))
    return pair[0] if _LANG[0] == "zh" else pair[1]


_LANG = ["zh"]
_NONINTERACTIVE = [False]


def _ask(prompt: str, default: str = "") -> str:
    tail = " [%s]" % default if default else ""
    try:
        raw = input("%s%s: " % (prompt, tail))
    except EOFError:
        if _NONINTERACTIVE[0]:
            return default
        raise SystemExit(130)
    return raw.strip() or default


def _confirm(prompt: str, default: bool = False) -> bool:
    tail = " [Y/n]" if default else " [y/N]"
    try:
        raw = input("%s%s: " % (prompt, tail)).strip().lower()
    except EOFError:
        if _NONINTERACTIVE[0]:
            return default
        raise SystemExit(130)
    if not raw:
        return default
    return raw in ("y", "yes", "是", "确认")


def _choose(prompt: str, options: List[Tuple[str, str]]) -> str:
    for index, (_, label) in enumerate(options, 1):
        print("  %d) %s" % (index, label))
    while True:
        raw = _ask(prompt, "1")
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        for key, label in options:
            if raw == key:
                return key
        print("  ?")


class Session:
    def __init__(self, jf: Jellyfin, bgm, archive: Optional[str], info: Dict[str, Any],
                 assume_yes: bool, write_default: bool):
        self.jf = jf
        self.bgm = bgm
        self.archive = archive
        self.info = info
        self.assume_yes = assume_yes
        self.write_default = write_default
        self.backup_dir = os.path.join(os.getcwd(), "_local", "backups")

    def backup_path(self, kind: str) -> str:
        os.makedirs(self.backup_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return os.path.join(self.backup_dir, "%s-%s.json" % (kind, stamp))

    def report_path(self, kind: str) -> str:
        os.makedirs(self.backup_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return os.path.join(self.backup_dir, "%s-%s-report.json" % (kind, stamp))

    def confirm(self, prompt: str) -> bool:
        # --yes takes the default answer, and every write prompt defaults to no;
        # --write only flips that default, it never skips the question.
        if self.assume_yes:
            return False
        return _confirm(prompt, default=self.write_default)

    def write_allowed(self) -> bool:
        return self.write_default


def _banner(sess: Session) -> None:
    version = sess.info.get("Version") or "?"
    if sess.archive:
        source = "%s（%s）" % (t("source_offline"), sess.archive) if _LANG[0] == "zh" \
            else "%s (%s)" % (t("source_offline"), sess.archive)
    else:
        source = t("source_online")
    print("")
    print("jbmid %s   Jellyfin %s   %s" % (__version__, version, source))
    print("-" * 62)


def _open(args) -> Optional[Session]:
    url = args.url or os.environ.get("JF_URL") or settings.load().get("url") or DEFAULT_URL
    key = args.api_key or os.environ.get("JF_API_KEY") or ""
    while not key:
        key = getpass.getpass("%s: " % t("key")).strip()
        if not key:
            print(t("nokey"))
            return None
    jf = Jellyfin(url, key, timeout=getattr(args, "timeout", 20.0))
    try:
        info = jf.get("/System/Info") or {}
    except Exception as exc:  # noqa: BLE001 - a wizard must explain, not traceback
        print("%s: %s" % (t("conn"), exc))
        print(t("conn_hint"))
        return None
    archive = _archive(args, jf)
    bgm = Bangumi(timeout=max(getattr(args, "timeout", 20.0), 10))
    if archive:
        bgm = OfflineBangumi(ArchiveIndex(archive, verbose=False), bgm, label=archive)
    return Session(jf, bgm, archive, info, getattr(args, "yes", False),
                   getattr(args, "write", False))


def _archive(args, jf) -> Optional[str]:
    if getattr(args, "no_archive", False):
        return None
    configured = settings.load().get("archive")
    extra = [("config", configured)] if configured else []
    found = find_archive(jf, getattr(args, "archive", None),
                         root=getattr(args, "archive_root", None),
                         search=getattr(args, "search_archive", False), extra=extra)
    while not found:
        print("")
        print(t("archive_missing"))
        hint = archive_hint(jf)
        if hint:
            print("  %s %s" % (t("arch_tried"), hint))
        for item in attempts():
            print("  - %s (%s) -> %s" % (item["path"], item["label"], item["status"]))
        mode = _choose(t("archive_fix"),
                       [("path", t("arch_path")), ("root", t("arch_root")), ("skip", t("arch_skip"))])
        if mode == "skip":
            return None
        if mode == "path":
            found = find_archive(jf, _ask(t("ask_path")))
        else:
            found = find_archive(jf, root=_ask(t("ask_root")), search=True)
        if found and _confirm(t("arch_save"), default=True):
            settings.save({"archive": found})
            print("  config: %s" % settings.config_path())
        if not found:
            print(t("not_found"))
    return found


def _library(sess: Session) -> Optional[str]:
    try:
        names = list(sess.jf.libraries())
    except Exception:  # noqa: BLE001
        names = []
    options = [("", t("all_libs"))] + [(name, name) for name in names]
    return _choose(t("library"), options) or None


def _limit() -> Optional[int]:
    raw = _ask(t("limit"))
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


def _series(sess: Session, library: Optional[str]) -> str:
    series = sess.jf.all_series(library_name=library)
    visible = series[:40]
    if len(series) > len(visible):
        print("  (1-%d of %d)" % (len(visible), len(series)))
    for index, item in enumerate(visible, 1):
        print("  %3d) %s" % (index, item.get("Name")))
    while True:
        raw = _ask(t("pick_series"))
        if raw.isdigit() and 1 <= int(raw) <= len(visible):
            return visible[int(raw) - 1]["Id"]
        for item in visible:
            if raw and raw in (item.get("Name") or ""):
                return item["Id"]
        print("  ?")


BULK_LIMIT = 50


def _bulk_confirm(sess: Session, count: int) -> bool:
    """A change this large deserves a typed answer, not one keystroke."""
    if not sess.confirm(t("confirm_write")):
        return False
    if count <= BULK_LIMIT or sess.assume_yes:
        return True
    typed = _ask("%s (%d)" % (t("bulk"), count))
    return typed.strip() == str(count)


def _lib(library: Optional[str]) -> str:
    return " --library %s" % library if library else ""


def _print_tail(sess: Session, backup: Optional[str], equivalent: str) -> None:
    if backup:
        print("%-12s: %s" % (t("backup"), backup))
        print("%-12s: jbmid rollback %s" % (t("roll_cmd"), backup))
    print("%-12s: %s" % (t("equiv"), equivalent))


def _flow_verify(sess: Session) -> None:
    library = _library(sess)
    out = sess.report_path("verify")
    if sess.archive:
        report = run_verify_offline(sess.jf, sess.archive, library=library, out=out)
    else:
        report = run_verify(sess.jf, sess.bgm, library=library, out=out)
    counts = report.get("counts") or {}
    print("")
    for key in ("ids", "unknown", "duplicate", "low_similarity", "disorder",
                "foreign_subject", "anchor_unused", "season_ids", "season_spans"):
        if key in counts:
            print("  %-16s %s" % (key.replace("_", "-"), counts.get(key)))
    print("  %-16s %s" % ("report", out))


def _flow_episodes(sess: Session, library: Optional[str] = None,
                   series_id: Optional[str] = None) -> None:
    library = library if library is not None else _library(sess)
    limit = None if series_id else _limit()
    out = sess.report_path("scan")
    report = run_scan(sess.jf, sess.bgm, library=library, limit=limit, out=out,
                      series_ids=[series_id] if series_id else None)
    summary = report["summary"]
    print("")
    print("  %-16s %s" % ("ok", summary["series_ok"]))
    print("  %-16s %s" % ("review", summary["series_review"]))
    print("  %-16s %s" % ("to write", summary["episodes_to_write"]))
    if not summary["episodes_to_write"]:
        print(t("nothing"))
        return
    if not _bulk_confirm(sess, summary["episodes_to_write"]):
        print(t("cancelled"))
        return
    backup = sess.backup_path("episodes")
    refresh = sess.confirm(t("confirm_refresh"))
    stats = {"written": 0, "failed": 0, "skipped": 0}
    apply_report(sess.jf, report, backup_path=backup, refresh=refresh, stats=stats)
    print("")
    print("  %-16s %s" % (t("written"), stats["written"],
                           ))
    equivalent = "jbmid scan%s%s%s && jbmid apply %s" % (
        _lib(library), " --series-id %s" % series_id if series_id else "",
        " --limit %d" % limit if limit else "", out)
    _print_tail(sess, backup if os.path.exists(backup) else None, equivalent)


def _flow_seasons(sess: Session, library: Optional[str] = None,
                  series_id: Optional[str] = None) -> None:
    library = library if library is not None else _library(sess)
    ids = [series_id] if series_id else None
    plan = run_seasons(sess.jf, sess.bgm, library=library, all_series=True, dry_run=True,
                       series_ids=ids)
    planned = int(plan.get("planned") or 0)
    print("")
    print("  %-16s %s" % ("seasons to fix", planned))
    if not planned:
        print(t("nothing"))
        return
    if not _bulk_confirm(sess, planned):
        print(t("cancelled"))
        return
    backup = sess.backup_path("seasons")
    run_seasons(sess.jf, sess.bgm, library=library, all_series=True, dry_run=False,
                backup_path=backup, series_ids=ids)
    _print_tail(sess, backup if os.path.exists(backup) else None,
                "jbmid anchor --seasons --all%s%s" % (
                    _lib(library), " --series-id %s" % series_id if series_id else ""))


def _flow_specials(sess: Session, library: Optional[str] = None,
                   series_id: Optional[str] = None) -> None:
    library = library if library is not None else _library(sess)
    limit = None if series_id else _limit()
    out = sess.report_path("specials")
    report = run_specials(sess.jf, sess.bgm, library=library, limit=limit, out=out,
                          series_ids=[series_id] if series_id else None)
    summary = report["summary"]
    print("")
    print("  %-16s %s" % ("matched", summary.get("specials_matched", 0)))
    print("  %-16s %s" % ("borrowed", summary.get("specials_cleared", 0)))
    print("  %-16s %s" % ("to write", summary.get("episodes_to_write", 0)))
    if not summary.get("episodes_to_write") and not summary.get("specials_cleared"):
        print(t("nothing"))
        return
    if not _bulk_confirm(sess, summary.get("episodes_to_write", 0)):
        print(t("cancelled"))
        return
    backup = sess.backup_path("specials")
    apply_report(sess.jf, report, backup_path=backup)
    _print_tail(sess, backup if os.path.exists(backup) else None,
                "jbmid special%s%s && jbmid apply %s" % (
                    _lib(library), " --series-id %s" % series_id if series_id else "", out))


def _flow_sync(sess: Session) -> None:
    library = _library(sess)
    limit = _limit()
    backup_dir = sess.backup_dir
    os.makedirs(backup_dir, exist_ok=True)
    # preview first: the same pipeline, writing nothing
    preview = run_sync(sess.jf, sess.bgm, archive=sess.archive, library=library, limit=limit,
                       dry_run=True, backup_dir=backup_dir)
    print("")
    print("  %-16s %s" % ("exit", preview.get("exit")))
    for step in preview.get("steps") or []:
        print("  %-16s %s" % (step.get("step"), "ok" if step.get("ok") else step.get("error")))
    if not sess.confirm(t("confirm_write")):
        print(t("cancelled"))
        _print_tail(sess, None, "jbmid sync%s%s --dry-run" % (
            _lib(library), " --limit %d" % limit if limit else ""))
        return
    result = run_sync(sess.jf, sess.bgm, archive=sess.archive, library=library, limit=limit,
                      dry_run=False, backup_dir=backup_dir)
    print("")
    print("  %-16s %s" % ("exit", result.get("exit")))
    for step in result.get("steps") or []:
        print("  %-16s %s" % (step.get("step"), "ok" if step.get("ok") else step.get("error")))
    _print_tail(sess, result.get("backup"),
                "jbmid sync%s%s" % (_lib(library), " --limit %d" % limit if limit else ""))


def _is_backup(path: str) -> bool:
    """A backup is a list of rows with item_id/new; reports are not."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return False
    return isinstance(data, list) and all(isinstance(row, dict) and "item_id" in row for row in data)


def _flow_rollback(sess: Session) -> None:
    if not os.path.isdir(sess.backup_dir):
        print(t("no_backups"))
        return
    names = sorted((n for n in os.listdir(sess.backup_dir)
                    if n.endswith(".json") and _is_backup(os.path.join(sess.backup_dir, n))),
                   reverse=True)
    if not names:
        print(t("no_backups"))
        return
    for index, name in enumerate(names[:15], 1):
        print("  %3d) %s" % (index, name))
    raw = _ask(t("pick_backup"))
    if not (raw.isdigit() and 1 <= int(raw) <= min(15, len(names))):
        print("  ?")
        return
    path = os.path.join(sess.backup_dir, names[int(raw) - 1])
    rollback(sess.jf, path, dry_run=True)
    try:
        with open(path, encoding="utf-8") as fh:
            rows = len(json.load(fh))
    except (OSError, ValueError):
        rows = 0
    if not _bulk_confirm(sess, rows):
        print(t("cancelled"))
        return
    rollback(sess.jf, path)
    _print_tail(sess, None, "jbmid rollback %s" % path)


def _flow_config(sess: Session) -> None:
    data = settings.load()
    print("")
    print("  config: %s" % settings.config_path())
    for key in settings.KEYS:
        print("  %-13s: %s" % (key, data.get(key) or "(unset)"))
    mode = _choose(t("config"), [("archive", "archive"), ("archive_root", "archive_root"),
                                 ("url", "url"), ("unset", "--unset"), ("back", t("back_menu"))])
    if mode == "back":
        return
    if mode == "unset":
        key = _choose("key", [(k, k) for k in settings.KEYS])
        settings.unset(key)
        print("  unset: %s" % key)
        return
    value = _ask(mode, data.get(mode, ""))
    if value:
        settings.save({mode: os.path.abspath(os.path.expanduser(value)) if mode != "url" else value})
        print("  saved: %s = %s" % (mode, value))


def _flow_single(sess: Session) -> None:
    library = _library(sess)
    series_id = _series(sess, library)
    mode = _choose(t("series"), [("episodes", t("episodes")), ("seasons", t("seasons")),
                                 ("specials", t("specials"))])
    if mode == "episodes":
        _flow_episodes(sess, library=library, series_id=series_id)
    elif mode == "seasons":
        _flow_seasons(sess, library=library, series_id=series_id)
    else:
        _flow_specials(sess, library=library, series_id=series_id)


MENU = [
    ("1", "verify", "体检（verify + 报告）"),
    ("2", "episodes", "修集级 ID（scan → apply）"),
    ("3", "seasons", "修季级 ID（anchor --seasons）"),
    ("4", "specials", "修番外 ID（special → apply）"),
    ("5", "sync", "一条龙（sync）"),
    ("6", "rollback", "回滚（从备份还原）"),
    ("7", "single", "单剧 / 单库"),
    ("8", "config", "配置（config）"),
    ("0", "exit", "退出"),
]

MENU_EN = [
    ("1", "verify", "check (verify)"),
    ("2", "episodes", "fix episode ids (scan -> apply)"),
    ("3", "seasons", "fix season ids (anchor --seasons)"),
    ("4", "specials", "fix specials (special -> apply)"),
    ("5", "sync", "one-shot (sync)"),
    ("6", "rollback", "rollback from a backup"),
    ("7", "single", "one series / one library"),
    ("8", "config", "config"),
    ("0", "exit", "exit"),
]


def _menu() -> None:
    for key, _, label in MENU if _LANG[0] == "zh" else MENU_EN:
        print("  %s  %s" % (key, label))


def run(args) -> int:
    if getattr(args, "lang", None):
        _LANG[0] = "en" if args.lang.startswith("en") else "zh"
    if not sys.stdin.isatty() and not getattr(args, "yes", False):
        print(t("nontty"))
        return 2
    if getattr(args, "ipv4", False):
        force_ipv4()
    _NONINTERACTIVE[0] = bool(getattr(args, "yes", False))
    if _NONINTERACTIVE[0]:
        print(t("noninteractive"))
    sess = _open(args)
    if sess is None:
        return 1
    _banner(sess)
    handlers = {
        "verify": _flow_verify,
        "episodes": _flow_episodes,
        "seasons": _flow_seasons,
        "specials": _flow_specials,
        "sync": _flow_sync,
        "rollback": _flow_rollback,
        "single": _flow_single,
        "config": _flow_config,
    }
    while True:
        print("")
        _menu()
        choice = _ask(t("menu"), "0")
        action = None
        for key, name, _ in MENU if _LANG[0] == "zh" else MENU_EN:
            if choice == key:
                action = name
                break
        if action is None:
            print("  ?")
            continue
        if action == "exit":
            print(t("bye"))
            return 0
        try:
            handlers[action](sess)
        except KeyboardInterrupt:
            print("")
            print(t("cancelled"))
            return 130
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001 - keep the menu alive
            print("  ! %s" % exc)
        if not sess.assume_yes:
            _ask(t("back"))
