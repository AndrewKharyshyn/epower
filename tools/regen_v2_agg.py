#!/usr/bin/env python3
"""M441 aggregation of the interval extractor v2 (spec analyses/M441_spec.md Rev 2.1): the OBSERVED apparent battery-side KE recovery by pack temperature, speed during braking and SOC band, with day-clustered
bootstrap uncertainty, support status and the ordered bridge from the legacy rule. Reads the per-drive cache only (tools/regen_v2_cache.py); every number comes from the cache arrays and the master.
Estimand per cell: 100 * sum(charge_kwh) / sum(ke_kwh) over the SAME intervals (ratio of sums; plateau intervals inside an episode carry charge and KE 0; trimmed plateaus are reported apart); assumed class masses; never clipped.
Bootstrap: calendar day = cluster, B = 4000, seed 42, one resample matrix per cohort shared by all cells. Support: supported = >= 200 strict-drop intervals AND >= 10 drives AND >= 5 days; thin otherwise; empty; failed (> 2.5 % of draws unidentified)."""
import hashlib, json, os, sys
import numpy as np
import pandas as pd
from scipy import sparse

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import regen_v2 as R
import regen_v2_cache as K

B_DRAWS, SEED, UNID_MAX = 4000, 42, 0.025
MIN_N, MIN_DRIVES, MIN_DAYS = 200, 10, 5
SOC_EDGES = [40, 50, 55, 60, 63, 66, 69, 72, 100]
SOC_SELS = ["noSocCondition", "allSoc"] + ["band %d-%d" % (a, b) for a, b in zip(SOC_EDGES[:-1], SOC_EDGES[1:])] + ["below40", "missingSoc"]
SPEED_LABELS = ["%d-%d" % (10 * j, 10 * j + 10) for j in range(13)] + [">=130"]
ZONES = [("<30", [0, 1, 2]), ("30-60", [3, 4, 5]), ("60-90", [6, 7, 8]), ("90-120", [9, 10, 11]), (">120", [12, 13])]
MASS_LO, MASS_HI = 1860.0, 1920.0


def load_master():
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    sdm = pd.read_csv("seasonal_drive_master.csv", low_memory=False).set_index("file")["thermal_regime"]
    return dm, dm["file"].map(sdm)


def temp_bins():
    import compute_summary_arrays as C
    return C.REGEN_TEMP_BINS


def soc_sel_masks(soc):
    fin = np.isfinite(soc)
    out = {"noSocCondition": np.ones(len(soc), bool), "allSoc": fin, "missingSoc": ~fin, "below40": fin & (soc < 40)}
    for a, b in zip(SOC_EDGES[:-1], SOC_EDGES[1:]):
        out["band %d-%d" % (a, b)] = fin & (soc >= a) & ((soc < b) | ((b == 100) & (soc <= 100)))
    return out


def onehot(idx, n):
    m = np.zeros((len(idx), n))
    ok = (idx >= 0) & (idx < n)
    m[np.where(ok)[0], idx[ok]] = 1.0
    return m


class Cohort:
    """Per-cohort tables and the shared bootstrap matrix."""

    def __init__(self, T, dm, mask_drive, label, days=None, row_mask=None, hold_from=None):
        self.label = label
        di = T["drive"]
        keep = mask_drive[di] if row_mask is None else (mask_drive[di] & row_mask)
        if days is not None:
            keep = keep & np.isin(dm["date"].astype(str).str[:10].values[di], np.asarray(days))
        self.keep = keep
        d = {k: v[keep] for k, v in T.items()}
        self.d = d
        self.drive = di[keep]
        days_all = dm["date"].astype(str).str[:10].values
        self.day_of = days_all[self.drive]
        self.days = np.array(days) if days is not None else (np.array(sorted(set(self.day_of[~d["iv_trimmed"]]))) if len(self.drive) else np.array([]))
        self.D = len(self.days)
        self.didx = np.searchsorted(self.days, self.day_of) if self.D else np.zeros(0, int)
        self.didx = np.clip(self.didx, 0, max(self.D - 1, 0))
        self.drives_u = np.unique(self.drive)
        self.pidx = np.searchsorted(self.drives_u, self.drive)
        import compute_summary_arrays as C
        mass = np.array([C._mass_for_drive(t, f) for t, f in zip(dm["drive_type"], dm["file"])])
        self.um = np.array([t in ("urban", "mixed") for t in dm["drive_type"]])[self.drive]
        self.mass = mass[self.drive]
        self.w = d["w"] if "w" in d else np.ones(len(self.drive))
        self.est = ~d["iv_trimmed"]
        self.strict = self.est & ~d["iv_plateau"]
        self.cad = dm["ev_rpm_dt_med_s"].map(lambda x: "unknown" if not np.isfinite(x) else ("fast" if x < 1.0 else "slow")).values[self.drive]
        if hold_from is not None:                              # PCL-1 holding rule (B4): protocol drives stay out of every cadence-stratified aggregate until the one-shot analysis has run
            self.cad = np.array(self.cad, dtype=object)
            self.cad[days_all[self.drive] >= hold_from] = "held"
        N = len(self.drive)
        self.Dm = sparse.csr_matrix((np.ones(N), (self.didx, np.arange(N))), shape=(max(self.D, 1), N)) if N else None
        self.Pm = sparse.csr_matrix((np.ones(N), (self.pidx, np.arange(N))), shape=(max(len(self.drives_u), 1), N)) if N else None
        rng = np.random.default_rng(SEED)
        idx = rng.integers(0, max(self.D, 1), (B_DRAWS, max(self.D, 1)))
        self.counts = np.zeros((B_DRAWS, max(self.D, 1)))
        for b in range(B_DRAWS):
            self.counts[b] = np.bincount(idx[b], minlength=max(self.D, 1))
        self.sel = soc_sel_masks(d["iv_soc"])
        tb = temp_bins()
        tp = d["iv_tpack"]
        self.tidx = np.full(len(tp), -1)
        for j, (lo, hi, _) in enumerate(tb):
            self.tidx[np.isfinite(tp) & (tp >= lo) & (tp < hi)] = j
        self.tlabels = [x[2] for x in tb]

    # -- contribution matrices (intervals x cells)
    def mats(self, view):
        d = self.d
        n = len(self.drive)
        if view in ("speed", "temperature"):
            pass
        if view == "speed":
            return {"dv2": d["bin_dv2"], "charge": d["bin_charge"], "chargeOff": d["bin_chargeOff"], "touch": d["bin_touch"].astype(float)}, SPEED_LABELS
        if view == "temperature":
            oh = onehot(self.tidx, len(self.tlabels))
            return {"dv2": oh * d["iv_dv2"][:, None], "charge": oh * d["iv_charge"][:, None], "chargeOff": oh * d["iv_chargeOff"][:, None], "touch": oh}, self.tlabels
        if view in ("speedStart", "speedEnd"):
            v = d["iv_v0"] if view == "speedStart" else d["iv_v1"]
            idx = np.minimum((np.maximum(v, 0) // 10).astype(int), 13)
            oh = onehot(idx, 14)
            return {"dv2": oh * d["iv_dv2"][:, None], "charge": oh * d["iv_charge"][:, None], "chargeOff": oh * d["iv_chargeOff"][:, None], "touch": oh}, SPEED_LABELS
        if view == "zones":
            m, _ = self.mats("speed")
            out = {}
            for k, a in m.items():
                if k == "touch":
                    out[k] = np.stack([(a[:, ix].sum(axis=1) > 0).astype(float) for _, ix in ZONES], axis=1)
                else:
                    out[k] = np.stack([a[:, ix].sum(axis=1) for _, ix in ZONES], axis=1)
            return out, [z for z, _ in ZONES]
        if view == "class":
            oh = onehot(d["iv_cls"].astype(int), 3)
            return {"dv2": oh * d["iv_dv2"][:, None], "charge": oh * d["iv_charge"][:, None], "chargeOff": oh * d["iv_chargeOff"][:, None], "touch": oh}, ["A start<10", "B start>=10 end<10", "C end>=10"]
        if view == "all":
            one = np.ones((n, 1))
            return {"dv2": d["iv_dv2"][:, None], "charge": d["iv_charge"][:, None], "chargeOff": d["iv_chargeOff"][:, None], "touch": one}, ["all"]
        raise KeyError(view)

    def sums(self, mats, mask):
        """Per-day (and per-drive) sums over the estimator population (non-trimmed, under mask): charge, offset charge, KE, urban/mixed KE, strict counts, plateau counts, zero-charge counts, seconds, drive presence."""
        m = (mask & self.est).astype(float) * self.w
        ms = (mask & self.strict).astype(float) * self.w
        mp = (mask & self.est & self.d["iv_plateau"]).astype(float) * self.w
        ke_mat = R.KE_FACTOR * self.mass[:, None] * mats["dv2"]
        Dm, Pm = self.Dm, self.Pm
        C = Dm @ (mats["charge"] * m[:, None]); Co = Dm @ (mats["chargeOff"] * m[:, None]); Kt = Dm @ (ke_mat * m[:, None]); Ku = Dm @ (ke_mat * (m * self.um)[:, None])
        Ns = Dm @ (mats["touch"] * ms[:, None]); Np = Dm @ (mats["touch"] * mp[:, None])
        Zs = Dm @ (mats["touch"] * (ms * (self.d["iv_charge"] <= 0))[:, None])
        Sec = Dm @ (mats["touch"] * (self.d["iv_dt"] * m)[:, None])
        Pd = Pm @ (mats["touch"] * ms[:, None])
        return C, Co, Kt, Ku, Ns, Np, Zs, Sec, Pd

    def cell_block(self, view, mask, mats=None, labels=None, cadmask=None):
        """Per-cell statistics for a view under an interval mask (already includes SOC selection). mask selects the estimator population (non-trimmed)."""
        if mats is None:
            mats, labels = self.mats(view)
        N = len(self.drive)
        if N == 0:
            return {}
        C, Co, Kt, Ku, Ns, Np, Zs, Sec, Pd = self.sums(mats, mask)
        out = {}
        ctot, ktot, kutot, cotot = C.sum(0), Kt.sum(0), Ku.sum(0), Co.sum(0)
        nbc, nbk = self.counts @ C, self.counts @ Kt
        with np.errstate(invalid="ignore", divide="ignore"):
            draws = np.where(nbk > 0, 100.0 * nbc / np.where(nbk > 0, nbk, 1.0), np.nan)
        for j, lab in enumerate(labels):
            n_sf = float(Ns[:, j].sum())                        # unrounded per-phase mean (M442 C4); outputs are rounded
            n_s, n_p = int(round(n_sf)), int(round(Np[:, j].sum()))
            days = int(((Ns[:, j] + Np[:, j]) > 0).sum()); drives = int((Pd[:, j] > 0).sum())
            if n_s + n_p == 0:
                out[lab] = {"n": 0, "nPlateau": 0, "drives": 0, "days": 0, "status": "empty"}
                continue
            k, c, ku = float(ktot[j]), float(ctot[j]), float(kutot[j])
            eff = 100.0 * c / k if k > 0 else None
            dr = draws[:, j]; fin = np.isfinite(dr)
            ci = None
            if fin.mean() >= 1 - UNID_MAX and fin.sum() > 0:
                ci = [round(float(np.percentile(dr[fin], 2.5)), 2), round(float(np.percentile(dr[fin], 97.5)), 2)]
            if k > 0 and (1 - fin.mean()) > UNID_MAX:
                status = "failed"
            elif n_sf >= MIN_N and drives >= MIN_DRIVES and days >= MIN_DAYS:
                status = "supported"
            else:
                status = "thin"
            kh = k - ku
            rng_ = [round(100.0 * c / (kh + ku * MASS_HI / 1890.0), 2), round(100.0 * c / (kh + ku * MASS_LO / 1890.0), 2)] if k > 0 else None
            cell = {"n": n_s, "nPlateau": n_p, "nZeroCharge": int(round(Zs[:, j].sum())), "drives": drives, "days": days, "seconds": round(float(Sec[:, j].sum()), 1), "keKwh": round(k, 5), "chargeKwh": round(c, 5),
                    "eff": None if eff is None else round(eff, 2), "ci95": ci, "precisionHalfWidth": None if ci is None else round((ci[1] - ci[0]) / 2.0, 2), "massRange": rng_,
                    "effOffset": None if k <= 0 else round(100.0 * float(cotot[j]) / k, 2), "status": status, "_ke": k, "_ch": c}
            if eff is not None and eff > 100.0:
                cell["flagAbove100"] = True
            out[lab] = cell
        return out

    def per_drive_eff(self):
        """Per-drive pooled ratio (percent) over the estimator population; used only to count drives above 100 % (reported, never clipped)."""
        ke = R.KE_FACTOR * self.mass * self.d["iv_dv2"] * self.est * self.w
        ch = self.d["iv_charge"] * self.est * self.w
        k = np.bincount(self.pidx, weights=ke, minlength=len(self.drives_u)); c = np.bincount(self.pidx, weights=ch, minlength=len(self.drives_u))
        return [100.0 * x / y for x, y in zip(c, k) if y > 0]

    def view_by_soc(self, view, sels=SOC_SELS, extra_mask=None):
        mats, labels = self.mats(view)
        res = {}
        for s in sels:
            mk = self.sel[s] if extra_mask is None else (self.sel[s] & extra_mask)
            res[s] = self.cell_block(view, mk, mats, labels)
        return res


def reconcile(cb):
    """G3: bands + below40 + missingSoc == noSocCondition, and allSoc == bands + below40, exactly in n / ke / charge for every cell of the view."""
    bad = {"nSoc": 0, "keKwh": 0.0, "chargeKwh": 0.0, "nAll": 0, "keAll": 0.0}
    parts = [s for s in SOC_SELS if s.startswith("band") or s in ("below40", "missingSoc")]
    for lab, base in cb["noSocCondition"].items():
        sm = {k: 0.0 for k in ("n", "nPlateau", "keKwh", "chargeKwh")}
        for s in parts:
            c = cb[s].get(lab, {})
            for k in sm:
                sm[k] += c.get({"keKwh": "_ke", "chargeKwh": "_ch"}.get(k, k), 0)
        for k in ("n", "nPlateau"):
            bad["nSoc"] = max(bad["nSoc"], abs(sm[k] - base.get(k, 0)))
        bad["keKwh"] = max(bad["keKwh"], abs(sm["keKwh"] - base.get("_ke", 0)))
        bad["chargeKwh"] = max(bad["chargeKwh"], abs(sm["chargeKwh"] - base.get("_ch", 0)))
        a = cb["allSoc"].get(lab, {})
        sm2 = sum(cb[s].get(lab, {}).get("_ke", 0) for s in parts if s != "missingSoc")
        bad["keAll"] = max(bad["keAll"], abs(sm2 - a.get("_ke", 0)))
        bad["nAll"] = max(bad["nAll"], abs(sum(cb[s].get(lab, {}).get("n", 0) for s in parts if s != "missingSoc") - a.get("n", 0)))
    return {k: (float("%.3g" % v) if isinstance(v, float) else v) for k, v in bad.items()}


def strip(o):
    """Remove the unrounded internal fields (_ke, _ch) from a nested result."""
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if k not in ("_ke", "_ch")}
    return o


def cohort_block(co, hdrs, files_in):
    n = len(co.drive)
    d = co.d
    out = {}
    est, strict = co.est, co.strict
    tot = co.cell_block("all", np.ones(n, bool))["all"] if n else {}
    ex = {}
    for fn in files_in:
        for k, v in hdrs[fn]["counts"].items():
            ex[k] = ex.get(k, 0) + v
    ex["tempUnsupported"] = int((est & (d["iv_nprobe"] < 4)).sum()); ex["socUnsupported"] = int((est & ~np.isfinite(d["iv_soc"])).sum())
    tr = d["iv_trimmed"]
    out["totals"] = dict(tot, nDrivesWithIntervals=int(len(co.drives_u)), nDaysWithIntervals=int(co.D), nStrict=int(strict.sum()), nPlateauKept=int((est & d["iv_plateau"]).sum()), nTrimmedPlateau=int(tr.sum()),
                         trimmedChargeKwh=round(float(d["iv_charge"][tr].sum()), 5), trimmedSeconds=round(float(d["iv_dt"][tr].sum()), 1), endsAtStandstillStrict=int((strict & d["iv_endsAtStandstill"]).sum()))
    out["exclusions"] = ex
    # Rev 2.2 disclosure: the estimator population excludes the trimmed leading/trailing plateau intervals; the ratio with them included is reported beside the headline
    _e, _s = co.est, co.strict
    co.est, co.strict = np.ones(n, bool), ~d["iv_plateau"]
    wt = co.cell_block("all", np.ones(n, bool))["all"]
    co.est, co.strict = _e, _s
    out["totals"]["withTrimmedPlateaus"] = {"eff": wt.get("eff"), "chargeKwh": wt.get("chargeKwh"), "keKwh": wt.get("keKwh"), "trimmedShareOfKeptCharge": round(float(d["iv_charge"][tr].sum()) / max(float(d["iv_charge"][est].sum()), 1e-12), 4)}
    out["totals"]["nDrivesAbove100"] = int(sum(1 for r_ in co.per_drive_eff() if r_ > 100.0))
    views = {}
    views["temperature"] = co.view_by_soc("temperature")
    views["speed"] = co.view_by_soc("speed", sels=["noSocCondition", "allSoc"] + SOC_SELS[2:-1])
    views["zones"] = co.view_by_soc("zones", sels=["noSocCondition", "allSoc"])
    views["speedStart"] = co.view_by_soc("speedStart", sels=["noSocCondition"])
    views["speedEnd"] = co.view_by_soc("speedEnd", sels=["noSocCondition"])
    views["class"] = co.view_by_soc("class", sels=["noSocCondition"])
    cadv = {}
    for reg in ("fast", "slow", "unknown"):
        mk = co.cad == reg
        cadv[reg] = {"temperature": co.view_by_soc("temperature", sels=["noSocCondition", "allSoc"], extra_mask=mk), "speed": co.view_by_soc("speed", sels=["noSocCondition", "allSoc"], extra_mask=mk),
                     "totals": co.cell_block("all", mk)}
    mix = {}
    tb = co.tlabels
    m_t, _ = co.mats("temperature")
    ke_t = R.KE_FACTOR * co.mass[:, None] * m_t["dv2"] * co.est[:, None]
    for j, lab in enumerate(tb):
        ktot = ke_t[:, j].sum(); ntot = (m_t["touch"][:, j] * co.strict).sum()
        if ktot <= 0:
            continue
        mix[lab] = {reg: {"keShare": round(float(ke_t[co.cad == reg, j].sum() / ktot), 4), "intervalShare": round(float((m_t["touch"][:, j] * co.strict)[co.cad == reg].sum() / max(ntot, 1)), 4)} for reg in ("fast", "slow", "unknown")}
    out["views"] = views
    out["cadence"] = {"byRegime": cadv, "mixByTemperatureBin": mix}
    out["reconciliation"] = {"temperature": reconcile(views["temperature"]), "speed": reconcile({**views["speed"], "missingSoc": co.cell_block("speed", co.sel["missingSoc"])})}
    # ordered bridge (computed from the v2 intervals by masks; each step adds one change)
    bridge = {}
    steps = [("S2_intervalIntegration", strict & ~d["iv_endsAtStandstill"], "speedEnd"), ("S3_plusStandstillEnds", strict, "speedEnd"), ("S4_plusPlateaus", est, "speedEnd"), ("S5_instantaneousBinning", est, "speed")]
    for name, mk, v in steps:
        bridge[name] = {"totals": co.cell_block("all", mk)["all"], "bySpeed": co.cell_block(v, mk), "byTemperature": co.cell_block("temperature", mk)}
    out["bridge"] = bridge
    return out


def oos_info(files, delta):
    """M442 support rule (C3): a drive is out of support if the 90 % quantile of its native speed, I or V sampling interval (positive intervals of at most 5 s) exceeds delta. Returns (mask, info)."""
    Tn, Hn = K.load(files, "base", with_off=False)
    oos = np.array([any(x > delta for x in (Hn[f]["cadence"].get("nativeDtQ90") or {}).values() if x == x) for f in files])
    ke_all = R.KE_FACTOR * 1890.0 * Tn["iv_dv2"] * ~Tn["iv_trimmed"]
    info = {"deltaS": delta, "nDrives": int(oos.sum()), "keShare": round(float(ke_all[oos[Tn["drive"]]].sum() / max(ke_all.sum(), 1e-12)), 4), "files": [f for f, o in zip(files, oos) if o][:50],
            "rule": "90 % quantile of the native speed, I or V sampling interval (positive intervals <= 5 s) > delta; more than 10 % of the native KE out of support blocks stage ME"}
    return oos, info


def protocol_hold(schedule="analyses/PCL1_schedule.csv", lock="analyses/PCL1_gate.lock"):
    """START DATE (ISO string) of the PCL-1 paired-cadence protocol while its one-shot analysis has not run, else None (spec analyses/PCL1_spec.md section 3, holding rule)."""
    if not os.path.exists(schedule) or os.path.exists(lock):
        return None
    import pcl_schedule as PS
    return PS.read(schedule)[0].isoformat()


def run(variant="base", cohorts=("all", "warm", "shoulder", "cold"), workers=5, stack=None, oos_delta=None, ens_clean=True):
    """variant: one cache variant; stack: a list of variants (e.g. the four grid phases) pooled with equal weight; oos_delta: M442 support rule - drives whose native speed, I or V sampling interval has a 90 % quantile above oos_delta are out of support."""
    dm, reg = load_master()
    files = list(dm["file"])
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    i_off = float(A["offsetUncertainty"]["pointEstimateA"])
    variants = list(stack) if stack else [variant]
    st = None
    for v in variants:
        st_ = K.ensure(files, i_off, variant=v, workers=workers)
        st = st or st_
    T, hdrs = K.load_stack(files, variants) if stack else K.load(files, variant=variant)
    res = {"extraction": {k: v for k, v in st.items() if k != "rawSha"}, "cohorts": {}}
    keep_drive = np.ones(len(dm), bool)
    hold = protocol_hold()
    if hold:
        res["protocolHold"] = {"startDate": hold, "rule": "PCL-1 holding rule: drives on or after the START DATE are excluded from the cadence-stratified (fast / slow / unknown) views until the one-shot analysis has run"}
    if oos_delta is not None:
        oos, res["outOfSupport"] = oos_info(files, oos_delta)
        keep_drive = ~oos
    for c in cohorts:
        mask = (np.ones(len(dm), bool) if c == "all" else (reg.values == c)) & keep_drive
        if mask.sum() == 0:
            continue
        co = Cohort(T, dm, mask, c, hold_from=hold)
        res["cohorts"][c] = cohort_block(co, hdrs, [f for f, m in zip(files, mask) if m])
    # ens-clean sensitivity (totals only, cohort all)
    if ens_clean and "ens_outlier_v2" in dm:
        clean = (~dm["ens_outlier_v2"].astype(bool)).values & keep_drive
        co = Cohort(T, dm, clean, "all-ensClean")
        res["sensitivityEnsClean"] = {"nDrives": int(clean.sum()), "totals": co.cell_block("all", np.ones(len(co.drive), bool))["all"], "temperature": co.view_by_soc("temperature", sels=["noSocCondition"])["noSocCondition"]}
    res = strip(res)
    return res, st


if __name__ == "__main__":
    import time
    t0 = time.time()
    res, st = run()
    print(json.dumps({"seconds": round(time.time() - t0, 1), "extraction": res["extraction"]})[:300])
    print(json.dumps(res["cohorts"]["all"]["totals"]))
    print(json.dumps(res["cohorts"]["all"]["reconciliation"]))
    for lab, c in res["cohorts"]["all"]["views"]["temperature"]["noSocCondition"].items():
        print(lab, {k: c.get(k) for k in ("n", "drives", "days", "eff", "ci95", "massRange", "status")})
