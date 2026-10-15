from common2 import *
def wq(x, w, q):
    o = np.argsort(x, kind='stable'); x = x[o]; w = w[o]; c = np.cumsum(w) / w.sum()
    return x[np.searchsorted(c, q, 'left')]
def wq_interp(x, w, q):
    o = np.argsort(x, kind='stable'); x = x[o]; w = w[o]; c = np.cumsum(w) / w.sum()
    return np.interp(q, c, x)
for name, m in [('strict v0>=10', strict & (v0 >= 10)),
                ('strict v0>=10 & temp & soc>=0', strict & (v0 >= 10) & hasT & (band != -9)),
                ('strict v0>=10 & soc', strict & (v0 >= 10) & (band != -9)),
                ('strict v0>=10 & temp', strict & (v0 >= 10) & hasT)]:
    x = X.epdec.to_numpy()[m]; w = ke[m]
    print(name, m.sum(), np.isfinite(x).all(), [round(float(wq(x, w, q)), 4) for q in (1/3, 2/3)], [round(float(wq_interp(x, w, q)), 4) for q in (1/3, 2/3)])
print('days', D_, 'drives', X.file.nunique(), 'kept', len(X))
