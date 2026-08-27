from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from corporate_quarterly.estat import sha256_file
from corporate_quarterly.stage2_phase3_non_operating import (
    ALL_CAPITAL_CODE,
    ALL_INDUSTRY_CODE,
    COMPONENT_IDS,
    PHASE3_RAW_ROOT,
    REQUIRED_METRIC_IDS,
    TARGET_PERIOD_CODE,
    Phase3NonOperatingAnalysis,
    build_current_breakdown,
    build_historical_statistics,
    build_identity_checks,
    build_non_operating_decomposition,
    build_phase3_non_operating_analysis,
    mechanical_earliest_complete_period,
    parse_phase3_non_operating_raw,
)


@pytest.fixture(scope="module")
def phase3_raw() -> pd.DataFrame:
    return parse_phase3_non_operating_raw(dataset="combined")


@pytest.fixture(scope="module")
def phase3_analysis(phase3_raw: pd.DataFrame) -> Phase3NonOperatingAnalysis:
    return build_phase3_non_operating_analysis(phase3_raw)


def _current_total(frame: pd.DataFrame) -> pd.Series:
    selected = frame.loc[
        frame["period_code"].eq(TARGET_PERIOD_CODE)
        & frame["industry_code"].eq(ALL_INDUSTRY_CODE)
        & frame["capital_size_code"].eq(ALL_CAPITAL_CODE)
    ]
    assert len(selected) == 1
    return selected.iloc[0]


def test_phase3_raw_manifest_is_frozen_and_complete() -> None:
    manifest_path = PHASE3_RAW_ROOT / "data_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["vintage_id"] == "non_operating_2026Q1"
    assert manifest["publication_date"] == "2026-06-01"
    assert manifest["table_number"] == "1"
    assert manifest["estat_sid"] == "0003060191"
    assert manifest["requested_period_start"] == "20092"
    assert manifest["requested_period_end"] == "20261"
    assert {metric["code"] for metric in manifest["required_metrics"]} == {
        "081",
        "082",
        "083",
        "084",
        "085",
        "086",
    }
    assert len(manifest["sources"]) == 13
    history_values = [
        source
        for source in manifest["sources"]
        if source["role"] == "numeric_authority_history_chunk"
    ]
    assert len(history_values) == 5
    assert sum(len(source["period_codes"]) for source in history_values) == 68
    assert len(
        [
            source
            for source in manifest["sources"]
            if source["role"] == "numeric_authority_current"
        ]
    ) == 1
    for source in manifest["sources"]:
        path = Path(source["raw_path"])
        if not path.is_absolute():
            path = PHASE3_RAW_ROOT.parents[2] / path
        assert path.exists()
        assert sha256_file(path) == source["sha256"]
        assert source["retrieved_at"]
        assert source["url"].startswith("https://www.e-stat.go.jp/")


def test_parser_verifies_current_snapshot_and_preserves_source_units(
    phase3_raw: pd.DataFrame,
) -> None:
    assert set(phase3_raw["metric_id"]) == set(REQUIRED_METRIC_IDS)
    assert phase3_raw["source_unit"].eq("百万円").all()
    assert phase3_raw["coverage_scope"].eq("EXCL_FINANCE_INSURANCE").all()
    assert phase3_raw["seasonal_adjustment"].eq("RAW").all()
    assert phase3_raw.loc[
        phase3_raw["period_code"].eq(TARGET_PERIOD_CODE),
        "current_snapshot_verified",
    ].all()
    assert not phase3_raw.loc[
        phase3_raw["period_code"].ne(TARGET_PERIOD_CODE),
        "current_snapshot_verified",
    ].any()


def test_mechanical_earliest_period_and_absent_rows_are_explicit(
    phase3_raw: pd.DataFrame,
    phase3_analysis: Phase3NonOperatingAnalysis,
) -> None:
    audit = mechanical_earliest_complete_period(phase3_raw)
    assert len(audit) == 68
    earliest = audit.loc[audit["is_mechanical_earliest"]]
    assert earliest["period_code"].tolist() == ["20092"]
    assert earliest["status"].eq("COMPLETE").all()
    # e-Stat omits a full six-metric row for this sparse historical cell.  It is
    # retained as null by the decomposition, never inferred to be zero.
    assert (
        audit.loc[audit["period_code"].eq("20162"), "missing_cells"].iloc[0]
        == len(REQUIRED_METRIC_IDS)
    )
    missing = phase3_analysis.decomposition.loc[
        phase3_analysis.decomposition["period_code"].eq("20162")
        & phase3_analysis.decomposition["industry_code"].eq("103")
        & phase3_analysis.decomposition["capital_size_code"].eq("25")
    ].iloc[0]
    assert missing["interest_expense_source_status"] == "ABSENT_SOURCE_ROW"
    assert pd.isna(missing["interest_expense_oku_yen"])
    assert missing["identity_status"] == "MISSING_INPUT"


def test_2026q1_four_component_identity_reproduces_exact_and_rounded_values(
    phase3_analysis: Phase3NonOperatingAnalysis,
) -> None:
    row = _current_total(phase3_analysis.decomposition)

    assert row["interest_and_dividend_income_yoy_delta_oku_yen"] == pytest.approx(
        152.04
    )
    assert row["other_non_operating_income_yoy_delta_oku_yen"] == pytest.approx(
        15_424.31
    )
    assert row["interest_expense_yoy_delta_oku_yen"] == pytest.approx(6_759.86)
    assert row["other_non_operating_expense_yoy_delta_oku_yen"] == pytest.approx(
        -6_790.13
    )
    assert row["interest_expense_profit_impact_yoy_oku_yen"] == pytest.approx(
        -6_759.86
    )
    assert row[
        "other_non_operating_expense_profit_impact_yoy_oku_yen"
    ] == pytest.approx(6_790.13)
    assert row["anchor_gap_yoy_delta_oku_yen"] == pytest.approx(15_606.62)
    assert row["profit_impact_sum_yoy_oku_yen"] == pytest.approx(15_606.62)
    assert row["yoy_identity_residual_oku_yen"] == pytest.approx(0.0, abs=1e-10)

    rounded_impacts = [
        round(row[f"{component}_profit_impact_yoy_oku_yen"])
        for component in COMPONENT_IDS
    ]
    assert rounded_impacts == [152, 15_424, -6_760, 6_790]
    # Component-wise whole-oku rounding reproduces the requested display bridge.
    assert sum(rounded_impacts) == 15_606


def test_expense_changes_use_signed_profit_impact_not_directional_claims(
    phase3_analysis: Phase3NonOperatingAnalysis,
) -> None:
    current = phase3_analysis.current_breakdown
    total = current.loc[
        current["industry_code"].eq(ALL_INDUSTRY_CODE)
        & current["capital_size_code"].eq(ALL_CAPITAL_CODE)
    ].set_index("component_id")

    assert total.loc["interest_expense", "source_yoy_delta_oku_yen"] > 0
    assert total.loc["interest_expense", "profit_impact_yoy_oku_yen"] < 0
    assert total.loc["interest_expense", "profit_impact_sign"] == (
        "REDUCES_PROFIT_CHANGE"
    )
    assert total.loc[
        "other_non_operating_expense", "source_yoy_delta_oku_yen"
    ] < 0
    assert total.loc[
        "other_non_operating_expense", "profit_impact_yoy_oku_yen"
    ] > 0
    text = " ".join(
        current["profit_impact_label_ja"].astype(str)
        .tolist()
        + current["interpretation_guardrail"].astype(str).tolist()
    )
    prohibited_directional_label = "支払利息" + "減少" + "寄与"
    assert prohibited_directional_label not in text
    other_income = total.loc["other_non_operating_income"]
    assert other_income["interpretation_guardrail"] == "原因は統計だけでは特定しない"


def test_identity_and_additivity_cover_current_major_leaf_and_cross_cells(
    phase3_analysis: Phase3NonOperatingAnalysis,
) -> None:
    identity = phase3_analysis.identity_checks
    assert "FAIL" not in set(identity["status"])
    current_identity = identity.loc[identity["period_code"].eq(TARGET_PERIOD_CODE)]
    assert len(current_identity) == 52 * 4 * 2
    assert current_identity["status"].eq("PASS").all()
    assert set(current_identity["basis"]) == {"LEVEL", "YOY_DELTA"}

    additivity = phase3_analysis.additivity_checks
    assert "FAIL" not in set(additivity["status"])
    current_additivity = additivity.loc[
        additivity["period_code"].eq(TARGET_PERIOD_CODE)
    ]
    assert current_additivity["status"].eq("PASS").all()
    assert {"major", "leaf"} == set(current_additivity["taxonomy"])
    assert {
        "CAPITAL_COMPONENTS_TO_ALL",
        "INDUSTRIES_TO_ALL",
        "LEAF_TO_PARENT",
        "CROSS_GRAND_TOTAL",
    } <= set(current_additivity["check_type"])
    assert current_additivity["difference_oku_yen"].abs().max() <= 0.01


def test_missing_component_propagates_without_zero_fill(
    phase3_raw: pd.DataFrame,
) -> None:
    subset = phase3_raw.loc[
        phase3_raw["period_code"].isin({"20251", "20261"})
    ].copy()
    target = (
        subset["period_code"].eq("20261")
        & subset["industry_code"].eq("104")
        & subset["capital_size_code"].eq("26")
        & subset["metric_id"].eq("other_non_operating_income")
    )
    assert target.sum() == 1
    subset.loc[target, "value_oku_yen"] = None
    subset.loc[target, "source_value_million_yen"] = None
    subset.loc[target, "value_status"] = "SOURCE_MISSING_MARKER"
    decomposition = build_non_operating_decomposition(subset)
    row = _current_total(decomposition)

    assert pd.isna(row["other_non_operating_income_oku_yen"])
    assert pd.isna(row["component_gap_oku_yen"])
    assert pd.isna(row["profit_impact_sum_yoy_oku_yen"])
    assert row["identity_status"] == "MISSING_INPUT"
    checks = build_identity_checks(decomposition)
    target_checks = checks.loc[
        checks["period_code"].eq("20261")
        & checks["industry_code"].eq("104")
        & checks["capital_size_code"].eq("26")
    ]
    assert target_checks["status"].eq("MISSING_INPUT").all()


def test_four_quarter_totals_and_inclusive_historical_percentile(
    phase3_analysis: Phase3NonOperatingAnalysis,
) -> None:
    history = phase3_analysis.historical_statistics
    group = history.loc[
        history["industry_code"].eq(ALL_INDUSTRY_CODE)
        & history["capital_size_code"].eq(ALL_CAPITAL_CODE)
        & history["component_id"].eq("other_non_operating_income")
    ].sort_values("period_ordinal")
    current = group.loc[group["period_code"].eq(TARGET_PERIOD_CODE)].iloc[0]

    assert current["source_value_trailing4q_oku_yen"] == pytest.approx(
        group.tail(4)["source_value_oku_yen"].sum()
    )
    nonmissing = group["profit_impact_yoy_oku_yen"].dropna()
    inclusive = (nonmissing <= current["profit_impact_yoy_oku_yen"]).sum()
    expected_percentile = inclusive / len(nonmissing) * 100.0
    assert current["profit_impact_percentile_inclusive_pct"] == pytest.approx(
        expected_percentile
    )
    assert current["profit_impact_percentile_method"] == (
        "INCLUSIVE_EMPIRICAL_CDF:100*count(values<=current)/count(nonmissing)"
    )
    assert pd.notna(current["profit_impact_rank_desc"])
    assert pd.notna(current["profit_impact_abs_rank_desc"])


def test_item_capital_and_separate_taxonomy_concentrations_are_available(
    phase3_analysis: Phase3NonOperatingAnalysis,
) -> None:
    concentration = phase3_analysis.concentration
    assert set(concentration["concentration_dimension"]) == {
        "ITEM",
        "CAPITAL",
        "INDUSTRY",
    }
    assert {"major", "leaf"} <= set(concentration["taxonomy"])
    assert not concentration.loc[
        concentration["concentration_dimension"].isin({"CAPITAL", "INDUSTRY"})
        & concentration["component_id"].eq("ALL_COMPONENTS")
    ].empty
    item = concentration.loc[concentration["concentration_dimension"].eq("ITEM")]
    assert len(item) == 4
    assert item["profit_impact_yoy_oku_yen"].sum() == pytest.approx(15_606.62)
    assert item["positive_share_pct"].sum() == pytest.approx(100.0)
    for column in (
        "top1_positive_concentration_pct",
        "top3_positive_concentration_pct",
        "top5_positive_concentration_pct",
    ):
        assert item[column].notna().all()


def test_phase3_result_exposes_documented_dataframes(
    phase3_analysis: Phase3NonOperatingAnalysis,
) -> None:
    assert isinstance(phase3_analysis, Phase3NonOperatingAnalysis)
    assert {
        "anchor_gap_oku_yen",
        "component_gap_oku_yen",
        "anchor_gap_yoy_delta_oku_yen",
        "profit_impact_sum_yoy_oku_yen",
        "identity_status",
        "yoy_identity_status",
    } <= set(phase3_analysis.decomposition.columns)
    assert {
        "component_id",
        "source_yoy_delta_oku_yen",
        "profit_impact_yoy_oku_yen",
        "profit_impact_sign",
        "interpretation_guardrail",
    } <= set(phase3_analysis.current_breakdown.columns)
    assert {
        "profit_impact_yoy_trailing4q_oku_yen",
        "profit_impact_rank_desc",
        "profit_impact_percentile_inclusive_pct",
        "profit_impact_percentile_method",
    } <= set(phase3_analysis.historical_statistics.columns)
