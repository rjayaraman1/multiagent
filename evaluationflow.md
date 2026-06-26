# Evaluation Flow — Current Implementation

## Overview

The evaluation runs in two distinct phases:
- **Phase 1** — happens continuously as the user chats with the agent
- **Phase 2** — happens on-demand when the user clicks Evaluate

---

## Phase 1: User Chats (Building up chat_log.csv)

### Step 1 — User types a question in the frontend

The frontend calls `POST /api/chat` with:
```json
{ "message": "Lord of this Raashi", "session_id": "abc-123", "chart_summary": "Moon Sign: Leo; ..." }
```

### Step 2 — RAG pipeline runs (`graph.py`)

Three nodes execute in sequence:
```
classify()  →  retrieve()  →  generate_answer()
   ↓               ↓                ↓
"raashi"    pulls 4 docs      gpt-4o-mini writes
            from Chroma       the answer
```

### Step 3 — Answer logged to CSV (`evaluate.py → log_chat()`)

`main.py` calls `log_chat()` immediately after getting the answer:
```
chat_log.csv gets one new row:
timestamp        | session_id | question           | answer              | sources
2026-06-25 10:00 | abc-123    | Lord of this Raashi| The lord of Leo ... | Raashi_Corpus.md
```

This repeats for every question the user asks. The CSV grows with every chat turn.

---

## Phase 2: User Triggers Evaluation

### Step 4 — User clicks Evaluate in the UI

Frontend calls `POST /api/evaluate` → `main.py` → `run_langsmith_eval()`

### Step 5 — CSV is read

All rows from `chat_log.csv` are loaded into memory (or filtered by `session_id`).

### Step 6 — LangSmith dataset recreated

```python
# Delete old dataset if exists, create fresh one
client.delete_dataset(...)
dataset = client.create_dataset("vedic-astro-chat-evals")

# Each CSV row becomes one Example in LangSmith
client.create_example(
    inputs={"question": "Lord of this Raashi", "answer": "The lord of Leo..."},
    outputs={}
)
```

### Step 7 — Experiment created via `ls_evaluate`

```python
exp = ls_evaluate(target, data="vedic-astro-chat-evals", evaluators=[], ...)
```
This creates a named experiment (`vedic-astro-eval-xxxx`) in LangSmith and produces
one `run` object per example. The `target()` function just echoes the stored answer —
no agent is called here.

### Step 8 — Judge LLM scores each run (×2 per row)

For every result in `exp`:
```python
rel_score  = _score(llm, question, answer, relevance_criterion)
qual_score = _score(llm, question, answer, quality_criterion)
```
gpt-4o-mini reads the Q&A and outputs a digit 1–5. `_score()` normalizes it to 0.0–1.0.

### Step 9 — Scores logged directly to LangSmith

```python
client.create_feedback(run_id=run_id, key="relevance", score=0.75)
client.create_feedback(run_id=run_id, key="quality",   score=1.00)
```

### Step 10 — Aggregates returned to frontend

```json
{
  "scores": { "relevance": 85, "quality": 77 },
  "rows": [{ "question": "...", "relevance": 0.75, "quality": 1.0 }, ...]
}
```

---

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                     PHASE 1 — CHAT  (repeats per question)          │
└─────────────────────────────────────────────────────────────────────┘

  User (Frontend)
       │
       │  POST /api/chat  { message, session_id, chart_summary }
       ▼
  main.py → _compiled_graph.invoke()
       │
       │         graph.py (RAG Pipeline)
       │    ┌─────────────────────────┐
       │    │  classify()             │
       │    │  "nakshatra" /          │
       │    │  "raashi" /             │
       │    │  "chart_specific" /     │
       │    │  "general"              │
       │    └──────────┬──────────────┘
       │               │
       │    ┌──────────▼──────────────┐
       │    │  retrieve()             │
       │    │  Chroma vector search   │
       │    │  (filtered by type)     │
       │    └──────────┬──────────────┘
       │               │
       │    ┌──────────▼──────────────┐
       │    │  generate_answer()      │
       │    │  gpt-4o-mini writes     │
       │    │  grounded answer        │
       │    └──────────┬──────────────┘
       │               │ answer + sources
       ▼               ▼
  log_chat() ──────────────────────────────► chat_log.csv
                                              (appends one row)
       │
       ▼
  ChatResponse → Frontend


┌─────────────────────────────────────────────────────────────────────┐
│                  PHASE 2 — EVALUATION  (on-demand)                  │
└─────────────────────────────────────────────────────────────────────┘

  User clicks "Evaluate"
       │
       │  POST /api/evaluate
       ▼
  run_langsmith_eval()
       │
       ├─① read_log()
       │       └── loads all rows from chat_log.csv
       │
       ├─② Recreate LangSmith Dataset
       │       └── delete old → create "vedic-astro-chat-evals"
       │       └── create_example() per CSV row
       │               inputs: { question, answer }
       │               outputs: {}
       │
       ├─③ ls_evaluate()  [evaluators=[]]
       │       └── creates experiment "vedic-astro-eval-xxxx"
       │       └── runs target() per example  →  run objects
       │               (target just echoes answer — no agent called)
       │
       ├─④ For each run result:
       │       │
       │       ├── _score(llm, q, a, relevance_criterion)
       │       │       └── gpt-4o-mini rates 1–5
       │       │       └── normalizes → 0.0 / 0.25 / 0.5 / 0.75 / 1.0
       │       │
       │       ├── _score(llm, q, a, quality_criterion)
       │       │       └── gpt-4o-mini rates 1–5
       │       │       └── normalizes → 0.0 / 0.25 / 0.5 / 0.75 / 1.0
       │       │
       │       └── client.create_feedback()  ──────────────────────────►  LangSmith
       │               key="relevance"  score=0.75                         computes
       │               key="quality"    score=1.00                         p50 / p95
       │                                                                    per key
       ├─⑤ Compute local aggregates
       │       avg_relevance = mean(all_rel) × 100  →  85
       │       avg_quality   = mean(all_qual) × 100 →  77
       │
       └─⑥ Return to Frontend
               {
                 "scores": { "relevance": 85, "quality": 77 },
                 "rows":   [ { q, a, relevance, quality } × N ]
               }
```

---

## Key Design Notes

| Point | Detail |
|---|---|
| **Agent not re-invoked in Phase 2** | The stored answers from `chat_log.csv` are what get scored — not fresh agent responses |
| **Dataset is recreated every run** | Old dataset deleted and rebuilt fresh on each `/api/evaluate` call |
| **Judge LLM is separate** | `gpt-4o-mini` used only for scoring — separate from the chat LLM |
| **Latency p50/p95 = 0** | Expected — `target()` just echoes text instantly; score p50/p95 are in the feedback columns |
| **Score p50/p95 location** | In LangSmith UI → experiment → click the ↕ toggle on the `quality` or `relevance` column header |
| **Limitation** | Scores historical responses, not current agent state. CSV-based evaluation (running fresh agent per prompt) would be more reliable for regression testing |
