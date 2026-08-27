"""Additive rule corrections and sensitivity analysis for frozen Stage 2.

The generated ``outputs/2026Q1_v2`` vintage is immutable.  This module does
not rewrite it.  It preserves the exact legacy rule as metadata, replaces the
two artificial magnitude composites for candidates B and C with their stated
Boolean conditions, and evaluates a monotone correction to the count/rolling
decision table.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import math
from typing import Any, Iterable, Mapping

import pandas as pd

from .stage2_historical import (
    TARGET_PERIOD_CODE,
    build_historical_robustness,
    load_stage2_config,
)


LEGACY_RULE_ID = "stage2_2026Q1_frozen_pre_registered_v1"
CORRECTED_RULE_ID = "phase4_boolean_bc_monotone_counts_v2"
CORRECTED_RULE: dict[str, Any] = {
    "persistent_min_same_direction_last4": 3,
    "persistent_requires_rolling_4q_same_direction": True,
    "recent_min_same_direction_last4": 2,
    "recent_operator": ">=",
    "recent_if_rolling_4q_same_direction": True,
    "outlier_requires_current_only_in_last4": True,
    "outlier_percentile_threshold": 90.0,
    "outlier_percentile_operator": ">",
    "criteria_frozen_before_corrected_analysis": True,
}

DECISION_RANK = {
    "INSUFFICIENT_DATA": -1,
    "UNSTABLE_OR_NO_PATTERN": 0,
    "ONE_QUARTER_OUTLIER": 1,
    "RECENT_BUT_NOT_ESTABLISHED": 2,
    "PERSISTENT_PATTERN": 3,
}

BOOLEAN_CONDITIONS = {
    "B": {
        "indicator_id": "capital_margin_divergence_boolean",
        "current_columns": (
            "small_sales_yoy_pct",
            "small_operating_margin_yoy_delta_pp",
            "large_operating_margin_yoy_delta_pp",
        ),
        "rolling_columns": (
            "rolling_4q_small_sales_yoy_pct",
            "rolling_4q_small_operating_margin_yoy_delta_pp",
            "rolling_4q_large_operating_margin_yoy_delta_pp",
        ),
        "definition": (
            "small_sales_yoy_pct > 0 AND "
            "small_operating_margin_yoy_delta_pp < 0 AND "
            "large_operating_margin_yoy_delta_pp > 0"
        ),
        "rolling_definition": (
            "rolling_4q_small_sales_yoy_pct > 0 AND "
            "rolling_4q_small_operating_margin_yoy_delta_pp < 0 AND "
            "rolling_4q_large_operating_margin_yoy_delta_pp > 0"
        ),
    },
    "C": {
        "indicator_id": "software_rotation_boolean",
        "current_columns": (
            "capex_including_yoy_pct",
            "software_capex_yoy_delta_oku_yen",
            "capex_excluding_yoy_delta_oku_yen",
        ),
        "rolling_columns": (
            "rolling_4q_capex_including_yoy_pct",
            "rolling_4q_software_capex_yoy_delta_oku_yen",
            "rolling_4q_capex_excluding_yoy_delta_oku_yen",
        ),
        "definition": (
            "abs(capex_including_yoy_pct) <= flat_threshold AND "
            "software_capex_yoy_delta_oku_yen > 0 AND "
            "capex_excluding_yoy_delta_oku_yen < 0"
        ),
        "rolling_definition": (
            "abs(rolling_4q_capex_including_yoy_pct) <= flat_threshold AND "
            "rolling_4q_software_capex_yoy_delta_oku_yen > 0 AND "
            "rolling_4q_capex_excluding_yoy_delta_oku_yen < 0"
        ),
    },
}


@dataclass(frozen=True)
class CorrectedPatternEvidence:
    decision: str
    same_direction_last4: int
    valid_observations_last4: int
    current_same_direction: bool | None
    rolling_4q_same_direction: bool | None
    historical_percentile_inclusive_pct: float | None
    numeric_history_eligible: bool
    rule_id: str = CORRECTED_RULE_ID


def legacy_rule_snapshot(
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a JSON-serialisable copy of the exact rule used by frozen v2."""
    stage2 = dict(config or load_stage2_config())
    return {
        "rule_id": LEGACY_RULE_ID,
        "immutability_status": "FROZEN_OUTPUTS_2026Q1_V2_NOT_REWRITTEN",
        "pattern_rule": deepcopy(stage2["pattern_rule"]),
        "candidate_B": deepcopy(stage2["candidate_rules"]["B"]),
        "candidate_C": deepcopy(stage2["candidate_rules"]["C"]),
    }


def inclusive_empirical_percentile(
    values: Iterable[Any],
    current: Any,
    *,
    reference_includes_current: bool,
) -> dict[str, Any]:
    """Calculate and document the inclusive empirical CDF percentile.

    Missing and non-finite reference values are excluded, never converted to
    zero.  Ties equal to the current value are included in the numerator.
    """
    clean: list[float] = []
    for value in values:
        if pd.isna(value):
            continue
        number = float(value)
        if math.isfinite(number):
            clean.append(number)
    current_value = None
    if not pd.isna(current):
        parsed = float(current)
        if math.isfinite(parsed):
            current_value = parsed
    numerator = (
        sum(value <= current_value for value in clean)
        if current_value is not None
        else None
    )
    percentile = (
        100.0 * float(numerator) / len(clean)
        if numerator is not None and clean
        else None
    )
    return {
        "historical_percentile_inclusive_pct": percentile,
        "percentile_numerator_le_current": numerator,
        "percentile_denominator_non_missing": len(clean),
        "percentile_method": "INCLUSIVE_EMPIRICAL_CDF_LE",
        "percentile_formula": (
            "100 * count(non-missing finite reference values <= current) / "
            "count(non-missing finite reference values)"
        ),
        "percentile_tie_policy": "INCLUDE_ALL_TIES_EQUAL_TO_CURRENT",
        "percentile_reference_includes_current": bool(reference_includes_current),
        "percentile_missing_policy": "EXCLUDE_MISSING_AND_NON_FINITE_NO_ZERO_FILL",
    }


def _nullable_condition(
    frame: pd.DataFrame,
    *,
    candidate_id: str,
    rolling: bool,
    flat_threshold: float,
) -> tuple[pd.Series, pd.Series]:
    definition = BOOLEAN_CONDITIONS[candidate_id]
    columns = definition["rolling_columns" if rolling else "current_columns"]
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(
            f"Candidate {candidate_id} Boolean inputs are missing: {sorted(missing)}"
        )
    numeric = frame.loc[:, list(columns)].apply(pd.to_numeric, errors="coerce")
    finite = numeric.notna().all(axis=1)
    if candidate_id == "B":
        condition = numeric.iloc[:, 0].gt(0) & numeric.iloc[:, 1].lt(0) & numeric.iloc[:, 2].gt(0)
    else:
        condition = (
            numeric.iloc[:, 0].abs().le(float(flat_threshold))
            & numeric.iloc[:, 1].gt(0)
            & numeric.iloc[:, 2].lt(0)
        )
    result = condition.astype("boolean").where(finite, pd.NA)
    status = pd.Series(
        ["CALCULABLE" if value else "MISSING_INPUT" for value in finite],
        index=frame.index,
        dtype="object",
    )
    return result, status


def build_corrected_boolean_signals(
    candidate_series: pd.DataFrame,
    *,
    flat_including_capex_abs_yoy_pct_max: float = 1.0,
) -> pd.DataFrame:
    """Return corrected, nullable Boolean signals for candidates B and C."""
    required = {"candidate_id", "period_code", "period_ordinal"}
    missing = required - set(candidate_series.columns)
    if missing:
        raise ValueError(f"candidate_series missing columns: {sorted(missing)}")
    selected = candidate_series.loc[
        candidate_series["candidate_id"].isin(BOOLEAN_CONDITIONS)
    ].copy()
    if set(selected["candidate_id"]) != set(BOOLEAN_CONDITIONS):
        raise ValueError("candidate_series must contain both candidate B and candidate C")
    if selected.duplicated(["candidate_id", "period_code"]).any():
        raise ValueError("candidate_series has duplicate candidate/period rows")

    records: list[pd.DataFrame] = []
    for candidate_id in ("B", "C"):
        frame = selected.loc[selected["candidate_id"].eq(candidate_id)].copy()
        current, current_status = _nullable_condition(
            frame,
            candidate_id=candidate_id,
            rolling=False,
            flat_threshold=flat_including_capex_abs_yoy_pct_max,
        )
        rolling, rolling_status = _nullable_condition(
            frame,
            candidate_id=candidate_id,
            rolling=True,
            flat_threshold=flat_including_capex_abs_yoy_pct_max,
        )
        result = frame[["candidate_id", "period_code", "period_ordinal"]].copy()
        result["corrected_indicator_id"] = BOOLEAN_CONDITIONS[candidate_id][
            "indicator_id"
        ]
        result["corrected_indicator_unit"] = "boolean_condition"
        result["corrected_indicator_value"] = current.astype("Float64")
        result["corrected_indicator_status"] = current_status
        result["corrected_same_direction"] = current
        result["corrected_rolling_4q_indicator_value"] = rolling.astype("Float64")
        result["corrected_rolling_4q_indicator_status"] = rolling_status
        result["corrected_rolling_4q_same_direction"] = rolling
        result["corrected_indicator_definition"] = BOOLEAN_CONDITIONS[candidate_id][
            "definition"
        ]
        result["corrected_rolling_definition"] = BOOLEAN_CONDITIONS[candidate_id][
            "rolling_definition"
        ]
        result["flat_including_capex_abs_yoy_pct_max"] = (
            float(flat_including_capex_abs_yoy_pct_max)
            if candidate_id == "C"
            else float("nan")
        )
        result["legacy_composite_preserved"] = True
        result["corrected_rule_id"] = CORRECTED_RULE_ID
        records.append(result)
    return pd.concat(records, ignore_index=True).sort_values(
        ["candidate_id", "period_ordinal"], kind="stable"
    ).reset_index(drop=True)


def classify_corrected_pattern(
    *,
    same_direction_last4: int,
    valid_observations_last4: int,
    current_same_direction: bool | None,
    rolling_4q_same_direction: bool | None,
    historical_percentile_inclusive_pct: float | None,
    numeric_history_eligible: bool = True,
    rules: Mapping[str, Any] | None = None,
) -> CorrectedPatternEvidence:
    """Apply the corrected monotone count/rolling rule.

    The important correction is ``count4 >= recent_min``.  The legacy exact
    equality made count4=3 with a false rolling signal weaker than count4=2.
    """
    rule = dict(rules or CORRECTED_RULE)
    count4 = int(same_direction_last4)
    valid4 = int(valid_observations_last4)
    if not 0 <= count4 <= 4:
        raise ValueError("same_direction_last4 must be between 0 and 4")
    if not 0 <= valid4 <= 4 or count4 > valid4:
        raise ValueError("valid_observations_last4 must be 0..4 and >= count")
    if not numeric_history_eligible and historical_percentile_inclusive_pct is not None:
        raise ValueError(
            "Boolean/non-numeric conditions cannot use a historical percentile"
        )
    if (
        valid4 < 4
        or current_same_direction is None
        or rolling_4q_same_direction is None
    ):
        decision = "INSUFFICIENT_DATA"
    else:
        persistent_min = int(rule["persistent_min_same_direction_last4"])
        recent_min = int(rule["recent_min_same_direction_last4"])
        outlier_threshold = float(rule["outlier_percentile_threshold"])
        if count4 >= persistent_min and bool(rolling_4q_same_direction):
            decision = "PERSISTENT_PATTERN"
        elif count4 >= recent_min or bool(rolling_4q_same_direction):
            decision = "RECENT_BUT_NOT_ESTABLISHED"
        elif (
            count4 == 1
            and bool(current_same_direction)
            and numeric_history_eligible
            and historical_percentile_inclusive_pct is not None
            and float(historical_percentile_inclusive_pct) > outlier_threshold
        ):
            decision = "ONE_QUARTER_OUTLIER"
        else:
            decision = "UNSTABLE_OR_NO_PATTERN"
    return CorrectedPatternEvidence(
        decision=decision,
        same_direction_last4=count4,
        valid_observations_last4=valid4,
        current_same_direction=current_same_direction,
        rolling_4q_same_direction=rolling_4q_same_direction,
        historical_percentile_inclusive_pct=historical_percentile_inclusive_pct,
        numeric_history_eligible=bool(numeric_history_eligible),
    )


def build_count_rolling_sensitivity() -> pd.DataFrame:
    """Return the complete 5 x 2 corrected decision table."""
    rows: list[dict[str, Any]] = []
    for rolling in (False, True):
        for count4 in range(5):
            current = count4 > 0
            evidence = classify_corrected_pattern(
                same_direction_last4=count4,
                valid_observations_last4=4,
                current_same_direction=current,
                rolling_4q_same_direction=rolling,
                historical_percentile_inclusive_pct=None,
                numeric_history_eligible=False,
            )
            rows.append(
                {
                    **asdict(evidence),
                    "decision_rank": DECISION_RANK[evidence.decision],
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["rolling_4q_same_direction", "same_direction_last4"], kind="stable"
    ).reset_index(drop=True)


def _nullable_bool(value: Any) -> bool | None:
    return None if pd.isna(value) else bool(value)


def _last_window(values: pd.Series, length: int) -> tuple[int, int]:
    tail = values.tail(length)
    valid = tail.dropna()
    return int(valid.astype(bool).sum()), int(len(valid))


def build_rule_sensitivity(
    candidate_series: pd.DataFrame,
    config: Mapping[str, Any] | None = None,
    *,
    target_period_code: str = TARGET_PERIOD_CODE,
) -> pd.DataFrame:
    """Compare frozen-v2 decisions with the additive corrected rules."""
    stage2 = dict(config or load_stage2_config())
    legacy = build_historical_robustness(candidate_series, stage2).set_index(
        "candidate_id"
    )
    boolean = build_corrected_boolean_signals(
        candidate_series,
        flat_including_capex_abs_yoy_pct_max=float(
            stage2["candidate_rules"]["C"][
                "flat_including_capex_abs_yoy_pct_max"
            ]
        ),
    )
    rows: list[dict[str, Any]] = []
    for candidate_id in sorted(candidate_series["candidate_id"].unique()):
        source = candidate_series.loc[
            candidate_series["candidate_id"].eq(candidate_id)
            & candidate_series["period_code"].astype(int).le(int(target_period_code))
        ].sort_values("period_ordinal", kind="stable")
        target = source.loc[source["period_code"].eq(target_period_code)]
        if len(target) != 1:
            raise ValueError(
                f"Expected one target row for candidate {candidate_id}; found {len(target)}"
            )
        legacy_target = target.iloc[0]
        if candidate_id in BOOLEAN_CONDITIONS:
            corrected = boolean.loc[
                boolean["candidate_id"].eq(candidate_id)
                & boolean["period_code"].astype(int).le(int(target_period_code))
            ].sort_values("period_ordinal", kind="stable")
            corrected_target = corrected.loc[
                corrected["period_code"].eq(target_period_code)
            ].iloc[0]
            signal = corrected["corrected_same_direction"]
            indicator_values = corrected["corrected_indicator_value"]
            current_indicator = corrected_target["corrected_indicator_value"]
            current_same = _nullable_bool(
                corrected_target["corrected_same_direction"]
            )
            rolling_same = _nullable_bool(
                corrected_target["corrected_rolling_4q_same_direction"]
            )
            corrected_indicator_id = corrected_target["corrected_indicator_id"]
            corrected_definition = corrected_target[
                "corrected_indicator_definition"
            ]
            corrected_unit = "boolean_condition"
            position = {
                "historical_percentile_inclusive_pct": None,
                "percentile_numerator_le_current": None,
                "percentile_denominator_non_missing": None,
                "percentile_method": "NOT_APPLICABLE_BOOLEAN_CONDITION",
                "percentile_formula": "NOT_APPLICABLE",
                "percentile_tie_policy": "NOT_APPLICABLE",
                "percentile_reference_includes_current": None,
                "percentile_missing_policy": "NOT_APPLICABLE",
                "numeric_history_eligible": False,
            }
        else:
            valid = source["indicator_status"].eq("CALCULABLE")
            signal = source["same_direction"].astype("boolean").where(valid, pd.NA)
            indicator_values = pd.to_numeric(
                source["pattern_signal_value"], errors="coerce"
            ).where(valid)
            current_indicator = legacy_target["indicator_value"]
            current_same = (
                bool(legacy_target["same_direction"])
                if legacy_target["indicator_status"] == "CALCULABLE"
                else None
            )
            rolling_same = (
                bool(legacy_target["rolling_4q_same_direction"])
                if legacy_target["rolling_4q_indicator_status"] == "CALCULABLE"
                else None
            )
            corrected_indicator_id = legacy_target["indicator_id"]
            corrected_definition = legacy_target["indicator_definition"]
            corrected_unit = legacy_target["indicator_unit"]
            position = {
                **inclusive_empirical_percentile(
                    indicator_values,
                    legacy_target["pattern_signal_value"],
                    reference_includes_current=True,
                ),
                "numeric_history_eligible": True,
            }
        count4, valid4 = _last_window(signal, 4)
        count8, valid8 = _last_window(signal, 8)
        evidence = classify_corrected_pattern(
            same_direction_last4=count4,
            valid_observations_last4=valid4,
            current_same_direction=current_same,
            rolling_4q_same_direction=rolling_same,
            historical_percentile_inclusive_pct=position[
                "historical_percentile_inclusive_pct"
            ],
            numeric_history_eligible=bool(position["numeric_history_eligible"]),
        )
        legacy_row = legacy.loc[candidate_id]
        rows.append(
            {
                "candidate_id": candidate_id,
                "target_period_code": target_period_code,
                "legacy_rule_id": LEGACY_RULE_ID,
                "legacy_indicator_id": legacy_target["indicator_id"],
                "legacy_indicator_unit": legacy_target["indicator_unit"],
                "legacy_current_indicator_value": legacy_target["indicator_value"],
                "legacy_historical_percentile": legacy_row[
                    "historical_percentile"
                ],
                "legacy_pattern_decision": legacy_row["pattern_decision"],
                "legacy_rule_json": json.dumps(
                    legacy_rule_snapshot(stage2),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "corrected_rule_id": CORRECTED_RULE_ID,
                "corrected_indicator_id": corrected_indicator_id,
                "corrected_indicator_unit": corrected_unit,
                "corrected_current_indicator_value": current_indicator,
                "corrected_indicator_definition": corrected_definition,
                "corrected_same_direction_last4": count4,
                "corrected_same_direction_last8": count8,
                "corrected_valid_observations_last4": valid4,
                "corrected_valid_observations_last8": valid8,
                "corrected_current_same_direction": current_same,
                "corrected_rolling_4q_same_direction": rolling_same,
                **position,
                "corrected_pattern_decision": evidence.decision,
                "decision_changed": legacy_row["pattern_decision"]
                != evidence.decision,
                "sensitivity_status": (
                    "DECISION_CHANGED_UNDER_CORRECTED_RULE"
                    if legacy_row["pattern_decision"] != evidence.decision
                    else "DECISION_STABLE_UNDER_CORRECTED_RULE"
                ),
                "frozen_v2_mutation": "NONE",
            }
        )
    return pd.DataFrame(rows).sort_values("candidate_id", kind="stable").reset_index(
        drop=True
    )
