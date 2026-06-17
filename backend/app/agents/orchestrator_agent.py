"""Orchestrator Agent — Top-level multi-agent pipeline controller.

Control flow:
    START
      → validate_input
            ↓ valid                     ↓ invalid / ambiguous
      run_chart_analyst         request_human_clarification
            ↓                                ↓ (human answers → resume)
      run_nakshatra_retriever ←────────────────
            ↓
      check_confidence
            ↓ confident           ↓ low confidence
      run_synthesizer     human_handoff_node
            ↓                     ↓ (human answers → resume)
           END           resume_synthesizer → END

Coordination pattern  : sequential with dependency gating
Delegation mechanism  : each specialized agent is invoked as a function (compiled subgraph)
Agent-to-agent comms  : all data flows through OrchestratorState fields — no direct calls
Human handoff         : LangGraph interrupt() pauses the graph; Command(resume=) restarts it
"""
from __future__ import annotations

from typing import List, Optional
from typing_extensions import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ..schemas import (
    ChartAnalysisResult, HandoffQuestion, NakshatraAnalysisResult, PredictionReport,
)
from .chart_analyst_agent import run_chart_analyst
from .nakshatra_retriever_agent import run_nakshatra_retriever
from .prediction_synthesizer_agent import run_synthesizer

# Threshold: if this many or more sections are low-confidence, escalate to human
LOW_CONFIDENCE_THRESHOLD = 2


# ── Orchestrator state ────────────────────────────────────────────────────────

class OrchestratorState(TypedDict):
    session_id: str
    task: str
    birth_data: dict
    person_name: str

    # Inter-agent communication fields (read/written exclusively by orchestrator)
    chart_result: Optional[dict]          # ChartAnalysisResult as dict
    nakshatra_result: Optional[dict]      # NakshatraAnalysisResult as dict
    final_report: Optional[dict]          # PredictionReport as dict

    # Control / audit
    error_log: List[str]
    retry_counts: dict                    # {step: count}
    needs_human: bool
    human_question: Optional[str]
    human_response: Optional[str]
    step_history: List[str]


# ── Node: validate input ──────────────────────────────────────────────────────

def node_validate_input(state: OrchestratorState) -> dict:
    bd = state.get("birth_data", {})
    required = ["birth_date", "birth_time", "birth_place"]
    missing = [f for f in required if not bd.get(f, "").strip()]
    step_history = list(state.get("step_history", []))

    if missing:
        step_history.append(f"validate_input: missing fields {missing}")
        return {
            "needs_human": True,
            "human_question": f"Missing birth details: {', '.join(missing)}. Please provide them to generate your prediction.",
            "step_history": step_history,
        }

    step_history.append("validate_input: ok")
    return {"needs_human": False, "step_history": step_history}


def route_after_validate(state: OrchestratorState) -> str:
    return "request_human_clarification" if state.get("needs_human") else "run_chart_analyst"


# ── Node: request human clarification (input validation failure) ─────────────

def node_request_human_clarification(state: OrchestratorState) -> dict:
    question = state.get("human_question", "Please provide complete birth details.")
    print(f"[orchestrator] Interrupting for human clarification: {question}")

    # LangGraph interrupt() suspends execution and surfaces the value to the caller
    human_answer = interrupt(question)

    step_history = list(state.get("step_history", []))
    step_history.append(f"request_human_clarification: human answered")

    # Merge human answer into birth_data if they provided corrections
    bd = dict(state.get("birth_data", {}))
    return {
        "human_response": human_answer,
        "needs_human": False,
        "step_history": step_history,
        "birth_data": bd,
    }


# ── Node: run chart analyst (Agent 1 delegation) ──────────────────────────────

def node_run_chart_analyst(state: OrchestratorState) -> dict:
    step_history = list(state.get("step_history", []))
    step_history.append("run_chart_analyst: delegating to chart_analyst_agent")
    print("[orchestrator] Delegating to chart_analyst_agent")

    result: ChartAnalysisResult = run_chart_analyst(state["birth_data"])

    error_log = list(state.get("error_log", []))
    error_log.extend(result.error_log)
    step_history.append(
        f"run_chart_analyst: {'success' if result.success else 'failed'}, "
        f"nakshatra={result.moon_nakshatra}, ascendant={result.ascendant}"
    )

    needs_human = not result.success
    human_question = None
    if needs_human:
        human_question = (
            "The chart calculation encountered issues. "
            "Could you verify: (1) birth date format YYYY-MM-DD, (2) time as HH:MM, "
            "(3) city name in English?"
        )

    return {
        "chart_result": result.model_dump(),
        "error_log": error_log,
        "needs_human": needs_human,
        "human_question": human_question,
        "step_history": step_history,
    }


def route_after_chart(state: OrchestratorState) -> str:
    if state.get("needs_human"):
        return "human_handoff_chart"
    return "run_nakshatra_retriever"


# ── Node: human handoff after chart failure ───────────────────────────────────

def node_human_handoff_chart(state: OrchestratorState) -> dict:
    question = state.get("human_question", "Please verify your birth details.")
    print(f"[orchestrator] Chart handoff — interrupting: {question}")
    human_answer = interrupt(question)
    step_history = list(state.get("step_history", []))
    step_history.append("human_handoff_chart: human answered, resuming with nakshatra_retriever")
    return {
        "human_response": human_answer,
        "needs_human": False,
        "step_history": step_history,
    }


# ── Node: run nakshatra retriever (Agent 2 delegation) ───────────────────────

def node_run_nakshatra_retriever(state: OrchestratorState) -> dict:
    step_history = list(state.get("step_history", []))
    step_history.append("run_nakshatra_retriever: delegating to nakshatra_retriever_agent")
    print("[orchestrator] Delegating to nakshatra_retriever_agent")

    chart = ChartAnalysisResult(**state["chart_result"])

    # Agent 2 reads moon_nakshatra from Agent 1's result — dependency gating
    moon_nakshatra = chart.moon_nakshatra or "Ashwini"
    chart_summary = (
        f"Ascendant: {chart.ascendant}, Moon Nakshatra: {moon_nakshatra}. "
        f"{chart.chart_analysis_text[:200] if chart.chart_analysis_text else ''}"
    )

    result: NakshatraAnalysisResult = run_nakshatra_retriever(moon_nakshatra, chart_summary)

    step_history.append(
        f"run_nakshatra_retriever: {len(result.sections)} sections, "
        f"low_confidence={result.low_confidence_count}"
    )

    return {
        "nakshatra_result": result.model_dump(),
        "step_history": step_history,
    }


# ── Node: check confidence gate ───────────────────────────────────────────────

def node_check_confidence(state: OrchestratorState) -> dict:
    nak = NakshatraAnalysisResult(**state["nakshatra_result"])
    step_history = list(state.get("step_history", []))

    if nak.low_confidence_count >= LOW_CONFIDENCE_THRESHOLD:
        low_areas = [s.life_area for s in nak.sections if s.low_confidence]
        question = (
            f"The knowledge base had limited information for: {', '.join(low_areas)}. "
            f"Would you like to provide any additional context about your interests or concerns "
            f"in these life areas? (Or type 'skip' to proceed with available information.)"
        )
        step_history.append(f"check_confidence: low confidence in {low_areas} — escalating to human")
        return {
            "needs_human": True,
            "human_question": question,
            "step_history": step_history,
        }

    step_history.append("check_confidence: confidence ok, proceeding to synthesizer")
    return {"needs_human": False, "step_history": step_history}


def route_after_confidence(state: OrchestratorState) -> str:
    return "human_handoff_synthesis" if state.get("needs_human") else "run_synthesizer"


# ── Node: human handoff before synthesis ─────────────────────────────────────

def node_human_handoff_synthesis(state: OrchestratorState) -> dict:
    question = state.get("human_question", "Any additional context before we finalize your prediction?")
    print(f"[orchestrator] Synthesis handoff — interrupting: {question}")
    human_answer = interrupt(question)
    step_history = list(state.get("step_history", []))
    step_history.append("human_handoff_synthesis: human answered, resuming synthesizer")
    return {
        "human_response": human_answer,
        "needs_human": False,
        "step_history": step_history,
    }


# ── Node: run synthesizer (Agent 3 delegation) ───────────────────────────────

def node_run_synthesizer(state: OrchestratorState) -> dict:
    step_history = list(state.get("step_history", []))
    step_history.append("run_synthesizer: delegating to prediction_synthesizer_agent")
    print("[orchestrator] Delegating to prediction_synthesizer_agent")

    # Agent 3 reads BOTH chart_result and nakshatra_result — dependency gating
    chart_result = ChartAnalysisResult(**state["chart_result"])
    nakshatra_result = NakshatraAnalysisResult(**state["nakshatra_result"])

    report: PredictionReport = run_synthesizer(
        session_id=state["session_id"],
        person_name=state.get("person_name", "Guest"),
        chart_result=chart_result,
        nakshatra_result=nakshatra_result,
        human_response=state.get("human_response"),
    )

    # Append full orchestrator step_history to report
    combined_history = step_history + ["run_synthesizer: report assembled"]
    report.step_history = combined_history

    step_history.append("run_synthesizer: prediction report complete")
    return {
        "final_report": report.model_dump(),
        "step_history": step_history,
    }


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_orchestrator(session_id: str | None = None):
    """Build and compile the orchestrator graph with MemorySaver checkpointer."""
    builder = StateGraph(OrchestratorState)

    builder.add_node("validate_input", node_validate_input)
    builder.add_node("request_human_clarification", node_request_human_clarification)
    builder.add_node("run_chart_analyst", node_run_chart_analyst)
    builder.add_node("human_handoff_chart", node_human_handoff_chart)
    builder.add_node("run_nakshatra_retriever", node_run_nakshatra_retriever)
    builder.add_node("check_confidence", node_check_confidence)
    builder.add_node("human_handoff_synthesis", node_human_handoff_synthesis)
    builder.add_node("run_synthesizer", node_run_synthesizer)

    builder.add_edge(START, "validate_input")
    builder.add_conditional_edges("validate_input", route_after_validate, {
        "run_chart_analyst": "run_chart_analyst",
        "request_human_clarification": "request_human_clarification",
    })
    builder.add_edge("request_human_clarification", "run_chart_analyst")
    builder.add_conditional_edges("run_chart_analyst", route_after_chart, {
        "run_nakshatra_retriever": "run_nakshatra_retriever",
        "human_handoff_chart": "human_handoff_chart",
    })
    builder.add_edge("human_handoff_chart", "run_nakshatra_retriever")
    builder.add_edge("run_nakshatra_retriever", "check_confidence")
    builder.add_conditional_edges("check_confidence", route_after_confidence, {
        "run_synthesizer": "run_synthesizer",
        "human_handoff_synthesis": "human_handoff_synthesis",
    })
    builder.add_edge("human_handoff_synthesis", "run_synthesizer")
    builder.add_edge("run_synthesizer", END)

    return builder.compile(checkpointer=MemorySaver())
