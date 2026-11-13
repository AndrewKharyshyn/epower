"""M641: dashboard ladder, coverage sentence and the Monte Carlo relabel (binds S.energySupportLadder and S.energyUncertaintyMC.labelNumericalSensitivity)."""
def edit(p, pairs):
    s = open(p, encoding='utf-8', newline='').read()
    for o, n in pairs:
        ok = False
        for oo, nn in ((o, n), (o.replace('\n', '\r\n'), n.replace('\n', '\r\n'))):
            if s.count(oo) == 1:
                s = s.replace(oo, nn); ok = True; break
        assert ok, (p, o[:90], s.count(o))
    open(p, 'w', encoding='utf-8', newline='').write(s)

A1 = '              <p style={{marginTop:6}}><strong style={{color:"#0f172a"}}>Sources.</strong> Contribution of each source: timing offset'
LADDER = (
 '              {S.energyUncertaintyMC.labelNumericalSensitivity && <p style={{marginTop:6}}><strong style={{color:"#0f172a"}}>What the range is.</strong> {S.energyUncertaintyMC.labelNumericalSensitivity}</p>}\n'
 '              {S.energySupportLadder && (() => { const L = S.energySupportLadder, P = L.policies, order = ["cap5","cap10","capNone","drop1.6","drop2.5","drop3.5","drop5","drop10","drop30"], nm = k => k === "capNone" ? "cap-at-c, no cap" : k.startsWith("cap") ? "cap-at-c, c = " + P[k].seconds + " s" : "drop-above-g, g = " + P[k].seconds + " s"; return (<>\n'
 '              <p style={{marginTop:6}}><strong style={{color:"#0f172a"}}>Support-policy ladder.</strong> The same logged current and voltage, re-integrated under different treatments of long intervals between samples ({L.eligibility}). It is a deterministic support-policy sensitivity of an estimated, offset-uncorrected throughput; it is not an error bar or an uncertainty interval, and no interval is drawn. The published total uses the cap-5 rule.</p>\n'
 '              <table style={{borderCollapse:"collapse", fontSize:"0.85em", margin:"4px 0"}}><thead><tr><th style={{textAlign:"left", padding:"2px 8px"}}>Policy</th><th style={{padding:"2px 8px"}}>Gross kWh</th><th style={{padding:"2px 8px"}}>Share of published</th><th style={{padding:"2px 8px"}}>Integrated h</th><th style={{padding:"2px 8px"}}>Drives / days</th></tr></thead><tbody>\n'
 '              {order.map(k => <tr key={k} style={{fontWeight: k === L.anchor ? 700 : 400}}><td style={{padding:"2px 8px"}}>{nm(k)}{P[k].role ? " (" + P[k].role + ")" : ""}{P[k].note ? " \u2014 " + P[k].note : ""}</td><td style={{padding:"2px 8px", textAlign:"right"}}>{fmtKeep(P[k].grossKwh,1)}</td><td style={{padding:"2px 8px", textAlign:"right"}}>{(P[k].shareOfPublished*100).toFixed(2)}%</td><td style={{padding:"2px 8px", textAlign:"right"}}>{fmtKeep(P[k].integratedHours,1)}</td><td style={{padding:"2px 8px", textAlign:"right"}}>{P[k].nDrives} / {P[k].nDays}</td></tr>)}\n'
 '              </tbody></table>\n'
 '              <p style={{marginTop:6}}><strong style={{color:"#0f172a"}}>Per-drive support and coverage.</strong> Support share of a drive is the integrated time in intervals of at most 2.5 s over its integrated time under the published rule. Classes: {Object.keys(L.supportClasses).map(c => c + ": " + L.supportClasses[c]).join(", ")} drives. Against the drop-above-2.5 s reading, the per-drive median absolute difference is {L.perDriveDifferenceVsDropAbove2p5s.medianAbs} Wh (95th percentile {L.perDriveDifferenceVsDropAbove2p5s.p95Abs} Wh, 99th {L.perDriveDifferenceVsDropAbove2p5s.p99Abs} Wh); the drive with the largest difference ({L.largestDifferencesAbsolute[0].file.replace(".csv","")}) is {fmtKeep(L.largestDifferencesAbsolute[0].publishedKwh,2)} kWh under the published rule and {fmtKeep(L.largestDifferencesAbsolute[0].dropAbove2p5sKwh,2)} kWh at {(L.largestDifferencesAbsolute[0].supportShare*100).toFixed(1)}% support. {L.coverage.drivesWithoutIntegral} drives ({fmtKeep(L.coverage.kmWithoutIntegral,0)} km, {(L.coverage.kmShareOfCorpus*100).toFixed(1)}% of corpus distance) carry no integral and are not in any row. Limits: {L.limits.join("; ")}.</p></>); })()}\n')
edit('xtrail_summary.jsx', [
 (A1, LADDER + A1),
 ('metric={`95% CI [${S.energyUncertaintyMC?.grossThroughputMC?.throughputKwh?.p2_5?.toFixed(1)}',
  'metric={`95% Monte Carlo sensitivity range [${S.energyUncertaintyMC?.grossThroughputMC?.throughputKwh?.p2_5?.toFixed(1)}'),
])
print('ok')
