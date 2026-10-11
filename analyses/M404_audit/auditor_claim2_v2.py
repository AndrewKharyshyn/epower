import warnings, json; warnings.filterwarnings("ignore")
src=open("analyses/M404_audit/auditor_impl.py",encoding="utf-8").read().split("c1,c2,D=claim12")[0]
exec(src)
M=m.sort_values("dt0",kind="stable").reset_index(drop=True)
def run(cap):
    J=[];Q=[]
    for k in range(len(M)-1):
        i,j=M.iloc[k],M.iloc[k+1]
        if i.ens_outlier_v2!="False" or j.ens_outlier_v2!="False": continue
        if pd.isna(i.soc_end) or pd.isna(j.soc_start) or pd.isna(i.duration_s): continue
        if i.file not in cache or cache[i.file][1] is None or len(cache[i.file][1][0])<2: continue
        rest=(j.dt0-(i.dt0+pd.Timedelta(seconds=i.duration_s))).total_seconds()
        if rest<30: continue
        J.append(j.soc_start-i.soc_end); Q.append(integ(*cache[i.file][1],cap)[1])
    J=np.array(J);Q=np.array(Q); a,b=np.linalg.lstsq(np.c_[np.ones(len(Q)),Q],J,rcond=None)[0]
    return dict(b=round(b,4),a=round(a,4),n=len(J))
out={k:run(c) for k,c in (("1s",1),("2s",2),("5s",5),("none",None))}
json.dump(out,open("analyses/M404_audit/auditor_results_claim2_v2.json","w",encoding="utf-8"),indent=1)
print(json.dumps(out))
