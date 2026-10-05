#!/usr/bin/env python3
"""Stamp notes generated from the payload (M382, audit F07): the generatorTractionRecon stamp note used to be typed per ingestion and
described a carried gtrClosure at 257 drives after the closure had been refreshed (292 drives). Every number and block status below is
READ from the payload blocks; nothing is typed.
Usage: python tools/stamp_notes.py --milestone M382 [--dry-run]   (sets _artifactStamps.generatorTractionRecon.computationStatusNote)"""
import argparse, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def gtr_stamp_note(A, milestone):
    g = A["generatorTractionRecon"]
    sc = g["gtrClosure"]["scope"]
    carried = sc.get("carriedAtIngestion")
    refreshed = g.get("refreshedBlocks") or []
    stale = (g.get("staleBlocks") or {}).get("perBlock") or []
    total = A.get("meta", {}).get("totalDrives") or sc.get("nCanonical")
    done = ["headline and cohort splits (refresh_gtr_headline: %s drives)" % g["nDrives"]]
    done += ["%s (%s, %s drives, %s days)" % (b["block"], b.get("rerunMilestone") or b.get("basisMilestone"), b.get("nDrives"), b.get("nDays")) for b in refreshed]
    done.append("eligibilityAlignment current counts")
    if carried:
        clos = "gtrClosure numbers carried at the %s set (%s drives; scope.carriedAtIngestion)" % (carried.get("milestone"), carried.get("basisNDrives"))
    else:
        clos = "gtrClosure recomputed on the live corpus (%s drives, %s days)" % (sc["nDrives"], sc["nDays"])
    st = "; ".join("%s carried at %s (%s)" % (p["block"], p.get("basisMilestone"), p.get("basisDate") or "basis date not recorded") for p in stale)
    return "%s: generated from the payload. Recomputed on the %s-drive corpus: %s; %s; %s." % (
        milestone, total, "; ".join(done), clos, st or "no carried blocks")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--milestone", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    p = os.path.join(ROOT, "summary_arrays.json")
    A = json.load(open(p, encoding="utf-8"))
    note = gtr_stamp_note(A, a.milestone)
    print(note)
    if not a.dry_run:
        A["_artifactStamps"]["generatorTractionRecon"]["computationStatusNote"] = note
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(A, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
