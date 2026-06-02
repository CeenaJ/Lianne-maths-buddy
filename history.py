"""Lightweight JSON-backed history of quiz attempts, for the parent dashboard.

Each completed quiz is stored as one "attempt" with per-question results, so we
can roll up topics covered, accuracy, and capability by question type over time.
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HISTORY_FILE = Path(__file__).with_name("history.json")

# How question types are shown to parents.
TYPE_LABELS = {
    "multiple_choice": "Multiple choice",
    "short_answer": "Short answer",
}


def load_attempts() -> list[dict]:
    """Return all stored attempts (oldest first). Empty list if none yet."""
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def record_attempt(score: int, total: int, results: list[dict]) -> None:
    """Append a completed quiz.

    `results` is a list of {"topic", "type", "correct"} dicts, one per question.
    """
    attempts = load_attempts()
    attempts.append(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "score": score,
            "total": total,
            "results": results,
        }
    )
    HISTORY_FILE.write_text(json.dumps(attempts, indent=2))


def clear_history() -> None:
    """Delete all stored attempts."""
    HISTORY_FILE.unlink(missing_ok=True)


def capability_label(pct: float) -> str:
    """Map an accuracy fraction (0-1) to a friendly capability level."""
    if pct >= 0.9:
        return "⭐ Expert"
    if pct >= 0.75:
        return "💪 Proficient"
    if pct >= 0.5:
        return "🌱 Developing"
    return "🔰 Beginner"


def _accuracy(rows: list[dict]) -> tuple[int, int, float]:
    """Return (correct, total, fraction) for a list of result rows."""
    total = len(rows)
    correct = sum(1 for r in rows if r.get("correct"))
    return correct, total, (correct / total if total else 0.0)


def summarize(attempts: list[dict]) -> dict:
    """Aggregate attempts into the numbers the dashboard displays."""
    all_results = [r for a in attempts for r in a.get("results", [])]
    correct, total, overall_pct = _accuracy(all_results)

    by_topic = defaultdict(list)
    by_type = defaultdict(list)
    for r in all_results:
        by_topic[r.get("topic", "General")].append(r)
        by_type[r.get("type", "short_answer")].append(r)

    def rollup(grouped: dict) -> list[dict]:
        out = []
        for name, rows in grouped.items():
            c, t, pct = _accuracy(rows)
            out.append(
                {
                    "name": name,
                    "done": t,
                    "correct": c,
                    "pct": pct,
                    "level": capability_label(pct),
                }
            )
        return sorted(out, key=lambda x: x["done"], reverse=True)

    return {
        "quizzes": len(attempts),
        "questions": total,
        "correct": correct,
        "wrong": total - correct,
        "overall_pct": overall_pct,
        "topics": rollup(by_topic),
        "types": rollup({TYPE_LABELS.get(k, k): v for k, v in by_type.items()}),
    }
