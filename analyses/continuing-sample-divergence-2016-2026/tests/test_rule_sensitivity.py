from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from corporate_quarterly.rule_sensitivity import (
    BOOLEAN_CONDITIONS,
    CORRECTED_RULE_ID,
    DECISION_RANK,
    LEGACY_RULE_ID,
    build_corrected_boolean_signals,
    build_count_rolling_sensitivity,
    build_rule_sensitivity,
    classify_corrected_pattern,
    inclusive_empirical_percentile,
    legacy_rule_snapshot,
)


@pytest.fixture
def frozen_candidate_series(project_root: Path) -> pd.DataFrame:
    return pd.read_parquet(
        project_root
        / "outputs"
        / "2026Q1_v2"
        / "historical_candidate_series.parquet"
    )


def _output_hashes(project_root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for release in ("2026Q1", "2026Q1_v2"):
        root = project_root / "outputs" / release
        for path in root.rglob("*"):
            if path.is_file():
                result[path.relative_to(project_root).as_posix()] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
    return result


def test_legacy_rule_snapshot_preserves_frozen_config(project_root: Path) -> None:
    config = json.loads(
        (project_root / "config" / "stage2_2026Q1.json").read_text(
            encoding="utf-8"
        )
    )
    snapshot = legacy_rule_snapshot(config)
    assert snapshot["rule_id"] == LEGACY_RULE_ID
    assert snapshot["pattern_rule"] == config["pattern_rule"]
    assert snapshot["candidate_B"] == config["candidate_rules"]["B"]
    assert snapshot["candidate_C"] == config["candidate_rules"]["C"]
    assert snapshot["immutability_status"] == (
        "FROZEN_OUTPUTS_2026Q1_V2_NOT_REWRITTEN"
    )


def test_candidates_b_c_use_nullable_boolean_conditions_not_composites(
    frozen_candidate_series: pd.DataFrame,
) -> None:
    corrected = build_corrected_boolean_signals(frozen_candidate_series)
    assert set(corrected["candidate_id"]) == {"B", "C"}
    assert set(corrected["corrected_indicator_id"]) == {
        BOOLEAN_CONDITIONS["B"]["indicator_id"],
        BOOLEAN_CONDITIONS["C"]["indicator_id"],
    }
    finite = corrected["corrected_indicator_value"].dropna().astype(float)
    assert set(finite.unique()) <= {0.0, 1.0}
    assert corrected.loc[
        corrected["corrected_indicator_status"].eq("MISSING_INPUT"),
        "corrected_indicator_value",
    ].isna().all()
    current = corrected.loc[corrected["period_code"].eq("20261")].set_index(
        "candidate_id"
    )
    assert current.loc["B", "corrected_indicator_value"] == 1.0
    assert current.loc["C", "corrected_indicator_value"] == 1.0
    assert current["corrected_rule_id"].eq(CORRECTED_RULE_ID).all()
    assert current["legacy_composite_preserved"].eq(True).all()  # noqa: E712


def test_candidate_c_flat_boundary_is_inclusive(
    frozen_candidate_series: pd.DataFrame,
) -> None:
    sample = pd.concat(
        [
            frozen_candidate_series.loc[
                frozen_candidate_series["candidate_id"].eq(candidate)
            ].tail(1)
            for candidate in ("B", "C")
        ],
        ignore_index=True,
    )
    c = sample["candidate_id"].eq("C")
    sample.loc[c, "capex_including_yoy_pct"] = 1.0
    sample.loc[c, "software_capex_yoy_delta_oku_yen"] = 1.0
    sample.loc[c, "capex_excluding_yoy_delta_oku_yen"] = -1.0
    corrected = build_corrected_boolean_signals(sample)
    assert corrected.loc[
        corrected["candidate_id"].eq("C"), "corrected_indicator_value"
    ].iloc[0] == 1.0

    sample.loc[c, "capex_including_yoy_pct"] = 1.000001
    corrected = build_corrected_boolean_signals(sample)
    assert corrected.loc[
        corrected["candidate_id"].eq("C"), "corrected_indicator_value"
    ].iloc[0] == 0.0


def test_inclusive_percentile_metadata_counts_ties_and_excludes_missing() -> None:
    result = inclusive_empirical_percentile(
        [1.0, 2.0, 2.0, 3.0, None, float("nan")],
        2.0,
        reference_includes_current=True,
    )
    assert result["historical_percentile_inclusive_pct"] == 75.0
    assert result["percentile_numerator_le_current"] == 3
    assert result["percentile_denominator_non_missing"] == 4
    assert result["percentile_method"] == "INCLUSIVE_EMPIRICAL_CDF_LE"
    assert result["percentile_tie_policy"] == "INCLUDE_ALL_TIES_EQUAL_TO_CURRENT"
    assert result["percentile_reference_includes_current"] is True
    assert "NO_ZERO_FILL" in result["percentile_missing_policy"]


def test_corrected_count_rolling_grid_covers_all_ten_cases_and_is_monotone() -> None:
    grid = build_count_rolling_sensitivity()
    assert len(grid) == 10
    assert set(
        zip(
            grid["same_direction_last4"],
            grid["rolling_4q_same_direction"],
            strict=True,
        )
    ) == {(count, rolling) for count in range(5) for rolling in (False, True)}
    expected = {
        (0, False): "UNSTABLE_OR_NO_PATTERN",
        (1, False): "UNSTABLE_OR_NO_PATTERN",
        (2, False): "RECENT_BUT_NOT_ESTABLISHED",
        (3, False): "RECENT_BUT_NOT_ESTABLISHED",
        (4, False): "RECENT_BUT_NOT_ESTABLISHED",
        (0, True): "RECENT_BUT_NOT_ESTABLISHED",
        (1, True): "RECENT_BUT_NOT_ESTABLISHED",
        (2, True): "RECENT_BUT_NOT_ESTABLISHED",
        (3, True): "PERSISTENT_PATTERN",
        (4, True): "PERSISTENT_PATTERN",
    }
    observed = {
        (int(row.same_direction_last4), bool(row.rolling_4q_same_direction)): row.decision
        for row in grid.itertuples()
    }
    assert observed == expected
    for _, frame in grid.groupby("rolling_4q_same_direction"):
        ranks = frame.sort_values("same_direction_last4")["decision_rank"].tolist()
        assert ranks == sorted(ranks)
    for count in range(5):
        rows = grid.loc[grid["same_direction_last4"].eq(count)].set_index(
            "rolling_4q_same_direction"
        )
        assert rows.loc[True, "decision_rank"] >= rows.loc[False, "decision_rank"]
    assert set(grid["decision_rank"]) <= set(DECISION_RANK.values())


def test_corrected_classifier_does_not_convert_missing_to_false() -> None:
    result = classify_corrected_pattern(
        same_direction_last4=2,
        valid_observations_last4=3,
        current_same_direction=True,
        rolling_4q_same_direction=False,
        historical_percentile_inclusive_pct=99.0,
    )
    assert result.decision == "INSUFFICIENT_DATA"

    with pytest.raises(ValueError, match="cannot use a historical percentile"):
        classify_corrected_pattern(
            same_direction_last4=1,
            valid_observations_last4=4,
            current_same_direction=True,
            rolling_4q_same_direction=False,
            historical_percentile_inclusive_pct=100.0,
            numeric_history_eligible=False,
        )


def test_rule_sensitivity_keeps_boolean_candidates_out_of_numeric_percentiles(
    frozen_candidate_series: pd.DataFrame,
) -> None:
    sensitivity = build_rule_sensitivity(frozen_candidate_series).set_index(
        "candidate_id"
    )
    assert set(sensitivity.index) == set("ABCDE")
    for candidate in ("B", "C"):
        assert bool(sensitivity.loc[candidate, "numeric_history_eligible"]) is False
        assert pd.isna(
            sensitivity.loc[candidate, "historical_percentile_inclusive_pct"]
        )
        assert sensitivity.loc[candidate, "percentile_method"] == (
            "NOT_APPLICABLE_BOOLEAN_CONDITION"
        )
        assert sensitivity.loc[candidate, "corrected_indicator_unit"] == (
            "boolean_condition"
        )
    for candidate in ("A", "D", "E"):
        assert bool(sensitivity.loc[candidate, "numeric_history_eligible"]) is True
        assert pd.notna(
            sensitivity.loc[candidate, "historical_percentile_inclusive_pct"]
        )
        assert sensitivity.loc[candidate, "percentile_method"] == (
            "INCLUSIVE_EMPIRICAL_CDF_LE"
        )
    assert sensitivity.loc["C", "legacy_pattern_decision"] == (
        "ONE_QUARTER_OUTLIER"
    )
    assert sensitivity.loc["C", "corrected_pattern_decision"] == (
        "UNSTABLE_OR_NO_PATTERN"
    )
    assert sensitivity.loc["E", "legacy_pattern_decision"] == (
        "UNSTABLE_OR_NO_PATTERN"
    )
    assert sensitivity.loc["E", "corrected_pattern_decision"] == (
        "RECENT_BUT_NOT_ESTABLISHED"
    )


def test_sensitivity_api_does_not_mutate_frozen_v1_or_v2(
    project_root: Path, frozen_candidate_series: pd.DataFrame
) -> None:
    before = _output_hashes(project_root)
    build_rule_sensitivity(frozen_candidate_series)
    after = _output_hashes(project_root)
    assert after == before
