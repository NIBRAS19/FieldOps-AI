"""Lexical retrieval over already-authorized chunks. Embeddings/pgvector are a later, measured phase."""
import re
from dataclasses import dataclass

STOP = set("the and for with that this have has had was were are not but you your from into when then than they them their there what "
           "which would could should will can may need please after before since about also just very any all our out one two new been being its".split())


def tokenize(s: str) -> set[str]:
    return {w for w in re.sub(r"[^a-z0-9 ]+", " ", s.lower()).split() if len(w) > 2 and w not in STOP}


@dataclass(frozen=True)
class ChunkRef:
    key: str
    source_key: str
    source_title: str
    source_version: int
    source_owner: str
    section: str
    text: str
    keywords: str = ""
    tags: tuple[str, ...] = ()
    conflicts_with: str | None = None


def search(query: str, chunks: list[ChunkRef], top_k: int) -> tuple[list[tuple[ChunkRef, int]], int]:
    """Return (selected [(chunk, score)], candidate_count). Threshold is relative to the best score."""
    qt = tokenize(query)
    scored = []
    for c in chunks:
        ct = tokenize(f"{c.section} {c.text} {c.keywords}")
        score = len(qt & ct)
        if score >= 2:
            scored.append((c, score))
    scored.sort(key=lambda x: (-x[1], x[0].key))
    if not scored:
        return [], 0
    floor = max(2, -(-scored[0][1] // 2))  # ceil(top/2)
    return [s for s in scored if s[1] >= floor][:top_k], len(scored)
