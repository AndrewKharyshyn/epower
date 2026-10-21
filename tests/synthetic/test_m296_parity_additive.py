"""M463: the m296 parity guard excludes ONLY the two carried additive evTraction leaves; any other leaf difference must still be a parity failure."""
import os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
src = open(os.path.join(ROOT, "m296_refresh_master_seasonal.py"), encoding="utf-8").read()
i, j = src.index("ADDITIVE_TOP = "), src.index("bad = [cid")
snippet = src[i:j]


def top(A, key):
    ns = {"A": A}
    exec(snippet, ns)
    return ns["_top"](key), ns["ADDITIVE_TOP"]


def main():
    base = {"nDrives": 3, "evKm": 1.5}
    extra = dict(base, detectorSensitivity={"x": 1}, zeroFuelVariant={"y": 2})
    v, add = top({"evTraction": extra}, "evTraction")
    assert add == {"evTraction": ("detectorSensitivity", "zeroFuelVariant")}, add
    assert v == base, v
    # any other extra leaf is NOT excluded (parity would fail)
    v, _ = top({"evTraction": dict(base, newLeaf=1)}, "evTraction")
    assert v != base and "newLeaf" in v
    # other blocks are never filtered
    other = {"a": 1, "detectorSensitivity": 2}
    v, _ = top({"cycleByType": other}, "cycleByType")
    assert v == other
    # a changed shared leaf stays a difference
    v, _ = top({"evTraction": dict(extra, evKm=9.9)}, "evTraction")
    assert v != base
    print("test_m296_parity_additive OK")


if __name__ == "__main__":
    main()
