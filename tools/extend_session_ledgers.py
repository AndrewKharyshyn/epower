#!/usr/bin/env python3
"""Extend the hand-maintained session ledgers in summary_config.json (`sessionGroups` = "Sessions (grouped by phase)" and `sessions` = detailed
per-day panel) to every calendar day of drive_master.csv that is newer than the last date-resolvable ledger row (M313; standing rule: new drives are
added to that section on EVERY ingestion). One row per new day in each ledger; every number is computed from drive_master.csv, seasonal_drive_master.csv,
raw_temperature_triplets.csv, summary_config.json ambientByDrive and the raw CSV headers, never typed. Then regenerates the sessionLedgerAudit block in
summary_arrays.json (compute_summary_arrays._session_ledger_audit; additive splice, only that key may change).
Older uncovered dates are NOT touched unless --from-date is given (M313 used it to backfill Sep 04-11); new rows are inserted chronologically.
Usage: python tools/extend_session_ledgers.py [--from-date YYYY-MM-DD] [--dry-run] [--check-day YYYY-MM-DD]   (--check-day prints the generated rows for an existing day)"""
import argparse, datetime as dt, hashlib, json, os, re, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WORDS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten", 11: "Eleven", 12: "Twelve", 13: "Thirteen", 14: "Fourteen"}
digits = lambda s: re.sub(r"\D", "", str(s).rsplit(".", 1)[0])


def amb_txt(v):
    v = [int(round(float(x))) for x in (v if isinstance(v, list) else [v, v])]
    return f"+{v[0]}" if len(set(v)) == 1 else "+" + "→".join(str(x) for x in [v[0]] + [y for y in v[1:]])


def raw_header_sig(fn, rawdir, idx):
    p = idx.get(digits(fn))
    if not p:
        return None
    with open(os.path.join(rawdir, p), encoding="utf-8", errors="replace") as f:
        return hashlib.md5(f.readline().strip().encode("utf-8")).hexdigest()


def build_rows(day, g, prev_sig, sigs, amb, sdm, trip):
    n = len(g)
    km = float(g["distance_km"].sum())
    minutes = float(g["duration_s"].sum()) / 60.0
    gross, gtc, net = float(g["gross_throughput_kwh"].sum()), float(g["gtc"].sum()), float(g["net_draw_kwh_corr2p"].sum())
    clean = int((~g["ens_outlier_v2"].fillna(False).astype(bool)).sum())
    signok = int((g["sign_check"].astype(str) == "ok").sum())
    typ = g.groupby("drive_type")["distance_km"].sum().sort_values(ascending=False)
    dtype = str(typ.index[0]) if len(typ) else "unknown"
    urban_all = set(g["drive_type"].astype(str)) == {"urban"}
    starts = [str(t)[:5] for t in g["time_start"]]
    ambs = [amb.get(f) for f in g["file"]]
    flat = [float(x) for a in ambs if a is not None for x in (a if isinstance(a, list) else [a])]
    a_lo, a_hi = (int(round(min(flat))), int(round(max(flat)))) if flat else (None, None)
    rng_txt = "" if a_lo is None else (f"{a_lo}–{a_hi}°C" if a_lo != a_hi else f"{a_lo}°C")
    reg = sdm[sdm["file"].isin(g["file"])]["thermal_regime_raw"].value_counts().to_dict()
    reg_txt = ", ".join(f"{v} {k}" for k, v in sorted(reg.items(), key=lambda kv: -kv[1]))
    net_txt = "near-neutral" if abs(net) < 0.05 else ("net-charge bias" if net < 0 else "net-discharge bias")
    swing = (g["soc_max"] - g["soc_min"]).astype(float)           # SoC range span per drive (== seasonal soc_range_span_pp), as the hand-written ledgers used
    i_sw = int(np.nanargmax(np.abs(swing.values)))
    i_lg = int(np.nanargmax(g["distance_km"].values))
    t = trip.set_index("file") if "file" in trip.columns else None
    unwarm = []
    for k, (_, r) in enumerate(g.iterrows()):
        if t is not None and r["file"] in t.index and ambs[k] is not None:
            oil, cool = t.loc[r["file"], "oil_temp_start_c"], t.loc[r["file"], "engine_coolant_start_c"]
            a0 = float((ambs[k] if isinstance(ambs[k], list) else [ambs[k]])[0])
            if pd.notna(oil) and pd.notna(cool) and oil <= a0 + 3 and cool <= a0 + 3:
                unwarm.append(f"D{k + 1} (oil {int(round(float(oil)))}°C / coolant {int(round(float(cool)))}°C at +{int(round(a0))}°C)")
    pid_same = all(s == (prev_sig if k == 0 else sigs[k - 1]) for k, s in enumerate(sigs)) and prev_sig is not None
    pid_txt = "no PID-configuration change" if pid_same else ("PID configuration differs from the previous drive" if prev_sig is not None else "PID configuration not checked (no previous drive)")
    day_txt = "across the full day" if (len(starts) > 1 and int(starts[-1][:2]) - int(starts[0][:2]) >= 8) else "within a short window"
    name = f"{MON[day.month - 1]} {day.day}"
    leg = lambda k: f"D{k + 1} ({starts[k]}, {float(g['distance_km'].iloc[k]):.1f}km" + (f", {amb_txt(ambs[k])}°C" if ambs[k] is not None else "") + ")"
    sw = swing.iloc[i_sw]
    common = (f"{WORDS.get(n, str(n))} {'urban ' if urban_all else ''}leg{'s' if n != 1 else ''}, {km:.1f}km / {minutes:.1f}min, {gross:.4f} kWh gross, GTC {gtc:.4f}, "
              f"{net:+.4f} kWh net corr2p sum ({net_txt}).")
    tail = (f" Largest SoC swing: {leg(i_sw)} SoC {float(g['soc_min'].iloc[i_sw]):.0f}→{float(g['soc_max'].iloc[i_sw]):.0f} ({sw:+.1f}pp). Longest leg: {leg(i_lg)}."
            + (f" Unwarmed starts (oil and coolant within 3°C of ambient): {'; '.join(unwarm[:4])}{' and more' if len(unwarm) > 4 else ''}." if unwarm else "")
            + f" {clean} of {n} ens_outlier_v2-clean, {signok} of {n} sign_check ok.")
    amb_part = f" Ambients {rng_txt}; thermal regime (raw class): {reg_txt}." if rng_txt else ""
    group = {"name": name, "phase": f"Routine ingestion, {WORDS.get(n, str(n)).lower()} leg{'s' if n != 1 else ''} {day_txt}; {pid_txt}; ambient {rng_txt or 'n/a'}",
             "drives": n, "km": round(km, 1), "type": dtype, "note": common + amb_part + tail}
    sess = {"name": name, "drives": n, "km": round(km, 1), "type": dtype,
            "note": f"{WORDS.get(n, str(n))} {dtype} leg{'s' if n != 1 else ''} ({starts[0]}→{starts[-1]}), {km:.1f}km / {minutes:.1f}min, {gross:.4f} kWh gross, GTC {gtc:.4f}, {net:+.4f} kWh net corr2p sum ({net_txt})."
                    + amb_part + tail}
    return group, sess, [starts[-1]]


def first_md(name):
    """(month, day) of the first date token of a ledger row name ('Sep 22', 'May 11-18', 'Jun 29 - Jul 07'); None for names without one."""
    m = re.search(r"([A-Za-z]{3})\s*0?(\d{1,2})", str(name))
    return (MON.index(m.group(1).title()) + 1, int(m.group(2))) if m and m.group(1).title() in MON else None


def insert_chrono(rows, new_rows, days):
    """Insert each new row before the first existing row whose first date is later (keeps the ledgers chronological when backfilling)."""
    out = list(rows)
    for day, r in sorted(zip(days, new_rows), key=lambda x: x[0]):
        pos = len(out)
        for i, e in enumerate(out):
            md = first_md(e.get("name"))
            if md is not None and md > (day.month, day.day):
                pos = i
                break
        out.insert(pos, r)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-date")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check-day")
    a = ap.parse_args()
    cfg = json.load(open("summary_config.json", encoding="utf-8"))
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    sdm = pd.read_csv("seasonal_drive_master.csv", low_memory=False)
    trip = pd.read_csv("raw_temperature_triplets.csv", low_memory=False)
    amb = cfg["ambientByDrive"]
    rawdir = os.path.join(ROOT, "raw")
    idx = {digits(f): f for f in os.listdir(rawdir) if f.lower().endswith(".csv")}
    dm["_d"] = pd.to_datetime(dm["date"]).dt.date
    dm = dm.sort_values(["date", "time_start"]).reset_index(drop=True)
    import compute_summary_arrays as csa
    au = csa._session_ledger_audit(dm.drop(columns="_d"), cfg)
    covered_dates = set(dm["_d"]) - {dt.date.fromisoformat(x) for x in au["sessionGroups"]["datesUncovered"]}
    last_cov = max(covered_dates) if covered_dates else None
    days = sorted(set(dm["_d"]))
    if a.check_day:
        targets = [dt.date.fromisoformat(a.check_day)]
    elif a.from_date:
        targets = [d for d in days if d >= dt.date.fromisoformat(a.from_date) and d not in covered_dates]
    else:
        targets = [d for d in days if last_cov is not None and d > last_cov]
    if not targets:
        print(json.dumps({"status": "nothing to add", "last_covered": str(last_cov)}))
        return
    out_g, out_s = [], []
    for day in targets:
        g = dm[dm["_d"] == day].reset_index(drop=True)
        before = dm[dm["_d"] < day]
        prev_sig = raw_header_sig(before["file"].iloc[-1], rawdir, idx) if len(before) else None
        sigs = [raw_header_sig(f, rawdir, idx) for f in g["file"]]
        grow, srow, _ = build_rows(day, g, prev_sig, sigs, amb, sdm, trip)
        out_g.append(grow)
        out_s.append(srow)
    if a.check_day:
        print(json.dumps({"generated_group": out_g[0], "generated_session": out_s[0]}, ensure_ascii=False, indent=1))
        return
    names_g = {r["name"] for r in cfg["sessionGroups"]}
    assert not any(r["name"] in names_g for r in out_g), "a generated day already exists in sessionGroups"
    cfg["sessionGroups"] = insert_chrono(cfg["sessionGroups"], out_g, targets)
    cfg["sessions"] = insert_chrono(cfg["sessions"], out_s, targets)
    res = {"added_days": [r["name"] for r in out_g], "added_drives": int(sum(r["drives"] for r in out_g)), "added_km": round(sum(r["km"] for r in out_g), 1)}
    if not a.dry_run:
        with open("summary_config.json", "w", encoding="utf-8") as f:
            f.write(json.dumps(cfg, ensure_ascii=False, indent=1))
        A = json.load(open("summary_arrays.json", encoding="utf-8"))
        new_audit = csa._session_ledger_audit(dm.drop(columns="_d"), cfg)
        A["sessionLedgerAudit"] = new_audit
        with open("summary_arrays.json", "w", encoding="utf-8") as f:
            f.write(json.dumps(A, ensure_ascii=False, indent=1))
        res["audit"] = {k: {x: new_audit[k][x] for x in ("nRows", "cfgDrives", "nMismatched", "driveShortfall", "datesUncovered")} for k in ("sessions", "sessionGroups")}
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
