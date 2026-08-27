# legacy_rule と corrected_rule_sensitivity

**STATUS: PASS**

v2出力とlegacy判定は不変。v3は修正規則による感度分析を別列で追加する。

| 候補 | legacy indicator | corrected indicator | legacy | corrected | 差分 |
|---|---|---|---|---|---:|
| A | `large_manufacturing_ordinary_contribution_pct` | `large_manufacturing_ordinary_contribution_pct` | `UNSTABLE_OR_NO_PATTERN` | `UNSTABLE_OR_NO_PATTERN` | SAME |
| B | `capital_margin_divergence_composite` | `capital_margin_divergence_boolean` | `RECENT_BUT_NOT_ESTABLISHED` | `RECENT_BUT_NOT_ESTABLISHED` | SAME |
| C | `software_rotation_composite` | `software_rotation_boolean` | `ONE_QUARTER_OUTLIER` | `UNSTABLE_OR_NO_PATTERN` | CHANGED |
| D | `net_non_operating_gap_share_pct` | `net_non_operating_gap_share_pct` | `RECENT_BUT_NOT_ESTABLISHED` | `RECENT_BUT_NOT_ESTABLISHED` | SAME |
| E | `ict_machinery_ordinary_contribution_pct` | `ict_machinery_ordinary_contribution_pct` | `UNSTABLE_OR_NO_PATTERN` | `RECENT_BUT_NOT_ESTABLISHED` | CHANGED |

BとCはBoolean条件のみで、corrected側の数値percentileはNA。A・D・Eの位置は `historical_percentile_inclusive_pct` で保存する。

## count4 × rollingの全10ケース

| count4 | rolling | corrected classification | rank |
|---:|---:|---|---:|
| 0 | False | `UNSTABLE_OR_NO_PATTERN` | 0 |
| 0 | True | `RECENT_BUT_NOT_ESTABLISHED` | 2 |
| 1 | False | `UNSTABLE_OR_NO_PATTERN` | 0 |
| 1 | True | `RECENT_BUT_NOT_ESTABLISHED` | 2 |
| 2 | False | `RECENT_BUT_NOT_ESTABLISHED` | 2 |
| 2 | True | `RECENT_BUT_NOT_ESTABLISHED` | 2 |
| 3 | False | `RECENT_BUT_NOT_ESTABLISHED` | 2 |
| 3 | True | `PERSISTENT_PATTERN` | 3 |
| 4 | False | `RECENT_BUT_NOT_ESTABLISHED` | 2 |
| 4 | True | `PERSISTENT_PATTERN` | 3 |

countの増加、またはrolling=False→Trueでdecision rankが低下しないことをpytestで全10ケース確認する。

継続標本系列は通常系列よりサンプルサイズが小さく、営業利益・経常利益の標準誤差率は財務省が算出していない。
