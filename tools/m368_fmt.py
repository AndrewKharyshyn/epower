"""M368 display formatters (analyses/M368_spec.md Rev 2). Display-only: stored values are never changed.

fmt_energy(x, signed): R4 - 2 dp when |x| >= 0.1, else 2 significant figures; never a signed zero.
fmt_cycles(x): GTC/FCE/rf_efc are dimensionless cycle counts (depend on CAP_KWH, verified:false) - 2 dp, same zero rule.
"""
import math


def _sig(x, n):
    if x == 0:
        return "0"
    d = n - 1 - int(math.floor(math.log10(abs(x))))
    return f"{round(x, d):.{max(d, 0)}f}"


NOISE = 1e-6        # below this a stored sum is numerical noise, shown as 0.00 (never a signed zero)


def _two(x):
    if abs(x) < NOISE:
        return "0.00"
    s = _sig(x, 2)
    return f"{x:.2f}" if abs(float(s)) >= 0.1 else s     # 0.0999 -> "0.10", not "0.100"


def fmt_energy(x, signed=False):
    x = float(x)
    s = _two(x)
    return "+" + s if signed and s != "0.00" and x > 0 else s


def fmt_cycles(x):
    return _two(float(x))
