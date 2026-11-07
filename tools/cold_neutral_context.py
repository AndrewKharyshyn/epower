#!/usr/bin/env python3
"""M605 (analyses/M605_spec.md Rev 1): fueled, high-SoC, cold-coolant, pack-neutral engine context (independent audit section 04).
Descriptive counts only. A grid second qualifies when SoC >= 68 %, coolant <= 60 C (last non-null raw sample, valid <= 30 s), logged rpm >= 500, app-calculated fuel rate >= 1.5 L/h
and net pack current |I| <= 3 A (discharge-positive; I == 0 is pack-neutral with sub-field zero). An interval is a maximal run of consecutive qualifying seconds of >= 10 s on the M559 grid
(speed priority, 1 s mean, forward fill limit 3). Strata fast / slow / slow_fuelValid / unknown (cadence_regime.csv) are never pooled; support (>= 200 s, >= 10 interval-bearing drives,
>= 5 interval-bearing days) is judged per stratum. Sensitivities one at a time. A conditional rate is computed only for a supported stratum.
Per-drive records are cached by the raw sha256 and the source hash (cnc_cache/, git-ignored). Writes engine_cold_neutral_intervals.csv (base intervals) and analyses/M605_result.json.
drive_master.csv is read-only. Usage: python tools/cold_neutral_context.py [--rebuild] [--splice] [--out analyses/M605_result.json]
--splice additionally writes the additive payload block S.coldNeutralContext (+ stamp); STOP (exit 2, nothing written) when any stratum is supported or any relaxed setting reaches support (Director: escalate, no auto-promotion)."""
import hashlib, inspect, io, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (ROOT, os.path.join(ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
SIDECAR = os.path.join(ROOT, "engine_cold_neutral_intervals.csv")
CACHE = os.path.join(ROOT, "cnc_cache")
OUT = os.path.join(ROOT, "analyses", "M605_result.json")
SUPPORT = (200, 10, 5)                 # seconds in intervals, interval-bearing drives, interval-bearing days
MINLEN = 10
NL = chr(10)
ROT_RPM = 400.0                        # first-rotation clock uses the project rotation rule (strict >), as in M559
BASE = dict(soc_min=68.0, cool_max=60.0, rpm_min=500.0, rpm_strict=False, fuel_min=1.5, i_max=3.0, cool_age=30.0, need_real=False)
VARIANTS = {"base": {}, "soc65": {"soc_min": 65.0}, "soc72": {"soc_min": 72.0}, "soc75": {"soc_min": 75.0}, "fuel1p0": {"fuel_min": 1.0}, "fuel2p0": {"fuel_min": 2.0},
            "rpmGt500": {"rpm_min": 500.0, "rpm_strict": True}, "rpmGt400": {"rpm_min": 400.0, "rpm_strict": True}, "rpm600": {"rpm_min": 600.0},
            "i2": {"i_max": 2.0}, "i5": {"i_max": 5.0}, "min5": {"minlen": 5}, "min20": {"minlen": 20}, "cool55": {"cool_max": 55.0}, "cool65": {"cool_max": 65.0},
            "dropFilled": {"need_real": True}}
RELAXED = dict(soc_min=None, cool_max=None, rpm_min=400.0, rpm_strict=True, fuel_min=None, i_max=None, cool_age=None, need_real=False)
RT_COLS = ("rpm", "fuel", "I", "soc")
SPEED_BANDS = ("standing", "low", "moving", "unknown")
LABELS = ("generation_net_charge", "generation_with_pack_discharge", "thermal_context", "dissipation_candidate")


# ---------------------------------------------------------------- kernel (pure, unit-tested)
def qualify(g, cool, age, p, real=None):
    """boolean per grid second. A threshold of None switches that condition off; with a threshold set, NaN never qualifies."""
    n = len(g)
    q = np.ones(n, bool)
    def col(c):
        return g[c].to_numpy(float) if c in g else np.full(n, np.nan)
    rpm = col("rpm")
    if p.get("rpm_min") is not None:
        q &= (rpm > p["rpm_min"]) if p.get("rpm_strict") else (rpm >= p["rpm_min"])      # NaN compares False
    if p.get("soc_min") is not None:
        q &= col("soc") >= p["soc_min"]
    if p.get("fuel_min") is not None:
        q &= col("fuel") >= p["fuel_min"]
    if p.get("i_max") is not None:
        q &= np.abs(col("I")) <= p["i_max"]
    if p.get("cool_max") is not None:
        cv = np.asarray(cool, float)
        q &= cv <= p["cool_max"]
        if p.get("cool_age") is not None:
            q &= np.asarray(age, float) <= p["cool_age"]
    if p.get("need_real") and real is not None:
        for c in ("rpm", "fuel", "I"):
            q &= real[c].to_numpy(bool)
    return q


def find_runs(q, minlen=MINLEN):
    """maximal runs of consecutive True; returns (intervals with length >= minlen, fragments shorter), each a list of (start, length)."""
    q = np.asarray(q, bool)
    if not len(q):
        return [], []
    d = np.diff(np.r_[False, q, False].astype(np.int8))
    st, en = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    ln = en - st
    iv = [(int(s), int(l)) for s, l in zip(st, ln) if l >= minlen]
    fr = [(int(s), int(l)) for s, l in zip(st, ln) if l < minlen]
    return iv, fr


def band_speed(v):
    v = np.asarray(v, float)
    return np.where(np.isnan(v), "unknown", np.where(v < 5, "standing", np.where(v < 30, "low", "moving")))


def band_load(v):
    v = np.asarray(v, float)
    return np.where(np.isnan(v), "unknown", np.where(v < 8, "<8", np.where(v < 30, "8-30", ">=30")))


def band_rpm(v):
    v = np.asarray(v, float)
    return np.where(v < 1000, "500-1000", np.where(v < 2000, "1000-2000", ">=2000"))


def band_cool(v):
    return np.where(np.asarray(v, float) <= 40, "<=40", "40-60")


def band_fuel(v):
    return np.where(np.asarray(v, float) < 3, "1.5-3", ">=3")


def band_since(v):
    return np.where(np.asarray(v, float) < 300, "<300", ">=300")


def sign_counts(I):
    """discharge-positive current: negative = charging, 0 = zero, positive = discharging."""
    I = np.asarray(I, float)
    return {"charging": int((I < 0).sum()), "zero": int((I == 0).sum()), "discharging": int((I > 0).sum())}


def support_label(sec, drives, days):
    ok = bool(sec >= SUPPORT[0] and drives >= SUPPORT[1] and days >= SUPPORT[2])
    return ("supported" if ok else "candidate, not supported"), ok


def seconds_since_first_rotation(rpm):
    """seconds since the first grid second with rpm > 400 (strict); -1 before it or when the drive never rotates."""
    rpm = np.asarray(rpm, float)
    on = np.flatnonzero(np.where(np.isnan(rpm), False, rpm > ROT_RPM))
    n = len(rpm)
    if not len(on):
        return np.full(n, -1)
    out = np.arange(n) - int(on[0])
    out[out < 0] = -1
    return out


def conditional_rate(recs, side, supported):
    """pooled share of pack-neutral seconds among fuelled high-SoC rotating seconds on one coolant side (Cold <= 60 C, Warm > 80 C); only for a supported stratum."""
    if not supported:
        return None
    from cell_observability import _pooled_share
    num = [r["num" + side] for r in recs]
    den = [r["den" + side] for r in recs]
    days = [r["day"] for r in recs]
    return _pooled_share(num, den, days)


def summarize_interval(g, cool, real, since, start, length):
    sl = slice(start, start + length)
    I = g["I"].to_numpy(float)[sl]
    cl = np.asarray(cool, float)[sl]
    def nm(c):
        v = g[c].to_numpy(float)[sl]
        return float(np.nanmean(v)) if np.isfinite(v).any() else None
    return {"start": int(start), "len": int(length), "meanSoc": nm("soc"), "meanCool": float(np.nanmean(cl)), "meanRpm": nm("rpm"), "meanFuel": nm("fuel"),
            "meanAbsI": float(np.nanmean(np.abs(I))), "sign": sign_counts(I), "meanSpeed": nm("speed"), "meanLoad": nm("load"),
            "sinceStart": int(np.asarray(since)[start]),
            "realRpm": int(real["rpm"].to_numpy(bool)[sl].sum()), "realFuel": int(real["fuel"].to_numpy(bool)[sl].sum()),
            "realI": int(real["I"].to_numpy(bool)[sl].sum()), "realSoc": int(real["soc"].to_numpy(bool)[sl].sum())}


# ---------------------------------------------------------------- per-drive extraction
def _src_hash():
    fs = (qualify, find_runs, band_speed, band_load, band_rpm, band_cool, band_fuel, band_since, sign_counts, seconds_since_first_rotation, summarize_interval, _grid_real, drive_record, _count_bands)
    return hashlib.sha256((repr((BASE, VARIANTS, RELAXED, SUPPORT, MINLEN)) + "".join(inspect.getsource(f) for f in fs)).encode()).hexdigest()[:16]


def _grid_real(df):
    """M559 grid (speed priority, resample 1 s mean, ffill limit 3) plus the real-sample mask (the 1 s bin held at least one logged sample)."""
    import compute_summary_arrays as C
    import engine_context_fields as E
    df, _ = C._apply_speed_priority(df)
    g = df.set_index(C._ft(df["time"]))
    keep = [c for c in E.COLS if c in g.columns]
    g = g[keep].apply(pd.to_numeric, errors="coerce").rename(columns=E.COLS)
    raw = g.resample("1s").mean()
    real = raw.notna()
    return raw.ffill(limit=3), real, df


def _count_bands(g, since, mask):
    out = {}
    for name, vals in (("speed", band_speed(g["speed"].to_numpy(float)[mask])), ("load", band_load(g["load"].to_numpy(float)[mask])), ("rpm", band_rpm(g["rpm"].to_numpy(float)[mask])),
                       ("fuel", band_fuel(g["fuel"].to_numpy(float)[mask])), ("since", band_since(since[mask]))):
        u, c = np.unique(vals, return_counts=True)
        out[name] = {str(a): int(b) for a, b in zip(u, c)}
    return out


def drive_record(b):
    import compute_summary_arrays as C
    import engine_context_fields as E
    hdr = list(pd.read_csv(io.BytesIO(b), nrows=0).columns)
    if "time" not in hdr:
        return {"ok": False, "why": "no time column"}
    need = lambda c: c in E.COLS or c == "time" or c == C._SPEED_OBD_RAW or c == E.COOL
    df = pd.read_csv(io.BytesIO(b), usecols=lambda c: need(c), low_memory=False)
    g, real, df2 = _grid_real(df)
    fu = g["fuel"].to_numpy(float) if "fuel" in g else np.array([])
    flags = {"hasBoost": "boost" in g and bool(np.isfinite(g["boost"]).any()), "hasLoad": "load" in g and bool(np.isfinite(g["load"]).any()),
             "fuelOk": bool("fuel" in g and np.nanmax(np.where(np.isfinite(fu), fu, 0.0)) > 0), "hasCool": E.COOL in df.columns and bool(pd.to_numeric(df[E.COOL], errors="coerce").notna().any()), "hasRpm": "rpm" in g}
    if not flags["hasRpm"] or "I" not in g:
        return {"ok": False, "why": "no rpm or current channel", "flags": flags}
    g["I"] = -g["I"]                                            # BMS current is charge-positive (M11); discharge-positive here
    for c in ("boost", "load", "fuel", "soc", "speed"):
        if c not in g:
            g[c] = np.nan
        if c not in real:
            real[c] = False
    real["I"] = real["I"].to_numpy(bool)
    tns = g.index.values.astype("datetime64[ns]").astype("int64")
    if flags["hasCool"]:
        ct = pd.to_numeric(df[E.COOL], errors="coerce")
        tt = pd.Series(pd.to_datetime(C._ft(df["time"]))).values.astype("datetime64[ns]").astype("int64")
        mk = ct.notna().to_numpy()
        order = np.argsort(tt[mk], kind="stable")
        cool, age = E.coolant_age(tns, tt[mk][order], ct.to_numpy(float)[mk][order])
    else:
        cool, age = np.full(len(g), np.nan), np.full(len(g), np.nan)
    since = seconds_since_first_rotation(g["rpm"].to_numpy(float))
    rec = {"ok": True, "flags": flags, "gridSeconds": int(len(g)), "rot400": int(qualify(g, cool, age, RELAXED).sum()), "variants": {}}
    for name, over in VARIANTS.items():
        p = dict(BASE); p.update({k: v for k, v in over.items() if k != "minlen"})
        q = qualify(g, cool, age, p, real=real)
        iv, fr = find_runs(q, over.get("minlen", MINLEN))
        v = {"sec": int(sum(l for _, l in iv)), "nInt": len(iv), "fragSec": int(sum(l for _, l in fr)), "nFrag": len(fr)}
        if name == "base":
            ivs = [summarize_interval(g, cool, real, since, s, l) for s, l in iv]
            v["intervals"] = ivs
            m = np.zeros(len(g), bool)
            for s, l in iv:
                m[s:s + l] = True
            v["bands"] = _count_bands(g, since, m)
            v["coolBands"] = {str(a): int(c) for a, c in zip(*np.unique(band_cool(cool[m]), return_counts=True))}
            v["sign"] = sign_counts(g["I"].to_numpy(float)[m])
            v["realSeconds"] = {c: int(real[c].to_numpy(bool)[m].sum()) for c in RT_COLS}
            # M559 candidate labels on the interval seconds (extractor base parameters)
            pe = dict(E.BASE)
            r = E.classify(g, cool, age, flags, pe)
            idx = {t: i for i, t in enumerate(g.index)}
            pos = np.array([idx[t] for t in r.index], int)
            sel = m[pos]
            v["labels"] = {L: int(r[L].to_numpy(bool)[sel].sum()) for L in LABELS}
            v["labels"]["none"] = int((~r[list(LABELS)].to_numpy(bool).any(axis=1))[sel].sum())
            v["labels"]["rotatingInInterval"] = int(sel.sum())
            # conditional-rate counts (fuelled, high-SoC, rpm >= 500 seconds by coolant side; pack-neutral numerator)
            base_q = qualify(g, cool, age, dict(BASE, i_max=None, cool_max=None, cool_age=None), real=real)
            valid = np.isfinite(cool) & (np.asarray(age, float) <= BASE["cool_age"])
            neutral = np.abs(g["I"].to_numpy(float)) <= BASE["i_max"]
            cold = base_q & valid & (cool <= 60.0)
            warm = base_q & valid & (cool > 80.0)
            sp = band_speed(g["speed"].to_numpy(float))
            v["cond"] = {"Cold": {"den": int(cold.sum()), "num": int((cold & neutral).sum())}, "Warm": {"den": int(warm.sum()), "num": int((warm & neutral).sum())}}
            v["condBySpeed"] = {side: {b: {"den": int((msk & (sp == b)).sum()), "num": int((msk & (sp == b) & neutral).sum())} for b in SPEED_BANDS} for side, msk in (("Cold", cold), ("Warm", warm))}
        rec["variants"][name] = v
    return rec


# ---------------------------------------------------------------- loading with the cache
def load_records(rebuild=False):
    import compute_summary_arrays as C
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    cr = pd.read_csv("cadence_regime.csv")[["file", "regime"]]
    cad = dict(zip(cr.file, cr.regime))
    bad = C._canonical_bad(dm)
    raw_dir = os.environ.get("XT_RAW_DIR", os.path.join(ROOT, "raw"))
    dig = lambda s: "".join(ch for ch in s if ch.isdigit())[:14]
    rawmap = {}
    for f in os.listdir(raw_dir):
        if f.endswith(".csv"):
            rawmap.setdefault(dig(f), []).append(f)
    os.makedirs(CACHE, exist_ok=True)
    sh = _src_hash()
    recs, stats = {}, {"cacheHits": 0, "extracted": 0, "noRaw": 0, "notOk": 0}
    for i, r in dm.iterrows():
        fn = r["file"]
        cand = rawmap.get(dig(fn))
        if not cand:
            stats["noRaw"] += 1
            continue
        b = open(os.path.join(raw_dir, cand[0]), "rb").read()
        digest = hashlib.sha256(b).hexdigest()
        cp = os.path.join(CACHE, f"{digest}_{sh}.json")
        if os.path.exists(cp) and not rebuild:
            rec = json.load(open(cp, encoding="utf-8")); stats["cacheHits"] += 1
        else:
            rec = drive_record(b)
            json.dump(rec, open(cp, "w", encoding="utf-8")); stats["extracted"] += 1
        if not rec.get("ok"):
            stats["notOk"] += 1
        c_ = cad.get(fn)
        s = "".join(c for c in fn if c.isdigit())
        recs[fn] = {"rec": rec, "file": fn, "rawSha256": digest, "cadence": c_ if isinstance(c_, str) else "unknown", "canonClean": bool(not bad.iloc[i]), "day": f"{s[:4]}-{s[4:6]}-{s[6:8]}"}
    return dm, recs, stats


def reconcile(recs):
    """zero tolerance: relaxed qualifying seconds (rpm > 400 strict, nothing else) equal the M559 rotating seconds of the same drive (ecf_cache)."""
    import engine_context_fields as E
    esh = E._src_hash()
    n = miss = skipped = 0
    bad = []
    for fn, a in recs.items():
        if not a["rec"].get("ok"):
            continue
        cp = os.path.join(E.CACHE, f"{a['rawSha256']}_{esh}.json")
        if not os.path.exists(cp):
            skipped += 1
            continue
        e = json.load(open(cp, encoding="utf-8"))
        if not e.get("ok"):
            skipped += 1
            continue
        n += 1
        if int(e["variants"]["base"]["rot"]) != int(a["rec"]["rot400"]):
            miss += 1; bad.append(fn)
    return {"compared": n, "mismatches": miss, "skippedNoM559Cache": skipped, "files": bad[:10]}


# ---------------------------------------------------------------- aggregation
def _stratum(sub, label):
    out = {"nDrives": len(sub), "nDays": len({a["day"] for a in sub}), "gridSeconds": int(sum(a["rec"]["gridSeconds"] for a in sub)),
           "drivesWithoutFuelRate": int(sum(1 for a in sub if not a["rec"]["flags"]["fuelOk"]))}
    sens = {}
    for name in VARIANTS:
        vs = [(a, a["rec"]["variants"][name]) for a in sub]
        with_i = [(a, v) for a, v in vs if v["nInt"] > 0]
        sec = int(sum(v["sec"] for _, v in vs))
        drives, days = len(with_i), len({a["day"] for a, _ in with_i})
        lab, ok = support_label(sec, drives, days)
        sens[name] = {"seconds": sec, "intervals": int(sum(v["nInt"] for _, v in vs)), "fragmentSeconds": int(sum(v["fragSec"] for _, v in vs)), "fragments": int(sum(v["nFrag"] for _, v in vs)),
                      "drives": drives, "days": days, "label": lab, "supported": ok}
    b = sens["base"]
    lens = [iv["len"] for a in sub for iv in a["rec"]["variants"]["base"]["intervals"]]
    out["base"] = dict(b, totalIntervalSeconds=int(sum(lens)), medianIntervalSeconds=(float(np.median(lens)) if lens else None), maxIntervalSeconds=(max(lens) if lens else None))
    out["sensitivities"] = {k: v for k, v in sens.items() if k != "base"}
    flips = sorted(k for k, v in sens.items() if k != "base" and v["supported"] != b["supported"])
    out["labelFlips"] = flips
    if b["supported"]:
        out["finalLabel"] = "supported" if not flips else "not established"
    else:
        out["finalLabel"] = "candidate, not supported"
    out["relaxedReachesSupport"] = sorted(k for k, v in sens.items() if k != "base" and v["supported"] and not b["supported"])
    # overlap states (per second inside base intervals) and sign, real-sample shares, M559 labels
    def agg(key, sub_key=None):
        d = {}
        for a in sub:
            src = a["rec"]["variants"]["base"][key] if sub_key is None else a["rec"]["variants"]["base"][key][sub_key]
            for k, v in src.items():
                d[k] = d.get(k, 0) + v
        return d
    out["overlap"] = {k: agg("bands", k) for k in ("speed", "load", "rpm", "fuel", "since")}
    out["overlap"]["coolant"] = agg("coolBands")
    out["sign"] = agg("sign")
    out["realSeconds"] = agg("realSeconds")
    out["m559Labels"] = agg("labels")
    # conditional rate: only for a supported stratum
    cr = [dict(day=a["day"], denCold=a["rec"]["variants"]["base"]["cond"]["Cold"]["den"], numCold=a["rec"]["variants"]["base"]["cond"]["Cold"]["num"],
               denWarm=a["rec"]["variants"]["base"]["cond"]["Warm"]["den"], numWarm=a["rec"]["variants"]["base"]["cond"]["Warm"]["num"]) for a in sub]
    sup = out["finalLabel"] == "supported"
    out["conditionalRate"] = {"computed": sup, "cold": conditional_rate(cr, "Cold", sup), "warm": conditional_rate(cr, "Warm", sup)}
    out["conditionalCounts"] = {"coldDen": sum(r["denCold"] for r in cr), "coldNum": sum(r["numCold"] for r in cr), "warmDen": sum(r["denWarm"] for r in cr), "warmNum": sum(r["numWarm"] for r in cr)}
    return out


def write_sidecar(el):
    rows = []
    for fn, a in sorted(el.items()):
        for iv in a["rec"]["variants"]["base"]["intervals"]:
            sp = band_speed([iv["meanSpeed"] if iv["meanSpeed"] is not None else np.nan])[0]
            rows.append(dict(file=fn, date=a["day"], stratum=a["cadence"], raw_sha256=a["rawSha256"], start_s=iv["start"], len_s=iv["len"], mean_soc=iv["meanSoc"], mean_cool_c=iv["meanCool"],
                             mean_rpm=iv["meanRpm"], mean_fuel_lph=iv["meanFuel"], mean_abs_i_a=iv["meanAbsI"], n_charging=iv["sign"]["charging"], n_zero=iv["sign"]["zero"], n_discharging=iv["sign"]["discharging"],
                             speed_band=sp, load_band=band_load([iv["meanLoad"] if iv["meanLoad"] is not None else np.nan])[0], rpm_band=band_rpm([iv["meanRpm"]])[0],
                             since_first_rotation_s=iv["sinceStart"], real_rpm=iv["realRpm"], real_fuel=iv["realFuel"], real_i=iv["realI"], real_soc=iv["realSoc"]))
    cols = ["file", "date", "stratum", "raw_sha256", "start_s", "len_s", "mean_soc", "mean_cool_c", "mean_rpm", "mean_fuel_lph", "mean_abs_i_a", "n_charging", "n_zero", "n_discharging", "speed_band", "load_band",
            "rpm_band", "since_first_rotation_s", "real_rpm", "real_fuel", "real_i", "real_soc"]
    pd.DataFrame(rows, columns=cols).to_csv(SIDECAR, index=False, float_format="%.10g", lineterminator="\n")
    return len(rows)


def splice(res):
    """additive write of S.coldNeutralContext (+ stamp); no existing key changes."""
    import copy, datetime
    ARR = os.path.join(ROOT, "summary_arrays.json")
    md5 = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    strata = {}
    for k, v in res["strata"].items():
        strata[k] = {"nDrives": v["nDrives"], "nDays": v["nDays"], "drivesWithoutFuelRate": v["drivesWithoutFuelRate"], "base": v["base"],
                     "i2Beside3": {"i3": {x: v["base"][x] for x in ("seconds", "intervals", "drives", "days")}, "i2": {x: v["sensitivities"]["i2"][x] for x in ("seconds", "intervals", "drives", "days")}},
                     "sensitivities": v["sensitivities"], "labelFlips": v["labelFlips"], "relaxedReachesSupport": v["relaxedReachesSupport"], "finalLabel": v["finalLabel"],
                     "overlap": v["overlap"], "sign": v["sign"], "realSeconds": v["realSeconds"], "m559Labels": v["m559Labels"], "conditionalRate": v["conditionalRate"]}
    block = {"_provenance": "GENERATED by tools/cold_neutral_context.py (M605). Do not hand-edit.", "schemaVersion": 1, "specRev": res["specRev"],
             "basis": "raw bytes; M559 1 s grid (speed priority, 1 s mean, forward fill limit 3); SoC >= 68 %, coolant <= 60 C (last non-null raw sample, valid <= 30 s), logged rpm >= 500, app-calculated fuel >= 1.5 L/h, |I| <= 3 A (discharge-positive), runs >= 10 s; raw/ = sha256-verified originals (M366)",
             "inputs": {"driveMasterMd5": md5, "rawListSha256": res["rawListSha256"]}, "params": res["base"], "minInterval": res["minInterval"], "support": res["support"],
             "population": res["population"], "reconciliation": res["reconciliation"], "extractorSourceHash": res["extractorSourceHash"], "sidecarSha256": hashlib.sha256(open(SIDECAR, "rb").read()).hexdigest(),
             "strata": strata,
             "limits": ["pack-neutral means |I| <= 3 A, about +/- 1 kW net, not zero flow and not an idle generator", "fuel rate is app-calculated; HVAC and defrost are not logged; motive unknown; traction, auxiliary use and heat can overlap",
                        "strata are cadence groups and are never pooled; support is judged per stratum (200 s, 10 interval-bearing drives, 5 interval-bearing days)", "unsupported is not evidence that the state is absent"]}
    block = json.loads(json.dumps(block, default=float))
    A2 = json.load(open(ARR, encoding="utf-8"))
    skip = ("coldNeutralContext", "_artifactStamps")
    before = {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    old = A2["_artifactStamps"].get("coldNeutralContext")
    A2["coldNeutralContext"] = block
    st = copy.deepcopy(A2["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=md5, generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M605: computed by tools/cold_neutral_context.py from the raw bytes; additive, descriptive counts only; not M299-reproducible.", upstreamHashes=dict(block["inputs"]))
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A2["_artifactStamps"]["coldNeutralContext"] = st
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    with open(ARR, "w", encoding="utf-8", newline=NL) as f:
        json.dump(A2, f, ensure_ascii=False, indent=1)
    print(json.dumps({"coldNeutralContext": "written"}))


def main():
    rebuild = "--rebuild" in sys.argv
    out = OUT
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    dm, recs, stats = load_records(rebuild)
    rc = reconcile(recs)
    el = {fn: a for fn, a in recs.items() if a["rec"].get("ok") and a["canonClean"]}
    res = {"milestone": "M605", "specRev": 1, "stats": stats, "reconciliation": rc, "extractorSourceHash": _src_hash(),
           "population": {"masterRows": int(len(dm)), "withRaw": len(recs), "ok": sum(1 for a in recs.values() if a["rec"].get("ok")), "canonClean": len(el),
                          "fuelAllZeroOrMissing": sum(1 for a in el.values() if not a["rec"]["flags"]["fuelOk"]), "noCoolant": sum(1 for a in el.values() if not a["rec"]["flags"]["hasCool"])},
           "support": {"seconds": SUPPORT[0], "drives": SUPPORT[1], "days": SUPPORT[2]}, "base": {k: v for k, v in BASE.items()}, "minInterval": MINLEN, "strata": {}}
    for c in ("fast", "slow", "unknown"):
        sub = [a for a in el.values() if a["cadence"] == c]
        if sub:
            res["strata"][c] = _stratum(sub, c)
            if c == "slow":
                fv = [a for a in sub if a["rec"]["flags"]["fuelOk"] and a["rec"]["flags"]["hasBoost"] and a["rec"]["flags"]["hasLoad"]]
                if fv:
                    res["strata"]["slow_fuelValid"] = _stratum(fv, "slow_fuelValid")
    res["sidecarRows"] = write_sidecar(el)
    res["rawListSha256"] = hashlib.sha256(json.dumps(sorted((a["file"], a["rawSha256"]) for a in recs.values())).encode()).hexdigest()
    json.dump(res, open(out, "w", encoding="utf-8"), indent=1, default=float)
    summ = {k: {"final": v["finalLabel"], "sec": v["base"]["seconds"], "int": v["base"]["intervals"], "drv": v["base"]["drives"], "days": v["base"]["days"]} for k, v in res["strata"].items()}
    print(json.dumps({"ok": True, "stats": stats, "reconciliation": rc, "strata": summ}, default=float))
    if rc["mismatches"]:
        sys.exit(2)
    if "--splice" in sys.argv:
        esc = {k: {"final": v["finalLabel"], "relaxed": v["relaxedReachesSupport"]} for k, v in res["strata"].items() if v["finalLabel"] != "candidate, not supported" or v["relaxedReachesSupport"]}
        if esc:
            print(json.dumps({"STOP": "a stratum is supported or a relaxed setting reaches support: Director decision before any display change", "strata": esc}))
            sys.exit(2)
        splice(res)


if __name__ == "__main__":
    main()
