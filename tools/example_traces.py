#!/usr/bin/env python3
"""M795 (analyses/M795_spec.md Rev 2): three single-drive example traces on the master's 1 s alignment, chosen by fixed rules (not averages, not typical cases).
T8 = the longest engine-off run named by S.evTraction.runMax (a record), T7 = rotation / pack power / coolant window around a first engine start, T9 = power burst under acceleration at highway speed.
The only writer of S.exampleTraces (additive splice with a stamp). The selection is FROZEN: master MD5, candidate / eligible counts and the median are recorded; --check reports a stale selection and never re-selects.
Usage: python tools/example_traces.py [--dry-run | --splice | --check]"""
import copy, datetime, hashlib, inspect, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

ARR = os.path.join(ROOT, "summary_arrays.json")
PRE_S, WIN_T7_S, WIN_T9_HALF_S, MARGIN_T8_S = 30, 300, 30, 30
COV_MIN = 0.95
CHARGE_KW, DISCH_KW, SIGN_MIN_S = 1.0, 1.0, 20
PEDAL_MIN, PEDAL_LOOK_S, HIGHWAY_KMH, GAP_GUARD_S = 10.0, 5, 80.0, 3
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
SPEC_REV = "analyses/M795_spec.md Rev 2"


# ---------------------------------------------------------------- pure kernels (unit-tested)
def debounce(state, n):
    """boolean array; runs shorter than n samples (not at the start) take the previous state (same as compute_drive_summary_v6._ev_debounce)."""
    s = np.asarray(state, dtype=np.int8).copy()
    if len(s) == 0:
        return s.astype(bool)
    chg = np.flatnonzero(np.diff(s)) + 1
    for a, b in zip(np.r_[0, chg], np.r_[chg, len(s)]):
        if (b - a) < n and a > 0:
            s[a:b] = s[a - 1]
    return s.astype(bool)


def longest_off_run(rpm, speed, k, deb_s=3, min_km=0.05):
    """the master's engine-off run rule on a 1 s grid: off = debounced (known and rpm <= 400) and known; runs are maximal contiguous off intervals; distance = sum(speed/3600) * k.
    Returns {a, b (half-open grid index), km, n, rawAbove400} of the longest run by distance, or None."""
    rpm = np.asarray(rpm, float); speed = np.asarray(speed, float)
    known = np.isfinite(rpm)
    off = debounce(known & (np.where(known, rpm, 0.0) <= 400), deb_s) & known
    dkm = np.nan_to_num(speed, nan=0.0) / 3600.0
    best = None
    i, n = 0, len(off)
    while i < n:
        if not off[i]:
            i += 1; continue
        j = i
        while j < n and off[j]:
            j += 1
        d = float(dkm[i:j].sum()) * k
        if d >= min_km and (best is None or d > best["km"]):
            best = {"a": i, "b": j, "km": d, "n": j - i, "rawAbove400": int(np.nansum(rpm[i:j] > 400))}
        i = j
    return best


def first_start_window(rpm, pre=PRE_S, length=WIN_T7_S):
    """index a of the window [a, a+length) that starts `pre` s before the first engine start (first grid second with rpm > 400 after `pre` known seconds with rpm <= 400), or None; the window must lie inside the grid."""
    rpm = np.asarray(rpm, float)
    for i in range(pre, len(rpm)):
        if np.isfinite(rpm[i]) and rpm[i] > 400:
            prev = rpm[i - pre:i]
            if np.all(np.isfinite(prev)) and np.all(prev <= 400):
                a = i - pre
                return a if a + length <= len(rpm) else None
    return None


def sign_seconds(rpm, p_kw, tq):
    """(discharge seconds, charge seconds) while engine rotation is above 400 rpm; a charge second counts only when the logged target torque is >= 0 (motor not braking) and known."""
    rpm = np.asarray(rpm, float); p = np.asarray(p_kw, float); tq = np.asarray(tq, float)
    on = np.isfinite(rpm) & (rpm > 400)
    d = int((on & np.isfinite(p) & (p > DISCH_KW)).sum())
    c = int((on & np.isfinite(p) & (p < -CHARGE_KW) & np.isfinite(tq) & (tq >= 0)).sum())
    return d, c


def coverage(*arrs):
    return min(float(np.isfinite(np.asarray(a, float)).mean()) for a in arrs)


def closest_to_median(vals, keys):
    """index of the value closest to the median; ties by the smaller key (earlier date)."""
    v = np.asarray(vals, float); med = float(np.median(v))
    dist = np.abs(v - med); best = np.flatnonzero(dist == dist.min())
    return int(min(best, key=lambda i: keys[i])), med


def peak_eligible(p_kw, speed, pedal, a, n_pre=PEDAL_LOOK_S, gap=GAP_GUARD_S, half=WIN_T9_HALF_S):
    """for the drive's peak discharge second (a = grid index): window inside the grid, speed >= highway threshold at the peak, pedal above the minimum in at least one of the `n_pre` seconds before the peak, no gap (non-finite drawn channel) within `gap` s of the peak."""
    n = len(p_kw)
    if a - half < 0 or a + half + 1 > n:
        return False
    lo, hi = max(0, a - gap), min(n, a + gap + 1)
    for ch in (p_kw, speed, pedal):
        if not np.all(np.isfinite(np.asarray(ch, float)[lo:hi])):
            return False
    if not (speed[a] >= HIGHWAY_KMH):
        return False
    pre = np.asarray(pedal, float)[max(0, a - n_pre):a]
    return bool(np.any(np.isfinite(pre) & (pre > PEDAL_MIN)))


# ---------------------------------------------------------------- data access
def _src_hash():
    fs = (debounce, longest_off_run, first_start_window, sign_seconds, coverage, closest_to_median, peak_eligible, grid_drive, window_json)
    return hashlib.sha256("".join(inspect.getsource(f) for f in fs).encode()).hexdigest()[:16]


def grid_drive(b):
    """1 s grid channels of a drive (master alignment: nearest sample within ENG_ALIGN_TOL; pack power as the master pairs it, discharge positive). Returns dict of arrays plus start time, or None."""
    import compute_drive_summary_v6 as D
    df, t = D._prep_bytes(b)
    tv = t.dropna()
    if len(tv) < 10:
        return None
    grid = pd.DataFrame({"t": pd.date_range(tv.min(), tv.max(), freq="1s")})
    if len(grid) < 10:
        return None
    tol = pd.Timedelta(D.ENG_ALIGN_TOL)
    spd = D._series(df, t, "speed", lo=0, hi=260)
    if spd is None or len(spd) < 20:
        spd = D._series(df, t, "speed_obd", lo=0, hi=260)
    ch = {"speed": spd, "rpm": D._series(df, t, "eng_rpm", lo=0), "coolant": D._series(df, t, "T_eng_coolant"), "torque": D._series(df, t, "target_torque")}
    pe = [c for c in df.columns if str(c).startswith("Положення педалі акселератора D")]
    if pe:
        m = df[pe[0]].notna()
        ch["pedal"] = pd.DataFrame({"t": t[m].values, "v": df.loc[m, pe[0]].astype(float).values}).sort_values("t").reset_index(drop=True) if m.any() else None
    else:
        ch["pedal"] = None
    I = D._series(df, t, "I")
    if I is not None:
        I = I[I["v"].abs() < 900]
    V = D._series(df, t, "V", lo=200, hi=450)
    ch["power"] = None
    if I is not None and V is not None and len(I) > 50:
        e = D._asof(I.copy(), V, "V", D.V_ALIGN_TOL).dropna(subset=["V"])
        ch["power"] = pd.DataFrame({"t": e["t"].values, "v": (-e["v"] * e["V"] / 1000.0).values}).sort_values("t").reset_index(drop=True)
    g = grid
    for k, s in ch.items():
        if s is None:
            g[k] = np.nan
        else:
            g = pd.merge_asof(g, s.rename(columns={"v": k}), on="t", direction="nearest", tolerance=tol)
    odo = D._series(df, t, "odo")
    dist_odo = float(odo["v"].max() - odo["v"].min()) if odo is not None and len(odo) else np.nan
    dist_int = float(np.nan_to_num(g["speed"].to_numpy(float), nan=0.0).sum() / 3600.0)
    k = dist_odo / dist_int if (dist_int > 0 and np.isfinite(dist_odo) and dist_odo > 0) else 1.0
    return {"t0": g["t"].iloc[0], "k": float(k), **{c: g[c].to_numpy(float) for c in ("speed", "rpm", "coolant", "torque", "pedal", "power")}, "has": {c: ch[c] is not None for c in ch}}


def _r(x):
    return [None if not np.isfinite(v) else round(float(v), 2) for v in x]


def window_json(G, a, b, chans):
    return {"t": list(range(0, b - a)), **{name: _r(G[src][a:b]) for name, src in chans}}


def month_label(date_str):
    """month and year of the drive from the master's date column (the grid clock carries no calendar date)."""
    y, m = int(str(date_str)[:4]), int(str(date_str)[5:7])
    return f"{MONTHS[m - 1]} {y}"


def load_inputs():
    import ah_throughput as AH
    import compute_summary_arrays as C
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    cr = pd.read_csv("cadence_regime.csv")[["file", "regime"]]
    cad = dict(zip(cr.file, cr.regime))
    bad = C._canonical_bad(dm)
    return dm, cad, bad, AH.raw_loader()


def select_all(dm, cad, bad, loader):
    A = json.load(open(ARR, encoding="utf-8"))
    rm = A["evTraction"]["runMax"]
    out = {"T8": None, "T7": None, "T9": None}
    sel = {"T7": {"candidates": 0, "eligible": 0}, "T9": {"candidates": 0, "eligible": 0}}
    c7, c9 = [], []
    prov = {}
    for i, r in dm.iterrows():
        fn = r["file"]
        isfast = cad.get(fn) == "fast"
        need = (fn == rm["file"]) or (isfast and not bool(bad.iloc[i]))
        if not need:
            continue
        b = loader(fn)
        if b is None:
            continue
        G = grid_drive(b)
        if G is None:
            continue
        digest = hashlib.sha256(b).hexdigest()
        if fn == rm["file"]:
            run = longest_off_run(G["rpm"], G["speed"], G["k"])
            assert run is not None, "T8 run not found"
            a, e = max(0, run["a"] - MARGIN_T8_S), min(len(G["rpm"]), run["b"] + MARGIN_T8_S)
            out["T8"] = {"date": str(r["date"]), "G": G, "run": run, "a": a, "b": e, "file": fn, "sha": digest, "cadence": cad.get(fn, "unknown")}
        if not (isfast and not bool(bad.iloc[i])):
            continue
        # T7 candidate: first engine start with the full window and channel coverage
        a7 = first_start_window(G["rpm"], PRE_S, WIN_T7_S)
        if a7 is not None and all(G["has"][c] for c in ("speed", "rpm", "power", "coolant", "torque")):
            sl = slice(a7, a7 + WIN_T7_S)
            if coverage(G["speed"][sl], G["rpm"][sl], G["power"][sl], G["coolant"][sl], G["torque"][sl]) >= COV_MIN:
                sel["T7"]["candidates"] += 1
                d, c = sign_seconds(G["rpm"][sl], G["power"][sl], G["torque"][sl])
                if d >= SIGN_MIN_S and c >= SIGN_MIN_S:
                    sel["T7"]["eligible"] += 1
                    c7.append({"file": fn, "date": str(r["date"]), "a": a7, "engineOnS": int((G["rpm"][sl] > 400).sum()), "dischargeS": d, "chargeS": c, "G": G, "sha": digest})
        # T9 candidate: the drive's peak discharge second
        if all(G["has"][c] for c in ("speed", "rpm", "power", "pedal")) and np.isfinite(G["power"]).any():
            a9 = int(np.nanargmax(G["power"]))
            sel["T9"]["candidates"] += 1
            if peak_eligible(G["power"], G["speed"], G["pedal"], a9):
                sl = slice(a9 - WIN_T9_HALF_S, a9 + WIN_T9_HALF_S + 1)
                if coverage(G["speed"][sl], G["rpm"][sl], G["power"][sl], G["pedal"][sl]) >= COV_MIN:
                    sel["T9"]["eligible"] += 1
                    c9.append({"file": fn, "date": str(r["date"]), "a": a9, "peakKw": float(G["power"][a9]), "G": G, "sha": digest})
    assert out["T8"] is not None, "T8 drive not processed"
    if c7:
        j, med = closest_to_median([x["engineOnS"] for x in c7], [x["date"] + x["file"] for x in c7])
        out["T7"] = c7[j]; sel["T7"]["medianEngineOnS"] = med
    if c9:
        j, med = closest_to_median([x["peakKw"] for x in c9], [x["date"] + x["file"] for x in c9])
        out["T9"] = c9[j]; sel["T9"]["medianPeakKw"] = round(med, 3)
    return out, sel, rm


def build_block(out, sel, rm, dm):
    t8, t7, t9 = out["T8"], out["T7"], out["T9"]
    G8 = t8["G"]; run = t8["run"]
    # known answers for T8 (STOP on a miss)
    assert run["n"] == rm["durationS"] or abs(run["n"] - rm["durationS"]) <= 1, ("T8 duration", run["n"], rm["durationS"])
    assert abs(run["km"] - rm["km"]) <= 0.01, ("T8 km", run["km"], rm["km"])
    off_deb = debounce(np.isfinite(G8["rpm"]) & (np.nan_to_num(G8["rpm"], nan=0.0) <= 400), 3)
    assert off_deb[run["a"]:run["b"]].all()
    d8 = G8["t0"] + pd.Timedelta(seconds=t8["a"])
    T8 = {"label": "longest engine-off run in the log (a record)", "month": month_label(t8["date"]), "cadence": t8["cadence"],
          "run": {"startS": run["a"] - t8["a"], "endS": run["b"] - t8["a"], "durationS": int(run["n"]), "km": round(run["km"], 2), "rawRpmAbove400Seconds": run["rawAbove400"],
                  "debouncedEngineOnSeconds": int((~off_deb[run["a"]:run["b"]]).sum())},
          **window_json(G8, t8["a"], t8["b"], [("speed", "speed"), ("rpm", "rpm")])}
    block = {"_provenance": "GENERATED by tools/example_traces.py (M795). Do not hand-edit.", "schemaVersion": 1, "specRev": SPEC_REV,
             "basis": "raw bytes through the master's 1 s alignment (nearest sample within 3 s, gaps left as null); logged channels (app-reported), pack power from logged current x voltage as the master pairs them; raw/ = sha256-verified originals (M366)",
             "rule": {"T8": "the run named by S.evTraction.runMax (a record), +-30 s clipped to the drive; the master's debounced rpm <= 400 rule",
                      "T7": "window of 300 s starting 30 s before the first engine start of a fast-polled clean drive with all channels at >= 95 % coverage; eligible when, while rpm > 400, the logged pack power is above +1 kW for >= 20 s and below -1 kW with target torque >= 0 for >= 20 s; the eligible window whose engine-rotation seconds are closest to the median is shown",
                      "T9": "per fast-polled clean drive the peak 1 s discharge power; eligible when speed >= 80 km/h at the peak, accelerator pedal above 10 % in one of the 5 s before it, no gap within 3 s, window +-30 s with >= 95 % coverage; the drive whose peak is closest to the median of eligible peaks is shown",
                      "frozen": "the selection is not re-run at ingestion; --check reports a stale selection"},
             "selection": {**sel, "T7": {**sel["T7"], "chosenEngineOnS": t7["engineOnS"]}, "T9": {**sel["T9"], "chosenPeakKw": round(t9["peakKw"], 2)}},
             "traces": {"T8": T8}}
    G7, a7 = t7["G"], t7["a"]
    block["traces"]["T7"] = {"label": "one drive, chosen by a fixed rule; not an average or representative drive", "month": month_label(t7["date"]),
                             "dischargeSeconds": t7["dischargeS"], "chargeSeconds": t7["chargeS"], "engineRotationSeconds": t7["engineOnS"],
                             **window_json(G7, a7, a7 + WIN_T7_S, [("rpm", "rpm"), ("powerKw", "power"), ("coolantC", "coolant"), ("torqueNm", "torque"), ("speed", "speed")]),
                             "omitted": ["engine-load proxy (not drawn; its coverage was not evaluated, a deviation from the conditional rule of spec section 2)"]}
    G9, a9 = t9["G"], t9["a"]
    lo, hi = a9 - WIN_T9_HALF_S, a9 + WIN_T9_HALF_S + 1
    ped = G9["pedal"][lo:hi]; rp = G9["rpm"][lo:hi]
    ped_on = np.flatnonzero(np.isfinite(ped) & (ped > PEDAL_MIN)); rp_on = np.flatnonzero(np.isfinite(rp) & (rp > 400))
    block["traces"]["T9"] = {"label": "one drive, chosen by a fixed rule; not an average or representative drive", "month": month_label(t9["date"]),
                             "peakS": WIN_T9_HALF_S, "peakKw": round(t9["peakKw"], 2), "peakSpeedKmh": round(float(G9["speed"][a9]), 1),
                             "pedalOnsetS": int(ped_on[0]) if len(ped_on) else None, "rpmOnsetS": int(rp_on[0]) if len(rp_on) else None,
                             **window_json(G9, lo, hi, [("speed", "speed"), ("pedal", "pedal"), ("powerKw", "power"), ("rpm", "rpm")])}
    block["provenance"] = {"driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "scriptSha": _src_hash(),
                           "drives": {"T8": {"file": t8["file"], "date": t8["date"], "rawSha256": t8["sha"], "windowStartS": int(t8["a"])},
                                      "T7": {"file": t7["file"], "date": t7["date"], "rawSha256": t7["sha"], "windowStartS": int(a7)},
                                      "T9": {"file": t9["file"], "date": t9["date"], "rawSha256": t9["sha"], "windowStartS": int(lo)}}}
    block["limits"] = ["three single-drive windows chosen by fixed rules, not averages, not typical or representative drives, not evidence about the corpus",
                       "engine rotation above the 400 rpm cutoff is not combustion and not generation; pack power is the logged current x voltage; a charging second is not generation (it can be regeneration), the eligibility counts charge only with target torque >= 0",
                       "the traces are on the 1 s alignment of nearest samples within 3 s; gaps are null", "the page shows relative seconds and the drive month only (owner decision 2026-11-28)",
                       "the selection is frozen at the recorded master; a later ingestion does not change it"]
    return json.loads(json.dumps(block, default=float))


def splice(block):
    A2 = json.load(open(ARR, encoding="utf-8"))
    skip = ("exampleTraces", "_artifactStamps")
    before = {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    stamps_before = {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "exampleTraces"}
    A2["exampleTraces"] = block
    st = copy.deepcopy(A2["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=block["provenance"]["driveMasterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M795: computed by tools/example_traces.py from the raw bytes; additive, no published value recomputed; selection frozen; not M299-reproducible.",
              upstreamHashes={"driveMasterMd5": block["provenance"]["driveMasterMd5"]})
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A2["_artifactStamps"]["exampleTraces"] = st
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    assert stamps_before == {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "exampleTraces"}
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A2, f, ensure_ascii=False, indent=1)


def main():
    mode = "--splice" if "--splice" in sys.argv else ("--check" if "--check" in sys.argv else "--dry-run")
    if mode == "--check":
        A = json.load(open(ARR, encoding="utf-8"))["exampleTraces"]
        md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
        print(json.dumps({"check": "exampleTraces", "selectionStale": md5 != A["provenance"]["driveMasterMd5"], "recordedMasterMd5": A["provenance"]["driveMasterMd5"], "selection": A["selection"],
                          "t8FileMatchesRunMax": A["provenance"]["drives"]["T8"]["file"] == json.load(open(ARR, encoding="utf-8"))["evTraction"]["runMax"]["file"]}))
        if A["provenance"]["drives"]["T8"]["file"] != json.load(open(ARR, encoding="utf-8"))["evTraction"]["runMax"]["file"]:
            sys.exit(1)
        return
    dm, cad, bad, loader = load_inputs()
    out, sel, rm = select_all(dm, cad, bad, loader)
    block = build_block(out, sel, rm, dm)
    sz = len(json.dumps(block))
    print(json.dumps({"mode": mode, "selection": block["selection"], "bytes": sz, "T8": {k: block["traces"]["T8"][k] for k in ("month", "cadence", "run")},
                      "T9": {k: block["traces"]["T9"][k] for k in ("month", "peakKw", "peakSpeedKmh", "pedalOnsetS", "rpmOnsetS")}, "T7": {k: block["traces"]["T7"][k] for k in ("month", "dischargeSeconds", "chargeSeconds", "engineRotationSeconds")}}))
    if mode == "--splice":
        splice(block); print(json.dumps({"exampleTraces": "written"}))


if __name__ == "__main__":
    main()
