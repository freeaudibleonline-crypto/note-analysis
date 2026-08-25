# データ辞書

CSVはUTF-8、カンマ区切り、1行目を列名として保存しています。割合の単位は、列名が`_pct`なら百分率（%）、`_pt`ならパーセントポイントです。A-3では遷移率・不確定割合・境界感度を小数第2位、法人カバー率と反転率を小数第1位、平均変化を小数第3位に丸めています。そのため、整数列からの再計算値とは丸めの範囲で差が生じます。

## `data/a3/exact_industries.csv`

2021年・2024年の産業分類を点で接続できた9業種について、法人事業所数の集計状態変化を収録します。遷移に関する列は、境界変更35地域を除いた1,706分析単位で算出しています。

| 列 | 定義 |
|---|---|
| `industry_code` | 分析用業種コード。`78A`、`79A`はe-Stat上の集約コード |
| `industry_name` | 業種名 |
| `tier` | 2021年法人カバー率による記事上の区分。1＝80%以上、2＝50%以上80%未満、3＝50%未満 |
| `publication_role` | 記事上の位置づけ。`main`、`secondary`、`corporate_segment_appendix` |
| `corporate_coverage_pct_2021_all1741` | `100 × 全1,741分析単位の法人事業所数合計 / 全1,741分析単位の全事業所数合計`。自治体別比率の単純平均ではない |
| `n_ge2_flip_pct_2021_all1741` | `100 × #(全事業所では2以上、法人限定では1以下) / #(全事業所では2以上)`。地理的な算出対象は全1,741分析単位だが、1,741自体は分母ではない |
| `n_units_2021_eq0` | 2021年の法人事業所数が0の分析単位数 |
| `n_units_2021_eq2` | 2021年の法人事業所数がちょうど2の分析単位数 |
| `n_down_2_to_le1` | 2021年に2、2024年に1以下となった分析単位数 |
| `down_2_to_le1_pct` | `100 × n_down_2_to_le1 / n_units_2021_eq2` |
| `n_units_2021_eq1` | 2021年の法人事業所数がちょうど1の分析単位数 |
| `n_up_1_to_ge2` | 2021年に1、2024年に2以上となった分析単位数 |
| `up_1_to_ge2_pct` | `100 × n_up_1_to_ge2 / n_units_2021_eq1` |
| `n_units_ge2_2021` | 2021年に法人事業所数が2以上の分析単位数 |
| `n_units_ge2_2024` | 2024年に法人事業所数が2以上の分析単位数 |
| `n_down_ge2_to_le1` | 2021年に2以上、2024年に1以下となった分析単位数。初期値が3以上の場合も含む |
| `n_up_le1_to_ge2` | 2021年に1以下、2024年に2以上となった分析単位数。初期値が0の場合も含む |
| `net_change_units_ge2` | `n_up_le1_to_ge2 − n_down_ge2_to_le1`。`n_units_ge2_2024 − n_units_ge2_2021`と一致 |
| `mean_establishment_count_change` | 1分析単位当たり法人事業所数の平均変化（2024年−2021年） |
| `n_units_delta_lt0` | 法人事業所数が減った分析単位数 |
| `n_units_delta_eq0` | 法人事業所数が変わらなかった分析単位数 |
| `n_units_delta_gt0` | 法人事業所数が増えた分析単位数 |
| `transition_analysis_units` | 遷移分析の分析単位数。全行1,706 |

## `data/a3/retail_endpoint_scenarios.csv`

2024年に新設された5661「均一価格店」の旧分類上の流出元を一意化できない小売4業種について、二つの端点シナリオを示します。

`exclude_566`は2024年に当該業種コードだけを使い、`include_all_566`は566を全て当該業種へ加えます。後者は業種ごとの周辺的な極端配分であり、複数業種について同時成立しません。

| 列 | 定義 |
|---|---|
| `industry_code`, `industry_name` | 業種コード・業種名 |
| `scenario_2024_exclude_566` | 566を加えない2024年側の集計式 |
| `scenario_2024_include_all_566` | 566を全て加える2024年側の集計式 |
| `uncertain_analysis_units` | 二シナリオ間で0・1・2以上の状態が変わる分析単位数 |
| `uncertain_pct_of_1706` | `100 × uncertain_analysis_units / 1,706` |
| `n_units_2021_eq2` | 2021年の法人事業所数がちょうど2の分析単位数 |
| `n_down_2_to_le1_exclude_566` | `exclude_566`で2→1以下となる分析単位数 |
| `down_2_to_le1_exclude_566_pct` | 上記件数を`n_units_2021_eq2`で割った百分率 |
| `n_down_2_to_le1_include_all_566` | `include_all_566`で2→1以下となる分析単位数 |
| `down_2_to_le1_include_all_566_pct` | 上記件数を`n_units_2021_eq2`で割った百分率 |
| `n_units_2021_eq1` | 2021年の法人事業所数がちょうど1の分析単位数 |
| `n_up_1_to_ge2_exclude_566` | `exclude_566`で1→2以上となる分析単位数 |
| `up_1_to_ge2_exclude_566_pct` | 上記件数を`n_units_2021_eq1`で割った百分率 |
| `n_up_1_to_ge2_include_all_566` | `include_all_566`で1→2以上となる分析単位数 |
| `up_1_to_ge2_include_all_566_pct` | 上記件数を`n_units_2021_eq1`で割った百分率 |
| `n_down_ge2_to_le1_exclude_566` | `exclude_566`で2以上→1以下となる分析単位数 |
| `n_up_le1_to_ge2_exclude_566` | `exclude_566`で1以下→2以上となる分析単位数 |
| `net_change_units_ge2_exclude_566` | `exclude_566`の上向き全横断−下向き全横断 |
| `n_down_ge2_to_le1_include_all_566` | `include_all_566`で2以上→1以下となる分析単位数 |
| `n_up_le1_to_ge2_include_all_566` | `include_all_566`で1以下→2以上となる分析単位数 |
| `net_change_units_ge2_include_all_566` | `include_all_566`の上向き全横断−下向き全横断 |
| `interval_type` | `per_industry_marginal_worst_case`。業種ごとの周辺的端点であることを示す |
| `jointly_satisfiable_across_industries` | 全行`false`。各業種の`include_all_566`は同時成立しない |

## `data/a3/analysis_scope.csv`

前稿の15業種を、2021年→2024年の比較可能性に基づいて分類した判断表です。

| 列 | 定義 |
|---|---|
| `industry_code`, `industry_name` | 業種コード・業種名 |
| `comparison_group` | `exact_comparison`、`retail_endpoint_scenarios`、`retail_reference`、`excluded`のいずれか |
| `comparison_method` | 点比較、端点シナリオ、参考、除外という比較方法 |
| `publication_role` | 記事上の表示区分。これは分析から推定したパラメータではなく編集上の判断 |
| `reason` | 公式分類対応と内容定義に基づく理由 |

## `data/a3/boundary_sensitivity.csv`

2021年6月から2024年6月までの自治体境界変更監査と、影響35地域を除外した場合の感度をlong形式で収録します。

| `metric` | 定義 |
|---|---|
| `boundary_change_events` | 境界変更イベント数 |
| `unique_pairs` | 重複除去後の自治体ペア数 |
| `connected_components` | 自治体ペアをグラフ化した連結成分数 |
| `affected_analysis_units` | 影響を受けた分析単位数 |
| `component_industry_combinations` | 17成分×点比較9業種＝153組合せ |
| `mixed_sign_combinations` | 同一成分内で事業所数変化の符号が混在した組合せ数 |
| `zero_sum_combinations` | 成分内の事業所数変化合計が0の組合せ数 |
| `mixed_sign_and_zero_sum` | 符号混在かつ成分内変化合計0の組合せ数 |
| `max_abs_down_2_to_le1_difference_pt` | 点比較9業種における、1,706単位版と1,741単位版の下向き率の最大絶対差。単位はパーセントポイント |
| `max_abs_up_1_to_ge2_difference_pt` | 点比較9業種における上向き率の最大絶対差。単位はパーセントポイント |

`unit`列は各値の単位です。率の差は`percentage_points`です。

## `data/phase1/model_sensitivity.csv`

前稿の2021年横断分析について、人口だけを説明変数とする4仕様の結果を収録します。全事業所ベース、双葉町を除く1,740自治体であり、法人限定1,706単位の遷移分析とは別データです。

| 列 | 定義 |
|---|---|
| `industry_code`, `industry_name` | 業種コード・業種名 |
| `model` | `binary_logit`、`ordered_logit`、`poisson`、`negbin` |
| `n_obs` | 観測自治体数。全行1,740 |
| `topcode` | 順序ロジットで5以上を5へまとめた上限。該当モデル以外は欠測 |
| `converged` | 保存した推定が収束したか |
| `S2`～`S5` | 推定上、事業所数がk以上となる確率が50%に達する人口。単位は人 |
| `s5_s2` | 正規化境界比 `(S5 / 5) / (S2 / 2)`。生の`S5 / S2`ではなく、単位を持たない |
| `s5_s2_ci_lo`, `s5_s2_ci_hi` | 自治体再標本化ブートストラップによる95%パーセンタイル区間の下端・上端 |
| `boot_B`, `boot_valid`, `boot_seed` | 要求反復数、有効反復数、乱数seed |
| `poisson_pearson_chi2_df` | ポアソンモデルのPearsonカイ二乗／自由度。他モデルは欠測 |
| `negbin_alpha_mom` | 負の二項モデルのモーメント法によるNB2のalpha。他モデルは欠測 |

## `data/phase1/binary_logit_monotonicity_diagnostics.csv`

独立に推定した二値ロジットの累積予測確率について、Nが増えるにつれて確率が低下するという単調性からの微小な交差を業種別に確認した診断です。

| 列 | 定義 |
|---|---|
| `industry_code`, `industry_name` | 業種コード・業種名 |
| `cross_municipalities` | 累積予測確率の交差が生じた自治体数 |
| `cross_pop_min`, `cross_pop_max` | 交差が生じた自治体人口の最小・最大。該当なしは欠測 |
| `cross_max_gap` | 隣接するNの累積予測確率が逆転した幅の最大値。確率尺度（0～1）であり、百分率やパーセントポイントではない |
