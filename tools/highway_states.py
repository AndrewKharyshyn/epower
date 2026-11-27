#!/usr/bin/env python3
"""M792 (analyses/M792_spec.md Rev 2, audit Wave C item 9): three-state strip by speed zone.
Per drive and speed zone (the seven engineOnBySpeed zones, half-open [lo, hi), last zone 120 and above) the logged seconds split into
S1 = engine turning (rpm > 400) and battery supplying power (Id > 0), S2 = engine turning and not (Id > 0) (charging, zero, or current not logged),
S3 = engine not turning or rpm not logged (rpm <= 400 or NaN). Sidecar highway_states.csv is written ONLY by this tool; drive_master.csv is read-only.
Same frame, masks and per-sample dt as tools/highway_share.py (M597). Usage: python tools/highway_states.py [--rebuild] [--check] [--dry-run]"""
import copy, datetime, hashlib, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (ROOT, os.path.join(ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
SIDECAR = os.path.join(ROOT, "highway_states.csv")
METHOD_VERSION = 2
EDGES = [20.0, 40.0, 60.0, 80.0, 100.0, 120.0]
ZONES = ["0-20", "20-40", "40-60", "60-80", "80-100", "100-120", "120+"]
RPM_THR, RPM_THR_SENS = 400.0, 300.0
ZCOLS = ["B", "S1", "S2", "S3", "Nrpm", "Nid", "S1_300", "S2_300", "S1_5", "S1_2"]
INCL = ["B_i", "E_i", "D_i", "D5_i", "T120", "T120E", "T120D"]
COLS = ["file", "date"] + ["z%d_%s" % (k, c) for k in range(len(ZONES)) for c in ZCOLS] + INCL + ["raw_sha256", "method_version", "reason"]
NUM = COLS[2:-3]
FLOOR_S, DISP_DRIVES, DISP_DAYS = 120.0, 10, 5
CLAIM_LO, CLAIM_HI = 40.0, 60.0
DRAWS, SEED = 4000, 42


def zone_seconds(speed, rpm, Id, dt_s):
    """Pure per-drive extraction from aligned per-sample arrays. Returns {column: seconds}. Zone = number of edges <= speed (a sample exactly on an edge belongs to the upper zone); NaN speed is in no zone.
    The inclusive 80-120 band (M597) and the seconds at exactly 120.0 km/h are returned too for the reconciliation."""
    speed = np.asarray(speed, dtype=float); rpm_raw = np.asarray(rpm, dtype=float); Id = np.asarray(Id, dtype=float); dt = np.asarray(dt_s, dtype=float)
    rpm = np.nan_to_num(rpm_raw, nan=0.0)
    ok = np.isfinite(speed)
    zi = np.searchsorted(np.asarray(EDGES), np.where(ok, speed, 0.0), side="right")
    eng, eng3 = rpm > RPM_THR, rpm > RPM_THR_SENS
    dis, dis5, dis2 = Id > 0, Id > 5.0, Id > 2.0            # NaN compares False
    out = {}
    for k in range(len(ZONES)):
        m = ok & (zi == k)
        s = lambda mask: float(dt[m & mask].sum())
        out["z%d_B" % k] = s(np.ones(len(dt), bool))
        out["z%d_S1" % k] = s(eng & dis)
        out["z%d_S2" % k] = s(eng & ~dis)
        out["z%d_S3" % k] = s(~eng)
        out["z%d_Nrpm" % k] = s(np.isnan(rpm_raw))
        out["z%d_Nid" % k] = s(eng & np.isnan(Id))
        out["z%d_S1_300" % k] = s(eng3 & dis)
        out["z%d_S2_300" % k] = s(eng3 & ~dis)
        out["z%d_S1_5" % k] = s(eng & dis5)
        out["z%d_S1_2" % k] = s(eng & dis2)
    band = ok & (speed >= 80.0) & (speed <= 120.0)
    out["B_i"] = float(dt[band].sum()); out["E_i"] = float(dt[band & eng].sum()); out["D_i"] = float(dt[band & eng & dis].sum()); out["D5_i"] = float(dt[band & eng & dis5].sum())
    at120 = ok & (speed == 120.0)
    out["T120"] = float(dt[at120].sum()); out["T120E"] = float(dt[at120 & eng].sum()); out["T120D"] = float(dt[at120 & eng & dis].sum())
    return out


def extract_from_bytes(csv_bytes):
    """Same pipeline frame as highway_share.extract_from_bytes (I base, V asof, rpm asof, speed asof, Id = -I, dt = (clip(dt_h) * 3600))."""
    import compute_drive_summary_v6 as D
    res = {c: None for c in NUM}; res["reason"] = None
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
        res["reason"] = "no_iv_series"; return res
    e = D._asof(I.copy(), V, 'V', D.V_ALIGN_TOL).dropna(subset=['V'])
    e = D._asof(e, eng, 'eng_rpm', D.ENG_ALIGN_TOL)
    e = D._asof(e, spd, 'speed', D.ENG_ALIGN_TOL)
    if len(e) < 2:
        res["reason"] = "no_integrable_iv_pairs"; return res
    Id = -e['v'].to_numpy(dtype=float)
    dt_h = e['t'].diff().dt.total_seconds().clip(lower=0, upper=D.DT_CAP_S).fillna(0) / 3600.0
    dt = (dt_h * 3600.0).to_numpy()
    res.update(zone_seconds(e['speed'].to_numpy(), e['eng_rpm'].to_numpy(), Id, dt))
    return res


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
            r = {k: None for k in COLS}; r.update(file=f, date=date, reason="raw_file_missing", method_version=METHOD_VERSION); rows.append(r); continue
        h = hashlib.sha256(b).hexdigest()
        prev = old.get(f)
        if prev is not None and prev.get("raw_sha256") == h and prev.get("method_version") == METHOD_VERSION:
            rows.append({k: (None if pd.isna(prev.get(k)) else prev.get(k)) for k in COLS}); continue
        r = {k: None for k in COLS}; r.update(extract_from_bytes(b)); r.update(file=f, date=date, raw_sha256=h, method_version=METHOD_VERSION)
        rows.append(r)
    out = pd.DataFrame(rows, columns=COLS)
    for c in NUM:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out.to_csv(path, index=False, lineterminator="\n")
    return pd.read_csv(path, dtype={"raw_sha256": str}, keep_default_na=False, na_values=[""])


def estimates(day, B, nums, floor, draws=DRAWS, seed=SEED, kinds=("mean", "pooled")):
    """Day-clustered percentile bootstrap for several numerators over ONE shared draw set. day: array of day labels, B: denominator seconds, nums: {state: seconds}.
    Drives with B < floor (or B <= 0) are dropped. per-drive mean = mean of num/B; pooled = ratio of resampled sums. Returns None when nothing is eligible."""
    day = np.asarray(day); B = np.asarray(B, dtype=float)
    keep = np.isfinite(B) & (B >= floor) & (B > 0)
    if not keep.any():
        return None
    day = day[keep]; B = B[keep]
    days, di = np.unique(day, return_inverse=True)
    nd = len(days)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, nd, size=(draws, nd))            # one draw set for every state of this zone
    cnt = np.bincount(di, minlength=nd).astype(float); sB = np.bincount(di, weights=B, minlength=nd)
    out = {"nDrives": int(keep.sum()), "nDays": int(nd), "seconds": round(float(B.sum()), 1)}
    for name, v in nums.items():
        v = np.asarray(v, dtype=float)[keep]
        sh = v / B
        s_share = np.bincount(di, weights=sh, minlength=nd); s_num = np.bincount(di, weights=v, minlength=nd)
        blk = {}
        if "mean" in kinds:
            est = 100.0 * sh.mean(); bt = 100.0 * s_share[pick].sum(1) / cnt[pick].sum(1)
            blk["perDriveMean"] = {"est": est, "lo": float(np.percentile(bt, 2.5)), "hi": float(np.percentile(bt, 97.5))}
        if "pooled" in kinds:
            est = 100.0 * v.sum() / B.sum(); bt = 100.0 * s_num[pick].sum(1) / sB[pick].sum(1)
            blk["pooled"] = {"est": est, "lo": float(np.percentile(bt, 2.5)), "hi": float(np.percentile(bt, 97.5))}
        out[name] = blk
    return out


def _zv(side, k, c):
    return pd.to_numeric(side["z%d_%s" % (k, c)], errors="coerce").to_numpy(dtype=float)


def zone_variants(side, k, floor=FLOOR_S, draws=DRAWS):
    day = side["date"].astype(str).to_numpy()
    B, S1, S2, S3 = (_zv(side, k, c) for c in ("B", "S1", "S2", "S3"))
    E = S1 + S2
    prim = estimates(day, B, {"S1": S1, "S2": S2, "S3": S3}, floor, draws)
    var = {
        "rpm300": estimates(day, B, {"S1": _zv(side, k, "S1_300"), "S2": _zv(side, k, "S2_300"), "S3": B - _zv(side, k, "S1_300") - _zv(side, k, "S2_300")}, floor, draws),
        "dead5A": estimates(day, B, {"S1": _zv(side, k, "S1_5"), "S2": E - _zv(side, k, "S1_5"), "S3": S3}, floor, draws),
        "dead2A": estimates(day, B, {"S1": _zv(side, k, "S1_2"), "S2": E - _zv(side, k, "S1_2"), "S3": S3}, floor, draws),
        "floor30s": estimates(day, B, {"S1": S1, "S2": S2, "S3": S3}, 30.0, draws),
        "floor300s": estimates(day, B, {"S1": S1, "S2": S2, "S3": S3}, 300.0, draws),
        "allDrivesPooled": estimates(day, B, {"S1": S1, "S2": S2, "S3": S3}, 1e-9, draws, kinds=("pooled",)),
        "rpmLoggedOnly": estimates(day, B - _zv(side, k, "Nrpm"), {"S1": S1, "S2": S2, "S3": S3 - _zv(side, k, "Nrpm")}, floor, draws),
    }
    return prim, var


def merged_band(side, master, draws=DRAWS):
    """The audit claim's band: inclusive 80-120 km/h on the M597 population (master deficit_80_120_valid and B >= 120 s)."""
    s = side.merge(master[["file", "deficit_80_120_valid"]], on="file", how="inner")
    s = s[s["deficit_80_120_valid"].astype(str).str.lower().eq("true") & s["B_i"].notna()]
    B, E, Dd = (pd.to_numeric(s[c]).to_numpy(dtype=float) for c in ("B_i", "E_i", "D_i"))
    day = s["date"].astype(str).to_numpy()
    est = estimates(day, B, {"S1": Dd, "S2": E - Dd, "S3": B - E}, FLOOR_S, draws)
    D5 = pd.to_numeric(s["D5_i"]).to_numpy(dtype=float)
    est["dead5A"] = estimates(day, B, {"S1": D5, "S2": E - D5, "S3": B - E}, FLOOR_S, draws)      # sensitivity: S1 requires Id > 5 A (Director binding change 3)
    return est


def claim_verdict(est):
    """Frozen three-outcome rule (spec D5) on S1 of the merged inclusive band: both intervals inside 40-60 -> aboutHalf; any entirely outside -> falsified; otherwise inconclusive."""
    iv = [est["S1"]["perDriveMean"], est["S1"]["pooled"]]
    if any(x["hi"] < CLAIM_LO or x["lo"] > CLAIM_HI for x in iv):
        return "falsified"
    if all(x["lo"] >= CLAIM_LO and x["hi"] <= CLAIM_HI for x in iv):
        return "aboutHalf"
    return "inconclusive"


def reconcile(side, share, master):
    """D1/D2 against the M597 sidecar highway_share.csv (zero tolerance on round(., 1) of the unrounded zone sum) and per-drive partition identity."""
    m = side.merge(share[["file", "B_s", "E_s", "D_s"]], on="file", how="inner").merge(master[["file"]], on="file", how="inner")
    m = m[m["B_i"].notna() & m["B_s"].notna()]
    t = lambda c: pd.to_numeric(m[c]).to_numpy(dtype=float)
    r1 = lambda x: np.round(x, 1)
    zsum_b = _zv(m, 4, "B") + _zv(m, 5, "B") + t("T120")
    zsum_e = _zv(m, 4, "S1") + _zv(m, 4, "S2") + _zv(m, 5, "S1") + _zv(m, 5, "S2") + t("T120E")      # unrounded zone sums, rounded once
    zsum_d = _zv(m, 4, "S1") + _zv(m, 5, "S1") + t("T120D")
    # identity at float precision (summing the same seconds in a different order differs by about 1e-13 s, which flips round(., 1) at an exact x.x5 value: one drive, 810.35 s), then the inclusive columns against M597 on round(., 1) with zero tolerance
    bad_b = int((np.abs(zsum_b - t("B_i")) > 1e-9).sum())
    bad_e = int((np.abs(zsum_e - t("E_i")) > 1e-9).sum())
    bad_d = int((np.abs(zsum_d - t("D_i")) > 1e-9).sum())
    bad_bi = int((r1(t("B_i")) != r1(m["B_s"].to_numpy(dtype=float))).sum())
    bad_ei = int((r1(t("E_i")) != r1(m["E_s"].to_numpy(dtype=float))).sum())
    bad_di = int((r1(t("D_i")) != r1(m["D_s"].to_numpy(dtype=float))).sum())
    zt = side[side["z0_B"].notna()]
    part_zone = max(float(np.abs(_zv(zt, k, "S1") + _zv(zt, k, "S2") + _zv(zt, k, "S3") - _zv(zt, k, "B")).max()) for k in range(len(ZONES))) if len(zt) else 0.0
    return {"nCompared": int(len(m)), "mismatchBandZoneSum": bad_b, "mismatchEngineOnZoneSum": bad_e, "mismatchDischargeZoneSum": bad_d, "mismatchInclusiveBand": bad_bi, "mismatchInclusiveEngineOn": bad_ei, "mismatchInclusiveDischarge": bad_di,
            "maxPartitionResidualS": round(part_zone, 9), "ok": bool(bad_b == 0 and bad_e == 0 and bad_d == 0 and bad_bi == 0 and bad_ei == 0 and bad_di == 0 and part_zone < 1e-6)}


def engine_on_crosscheck(side, A):
    """D3: pooled engine-on share (rpm > 300 variant, same threshold as S.engineOnBySpeed) per zone over all drives with a zone value, against the stored integer percentage. Printed, never adjusted."""
    pub = {r["zone"]: r["pct"] for r in A.get("engineOnBySpeed", [])}
    out = []
    for k, z in enumerate(ZONES):
        B = _zv(side, k, "B"); on = _zv(side, k, "S1_300") + _zv(side, k, "S2_300"); ok = np.isfinite(B)
        mine = 100.0 * on[ok].sum() / B[ok].sum() if B[ok].sum() > 0 else None
        out.append({"zone": z, "pooledEngineOnPct300": None if mine is None else round(mine, 2), "published": pub.get(z),
                    "absDiffPp": None if mine is None or z not in pub else round(abs(mine - pub[z]), 2)})
    return out


def _r(o, nd=2):
    if isinstance(o, dict):
        return {k: _r(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_r(v, nd) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else round(float(o), nd)
    if isinstance(o, np.integer):
        return int(o)
    return o


def make_block(side, share, master, A, draws=DRAWS):
    rc = reconcile(side, share, master)
    mm = master[["file", "ens_outlier_v2"]].copy()
    mm["clean"] = ~mm["ens_outlier_v2"].astype(str).str.lower().eq("true")
    sd = side.merge(mm[["file", "clean"]], on="file", how="inner")
    sd = sd[sd["clean"] & sd["z0_B"].notna()]
    zones, flags = [], []
    for k, z in enumerate(ZONES):
        prim, var = zone_variants(sd, k, draws=draws)
        shown = bool(prim and prim["nDrives"] >= DISP_DRIVES and prim["nDays"] >= DISP_DAYS)
        row = {"zone": z, "shown": shown, "reasonNotShown": None if shown else "fewer than %d drives on %d days with at least %d s in the zone" % (DISP_DRIVES, DISP_DAYS, FLOOR_S),
               "primary": prim, "sensitivity": var,
               "missingRpmSeconds": round(float(np.nansum(_zv(sd, k, "Nrpm"))), 1), "missingCurrentWhileEngineOnSeconds": round(float(np.nansum(_zv(sd, k, "Nid"))), 1)}
        if prim and k in (4, 5):
            for name in ("dead5A", "rpmLoggedOnly"):
                v = var.get(name)
                if v and not (prim["S1"]["perDriveMean"]["lo"] <= v["S1"]["perDriveMean"]["est"] <= prim["S1"]["perDriveMean"]["hi"]):
                    flags.append({"zone": z, "variant": name})
        zones.append(row)
    mb = merged_band(side, master, draws)
    blk = {"specRev": "analyses/M792_spec.md Rev 2", "methodVersion": METHOD_VERSION,
           "definition": {"S1": "engine turning (logged rpm above 400) and battery supplying power (logged discharge current above 0)",
                          "S2": "engine turning (logged rpm above 400) and battery not supplying power (charging, zero, or current not logged)",
                          "S3": "engine not turning or rpm not logged (logged rpm 400 or lower, or missing)",
                          "units": "percent of logged seconds in the speed zone; logged-signal control observables, estimated, not generator output or saturation"},
           "bootstrap": {"unit": "calendar day", "draws": draws, "seed": SEED, "ci": "percentile 95%", "sharedDrawsAcrossStates": True},
           "floors": {"zoneSecondsPerDrive": FLOOR_S, "displayDrives": DISP_DRIVES, "displayDays": DISP_DAYS},
           "zones": zones, "mergedBand80to120": {"population": "M597: deficit_80_120_valid and at least 120 s in the inclusive 80-120 km/h band", **mb},
           "claim": {"text": "at 80-120 km/h the battery supplied power while the engine turned during about half of covered time", "range": [CLAIM_LO, CLAIM_HI], "verdict": claim_verdict(mb),
                     "dead5AIntervalsInside": bool(all(mb["dead5A"]["S1"][q]["lo"] >= CLAIM_LO and mb["dead5A"]["S1"][q]["hi"] <= CLAIM_HI for q in ("perDriveMean", "pooled")))},
           "timeBase": {"frame": "M597 extract_from_bytes: pack-current series with voltage, rpm and speed aligned as-of; drives with no usable current series are excluded", "noIvSeriesDrives": int((side["reason"] == "no_iv_series").sum()),
                        "audit": "blind reproduction on the speed series: zone S1 within 0.5 pp, merged band within 0.35 pp, all inside the tool intervals, zone drive counts differ by 0-2"},
           "flags": flags, "reconciliation": rc, "engineOnCrossCheck": engine_on_crosscheck(sd, A),
           "notRun": ["Sf logger-cadence stratum", "Sg pack-temperature class"],
           "sidecar": {"file": "highway_states.csv", "sha256": hashlib.sha256(open(SIDECAR, "rb").read()).hexdigest(), "rows": int(len(side))},
           "basis": "raw/ = sha256-verified originals (M366)"}
    return _r(blk), rc


ALLOWED = ("/highwayStates", "/_artifactStamps/highwayStates")


def _paths(a, b, p=""):
    if isinstance(a, dict) and isinstance(b, dict):
        return [x for k in sorted(set(a) | set(b)) for x in (_paths(a.get(k), b.get(k), "%s/%s" % (p, k)) if (k in a and k in b) else ["%s/%s" % (p, k)])]
    return [] if json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) else [p]


def splice(A, blk, master_md5="", now=None):
    new = copy.deepcopy(A)
    new["highwayStates"] = blk
    old = (A.get("_artifactStamps") or {}).get("highwayStates")
    coherent = old and old.get("includedInReleaseAt") == old.get("computedAt") == old.get("generatedAt")
    if old and coherent and A.get("highwayStates") == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"]["highwayStates"] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M792: derived by tools/highway_states.py from drive_master.csv and the tracked highway_states.csv (three-state strip by speed zone; analyses/M792_spec.md)",
                  upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
        import stamp_common as _sc
        new["_artifactStamps"]["highwayStates"] = _sc.carry_declared(old, st)
    ch = _paths(A, new)
    return new, ch, [c for c in ch if not any(c == a_ or c.startswith(a_ + "/") for a_ in ALLOWED)]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    master = pd.read_csv("drive_master.csv", low_memory=False)
    share = pd.read_csv("highway_share.csv", dtype={"raw_sha256": str}, keep_default_na=False, na_values=[""])
    raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A0 = json.loads(raw)
    if "--check" in argv:
        if not os.path.exists(SIDECAR):
            print("FAIL highway_states.csv missing"); return 1
        side = pd.read_csv(SIDECAR, dtype={"raw_sha256": str}, keep_default_na=False, na_values=[""])
        blk, rc = make_block(side, share, master, A0)
        same = A0.get("highwayStates") == blk
        print(json.dumps({"check": "highwayStates", "reconciliationOk": rc["ok"], "matchesPayload": same}))
        return 0 if (rc["ok"] and same) else 1
    from ah_throughput import raw_loader
    side = build_sidecar(master, raw_loader(), SIDECAR, rebuild="--rebuild" in argv)
    blk, rc = make_block(side, share, master, A0)
    print(json.dumps(rc))
    if not rc["ok"]:
        return 1                                   # STOP: the sidecar does not reproduce the M597 band, engine-on and discharge seconds, or the partition identity
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
