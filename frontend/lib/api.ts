import type {
  AnalyzeResponse,
  BirthInput,
  ChartResponse,
  ChatRequest,
  ChatResponse,
  EvalResponse,
  HandoffQuestion,
  HandoffResponse,
  PredictResponse,
  ReadingResponse,
} from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://127.0.0.1:8000';

type BackendBirthPayload = {
  name: string;
  birth_date: string;
  birth_time: string;
  birth_place: string;
  timezone: string;
};

function toBirthPayload(input: BirthInput): BackendBirthPayload {
  const { birth_city, birth_state, birth_country, ...rest } = input;
  return {
    ...rest,
    birth_place: [birth_city, birth_state, birth_country].filter(Boolean).join(', '),
  };
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Request failed (${response.status}): ${text}`);
  }

  return response.json() as Promise<T>;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Request failed (${response.status}): ${text}`);
  }

  return response.json() as Promise<T>;
}

// ── Existing API functions (unchanged) ───────────────────────────────────────

export function getChart(input: BirthInput) {
  return postJson<ChartResponse>('/api/chart', toBirthPayload(input));
}

export function getReading(input: BirthInput) {
  return postJson<ReadingResponse>('/api/reading', toBirthPayload(input));
}

export function analyze(input: BirthInput) {
  return postJson<AnalyzeResponse>('/api/analyze', toBirthPayload(input));
}

export function chatMessage(req: ChatRequest) {
  return postJson<ChatResponse>('/api/chat', req);
}

export function runEval(sessionId: string) {
  return postJson<EvalResponse>('/api/evaluate', { session_id: sessionId });
}

// ── Multi-agent prediction API functions ─────────────────────────────────────

/** Run the full multi-agent prediction pipeline.
 *  Returns PredictionReport on success, HandoffQuestion if human input is needed. */
export function predict(input: BirthInput) {
  return postJson<PredictResponse>('/api/predict', toBirthPayload(input));
}

/** Submit a human answer to resume a paused orchestrator graph. */
export function respondToHandoff(payload: HandoffResponse) {
  return postJson<PredictResponse>('/api/predict/respond', payload);
}

/** Poll for a pending handoff question. Returns HandoffQuestion or {pending: false}. */
export function pollHandoffStatus(sessionId: string) {
  return getJson<HandoffQuestion | { pending: false; session_id: string }>(
    `/api/predict/status/${sessionId}`
  );
}
