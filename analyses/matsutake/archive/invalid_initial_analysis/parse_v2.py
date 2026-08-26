# -*- coding: utf-8 -*-
"""都道府県別特用林産物生産量 (山梨県オープンデータ / 農林水産省統計表由来) v2 パーサ
設計方針:
  - 原値と状態を保存し、意味付け(ゼロ/欠測)は列単位の加算恒等式で判定する
  - 単位は原票の単位行をそのまま保持し、系列接続はしない
"""
import xlrd, glob, re, csv, os, json, collections

SRC = '/home/claude/y'
OUT = '/home/claude/build'

PREF = ['北海道','青森','岩手','宮城','秋田','山形','福島','茨城','栃木','群馬','埼玉','千葉',
        '東京','神奈川','新潟','富山','石川','福井','山梨','長野','岐阜','静岡','愛知','三重',
        '滋賀','京都','大阪','兵庫','奈良','和歌山','鳥取','島根','岡山','広島','山口','徳島',
        '香川','愛媛','高知','福岡','佐賀','長崎','熊本','大分','宮崎','鹿児島','沖縄']
NORM = {}
for p in PREF:
    NORM[p] = p
    for s in ('県','府','都','道'):
        NORM[p+s] = p
NORM['沖繩'] = '沖縄'; NORM['沖繩県'] = '沖縄'   # 旧字体
NORM['北海道'] = '北海道'

ITEM_CANON = {'乾燥しいたけ':'乾しいたけ', 'くり※１':'くり', 'くるみ※２':'くるみ'}
DASH = {'-','‐','－','―','ー','–'}

def year_of(fn):
    m = re.search(r'_(s|h)(\d+)\.xls$', fn)
    era, n = m.group(1), int(m.group(2))
    return 1925 + n if era == 's' else 1988 + n

def classify(raw):
    """セル生値 -> (float|None, kind)  kind in {num, dash, x, blank, other}"""
    if raw is None:
        return None, 'blank'
    s = str(raw).strip().replace('\u3000', '')
    if s == '':
        return None, 'blank'
    if s in DASH:
        return None, 'dash'
    if s.lower() == 'x':
        return None, 'x'
    try:
        return float(s), 'num'
    except ValueError:
        return None, 'other'

rows, qa = [], []
files = sorted(glob.glob(os.path.join(SRC, '*.xls')), key=lambda f: year_of(os.path.basename(f)))

for path in files:
    fn = os.path.basename(path)
    y = year_of(fn)
    sh = xlrd.open_workbook(path).sheet_by_index(0)
    units = [str(sh.cell_value(2, c)).strip() for c in range(sh.ncols)]
    hdr   = [str(sh.cell_value(3, c)).strip() for c in range(sh.ncols)]

    nat_row = next((r for r in range(4, sh.nrows)
                    if str(sh.cell_value(r, 0)).strip().replace('\u3000','') == '日本'), None)

    # 県行の収集
    pref_rows = {}
    for r in range(4, sh.nrows):
        a = str(sh.cell_value(r, 0)).strip().replace('\u3000','')
        p = NORM.get(a)
        if p and p not in pref_rows:
            pref_rows[p] = r

    for c in range(1, sh.ncols):
        item_raw = hdr[c]
        if not item_raw:
            continue
        item = ITEM_CANON.get(item_raw, item_raw)
        unit = units[c]

        nat_val, nat_kind = classify(sh.cell_value(nat_row, c)) if nat_row is not None else (None,'blank')
        item_observed = (nat_kind == 'num')

        s_num = 0.0; n_num = n_dash = n_x = n_blank = 0
        cells = []
        for p in PREF:
            r = pref_rows.get(p)
            if r is None:
                cells.append((p, '', None, 'not_in_source')); continue
            raw = sh.cell_value(r, c)
            v, kind = classify(raw)
            if kind == 'num':
                s_num += v; n_num += 1; st = 'num'
            elif kind == 'x':
                n_x += 1; st = 'suppressed_x'
            elif kind == 'dash':
                n_dash += 1
                st = 'zero_dash' if item_observed else 'item_unobserved'
                if st == 'zero_dash':
                    v = 0.0
            elif kind == 'blank':
                n_blank += 1
                st = 'item_unobserved' if not item_observed else 'blank'
            else:
                st = 'other'
            cells.append((p, str(raw).strip(), v, st))

        gap = (nat_val - s_num) if item_observed else None
        tol = 0.005 * max(abs(nat_val), 1.0) + 1.0 if item_observed else None
        consistent = (abs(gap) <= tol) if item_observed else None
        # 加算恒等式が破れている年×品目は県値を信用しない
        suspect = item_observed and not consistent and n_x == 0

        for p, raw, v, st in cells:
            if suspect and st in ('num', 'zero_dash'):
                st = 'suspect_' + st
            rows.append([y, p, item, item_raw, raw, ('' if v is None else v), st, unit, fn])

        qa.append([y, item, unit,
                   ('' if nat_val is None else nat_val), nat_kind,
                   round(s_num, 3), ('' if gap is None else round(gap, 3)),
                   ('' if consistent is None else int(consistent)),
                   n_num, n_dash, n_x, n_blank,
                   len(pref_rows), int(item_observed), int(bool(suspect)), fn])

with open(f'{OUT}/tokuyo_panel_v2.csv', 'w', newline='', encoding='utf-8-sig') as fh:
    w = csv.writer(fh)
    w.writerow(['year','pref','item','item_raw','raw_value','value','status','unit','source_file'])
    w.writerows(rows)
with open(f'{OUT}/tokuyo_itemyear_qa.csv', 'w', newline='', encoding='utf-8-sig') as fh:
    w = csv.writer(fh)
    w.writerow(['year','item','unit','national','national_kind','sum_pref','gap','consistent',
                'n_num','n_dash','n_x','n_blank','n_pref_rows','item_observed','suspect','source_file'])
    w.writerows(qa)
print('panel rows', len(rows), '| item-year rows', len(qa))
