# -*- coding: utf-8 -*-
"""都道府県別特用林産物生産量 v3
v2からの変更:
  - 1983年型の「一部セル10分の1化」を2規則で自動検出・復元 (status=repaired_x10)
  - 原値(value_raw)と復元値(value)を分離保持
  - 公表様式レジーム(全県掲載 / 正値のみ掲載)を年×品目で判定
  - 単位ラベル変更に加え、ラベル不変のまま起きた尺度断層を検出
"""
import xlrd, glob, re, csv, os, collections

import os, sys
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
SRC=os.path.join(ROOT,'data','raw'); OUT=os.path.join(ROOT,'data','processed')
PREF = ['北海道','青森','岩手','宮城','秋田','山形','福島','茨城','栃木','群馬','埼玉','千葉',
        '東京','神奈川','新潟','富山','石川','福井','山梨','長野','岐阜','静岡','愛知','三重',
        '滋賀','京都','大阪','兵庫','奈良','和歌山','鳥取','島根','岡山','広島','山口','徳島',
        '香川','愛媛','高知','福岡','佐賀','長崎','熊本','大分','宮崎','鹿児島','沖縄']
NORM = {}
for p in PREF:
    NORM[p] = p
    for s in ('県','府','都','道'): NORM[p+s] = p
NORM['沖繩'] = NORM['沖繩県'] = '沖縄'
ITEM_CANON = {'乾燥しいたけ':'乾しいたけ','くり※１':'くり','くるみ※２':'くるみ'}
DASH = {'-','‐','－','―','ー','–'}
TOL_PCT = 0.02          # これを超える不一致を suspect とする
AUTO_SCALE_RATIO = 20   # 自動検出の閾値(前年比 20 倍超 / 1/20 未満)

# 自動閾値(20 倍)では検出されないが、原票の突き合わせで確認した既知の断層。
# (year, item) -> flag
MANUAL_BREAKS = {
    (1973, 'くり'):  'manual_known_break',   # 1972: 2,837 t -> 1973: 470 t
    (1988, 'くるみ'): 'manual_known_break',  # 1987: 100 t -> 1988: 752 t
}
REPAIR_RATIO = 0.35     # 前後年平均に対しこの比率未満なら桁落ち候補

def year_of(fn):
    m = re.search(r'_(s|h)(\d+)\.xls$', fn); era, n = m.group(1), int(m.group(2))
    return 1925 + n if era == 's' else 1988 + n

def classify(raw):
    if raw is None: return None, 'blank'
    s = str(raw).strip().replace('\u3000','')
    if s == '': return None, 'blank'
    if s in DASH: return None, 'dash'
    if s.lower() == 'x': return None, 'x'
    try: return float(s), 'num'
    except ValueError: return None, 'other'

# ---------- 読み込み ----------
book = {}   # (year, item) -> dict(pref -> (raw, val, kind)), plus meta
meta = {}
for path in sorted(glob.glob(os.path.join(SRC,'*.xls')), key=lambda f: year_of(os.path.basename(f))):
    fn = os.path.basename(path); y = year_of(fn)
    sh = xlrd.open_workbook(path).sheet_by_index(0)
    units = [str(sh.cell_value(2,c)).strip() for c in range(sh.ncols)]
    hdr   = [str(sh.cell_value(3,c)).strip() for c in range(sh.ncols)]
    nat_r = next((r for r in range(4,sh.nrows)
                  if str(sh.cell_value(r,0)).strip().replace('\u3000','')=='日本'), None)
    prow = {}
    for r in range(4, sh.nrows):
        p = NORM.get(str(sh.cell_value(r,0)).strip().replace('\u3000',''))
        if p and p not in prow: prow[p] = r
    for c in range(1, sh.ncols):
        if not hdr[c]: continue
        item = ITEM_CANON.get(hdr[c], hdr[c])
        cells = {}
        for p in PREF:
            r = prow.get(p)
            if r is None: cells[p] = ('', None, 'absent'); continue
            raw = sh.cell_value(r,c); v,k = classify(raw)
            cells[p] = (str(raw).strip(), v, k)
        natraw = sh.cell_value(nat_r,c) if nat_r is not None else None
        natv, natk = classify(natraw)
        book[(y,item)] = cells
        meta[(y,item)] = dict(unit=units[c], item_raw=hdr[c], file=fn,
                              nat=natv, natk=natk, n_pref=len(prow))

years  = sorted({y for y,_ in book})
items  = sorted({i for _,i in book})

# ---------- 尺度断層の検出(単位ラベル不変のまま) ----------
scale_break = set()
for it in items:
    ys = [y for y in years if (y,it) in meta and meta[(y,it)]['nat'] is not None]
    for a,b in zip(ys, ys[1:]):
        na, nb = meta[(a,it)]['nat'], meta[(b,it)]['nat']
        ua, ub = meta[(a,it)]['unit'], meta[(b,it)]['unit']
        if na > 0 and nb > 0:
            ratio = nb/na
            if ratio > AUTO_SCALE_RATIO or ratio < 1 / AUTO_SCALE_RATIO:
                scale_break.add((b, it, 'unit_label_change' if ua != ub else 'unmarked_scale_break'))

# ---------- 復元 ----------
def try_repair(y, item):
    """returns (values dict pref->repaired, rule) or (None,None)"""
    m = meta[(y,item)]; nat = m['nat']
    if nat is None: return None, None
    cells = book[(y,item)]
    prev = book.get((y-1,item)); nxt = book.get((y+1,item))
    def base(): return {p:c[1] for p,c in cells.items() if c[2]=='num'}
    cands = {}
    # 規則A: 小数第1位が非ゼロ
    a = {}
    for p,v in base().items():
        a[p] = v*10 if round(v*10) % 10 != 0 else v
    cands['decimal'] = a
    # 規則B: 前後年平均比
    b = {}
    for p,v in base().items():
        refs = []
        for src in (prev, nxt):
            if src and src.get(p) and src[p][2]=='num' and src[p][1] > 0: refs.append(src[p][1])
        ref = sum(refs)/len(refs) if refs else None
        b[p] = v*10 if (ref and v > 0 and v/ref < REPAIR_RATIO) else v
    cands['neighbor'] = b
    tol = TOL_PCT*abs(nat) + 1.0
    for rule in ('decimal','neighbor'):
        if abs(nat - sum(cands[rule].values())) <= tol:
            return cands[rule], rule
    return None, None

rows, qa = [], []
for (y,item), cells in sorted(book.items()):
    m = meta[(y,item)]; nat, natk = m['nat'], m['natk']
    observed = (natk == 'num')
    nums = {p:c[1] for p,c in cells.items() if c[2]=='num'}
    n_dash = sum(1 for c in cells.values() if c[2]=='dash')
    n_x    = sum(1 for c in cells.values() if c[2]=='x')
    n_abs  = sum(1 for c in cells.values() if c[2]=='absent')
    s0 = sum(nums.values())
    gap = (nat - s0) if observed else None
    gap_pct = (gap/nat) if (observed and nat) else None
    tol = TOL_PCT*abs(nat) + 1.0 if observed else None
    ok = (abs(gap) <= tol) if observed else None   # 補正前の判定

    repaired, rule = (None, None)
    if observed and not ok and n_x == 0:
        repaired, rule = try_repair(y, item)

    # 公表様式レジーム
    regime = 'all_listed' if (observed and n_dash == 0 and n_abs == 0) else \
             ('positive_only' if observed else 'unobserved')
    sb = [t for (yy,ii,t) in scale_break if yy==y and ii==item]
    if not sb and (y, item) in MANUAL_BREAKS:
        sb = [MANUAL_BREAKS[(y, item)]]

    for p in PREF:
        raw, v, k = cells[p]
        if k == 'num':
            st = 'num'; val = v
            if repaired is not None and abs(repaired[p]-v) > 1e-9:
                st = 'repaired_x10'; val = repaired[p]
            elif observed and not ok and repaired is None:
                st = 'gap_w_suppression' if n_x > 0 else 'suspect_num'
        elif k == 'dash':
            if observed: st, val = 'zero_dash', 0.0
            else:        st, val = 'item_unobserved', None
        elif k == 'x':   st, val = 'suppressed_x', None
        elif k == 'absent': st, val = 'not_in_source', None
        elif k == 'blank':
            st, val = ('item_unobserved', None) if not observed else ('blank', None)
        else: st, val = 'other', None
        rows.append([y,p,item,m['item_raw'],raw,('' if v is None else v),
                     ('' if val is None else round(val,4)), st, m['unit'],
                     regime, (sb[0] if sb else ''), m['file']])

    s1 = sum(repaired.values()) if repaired else s0
    gap1 = (nat - s1) if observed else None
    ok1 = (abs(gap1) <= tol) if observed else None   # 補正後の判定
    qa.append([y,item,m['unit'],('' if nat is None else nat),natk,
               round(s0,3), round(s1,3),
               ('' if gap is None else round(gap,3)),
               ('' if gap_pct is None else round(gap_pct,5)),
               ('' if ok is None else int(ok)),
               ('' if ok1 is None else int(ok1)), (rule or ''),
               ('suppression' if (observed and not ok and repaired is None and n_x>0)
                else ('unresolved' if (observed and not ok and repaired is None) else '')),
               len(nums),n_dash,n_x,n_abs,regime,(sb[0] if sb else ''),m['file']])

with open(f'{OUT}/tokuyo_panel_v3.csv','w',newline='',encoding='utf-8-sig') as fh:
    w=csv.writer(fh)
    w.writerow(['year','pref','item','item_raw','raw_value','value_raw','value',
                'status','unit','regime','scale_flag','source_file'])
    w.writerows(rows)
with open(f'{OUT}/tokuyo_itemyear_qa_v3.csv','w',newline='',encoding='utf-8-sig') as fh:
    w=csv.writer(fh)
    w.writerow(['year','item','unit','national','national_kind','sum_raw','sum_repaired',
                'gap','gap_pct','consistent_raw','consistent_repaired','repair_rule','gap_reason',
                'n_num','n_dash','n_x','n_absent',
                'regime','scale_flag','source_file'])
    w.writerows(qa)
print('panel', len(rows), '| item-year', len(qa))
print('repaired item-years:', sorted({(q[0],q[1],q[11]) for q in qa if q[11]}))
print('unresolved suspect :', sorted({(q[0],q[1]) for q in qa if q[10]==0 and not q[11]}))
print('scale flags (auto):', sorted(scale_break))
print('scale flags (manual):', sorted((y,i,f) for (y,i),f in MANUAL_BREAKS.items()))
