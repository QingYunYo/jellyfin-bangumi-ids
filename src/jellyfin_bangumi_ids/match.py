"""Episode-name matching: normalisation, similarity, monotonic alignment."""
from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any, Dict, List, Sequence, Tuple

SPECIAL_RE = re.compile(
    r"(番外|OVA|OAD|特别篇|特別篇|总集篇|總集篇|特典|花絮|预告|預告|NCOP|NCED|(^|[^A-Za-z])SP\d*)",
    re.IGNORECASE,
)
BRACKET_TITLE_RE = re.compile(r"[「『](.+?)[」』]")
DROP_NOISE_RE = re.compile(r"\[[^\]]*\]|S\d{1,2}E\d{1,3}|#\d+", re.IGNORECASE)
SEPARATORS = (" - ", " – ", " — ", "／", "/")


def is_special(name: str) -> bool:
    """True for OVA / SP / recap style episodes we must drop from the pool."""
    return bool(name and SPECIAL_RE.search(name))


# Full-width ``８６``/``！`` must fold to ASCII, and kana (``ダンダダン``) must survive:
# stripping them left a lot of Japanese titles as an empty string -> similarity 0.
_KEEP_RE = re.compile(r"[^0-9a-z\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")


def normalize(text: str) -> str:
    """NFKC + casefold, then keep letters/digits/kana/CJK. Punctuation differs between sources."""
    folded = unicodedata.normalize("NFKC", text or "").casefold()
    return _KEEP_RE.sub("", folded)


def title_keys(series: Dict[str, Any]) -> List[str]:
    """Every title a library may store for one show: localized name and original title."""
    out: List[str] = []
    for key in ("Name", "OriginalTitle"):
        value = (series.get(key) or "").strip()
        if value and normalize(value) and value not in out:
            out.append(value)
    if not out:
        fallback = (series.get("Name") or "").strip()
        if fallback:
            out.append(fallback)
    return out


def similarity(a: str, b: str) -> float:
    left, right = normalize(a), normalize(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def variants(name: str) -> List[str]:
    """Candidate titles hidden in a scraped episode name.

    Local libraries rarely keep the plain title: ``S01E18 - [Group] 白夜`` or
    ``进击的巨人 - S03E18 - 白夜``. Every plausible slice is tried.
    """
    raw = (name or "").strip()
    out: List[str] = []

    def add(value: str) -> None:
        value = (value or "").strip(" .-–—:：")
        if value and value not in out:
            out.append(value)

    add(raw)
    for hit in BRACKET_TITLE_RE.findall(raw):
        add(hit)
    add(DROP_NOISE_RE.sub(" ", raw))
    for sep in SEPARATORS:
        if sep in raw:
            add(raw.split(sep)[-1])
    return out


def episode_similarity(local_name: str, bgm_episode: Dict[str, Any]) -> float:
    """Best similarity between a local name and a Bangumi episode record."""
    targets = [x for x in (bgm_episode.get("name_cn"), bgm_episode.get("name")) if x]
    best = 0.0
    for cand in variants(local_name):
        for target in targets:
            score = similarity(cand, target)
            if score > best:
                best = score
    return best


def align(local_names: Sequence[str], pool: Sequence[Dict[str, Any]],
          threshold: float = 0.45) -> List[Tuple[int, int]]:
    """Monotonic best alignment (order preserving), maximising summed similarity."""
    n, m = len(local_names), len(pool)
    if not n or not m:
        return []
    scores = [[episode_similarity(local_names[i], pool[j]) for j in range(m)] for i in range(n)]
    neg = float("-inf")
    dp = [[neg] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(n + 1):
        row, prev = dp[i], dp[i - 1] if i else None
        for j in range(m + 1):
            if i and dp[i - 1][j] > row[j]:
                row[j] = dp[i - 1][j]
                back[i][j] = ("up", i - 1, j)
            if j and row[j - 1] > row[j]:
                row[j] = row[j - 1]
                back[i][j] = ("left", i, j - 1)
            if i and j and scores[i - 1][j - 1] >= threshold:
                cand = dp[i - 1][j - 1] + scores[i - 1][j - 1]
                if cand > row[j]:
                    row[j] = cand
                    back[i][j] = ("diag", i - 1, j - 1)
    pairs: List[Tuple[int, int]] = []
    i, j = n, m
    while i or j:
        step = back[i][j]
        if step is None:
            break
        kind, pi, pj = step
        if kind == "diag":
            pairs.append((pi, pj))
        i, j = pi, pj
    pairs.reverse()
    return pairs


def fill_gaps(pairs: Sequence[Tuple[int, int]], n: int, m: int) -> List[Tuple[int, int]]:
    """Pair leftovers 1:1 when the unmatched run is equally long on both sides."""
    out = list(pairs)
    prev_i, prev_j = -1, -1
    for i, j in list(pairs) + [(n, m)]:
        gap_i, gap_j = i - prev_i - 1, j - prev_j - 1
        if gap_i == gap_j and gap_i > 0:
            out.extend((prev_i + 1 + k, prev_j + 1 + k) for k in range(gap_i))
        prev_i, prev_j = i, j
    out.sort()
    return out


def name_match(left: str, right: str) -> bool:
    """Loose title guard: one title must contain the other after normalisation."""
    a, b = normalize(left), normalize(right)
    return bool(a and b and (a in b or b in a))


_PREFIX = re.compile(r"^\s*[Ss]\d{1,2}[Ee]\d{1,4}\s*[-–—:]+\s*")
_BRACKET = re.compile(r"[\[【(（][^\]】)）]{0,40}[\]】)）]")


def clean_title(name: str) -> str:
    """Drop release-group noise that leaks in from file names ("S01E01 - [Group] ...")."""
    text = _PREFIX.sub("", name or "")
    text = _BRACKET.sub(" ", text)
    return " ".join(text.split())
