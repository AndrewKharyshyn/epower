import sys, os, json
sys.path.insert(0, os.environ['TEMP']); sys.path.insert(0, 'tools'); sys.path.insert(0, os.getcwd())
import numpy as np, pandas as pd
import regen_v2x as R
import drive_raw_cache as drc
import compute_summary_arrays as C
FL = drc.make_frame_loader(raw_dir=os.path.join(os.getcwd(), "raw_only"))
def work(a):
    fn, jit, dec = a
    df = FL(fn)
    r = R.extract_drive(df, C=C, jitter_kmh=jit, decimate=dec)
    iv = r["intervals"]
    if iv is None: return (0,0,0,0,0)
    m = ~iv["trimmed"]; st = m & ~iv["plateau"]
    ke = (R.KE_FACTOR*1890*iv["dv2"])
    return (ke[m].sum(), iv["charge"][m].sum(), ke[st].sum(), iv["charge"][st].sum(), int(m.sum()))
if __name__ == "__main__":
    from concurrent.futures import ProcessPoolExecutor
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    fast = dm[dm["ev_rpm_dt_med_s"] < 1.0]["file"].tolist()
    with ProcessPoolExecutor(5) as ex:
        for jit in (0.0, 1.0, 2.0):
            res = {}
            for dec in (None, 0, 1):
                r = np.array(list(ex.map(work, [(f, jit, dec) for f in fast], chunksize=4))).sum(axis=0)
                res[dec] = r
            out = {}
            for dec, r in res.items():
                out[str(dec)] = {"kept_ke": round(r[0],2), "kept_eff": round(100*r[1]/r[0],2), "strict_eff": round(100*r[3]/r[2],2), "n": int(r[4])}
            print("jitter", jit, json.dumps(out))
