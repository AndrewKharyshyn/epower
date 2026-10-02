#!/usr/bin/env python3
"""M337 (F03, owner-approved read-only check): compare the FUEL columns of the raw/ copies of the hash-failing canonical files against the
sha256-verified originals in ../../originals_recovered (outside the repo). Reads only; copies nothing into raw/; no re-anchoring.
For every such file that carries a fuel column: row-count equality, cell-level equality and max absolute difference per fuel column, and the per-trip
counter delta V_cnt and rate integral V_int (time-weighted, per-sample dt capped at recon_engine.DT_CAP) computed from each copy.
Writes analyses/M337_f03_fuel_check.json. Usage: python tools/f03_fuel_columns_check.py"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import numpy as np, pandas as pd
import recon_engine as RE

ORIG = os.path.abspath(os.path.join(ROOT, "..", "..", "originals_recovered"))
RAW = os.path.join(ROOT, "raw")
COLS = {"counter": RE.CH["used"], "rate": RE.CH["flow"], "lifetime": "Використане паливо(загальний) (L)"}


def key_of(n):
    d = "".join(ch for ch in n if ch.isdigit())
    return d[:8] + "_" + d[8:14] + ".csv" if len(d) >= 14 else None


def totals(df):
    t = pd.to_datetime(df["time"], errors="coerce")
    out = {}
    c = pd.to_numeric(df[COLS["counter"]], errors="coerce") if COLS["counter"] in df.columns else None
    r = pd.to_numeric(df[COLS["rate"]], errors="coerce") if COLS["rate"] in df.columns else None
    if c is not None and c.notna().sum() >= 2:
        i0, i1 = c.first_valid_index(), c.last_valid_index()
        out["V_cnt"] = float(c.loc[i1] - c.loc[i0])
        if r is not None and r.notna().sum() >= 2:
            # integrate on the rate series' OWN valid sample times (the pipeline's _ser drops NaN rows), window = counter first..last valid time
            tt, rr = t[r.notna()], r[r.notna()]
            dt = tt.diff().dt.total_seconds().clip(upper=RE.DT_CAP).fillna(0.0)
            m = (tt >= t.loc[i0]) & (tt <= t.loc[i1])
            out["V_int"] = float((rr / 3600.0 * dt)[m].sum())
    return out


def main():
    man = json.load(open(os.path.join(ROOT, "originals_manifest.json"), encoding="utf-8"))["records"]
    names = {key_of(n): n for n in os.listdir(RAW) if key_of(n)}
    onames = {key_of(n): n for n in os.listdir(ORIG) if key_of(n)} if os.path.isdir(ORIG) else {}
    rows, skipped = [], {"no_orig": 0, "no_raw": 0, "no_fuel_col": 0}
    for rec in man:
        k = rec["record_id"]
        if k not in onames: skipped["no_orig"] += 1; continue
        if k not in names: skipped["no_raw"] += 1; continue
        a = pd.read_csv(os.path.join(RAW, names[k]), low_memory=False)
        b = pd.read_csv(os.path.join(ORIG, onames[k]), low_memory=False)
        if not any(c in a.columns or c in b.columns for c in COLS.values()): skipped["no_fuel_col"] += 1; continue
        row = {"id": k, "rows_raw": int(len(a)), "rows_orig": int(len(b)), "rows_equal": len(a) == len(b)}
        for nm, c in COLS.items():
            row[nm + "_col_in_raw"] = c in a.columns
            row[nm + "_col_in_orig"] = c in b.columns
            if c in a.columns and c in b.columns and len(a) == len(b):
                x = pd.to_numeric(a[c], errors="coerce").values
                y = pd.to_numeric(b[c], errors="coerce").values
                both = np.isfinite(x) & np.isfinite(y)
                row[nm + "_cells_equal_share"] = float(np.mean(x[both] == y[both])) if both.any() else None
                row[nm + "_max_abs_diff"] = float(np.max(np.abs(x[both] - y[both]))) if both.any() else None
                row[nm + "_nan_mismatch"] = int(np.sum(np.isfinite(x) != np.isfinite(y)))
        ta, tb = totals(a), totals(b)
        for q in ("V_cnt", "V_int"):
            row[q + "_raw"], row[q + "_orig"] = ta.get(q), tb.get(q)
        rows.append(row)
    d = pd.DataFrame(rows)
    res = {"milestone": "M337", "check": "F03 fuel columns raw/ vs sha256-verified originals (read-only)", "originalsDir": "../../originals_recovered (outside repo)",
           "nManifestRecords": len(man), "nWithFuelColumns": int(len(d)), "skipped": skipped}
    if len(d):
        eq = lambda c: d[c].dropna() if c in d.columns else pd.Series(dtype=float)
        for nm in COLS:
            cs, md = eq(nm + "_cells_equal_share"), eq(nm + "_max_abs_diff")
            res[nm] = {"nFilesCompared": int(len(cs)), "filesAllCellsEqual": int((cs == 1.0).sum()), "minCellsEqualShare": float(cs.min()) if len(cs) else None,
                       "maxAbsDiffOverFiles": float(md.max()) if len(md) else None}
        dv = d.dropna(subset=["V_cnt_raw", "V_cnt_orig"])
        res["V_cnt"] = {"n": int(len(dv)), "sumRaw": float(dv.V_cnt_raw.sum()), "sumOrig": float(dv.V_cnt_orig.sum()),
                        "aggRelDiff": float((dv.V_cnt_raw.sum() - dv.V_cnt_orig.sum()) / dv.V_cnt_orig.sum()) if dv.V_cnt_orig.sum() else None,
                        "maxAbsTripDiffL": float((dv.V_cnt_raw - dv.V_cnt_orig).abs().max()) if len(dv) else None}
        di = d.dropna(subset=["V_int_raw", "V_int_orig"])
        res["V_int"] = {"n": int(len(di)), "sumRaw": float(di.V_int_raw.sum()), "sumOrig": float(di.V_int_orig.sum()),
                        "aggRelDiff": float((di.V_int_raw.sum() - di.V_int_orig.sum()) / di.V_int_orig.sum()) if di.V_int_orig.sum() else None,
                        "maxAbsTripDiffL": float((di.V_int_raw - di.V_int_orig).abs().max()) if len(di) else None}
        res["rowsEqualAll"] = bool(d.rows_equal.all())
    with open(os.path.join(ROOT, "analyses", "M337_f03_fuel_check.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
