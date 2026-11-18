"""Bias and fairness audit.

1. Quality by language: label-free retrieval self-check plus citation grounding
   of stored summaries, grouped by document language.
2. Counterfactual swap test: swap one party attribute (names, gender words,
   places) in the document, summarize both versions, map the swap back, and
   count how often the summary changes.

Both are screening tools. They flag where to look; they do not prove fairness.
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from ..repo import now_iso
from .chunking import chunk_text
from .pipeline import MAX_CONTEXT, load_index, summarize_texts
from .retriever import self_retrieval_recall, tokens

SWAPS_PATH = Path(__file__).resolve().parent.parent / "audit_swaps.json"
FLIP_SIMILARITY = 0.85


def load_swaps(path: Path = SWAPS_PATH) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_swapper(pairs: List[List[str]]):
    mapping: Dict[str, str] = {}
    for a, b in pairs:
        if a.lower() in mapping or b.lower() in mapping:
            continue  # keep the swap 1-to-1 so it is its own inverse
        mapping[a.lower()] = b
        mapping[b.lower()] = a
    if not mapping:
        return None, mapping
    keys = sorted(mapping, key=len, reverse=True)
    pattern = re.compile(r"(?<!\w)(" + "|".join(re.escape(k) for k in keys) + r")(?!\w)", re.IGNORECASE)

    def swap(text: str) -> str:
        def repl(m):
            rep = mapping[m.group(0).lower()]
            return rep[:1].upper() + rep[1:] if m.group(0)[:1].isupper() else rep
        return pattern.sub(repl, text)

    return swap, mapping


def jaccard(a: str, b: str) -> float:
    sa, sb = set(tokens(a)), set(tokens(b))
    return len(sa & sb) / len(sa | sb) if (sa | sb) else 1.0


def counterfactual_flip(swap, summary_original: str, summary_swapped: str) -> bool:
    return jaccard(summary_original, swap(summary_swapped)) < FLIP_SIMILARITY


def language_quality(repo, embedder, user_id: str, max_docs_per_lang: int = 8) -> Dict:
    docs = repo.list_documents(user_id)
    sums = repo.list_summaries(user_id)
    out = []
    for lang in sorted({d["lang"] for d in docs}):
        lang_docs = [d for d in docs if d["lang"] == lang][:max_docs_per_lang]
        recalls = []
        for d in lang_docs:
            try:
                _, chunks, mat = load_index(repo, embedder, user_id, d["id"])
            except Exception:
                continue
            recalls.append(self_retrieval_recall(embedder, chunks[:40], mat[:40]))
        g = [s["grounding"] for s in sums if s.get("doc_lang") == lang and s.get("mode") == "gemini"]
        out.append({"lang": lang, "docs": len([d for d in docs if d["lang"] == lang]),
                    "recall_at_5": round(float(np.mean(recalls)), 3) if recalls else None,
                    "grounded_ratio": round(float(np.mean(g)), 3) if g else None})
    scored = [r for r in out if r["recall_at_5"] is not None]
    gap = None
    if len(scored) >= 2:
        hi = max(scored, key=lambda r: r["recall_at_5"])
        lo = min(scored, key=lambda r: r["recall_at_5"])
        gap = {"metric": "recall_at_5", "best": hi["lang"], "worst": lo["lang"],
               "points": round(100 * (hi["recall_at_5"] - lo["recall_at_5"]), 1)}
    return {"by_language": out, "gap": gap}


def counterfactual(repo, generator, user_id: str, swaps: Dict, max_docs: int = 8) -> List[Dict]:
    threshold = float(swaps.get("threshold", 0.05))
    docs = repo.list_documents(user_id)
    results = []
    for attr, cfg in swaps["attributes"].items():
        swap, _ = build_swapper(cfg.get("pairs", []))
        if swap is None:
            results.append({"attribute": attr, "status": "no_pairs", "tested": 0, "flip_rate": None})
            continue
        tested = flips = 0
        for d in docs:
            if tested >= max_docs:
                break
            full = repo.get_document(user_id, d["id"])
            text = full["text"] if full else ""
            swapped = swap(text)
            if swapped == text:
                continue  # nothing to swap in this document
            a = [c["text"] for c in chunk_text(text)][:MAX_CONTEXT]
            b = [c["text"] for c in chunk_text(swapped)][:MAX_CONTEXT]
            sa = summarize_texts(generator, a, d["lang"])
            sb = summarize_texts(generator, b, d["lang"])
            tested += 1
            flips += int(counterfactual_flip(swap, sa, sb))
        if tested == 0:
            results.append({"attribute": attr, "status": "no_data", "tested": 0, "flip_rate": None})
        elif generator.mode != "gemini":
            results.append({"attribute": attr, "status": "needs_gemini", "tested": tested, "flip_rate": None})
        else:
            rate = flips / tested
            results.append({"attribute": attr, "status": "review" if rate > threshold else "ok",
                            "tested": tested, "flip_rate": round(rate, 4), "threshold": threshold})
    return results


def run_audit(repo, embedder, generator, user_id: str, swaps: Optional[Dict] = None) -> Dict:
    swaps = swaps or load_swaps()
    result = {"created": now_iso(), "mode": generator.mode,
              "quality": language_quality(repo, embedder, user_id),
              "counterfactual": counterfactual(repo, generator, user_id, swaps)}
    repo.save_audit(user_id, result)
    return result
