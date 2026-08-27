# 2026Q1 v3 最終監査

**STATUS: PASS**

| 監査ID | 状態 | 証拠 |
|---|---:|---|
| `archive_or_repository_complete` | PASS | repository=True; archive=False |
| `all_frozen_output_hashes_in_manifest` | PASS | files=38 |
| `runtime_dependencies` | PASS | {'status': 'PASS', 'python': '3.14.2', 'dependencies': ['beautifulsoup4', 'lxml', 'matplotlib', 'numpy', 'openpyxl', 'pandas', 'pyarrow', 'requests']} |
| `baseline_and_expanded_pytest_collection` | PASS | baseline=95; current=166 |
| `corrected_rule_all_ten_cases_monotone` | PASS | count4=0..4 x rolling=False/True |
| `legacy_2026q1_decisions_unchanged` | PASS | {'A': 'UNSTABLE_OR_NO_PATTERN', 'B': 'RECENT_BUT_NOT_ESTABLISHED', 'C': 'ONE_QUARTER_OUTLIER', 'D': 'RECENT_BUT_NOT_ESTABLISHED', 'E': 'UNSTABLE_OR_NO_PATTERN'} |
| `boolean_candidates_not_ranked_numerically` | PASS | B/C percentiles are null and numeric_history_eligible=False |
| `continuing_sample_2026q1_published_rates` | PASS | 12/12 capital-size published rates reproduced |
| `regular_series_2026q1_targets` | PASS | small sales/op/capex and large sales/op rounded targets |
| `small_capital_margin_direction_robustness_gate` | PASS | regular=DOWN; continuing=UP; continuing value is a directional proxy, not pp |
| `continuing_sample_limitations_explicit` | PASS | 継続標本系列は通常系列よりサンプルサイズが小さく、営業利益・経常利益の標準誤差率は財務省が算出していない。 |
| `continuing_sample_limitations_carried_by_all_outputs` | PASS | all CSV/Markdown/JSON analytical outputs carry the small-sample and profit-SE caveat; all three charts carry the same footnote |
| `nonoperating_current_identity` | PASS | component_sum=15606.62; residual=0.0 |
| `nonoperating_four_item_signs_and_rounding` | PASS | interest expense increased and contributes -6,760; other expense decreased and contributes +6,790 |
| `nonoperating_all_current_identities_and_additivity` | PASS | identity=416; additivity=1120 |
| `nonoperating_history_starts_mechanically` | PASS | mechanical earliest complete period=2009Q2 |
| `decision_is_exactly_one_allowed_value` | PASS | PUBLISH_SAMPLE_CONSTRUCTION_SENSITIVITY |
| `article_statistical_wording` | PASS | [] |
| `claims_v3_contract` | PASS | [] |
| `article_all_numbers_verified` | PASS | [] |
| `article_one_claim_two_figures_no_bridge_mix` | PASS | public_figures=2; generated_charts=3 |
| `frozen_v1_v2_outputs_unchanged` | PASS | before=38 files; after=38 files |
| `conditional_public_article` | PASS | exists=True; required=True |
| `required_v3_outputs` | PASS | all required files present |

## WARN / 解釈限界

- 継続標本系列は通常系列よりサンプルサイズが小さく、営業利益・経常利益の標準誤差率は財務省が算出していない。
- 継続標本の利益水準と符号はPDFから確認できず、利益率は増加率からの方向proxy。
- その他の営業外収益の特定要因は統計単独で断定できない。

継続標本系列は通常系列よりサンプルサイズが小さく、営業利益・経常利益の標準誤差率は財務省が算出していない。

欠損・計算不能値は0で補完しない。統計だけから原因を断定しない。
