"""BM25 поверх лемм PostgreSQL (`to_tsvector('russian', …)`).

`ts_rank_cd` не учитывает редкость слова (IDF), поэтому на полном кодексе наверх
выходят длинные части с частыми словами. BM25 считается в памяти по снимку
нормативки: на нескольких тысячах фрагментов это микросекунды.
"""

from __future__ import annotations

import math
import re
from collections import Counter

LEXEME = re.compile(r"'((?:[^']|'')+)'(?::([\d,A-D]+))?")


def parse_tsvector(value: str) -> Counter[str]:
    """«'отпуск':3,7 'труд':1» → Counter({'отпуск': 2, 'труд': 1})."""
    counts: Counter[str] = Counter()
    for lexeme, positions in LEXEME.findall(value or ""):
        counts[lexeme.replace("''", "'")] += len(positions.split(",")) if positions else 1
    return counts


class BM25Index:
    def __init__(self, documents: dict[str, Counter[str]], *, k1: float = 1.4, b: float = 0.75):
        self._docs = documents
        self._k1 = k1
        self._b = b
        self._lengths = {doc_id: sum(tf.values()) for doc_id, tf in documents.items()}
        self._avg = (sum(self._lengths.values()) / len(documents)) if documents else 1.0
        df: Counter[str] = Counter()
        for tf in documents.values():
            df.update(tf.keys())
        total = len(documents)
        self._idf = {term: math.log(1 + (total - n + 0.5) / (n + 0.5)) for term, n in df.items()}

    def search(self, terms: Counter[str] | list[str], limit: int = 20) -> dict[str, float]:
        query = list(terms)
        scores: dict[str, float] = {}
        for doc_id, tf in self._docs.items():
            length_norm = self._k1 * (1 - self._b + self._b * self._lengths[doc_id] / self._avg)
            score = 0.0
            for term in query:
                freq = tf.get(term)
                if freq:
                    score += self._idf[term] * freq * (self._k1 + 1) / (freq + length_norm)
            if score > 0:
                scores[doc_id] = score
        best = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]
        return dict(best)
