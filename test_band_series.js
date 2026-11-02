// M570: known-answer test of bandSeriesModel extracted from xtrail_summary.jsx (spec analyses/M570_spec.md).
const fs=require('fs');
const src=fs.readFileSync('xtrail_summary.jsx','utf8');
const m=src.match(/\/\*M570-MODEL-BEGIN\*\/([\s\S]*?)\/\*M570-MODEL-END\*\//); if(!m){console.error('FAIL: model not found');process.exit(1);}
const {bandSeriesModel}=new Function(m[1]+';return {bandSeriesModel};')();
let f=0; const t=(n,c,x)=>{ if(!c){f++;console.log('FAIL',n,x===undefined?'':x);} else console.log('  ok:',n); };
const eq=(a,b)=>JSON.stringify(a)===JSON.stringify(b);

let v=bandSeriesModel([{label:'a',pts:[{x:5,est:2,lo:1,hi:3},{x:10,est:3,lo:2,hi:4}]}]);
t('kinds interval, axis covers the intervals (1..4 -> 0..4 not forced)',v.series[0].pts.every(p=>p.kind==='interval')&&v.ymin<=1&&v.ymax>=4,v.ymin+'..'+v.ymax);
t('x range and ticks follow the data',v.xmin===5&&v.xmax===10&&eq(v.xticks.map(x=>x.x),[5,10]));
v=bandSeriesModel([{label:'a',pts:[{x:5,est:2,lo:1,hi:3}]}],{zero:true});
t('zero:true brings 0 into the axis',v.ymin===0);
v=bandSeriesModel([{label:'a',pts:[{x:1,est:-1,lo:-2,hi:0.5}]}],{ref:1});
t('ref line value is inside the axis',v.ymax>=1&&v.ymin<=-2);

v=bandSeriesModel([{label:'a',pts:[{x:1,est:0.2,lo:0.1,hi:0.3},{x:2,est:null},{x:3,est:0.5}]}],{ylim:[0,1]});
t('gap (no estimate) is kind none, point without interval is a point',v.series[0].pts[1].kind==='none'&&v.series[0].pts[2].kind==='point');
t('ylim fixes the axis at 0..1',v.ymin===0&&v.ymax===1&&v.yticks[0]===0&&v.yticks[v.yticks.length-1]===1,JSON.stringify(v.yticks));
t('a gap does not create an x tick',eq(v.xticks.map(x=>x.x),[1,3]));

v=bandSeriesModel([{label:'a',pts:[{x:0,est:1,lo:0,hi:2},{x:-5,est:1},{x:5,est:2,lo:1,hi:3},{x:120,est:4,lo:3,hi:5}]}],{xlog:true});
t('log axis drops x <= 0 (kind none), keeps the others',v.series[0].pts[0].kind==='none'&&v.series[0].pts[1].kind==='none'&&v.series[0].pts[2].kind==='interval');
t('log axis domain is 5..120',v.xmin===5&&v.xmax===120);

v=bandSeriesModel([{label:'a',pts:[{x:600,est:0.4,lo:0.3,hi:0.5,bound:[0.1,0.9]}]}],{ylim:[0,1]});
t('bound kept and never turned into an interval',v.series[0].pts[0].bound[1]===0.9&&v.series[0].pts[0].kind==='interval');
v=bandSeriesModel([{label:'a',pts:[{x:600,est:0.4,bound:[0.1,0.9]}]}]);
t('bound widens the axis',v.ymin<=0.1&&v.ymax>=0.9);
v=bandSeriesModel([{label:'a',pts:[{x:600,est:null,bound:[0.1,0.9]}]}]);
t('bound alone (no estimate) is kept, point is none',v.series[0].pts[0].kind==='none'&&v.series[0].pts[0].bound!==null);
v=bandSeriesModel([{label:'a',pts:[{x:600,est:0.4,bound:[0.9,0.1]}]}]);
t('inverted bound is rejected',v.series[0].pts[0].bound===null);

v=bandSeriesModel([{label:'a',pts:[{x:1,est:5,lo:6,hi:7}]}]);
t('estimate outside its interval: point, axis not widened by it',v.series[0].pts[0].kind==='point'&&v.ymax<7,String(v.ymax));
v=bandSeriesModel([{label:'a',pts:[{x:3,est:5,lo:4,hi:6}]}]);
t('single x: finite domain',v.xmin<3&&v.xmax>3);
v=bandSeriesModel([{label:'a',pts:[{x:3,est:5,lo:4,hi:6}]}],{xlog:true});
t('single x on log axis: finite positive domain',v.xmin>0&&v.xmin<3&&v.xmax>3);
v=bandSeriesModel([{label:'a',pts:[{x:1,est:1,xl:'Sep'}]},{label:'b',pts:[{x:1,est:2,lo:1,hi:3}]}]);
t('two series share the x tick; label comes from xl',v.xticks.length===1&&v.xticks[0].label==='Sep');
v=bandSeriesModel(undefined); t('undefined input: no series, no throw',v.series.length===0&&v.xticks.length===0);
v=bandSeriesModel([{label:'a',pts:[]}]); t('empty series: default axes finite',isFinite(v.ymin)&&isFinite(v.ymax)&&v.xmax>v.xmin);
v=bandSeriesModel([{label:'a',dash:'3 3',color:'#f00',pts:[{x:1,est:1,hollow:true}]}]);
t('extra fields pass through',v.series[0].dash==='3 3'&&v.series[0].color==='#f00'&&v.series[0].pts[0].hollow===true);

console.log(f?'BAND SERIES TEST FAILED':'BAND SERIES TEST PASSED'); process.exit(f?1:0);
