"""Offline tests: no network, no MongoDB, no Gemini key needed.

Gemini and MongoDB calls are checked against fake sessions (request shape) and
an in-memory repo. Run live checks with scripts/check_live.py.
"""
from pathlib import Path

import numpy as np
import pytest

from backend.rag import audit, pipeline
from backend.rag.chunking import chunk_text
from backend.rag.embeddings import EmbeddingError, GeminiEmbedder, LocalEmbedder
from backend.rag.generator import (ExtractiveGenerator, GeminiGenerator, GenerationError,
                                   grounding, parse_review)
from backend.rag.langs import detect_lang
from backend.rag.retriever import retrieve, self_retrieval_recall
from backend.repo import MemoryRepo
from backend.security import hash_password, make_token, read_token, verify_password

DOCS = Path(__file__).resolve().parent.parent / "sample_docs"


def sample(lang):
    return (DOCS / f"rental_{lang}.txt").read_text(encoding="utf-8")


# question -> clause number that holds the answer
QUESTIONS = {
    "hi": [("सुरक्षा जमा राशि कब लौटाई जाएगी?", 3), ("रखरखाव शुल्क कितना है?", 5),
           ("उप-किराये पर देने के लिए क्या अनुमति चाहिए?", 4), ("नोटिस कितने महीने का देना होगा?", 6),
           ("किराया देरी से देने पर क्या होगा?", 2)],
    "te": [("భద్రతా డిపాజిట్ ఎప్పుడు తిరిగి ఇస్తారు?", 3), ("నిర్వహణ రుసుము ఎంత?", 5),
           ("ఉప-అద్దెకు ఇవ్వడానికి అనుమతి కావాలా?", 4), ("ముందస్తు నోటీసు ఎన్ని నెలలు?", 6),
           ("అద్దె ఆలస్యమైతే ఏమవుతుంది?", 2)],
    "ta": [("பாதுகாப்பு வைப்புத்தொகை எப்போது திருப்பித் தரப்படும்?", 3), ("பராமரிப்புக் கட்டணம் எவ்வளவு?", 5),
           ("துணை வாடகைக்கு விட அனுமதி தேவையா?", 4), ("எத்தனை மாத அறிவிப்பு வழங்க வேண்டும்?", 6),
           ("வாடகை தாமதமானால் என்ன ஆகும்?", 2)],
    "en": [("When is the security deposit refunded?", 3), ("How much is the maintenance charge?", 5),
           ("Can the tenant sublet?", 4), ("How much notice is needed to terminate?", 6),
           ("What happens if rent is late?", 2)],
}


# ---- chunking and language -------------------------------------------------

@pytest.mark.parametrize("lang", ["hi", "te", "ta", "en"])
def test_each_clause_becomes_one_chunk(lang):
    chunks = chunk_text(sample(lang))
    assert len(chunks) == 9  # title + 8 clauses
    assert [c["text"][:2] for c in chunks[1:]] == [f"{i}." for i in range(1, 9)]


def test_plain_prose_is_packed_with_overlap():
    text = " ".join(f"This is sentence number {i} of a long paragraph." for i in range(40))
    chunks = chunk_text(text, max_chars=200)
    assert len(chunks) > 3 and all(len(c["text"]) <= 260 for c in chunks)


@pytest.mark.parametrize("lang,expected", [("hi", "hi"), ("te", "te"), ("ta", "ta"), ("en", "en")])
def test_language_detection(lang, expected):
    assert detect_lang(sample(lang)) == expected


# ---- retrieval -------------------------------------------------------------

@pytest.mark.parametrize("lang", ["hi", "te", "ta", "en"])
def test_retrieval_finds_the_right_clause(lang, capsys):
    emb = LocalEmbedder()
    chunks = chunk_text(sample(lang))
    mat = emb.embed_documents([c["text"] for c in chunks])
    top1 = top2 = 0
    for question, clause in QUESTIONS[lang]:
        hits = retrieve(question, emb.embed_query(question), chunks, mat, k=2)
        wanted = f"{clause}."
        top1 += hits[0]["text"].startswith(wanted)
        top2 += any(h["text"].startswith(wanted) for h in hits)
    print(f"\n[{lang}] retrieval top-1 {top1}/5  top-2 {top2}/5")
    assert top2 >= 4, f"{lang}: only {top2}/5 questions found their clause in the top 2"


def test_self_retrieval_recall_is_high_on_clean_text():
    emb = LocalEmbedder()
    chunks = chunk_text(sample("hi"))
    mat = emb.embed_documents([c["text"] for c in chunks])
    assert self_retrieval_recall(emb, chunks, mat, k=5) >= 0.9


# ---- Gemini request shapes (fake HTTP session) -----------------------------

class FakeResp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code, self._p, self.text = status, payload or {}, text

    def json(self):
        return self._p


class FakeSession:
    def __init__(self, responder):
        self.responder, self.calls = responder, []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self.responder(url, json)


def test_gemini_embedder_batches_and_normalizes():
    def responder(url, body):
        n = len(body["requests"])
        return FakeResp(200, {"embeddings": [{"values": [3.0, 4.0] + [0.0] * 6} for _ in range(n)]})
    sess = FakeSession(responder)
    emb = GeminiEmbedder("KEY", "gemini-embedding-001", dim=8, session=sess)
    out = emb.embed_documents([f"text {i}" for i in range(150)])
    assert out.shape == (150, 8)
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-5)
    assert len(sess.calls) == 2  # 100 + 50
    call = sess.calls[0]
    assert call["url"].endswith("/models/gemini-embedding-001:batchEmbedContents")
    assert call["headers"]["x-goog-api-key"] == "KEY"
    req = call["json"]["requests"][0]
    assert req["taskType"] == "RETRIEVAL_DOCUMENT" and req["outputDimensionality"] == 8
    emb.embed_query("q")
    assert sess.calls[-1]["json"]["requests"][0]["taskType"] == "RETRIEVAL_QUERY"


def test_gemini_embedder_raises_on_http_error():
    sess = FakeSession(lambda u, b: FakeResp(400, text="bad key"))
    with pytest.raises(EmbeddingError):
        GeminiEmbedder("KEY", session=sess).embed_documents(["x"])


def test_gemini_generator_request_and_errors():
    ok = FakeSession(lambda u, b: FakeResp(200, {"candidates": [{"content": {"parts": [{"text": "జవాబు [1]"}]}}]}))
    gen = GeminiGenerator("KEY", "gemini-2.5-flash", session=ok)
    assert gen.generate("Question: x", lang="te") == "జవాబు [1]"
    body = ok.calls[0]["json"]
    assert "Telugu" in body["systemInstruction"]["parts"][0]["text"]
    assert "NOT_FOUND" in body["systemInstruction"]["parts"][0]["text"]
    assert ok.calls[0]["url"].endswith("models/gemini-2.5-flash:generateContent")
    gen.generate("x", json_mode=True)
    assert ok.calls[1]["json"]["generationConfig"]["responseMimeType"] == "application/json"
    bad = GeminiGenerator("KEY", session=FakeSession(lambda u, b: FakeResp(500, text="oops")))
    with pytest.raises(GenerationError):
        bad.generate("x")
    blocked = GeminiGenerator("KEY", session=FakeSession(lambda u, b: FakeResp(200, {"promptFeedback": {"blockReason": "SAFETY"}})))
    with pytest.raises(GenerationError):
        blocked.generate("x")


def test_grounding_counts_valid_citations():
    g = grounding("Rent is due on the 5th [1]. The deposit is returned in 30 days [3]. Unsupported claim. Bad cite [9].", 4)
    assert g["sentences"] == 4 and g["cited"] == 2 and g["invalid_citations"] == [9]


def test_grounding_is_not_fooled_by_clause_numbers_abbreviations_or_late_citations():
    g = grounding("3. The deposit is returned in 30 days. [3] A charge of Rs. 1,500 is paid monthly [5].", 8)
    assert g["sentences"] == 2 and g["cited"] == 2
    g = grounding("किराया 5 तारीख तक देना होगा। [1] जमा राशि 30 दिनों में लौटाई जाएगी। [3]", 8)
    assert g["sentences"] == 2 and g["cited"] == 2


def test_parse_review_handles_fences_and_bad_values():
    raw = '```json\n[{"clause": 2, "title": "Late rent", "risk": "MEDIUM", "note": "No notice."}, {"risk": "weird"}]\n```'
    items = parse_review(raw)
    assert items[0]["risk"] == "medium" and items[1]["risk"] == "low"
    assert parse_review("not json") == []


# ---- end-to-end pipeline on the in-memory repo ----------------------------

def make_env():
    return MemoryRepo(), LocalEmbedder(), ExtractiveGenerator()


def test_end_to_end_ask_and_summarize():
    repo, emb, gen = make_env()
    info = pipeline.ingest(repo, emb, "u1", "Rental", sample("hi"))
    assert info["lang"] == "hi" and info["n_chunks"] == 9
    res = pipeline.ask(repo, emb, gen, "u1", info["id"], "सुरक्षा जमा राशि कब लौटाई जाएगी?", "hi")
    assert "30" in res["passages"][0]["text"] and "[1]" in res["answer"]
    assert res["grounding"]["ratio"] == 1.0
    s = pipeline.summarize(repo, emb, gen, "u1", info["id"], "hi")
    assert s["grounding"]["ratio"] == 1.0 and len(s["passages"]) == 9
    st = pipeline.stats(repo, "u1")
    assert st["documents"] == 1 and st["summaries"] == 1 and st["languages"] == 1


def test_users_cannot_read_each_others_documents():
    repo, emb, gen = make_env()
    info = pipeline.ingest(repo, emb, "alice", "Rental", sample("en"))
    with pytest.raises(pipeline.NotFound):
        pipeline.ask(repo, emb, gen, "mallory", info["id"], "When is the deposit refunded?", "en")
    assert repo.delete_document("mallory", info["id"]) is False
    assert repo.list_documents("mallory") == []


def test_reindex_needed_when_embedder_changes():
    repo, emb, gen = make_env()
    info = pipeline.ingest(repo, emb, "u1", "Rental", sample("en"))

    class Other(LocalEmbedder):
        def __init__(self):
            super().__init__(n_features=1024)
    with pytest.raises(pipeline.ReindexNeeded):
        pipeline.ask(repo, Other(), gen, "u1", info["id"], "deposit?", "en")


def test_long_documents_are_sampled_evenly():
    chunks = [{"idx": i, "text": f"c{i}"} for i in range(100)]
    picked = pipeline.coverage_sample(chunks, limit=24)
    assert len(picked) <= 24 and picked[0]["idx"] == 0 and picked[-1]["idx"] == 99


def test_ingest_rejects_empty_text_and_keeps_db_clean():
    repo, emb, _ = make_env()
    with pytest.raises(ValueError):
        pipeline.ingest(repo, emb, "u1", "Empty", "  short ")
    assert repo.list_documents("u1") == []


# ---- audit -----------------------------------------------------------------

def test_swapper_is_its_own_inverse_and_keeps_case():
    swap, _ = audit.build_swapper([["Ramesh", "Rahim"], ["his", "her"]])
    text = "Ramesh gave his key to Rahim. His friend left."
    out = swap(text)
    assert out == "Rahim gave her key to Ramesh. Her friend left."
    assert swap(out) == text


class EchoGen:
    mode = "gemini"
    def generate(self, user, lang="en", json_mode=False, temperature=0.0):
        return user


class BiasedGen:
    mode = "gemini"
    def generate(self, user, lang="en", json_mode=False, temperature=0.0):
        return "Short." if "Chennai" in user else user


def _audit_repo():
    repo, emb, _ = make_env()
    pipeline.ingest(repo, emb, "u1", "Rental", sample("en"))
    return repo, emb


def test_counterfactual_flags_a_biased_model_and_passes_a_fair_one():
    repo, emb = _audit_repo()
    swaps = audit.load_swaps()
    fair = {r["attribute"]: r for r in audit.counterfactual(repo, EchoGen(), "u1", swaps)}
    assert fair["region"]["status"] == "ok" and fair["region"]["flip_rate"] == 0.0
    biased = {r["attribute"]: r for r in audit.counterfactual(repo, BiasedGen(), "u1", swaps)}
    assert biased["region"]["status"] == "review" and biased["region"]["flip_rate"] == 1.0
    assert biased["caste"]["status"] == "no_pairs"      # no pairs configured
    assert biased["religion"]["status"] == "no_data"    # document has none of these names


def test_extractive_mode_is_not_reported_as_a_pass():
    repo, emb = _audit_repo()
    res = {r["attribute"]: r for r in audit.counterfactual(repo, ExtractiveGenerator(), "u1", audit.load_swaps())}
    assert res["region"]["status"] == "needs_gemini" and res["region"]["flip_rate"] is None


def test_language_quality_reports_gap_across_languages():
    repo, emb, _ = make_env()
    for lang in ("hi", "te", "en"):
        pipeline.ingest(repo, emb, "u1", lang, sample(lang))
    q = audit.language_quality(repo, emb, "u1")
    assert {r["lang"] for r in q["by_language"]} == {"hi", "te", "en"}
    assert q["gap"] is not None and q["gap"]["points"] >= 0


# ---- security --------------------------------------------------------------

def test_password_hashing_and_tokens():
    h = hash_password("correct horse")
    assert verify_password("correct horse", h) and not verify_password("wrong", h)
    assert not verify_password("x", "garbage")
    token = make_token("user-1", "secret")
    assert read_token(token, "secret") == "user-1"
    assert read_token(token, "other-secret") is None
    assert read_token(token[:-2] + "xx", "secret") is None
    assert read_token(make_token("user-1", "secret", hours=-1), "secret") is None


# ---- HTTP API (skipped when FastAPI/httpx are not installed) ---------------

def test_http_api_flow():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    pytest.importorskip("multipart")
    from fastapi.testclient import TestClient
    from backend.main import app
    c = TestClient(app)
    assert c.get("/api/documents").status_code == 401
    r = c.post("/api/auth/register", json={"name": "A", "email": "a@example.com", "password": "password123"})
    assert r.status_code == 200
    assert c.post("/api/auth/register", json={"name": "A", "email": "a@example.com", "password": "password123"}).status_code == 409
    assert c.post("/api/auth/login", json={"email": "a@example.com", "password": "nope-nope"}).status_code == 401
    token = c.post("/api/auth/login", json={"email": "a@example.com", "password": "password123"}).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    doc = c.post("/api/documents", data={"title": "Rental", "text": sample("hi")}, headers=h).json()
    ans = c.post(f"/api/documents/{doc['id']}/ask",
                 json={"question": "सुरक्षा जमा राशि कब लौटाई जाएगी?", "lang": "hi"}, headers=h)
    assert ans.status_code == 200 and "30" in ans.json()["passages"][0]["text"]
    other = c.post("/api/auth/register", json={"name": "B", "email": "b@example.com", "password": "password123"}).json()["token"]
    ho = {"Authorization": f"Bearer {other}"}
    assert c.get(f"/api/documents/{doc['id']}", headers=ho).status_code == 404
    assert c.post(f"/api/documents/{doc['id']}/summarize", json={"lang": "hi"}, headers=ho).status_code == 404
