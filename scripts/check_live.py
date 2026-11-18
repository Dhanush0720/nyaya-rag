"""Live check against YOUR Atlas cluster and Gemini key. Run from the project root:

    python scripts/check_live.py

It tests, in order: Atlas connection + write/read, Gemini embeddings (multilingual and
cross-language retrieval), Gemini answers with citations, and cleans up after itself.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings  # noqa: E402
from backend.rag import pipeline  # noqa: E402
from backend.rag.embeddings import GeminiEmbedder  # noqa: E402
from backend.rag.generator import GeminiGenerator  # noqa: E402
from backend.repo import MongoRepo  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "sample_docs"
fails = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + (f"  ({detail})" if detail else ""))
    if not ok:
        fails.append(name)


def main():
    if not settings.mongodb_uri or not settings.gemini_api_key:
        sys.exit("Set MONGODB_URI and GEMINI_API_KEY in .env first.")
    repo = MongoRepo(settings.mongodb_uri, settings.mongodb_db)
    check("Atlas connection", True, repo.kind)
    emb = GeminiEmbedder(settings.gemini_api_key, settings.gemini_embed_model, settings.embed_dim)
    gen = GeminiGenerator(settings.gemini_api_key, settings.gemini_gen_model)
    user = repo.create_user("Live check", f"live-{int(time.time())}@example.invalid", "x")
    uid, doc_ids = user["id"], {}
    try:
        for lang in ("hi", "te", "ta", "en"):
            text = (DOCS / f"rental_{lang}.txt").read_text(encoding="utf-8")
            doc_ids[lang] = pipeline.ingest(repo, emb, uid, f"rental_{lang}", text)["id"]
        check("Ingest 4 languages into Atlas", len(doc_ids) == 4)

        # Same-language and cross-language retrieval: English question against the Hindi / Telugu / Tamil document.
        q = "When is the security deposit refunded?"
        for lang in ("hi", "te", "ta"):
            r = pipeline.ask(repo, emb, gen, uid, doc_ids[lang], q, "en")
            top2 = [p["text"][:2] for p in r["passages"][:2]]
            check(f"Cross-language retrieval EN question -> {lang} document", "3." in top2, f"top passages start {top2}")
            check(f"Answer cites sources ({lang})", r["grounding"]["ratio"] >= 0.99 and not r["not_found"],
                  f"grounding {r['grounding']['ratio']:.2f}")
            print("      answer:", r["answer"][:160].replace("\n", " "))

        r = pipeline.ask(repo, emb, gen, uid, doc_ids["hi"], "इस अनुबंध में गिरवी रखने की क्या शर्तें हैं?", "hi")
        check("Unanswerable question returns NOT_FOUND (no invention)", r["not_found"], r["answer"][:80])

        s = pipeline.summarize(repo, emb, gen, uid, doc_ids["te"], "te")
        check("Summary in Telugu with citations", s["grounding"]["ratio"] >= 0.8, f"grounding {s['grounding']['ratio']:.2f}")
        print("      summary:", s["answer"][:200].replace("\n", " "))
        rv = pipeline.review(repo, emb, gen, uid, doc_ids["en"], "en")
        check("Clause review returns structured items", len(rv["items"]) > 0, f"{len(rv['items'])} items")
    finally:
        for d in doc_ids.values():
            repo.delete_document(uid, d)
        repo.db.users.delete_one({"email": user["email"]})
        repo.db.summaries.delete_many({"user_id": uid})
    print("\nAll live checks passed." if not fails else f"\n{len(fails)} check(s) failed: {fails}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
