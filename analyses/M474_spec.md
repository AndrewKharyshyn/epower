# M474 spec: capacity narrative bound to the computed apparent-scale keys (audit 2026-10-21, "Independent capacity-scale estimation and CV")

Scope: wording and bindings only. No estimator, producer, master or payload value changes; no new figure. The audit's independent window estimate (4.9141 Ah per 100 SoC points, day-bootstrap [4.8727, 4.9564], 1,543 windows on 116 days; terminal-energy scale 1.7909 kWh) is a reproduction/consistency TARGET, never typed into the repo; the released scale (capacityBasis.ahPer100.point 4.8926 Ah, bootstrapCI95 [4.8, 4.993], 1.7984 kWh [1.7581, 1.8429], 592 drives / 117 days / 185,105 events) lies inside the same band, and the audit's interval lies inside the released method range [4.6355, 5.3836].

## Change
1. The Health card row "Capacity SOH" (now "apparent SoC scale only", M467) states, from `S.capacityBasis` only: the Ah and kWh scale per 100 SoC points with their day-bootstrap intervals, the n (drives, days, events) and the range over the method variants; that it is the scale of the logged signal, not full capacity, accessible capacity or state of health; that physical full capacity and capacity fade are not identified (no relaxed-OCV count, sensor gain and BMS SoC remapping not separable); that it does not show whether 2.1 kWh is a gross capacity and the fitted scale the usable part (2.1 kWh stays an assumed constant, `verified:false`; `CAP_KWH` is not changed); that the 5 Ah figure is the manufacturer's documentary Article 10 reference, not a pack test of this vehicle.
2. `language_gate.py` rule `M474-capacity-scale-readings` (affirmative claims only: the scale 'confirms/proves' 2.1 or 1.8 kWh as gross/usable/full; the fitted scale 'gives/equals' usable/full capacity).
3. Test `tests/synthetic/test_capacity_narrative.py` (in ci.yml): payload keys carry interval and n; the JSX binds them and contains the readings; the rule fires on the claims and not on the negated wording.

## Not in scope
A new forward-blocked held-out comparison of the fitted scale against the fixed 5 Ah reference (the audit reports the fit better in 2 of 4 blocks, 'not uniformly superior'): it would be a new analysis needing its own spec, blind audit and Director; listed as an optional follow-up. Rated-Ah exposure and the legacy 2.1 kWh scenarios stay separate (M415).

## Gates
No new figure and no method change, so no blind audit or Director dispatch is required (CLAUDE.md escalation: new headline figure or method change); the wording follows the rulings already recorded (M415 exposure rule, owner decision 2026-10-02 on the 5 Ah lead). Release gate, semantic gate and the new test must pass.
