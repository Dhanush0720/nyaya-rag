"""The RAG pipeline: ingest, ask, summarize, review. Storage, embedder and
generator are passed in, so the same code runs against Atlas + Gemini in
production and against in-memory + offline components in tests."""
from typing import Dict, List, Optional

import numpy as np

from ..repo import now_iso
from .chunking import chunk_text
from .generator import (ExtractiveGenerator, ask_prompt, grounding, parse_review,
                        review_prompt, summarize_prompt)
from .langs import NAMES, detect_lang
from .retriever import retrieve

MAX_CONTEXT = 24
TOP_K = 5


class ReindexNeeded(RuntimeError):
    pass


class NotFound(LookupError):
    pass


def ingest(repo, embedder, user_id: str, title: str, text: str, lang: str = "", doc_type: str = "") -> Dict:
    text = text.replace("\x00", "").strip()
    if len(text) < 20:
        raise ValueError("The document has too little text to index.")
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("The document has no readable text.")
    lang = lang if lang in NAMES else detect_lang(text)
    vectors = embedder.embed_documents([c["text"] for c in chunks])  # may fail: do it before writing
    doc_id = repo.add_document({
        "user_id": user_id, "title": title.strip()[:200] or "Untitled", "lang": lang,
        "doc_type": doc_type.strip()[:60], "n_chunks": len(chunks), "status": "indexed",
        "created": now_iso(), "text": text,
    })
    repo.add_chunks([{
        "user_id": user_id, "doc_id": doc_id, "idx": c["idx"], "text": c["text"],
        "emb": vectors[i].astype(np.float32).tobytes(), "embedder": embedder.name,
    } for i, c in enumerate(chunks)])
    return {"id": doc_id, "lang": lang, "n_chunks": len(chunks)}


def load_index(repo, embedder, user_id: str, doc_id: str):
    doc = repo.get_document(user_id, doc_id)
    if not doc:
        raise NotFound("Document not found")
    chunks = repo.get_chunks(user_id, doc_id)
    if not chunks:
        raise NotFound("Document has no indexed passages")
    if any(c.get("embedder") != embedder.name for c in chunks):
        raise ReindexNeeded("This document was indexed with a different embedding model. Upload it again.")
    mat = np.vstack([np.frombuffer(bytes(c["emb"]), dtype=np.float32) for c in chunks])
    return doc, chunks, mat


def _number(chunks: List[Dict]) -> List[Dict]:
    return [{"n": i + 1, "idx": c["idx"], "text": c["text"]} for i, c in enumerate(chunks)]


def coverage_sample(chunks: List[Dict], limit: int = MAX_CONTEXT) -> List[Dict]:
    """All chunks in order for short documents; evenly spaced chunks for long ones."""
    if len(chunks) <= limit:
        return chunks
    picks = sorted(set(np.linspace(0, len(chunks) - 1, limit).round().astype(int).tolist()))
    return [chunks[i] for i in picks]


def _generate(generator, kind: str, passages: List[Dict], lang: str, question: str = "") -> str:
    if generator.mode == "extractive":
        return generator.ask(passages) if kind == "ask" else generator.summarize(passages)
    prompt = ask_prompt(question, passages) if kind == "ask" else summarize_prompt(passages)
    return generator.generate(prompt, lang)


def summarize_texts(generator, texts: List[str], lang: str) -> str:
    passages = [{"n": i + 1, "idx": i, "text": t} for i, t in enumerate(texts[:MAX_CONTEXT])]
    return _generate(generator, "summarize", passages, lang)


def summarize(repo, embedder, generator, user_id: str, doc_id: str, lang: str) -> Dict:
    doc, chunks, _ = load_index(repo, embedder, user_id, doc_id)
    passages = _number(coverage_sample(chunks))
    answer = _generate(generator, "summarize", passages, lang)
    not_found = answer.strip() == "NOT_FOUND"
    g = grounding("" if not_found else answer, len(passages))
    repo.add_summary({"user_id": user_id, "doc_id": doc_id, "doc_lang": doc["lang"], "lang": lang,
                      "text": answer, "grounding": g["ratio"], "mode": generator.mode,
                      "created": now_iso()})
    return {"answer": "" if not_found else answer, "not_found": not_found, "mode": generator.mode,
            "grounding": g, "passages": passages}


def ask(repo, embedder, generator, user_id: str, doc_id: str, question: str, lang: str) -> Dict:
    doc, chunks, mat = load_index(repo, embedder, user_id, doc_id)
    hits = retrieve(question, embedder.embed_query(question), chunks, mat, k=TOP_K)
    passages = [{"n": i + 1, "idx": h["idx"], "text": h["text"], "score": round(h["score"], 4)}
                for i, h in enumerate(hits)]
    answer = _generate(generator, "ask", passages, lang, question)
    not_found = answer.strip() == "NOT_FOUND"
    g = grounding("" if not_found else answer, len(passages))
    return {"answer": "" if not_found else answer, "not_found": not_found, "mode": generator.mode,
            "grounding": g, "passages": passages}


def review(repo, embedder, generator, user_id: str, doc_id: str, lang: str) -> Dict:
    doc, chunks, _ = load_index(repo, embedder, user_id, doc_id)
    passages = _number(coverage_sample(chunks))
    if generator.mode != "gemini":
        return {"items": [], "mode": generator.mode, "passages": passages,
                "message": "Clause review needs a Gemini API key."}
    raw = generator.generate(review_prompt(passages), lang, json_mode=True)
    by_n = {p["n"]: p for p in passages}
    items = parse_review(raw)
    for it in items:
        try:
            it["passage"] = by_n.get(int(it["clause"]), {}).get("text", "")
        except (TypeError, ValueError):
            it["passage"] = ""
    return {"items": items, "mode": generator.mode, "passages": passages}


def stats(repo, user_id: str) -> Dict:
    docs = repo.list_documents(user_id)
    sums = repo.list_summaries(user_id)
    by_lang: Dict[str, int] = {}
    for d in docs:
        by_lang[d["lang"]] = by_lang.get(d["lang"], 0) + 1
    gem = [s["grounding"] for s in sums if s.get("mode") == "gemini"]
    return {
        "documents": len(docs), "summaries": len(sums), "languages": len(by_lang),
        "by_language": sorted(({"lang": k, "count": v} for k, v in by_lang.items()),
                              key=lambda x: -x["count"]),
        "grounded_pct": round(100 * sum(gem) / len(gem)) if gem else None,
        "recent": docs[:6],
    }
