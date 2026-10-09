#!/usr/bin/env python3
"""M392 calibration study (read-only, script-written JSON analyses/M392_calibration.json): how often do the recalibration-gate offset rules fire on REAL historical batches?
Retro-replay: for every batch of k consecutive observed calendar days (k in 2, 4, 7, 10; sliding by k days, at least 30 earlier days) the batch plays the 'new' ingestion and ALL
earlier days the 'old' corpus, exactly as in tools/recal_gate.py (day-clustered percentile bootstrap of the pre-ingest estimate, seed 42, 4000 draws, ratio of sums).
Rules compared per pass (pass 1 = M13 eligibility, pass 2 = also not f_domain_2p):
  H1  pooled new estimate (old+batch) outside the old 95% CI                              (current rule, all quantities)
  H2  batch-only estimate outside the old 95% CI                                          (current rule, offsets only; uncalibrated: a k-day estimate vs a CI for an N-day pooled mean)
  C1  window-null: batch-only deviation from the old estimate ranked against ALL contiguous k-day windows of the old corpus (no minimum-drive condition); p <= 0.05
  C2  two-sample day-clustered bootstrap: CI of (batch-only - old-only) excludes 0 (batch days and old days resampled separately)
  M   minimum detectable difference reported by C1 (95th percentile of |window deviation|)
Under a stable process a calibrated rule fires about 5% of the time or less; a rate far above that is a false-alarm generator. Nothing here changes the gate.
Usage: python analyses/M392_calibration.py"""
import json, os, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import recal_gate as rg

SEED, NB, MIN_OLD_DAYS = 42, 4000, 30
dm = pd.read_csv("drive_master.csv", low_memory=False)
dm["_d"] = dm["date"].astype(str)
days = sorted(dm["_d"].unique())


def day_sums(d, tp):
    num, den = rg._offset_parts(d, tp)
    g = pd.DataFrame({"d": d["_d"].values, "n": num.values, "v": den.values}).groupby("d").sum()
    return g["n"], g["v"]


def boot(n, v, rng, size=None):
    idx = rng.integers(0, len(n), size=(NB, len(n) if size is None else size))
    return n.values[idx].sum(1) / v.values[idx].sum(1)


def run(k, tp):
    rows = []
    for s in range(MIN_OLD_DAYS, len(days) - k + 1, k):
        bdays, odays = days[s:s + k], days[:s]
        old, new = dm[dm["_d"].isin(odays)], dm[dm["_d"].isin(bdays)]
        no, vo = day_sums(old, tp); nn, vn = day_sums(new, tp)
        vo, no = vo[vo > 0], no[vo > 0]; vn, nn = vn[vn > 0], nn[vn > 0]
        if len(no) < 10 or len(nn) < 1:
            continue
        rng = np.random.default_rng(SEED + s)
        est_old = float(no.sum() / vo.sum())
        e = boot(no, vo, rng); lo, hi = np.percentile(e, [2.5, 97.5])
        est_new_only = float(nn.sum() / vn.sum())
        est_pool = float((no.sum() + nn.sum()) / (vo.sum() + vn.sum()))
        h1 = not (lo <= est_pool <= hi); h2 = not (lo <= est_new_only <= hi)
        # C1: all contiguous k-day windows of the old corpus
        od = list(no.index); dev = []
        for j in range(0, len(od) - len(nn) + 1):
            w = od[j:j + len(nn)]
            dev.append(float(no[w].sum() / vo[w].sum()) - est_old)
        dev = np.abs(np.array(dev)); obs = abs(est_new_only - est_old)
        p = float((1 + np.sum(dev >= obs)) / (len(dev) + 1))
        # C2: two-sample day-clustered bootstrap of the difference
        diff = boot(nn, vn, rng) - boot(no, vo, rng)
        c2 = not (np.percentile(diff, 2.5) <= 0 <= np.percentile(diff, 97.5))
        rows.append({"start": bdays[0], "n_old_days": len(no), "n_batch_days": len(nn), "n_batch_drives": int(len(new)), "H1": h1, "H2": h2,
                     "C1_p": p, "C1_flag": p <= 0.05, "C2": bool(c2), "mdd_95": float(np.percentile(dev, 95)), "obs_abs_dev": obs})
    return rows


out = {"seed": SEED, "n_boot": NB, "min_old_days": MIN_OLD_DAYS, "nDaysCorpus": len(days), "results": {}}
for tp in (False, True):
    for k in (2, 4, 7, 10):
        r = run(k, tp)
        n = len(r)
        rate = lambda key: round(sum(1 for x in r if x[key]) / n, 3) if n else None
        out["results"][f"pass{2 if tp else 1}_k{k}"] = {"n_batches": n, "H1_rate": rate("H1"), "H2_rate": rate("H2"), "C1_rate_p05": rate("C1_flag"), "C2_rate": rate("C2"),
                                                       "median_mdd95": round(float(np.median([x["mdd_95"] for x in r])), 4) if n else None,
                                                       "median_batch_drives": float(np.median([x["n_batch_drives"] for x in r])) if n else None, "batches": r}
json.dump(out, open("analyses/M392_calibration.json", "w", encoding="utf-8", newline="\n"), indent=1)
for key, v in out["results"].items():
    print(key, {k2: v[k2] for k2 in ("n_batches", "H1_rate", "H2_rate", "C1_rate_p05", "C2_rate", "median_mdd95", "median_batch_drives")})
