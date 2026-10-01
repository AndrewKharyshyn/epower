#!/usr/bin/env python3
"""M318 runner (spec: analyses/M318_spec.md): M119-v2 corrected refit and its control / sensitivity runs, split in two stages so the
expensive raw pass is done once per population.
  python tools/m318_run.py tables --n-first 489 --out TABLES.pkl         # raw_only/ -> per-second at-risk tables (S, T)
  python tools/m318_run.py fit --tables TABLES.pkl --label R2 --boot-b 4000 --boot-seed 42 --out R2.json [--exclude-ens] [--rolling]
`--n-first N` takes the first N master rows (R1 control = 410, the HEAD block's population). Outputs JSON with provenance (master MD5, script sha256,
module sha256, boot settings) plus per-drive event counts for the blind-audit reconciliation. drive_master.csv is only read."""
import argparse, hashlib, json, os, pickle, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import pandas as pd
import m119v2_model as m

sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
RAW = os.path.join(ROOT, "raw_only")


def master(n_first=None):
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    return dm.iloc[:n_first].copy() if n_first else dm


def prov(a, extra=None):
    d = {"master_md5": md5, "script_sha256": sha(__file__), "m119v2_model_sha256": sha(os.path.join(ROOT, "m119v2_model.py")),
         "spec": "analyses/M318_spec.md", "bootB": m.BOOT_B, "bootSeed": m.BOOT_SEED, "raw_dir": "raw_only (tools/stage_raw.py)",
         "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    d.update(extra or {})
    return d


def cmd_tables(a):
    dm = master(a.n_first)
    def loader(fn):
        with open(os.path.join(RAW, fn), "rb") as f:
            return f.read()
    t = time.time()
    tabs = m._corpus_tables(dm, raw_loader=loader, raw_dir=RAW)
    pickle.dump({"tables": tabs, "files": list(dm["file"]), "prov": prov(a, {"n_first": a.n_first, "secs": round(time.time() - t)})},
                open(a.out, "wb"))
    S, T, cov = tabs[0], tabs[1], tabs[2]
    print(json.dumps({"covered": cov, "S_rows": len(S), "T_rows": len(T), "S_events": int(S["y"].sum()), "T_events": int(T["y"].sum()),
                      "S_days": int(S["day"].nunique()), "T_days": int(T["day"].nunique()), "secs": round(time.time() - t)}))


def cmd_fit(a):
    m.BOOT_B, m.BOOT_SEED = a.boot_b, a.boot_seed
    P = pickle.load(open(a.tables, "rb"))
    S, T, cov, srcs, diag = P["tables"]
    dm = master(len(P["files"]))
    note = None
    if a.exclude_ens:
        clean = ~dm["ens_outlier_v2"].fillna(False).astype(bool)
        keep = set(dm.loc[clean, "file"])
        S, T = S[S["file"].isin(keep)].reset_index(drop=True), T[T["file"].isin(keep)].reset_index(drop=True)
        dm = dm[clean].reset_index(drop=True)
        cov = int(dm.shape[0])
        note = "S3: ens_outlier_v2-clean drives only; diag totals are those of the full table (not recomputed)"
    per_drive = {"start": S.groupby("file")["y"].sum().astype(int).to_dict(), "stop": T.groupby("file")["y"].sum().astype(int).to_dict()}
    m._corpus_tables = lambda *_a, **_k: (S, T, cov, srcs, diag)     # reuse the cached raw pass; fits/bootstraps are unchanged
    t = time.time()
    v2 = m.build_m119v2(dm)
    out = {"label": a.label, "block": v2, "fit_secs": round(time.time() - t),
           "days": {"start_included": int(S["day"].nunique()), "stop_included": int(T["day"].nunique()),
                    "start_complete_case": int(S.dropna(subset=m.CORE5)["day"].nunique()),
                    "stop_complete_case": int(T.dropna(subset=m.CORE5)["day"].nunique()),
                    "master_dates": int(dm["date"].nunique()), "n_drives": int(len(dm))},
           "perDriveEvents": per_drive}
    if a.rolling:
        t = time.time()
        out["rollingOrigin"] = m.rolling_origin_validation(dm)
        out["rolling_secs"] = round(time.time() - t)
    out["provenance"] = prov(a, {"tables_prov": P["prov"], "note": note})
    json.dump(out, open(a.out, "w", encoding="utf-8"), default=str)
    print(json.dumps({"label": a.label, "nDrivesCovered": v2.get("nDrivesCovered"), "nDays": v2.get("nDays"), "fit_secs": out["fit_secs"]}))


def main():
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    t = sp.add_parser("tables"); t.add_argument("--n-first", type=int); t.add_argument("--out", required=True); t.set_defaults(f=cmd_tables)
    f = sp.add_parser("fit"); f.add_argument("--tables", required=True); f.add_argument("--label", required=True)
    f.add_argument("--boot-b", type=int, default=4000); f.add_argument("--boot-seed", type=int, default=42)
    f.add_argument("--out", required=True); f.add_argument("--exclude-ens", action="store_true"); f.add_argument("--rolling", action="store_true")
    f.set_defaults(f=cmd_fit)
    a = ap.parse_args(); a.f(a)


if __name__ == "__main__":
    main()
