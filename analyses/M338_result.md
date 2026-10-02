# M338 result (script-written numbers: `tools/m338_lhv_splice.py` -> `M338_result.json`; blind audit: confirmed)

Single assumed E10 LHV for the SoC-balanced scenario: 751 g/L x 41.15 MJ/kg = 8.5843 kWh/L (was the literal 8.9). Control C0: the unchanged-method result reproduced the stored block leaf for leaf; the allow-list held (22 leaves; every `regression` leaf byte-identical); known answer new correction = old x 8.9/8.5843 exact (error 0, unrounded).

| (L/100 km, 230 trips, 48 days) | before (8.9) | after (8.5843) |
|---|---|---|
| raw fleet | 5.691 | 5.691 |
| SoC-balanced, eta 0.30 | 5.479 | 5.472 |
| correction (delta) | -0.211 | -0.219 |
| bootstrap median / 95% CI | 5.481 / 5.262-5.699 | 5.474 / 5.255-5.690 |

The shift (-0.008 L/100 km; audit reference -0.00776) is about 4% of the CI half-width and is a basis-consistency change, not a finding; the new level is inside the old CI and the sign is unchanged (no escalation). Blind audit: deltas reproduced exactly (-0.219, -0.263, -0.188 for eta 0.25/0.30/0.35), levels within 0.003 (audit used a trapezoid speed integral with a 10 s cap; the builder's distance rule differs), bootstrap CI within 0.003.

Eligibility (stated because the audit found it under-specified): fuel-accumulator subset = trips with >= 10 fuel samples, accumulator delta in (0.01, 30] L, a usable speed channel, integrated distance >= 1 km and a SoC channel; trips with a non-advancing accumulator are therefore dropped, a selection that slightly raises the raw L/100 km. Speed is mostly the OBD fallback channel, not the VCM one.

Limits (wording): assumed E10 basis, fuel composition not measured; the E10 span (8.50-8.70 kWh/L) is not propagated; the correction scales as CAP/(eta*LHV), and the unverified CAP (2.1 kWh; 5 Ah OEM-rated lead) dominates (CAP 5.0 instead of 2.1 gives a correction of about -0.52, 2.4x), eta spans -0.263 to -0.188, LHV moves it by 0.008; the bootstrap CI is conditional on eta, CAP and LHV and is essentially the sampling CI of raw fleet fuel per km; dSoC is quantised at 0.5 pp and SoC is a BMS display, not a metered energy. The correction is a conditional scenario, not an estimate.
Basis: staged raw_only/ (raw/, F03 provenance-sensitive).
