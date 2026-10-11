"""M402: compare the blind auditor's results (auditor_results.json) with the sidecar ah_throughput.csv; writes compare_results.json. Run after the auditor; read-only on the repo."""
import json, os
import pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(D, "..", ".."))
aud = json.load(open(os.path.join(D, "auditor_results.json"), encoding="utf-8"))["files"]
side = pd.read_csv(os.path.join(ROOT, "ah_throughput.csv"), keep_default_na=False, na_values=[""]).set_index("file")
rows, bad = [], []
for f, a in sorted(aud.items()):
    s = side.loc[f]
    sv = s["ah_discharge"]
    if a["ah_discharge"] is None or pd.isna(sv):
        agree_null = a["ah_discharge"] is None and pd.isna(sv)
        rows.append({"file": f, "null_agree": agree_null, "auditor_reason": a.get("reason"), "sidecar_reason": None if pd.isna(s["reason"]) else s["reason"]})
        if not agree_null: bad.append(f)
        continue
    dd, dc = abs(a["ah_discharge"] - sv), abs(a["ah_charge"] - s["ah_charge"])
    rel = max(dd / max(abs(sv), 1e-12), dc / max(abs(s["ah_charge"]), 1e-12))
    ok = dd <= 2e-6 + 1e-6 * abs(sv) and dc <= 2e-6 + 1e-6 * abs(s["ah_charge"]) and int(a["n_pairs"]) == int(s["n_pairs"]) and int(a["n_crossings"]) == int(s["n_crossings"])
    rows.append({"file": f, "abs_diff_discharge": dd, "abs_diff_charge": dc, "max_rel": rel, "n_pairs_equal": int(a["n_pairs"]) == int(s["n_pairs"]), "n_crossings_equal": int(a["n_crossings"]) == int(s["n_crossings"]), "ok": ok})
    if not ok: bad.append(f)
vals = [r for r in rows if "ok" in r]
out = {"n_files": len(rows), "n_valued": len(vals), "n_null_agree": sum(1 for r in rows if r.get("null_agree")), "disagreements": bad,
       "max_abs_diff_ah": max([max(r["abs_diff_discharge"], r["abs_diff_charge"]) for r in vals] or [0.0]), "max_rel": max([r["max_rel"] for r in vals] or [0.0]), "rows": rows}
json.dump(out, open(os.path.join(D, "compare_results.json"), "w", encoding="utf-8"), indent=1)
print(json.dumps({k: out[k] for k in ("n_files", "n_valued", "n_null_agree", "disagreements", "max_abs_diff_ah", "max_rel")}))
