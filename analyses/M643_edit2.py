"""M643 (UI-02): ComparisonCube and RegenCompareV2 read the Compare toggles (CompareCtx) instead of their own fixed cohort lists."""
def edit(p, pairs):
    s = open(p, encoding='utf-8', newline='').read()
    for o, n in pairs:
        ok = False
        for oo, nn in ((o, n), (o.replace('\n', '\r\n'), n.replace('\n', '\r\n'))):
            if s.count(oo) == 1:
                s = s.replace(oo, nn); ok = True; break
        assert ok, (o[:90], s.count(o))
    open(p, 'w', encoding='utf-8', newline='').write(s)

edit('xtrail_summary.jsx', [
 ('function ComparisonCube(){\n  const _coh=useCohort(); const C=S.comparisonCube; if(!C) return null;\n  const cohorts=_coh==="compare"?["warm","shoulder"].concat(cohortAvailable("cold")?["cold"]:[]):[_coh==="cold"?"cold":_coh];\n',
  'function ComparisonCube(){\n  const _coh=useCohort(); const C=S.comparisonCube; if(!C) return null;\n  const _sel=React.useContext(CompareCtx);      // M643 (UI-02): the Compare filter bar decides which cohort columns are shown\n'
  '  const cohorts=_coh==="compare"?["warm","shoulder"].concat(cohortAvailable("cold")?["cold"]:[]).filter(c=>_sel&&_sel[c]):[_coh==="cold"?"cold":_coh];\n'
  '  if(!cohorts.length) return <div style={{fontSize:11,color:"#64748b",padding:"6px 0"}} data-comparison-cube="none">No cohort selected: enable at least one of Warm, Shoulder, Cold in the filter bar above.</div>;\n'),
 ('  const cols=[["warm","Warm"],["shoulder","Shoulder"],["cold","Cold"]].filter(([c])=>D.cohorts[c]&&D.cohorts[c].strata&&D.cohorts[c].strata[stratum])\n',
  '  const _sel=React.useContext(CompareCtx);      // M643 (UI-02): the Compare filter bar decides which cohort columns are shown\n'
  '  const cols=[["warm","Warm"],["shoulder","Shoulder"],["cold","Cold"]].filter(([c])=>(!_sel||_sel[c])&&D.cohorts[c]&&D.cohorts[c].strata&&D.cohorts[c].strata[stratum])\n'),
])
print('ok')
