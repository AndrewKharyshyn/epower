#!/usr/bin/env python3
"""Delta report -> delta_report.json. Compares KPIs in summary_arrays.json with the previous snapshot in
snapshots/kpis.jsonl (append-only history). Flags: (1) value outside previous CI; (2) |delta| > 0.5 x previous CI
half-width (standardised effect vs baseline); (3) cumulative drift from the FIRST snapshot > CI half-width;
(4) CI half-width change > 50%. Any single flag routes the milestone to audit + Director.
KPI specs: tools/kpi_paths.json ({name, path:[...], ci:[lo_path, hi_path]}). Usage: python tools/delta_report.py [--commit]
--commit appends the current KPIs as the new snapshot (do this after the milestone is accepted)."""
import argparse, datetime as dt, json, os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
P = lambda *a: os.path.join(ROOT, *a)


def dig(d, path):
    for k in path:
        if isinstance(d, dict) and k in d:
            d = d[k]
        else:
            return None
    return d


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--commit", action="store_true"); a = ap.parse_args()
    arr = json.load(open(P("summary_arrays.json"), encoding="utf-8"))
    specs = json.load(open(P("tools", "kpi_paths.json")))["kpis"]
    cur = {}
    for s in specs:
        v = dig(arr, s["path"])
        ci = [dig(arr, p) for p in s["ci"]] if s.get("ci") else None
        cur[s["name"]] = {"value": v, "ci": ci}
    hist_p = P("snapshots", "kpis.jsonl")
    hist = [json.loads(l) for l in open(hist_p)] if os.path.exists(hist_p) else []
    prev = hist[-1]["kpis"] if hist else None
    first = hist[0]["kpis"] if hist else None
    rep, flags = {}, []
    for name, c in cur.items():
        r = {"value": c["value"], "ci": c["ci"]}
        if prev and name in prev and isinstance(c["value"], (int, float)) and isinstance(prev[name]["value"], (int, float)):
            pv, pci = prev[name]["value"], prev[name]["ci"]
            r["prev"] = pv; r["delta"] = c["value"] - pv
            if pci and None not in pci:
                hw = (pci[1] - pci[0]) / 2
                r["outside_prev_ci"] = not (pci[0] <= c["value"] <= pci[1])
                r["delta_over_halfwidth"] = (r["delta"] / hw) if hw else None
                if r["outside_prev_ci"]: flags.append(f"{name}: outside previous CI")
                if hw and abs(r["delta"]) > 0.5 * hw: flags.append(f"{name}: |delta| > 0.5 x prev CI half-width")
                if c["ci"] and None not in c["ci"]:
                    nhw = (c["ci"][1] - c["ci"][0]) / 2
                    if hw and abs(nhw - hw) / hw > 0.5: flags.append(f"{name}: CI half-width changed >50%")
                if first and name in first and first[name]["ci"] and None not in first[name]["ci"]:
                    fhw = (first[name]["ci"][1] - first[name]["ci"][0]) / 2
                    r["cumulative_drift"] = c["value"] - first[name]["value"]
                    if fhw and abs(r["cumulative_drift"]) > fhw: flags.append(f"{name}: cumulative drift > baseline CI half-width")
        rep[name] = r
    gf = P("analyses/gtr_family_delta.json")     # M377b: GTR-family refresh delta (per-block n drives / n days, moves, band and STOP outcomes)
    gtr = json.load(open(gf, encoding="utf-8")) if os.path.exists(gf) else None
    if gtr:
        flags += [f"gtrFamily: {x}" for x in gtr.get("stops", [])]
    out = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "has_baseline": bool(prev),
           "flags": flags, "route_to_audit": bool(flags), "kpis": rep, "gtrFamily": gtr}
    json.dump(out, open(P("delta_report.json"), "w"), indent=1)
    print(json.dumps({"has_baseline": out["has_baseline"], "route_to_audit": out["route_to_audit"], "flags": flags}, indent=1))
    if a.commit:
        os.makedirs(P("snapshots"), exist_ok=True)
        with open(hist_p, "a") as f:
            f.write(json.dumps({"utc": out["generated_utc"], "kpis": cur}) + "\n")


if __name__ == "__main__":
    main()
