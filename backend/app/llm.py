from __future__ import annotations

import json
import os
from typing import List

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_openai import ChatOpenAI

from .astrology_engine import summarize_chart
from .schemas import ChartResponse, ReadingResponse, ReadingSection


_READING_PROMPT = ChatPromptTemplate.from_template(
    """You are a Vedic astrology interpreter. Generate a structured reading from the chart summary and context passages below.

Return ONLY a valid JSON object — no markdown fences, no extra text:
{{
  "headline": "A short, compelling headline about this chart (max 12 words)",
  "summary": "2–3 sentence overview of the key themes in this chart",
  "sections": [
    {{"heading": "Personality and Presentation", "body": "Interpretation based on ascendant and 1st-house planets"}},
    {{"heading": "Emotional Patterns", "body": "Interpretation based on Moon sign and placement"}},
    {{"heading": "Life Direction", "body": "Interpretation based on Sun sign and key planetary themes"}}
  ]
}}

Chart summary:
{chart_summary}

Context passages from Vedic texts:
{passages}

JSON:"""
)


def _llm_reading(chart: ChartResponse, passages: List[str]) -> ReadingResponse:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.4)
    chain = _READING_PROMPT | llm | JsonOutputParser()

    try:
        data = chain.invoke({
            "chart_summary": summarize_chart(chart),
            "passages": "\n---\n".join(passages) if passages else "No passages available.",
        })
        return ReadingResponse(
            headline=data["headline"],
            summary=data["summary"],
            sections=[
                ReadingSection(heading=s["heading"], body=s["body"])
                for s in data["sections"]
            ],
            source_passages=passages,
        )
    except Exception as exc:
        print(f"[llm] LLM reading failed ({exc}), using fallback")
        return _fallback_reading(chart, passages)


def _fallback_reading(chart: ChartResponse, passages: List[str]) -> ReadingResponse:
    asc = chart.profile.get("ascendant_sign", "Unknown")
    moon = chart.profile.get("moon_sign", "Unknown")
    sun = chart.profile.get("sun_sign", "Unknown")
    placements = chart.placements[:5]

    return ReadingResponse(
        headline="Starter horoscope reading",
        summary=(
            f"Deterministic reading generated without an LLM. "
            f"Ascendant={asc}, Moon={moon}, Sun={sun}."
        ),
        sections=[
            ReadingSection(
                heading="Personality and Presentation",
                body=(
                    f"Your ascendant sign is {asc}. This starter reading suggests a style shaped "
                    f"by the first house and the planets placed close to it."
                ),
            ),
            ReadingSection(
                heading="Emotional Patterns",
                body=(
                    f"The Moon sign is {moon}, used as a proxy for emotional tone in Vedic interpretation."
                ),
            ),
            ReadingSection(
                heading="Life Direction",
                body=(
                    f"The Sun sign is {sun}. Key anchor points in this chart: "
                    f"{', '.join(p.body for p in placements)}."
                ),
            ),
        ],
        source_passages=passages,
        prompt=(
            f"Chart summary: {summarize_chart(chart)}\nSource passages: {passages}"
        ),
    )


def generate_reading(chart: ChartResponse, passages: List[str]) -> ReadingResponse:
    if os.getenv("OPENAI_API_KEY"):
        return _llm_reading(chart, passages)
    return _fallback_reading(chart, passages)
