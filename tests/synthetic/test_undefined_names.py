"""M384: no root or tools/ script uses a name that is defined nowhere in its module (the class of bug that left tools/gtr_family_refresh_splice.py with an unimported
`M377_PIN`: a NameError at the first ingestion after M377c). Crude on purpose (module-wide: any binding anywhere counts), so it has no false positives from scoping."""
import ast, builtins, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
import glob
scripts = sorted(os.path.relpath(f, ROOT).replace(os.sep, "/") for f in glob.glob(os.path.join(ROOT, "*.py")) + glob.glob(os.path.join(ROOT, "tools", "*.py")))
BUILTIN = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__builtins__", "__spec__", "__path__"}


def undefined(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    bound = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(n.name)
            if not isinstance(n, ast.ClassDef):
                a = n.args
                bound |= {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs} | ({a.vararg.arg} if a.vararg else set()) | ({a.kwarg.arg} if a.kwarg else set())
        elif isinstance(n, ast.Lambda):
            a = n.args
            bound |= {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs} | ({a.vararg.arg} if a.vararg else set()) | ({a.kwarg.arg} if a.kwarg else set())
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for al in n.names:
                if al.name == "*":
                    return None                       # cannot decide
                bound.add((al.asname or al.name).split(".")[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            bound.add(n.id)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            bound |= set(n.names)
        elif isinstance(n, ast.MatchAs) and n.name:
            bound.add(n.name)
    return sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in bound and n.id not in BUILTIN})


import tempfile
NL = chr(10)
with tempfile.TemporaryDirectory() as td:                                          # known answer: an unimported module name is found, an imported one is not
    p = os.path.join(td, "k.py")
    open(p, "w", encoding="utf-8").write(NL.join(["import os", "x = os.sep", "y = M377_PIN.spec_sha('a')", ""]))
    assert undefined(p) == ["M377_PIN"], undefined(p)
    open(p, "w", encoding="utf-8").write(NL.join(["import m377_pin as M377_PIN", "y = M377_PIN.spec_sha('a')", ""]))
    assert undefined(p) == []
bad = {}
for s in scripts:
    u = undefined(os.path.join(ROOT, s))
    if u:
        bad[s] = u
assert not bad, "undefined names: %s" % bad
print("OK test_undefined_names (%d scripts)" % len(scripts))
