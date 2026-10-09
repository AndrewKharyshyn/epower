#!/usr/bin/env python3
"""M394 exploratory scan (read-only, script-written JSON analyses/M394_dissipation_scan.json): what does the unfuelled (motored) dissipation classifier see across the corpus, and how would a
winter regime (cold pack, lower SoC, lower rpm) look to it?  Same 1 s grid and channels as compute_summary_arrays._dissipation_census (M46). No payload value is changed.
Classifiers per 1 s sample (boost < -0.70 ~ MAP < 25 kPa and calc load < 8 %, i.e. closed throttle / no combustion load):
  CUR  rpm > 2000                      (the published census)
  RLX  rpm > 800                       (relaxed gate; counts engine spin below 2000 rpm)
Events = runs of consecutive CUR samples >= 3 s. Per event: duration, rpm start / mean / end and slope (spin-down vs sustained), SoC mean, pack temperature (drive mean), speed, pack current.
Split by drive pack-temperature band (T_pack_mean_avg: <15, 15-25, >=25 C) and SoC band (<60, 60-75, 75-85, >=85).  Usage: python analyses/M394_dissipation_scan.py"""
import json, os, sys, time
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
os.environ.setdefault("XT_RAW_DIR", os.path.join(ROOT, "raw"))
import drive_raw_cache as drc

C = {'[BMS] HV Battery Current (A)': 'I', '[BMS] HV State of charge (%)': 'soc', '[VCM] Vehicle Speed (km/h)': 'speed', 'Оберти двигуна (rpm)': 'rpm',
     'Розрахункове значення навантаження на двигун (%)': 'load', 'Розрахунковий наддув (bar)': 'boost'}
BOOST_M, LOAD_MAX, CEIL = -0.70, 8.0, 85.0
dm = pd.read_csv("drive_master.csv", low_memory=False)
fl = drc.make_frame_loader()
rows, events = [], []
t0 = time.time()
for n, (fn, tp) in enumerate(zip(dm["file"].astype(str), dm["T_pack_mean_avg"])):
    fr = fl(fn)
    if fr is None or 'time' not in fr.columns:
        continue
    fr = fr[[c for c in fr.columns if c in C or c == 'time']].rename(columns=C)
    need = [c for c in ('I', 'soc', 'speed', 'rpm', 'load', 'boost') if c in fr.columns]
    if not {'rpm', 'boost', 'load', 'soc'} <= set(need):
        continue
    g = fr.set_index(pd.to_datetime(fr['time'], errors='coerce'))[need].apply(pd.to_numeric, errors='coerce')
    g = g[g.index.notna()].resample('1s').mean().ffill(limit=3).dropna(subset=['soc', 'rpm', 'boost'])
    g['load'] = g['load'].fillna(0)
    base_low = (g['boost'] < BOOST_M) & (g['load'] < LOAD_MAX)
    cur = (g['rpm'] > 2000) & base_low
    rlx = (g['rpm'] > 800) & base_low
    rows.append({"file": fn, "T_pack": None if tp != tp else float(tp), "n_cur": int(cur.sum()), "n_rlx": int(rlx.sum()), "n_rlx_below2000": int((rlx & ~cur).sum()),
                 "n_cur_soc_lt85": int((cur & (g['soc'] < CEIL)).sum()), "n_cur_soc_ge85": int((cur & (g['soc'] >= CEIL)).sum()), "n_seconds": int(len(g))})
    # events: runs of CUR samples >= 3 s
    c = cur.values
    i = 0
    while i < len(c):
        if c[i]:
            j = i
            while j + 1 < len(c) and c[j + 1]:
                j += 1
            if j - i + 1 >= 3:
                seg = g.iloc[i:j + 1]
                x = np.arange(len(seg)); sl = float(np.polyfit(x, seg['rpm'].values, 1)[0]) if len(seg) >= 3 else 0.0
                events.append({"file": fn, "T_pack": None if tp != tp else float(tp), "dur_s": int(len(seg)), "rpm_start": float(seg['rpm'].iloc[0]), "rpm_mean": float(seg['rpm'].mean()),
                               "rpm_end": float(seg['rpm'].iloc[-1]), "rpm_slope_per_s": sl, "soc_mean": float(seg['soc'].mean()), "speed_mean": float(seg['speed'].mean()) if 'speed' in seg else None,
                               "I_mean": float(seg['I'].mean()) if 'I' in seg else None})
            i = j + 1
        else:
            i += 1
    if (n + 1) % 100 == 0:
        print(f"  {n + 1}/{len(dm)} drives, {round(time.time() - t0)} s", flush=True)
R, E = pd.DataFrame(rows), pd.DataFrame(events)
band = lambda t: "unknown" if t is None or t != t else ("<15C" if t < 15 else ("15-25C" if t < 25 else ">=25C"))
R["tband"] = R["T_pack"].map(band); E["tband"] = E["T_pack"].map(band)
E["sustained"] = (E["dur_s"] >= 10) & (E["rpm_slope_per_s"].abs() < 30)          # not a spin-down ramp
E["soc_band"] = pd.cut(E["soc_mean"], [0, 60, 75, 85, 101], labels=["<60", "60-75", "75-85", ">=85"], right=False)
out = {"params": {"rpm_cur": 2000, "rpm_relaxed": 800, "boost": BOOST_M, "load_max": LOAD_MAX, "ceil_soc": CEIL, "event_min_s": 3, "sustained": "dur >= 10 s and |rpm slope| < 30 rpm/s"},
       "n_drives_scanned": int(len(R)),
       "samples": {"cur": int(R.n_cur.sum()), "relaxed": int(R.n_rlx.sum()), "relaxed_below_2000rpm": int(R.n_rlx_below2000.sum()), "cur_soc_lt85": int(R.n_cur_soc_lt85.sum()), "cur_soc_ge85": int(R.n_cur_soc_ge85.sum())},
       "drives_with_cur": int((R.n_cur > 0).sum()), "drives_with_cur_by_tband": {k: int(v) for k, v in R[R.n_cur > 0].groupby("tband").size().items()},
       "drives_by_tband": {k: int(v) for k, v in R.groupby("tband").size().items()},
       "n_events": int(len(E)), "events_by_tband": {k: int(v) for k, v in E.groupby("tband").size().items()},
       "events_sustained": int(E.sustained.sum()), "events_by_soc_band": {str(k): int(v) for k, v in E.groupby("soc_band", observed=False).size().items()},
       "events_sustained_by_soc_band": {str(k): int(v) for k, v in E[E.sustained].groupby("soc_band", observed=False).size().items()},
       "event_dur_s_quantiles": {str(q): float(E.dur_s.quantile(q)) for q in (0.5, 0.9, 0.99)} if len(E) else None,
       "event_rpm_mean_quantiles": {str(q): float(E.rpm_mean.quantile(q)) for q in (0.1, 0.5, 0.9)} if len(E) else None,
       "spin_down_share": float((E.rpm_slope_per_s < -30).mean()) if len(E) else None,
       "median_pack_current_A_sustained_ge85": float(E[(E.sustained) & (E.soc_mean >= 85)].I_mean.median()) if int(((E.sustained) & (E.soc_mean >= 85)).sum()) else None,
       "events_tail": E.sort_values("dur_s", ascending=False).head(15).to_dict("records")}
json.dump(out, open("analyses/M394_dissipation_scan.json", "w", encoding="utf-8", newline="\n"), indent=1, default=float)
print(json.dumps({k: v for k, v in out.items() if k != "events_tail"}, indent=0, default=float)[:3500])
