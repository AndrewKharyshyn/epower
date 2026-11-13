"""M634 wiring: the payload binding and the dashboard sentence for powerFadeTemperatureControls (appended to the primary-equivalence result text), and the ingestion stage after powerfade_temperature_specs."""
import json


def edit_jsx(pairs):
    p = 'xtrail_summary.jsx'
    s = open(p, encoding='utf-8', newline='').read()
    for o, n in pairs:
        ok = False
        for oo, nn in ((o, n), (o.replace('\n', '\r\n'), n.replace('\n', '\r\n'))):
            if s.count(oo) == 1:
                s = s.replace(oo, nn)
                ok = True
                break
        assert ok, (o[:80], s.count(o))
    open(p, 'w', encoding='utf-8', newline='').write(s)


edit_jsx([
    ('    powerFadeTemperatureSpecs: A.powerFadeTemperatureSpecs || null,\n',
     '    powerFadeTemperatureSpecs: A.powerFadeTemperatureSpecs || null,\n    powerFadeTemperatureControls: A.powerFadeTemperatureControls || null,   // M634 (spec analyses/M622_spec.md Rev 1)\n'),
    ('${temperatureSpecsSentence()}${vregAlignmentSentence()}', '${temperatureSpecsSentence()}${temperatureControlsSentence()}${vregAlignmentSentence()}'),
    ('// M499 (spec analyses/M499_spec.md Rev 2, Director: accept): temperature-specification sensitivity of the resistance-proxy months coefficient, bound to S.powerFadeTemperatureSpecs only\nfunction temperatureSpecsSentence(){',
     '''// M634 (spec analyses/M622_spec.md Rev 1): the four pre-registered temperature controls (linear, quadratic, Arrhenius, support-flagged spline) for the resistance-proxy and cell-spread months coefficients, bound to S.powerFadeTemperatureControls only
function temperatureControlsSentence(){
  const c=S.powerFadeTemperatureControls;
  if(!c||!c.resistanceProxyS0||!c.cellSpread) return "";
  const nm={"T-lin":"linear","T-quad":"quadratic","T-arr":"Arrhenius","T-spl":"spline"};
  const f=(v)=>typeof v==="number"?v.toFixed(2):"n/a";
  const one=(blk,unit)=>Object.keys(blk.specs).filter(k=>k!=="T-spl"||blk.specs[k].reportable).map(k=>{ const r=blk.specs[k]; return `${nm[k]} ${f(r.slope)} [${f(r.dayBootstrap.ci95[0])}, ${f(r.dayBootstrap.ci95[1])}]${r.includesZero?" (includes zero)":""}`; }).join("; ");
  const R=c.resistanceProxyS0, CS=c.cellSpread, ret=R.crossValidation.retention, m12=(R.attainability||{}).month12||{};
  const spl=R.specs["T-spl"], splTxt=spl.reportable ? "" : ` The spline is not reported (${spl.supportReason}).`;
  const chal=ret.challenger ? ` On the day-blocked cross-validation (K = ${R.crossValidation.K}) the ${nm[ret.challenger]} control predicts better than the Arrhenius primary on ${ret.consecutive} ingestion${ret.consecutive===1?"":"s"}; the rule switches the primary only after two consecutive ingestions (current-window figure, not a formal test).` : ` The Arrhenius primary is retained on the day-blocked cross-validation (K = ${R.crossValidation.K}).`;
  return ` Pre-registered temperature controls (M622 spec; trend and sensitivity specifications, estimated proxy; the equivalence test and its locked bound are unchanged). Resistance-proxy months coefficient, mΩ/month with day-clustered 95 % intervals (${R.nDrives} drives, ${R.nDays} days, original scale, smearing for the Arrhenius form): ${one(R)}.${splTxt} Cell spread, mV/month (${CS.nDrives} drives, ${CS.nDays} days): ${one(CS)}.${chal} Formal looks are at month 9 (descriptive only) and month 12 (full alpha); the standard error ceiling at the month-12 look is ${m12.seCeiling} against a current ${m12.currentSe}; ${m12.attainableNow ? "attainable" : "not attainable at the current standard error"}; every figure before the month-12 look is provisional.`;
}
// M499 (spec analyses/M499_spec.md Rev 2, Director: accept): temperature-specification sensitivity of the resistance-proxy months coefficient, bound to S.powerFadeTemperatureSpecs only
function temperatureSpecsSentence(){'''),
])

# ingestion stage: right after powerfade_temperature_specs
p = 'tools/ingest_stages.json'
s = open(p, encoding='utf-8', newline='').read()
anchor = '''   "id": "powerfade_temperature_specs",'''
i = s.index(anchor)
j = s.index('  },\n', i) + len('  },\n')
stage = '''  {
   "id": "winter_temperature_controls",
   "title": "M634: pre-registered temperature controls (linear, quadratic, Arrhenius, support-flagged spline) of the resistance-proxy and cell-spread months coefficients, day-blocked cross-validation, retention rule, per-look attainability; additive payload block powerFadeTemperatureControls + stamp (spec analyses/M622_spec.md Rev 1)",
   "cmd": [
    "python3",
    "tools/m634_winter_controls.py",
    "--splice"
   ],
   "needs": [
    "powerfade_temperature_specs"
   ],
   "verified": false,
   "outputs": [
    "summary_arrays.json"
   ]
  },
'''
s = s[:j] + stage + s[j:]
open(p, 'w', encoding='utf-8', newline='').write(s)
json.loads(s)
print('ok')
