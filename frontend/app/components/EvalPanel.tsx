'use client';

import { useState } from 'react';
import { runEval } from '@/lib/api';
import type { EvalResponse, EvalRow } from '@/lib/types';

// ── PDF generation ────────────────────────────────────────────────────────────

async function downloadPDF(result: EvalResponse) {
  // Dynamic imports keep jspdf out of the initial bundle
  const { jsPDF } = await import('jspdf');
  const autoTable = (await import('jspdf-autotable')).default;

  const doc = new jsPDF({ orientation: 'landscape', unit: 'pt', format: 'a4' });
  const pageW = doc.internal.pageSize.getWidth();
  const generated = new Date().toLocaleString();

  // ── Title block ───────────────────────────────────────────────────────────
  doc.setFillColor(37, 99, 235);
  doc.rect(0, 0, pageW, 52, 'F');

  doc.setTextColor(255, 255, 255);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(18);
  doc.text('Vedic Astrology Agent — Evaluation Report', 40, 32);

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(9);
  doc.text(`Generated: ${generated}`, pageW - 40, 32, { align: 'right' });

  // ── Summary section ───────────────────────────────────────────────────────
  doc.setTextColor(15, 23, 42);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(12);
  doc.text('Evaluation Summary', 40, 80);

  doc.setDrawColor(219, 228, 238);
  doc.setLineWidth(0.5);
  doc.line(40, 85, pageW - 40, 85);

  const summaryY = 105;
  const cols = [
    { label: 'Interactions Evaluated', value: String(result.examples_count ?? 0) },
    { label: 'Relevance Score', value: `${result.scores?.relevance ?? 0}%` },
    { label: 'Quality Score', value: `${result.scores?.quality ?? 0}%` },
  ];

  const colW = (pageW - 80) / cols.length;
  cols.forEach(({ label, value }, i) => {
    const x = 40 + i * colW + colW / 2;

    // card background
    doc.setFillColor(248, 250, 252);
    doc.roundedRect(40 + i * colW + 4, summaryY - 18, colW - 8, 48, 6, 6, 'F');

    doc.setFont('helvetica', 'normal');
    doc.setFontSize(9);
    doc.setTextColor(100, 116, 139);
    doc.text(label, x, summaryY, { align: 'center' });

    doc.setFont('helvetica', 'bold');
    doc.setFontSize(20);
    doc.setTextColor(37, 99, 235);
    doc.text(value, x, summaryY + 22, { align: 'center' });
  });

  // LangSmith URL
  if (result.dataset_url) {
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(9);
    doc.setTextColor(100, 116, 139);
    doc.text(`LangSmith Dataset: ${result.dataset_url}`, 40, summaryY + 50);
  }

  // ── Results table ─────────────────────────────────────────────────────────
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(12);
  doc.setTextColor(15, 23, 42);
  doc.text('Detailed Results', 40, summaryY + 78);

  const tableRows = (result.rows ?? []).map((row, i) => [
    String(i + 1),
    row.question,
    row.answer,
    row.relevance === 1 ? 'Pass' : row.relevance === 0 ? 'Fail' : '—',
    row.quality === 1 ? 'Pass' : row.quality === 0 ? 'Fail' : '—',
  ]);

  autoTable(doc, {
    startY: summaryY + 90,
    head: [['#', 'Question', 'Answer (preview)', 'Relevance', 'Quality']],
    body: tableRows,
    styles: { fontSize: 9, cellPadding: 6, overflow: 'linebreak' },
    headStyles: { fillColor: [37, 99, 235], textColor: 255, fontStyle: 'bold' },
    columnStyles: {
      0: { halign: 'center', cellWidth: 28 },
      1: { cellWidth: 170 },
      2: { cellWidth: 250 },
      3: { halign: 'center', cellWidth: 72 },
      4: { halign: 'center', cellWidth: 72 },
    },
    alternateRowStyles: { fillColor: [248, 250, 252] },
    didParseCell(data) {
      // Colour Pass/Fail cells
      if (data.section === 'body' && (data.column.index === 3 || data.column.index === 4)) {
        if (data.cell.text[0] === 'Pass') {
          data.cell.styles.textColor = [21, 128, 61];
          data.cell.styles.fontStyle = 'bold';
        } else if (data.cell.text[0] === 'Fail') {
          data.cell.styles.textColor = [185, 28, 28];
          data.cell.styles.fontStyle = 'bold';
        }
      }
    },
  });

  // ── Page footer ───────────────────────────────────────────────────────────
  const pageCount = (doc.internal as any).getNumberOfPages();
  for (let p = 1; p <= pageCount; p++) {
    doc.setPage(p);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(8);
    doc.setTextColor(148, 163, 184);
    doc.text(
      `Vedic Astrology AI Agent · LangSmith Evaluation · Page ${p} of ${pageCount}`,
      pageW / 2,
      doc.internal.pageSize.getHeight() - 16,
      { align: 'center' },
    );
  }

  doc.save(`vedic-astro-eval-${Date.now()}.pdf`);
}

// ── Component ─────────────────────────────────────────────────────────────────

export function EvalPanel({ sessionId }: { sessionId: string }) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<EvalResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  async function handleEvaluate() {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await runEval(sessionId);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Evaluation failed. Check the backend logs.');
    } finally {
      setLoading(false);
    }
  }

  async function handleDownload() {
    if (!result) return;
    setDownloading(true);
    try {
      await downloadPDF(result);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="panel" style={{ marginTop: 24 }}>
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 24 }}>
        <div>
          <div className="agent-label">LangSmith</div>
          <h2 style={{ marginBottom: 4 }}>Agent Response Evaluator</h2>
          <p className="small" style={{ marginBottom: 4 }}>
            Runs LLM-graded criteria evaluation (Relevance &amp; Quality) on all logged chat
            interactions and uploads them as a LangSmith dataset.
          </p>
          <p className="small" style={{ marginBottom: 0, color: 'var(--accent-2)', fontWeight: 600 }}>
            Evaluating interactions from this session only.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10, flexShrink: 0, alignSelf: 'center' }}>
          {result?.status === 'ok' && (
            <button
              onClick={handleDownload}
              disabled={downloading}
              style={{
                padding: '11px 20px',
                borderRadius: 12,
                border: '1px solid var(--border)',
                background: 'white',
                color: '#334155',
                fontWeight: 700,
                fontSize: 14,
                cursor: downloading ? 'wait' : 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              {downloading ? 'Generating…' : '⬇ Download Report'}
            </button>
          )}
          <button
            className="btn"
            onClick={handleEvaluate}
            disabled={loading}
            style={{ whiteSpace: 'nowrap' }}
          >
            {loading ? 'Evaluating…' : '▶ Evaluate'}
          </button>
        </div>
      </div>

      {/* Error from fetch */}
      {error && (
        <div className="reading-card" style={{ marginTop: 16, borderColor: '#fecaca', background: '#fff1f2' }}>
          <p style={{ marginBottom: 0 }}>{error}</p>
        </div>
      )}

      {/* No data / config error from backend */}
      {result && result.status !== 'ok' && (
        <div
          className="reading-card"
          style={{
            marginTop: 16,
            borderColor: result.status === 'error' ? '#fecaca' : '#dbeafe',
            background: result.status === 'error' ? '#fff1f2' : '#eff6ff',
          }}
        >
          <p style={{ marginBottom: 0 }}>{result.message}</p>
        </div>
      )}

      {/* Results */}
      {result?.status === 'ok' && (
        <>
          {/* Summary chips */}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 18 }}>
            <Chip color="green">{result.examples_count} interactions evaluated</Chip>
            <Chip color="blue">Relevance: <strong>{result.scores?.relevance}%</strong></Chip>
            <Chip color="purple">Quality: <strong>{result.scores?.quality}%</strong></Chip>
            {result.dataset_url && (
              <a href={result.dataset_url} target="_blank" rel="noopener noreferrer">
                <Chip color="amber">View Dataset in LangSmith ↗</Chip>
              </a>
            )}
          </div>

          {/* Per-row table */}
          {result.rows && result.rows.length > 0 && (
            <div style={{ overflowX: 'auto', marginTop: 18 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ background: '#f8fafc', borderBottom: '2px solid var(--border)' }}>
                    {['#', 'Question', 'Answer (preview)', 'Relevance', 'Quality'].map((h) => (
                      <th
                        key={h}
                        style={{
                          textAlign: h === 'Relevance' || h === 'Quality' || h === '#' ? 'center' : 'left',
                          padding: '10px 12px',
                          fontWeight: 600,
                          color: '#334155',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row, i) => (
                    <EvalTableRow key={i} row={row} index={i + 1} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function EvalTableRow({ row, index }: { row: EvalRow; index: number }) {
  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}>
      <td style={{ padding: '10px 12px', textAlign: 'center', color: '#94a3b8', fontSize: 12 }}>{index}</td>
      <td style={{ padding: '10px 12px', color: '#334155', maxWidth: 240, wordBreak: 'break-word' }}>
        {row.question}
      </td>
      <td style={{ padding: '10px 12px', color: '#64748b', maxWidth: 340, wordBreak: 'break-word' }}>
        {row.answer}
      </td>
      <td style={{ padding: '10px 12px', textAlign: 'center' }}>
        <ScoreBadge score={row.relevance} />
      </td>
      <td style={{ padding: '10px 12px', textAlign: 'center' }}>
        <ScoreBadge score={row.quality} />
      </td>
    </tr>
  );
}

function ScoreBadge({ score }: { score: number | null }) {
  if (score === null || score === undefined) {
    return <span style={{ color: '#94a3b8' }}>—</span>;
  }
  const pass = score === 1;
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '3px 11px',
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 600,
        background: pass ? '#f0fdf4' : '#fff1f2',
        color: pass ? '#15803d' : '#b91c1c',
        border: `1px solid ${pass ? '#bbf7d0' : '#fecaca'}`,
      }}
    >
      {pass ? '✓ Pass' : '✗ Fail'}
    </span>
  );
}

type ChipColor = 'green' | 'blue' | 'purple' | 'amber';

const CHIP_STYLES: Record<ChipColor, React.CSSProperties> = {
  green:  { background: '#f0fdf4', borderColor: '#bbf7d0', color: '#166534' },
  blue:   { background: '#eff6ff', borderColor: '#bfdbfe', color: '#1e40af' },
  purple: { background: '#f5f3ff', borderColor: '#ddd6fe', color: '#5b21b6' },
  amber:  { background: '#fefce8', borderColor: '#fde68a', color: '#92400e' },
};

function Chip({ color, children }: { color: ChipColor; children: React.ReactNode }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '7px 14px',
        borderRadius: 999,
        border: '1px solid',
        fontSize: 13,
        ...CHIP_STYLES[color],
      }}
    >
      {children}
    </span>
  );
}
