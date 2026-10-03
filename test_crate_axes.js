// M358 (F21.r1): known-answer test of the pure axis model crateAxisModel extracted from xtrail_summary.jsx.
const fs=require('fs');
const src=fs.readFileSync('xtrail_summary.jsx','utf8');
const m=src.match(/\/\*M358-MODEL-BEGIN\*\/([\s\S]*?)\/\*M358-MODEL-END\*\//); if(!m){console.error('FAIL: model not found');process.exit(1);}
const {crateAxisModel,crateNiceStep}=new Function(m[1]+';return {crateAxisModel,crateNiceStep};')();
let f=0; const t=(n,c)=>{ if(!c){f++;console.log('FAIL',n);} else console.log('  ok:',n); };
const pts=[[16,9.8,'city',54.9,21.0],[31,16.5,'city',96.4,35.6],[33,28.9,'city',200,null],[25,10,'mixed',null,30]];
const AXp={cPerA:{median:0.17,secondaryAxisMode:'axis'},vPackMedianCorpus:370};
const RLa={lines:[{kind:'typical',C:18,A:105,kW:38.9,n:448},{kind:'peak',C:36.4,A:213,kW:80.5,drive:'x'}]};
const C0={axis:{yMax:40},lines:[{y:18,label:'l',color:'#000',dash:'1'}]};
const A=crateAxisModel('A',pts,AXp,RLa,C0), K=crateAxisModel('kW',pts,AXp,RLa,C0), C=crateAxisModel('C',pts,AXp,RLa,C0);
t('A view plots rows with A only (null A excluded)',A.vals.length===3 && A.vals.every(x=>typeof x.v==='number'));
t('kW view excludes null-kW rows',K.vals.length===3 && !K.vals.some(x=>x.i===2));
t('kW axis bound derived from non-null kW and lines only (80.5 -> 100)',K.yMax===100 && K.step===20);
t('A axis bound covers max A 213 (-> 250)',A.yMax===250 && A.step===50 && A.ticks.join()==='0,50,100,150,200,250');
t('C view keeps the payload axis and the existing lines',C.yMax===40 && C.lines.length===1 && C.lines[0].y===18);
t('A view secondary axis is C = A x median C-per-A (monotone, in range)',A.sec.ticks.every((k,i,a)=>i===0||k.y>a[i-1].y) && A.sec.ticks.every(k=>k.y<=A.yMax+1e-9) && Math.abs(A.sec.ticks[1].y*0.17-Number(A.sec.ticks[1].label))<1e-9);
t('kW view secondary is approximate A at median voltage',/approximate/.test(K.sec.title)&&/370/.test(K.sec.title));
t('kW view has no C-rate secondary',!/C-rate/.test(K.sec.title));
t('A-view lines are in A, kW-view lines in kW',A.lines.map(l=>l.y).join()==='105,213' && K.lines.map(l=>l.y).join()==='38.9,80.5');
t('median line labelled per axis, not an operating point',/median of per-drive peaks/.test(A.lines[0].label)&&/n=448/.test(A.lines[0].label));
t('missing payload degrades without throwing',crateAxisModel('A',[],{},null,null).vals.length===0 && crateAxisModel('kW',undefined,undefined,undefined,undefined).sec===null);
t('nice step ladder',crateNiceStep(0)===1 && crateNiceStep(262)===50 && crateNiceStep(84)===20);
console.log(f?'CRATE AXES TEST FAILED':'CRATE AXES TEST PASSED'); process.exit(f?1:0);
