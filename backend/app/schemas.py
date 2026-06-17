from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


# ── Existing schemas (unchanged) ─────────────────────────────────────────────

class BirthInput(BaseModel):
    name: str = Field(default="Guest", description="Optional display name")
    birth_date: str = Field(..., description="YYYY-MM-DD")
    birth_time: str = Field(..., description="HH:MM")
    birth_place: str = Field(..., description="City, Country")
    timezone: str = Field(default="+05:30", description="UTC offset fallback if auto-detection fails")


class PlanetPlacement(BaseModel):
    body: str
    degree: float
    sign: str
    house: int


class ChartResponse(BaseModel):
    profile: dict
    placements: List[PlanetPlacement]
    house_labels: List[str]


class ReadingSection(BaseModel):
    heading: str
    body: str


class ReadingResponse(BaseModel):
    headline: str
    summary: str
    sections: List[ReadingSection]
    source_passages: List[str]
    prompt: Optional[str] = None


class AnalyzeResponse(BaseModel):
    chart: ChartResponse
    reading: ReadingResponse


class ChatRequest(BaseModel):
    message: str = Field(..., description="User's chat message")
    session_id: str = Field(..., description="Unique session identifier for conversation history")
    chart_summary: Optional[str] = Field(None, description="Chart summary string for personalised context")


class ChatResponse(BaseModel):
    answer: str
    sources: List[str]
    session_id: str


class EvalRequest(BaseModel):
    session_id: Optional[str] = Field(None, description="If provided, evaluate only this session's interactions")


class EvalRow(BaseModel):
    question: str
    answer: str
    relevance: Optional[int] = None
    quality: Optional[int] = None


class EvalResponse(BaseModel):
    status: str  # "ok" | "no_data" | "error"
    message: Optional[str] = None
    examples_count: Optional[int] = None
    dataset_url: Optional[str] = None
    scores: Optional[dict] = None
    rows: Optional[List[EvalRow]] = None


# ── New multi-agent schemas ───────────────────────────────────────────────────

class DashaPeriod(BaseModel):
    planet: str
    start_date: str
    end_date: str
    is_current: bool = False
    sub_periods: Optional[List[str]] = None


class ReportSection(BaseModel):
    heading: str
    body: str
    agent_source: str              # "chart_analyst" | "nakshatra_retriever" | "synthesizer"
    confidence: float = 1.0        # 0.0–1.0
    low_confidence: bool = False


class AgentAttribution(BaseModel):
    chart_analyst: str = "Chart analysis and dasha calculation"
    nakshatra_retriever: str = "Nakshatra-based life area retrieval"
    synthesizer: str = "Executive summary and report assembly"
    human_input: Optional[str] = None  # set if human answered a handoff question


class PredictionReport(BaseModel):
    session_id: str
    person_name: str
    executive_summary: str
    sections: List[ReportSection]
    dasha_periods: List[DashaPeriod]
    agent_attribution: AgentAttribution
    low_confidence_count: int = 0
    human_input_used: bool = False
    step_history: List[str] = Field(default_factory=list)


class HandoffQuestion(BaseModel):
    session_id: str
    question: str
    context: str
    step: str                      # which orchestrator step triggered the handoff


class HandoffResponse(BaseModel):
    session_id: str
    answer: str


# ── Internal agent result schemas (used between agents via OrchestratorState) ─

class ChartAnalysisResult(BaseModel):
    chart_data: Optional[ChartResponse] = None
    dasha_periods: List[DashaPeriod] = Field(default_factory=list)
    chart_analysis_text: str = ""
    moon_nakshatra: str = ""
    ascendant: str = ""
    error_log: List[str] = Field(default_factory=list)
    success: bool = True


class NakshatraSectionResult(BaseModel):
    life_area: str
    heading: str
    body: str
    low_confidence: bool = False
    passages_used: int = 0


class NakshatraAnalysisResult(BaseModel):
    sections: List[NakshatraSectionResult] = Field(default_factory=list)
    failed_retrievals: List[str] = Field(default_factory=list)
    low_confidence_count: int = 0
    success: bool = True
