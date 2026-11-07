import os, sys, io, json
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import compute_summary_arrays as C
import engine_context_fields as E
dm = pd.read_csv("drive_master.csv", low_memory=False)
cad = dict(zip(*[pd.read_csv("cadence_regime.csv")[c] for c in ("file", "regime")]))
bad = C._canonical_bad(dm)
raw_dir = os.path.join(ROOT, "raw")
dig = lambda s: "".join(ch for ch in s if ch.isdigit())[:14]
rawmap = {}
for f in os.listdir(raw_dir):
    if f.endswith(".csv"): rawmap.setdefault(dig(f), []).append(f)
VARS = {"base": {}, "fuel1.0": {"fuel": 1.0}, "I2": {"I": 2.0}, "cool65": {"cool": 65.0}, "minrun5": {"minrun": 5}, "dropfilled": {"drop": True}}
DEF = dict(soc=68.0, cool=60.0, rpm=500.0, fuel=1.5, I=3.0, minrun=10, drop=False)
def runs(q):
    d = np.diff(np.concatenate([[0], q.astype(np.int8), [0]]))
    return np.flatnonzero(d == 1), np.flatnonzero(d == -1)
res = {}; ivs = []
for i, r in dm.iterrows():
    fn = r["file"]; cand = rawmap.get(dig(fn))
    if not cand or bad.iloc[i]: continue
    b = open(os.path.join(raw_dir, cand[0]), "rb").read()
    hdr = list(pd.read_csv(io.BytesIO(b), nrows=0).columns)
    if "time" not in hdr: continue
    need = lambda c: c in E.COLS or c == "time" or c == C._SPEED_OBD_RAW or c == E.COOL
    df = pd.read_csv(io.BytesIO(b), usecols=lambda c: need(c), low_memory=False)
    g, _ = E._grid(df)
    if "rpm" not in g or "I" not in g: continue
    for c in ("fuel", "soc", "speed", "load"):
        if c not in g: g[c] = np.nan
    # real-sample masks: before ffill
    df2, _ = C._apply_speed_priority(df.copy())
    raw = df2.set_index(C._ft(df2["time"]))[[c for c in E.COLS if c in df2.columns]].apply(pd.to_numeric, errors="coerce").rename(columns=E.COLS)
    real = raw.resample("1s").mean().notna().reindex(g.index, fill_value=False)
    for c in ("rpm", "fuel", "I", "soc"):
        if c not in real: real[c] = False
    I = -g["I"].to_numpy(float)
    tns = g.index.values.astype("datetime64[ns]").astype("int64")
    if E.COOL in df.columns and pd.to_numeric(df[E.COOL], errors="coerce").notna().any():
        ct = pd.to_numeric(df[E.COOL], errors="coerce")
        tt = pd.Series(pd.to_datetime(C._ft(df["time"]))).values.astype("datetime64[ns]").astype("int64")
        mk = ct.notna().to_numpy(); o = np.argsort(tt[mk], kind="stable")
        cool, age = E.coolant_age(tns, tt[mk][o], ct.to_numpy(float)[mk][o])
    else:
        cool = age = np.full(len(g), np.nan)
    rpm = g["rpm"].to_numpy(float); fuel = g["fuel"].to_numpy(float); soc = g["soc"].to_numpy(float)
    with np.errstate(invalid="ignore"):
        rot400 = int((rpm > 400).sum())
        flags_fuelOk = bool(np.nanmax(np.where(np.isfinite(fuel), fuel, 0.0)) > 0) if "fuel" in g else False
        hasB = "boost" in g and bool(np.isfinite(g["boost"]).any()); hasL = bool(np.isfinite(g["load"]).any())
    c_ = cad.get(fn); c_ = c_ if isinstance(c_, str) else "unknown"
    day = "".join(ch for ch in fn if ch.isdigit())
    day = f"{day[:4]}-{day[4:6]}-{day[6:8]}"
    out = {"cad": c_, "day": day, "rot400": rot400, "fv": flags_fuelOk and hasB and hasL, "v": {}}
    for name, ov in VARS.items():
        p = dict(DEF); p.update(ov)
        with np.errstate(invalid="ignore"):
            q = (soc >= p["soc"]) & (cool <= p["cool"]) & (age <= 30) & (rpm >= p["rpm"]) & (fuel >= p["fuel"]) & (np.abs(I) <= p["I"])
        if p["drop"]: q &= real["rpm"].to_numpy() & real["fuel"].to_numpy() & real["I"].to_numpy()
        s, e = runs(q); L = e - s
        keep = L >= p["minrun"]
        out["v"][name] = {"secs": int(L[keep].sum()), "nint": int(keep.sum()), "nfrag": int((~keep).sum()), "fragsecs": int(L[~keep].sum())}
        if name == "base":
            for a, bb in zip(s[keep], e[keep]):
                sl = slice(a, bb)
                ivs.append({"file": fn, "cad": c_, "start": int(a), "len": int(bb - a), "rpm_real": int(real["rpm"].to_numpy()[sl].sum()), "fuel_real": int(real["fuel"].to_numpy()[sl].sum()),
                            "I_real": int(real["I"].to_numpy()[sl].sum()), "soc_real": int(real["soc"].to_numpy()[sl].sum())})
    res[fn] = out
    print(len(res), fn, file=sys.stderr) if len(res) % 100 == 0 else None
strata = {"fast": lambda a: a["cad"] == "fast", "slow": lambda a: a["cad"] == "slow", "slow_fuelValid": lambda a: a["cad"] == "slow" and a["fv"], "unknown": lambda a: a["cad"] == "unknown"}
outj = {}
for sn, f in strata.items():
    sub = {k: a for k, a in res.items() if f(a)}
    o = {"nEligible": len(sub), "rot400": sum(a["rot400"] for a in sub.values())}
    for v in VARS:
        d = [(a["day"], a["v"][v]) for a in sub.values() if a["v"][v]["nint"] > 0]
        secs = sum(x["secs"] for _, x in d)
        nd, ny = len(d), len({y for y, _ in d})
        o[v] = {"secs": secs, "nint": sum(x["nint"] for a in sub.values() for x in [a["v"][v]]), "nfrag": sum(a["v"][v]["nfrag"] for a in sub.values()),
                "fragsecs": sum(a["v"][v]["fragsecs"] for a in sub.values()), "drives": nd, "days": ny, "supported": bool(secs >= 200 and nd >= 10 and ny >= 5)}
    outj[sn] = o
json.dump({"strata": outj}, open("analyses/M605_audit/out.json", "w"), indent=1)
pd.DataFrame(ivs).to_csv("analyses/M605_audit/intervals.csv", index=False)
print(json.dumps(outj))
