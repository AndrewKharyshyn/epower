#!/usr/bin/env python3
"""F03-originals G1/G2 (read-only): rebuild from a staged dir (XT_RAW) and write the rebuilt master to OUT_CSV, plus per-group drift
vs the published master (groups: hash_fail = the originals-replaced drives, hash_ok, new>=20260923), raw-derived columns only
(same exclusions as refit_provenance_diag). Usage: XT_RAW=DIR python tools/f03_originals_groups.py OUT_JSON OUT_CSV FAILING_KEYS_JSON"""
import json, os, re, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
import master_refit_audit as M
ML16 = ['drive_cluster_k3','iso_outlier','iso_score','lof_score','f_iso','f_lof','f_mad','f_domain','ens_outlier','f_domain_2p','f_iso_i','f_lof_i','f_mad_i','ens_invalid','ens_extreme','ens_outlier_v2']
CORPUS = re.compile(r"(_corr|_applied|offset_|implied_offset|_adj_|cell_spread_loaded_p95_adj)")
dg = lambda s: re.sub(r"\D", "", str(s).rsplit(".", 1)[0])
def main():
    out_json, out_csv, keys = sys.argv[1:4]
    fail = set(json.load(open(keys)))
    pub = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False).set_index("file")
    if os.environ.get("XT_REB_CSV"):      # compare a previously saved rebuild without rebuilding
        reb = pd.read_csv(os.environ["XT_REB_CSV"], low_memory=False).set_index("file")
    else:
        reb = M.rebuild(2).set_index("file").loc[pub.index]
        reb.to_csv(out_csv)
    cols = [c for c in pub.columns if c in reb.columns and c not in ML16 and not CORPUS.search(c)]
    grp = {f: ("new" if dg(f) >= "20260923" else ("hash_fail" if (dg(f)[:8] + "_" + dg(f)[8:14] + ".csv") in fail else "hash_ok")) for f in pub.index}
    def drift(a, b):
        both = pd.concat([a, b], axis=1, keys=["p", "r"])
        na = both.p.isna() != both.r.isna()
        def num(x):
            return pd.to_numeric(x.astype(object).where(~x.astype(object).isin([True, False]), np.nan), errors="coerce")
        nn = num(both.p); rn = num(both.r)
        isnum = nn.notna() & rn.notna()
        d = pd.Series(False, index=both.index)
        d[isnum] = (nn[isnum] - rn[isnum]).abs() > 1e-9
        d[~isnum & ~na] = both.p[~isnum & ~na].astype(str) != both.r[~isnum & ~na].astype(str)
        return d | na
    res = {}
    for g in ("hash_fail", "hash_ok", "new"):
        idx = [f for f in pub.index if grp[f] == g]
        dr = {c: int(drift(pub.loc[idx, c], reb.loc[idx, c]).sum()) for c in cols}
        dr = {c: n for c, n in dr.items() if n}
        res[g] = dict(n_rows=len(idx), n_cols_compared=len(cols), columnsDrifted=len(dr), drift=dr)
    json.dump(res, open(out_json, "w"), indent=1, ensure_ascii=False)
    print({g: (v["n_rows"], v["columnsDrifted"]) for g, v in res.items()})


if __name__ == '__main__':
    main()
