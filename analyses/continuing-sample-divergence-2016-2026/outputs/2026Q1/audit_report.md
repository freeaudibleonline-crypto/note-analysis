# 監査報告 — 令和8年1〜3月期

**STATUS: PASS**

## 公開ゲート

| チェック | 状態 | 詳細 |
|---|---|---|
| raw_manifest_hashes | PASS | 14 source hashes verified |
| oku_to_trillion_conversion | PASS | 10,000 億円 = 1.0 兆円 |
| required_metric_sales | PASS | Available without missing-value imputation |
| required_metric_operating_profit | PASS | Available without missing-value imputation |
| required_metric_ordinary_profit | PASS | Available without missing-value imputation |
| required_metric_capex_including_software | PASS | Available without missing-value imputation |
| required_metric_capex_excluding_software | PASS | Available without missing-value imputation |
| required_metric_software_capex_derived | PASS | Available without missing-value imputation |
| required_metric_employee_pay_per_person_approx | PASS | Available without missing-value imputation |
| required_metric_employee_total_pay_derived | PASS | Available without missing-value imputation |
| required_metric_employee_count | PASS | Available without missing-value imputation |
| required_metric_cash_and_deposits | PASS | Available without missing-value imputation |
| required_metric_total_borrowings_derived | PASS | Available without missing-value imputation |
| required_metric_interest_expense | PASS | Available without missing-value imputation |
| required_metric_ordinary_minus_operating | PASS | Available without missing-value imputation |
| derived_identity_software_bridge_raw_value_oku_yen | PASS | rows=522, complete inputs=522, max absolute error=0.000000000000 |
| derived_identity_borrowings_sum_raw_value_oku_yen | PASS | rows=522, complete inputs=522, max absolute error=0.000000000931 |
| derived_identity_ordinary_operating_gap_raw_value_oku_yen | PASS | rows=522, complete inputs=522, max absolute error=0.000000000000 |
| derived_identity_employee_total_pay_raw_value_oku_yen | PASS | rows=522, complete inputs=522, max absolute error=0.000000000000 |
| derived_identity_software_bridge_raw_lag4_value_oku_yen | PASS | rows=522, complete inputs=522, max absolute error=0.000000000000 |
| derived_identity_borrowings_sum_raw_lag4_value_oku_yen | PASS | rows=522, complete inputs=522, max absolute error=0.000000000931 |
| derived_identity_ordinary_operating_gap_raw_lag4_value_oku_yen | PASS | rows=522, complete inputs=522, max absolute error=0.000000000000 |
| derived_identity_employee_total_pay_raw_lag4_value_oku_yen | PASS | rows=522, complete inputs=522, max absolute error=0.000000000000 |
| derived_identity_employee_pay_per_person_source_value | PASS | rows=522, complete inputs=522, max absolute error=0.000000000000 |
| derived_identity_employee_pay_per_person_raw_lag4_value | PASS | rows=522, complete inputs=522, max absolute error=0.000000000000 |
| capital_components_sales_completeness | PASS | observed=3, expected=3, missing names=[], extra names=[], null cells=0 |
| capital_components_sales_raw_value_oku_yen | PASS | components=4086614.05, total=4086614.05 (億円) |
| capital_components_sales_raw_lag4_value_oku_yen | PASS | components=4042310.81, total=4042310.81 (億円) |
| capital_components_sales_raw_yoy_delta_oku_yen | PASS | components=44303.24, total=44303.24 (億円) |
| capital_components_operating_profit_completeness | PASS | observed=3, expected=3, missing names=[], extra names=[], null cells=0 |
| capital_components_operating_profit_raw_value_oku_yen | PASS | components=262834.36, total=262834.36 (億円) |
| capital_components_operating_profit_raw_lag4_value_oku_yen | PASS | components=236864.11, total=236864.11 (億円) |
| capital_components_operating_profit_raw_yoy_delta_oku_yen | PASS | components=25970.25, total=25970.25 (億円) |
| capital_components_ordinary_profit_completeness | PASS | observed=3, expected=3, missing names=[], extra names=[], null cells=0 |
| capital_components_ordinary_profit_raw_value_oku_yen | PASS | components=326270.86, total=326270.86 (億円) |
| capital_components_ordinary_profit_raw_lag4_value_oku_yen | PASS | components=284693.99, total=284693.99 (億円) |
| capital_components_ordinary_profit_raw_yoy_delta_oku_yen | PASS | components=41576.87, total=41576.87 (億円) |
| capital_components_capex_including_software_completeness | PASS | observed=3, expected=3, missing names=[], extra names=[], null cells=0 |
| capital_components_capex_including_software_raw_value_oku_yen | PASS | components=188063.90, total=188063.90 (億円) |
| capital_components_capex_including_software_raw_lag4_value_oku_yen | PASS | components=187975.12, total=187975.12 (億円) |
| capital_components_capex_including_software_raw_yoy_delta_oku_yen | PASS | components=88.78, total=88.78 (億円) |
| capital_components_capex_excluding_software_completeness | PASS | observed=3, expected=3, missing names=[], extra names=[], null cells=0 |
| capital_components_capex_excluding_software_raw_value_oku_yen | PASS | components=165661.68, total=165661.68 (億円) |
| capital_components_capex_excluding_software_raw_lag4_value_oku_yen | PASS | components=168004.32, total=168004.32 (億円) |
| capital_components_capex_excluding_software_raw_yoy_delta_oku_yen | PASS | components=-2342.64, total=-2342.64 (億円) |
| capital_components_software_capex_derived_completeness | PASS | observed=3, expected=3, missing names=[], extra names=[], null cells=0 |
| capital_components_software_capex_derived_raw_value_oku_yen | PASS | components=22402.22, total=22402.22 (億円) |
| capital_components_software_capex_derived_raw_lag4_value_oku_yen | PASS | components=19970.80, total=19970.80 (億円) |
| capital_components_software_capex_derived_raw_yoy_delta_oku_yen | PASS | components=2431.42, total=2431.42 (億円) |
| capital_components_cash_and_deposits_completeness | PASS | observed=3, expected=3, missing names=[], extra names=[], null cells=0 |
| capital_components_cash_and_deposits_raw_value_oku_yen | PASS | components=2795196.62, total=2795196.62 (億円) |
| capital_components_cash_and_deposits_raw_lag4_value_oku_yen | PASS | components=2687438.33, total=2687438.33 (億円) |
| capital_components_cash_and_deposits_raw_yoy_delta_oku_yen | PASS | components=107758.29, total=107758.29 (億円) |
| capital_components_total_borrowings_derived_completeness | PASS | observed=3, expected=3, missing names=[], extra names=[], null cells=0 |
| capital_components_total_borrowings_derived_raw_value_oku_yen | PASS | components=5759814.34, total=5759814.34 (億円) |
| capital_components_total_borrowings_derived_raw_lag4_value_oku_yen | PASS | components=5341177.08, total=5341177.08 (億円) |
| capital_components_total_borrowings_derived_raw_yoy_delta_oku_yen | PASS | components=418637.26, total=418637.26 (億円) |
| capital_components_interest_expense_completeness | PASS | observed=3, expected=3, missing names=[], extra names=[], null cells=0 |
| capital_components_interest_expense_raw_value_oku_yen | PASS | components=28446.99, total=28446.99 (億円) |
| capital_components_interest_expense_raw_lag4_value_oku_yen | PASS | components=21687.13, total=21687.13 (億円) |
| capital_components_interest_expense_raw_yoy_delta_oku_yen | PASS | components=6759.86, total=6759.86 (億円) |
| capital_components_employee_wages_completeness | PASS | observed=3, expected=3, missing names=[], extra names=[], null cells=0 |
| capital_components_employee_wages_raw_value_oku_yen | PASS | components=328653.09, total=328653.09 (億円) |
| capital_components_employee_wages_raw_lag4_value_oku_yen | PASS | components=321156.01, total=321156.01 (億円) |
| capital_components_employee_wages_raw_yoy_delta_oku_yen | PASS | components=7497.08, total=7497.08 (億円) |
| capital_components_employee_bonuses_completeness | PASS | observed=3, expected=3, missing names=[], extra names=[], null cells=0 |
| capital_components_employee_bonuses_raw_value_oku_yen | PASS | components=60855.75, total=60855.75 (億円) |
| capital_components_employee_bonuses_raw_lag4_value_oku_yen | PASS | components=59926.58, total=59926.58 (億円) |
| capital_components_employee_bonuses_raw_yoy_delta_oku_yen | PASS | components=929.17, total=929.17 (億円) |
| capital_components_employee_total_pay_derived_completeness | PASS | observed=3, expected=3, missing names=[], extra names=[], null cells=0 |
| capital_components_employee_total_pay_derived_raw_value_oku_yen | PASS | components=389508.84, total=389508.84 (億円) |
| capital_components_employee_total_pay_derived_raw_lag4_value_oku_yen | PASS | components=381082.59, total=381082.59 (億円) |
| capital_components_employee_total_pay_derived_raw_yoy_delta_oku_yen | PASS | components=8426.25, total=8426.25 (億円) |
| capital_components_employee_count_completeness | PASS | observed=3, expected=3, missing names=[], extra names=[], null cells=0 |
| capital_components_employee_count_source_value | PASS | components=33584884.00, total=33584884.00 (人) |
| capital_components_employee_count_raw_lag4_value | PASS | components=33374544.00, total=33374544.00 (人) |
| capital_components_employee_count_raw_yoy_delta | PASS | components=210340.00, total=210340.00 (人) |
| capital_components_ordinary_minus_operating_completeness | PASS | observed=3, expected=3, missing names=[], extra names=[], null cells=0 |
| capital_components_ordinary_minus_operating_raw_value_oku_yen | PASS | components=63436.50, total=63436.50 (億円) |
| capital_components_ordinary_minus_operating_raw_lag4_value_oku_yen | PASS | components=47829.88, total=47829.88 (億円) |
| capital_components_ordinary_minus_operating_raw_yoy_delta_oku_yen | PASS | components=15606.62, total=15606.62 (億円) |
| industry_components_sales_completeness | PASS | observed=11, expected=11, missing names=[], extra names=[], null cells=0 |
| industry_components_sales_raw_value_oku_yen | PASS | published-major-industry sum=4086614.05, total=4086614.05 (億円) |
| industry_components_sales_raw_lag4_value_oku_yen | PASS | published-major-industry sum=4042310.81, total=4042310.81 (億円) |
| industry_components_sales_raw_yoy_delta_oku_yen | PASS | published-major-industry sum=44303.24, total=44303.24 (億円) |
| industry_components_operating_profit_completeness | PASS | observed=11, expected=11, missing names=[], extra names=[], null cells=0 |
| industry_components_operating_profit_raw_value_oku_yen | PASS | published-major-industry sum=262834.36, total=262834.36 (億円) |
| industry_components_operating_profit_raw_lag4_value_oku_yen | PASS | published-major-industry sum=236864.11, total=236864.11 (億円) |
| industry_components_operating_profit_raw_yoy_delta_oku_yen | PASS | published-major-industry sum=25970.25, total=25970.25 (億円) |
| industry_components_ordinary_profit_completeness | PASS | observed=11, expected=11, missing names=[], extra names=[], null cells=0 |
| industry_components_ordinary_profit_raw_value_oku_yen | PASS | published-major-industry sum=326270.86, total=326270.86 (億円) |
| industry_components_ordinary_profit_raw_lag4_value_oku_yen | PASS | published-major-industry sum=284693.99, total=284693.99 (億円) |
| industry_components_ordinary_profit_raw_yoy_delta_oku_yen | PASS | published-major-industry sum=41576.87, total=41576.87 (億円) |
| industry_components_capex_including_software_completeness | PASS | observed=11, expected=11, missing names=[], extra names=[], null cells=0 |
| industry_components_capex_including_software_raw_value_oku_yen | PASS | published-major-industry sum=188063.90, total=188063.90 (億円) |
| industry_components_capex_including_software_raw_lag4_value_oku_yen | PASS | published-major-industry sum=187975.12, total=187975.12 (億円) |
| industry_components_capex_including_software_raw_yoy_delta_oku_yen | PASS | published-major-industry sum=88.78, total=88.78 (億円) |
| industry_components_capex_excluding_software_completeness | PASS | observed=11, expected=11, missing names=[], extra names=[], null cells=0 |
| industry_components_capex_excluding_software_raw_value_oku_yen | PASS | published-major-industry sum=165661.68, total=165661.68 (億円) |
| industry_components_capex_excluding_software_raw_lag4_value_oku_yen | PASS | published-major-industry sum=168004.32, total=168004.32 (億円) |
| industry_components_capex_excluding_software_raw_yoy_delta_oku_yen | PASS | published-major-industry sum=-2342.64, total=-2342.64 (億円) |
| industry_components_software_capex_derived_completeness | PASS | observed=11, expected=11, missing names=[], extra names=[], null cells=0 |
| industry_components_software_capex_derived_raw_value_oku_yen | PASS | published-major-industry sum=22402.22, total=22402.22 (億円) |
| industry_components_software_capex_derived_raw_lag4_value_oku_yen | PASS | published-major-industry sum=19970.80, total=19970.80 (億円) |
| industry_components_software_capex_derived_raw_yoy_delta_oku_yen | PASS | published-major-industry sum=2431.42, total=2431.42 (億円) |
| industry_components_cash_and_deposits_completeness | PASS | observed=11, expected=11, missing names=[], extra names=[], null cells=0 |
| industry_components_cash_and_deposits_raw_value_oku_yen | PASS | published-major-industry sum=2795196.62, total=2795196.62 (億円) |
| industry_components_cash_and_deposits_raw_lag4_value_oku_yen | PASS | published-major-industry sum=2687438.33, total=2687438.33 (億円) |
| industry_components_cash_and_deposits_raw_yoy_delta_oku_yen | PASS | published-major-industry sum=107758.29, total=107758.29 (億円) |
| industry_components_total_borrowings_derived_completeness | PASS | observed=11, expected=11, missing names=[], extra names=[], null cells=0 |
| industry_components_total_borrowings_derived_raw_value_oku_yen | PASS | published-major-industry sum=5759814.34, total=5759814.34 (億円) |
| industry_components_total_borrowings_derived_raw_lag4_value_oku_yen | PASS | published-major-industry sum=5341177.08, total=5341177.08 (億円) |
| industry_components_total_borrowings_derived_raw_yoy_delta_oku_yen | PASS | published-major-industry sum=418637.26, total=418637.26 (億円) |
| industry_components_interest_expense_completeness | PASS | observed=11, expected=11, missing names=[], extra names=[], null cells=0 |
| industry_components_interest_expense_raw_value_oku_yen | PASS | published-major-industry sum=28446.99, total=28446.99 (億円) |
| industry_components_interest_expense_raw_lag4_value_oku_yen | PASS | published-major-industry sum=21687.13, total=21687.13 (億円) |
| industry_components_interest_expense_raw_yoy_delta_oku_yen | PASS | published-major-industry sum=6759.86, total=6759.86 (億円) |
| industry_components_employee_wages_completeness | PASS | observed=11, expected=11, missing names=[], extra names=[], null cells=0 |
| industry_components_employee_wages_raw_value_oku_yen | PASS | published-major-industry sum=328653.09, total=328653.09 (億円) |
| industry_components_employee_wages_raw_lag4_value_oku_yen | PASS | published-major-industry sum=321156.01, total=321156.01 (億円) |
| industry_components_employee_wages_raw_yoy_delta_oku_yen | PASS | published-major-industry sum=7497.08, total=7497.08 (億円) |
| industry_components_employee_bonuses_completeness | PASS | observed=11, expected=11, missing names=[], extra names=[], null cells=0 |
| industry_components_employee_bonuses_raw_value_oku_yen | PASS | published-major-industry sum=60855.75, total=60855.75 (億円) |
| industry_components_employee_bonuses_raw_lag4_value_oku_yen | PASS | published-major-industry sum=59926.58, total=59926.58 (億円) |
| industry_components_employee_bonuses_raw_yoy_delta_oku_yen | PASS | published-major-industry sum=929.17, total=929.17 (億円) |
| industry_components_employee_total_pay_derived_completeness | PASS | observed=11, expected=11, missing names=[], extra names=[], null cells=0 |
| industry_components_employee_total_pay_derived_raw_value_oku_yen | PASS | published-major-industry sum=389508.84, total=389508.84 (億円) |
| industry_components_employee_total_pay_derived_raw_lag4_value_oku_yen | PASS | published-major-industry sum=381082.59, total=381082.59 (億円) |
| industry_components_employee_total_pay_derived_raw_yoy_delta_oku_yen | PASS | published-major-industry sum=8426.25, total=8426.25 (億円) |
| industry_components_employee_count_completeness | PASS | observed=11, expected=11, missing names=[], extra names=[], null cells=0 |
| industry_components_employee_count_source_value | PASS | published-major-industry sum=33584884.00, total=33584884.00 (人) |
| industry_components_employee_count_raw_lag4_value | PASS | published-major-industry sum=33374544.00, total=33374544.00 (人) |
| industry_components_employee_count_raw_yoy_delta | PASS | published-major-industry sum=210340.00, total=210340.00 (人) |
| industry_components_ordinary_minus_operating_completeness | PASS | observed=11, expected=11, missing names=[], extra names=[], null cells=0 |
| industry_components_ordinary_minus_operating_raw_value_oku_yen | PASS | published-major-industry sum=63436.50, total=63436.50 (億円) |
| industry_components_ordinary_minus_operating_raw_lag4_value_oku_yen | PASS | published-major-industry sum=47829.88, total=47829.88 (億円) |
| industry_components_ordinary_minus_operating_raw_yoy_delta_oku_yen | PASS | published-major-industry sum=15606.62, total=15606.62 (億円) |
| finance_reconciliation_capex_excluding_software_source_value | PASS | including-finance=17143220, non-finance+finance=17143220 (source unit) |
| finance_reconciliation_capex_excluding_software_raw_lag4_value | PASS | including-finance=17306085, non-finance+finance=17306085 (source unit) |
| finance_reconciliation_capex_including_software_source_value | PASS | including-finance=20029906, non-finance+finance=20029906 (source unit) |
| finance_reconciliation_capex_including_software_raw_lag4_value | PASS | including-finance=19912125, non-finance+finance=19912125 (source unit) |
| finance_reconciliation_employee_bonuses_source_value | PASS | including-finance=6662306, non-finance+finance=6662306 (source unit) |
| finance_reconciliation_employee_bonuses_raw_lag4_value | PASS | including-finance=6501032, non-finance+finance=6501032 (source unit) |
| finance_reconciliation_employee_wages_source_value | PASS | including-finance=34588722, non-finance+finance=34588722 (source unit) |
| finance_reconciliation_employee_wages_raw_lag4_value | PASS | including-finance=33779513, non-finance+finance=33779513 (source unit) |
| finance_reconciliation_employee_count_source_value | PASS | including-finance=34855940, non-finance+finance=34855940 (source unit) |
| finance_reconciliation_employee_count_raw_lag4_value | PASS | including-finance=34682016, non-finance+finance=34682016 (source unit) |
| finance_reconciliation_ordinary_profit_source_value | PASS | including-finance=37094413, non-finance+finance=37094413 (source unit) |
| finance_reconciliation_ordinary_profit_raw_lag4_value | PASS | including-finance=30437043, non-finance+finance=30437043 (source unit) |
| published_sa_rate_error | PASS | 15 series compared; max absolute error=0.000000000000 percentage points |
| pdf_published_yoy_rate_sales | PASS | computed=1.095988%, PDF=1.1%, absolute error=0.004012 percentage points |
| processed_official_yoy_rate_sales | PASS | processed official_yoy_pct=1.1, PDF reference=1.1 |
| pdf_published_yoy_rate_operating_profit | PASS | computed=10.964198%, PDF=11.0%, absolute error=0.035802 percentage points |
| processed_official_yoy_rate_operating_profit | PASS | processed official_yoy_pct=11.0, PDF reference=11.0 |
| pdf_published_yoy_rate_ordinary_profit | PASS | computed=14.604056%, PDF=14.6%, absolute error=0.004056 percentage points |
| processed_official_yoy_rate_ordinary_profit | PASS | processed official_yoy_pct=14.6, PDF reference=14.6 |
| pdf_published_yoy_rate_capex_including_software | PASS | computed=0.047230%, PDF=0.0%, absolute error=0.047230 percentage points |
| processed_official_yoy_rate_capex_including_software | PASS | processed official_yoy_pct=0.0, PDF reference=0.0 |
| pdf_published_yoy_rate_capex_excluding_software | PASS | computed=-1.394393%, PDF=-1.4%, absolute error=0.005607 percentage points |
| processed_official_yoy_rate_capex_excluding_software | PASS | processed official_yoy_pct=-1.4, PDF reference=-1.4 |
| processed_official_yoy_rate_coverage | PASS | populated headline official_yoy_pct rows=5, expected=5 |
| pdf_ranked_amount_sales | PASS | structured amount rounds to 4,086,614 億円; PDF page 1 reports rank 1 of 288 quarters. The rank is a PDF cross-check, not independently recomputed from the three-period extract. |
| pdf_ranked_amount_ordinary_profit | PASS | structured amount rounds to 326,271 億円; PDF page 1 reports rank 3 of 288 quarters. The rank is a PDF cross-check, not independently recomputed from the three-period extract. |
| pdf_ranked_amount_capex_including_software | PASS | structured amount rounds to 188,064 億円; PDF page 1 reports rank 1 of 99 quarters. The rank is a PDF cross-check, not independently recomputed from the three-period extract. |
| raw_yoy_sa_variables_separate | PASS | Raw, year-on-year, raw quarter-on-quarter, and seasonally adjusted variables are separate |
| target_period_end_parsed | PASS | period_end populated for 9,978 target-period rows |
| missing_values_not_zero_imputed | PASS | 0 missing/derived-missing current values retained as null, never zero-filled |
| canonical_observation_key_unique | PASS | duplicate rows=0 |
| finance_scope_separation | PASS | available scopes=['EXCL_FINANCE_INSURANCE', 'FINANCE_INSURANCE_ONLY', 'INCL_FINANCE_INSURANCE'] |
| quality_log_missing_or_unparseable_value | PASS | logged events=0, fatal=0; values are not imputed |
| quality_log_table_shape | PASS | logged events=0, fatal=0; values are not imputed |
| quality_log_unknown_dimension_code | PASS | logged events=0, fatal=0; values are not imputed |
| quality_log_unknown_metric_code | PASS | logged events=0, fatal=0; values are not imputed |
| quality_log_industry_classification_change | PASS | logged events=0, fatal=0; values are not imputed |
| profit_loss_transition_status_persisted | PASS | Persisted transition statuses match recomputation |
| profit_loss_transition_detection | PASS | 63 black/red transitions detected; 38 negative-base rates suppressed |
| claims_unique_ids | PASS | All claim IDs are unique |
| claims_all_numeric_verified | PASS | Every FACT/CALC claim has finite inputs |
| claims_value_unit_display_consistency | PASS | Exact claim values, units, and rounded displays are consistent |
| claims_hypotheses_explicitly_labelled | PASS | labelled hypotheses=3 |
| chart_inputs_claim_backed | PASS | 29 exact plotted values matched to CHART_INPUT rows in claims.csv |
| chart_artifacts_complete | PASS | charts=['allocation_growth.png', 'capex_software_bridge.png', 'operating_profit_capital_contribution.png', 'operating_profit_industry_contribution.png', 'profit_margin_and_gap.png'], nontrivial_png_bytes=True |
| article_claim_marker_uniqueness | PASS | 40 markers, 40 unique |
| article_claim_marker_coverage | PASS | All verified FACT/CALC claims are marked |
| article_hypothesis_marker_coverage | PASS | All hypothesis records are linked from the article |
| article_no_unknown_markers | PASS | No unknown claim markers |
| article_display_value_claim_match | PASS | All displayed numeric claims exactly match claims.csv |
| article_no_unclaimed_numbers | PASS | No unclaimed numeric-with-unit strings |
| article_numeric_claim_pairs_exact | PASS | Every statistical number is directly followed by its matching claim ID |
| article_no_unclassified_arabic_numbers | PASS | All Arabic numerals are claim-backed statistics or whitelisted provenance/layout metadata |
| article_claim_type_badges_match | PASS | Every narrative claim marker inherits the matching FACT/CALC/HYPOTHESIS badge |
| article_interpretation_policy | PASS | Article interpretation policy satisfied |
| article_fact_summary_200_characters | PASS | visible fact-summary length=200 characters |
| required_output_artifacts | PASS | All required artifacts generated |

## データ品質ログ

欠損・表章変更・業種分類変更は0へ補完せず、以下に保持する。

- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: PROFIT_TO_LOSS
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT
- [INFO] PROFIT_LOSS_TRANSITION: LOSS_TO_PROFIT

## 判定規則

- 数値正本はe-Stat構造化表。PDFは定義・注記・公表ランキングの照合に限る。
- 金融・保険業を除く表1と、金融・保険業を含む表2は別系列として扱う。
- 季節調整済前期比は表4と財務省公表Excelの一致を確認する。業種別・資本金規模別の季調前期比は作成しない。
- 記事本文・表の統計値はclaims.csvと直結照合し、図の描画入力はCHART_INPUT claimと照合する。公開日、表番号、軸目盛などの来歴・レイアウト数値は統計claimと分離する。
- FAILが一つでもあれば、記事は完成扱いにしない。
