#!/usr/bin/env python3
"""M653 (owner decision 2026-11-14: the mileage pace may be shown): sets officialDisclosureCorrelation.usageRate.yearsToOfficialLifeKm = round(officialLifeKm / kmPerYr, 1) from the leaves of the same block
(plain arithmetic: the years at the current logged pace to reach the disclosed mileage; NOT a battery-life or state-of-health estimate), and updates the retraction note text accordingly.
The arrays builder no longer nulls this leaf (compute_summary_arrays.py, M653); this tool applies the same result to the carried payload without a rebuild. Exact-leaf edit, deep-diff guarded, idempotent.
Usage: python tools/m653_mileage_pace.py [--dry-run]"""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
P = os.path.join(ROOT, "summary_arrays.json")
OLD_NOTE = "calendar-life ceiling, seasonal/hot-tail/plating year sensitivities, years-to-official-life). Exposure rates"
NEW_NOTE = "calendar-life ceiling, seasonal/hot-tail/plating year sensitivities). The mileage pace (usageRate.yearsToOfficialLifeKm: disclosed mileage divided by the logged km per year, arithmetic only) is retained. Exposure rates"


def main():
    raw = open(P, "rb").read().decode("utf-8")
    A = json.loads(raw)
    old = copy.deepcopy(A)
    ur = A["officialDisclosureCorrelation"]["usageRate"]
    v = round(ur["officialLifeKm"] / ur["kmPerYr"], 1)
    if ur.get("yearsToOfficialLifeKm") not in (None, v):
        raise SystemExit("STOP: yearsToOfficialLifeKm is %r, expected null or %r" % (ur.get("yearsToOfficialLifeKm"), v))
    ur["yearsToOfficialLifeKm"] = v
    n = A["_retractedLifeEol"]
    if OLD_NOTE in n:
        A["_retractedLifeEol"] = n.replace(OLD_NOTE, NEW_NOTE)
    elif NEW_NOTE not in n:
        raise SystemExit("STOP: retraction note text not recognised")
    # deep diff: only these two leaves may differ
    chk = copy.deepcopy(A); chk["officialDisclosureCorrelation"]["usageRate"]["yearsToOfficialLifeKm"] = old["officialDisclosureCorrelation"]["usageRate"]["yearsToOfficialLifeKm"]; chk["_retractedLifeEol"] = old["_retractedLifeEol"]
    assert chk == old, "unexpected change"
    if "--dry-run" in sys.argv or A == old:
        print(json.dumps({"changed": A != old, "yearsToOfficialLifeKm": v})); return
    open(P, "wb").write(json.dumps(A, ensure_ascii=False, indent=1).encode("utf-8") + (b"\n" if raw.endswith("\n") else b""))
    print(json.dumps({"changed": True, "yearsToOfficialLifeKm": v}))


if __name__ == "__main__":
    main()
