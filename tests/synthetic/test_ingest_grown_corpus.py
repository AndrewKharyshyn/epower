"""M464 (spec analyses/M464_spec.md, component C): code that never ran on a GROWN corpus fails here, not during a real ingestion.
A sandbox copy of the repository gets a reduced corpus (every 20th drive of the committed master) plus ONE synthetic new drive (a clone of the newest row under a new file
key and date, same thermal cohort). The top-level blocks m296 compares against are rebuilt with the same builder functions the ingestion uses (compute_summary_arrays),
the previous arrays' additive leaves are carried onto them with ingest_core.carry_forward exactly as at a real ingestion, and m296_refresh_master_seasonal.py --dry-run
(the parity guard, M463 failure (a)) must pass. Negative control: a changed shared leaf must still fail the guard."""
import copy, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
import pandas as pd
import ingest_preflight as P


def main():
    sb, _ = P.make_sandbox(REPO)
    try:
        dm = pd.read_csv(os.path.join(REPO, "drive_master.csv"), low_memory=False)
        reg = pd.read_csv(os.path.join(REPO, "seasonal_drive_master.csv"), low_memory=False)
        sub = dm.iloc[::20].copy()
        newest = dm.iloc[[-1]].copy()
        synth = newest.copy()
        synth["file"] = "2099-01-01 00-00-00.csv"
        for c in ("date", "Date", "start_time", "startTime"):
            if c in synth.columns:
                synth[c] = "2099-01-01" if c.lower() == "date" else synth[c]
        sub = pd.concat([sub, synth], ignore_index=True)
        regs = reg[reg["file"].isin(sub["file"])][["file", "thermal_regime"]].copy()
        src_regime = reg.loc[reg["file"] == newest["file"].iloc[0], "thermal_regime"].iloc[0]
        regs = pd.concat([regs, pd.DataFrame({"file": [synth["file"].iloc[0]], "thermal_regime": [src_regime]})], ignore_index=True)
        assert {"warm", "shoulder"} <= set(regs["thermal_regime"]), "the reduced corpus must keep both warm and shoulder drives"
        sub.to_csv(os.path.join(sb, "drive_master.csv"), index=False, lineterminator="\n")
        reg_full = reg[reg["file"].isin(sub["file"])].copy()
        pd.concat([reg_full, regs.tail(1).reindex(columns=reg_full.columns)], ignore_index=True).to_csv(os.path.join(sb, "seasonal_drive_master.csv"), index=False, lineterminator="\n")

        sc_path = os.path.join(sb, "ah_throughput.csv")           # the ah_throughput stage appends the new drive's sidecar row at a real ingestion
        sc = pd.read_csv(sc_path, dtype=str, keep_default_na=False)
        row = sc[sc["file"] == newest["file"].iloc[0]].copy()
        assert len(row) == 1, "the newest master row must have one sidecar row"
        row["file"] = synth["file"].iloc[0]
        pd.concat([sc, row], ignore_index=True).to_csv(sc_path, index=False, lineterminator=chr(10))

        import compute_summary_arrays as C
        import ingest_core as IC
        prev = json.load(open(os.path.join(REPO, "summary_arrays.json"), encoding="utf-8"))
        cfg = json.load(open(os.path.join(REPO, "summary_config.json"), encoding="utf-8"))
        odo = prev.get("meta", {}).get("odometerKm")
        d2 = C._load_exposure_frame().exposure_frame(sub.copy(), sidecar_path=sc_path)
        ca = C.category_A(d2, odometer_km=odo)
        fresh = {key: ca.get(key) for key in ("efficiencyBands", "cycleByType", "regenByType", "regenByTypeMeta", "driveTypes", "driveDurationDist", "evTraction")}
        fresh["energyPath"] = C._energy_path(d2)
        fresh["dodSocLevelSensitivity"] = C._soc_level_sensitivity(d2, (cfg or {}).get("socLevelWeighting"))
        carried = IC.carry_forward(fresh, prev)                  # the ingestion step that re-attaches the additive evTraction leaves
        assert any(c.startswith("evTraction.") for c in carried), carried
        grown = copy.deepcopy(prev)
        grown.update(fresh)
        path = os.path.join(sb, "summary_arrays.json")
        json.dump(grown, open(path, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=1)
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        cmd = [sys.executable, "m296_refresh_master_seasonal.py", "--dry-run"]
        r = subprocess.run(cmd, cwd=sb, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert r.returncode == 0 and "PARITY OK" in r.stdout, (r.returncode, r.stdout[-800:], r.stderr[-1200:])
        # negative control: a changed shared (non-additive) leaf is still a parity failure
        bad = copy.deepcopy(grown)
        bad["efficiencyBands"] = {"tampered": True}
        json.dump(bad, open(path, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=1)
        r = subprocess.run(cmd, cwd=sb, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert r.returncode == 1 and "PARITY FAILURE" in r.stdout, (r.returncode, r.stdout[-400:])
        print("OK test_ingest_grown_corpus")
    finally:
        P.remove_sandbox(sb)


if __name__ == "__main__":
    main()
