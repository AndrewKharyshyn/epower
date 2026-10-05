"""M377b: master-hash pin of the point runner (tools/m373_point.py), as a tested function (analyses/M377_spec.md Rev 4 (e)).
Historical tags (M373, M375) keep their frozen hash; every other tag pins the live drive_master.csv MD5 at start and the runner asserts at the end that it is unchanged."""
import hashlib

FROZEN = {"M373": "bd9d10726bb064d857cf9ff98d2b7338", "M375": "bd9d10726bb064d857cf9ff98d2b7338"}


def md5_of(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def master_pin(tag, master_path):
    """Return the MD5 the run must see before and after."""
    return FROZEN[tag] if tag in FROZEN else md5_of(master_path)
