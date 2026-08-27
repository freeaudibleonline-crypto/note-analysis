# Phase 0 現在値再現ゲート

**STATUS: PASS**

| check_id | expected | actual | difference | tolerance | unit | status |
|---|---:|---:|---:|---:|---|---|
| all_operating_profit_yoy_delta | 25970.250000 | 25970.250000 | 0.000000 | 0.010000 | 億円 | PASS |
| all_ordinary_profit_yoy_delta | 41576.870000 | 41576.870000 | -0.000000 | 0.010000 | 億円 | PASS |
| all_gap_yoy_delta | 15606.620000 | 15606.620000 | -0.000000 | 0.010000 | 億円 | PASS |
| all_gap_share_of_ordinary_delta_pct | 37.540000 | 37.536784 | -0.003216 | 0.010000 | % | PASS |
| capital_25_ordinary_delta | 34231.100000 | 34231.100000 | 0.000000 | 0.010000 | 億円 | PASS |
| capital_25_ordinary_contribution_pct | 82.332000 | 82.332076 | 0.000076 | 0.010000 | % | PASS |
| capital_24_ordinary_delta | 5942.970000 | 5942.970000 | 0.000000 | 0.010000 | 億円 | PASS |
| capital_24_ordinary_contribution_pct | 14.294000 | 14.293933 | -0.000067 | 0.010000 | % | PASS |
| capital_19_ordinary_delta | 1402.800000 | 1402.800000 | -0.000000 | 0.010000 | 億円 | PASS |
| capital_19_ordinary_contribution_pct | 3.374000 | 3.373991 | -0.000009 | 0.010000 | % | PASS |
| manufacturing_ordinary_delta | 38783.330000 | 38783.330000 | -0.000000 | 0.010000 | 億円 | PASS |
| manufacturing_ordinary_contribution_pct | 93.281000 | 93.281024 | 0.000024 | 0.010000 | % | PASS |
| large_manufacturing_ordinary_delta | 29960.180000 | 29960.180000 | -0.000000 | 0.010000 | 億円 | PASS |
| large_manufacturing_ordinary_contribution_pct | 72.060000 | 72.059729 | -0.000271 | 0.010000 | % | PASS |
| small_manufacturing_ordinary_delta | 6225.360000 | 6225.360000 | 0.000000 | 0.010000 | 億円 | PASS |
| small_manufacturing_ordinary_contribution_pct | 14.973000 | 14.973133 | 0.000133 | 0.010000 | % | PASS |
| ict_machinery_operating_delta | 11801.410000 | 11801.410000 | -0.000000 | 0.010000 | 億円 | PASS |
| ict_machinery_ordinary_delta | 15853.140000 | 15853.140000 | 0.000000 | 0.010000 | 億円 | PASS |
| ict_machinery_gap_delta | 4051.730000 | 4051.730000 | 0.000000 | 0.010000 | 億円 | PASS |
| ict_machinery_ordinary_contribution_pct | 38.130000 | 38.129710 | -0.000290 | 0.010000 | % | PASS |
| ict_machinery_gap_share_pct | 25.560000 | 25.557902 | -0.002098 | 0.010000 | % | PASS |
| capital_25_sales_yoy_pct | 1.695800 | 1.695835 | 0.000035 | 0.010000 | % | PASS |
| capital_25_operating_yoy_pct | 18.494700 | 18.494685 | -0.000015 | 0.010000 | % | PASS |
| capital_25_operating_margin_delta_pp | 1.070000 | 1.069859 | -0.000141 | 0.005000 | ポイント | PASS |
| capital_19_sales_yoy_pct | 2.100900 | 2.100851 | -0.000049 | 0.010000 | % | PASS |
| capital_19_operating_yoy_pct | -1.890200 | -1.890184 | 0.000016 | 0.010000 | % | PASS |
| capital_19_operating_margin_delta_pp | -0.228000 | -0.227518 | 0.000482 | 0.005000 | ポイント | PASS |
| software_all_delta | 2431.420000 | 2431.420000 | 0.000000 | 0.010000 | 億円 | PASS |
| software_capital_19_delta | 1784.110000 | 1784.110000 | 0.000000 | 0.010000 | 億円 | PASS |
| software_capital_19_contribution_pct | 73.377000 | 73.377286 | 0.000286 | 0.010000 | % | PASS |
| capex_excluding_all_delta | -2342.640000 | -2342.640000 | -0.000000 | 0.010000 | 億円 | PASS |
| capex_including_all_delta | 88.780000 | 88.780000 | -0.000000 | 0.010000 | 億円 | PASS |

金額は億円、比率は%、利益率差はポイントで表示した。比率と利益率差の許容誤差はいずれもポイントで評価した。
期待値は監査ターゲットであり、記事の数値ソースではない。
