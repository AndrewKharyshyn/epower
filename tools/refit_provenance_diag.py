#!/usr/bin/env python3
"""Refit-audit provenance diagnostic (M311 prep; Director 2026-09-30). Read-only: never writes drive_master.csv or raw/.

Question: is the clean-room rebuild drift (117/186 columns at 489 drives) caused by raw CONTENT (today's raw files differ from the
originals) or by a CODE-PATH difference? Method: rebuild the master from the staged raw archive exactly as master_refit_audit.py does,
then compare per row against the published drive_master.csv, in three groups:
  new        : the 43 drives ingested from the files now in git (hash recorded at ingestion, so byte-identical by construction)
  hash_ok    : pre-existing drives whose raw file SHA-256 equals the raw_manifest.json record
  hash_fail  : pre-existing drives whose raw file SHA-256 differs from the manifest (F03)
RAW-DERIVED columns only (ML16, offset cascade, corpus-level refits and the M15/M19 adjustments are excluded: they move with the corpus).
Zero drift in new + hash_ok rows => same code path, cause is content. Any drift there => code-path difference (blocks the provenance reading).
Also reports decimal precision of current/torque columns in a few hash-failing vs hash-ok raw files (first lines only).
Usage: XT_RAW=$PWD/raw_only python tools/refit_provenance_diag.py [--workers 4]   (run tools/stage_raw.py first). Writes analyses/M311_refit_provenance_diag.json."""
import hashlib, json, os, re, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ.setdefault("XT_RAW", os.path.join(ROOT, "raw_only"))
import master_refit_audit as M

TOL = 1e-9
ML16 = ['drive_cluster_k3', 'iso_outlier', 'iso_score', 'lof_score', 'f_iso', 'f_lof', 'f_mad', 'f_domain', 'ens_outlier',
        'f_domain_2p', 'f_iso_i', 'f_lof_i', 'f_mad_i', 'ens_invalid', 'ens_extreme', 'ens_outlier_v2']
CORPUS_LEVEL = re.compile(r"(_corr|_applied|offset_|implied_offset|_adj_|cell_spread_loaded_p95_adj)")
digits = lambda s: re.sub(r"\D", "", str(s).rsplit(".", 1)[0])


def main():
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 2
    pub = pd.read_csv("drive_master.csv", low_memory=False).set_index("file")
    reb = M.rebuild(workers).set_index("file").loc[pub.index]
    man = json.load(open("raw_manifest.json", encoding="utf-8"))
    rec = {digits(r["raw_name"]): r["sha256"] for r in man["files"] if r.get("raw_name") and r["role"] == "canonical"}
    rawdir = os.path.join(ROOT, "raw")
    by_digits = {digits(f): f for f in os.listdir(rawdir) if f.lower().endswith(".csv")}
    grp = {}
    new_keys = {f for f in pub.index if digits(f) >= "20260923"}
    for f in pub.index:
        d = digits(f)
        if f in new_keys:
            grp[f] = "new"
            continue
        fn = by_digits.get(d)
        ok = fn is not None and d in rec and hashlib.sha256(open(os.path.join(rawdir, fn), "rb").read()).hexdigest() == rec[d]
        grp[f] = "hash_ok" if ok else "hash_fail"
    g = pd.Series(grp)
    cols = [c for c in pub.columns if c in reb.columns and c not in ML16 and not CORPUS_LEVEL.search(c)]
    out = {"groups": g.value_counts().to_dict(), "columns_compared": len(cols), "tolerance": TOL, "perGroup": {}}
    for name in ("new", "hash_ok", "hash_fail"):
        idx = g.index[g == name]
        drift = {}
        for c in cols:
            x, y = pub.loc[idx, c], reb.loc[idx, c]
            both = x.notna() & y.notna()
            if pd.api.types.is_numeric_dtype(x) and pd.api.types.is_numeric_dtype(y) and x.dtype != bool and y.dtype != bool:
                d = (x[both].astype(float) - y[both].astype(float)).abs()
                n, mx = int((d > TOL).sum()), (float(d.max()) if len(d) else 0.0)
            else:
                n, mx = int((x[both].astype(str) != y[both].astype(str)).sum()), None
            nm = int((x.isna() != y.isna()).sum())
            if n or nm:
                drift[c] = {"rowsDiffer": n, "nullMismatch": nm, "maxAbsDiff": mx}
        out["perGroup"][name] = {"n_rows": int(len(idx)), "columnsDrifted": len(drift), "drift": drift}
    # decimal precision of current / torque columns: first 30 data lines of up to 3 files per group
    def decimals(path):
        with open(path, encoding="utf-8", errors="replace") as fh:
            hdr = fh.readline().rstrip("\n").split(",")
            want = [i for i, h in enumerate(hdr) if re.search(r"Current|Torque", h, re.I)]
            dec = {hdr[i]: 0 for i in want}
            for _ in range(30):
                row = fh.readline().rstrip("\n").split(",")
                for i in want:
                    if i < len(row) and "." in row[i]:
                        dec[hdr[i]] = max(dec[hdr[i]], len(row[i].split(".")[1].strip('"')))
        return dec
    prec = {}
    for name in ("hash_ok", "hash_fail"):
        files = [f for f in g.index[g == name]][:3]
        prec[name] = {f: decimals(os.path.join(rawdir, by_digits[digits(f)])) for f in files if digits(f) in by_digits}
    out["decimalPrecisionFirst30Rows"] = prec
    out["python"] = sys.version.split()[0]
    json.dump(out, open(os.path.join(ROOT, "analyses", "M311_refit_provenance_diag.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps({k: (v if k != "perGroup" else {n: {"n_rows": d["n_rows"], "columnsDrifted": d["columnsDrifted"]} for n, d in v.items()})
                      for k, v in out.items() if k != "decimalPrecisionFirst30Rows"}, indent=1))


if __name__ == "__main__":
    main()
