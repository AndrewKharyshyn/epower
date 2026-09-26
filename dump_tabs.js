// dump_tabs.js — render xtrail_dashboard.html in jsdom and write per-tab/per-mode visible text
// to tabtext/<tab>__<mode>.txt (used by the M299 semantic gate and for prose review).
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};this.port2={postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}};}
const html=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');const errs=[];
const dom=new JSDOM(html,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=(...a)=>errs.push(a.join(' '));w.console.warn=()=>{};}});
const d=dom.window.document,sleep=ms=>new Promise(r=>setTimeout(r,ms)),click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const TABS=['overview','charts','distribution','highway vs city','thermal','records','health','cross-vehicle','conclusions'];
(async()=>{await sleep(800);fs.mkdirSync('tabtext',{recursive:true});
 const btns=()=>[...d.querySelectorAll('button')];
 for(const t of TABS){click(btns().find(b=>b.textContent.trim().toLowerCase()===t));await sleep(250);
  // expand collapsibles (non-nav, non-cohort buttons that look like toggles)
  for(const b of btns().filter(b=>!TABS.includes(b.textContent.trim().toLowerCase())&&!b.hasAttribute('data-cohort-btn')&&!b.hasAttribute('data-cmp-btn')&&/▸|▶|show|expand|more|details/i.test(b.textContent)).slice(0,150)){click(b);await sleep(3);}
  await sleep(120);
  for(const m of ['all','warm','shoulder','compare']){const b=d.querySelector(`button[data-cohort-btn="${m}"]`);if(!b||b.disabled)continue;click(b);await sleep(180);
   const cl=d.getElementById('root').cloneNode(true);cl.querySelectorAll('script,style').forEach(x=>x.remove());
   fs.writeFileSync(`tabtext/${t.replace(/ /g,'_')}__${m}.txt`,cl.textContent);}
  const a=d.querySelector('button[data-cohort-btn="all"]');click(a);await sleep(120);}
 console.log('dumped',fs.readdirSync('tabtext').length,'files; console errors',errs.length);process.exit(0);})();
