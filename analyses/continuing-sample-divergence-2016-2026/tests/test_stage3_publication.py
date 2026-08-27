from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd

from corporate_quarterly.stage2_continuing_sample import ContinuingSampleAnalysis
from corporate_quarterly.stage2_phase3_non_operating import Phase3NonOperatingAnalysis
from corporate_quarterly.stage3_charts import (
    PUBLIC_SAMPLE_CHART_FILENAMES,
    STAGE3_CHART_FILENAMES,
    build_stage3_charts,
)
from corporate_quarterly.stage3_publication import (
    ARCHIVE_NO_ROBUST_STORY,
    CLAIM_CANDIDATE_REGISTRY_V3,
    EXACT_FACT_SUMMARY_200,
    NONOPERATING_CANDIDATE_ID,
    PUBLISH_FULL_NONOPERATING_BRIDGE_SNAPSHOT,
    PUBLISH_SAMPLE_CONSTRUCTION_SENSITIVITY,
    SAMPLE_CANDIDATE_ID,
    _extract_summary,
    _strip_html_comments,
    build_claims_v3,
    render_sample_sensitivity_article,
    select_stage3_publication_decision,
    validate_claims_v3,
    validate_stage3_article,
)


def _continuing_analysis() -> ContinuingSampleAnalysis:
    relative = pd.DataFrame(
        [
            {
                "period_code": "20261",
                "breakdown": "capital_size",
                "category_code": code,
                "regular_sales_yoy_pct": regular_sales,
                "regular_operating_profit_yoy_pct": regular_operating,
                "regular_relative_margin_change_direction": regular_direction,
                "continuing_sales_yoy_pct": continuing_sales,
                "continuing_operating_profit_yoy_pct": continuing_operating,
                "continuing_relative_margin_change_direction": continuing_direction,
                "continuing_relative_margin_status": "PROXY_PROFIT_BASE_SIGN_NOT_PUBLISHED",
            }
            for (
                code,
                regular_sales,
                regular_operating,
                regular_direction,
                continuing_sales,
                continuing_operating,
                continuing_direction,
            ) in (
                ("19", 2.100851, -1.890184, "DOWN", 2.5, 6.0, "UP"),
                ("24", -1.465080, 16.976869, "UP", 2.0, 22.4, "UP"),
                ("25", 1.695835, 18.494685, "UP", 2.6, 20.0, "UP"),
            )
        ]
    )
    headline_history = pd.DataFrame(
        [
            {
                "period_code": "20261",
                "regular_headline_supported": True,
                "continuing_headline_supported": False,
                "headline_reversal": True,
                "headline_definition": (
                    "small sales yoy > 0 AND small relative operating-margin "
                    "direction DOWN AND large relative operating-margin direction UP"
                ),
            }
        ]
    )
    headline_frequency = pd.DataFrame(
        [
            {
                "headline_id": "CAPITAL_MARGIN_DIVERGENCE_B",
                "total_quarters": 41,
                "comparable_headline_quarters": 41,
                "headline_reversal_count": 11,
                "headline_reversal_rate_pct": 11 / 41 * 100,
            }
        ]
    )
    margin_frequency = pd.DataFrame(
        [
            {
                "breakdown": "capital_size",
                "category_code": "19",
                "category_id": "capital_19",
                "category_label_ja": "中小企業",
                "total_quarters": 41,
                "comparable_direction_quarters": 41,
                "direction_reversal_count": 16,
                "direction_reversal_rate_pct": 16 / 41 * 100,
            }
        ]
    )
    empty = pd.DataFrame()
    return ContinuingSampleAnalysis(
        continuing_yoy=empty,
        regular_yoy=empty,
        comparison=empty,
        relative_margin_comparison=relative,
        sign_reversal_frequency=empty,
        relative_margin_reversal_frequency=margin_frequency,
        capital_headline_history=headline_history,
        headline_reversal_frequency=headline_frequency,
        response_counts=empty,
        standard_error_rates=empty,
        limitations={
            "small_sample": "continuing sample is smaller",
            "profit_standard_error": "not calculated",
        },
    )


def _nonoperating_analysis() -> Phase3NonOperatingAnalysis:
    components = (
        (1, "interest_and_dividend_income", "受取利息等", 1, 152.04, 152.04),
        (2, "other_non_operating_income", "その他の営業外収益", 1, 15424.31, 15424.31),
        (3, "interest_expense", "支払利息等", -1, 6759.86, -6759.86),
        (4, "other_non_operating_expense", "その他の営業外費用", -1, -6790.13, 6790.13),
    )
    current = pd.DataFrame(
        [
            {
                "period_code": "20261",
                "industry_code": "104",
                "capital_size_code": "26",
                "component_order": order,
                "component_id": component_id,
                "component_label_ja": label,
                "accounting_sign": sign,
                "source_yoy_delta_oku_yen": source_delta,
                "profit_impact_yoy_oku_yen": impact,
                "calculation_status": "CALCULABLE",
            }
            for order, component_id, label, sign, source_delta, impact in components
        ]
    )
    decomposition = pd.DataFrame(
        [
            {
                "period_code": "20261",
                "industry_code": "104",
                "capital_size_code": "26",
                "anchor_gap_yoy_delta_oku_yen": 15606.62,
            }
        ]
    )
    identity = pd.DataFrame(
        [{"period_code": "20261", "status": "PASS"}]
    )
    empty = pd.DataFrame()
    return Phase3NonOperatingAnalysis(
        raw_long=empty,
        earliest_complete_period=empty,
        decomposition=decomposition,
        current_breakdown=current,
        historical_statistics=empty,
        concentration=empty,
        identity_checks=identity,
        additivity_checks=empty,
    )


def test_claims_v3_has_complete_explicit_mapping_and_all_chart_inputs() -> None:
    claims = build_claims_v3(
        continuing=_continuing_analysis(), nonoperating=_nonoperating_analysis()
    )
    assert len(claims) == len(CLAIM_CANDIDATE_REGISTRY_V3) == 28
    assert not validate_claims_v3(claims)
    assert claims.set_index("claim_id")["candidate_id"].to_dict() == (
        CLAIM_CANDIDATE_REGISTRY_V3
    )
    assert set(
        chart
        for value in claims["chart_ids"]
        for chart in value.split(";")
        if chart
    ) == set(STAGE3_CHART_FILENAMES)

    frequency = claims.set_index("claim_id")
    headline = frequency.loc["V3-HEADLINE-REVERSAL-FREQUENCY"]
    margin = frequency.loc["V3-SMALL-MARGIN-REVERSAL-FREQUENCY"]
    assert (headline["numerator"], headline["denominator"]) == (11, 41)
    assert headline["numeric_value"] == 11 / 41 * 100
    assert headline["display_value"] == "11/41四半期（26.83％）"
    assert (margin["numerator"], margin["denominator"]) == (16, 41)
    assert margin["numeric_value"] == 16 / 41 * 100
    assert margin["display_value"] == "16/41四半期（39.02％）"

    nonop = claims.loc[claims["candidate_id"].eq(NONOPERATING_CANDIDATE_ID)]
    assert len(nonop) == 5
    assert not nonop["article_use"].any()
    assert frequency.loc["V3-NONOP-NET-GAP", "numeric_value"] == 15606.62
    assert frequency.loc[
        "V3-NONOP-INTEREST-EXPENSE", "source_yoy_delta_oku_yen"
    ] == 6759.86
    assert frequency.loc[
        "V3-NONOP-INTEREST-EXPENSE", "numeric_value"
    ] == -6759.86


def test_explicit_mapping_validator_does_not_infer_owner_from_claim_text() -> None:
    claims = build_claims_v3(
        continuing=_continuing_analysis(), nonoperating=_nonoperating_analysis()
    )
    claims.loc[
        claims["claim_id"].eq("V3-NONOP-NET-GAP"), "candidate_id"
    ] = SAMPLE_CANDIDATE_ID
    assert "EXPLICIT_CANDIDATE_MAPPING_MISMATCH" in validate_claims_v3(claims)


def test_article_has_exact_visible_summary_one_claim_and_two_public_figures() -> None:
    continuing = _continuing_analysis()
    claims = build_claims_v3(
        continuing=continuing, nonoperating=_nonoperating_analysis()
    )
    article = render_sample_sensitivity_article(
        continuing=continuing,
        claims_v3=claims,
        chart_paths=[f"charts/{name}" for name in PUBLIC_SAMPLE_CHART_FILENAMES],
    )
    summary = _extract_summary(article)
    assert summary is not None
    assert _strip_html_comments(summary) == EXACT_FACT_SUMMARY_200
    assert len(_strip_html_comments(summary)) == 200
    assert article.count("<!-- central-claim:") == 1
    assert article.count("![") == 2
    assert STAGE3_CHART_FILENAMES[2] not in article
    assert "営業外損益" not in article
    assert validate_stage3_article(article, claims).status == "PASS"


def test_article_validator_fails_unlinked_value_and_candidate_mixing() -> None:
    continuing = _continuing_analysis()
    claims = build_claims_v3(
        continuing=continuing, nonoperating=_nonoperating_analysis()
    )
    article = render_sample_sensitivity_article(
        continuing=continuing,
        claims_v3=claims,
        chart_paths=[f"charts/{name}" for name in PUBLIC_SAMPLE_CHART_FILENAMES],
    )
    unlinked = article.replace(
        "原因の推定ではなく",
        "9.9兆円であり、原因の推定ではなく",
        1,
    )
    audit = validate_stage3_article(unlinked, claims)
    assert audit.status == "FAIL"
    assert "all_statistical_numbers_linked" in audit.failed_check_ids

    mixed = article.replace(
        PUBLIC_SAMPLE_CHART_FILENAMES[1], STAGE3_CHART_FILENAMES[2], 1
    )
    audit = validate_stage3_article(mixed, claims)
    assert audit.status == "FAIL"
    assert "principal_figure_limit_and_set" in audit.failed_check_ids
    assert "no_nonoperating_candidate_mixing" in audit.failed_check_ids


def test_decision_prioritises_current_sample_reversal_then_complete_bridge() -> None:
    continuing = _continuing_analysis()
    nonoperating = _nonoperating_analysis()
    assert select_stage3_publication_decision(
        continuing=continuing, nonoperating=nonoperating
    ) == PUBLISH_SAMPLE_CONSTRUCTION_SENSITIVITY

    no_reversal_relative = continuing.relative_margin_comparison.copy()
    no_reversal_relative.loc[
        no_reversal_relative["category_code"].eq("19"),
        "continuing_relative_margin_change_direction",
    ] = "DOWN"
    no_reversal_headline = continuing.capital_headline_history.copy()
    no_reversal_headline.loc[:, "headline_reversal"] = False
    no_reversal = replace(
        continuing,
        relative_margin_comparison=no_reversal_relative,
        capital_headline_history=no_reversal_headline,
    )
    assert select_stage3_publication_decision(
        continuing=no_reversal, nonoperating=nonoperating
    ) == PUBLISH_FULL_NONOPERATING_BRIDGE_SNAPSHOT

    failed_identity = replace(
        nonoperating,
        identity_checks=pd.DataFrame([{"period_code": "20261", "status": "FAIL"}]),
    )
    assert select_stage3_publication_decision(
        continuing=no_reversal, nonoperating=failed_identity
    ) == ARCHIVE_NO_ROBUST_STORY


def test_stage3_chart_builder_writes_exactly_three_registered_pngs(
    tmp_path: Path,
) -> None:
    charts = build_stage3_charts(
        continuing=_continuing_analysis(),
        nonoperating=_nonoperating_analysis(),
        output_dir=tmp_path,
    )
    assert tuple(charts) == STAGE3_CHART_FILENAMES
    assert {path.name for path in tmp_path.iterdir()} == set(STAGE3_CHART_FILENAMES)
    for path in charts.values():
        assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert path.stat().st_size > 10_000

