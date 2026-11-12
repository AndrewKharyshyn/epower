#!/usr/bin/env python3
"""M625 (spec analyses/M625_spec.md Rev 1, W1-04): analysis-scope statements derived from the analysed population, never typed.
  month_span(dates)        'May-November 2026' (one calendar year) / 'May 2026-May 2027' (across years) / 'May 2026' (one month); None when no date
  ambient_span(values)     'ambient -1 to 38 C'; None when no finite value; ROUND_HALF_UP through Decimal(str(x)); -0.0 -> '0'; one decimal for both endpoints if any is fractional
  winter_clause(dates, ...) December-to-February status from the dates of the analysed drives (R2); raises WinterAtSupport at or above the support floor: the Director decides the wording
Pure functions, no I/O."""
import datetime as _dt
import math
from decimal import Decimal, ROUND_HALF_UP

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
WINTER_MONTHS = (12, 1, 2)
MIN_DRIVES, MIN_DAYS = 10, 5            # the project cohort floor (m435_tte MIN_N, MIN_DAYS)


class WinterAtSupport(RuntimeError):
    """Drives dated December to February meet the support floor: no automatic wording (spec M625 R2); the Director decides."""


def _dates(dates):
    out = []
    for d in dates:
        if d is None:
            continue
        s = str(d)[:10]
        try:
            out.append(_dt.date.fromisoformat(s))
        except ValueError:
            continue
    return out


def month_span(dates):
    ds = _dates(dates)
    if not ds:
        return None
    a, b = min(ds), max(ds)
    if (a.year, a.month) == (b.year, b.month):
        return "%s %d" % (MONTHS[a.month - 1], a.year)
    if a.year == b.year:
        return "%s-%s %d" % (MONTHS[a.month - 1], MONTHS[b.month - 1], a.year)
    return "%s %d-%s %d" % (MONTHS[a.month - 1], a.year, MONTHS[b.month - 1], b.year)


def _fmt(x, decimals):
    q = Decimal(str(x)).quantize(Decimal(1) if decimals == 0 else Decimal("0.1"), rounding=ROUND_HALF_UP)
    if q == 0:
        q = abs(q)                                           # -0 / -0.0 -> 0
    return str(q) if decimals else str(int(q))


def ambient_span(values):
    v = []
    for x in values:
        try:
            f = float(x)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            v.append(f)
    if not v:
        return None
    lo, hi = min(v), max(v)
    frac = (lo != int(lo)) or (hi != int(hi))
    d = 1 if frac else 0
    return "ambient %s to %s C" % (_fmt(lo, d), _fmt(hi, d))


def winter_clause(dates, min_drives=MIN_DRIVES, min_days=MIN_DAYS):
    """Rule R2: winter = December to February. 0 drives dated in it -> unobserved; some below the floor -> observed, below support; at or above the floor -> raise."""
    ds = [d for d in _dates(dates) if d.month in WINTER_MONTHS]
    n, days = len(ds), len({d for d in ds})
    if n == 0:
        return "winter (December to February) stays unobserved"
    if n >= min_drives and days >= min_days:
        raise WinterAtSupport("%d drives on %d days dated December to February meet the support floor (%d drives, %d days): the Director decides the wording" % (n, days, min_drives, min_days))
    return "December to February observed on %d drives on %d days, below the support floor" % (n, days)
