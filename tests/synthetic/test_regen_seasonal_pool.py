"""M424: the seasonal regeneration runs its independent (cohort, chart) tasks in a process pool. Tests: the worker-count rule; the cohort subsets partition the master; a task run in the parent process and the same
task run in pool workers return identical canonical JSON (the below-minimum-support cohort, so it takes seconds); the tool source dispatches through the pool and the CI list names this test. The full-size comparison
(6 workers against 1 on the 574-drive rehearsal state: payloads identical except two timestamps) is recorded in analyses/M424_pool_parity.json."""
import json, os, sys
from concurrent.futures import ProcessPoolExecutor
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.argv = [sys.argv[0]]
import regen_seasonal_raw as R


def main():
    os.environ.pop("XT_WORKERS", None)
    w = R._default_workers()
    assert 1 <= w <= 6, w
    os.environ["XT_WORKERS"] = "3"
    assert R._default_workers() == 3
    sys.argv[1:] = ["--workers", "2"]
    assert R._default_workers() == 2, "the command-line option overrides the environment"
    sys.argv[1:] = []
    os.environ["XT_WORKERS"] = "0"
    assert R._default_workers() == 1
    os.environ.pop("XT_WORKERS", None)

    dm, subsets = R.load_subsets()
    assert sum(len(v) for k, v in subsets.items() if k != "all") == len(subsets["all"]) == len(dm), "the cohorts partition the master (M426: warm, shoulder and cold once it meets the support, else the below-support remainder cold_ins)"
    small = "cold" if "cold" in subsets else "cold_ins"      # the smallest cohort drives the serial-vs-pool equality tasks below
    assert set(R.builders(None, None, None)) >= {"CrawlStopGo", "ThermalFuelPenalty", "BufferDebtRecovery"} and len(R.builders(None, None, None)) == 14

    tasks = [("catB", small, None), ("b", small, "HandoffSequence"), ("b", small, "DepartureArrival")]
    R._init_worker()
    serial = {t: R._run_task(t) for t in tasks}
    with ProcessPoolExecutor(max_workers=2, initializer=R._init_worker) as ex:
        pooled = {t: r for t, r in zip(tasks, ex.map(R._run_task, tasks))}
    canon = lambda v: json.dumps(v, sort_keys=True, default=float)
    for t in tasks:
        assert serial[t]["error"] is None and pooled[t]["error"] is None, (t, serial[t]["error"], pooled[t]["error"])
        assert canon(serial[t]["value"]) == canon(pooled[t]["value"]), "pool result differs from the in-process result: " + str(t)
        assert serial[t]["cf"] == pooled[t]["cf"] and serial[t]["crok"] == pooled[t]["crok"], "load counts must not depend on the process"

    src = open("tools/regen_seasonal_raw.py", encoding="utf-8").read()
    assert "ProcessPoolExecutor(max_workers=workers, initializer=_init_worker)" in src and "if workers <= 1" in src
    ci = open(".github/workflows/ci.yml", encoding="utf-8").read()
    assert "test_regen_seasonal_pool.py" in ci
    rec = json.load(open("analyses/M424_pool_parity.json", encoding="utf-8"))
    assert rec["nonTimestampDifferingLeaves"] == 0 and rec["seconds"]["workers6"] < rec["seconds"]["workers1"]
    print("OK test_regen_seasonal_pool")


if __name__ == "__main__":
    main()
