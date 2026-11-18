"""Hybrid retrieval: dense cosine similarity plus a light lexical stem match.

The lexical part helps with numbers, dates and exact terms ("15 days") that
embeddings can blur. Stems are the first 5 characters of each word, which is a
crude but useful way to survive Indian-language suffixes.
"""
import re
from typing import Dict, List

import numpy as np

_TOKEN = re.compile(r"[^\s.,;:!?()\[\]{}\"'।॥\-/]+")


def tokens(text: str) -> List[str]:
    return _TOKEN.findall(text.lower())


def lexical_score(query: str, text: str) -> float:
    q = [t[:5] for t in tokens(query) if len(t) >= 2]
    if not q:
        return 0.0
    stems = {t[:5] for t in tokens(text)}
    return sum(1 for s in q if s in stems) / len(q)


def retrieve(query: str, qvec: np.ndarray, chunks: List[Dict], mat: np.ndarray,
             k: int = 5, alpha: float = 0.25) -> List[Dict]:
    """Return the top-k chunks as dicts with idx, text, score, dense and lexical parts."""
    if mat.size == 0:
        return []
    dense = mat @ qvec
    lex = np.array([lexical_score(query, c["text"]) for c in chunks], dtype=np.float32)
    score = (1 - alpha) * dense + alpha * lex
    order = np.argsort(-score)[:k]
    return [{
        "idx": chunks[i]["idx"], "text": chunks[i]["text"],
        "score": float(score[i]), "dense": float(dense[i]), "lexical": float(lex[i]),
    } for i in order]


def self_retrieval_recall(embedder, chunks: List[Dict], mat: np.ndarray, k: int = 5) -> float:
    """Label-free sanity check of the embedder on a document.

    Each chunk's middle part is used as a query. Recall@k is the share of
    queries whose own chunk appears in the top k. It shows whether the
    embedder separates this language's text at all; it is not a substitute
    for a gold question set.
    """
    if len(chunks) == 0:
        return 0.0
    queries = []
    for c in chunks:
        words = c["text"].split()
        lo, hi = len(words) // 5, max(len(words) - len(words) // 5, len(words) // 5 + 1)
        queries.append(" ".join(words[lo:hi]) or c["text"])
    qmat = embedder.embed_queries(queries)
    sims = qmat @ mat.T
    hits = 0
    for i in range(len(chunks)):
        top = np.argsort(-sims[i])[:k]
        hits += int(i in top)
    return hits / len(chunks)
