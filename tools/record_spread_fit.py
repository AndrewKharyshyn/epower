#!/usr/bin/env python3
"""Record the M19b Huber fit behind the published spread numbers (M317 Part A; spec analyses/M317_spec.md rev 2).
Appends ONE record per distinct (master MD5, estimator-config/code key) to the append-only `spread_fit_history.json` (existing records are never rewritten) and
publishes the latest record in summary_arrays.json -> spreadFitProvenance (+ stamp). Every value is computed here from drive_master.csv and
compute_drive_summary_v6.m19b_huber_adjust; nothing is typed. Includes the Part B intervals (primary, S1, S2, S2-S1) and the report-only bT stability diagnostic
(first stage refit leaving the last 8 calendar days out; pre-registered FLAG, not a gate: bT sign flip or |delta bT| > half the width of the bT day-clustered bootstrap CI).
Idempotent: a second run with the same key only refreshes the arrays block. Usage: python tools/record_spread_fit.py [--force-print]"""
import argparse, copy, datetime, hashlib, inspect, json, os, platform, subprocess, sys
import numpy as np
import pandas as pd
import sklearn
from sklearn.linear_model import HuberRegressor

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import compute_drive_summary_v6 as v6
import huber_slope_ci as H

HIST = "spread_fit_history.json"
T, I, Y = H.T_COL, H.I_COL, H.Y_COL
sha = lambda b: hashlib.sha256(b).hexdigest()


def bt_bootstrap_ci(d, n_boot=4000, seed=42):
    groups = H._groups(H.day_labels(d["date"]))
    rng = np.random.default_rng(seed)
    bt, fail = [], 0
    for _ in range(n_boot):
        idx = np.concatenate([groups[k] for k in rng.integers(0, len(groups), len(groups))])
        try:
            h = HuberRegressor(epsilon=1.35, max_iter=500).fit(d[[T, I]].values[idx], d[Y].values[idx])
            bt.append(float(h.coef_[0]))
        except Exception:
            fail += 1
    return [float(x) for x in np.percentile(bt, [2.5, 97.5])], fail


def compute_record():
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    for c in ("ens_outlier", "ens_outlier_v2"):
        dm[c] = dm[c].fillna(False).astype(bool)
    _, info = v6.m19b_huber_adjust(dm)
    assert "error" not in info, info
    sc = dm.dropna(subset=[Y, T, I, "date"]).copy()
    keep = sc[~sc["ens_outlier_v2"]].reset_index(drop=True)                     # first-stage keep set == rows carrying a stored adjusted value
    stored = dm.set_index("file").loc[keep["file"], "cell_spread_loaded_p95_adj_hub_mv"].values
    assert not np.isnan(stored).any(), "stored adj_hub missing for a kept row"
    h = HuberRegressor(epsilon=1.35, max_iter=500).fit(keep[[T, I]].values, keep[Y].values)
    hc = info["huber_coef"]
    assert abs(h.intercept_ - hc["intercept"]) < 1e-9 and abs(h.coef_[0] - hc["bT"]) < 1e-9 and abs(h.coef_[1] - hc["bI"]) < 1e-9, "first-stage refit differs from m19b"
    bundle = H.bundle(keep, stored)
    # stability: leave the last 8 calendar days of the keep set out
    days = sorted(keep["date"].astype(str).unique())
    left = days[-8:]
    k8 = keep[~keep["date"].astype(str).isin(left)]
    h8 = HuberRegressor(epsilon=1.35, max_iter=500).fit(k8[[T, I]].values, k8[Y].values)
    bt_ci, bt_fail = bt_bootstrap_ci(keep)
    d_bt = float(h8.coef_[0] - h.coef_[0])
    flag_sign = bool(np.sign(h8.coef_[0]) != np.sign(h.coef_[0]))
    flag_size = bool(abs(d_bt) > (bt_ci[1] - bt_ci[0]) / 2)
    m19_src = inspect.getsource(v6.m19b_huber_adjust)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    except Exception:
        commit = None
    code_key = {"m19b_sha256": sha(m19_src.encode()), "huber_slope_ci_sha256": sha(open("tools/huber_slope_ci.py", "rb").read()),
                "python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "scikit_learn": sklearn.__version__,
                "SPREAD_T_REF": v6.SPREAD_T_REF, "epsilon": 1.35, "max_iter": 500, "n_boot": v6.N_BOOT, "seed": 42}
    return {
        "milestone": "M317", "masterMd5": md5, "generatedAtUtc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "gitCommit": commit,
        "codeKey": code_key,
        "data": {"nRowsMaster": int(len(dm)), "nEligible": int(len(sc)), "nClean": int(len(keep)), "nDays": int(len(days)), "exclusion": info["exclusion"],
                 "keepSetSha256": sha("\n".join(sorted(keep["file"])).encode())},
        "firstStage": {"intercept": hc["intercept"], "bT": hc["bT"], "bI": hc["bI"], "I_ref": hc["I_ref"], "n_iter": int(np.max(h.n_iter_)), "scale": float(h.scale_)},
        "slopeI": {"label": "OLS slope of the Huber-adjusted series; CI = day-clustered bootstrap with an OLS first stage (NOT a Huber-slope CI); months = days / 30.44",
                   "value": info["slope_hub_mv_per_month"], "ci95": info["boot_ci95_mv_per_month"], "nClean": info["n_clean"]},
        "slopeII": {"label": "second-stage Huber slope of the stored (0.1-rounded) adjusted series; months = total_seconds / (30.4375 x 86400)", **bundle},
        "stability": {"leaveLast8Days": {"leftOutDays": left, "nRows": int(len(k8)), "bT": float(h8.coef_[0]), "bI": float(h8.coef_[1]),
                                         "deltaBT": d_bt, "deltaBI": float(h8.coef_[1] - h.coef_[1])},
                      "bT_ci95_day_clustered_bootstrap": bt_ci, "bT_bootstrap_failed_draws": bt_fail,
                      "flag": {"raised": flag_sign or flag_size, "bT_sign_flip": flag_sign, "abs_deltaBT_gt_half_ci_width": flag_size,
                               "rule": "report-only (not a gate): bT sign flip, or |delta bT| > half the width of the bT day-clustered bootstrap CI"}},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-print", action="store_true")
    a = ap.parse_args()
    rec = compute_record()
    hist = json.load(open(HIST, encoding="utf-8")) if os.path.exists(HIST) else {"_note": "Append-only: one record per distinct (masterMd5, codeKey); never rewrite existing records (tools/record_spread_fit.py, M317).", "records": []}
    key = lambda r: (r["masterMd5"], json.dumps({k: r["codeKey"][k] for k in ("m19b_sha256", "huber_slope_ci_sha256")}, sort_keys=True))
    known = {key(r) for r in hist["records"]}
    added = key(rec) not in known
    if added:
        hist["records"].append(rec)
        with open(HIST, "w", encoding="utf-8") as f:
            f.write(json.dumps(hist, ensure_ascii=False, indent=1) + "\n")
    latest = rec if added else next(r for r in hist["records"] if key(r) == key(rec))
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    A["spreadFitProvenance"] = {
        "_provenance": "GENERATED by tools/record_spread_fit.py (M317) from drive_master.csv and compute_drive_summary_v6.m19b_huber_adjust; the full append-only log is spread_fit_history.json. Non-authoritative (degradationTrends.cellSpread governs).",
        "latest": latest, "nRecords": len(hist["records"]),
        "history": [{"masterMd5": r["masterMd5"], "generatedAtUtc": r["generatedAtUtc"], "nClean": r["data"]["nClean"], "bT": r["firstStage"]["bT"], "bI": r["firstStage"]["bI"],
                     "slopeI": r["slopeI"]["value"], "slopeII": r["slopeII"]["point_slope_mv_per_month"], "keepSetSha256": r["data"]["keepSetSha256"]} for r in hist["records"]]}
    s = copy.deepcopy(A["_artifactStamps"]["cohortMeta"])
    s.update(corpusHash=rec["masterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
             computationStatusNote="M317: Huber spread-fit provenance record (tools/record_spread_fit.py); append-only history in spread_fit_history.json.")
    for k in ("carriedForward", "basisNDrives", "reissuedFrom", "reissueNote"):
        s.pop(k, None)
    A["_artifactStamps"]["spreadFitProvenance"] = s
    with open("summary_arrays.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(A, ensure_ascii=False, indent=1))
    print(json.dumps({"added_to_history": added, "nRecords": len(hist["records"]), "slopeII_point": rec["slopeII"]["point_slope_mv_per_month"],
                      "primary_ci": rec["slopeII"]["primary"].get("ci95"), "S1_ci": rec["slopeII"]["S1"].get("ci95"), "S2_ci": rec["slopeII"]["S2"].get("ci95"),
                      "flag": rec["stability"]["flag"]["raised"]}, indent=1))


if __name__ == "__main__":
    main()
