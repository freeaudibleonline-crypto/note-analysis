# -*- coding: utf-8 -*-
"""e-Stat から樹種別素材生産量パネルを取得する(任意)

`data/processed/timber_pref_species_1960_2013.csv` は取得済みのものを同梱して
いるため、通常このスクリプトを実行する必要はない。原典から取り直したい場合、
または取得の再現性を確認したい場合にのみ使用する。

取得対象:
  農林水産省「木材統計調査 長期累年
  『木材需給報告書 主要樹種別素材生産量累年統計 都道府県別』」
  statsDataId = 0003234708
  1960-2013 年 / 47 都道府県 + 全国 / 13 樹種区分 / 単位 千 m3

実行には e-Stat のアプリケーション ID が必要。
  https://www.e-stat.go.jp/mypage/user/preregister で登録し、
  マイページからアプリケーション ID を発行する。

使い方:
  export ESTAT_APP_ID=xxxxxxxx
  python 00_fetch_estat_timber.py

注意: 素材生産量は森林ストックの測定値ではなく、製材・合板・木材チップ工場への
入荷量である。DATA-LICENSE.md の該当節を参照のこと。
"""
import os
import sys
import json
import urllib.request
import urllib.parse
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'processed')
STATS_DATA_ID = '0003234708'
ENDPOINT = 'https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData'

SPECIES_ORDER = ['計', '針葉樹_計', '針葉樹_あかまつ・くろまつ', '針葉樹_すぎ',
                 '針葉樹_ひのき', '針葉樹_もみ・つが', '針葉樹_からまつ',
                 '針葉樹_えぞまつ・とどまつ', '針葉樹_その他', '広葉樹_計',
                 '広葉樹_なら', '広葉樹_ぶな', '広葉樹_その他']


def main():
    app_id = os.environ.get('ESTAT_APP_ID', '').strip()
    if not app_id:
        sys.exit('環境変数 ESTAT_APP_ID が設定されていません。\n'
                 '  export ESTAT_APP_ID=xxxxxxxx\n'
                 'ID は https://www.e-stat.go.jp/ のマイページで発行できます。\n'
                 '（末尾に空白が混入すると認証エラー STATUS=100 になります）')
    params = {'appId': app_id, 'lang': 'J', 'statsDataId': STATS_DATA_ID,
              'metaGetFlg': 'Y', 'cntGetFlg': 'N', 'sectionHeaderFlg': '1'}
    url = ENDPOINT + '?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=120) as r:
        payload = json.load(r)

    root = payload['GET_STATS_DATA']
    status = root['RESULT']['STATUS']
    if status != 0:
        sys.exit(f"e-Stat API エラー STATUS={status}: {root['RESULT']['ERROR_MSG']}")

    sd = root['STATISTICAL_DATA']
    maps = {}
    for obj in sd['CLASS_INF']['CLASS_OBJ']:
        cls = obj['CLASS']
        if isinstance(cls, dict):
            cls = [cls]
        maps[obj['@id']] = {c['@code']: c['@name'] for c in cls}

    recs = []
    for v in sd['DATA_INF']['VALUE']:
        try:
            val = float(v['$'])
        except (ValueError, TypeError):
            val = None
        recs.append({'year': int(v['@time'][:4]),
                     'pref': maps['area'][v['@area']],
                     'sp': maps['cat01'][v['@cat01']],
                     'v': val})
    df = (pd.DataFrame(recs)
          .pivot_table(index=['year', 'pref'], columns='sp', values='v')
          .reindex(columns=SPECIES_ORDER)
          .reset_index())
    df.columns.name = None
    path = os.path.join(OUT, 'timber_pref_species_1960_2013.csv')
    df.to_csv(path, index=False, encoding='utf-8-sig')
    print(f'{len(df)} 行を {path} に書き出しました '
          f'({df.year.min()}-{df.year.max()}, {df.pref.nunique()} 地域)')
    print('注記:', sd['TABLE_INF']['TITLE_SPEC'].get('TABLE_EXPLANATION', ''))


if __name__ == '__main__':
    main()
