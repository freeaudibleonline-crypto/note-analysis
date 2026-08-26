# 出典一覧

すべての URL について、公開前に**閲覧日を記入**すること（`____年__月__日` の箇所）。
自治体・省庁のページは改廃されうるため、可能なら Wayback Machine 等の
アーカイブ URL も併記することを推奨する。

---

## 1. 特用林産物生産量パネル（1965–2019年）

**原典**
農林水産省『特用林産基礎資料』および『農林水産省統計表』

**取得経路**
山梨県オープンデータカタログ「都道府県別特用林産物生産量」
データセット ID `12594_edfa08000`
- カタログ: `https://catalog.dataplatform-yamanashi.jp/dataset/12594_edfa08000`
- CKAN API: `https://catalog.dataplatform-yamanashi.jp/api/3/action/package_show?id=12594_edfa08000`
- 取得日: ____年__月__日
- ファイル 52 本の SHA-256: `data/raw/CHECKSUMS.md`

**利用条件**
山梨県オープンデータ利用規約
`https://www.pref.yamanashi.jp/opendata/kiyaku.html`（閲覧日 ____年__月__日）

---

## 2. 樹種別素材生産量パネル（1960–2013年）

**原典**
農林水産省「木材統計調査 長期累年『木材需給報告書 主要樹種別素材生産量累年統計
都道府県別』」

- e-Stat `statsDataId = 0003234708`
- 政府統計コード `00500217`（木材統計調査）
- 取得日: ____年__月__日
- 取得コード: `code/00_fetch_estat_timber.py`

**素材生産量の定義について**
農林水産省「木材統計調査の概要」
`https://www.maff.go.jp/j/tokei/kouhyou/mokuzai/gaiyou/index.html`
（閲覧日 ____年__月__日）

山元での供給量を直接調査することが困難なため、製材工場・合板工場・木材チップ
工場への**素材入荷量**をもって素材供給量としている旨が記されている。

**利用条件**
政府統計の総合窓口（e-Stat）利用規約
`https://www.e-stat.go.jp/terms-of-use`（閲覧日 ____年__月__日）

---

## 3. 特用林産物の分類について

農林水産省「林業産出額」の概要
`https://www.maff.go.jp/j/tokei/kouhyou/ringyou_sansyutu/gaiyou/index.html`
（閲覧日 ____年__月__日）

「なめこ」は栽培品を含む。本リポジトリでは野生採取品として扱わず、
「非宿主の比較候補」と位置づけている。

---

## 4. 松くい虫（マツ材線虫病）の県別初確認年

いずれも県の公表資料による。**「県内のどこか一市町村で初めて確認された年」で
あって、県全体のマツ林が曝露された時点ではない。**

| 県 | 年 | 初確認地 | 文書名 | URL | 閲覧日 |
|---|---|---|---|---|---|
| 宮城 | 1975（昭和50） | 石巻市大門崎 | 宮城県「松くい虫被害対策」 | `https://www.pref.miyagi.jp/soshiki/et-sgsin-r/matsukui.html` | ____ |
| 新潟 | 1977年度（昭和52年度） | 南魚沼市（旧六日町・旧塩沢町） | 新潟県治山課「令和6年度松くい虫被害の状況について」 | `https://www.pref.niigata.lg.jp/sec/chisan/1221588125296.html` | ____ |
| 山形 | 1978（昭和53） | 山形市 | 山形県「松くい虫被害対策推進計画（令和4年度〜8年度）」 p.1 | `https://www.pref.yamagata.jp/documents/19501/keikakur4~r8.pdf` | ____ |
| 山梨 | 1978（昭和53） | ― | 山梨県「松くい虫被害について」 | `https://www.pref.yamanashi.jp/shinrin-sb/shinrin_matukui.html` | ____ |
| 長野 | 1981（昭和56） | 木曽郡山口村 | 長野県林業総合センター「長野県における松くい虫の被害とその特徴」pp.5–8 | `https://www.pref.nagano.lg.jp/ringyosogo/seika/gijyutsu/documents/053-3.pdf` | ____ |
| 秋田 | 1982年度（昭和57年度） | にかほ市（旧象潟町） | 秋田県「松くい虫被害について」 | `https://www.pref.akita.lg.jp/pages/archive/802` | ____ |

### 未処置として扱った 2 県の根拠

| 県 | 扱い | 根拠 |
|---|---|---|
| 北海道 | 松くい虫未発生 | 林野庁「松くい虫被害」。全国の被害は「北海道を除く46都府県」と一貫して記載されている。`https://www.rinya.maff.go.jp/j/hogo/higai/matukui.html`（閲覧日 ____） |
| 青森 | 2010年1月に蓬田村で県内初確認（推定窓 1965–1999 の外） | 青森県「森林病害虫等の防除」`https://www.pref.aomori.lg.jp/soshiki/nourin/rinsei/byougaichu.html`（閲覧日 ____） |

### 東北地方の下限に関する補助的根拠

林野庁 東北森林管理局「松くい虫被害対策について」
`https://www.rinya.maff.go.jp/tohoku/policy/business/management/hozen/matukui.html`
（閲覧日 ____年__月__日）

管内では昭和50年代に宮城県で初めて確認され、その後他県へ拡大した旨が記されて
おり、東北 6 県の到達年が 1975 年以降であることの下限根拠になる。

---

## 5. 本文で言及したその他の事実

| 記述 | 出典 | URL | 閲覧日 |
|---|---|---|---|
| 2023年の都道府県別まつたけ（実数14県・秘匿9県・ゼロ24県） | 農林水産省「令和5年特用林産基礎資料」表1-2 きのこ類の生産量 | e-Stat `toukei=00501004&tstat=000001021191` | ____ |
| 松くい虫が1905年に長崎で初確認 | 林野庁「松くい虫被害」 | `https://www.rinya.maff.go.jp/j/hogo/higai/matukui.html` | ____ |
| 『森林・林業統計要覧』表87「特用林産物生産量」（1巻1年分、2018年以降のみ公開） | 林野庁「森林・林業統計要覧」 | `https://www.rinya.maff.go.jp/j/kikaku/toukei/youran.html` | ____ |
| 『特用林産基礎資料』の該当巻が国立国会図書館内限定 | 国立国会図書館デジタルコレクション | `https://dl.ndl.go.jp/` | ____ |

---

## 6. 分析期間の上限（2011年）に関する根拠

原子力災害対策特別措置法第20条に基づく出荷制限指示。まつたけを含む
「野生きのこ類」、原木しいたけ、なめこ、たけのこ、わらび、ぜんまい等が、
市町村単位で規制対象となっている。

**引用すべき具体的文書**（いずれも閲覧日 ____年__月__日を記入すること）

- 厚生労働省「東日本大震災関連情報 — 食品中の放射性物質への対応」
  出荷制限等の品目・区域一覧
  `https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000045810.html`
- 岩手県「県産農林水産物の出荷制限等の状況」
  `https://www.pref.iwate.jp/kurashikankyou/shokuhin/hoshanou/index.html`
- 福島県「野生きのこ・山菜の出荷制限等の状況」
  `https://www.pref.fukushima.lg.jp/sec/36035b/`

制限・解除の一覧は随時更新されるため、引用時は**版と日付を特定すること**。
本リポジトリの主張（2011年以降を県レベルパネルで扱えない）は、
制限が市町村×品目単位で課され解除も同単位で進むという構造に依存しており、
個別の指示日付には依存しない。

---

## 7. 先行研究（設計の参照元）

- Alsan, M. (2015). The Effect of the TseTse Fly on African Development.
  *American Economic Review*, 105(1), 382–410.
- Frank, E. G. (2024). The economic impacts of ecosystem disruptions:
  Costs from substituting biological pest control. *Science*, 385(6713).

いずれも生物学的ショックを準実験として用いた実証研究であり、本プロジェクトの
当初設計はこれらの様式に倣ったものである。
