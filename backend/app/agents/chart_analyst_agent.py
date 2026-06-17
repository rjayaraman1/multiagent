"""Agent 1 — Chart Analyst

Receives birth data, builds the Vedic chart, computes Vimshottari Dasha periods,
and generates a chart analysis text section. Runs as a LangGraph StateGraph.

Delegation input  : birth_data dict
Communication out : ChartAnalysisResult written into OrchestratorState["chart_result"]
"""
from __future__ import annotations

from typing import List, Optional
from typing_extensions import TypedDict

from langgraph.graph import END, START, StateGraph

from ..schemas import BirthInput, ChartAnalysisResult, DashaPeriod
from ..tools import build_birth_chart, calculate_vimshottari_dasha, generate_section_reading, flag_for_human_review

MAX_RETRIES = 2


class ChartAnalystState(TypedDict):
    birth_data: dict
    chart_raw: Optional[dict]           # raw output from build_birth_chart tool
    dasha_raw: Optional[dict]           # raw output from calculate_vimshottari_dasha tool
    analysis_raw: Optional[dict]        # raw output from generate_section_reading tool
    error_log: List[str]
    retry_count: int
    needs_human: bool
    human_question: Optional[str]
    result: Optional[dict]              # final ChartAnalysisResult as dict


# ── Node: build chart ─────────────────────────────────────────────────────────

def node_build_chart(state: ChartAnalystState) -> dict:
    bd = state["birth_data"]
    print(f"[chart_analyst] Building chart for {bd.get('name', 'Guest')}")
    result = build_birth_chart.invoke({
        "birth_date": bd["birth_date"],
        "birth_time": bd["birth_time"],
        "birth_place": bd["birth_place"],
        "timezone": bd.get("timezone", "+05:30"),
        "name": bd.get("name", "Guest"),
    })
    return {"chart_raw": result}


def route_after_chart(state: ChartAnalystState) -> str:
    chart = state.get("chart_raw", {})
    if chart.get("success"):
        return "build_dasha"
    retry = state.get("retry_count", 0)
    if retry < MAX_RETRIES:
        print(f"[chart_analyst] chart failed, retry {retry + 1}/{MAX_RETRIES}: {chart.get('error')}")
        return "retry_chart"
    print(f"[chart_analyst] chart failed after {MAX_RETRIES} retries — flagging for human")
    return "flag_human"


def node_retry_chart(state: ChartAnalystState) -> dict:
    error_log = list(state.get("error_log", []))
    error_log.append(f"Chart build failed: {state.get('chart_raw', {}).get('error', 'unknown')}")
    # Re-attempt the chart build with same data
    bd = state["birth_data"]
    result = build_birth_chart.invoke({
        "birth_date": bd["birth_date"],
        "birth_time": bd["birth_time"],
        "birth_place": bd["birth_place"],
        "timezone": bd.get("timezone", "+05:30"),
        "name": bd.get("name", "Guest"),
    })
    return {
        "chart_raw": result,
        "retry_count": state.get("retry_count", 0) + 1,
        "error_log": error_log,
    }


def node_flag_human(state: ChartAnalystState) -> dict:
    error_log = list(state.get("error_log", []))
    chart_err = state.get("chart_raw", {}).get("error", "unknown error")
    error_log.append(f"Chart build failed after retries: {chart_err}")
    flag = flag_for_human_review.invoke({
        "reason": "Could not calculate the birth chart accurately. Please verify the birth date, time, and place.",
        "context": f"Birth data: {state['birth_data']}. Last error: {chart_err}",
        "step": "chart_analyst.build_chart",
    })
    return {
        "needs_human": True,
        "human_question": flag["question"],
        "error_log": error_log,
    }


# ── Node: calculate dasha ─────────────────────────────────────────────────────

def node_build_dasha(state: ChartAnalystState) -> dict:
    chart = state["chart_raw"]
    profile = chart.get("profile", {})
    moon_nakshatra = profile.get("moon_nakshatra", "Ashwini")

    # Find moon degree within its nakshatra from placements
    placements = chart.get("placements", [])
    moon_placement = next((p for p in placements if p["body"] == "Moon"), None)
    moon_degree = moon_placement["degree"] % (360 / 27) if moon_placement else 0.0

    print(f"[chart_analyst] Calculating dasha for nakshatra: {moon_nakshatra}")
    result = calculate_vimshottari_dasha.invoke({
        "birth_date": state["birth_data"]["birth_date"],
        "moon_nakshatra": moon_nakshatra,
        "moon_degree_in_nakshatra": moon_degree,
    })
    return {"dasha_raw": result}


# ── Node: generate chart analysis text ───────────────────────────────────────

def node_generate_analysis(state: ChartAnalystState) -> dict:
    chart = state["chart_raw"]
    summary = chart.get("summary", "No chart summary available.")
    dasha = state.get("dasha_raw", {})
    current_dasha = dasha.get("current_dasha", {})
    dasha_info = ""
    if current_dasha:
        dasha_info = f" Current Vimshottari Dasha: {current_dasha.get('planet')} (until {current_dasha.get('end_date')})."

    print("[chart_analyst] Generating chart analysis section")
    result = generate_section_reading.invoke({
        "topic": "Chart Overview and Planetary Configuration",
        "chart_summary": summary + dasha_info,
        "passages": [],
        "agent_name": "chart_analyst",
    })
    return {"analysis_raw": result}


# ── Node: assemble result ─────────────────────────────────────────────────────

def node_assemble_result(state: ChartAnalystState) -> dict:
    chart = state.get("chart_raw", {})
    dasha_raw = state.get("dasha_raw", {})
    analysis = state.get("analysis_raw", {})

    dasha_periods = []
    for p in dasha_raw.get("periods", []):
        dasha_periods.append(DashaPeriod(**p))

    from ..schemas import ChartResponse, PlanetPlacement
    chart_response = None
    if chart.get("success"):
        placements = [PlanetPlacement(**pl) for pl in chart.get("placements", [])]
        chart_response = ChartResponse(
            profile=chart.get("profile", {}),
            placements=placements,
            house_labels=chart.get("house_labels", []),
        )

    profile = chart.get("profile", {})
    result = ChartAnalysisResult(
        chart_data=chart_response,
        dasha_periods=dasha_periods,
        chart_analysis_text=analysis.get("body", ""),
        moon_nakshatra=profile.get("moon_nakshatra", ""),
        ascendant=profile.get("ascendant_sign", ""),
        error_log=state.get("error_log", []),
        success=chart.get("success", False),
    )
    return {"result": result.model_dump()}


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_chart_analyst_graph():
    builder = StateGraph(ChartAnalystState)

    builder.add_node("build_chart", node_build_chart)
    builder.add_node("retry_chart", node_retry_chart)
    builder.add_node("flag_human", node_flag_human)
    builder.add_node("build_dasha", node_build_dasha)
    builder.add_node("generate_analysis", node_generate_analysis)
    builder.add_node("assemble_result", node_assemble_result)

    builder.add_edge(START, "build_chart")
    builder.add_conditional_edges("build_chart", route_after_chart, {
        "build_dasha": "build_dasha",
        "retry_chart": "retry_chart",
        "flag_human": "flag_human",
    })
    builder.add_conditional_edges("retry_chart", route_after_chart, {
        "build_dasha": "build_dasha",
        "retry_chart": "retry_chart",
        "flag_human": "flag_human",
    })
    builder.add_edge("flag_human", "assemble_result")
    builder.add_edge("build_dasha", "generate_analysis")
    builder.add_edge("generate_analysis", "assemble_result")
    builder.add_edge("assemble_result", END)

    return builder.compile()


# Module-level compiled graph (lazy)
_chart_analyst_graph = None


def run_chart_analyst(birth_data: dict) -> ChartAnalysisResult:
    """Entry point called by the orchestrator. Returns ChartAnalysisResult."""
    global _chart_analyst_graph
    if _chart_analyst_graph is None:
        _chart_analyst_graph = build_chart_analyst_graph()

    initial_state: ChartAnalystState = {
        "birth_data": birth_data,
        "chart_raw": None,
        "dasha_raw": None,
        "analysis_raw": None,
        "error_log": [],
        "retry_count": 0,
        "needs_human": False,
        "human_question": None,
        "result": None,
    }
    final = _chart_analyst_graph.invoke(initial_state)
    result_dict = final.get("result") or {}
    return ChartAnalysisResult(**result_dict) if result_dict else ChartAnalysisResult(success=False)
