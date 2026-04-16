# """Benchmark metadata and replay analytics for continuous evaluation."""

# from __future__ import annotations

# import json
# from collections import defaultdict
# from datetime import datetime
# from pathlib import Path
# from typing import Any

# from app.services.replay_eval import evaluate_replay_artifact
# from app.services.replay_store import get_replay_artifact, list_replay_artifacts


# def _benchmark_dir() -> Path:
#     return Path(__file__).resolve().parents[1] / "evals" / "benchmarks"


# def list_benchmark_sets() -> list[dict[str, Any]]:
#     """Load benchmark-set metadata from checked-in JSON files."""
#     items: list[dict[str, Any]] = []
#     for path in sorted(_benchmark_dir().glob("*.json")):
#         try:
#             data = json.loads(path.read_text(encoding="utf-8"))
#         except Exception:
#             continue
#         items.append(
#             {
#                 "id": data.get("id", path.stem),
#                 "title": data.get("title", path.stem.replace("_", " ").title()),
#                 "description": data.get("description", ""),
#                 "specialist": data.get("specialist", data.get("workflow", "")),
#                 "scenario_count": int(data.get("scenario_count", 0) or 0),
#                 "examples": list(data.get("examples", []) or [])[:3],
#             }
#         )
#     return items


# def _parse_time(value: str | None) -> datetime | None:
#     text = str(value or "").strip()
#     if not text:
#         return None
#     text = text.replace("Z", "+00:00")
#     try:
#         return datetime.fromisoformat(text)
#     except ValueError:
#         return None


# def _group_summary(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
#     grouped: dict[str, list[float]] = defaultdict(list)
#     status_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "warn": 0, "fail": 0})
#     for item in values:
#         key = str(item.get("key", "") or "unknown")
#         grouped[key].append(float(item.get("score", 0.0) or 0.0))
#         status = str(item.get("status", "warn") or "warn")
#         if status not in status_counts[key]:
#             status_counts[key][status] = 0
#         status_counts[key][status] += 1
#     rows: list[dict[str, Any]] = []
#     for key, scores in grouped.items():
#         rows.append(
#             {
#                 "key": key,
#                 "count": len(scores),
#                 "average_score": round(sum(scores) / max(1, len(scores)), 4),
#                 "passed": int(status_counts[key].get("pass", 0)),
#                 "warned": int(status_counts[key].get("warn", 0)),
#                 "failed": int(status_counts[key].get("fail", 0)),
#             }
#         )
#     rows.sort(key=lambda item: (item["average_score"], item["count"]), reverse=True)
#     return rows


# def _trend_summary(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
#     ordered = sorted(
#         [item for item in evaluations if item.get("created_at")],
#         key=lambda item: str(item.get("created_at", "")),
#     )
#     points = [
#         {
#             "id": item.get("replay_id", ""),
#             "created_at": item.get("created_at", ""),
#             "score": float(item.get("score", 0.0) or 0.0),
#         }
#         for item in ordered[-20:]
#     ]
#     if not points:
#         return {"points": [], "direction": "flat", "delta": 0.0}
#     midpoint = max(1, len(points) // 2)
#     early = points[:midpoint]
#     late = points[midpoint:]
#     early_avg = sum(point["score"] for point in early) / max(1, len(early))
#     late_avg = sum(point["score"] for point in late) / max(1, len(late))
#     delta = round(late_avg - early_avg, 4)
#     direction = "flat"
#     if delta > 0.04:
#         direction = "improving"
#     elif delta < -0.04:
#         direction = "declining"
#     return {"points": points, "direction": direction, "delta": delta}


# def build_eval_analytics(limit: int = 50, student_id: str | None = None) -> dict[str, Any]:
#     """Build grouped replay analytics for continuous evaluation."""
#     summaries = list_replay_artifacts(limit=limit)
#     if student_id:
#         summaries = [item for item in summaries if item.get("student_id") == student_id]

#     evaluations: list[dict[str, Any]] = []
#     for summary in summaries:
#         replay_id = str(summary.get("id", "") or "")
#         if not replay_id:
#             continue
#         artifact = get_replay_artifact(replay_id)
#         if artifact is None:
#             continue
#         evaluated = evaluate_replay_artifact(artifact)
#         raw_runtime_snapshot = artifact.get("runtime_snapshot", {}) or {}
#         runtime_snapshot = dict(raw_runtime_snapshot) if isinstance(raw_runtime_snapshot, dict) else {}
#         evaluations.append(
#             {
#                 **evaluated,
#                 "created_at": artifact.get("created_at", ""),
#                 "specialist_key": artifact.get("selected_specialist", "") or "unknown",
#                 "method_key": artifact.get("method", "") or "unknown",
#                 "model_key": runtime_snapshot.get("selected_text_model", "") or "unknown",
#                 "retrieval_mode_key": runtime_snapshot.get("selected_retrieval_mode", "") or "unknown",
#             }
#         )

#     by_specialist = _group_summary([{"key": item.get("specialist_key", "unknown"), **item} for item in evaluations])
#     by_method = _group_summary([{"key": item.get("method_key", "unknown"), **item} for item in evaluations])
#     by_model = _group_summary([{"key": item.get("model_key", "unknown"), **item} for item in evaluations])
#     by_retrieval_mode = _group_summary([{"key": item.get("retrieval_mode_key", "unknown"), **item} for item in evaluations])

#     average_score = round(
#         sum(float(item.get("score", 0.0) or 0.0) for item in evaluations) / max(1, len(evaluations)),
#         4,
#     )

#     return {
#         "summary": {
#             "total": len(evaluations),
#             "average_score": average_score,
#             "student_id": student_id or "",
#             "benchmark_set_count": len(list_benchmark_sets()),
#         },
#         "benchmarks": list_benchmark_sets(),
#         "comparisons": {
#             "by_specialist": by_specialist,
#             "by_method": by_method,
#             "by_model": by_model,
#             "by_retrieval_mode": by_retrieval_mode,
#         },
#         "trend": _trend_summary(evaluations),
#     }
