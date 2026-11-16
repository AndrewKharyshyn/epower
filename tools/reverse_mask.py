"""M698: inferred reverse-consistent episodes versus regeneration (spec analyses/M695_spec.md Rev 1.1 + section 12; descriptive payload block `reverseInference`).

Direction is NEVER observed: no gear / direction PID exists and the logged vehicle speed is unsigned. An episode is an INFERRED reverse-consistent episode, from standstill onset,
the sign of the commanded torque, d|speed| and (as validation V1) the battery current. Per-drive results are cached by raw sha256 (reverse_mask_cache/); aggregation never rereads raw.
Labels (mutually exclusive; precedence high to low): REGEN_TO_STOP 5, NEG_AT_STANDSTILL 4, REV_CAND 3, AMBIGUOUS_GAP 2, AMBIGUOUS_LOW 1, FORWARD 0.
"""
import copy, datetime, hashlib, json, os, sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
CACHE_DIR = os.path.join(ROOT, "reverse_mask_cache")
SPEC = "analyses/M695_spec.md"
VERSION = 1
SEED, NBOOT = 42, 4000
TOL_MS = 1500
RPM_OFF = 300.0
GAP_FACTOR = 3.0
REGEN_WINDOW_S = 3.0
MAX_DURATION_S = 120.0
MIN_MOVING = 2
MIN_VMAX = 2.0
BIN_KMH = 2.0
V3_SPEED = 40.0
LABELS = {0: "FORWARD", 1: "AMBIGUOUS_LOW", 2: "AMBIGUOUS_GAP", 3: "REV_CAND", 4: "NEG_AT_STANDSTILL", 5: "REGEN_TO_STOP"}
PRIMARY = {"cap": 15.0, "stand": 1.0, "k": 2, "tauScale": 1.0}
GRID = [("primary", {})] + [("cap%g" % c, {"cap": c}) for c in (10.0, 20.0)] + [("stand%g" % s, {"stand": s}) for s in (0.5, 2.0)] + [("k%d" % k, {"k": k}) for k in (1, 3)] + [("tau0x%g" % f, {"tauScale": f}) for f in (0.5, 2.0)]
MIN_DRIVES, MIN_DAYS, ESS_MIN = 10, 5, 10.0
TAU0_FILE = os.path.join(ROOT, "analyses", "M698_tau0.json")


# ------------------------------------------------------------------------------------------------ alignment
def pick_speed(D, df, t, source):
    """Speed series by source: 'vcm' = [VCM] Vehicle Speed only; 'obd' = the standard OBD vehicle speed (ECU-reported, integer km/h, never GPS); 'auto' = VCM when present, else OBD (spec Rev 1.2)."""
    vcm = D._series(df, t, "speed", lo=0, hi=260)
    obd = D._series(df, t, "speed_obd", lo=0, hi=260)
    if source == "vcm":
        return vcm, ("VCM" if vcm is not None else None)
    if source == "obd":
        return obd, ("OBD" if obd is not None else None)
    if vcm is not None:
        return vcm, "VCM"
    return obd, ("OBD" if obd is not None else None)


def aligned(csv_bytes, source="auto"):
    """Torque-sample grid: ts (s from the first timestamp), T, v (speed), rpm, I (HV battery current) by nearest-previous within 1500 ms (NaN otherwise, no interpolation);
    lastPos = time of the last native speed > 0 sample at or before each torque sample."""
    import compute_drive_summary_v6 as D
    df, t = D._prep_bytes(csv_bytes)
    tq = D._series(df, t, "target_torque")
    sp, src = pick_speed(D, df, t, source)
    if tq is None or sp is None:
        return None
    en = D._series(df, t, "eng_rpm", lo=0)
    cu = D._series(df, t, "I")
    if cu is not None:
        cu = cu[cu["v"].abs() < 900]
    t0 = min(tq["t"].min(), sp["t"].min())
    base = pd.DataFrame({"t": tq["t"].values, "T": tq["v"].values}).sort_values("t")
    tol = pd.Timedelta(milliseconds=TOL_MS)
    for name, s in (("v", sp), ("rpm", en), ("I", cu)):
        if s is None or len(s) == 0:
            base[name] = np.nan
        else:
            base = pd.merge_asof(base, pd.DataFrame({"t": s["t"].values, name: s["v"].values}).sort_values("t"), on="t", direction="backward", tolerance=tol)
    ts = (base["t"] - t0).dt.total_seconds().to_numpy(float)
    spt = (sp["t"] - t0).dt.total_seconds().to_numpy(float)
    pos = spt[sp["v"].to_numpy(float) > 0]
    last_pos = np.full(len(ts), np.nan)
    if len(pos):
        j = np.searchsorted(pos, ts, side="right") - 1
        last_pos = np.where(j >= 0, pos[np.clip(j, 0, len(pos) - 1)], np.nan)
    return {"speedSource": src, "ts": ts, "T": base["T"].to_numpy(float), "v": base["v"].to_numpy(float), "rpm": base["rpm"].to_numpy(float), "I": base["I"].to_numpy(float), "lastPos": last_pos}


# ------------------------------------------------------------------------------------------------ discriminator
def analyse(a, tau0, params=None, detail=False):
    """Labels and episodes for one drive and one parameter set. `a` = aligned arrays (see aligned)."""
    p = {**PRIMARY, **(params or {})}
    tau = tau0 * p["tauScale"]
    ts, T, v, rpm, I = a["ts"], a["T"], a["v"], a["rpm"], a["I"]
    n = len(ts)
    lab = np.zeros(n, dtype=int)
    if n < 3:
        return {"n": n, "episodes": [], "labelCounts": {}, "negCounts": {}}
    med_dt = float(np.median(np.diff(ts))) if n > 1 else 0.0
    gap_after = np.concatenate([np.diff(ts) > GAP_FACTOR * med_dt, [False]])
    ok = np.isfinite(v) & np.isfinite(T)
    # NEG_AT_STANDSTILL
    stand_neg = ok & (v == 0) & (T < -tau)
    lab = np.maximum(lab, np.where(stand_neg, 4, 0))
    # REGEN_TO_STOP: negative torque while speed falls and reaches 0 within 3 s
    for j in range(1, n):
        if ok[j] and v[j] == 0 and ok[j - 1] and v[j - 1] > 0:
            i = j - 1
            while i >= 0 and ok[i] and v[i] > 0 and ts[j] - ts[i] <= REGEN_WINDOW_S and (i == j - 1 or v[i] >= v[i + 1]):
                if T[i] < 0:
                    lab[i] = max(lab[i], 5)
                i -= 1
    # episodes
    episodes = []
    j1 = 1
    while j1 < n:
        if not (ok[j1] and v[j1] > 0 and ok[j1 - 1] and v[j1 - 1] == 0):
            j1 += 1
            continue
        s = j1 - 1
        while s - 1 >= 0 and ok[s - 1] and v[s - 1] == 0:
            s -= 1
        standstill = np.inf if s == 0 else ts[j1] - ts[s - 1]       # the drive start counts as standstill
        e = j1
        while e < n and ok[e] and v[e] > 0:
            e += 1                                                   # e = first index with speed 0 (or end of data)
        cand = T[j1] < -tau
        if cand and standstill >= p["stand"]:
            ke = max(p["k"], 2)
            kidx = list(range(j1, min(j1 + p["k"], e)))
            dyn = len(kidx) == p["k"] and all(T[i] < -tau for i in kidx) and (j1 + ke - 1 < e) and v[j1 + ke - 1] > v[j1]
            seg = slice(j1, e)
            vmax = float(np.nanmax(v[seg])) if e > j1 else 0.0
            dur = float(ts[min(e, n - 1)] - ts[j1])
            has_gap = bool(gap_after[max(j1 - 1, 0):max(e - 1, j1)].any())
            caps = vmax <= p["cap"] and dur <= MAX_DURATION_S and (e - j1) >= MIN_MOVING and vmax >= MIN_VMAX
            if dyn and caps and not has_gap:
                lab[seg] = np.maximum(lab[seg], 3)
                episodes.append({"j1": int(j1), "e": int(e), "tStart": float(ts[j1]), "duration": dur, "vmax": vmax, "nMoving": int(e - j1), "startFrac": float(ts[j1] / ts[-1]) if ts[-1] > 0 else None,
                                 "endFrac": float(ts[min(e, n - 1)] / ts[-1]) if ts[-1] > 0 else None, "onsetSample": int(s)})
            elif has_gap and dyn:
                lab[seg] = np.maximum(lab[seg], 2)
            else:
                lab[seg] = np.maximum(lab[seg], 1)               # a candidate that fails the dynamics rule or exceeds the caps
        j1 = max(e, j1 + 1)
    # AMBIGUOUS_LOW: negative torque at low speed with flat speed, not otherwise labelled
    low = ok & (v > 0) & (v <= p["cap"]) & (T < -tau)
    lab = np.maximum(lab, np.where(low, 1, 0))
    neg = ok & (T < 0)
    out = {"n": int(n), "episodes": episodes,
           "labelCounts": {LABELS[k]: int((lab == k).sum()) for k in LABELS}, "negCounts": {LABELS[k]: int(((lab == k) & neg).sum()) for k in LABELS},
           "tMin": float(np.nanmin(T[ok])) if ok.any() else None,
           "tMinExclRev": float(np.nanmin(T[ok & (lab != 3)])) if (ok & (lab != 3)).any() else None}
    if detail:
        out["labels"] = lab
    return out


def validation_inputs(a, tau0, lab_out):
    """Primary-run inputs of V1 (current), V3 (negative control above 40 km/h) per drive."""
    ts, T, v, rpm, I = a["ts"], a["T"], a["v"], a["rpm"], a["I"]
    tau = tau0
    n = len(ts)
    res = {"episodes": [], "regenBins": {}, "revBins": {}}
    d = -I                                                  # discharge positive (the project's Ah-throughput convention: Id = -(I + offset))
    stand = np.isfinite(v) & (v == 0) & np.isfinite(rpm) & (rpm < RPM_OFF) & np.isfinite(d)
    base_drive = float(np.mean(d[stand])) if stand.sum() >= 3 else None
    for ep in lab_out["episodes"]:
        j1, e, s = ep["j1"], ep["e"], ep["onsetSample"]
        idx = np.arange(j1, e)
        eng_off = bool(np.all(np.isfinite(rpm[idx]) & (rpm[idx] < RPM_OFF)))
        accel = idx[(T[idx] < -tau) & np.isfinite(d[idx])]
        pre = np.where((ts >= ts[s] - 5.0) & (ts <= ts[s]) & np.isfinite(d) & (v == 0))[0]
        base = float(np.mean(d[pre])) if len(pre) >= 1 else None
        rec = {"supported": bool(eng_off and len(accel) >= 2 and base is not None), "meanDischargeExcess": float(np.mean(d[accel]) - base) if (len(accel) >= 1 and base is not None) else None, "startFrac": ep["startFrac"], "endFrac": ep["endFrac"]}
        res["episodes"].append(rec)
        if base_drive is not None:
            for i in accel:
                if eng_off:
                    b = int(v[i] // BIN_KMH)
                    c = res["revBins"].setdefault(b, [0.0, 0])
                    c[0] += float(d[i] - base_drive); c[1] += 1
    lab = lab_out.get("labels")
    if lab is not None and base_drive is not None:
        for i in np.where((lab == 5) & np.isfinite(d) & np.isfinite(rpm) & (rpm < RPM_OFF) & np.isfinite(v))[0]:
            b = int(v[i] // BIN_KMH)
            c = res["regenBins"].setdefault(b, [0.0, 0])
            c[0] += float(d[i] - base_drive); c[1] += 1
    # V3: negative-torque onsets above 40 km/h following a speed decrease or coast; hit = the dynamics rule (k = 2: torque < -tau on two samples and speed rises) without caps
    on, hit = 0, 0
    for i in range(1, n - 1):
        if np.isfinite(v[i]) and v[i] > V3_SPEED and T[i] < -tau and (T[i - 1] >= -tau) and np.isfinite(v[i - 1]) and v[i] <= v[i - 1]:
            on += 1
            if T[i + 1] < -tau and np.isfinite(v[i + 1]) and v[i + 1] > v[i]:
                hit += 1
    res["v3"] = {"onsets": on, "hits": hit}
    return res


# ------------------------------------------------------------------------------------------------ corpus (cached)
def load_tau0():
    return json.load(open(TAU0_FILE, encoding="utf-8"))["tau0Nm"]


def drive_record(csv_bytes, tau0):
    a = aligned(csv_bytes)
    if a is None:
        return {"reason": "no_torque_or_speed"}
    rec = {"reason": None, "speedSource": a["speedSource"], "nSamples": int(len(a["ts"])), "medianDt": float(np.median(np.diff(a["ts"]))) if len(a["ts"]) > 1 else None, "duration": float(a["ts"][-1]) if len(a["ts"]) else 0.0}
    prim = analyse(a, tau0, detail=True)
    rec["variants"] = {"primary": {k: prim[k] for k in ("labelCounts", "negCounts", "tMin", "tMinExclRev") if k in prim}}
    rec["variants"]["primary"]["nEpisodes"] = len(prim["episodes"])
    rec["episodes"] = prim["episodes"]
    rec["validation"] = validation_inputs(a, tau0, prim)
    for name, par in GRID[1:]:
        r = analyse(a, tau0, par)
        rec["variants"][name] = {"labelCounts": r["labelCounts"], "nEpisodes": len(r["episodes"])}
    return rec


def corpus(raw_dir=None):
    import ah_throughput as AH
    tau0 = load_tau0()
    m = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), usecols=["file", "date", "ens_outlier_v2", "ens_invalid"], low_memory=False)
    clean = ~(m["ens_outlier_v2"].map(lambda x: x is True or x == "True") | m["ens_invalid"].map(lambda x: x is True or x == "True"))
    m = m[clean].reset_index(drop=True)
    cad = pd.read_csv(os.path.join(ROOT, "cadence_regime.csv"))
    reg = {r.file: (r.regime if isinstance(r.regime, str) else "unknown") for r in cad.itertuples()}
    sha_by, loader = AH.manifest_sha_lookup(), AH.raw_loader(raw_dir or os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    os.makedirs(CACHE_DIR, exist_ok=True)
    code = hashlib.sha256(open(__file__, "rb").read()).hexdigest()[:8]
    rows = []
    for _, r in m.iterrows():
        b = loader(r["file"])
        if b is None:
            continue
        sha = sha_by(r["file"]) or hashlib.sha256(b).hexdigest()
        cp = os.path.join(CACHE_DIR, "%s_v%d_%s_%g.json" % (sha, VERSION, code, tau0))
        if os.path.isfile(cp):
            rec = json.load(open(cp, encoding="utf-8"))
        else:
            rec = {"sha": sha, **drive_record(b, tau0)}
            json.dump(rec, open(cp, "w", encoding="utf-8"), separators=(",", ":"))
        rows.append({**rec, "file": r["file"], "date": str(r["date"])[:10], "regime": reg.get(r["file"], "unknown")})
    return rows


# ------------------------------------------------------------------------------------------------ aggregation (no raw)
def ess(w):
    w = np.asarray(w, float)
    return float(w.sum() ** 2 / np.sum(w ** 2)) if len(w) and np.sum(w ** 2) > 0 else 0.0


def status(nd, ndays, e):
    return "not shown" if (nd < MIN_DRIVES or ndays < MIN_DAYS) else ("exploratory" if e < ESS_MIN else "supported")


def day_boot(num_by_day, den_by_day, nboot=NBOOT, seed=SEED):
    """Percentile interval of sum(num) / sum(den) with calendar day as the resampling cluster."""
    days = sorted(set(num_by_day) | set(den_by_day))
    num = np.array([num_by_day.get(d, 0.0) for d in days], float)
    den = np.array([den_by_day.get(d, 0.0) for d in days], float)
    if den.sum() <= 0 or len(days) < 2:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(days), (nboot, len(days)))
    s, d = num[idx].sum(1), den[idx].sum(1)
    ok = d > 0
    return [round(float(np.percentile(s[ok] / d[ok], 2.5)), 4), round(float(np.percentile(s[ok] / d[ok], 97.5)), 4)]


def stratum_block(rows, nboot):
    use = [r for r in rows if r.get("nSamples", 0) >= 3]
    days = {r["date"] for r in use}
    wd = {}
    for r in use:
        wd[r["date"]] = wd.get(r["date"], 0.0) + r["nSamples"]
    blk = {"nDrives": len(use), "nDays": len(days), "essDays": round(ess(list(wd.values())), 3), "status": status(len(use), len(days), ess(list(wd.values())))}
    if not use:
        return blk
    prim = [r["variants"]["primary"] for r in use]
    tot = {k: sum(p["labelCounts"][k] for p in prim) for k in LABELS.values()}
    neg = {k: sum(p["negCounts"][k] for p in prim) for k in LABELS.values()}
    negall = sum(neg.values())
    eps = [(r["date"], e) for r in use for e in r["episodes"]]
    blk.update({"nSamples": int(sum(r["nSamples"] for r in use)), "labelCounts": tot, "negativeTorqueSamplesByLabel": neg, "nNegativeTorqueSamples": int(negall),
                "shareOfNegativeSamplesLabelledREV_CAND": round(neg["REV_CAND"] / negall, 5) if negall else None,
                "shareOfNegativeSamplesAMBIGUOUS": round((neg["AMBIGUOUS_LOW"] + neg["AMBIGUOUS_GAP"]) / negall, 5) if negall else None,
                "shareOfNegativeSamplesNegAtStandstill": round(neg["NEG_AT_STANDSTILL"] / negall, 5) if negall else None,
                "shareOfNegativeSamplesRegenToStop": round(neg["REGEN_TO_STOP"] / negall, 5) if negall else None,
                "nEpisodes": len(eps), "nDrivesWithEpisode": int(sum(1 for r in use if r["episodes"])), "episodesPerDrive": round(len(eps) / len(use), 4)})
    # V4: position in the drive: first or last 10 % of the drive time (episode start in the first 10 % or end in the last 10 %)
    num, den = {}, {}
    for d, e in eps:
        sf, ef = e.get("startFrac"), e.get("endFrac")
        hit = 1.0 if ((sf is not None and sf <= 0.10) or (ef is not None and ef >= 0.90)) else 0.0
        num[d] = num.get(d, 0.0) + hit
        den[d] = den.get(d, 0.0) + 1.0
    sh = sum(num.values()) / sum(den.values()) if den else None
    blk["V4_startOrEndShare"] = {"share": None if sh is None else round(sh, 4), "ci95": day_boot(num, den, nboot) if den else None, "nEpisodes": len(eps), "nDays": len(den),
                                 "supportsOwnerStatement": bool(sh is not None and (day_boot(num, den, nboot) or [0])[0] > 0.20) if len(eps) >= 10 else None}
    # V5: one-at-a-time max / min ratio of the episode count over the grid
    cnts = {name: int(sum(r["variants"][name]["nEpisodes"] for r in use)) for name, _ in GRID}
    pos = [c for c in cnts.values() if c > 0]
    v5 = {"episodeCountByVariant": cnts}
    if cnts["primary"] == 0:
        v5.update(status="not applicable (no primary episodes in this stratum)", passed=None)
    else:
        allpos = len(pos) == len(cnts)
        v5.update(maxOverMin=round(max(pos) / min(pos), 3) if allpos else None, passed=bool(allpos and max(pos) / min(pos) <= 1.5),
                  status="passed" if (allpos and max(pos) / min(pos) <= 1.5) else "FAILED (threshold-sensitive)")
        if allpos or pos:
            a_, b_ = max(cnts.values()), min(cnts.values())
            if b_ > 0 and a_ > b_:
                from scipy.stats import beta
                lo = beta.ppf(0.025, a_, b_ + 1)
                ratio_lo = lo / (1.0 - lo)
                v5["postHocSupplement"] = {"label": "POST HOC (allowed by the Director, never overrides the pre-registered verdict)", "method": "exact Clopper-Pearson interval on max / (max + min), converted to a ratio; lower bound shown",
                                           "ratioLowerBound95": round(float(ratio_lo), 3),
                                           "reading": "instability not distinguishable from small n" if ratio_lo <= 1.5 else "the max / min ratio exceeds 1.5 beyond Poisson noise"}
    blk["V5_stability"] = v5
    # V1: supported episodes, mean discharge excess > 0 (after the standstill baseline)
    sup = [(r["date"], x) for r in use for x in r["validation"]["episodes"] if x["supported"] and x["meanDischargeExcess"] is not None]
    nd = len({d for d, _ in sup})
    if len(sup) >= 10 and nd >= 5:
        fail = sum(1 for _, x in sup if x["meanDischargeExcess"] <= 0)
        blk["V1_currentSign"] = {"nSupportedEpisodes": len(sup), "nDays": nd, "shareFailing": round(fail / len(sup), 4), "falsifierThreshold": 0.10, "falsified": bool(fail / len(sup) > 0.10)}
    else:
        blk["V1_currentSign"] = {"nSupportedEpisodes": len(sup), "nDays": nd, "status": "not testable (fewer than 10 supported episodes on 5 days)"}
    bins = {}
    for r in use:
        for kind in ("revBins", "regenBins"):
            for b, (s, c) in r["validation"].get(kind, {}).items():
                bins.setdefault(int(b), {"revBins": [], "regenBins": []})[kind].append(s / c)
    matched = []
    for b, kv in sorted(bins.items()):
        if len(kv["revBins"]) >= 10 and len(kv["regenBins"]) >= 10:
            matched.append({"speedBinKmh": [b * BIN_KMH, (b + 1) * BIN_KMH], "nDrivesREV": len(kv["revBins"]), "nDrivesRegen": len(kv["regenBins"]),
                            "medianDischargeExcessREV": round(float(np.median(kv["revBins"])), 3), "medianDischargeExcessRegenToStop": round(float(np.median(kv["regenBins"])), 3),
                            "revAboveRegen": bool(np.median(kv["revBins"]) > np.median(kv["regenBins"]))})
    blk["V1_matchedSpeedBins"] = matched if matched else "not testable (no speed bin with at least 10 drives in both classes)"
    # V3 negative control
    on = sum(r["validation"]["v3"]["onsets"] for r in use)
    hit = sum(r["validation"]["v3"]["hits"] for r in use)
    blk["V3_negativeControlAbove40kmh"] = {"onsets": int(on), "hits": int(hit), "hitRate": round(hit / on, 5) if on else None, "falsifierThreshold": 0.01,
                                           "status": "not testable (fewer than 50 onsets)" if on < 50 else ("falsified" if hit / on > 0.01 else "not falsified")}
    # torque minimum with inferred reverse excluded (flagged sensitivity input, per drive)
    tm = [(r["variants"]["primary"].get("tMin"), r["variants"]["primary"].get("tMinExclRev")) for r in use if r["variants"]["primary"].get("tMin") is not None]
    blk["torqueMinimumSensitivity"] = {"nDrives": len(tm), "nDrivesWhereMinimumIsInsideAnEpisode": int(sum(1 for a, b in tm if b is not None and b > a + 1e-9)),
                                       "note": "per-drive minimum of the commanded torque with and without the samples inside inferred reverse-consistent episodes; the published records block is not changed"}
    return blk


def source_verdict(src_block, concordant):
    fals = []
    for reg, st in src_block.items():
        if reg == "all" or not isinstance(st, dict):
            continue
        if st.get("V1_currentSign", {}).get("falsified"):
            fals.append("V1 (%s)" % reg)
        if st.get("V3_negativeControlAbove40kmh", {}).get("status") == "falsified":
            fals.append("V3 (%s)" % reg)
        if st.get("V5_stability", {}).get("passed") is False:
            fals.append("V5 (%s)" % reg)
    txt = ("falsified by " + ", ".join(fals)) if fals else "not falsified by V1 to V5 (V6, the overlap with the regeneration events, is a separate step; a pass is never worded as validated)"
    if not concordant:
        txt += "; descriptive only, speed source not concordant"
    return {"discriminatorFalsifiedBy": fals, "text": txt}


def aggregate(rows, nboot=NBOOT):
    tau = json.load(open(TAU0_FILE, encoding="utf-8"))
    tau_obd = json.load(open(TAU0_FILE.replace("M698_tau0.json", "M698_tau0_obd.json"), encoding="utf-8"))
    conc = json.load(open(os.path.join(ROOT, "analyses", "M698_speed_concordance.json"), encoding="utf-8"))
    blk = {"label": "inferred reverse-consistent episodes versus regeneration (inferred from standstill onset, the commanded-torque sign, d|speed| and battery current; direction is never observed; the owner statement is an assumption under test)",
           "spec": SPEC + " Rev 1.2 final (sections 11 to 14)", "status": "exploratory",
           "parameters": {**PRIMARY, "tau0Nm": tau["tau0Nm"], "tau0File": "analyses/M698_tau0.json", "regenWindowS": REGEN_WINDOW_S, "maxDurationS": MAX_DURATION_S, "minMoving": MIN_MOVING, "minVmaxKmh": MIN_VMAX, "gapFactor": GAP_FACTOR},
           "sensitivityGrid": [n for n, _ in GRID],
           "deviation": "Rev 1.2 (disclosed): coverage prompted the extension of the speed source: VCM speed where the PID exists, else the standard OBD vehicle speed (ECU-reported, integer km/h, not GPS); 663 canonical-clean drives here against 665 master drives; the VCM stratum is the pre-registered first pass; the first-pass outcome counts were known before the extension; tau0 stays frozen",
           "tau0PerSourceDescriptive": {"VCM": tau["tau0Nm"], "OBD": tau_obd["tau0Nm"], "obdFile": "analyses/M698_tau0_obd.json", "insideGrid": bool(0.5 * tau["tau0Nm"] <= tau_obd["tau0Nm"] <= 2.0 * tau["tau0Nm"]), "substituted": False},
           "speedConcordance": {"file": "analyses/M698_speed_concordance.json", "status": conc["status"], "nDrivesWithBoth": conc["nDrivesWithBoth"], "corpus": conc.get("corpus"), "limits": conc["limits"]},
           "strata": {}, "verdict": {}}
    concordant = conc["status"] == "concordant"
    for src in ("VCM", "OBD"):
        rs = [r for r in rows if r.get("speedSource") == src]
        if not rs:
            continue
        sb = {"all": stratum_block(rs, nboot)}
        for reg in ("fast", "slow", "unknown"):
            rr = [r for r in rs if r["regime"] == reg]
            if rr:
                sb[reg] = stratum_block(rr, nboot)
        blk["strata"][src] = sb
        blk["verdict"][src] = source_verdict(sb, concordant if src == "OBD" else True)
    blk["verdict"]["pooledAcrossSources"] = "none (no pooled verdict across speed sources)"
    blk["verdict"]["ownerStatement"] = "supported by V4 only if the lower bound of the start-or-end share exceeds 0.20 (see strata.<source>.<stratum>.V4_startOrEndShare); the pattern expected from the owner answers is frozen in spec section 12"
    blk["reading"] = ["an episode is an INFERRED reverse-consistent episode: no gear or direction channel exists and the logged speed is unsigned; the share labelled REV_CAND under the frozen rule is always shown next to the AMBIGUOUS share",
                      "the torque is the commanded / logged (app-calculated) register; tau0 is the standstill noise floor of that register fixed in a separate earlier run",
                      "every rate is stratified by speed source and cadence regime; there is no pooled verdict across speed sources",
                      "V5 (stability over the sensitivity grid) is applied as pre-registered; the Poisson supplement is labelled post hoc and never overrides it",
                      "the sensitivities with inferred reverse excluded for the exposed blocks and the overlap with the regeneration events (V6) are separate flagged steps; no published figure is changed here"]
    return blk


def stamp(A, md5):
    import stamp_common as _sc
    old = (A.get("_artifactStamps") or {}).get("reverseInference")
    st = copy.deepcopy(A["_artifactStamps"]["headroomUtilization"]) if "headroomUtilization" in A.get("_artifactStamps", {}) else {}
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for k in ("carriedForward", "recomputeMode", "corpusSizeAtRecompute"):
        st.pop(k, None)
    st.update(corpusHash=md5, generatedAt=now, computationStatus="computed", upstreamHashes={"driveMasterMd5": md5},
              computationStatusNote="M698: derived by tools/reverse_mask.py from raw drive CSVs (cached by sha256), drive_master.csv, cadence_regime.csv and analyses/M698_tau0.json (spec analyses/M695_spec.md Rev 1.1); inferred, exploratory")
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A["_artifactStamps"]["reverseInference"] = _sc.carry_declared(old, st)


def splice(A, block, md5):
    old = copy.deepcopy(A)
    A["reverseInference"] = block
    stamp(A, md5)
    chk = copy.deepcopy(A); chk.pop("reverseInference"); chk["_artifactStamps"].pop("reverseInference")
    o2 = copy.deepcopy(old); o2.pop("reverseInference", None); o2.setdefault("_artifactStamps", {}).pop("reverseInference", None)
    assert chk == o2, "unexpected change outside /reverseInference"
    return A


def main(argv):
    raw_dir = argv[argv.index("--raw-dir") + 1] if "--raw-dir" in argv else None
    rows = corpus(raw_dir)
    nb = 400 if "--dry-run" in argv else NBOOT
    block = aggregate(rows, nb)
    md5 = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    block["provenance"] = {"masterMd5": md5, "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "tau0Sha256": hashlib.sha256(open(TAU0_FILE, "rb").read()).hexdigest(), "seed": SEED, "nBoot": nb,
                           "specSha256": "see the CHANGELOG entries of M695 and M696", "nDrivesWithRawRecord": len(rows)}
    if "--out" in argv:
        json.dump(block, open(argv[argv.index("--out") + 1], "w", encoding="utf-8"), indent=1, default=str)
        print("wrote block")
        return
    if "--dry-run" in argv:
        print(json.dumps({src: {reg: {k: st.get(k) for k in ("nDrives", "nEpisodes", "V1_currentSign", "V3_negativeControlAbove40kmh", "V4_startOrEndShare", "V5_stability")} for reg, st in sb.items()} for src, sb in block["strata"].items()}, default=str)[:6000])
        print(json.dumps(block["verdict"]))
        return
    p = os.path.join(ROOT, "summary_arrays.json")
    raw = open(p, encoding="utf-8", newline="").read()
    A = splice(json.loads(raw), block, md5)
    open(p, "w", encoding="utf-8", newline="").write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    print(json.dumps({"changed": True}))


if __name__ == "__main__":
    main(sys.argv[1:])
