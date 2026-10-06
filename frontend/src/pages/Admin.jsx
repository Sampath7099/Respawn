import { useEffect, useState } from "react";
import { api } from "../api.js";

const fmt = {
  money: (v) => `$${Math.round(v).toLocaleString()}`,
  num: (v) => Math.round(v).toLocaleString(),
};

// Area chart with a hover readout. `tone` picks the neon colour.
function Sparkline({ data, field, label, format, tone }) {
  const [hover, setHover] = useState(null);
  if (!data.length) return <div className="panel skeleton tall" />;
  const w = 640, h = 150, pad = 8;
  const vals = data.map((d) => Number(d[field]));
  const max = Math.max(...vals) || 1;
  const x = (i) => pad + (i * (w - 2 * pad)) / Math.max(vals.length - 1, 1);
  const y = (v) => h - pad - (v / max) * (h - 2 * pad);
  const path = vals.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");
  const shown = hover ?? vals.length - 1;
  const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
  const id = `g-${field}`;
  return (
    <div className={`panel tone-${tone}`}>
      <div className="panel-head">
        <span className="mono">{label}</span>
        <b>{format(hover === null ? avg : vals[shown])}</b>
        <span className="muted small mono">{hover === null ? "AVG / DAY · hover for a day" : String(data[shown].date_day).slice(0, 10)}</span>
      </div>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="spark"
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          setHover(Math.max(0, Math.min(vals.length - 1, Math.round(((e.clientX - r.left) / r.width) * (vals.length - 1)))));
        }}
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" className="spark-stop-top" />
            <stop offset="100%" className="spark-stop-bottom" />
          </linearGradient>
        </defs>
        <path d={`${path} L${x(vals.length - 1)},${h} L${x(0)},${h} Z`} fill={`url(#${id})`} />
        <path d={path} className="spark-line" />
        {hover !== null && (
          <>
            <line x1={x(shown)} x2={x(shown)} y1={0} y2={h} className="spark-cursor" />
            <circle cx={x(shown)} cy={y(vals[shown])} r="5" className="spark-dot" />
          </>
        )}
      </svg>
    </div>
  );
}

function ArmBar({ label, value, max, tone }) {
  return (
    <div className="arm-bar">
      <span className="mono">{label}</span>
      <div className="arm-track">
        <i className={`tone-${tone}`} style={{ width: `${(value / max) * 100}%` }} />
      </div>
      <b>{(value * 100).toFixed(2)}%</b>
    </div>
  );
}

export default function Admin() {
  const [kpis, setKpis] = useState([]);
  const [ab, setAb] = useState(null);

  useEffect(() => {
    // dim_date spans first..last event, so quiet days between the simulated history and live traffic are zeros
    api("/metrics/kpis").then((rows) => setKpis(rows.filter((r) => r.dau > 0)));
    api("/metrics/ab").then(setAb);
  }, []);

  const arms = ab?.arms?.length === 2 ? ab.arms : null;
  const maxRate = arms ? Math.max(...arms.map((a) => a.buyer_rate)) : 1;

  return (
    <>
      <div className="page-head">
        <h1 className="section-title">Analytics</h1>
        <span className="chip-mono">SOURCE: DBT MARTS · REFRESHED BY AIRFLOW</span>
      </div>

      {arms ? (
        <section className="panel ab">
          <div className="panel-head">
            <span className="mono">EXPERIMENT · {ab.experiment}</span>
            <b className={ab.p_value < 0.05 ? "sig" : "nsig"}>
              {ab.p_value < 0.05 ? "◆ SIGNIFICANT" : "◇ NOT SIGNIFICANT"} · p = {ab.p_value.toExponential(1)}
            </b>
          </div>
          <p className="muted small">Primary metric: share of users who bought at least once (pre-registered).</p>
          <div className="arm-bars">
            <ArmBar label="CONTROL · POPULARITY" value={arms[0].buyer_rate} max={maxRate} tone="cyan" />
            <ArmBar label="TREATMENT · MF + RANKER" value={arms[1].buyer_rate} max={maxRate} tone="pink" />
          </div>
          <div className="ab-arms">
            {arms.map((a) => (
              <div key={a.variant} className={`ab-arm ${a.variant}`}>
                <h3>{a.variant}</h3>
                <div className="hud">
                  <div><b>{fmt.num(a.users)}</b><span>users</span></div>
                  <div><b>{fmt.num(a.buyers)}</b><span>buyers</span></div>
                  <div><b>${a.revenue_per_user.toFixed(2)}</b><span>revenue / user</span></div>
                </div>
              </div>
            ))}
            <div className="ab-lift">
              <span className="mono">BUYER-RATE LIFT</span>
              <b className="neon-pink">+{(ab.lift * 100).toFixed(1)}%</b>
              <span className="mono muted">z = {ab.z.toFixed(2)}</span>
            </div>
          </div>
          <p className="muted small">
            Shoppers are simulated (see README): this validates the experiment pipeline end to end, not real-world lift.
          </p>
        </section>
      ) : (
        <div className="panel skeleton tall" />
      )}

      <div className="panels">
        <Sparkline data={kpis} field="gmv" label="DAILY GMV" format={fmt.money} tone="pink" />
        <Sparkline data={kpis} field="dau" label="DAILY ACTIVE USERS" format={fmt.num} tone="cyan" />
        <Sparkline data={kpis} field="orders" label="ORDERS" format={fmt.num} tone="yellow" />
        <Sparkline data={kpis} field="sessions" label="SESSIONS" format={fmt.num} tone="violet" />
      </div>
    </>
  );
}
