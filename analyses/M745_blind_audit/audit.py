import pandas as pd, numpy as np, itertools, json
def load(s):
    d=pd.read_csv(f's{s}/drive_master.csv',dtype=str,usecols=['file','distance_km','gross_throughput_kwh','ens_invalid','ens_outlier_v2'])
    q=pd.read_csv(f's{s}/seasonal_drive_master.csv',dtype=str,usecols=['file','date','thermal_regime'])
    info=dict(dupD=int(d.file.duplicated().sum()),dupQ=int(q.file.duplicated().sum()))
    m=d.merge(q,on='file',how='inner')
    info['nD']=len(d);info['nQ']=len(q);info['nM']=len(m)
    ex=lambda c:m[c].fillna('').str.strip().str.lower()=='true'
    m['kwh']=pd.to_numeric(m.gross_throughput_kwh,errors='coerce');m['km']=pd.to_numeric(m.distance_km,errors='coerce')
    e=m[(m.thermal_regime=='shoulder')&~ex('ens_invalid')&~ex('ens_outlier_v2')&m.kwh.notna()&m.km.notna()&(m.km>0)]
    return e.set_index('file'),info
e0,i0=load(0);e1,i1=load(1);print(i0,i1)
V=lambda k,m:100*k/m
for e in(e0,e1):print(len(e),e.km.sum(),V(e.kwh.sum(),e.km.sum()))
C=e0.index.intersection(e1.index);A=e1.index.difference(e0.index);R=e0.index.difference(e1.index)
print(len(C),len(A),len(R))
print('C identical',np.allclose(e0.loc[C,['kwh','km']].values.astype(float),e1.loc[C,['kwh','km']].values.astype(float)),'date mismatch',(e0.loc[C,'date']!=e1.loc[C,'date']).sum())
a=e1.loc[A];print('A',V(a.kwh.sum(),a.km.sum()),a.km.sum(),a.km.sum()/e1.km.sum())
# per-drive table
T=pd.concat([e0.loc[C,['kwh','km','date']],e1.loc[A,['kwh','km','date']],e0.loc[R,['kwh','km','date']]])
grp=['C']*len(C)+['A']*len(A)+['R']*len(R);T['g']=grp
T0=e0.loc[C,['kwh','km']].astype(float);T1=e1.loc[C,['kwh','km']].astype(float)
days=sorted(T.date.unique());print('days',len(days))
di={d:i for i,d in enumerate(days)}
def cell(vals,w):  # vals: list of (kwh,km,date) arrays
    pass
def arrs(df):return df.kwh.values.astype(float),df.km.values.astype(float),df.date.map(di).values
G=len(days)
parts={'C0':arrs(e0.loc[C]),'C1':arrs(e1.loc[C]),'R':arrs(e0.loc[R]),'A':arrs(e1.loc[A])}
def Vcell(sel,w):
    k=m_=0
    for p in sel:
        kk,mm,dd=parts[p];k=k+(kk*w[dd]).sum();m_=m_+(mm*w[dd]).sum()
    return 100*k/m_
def stats(w):
    v0=Vcell(['C0','R'],w);v1=Vcell(['C1','A'],w)
    # factors: f1 C values->S1, f2 remove R, f3 add A
    def Vs(f):
        sel=['C1' if f[0] else 'C0']+(['R'] if not f[1] else [])+(['A'] if f[2] else [])
        return Vcell(sel,w)
    sh=np.zeros(3)
    for o in itertools.permutations(range(3)):
        f=[0,0,0]
        for i in o:
            b=Vs(f);f[i]=1;sh[i]+=Vs(f)-b
    return v0,v1,v1-v0,sh/6
w1=np.ones(G);print('point',stats(w1))
rng=np.random.default_rng(4242);out=[]
for _ in range(4000):
    w=rng.multinomial(G,np.ones(G)/G).astype(float);s=stats(w);out.append([s[0],s[1],s[2],s[3][2]])
out=np.array(out)
for n,c in zip(['V0','V1','tot','f3'],out.T):print(n,np.nanpercentile(c,[2.5,97.5]))
kd=e1.loc[A].groupby('date').km.apply(lambda x:x.astype(float).sum()).values
print('kish',kd.sum()**2/(kd**2).sum(),len(kd))
