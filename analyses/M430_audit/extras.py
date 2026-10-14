import json, numpy as np
from audit_m430 import *
out={}
# descriptive bins + floor diagnostics
for i,name in enumerate(P['order']):
    f=P['fits'][i]; x=np.array(f['gapH']); y=np.array(f['y']); days=np.array(f['arrivalDay'])
    p,_=heldout(x,y,days,'k10'); s=sen(x,y)
    b=binidx(x); d={}
    print('==',name,'slope',round(s,4),'ymin',y.min().round(3),'y==0',(y==0).mean().round(3),'y>0',(y>0).mean().round(3),'y<-2',(y<-2).mean().round(3))
    for k in range(6):
        m=b==k
        if m.sum()==0: continue
        lab=['0-1','1-3','3-6','6-12','12-24','24+'][k]
        print('  bin',lab,'n',m.sum(),'obs med retained %.3f'%np.median(np.exp(y[m])),'pred(full-fit) %.3f'%np.median(np.exp(s*x[m])),'pred(heldout) %.3f'%np.median(np.exp(p['M'][m])),'med y %.3f'%np.median(y[m]),'min y %.2f'%y[m].min(),'yhat med %.2f'%np.median(s*x[m]))
    # log-MSE decomposition by gap<12 / >=12
    for lab,sel in [('gap<12',x<12),('gap>=12',x>=12)]:
        eM=((y-p['M'])**2)[sel].sum(); e0=(y**2)[sel].sum()
        print('  logSE share',lab,'n',sel.sum(),'M %.1f B0 %.1f'%(eM,e0),'share of M total %.2f'%(eM/((y-p['M'])**2).sum()))
    # floor-aware prediction: clip yhat at min of training y (here use global quantile 1% of y as floor proxy)
    fl=np.percentile(y,1)
    pc=np.maximum(p['M'],fl)
    for kind in ['mse','mae']:
        print('  clipped-at-floor(%.2f) %s skill vs B0 %.3f (unclipped %.3f)'%(fl,kind,1-stat(y,pc,kind)/stat(y,p['B0'],kind),1-stat(y,p['M'],kind)/stat(y,p['B0'],kind)))
    # retained-scale MAE contribution by bins
    eM=np.abs(np.exp(y)-np.exp(p['M'])); e0=np.abs(np.exp(y)-1)
    print('  MAE retained: M mean err gap>=12 %.3f, B0 %.3f; frac of MAE_B0 from gap<1: %.2f'%(eM[x>=12].mean(),e0[x>=12].mean(),e0[x<1].sum()/e0.sum()))
# pack lt1: B2==B0?
f=P['fits'][0]; x=np.array(f['gapH']); y=np.array(f['y']); days=np.array(f['arrivalDay'])
p,_=heldout(x,y,days,'k10'); l=x<1
print('pack lt1: B2m==0 all', np.all(p['B2m'][l]==0), 'y==0 share', (y[l]==0).mean(), 'y<0', (y[l]<0).mean(), 'y>0',(y[l]>0).mean(), 'slope*x range', (p['M'][l]).min(), (p['M'][l]).max())
# seed robustness for S3 pack lt1 and all key bounds, seeds 0..9
for i,name in enumerate(P['order']):
    ups=[];los=[]
    for sd in range(20):
        pass
