import sys, json, copy, tempfile, os, subprocess
sys.path.insert(0,'tools'); sys.path.insert(0,'.')
import numpy as np, pandas as pd
import m573_cell_spread_step as M
rng=np.random.default_rng(1)
PRE={}
def mk(days_post, per=3, tpost=20.0, pre_days=60):
    rows=[]
    rng=np.random.default_rng(1)
    for i in range(pre_days):
        for k in range(3):
            rows.append((pd.Timestamp('2026-07-01')+pd.Timedelta(days=i), 10+rng.uniform(0,30), 100+rng.normal()*10, 60+rng.normal()*3))
    rng=np.random.default_rng(2)
    for i in range(days_post):
        for k in range(per):
            rows.append((pd.Timestamp('2026-10-18')+pd.Timedelta(days=i), tpost+rng.uniform(0,5), 100+rng.normal()*10, 60+rng.normal()*3))
    d=pd.DataFrame(rows,columns=['date','T','I','soc'])
    d['y']=20+0.3*d['T']+0.05*d['I']+np.random.default_rng(5).normal(size=5000)[:len(d)]
    d['day']=d.date.dt.strftime('%Y-%m-%d'); d['months']=(d.date-d.date.min()).dt.days/30.4375
    return d
tmp=tempfile.mkdtemp(); L=os.path.join(tmp,'l.json'); spec=os.path.join(tmp,'s.md'); open(spec,'w').write('x')
def look(d,md5,**k):
    c=M.confirmatory(d); c2,led=M.apply_looks(c,d,md5,path=L,spec_path=spec); return c2,led
d=mk(6)
c,l=look(d,'A'); print('A',c['evaluationNumber'],c['lookLabel'])
c,l=look(d,'A'); print('A again',c['evaluationNumber'],len(l['looks']))
d2=mk(8); c,l=look(d2,'B'); print('B',c['evaluationNumber'],c['lookLabel'], c['terminalEvaluation']['status'])
# terminal: 10 days x3 = 30 in-range drives; D = day 10 (>=20 and >=10 days)
d3=mk(14); c,l=look(d3,'C'); t=l['terminal']; print('C',c['evaluationNumber'],c['lookLabel'],t['D'],t['dataThrough'],t['n'],t['days'],t['evaluationNumber'])
frozen=json.dumps(t,sort_keys=True)
d4=mk(20); c,l=look(d4,'D'); print('D',c['evaluationNumber'],c['lookLabel'],json.dumps(l['terminal'],sort_keys=True)==frozen)
c,l=look(d3,'C'); print('C rerun',c['evaluationNumber'],c['lookLabel'])
# fallback
os.remove(L)
dd=mk(5,per=3); 
# extend to 2027-01-31 with sparse out-of-range
extra=pd.DataFrame({'date':[pd.Timestamp('2027-01-31'),pd.Timestamp('2027-02-03')],'T':[60.,60.],'I':[100.,100.],'soc':[60.,60.],'y':[50.,50.]})
extra['day']=extra.date.dt.strftime('%Y-%m-%d'); extra['months']=(extra.date-dd.date.min()).dt.days/30.4375
dfb=pd.concat([dd,extra],ignore_index=True)
c,l=look(dd,'E'); print('E pre-fallback', l['terminal'])
c,l=look(dfb,'F'); t=l['terminal']; print('F fallback',t and (t['how'],t['dataThrough'],t['n'],t['days']))
# fallback must not apply if primary exists
os.remove(L); c,l=look(mk(14),'G'); print('primary how',l['terminal']['how'])
# d) changed fit
dchg=mk(6,pre_days=61)
try: look(dchg,'H'); print('NO STOP')
except SystemExit as e: print('stop:',str(e)[:60])
