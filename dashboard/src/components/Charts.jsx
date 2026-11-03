import { useState } from "react";

// Small dependency-free SVG charts.
// Mark specs: bars <= 24px thick, 4px rounded data-end, square at baseline, 2px surface gap between
// stacked segments, hairline recessive grid, hover tooltip, legend for >= 2 series, table view.

export const SERIES = { primary: "#5156be", secondary: "#d97706" };

function niceMax(v) {
  if (v <= 4) return 4;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / p;
  const step = n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return Math.ceil(v / ((step * p) / 4)) * ((step * p) / 4);
}

function roundTopRect(x, y, w, h, r) {
  if (h <= 0) return "";
  const rr = Math.min(r, h, w / 2);
  return `M${x},${y + h} L${x},${y + rr} Q${x},${y} ${x + rr},${y} L${x + w - rr},${y} Q${x + w},${y} ${x + w},${y + rr} L${x + w},${y + h} Z`;
}

/** Vertical stacked columns. data: [{label, values: {key: number}}]; series: [{key, name, color}] */
export function ColumnChart({ data, series, height = 220, ariaLabel }) {
  const [tip, setTip] = useState(null);
  const W = 400, H = height, L = 28, R = 6, T = 14, B = 28;
  const totals = data.map((d) => series.reduce((s, k) => s + (d.values[k.key] || 0), 0));
  const max = niceMax(Math.max(1, ...totals));
  const band = (W - L - R) / data.length;
  const bw = Math.min(24, band * 0.55);
  const y = (v) => T + (H - T - B) * (1 - v / max);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(max * f));

  return (
    <div className="chart-wrap" onMouseLeave={() => setTip(null)}>
      {series.length > 1 && (
        <div className="chart-legend">
          {series.map((s) => <span key={s.key}><span className="sw" style={{ background: s.color }} />{s.name}</span>)}
        </div>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="#eef0f6" strokeWidth="1" />
            <text x={L - 8} y={y(t) + 4} fontSize="11" fill="#8c94a8" textAnchor="end">{t}</text>
          </g>
        ))}
        {data.map((d, i) => {
          const cx = L + band * i + band / 2;
          let acc = 0;
          const segs = series.map((s, si) => {
            const v = d.values[s.key] || 0;
            const y0 = y(acc), y1 = y(acc + v);
            acc += v;
            const isTop = series.slice(si + 1).every((n) => !(d.values[n.key] > 0));
            const gap = si > 0 && v > 0 ? 2 : 0; // 2px surface gap between stacked segments
            const h = Math.max(0, y0 - y1 - gap);
            return v > 0 ? (
              isTop ? <path key={s.key} d={roundTopRect(cx - bw / 2, y1, bw, h, 4)} fill={s.color} />
                    : <rect key={s.key} x={cx - bw / 2} y={y1} width={bw} height={h} fill={s.color} />
            ) : null;
          });
          return (
            <g key={d.label}>
              {segs}
              <text x={cx} y={H - 10} fontSize="11" fill="#8c94a8" textAnchor="middle">{d.label}</text>
              {totals[i] > 0 && <text x={cx} y={y(totals[i]) - 6} fontSize="11" fill="#4b5875" textAnchor="middle">{totals[i]}</text>}
              <rect x={L + band * i} y={T} width={band} height={H - T - B} fill="transparent"
                    onMouseEnter={() => setTip({ i, x: ((cx) / W) * 100, y: (y(totals[i]) / H) * 100 })} />
            </g>
          );
        })}
        <line x1={L} x2={W - R} y1={y(0)} y2={y(0)} stroke="#d9dce6" strokeWidth="1" />
      </svg>
      {tip && (
        <div className="chart-tip" style={{ left: `${tip.x}%`, top: `${tip.y}%` }}>
          <div className="fw-semibold mb-1">{data[tip.i].full || data[tip.i].label}</div>
          {series.map((s) => (
            <div key={s.key}><span className="sw" style={{ background: s.color }} />{s.name}: <b>{data[tip.i].values[s.key] || 0}</b></div>
          ))}
        </div>
      )}
      <details className="chart-table">
        <summary>Show as table</summary>
        <table className="table table-sm">
          <thead><tr><th>Day</th>{series.map((s) => <th key={s.key}>{s.name}</th>)}</tr></thead>
          <tbody>{data.map((d) => <tr key={d.label}><td>{d.full || d.label}</td>{series.map((s) => <td key={s.key}>{d.values[s.key] || 0}</td>)}</tr>)}</tbody>
        </table>
      </details>
    </div>
  );
}

/** Horizontal bars, single series (magnitude). data: [{label, value}] */
export function BarList({ data, color = SERIES.primary, unit = "" }) {
  const [hover, setHover] = useState(null);
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div className="d-flex flex-column gap-3">
      {data.map((d) => (
        <div key={d.label} onMouseEnter={() => setHover(d.label)} onMouseLeave={() => setHover(null)}>
          <div className="d-flex justify-content-between small mb-1">
            <span className={hover === d.label ? "fw-semibold" : ""}>{d.label}</span>
            <span className="text-muted">{d.value}{unit}</span>
          </div>
          <div style={{ height: 10, background: "#f1f1fb", borderRadius: 5 }}>
            <div style={{ width: `${(d.value / max) * 100}%`, height: "100%", background: color, borderRadius: 5,
                          minWidth: d.value ? 6 : 0, transition: "width .3s" }} />
          </div>
        </div>
      ))}
    </div>
  );
}
