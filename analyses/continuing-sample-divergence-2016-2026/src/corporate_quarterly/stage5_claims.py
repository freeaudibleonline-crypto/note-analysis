"""Claims, unit registry, and correction ledger for the 2026Q1 v3.2 release.

This module deliberately keeps the numerical lineage one-way::

    canonical CSV -> claims

The six current-quarter claims are therefore derived from the frozen v3
``main_vs_continuing_sample.csv`` rather than from prose or display targets.
Display targets are used only as a fail-closed reproduction check after the
source values and cross-series differences have been computed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


RELEASE_V3_2 = "2026Q1_v3_2"
CANONICAL_RELATIVE_PATH = Path("outputs/2026Q1_v3/main_vs_continuing_sample.csv")
V3_1_CLAIMS_RELATIVE_PATH = Path("outputs/2026Q1_v3_1/claims_v3_1.csv")

ARTICLE_TITLE_V3_1 = (
    "食い違いは小規模資本金層に集中していた"
    "――法人企業統計、二つの推計を41四半期並べる"
)
ARTICLE_TITLE_V3_2 = (
    "利益率方向の食い違いは小規模資本金層に集中していた"
    "――法人企業統計、二つの推計を41四半期比べる"
)

NEW_2026Q1_CLAIM_IDS = (
    "V32-2026Q1-SMALL-REGULAR-SALES-YOY",
    "V32-2026Q1-SMALL-REGULAR-OPERATING-PROFIT-YOY",
    "V32-2026Q1-SMALL-CONTINUING-SALES-YOY",
    "V32-2026Q1-SMALL-CONTINUING-OPERATING-PROFIT-YOY",
    "V32-2026Q1-SMALL-SALES-CROSS-SERIES-GAP",
    "V32-2026Q1-SMALL-OPERATING-PROFIT-CROSS-SERIES-GAP",
)

DECISION_MARGIN_CLAIM_IDS = (
    "V31-SMALL-DECISION-MARGIN-MEDIAN",
    "V31-MIDDLE-DECISION-MARGIN-MEDIAN",
    "V31-LARGE-DECISION-MARGIN-MEDIAN",
)

_DECISION_MARGIN_EXPECTED = {
    "V31-SMALL-DECISION-MARGIN-MEDIAN": (11.3, "11.3ポイント"),
    "V31-MIDDLE-DECISION-MARGIN-MEDIAN": (9.0, "9.0ポイント"),
    "V31-LARGE-DECISION-MARGIN-MEDIAN": (8.5, "8.5ポイント"),
}

# These are reproduction gates, not sources for claim values.  Values are first
# read/calculated from the canonical CSV and only then compared after rounding.
_EXPECTED_2026Q1_DISPLAY_NUMBERS = {
    "regular_sales_yoy": 2.1,
    "regular_operating_profit_yoy": -1.9,
    "continuing_sales_yoy": 2.5,
    "continuing_operating_profit_yoy": 6.0,
    "sales_cross_series_gap": 0.4,
    "operating_profit_cross_series_gap": 7.9,
}

CANONICAL_UNIT_BY_METRIC_TYPE: dict[str, str] = {
    "yoy_growth_rate": "percent",
    "difference_between_growth_rates": "percentage_points",
    "direction_mismatch_rate": "percent",
    "implied_relative_margin_change": "percent",
    "deadband_threshold": "percent",
    "count": "count",
    "currency": "oku_yen",
    # Additional type needed by the pre-existing five-hundred-million-yen
    # survey-design boundary claim.  It is not an amount measured in 億円.
    "currency_threshold_yen": "yen",
}

_COUNT_METRICS = {
    "continuing-total",
    "extreme_yoy_flagged_mismatch_count",
    "extreme_yoy_rate_gt_100_count",
    "headline_2x2_both",
    "headline_2x2_continuing_only",
    "headline_2x2_neither",
    "headline_2x2_regular_only",
    "regular-total",
    "rounding_ambiguous_count",
}
_DIRECTION_MISMATCH_METRICS = {
    "composite_headline_support_mismatch",
    "deadband_margin_direction_mismatch",
    "operating_profit_mismatch",
    "relative_margin_direction_mismatch",
    "sales_mismatch",
}
_DIFFERENCE_METRICS = {
    "decision-margin-median",
    "minimum_rounding_decision_margin",
    "published_rounding_half_width",
    "rounding_ambiguity_threshold",
    "series-divergence-median",
    "sales_cross_series_growth_rate_gap",
    "operating_profit_cross_series_growth_rate_gap",
}
_YOY_METRICS = {
    "sales_yoy_growth_rate",
    "operating_profit_yoy_growth_rate",
    "extreme_yoy_review_threshold",
}


@dataclass(frozen=True)
class CurrentQuarterSmallValues:
    """Unrounded values selected or derived from the canonical comparison CSV."""

    regular_sales_yoy: float
    regular_operating_profit_yoy: float
    continuing_sales_yoy: float
    continuing_operating_profit_yoy: float
    sales_cross_series_gap: float
    operating_profit_cross_series_gap: float
    source_rows: Mapping[str, int]


@dataclass(frozen=True)
class Stage5ClaimArtifacts:
    claims_v3_2: pd.DataFrame
    unit_registry: dict[str, Any]
    claim_corrections_v3_2: pd.DataFrame
    expected_value_changes_v3_2: pd.DataFrame
    current_quarter_values: CurrentQuarterSmallValues


def _as_bool(value: object) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _metric_type(metric_id: str) -> str:
    if metric_id in _COUNT_METRICS:
        return "count"
    if metric_id in _DIRECTION_MISMATCH_METRICS:
        return "direction_mismatch_rate"
    if metric_id in _DIFFERENCE_METRICS:
        return "difference_between_growth_rates"
    if metric_id in _YOY_METRICS:
        return "yoy_growth_rate"
    if metric_id == "regular_series_census_threshold":
        return "currency_threshold_yen"
    raise ValueError(f"unregistered metric_id: {metric_id}")


def _canonical_unit(metric_id: str) -> str:
    return CANONICAL_UNIT_BY_METRIC_TYPE[_metric_type(metric_id)]


def extract_2026q1_small_values(canonical: pd.DataFrame) -> CurrentQuarterSmallValues:
    """Select code 19 in 2026Q1 and compute both absolute cross-series gaps.

    The function accepts an in-memory frame to make lineage tests possible.  It
    never substitutes the expected publication values for missing source data.
    """

    required = {
        "period_code",
        "breakdown",
        "category_code",
        "metric_id",
        "regular_yoy_pct",
        "continuing_yoy_pct",
        "regular_current_value_oku_yen",
        "regular_prior_value_oku_yen",
        "yoy_difference_pp",
    }
    missing = required - set(canonical)
    if missing:
        raise ValueError(f"canonical comparison CSV lacks columns: {sorted(missing)}")

    period = pd.to_numeric(canonical["period_code"], errors="coerce")
    capital = pd.to_numeric(canonical["category_code"], errors="coerce")
    target = canonical.loc[
        period.eq(20261)
        & canonical["breakdown"].astype(str).eq("capital_size")
        & capital.eq(19)
        & canonical["metric_id"].astype(str).isin({"sales", "operating_profit"})
    ].copy()
    target["_source_row_number"] = target.index.astype(int)
    counts = target["metric_id"].astype(str).value_counts().to_dict()
    if counts != {"sales": 1, "operating_profit": 1}:
        raise ValueError(
            "canonical comparison must contain exactly one 2026Q1 code-19 row "
            f"for sales and operating_profit; observed={counts}"
        )
    target = target.set_index("metric_id", drop=False)
    numeric_columns = (
        "regular_yoy_pct",
        "continuing_yoy_pct",
        "regular_current_value_oku_yen",
        "regular_prior_value_oku_yen",
        "yoy_difference_pp",
    )
    for column in numeric_columns:
        values = pd.to_numeric(target[column], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
            raise ValueError(f"canonical target rows contain invalid {column}")
        target[column] = values

    # Recheck the regular rates against the underlying canonical amount fields.
    calculated_regular = 100 * (
        target["regular_current_value_oku_yen"]
        / target["regular_prior_value_oku_yen"]
        - 1
    )
    if not np.allclose(
        calculated_regular.to_numpy(dtype=float),
        target["regular_yoy_pct"].to_numpy(dtype=float),
        rtol=0,
        atol=1e-9,
    ):
        raise ValueError("regular_yoy_pct does not reconcile to canonical amount fields")

    regular_sales = float(target.loc["sales", "regular_yoy_pct"])
    regular_operating = float(target.loc["operating_profit", "regular_yoy_pct"])
    continuing_sales = float(target.loc["sales", "continuing_yoy_pct"])
    continuing_operating = float(
        target.loc["operating_profit", "continuing_yoy_pct"]
    )
    sales_gap = abs(continuing_sales - regular_sales)
    operating_gap = abs(continuing_operating - regular_operating)

    # ``yoy_difference_pp`` is signed in the source; compare its magnitude to
    # the independently calculated absolute gap used by the public claim.
    if not np.isclose(
        abs(float(target.loc["sales", "yoy_difference_pp"])),
        sales_gap,
        rtol=0,
        atol=1e-9,
    ):
        raise ValueError("sales cross-series gap does not reconcile to source columns")
    if not np.isclose(
        abs(float(target.loc["operating_profit", "yoy_difference_pp"])),
        operating_gap,
        rtol=0,
        atol=1e-9,
    ):
        raise ValueError(
            "operating-profit cross-series gap does not reconcile to source columns"
        )

    return CurrentQuarterSmallValues(
        regular_sales_yoy=regular_sales,
        regular_operating_profit_yoy=regular_operating,
        continuing_sales_yoy=continuing_sales,
        continuing_operating_profit_yoy=continuing_operating,
        sales_cross_series_gap=sales_gap,
        operating_profit_cross_series_gap=operating_gap,
        source_rows={
            "sales": int(target.loc["sales", "_source_row_number"]),
            "operating_profit": int(
                target.loc["operating_profit", "_source_row_number"]
            ),
        },
    )


def validate_current_quarter_reproduction(values: CurrentQuarterSmallValues) -> list[str]:
    """Compare computed values with the release's one-decimal reproduction goals."""

    errors: list[str] = []
    for field, expected in _EXPECTED_2026Q1_DISPLAY_NUMBERS.items():
        observed = round(float(getattr(values, field)), 1)
        if not np.isclose(observed, expected, rtol=0, atol=1e-12):
            errors.append(f"REPRODUCTION_MISMATCH:{field}:{observed!r}!={expected!r}")
    return errors


def _signed_percent(value: float) -> str:
    sign = "＋" if value >= 0 else "－"
    return f"{sign}{abs(value):.1f}％"


def _new_claim_rows(
    values: CurrentQuarterSmallValues,
    *,
    canonical_source: str,
) -> list[dict[str, Any]]:
    scope = "資本金1,000万円以上1億円未満層、2026Q1"
    base: dict[str, Any] = {
        "claim_role": "SUPPORTING",
        "claim_class": "CALC",
        "scope": scope,
        "value_text": "",
        "numerator": np.nan,
        "denominator": np.nan,
        "rounding_digits": 1,
        "verification_status": "PASS",
        "article_use": True,
        "chart_ids": "",
        "calculation": "selected from canonical comparison CSV",
        "source": canonical_source,
        "note": "内部値を保持し、表示時のみ小数第1位へ丸める。",
        "exploratory_backtest_status": "NOT_APPLICABLE_CURRENT_QUARTER_EXAMPLE",
        "series_comparability_limitation": (
            "通常系列と継続標本系列は単に同じ真値を異なる標本で測った二つの"
            "推計とは限らず、いずれかを真実又は正解として扱わない。"
        ),
        "continuing_sample_size_limitation": (
            "継続標本のみを用い母集団推計を行うため、本系列に比べ"
            "サンプルサイズが小さくなる。"
        ),
        "profit_standard_error_limitation": (
            "営業利益及び経常利益については、標準誤差率の算出は行っていない。"
        ),
        "continuing_margin_interpretation": (
            "継続標本系列では営業利益率の水準を公表しないため方向だけを判定する。"
        ),
        "sample_error_status": (
            "NOT_QUANTIFIED_OPERATING_AND_ORDINARY_PROFIT_STANDARD_ERRORS_"
            "NOT_CALCULATED_BY_MOF"
        ),
        "canonical_source_path": canonical_source,
        "canonical_period_code": 20261,
        "canonical_breakdown": "capital_size",
        "canonical_category_code": 19,
    }
    specs = (
        (
            NEW_2026Q1_CLAIM_IDS[0],
            "sales_yoy_growth_rate",
            "regular",
            "sales",
            values.regular_sales_yoy,
            _signed_percent(values.regular_sales_yoy),
            "regular_yoy_pct",
        ),
        (
            NEW_2026Q1_CLAIM_IDS[1],
            "operating_profit_yoy_growth_rate",
            "regular",
            "operating_profit",
            values.regular_operating_profit_yoy,
            _signed_percent(values.regular_operating_profit_yoy),
            "regular_yoy_pct",
        ),
        (
            NEW_2026Q1_CLAIM_IDS[2],
            "sales_yoy_growth_rate",
            "continuing",
            "sales",
            values.continuing_sales_yoy,
            _signed_percent(values.continuing_sales_yoy),
            "continuing_yoy_pct",
        ),
        (
            NEW_2026Q1_CLAIM_IDS[3],
            "operating_profit_yoy_growth_rate",
            "continuing",
            "operating_profit",
            values.continuing_operating_profit_yoy,
            _signed_percent(values.continuing_operating_profit_yoy),
            "continuing_yoy_pct",
        ),
        (
            NEW_2026Q1_CLAIM_IDS[4],
            "sales_cross_series_growth_rate_gap",
            "cross_series_absolute_gap",
            "sales",
            values.sales_cross_series_gap,
            f"{values.sales_cross_series_gap:.1f}ポイント",
            "abs(continuing_yoy_pct-regular_yoy_pct)",
        ),
        (
            NEW_2026Q1_CLAIM_IDS[5],
            "operating_profit_cross_series_growth_rate_gap",
            "cross_series_absolute_gap",
            "operating_profit",
            values.operating_profit_cross_series_gap,
            f"{values.operating_profit_cross_series_gap:.1f}ポイント",
            "abs(continuing_yoy_pct-regular_yoy_pct)",
        ),
    )
    rows: list[dict[str, Any]] = []
    for claim_id, metric_id, series, metric, value, display, lineage in specs:
        row = dict(base)
        row.update(
            {
                "claim_id": claim_id,
                "metric_id": metric_id,
                "metric_type": _metric_type(metric_id),
                "numeric_value": float(value),
                "internal_value": float(value),
                "unit": _canonical_unit(metric_id),
                "display_value": display,
                "article_tokens": display,
                "canonical_series": series,
                "canonical_metric_id": metric,
                "canonical_source_row_number": values.source_rows[metric],
                "canonical_value_lineage": lineage,
            }
        )
        if series == "cross_series_absolute_gap":
            row["calculation"] = lineage
        rows.append(row)
    return rows


def build_claims_v3_2(
    *,
    claims_v3_1: pd.DataFrame,
    canonical_comparison: pd.DataFrame,
    canonical_source: str = str(CANONICAL_RELATIVE_PATH),
) -> pd.DataFrame:
    """Correct v3.1 units and append six source-derived 2026Q1 claims."""

    required = {"claim_id", "metric_id", "unit", "display_value", "numeric_value"}
    missing = required - set(claims_v3_1)
    if missing:
        raise ValueError(f"claims_v3_1 lacks columns: {sorted(missing)}")
    if claims_v3_1["claim_id"].astype(str).duplicated().any():
        raise ValueError("claims_v3_1 has duplicate claim IDs")

    values = extract_2026q1_small_values(canonical_comparison)
    reproduction_errors = validate_current_quarter_reproduction(values)
    if reproduction_errors:
        raise ValueError(";".join(reproduction_errors))

    old = claims_v3_1.copy()
    old["metric_type"] = old["metric_id"].astype(str).map(_metric_type)
    old["legacy_unit_v3_1"] = old["unit"]
    old["unit"] = old["metric_id"].astype(str).map(_canonical_unit)
    for claim_id, (expected_value, display) in _DECISION_MARGIN_EXPECTED.items():
        mask = old["claim_id"].astype(str).eq(claim_id)
        if int(mask.sum()) != 1:
            raise ValueError(f"claims_v3_1 must contain exactly one {claim_id}")
        actual = float(pd.to_numeric(old.loc[mask, "numeric_value"], errors="raise").iloc[0])
        if not np.isclose(actual, expected_value, rtol=0, atol=1e-12):
            raise ValueError(
                f"decision-margin source mismatch for {claim_id}: {actual}!={expected_value}"
            )
        old.loc[mask, "display_value"] = display
        old.loc[mask, "article_tokens"] = display

    # Add explicit lineage columns without changing the prior release on disk.
    lineage_defaults: dict[str, Any] = {
        "internal_value": old["numeric_value"],
        "canonical_source_path": "",
        "canonical_period_code": np.nan,
        "canonical_breakdown": "",
        "canonical_category_code": np.nan,
        "canonical_series": "",
        "canonical_metric_id": "",
        "canonical_source_row_number": np.nan,
        "canonical_value_lineage": "",
    }
    for column, value in lineage_defaults.items():
        if column not in old:
            old[column] = value

    new = pd.DataFrame(_new_claim_rows(values, canonical_source=canonical_source))
    for column in old.columns:
        if column not in new:
            new[column] = np.nan
    for column in new.columns:
        if column not in old:
            old[column] = np.nan
    claims = pd.concat([old, new[old.columns]], ignore_index=True)
    claims = claims.sort_values("claim_id", kind="stable").reset_index(drop=True)

    registry = build_unit_registry(claims)
    errors = validate_claim_units(claims, registry)
    errors.extend(
        validate_new_claims_against_canonical(
            claims,
            canonical_comparison,
        )
    )
    if errors:
        raise ValueError(f"claims_v3_2 validation failed: {errors}")
    return claims


def build_unit_registry(claims: pd.DataFrame) -> dict[str, Any]:
    """Return a JSON-serialisable metric- and claim-level unit registry."""

    required = {"claim_id", "metric_id", "unit"}
    missing = required - set(claims)
    if missing:
        raise ValueError(f"claims lack unit-registry columns: {sorted(missing)}")
    if claims["claim_id"].astype(str).duplicated().any():
        raise ValueError("cannot register duplicate claim IDs")

    metric_registry: dict[str, dict[str, str]] = {}
    claim_registry: dict[str, dict[str, str]] = {}
    for row in claims.sort_values("claim_id", kind="stable").itertuples(index=False):
        claim_id = str(row.claim_id)
        metric_id = str(row.metric_id)
        metric_type = _metric_type(metric_id)
        expected_unit = CANONICAL_UNIT_BY_METRIC_TYPE[metric_type]
        prior = metric_registry.get(metric_id)
        entry = {"metric_type": metric_type, "canonical_unit": expected_unit}
        if prior is not None and prior != entry:
            raise ValueError(f"inconsistent registry mapping for metric_id={metric_id}")
        metric_registry[metric_id] = entry
        claim_registry[claim_id] = {
            "metric_id": metric_id,
            "metric_type": metric_type,
            "canonical_unit": expected_unit,
        }

    return {
        "schema_version": "1.0",
        "release": RELEASE_V3_2,
        "canonical_unit_by_metric_type": dict(CANONICAL_UNIT_BY_METRIC_TYPE),
        "unit_definitions": {
            "percent": "rate expressed in percent",
            "percentage_points": "arithmetic difference between percentage rates",
            "count": "integer count",
            "oku_yen": "currency amount in hundred-million yen",
            "yen": "currency amount in yen",
        },
        "legacy_notation_aliases": {
            "%": "percent",
            "pt": "percentage_points",
            "quarters": "count",
        },
        "metric_id_registry": metric_registry,
        "claim_id_registry": claim_registry,
        "validation_rules": {
            "difference_between_growth_rates_forbidden_units": ["percent", "%"],
            "claim_and_metric_registry_must_agree": True,
        },
    }


def validate_claim_units(
    claims: pd.DataFrame,
    registry: Mapping[str, Any],
) -> list[str]:
    """Validate actual claim units against both metric and claim registries."""

    required = {"claim_id", "metric_id", "unit"}
    missing = required - set(claims)
    if missing:
        return [f"MISSING_UNIT_COLUMNS:{','.join(sorted(missing))}"]
    errors: list[str] = []
    metric_registry = registry.get("metric_id_registry", {})
    claim_registry = registry.get("claim_id_registry", {})
    canonical_units = registry.get("canonical_unit_by_metric_type", {})
    for row in claims.itertuples(index=False):
        claim_id = str(row.claim_id)
        metric_id = str(row.metric_id)
        unit = str(row.unit)
        metric_entry = metric_registry.get(metric_id)
        claim_entry = claim_registry.get(claim_id)
        if metric_entry is None:
            errors.append(f"UNREGISTERED_METRIC_ID:{metric_id}")
            continue
        if claim_entry is None:
            errors.append(f"UNREGISTERED_CLAIM_ID:{claim_id}")
            continue
        if str(claim_entry.get("metric_id")) != metric_id:
            errors.append(f"CLAIM_METRIC_REGISTRY_MISMATCH:{claim_id}")
        metric_type = str(metric_entry.get("metric_type"))
        expected = str(canonical_units.get(metric_type, ""))
        if not expected:
            errors.append(f"UNREGISTERED_METRIC_TYPE:{metric_type}")
        elif unit != expected:
            errors.append(f"UNIT_MISMATCH:{claim_id}:{unit}!={expected}")
        if metric_type == "difference_between_growth_rates" and unit in {
            "percent",
            "%",
        }:
            errors.append(f"GROWTH_RATE_DIFFERENCE_MUST_USE_PERCENTAGE_POINTS:{claim_id}")
    return errors


def validate_new_claims_against_canonical(
    claims: pd.DataFrame,
    canonical_comparison: pd.DataFrame,
) -> list[str]:
    """Re-derive the six new claim values and compare at full stored precision."""

    try:
        expected_values = extract_2026q1_small_values(canonical_comparison)
    except ValueError as exc:
        return [f"CANONICAL_EXTRACTION_FAILED:{exc}"]
    expected = {
        NEW_2026Q1_CLAIM_IDS[0]: expected_values.regular_sales_yoy,
        NEW_2026Q1_CLAIM_IDS[1]: expected_values.regular_operating_profit_yoy,
        NEW_2026Q1_CLAIM_IDS[2]: expected_values.continuing_sales_yoy,
        NEW_2026Q1_CLAIM_IDS[3]: expected_values.continuing_operating_profit_yoy,
        NEW_2026Q1_CLAIM_IDS[4]: expected_values.sales_cross_series_gap,
        NEW_2026Q1_CLAIM_IDS[5]: expected_values.operating_profit_cross_series_gap,
    }
    errors: list[str] = []
    ids = claims["claim_id"].astype(str)
    for claim_id, expected_value in expected.items():
        selected = claims.loc[ids.eq(claim_id)]
        if len(selected) != 1:
            errors.append(f"CLAIM_CARDINALITY:{claim_id}:{len(selected)}")
            continue
        observed = pd.to_numeric(selected["numeric_value"], errors="coerce").iloc[0]
        internal = pd.to_numeric(selected["internal_value"], errors="coerce").iloc[0]
        if pd.isna(observed) or not np.isclose(
            float(observed), expected_value, rtol=0, atol=1e-12
        ):
            errors.append(f"CANONICAL_VALUE_MISMATCH:{claim_id}")
        if pd.isna(internal) or not np.isclose(
            float(internal), expected_value, rtol=0, atol=1e-12
        ):
            errors.append(f"INTERNAL_VALUE_MISMATCH:{claim_id}")
    return errors


def build_claim_corrections_v3_2(
    claims_v3_1: pd.DataFrame,
    claims_v3_2: pd.DataFrame,
) -> pd.DataFrame:
    """Create the six-row semantic correction ledger (three claims x two fields)."""

    before = claims_v3_1.set_index(claims_v3_1["claim_id"].astype(str))
    after = claims_v3_2.set_index(claims_v3_2["claim_id"].astype(str))
    rows: list[dict[str, str]] = []
    for claim_id in DECISION_MARGIN_CLAIM_IDS:
        if claim_id not in before.index or claim_id not in after.index:
            raise ValueError(f"correction ledger missing claim {claim_id}")
        for field, reason in (
            (
                "unit",
                "増加率同士の差をpercentではなくpercentage_pointsへ訂正",
            ),
            (
                "display_value",
                "日本語表示を増加率同士の差に対応するポイント表記へ訂正",
            ),
        ):
            rows.append(
                {
                    "claim_id": claim_id,
                    "field": field,
                    "before_value": str(before.loc[claim_id, field]),
                    "after_value": str(after.loc[claim_id, field]),
                    "reason": reason,
                    "source_version": "2026Q1_v3_1",
                    "target_version": RELEASE_V3_2,
                }
            )
    result = pd.DataFrame(rows)
    if len(result) != 6:
        raise AssertionError("claim correction ledger must contain exactly six rows")
    return result


def build_expected_value_changes_v3_2() -> pd.DataFrame:
    """Record the intentional exact-title expectation update."""

    return pd.DataFrame(
        [
            {
                "check_id": "article_title_exact_and_small_capital",
                "before_expected_value": ARTICLE_TITLE_V3_1,
                "after_expected_value": ARTICLE_TITLE_V3_2,
                "change_reason": (
                    "主張を営業利益率方向の不一致に限定し、期間表現を最終版へ更新"
                ),
                "status": "EXPECTED_VALUE_UPDATED",
            }
        ]
    )


def build_stage5_claim_artifacts(project_root: Path | str) -> Stage5ClaimArtifacts:
    """Load frozen inputs and build all v3.2 claim/unit-ledger artifacts in memory."""

    root = Path(project_root).resolve()
    canonical_path = root / CANONICAL_RELATIVE_PATH
    claims_path = root / V3_1_CLAIMS_RELATIVE_PATH
    canonical = pd.read_csv(canonical_path)
    claims_v3_1 = pd.read_csv(claims_path)
    values = extract_2026q1_small_values(canonical)
    claims_v3_2 = build_claims_v3_2(
        claims_v3_1=claims_v3_1,
        canonical_comparison=canonical,
        canonical_source=CANONICAL_RELATIVE_PATH.as_posix(),
    )
    unit_registry = build_unit_registry(claims_v3_2)
    return Stage5ClaimArtifacts(
        claims_v3_2=claims_v3_2,
        unit_registry=unit_registry,
        claim_corrections_v3_2=build_claim_corrections_v3_2(
            claims_v3_1,
            claims_v3_2,
        ),
        expected_value_changes_v3_2=build_expected_value_changes_v3_2(),
        current_quarter_values=values,
    )
