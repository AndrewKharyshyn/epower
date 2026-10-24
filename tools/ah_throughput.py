#!/usr/bin/env python3
"""M402 (analyses/M402_spec.md, deep audit F16b): per-drive Ah throughput, integrated on the SAME current/voltage pairs as the kWh energy block of compute_drive_summary_v6.py
(same helpers _prep_bytes / _series / _asof, same current artifact filter |I| < 900 A, voltage 200-450 V, pairing tolerance V_ALIGN_TOL, dt clipped to [0, DT_CAP_S], piecewise-linear
quantity with the M229 zero-crossing-aware split of each interval into discharge and charge), with the current in place of the power. Discharge-positive current Id = -I (BMS current is
charge-positive). Values are unrounded in memory; the sidecar rounds at export only (6 decimals). Integrated from logged BMS current samples: an estimated throughput, not a capacity.
Sidecar ah_throughput.csv + ah_throughput_summary.json are written ONLY by this tool; drive_master.csv is read-only. Incremental by content: a drive is recomputed only when its raw sha256
(raw_manifest.json, else hashed bytes) or METHOD_VERSION changed. No normalisation by any capacity here.
Usage: python tools/ah_throughput.py [--rebuild] [--check]    (--check is read-only and needs no raw files)"""
import glob, hashlib, json, os, re, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)          # compute_drive_summary_v6 lives at the repo root
SIDECAR = os.path.join(ROOT, "ah_throughput.csv")
SUMMARY = os.path.join(ROOT, "ah_throughput_summary.json")
METHOD_VERSION = 1
MASTER_ROUNDING_TOL = 5.5e-5          # master gross_*_kwh are rounded to 4 decimals
V_BAND = (200.0, 450.0)               # the voltage filter of the energy block
NUM = ("ah_discharge", "ah_charge", "ah_throughput", "ah_net", "kwh_discharge", "kwh_charge", "kwh_per_ah_throughput")
COLS = ["file", "date", "ah_discharge", "ah_charge", "ah_throughput", "ah_net", "n_pairs", "n_crossings", "kwh_discharge", "kwh_charge",
        "kwh_per_ah_throughput", "raw_sha256", "method_version", "reason"]


def _split(dt, x):
    """The M229 rule on a discharge-positive quantity x (A or kW): (discharge, charge, n_crossings) as unrounded sums."""
    p0 = np.nan_to_num(np.concatenate([[np.nan], x[:-1]]), nan=0.0)
    cross = (p0 * x) < 0
    absum = np.abs(p0) + np.abs(x)
    den = np.where(absum > 0, 2.0 * absum, 1.0)
    disc_c = dt * ((p0 > 0) * p0 ** 2 + (x > 0) * x ** 2) / den
    chg_c = dt * ((p0 < 0) * p0 ** 2 + (x < 0) * x ** 2) / den
    signed = dt * (p0 + x) / 2.0
    disc = np.where(cross, disc_c, np.where(signed > 0, signed, 0.0))
    chg = np.where(cross, chg_c, np.where(signed < 0, -signed, 0.0))
    return float(disc.sum()), float(chg.sum()), int(cross.sum())


def ah_from_bytes(csv_bytes):
    """Ah (and the matched kWh from the identical loop) of one drive CSV. Fewer than two integrable I/V pairs -> None values with a reason (never zero)."""
    import compute_drive_summary_v6 as D
    out = {"ah_discharge": None, "ah_charge": None, "ah_throughput": None, "ah_net": None, "n_pairs": 0, "n_crossings": 0, "kwh_discharge": None, "kwh_charge": None, "reason": None}
    df, t = D._prep_bytes(csv_bytes)
    I = D._series(df, t, 'I')
    if I is not None:
        I = I[I['v'].abs() < 900]
    V = D._series(df, t, 'V', lo=V_BAND[0], hi=V_BAND[1])
    if I is None or V is None or len(I) <= 2:
        out["reason"] = "no_iv_series"
        return out
    e = D._asof(I.copy(), V, 'V', D.V_ALIGN_TOL).dropna(subset=['V'])
    out["n_pairs"] = int(len(e))
    if len(e) < 2:
        out["reason"] = "no_integrable_iv_pairs"
        return out
    Id = -e['v'].to_numpy(dtype=float)
    P = Id * e['V'].to_numpy(dtype=float) / 1000.0
    dt = e['t'].diff().dt.total_seconds().clip(lower=0, upper=D.DT_CAP_S).fillna(0).to_numpy() / 3600.0
    ad, ac, nx = _split(dt, Id)
    kd, kc, _ = _split(dt, P)
    out.update(ah_discharge=ad, ah_charge=ac, ah_throughput=ad + ac, ah_net=ad - ac, n_crossings=nx, kwh_discharge=kd, kwh_charge=kc)
    return out


def raw_loader(raw_dir=None):
    """f(master file key) -> csv bytes or None: raw_only/ (staged master-key view) first, else raw/ matched by the digits of the name."""
    raw_dir = raw_dir or os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")
    stage = os.path.join(ROOT, "raw_only")
    idx = {re.sub(r"\D", "", os.path.basename(p)): p for p in glob.glob(os.path.join(raw_dir, "*.csv"))}

    def load(f):
        p = os.path.join(stage, f)
        if not os.path.exists(p):
            p = idx.get(re.sub(r"\D", "", f))
        return open(p, "rb").read() if p and os.path.exists(p) else None
    return load


def manifest_sha_lookup():
    """canonical file key -> recorded sha256, or None. Audit PF-04 (M496): the former body read a 'records' key that raw_manifest.json does not
    have (it stores 'files'), so it always returned None and every run hashed the raw files from disk. A recorded hash must not stand in for
    the file content when deciding reuse, so the lookup is now an explicit None (same behaviour, stated)."""
    return lambda f: None


def _clean(prev):
    return {k: (None if (isinstance(prev.get(k), float) and np.isnan(prev.get(k))) else prev.get(k)) for k in COLS}


def _row(f, date, res, sha):
    r = {k: None for k in COLS}
    r.update({k: res.get(k) for k in COLS if k in res})
    r.update(file=f, date=date, raw_sha256=sha, method_version=METHOD_VERSION)
    ad, ac, kd, kc = res.get("ah_discharge"), res.get("ah_charge"), res.get("kwh_discharge"), res.get("kwh_charge")
    r["kwh_per_ah_throughput"] = ((kd + kc) / (ad + ac)) if ad is not None and ad + ac > 0 else None
    return r


def build_sidecar(master, loader, path=SIDECAR, sha_lookup=None, rebuild=False):
    """One row per master drive (master order). Reuses a stored row when its raw sha256 and method_version are unchanged; otherwise recomputes it. Writes the CSV (6-decimal export)."""
    old = {}
    if os.path.exists(path) and not rebuild:
        o = pd.read_csv(path, dtype={"raw_sha256": str}, keep_default_na=False, na_values=[""])
        old = {r["file"]: r for r in o.to_dict("records")}
    rows = []
    for _, m in master.iterrows():
        f, date = str(m["file"]), str(m["date"])
        prev = old.get(f)
        reusable = prev is not None and prev.get("method_version") == METHOD_VERSION and prev.get("reason") != "raw_file_missing"
        sha = sha_lookup(f) if sha_lookup else None
        if reusable and sha and prev.get("raw_sha256") == sha:
            rows.append(_clean(prev))
            continue
        b = loader(f)
        if b is None:
            rows.append(_row(f, date, {"reason": "raw_file_missing"}, None))
            continue
        h = hashlib.sha256(b).hexdigest()
        if reusable and prev.get("raw_sha256") == h:
            rows.append(_clean(prev))
            continue
        rows.append(_row(f, date, ah_from_bytes(b), h))
    out = pd.DataFrame(rows, columns=COLS)
    for c in NUM:
        out[c] = pd.to_numeric(out[c], errors="coerce").round(6)
    out.to_csv(path, index=False, lineterminator="\n")
    return pd.read_csv(path, dtype={"raw_sha256": str}, keep_default_na=False, na_values=[""])


def matched_support(side, master):
    """Pre-registered checks (analyses/M402_spec.md): same rows, same null pattern, kWh of the identical loop equal to the master within its rounding, V-equivalent inside the filter band."""
    mm = master.set_index("file")
    s = side.set_index("file")
    res = {"rows_equal_to_master": list(side["file"]) == list(master["file"]), "n_master": int(len(master)), "n_with_pairs": int(s["ah_discharge"].notna().sum()),
           "n_no_pairs": int(s["reason"].isin(["no_iv_series", "no_integrable_iv_pairs"]).sum()), "n_raw_missing": int((s["reason"] == "raw_file_missing").sum())}
    comp = [f for f in s.index[s["reason"] != "raw_file_missing"] if f in mm.index]
    nullm = [f for f in comp if pd.isna(mm.loc[f, "gross_discharge_kwh"]) != pd.isna(s.loc[f, "kwh_discharge"])]
    both = [f for f in comp if not pd.isna(mm.loc[f, "gross_discharge_kwh"]) and not pd.isna(s.loc[f, "kwh_discharge"])]
    dd = np.array([abs(s.loc[f, "kwh_discharge"] - mm.loc[f, "gross_discharge_kwh"]) for f in both]) if both else np.array([0.0])
    dc = np.array([abs(s.loc[f, "kwh_charge"] - mm.loc[f, "gross_charge_kwh"]) for f in both]) if both else np.array([0.0])
    tol = MASTER_ROUNDING_TOL + 1e-6        # + the 6-decimal export rounding of the sidecar
    res.update(n_compared=len(both), null_pattern_mismatch=nullm, max_abs_diff_kwh_discharge=float(dd.max()), max_abs_diff_kwh_charge=float(dc.max()),
               over_tolerance=[f for f, a, b in zip(both, dd, dc) if a > tol or b > tol])
    veq = (s["kwh_per_ah_throughput"] * 1000.0).dropna()
    res.update(v_equiv_median_V=float(veq.median()) if len(veq) else None, outside_voltage_band=[f for f, v in veq.items() if not (V_BAND[0] <= v <= V_BAND[1])])
    res["ok"] = bool(res["rows_equal_to_master"] and not nullm and not res["over_tolerance"] and not res["outside_voltage_band"])
    return res


def summarise(side, master):
    ms = matched_support(side, master)
    s = side[side["ah_discharge"].notna()]
    return {"_provenance": "GENERATED by tools/ah_throughput.py; do not hand-edit", "methodVersion": METHOD_VERSION,
            "definition": "Ah integrated from logged BMS current samples on the same I/V pairs, dt cap and zero-crossing rule as the kWh energy block; discharge-positive; unrounded in memory, 6 decimals in the sidecar; an estimated throughput, not a capacity",
            "nDrivesWithPairs": int(len(s)),
            "totals": {"ahDischarge": round(float(s["ah_discharge"].sum()), 4), "ahCharge": round(float(s["ah_charge"].sum()), 4),
                       "ahThroughput": round(float(s["ah_throughput"].sum()), 4), "ahNet": round(float(s["ah_net"].sum()), 4),
                       "kwhThroughputSameLoop": round(float((s["kwh_discharge"] + s["kwh_charge"]).sum()), 4)},
            "matchedSupport": ms, "status": "ok" if ms["ok"] else "FAILED"}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    master = pd.read_csv("drive_master.csv", low_memory=False)
    if "--check" in argv:
        if not os.path.exists(SIDECAR):
            print("FAIL ah_throughput.csv missing")
            return 1
        side = pd.read_csv(SIDECAR, dtype={"raw_sha256": str}, keep_default_na=False, na_values=[""])
        ms = matched_support(side, master)
        print(("PASS " if ms["ok"] else "FAIL ") + "Ah-throughput sidecar:", json.dumps({k: ms[k] for k in ("rows_equal_to_master", "n_compared", "max_abs_diff_kwh_discharge", "max_abs_diff_kwh_charge", "v_equiv_median_V")}),
              json.dumps({k: ms[k] for k in ("null_pattern_mismatch", "over_tolerance", "outside_voltage_band") if ms[k]}))
        return 0 if ms["ok"] else 1
    side = build_sidecar(master, raw_loader(), SIDECAR, manifest_sha_lookup(), rebuild="--rebuild" in argv)
    summ = summarise(side, master)
    with open(SUMMARY, "w", encoding="utf-8", newline="\n") as f:
        json.dump(summ, f, indent=1, ensure_ascii=False, sort_keys=True)
    ms = summ["matchedSupport"]
    print(json.dumps({"nDrivesWithPairs": summ["nDrivesWithPairs"], "totals": summ["totals"], "status": summ["status"],
                      "max_abs_diff_kwh": [ms["max_abs_diff_kwh_discharge"], ms["max_abs_diff_kwh_charge"]]}))
    return 0 if summ["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
