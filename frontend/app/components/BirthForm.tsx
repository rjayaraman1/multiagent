'use client';

import { useState, type ChangeEvent } from 'react';
import type { BirthInput } from '@/lib/types';

type Props = {
  value: BirthInput;
  onChange: (next: BirthInput) => void;
  onSubmit: () => void;
  loading?: boolean;
};

function toDisplayDate(iso: string): string {
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  // DD/MM/YYYY: day first, Indian date convention
  return m ? `${m[3]}/${m[2]}/${m[1]}` : iso;
}

function toIsoDate(display: string): string | null {
  const m = display.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (!m) return null;
  const day = parseInt(m[1], 10);
  const month = parseInt(m[2], 10);
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  // DD/MM/YYYY → ISO YYYY-MM-DD
  return `${m[3]}-${m[2].padStart(2, '0')}-${m[1].padStart(2, '0')}`;
}

export function BirthForm({ value, onChange, onSubmit, loading }: Props) {
  const [dateDisplay, setDateDisplay] = useState(() => toDisplayDate(value.birth_date));
  const [dateError, setDateError] = useState<string | null>(null);

  const set = (key: keyof BirthInput) => (e: ChangeEvent<HTMLInputElement>) =>
    onChange({ ...value, [key]: e.target.value });

  function handleDateChange(e: ChangeEvent<HTMLInputElement>) {
    const display = e.target.value;
    setDateDisplay(display);
    const iso = toIsoDate(display);
    if (iso) {
      setDateError(null);
      onChange({ ...value, birth_date: iso });
    } else if (display.length === 10) {
      setDateError('Use DD/MM/YYYY format, e.g. 15/08/1990');
    } else {
      setDateError(null);
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const iso = toIsoDate(dateDisplay);
    if (!iso) {
      setDateError('Use DD/MM/YYYY format, e.g. 15/08/1990');
      return;
    }
    setDateError(null);
    if (iso !== value.birth_date) {
      onChange({ ...value, birth_date: iso });
    }
    onSubmit();
  }

  return (
    <form onSubmit={handleSubmit}>
      <div className="form-grid">
        <div className="field">
          <label>Name</label>
          <input value={value.name} onChange={set('name')} placeholder="Your name" />
        </div>
        <div className="field">
          <label>Date of Birth (DD/MM/YYYY)</label>
          <input
            value={dateDisplay}
            onChange={handleDateChange}
            placeholder="DD/MM/YYYY"
            maxLength={10}
          />
          {dateError && <span style={{ color: '#dc2626', fontSize: '0.75rem' }}>{dateError}</span>}
        </div>
        <div className="field">
          <label>Birth time</label>
          <input type="time" value={value.birth_time} onChange={set('birth_time')} />
        </div>
        <div className="field" style={{ gridColumn: '1 / -1' }}>
          <label>Birth place</label>
          <div className="place-grid">
            <input value={value.birth_city} onChange={set('birth_city')} placeholder="City (e.g. Chennai)" />
            <input value={value.birth_state} onChange={set('birth_state')} placeholder="State (e.g. Tamil Nadu)" />
            <input value={value.birth_country} onChange={set('birth_country')} placeholder="Country (e.g. India)" />
          </div>
        </div>
        <div className="field">
          <label>UTC offset (auto-detected)</label>
          <input
            value={value.timezone}
            onChange={set('timezone')}
            placeholder="+05:30"
            maxLength={6}
            style={{ maxWidth: '40%' }}
          />
        </div>
      </div>

      <div className="actions">
        <button className="btn" type="submit" disabled={loading}>
          {loading ? 'Generating…' : 'Generate chart'}
        </button>
        <span className="small">Enter your birth details and click Generate chart.</span>
      </div>
      <div className="agent-label" style={{ marginTop: 10 }}>Star retriever agent</div>
    </form>
  );
}
