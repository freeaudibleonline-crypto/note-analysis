# -*- coding: utf-8 -*-
"""Gate 5 診断: 松くい虫の県初確認年と、あかまつ・くろまつ素材生産量

【この推定が「生態学的 first-stage」ではない理由】
素材生産量は、農林水産省の定義上、山元供給を直接測ったものではなく
製材・合板・チップ工場への「入荷量」である。したがって

    素材生産量 = f(森林在庫, 需要, 価格, 伐採採算, 工場能力, 被害木の利用)

であり、森林ストックの指標ではない。また「あかまつ・くろまつ」は合算値で、
海岸クロマツ林の被害と内陸アカマツ林(マツタケの宿主)が分離できない。
本スクリプトの結果は first-stage の確認ではなく、
「入手可能な指標では first-stage を測れなかった」ことの記録である。

【推定上の既知の限界】
- pooled TWFE であり、stacked / Callaway-Sant'Anna / BJS ではない。
  効果が異質な staggered 設定では、既処置コホートが比較に混入しうる。
- クラスタは 8 県のみ。クラスタ頑健共分散行列の階数は最大 8 で、
  イベントダミー 22 本の同時検定は信頼できない。
  事前係数の同時検定 p 値は「平坦性の証拠」として解釈してはならない。
- 到達年は緯度・気候・隣接伝播で決まるため交換可能ではない。
  到達年の置換は正式な randomization inference ではなく感度診断である。

出力: output/firststage/ 配下
"""
import os
import itertools
import numpy as np
import pandas as pd
import statsmodels.api as sm

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROC = os.path.join(ROOT, 'data', 'processed')
OUT = os.path.join(ROOT, 'output', 'firststage')
os.makedirs(OUT, exist_ok=True)

YEAR_LO, YEAR_HI = 1960, 1999        # 2000年以降は木材統計の調査方法変更のため除外
ET_LO, ET_HI = -10, 12               # イベント時間の両端 binning
BASE = -1                            # 基準イベント時
MID = (5, 9)                         # 主効果とする事後帯

ARRIVAL = {'宮城': 1975, '新潟': 1977, '山形': 1978,
           '山梨': 1978, '長野': 1981, '秋田': 1982}
ARRIVAL_SOURCE = {
    '宮城': '宮城県公式サイト(石巻市大門崎, 昭和50年)',
    '新潟': '新潟県治山課(南魚沼市, 昭和52年度)',
    '山形': '山形県松くい虫被害対策推進計画(山形市, 昭和53年)',
    '山梨': '山梨県公式サイト(昭和53年)',
    '長野': '長野県林業総合センター研究報告(木曽郡山口村, 昭和56年)',
    '秋田': '秋田県公式サイト(にかほ市旧象潟町, 昭和57年度)',
}
# 未処置として使える県は、到達履歴が確認できた県に限る。
# 北海道 = 松くい虫未発生 / 青森 = 2010年前後に県内初確認(推定窓の外)
NEVER = ['北海道', '青森']
SPECIES = {'針葉樹_あかまつ・くろまつ': 'matsu',
           '針葉樹_すぎ': 'sugi',
           '針葉樹_ひのき': 'hinoki'}
PREFS = list(ARRIVAL) + NEVER


def load():
    t = pd.read_csv(os.path.join(PROC, 'timber_pref_species_1960_2013.csv'),
                    encoding='utf-8-sig')
    t = t[(t.pref != '全国') & t.year.between(YEAR_LO, YEAR_HI)].copy()
    t['pref'] = t.pref.str.replace('県$|府$|都$', '', regex=True)
    t = t[t.pref.isin(PREFS)]
    grid = pd.MultiIndex.from_product(
        [range(YEAR_LO, YEAR_HI + 1), PREFS, list(SPECIES.values())],
        names=['year', 'pref', 'sp']).to_frame(index=False)
    long = t[['year', 'pref'] + list(SPECIES)].melt(
        id_vars=['year', 'pref'], var_name='sp_raw', value_name='v')
    long['sp'] = long.sp_raw.map(SPECIES)
    merged = grid.merge(long[['year', 'pref', 'sp', 'v']],
                        on=['year', 'pref', 'sp'], how='left')
    missing = merged[merged.v.isna()].copy()
    d = merged.dropna(subset=['v']).copy()
    d['arrival'] = d.pref.map(ARRIVAL)
    d['arrival_source'] = d.pref.map(ARRIVAL_SOURCE).fillna('')
    d['event_time'] = d.year - d.arrival
    d['event_time_binned'] = d.event_time.clip(ET_LO, ET_HI)
    d['is_matsu'] = (d.sp == 'matsu').astype(int)
    d['ln1p_v'] = np.log1p(d.v)
    d['fe_pref_year'] = d.pref + '_' + d.year.astype(str)
    d['fe_sp_year'] = d.sp + '_' + d.year.astype(str)
    d['fe_pref_sp'] = d.pref + '_' + d.sp
    return d, missing


def estimate(d, treated='matsu', arrival=ARRIVAL):
    x = d.copy()
    x['arr'] = x.pref.map(arrival)
    x['etb'] = (x.year - x.arr).clip(ET_LO, ET_HI)
    x['is_t'] = (x.sp == treated).astype(int)
    ev = [int(e) for e in sorted(x.etb.dropna().unique()) if int(e) != BASE]
    for e in ev:
        x[f'D{e}'] = ((x.etb == e) & (x.is_t == 1)).astype(float)
    fe = pd.get_dummies(x[['fe_pref_year', 'fe_sp_year', 'fe_pref_sp']],
                        drop_first=True).astype(float)
    X = sm.add_constant(
        pd.concat([x[[f'D{e}' for e in ev]].reset_index(drop=True),
                   fe.reset_index(drop=True)], axis=1), has_constant='add')
    res = sm.OLS(np.log1p(x.v).reset_index(drop=True), X).fit(
        cov_type='cluster', cov_kwds={'groups': x.pref.reset_index(drop=True)})
    return res, ev


def band(res, ev, lo, hi):
    return float(np.mean([res.params[f'D{e}'] for e in ev if lo <= e <= hi]))


def main():
    d, missing = load()
    missing.to_csv(os.path.join(OUT, 'fs_missing_cells.csv'),
                   index=False, encoding='utf-8-sig')
    d.to_csv(os.path.join(OUT, 'fs_sample.csv'),
             index=False, encoding='utf-8-sig')

    res, ev = estimate(d)
    cols = [f'D{e}' for e in ev]
    ci = res.conf_int()
    es = pd.DataFrame({
        'event_time': ev,
        'coef': [res.params[c] for c in cols],
        'se_cluster_pref': [res.bse[c] for c in cols],
        't': [res.params[c] / res.bse[c] for c in cols],
        'ci_lo': [ci.loc[c, 0] for c in cols],
        'ci_hi': [ci.loc[c, 1] for c in cols],
    })
    es.loc[len(es)] = [BASE, 0.0, np.nan, np.nan, np.nan, np.nan]
    es = es.sort_values('event_time')
    es.to_csv(os.path.join(OUT, 'fs_eventstudy.csv'),
              index=False, encoding='utf-8-sig')
    res.cov_params().loc[cols, cols].to_csv(
        os.path.join(OUT, 'fs_vcov.csv'), encoding='utf-8-sig')

    obs = band(res, ev, *MID)
    rows = []
    seen = set()
    for perm in itertools.permutations(list(ARRIVAL.values())):
        if perm in seen:
            continue
        seen.add(perm)
        a = dict(zip(list(ARRIVAL), perm))
        r2, e2 = estimate(d, arrival=a)
        rows.append({'assignment': '|'.join(f'{k}:{v}' for k, v in a.items()),
                     'is_actual': int(a == ARRIVAL),
                     'pre_mean': band(r2, e2, ET_LO, -2),
                     'mid_5_9': band(r2, e2, *MID)})
    pf = pd.DataFrame(rows)
    pf.to_csv(os.path.join(OUT, 'fs_permutations.csv'),
              index=False, encoding='utf-8-sig')

    n_le = int((pf.mid_5_9 <= obs).sum())
    print(f'N = {int(res.nobs)}  クラスタ(県) = {d.pref.nunique()}  '
          f'イベントダミー = {len(ev)}')
    print(f'共分散行列の階数 = '
          f'{np.linalg.matrix_rank(res.cov_params().loc[cols, cols].values)} '
          f'(<= クラスタ数。同時検定は信頼できない)')
    print(f'事前平均(t<=-2) = {band(res, ev, ET_LO, -2):+.4f}')
    print(f'事後 {MID[0]}-{MID[1]} 年 = {obs:+.4f}  '
          f'(= {np.expm1(obs):+.1%})')
    print(f'置換診断: 全 {len(pf)} 通り中 {n_le} 通りが実際以下 '
          f'= {n_le/len(pf):.4f}')
    print('  ※ 到達年は交換可能でないため、これは p 値ではなく感度診断である。')
    print(f'欠測セル {len(missing)} 件 (すべて北海道のひのき)')


if __name__ == '__main__':
    main()
