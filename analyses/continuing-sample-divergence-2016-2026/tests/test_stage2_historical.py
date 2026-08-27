from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from corporate_quarterly.estat import _find_dimension, sha256_file
from corporate_quarterly.stage2_historical import (
    CURRENT_VINTAGE_STATUS,
    HISTORICAL_CAPITAL_SIZES,
    HISTORICAL_INDUSTRIES,
    HISTORICAL_METRICS,
    REVISION_STATUS,
    HistoricalDataError,
    _safe_positive_contribution,
    _safe_profit_share,
    build_candidate_series,
    build_historical_query,
    build_historical_quarterly,
    build_historical_robustness,
    build_pattern_decisions,
    classify_pre_registered_pattern,
    detect_software_definition_start,
    fetch_historical_snapshot,
    historical_position,
    load_historical_snapshot,
    load_stage2_config,
    verify_historical_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def snapshot():
    return load_historical_snapshot(PROJECT_ROOT)


@pytest.fixture(scope="module")
def historical() -> pd.DataFrame:
    return build_historical_quarterly(PROJECT_ROOT)


@pytest.fixture(scope="module")
def candidate_series(historical: pd.DataFrame) -> pd.DataFrame:
    return build_candidate_series(historical, load_stage2_config(PROJECT_ROOT))


def test_query_is_exact_current_classification_slice(project_root: Path) -> None:
    model_path = (
        project_root
        / "data"
        / "raw"
        / "historical_2026Q1"
        / "historical_table1_model.json"
    )
    model = json.loads(model_path.read_text(encoding="utf-8"))
    posted, metadata, selected = build_historical_query(model)

    assert len(selected["periods"]) == 288
    assert selected["periods"][0]["code"] == "19542"
    assert selected["periods"][-1]["code"] == "20261"
    assert [row["code"] for row in selected["industries"]] == list(
        HISTORICAL_INDUSTRIES
    )
    assert [row["code"] for row in selected["capital_sizes"]] == list(
        HISTORICAL_CAPITAL_SIZES
    )
    assert [row["metric_id"] for row in selected["metrics"]] == list(
        HISTORICAL_METRICS
    )
    assert metadata["request"]["http_method"] == "POST"
    assert metadata["request"]["url"].endswith("sid=0003060191")
    assert metadata["request"]["form_payload"] == posted
    assert all(isinstance(posted[key], str) for key in ("rows", "cols"))


def test_query_rejects_silent_code_name_reassignment(project_root: Path) -> None:
    model_path = (
        project_root
        / "data"
        / "raw"
        / "historical_2026Q1"
        / "historical_table1_model.json"
    )
    model = deepcopy(json.loads(model_path.read_text(encoding="utf-8")))
    _, industry = _find_dimension(model, "industry")
    entry = next(
        row for row in industry["listData"].values() if row["code"] == "104"
    )
    entry["name"] = "classification changed"

    with pytest.raises(HistoricalDataError, match="classification changed"):
        build_historical_query(model)


def test_snapshot_manifest_freezes_all_three_artifacts(
    project_root: Path, snapshot
) -> None:
    parsed, manifest, query = snapshot
    verify_historical_manifest(manifest, project_root)

    assert parsed.shape == (9750, 24)
    assert set(parsed["missing_status"]) == {"PRESENT"}
    assert manifest["vintage_status"] == CURRENT_VINTAGE_STATUS
    assert manifest["revision_robustness_status"] == REVISION_STATUS
    assert manifest["selection"]["model_period_count"] == 288
    assert manifest["selection"]["model_first_period_code"] == "19542"
    assert manifest["selection"]["model_last_period_code"] == "20261"
    assert manifest["software_capex_comparable_start_period_code"] == "20013"
    assert query["dimension_spec"]["time"][0]["code"] == "19542"
    assert query["dimension_spec"]["time"][-1]["code"] == "20261"

    sources = {source["source_id"]: source for source in manifest["sources"]}
    assert set(sources) == {
        "historical_table1_model",
        "historical_table1_query",
        "historical_table1_values",
    }
    for source in sources.values():
        assert source["http_method"] == "POST"
        assert source["estat_sid"] == "0003060191"
        assert source["retrieved_at"]
        assert source["url"].startswith("https://www.e-stat.go.jp/")
        raw_path = project_root / source["raw_path"]
        assert sha256_file(raw_path) == source["sha256"]
        assert raw_path.stat().st_size == source["bytes"]


def test_existing_snapshot_fetch_is_offline_and_hash_verified(project_root: Path) -> None:
    class NoNetworkSession:
        headers: dict[str, str] = {}

        def post(self, *args, **kwargs):  # pragma: no cover - must never be called
            raise AssertionError("existing immutable snapshot must not make a network call")

    manifest = fetch_historical_snapshot(project_root, session=NoNetworkSession())
    assert manifest["historical_vintage_id"] == "historical_2026Q1"


def test_machine_detected_first_present_periods_and_no_internal_gaps(snapshot) -> None:
    _, manifest, _ = snapshot
    availability = pd.DataFrame(manifest["mechanical_availability"])
    assert len(availability) == 45
    assert (availability["internal_missing_count"] == 0).all()

    expected_start = {
        ("104", "26"): "19542",
        ("104", "19"): "19542",
        ("108", "26"): "19542",
        ("108", "19"): "19542",
        ("104", "25"): "19593",
        ("108", "25"): "19593",
        ("145", "26"): "20042",
        ("145", "25"): "20042",
        ("145", "19"): "20042",
    }
    for key, frame in availability.groupby(
        ["industry_code", "capital_size_code"], sort=False
    ):
        assert set(frame["source_first_present_period_code"]) == {
            expected_start[key]
        }


def test_software_definition_start_is_detected_from_values(snapshot) -> None:
    parsed, _, _ = snapshot
    start, events = detect_software_definition_start(parsed)
    assert start == "20013"
    assert events[0]["kind"] == "CAPEX_SOFTWARE_DEFINITION_START"
    assert not [event for event in events if event["severity"] == "FAIL"]


def test_historical_panel_schema_units_and_comparability(
    historical: pd.DataFrame,
) -> None:
    assert historical.shape == (17550, 52)
    key = ["industry_code", "capital_size_code", "metric_id", "period_code"]
    assert not historical.duplicated(key).any()
    assert set(historical["historical_vintage_id"]) == {"historical_2026Q1"}
    assert set(historical["vintage_status"]) == {CURRENT_VINTAGE_STATUS}
    assert set(historical["revision_robustness_status"]) == {REVISION_STATUS}
    assert set(historical["classification_status"]) == {
        "CURRENT_MODEL_CODE_NAME_MATCH"
    }

    current_ordinary = historical.loc[
        historical["period_code"].eq("20261")
        & historical["industry_code"].eq("104")
        & historical["capital_size_code"].eq("26")
        & historical["metric_id"].eq("ordinary_profit")
    ].iloc[0]
    assert current_ordinary["source_unit"] == "百万円"
    assert current_ordinary["source_value"] == pytest.approx(32_627_086.0)
    assert current_ordinary["analytical_unit"] == "億円"
    assert current_ordinary["value"] == pytest.approx(326_270.86)
    assert current_ordinary["yoy_delta_oku_yen"] == pytest.approx(41_576.87)

    software = historical.loc[
        historical["industry_code"].eq("104")
        & historical["capital_size_code"].eq("26")
        & historical["metric_id"].eq("software_capex_derived")
    ].set_index("period_code")
    assert pd.isna(software.loc["20012", "value"])
    assert (
        software.loc["20012", "missing_status"]
        == "PRE_DEFINITION_NOT_COMPARABLE"
    )
    assert software.loc["20012", "comparability_status"] == "PRE_COMPARABLE_PERIOD"
    assert software.loc["20013", "comparability_start_period_code"] == "20013"
    assert software.loc["20013", "value"] == pytest.approx(5_201.16)
    assert pd.isna(software.loc["20022", "yoy_delta"])
    assert software.loc["20023", "yoy_delta"] == pytest.approx(1_135.58)


def test_four_quarter_calculations_match_direct_sums(historical: pd.DataFrame) -> None:
    series = historical.loc[
        historical["industry_code"].eq("104")
        & historical["capital_size_code"].eq("26")
        & historical["metric_id"].eq("ordinary_profit")
    ].set_index("period_code")
    current_codes = ["20252", "20253", "20254", "20261"]
    prior_codes = ["20242", "20243", "20244", "20251"]
    current_sum = series.loc[current_codes, "value"].sum()
    prior_sum = series.loc[prior_codes, "value"].sum()

    assert series.loc["20261", "rolling_4q_value"] == pytest.approx(current_sum)
    assert series.loc["20261", "rolling_4q_lag4_value"] == pytest.approx(
        prior_sum
    )
    assert series.loc["20261", "rolling_4q_yoy_delta"] == pytest.approx(
        current_sum - prior_sum
    )
    assert series.loc["20261", "rolling_4q_yoy_pct"] == pytest.approx(
        (current_sum / prior_sum - 1.0) * 100.0
    )


@pytest.mark.parametrize(
    ("overrides", "expected_status"),
    [
        ({"denominator_delta": np.nan}, "MISSING_INPUT"),
        ({"denominator_delta": 0.0}, "DENOMINATOR_ZERO"),
        ({"denominator_delta": -1.0}, "DENOMINATOR_NOT_POSITIVE"),
        ({"numerator_prior": -1.0}, "PROFIT_SIGN_NOT_POSITIVE"),
        ({"denominator_current": 0.0}, "PROFIT_SIGN_NOT_POSITIVE"),
    ],
)
def test_profit_share_invalid_denominators_and_signs_are_null(
    overrides: dict[str, float], expected_status: str
) -> None:
    inputs = {
        "numerator_delta": 5.0,
        "denominator_delta": 10.0,
        "numerator_current": 20.0,
        "numerator_prior": 15.0,
        "denominator_current": 100.0,
        "denominator_prior": 90.0,
    }
    inputs.update(overrides)
    value, status = _safe_profit_share(**inputs)
    assert value is None
    assert status == expected_status


def test_positive_contribution_never_zero_fills_invalid_denominator() -> None:
    assert _safe_positive_contribution(1.0, 0.0) == (None, "DENOMINATOR_ZERO")
    assert _safe_positive_contribution(1.0, -1.0) == (
        None,
        "DENOMINATOR_NOT_POSITIVE",
    )
    assert _safe_positive_contribution(np.nan, 1.0) == (None, "MISSING_INPUT")


def test_current_candidate_components_reproduce_phase0(
    candidate_series: pd.DataFrame,
) -> None:
    current = candidate_series.loc[
        candidate_series["period_code"].eq("20261")
    ].set_index("candidate_id")
    assert set(current.index) == set("ABCDE")

    assert current.loc["A", "indicator_value"] == pytest.approx(72.059729, abs=1e-6)
    assert current.loc["A", "numerator_yoy_delta_oku_yen"] == pytest.approx(
        29_960.18
    )
    assert current.loc["A", "denominator_yoy_delta_oku_yen"] == pytest.approx(
        41_576.87
    )

    assert current.loc["B", "small_sales_yoy_pct"] == pytest.approx(
        2.100851, abs=1e-6
    )
    assert current.loc[
        "B", "small_operating_margin_yoy_delta_pp"
    ] == pytest.approx(-0.227518, abs=1e-6)
    assert current.loc[
        "B", "large_operating_margin_yoy_delta_pp"
    ] == pytest.approx(1.069859, abs=1e-6)
    assert current.loc["B", "indicator_value"] == pytest.approx(0.227518, abs=1e-6)

    assert current.loc["C", "capex_including_yoy_pct"] == pytest.approx(
        0.047230, abs=1e-6
    )
    assert current.loc[
        "C", "software_capex_yoy_delta_oku_yen"
    ] == pytest.approx(2_431.42)
    assert current.loc[
        "C", "capex_excluding_yoy_delta_oku_yen"
    ] == pytest.approx(-2_342.64)
    assert current.loc[
        "C", "small_capital_software_contribution_pct"
    ] == pytest.approx(73.377286, abs=1e-6)

    assert current.loc["D", "indicator_value"] == pytest.approx(37.536784, abs=1e-6)
    assert current.loc["D", "numerator_yoy_delta_oku_yen"] == pytest.approx(
        15_606.62
    )
    assert current.loc["E", "indicator_value"] == pytest.approx(38.129710, abs=1e-6)
    assert current.loc["E", "numerator_yoy_delta_oku_yen"] == pytest.approx(
        15_853.14
    )
    assert (current["indicator_status"] == "CALCULABLE").all()


def test_historical_position_uses_median_iqr_mad_and_empirical_percentile() -> None:
    result = historical_position(pd.Series([1.0, 2.0, 3.0, 4.0, np.nan]), 4.0)
    assert result["history_n"] == 4
    assert result["historical_percentile"] == 100.0
    assert result["historical_median"] == 2.5
    assert result["historical_q1"] == 1.75
    assert result["historical_q3"] == 3.25
    assert result["historical_iqr"] == 1.5
    assert result["historical_mad"] == 1.0
    assert result["iqr_outlier_score"] == 1.0
    assert result["mad_robust_z"] == pytest.approx(1.0117346253)


@pytest.mark.parametrize(
    ("same_direction", "rolling", "percentile", "expected"),
    [
        ([False, True, True, True], True, 50.0, "PERSISTENT_PATTERN"),
        ([False, False, True, True], False, 50.0, "RECENT_BUT_NOT_ESTABLISHED"),
        ([False, False, False, False], True, 50.0, "RECENT_BUT_NOT_ESTABLISHED"),
        ([False, False, False, True], False, 91.0, "ONE_QUARTER_OUTLIER"),
        ([False, False, False, True], False, 90.0, "UNSTABLE_OR_NO_PATTERN"),
    ],
)
def test_pre_registered_pattern_classifier(
    same_direction: list[bool],
    rolling: bool,
    percentile: float,
    expected: str,
    project_root: Path,
) -> None:
    rules = load_stage2_config(project_root)["pattern_rule"]
    evidence = classify_pre_registered_pattern(
        same_direction=same_direction,
        rolling_4q_same_direction=rolling,
        historical_percentile=percentile,
        rules=rules,
    )
    assert evidence.decision == expected
    assert evidence.same_direction_last4 == sum(same_direction[-4:])


def test_current_pattern_decisions_are_frozen_and_have_robust_statistics(
    candidate_series: pd.DataFrame, project_root: Path
) -> None:
    config = load_stage2_config(project_root)
    robustness = build_historical_robustness(candidate_series, config)
    decisions = build_pattern_decisions(candidate_series, config).set_index(
        "candidate_id"
    )
    assert robustness["criteria_frozen_before_analysis"].all()
    assert (robustness["history_n"] > 0).all()
    assert robustness["historical_median"].notna().all()
    assert robustness["historical_iqr"].notna().all()
    assert robustness["historical_mad"].notna().all()
    assert robustness["same_direction_last4"].between(0, 4).all()
    assert robustness["same_direction_last8"].between(0, 8).all()
    assert decisions["pattern_decision"].to_dict() == {
        "A": "UNSTABLE_OR_NO_PATTERN",
        "B": "RECENT_BUT_NOT_ESTABLISHED",
        "C": "ONE_QUARTER_OUTLIER",
        "D": "RECENT_BUT_NOT_ESTABLISHED",
        "E": "UNSTABLE_OR_NO_PATTERN",
    }
    assert not decisions["pattern_decision"].eq("PERSISTENT_PATTERN").any()
