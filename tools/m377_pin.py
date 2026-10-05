"""M377b: master-hash pin of the point runner (tools/m373_point.py), as a tested function (analyses/M377_spec.md Rev 4 (e)).
Historical tags (M373, M375) keep their frozen hash; every other tag pins the live drive_master.csv MD5 at start and the runner asserts at the end that it is unchanged."""
import hashlib

FROZEN = {"M373": "bd9d10726bb064d857cf9ff98d2b7338", "M375": "bd9d10726bb064d857cf9ff98d2b7338"}


def md5_of(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def master_pin(tag, master_path):
    """Return the MD5 the run must see before and after."""
    return FROZEN[tag] if tag in FROZEN else md5_of(master_path)


import re as _re
_DOC_ADDENDUM = _re.compile(rb"\n---\n# Rev \d+ \(documentation")


def spec_sha(path):
    """sha256 of a spec file's FROZEN part: everything before the first 'documentation addendum' revision heading ('# Rev N (documentation ...'),
    so a documentation addendum written after the runs (no estimate, gate or tolerance changed) does not break the binding of the run outputs to the frozen spec."""
    b = open(path, "rb").read()
    m = _DOC_ADDENDUM.search(b)
    return hashlib.sha256(b[:m.start()] if m else b).hexdigest()
