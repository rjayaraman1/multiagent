import type { ChartResponse } from '@/lib/types';

const SIGNS = [
  'Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
  'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces',
];

// South Indian chart: signs are always fixed in these grid positions
// Top row L→R: Pisces, Aries, Taurus, Gemini
// Left col T→B: Pisces, Aquarius, Capricorn, Sagittarius
// Right col T→B: Gemini, Cancer, Leo, Virgo
// Bottom row L→R: Sagittarius, Scorpio, Libra, Virgo
const SIGN_GRID: [number, number, string][] = [
  [0, 0, 'Pisces'],
  [0, 1, 'Aries'],
  [0, 2, 'Taurus'],
  [0, 3, 'Gemini'],
  [1, 0, 'Aquarius'],
  [1, 3, 'Cancer'],
  [2, 0, 'Capricorn'],
  [2, 3, 'Leo'],
  [3, 0, 'Sagittarius'],
  [3, 1, 'Scorpio'],
  [3, 2, 'Libra'],
  [3, 3, 'Virgo'],
];

const PLANET_ABBR: Record<string, string> = {
  Sun: 'Su', Moon: 'Mo', Mars: 'Ma', Mercury: 'Me',
  Jupiter: 'Ju', Venus: 'Ve', Saturn: 'Sa', Rahu: 'Ra', Ketu: 'Ke',
};

const CELL = 116;
const SIZE = CELL * 4;

export function HoroscopeWheel({ chart }: { chart: ChartResponse | null }) {
  const placements = chart?.placements ?? [];
  const ascSign = chart?.profile.ascendant_sign ?? '';
  const ascIdx = SIGNS.indexOf(ascSign);

  const signToPlanets: Record<string, string[]> = {};
  for (const p of placements) {
    (signToPlanets[p.sign] ??= []).push(PLANET_ABBR[p.body] ?? p.body.slice(0, 2));
  }

  function houseFor(sign: string): number {
    if (ascIdx < 0) return 0;
    const sIdx = SIGNS.indexOf(sign);
    if (sIdx < 0) return 0;
    return ((sIdx - ascIdx + 12) % 12) + 1;
  }

  if (!chart) {
    return (
      <div className="panel" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '12px', minHeight: '320px', textAlign: 'center' }}>
        <div style={{ fontSize: '36px', opacity: 0.18 }}>☽</div>
        <div style={{ fontSize: '15px', fontWeight: '700', color: '#334155' }}>Vedic Astrology Rasi Chart</div>
        <p style={{ margin: 0, fontSize: '14px', color: '#94a3b8', maxWidth: '220px', lineHeight: '1.5' }}>
          Enter your birth details and click <strong>Generate chart</strong> to see your placements.
        </p>
      </div>
    );
  }

  return (
    <div
      className="chart-wrap"
      style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '14px', padding: '24px' }}
    >
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: '15px', fontWeight: '700', color: '#334155' }}>Vedic Astrology Rasi Chart</div>
        <div style={{ fontSize: '13px', color: '#64748b' }}>{ascSign} Ascendant</div>
      </div>

      <svg
        width={SIZE}
        height={SIZE}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        aria-label="South Indian Vedic chart"
        style={{ fontFamily: 'system-ui, sans-serif', display: 'block' }}
      >
        {/* Base fill */}
        <rect x={0} y={0} width={SIZE} height={SIZE} fill="#fafaf9" />

        {/* Sign cell backgrounds */}
        {SIGN_GRID.map(([row, col, sign]) => (
          <rect
            key={sign + '-bg'}
            x={col * CELL} y={row * CELL}
            width={CELL} height={CELL}
            fill={sign === ascSign ? '#fef9c3' : '#ffffff'}
          />
        ))}

        {/* Center 2×2 area */}
        <rect x={CELL} y={CELL} width={CELL * 2} height={CELL * 2} fill="#f5f0e8" />

        {/* Grid lines (drawn over backgrounds so borders are crisp) */}
        <rect x={0} y={0} width={SIZE} height={SIZE} fill="none" stroke="#1c1917" strokeWidth="2.5" />
        {[1, 2, 3].map(i => (
          <line key={`h${i}`} x1={0} y1={i * CELL} x2={SIZE} y2={i * CELL} stroke="#1c1917" strokeWidth="1.5" />
        ))}
        {[1, 2, 3].map(i => (
          <line key={`v${i}`} x1={i * CELL} y1={0} x2={i * CELL} y2={SIZE} stroke="#1c1917" strokeWidth="1.5" />
        ))}

        {/* Center diagonals */}
        <line x1={CELL} y1={CELL} x2={CELL * 3} y2={CELL * 3} stroke="#c5b99a" strokeWidth="1.5" />
        <line x1={CELL * 3} y1={CELL} x2={CELL} y2={CELL * 3} stroke="#c5b99a" strokeWidth="1.5" />

        {/* Center label */}
        <text x={SIZE / 2} y={SIZE / 2 - 6} textAnchor="middle" fontSize="12" fill="#78716c" fontWeight="700">
          {ascSign}
        </text>
        <text x={SIZE / 2} y={SIZE / 2 + 12} textAnchor="middle" fontSize="10" fill="#a8a29e">
          Rasi
        </text>

        {/* Cell content: house number, sign label, planet list */}
        {SIGN_GRID.map(([row, col, sign]) => {
          const x = col * CELL;
          const y = row * CELL;
          const house = houseFor(sign);
          const isAsc = sign === ascSign;
          const planets = signToPlanets[sign] ?? [];

          return (
            <g key={sign}>
              {/* House number – top-left corner */}
              <text
                x={x + 7} y={y + 16}
                fontSize="12"
                fill={isAsc ? '#854d0e' : '#78716c'}
                fontWeight={isAsc ? '700' : '400'}
              >
                {house > 0 ? house : ''}
              </text>

              {/* Sign abbreviation – top-right corner */}
              <text
                x={x + CELL - 7} y={y + 16}
                textAnchor="end"
                fontSize="10"
                fill="#a8a29e"
              >
                {sign.slice(0, 3)}
              </text>

              {/* ASC label – bottom-center of ascendant cell */}
              {isAsc && (
                <text
                  x={x + CELL / 2} y={y + CELL - 7}
                  textAnchor="middle"
                  fontSize="9"
                  fill="#854d0e"
                  fontWeight="700"
                  letterSpacing="1"
                >
                  ASC
                </text>
              )}

              {/* Planet abbreviations stacked vertically */}
              {planets.map((abbr, i) => (
                <text
                  key={abbr + i}
                  x={x + CELL / 2}
                  y={y + 34 + i * 17}
                  textAnchor="middle"
                  fontSize="13"
                  fill="#1c1917"
                  fontWeight="600"
                >
                  {abbr}
                </text>
              ))}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
