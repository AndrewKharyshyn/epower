#!/usr/bin/env python3
"""M485 (analyses/M485_spec.md Rev 3, pre-registered): pipeline-computed observation-window and cutoff-sensitivity caveat for the RELEASED cell-spread slope. Additive: writes ONLY the payload block
summary_arrays.json['windowCaveat'] (+ its artifact stamp). The released estimator is imported and called, never reimplemented (degradation_trends._prep / _covars_present / _cluster_ols: cluster-robust
OLS of cell_spread_loaded_p95_mv on months + T_pack_mean_avg + peak_I_discharge, canonical-clean, day clusters, CR1 with the t(G-1) reference). Cumulative refits at month-end cutoffs are nested and reuse
almost all observations: the counts are descriptive, not independent evidence, and make no claim beyond the released interval.
Rules (frozen in the spec): cutoffs = last calendar day of every month from the month of the first eligible day up to (excluding) the month of the last eligible day, plus the last eligible day; a row needs
>= 20 eligible drives on >= 5 days and the pinned formula (a covariate present in under half of the subset would silently change the formula: such a row is not evaluable); a month-end with no new eligible drive
is noNewData and left out of m, k, s; the leave-last-k rows (k = 8, 12, 16) and the daily-grid counts are separate and outside the counts; the final row must reconcile with the released model (hard stop).
Usage: python tools/window_caveat.py [--dry-run]"""
import copy, datetime, hashlib, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p_ in (ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import degradation_trends as DT          # noqa: E402

METHOD_VERSION = 1
YCOL, ICOL = "cell_spread_loaded_p95_mv", "peak_I_discharge"
MIN_DRIVES, MIN_DAYS = 20, 5
LEAVE_LAST_KS = (8, 12, 16)          # Rev 3 (Director 2026-10-23): all reported whatever they show; 12 and 16 were chosen after the Rev 2 result was seen
FORMULA = "y ~ months + T + I"
ALLOWED = ["/windowCaveat", "/_artifactStamps/windowCaveat"]
STATEMENT = ("Descriptive: cumulative refits of the released cell-spread estimator at calendar month-end cutoffs. The refits are nested and reuse almost all observations, so the counts are not independent evidence; "
             "no claim beyond the released interval.")


# ------------------------------------------------------------------------------------------------ the released fit on a subset
def fit_subset(dm_sub):
    """(row fields, None) for an evaluable subset, (None, reason) otherwise. Uses the released functions; the formula is pinned to months + T + I."""
    d = DT._prep(dm_sub, YCOL, icol=ICOL)
    if d.empty or d.shape[0] < 8:
        return None, "support"
    use = DT._covars_present(d, ("T", "I"))
    if use != ["T", "I"]:
        return None, "covariate support"
    dd = d.dropna(subset=use)
    if dd.shape[0] < MIN_DRIVES or dd["day"].nunique() < MIN_DAYS:
        return None, "support"
    co = DT._cluster_ols(d, covars=("T", "I"))
    if co.get("formula") != "y ~ months + T + I":
        return None, "covariate support"
    return co, None


def eligible_days(dm):
    """Complete-case eligible rows of the released fit: (frame with 'date' normalised to a calendar day, sorted unique days)."""
    d = DT._prep(dm, YCOL, icol=ICOL)
    d = d.dropna(subset=["T", "I"]).copy()
    d["day_dt"] = pd.to_datetime(d["date"]).dt.normalize()
    return d, sorted(d["day_dt"].unique())


def cutoffs_for(first_day, last_day):
    """Last calendar day of every month from the month of first_day up to, excluding, the month of last_day, plus last_day (once)."""
    out = []
    m = pd.Period(first_day, "M")
    end_m = pd.Period(last_day, "M")
    while m < end_m:
        out.append(m.end_time.normalize())
        m += 1
    out.append(pd.Timestamp(last_day))
    return out


def _sub(dm, cutoff):
    return dm[pd.to_datetime(dm["date"]).dt.normalize() <= pd.Timestamp(cutoff)]


def _row_from(co, cutoff, status="ok"):
    lo, hi = co["ci95"]
    sl = co["slope"]
    return {"cutoff": str(pd.Timestamp(cutoff).date()), "status": status, "nDrives": int(co["nObs"]), "nDays": int(co["nDays"]), "slope": sl, "se": co["se"], "ci95": [lo, hi],
            "excludesZero": bool(lo > 0 or hi < 0), "sign": int(np.sign(sl))}


def summarize_rows(rows, last_day):
    """Pure: the derived counts over the evaluable ('ok') rows only (noNewData, notEvaluable and the leave-last-k rows are outside); an exactly-zero estimate (sign 0) never counts as a sign change."""
    ok = [r for r in rows if r["status"] == "ok"]
    signs = [r["sign"] for r in ok]
    first_ex = next((r["cutoff"] for r in ok if r["excludesZero"]), None)
    return {"nEvaluableCutoffs": len(ok), "nIntervalExcludesZero": int(sum(bool(r["excludesZero"]) for r in ok)),
            "nSignChanges": int(sum(1 for a, b in zip(signs, signs[1:]) if a * b < 0)),
            "firstCutoffExcludingZero": first_ex, "firstCutoffExcludingZeroIsLastDay": bool(first_ex is not None and first_ex == last_day)}


def daily_counts(dm, days):
    """Counts over refits at every distinct eligible day that meets the support rule and the pinned formula (each eligible day is new data): evaluable fits, intervals excluding zero (positive / negative), sign changes."""
    fits = []
    for d in days:
        co, _ = fit_subset(_sub(dm, pd.Timestamp(d)))
        if co is not None:
            fits.append(co)
    signs = [int(np.sign(c["slope"])) for c in fits]
    lo_hi = [tuple(c["ci95"]) for c in fits]
    return {"nEvaluable": len(fits), "nExcludeZeroPos": int(sum(lo > 0 for lo, hi in lo_hi)), "nExcludeZeroNeg": int(sum(hi < 0 for lo, hi in lo_hi)),
            "nSignChanges": int(sum(1 for a, b in zip(signs, signs[1:]) if a * b < 0))}


def build(dm):
    """The windowCaveat block from a master frame."""
    ed, days = eligible_days(dm)
    if not days:
        raise SystemExit("STOP: no eligible rows for the released cell-spread fit")
    first, last = pd.Timestamp(days[0]), pd.Timestamp(days[-1])
    rows, prev_n = [], 0
    for c in cutoffs_for(first, last):
        n_elig = int((ed["day_dt"] <= c).sum())
        if n_elig == prev_n:
            rows.append({"cutoff": str(c.date()), "status": "noNewData", "nDrives": n_elig})
            continue
        prev_n = n_elig
        co, why = fit_subset(_sub(dm, c))
        rows.append(_row_from(co, c) if co is not None else {"cutoff": str(c.date()), "status": "notEvaluable", "reason": why, "nDrives": n_elig,
                                                                 "nDays": int(ed.loc[ed["day_dt"] <= c, "day_dt"].nunique())})
    llk = []
    for k in LEAVE_LAST_KS:
        keep = days[:-k] if len(days) > k else []
        row = {"k": int(k)}
        if keep:
            co, why = fit_subset(_sub(dm, pd.Timestamp(keep[-1])))
            row.update(_row_from(co, keep[-1]) if co is not None else {"cutoff": str(pd.Timestamp(keep[-1]).date()), "status": "notEvaluable", "reason": why})
        else:
            row.update({"status": "notEvaluable", "reason": "support"})
        llk.append(row)
    daily = daily_counts(dm, days)
    n_d, n_days = int(len(ed)), int(ed["day_dt"].nunique())
    span_days = int((last - first).days)
    return {
        "methodVersion": METHOD_VERSION, "quantity": "cell-spread slope (released estimator)", "formula": FORMULA,
        "estimator": "degradation_trends._cluster_ols: cluster-robust OLS, day clusters, CR1, interval t(G-1); formula pinned; a cutoff whose fitted formula would differ is not evaluable",
        "window": {"firstDay": str(first.date()), "lastDay": str(last.date()), "spanDays": span_days, "spanMonths": round(span_days / DT.MONTH_DAYS, 1), "nDrives": n_d, "nDays": n_days,
                   "resistanceWindowKey": "powerFade.windowMo"},
        "rule": {"cutoffs": "last calendar day of each month from the first eligible month up to, excluding, the last eligible month, plus the last eligible day", "minDrives": MIN_DRIVES, "minDays": MIN_DAYS,
                 "leaveLastKs": list(LEAVE_LAST_KS), "leaveLastNote": "the 8 is the number used by tools/record_spread_fit.py (its leave-days-out check); that rule refits a first stage on the keep set, a different object; 12 and 16 were chosen after the first result was seen (data-informed, all reported)",
                 "countsExclude": ["noNewData", "notEvaluable", "leaveLastK", "daily"], "signRule": "an exactly-zero estimate has sign 0 and counts as no change",
                 "daily": "a refit at every distinct eligible day meeting the support rule and the pinned formula; counts only"},
        "cutoffs": rows, "leaveLastK": llk, "daily": daily,
        "summary": summarize_rows(rows, str(last.date())),
        "statement": STATEMENT,
    }


def lastk_clause(blk):
    """Rev 3 (c): K = the smallest k of the evaluable leaveLastK rows whose interval includes zero; if none includes zero, list the evaluable k; no evaluable row: no clause."""
    rows = [r for r in blk.get("leaveLastK", []) if r.get("status") == "ok"]
    if not rows:
        return ""
    inc = [r["k"] for r in rows if not r["excludesZero"]]
    if inc:
        return "the interval includes zero when the last %d days are removed" % min(inc)
    ks = [str(r["k"]) for r in rows]
    return "the interval excludes zero after removal of the last %s days" % (ks[0] if len(ks) == 1 else ", ".join(ks[:-1]) + " and " + ks[-1])


def sentence(blk):
    """The dashboard sentence, generated from the block only (mirrored in the JSX; the semantic gate compares them). Contains none of the language-gate forbidden words."""
    w, s, dl = blk["window"], blk["summary"], blk["daily"]
    parts = ["Cell-spread observation window %s months (%d drives on %d days). Cumulative refits of the released estimator at month-end cutoffs: the interval excluded zero at %d of %d cutoffs and the point estimate "
             "changed sign %d times" % (("%.1f" % w["spanMonths"]), w["nDrives"], w["nDays"], s["nIntervalExcludesZero"], s["nEvaluableCutoffs"], s["nSignChanges"]),
             "month-end cutoffs are one fixed grid (at daily cutoffs the interval excluded zero at %d of %d, %d positive, %d negative)"
             % (dl["nExcludeZeroPos"] + dl["nExcludeZeroNeg"], dl["nEvaluable"], dl["nExcludeZeroPos"], dl["nExcludeZeroNeg"])]
    cl = lastk_clause(blk)
    if cl:
        parts.append(cl)
    parts.append("the refits are nested, reuse almost all observations and are not independent replication")
    return "; ".join(parts) + "; no claim beyond the released interval."


def reconcile(blk, released):
    """Hard stop: the final cutoff row equals the released cluster-robust OLS (slope, interval, nObs, nDays)."""
    last = [r for r in blk["cutoffs"] if r["cutoff"] == blk["window"]["lastDay"]]
    if not last or last[-1]["status"] != "ok":
        raise SystemExit("STOP: the final cutoff row is not evaluable")
    r = last[-1]
    if (r["slope"], r["ci95"], r["nDrives"], r["nDays"]) != (released["slope"], list(released["ci95"]), released["nObs"], released["nDays"]):
        raise SystemExit("STOP: the final cutoff row does not equal the released cell-spread fit: %s vs %s" % ((r["slope"], r["ci95"], r["nDrives"], r["nDays"]),
                                                                                                          (released["slope"], released["ci95"], released["nObs"], released["nDays"])))
    return True


# ------------------------------------------------------------------------------------------------ additive splice
def _paths(a, b, p=""):
    if isinstance(a, dict) and isinstance(b, dict):
        return [x for k in sorted(set(a) | set(b)) for x in (_paths(a.get(k), b.get(k), "%s/%s" % (p, k)) if (k in a and k in b) else ["%s/%s" % (p, k)])]
    return [] if json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) else [p]


def splice(A, blk, master_md5="", now=None):
    new = copy.deepcopy(A)
    new["windowCaveat"] = blk
    old = (A.get("_artifactStamps") or {}).get("windowCaveat")
    coherent = old and old.get("includedInReleaseAt") == old.get("computedAt") == old.get("generatedAt")      # M419: the three timestamps of an additive stamp are one instant
    if old and coherent and A.get("windowCaveat") == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"]["windowCaveat"] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M485: derived by tools/window_caveat.py from drive_master.csv; descriptive cumulative refits of the released cell-spread estimator (analyses/M485_spec.md)",
                  upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
        new["_artifactStamps"]["windowCaveat"] = st
    ch = _paths(A, new)
    return new, ch, [c for c in ch if not any(c == a_ or c.startswith(a_ + "/") for a_ in ALLOWED)]


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A0 = json.loads(raw)
    blk = _clean(build(dm))
    reconcile(blk, A0["degradationTrends"]["cellSpread"]["clusterRobustOLS"])
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    new, changed, bad = splice(A0, blk, md5)
    print(json.dumps({"nChanged": len(changed), "outsideAllowList": bad, "sentence": sentence(blk)}))
    if bad:
        return 1
    if "--dry-run" not in argv and changed:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
