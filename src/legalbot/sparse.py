"""Sparse (lexical) vectors for Qdrant: hashed unigrams + bigrams with log-tf weights.

Qdrant applies IDF at query time (collection configured with the IDF modifier), so
rare legal terms and section numbers ("103", "dowry") dominate the sparse score
without us keeping vocabulary files around.
"""
from __future__ import annotations

import math
import re
import zlib
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+")
_MASK = 0xFFFFF  # 2**20 buckets

STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the this to was were "
    "which who whom with shall may any".split()
)


def features(text: str) -> list[str]:
    toks = [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]
    return toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]


def sparse_vector(text: str) -> tuple[list[int], list[float]]:
    acc: dict[int, float] = {}
    for feat, count in Counter(features(text)).items():
        idx = zlib.crc32(feat.encode()) & _MASK
        acc[idx] = acc.get(idx, 0.0) + 1.0 + math.log(count)
    items = sorted(acc.items())
    return [i for i, _ in items], [v for _, v in items]
