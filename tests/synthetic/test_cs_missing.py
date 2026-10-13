"""M427 (external audit F13) known-answer test: the charge-sustaining flag is unavailable (None) when the SoC endpoints, soc_delta_pp and soc_delta_kwh are all absent;
the three documented paths keep their results."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import fuel_recon as F
nan = float("nan")
assert F._cs({}) is None and F._cs({"soc_start": nan, "soc_end": nan, "soc_delta_kwh": nan}) is None, "all inputs absent must be unavailable"
assert F._cs({"soc_delta_pp": 1.5}) is True and F._cs({"soc_delta_pp": 2.5}) is False
assert F._cs({"soc_start": 50.0, "soc_end": 51.5}) is True and F._cs({"soc_start": 50.0, "soc_end": 55.0}) is False
assert F._cs({"soc_start": nan, "soc_end": 50.0, "soc_delta_kwh": 0.01}) is True and F._cs({"soc_delta_kwh": 0.5}) is False
print("OK test_cs_missing")
