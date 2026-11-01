#!/usr/bin/env python3
"""M560 (spec analyses/M560_spec.md Rev 2): the V0 window finder (a verbatim re-statement of the published _cell_spread_relaxation loop, with fresh / gap flags added) and the window-key emitter that must reproduce the stored cellSpreadRelaxation window count BEFORE any variant code is written.
`build_grid` equals the published `_csr_grid` when fill_mm = fill_i = 3; `find_windows` equals the published detection (rows are rows of the dropna-collapsed grid).
Usage: python tools/m560_window_keys.py   (writes analyses/M560_window_keys.json and prints the reproduction check)"""
import io, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

MAXV, MINV, CUR = "[BMS] Max Cell Voltage (V)", "[BMS] Min Cell Voltage (V)", "[BMS] HV Battery Current (A)"
REST_I, LOAD_I, MIN_REST_S, PRELOAD_S = 5.0, 20.0, 5, 3


def read_frame(b):
    hdr = list(pd.read_csv(io.BytesIO(b), nrows=0).columns)
    if "time" not in hdr or MAXV not in hdr or MINV not in hdr:
        return None
    return pd.read_csv(io.BytesIO(b), usecols=[c for c in ("time", MAXV, MINV, CUR) if c in hdr], low_memory=False)


def build_grid(fr, fill_mm=3, fill_i=3):
    """1 s mean of Max, Min and current; forward fill limited per channel (limit 0 = no fill). Returns (grid, fresh): fresh = a real sample in that second."""
    from compute_summary_arrays import _ft
    g = fr.set_index(_ft(fr["time"]))
    g = g[[c for c in (MAXV, MINV, CUR) if c in g.columns]].rename(columns={MAXV: "maxv", MINV: "minv", CUR: "I"}).apply(pd.to_numeric, errors="coerce")
    m = g.resample("1s").mean()
    fresh = m.notna()
    out = m.copy()
    for c, lim in (("maxv", fill_mm), ("minv", fill_mm), ("I", fill_i)):
        if c in out and lim > 0:
            out[c] = m[c].ffill(limit=lim)
    return out, fresh


def find_windows(g, fresh):
    """published detection on the dropna-collapsed grid. Returns (dropna grid, list of window dicts)."""
    if "I" not in g.columns:
        return None, []
    g2 = g.dropna(subset=["maxv", "minv", "I"])
    if len(g2) < 30:
        return g2, []
    f2 = fresh.loc[g2.index]
    last_real = {c: (fresh.index[fresh[c].to_numpy()].max() if fresh[c].any() else None) for c in ("maxv", "minv", "I")}   # last second holding a real sample of each channel
    spread = (g2["maxv"] - g2["minv"]).values * 1000.0
    cur = g2["I"].abs().values
    resting = cur < REST_I
    idx = g2.index
    n = len(resting)
    wins = []
    i = 0
    while i < n:
        if resting[i]:
            j = i
            while j < n and resting[j]:
                j += 1
            if j - i >= MIN_REST_S:
                pre0 = max(0, i - PRELOAD_S)
                if i - pre0 >= 2 and np.nanmean(cur[pre0:i]) >= LOAD_I:
                    seg = spread[i:j]
                    if np.isfinite(seg).sum() >= 5:
                        s_onset = float(np.nanmean(spread[max(0, i - 1):i + 1]))
                        s_asym = float(np.nanmedian(seg[-min(5, len(seg)):]))
                        m = s_onset - s_asym
                        half = None
                        if m > 1.0:
                            hit = np.where(seg <= s_onset - 0.5 * m)[0]
                            if len(hit):
                                half = int(hit[0])
                        t = idx[pre0:j]
                        gap = bool((np.diff(t.values).astype("timedelta64[s]").astype(int) != 1).any()) if len(t) > 1 else False
                        used = list(range(max(0, i - 1), i + 1)) + list(range(j - min(5, len(seg)), j))
                        fr = f2[["maxv", "minv"]].iloc[used].to_numpy()
                        onset_rows = f2[["maxv", "minv"]].iloc[max(0, i - 1):i + 1].to_numpy()
                        used_ts = idx[used]
                        trailing = bool(any(lr is not None and (used_ts > lr).any() for lr in last_real.values()))   # an onset / asymptote second lies after a channel's last real sample (filled past the end of its data)
                        wins.append({"i": i, "j": j, "pre0": pre0, "key": str(idx[i]), "onset": s_onset, "asym": s_asym, "mag": m, "half": half, "restRows": j - i,
                                     "gapInside": gap, "trailingFill": trailing, "freshAll": bool(fr.all()), "onsetFilled": bool(not onset_rows.all()), "negative": bool(m < 0)})
                i = j
                continue
            i = j
        else:
            i += 1
    return g2, wins


def main():
    import compute_summary_arrays as C
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    cr = pd.read_csv("cadence_regime.csv")[["file", "regime"]]
    cad = dict(zip(cr.file, cr.regime))
    raw_dir = os.environ.get("XT_RAW_DIR", os.path.join(ROOT, "raw"))
    dig = lambda s: "".join(ch for ch in s if ch.isdigit())[:14]
    rawmap = {dig(f): f for f in os.listdir(raw_dir) if f.endswith(".csv")}
    keys, nd = [], 0
    for _, r in dm.iterrows():
        f = r["file"]
        if dig(f) not in rawmap:
            continue
        fr = read_frame(open(os.path.join(raw_dir, rawmap[dig(f)]), "rb").read())
        if fr is None or CUR not in fr.columns:
            continue
        g, fresh = build_grid(fr, 3, 3)
        g2, wins = find_windows(g, fresh)
        if g2 is None or len(g2) < 30:
            continue
        nd += 1
        for w in wins:
            keys.append({"file": f, "key": w["key"], "stratum": cad.get(f) if isinstance(cad.get(f), str) else "unknown", "day": str(r.get("date", ""))[:10],
                         "gapInside": w["gapInside"], "onsetFilled": w["onsetFilled"], "negative": w["negative"], "freshAll": w["freshAll"], "mag": round(w["mag"], 6)})
    A = json.load(open("summary_arrays.json", encoding="utf-8"))["cellSpreadRelaxation"]
    mags = np.array([k["mag"] for k in keys])
    res = {"nDrivesCovered": nd, "nWindows": len(keys), "storedNDrivesCovered": A["nDrivesCovered"], "storedNRestWindows": A["nRestWindows"], "medianMagnitude": round(float(np.median(mags)), 2), "storedMedian": A["relaxationMagnitudeMv"]["median"],
           "reproduces": bool(len(keys) == A["nRestWindows"] and nd == A["nDrivesCovered"] and round(float(np.median(mags)), 2) == A["relaxationMagnitudeMv"]["median"])}
    json.dump({"check": res, "windows": keys}, open(os.path.join(ROOT, "analyses", "M560_window_keys.json"), "w", encoding="utf-8"))
    print(json.dumps(res))


if __name__ == "__main__":
    main()
