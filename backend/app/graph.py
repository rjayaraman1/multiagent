from __future__ import annotations

import os
import re
from typing import Annotated, Any, List, Optional

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

load_dotenv()

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_APP_DIR)          # backend/
CHROMA_DIR = os.path.join(BASE_DIR, ".chroma")
COLLECTION_NAME = "vedic_astrology"

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class AstrologyState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    query: str
    chart_context: str        # user's chart summary; empty string when no chart generated yet
    query_type: str           # nakshatra | raashi | chart_specific | general
    retrieved_docs: List[Any]
    sources: List[str]
    answer: str
    turn: int


# ---------------------------------------------------------------------------
# Shared resources (lazy-initialised so imports don't fail before .env loads)
# ---------------------------------------------------------------------------

_llm: Optional[ChatOpenAI] = None
_vectorstore: Optional[Chroma] = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    return _llm


def _get_vectorstore() -> Chroma:
    global _vectorstore
    if _vectorstore is None:
        embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        _vectorstore = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=embeddings,
            persist_directory=CHROMA_DIR,
        )
    return _vectorstore


# ---------------------------------------------------------------------------
# Classifier vocabulary
# ---------------------------------------------------------------------------

_NAKSHATRA_NAMES = (
    "ashvini, bharani, krittika, rohini, mrigashira, ardra, punarvasu, pushya, ashlesha, "
    "magha, purva phalguni, uttara phalguni, hasta, chitra, swati, vishakha, anuradha, "
    "jyeshtha, mula, purva ashadha, uttara ashadha, shravana, dhanishtha, shatabhisha, "
    "purva bhadrapada, uttara bhadrapada, revati"
)

_RAASHI_NAMES = (
    "mesham, mesh, aries, rishabam, vrishabha, taurus, mithunam, mithuna, gemini, "
    "kadakam, karka, cancer, simham, simha, leo, kanni, kanya, virgo, thulam, tula, libra, "
    "vrishchikam, vrishchika, scorpio, dhanusu, dhanur, sagittarius, makaram, makara, "
    "capricorn, kumbam, kumba, aquarius, meenam, meena, pisces"
)

_CHART_TERMS = (
    "my moon, my sun, my ascendant, my lagna, my mars, my jupiter, my venus, my saturn, "
    "my mercury, my rahu, my ketu, my chart, my house, my sign, my placement, my rising"
)


# ---------------------------------------------------------------------------
# Node helpers
# ---------------------------------------------------------------------------

def _extract_chart_field(chart_context: str, label: str) -> str:
    """Pull a single field value out of the semicolon-delimited chart_context string."""
    match = re.search(rf"{re.escape(label)}:\s*([^;]+)", chart_context)
    return match.group(1).strip() if match else ""


def _format_history(messages: List[BaseMessage], max_turns: int = 3) -> str:
    recent = messages[-(max_turns * 2):]
    lines = []
    for m in recent:
        role = "User" if isinstance(m, HumanMessage) else "Assistant"
        lines.append(f"{role}: {m.content}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

def classify(state: AstrologyState) -> dict:
    """Classify query as nakshatra | raashi | chart_specific | general."""
    has_chart = bool(state.get("chart_context", "").strip())
    history = _format_history(state.get("messages", []))

    chart_specific_rule = (
        f"\n- If the user uses possessive or referential language about other chart topics "
        f"(my moon placement, my ascendant, my house, my planet, my lagna, my chart, etc.) "
        f"AND a chart is available → output: chart_specific"
        if has_chart else ""
    )

    raashi_generic_rule = (
        f"\n- If the user uses the word 'raashi' or 'moon sign' generically "
        f"(e.g. 'my raashi lord', 'raashi lord', 'my moon sign lord') "
        f"AND a chart is available → output: raashi"
        if has_chart else ""
    )

    nakshatra_generic_rule = (
        f"\n- If the user uses the word 'nakshatra', 'star', or 'birth star' generically "
        f"(e.g. 'my star lord', 'lord of my star', 'my nakshatra lord') "
        f"AND a chart is available → output: nakshatra"
        if has_chart else ""
    )

    prompt = f"""You are a Vedic astrology classifier. Output ONLY one word.

Known NAKSHATRA names (birth stars):
{_NAKSHATRA_NAMES}

Known RAASHI names (moon signs):
{_RAASHI_NAMES}

Rules (apply in order):
- If the user mentions any NAKSHATRA name → output: nakshatra
- If the user mentions any RAASHI name → output: raashi{raashi_generic_rule}{nakshatra_generic_rule}{chart_specific_rule}
- Otherwise → output: general

Conversation so far:
{history}

New query: {state["query"]}

Output ONLY one word (nakshatra / raashi{" / chart_specific" if has_chart else ""} / general):"""

    response = _get_llm().invoke(prompt)
    query_type = response.content.strip().lower().split()[0]
    valid = {"nakshatra", "raashi", "general", "chart_specific"}
    if query_type not in valid:
        query_type = "general"
    print(f"[graph] classified as: {query_type}")
    return {"query_type": query_type}


def retrieve(state: AstrologyState) -> dict:
    """Retrieve top-4 relevant chunks with optional source filter."""
    query_type = state["query_type"]
    query = state["query"]
    chart_context = state.get("chart_context", "")

    # Enrich queries with only the relevant chart field to avoid cross-contamination
    if query_type == "raashi" and chart_context:
        moon_sign = _extract_chart_field(chart_context, "Moon Sign (Raashi)")
        if moon_sign:
            query = f"{moon_sign} raashi {query}"
    elif query_type == "nakshatra" and chart_context:
        nakshatra = _extract_chart_field(chart_context, "Moon Nakshatra (birth star)")
        if nakshatra:
            query = f"{nakshatra} nakshatra {query}"
    elif query_type == "chart_specific" and chart_context:
        query = f"{chart_context} {query}"

    # Enrich very short follow-up queries with recent AI context
    messages = state.get("messages", [])
    if len(query.split()) <= 4 and messages:
        recent_ai = [m for m in messages if isinstance(m, AIMessage)]
        if recent_ai:
            query = f"{recent_ai[-1].content[:150]} {query}"

    source_filter = {"source": query_type} if query_type in ("nakshatra", "raashi") else None

    search_kwargs: dict = {"k": 4}
    if source_filter:
        search_kwargs["filter"] = source_filter

    vs = _get_vectorstore()
    retriever = vs.as_retriever(search_type="similarity", search_kwargs=search_kwargs)
    docs = retriever.invoke(query)

    # Fallback: retry without filter if too few results
    if len(docs) < 2 and source_filter:
        print(f"[graph] only {len(docs)} doc(s) with filter — retrying without")
        docs = vs.as_retriever(
            search_type="similarity", search_kwargs={"k": 4}
        ).invoke(query)

    print(f"[graph] retrieved {len(docs)} doc(s)")
    sources = list({doc.metadata.get("file_name", "unknown") for doc in docs})
    return {"retrieved_docs": docs, "sources": sources}


def generate_answer(state: AstrologyState) -> dict:
    """Generate a grounded answer from retrieved context and conversation history."""
    docs = state["retrieved_docs"]
    chart_context = state.get("chart_context", "")
    history = _format_history(state.get("messages", []))

    context_parts = []
    if chart_context and state["query_type"] in ("chart_specific", "nakshatra", "raashi"):
        context_parts.append(f"User's chart:\n{chart_context}")
    if docs:
        context_parts.append(
            "Relevant passages:\n" + "\n\n---\n\n".join(doc.page_content for doc in docs)
        )
    context = "\n\n".join(context_parts) if context_parts else "No context available."

    prompt = f"""You are a warm and knowledgeable Vedic astrology guide.
Answer the user's question using ONLY the context below.
If the answer is not in the context, say so honestly — do not guess.

Important Vedic astrology distinctions:
- Raashi (moon sign) = the zodiac sign where the Moon is placed — NOT the Ascendant.
- Lagna (Ascendant) = the rising sign at the time of birth — this is separate from Raashi.
- When the user asks about their "Raashi lord", use the Moon Sign (Raashi), not the Ascendant (Lagna).

Context:
{context}

Conversation history:
{history}

User's question: {state["query"]}

Give a clear, friendly, and informative answer."""

    response = _get_llm().invoke(prompt)
    answer = response.content.strip()

    return {
        "answer": answer,
        "turn": state.get("turn", 0) + 1,
        "messages": [AIMessage(content=answer)],
    }


# ---------------------------------------------------------------------------
# Build and compile
# ---------------------------------------------------------------------------

def build_graph():
    builder = StateGraph(AstrologyState)

    builder.add_node("classify", classify)
    builder.add_node("retrieve", retrieve)
    builder.add_node("answer", generate_answer)

    builder.add_edge(START, "classify")
    builder.add_edge("classify", "retrieve")
    builder.add_edge("retrieve", "answer")
    builder.add_edge("answer", END)

    return builder.compile(checkpointer=MemorySaver())
