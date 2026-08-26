# -*- coding: utf-8 -*-
"""記述統計と図の生成

【分母の規約】
シェアと HHI は「公表全国値」を分母に用いる。県計ではなく公表全国値を使うのは、
秘匿(x)セルが県計から抜け落ちるため。

【HHI の分母】
- 秘匿県が無い年: 県計を分母に用いる(シェア合計が 1 になる)。
  公表全国値と県計は丸めのため最大 6 t 程度ずれる年があり、公表全国値を
  分母にするとシェア合計が 1 からずれて HHI が歪む。
- 秘匿県がある年: 公表全国値を分母とし、残差 R = 公表全国値 - 実数公表県計 を
  秘匿分とみなして HHI に上下限を与える。
    下限: R を秘匿 n_x 県に均等配分(最も分散した配分)
    上限: R 全体を 1 県に集中(最も集中した配分)

【欠年の扱い】
1996-98 年は原資料が存在しない。暦年で再 index して欠年を NaN とし、
移動平均も折れ線も欠年で切る。
"""
import os
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROC = os.path.join(ROOT, 'data', 'processed')
FIG = os.path.join(ROOT, 'output', 'figures')
TAB = os.path.join(ROOT, 'output', 'tables')
os.makedirs(FIG, exist_ok=True)
os.makedirs(TAB, exist_ok=True)

# --- 日本語フォントが無ければ停止する(豆腐のまま成功終了させない) ---
CJK_CANDIDATES = ('Noto Sans CJK JP', 'IPAGothic', 'Noto Sans JP',
                  'Hiragino Sans', 'Yu Gothic', 'TakaoGothic')
_installed = {f.name for f in fm.fontManager.ttflist}
_chosen = next((c for c in CJK_CANDIDATES if c in _installed), None)
if _chosen is None:
    sys.exit(
        '日本語(CJK)フォントが見つかりません。図のラベルが豆腐になるため中止します。\n'
        f'  候補: {", ".join(CJK_CANDIDATES)}\n'
        '  Debian/Ubuntu: sudo apt-get install fonts-noto-cjk\n'
        '  macOS/Windows: Hiragino Sans / Yu Gothic が既定で利用できます')
plt.rcParams['font.family'] = _chosen
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.dpi'] = 140
plt.rcParams['savefig.bbox'] = 'tight'

VALID = {'num', 'zero_dash', 'repaired_x10'}
panel = pd.read_csv(os.path.join(PROC, 'tokuyo_panel_v3.csv'), encoding='utf-8-sig')
qa = pd.read_csv(os.path.join(PROC, 'tokuyo_itemyear_qa_v3.csv'), encoding='utf-8-sig')

mt = panel[panel.item == 'まつたけ'].copy()
CAL = list(range(1965, 2020))                      # 暦年グリッド(1996-98 は欠年)
wide = (mt[mt.status.isin(VALID)]
        .pivot_table(index='year', columns='pref', values='value')
        .reindex(CAL))
national = qa[qa.item == 'まつたけ'].set_index('year')['national'].reindex(CAL)
n_supp = mt[mt.status == 'suppressed_x'].groupby('year').size().reindex(CAL).fillna(0)
observed = sorted(qa[qa.item == 'まつたけ'].year)   # 実在する年のみ


def hhi_bounds(year):
    """(下限, 上限) を返す。秘匿県が無い年は県計を分母とし両者一致。"""
    s = wide.loc[year].dropna()
    s = s[s > 0]
    k = int(n_supp[year])
    if k == 0:
        v = float(sum(x * x for x in (s / s.sum())))   # 県計で正規化
        return v, v
    nat = national[year]
    base = sum(x * x for x in (s / nat))
    resid = max(nat - s.sum(), 0.0) / nat
    lo = base + k * (resid / k) ** 2               # 均等配分
    hi = base + resid ** 2                         # 1 県に集中
    return float(lo), float(hi)


rows = []
for y in observed:
    lo, hi = hhi_bounds(y)
    rows.append({'year': y,
                 'national_published_t': national[y],
                 'sum_positive_pref_t': wide.loc[y].sum(),
                 'n_pref_positive': int((wide.loc[y] > 0).sum()),
                 'n_pref_suppressed': int(n_supp[y]),
                 'hhi_lower': lo, 'hhi_upper': hi})
summary = pd.DataFrame(rows)
ma = national.rolling(5, center=True, min_periods=5).mean()   # 暦年グリッド上
summary['ma5_national'] = ma.reindex(summary.year).values
summary.to_csv(os.path.join(TAB, 'matsutake_national_summary.csv'),
               index=False, encoding='utf-8-sig')

# ---- 図1 ----
fig, ax = plt.subplots(figsize=(9, 4.6))
ax.plot(CAL, national.values, lw=1.0, color='#999999', label='年次(公表全国値)')
ax.plot(CAL, ma.values, lw=2.4, color='#B03A2E', label='5年移動平均')
ax.set_yscale('log')
ax.set_ylabel('生産量 (t, 対数軸)')
ax.set_xlabel('年')
ax.set_title('図1  全国まつたけ生産量 1965–2019\n'
             '(1996–98年は原資料が存在せず、線を切っている)')
ax.legend(frameon=False)
ax.grid(alpha=.25, which='both')
fig.savefig(os.path.join(FIG, 'fig1_national_production.png'))
plt.close(fig)

# ---- 図2 ----
fig, ax = plt.subplots(figsize=(9, 4.8))
palette = {'広島': '#B03A2E', '岡山': '#CA6F1E', '京都': '#B7950B',
           '長野': '#1A5276', '岩手': '#148F77'}
for p, c in palette.items():
    ax.plot(CAL, wide[p].values, lw=1.8, color=c, label=p)
ax.set_ylabel('生産量 (t)')
ax.set_xlabel('年')
ax.set_title('図2  主要県のまつたけ生産量\n'
             '旧産地(広島・岡山・京都)の大幅縮小と、長野・岩手への残存')
ax.legend(frameon=False, ncol=5)
ax.grid(alpha=.25)
fig.savefig(os.path.join(FIG, 'fig2_prefecture_trajectories.png'))
plt.close(fig)

# ---- 図3 ----
A, B = list(range(1965, 1970)), list(range(2015, 2020))
natA, natB = national[A].mean(), national[B].mean()
groups = {'広島・岡山・京都': ['広島', '岡山', '京都'],
          '長野': ['長野'], '岩手': ['岩手'], 'その他': None}
rows = []
for lab, ps in groups.items():
    if ps is None:
        used = ['広島', '岡山', '京都', '長野', '岩手']
        a = natA - wide.loc[A, used].sum(axis=1).mean()
        b = natB - wide.loc[B, used].sum(axis=1).mean()
    else:
        a = wide.loc[A, ps].sum(axis=1).mean()
        b = wide.loc[B, ps].sum(axis=1).mean()
    rows.append({'group': lab, 't_1965_69': a, 't_2015_19': b,
                 'share_1965_69': a / natA, 'share_2015_19': b / natB})
comp = pd.DataFrame(rows)
comp.to_csv(os.path.join(TAB, 'matsutake_period_comparison.csv'),
            index=False, encoding='utf-8-sig')

s = summary.set_index('year')
hhA = (s.loc[A, 'hhi_lower'].mean(), s.loc[A, 'hhi_upper'].mean())
hhB = (s.loc[B, 'hhi_lower'].mean(), s.loc[B, 'hhi_upper'].mean())

fig, axes = plt.subplots(1, 3, figsize=(11.5, 4.2))
x = np.arange(len(comp))
axes[0].bar(x - .2, comp.t_1965_69, .38, label='1965–69', color='#5D6D7E')
axes[0].bar(x + .2, comp.t_2015_19, .38, label='2015–19', color='#B03A2E')
axes[0].set_yscale('log')
axes[0].set_xticks(x)
axes[0].set_xticklabels(comp.group, rotation=30, ha='right')
axes[0].set_ylabel('平均生産量 (t, 対数軸)')
axes[0].set_title('生産量')
axes[0].legend(frameon=False)
axes[1].bar(x - .2, comp.share_1965_69 * 100, .38, color='#5D6D7E')
axes[1].bar(x + .2, comp.share_2015_19 * 100, .38, color='#B03A2E')
axes[1].set_xticks(x)
axes[1].set_xticklabels(comp.group, rotation=30, ha='right')
axes[1].set_ylabel('全国シェア (%)')
axes[1].set_title('シェア')
mid = [float(np.mean(hhA)), float(np.mean(hhB))]
err = [[mid[0] - hhA[0], mid[1] - hhB[0]], [hhA[1] - mid[0], hhB[1] - mid[1]]]
axes[2].bar(['1965–69', '2015–19'], mid, yerr=err, capsize=4,
            color=['#5D6D7E', '#B03A2E'], width=.5)
axes[2].set_ylabel('HHI')
axes[2].set_ylim(0, max(hhA[1], hhB[1]) * 1.28)
axes[2].set_title('集中度 (HHI)\n秘匿配分の上下限をエラーバーで表示', pad=12)
for i, v in enumerate(mid):
    axes[2].text(i, v + .045, f'{v:.3f}', ha='center')
fig.suptitle('図3  1965–69年 対 2015–19年:生産量・シェア・集中度', y=1.02)
fig.savefig(os.path.join(FIG, 'fig3_before_after.png'))
plt.close(fig)


def ever_positive(ys):
    """5 年間に一度でも実数で正値が確認された県の数。"""
    return int((wide.loc[ys] > 0).any(axis=0).sum())


print(f'使用フォント: {_chosen}')
print(f'\n全国  1965–69 平均 {natA:.1f} t → 2015–19 平均 {natB:.1f} t '
      f'({natB/natA-1:+.1%})')
print(f'HHI   1965–69 {hhA[0]:.3f}–{hhA[1]:.3f} → 2015–19 {hhB[0]:.3f}–{hhB[1]:.3f}')
print(f'5年間に一度でも正値が確認された県: '
      f'1965–69 {ever_positive(A)} → 2015–19 {ever_positive(B)}')
C = list(range(2006, 2011))     # 震災前の中間期(出荷制限の影響を受けない)
natC = national[C].mean()
print(f'\n参考 2006–10 平均(震災前): 全国 {natC:.1f} t / '
      f'長野 {wide.loc[C, "長野"].mean():.1f} t '
      f'({wide.loc[C, "長野"].mean()/natC:.1%}) / '
      f'旧3県 {wide.loc[C, ["広島","岡山","京都"]].sum(axis=1).mean():.1f} t '
      f'({wide.loc[C, ["広島","岡山","京都"]].sum(axis=1).mean()/natC:.1%})')
print('\n' + comp.to_string(index=False, float_format=lambda v: f'{v:8.3f}'))
print('\n単年 HHI(下限–上限)')
for y in [1965, 1970, 1980, 1990, 2000, 2010, 2019]:
    r = s.loc[y]
    print(f'  {y}  {r.hhi_lower:.4f}–{r.hhi_upper:.4f}  '
          f'実数公表 {int(r.n_pref_positive)} 県 / 秘匿 {int(r.n_pref_suppressed)} 県 '
          f'/ 公表全国 {r.national_published_t:.1f} t')

# ---- 派生ファイル: まつたけと比較候補品目の横持ち ----
CTRL = ['くるみ', 'たけのこ', 'なめこ', '生しいたけ', '乾しいたけ', 'えのきたけ']
sub = panel[panel.item.isin(['まつたけ'] + CTRL)]
val = sub.pivot_table(index=['year', 'pref'], columns='item',
                      values='value', aggfunc='first')
sta = sub.pivot_table(index=['year', 'pref'], columns='item',
                      values='status', aggfunc='first')
reg = (panel[panel.item == 'まつたけ']
       .set_index(['year', 'pref'])['regime'].reindex(val.index))
out = pd.DataFrame(index=val.index)
out['matsutake_t'] = val.get('まつたけ')
out['matsutake_status'] = sta.get('まつたけ')
out['regime'] = reg
for c in CTRL:
    out[c] = val.get(c)
    out[c + '_status'] = sta.get(c)
out.reset_index().to_csv(os.path.join(PROC, 'matsutake_analysis.csv'),
                         index=False, encoding='utf-8-sig')
print(f'\nmatsutake_analysis.csv を再生成しました ({len(out)} 行)')
