#!/usr/bin/env python3
"""Writes analyses/F03_originals/M365_RESULT.md from M365_compare.json (every figure script-written; read-only on the JSON). Usage: python tools/f03_originals_report.py"""
import json, os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
r = json.load(open("analyses/F03_originals/M365_compare.json", encoding="utf-8"))
A, B = r["A_chargingSubState"], r["B_phaseEnergies"]
pp = lambda v: f"{v * 100:+.2f} pp"
L = ["# M365: read-only comparison on the sha256-verified originals (owner-approved 2026-10-03; script-written from M365_compare.json)", "",
     "Provenance-sensitivity analysis, not a correction. Same code and trips on the raw/ copies and on the originals of the files that fail the raw_manifest hash; nothing copied into raw/; no payload or master write.", "",
     f"## A. M339 charging sub-state (litres of logged fuel while net pack power < -deadband), {A['nTrips']} trips, {A['nDays']} days",
     "| deadband | charging share raw/ | charging share originals | difference (originals - raw/), 95% CI (day-clustered, seed 42, 4000) |", "|---|---|---|---|"]
for k, v in A["byDeadbandKw"].items():
    d = v["shareDifferenceOriginalsMinusRaw"]
    L.append(f"| {k[2:]} kW | {v['chargingShare']['raw'] * 100:.2f}% | {v['chargingShare']['originals'] * 100:.2f}% | {pp(d['est'])} [{pp(d['ci95'][0])}, {pp(d['ci95'][1])}], {d['nDays']} days |")
L += ["", f"Total logged litres on these trips: raw/ {A['totalLitres']['raw']}, originals {A['totalLitres']['originals']}.", "",
      f"## B. M356 phase energies on the same {B['nDrives']} drives ({B['raw']['nCycles']} cycles raw/, {B['originals']['nCycles']} originals)",
      "| window | regen zero share raw/ | originals | difference | regen median Wh raw/ / originals | discharge zero share raw/ / originals | net median Wh raw/ / originals |", "|---|---|---|---|---|---|---|"]
for w in ("launch", "approach", "cycle"):
    a, b = B["raw"][w], B["originals"][w]
    L.append(f"| {w} | {a['regenZeroShare'] * 100:.2f}% | {b['regenZeroShare'] * 100:.2f}% | {pp(b['regenZeroShare'] - a['regenZeroShare'])} | {a['regenMedian']} / {b['regenMedian']} | {a['dischargeZeroShare'] * 100:.2f}% / {b['dischargeZeroShare'] * 100:.2f}% | {a['netMedian']} / {b['netMedian']} |")
L += ["", "Reading (descriptive): the regen-direction zero shares are lower on the originals in every window, the direction expected from integer-rounded current in the raw/ re-exports, but by a fraction of a percentage point; medians and the net are essentially unchanged. The charging-share differences are of either sign by deadband and a fraction of a percentage point. No decision threshold was pre-registered for this comparison, so no pass/fail is stated; interpretation (Director / Andrii) is separate. F03 stays open and every raw-derived figure keeps its label."]
open("analyses/F03_originals/M365_RESULT.md", "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
print("\n".join(L))
