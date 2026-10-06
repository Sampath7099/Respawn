"""A/B test readout: control vs treatment on buyer rate and revenue per user.

- buyer rate: two-proportion z-test
- revenue/user (heavy-tailed): Welch t-test + bootstrap 95% CI of the difference
- sample-ratio mismatch check first: a broken 50/50 split invalidates everything else
"""
import os

import numpy as np
import pandas as pd
import psycopg
from scipy import stats

DSN = os.environ.get("RESPAWN_DSN", "postgresql://respawn:respawn@localhost:5433/respawn")
rng = np.random.default_rng(0)

with psycopg.connect(DSN) as conn:
    df = pd.read_sql("""
        SELECT u.user_id, u.variant,
               count(o.order_id) > 0          AS bought,
               coalesce(sum(o.revenue), 0)    AS revenue
        FROM marts.dim_user u LEFT JOIN marts.fct_orders o USING (user_id)
        GROUP BY 1, 2""", conn)

    ctr = pd.read_sql("""
        SELECT variant, count(*) AS sessions, count(*) FILTER (WHERE clicked) AS clicked
        FROM (SELECT variant, session_id, bool_or(event_type = 'rec_click') AS clicked
              FROM marts.fct_events GROUP BY 1, 2) s
        GROUP BY 1""", conn).set_index("variant")

c, t = df[df.variant == "control"], df[df.variant == "treatment"]

srm_p = stats.chisquare([len(c), len(t)]).pvalue
print(f"users: control={len(c)} treatment={len(t)}  SRM p={srm_p:.3f} "
      f"({'OK' if srm_p > 0.01 else 'SAMPLE RATIO MISMATCH - stop'})")

# buyer rate
x1, n1, x2, n2 = c.bought.sum(), len(c), t.bought.sum(), len(t)
p_pool = (x1 + x2) / (n1 + n2)
z = (x2 / n2 - x1 / n1) / np.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
print(f"buyer rate: {x1/n1:.2%} -> {x2/n2:.2%}  lift={(x2/n2)/(x1/n1)-1:+.1%}  "
      f"z={z:.2f} p={2 * stats.norm.sf(abs(z)):.2g}")

# revenue per user
welch = stats.ttest_ind(t.revenue, c.revenue, equal_var=False)
boot = [rng.choice(t.revenue.values, len(t)).mean() - rng.choice(c.revenue.values, len(c)).mean()
        for _ in range(2000)]
lo, hi = np.percentile(boot, [2.5, 97.5])
print(f"revenue/user: ${c.revenue.mean():.2f} -> ${t.revenue.mean():.2f}  "
      f"Welch p={welch.pvalue:.2g}  bootstrap 95% CI of diff=[${lo:.2f}, ${hi:.2f}]")

# primary metric: did the "Picked for you" row get clicked? (per session)
(n1, x1), (n2, x2) = ctr.loc["control", ["sessions", "clicked"]], ctr.loc["treatment", ["sessions", "clicked"]]
p_pool = (x1 + x2) / (n1 + n2)
z = (x2 / n2 - x1 / n1) / np.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
print(f"rec row CTR (per session): {x1/n1:.2%} -> {x2/n2:.2%}  lift={(x2/n2)/(x1/n1)-1:+.1%}  "
      f"z={z:.2f} p={2 * stats.norm.sf(abs(z)):.2g}")
