# Evaluate Logic — LLM-as-a-Judge with LangSmith

## Files Changed

| File | What changed |
|---|---|
| `backend/app/evaluate.py` | Scoring prompt: Y/N → 1–5 rubric; `_score()` returns float; removed evaluator protocol; scores logged via `client.create_feedback()` directly |
| `backend/app/schemas.py` | `EvalRow.relevance` and `EvalRow.quality` changed from `Optional[int]` to `Optional[float]` |

---

## Change 1: Binary → Continuous Scoring

### Before (binary — caused p50=0, p90=0)
```python
# Prompt asked: "Y or N"
# _score() returned: 0 or 1
# Distribution: [0, 0, 1, 0, 1] → p50=0, p90=0
```

### After (continuous 1–5 rubric → normalized 0.0–1.0)
```python
# Prompt asks: "Rate 1–5"
# _score() returns: 0.0 / 0.25 / 0.50 / 0.75 / 1.0
# Distribution: [0.25, 0.5, 0.75, 1.0, 0.5] → p50=0.5, p90=0.85
```

### Scoring prompt (evaluate.py)
```
Score the response on a scale of 1 to 5:
1 - Completely fails the criterion
2 - Mostly fails, minor relevant content
3 - Partially meets the criterion
4 - Mostly meets the criterion
5 - Fully meets the criterion

Reply with a single digit (1, 2, 3, 4, or 5). Nothing else.
```

### Normalization formula (_score() in evaluate.py)
| LLM says | Normalized score | Formula |
|---|---|---|
| 1 | 0.00 | (1-1)/4 |
| 2 | 0.25 | (2-1)/4 |
| 3 | 0.50 | (3-1)/4 |
| 4 | 0.75 | (4-1)/4 |
| 5 | 1.00 | (5-1)/4 |

---

## Change 2: Schema Fix (schemas.py)

`EvalRow` fields changed from `int` to `float` to accept normalized scores:

```python
# Before — caused 500 Internal Server Error (Pydantic rejected 0.75 as int)
relevance: Optional[int] = None
quality: Optional[int] = None

# After
relevance: Optional[float] = None
quality: Optional[float] = None
```

---

## Change 3: Direct Feedback Logging via client.create_feedback()

### Root cause of p50=null / p99=0 in LangSmith UI (after signature fix)

Even with the correct evaluator signature, LangSmith 0.8.x internally calls
`_log_evaluation_feedback()` to push scores to LangSmith (see `_runner.py:1681–1685`).
This upload only runs if `_upload_results` is True **and** the internal feedback logger
succeeds. Any silent failure drops the score entirely.

The local iteration loop still saw correct non-zero scores (from the in-memory
`eval_results` dict), which is why the local curl response looked right — but LangSmith
received nothing, so p50/p99 stayed null/0.

### Before (evaluator protocol — silently dropped in LangSmith 0.8.x)
```python
# Scores computed inside evaluator wrappers and uploaded via internal protocol
exp = ls_evaluate(
    target,
    data=DATASET_NAME,
    evaluators=[eval_relevance, eval_quality],  # ← scores silently dropped
    ...
)

for result in exp:
    # reads from in-memory eval_results — looks correct locally
    for er in _get(_get(result, "evaluation_results"), "results") or []:
        score = _get(er, "score")   # ← non-zero locally, but 0/null in LangSmith
```

### After (direct feedback — guaranteed to appear in LangSmith)
```python
# ls_evaluate creates the experiment framework only — no evaluators
exp = ls_evaluate(
    target,
    data=DATASET_NAME,
    evaluators=[],   # ← empty
    ...
)

for result in exp:
    run_id = _get(_get(result, "run"), "id")
    q = inputs.get("question", "")
    a = inputs.get("answer", "")

    rel_score  = _score(llm, q, a, _rel_criterion)
    qual_score = _score(llm, q, a, _qual_criterion)

    # Direct API call — bypasses evaluator protocol entirely
    client.create_feedback(run_id=run_id, key="relevance", score=rel_score)
    client.create_feedback(run_id=run_id, key="quality",   score=qual_score)
```

### Why create_feedback() is the reliable path
`client.create_feedback()` is the lowest-level LangSmith API call. It does not
go through any evaluator wrapping, version-specific protocol, or internal upload
flag. Whatever score you pass is what LangSmith stores — always visible in p50/p90/p99.

---

## Step-by-Step Evaluation Flow (Final Working Version)

### Step 1: User Chats with the Agent

User sends a question via `/api/chat`. The RAG pipeline answers it and `log_chat()`
appends the Q&A pair to `backend/chat_log.csv`:

```
timestamp | session_id | question                        | answer              | sources
----------|------------|---------------------------------|---------------------|--------
2026-06-24| abc-123    | Lord of this Raashi             | The lord of your... | Raashi_Corpus.md
2026-06-24| abc-123    | Key traits of this star         | Rohini nakshatra... | Nakshatra_Corpus.md
```

---

### Step 2: User Triggers Evaluation

User calls `/api/evaluate`. This calls `run_langsmith_eval()` in `backend/app/evaluate.py`.

---

### Step 3: Q&A Pairs Uploaded to LangSmith Dataset

Every row from the CSV is pushed as an **example** into a fresh LangSmith dataset
named `"vedic-astro-chat-evals"`:

```python
client.create_example(
    inputs={"question": row["question"], "answer": row["answer"]},
    outputs={},
    dataset_id=dataset.id,
)
```

---

### Step 4: Experiment Created via ls_evaluate (no evaluators)

`ls_evaluate` is called with an empty evaluator list. Its only job here is to
create a named experiment and produce run objects linked to each dataset example:

```python
exp = ls_evaluate(target, data=DATASET_NAME, evaluators=[], ...)
```

---

### Step 5: The Judge LLM Scores Each Example + Feedback Logged Directly

For every result in the experiment, `_score()` is called twice (relevance + quality)
and each score is logged to LangSmith via `client.create_feedback()`:

```
Question: Lord of this Raashi
Answer:   The lord of your moon sign Rishabam (Taurus) is Venus...

  → gpt-4o-mini judges RELEVANCE → "4" → (4-1)/4 = 0.75
  → client.create_feedback(run_id, key="relevance", score=0.75)  ✓ stored in LangSmith

  → gpt-4o-mini judges QUALITY → "3" → (3-1)/4 = 0.50
  → client.create_feedback(run_id, key="quality", score=0.50)    ✓ stored in LangSmith
```

---

### Step 6: LangSmith Computes p50 / p90 / p99

LangSmith aggregates all logged scores per feedback key across all examples:

```
Relevance scores: [0.75, 1.0, 0.5, 0.75, 0.25, 1.0, 0.75]
  → p50 = 0.75   (median — 50% of responses score at or below this)
  → p90 = 1.0    (90th percentile)
  → p99 = 1.0    (99th percentile)

Quality scores:   [0.5, 0.75, 0.25, 0.5, 0.5, 0.75, 0.5]
  → p50 = 0.5
  → p90 = 0.75
  → p99 = 0.75
```

---

### Step 7: Results Returned to App

`run_langsmith_eval()` returns per-row scores + aggregate averages to the frontend.
The full experiment with p50/p90/p99 is visible in LangSmith UI.

**To view in LangSmith:**
- Go to your dataset → **Experiments** tab
- Sort by date → open the latest `vedic-astro-eval-...` experiment
- Click into **Feedback** section → see score distribution per criterion

---

## Complete Picture (Final)

```
chat_log.csv
    │
    │  (one row per Q&A turn)
    ▼
LangSmith Dataset  ("vedic-astro-chat-evals")
    │
    │  ls_evaluate() creates experiment + runs (no evaluators)
    │
    │  for each run:
    ├──► gpt-4o-mini scores RELEVANCE (1–5) → normalized 0.0–1.0
    │    └─► client.create_feedback(run_id, "relevance", score)  ──► LangSmith ✓
    │
    └──► gpt-4o-mini scores QUALITY (1–5) → normalized 0.0–1.0
         └─► client.create_feedback(run_id, "quality", score)    ──► LangSmith ✓
                                    │
                                    ▼
                         LangSmith experiment
                         p50 / p90 / p99 now populated ✓
```

---

## Why LLM-as-a-Judge Works Here

| Aspect | Detail |
|---|---|
| **No ground truth needed** | You don't have pre-written "correct" answers — the judge evaluates quality directly |
| **Scalable** | Runs automatically on every Q&A pair without human review |
| **Two criteria** | Relevance (is it on-topic?) and Quality (is it accurate and helpful?) are evaluated independently |
| **Weakness** | The judge itself can be wrong — gpt-4o-mini may score a hallucinated Vedic fact as "5" if it sounds confident. For higher-stakes evals, add a reference corpus check or use a stronger judge like `gpt-4o` |

---

## Debugging History (for reference)

| Symptom | Root Cause | Fix applied |
|---|---|---|
| `p50=0, p90=0` | Binary Y/N scoring — only 0 or 1 possible | Changed to 1–5 rubric, normalized to float |
| `500 Internal Server Error` | `EvalRow.relevance` typed as `int`, Pydantic rejected float `0.75` | Changed to `Optional[float]` in schemas.py |
| `p50=null, p90=0` (1st attempt) | Old `(run, example)` signature — `example` was empty `{}` in 0.8.x | Updated to `(inputs, outputs, reference_outputs)` |
| `p50=null, p99=0` (2nd attempt) | `_log_evaluation_feedback()` in 0.8.x internally dropped scores silently | Removed evaluators from `ls_evaluate`; log via `client.create_feedback()` directly |
