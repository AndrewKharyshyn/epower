#!/usr/bin/env python3
"""M597 (analyses/M597_spec.md Rev 1, audit D2): joint vs conditional highway share, 80-120 km/h.
Per drive: B = band seconds, E = band seconds with the engine turning (rpm > 400), D = band seconds with the engine turning AND discharge (Id > 0),
all as sums of the same per-sample dt the pipeline uses (compute_drive_summary_v6.py lines ~653-657 and 815-819). E300/D300 repeat E/D with rpm > 300 (sensitivity).
J = D/B (joint share, the existing deficit_80_120_pct), C = D/E (conditional share), R = E/B. Sidecar highway_share.csv is written ONLY by this tool;
drive_master.csv is read-only. Reconciliation gate: B and D, after round(., 1), must equal the master's band_80_120_s and deficit_80_120_s with ZERO tolerance.
Usage: python tools/highway_share.py [--rebuild] [--check]"""
import hashlib, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (ROOT, os.path.join(ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
SIDECAR = os.path.join(ROOT, "highway_share.csv")
METHOD_VERSION = 1
BAND = (80.0, 120.0)
RPM_THR, RPM_THR_SENS = 400.0, 300.0
COLS = ["file", "date", "B_s", "E_s", "D_s", "E300_s", "D300_s", "raw_sha256", "method_version", "reason"]
NUM = ("B_s", "E_s", "D_s", "E300_s", "D300_s")


def band_seconds(speed, rpm, Id, dt_s, thr=RPM_THR):
    """(B, E, D) in seconds from aligned per-sample arrays. Same masks as the pipeline: speed.between(80,120) (NaN -> False), rpm.fillna(0) > thr, Id > 0 (NaN -> False)."""
    speed = np.asarray(speed, dtype=float); rpm = np.nan_to_num(np.asarray(rpm, dtype=float), nan=0.0)
    Id = np.asarray(Id, dtype=float); dt = np.asarray(dt_s, dtype=float)
    band = (speed >= BAND[0]) & (speed <= BAND[1])
    eng = rpm > thr
    dis = Id > 0
    return float(dt[band].sum()), float(dt[band & eng].sum()), float(dt[band & eng & dis].sum())


def extract_from_bytes(csv_bytes):
    """Rebuild the pipeline frame e (I base, V asof, rpm asof, speed asof, Id = -I, dt clipped to [0, DT_CAP_S]) and return the per-drive seconds."""
    import compute_drive_summary_v6 as D
    out = {k: None for k in NUM}
    out["reason"] = None
    df, t = D._prep_bytes(csv_bytes)
    I = D._series(df, t, 'I')
    if I is not None:
        I = I[I['v'].abs() < 900]
    V = D._series(df, t, 'V', lo=200, hi=450)
    spd = D._series(df, t, 'speed', lo=0, hi=260)
    if spd is None or len(spd) < 20:
        alt = D._series(df, t, 'speed_obd', lo=0, hi=260)
        if alt is not None:
            spd = alt
    eng = D._series(df, t, 'eng_rpm', lo=0)
    if I is None or V is None or len(I) <= 2:
        out["reason"] = "no_iv_series"
        return out
    e = D._asof(I.copy(), V, 'V', D.V_ALIGN_TOL).dropna(subset=['V'])
    e = D._asof(e, eng, 'eng_rpm', D.ENG_ALIGN_TOL)
    e = D._asof(e, spd, 'speed', D.ENG_ALIGN_TOL)
    if len(e) < 2:
        out["reason"] = "no_integrable_iv_pairs"
        return out
    Id = -e['v'].to_numpy(dtype=float)
    # the pipeline holds the step in hours and multiplies by 3600 again (dts = dt_h * 3600.0); mirror it so the last float digit, and hence round(., 1), agrees
    dt_h = e['t'].diff().dt.total_seconds().clip(lower=0, upper=D.DT_CAP_S).fillna(0) / 3600.0
    dt = (dt_h * 3600.0).to_numpy()
    b, en, d = band_seconds(e['speed'].to_numpy(), e['eng_rpm'].to_numpy(), Id, dt, RPM_THR)
    _, en3, d3 = band_seconds(e['speed'].to_numpy(), e['eng_rpm'].to_numpy(), Id, dt, RPM_THR_SENS)
    out.update(B_s=b, E_s=en, D_s=d, E300_s=en3, D300_s=d3)
    return out


def shares(B, E, D):
    """(J, C, R) as fractions from seconds; C is None when E == 0, J and R None when B == 0."""
    J = D / B if B > 0 else None
    C = D / E if E > 0 else None
    R = E / B if B > 0 else None
    return J, C, R


def day_bootstrap(values_by_day, stat, draws=4000, seed=42):
    """Day-clustered percentile bootstrap: resample calendar days with replacement, `stat` receives the list of per-day arrays concatenated. Returns (est, lo, hi)."""
    days = list(values_by_day)
    rng = np.random.default_rng(seed)
    est = stat(np.concatenate([values_by_day[d] for d in days], axis=0))
    boots = np.empty(draws)
    for i in range(draws):
        pick = rng.integers(0, len(days), len(days))
        boots[i] = stat(np.concatenate([values_by_day[days[j]] for j in pick], axis=0))
    return float(est), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def build_sidecar(master, loader, path=SIDECAR, rebuild=False):
    old = {}
    if os.path.exists(path) and not rebuild:
        o = pd.read_csv(path, dtype={"raw_sha256": str}, keep_default_na=False, na_values=[""])
        old = {r["file"]: r for r in o.to_dict("records")}
    rows = []
    for _, m in master.iterrows():
        f, date = str(m["file"]), str(m["date"])
        b = loader(f)
        if b is None:
            r = {k: None for k in COLS}; r.update(file=f, date=date, reason="raw_file_missing", method_version=METHOD_VERSION)
            rows.append(r); continue
        h = hashlib.sha256(b).hexdigest()
        prev = old.get(f)
        if prev is not None and prev.get("raw_sha256") == h and prev.get("method_version") == METHOD_VERSION:
            rows.append({k: (None if pd.isna(prev.get(k)) else prev.get(k)) for k in COLS}); continue
        res = extract_from_bytes(b)
        r = {k: None for k in COLS}; r.update(res); r.update(file=f, date=date, raw_sha256=h, method_version=METHOD_VERSION)
        rows.append(r)
    out = pd.DataFrame(rows, columns=COLS)
    for c in NUM:
        out[c] = pd.to_numeric(out[c], errors="coerce").round(1)
    out.to_csv(path, index=False, lineterminator="\n")
    return pd.read_csv(path, dtype={"raw_sha256": str}, keep_default_na=False, na_values=[""])


def reconcile(side, master):
    """Zero-tolerance gate on the rounded values: B vs band_80_120_s, D vs deficit_80_120_s, for every master drive with a sidecar value."""
    mm = master.set_index("file"); s = side.set_index("file")
    bad_b, bad_d, n = [], [], 0
    for f in s.index:
        if f not in mm.index or pd.isna(s.loc[f, "B_s"]) or pd.isna(mm.loc[f, "band_80_120_s"]):
            continue
        n += 1
        if round(float(s.loc[f, "B_s"]), 1) != round(float(mm.loc[f, "band_80_120_s"]), 1):
            bad_b.append(f)
        if round(float(s.loc[f, "D_s"]), 1) != round(float(mm.loc[f, "deficit_80_120_s"]), 1):
            bad_d.append(f)
    return {"rows_equal_to_master": list(side["file"]) == list(master["file"]), "n_compared": n, "mismatch_band": bad_b, "mismatch_discharge": bad_d,
            "n_raw_missing": int((side["reason"] == "raw_file_missing").sum()),
            "ok": bool(list(side["file"]) == list(master["file"]) and not bad_b and not bad_d)}


MIN_BAND_S, E_FLOOR_S, MARGIN_PP = 120.0, 60.0, 2.0     # M14 gate, spec section 3 floor, spec section 5 margin


def _mean_pct(x):
    return float(np.mean(x)) * 100.0


def _pooled_ratio(a):
    """a rows are (numerator_s, denominator_s); time-pooled ratio in percent."""
    return float(a[:, 0].sum() / a[:, 1].sum()) * 100.0


def _est(df, num, den, kind, draws):
    """Estimate with day-clustered 95% interval. kind 'mean' = per-drive mean of num/den, 'pooled' = sum num / sum den. Returns dict(est, lo, hi, n, days)."""
    d = df[[num, den, "date"]].dropna()
    by = {k: g[[num, den]].to_numpy(dtype=float) for k, g in d.groupby("date")}
    stat = (lambda a: _mean_pct(a[:, 0] / a[:, 1])) if kind == "mean" else _pooled_ratio
    est, lo, hi = day_bootstrap(by, stat, draws=draws)
    return {"est": round(est, 2), "lo": round(lo, 2), "hi": round(hi, 2), "nDrives": int(len(d)), "nDays": int(len(by))}


def _diff(df, draws):
    """Paired per-drive mean of C - J in percentage points, day-clustered."""
    d = df[["D", "E", "B", "date"]].dropna()
    by = {k: g[["D", "E", "B"]].to_numpy(dtype=float) for k, g in d.groupby("date")}
    est, lo, hi = day_bootstrap(by, lambda a: _mean_pct(a[:, 0] / a[:, 1] - a[:, 0] / a[:, 2]), draws=draws)
    return {"est": round(est, 2), "lo": round(lo, 2), "hi": round(hi, 2), "nDrives": int(len(d)), "nDays": int(len(by))}


def _view(side, floor_s, rpm300=False, min_band=MIN_BAND_S, draws=4000):
    """One analysis variant. Joint on the master-valid population, conditional/R/J-on-conditional on the E >= floor subset."""
    e, dd = ("E300_s", "D300_s") if rpm300 else ("E_s", "D_s")
    f = side.rename(columns={"B_s": "B", e: "E", dd: "D"})[["file", "date", "B", "E", "D"]].copy()
    f = f[f["B"] >= min_band]
    cond = f[f["E"] >= floor_s]
    out = {"joint": {"perDriveMean": _est(f, "D", "B", "mean", draws), "pooled": _est(f, "D", "B", "pooled", draws)},
           "conditional": {"perDriveMean": _est(cond, "D", "E", "mean", draws), "pooled": _est(cond, "D", "E", "pooled", draws)},
           "engineOnShare": {"perDriveMean": _est(cond, "E", "B", "mean", draws), "pooled": _est(cond, "E", "B", "pooled", draws)},
           "jointOnConditionalPopulation": {"perDriveMean": _est(cond, "D", "B", "mean", draws), "pooled": _est(cond, "D", "B", "pooled", draws)},
           "conditionalMinusJoint_pp": _diff(cond, draws),
           "counts": {"eligibleBand": int(len(f)), "engineOffInBand(E=0)": int((f["E"] == 0).sum()), "lostToFloor": int(((f["E"] > 0) & (f["E"] < floor_s)).sum()),
                      "conditionalPopulation": int(len(cond)), "allBandEngineOn(R=1)": int((cond["E"] == cond["B"]).sum())}}
    out["marginMet"] = bool(out["conditionalMinusJoint_pp"]["lo"] >= MARGIN_PP)
    return out


def compute_stats(side, master, draws=4000):
    """Pre-registered analysis (spec section 5). Primary = floor 60 s, rpm > 400, B >= 120 s. Sensitivities do not gate; marginMet changes are flagged."""
    keep = master[["file", "deficit_80_120_valid"]].copy()
    keep["valid"] = keep["deficit_80_120_valid"].astype(str).str.lower().eq("true")
    sd = side.merge(keep[["file", "valid"]], on="file", how="inner")
    sd = sd[sd["valid"] & sd["B_s"].notna()]
    prim = _view(sd, E_FLOOR_S, draws=draws)
    sens = {"floor30s": _view(sd, 30.0, draws=draws), "floor120s": _view(sd, 120.0, draws=draws), "rpm300": _view(sd, E_FLOOR_S, rpm300=True, draws=draws),
            "band300s": _view(sd, E_FLOOR_S, min_band=300.0, draws=draws)}
    flips = sorted(k for k, v in sens.items() if v["marginMet"] != prim["marginMet"])
    return {"_provenance": "GENERATED by tools/highway_share.py; do not hand-edit", "specRev": "analyses/M597_spec.md Rev 1", "methodVersion": METHOD_VERSION,
            "definition": {"joint": "engine turning (rpm>400) and battery discharging (Id>0) seconds / all 80-120 km/h seconds",
                           "conditional": "engine turning and battery discharging seconds / engine turning 80-120 km/h seconds",
                           "engineOnShare": "engine turning 80-120 km/h seconds / all 80-120 km/h seconds",
                           "units": "percent; logged-signal control observables, estimated, not generator saturation"},
            "bootstrap": {"unit": "calendar day", "draws": draws, "seed": 42, "ci": "percentile 95%"},
            "primary": prim, "sensitivity": sens, "marginPp": MARGIN_PP, "eFloorS": E_FLOOR_S, "marginDecisionFlipsUnder": flips}


ALLOWED = ("/highwayShare", "/_artifactStamps/highwayShare")


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else round(float(o), 4)
    if isinstance(o, np.integer):
        return int(o)
    return o


def _paths(a, b, p=""):
    if isinstance(a, dict) and isinstance(b, dict):
        return [x for k in sorted(set(a) | set(b)) for x in (_paths(a.get(k), b.get(k), "%s/%s" % (p, k)) if (k in a and k in b) else ["%s/%s" % (p, k)])]
    return [] if json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) else [p]


def _eligible_uncompared(side, master):
    """Master-valid drives (B >= 120 s) with no sidecar band value: must be 0 (the 14 uncompared master rows are outside the eligible set)."""
    valid = set(master.loc[master["deficit_80_120_valid"].astype(str).str.lower().eq("true"), "file"])
    have = set(side.loc[side["B_s"].notna(), "file"])
    return len(valid - have)


def make_block(side, master):
    rc = reconcile(side, master)
    blk = _clean(compute_stats(side, master))
    blk.pop("_provenance", None)
    blk["reconciliation"] = {"nCompared": rc["n_compared"], "eligibleNotCompared": int(_eligible_uncompared(side, master)), "mismatchBand": len(rc["mismatch_band"]), "mismatchDischarge": len(rc["mismatch_discharge"]), "ok": rc["ok"]}
    blk["sidecar"] = {"file": "highway_share.csv", "sha256": hashlib.sha256(open(SIDECAR, "rb").read()).hexdigest(), "rows": int(len(side))}
    blk["basis"] = "raw/ = sha256-verified originals (M366)"
    return blk, rc


def splice(A, blk, master_md5="", now=None):
    import copy, datetime
    new = copy.deepcopy(A)
    new["highwayShare"] = blk
    old = (A.get("_artifactStamps") or {}).get("highwayShare")
    coherent = old and old.get("includedInReleaseAt") == old.get("computedAt") == old.get("generatedAt")
    if old and coherent and A.get("highwayShare") == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"]["highwayShare"] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M597: derived by tools/highway_share.py from drive_master.csv and the tracked highway_share.csv (joint and conditional highway share; analyses/M597_spec.md)",
                  upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
        import stamp_common as _sc
        new["_artifactStamps"]["highwayShare"] = _sc.carry_declared(old, st)
    ch = _paths(A, new)
    return new, ch, [c for c in ch if not any(c == a_ or c.startswith(a_ + "/") for a_ in ALLOWED)]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    master = pd.read_csv("drive_master.csv", low_memory=False)
    raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A0 = json.loads(raw)
    if "--check" in argv:
        if not os.path.exists(SIDECAR):
            print("FAIL highway_share.csv missing"); return 1
        side = pd.read_csv(SIDECAR, dtype={"raw_sha256": str}, keep_default_na=False, na_values=[""])
        blk, rc = make_block(side, master)
        bad = (not rc["ok"]) or A0.get("highwayShare") != blk
        print(json.dumps({"check": "highwayShare", "reconciliationOk": rc["ok"], "matchesPayload": A0.get("highwayShare") == blk}))
        return 1 if bad else 0
    from ah_throughput import raw_loader
    side = build_sidecar(master, raw_loader(), SIDECAR, rebuild="--rebuild" in argv)
    blk, rc = make_block(side, master)
    print(json.dumps({k: rc[k] for k in ("n_compared", "mismatch_band", "mismatch_discharge", "ok")})[:600])
    if not rc["ok"]:
        return 1                                   # STOP: the sidecar does not reproduce the master's published band and discharge seconds
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    new, changed, bad = splice(A0, blk, md5)
    print(json.dumps({"nChanged": len(changed), "outsideAllowList": bad}))
    if bad:
        return 1
    if "--dry-run" not in argv and changed:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
