# 2026Q1 v3.1 公開監査

**STATUS: PASS**

| check_id | status | detail |
|---|---|---|
| release_required_files_present | PASS | missing=[] |
| release_required_charts_exact | PASS | expected=['deadband_sensitivity.png', 'headline_2x2.png', 'mismatch_heatmap.png']; observed=['deadband_sensitivity.png', 'headline_2x2.png', 'mismatch_heatmap.png']; png_signatures=True |
| claims_required_columns | PASS | missing=[] |
| claims_ids_unique_and_nonempty | PASS | rows=42 |
| claims_all_verified | PASS | every registry row must have verification_status=PASS |
| claims_article_use_is_boolean | PASS | article_use accepts only true/false or 1/0 |
| claims_display_values_nonempty | PASS | all claims require a human-inspectable display_value |
| claims_primary_and_supplemental_present | PASS | missing=[] |
| claims_no_nonoperating_candidate | PASS | nonoperating claim IDs=[] |
| claims_anchor_values_and_roles | PASS | invalid=[]; expected primary=16/41, supplemental=11/41 |
| article_title_exact_and_small_capital | PASS | observed='食い違いは小規模資本金層に集中していた――法人企業統計、二つの推計を41四半期並べる' |
| article_visible_character_count_2500_3500 | PASS | visible_characters=2697 |
| article_exactly_one_primary_central_claim | PASS | central_claims=['V31-SMALL-MARGIN-DIRECTION-MISMATCH'] |
| article_one_to_three_registered_figures | PASS | figure_count=3; names=['mismatch_heatmap.png', 'headline_2x2.png', 'deadband_sensitivity.png'] |
| article_forbidden_wording_and_overclaims | PASS | literal=[]; causal=[] |
| article_no_nonoperating_content | PASS | hits=[] |
| article_formal_small_capital_first_mention | PASS | formal_index=57; early_shorthand=False |
| article_claim_references_explicit_and_verified | PASS | unknown=[] |
| article_primary_and_supplemental_claims_linked | PASS | missing=[] |
| article_primary_16_41_supplemental_11_41 | PASS | primary_index=193; supplemental_index=300 |
| article_both_backtests_disclosed_post_hoc_exploratory | PASS | 16/41 and 11/41 must share an explicit post-2026Q1 exploratory-backtest disclosure |
| article_headline_support_asymmetry_10_vs_3 | PASS | requires descriptive counts without probability language |
| article_required_design_caveats | PASS | {'same_truth_not_assumed': True, 'entry_exit': True, 'response_continuity': True, 'weight': True, 'imputation': True, 'population': True, 'consistent_not_causal': True} |
| article_continuing_margin_direction_only_no_pp | PASS | numeric_pp_sentences=[] |
| article_deadband_unit_is_relative_rate_pct | PASS | deadband must not be described as an absolute margin-point difference |
| article_sample_and_standard_error_caveats | PASS | {'small_sample': True, 'profit_se': True, 'sample_error_unquantified': True} |
| article_neither_series_called_truth_or_correct | PASS | requires an explicit non-ranking caveat |
| article_extreme_yoy_flag_not_interpreted_as_base | PASS | sentences=['さらに、継続標本の営業利益増加率の絶対値が100％を超えた3件へ、NEAR_ZERO_BASE欄の機械的レビュー印 EXTREME_YOY_RATE_GT_100 を付けたが、名称にかかわらず低ベースやゼロ近傍を示す証拠とは扱わない'] |
| article_change_magnitude_confound_rejected_descriptively | PASS | the specified alternative explanation must be checked, not causally resolved |
| article_all_statistical_numbers_claim_linked | PASS | all statistical values explicitly linked |
| data_headline_2x2_required_columns | PASS | missing=[] |
| data_headline_2x2_canonical | PASS | observed={(True, False): 9, (False, True): 2, (True, True): 1, (False, False): 29}; totals_ok=True; exploratory=True |
| data_mismatch_heatmap_required_columns | PASS | missing=[] |
| data_mismatch_heatmap_canonical | PASS | observed={('19', 'margin'): (16, 41, 39.0), ('19', 'operating_profit'): (13, 41, 31.7), ('19', 'sales'): (6, 40, 15.0), ('24', 'margin'): (6, 41, 14.6), ('24', 'operating_profit'): (4, 41, 9.8), ('24', 'sales'): (7, 41, 17.1), ('25', 'margin'): (0, 41, 0.0), ('25', 'operating_profit'): (0, 41, 0.0), ('25', 'sales'): (1, 41, 2.4)} |
| data_heatmap_design_and_rotation_annotations | PASS | annotations=True; threshold_values=[np.int64(500000000)] |
| data_decision_margin_and_series_divergence_medians | PASS | invalid_capital_codes=[] |
| data_rounding_sensitivity_required_columns | PASS | missing=[] |
| data_rounding_sensitivity_canonical | PASS | rows=41; ambiguous=0; min=0.5; periods={'20182'} |
| data_rounding_separate_from_unquantified_sample_error | PASS | statuses=['NOT_QUANTIFIED_OPERATING_AND_ORDINARY_PROFIT_STANDARD_ERRORS_NOT_CALCULATED_BY_MOF'] |
| data_extreme_yoy_mechanical_review_fixed_window | PASS | flagged=3; margin_reversals=0; headline_reversals=0; methods=['FIXED_41_QUARTER_EVENT_ATTRIBUTION_NOT_ROW_DELETION'] |
| data_deadband_sensitivity_required_columns | PASS | missing=[] |
| data_deadband_sensitivity_canonical | PASS | small={0.5: (15, 39), 1.0: (14, 37), 2.0: (10, 33), 3.0: (8, 29)}; d3_rates_ok=True |
| data_deadband_unit_relative_rate_pct | PASS | units=['estimated_relative_margin_change_pct (%) - not operating-margin percentage points'] |
| release_existing_audit_pass | PASS | existing audit declares PASS without FAIL rows |
| frozen_v3_expected_snapshot_valid | PASS | expected_files=21 |
| frozen_v3_sha256_exact_equality | PASS | scan_error=''; missing=[]; added=[]; changed=[] |

PASS は全チェックが PASS の場合に限る。FAIL が一件でもあれば公開不可。
