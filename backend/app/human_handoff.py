"""Human Handoff Infrastructure

Manages the in-memory queue of pending human handoff questions and provides
helpers to resume a paused OrchestratorGraph via LangGraph's Command(resume=).

The queue is keyed by session_id. When the orchestrator graph reaches an
interrupt() node, the API endpoint stores the question here. The frontend polls
GET /api/predict/status/{session_id} to detect it. When the human answers,
POST /api/predict/respond injects the answer via Command(resume=answer).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .schemas import HandoffQuestion

# In-memory store: session_id → HandoffQuestion
# For production this would be Redis or a database.
_handoff_queue: dict[str, HandoffQuestion] = {}


def store_handoff(session_id: str, question: str, context: str, step: str) -> HandoffQuestion:
    """Record that a graph is paused and waiting for human input."""
    hq = HandoffQuestion(
        session_id=session_id,
        question=question,
        context=context,
        step=step,
    )
    _handoff_queue[session_id] = hq
    print(f"[handoff] Stored question for session {session_id}: {question[:80]}...")
    return hq


def get_pending(session_id: str) -> Optional[HandoffQuestion]:
    """Return the pending question for a session, or None if none exists."""
    return _handoff_queue.get(session_id)


def clear_handoff(session_id: str) -> None:
    """Remove the pending question after the human has answered."""
    _handoff_queue.pop(session_id, None)


def has_pending(session_id: str) -> bool:
    return session_id in _handoff_queue
