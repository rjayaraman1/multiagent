import type { ReadingResponse } from '@/lib/types';

export function ReadingPanel({ reading }: { reading: ReadingResponse | null }) {
  if (!reading) {
    return (
      <div className="panel">
        <h2>Horoscope reading</h2>
        <p>Generate a chart to see the interpretation.</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>{reading.headline}</h2>
      <p>{reading.summary}</p>

      <div className="section-stack">
        {reading.sections.map((section) => (
          <div className="reading-card" key={section.heading}>
            <h3>{section.heading}</h3>
            <p>{section.body}</p>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 18 }}>
        <div className="small" style={{ marginBottom: 8 }}>Retrieved passages</div>
        {reading.source_passages.length > 0 ? (
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            {reading.source_passages.map((passage, idx) => (
              <li key={idx} style={{ marginBottom: 10 }}>{passage}</li>
            ))}
          </ul>
        ) : (
          <p className="small">No passages retrieved.</p>
        )}
      </div>
    </div>
  );
}
