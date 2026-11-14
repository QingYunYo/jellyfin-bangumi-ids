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
from .transport import build_url, force_ipv4, get_json
from .offline import (ArchiveIndex, OfflineBangumi, archive_hint, attempts,
                      derive_from_root, find_archive, looks_like_archive)
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
    "online_word": ("在线 API", "online API"),
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
    "cfg_url": ("Jellyfin 地址（媒体服务器，默认 8096 端口，不是 Bangumi）",
                "Jellyfin URL (the media server, port 8096, not Bangumi)"),
    "cfg_key": ("Jellyfin API Key（控制台 → API 密钥；输入可见，可加 --hide-key）",
                "Jellyfin API Key (dashboard → API Keys; typed visibly, add --hide-key)"),
    "test": ("测试连接", "test the connection"),
    "ask_archive": ("离线档案目录（Bangumi 插件下载的 archive）",
                    "offline archive directory (the Bangumi plugin's archive)"),
    "ask_archive_root": ("宿主机上 Jellyfin 的 data 目录（Docker 场景）",
                         "host path of Jellyfin's data directory (Docker)"),
    "type_actions": ("%s，回车默认%s", "%s, Enter = %s"),
    "bad_encoding": ("这一行没读出来（编码问题），请重新输入。",
                     "this line could not be decoded, please retype."),
    "wide": ("含全角字符「%s」：请切到半角后重输（不做自动转换）。",
             "full-width character %s: switch to half-width and retype (no auto-conversion)."),
    "key_masked": ("已输入 %d 个字符：%s", "%d characters entered: %s"),
    "key_short": ("Jellyfin 的 Key 一般是 32 位，请确认没粘错。",
                  "Jellyfin keys are usually 32 characters; check the paste."),
    "key_clean": ("已去掉误粘的空白、引号或 Bearer 前缀。",
                  "trimmed stray spaces, quotes or a Bearer prefix."),
    "why_scheme": ("地址缺少 http:// 前缀", "the URL is missing the http:// prefix"),
    "why_dns": ("域名解析失败：地址写错或 DNS 不可用", "cannot resolve the host: wrong address or no DNS"),
    "why_refused": ("连接被拒绝：端口没开或服务没启动", "connection refused: wrong port or no server"),
    "why_timeout": ("连接超时：网络不通或地址不对", "timed out: unreachable or wrong address"),
    "why_401": ("Key 被拒绝（401）", "the key was rejected (401)"),
    "why_403": ("Key 权限不足（403）", "the key lacks permission (403)"),
    "why_ssl": ("HTTPS 证书有问题，可先用 http://", "TLS problem: try http:// first"),
    "why_other": ("原因：%s", "reason: %s"),
    "first": ("第一个", "the first"),
    "key_hint": ("Key 被拒绝：跑 `jbmid setup` 重输，或确认这个 Key 属于该服务器。",
                 "the key was rejected: rerun `jbmid setup`, or check that it belongs to this server."),
    "act_retry_url": ("Y=重新输入地址，n=放弃", "Y=retype the URL, n=give up"),
    "act_retry_key": ("Y=重新输入 Key，n=放弃", "Y=retype the key, n=give up"),
    "act_save": ("Y=保存到配置文件，n=只用这一次", "Y=save to the config file, n=this run only"),
    "act_fix": ("1=改地址，2=改 Key，3=放弃", "1=fix the URL, 2=fix the key, 3=give up"),
    "act_back": ("0=返回，回车默认0", "0=back, Enter = 0"),
    "act_fix_url": ("改地址", "fix the URL"),
    "act_fix_key": ("改 Key", "fix the key"),
    "give_up_short": ("放弃", "give up"),
    "no_save_any": ("不保存，这次运行先用着。", "not saved; used for this run only."),
    "url_ok": ("地址可达：%s", "the URL answers: %s"),
    "give_up": ("已取消首次设置；之后随时用 `jbmid setup` 重来。",
                "setup cancelled; run `jbmid setup` whenever you want."),
    "wrote": ("已保存", "saved"),
    "not_wrote": ("没保存", "not saved"),
    "cannot_write": ("写不进 %s（%s）；本次运行继续用这个值，退出后失效。需要长期保存就设 "
                     "JBMID_CONFIG_DIR 到可写目录，或用 sudo。",
                     "cannot write %s (%s); the value is used for this run only. Set "
                     "JBMID_CONFIG_DIR to a writable directory, or use sudo."),
    "cfg_archive": ("离线档案目录", "offline archive directory"),
    "cfg_root": ("Jellyfin 的 data 目录（Windows 默认 C:\\ProgramData\\Jellyfin\\Server\\data；"
                 "Docker 填 /config 对应的宿主机目录）",
                 "Jellyfin's data directory (Windows: C:\\ProgramData\\Jellyfin\\Server\\data; "
                 "Docker: the host directory mounted at /config)"),
    "cfg_lang": ("界面语言", "interface language"),
    "cfg_ipv4": ("网络：跳过 IPv6（本机 v6 不通时开）", "network: skip IPv6 (on when v6 hangs)"),
    "ipv4_on": ("开（只用 IPv4）", "on (IPv4 only)"),
    "ipv4_off": ("关（走默认）", "off (default)"),
    "ipv4_saved": ("已保存：IPv4 模式 %s，下次运行生效", "saved: IPv4 mode %s, takes effect next run"),
    "ask_lang": ("界面语言（中文 / English）", "interface language (中文 / English)"),
    "lang_saved": ("界面语言：%s", "interface language: %s"),
    "archive_step": ("接着配离线档案：能让扫描快 40 倍，回车跳过（走在线 API）。",
                     "next: the offline archive makes scans ~40x faster; Enter skips it (online API)."),
    "ask_archive_path": ("离线档案目录（Bangumi 插件下载的 archive；填绝对路径，回车跳过）",
                         "offline archive directory (download by the Bangumi plugin; absolute path, Enter skips)"),
    "ask_root": ("Jellyfin 的 data 目录（Windows 默认 C:\\ProgramData\\Jellyfin\\Server\\data；"
                 "Docker 填 /config 对应的宿主机目录；回车跳过）",
                 "Jellyfin's data directory (Windows: C:\\ProgramData\\Jellyfin\\Server\\data; "
                 "Docker: the host directory mounted at /config; Enter skips)"),
    "archive_ok": ("识别到 %s 个 subject / %s 个 episode", "found %s subjects / %s episodes"),
    "bad_path_abs": ("请填绝对路径，例如 /vol1/1000/Docker/Jellyfin/config/data/bangumi/archive",
                     "use an absolute path, e.g. /vol1/1000/Docker/Jellyfin/config/data/bangumi/archive"),
    "bad_path": ("目录不存在", "no such directory"),
    "bad_archive": ("这不是 Bangumi 档案目录（缺 episode.jsonlines）",
                    "not a Bangumi archive (episode.jsonlines is missing)"),
    "root_none": ("这个目录下没找到 data/bangumi/archive，换个目录或直接跳过",
                  "no data/bangumi/archive under it; try another directory or skip"),
    "root_derived": ("已推导出档案目录：%s", "derived the archive directory: %s"),
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


def detect_lang() -> str:
    """Menu language when the user did not pass --lang.

    JBMID_LANG wins, then the usual POSIX locale variables. A locale we cannot read
    (C, POSIX, empty) means "not set", not "English", so an unconfigured box keeps Chinese.
    """
    forced = (os.environ.get("JBMID_LANG") or "").strip().lower()
    if forced.startswith("zh"):
        return "zh"
    if forced.startswith("en"):
        return "en"
    for name in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = (os.environ.get(name) or "").strip().lower()
        if not value or value in ("c", "posix", "c.utf-8", "c.utf8"):
            continue
        return "en" if not value.startswith("zh") else "zh"
    return "zh"


def set_lang(value: Optional[str]) -> str:
    """Apply an explicit --lang, then JBMID_LANG, then the stored config, then the locale.

    The stored value has to be consulted here: `jbmid config` writes `lang` to disk, and a
    later `jbmid` with no flags must pick it up instead of falling back to the locale.
    """
    lang = ""
    if value:
        lang = "en" if value.lower().startswith("en") else "zh"
    else:
        forced = (os.environ.get("JBMID_LANG") or "").strip().lower()
        if forced.startswith(("zh", "en")):
            lang = "en" if forced.startswith("en") else "zh"
        else:
            try:
                stored = str(settings.load().get("lang") or "").strip().lower()
            except Exception:
                stored = ""
            if stored.startswith("en"):
                lang = "en"
            elif stored.startswith("zh"):
                lang = "zh"
            else:
                lang = detect_lang()
    _LANG[0] = lang
    return lang


def language() -> str:
    return _LANG[0]


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


def _hint(actions: str, default: str) -> str:
    """Bracket text: the actions AND what Enter picks. Both are mandatory."""
    return t("type_actions") % (actions, default)


def _wide_char(text: str) -> str:
    for ch in text:
        if "\uff01" <= ch <= "\uff5e" or ch == "\u3000":
            return ch
    return ""


def _read_line(prompt: str, ascii_only: bool = False, secret: bool = False) -> str:
    """One line of input. Never converts characters: a full-width char is an error."""
    while True:
        try:
            raw = getpass.getpass(prompt) if secret else input(prompt)
        except UnicodeDecodeError:
            print("  %s" % t("bad_encoding"))
            continue
        except EOFError:
            if _NONINTERACTIVE[0]:
                return ""
            _eof()
            return ""
        except KeyboardInterrupt:
            raise
        if ascii_only:
            wide = _wide_char(raw)
            if wide:
                print("  %s" % (t("wide") % wide))
                continue
        return raw.strip()


def _ask(prompt: str, default: str = "", hint: Optional[str] = None,
         ascii_only: bool = False, secret: bool = False) -> str:
    """A free-text answer; the bracket always says what Enter picks."""
    if hint:
        tail = "[%s]" % hint
    elif default:
        tail = "[直接回车保留当前值]" if _LANG[0] == "zh" else "[Enter keeps the current value]"
    else:
        tail = "[%s]" % t("enter_empty")
    raw = _read_line("%s%s: " % (prompt, tail), ascii_only=ascii_only, secret=secret)
    return raw or default


def _h(word: str, default: str = "0") -> str:
    return _hint("%s=%s" % (default, word), default)


def _ask_back(prompt: str) -> Optional[str]:
    """Free text where Enter (or 0) means 'go back'."""
    raw = _ask(prompt, "0", hint=_h(t("back_menu")))
    if raw in ("0", ""):
        raise _Back()
    return raw


def _confirm(prompt: str, default: bool = False, actions: Optional[str] = None) -> bool:
    word = "Y" if default else "N"
    if actions:
        tail = "[%s]" % _hint(actions, word)
    else:
        pair = "Y=%s，n=%s" % (t("yes_word"), t("no_word")) if _LANG[0] == "zh" \
            else "Y=%s, n=%s" % (t("yes_word"), t("no_word"))
        tail = "[%s]" % _hint(pair, word)
    raw = _read_line("%s%s: " % (prompt, tail)).lower()
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
            raw = _ask(prompt, "1", hint=_h(t("first"), "1"))
        if back and raw == "0":
            raise _Back()
        if raw.isdigit() and 1 <= int(raw) <= len(opts):
            return opts[int(raw) - 1][0]
        for key, label in opts:
            if raw == key:
                return key
        print("  ?")


def normalize_url(raw: str) -> str:
    """Trim, drop quotes, add http:// when the scheme is missing, drop a trailing /."""
    text = (raw or "").strip().strip("\"'")
    if not text:
        return ""
    if "://" not in text:
        text = "http://" + text
    return text.rstrip("/")


def clean_key(raw: str) -> Tuple[str, bool]:
    """Strip stray quotes/spaces and a pasted `Bearer ` prefix. Returns (key, changed)."""
    text = (raw or "").strip().strip("\"'")
    changed = text != (raw or "").strip()
    for prefix in ("Bearer ", "bearer ", "BEARER "):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            changed = True
            break
    return text, changed


def explain_conn(exc: Exception) -> str:
    text = str(exc)
    low = text.lower()
    if "unknown url type" in low:
        return t("why_scheme")
    if "name or service not known" in low or "getaddrinfo" in low or "nodename" in low:
        return t("why_dns")
    if "connection refused" in low:
        return t("why_refused")
    if "timed out" in low or "timeout" in low:
        return t("why_timeout")
    if "certificate" in low or "ssl" in low and "handshake" in low:
        return t("why_ssl")
    if "401" in text:
        return t("why_401")
    if "403" in text:
        return t("why_403")
    return t("why_other") % text


def classify_conn(exc: Exception) -> str:
    """Which field should be re-asked: 'url', 'key' or 'other'."""
    text = str(exc)
    low = text.lower()
    if "unknown url type" in low or "name or service not known" in low or "getaddrinfo" in low \
            or "nodename" in low or "connection refused" in low or "timed out" in low:
        return "url"
    if "401" in text or "403" in text:
        return "key"
    return "other"


def probe_url(url: str, timeout: float = 5.0) -> Dict[str, Any]:
    """Ask Jellyfin ``/System/Info/Public`` (no key needed) whether the URL is right."""
    return get_json(build_url(url, "/System/Info/Public"), timeout=timeout, retries=0)


def save_settings(values: Dict[str, Any]) -> bool:
    """Persist and say plainly whether it worked; never raise at the user."""
    try:
        settings.save(values)
    except OSError as exc:
        print("  %s" % (t("not_wrote") + ": " + (t("cannot_write") % (settings.config_path(), exc))))
        return False
    print("  %s: %s" % (t("wrote"), settings.config_path()))
    return True


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
    print("  " + t("status") % (sess.url or "?", sess.archive or t("online_word"), masked))
    print("-" * 62)


def _ask_url(args, current: str) -> str:
    hint = "直接回车保留当前值" if _LANG[0] == "zh" else "Enter keeps the current value"
    raw = _ask(t("url_help"), current, hint=hint, ascii_only=True)
    return normalize_url(raw) or current


def _ask_key(args) -> str:
    """Ask for the key; visible unless --hide-key, then print a masked summary."""
    raw = _read_line("%s: " % t("cfg_key"), ascii_only=True,
                     secret=bool(getattr(args, "hide_key", False)))
    key, changed = clean_key(raw)
    if key:
        print("  " + t("key_masked") % (len(key), settings.mask(key)))
        if len(key) != 32:
            print("  " + t("key_short"))
        if changed:
            print("  " + t("key_clean"))
    return key


def _abs_path(raw: str) -> Optional[str]:
    """Absolute path or nothing; a bare "3" must never become <cwd>/3."""
    text = (raw or "").strip()
    if not text:
        return None
    text = os.path.expanduser(text)
    if not os.path.isabs(text):
        return None
    return os.path.normpath(text)


def _archive_ok(path: str) -> Tuple[bool, str]:
    """Check the directory really is the plugin's archive, and say what was found."""
    if not os.path.isdir(path):
        return False, t("bad_path")
    if not looks_like_archive(path):
        return False, t("bad_archive")
    try:
        counts = ArchiveIndex(path, verbose=False).counts()
    except Exception as exc:  # noqa: BLE001 - a bad archive is a message, not a crash
        return False, "%s: %s" % (t("bad_archive"), exc)
    return True, t("archive_ok") % (counts.get("subjects", 0), counts.get("episodes", 0))


def _ask_archive_path(default: str = "") -> Optional[str]:
    """Ask until the path is absolute and really holds an archive; None = skip."""
    while True:
        try:
            raw = _ask_back(t("ask_archive_path"))
        except _Back:
            return None
        if not raw:
            return None
        path = _abs_path(raw)
        if not path:
            print("  " + t("bad_path_abs"))
            continue
        ok, detail = _archive_ok(path)
        print("  " + detail)
        if not ok:
            continue
        return path


def _ask_archive_root(default: str = "") -> Optional[str]:
    """Ask for Jellyfin's data directory and derive the archive from it."""
    while True:
        try:
            raw = _ask_back(t("ask_root"))
        except _Back:
            return None
        if not raw:
            return None
        path = _abs_path(raw)
        if not path:
            print("  " + t("bad_path_abs"))
            continue
        if not os.path.isdir(path):
            print("  " + t("bad_path"))
            continue
        found = derive_from_root(path)
        if not found:
            print("  " + t("root_none"))
            continue
        ok, detail = _archive_ok(found)
        print("  " + detail)
        if not ok:
            continue
        print("  " + t("root_derived") % found)
        return path


def _save_archive(path: str) -> bool:
    """Store the archive and drop a stale root: only one path may win."""
    if not save_settings({"archive": path}):
        return False
    if settings.load().get("archive_root"):
        try:
            settings.unset("archive_root")
        except OSError:
            pass
    return True


def _save_archive_root(root: str) -> bool:
    found = derive_from_root(root)
    if not found:
        return False
    return save_settings({"archive_root": root, "archive": found})


def _ask_lang() -> str:
    current = language()
    try:
        choice = _choose(t("ask_lang"), [("zh", "中文"), ("en", "English")],
                         back=t("back_menu"))
    except _Back:
        return current
    if choice != current:
        set_lang(choice)
        save_settings({"lang": choice})
    return choice


def _first_run(args, url: str, key: str) -> Tuple[str, str]:
    """Ask for URL + key, prove they work, re-ask the field that actually failed."""
    print("")
    print("  %s" % t("first_run"))
    _ask_lang()
    print("")
    url = _ask_url(args, url or DEFAULT_URL)
    for attempt in range(3):
        try:
            probe_url(url, timeout=min(float(getattr(args, "timeout", 20.0)), 8.0))
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 - check the address before the key
            print("  %s: %s" % (t("test_fail"), explain_conn(exc)))
            if attempt == 2 or not _confirm(t("retry"), default=True, actions=t("act_retry_url")):
                print("  %s" % t("give_up"))
                return "", ""
            url = _ask_url(args, url)
            continue
        print("  " + t("url_ok") % url)
        break
    else:
        print("  %s" % t("give_up"))
        return "", ""
    for attempt in range(3):
        key = _ask_key(args)
        if not key:
            print("  %s" % t("nokey"))
            continue
        print("  %s" % t("trying"))
        try:
            info = Jellyfin(url, key, timeout=getattr(args, "timeout", 20.0)).ping()
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 - explain, never traceback
            print("  %s: %s" % (t("test_fail"), explain_conn(exc)))
            kind = classify_conn(exc)
            if kind == "url":
                if attempt == 2 or not _confirm(t("retry"), default=True, actions=t("act_retry_url")):
                    print("  %s" % t("give_up"))
                    return "", ""
                url = _ask_url(args, url)
                continue
            if kind == "key":
                if attempt == 2 or not _confirm(t("retry"), default=True, actions=t("act_retry_key")):
                    print("  %s" % t("give_up"))
                    return "", ""
                continue
            try:
                choice = _choose(t("conn"), [("url", t("act_fix_url")),
                                             ("key", t("act_fix_key")),
                                             ("giveup", t("give_up_short"))])
            except _Back:
                return "", ""
            if choice == "giveup":
                print("  %s" % t("give_up"))
                return "", ""
            if choice == "url":
                url = _ask_url(args, url)
            continue
        print("  " + t("test_ok") % (info["version"], info["users"], info["libraries"]))
        break
    else:
        print("  %s" % t("give_up"))
        return "", ""
    if _confirm(t("save_config"), default=True, actions=t("act_save")):
        values: Dict[str, Any] = {"url": url}
        if getattr(args, "no_save_key", False):
            print("  %s (api_key)" % t("not_saved"))
        else:
            values["api_key"] = key
        save_settings(values)
    else:
        print("  %s" % t("no_save_any"))
    print("")
    print("  " + t("archive_step"))
    path = _ask_archive_path()
    if path:
        if _save_archive(path):
            print("  %s: archive = %s" % (t("wrote"), path))
    else:
        root = _ask_archive_root()
        if root and _save_archive_root(root):
            print("  %s: archive_root = %s" % (t("wrote"), root))
    return url, key


def _open(args, force_setup: bool = False) -> Optional["Session"]:
    stored = settings.load()
    url = getattr(args, "url", None) or os.environ.get("JF_URL") or stored.get("url") or DEFAULT_URL
    url = normalize_url(url) or DEFAULT_URL
    key = getattr(args, "api_key", None) or os.environ.get("JF_API_KEY") or stored.get("api_key") or ""
    key = clean_key(key)[0]
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
        print("%s: %s" % (t("conn"), explain_conn(exc)))
        kind = classify_conn(exc)
        if interactive and kind == "url":
            if _confirm(t("retry"), default=True, actions=t("act_retry_url")):
                fixed = _ask_url(args, url)
                jf = Jellyfin(fixed, key, timeout=getattr(args, "timeout", 20.0))
                try:
                    info = jf.get("/System/Info") or {}
                except Exception as exc2:  # noqa: BLE001
                    print("%s: %s" % (t("conn"), explain_conn(exc2)))
                    print(t("conn_hint"))
                    return None
                url = fixed
                if _confirm(t("save_config"), default=True, actions=t("act_save")):
                    save_settings({"url": url})
                return _session(args, jf, info, url)
        elif interactive and kind == "key":
            print(t("key_hint"))
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
    """Edit one value at a time; every path is checked before it is stored."""
    _show_config(sess)
    data = settings.load()
    while True:
        print("")
        try:
            mode = _choose(t("config"), [
                ("url", t("cfg_url")), ("api_key", t("cfg_key")),
                ("archive", t("cfg_archive")), ("archive_root", t("cfg_root")),
                ("lang", t("cfg_lang")), ("ipv4", t("cfg_ipv4")), ("test", t("test")),
                ("unset", t("cfg_unset")),
            ], back=t("back_menu"))
        except _Back:
            return
        if mode == "test":
            print("  %s" % t("trying"))
            try:
                info = sess.jf.ping()
                print("  " + t("test_ok") % (info["version"], info["users"], info["libraries"]))
            except Exception as exc:  # noqa: BLE001
                print("  %s: %s" % (t("test_fail"), explain_conn(exc)))
            continue
        if mode == "lang":
            _ask_lang()
            print("  " + t("lang_saved") % language())
            continue
        if mode == "ipv4":
            try:
                pick = _choose(t("cfg_ipv4"),
                               [("on", t("ipv4_on")), ("off", t("ipv4_off"))],
                               back=t("back_menu"))
            except _Back:
                continue
            try:
                settings.save({"ipv4": pick})
            except OSError as exc:
                print("  %s: %s" % (t("not_wrote"), exc))
                continue
            print("  " + t("ipv4_saved") % pick)
            continue
        if mode == "unset":
            try:
                key = _choose(t("cfg_unset"), [(k, k) for k in settings.KEYS], back=t("back_menu"))
            except _Back:
                continue
            try:
                settings.unset(key)
            except OSError as exc:
                print("  %s: %s" % (t("not_wrote"), exc))
                continue
            print("  unset: %s" % key)
            continue
        if mode == "api_key":
            value = _ask_key(sess_args(sess))
            if not value:
                continue
            changed_url = sess.url
            try:
                info = Jellyfin(changed_url, value, timeout=getattr(sess.jf, "timeout", 20.0)).ping()
                print("  " + t("test_ok") % (info["version"], info["users"], info["libraries"]))
            except Exception as exc:  # noqa: BLE001
                print("  %s: %s" % (t("test_fail"), explain_conn(exc)))
                if not _confirm(t("save_config"), default=False, actions=t("act_save")):
                    continue
            if save_settings({"api_key": value}):
                sess.jf = Jellyfin(changed_url, value, timeout=getattr(sess.jf, "timeout", 20.0))
            continue
        if mode in ("archive", "archive_root"):
            if mode == "archive":
                path = _ask_archive_path()
                if not path:
                    continue
                if _save_archive(path):
                    print("  %s: archive = %s" % (t("wrote"), path))
                    sess.archive = path
                    sess.bgm = OfflineBangumi(ArchiveIndex(path, verbose=False), Bangumi(), label=path)
                continue
            root = _ask_archive_root()
            if not root:
                continue
            if _save_archive_root(root):
                found = derive_from_root(root) or ""
                print("  %s: archive_root = %s" % (t("wrote"), root))
                if found:
                    sess.archive = found
                    sess.bgm = OfflineBangumi(ArchiveIndex(found, verbose=False), Bangumi(), label=found)
            continue
        hint = "直接回车保留当前值" if _LANG[0] == "zh" else "Enter keeps the current value"
        raw = _ask(t("url_help"), data.get("url") or sess.url, hint=hint, ascii_only=True)
        if not raw:
            continue
        value = normalize_url(raw)
        if not save_settings({"url": value}):
            continue
        print("  %s: url = %s" % (t("wrote"), value))
        sess.url = value
        sess.jf = Jellyfin(value, getattr(sess.jf, "api_key", ""), timeout=20.0)
        try:
            sess.info = sess.jf.get("/System/Info") or {}
        except Exception:  # noqa: BLE001
            pass


class _Args:
    hide_key = False
    timeout = 20.0
    no_save_key = False


def sess_args(sess: Session) -> _Args:
    return _Args()


def setup(args) -> int:
    set_lang(getattr(args, "lang", None))
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
    set_lang(getattr(args, "lang", None))
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
    set_lang(getattr(args, "lang", None))
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
        choice = _ask(t("menu"), "0", hint=_h(t("exit")))
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
        except OSError as exc:  # noqa: BLE001 - a file problem, not a crash
            print("  ! %s" % exc)
        except Exception as exc:  # noqa: BLE001 - keep the menu alive
            print("  ! %s: %s" % (t("test_fail"), explain_conn(exc)))
