#!/usr/bin/env python3
"""M520 Part A (analyses/M520_spec.md Rev 2; Director: revise, then payload only by owner decision 2026-10-27): support-restricted refits of the resistance-proxy months coefficient.
POST HOC and exploratory: the restricted values were seen by the 2026-10-26 re-audit before this registration. Six cells A{0,1} x G{0,1,2} (C1, T0), the M514 engine unchanged (tools/resistance_joint_matrix.py),
drives restricted to a per-variant sample count >= 2 x 300 (A0: n_vreg_samples, A1: a1_n). Also reported: a selection diagnostic (retained vs excluded drives) and a size-matched null (random day-clustered subsets).
Writes ONLY the sibling payload key resistanceSupportRestricted + its stamp (additive). Deviation from spec Rev 2 recorded in Rev 2.1: a sibling key instead of a child key, so that the M514 block and
tools/resistance_joint_matrix.py (a declared input of its stamp) stay byte-identical. The M514 ladder is never called on these cells."""
KEY = "resistanceSupportRestricted"
import copy, datetime, hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import numpy as np, pandas as pd
import resistance_joint_matrix as RJ
import powerfade_equivalence as PE

MIN_N = 2 * 300
NULL_DRAWS, SEL_DRAWS, SEED = 2000, 2000, 42
ALLOWED = ["/resistanceSupportRestricted", "/_artifactStamps/resistanceSupportRestricted"]
SPEC = os.path.join("analyses", "M520_spec.md")
CELLS = ["A%dG%dC1T0" % (a, g) for a in (0, 1) for g in (0, 1, 2)]
COVS = (("months", None), ("T_pack_mean_avg", RJ.T_), ("eff_dt_s", "_de"), ("coverage_frac", "_dc"), ("distance_km", "distance_km"), ("duration_s", "duration_s"))


def _ncol(a):
    return RJ.N_ if a == 0 else "a1_n"


def _months(sub, t0):
    return ((pd.to_datetime(sub["date"]) - t0).dt.days / RJ.MONTH_DAYS).values


def fit_cells(F, min_n, nb, t0, knots):
    """The six restricted cells (or, with min_n = 0, the unrestricted cells = the M514 cells for the same ids). Returns (records, populations)."""
    recs, pops = {}, {}
    for a in (0, 1):
        Fr = F[F[_ncol(a)].astype(float) >= min_n].reset_index(drop=True)
        nchg = int(Fr["_chg"].astype(float).sum()); chg_days = int(Fr.loc[Fr["_chg"].astype(bool), "date"].nunique())
        grid_ok = nchg >= RJ.MIN_GRID_DRIVES and chg_days >= RJ.MIN_GRID_DAYS
        pop_ok = len(Fr) >= RJ.MIN_DRIVES and Fr["date"].nunique() >= RJ.MIN_DAYS
        S2 = Fr[~Fr["_chg"].astype(bool)].reset_index(drop=True)
        s2_ok = len(S2) >= RJ.MIN_DRIVES and S2["date"].nunique() >= RJ.MIN_DAYS
        pops[a] = {"nDrives": int(len(Fr)), "nDays": int(Fr["date"].nunique()), "nGridChangeDrives": nchg, "nGridChangeDays": chg_days,
                   "g2Subset": {"nDrives": int(len(S2)), "nDays": int(S2["date"].nunique())}, "gridChangeRuleMet": bool(grid_ok), "g2SubsetRuleMet": bool(s2_ok), "populationRuleMet": bool(pop_ok)}
        cells_F = ["A%dG0C1T0" % a, "A%dG1C1T0" % a]
        cell_S = "A%dG2C1T0" % a
        if len(Fr) >= 3 and Fr["date"].nunique() >= 3:
            gF = RJ.make_group(Fr, cells_F, t0, knots); rF = RJ.procedures(gF, nb)
            for k, cid in enumerate(cells_F):
                r = RJ.cell_record(gF, rF, k, nb, pop_ok and (True if cid[3] == "0" else grid_ok))
                recs[cid] = r
        if len(S2) >= 3 and S2["date"].nunique() >= 3:
            gS = RJ.make_group(S2, [cell_S], t0, knots); rS = RJ.procedures(gS, nb)
            r = RJ.cell_record(gS, rS, 0, nb, grid_ok and s2_ok)
            r["subset"] = "G2: gridChange drives excluded"
            recs[cell_S] = r
    return recs, pops


def _std_diff(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    x, y = x[np.isfinite(x)], y[np.isfinite(y)]
    if len(x) < 2 or len(y) < 2:
        return None
    sd = np.sqrt((x.var(ddof=1) + y.var(ddof=1)) / 2)
    return None if sd == 0 else float((x.mean() - y.mean()) / sd)


def selection_diagnostic(F, t0):
    """A2 (reported only): balance between retained and excluded drives, and the slope of the sample count on months with a day-clustered interval."""
    out = {}
    mo = _months(F, t0)
    for a in (0, 1):
        n = F[_ncol(a)].astype(float).values
        keep = n >= MIN_N
        d = {"nRetained": int(keep.sum()), "nExcluded": int((~keep).sum()), "daysLost": int(F["date"].nunique() - F.loc[keep, "date"].nunique()), "standardizedMeanDifference": {}}
        for name, col in COVS:
            v = mo if col is None else pd.to_numeric(F[col], errors="coerce").values
            d["standardizedMeanDifference"][name] = _std_diff(v[keep], v[~keep])
        days = F["date"].astype(str).values
        uniq, di = np.unique(days, return_inverse=True)
        x = mo - mo.mean(); sl = float((x * (n - n.mean())).sum() / (x ** 2).sum())
        rng = np.random.default_rng(SEED); bs = []
        for _ in range(SEL_DRAWS):
            pick = rng.integers(0, len(uniq), len(uniq))
            idx = np.concatenate([np.where(di == u)[0] for u in pick])
            xx, yy = mo[idx], n[idx]
            if xx.std() > 0:
                bs.append(float(((xx - xx.mean()) * (yy - yy.mean())).sum() / ((xx - xx.mean()) ** 2).sum()))
        ci = [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]
        d["sampleCountSlopePerMonth"] = {"slope": sl, "dayCi95": ci, "excludesZero": bool(ci[0] > 0 or ci[1] < 0)}
        d["flag"] = "selection aliased with calendar" if d["sampleCountSlopePerMonth"]["excludesZero"] else "no calendar trend in support detected (does not rule out confounding)"
        out["A%d" % a] = d
    return out


def size_matched_null(sub, cell, k, t0, knots, observed):
    """A3: distribution of the point slope over random day-clustered subsets of `sub` with exactly k drives (fixed seed)."""
    t = _months(sub, t0)
    X, y = RJ.design(sub, cell, t, knots)
    days = sub["date"].astype(str).values
    uniq, di = np.unique(days, return_inverse=True)
    rows = [np.where(di == u)[0] for u in range(len(uniq))]
    rng = np.random.default_rng(SEED + 7 * int(cell[1]) + int(cell[3]))
    sl = []
    for _ in range(NULL_DRAWS):
        take = []
        for u in rng.permutation(len(uniq)):
            take.append(rows[u])
            if sum(len(r) for r in take) >= k:
                break
        idx = np.concatenate(take)
        if len(idx) > k:
            idx = rng.choice(idx, size=k, replace=False)
        b = np.linalg.lstsq(X[idx], y[idx], rcond=None)[0]
        sl.append(float(b[1]))
    sl = np.array(sl)
    lo, med, hi = (float(np.percentile(sl, q)) for q in (2.5, 50, 97.5))
    return {"nDraws": NULL_DRAWS, "k": int(k), "nullQuantiles": {"p2.5": lo, "p50": med, "p97.5": hi}, "observedSlope": float(observed),
            "fractionOfNullAtOrBelowObserved": float((sl <= observed).mean()), "insideCentral95": bool(lo <= observed <= hi)}


def reading_across(rec):
    """Readings of the four procedures for one cell (decisive only)."""
    return {p: (rec[p]["reading"] if rec[p].get("decisive") else None) for p in ("day", "week", "M7", "M14")}


def summarize(recs):
    cnt = {}
    for p in ("day", "week", "M7", "M14"):
        dec = [c[p]["reading"] for c in recs.values() if c[p].get("decisive")]
        cnt[p] = {"decisive": len(dec), "excludeZero": int(sum(1 for x in dec if x in ("positive", "negative"))), "positive": int(sum(1 for x in dec if x == "positive"))}
    allp = [c for c in recs.values()]
    pos_all = bool(allp) and all(c["slope"] > 0 for c in allp)
    agree = all(cnt[p]["decisive"] > 0 and cnt[p]["positive"] == cnt[p]["decisive"] for p in cnt)
    procs_differ = len({(cnt[p]["positive"], cnt[p]["decisive"]) for p in cnt}) > 1
    level = "positive in every decisive interval of all four procedures" if agree and pos_all else "procedure-dependent or mixed"
    return {"nCells": len(recs), "nPositiveSlopes": int(sum(1 for c in allp if c["slope"] > 0)), "slopeRange": [min(c["slope"] for c in allp), max(c["slope"] for c in allp)] if allp else None,
            "intervalCounts": cnt, "proceduresDiffer": bool(procs_differ), "readingAcrossProcedures": level,
            "escalationK": cnt["day"]["excludeZero"],
            "note": "six cells share one dataset and are not six independent results; no multiplicity control (6 cells x 4 procedures, re-looked at every ingestion); post hoc, exploratory; not part of the M514 ladder"}


def compute(dm, side, dens, nb=RJ.NB):
    modal, _ = RJ.frozen_modal_pair()
    cc, F = RJ.build_frame(dm, side, dens, modal)
    t0 = pd.to_datetime(F["date"]).min(); knots = RJ.quantile_knots(F[RJ.T_].values)
    recs, pops = fit_cells(F, MIN_N, nb, t0, knots)
    S2 = F[~F["_chg"].astype(bool)].reset_index(drop=True)
    nulls = {}
    for cid, r in recs.items():
        a = int(cid[1])
        base = S2 if cid[3] == "2" else F
        nulls[cid] = size_matched_null(base, cid, r["n"], t0, knots, r["slope"])
    # identity check (A: same code with the filter set to "all drives" must reproduce the M514 payload cells)
    idrecs, _ = fit_cells(F, 0, nb, t0, knots)
    return F, t0, recs, pops, nulls, idrecs


def identity_check(idrecs, m514_cells, tol=5e-6):
    by = {c["id"]: c for c in m514_cells}
    worst, n = 0.0, 0
    for cid, r in idrecs.items():
        m = by.get(cid)
        if m is None:
            return {"passed": False, "reason": "cell %s not in the M514 payload" % cid}
        pairs = [(r["slope"], m["slope"])]
        for p in ("day", "week", "M7", "M14"):
            if r[p].get("ci95") and m[p].get("ci95"):
                pairs += list(zip(r[p]["ci95"], m[p]["ci95"]))
        for x, y in pairs:
            worst = max(worst, abs(x - y)); n += 1
    return {"passed": bool(worst <= tol), "maxAbsDifference": worst, "nValuesCompared": n, "tolerance": "5e-6" if tol == 5e-6 else str(tol), "cells": sorted(idrecs)}


def build_block(dm, side, dens, A, nb=RJ.NB):
    F, t0, recs, pops, nulls, idrecs = compute(dm, side, dens, nb)
    m514 = A["resistanceJointSensitivity"]
    idc = identity_check(idrecs, m514["cells"])
    cells = []
    for cid in CELLS:
        if cid not in recs:
            continue
        r = copy.deepcopy(recs[cid]); r["readingAcrossProcedures"] = reading_across(r); r["sizeMatchedNull"] = nulls[cid]
        cells.append(r)
    blk = {"label": "support-restricted refits of the resistance-proxy (vreg_R_pack_mohm) months coefficient, powerFade S1 design; POST HOC exploratory sensitivity (the restricted values were seen before registration); estimated proxy, a conditional association in one warm window, not a degradation rate, SOH or true resistance",
           "postHoc": True, "confirmatory": False, "displayed": False,
           "spec": "analyses/M520_spec.md (Rev 2.1)", "specSha256": hashlib.sha256(open(SPEC, "rb").read()).hexdigest(),
           "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(),
           "m514ScriptSha256": m514["scriptSha256"], "seed": SEED, "nBoot": nb, "supportMargin": {"minSamples": MIN_N, "rule": "A0: n_vreg_samples >= 2 x 300; A1: a1_n >= 2 x 300 (M505 Rev 2 R2)"},
           "populations": {"A%d" % a: p for a, p in pops.items()}, "cells": cells, "summary": summarize({c["id"]: c for c in cells}),
           "selectionDiagnostic": selection_diagnostic(F, t0), "identityCheck": idc,
           "decisiveRules": "M514 R7 unchanged inside the restricted set (failed draws <= 1 %, fewBlocks, cond <= 1e9, >= 10 gridChange drives on >= 5 days for G1/G2, >= 150 drives on >= 50 days)"}
    return RJ._clean(blk)


def splice(A, blk, master_md5="", now=None):
    new = copy.deepcopy(A)
    new[KEY] = blk
    old = (A.get("_artifactStamps") or {}).get(KEY)
    if old and A.get(KEY) == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"][KEY] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M520: derived by tools/resistance_support_restricted.py from drive_master.csv, powerfade_density.csv and the tracked resistance_joint_sidecar.csv (analyses/M520_spec.md Rev 2.1)",
                  upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
        import stamp_common as _sc
        new["_artifactStamps"][KEY] = _sc.carry_declared(old, st)
    ch = [k for k in set(A) | set(new) if A.get(k) != new.get(k)]
    bad = [k for k in ch if k not in (KEY, "_artifactStamps")]
    st_bad = [k for k in set(A["_artifactStamps"]) | set(new["_artifactStamps"]) if A["_artifactStamps"].get(k) != new["_artifactStamps"].get(k) and k != KEY]
    return new, ch, bad + st_bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    nb = int(argv[argv.index("--nb") + 1]) if "--nb" in argv else RJ.NB
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A = json.loads(raw)
    side = RJ._read(RJ.SIDECAR)
    ps = PE._read(PE.SIDECAR)
    dens = {r["file"]: (float(r["eff_dt_s"]) if pd.notna(r["eff_dt_s"]) else np.nan, float(r["coverage_frac"]) if pd.notna(r["coverage_frac"]) else np.nan) for r in ps.to_dict("records")}
    blk = build_block(dm, side, dens, A, nb)
    if not blk["identityCheck"]["passed"]:
        print(json.dumps({"STOP": "identity check failed", "identityCheck": blk["identityCheck"]}))
        return 1
    if "--check" in argv:
        have = A.get(KEY)
        print(json.dumps({"check": "supportRestricted", "matchesPayload": have == blk}))
        return 0 if have == blk else 1
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    new, ch, bad = splice(A, blk, md5)
    json.dump(blk, open(os.path.join("analyses", "M520_result.json"), "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False)
    print(json.dumps({"nChanged": len(ch), "outsideAllowList": bad, "summary": blk["summary"]["readingAcrossProcedures"], "kDayExcludeZero": blk["summary"]["escalationK"], "identity": blk["identityCheck"]["passed"]}))
    if bad:
        return 1
    if "--dry-run" not in argv and ch:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
