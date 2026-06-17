'use client';

import { useState } from 'react';
import { respondToHandoff } from '@/lib/api';
import type { HandoffQuestion, PredictionReport } from '@/lib/types';
import { isHandoffQuestion } from '@/lib/types';

interface Props {
  handoff: HandoffQuestion;
  onResolved: (report: PredictionReport) => void;
  onNextHandoff: (hq: HandoffQuestion) => void;
  onDismiss: () => void;
}

export function HumanHandoffPanel({ handoff, onResolved, onNextHandoff, onDismiss }: Props) {
  const [answer, setAnswer] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (!answer.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await respondToHandoff({ session_id: handoff.session_id, answer: answer.trim() });
      if (isHandoffQuestion(result)) {
        onNextHandoff(result);
      } else {
        onResolved(result as PredictionReport);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit answer');
    } finally {
      setLoading(false);
    }
  }

  return (
    /* Modal overlay */
    <div style={{
      position: 'fixed',
      inset: 0,
      background: 'rgba(15, 23, 42, 0.55)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000,
      backdropFilter: 'blur(4px)',
    }}>
      <div style={{
        background: 'white',
        borderRadius: 24,
        padding: 32,
        maxWidth: 520,
        width: '90%',
        boxShadow: '0 24px 64px rgba(15,23,42,0.18)',
        border: '1px solid #e2e8f0',
      }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
          <div style={{
            width: 36,
            height: 36,
            borderRadius: '50%',
            background: 'linear-gradient(135deg, #f59e0b, #d97706)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 18,
            flexShrink: 0,
          }}>
            🤝
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 15, color: '#1e293b' }}>
              Agent needs your input
            </div>
            <div style={{ fontSize: 12, color: '#64748b' }}>
              Step: {handoff.step}
            </div>
          </div>
        </div>

        {/* Question */}
        <div style={{
          background: '#fffbeb',
          border: '1px solid #fde68a',
          borderRadius: 14,
          padding: '12px 16px',
          marginBottom: 16,
        }}>
          <p style={{ margin: 0, fontSize: 15, color: '#1e293b', lineHeight: 1.6 }}>
            {handoff.question}
          </p>
        </div>

        {/* Context (collapsible) */}
        {handoff.context && (
          <details style={{ marginBottom: 14 }}>
            <summary style={{ fontSize: 12, color: '#94a3b8', cursor: 'pointer' }}>
              Show agent context
            </summary>
            <p style={{ fontSize: 12, color: '#64748b', margin: '6px 0 0', lineHeight: 1.5 }}>
              {handoff.context}
            </p>
          </details>
        )}

        {/* Answer input */}
        <textarea
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="Type your answer here…"
          rows={3}
          className="chat-textarea"
          style={{ width: '100%', marginBottom: 12, resize: 'vertical' }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleSubmit();
            }
          }}
        />

        {error && (
          <p style={{ color: '#dc2626', fontSize: 13, margin: '0 0 10px' }}>{error}</p>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button
            onClick={onDismiss}
            style={{
              padding: '10px 16px',
              borderRadius: 12,
              border: '1px solid #e2e8f0',
              background: 'white',
              cursor: 'pointer',
              fontSize: 14,
              color: '#64748b',
            }}
          >
            Cancel
          </button>
          <button
            className="btn"
            onClick={handleSubmit}
            disabled={loading || !answer.trim()}
            style={{ fontSize: 14 }}
          >
            {loading ? 'Resuming agent…' : 'Submit & Resume Agent'}
          </button>
        </div>
      </div>
    </div>
  );
}
