#!/usr/bin/env python3
"""Write ONE acknowledgement record for the current M321 `warn-newspec` warning set into analyses/M321_acknowledgements.json.
A deliberate manual step AFTER the Director's decision (never run from ingestion, never by the monitor): see analyses/TEMPLATE_ladder_warning_spec.md.
The record carries the warningSetHash, a `ref` that must name an existing CHANGELOG '## M###' heading or an existing analyses/ spec file, and the current basis
identity (selectionCodeSha256 + basisNDrives), exactly what release_check's gate (m321_ladder_monitor.ack_valid) requires.
Usage: python tools/m321_acknowledge.py --ref "M322 <title or spec id>" --note "<one line>" [--dry-run]"""
import argparse, datetime, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import m321_ladder_monitor as M

ACKS = os.path.join(ROOT, "analyses", "M321_acknowledgements.json")


def make_record(mon, ref, note="", root=ROOT, today=None):
    """Pure: the acknowledgement record for monitor block `mon`, or ValueError with the reason it must not be written."""
    if mon.get("status") != "warn-newspec":
        raise ValueError(f"nothing to acknowledge: monitor status is {mon.get('status')!r} (only warn-newspec needs an acknowledgement)")
    if not M.ref_resolves(ref, root):
        raise ValueError(f"ref {ref!r} does not resolve: it must name an existing CHANGELOG '## M###' heading (e.g. 'M322 title') or an existing analyses/ spec file; "
                         f"write the CHANGELOG entry or spec first")
    rec = {"warningSetHash": mon["warningSetHash"], "ref": ref, "date": today or datetime.date.today().isoformat(),
           "selectionCodeSha256": mon["selectionCodeSha256"], "basisNDrives": mon["basisNDrives"], "warningCodes": mon.get("warningCodes", []), "note": note}
    if not M.ack_valid(rec, mon, root):
        raise ValueError("internal: the record would not satisfy the gate")
    return rec


def append_record(rec, path=ACKS):
    acks = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []
    if any(a.get("warningSetHash") == rec["warningSetHash"] and a.get("selectionCodeSha256") == rec["selectionCodeSha256"]
           and a.get("basisNDrives") == rec["basisNDrives"] for a in acks):
        return False                                   # idempotent: this warning set on this basis is already acknowledged
    acks.append(rec)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(acks, indent=1, ensure_ascii=False) + "\n")
    return True


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ref", required=True); ap.add_argument("--note", default=""); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    A = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
    mon = (A.get("socHysteresisV2") or {}).get("tempLadderMonitor")
    if not mon:
        sys.exit("no tempLadderMonitor block in summary_arrays.json (run tools/m321_ladder_monitor.py update)")
    try:
        rec = make_record(mon, a.ref, a.note)
    except ValueError as e:
        sys.exit(str(e))
    print(json.dumps(rec, indent=1))
    if not a.dry_run:
        print("written" if append_record(rec) else "already acknowledged (no change)")


if __name__ == "__main__":
    main()
