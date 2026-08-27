from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from corporate_quarterly.stage2_continuing_sample import (
    build_continuing_sample_analysis,
)
from corporate_quarterly.stage4_analysis import (
    CAPITAL_DESIGN,
    CENSUS_THRESHOLD_YEN,
    EXPLORATORY_BACKTEST_STATUS,
    SAMPLE_ERROR_STATUS,
    build_stage4_analysis,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def continuing():
    return build_continuing_sample_analysis(PROJECT_ROOT)


@pytest.fixture(scope="module")
def stage4(continuing):
    return build_stage4_analysis(PROJECT_ROOT, continuing=continuing)


def test_build_is_read_only_and_reuses_passed_analysis(monkeypatch, continuing) -> None:
    def forbidden_loader(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("passed analysis must be reused")

    monkeypatch.setattr(
        "corporate_quarterly.stage4_analysis.build_continuing_sample_analysis",
        forbidden_loader,
    )
    result = build_stage4_analysis(PROJECT_ROOT, continuing=continuing)
    assert result.headline_2x2["quarter_count"].sum() == 41


def test_headline_2x2_exact_counts_and_asymmetric_totals(stage4) -> None:
    frame = stage4.headline_2x2.set_index("cell_id")
    assert frame["quarter_count"].to_dict() == {
        "REGULAR_ONLY": 9,
        "CONTINUING_ONLY": 2,
        "BOTH": 1,
        "NEITHER": 29,
    }
    assert frame["denominator_quarters"].eq(41).all()
    assert frame["not_comparable_quarters"].eq(0).all()
    assert frame["regular_supported_total"].eq(10).all()
    assert frame["continuing_supported_total"].eq(3).all()
    assert frame["exploratory_backtest_status"].eq(
        EXPLORATORY_BACKTEST_STATUS
    ).all()
    assert np.isclose(frame.loc["REGULAR_ONLY", "share_pct"], 9 / 41 * 100)


def test_heatmap_reproduces_all_nine_requested_cells(stage4) -> None:
    frame = stage4.mismatch_heatmap.set_index(["metric_id", "capital_code"])
    expected = {
        ("relative_margin_direction", "19"): (16, 41, 39.024390),
        ("relative_margin_direction", "24"): (6, 41, 14.634146),
        ("relative_margin_direction", "25"): (0, 41, 0.0),
        ("operating_profit", "19"): (13, 41, 31.707317),
        ("operating_profit", "24"): (4, 41, 9.756098),
        ("operating_profit", "25"): (0, 41, 0.0),
        ("sales", "19"): (6, 40, 15.0),
        ("sales", "24"): (7, 41, 17.073171),
        ("sales", "25"): (1, 41, 2.439024),
    }
    assert set(frame.index) == set(expected)
    for key, (count, denominator, rate) in expected.items():
        row = frame.loc[key]
        assert row["mismatch_count"] == count
        assert row["comparable_quarters"] == denominator
        assert row["mismatch_rate_pct"] == pytest.approx(rate, abs=1e-6)
    assert frame.loc[("sales", "19"), "noncomparable_quarters"] == 1


def test_heatmap_carries_explicit_census_rotation_design_notes(stage4) -> None:
    frame = stage4.mismatch_heatmap
    assert frame["census_threshold_yen"].eq(CENSUS_THRESHOLD_YEN).all()
    for capital_code, expected in CAPITAL_DESIGN.items():
        rows = frame.loc[frame["capital_code"].eq(capital_code)]
        assert len(rows) == 3
        assert rows["census_sample_design_ja"].eq(
            expected["census_sample_design_ja"]
        ).all()
        assert rows["rotation_status"].eq(expected["rotation_status"]).all()
        assert rows["rotation_note_ja"].eq(expected["rotation_note_ja"]).all()
    assert frame["design_interpretation_note"].str.contains("整合的").all()
    assert frame["design_interpretation_note"].str.contains("原因であること.*示さない").all()


def test_decision_margin_and_cross_series_divergence_medians(stage4) -> None:
    frame = stage4.decision_margin_summary.set_index("capital_code")
    assert frame["continuing_decision_margin_abs_gap_median_pct"].to_dict() == pytest.approx(
        {"19": 11.3, "24": 9.0, "25": 8.5}, abs=1e-12
    )
    assert frame["cross_series_growth_gap_divergence_median_pp"].to_dict() == pytest.approx(
        {"19": 11.20869500294094, "24": 4.070024346681685, "25": 1.0500234778042916},
        abs=1e-12,
    )
    # The headline confound is rejected descriptively: the all-census tier does
    # not have a larger continuing-series decision margin than the sample tier.
    assert (
        frame.loc["25", "continuing_decision_margin_abs_gap_median_pct"]
        < frame.loc["19", "continuing_decision_margin_abs_gap_median_pct"]
    )
    assert frame["large_amplitude_explanation_status"].eq(
        "NOT_SUPPORTED_DESCRIPTIVELY"
    ).all()
    assert frame["large_amplitude_explanation_note_ja"].str.contains(
        "因果関係の検証ではない"
    ).all()


def test_rounding_sensitivity_has_no_ambiguous_quarters_and_exact_minimum(stage4) -> None:
    frame = stage4.rounding_sensitivity
    assert len(frame) == 41
    assert set(frame["capital_code"]) == {"19"}
    assert int(frame["is_ambiguous_by_rounding"].sum()) == 0
    assert not frame["rounding_direction_status"].eq(
        "NOT_DETERMINED_BY_ROUNDING"
    ).any()
    minimum = frame.loc[
        frame["absolute_decision_margin_pp"].eq(
            frame["absolute_decision_margin_pp"].min()
        )
    ]
    assert minimum["period_code"].tolist() == ["20182"]
    assert minimum["absolute_decision_margin_pp"].item() == pytest.approx(0.5)
    assert minimum["relative_growth_gap_low_pp"].item() == pytest.approx(0.4)
    assert frame["sample_error_status"].eq(SAMPLE_ERROR_STATUS).all()
    assert frame["rounding_interpretation_note"].str.contains("標本誤差.*未定量").all()


def test_rounding_boundary_rule_is_inclusive(continuing) -> None:
    modified = continuing.relative_margin_comparison.copy()
    key = (
        modified["breakdown"].eq("capital_size")
        & modified["category_code"].astype(str).eq("19")
        & modified["period_code"].astype(str).eq("20182")
    )
    modified.loc[key, "continuing_sales_yoy_pct"] = 0.0
    modified.loc[key, "continuing_operating_profit_yoy_pct"] = 0.1
    from dataclasses import replace

    synthetic = replace(continuing, relative_margin_comparison=modified)
    from corporate_quarterly.stage4_analysis import build_rounding_sensitivity

    result = build_rounding_sensitivity(synthetic)
    row = result.loc[result["period_code"].eq("20182")].iloc[0]
    assert row["is_ambiguous_by_rounding"]
    assert row["rounding_direction_status"] == "NOT_DETERMINED_BY_ROUNDING"


def test_deadband_sensitivity_reproduces_small_tier_sequence(stage4) -> None:
    frame = stage4.deadband_sensitivity
    assert len(frame) == 12
    small = frame.loc[frame["capital_code"].eq("19")].set_index("deadband_pct")
    expected = {0.5: (15, 39), 1.0: (14, 37), 2.0: (10, 33), 3.0: (8, 29)}
    assert {
        d: (int(small.loc[d, "mismatch_count"]), int(small.loc[d, "retained_quarters"]))
        for d in expected
    } == expected
    assert small.loc[3.0, "mismatch_rate_pct"] == pytest.approx(27.5862068966)
    assert small["unit"].eq(
        "estimated_relative_margin_change_pct (%) - not operating-margin percentage points"
    ).all()


def test_deadband_three_percent_leaves_only_small_tier_mismatch(stage4) -> None:
    d3 = stage4.deadband_sensitivity.loc[
        stage4.deadband_sensitivity["deadband_pct"].eq(3.0)
    ].set_index("capital_code")
    assert d3.loc["19", "mismatch_count"] == 8
    assert d3.loc["19", "retained_quarters"] == 29
    assert d3.loc["19", "mismatch_rate_pct"] == pytest.approx(8 / 29 * 100)
    assert d3.loc["24", "mismatch_rate_pct"] == 0.0
    assert d3.loc["25", "mismatch_rate_pct"] == 0.0
    assert d3.loc["24", "retained_quarters"] == 29
    assert d3.loc["25", "retained_quarters"] == 33


def test_near_zero_base_flag_is_mechanical_and_not_a_row_deletion_rate(stage4) -> None:
    frame = stage4.near_zero_base_flags
    assert frame["period_code"].tolist() == ["20212", "20213", "20233"]
    assert len(frame) == 3
    assert frame["mechanical_flag"].eq("NEAR_ZERO_BASE").all()
    assert frame["extreme_yoy_rate_gt_100"].all()
    assert (~frame["relative_margin_direction_reversal"]).all()
    assert (~frame["headline_reversal"]).all()
    assert frame["flagged_margin_reversal_count"].eq(0).all()
    assert frame["flagged_headline_reversal_count"].eq(0).all()
    assert frame["margin_reversal_count_fixed_window_before"].eq(16).all()
    assert frame["margin_reversal_count_fixed_window_after_attribution"].eq(16).all()
    assert frame["headline_reversal_count_fixed_window_before"].eq(11).all()
    assert frame["headline_reversal_count_fixed_window_after_attribution"].eq(11).all()
    assert frame["fixed_window_denominator_quarters"].eq(41).all()
    assert frame["row_deletion_denominator_quarters"].eq(38).all()
    assert frame["sensitivity_method"].eq(
        "FIXED_41_QUARTER_EVENT_ATTRIBUTION_NOT_ROW_DELETION"
    ).all()
    assert frame["causal_interpretation_status"].eq(
        "NOT_ESTABLISHED_BY_RATE_ALONE"
    ).all()


def test_no_analysis_table_zero_fills_missing_values(stage4) -> None:
    # The one zero-involved sales quarter is kept as explicitly non-comparable,
    # not silently added to the denominator or counted as a non-mismatch.
    small_sales = stage4.mismatch_heatmap.loc[
        stage4.mismatch_heatmap["capital_code"].eq("19")
        & stage4.mismatch_heatmap["metric_id"].eq("sales")
    ].iloc[0]
    assert small_sales["total_quarters"] == 41
    assert small_sales["comparable_quarters"] == 40
    assert small_sales["noncomparable_quarters"] == 1
    assert small_sales["mismatch_count"] == 6
    assert small_sales["mismatch_rate_pct"] == 15.0


def test_main_and_composite_frequencies_both_marked_post_hoc(stage4) -> None:
    assert stage4.headline_2x2["exploratory_backtest_status"].eq(
        EXPLORATORY_BACKTEST_STATUS
    ).all()
    margin = stage4.mismatch_heatmap.loc[
        stage4.mismatch_heatmap["capital_code"].eq("19")
        & stage4.mismatch_heatmap["metric_id"].eq(
            "relative_margin_direction"
        )
    ]
    assert margin["exploratory_backtest_status"].eq(
        EXPLORATORY_BACKTEST_STATUS
    ).all()
    prohibited_probability_words = ("事前確率", "誤報率", "バイアス率", "有意")
    all_text = "\n".join(
        str(value)
        for output in (
            stage4.headline_2x2,
            stage4.mismatch_heatmap,
            stage4.rounding_sensitivity,
            stage4.deadband_sensitivity,
        )
        for value in output.astype(str).to_numpy().ravel()
    )
    assert not any(word in all_text for word in prohibited_probability_words)


def test_outputs_do_not_call_either_series_truth_or_correct(stage4) -> None:
    all_text = "\n".join(
        str(value)
        for output in (
            stage4.headline_2x2,
            stage4.mismatch_heatmap,
            stage4.decision_margin_summary,
            stage4.rounding_sensitivity,
            stage4.deadband_sensitivity,
            stage4.near_zero_base_flags,
        )
        for value in output.astype(str).to_numpy().ravel()
    )
    assert "真実" not in all_text
    assert "正解" not in all_text
    assert "同一企業パネル" not in all_text
