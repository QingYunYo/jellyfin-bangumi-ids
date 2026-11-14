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
    "hint": ("方括号里是直接回车时采用的默认值；0 永远是返回、退出或取消。",
             "the bracket shows what Enter picks; 0 always means back, exit or cancel."),
    "eof": ("输入流结束，已退出。", "input ended, exiting."),
    "yes_word": ("是", "yes"),
    "no_word": ("取消", "no"),
    "clear_borrowed": ("清空借用正片 ID 的番外？", "clear specials that borrow a main-episode id?"),
    "bye": ("再见。", "bye."),
    "noninteractive": ("非交互模式：全部取默认值（写操作一律不执行）。",
                       "non-interactive: every default is taken (nothing is written)."),
    "nontty": ("没有可交互的终端；脚本请直接用子命令（如 jbmid sync --dry-run），"
               "或加 --yes 接受全部默认值（默认不写入）。",
               "no interactive terminal; use the subcommands in scripts, or pass --yes "
               "to accept every default (which does not write)."),
    "url": ("Jellyfin 地址", "Jellyfin URL"),
    "key": ("Jellyfin API Key", "Jellyfin API Key"),
    "nokey": ("缺少 API Key：先跑一次 `jbmid setup`，或传 --api-key / 设 JF_API_KEY",
              "missing API key: run `jbmid setup` once, or pass --api-key / set JF_API_KEY"),
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
    "limit": ("部数", "series count"),
    "series": ("剧集", "series"),
    "pick_series": ("编号或剧名", "number or name"),
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
    "pick_backup": ("编号", "number"),
    "restore_confirm": ("确认用这个备份还原？", "restore from this backup?"),
    "enter_pick": ("直接回车默认选%s=%s", "Enter = %s (%s)"),
    "enter_empty": ("直接回车=空", "Enter = empty"),
    "all_hint": ("输a=全部", "a = all"),
    "bulk_hint": ("直接回车默认选0=取消", "Enter = 0 (cancel)"),
    "preview_failed": ("预览没通过，未写入。", "the preview failed; nothing was written."),
    "rollback_warn": ("当前已存的 ID 会被覆盖，且不会产生新备份。",
                      "current ids will be overwritten and no new backup is made."),
    "more_backups": ("只列最近 %d 个；其余用 jbmid rollback <文件>",
                     "only the newest %d are listed; use jbmid rollback <file> for the rest"),
    "bad_limit": ("请输入数字（a=全部，0=返回）", "type a number (a = all, 0 = back)"),
    "first_run": ("首次设置：三项就够，之后随时用 `jbmid config` 改。",
                  "First run: three answers, change them later with `jbmid config`."),
    "url_help": ("Jellyfin 地址（媒体服务器，不是 Bangumi 的网址）",
                 "Jellyfin URL (the media server, not Bangumi)"),
    "url_hint": ("直接回车保留当前值", "Enter keeps the current value"),
    "save_config": ("保存到配置文件？", "Save it to the config file?"),
    "saved_word": ("已保存", "saved"),
    "not_saved": ("按 --no-save-key，不把 Key 写进文件", "--no-save-key: the key stays out of the file"),
    "cfg_show": ("显示当前值", "show current values"),
    "cfg_unset": ("清空某一项", "clear one value"),
    "cfg_key": ("API Key（输入不回显）", "API Key (input is hidden)"),
    "cfg_archive": ("离线档案目录", "offline archive directory"),
    "cfg_root": ("宿主机上 Jellyfin 的 data 挂载点", "host directory holding Jellyfin's data mount"),
    "trying": ("正在验证…", "checking…"),
    "test_ok": ("连接成功：Jellyfin %s，%d 个用户，%d 个库",
                "connected: Jellyfin %s, %d users, %d libraries"),
    "test_fail": ("连接失败", "connection failed"),
    "status": ("Jellyfin %s | 数据源 %s | Key %s", "Jellyfin %s | source %s | key %s"),
    "retry": ("重试？", "Try again?"),
    "config_bad": ("（配置文件损坏，已忽略）", "(config file is broken, ignored)"),
}


def t(key: str) -> str:
    pair = _T.get(key, (key, key))
    return pair[0] if _LANG[0] == "zh" else pair[1]


_LANG = ["zh"]
_NONINTERACTIVE = [False]


class _Back(Exception):
    """The user asked to go back one level; the menu loop redraws itself."""


EOF_CODE = 3


def _eof() -> None:
    if _NONINTERACTIVE[0]:
        return
    print("")
    print(t("eof"))
    raise SystemExit(EOF_CODE)


def _ask(prompt: str, default: str = "", hint: Optional[str] = None) -> str:
    """A free-text answer; the bracket always says what Enter picks."""
    if hint:
        tail = "[%s]" % hint
    elif default:
        tail = "[%s]" % (t("enter_pick") % (default, default))
    else:
        tail = "[%s]" % t("enter_empty")
    try:
        raw = input("%s%s: " % (prompt, tail))
    except EOFError:
        if _NONINTERACTIVE[0]:
            return default
        _eof()
        return default
    return raw.strip() or default


def _h(word: str, default: str = "0") -> str:
    return t("enter_pick") % (default, word)


def _ask_back(prompt: str) -> Optional[str]:
    """Free text where Enter (or 0) means 'go back'."""
    raw = _ask(prompt, "0", hint=_h(t("back_menu")))
    if raw in ("0", ""):
        raise _Back()
    return raw


def _confirm(prompt: str, default: bool = False) -> bool:
    word = "Y" if default else "N"
    tail = "[%s]" % (t("enter_pick") % (word, t("yes_word") if default else t("no_word")))
    try:
        raw = input("%s%s: " % (prompt, tail)).strip().lower()
    except EOFError:
        if _NONINTERACTIVE[0]:
            return default
        _eof()
        return default
    if not raw:
        return default
    return raw in ("y", "yes", "是", "确认")


def _choose(prompt: str, options: List[Tuple[str, str]], back: Optional[str] = None) -> str:
    """A numbered menu. `back` adds "0) <back>" and makes Enter mean 0."""
    opts = list(options)
    for index, (_, label) in enumerate(opts, 1):
        print("  %d) %s" % (index, label))
    if back:
        print("  0) %s" % back)
    while True:
        if back:
            raw = _ask(prompt, "0", hint=_h(t("back_menu")))
        else:
            raw = _ask(prompt, "1", hint=_h("first", "1"))
        if back and raw == "0":
            raise _Back()
        if raw.isdigit() and 1 <= int(raw) <= len(opts):
            return opts[int(raw) - 1][0]
        for key, label in opts:
            if raw == key:
                return key
        print("  ?")


class Session:
    def __init__(self, jf: Jellyfin, bgm, archive: Optional[str], info: Dict[str, Any],
                 assume_yes: bool, write_default: bool, url: str = "",
                 backup_dir: Optional[str] = None, out_dir: Optional[str] = None):
        self.jf = jf
        self.url = url
        self.bgm = bgm
        self.archive = archive
        self.info = info
        self.assume_yes = assume_yes
        self.write_default = write_default
        # The wizard keeps the same default the subcommands use, but --backup-dir
        # and --out-dir are honoured so a read-only working directory is not fatal.
        self.backup_dir = os.path.abspath(os.path.expanduser(backup_dir)) if backup_dir \
            else os.path.join(os.getcwd(), "_local", "backups")
        self.out_dir = os.path.abspath(os.path.expanduser(out_dir)) if out_dir \
            else self.backup_dir

    def backup_path(self, kind: str) -> str:
        os.makedirs(self.backup_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return os.path.join(self.backup_dir, "%s-%s.json" % (kind, stamp))

    def report_path(self, kind: str) -> str:
        os.makedirs(self.out_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return os.path.join(self.out_dir, "%s-%s-report.json" % (kind, stamp))

    def confirm(self, prompt: str) -> bool:
        # --yes takes the default answer, and every write prompt defaults to no;
        # --write only flips that default, it never skips the question.
        if self.assume_yes:
            return False
        return _confirm(prompt, default=self.write_default)

def _banner(sess: Session) -> None:
    version = sess.info.get("Version") or "?"
    if sess.archive:
        source = "%s（%s）" % (t("source_offline"), sess.archive) if _LANG[0] == "zh" \
            else "%s (%s)" % (t("source_offline"), sess.archive)
    else:
        source = t("source_online")
    print("")
    print("jbmid %s   Jellyfin %s   %s" % (__version__, version, source))
    masked = settings.mask(settings.load().get("api_key", "")) or "(unset)"
    print("  " + t("status") % (sess.url or "?", sess.archive or t("source_online"), masked))
    print("-" * 62)


def _first_run(args, url: str, key: str) -> Tuple[str, str]:
    """Ask for URL + key once, prove they work, and offer to remember them."""
    print("")
    print("  %s" % t("first_run"))
    url = _ask(t("url_help"), url or DEFAULT_URL, hint=t("url_hint")) or DEFAULT_URL
    while True:
        try:
            key = getpass.getpass("%s: " % t("cfg_key")).strip()
        except (EOFError, KeyboardInterrupt):
            _eof()
            return url, key
        if not key:
            print("  %s" % t("nokey"))
            continue
        print("  %s" % t("trying"))
        try:
            info = Jellyfin(url, key, timeout=getattr(args, "timeout", 20.0)).ping()
        except Exception as exc:  # noqa: BLE001 - explain, never traceback
            print("  %s: %s" % (t("test_fail"), exc))
            if not _confirm(t("retry"), default=True):
                return url, ""
            continue
        print("  " + t("test_ok") % (info["version"], info["users"], info["libraries"]))
        break
    if _confirm(t("save_config"), default=True):
        values = {"url": url}
        if getattr(args, "no_save_key", False):
            print("  %s (api_key)" % t("not_saved"))
        else:
            values["api_key"] = key
        settings.save(values)
        print("  %s: %s" % (t("saved_word"), settings.config_path()))
    return url, key


def _open(args, force_setup: bool = False) -> Optional[Session]:
    stored = settings.load()
    url = getattr(args, "url", None) or os.environ.get("JF_URL") or stored.get("url") or DEFAULT_URL
    key = getattr(args, "api_key", None) or os.environ.get("JF_API_KEY") or stored.get("api_key") or ""
    interactive = not _NONINTERACTIVE[0] and sys.stdin.isatty()
    if force_setup or (not key and interactive):
        if not interactive:
            print(t("nokey"))
            return None
        url, key = _first_run(args, url, key)
    if not key:
        print(t("nokey"))
        return None
    jf = Jellyfin(url, key, timeout=getattr(args, "timeout", 20.0))
    try:
        info = jf.get("/System/Info") or {}
    except Exception as exc:  # noqa: BLE001 - a wizard must explain, not traceback
        print("%s: %s" % (t("conn"), exc))
        if interactive:
            fixed = _ask(t("url_help"), url, hint=t("url_hint"))
            if fixed and fixed != url:
                url = fixed
                jf = Jellyfin(url, key, timeout=getattr(args, "timeout", 20.0))
                try:
                    info = jf.get("/System/Info") or {}
                except Exception as exc2:  # noqa: BLE001
                    print("%s: %s" % (t("conn"), exc2))
                    print(t("conn_hint"))
                    return None
                if _confirm(t("save_config"), default=True):
                    settings.save({"url": url})
                return _session(args, jf, info, url)
        print(t("conn_hint"))
        return None
    return _session(args, jf, info, url)


def _session(args, jf, info, url: str) -> Session:
    archive = _archive(args, jf)
    bgm = Bangumi(timeout=max(getattr(args, "timeout", 20.0), 10))
    if archive:
        bgm = OfflineBangumi(ArchiveIndex(archive, verbose=False), bgm, label=archive)
    return Session(jf, bgm, archive, info, getattr(args, "yes", False),
                   getattr(args, "write", False), url=url,
                   backup_dir=getattr(args, "backup_dir", None),
                   out_dir=getattr(args, "out_dir", None))


def _archive(args, jf) -> Optional[str]:
    if getattr(args, "no_archive", False):
        return None
    stored = settings.load()
    configured = stored.get("archive")
    extra = [("config", configured)] if configured else []
    root = getattr(args, "archive_root", None) or stored.get("archive_root")
    found = find_archive(jf, getattr(args, "archive", None), root=root,
                         search=getattr(args, "search_archive", False), extra=extra)
    while not found:
        print("")
        print(t("archive_missing"))
        hint = archive_hint(jf)
        if hint:
            print("  %s %s" % (t("arch_tried"), hint))
        for item in attempts():
            print("  - %s (%s) -> %s" % (item["path"], item["label"], item["status"]))
        try:
            mode = _choose(t("archive_fix"),
                           [("path", t("arch_path")), ("root", t("arch_root")),
                            ("skip", t("arch_skip"))],
                           back=t("back_menu"))
            if mode == "skip":
                return None
            if mode == "path":
                found = find_archive(jf, _ask_back(t("ask_path")))
            else:
                found = find_archive(jf, root=_ask_back(t("ask_root")), search=True)
        except _Back:
            # "back" at the first screen means "go online for now".
            return None
        if found and not _NONINTERACTIVE[0] and _confirm(t("arch_save"), default=False):
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
    return _choose(t("library"), options, back=t("back_menu")) or None


def _limit() -> Optional[int]:
    """A number, "a" for all, or 0 to go back -- never guess."""
    while True:
        raw = _ask(t("limit"), "0", hint=_h(t("back_menu")) + ", " + t("all_hint"))
        if raw in ("", "0"):
            raise _Back()
        if raw.lower() == "a":
            return None
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("  ? %s" % t("bad_limit"))


def _series(sess: Session, library: Optional[str]) -> str:
    series = sess.jf.all_series(library_name=library)
    visible = series[:40]
    if len(series) > len(visible):
        print("  (1-%d / 共 %d 部)" % (len(visible), len(series)))
    for index, item in enumerate(visible, 1):
        print("  %3d) %s" % (index, item.get("Name")))
    print("    0) %s" % t("back_menu"))
    while True:
        raw = _ask(t("pick_series"), "0")
        if raw in ("", "0"):
            raise _Back()
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
    if count <= BULK_LIMIT:
        return True
    raw = _ask("%s (%d)" % (t("bulk"), count), "0", hint=t("bulk_hint"))
    return raw == str(count)


def _lib(library: Optional[str]) -> str:
    return " --library %s" % library if library else ""


def _cmd() -> str:
    """The command the user actually typed: ``./jbmid`` in a checkout, else jbmid."""
    name = os.path.basename(sys.argv[0] or "")
    if name and not name.startswith("python"):
        return name
    return "jbmid"


def _print_tail(sess: Session, backup: Optional[str], equivalent: str) -> None:
    if backup:
        print("%-12s: %s" % (t("backup"), backup))
        print("%-12s: %s rollback %s" % (t("roll_cmd"), _cmd(), backup))
    print("%-12s: %s" % (t("equiv"), equivalent))


def _flow_verify(sess: Session) -> None:
    library = _library(sess)
    out = sess.report_path("verify")
    if sess.archive:
        report = run_verify_offline(sess.jf, sess.archive, library=library, out=out)
    else:
        report = run_verify(sess.jf, sess.bgm, library=library, out=out)
    counts = {
        "ids": report.get("checked"),
        "unknown": report.get("unknown"),
        "duplicate": report.get("duplicate"),
        "low-sim": report.get("low_similarity"),
        "disorder": report.get("disorder"),
        "foreign": report.get("foreign_subject"),
        "season-ids": len(report.get("season_rows") or []),
        "spans": len(report.get("span_rows") or []),
    }
    print("")
    for key, value in counts.items():
        if value is not None:
            print("  %-16s %s" % (key, value))
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
    equivalent = "%s scan%s%s%s && %s apply %s --backup %s%s" % (
        _cmd(), _lib(library), " --series-id %s" % series_id if series_id else "",
        " --limit %d" % limit if limit else "", _cmd(), out, backup,
        " --refresh" if refresh else "")
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
                "%s anchor --seasons --all%s%s --backup %s" % (
                    _cmd(), _lib(library), " --series-id %s" % series_id if series_id else "",
                    backup))


def _flow_specials(sess: Session, library: Optional[str] = None,
                   series_id: Optional[str] = None) -> None:
    library = library if library is not None else _library(sess)
    limit = None if series_id else _limit()
    out = sess.report_path("specials")
    clear = False if sess.assume_yes else _confirm(t("clear_borrowed"), default=False)
    report = run_specials(sess.jf, sess.bgm, library=library, limit=limit, out=out,
                          series_ids=[series_id] if series_id else None,
                          clear_borrowed=clear)
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
                "%s special%s%s%s && %s apply %s --backup %s" % (
                    _cmd(), _lib(library), " --series-id %s" % series_id if series_id else "",
                    " --clear-borrowed" if clear else "", _cmd(), out, backup))


def _planned_count(result: Dict[str, Any]) -> int:
    """How many changes a sync preview promised.

    ``apply`` and ``special`` report under ``stats``; ``anchor`` keeps its counts
    under ``seasons``, so counting only ``stats`` would let a run that rewrites
    200 season ids skip the typed-count gate.
    """
    total = 0
    for step in result.get("steps") or []:
        total += int((step.get("stats") or {}).get("written") or 0)
        total += len((step.get("seasons") or {}).get("issues") or [])
    return total


def _flow_sync(sess: Session) -> None:
    library = _library(sess)
    limit = _limit()
    backup_dir = sess.backup_dir
    os.makedirs(backup_dir, exist_ok=True)
    # preview first: the same pipeline, writing nothing
    preview = run_sync(sess.jf, sess.bgm, archive=sess.archive, library=library, limit=limit,
                       dry_run=True, backup_dir=backup_dir, out_dir=backup_dir)
    print("")
    print("  %-16s %s" % ("exit", preview.get("exit")))
    for step in preview.get("steps") or []:
        print("  %-16s %s" % (step.get("step"), "ok" if step.get("ok") else step.get("error")))
    if preview.get("exit"):
        print(t("preview_failed"))
        _print_tail(sess, None, "%s sync%s%s --dry-run" % (
            _cmd(), _lib(library), " --limit %d" % limit if limit else ""))
        return
    planned = _planned_count(preview)
    if not _bulk_confirm(sess, planned):
        print(t("cancelled"))
        _print_tail(sess, None, "%s sync%s%s --dry-run" % (
            _cmd(), _lib(library), " --limit %d" % limit if limit else ""))
        return
    result = run_sync(sess.jf, sess.bgm, archive=sess.archive, library=library, limit=limit,
                      dry_run=False, backup_dir=backup_dir, out_dir=backup_dir)
    print("")
    print("  %-16s %s" % ("exit", result.get("exit")))
    for step in result.get("steps") or []:
        print("  %-16s %s" % (step.get("step"), "ok" if step.get("ok") else step.get("error")))
    backups = result.get("backups") or []
    for path in backups:
        print("%-12s: %s" % (t("backup"), path))
    _print_tail(sess, backups[0] if backups else None,
                "%s sync%s%s --backup-dir %s" % (
                    _cmd(), _lib(library), " --limit %d" % limit if limit else "", backup_dir))


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
    if len(names) > 15:
        print("  (%s)" % (t("more_backups") % 15))
    raw = _ask(t("pick_backup"), "0")
    if raw == "0":
        raise _Back()
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
    print("  %s" % t("rollback_warn"))
    if not _bulk_confirm(sess, rows):
        print(t("cancelled"))
        return
    rollback(sess.jf, path)
    _print_tail(sess, None, "%s rollback %s" % (_cmd(), path))


def _show_config(sess: Session) -> None:
    data = settings.load()
    print("")
    print("  config: %s" % settings.config_path())
    if settings.LAST_ERROR:
        print("          %s" % t("config_bad"))
    for key in settings.KEYS:
        value = data.get(key) or "(unset)"
        if key == "api_key":
            value = settings.mask(data.get(key, "")) or "(unset)"
        print("  %-13s: %s" % (key, value))
    print("  %-13s: %s" % ("url in use", sess.url or "?"))


def _flow_config(sess: Session) -> None:
    """Edit every stored value, test the connection, clear a value."""
    while True:
        _show_config(sess)
        try:
            mode = _choose(t("config"), [
                ("url", t("cfg_url")), ("api_key", t("cfg_key")),
                ("archive", t("cfg_archive")), ("archive_root", t("cfg_root")),
                ("test", t("test")), ("show", t("cfg_show")), ("unset", t("cfg_unset")),
            ], back=t("back_menu"))
        except _Back:
            return
        data = settings.load()
        if mode == "test":
            print("  %s" % t("trying"))
            try:
                info = sess.jf.ping()
                print("  " + t("test_ok") % (info["version"], info["users"], info["libraries"]))
            except Exception as exc:  # noqa: BLE001
                print("  %s: %s" % (t("test_fail"), exc))
            continue
        if mode == "show":
            continue
        if mode == "unset":
            try:
                key = _choose("key", [(k, k) for k in settings.KEYS], back=t("back_menu"))
            except _Back:
                continue
            settings.unset(key)
            print("  unset: %s" % key)
            continue
        if mode == "api_key":
            try:
                value = getpass.getpass("%s: " % t("cfg_key")).strip()
            except (EOFError, KeyboardInterrupt):
                _eof()
                return
            if not value:
                continue
            try:
                info = Jellyfin(sess.url, value, timeout=20.0).ping()
                print("  " + t("test_ok") % (info["version"], info["users"], info["libraries"]))
            except Exception as exc:  # noqa: BLE001
                print("  %s: %s" % (t("test_fail"), exc))
                if not _confirm(t("save_config"), default=False):
                    continue
            settings.save({"api_key": value})
            sess.jf = Jellyfin(sess.url, value, timeout=getattr(sess.jf, "timeout", 20.0))
            print("  %s: %s" % (t("saved_word"), settings.config_path()))
            continue
        default = data.get(mode, "") if mode != "url" else (data.get("url") or sess.url)
        value = _ask(mode, default, hint=t("url_hint"))
        if not value or value == "0":
            continue
        if mode in ("archive", "archive_root"):
            value = os.path.abspath(os.path.expanduser(value))
        settings.save({mode: value})
        print("  %s: %s = %s" % (t("saved_word"), mode, value))
        if mode == "url":
            sess.url = value
            sess.jf = Jellyfin(value, getattr(sess.jf, "api_key", ""), timeout=20.0)
            try:
                sess.info = sess.jf.get("/System/Info") or {}
            except Exception:  # noqa: BLE001
                pass
        if mode == "archive":
            sess.archive = value
            sess.bgm = OfflineBangumi(ArchiveIndex(value, verbose=False), Bangumi(), label=value)


def setup(args) -> int:
    """``jbmid setup``: ask the three questions again, even if configured."""
    try:
        sess = _open(args, force_setup=True)
    except _Back:
        return 0
    if sess is None:
        return 1
    _banner(sess)
    return 0


def config_flow(args) -> int:
    """``jbmid config`` with no flags in a terminal: the editor, then exit."""
    try:
        sess = _open(args)
    except _Back:
        return 0
    if sess is None:
        return 1
    _flow_config(sess)
    return 0


def _flow_single(sess: Session) -> None:
    library = _library(sess)
    series_id = _series(sess, library)
    mode = _choose(t("series"), [("episodes", t("episodes")), ("seasons", t("seasons")),
                                 ("specials", t("specials"))], back=t("back_menu"))
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
    ("7", "single", "单剧（按剧修）"),
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
    ("7", "single", "one series"),
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
    try:
        sess = _open(args)
    except _Back:
        # the first screen's "back" means "not now", not a crash
        print(t("bye"))
        return 0
    if sess is None:
        return 1
    _banner(sess)
    print(t("hint"))
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
        choice = _ask(t("menu"), "0", hint=_h("退出"))
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
        except _Back:
            continue
        except KeyboardInterrupt:
            print("")
            print(t("cancelled"))
            return 130
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001 - keep the menu alive
            print("  ! %s" % exc)
