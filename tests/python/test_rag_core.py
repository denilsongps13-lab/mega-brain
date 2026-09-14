"""Tests for RAG chunker + in-house BM25 index (no network, skip_vectors=True).

MD chunks must be writable under repo BASE_DIR because chunker computes
``relative_to(BASE_DIR)``. The test writes a temp file under ``tests/python``
(a sibling of BASE_DIR) and cleans it up afterwards.

Section bodies are kept above ``MIN_CHUNK_SIZE`` (100 chars) so the size-based
recursive splitter actually produces chunks (short docs are intentionally
dropped by the chunker).
"""
from pathlib import Path

from engine.intelligence.rag.chunker import chunk_markdown
from engine.intelligence.rag.hybrid_index import BM25Index, HybridIndex

BASE_DIR = Path(__file__).resolve().parents[2]

_LONG_BODY = (
    "The Alpha method relies on daily systematic investing, position sizing, "
    "and a disciplined review cadence that protects the downside while chasing "
    "compounding over long horizons without emotional interference.\n\n"
    "Practitioners journal every trade, separate process from outcome, and "
    "continue refining allocation rules based on measured edge rather than "
    "short-term noise from the market.\n\n"
)

MARKDOWN = (
    "# Alpha Course\n\n"
    "## Foundations\n\n" + _LONG_BODY +
    "## Tactics\n\n" + _LONG_BODY +
    "## Deep Dive\n\n" + _LONG_BODY
)


def _repo_local_tmp_md(name: str, content: str) -> Path:
    target = BASE_DIR / "tests" / "python" / name
    target.write_text(content, encoding="utf-8")
    return target


def test_chunk_markdown_splits_sections():
    p = _repo_local_tmp_md("_tmp_chunk_test.md", MARKDOWN)
    try:
        chunks = chunk_markdown(p, semantic=False)
        assert isinstance(chunks, list)
        assert len(chunks) >= 1
        assert all(hasattr(c, "text") and c.text for c in chunks)
        assert all(c.bucket == "external" for c in chunks)
    finally:
        p.unlink(missing_ok=True)


def test_chunk_markdown_returns_empty_for_missing_file(tmp_path: Path):
    miss = tmp_path / "nope.md"
    chunks = chunk_markdown(miss, semantic=False)
    # Missing file yields [] (chunker catches OSError) — never raises.
    assert isinstance(chunks, list)


def test_bm25_build_and_query():
    docs = [
        "alpha is a systematic strategy for daily investing",
        "the dip is bought by momentum traders",
        "andrew theta hour is a known trading heuristic",
    ]
    idx = BM25Index()
    idx.build(docs)
    hits = idx.query("alpha systematic strategy", top_k=3)
    assert len(hits) >= 1
    assert isinstance(hits[0], tuple)
    assert hits[0][0] == 0  # most relevant doc is doc #0


def test_hybrid_index_build_skip_vectors():
    p = _repo_local_tmp_md("_tmp_chunk_mix.md", MARKDOWN)
    try:
        chunks = chunk_markdown(p, semantic=False)
        idx = HybridIndex()
        stats = idx.build(chunks, skip_vectors=True)
        assert stats["total_chunks"] == len(chunks)
        # With skip_vectors=True no OpenAI call happens: vectors stay empty.
        assert len(idx.vector.vectors) == 0
        assert idx.bm25.n_docs >= 1
    finally:
        (BASE_DIR / "tests" / "python" / "_tmp_chunk_mix.md").unlink(missing_ok=True)


def test_hybrid_index_save_load(tmp_path: Path):
    p = _repo_local_tmp_md("_tmp_chunk_saveload.md", MARKDOWN)
    try:
        chunks = chunk_markdown(p, semantic=False)
        idx = HybridIndex()
        idx.build(chunks, skip_vectors=True)
        d = tmp_path / "rag_index"
        idx.save(d)
        assert (d / "chunks.json").exists()
        assert (d / "bm25.json").exists()

        idx2 = HybridIndex()
        assert idx2.load(d) is True
        assert len(idx2.chunks) >= 1
        assert idx2.bm25.n_docs >= 1
    finally:
        (BASE_DIR / "tests" / "python" / "_tmp_chunk_saveload.md").unlink(missing_ok=True)