"""M374: wire_gtr_seasonal.py must not rewrite summary_arrays.json when imported (it did, as a side effect, for every importer such as refresh_gtr_headline.py
and ad-hoc scripts). The wiring runs only as a script. Known answers: (a) an import leaves the payload byte-identical and prints nothing; (b) ENTRY_META equals the entry
metadata the payload carries (so skipping the wiring on import cannot change the ingestion output); (c) the script entry point still writes the entry; (d) refresh_gtr_headline.py
still runs against the guarded module."""
import hashlib, json, os, shutil, subprocess, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
FILES = ["fuel_recon_master.csv", "seasonal_drive_master.csv", "drive_master.csv", "summary_arrays.json", "eligibility.py", "wire_gtr_seasonal.py", "refresh_gtr_headline.py"]
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()


def stage(td):
    for f in FILES:
        shutil.copyfile(os.path.join(ROOT, f), os.path.join(td, f))


def run(args, td):
    return subprocess.run([sys.executable] + args, cwd=td, capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, PYTHONUTF8="1"))


with tempfile.TemporaryDirectory() as td:
    stage(td)
    before = sha(os.path.join(td, "summary_arrays.json"))
    r = run(["-c", "import wire_gtr_seasonal as w; assert callable(w.aggregate) and callable(w.wavg) and hasattr(w, 'ENTRY_META')"], td)
    assert r.returncode == 0, r.stderr[-500:]
    assert r.stdout == "", "importing the module must print nothing"
    assert sha(os.path.join(td, "summary_arrays.json")) == before, "importing the module rewrote summary_arrays.json"

    # (b) the metadata the wiring sets equals what the payload already carries
    sys.path.insert(0, ROOT)
    import wire_gtr_seasonal as W
    entry = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))["seasonalCharts"]["charts"]["GeneratorTractionRecon"]
    assert {k: entry[k] for k in W.ENTRY_META} == W.ENTRY_META, "payload entry metadata drifted from wire_gtr_seasonal.ENTRY_META"

    # (c) the script entry point still writes the entry
    r = run(["wire_gtr_seasonal.py"], td)
    assert r.returncode == 0, r.stderr[-500:]
    e2 = json.load(open(os.path.join(td, "summary_arrays.json"), encoding="utf-8"))["seasonalCharts"]["charts"]["GeneratorTractionRecon"]
    assert {k: e2[k] for k in W.ENTRY_META} == W.ENTRY_META and set(e2["data"]) == {"all", "warm", "shoulder", "cold"}

    # (d) the ingestion stage that imports the module still runs, and twice gives the same bytes
    stage(td)
    r = run(["refresh_gtr_headline.py"], td)
    assert r.returncode == 0, r.stderr[-500:]
    one = sha(os.path.join(td, "summary_arrays.json"))
    r = run(["refresh_gtr_headline.py"], td)
    assert r.returncode == 0 and sha(os.path.join(td, "summary_arrays.json")) == one, "refresh_gtr_headline.py is not idempotent"
print("test_wire_gtr_import_guard: ok")
