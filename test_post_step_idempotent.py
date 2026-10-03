"""Regression (M300): apply_m284_post.sh applied twice to the shipped arrays/config leaves both byte-identical."""
import hashlib, os, shutil, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.abspath(__file__))
def md5(p): return hashlib.md5(open(p, "rb").read()).hexdigest()
tmp = tempfile.mkdtemp()
try:
    for f in os.listdir(ROOT):
        p = os.path.join(ROOT, f)
        if os.path.isfile(p) and not f.endswith((".html", ".log")) and f != "STATE.md":
            shutil.copy(p, tmp)
    os.makedirs(os.path.join(tmp, "tools"), exist_ok=True)      # M355: post-step helpers live under tools/ (apply_m284_post.sh calls tools/refresh_meta_sources.py)
    shutil.copy(os.path.join(ROOT, "tools", "refresh_meta_sources.py"), os.path.join(tmp, "tools"))
    base = {n: md5(os.path.join(tmp, n)) for n in ("summary_arrays.json", "summary_config.json")}
    for i in (1, 2):
        r = subprocess.run(["bash", "apply_m284_post.sh"], cwd=tmp, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-500:]
        for n, h in base.items():
            assert md5(os.path.join(tmp, n)) == h, f"{n} changed after post-step run {i}"
    print("OK post-step idempotent (2 runs, arrays+config byte-identical)")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
