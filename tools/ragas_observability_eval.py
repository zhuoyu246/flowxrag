from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CASE_FILE = ROOT_DIR / "data" / "eval" / "ragas_eval_cases.example.json"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "evaluations"

DEFAULT_CASES = [
    {
        "id": "paper_overview",
        "question": "这篇论文主要讲了什么？",
        "reference": (
            "论文提出 PhysGated-LSTM 用于超短期光伏功率预测。它用 CPO 识别双二极管模型参数，"
            "并将物理参数映射到 LSTM 门控单元，让神经网络记忆流受到物理机制调制，从而提升强辐照波动场景下的泛化能力。"
        ),
    },
    {
        "id": "core_innovation",
        "question": "这篇论文的核心创新是什么？",
        "reference": (
            "核心创新是 Physics-Embedded Gated LSTM/PhysGated 架构：不是简单拼接物理特征，"
            "而是把双二极管模型参数嵌入 LSTM gates，并结合一致性损失和物理残差调制来抑制预测误差。"
        ),
    },
    {
        "id": "experiment_result",
        "question": "这篇论文的实验结果怎么样？",
        "reference": (
            "实验显示模型在 30 分钟预测中达到 R2=0.936，相比基线 RMSE 降低 18.18%，MAE 降低 23.81%。"
            "在快速辐照突变等极端条件下，模型保持 R2=0.992，高于基线 0.876，减少相位滞后和非物理过冲。"
        ),
    },
]

DEFAULT_THRESHOLDS = {
    "faithfulness": 0.75,
    "answer_relevancy": 0.65,
    "context_precision": 0.60,
    "context_recall": 0.60,
    "retrieval_hit_rate": 1.00,
    "local_route_rate": 1.00,
    "p95_latency_sec": 60.0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run local RAGAS evaluation and enterprise-style RAG observability report.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASE_FILE,
        help="JSON file with eval cases. Use a list or {'cases': [...]} schema.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Limit case count. 0 means all cases.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Local report directory.")
    parser.add_argument("--no-ragas", action="store_true", help="Only collect RAG telemetry, skip RAGAS scoring.")
    parser.add_argument("--trace-langsmith", action="store_true", help="Keep LangSmith tracing enabled for this eval run.")
    parser.add_argument("--ragas-timeout", type=int, default=180, help="RAGAS judge timeout in seconds.")
    parser.add_argument("--ragas-retries", type=int, default=3, help="RAGAS judge retry count.")
    parser.add_argument("--ragas-workers", type=int, default=4, help="RAGAS parallel worker count.")
    parser.add_argument("--answer-relevancy-strictness", type=int, default=1, help="Generated questions per answer.")
    parser.add_argument("--judge-max-tokens", type=int, default=2048, help="Max tokens for the RAGAS judge LLM.")
    parser.add_argument("--quiet", action="store_true", help="Hide RAGAS progress bar.")
    return parser.parse_args()


def configure_environment(trace_langsmith: bool) -> None:
    load_dotenv(ROOT_DIR / ".env", override=True)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ["RAGAS_DO_NOT_TRACK"] = "true"
    warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"ragas\..*")
    warnings.filterwarnings("ignore", category=DeprecationWarning, message=r".*Langchain.*Wrapper.*")
    warnings.filterwarnings("ignore", category=PendingDeprecationWarning, module=r"langgraph\..*")

    if not trace_langsmith:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        os.environ["LANGSMITH_TRACING"] = "false"

    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))


def load_cases(path: Path, limit: int) -> list[dict[str, Any]]:
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        cases = payload["cases"] if isinstance(payload, dict) else payload
    else:
        cases = DEFAULT_CASES

    normalized = []
    for index, case in enumerate(cases, start=1):
        question = str(case.get("question", "")).strip()
        reference = str(case.get("reference", "")).strip()
        if not question or not reference:
            raise ValueError(f"Eval case #{index} must include non-empty question and reference.")
        normalized.append(
            {
                "id": str(case.get("id") or f"case_{index:03d}"),
                "question": question,
                "reference": reference,
                "metadata": case.get("metadata", {}),
            }
        )

    return normalized[:limit] if limit and limit > 0 else normalized


def percentile(values: list[float], pct: float) -> float | None:
    clean = sorted(value for value in values if math.isfinite(value))
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    rank = (len(clean) - 1) * pct / 100
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return clean[int(rank)]
    return clean[lower] + (clean[upper] - clean[lower]) * (rank - lower)


def numeric_mean(values: list[Any]) -> float | None:
    clean = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            clean.append(number)
    return statistics.mean(clean) if clean else None


def as_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): as_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [as_jsonable(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item") and callable(value.item):
        try:
            return as_jsonable(value.item())
        except Exception:
            return str(value)
    return value


def source_scores(sources: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    scores = []
    for source in sources:
        for key in ("retrieval_score", "score"):
            try:
                score = float(source.get(key))
            except (TypeError, ValueError):
                continue
            if math.isfinite(score):
                scores.append(score)
                break
    if not scores:
        return None, None
    return max(scores), statistics.mean(scores)


def run_application_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from backend.graph import crag_app, initial_state

    records = []
    for case in cases:
        started = time.perf_counter()
        state = crag_app.invoke(initial_state(case["question"]))
        latency_sec = round(time.perf_counter() - started, 3)

        documents = state.get("documents") or []
        contexts = [str(doc.get("content", "")).strip() for doc in documents if doc.get("content")]
        sources = state.get("sources") or [doc.get("source_meta", {}) for doc in documents]
        sources = [source for source in sources if isinstance(source, dict)]
        top_score, avg_score = source_scores(sources)

        records.append(
            {
                "id": case["id"],
                "question": case["question"],
                "reference": case["reference"],
                "answer": state.get("generation", ""),
                "route": state.get("route", ""),
                "web_fallback": bool(state.get("web_fallback", False)),
                "latency_sec": latency_sec,
                "retrieved_count": len(contexts),
                "context_chars": sum(len(context) for context in contexts),
                "top_retrieval_score": top_score,
                "avg_retrieval_score": avg_score,
                "sources": sources,
                "contexts": contexts,
                "steps": state.get("steps", []),
                "reasoning_summary": state.get("reasoning_summary", []),
                "metadata": case.get("metadata", {}),
            }
        )
    return records


def run_ragas(records: list[dict[str, Any]], args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, float | None]]:
    from langchain_core.embeddings import Embeddings
    from langchain_openai import ChatOpenAI
    from ragas import EvaluationDataset, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics._answer_relevance import answer_relevancy
    from ragas.metrics._context_precision import context_precision
    from ragas.metrics._context_recall import context_recall
    from ragas.metrics._faithfulness import faithfulness
    from ragas.run_config import RunConfig

    from backend.retriever import knowledge_base

    class KnowledgeBaseEmbeddings(Embeddings):
        model: str

        def __init__(self) -> None:
            self.model = knowledge_base.embedding.provider

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            if not texts:
                return []
            return knowledge_base.embedding.embed(texts).astype(float).tolist()

        def embed_query(self, text: str) -> list[float]:
            return self.embed_documents([text])[0]

    dataset = EvaluationDataset.from_list(
        [
            {
                "user_input": record["question"],
                "response": record["answer"],
                "retrieved_contexts": record["contexts"],
                "reference": record["reference"],
            }
            for record in records
        ]
    )

    run_config = RunConfig(
        timeout=args.ragas_timeout,
        max_retries=args.ragas_retries,
        max_workers=args.ragas_workers,
    )
    judge_llm = LangchainLLMWrapper(
        ChatOpenAI(
            model=os.getenv("RAGAS_JUDGE_MODEL", os.getenv("OPENAI_MODEL", os.getenv("MODEL_NAME", "deepseek-chat"))),
            temperature=0,
            base_url=os.getenv("OPENAI_API_BASE", "https://api.deepseek.com"),
            api_key=os.getenv("OPENAI_API_KEY"),
            max_tokens=args.judge_max_tokens,
            timeout=args.ragas_timeout,
            max_retries=1,
        ),
        run_config=run_config,
        bypass_n=True,
    )
    embeddings = LangchainEmbeddingsWrapper(KnowledgeBaseEmbeddings(), run_config=run_config)

    answer_relevancy.strictness = max(1, args.answer_relevancy_strictness)
    metrics = [faithfulness, answer_relevancy, context_precision, context_recall]

    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=judge_llm,
        embeddings=embeddings,
        run_config=run_config,
        raise_exceptions=False,
        show_progress=not args.quiet,
        experiment_name="local-ragas-observability",
    )

    score_rows = [as_jsonable(row) for row in result.scores]
    aggregate = {key: as_jsonable(value) for key, value in result._repr_dict.items()}
    return score_rows, aggregate


def build_summary(records: list[dict[str, Any]], ragas_aggregate: dict[str, Any]) -> dict[str, Any]:
    total = len(records)
    latencies = [float(record["latency_sec"]) for record in records]
    retrieval_hits = sum(1 for record in records if record["retrieved_count"] > 0)
    local_routes = sum(1 for record in records if record["route"] == "local")
    web_fallbacks = sum(1 for record in records if record["web_fallback"])

    summary = {
        "case_count": total,
        "quality": ragas_aggregate,
        "routing": {
            "local_route_rate": local_routes / total if total else None,
            "web_fallback_rate": web_fallbacks / total if total else None,
        },
        "retrieval": {
            "retrieval_hit_rate": retrieval_hits / total if total else None,
            "avg_retrieved_count": numeric_mean([record["retrieved_count"] for record in records]),
            "avg_context_chars": numeric_mean([record["context_chars"] for record in records]),
            "avg_top_retrieval_score": numeric_mean([record["top_retrieval_score"] for record in records]),
        },
        "latency": {
            "avg_latency_sec": numeric_mean(latencies),
            "p50_latency_sec": percentile(latencies, 50),
            "p95_latency_sec": percentile(latencies, 95),
            "max_latency_sec": max(latencies) if latencies else None,
        },
    }

    gates = []
    for metric, threshold in DEFAULT_THRESHOLDS.items():
        if metric in summary["quality"]:
            value = summary["quality"].get(metric)
            ok = value is not None and float(value) >= threshold
        elif metric == "p95_latency_sec":
            value = summary["latency"].get(metric)
            ok = value is not None and float(value) <= threshold
        elif metric in summary["routing"]:
            value = summary["routing"].get(metric)
            ok = value is not None and float(value) >= threshold
        else:
            value = summary["retrieval"].get(metric)
            ok = value is not None and float(value) >= threshold
        gates.append({"metric": metric, "value": value, "threshold": threshold, "passed": bool(ok)})
    summary["gates"] = gates
    summary["passed"] = all(gate["passed"] for gate in gates if gate["value"] is not None)
    return summary


def fmt(value: Any, digits: int = 3) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if not math.isfinite(number):
        return "-"
    return f"{number:.{digits}f}"


def write_reports(
    output_dir: Path,
    records: list[dict[str, Any]],
    summary: dict[str, Any],
    config: dict[str, Any],
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"ragas_observability_{stamp}.json"
    md_path = output_dir / f"ragas_observability_{stamp}.md"

    payload = {"config": config, "summary": summary, "records": records}
    json_path.write_text(json.dumps(as_jsonable(payload), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    lines = [
        "# RAGAS Local Observability Report",
        "",
        f"- Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Cases: {summary['case_count']}",
        f"- Judge model: {config.get('judge_model')}",
        f"- Retrieval mode: {config.get('retrieval_mode')}",
        f"- LangSmith tracing for eval: {config.get('trace_langsmith')}",
        "",
        "## Quality Gates",
        "",
        "| Gate | Value | Threshold | Status |",
        "| --- | ---: | ---: | --- |",
    ]
    for gate in summary["gates"]:
        comparator = "<=" if gate["metric"] == "p95_latency_sec" else ">="
        lines.append(
            f"| {gate['metric']} | {fmt(gate['value'])} | {comparator} {fmt(gate['threshold'])} | "
            f"{'PASS' if gate['passed'] else 'WARN'} |"
        )

    lines.extend(
        [
            "",
            "## Aggregate Metrics",
            "",
            "| Area | Metric | Value |",
            "| --- | --- | ---: |",
        ]
    )
    for key, value in summary["quality"].items():
        lines.append(f"| RAGAS | {key} | {fmt(value)} |")
    for area in ("routing", "retrieval", "latency"):
        for key, value in summary[area].items():
            lines.append(f"| {area} | {key} | {fmt(value)} |")

    lines.extend(
        [
            "",
            "## Case Results",
            "",
            "| Case | Route | Latency(s) | Contexts | Faithfulness | Answer Rel. | Ctx Precision | Ctx Recall |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for record in records:
        scores = record.get("ragas_scores", {})
        lines.append(
            f"| {record['id']} | {record['route']} | {fmt(record['latency_sec'])} | "
            f"{record['retrieved_count']} | {fmt(scores.get('faithfulness'))} | "
            f"{fmt(scores.get('answer_relevancy'))} | {fmt(scores.get('context_precision'))} | "
            f"{fmt(scores.get('context_recall'))} |"
        )

    lines.extend(
        [
            "",
            "## Enterprise Observability Notes",
            "",
            "- RAGAS 指标用于回答质量：faithfulness 看答案是否被上下文支撑，answer_relevancy 看回答是否贴合问题，context_precision/context_recall 看检索上下文是否精确且覆盖参考答案。",
            "- 工程指标用于线上观测：route、retrieved_count、top_retrieval_score、context_chars、latency_sec 可以进入日志、Prometheus 或 LangSmith metadata。",
            "- 本脚本默认只写本地文件，并关闭 RAGAS analytics 与 LangSmith tracing；需要链路追踪时显式加 --trace-langsmith。",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")

    latest_json = output_dir / "ragas_observability_latest.json"
    latest_md = output_dir / "ragas_observability_latest.md"
    latest_json.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
    latest_md.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    args = parse_args()
    configure_environment(args.trace_langsmith)

    from backend.retriever import knowledge_base

    cases = load_cases(args.cases, args.limit)
    records = run_application_cases(cases)

    ragas_aggregate: dict[str, Any] = {}
    if not args.no_ragas:
        score_rows, ragas_aggregate = run_ragas(records, args)
        for record, scores in zip(records, score_rows):
            record["ragas_scores"] = scores
    else:
        for record in records:
            record["ragas_scores"] = {}

    kb_stats = knowledge_base.stats()
    summary = build_summary(records, ragas_aggregate)
    config = {
        "cases_file": str(args.cases),
        "no_ragas": args.no_ragas,
        "trace_langsmith": args.trace_langsmith,
        "judge_model": os.getenv("RAGAS_JUDGE_MODEL", os.getenv("OPENAI_MODEL", os.getenv("MODEL_NAME", "deepseek-chat"))),
        "retrieval_mode": kb_stats.get("retrieval_mode"),
        "chunking_strategy": kb_stats.get("chunking_strategy"),
        "embedding_provider": kb_stats.get("embedding_provider"),
        "embedding_dimension": kb_stats.get("embedding_dimension"),
        "source_count": kb_stats.get("source_count"),
        "chunk_count": kb_stats.get("chunks"),
    }

    json_path, md_path = write_reports(args.output_dir, records, summary, config)

    print(json.dumps(as_jsonable({"summary": summary, "json": str(json_path), "markdown": str(md_path)}), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
