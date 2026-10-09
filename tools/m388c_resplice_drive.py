#!/usr/bin/env python3
"""M388c (spec analyses/M388c_spec.md, Director option (b)): re-derive the master row of the ONE drive that carried a single-sample SoC logger glitch
with the patched per-drive code, through the same primitives as tools/ingest_core.step1_master (analyze_bytes -> postprocess_master -> ML16 restore ->
m19b_huber_adjust), with the glitch row removed from the 'pre-existing' set. Gates (STOP on any failure, nothing written):
  G1 every row except the glitch row is text-identical to the current drive_master.csv (0 pre-existing-row diffs; includes the 29 other new drives and the ML16 columns);
  G2 the glitch row differs only in SoC-derived columns (^soc_|^rf_|^vsag_soc, vreg_R_pack_mohm whose regression uses SoC as a regressor); any other changed column escalates;
  G3 soc_start / soc_end unchanged.
Modes: --check (writes analyses/M388c_resplice_check.json, no master write) | --write (check + atomic master write; MD5 before/after recorded).
Never writes raw files. Usage: python tools/m388c_resplice_drive.py --check|--write"""
import hashlib, json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd
import ingest_core as IC
import compute_drive_summary_v6 as v6

FILE_RAW = "2026-10-08 10-14-58.csv"
KEY = IC.master_key(FILE_RAW)
OUT = os.path.join(ROOT, "analyses", "M388c_resplice_check.json")
SOC_COL = re.compile(r"^(soc_|rf_|vsag_soc|vreg_R_pack_mohm$)")   # vreg_R_pack_mohm: Huber V ~ soc + Id, SoC is a regressor (found by the first --check; disclosed)


def main():
    write = "--write" in sys.argv
    cur_path = os.path.join(ROOT, "drive_master.csv")
    dm_cur = pd.read_csv(cur_path, low_memory=False)
    assert KEY in set(dm_cur["file"]), KEY
    dm_old = dm_cur[dm_cur["file"] != KEY].reset_index(drop=True)
    p = os.path.join(os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"), FILE_RAW)
    r = v6.analyze_bytes(open(p, "rb").read(), KEY)
    d, tm = v6._date_from_name(p)
    r.setdefault("date", d); r.setdefault("time_start", r.get("time_start") or tm)
    merged = pd.concat([dm_old, pd.DataFrame([r])], ignore_index=True, sort=False)
    merged = merged.sort_values(["date", "time_start"], kind="stable").reset_index(drop=True)
    out = v6.postprocess_master(merged, verbose=False)
    dm_new = out[0] if isinstance(out, tuple) else out
    old = dm_old.set_index("file")
    is_old = dm_new["file"].isin(old.index)
    for c in IC.ML16:
        if c in dm_new.columns and c in old.columns:
            dm_new.loc[is_old, c] = old[c].reindex(dm_new.loc[is_old, "file"]).values
    dm_new, _ = v6.m19b_huber_adjust(dm_new)
    tmp = os.path.join(ROOT, "runs", "_m388c_tmp_master.csv")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    dm_new.to_csv(tmp, index=False)
    chk = pd.read_csv(tmp, low_memory=False, dtype=str, keep_default_na=False)
    ref = pd.read_csv(cur_path, low_memory=False, dtype=str, keep_default_na=False)
    res = {"milestone": "M388c", "mode": "--write" if write else "--check", "file": KEY, "rowsCurrent": len(ref), "rowsNew": len(chk),
           "md5Before": hashlib.md5(open(cur_path, "rb").read()).hexdigest()}
    cols_ok = list(ref.columns) == list(chk.columns)
    a = ref.set_index("file"); b = chk.set_index("file").loc[a.index]
    others = [f for f in a.index if f != KEY]
    other_diffs = {c: int((a.loc[others, c] != b.loc[others, c]).sum()) for c in a.columns if (a.loc[others, c] != b.loc[others, c]).any()}
    row_cols = [c for c in a.columns if a.loc[KEY, c] != b.loc[KEY, c]]
    res.update(columnsIdentical=cols_ok, otherRowDiffs=other_diffs, glitchRowChangedColumns=row_cols,
               glitchRowBeforeAfter={c: [a.loc[KEY, c], b.loc[KEY, c]] for c in row_cols},
               nonSocChanged=[c for c in row_cols if not SOC_COL.match(c)],
               socStartEndUnchanged=bool(a.loc[KEY, "soc_start"] == b.loc[KEY, "soc_start"] and a.loc[KEY, "soc_end"] == b.loc[KEY, "soc_end"]))
    ok = cols_ok and not other_diffs and not res["nonSocChanged"] and res["socStartEndUnchanged"] and len(chk) == len(ref)
    res["ok"] = bool(ok)
    if write and ok:
        IC._atomic(cur_path, lambda t: dm_new.to_csv(t, index=False))
        res["md5After"] = hashlib.md5(open(cur_path, "rb").read()).hexdigest()
    os.remove(tmp)
    json.dump(res, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1, default=str)
    print(json.dumps({k: res[k] for k in res if k != "glitchRowBeforeAfter"}, default=str), flush=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
