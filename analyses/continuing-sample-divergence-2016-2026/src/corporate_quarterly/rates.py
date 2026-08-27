from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .constants import Release


def _metric_from_header(text: str) -> str | None:
    compact = text.replace(chr(10), "").replace(" ", "").replace("　", "")
    if "設備投資" in compact and "ソフトウェアを除く" in compact:
        return "capex_excluding_software"
    if "設備投資" in compact and "ソフトウェアを含む" in compact:
        return "capex_including_software"
    if "営業利益" in compact:
        return "operating_profit"
    if "経常利益" in compact:
        return "ordinary_profit"
    if "売上高" in compact:
        return "sales"
    return None


def _industry_from_header(text: str) -> str | None:
    compact = text.replace(chr(10), "").replace(" ", "").replace("　", "")
    if "全産業" in compact:
        return "ALL_NONFINANCIAL"
    if "製造業" in compact and "非製造" not in compact:
        return "MANUFACTURING"
    if "非製造" in compact:
        return "NON_MANUFACTURING"
    return None


def parse_published_sa_rates(path: Path, release: Release) -> pd.DataFrame:
    """Read MOF's versioned-at-download seasonal-adjustment rate workbook."""
    workbook = pd.read_excel(path, sheet_name=0, header=None)
    header_row = next(
        (
            index
            for index, row in workbook.iterrows()
            if any("売上高" in str(value) for value in row.values)
            and any("営業利益" in str(value) for value in row.values)
        ),
        None,
    )
    if header_row is None:
        raise ValueError(f"Could not find seasonal-rate metric header in {path}")
    industry_row = header_row + 1
    target_year = release.target_period_code[:4]
    quarter_names = {"1": "1～3月", "2": "4～6月", "3": "7～9月", "4": "10～12月"}
    target_period_text = f"{target_year} {quarter_names[release.target_period_code[-1]]}"
    target_rows = workbook[
        workbook.iloc[:, 1].astype(str).str.contains(
            re.escape(target_period_text), regex=True, na=False
        )
    ]
    if len(target_rows) != 1:
        raise ValueError(
            f"Could not uniquely find {target_period_text} in published rate workbook: {len(target_rows)} rows"
        )
    target = target_rows.iloc[0]
    metrics: list[str | None] = []
    current_metric: str | None = None
    for value in workbook.iloc[header_row].tolist():
        metric = _metric_from_header(str(value))
        if metric is not None:
            current_metric = metric
        metrics.append(current_metric)
    rows: list[dict[str, object]] = []
    for col, metric_id in enumerate(metrics):
        if metric_id is None:
            continue
        industry_bucket = _industry_from_header(str(workbook.iloc[industry_row, col]))
        if industry_bucket is None:
            continue
        value = target.iloc[col]
        if pd.isna(value) or str(value).strip() in {"-", "…"}:
            rate = None
        else:
            rate = float(value)
        rows.append(
            {
                "coverage_scope": "EXCL_FINANCE_INSURANCE",
                "industry_bucket": industry_bucket,
                "capital_bucket": "ALL_CAPITAL",
                "metric_id": metric_id,
                "official_sa_qoq_pct": rate,
                "published_rate_source_path": str(path),
            }
        )
    result = pd.DataFrame(rows).drop_duplicates(
        ["coverage_scope", "industry_bucket", "capital_bucket", "metric_id"],
        keep="last",
    )
    if result.empty:
        raise ValueError(f"No published seasonal rates parsed from {path}")
    return result
