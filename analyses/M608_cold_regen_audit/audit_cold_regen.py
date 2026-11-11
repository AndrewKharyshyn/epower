"""Independent blind reproduction (M608 C1). Own extractor + aggregation + bootstrap from raw CSV + drive_master.
Reused (loader/definitions only): compute_summary_arrays RAW_MAP, _apply_speed_priority, _mass_for_drive. Everything else own."""
import sys, os, json, io
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
ROOT = r"C:/Users/AndriiKharyshyn/Downloads/X-Trail Investigation/Repo/xtrail-repo"
os.chdir(ROOT); sys.path.insert(0, ROOT)
import compute_summary_arrays as C
dm = pd.read_csv("drive_master.csv", low_memory=False)
reg = dm["file"].map(pd.read_csv("seasonal_drive_master.csv", low_memory=False).set_index("file")["thermal_regime"])
KEF = 0.5 / 3.6**2 / 3.6e6
H = 0.01  # fine grid for exact-enough integration

def tsec(s):
    t = pd.to_datetime(s, format="%H:%M:%S.%f", errors="coerce")
    if t.isna().mean() > .5: t = pd.to_datetime(s, format="mixed", errors="coerce")
    x = (t - t.dropna().iloc[0]).dt.total_seconds().values
    # midnight rollover
    d = np.diff(np.where(np.isfinite(x), x, np.nan)); add = 0; out = x.copy(); last = x[0]
    for i in range(1, len(x)):
        if np.isfinite(x[i]):
            if np.isfinite(last) and x[i] - last < -3600: add += 86400
            last = x[i]; out[i] = x[i] + add
    return out

def nat(t, s, lo=None, hi=None):
    v = pd.to_numeric(s, errors="coerce").values.astype(float); m = np.isfinite(v) & np.isfinite(t)
    if lo is not None: m &= v >= lo
    if hi is not None: m &= v <= hi
    tt, vv = t[m], v[m]; o = np.argsort(tt, kind="stable"); tt, vv = tt[o], vv[o]
    k = np.r_[tt[1:] != tt[:-1], True]; return tt[k], vv[k]

def drive(fn):
    raw = os.path.join("raw", fn.replace("_", " ", 1))
    df = pd.read_csv(raw, low_memory=False)
    df, _ = C._apply_speed_priority(df)
    df = df.rename(columns={k: v for k, v in C.RAW_MAP.items() if k in df.columns})
    t = tsec(df["time"])
    st, sv = nat(t, df["speed"], 0, 260); rt, rv = nat(t, df["eng_rpm"], 0, None)
    it, iv = nat(t, df["I"]); vt, vv = nat(t, df["V"], 200, 450)
    if st.size < 2: return []
    t0, t1, v0, v1 = st[:-1], st[1:], sv[:-1], sv[1:]; dt = t1 - t0; n = t0.size
    okdt = (dt > 0) & (dt <= 5)
    def lat(tn, vn, x, age):
        if tn.size == 0: return np.full(x.shape, np.nan)
        i = np.searchsorted(tn, x, side="right") - 1; ic = np.clip(i, 0, None)
        return np.where((i >= 0) & (x - tn[ic] <= age), vn[ic], np.nan)
    r0, r1 = lat(rt, rv, t0, 5), lat(rt, rv, t1, 5)
    known = np.isfinite(r0) & np.isfinite(r1)
    cs = np.r_[0, np.cumsum(rv > 300)]
    a = np.searchsorted(rt, t0, "right"); b = np.searchsorted(rt, t1, "left")
    inside_on = (cs[b] - cs[a]) > 0
    off = known & (r0 <= 300) & (r1 <= 300) & ~inside_on
    def brk(tn, x0, x1):
        if tn.size < 2: return np.zeros(x0.shape, bool)
        ib = np.searchsorted(tn, x0, "right") - 1; ia = np.searchsorted(tn, x1, "left")
        ok = (ib >= 0) & (ia < tn.size); bad = np.r_[0, np.cumsum(np.diff(tn) > 5)]
        return ok & (bad[np.clip(ia, 0, tn.size-1)] == bad[np.clip(ib, 0, tn.size-1)])
    ivok = brk(it, t0, t1) & brk(vt, t0, t1)
    valid = okdt & off & ivok; nonincr = v1 <= v0; strict = v1 < v0
    run = valid & nonincr
    ep = np.full(n, -1); cur = -1
    for k in range(n):
        if run[k]:
            if k == 0 or ep[k-1] < 0: cur += 1
            ep[k] = cur
    trimmed = np.zeros(n, bool)
    for e in range(cur + 1):
        idx = np.where(ep == e)[0]; s = idx[strict[idx]]
        if s.size == 0: trimmed[idx] = True; continue
        trimmed[idx[idx < s[0]]] = True; trimmed[idx[idx > s[-1]]] = True
    rows = []
    for k in np.where((ep >= 0) & ~trimmed)[0]:
        ng = max(int(np.ceil((dt[k]) / H)), 1)
        g = t0[k] + (np.arange(ng + 1)) * dt[k] / ng
        P = np.maximum(np.interp(g, it, iv) * np.interp(g, vt, vv) / 1000.0, 0)
        ch = np.trapezoid(P, g) / 3600.0
        rows.append((ch, v0[k]**2 - v1[k]**2, bool(strict[k])))
    return rows

def main():
    out = {}
    cold = reg.values == "cold"
    ev = dm["ev_rpm_dt_med_s"].values
    mass = np.array([C._mass_for_drive(a, b) for a, b in zip(dm["drive_type"], dm["file"])])
    cache = {}
    per = []
    for i in np.where(cold)[0]:
        rows = drive(dm["file"][i]); a = np.array(rows, float).reshape(-1, 3)
        per.append(dict(file=dm["file"][i], day=str(dm["date"][i])[:10], ev=ev[i], mass=mass[i],
                        ch=a[:, 0].sum(), dv2=a[:, 1].sum(), nstrict=int(a[:, 2].sum()), nint=len(a),
                        outlier=bool(dm["ens_outlier_v2"][i])))
    P = pd.DataFrame(per); P.to_csv("analyses/M608_cold_regen_audit/per_drive.csv", index=False)
    rng_idx = {}
    for name, m in (("fast", P.ev < 1.0), ("slow", P.ev >= 1.0)):
        for tag, sub in (("display", P[m]), ("ensClean", P[m & ~P.outlier])):
            ke = KEF * sub["mass"] * sub["dv2"]
            sub = sub.assign(ke=ke)
            days = sorted(sub.loc[sub.nstrict > 0, "day"].unique())
            dg = sub.groupby("day")[["ch", "ke"]].sum().reindex(days).fillna(0)
            # estimator population includes days w/ any non-trimmed intervals; cluster days = days with est intervals
            dall = sorted(sub.loc[sub.nint > 0, "day"].unique())
            dg = sub.groupby("day")[["ch", "ke"]].sum().reindex(dall).fillna(0)
            eff = 100 * dg.ch.sum() / dg.ke.sum()
            rng = np.random.default_rng(42); D = len(dall)
            idx = rng.integers(0, D, (4000, D))
            c = dg.ch.values[idx].sum(1); k = dg.ke.values[idx].sum(1)
            d = 100 * c / k; ci = np.percentile(d[np.isfinite(d)], [2.5, 97.5])
            out[name + "_" + tag] = dict(n=int(sub.nstrict.sum()), drives=int((sub.nstrict > 0).sum()), drives_any=int(len(sub)),
                                          days=len(days), days_clusters=D, eff=round(eff, 2), ci95=[round(ci[0], 2), round(ci[1], 2)],
                                          days_list=days)
    json.dump(out, open("analyses/M608_cold_regen_audit/result.json", "w", encoding="utf-8"), indent=1, default=str)
    print(json.dumps({k: {a: b for a, b in v.items() if a != "days_list"} for k, v in out.items()}, indent=1))
    print(P.groupby(["day"]).agg(ev=("ev", "median"), n=("file", "count")).tail(8))
main()
