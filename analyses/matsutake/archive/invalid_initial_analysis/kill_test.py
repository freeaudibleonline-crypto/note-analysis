# -*- coding: utf-8 -*-
"""松枯れ到達 × まつたけ生産 DDD cheap kill test
入力 : tokuyo_panel_v3.csv (山梨県オープンデータ由来 都道府県別特用林産物生産量 1965-2019)
出力 : kill_test_sample.csv / kill_test_eventstudy.csv / kill_test_robustness.csv
仕様 : log(1+Y) を 県×年 + 品目×年 + 県×品目 FE に回帰、
       (到達からの経過年ダミー) × 1[品目=まつたけ] を関心係数、基準は t-1、
       イベント時間は [-8, +10] で両端binning、標準誤差は県クラスタ
"""
import pandas as pd, numpy as np, statsmodels.api as sm, warnings
warnings.filterwarnings('ignore')
SRC='/home/claude/build/tokuyo_panel_v3.csv'; OUT='/home/claude/out'
Y0,Y1=1965,1995
VALID={'num','zero_dash','repaired_x10'}          # 有効値とみなす status
ITEMS=['まつたけ','くるみ','なめこ','生しいたけ']
ARRIVAL={'宮城':1975,'新潟':1977,'山形':1978,'山梨':1978,'長野':1981,'秋田':1982}
SRC_ARRIVAL={'宮城':'宮城県サイト(石巻市大門崎)','新潟':'新潟県治山課(南魚沼市)',
             '山形':'山形県松くい虫被害対策推進計画(山形市)','山梨':'山梨県サイト',
             '長野':'長野県林業総合センター研究報告(木曽郡山口村)','秋田':'秋田県サイト(にかほ市)'}

raw=pd.read_csv(SRC,encoding='utf-8-sig')
d=raw[(raw.year.between(Y0,Y1))&(raw.item.isin(ITEMS))].copy()
d['usable']=d.status.isin(VALID)
d=d[d.usable].copy()
d['arrival']=d.pref.map(ARRIVAL)
d['arrival_source']=d.pref.map(SRC_ARRIVAL).fillna('')
d['dated']=d.arrival.notna()
d['event_time']=d.year-d.arrival
d['event_time_binned']=d.event_time.clip(-8,10)
d['is_matsutake']=(d.item=='まつたけ').astype(int)
d['ln1p_value']=np.log1p(d.value)
d['fe_pref_year']=d.pref+'_'+d.year.astype(str)
d['fe_item_year']=d.item+'_'+d.year.astype(str)
d['fe_pref_item']=d.pref+'_'+d.item
d[['year','pref','item','value','status','ln1p_value','arrival','arrival_source','dated',
   'event_time','event_time_binned','is_matsutake','fe_pref_year','fe_item_year','fe_pref_item'
  ]].sort_values(['year','pref','item']).to_csv(f'{OUT}/kill_test_sample.csv',index=False,encoding='utf-8-sig')

def fit(df, treated_item='まつたけ', arrival=ARRIVAL):
    x=df.copy()
    x['arr']=x.pref.map(arrival)
    x['etb']=(x.year-x.arr).clip(-8,10)
    x['is_t']=(x.item==treated_item).astype(int)
    ev=[int(e) for e in sorted(x.etb.dropna().unique()) if int(e)!=-1]
    for e in ev: x[f'D{e}']=((x.etb==e)&(x.is_t==1)).astype(float)
    cols=[f'D{e}' for e in ev]
    F=pd.get_dummies(x[['fe_pref_year','fe_item_year','fe_pref_item']],drop_first=True).astype(float)
    X=pd.concat([x[cols].reset_index(drop=True),F.reset_index(drop=True)],axis=1)
    r=sm.OLS(np.log1p(x.value).reset_index(drop=True),X).fit(
        cov_type='cluster',cov_kwds={'groups':x.pref.reset_index(drop=True)})
    return r, ev, x

r,ev,_=fit(d)
rows=[[e,r.params[f'D{e}'],r.bse[f'D{e}'],r.params[f'D{e}']/r.bse[f'D{e}'],
       *r.conf_int().loc[f'D{e}'].tolist()] for e in ev]
rows.append([-1,0.0,np.nan,np.nan,np.nan,np.nan])
es=pd.DataFrame(rows,columns=['event_time','coef','se_cluster_pref','t','ci_lo','ci_hi']).sort_values('event_time')
es.to_csv(f'{OUT}/kill_test_eventstudy.csv',index=False,encoding='utf-8-sig')

def summ(r,ev,label):
    pre=[f'D{e}' for e in ev if e<0]; post=[f'D{e}' for e in ev if e>=0]
    return dict(spec=label,n_obs=int(r.nobs),
                pre_mean=np.mean([r.params[c] for c in pre]),
                post_mean=np.mean([r.params[c] for c in post]),
                pre_F=float(r.f_test(', '.join(f'{c} = 0' for c in pre)).statistic),
                pre_p=float(r.f_test(', '.join(f'{c} = 0' for c in pre)).pvalue),
                post_F=float(r.f_test(', '.join(f'{c} = 0' for c in post)).statistic),
                post_p=float(r.f_test(', '.join(f'{c} = 0' for c in post)).pvalue))
res=[summ(r,ev,'主仕様: 対照3品目')]
for it in ['くるみ','なめこ','生しいたけ']:
    rr,ee,_=fit(d[d.item.isin(['まつたけ',it])]); res.append(summ(rr,ee,f'対照={it}のみ'))
for p in ARRIVAL:
    a={k:v for k,v in ARRIVAL.items() if k!=p}
    rr,ee,_=fit(d,arrival=a); res.append(summ(rr,ee,f'leave-one-out: {p}除外'))
for ti in ['くるみ','なめこ','生しいたけ']:
    rr,ee,_=fit(d,treated_item=ti); res.append(summ(rr,ee,f'プラシーボ: 処置品目={ti}'))
for sh in (-3,-2,2,3):
    a={k:v+sh for k,v in ARRIVAL.items()}
    rr,ee,_=fit(d,arrival=a); res.append(summ(rr,ee,f'到達年{sh:+d}年ずらし'))
pd.DataFrame(res).to_csv(f'{OUT}/kill_test_robustness.csv',index=False,encoding='utf-8-sig')

cov=(d[d.item=='まつたけ'].groupby('year')
     .apply(lambda g: pd.Series({'national_t':g.value.sum(),
                                 'dated6_t':g[g.dated].value.sum(),
                                 'n_positive_pref':(g.value>0).sum()})))
cov['dated6_share']=cov.dated6_t/cov.national_t
cov.reset_index().to_csv(f'{OUT}/kill_test_coverage.csv',index=False,encoding='utf-8-sig')
print('sample',len(d),'| eventstudy',len(es),'| robustness',len(res))
