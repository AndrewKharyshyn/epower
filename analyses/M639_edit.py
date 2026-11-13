"""M639: dashboard row and sentence for the mix-standardised f_gen sensitivity (binds Z.fGenMixStandardised, Z = generatorTractionRecon.gtrClosure)."""
def edit(p, pairs):
    s = open(p, encoding='utf-8', newline='').read()
    for o, n in pairs:
        ok = False
        for oo, nn in ((o, n), (o.replace('\n', '\r\n'), n.replace('\n', '\r\n'))):
            if s.count(oo) == 1:
                s = s.replace(oo, nn); ok = True; break
        assert ok, (p, o[:80], s.count(o))
    open(p, 'w', encoding='utf-8', newline='').write(s)

ROW_ANCHOR = '      <tr><td style={{padding:"2px 6px"}}>Implied closure parameter \u03b1* (95% CI)</td>'
ROW = ('      {Z.fGenMixStandardised && (() => { const M = Z.fGenMixStandardised, P = M[M.displayedPrimary], c = P.joint.ci95.E1; return (<tr><td style={{padding:"2px 6px"}}>Drive-type-mix-standardised (corpus km mix) f_gen, model-derived (Path B), sensitivity ({M.displayedPrimary === "urbanNonUrban" ? "urban / non-urban strata" : "four drive types"}; 95% CI)</td>'
       '<td style={{padding:"2px 6px",fontWeight:700}}>{fmtKeep(P.E1,2,0.5)}{c ? <> ({fmtKeep(c[0],2,0.5)} to {fmtKeep(c[1],2,0.5)})</> : " (interval withheld)"}</td></tr>); })()}\n')
SENT_ANCHOR = '    <div style={{color:"#b45309",marginTop:3}}>Scope: the subset of drives that log the fuel signal'
SENT = ('    {Z.fGenMixStandardised && (() => { const M = Z.fGenMixStandardised, F = M.fourTypes, U = M.urbanNonUrban; return (<div style={{marginTop:3}}>Mix standardisation (M639): the headline is a ratio over the {M.E0.nDrives} drives that log the fuel signal, whose drive-type mix differs from the corpus '
        '(urban {(U.strata.urban.closureKmShare*100).toFixed(0)}% of their km against {(U.strata.urban.referenceKmShare*100).toFixed(0)}% of the {M.referenceSet.nDrives} canonical-clean corpus drives). Re-weighted to the corpus km mix the ratio is {fmtKeep(U.E1,2,0.5)} for urban / non-urban strata '
        '(joint day-clustered 95% CI {fmtKeep(U.joint.ci95.E1[0],2,0.5)} to {fmtKeep(U.joint.ci95.E1[1],2,0.5)}; fixed-weight CI {fmtKeep(U.fixedWeights.ci95.E1[0],2,0.5)} to {fmtKeep(U.fixedWeights.ci95.E1[1],2,0.5)}). {M.verdict.charAt(0).toUpperCase() + M.verdict.slice(1)}. '
        'With four drive types it is {fmtKeep(F.E1,2,0.5)}, labelled extrapolative because the highway cell ({F.strata.highway.closureDrives} drives, {F.strata.highway.closureDays} days) is below the support floor. '
        'The headline is unchanged; the sensitivity assumes fuel-signal availability does not depend on season, SoC or period within a drive type. It is not an article figure.</div>); })()}\n')
edit('xtrail_summary.jsx', [(ROW_ANCHOR, ROW + ROW_ANCHOR), (SENT_ANCHOR, SENT + SENT_ANCHOR)])
print('ok')
