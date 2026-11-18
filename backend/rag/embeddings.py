"""Embedders.

GeminiEmbedder calls the Gemini REST API (multilingual, works across Indian
languages and across languages). LocalEmbedder is an offline fallback built on
hashed character n-grams: it needs no network or key, but it only matches
text in the same language and script, so use it for development and tests.
"""
import time
from typing import List, Optional

import numpy as np
import requests

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


class EmbeddingError(RuntimeError):
    pass


def _normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (mat / norms).astype(np.float32)


class GeminiEmbedder:
    def __init__(self, api_key: str, model: str = "gemini-embedding-001", dim: int = 768,
                 session: Optional[requests.Session] = None):
        if not api_key:
            raise EmbeddingError("GEMINI_API_KEY is not set")
        self.api_key, self.model, self.dim = api_key, model, dim
        self.session = session or requests.Session()
        self.name = f"gemini:{model}:{dim}"

    def _post(self, url: str, body: dict) -> dict:
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        last = ""
        for attempt in range(3):
            resp = self.session.post(url, headers=headers, json=body, timeout=60)
            if resp.status_code == 200:
                return resp.json()
            last = f"{resp.status_code}: {resp.text[:200]}"
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            break
        raise EmbeddingError(f"Gemini embedding request failed ({last})")

    def _embed(self, texts: List[str], task_type: str) -> np.ndarray:
        vectors: List[List[float]] = []
        url = f"{GEMINI_BASE}/models/{self.model}:batchEmbedContents"
        for i in range(0, len(texts), 100):
            part = texts[i:i + 100]
            body = {"requests": [{
                "model": f"models/{self.model}",
                "content": {"parts": [{"text": t}]},
                "taskType": task_type,
                "outputDimensionality": self.dim,
            } for t in part]}
            data = self._post(url, body)
            embeddings = data.get("embeddings", [])
            if len(embeddings) != len(part):
                raise EmbeddingError("Gemini returned an unexpected number of embeddings")
            vectors.extend(e["values"] for e in embeddings)
        # Reduced-dimension outputs are not unit length, so normalize here.
        return _normalize(np.array(vectors, dtype=np.float32))

    def embed_documents(self, texts: List[str]) -> np.ndarray:
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def embed_queries(self, texts: List[str]) -> np.ndarray:
        return self._embed(texts, "RETRIEVAL_QUERY")

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_queries([text])[0]


class LocalEmbedder:
    def __init__(self, n_features: int = 2048):
        from sklearn.feature_extraction.text import HashingVectorizer
        self._vec = HashingVectorizer(
            analyzer="char_wb", ngram_range=(2, 4), n_features=n_features,
            alternate_sign=False, norm="l2", lowercase=True)
        self.name = f"local-char-ngram:{n_features}"

    def _embed(self, texts: List[str]) -> np.ndarray:
        return _normalize(self._vec.transform(texts).toarray().astype(np.float32))

    def embed_documents(self, texts: List[str]) -> np.ndarray:
        return self._embed(texts)

    def embed_queries(self, texts: List[str]) -> np.ndarray:
        return self._embed(texts)

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([text])[0]


def make_embedder(settings):
    if settings.gemini_api_key:
        return GeminiEmbedder(settings.gemini_api_key, settings.gemini_embed_model, settings.embed_dim)
    return LocalEmbedder()
