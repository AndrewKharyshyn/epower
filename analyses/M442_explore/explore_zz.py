import sys, os, json
sys.path.insert(0, os.environ['TEMP']); sys.path.insert(0, 'tools'); sys.path.insert(0, os.getcwd())
import numpy as np, pandas as pd
import regen_v2x as R
import drive_raw_cache as drc
import compute_summary_arrays as C
FL = drc.make_frame_loader(raw_dir=os.path.join(os.getcwd(), "raw_only"))
def work(a):
    fn, th, dec, part = a
    R.SIGNED = True
    df = FL(fn)
    r = R.extract_drive(df, C=C, zz_theta=th, decimate=dec, dec_part=part)
    iv = r["intervals"]
    if iv is None: return (0,0,0)
    ke = (R.KE_FACTOR*1890*iv["dv2"])
    return (ke.sum(), iv["charge"].sum(), len(ke))
if __name__ == "__main__":
    from concurrent.futures import ProcessPoolExecutor
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    day = dm["date"].astype(str).str[8:10].astype(int)
    dev = dm[(dm["ev_rpm_dt_med_s"] < 1.0) & (day % 2 == 1)]["file"].tolist()
    print("dev fast drives", len(dev))
    with ProcessPoolExecutor(5) as ex:
        for part in (None, ("I", "V"), ("speed",), ("rpm",)):
            out = {}
            for dec in (None, 0, 1):
                r = np.array(list(ex.map(work, [(f, 3.0, dec, part) for f in dev], chunksize=4))).sum(axis=0)
                out[str(dec)] = {"ke": round(r[0],2), "ch": round(r[1],2), "eff": round(100*r[1]/r[0],2), "n": int(r[2])}
            print("decimate", part, json.dumps(out))
