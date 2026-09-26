#!/usr/bin/env python3
"""Compare docs/claim_register.csv rows with current summary_arrays.json. source_json_path is a dotted path
(e.g. seasonalCharts.charts.EnergyIntensity.data.all.value). Prints rows whose value changed or whose path vanished ->
claim_check.json. Usage: python tools/claim_check.py"""
import csv, json, os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
P = lambda *a: os.path.join(ROOT, *a)


def dig(d, path):
    for k in path.split("."):
        if isinstance(d, dict) and k in d:
            d = d[k]
        elif isinstance(d, list) and k.isdigit() and int(k) < len(d):
            d = d[int(k)]
        else:
            return "__MISSING__"
    return d


def main():
    arr = json.load(open(P("summary_arrays.json"), encoding="utf-8"))
    rows, changed = list(csv.DictReader(open(P("docs", "claim_register.csv"), newline=""))), []
    for r in rows:
        if not r.get("source_json_path"):
            continue
        now = dig(arr, r["source_json_path"])
        was = r.get("source_value_at_check", "")
        same = (str(now) == was) or (isinstance(now, float) and was != "" and abs(now - float(was)) < 1e-9)
        if not same:
            changed.append({"claim_id": r["claim_id"], "path": r["source_json_path"], "was": was, "now": now})
    json.dump({"n_rows": len(rows), "changed": changed}, open(P("claim_check.json"), "w"), indent=1, default=str)
    print(json.dumps({"n_rows": len(rows), "n_changed": len(changed), "changed_ids": [c["claim_id"] for c in changed]}))


if __name__ == "__main__":
    main()
