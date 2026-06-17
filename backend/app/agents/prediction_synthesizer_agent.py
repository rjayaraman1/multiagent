"""Agent 3 — Prediction Synthesizer

Receives ChartAnalysisResult and NakshatraAnalysisResult from the orchestrator.
Synthesizes them into a final PredictionReport with an executive summary,
ordered sections, dasha timeline, and full agent attribution.

Delegation input  : chart_result + nakshatra_result + optional human_response
Communication out : PredictionReport written into OrchestratorState["final_report"]
"""
from __future__ import annotations

from typing import List, Optional
from typing_extensions import TypedDict

from langgraph.graph import END, START, StateGraph

from ..schemas import (
    AgentAttribution, ChartAnalysisResult, DashaPeriod,
    NakshatraAnalysisResult, PredictionReport, ReportSection,
)
from ..tools import generate_section_reading


class SynthesizerState(TypedDict):
    session_id: str
    person_name: str
    chart_result: dict               # ChartAnalysisResult as dict
    nakshatra_result: dict           # NakshatraAnalysisResult as dict
    human_response: Optional[str]    # injected if human handoff occurred upstream
    chart_section: Optional[dict]    # ReportSection dict from chart analyst
    nakshatra_sections: List[dict]   # ReportSection dicts from nakshatra retriever
    executive_summary: Optional[str]
    result: Optional[dict]           # final PredictionReport as dict


# ── Node: build chart section ─────────────────────────────────────────────────

def node_build_chart_section(state: SynthesizerState) -> dict:
    chart = ChartAnalysisResult(**state["chart_result"])
    human_note = ""
    if state.get("human_response"):
        human_note = f" User clarification: {state['human_response']}."

    print("[synthesizer] Building chart overview section")
    section = ReportSection(
        heading="Chart Overview and Planetary Configuration",
        body=chart.chart_analysis_text + human_note if chart.chart_analysis_text
             else f"Ascendant: {chart.ascendant}, Moon Nakshatra: {chart.moon_nakshatra}.{human_note}",
        agent_source="chart_analyst",
        confidence=1.0 if chart.success else 0.5,
        low_confidence=not chart.success,
    )
    return {"chart_section": section.model_dump()}


# ── Node: build nakshatra sections ───────────────────────────────────────────

def node_build_nakshatra_sections(state: SynthesizerState) -> dict:
    nak = NakshatraAnalysisResult(**state["nakshatra_result"])
    sections = []
    for s in nak.sections:
        confidence = 0.6 if s.low_confidence else 1.0
        sections.append(ReportSection(
            heading=s.heading,
            body=s.body,
            agent_source="nakshatra_retriever",
            confidence=confidence,
            low_confidence=s.low_confidence,
        ).model_dump())
    print(f"[synthesizer] Assembled {len(sections)} nakshatra sections")
    return {"nakshatra_sections": sections}


# ── Node: generate executive summary ─────────────────────────────────────────

def node_generate_summary(state: SynthesizerState) -> dict:
    chart = ChartAnalysisResult(**state["chart_result"])
    nak = NakshatraAnalysisResult(**state["nakshatra_result"])

    # Collect section headings for context
    section_topics = [s["heading"] for s in state.get("nakshatra_sections", [])]
    human_context = ""
    if state.get("human_response"):
        human_context = f" Human clarification provided: {state['human_response']}."

    chart_summary = (
        f"Ascendant: {chart.ascendant}, Moon Nakshatra: {chart.moon_nakshatra}. "
        f"Dasha: {chart.dasha_periods[0].planet if chart.dasha_periods else 'unknown'}."
    )
    passages_context = [
        f"Topics covered: {', '.join(section_topics)}.",
        f"Low confidence areas: {nak.low_confidence_count}.",
        human_context,
    ]

    print("[synthesizer] Generating executive summary")
    result = generate_section_reading.invoke({
        "topic": "Executive Summary",
        "chart_summary": chart_summary,
        "passages": [p for p in passages_context if p.strip()],
        "agent_name": "synthesizer",
    })

    summary_text = result.get("body", f"Vedic prediction report for {state['person_name']}.")
    return {"executive_summary": summary_text}


# ── Node: assemble final report ───────────────────────────────────────────────

def node_assemble_report(state: SynthesizerState) -> dict:
    chart = ChartAnalysisResult(**state["chart_result"])
    nak = NakshatraAnalysisResult(**state["nakshatra_result"])

    # Section order: chart overview first, then life areas
    all_sections: List[ReportSection] = []
    if state.get("chart_section"):
        all_sections.append(ReportSection(**state["chart_section"]))
    for s in state.get("nakshatra_sections", []):
        all_sections.append(ReportSection(**s))

    dasha_periods = chart.dasha_periods or []
    low_conf_count = sum(1 for s in all_sections if s.low_confidence)

    attribution = AgentAttribution(
        human_input=state.get("human_response"),
    )

    report = PredictionReport(
        session_id=state["session_id"],
        person_name=state["person_name"],
        executive_summary=state.get("executive_summary", "Prediction report generated."),
        sections=all_sections,
        dasha_periods=dasha_periods,
        agent_attribution=attribution,
        low_confidence_count=low_conf_count,
        human_input_used=bool(state.get("human_response")),
        step_history=[
            "chart_analyst: chart built",
            "chart_analyst: dasha calculated",
            "nakshatra_retriever: life areas retrieved",
            "synthesizer: sections assembled",
            "synthesizer: executive summary generated",
        ],
    )
    return {"result": report.model_dump()}


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_synthesizer_graph():
    builder = StateGraph(SynthesizerState)

    builder.add_node("build_chart_section", node_build_chart_section)
    builder.add_node("build_nakshatra_sections", node_build_nakshatra_sections)
    builder.add_node("generate_summary", node_generate_summary)
    builder.add_node("assemble_report", node_assemble_report)

    builder.add_edge(START, "build_chart_section")
    builder.add_edge("build_chart_section", "build_nakshatra_sections")
    builder.add_edge("build_nakshatra_sections", "generate_summary")
    builder.add_edge("generate_summary", "assemble_report")
    builder.add_edge("assemble_report", END)

    return builder.compile()


_synthesizer_graph = None


def run_synthesizer(
    session_id: str,
    person_name: str,
    chart_result: ChartAnalysisResult,
    nakshatra_result: NakshatraAnalysisResult,
    human_response: Optional[str] = None,
) -> PredictionReport:
    """Entry point called by the orchestrator. Returns PredictionReport."""
    global _synthesizer_graph
    if _synthesizer_graph is None:
        _synthesizer_graph = build_synthesizer_graph()

    initial_state: SynthesizerState = {
        "session_id": session_id,
        "person_name": person_name,
        "chart_result": chart_result.model_dump(),
        "nakshatra_result": nakshatra_result.model_dump(),
        "human_response": human_response,
        "chart_section": None,
        "nakshatra_sections": [],
        "executive_summary": None,
        "result": None,
    }
    final = _synthesizer_graph.invoke(initial_state)
    result_dict = final.get("result") or {}
    return PredictionReport(**result_dict) if result_dict else PredictionReport(
        session_id=session_id,
        person_name=person_name,
        executive_summary="Report generation failed.",
        sections=[],
        dasha_periods=[],
        agent_attribution=AgentAttribution(),
    )
