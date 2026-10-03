"""M350: the NaN-propagating idiom `float(x.get('I_offset_A_applied', 0.0) or 0.0)` / `(float(v) or 0.0)` must not return to the GTR scripts.
`NaN or 0.0` is NaN (NaN is truthy), which suppressed the battery term for drives with an unstamped offset (M349). Source scan + the shared
helper's contract (fuel_recon.resolve_offset never returns NaN)."""
import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
fails = 0
def ok(label, c, extra=""):
    global fails
    print(("PASS " if c else "FAIL ") + label + ((" - " + str(extra)) if (not c and extra) else ""))
    fails += 0 if c else 1
BAD = re.compile(r"I_offset_A_applied['\"][^\n]{0,40}or 0\.0|float\(v\) or 0\.0")
for sc in ("speed_split.py", "crossval_gtr.py", "sensitivity_gtr.py", "simultaneity_gtr.py", "fuel_recon.py"):
    src = open(os.path.join(ROOT, sc), encoding="utf-8").read()
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    ok(f"{sc}: no NaN-propagating `or 0.0` offset idiom in code", not BAD.search(code))
    if sc != "fuel_recon.py":
        ok(f"{sc}: uses fuel_recon.resolve_offset / corpus_offset", "resolve_offset" in code and "corpus_offset" in code)
import numpy as np, fuel_recon as FR
for v in (float("nan"), None, "x", np.nan):
    r, imp = FR.resolve_offset({"I_offset_A_applied": v}, -0.3858)
    ok(f"resolve_offset({v!r}) is finite and imputed", r == r and np.isfinite(r) and imp)
print("NAN_OFFSET_PATTERN FAILS =", fails)
sys.exit(1 if fails else 0)
