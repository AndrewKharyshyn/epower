# M536 decision pack for Andrii: one engine-on / engine-off definition (DRAFT for Director check, 2026-10-30)

Evidence behind it: `analyses/M536_evidence.json` (phase 1), `analyses/M536_wave0.json`, `analyses/M536_wave0_addendum.json`, inventories `analyses/M536_inventory.json`. Nothing in the dashboard, payload or master has changed. Every number below is script-written; "not yet computed" means a wave-2 spec would compute it.

## 1. What "engine-on" means today (the problem)
- 300 rpm family (1 Hz grid, duration weighted): rpmDistribution bins (>= 300), rpmOptBand, rpmModeCentres, rpmFinding (superseded), engineOnBySpeed, turbo blocks, engine-start detector (> 300, run >= 2 s), and your regeneration engine-off proxy (<= 300, owner decision 2026-10-14 (g)).
- 400 rpm family: the pipeline's own EV state and master `engine_on_pct` (eng_rpm > 400, "the same threshold"), engineRuntime (M512, > 400 on RPM-supported intervals), rpmSyncPoint, GTR interval block, capacity_basis, fuel_analytics2, engineStateMachine (>= 400).
- Not rpm rules and kept separate by name: generator-active (reconstructed Pgen > 0; `simultaneity`), engine-start trigger (> 800 after <= 100), event classifiers (> 1200, > 2000).
- The two families differ by 2.325 h of the 99.87 h (B1 vs the M512 numerator): threshold 1.7 h (1.59 % of engine-on seconds, interval [1.46, 1.75] %), integration 0.6 h (0.75 %, [0.64, 0.87] %), order-dependent split, residual 0.

## 2. What the data say about the 300-400 rpm band
1.57 h = 1.57 % of engine-on time; 62 % of its seconds sit next to an engine-off second (spin-up / run-down), 99 % carry positive app-calculated load; it is slightly larger in slow-polled drives (1.68 % vs 1.23 % fast). The forward-fill limit matters only at zero (no fill drops engine-on hours by 21 %, almost all in slow-polled drives); 5 s vs 15 s changes them by 0.4 %. Hysteresis rules (on >= 400, off < 300) give 1.5-2.2 % more than plain > 400.

## 3. Options
| | A: one rule, rpm > 400, band reported separately | B: one rule, rpm >= 300 | C: keep both, label each everywhere |
|---|---|---|---|
| Figures that move | the 300 family: engine-on hours -1.57 h (-1.57 %); rpmOptBand 63.073 [60.614, 65.332] % -> 64.092 [61.597, 66.407] % (+1.02 pp, inside the previous interval); engineOnBySpeed, turbo, start-rate, rpmModeCentres denominators: not yet computed | the 400 family: master engine_on_pct and the EV-state columns, engineRuntime, rpmSyncPoint, GTR interval, capacity_basis, fuel_analytics2: not yet computed; engine-on hours +1.57 h | none |
| Master / ML risk | none (the master already uses 400) | changes master columns -> refit / ML16 freeze issue, clean-room rebuild open item | none |
| Regeneration proxy | stays 300 under owner decision (g) unless you depart; it would then be the only 300 rule, named "engine-off proxy" | consistent with (g) | stays |
| Work | ~4 waves (B1 family, per-speed / turbo, start-rate, boundary > vs >=), each its own spec, splice, deep diff, audit | larger: touches the master pipeline | labels only (M521-style), no unification |
| Director view | recommended | not recommended | acceptable as a stop-gap only; does not meet "single definition" |

Also needed in A: one boundary (strict > 400 everywhere; engineStateMachine currently uses >= 400; 5 seconds at exactly 400 rpm in a 20-drive sample, negligible but should be one rule).

## 4. What I need from you
1. Option A, B or C (verbatim answer; recorded in the CHANGELOG). 2. Keep the regeneration proxy at 300 (g) or depart from it (a separate decision). 3. If A or B: go-ahead to write the wave specs (each figure-changing wave needs Director review and a blind audit when a figure leaves its interval).

## 5. Limits
Phase 1 and wave 0 do not cover: the cross-tab against generator-active (per-second Pgen not stored) or the app fuel rate (not in the loader map); the native-row fill limit counts rows, the grid limit counts seconds (for slow-polled drives 15 rows can span more than 15 s); the shifts above are what-ifs on the same grid, not new published figures; no article figure.
