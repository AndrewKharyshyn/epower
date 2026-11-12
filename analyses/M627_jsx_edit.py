"""One-off editor: replace the hand-typed BMS Headroom Utilization block of xtrail_summary.jsx by a block bound to S.headroomUtilization (M627, spec analyses/M626_spec.md Rev 1)."""
p = 'xtrail_summary.jsx'
s = open(p, encoding='utf-8', newline='').read()
a = s.index('        {/* M140 (2026-08-18): BMS-declared possible-power headroom utilization.')
b = s.index('        <Section seasonAware title="Turbo Pattern">')
nl = '\r\n' if '\r\n' in s[a:a + 400] else '\n'
new = r'''        {/* M627 (spec analyses/M626_spec.md Rev 1): the possible power the BMS reports, logged / app-calculated, both column names (hp until 2026-09-30, kW after), per era.
            Every figure binds to S.headroomUtilization; nothing here is typed. */}
        {S.headroomUtilization && S.headroomUtilization.nFilesCovered > 0 && (
        <Section title="BMS Headroom Utilization">
          <div style={{padding:10,background:"#f1f5f9",borderRadius:8,fontSize:11,color:"#374151",lineHeight:1.7,border:"1px solid #e2e8f0"}}>
            {(() => { const h = S.headroomUtilization, cv = h.coverage || {}, ce = h.ceiling || {}, er = h.eras || {}, un = h.unit || {};
              const f3 = x => x == null ? "—" : Number(x).toFixed(3);
              const ciS = o => (o && o.length === 2) ? `${f3(o[0])}–${f3(o[1])}` : "—";
              const eraNames = Object.keys(er);
              const row = (lab, st) => st ? (<tr key={lab}><td style={{padding:"2px 6px"}}>{lab}</td><td style={{padding:"2px 6px"}}>{st.nEvents}</td><td style={{padding:"2px 6px"}}>{st.nDrives} / {st.nDays}</td><td style={{padding:"2px 6px"}}>{f3(st.median)} ({ciS(st.ci95DayCluster && st.ci95DayCluster.median)})</td><td style={{padding:"2px 6px"}}>{f3(st.p95)} ({ciS(st.ci95DayCluster && st.ci95DayCluster.p95)})</td><td style={{padding:"2px 6px"}}>{f3(st.max)}</td><td style={{padding:"2px 6px"}}>{st.nAbove1}</td></tr>) : null;
              const table = (dir, title) => (<table style={{borderCollapse:"collapse",fontSize:10,marginBottom:6}}><thead><tr style={{textAlign:"left",color:"#64748b"}}><th style={{padding:"2px 6px"}}>{title}</th><th style={{padding:"2px 6px"}}>events</th><th style={{padding:"2px 6px"}}>drives / days</th><th style={{padding:"2px 6px"}}>median (95% CI, day-clustered)</th><th style={{padding:"2px 6px"}}>p95 (95% CI)</th><th style={{padding:"2px 6px"}}>max</th><th style={{padding:"2px 6px"}}>above 1</th></tr></thead><tbody>
                {row("both eras", dir === "charge" ? h.chargeUtilization : h.dischargeUtilization)}
                {eraNames.map(e => row(`${e} era`, er[e] && er[e][dir]))}</tbody></table>);
              return (<>
              <p style={{marginTop:0}}><strong>What this is.</strong> The BMS reports a possible input power and a possible output power: the limit the BMS reports (logged / app-calculated). The logger wrote them as <code>(hp)</code> columns until 2026-09-30 and as <code>(kW)</code> columns after it; both are read, and <code>(hp)</code> is converted with the metric horsepower factor ({un.factorUsedHpToKw}). A utilisation is the logged I &times; V power (charge-positive raw) aligned to the nearest possible-power sample, divided by the BMS-reported limit; it is not a physical capability. {cv.drivesWithChannel} of {cv.scannedDrives} corpus drives carry the channel ({cv.drivesAnalysed} analysed); files are selected by header, not by date.</p>
              <p><strong style={{color:"#0f172a"}}>Coverage by era.</strong> {eraNames.map(e => { const c = (cv.byEra || {})[e] || {}; return `${e}: ${c.drives} drives, ${c.dateFrom} to ${c.dateTo}, ${c.nChargeEvents} charge and ${c.nDischargeEvents} discharge events, median channel gap ${c.medianChannelGapS} s, median match rate ${c.medianMatchRate}`; }).join("; ")}. The channel is polled far less densely than ordinary BMS current and voltage, so a few utilisations exceed 1.0, most plausibly a stale match during fast current transients; none is clipped.</p>
              <div style={{overflowX:"auto"}}>{table("charge", "Input (charge)")}{table("discharge", "Output (discharge)")}</div>
              <p><strong style={{color:"#0f172a"}}>Reported limit and a possible ceiling.</strong> The output limit is {h.outputCeilingConstant ? "the same value in every analysed sample" : `not constant (${h.outputCeilingRangeKw && h.outputCeilingRangeKw[0]} to ${h.outputCeilingRangeKw && h.outputCeilingRangeKw[1]} kW)`}. The reported limit may be saturated at {ce.valueKw} kW ({ce.basis}); samples at or above {Number(ce.valueKw - ce.toleranceKw).toFixed(2)} kW: {Object.keys(ce.byEra || {}).map(e => { const c = ce.byEra[e]; return `${e} era, input ${c.inputSamplesAtCeiling} of ${c.inputSamples}, output ${c.outputSamplesAtCeiling} of ${c.outputSamples} (${c.filesWithSamplesAtCeiling} files)`; }).join("; ")}. The statistics for events whose limit is below that value are in the data (<code>belowCeiling</code>); they are conditional on the denominator and are not a censoring correction.</p>
              <p style={{marginBottom:0}}><strong style={{color:"#0f172a"}}>Unit check.</strong> Share of converted possible-power samples on a multiple of {un.gridKw} kW: {Object.keys(un.eras || {}).map(e => `${e} ${f3(un.eras[e].share)}`).join(", ")}{un.eras && un.eras.hp && un.eras.hp.shareMechanicalFactor != null ? `; with the mechanical factor ${un.eras.hp.mechanicalFactor} the hp share would be ${f3(un.eras.hp.shareMechanicalFactor)}` : ""}. The two eras are shown side by side; no contrast between them is drawn, and nothing here shows that the limit constrained driving.</p>
              </>); })()}
          </div>
        </Section>
        )}
'''.replace('\n', nl)
s = s[:a] + new + s[b:]
open(p, 'w', encoding='utf-8', newline='').write(s)
print('ok')
