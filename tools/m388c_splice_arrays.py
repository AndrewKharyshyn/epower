#!/usr/bin/env python3
"""M388c (spec analyses/M388c_spec.md, Director plan step 4): arrays-only additive splice after the one-row master resplice (tools/m388c_resplice_drive.py).
Recomputes with the patched code, from the live master and the raw staging dir, exactly the two raw-SoC rainflow keys of summary_arrays.json
(rfDodHistogram via _rf_dod_histogram; kLadderScenarios via _k_ladder_scenarios with fadeModes / seasonalLife / kExponentLadder read from the current payload, as
build_summary_arrays does) and the determinism block (master MD5 changed: tools/ingest_core.step3_determinism -> summary_arrays.json determinism and
summary_config.json auditMetadata.determinism). Deep-diff: only those three payload paths may change.
Modes: --check (writes analyses/M388c_arrays_check.json, no write) | --splice (check + write). Never writes drive_master.csv or raw files.
Usage: python tools/m388c_splice_arrays.py --check|--splice"""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd
import compute_summary_arrays as C
import drive_raw_cache as drc
import ingest_core as IC

OUT = os.path.join(ROOT, "analyses", "M388c_arrays_check.json")
ALLOW = ("rfDodHistogram", "kLadderScenarios", "determinism")
LF = chr(10)
canon = lambda o: json.dumps(o, sort_keys=True, ensure_ascii=False, default=float)


def paths(a, b, p=""):
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            out += paths(a.get(k), b.get(k), f"{p}/{k}") if (k in a and k in b) else [f"{p}/{k}"]
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += paths(x, y, f"{p}/{i}")
        return out
    return [] if canon(a) == canon(b) else [p]


def main():
    write = "--splice" in sys.argv
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    cfg = json.load(open("summary_config.json", encoding="utf-8"))
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    stage = os.path.join(ROOT, "raw_only")

    def loader(fn):
        with open(os.path.join(stage, fn), "rb") as f:
            return f.read()
    fl = drc.make_frame_loader(raw_dir=stage)
    new = copy.deepcopy(A)
    new["rfDodHistogram"] = C._rf_dod_histogram(dm, loader, fl)
    new["kLadderScenarios"] = C._k_ladder_scenarios(dm, loader, fl, (A.get("fadeModes") or {}).get("capacity"),
                                                    (A.get("seasonalLife") or {}).get("calendarLifeYrShaded"), cfg.get("kExponentLadder"))
    block, _ = IC.step3_determinism(os.path.join(ROOT, "drive_master.csv"))
    new["determinism"] = block
    ch = paths(A, new)
    bad = [p for p in ch if p.split("/")[1] not in ALLOW]
    res = {"milestone": "M388c", "mode": "--splice" if write else "--check", "changedPathCount": len(ch), "changedTop": sorted({p.split("/")[1] for p in ch}),
           "outsideAllowList": bad[:10], "ok": not bad,
           "rfDodHistogramBefore": {k: A["rfDodHistogram"].get(k) for k in ("nCyclesTotal", "nFilesUsed", "le1PctShare", "le2PctShare", "maxDodPct")},
           "rfDodHistogramAfter": {k: new["rfDodHistogram"].get(k) for k in ("nCyclesTotal", "nFilesUsed", "le1PctShare", "le2PctShare", "maxDodPct")}}
    if write and not bad:
        cfg2 = copy.deepcopy(cfg)
        cfg2.setdefault("auditMetadata", {})["determinism"] = block
        for path, obj in (("summary_arrays.json", new), ("summary_config.json", cfg2)):      # LF, no trailing newline: byte-identical round trip (checked)
            IC._atomic(os.path.join(ROOT, path), lambda tt, obj=obj: open(tt, "w", encoding="utf-8", newline=LF).write(json.dumps(obj, ensure_ascii=False, indent=1)))
    json.dump(res, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1, default=float)
    print(json.dumps(res, default=float), flush=True)
    sys.exit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
