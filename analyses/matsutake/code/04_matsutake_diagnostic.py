# -*- coding: utf-8 -*-
"""まつたけ診断(最終仕様): 松くい虫の県初確認年による三重差分

【この仕様が最終である理由】
初期分析(archive/invalid_initial_analysis/)は、到達年が未確定の 41 県を
暗黙に never-treated として投入していた。該当 41 県は 1965-75 年の全国
まつたけ生産の 94.0% を保有しており、比較群としては使えない。
本スクリプトは対照県を「到達履歴が確認できた県」のみに限定する。

  処置 6 県: 宮城 1975 / 新潟 1977 / 山形 1978 / 山梨 1978 / 長野 1981 / 秋田 1982
  未処置 2 県: 北海道(松くい虫未発生) / 青森(2010 年前後に初確認、推定窓の外)

【結論】
効果推定には進まない。本命推定にもプラシーボにも事前差と対照品目依存が残り、
さらに県初確認年は県全体のアカマツ林曝露を表さないためである。
本スクリプトの出力は「効果の推定値」ではなく「診断の記録」である。

【既知の限界】
- pooled TWFE であり stacked / Callaway-Sant'Anna / BJS ではない
- クラスタは 8 県のみ。クラスタ頑健共分散行列の階数は最大 8
- 対照品目のうち「なめこ」は栽培品を含む(野生採取品ではない)
- 到達年は交換可能でないため、置換は感度診断であって p 値ではない

出力: output/matsutake_diagnostic/
"""
import os
import itertools
import numpy as np
import pandas as pd
import statsmodels.api as sm

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROC = os.path.join(ROOT, 'data', 'processed')
OUT = os.path.join(ROOT, 'output', 'matsutake_diagnostic')
os.makedirs(OUT, exist_ok=True)

VALID = {'num', 'zero_dash', 'repaired_x10'}
YEAR_LO, YEAR_HI = 1965, 1995
DROP_YEARS = {1983}          # 桁ずれの暫定補正年は主仕様から除外
ET_LO, ET_HI, BASE = -8, 10, -1

ARRIVAL = {'宮城': 1975, '新潟': 1977, '山形': 1978,
           '山梨': 1978, '長野': 1981, '秋田': 1982}
NEVER = ['北海道', '青森']
PREFS = list(ARRIVAL) + NEVER
ITEMS = ['まつたけ', 'くるみ', 'なめこ', '生しいたけ']


def load():
    d = pd.read_csv(os.path.join(PROC, 'tokuyo_panel_v3.csv'), encoding='utf-8-sig')
    d = d[d.year.between(YEAR_LO, YEAR_HI) & ~d.year.isin(DROP_YEARS)
          & d.item.isin(ITEMS) & d.status.isin(VALID) & d.pref.isin(PREFS)].copy()
    d['arrival'] = d.pref.map(ARRIVAL)
    d['event_time'] = d.year - d.arrival
    d['event_time_binned'] = d.event_time.clip(ET_LO, ET_HI)
    d['ln1p_value'] = np.log1p(d.value)
    d['fe_pref_year'] = d.pref + '_' + d.year.astype(str)
    d['fe_item_year'] = d.item + '_' + d.year.astype(str)
    d['fe_pref_item'] = d.pref + '_' + d.item
    return d


def estimate(d, treated, arrival=ARRIVAL):
    x = d.copy()
    x['arr'] = x.pref.map(arrival)
    x['etb'] = (x.year - x.arr).clip(ET_LO, ET_HI)
    x['is_t'] = (x.item == treated).astype(int)
    ev = [int(e) for e in sorted(x.etb.dropna().unique()) if int(e) != BASE]
    for e in ev:
        x[f'D{e}'] = ((x.etb == e) & (x.is_t == 1)).astype(float)
    fe = pd.get_dummies(x[['fe_pref_year', 'fe_item_year', 'fe_pref_item']],
                        drop_first=True).astype(float)
    X = sm.add_constant(
        pd.concat([x[[f'D{e}' for e in ev]].reset_index(drop=True),
                   fe.reset_index(drop=True)], axis=1), has_constant='add')
    res = sm.OLS(x.ln1p_value.reset_index(drop=True), X).fit(
        cov_type='cluster', cov_kwds={'groups': x.pref.reset_index(drop=True)})
    return res, ev


def band(res, ev, lo, hi):
    v = [res.params[f'D{e}'] for e in ev if lo <= e <= hi]
    return float(np.mean(v)) if v else np.nan


def main():
    d = load()
    d.to_csv(os.path.join(OUT, 'md_sample.csv'), index=False, encoding='utf-8-sig')

    res, ev = estimate(d, 'まつたけ')
    cols = [f'D{e}' for e in ev]
    ci = res.conf_int()
    es = pd.DataFrame({'event_time': ev,
                       'coef': [res.params[c] for c in cols],
                       'se_cluster_pref': [res.bse[c] for c in cols],
                       't': [res.params[c] / res.bse[c] for c in cols],
                       'ci_lo': [ci.loc[c, 0] for c in cols],
                       'ci_hi': [ci.loc[c, 1] for c in cols]})
    es.loc[len(es)] = [BASE, 0.0, np.nan, np.nan, np.nan, np.nan]
    es.sort_values('event_time').to_csv(
        os.path.join(OUT, 'md_eventstudy.csv'), index=False, encoding='utf-8-sig')
    res.cov_params().loc[cols, cols].to_csv(
        os.path.join(OUT, 'md_vcov.csv'), encoding='utf-8-sig')

    rows = [{'spec': '本命: まつたけ 対 くるみ・なめこ・生しいたけ',
             'n_obs': int(res.nobs), 'pre_mean': band(res, ev, ET_LO, -2),
             'post_mean': band(res, ev, 0, ET_HI)}]
    # プラシーボ: まつたけを標本から完全に除き、対照品目同士を比べる
    for a, b in itertools.combinations(['くるみ', 'なめこ', '生しいたけ'], 2):
        sub = d[d.item.isin([a, b])]
        r2, e2 = estimate(sub, a)
        rows.append({'spec': f'プラシーボ: {a} 対 {b}', 'n_obs': int(r2.nobs),
                     'pre_mean': band(r2, e2, ET_LO, -2),
                     'post_mean': band(r2, e2, 0, ET_HI)})
    # 対照品目を 1 つずつに絞った本命
    for c in ['くるみ', 'なめこ', '生しいたけ']:
        sub = d[d.item.isin(['まつたけ', c])]
        r2, e2 = estimate(sub, 'まつたけ')
        rows.append({'spec': f'本命(対照={c} のみ)', 'n_obs': int(r2.nobs),
                     'pre_mean': band(r2, e2, ET_LO, -2),
                     'post_mean': band(r2, e2, 0, ET_HI)})
    rob = pd.DataFrame(rows)
    rob.to_csv(os.path.join(OUT, 'md_robustness.csv'),
               index=False, encoding='utf-8-sig')

    # 到達年の置換(6!/2! = 360 通り全列挙)。p 値ではなく感度診断。
    obs = band(res, ev, 0, ET_HI)
    perm, seen = [], set()
    for p in itertools.permutations(list(ARRIVAL.values())):
        if p in seen:
            continue
        seen.add(p)
        a = dict(zip(list(ARRIVAL), p))
        r2, e2 = estimate(d, 'まつたけ', arrival=a)
        perm.append({'assignment': '|'.join(f'{k}:{v}' for k, v in a.items()),
                     'is_actual': int(a == ARRIVAL),
                     'pre_mean': band(r2, e2, ET_LO, -2),
                     'post_mean': band(r2, e2, 0, ET_HI)})
    pf = pd.DataFrame(perm)
    pf.to_csv(os.path.join(OUT, 'md_permutations.csv'),
              index=False, encoding='utf-8-sig')

    rank = np.linalg.matrix_rank(res.cov_params().loc[cols, cols].values)
    print(f'N = {int(res.nobs)}  クラスタ(県) = {d.pref.nunique()}  '
          f'イベントダミー = {len(ev)}  共分散行列の階数 = {rank}')
    print('\n' + rob.to_string(index=False, float_format=lambda v: f'{v:9.4f}'))
    n_ge = int((pf.post_mean >= obs).sum())
    print(f'\n置換診断: 全 {len(pf)} 通り中 {n_ge} 通りが実際以上 '
          f'= {n_ge/len(pf):.4f}（p 値ではなく感度診断）')
    print('\n判定: 本命の事後平均は正、事前平均も同程度に正。プラシーボは対照品目に')
    print('      よって +0.15 から -0.36 まで動く。効果推定には進まない。')


if __name__ == '__main__':
    main()
