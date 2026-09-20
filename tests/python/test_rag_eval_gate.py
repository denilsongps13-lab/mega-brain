"""Deterministic characterization tests for the RAG correctness gate."""
import json

from engine.intelligence.rag import eval_gate


def _qrels():
    return eval_gate.parse_qrels_file(
        json.dumps(
            {
                "schema_version": 1,
                "queries": [
                    {
                        "query_id": "q1",
                        "query": "alpha",
                        "relevant": [{"bucket": "external", "chunk_id": "c1"}],
                        "expected_top1": {"bucket": "external", "chunk_id": "c1"},
                    },
                    {
                        "query_id": "q2",
                        "query": "beta",
                        "relevant": [{"bucket": "external", "chunk_id": "c2"}],
                        "expected_top1": {"bucket": "external", "chunk_id": "c2"},
                    },
                ],
            }
        )
    )


def test_eval_gate_metrics_pass_with_relevant_top1():
    qrels = _qrels()

    def search(query, bucket, k):
        chunk = "c1" if query == "alpha" else "c2"
        return [(bucket, chunk), (bucket, "noise")][:k]

    summary, rows = eval_gate.run_correctness_gate(qrels, k=2, search_fn=search)

    assert summary.queries_total == 2
    assert summary.queries_errored == 0
    assert summary.mean_recall_at_k == 1.0
    assert summary.first_relevant_hit_rate == 1.0
    assert summary.expected_top1_hit_rate == 1.0
    assert all(not row.errored for row in rows)


def test_eval_gate_is_fail_closed_on_retrieval_error():
    qrels = _qrels()

    def broken_search(query, bucket, k):
        raise RuntimeError("synthetic retrieval failure")

    summary, rows = eval_gate.run_correctness_gate(qrels, k=2, search_fn=broken_search)
    breaches = eval_gate._correctness_breaches(
        summary,
        rows,
        {"recall_at_k": 0.70, "first_relevant_hit": 0.60, "expected_top1": 0.50},
    )

    assert summary.queries_errored == 2
    assert any(b.metric == "queries_errored" for b in breaches)
