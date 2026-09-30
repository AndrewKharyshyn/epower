#!/usr/bin/env python3
"""F03 provenance-sensitivity: headline KPI deltas between two summary_arrays.json files.
Usage: python tools/f03_headline_delta.py PUBLISHED.json FRESH.json OUT.json [--spec tools/f03_headline_kpis.json]
Per KPI: published/fresh value, abs and relative delta, published CI, whether fresh lies outside the published CI,
CI-width-relative shift, and decision flips. Escalation rule (CLAUDE.md, owner decisions): outside-CI or flip -> Director."""
import json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def get(o, path):
    for p in path:
        if isinstance(o, dict) and p in o:
            o = o[p]
        elif isinstance(o, list) and isinstance(p, int) and p < len(o):
            o = o[p]
        else:
            return None
    return o


def ci_of(o, spec):
    c = spec.get("ci")
    if not c:
        return None
    if isinstance(c[0], list):
        lo, hi = get(o, c[0]), get(o, c[1])
    else:
        v = get(o, c)
        lo, hi = (v[0], v[1]) if isinstance(v, list) and len(v) == 2 else (None, None)
    return (lo, hi) if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) else None


def main():
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    spec_path = sys.argv[sys.argv.index("--spec") + 1] if "--spec" in sys.argv else os.path.join(ROOT, "tools", "f03_headline_kpis.json")
    if "--spec" in sys.argv:
        a.remove(spec_path)
    pub, fresh = json.load(open(a[0])), json.load(open(a[1]))
    rows, esc = [], []
    for k in json.load(open(spec_path))["kpis"]:
        pv, fv = get(pub, k["path"]), get(fresh, k["path"])
        r = {"name": k["name"], "published": pv, "fresh": fv}
        if pv is None or fv is None:
            r["status"] = "path_missing"
        elif k.get("flag"):
            r["status"] = "flip" if pv != fv else "same"
        else:
            r["absDelta"] = round(fv - pv, 6)
            r["relDeltaPct"] = None if pv == 0 else round((fv - pv) / abs(pv) * 100, 4)
            ci = ci_of(pub, k)
            if ci:
                w = ci[1] - ci[0]
                r["publishedCI"] = list(ci)
                r["freshInsidePublishedCI"] = ci[0] <= fv <= ci[1]
                r["deltaInPublishedCIWidths"] = None if w == 0 else round((fv - pv) / w, 4)
                r["status"] = "same" if fv == pv else ("inside_ci" if r["freshInsidePublishedCI"] else "OUTSIDE_CI")
            else:
                r["status"] = "same" if fv == pv else "changed_no_ci"
        rows.append(r)
        if r["status"] in ("flip", "OUTSIDE_CI"):
            esc.append(k["name"])
    out = {"published": a[0], "fresh": a[1], "nKpis": len(rows), "escalate": esc, "kpis": rows}
    json.dump(out, open(a[2], "w"), indent=1)
    print(json.dumps({"nKpis": len(rows), "missing": [r["name"] for r in rows if r["status"] == "path_missing"], "escalate": esc}, indent=1))


if __name__ == "__main__":
    main()
