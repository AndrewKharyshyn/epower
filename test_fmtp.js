// M351 (p23.16): known-answer test of the single p-value formatter fmtP extracted from xtrail_summary.jsx.
const fs=require('fs');
const src=fs.readFileSync('xtrail_summary.jsx','utf8');
const m=src.match(/function fmtP\(p\)\{[^\n]*\}/); if(!m){console.error('FAIL: fmtP not found');process.exit(1);}
const fmtP=new Function(m[0]+';return fmtP;')();
const cases=[[0,'p<0.001'],[0.0,'p<0.001'],[0.0004,'p<0.001'],[0.00099,'p<0.001'],[0.001,'p=0.0010'],[0.0034,'p=0.0034'],[0.2522,'p=0.2522'],[1,'p=1.0000'],[null,'p n/a'],[undefined,'p n/a'],[NaN,'p n/a'],['x','p n/a']];
let f=0; for(const [i,o] of cases){ const r=fmtP(i); if(r!==o){f++;console.log('FAIL',String(i),'->',r,'expected',o);} else console.log('  ok:',String(i),'->',r); }
if(/p=0(\.0*)?['"` ]/.test(src.split('\n').filter(l=>l.includes('fmtP(')).join('\n'))) { f++; console.log('FAIL: literal p=0 near fmtP use'); }
console.log(f?'FMTP TEST FAILED':'FMTP TEST PASSED'); process.exit(f?1:0);
