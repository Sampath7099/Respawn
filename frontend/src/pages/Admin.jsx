import { useEffect, useState } from "react";
import { api } from "../api.js";

// Live readout straight from the dbt marts: daily KPIs and the A/B test.
function Sparkline({ data, field, label, format }) {
  const [hover, setHover] = useState(null);
  if (!data.length) return null;
  const w = 640, h = 140, pad = 6;
  const vals = data.map((d) => Number(d[field]));
  const max = Math.max(...vals) || 1;
  const x = (i) => pad + (i * (w - 2 * pad)) / (vals.length - 1);
  const y = (v) => h - pad - (v / max) * (h - 2 * pad);
  const path = vals.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");
  const shown = hover ?? vals.length - 1;
  return (
    <div className="panel">
      <div className="panel-head">
        <span>{label}</span>
        <b>{format(vals[shown])}</b>
        <span className="muted small">{String(data[shown].date_day).slice(0, 10)}</span>
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
        <path d={`${path} L${x(vals.length - 1)},${h} L${x(0)},${h} Z`} className="spark-fill" />
        <path d={path} className="spark-line" />
        <circle cx={x(shown)} cy={y(vals[shown])} r="4" className="spark-dot" />
      </svg>
    </div>
  );
}

export default function Admin() {
  const [kpis, setKpis] = useState([]);
  const [ab, setAb] = useState(null);

  useEffect(() => {
    api("/metrics/kpis").then(setKpis);
    api("/metrics/ab").then(setAb);
  }, []);

  const money = (v) => `$${Math.round(v).toLocaleString()}`;
  const num = (v) => Math.round(v).toLocaleString();

  return (
    <>
      <h1>Analytics</h1>
      <p className="muted">From the warehouse (dbt marts), refreshed by the Airflow DAG.</p>

      {ab?.arms?.length === 2 && (
        <section className="panel ab">
          <div className="panel-head">
            <span>A/B test · home-recs-v1</span>
            <b className={ab.p_value < 0.05 ? "sig" : ""}>
              {ab.p_value < 0.05 ? "significant" : "not significant"} · p = {ab.p_value.toExponential(1)}
            </b>
          </div>
          <div className="ab-arms">
            {ab.arms.map((a) => (
              <div key={a.variant} className="ab-arm">
                <h3>{a.variant === "control" ? "Control · popularity" : "Treatment · MF + ranker"}</h3>
                <div className="stats">
                  <div><b>{num(a.users)}</b><span>users</span></div>
                  <div><b>{(a.buyer_rate * 100).toFixed(2)}%</b><span>buyer rate</span></div>
                  <div><b>${a.revenue_per_user.toFixed(2)}</b><span>revenue / user</span></div>
                </div>
              </div>
            ))}
          </div>
          <p className="muted">
            Buyer-rate lift <b className="neon">{(ab.lift * 100).toFixed(1)}%</b> (two-proportion z = {ab.z.toFixed(2)})
          </p>
        </section>
      )}

      <div className="panels">
        <Sparkline data={kpis} field="gmv" label="Daily GMV" format={money} />
        <Sparkline data={kpis} field="dau" label="Daily active users" format={num} />
        <Sparkline data={kpis} field="orders" label="Orders" format={num} />
        <Sparkline data={kpis} field="sessions" label="Sessions" format={num} />
      </div>
    </>
  );
}
