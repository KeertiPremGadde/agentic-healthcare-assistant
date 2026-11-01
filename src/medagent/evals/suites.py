"""Suites that run the real system: retrieval (free), routing and RAG answers (LLM).

Each returns an `EvalResult`; scoring lives in `metrics.py`. LLM suites take a `Spend` so a run
stops at its USD cap, and write what they have if they are stopped.
"""

import asyncio
from collections import defaultdict
from collections.abc import Coroutine
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.messages import HumanMessage

from medagent.agents.llm import AnthropicStructuredLLM
from medagent.agents.prompts.router import ROUTER_SYSTEM_PROMPT
from medagent.agents.schemas import RouteDecision
from medagent.core.config import Settings, get_settings
from medagent.db.session import get_sessionmaker
from medagent.evals import datasets, metrics
from medagent.evals.results import EvalResult, Spend, git_sha, new_run_id
from medagent.guardrails.dose import contains_dose
from medagent.observability.cost import estimate_cost
from medagent.rag.answer import AnthropicAnswerLLM, Retriever, answer_question
from medagent.rag.embeddings import get_embedder
from medagent.rag.retriever import HybridRetriever, get_reranker
from medagent.rag.types import Candidate

CONCURRENCY = 4
SWEEP = (0.5, 0.55, 0.6, 0.65, 0.7, 0.72, 0.74, 0.76, 0.78, 0.8)


def _reranker_params(settings: Settings) -> dict[str, Any]:
    """Which reranker produced a result file (the default changed from `score` in Phase 7)."""
    if settings.reranker == "score":
        return {"reranker": "score"}
    return {
        "reranker": settings.reranker,
        "reranker_model": settings.reranker_model,
        "reranker_top_n": settings.reranker_top_n,
    }


def _base(
    suite: str, model: str | None, names: tuple[str, ...], params: dict[str, Any]
) -> EvalResult:
    hashes = datasets.current_hashes()
    return EvalResult(
        suite=suite,
        run_id=new_run_id(suite),
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
        git_sha=git_sha(),
        model=model,
        datasets={n: hashes[n] for n in names},
        params=params,
        metrics={},
    )


# -- retrieval (free: local embeddings + Postgres, no LLM) ----------------------------------


def run_retrieval(k: int = 5) -> EvalResult:
    settings = get_settings()
    questions = datasets.load_rag().items
    retriever = HybridRetriever(get_embedder(settings), get_reranker(settings))
    records: list[metrics.RetrievalRecord] = []
    with get_sessionmaker()() as session:
        for q in questions:
            found = retriever.search(session, q.question, k=k, public_only=settings.kb_public_only)
            titles = tuple(c.document_title for c in found)
            records.append(
                metrics.RetrievalRecord(
                    id=q.id,
                    kind=q.kind,
                    rank=metrics.rank_of(titles, q.expected_topics) if q.expected_topics else None,
                    max_sim=round(max((c.vector_sim for c in found), default=0.0), 4),
                    top_titles=titles[:3],
                )
            )
    result = _base(
        "retrieval",
        None,
        ("rag_golden",),
        {"k": k, "min_score": settings.rag_min_score, **_reranker_params(settings)},
    )
    result.metrics = dict(metrics.retrieval_metrics(records, settings.rag_min_score))
    result.metrics["threshold_sweep"] = metrics.threshold_sweep(records, SWEEP)
    result.items = [asdict(r) for r in records]
    return result


# -- routing (LLM: the router alone, one message per call, no conversation state) -----------


async def _gather_limited[T](jobs: list[Coroutine[Any, Any, T]]) -> list[T]:
    sem = asyncio.Semaphore(CONCURRENCY)

    async def run(job: Coroutine[Any, Any, T]) -> T:
        async with sem:
            return await job

    return await asyncio.gather(*(run(j) for j in jobs))


async def run_routing(spend: Spend, repeats: int = 3, limit: int | None = None) -> EvalResult:
    settings = get_settings()
    messages = datasets.load_routing().items[:limit]
    llm = AnthropicStructuredLLM(settings)
    records: list[metrics.RoutingRecord] = []
    failed: list[str] = []

    async def one(m: datasets.RoutingMessage, repeat: int) -> None:
        if spend.exhausted:
            return
        with get_usage_metadata_callback() as usage:
            try:
                d = await llm.ainvoke(
                    RouteDecision,
                    ROUTER_SYSTEM_PROMPT.format(context="None."),
                    [HumanMessage(m.text)],
                )
            except Exception as exc:  # a failed call is a data point, not a crash
                failed.append(f"{m.id}#{repeat}:{type(exc).__name__}")
                return
            finally:
                spend.add(estimate_cost(usage.usage_metadata))
        records.append(
            metrics.RoutingRecord(m.id, repeat, d.route.value, d.is_emergency, d.is_harmful)
        )

    result = _base("routing", settings.llm_model, ("routing_golden",), {"repeats": repeats})
    await _gather_limited([one(m, r) for m in messages for r in range(repeats)])
    result.aborted = spend.abort_reason()
    result.metrics = dict(metrics.routing_metrics(messages, records))
    result.metrics["confusion"] = metrics.confusion(messages, records)
    result.metrics["failed_calls"] = len(failed)
    result.items = [asdict(r) for r in sorted(records, key=lambda r: (r.id, r.repeat))]
    result.cost = spend.as_dict()
    return result


# -- RAG answers (LLM): the real pipeline, deterministic checks on the result ---------------


class _RecordingRetriever:
    """Remembers what was retrieved for one question (needed later by the LLM-judged metrics)."""

    def __init__(self, inner: Retriever) -> None:
        self.inner = inner
        self.last: list[Candidate] = []

    def search(
        self, session: Any, query: str, k: int = 5, public_only: bool = False
    ) -> list[Candidate]:
        self.last = self.inner.search(session, query, k=k, public_only=public_only)
        return self.last


async def run_rag(
    spend: Spend, limit: int | None = None, per_kind: int | None = None
) -> EvalResult:
    settings = get_settings()
    questions = datasets.load_rag().items
    if per_kind is not None:  # a small, balanced sample for pilots
        seen: dict[str, int] = defaultdict(int)
        picked = []
        for q in questions:
            if seen[q.kind] < per_kind:
                picked.append(q)
                seen[q.kind] += 1
        questions = picked
    questions = questions[:limit]
    inner = HybridRetriever(get_embedder(settings), get_reranker(settings))
    answer_llm = AnthropicAnswerLLM(settings)
    router = AnthropicStructuredLLM(settings)
    records: list[metrics.RagRecord] = []
    items: list[dict[str, Any]] = []

    def answer_sync(q: datasets.RagQuestion) -> tuple[Any, list[Candidate], Any]:
        rec = _RecordingRetriever(inner)
        with get_usage_metadata_callback() as usage, get_sessionmaker()() as session:
            try:
                ans = answer_question(session, rec, answer_llm, q.question)
            finally:
                cost = estimate_cost(usage.usage_metadata)
        return ans, rec.last, cost

    async def one(q: datasets.RagQuestion) -> None:
        if spend.exhausted:
            return
        if q.kind == "off_topic":  # not a retrieval question: scored on the route it gets
            with get_usage_metadata_callback() as usage:
                try:
                    d = await router.ainvoke(
                        RouteDecision,
                        ROUTER_SYSTEM_PROMPT.format(context="None."),
                        [HumanMessage(q.question)],
                    )
                finally:
                    spend.add(estimate_cost(usage.usage_metadata))
            records.append(metrics.RagRecord(q.id, q.kind, False, (), False, route=d.route.value))
            items.append({"id": q.id, "kind": q.kind, "route": d.route.value})
            return
        ans, contexts, cost = await asyncio.to_thread(answer_sync, q)
        spend.add(cost)
        cited = tuple(s.label.split(": ", 1)[-1] for s in ans.sources)
        records.append(
            metrics.RagRecord(q.id, q.kind, ans.grounded, cited, contains_dose(ans.answer))
        )
        items.append(
            {
                "id": q.id,
                "kind": q.kind,
                "question": q.question,
                "answer": ans.answer,
                "grounded": ans.grounded,
                "cited": list(cited),
                "contexts": [c.content for c in contexts],
                "context_titles": [c.document_title for c in contexts],
            }
        )

    result = _base(
        "rag",
        settings.llm_model,
        ("rag_golden",),
        {"k": 5, "min_score": settings.rag_min_score, **_reranker_params(settings)},
    )
    await _gather_limited([one(q) for q in questions])
    result.aborted = spend.abort_reason()
    done = {r.id for r in records}
    result.metrics = metrics.rag_metrics([q for q in questions if q.id in done], records)
    result.items = sorted(items, key=lambda i: i["id"])
    result.cost = spend.as_dict()
    return result
