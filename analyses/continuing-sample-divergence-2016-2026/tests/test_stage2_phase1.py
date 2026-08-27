from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from corporate_quarterly.constants import load_release
from corporate_quarterly.processing import build_processed
from corporate_quarterly.stage2_phase1 import (
    ALL_CAPITAL_CODE,
    CAPITAL_CODES,
    Phase0ReproductionError,
    build_capital_margin_bridge,
    build_cell_margin_bridge,
    build_industry_x_capital,
    build_net_non_operating_gap,
    build_phase1_analysis,
    build_software_capex_decomposition,
    load_stage2_config,
    render_phase0_failure,
    reproduce_phase0,
    require_phase0_pass,
    taxonomy_definition,
    validate_cross_additivity,
    validate_decomposition_additivity,
    validate_taxonomy_additivity,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def stage2_processed() -> pd.DataFrame:
    frozen = PROJECT_ROOT / "outputs" / "2026Q1" / "processed_quarterly.parquet"
    if frozen.exists():
        return pd.read_parquet(frozen)
    processed, issues = build_processed(PROJECT_ROOT, load_release("2026Q1"))
    assert not [issue for issue in issues if issue.get("severity") == "FAIL"]
    return processed


def _source_index(
    processed: pd.DataFrame, industry: str, capital: str, metric: str
) -> int:
    mask = (
        processed["coverage_scope"].eq("EXCL_FINANCE_INSURANCE")
        & processed["source_table_number"].astype(str).eq("1")
        & processed["industry_code"].astype(str).eq(industry)
        & processed["capital_size_code"].astype(str).eq(capital)
        & processed["metric_id"].eq(metric)
    )
    index = processed.index[mask]
    assert len(index) == 1
    return int(index[0])


def test_phase0_reproduces_every_frozen_target(stage2_processed: pd.DataFrame) -> None:
    checks = reproduce_phase0(stage2_processed)

    assert len(checks) == 32
    assert checks["status"].eq("PASS").all()
    actual = checks.set_index("check_id")["actual"]
    assert actual["all_gap_yoy_delta"] == pytest.approx(15_606.62)
    assert actual["large_manufacturing_ordinary_contribution_pct"] == pytest.approx(
        72.0597293639
    )
    assert actual["ict_machinery_ordinary_contribution_pct"] == pytest.approx(
        38.1297101008
    )
    assert actual["capital_19_operating_margin_delta_pp"] == pytest.approx(
        -0.2275178183
    )
    assert actual["software_capital_19_contribution_pct"] == pytest.approx(
        73.3772857014
    )
    units = checks.set_index("check_id")["unit"]
    assert units["capital_19_sales_yoy_pct"] == "%"
    assert units["capital_25_operating_yoy_pct"] == "%"
    assert units["software_capital_19_contribution_pct"] == "%"
    assert units["capital_19_operating_margin_delta_pp"] == "ポイント"
    assert units["capital_25_operating_margin_delta_pp"] == "ポイント"


def test_phase0_fails_closed_and_identifies_target_cell(
    stage2_processed: pd.DataFrame,
) -> None:
    changed = stage2_processed.copy(deep=True)
    index = _source_index(changed, "104", "26", "operating_profit")
    changed.at[index, "raw_value_oku_yen"] += 1.0
    checks = reproduce_phase0(changed)

    assert not checks["status"].eq("PASS").all()
    with pytest.raises(Phase0ReproductionError):
        require_phase0_pass(checks)
    with pytest.raises(Phase0ReproductionError):
        build_phase1_analysis(changed)
    failure = render_phase0_failure(checks)
    assert "PHASE 0 FAIL" in failure
    assert "industry=104;capital=26;metric=operating_profit" in failure


def test_taxonomies_are_closed_mutually_exclusive_and_additive(
    stage2_processed: pd.DataFrame,
) -> None:
    config = load_stage2_config()
    major = taxonomy_definition("major", config=config)
    leaf = taxonomy_definition("leaf", config=config)
    excluded = set(config["taxonomy_policy"]["excluded_overlapping_or_legacy_codes"])

    assert len(major) == 11
    assert len(leaf) == 45
    assert major["industry_code"].is_unique
    assert leaf["industry_code"].is_unique
    assert not (set(leaf["industry_code"]) & excluded)
    assert not leaf["industry_name"].str.contains("H20年度まで", regex=False).any()
    assert leaf["is_mutually_exclusive"].all()

    for taxonomy in ("major", "leaf"):
        checks = validate_taxonomy_additivity(stage2_processed, taxonomy)
        assert not checks.empty
        assert checks["status"].eq("PASS").all()
        assert checks["difference_oku_yen"].abs().max() <= 0.01


@pytest.mark.parametrize(
    ("taxonomy", "expected_rows"), [("major", 33), ("leaf", 135)]
)
def test_industry_capital_cross_reconciles_rows_columns_and_grand_total(
    stage2_processed: pd.DataFrame, taxonomy: str, expected_rows: int
) -> None:
    cross = build_industry_x_capital(stage2_processed, taxonomy)  # type: ignore[arg-type]
    assert len(cross) == expected_rows
    assert set(cross["capital_size_code"]) == set(CAPITAL_CODES)
    checks = validate_cross_additivity(
        stage2_processed, cross, taxonomy  # type: ignore[arg-type]
    )

    assert checks["status"].eq("PASS").all()
    assert {
        "CAPITAL_COLUMNS_TO_INDUSTRY",
        "INDUSTRY_ROWS_TO_CAPITAL",
        "CROSS_TO_ALL_INDUSTRY_ALL_CAPITAL",
    } <= set(checks["scope"])


def test_cell_and_capital_shapley_bridges_are_exact_and_order_independent(
    stage2_processed: pd.DataFrame,
) -> None:
    cross = build_industry_x_capital(stage2_processed, "leaf")
    cells = build_cell_margin_bridge(cross)
    capital = build_capital_margin_bridge(cross)

    assert cells["bridge_status"].eq("CALCULABLE").all()
    three_term = (
        cells["sales_change_identity_effect_oku_yen"]
        + cells["margin_change_identity_effect_oku_yen"]
        + cells["interaction_identity_effect_oku_yen"]
    )
    two_factor = (
        cells["shapley_sales_effect_oku_yen"]
        + cells["shapley_margin_effect_oku_yen"]
    )
    assert (
        three_term - cells["operating_profit_yoy_delta_oku_yen"]
    ).abs().max() < 1e-8
    assert (
        two_factor - cells["operating_profit_yoy_delta_oku_yen"]
    ).abs().max() < 1e-8
    assert cells["bridge_residual_oku_yen"].abs().max() < 1e-8

    assert capital["bridge_status"].eq("CALCULABLE").all()
    reconstructed = (
        capital["aggregate_sales_scale_effect_oku_yen"]
        + capital["industry_composition_effect_oku_yen"]
        + capital["within_industry_margin_effect_oku_yen"]
    )
    assert (
        reconstructed - capital["operating_profit_yoy_delta_oku_yen"]
    ).abs().max() < 1e-8
    assert capital["bridge_residual_oku_yen"].abs().max() < 1e-8
    assert capital["shapley_order_count"].eq(6).all()

    large = capital.loc[capital["capital_size_code"].eq("25")].iloc[0]
    assert large["aggregate_sales_scale_effect_oku_yen"] == pytest.approx(
        1_952.611090, abs=1e-6
    )
    assert large["industry_composition_effect_oku_yen"] == pytest.approx(
        3_557.892939, abs=1e-6
    )
    assert large["within_industry_margin_effect_oku_yen"] == pytest.approx(
        14_204.905971, abs=1e-6
    )


def test_net_non_operating_gap_uses_guarded_ratio_states(
    stage2_processed: pd.DataFrame,
) -> None:
    gap = build_net_non_operating_gap(stage2_processed, "leaf")
    all_row = gap.loc[gap["aggregation_level"].eq("ALL")].iloc[0]
    assert all_row["net_non_operating_gap_yoy_delta_oku_yen"] == pytest.approx(
        15_606.62
    )
    assert all_row["gap_delta_share_of_ordinary_delta_pct"] == pytest.approx(
        37.5367842745
    )
    assert all_row["gap_share_status"] == "CALCULABLE"
    additivity = validate_decomposition_additivity(gap, "net_non_operating_gap")
    assert additivity["status"].eq("PASS").all()

    negative_prior = stage2_processed.copy(deep=True)
    index = _source_index(negative_prior, "145", "19", "ordinary_profit")
    negative_prior.at[index, "raw_lag4_value_oku_yen"] = -1.0
    guarded = build_net_non_operating_gap(negative_prior, "leaf")
    target = guarded.loc[
        guarded["aggregation_level"].eq("INDUSTRY_X_CAPITAL")
        & guarded["industry_code"].eq("145")
        & guarded["capital_size_code"].eq("19")
    ].iloc[0]
    assert pd.isna(target["gap_delta_share_of_ordinary_delta_pct"])
    assert target["gap_share_status"] == "NEGATIVE_PRIOR_ORDINARY_PROFIT"

    sign_change = stage2_processed.copy(deep=True)
    index = _source_index(sign_change, "145", "19", "ordinary_profit")
    assert sign_change.at[index, "raw_lag4_value_oku_yen"] > 0
    sign_change.at[index, "raw_value_oku_yen"] = -1.0
    guarded = build_net_non_operating_gap(sign_change, "leaf")
    target = guarded.loc[
        guarded["aggregation_level"].eq("INDUSTRY_X_CAPITAL")
        & guarded["industry_code"].eq("145")
        & guarded["capital_size_code"].eq("19")
    ].iloc[0]
    assert pd.isna(target["gap_delta_share_of_ordinary_delta_pct"])
    assert target["gap_share_status"] == "ORDINARY_PROFIT_SIGN_TRANSITION"
    assert target["ordinary_profit_transition_yoy"] == "PROFIT_TO_LOSS"


def test_software_capex_is_derived_reconciled_and_base_diagnosed(
    stage2_processed: pd.DataFrame,
) -> None:
    software = build_software_capex_decomposition(stage2_processed, "leaf")
    assert not software["is_direct_published_series"].any()
    all_row = software.loc[software["aggregation_level"].eq("ALL")].iloc[0]
    small = software.loc[
        software["aggregation_level"].eq("CAPITAL")
        & software["capital_size_code"].eq("19")
    ].iloc[0]
    assert all_row["software_capex_yoy_delta_oku_yen"] == pytest.approx(2_431.42)
    assert small["software_capex_yoy_delta_oku_yen"] == pytest.approx(1_784.11)
    assert small["software_capex_yoy_pct"] == pytest.approx(84.417747)
    assert small["software_contribution_pct_to_all_net_change"] == pytest.approx(
        73.3772857
    )
    assert small["prior_base_status"] == "POSITIVE_BASE"
    checks = validate_decomposition_additivity(software, "software_capex")
    assert checks["status"].eq("PASS").all()


def test_missing_values_are_not_zero_filled_and_break_additivity(
    stage2_processed: pd.DataFrame,
) -> None:
    changed = stage2_processed.copy(deep=True)
    index = _source_index(changed, "145", "19", "ordinary_profit")
    changed.at[index, "raw_value_oku_yen"] = None
    cross = build_industry_x_capital(changed, "leaf")
    target = cross.loc[
        cross["industry_code"].eq("145")
        & cross["capital_size_code"].eq("19")
    ].iloc[0]
    assert pd.isna(target["ordinary_profit_current_oku_yen"])
    assert target["ordinary_profit_yoy_status"] == "MISSING_INPUT"
    checks = validate_cross_additivity(changed, cross, "leaf")
    assert "MISSING_INPUT" in set(checks["status"])

    capex_missing = stage2_processed.copy(deep=True)
    index = _source_index(capex_missing, "145", "19", "capex_excluding_software")
    capex_missing.at[index, "raw_value_oku_yen"] = None
    software = build_software_capex_decomposition(capex_missing, "leaf")
    target = software.loc[
        software["aggregation_level"].eq("INDUSTRY_X_CAPITAL")
        & software["industry_code"].eq("145")
        & software["capital_size_code"].eq("19")
    ].iloc[0]
    assert pd.isna(target["software_capex_current_oku_yen"])
    assert pd.isna(target["software_capex_yoy_delta_oku_yen"])
    assert target["software_capex_yoy_status"] == "MISSING_INPUT"
    checks = validate_decomposition_additivity(software, "software_capex")
    assert "MISSING_INPUT" in set(checks["status"])


def test_zero_sales_base_keeps_null_rate_and_bridge_status(
    stage2_processed: pd.DataFrame,
) -> None:
    changed = stage2_processed.copy(deep=True)
    index = _source_index(changed, "145", "19", "sales")
    changed.at[index, "raw_lag4_value_oku_yen"] = 0.0
    cross = build_industry_x_capital(changed, "leaf")
    target = cross.loc[
        cross["industry_code"].eq("145")
        & cross["capital_size_code"].eq("19")
    ].iloc[0]
    assert pd.isna(target["sales_yoy_pct"])
    assert target["sales_yoy_status"] == "ZERO_BASE_NOT_CALCULABLE"
    assert pd.isna(target["operating_margin_previous_pct"])
    assert target["operating_margin_status"] == "NON_POSITIVE_SALES_NOT_CALCULABLE"

    bridge = build_cell_margin_bridge(cross)
    bridged = bridge.loc[
        bridge["industry_code"].eq("145")
        & bridge["capital_size_code"].eq("19")
    ].iloc[0]
    assert bridged["bridge_status"] == "NON_POSITIVE_SALES_NOT_CALCULABLE"
    assert pd.isna(bridged["shapley_sales_effect_oku_yen"])
    capital = build_capital_margin_bridge(cross)
    small = capital.loc[capital["capital_size_code"].eq("19")].iloc[0]
    assert small["bridge_status"] == "NON_POSITIVE_CELL_SALES_NOT_CALCULABLE"
    assert pd.isna(small["industry_composition_effect_oku_yen"])


def test_integrated_phase1_result_is_fail_closed_and_complete(
    stage2_processed: pd.DataFrame,
) -> None:
    result = build_phase1_analysis(stage2_processed)
    assert result.phase0_checks["status"].eq("PASS").all()
    assert result.additivity_checks["status"].eq("PASS").all()
    assert len(result.major_industry_x_capital) == 33
    assert len(result.leaf_industry_x_capital) == 135
    assert len(result.capital_margin_bridge) == len(CAPITAL_CODES)
    assert set(result.ordinary_operating_gap["aggregation_level"]) == {
        "ALL",
        "CAPITAL",
        "INDUSTRY",
        "INDUSTRY_X_CAPITAL",
    }
    assert ALL_CAPITAL_CODE in set(
        result.software_capex_decomposition["capital_size_code"]
    )
