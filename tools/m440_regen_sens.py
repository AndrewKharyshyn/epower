#!/usr/bin/env python3
"""M440 (spec analyses/M440_spec.md): sensitivity of the legacy apparent KE recovery to its confirmed extraction defects (regen programme, milestone MB).
extract_drive replicates the legacy "regen capture" block of compute_summary_arrays._RawAccum.add step by step (same grid, same masks, same fixed dt = 1 s) and, for every qualifying step, also records what the
variants need: RPM missing?, ages of speed / current / voltage / RPM (seconds since the last native sample), whether the previous kept row is exactly 1 s earlier, the probe count, the start speed and the
offset-corrected charge energy. Variants only remove steps (V1, V2, V3, V5), re-bin (V4) or recompute the charge energy (V6). Every number is computed here from the slim frames; nothing is typed.
Usage: python tools/m440_regen_sens.py run --out analyses/M440_result.json [--workers 5]"""
import hashlib, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if __name__ == "__main__":
    os.chdir(ROOT)
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)

AGES = (2, 5, 10)
B_DRAWS, SEED = 4000, 42
STEP_COLS = ["file", "day", "cap", "capOff", "ke", "keUm", "spEnd", "spStart", "tbin", "nprobe", "rpmNan", "ageMax", "gap"]


def _csa():
    import compute_summary_arrays as C
    return C


def native_age(df_time_s, native_mask, grid_end_s):
    """Seconds from the reference point s+1 of each grid bin [s, s+1) to the latest native sample with time < s+1 (NaN if none)."""
    tn = df_time_s[native_mask]
    if tn.size == 0:
        return np.full(grid_end_s.shape, np.nan)
    idx = np.searchsorted(tn, grid_end_s, side="left") - 1
    out = np.where(idx >= 0, grid_end_s - tn[np.clip(idx, 0, None)], np.nan)
    return out


def extract_drive(df, cond_class, fn, day, C=None, i_off=0.0):
    """Legacy-equivalent qualifying decel steps of one drive with the per-step fields the variants need. Returns a DataFrame (possibly empty)."""
    C = C or _csa()
    df, _ = C._apply_speed_priority(df)
    df = df.rename(columns={k: v for k, v in C.RAW_MAP.items() if k in df.columns})
    if "time" not in df:
        return pd.DataFrame(columns=STEP_COLS)
    t = C._ft(df["time"], mixed=True)

    def col(name, lo=None, hi=None):
        if name not in df:
            return None
        s = pd.to_numeric(df[name], errors="coerce").ffill(limit=15)
        if lo is not None:
            s = s.where(s >= lo)
        if hi is not None:
            s = s.where(s <= hi)
        return s

    spd = col("speed", 0, 260); rpm = col("eng_rpm", 0)
    Ts = {s_: col(s_, -40, 90) for s_ in ["T1", "T2", "T3", "T4"]}
    I = col("I"); V = col("V", 200, 450)
    g1 = pd.DataFrame({"t": t})
    for cN, cS in [("speed", spd), ("eng_rpm", rpm), ("I", I), ("V", V), ("T1", Ts["T1"]), ("T2", Ts["T2"]), ("T3", Ts["T3"]), ("T4", Ts["T4"])]:
        g1[cN] = cS.values if cS is not None else np.nan
    g1 = g1.dropna(subset=["t"]).set_index("t")
    hz = g1.resample("1s").mean().ffill(limit=15)
    rq = hz.dropna(subset=["speed", "I", "V"])
    if len(rq) < 4:
        return pd.DataFrame(columns=STEP_COLS)
    sp = rq["speed"].values
    rp_raw = rq["eng_rpm"].values
    rp = np.where(np.isnan(rp_raw), 0.0, rp_raw)
    Iv, Vv = rq["I"].values, rq["V"].values
    eng_off = rp <= 300
    v_prev = np.concatenate([sp[:1], sp[:-1]])
    decel = sp < v_prev
    P = (-Iv) * Vv / 1000.0
    cap = np.where(P < 0, -P, 0) / 3600.0
    Pc = (-(Iv + i_off)) * Vv / 1000.0
    cap_off = np.where(Pc < 0, -Pc, 0) / 3600.0
    mass = C._mass_for_drive(cond_class, fn)
    ke = 0.5 * mass * ((v_prev / 3.6) ** 2 - (sp / 3.6) ** 2) / 3.6e6
    step = eng_off & decel & (sp > 0) & (ke > 0)
    if not step.any():
        return pd.DataFrame(columns=STEP_COLS)
    Tm = rq[["T1", "T2", "T3", "T4"]]
    Tpack = Tm.mean(axis=1).values
    nprobe = Tm.notna().sum(axis=1).values
    tbin = np.full(len(rq), -1)
    for k, (lo, hi, lbl) in enumerate(C.REGEN_TEMP_BINS):
        tbin[(Tpack >= lo) & (Tpack < hi)] = k
    # grid seconds of the kept rows and the gap to the previous kept row
    gsec = ((rq.index.values.astype("datetime64[ns]").astype("int64")) // 10**9).astype(np.int64)
    gap = np.concatenate([[0], np.diff(gsec)])
    # native-sample ages at the end of each kept grid second (speed, current, voltage, RPM)
    ts_s = (t.values.astype("datetime64[ns]").astype("int64") / 1e9)
    ge = gsec.astype(float) + 1.0
    gates = {"speed": (0, 260), "I": (None, None), "V": (200, 450), "eng_rpm": (0, None)}
    ages = {}
    for name, (lo, hi) in gates.items():
        if name in df:
            v = pd.to_numeric(df[name], errors="coerce")
            nat = v.notna()
            if lo is not None:
                nat &= v >= lo
            if hi is not None:
                nat &= v <= hi
            ages[name] = native_age(ts_s, nat.values, ge)
        else:
            ages[name] = np.full(len(rq), np.nan)
    sp_prev_age = np.concatenate([ages["speed"][:1], ages["speed"][:-1]])          # KE uses the speed at the previous kept row as well
    A5 = np.vstack([ages["speed"], sp_prev_age, ages["I"], ages["V"], ages["eng_rpm"]])
    # the age of a step is the largest of the five; a channel with no native sample before the second (or an absent channel) makes it unbounded (inf)
    age_max = np.where(np.isnan(A5).any(axis=0), np.inf, A5.max(axis=0))
    is_um = cond_class in ("urban", "mixed")
    out = pd.DataFrame({"file": fn, "day": day, "cap": cap[step], "capOff": cap_off[step], "ke": ke[step], "keUm": ke[step] if is_um else 0.0,
                        "spEnd": sp[step], "spStart": v_prev[step], "tbin": tbin[step], "nprobe": nprobe[step].astype(np.int8),
                        "rpmNan": np.isnan(rp_raw[step]), "ageMax": age_max[step], "gap": gap[step].astype(np.int32)})
    return out


def mid_bin(sp):
    return (np.clip(sp, 0, 129) // 10 * 10 + 5).astype(int)


def bins_table(steps, speed_key="spEnd", cap_key="cap"):
    """Sums per temperature bin and per speed mid-bin."""
    tm = steps[steps["tbin"] >= 0]
    tt = tm.groupby("tbin").agg(cap=(cap_key, "sum"), ke=("ke", "sum"), n=("ke", "size"))
    sm = steps.assign(mid=mid_bin(steps[speed_key].values)).groupby("mid").agg(cap=(cap_key, "sum"), ke=("ke", "sum"), n=("ke", "size"))
    return tt, sm


# ------------------------------------------------------------------------------------------------ driver
def _work(args):
    fn, cond, day, i_off = args
    import drive_raw_cache as drc
    global _FL
    try:
        _FL
    except NameError:
        _FL = drc.make_frame_loader(raw_dir=os.environ.get("XT_RAW_DIR_STAGED") or os.path.join(ROOT, "raw_only"))
    df = _FL(fn)
    if df is None:
        return fn, None
    return fn, extract_drive(df, cond, fn, day, i_off=i_off)


def extract_all(workers=5, i_off=None):
    from concurrent.futures import ProcessPoolExecutor
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    if i_off is None:
        i_off = float(A["offsetUncertainty"]["pointEstimateA"])
    jobs = [(fn, ct, str(d)[:10], i_off) for fn, ct, d in zip(dm["file"], dm["drive_type"], dm["date"])]
    parts = {}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for fn, st in ex.map(_work, jobs, chunksize=8):
            parts[fn] = st
    steps = pd.concat([p for p in parts.values() if p is not None and len(p)], ignore_index=True)
    return dm, A, steps, i_off


def reproduce(steps, A):
    tt, sm = bins_table(steps)
    pub_t = {r["label"]: r for r in A["regenByTempMeasured"]}
    from compute_summary_arrays import REGEN_TEMP_BINS
    res = {"temp": {}, "speed": {}}
    ok = True
    for k, (lo, hi, lbl) in enumerate(REGEN_TEMP_BINS):
        r = tt.loc[k] if k in tt.index else None
        n = int(r["n"]) if r is not None else 0
        eff = round(r["cap"] / r["ke"] * 100, 1) if (r is not None and r["ke"] > 0) else None
        p = pub_t[lbl]
        res["temp"][lbl] = {"n": n, "eff": eff, "pubN": p["n"], "pubEff": p["eff"], "equal": bool(n == p["n"] and eff == p["eff"])}
        ok = ok and res["temp"][lbl]["equal"]
    for mid, e, n in A["regenCaptureMeasured"]:
        r = sm.loc[mid] if mid in sm.index else None
        n2 = int(r["n"]) if r is not None else 0
        eff = round(r["cap"] / r["ke"] * 100, 1) if (r is not None and r["ke"] > 0) else None
        res["speed"][str(mid)] = {"n": n2, "eff": eff, "pubN": n, "pubEff": e, "equal": bool(n2 == n and eff == e)}
        ok = ok and res["speed"][str(mid)]["equal"]
    return ok, res


if __name__ == "__main__":
    import time
    if len(sys.argv) > 1 and sys.argv[1] == "reproduce":
        t0 = time.time()
        dm, A, steps, i_off = extract_all()
        ok, res = reproduce(steps, A)
        print(json.dumps({"ok": bool(ok), "nSteps": int(len(steps)), "seconds": round(time.time() - t0)}))
        print(json.dumps({k: {l: (v["n"], v["pubN"], v["eff"], v["pubEff"]) for l, v in d.items()} for k, d in res.items()}))
    elif len(sys.argv) > 1 and sys.argv[1] == "run":
        import m440_analyse as AN
        from compute_summary_arrays import REGEN_TEMP_BINS
        out_path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "analyses/M440_result.json"
        t0 = time.time()
        dm, A, steps, i_off = extract_all()
        ok, g1 = reproduce(steps, A)
        if not ok:
            raise SystemExit("G1 failed: the legacy reproduction does not equal the published bins")
        labels = [b[2] for b in REGEN_TEMP_BINS]
        dt_med = dict(zip(dm["file"], dm["ev_rpm_dt_med_s"]))
        steps["cadence"] = steps["file"].map(lambda f: "unknown" if not np.isfinite(dt_med.get(f, np.nan)) else ("fast" if dt_med[f] < 1.0 else "slow"))
        sdm = pd.read_csv("seasonal_drive_master.csv", low_memory=False).set_index("file")["thermal_regime"]
        reg = steps["file"].map(sdm).values
        out = {"_provenance": {"spec": "analyses/M440_spec.md", "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "script": "tools/m440_regen_sens.py + tools/m440_analyse.py",
                               "nDrives": int(len(dm)), "offsetA": i_off, "bootstrap": {"B": B_DRAWS, "seed": SEED, "cluster": "calendar day"},
                               "label": "raw/ = sha256-verified originals (M366); range over declared extraction conventions; apparent KE recovery with assumed masses; not a correction of the legacy values"},
               "G1": {"ok": bool(ok), "nStepsReproduced": int(len(steps)), "bins": g1}, "cohorts": {"all": AN.analyse(steps, A, "all", labels)}}
        for c in ("warm", "shoulder", "cold"):
            sub = steps[reg == c]
            if len(sub):
                out["cohorts"][c] = AN.analyse(sub.reset_index(drop=True), A, c, labels)
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, indent=1, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, "item") else str(o))
        print(json.dumps({"G1": bool(ok), "seconds": round(time.time() - t0), "cohorts": list(out["cohorts"])}))
