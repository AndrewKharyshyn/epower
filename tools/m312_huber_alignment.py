#!/usr/bin/env python3
"""M312 additive splice (spec: analyses/M312_spec.md rev 2, section 3). Recomputes ONLY `cell_spread_loaded_p95_adj_hub_mv` on the frozen
master with the single-source function compute_drive_summary_v6.m19b_huber_adjust (canonical keep set ~ens_outlier_v2) and splices that one
column into drive_master.csv at byte level (csv module, no pandas round trip), atomically. drive_master.csv is written by this pipeline tool only.

Hard aborts (nothing written): pre-run MD5 != --expect-md5; CSV round trip of the untouched file is not byte-identical; any other column's
raw text changes; ML16 columns change; a float formatted for a row whose value did not change differs from the stored string.
--verify-pipeline: also runs postprocess_master on the frozen master, restores ML16, applies m19b, and requires the column to equal the spliced one
byte-exact and recomputed ens_outlier_v2 to equal the frozen one (0 diffs).
Usage: python tools/m312_huber_alignment.py [--write] [--verify-pipeline] [--expect-md5 MD5]   (dry run without --write)"""
import argparse, csv, hashlib, io, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
import compute_drive_summary_v6 as v6

COL = "cell_spread_loaded_p95_adj_hub_mv"
ML16 = ['drive_cluster_k3', 'iso_outlier', 'iso_score', 'lof_score', 'f_iso', 'f_lof', 'f_mad', 'f_domain', 'ens_outlier',
        'f_domain_2p', 'f_iso_i', 'f_lof_i', 'f_mad_i', 'ens_invalid', 'ens_extreme', 'ens_outlier_v2']
md5b = lambda b: hashlib.md5(b).hexdigest()
fmt = lambda x: "" if pd.isna(x) else repr(float(x))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--verify-pipeline", action="store_true")
    ap.add_argument("--expect-md5", default="5197ab6dc2a44b99ccb246af03f8f6b0")
    a = ap.parse_args()
    raw = open("drive_master.csv", "rb").read()
    if md5b(raw) != a.expect_md5:
        sys.exit(f"ABORT: drive_master MD5 {md5b(raw)} != expected {a.expect_md5}")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8"), newline="")))
    hdr = rows[0]
    j = hdr.index(COL)
    buf = io.StringIO(newline="")
    csv.writer(buf, lineterminator="\n").writerows(rows)
    if buf.getvalue().encode("utf-8") != raw:
        sys.exit("ABORT: csv round trip of the untouched master is not byte-identical")
    df = pd.read_csv("drive_master.csv", low_memory=False)
    assert len(df) == len(rows) - 1
    new_df, info = v6.m19b_huber_adjust(df)
    if "error" in info:
        sys.exit("ABORT: m19b failed: " + info["error"])
    new_vals = [fmt(v) for v in new_df[COL]]
    old_vals = [r[j] for r in rows[1:]]
    # formatting sanity: where the float is unchanged the string must be identical
    bad_fmt = 0
    for o, n in zip(old_vals, new_vals):
        if o != "" and n != "" and float(o) == float(n) and o != n:
            bad_fmt += 1
    if bad_fmt:
        sys.exit(f"ABORT: {bad_fmt} unchanged floats format differently from the stored strings")
    out_rows = [hdr] + [r[:j] + [nv] + r[j + 1:] for r, nv in zip(rows[1:], new_vals)]
    # per-column raw-text hashes of all other columns must be unchanged
    col_hash = lambda rs, k: md5b("\x1f".join(r[k] for r in rs).encode("utf-8"))
    changed_cols = [h for k, h in enumerate(hdr) if k != j and col_hash(rows, k) != col_hash(out_rows, k)]
    if changed_cols:
        sys.exit("ABORT: other columns changed: " + str(changed_cols))
    ml_changed = [c for c in ML16 if c in hdr and col_hash(rows, hdr.index(c)) != col_hash(out_rows, hdr.index(c))]
    assert not ml_changed
    nchg = sum(1 for o, n in zip(old_vals, new_vals) if o != n)
    nnan_new = sum(1 for n in new_vals if n == "")
    res = {"script_sha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "md5_before": md5b(raw), "rows": len(df),
           "n_days": int(pd.to_datetime(df["date"]).dt.date.nunique()), "target_column": COL, "rows_changed_text": nchg,
           "rows_old_nonnull": sum(1 for o in old_vals if o != ""), "rows_new_nonnull": len(new_vals) - nnan_new,
           "other_columns_changed": 0, "ml16_diffs": "0/16", "m19b_trend": {k: v for k, v in info.items()}}
    if a.verify_pipeline:
        out = v6.postprocess_master(df.copy(), verbose=False)
        pm = out[0] if isinstance(out, tuple) else out
        v2_diff = int((pm["ens_outlier_v2"].astype(bool).values != df["ens_outlier_v2"].astype(bool).values).sum())
        for c in ML16:
            if c in pm.columns and c in df.columns:
                pm[c] = df[c].values
        pm, _ = v6.m19b_huber_adjust(pm)
        pipe_vals = [fmt(v) for v in pm[COL]]
        res["verify_pipeline"] = {"ens_outlier_v2_recomputed_vs_frozen_diffs": v2_diff,
                                  "column_diffs_vs_spliced": int(sum(1 for x, y in zip(pipe_vals, new_vals) if x != y))}
        if v2_diff or res["verify_pipeline"]["column_diffs_vs_spliced"]:
            print(json.dumps(res, indent=1))
            sys.exit("ABORT: pipeline path does not reproduce the spliced column / frozen v2")
    if a.write:
        b2 = io.StringIO(newline="")
        csv.writer(b2, lineterminator="\n").writerows(out_rows)
        data = b2.getvalue().encode("utf-8")
        tmp = "drive_master.csv.tmp"
        open(tmp, "wb").write(data)
        os.replace(tmp, "drive_master.csv")
        res["md5_after"] = md5b(data)
        json.dump(res, open("analyses/M312_splice.json", "w", encoding="utf-8"), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "m19b_trend"}, indent=1))


if __name__ == "__main__":
    main()
