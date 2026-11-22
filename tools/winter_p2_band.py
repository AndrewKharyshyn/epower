#!/usr/bin/env python3
"""M731 (analyses/M731_spec.md Rev 2.1, section 4): the realised-ambient band of the M717 winter prediction P2.
`realised_shifts(frame, bias, normals)`: per calendar month of the scoring window, the day-bootstrapped shift draws [B, 12] and the month table (days, shift, thin flag). A_day = mean over the day's drives of the mean of the drive start and end ambient
(driver-read vehicle sensor); shift_m = mean over scoring days of A_day minus the normal of month m minus the frozen engine BIAS. A month with fewer than MIN_DAYS days is thin: Nov-Mar take the S3a value in one run and the S3b value in a second
(the band is the envelope of both runs), any other thin month takes 0 and is flagged. `realised_band(frame)` runs the vendored engine through tools/winter_p2_band_run.py (a fresh interpreter, no live module) for scenario S2 with those shifts, for the window months and
for all twelve months, and returns both intervals. Day bootstrap: numpy default_rng(42), 4000 draws, days ascending. Model-derived band; the frozen annual band is reported beside it by the caller."""
import json, os, subprocess, sys, tempfile
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
RUNNER = os.path.join(ROOT, "tools", "winter_p2_band_run.py")
SEED, NB = 42, 4000
MIN_DAYS = 5
VERSION = 1
SCENARIO = "S2_balanced_owner_expected"
S3A = {12: 4.0, 1: 4.0, 2: 4.0, 11: 2.0, 3: 2.0}
S3B = {12: -6.0, 1: -6.0, 2: -6.0, 11: -3.0, 3: -3.0}
COLUMNS = {"P2band": ["day", "start", "ambient_start_c", "ambient_end_c"]}


def day_ambient(frame):
    """One A_day per (day, month): the mean over the day's drives of the mean of the drive start and end ambient (NaN drives dropped)."""
    f = frame.copy()
    f["_a"] = f[["ambient_start_c", "ambient_end_c"]].mean(axis=1)
    f = f[np.isfinite(f["_a"])]
    f["_m"] = pd.to_datetime(f["start"]).dt.month
    g = f.groupby(["day", "_m"])["_a"].mean().reset_index()
    return g.rename(columns={"_a": "A_day", "_m": "month"}).sort_values("day").reset_index(drop=True)


def realised_shifts(frame, bias, normals, nb=NB, seed=SEED, min_days=MIN_DAYS):
    """Returns (draws [nb, 12] with NaN in thin months, table list, window months). `normals`: 12 monthly climate normals (C)."""
    ad = day_ambient(frame)
    rng = np.random.default_rng(seed)
    draws = np.full((nb, 12), np.nan)
    table, window = [], []
    for m in range(1, 13):
        a = ad.loc[ad["month"] == m, "A_day"].values
        if len(a) == 0:
            continue
        window.append(m)
        thin = len(a) < min_days
        shift = float(a.mean() - normals[m - 1] - bias)
        table.append({"month": m, "days": int(len(a)), "meanAday": float(a.mean()), "shiftC": shift, "thin": bool(thin)})
        if not thin:
            idx = rng.integers(0, len(a), size=(nb, len(a)))
            draws[:, m - 1] = a[idx].mean(axis=1) - normals[m - 1] - bias
    return draws, table, window


def _run(shifts, window, draws, tag, workdir):
    out = os.path.join(workdir, tag + ".npy")
    args = {"scenario": SCENARIO, "shifts": np.asarray(shifts).tolist(), "windowMonths": window, "draws": draws, "out": out}
    ap = os.path.join(workdir, tag + ".json")
    json.dump(args, open(ap, "w", encoding="utf-8"))
    r = subprocess.run([sys.executable, "-I", RUNNER, ap], capture_output=True, text=True, cwd=ROOT)
    line = [l for l in r.stdout.splitlines() if l.startswith("RESULT ")]
    if r.returncode != 0 or not line:
        raise RuntimeError("band runner failed: " + (r.stderr or r.stdout)[-800:])
    res = json.loads(line[0][7:])
    res["x"] = np.load(out)
    return res


def realised_band(frame, bias=None, normals=None, nb=NB, workdir=None):
    """Both domains. bias and normals default to the vendored model values (read through a 1-draw runner call)."""
    wd = workdir or tempfile.mkdtemp(prefix="m731_band_")
    if bias is None or normals is None:
        r0 = _run(np.zeros((1, 12)), None, 2, "probe", wd)
        bias, normals = r0["bias"], r0["normals"]
    draws, table, window = realised_shifts(frame, bias, normals, nb)
    if not window:
        return {"status": "not available", "reason": "no scoring day with a driver-read ambient", "table": table}
    thin = [t["month"] for t in table if t["thin"]]
    if len(thin) == len(window):
        return {"status": "not available", "reason": "no month with at least %d days" % MIN_DAYS, "table": table}
    variants = [("single", {})] if not thin else [("S3a-thin", S3A), ("S3b-thin", S3B)]
    out = {"status": "ok", "table": table, "windowMonths": window, "thinMonths": thin, "flags": [], "runs": {}}
    for name, fill in variants:
        sh = np.where(np.isnan(draws), 0.0, draws)                # months outside the window carry shift 0 (their days are null days)
        for m in thin:
            sh[:, m - 1] = fill.get(m, 0.0)
            if m not in S3A:
                out["flags"].append("month %d thin and outside Nov-Mar: shift 0" % m)
        for dom, wm in (("windowMatched", window), ("annual", None)):
            r = _run(sh, wm, nb, "%s_%s" % (name, dom), wd)
            out["runs"]["%s/%s" % (name, dom)] = {"ci": r["ci"], "x": r["x"]}
    for dom in ("windowMatched", "annual"):
        cis = [v["ci"] for k, v in out["runs"].items() if k.endswith(dom)]
        out[dom] = [float(min(c[1] for c in cis)), float(max(c[2] for c in cis))]
    for v in out["runs"].values():
        v.pop("x")
    out["scenario"] = SCENARIO
    return out
