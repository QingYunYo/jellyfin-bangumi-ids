# jellyfin-bangumi-ids

[![test](https://github.com/QingYunYo/jellyfin-bangumi-ids/actions/workflows/test.yml/badge.svg)](https://github.com/QingYunYo/jellyfin-bangumi-ids/actions/workflows/test.yml)

> [中文](README.md) | English

Fill in the correct `ProviderIds.Bangumi` on every episode **and every season** in Jellyfin, so the
Bangumi plugin reports progress against the right subject. It changes that one field — never your
video files, never other metadata.

## Contents

- [1. Two kinds of ID](#1-two-kinds-of-id)
- [2. Install and API key](#2-install-and-api-key)
- [3. Quick start](#3-quick-start)
- [4. The seven modes](#4-the-seven-modes)
- [5. Season IDs: why they have to be fixed too](#5-season-ids-why-they-have-to-be-fixed-too)
- [6. Speeding up with the offline archive](#6-speeding-up-with-the-offline-archive)
- [7. Safety](#7-safety)
- [8. FAQ](#8-faq)
- [9. How it works](#9-how-it-works)
- [10. Development](#10-development)

## 1. Two kinds of ID

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
| one local season, two entries | `anchor --seasons --clear-spans` clears the season ID (chapter 5) |
| `SP` in a title treated as a special | matched as `SP\d+` now (`（Sp...）` no longer misread) |

## 2. Install and API key

Standard library only, Python ≥ 3.8:

```bash
pip install git+https://github.com/QingYunYo/jellyfin-bangumi-ids.git
# local development
git clone https://github.com/QingYunYo/jellyfin-bangumi-ids.git
cd jellyfin-bangumi-ids && pip install -e .
```

This gives you `jbmid` (also `python -m jellyfin_bangumi_ids`). Create an API key in Jellyfin
(Dashboard → API Keys), then:

```bash
export JF_URL=http://127.0.0.1:8096
export JF_API_KEY=your-key
jbmid doctor          # connectivity, data source, plugin state
```

`doctor` reports whether it uses the live API or the offline archive, and whether the plugin has
`TrustExistedBangumiId` enabled. Every command also accepts `--url` / `--api-key`, plus `--ipv4`
(containers with no IPv6) and `--timeout`.

## 3. Quick start

```bash
# 1) scan the library, write a report only (add --limit 3 to try it out)
jbmid scan --library Anime --out report.json

# 2) dry run first
jbmid apply report.json --dry-run

# 3) apply for real (old values are backed up)
jbmid apply report.json --backup jbmid-backup.json

# 4) undo everything if needed
jbmid rollback jbmid-backup.json
```

```text
$ jbmid scan --library Anime --limit 3
scanning 3 series from library Anime
[1/3] OK   2.5次元的诱惑           to write 0
[2/3] OK   86-不存在的战区-        to write 0
[3/3] OK   拔作岛                  to write 0
series ok      : 3
series review  : 0
episodes       : 0 to write
```

Three numbers: `series ok` aligned, `series review` uncertain (**not written**, see `reason`),
`episodes to write` how many episodes change. Each series in the report carries `anchor` / `chain` /
`notes`; reviews explain themselves (e.g. `size mismatch 25 local vs 51 pool`).

## 4. The seven modes

| Mode | When | Writes? |
| --- | --- | --- |
| `scan` + `apply` | mostly clean library, a few shows off | report → `apply` writes |
| `season` | Bangumi's seasons don't line up with your folders | writes (has `--dry-run`) |
| `auto` | one shot: find subjects by title, align by name | writes (has `--dry-run`) |
| `special` | fix SP / OVA / specials too | report → `apply` writes |
| `anchor` | a show's anchor itself is wrong (including season IDs) | writes (has `--dry-run`) |
| `verify` | audit before/after | read-only |
| `protect` | stop the plugin from overwriting your IDs | plugin setting |

**`season`**: when the number of local seasons differs from the chain, or the order is off, say
"season N = these subjects" by hand:

```json
{"物语系列": {"1": {"subjects": [140001]}, "12": {"subjects": [138829]},
            "14": {"subjects": [475354], "sp": true}}}
```

```bash
jbmid season --map map.json --dry-run
```

**`special`**: Season 0 and episodes whose title contains `番外|OVA|OAD|SP|总集篇|特典`, matched against
Bangumi `type=1` episodes. `--clear-borrowed` clears specials that borrowed a regular episode's ID.

**`anchor`**: repin one show. Order: **episode-parent → season-ID vote → the series' own ID → title search**;
whatever comes back must pass a title check, `--force` accepts dubious values, `--clear` removes them.

**`verify`**: see [chapter 5](#5-season-ids-why-they-have-to-be-fixed-too). **`protect`**: sets the plugin's
`TrustExistedBangumiId` to `true` so metadata refreshes stop overwriting hand-written IDs.

Every sample output in both READMEs comes from `examples/` (real reports and backups, trimmed).

## 5. Season IDs: why they have to be fixed too

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
that is exactly the log comparison in chapter 1.

**Safety boundary**: `--force` only widens low confidence (fewer than 2 episodes, under 60% of the vote).
It **never** writes a majority vote for a spanning season (those are skipped), otherwise it would immediately
re-fill the half you just cleared. A single-episode season can be filled with `--force`.

Writes are read-modify-write: GET the full item → change only `ProviderIds.Bangumi` → POST → read back, and
check neighbouring fields were not dragged along; every change is also recorded in a backup that `rollback`
can restore. Season rows carry `"kind": "season"`.

## 6. Speeding up with the offline archive

After installing the Bangumi plugin and running its "update offline database" task,
`{Jellyfin DataPath}/bangumi/archive/` holds a few `.jsonlines` files. This tool reads them directly,
turning API calls into primary-key lookups:

| Operation | Live API | Offline archive (indexed) |
| --- | --- | --- |
| full `verify` | ~40 minutes | ~18 seconds |
| full `scan` | ~12 minutes | ~2 minutes the first time (builds the index), then ~19 seconds |

Lookup order: `--archive DIR` → `JBMID_ARCHIVE` → auto-detect from `DataPath` in `/System/Info`. If the
archive is missing, or an episode is not in it, the online API is used instead. The first run builds a
~150 MB SQLite index inside the archive directory (source files are read-only). The archive refreshes every
14 days; when it is stale, the live API wins.

## 7. Safety

- **One field only**: `ProviderIds.Bangumi`. No files, no other metadata, no deleted items.
- **Read-modify-write with read-back**: fetch the full item, write, read again, verify neighbours.
- **Backups everywhere**: `apply` / `anchor` / `season` / `special` produce backups; `rollback` restores them.
- **When unsure, don't write**: count mismatch, low coverage or low similarity → `review`, skipped.
- **Never overwrite blindly**: `apply` writes only episodes whose old value differs; `protect` stops the plugin too.
- **Credentials stay local**: the API key and Bangumi token are used for requests only — never stored, never uploaded.

## 8. FAQ

**Q1. `HTTP 401`**
Send `Authorization: MediaBrowser Token="key"`, not `X-Emby-Token`. `jbmid` already does; mind it if you curl yourself.

**Q2. `HTTP 404 ... "Series not found"`**
Older Jellyfin builds are inconsistent about `/Shows/{id}/Episodes`. This tool uses
`/Items?ParentId=…&IncludeItemTypes=Episode&Recursive=true` instead and does not depend on that endpoint.

**Q3. Scans are slow**
Every series means serial Bangumi requests. With the offline archive (chapter 6) a full scan takes 19 seconds;
`--limit` also helps for a first look.

**Q4. The same show appears twice**
`verify`'s `duplicate_series` lists them (usually one set of files registered under two library paths). The
tool fixes both copies and never deletes anything.

**Q5. What about SP / OVA?**
Regular episodes only by default: Season 0 and titles containing `番外|OVA|OAD|SP|总集篇|特典` are not
counted as regular episodes. Use `special` to fix them too.

**Q6. One TMDB season = two Bangumi entries**
`scan` tries season alignment first (each local season onto a contiguous run of chain subjects). If that
fails, use `season` with an explicit map, or `--seasons --clear-spans` to clear the season ID (chapter 5).

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

## 9. How it works

Data comes from exactly two places: the Jellyfin REST API and Bangumi API v0 (or the offline archive in
chapter 6).

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

## 10. Development

```bash
PYTHONPATH=src python -m unittest discover -s tests   # 87 cases, fully offline (if not pip install -e .)
```

CI runs the same suite on Python 3.8 / 3.10 / 3.12. Layout:

```text
src/jellyfin_bangumi_ids/
  cli.py       command line (scan/apply/season/auto/special/anchor/verify/rollback/protect/doctor)
  jellyfin.py  Jellyfin client (retries, ProviderIds read-modify-write)
  bangumi.py   Bangumi API v0 client
  offline.py   offline archive backend (read-only, falls back online)
  archive.py   .jsonlines -> read-only index
  scan.py      anchors, sequel chains, pools, alignment, decisions
  season_align.py  order-preserving DP: local seasons onto a run of chain subjects
  match.py     normalization, variants, similarity, order-preserving DP
  season.py    manual season maps
  anchor.py    anchor repair (series-level / season-level)
  verify.py    read-only audit
  transport.py HTTP, forced IPv4, retries
```

Releasing: bump the version in `pyproject.toml` and `__init__.py` → update `CHANGELOG.md` → tag → attach the
wheel to a GitHub release.

## License

MIT
