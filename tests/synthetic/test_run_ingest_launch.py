"""M397 known-answer test: stage commands are launched with the running interpreter (not the flaky Windows Store 'python3' alias) and a launch failure becomes a recorded stage failure, not a crash."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
import run_ingest as RI

assert RI.resolve_cmd(["python3", "tools/x.py", "--a"]) == [sys.executable, "tools/x.py", "--a"]
assert RI.resolve_cmd(["python", "x.py"]) == [sys.executable, "x.py"]
assert RI.resolve_cmd(["node", "build_html.js"]) == ["node", "build_html.js"]                       # other commands unchanged
assert RI.resolve_cmd([]) == [] and RI.resolve_cmd(("python3", "a")) == [sys.executable, "a"]       # empty list safe, tuple accepted, input not mutated
src = ["python3", "a.py"]
RI.resolve_cmd(src)
assert src == ["python3", "a.py"]
with tempfile.TemporaryDirectory() as td:
    log = os.path.join(td, "o.log")
    with open(log, "w") as lf:
        r, err = RI.launch(["python3", "-c", "import sys; sys.exit(7)"], cwd=td, stdout=lf, stderr=RI.subprocess.STDOUT)
    assert r.returncode == 7 and err is None                                                          # a real stage: its own return code
    with open(log, "w") as lf:
        r, err = RI.launch(["this_command_does_not_exist_m397"], cwd=td, stdout=lf, stderr=RI.subprocess.STDOUT)
    assert r.returncode != 0 and err and "FileNotFoundError" in err                                    # never started: a failure value, not an exception
print("OK run_ingest launch: running interpreter used, other commands unchanged, launch failure recorded")
