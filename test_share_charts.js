// M571: known-answer test of shareStackModel and dumbbellModel extracted from xtrail_summary.jsx (spec analyses/M571_spec.md).
const fs=require('fs');
const src=fs.readFileSync('xtrail_summary.jsx','utf8');
const m=src.match(/\/\*M571-MODEL-BEGIN\*\/([\s\S]*?)\/\*M571-MODEL-END\*\//); if(!m){console.error('FAIL: model not found');process.exit(1);}
const {shareStackModel,dumbbellModel}=new Function(m[1]+';return {shareStackModel,dumbbellModel};')();
let f=0; const t=(n,c,x)=>{ if(!c){f++;console.log('FAIL',n,x===undefined?'':x);} else console.log('  ok:',n); };
const eq=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
const K=['a','b','c','d'];

let v=shareStackModel([{label:'u',shares:{a:40,b:30,c:20,d:10}}],K)[0];
t('segments are cumulative 0-40-70-90-100',eq(v.segs.map(s=>[s.x0,s.x1]),[[0,40],[40,70],[70,90],[90,100]]),JSON.stringify(v.segs));
t('total 100, not flagged, not empty',v.total===100&&!v.off&&!v.empty);
v=shareStackModel([{label:'u',shares:{a:40.2,b:30.4,c:20.1,d:9.4}}],K)[0];
t('rounding drift inside 1 pp is not flagged',!v.off,String(v.total));
v=shareStackModel([{label:'u',shares:{a:50,b:30,c:10,d:5}}],K)[0];
t('shares summing to 95 are flagged and not rescaled',v.off&&v.total===95&&v.segs[3].x1===95);
v=shareStackModel([{label:'u',shares:{a:60,b:60}}],K)[0];
t('shares summing over 100 are flagged',v.off&&v.total===120);
v=shareStackModel([{label:'u',shares:{a:50,b:null,c:'x',d:-5}}],K)[0];
t('null, string and negative shares are skipped, not zeroed',v.segs.length===1&&v.segs[0].k==='a');
v=shareStackModel([{label:'u'},{label:'w',shares:{}}],K);
t('row without shares is empty, no throw',v[0].empty&&v[1].empty&&!v[0].off);
t('undefined input: empty list',shareStackModel(undefined,K).length===0);
v=shareStackModel([{label:'u',sub:'n=3',color:'#f00',shares:{a:100}}],K)[0];
t('extra row fields pass through; single 100 % segment ok',v.sub==='n=3'&&v.color==='#f00'&&!v.off&&v.segs[0].x1===100);

let d=dumbbellModel([{label:'x',vals:{w:3,s:5}}],['w','s']);
t('two dots: span 3..5, axis includes zero',d.rows[0].lo===3&&d.rows[0].hi===5&&d.min===0&&d.max>=5);
t('ticks 0..6 step 1 or 2 (nice)',d.ticks[0]===0&&d.ticks[d.ticks.length-1]>=5,JSON.stringify(d.ticks));
d=dumbbellModel([{label:'x',vals:{w:3,s:null,c:'y'}}],['w','s','c']);
t('missing values skipped; single dot has no span',d.rows[0].pts.length===1&&d.rows[0].lo===null&&d.rows[0].hi===null);
d=dumbbellModel([{label:'x',vals:{w:-2,s:1.5}}],['w','s']);
t('negative values: axis spans them and zero',d.min<=-2&&d.max>=1.5&&d.ticks.includes(0));
d=dumbbellModel([{label:'x',vals:{w:0.12,s:0.3}}],['w','s']);
t('small values: no float noise in ticks',d.ticks.every(x=>Math.abs(x*100-Math.round(x*100))<1e-9),JSON.stringify(d.ticks));
d=dumbbellModel([{label:'x'}],['w']); t('row without values: no points, finite axis',d.rows[0].pts.length===0&&isFinite(d.min)&&isFinite(d.max));
d=dumbbellModel(undefined,['w']); t('undefined input: no rows, no throw',d.rows.length===0);
d=dumbbellModel([{label:'x',valueText:'+1.00',vals:{w:1}}],['w']); t('extra fields pass through',d.rows[0].valueText==='+1.00');

d=dumbbellModel([{label:'x',vals:{w:3,s:5,c:9}}],['w','s','c'],['w','s']);
t('span covers only the span keys; the third dot is kept but outside the span',d.rows[0].lo===3&&d.rows[0].hi===5&&d.rows[0].pts.length===3&&d.max>=9);
d=dumbbellModel([{label:'x',vals:{w:3,c:9}}],['w','s','c'],['w','s']);
t('span needs two span-key values: one is not a span',d.rows[0].lo===null);
console.log(f?'SHARE CHARTS TEST FAILED':'SHARE CHARTS TEST PASSED'); process.exit(f?1:0);
