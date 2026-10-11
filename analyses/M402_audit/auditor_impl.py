import json, re, os, sys
import numpy as np, pandas as pd
ROOT = r"C:\Users\AndriiKharyshyn\Downloads\X-Trail Investigation\Repo\xtrail-repo"
RAW = os.path.join(ROOT, "raw")
CUR = "[BMS] HV Battery Current (A)"; VOL = "[BMS] HV Battery voltage (V)"
keys = json.load(open(os.path.join(ROOT, "analyses/M402_audit/sample_files.json"), encoding="utf-8"))["files"]
digits = lambda s: re.sub(r"\D", "", os.path.splitext(s)[0])
rawmap = {digits(f): f for f in os.listdir(RAW) if f.endswith(".csv")}

def tsec(s):
    p = s.str.split(":", expand=True).astype(float)
    return (p[0]*3600 + p[1]*60 + p[2]).to_numpy()

def load(path):
    hdr = pd.read_csv(path, nrows=0, encoding="utf-8-sig").columns
    cols = ["time"] + [x for x in (CUR, VOL) if x in hdr]
    df = pd.read_csv(path, usecols=cols, dtype=str, encoding="utf-8-sig")
    for x in (CUR, VOL):
        if x not in df: df[x] = np.nan
    t = tsec(df["time"])
    c = pd.to_numeric(df[CUR], errors="coerce").to_numpy()
    v = pd.to_numeric(df[VOL], errors="coerce").to_numpy()
    return t, c, v

def seg(a, b, dt):
    """exact integral of positive and negative parts of linear a->b over dt; returns (pos, neg_abs)"""
    if a >= 0 and b >= 0: return dt*(a+b)/2, 0.0
    if a <= 0 and b <= 0: return 0.0, dt*(-a-b)/2
    f = a/(a-b)  # zero crossing fraction
    if a > 0:
        return dt*f*a/2, dt*(1-f)*(-b)/2
    return dt*(1-f)*b/2, dt*f*(-a)/2

def compute(t, c, v, tie="earlier", tol_incl=True, cur_lim=900., dupe="keep", dtmax=5.0, vlo=200, vhi=450, energy=False):
    mc = ~np.isnan(c); ct, cc = t[mc], c[mc]
    keep = np.abs(cc) < cur_lim; ct, cc = ct[keep], cc[keep]
    mv = ~np.isnan(v) & (v >= vlo) & (v <= vhi); vt, vv = t[mv], v[mv]
    if len(ct) < 3: return None, "fewer than 3 current samples"
    if len(vt) == 0: return None, "no voltage samples"
    o = np.argsort(ct, kind="stable"); ct, cc = ct[o], cc[o]
    o = np.argsort(vt, kind="stable"); vt, vv = vt[o], vv[o]
    idx = np.searchsorted(vt, ct)  # first vt >= ct
    lo = np.clip(idx-1, 0, len(vt)-1); hi = np.clip(idx, 0, len(vt)-1)
    dlo = np.abs(ct - vt[lo]); dhi = np.abs(vt[hi] - ct)
    if tie == "earlier": pick_hi = dhi < dlo
    else: pick_hi = dhi <= dlo
    j = np.where(pick_hi, hi, lo); d = np.where(pick_hi, dhi, dlo)
    ok = d <= 1.5 if tol_incl else d < 1.5
    pt, pc, pv = ct[ok], cc[ok], vv[j[ok]]
    if dupe == "dedup_first":
        _, u = np.unique(pt, return_index=True); pt, pc, pv = pt[u], pc[u], pv[u]
    if len(pt) < 2: return None, "fewer than 2 pairs"
    Id = -pc
    dts = np.clip(np.diff(pt), 0, dtmax)
    P = Id*pv/1000.0 if energy else Id
    dis = chg = 0.0; ncross = 0
    for i in range(1, len(pt)):
        a, b = P[i-1], P[i]
        if Id[i-1]*Id[i] < 0: ncross += 1
        p, n = seg(a, b, dts[i-1]); dis += p; chg += n
    return dict(dis=dis/3600, chg=chg/3600, n=len(pt), nx=ncross, ndup=int((np.diff(pt) == 0).sum())), None

if __name__ == "__main__":
    res = {}; data = {}; sens = {}; eqv = {}; info = {}
    variants = {"base": {}, "tie_later": {"tie": "later"}, "tol_exclusive": {"tol_incl": False},
                "lim_le900": {"cur_lim": 900.0000001}, "dedup_dupe_ts": {"dupe": "dedup_first"},
                "dtclip_none": {"dtmax": 1e9}}
    for k in keys:
        f = rawmap[digits(k)]; t, c, v = load(os.path.join(RAW, f)); data[k] = (t, c, v)
        r, why = compute(t, c, v)
        if r is None:
            if CUR not in pd.read_csv(os.path.join(RAW, f), nrows=0, encoding="utf-8-sig").columns: why = "current column absent; " + why
            if VOL not in pd.read_csv(os.path.join(RAW, f), nrows=0, encoding="utf-8-sig").columns: why = "voltage column absent; " + why
            res[k] = dict(ah_discharge=None, ah_charge=None, n_pairs=0, n_crossings=0, reason=why)
        else:
            res[k] = dict(ah_discharge=r["dis"], ah_charge=r["chg"], n_pairs=r["n"], n_crossings=r["nx"], reason=None)
            e, _ = compute(t, c, v, energy=True)
            eqv[k] = (e["dis"]+e["chg"])*1000/(r["dis"]+r["chg"])
            info[k] = dict(ndup_ts=r["ndup"], equiv_V=eqv[k], file=f)
        for name, kw in variants.items():
            rr, _ = compute(t, c, v, **kw)
            sens.setdefault(name, {})[k] = None if rr is None else (rr["dis"], rr["chg"], rr["n"])
    rel = {}
    for name in variants:
        if name == "base": continue
        m = 0.0
        for k in keys:
            b, s = sens["base"][k], sens[name][k]
            if b is None or s is None:
                if (b is None) != (s is None): m = float("inf")
                continue
            for x, y in ((b[0], s[0]), (b[1], s[1])):
                if x > 0: m = max(m, abs(y-x)/x)
                elif y != 0: m = max(m, float("inf"))
        rel[name] = m
    vals = np.array(list(eqv.values()))
    out = {"files": res, "notes": "see sanity", "sanity": {"equiv_V_median": float(np.median(vals)),
           "equiv_V_range": [float(vals.min()), float(vals.max())], "per_drive": info,
           "sensitivity_max_rel": rel,
           "sensitivity_npairs_changed": {n: [k for k in keys if sens[n][k] and sens["base"][k] and sens[n][k][2] != sens["base"][k][2]] for n in variants if n != "base"}}}
    json.dump(out, open(os.path.join(ROOT, "analyses/M402_audit/auditor_results.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps(out["sanity"]["sensitivity_max_rel"], indent=1))
    print(out["sanity"]["equiv_V_median"], out["sanity"]["equiv_V_range"])
    print(sum(1 for r in res.values() if r["ah_discharge"] is None), "null of", len(res))
    print(out["sanity"]["sensitivity_npairs_changed"])
    for k, i in info.items(): print(k, i["ndup_ts"], round(i["equiv_V"],1), res[k]["n_pairs"], res[k]["n_crossings"], res[k]["ah_discharge"], res[k]["ah_charge"])
    print({k:v["reason"] for k,v in res.items() if v["reason"]})
