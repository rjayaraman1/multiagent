from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Any

from dotenv import load_dotenv

load_dotenv()

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_APP_DIR)
CSV_PATH = os.path.join(BASE_DIR, "chat_log.csv")
_CSV_HEADERS = ["timestamp", "session_id", "question", "answer", "sources"]
DATASET_NAME = "vedic-astro-chat-evals"

_SCORE_PROMPT = """\
You are evaluating a Vedic astrology chatbot response.

Criterion: {criterion}

Question: {question}
Response: {answer}

Score the response on a scale of 1 to 5:
1 - Completely fails the criterion
2 - Mostly fails, minor relevant content
3 - Partially meets the criterion
4 - Mostly meets the criterion
5 - Fully meets the criterion

Reply with a single digit (1, 2, 3, 4, or 5). Nothing else."""


def log_chat(session_id: str, question: str, answer: str, sources: list[str]) -> None:
    """Append a single chat turn to the CSV log file."""
    write_header = not os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(_CSV_HEADERS)
        writer.writerow([
            datetime.utcnow().isoformat(),
            session_id,
            question,
            answer,
            "; ".join(sources),
        ])


def read_log(session_id: str | None = None) -> list[dict]:
    if not os.path.exists(CSV_PATH):
        return []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if session_id:
        rows = [r for r in rows if r.get("session_id") == session_id]
    return rows


def _score(llm: Any, question: str, answer: str, criterion: str) -> float:
    """Return a normalized score 0.0–1.0 for the given criterion (from a 1–5 rubric)."""
    prompt = _SCORE_PROMPT.format(criterion=criterion, question=question, answer=answer)
    response = llm.invoke(prompt)
    raw = response.content.strip()
    try:
        rating = int(raw[0])
        rating = max(1, min(5, rating))  # clamp to [1, 5]
    except (ValueError, IndexError):
        rating = 1
    return (rating - 1) / 4.0  # maps 1→0.0, 2→0.25, 3→0.5, 4→0.75, 5→1.0


def run_langsmith_eval(session_id: str | None = None) -> dict:
    """
    Reads chat_log.csv (filtered to session_id when provided), pushes Q&A pairs to a
    LangSmith dataset, runs LLM-based criteria evaluations (Relevance + Quality) via
    langsmith.evaluate, and returns per-row scores plus aggregates.
    """
    rows = read_log(session_id=session_id)
    if not rows:
        msg = (
            "No chat interactions found for this session yet. Ask the agent some questions first."
            if session_id
            else "No chat interactions logged yet. Ask the agent some questions first."
        )
        return {"status": "no_data", "message": msg}

    api_key = os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        return {
            "status": "error",
            "message": (
                "LANGCHAIN_API_KEY is not set. "
                "Add it to backend/.env (LANGCHAIN_API_KEY=ls__...) to enable LangSmith evaluation."
            ),
        }

    from langsmith import Client
    from langsmith import evaluate as ls_evaluate
    from langchain_openai import ChatOpenAI

    client = Client()
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    # ── Refresh examples without deleting the dataset (preserves experiment history) ──
    # Deleting the dataset also deletes all past experiments linked to it.
    # Instead: keep the dataset alive, wipe only its examples, then re-add them.
    # Each ls_evaluate() call below creates a NEW experiment (unique suffix), so
    # all runs accumulate under the dataset's Experiments tab in LangSmith.
    try:
        dataset = client.read_dataset(dataset_name=DATASET_NAME)
        for ex in client.list_examples(dataset_id=dataset.id):
            client.delete_example(ex.id)
    except Exception:
        dataset = client.create_dataset(
            DATASET_NAME,
            description="Vedic Astrology RAG chatbot — logged Q&A pairs for offline evaluation",
        )

    for row in rows:
        client.create_example(
            inputs={"question": row["question"], "answer": row["answer"]},
            outputs={},
            dataset_id=dataset.id,
        )

    _rel_criterion = "Is the response relevant and on-topic for the Vedic astrology question asked?"
    _qual_criterion = (
        "Is the response accurate, informative, and genuinely helpful as a Vedic astrology answer?"
    )

    # ── Run experiment (no evaluators — we log feedback directly below) ────
    # Passing evaluators through ls_evaluate's internal protocol silently
    # drops scores in LangSmith 0.8.x. Using client.create_feedback() directly
    # is the guaranteed path that always appears in the UI's p50/p90/p99.
    def target(inputs: dict) -> dict:
        return {"answer": inputs.get("answer", "")}

    exp = ls_evaluate(
        target,
        data=DATASET_NAME,
        evaluators=[],
        experiment_prefix="vedic-astro-eval",
        max_concurrency=1,
        blocking=True,
    )

    # ── Score each result and log feedback directly to LangSmith ──────────
    rows_with_scores: list[dict] = []
    all_rel: list[float] = []
    all_qual: list[float] = []

    for result in exp:
        example = _get(result, "example")
        run = _get(result, "run")
        run_id = _get(run, "id")

        inputs = _inputs(example)
        q = inputs.get("question", "")
        a = inputs.get("answer", "")

        rel_score = _score(llm, q, a, _rel_criterion)
        qual_score = _score(llm, q, a, _qual_criterion)

        # Direct feedback logging — bypasses evaluator protocol entirely
        if run_id:
            client.create_feedback(run_id=run_id, key="relevance", score=rel_score)
            client.create_feedback(run_id=run_id, key="quality", score=qual_score)

        all_rel.append(rel_score)
        all_qual.append(qual_score)

        rows_with_scores.append({
            "question": q[:120],
            "answer": a[:200],
            "relevance": rel_score,
            "quality": qual_score,
        })

    avg_rel = round(sum(all_rel) / len(all_rel) * 100) if all_rel else 0
    avg_qual = round(sum(all_qual) / len(all_qual) * 100) if all_qual else 0

    dataset_url = f"https://smith.langchain.com/datasets/{dataset.id}"

    return {
        "status": "ok",
        "examples_count": len(rows),
        "dataset_url": dataset_url,
        "scores": {"relevance": avg_rel, "quality": avg_qual},
        "rows": rows_with_scores,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get(obj: Any, attr: str, default: Any = None) -> Any:
    """Uniform attribute access for both dicts and objects."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


def _inputs(obj: Any) -> dict:
    """Return the .inputs dict from a run/example object or dict."""
    raw = _get(obj, "inputs", {})
    return raw if isinstance(raw, dict) else {}
