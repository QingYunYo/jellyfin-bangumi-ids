"""Season-level alignment: map each local season onto a run of chain subjects.

A library often splits a franchise the way *it* likes: ``Fate/stay night [UBW]``
has two local seasons over a three subject chain, ``Psycho-Pass`` folds a movie
between its second and third season, ``Rick and Morty`` keeps a season short by
dropping one episode.  Comparing the flattened library against the flattened
chain then reports "size mismatch" even though every episode has a home.

This module answers a narrower question: *which chain subjects belong to which
local season?*  Every season scores every candidate run of subjects (a window),
and an order-preserving DP picks one window per season, left to right.  A window
is trusted only when it shows real evidence:

* ``name``   -- episode names line up (coverage and average similarity),
* ``stored`` -- the library already carries Bangumi episode ids inside the window,
* ``order``  -- the window is exactly as long as the season, so position decides.

Anything without evidence stays out, and the caller falls back to the flat pool.
"""

from __future__ import annotations

import difflib
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from .match import align_scores, fill_gaps, normalize, variants

Local = List[Dict[str, Any]]
Pool = List[Dict[str, Any]]
Pairs = List[Tuple[int, int]]
Segment = Tuple[Local, Pool, Pairs]

# A window counts as name evidence only when it really lines up: nearly every
# local episode matched, and the matches are more than incidental noise.
MIN_COVERAGE = 0.9
MIN_MEAN = 0.55
# Stored ids are good evidence but can be stale, so names win when both exist.
ID_WEIGHT = 0.85
# Guard rails: keep the window DP small enough to stay instant on a full library.
MAX_SEASONS = 24
MAX_SUBJECTS = 24
MAX_EPISODES = 400
MAX_POOL_EPISODES = 2000


class Plan(NamedTuple):
    """One resolved season -> subject run mapping."""

    segments: List[Segment]
    spans: List[List[int]]
    kinds: List[str]

    def summary(self) -> str:
        """``1:S1->95225 2:S2->109386`` -- one token per local season."""
        parts: List[str] = []
        for index, span in enumerate(self.spans, start=1):
            ids = "+".join(str(sid) for sid in span)
            parts.append("%d:S%d->%s" % (index, index, ids))
        return " ".join(parts)


def _norm_variants(name: str) -> List[str]:
    """Normalised name variants of a local episode, deduplicated."""
    out: List[str] = []
    for value in variants(name):
        norm = normalize(value)
        if norm and norm not in out:
            out.append(norm)
    return out


def _norm_targets(episode: Dict[str, Any]) -> List[str]:
    """Normalised titles a Bangumi episode may be known by."""
    out: List[str] = []
    for key in ("name_cn", "name"):
        norm = normalize(episode.get(key) or "")
        if norm and norm not in out:
            out.append(norm)
    return out


def _pair_similarity(left: Sequence[str], right: Sequence[str]) -> float:
    best = 0.0
    for a in left:
        for b in right:
            if a == b:
                return 1.0
            # Cheap reject: unrelated titles (a Chinese translation against an
            # English original) share no character at all and cannot match.
            if not set(a) & set(b):
                continue
            score = difflib.SequenceMatcher(None, a, b).ratio()
            if score > best:
                best = score
    return best


def _score_rows(local: Local, pool: Pool) -> List[List[float]]:
    """Similarity matrix of one season against one subject."""
    targets = [_norm_targets(episode) for episode in pool]
    return [
        [_pair_similarity(_norm_variants(episode.get("Name") or ""), target) for target in targets]
        for episode in local
    ]


def _stored_pairs(local: Local, pool: Pool) -> Optional[Pairs]:
    """Map by the Bangumi ids the library already stores, if they all land in ``pool``.

    Requires a strictly increasing fit: an id order that jumps around means the
    stored ids belong to something else (Haruhi style airing order), so we bail.
    """
    index: Dict[str, int] = {}
    for position, episode in enumerate(pool):
        index[str(episode.get("id"))] = position
    pairs: Pairs = []
    last = -1
    for position, episode in enumerate(local):
        raw = (episode.get("ProviderIds") or {}).get("Bangumi")
        value = str(raw) if raw not in (None, "") else ""
        target = index.get(value)
        if target is None or target <= last:
            return None
        last = target
        pairs.append((position, target))
    return pairs or None


def _evaluate(local: Local, rows: List[List[float]], pool: Pool,
              threshold: float) -> Optional[Tuple[float, Pairs, str]]:
    """Best evidence for one season inside one candidate window."""
    n, m = len(local), len(pool)
    if not n or not m or n > m:
        return None
    best: Optional[Tuple[float, Pairs, str]] = None
    if m == n:
        pairs = [(i, i) for i in range(n)]
        mean = sum(rows[i][i] for i in range(n)) / n
        best = (mean, pairs, "order")
    else:
        pairs = fill_gaps(align_scores(rows, threshold), n, m)
        if pairs:
            mean = sum(rows[i][j] for i, j in pairs) / len(pairs)
            if len(pairs) / float(n) >= MIN_COVERAGE and mean >= MIN_MEAN:
                # Reward close fits: the same season covering six subjects is
                # weaker evidence than a one-to-one season.
                best = (mean * 2.0 * len(pairs) / (n + m), pairs, "name")
    stored = _stored_pairs(local, pool)
    if stored:
        score = ID_WEIGHT * 2.0 * len(stored) / (n + m)
        if best is None or score > best[0]:
            best = (score, stored, "stored")
    return best


def plan_segments(seasons: Sequence[Local], chain: Sequence[int], bgm: Any,
                  threshold: float = 0.45) -> Optional[Plan]:
    """Map every local season onto a consecutive run of ``chain`` subjects.

    Returns ``None`` whenever the evidence does not add up -- an empty season, no
    usable subject, a season with no usable evidence, or two seasons claiming the
    same episode.  Callers must then keep their flat-pool behaviour.
    """
    groups = [list(season) for season in seasons]
    if len(groups) < 2 or not all(groups):
        return None
    if not 2 <= len(chain) <= MAX_SUBJECTS or len(groups) > MAX_SEASONS:
        return None
    if sum(len(group) for group in groups) > MAX_EPISODES:
        return None
    pools: List[Pool] = []
    subjects: List[int] = []
    for sid in chain:
        episodes = list(bgm.episode_list(sid))
        if episodes:
            subjects.append(sid)
            pools.append(episodes)
    if len(subjects) < 2 or sum(len(pool) for pool in pools) > MAX_POOL_EPISODES:
        return None
    rows = [[_score_rows(group, pool) for pool in pools] for group in groups]

    cache: Dict[Tuple[int, int, int], Optional[Tuple[float, Pairs, str]]] = {}

    def window(season: int, first: int, last: int) -> Optional[Tuple[float, Pairs, str]]:
        key = (season, first, last)
        if key not in cache:
            pool: Pool = []
            for subject in range(first, last + 1):
                pool.extend(pools[subject])
            # One row per local episode; the row spans every subject of the window.
            flat = [[score for subject in range(first, last + 1)
                     for score in rows[season][subject][i]]
                    for i in range(len(groups[season]))]
            cache[key] = _evaluate(groups[season], flat, pool, threshold)
        return cache[key]

    # dp[i][j]: best evidence for seasons 0..i-1 placed inside subjects 0..j-1.
    # Prefix-max semantics, so leading subjects may be skipped (a season need not
    # start at the head of the chain) and so may gaps between two seasons -- a
    # movie, a special, an unaired season in the middle of the chain.
    neg = float("-inf")
    count, width = len(groups), len(subjects)
    dp = [[0.0] * (width + 1)] + [[neg] * (width + 1) for _ in range(count)]
    back: List[List[Optional[Tuple[Any, Pairs, str]]]] = [[None] * (width + 1)
                                                          for _ in range(count + 1)]
    for season in range(count):
        for start in range(width):
            base = dp[season][start]
            if base == neg:
                continue
            for end in range(start, width):
                evidence = window(season, start, end)
                if evidence is None:
                    continue
                total = base + evidence[0]
                if total > dp[season + 1][end + 1]:
                    dp[season + 1][end + 1] = total
                    back[season + 1][end + 1] = (start, evidence[1], evidence[2])
        for column in range(1, width + 1):
            if dp[season + 1][column - 1] > dp[season + 1][column]:
                dp[season + 1][column] = dp[season + 1][column - 1]
                back[season + 1][column] = (column - 1, [], "skip")
    final: Optional[int] = None
    for column in range(width + 1):
        if dp[count][column] == neg:
            continue
        if final is None or dp[count][column] > dp[count][final]:
            final = column
    if final is None:
        return None

    picked: List[Tuple[int, int, Pairs, str]] = []
    season, column = count, final
    while season:
        step = back[season][column]
        if step is None:
            return None
        start, pairs, kind = step
        if kind == "skip":
            column -= 1
            continue
        picked.append((start, column - 1, pairs, kind))
        season, column = season - 1, start
    picked.reverse()

    segments: List[Segment] = []
    spans: List[List[int]] = []
    kinds: List[str] = []
    seen: set = set()
    for (first, end, pairs, kind), group in zip(picked, groups):
        pool: Pool = []
        for subject in range(first, end + 1):
            pool.extend(pools[subject])
        if len(pairs) != len(group):
            return None
        ids = [str(pool[j]["id"]) for _, j in pairs]
        if len(set(ids)) != len(ids) or seen & set(ids):
            return None
        seen.update(ids)
        segments.append((group, pool, pairs))
        spans.append([subjects[subject] for subject in range(first, end + 1)])
        kinds.append(kind)
    return Plan(segments, spans, kinds)
