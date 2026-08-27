from __future__ import annotations

import json
import math
from typing import Any

import pandas as pd

from .contributions import positive_contribution_concentration


CLAIM_COLUMNS = [
    "claim_id",
    "article_anchor",
    "claim_usage",
    "chart_id",
    "series_key",
    "section",
    "claim_type",
    "claim_text",
    "metric_id",
    "period",
    "coverage_scope",
    "filters_json",
    "value",
    "unit",
    "display_value",
    "formula",
    "source_ids",
    "verification_status",
    "failure_reason",
]


def _finite(value: object) -> bool:
    return value is not None and not pd.isna(value) and math.isfinite(float(value))


def format_trillion(oku_yen: float) -> str:
    return f"{oku_yen / 10_000.0:,.1f}兆円"


def format_oku(oku_yen: float) -> str:
    return f"{oku_yen:,.0f}億円"


def format_pct(value: float, signed: bool = False) -> str:
    decimals = 2 if 0 < abs(value) < 0.1 else 1
    return f"{value:+.{decimals}f}%" if signed else f"{value:.{decimals}f}%"


def format_man_yen(value: float) -> str:
    return f"{value:,.1f}万円/人"


def money_claim_fields(oku_yen: float) -> tuple[float, str, str]:
    """Return an exact claim value whose numeric unit matches its display unit."""
    if abs(oku_yen) < 10_000.0:
        return float(oku_yen), "億円", format_oku(oku_yen)
    return float(oku_yen) / 10_000.0, "兆円", format_trillion(oku_yen)


class ClaimBuilder:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.sequence = 0

    def numeric(
        self,
        *,
        anchor: str,
        section: str,
        claim_type: str,
        claim_text: str,
        metric_id: str,
        period: str,
        coverage_scope: str,
        value: float | None,
        unit: str,
        display_value: str | None,
        formula: str,
        source_ids: list[str],
        filters: dict[str, Any],
        claim_usage: str = "ARTICLE_TEXT",
        chart_id: str = "",
        series_key: str = "",
    ) -> str:
        self.sequence += 1
        claim_id = f"C-{self.sequence:03d}"
        valid = _finite(value) and bool(display_value)
        self.rows.append(
            {
                "claim_id": claim_id,
                "article_anchor": anchor,
                "claim_usage": claim_usage,
                "chart_id": chart_id,
                "series_key": series_key,
                "section": section,
                "claim_type": claim_type,
                "claim_text": claim_text,
                "metric_id": metric_id,
                "period": period,
                "coverage_scope": coverage_scope,
                "filters_json": json.dumps(filters, ensure_ascii=False, sort_keys=True),
                "value": value,
                "unit": unit,
                "display_value": display_value or "",
                "formula": formula,
                "source_ids": ";".join(source_ids),
                "verification_status": "PASS" if valid else "FAIL",
                "failure_reason": "" if valid else "Missing/non-finite input or display value",
            }
        )
        return claim_id

    def hypothesis(self, *, anchor: str, claim_text: str) -> str:
        self.sequence += 1
        claim_id = f"H-{self.sequence:03d}"
        self.rows.append(
            {
                "claim_id": claim_id,
                "article_anchor": anchor,
                "claim_usage": "ARTICLE_TEXT",
                "chart_id": "",
                "series_key": "",
                "section": "追加検証仮説",
                "claim_type": "HYPOTHESIS",
                "claim_text": claim_text,
                "metric_id": "",
                "period": "",
                "coverage_scope": "",
                "filters_json": "{}",
                "value": None,
                "unit": "",
                "display_value": "",
                "formula": "External primary-source verification required before causal assertion",
                "source_ids": "",
                "verification_status": "HYPOTHESIS_LABELLED",
                "failure_reason": "",
            }
        )
        return claim_id

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=CLAIM_COLUMNS)


def _find_total(
    processed: pd.DataFrame,
    metric_id: str,
    *,
    coverage_scope: str = "EXCL_FINANCE_INSURANCE",
    source_table_number: str = "1",
) -> pd.Series:
    subset = processed.loc[
        processed["coverage_scope"].eq(coverage_scope)
        & processed["source_table_number"].astype(str).eq(source_table_number)
        & processed["capital_bucket"].eq("ALL_CAPITAL")
        & processed["metric_id"].eq(metric_id)
    ]
    if coverage_scope == "EXCL_FINANCE_INSURANCE":
        subset = subset.loc[subset["industry_bucket"].eq("ALL_NONFINANCIAL")]
    if subset.empty:
        raise KeyError(f"Missing headline observation for {metric_id}/{coverage_scope}")
    return subset.iloc[0]


def _top_industry(contributions: pd.DataFrame, metric_id: str) -> pd.Series:
    subset = contributions.loc[
        contributions["metric_id"].eq(metric_id)
        & contributions["raw_yoy_delta_oku_yen"].notna()
    ].sort_values("raw_yoy_delta_oku_yen", ascending=False, kind="stable")
    if subset.empty:
        raise KeyError(f"No industry contribution rows for {metric_id}")
    return subset.iloc[0]


def _top_capital(contributions: pd.DataFrame, metric_id: str) -> pd.Series:
    subset = contributions.loc[
        contributions["metric_id"].eq(metric_id)
        & contributions["raw_yoy_delta_oku_yen"].notna()
    ].sort_values("raw_yoy_delta_oku_yen", ascending=False, kind="stable")
    if subset.empty:
        raise KeyError(f"No capital contribution rows for {metric_id}")
    return subset.iloc[0]


def build_claims(
    processed: pd.DataFrame,
    industry_contributions: pd.DataFrame,
    capital_contributions: pd.DataFrame,
) -> pd.DataFrame:
    """Create the sole numeric source for the article renderer."""
    b = ClaimBuilder()
    period = str(processed["period"].dropna().iloc[0])
    headline = {
        metric: _find_total(processed, metric)
        for metric in (
            "sales",
            "operating_profit",
            "ordinary_profit",
            "capex_including_software",
            "capex_excluding_software",
            "software_capex_derived",
            "employee_pay_per_person_approx",
            "employee_total_pay_derived",
            "employee_count",
            "cash_and_deposits",
            "total_borrowings_derived",
            "interest_expense",
            "ordinary_minus_operating",
        )
    }
    common_filters = {
        "industry_bucket": "ALL_NONFINANCIAL",
        "capital_bucket": "ALL_CAPITAL",
    }
    source_table1 = ["table1_nonfinancial_raw"]

    for metric_id, label in (
        ("sales", "売上高"),
        ("operating_profit", "営業利益"),
        ("ordinary_profit", "経常利益"),
        ("capex_including_software", "設備投資（ソフトウェア込み）"),
    ):
        row = headline[metric_id]
        current_value, current_unit, current_display = money_claim_fields(
            row["raw_value_oku_yen"]
        )
        b.numeric(
            anchor="fact_summary",
            section="要約",
            claim_type="FACT",
            claim_text=f"{label}の当期水準",
            metric_id=metric_id,
            period=period,
            coverage_scope="EXCL_FINANCE_INSURANCE",
            value=current_value,
            unit=current_unit,
            display_value=current_display,
            formula="e-Stat source value (百万円) / 100 / 10,000",
            source_ids=source_table1,
            filters=common_filters,
        )
        delta_value, delta_unit, delta_display = money_claim_fields(
            row["raw_yoy_delta_oku_yen"]
        )
        b.numeric(
            anchor="fact_summary",
            section="要約",
            claim_type="CALC",
            claim_text=f"{label}の前年同期差",
            metric_id=metric_id,
            period=period,
            coverage_scope="EXCL_FINANCE_INSURANCE",
            value=delta_value,
            unit=delta_unit,
            display_value=delta_display,
            formula="current raw value - year-ago raw value",
            source_ids=source_table1,
            filters=common_filters,
        )
        b.numeric(
            anchor="fact_summary",
            section="要約",
            claim_type="CALC",
            claim_text=f"{label}の前年同期比",
            metric_id=metric_id,
            period=period,
            coverage_scope="EXCL_FINANCE_INSURANCE",
            value=row["raw_yoy_pct"],
            unit="%",
            display_value=format_pct(row["raw_yoy_pct"], signed=True),
            formula="(current / year-ago - 1) × 100",
            source_ids=source_table1,
            filters=common_filters,
        )

    for metric_id, label in (
        ("sales", "売上高"),
        ("operating_profit", "営業利益"),
        ("ordinary_profit", "経常利益"),
        ("capex_excluding_software", "設備投資（ソフトウェア除く）"),
        ("capex_including_software", "設備投資（ソフトウェア込み）"),
    ):
        row = headline[metric_id]
        b.numeric(
            anchor="seasonal",
            section="季節調整",
            claim_type="CALC",
            claim_text=f"{label}の季節調整済み前期比",
            metric_id=metric_id,
            period=period,
            coverage_scope="EXCL_FINANCE_INSURANCE",
            value=row["sa_qoq_pct"],
            unit="%",
            display_value=format_pct(row["sa_qoq_pct"], signed=True),
            formula="(seasonally adjusted current / prior quarter - 1) × 100",
            source_ids=["table4_nonfinancial_sa", "mof_published_sa_rates"],
            filters=common_filters,
        )

    top_industry = _top_industry(industry_contributions, "operating_profit")
    top_industry_value, top_industry_unit, top_industry_display = money_claim_fields(
        top_industry["raw_yoy_delta_oku_yen"]
    )
    b.numeric(
        anchor="finding_concentration",
        section="独自発見",
        claim_type="CALC",
        claim_text=f"{top_industry['industry_name']}の営業利益前年差",
        metric_id="operating_profit",
        period=period,
        coverage_scope="EXCL_FINANCE_INSURANCE",
        value=top_industry_value,
        unit=top_industry_unit,
        display_value=top_industry_display,
        formula="industry current operating profit - year-ago operating profit",
        source_ids=source_table1,
        filters={"industry_name": top_industry["industry_name"], "capital_bucket": "ALL_CAPITAL"},
    )
    b.numeric(
        anchor="finding_concentration",
        section="独自発見",
        claim_type="CALC",
        claim_text=f"{top_industry['industry_name']}の全体営業利益前年差への寄与率",
        metric_id="operating_profit",
        period=period,
        coverage_scope="EXCL_FINANCE_INSURANCE",
        value=top_industry["contribution_pct_to_net_change"],
        unit="%",
        display_value=format_pct(top_industry["contribution_pct_to_net_change"]),
        formula="industry operating-profit delta / all-industry operating-profit delta × 100",
        source_ids=source_table1,
        filters={"industry_name": top_industry["industry_name"], "capital_bucket": "ALL_CAPITAL"},
    )
    concentration = positive_contribution_concentration(industry_contributions)
    for top_n in (1, 3, 5):
        record = concentration.loc[concentration["top_n"].eq(top_n)].iloc[0]
        b.numeric(
            anchor="finding_concentration",
            section="独自発見",
            claim_type="CALC",
            claim_text=f"営業利益の増益寄与・上位{top_n}業種集中度",
            metric_id="operating_profit",
            period=period,
            coverage_scope="EXCL_FINANCE_INSURANCE",
            value=record["share_of_gross_positive_pct"],
            unit="%",
            display_value=format_pct(record["share_of_gross_positive_pct"]),
            formula="sum(top-N positive industry deltas) / gross positive industry deltas × 100",
            source_ids=source_table1,
            filters={"top_n": top_n, "industry_level": "published_major_industry"},
        )

    top_capital = _top_capital(capital_contributions, "operating_profit")
    top_capital_value, top_capital_unit, top_capital_display = money_claim_fields(
        top_capital["raw_yoy_delta_oku_yen"]
    )
    b.numeric(
        anchor="finding_capital",
        section="独自発見",
        claim_type="CALC",
        claim_text=f"{top_capital['capital_size_name']}の営業利益前年差",
        metric_id="operating_profit",
        period=period,
        coverage_scope="EXCL_FINANCE_INSURANCE",
        value=top_capital_value,
        unit=top_capital_unit,
        display_value=top_capital_display,
        formula="capital-size current operating profit - year-ago value",
        source_ids=source_table1,
        filters={"capital_size_name": top_capital["capital_size_name"]},
    )
    b.numeric(
        anchor="finding_capital",
        section="独自発見",
        claim_type="CALC",
        claim_text=f"{top_capital['capital_size_name']}の営業利益前年差への寄与率",
        metric_id="operating_profit",
        period=period,
        coverage_scope="EXCL_FINANCE_INSURANCE",
        value=top_capital["contribution_pct_to_net_change"],
        unit="%",
        display_value=format_pct(top_capital["contribution_pct_to_net_change"]),
        formula="capital-size operating-profit delta / all-capital delta × 100",
        source_ids=source_table1,
        filters={"capital_size_name": top_capital["capital_size_name"]},
    )

    operating = headline["operating_profit"]
    ordinary = headline["ordinary_profit"]
    gap = headline["ordinary_minus_operating"]
    gap_value, gap_unit, gap_display = money_claim_fields(gap["raw_value_oku_yen"])
    b.numeric(
        anchor="finding_profit_gap",
        section="独自発見",
        claim_type="CALC",
        claim_text="経常利益と営業利益の水準差",
        metric_id="ordinary_minus_operating",
        period=period,
        coverage_scope="EXCL_FINANCE_INSURANCE",
        value=gap_value,
        unit=gap_unit,
        display_value=gap_display,
        formula="ordinary profit - operating profit",
        source_ids=source_table1,
        filters=common_filters,
    )
    gap_delta_value, gap_delta_unit, gap_delta_display = money_claim_fields(
        gap["raw_yoy_delta_oku_yen"]
    )
    b.numeric(
        anchor="finding_profit_gap",
        section="独自発見",
        claim_type="CALC",
        claim_text="経常利益前年差と営業利益前年差の差",
        metric_id="ordinary_minus_operating",
        period=period,
        coverage_scope="EXCL_FINANCE_INSURANCE",
        value=gap_delta_value,
        unit=gap_delta_unit,
        display_value=gap_delta_display,
        formula="ordinary-profit yoy delta - operating-profit yoy delta",
        source_ids=source_table1,
        filters=common_filters,
    )
    for metric_id, label in (
        ("operating_profit", "売上高営業利益率"),
        ("ordinary_profit", "売上高経常利益率"),
    ):
        row = headline[metric_id]
        margin = row["raw_value_oku_yen"] / headline["sales"]["raw_value_oku_yen"] * 100
        b.numeric(
            anchor="margin",
            section="利益率",
            claim_type="CALC",
            claim_text=label,
            metric_id=metric_id,
            period=period,
            coverage_scope="EXCL_FINANCE_INSURANCE",
            value=margin,
            unit="%",
            display_value=format_pct(margin),
            formula=f"{metric_id} / sales × 100",
            source_ids=source_table1,
            filters=common_filters,
        )

    software = headline["software_capex_derived"]
    software_value, software_unit, software_display = money_claim_fields(
        software["raw_value_oku_yen"]
    )
    b.numeric(
        anchor="software",
        section="設備投資",
        claim_type="CALC",
        claim_text="ソフトウェア投資の逆算値",
        metric_id="software_capex_derived",
        period=period,
        coverage_scope="EXCL_FINANCE_INSURANCE",
        value=software_value,
        unit=software_unit,
        display_value=software_display,
        formula="capex including software - capex excluding software",
        source_ids=source_table1,
        filters=common_filters,
    )
    b.numeric(
        anchor="software",
        section="設備投資",
        claim_type="CALC",
        claim_text="ソフトウェア投資逆算値の前年同期比",
        metric_id="software_capex_derived",
        period=period,
        coverage_scope="EXCL_FINANCE_INSURANCE",
        value=software["raw_yoy_pct"],
        unit="%",
        display_value=format_pct(software["raw_yoy_pct"], signed=True),
        formula="(derived software investment / year-ago - 1) × 100",
        source_ids=source_table1,
        filters=common_filters,
    )

    for metric_id, label in (
        ("employee_pay_per_person_approx", "従業員1人当たり給与総額の概算"),
        ("cash_and_deposits", "現預金の前年差"),
        ("total_borrowings_derived", "借入金合計の前年差"),
        ("interest_expense", "支払利息等の前年差"),
    ):
        row = headline[metric_id]
        if metric_id == "employee_pay_per_person_approx":
            value = row["source_value"]
            unit = "万円/人"
            display = format_man_yen(value)
        else:
            value, unit, display = money_claim_fields(row["raw_yoy_delta_oku_yen"])
        b.numeric(
            anchor="allocation",
            section="配分",
            claim_type="CALC",
            claim_text=label,
            metric_id=metric_id,
            period=period,
            coverage_scope="EXCL_FINANCE_INSURANCE",
            value=value,
            unit=unit,
            display_value=display,
            formula=(
                "(employee wages + bonuses) × 100 / employee count"
                if metric_id == "employee_pay_per_person_approx"
                else "current raw value - year-ago raw value"
            ),
            source_ids=source_table1,
            filters=common_filters,
        )

    for metric_id, label in (
        ("employee_total_pay_derived", "従業員給与・賞与合計の前年同期比"),
        ("employee_count", "従業員数の前年同期比"),
    ):
        row = headline[metric_id]
        b.numeric(
            anchor="allocation",
            section="配分",
            claim_type="CALC",
            claim_text=label,
            metric_id=metric_id,
            period=period,
            coverage_scope="EXCL_FINANCE_INSURANCE",
            value=row["raw_yoy_pct"],
            unit="%",
            display_value=format_pct(row["raw_yoy_pct"], signed=True),
            formula="(current raw value / year-ago raw value - 1) × 100",
            source_ids=source_table1,
            filters=common_filters,
        )

    inclusive_ordinary = _find_total(
        processed,
        "ordinary_profit",
        coverage_scope="INCL_FINANCE_INSURANCE",
        source_table_number="2",
    )
    inclusive_value, inclusive_unit, inclusive_display = money_claim_fields(
        inclusive_ordinary["raw_value_oku_yen"]
    )
    b.numeric(
        anchor="scope",
        section="調査範囲",
        claim_type="FACT",
        claim_text="金融・保険業込み全産業の経常利益",
        metric_id="ordinary_profit",
        period=period,
        coverage_scope="INCL_FINANCE_INSURANCE",
        value=inclusive_value,
        unit=inclusive_unit,
        display_value=inclusive_display,
        formula="e-Stat Table 2 source value (百万円) / 100 / 10,000",
        source_ids=["table2_all_industries_raw"],
        filters={"capital_bucket": "ALL_CAPITAL"},
    )

    def chart_numeric(
        *,
        chart_id: str,
        series_key: str,
        claim_text: str,
        metric_id: str,
        value: float,
        unit: str,
        display_value: str,
        formula: str,
        source_ids: list[str],
        filters: dict[str, Any],
    ) -> None:
        b.numeric(
            anchor="chart_input",
            section="図表",
            claim_type="CALC",
            claim_text=claim_text,
            metric_id=metric_id,
            period=period,
            coverage_scope="EXCL_FINANCE_INSURANCE",
            value=value,
            unit=unit,
            display_value=display_value,
            formula=formula,
            source_ids=source_ids,
            filters=filters,
            claim_usage="CHART_INPUT",
            chart_id=chart_id,
            series_key=series_key,
        )

    op_industries = industry_contributions.loc[
        industry_contributions["metric_id"].eq("operating_profit")
    ]
    for row in op_industries.itertuples():
        value = float(row.raw_yoy_delta_oku_yen) / 10_000.0
        chart_numeric(
            chart_id="operating_profit_industry_contribution",
            series_key=str(row.industry_name),
            claim_text=f"業種別営業利益前年差（図表）: {row.industry_name}",
            metric_id="operating_profit",
            value=value,
            unit="兆円",
            display_value=f"{value:+.2f}兆円",
            formula="industry operating-profit yoy delta (億円) / 10,000",
            source_ids=source_table1,
            filters={"industry_name": row.industry_name, "capital_bucket": "ALL_CAPITAL"},
        )

    op_capital = capital_contributions.loc[
        capital_contributions["metric_id"].eq("operating_profit")
    ]
    for row in op_capital.itertuples():
        value = float(row.raw_yoy_delta_oku_yen) / 10_000.0
        chart_numeric(
            chart_id="operating_profit_capital_contribution",
            series_key=str(row.capital_size_name),
            claim_text=f"資本金規模別営業利益前年差（図表）: {row.capital_size_name}",
            metric_id="operating_profit",
            value=value,
            unit="兆円",
            display_value=f"{value:+.2f}兆円",
            formula="capital-size operating-profit yoy delta (億円) / 10,000",
            source_ids=source_table1,
            filters={"capital_size_name": row.capital_size_name},
        )

    for metric_id, series_key, value, unit, display, formula in (
        (
            "operating_profit",
            "operating_margin",
            operating["raw_value_oku_yen"] / headline["sales"]["raw_value_oku_yen"] * 100,
            "%",
            format_pct(operating["raw_value_oku_yen"] / headline["sales"]["raw_value_oku_yen"] * 100),
            "operating profit / sales × 100",
        ),
        (
            "ordinary_profit",
            "ordinary_margin",
            ordinary["raw_value_oku_yen"] / headline["sales"]["raw_value_oku_yen"] * 100,
            "%",
            format_pct(ordinary["raw_value_oku_yen"] / headline["sales"]["raw_value_oku_yen"] * 100),
            "ordinary profit / sales × 100",
        ),
        (
            "operating_profit",
            "operating_level",
            operating["raw_value_oku_yen"] / 10_000.0,
            "兆円",
            format_trillion(operating["raw_value_oku_yen"]),
            "operating profit (億円) / 10,000",
        ),
        (
            "ordinary_profit",
            "ordinary_level",
            ordinary["raw_value_oku_yen"] / 10_000.0,
            "兆円",
            format_trillion(ordinary["raw_value_oku_yen"]),
            "ordinary profit (億円) / 10,000",
        ),
        (
            "ordinary_minus_operating",
            "profit_gap",
            gap["raw_value_oku_yen"] / 10_000.0,
            "兆円",
            format_trillion(gap["raw_value_oku_yen"]),
            "(ordinary profit - operating profit) (億円) / 10,000",
        ),
    ):
        chart_numeric(
            chart_id="profit_margin_and_gap",
            series_key=series_key,
            claim_text=f"利益率・利益差図表入力: {series_key}",
            metric_id=metric_id,
            value=float(value),
            unit=unit,
            display_value=display,
            formula=formula,
            source_ids=source_table1,
            filters=common_filters,
        )

    for metric_id in (
        "capex_including_software",
        "capex_excluding_software",
        "software_capex_derived",
    ):
        row = headline[metric_id]
        chart_numeric(
            chart_id="capex_software_bridge",
            series_key=f"{metric_id}:level",
            claim_text=f"設備投資比較図表の水準: {metric_id}",
            metric_id=metric_id,
            value=float(row["raw_value_oku_yen"]) / 10_000.0,
            unit="兆円",
            display_value=format_trillion(row["raw_value_oku_yen"]),
            formula="raw value (億円) / 10,000",
            source_ids=source_table1,
            filters=common_filters,
        )
        chart_numeric(
            chart_id="capex_software_bridge",
            series_key=f"{metric_id}:yoy_pct",
            claim_text=f"設備投資比較図表の前年同期比: {metric_id}",
            metric_id=metric_id,
            value=float(row["raw_yoy_pct"]),
            unit="%",
            display_value=format_pct(row["raw_yoy_pct"], signed=True),
            formula="(current raw value / year-ago raw value - 1) × 100",
            source_ids=source_table1,
            filters=common_filters,
        )

    for metric_id in (
        "operating_profit",
        "employee_total_pay_derived",
        "employee_count",
        "capex_including_software",
    ):
        row = headline[metric_id]
        chart_numeric(
            chart_id="allocation_growth",
            series_key=metric_id,
            claim_text=f"配分比較図表の前年同期比: {metric_id}",
            metric_id=metric_id,
            value=float(row["raw_yoy_pct"]),
            unit="%",
            display_value=format_pct(row["raw_yoy_pct"], signed=True),
            formula="(current raw value / year-ago raw value - 1) × 100",
            source_ids=source_table1,
            filters=common_filters,
        )

    b.hypothesis(
        anchor="hypotheses",
        claim_text="【HYPOTHESIS】製造業の増益にAI関連需要が関与した可能性。企業の受注・販売・投資家向け一次資料で確認が必要。",
    )
    b.hypothesis(
        anchor="hypotheses",
        claim_text="【HYPOTHESIS】サービス業の減益に人件費・人手不足・価格転嫁の差が関与した可能性。業種別の一次資料で確認が必要。",
    )
    b.hypothesis(
        anchor="hypotheses",
        claim_text="【HYPOTHESIS】宿泊・飲食関連の動きにインバウンド需要が関与した可能性。観光庁等の一次統計で確認が必要。",
    )
    return b.frame()
