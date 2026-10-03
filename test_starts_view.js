// M362: known-answer test of startsViewModel extracted from xtrail_summary.jsx (spec analyses/M362_spec.md Rev 2).
const fs=require('fs');
const src=fs.readFileSync('xtrail_summary.jsx','utf8');
const m=src.match(/\/\*M362-MODEL-BEGIN\*\/([\s\S]*?)\/\*M362-MODEL-END\*\//); if(!m){console.error('FAIL: model not found');process.exit(1);}
const {startsViewModel,STARTS_MIN_IQR_N,STARTS_MIN_IQR_DAYS,STARTS_MIN_WHISKER_N}=new Function(m[1]+';return {startsViewModel,STARTS_MIN_IQR_N,STARTS_MIN_IQR_DAYS,STARTS_MIN_WHISKER_N};')();
let f=0; const t=(n,c)=>{ if(!c){f++;console.log('FAIL',n);} else console.log('  ok:',n); };
const base={label:'Urban',color:'#f00',lo:0,hi:500,avg:105,classKey:'urban',median:93.2,p10:30,p25:60,p75:130,p90:190,n:408,nDays:94,nShort:118,shortKm:2,maxDrive:'a.csv',maxKm:1.2};
const M343={urban:{est:99.75,ci95:[91.8,107.7],nTrips:406,nDays:94}};
let v=startsViewModel([base],M343);
t('thresholds are 5 drives, 3 days, 10 drives',STARTS_MIN_IQR_N===5&&STARTS_MIN_IQR_DAYS===3&&STARTS_MIN_WHISKER_N===10);
t('dot is the median, IQR and whisker shown at n=408',v.rows[0].dot===93.2&&v.rows[0].showIqr&&v.rows[0].showWhisker);
t('diamond binds to the M343 est and CI with its own n',v.rows[0].diamond.est===99.75&&v.rows[0].diamond.lo===91.8&&v.rows[0].diamond.n===406);
t('axis bound follows p90 / CI, not the 500 maximum (190 -> 200)',v.maxS===250&&v.maxS<500, String(v.maxS));
t('maximum on a short drive is described, not drawn',/Urban maximum 500 per 100 km on a 1.2 km drive/.test(v.rows[0].maxText));
v=startsViewModel([base],null); t('no M343 (cohort views): no diamond',v.rows[0].diamond===null);
v=startsViewModel([{...base,n:7,nDays:5}],null); t('n=7: IQR shown, whisker not',v.rows[0].showIqr&&!v.rows[0].showWhisker);
v=startsViewModel([{...base,n:4,nDays:4}],null); t('n=4: no spread, note states n and days',!v.rows[0].showIqr&&/n=4 drives, 4 days \(spread not shown\)/.test(v.rows[0].spreadNote));
v=startsViewModel([{...base,n:12,nDays:2}],null); t('n=12 but 2 days: no spread',!v.rows[0].showIqr&&!v.rows[0].showWhisker);
const old={label:'Mixed Highway',color:'#00f',lo:41,hi:144,avg:77};
v=startsViewModel([old],null); t('payload without the M362 fields falls back to avg and the old extent, no spread',v.rows[0].dot===77&&!v.rows[0].showIqr&&v.rows[0].key==='mixed_highway'&&v.maxS>=150);
t('empty input does not throw',startsViewModel(undefined,undefined).rows.length===0);
console.log(f?'STARTS VIEW TEST FAILED':'STARTS VIEW TEST PASSED'); process.exit(f?1:0);
