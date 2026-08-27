# 法人企業統計・四半期別調査 再現可能分析パイプライン

財務省「法人企業統計調査・四半期別調査」の公表値から、前年差、業種別・資本金規模別の寄与、利益の幅、ソフトウェア投資の逆算値、利益・給与・人員・設備投資の動きを計算し、数値根拠付きの記事まで生成するパイプラインです。

数値の正本はe-Statの構造化表データです。財務省PDFは調査範囲・定義・注記・公表ランキングの照合用であり、PDFから記事数値を転記しません。

## 現在固定している公表ビンテージ

- 対象: 令和8年1〜3月期（`2026Q1`）
- 公開日: 2026-06-01
- 前年同期: 2025年1〜3月期
- 直前四半期: 2025年10〜12月期
- リリース定義: `config/release_2026Q1.json`

取得日時とハッシュは統計の対象期とは別です。「どの期の統計か」はリリース定義と公開日で、「いつ、どの応答を保存したか」はmanifestの`retrieved_at`と`sha256`で識別します。

## 調査対象と分析範囲

公表PDFの定義では、日本の資本金、出資金または基金が1,000万円以上の営利法人等の仮決算計数をまとめた標本調査です。標本法人の回答から母集団法人の値が推計されます。金融業、保険業は平成20年4〜6月期から調査対象に加わっています。

このパイプラインは範囲を混同しないよう、次の3系列を明示的に分離します。

| `coverage_scope` | 内容 | 主な用途 |
|---|---|---|
| `EXCL_FINANCE_INSURANCE` | 金融業、保険業を除く | 売上高、営業利益、経常利益、設備投資の主分析 |
| `INCL_FINANCE_INSURANCE` | 金融業、保険業を含む全産業 | 表2で公表される共通項目の別系列 |
| `FINANCE_INSURANCE_ONLY` | 金融業、保険業のみ | 「含む = 除く + 金融・保険」の照合 |

記事の主系列は「金融業、保険業を除く」です。これは調査自体から金融・保険が除外されているという意味ではありません。金融・保険込みの数値を使う場合は、記事と`claims.csv`で別の範囲として明記します。

## データソース

| 表・資料 | ID / URL | 範囲 | 役割 |
|---|---|---|---|
| e-Stat 表1 | SID `0003060191` | 金融・保険を除く、原数値 | 主要数値、業種別・資本金規模別の正本 |
| e-Stat 表2 | SID `0003061946` | 金融・保険を含む、原数値 | 金融込みで公表される項目 |
| e-Stat 表3 | SID `0003061948` | 金融・保険のみ、原数値 | 金融込み値との合計照合 |
| e-Stat 表4 | SID `0003066618` | 金融・保険を除く、季節調整値 | 季節調整済み前期比 |
| [財務省結果概要PDF](https://www.mof.go.jp/pri/reference/ssc/results/r8.1-3.pdf) | 令和8年1〜3月期 | 公表資料 | 定義、注記、公表順位の照合のみ |
| [財務省季調前期比Excel](https://www.mof.go.jp/pri/reference/ssc/results/percent.xlsx) | 公表時点のスナップショット | 公表増減率 | e-Stat表4からの再計算値の照合 |

e-Statの取得には公開DBビューアの構造化JSON応答（`source_method=ESTAT_DB_VIEW_PUBLIC_UI`）を使い、取得時のモデル、選択クエリ、応答をそれぞれ保存します。e-StatのアプリケーションIDは不要です。POST先、閲覧URL、対象期、クエリと応答のSHA-256も固定します。未知のディメンション・指標・表形状はFAILとし、既知の分類でも期待する業種集合と資本金区分、内訳合計を別途検証します。

財務省の`percent.xlsx`は同じURLで更新されるため、必ずリリース別に生バイトとSHA-256を固定します。

## rawデータとmanifest

`data/raw/<release_id>/`は取得したバイトをそのまま保存する領域です。取得後の整形、エンコード変換、Excelの再保存、PDFの抽出結果による上書きはしません。

`data_manifest.json`は各資料について、少なくとも次を記録します。

- 取得日時 `retrieved_at`
- 取得URL `url`
- e-Statの表番号 `table_number`とSID `estat_sid`
- 公開日 `publication_date`
- 金融・保険の範囲 `coverage_scope`
- 原数値か季節調整値か `seasonal_adjustment`
- 保存先、バイト数、content type、SHA-256
- 数値正本、公表率照合、PDF照合の役割 `role`
- 実取得方法 `source_method`、HTTPメソッド、閲覧URL、対象期コード

ビルド成果物のmanifestはversion 2で、保存先をプロジェクト相対パスに正規化します。初回取得時の旧manifestに含まれていなかった4クエリは、リリース設定へ固定した当初SHA-256と照合してから追加します。したがって、改変したクエリを同じビルドで正当化することはできません。

同じリリースIDのrawファイルが既にある場合、`fetch`はmanifestのハッシュと実ファイルを照合します。バイトが異なる既存ファイルは上書きせず停止します。改訂値や別取得時点を保存するときは、新しいリリースIDまたはビンテージ用ディレクトリを作ってください。

## 列の意味と比較の分離

`processed_quarterly.parquet`では、原数値、前年同期比、原数値の前期比、季節調整済み前期比を同じ列に上書きしません。

| 変数 | 意味 |
|---|---|
| `source_value` | e-Stat原表の当期原数値（原単位） |
| `raw_value_oku_yen` | 金額項目の当期原数値を億円に変換 |
| `raw_lag4_value`, `raw_lag4_value_oku_yen` | 前年同期の原数値 |
| `raw_yoy_delta`, `raw_yoy_delta_oku_yen` | 当期原数値 - 前年同期原数値 |
| `raw_yoy_pct` | 原数値の前年同期比 |
| `raw_yoy_rate_status` | 増加率の計算可否。利益の前年値が負なら算出不能 |
| `raw_lag1_value`, `raw_qoq_delta`, `raw_qoq_pct` | 原数値の直前四半期比較。見出しに使う季調前期比とは別物 |
| `sa_value_oku_yen`, `sa_lag1_value_oku_yen` | e-Stat表4の当期・前期の季節調整値 |
| `sa_qoq_delta_oku_yen`, `sa_qoq_pct` | 季節調整値の前期差・前期比 |
| `official_sa_qoq_pct` | 財務省Excelにある公表前期比。`sa_qoq_pct`と照合 |
| `official_yoy_pct` | 財務省PDFの公表前年比。全産業・全規模の見出し系列だけに設定 |
| `profit_transition_yoy`, `profit_transition_qoq` | 黒字→赤字、赤字→黒字、ゼロ境界などの状態 |
| `missing_status` | 実値、原表欠損、解析不能、導出元不足の状態 |
| `comparability_status` | 標本交替期や原数値前期比の注意状態 |

原数値の前期比は保持しますが、記事の前期比には原則として季節調整済み系列を使います。業種別・資本金規模別の寄与は原数値の前年差で計算し、独自の季節調整は行いません。

## 主な計算式

金額のe-Stat原単位は百万円です。従業員数などの非金額項目に金額変換は適用しません。

```text
億円                 = 百万円 / 100
兆円                 = 億円 / 10,000
前年差             = 当期原数値 - 前年同期原数値
前年同期比         = (当期原数値 / 前年同期原数値 - 1) * 100
季調前期比         = (当期季調値 / 前期季調値 - 1) * 100
寄与率               = 内訳の前年差 / 全体の前年差 * 100
売上高営業利益率     = 営業利益 / 売上高 * 100
売上高経常利益率     = 経常利益 / 売上高 * 100
利益差               = 経常利益 - 営業利益
利益前年差の幅     = 経常利益前年差 - 営業利益前年差
ソフトウェア投資   = 設備投資（込み） - 設備投資（除く）
従業員1人当たり給与 = (従業員給与 + 従業員賞与) * 100 / 従業員数
借入金合計           = 流動・固定の金融機関借入金 + その他借入金
```

営業利益・経常利益は財務省表の慣行に合わせ、前年値が負なら前年比を算出不能としてnullにし、`raw_yoy_rate_status`へ理由を残します。前年が黒字で当期が赤字の場合は率を計算しつつ、`profit_transition_yoy=PROFIT_TO_LOSS`を併記します。

従業員1人当たり給与は、当該四半期の給与・賞与総額を期末従業員数で除した概算であり、年率換算しません。分子が期間中のフロー、分母が期末時点の人数であるため、個人の賃金水準とは一致しません。

上位1・3・5業種の集中度は、増益となった主要業種の正の前年差合計を分母にします。全体の純増減を分母にしないのは、減益業種による相殺で集中度が歪むのを避けるためです。一方、個別業種や資本金規模の「全体増減への寄与率」は純増減が分母なので、100%を超える、または負になることがあります。

## 実行環境

- Python 3.11以上
- ネットワークは`fetch`のみで必要
- ビルドとテストは保存済みrawデータでオフライン実行可能

```bash
cd corporate_quarterly_pipeline
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.lock
python3 -m pip install -e . --no-deps
```

## 実行方法

取得、ビルド、テストを順番に実行します。

```bash
make all
```

個別に実行する場合は次のとおりです。

```bash
# e-Statと財務省からrawバイトを取得し、manifestを固定
make fetch

# 保存済みrawのみで加工・分析・記事生成・監査
make build

# 単位、合計、公表率、欠損、符号転換、記事ゲートを検証
make test
```

同じ操作をCLIで行うこともできます。

```bash
corporate-quarterly fetch --release 2026Q1
corporate-quarterly build --release 2026Q1 --offline

# editable installを使わない場合
PYTHONPATH=src python3 -m corporate_quarterly fetch --release 2026Q1
PYTHONPATH=src python3 -m corporate_quarterly build --release 2026Q1 --offline
```

`build --offline`はネットワーク取得を行いません。rawまたはmanifestがない、あるいはハッシュが合わない場合は失敗します。

## 出力

リリース別に`outputs/<release_id>/`へ書き出します。

| 出力 | 内容 |
|---|---|
| `data_manifest.json` | ビルドに使ったrawの来歴・取得日時・URL・表番号・公開日・ハッシュ |
| `processed_quarterly.parquet` | 処理済み長期形データ。範囲、原数値、前年比、原数値前期比、季調前期比を分離 |
| `industry_contributions.csv` | 重複しない公表主要業種の前年差、寄与率、順位 |
| `capital_size_contributions.csv` | 重複しない3資本金規模の前年差、寄与率、順位 |
| `claims.csv` | 記事中の数値主張の一意ID、FACT/CALC/HYPOTHESIS、式、単位、フィルタ、出典、検証状態 |
| `audit_report.md` | データ検証、記事数値照合、データ品質ログ、最終STATUS |
| `article.md` | 厳密に200字の事実要約、独自発見、図表付き本文、限界、再現方法、追加検証仮説 |
| `charts/*.png` | 業種寄与、資本金規模寄与、利益差、設備投資差、配分比較などの図 |
| `industry_concentration.csv` | 増益寄与上位1・3・5業種の集中度と構成業種 |
| `data_quality_log.json` | 欠損、解析不能、表章・分類変更、利益の符号転換の機械可読ログ |

数値の監査可能性を保つため、`article.md`本文・表の各統計値には`claims.csv`のclaim IDが直後のHTMLコメントとして埋め込まれます。通常のMarkdown表示では見えませんが、公開ゲートが表示値・単位・claim ID・FACT/CALC/HYPOTHESISラベルを1対1で照合します。図中の正確な描画値も`claim_usage=CHART_INPUT`としてclaimsへ収録し、描画入力29件と機械照合します。公開日、リリースID、表番号、要約字数、軸目盛などの来歴・レイアウト用数値は統計claimの対象外として明示的に許可します。

## 検証とFAILの意味

ビルドは次を自動検証します。

- rawファイルとmanifestのSHA-256一致
- 必須指標の存在と非欠損
- 業種内訳・資本金規模内訳と全体の、当期値・前年値・前年差の一致
- 金融・保険込み値と、金融・保険除く値 + 金融・保険のみの一致
- 百万円→億円→兆円の単位変換
- e-Stat季調値から再計算した前期比と財務省Excel公表値の誤差（許容0.05ポイント以下）
- e-Stat原数値から再計算した前年比と財務省PDF公表値の丸め誤差（許容0.05ポイント以下）
- 黒字→赤字、赤字→黒字、0境界の状態検出
- 欠損値、解析不能値、表章変更、業種分類変更のログ保持
- `claims.csv`のFACT/CALCと記事内数値の直結・完全一致、および全図表入力との一致
- claimにない単位付き数値、重複claim ID、未知claim IDの不存在
- 「経常利益 = 本業のもうけ」という誤表現の不存在
- AI需要、インバウンド、人手不足、価格転嫁を含む原因候補が`HYPOTHESIS`と明記されていること
- 「過去最高」を使うなら名目値か実質値かを併記すること

欠損や分母0の計算不能値は0に補完せず、nullと状態コードで保持します。寄与率や増減率が計算不能なのに0と表示されることはありません。

1つでもFAILがあれば、`audit_report.md`の最終判定は`STATUS: FAIL`となり、`article.md`も完成扱いになりません。CLIも非0で終了します。ビルド開始時に旧PASS記事をFAILスタブで無効化するため、途中例外で過去のPASSが残ることもありません。WARNは値を0に変換せず品質ログに残ります。記事を利用する前に、必ず`audit_report.md`のSTATUSとWARNを確認してください。

## 記事の表現ルール

- `FACT`: e-Stat原表または公表資料にある観測事実
- `CALC`: 公式を明記して原表から計算した値
- `HYPOTHESIS`: 法人企業統計だけでは確認できない原因仮説

法人企業統計が示すのは会計数値の合計・推計値であり、原因ではありません。経常利益には営業外損益が含まれるため、「本業のもうけ」とは表現しません。値は名目値であり、物価調整済みの実質値ではありません。

## 利用上の限界

- 標本調査による推計値であり、標本誤差と回答修正の影響があります。
- 四半期の仮決算値で、後日改訂される可能性があります。
- 金額は名目値です。実質化や価格要因の分離は行っていません。
- 合計値はミクロな企業間差を隠します。業種内で利益が広く分布したかは判定できません。
- 寄与率は全体の純増減が小さいと大きく振れます。増減額と併記してください。
- ソフトウェア投資は2系列の差分であり、独立表の観測値ではありません。
- 従業員1人当たり給与は概算であり、個人の賃金水準や年収ではありません。
- 利益・給与・人員・設備投資の4項目比較は同時変化の比較で、会計上の加算分解ではありません。
- 統計表だけから需要、価格転嫁、人手不足、為替、金利などの原因を特定できません。
- e-Stat DBビューアと財務省Excelのレイアウトは外部仕様です。変更時はパーサの更新が必要です。

## 新しい公表期への更新

1. `config/release_2026Q1.json`を`config/release_<release_id>.json`へコピーし、リリースID、対象期、前年同期、直前期、公開日、PDF URLを更新します。
2. e-Statの表SID、表題、金融・保険範囲、原数値/季調値を公式画面で確認します。表構造が同じでも無条件にSIDを使い回さないでください。
3. PDFの見出し前年比、金額、順位、ページ、比較対象期数を二人または二回の目視で確認し、`pdf_reference_checks`を更新します。PDFは数値正本にはしません。
4. 新しいリリースIDで`fetch`します。既存rawは上書きしません。新規取得のversion 2 manifestにはqueryも含まれるため、通常は`legacy_frozen_query_sha256`を使いません。
5. `data/raw/<release_id>/data_manifest.json`のURL、表番号、公開日、取得日時、ハッシュを確認します。
6. `build --offline`を実行し、欠損、未知メトリク、表章変更、業種分類変更のログを確認します。
7. `make test`を実行し、`audit_report.md`と`article.md`がともに`STATUS: PASS`であることを確認します。
8. `article.md`のHYPOTHESISは当期の外部一次資料で検証しない限り、FACTへ変更しません。

表章項目の名称、単位、業種階層、資本金区分が変わった場合は、過去の対応表を無言で流用せず、設定とテストを明示的に更新してください。

## 第2段階：見出し選定・クロス分解・長期頑健性

第2段階は既存の`outputs/2026Q1/`を入力の正本にせず、保存済みrawから再計算してPhase 0を通したうえで、追加成果物を`outputs/2026Q1_v2/`へ生成します。第1段階の成果物は上書きしません。Phase 0の32ターゲットのうち1件でも許容誤差を外れれば、`PHASE0_FAIL.md`に対象セルと差分を記録して後続処理を停止します。

実行用の公表期正本は`config/release_2026Q1.json`（`CONFIG_KIND=EXECUTABLE_RELEASE_CONFIGURATION`）、第2段階の固定基準は`config/stage2_2026Q1.json`です。プロジェクト外にあった簡略設定は`../corporate_quarterly/config/release_input_minimal.json`へ改名し、`CONFIG_KIND=INPUT_STUB_NOT_EXECUTABLE`と正本へのポインタを明記しています。簡略版を実行設定として読み込んではいけません。

```bash
# e-Statのcurrent-vintage長期系列を凍結。Phase 3は条件成立時のみ取得
make fetch-v2

# 保存済みrawだけでPhase 0〜公開判定を再生成
make build-v2

# 取得、ビルド、全テスト
make stage2
```

第2段階では、major 11業種と相互排他的なleaf 45業種を別taxonomyとして保持し、親と子を同じランキングや図に混在させません。業種×3資本金区分、二要因・三要因Shapley分解、`net_non_operating_gap`、逆算ソフトウェア投資を計算し、親・列・行・全産業への加算一致を監査します。

長期系列はe-Stat表1、SID `0003060191`の1954Q2〜2026Q1を現在取得時点の分類名で機械的に取得した`current-vintage historical series`です。系列ごとの実在開始期を保持し、ソフトウェア投資は定義差を検知した2001Q3からのみ比較可能とします。それ以前は0ではなくnullと`PRE_DEFINITION_NOT_COMPARABLE`を残します。過去公表ビンテージは保存されていないため、改訂への頑健性を確認した系列ではありません。

パターン判定は結果を見る前に次の順序で固定しています。

- 過去4四半期中3期以上が同方向、かつ4四半期移動集計も同方向: `PERSISTENT_PATTERN`
- 過去4四半期中ちょうど2期が同方向、または移動集計だけが同方向: `RECENT_BUT_NOT_ESTABLISHED`
- 現四半期だけが同方向で歴史的90パーセンタイル超: `ONE_QUARTER_OUTLIER`
- その他: `UNSTABLE_OR_NO_PATTERN`

主な成果物は次のとおりです。

| 出力 | 内容 |
|---|---|
| `phase0_reproduction.md` | 32ターゲットの期待値、再計算値、差、許容誤差 |
| `industry_leaf_contributions.csv` | 相互排他的leaf業種の前年差・寄与 |
| `industry_x_capital_contributions.csv` | taxonomyを分離した業種×資本金規模セル |
| `capital_margin_bridge.csv` | 資本金規模別の売上規模・業種構成・業種内利益率Shapley分解 |
| `ordinary_operating_gap.csv` | 経常利益−営業利益の純差額と前年差。単一原因へ読み替えない |
| `software_capex_decomposition.csv` | ソフト込み−除くの逆算値。直接公表系列ではない |
| `historical_quarterly.parquet` | current-vintage長期パネル、比較可能性・欠損・分類状態 |
| `historical_robustness.csv` / `pattern_decisions.csv` | percentile、IQR、MAD、符号数、連続数、固定判定 |
| `external_evidence_ledger.csv` | Phase 3の発動・取得・評価・公開可否の状態 |
| `claims_v2.csv` / `audit_v2.md` | 数値主張台帳とFAIL閉鎖型の最終監査 |
| `decision.md` / `candidate_headlines.md` | A〜Eの公開判定と見出しの採否 |
| `charts/*.png` | 指定された5図 |

`article_public.md`は少なくとも1候補が`PERSISTENT_PATTERN`となり、必要な外部一次資料の取得・評価とclaim照合まで通った場合だけ生成します。

## 第2段階のPhase 3発動ゲート

第2段階では、候補A〜Eの長期安定性を先に固定基準で判定し、`PERSISTENT_PATTERN`だけを外部一次資料の調査対象にします。2026Q1の確定結果は次のとおりです。

| 候補 | 現四半期の指標値 | 長期判定 |
|---|---:|---|
| A 資本金10億円以上の製造業への経常増益集中 | 72.0597% | `UNSTABLE_OR_NO_PATTERN` |
| B 1億円未満と10億円以上の営業利益率の動き | 0.227518（旧v2複合スコア、凍結） | `RECENT_BUT_NOT_ESTABLISHED` |
| C 設備投資全体・ソフトウェア・除く系列の差 | 0.952770（旧v2複合スコア、凍結） | `ONE_QUARTER_OUTLIER` |
| D 経常増益と営業増益の差 | 37.5368% | `RECENT_BUT_NOT_ESTABLISHED` |
| E 情報通信機械の利益寄与 | 38.1297% | `UNSTABLE_OR_NO_PATTERN` |

`PERSISTENT_PATTERN`は0件です。そのためPhase 3は`NOT_ACTIVATED`であり、HTTP取得、`data/raw/external_2026Q1/`、その`data_manifest.json`、`article_public.md`は意図的に生成しません。これらの不在は欠損やビルド失敗ではなく、ゲートが正常に閉じた結果です。

`config/external_evidence_2026Q1.json`は官公庁・日本銀行等の出典候補を事前登録した調査計画であり、取得済みの証拠台帳ではありません。各行は`assessment=PENDING_RESEARCH`、`direct_observation=NOT_ACQUIRED`のまま保持します。実績の`external_evidence_ledger.csv`には`NOT_ACTIVATED_NON_PERSISTENT`、`NOT_APPLICABLE`を記録し、外部観測値、rawパス、SHA-256を書き込みません。

Python APIも同じゲートを必須入力とします。

```python
from pathlib import Path
from corporate_quarterly.stage2_publication import fetch_external_sources

receipt = fetch_external_sources(
    phase0_passed=True,
    pattern_decisions=pattern_decisions,  # A〜Eのcandidate_idとpattern_decision
    project_root=Path("."),
)
assert receipt["acquisition_status"] == "NOT_ACTIVATED_NO_PERSISTENT_PATTERN"
assert receipt["sources"] == []
```

CLIでは次の順に実行できます。`fetch-stage2`はPhase 0結果とA〜Eの判定を取得APIへ必ず渡し、現ビンテージでは`external_activated=False`を返します。

```bash
PYTHONPATH=src python3 -m corporate_quarterly fetch-stage2 --release 2026Q1
PYTHONPATH=src python3 -m corporate_quarterly build-stage2 --release 2026Q1 --offline
```

Phase 3が将来発動するのは、Phase 0がPASSで、かつA〜Eのいずれかが`PERSISTENT_PATTERN`のときだけです。その場合も対象候補に事前紐付けた出典のみをrawとmanifestに凍結し、読解と方向評価が終わるまで`RESEARCH_REQUIRED`のままとします。

公開記事は中心主張1件、120〜180字の要約、図は最大3枚とします。`claims_v2.csv`の公開行は`claim_id`、`display_value`、`candidate_id`、`publication_status=PUBLIC`、`verification_status=PASS`を持ち、記事のHTMLコメントと表示値が完全一致する必要があります。未登録数値、別候補の外部証拠、原因断定、読者向けのFACT/CALC/HYPOTHESISバッジ、4枚以上の図のいずれかがあれば`audit_v2.md`はFAILとなり、記事は完成扱いになりません。

## 凍結v2に対する補正ルール感度分析

`outputs/2026Q1/`と`outputs/2026Q1_v2/`は凍結成果物です。`rule_sensitivity.py`は両ディレクトリを上書きせず、旧ルールと補正ルールの差をメモリ上のDataFrameとして返します。

候補BとCの旧複合スコアは、条件からの距離を経済的な大きさのように見せるため、補正系列では次のBoolean条件へ置き換えます。入力が欠損する期はFalseや0にせずnullと`MISSING_INPUT`を保持します。

- B: `small_sales_yoy_pct > 0 AND small_operating_margin_yoy_delta_pp < 0 AND large_operating_margin_yoy_delta_pp > 0`
- C: `abs(capex_including_yoy_pct) <= 1.0 AND software_capex_yoy_delta_oku_yen > 0 AND capex_excluding_yoy_delta_oku_yen < 0`

B/Cの0/1条件成立フラグに数値パーセンタイルは適用しません。`numeric_history_eligible=False`、`historical_percentile_inclusive_pct=null`、`percentile_method=NOT_APPLICABLE_BOOLEAN_CONDITION`とし、外れ値分岐に入れず、過去4四半期の条件成立数と4四半期移動合計条件だけで判定します。A/D/Eの数値系列は、`100 × count(reference <= current) / non-missing N`という同値を含む経験CDFを使い、`historical_percentile_inclusive_pct`、分子、分母、tie policy、当期を参照集合に含むかをmetadataに残します。

旧分類の`count4 == 2 OR rolling`は、`count4=3, rolling=False`を`count4=2`より弱くする非単調点がありました。補正分類は`count4 >= 2 OR rolling`とし、`count4=0..4 × rolling=False/True`の10ケースを全数テストします。2026Q1の感度結果では、Cが`ONE_QUARTER_OUTLIER`から`UNSTABLE_OR_NO_PATTERN`、Eが`UNSTABLE_OR_NO_PATTERN`から`RECENT_BUT_NOT_ESTABLISHED`に変わります。どちらも`PERSISTENT_PATTERN`ではなく、Phase 3非発動は変わりません。

```python
import pandas as pd
from corporate_quarterly.rule_sensitivity import build_rule_sensitivity

series = pd.read_parquet("outputs/2026Q1_v2/historical_candidate_series.parquet")
sensitivity = build_rule_sensitivity(series)
```

## claim帰属と統計表現の追加監査

`publication_contracts.py`の`CLAIM_CANDIDATE_REGISTRY_V2`は、凍結済み`V-001`〜`V-077`の全claim IDをA〜Eのいずれか1件に明示対応させます。旧ファイルの空欄を上書きせず、`apply_claim_candidate_registry()`が補正copyと差分フラグを返します。

表データの資本金区分名は`1千万円以上 - 1億円未満`、`1億円以上 - 10億円未満`、`10億円以上`、`全規模`と原表名称の完全一致を求めます。記事本文は別契約で、初出を例えば`資本金1千万円以上1億円未満層`と厳密に書けば、以後の`同層`や文脈の明らかな`1億円未満層`は許容します。substringだけで機械的に禁止しません。

`従業員給与+従業員賞与`の比率ラベルは厳密に`従業員給与・賞与比率`とします。合計金額と1人当たり概算は別ラベルを使えますが、いずれも`人件費`全体と同一視しません。`人件費率`は調査項目コード`093`を実際に取得した場合のみ使用できます。

## 完全性inventoryとclean ZIP

`release_integrity.py`は、v1/v2の全ファイルを再帰的に列挙し、各パス、バイト数、SHA-256とinventory全体のSHA-256を返します。必須構成検査は個別成果物に加え、リポジトリとZIPの`config/`、`data/raw/`、`outputs/2026Q1/`、`outputs/2026Q1_v2/`、`src/`、`tests/`、`README.md`、`pyproject.toml`、`requirements.lock`を確認します。既存ZIPの必須パス欠損とjunk混入は、`required_structure_status`と`hygiene_status`に分けて報告します。

```bash
make doctor-release
make verify-release
make inventory-release  # dist/release_sha256_inventory.json
make package-release    # dist/corporate_quarterly_2026Q1_clean.zip
```

clean ZIPは検査済みv1/v2 inventoryを`release_sha256_inventory.json`として自己同梱し、パスを固定順序で格納します。`__MACOSX`、`__pycache__`、`.DS_Store`、`.pytest_cache`、旧`アーカイブ.zip`、出力先ZIP自身は含めません。出力先が既にある場合はデフォルトで上書きを拒否し、旧`アーカイブ.zip`と同名の出力先は`overwrite=True`でも常に拒否します。

実行環境のライブラリ不足は`DEPENDENCY_FAILURE`としてexit code 3、欠損ファイル、SHA不一致、コード契約違反、データ契約違反は`CODE_OR_DATA_FAILURE`としてexit code 4を返します。この2種を同じ「ビルド失敗」にまとめません。

## 第3段階：継続標本と営業外損益の完全分解

第3段階は財務省「継続標本のみを用いた計数」と通常のe-Stat系列を2016Q1から2026Q1まで比較し、見出しが標本のつなぎ方に依存するかを検証します。継続標本PDFには利益率水準がないため、売上高と営業利益の前年同期比がともに計算可能な場合だけ、次式で利益率の上下方向をproxy判定します。ポイント差は作りません。

```text
relative_margin_change
  = (1 + operating_profit_growth) / (1 + sales_growth) - 1
```

継続標本は通常系列よりサンプルサイズが小さく、財務省は営業利益と経常利益の標準誤差率を算出していません。この制約はCSVの明示列、manifest、監査、判定、公開記事のすべてに残します。

同時にe-Stat表1のコード082〜085を取得し、次の恒等式を全規模、資本金階層、major/leaf業種、業種×資本金階層で検証します。

```text
ordinary_profit
  = operating_profit
  + interest_and_dividend_income
  + other_non_operating_income
  - interest_expense
  - other_non_operating_expense
```

支払利息等は原額の増加と利益への負の寄与を別列に保持します。「支払利息の減少寄与」とは表現しません。「その他の営業外収益」を為替差益、配当、持分法利益などの特定要因に帰属させることもしません。

判定規則の感度分析では、旧B/C複合量をlegacy metadataとして保存し、修正側はnullable Booleanだけを使います。B/Cを数値のpercentileや候補間順位に使いません。その他の歴史位置は`historical_percentile_inclusive_pct`とし、tiesを含むinclusive empirical CDFです。

```bash
make fetch-v3    # 公式ソースを新規raw vintageに凍結
make build-v3    # 保存済みrawだけでv3を再生成
make stage3      # 取得、生成、全pytest
make package-v3 # clean ZIPを再生成
```

v3出力は`outputs/2026Q1_v3/`に限定し、`outputs/2026Q1/`と`outputs/2026Q1_v2/`の全ファイルSHA-256を生成前後で比較します。公開判定は`PUBLISH_SAMPLE_CONSTRUCTION_SENSITIVITY`、`PUBLISH_FULL_NONOPERATING_BRIDGE_SNAPSHOT`、`ARCHIVE_NO_ROBUST_STORY`のどれか一つです。

公開記事は一主張に限定し、主要図は最大3点。通常系列と継続標本で資本金1千万円以上1億円未満層の利益率方向が反転する場合、「同層だけ利益率低下」という記事は生成しません。`claims_v3.csv`との数値照合、単位、合計、断定表現のいずれかが不合格なら`audit_v3.md`をFAILとし、`article_public.md`を完成品として残しません。

## 公開用最終版 v3.1：標本構成感応度の限定分析

v3.1はv3と同じ凍結済み公式rawを再利用し、営業外損益分解を含めず、2016Q1から2026Q1の41四半期について通常系列と継続標本系列の結論の食い違いを検証します。中心数値は、資本金1千万円以上1億円未満層の利益率方向の不一致16/41です。複合見出しの不一致11/41は補足とし、両者とも2026Q1の結果を確認した後に過去へ適用した探索的バックテストとして扱います。

見出し2×2表、資本金階層×指標の不一致率、判定余裕と系列間乖離、公表増減率の丸め感応度、利益率の相対変化率（％）に対するdeadband感応度、及び継続標本の営業利益増加率の絶対値が100％を超える期の機械的フラグを対象にします。通常系列と継続標本系列は、企業の参入・退出、回答継続条件、推計用乗率、未回答補完、母集団構成の違いを含み得るため、どちらも真値や正解とは扱いません。階層間の勾配は5億円の全数・標本境界とローテーションを含む調査設計と整合的との記述に限定し、原因とは断定しません。継続標本は標本数が小さく、営業利益・経常利益の標準誤差率が算出されていない制約も各出力に残します。

実行時はv3の全ファイルのSHA-256を前後で照合し、`outputs/2026Q1_v3/`を上書きせず、新規の`outputs/2026Q1_v3_1/`だけに保存します。v3.1は追加取得を行わないため、オフラインビルドだけを提供します。

```bash
make build-v3-1
# または
PYTHONPATH=src python3 -m corporate_quarterly build-stage4 --release 2026Q1 --offline

# v3.1生成後に全テストまで実行
make stage4
```

出力は次のファイルと3図に限定します。`audit_v3_1.md`がPASSにならない場合、`article_note.md`は完成扱いになりません。

| 出力 | 内容 |
|---|---|
| `article_note.md` | 2,500〜3,500字、中心主張1件の公開用記事 |
| `headline_2x2.csv` | 見出し成立の2×2表（通常のみ9、継続のみ2、両方1、どちらも29） |
| `mismatch_heatmap.csv` | 資本金階層×指標の不一致率と調査設計の注記 |
| `rounding_sensitivity.csv` | ±0.05ptの丸め感応度と機械的フラグ |
| `deadband_sensitivity.csv` | 利益率の相対変化率に対する階層別deadband感応度 |
| `claims_v3_1.csv` | 記事数値のclaim照合台帳 |
| `audit_v3_1.md` | 数値、表現、図数、凍結v3のSHA-256を検査するFAIL閉鎖型監査 |
| `charts/mismatch_heatmap.png` | 利益率方向の階層別不一致率 |
| `charts/headline_2x2.png` | 見出し成立の2×2表 |
| `charts/deadband_sensitivity.png` | 資本金階層別のdeadband感応度 |

## 公開用最終版 v3.2：単位と公開原稿の限定修正

v3.2は新しいデータ取得や営業外損益分解の追加ではなく、凍結済みv3とv3.1に基づく公開版の限定修正です。主な変更は、判定余裕の中央値を「増加率同士の差」に対応する`percentage_points`（ポイント）へ訂正すること、2026Q1の資本金1,000万円以上1億円未満層の例示を正本CSVからclaim化すること、見出しを営業利益率方向の不一致という中心主張に絞ることです。数値の訂正有無と理由は`claim_corrections_v3_2.csv`と`expected_value_changes_v3_2.csv`に残します。

`article_note.md`はclaim用HTMLコメントと相対図版リンクを含む監査用の正本原稿です。`article_note_render.md`はその原稿から監査コメントを除き、図版リンクを投稿時の図マーカーに置き換えたnote入稿用です。render側で文章や数値を再生成しません。

Stage 5はオフライン専用で、一時ディレクトリ内で生成・全pytest・監査を通過した場合だけ`outputs/2026Q1_v3_2/`を公開します。完成済みv3.2の上書きは拒否し、CLIは再実行の失敗を既存ディレクトリへFAIL markerとして追記しません。生成前後で`outputs/2026Q1/`、`outputs/2026Q1_v2/`、`outputs/2026Q1_v3/`、`outputs/2026Q1_v3_1/`の全ファイルSHA-256が不変であることを検査します。

```bash
make build-v3-2
# または
PYTHONPATH=src python3 -m corporate_quarterly build-stage5 --release 2026Q1 --offline

# build-stage5は全pytest、監査、clean ZIP検証まで実行
make stage5
```

v3.2の出力は次の通りです。`audit_v3_2.md`がPASSした場合だけ、指定された再現入力と公開成果物を収録する`corporate_quarterly_2026Q1_v3_2_clean.zip`を同じディレクトリに生成します。ZIPは`__MACOSX`、`__pycache__`、`.pytest_cache`、`.DS_Store`、`.pyc`、`.pyo`を含みません。

| 出力 | 内容 |
|---|---|
| `article_note.md` / `article_note_render.md` | 監査用正本原稿 / note入稿用render |
| `claims_v3_2.csv` / `claim_corrections_v3_2.csv` | claim台帳 / v3.1からの訂正履歴 |
| `mismatch_heatmap.csv` / `headline_2x2.csv` | 不一致率 / 見出し2×2表 |
| `deadband_sensitivity.csv` / `rounding_sensitivity.csv` | deadband / 丸め感応度 |
| `unit_registry.json` / `chart_manifest_v3_2.json` | 単位契約 / 図の数値系譜とSHA-256 |
| `expected_value_changes_v3_2.csv` | タイトル期待値の意図した変更 |
| `audit_v3_2.md` / `v3_1_immutability_manifest.json` | 最終監査 / 凍結v3.1のSHA-256照合 |
| `charts/*.png` | 正本CSVから再生成した主要3図 |
| `corporate_quarterly_2026Q1_v3_2_clean.zip` | 検証済みの再現・公開用clean ZIP |

## ディレクトリ構成

```text
corporate_quarterly_pipeline/
├── config/                     # 公表期ごとの取得・期間定義
├── data/raw/<release_id>/     # 不変の取得バイトとraw manifest
├── outputs/<release_id>/      # 加工データ、記事、監査、図
├── src/corporate_quarterly/   # 取得・加工・分析・生成・監査実装
├── tests/                      # 単体・契約・成果物統合テスト
├── Makefile
├── pyproject.toml
└── requirements.lock
```

## テストの独立実行

```bash
PYTHONPATH=src python3 -m pytest tests -q
```

単体テストはネットワークを使いません。`outputs/2026Q1/`がある場合は、必須成果物、Parquetの列契約、claimsのPASS、記事と監査の公開ゲートも追加で検証します。
