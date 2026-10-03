import pandas as pd, numpy as np, json
R="C:/Users/AndriiKharyshyn/Downloads/X-Trail Investigation/Repo/xtrail-repo/"
d=pd.read_csv(R+"fuel_recon_master.csv")
print("rows",len(d))
drop={"20260512_195020.csv","20260813_145651.csv","20260813_150341.csv"}
m=d[~d.file.isin(drop)].copy()
cols=["generator_kWh_100","gen_to_traction_kWh_100","gen_to_batt_kWh_100","regen_to_batt_kWh_100","batt_to_traction_kWh_100","traction_gross_kWh_100"]
print("nan rows after mask", m[cols].isna().any(axis=1).sum())
print("dropped rows nan:", d[d.file.isin(drop)][cols].isna().sum().to_dict())
print("n_drives",len(m),"n_days",m.date.nunique())
W=lambda g,c:(g[c]*g.distance_km).sum()/g.distance_km.sum()
v={c:W(m,c) for c in cols}; print({k:round(x,4) for k,x in v.items()})
def stats(g):
    gen=(g.generator_kWh_100*g.distance_km).sum(); g2t=(g.gen_to_traction_kWh_100*g.distance_km).sum()
    g2b=(g.gen_to_batt_kWh_100*g.distance_km).sum(); tr=(g.traction_gross_kWh_100*g.distance_km).sum()
    return (g2t+g2b-gen)/gen, g2t/tr
ex,fg=stats(m); print("excess",ex,"fgen",fg)
print("gen resid",v["gen_to_traction_kWh_100"]+v["gen_to_batt_kWh_100"]-v["generator_kWh_100"])
print("batt resid",v["gen_to_batt_kWh_100"]+v["regen_to_batt_kWh_100"]-v["batt_to_traction_kWh_100"])
# per-day sums
m["x"]=m.distance_km
agg=pd.DataFrame({k:(m[c]*m.distance_km).groupby(m.date).sum() for k,c in zip(["gen","g2t","g2b","reg","b2t","tr"],cols)})
days=agg.index.values; A=agg.values; nd=len(days)
rng=np.random.default_rng(42); E=[];F=[]
for _ in range(4000):
    idx=rng.integers(0,nd,nd); s=A[idx].sum(0)
    E.append((s[1]+s[2]-s[0])/s[0]); F.append(s[1]/s[5])
print("excess CI",np.percentile(E,[2.5,97.5]),"fgen CI",np.percentile(F,[2.5,97.5]))
# alt: rng.choice
rng=np.random.default_rng(42); E2=[];F2=[]
for _ in range(4000):
    idx=rng.choice(nd,nd,replace=True); s=A[idx].sum(0)
    E2.append((s[1]+s[2]-s[0])/s[0]); F2.append(s[1]/s[5])
print("alt choice excess CI",np.percentile(E2,[2.5,97.5]),"fgen CI",np.percentile(F2,[2.5,97.5]))
print("mean f_gen col", m.f_gen.mean())

# Variant B: additionally drop zero-flow row with NaN f_gen (20260513_182950.csv, 20.7 km)
mb=m[m.f_gen.notna()].copy()
print("VariantB n",len(mb),"days",mb.date.nunique(),"km",mb.distance_km.sum())
vb={c:(mb[c]*mb.distance_km).sum()/mb.distance_km.sum() for c in cols}; print({k:round(x,3) for k,x in vb.items()})
print("B gen resid",vb["gen_to_traction_kWh_100"]+vb["gen_to_batt_kWh_100"]-vb["generator_kWh_100"],"batt resid",vb["gen_to_batt_kWh_100"]+vb["regen_to_batt_kWh_100"]-vb["batt_to_traction_kWh_100"])
ag=pd.DataFrame({k:(mb[c]*mb.distance_km).groupby(mb.date).sum() for k,c in zip(["gen","g2t","g2b","reg","b2t","tr"],cols)}).values
n=len(ag); rng=np.random.default_rng(42); E=[];F=[]
for _ in range(4000):
    s=ag[rng.integers(0,n,n)].sum(0); E.append((s[1]+s[2]-s[0])/s[0]); F.append(s[1]/s[5])
s=ag.sum(0); print("B excess",(s[1]+s[2]-s[0])/s[0],np.percentile(E,[2.5,97.5]),"fgen",s[1]/s[5],np.percentile(F,[2.5,97.5]))
