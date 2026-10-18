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

## Symptoms: you might need this

- You finish an episode and nothing shows up on Bangumi; the log keeps saying
  `item "..." (#...) doesn't have bangumi id, ignored`.
- Progress *does* sync — to the **wrong show**. For example every episode in a season points at
  some other series.
- A show is one season on TMDB but Bangumi splits it into "part 1 / part 2", so everything after
  episode 12 is off by a fixed amount.
- A special (SP / OVA / episode 0) got treated as a regular episode, shifting every later episode
  by one.
- You fixed one ID by hand, and the next metadata refresh overwrote it.

## What it does

Every Jellyfin episode carries a `ProviderIds.Bangumi` value, and that number is the only thing
the Bangumi plugin looks at when reporting playback. This tool fills that number in correctly —
**and touches nothing else**.

Five modes; pick one based on how messy your library is (each is documented under
[Modes in detail](#modes-in-detail)):

| Mode | When to use | Command |
| --- | --- | --- |
| `scan` | Most shows are fine, only a handful are wrong | `jbmid scan` → `jbmid apply` |
| `season` | Bangumi's season split has nothing to do with your folders; you map it yourself | `jbmid season --map map.json` |
| `auto` | Do it in one shot: let the tool find subjects by title and align by episode title | `jbmid auto` |
| `special` | You also want bonus episodes (SP / OVA / recaps) synced | `jbmid special` → `jbmid apply` |
| `verify` | Check which IDs are broken, before or after a repair — **read-only** | `jbmid verify` |

## Install

Standard library only; Python ≥ 3.8.

```bash
pip install git+https://github.com/QingYunYo/jellyfin-bangumi-ids.git
# or for local development
git clone https://github.com/QingYunYo/jellyfin-bangumi-ids.git
cd jellyfin-bangumi-ids && pip install -e .
```

You get a `jbmid` command (or `python -m jellyfin_bangumi_ids`).

## Prepare an API key

Jellyfin Dashboard → Administration → API Keys → New, give it a name (e.g. `jbmid`). Then:

```bash
export JF_URL=http://127.0.0.1:8096
export JF_API_KEY=your-key
jbmid doctor
```

`doctor` reports the Jellyfin version, your libraries, whether `bgm.tv` is reachable, and the
plugin's configuration state. Get all four green before going further.

## Quick start

```bash
# 1) scan the "Anime" library and write a report (writes nothing)
jbmid scan --library Anime --out report.json

# 2) read the report: series ok / series review / episodes to write is the verdict
# 3) dry-run first to see how many episodes would change
jbmid apply report.json --dry-run

# 4) for real (old values are backed up to jbmid-backup.json)
jbmid apply report.json --backup jbmid-backup.json

# 5) something went wrong → one command to roll back
jbmid rollback jbmid-backup.json
```

> `scan` uses the Bangumi ID **already present** as an anchor, walks the "sequel" relations to pull
> the whole TV chain, then aligns every regular episode on that chain against your library by
> title. That is why it handles "one show split into several subjects" natively — as long as the
> chain's total episode count matches your library.

## Speed it up with the offline archive

The Bangumi plugin ships a local database: run its "update offline database" task once and it
downloads subject / episode / person dumps into `{Jellyfin data dir}/bangumi/archive/`
(`/config/data/bangumi/archive` in Docker, about 1.4 GB, refreshed every couple of weeks).

This tool **uses that archive by default** — no extra setup:

```bash
jbmid scan --library Anime                       # auto-detects the archive
jbmid verify --library Anime                     # offline check as well
jbmid scan --library Anime --archive /path/to/archive   # archive lives elsewhere
jbmid scan --library Anime --no-archive                 # force the online API
```

Resolution order: `--archive` → `JBMID_ARCHIVE` → `DataPath` from Jellyfin's `/System/Info`.

**The first run builds an index.** 1.4 GB of jsonlines is too much to read on every run, so the
first use writes a ~100 MB SQLite index into the cache directory (`$JBMID_CACHE` →
`~/.cache/jellyfin-bangumi-ids` → the system temp dir) in about twenty seconds; queries after
that answer in milliseconds. The index is rebuilt automatically when the archive changes
(size or mtime).

**Measured on a 2122-episode library:**

| command | online API | offline (cold) | offline (warm) |
| --- | --- | --- | --- |
| `verify` | 40 min (and rate-limited) | 18 s | 18 s |
| `scan` | ~12 min | 2.5 min | 19 s |

Sequel/prequel relations and title search are not in the archive: the first run still calls the
API for those and caches the answers inside the index, which is why the cold run pays for the
relation graph once. The archive is older than the live database, so ids it does not know
(new shows, freshly created subjects) fall back to the API — nothing gets missed.

## Modes in detail

### 1. `scan` — find anchors automatically

```bash
jbmid scan --library Anime --out report.json
jbmid scan --library Anime --limit 5          # try 5 shows first
jbmid scan --library Anime --no-search        # trust existing IDs only, never search by title
```

Anchor priority: **the series' own Bangumi ID → any season's Bangumi ID → search by title.**

Two guards, both required:

- **Stored IDs are verified too.** A library may carry a wrong id (the whole show pointing at an
  unrelated title). The id is kept only if that subject's title resembles yours; otherwise it is
  dropped and search takes over. Without this check one bad id keeps a show in `review` forever,
  and a metadata refresh can rewrite the entire series.
- **Search results must pass the title guard** (`无职转生` matches
  `无职转生～到了异世界就拿出真本事～`; `Andor` does not match `安德烈和威利的冒险`), otherwise the
  show goes straight to `review` — no guessing.

Search queries **both `Name` and `OriginalTitle`**: a localized library name often differs from
Bangumi's original title, and the original-title field usually hits it exactly (measured on 88
shows: 81 hit by `Name` alone, 87 with `OriginalTitle` added). Text is NFKC-folded
(`８６` → `86`) and kana is preserved — otherwise a pure-katakana title normalises to an empty
string and scores 0 against everything.

### 2. `season` — you say which subjects form a season

Use this when Bangumi's subject split has no pattern that matches your folders. Write a JSON file:

```json
{
  "Mushoku Tensei: Jobless Reincarnation": {
    "1": {"subjects": [277554]},
    "2": {"subjects": [325585]},
    "3": {"subjects": [373247]},
    "4": {"subjects": [444557]},
    "5": {"subjects": [501963]}
  },
  "Monogatari Series": {
    "4": {"subjects": [68812], "filter": "猫物语（白）"},
    "15": {"subjects": [475354], "filter": "业物语|残酷童话"}
  }
}
```

- Keys are **the show title as it appears in your library**; inner keys are **season numbers**
  (Jellyfin's `IndexNumber`).
- `subjects` are concatenated in order into one pool. `filter` keeps only episodes whose title
  matches the regex. `sp: true` also pulls that subject's SP episodes into the pool (for "SP sits
  between regular episodes" cases).
- If the pool's length equals your local episode count, episodes are mapped in order; otherwise
  they are aligned by title, and anything below 100% hit rate goes to `review`.

A real example: [`examples/monogatari-season-map.json`](examples/monogatari-season-map.json).

### 3. `auto` — least work, most need to check the results

```bash
jbmid auto --library Anime --dry-run
jbmid auto --library Anime --backup jbmid-backup-auto.json
```

Searches Bangumi by show title, keeps candidates whose titles pass the guard, pulls the whole
chain, and aligns by episode title. Hit rate ≥ 80% → write. Otherwise, if **episode counts are
exactly equal and the show title contains "Season N / 第 N 季"**, it degrades to positional
mapping and marks the show `order-low-confidence` — that path handles libraries whose episode
titles are just filenames (e.g. `S01E01 - [CASO&DMG] ...`).

### 4. `special` — fix bonus episodes too

Regular episodes live in Season ≥ 1; specials usually sit in Season 0. The other modes **skip**
them, so specials never sync to Bangumi. `special` fills that gap:

```bash
jbmid special --library Anime --out specials.json
jbmid apply specials.json --dry-run
jbmid apply specials.json --backup specials-backup.json
```

It pulls the same chain from the same anchor, collects each subject's `type=1` episodes
(SP / OVA / recaps) into a pool, and aligns them by title against your Season 0 episodes and any
episode whose title contains `OVA|SP|番外|总集篇`.

- Only writes when names match (similarity ≥ 0.55); the rest is left for a human — never padded
  just to make numbers line up.
- When the whole chain has only one or two SPs and the counts happen to match, it falls back to
  positional mapping, but still requires a floor of 0.25 similarity.
- The output is structurally identical to `scan`, so `apply` / `rollback` work unchanged.

### 5. `verify`: read-only health check

```bash
jbmid verify --library Anime --out check.json
```

It looks every stored id up on `api.bgm.tv` and compares episode names. Everything
below the threshold is printed — which is **not** the same as "wrong": file-name
titles, fan-sub translations and English-only entries all raise false alarms.

**Offline variant (recommended)**: the Bangumi plugin ships a local archive
(`{config}/data/bangumi/archive/`). Reading it costs no API quota — a 2000-episode
library finishes in about fifteen seconds:

```bash
jbmid verify --library Anime --archive /path/to/bangumi/archive --out check.json
```

The offline run checks more, because order is more reliable than names:

- `unknown_id`: the stored id does not exist in the archive
- `duplicate`: one bgm episode id used by two local episodes (usually a Season 0 special borrowing a TV id)
- `disorder`: within one season the bgm `sort` values no longer walk `n, n+1, n+2…`
- `foreign_subject`: the episode lives in another subject and is the only one doing so
- `anchor_unused`: no episode uses the series-level id — how a stale anchor shows up
- `duplicate_series`: the same show is registered twice (e.g. `/hdd` and `/strm`)


### 6. `protect` — stop a later refresh from overwriting your IDs

```bash
jbmid protect
```

Sets the Bangumi plugin's `TrustExistedBangumiId` to `true`, so a re-scrape trusts the IDs that
already exist instead of recomputing them per season. **Run this after fixing IDs.**

## Safety

- **One field only**: GET the full item → change only `ProviderIds.Bangumi` → POST it back → GET
  again and verify that `Name / Overview / PremiereDate / Imdb / Tmdb / Tvdb` were not damaged.
- **Dry run first**: `--dry-run` really reads current IDs and tells you how many episodes would
  change, writing nothing.
- **Backup before writing**: every write records `(item_id, old, new)` to JSON; `rollback` restores
  with one command.
- **No guesses**: count mismatch, low match rate, or an unverified anchor all end in `review`, and
  that show is left completely untouched.
- It never deletes items and never changes file paths or metadata text.

## FAQ

**`HTTP 401`**
Wrong key, or a key for a different server. Run `jbmid doctor` first to confirm the version is
readable.

**`HTTP 404 ... "Series not found"`**
Some Jellyfin versions parse `/Shows/{id}/Episodes` inconsistently. This tool uses
`/Items?ParentId=` instead, so you won't hit it.

**Scanning is very slow, ~20 s per show**
Your NAS has IPv6 that does not actually work, and `api.bgm.tv`'s AAAA records are poisoned, so
urllib waits for a timeout every time. Add `--ipv4` (or make the system prefer IPv4 via
`gai.conf`).

**The same show appears twice in the library**
Common when `/strm/` and `/hdd/` each hold a copy, or when the title has a stray leading space
(`新 吊带袜天使`). `season` mode requires the title to match your library **exactly**; `auto`
searches titles fuzzily and aborts with an error when it finds duplicates, so you can confirm.

**What about SP / OVA?**
`scan` and `auto` exclude Season 0 and any episode whose title contains
`OVA|OAD|SP|总集篇|番外|特典|NCOP|NCED` from alignment, and count them in the report's
`skipped_specials`. For "SP inserted as episode 8.5", use `season` mode with `"sp": true`.

**One TMDB season = two Bangumi subjects**
Exactly what `season` mode is for: point season 1 at the first subject and season 2 at the second.
If the two subjects are related as "sequel" on Bangumi, `scan` mode can also stitch them together.

**My library uses English titles — does matching still work?**
Yes, but it depends on the language of the episode titles on Bangumi. Western shows (`Rick and
Morty`) have English episode names on bgm, so per-episode similarity works. Japanese anime store
`name` in Japanese and `name_cn` in Chinese; an English local title scores 0 against both. Matching
then falls back to "equal counts → map by order". If the counts also differ, the show goes to
`review` — use `season` mode, or fix the metadata first.

**Is `--library` case-sensitive?**
No. Exact match first, then case-insensitive, then a unique substring; if nothing matches it lists
the available library names.

## Where the data comes from

Only three sources, none of which needs anything installed:

| Source | What it provides | Where |
| --- | --- | --- |
| Your Jellyfin | libraries / shows / seasons / episodes, each episode's `Name` and `ProviderIds.Bangumi` | your own `:8096` |
| Bangumi public API | subject relations, regular episodes, specials, episode titles | `https://api.bgm.tv/v0` (anonymous, no token) |
| Existing Bangumi IDs | anchors: "which subject is this show?" | read from Jellyfin |

The endpoints actually used:

```text
Jellyfin
  GET  /Library/MediaFolders                                      → library name → id
  GET  /Items?IncludeItemTypes=Series&Recursive                   → all series (with ProviderIds)
  GET  /Shows/{seriesId}/Seasons                                  → seasons
  GET  /Items?ParentId={seasonId}&IncludeItemTypes=Episode&Recursive=true
                                                                  → episodes per season
  GET  /Items/{itemId}?userId={uid}&Fields=ProviderIds,Path       → full item DTO
  POST /Items/{itemId}                                            → write back

Bangumi
  GET  /v0/subjects/{id}/subjects                                 → sequel / prequel relations
  GET  /v0/episodes?subject_id={id}&type=0                        → regular episodes
  GET  /v0/episodes?subject_id={id}&type=1                        → SP / OVA
  POST /v0/search/subjects                                        → find a subject by title
  GET  /v0/episodes/{id}                                          → one episode
```

Two things people usually get wrong:

- **It does not read TMDB / TVDB data.** Those are just your scraping sources; the tool sees the
  episode title that scraping left in Jellyfin. So "one season on TMDB, two subjects on Bangumi"
  is solved at the **title** level — it never needs to know which scraper you use.
- **`sort` is not always an integer.** Bangumi episode numbers can be `8.5` or `16.5` (an SP
  wedged between regular episodes), so ordering uses floats and never rounds.

## How it works

```text
① anchor      series ID → some season's ID → search by title
② chain       walk "sequel" forward and "prequel" backward, dedupe
③ pool        take type=0 from every subject on the chain, drop empty titles, sort by sort
④ align       segment → variant split → similarity → monotonic optimal match → gap fill
⑤ gate        equal counts, or (close counts + hit rate ≥ 90% + mean similarity ≥ 0.55)
⑥ write       GET full DTO → change one field → POST → GET again and compare
```

**① Anchor** is the cheapest and most reliable signal. Only when there is none does it search by
title, and search results must pass the title guard (mutual containment after normalization),
otherwise the show goes straight to `review` — no gambling.

**④ Alignment** in a few details:

- *Segments*: when the number of local seasons equals the number of subjects on the chain, each
  season is aligned only against its own subject, preventing cross-season drift.
- *Variant splitting*: `S01E18 - [Group] 白夜`, `进击的巨人 - S03E18 - 白夜`, `「…」『…』`,
  `A／B` all yield candidate titles, compared one by one against `name_cn` / `name`.
- *Monotonic*: dynamic programming maximizes total score while preserving order — episode 5 can
  never be matched to episode 3.
- *Gap fill*: when the remaining gaps on both sides are equal, they are paired 1:1, which handles
  translation differences with zero lexical overlap but a fixed position (`觉悟` ↔ `決心`).

**⑥ Write** touches only the `ProviderIds.Bangumi` key, reads back, and checks whether
`Name / Overview / PremiereDate / Imdb / Tmdb / Tvdb` were damaged.

### What alignment looks like

All four writing modes (`scan` / `season` / `auto` / `special`) share one core idea: **align by
episode title, not by episode number**.

```text
local title                    Bangumi title
进击的巨人 - S03E18 - 白夜   ⟷  白夜            ✔ 1.00
S01E05 - [Group] 白夜        ⟷  白夜            ✔ 1.00  (after stripping [group] and SxxExx)
第 14 集                     ⟷  決心            ✘ 0.00  → falls back to order
```

Matching is **monotonic optimal** (order-preserving), then "equal gaps on both sides get paired
1:1" handles translation differences (`觉悟` vs `決心`).

**Avoiding cross-season drift**: when the number of local seasons equals the number of subjects on
the Bangumi chain, each season is aligned only against **its own** subject; otherwise (a show split
into 6 subjects, 3 seasons in your library) the whole chain becomes one pool. Pool-wide alignment
lets one missing episode in an earlier season shift every later season by one — the classic way
tools like this break.

**When it writes**: counts are equal, or (counts are close + hit rate ≥ 90% + mean similarity
≥ 0.55). If neither holds, the show goes to `review` and not a single episode is touched.

## Generality: will it work on someone else's library?

**There is no "your library" hard-coded anywhere**

- Zero hard-coding: no subject ID, show title or episode count is baked in. The only fixed constant
  is the Bangumi plugin GUID `41b59f1b-a6cf-474a-b416-785379cbd856`, which the plugin author sets;
  it is used only by `protect` to flip `TrustExistedBangumiId`.
- Libraries without any Bangumi ID still work (title search). When there is no ID *and* no title
  match, it reports `no Bangumi anchor` instead of guessing.

**Defenses against "someone else's library"**

| Your library might look like | What the tool does |
| --- | --- |
| filenames as titles: `S01E01 - [CASO&DMG] 夏の…` | variant split strips `[group]` and `SxxExx` before comparing |
| titles like `Show - S03E18 - 白夜` | takes the last dash-separated segment as the title |
| one TMDB season / two Bangumi parts | builds a pool from the sequel chain; still unmatched → `review` |
| one season has two extra episodes, shifting the rest | per-season segmented alignment, no cross-season drift |
| the chain wrongly includes a "season 2" | size guard rejects it (13 episodes vs 26 → `review`) |
| titles are pure Japanese or pure numbers | positional mapping when counts match, flagged in the report |
| specials in Season 0 or in the title | excluded from regular modes; `special` mode uses `type=1` |
| the same show twice (`/strm` + `/hdd`) | scanned independently, no shared state |

**Cross-version, cross-environment compatibility**

- Both auth headers are sent: `Authorization: MediaBrowser Token="…"` and `X-Emby-Token`.
  Jellyfin 10.x accepts the former, some 12.x builds only the latter; sending one alone gives 401.
- Episodes are fetched via `/Items?ParentId=` rather than `/Shows/{seasonId}/Episodes`, which some
  versions answer with 404 `Series not found`.
- Network: 5xx / 429 / URLError get three retries with backoff; a single failing show is marked
  `review` without aborting the run; `--ipv4` fixes the "IPv6 exists but does not work, and AAAA
  records are poisoned" case that otherwise costs 20 seconds per show.
- Python ≥ 3.8, zero third-party dependencies; `pip install` gives you `jbmid`.

**Safety and reversibility**

- Only one field is modified, and every write is read back and verified.
- `--dry-run` really reads and computes, without writing.
- Every write records `(item_id, old, new)`; `rollback` restores with one command.
- Every ambiguous case converges to `review` instead of guessing something that merely looks fine.

## What it doesn't solve

1. **The titles themselves are wrong** (a whole season's titles copied from another show) — fix
   the metadata first; the tool will not guess your episode order.
2. **Titles carry no information** (plain "Episode 1") and counts differ from Bangumi — only
   `review`.
3. **Episodes Bangumi does not have** — movies, short specials, in-show series are not on the TV
   chain, and the tool will not force them.
4. **Movies** are out of scope.
5. **The Bangumi plugin must be installed**; `protect` relies on its fixed GUID.
6. No scraping, no title rewriting; Bangumi `sort` values that are not consecutive integers (e.g.
   8.5) are ordered as floats, never rounded.

## Development

```bash
pip install -e .
python -m unittest discover -s tests -v     # 21 tests, no network
```

Tests cover title splitting, similarity, monotonic alignment, gap filling, scan decisions, special
matching, library resolution, writing and rollback.

> CI runs on every push / PR across Python 3.8 / 3.10 / 3.12;
> the workflow lives at `.github/workflows/test.yml`.

### Releasing

```bash
# 1) bump the version (pyproject.toml / __init__.py) and CHANGELOG.md
# 2) run the tests
python -m unittest discover -s tests
# 3) commit and tag
git commit -am "chore: release v0.1.2"
git tag -a v0.1.2 -m "v0.1.2"
git push origin main --tags
# 4) create a release from the tag on GitHub (attach the wheel)
python -m pip wheel . --no-deps -w dist
```

## License

MIT
