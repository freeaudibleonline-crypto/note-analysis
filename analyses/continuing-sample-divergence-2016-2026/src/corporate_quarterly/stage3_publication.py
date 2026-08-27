"""Fail-closed Stage 3 claims, article, and publication decision support.

There are two mutually exclusive public candidates:

``SAMPLE_CONSTRUCTION_SENSITIVITY``
    The regular and continuing-sample series can imply opposite operating-
    margin directions.

``NONOPERATING_BRIDGE``
    The ordinary-minus-operating-profit change can be decomposed into the four
    Table 1 non-operating items.

Claim ownership is a complete literal registry.  No claim is assigned by an ID
substring, label fragment, or article-text heuristic.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Mapping

import numpy as np
import pandas as pd

from .stage3_charts import (
    PUBLIC_SAMPLE_CHART_FILENAMES,
    STAGE3_CHART_FILENAMES,
    _current_capital_margin_rows,
    _current_nonoperating_rows,
    _historical_frequency_rows,
)

if TYPE_CHECKING:  # pragma: no cover
    from .stage2_continuing_sample import ContinuingSampleAnalysis
    from .stage2_phase3_non_operating import Phase3NonOperatingAnalysis


SAMPLE_CANDIDATE_ID = "SAMPLE_CONSTRUCTION_SENSITIVITY"
NONOPERATING_CANDIDATE_ID = "NONOPERATING_BRIDGE"

PUBLISH_SAMPLE_CONSTRUCTION_SENSITIVITY = (
    "PUBLISH_SAMPLE_CONSTRUCTION_SENSITIVITY"
)
PUBLISH_FULL_NONOPERATING_BRIDGE_SNAPSHOT = (
    "PUBLISH_FULL_NONOPERATING_BRIDGE_SNAPSHOT"
)
ARCHIVE_NO_ROBUST_STORY = "ARCHIVE_NO_ROBUST_STORY"

VALID_STAGE3_DECISIONS = frozenset(
    {
        PUBLISH_SAMPLE_CONSTRUCTION_SENSITIVITY,
        PUBLISH_FULL_NONOPERATING_BRIDGE_SNAPSHOT,
        ARCHIVE_NO_ROBUST_STORY,
    }
)

# Complete explicit ownership for every row emitted by build_claims_v3().
# Keeping this as a literal makes additions reviewable and prevents accidental
# ownership based on a matching fragment in a claim ID.
CLAIM_CANDIDATE_REGISTRY_V3: dict[str, str] = {
    "V3-MAIN-CAP19-SALES-YOY": SAMPLE_CANDIDATE_ID,
    "V3-MAIN-CAP19-OPERATING-PROFIT-YOY": SAMPLE_CANDIDATE_ID,
    "V3-MAIN-CAP19-MARGIN-DIRECTION": SAMPLE_CANDIDATE_ID,
    "V3-CONT-CAP19-SALES-YOY": SAMPLE_CANDIDATE_ID,
    "V3-CONT-CAP19-OPERATING-PROFIT-YOY": SAMPLE_CANDIDATE_ID,
    "V3-CONT-CAP19-MARGIN-DIRECTION": SAMPLE_CANDIDATE_ID,
    "V3-MAIN-CAP24-SALES-YOY": SAMPLE_CANDIDATE_ID,
    "V3-MAIN-CAP24-OPERATING-PROFIT-YOY": SAMPLE_CANDIDATE_ID,
    "V3-MAIN-CAP24-MARGIN-DIRECTION": SAMPLE_CANDIDATE_ID,
    "V3-CONT-CAP24-SALES-YOY": SAMPLE_CANDIDATE_ID,
    "V3-CONT-CAP24-OPERATING-PROFIT-YOY": SAMPLE_CANDIDATE_ID,
    "V3-CONT-CAP24-MARGIN-DIRECTION": SAMPLE_CANDIDATE_ID,
    "V3-MAIN-CAP25-SALES-YOY": SAMPLE_CANDIDATE_ID,
    "V3-MAIN-CAP25-OPERATING-PROFIT-YOY": SAMPLE_CANDIDATE_ID,
    "V3-MAIN-CAP25-MARGIN-DIRECTION": SAMPLE_CANDIDATE_ID,
    "V3-CONT-CAP25-SALES-YOY": SAMPLE_CANDIDATE_ID,
    "V3-CONT-CAP25-OPERATING-PROFIT-YOY": SAMPLE_CANDIDATE_ID,
    "V3-CONT-CAP25-MARGIN-DIRECTION": SAMPLE_CANDIDATE_ID,
    "V3-CURRENT-HEADLINE-REVERSAL": SAMPLE_CANDIDATE_ID,
    "V3-HEADLINE-REVERSAL-FREQUENCY": SAMPLE_CANDIDATE_ID,
    "V3-SMALL-MARGIN-REVERSAL-FREQUENCY": SAMPLE_CANDIDATE_ID,
    "V3-CONT-SMALLER-SAMPLE": SAMPLE_CANDIDATE_ID,
    "V3-CONT-PROFIT-SE-NOT-CALCULATED": SAMPLE_CANDIDATE_ID,
    "V3-NONOP-INTEREST-INCOME": NONOPERATING_CANDIDATE_ID,
    "V3-NONOP-OTHER-INCOME": NONOPERATING_CANDIDATE_ID,
    "V3-NONOP-INTEREST-EXPENSE": NONOPERATING_CANDIDATE_ID,
    "V3-NONOP-OTHER-EXPENSE": NONOPERATING_CANDIDATE_ID,
    "V3-NONOP-NET-GAP": NONOPERATING_CANDIDATE_ID,
}

CAPITAL_SCOPE_NAMES = {
    "19": "資本金1千万円以上1億円未満層",
    "24": "資本金1億円以上10億円未満層",
    "25": "資本金10億円以上層",
}

EXACT_FACT_SUMMARY_200 = (
    "令和八年一～三月期、通常系列では資本金1千万円以上1億円未満層の売上高は2.1％増、営業利益は1.9％減で、営業利益率は低下した。一方、同じ層の継続標本系列では売上高2.5％増、営業利益6.0％増となり、利益率は上昇方向だった。通常系列の同層見出しは、継続標本へ替えると成立しない。継続標本は通常系列より標本数が少なく、売上高と設備投資以外の標準誤差率は公表資料で計算されていないとの公式注記がある。"
)

if len(EXACT_FACT_SUMMARY_200) != 200:  # pragma: no cover - import-time guard
    raise AssertionError("The frozen FACT summary must be exactly 200 characters")


@dataclass(frozen=True)
class Stage3PublicationAudit:
    status: str
    checks: pd.DataFrame

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(
            self.checks.loc[self.checks["status"].eq("FAIL"), "check_id"].astype(str)
        )


def _claim_row(
    *,
    claim_id: str,
    claim_class: str,
    period_code: str,
    scope: str,
    metric_id: str,
    numeric_value: float | None = None,
    value_text: str = "",
    unit: str,
    display_value: str,
    rounding_digits: int | None,
    numerator: int | None = None,
    denominator: int | None = None,
    source_yoy_delta_oku_yen: float | None = None,
    calculation: str = "DIRECT_PUBLISHED_VALUE",
    source: str,
    article_use: bool,
    chart_ids: Iterable[str] = (),
    note: str = "",
) -> dict[str, Any]:
    candidate_id = CLAIM_CANDIDATE_REGISTRY_V3[claim_id]
    return {
        "claim_id": claim_id,
        "candidate_id": candidate_id,
        "candidate_mapping_registry": "CLAIM_CANDIDATE_REGISTRY_V3_EXPLICIT",
        "claim_class": claim_class,
        "period_code": period_code,
        "scope": scope,
        "metric_id": metric_id,
        "numeric_value": numeric_value,
        "value_text": value_text,
        "unit": unit,
        "display_value": display_value,
        "rounding_digits": rounding_digits,
        "numerator": numerator,
        "denominator": denominator,
        "source_yoy_delta_oku_yen": source_yoy_delta_oku_yen,
        "calculation": calculation,
        "source": source,
        "verification_status": "PASS",
        "article_use": bool(article_use),
        "chart_ids": ";".join(chart_ids),
        "note": note,
    }


def _growth_display(value: float) -> str:
    if value > 0:
        return f"{abs(value):.1f}％増"
    if value < 0:
        return f"{abs(value):.1f}％減"
    return "0.0％"


def _direction_display(direction: str, *, continuing: bool) -> str:
    labels = {"UP": "上昇", "DOWN": "低下", "FLAT": "横ばい"}
    if direction not in labels:
        raise ValueError(f"Unknown margin direction: {direction}")
    return labels[direction] + ("方向" if continuing and direction != "FLAT" else "")


def build_claims_v3(
    *,
    continuing: "ContinuingSampleAnalysis",
    nonoperating: "Phase3NonOperatingAnalysis",
) -> pd.DataFrame:
    """Build every public/article and chart value with explicit ownership."""
    current = _current_capital_margin_rows(continuing)
    rows: list[dict[str, Any]] = []
    for source_prefix, id_prefix, source_name in (
        ("regular", "MAIN", "e-Stat表1（通常系列）"),
        ("continuing", "CONT", "財務省 keizoku.pdf（継続標本）"),
    ):
        for row in current.itertuples(index=False):
            capital_code = str(row.category_code)
            scope = CAPITAL_SCOPE_NAMES[capital_code] + "（金融業・保険業を除く）"
            sales = float(getattr(row, f"{source_prefix}_sales_yoy_pct"))
            operating = float(
                getattr(row, f"{source_prefix}_operating_profit_yoy_pct")
            )
            direction = str(
                getattr(row, f"{source_prefix}_relative_margin_change_direction")
            )
            article_use = capital_code == "19"
            calculation = (
                "DIRECT_PUBLISHED_YOY_RATE"
                if source_prefix == "continuing"
                else "100*(current/year_ago-1); positive profit levels required"
            )
            rows.extend(
                [
                    _claim_row(
                        claim_id=f"V3-{id_prefix}-CAP{capital_code}-SALES-YOY",
                        claim_class="FACT" if source_prefix == "continuing" else "CALC",
                        period_code="20261",
                        scope=scope,
                        metric_id="sales_yoy_pct",
                        numeric_value=sales,
                        unit="%",
                        display_value=_growth_display(sales),
                        rounding_digits=1,
                        calculation=calculation,
                        source=source_name,
                        article_use=article_use,
                        chart_ids=(STAGE3_CHART_FILENAMES[0],),
                    ),
                    _claim_row(
                        claim_id=f"V3-{id_prefix}-CAP{capital_code}-OPERATING-PROFIT-YOY",
                        claim_class="FACT" if source_prefix == "continuing" else "CALC",
                        period_code="20261",
                        scope=scope,
                        metric_id="operating_profit_yoy_pct",
                        numeric_value=operating,
                        unit="%",
                        display_value=_growth_display(operating),
                        rounding_digits=1,
                        calculation=calculation,
                        source=source_name,
                        article_use=article_use,
                        chart_ids=(STAGE3_CHART_FILENAMES[0],),
                    ),
                    _claim_row(
                        claim_id=f"V3-{id_prefix}-CAP{capital_code}-MARGIN-DIRECTION",
                        claim_class="CALC",
                        period_code="20261",
                        scope=scope,
                        metric_id="operating_margin_change_direction",
                        value_text=direction,
                        unit="direction",
                        display_value=_direction_display(
                            direction, continuing=source_prefix == "continuing"
                        ),
                        rounding_digits=None,
                        calculation=(
                            "sign((1+operating_profit_yoy)/(1+sales_yoy)-1); "
                            "direction proxy only; no margin level or pp change"
                            if source_prefix == "continuing"
                            else "sign((1+operating_profit_yoy)/(1+sales_yoy)-1); "
                            "positive operating-profit levels verified"
                        ),
                        source=source_name,
                        article_use=article_use,
                        chart_ids=(STAGE3_CHART_FILENAMES[0],),
                        note=(
                            "継続標本の利益率水準は不明。方向代理のみ。"
                            if source_prefix == "continuing"
                            else ""
                        ),
                    ),
                ]
            )

    current_headline = continuing.capital_headline_history.loc[
        continuing.capital_headline_history["period_code"].astype(str).eq("20261")
    ]
    if len(current_headline) != 1:
        raise ValueError("Expected one current headline-comparison row")
    headline_row = current_headline.iloc[0]
    if pd.isna(headline_row["regular_headline_supported"]) or pd.isna(
        headline_row["continuing_headline_supported"]
    ):
        raise ValueError("Current headline comparison is not calculable")
    regular_supported = bool(headline_row["regular_headline_supported"])
    continuing_supported = bool(headline_row["continuing_headline_supported"])
    reversal = regular_supported != continuing_supported
    rows.append(
        _claim_row(
            claim_id="V3-CURRENT-HEADLINE-REVERSAL",
            claim_class="CALC",
            period_code="20261",
            scope="資本金規模別の営業利益率方向見出し（金融業・保険業を除く）",
            metric_id="headline_support_reversal",
            numeric_value=float(reversal),
            value_text=(
                f"regular={regular_supported};continuing={continuing_supported}"
            ),
            unit="boolean",
            display_value="継続標本では成立しない" if reversal else "反転なし",
            rounding_digits=None,
            calculation=str(headline_row["headline_definition"]),
            source="e-Stat表1と財務省 keizoku.pdf",
            article_use=True,
            note="継続標本の利益率方向は代理指標。",
        )
    )

    headline_frequency, margin_frequency = _historical_frequency_rows(continuing)
    for claim_id, metric_id, record, display_scope in (
        (
            "V3-HEADLINE-REVERSAL-FREQUENCY",
            "headline_reversal_frequency",
            headline_frequency,
            "規模別見出しの成立可否",
        ),
        (
            "V3-SMALL-MARGIN-REVERSAL-FREQUENCY",
            "small_capital_margin_direction_reversal_frequency",
            margin_frequency,
            "資本金1千万円以上1億円未満層の利益率方向",
        ),
    ):
        rows.append(
            _claim_row(
                claim_id=claim_id,
                claim_class="CALC",
                period_code="20161-20261",
                scope=display_scope + "（金融業・保険業を除く）",
                metric_id=metric_id,
                numeric_value=float(record["rate"]),
                unit="%",
                display_value=(
                    f"{record['numerator']}/{record['denominator']}四半期"
                    f"（{record['rate']:.2f}％）"
                ),
                rounding_digits=2,
                numerator=int(record["numerator"]),
                denominator=int(record["denominator"]),
                calculation="100*reversal_count/comparable_quarters",
                source="e-Stat表1と財務省 keizoku.pdf",
                article_use=True,
                chart_ids=(STAGE3_CHART_FILENAMES[1],),
                note="比較不能な期は分母に入れず、0補完しない。",
            )
        )

    rows.extend(
        [
            _claim_row(
                claim_id="V3-CONT-SMALLER-SAMPLE",
                claim_class="FACT",
                period_code="20261",
                scope="継続標本の標本設計",
                metric_id="continuing_sample_size_note",
                value_text="SMALLER_THAN_REGULAR_SERIES",
                unit="text",
                display_value="通常系列より標本数が少ない",
                rounding_digits=None,
                source="財務省 keizoku.pdf 注記",
                article_use=True,
            ),
            _claim_row(
                claim_id="V3-CONT-PROFIT-SE-NOT-CALCULATED",
                claim_class="FACT",
                period_code="20261",
                scope="継続標本の標準誤差率",
                metric_id="profit_standard_error_status",
                value_text="OPERATING_AND_ORDINARY_PROFIT_NOT_CALCULATED",
                unit="text",
                display_value="営業利益・経常利益の標準誤差率は未算出",
                rounding_digits=None,
                source="財務省 keizoku.pdf 注記",
                article_use=True,
            ),
        ]
    )

    bridge = _current_nonoperating_rows(nonoperating)
    component_claim_ids = {
        "interest_and_dividend_income": "V3-NONOP-INTEREST-INCOME",
        "other_non_operating_income": "V3-NONOP-OTHER-INCOME",
        "interest_expense": "V3-NONOP-INTEREST-EXPENSE",
        "other_non_operating_expense": "V3-NONOP-OTHER-EXPENSE",
    }
    for component in bridge.itertuples(index=False):
        rows.append(
            _claim_row(
                claim_id=component_claim_ids[str(component.component_id)],
                claim_class="CALC",
                period_code="20261",
                scope="全産業・全規模（金融業・保険業を除く）",
                metric_id=f"{component.component_id}_profit_impact_yoy",
                numeric_value=float(component.profit_impact_yoy_oku_yen),
                unit="億円",
                display_value=f"{float(component.profit_impact_yoy_oku_yen):+,.2f}億円",
                rounding_digits=2,
                source_yoy_delta_oku_yen=float(component.source_yoy_delta_oku_yen),
                calculation=f"accounting_sign({int(component.accounting_sign):+d}) * source_yoy_delta",
                source="e-Stat表1 コード082–085",
                article_use=False,
                chart_ids=(STAGE3_CHART_FILENAMES[2],),
                note=(
                    "支払利息等は増加し、利益影響はマイナス。"
                    if component.component_id == "interest_expense"
                    else (
                        "特定要因に帰属させない。"
                        if component.component_id == "other_non_operating_income"
                        else ""
                    )
                ),
            )
        )
    # The source is stored to 0.01 oku-yen.  Canonicalise the displayed total
    # at that same precision instead of exposing a binary-float artefact.
    impact_total = round(
        float(bridge["profit_impact_yoy_oku_yen"].astype(float).sum()), 2
    )
    decomposition_current = nonoperating.decomposition.loc[
        nonoperating.decomposition["period_code"].astype(str).eq("20261")
        & nonoperating.decomposition["industry_code"].astype(str).eq("104")
        & nonoperating.decomposition["capital_size_code"].astype(str).eq("26")
    ]
    if len(decomposition_current) != 1:
        raise ValueError("Expected one current all-industry/all-capital decomposition row")
    anchor_total = float(decomposition_current.iloc[0]["anchor_gap_yoy_delta_oku_yen"])
    if not np.isclose(impact_total, anchor_total, rtol=0, atol=0.01):
        raise ValueError("Four-item claim total does not equal the ordinary-operating gap")
    rows.append(
        _claim_row(
            claim_id="V3-NONOP-NET-GAP",
            claim_class="CALC",
            period_code="20261",
            scope="全産業・全規模（金融業・保険業を除く）",
            metric_id="net_non_operating_gap_yoy_delta",
            numeric_value=impact_total,
            unit="億円",
            display_value=f"{impact_total:+,.2f}億円",
            rounding_digits=2,
            calculation="sum(four signed non-operating item YoY impacts)",
            source="e-Stat表1 コード081–086",
            article_use=False,
            chart_ids=(STAGE3_CHART_FILENAMES[2],),
        )
    )

    claims = pd.DataFrame(rows)
    errors = validate_claims_v3(claims)
    if errors:
        raise ValueError(f"claims_v3 validation failed: {errors}")
    return claims.sort_values("claim_id", kind="stable").reset_index(drop=True)


def validate_claims_v3(
    claims: pd.DataFrame,
    *,
    registry: Mapping[str, str] = CLAIM_CANDIDATE_REGISTRY_V3,
) -> list[str]:
    """Validate the complete Stage 3 ledger; return stable error codes."""
    required = {
        "claim_id",
        "candidate_id",
        "candidate_mapping_registry",
        "claim_class",
        "period_code",
        "scope",
        "metric_id",
        "numeric_value",
        "value_text",
        "unit",
        "display_value",
        "verification_status",
        "article_use",
        "chart_ids",
    }
    errors: list[str] = []
    missing = required - set(claims.columns)
    if missing:
        return [f"MISSING_COLUMNS:{','.join(sorted(missing))}"]
    ids = claims["claim_id"].astype(str)
    if ids.duplicated().any():
        errors.append("DUPLICATE_CLAIM_IDS")
    observed = set(ids)
    if observed != set(registry):
        errors.append(
            "REGISTRY_SET_MISMATCH:"
            f"missing={sorted(set(registry) - observed)}:"
            f"extra={sorted(observed - set(registry))}"
        )
    bad_mapping = claims.loc[
        claims.apply(
            lambda row: registry.get(str(row["claim_id"])) != row["candidate_id"],
            axis=1,
        )
    ]
    if not bad_mapping.empty:
        errors.append("EXPLICIT_CANDIDATE_MAPPING_MISMATCH")
    if not claims["candidate_mapping_registry"].eq(
        "CLAIM_CANDIDATE_REGISTRY_V3_EXPLICIT"
    ).all():
        errors.append("MAPPING_REGISTRY_MARKER_MISSING")
    if not claims["claim_class"].isin({"FACT", "CALC", "HYPOTHESIS"}).all():
        errors.append("INVALID_CLAIM_CLASS")
    if not claims["verification_status"].eq("PASS").all():
        errors.append("NON_PASS_CLAIM")
    nonop_public = claims.loc[
        claims["candidate_id"].eq(NONOPERATING_CANDIDATE_ID)
        & claims["article_use"].astype(bool)
    ]
    if not nonop_public.empty:
        errors.append("NONOPERATING_CLAIM_MARKED_FOR_SAMPLE_ARTICLE")
    unknown_charts = {
        chart
        for cell in claims["chart_ids"].fillna("").astype(str)
        for chart in cell.split(";")
        if chart and chart not in STAGE3_CHART_FILENAMES
    }
    if unknown_charts:
        errors.append(f"UNKNOWN_CHART_IDS:{sorted(unknown_charts)}")
    charts_with_claims = {
        chart
        for cell in claims["chart_ids"].fillna("").astype(str)
        for chart in cell.split(";")
        if chart
    }
    if charts_with_claims != set(STAGE3_CHART_FILENAMES):
        errors.append("CHART_INPUT_CLAIMS_INCOMPLETE")
    numeric_expected = claims["unit"].isin({"%", "億円", "boolean"})
    numeric = pd.to_numeric(claims.loc[numeric_expected, "numeric_value"], errors="coerce")
    if numeric.isna().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        errors.append("MISSING_OR_NONFINITE_NUMERIC_CLAIM")
    if observed == set(registry) and not ids.duplicated().any():
        by_id = claims.set_index("claim_id")
        canonical_numeric = {
            "V3-MAIN-CAP19-SALES-YOY": (2.1, 1),
            "V3-MAIN-CAP19-OPERATING-PROFIT-YOY": (-1.9, 1),
            "V3-MAIN-CAP25-SALES-YOY": (1.7, 1),
            "V3-MAIN-CAP25-OPERATING-PROFIT-YOY": (18.5, 1),
            "V3-CONT-CAP19-SALES-YOY": (2.5, 1),
            "V3-CONT-CAP19-OPERATING-PROFIT-YOY": (6.0, 1),
            "V3-CONT-CAP24-SALES-YOY": (2.0, 1),
            "V3-CONT-CAP24-OPERATING-PROFIT-YOY": (22.4, 1),
            "V3-CONT-CAP25-SALES-YOY": (2.6, 1),
            "V3-CONT-CAP25-OPERATING-PROFIT-YOY": (20.0, 1),
            "V3-NONOP-INTEREST-INCOME": (152.04, 2),
            "V3-NONOP-OTHER-INCOME": (15424.31, 2),
            "V3-NONOP-INTEREST-EXPENSE": (-6759.86, 2),
            "V3-NONOP-OTHER-EXPENSE": (6790.13, 2),
            "V3-NONOP-NET-GAP": (15606.62, 2),
        }
        bad_canonical = []
        for claim_id, (expected, digits) in canonical_numeric.items():
            observed_value = pd.to_numeric(
                pd.Series([by_id.loc[claim_id, "numeric_value"]]), errors="coerce"
            ).iloc[0]
            if pd.isna(observed_value) or round(float(observed_value), digits) != expected:
                bad_canonical.append(claim_id)
        if bad_canonical:
            errors.append(f"CANONICAL_2026Q1_VALUE_MISMATCH:{bad_canonical}")
        expected_directions = {
            "V3-MAIN-CAP19-MARGIN-DIRECTION": "DOWN",
            "V3-CONT-CAP19-MARGIN-DIRECTION": "UP",
        }
        bad_directions = [
            claim_id
            for claim_id, expected in expected_directions.items()
            if by_id.loc[claim_id, "value_text"] != expected
        ]
        if bad_directions:
            errors.append(f"CANONICAL_2026Q1_DIRECTION_MISMATCH:{bad_directions}")
        expected_frequency = {
            "V3-HEADLINE-REVERSAL-FREQUENCY": (11, 41, 26.83),
            "V3-SMALL-MARGIN-REVERSAL-FREQUENCY": (16, 41, 39.02),
        }
        bad_frequency = []
        for claim_id, (numerator, denominator, rate) in expected_frequency.items():
            row = by_id.loc[claim_id]
            observed_numerator = pd.to_numeric(
                pd.Series([row["numerator"]]), errors="coerce"
            ).iloc[0]
            observed_denominator = pd.to_numeric(
                pd.Series([row["denominator"]]), errors="coerce"
            ).iloc[0]
            if (
                pd.isna(observed_numerator)
                or pd.isna(observed_denominator)
                or int(float(observed_numerator)) != numerator
                or int(float(observed_denominator)) != denominator
                or round(float(row["numeric_value"]), 2) != rate
            ):
                bad_frequency.append(claim_id)
        if bad_frequency:
            errors.append(f"CANONICAL_REVERSAL_FREQUENCY_MISMATCH:{bad_frequency}")
        expected_source_deltas = {
            "V3-NONOP-INTEREST-INCOME": 152.04,
            "V3-NONOP-OTHER-INCOME": 15424.31,
            "V3-NONOP-INTEREST-EXPENSE": 6759.86,
            "V3-NONOP-OTHER-EXPENSE": -6790.13,
        }
        bad_source_deltas = [
            claim_id
            for claim_id, expected in expected_source_deltas.items()
            if round(float(by_id.loc[claim_id, "source_yoy_delta_oku_yen"]), 2)
            != expected
        ]
        if bad_source_deltas:
            errors.append(f"CANONICAL_NONOPERATING_SOURCE_DELTA_MISMATCH:{bad_source_deltas}")
    return errors


def select_stage3_publication_decision(
    *,
    continuing: "ContinuingSampleAnalysis",
    nonoperating: "Phase3NonOperatingAnalysis",
) -> str:
    """Select exactly one public result, prioritising the observed reversal."""
    current = _current_capital_margin_rows(continuing).set_index("category_code")
    small = current.loc["19"]
    reversal_gate = (
        small["regular_relative_margin_change_direction"] == "DOWN"
        and small["continuing_relative_margin_change_direction"] == "UP"
    )
    headline = continuing.capital_headline_history.loc[
        continuing.capital_headline_history["period_code"].astype(str).eq("20261")
    ]
    if len(headline) == 1 and not pd.isna(headline.iloc[0]["headline_reversal"]):
        reversal_gate = reversal_gate and bool(headline.iloc[0]["headline_reversal"])
    else:
        reversal_gate = False
    if reversal_gate:
        return PUBLISH_SAMPLE_CONSTRUCTION_SENSITIVITY

    try:
        bridge = _current_nonoperating_rows(nonoperating)
        current_identity = nonoperating.identity_checks.loc[
            nonoperating.identity_checks["period_code"].astype(str).eq("20261")
        ]
        bridge_gate = len(bridge) == 4 and not current_identity.empty and current_identity[
            "status"
        ].eq("PASS").all()
    except (KeyError, TypeError, ValueError):
        bridge_gate = False
    return (
        PUBLISH_FULL_NONOPERATING_BRIDGE_SNAPSHOT
        if bridge_gate
        else ARCHIVE_NO_ROBUST_STORY
    )


def _summary_with_claim_comments() -> str:
    summary = EXACT_FACT_SUMMARY_200
    replacements = (
        ("2.1％", "2.1％<!-- claim: V3-MAIN-CAP19-SALES-YOY -->"),
        ("1.9％", "1.9％<!-- claim: V3-MAIN-CAP19-OPERATING-PROFIT-YOY -->"),
        ("利益率は低下した", "利益率は低下<!-- claim: V3-MAIN-CAP19-MARGIN-DIRECTION -->した"),
        ("2.5％", "2.5％<!-- claim: V3-CONT-CAP19-SALES-YOY -->"),
        ("6.0％", "6.0％<!-- claim: V3-CONT-CAP19-OPERATING-PROFIT-YOY -->"),
        ("利益率は上昇方向だった", "利益率は上昇方向<!-- claim: V3-CONT-CAP19-MARGIN-DIRECTION -->だった"),
        ("成立しない", "成立しない<!-- claim: V3-CURRENT-HEADLINE-REVERSAL -->"),
        ("標本数が少なく", "標本数が少なく<!-- claim: V3-CONT-SMALLER-SAMPLE -->"),
        ("公式注記がある", "公式注記がある<!-- claim: V3-CONT-PROFIT-SE-NOT-CALCULATED -->"),
    )
    for old, new in replacements:
        if summary.count(old) != 1:
            raise AssertionError(f"Frozen summary replacement drift: {old}")
        summary = summary.replace(old, new)
    if _strip_html_comments(summary) != EXACT_FACT_SUMMARY_200:
        raise AssertionError("Claim comments changed visible summary text")
    return summary


def render_sample_sensitivity_article(
    *,
    continuing: "ContinuingSampleAnalysis",
    claims_v3: pd.DataFrame,
    chart_paths: Iterable[str | Path] = PUBLIC_SAMPLE_CHART_FILENAMES,
) -> str:
    """Render the one-claim public article; the four-item bridge is excluded."""
    decision = select_stage3_publication_decision(
        continuing=continuing,
        # The sample gate is evaluated before this sentinel is inspected.
        nonoperating=_NonOperatingNotUsed(),  # type: ignore[arg-type]
    )
    if decision != PUBLISH_SAMPLE_CONSTRUCTION_SENSITIVITY:
        raise ValueError("Sample-sensitivity publication gate is not satisfied")
    claim_errors = validate_claims_v3(claims_v3)
    if claim_errors:
        raise ValueError(f"Cannot render article with invalid claims: {claim_errors}")
    paths = [str(Path(path).as_posix()) for path in chart_paths]
    if tuple(Path(path).name for path in paths) != PUBLIC_SAMPLE_CHART_FILENAMES:
        raise ValueError("Sample article must embed exactly the two registered public charts")
    summary = _summary_with_claim_comments()
    article = f"""# 標本を替えると、利益率の方向は反転した

<!-- central-candidate: {SAMPLE_CANDIDATE_ID} -->
<!-- central-claim: V3-CURRENT-HEADLINE-REVERSAL -->
<!-- article-mode: SAMPLE_CONSTRUCTION_SENSITIVITY_ONLY -->

## 事実だけによる200字要約

{summary}

## 調査対象と結論

調査対象は、財務省「法人企業統計調査・四半期別調査」の法人企業で、ここでは金融業・保険業を除く。結論は一つだ。同じ対象期でも、通常系列から継続標本系列へ替えると、この規模別見出しの成立可否が反転する<!-- claim: V3-CURRENT-HEADLINE-REVERSAL -->。

通常系列は利益と売上高の水準から方向を確認した。継続標本系列は利益率水準も前年差ポイントも示さず、売上高前年同期比と営業利益前年同期比から作った上昇・低下の方向代理だけを使った<!-- claim: V3-CONT-CAP19-MARGIN-DIRECTION -->。

![通常系列と継続標本系列の利益率方向]({paths[0]})

## 長期でも無視できない反転頻度

規模別見出しの成立可否は11/41四半期（26.83％）<!-- claim: V3-HEADLINE-REVERSAL-FREQUENCY -->で異なった。資本金1千万円以上1億円未満層の利益率方向だけでは16/41四半期（39.02％）<!-- claim: V3-SMALL-MARGIN-REVERSAL-FREQUENCY -->で反転した。これは原因の推定ではなく、標本構成に対する見出しの感度を記述したものだ。

![判定反転の歴史的頻度]({paths[1]})

## 解釈上の限界

継続標本は通常系列より標本数が少ない<!-- claim: V3-CONT-SMALLER-SAMPLE -->。また、公表資料では営業利益と経常利益の標準誤差率は算出されていない<!-- claim: V3-CONT-PROFIT-SE-NOT-CALCULATED -->。したがって、反転の頻度は不確実性を解消するものではない。また、統計だけから企業行動の原因は断定しない。

## 使用データと再現方法

数値の正本は e-Stat 表1と財務省の継続標本参考系列 `keizoku.pdf` である。取得物はハッシュ付きで凍結し、`build_continuing_sample_analysis()` から `build_claims_v3()`、`build_stage3_charts()` の順に再計算する。本文の数値は `claims_v3.csv` の PASS 行と明示的な claim ID で紐付ける。

## 外部資料で追加検証すべき仮説

【HYPOTHESIS】通常系列と継続標本系列の差が、標本の入れ替わり、ウェイト、企業構成のどれと関連するかは本統計だけでは分からない。財務省の標本設計資料と追加の公式集計で別途検証する必要がある。
"""
    audit = validate_stage3_article(article, claims_v3)
    if audit.status != "PASS":
        raise ValueError(f"Rendered article failed publication audit: {audit.failed_check_ids}")
    return article


class _NonOperatingNotUsed:
    """Sentinel proving that the sample gate does not inspect bridge inputs."""

    identity_checks = pd.DataFrame()


def _strip_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def _extract_summary(article: str) -> str | None:
    match = re.search(
        r"^## 事実だけによる200字要約\s*\n(.*?)(?=^## |\Z)",
        article,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        return None
    return match.group(1).strip()


def _check(
    rows: list[dict[str, str]], check_id: str, passed: bool, detail: str
) -> None:
    rows.append(
        {"check_id": check_id, "status": "PASS" if passed else "FAIL", "detail": detail}
    )


def _statistical_number_links(article: str, claims: pd.DataFrame) -> tuple[bool, str]:
    # Only statistical value patterns are included.  Table numbers, claim IDs,
    # paths, and the heading's character count are metadata rather than claims.
    pattern = re.compile(
        r"[+\-−]?[0-9][0-9,]*(?:\.[0-9]+)?(?:/[0-9][0-9,]*)?"
        r"\s*(?:％|%|億円|兆円|四半期|ポイント|pt)"
    )
    claim_by_id = claims.set_index("claim_id")
    failures: list[str] = []
    for match in pattern.finditer(article):
        # Capital-bracket thresholds are definitional metadata, audited by the
        # formal-first-mention check below.  They are not observed monetary
        # amounts and must not be mistaken for an article result measured in
        # oku-yen.
        if match.group(0).endswith("億円") and re.match(
            r"(?:以上|未満)", article[match.end() :]
        ):
            continue
        following = article[match.end() : match.end() + 140]
        linked = re.search(r"<!--\s*claim:\s*([^\s]+)\s*-->", following)
        if linked is None:
            failures.append(f"UNLINKED:{match.group(0)}")
            continue
        claim_id = linked.group(1)
        if claim_id not in claim_by_id.index:
            failures.append(f"UNKNOWN:{match.group(0)}:{claim_id}")
            continue
        row = claim_by_id.loc[claim_id]
        if isinstance(row, pd.DataFrame):
            failures.append(f"DUPLICATE:{match.group(0)}:{claim_id}")
            continue
        if row["verification_status"] != "PASS":
            failures.append(f"NONPASS:{match.group(0)}:{claim_id}")
            continue
        token = match.group(0).replace(",", "").replace("−", "-").strip()
        number_part = re.match(r"[+\-]?[0-9]+(?:\.[0-9]+)?(?:/[0-9]+)?", token)
        if number_part is None:  # pragma: no cover - guarded by the outer regex
            failures.append(f"UNPARSEABLE:{match.group(0)}:{claim_id}")
            continue
        raw_number = number_part.group(0)
        if "/" in raw_number:
            numerator, denominator = (int(part) for part in raw_number.split("/"))
            claim_numerator = pd.to_numeric(
                pd.Series([row.get("numerator")]), errors="coerce"
            ).iloc[0]
            claim_denominator = pd.to_numeric(
                pd.Series([row.get("denominator")]), errors="coerce"
            ).iloc[0]
            if pd.isna(claim_numerator) or pd.isna(claim_denominator):
                failures.append(f"NO_FREQUENCY_FIELDS:{match.group(0)}:{claim_id}")
            elif (
                numerator != int(float(claim_numerator))
                or denominator != int(float(claim_denominator))
            ):
                failures.append(f"VALUE_MISMATCH:{match.group(0)}:{claim_id}")
        else:
            claim_value = pd.to_numeric(
                pd.Series([row.get("numeric_value")]), errors="coerce"
            ).iloc[0]
            digits = row.get("rounding_digits")
            if pd.isna(claim_value) or pd.isna(digits):
                failures.append(f"NO_NUMERIC_VALUE:{match.group(0)}:{claim_id}")
            elif round(abs(float(claim_value)), int(float(digits))) != abs(
                float(raw_number)
            ):
                failures.append(f"VALUE_MISMATCH:{match.group(0)}:{claim_id}")
    return not failures, ";".join(failures) if failures else "all statistical values linked"


def validate_stage3_article(
    article: str,
    claims_v3: pd.DataFrame,
) -> Stage3PublicationAudit:
    """Audit the single-claim article and fail closed on any contract breach."""
    rows: list[dict[str, str]] = []
    claim_errors = validate_claims_v3(claims_v3)
    _check(rows, "claims_v3_integrity", not claim_errors, str(claim_errors) or "complete explicit registry")

    central_candidates = re.findall(r"<!--\s*central-candidate:\s*([^\s]+)\s*-->", article)
    central_claims = re.findall(r"<!--\s*central-claim:\s*([^\s]+)\s*-->", article)
    _check(
        rows,
        "single_central_claim",
        central_candidates == [SAMPLE_CANDIDATE_ID]
        and central_claims == ["V3-CURRENT-HEADLINE-REVERSAL"],
        f"candidates={central_candidates}; claims={central_claims}",
    )

    referenced = set(re.findall(r"<!--\s*claim:\s*([^\s]+)\s*-->", article))
    known = set(claims_v3["claim_id"].astype(str)) if "claim_id" in claims_v3 else set()
    reference_rows = claims_v3.loc[
        claims_v3["claim_id"].astype(str).isin(referenced)
    ] if known else pd.DataFrame()
    references_pass = (
        bool(referenced)
        and referenced <= known
        and len(reference_rows) == len(referenced)
        and reference_rows["verification_status"].eq("PASS").all()
        and reference_rows["article_use"].astype(bool).all()
    )
    _check(
        rows,
        "article_claim_references",
        references_pass,
        f"referenced={sorted(referenced)}; unknown={sorted(referenced - known)}",
    )
    candidate_isolation = (
        not reference_rows.empty
        and reference_rows["candidate_id"].eq(SAMPLE_CANDIDATE_ID).all()
    )
    _check(
        rows,
        "candidate_isolation",
        candidate_isolation,
        "article references sample-sensitivity claims only",
    )

    summary = _extract_summary(article)
    visible_summary = _strip_html_comments(summary or "")
    _check(
        rows,
        "exact_200_character_fact_summary",
        visible_summary == EXACT_FACT_SUMMARY_200 and len(visible_summary) == 200,
        f"visible_characters={len(visible_summary)}",
    )

    number_links_pass, number_link_detail = _statistical_number_links(article, claims_v3)
    _check(rows, "all_statistical_numbers_linked", number_links_pass, number_link_detail)

    figures = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", article)
    figure_names = tuple(Path(path).name for path in figures)
    _check(
        rows,
        "principal_figure_limit_and_set",
        len(figures) <= 3 and figure_names == PUBLIC_SAMPLE_CHART_FILENAMES,
        f"figure_count={len(figures)}; names={figure_names}",
    )

    formal = CAPITAL_SCOPE_NAMES["19"]
    small_fragment_index = article.find("1億円未満")
    formal_index = article.find(formal)
    _check(
        rows,
        "scope_and_formal_capital_first_mention",
        "調査対象" in article
        and ("金融業・保険業を除" in article or "金融・保険業を除" in article)
        and formal_index >= 0
        and small_fragment_index == formal_index + formal.index("1億円未満"),
        f"formal_index={formal_index}; fragment_index={small_fragment_index}",
    )

    proxy_guard = (
        "継続標本系列は利益率水準も前年差ポイントも示さず" in article
        and "方向代理" in article
        and not re.search(r"継続標本[^\n]{0,80}[+\-]?[0-9.]+\s*(?:pt|ポイント)", article)
    )
    _check(rows, "continuing_margin_direction_only", proxy_guard, "no fabricated continuing-sample pp change")

    no_bridge = not any(
        term in article
        for term in (
            "営業外損益",
            "営業利益外差額",
            "受取利息等",
            "その他の営業外収益",
            "支払利息等",
            STAGE3_CHART_FILENAMES[2],
        )
    )
    _check(rows, "no_nonoperating_candidate_mixing", no_bridge, "bridge candidate excluded")

    hypothesis_guard = (
        "【HYPOTHESIS】" in article
        and "統計だけから企業行動の原因は断定しない" in article
        and "外部資料で追加検証すべき仮説" in article
    )
    _check(rows, "fact_calc_hypothesis_guardrail", hypothesis_guard, "causal interpretation remains a labelled hypothesis")

    checks = pd.DataFrame(rows)
    return Stage3PublicationAudit(
        status="PASS" if checks["status"].eq("PASS").all() else "FAIL",
        checks=checks,
    )


def render_candidate_headlines_v3(decision: str) -> str:
    """Render adopted/rejected headlines without merging the two candidates."""
    if decision not in VALID_STAGE3_DECISIONS:
        raise ValueError(f"Unknown Stage 3 decision: {decision}")
    rows = [
        "# 第3段階 記事見出し判定",
        "",
        f"**最終判定: {decision}**",
        "",
        "| 状態 | 候補 | 見出し | 理由 |",
        "|---|---|---|---|",
    ]
    sample_status = "採用" if decision == PUBLISH_SAMPLE_CONSTRUCTION_SENSITIVITY else "棄却"
    bridge_status = "採用" if decision == PUBLISH_FULL_NONOPERATING_BRIDGE_SNAPSHOT else "棄却"
    rows.extend(
        [
            f"| {sample_status} | {SAMPLE_CANDIDATE_ID} | 標本を替えると、利益率の方向は反転した | 通常系列と継続標本系列の定義感度を一つの主張とする。 |",
            f"| {bridge_status} | {NONOPERATING_CANDIDATE_ID} | 経常増益の営業利益外差額を4項目に分ける | 四項目恒等式は検証済みだが、標本感度記事には混在させない。 |",
            "| 禁止・棄却 | LEGACY_SMALL_CAPITAL_MARGIN | 小規模資本金層だけ利益率低下 | 継続標本で方向が反転するため公開不可。 |",
            "",
        ]
    )
    return "\n".join(rows)


def render_decision_v3(decision: str) -> str:
    if decision not in VALID_STAGE3_DECISIONS:
        raise ValueError(f"Unknown Stage 3 decision: {decision}")
    central = {
        PUBLISH_SAMPLE_CONSTRUCTION_SENSITIVITY: SAMPLE_CANDIDATE_ID,
        PUBLISH_FULL_NONOPERATING_BRIDGE_SNAPSHOT: NONOPERATING_CANDIDATE_ID,
        ARCHIVE_NO_ROBUST_STORY: "NONE",
    }[decision]
    return (
        "# 第3段階 最終判定\n\n"
        f"**{decision}**\n\n"
        f"central_candidate_id: `{central}`\n\n"
        "一つの公開記事に複数候補を混在させない。\n"
    )
