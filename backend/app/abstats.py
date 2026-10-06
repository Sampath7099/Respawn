"""Statistics for the A/B readout. One implementation, used by the API's live
readout and by analysis/ab_test.py."""
import math


def two_proportion_ztest(x1, n1, x2, n2):
    """Pooled two-sided z-test for p2 - p1. Returns (z, p_value)."""
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return 0.0, 1.0
    z = (x2 / n2 - x1 / n1) / se
    return z, math.erfc(abs(z) / math.sqrt(2))


def holm(p_values):
    """Holm-Bonferroni adjusted p-values (same order as given)."""
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted, running = [0.0] * m, 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p_values[i]))
        adjusted[i] = running
    return adjusted
