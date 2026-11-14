#!/usr/bin/env python3
"""M658 (N-06; spec analyses/M657_spec.md Rev 1.2 (Rev 1.1 Director review R1-R11), owner decisions O1/O2): map of the BMS-reported possible power (input and output) against pack temperature and SoC.

Additive top-level payload block `bmsPowerMap` (+ artifact stamp). Per-drive sufficient statistics are cached by the raw-file sha256 and the extractor version (`bms_map_cache/`, git-ignored);
aggregation never rereads raw. Wording: BMS-reported possible power, logged / app-calculated; descriptive, no capability or degradation claim.

Per drive and direction the cache holds, per cell (5 C pack-temperature bin anchored at 0 C x SoC band), the time-weighted histogram of the reported value (rounded to 0.05 kW), the seconds and
sample count; plus the saturation facts (exact-maximum run, values near the maximum), the I x V check counts and the dropped-sample counts. Time weight = min(gap to the next channel sample, 15 s); the last
sample carries the drive's median gap (<= 15 s). A sample needs a pack temperature (mean of the available probes T1..T4, nearest valid within 5 s) and a SoC (nearest valid within 5 s).

Usage: python tools/n06_bms_power_map.py [--dry-run] [--raw-dir DIR] [--out PATH]      (writes ONLY /bmsPowerMap and /_artifactStamps/bmsPowerMap of summary_arrays.json)
Library: extract_drive(csv_bytes, filename) -> dict, aggregate(stats_by_file, meta) -> block, soc_band(v), t_bin(v)."""
import copy, datetime, hashlib, io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import numpy as np
import pandas as pd

EXTRACTOR_VERSION = "n06-r3"
CACHE_DIR = os.path.join(ROOT, "bms_map_cache")
SPEC = "analyses/M657_spec.md"
SOC_EDGES = [40, 50, 55, 60, 63, 66, 69, 72, 100]
SOC_LABELS = ["<40"] + ["%d-%d" % (a, b) for a, b in zip(SOC_EDGES[:-1], SOC_EDGES[1:])]
MAX_FLAG_KW = 63.70
HOLD_S = 15.0
NEAR_S = 5.0
Q = 0.05                    # histogram quantisation (kW); the logged grids are 0.1 kW (hp era) and 0.05 kW (kW era)
GRID_STEP = {"hp": 0.1, "kW": 0.05}
FLOOR_DRIVES, FLOOR_DAYS, FLOOR_S, ESS_SUPPORTED = 10, 5, 600.0, 10.0
NB, SEED = 4000, 42
MIN_COVERAGE = 0.25
SOC_LADDER = ("55-60", "60-63", "63-66")      # reading ladder band: SoC 55 to 66 %


def t_bin(v):
    return int(np.floor(v / 5.0) * 5)


def soc_band(v):
    if v < SOC_EDGES[0]:
        return "<40"
    for a, b in zip(SOC_EDGES[:-1], SOC_EDGES[1:]):
        if a <= v < b or (b == 100 and a <= v <= 100):
            return "%d-%d" % (a, b)
    return None


def _nearest(base_t, other, tol_s):
    """Value of `other` (frame t, v) nearest in time to each base_t within tol_s, else NaN."""
    o = other.sort_values("t")
    b = pd.DataFrame({"t": base_t}).reset_index()
    m = pd.merge_asof(b.sort_values("t"), o.rename(columns={"v": "_v"}), on="t", direction="nearest", tolerance=pd.Timedelta(seconds=tol_s)).sort_values("index")
    return m["_v"].to_numpy(float)


def extract_drive(csv_bytes, filename):
    """Per-drive sufficient statistics (JSON-able), or None when the file carries neither possible-power channel."""
    import compute_summary_arrays as C
    import compute_drive_summary_v6 as v6
    head = pd.read_csv(io.BytesIO(csv_bytes), nrows=0).columns
    if not any(c in head for pair in C._HDRM_PP_COLS.values() for c in pair):
        return None
    df_raw = pd.read_csv(io.BytesIO(csv_bytes), low_memory=False)
    df = df_raw.rename(columns={k: v for k, v in v6.COL_MAP.items() if k in df_raw.columns})
    t = C._ft(df["time"], mixed=True)
    # M658 Rev 1.2 (blind-audit reconciliation): the spec text is applied literally. Pack temperature = mean over the available probes of the nearest valid reading (-40..90 C) within 5 s of the
    # possible-power sample; SoC = the nearest valid logged reading (0..100 %) within 5 s (the pipeline's SoC spike filter is not applied); I and V each nearest within 2 s.
    def ser(col, lo=None, hi=None, absmax=None):
        if col not in df.columns:
            return None
        x = pd.to_numeric(df[col], errors="coerce")
        m = x.notna()
        if lo is not None:
            m &= x >= lo
        if hi is not None:
            m &= x <= hi
        if absmax is not None:
            m &= x.abs() < absmax
        if not m.any():
            return None
        return pd.DataFrame({"t": t[m].values, "v": x[m].astype(float).values}).sort_values("t").reset_index(drop=True)
    tser = [ser(c, -40, 90) for c in ("T1", "T2", "T3", "T4")]
    tser = [s for s in tser if s is not None]
    soc = ser("soc", 0, 100)
    Iser, Vser = ser("I", absmax=900), ser("V", 200, 450)
    out = {"file": filename, "dir": {}}
    for dname, direction in (("input", 0), ("output", 1)):
        s, era = C._hdrm_pp_series(df_raw, direction)
        if s is None:
            continue
        pp = pd.DataFrame({"t": t, "pp": s}).dropna().sort_values("t").reset_index(drop=True)
        if not len(pp):
            continue
        gaps = pp["t"].diff().dt.total_seconds().to_numpy()
        gnext = np.append(gaps[1:], np.nan)
        med = float(np.nanmedian(gaps)) if np.isfinite(gaps[1:]).any() else 1.0
        w = np.where(np.isfinite(gnext), np.minimum(gnext, HOLD_S), min(med, HOLD_S))
        pv = pp["pp"].to_numpy(float)
        tp = np.nanmean(np.vstack([_nearest(pp["t"], s, NEAR_S) for s in tser]), axis=0) if tser else np.full(len(pp), np.nan)
        sv = _nearest(pp["t"], soc, NEAR_S) if soc is not None else np.full(len(pp), np.nan)
        ok = np.isfinite(tp) & np.isfinite(sv)
        d = {"era": era, "nSamples": int(len(pp)), "nDropped": int((~ok).sum()), "droppedSeconds": float(w[~ok].sum()), "seconds": float(w.sum()),
             "nOnGrid": int((np.abs(pv / GRID_STEP["kW"] - np.round(pv / GRID_STEP["kW"])) * GRID_STEP["kW"] <= 0.005).sum()), "cells": {}, "medianGapS": med}
        # saturation facts (all samples, before the temperature / SoC requirement)
        vmax = float(pv.max()); at_max = pv >= vmax - 0.005
        run = best = 0.0
        for a, ww in zip(at_max, w):
            run = run + ww if a else 0.0
            best = max(best, run)
        d["maxValue"] = round(vmax, 3); d["secondsAtDriveMax"] = float(w[at_max].sum()); d["longestRunAtDriveMaxS"] = round(best, 2)
        d["secondsAtOrAboveFlag"] = float(w[pv >= MAX_FLAG_KW].sum())
        d["nearMaxValues"] = sorted({round(float(x) / Q) * Q for x in pv if vmax - 1.0 <= x <= vmax})[:200]
        for i in np.nonzero(ok)[0]:
            key = "%d|%s" % (t_bin(tp[i]), soc_band(sv[i]))
            c = d["cells"].setdefault(key, {"s": 0.0, "n": 0, "h": {}})
            c["s"] += float(w[i]); c["n"] += 1
            r = "%.2f" % (round(pv[i] / Q) * Q)
            c["h"][r] = c["h"].get(r, 0.0) + float(w[i])
        # I x V check (input only): weight where the logged charge power exceeds the reported limit, by whether the limit is at the logged maximum
        if direction == 0 and Iser is not None and Vser is not None:
            pe = _nearest(pp["t"], Iser, 2.0) * _nearest(pp["t"], Vser, 2.0) / 1000.0
            chg = np.isfinite(pe) & (pe > 0.1)
            atm = pv >= MAX_FLAG_KW
            d["ivCheck"] = {"atMax": {"s": float(w[chg & atm].sum()), "exceed": float(w[chg & atm & (pe > pv)].sum())},
                            "belowMax": {"s": float(w[chg & ~atm].sum()), "exceed": float(w[chg & ~atm & (pe > pv)].sum())},
                            "chargeAbove50kWSeconds": float(w[np.isfinite(pe) & (pe > 50.0)].sum()), "pairedSeconds": float(w[np.isfinite(pe)].sum())}
        out["dir"][dname] = d
    return out if out["dir"] else None


# ------------------------------------------------------------------------------------------------ aggregation
def _hist_arrays(cell_list, grid):
    """cell_list: [(day, driveIndex, hist dict)] -> (days, matrix days x grid of weights)"""
    days = sorted({d for d, _, _ in cell_list})
    di = {d: i for i, d in enumerate(days)}
    M = np.zeros((len(days), len(grid)))
    gi = {g: i for i, g in enumerate(grid)}
    for d, _, h in cell_list:
        for k, wv in h.items():
            M[di[d], gi[k]] += wv
    return days, M


def _wq(vals, w, q):
    """time-weighted quantile (lower interpolation on the cumulative weight)"""
    tot = w.sum()
    if tot <= 0:
        return None
    c = np.cumsum(w) / tot
    return float(vals[min(int(np.searchsorted(c, q - 1e-12)), len(vals) - 1)])


def _stats_from_hist(h, vals, below_mask):
    tot = h.sum()
    if tot <= 0:
        return None
    mx = float(h[~below_mask].sum() / tot)
    out = {"median": _wq(vals, h, 0.5), "p5": _wq(vals, h, 0.05), "p95": _wq(vals, h, 0.95), "maxShare": mx}
    hb = np.where(below_mask, h, 0.0)
    out["belowMaxMedian"] = _wq(vals, hb, 0.5) if hb.sum() > 0 else None
    out["belowMaxP5"] = _wq(vals, hb, 0.05) if hb.sum() > 0 else None
    return out


def _boot(M, vals, below_mask, drive_med_by_day, nb=NB, seed=SEED):
    """Day-clustered percentile bootstrap resampling the cell's OWN days. M: days x grid weights. drive_med_by_day: list (per day) of per-drive medians (median-of-medians sensitivity)."""
    D = M.shape[0]
    rng = np.random.default_rng(seed)
    keys = ("median", "p5", "p95", "maxShare", "belowMaxMedian", "belowMaxP5")
    acc = {k: [] for k in keys}
    mom = []
    dropped = 0
    for _ in range(nb):
        idx = rng.integers(0, D, D)
        h = M[idx].sum(axis=0)
        s = _stats_from_hist(h, vals, below_mask)
        if s is None:
            dropped += 1
            continue
        for k in keys:
            if s[k] is not None:
                acc[k].append(s[k])
        allm = [m for i in idx for m in drive_med_by_day[i]]
        if allm:
            mom.append(float(np.median(allm)))
    ci = {k: ([round(float(np.percentile(v, 2.5)), 3), round(float(np.percentile(v, 97.5)), 3)] if len(v) > 0.5 * nb else None) for k, v in acc.items()}
    ci["medianOfMedians"] = [round(float(np.percentile(mom, 2.5)), 3), round(float(np.percentile(mom, 97.5)), 3)] if mom else None
    return ci, dropped / nb


def _ess_days(day_secs):
    s = np.asarray(day_secs, float); s = s[s > 0]
    return float(s.sum() ** 2 / (s ** 2).sum()) if len(s) else 0.0


def _fmt(x, nd=3):
    return None if x is None else round(float(x), nd)


def _cell_record(parts, vals, below_mask, era):
    """parts: [(day, drive, seconds, hist)] for one cell -> record with status and (if shown) statistics and intervals"""
    drives = {p[1] for p in parts}; days = sorted({p[0] for p in parts})
    secs = sum(p[2] for p in parts)
    day_secs = {}
    for d, _, s, _h in parts:
        day_secs[d] = day_secs.get(d, 0.0) + s
    ess = _ess_days(list(day_secs.values()))
    rec = {"nDrives": len(drives), "nDays": len(days), "seconds": round(secs, 1), "essDays": round(ess, 2)}
    if len(drives) < FLOOR_DRIVES or len(days) < FLOOR_DAYS or secs < FLOOR_S:
        why = [n for n, bad in (("fewer than %d drives" % FLOOR_DRIVES, len(drives) < FLOOR_DRIVES), ("fewer than %d days" % FLOOR_DAYS, len(days) < FLOOR_DAYS), ("fewer than %d s" % FLOOR_S, secs < FLOOR_S)) if bad]
        rec.update(status="not shown", reason="; ".join(why))
        return rec
    rec["status"] = "supported" if ess >= ESS_SUPPORTED else "exploratory"
    dd, M = _hist_arrays([(p[0], p[1], p[3]) for p in parts], [("%.2f" % v) for v in vals])
    h = M.sum(axis=0)
    st = _stats_from_hist(h, vals, below_mask)
    meds = {}
    for d, drv, _s, hh in parts:
        meds.setdefault((d, drv), {})
        for k, wv in hh.items():
            meds[(d, drv)][k] = meds[(d, drv)].get(k, 0.0) + wv
    by_day = [[] for _ in dd]
    pm = []
    for (d, drv), hh in meds.items():
        a = np.zeros(len(vals))
        for k, wv in hh.items():
            a[int(round((float(k) - vals[0]) / Q))] += wv
        m = _wq(vals, a, 0.5)
        if m is not None:
            by_day[dd.index(d)].append(m); pm.append(m)
    ci, drop = _boot(M, vals, below_mask, by_day)
    mom = float(np.median(pm)) if pm else None
    at_max = lambda v: None if v is None else (">=%.2f (at the logged maximum)" % MAX_FLAG_KW if v >= MAX_FLAG_KW else None)
    rec.update({"median": _fmt(st["median"]), "p5": _fmt(st["p5"]), "p95": _fmt(st["p95"]), "maxShare": _fmt(st["maxShare"], 4), "belowMaxMedian": _fmt(st["belowMaxMedian"]), "belowMaxP5": _fmt(st["belowMaxP5"]),
                "medianOfMedians": _fmt(mom), "ci95": ci, "bootDropRate": round(drop, 4),
                "medianAtLoggedMaximum": st["median"] is not None and st["median"] >= MAX_FLAG_KW, "p95AtLoggedMaximum": st["p95"] is not None and st["p95"] >= MAX_FLAG_KW})
    deg = [k for k in ("median", "p5", "p95", "belowMaxMedian", "belowMaxP5") if ci.get(k) and ci[k][0] == ci[k][1]]
    rec["degenerateIntervals"] = deg
    if drop > 0.01:
        rec["status"] = "not estimable"; rec["reason"] = "bootstrap drop rate %.3f exceeds 0.01" % drop
    g = GRID_STEP[era]
    mm = ci.get("medianOfMedians")
    if mm and ci.get("median") and rec["median"] is not None and mom is not None:
        hw = max((ci["median"][1] - ci["median"][0]) / 2.0, (mm[1] - mm[0]) / 2.0, g)
        rec["estimatorDependent"] = bool(abs(rec["median"] - mom) > hw)
    return rec


def _ladder(cells_by_key, tbins, vals_ci_key):
    return None


def aggregate(stats, meta, nb=NB):
    """stats: {file: extract_drive output}; meta: {file: {'date': 'YYYY-MM-DD', 'period': float|None}} for the canonical-clean drives to analyse. -> payload block."""
    import regime_reader as RR
    files = [f for f in sorted(stats) if f in meta]
    block = {"spec": SPEC, "specVersion": "Rev 1.2", "extractor": EXTRACTOR_VERSION, "methodVersion": "M658-r1",
             "label": "BMS-reported possible power (logged / app-calculated by the Car Scanner ELM OBD2 app) against pack temperature and SoC; descriptive, exploratory, no capability, degradation or causal-temperature claim",
             "binning": {"packTempC": "5 C bins, edges at multiples of 5 C anchored at 0 C", "socBands": SOC_LABELS, "socNote": "display bands (owner decision (b) 2026-10-14), not identified BMS thresholds"},
             "rules": {"hold_s": HOLD_S, "nearestValid_s": NEAR_S, "quantisationKw": Q, "loggedMaximumFlagKw": MAX_FLAG_KW, "floors": {"drives": FLOOR_DRIVES, "days": FLOOR_DAYS, "seconds": FLOOR_S, "essDaysSupported": ESS_SUPPORTED},
                       "bootstrap": {"cluster": "calendar day, the cell's own days", "draws": nb, "seed": SEED, "interval": "95% percentile"}, "minCoverage": MIN_COVERAGE},
             "preSeen": "M627 facts (input time at or above 63.70 kW 70 to 91 % by era, output limit not constant, utilisation maximum 1.171) were seen before the pre-registration; 3 of the 432 drives with the channel have no usable I x V pairing in M627 and are not analysed there",
             "eras": {}}
    for era in ("hp", "kW"):
        block["eras"][era] = {}
    block["reading"] = ["BMS-reported possible power (logged / app-calculated); the input channel covers generator charging and regeneration and does not separate them",
                        "values at or above 63.70 kW are printed as at the logged maximum; zero-width intervals are degenerate, not precise",
                        "a cold-bin value is a cell value only; no ordered relation below the warm bins is established for the below-maximum median; the 5 C bin is exploratory",
                        "an ordering of the logged-maximum share is consistent with a saturated byte hiding a warm-bin rise and with a fixed cap; it identifies neither",
                        "no contrast is drawn between the two logger eras or between temperature classes; era and season are confounded; the below-maximum statistics are selected on the outcome",
                        "dropped samples (missing pack temperature or SoC) are not random; the cadence-regime sensitivity pools SoC and is not like-for-like"]
    block["disclosures"] = ["Rev 1.1 sample rules were ambiguous: the first blind audit pass did not reproduce the ladder; the Rev 1.2 rules (per-probe nearest reading within 5 s, SoC without the spike filter, I and V nearest within 2 s) were written after a result had been seen and the re-audit reproduced every audited field",
                            "output direction: the logged-maximum marker, not a ceiling (owner decision O1)", "no article use without the Opus audit and Andrii's sign-off"]
    block["notIndependentlyReproduced"] = ["bootstrap intervals", "longestRunAtMaximumS"]
    # unit gate per era (M626/M627): >= 99.9 % of samples on the 0.05 kW grid in the kW era; hp-era samples are converted values and are gated by the same share on the 0.1 kW grid after rounding
    fails = []
    for dname in ("input", "output"):
        for era in ("hp", "kW"):
            parts_f = [f for f in files if dname in stats[f]["dir"] and stats[f]["dir"][dname]["era"] == era]
            if not parts_f:
                continue
            nsamp = sum(stats[f]["dir"][dname]["nSamples"] for f in parts_f)
            ev = {"drives": len(parts_f), "samples": nsamp}
            days = sorted({meta[f]["date"] for f in parts_f})
            ev["days"] = len(days); ev["dateFrom"], ev["dateTo"] = days[0], days[-1]
            # cells
            cell_parts = {}
            vals_set = set()
            for f in parts_f:
                d = stats[f]["dir"][dname]
                for key, c in d["cells"].items():
                    cell_parts.setdefault(key, []).append((meta[f]["date"], f, c["s"], c["h"]))
                    vals_set.update(float(k) for k in c["h"])
            vals = np.arange(round(min(vals_set) / Q) * Q, round(max(vals_set) / Q) * Q + Q / 2, Q) if vals_set else np.array([0.0])
            below = vals < MAX_FLAG_KW - 1e-9
            total_s = sum(stats[f]["dir"][dname]["seconds"] for f in parts_f)
            dropped_s = sum(stats[f]["dir"][dname]["droppedSeconds"] for f in parts_f)
            ev["secondsTotal"] = round(total_s, 1); ev["droppedForMissingTemperatureOrSocSeconds"] = round(dropped_s, 1)
            ev["droppedShare"] = round(dropped_s / total_s, 4) if total_s else None
            cells = {}
            for key in sorted(cell_parts, key=lambda k: (int(k.split("|")[0]), SOC_LABELS.index(k.split("|")[1]))):
                cells[key] = _cell_record(cell_parts[key], vals, below, era)
            ev["cells"] = {k: {**v} for k, v in cells.items()}
            shown_s = sum(v["seconds"] for v in cells.values() if v["status"] == "supported")
            ev["supportedSecondsShare"] = round(shown_s / max(total_s - dropped_s, 1e-9), 4)
            if ev["supportedSecondsShare"] < MIN_COVERAGE:
                ev["coverageFalsification"] = "supported cells cover less than %.0f %% of the channel time of the analysed drives: no map is shown for this era and direction" % (100 * MIN_COVERAGE)
            # reading ladder on the SoC 55-66 band pooled across its three bands (own cell record, same rules)
            lad = {}
            tbs = sorted({int(k.split("|")[0]) for k in cell_parts})
            for tb in tbs:
                pr = []
                for sb in SOC_LADDER:
                    pr += cell_parts.get("%d|%s" % (tb, sb), [])
                lad[str(tb)] = _cell_record(pr, vals, below, era) if pr else {"status": "not shown", "reason": "no samples", "nDrives": 0, "nDays": 0, "seconds": 0.0, "essDays": 0.0}
            ev["ladderSoc55to66"] = lad
            sup = [tb for tb in tbs if lad[str(tb)]["status"] == "supported"]
            contiguous = bool(sup) and sup == list(range(min(sup), max(sup) + 5, 5))
            ev["supportedPackTempOuterBinEdgesC"] = [min(sup), max(sup) + 5] if sup else None
            ev["supportedPackTempBinsC"] = sup
            ev["supportedBinsContiguous"] = contiguous
            mono = {}
            for qn, getter in (("belowMaxMedian", lambda r: r.get("belowMaxMedian")), ("maxShare", lambda r: r.get("maxShare"))):
                if len(sup) >= 3 and contiguous and all(getter(lad[str(b)]) is not None for b in sup):
                    v = [getter(lad[str(b)]) for b in sup]
                    inc = all(b > a for a, b in zip(v, v[1:])); dec = all(b < a for a, b in zip(v, v[1:]))
                    ci_lo, ci_hi = lad[str(sup[0])]["ci95"].get(qn), lad[str(sup[-1])]["ci95"].get(qn)
                    sep = bool(ci_lo and ci_hi and (ci_lo[1] < ci_hi[0] or ci_hi[1] < ci_lo[0]))
                    nm = {"belowMaxMedian": "below-maximum median", "maxShare": "logged-maximum share"}[qn]
                    binsTxt = ", ".join(str(b) for b in sup) + " C, lower bin edges"
                    pre = "%s era, %s direction, SoC 55-66 %%: " % (era, dname)
                    mono[qn] = (pre + nm + " is higher in each warmer supported bin (" + binsTxt + "); descriptive, not a temperature effect") if (inc and sep) else (
                        (pre + nm + " is lower in each warmer supported bin (" + binsTxt + "); descriptive, not a temperature effect") if (dec and sep) else (pre + nm + ": no ordered relation is established"))
                else:
                    mono[qn] = "no ordered relation is established (fewer than three contiguous supported bins or an undefined value)"
            ev["monotone"] = mono
            cold = [tb for tb in tbs if tb < 10]
            ev["winter"] = {"coldestSupportedBinC": (min(sup) if sup else None), "coldBinsBelow10C": {str(tb): {k: lad[str(tb)][k] for k in ("status", "nDrives", "nDays", "essDays", "seconds")} for tb in cold},
                            "rule": "a statement about the logged input possible power (generator charging and regeneration are not separated by the channel) is allowed only for supported bins; below that: not observed at this support"}
            # saturation descriptions (input only) and the I x V check
            if dname == "input":
                mxv = max(stats[f]["dir"][dname]["maxValue"] for f in parts_f)
                at = sum(stats[f]["dir"][dname]["secondsAtOrAboveFlag"] for f in parts_f)
                sat = {"eraMaximumKw": round(mxv, 3), "shareOfChannelTimeAtOrAboveLoggedMaximumFlag": round(at / total_s, 4) if total_s else None, "shareBasis": "all channel samples of the analysed drives (before the temperature / SoC requirement); the flag is >= %.2f kW, so both 63.75 and the hp-era 63.8 count" % MAX_FLAG_KW,
                       "distinctValuesWithin1kWBelowMaximum": len({int(round(float(v) / Q)) for f in parts_f for v in stats[f]["dir"][dname]["nearMaxValues"] if float(v) >= mxv - 1.0 - 1e-9}),
                       "distinctValuesBasis": "counted on the 0.05 kW quantisation grid (integer grid index), per era",
                       "longestRunAtMaximumS": max(stats[f]["dir"][dname]["longestRunAtDriveMaxS"] for f in parts_f)}
                shown = [(k, v) for k, v in cells.items() if v["status"] == "supported"]
                present = [k for k, v in shown if (v.get("maxShare") or 0) > 0]
                sat["supportedCellsWithMaximum"] = len(present); sat["supportedCells"] = len(shown)
                sat["pattern"] = ("maximum reached in every supported bin" if shown and len(present) == len(shown) else ("maximum absent in some supported bin" if shown and present else "undetermined"))
                sat["patternNote"] = "a description only; a temperature-independent design cap at the same value gives the same pattern, and a zero share in a high-SoC bin is also expected under a saturated byte"
                iv = [stats[f]["dir"][dname].get("ivCheck") for f in parts_f]
                dayof = {f: meta[f]["date"] for f in parts_f}
                rng = np.random.default_rng(SEED)
                ud = sorted(set(dayof.values())); byd = {d: [0.0] * 4 for d in ud}
                for f, c in zip(parts_f, iv):
                    if c:
                        a = byd[dayof[f]]; a[0] += c["atMax"]["s"]; a[1] += c["atMax"]["exceed"]; a[2] += c["belowMax"]["s"]; a[3] += c["belowMax"]["exceed"]
                A = np.array([byd[d] for d in ud])
                pw_s = sum((c or {}).get("chargeAbove50kWSeconds", 0.0) for c in iv); pr_s = sum((c or {}).get("pairedSeconds", 0.0) for c in iv)
                def shares(X):
                    s = X.sum(axis=0)
                    return (s[1] / s[0] if s[0] > 0 else np.nan, s[3] / s[2] if s[2] > 0 else np.nan)
                pt = shares(A); bs = []
                for _ in range(nb):
                    bs.append(shares(A[rng.integers(0, len(ud), len(ud))]))
                bs = np.array(bs)
                def cinterval(col):
                    v = bs[:, col]; v = v[np.isfinite(v)]
                    return [round(float(np.percentile(v, 2.5)), 4), round(float(np.percentile(v, 97.5)), 4)] if len(v) > 0.5 * nb else None
                sat["loggedPowerAboveReportedLimit"] = {"definition": "time share of input samples with logged I x V charge power above 0.1 kW in which the logged power exceeds the reported input limit, by whether the reported limit is at the logged maximum (>= %.2f kW) or below it" % MAX_FLAG_KW,
                                                        "limitAtLoggedMaximum": {"share": None if not np.isfinite(pt[0]) else round(float(pt[0]), 4), "ci95": cinterval(0)},
                                                        "limitBelowMaximum": {"share": None if not np.isfinite(pt[1]) else round(float(pt[1]), 4), "ci95": cinterval(1)},
                                                        "power": {"timeShareLoggedChargePowerAbove50kW": round(pw_s / pr_s, 4) if pr_s else None, "pairedSeconds": round(pr_s, 1),
                                                                  "note": "the logged charge power is rarely near the reported limit, so the check has little power to detect an imposed cap or a saturated byte"},
                                                        "note": "descriptive; exceedance is rare at the logged maximum and absent below it; not evidence for or against saturation; the battery-current sign convention (charge-positive) is assumed"}
                ev["saturation"] = sat
            # cadence-regime sensitivity: per regime, share of time at the logged maximum and the median by pack-temperature bin pooled over SoC (point values)
            reg = {}
            for rg in ("fast", "slow"):
                rf = [f for f in parts_f if RR.regime_of(meta[f]["period"]) == rg]
                row = {}
                for tb in tbs:
                    hh = np.zeros(len(vals)); n = 0
                    for f in rf:
                        for key, c in stats[f]["dir"][dname]["cells"].items():
                            if int(key.split("|")[0]) == tb:
                                for k, wv in c["h"].items():
                                    hh[int(round((float(k) - vals[0]) / Q))] += wv
                    st = _stats_from_hist(hh, vals, below)
                    if st:
                        row[str(tb)] = {"median": _fmt(st["median"]), "maxShare": _fmt(st["maxShare"], 4), "seconds": round(float(hh.sum()), 1)}
                reg[rg] = {"nDrives": len(rf), "byPackTempC": row}
            ev["cadenceRegimeSensitivity"] = reg
            block["eras"][era][dname] = ev
    # unit and both-pairs gates are enforced by the shared reader (C._hdrm_pp_series raises HeadroomUnitError); the grid share is reported
    for era in ("hp", "kW"):
        for dname, ev in block["eras"][era].items():
            pf = [f for f in files if dname in stats[f]["dir"] and stats[f]["dir"][dname]["era"] == era]
            ns = sum(stats[f]["dir"][dname]["nSamples"] for f in pf); ng = sum(stats[f]["dir"][dname]["nOnGrid"] for f in pf)
            ev["gridShareOn0p05kW"] = round(ng / ns, 4) if ns else None
    return block


# ------------------------------------------------------------------------------------------------ cache, corpus, payload
def _file_sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _cache_path(sha):
    return os.path.join(CACHE_DIR, "%s_%s.json" % (sha, EXTRACTOR_VERSION))


def corpus_stats(raw_dir, files, verbose=False):
    os.makedirs(CACHE_DIR, exist_ok=True)
    stats, nnew = {}, 0
    for f in files:
        p = os.path.join(raw_dir, f)
        if not os.path.isfile(p):
            continue
        sha = _file_sha(p); cp = _cache_path(sha)
        if os.path.isfile(cp):
            r = json.load(open(cp, encoding="utf-8"))
        else:
            r = {"result": extract_drive(open(p, "rb").read(), f)}
            json.dump(r, open(cp, "w", encoding="utf-8"), separators=(",", ":")); nnew += 1
        if r["result"] is not None:
            stats[f] = r["result"]
    if verbose:
        print(json.dumps({"extractedNew": nnew, "withChannel": len(stats)}))
    return stats


def canonical_meta():
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    def clean(c):
        return ~dm[c].map(lambda x: x is True or x == "True")
    keep = clean("ens_outlier_v2") & clean("ens_invalid")
    meta = {r["file"]: {"date": str(r["date"]), "period": (None if pd.isna(r["I_sample_period_s"]) else float(r["I_sample_period_s"]))} for r in dm[keep].to_dict("records")}
    return meta, len(dm)


def stamp(A, md5):
    import stamp_common as _sc
    old = (A.get("_artifactStamps") or {}).get("bmsPowerMap")
    st = copy.deepcopy(A["_artifactStamps"]["headroomUtilization"]) if "headroomUtilization" in A.get("_artifactStamps", {}) else {}
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for k in ("carriedForward", "recomputeMode", "corpusSizeAtRecompute"):
        st.pop(k, None)
    st.update(corpusHash=md5, generatedAt=now, computationStatus="computed", upstreamHashes={"driveMasterMd5": md5},
              computationStatusNote="M658: derived by tools/n06_bms_power_map.py from the raw possible-power channels and drive_master.csv (spec analyses/M657_spec.md Rev 1.2); descriptive, exploratory")
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A["_artifactStamps"]["bmsPowerMap"] = _sc.carry_declared(old, st)


def main(argv):
    raw_dir = argv[argv.index("--raw-dir") + 1] if "--raw-dir" in argv else (os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw_only"))
    meta, ndm = canonical_meta()
    stats = corpus_stats(raw_dir, sorted(meta), verbose=True)
    block = aggregate(stats, meta)
    md5 = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    block["provenance"] = {"masterMd5": md5, "nCanonicalCleanDrives": len(meta), "nDrivesWithChannel": len(stats), "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest()}
    if "--out" in argv:
        json.dump(block, open(argv[argv.index("--out") + 1], "w", encoding="utf-8"), indent=1)
        print("wrote block")
        return
    if "--dry-run" in argv:
        print(json.dumps({"eras": {e: {d: {"drives": v["drives"], "days": v["days"], "supportedSecondsShare": v["supportedSecondsShare"]} for d, v in b.items()} for e, b in block["eras"].items()}}))
        return
    p = os.path.join(ROOT, "summary_arrays.json")
    raw = open(p, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    old = copy.deepcopy(A)
    A["bmsPowerMap"] = block
    stamp(A, md5)
    chk = copy.deepcopy(A); chk.pop("bmsPowerMap"); chk["_artifactStamps"].pop("bmsPowerMap")
    o2 = copy.deepcopy(old); o2.pop("bmsPowerMap", None); o2["_artifactStamps"].pop("bmsPowerMap", None)
    assert chk == o2, "unexpected change outside /bmsPowerMap"
    open(p, "w", encoding="utf-8", newline="").write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    print(json.dumps({"changed": True, "eras": list(block["eras"])}))


if __name__ == "__main__":
    main(sys.argv[1:])
