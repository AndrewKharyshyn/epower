#!/usr/bin/env python3
"""gtrClosure refresh as an ingestion stage (M377c, analyses/M377c_spec.md Rev 2; closes the carry-forward of M377b).
Steps: (1) run tools/gtr_closure_diag.py --ingest and tools/gtr_interval_sens.py --ingest (expected-set rule against the previous per-drive file pinned in
analyses/gtr_closure_record.json; previous-ID per-drive identity; raw originals sha256; ens flag equality; a failed check exits non-zero = STOP);
(2) build the block from analyses/M377c_* (tools/gtr_closure_block.py --m377c); (3) diff against the carried block under the ingestion rules; (4) splice.
STOP (exit 3, nothing spliced, Director): key-set change; any bool / verdict flip; an estimate outside its previous 95 % CI; a type change (e.g. a stratum crossing the n >= 10
threshold); a list-length change outside the documentation lists under /scope/; an escalation-band breach (point-only leaf moving by more than 10 % relative, 0.01 absolute when
|previous| < 0.1; n_days changing by more than 20 %); a deep-diff outside the allow-list. Moves of point-only leaves inside the band are REPORTED (analyses/gtr_closure_delta.json).
Splice allow-list: generatorTractionRecon.gtrClosure and generatorTractionRecon.staleBlocks (gtrClosure removed; crossval stays).
Usage: python tools/gtr_closure_refresh.py [--dry-run] [--no-record] [--skip-producers]"""
import argparse, copy, hashlib, json, os, shutil, subprocess, sys
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
REL_BAND, ABS_BAND, ABS_SWITCH, NDAYS_BAND = 0.10, 0.01, 0.1, 0.20
ALLOW = ["/generatorTractionRecon/gtrClosure", "/generatorTractionRecon/staleBlocks"]
DOC_LISTS = ("/scope/excludedNoBatteryInputs", "/scope/excludedWithoutPublishedRow", "/scope/publishedRowsWithFgenOne")
UNITS = {"fractions": "0-1 unless the leaf name ends in Pct", "per100km": "kWh per 100 km", "scope": "counts, days, km"}
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)


import re
COUNT_OF_DRIVES = re.compile(r"^n[A-Za-z]*Drives[A-Za-z]*$")       # Rev 3: integer count-of-drives leaves are compared as shares of the set size


def diff_blocks(old, new):
    """Pure: returns the delta dict with stops (STOP rules) and escalations (band breaches); point-only moves inside the band are reported."""
    n_old, n_new = old.get("scope", {}).get("nDrives"), new.get("scope", {}).get("nDrives")
    out = {"keyDiffs": [], "ciChecks": [], "pointOnly": [], "boolFlips": [], "typeChanges": [], "listChanges": [], "scopeChanges": [], "stringChanges": [], "stops": [], "escalations": [], "units": UNITS}

    def ci_check(path, oe, oci, ne, nci):
        inside = bool(oci[0] <= ne <= oci[1])
        w_o, w_n = oci[1] - oci[0], nci[1] - nci[0]
        out["ciChecks"].append({"path": path, "prev": [oe, oci], "new": [ne, nci], "newEstInsidePrevCI": inside, "ciWidthRatio": round(w_n / w_o, 4) if w_o else None})
        if not inside:
            out["stops"].append({"rule": "estimate outside previous 95% CI", "path": path})

    def walk(path, o, n):
        if isinstance(o, dict) and isinstance(n, dict):
            for k in sorted(set(o) | set(n)):
                if k not in o or k not in n:
                    out["keyDiffs"].append(f"{path}/{k}")
                    out["stops"].append({"rule": "key-set difference", "path": f"{path}/{k}"})
            if "est" in o and "ci95" in o and "est" in n and "ci95" in n:
                ci_check(path, o["est"], o["ci95"], n["est"], n["ci95"])
                skip = ("est", "ci95")
            elif "relToGenerator" in o and "ci95" in o and "relToGenerator" in n and "ci95" in n:
                ci_check(path, o["relToGenerator"], o["ci95"], n["relToGenerator"], n["ci95"])
                skip = ("relToGenerator", "ci95")
            else:
                skip = ()
            for k in sorted(set(o) & set(n)):
                if k not in skip:
                    walk(f"{path}/{k}", o[k], n[k])
        elif isinstance(o, list) and isinstance(n, list):
            if len(o) != len(n):
                rec = {"path": path, "prevLen": len(o), "newLen": len(n)}
                out["listChanges"].append(rec)
                if path not in DOC_LISTS:
                    out["stops"].append({"rule": "list length changed", "path": path})
                return
            for i, (x, y) in enumerate(zip(o, n)):
                walk(f"{path}[{i}]", x, y)
        elif isinstance(o, bool) or isinstance(n, bool):
            if o != n:
                out["boolFlips"].append({"path": path, "prev": o, "new": n})
                out["stops"].append({"rule": "flag/verdict flip", "path": path})
        elif type(o) is not type(n) and not (num(o) and num(n)):
            out["typeChanges"].append({"path": path, "prev": str(o)[:60], "new": str(n)[:60]})
            out["stops"].append({"rule": "type change (stratum evaluation status / null state)", "path": path})
        elif num(o) and num(n):
            if path.startswith("/scope/"):
                if o != n:
                    out["scopeChanges"].append({"path": path, "prev": o, "new": n})
                    if path == "/scope/nDays" and o and abs(n - o) / o > NDAYS_BAND:
                        out["escalations"].append({"rule": "n_days changed by more than 20%", "path": path, "prev": o, "new": n})
                return
            if isinstance(o, int) and isinstance(n, int) and COUNT_OF_DRIVES.match(path.rsplit("/", 1)[-1]) and n_old and n_new:
                so, sn = o / n_old, n / n_new                         # Rev 3: share of the set size under the unchanged band
                d = abs(sn - so)
                tol = ABS_BAND if abs(so) < ABS_SWITCH else REL_BAND * abs(so)
                out["pointOnly"].append({"path": path, "prev": o, "new": n, "comparedAs": "share of set size", "prevShare": round(so, 4), "newShare": round(sn, 4), "absDiff": round(d, 6), "relDiff": round(d / abs(so), 5) if so else None, "withinBand": bool(d <= tol)})
                if d > tol:
                    out["escalations"].append({"rule": "count leaf (share of set size) beyond the escalation band", "path": path})
                return
            d = abs(n - o)
            tol = ABS_BAND if abs(o) < ABS_SWITCH else REL_BAND * abs(o)
            out["pointOnly"].append({"path": path, "prev": o, "new": n, "absDiff": round(d, 6), "relDiff": round(d / abs(o), 5) if o else None, "withinBand": bool(d <= tol)})
            if d > tol:
                out["escalations"].append({"rule": "point-only leaf beyond the escalation band (10% relative, 0.01 absolute when |previous| < 0.1)", "path": path})
        elif o != n:
            out["stringChanges"].append({"path": path})

    walk("", old, new)
    out["summary"] = {"nCiChecked": len(out["ciChecks"]), "nInsidePreviousCI": sum(r["newEstInsidePrevCI"] for r in out["ciChecks"]), "nPointOnly": len(out["pointOnly"]),
                      "nPointOnlyWithinBand": sum(r["withinBand"] for r in out["pointOnly"]), "nStops": len(out["stops"]), "nEscalations": len(out["escalations"]),
                      "nStringChanges": len(out["stringChanges"])}
    return out


def splice_plan(A, blk):
    """Pure: the new arrays (gtrClosure replaced, gtrClosure removed from staleBlocks) or a list of problems."""
    new = copy.deepcopy(A)
    G = new["generatorTractionRecon"]
    G["gtrClosure"] = blk
    sb = G["staleBlocks"]
    sb["blocks"] = [b for b in sb["blocks"] if b != "gtrClosure"]
    sb["perBlock"] = [p for p in sb["perBlock"] if p["block"] != "gtrClosure"]
    assert [p["block"] for p in sb["perBlock"]] == sb["blocks"], "staleBlocks perBlock / blocks mismatch"
    return new


def walk_paths(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            yield from walk_paths(a.get(k), b.get(k), f"{path}/{k}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            yield from walk_paths(x, y, f"{path}[{i}]")
    elif a != b:
        yield path


def allow_check(A, new):
    return [p for p in walk_paths(A, new) if not any(p == a or p.startswith(a + "/") or p.startswith(a + "[") for a in ALLOW)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-record", action="store_true", help="do not move the previous-per-drive pin (controls)")
    ap.add_argument("--skip-producers", action="store_true", help="use the existing analyses/M377c_* files (tests / re-splice)")
    a = ap.parse_args()
    import m372_closure_common as CM
    if not a.skip_producers:
        for tool in ("tools/gtr_closure_diag.py", "tools/gtr_interval_sens.py"):
            rc = subprocess.run([sys.executable, tool, "--ingest"], cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1")).returncode
            if rc != 0:
                sys.exit(rc)
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    old = A["generatorTractionRecon"]["gtrClosure"]
    sys.argv = [sys.argv[0], "--m377c"]
    import gtr_closure_block as GB
    blk = GB.build()
    old_cmp = copy.deepcopy(old)
    old_cmp["scope"].pop("carriedAtIngestion", None)            # the M377b disclosure leaf is removed by this refresh
    delta = diff_blocks(old_cmp, blk)
    diag = json.load(open("analyses/M377c_closure_diag.json", encoding="utf-8"))
    delta["set"] = diag["m372"]["checks"]["expectedSet"]
    delta["checks"] = {k: v for k, v in diag["m372"]["checks"].items() if k != "expectedSet"}
    spec_sha = __import__("m377_pin").spec_sha("analyses/M377c_spec.md")
    delta["specSha256Frozen"] = spec_sha
    step2 = json.load(open("analyses/M377c_step2_result.json", encoding="utf-8"))
    ids = (step2.get("variants", {}).get("baseline", {}) or {}).get("infeasible_alpha_files")
    if ids is not None:
        prev_ids = set(pd.read_csv(os.path.join(ROOT, CM.load_record()["previousPerDrive"]["path"]))["file"])
        delta["infeasibleAlphaDrives"] = {"n": len(ids), "inPreviousSet": [x for x in ids if x in prev_ids], "inNewDrives": [x for x in ids if x not in prev_ids]}
    new = splice_plan(A, blk)
    bad = allow_check(A, new)
    if bad:
        delta["stops"].append({"rule": "deep-diff outside the allow-list", "path": bad[:5]})
    with open("analyses/gtr_closure_delta.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(delta, indent=1, ensure_ascii=False) + "\n")
    problems = [f"{s['rule']} @ {s['path']}" for s in delta["stops"]] + [f"ESCALATION {e['rule']} @ {e['path']}" for e in delta["escalations"]]
    if problems:
        print("STOP (Director): " + "; ".join(problems[:8]), file=sys.stderr)
        sys.exit(3)
    if a.dry_run:
        print("dry run ok;", len(list(walk_paths(A, new))), "changed leaves;", delta["summary"])
        return
    with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(new, ensure_ascii=False, indent=1))
    if not a.no_record:                                          # the new per-drive file becomes the pinned previous set of the next ingestion
        n = diag["n_drives"]
        dest = f"analyses/closure_baselines/perdrive_{n}drives.csv"
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile("analyses/M377c_closure_perdrive.csv", dest)
        rec = {"previousPerDrive": {"path": dest, "sha256": sha(dest), "nDrives": n, "master": __import__("hashlib").md5(open("drive_master.csv", "rb").read()).hexdigest()}, "specSha256Frozen": spec_sha}
        with open("analyses/gtr_closure_record.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec, indent=1) + "\n")
    print("spliced gtrClosure;", delta["summary"])


if __name__ == "__main__":
    main()
