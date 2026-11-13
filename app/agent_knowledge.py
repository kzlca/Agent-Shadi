"""Small, dependency-free retrieval for Agent Shadi's product knowledge.

Knowledge is authored as Markdown, split on headings, and retrieved per turn.
This avoids placing the whole manual into an 8k local-model context window.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = ROOT / "knowledge"
TOKEN_RE = re.compile(r"[\w\u0600-\u06ff]+", re.UNICODE)


def _tokens(value: str) -> list[str]:
    return [x.lower() for x in TOKEN_RE.findall(str(value or "")) if len(x) > 1]


def _sections():
    docs = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        if path.name.upper() == "INDEX.MD":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        current_title = path.stem.replace("-", " ").title()
        lines: list[str] = []
        for line in text.splitlines():
            if line.startswith("## ") and lines:
                body = "\n".join(lines).strip()
                if body:
                    docs.append({"source": path.name, "title": current_title, "text": body})
                current_title = line[3:].strip()
                lines = [line]
            else:
                if line.startswith("# "):
                    continue
                lines.append(line)
        body = "\n".join(lines).strip()
        if body:
            docs.append({"source": path.name, "title": current_title, "text": body})
    return docs


def retrieve_agent_knowledge(query: str, limit: int = 4, max_chars: int = 5200) -> list[dict[str, str]]:
    """Return relevant Markdown sections using lightweight BM25-style ranking."""
    docs = _sections()
    q = _tokens(query)
    if not docs or not q:
        return []
    qset = set(q)
    tokenized = [_tokens(d["title"] + " " + d["source"] + " " + d["text"]) for d in docs]
    lengths = [len(t) for t in tokenized]
    avg_len = sum(lengths) / max(1, len(lengths))
    df = Counter(term for terms in tokenized for term in set(terms))
    scored = []
    for doc, terms, length in zip(docs, tokenized, lengths):
        counts = Counter(terms)
        score = 0.0
        for term in qset:
            freq = counts.get(term, 0)
            if not freq:
                continue
            idf = math.log(1 + (len(docs) - df[term] + 0.5) / (df[term] + 0.5))
            denom = freq + 1.2 * (0.25 + 0.75 * length / max(1.0, avg_len))
            score += idf * (freq * 2.2) / denom
        title_hits = len(qset.intersection(_tokens(doc["title"])))
        score += title_hits * 1.8
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = []
    used = 0
    for score, doc in scored[:max(1, min(8, limit))]:
        body = doc["text"].strip()
        remaining = max_chars - used
        if remaining <= 250:
            break
        body = body[:remaining]
        selected.append({"source": doc["source"], "title": doc["title"], "text": body})
        used += len(body)
    return selected
