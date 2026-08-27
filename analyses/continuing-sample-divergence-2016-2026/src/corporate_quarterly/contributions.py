from __future__ import annotations

import math

import pandas as pd

from .constants import (
    CAPITAL_COMPONENT_NAMES,
    MAJOR_INDUSTRY_NAMES,
    PRIMARY_ANALYSIS_METRICS,
)


def _contribution_rate(component: float | None, total: float | None) -> float | None:
    if component is None or total is None or pd.isna(component) or pd.isna(total) or total == 0:
        return None
    return component / total * 100.0


def _base_for_contributions(processed: pd.DataFrame) -> pd.DataFrame:
    return processed.loc[
        processed["coverage_scope"].eq("EXCL_FINANCE_INSURANCE")
        & processed["source_table_number"].eq("1")
        & processed["seasonal_adjustment"].isin(("RAW", "DERIVED_FROM_RAW"))
        & processed["metric_id"].isin((*PRIMARY_ANALYSIS_METRICS, "software_capex_derived"))
    ].copy()


def build_industry_contributions(processed: pd.DataFrame) -> pd.DataFrame:
    base = _base_for_contributions(processed)
    total = base.loc[
        base["industry_bucket"].eq("ALL_NONFINANCIAL")
        & base["capital_bucket"].eq("ALL_CAPITAL")
    ][["metric_id", "raw_yoy_delta_oku_yen", "raw_value_oku_yen"]].rename(
        columns={
            "raw_yoy_delta_oku_yen": "total_yoy_delta_oku_yen",
            "raw_value_oku_yen": "total_value_oku_yen",
        }
    )
    components = base.loc[
        base["industry_name"].isin(MAJOR_INDUSTRY_NAMES)
        & base["capital_bucket"].eq("ALL_CAPITAL")
    ].copy()
    result = components.merge(total, on="metric_id", how="left", validate="many_to_one")
    result["contribution_pct_to_net_change"] = [
        _contribution_rate(component, total_value)
        for component, total_value in zip(
            result["raw_yoy_delta_oku_yen"], result["total_yoy_delta_oku_yen"], strict=True
        )
    ]
    result["rank_by_yoy_delta"] = (
        result.groupby("metric_id")["raw_yoy_delta_oku_yen"]
        .rank(method="first", ascending=False, na_option="bottom")
        .astype("Int64")
    )
    result["component_type"] = "major_industry"
    result["taxonomy"] = "MOF_PUBLISHED_MUTUALLY_EXCLUSIVE_MAJOR_INDUSTRIES"
    result["contribution_denominator"] = "ALL_NONFINANCIAL_NET_YOY_DELTA"
    columns = [
        "release_id",
        "period_code",
        "period",
        "period_end",
        "coverage_scope",
        "seasonal_adjustment",
        "metric_id",
        "metric_label_ja",
        "industry_code",
        "industry_name",
        "raw_value_oku_yen",
        "raw_lag4_value_oku_yen",
        "raw_yoy_delta_oku_yen",
        "raw_yoy_pct",
        "total_yoy_delta_oku_yen",
        "contribution_pct_to_net_change",
        "rank_by_yoy_delta",
        "component_type",
        "taxonomy",
        "contribution_denominator",
        "source_table_number",
        "estat_sid",
        "source_path",
        "source_sha256",
    ]
    return result[columns].sort_values(["metric_id", "rank_by_yoy_delta"], kind="stable").reset_index(drop=True)


def build_capital_contributions(processed: pd.DataFrame) -> pd.DataFrame:
    base = _base_for_contributions(processed)
    total = base.loc[
        base["industry_bucket"].eq("ALL_NONFINANCIAL")
        & base["capital_bucket"].eq("ALL_CAPITAL")
    ][["metric_id", "raw_yoy_delta_oku_yen", "raw_value_oku_yen"]].rename(
        columns={
            "raw_yoy_delta_oku_yen": "total_yoy_delta_oku_yen",
            "raw_value_oku_yen": "total_value_oku_yen",
        }
    )
    components = base.loc[
        base["industry_bucket"].eq("ALL_NONFINANCIAL")
        & base["capital_size_name"].isin(CAPITAL_COMPONENT_NAMES)
    ].copy()
    result = components.merge(total, on="metric_id", how="left", validate="many_to_one")
    result["contribution_pct_to_net_change"] = [
        _contribution_rate(component, total_value)
        for component, total_value in zip(
            result["raw_yoy_delta_oku_yen"], result["total_yoy_delta_oku_yen"], strict=True
        )
    ]
    result["rank_by_yoy_delta"] = (
        result.groupby("metric_id")["raw_yoy_delta_oku_yen"]
        .rank(method="first", ascending=False, na_option="bottom")
        .astype("Int64")
    )
    result["component_type"] = "capital_size"
    result["taxonomy"] = "MOF_THREE_DISJOINT_CAPITAL_SIZE_BUCKETS"
    result["contribution_denominator"] = "ALL_CAPITAL_NET_YOY_DELTA"
    columns = [
        "release_id",
        "period_code",
        "period",
        "period_end",
        "coverage_scope",
        "seasonal_adjustment",
        "metric_id",
        "metric_label_ja",
        "capital_size_code",
        "capital_size_name",
        "raw_value_oku_yen",
        "raw_lag4_value_oku_yen",
        "raw_yoy_delta_oku_yen",
        "raw_yoy_pct",
        "total_yoy_delta_oku_yen",
        "contribution_pct_to_net_change",
        "rank_by_yoy_delta",
        "component_type",
        "taxonomy",
        "contribution_denominator",
        "source_table_number",
        "estat_sid",
        "source_path",
        "source_sha256",
    ]
    return result[columns].sort_values(["metric_id", "rank_by_yoy_delta"], kind="stable").reset_index(drop=True)


def positive_contribution_concentration(
    contributions: pd.DataFrame, metric_id: str = "operating_profit"
) -> pd.DataFrame:
    """Top 1/3/5 shares of gross positive contribution, not net change."""
    data = contributions.loc[
        contributions["metric_id"].eq(metric_id)
        & contributions["raw_yoy_delta_oku_yen"].gt(0)
    ].copy()
    data = data.sort_values("raw_yoy_delta_oku_yen", ascending=False, kind="stable")
    gross_positive = data["raw_yoy_delta_oku_yen"].sum(min_count=1)
    net_change = (
        contributions.loc[contributions["metric_id"].eq(metric_id), "total_yoy_delta_oku_yen"]
        .dropna()
        .iloc[0]
        if not contributions.loc[contributions["metric_id"].eq(metric_id)].empty
        else math.nan
    )
    rows: list[dict[str, float | int | str | None]] = []
    for n in (1, 3, 5):
        selected = data.head(n)
        top_sum = selected["raw_yoy_delta_oku_yen"].sum(min_count=1)
        rows.append(
            {
                "metric_id": metric_id,
                "top_n": n,
                "actual_n": len(selected),
                "component_names": ";".join(selected["industry_name"].astype(str)),
                "top_n_yoy_delta_oku_yen": top_sum,
                "gross_positive_yoy_delta_oku_yen": gross_positive,
                "share_of_gross_positive_pct": _contribution_rate(top_sum, gross_positive),
                "share_of_net_change_pct": _contribution_rate(top_sum, net_change),
            }
        )
    return pd.DataFrame(rows)
