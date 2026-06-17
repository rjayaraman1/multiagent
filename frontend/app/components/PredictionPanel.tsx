'use client';

import { useState } from 'react';
import { predict } from '@/lib/api';
import type { BirthInput, DashaPeriod, HandoffQuestion, PredictionReport, ReportSection } from '@/lib/types';
import { isHandoffQuestion } from '@/lib/types';

const AGENT_LABELS: Record<string, string> = {
  chart_analyst: 'Chart Analyst',
  nakshatra_retriever: 'Nakshatra Specialist',
  synthesizer: 'Prediction agent',
};

const AGENT_COLORS: Record<string, string> = {
  chart_analyst: '#2563eb',
  nakshatra_retriever: '#7c3aed',
  synthesizer: '#059669',
};

function AgentBadge({ source }: { source: string }) {
  const label = AGENT_LABELS[source] ?? source;
  const color = AGENT_COLORS[source] ?? '#64748b';
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 8px',
      borderRadius: 999,
      fontSize: 11,
      fontWeight: 700,
      color: 'white',
      background: color,
      marginBottom: 6,
    }}>
      {label}
    </span>
  );
}

function SectionCard({ section }: { section: ReportSection }) {
  return (
    <div className="reading-card" style={{
      borderLeft: `3px solid ${AGENT_COLORS[section.agent_source] ?? '#e2e8f0'}`,
      position: 'relative',
    }}>
      <AgentBadge source={section.agent_source} />
      {section.low_confidence && (
        <span style={{
          marginLeft: 6,
          padding: '2px 8px',
          borderRadius: 999,
          fontSize: 11,
          fontWeight: 600,
          color: '#92400e',
          background: '#fef3c7',
          border: '1px solid #fde68a',
        }}>
          ⚠ Limited data
        </span>
      )}
      <h3 style={{ margin: '6px 0 8px', fontSize: 15, color: '#1e293b' }}>{section.heading}</h3>
      <p style={{ margin: 0, fontSize: 14, lineHeight: 1.65, color: '#334155' }}>{section.body}</p>
    </div>
  );
}

function DashaTimeline({ periods }: { periods: DashaPeriod[] }) {
  if (!periods.length) return null;
  return (
    <div style={{ marginTop: 12 }}>
      <h3 style={{ fontSize: 14, fontWeight: 700, color: '#475569', marginBottom: 8 }}>
        Vimshottari Dasha Timeline
      </h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {periods.slice(0, 5).map((p, i) => (
          <div key={i} style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '6px 10px',
            borderRadius: 10,
            background: p.is_current ? '#eff6ff' : '#f8fafc',
            border: p.is_current ? '1px solid #93c5fd' : '1px solid #e2e8f0',
            fontSize: 13,
          }}>
            {p.is_current && <span style={{ color: '#2563eb', fontWeight: 700 }}>▶</span>}
            <strong style={{ minWidth: 80, color: p.is_current ? '#1d4ed8' : '#334155' }}>
              {p.planet}
            </strong>
            <span style={{ color: '#64748b' }}>{p.start_date} → {p.end_date}</span>
            {p.is_current && (
              <span style={{ marginLeft: 'auto', color: '#2563eb', fontWeight: 600, fontSize: 11 }}>
                CURRENT
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

interface Props {
  birthInput: BirthInput | null;
  onHandoff: (hq: HandoffQuestion) => void;
}

export function PredictionPanel({ birthInput, onHandoff }: Props) {
  const [report, setReport] = useState<PredictionReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate() {
    if (!birthInput) return;
    setLoading(true);
    setError(null);
    try {
      const response = await predict(birthInput);
      if (isHandoffQuestion(response)) {
        onHandoff(response);
      } else {
        setReport(response as PredictionReport);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Prediction failed');
    } finally {
      setLoading(false);
    }
  }

  async function handleExportPDF() {
    if (!report) return;
    const { default: jsPDF } = await import('jspdf');
    const doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' });

    doc.setFillColor(37, 99, 235);
    doc.rect(0, 0, 210, 28, 'F');
    doc.setTextColor(255, 255, 255);
    doc.setFontSize(16);
    doc.setFont('helvetica', 'bold');
    doc.text(`Vedic Prediction Report — ${report.person_name}`, 14, 18);

    let y = 36;
    doc.setTextColor(15, 23, 42);
    doc.setFontSize(11);
    doc.setFont('helvetica', 'normal');
    const summaryLines = doc.splitTextToSize(`Summary: ${report.executive_summary}`, 182);
    doc.text(summaryLines, 14, y);
    y += summaryLines.length * 6 + 6;

    if (report.human_input_used) {
      doc.setTextColor(124, 58, 237);
      doc.setFontSize(10);
      doc.text('* Human input was incorporated into this report.', 14, y);
      y += 8;
    }

    doc.setTextColor(15, 23, 42);
    for (const section of report.sections) {
      if (y > 260) { doc.addPage(); y = 14; }
      doc.setFontSize(12);
      doc.setFont('helvetica', 'bold');
      doc.text(section.heading, 14, y);
      y += 6;
      doc.setFontSize(10);
      doc.setFont('helvetica', 'normal');
      const lines = doc.splitTextToSize(section.body, 182);
      doc.text(lines, 14, y);
      y += lines.length * 5 + 6;
      const agentLabel = AGENT_LABELS[section.agent_source] ?? section.agent_source;
      doc.setFontSize(9);
      doc.setTextColor(100, 116, 139);
      doc.text(`Generated by: ${agentLabel}${section.low_confidence ? ' ⚠ limited data' : ''}`, 14, y);
      doc.setTextColor(15, 23, 42);
      y += 8;
    }

    doc.save(`vedic-prediction-${report.person_name.toLowerCase().replace(/\s+/g, '-')}-${Date.now()}.pdf`);
  }

  return (
    <div className="panel" style={{ marginTop: 24 }}>
      <div className="agent-label">Prediction agent</div>
      <h2 style={{ marginBottom: 4 }}>Full Prediction Report</h2>
      <p style={{ fontSize: 13, marginBottom: 16 }}>
        Runs 3 specialized agents: Chart Analyst → Nakshatra Specialist → Synthesizer.
        Includes dasha timeline, life area predictions, and agent attribution per section.
      </p>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
        <button
          className="btn"
          onClick={handleGenerate}
          disabled={loading || !birthInput}
          style={{ fontSize: 14 }}
        >
          {loading ? 'Running agents…' : '▶ Generate Full Prediction'}
        </button>
        {report && (
          <button
            onClick={handleExportPDF}
            style={{
              padding: '11px 20px',
              borderRadius: 12,
              border: '1px solid var(--border)',
              background: 'white',
              cursor: 'pointer',
              fontWeight: 700,
              fontSize: 14,
            }}
          >
            ⬇ Export PDF
          </button>
        )}
      </div>

      {error && (
        <div className="reading-card" style={{ borderColor: '#fecaca', background: '#fff1f2', marginBottom: 12 }}>
          <strong>Error</strong>
          <p style={{ margin: 0 }}>{error}</p>
        </div>
      )}

      {!birthInput && !report && (
        <div style={{ color: '#94a3b8', fontSize: 14, padding: '16px 0' }}>
          Generate a chart first using the birth form above, then click Generate Full Prediction.
        </div>
      )}

      {report && (
        <div>
          {/* Attribution legend */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
            {Object.entries(AGENT_LABELS).map(([key, label]) => (
              <span key={key} style={{
                padding: '4px 10px',
                borderRadius: 999,
                fontSize: 12,
                color: 'white',
                background: AGENT_COLORS[key],
              }}>
                {label}
              </span>
            ))}
            {report.human_input_used && (
              <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 12, background: '#fef3c7', color: '#92400e', border: '1px solid #fde68a' }}>
                Human Input Used
              </span>
            )}
          </div>

          {/* Executive summary */}
          <div className="reading-card" style={{ marginBottom: 12, background: '#f0f9ff', borderColor: '#bae6fd' }}>
            <h3 style={{ margin: '0 0 6px', fontSize: 15, color: '#0369a1' }}>Executive Summary</h3>
            <p style={{ margin: 0, fontSize: 14, lineHeight: 1.65 }}>{report.executive_summary}</p>
          </div>

          {/* Dasha timeline */}
          <DashaTimeline periods={report.dasha_periods} />

          {/* Sections */}
          <div className="section-stack" style={{ marginTop: 16 }}>
            {report.sections.map((s, i) => (
              <SectionCard key={i} section={s} />
            ))}
          </div>

          {/* Step history */}
          <details style={{ marginTop: 14 }}>
            <summary style={{ fontSize: 12, color: '#94a3b8', cursor: 'pointer' }}>
              Pipeline audit trail ({report.step_history.length} steps)
            </summary>
            <ol style={{ margin: '8px 0 0', paddingLeft: 20 }}>
              {report.step_history.map((s, i) => (
                <li key={i} style={{ fontSize: 11, color: '#64748b', marginBottom: 2 }}>{s}</li>
              ))}
            </ol>
          </details>
        </div>
      )}
    </div>
  );
}
