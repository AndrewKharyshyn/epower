#!/usr/bin/env python3
"""M394 exploratory cross-check (read-only, script-written JSON analyses/M394_fuel_crosscheck.json): does an INDEPENDENT unfuelled indicator (logged / app-calculated fuel rate ~ 0 with the engine
turning and the throttle closed) agree with the published manifold-pressure classifier of the dissipation census (rpm > 2000, boost < -0.70, calc load < 8), and does it find unfuelled spin the
published classifier misses?  Only the 60-column logging generation carries the fuel-rate, throttle and engine-power channels (script counts them).  1 s grid as in the census.
  PUB  = rpm > 2000 & boost < -0.70 & load < 8                         (published census)
  FUEL = rpm > 1200 & fuel_rate < 0.2 L/h & abs. throttle B < 10 %      (independent indicator; thresholds fixed here, not tuned)
Cross-tab per rpm band and per SoC band; FUEL-only events (runs >= 3 s) are listed with SoC / rpm trend / pack temperature.  Usage: python analyses/M394_fuel_crosscheck.py"""
import glob, json, os, re, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
dm = pd.read_csv("drive_master.csv", low_memory=False)
idx = {re.sub(r"\D", "", os.path.basename(p)): p for p in glob.glob("raw/*.csv")}


def find(df, *keys):
    for c in df.columns:
        if all(k.lower() in c.lower() for k in keys):
            return c


tot = {"drives": 0, "PUB": 0, "FUEL": 0, "both": 0, "PUB_only": 0, "FUEL_only": 0}
byrpm, bysoc, events = {}, {}, []
for fn, tp in zip(dm["file"].astype(str), dm["T_pack_mean_avg"]):
    p = idx.get(re.sub(r"\D", "", fn))
    if not p or not any("(л/год)" in c for c in pd.read_csv(p, nrows=0).columns):
        continue
    df = pd.read_csv(p, low_memory=False)
    rpm, boost, load = find(df, "Оберти двигуна"), find(df, "наддув"), find(df, "Розрахункове значення навантаження")
    fuel, thr, soc = find(df, "(л/год)"), find(df, "Абсолютне положення дросельної заслінки B"), find(df, "state of charge")
    if not (rpm and boost and load and fuel and thr and soc):
        continue
    t = pd.to_timedelta(df.iloc[:, 0]).dt.total_seconds()
    g = df[[rpm, boost, load, fuel, thr, soc]].apply(pd.to_numeric, errors="coerce")
    g.columns = ["rpm", "boost", "load", "fuel", "thr", "soc"]
    g.index = pd.to_datetime("1900-01-01") + pd.to_timedelta(t, unit="s")
    g = g.resample("1s").mean().ffill(limit=3).dropna(subset=["rpm", "boost", "fuel", "thr", "soc"])
    g["load"] = g["load"].fillna(0)
    pub = (g.rpm > 2000) & (g.boost < -0.70) & (g.load < 8)
    fu = (g.rpm > 1200) & (g.fuel < 0.2) & (g.thr < 10)
    tot["drives"] += 1; tot["PUB"] += int(pub.sum()); tot["FUEL"] += int(fu.sum()); tot["both"] += int((pub & fu).sum())
    tot["PUB_only"] += int((pub & ~fu).sum()); tot["FUEL_only"] += int((fu & ~pub).sum())
    for name, m in (("PUB", pub), ("FUEL", fu), ("FUEL_only", fu & ~pub), ("PUB_only", pub & ~fu)):
        for lo, hi in ((1200, 1500), (1500, 2000), (2000, 3000), (3000, 99999)):
            k = f"{name}|{lo}-{hi}"
            byrpm[k] = byrpm.get(k, 0) + int((m & (g.rpm >= lo) & (g.rpm < hi)).sum())
        for lo, hi in ((0, 60), (60, 75), (75, 85), (85, 101)):
            k = f"{name}|soc{lo}-{hi}"
            bysoc[k] = bysoc.get(k, 0) + int((m & (g.soc >= lo) & (g.soc < hi)).sum())
    c = (fu & ~pub).values
    i = 0
    while i < len(c):
        if c[i]:
            j = i
            while j + 1 < len(c) and c[j + 1]:
                j += 1
            if j - i + 1 >= 3:
                seg = g.iloc[i:j + 1]
                events.append({"file": fn, "T_pack": None if tp != tp else round(float(tp), 1), "dur_s": int(len(seg)), "rpm_start": round(float(seg.rpm.iloc[0])), "rpm_end": round(float(seg.rpm.iloc[-1])),
                               "soc_mean": round(float(seg.soc.mean()), 1), "boost_med": round(float(seg.boost.median()), 2), "load_med": round(float(seg.load.median()), 1)})
            i = j + 1
        else:
            i += 1
E = pd.DataFrame(events)
out = {"definition": {"PUB": "rpm>2000 & boost<-0.70 & load<8", "FUEL": "rpm>1200 & fuel_rate<0.2 L/h & abs throttle B<10 %"}, "totals_seconds": tot, "by_rpm_band": byrpm, "by_soc_band": bysoc,
       "fuel_only_events": {"n": int(len(E)), "dur_s_median": float(E.dur_s.median()) if len(E) else None, "dur_s_p90": float(E.dur_s.quantile(0.9)) if len(E) else None,
                            "rpm_end_lt_rpm_start_share": float((E.rpm_end < E.rpm_start).mean()) if len(E) else None, "soc_mean_median": float(E.soc_mean.median()) if len(E) else None,
                            "boost_med_median": float(E.boost_med.median()) if len(E) else None, "load_med_median": float(E.load_med.median()) if len(E) else None,
                            "by_tpack": {("unknown" if k != k else ("<15" if k < 15 else ("15-25" if k < 25 else ">=25"))): int(v) for k, v in E.assign(T=E.T_pack).groupby(E.T_pack.map(lambda x: np.nan if x is None else x)).size().items()} if len(E) else {}}}
json.dump(out, open("analyses/M394_fuel_crosscheck.json", "w", encoding="utf-8", newline="\n"), indent=1, default=float)
print(json.dumps(out, indent=0, default=float)[:3000])
