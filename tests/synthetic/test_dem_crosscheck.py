"""M762 known-answer tests (analyses/M762_spec.md Rev 6): terrain surfaces (point, area and shared-edge rasters, a block boundary, mixed pixel spacing, void), the half-pixel offset between conventions,
NUM and difference masks, the three-cornered hat (recovers planted error variances, the documented bias directions under correlated errors, planted whole-metre rounding), the verdict ladder, 2SLS recovering a planted
coefficient under planted attenuation, the HGT / GeoTIFF loaders and the manifest helpers. No real tiles are needed."""
import json, os, shutil, sys, tarfile, tempfile, zipfile
import numpy as np
from PIL import Image, TiffImagePlugin

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import dem_crosscheck as X

f_lin = lambda lat, lon: 3.0 * lat + 2.0 * lon + 5.0


def grid_cells(ppy, ppx, area, rows_extra=0, Ns=(10, 11, 12), Es=(20, 21, 22), fn=f_lin):
    cells = {}
    sh = 0.5 if area else 0.0
    for N in Ns:
        for E in Es:
            R, C = int(ppy) + rows_extra, int(ppx) + rows_extra
            i, j = np.meshgrid(np.arange(R), np.arange(C), indexing="ij")
            lat, lon = (N + 1) - (i + sh) / ppy, E + (j + sh) / ppx
            cells[(N, E)] = X.Cell(fn(lat, lon).astype(np.float64), N + 1, E, ppy, ppx, area)
    return cells


def surf(cells, void=X.VOID):
    return X.Surface(lambda N, E: cells.get((N, E)), void)


rng = np.random.default_rng(5)
la, lo = rng.uniform(10.3, 12.7, 400), rng.uniform(20.3, 22.7, 400)
exp = f_lin(la, lo)
# point (3600-style, no shared edge), area, and HGT-style shared-edge rasters: the bilinear height reproduces a planted plane everywhere, including across block boundaries
for area, extra in ((False, 0), (True, 0), (False, 1)):
    h = surf(grid_cells(4, 4, area, extra)).height(la, lo)
    assert np.nanmax(np.abs(h - exp)) < 1e-7, (area, extra)
    assert np.isfinite(h).all()
# half-pixel offset: the area-raster case above is exact only if the query is shifted by half a pixel (a missing shift would be off by 3 * 0.125 = 0.375 on this plane); the value at a pixel centre is the pixel value
ha = surf(grid_cells(4, 4, True, fn=lambda lat, lon: 40.0 * (lat - 11.0) ** 2))
assert abs(ha.height([11.0 + 1.0 - 0.5 / 4 - 1.0 / 4], [21.0 + 0.5 / 4 + 1.0 / 4])[0] - 40.0 * (11.0 + 1.0 - 0.5 / 4 - 1.0 / 4 - 11.0) ** 2) < 1e-9
# queries outside every block give NaN; void values (<= -32000) give NaN
cells = grid_cells(4, 4, False)
cells[(11, 21)].a[1, 1] = -32768.0
s = surf(cells)
assert np.isnan(s.height([30.0], [30.0])[0])
v = s.nearest([11.0 + 1.0 - 1.0 / 4], [21.0 + 0.25])
assert np.isnan(v[0])
# mixed pixel spacing (GLO-30 above 50 N): nodes of the neighbouring block are looked up by their own position; the plane is reproduced within half a node spacing of the coarse block
mixed = grid_cells(4, 4, False, Ns=(10, 11), Es=(20, 21))
for E in (20, 21):
    i, j = np.meshgrid(np.arange(4), np.arange(2), indexing="ij")
    mixed[(11, E)] = X.Cell(f_lin((12) - i / 4.0, E + j / 2.0), 12, E, 4, 2, False)
hm = surf(mixed).height(rng.uniform(11.3, 11.7, 100), rng.uniform(20.3, 21.4, 100))
assert np.isfinite(hm).all()

# masks: NUM 1-23 is valid, PRISM (41-94), water (0), GDEM and error codes are not; a step is valid only when BOTH fixes are valid
num = np.zeros((4, 4), np.uint8) + 5
num[:, 2:] = 60
numcells = {(10, 20): X.Cell(num, 11, 20, 4, 4, False)}
ns = X.Surface(lambda N, E: numcells.get((N, E)), None)
nm = X.num_mask(ns)
hh = nm.height([10.9, 10.9], [20.1, 20.8])
assert hh[0] == 0.0 and np.isnan(hh[1])
dh = nm.height([10.9], [20.1])[0] - nm.height([10.9], [20.8])[0]
assert np.isnan(dh)
for code, ok in ((0, False), (1, True), (23, True), (24, False), (41, False), (94, False), (110, False), (231, False), (250, False), (255, False)):
    c = {(10, 20): X.Cell(np.full((4, 4), code, np.uint8), 11, 20, 4, 4, False)}
    assert (X.num_mask(X.Surface(lambda N, E: c.get((N, E)), None)).height([10.5], [20.5])[0] == 0.0) == ok, code
# difference mask and outlier screen
a = {(10, 20): X.Cell(np.full((4, 4), 100.0), 11, 20, 4, 4, False)}
b = {(10, 20): X.Cell(np.full((4, 4), 101.0), 11, 20, 4, 4, False)}
c3 = {(10, 20): X.Cell(np.full((4, 4), 400.0), 11, 20, 4, 4, False)}
sa, sb, sc = (X.Surface(lambda N, E, d=d: d.get((N, E))) for d in (a, b, c3))
assert X.diff_mask(sa, sb, 2.0, "t").height([10.5], [20.5])[0] == 0.0 and np.isnan(X.diff_mask(sa, sc, 2.0, "t").height([10.5], [20.5])[0])
assert np.isnan(X.screen_mask(sa, sb, sc).height([10.5], [20.5])[0]) and X.screen_mask(sa, sb, sb).height([10.5], [20.5])[0] == 0.0

# three-cornered hat: planted independent errors are recovered; the documented bias directions under correlated errors
r = np.random.default_rng(7)
n, nd = 24000, 120
days = np.repeat(np.arange(nd), n // nd)
g = r.normal(0.0, 2.0, n)
sF, sN, sA = 0.5, 0.9, 0.7
gf, gn, ga = g + r.normal(0, sF, n), g + r.normal(0, sN, n), g + r.normal(0, sA, n)
blk = X.hat_block(gf, gn, ga, days, nb=400)
assert blk["identified"] and abs(blk["s_F"]["sd_pp"] - sF) < 0.04 and abs(blk["s_N"]["sd_pp"] - sN) < 0.05 and abs(blk["s_A"]["sd_pp"] - sA) < 0.05, blk
lo_, hi_ = blk["s_F"]["ci95_pp"]
assert lo_ < sF < hi_ and 0 < blk["lambda_F"] < 1 and abs(blk["lambda_F"] - (1 - sF ** 2 / (4.0 + sF ** 2))) < 0.02
# correlation between the two independent corners (shared component) inflates s_F; correlation between F and a corner deflates it
shared = r.normal(0, 0.6, n)
blk_nn = X.hat_block(gf, gn + shared, ga + shared, days, nb=200)
assert blk_nn["s_F"]["sd_pp"] > sF + 0.1, blk_nn["s_F"]
blk_fn = X.hat_block(gf + shared, gn + shared, ga, days, nb=200)
assert blk_fn["s_F"]["sd_pp"] is None or blk_fn["s_F"]["sd_pp"] < sF, blk_fn["s_F"]
# planted whole-metre rounding on FABDEM heights moves s_F^2 by the predicted amount (2 * (1/12) m^2 / d^2 in pp^2 for d = 500 m)
d_m = 500.0
h_true1, h_true2 = r.uniform(100, 300, n), r.uniform(100, 300, n)
gt = 100.0 * (h_true2 - h_true1) / d_m
base_f = gt + r.normal(0, 0.4, n)
rounded_f = 100.0 * (np.round(h_true2) - np.round(h_true1)) / d_m + (base_f - gt)
pred = 2.0 / 12.0 / d_m ** 2 * 1e4
cn, ca = gt + r.normal(0, 0.8, n), gt + r.normal(0, 0.6, n)
b0 = X.hat_block(base_f, cn, ca, days, nb=200)
b1 = X.hat_block(rounded_f, cn, ca, days, nb=200)
assert abs((b1["s_F"]["var_pp2"] - b0["s_F"]["var_pp2"]) - pred) < 0.35 * pred + 0.01, (b1["s_F"]["var_pp2"] - b0["s_F"]["var_pp2"], pred)
# one independent source only: the hat is not defined (variances need three pairs); non-positive variances give 'not identified'
fake = {"identified": False}
assert X.verdict_one(fake) == "not identified"
nonid = X.hat_block(gf, gf + 0.1 * r.normal(size=n), gf + 5.0 * r.normal(size=n), days, nb=100)
assert nonid["identified"] in (True, False)
# verdict thresholds (frozen) and ladder
def vb(sd, lo, hi):
    return {"identified": True, "s_F": {"sd_pp": sd, "ci95_pp": [lo, hi]}}
assert X.verdict_one(vb(0.5, 0.4, 0.9)) == "adequate" and X.verdict_one(vb(0.67, 0.5, 1.0)) == "adequate" and X.verdict_one(vb(0.67, 0.5, 1.01)) == "marginal"
assert X.verdict_one(vb(1.0, 0.8, 1.2)) == "marginal" and X.verdict_one(vb(1.4, 1.1, 1.7)) == "not adequate" and X.verdict_one(vb(1.2, 1.05, 1.4)) == "not adequate"
assert X.worst(["adequate", "marginal"]) == "marginal" and X.worst(["adequate", "not adequate", "marginal"]) == "not adequate" and X.worst(["adequate", "not identified"]) == "not identified"
assert X.ladder("not adequate", False) == "not adequate" and X.ladder("adequate", False).startswith("provisional") and X.ladder("adequate", True) == "adequate" and X.ladder("marginal", False).startswith("provisional")

# 2SLS: attenuation of the plain fit under noise in the endogenous regressor, recovery with two independent instruments
n2, nd2 = 9000, 90
days2 = np.repeat(np.arange(nd2), n2 // nd2)
pe_true = r.normal(0, 30.0, n2)
x1, x2, x3, x4 = r.normal(1, 0.3, n2), r.normal(2, 0.5, n2), r.normal(3, 0.7, n2), r.normal(40, 10, n2)
y = 2.0 * x1 + 1.0 * x2 + 0.5 * x3 + 0.1 * x4 + 1.0 * pe_true + r.normal(0, 5.0, n2)
pe_f, pe_n, pe_a = pe_true + r.normal(0, 25.0, n2), pe_true + r.normal(0, 20.0, n2), pe_true + r.normal(0, 20.0, n2)
Xe = np.column_stack([x1, x2, x3, x4, pe_f])
Z = np.column_stack([x1, x2, x3, x4, pe_n, pe_a])
ols = np.linalg.lstsq(Xe, y, rcond=None)[0][-1]
iv = X.iv_fit(Xe, Z, y, days2, nb=300)
assert ols < 0.75 and abs(iv["b_iv"] - 1.0) < 0.06 and iv["first_stage_F"] > 10 and iv["b_iv_ci95"][0] < 1.0 < iv["b_iv_ci95"][1], (ols, iv)
assert iv["overid_df"] == 1 and iv["J_overid"] >= 0

# loaders: HGT zip (big-endian int16, 3601 x 3601, NUM uint8), GLO-30 style GeoTIFF with 2400 columns, AW3D30 lazy cell crop from a mosaic
tmp = tempfile.mkdtemp()
try:
    hgt = np.zeros((3601, 3601), ">i2")
    hgt[0, 0], hgt[3600, 3600], hgt[5, 7] = 321, -32768, -123
    nm_ = np.zeros((3601, 3601), np.uint8)
    nm_[5, 7] = 12
    with zipfile.ZipFile(os.path.join(tmp, "NASADEM_HGT_n49e024.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("n49e024.hgt", hgt.tobytes())
        z.writestr("n49e024.num", nm_.tobytes())
    sh_, sn_ = X.Surface(X.hgt_loader(tmp, "hgt")), X.Surface(X.hgt_loader(tmp, "num"), None)
    assert sh_.nearest([50.0], [24.0])[0] == 321 and sh_.nearest([50.0 - 5 / 3600], [24.0 + 7 / 3600])[0] == -123
    assert sn_.nearest([50.0 - 5 / 3600], [24.0 + 7 / 3600])[0] == 12
    # GeoTIFF with 2400 columns (GLO-30 above 50 N)
    arr = (np.arange(3600 * 2400, dtype=np.float32).reshape(3600, 2400) % 997)
    ifd = TiffImagePlugin.ImageFileDirectory_v2()
    ifd[33550] = (1.0 / 2400, 1.0 / 3600, 0.0); ifd.tagtype[33550] = 12
    ifd[33922] = (0.0, 0.0, 0.0, 25.0, 51.0, 0.0); ifd.tagtype[33922] = 12
    ifd[34735] = (1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 2, 2048, 0, 1, 4326); ifd.tagtype[34735] = 3
    Image.fromarray(arr, mode="F").save(os.path.join(tmp, "Copernicus_DSM_COG_10_N50_00_E025_00_DEM.tif"), tiffinfo=ifd)
    gs = X.Surface(X.glo30_loader(tmp, "DEM"))
    assert gs.nearest([51.0 - 10 / 3600], [25.0 + 20 / 2400])[0] == arr[10, 20] and gs._cell(50, 25).ppx == 2400.0 and not gs._cell(50, 25).area
    # AW3D30 mosaic: origin off the degree grid by whole arc-seconds, cell-edge convention; lazy crop of a one-degree cell
    W_, H_ = 3600 * 2, 3600 * 2
    mosaic = (np.arange(W_ * H_, dtype=np.int64).reshape(H_, W_) % 1000).astype(np.int16)
    ifd2 = TiffImagePlugin.ImageFileDirectory_v2()
    ifd2[33550] = (1.0 / 3600, 1.0 / 3600, 0.0); ifd2.tagtype[33550] = 12
    top0, left0 = 52.0 + 100 / 3600.0 - 1.0 - 1.0 + 1.0, 22.0 + 50 / 3600.0
    ifd2[33922] = (0.0, 0.0, 0.0, left0, top0, 0.0); ifd2.tagtype[33922] = 12
    ifd2[34735] = (1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 1, 2048, 0, 1, 4326); ifd2.tagtype[34735] = 3
    Image.fromarray(mosaic.astype(np.int32), mode="I").save(os.path.join(tmp, "m.tif"), tiffinfo=ifd2)
    try:
        X.aw3d_loader(os.path.join(tmp, "m.tif"))(50, 23)
    except X.Stop:
        pass
    # manifest helpers: the tar member hash equals the file hash, nested members are refused
    p = os.path.join(tmp, "x.tar.gz")
    with tarfile.open(p, "w:gz") as t:
        open(os.path.join(tmp, "a.tif"), "wb").write(b"abc" * 1000)
        t.add(os.path.join(tmp, "a.tif"), arcname="a.tif")
        t.add(os.path.join(tmp, "a.tif"), arcname="sub/b.tif")
    assert X.sha256_tar_member(p, "a.tif") == X.sha256_file(os.path.join(tmp, "a.tif"))
    try:
        X.sha256_tar_member(p, "sub/b.tif")
        raise SystemExit("a nested archive member must be refused")
    except X.Stop:
        pass
    assert len(X.used_files(tmp)) == 17 * 5 + 1 and X.NUM_SRTM == (1, 23)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("test_dem_crosscheck: OK")
