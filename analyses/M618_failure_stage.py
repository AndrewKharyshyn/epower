"""M618 spec Rev 1, R5: where does the SHIPPED mixed-effects fit fail? Descriptive reconciliation on the shipped code path (degradation_trends._mixedlm, one lbfgs run) over the M614 replay grid
(analyses/M614_replay.json), not a result of the new method. For each prefix: does the shipped fit return an estimate, and in a raw statsmodels lbfgs fit does the optimiser call raise, or does
the covariance / standard-error step raise. Output: analyses/M618_failure_stage.json."""
import json, os, sys, warnings
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import pandas as pd, statsmodels.formula.api as smf
import degradation_trends as DT


def main():
    r = json.load(open("analyses/M614_replay.json", encoding="utf-8"))
    dm = pd.read_csv("drive_master.csv")
    dm["date"] = pd.to_datetime(dm["date"])
    out = []
    for p in r["grid"]:
        sub = dm[dm["date"] <= pd.Timestamp(p["endDay"])]
        d = DT._prep(sub, "vreg_R_pack_mohm", icol="vreg_I_p95_A").dropna(subset=["T", "I"])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            shipped = DT._mixedlm(d, ("T", "I"))
            conv, stage = None, "optimiser raised"
            try:
                f = smf.mixedlm("y ~ months + T + I", d, groups=d["day"]).fit(method="lbfgs", reml=True, disp=False)
                conv, stage = bool(f.converged), "optimiser returned"
                try:
                    f.bse_fe["months"]
                    f.conf_int()
                    stage = "fit and covariance ok"
                except Exception as e:
                    stage = "optimiser returned; covariance or SE raised " + type(e).__name__
            except Exception as e:
                stage = "optimiser raised " + type(e).__name__
        out.append({"endDay": p["endDay"], "n": p["nDrives"], "shippedFitted": "slope" in shipped, "shippedError": shipped.get("error"), "shippedConverged": shipped.get("converged"), "rawConverged": conv, "stage": stage})
    with open("analyses/M618_failure_stage.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1)
    print(len(out), "prefixes;", sum(1 for o in out if o["shippedFitted"]), "fitted")


if __name__ == "__main__":
    main()
