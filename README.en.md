# jellyfin-bangumi-ids

**Fix the Bangumi episode IDs in your Jellyfin library, in bulk.**

![tests](https://github.com/QingYunYo/jellyfin-bangumi-ids/actions/workflows/test.yml/badge.svg)

> [中文](README.md) | English

A zero-dependency CLI that repairs `ProviderIds.Bangumi` on Jellyfin episodes. When that ID is
wrong, the Bangumi plugin either reports nothing at all (log line: `doesn't have bangumi id`) or
reports your progress to a different show. The tool scans your library, aligns episodes **by
title** (not by episode number), writes the IDs back one by one, and leaves a backup you can roll
back with a single command.

---

## Contents

1. [Symptoms: you might need this](#1-symptoms-you-might-need-this)
2. [What it does](#2-what-it-does)
3. [Install](#3-install)
4. [Prepare an API key](#4-prepare-an-api-key)
5. [Quick start](#5-quick-start)
   - [5.1 First run](#51-first-run)
   - [5.2 Writing and rolling back](#52-writing-and-rolling-back)
6. [Speed it up with the offline archive](#6-speed-it-up-with-the-offline-archive)
7. [Modes in detail](#7-modes-in-detail)
   - [7.1 `scan` — find anchors automatically](#71-scan--find-anchors-automatically)
   - [7.2 `season` — you say which subjects form a season](#72-season--you-say-which-subjects-form-a-season)
   - [7.3 `auto` — least work, most need to check the results](#73-auto--least-work-most-need-to-check-the-results)
   - [7.4 `special` — fix bonus episodes too](#74-special--fix-bonus-episodes-too)
   - [7.5 `anchor` — repair the anchor of a single show](#75-anchor--repair-the-anchor-of-a-single-show)
   - [7.6 `verify` — read-only health check](#76-verify--read-only-health-check)
   - [7.7 `protect` — stop a later refresh from overwriting your IDs](#77-protect--stop-a-later-refresh-from-overwriting-your-ids)
8. [Field notes: real misalignments I hit on my own library](#8-field-notes-real-misalignments-i-hit-on-my-own-library)
   - [8.1 A whole season shifted by two](#81-a-whole-season-shifted-by-two)
   - [8.2 Only half the season had IDs](#82-only-half-the-season-had-ids)
   - [8.3 The series ID pointed at another work](#83-the-series-id-pointed-at-another-work)
   - [8.4 Broadcast order is not episode order](#84-broadcast-order-is-not-episode-order)
   - [8.5 One local season, two subjects](#85-one-local-season-two-subjects)
   - [8.6 Incomplete seasons and titles that never match](#86-incomplete-seasons-and-titles-that-never-match)
   - [8.7 A title containing `SP` was misread](#87-a-title-containing-sp-was-misread)
   - [8.8 Shapes I have not hit, but the tool guards against](#88-shapes-i-have-not-hit-but-the-tool-guards-against)
9. [Safety](#9-safety)
10. [FAQ](#10-faq)
11. [Where the data comes from](#11-where-the-data-comes-from)
12. [How it works](#12-how-it-works)
    - [12.1 The five-stage pipeline](#121-the-five-stage-pipeline)
    - [12.2 What alignment looks like](#122-what-alignment-looks-like)
    - [12.3 Shapes that season alignment solves](#123-shapes-that-season-alignment-solves)
    - [12.4 When it actually writes](#124-when-it-actually-writes)
13. [Generality: will it work on someone else's library?](#13-generality-will-it-work-on-someone-elses-library)
14. [What it doesn't solve](#14-what-it-doesnt-solve)
15. [Development](#15-development)
    - [15.1 Tests and CI](#151-tests-and-ci)
    - [15.2 Layout](#152-layout)
    - [15.3 Releasing](#153-releasing)
16. [License](#16-license)

---

## 1. Symptoms: you might need this

- You finish an episode and nothing shows up on Bangumi; the log keeps saying
  `item "..." (#...) doesn't have bangumi id, ignored`.
- Progress *does* sync — to the **wrong show**. For example every episode in a season points at
  some other series.
- A show is one season on TMDB but Bangumi splits it into "part 1 / part 2", so everything after
  episode 12 is off by a fixed amount.
- A special (SP / OVA / episode 0) got treated as a regular episode, shifting every later episode
  by one.
- You fixed one ID by hand, and the next metadata refresh overwrote it.

## 2. What it does

Every Jellyfin episode carries a `ProviderIds.Bangumi` value, and that number is the only thing
the Bangumi plugin looks at when reporting playback. This tool fills that number in correctly —
**and touches nothing else**.

Seven modes; pick one based on how messy your library is (each has real input and output below):

| Mode | When to use | Writes? |
| --- | --- | --- |
| `scan` | Most shows are fine, only a handful are wrong | writes a report; `apply` writes to Jellyfin |
| `season` | Bangumi's season split does not match your folders at all | directly (`--dry-run` available) |
| `auto` | One shot: find subjects by title, align by episode title | directly (`--dry-run` available) |
| `special` | You want SP / OVA / recaps synced too | writes a report; `apply` writes to Jellyfin |
| `anchor` | The anchor (Bangumi ID on the series/season) is itself wrong | directly (`--dry-run` available) |
| `verify` | Check which IDs look broken, before or after a fix | read-only |
| `protect` | After fixing, stop the plugin overwriting your IDs | changes a plugin setting |

`apply` and `rollback` are generic: the former writes a report into Jellyfin, the latter restores
from a backup.

## 3. Install

Standard library only, Python ≥ 3.8.

```bash
pip install git+https://github.com/QingYunYo/jellyfin-bangumi-ids.git
# or for local development
git clone https://github.com/QingYunYo/jellyfin-bangumi-ids.git
cd jellyfin-bangumi-ids && pip install -e .
```

You get a `jbmid` command (equivalently `python -m jellyfin_bangumi_ids`).

## 4. Prepare an API key

Jellyfin dashboard → Administration → API Keys → New, give it a name (say `jbmid`), then:

```bash
export JF_URL=http://127.0.0.1:8096
export JF_API_KEY=your-key
jbmid doctor
```

`doctor` reports the Jellyfin version, the libraries, whether bgm.tv is reachable, the plugin
settings, and whether the offline archive was found (`archive : …`; if it cannot be read it tells
you to pass `--archive DIR`). The output looks like this:

```text
$ jbmid doctor
data source    : offline archive /path/to/bangumi/archive (episodes=1705871, subjects=694202)
jellyfin  : 12.2.0 (http://127.0.0.1:8096)
archive   : /path/to/bangumi/archive (694202 subjects, 1705871 episodes)
libraries : 8 (电视剧, 电影, 动漫, 动漫电影, 合集, JAV, Playlists, 音乐)
bgm.tv    : ok 0.00s (化物语)
plugin    : TrustExistedBangumiId=True ReportPlaybackStatus=True
```

Everything green before you go further. The `plugin` line shows what `protect` would set.

## 5. Quick start

### 5.1 First run

```bash
# 1) scan the "Anime" library and write a report (writes nothing to Jellyfin)
jbmid scan --library 动漫 --out report.json

# 2) read three numbers: series ok / series review / episodes to write
#    add --limit 5 to start small

# 3) dry-run first to see how many episodes would change
jbmid apply report.json --dry-run

# 4) for real (old values are backed up to jbmid-backup.json)
jbmid apply report.json --backup jbmid-backup.json

# 5) something went wrong → one command to roll back
jbmid rollback jbmid-backup.json
```

A first scan of three shows, in full:

```text
$ jbmid scan --library 动漫 --limit 3
data source    : offline archive /path/to/bangumi/archive (episodes=1705871, subjects=694202)
scanning 3 series from library 动漫
[1/3] OK   2.5次元的诱惑                                to write 0
[2/3] OK   86-不存在的战区-                             to write 0
[3/3] OK   拔作岛                                       to write 0

series ok      : 3
series review  : 0
episodes       : 0 to write
report         : jbmid-report.json
```

On the full library (89 shows) those last three lines are the verdict: `89 / 0 / 0` means
everything matched and nothing needs writing. `review` rows need a human; `to write` is what
`apply` would change. How the anchor and the whole TV chain are built:
[7.1](#71-scan--find-anchors-automatically).

The report looks like this (excerpt; full field list in 7.1):

```json
{
  "library": "动漫",
  "threshold": 0.45,
  "series": [
    {
      "series": "2.5次元的诱惑",
      "seasons": 1,
      "status": "ok",
      "anchor": 410346,
      "anchor_how": "episode-parent",
      "chain": [410346],
      "notes": ["chain trimmed to 1 subject(s)",
                "kept 24 existing ids (library order differs from Bangumi)"],
      "episodes": [
        {"item_id": "69c3…", "season": 1, "index": 1, "name": "异次元的新进生",
         "bgm_id": "1336023", "bgm_name": "来自异次元的新生", "sim": 0.8, "change": false}
      ]
    }
  ],
  "summary": {"series_ok": 3, "series_review": 0, "episodes_to_write": 0}
}
```

> The full sample is an excerpt of a real report (one `ok` row and two `review` rows with
> their original `reason`): [`examples/scan-report.json`](examples/scan-report.json).

### 5.2 Writing and rolling back

`apply` writes every episode with `change: true` (the single-field write and the read-back check
are described in section 9). Every write goes into a backup:

```json
[
 {"item_id": "69c36749e0dfb987a371a1980815c354", "series": "2.5次元的诱惑",
  "season": 1, "index": 2, "name": "…", "old": "1336023", "new": "1336024"}
]
```

> Full sample: [`examples/backup.json`](examples/backup.json) (a whole-column shift and a
> previously empty ID).

Rolling back means writing `old` back, with one command:

```text
$ jbmid rollback jbmid-backup.json
would restore 33 episodes        # add --dry-run to only look
```

## 6. Speed it up with the offline archive

The Bangumi plugin ships an offline database. Run its "update offline database" task once and it
downloads subjects / episodes / persons into `{Jellyfin data directory}/bangumi/archive/` (in
Docker usually `/config/data/bangumi/archive`, about 1.5 GB, refreshed roughly every two weeks).

This tool **uses that archive by default**; no extra configuration:

```bash
jbmid scan --library 动漫            # auto-detects the archive and uses it
jbmid verify --library 动漫          # same, offline
jbmid scan --library 动漫 --archive /path/to/archive   # archive somewhere else
jbmid scan --library 动漫 --no-archive                 # force online API only
```

Detection order: `--archive` → `JBMID_ARCHIVE` → the `DataPath` reported by Jellyfin's
`/System/Info`.

**The first run builds an index.** 1.5 GB of jsonlines is too much to read on every run, so the
first run writes a ~150 MB SQLite index into the cache directory (`$JBMID_CACHE` →
`~/.cache/jellyfin-bangumi-ids` → system temp), which takes about 20 seconds; afterwards queries
take milliseconds. The index rebuilds itself when the archive changes (size or mtime).

**Measured** (anime library, 2000+ episodes):

| Operation | Online API | Archive (cold) | Archive (warm) |
| --- | --- | --- | --- |
| `verify` | 40 minutes (and gets rate-limited) | 18 s | 18 s |
| `scan` | about 12 minutes | 2.5 min | 19 s |

The archive has no "sequel/prequel" relations and no title search; those still hit the API on
first use and get cached in the index — so a cold start pulls the relation graph once, and from
the second run on it is fully offline. The archive is older than the API: subjects it does not
contain (new shows, freshly created entries) fall back to the API automatically, so nothing is
missed.

## 7. Modes in detail

### 7.1 `scan` — find anchors automatically

```bash
jbmid scan --library 动漫 --out report.json
jbmid scan --library 动漫 --limit 5          # try five shows first
jbmid scan --library 动漫 --no-search        # trust stored IDs only, no title search
```

Anchor priority: **episode parent (look up the subject each episode's own ID belongs to) →
season-ID majority vote → the series' own ID → title search**. Earlier is more trustworthy: an
episode's ID belongs to exactly one subject, season IDs are scraped per season, and the
series-level ID is a single field — one bad match or one refresh rewrites it (that is how
物语系列 ended up on `2098`).

Two guards, both required:

- **Validate even a stored ID.** The ID in your library may be wrong (a whole show pointing at
  another title), so the tool fetches that subject's title and compares it with yours; if it does
  not look alike the ID is dropped and the title search takes over. Without this guard one bad ID
  keeps the show in `review` forever, or gets written back by a refresh.
- **Search results must pass the title guard** (`无职转生` matches
  `无职转生～到了异世界就拿出真本事～`; `Andor` does not match `安德烈和威利的冒险`). Otherwise
  the show goes to `review` — the tool does not gamble.

Title search uses **both `Name` and `OriginalTitle`**: Chinese libraries often carry a translated
name while bgm's `name` is the original, and the original title field hits it first try (measured
on 88 shows: `Name` alone matched 81, adding `OriginalTitle` reached 87). Normalisation folds
full-width to half-width (`８６` → `86`) and keeps kana; without that, a pure-katakana title
normalises to an empty string and similarity is always 0.

**Output on the full library** (89 shows): `89 ok / 0 review / 0 to write`; the three numbers are
explained in 5.1.

**Fields of each show in the report** (excerpt):

| Field | Meaning |
| --- | --- |
| `status` | `ok` or `review` |
| `reason` | why it went to review (`size mismatch` / `weak match` / `no Bangumi anchor` …) |
| `anchor` / `anchor_how` | the subject used, and how it was chosen (`episode-parent` / `season-vote` / `series-id` / `search`) |
| `chain` | the whole TV chain pulled from the anchor (subject ids) |
| `notes` | alignment details such as `season map 1:S1->95225 2:S2->109386` |
| `episodes[]` | per episode: `old` / `bgm_id` / `bgm_name` / `sim` / `change` |

### 7.2 `season` — you say which subjects form a season

Use this when Bangumi's subject split and your folder split follow no rule you can derive. Write
a json file:

```json
{
  "无职转生～到了异世界就拿出真本事～": {
    "1": {"subjects": [277554]},
    "2": {"subjects": [325585]},
    "3": {"subjects": [373247]},
    "4": {"subjects": [444557]},
    "5": {"subjects": [501963]}
  },
  "物语系列": {
    "4": {"subjects": [68812], "filter": "猫物语（白）"},
    "15": {"subjects": [475354], "filter": "业物语|残酷童话"}
  }
}
```

- Keys are **the show's name in your library**; inner keys are **season numbers** (Jellyfin's
  `IndexNumber`).
- `subjects` are concatenated, in order, into one pool. `filter` keeps only episodes whose title
  matches that regex. `sp: true` also pulls that subject's SPs into the pool (for "an SP inserted
  between main episodes").
- When the pool size equals your episode count the IDs are written in order; otherwise the tool
  aligns by title, and if coverage is below 100% the season goes to `review`.

A real map is in [`examples/monogatari-season-map.json`](examples/monogatari-season-map.json);
all sample files are indexed in [`examples/README.md`](examples/README.md).

**Output** (that 17-season map against 物语系列):

```text
$ jbmid season --map examples/monogatari-season-map.json --dry-run
[物语系列 S1] ok 15/15 eps, mean sim 0.82
[物语系列 S2] ok 11/11 eps, mean sim 0.86
…
[物语系列 S12] review 12/19 eps, mean sim 0.97
…
seasons ok: 16   review: 1   episodes: 95
would write 0 episodes
```

One line per season; `review` means that season's pool does not fit (it has 7 extra episodes
here); the rest are written as usual.

### 7.3 `auto` — least work, most need to check the results

```bash
jbmid auto --library 动漫 --dry-run
jbmid auto --library 动漫 --backup jbmid-backup-auto.json
```

It searches Bangumi by series title, keeps candidates whose title passes the guard, pulls the
chain, and aligns by episode title. Coverage ≥ 80% is written directly. Otherwise, if the episode
counts are exactly equal and the series name carries "Season N", it degrades to an ordered mapping
flagged `order-low-confidence` — that path covers libraries whose episode titles are bare
filenames (`S01E01 - [CASO&DMG] ...`).

**Output** (excerpt):

```text
$ jbmid auto --library 动漫 --dry-run
[ok] 2.5次元的诱惑 subject=410346 method=name cov=100% sim=0.90 -> 24 eps
[ok] 碧蓝之海 subject=235130 method=season-map cov=100% sim=0.88 -> 24 eps
[ok] CLANNAD subject=51 method=name cov=100% sim=0.80 -> 44 eps
[ok] 吊带袜天使 subject=8402 method=name cov=92% sim=0.90 -> 12 eps
…
series ok: 83   review: 6   episodes: 2120
would write 0 episodes
```

`method` says what identified it: `name` (title search), `season-map` (season alignment),
`stored` (episode IDs already in the library), `order` (ordered mapping when counts match).

### 7.4 `special` — fix bonus episodes too

Main-episode IDs live in Season ≥ 1; specials usually sit in Season 0. All other modes **skip**
them, so specials never reach Bangumi. `special` covers exactly that gap:

```bash
jbmid special --library 动漫 --out specials.json
jbmid apply specials.json --dry-run
jbmid apply specials.json --backup specials-backup.json
```

It pulls the same chain from the same anchor, collects every `type=1` subject (SP / OVA / recap)
into one pool, and aligns that pool against Season 0 and against episodes whose titles contain
`OVA|SP|番外|总集篇`.

- It only writes what it can name-match (similarity ≥ 0.55); the rest is left for a human — it
  never pads the count to make the numbers fit.
- If the whole chain has one or two SPs and the counts line up, it uses an ordered mapping with a
  floor of 0.25 similarity.
- The output is structurally identical to `scan`, so you still use `apply` / `rollback` and get the
  same backups.

**Output** (excerpt):

```text
$ jbmid special --library 动漫
[11/89] OK      CLANNAD                      match 3/5 sim 0.92
[49/89] OK      轻音少女                       match 2/5 sim 0.79
[51/89] OK      人形电脑天使心                   match 2/4 sim 1.00
series ok      : 13
series review  : 76
specials       : 19 matched
borrowed       : 0 cleared
episodes       : 0 to write
```

Very few SP sets are already correct (Bangumi sometimes records an OVA as a main episode), so
only 13 of 89 shows have alignable specials.

Report excerpt (`match 3/5`, per-episode `old` / `bgm_id`):
[`examples/special-report.json`](examples/special-report.json).

With `--clear-borrowed` it also handles another kind of dirt: a special "borrows" a main
episode's ID (Jellyfin's plugin occasionally does this, and the special then displays the main
episode's title). The test is **fetch that ID from Bangumi and compare the title with the local
special** — if it matches, the OVA really is recorded as a main episode upstream and is kept; if
not, it is cleared, because an empty field beats a wrong one. Cleared IDs go into the backup as
well and `rollback` restores them exactly.

```bash
jbmid special --library 动漫 --clear-borrowed --out specials.json
```

### 7.5 `anchor` — repair the anchor of a single show

The series-level / season-level `Bangumi` value is the "anchor"; every mode starts from it. If it
is wrong, no amount of alignment will save the show (the usual symptom: the same show sits in
`review` forever with `size mismatch` or `weak match`).

```bash
# Show what it has now and what the tool would pick (writes nothing)
jbmid anchor --library 动漫 --series "凉宫春日的忧郁" --dry-run

# Let the tool decide: episode parents > season-ID vote > series ID > title search
jbmid anchor --library 动漫 --series "凉宫春日的忧郁"

# You know the subject: give it explicitly (title-checked; --force overrides)
jbmid anchor --library 动漫 --series "某部剧" --id 1606

# The series-level ID is wrong and you don't want another one: drop it
jbmid anchor --library 动漫 --series "某部剧" --clear
```

**Output:**

```text
$ jbmid anchor --library 动漫 --series "凉宫春日的忧郁" --dry-run
凉宫春日的忧郁 (66cd9aade8589fc19b81d5776ffeccd6)
  before : 1606
  after  : 1606 (episode-parent)
already correct, nothing to write
```

Where that order comes from: **an episode's own Bangumi ID belongs to exactly one parent subject**,
so the subject looked up from the first couple of episodes in a season beats season-level metadata
(which is often copied around), and it is the fallback when a whole season failed to match (the
order itself is in 7.1).

Changes go into `anchor-backup.json`, in the same shape as episode backups, so `rollback` restores
them too.

**Check season-level IDs too.** The plugin reports "watching" with the **season**'s Bangumi ID
(`PlaybackScrobbler` asks the episode's parent); episode IDs only drive per-episode status. So
"every episode is right, the season sits one show off" is invisible to any per-episode check:
playback looks fine while bgm.tv records the neighbouring season. The episode IDs vote it out:

```bash
# Report only: which season ID is not the majority vote of its own episodes
jbmid anchor --library 动漫 --seasons --all --dry-run

# Fix them (written to a backup file; `rollback` restores it)
jbmid anchor --library 动漫 --seasons --all
```

```text
$ jbmid anchor --library 动漫 --seasons --all --dry-run
凉宫春日的忧郁
  season 1   id 1372     -> 1606     (28/28 episodes)
人形电脑天使心
  season 1   id 496276   -> 12       (26/26 episodes)
37 season id(s) off, 0 written (dry run)
```

Only seasons with a vote share of at least 60% and at least 2 episodes are written; the rest are
reported and only written with `--force` -- which still **never** writes a majority vote onto a season
that spans two subjects (it skips them), since that would re-break the half you just cleared.

**A local season that spans two Bangumi subjects has no single right ID.** Whichever one is stored,
episodes of the other subject report the neighbouring entry (86 season 1 is two parts; so is
Mushoku Tensei season 1). Clear those season IDs with `--clear-spans`: `PlaybackScrobbler` then falls
back to the episode's own ID and resolves the subject from it. Same episode, measured:

```text
before: report subject #525565 status Watching   <- the stored first part
after : report subject #638497 status Watching   <- the part this episode belongs to
```

```bash
# Clear every season that spans two subjects (backed up; `rollback` restores it)
jbmid anchor --library 动漫 --seasons --all --clear-spans --dry-run
jbmid anchor --library 动漫 --seasons --all --clear-spans
```

```text
$ jbmid anchor --library 动漫 --seasons --all --clear-spans --dry-run
86-不存在的战区-
  season 1   id 302189   -> (cleared) (12/23 episodes) [clear: spanning season]
进击的巨人
  season 3   id 217300   -> (cleared) (12/22 episodes) [clear: spanning season]
17 season id(s) off, 0 written (dry run)
```


### 7.6 `verify` — read-only health check

```bash
jbmid verify --library 动漫 --out check.json
```

It looks up every episode that has a Bangumi ID on `api.bgm.tv` and compares titles. Anything below
the similarity threshold is listed — note that **this does not mean it is wrong**: filename-style
titles, pure translation differences and English-titled subjects all show up as false positives
and need a human scan.

**Running it against the offline archive (recommended)**: seconds for the whole library and no
API quota; where the archive lives and how the index is built is in section 6:

```bash
jbmid verify --library 动漫 --archive /path/to/bangumi/archive --out check.json
```

Report excerpt: [`examples/verify-report.json`](examples/verify-report.json).

**Output:**

```text
$ jbmid verify --library 动漫
data source    : offline archive /path/to/bangumi/archive
offline check: 2095 ids | unknown 0 | dup 3 | low-sim 278 | disorder 22 | foreign 5 | anchors 0 | season-ids 0 | season-spans 0
```

Besides those counters, `check.json` lists the details per category: `season_rows` holds seasons whose
season ID is not the majority vote of their own episodes (fix: `--seasons`, see 7.5); `span_rows` holds
seasons that span two subjects yet still carry one season ID (fix: `--clear-spans`, see 7.5). Once
cleared, those seasons no longer count towards `season-ids`, so the health check can come back clean:

```json
{
  "checked": 2095, "threshold": 0.45,
  "unknown": 0, "duplicate": 3, "low_similarity": 278,
  "disorder": 22, "foreign_subject": 5, "anchor_rows": [], "season_rows": [], "span_rows": [],
  "duplicate_series": [
    {"name": "间谍过家家",
     "paths": ["/strm/Anime/…/间谍过家家 (2022)", "/hdd/Anime/间谍过家家 (2022)"]}
  ],
  "rows": [
    {"series": "2.5次元的诱惑", "bgm_id": 1336030,
     "local": "热爱Cosplay吗？", "bgm": "爱着角色扮演吗？",
     "season": 1, "index": 8, "sim": 0.235, "kind": "low_similarity"}
  ]
}
```

The offline check sees more than the online one, because order is more reliable than names:

| Field | Meaning |
| --- | --- |
| `unknown` | the stored ID does not exist in the archive (stale or wrong) |
| `duplicate` | one bgm episode ID is shared by two episodes (usually a Season 0 special borrowing a main ID) |
| `disorder` | within one season, the bgm `sort` values behind the IDs are not `n, n+1, n+2…` (shifted or crossed) |
| `foreign_subject` | this episode belongs to another bgm subject, and it is the only one (orphan ID) |
| `anchor_rows` (the `anchors N` line) | the report stores detail rows; the terminal number N is the sum of "does not exist" (`unknown`) and "no episode uses it" (`unused`) |
| `duplicate_series` | the same show is registered twice (e.g. under both `/hdd` and `/strm`) |

The dirty anchors of 物语系列 and 凉宫 were found exactly this way, through `anchor_rows`.

### 7.7 `protect` — stop a later refresh from overwriting your IDs

```bash
jbmid protect
```

It sets the Bangumi plugin's `TrustExistedBangumiId` to `true`, so a re-scrape trusts existing IDs
instead of recomputing them from the season. **Run this after you have fixed the IDs.**

```text
$ jbmid protect
TrustExistedBangumiId = True
```

## 8. Field notes: real misalignments I hit on my own library

Every case below really happened. The library is 89 shows, 2300+ episodes.

### 8.1 A whole season shifted by two

In CLANNAD's second season, 20 episodes had IDs shifted two positions to the right (episode 1
carried episode 3's ID). Titles still matched episode by episode, so `scan` marked the show `ok`,
and those 20 rows were `change: true`; `apply` wrote them in one go.

> Signature: normal similarity, equal counts, but the `old` column is offset as a whole — 20 hand
> edits otherwise.

### 8.2 Only half the season had IDs

In 正相反的你与我, episodes 1–12 had IDs and episodes 13–25 were empty. Empty IDs are treated as
gaps during alignment, so `scan` matched the second half by title and the report showed `old: null`
with a `bgm_id`; `apply` filled 13 episodes.

### 8.3 The series ID pointed at another work

物语系列 had a series-level `Bangumi` of `2098`, which is **源氏物語千年紀 Genji** — both titles
contain 「物语」, so the title guard passed and the whole show was wrong. The tool's handling: the
season-ID majority vote produced the right subject (`anchor_how: season-vote`), the bad ID was
replaced, and the 17 seasons were then pinned with a `season` map.

> This is why `pick_anchor` orders evidence the way it does: a series-level ID is one field, and
> one wrong value breaks a whole show.

### 8.4 Broadcast order is not episode order

The 2009 run of 凉宫春日 is stored in **broadcast order** locally (episode 1 is 「竹叶狂想曲」),
while Bangumi orders it by production number. Title coverage is only 22%, so all 13 episodes were
flagged `disorder` and the show went to `review` — **no guessing**.

> This cannot be recovered from titles alone; you have to reorder it yourself, or scrape metadata
> that follows broadcast order.

### 8.5 One local season, two subjects

Fate/stay night UBW: two local seasons (12 + 13 episodes), while the Bangumi chain is
`Fate/Zero`(25) → `UBW`(13) → `UBW S2`(13), 51 episodes in total. A flat alignment is 25 versus 51,
`size mismatch`; with season alignment:

```text
season map 1:S1->95225 2:S2->109386
```

S1's 12 episodes land in the first subject and S2 in the second. The same shape appears in
心理测量者 (three seasons of 22 / 11 / 8 episodes, with four single-episode movies mixed into the
chain, which season alignment simply skips).

### 8.6 Incomplete seasons and titles that never match

Rick and Morty has seven local seasons, one of them with only 9 episodes, and none of the titles
match. The tool falls back to **the episode IDs already stored in the library**: they happen to be
the Bangumi set of 10 with one hole, so the hole is placed in the right spot.

> Three kinds of evidence, in order: title similarity → where the stored IDs land → ordered mapping
> when the counts are equal.

### 8.7 A title containing `SP` was misread

An early version used `SP\d*` to detect bonus episodes, so the `SP` inside `Splitting of the Breast`
was read as a marker and a whole episode was dropped from alignment. Requiring a digit (`SP\d+`)
restored EVA from `25/28` to `26/26`.

### 8.8 Shapes I have not hit, but the tool guards against

| Your library might look like | What the tool does |
| --- | --- |
| Titles are filenames `S01E01 - [CASO&DMG] 夏の…` | variant splitting strips group tags and `SxxExx` before comparing |
| Titles are `Show - S03E18 - 白夜` | takes the last segment after the separator as the title |
| One season has two extra episodes and pushes everything | per-season segments, no cross-season drift |
| The chain contains single-episode movies or unreleased seasons | season alignment skips whole runs without inflating the pool |
| The chain wrongly includes "season 2" | size guard catches it (13 episodes vs 26 → `review`) |
| Titles are pure Japanese or pure numbers | ordered mapping when counts are equal, flagged in the report |
| Local order differs from Bangumi's `sort` | that season searches for its own subject (`season rescue`) |
| Main list contains "…的谈话" recap episodes | filtered out as specials, not counted in the main pool |
| Specials in Season 0 or with SP/OVA in the title | skipped by main modes, handled by `special` against `type=1` |
| The same show twice (`/strm` + `/hdd`) | scanned independently, no shared state; `verify` reports `duplicate_series` |

## 9. Safety

- **One field only**: GET the full item → change `ProviderIds.Bangumi` → POST back → GET again and
  compare; also check that `Name / Overview / PremiereDate / Imdb / Tmdb / Tvdb` were not touched
  (`collateral`).
- **Dry-run first**: `--dry-run` really reads the current IDs and tells you how many episodes it
  would write, without writing.
- **Backup before writing**: every write records `(item_id, old, new)` in a json file, and
  `rollback` restores it with one command.
- **No guessing**: count mismatches, low title coverage and failed anchor checks all end in
  `review`, with not a single field changed.
- The tool never deletes items and never touches file paths or metadata text.

## 10. FAQ

### Q1. `HTTP 401`

Wrong key, or a key belonging to a different server. Run `jbmid doctor` first.

### Q2. `HTTP 404 ... "Series not found"`

Some Jellyfin versions parse `/Shows/{id}/Episodes` inconsistently. This tool uses
`/Items?ParentId=` instead and never hits that path.

### Q3. Scanning is extremely slow, ~20 s per show

Your NAS advertises IPv6 but cannot actually use it, and the AAAA records for `api.bgm.tv` are
polluted, so every request waits for a timeout. Add `--ipv4` (or write a `gai.conf` that prefers
IPv4).

### Q4. The same show appears twice in the library

Usually `/strm/` and `/hdd/` copies, or a leading space in the title (`新 吊带袜天使`). `season` mode
needs the exact name from your library; `auto` searches by fuzzy title and refuses to guess when
names collide.

### Q5. How are SP / OVA handled

`scan` and `auto` exclude Season 0 and episodes whose titles contain
`OVA|OAD|SP|总集篇|番外|特典|NCOP|NCED` from main-episode alignment and count them in the report's
`skipped_specials`; `special` (7.4) covers bonus episodes, and "an SP inserted at episode 8.5" is a
`season` mode job with `"sp": true`.

### Q6. TMDB says one season, Bangumi has two subjects

If the two subjects are linked by a "sequel" relation, `scan` / `auto` **align seasons
automatically**; no map needed (the mechanism is in 12.3). Only when the tool cannot decide
(titles do not match, no stored IDs) do you need `season` mode by hand.

### Q7. My library uses English titles — can it still match

Yes, but it depends on the episode-title language of that subject on Bangumi. Western works
(`Rick and Morty`) have English episode titles there, so per-episode similarity works. Japanese
animation has a Japanese `name` and a Chinese `name_cn`; an English show title matches neither.
Then three signals are tried in order: **episode titles** (high enough similarity) → **episode IDs
already stored in the library** → **equal counts** (ordered mapping); only when none of them
exists does a show go to `review`. Rick and Morty was fully matched by the first two (see 8.6).

### Q8. Is `--library` case-sensitive

No. After an exact match fails it retries case-insensitively, then by unique substring; if it still
cannot find one it lists the available library names.

### Q9. What should I do after `scan`

Look at the `series review` rows first: `reason` says why. If the rest looks right, `apply`, then
`verify` to confirm, then `protect` once. `review` shows are never touched, so you can re-run as
often as you like.

### Q10. Does the offline archive go stale

Yes — the plugin refreshes it roughly every two weeks. Anything missing falls back to the online
API (section 6), so an old archive can be slow but never causes missed matches. To force a refresh,
run the plugin's "update offline database" task.

### Q11. Does it support movies or films

No. It handles TV episodes (`type=0`) and SPs (`type=1`) on the TV chain; films are out of scope.

### Q12. Will it change my existing metadata

No — writing touches only `ProviderIds.Bangumi`; the read-back comparison and the `collateral`
check are in section 9.

## 11. Where the data comes from

Three sources, none of which needs extra software:

| Source | What is read | Address |
| --- | --- | --- |
| Your Jellyfin | libraries / shows / seasons / episodes, each episode's `Name` and `ProviderIds.Bangumi` | your own `:8096` |
| Bangumi public API | relations, main episodes, specials, titles | `https://api.bgm.tv/v0` (anonymous, no token) |
| Bangumi IDs already in your library | used as anchors to locate "which subject is this show" | read from Jellyfin |

The endpoints actually used:

```text
Jellyfin
  GET  /Library/MediaFolders                                      → library name → id
  GET  /Items?IncludeItemTypes=Series&Recursive                   → every show (with ProviderIds)
  GET  /Shows/{seriesId}/Seasons                                  → seasons
  GET  /Items?ParentId={seasonId}&IncludeItemTypes=Episode&Recursive=true
                                                                  → episodes per season
  GET  /Items/{itemId}?userId={uid}&Fields=ProviderIds,Path       → full episode DTO
  POST /Items/{itemId}                                            → write back

Bangumi
  GET  /v0/subjects/{id}/subjects                                 → sequel / prequel relations
  GET  /v0/episodes?subject_id={id}&type=0                        → main episodes
  GET  /v0/episodes?subject_id={id}&type=1                        → SP / OVA
  POST /v0/search/subjects                                        → find a subject by title
  GET  /v0/episodes/{id}                                          → single episode
```

Two common misunderstandings:

- **It does not read TMDB / TVDB data.** Those are only where your metadata came from; the tool
  sees the episode title that scraping left in Jellyfin — so "TMDB one season, Bangumi two
  subjects" is solved at the **title** level, whichever scraper you use.
- **`sort` is not necessarily an integer.** Bangumi episode numbers can be `8.5` or `16.5` (an SP
  inserted between main episodes); sorting is done as floats, never rounded.

## 12. How it works

### 12.1 The five-stage pipeline

```text
① anchor     episode parent → season-ID vote → series ID → title search (order in 7.1)
② chain      from the anchor follow "sequel" forward and "prequel" backward, de-duplicated
③ pool       take type=0 from every subject on the chain, drop empty titles, sort by `sort`
④ align      segment → variant split → similarity → monotonic best match → gap fill
⑤ decide     conditions in 12.4
⑥ write      GET the full DTO → change one field → POST → GET back (see section 9)
```

### 12.2 What alignment looks like

All five writing modes (`scan` / `season` / `auto` / `special` / `anchor`) share one core
algorithm: **align by episode title, not by episode number**.

```text
local title                        Bangumi title
进击的巨人 - S03E18 - 白夜   ⟷  白夜            ✔ 1.00
S01E05 - [Group] 白夜        ⟷  白夜            ✔ 1.00 (group tag and SxxExx stripped first)
第 14 集                     ⟷  決心            ✘ 0.00 → fall back to order
```

#### 12.2.1 Variant splitting

`S01E18 - [Group] 白夜`, `Show - S03E18 - 白夜`, `「…」『…』` and `A／B` all yield candidate
titles, each compared against `name_cn` / `name`.

#### 12.2.2 Monotonic best match and gap filling

- *Monotonic*: a dynamic program finds the highest-scoring order-preserving match; episode 5 can
  never be paired with episode 3.
- *Gap filling*: when both sides have the same number of gaps left, they are filled 1:1, which
  handles translation differences like `觉悟` ↔ `決心` that score 0 on similarity but are
  positionally certain.

**Avoiding cross-season drift**: when the local season count equals the subject count on the chain,
each season is aligned only against **its own** subject; otherwise a season-level alignment runs
first (12.3) and only if that fails is the chain treated as one pool. A flat pool lets one short
season shift every later season — the most common way tools like this break.

### 12.3 Shapes that season alignment solves

Each local season and each subject on the chain get a similarity matrix over **episode-title
fingerprints**; an order-preserving DP then assigns runs of consecutive subjects to seasons,
allowing several local seasons inside one subject, single-episode movies to be skipped outright, and
a season to be merely a subset. Evidence must be real — no positional guessing: title coverage
≥ 90% and mean similarity ≥ 0.55, or every stored Bangumi episode ID inside that run and strictly
increasing. If any step fails, the assignment is abandoned and the flat pool takes over.

| Your library | Bangumi chain | Result |
| --- | --- | --- |
| 2 seasons: 12 + 13 episodes | `Fate/Zero`(25) → `UBW S1`(13) → `UBW S2`(13) | 25 vs 51 episodes is `size mismatch`; after season alignment `1:S1->95225 2:S2->109386` |
| 3 seasons: 22 / 11 / 8 episodes | 4 main subjects + 4 single-episode movies in between | the movie run is skipped, `3:S3->277105` |
| 7 seasons, one with only 9 episodes | 7 main subjects + 3 empty ones | titles never match, so stored episode IDs locate it and the missing episode is filled in the right place |

The report's `notes` records `season map 1:S1->95225 2:S2->109386`, so you can see exactly which run
was claimed.

Two more shapes are rescued without a monotonic whole-chain match:

- **A season that is out of chain order** (物语系列 puts `花物语` before `终物语`, the opposite of
  Bangumi's `sort`): no whole-chain alignment can satisfy it. Such a season searches for its own
  subject by title (`花物语 第变话 …` → search 「花物语」) and first tries episodes left over from
  subjects other seasons did not use (`业物语` hides in the 3 leftover episodes of `外传季`), then
  writes that segment alone; the report says `season rescue <query> -> <subject>`.
- **Titles that never match at all** (EVA has English subtitles locally, Bangumi only Chinese): as
  long as a monotonic pairing covers 98%+ of local episodes, uses ≥ 85% of the pool, and the pool
  is at most 3 episodes longer, it is accepted in order and the report says `positional match`.
  Worse cases — like 凉宫's broadcast-order library — never trigger this, because its title
  coverage is only 22%.

### 12.4 When it actually writes

Counts equal on both sides, or (similar size + coverage ≥ 90% + mean similarity ≥ 0.55). If any
condition fails, the show goes to `review` and nothing is changed.

## 13. Generality: will it work on someone else's library?

**There is nothing "of one person's library" in the code**: no hard-coded subject IDs, show names
or episode counts; the only fixed constant is the Bangumi plugin GUID `41b59f1b-a6cf-474a-b416-785379cbd856`,
used only by `protect` to flip `TrustExistedBangumiId`. A library without any Bangumi IDs still
works (title search); with neither an ID nor a title match it reports `no Bangumi anchor` instead
of guessing. Defences against "someone else's library" are in the table in 8.8.

**Cross-version, cross-environment compatibility**

- Both auth headers are sent: `Authorization: MediaBrowser Token="…"` and `X-Emby-Token`. Jellyfin
  10.x accepts the former, some 12.x builds only the latter; sending one gives 401.
- Episodes are fetched with `/Items?ParentId=` rather than `/Shows/{seasonId}/Episodes` (which
  returns 404 `Series not found` on some versions).
- Network: 5xx / 429 / URLError retried three times with backoff; a single failing show is marked
  `review` without aborting the run. Runtime dependencies: section 3 (standard library only).

**Safe and reversible**: see section 9.

## 14. What it doesn't solve

1. **Titles that are themselves wrong** (a whole season copied from another show) — re-scrape first;
   the tool will not guess your episode order.
2. **Titles with no information** (bare "Episode 1") and counts that differ from Bangumi — `review`
   only.
3. **Subjects that do not exist on Bangumi** — films, bonus shorts and in-show shows are not on the
   TV chain, and movies are out of scope; the tool will not force them.
4. **The Bangumi plugin must be installed**; `protect` depends on its fixed GUID.
5. It does not scrape and does not rename episodes; non-integer `sort` values are handled in
   section 11.

## 15. Development

### 15.1 Tests and CI

```bash
pip install -e .
python -m unittest discover -s tests -v     # 80 tests, offline
```

Coverage: title splitting, similarity, monotonic alignment, gap filling, scan decisions, special
matching, library-name resolution, writing and rollback, plus season alignment, the offline archive
index and anchor priority.

> CI runs on every push / PR across Python 3.8 / 3.10 / 3.12;
> see `.github/workflows/test.yml`.

### 15.2 Layout

```text
src/jellyfin_bangumi_ids/
  cli.py           subcommands and arguments
  jellyfin.py      Jellyfin REST client, single-field writes
  bangumi.py       api.bgm.tv client (relations / episodes / search)
  offline.py       offline archive backend (same interface as bangumi.py)
  archive.py       jsonlines reader and SQLite index
  scan.py          anchor, chain, pool, alignment, decision, writing
  season_align.py  order-preserving DP for season alignment
  match.py         title normalisation, variant splitting, similarity, monotonic match
  season.py        manual map mode
  auto.py          title-search mode
  anchor.py        anchor diagnosis and repair
  verify.py        read-only health check
  transport.py     retries and IPv4
tests/             80 tests, offline
examples/          real output samples: report / backup / verify / specials / season map
```

### 15.3 Releasing

```bash
# 1) bump the version (pyproject.toml / __init__.py) and CHANGELOG.md
# 2) run the tests
python -m unittest discover -s tests
# 3) commit and tag
git commit -am "chore: release v0.1.3"
git tag -a v0.1.3 -m "v0.1.3"
git push origin main --tags
# 4) create a release from the tag on GitHub (attach the wheel)
python -m pip wheel . --no-deps -w dist
```

## 16. License

MIT
