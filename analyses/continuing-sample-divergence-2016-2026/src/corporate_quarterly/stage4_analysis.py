"""Bounded Stage 4 sensitivity analysis for the 2026Q1 public article.

This module only re-analyses the frozen regular-series and continuing-sample
rates already loaded by :mod:`stage2_continuing_sample`.  It does not fetch
data, write output files, or modify a prior release.

The comparisons are descriptive.  In particular, the two series need not be
two measurements of one common true value: entry and exit, response-
continuation conditions, estimation weights, non-response imputation, and
population composition can all differ.  Missing or non-comparable cells remain
explicit and are never replaced by zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

import numpy as np
import pandas as pd

from .constants import PROJECT_ROOT
from .stage2_continuing_sample import build_continuing_sample_analysis

if TYPE_CHECKING:  # pragma: no cover
    from .stage2_continuing_sample import ContinuingSampleAnalysis


FOCUS_CAPITAL_CODE = "19"
CAPITAL_CODES = ("19", "24", "25")
CAPITAL_SCOPE_NAMES = {
    "19": "資本金1千万円以上1億円未満層",
    "24": "資本金1億円以上10億円未満層",
    "25": "資本金10億円以上層",
}
CENSUS_THRESHOLD_YEN = 500_000_000
CENSUS_THRESHOLD_LABEL_JA = "資本金5億円以上"
EXPLORATORY_BACKTEST_STATUS = (
    "POST_HOC_EXPLORATORY_BACKTEST_RULE_DEFINED_AFTER_2026Q1"
)
SAMPLE_ERROR_STATUS = (
    "NOT_QUANTIFIED_OPERATING_AND_ORDINARY_PROFIT_STANDARD_ERRORS_"
    "NOT_CALCULATED_BY_MOF"
)
ROUNDING_HALF_WIDTH_PP = 0.05
ROUNDING_AMBIGUITY_THRESHOLD_PP = 0.10
DEADBANDS_PCT = (0.5, 1.0, 2.0, 3.0)
NEAR_ZERO_BASE_FLAG = "NEAR_ZERO_BASE"


# The 5-oku-yen boundary and rotation notes describe the official survey
# design.  They do not assign causality to the observed mismatch gradient.
CAPITAL_DESIGN: dict[str, dict[str, Any]] = {
    "19": {
        "census_sample_design_ja": "標本調査（資本金5億円未満）",
        "rotation_status": "YES",
        "rotation_note_ja": "標本調査部分で、毎年度おおむね半数を入れ替える抽出替えの対象",
    },
    "24": {
        "census_sample_design_ja": (
            "標本・全数混在（1億円以上5億円未満は標本、"
            "5億円以上10億円未満は全数）"
        ),
        "rotation_status": "PARTIAL",
        "rotation_note_ja": (
            "5億円未満部分は抽出替えの対象、5億円以上部分は全数で抽出替えなし"
        ),
    },
    "25": {
        "census_sample_design_ja": "全数調査（資本金10億円以上）",
        "rotation_status": "NO",
        "rotation_note_ja": "全数調査部分で抽出替えなし",
    },
}

DESIGN_INTERPRETATION_NOTE = (
    "資本金階層別の不一致勾配は調査設計と整合的だが、"
    "調査方式が原因であること又は全数・標本の別で決まることを示さない。"
)
SERIES_COMPARABILITY_NOTE = (
    "通常系列と継続標本系列は、企業の参入・退出、回答継続条件、推計用乗率、"
    "未回答補完、母集団構成の違いを含み得るため、いずれかを基準系列として優越させない。"
)


@dataclass(frozen=True)
class Stage4Analysis:
    """All bounded analytical tables needed by the v3.1 publication layer."""

    headline_2x2: pd.DataFrame
    mismatch_heatmap: pd.DataFrame
    decision_margin_summary: pd.DataFrame
    rounding_sensitivity: pd.DataFrame
    deadband_sensitivity: pd.DataFrame
    near_zero_base_flags: pd.DataFrame


def _capital_subset(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.loc[frame["breakdown"].eq("capital_size")].copy()
    result["category_code"] = result["category_code"].astype(str)
    result = result.loc[result["category_code"].isin(CAPITAL_CODES)].copy()
    return result


def _require_41_quarters(frame: pd.DataFrame, *, keys: Iterable[str]) -> None:
    counts = frame.groupby(list(keys), dropna=False)["period_code"].nunique()
    bad = counts.loc[counts.ne(41)]
    if not bad.empty:
        raise ValueError(f"Expected 41 quarters for every group; observed {bad.to_dict()}")


def build_headline_2x2(
    continuing: "ContinuingSampleAnalysis",
) -> pd.DataFrame:
    """Return the four cells of the exploratory capital-headline comparison."""
    history = continuing.capital_headline_history.copy()
    regular = history["regular_headline_supported"].astype("boolean")
    reference = history["continuing_headline_supported"].astype("boolean")
    comparable = regular.notna() & reference.notna()
    denominator = int(comparable.sum())
    not_comparable = int((~comparable).sum())
    regular_total = int((regular.loc[comparable] == True).sum())  # noqa: E712
    continuing_total = int((reference.loc[comparable] == True).sum())  # noqa: E712

    cells = (
        ("REGULAR_ONLY", True, False),
        ("CONTINUING_ONLY", False, True),
        ("BOTH", True, True),
        ("NEITHER", False, False),
    )
    rows: list[dict[str, Any]] = []
    for cell_id, regular_value, continuing_value in cells:
        count = int(
            (
                comparable
                & (regular == regular_value)
                & (reference == continuing_value)
            ).sum()
        )
        rows.append(
            {
                "cell_id": cell_id,
                "regular_headline_supported": regular_value,
                "continuing_headline_supported": continuing_value,
                "quarter_count": count,
                "denominator_quarters": denominator,
                "share_pct": count / denominator * 100.0 if denominator else np.nan,
                "regular_supported_total": regular_total,
                "continuing_supported_total": continuing_total,
                "not_comparable_quarters": not_comparable,
                "exploratory_backtest_status": EXPLORATORY_BACKTEST_STATUS,
                "comparison_status": (
                    "COMPARABLE_BOOLEAN_PAIR"
                    if denominator
                    else "NO_COMPARABLE_QUARTERS"
                ),
                "series_comparability_note": SERIES_COMPARABILITY_NOTE,
            }
        )
    return pd.DataFrame(rows)


def build_decision_margin_summary(
    continuing: "ContinuingSampleAnalysis",
) -> pd.DataFrame:
    """Summarise signal width and the distance between the two growth gaps.

    ``continuing_decision_margin_abs_gap_median_pct`` is the median absolute
    difference between the published continuing-sample operating-profit and
    sales YoY rates.  ``cross_series_growth_gap_divergence_median_pp`` is the
    median absolute difference between that growth gap and its regular-series
    counterpart.  Neither quantity is an operating-margin percentage-point
    change.
    """
    relative = _capital_subset(continuing.relative_margin_comparison)
    _require_41_quarters(relative, keys=("category_code",))
    rows: list[dict[str, Any]] = []
    for capital_code in CAPITAL_CODES:
        frame = relative.loc[relative["category_code"].eq(capital_code)].copy()
        continuing_gap = frame["continuing_relative_growth_gap_pp"]
        regular_gap = frame["regular_relative_growth_gap_pp"]
        valid = continuing_gap.notna() & regular_gap.notna()
        rows.append(
            {
                "capital_code": capital_code,
                "capital_scope_ja": CAPITAL_SCOPE_NAMES[capital_code],
                "total_quarters": len(frame),
                "comparable_quarters": int(valid.sum()),
                "noncomparable_quarters": int((~valid).sum()),
                "continuing_decision_margin_abs_gap_median_pct": (
                    float(continuing_gap.loc[valid].abs().median())
                    if valid.any()
                    else np.nan
                ),
                "cross_series_growth_gap_divergence_median_pp": (
                    float((continuing_gap.loc[valid] - regular_gap.loc[valid]).abs().median())
                    if valid.any()
                    else np.nan
                ),
                "decision_margin_definition": (
                    "median(abs(continuing operating-profit YoY pct - "
                    "continuing sales YoY pct))"
                ),
                "divergence_definition": (
                    "median(abs((continuing operating-profit YoY - sales YoY) - "
                    "(regular operating-profit YoY - sales YoY)))"
                ),
                "operating_margin_level_status": "NOT_PUBLISHED_FOR_CONTINUING_SAMPLE",
                "large_amplitude_explanation_status": "NOT_SUPPORTED_DESCRIPTIVELY",
                "large_amplitude_explanation_note_ja": (
                    "大規模資本金層は変化幅が大きいため一致する、という説明を"
                    "この判定余裕中央値は支持しない。因果関係の検証ではない。"
                ),
            }
        )
    return pd.DataFrame(rows)


def build_mismatch_heatmap(
    continuing: "ContinuingSampleAnalysis",
    decision_margin_summary: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build capital-tier by metric mismatch frequencies and design notes."""
    if decision_margin_summary is None:
        decision_margin_summary = build_decision_margin_summary(continuing)
    medians = decision_margin_summary.set_index("capital_code")

    sign = _capital_subset(continuing.sign_reversal_frequency)
    sign = sign.loc[sign["metric_id"].isin(("sales", "operating_profit"))]
    relative = _capital_subset(continuing.relative_margin_reversal_frequency)

    rows: list[dict[str, Any]] = []
    for capital_code in CAPITAL_CODES:
        design = CAPITAL_DESIGN[capital_code]
        margin = relative.loc[relative["category_code"].eq(capital_code)]
        if len(margin) != 1:
            raise ValueError(f"Expected one margin-frequency row for capital {capital_code}")
        margin_row = margin.iloc[0]
        metric_rows: list[dict[str, Any]] = [
            {
                "metric_id": "relative_margin_direction",
                "metric_label_ja": "利益率方向",
                "mismatch_count": int(margin_row["direction_reversal_count"]),
                "comparable_quarters": int(
                    margin_row["comparable_direction_quarters"]
                ),
                "total_quarters": int(margin_row["total_quarters"]),
                "mismatch_rate_pct": float(
                    margin_row["direction_reversal_rate_pct"]
                ),
                "noncomparable_quarters": int(
                    margin_row["not_comparable_or_flat_quarters"]
                ),
                "comparison_status": str(margin_row["frequency_status"]),
                "metric_interpretation_note": (
                    "売上高前年比と営業利益前年比から推定した利益率の相対変化方向。"
                    "継続標本の利益率水準又はポイント変化ではない。"
                ),
            }
        ]
        for metric_id, label in (
            ("operating_profit", "営業利益前年比の符号"),
            ("sales", "売上高前年比の符号"),
        ):
            selected = sign.loc[
                sign["category_code"].eq(capital_code)
                & sign["metric_id"].eq(metric_id)
            ]
            if len(selected) != 1:
                raise ValueError(
                    f"Expected one sign-frequency row for capital {capital_code}, {metric_id}"
                )
            source = selected.iloc[0]
            metric_rows.append(
                {
                    "metric_id": metric_id,
                    "metric_label_ja": label,
                    "mismatch_count": int(source["sign_reversal_count"]),
                    "comparable_quarters": int(
                        source["comparable_nonzero_sign_quarters"]
                    ),
                    "total_quarters": int(source["total_quarters"]),
                    "mismatch_rate_pct": float(source["sign_reversal_rate_pct"]),
                    "noncomparable_quarters": int(
                        source["zero_involved_quarters"]
                        + source["not_comparable_quarters"]
                    ),
                    "comparison_status": str(source["frequency_status"]),
                    "metric_interpretation_note": (
                        "非ゼロの前年比符号が反対となる四半期。"
                        "ゼロ又は計算不能は分母から除き、0補完しない。"
                    ),
                }
            )
        for metric_row in metric_rows:
            rows.append(
                {
                    "capital_code": capital_code,
                    "capital_scope_ja": CAPITAL_SCOPE_NAMES[capital_code],
                    **metric_row,
                    **design,
                    "census_threshold_yen": CENSUS_THRESHOLD_YEN,
                    "census_threshold_label_ja": CENSUS_THRESHOLD_LABEL_JA,
                    "design_interpretation_note": DESIGN_INTERPRETATION_NOTE,
                    "continuing_decision_margin_abs_gap_median_pct": float(
                        medians.loc[
                            capital_code,
                            "continuing_decision_margin_abs_gap_median_pct",
                        ]
                    ),
                    "cross_series_growth_gap_divergence_median_pp": float(
                        medians.loc[
                            capital_code,
                            "cross_series_growth_gap_divergence_median_pp",
                        ]
                    ),
                    "large_amplitude_explanation_status": str(
                        medians.loc[
                            capital_code,
                            "large_amplitude_explanation_status",
                        ]
                    ),
                    "exploratory_backtest_status": EXPLORATORY_BACKTEST_STATUS,
                    "sample_error_status": SAMPLE_ERROR_STATUS,
                    "series_comparability_note": SERIES_COMPARABILITY_NOTE,
                }
            )
    return pd.DataFrame(rows)


def build_rounding_sensitivity(
    continuing: "ContinuingSampleAnalysis",
    *,
    capital_code: str = FOCUS_CAPITAL_CODE,
    half_width_pp: float = ROUNDING_HALF_WIDTH_PP,
    ambiguity_threshold_pp: float = ROUNDING_AMBIGUITY_THRESHOLD_PP,
) -> pd.DataFrame:
    """Test whether one-decimal published-rate rounding can determine direction.

    This is intentionally a rounding-only interval check.  It does not quantify
    sampling error, and a determined rounding interval is never labelled
    "certain".
    """
    relative = _capital_subset(continuing.relative_margin_comparison)
    frame = relative.loc[relative["category_code"].eq(str(capital_code))].copy()
    _require_41_quarters(frame, keys=("category_code",))
    rows: list[dict[str, Any]] = []
    for source in frame.sort_values("period_ordinal", kind="stable").itertuples(
        index=False
    ):
        sales = source.continuing_sales_yoy_pct
        operating = source.continuing_operating_profit_yoy_pct
        if pd.isna(sales) or pd.isna(operating):
            rows.append(
                {
                    "period_code": str(source.period_code),
                    "period": source.period,
                    "period_end": source.period_end,
                    "capital_code": str(capital_code),
                    "capital_scope_ja": CAPITAL_SCOPE_NAMES[str(capital_code)],
                    "continuing_sales_yoy_pct": sales,
                    "continuing_operating_profit_yoy_pct": operating,
                    "relative_growth_gap_pp": np.nan,
                    "absolute_decision_margin_pp": np.nan,
                    "rounded_sales_low_pct": np.nan,
                    "rounded_sales_high_pct": np.nan,
                    "rounded_operating_low_pct": np.nan,
                    "rounded_operating_high_pct": np.nan,
                    "relative_growth_gap_low_pp": np.nan,
                    "relative_growth_gap_high_pp": np.nan,
                    "rounding_direction_status": "NOT_CALCULABLE_MISSING_RATE",
                    "margin_direction": "NOT_CALCULABLE",
                    "is_ambiguous_by_rounding": pd.NA,
                    "rounding_half_width_pp": half_width_pp,
                    "ambiguity_threshold_pp": ambiguity_threshold_pp,
                    "sample_error_status": SAMPLE_ERROR_STATUS,
                    "rounding_interpretation_note": (
                        "丸め幅だけの感応度であり、標本誤差は別途未定量。"
                    ),
                }
            )
            continue

        sales = float(sales)
        operating = float(operating)
        gap = operating - sales
        ambiguous = abs(gap) <= ambiguity_threshold_pp + 1e-12
        gap_low = (operating - half_width_pp) - (sales + half_width_pp)
        gap_high = (operating + half_width_pp) - (sales - half_width_pp)
        if ambiguous:
            status = "NOT_DETERMINED_BY_ROUNDING"
        elif gap_low > 0:
            status = "DETERMINED_UP_BY_ROUNDING_INTERVAL"
        elif gap_high < 0:
            status = "DETERMINED_DOWN_BY_ROUNDING_INTERVAL"
        else:  # defensive: explicit threshold and interval should agree
            raise ValueError(
                f"Rounding rule and interval disagree for {source.period_code}: {gap}"
            )
        direction = "UP" if gap > 0 else ("DOWN" if gap < 0 else "FLAT")
        rows.append(
            {
                "period_code": str(source.period_code),
                "period": source.period,
                "period_end": source.period_end,
                "capital_code": str(capital_code),
                "capital_scope_ja": CAPITAL_SCOPE_NAMES[str(capital_code)],
                "continuing_sales_yoy_pct": sales,
                "continuing_operating_profit_yoy_pct": operating,
                "relative_growth_gap_pp": gap,
                "absolute_decision_margin_pp": abs(gap),
                "rounded_sales_low_pct": sales - half_width_pp,
                "rounded_sales_high_pct": sales + half_width_pp,
                "rounded_operating_low_pct": operating - half_width_pp,
                "rounded_operating_high_pct": operating + half_width_pp,
                "relative_growth_gap_low_pp": gap_low,
                "relative_growth_gap_high_pp": gap_high,
                "rounding_direction_status": status,
                "margin_direction": direction,
                "is_ambiguous_by_rounding": ambiguous,
                "rounding_half_width_pp": half_width_pp,
                "ambiguity_threshold_pp": ambiguity_threshold_pp,
                "sample_error_status": SAMPLE_ERROR_STATUS,
                "rounding_interpretation_note": (
                    "丸め幅だけの感応度であり、標本誤差は別途未定量。"
                ),
            }
        )
    result = pd.DataFrame(rows)
    result["is_ambiguous_by_rounding"] = pd.array(
        result["is_ambiguous_by_rounding"], dtype="boolean"
    )
    return result


def build_deadband_sensitivity(
    continuing: "ContinuingSampleAnalysis",
    *,
    deadbands_pct: Iterable[float] = DEADBANDS_PCT,
) -> pd.DataFrame:
    """Retain quarters where both inferred relative changes exceed ``d``.

    The deadband unit is percent relative operating-margin change inferred from
    sales and operating-profit YoY rates.  It is not an absolute operating-
    margin percentage-point difference.
    """
    relative = _capital_subset(continuing.relative_margin_comparison)
    _require_41_quarters(relative, keys=("category_code",))
    rows: list[dict[str, Any]] = []
    for capital_code in CAPITAL_CODES:
        frame = relative.loc[relative["category_code"].eq(capital_code)].copy()
        regular_change = frame["regular_implied_relative_margin_change_pct"]
        continuing_change = frame[
            "continuing_implied_relative_margin_change_pct"
        ]
        reversal = frame["relative_margin_direction_reversal"].astype("boolean")
        input_comparable = (
            regular_change.notna() & continuing_change.notna() & reversal.notna()
        )
        for deadband in deadbands_pct:
            d = float(deadband)
            retained = (
                input_comparable
                & regular_change.abs().gt(d)
                & continuing_change.abs().gt(d)
            )
            denominator = int(retained.sum())
            mismatch_count = int((reversal.loc[retained] == True).sum())  # noqa: E712
            rows.append(
                {
                    "capital_code": capital_code,
                    "capital_scope_ja": CAPITAL_SCOPE_NAMES[capital_code],
                    "deadband_pct": d,
                    "total_quarters": len(frame),
                    "input_comparable_quarters": int(input_comparable.sum()),
                    "retained_quarters": denominator,
                    "excluded_by_deadband_quarters": int(
                        (input_comparable & ~retained).sum()
                    ),
                    "not_comparable_quarters": int((~input_comparable).sum()),
                    "mismatch_count": mismatch_count,
                    "mismatch_rate_pct": (
                        mismatch_count / denominator * 100.0
                        if denominator
                        else np.nan
                    ),
                    "deadband_rule": (
                        "abs(regular inferred relative margin change)>d AND "
                        "abs(continuing inferred relative margin change)>d"
                    ),
                    "unit": (
                        "estimated_relative_margin_change_pct (%) - "
                        "not operating-margin percentage points"
                    ),
                    "comparison_status": (
                        "CALCULABLE" if denominator else "NO_RETAINED_QUARTERS"
                    ),
                    "sample_error_status": SAMPLE_ERROR_STATUS,
                    "operating_margin_level_status": (
                        "CONTINUING_SAMPLE_LEVEL_NOT_PUBLISHED_DIRECTION_ONLY"
                    ),
                }
            )
    return pd.DataFrame(rows)


def build_near_zero_base_sensitivity(
    continuing: "ContinuingSampleAnalysis",
    *,
    capital_code: str = FOCUS_CAPITAL_CODE,
) -> pd.DataFrame:
    """Flag >100% continuing-profit rates within a fixed 41-quarter window.

    ``NEAR_ZERO_BASE`` is the user-specified mechanical flag name.  The rate
    alone does not establish a low or near-zero base.  The sensitivity is an
    event-attribution check with the original 41-quarter denominator frozen;
    it is not a row-deletion re-estimate (which would have denominator 38).
    """
    relative = _capital_subset(continuing.relative_margin_comparison)
    frame = relative.loc[relative["category_code"].eq(str(capital_code))].copy()
    _require_41_quarters(frame, keys=("category_code",))
    headline = continuing.capital_headline_history.copy()
    headline["period_code"] = headline["period_code"].astype(str)
    frame["period_code"] = frame["period_code"].astype(str)
    flagged = frame.loc[
        frame["continuing_operating_profit_yoy_pct"].abs().gt(100.0)
    ].copy()
    flagged = flagged.merge(
        headline[["period_code", "headline_reversal"]],
        on="period_code",
        how="left",
        validate="one_to_one",
    )
    full_margin_count = int(
        (frame["relative_margin_direction_reversal"].astype("boolean") == True).sum()  # noqa: E712
    )
    full_headline_count = int(
        (
            continuing.capital_headline_history["headline_reversal"].astype(
                "boolean"
            )
            == True  # noqa: E712
        ).sum()
    )
    flagged_margin_count = int(
        (flagged["relative_margin_direction_reversal"].astype("boolean") == True).sum()  # noqa: E712
    )
    flagged_headline_count = int(
        (flagged["headline_reversal"].astype("boolean") == True).sum()  # noqa: E712
    )
    rows: list[dict[str, Any]] = []
    for source in flagged.sort_values("period_ordinal", kind="stable").itertuples(
        index=False
    ):
        rows.append(
            {
                "period_code": str(source.period_code),
                "period": source.period,
                "capital_code": str(capital_code),
                "capital_scope_ja": CAPITAL_SCOPE_NAMES[str(capital_code)],
                "continuing_operating_profit_yoy_pct": float(
                    source.continuing_operating_profit_yoy_pct
                ),
                "mechanical_flag": NEAR_ZERO_BASE_FLAG,
                "mechanical_trigger": (
                    "abs(continuing_operating_profit_yoy_pct)>100"
                ),
                "extreme_yoy_rate_gt_100": True,
                "relative_margin_direction_reversal": bool(
                    source.relative_margin_direction_reversal
                ),
                "headline_reversal": bool(source.headline_reversal),
                "flagged_margin_reversal_count": flagged_margin_count,
                "flagged_headline_reversal_count": flagged_headline_count,
                "margin_reversal_count_fixed_window_before": full_margin_count,
                "margin_reversal_count_fixed_window_after_attribution": (
                    full_margin_count - flagged_margin_count
                ),
                "headline_reversal_count_fixed_window_before": full_headline_count,
                "headline_reversal_count_fixed_window_after_attribution": (
                    full_headline_count - flagged_headline_count
                ),
                "fixed_window_denominator_quarters": len(frame),
                "row_deletion_denominator_quarters": len(frame) - len(flagged),
                "sensitivity_method": (
                    "FIXED_41_QUARTER_EVENT_ATTRIBUTION_NOT_ROW_DELETION"
                ),
                "causal_interpretation_status": "NOT_ESTABLISHED_BY_RATE_ALONE",
                "flag_interpretation_note": (
                    "NEAR_ZERO_BASEは指定された機械的フラグ名にすぎず、"
                    "EXTREME_YOY_RATE_GT_100だけから低ベース又はゼロ近傍とは断定しない。"
                ),
            }
        )
    return pd.DataFrame(rows)


def build_stage4_analysis(
    project_root: Path = PROJECT_ROOT,
    *,
    continuing: "ContinuingSampleAnalysis | None" = None,
) -> Stage4Analysis:
    """Build every v3.1 analytical table without performing any writes."""
    if continuing is None:
        continuing = build_continuing_sample_analysis(project_root)
    decision = build_decision_margin_summary(continuing)
    return Stage4Analysis(
        headline_2x2=build_headline_2x2(continuing),
        mismatch_heatmap=build_mismatch_heatmap(continuing, decision),
        decision_margin_summary=decision,
        rounding_sensitivity=build_rounding_sensitivity(continuing),
        deadband_sensitivity=build_deadband_sensitivity(continuing),
        near_zero_base_flags=build_near_zero_base_sensitivity(continuing),
    )
