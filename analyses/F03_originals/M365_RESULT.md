# M365: read-only comparison on the sha256-verified originals (owner-approved 2026-10-03; script-written from M365_compare.json)

Provenance-sensitivity analysis, not a correction. Same code and trips on the raw/ copies and on the originals of the files that fail the raw_manifest hash; nothing copied into raw/; no payload or master write.

## A. M339 charging sub-state (litres of logged fuel while net pack power < -deadband), 95 trips, 35 days
| deadband | charging share raw/ | charging share originals | difference (originals - raw/), 95% CI (day-clustered, seed 42, 4000) |
|---|---|---|---|
| 0.1 kW | 76.93% | 76.79% | -0.14 pp [-0.20 pp, -0.08 pp], 35 days |
| 0.5 kW | 75.87% | 75.60% | -0.27 pp [-0.35 pp, -0.17 pp], 35 days |
| 1 kW | 73.80% | 74.08% | +0.28 pp [+0.18 pp, +0.37 pp], 35 days |

Total logged litres on these trips: raw/ 55.776, originals 55.647.

## B. M356 phase energies on the same 333 drives (1558 cycles raw/, 1558 originals)
| window | regen zero share raw/ | originals | difference | regen median Wh raw/ / originals | discharge zero share raw/ / originals | net median Wh raw/ / originals |
|---|---|---|---|---|---|---|
| launch | 81.36% | 80.98% | -0.38 pp | 0.0 / 0.0 | 4.18% / 4.05% | 3.62 / 3.65 |
| approach | 64.72% | 64.20% | -0.52 pp | 0.0 / 0.0 | 9.25% / 9.25% | 1.41 / 1.43 |
| cycle | 62.75% | 62.49% | -0.26 pp | 0.0 / 0.0 | 3.34% / 3.28% | 5.94 / 5.85 |

Reading (descriptive): the regen-direction zero shares are lower on the originals in every window, the direction expected from integer-rounded current in the raw/ re-exports, but by a fraction of a percentage point; medians and the net are essentially unchanged. The charging-share differences are of either sign by deadband and a fraction of a percentage point. No decision threshold was pre-registered for this comparison, so no pass/fail is stated; interpretation (Director / Andrii) is separate. F03 stays open and every raw-derived figure keeps its label.
