"""FastAPI app: auth, documents, RAG endpoints, audit, and the static frontend.

Run from the project root:  uvicorn backend.main:app --reload
"""
import re
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import ROOT, settings
from .extract import extract_text
from .rag import audit as audit_mod
from .rag import pipeline
from .rag.embeddings import EmbeddingError, make_embedder
from .rag.generator import ExtractiveGenerator, GeminiGenerator, GenerationError
from .rag.langs import NAMES
from .repo import DuplicateEmail, MemoryRepo, MongoRepo
from .security import hash_password, make_token, read_token, verify_password

app = FastAPI(title="Nyaya RAG", docs_url="/api/docs", openapi_url="/api/openapi.json")

repo = MongoRepo(settings.mongodb_uri, settings.mongodb_db) if settings.mongodb_uri else MemoryRepo()
embedder = make_embedder(settings)
generator = (GeminiGenerator(settings.gemini_api_key, settings.gemini_gen_model)
             if settings.gemini_api_key else ExtractiveGenerator())

if repo.kind == "memory":
    print("WARNING: MONGODB_URI is not set. Using in-memory storage; data is lost on restart.")
if settings.jwt_secret_is_ephemeral:
    print("WARNING: JWT_SECRET is not set. Logins will be invalidated on every restart.")
if len(settings.jwt_secret) < 32:
    print("WARNING: JWT_SECRET is shorter than 32 characters. Use a long random value.")
if generator.mode != "gemini":
    print("WARNING: GEMINI_API_KEY is not set. Using offline extractive mode (no real summaries).")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DUMMY_HASH = hash_password("not-a-real-password")


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src 'self' data:; frame-ancestors 'none'")
    return response


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(max_length=200)
    password: str = Field(min_length=8, max_length=200)


class LoginIn(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    lang: str = "en"


class LangIn(BaseModel):
    lang: str = "en"


def current_user(authorization: str = Header(default="")):
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not signed in")
    user_id = read_token(authorization[7:].strip(), settings.jwt_secret)
    user = repo.get_user(user_id) if user_id else None
    if not user:
        raise HTTPException(401, "Session expired. Please sign in again.")
    return user


def run(fn, *args):
    try:
        return fn(*args)
    except pipeline.NotFound as e:
        raise HTTPException(404, str(e))
    except pipeline.ReindexNeeded as e:
        raise HTTPException(409, str(e))
    except (EmbeddingError, GenerationError) as e:
        raise HTTPException(502, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


def _lang(code: str) -> str:
    return code if code in NAMES else "en"


def _public(user: dict) -> dict:
    return {"id": user["id"], "name": user["name"], "email": user["email"]}


# ---- config and auth -------------------------------------------------------

@app.get("/api/config")
def get_config():
    return {"mode": generator.mode, "embedder": embedder.name, "storage": repo.kind, "languages": NAMES}


@app.post("/api/auth/register")
def register(body: RegisterIn):
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address")
    try:
        user = repo.create_user(body.name.strip(), email, hash_password(body.password))
    except DuplicateEmail:
        raise HTTPException(409, "An account with this email already exists")
    return {"token": make_token(user["id"], settings.jwt_secret, settings.token_hours), "user": _public(user)}


@app.post("/api/auth/login")
def login(body: LoginIn):
    user = repo.find_user_by_email(body.email.strip().lower())
    if not user:
        verify_password(body.password, _DUMMY_HASH)  # keep timing similar
        raise HTTPException(401, "Wrong email or password")
    if not verify_password(body.password, user["pw_hash"]):
        raise HTTPException(401, "Wrong email or password")
    return {"token": make_token(user["id"], settings.jwt_secret, settings.token_hours), "user": _public(user)}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return _public(user)


# ---- documents -------------------------------------------------------------

@app.post("/api/documents")
def create_document(title: str = Form(""), lang: str = Form(""), doc_type: str = Form(""),
                    text: str = Form(""), file: Optional[UploadFile] = File(None),
                    user=Depends(current_user)):
    content = text
    if file is not None and file.filename:
        data = file.file.read(settings.max_upload_bytes + 1)
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(413, "File is larger than 5 MB")
        try:
            content = extract_text(file.filename, data)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception:
            raise HTTPException(400, "Could not read this file")
        title = title or file.filename
    if not content.strip():
        raise HTTPException(400, "Upload a file or paste some text")
    if len(content) > settings.max_chars:
        raise HTTPException(413, "Document is too long (limit 300,000 characters)")
    return run(pipeline.ingest, repo, embedder, user["id"], title or "Pasted text", content, lang, doc_type)


@app.get("/api/documents")
def list_documents(user=Depends(current_user)):
    return repo.list_documents(user["id"])


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str, user=Depends(current_user)):
    doc = repo.get_document(user["id"], doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str, user=Depends(current_user)):
    if not repo.delete_document(user["id"], doc_id):
        raise HTTPException(404, "Document not found")
    return {"ok": True}


@app.post("/api/documents/{doc_id}/summarize")
def summarize(doc_id: str, body: LangIn, user=Depends(current_user)):
    return run(pipeline.summarize, repo, embedder, generator, user["id"], doc_id, _lang(body.lang))


@app.post("/api/documents/{doc_id}/review")
def review(doc_id: str, body: LangIn, user=Depends(current_user)):
    return run(pipeline.review, repo, embedder, generator, user["id"], doc_id, _lang(body.lang))


@app.post("/api/documents/{doc_id}/ask")
def ask(doc_id: str, body: AskIn, user=Depends(current_user)):
    return run(pipeline.ask, repo, embedder, generator, user["id"], doc_id, body.question.strip(),
               _lang(body.lang))


# ---- dashboard and audit ---------------------------------------------------

@app.get("/api/stats")
def stats(user=Depends(current_user)):
    return pipeline.stats(repo, user["id"])


@app.post("/api/audit/run")
def run_audit(user=Depends(current_user)):
    return run(audit_mod.run_audit, repo, embedder, generator, user["id"])


@app.get("/api/audit/latest")
def latest_audit(user=Depends(current_user)):
    return repo.latest_audit(user["id"]) or {}


app.mount("/", StaticFiles(directory=str(ROOT / "frontend"), html=True), name="frontend")
