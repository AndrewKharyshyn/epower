"""
Energy-reconstruction model constants and BSFC surface.
All values are MODEL-DERIVED / literature-anchored unless marked MEASURED.
Nissan anchor: BSFC_min = 217 g/kWh @ 2000 rpm (TR No.89, KR15DDT) -- a FLOOR/optimum,
never a universal constant. Enforced as a hard lower bound in every draw.
"""
import numpy as np

# ---- fuel physical properties (E5/E10 A-95 gasoline; UA market) ----
# density g/L and LHV MJ/kg: central + (lo,hi) treated as ~95% span -> sigma=(hi-lo)/4
RHO_G_PER_L   = (751.0, 746.0, 757.0)     # g/L  E10@15C, EN228 EU-origin (WOG/OKKO); density -> fuel MASS only
LHV_MJ_PER_KG = (41.15, 40.70, 41.70)     # MJ/kg  E10 (~8.58 kWh/L, 8.50-8.70); LHV -> chemical energy & eta ONLY
FUEL_VOL_ERR  = 0.03                       # +/- multiplicative on ECU fuel volume (1 sigma ~1.5%)

# ---- generator + power-electronics electrical efficiency (literature, PM machine + rectifier) ----
ETA_GEN = (0.95, 0.93, 0.97)               # generator electrical
ETA_PE  = (0.975, 0.96, 0.99)              # rectifier / DC bus PE

# ---- auxiliary HV load, drive-constant (DC-DC 12V, thermal, compressor baseline) ----
P_AUX_KW = (0.50, 0.20, 1.20)              # kW

# ---- battery current offset uncertainty (per-drive value already applied by pipeline) ----
I_OFFSET_SIGMA_A = 0.15                     # extra uncertainty around the applied offset

# ---- BSFC surface: central g/kWh per regime, with (lo,hi) ~95% span. Hard floor 217. ----
BSFC_FLOOR = 217.0
BSFC = {
 'OPT'     : (228.0, 217.0, 245.0),  # 1850-2150 rpm warm steady mid-load (best point cluster)
 'NEAR'    : (240.0, 222.0, 265.0),  # 2150-2400 rpm near-optimum high side
 'SEC'     : (245.0, 225.0, 275.0),  # 1350-1850 rpm secondary/1500 load point
 'LOW'     : (290.0, 245.0, 360.0),  # <1350 rpm low-rpm / transient
 'HIGH'    : (265.0, 235.0, 320.0),  # >2400 rpm and/or high boost: enrichment
}
COLD_MULT = (1.25, 1.12, 1.45)         # multiplicative penalty for cold/warm-up on top of warm regime

# regime thresholds (rpm). Cold gate: coolant<COLD_T_C or since-start<COLD_S.
OPT_LO, OPT_HI = 1850.0, 2150.0
NEAR_HI        = 2400.0
SEC_LO         = 1350.0
COLD_T_C       = 60.0
COLD_OIL_T_C   = 55.0        # oil-temp cold gate (empirical enrichment zone); oil retains heat across e-POWER engine restarts
COLD_S         = 90.0
BOOST_HIGH_BAR = 0.30                    # calc boost (bar) above this -> HIGH even if rpm modest

# scenario scalers applied to every regime central (sensitivity S16)
SCEN = {'optimistic':0.94, 'central':1.00, 'conservative':1.09}

def tri_sigma(c, lo, hi):
    """treat (lo,hi) as ~+-2 sigma about central c."""
    return c, (hi - lo) / 4.0

def sample_norm(rng, spec, n, floor=None, ceil=None):
    c, lo, hi = spec
    _, s = tri_sigma(c, lo, hi)
    x = rng.normal(c, s, n)
    if floor is not None: x = np.maximum(x, floor)
    if ceil  is not None: x = np.minimum(x, ceil)
    return x

def classify_regime(rpm, coolant, since_start_s, boost):
    """Vectorised regime id per engine-on sample. Returns array of dtype '<U4'."""
    rpm = np.asarray(rpm, float)
    reg = np.full(rpm.shape, 'OPT', dtype='<U4')
    reg[(rpm < SEC_LO)] = 'LOW'
    reg[(rpm >= SEC_LO) & (rpm < OPT_LO)] = 'SEC'
    reg[(rpm > OPT_HI) & (rpm <= NEAR_HI)] = 'NEAR'
    reg[(rpm > NEAR_HI)] = 'HIGH'
    if boost is not None:
        b = np.asarray(boost, float)
        reg[np.nan_to_num(b) > BOOST_HIGH_BAR] = 'HIGH'
    return reg

def cold_mask(coolant, since_start_s, oil=None):
    # Oil temp is the physical thermal-state variable and persists across the frequent
    # engine on/off cycling of a series hybrid; use it when present, else fall back to coolant.
    # The since_start term is intentionally NOT used (it mislabels every restart as cold).
    c = np.nan_to_num(np.asarray(coolant, float), nan=90.0)
    if oil is not None:
        o = np.asarray(oil, float)
        have = ~np.isnan(o)
        m = np.where(have, o < COLD_OIL_T_C, c < COLD_T_C)
        return m
    return (c < COLD_T_C)
