#!/usr/bin/env python3
"""M559: the tool's per-window summary for the 58 blind-audit windows (analyses/M559_audit_sample.json), written to analyses/M559_window_report.json. The auditor's table is compared with this file at the count level.
Usage: python tools/m559_window_report.py"""
import io, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import engine_context_fields as E
import compute_summary_arrays as C

raw_dir = os.environ.get("XT_RAW_DIR", os.path.join(ROOT, "raw"))
dig = lambda s: "".join(ch for ch in s if ch.isdigit())[:14]
rawmap = {dig(f): f for f in os.listdir(raw_dir) if f.endswith(".csv")}
S = json.load(open(os.path.join(ROOT, "analyses", "M559_audit_sample.json"), encoding="utf-8"))
out = []
cache = {}
for w in S["windows"]:
    f = w["file"]
    if f not in cache:
        b = open(os.path.join(raw_dir, rawmap[dig(f)]), "rb").read()
        df = pd.read_csv(io.BytesIO(b), usecols=lambda c: c in E.COLS or c in ("time", E.COOL, C._SPEED_OBD_RAW), low_memory=False)
        g, df2 = E._grid(df)
        fu = g["fuel"].to_numpy(float) if "fuel" in g else np.array([])
        flags = {"hasBoost": "boost" in g and bool(np.isfinite(g["boost"]).any()), "hasLoad": "load" in g and bool(np.isfinite(g["load"]).any()),
                 "fuelOk": bool("fuel" in g and np.nanmax(np.where(np.isfinite(fu), fu, 0.0)) > 0), "hasCool": E.COOL in df.columns and bool(pd.to_numeric(df[E.COOL], errors="coerce").notna().any()), "hasRpm": True}
        g["I"] = -g["I"]
        for c in ("boost", "load", "fuel", "soc", "speed"):
            if c not in g:
                g[c] = np.nan
        tns = g.index.values.astype("datetime64[ns]").astype("int64")
        if flags["hasCool"]:
            ct = pd.to_numeric(df[E.COOL], errors="coerce")
            tt = pd.Series(pd.to_datetime(C._ft(df["time"]))).values.astype("datetime64[ns]").astype("int64")
            mk = ct.notna().to_numpy(); order = np.argsort(tt[mk], kind="stable")
            cool, age = E.coolant_age(tns, tt[mk][order], ct.to_numpy(float)[mk][order])
        else:
            cool, age = np.full(len(g), np.nan), np.full(len(g), np.nan)
        r = E.classify(g, cool, age, flags, dict(E.BASE))
        cache[f] = (g, r)
    g, r = cache[f]
    lo, hi = pd.Timestamp(w["startTime"]), pd.Timestamp(w["endTime"])
    rr = r[(r.index >= lo) & (r.index <= hi)]
    cnt = {}
    for col in ("rot", "flow", "thermal", "comb"):
        for k, v in rr[col].value_counts().items():
            cnt[f"{col}_{k}"] = int(v)
    for L in E.LABELS:
        cnt["label_" + L] = int(rr[L].sum())
    lab = rr[list(E.LABELS)].to_numpy(bool)
    cnt["unresolved"] = int((~lab.any(axis=1)).sum()); cnt["spin"] = int(rr["spin"].sum()); cnt["rotatingSeconds"] = int(len(rr)); cnt["fuelFlag"] = int(rr["fuelFlag"].sum())
    cnt["rpmExactly2000"] = int(((g.loc[rr.index, "rpm"] == 2000.0) & (rr["comb"] == "motored") & rr["lowLoad"]).sum()) if len(rr) else 0   # as the brief's re-run: rpm exactly 2000 AND motored AND low load (spin ignored)
    cnt["unsureEntries"] = None
    out.append({"idx0": int(w["startIndexS"]), "file": f, "category": w["category"], "stratum": w["stratum"], "startTime": w["startTime"], "endTime": w["endTime"], "counts": cnt})
json.dump({"milestone": "M559", "windows": out}, open(os.path.join(ROOT, "analyses", "M559_window_report.json"), "w", encoding="utf-8"), indent=1)
print(len(out), "windows")
