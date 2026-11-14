# jellyfin-bangumi-ids

[![test](https://github.com/QingYunYo/jellyfin-bangumi-ids/actions/workflows/test.yml/badge.svg)](https://github.com/QingYunYo/jellyfin-bangumi-ids/actions/workflows/test.yml)

> [中文](README.md) | English

Fill in the correct `ProviderIds.Bangumi` on every episode **and every season** in Jellyfin, so the
Bangumi plugin reports progress against the right subject. It changes that one field — never your
video files, never other metadata.

**Just want to see it work?** Run `jbmid wizard` (`./jbmid wizard` from a checkout) and pick
"1 check" — read-only.

## Contents

- [1. Install and first run](#1-install-and-first-run)
- [2. Two kinds of ID](#2-two-kinds-of-id)
- [3. Modes and usage](#3-modes-and-usage)
- [4. Season IDs: why they have to be fixed too](#4-season-ids-why-they-have-to-be-fixed-too)
- [5. Data sources and configuration: archive, Docker, config](#5-data-sources-and-configuration-archive-docker-config)
- [6. Safety](#6-safety)
- [7. FAQ](#7-faq)
- [8. How it works](#8-how-it-works)
- [9. Development](#9-development)
- [License](#license)

## 1. Install and first run

Standard library only, Python ≥ 3.8:

```bash
pip install git+https://github.com/QingYunYo/jellyfin-bangumi-ids.git
```

If installing fails, that is fine: Debian / NAS Python ships PEP 668 (`externally-managed-environment`).
Run the bundled launcher from the checkout instead — it touches no system directory:

```bash
git clone https://github.com/QingYunYo/jellyfin-bangumi-ids.git
cd jellyfin-bangumi-ids
./jbmid               # just run it; it asks for language, URL and key first
```

Prefer a real install without touching system Python? `python3 -m venv .venv && . .venv/bin/activate && pip install -e .`

### 1.1 First run: language, address, key, archive

```bash
./jbmid               # or just jbmid once installed
```

With no config yet it goes straight into setup, four questions (the last two may be skipped):

1. **Interface language** — `zh` / `en`, remembered after the first pick; `jbmid --lang en ...`
   changes it later and stores the choice.
2. **Jellyfin URL** — the media server (port 8096 by default), **not Bangumi**; an IP is fine,
   `192.168.1.10:8096` becomes `http://192.168.1.10:8096`. It checks `/System/Info/Public` first
   (no key needed), so a wrong address never makes you retype the key.
3. **Jellyfin API key** — dashboard → API Keys → create. Typed **visibly**; after Enter you see a
   masked summary (`e76c********84d0`) and a length hint.
4. **Offline archive** (optional) — the archive directory used by the Bangumi plugin; Enter skips it.
   If skipped, it asks for **Jellyfin's data directory** instead (Windows:
   `C:\ProgramData\Jellyfin\Server\data`; Docker: the host directory mounted at `/config`),
   and derives `.../data/bangumi/archive` from it.

Paths are checked before they are stored: absolute, existing, and containing `episode.jsonlines`;
it then prints `found 694202 subjects / 1705871 episodes`. A bad path is re-asked, never written —
a relative `3` is refused instead of silently becoming `<cwd>/3`. `archive` and `archive_root`
never both take effect: storing one clears/derives the other, so exactly one path wins.

The answers are verified against the server and written to
`~/.config/jellyfin-bangumi-ids/config.json` (mode 0600), so later commands need **no environment
variables at all**. Add `--no-save-key` to keep the key off disk, `--hide-key` to stop masking while typing.

> If the directory is not writable it says "not saved" and tells you about `JBMID_CONFIG_DIR`; it never
> pretends the write worked. Later: `jbmid config` (an editor in a terminal), `jbmid config --test`.

When a connection fails it asks for the field that actually failed: an address problem re-asks the URL,
a 401/403 re-asks the key, anything else gives you a choice.

### 1.2 Then: the menu, or the subcommands

Run `jbmid` (the same as `jbmid wizard`) and you get the eight-entry menu. On a first run go
"1 check → 2 episode ids → 3 season ids", and use "6 rollback" if something looks wrong:

```text
  1  check (verify + report)
  2  fix episode ids (scan -> apply)
  3  fix season ids (anchor --seasons)
  4  fix specials (special -> apply)
  5  one-shot (sync)
  6  rollback from a backup
  7  one series
  8  config
  0  exit
```

Every write flow previews first and asks once more: **the bracket names both the keys and what Enter
picks**, and `0` always means back / cancel. Afterwards it prints the backup file, the rollback command
and the equivalent subcommand. For cron, skip the menu and use 1.3.

### 1.3 Subcommands (scripts, exact control)

```bash
jbmid scan --library Anime --limit 3 --out report.json   # report only; --library is case-insensitive
jbmid apply report.json --dry-run                        # dry run first
jbmid apply report.json --backup jbmid-backup.json       # write, old values saved
jbmid rollback jbmid-backup.json                         # one command to undo
```

```text
$ jbmid scan --library 动漫 --limit 3
scanning 3 series from library 动漫
[1/3] OK   2.5次元的诱惑           to write 0
[2/3] OK   86-不存在的战区-        to write 0
[3/3] OK   拔作岛                  to write 0
series ok      : 3
series review  : 0
episodes       : 0 to write
```

Three numbers: `series ok` can be aligned, `series review` is uncertain (**not written**, read `reason`),
`episodes to write` is the count that would change. Each series in the report carries `anchor` / `chain` /
`notes`, and `review` rows explain themselves (e.g. `size mismatch 25 local vs 51 pool`).

If more than a couple of series land in `review`, pick a mode in chapter 3; if the IDs are written but the
plugin still complains, read chapter 4 (season ids).


## 2. Two kinds of ID

Every **episode** and every **season** in Jellyfin can carry a Bangumi ID, and they do different jobs:

| Field | What it decides | How the plugin uses it |
| --- | --- | --- |
| Episode `ProviderIds.Bangumi` | whether this episode is watched | per-episode progress, `Watched` / `Default` |
| Season `ProviderIds.Bangumi` | which subject the "watching" status goes to | `PlaybackScrobbler` takes the episode's **parent (season)** as the subject |

So **fixing episodes is not enough**. With correct episode IDs and a season ID one step off, playback and
per-episode status look fine, but "watching" is recorded on the neighbouring season — and no per-episode
check can see it. This tool checks and fixes both:

```bash
jbmid scan    --library Anime                  # episodes: align by title, write a report
jbmid apply   report.json                      # episodes: apply
jbmid anchor  --library Anime --seasons --all  # seasons: repair by episode-ID vote
jbmid verify  --library Anime                  # audit both
```

Measured, same episode, from the plugin log:

```text
season ID pinned to the previous part:
  report subject #525565 status Watching     <- went to the wrong part
after clearing the season ID (the plugin falls back to this episode's own ID):
  report subject #638497 status Watching     <- correct
```

Typical symptoms: nothing happens after an episode (log spammed with `doesn't have bangumi id`), progress
syncing to a different show, one TMDB season covering two Bangumi entries (everything after the split is
off), an SP counted as a regular episode (shifting everything), manual fixes overwritten on the next refresh.

### Common misalignments

| Symptom | What the tool does |
| --- | --- |
| whole season shifted by two | `scan` aligns by title, `apply` writes (`rollback` undoes) |
| half a season without IDs | `apply` fills empty slots only |
| episode IDs pointing at another show | anchor validation + season vote; `anchor --series` to re-pin |
| broadcast order ≠ episode order | `verify` reports `disorder`; you decide |
| one local season, two entries | `anchor --seasons --clear-spans` clears the season ID (chapter 4) |
| `SP` in a title treated as a special | matched as `SP\d+` now (`（Sp...）` no longer misread) |

## 3. Modes and usage

The only hard rule for picking a mode is **whether it writes** — when in doubt, add `--dry-run`. The table
below is grouped by how much it touches; individual modes are 3.1–3.10, and
**[3.11](#311-putting-it-together-the-order-that-actually-works) is how to combine them on a real repair**.

| Group | Mode | What it does | Writes? |
| --- | --- | --- | --- |
| entry | `jbmid` (= `wizard`) | menu: check / episodes / seasons / specials / one-shot / rollback / one series / config | preview first |
| read-only | `doctor` | connectivity / data source / plugin state | read-only |
| read-only | `verify` | audit episode and season IDs | read-only |
| report only | `scan` | find anchors, align the whole library by episode title | report only |
| report only | `special` | fix Season 0 / specials / OVA | report only |
| write | `apply` | write a `scan` / `special` report into Jellyfin | writes (`--dry-run`) |
| write | `season` | declare "season N = these subjects" by hand | writes (`--dry-run`) |
| write | `auto` | find subjects by title + align by episode name, one shot | writes (`--dry-run`) |
| write | `anchor` | repair a show's series-level / season-level ID | writes (`--dry-run`) |
| write | `sync` | one run: scan → apply → season ids → specials → verify | writes (`--dry-run`) |
| undo | `rollback` | restore from a backup | writes |
| config | `protect` | stop the plugin from overwriting hand-written IDs | plugin setting |
| config | `config` | remember the archive path / server URL | writes config |

### 3.1 Just run `jbmid`: the menu is the entry point

**You do not need to remember `wizard`**: typing `jbmid` (or the checkout's `./jbmid`) *is* the menu, and
`jbmid wizard` is only the same thing spelled out — they are equivalent. Every write is previewed first
and then asked again, and the default answer is "no". With no config yet it walks you through setup
(see 1.1); `jbmid setup` redoes that.

```bash
jbmid                   # same as jbmid wizard; first run goes through setup
jbmid wizard            # the same entry point, long form
jbmid wizard --lang en  # English menu
jbmid wizard --write    # default the write prompts to yes (it still previews, still asks)
jbmid wizard --yes      # non-interactive: take every default, never write (smoke test only)
```

Eight entries: check, fix episode ids, fix season ids, fix specials, one-shot, rollback, one series,
config. On start it resolves the server URL (`--url` -> `JF_URL` -> `config` -> default) and the
offline archive (chapter 5); when no archive is found it prints the paths it tried and why, then offers
to type a path, give the host mount point, or go online.

The specials flow also asks whether to clear specials that borrow a main-episode id (default `N`,
same as `--clear-borrowed`); reports and backups land in `./_local/backups/` (`--backup-dir` / `--out-dir` change it), and after a write it asks whether to
refresh those items (default `N`, same as `--refresh`). Above 50 changes a single `y` is not enough: you have to type the count back. Restoring a backup goes
through the same threshold. Each write ends with three lines: the backup file, the
`jbmid rollback <backup>` command, and the equivalent non-interactive command you can paste into cron.
Non-interactive shells (pipes, CI) are refused with exit code 2 unless you pass `--yes`.

Interface rule: **the bracket spells out what Enter picks**, and `0` always means "back / exit /
cancel" — Enter never performs a write on your behalf. In a submenu `0` returns to the main menu (it
does not quit), and a finished flow drops you straight back into the menu.

Exit codes: `0` finished, `1` cannot reach Jellyfin or the API key was rejected, `2` no terminal and
no `--yes`, `3` input ended (a script that closed stdin), `130` Ctrl-C. A failure prints one
actionable line instead of a traceback; add `-v` to see every HTTP request, status and byte count.

### 3.2 `scan`: look before you leap

The usual entry point: for every show it finds an anchor, builds a pool, aligns by episode title and
decides — **without writing anything**.

```bash
jbmid scan --library Anime --out report.json   # whole library
jbmid scan --library Anime --limit 3            # try three shows first
```

To look at just one or two shows, pass `--series-id` (a Jellyfin item id, repeatable):

```bash
jbmid scan --series-id 9a63c5f950cf05e5ba3796722a403f27
```

Read the `reason` of every `series review`, then run `jbmid apply report.json`.

When the whole chain does not fit, `scan` takes one step back: a season that stores its own Bangumi id —
one that passes the title check and whose subject has about as many episodes — is aligned against that
subject first, while the other seasons still walk the chain (`notes` then say
`season 2 keeps its own subject 513878 (10/10 episodes)`). This fallback is used **only after the plain
chain failed**; by default the chain still decides, otherwise a season that legitimately spans two
subjects would be split into "this season owns one subject".

### 3.3 `apply` / `rollback`: land the report, or undo it

```bash
jbmid apply report.json --dry-run                 # how many episodes would change
jbmid apply report.json --backup jbmid-backup.json
jbmid apply report.json --backup b.json --refresh # also refresh the touched items
jbmid rollback jbmid-backup.json --dry-run
```

`apply` writes only episodes whose value actually changes; `rollback` restores row by row. Both support
`--dry-run`.

`--refresh` asks Jellyfin to refresh **only the items whose id just changed**
(`POST /Items/{id}/Refresh`), so the Bangumi plugin rewrites the fields it owns (such as
`OriginalTitle`) from the new episode. Omit it and nothing is refreshed. Measured on a season that had
been mapped to the previous season's episodes: the refresh changed `OriginalTitle` from the old
season's title to the correct one and left `Name` / `Overview` / `PremiereDate` untouched; locked
fields are never overwritten. `season` and `auto` accept `--refresh` too.

### 3.4 `season`: when Bangumi's seasons don't line up

Use it when the number of local seasons differs from the chain, or the order is off. The JSON says
"season N = these subjects":

```json
{"物语系列": {"1": {"subjects": [140001]}, "14": {"subjects": [475354], "sp": true}}}
```

```bash
jbmid season --map map.json --dry-run
```

`sp: true` treats that season as specials (aligns against Bangumi `type=1` episodes).

### 3.5 `auto`: the one-shot

No anchor given: it searches subjects by title, aligns by episode name and writes:

```bash
jbmid auto --library Anime --dry-run
jbmid auto --library Anime
```

Easiest to run, and the mode most worth reading: every show prints its `method`
(`name` / `season-map` / `stored` / `order`).

### 3.6 `special`: specials, OVA, recaps

Season 0 and episodes containing `番外|OVA|OAD|SP|总集篇|特典` are aligned against Bangumi `type=1`
episodes:

```bash
jbmid special --library Anime --out specials.json
jbmid apply specials.json
jbmid special --library Anime --clear-borrowed   # clear specials that borrowed a regular episode ID
```

### 3.7 `anchor`: the anchor itself is wrong

Repins a single show, and repairs season-level IDs:

```bash
jbmid anchor --series 物语系列 --dry-run                     # repin the series-level anchor
jbmid anchor --library Anime --seasons --all                 # repair season IDs
jbmid anchor --library Anime --seasons --all --clear-spans   # clear seasons that span entries
```

Lookup order: **episode-parent → season-ID vote → the series' own ID → title search**, all behind a title
check; `--force` accepts dubious values, `--clear` removes them.

### 3.8 `verify`: the read-only audit

```bash
jbmid verify --library Anime                          # one summary line + category detail
jbmid verify --library Anime --by-series              # grouped per show: which one to fix first
jbmid verify --library Anime --fail-on season-ids,dup # exit 1 on a hit (cron / CI)
```

Field meanings are in [chapter 4](#4-season-ids-why-they-have-to-be-fixed-too); `--fail-on` accepts
`unknown dup low-sim disorder foreign anchors season-ids season-spans none`.

### 3.9 `protect` / `doctor`

```bash
jbmid protect     # sets TrustExistedBangumiId = True so refreshes stop overwriting
jbmid doctor      # connectivity / data source / plugin state
```

`jbmid config` (remember the paths) is at the end of
[chapter 5](#5-data-sources-and-configuration-archive-docker-config).

Every sample output in both READMEs comes from [`examples/`](examples/README.md) (real reports and backups, trimmed, with field notes).

### 3.10 `sync`: the whole pipeline in one run

It chains the five steps of the 3.11 table: `scan` → `apply` → `anchor --seasons` → `special` → `verify`.

```bash
jbmid sync --library Anime --dry-run              # prints every step, writes nothing
jbmid sync --library Anime --refresh              # really run, refresh the touched items
jbmid sync --series-id 9a63c5f950cf05e5ba3796722a403f27   # just one show
```

Only episodes that `scan` marked `ok` are written; a failing step stops the pipeline instead of carrying a
half-applied state forward. `--stop-on-review` stops right after `scan` if anything needs review, and
`--fail-on season-ids,dup` turns the final audit into an exit code for cron / CI. `--backup-dir` and
`--out-dir` choose where backups and intermediate reports go.

### 3.11 Putting it together: the order that actually works

In practice these modes are **used together**, not one and done. On a first pass, walk this order:

| Step | Command | Why it sits here |
| --- | --- | --- |
| 1 survey | `jbmid doctor` → `jbmid verify --library Anime` | confirm connectivity and the offline archive; `verify` gives the baseline (unknown / dup / disorder / season-ids) |
| 2 episodes | `jbmid scan --library Anime --out report.json` → `jbmid apply report.json` | episode IDs feed the season vote, so they come first |
| 3 seasons | `jbmid anchor --library Anime --seasons --all` (add `--clear-spans` for spanning seasons) | the majority vote reads the episode IDs written in step 2 |
| 4 specials | `jbmid special --library Anime --out specials.json` → `jbmid apply specials.json` | specials that borrowed a regular ID pollute the pool, so they come after episodes are stable |
| 5 re-audit | `jbmid verify --library Anime` | numbers should converge: `unknown 0`, `season-ids 0`, `season-spans 0` (`dup` only the duplicated entries themselves) |
| 6 lock | `jbmid protect` | lock last; locking first also blocks your own later fixes |

Four mixed scenarios:

**A. Fresh library / big repair** (`verify` is all red) → steps 1 → 2 → 3 → 4 → 5 → 6, all of them.

**B. Only a few shows are off** (`verify` numbers are small) → `scan` (use `--limit` if you like) → `apply` →
read `anchor --seasons`, fix only the seasons it names → `verify`. Skip `special`.

**C. Only specials are wrong** (episodes are fine) → `special --clear-borrowed` → `apply specials.json` →
`verify`. Do not touch episode IDs.

**D. One TMDB season = two Bangumi entries** → run `scan` first (it attempts season alignment); if it still
reviews, pin the mapping with `season --map`; if a *single* local season spans two entries, clear it with
`anchor --seasons --all --clear-spans` (clear, do not guess); finish with `verify`.

Why the order cannot be reversed: **episodes → seasons** (the vote reads episode IDs), **episodes → specials**
(borrowed IDs make the pool dirty), **fix → lock** (`protect` too early also blocks your own fixes).

## 4. Season IDs: why they have to be fixed too

When reporting "watching", the Bangumi plugin takes the subject from **the episode's parent (season)**, not
from the episode's own ID. Therefore:

- all episode IDs correct → per-episode watched state is correct;
- season ID pointing at the neighbouring entry → "watching" is always wrong, and a per-episode check
  (`verify`'s title comparison) cannot see it.

`verify` reports the two problems separately:

```text
offline check: 2095 ids | unknown 0 | dup 3 | low-sim 278 | disorder 22 | foreign 5
               | anchors 0 | season-ids 0 | season-spans 0
```

`season-ids` = the season ID disagrees with the majority vote of its own episode IDs; `season-spans` = a
season spans two subjects yet still carries a season ID. Two fixes:

```bash
# 1) repair season IDs by episode vote (needs >=60% and >=2 episodes)
jbmid anchor --library Anime --seasons --all --dry-run
jbmid anchor --library Anime --seasons --all

# 2) a season spanning two subjects has no single correct ID: clear it
jbmid anchor --library Anime --seasons --all --clear-spans --dry-run
jbmid anchor --library Anime --seasons --all --clear-spans
```

```text
$ jbmid anchor --library Anime --seasons --all --clear-spans --dry-run
86-不存在的战区-
  season 1   id 302189   -> (cleared) (12/23 episodes) [clear: spanning season]
进击的巨人
  season 3   id 217300   -> (cleared) (12/22 episodes) [clear: spanning season]
17 season id(s) off, 0 written (dry run)
```

**Why clear instead of picking one**: 12 episodes belong to part A, 13 to part B, and a season has room for
one ID. Write A and B's 13 episodes report to A; write B and A's 12 report to B. With the ID cleared,
`PlaybackScrobbler` falls back to "look up the subject from this episode's own ID", which is right for both —
that is exactly the log comparison in chapter 2.

**Safety boundary**: `--force` only widens low confidence (fewer than 2 episodes, under 60% of the vote).
It **never** writes a majority vote for a spanning season (those are skipped), otherwise it would immediately
re-fill the half you just cleared. A single-episode season can be filled with `--force`.

Writes are read-modify-write: GET the full item → change only `ProviderIds.Bangumi` → POST → read back, and
check neighbouring fields were not dragged along; every change is also recorded in a backup that `rollback`
can restore. Season rows carry `"kind": "season"`.

## 5. Data sources and configuration: archive, Docker, config

After installing the Bangumi plugin and running its "update offline database" task,
`{Jellyfin DataPath}/bangumi/archive/` holds a few `.jsonlines` files. This tool reads them directly,
turning API calls into primary-key lookups:

| Operation | Live API | Offline archive (indexed) |
| --- | --- | --- |
| full `verify` | ~40 minutes | ~18 seconds |
| full `scan` | ~12 minutes | ~2 minutes the first time (builds the index), then ~19 seconds |

Lookup order (first hit wins):

1. `--archive DIR` (works on every command)
2. `JBMID_ARCHIVE` environment variable
3. the config file: `jbmid config --archive DIR`
4. a copy inside the checkout (`_local/archive`)
5. `--archive-root DIR` / `JBMID_ARCHIVE_ROOT`: map container paths onto the host (below)
6. Jellyfin's `DataPath` from `/System/Info`, when that path is readable **on this machine**
7. `--search-archive` / `JBMID_ARCHIVE_SEARCH=1`: a bounded walk under `--archive-root` (fallback, slower)

**Jellyfin in Docker**: the plugin sees container paths such as `/config/data/bangumi/archive`, which do
not exist on the host. Point the tool at the host directory and it maps them for you:

```bash
jbmid config --archive-root /volume1/docker/jellyfin   # your mount point
jbmid doctor
```

Mapping tries the whole container path under that root, then with the first segment dropped, then the last
three segments only (`data/bangumi/archive`). If the tree is deeper, add `--search-archive`
(a bounded walk: 5 levels, 3 seconds).

**A broken path never aborts detection**: when `JBMID_ARCHIVE` points at a deleted directory, the tool
records the attempt and keeps looking instead of silently running online for 40 minutes. `jbmid doctor`
prints every path it tried and why it failed (`missing` / `unreadable`) — fix it with one
`jbmid config --archive DIR`.

### 5.1 Remember the paths: `jbmid config`

```bash
jbmid config --url http://127.0.0.1:8096   # Jellyfin URL (port 8096), not Bangumi
jbmid config --api-key KEY                 # store the key (plain text, file 0600, masked on display)
jbmid config --archive DIR                 # archive directory (absolute, with episode.jsonlines)
jbmid config --archive-root DIR            # Jellyfin's data directory; the archive is derived
jbmid config --lang en                     # interface language, stored for next time
jbmid config --test                        # connect once and print version / users / libraries
jbmid config                               # editor in a terminal, plain print when piped
jbmid config --unset archive               # drop one value (url/api_key/archive/archive_root/lang)
```

Stored in `~/.config/jellyfin-bangumi-ids/config.json` (`%APPDATA%` on Windows, override with
`JBMID_CONFIG_DIR`), mode 0600. The API key is only written in plain text by `jbmid setup` /
`jbmid config --api-key`; `--no-save-key` keeps it off disk entirely, and it is always masked when
displayed. A corrupt file is reported and renamed to `.bad` so the next save cannot overwrite it.
Resolution order: `--url` / `--api-key` → `JF_URL` / `JF_API_KEY` → config file → default.

Environment variables:

| Variable | Meaning | Flag |
| --- | --- | --- |
| `JF_URL` | Jellyfin base URL | `--url` |
| `JF_API_KEY` | Jellyfin API key (the only credential source; never written to the config file) | `--api-key` |
| `JBMID_ARCHIVE` | archive directory | `--archive` |
| `JBMID_ARCHIVE_ROOT` | host directory that holds Jellyfin's data mount | `--archive-root` |
| `JBMID_ARCHIVE_SEARCH` | non-empty enables the bounded walk (`0`/`off` disables) | `--search-archive` |
| `JBMID_CACHE` | SQLite index cache directory | none |
| `JBMID_CONFIG_DIR` | config file directory | none |
| `JBMID_LANG` | menu and message language (`zh` / `en`) | `--lang` |

The server URL is resolved as `--url` → `JF_URL` → `jbmid config --url` → `http://127.0.0.1:8096`.

The language follows your locale: `LC_ALL`/`LC_MESSAGES`/`LANG` starting with `zh` gives Chinese,
any other valid locale gives English, and `C`/`POSIX`/unset means Chinese. The first run asks once
and **remembers** the answer; a top-level `jbmid --lang zh|en` updates the config, while
`JBMID_LANG=zh|en` only overrides the current run.

The SQLite index lives in `~/.cache/jellyfin-bangumi-ids/` (`JBMID_CACHE` overrides it), about 150 MB, and
the source files stay read-only. The archive is maintained by the plugin's "update offline database" task (roughly every two weeks); when it is stale the live API wins.
Anything the archive cannot answer (new episodes, relations, title search) falls back to the online API.

## 6. Safety

- **One field only**: `ProviderIds.Bangumi`. No files, no other metadata, no deleted items.
- **Read-modify-write with read-back**: fetch the full item, write, read again, verify neighbours.
- **Backups everywhere**: `apply` / `anchor` / `season` / `special` produce backups; `rollback` restores them.
- **When unsure, don't write**: count mismatch, low coverage or low similarity → `review`, skipped.
- **Never overwrite blindly**: `apply` writes only episodes whose old value differs; `protect` stops the plugin too.
- **Credentials stay local**: the API key and Bangumi token are used for requests only — never stored, never uploaded.

## 7. FAQ

**Q1. `HTTP 401`**
Send `Authorization: MediaBrowser Token="key"`, not `X-Emby-Token`. `jbmid` already does; mind it if you curl yourself.

**Q2. `HTTP 404 ... "Series not found"`**
Older Jellyfin builds are inconsistent about `/Shows/{id}/Episodes`. This tool uses
`/Items?ParentId=…&IncludeItemTypes=Episode&Recursive=true` instead and does not depend on that endpoint.

**Q3. Scans are slow**
Every series means serial Bangumi requests. With the offline archive (chapter 5) a full scan takes 19 seconds;
`--limit` also helps for a first look.

**Q4. The same show appears twice**
`verify`'s `duplicate_series` lists them (usually one set of files registered under two library paths). The
tool fixes both copies and never deletes anything.

**Q5. What about SP / OVA?**
Regular episodes only by default: Season 0 and titles containing `番外|OVA|OAD|SP|总集篇|特典` are not
counted as regular episodes. Use `special` to fix them too.

**Q6. One TMDB season = two Bangumi entries**
`scan` tries season alignment first (each local season onto a contiguous run of chain subjects). If that
fails, use `season` with an explicit map, or `--seasons --clear-spans` to clear the season ID (chapter 4).

**Q7. My library uses English titles — can it still match?**
Yes. Title search uses both `Name` and `OriginalTitle`, and episode alignment splits variants such as
bracketed titles, `SxxEyy` and `#nn`.

**Q8. Does `--library` need exact case?**
No. Exact → case-insensitive → unique substring; if all fail, the available library names are printed.

**Q9. What do I do after `scan`?**
`apply report.json` is what actually writes. Run `verify` to confirm nothing broke, `protect` to prevent overwrites.

**Q10. Movies / theatrical releases?**
Episodes only. Movies have no episode concept and are out of scope; single-episode theatricals inside a
series are skipped by season alignment.

**Q11. It says `jbmid: command not found`**
`pip install` was most likely blocked by PEP 668. Use `./jbmid` from the checkout, or
`python3 -m venv .venv && . .venv/bin/activate && pip install -e .` so `jbmid` lands on PATH.

**Q12. Will the menus speak English on my English system?**
Yes. Menus, prompts and error messages follow `LANG`: `zh*` → Chinese, any other valid locale →
English, `C`/`POSIX`/unset → Chinese. Force it with `JBMID_LANG=zh|en` or `jbmid wizard --lang en`.
Matching itself is unaffected: Bangumi episode titles are Japanese/Chinese, so English-language live
action usually matches per episode while English fansubs of anime rely more on "same episode count →
ordered mapping".

**Q13. Can the wizard run from cron?**
No. Without a terminal it refuses and exits 2 — use the subcommands (e.g. `jbmid sync --library Anime`),
or `jbmid wizard --yes` (all defaults, never writes, smoke tests only).

## 8. How it works

Data comes from exactly two places: the Jellyfin REST API and Bangumi API v0 (or the offline archive in
chapter 5).

| Purpose | Endpoint |
| --- | --- |
| series / season / episode lists | `/Items`, `/Items/{id}`, `/Items?ParentId=` |
| subject info and relations | `bgm.tv/v0/subjects/{id}`, `/subjects/{id}/subjects` (sequel/prequel) |
| episode lists | `bgm.tv/v0/episodes?subject_id=…&type=0` (regular) / `type=1` (specials) |
| find a subject by title | `bgm.tv/v0/search/subjects` |

One `scan` run:

1. **Find an anchor**: the Bangumi ID on the series/season, or a title search; both must pass a title check.
2. **Build a pool**: walk sequel/prequel relations to chain related subjects, collect their regular episodes.
3. **Align titles**: normalize (NFKC, drop non-alphanumerics except kana) → split variants → order-preserving DP (similarity 0.45).
4. **Decide**: equal counts, or (close size + coverage ≥ 90% + mean similarity ≥ 0.55); otherwise `review`.
5. **Write back**: only episodes whose value changes, then read back.

**Generality**: apart from the Bangumi plugin's GUID (used by `protect` to find its config), nothing is
hard-coded — libraries, subjects and season structure are all queried at runtime, so it works on anyone's library.

**What it does not solve**: subjects missing from Bangumi; episodes whose titles are just filenames or carry
no information; shows where broadcast order differs from episode order (`verify` can only report `disorder`);
movies.

## 9. Development

```bash
PYTHONPATH=src python -m unittest discover -s tests   # 197 cases, fully offline (if not pip install -e .)
```

CI runs the same suite on Python 3.8 / 3.10 / 3.12. Layout:

```text
src/jellyfin_bangumi_ids/
  cli.py       command line (scan/apply/season/auto/special/anchor/verify/sync/rollback/protect/doctor/config/wizard)
  wizard.py    interactive menu (eight entries, preview before write, bulk threshold)
  jellyfin.py  Jellyfin client (retries, ProviderIds read-modify-write)
  bangumi.py   Bangumi API v0 client
  offline.py   offline archive backend (read-only, falls back online)
  archive.py   .jsonlines -> read-only index
  scan.py      anchors, sequel chains, pools, alignment, decisions
  season_align.py  order-preserving DP: local seasons onto a run of chain subjects
  match.py     normalization, variants, similarity, order-preserving DP
  season.py    manual season maps
  anchor.py    anchor repair (series-level / season-level)
  verify.py    read-only audit (--by-series / --fail-on)
  sync.py      one-shot pipeline: scan → apply → seasons → specials → verify
  transport.py HTTP, forced IPv4, retries
```

Releasing: bump the version in `pyproject.toml` and `__init__.py` → update `CHANGELOG.md` → tag → attach the
wheel to a GitHub release.

## License

MIT
