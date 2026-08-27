# 法人企業統計 2026Q1 v3.2 最終公開監査

**STATUS: PASS**

## 監査期待値の変更履歴

- 変更前タイトル：食い違いは小規模資本金層に集中していた――法人企業統計、二つの推計を41四半期並べる
- 変更後タイトル：利益率方向の食い違いは小規模資本金層に集中していた――法人企業統計、二つの推計を41四半期比べる
- 変更理由：中心主張を営業利益率方向の不一致に限定し、期間表現を最終公開版に合わせた。
- 監査期待値：`article_title_exact_and_small_capital` を `EXPECTED_VALUE_UPDATED` として更新。

## フェイルクローズ判定

| check_id | status | detail |
|---|---|---|
| release_required_files_present_for_phase | PASS | phase=final; missing=[] |
| release_failure_markers_absent | PASS | present=[] |
| immutability_pre_build_snapshot_valid | PASS | pre_build_files=11 |
| immutability_v3_1_path_and_sha256_exact | PASS | scan_error=''; missing=[]; added=[]; changed=[] |
| immutability_manifest_readable | PASS | JSON object loaded |
| immutability_manifest_header_and_counts | PASS | release=2026Q1_v3_2; frozen=2026Q1_v3_1; pre=11; post=11 |
| immutability_manifest_entries_exact | PASS | duplicates=[]; bad_entries=[]; summary={'added': 0, 'changed': 0, 'matched': 11, 'missing': 0} |
| release_frozen_v3_1_audit_pass | PASS | /Users/araimasayuki/Documents/ChatGPT/論文作り/corporate_quarterly_pipeline/outputs/2026Q1_v3_1/audit_v3_1.md |
| claims_required_columns | PASS | missing=[] |
| claims_unique_nonempty_and_all_pass | PASS | rows=48; duplicates=[] |
| claims_six_2026q1_values_match_v3_canonical | PASS | missing=[]; errors=[] |
| claims_six_2026q1_displays_and_units | PASS | invalid=[] |
| unit_registry_claim_and_metric_validation | PASS | errors=[] |
| unit_registry_required_metric_types | PASS | observed={'count': 'count', 'currency': 'oku_yen', 'currency_threshold_yen': 'yen', 'deadband_threshold': 'percent', 'difference_between_growth_rates': 'percentage_points', 'direction_mismatch_rate': 'percent', 'implied_relative_margin_change': 'percent', 'yoy_growth_rate': 'percent'} |
| units_decision_margin_pp_deadband_and_mismatch_percent | PASS | decision_invalid=[]; deadband_units={'percent'}; mismatch_units={'percent'} |
| corrections_required_columns | PASS | missing=[] |
| corrections_exact_six_traceable_unit_and_display_rows | PASS | rows=6; pairs=[('V31-LARGE-DECISION-MARGIN-MEDIAN', 'display_value'), ('V31-LARGE-DECISION-MARGIN-MEDIAN', 'unit'), ('V31-MIDDLE-DECISION-MARGIN-MEDIAN', 'display_value'), ('V31-MIDDLE-DECISION-MARGIN-MEDIAN', 'unit'), ('V31-SMALL-DECISION-MARGIN-MEDIAN', 'display_value'), ('V31-SMALL-DECISION-MARGIN-MEDIAN', 'unit')] |
| expected_values_required_columns | PASS | missing=[] |
| expected_title_change_explicitly_recorded | PASS | rows=[{'check_id': 'article_title_exact_and_small_capital', 'before_expected_value': '食い違いは小規模資本金層に集中していた――法人企業統計、二つの推計を41四半期並べる', 'after_expected_value': '利益率方向の食い違いは小規模資本金層に集中していた――法人企業統計、二つの推計を41四半期比べる', 'change_reason': '主張を営業利益率方向の不一致に限定し、期間表現を最終版へ更新', 'status': 'EXPECTED_VALUE_UPDATED'}] |
| data_heatmap_old_pct_column_absent_new_pp_present | PASS | columns=['capital_code', 'capital_scope_ja', 'metric_id', 'metric_label_ja', 'mismatch_count', 'comparable_quarters', 'total_quarters', 'mismatch_rate_pct', 'noncomparable_quarters', 'comparison_status', 'metric_interpretation_note', 'census_sample_design_ja', 'rotation_status', 'rotation_note_ja', 'census_threshold_yen', 'census_threshold_label_ja', 'design_interpretation_note', 'continuing_decision_margin_abs_gap_median_pp', 'cross_series_growth_gap_divergence_median_pp', 'large_amplitude_explanation_status', 'exploratory_backtest_status', 'sample_error_status', 'series_comparability_note', 'series_comparability_limitation', 'continuing_sample_size_limitation', 'profit_standard_error_limitation', 'continuing_margin_interpretation', 'mismatch_rate_unit', 'continuing_decision_margin_abs_gap_median_unit', 'cross_series_growth_gap_divergence_median_unit'] |
| data_heatmap_required_columns | PASS | missing=[] |
| data_heatmap_values_and_pp_medians_canonical | PASS | cells={('19', 'margin'): (16, 41, 39.0), ('19', 'operating_profit'): (13, 41, 31.7), ('19', 'sales'): (6, 40, 15.0), ('24', 'margin'): (6, 41, 14.6), ('24', 'operating_profit'): (4, 41, 9.8), ('24', 'sales'): (7, 41, 17.1), ('25', 'margin'): (0, 41, 0.0), ('25', 'operating_profit'): (0, 41, 0.0), ('25', 'sales'): (1, 41, 2.4)}; invalid_medians=[] |
| data_headline_required_columns | PASS | missing=[] |
| data_headline_2x2_canonical | PASS | cells={(True, False): 9, (False, True): 2, (True, True): 1, (False, False): 29}; totals_ok=True |
| data_deadband_required_columns | PASS | missing=[] |
| data_deadband_canonical_and_percent_not_points | PASS | small={0.5: (15, 39, 38.5), 1.0: (14, 37, 37.8), 2.0: (10, 33, 30.3), 3.0: (8, 29, 27.6)}; d3_ok=True; units={'percent'} |
| article_title_exact_and_small_capital | PASS | observed='利益率方向の食い違いは小規模資本金層に集中していた――法人企業統計、二つの推計を41四半期比べる' |
| article_visible_character_count_2900_3300 | PASS | visible_characters=3018 |
| article_exactly_one_unchanged_central_claim | PASS | central_claims=['V31-SMALL-MARGIN-DIRECTION-MISMATCH'] |
| article_formal_small_capital_first_body_mention | PASS | formal_index=23; shorthand_before=False |
| article_trigger_section_position_length_and_content | PASS | start=164; compare_start=1377; visible=226; statements={'scope': True, 'regular_values': True, 'continuing_values': True, 'sales_both_up': True, 'operating_directions_split': True, 'margin_direction_split': True, 'gaps': True, 'expanded_to_41': True}; missing_claims=[] |
| article_claim_markers_known_and_new_six_linked | PASS | unknown=[]; missing_new=[] |
| article_all_statistical_numbers_claim_linked | PASS | all statistical values explicitly linked |
| article_exactly_three_registered_figures | PASS | paths=['charts/mismatch_heatmap.png', 'charts/headline_2x2.png', 'charts/deadband_sensitivity.png'] |
| article_forbidden_wording_and_overclaims_absent | PASS | literal=[]; patterns=[] |
| article_excluded_topics_absent | PASS | hits=[] |
| article_central_claim_and_design_limit_unchanged | PASS | central=True; missing_design=[]; movement_general=True; negative_truth=True |
| article_continuing_margin_direction_only | PASS | direction_ok=True; invalid=[] |
| article_deadband_formula_and_percent_unit | PASS | deadband must be relative change percent, not a margin percentage-point difference |
| render_no_comments_relative_images_or_claim_ids | PASS | comments=0; relative_images=[]; claim_ids=[]; labels=[] |
| render_three_figure_markers_once_each | PASS | counts={'【図1：資本金階層・指標別の方向不一致率】': 1, '【図2：複合見出しの2×2表】': 1, '【図3：deadband感応度】': 1} |
| render_preserves_article_text_and_order | PASS | audit_normalized_chars=3033; render_normalized_chars=3033 |
| charts_manifest_header_and_count | PASS | entry_count=3 |
| charts_three_regenerated_source_hashed_pngs | PASS | invalid=[]; manifest_pngs=['deadband_sensitivity.png', 'headline_2x2.png', 'mismatch_heatmap.png']; files=['deadband_sensitivity.png', 'headline_2x2.png', 'mismatch_heatmap.png'] |
| charts_heatmap_neutral_title_pp_metadata | PASS | title='通常系列と継続標本系列の方向不一致率\n（2016Q1～2026Q1）'; decision={'19': 11.3, '24': 9.0, '25': 8.5}; divergence={'19': 11.20869500294094, '24': 4.070024346681685, '25': 1.0500234778042916}; units=True/True |
| charts_headline_structured_counts | PASS | entries=1 |
| charts_deadband_structured_percent_values | PASS | small={0.0: (16, 41, 39.0), 0.5: (15, 39, 38.5), 1.0: (14, 37, 37.8), 2.0: (10, 33, 30.3), 3.0: (8, 29, 27.6)}; definition='percent of implied relative operating-margin change; not an absolute operating-margin percentage-point difference' |
| release_existing_audit_pass_and_title_change_documented | PASS | audit status and expectation-change narrative checked |
| release_clean_package_verified | PASS | {"issues": [], "path": "/Users/araimasayuki/Documents/ChatGPT/論文作り/corporate_quarterly_pipeline/outputs/2026Q1_v3_2/corporate_quarterly_2026Q1_v3_2_clean.zip", "status": "PASS"} |

PASSは全チェックがPASSの場合にのみ付与する。`IMMUTABILITY_FAIL.md`または`FINAL_RELEASE_FAIL.md`が存在する場合はFAILとする。

## 全テスト

- status: PASS
- passed: 286
- minimum_existing_test_count: 213
