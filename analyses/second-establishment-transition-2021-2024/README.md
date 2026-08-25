# 「人口何人の町に2軒目はあるのか、その後」公開データ・図表コード

note続編「『2軒以上ある町』は、3年でどう変わったか」で使った集計済みCSVと、記事用PNGを生成するPythonコードです。

このリポジトリで再現できるのは、**公開用に整理した集計済みCSVの整合性確認と、そのCSVから記事用図表8枚を生成する工程**です。e-Statからの取得、欠測セルのtable-implied zero判定、産業分類の接続、自治体集約、遷移行列の作成までを再実行する完全再現パッケージではありません。

前稿： [人口何人の町に「2軒目」はあるのか](https://note.com/masayuki_arai/n/nae37e02e6e9d)

## 分析の範囲

### 2021年→2024年の記述分析（`data/a3/`）

- 2021年「経済センサス‐活動調査」と2024年「経済センサス‐基礎調査」を使用
- 両年とも法人事業所に限定
- 政令指定都市は市全体、東京都は23区を各1地域として扱う
- 自治体境界変更の影響を受けた35地域を除く1,706自治体相当の分析単位が主分析
- 15業種のうち、産業分類上の点比較9業種、小売の端点シナリオ4業種、参考1業種、除外1業種
- 2021年法人カバー率80%以上を本文の主結果とする区切りは、統計的に推定した閾値ではなく公開上の編集基準

「閾値下向き遷移」は2021年に法人事業所がちょうど2つ、2024年に1つ以下となった分析単位です。「閾値上向き遷移」は2021年にちょうど1つ、2024年に2つ以上となった分析単位です。

個別事業所IDを接続していないため、これらは閉店率、退出率、開業率、参入率ではありません。閉店、開業、移転、法人化、産業格付け変更を分離できず、観察できるのは自治体別の法人事業所数という集計状態の変化だけです。

### 前稿のモデル感度（`data/phase1/`）

- 2021年の全事業所を使った横断面分析
- 双葉町を除く1,740自治体
- 独立二値ロジット、順序ロジット、ポアソン、負の二項の4仕様

こちらは法人限定の2021年→2024年分析とは、母集団も推定対象も異なります。二つのフォルダの値を同一サンプルの結果として接続しないでください。

## ファイル構成

```text
.
├── data/
│   ├── a3/
│   │   ├── analysis_scope.csv
│   │   ├── boundary_sensitivity.csv
│   │   ├── exact_industries.csv
│   │   └── retail_endpoint_scenarios.csv
│   └── phase1/
│       ├── binary_logit_monotonicity_diagnostics.csv
│       └── model_sensitivity.csv
├── fonts/
│   ├── NotoSansJP-Regular.ttf
│   └── OFL.txt
├── DATA_DICTIONARY.md
├── NOTICE.md
├── SHA256SUMS
├── make_figures.py
├── requirements.txt
└── verify_data.py
```

- `exact_industries.csv`：産業分類上の点比較が可能な9業種の状態変化
- `retail_endpoint_scenarios.csv`：新5661「均一価格店」の帰属を一意化できない小売4業種の二端点
- `analysis_scope.csv`：15業種の比較可否と記事上の位置づけ
- `boundary_sensitivity.csv`：自治体境界変更監査と35地域除外の感度
- `model_sensitivity.csv`：前稿の4モデルによる人口境界・正規化境界比
- `binary_logit_monotonicity_diagnostics.csv`：独立二値ロジットの単調性診断

列の定義は [DATA_DICTIONARY.md](DATA_DICTIONARY.md)、出典とフォントの表示は [NOTICE.md](NOTICE.md) を参照してください。

## 実行方法

Python 3.11以上を想定し、Python 3.12.13で動作確認しています。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python verify_data.py
python make_figures.py
python verify_data.py --check-figures
```

`verify_data.py`はCSVの列構成、件数、率、主要な恒等式を確認します。`--check-figures`は、生成済みPNGの存在、寸法、非空を追加確認します。配布ファイル自体のハッシュは次で照合できます。

```bash
sha256sum -c SHA256SUMS
```

Windows PowerShellでは仮想環境の有効化を次のように読み替えてください。

```powershell
.venv\Scripts\Activate.ps1
```

PNG 8枚は既定で`output/`に生成されます。別の場所へ出す場合は、生成と検証に同じパスを指定します。

```bash
python make_figures.py --output-dir figures
python verify_data.py --check-figures --output-dir figures
```

## 解釈上の注意

1. **点比較は調査全体の同一性を意味しません。** 産業分類と経営組織の対象を揃えたうえで、指定した業種集計を点として比較できるという限定的な意味です。
2. **小売4業種の二端点は95%信頼区間ではありません。** 各業種だけを見た周辺的な極端配分です。新5661は一つしかないため、複数業種の「include all 566」シナリオは同時成立せず、合算・交差・業種間ランキングに使えません。
3. **「市場」という経済学的な市場画定はしていません。** CSVでは自治体相当の単位を`analysis_unit`／`unit`と表記しています。自治体外への移動、近隣地域へのアクセス、店舗規模、価格、品質は扱っていません。
4. **病院は民営の法人病院です。** 公立病院を含む地域医療アクセス全体の分析ではありません。
5. **78Aと79Aは分析で使用したe-Stat上の集約コードです。** 通常の4桁日本標準産業分類コードと同一視しないでください。
6. **統計的推論ではなく記述分析です。** 2021年→2024年の状態変化について、新しい回帰、p値、信頼区間、因果推論は行っていません。

## 出典・ライセンス

元統計、産業分類資料、境界変更情報、フォントの出典は [NOTICE.md](NOTICE.md) に記載しています。CSVは公表統計から作成した著者集計値であり、政府による公式集計ではありません。

この配布物には、著者のコードと派生CSVに対する利用許諾ライセンスを設定していません。再利用を許諾して公開する場合は、公開者が方針を決めて`LICENSE`を追加してください。
