'use client';

import { useEffect, useRef, useState } from 'react';
import { chatMessage } from '@/lib/api';
import type { ChartResponse } from '@/lib/types';

type Message = {
  role: 'user' | 'assistant';
  text: string;
  sources?: string[];
};

function buildChartSummary(chart: ChartResponse): string {
  const { ascendant_sign, moon_sign, moon_nakshatra, sun_sign } = chart.profile;
  const top4 = chart.placements
    .slice(0, 4)
    .map((p) => `${p.body} in ${p.sign} (house ${p.house})`)
    .join(', ');
  return `Ascendant (Lagna): ${ascendant_sign}; Moon Sign (Raashi): ${moon_sign}; Moon Nakshatra (birth star): ${moon_nakshatra}; Sun Sign: ${sun_sign}; Key placements: ${top4}`;
}

type Props = {
  chart: ChartResponse | null;
  sessionId: string;
};

export function ChatPanel({ chart, sessionId }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  async function handleSend() {
    const text = input.trim();
    if (!text || loading) return;

    setInput('');
    setMessages((prev) => [...prev, { role: 'user', text }]);
    setLoading(true);

    try {
      const res = await chatMessage({
        message: text,
        session_id: sessionId,
        chart_summary: chart ? buildChartSummary(chart) : null,
      });
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', text: res.answer, sources: res.sources },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: err instanceof Error ? `Error: ${err.message}` : 'Something went wrong.',
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const hasChart = chart !== null;

  return (
    <div className="panel" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      <div className="agent-label">Ask Astro agent</div>
      <p className="small" style={{ marginBottom: 0 }}>
        {hasChart
          ? (() => {
              const nakshatra = chart!.profile.moon_nakshatra;
              const moonSign = chart!.profile.moon_sign;
              return (
                <>
                  <span style={{ fontWeight: 600 }}>Star (Nakshatra):</span>{' '}
                  <span style={{ fontWeight: 500 }}>{nakshatra}</span>
                  <span style={{ margin: '0 6px', opacity: 0.5 }}>·</span>
                  <span style={{ fontWeight: 600 }}>Moon Sign (Raashi):</span>{' '}
                  <span style={{ fontWeight: 500 }}>{moonSign}</span>
                </>
              );
            })()
          : 'Generate a chart first for personalised answers, or ask general Vedic astrology questions.'}
      </p>

      <div className="chat-history">
        {messages.length === 0 && !loading && (
          <span className="small" style={{ color: '#cbd5e1' }}>
            Your conversation will appear here.
          </span>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={msg.role === 'user' ? 'chat-bubble-user' : 'chat-bubble-assistant'}
          >
            <div className="chat-bubble-text">{msg.text}</div>
            {msg.sources && msg.sources.length > 0 && (
              <div className="chat-sources">
                Sources: {msg.sources.join(', ')}
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="chat-bubble-assistant">
            <div className="chat-bubble-text" style={{ color: '#94a3b8' }}>Thinking…</div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <div className="chat-input-row">
        <textarea
          className="chat-textarea"
          placeholder={
            hasChart
              ? 'Ask about your chart or Vedic astrology… (Enter to send)'
              : 'Ask about Nakshatras, Raashi signs, houses… (Enter to send)'
          }
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={3}
          disabled={loading}
        />
        <button
          className="chat-send-btn"
          onClick={handleSend}
          disabled={loading || !input.trim()}
        >
          {loading ? 'Thinking…' : 'Ask'}
        </button>
      </div>
    </div>
  );
}
