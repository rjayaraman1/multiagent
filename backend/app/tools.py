from __future__ import annotations

import os
from typing import List, Optional

from langchain_core.tools import tool

from .astrology_engine import build_chart, summarize_chart, NAKSHATRAS
from .schemas import BirthInput, ChartResponse, DashaPeriod


# ── Tool 1: Build birth chart ─────────────────────────────────────────────────

@tool
def build_birth_chart(
    birth_date: str,
    birth_time: str,
    birth_place: str,
    timezone: str = "+05:30",
    name: str = "Guest",
) -> dict:
    """Build a Vedic birth chart from birth details.

    Returns a dict with profile (ascendant, moon sign, moon nakshatra, sun sign),
    planetary placements, and house labels. Returns {"error": reason} on failure.
    """
    try:
        payload = BirthInput(
            name=name,
            birth_date=birth_date,
            birth_time=birth_time,
            birth_place=birth_place,
            timezone=timezone,
        )
        chart = build_chart(payload)
        return {
            "success": True,
            "profile": chart.profile,
            "placements": [p.model_dump() for p in chart.placements],
            "house_labels": chart.house_labels,
            "summary": summarize_chart(chart),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ── Tool 2: Retrieve Vedic knowledge ─────────────────────────────────────────

@tool
def retrieve_vedic_knowledge(query: str, source_filter: Optional[str] = None) -> dict:
    """Search the Vedic astrology knowledge base for relevant passages.

    source_filter can be "nakshatra", "raashi", or "general" (or None for no filter).
    Returns up to 4 passages. Returns {"error": reason, "passages": []} on failure.
    """
    try:
        import os
        from langchain_chroma import Chroma
        from langchain_openai import OpenAIEmbeddings

        _APP_DIR = os.path.dirname(os.path.abspath(__file__))
        BASE_DIR = os.path.dirname(_APP_DIR)
        CHROMA_DIR = os.path.join(BASE_DIR, ".chroma")

        embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        vs = Chroma(
            collection_name="vedic_astrology",
            embedding_function=embeddings,
            persist_directory=CHROMA_DIR,
        )

        search_kwargs: dict = {"k": 4}
        if source_filter in ("nakshatra", "raashi", "general"):
            search_kwargs["filter"] = {"source": source_filter}

        docs = vs.as_retriever(search_type="similarity", search_kwargs=search_kwargs).invoke(query)

        # Fallback: retry without filter if fewer than 2 results
        if len(docs) < 2 and source_filter:
            docs = vs.as_retriever(
                search_type="similarity", search_kwargs={"k": 4}
            ).invoke(query)

        passages = [doc.page_content for doc in docs]
        sources = list({doc.metadata.get("file_name", "unknown") for doc in docs})

        return {"success": True, "passages": passages, "sources": sources, "count": len(passages)}
    except Exception as exc:
        return {"success": False, "error": str(exc), "passages": [], "sources": []}


# ── Tool 3: Generate a section reading ───────────────────────────────────────

@tool
def generate_section_reading(
    topic: str,
    chart_summary: str,
    passages: List[str],
    agent_name: str = "synthesizer",
) -> dict:
    """Generate one section of a prediction report using the LLM.

    topic: heading/life-area (e.g. "Career and Finances")
    chart_summary: summarized chart string
    passages: relevant retrieved text passages
    Returns {"heading", "body", "agent_source"} or {"error": reason} on LLM failure.
    """
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.prompts import ChatPromptTemplate

        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.4)

        prompt = ChatPromptTemplate.from_template(
            """You are a Vedic astrology expert writing a section of a personal prediction report.

Topic / Life Area: {topic}

Chart Summary:
{chart_summary}

Relevant Vedic Passages:
{passages}

Write a clear, warm, and specific 3–5 sentence interpretation for "{topic}" based on this chart and the passages above.
Address the person directly. Focus only on this life area. Do not repeat the chart summary.

Section body:"""
        )

        chain = prompt | llm
        response = chain.invoke({
            "topic": topic,
            "chart_summary": chart_summary,
            "passages": "\n---\n".join(passages) if passages else "No specific passages retrieved.",
        })
        return {
            "success": True,
            "heading": topic,
            "body": response.content.strip(),
            "agent_source": agent_name,
        }
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "heading": topic,
            "body": f"Unable to generate interpretation for {topic} at this time.",
            "agent_source": agent_name,
        }


# ── Tool 4: Calculate Vimshottari Dasha ──────────────────────────────────────

# Dasha sequence and durations (years) per planet
_DASHA_SEQUENCE = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]
_DASHA_YEARS = {"Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10, "Mars": 7,
                "Rahu": 18, "Jupiter": 16, "Saturn": 19, "Mercury": 17}

# Nakshatra to ruling planet mapping (each nakshatra lord repeats in groups of 9)
_NAKSHATRA_LORDS = [
    "Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury",
    "Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury",
    "Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury",
]


@tool
def calculate_vimshottari_dasha(
    birth_date: str,
    moon_nakshatra: str,
    moon_degree_in_nakshatra: float = 0.0,
) -> dict:
    """Calculate Vimshottari Dasha planetary periods from birth date and moon nakshatra.

    Returns current dasha, next dasha, and a list of upcoming periods with dates.
    Returns {"error": reason} if inputs are invalid.
    """
    try:
        from datetime import date, timedelta

        nakshatra_name = moon_nakshatra.strip()
        if nakshatra_name not in NAKSHATRAS:
            # Try case-insensitive match
            matches = [n for n in NAKSHATRAS if n.lower() == nakshatra_name.lower()]
            if not matches:
                return {"success": False, "error": f"Unknown nakshatra: {nakshatra_name}"}
            nakshatra_name = matches[0]

        nak_index = NAKSHATRAS.index(nakshatra_name)
        ruling_planet = _NAKSHATRA_LORDS[nak_index]
        total_nak_degrees = 360 / 27  # ~13.33° per nakshatra

        # Fraction of the nakshatra already elapsed
        fraction_elapsed = min(max(moon_degree_in_nakshatra / total_nak_degrees, 0.0), 1.0)
        remaining_fraction = 1.0 - fraction_elapsed

        year, month, day = map(int, birth_date.split("-"))
        birth = date(year, month, day)

        # Starting dasha planet and remaining years at birth
        start_planet_idx = _DASHA_SEQUENCE.index(ruling_planet)
        remaining_years = _DASHA_YEARS[ruling_planet] * remaining_fraction

        periods: list[DashaPeriod] = []
        current_date = birth
        today = date.today()

        current_planet_idx = start_planet_idx
        years_left = remaining_years

        for _ in range(9):  # up to 9 consecutive dashas
            planet = _DASHA_SEQUENCE[current_planet_idx % 9]
            duration_days = int(years_left * 365.25)
            end_date = current_date + timedelta(days=duration_days)

            is_current = current_date <= today < end_date
            periods.append(DashaPeriod(
                planet=planet,
                start_date=current_date.isoformat(),
                end_date=end_date.isoformat(),
                is_current=is_current,
            ))

            if end_date > today + timedelta(days=365 * 30):
                break  # stop after 30 years into the future

            current_date = end_date
            current_planet_idx = (current_planet_idx + 1) % 9
            years_left = _DASHA_YEARS[_DASHA_SEQUENCE[current_planet_idx % 9]]

        current_dasha = next((p for p in periods if p.is_current), periods[0] if periods else None)

        return {
            "success": True,
            "ruling_planet_at_birth": ruling_planet,
            "current_dasha": current_dasha.model_dump() if current_dasha else None,
            "periods": [p.model_dump() for p in periods],
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "periods": []}


# ── Tool 5: Flag for human review ────────────────────────────────────────────

@tool
def flag_for_human_review(reason: str, context: str, step: str = "unknown") -> dict:
    """Signal that the pipeline needs human input before proceeding.

    This tool always succeeds. It sets a flag that the orchestrator reads
    to pause the graph and surface a question to the user.

    reason: why human input is needed
    context: relevant data to show the human
    step: which orchestrator step triggered this
    """
    return {
        "success": True,
        "needs_human": True,
        "reason": reason,
        "context": context,
        "step": step,
        "question": f"The agent needs your input: {reason}",
    }
