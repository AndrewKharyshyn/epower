#!/usr/bin/env python3
"""M751 (spec analyses/M751_spec.md Rev 2): unlogged-driving contamination of the heat-soak carryover pairs. REPORT-ONLY sensitivity; no payload, dashboard or published figure changes.

The published `heatSoakCarryover` block pairs every two consecutive LOGGED drives and bins the pairs by the parking gap. The registered cloud gap table (analyses/M729_cloud_gaps.csv,
pinned by sha256) says for each such gap whether the car stood still (S), moved without an OBD record (D: driving_observed or odometer_increase_only), was uncertain (U) or is
unknown (X). Sets: A all pairs (the published set), B = S only, C = A minus D, C1 = A minus D pairs with moved_km >= 1. A-B and A-C are LOWER BOUNDS on the contamination shift
(undetected contamination stays in B and C). Exclusion only, never a correction (the heat at the end of an unlogged drive is unknown).

Control V0: the pairing, the per-bin medians and the soak fit reproduced here for set A must equal the published block (tool STOPS, exit 3, nothing written, otherwise).
Usage: python tools/heatsoak_gap_sensitivity.py [--out-dir analyses] [--nb 4000] [--limit-drives N]   (no cloud gap table -> skipped, exit 0)"""
import argparse, hashlib, json, os, re, sys, time
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import soak_tau as ST

GAPS_PIN = "d1d3f8e9da732e7c58212c3bcf5718e05304a186df4f45e567d8799c704d159f"
REGISTERED_MASTER = "d514d6009d6d9a0a168ad4fb09b9bb98"
BINS = ((0, 1), (1, 3), (3, 6), (6, 12), (12, 24), (24, 1e9))
N_MIN, DAYS_MIN, SHIFT_PP, K_BAND, D1_KM, JOIN_TOL_H = 20, 10, 5.0, (0.80, 1.25), 1.0, 0.01
MIN_EXCESS, RESID_MIN, FIT_MIN, SEED, NB_DEFAULT = 3.0, 0.5, 8, 42, 4000
SET_NAMES = ("B", "C", "C1")
CLASS_SET = {"stationary_consistent": "S", "driving_observed": "D", "odometer_increase_only": "D", "uncertain": "U",
             "export_break": "X", "no_cloud_data": "X", "no_cloud_row": "X"}


class Stop(Exception):
    pass


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


# ---------------------------------------------------------------------------- pairs (re-implements the published pairing loop, keeping the file names)
def build_pairs(d, traj, amb):
    """d: DataFrame sorted by ts_full with file, ts_full, te_full. traj: {file: {pm_start, pm_end, ...}}. amb: {file: manual ambient}. Same rules as _heat_soak_carryover."""
    rows = []
    for k in range(len(d) - 1):
        a, b = d.iloc[k], d.iloc[k + 1]
        ta, tb = traj.get(a["file"], {}), traj.get(b["file"], {})
        if "pm_end" not in ta or "pm_start" not in tb:
            continue
        if pd.isna(a["te_full"]) or pd.isna(b["ts_full"]):
            continue
        gap_h = (b["ts_full"] - a["te_full"]).total_seconds() / 3600.0
        if gap_h < 0:
            continue
        t_end, t_start = ta["pm_end"], tb["pm_start"]
        rec = {"prev": a["file"], "next": b["file"], "gapH": gap_h, "tEnd": t_end, "tStart": t_start, "shedC": t_end - t_start,
               "retainedFrac": None, "initExcessC": None, "residExcessC": None}
        amb_b = amb.get(b["file"])
        if amb_b is not None:
            ie, re_ = t_end - amb_b, t_start - amb_b
            rec["initExcessC"], rec["residExcessC"] = ie, re_
            if ie > 0:
                rec["retainedFrac"] = re_ / ie
        rec["dayArrival"] = str(b["ts_full"])[:10]
        rec["dayDeparture"] = str(a["te_full"])[:10]
        rows.append(rec)
    return pd.DataFrame(rows)


def join_classes(pf, gaps):
    """Ordered (prev, next) join to the M729 gap rows. Asserts unique names and the gap tolerance; unmatched pairs get class no_cloud_row with a reason code."""
    if pf["prev"].duplicated().any() or pf["next"].duplicated().any():
        raise Stop("a drive appears twice as previous or as next in the pairing")
    if gaps.duplicated(["prev", "next"]).any():
        raise Stop("duplicate (prev, next) rows in the M729 gap table")
    g = gaps.rename(columns={"class": "cls", "gap_h": "gapH_m729"})[["prev", "next", "gapH_m729", "cls", "moved_km", "last_move_to_next_h"]]
    m = pf.merge(g, on=["prev", "next"], how="left")
    m["reason"] = ""
    nomatch = m["cls"].isna()
    m.loc[nomatch, "reason"] = "no_m729_row"
    bad = (~nomatch) & ((m["gapH"] - m["gapH_m729"]).abs() > JOIN_TOL_H)
    m.loc[bad, "reason"] = "gap_mismatch"
    m.loc[nomatch | bad, "cls"] = "no_cloud_row"
    m["set"] = m["cls"].map(CLASS_SET)
    keys = set(zip(pf["prev"], pf["next"]))
    only_m729 = int(sum(1 for r in gaps.itertuples() if (r.prev, r.next) not in keys))
    rec = {"pairs": int(len(pf)), "m729_gaps": int(len(gaps)), "matched": int((~(nomatch | bad)).sum()), "no_m729_row": int(nomatch.sum()), "gap_mismatch": int(bad.sum()),
           "m729_gaps_without_a_pair": only_m729}
    return m, rec


def masks(m):
    """Boolean membership of the sets (index aligned with m)."""
    D = m["set"] == "D"
    D1 = D & (m["moved_km"].fillna(0) >= D1_KM)
    return {"A": pd.Series(True, index=m.index), "B": m["set"] == "S", "C": ~D, "C1": ~D1, "D": D, "D1": D1, "S": m["set"] == "S"}


# ---------------------------------------------------------------------------- per-bin medians and shifts
def bin_rows(m, lo, hi):
    return (m["gapH"] >= lo) & (m["gapH"] < hi)


def paired_median_diffs(r, in_sets, cl, nb, seed):
    """Day-clustered paired bootstrap of median(A) - median(set) for each set in in_sets (all rows of r belong to A). r: retained fraction array, cl: cluster labels.
    Returns {set: array of draws}, plus the number of skipped draws (empty set sample)."""
    codes, uniq = pd.factorize(cl)
    groups = [np.where(codes == i)[0] for i in range(len(uniq))]
    rng = np.random.default_rng(seed)
    out = {k: [] for k in in_sets}
    skipped = 0
    for _ in range(nb):
        pick = rng.integers(0, len(groups), len(groups))
        idx = np.concatenate([groups[i] for i in pick])
        ra = r[idx]
        ok = True
        vals = {}
        for k, msk in in_sets.items():
            sel = msk[idx]
            if not sel.any():
                ok = False
                break
            vals[k] = np.median(ra) - np.median(ra[sel])
        if not ok:
            skipped += 1
            continue
        for k, v in vals.items():
            out[k].append(v)
    return {k: np.array(v) for k, v in out.items()}, skipped


def verdict_shift(delta_pp, lo_pp, hi_pp, supported):
    if not supported:
        return "not estimable at this support"
    if lo_pp > 0 or hi_pp < 0:
        return "material" if abs(delta_pp) >= SHIFT_PP else "small"
    return "not distinguishable"


def e2_bins(m, mk, cluster_col="dayArrival", nb=NB_DEFAULT, seed=SEED, excess_min=None, sets=SET_NAMES):
    """Per published gap bin: counts by class, medians of the retained fraction in A and in each comparison set, shift A - set (pp) with a day-clustered paired interval."""
    out = []
    base = m[m["retainedFrac"].notna()]
    if excess_min is not None:
        base = base[base["initExcessC"] > excess_min]
    for lo, hi in BINS:
        sub = base[bin_rows(base, lo, hi)]
        row = {"gapLoH": lo, "gapHiH": None if hi > 1e8 else hi, "nAmbA": int(len(sub))}
        if len(sub) == 0:
            out.append(row)
            continue
        r = sub["retainedFrac"].to_numpy(float)
        row["medA"] = round(float(np.median(r)), 4)
        msets = {k: mk[k].loc[sub.index].to_numpy(bool) for k in sets}
        draws, skipped = paired_median_diffs(r, msets, sub[cluster_col].to_numpy(), nb, seed) if len(sub) >= 2 else ({k: np.array([]) for k in sets}, nb)
        row["skippedDraws"] = int(skipped)
        for k in sets:
            sel = msets[k]
            n_k, days_k = int(sel.sum()), int(sub.loc[sel, cluster_col].nunique())
            supported = n_k >= N_MIN and days_k >= DAYS_MIN
            cell = {"nAmb": n_k, "days": days_k, "supported": bool(supported)}
            if n_k:
                med_k = float(np.median(r[sel]))
                cell["med"] = round(med_k, 4)
                dd = draws[k]
                if supported and len(dd):
                    delta = 100.0 * (float(np.median(r)) - med_k)
                    lo_i, hi_i = (100.0 * float(np.percentile(dd, 2.5)), 100.0 * float(np.percentile(dd, 97.5)))
                    cell.update({"shiftPp": round(delta, 2), "ci95Pp": [round(lo_i, 2), round(hi_i, 2)], "relativeShift": (round(delta / (100.0 * float(np.median(r))), 3) if np.median(r) else None),
                                 "mdePp": round(2.8016 * 100.0 * float(np.std(dd, ddof=1)), 2), "verdict": verdict_shift(delta, lo_i, hi_i, True)})
                else:
                    cell["verdict"] = verdict_shift(0, 0, 0, False)
            else:
                cell["verdict"] = verdict_shift(0, 0, 0, False)
            row[k] = cell
        out.append(row)
    return out


# ---------------------------------------------------------------------------- tau (same filters and estimator as the published fit)
def fit_arrays(sub):
    f = sub.dropna(subset=["initExcessC", "residExcessC"])
    n_pre = int(len(f))
    f = f[(f["initExcessC"] > MIN_EXCESS) & (f["residExcessC"] > RESID_MIN)]
    return f.reset_index(drop=True), n_pre


def tau_set(sub, slope_fn, nb=NB_DEFAULT, seed=SEED):
    f, n_pre = fit_arrays(sub)
    res = {"nAmbBeforeFilter": n_pre, "nFit": int(len(f))}
    if len(f) < FIT_MIN:
        res["status"] = "not estimable (fewer than %d pairs after the filter)" % FIT_MIN
        return res, f
    x = f["gapH"].to_numpy(float)
    y = np.log(f["residExcessC"].to_numpy(float) / f["initExcessC"].to_numpy(float))
    slope = float(slope_fn(x, y))
    iso = pd.to_datetime(pd.Series(f["dayArrival"])).dt.isocalendar()
    isok = (iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)).to_numpy()
    blk = ST.soak_block(x, y, f["dayArrival"].to_numpy(), f["dayDeparture"].to_numpy(), isok, slope_fn, slope, published_row=None, b=nb, seed=seed)
    res.update({"slope": round(slope, 6), "decayRateK": blk["decayRateK"], "decayRateKCI": blk["decayRateKCI"], "tauH": (round(-1.0 / slope, 2) if slope < 0 else None),
                "tauCI": blk["tauCI"], "clusteringTable": [{k: r[k] for k in ("id", "nClusters", "tauCI", "decayRateKCI") if k in r} for r in blk["methodTable"]]})
    return res, f


def paired_k_diff(fA, in_sets, slope_fn, nb, seed):
    """Day-clustered paired bootstrap of k_set - k_A (k = -Sen slope) on the filtered fit pairs of A; in_sets: {name: bool array over fA}."""
    x = fA["gapH"].to_numpy(float)
    y = np.log(fA["residExcessC"].to_numpy(float) / fA["initExcessC"].to_numpy(float))
    codes, uniq = pd.factorize(fA["dayArrival"].to_numpy())
    groups = [np.where(codes == i)[0] for i in range(len(uniq))]
    rng = np.random.default_rng(seed)
    out = {k: [] for k in in_sets}
    for _ in range(nb):
        pick = rng.integers(0, len(groups), len(groups))
        idx = np.concatenate([groups[i] for i in pick])
        kA = -float(slope_fn(x[idx], y[idx]))
        for k, msk in in_sets.items():
            sel = idx[msk[idx]]
            if len(sel) < FIT_MIN:
                continue
            out[k].append(-float(slope_fn(x[sel], y[sel])) - kA)
    return {k: np.array(v) for k, v in out.items()}


def verdict_k(k_a, k_s, lo, hi):
    if k_a is None or k_s is None or k_s == 0:
        return "not estimable"
    excl = lo > 0 or hi < 0
    ratio = k_a / k_s
    if excl and (ratio < K_BAND[0] or ratio > K_BAND[1]):
        return "material"
    return "small" if excl else "not distinguishable"


def overall(e2, taus):
    supported_bins = [b for b in e2 if b.get("B", {}).get("supported")]
    if len(supported_bins) < 3:
        return "not established (fewer than 3 gap bins with support)"
    def mat(name):
        return [b.get(name, {}).get("verdict") == "material" for b in supported_bins]
    mb, mc = mat("B"), mat("C")
    tb, tc = taus.get("B", {}).get("verdictK") == "material", taus.get("C", {}).get("verdictK") == "material"
    if (any(mb) or tb) and (any(mc) or tc):
        return "sensitive to unlogged driving (lower bound): a supported bin or tau is material under B and under C"
    if not (any(mb) or tb or any(mc) or tc):
        return "no material shift detected at this support (lower bound)"
    return "mixed: material under one set only"


# ---------------------------------------------------------------------------- control V0
def v0_compare(pf, published, slope_fn, nb):
    """Set A reproduced here must equal the published block: counts, per-bin medians, tau fit counts and decay rate."""
    diffs = []
    if int(len(pf)) != published["nPairs"]:
        diffs.append("nPairs %d vs %d" % (len(pf), published["nPairs"]))
    if int(pf["retainedFrac"].notna().sum()) != published["nPairsAmbient"]:
        diffs.append("nPairsAmbient")
    for b in published["gapBins"]:
        sub = pf[bin_rows(pf, b["gapLoH"], 1e9 if b["gapHiH"] is None else b["gapHiH"])]
        rf = sub["retainedFrac"].dropna()
        mine = {"n": int(len(sub)), "nAmb": int(len(rf)), "medShedC": round(float(sub["shedC"].median()), 2), "medRetainedFrac": (round(float(rf.median()), 4) if len(rf) else None)}
        for k, v in mine.items():
            if b.get(k) != v:
                diffs.append("bin %s-%s %s: %r vs %r" % (b["gapLoH"], b["gapHiH"], k, v, b.get(k)))
    t, _ = tau_set(pf, slope_fn, nb)
    if t.get("nFit") != published.get("tauFitN"):
        diffs.append("tauFitN %s vs %s" % (t.get("nFit"), published.get("tauFitN")))
    if t.get("decayRateK") is not None and abs(t["decayRateK"] - published.get("soakDecayRateK", 0)) > 1e-5:
        diffs.append("decayRateK %s vs %s" % (t.get("decayRateK"), published.get("soakDecayRateK")))
    if t.get("decayRateKCI") is not None and nb == NB_DEFAULT and [round(v, 5) for v in t["decayRateKCI"]] != [round(v, 5) for v in published.get("soakDecayRateKCI", [])]:
        diffs.append("decayRateKCI %s vs %s" % (t.get("decayRateKCI"), published.get("soakDecayRateKCI")))
    return diffs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", default=os.path.join(ROOT, "drive_master.csv"))
    ap.add_argument("--gaps", default=os.path.join(ROOT, "analyses", "M729_cloud_gaps.csv"))
    ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "analyses"))
    ap.add_argument("--nb", type=int, default=NB_DEFAULT)
    ap.add_argument("--limit-drives", type=int, default=0)
    a = ap.parse_args(argv)
    if not os.path.exists(a.gaps) or not os.path.isdir(a.raw_dir):
        print("heatsoak_gap_sensitivity: no cloud gap table or raw directory, skipped (optional)")
        return 0
    t0 = time.time()
    try:
        if sha256(a.gaps) != GAPS_PIN:
            raise Stop("the M729 gap table differs from its pinned sha256")
        m0 = md5(a.master)
        if m0 != REGISTERED_MASTER:
            raise Stop("master MD5 %s differs from the registered master (a rerun on a new master needs its own spec addendum)" % m0)
        import compute_summary_arrays as C
        dm = pd.read_csv(a.master, low_memory=False)
        if a.limit_drives:
            dm = dm.iloc[: a.limit_drives].copy()
        cfg = json.load(open(os.path.join(ROOT, "summary_config.json"), encoding="utf-8"))
        idx = {re.sub(r"[^0-9]", "", os.path.basename(p)): os.path.join(a.raw_dir, p) for p in os.listdir(a.raw_dir) if p.lower().endswith(".csv")}

        def loader(fn):
            with open(idx[re.sub(r"[^0-9]", "", fn)], "rb") as f:
                return f.read()
        traj = C._battery_temp_traj(dm, loader)
        amb = {}
        for fn, pair in (cfg.get("ambientByDrive") or {}).items():
            try:
                amb[fn] = sum(float(x) for x in pair) / len(pair)
            except Exception:
                pass
        d = C._full_datetimes(dm).dropna(subset=["ts_full"]).sort_values("ts_full").reset_index(drop=True)
        pf = build_pairs(d, traj, amb)
        slope_fn = C._sen_slope
        published = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))["heatSoakCarryover"]
        v0 = {"status": "skipped (limited drive set)"} if a.limit_drives else {"differences": v0_compare(pf, published, slope_fn, a.nb)}
        if not a.limit_drives:
            own = C._heat_soak_carryover(dm, traj, cfg.get("ambientByDrive"))
            if json.dumps(own["gapBins"], sort_keys=True) != json.dumps(published["gapBins"], sort_keys=True):
                v0["differences"].append("the corpus function on this machine does not reproduce the published gapBins")
            v0["status"] = "reproduced" if not v0["differences"] else "FAILED"
            if v0["differences"]:
                raise Stop("control V0 failed: %s" % v0["differences"][:4])
        gaps = pd.read_csv(a.gaps)
        m, recon = join_classes(pf, gaps)
        mk = masks(m)
        comp = {}
        for lo, hi in BINS:
            sub = m[bin_rows(m, lo, hi)]
            cnt = sub["set"].value_counts().to_dict()
            comp["%s-%s" % (lo, "" if hi > 1e8 else hi)] = {"n": int(len(sub)), **{k: int(cnt.get(k, 0)) for k in ("S", "D", "U", "X")},
                                                          "dGapHoursShare": (round(float(sub.loc[sub["set"] == "D", "gapH"].sum() / sub["gapH"].sum()), 3) if sub["gapH"].sum() else None),
                                                          "dMedianHoursSinceLastMove": (round(float(sub.loc[sub["set"] == "D", "last_move_to_next_h"].median()), 2) if (sub["set"] == "D").any() else None),
                                                          "dMedianNominalGapH": (round(float(sub.loc[sub["set"] == "D", "gapH"].median()), 2) if (sub["set"] == "D").any() else None)}
        e2 = {"primaryArrivalDay": e2_bins(m, mk, "dayArrival", a.nb), "sensitivityDepartureDay": e2_bins(m, mk, "dayDeparture", a.nb),
              "sensitivityInitExcessAbove3C": e2_bins(m, mk, "dayArrival", a.nb, excess_min=3.0)}
        taus, fits = {}, {}
        for name in ("A",) + SET_NAMES:
            sub = m[mk[name]]
            taus[name], fits[name] = tau_set(sub, slope_fn, a.nb)
        fA = fits["A"]
        if len(fA) >= FIT_MIN:
            key = set(zip(fA["prev"], fA["next"]))
            in_sets = {}
            for name in SET_NAMES:
                keep = set(zip(m.loc[mk[name], "prev"], m.loc[mk[name], "next"]))
                in_sets[name] = np.array([(p, n) in keep for p, n in zip(fA["prev"], fA["next"])])
            dd = paired_k_diff(fA, in_sets, slope_fn, a.nb, SEED)
            for name in SET_NAMES:
                t = taus[name]
                if t.get("decayRateK") is None or not len(dd[name]):
                    t["verdictK"] = "not estimable"
                    continue
                lo_i, hi_i = float(np.percentile(dd[name], 2.5)), float(np.percentile(dd[name], 97.5))
                t["kShiftVsA"] = round(t["decayRateK"] - taus["A"]["decayRateK"], 5)
                t["kShiftCI95"] = [round(lo_i, 5), round(hi_i, 5)]
                t["kRatioAOverSet"] = round(taus["A"]["decayRateK"] / t["decayRateK"], 3) if t["decayRateK"] else None
                t["verdictK"] = verdict_k(taus["A"]["decayRateK"], t["decayRateK"], lo_i, hi_i)
        # descriptive contrast S versus D (confounded by season, time of day and end temperature; not a contamination effect, not a correction)
        base = m[m["retainedFrac"].notna()]
        contrast = []
        for lo, hi in BINS:
            sub = base[bin_rows(base, lo, hi)]
            s, dd_ = sub[sub["set"] == "S"], sub[sub["set"] == "D"]
            row = {"gapLoH": lo, "gapHiH": None if hi > 1e8 else hi, "nS": int(len(s)), "nD": int(len(dd_))}
            if len(s) >= N_MIN and len(dd_) >= N_MIN and s["dayArrival"].nunique() >= DAYS_MIN and dd_["dayArrival"].nunique() >= DAYS_MIN:
                days = sorted(sub["dayArrival"].unique())
                grp = {dd0: sub[sub["dayArrival"] == dd0] for dd0 in days}
                rng = np.random.default_rng(SEED)
                diffs = []
                for _ in range(a.nb):
                    pick = rng.integers(0, len(days), len(days))
                    cat = pd.concat([grp[days[i]] for i in pick])
                    ss, dd2 = cat[cat["set"] == "S"]["retainedFrac"], cat[cat["set"] == "D"]["retainedFrac"]
                    if len(ss) and len(dd2):
                        diffs.append(float(dd2.median() - ss.median()))
                row.update({"medianS": round(float(s["retainedFrac"].median()), 4), "medianD": round(float(dd_["retainedFrac"].median()), 4),
                            "diffDminusSPp": round(100.0 * (float(dd_["retainedFrac"].median()) - float(s["retainedFrac"].median())), 2),
                            "ci95Pp": [round(100.0 * float(np.percentile(diffs, 2.5)), 2), round(100.0 * float(np.percentile(diffs, 97.5)), 2)],
                            "label": "a class difference confounded by season, time of day and end temperature; not a contamination effect and not a correction"})
            else:
                row["status"] = "not estimable at this support"
            contrast.append(row)
        month_mix = {}
        for name in ("A", "B"):
            mm = m[mk[name]]["dayArrival"].str[:7].value_counts().sort_index()
            month_mix[name] = {k: int(v) for k, v in mm.items()}
        res = {"milestone": "M751", "spec": "analyses/M751_spec.md Rev 2", "role": "report-only sensitivity of the published heat-soak carryover to unlogged driving (lower bounds; exclusion only)",
               "masterMd5": m0, "registeredMasterMd5": REGISTERED_MASTER, "m729GapsSha256": GAPS_PIN, "seed": SEED, "nBoot": a.nb, "toolSha256": sha256(os.path.abspath(__file__)),
               "control_V0": v0, "reconciliation": recon, "unlogged_shares": {k: int((m["set"] == k).sum()) for k in ("S", "D", "U", "X")}, "d1PairsMovedKmAtLeast1": int(mk["D1"].sum()),
               "E1_composition_by_gap_bin": comp, "E2_retained_fraction_shift": e2, "E3_tau": taus, "E4_S_versus_D": contrast, "monthMixArrival": month_mix,
               "overall": overall(e2["primaryArrivalDay"], taus), "language": "estimated cloud-derived classes; lower bounds, not corrections; unlogged means no OBD record, not no driving",
               "scope": "report-only: no payload, dashboard or published figure changes", "seconds": round(time.time() - t0, 1)}
        if md5(a.master) != m0:
            raise Stop("drive_master.csv changed during the run")
        os.makedirs(a.out_dir, exist_ok=True)
        json.dump(res, open(os.path.join(a.out_dir, "M751_heatsoak_gap_sensitivity.json"), "w", encoding="utf-8", newline="\n"), indent=1, default=float)
        m[["prev", "next", "gapH", "cls", "set", "reason"]].round(3).to_csv(os.path.join(a.out_dir, "M751_heatsoak_pair_classes.csv"), index=False, lineterminator="\n")
        print("heatsoak_gap_sensitivity: %s; pairs %d; V0 %s; %.0f s" % (res["overall"], len(pf), v0["status"], res["seconds"]))
        return 0
    except Stop as e:
        print("heatsoak_gap_sensitivity: STOP (%s); nothing written" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
