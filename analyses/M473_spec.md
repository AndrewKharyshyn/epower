# M473 spec: one interval reference convention for the trend table and the equivalence test (audit 2026-10-21, "Independent trend checks and inferential limits")

Status: reference-distribution change of two released intervals. Process note (honest record): the one-line producer change and its known-answer targets (the audit's published cluster-t intervals) were prepared before this file was written; the blind audit result was read only after it. Gates: blind audit (analytical-auditor, design stated, code not shown), Director (convention, wording, TOST non-flip). No new data, no new estimator.

## Defect
`degradationTrends.{cellSpread,resistanceVreg}.clusterRobustOLS.ci95` came from statsmodels `conf_int()` on a cluster covariance, i.e. a NORMAL reference, while the equivalence test (`_tost`, M158) has used the cluster-t reference t(G-1) (G = number of day clusters). One table, two conventions. The audit reproduced coefficients and SEs exactly and found the cluster-t interval slightly wider; neither sign conclusion changes.

## Change
1. `degradation_trends._cluster_ols`: ci95 = slope +/- t_{0.975, G-1} x SE_cluster (G = distinct days of the fitted rows); new leaf `ciReference` = 't(df=G-1)'. Slope, cluster SE, n, days, autocorrelation and every equivalence leaf are unchanged.
2. Readers of the former "released" CR1 interval now read `dependenceSensitivity.trendSlopes.*.cr1.ci95T_Gminus1` (JSX health rows and sign sentences, `semantic_gate.py`, `tools/serial_dependence.py`). The key `ci95NormalAsReleased` stays in the payload as the history of the convention (no key rename, M326) with a `referenceNote` saying so; the CR2, wild-cluster, day-pairs and week-block sensitivities are unchanged and stay visible.
3. Leaf-level splice `tools/m473_splice.py` (allow-list: the two clusterRobustOLS interval leaves + `ciReference`, `evidenceLedger.rows[*].checks[*].ci95` re-derived by the producer, and `cr1.referenceNote`); it refuses on any other difference or a changed slope / SE / n, and checks ci95 = slope +/- t(G-1) x SE.

## Known-answer targets (audit, independent least-squares and day-cluster sandwich with the standard finite-sample scaling)
cellSpread: slope 0.5239, SE 0.1300, t-interval [0.2665, 0.7814] (was normal [0.2692, 0.7787]), df 116. resistanceVreg: slope 0.8860, SE 0.5370, t-interval [-0.1798, 1.9518] (was [-0.1665, 1.9385]), df 97. Equivalence unchanged (cellSpread pTOST 0.9867, not equivalent; reference t(df=116) already).

## Readings (Director wording)
The positive loaded cell-spread slope is a conditional association in one vehicle across a seasonal window, not a measured capacity loss and not causal; a resistance interval spanning zero is not evidence of no degradation; failed equivalence stays separate from evidence of stability.

## Escalation
Any sign flip of a displayed trend sentence, or a TOST outcome flip, goes to the Director (neither occurs: cellSpread lower bound 0.2665 > 0, resistance interval spans 0 before and after).
