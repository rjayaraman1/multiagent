"""Agent 2 — Nakshatra Retriever

Receives moon nakshatra + chart summary from Agent 1's result.
For each life area (career, relationships, health, spirituality), retrieves
relevant passages from the knowledge base and generates a section reading.

Delegation input  : chart_result (ChartAnalysisResult dict)
Communication out : NakshatraAnalysisResult written into OrchestratorState["nakshatra_result"]
"""
from __future__ import annotations

from typing import List, Optional
from typing_extensions import TypedDict

from langgraph.graph import END, START, StateGraph

from ..schemas import NakshatraAnalysisResult, NakshatraSectionResult
from ..tools import retrieve_vedic_knowledge, generate_section_reading

LIFE_AREAS = [
    ("Career and Finances", "nakshatra"),
    ("Relationships and Love", "nakshatra"),
    ("Health and Vitality", "nakshatra"),
    ("Spirituality and Inner Growth", "general"),
]

MIN_PASSAGES_FOR_CONFIDENCE = 2


class NakshatraRetrieverState(TypedDict):
    moon_nakshatra: str
    chart_summary: str
    life_areas_todo: List[tuple]        # list of (area_name, source_filter) remaining
    sections: List[dict]                # completed NakshatraSectionResult dicts
    failed_retrievals: List[str]
    low_confidence_count: int
    result: Optional[dict]              # final NakshatraAnalysisResult as dict


# ── Node: initialise the work list ───────────────────────────────────────────

def node_init(state: NakshatraRetrieverState) -> dict:
    print(f"[nakshatra_retriever] Starting for nakshatra: {state['moon_nakshatra']}")
    return {"life_areas_todo": list(LIFE_AREAS), "sections": [], "failed_retrievals": [], "low_confidence_count": 0}


# ── Node: retrieve + generate one life area section ──────────────────────────

def node_process_next_area(state: NakshatraRetrieverState) -> dict:
    todo = list(state.get("life_areas_todo", []))
    if not todo:
        return {}

    area_name, source_filter = todo[0]
    remaining = todo[1:]

    nakshatra = state["moon_nakshatra"]
    chart_summary = state["chart_summary"]

    # Build a targeted retrieval query for this life area
    query = f"{nakshatra} nakshatra {area_name.lower()} Vedic astrology"
    print(f"[nakshatra_retriever] Retrieving for '{area_name}' (filter={source_filter})")

    retrieval = retrieve_vedic_knowledge.invoke({
        "query": query,
        "source_filter": source_filter,
    })

    passages = retrieval.get("passages", [])
    low_confidence = len(passages) < MIN_PASSAGES_FOR_CONFIDENCE

    if not retrieval.get("success") or not passages:
        failed = list(state.get("failed_retrievals", []))
        failed.append(area_name)
        low_confidence = True
        passages = []

    print(f"[nakshatra_retriever] '{area_name}': {len(passages)} passages, low_confidence={low_confidence}")

    # Generate the section even if passages are sparse (fallback text will be used)
    reading = generate_section_reading.invoke({
        "topic": area_name,
        "chart_summary": f"Moon Nakshatra: {nakshatra}. {chart_summary}",
        "passages": passages,
        "agent_name": "nakshatra_retriever",
    })

    section = NakshatraSectionResult(
        life_area=area_name,
        heading=reading.get("heading", area_name),
        body=reading.get("body", f"Interpretation for {area_name} based on {nakshatra} nakshatra."),
        low_confidence=low_confidence,
        passages_used=len(passages),
    )

    sections = list(state.get("sections", []))
    sections.append(section.model_dump())

    failed_retrievals = list(state.get("failed_retrievals", []))
    lcc = state.get("low_confidence_count", 0) + (1 if low_confidence else 0)

    return {
        "life_areas_todo": remaining,
        "sections": sections,
        "failed_retrievals": failed_retrievals,
        "low_confidence_count": lcc,
    }


def route_continue_or_finish(state: NakshatraRetrieverState) -> str:
    if state.get("life_areas_todo"):
        return "process_next_area"
    return "assemble_result"


# ── Node: assemble result ─────────────────────────────────────────────────────

def node_assemble_result(state: NakshatraRetrieverState) -> dict:
    sections = [NakshatraSectionResult(**s) for s in state.get("sections", [])]
    result = NakshatraAnalysisResult(
        sections=sections,
        failed_retrievals=state.get("failed_retrievals", []),
        low_confidence_count=state.get("low_confidence_count", 0),
        success=True,
    )
    return {"result": result.model_dump()}


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_nakshatra_retriever_graph():
    builder = StateGraph(NakshatraRetrieverState)

    builder.add_node("init", node_init)
    builder.add_node("process_next_area", node_process_next_area)
    builder.add_node("assemble_result", node_assemble_result)

    builder.add_edge(START, "init")
    builder.add_edge("init", "process_next_area")
    builder.add_conditional_edges("process_next_area", route_continue_or_finish, {
        "process_next_area": "process_next_area",
        "assemble_result": "assemble_result",
    })
    builder.add_edge("assemble_result", END)

    return builder.compile()


_nakshatra_retriever_graph = None


def run_nakshatra_retriever(moon_nakshatra: str, chart_summary: str) -> NakshatraAnalysisResult:
    """Entry point called by the orchestrator. Returns NakshatraAnalysisResult."""
    global _nakshatra_retriever_graph
    if _nakshatra_retriever_graph is None:
        _nakshatra_retriever_graph = build_nakshatra_retriever_graph()

    initial_state: NakshatraRetrieverState = {
        "moon_nakshatra": moon_nakshatra,
        "chart_summary": chart_summary,
        "life_areas_todo": [],
        "sections": [],
        "failed_retrievals": [],
        "low_confidence_count": 0,
        "result": None,
    }
    final = _nakshatra_retriever_graph.invoke(initial_state)
    result_dict = final.get("result") or {}
    return NakshatraAnalysisResult(**result_dict) if result_dict else NakshatraAnalysisResult(success=False)
