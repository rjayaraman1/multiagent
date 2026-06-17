'use client';

import dynamic from 'next/dynamic';
import { Fragment, useMemo, useRef, useState } from 'react';
import { analyze } from '@/lib/api';
import type { AnalyzeResponse, BirthInput, HandoffQuestion, PredictionReport } from '@/lib/types';
import { BirthForm } from './components/BirthForm';
import { ChatPanel } from './components/ChatPanel';
import { EvalPanel } from './components/EvalPanel';
import { HumanHandoffPanel } from './components/HumanHandoffPanel';
import { PredictionPanel } from './components/PredictionPanel';

const HoroscopeWheel = dynamic(
  () => import('./components/HoroscopeWheel').then((mod) => mod.HoroscopeWheel),
  {
    ssr: false,
    loading: () => (
      <div className="chart-wrap">
        <p style={{ color: '#94a3b8' }}>Loading chart…</p>
      </div>
    ),
  }
);

const defaultInput: BirthInput = {
  name: '',
  birth_date: '',
  birth_time: '',
  birth_city: '',
  birth_state: '',
  birth_country: '',
  timezone: '',
};

function makeSessionId() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

const STEPS = [
  'Enter birth details',
  'Generate chart',
  'Ask question',
  'Full Prediction',
  'Evaluate',
];

function WorkflowStepper({ hasChart, loading }: { hasChart: boolean; loading: boolean }) {
  // Determine which step is currently active (1-indexed)
  const active = loading ? 2 : !hasChart ? 1 : 3;

  return (
    <div className="stepper">
      {STEPS.map((label, i) => {
        const stepNum = i + 1;
        const isDone = stepNum < active;
        const isActive = stepNum === active;
        return (
          <Fragment key={label}>
            <div
              className={[
                'stepper-step',
                isDone ? 'stepper-step--done' : '',
                isActive ? 'stepper-step--active' : '',
              ]
                .filter(Boolean)
                .join(' ')}
            >
              <span className="stepper-num">{isDone ? '✓' : stepNum}</span>
              <span className="stepper-label">{label}</span>
            </div>
            {i < STEPS.length - 1 && (
              <span className="stepper-arrow" aria-hidden>
                →
              </span>
            )}
          </Fragment>
        );
      })}
    </div>
  );
}

export default function HomePage() {
  const sessionId = useRef(makeSessionId()).current;

  const [form, setForm] = useState<BirthInput>(defaultInput);
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [, setPredictionReport] = useState<PredictionReport | null>(null);
  const [pendingHandoff, setPendingHandoff] = useState<HandoffQuestion | null>(null);

  async function handleSubmit() {
    try {
      setLoading(true);
      setError(null);
      const response = await analyze(form);
      setResult(response);
      setPredictionReport(null);
      const detectedOffset = response.chart.profile.detected_utc_offset;
      if (detectedOffset) {
        setForm((prev) => ({ ...prev, timezone: detectedOffset }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong');
    } finally {
      setLoading(false);
    }
  }

  const profileBadges = useMemo(() => {
    if (!result) return [] as string[];
    const badges = [
      `Ascendant: ${result.chart.profile.ascendant_sign}`,
      `Moon: ${result.chart.profile.moon_sign}`,
      `Sun: ${result.chart.profile.sun_sign}`,
    ];
    if (result.chart.profile.detected_timezone) {
      badges.push(`Timezone: ${result.chart.profile.detected_timezone}`);
    }
    return badges;
  }, [result]);

  return (
    <main className="page">

      {/* App header */}
      <div className="app-header">
        <h1 className="app-title">Multi-Agent-VedicAstro-RAG-Pipeline</h1>
        <span className="app-subtitle">LangGraph · LangChain · OpenAI</span>
      </div>

      {/* Workflow stepper */}
      <WorkflowStepper hasChart={!!result} loading={loading} />

      {/* Main two-column layout */}
      <div className="main-grid">

        {/* LEFT column: birth form + horoscope wheel */}
        <div className="left-col">
          <div className="panel">
            <div className="agent-label">Birthchart analyst agent</div>
            <p style={{ fontSize: 13, marginBottom: 12 }}>
              Enter birth details to generate a chart, then use the RAG chat or run the
              full multi-agent prediction pipeline.
            </p>

            <BirthForm value={form} onChange={setForm} onSubmit={handleSubmit} loading={loading} />

            {error && (
              <div
                className="reading-card"
                style={{ marginTop: 12, borderColor: '#fecaca', background: '#fff1f2' }}
              >
                <strong style={{ fontSize: 13 }}>Backend error</strong>
                <p style={{ marginBottom: 0, fontSize: 13 }}>{error}</p>
              </div>
            )}

            {profileBadges.length > 0 && (
              <div className="badge-row">
                {profileBadges.map((badge) => (
                  <span className="badge" key={badge}>{badge}</span>
                ))}
              </div>
            )}

            <div className="footer-note">
              Chart engine: PyEphem + Lahiri ayanamsha · Multi-agent: LangGraph + 3 specialized agents
            </div>
          </div>

          {/* South Indian Rasi chart */}
          <div>
            <div className="agent-label">Chart analyst agent</div>
            <HoroscopeWheel chart={result?.chart ?? null} />
          </div>
        </div>

        {/* RIGHT column: live RAG chat */}
        <ChatPanel chart={result?.chart ?? null} sessionId={sessionId} />

      </div>

      {/* Multi-agent prediction panel */}
      <PredictionPanel
        birthInput={result ? form : null}
        onHandoff={(hq) => setPendingHandoff(hq)}
      />

      {/* LangSmith evaluation panel */}
      <EvalPanel sessionId={sessionId} />

      {/* Human handoff modal */}
      {pendingHandoff && (
        <HumanHandoffPanel
          handoff={pendingHandoff}
          onResolved={(report) => {
            setPendingHandoff(null);
            setPredictionReport(report);
          }}
          onNextHandoff={(hq) => setPendingHandoff(hq)}
          onDismiss={() => setPendingHandoff(null)}
        />
      )}
    </main>
  );
}
