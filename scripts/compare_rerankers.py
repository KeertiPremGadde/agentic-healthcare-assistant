# ruff: noqa: E501
"""Free comparison of cross-encoder rerankers against ScoreReranker (Phase 7, change 2).

    uv run python scripts/compare_rerankers.py [--models a b ...] [--top-n 20]

One subprocess per model (own cache folder, so download size and peak memory are that model's
alone). The child only loads fastembed/onnxruntime: it scores (query, passage) pairs and reports
timings and memory; the parent ranks the scores and computes the same retrieval metrics as the
eval suite. No LLM, no cost. The result is written to evals/results/reranker/comparison.json.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = (
    "Xenova/ms-marco-MiniLM-L-6-v2",
    "Xenova/ms-marco-MiniLM-L-12-v2",
    "jinaai/jina-reranker-v1-tiny-en",
    "BAAI/bge-reranker-v2-m3-int8",  # smallest multilingual one fastembed offers
)
WARMUP = 3


def _peak_rss_mb() -> float:
    """Peak working set of this process in MB (Windows via psapi, elsewhere via resource)."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        from typing import Any, ClassVar

        class Counters(ctypes.Structure):
            _fields_: ClassVar[list[tuple[str, Any]]] = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        c = Counters()
        c.cb = ctypes.sizeof(c)
        kernel32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")  # type: ignore[attr-defined]
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE  # a 64-bit handle: declare it
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(Counters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            raise OSError("GetProcessMemoryInfo failed")
        return c.PeakWorkingSetSize / 2**20
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _dir_mb(path: Path) -> float:
    """On-disk size of a Hugging Face cache folder. Windows copies each file into snapshots/ as
    well as blobs/, so only blobs/ is counted (the download size)."""
    return sum(f.stat().st_size for f in path.rglob("blobs/*") if f.is_file()) / 2**20


def child(
    model: str,
    pool_file: Path,
    cache: Path,
    top_n: int,
    threads: int | None,
    latency_only: bool,
    limit: int | None,
) -> None:
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    queries = json.loads(pool_file.read_text(encoding="utf-8"))
    if limit:
        queries = queries[:limit]
    rss_start = _peak_rss_mb()
    t0 = time.perf_counter()
    encoder = TextCrossEncoder(model_name=model, cache_dir=str(cache), threads=threads)
    load_s = time.perf_counter() - t0
    rss_loaded = _peak_rss_mb()

    def passages(item: dict, with_header: bool) -> list[str]:
        out = []
        for c in item["pool"][:top_n]:
            out.append(
                f"{c['header']}\n\n{c['content']}" if with_header and c["header"] else c["content"]
            )
        return out

    result: dict = {
        "model": model,
        "download_mb": round(_dir_mb(cache), 1),
        "load_s": round(load_s, 2),
        "rss_start_mb": round(rss_start),
        "rss_loaded_mb": round(rss_loaded),
        "threads": threads,
        "queries_timed": len(queries),
        "variants": {},
    }
    for name, with_header in (("content", False), ("header+content", True)):
        if latency_only and with_header:
            continue
        for item in queries[:WARMUP]:
            list(encoder.rerank(item["question"], passages(item, with_header)))
        scores, times = [], []
        for item in queries:
            docs = passages(item, with_header)
            t = time.perf_counter()
            s = [float(x) for x in encoder.rerank(item["question"], docs)]
            times.append((time.perf_counter() - t) * 1000)
            scores.append(s)
        times.sort()
        result["variants"][name] = {
            "scores": scores,
            "p50_ms": round(times[len(times) // 2], 1),
            "p95_ms": round(times[int(len(times) * 0.95) - 1], 1),
        }
    result["rss_peak_mb"] = round(_peak_rss_mb())
    print("RESULT" + json.dumps(result))


def collect(pool_file: Path, top_n: int) -> list[dict]:
    """Candidate pools from the real hybrid retriever, plus today's ScoreReranker ranking."""
    from medagent.core.config import get_settings
    from medagent.db.session import get_sessionmaker
    from medagent.evals import datasets
    from medagent.rag.embeddings import get_embedder
    from medagent.rag.retriever import HybridRetriever, ScoreReranker
    from medagent.rag.types import Candidate

    class Capture:
        """Keeps the fused pool (best RRF first), then ranks it the way production does."""

        def __init__(self) -> None:
            self.pool: list[Candidate] = []
            self.inner = ScoreReranker()
            self.seconds: list[float] = []

        def rerank(self, query: str, candidates: list[Candidate]) -> list[Candidate]:
            self.pool = sorted(candidates, key=lambda c: c.fused_score, reverse=True)
            t = time.perf_counter()
            ranked = self.inner.rerank(query, list(candidates))
            self.seconds.append((time.perf_counter() - t) * 1000)
            return ranked

    settings = get_settings()
    capture = Capture()
    retriever = HybridRetriever(get_embedder(settings), reranker=capture)
    items = []
    with get_sessionmaker()() as session:
        for q in datasets.load_rag().items:
            if q.kind not in ("in_scope", "in_scope_de"):
                continue
            base = retriever.search(session, q.question, k=5, public_only=settings.kb_public_only)
            items.append(
                {
                    "id": q.id,
                    "kind": q.kind,
                    "question": q.question,
                    "expected": q.expected_topics,
                    "pool_size": len(capture.pool),
                    "baseline_titles": [c.document_title for c in base],
                    "baseline_max_sim": max(c.vector_sim for c in base),
                    "pool": [
                        {
                            "title": c.document_title,
                            "content": c.content,
                            "header": c.context_header,
                            "sim": c.vector_sim,
                        }
                        for c in capture.pool
                    ],
                }
            )
    pool_file.write_text(json.dumps(items), encoding="utf-8")
    sizes = sorted(i["pool_size"] for i in items)
    print(
        f"pools: {len(items)} questions, pool size min {sizes[0]} median {sizes[len(sizes) // 2]} max {sizes[-1]}"
    )
    print(
        f"ScoreReranker: median {sorted(capture.seconds)[len(capture.seconds) // 2]:.3f} ms per query"
    )
    return items


def quality(items: list[dict], scores: list[list[float]] | None, top_n: int) -> dict:
    from medagent.evals import metrics

    records = []
    for i, item in enumerate(items):
        if scores is None:
            titles = item["baseline_titles"]
            max_sim = item["baseline_max_sim"]
        else:
            pool = item["pool"][:top_n]
            order = sorted(range(len(pool)), key=lambda j: scores[i][j], reverse=True)[:5]
            titles = [pool[j]["title"] for j in order]
            max_sim = max(pool[j]["sim"] for j in order)
        records.append(
            metrics.RetrievalRecord(
                id=item["id"],
                kind=item["kind"],
                rank=metrics.rank_of(titles, item["expected"]),
                max_sim=round(max_sim, 4),
                top_titles=tuple(titles[:3]),
            )
        )
    m = metrics.retrieval_metrics(records, 0.70)
    keys = ("en_hit_at_1", "en_hit_at_5", "en_mrr", "de_hit_at_1", "de_hit_at_5", "de_mrr")
    return {k: m[k] for k in keys} | {"ranks": {r.id: r.rank for r in records}}


def run_child(args: argparse.Namespace, model: str, pool_file: Path, work: Path) -> dict | None:
    cache = work / "models" / model.replace("/", "__")
    cache.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        __file__,
        "--child",
        model,
        "--pool",
        str(pool_file),
        "--cache",
        str(cache),
        "--top-n",
        str(args.top_n),
    ]
    if args.threads:
        cmd += ["--threads", str(args.threads)]
    if args.latency_only:
        cmd += ["--latency-only"]
    if args.limit:
        cmd += ["--limit", str(args.limit)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT")), None)
    if line is None:
        print(f"{model}: FAILED\n{proc.stderr[-800:]}")
        return None
    return json.loads(line[len("RESULT") :])


def latency_only(args: argparse.Namespace, pool_file: Path, work: Path) -> None:
    """Size, RAM and latency only (quality does not depend on timing). Run on an idle machine."""
    rows = []
    for model in args.models:
        r = run_child(args, model, pool_file, work)
        if r is None:
            continue
        v = r["variants"]["content"]
        r.update(p50_ms=v["p50_ms"], p95_ms=v["p95_ms"])
        del r["variants"]
        rows.append(r)
        print(
            f"{model}: {r['download_mb']} MB, RSS loaded {r['rss_loaded_mb']} / peak {r['rss_peak_mb']} MB, "
            f"load {r['load_s']} s, p50 {r['p50_ms']} ms, p95 {r['p95_ms']} ms "
            f"({r['queries_timed']} queries, threads={args.threads})"
        )
    dest = ROOT / "evals" / "results" / "reranker"
    dest.mkdir(parents=True, exist_ok=True)
    with (dest / "latency.jsonl").open("a", encoding="utf-8") as f:  # one line per invocation
        record = {
            "cpu_count": os.cpu_count(),
            "top_n": args.top_n,
            "threads": args.threads,
            "limit": args.limit,
            "rows": rows,
        }
        f.write(json.dumps(record) + os.linesep)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--models", nargs="*", default=list(MODELS))
    p.add_argument("--top-n", type=int, default=20)
    p.add_argument("--threads", type=int, default=None, help="ONNX threads (2 ~ a small container)")
    p.add_argument("--latency-only", action="store_true", help="size/RAM/latency from cached pools")
    p.add_argument("--limit", type=int, default=None, help="time only the first N questions")
    p.add_argument("--child", default=None)
    p.add_argument("--pool", default=None)
    p.add_argument("--cache", default=None)
    p.add_argument("--work", default=str(ROOT / "evals" / "results" / "runs" / "reranker-work"))
    args = p.parse_args()

    if args.child:
        child(
            args.child,
            Path(args.pool),
            Path(args.cache),
            args.top_n,
            args.threads,
            args.latency_only,
            args.limit,
        )
        return

    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    pool_file = work / "pools.json"
    if args.latency_only:
        latency_only(args, pool_file, work)
        return
    items = collect(pool_file, args.top_n)

    in_pool = [
        any(c["title"] in item["expected"] for c in item["pool"][: args.top_n]) for item in items
    ]
    en = [i for i, it in enumerate(items) if it["kind"] == "in_scope"]
    de = [i for i, it in enumerate(items) if it["kind"] == "in_scope_de"]
    upper = {
        "en_expected_topic_in_pool": round(sum(in_pool[i] for i in en) / len(en), 3),
        "de_expected_topic_in_pool": round(sum(in_pool[i] for i in de) / len(de), 3),
    }
    out: dict = {
        "top_n": args.top_n,
        "pool_recall": upper,
        "baseline_score_reranker": quality(items, None, args.top_n),
        "models": [],
    }

    for model in args.models:
        r = run_child(args, model, pool_file, work)
        if r is None:
            continue
        for v in r["variants"].values():
            v["quality"] = quality(items, v.pop("scores"), args.top_n)
        # timing/size/RAM of this pass are not trusted (collect() and DB work share the machine):
        # they come from --latency-only runs on an idle machine
        for k in ("download_mb", "load_s", "rss_start_mb", "rss_loaded_mb", "rss_peak_mb"):
            r.pop(k, None)
        for v in r["variants"].values():
            v.pop("p50_ms", None)
            v.pop("p95_ms", None)
        out["models"].append(r)
        print(f"{model}: EN {r['variants']['content']['quality']['en_mrr']} MRR")

    dest = ROOT / "evals" / "results" / "reranker"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "comparison.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "models"}, indent=1)[:900])


if __name__ == "__main__":
    main()
