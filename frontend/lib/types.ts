export type BirthInput = {
  name: string;
  birth_date: string;
  birth_time: string;
  birth_city: string;
  birth_state: string;
  birth_country: string;
  timezone: string;
};

export type PlanetPlacement = {
  body: string;
  degree: number;
  sign: string;
  house: number;
};

export type ChartResponse = {
  profile: Record<string, string>;
  placements: PlanetPlacement[];
  house_labels: string[];
};

export type ReadingSection = {
  heading: string;
  body: string;
};

export type ReadingResponse = {
  headline: string;
  summary: string;
  sections: ReadingSection[];
  source_passages: string[];
  prompt?: string | null;
};

export type AnalyzeResponse = {
  chart: ChartResponse;
  reading: ReadingResponse;
};

export type ChatRequest = {
  message: string;
  session_id: string;
  chart_summary: string | null;
};

export type ChatResponse = {
  answer: string;
  sources: string[];
  session_id: string;
};

export type EvalRow = {
  question: string;
  answer: string;
  relevance: number | null;
  quality: number | null;
};

export type EvalResponse = {
  status: 'ok' | 'no_data' | 'error';
  message?: string;
  examples_count?: number;
  dataset_url?: string;
  scores?: { relevance: number; quality: number };
  rows?: EvalRow[];
};

// ── Multi-agent prediction types ─────────────────────────────────────────────

export type DashaPeriod = {
  planet: string;
  start_date: string;
  end_date: string;
  is_current: boolean;
  sub_periods: string[] | null;
};

export type ReportSection = {
  heading: string;
  body: string;
  agent_source: 'chart_analyst' | 'nakshatra_retriever' | 'synthesizer';
  confidence: number;
  low_confidence: boolean;
};

export type AgentAttribution = {
  chart_analyst: string;
  nakshatra_retriever: string;
  synthesizer: string;
  human_input: string | null;
};

export type PredictionReport = {
  session_id: string;
  person_name: string;
  executive_summary: string;
  sections: ReportSection[];
  dasha_periods: DashaPeriod[];
  agent_attribution: AgentAttribution;
  low_confidence_count: number;
  human_input_used: boolean;
  step_history: string[];
};

export type HandoffQuestion = {
  session_id: string;
  question: string;
  context: string;
  step: string;
};

export type HandoffResponse = {
  session_id: string;
  answer: string;
};

export type PredictResponse = PredictionReport | HandoffQuestion;

export function isHandoffQuestion(r: PredictResponse): r is HandoffQuestion {
  return 'question' in r && 'step' in r;
}
