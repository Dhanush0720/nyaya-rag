"""Structure-aware chunking.

Legal text is split by numbered clause first, because a clause is the unit a
reader wants cited. Text without clause numbers falls back to sentence packing
with one sentence of overlap.
"""
import re
from typing import Dict, List

_CLAUSE_START = re.compile(r"(?m)^[ \t]*(?:\d{1,3}[\.\)]|\(\w{1,3}\)|Clause\s+\d+[\.:]?)[ \t]+")
_SENTENCE_END = re.compile(r"(?<=[।॥\.\?\!])\s+|\n+")


def split_sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE_END.split(text) if s and s.strip()]


def split_clauses(text: str) -> List[str]:
    starts = [m.start() for m in _CLAUSE_START.finditer(text)]
    if len(starts) < 3:
        return []
    blocks = []
    if text[: starts[0]].strip():
        blocks.append(text[: starts[0]].strip())
    for i, s in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        block = " ".join(text[s:end].split())
        if block:
            blocks.append(block)
    return blocks


def _pack_sentences(sentences: List[str], max_chars: int, overlap: bool) -> List[str]:
    chunks: List[str] = []
    current: List[str] = []
    size = 0
    for sent in sentences:
        if current and size + len(sent) + 1 > max_chars:
            chunks.append(" ".join(current))
            current = [current[-1]] if overlap and len(current[-1]) < max_chars // 2 else []
            size = sum(len(c) + 1 for c in current)
        current.append(sent)
        size += len(sent) + 1
    if current:
        chunks.append(" ".join(current))
    return chunks


def chunk_text(text: str, max_chars: int = 600) -> List[Dict]:
    text = text.replace("\r\n", "\n").replace("\x00", "").strip()
    if not text:
        return []
    texts: List[str] = []
    clauses = split_clauses(text)
    if clauses:
        for block in clauses:
            if len(block) <= max_chars:
                texts.append(block)
            else:
                texts.extend(_pack_sentences(split_sentences(block), max_chars, overlap=False))
    else:
        texts = _pack_sentences(split_sentences(text), max_chars, overlap=True)
    return [{"idx": i, "text": t} for i, t in enumerate(t for t in texts if t.strip())]
