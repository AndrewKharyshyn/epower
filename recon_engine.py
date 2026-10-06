import pandas as pd, numpy as np, warnings, json
warnings.filterwarnings('ignore')
import model_constants as MC

import os
BASE=(os.environ.get('XT_RAW_DIR') or '/mnt/project').rstrip('/')+'/'   # M306: env-aware (unset -> legacy path, unchanged behaviour)
CH = {
 'I':'[BMS] HV Battery Current (A)','V':'[BMS] HV Battery voltage (V)','soc':'[BMS] HV State of charge (%)',
 'speed':'Швидкість автомобіля (km/h)','rpm':'Оберти двигуна (rpm)',
 'flow':'Витрати палива (L/h)','used':'Використане паливо (L)',
 'coolant':'Температура охолодної рідини (℃)','boost':'Розрахунковий наддув (bar)',
 'dist':'Пройдений шлях (km)','load':'Розрахункове значення навантаження на двигун (%)',
 'oil':'Температура олії у двигуні (℃)',
}
DT_CAP=5.0

def _ser(df,t,c):
    if c not in df.columns: return None
    v=pd.to_numeric(df[c],errors='coerce'); m=v.notna().values
    if not m.any(): return None
    return pd.DataFrame({'t':t.values[m],'v':v.values[m]}).sort_values('t').reset_index(drop=True)

_USECOLS=set(CH.values())|{'time'}

def _parse_time(s):
    """M383 (audit F21): explicit-format fast path for HH:MM:SS.fraction; any other form (or a malformed row) falls back to the original
    format-inferring parse for the whole column. The inferring parse dates a time-only string TODAY, and consumers combine this series with their
    own pd.to_datetime(df['time']) result (tools/fuel_analytics2.load_trip windows on both), so the fast path is moved to the same date:
    absolute equality with the original parse is required, not only equal differences (M384: the first M383 version missed this)."""
    try:
        t = pd.to_datetime(s, format='%H:%M:%S.%f', errors='raise')
    except (ValueError, TypeError):
        return pd.to_datetime(s, errors='coerce')
    return t + (pd.Timestamp.now().normalize() - pd.Timestamp('1900-01-01'))

def load_drive(f, offset_A):
    df=pd.read_csv(BASE+f, low_memory=False, usecols=lambda c: c in _USECOLS)   # M383: only the channels this module reads
    t=_parse_time(df['time'])
    flow=_ser(df,t,CH['flow'])
    if flow is None or len(flow)<10: return None
    g=flow.rename(columns={'v':'flow'})
    for k in ['rpm','V','I','soc','speed','coolant','boost','used','dist','load','oil']:
        s=_ser(df,t,CH[k])
        if s is None:
            g[k]=np.nan
        else:
            g=pd.merge_asof(g, s.rename(columns={'v':k}), on='t', direction='nearest',
                            tolerance=pd.Timedelta('1500ms'))
    g['dt']=g['t'].diff().dt.total_seconds().clip(upper=DT_CAP).fillna(0.0)
    # battery power kW, discharge-positive, offset applied.
    # M265 SIGN FIX: raw BMS current '[BMS] HV Battery Current (A)' is
    # charge-positive (main pipeline: compute_drive_summary_v6.py:1317,1534,
    # "M11: BMS current is charge-positive"). Discharge-positive current is
    # therefore -I_raw. The M13 SoC-anchored offset is estimated in the
    # discharge-positive frame (net_draw_corr = net_draw - I_off*V*h), so the
    # correct per-sample discharge-positive expression is Id,adj = -I_raw - I_off.
    # Prior code used +I_raw - I_off, which reversed the temporal discharge/
    # charge phase; per-drive anchoring to master gross totals then preserved
    # aggregate energy while leaving the phase wrong, so the §4b headline looked
    # reconciled but was physically inverted. See CHANGELOG M265.
    g['Iadj']=-g['I']-offset_A
    g['Pbatt']=g['V']*g['Iadj']/1000.0     # kW, +discharge
    # engine-on + since-start
    on=(g['rpm'].fillna(0)>400).values
    tt=(g['t']-g['t'].iloc[0]).dt.total_seconds().values
    # M383 (audit F21): vectorised time since the start of the current engine-on run (1e9 while off); identical to the former per-row loop
    n=len(g); idx=np.arange(n)
    start=on & ~np.concatenate(([False], on[:-1]))
    last=np.maximum.accumulate(np.where(start, idx, 0))
    ss=np.where(on, tt-tt[last], 1e9)
    g['since_start']=ss
    g['on']=on
    return g

def precompute(g):
    """Regime partition + per-regime fuel-VOLUME (L) sums (central geometry, MC-independent)."""
    on=g['on'].values & (g['flow'].fillna(0).values>0)
    dt=g['dt'].values
    vol_L = g['flow'].fillna(0).values/3600.0*dt      # L per sample (flow in L/h)
    reg=MC.classify_regime(g['rpm'].values, g['coolant'].values, g['since_start'].values, g['boost'].values)
    cold=MC.cold_mask(g['coolant'].values, g['since_start'].values, g.get('oil',pd.Series(np.nan,index=g.index)).values)
    reg=reg.copy(); reg[~on]='OFF'
    out={'reg':reg,'cold':cold,'vol_L':vol_L,'dt':dt,'on':on,
         'Pbatt':g['Pbatt'].values,'flow':g['flow'].fillna(0).values,
         'soc':g['soc'].values}
    # per-regime, cold/warm split volume totals
    tot={}
    for r in ['OPT','NEAR','SEC','LOW','HIGH']:
        for cflag,cname in [(False,'warm'),(True,'cold')]:
            msk = on & (reg==r) & (cold==cflag)
            tot[(r,cname)] = float(vol_L[msk].sum())
    out['vol_by_regime']=tot
    out['vol_total']=float(vol_L[on].sum())
    # distance
    d=g['dist'].dropna()
    out['dist_km']=float(d.iloc[-1]-d.iloc[0]) if len(d)>2 else np.nan
    u=g['used'].dropna()
    out['fuel_used_L']=float(u.iloc[-1]-u.iloc[0]) if len(u)>2 else np.nan
    s=g['soc'].dropna()
    out['dsoc']=float(s.iloc[-1]-s.iloc[0]) if len(s)>2 else np.nan
    return out

def central_estimate(pc, scen='central'):
    """Deterministic central reconstruction for one drive (kWh)."""
    rho=MC.RHO_G_PER_L[0]; lhv=MC.LHV_MJ_PER_KG[0]/3.6/1000.0  # kWh/g
    sc=MC.SCEN[scen]
    egen_gpe=MC.ETA_GEN[0]*MC.ETA_PE[0]
    paux=MC.P_AUX_KW[0]
    # fuel chemical
    m_tot=pc['vol_total']*rho
    E_fuel=m_tot*lhv
    # engine brake via regime BSFC
    E_eng=0.0
    for r in ['OPT','NEAR','SEC','LOW','HIGH']:
        b=max(MC.BSFC[r][0]*sc, MC.BSFC_FLOOR)
        E_eng += (pc['vol_by_regime'][(r,'warm')]*rho)/b
        bc=max(b*MC.COLD_MULT[0], MC.BSFC_FLOOR)
        E_eng += (pc['vol_by_regime'][(r,'cold')]*rho)/bc
    E_gen=E_eng*egen_gpe
    # instantaneous P_gen(t): distribute regime BSFC back to samples
    reg=pc['reg']; cold=pc['cold']; vol=pc['vol_L']; dt=pc['dt']; on=pc['on']
    bsfc_t=np.full(len(reg), np.nan)
    for r in ['OPT','NEAR','SEC','LOW','HIGH']:
        b=max(MC.BSFC[r][0]*sc, MC.BSFC_FLOOR)
        bsfc_t[(reg==r)&(~cold)]=b
        bsfc_t[(reg==r)&(cold)]=max(b*MC.COLD_MULT[0], MC.BSFC_FLOOR)
    Peng_t=np.zeros(len(reg))
    good=on & np.isfinite(bsfc_t) & (dt>0)
    Peng_t[good]=(pc['flow'][good]*rho/3600.0)/bsfc_t[good]*3600.0  # kW = (g/s)/(g/kWh)*3600
    Pgen_t=Peng_t*egen_gpe
    Pbatt=np.nan_to_num(pc['Pbatt'])
    Ptrac=Pgen_t+Pbatt-paux
    E_trac_gross=float(np.sum(np.maximum(Ptrac,0.0)*dt)/3600.0)
    E_gen_to_trac=float(np.sum(np.minimum(Pgen_t, np.maximum(Ptrac,0.0))*dt)/3600.0)
    E_batt_dis=float(np.sum(np.maximum(Pbatt,0.0)*dt)/3600.0)
    E_batt_chg=float(np.sum(np.maximum(-Pbatt,0.0)*dt)/3600.0)
    # gen->battery vs regen->battery: charging while engine on & not decel(regen)
    # regen proxy: charging while flow~0 (engine off) OR speed decreasing; use engine-off charge as regen-ish
    chg = np.maximum(-Pbatt,0.0)
    eng_on = on
    E_gen_to_batt=float(np.sum(chg[eng_on]*dt[eng_on])/3600.0)
    E_regen_to_batt=float(np.sum(chg[~eng_on]*dt[~eng_on])/3600.0)
    E_batt_to_trac=max(E_trac_gross-E_gen_to_trac,0.0)
    return dict(E_fuel=E_fuel,E_eng=E_eng,E_gen=E_gen,E_trac_gross=E_trac_gross,
                E_gen_to_trac=E_gen_to_trac,E_batt_to_trac=E_batt_to_trac,
                E_batt_dis=E_batt_dis,E_batt_chg=E_batt_chg,
                E_gen_to_batt=E_gen_to_batt,E_regen_to_batt=E_regen_to_batt,
                eta_eng=E_eng/E_fuel if E_fuel>0 else np.nan,
                eta_fuel_bus=E_gen/E_fuel if E_fuel>0 else np.nan,
                f_gen=E_gen_to_trac/E_trac_gross if E_trac_gross>0 else np.nan)

if __name__=='__main__':
    import sys
    m=pd.read_csv(BASE+'drive_master.csv')[['file','I_offset_A_applied','distance_km','drive_type','date',
        'gross_discharge_kwh','gross_charge_kwh','soc_start','soc_end']]
    H=pd.read_csv('header_scan.csv')
    fi=H[H['fuel_Lh']==True]['file'].tolist()
    off=dict(zip(m['file'],m['I_offset_A_applied'].fillna(0.0)))
    # validate battery integration vs master on 3 drives + show central for a few
    test=fi[:6]
    for f in test:
        g=load_drive(f, off.get(f,0.0))
        if g is None: print(f,'skip'); continue
        pc=precompute(g); ce=central_estimate(pc)
        mm=m[m['file']==f].iloc[0]
        print(f'{f}  dist={pc["dist_km"]:.1f}km fuel={pc["fuel_used_L"]:.2f}L dSoC={pc["dsoc"]:.1f}pp')
        print(f'   E_fuel={ce["E_fuel"]:.3f}  E_eng={ce["E_eng"]:.3f} (eta_eng={ce["eta_eng"]:.3f})  E_gen={ce["E_gen"]:.3f}')
        print(f'   E_trac_gross={ce["E_trac_gross"]:.3f}  gen->trac={ce["E_gen_to_trac"]:.3f} batt->trac={ce["E_batt_to_trac"]:.3f}  f_gen={ce["f_gen"]:.2f}')
        print(f'   batt_dis(recon)={ce["E_batt_dis"]:.3f} vs master gross_dis={mm["gross_discharge_kwh"]:.3f} | batt_chg(recon)={ce["E_batt_chg"]:.3f} vs master gross_chg={mm["gross_charge_kwh"]:.3f}')

def central_estimate_v2(pc, mrow, scen='central'):
    """v2: battery dis/chg anchored to authoritative master energies; regen/gen charge split from master M12."""
    rho=MC.RHO_G_PER_L[0]; lhv=MC.LHV_MJ_PER_KG[0]/3.6/1000.0
    sc=MC.SCEN[scen]; egen_gpe=MC.ETA_GEN[0]*MC.ETA_PE[0]; paux=MC.P_AUX_KW[0]
    m_tot=pc['vol_total']*rho; E_fuel=m_tot*lhv
    reg=pc['reg']; cold=pc['cold']; dt=pc['dt']; on=pc['on']
    bsfc_t=np.full(len(reg),np.nan); coldfuel=0.0; totfuel=pc['vol_total']*rho
    E_eng=0.0
    for r in ['OPT','NEAR','SEC','LOW','HIGH']:
        b=max(MC.BSFC[r][0]*sc,MC.BSFC_FLOOR); bc=max(b*MC.COLD_MULT[0],MC.BSFC_FLOOR)
        bsfc_t[(reg==r)&(~cold)]=b; bsfc_t[(reg==r)&(cold)]=bc
        E_eng+=(pc['vol_by_regime'][(r,'warm')]*rho)/b+(pc['vol_by_regime'][(r,'cold')]*rho)/bc
        coldfuel+=pc['vol_by_regime'][(r,'cold')]*rho
    E_gen=E_eng*egen_gpe
    Peng_t=np.zeros(len(reg)); good=on&np.isfinite(bsfc_t)&(dt>0)
    Peng_t[good]=(pc['flow'][good]*rho/3600.0)/bsfc_t[good]*3600.0
    Pgen_t=Peng_t*egen_gpe
    # battery: anchor dis/chg to master
    Pbatt=np.nan_to_num(pc['Pbatt'])
    dis=np.maximum(Pbatt,0.0); chg=np.maximum(-Pbatt,0.0)
    E_dis_raw=float(np.sum(dis*dt)/3600.0); E_chg_raw=float(np.sum(chg*dt)/3600.0)
    md=mrow['gross_discharge_kwh']; mc_=mrow['gross_charge_kwh']
    kd=(md/E_dis_raw) if (E_dis_raw>1e-6 and md==md and md>0) else 1.0
    kc=(mc_/E_chg_raw) if (E_chg_raw>1e-6 and mc_==mc_ and mc_>0) else 1.0
    Pbatt_anch=dis*kd - chg*kc
    Ptrac=Pgen_t+Pbatt_anch-paux
    E_trac_gross=float(np.sum(np.maximum(Ptrac,0.0)*dt)/3600.0)
    E_trac_regen=float(np.sum(np.maximum(-Ptrac,0.0)*dt)/3600.0)  # bus energy returned by traction
    E_gen_to_trac=float(np.sum(np.minimum(Pgen_t,np.maximum(Ptrac,0.0))*dt)/3600.0)
    E_batt_dis=float(np.sum(np.maximum(Pbatt_anch,0)*dt)/3600.0)
    E_batt_chg=float(np.sum(np.maximum(-Pbatt_anch,0)*dt)/3600.0)
    regen_to_batt=mrow.get('charge_pure_regen_kwh',np.nan)
    gen_to_batt=(mrow.get('charge_eng_only_kwh',0) or 0)+(mrow.get('charge_dual_kwh',0) or 0)
    E_batt_to_trac=max(E_trac_gross-E_gen_to_trac,0.0)
    return dict(E_fuel=E_fuel,E_eng=E_eng,E_gen=E_gen,E_trac_gross=E_trac_gross,E_trac_regen=E_trac_regen,
        E_gen_to_trac=E_gen_to_trac,E_batt_to_trac=E_batt_to_trac,E_batt_dis=E_batt_dis,E_batt_chg=E_batt_chg,
        regen_to_batt=regen_to_batt,gen_to_batt=gen_to_batt,cold_fuel_frac=coldfuel/totfuel if totfuel>0 else np.nan,
        eta_eng=E_eng/E_fuel if E_fuel>0 else np.nan, eta_fuel_bus=E_gen/E_fuel if E_fuel>0 else np.nan,
        f_gen=E_gen_to_trac/E_trac_gross if E_trac_gross>0 else np.nan)


def central_estimate_v2_persample(pc, mrow, scen='central'):
    """M255 (2026-09-14): per-sample variant of central_estimate_v2, for the
    speed-binned "Traction supply split by vehicle speed" sub-analysis
    (generatorTractionRecon.speedSplit -- lost with no surviving generating
    code as of M253; rebuilt here). The aggregate math is copy-identical to
    central_estimate_v2 line for line -- nothing is recomputed differently --
    so summing this function's per-sample Ptrac/Pgen_t/Pbatt_anch/dt arrays
    must reproduce central_estimate_v2's own E_trac_gross/E_gen_to_trac/
    E_batt_to_trac for the same (pc, mrow) to within float rounding; that
    equivalence is asserted in speed_split.py before any speed-binned output
    is trusted. Returns (aggregate_dict, persample_dict) where persample_dict
    carries the same-length arrays 'Ptrac','Pgen_t','Pbatt_anch','dt' -- NOT
    speed, which lives on the caller's own `g` frame (same row order, since
    pc's arrays are taken directly from g's columns without reordering)."""
    rho=MC.RHO_G_PER_L[0]; lhv=MC.LHV_MJ_PER_KG[0]/3.6/1000.0
    sc=MC.SCEN[scen]; egen_gpe=MC.ETA_GEN[0]*MC.ETA_PE[0]; paux=MC.P_AUX_KW[0]
    m_tot=pc['vol_total']*rho; E_fuel=m_tot*lhv
    reg=pc['reg']; cold=pc['cold']; dt=pc['dt']; on=pc['on']
    bsfc_t=np.full(len(reg),np.nan); coldfuel=0.0; totfuel=pc['vol_total']*rho
    E_eng=0.0
    for r in ['OPT','NEAR','SEC','LOW','HIGH']:
        b=max(MC.BSFC[r][0]*sc,MC.BSFC_FLOOR); bc=max(b*MC.COLD_MULT[0],MC.BSFC_FLOOR)
        bsfc_t[(reg==r)&(~cold)]=b; bsfc_t[(reg==r)&(cold)]=bc
        E_eng+=(pc['vol_by_regime'][(r,'warm')]*rho)/b+(pc['vol_by_regime'][(r,'cold')]*rho)/bc
        coldfuel+=pc['vol_by_regime'][(r,'cold')]*rho
    E_gen=E_eng*egen_gpe
    Peng_t=np.zeros(len(reg)); good=on&np.isfinite(bsfc_t)&(dt>0)
    Peng_t[good]=(pc['flow'][good]*rho/3600.0)/bsfc_t[good]*3600.0
    Pgen_t=Peng_t*egen_gpe
    Pbatt=np.nan_to_num(pc['Pbatt'])
    dis=np.maximum(Pbatt,0.0); chg=np.maximum(-Pbatt,0.0)
    E_dis_raw=float(np.sum(dis*dt)/3600.0); E_chg_raw=float(np.sum(chg*dt)/3600.0)
    md=mrow['gross_discharge_kwh']; mc_=mrow['gross_charge_kwh']
    kd=(md/E_dis_raw) if (E_dis_raw>1e-6 and md==md and md>0) else 1.0
    kc=(mc_/E_chg_raw) if (E_chg_raw>1e-6 and mc_==mc_ and mc_>0) else 1.0
    Pbatt_anch=dis*kd - chg*kc
    Ptrac=Pgen_t+Pbatt_anch-paux
    E_trac_gross=float(np.sum(np.maximum(Ptrac,0.0)*dt)/3600.0)
    E_trac_regen=float(np.sum(np.maximum(-Ptrac,0.0)*dt)/3600.0)
    E_gen_to_trac=float(np.sum(np.minimum(Pgen_t,np.maximum(Ptrac,0.0))*dt)/3600.0)
    E_batt_dis=float(np.sum(np.maximum(Pbatt_anch,0)*dt)/3600.0)
    E_batt_chg=float(np.sum(np.maximum(-Pbatt_anch,0)*dt)/3600.0)
    regen_to_batt=mrow.get('charge_pure_regen_kwh',np.nan)
    gen_to_batt=(mrow.get('charge_eng_only_kwh',0) or 0)+(mrow.get('charge_dual_kwh',0) or 0)
    E_batt_to_trac=max(E_trac_gross-E_gen_to_trac,0.0)
    agg = dict(E_fuel=E_fuel,E_eng=E_eng,E_gen=E_gen,E_trac_gross=E_trac_gross,E_trac_regen=E_trac_regen,
        E_gen_to_trac=E_gen_to_trac,E_batt_to_trac=E_batt_to_trac,E_batt_dis=E_batt_dis,E_batt_chg=E_batt_chg,
        regen_to_batt=regen_to_batt,gen_to_batt=gen_to_batt,cold_fuel_frac=coldfuel/totfuel if totfuel>0 else np.nan,
        eta_eng=E_eng/E_fuel if E_fuel>0 else np.nan, eta_fuel_bus=E_gen/E_fuel if E_fuel>0 else np.nan,
        f_gen=E_gen_to_trac/E_trac_gross if E_trac_gross>0 else np.nan)
    persample = dict(Ptrac=Ptrac, Pgen_t=Pgen_t, Pbatt_anch=Pbatt_anch, dt=dt)
    return agg, persample
