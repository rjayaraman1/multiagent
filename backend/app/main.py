from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Optional, Union

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_chroma import Chroma
from langchain_core.messages import HumanMessage
from langgraph.types import Command

load_dotenv()

from .astrology_engine import build_chart, summarize_chart
from .evaluate import log_chat, run_langsmith_eval
from .ingest import ingest
from .graph import build_graph
from .llm import generate_reading
from .human_handoff import store_handoff, get_pending, clear_handoff, has_pending
from .agents.orchestrator_agent import build_orchestrator, OrchestratorState
from .schemas import (
    AnalyzeResponse,
    BirthInput,
    ChartResponse,
    ChatRequest,
    ChatResponse,
    EvalRequest,
    EvalResponse,
    HandoffQuestion,
    HandoffResponse,
    PredictionReport,
    ReadingResponse,
)

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

_compiled_graph = None          # existing RAG chat graph
_vectorstore: Optional[Chroma] = None
_orchestrator = None            # new multi-agent orchestrator graph


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _compiled_graph, _vectorstore, _orchestrator
    _vectorstore = await asyncio.to_thread(ingest)
    _compiled_graph = build_graph()
    _orchestrator = build_orchestrator()
    print("[startup] Ingest complete. RAG graph + orchestrator ready.")
    yield


app = FastAPI(title="Vedic Astrology — Multi-Agent Enhancement", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://192.168.68.56:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _retrieve_passages(query: str, k: int = 3) -> list[str]:
    if _vectorstore is None:
        return []
    docs = _vectorstore.similarity_search(query, k=k)
    return [doc.page_content for doc in docs]


# ---------------------------------------------------------------------------
# Existing endpoints (unchanged API contract)
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "graph_ready": _compiled_graph is not None,
        "orchestrator_ready": _orchestrator is not None,
    }


@app.post("/api/chart", response_model=ChartResponse)
def chart(payload: BirthInput):
    return build_chart(payload)


@app.post("/api/reading", response_model=ReadingResponse)
def reading(payload: BirthInput):
    chart_obj = build_chart(payload)
    passages = _retrieve_passages(summarize_chart(chart_obj))
    return generate_reading(chart_obj, passages)


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze(payload: BirthInput):
    chart_obj = build_chart(payload)
    passages = _retrieve_passages(summarize_chart(chart_obj))
    reading_obj = generate_reading(chart_obj, passages)
    return AnalyzeResponse(chart=chart_obj, reading=reading_obj)


@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest):
    if _compiled_graph is None:
        raise HTTPException(status_code=503, detail="Graph not initialised — server is starting up.")

    config = {"configurable": {"thread_id": payload.session_id}}
    state = _compiled_graph.invoke(
        {
            "query": payload.message,
            "chart_context": payload.chart_summary or "",
            "messages": [HumanMessage(content=payload.message)],
            "turn": 0,
        },
        config=config,
    )

    answer = state["answer"]
    sources = state.get("sources", [])
    log_chat(session_id=payload.session_id, question=payload.message, answer=answer, sources=sources)
    return ChatResponse(answer=answer, sources=sources, session_id=payload.session_id)


@app.post("/api/evaluate", response_model=EvalResponse)
def evaluate(payload: EvalRequest = EvalRequest()):
    result = run_langsmith_eval(session_id=payload.session_id or None)
    return EvalResponse(**result)


# ---------------------------------------------------------------------------
# New multi-agent prediction endpoints
# ---------------------------------------------------------------------------

@app.post("/api/predict", response_model=Union[PredictionReport, HandoffQuestion])
def predict(payload: BirthInput):
    """Run the full multi-agent prediction pipeline.

    Returns a PredictionReport on success.
    Returns a HandoffQuestion if the pipeline needs human input before proceeding.
    """
    if _orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not ready.")

    session_id = f"predict-{payload.name.lower().replace(' ', '-')}-{id(payload)}"
    config = {"configurable": {"thread_id": session_id}}

    initial_state: OrchestratorState = {
        "session_id": session_id,
        "task": "generate_prediction_report",
        "birth_data": payload.model_dump(),
        "person_name": payload.name,
        "chart_result": None,
        "nakshatra_result": None,
        "final_report": None,
        "error_log": [],
        "retry_counts": {},
        "needs_human": False,
        "human_question": None,
        "human_response": None,
        "step_history": [],
    }

    try:
        result = _orchestrator.invoke(initial_state, config=config)
    except Exception as exc:
        # LangGraph raises GraphInterrupt when interrupt() is hit
        if "GraphInterrupt" in type(exc).__name__ or hasattr(exc, "args") and exc.args:
            # Extract the question from the interrupt value
            question = str(exc.args[0]) if exc.args else "Human input required."
            hq = store_handoff(
                session_id=session_id,
                question=question,
                context=f"Birth data: {payload.model_dump()}",
                step="orchestrator.interrupt",
            )
            return hq
        raise HTTPException(status_code=500, detail=str(exc))

    # Check if the graph paused mid-run (interrupt was returned as state)
    if result.get("needs_human") and result.get("human_question"):
        hq = store_handoff(
            session_id=session_id,
            question=result["human_question"],
            context=f"Step history: {result.get('step_history', [])}",
            step=result.get("step_history", ["unknown"])[-1] if result.get("step_history") else "unknown",
        )
        return hq

    report_dict = result.get("final_report")
    if not report_dict:
        raise HTTPException(status_code=500, detail="Prediction pipeline did not produce a report.")

    return PredictionReport(**report_dict)


@app.post("/api/predict/respond")
def predict_respond(payload: HandoffResponse):
    """Submit a human answer to resume a paused orchestrator graph.

    The graph was paused at an interrupt() node. This endpoint injects
    the human's answer via Command(resume=answer) and runs the graph to completion.
    Returns PredictionReport or another HandoffQuestion if more input is needed.
    """
    if _orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not ready.")

    session_id = payload.session_id
    if not has_pending(session_id):
        raise HTTPException(status_code=404, detail="No pending handoff for this session.")

    clear_handoff(session_id)
    config = {"configurable": {"thread_id": session_id}}

    try:
        result = _orchestrator.invoke(Command(resume=payload.answer), config=config)
    except Exception as exc:
        if "GraphInterrupt" in type(exc).__name__ or hasattr(exc, "args") and exc.args:
            question = str(exc.args[0]) if exc.args else "Further input required."
            hq = store_handoff(
                session_id=session_id,
                question=question,
                context="Graph resumed but encountered another interrupt.",
                step="orchestrator.second_interrupt",
            )
            return hq
        raise HTTPException(status_code=500, detail=str(exc))

    if result.get("needs_human") and result.get("human_question"):
        hq = store_handoff(
            session_id=session_id,
            question=result["human_question"],
            context=f"Step history: {result.get('step_history', [])}",
            step="orchestrator.post_resume",
        )
        return hq

    report_dict = result.get("final_report")
    if not report_dict:
        raise HTTPException(status_code=500, detail="Pipeline did not complete after human input.")

    return PredictionReport(**report_dict)


@app.get("/api/predict/status/{session_id}")
def predict_status(session_id: str):
    """Poll for a pending human handoff question.

    Returns the HandoffQuestion if the graph is paused waiting for input,
    or {"pending": false} if no handoff is active.
    """
    pending = get_pending(session_id)
    if pending:
        return pending
    return {"pending": False, "session_id": session_id}
