# Nyaya RAG

Multilingual legal document assistant: login, dashboard, cited summaries, Q&A, clause review and a bias audit.
Backend: FastAPI + MongoDB Atlas + Gemini. Frontend: plain HTML/CSS/JS, responsive, 8 interface languages.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # then fill in the values
python -m pytest -q                                    # offline tests, no keys needed
python scripts/check_live.py                           # REAL test against your Atlas + Gemini
uvicorn backend.main:app --reload                      # open http://localhost:8000
```

In `.env`: `MONGODB_URI` (Atlas > Connect > Drivers; add your IP under Network Access),
`GEMINI_API_KEY` (aistudio.google.com/apikey), and a long random `JWT_SECRET`.
Without these the app still starts, with in-memory storage and an offline extractive mode, and says so on screen.

## How the RAG works

1. Upload `.txt`, `.pdf` (text layer) or `.docx`. Text is split by numbered clause.
2. Each chunk is embedded (Gemini, 768-dim) and stored in MongoDB with the user id.
3. A question is embedded, scored against that document's chunks (cosine + lexical match), top 5 go to Gemini.
4. Gemini must cite passages as `[n]` or reply `NOT_FOUND`. The app counts cited sentences and flags invalid citations.
5. Clicking a citation jumps to the source passage.

Similarity is computed in the app per document, so Atlas Vector Search is not required.
For corpus-wide search across thousands of documents, add an Atlas vector index on `chunks.emb`.

## Known limits

- Scanned PDFs and images need OCR (not included).
- The audit is a screening tool, not proof of fairness. Edit `backend/audit_swaps.json` with swap terms for your
  jurisdiction; the caste list is empty on purpose.
- Interface translations are machine-written. Have native speakers review `frontend/i18n.js`.
- Not legal advice. Outputs need lawyer review.
