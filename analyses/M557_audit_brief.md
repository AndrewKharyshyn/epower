# M557 blind-audit brief (claim and data path only)

Task: for each of the 13 numbered items below, say what the TARGET quantity is derived from and what the VALIDATOR quantity is derived from, using the repository code and the payload (`summary_arrays.json`) as sources (read them; cite the file and function). Do NOT read `channel_dependency_graph.json`, `independence_claims.json`, `tools/dependency_audit.py`, `analyses/M557_check*.json`, `analyses/M557_spec.md` or any other `analyses/M557_*` file. The audit's idea: a derived sibling must not validate its parent as an independent measurement.

For each item return: `targetRawAncestors` and `validatorRawAncestors` (the logged or app-calculated channels, unlogged inputs and constants each depends on, named by their raw header string where one exists), `shared` (the intersection), `sharedUnverifiedConstant` (true if the intersection contains an assumed constant), and a `class` using these definitions:
- `coding_check_only`: the validator is the same derivation re-coded.
- `circular`: one is an ancestor or part of the other, or the validator contains the target.
- `model_adequacy`: the validator is the same model refitted or re-split on the same data, or a richer model order.
- `shared_raw_input`: different derivations that read at least one shared logged / app-calculated / unlogged input.
- `independent_conditional_on_unverified_constant`: no shared data input but a shared unverified constant.
- `independent`: nothing shared.
- `negative_control` (items 7-13): in `nullMechanism` state why the control should be null, biased or one-sided, and what the payload records as its outcome.
Report ambiguities. Return one JSON file `M557_audit_result.json` in your scratchpad keyed by item number.

Items (target | validator), neutral labels:
1. Released gross throughput (energyUncertaintyMC) | same-algorithm re-implementation of it
2. Released gross throughput | re-integration with true trapezoidal integration on interpolated native timestamps
3. Buffer discharge-impulse detector events (bufferImpulse) | the full four-detector chain reconciliation (startEventChain)
4. Engine-start hazard model, blocked-day cross-validation (socHysteresisV2) | rolling-origin cross-validation of it
5. First-order drive-type transition model (regimeTransition) | second-order model comparison
6. powerFade resistance-proxy trend | resistanceVreg sensitivity specification
7. lowSpeedDissipation ceiling-defence diverted power | lowSpeedDissipation fuelCutCoast negativeControl
8. loggerCadence gross-throughput ratio under fast-to-slow thinning | slowToSlowerControl
9. loggerCadence gross-throughput ratio under fast-to-slow thinning | loggerCadence.sensitivity.negativeControls (peak keys)
10. serialDependence cellSpread trend slope | its misspecControl
11. serialDependence resistanceVreg trend slope | its misspecControl
12. powerFadeEquivalence S1 specification | powerFadeEquivalence s0Control
13. powerFadeTemperatureSpecs specification set | its falsificationClause
