#!/usr/bin/env python3
"""M438 (spec analyses/M438_spec.md Rev 2): start-temperature strata (terciles of the coolant start temperature of the coolant cold starts, shared by both fluids) of the M435 time-to-threshold
headline cells (cohort all; coolant 80 C and oil 70 C; descriptive h in {300, 600, 900} s). Reuses the M435 estimators; ONE set of day resamples per cohort (the same as the M435 block), the cut points and
the stratum membership are fixed inside the draws. Outputs per stratum: E1, E2, F_high, tilt rows theta 0.5 / 2, classes, median; the start-standardized E2 (weights = the cell's own stratum shares,
fixed), the difference D = E2_pooled - E2_std and descriptive contrasts against stratum 1, all with paired intervals. E1_std = E1 and F_high_std = F_high are identities (tested, not displayed).
No tipping points and no restricted mean time per stratum. A draw with an empty stratum is unidentified; more than 2.5 % unidentified draws: the interval is 'not available'."""
import os, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import m435_tte as M
import time_to_threshold as T

CELLS = (("coolant", 80), ("oil", 70))
HORIZONS = (300, 600, 900)
H = 600
UNID_MAX = 0.025
PCTS = (100.0 / 3.0, 200.0 / 3.0)
STRATA_NAMES = ("lowest", "middle", "highest")


def cut_points(starts):
    """numpy linear percentile at 33.33333 and 66.66667, each rounded as floor(2x + 0.5) / 2 (0.5 C)."""
    q = np.percentile(np.asarray(starts, float), PCTS)
    return [float(np.floor(2.0 * x + 0.5) / 2.0) for x in q]


def assign(starts, cuts):
    s = np.asarray(starts, float)
    return np.where(s < cuts[0], 0, np.where(s < cuts[1], 1, 2))


def _pct(draws, valid):
    """95 % percentile interval over the identified draws; None ('not available') if more than 2.5 % of all draws are unidentified."""
    n = len(draws)
    if n == 0 or (n - int(valid.sum())) / n > UNID_MAX or int(valid.sum()) == 0:
        return None
    return [float(x) for x in T.pct(draws[valid])]


def _round_ci(ci, d=4):
    return None if ci is None else [round(ci[0], d), round(ci[1], d)]


def _r(x, d=4):
    return None if x is None else round(float(x), d)


def pooled_valid_h(pooled, pp):
    return pp["valid"]


class StratCell:
    """One (stratum or pooled) subset of a cell with its point values and shared-draw values at the declared horizons."""

    def __init__(self, t, e, day, counts, uni):
        self.n = len(t)
        self.cell = T.Cell(t, e, day) if self.n else None
        if self.cell is None:
            self.W1 = self.Wb = self.S1 = self.Sb = None
            self.valid = None
            return
        self.W1 = self.cell.ones(); self.S1 = self.cell.surv_steps(self.W1)
        self.Wb = self.cell.weights(counts, uni); self.Sb = self.cell.surv_steps(self.Wb)
        self.valid = self.Wb.sum(axis=1) > 0                         # an empty stratum in a draw makes the draw unidentified for this subset

    def at_risk(self, h):
        return self.cell.at_risk(h) if self.cell is not None else (0, 0)

    def supported(self, h):
        n, d = self.at_risk(h)
        return n >= M.MIN_N and d >= M.MIN_DAYS

    def point_and_draws(self, h, tilt=True):
        c = self.cell
        lo1, hi1 = c.manski(self.W1, h); lob, hib = c.manski(self.Wb, h)
        e2 = 1.0 - c.surv_at(self.S1, h)[0, 0]; e2b = 1.0 - c.surv_at(self.Sb, h)[:, 0]
        tl = {}
        for th in ((0.5, 2.0) if tilt else ()):
            tl["%g" % th] = (1.0 - c.tilt_surv(self.W1, self.S1, h, th)[0], 1.0 - c.tilt_surv(self.Wb, self.Sb, h, th))
        n_b = self.Wb.sum(axis=1)
        at_risk_b = (self.Wb * (c.t >= float(h))[None, :]).sum(axis=1)
        s_h = c.surv_at(self.Sb, h)[:, 0]
        valid = (n_b > 0) & ~((at_risk_b == 0) & (s_h > 0))          # C3: empty stratum, or an empty risk set at h while S_KM(h) > 0
        return {"E1": (lo1[0], lob), "E2": (e2, e2b), "high": (hi1[0], hib), "tilt": tl, "valid": valid, "n_b": n_b}


def _row(sc, h):
    n_r, d_r = sc.at_risk(h)
    out = {"h": h, "atRisk": n_r, "atRiskDays": d_r, "supported": bool(sc.supported(h))}
    if not out["supported"]:
        return out, None
    pd_ = sc.point_and_draws(h)
    v = pd_["valid"]
    ci = lambda key: _round_ci(_pct(pd_[key][1], v))
    out["E1"] = {"point": _r(pd_["E1"][0]), "ci95": ci("E1")}
    out["E2"] = {"point": _r(pd_["E2"][0]), "ci95": ci("E2")}
    out["boundHigh"] = {"point": _r(pd_["high"][0]), "ci95": ci("high")}
    out["tilt"] = {k: {"point": _r(x[0]), "ci95": _round_ci(_pct(x[1], v))} for k, x in pd_["tilt"].items()}
    if all(out[k]["ci95"] is not None for k in ("E1", "boundHigh")) and all(out["tilt"][k]["ci95"] is not None for k in out["tilt"]):
        row = {"tilt": out["tilt"], "bounds": {"high": {"ci95": out["boundHigh"]["ci95"]}, "low": {"ci95": out["E1"]["ci95"]}}}
        out["reading"] = "F<0.5" if pd_["E2"][0] < 0.5 else "F>=0.5"
        out["readingClasses"] = M._classes(row)
    return out, pd_


def standardize(pooled, w, h, pd_list, tilt=True):
    """Start-standardized E2 (weights = the cell's own stratum shares, recomputed in every draw: C1), D = E2_pooled - E2_std and descriptive contrasts against stratum 1, with paired intervals
    from the shared draws. pd_list: the point_and_draws(h) dicts of the three strata. Returns (entry, identities_ok)."""
    pdraws = {h: pd_list}
    pp = pooled.point_and_draws(h, tilt=tilt)
    e2s = sum(w[s] * pdraws[h][s]["E2"][0] for s in range(3))
    e1s = sum(w[s] * pdraws[h][s]["E1"][0] for s in range(3))
    hs = sum(w[s] * pdraws[h][s]["high"][0] for s in range(3))
    nb = np.stack([pdraws[h][s]["n_b"] for s in range(3)], axis=1)                    # (B, 3) stratum total weights in each draw
    tot = nb.sum(axis=1)
    wb = np.where(tot[:, None] > 0, nb / np.where(tot[:, None] > 0, tot[:, None], 1.0), 0.0)         # C1: weights recomputed in each draw
    e2sb = sum(wb[:, s] * np.where(wb[:, s] > 0, pdraws[h][s]["E2"][1], 0.0) for s in range(3))
    e1sb = sum(wb[:, s] * np.where(wb[:, s] > 0, pdraws[h][s]["E1"][1], 0.0) for s in range(3))
    hsb = sum(wb[:, s] * np.where(wb[:, s] > 0, pdraws[h][s]["high"][1], 0.0) for s in range(3))
    parts_ok = np.logical_and.reduce([pdraws[h][s]["valid"] | (wb[:, s] == 0) for s in range(3)]) & pooled_valid_h(pooled, pp)
    D = pp["E2"][0] - e2s; Db = pp["E2"][1] - e2sb
    ent = {"available": True, "E2std": {"point": _r(e2s), "ci95": _round_ci(_pct(e2sb, parts_ok))}, "D": {"point": _r(D), "ci95": _round_ci(_pct(Db, parts_ok))},
           "nUnidentifiedDraws": int((~parts_ok).sum()), "shareDrawsUnidentified": _r(1.0 - float(parts_ok.mean()), 4), "contrasts": {}}
    ok = abs(e1s - pp["E1"][0]) < 1e-9 and abs(hs - pp["high"][0]) < 1e-9 and bool(np.all(np.abs(np.where(parts_ok, e1sb - pp["E1"][1], 0.0)) < 1e-9))                 and bool(np.all(np.abs(np.where(parts_ok, hsb - pp["high"][1], 0.0)) < 1e-9))
    for s in (1, 2):
        v2 = pdraws[h][s]["E2"]; v1 = pdraws[h][0]["E2"]; e1_2 = pdraws[h][s]["E1"]; e1_1 = pdraws[h][0]["E1"]
        vv = pdraws[h][s]["valid"] & pdraws[h][0]["valid"]
        ent["contrasts"]["stratum%d_minus_1" % (s + 1)] = {"E2": {"point": _r(v2[0] - v1[0]), "ci95": _round_ci(_pct(v2[1] - v1[1], vv))}, "E1": {"point": _r(e1_2[0] - e1_1[0]), "ci95": _round_ci(_pct(e1_2[1] - e1_1[1], vv))}}
    return ent, ok


def build_block(tte, days, main_block, C, meta=None):
    idx = range(len(tte))
    cold = [i for i in idx if tte[i].get("status") == "cold"]
    starts_all = [tte[i]["startC"] for i in cold]
    cuts = cut_points(starts_all)
    uni = np.array(sorted({days[i] for i in cold}))
    counts = T.day_counts(uni, M.B_DRAWS, M.SEED)
    strat_of = {i: int(assign([tte[i]["startC"]], cuts)[0]) for i in cold}
    shares_all = [sum(1 for i in cold if strat_of[i] == s) / len(cold) for s in range(3)]
    cells_out, checks = {}, {}
    g1 = True
    for fl, thr in CELLS:
        ents = []
        for i in cold:
            f = tte[i]["coolant"] if fl == "coolant" else tte[i]["oil"]
            if f is None:
                continue
            x = f["thr"][str(thr)]
            ents.append((i, x["t"], x["e"], x["reason"], days[i], strat_of[i]))
        pooled = StratCell([e_[1] for e_ in ents], [e_[2] for e_ in ents], [e_[4] for e_ in ents], counts, uni)
        subs = []
        for s in range(3):
            sel = [e_ for e_ in ents if e_[5] == s]
            subs.append((sel, StratCell([e_[1] for e_ in sel], [e_[2] for e_ in sel], [e_[4] for e_ in sel], counts, uni)))
        n_cell = len(ents)
        w = [len(sel) / n_cell for sel, _ in subs]
        cell_k = "%s/%d" % (fl, thr)
        strata = []
        rows_by_h = {h: [] for h in HORIZONS}
        pdraws = {h: [] for h in HORIZONS}
        for s, (sel, sc) in enumerate(subs):
            reached = sum(1 for e_ in sel if e_[2])
            rec = {"stratum": s + 1, "name": STRATA_NAMES[s], "range": ("start < %g C" % cuts[0]) if s == 0 else (("%g C <= start < %g C" % (cuts[0], cuts[1])) if s == 1 else ("start >= %g C" % cuts[1])),
                   "n": len(sel), "days": len({e_[4] for e_ in sel}), "weight": _r(w[s], 6), "reached": reached, "censoredShare": _r(1.0 - reached / len(sel)) if sel else None,
                   "censoredTripEnd": sum(1 for e_ in sel if e_[3] == "tripEnd"), "censoredChannelLoss": sum(1 for e_ in sel if e_[3] == "channelLoss")}
            hz = []
            for h in HORIZONS:
                row, pd_ = _row(sc, h) if sc.cell is not None else ({"h": h, "atRisk": 0, "atRiskDays": 0, "supported": False}, None)
                hz.append(row); rows_by_h[h].append(row); pdraws[h].append(pd_)
            rec["horizons"] = hz
            r600 = next(r for r in hz if r["h"] == H)
            lab = {0: "lowest", 1: "middle", 2: "highest"}[s]
            rec["classStatement"] = (("within the %s start-temperature tercile (%s), fewer than half reached by %d s: %s; half or more reached: %s" % (lab, rec["range"], H, r600["readingClasses"]["F<0.5"], r600["readingClasses"]["F>=0.5"]))
                                     if r600.get("readingClasses") else "within the %s start-temperature tercile (%s), %d s: not supported or interval not available" % (lab, rec["range"], H))
            med = float(sc.cell.median_time(sc.S1)[0]) if sc.cell is not None else float("inf")
            rec["median"] = {"point": _r(med, 1) if np.isfinite(med) else None, "identified": bool(np.isfinite(med))}
            if meta is not None and sel:                   # post-hoc descriptive profile (audit finding), script-written
                dk = np.array([meta[e_[0]]["distanceKm"] for e_ in sel], float); hr = np.array([meta[e_[0]]["startHour"] for e_ in sel], float)
                rec["profilePostHoc"] = {"medianDistanceKm": _r(np.median(dk), 2), "shareUnder5km": _r(np.mean(dk < 5)), "shareStartBefore10h": _r(np.mean(hr < 10)),
                                         "label": "post-hoc descriptive, not pre-registered (blind-audit finding); not a test"}
            strata.append(rec)
        # standardized value, D and contrasts per horizon
        std = {}
        for h in HORIZONS:
            if not all(r["supported"] for r in rows_by_h[h]) or any(pd_ is None for pd_ in pdraws[h]):
                std[str(h)] = {"available": False, "reason": "a stratum is not supported at this horizon (fewer than %d drives on %d days at risk)" % (M.MIN_N, M.MIN_DAYS)}
                continue
            ent, ok_ = standardize(pooled, w, h, pdraws[h])
            checks.setdefault("identitiesE1HighStd", True)
            checks["identitiesE1HighStd"] = bool(checks["identitiesE1HighStd"] and ok_)
            std[str(h)] = ent
        # G1: strata partition the cell and the pooled values equal the M435 cell
        m = main_block["cohorts"]["all"][fl][str(thr)]
        part = sum(r["n"] for r in strata) == m["n"] and sum(r["reached"] for r in strata) == m["reached"] and sum(r["censoredTripEnd"] for r in strata) == m["censoredTripEnd"] \
            and sum(r["censoredChannelLoss"] for r in strata) == m["censoredChannelLoss"] and abs(sum(w) - 1.0) < 1e-12
        same = True
        for mh in m["horizons"]:
            if mh["h"] in HORIZONS and mh["supported"]:
                prow, _ = _row(pooled, mh["h"])
                same = same and prow["E1"]["point"] == mh["E1"]["point"] and prow["E2"]["point"] == mh["E2"]["point"] and prow["boundHigh"]["point"] == mh["bounds"]["high"]["point"]
        g1 = g1 and part and same
        pooled_rows = [_row(pooled, h)[0] for h in HORIZONS]
        # script-written notes (Director ruling): contrasts against the lowest tercile, D near zero, thin support
        s600 = std.get(str(H), {})
        notes = {}
        if s600.get("available"):
            def incl(ci_):
                return "its interval includes zero" if (ci_ is not None and ci_[0] <= 0 <= ci_[1]) else "its interval excludes zero"
            c21 = s600["contrasts"]["stratum2_minus_1"]["E2"]; c31 = s600["contrasts"]["stratum3_minus_1"]["E2"]
            f2 = next(r for r in strata[1]["horizons"] if r["h"] == H)["E2"]["point"]; f3 = next(r for r in strata[2]["horizons"] if r["h"] == H)["E2"]["point"]
            notes["pattern"] = ("at %d s the middle tercile differs from the lowest by %.3f (%s) and the highest by %.3f (%s); the highest and the middle differ by %.3f (point only, no interval); "
                                "the contrasts are against the lowest tercile and no gradient across the terciles is claimed" % (H, c21["point"], incl(c21["ci95"]), c31["point"], incl(c31["ci95"]), abs(f3 - f2)))
            highs = [next(r for r in st_["horizons"] if r["h"] == H)["boundHigh"]["point"] for st_ in strata if next(r for r in st_["horizons"] if r["h"] == H).get("boundHigh")]
            notes["dNote"] = ("a difference D near zero is not evidence that censoring can be ignored: independent censoring is still assumed within each tercile, and the upper worst-case bounds of the terciles at %d s are %s"
                              % (H, " / ".join("%.3f" % x for x in highs)))
        thin = [(st_["stratum"], next(r for r in st_["horizons"] if r["h"] == H)) for st_ in strata]
        notes["thin"] = ["stratum %d has only %d drives on %d days at risk at %d s (below twice the support floor of %d drives)" % (k_, r["atRisk"], r["atRiskDays"], H, M.MIN_N) for k_, r in thin if r["atRisk"] < 2 * M.MIN_N] or None
        cells_out[cell_k] = {"notes": notes, "n": n_cell, "days": len({e_[4] for e_ in ents}), "weights": [_r(x, 6) for x in w], "pooled": pooled_rows, "strata": strata, "standardized": std}
    checks["g1PartitionAndPooledEqualsM435"] = bool(g1)
    checks["allOk"] = all(checks.values())
    if not checks["allOk"]:
        raise RuntimeError("M438 checks failed (no leaf is written; goes to the Director): %s" % {k: v for k, v in checks.items() if v is False})
    return {"spec": "analyses/M438_spec.md", "methodVersion": "M438-r2", "cohort": "all", "horizonsS": list(HORIZONS), "headlineH": H, "headlineCells": ["%s/%d" % c for c in CELLS],
            "cutPointsC": cuts, "cutRule": "numpy linear percentile at 33.33333 and 66.66667 of the coolant start temperature of the coolant cold starts, rounded as floor(2x + 0.5) / 2; start equal to a cut belongs to the higher stratum",
            "strataSharesOfCoolantColdStarts": [_r(x, 6) for x in shares_all], "nColdStarts": len(cold),
            "bootstrap": {"B": M.B_DRAWS, "seed": M.SEED, "cluster": "calendar day", "sharedWithM435": True, "cutsAndMembershipFixedInDraws": True, "unidentifiedMax": UNID_MAX},
            "cells": cells_out, "checks": checks, "label": M.LABEL,
            "required": {"R1": "assumes that ending the drive is unrelated to the remaining time to the threshold (independent censoring) within each start-temperature tercile; this cannot be checked from these data",
                         "entanglement": "start temperature is entangled with the season, the trip length and the decision to stop the drive: the strata describe, they do not identify an effect of the start temperature",
                         "contrasts": "contrasts are descriptive, no test and no p-value; standardized to the observed start-temperature mix (weights fixed)"},
            "limits": ["terciles are a declared planning choice with unequal shares (integer start temperature)", "few days per stratum at long horizons: the support rule decides what is shown",
                       "no family-wise claim over 2 cells x 3 horizons x contrasts", "strata are not matched on trip length, hour or season", "cohort all only"]}
