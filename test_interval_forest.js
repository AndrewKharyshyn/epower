// M569: known-answer test of intervalForestModel extracted from xtrail_summary.jsx (spec analyses/M569_spec.md).
const fs=require('fs');
const src=fs.readFileSync('xtrail_summary.jsx','utf8');
const m=src.match(/\/\*M569-MODEL-BEGIN\*\/([\s\S]*?)\/\*M569-MODEL-END\*\//); if(!m){console.error('FAIL: model not found');process.exit(1);}
const {intervalForestModel}=new Function(m[1]+';return {intervalForestModel};')();
let f=0; const t=(n,c,x)=>{ if(!c){f++;console.log('FAIL',n,x===undefined?'':x);} else console.log('  ok:',n); };
const eq=(a,b)=>JSON.stringify(a)===JSON.stringify(b);

let v=intervalForestModel([{label:'a',est:2,lo:1,hi:3}]);
t('positive interval: axis reaches zero, ticks 0..3 step 1',v.min===0&&v.max===3&&eq(v.ticks,[0,1,2,3]),JSON.stringify(v.ticks));
t('kind interval',v.rows[0].kind==='interval');

v=intervalForestModel([{label:'a',est:-1,lo:-2.5,hi:0.5},{label:'b',est:1,lo:-0.5,hi:4}]);
t('mixed sign: ticks -4..4 step 2',eq(v.ticks,[-4,-2,0,2,4]),JSON.stringify(v.ticks));
t('axis min/max equal first/last tick',v.min===-4&&v.max===4);

v=intervalForestModel([{label:'a',est:0.12,lo:0.1,hi:0.14}]);
t('small values: no float noise in ticks',v.ticks.every(x=>Math.abs(x*100-Math.round(x*100))<1e-9),JSON.stringify(v.ticks));
t('small values: axis includes zero and the upper limit',v.min===0&&v.max>=0.14);

v=intervalForestModel([{label:'a',est:10,lo:8,hi:12}],{zero:false});
t('zero:false keeps the axis on the data (8..12)',v.min>=8&&v.min<10&&v.max>=12&&v.max<=14,v.min+'..'+v.max);

v=intervalForestModel([{label:'p',est:3},{label:'q',est:3,lo:4,hi:5},{label:'r',est:3,lo:1}]);
t('estimate without interval is a point',v.rows[0].kind==='point');
t('estimate outside its interval is a point, interval not drawn',v.rows[1].kind==='point');
t('half interval is a point',v.rows[2].kind==='point');
t('invalid interval does not widen the axis',v.max<=4,String(v.max));

v=intervalForestModel([{label:'n',note:'not evaluable'},{label:'m',est:null,lo:1,hi:2},{label:'s',est:'x'}]);
t('no estimate: kind none, note kept',v.rows[0].kind==='none'&&v.rows[0].note==='not evaluable');
t('null / string estimate: none',v.rows[1].kind==='none'&&v.rows[2].kind==='none');
t('all none: default axis 0..1',v.min===0&&v.max===1);

v=intervalForestModel([{label:'a',est:5,lo:5,hi:5}]);
t('degenerate interval: finite axis, zero included',isFinite(v.min)&&isFinite(v.max)&&v.min<=0&&v.max>=5);

v=intervalForestModel(undefined); t('undefined input: empty rows, no throw',v.rows.length===0);
v=intervalForestModel([{label:'a',est:1,lo:0,hi:2,color:'#f00',muted:true,sub:'n'}]);
t('extra row fields pass through',v.rows[0].color==='#f00'&&v.rows[0].muted===true&&v.rows[0].sub==='n');
v=intervalForestModel([{label:'a',est:100,lo:90,hi:120}]);
t('large values: step 50, ticks 0..150',eq(v.ticks,[0,50,100,150]),JSON.stringify(v.ticks));

v=intervalForestModel([{label:'r',lo:1,hi:3,range:true},{label:'n',lo:1,hi:3}]);
t('interval-only row is a range only when flagged',v.rows[0].kind==='range'&&v.rows[1].kind==='none');
t('range widens the axis',v.max>=3);
v=intervalForestModel([{label:'r',lo:3,hi:1,range:true}]);
t('inverted range is rejected',v.rows[0].kind==='none');
v=intervalForestModel([{label:'r',est:2,lo:1,hi:3,range:true}]);
t('an estimate wins over the range flag',v.rows[0].kind==='interval');
v=intervalForestModel([{label:'a',est:1.2,lo:0.9,hi:1.6}],{zero:false,ref:1});
t('ref inside the axis; zero:false keeps zero out',v.min>0&&v.min<=0.9&&v.max>=1.6);
v=intervalForestModel([{label:'a',est:5,lo:4,hi:6}],{zero:false,ref:1});
t('a ref outside the data widens the axis to include it',v.min<=1&&v.max>=6);
console.log(f?'INTERVAL FOREST TEST FAILED':'INTERVAL FOREST TEST PASSED'); process.exit(f?1:0);
