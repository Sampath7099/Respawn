"""A/B readout for experiment home-recs-v1.

Plan, fixed before looking at results:
- Unit of randomisation and analysis: the user.
- Guardrail first: sample-ratio mismatch (chi-square on arm sizes). If it fails, stop.
- Primary metric: buyer rate (share of users with >= 1 order). Two-proportion z-test, alpha 0.05.
- Secondary metrics, Holm-corrected together:
    revenue per user (Welch t-test, plus a bootstrap CI of the difference),
    recommendation-row click-through per user (each user's share of sessions with a
    rec_click; Welch t-test over users, not sessions, because sessions of one user are correlated).
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.abstats import holm, two_proportion_ztest  # noqa: E402

DSN = os.environ.get("RESPAWN_DSN", "postgresql://respawn:respawn@localhost:5433/respawn")
rng = np.random.default_rng(0)

with psycopg.connect(DSN) as conn:
    users = pd.read_sql("""
        WITH sessions AS (
            SELECT user_id, session_id, bool_or(event_type = 'rec_click') AS clicked
            FROM marts.fct_events GROUP BY 1, 2
        ), ctr AS (
            SELECT user_id, avg(clicked::int) AS rec_ctr FROM sessions GROUP BY 1
        ), spend AS (
            SELECT user_id, count(*) AS orders, sum(revenue) AS revenue FROM marts.fct_orders GROUP BY 1
        )
        SELECT u.user_id, u.variant, coalesce(s.orders, 0) > 0 AS bought,
               coalesce(s.revenue, 0)::float AS revenue, coalesce(c.rec_ctr, 0)::float AS rec_ctr
        FROM marts.dim_user u LEFT JOIN spend s USING (user_id) LEFT JOIN ctr c USING (user_id)""", conn)

c, t = users[users.variant == "control"], users[users.variant == "treatment"]

srm_p = stats.chisquare([len(c), len(t)]).pvalue
print(f"guardrail  SRM: control={len(c)} treatment={len(t)}  p={srm_p:.3f}")
if srm_p < 0.01:
    sys.exit("sample ratio mismatch: assignment is broken, results are not interpretable")

z, p = two_proportion_ztest(c.bought.sum(), len(c), t.bought.sum(), len(t))
lift = t.bought.mean() / c.bought.mean() - 1
print(f"PRIMARY    buyer rate: {c.bought.mean():.2%} -> {t.bought.mean():.2%}  lift={lift:+.1%}  z={z:.2f}  p={p:.2g}"
      f"  -> {'significant' if p < 0.05 else 'not significant'} at alpha=0.05")

boot = [rng.choice(t.revenue.values, len(t)).mean() - rng.choice(c.revenue.values, len(c)).mean()
        for _ in range(2000)]
lo, hi = np.percentile(boot, [2.5, 97.5])
secondary = {
    "revenue / user": (c.revenue.mean(), t.revenue.mean(), stats.ttest_ind(t.revenue, c.revenue, equal_var=False).pvalue),
    "rec row CTR / user": (c.rec_ctr.mean(), t.rec_ctr.mean(), stats.ttest_ind(t.rec_ctr, c.rec_ctr, equal_var=False).pvalue),
}
adjusted = holm([v[2] for v in secondary.values()])
for (name, (a, b, raw)), adj in zip(secondary.items(), adjusted, strict=True):
    print(f"secondary  {name}: {a:.4f} -> {b:.4f}  lift={b / a - 1:+.1%}  p={raw:.2g}  Holm p={adj:.2g}")
print(f"           revenue / user difference, bootstrap 95% CI: [${lo:.2f}, ${hi:.2f}]")
