from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd
from bs4 import BeautifulSoup

from .constants import (
    METRIC_STOCK_FLOW,
    MONETARY_METRICS,
    Release,
)
from .estat import sha256_file
from .rates import parse_published_sa_rates


MISSING_MARKERS = {"", "-", "―", "…", "… ", "…※", "X", "x", "NA", "N/A", "＊"}


def _number_or_none(text: str) -> tuple[float | None, str]:
    normalized = (
        text.strip()
        .replace("　", "")
        .replace(",", "")
        .replace("−", "-")
        .replace("△", "-")
        .replace("▲", "-")
    )
    normalized = re.sub(r"[※*†]+$", "", normalized).strip()
    if normalized in MISSING_MARKERS:
        return None, "SOURCE_MISSING_MARKER"
    try:
        return float(normalized), "PRESENT"
    except ValueError:
        return None, f"UNPARSEABLE_SOURCE_VALUE:{text.strip()}"


def _period_end(period_code: str) -> str | None:
    if not re.fullmatch(r"\d{5}", str(period_code)):
        return None
    year, quarter = int(period_code[:4]), period_code[-1]
    ends = {"1": f"{year}-03-31", "2": f"{year}-06-30", "3": f"{year}-09-30", "4": f"{year}-12-31"}
    return ends.get(quarter)


def _industry_bucket(name: str) -> str:
    compact = name.replace(" ", "").replace("　", "")
    if compact.startswith("全産業"):
        return "ALL_NONFINANCIAL"
    if compact == "製造業":
        return "MANUFACTURING"
    if compact == "非製造業":
        return "NON_MANUFACTURING"
    return name


def _capital_bucket(name: str) -> str:
    return "ALL_CAPITAL" if name.replace(" ", "") == "全規模" else name


def parse_estat_response(
    *,
    result_path: Path,
    query_path: Path,
    table_spec: dict[str, Any],
    release: Release,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Convert e-Stat's immutable browser-table JSON response to tidy rows."""
    result = json.loads(result_path.read_text(encoding="utf-8"))
    query_meta = json.loads(query_path.read_text(encoding="utf-8"))
    table_html = result.get("table")
    if not table_html:
        raise ValueError(f"e-Stat response contains no table HTML: {result_path}")

    spec = query_meta["dimension_spec"]
    code_maps = {
        kind: {item["code"]: item for item in spec[kind]}
        for kind in ("industry", "capital", "time")
    }
    metrics_by_code = {
        item["code"]: {"metric_id": metric_id, **item}
        for metric_id, item in query_meta["canonical_metric_map"].items()
    }
    source_sha256 = sha256_file(result_path)
    # lxml is materially faster than Python's html.parser for the roughly
    # 20,000-cell Table 1 response.
    soup = BeautifulSoup(table_html, "lxml")
    column_codes = [
        node.get("data-unique", "").split("@")[-1]
        for node in soup.select("thead .js-dbview-cols")
    ]
    if not column_codes:
        raise ValueError(f"No metric columns found in source table: {result_path}")

    issues: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for html_row in soup.select("tbody tr"):
        row_headers = html_row.select("th.js-dbview-rows")
        values = html_row.select("td.stat-dbview-value")
        if not row_headers:
            continue
        # e-Stat orders the composite key innermost-to-outermost:
        # period@capital@industry for our industry/capital/time row layout.
        key_codes = row_headers[0].get("data-unique", "").split("@")
        if len(key_codes) != 3:
            issues.append(
                {
                    "kind": "TABLE_SHAPE",
                    "severity": "FAIL",
                    "detail": f"Expected 3 row dimensions; received {key_codes!r}",
                    "source_path": str(result_path),
                }
            )
            continue
        period_code, capital_code, industry_code = key_codes
        try:
            period = code_maps["time"][period_code]
            capital = code_maps["capital"][capital_code]
            industry = code_maps["industry"][industry_code]
        except KeyError as exc:
            issues.append(
                {
                    "kind": "UNKNOWN_DIMENSION_CODE",
                    "severity": "FAIL",
                    "detail": f"{exc} in row {key_codes!r}",
                    "source_path": str(result_path),
                }
            )
            continue
        if len(values) != len(column_codes):
            issues.append(
                {
                    "kind": "TABLE_SHAPE",
                    "severity": "FAIL",
                    "detail": f"{len(values)} values for {len(column_codes)} metric columns",
                    "source_path": str(result_path),
                    "row_key": "@".join(key_codes),
                }
            )
            continue
        for metric_code, value_node in zip(column_codes, values, strict=True):
            metric = metrics_by_code.get(metric_code)
            if metric is None:
                issues.append(
                    {
                        "kind": "UNKNOWN_METRIC_CODE",
                        "severity": "FAIL",
                        "detail": metric_code,
                        "source_path": str(result_path),
                    }
                )
                continue
            value, missing_status = _number_or_none(value_node.get_text(" ", strip=True))
            if missing_status != "PRESENT":
                issues.append(
                    {
                        "kind": "MISSING_OR_UNPARSEABLE_VALUE",
                        "severity": "WARN",
                        "detail": missing_status,
                        "source_path": str(result_path),
                        "source_cell_key": "@".join([period_code, capital_code, industry_code, metric_code]),
                    }
                )
            rows.append(
                {
                    "release_id": release.release_id,
                    "period_code": period_code,
                    "period": period["name"],
                    "period_end": _period_end(period_code),
                    "coverage_scope": table_spec["coverage_scope"],
                    "seasonal_adjustment": table_spec["seasonal_adjustment"],
                    "industry_code": industry_code,
                    "industry_name": industry["name"],
                    "industry_bucket": _industry_bucket(industry["name"]),
                    "capital_size_code": capital_code,
                    "capital_size_name": capital["name"],
                    "capital_bucket": _capital_bucket(capital["name"]),
                    "metric_id": metric["metric_id"],
                    "metric_label_ja": metric["metric_label_ja"],
                    "source_metric_name": metric["source_name"],
                    "stock_flow": METRIC_STOCK_FLOW.get(metric["metric_id"], "UNKNOWN"),
                    "source_unit": metric.get("source_unit") or "百万円",
                    "source_value": value,
                    "missing_status": missing_status,
                    "source_table_number": table_spec["table_number"],
                    "estat_sid": table_spec["sid"],
                    "source_cell_key": "@".join(
                        [period_code, capital_code, industry_code, metric_code]
                    ),
                    "source_path": str(result_path),
                    "source_sha256": source_sha256,
                }
            )

    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError(f"No source observations parsed from {result_path}")
    historical = frame["industry_name"].str.contains(r"H20年度まで", regex=True, na=False)
    for name in sorted(frame.loc[historical, "industry_name"].unique()):
        issues.append(
            {
                "kind": "INDUSTRY_CLASSIFICATION_CHANGE",
                "severity": "WARN",
                "detail": f"Historical classification row retained but excluded from rankings: {name}",
                "source_path": str(result_path),
            }
        )
    return frame, issues


def _to_oku_yen(metric_id: str, source_unit: str, value: float | None) -> float | None:
    if value is None or metric_id not in MONETARY_METRICS:
        return None
    if source_unit == "百万円":
        return value / 100.0
    if source_unit == "億円":
        return value
    raise ValueError(f"Unknown monetary source unit {source_unit!r} for {metric_id}")


def _percent_change(value: float | None, previous: float | None) -> float | None:
    if value is None or previous is None or previous == 0:
        return None
    return (value / previous - 1.0) * 100.0


PROFIT_METRICS = {"operating_profit", "ordinary_profit"}


def _rate_status(
    metric_id: str, value: float | None, previous: float | None
) -> str:
    if value is None or previous is None or pd.isna(value) or pd.isna(previous):
        return "MISSING_INPUT"
    if previous == 0:
        return "ZERO_BASE_NOT_CALCULABLE"
    if metric_id in PROFIT_METRICS and previous < 0:
        return "NEGATIVE_PROFIT_BASE_NOT_CALCULABLE"
    return "CALCULABLE"


def _metric_percent_change(
    metric_id: str, value: float | None, previous: float | None
) -> float | None:
    if _rate_status(metric_id, value, previous) != "CALCULABLE":
        return None
    return _percent_change(value, previous)


def _delta(value: float | None, previous: float | None) -> float | None:
    return None if value is None or previous is None else value - previous


def _add_lagged_raw_columns(raw: pd.DataFrame, release: Release) -> pd.DataFrame:
    keys = [
        "coverage_scope",
        "industry_code",
        "capital_size_code",
        "metric_id",
        "source_table_number",
    ]
    raw = raw.copy()
    raw["raw_value_oku_yen"] = [
        _to_oku_yen(metric, unit, value)
        for metric, unit, value in zip(
            raw["metric_id"], raw["source_unit"], raw["source_value"], strict=True
        )
    ]
    current = raw.loc[raw["period_code"] == release.target_period_code].copy()
    yoy = raw.loc[raw["period_code"] == release.prior_yoy_period_code, keys + ["source_value", "raw_value_oku_yen"]].rename(
        columns={
            "source_value": "raw_lag4_value",
            "raw_value_oku_yen": "raw_lag4_value_oku_yen",
        }
    )
    qoq = raw.loc[raw["period_code"] == release.prior_qoq_period_code, keys + ["source_value", "raw_value_oku_yen"]].rename(
        columns={
            "source_value": "raw_lag1_value",
            "raw_value_oku_yen": "raw_lag1_value_oku_yen",
        }
    )
    current = current.merge(yoy, on=keys, how="left", validate="one_to_one")
    current = current.merge(qoq, on=keys, how="left", validate="one_to_one")
    current["raw_yoy_delta"] = [
        _delta(value, previous)
        for value, previous in zip(
            current["source_value"], current["raw_lag4_value"], strict=True
        )
    ]
    current["raw_yoy_delta_oku_yen"] = [
        _delta(value, previous)
        for value, previous in zip(
            current["raw_value_oku_yen"], current["raw_lag4_value_oku_yen"], strict=True
        )
    ]
    current["raw_yoy_pct"] = [
        _metric_percent_change(metric, value, previous)
        for metric, value, previous in zip(
            current["metric_id"],
            current["source_value"],
            current["raw_lag4_value"],
            strict=True,
        )
    ]
    current["raw_yoy_rate_status"] = [
        _rate_status(metric, value, previous)
        for metric, value, previous in zip(
            current["metric_id"],
            current["source_value"],
            current["raw_lag4_value"],
            strict=True,
        )
    ]
    current["raw_qoq_delta"] = [
        _delta(value, previous)
        for value, previous in zip(
            current["source_value"], current["raw_lag1_value"], strict=True
        )
    ]
    current["raw_qoq_delta_oku_yen"] = [
        _delta(value, previous)
        for value, previous in zip(
            current["raw_value_oku_yen"], current["raw_lag1_value_oku_yen"], strict=True
        )
    ]
    current["raw_qoq_pct"] = [
        _metric_percent_change(metric, value, previous)
        for metric, value, previous in zip(
            current["metric_id"],
            current["source_value"],
            current["raw_lag1_value"],
            strict=True,
        )
    ]
    current["raw_qoq_rate_status"] = [
        _rate_status(metric, value, previous)
        for metric, value, previous in zip(
            current["metric_id"],
            current["source_value"],
            current["raw_lag1_value"],
            strict=True,
        )
    ]
    current["profit_transition_yoy"] = [
        detect_profit_transition(previous, value)
        if metric in PROFIT_METRICS
        else "NOT_APPLICABLE"
        for metric, value, previous in zip(
            current["metric_id"],
            current["source_value"],
            current["raw_lag4_value"],
            strict=True,
        )
    ]
    current["profit_transition_qoq"] = [
        detect_profit_transition(previous, value)
        if metric in PROFIT_METRICS
        else "NOT_APPLICABLE"
        for metric, value, previous in zip(
            current["metric_id"],
            current["source_value"],
            current["raw_lag1_value"],
            strict=True,
        )
    ]
    current["comparability_status"] = (
        "NOT_COMPARABLE_SAMPLE_REPLACEMENT"
        if release.target_period_code.endswith("2")
        else "RAW_QOQ_NOT_HEADLINE_SERIES"
    )
    return current


def _merge_sa_columns(processed: pd.DataFrame, sa: pd.DataFrame, release: Release) -> pd.DataFrame:
    keys = ["coverage_scope", "industry_bucket", "capital_bucket", "metric_id"]
    sa = sa.copy()
    sa["sa_value_oku_yen"] = [
        _to_oku_yen(metric, unit, value)
        for metric, unit, value in zip(sa["metric_id"], sa["source_unit"], sa["source_value"], strict=True)
    ]
    current = sa.loc[sa["period_code"] == release.target_period_code].copy()
    previous = sa.loc[
        sa["period_code"] == release.prior_qoq_period_code, keys + ["source_value", "sa_value_oku_yen"]
    ].rename(
        columns={
            "source_value": "sa_lag1_value",
            "sa_value_oku_yen": "sa_lag1_value_oku_yen",
        }
    )
    current = current.merge(previous, on=keys, how="left", validate="one_to_one")
    current["sa_qoq_delta_oku_yen"] = [
        _delta(value, previous)
        for value, previous in zip(
            current["sa_value_oku_yen"], current["sa_lag1_value_oku_yen"], strict=True
        )
    ]
    current["sa_qoq_pct"] = [
        _percent_change(value, previous)
        for value, previous in zip(
            current["source_value"], current["sa_lag1_value"], strict=True
        )
    ]
    sa_cols = keys + [
        "sa_value_oku_yen",
        "sa_lag1_value_oku_yen",
        "sa_qoq_delta_oku_yen",
        "sa_qoq_pct",
        "source_table_number",
        "estat_sid",
        "source_sha256",
    ]
    current = current[sa_cols].rename(
        columns={
            "source_table_number": "sa_source_table_number",
            "estat_sid": "sa_estat_sid",
            "source_sha256": "sa_source_sha256",
        }
    )
    return processed.merge(current, on=keys, how="left", validate="many_to_one")


def _base_key_columns(frame: pd.DataFrame) -> list[str]:
    return [
        "release_id",
        "period_code",
        "period",
        "period_end",
        "coverage_scope",
        "industry_code",
        "industry_name",
        "industry_bucket",
        "capital_size_code",
        "capital_size_name",
        "capital_bucket",
        "source_table_number",
        "estat_sid",
        "source_path",
        "source_sha256",
        "comparability_status",
    ]


def _make_derived_row(
    reference: pd.Series,
    *,
    metric_id: str,
    metric_label_ja: str,
    source_unit: str,
    stock_flow: str,
    current_value: float | None,
    lag4_value: float | None,
    lag1_value: float | None,
    is_monetary: bool = True,
) -> dict[str, Any]:
    row = {key: reference[key] for key in _base_key_columns(reference.to_frame().T)}
    row.update(
        {
            "seasonal_adjustment": "DERIVED_FROM_RAW",
            "metric_id": metric_id,
            "metric_label_ja": metric_label_ja,
            "source_metric_name": "derived",
            "stock_flow": stock_flow,
            "source_unit": source_unit,
            "source_value": current_value,
            "raw_lag4_value": lag4_value,
            "raw_lag1_value": lag1_value,
            "raw_yoy_delta": _delta(current_value, lag4_value),
            "raw_yoy_pct": _metric_percent_change(metric_id, current_value, lag4_value),
            "raw_yoy_rate_status": _rate_status(metric_id, current_value, lag4_value),
            "raw_qoq_delta": _delta(current_value, lag1_value),
            "raw_qoq_pct": _metric_percent_change(metric_id, current_value, lag1_value),
            "raw_qoq_rate_status": _rate_status(metric_id, current_value, lag1_value),
            "profit_transition_yoy": (
                detect_profit_transition(lag4_value, current_value)
                if metric_id in PROFIT_METRICS
                else "NOT_APPLICABLE"
            ),
            "profit_transition_qoq": (
                detect_profit_transition(lag1_value, current_value)
                if metric_id in PROFIT_METRICS
                else "NOT_APPLICABLE"
            ),
            "raw_value_oku_yen": current_value if is_monetary else None,
            "raw_lag4_value_oku_yen": lag4_value if is_monetary else None,
            "raw_lag1_value_oku_yen": lag1_value if is_monetary else None,
            "raw_yoy_delta_oku_yen": (
                _delta(current_value, lag4_value) if is_monetary else None
            ),
            "raw_qoq_delta_oku_yen": (
                _delta(current_value, lag1_value) if is_monetary else None
            ),
            "sa_value_oku_yen": None,
            "sa_lag1_value_oku_yen": None,
            "sa_qoq_delta_oku_yen": None,
            "sa_qoq_pct": None,
            "sa_source_table_number": None,
            "sa_estat_sid": None,
            "sa_source_sha256": None,
            "missing_status": (
                "PRESENT"
                if current_value is not None
                else "DERIVATION_INPUT_MISSING"
            ),
            "source_cell_key": "DERIVED",
        }
    )
    return row


def add_derived_metrics(processed: pd.DataFrame) -> pd.DataFrame:
    """Add the explicitly requested, non-source metrics without imputing values."""
    base = processed.loc[
        processed["seasonal_adjustment"].eq("RAW")
        & processed["source_table_number"].eq("1")
    ].copy()
    index = _base_key_columns(base)
    value_columns = [
        "raw_value_oku_yen",
        "raw_lag4_value_oku_yen",
        "raw_lag1_value_oku_yen",
        "source_value",
        "raw_lag4_value",
        "raw_lag1_value",
    ]
    # pivot_table(dropna=False) can materialize an enormous Cartesian product
    # when a source table has nested row labels. unstack preserves observed
    # source combinations and retains null inputs.
    wide = (
        base.set_index(index + ["metric_id"])[value_columns]
        .groupby(level=index + ["metric_id"], dropna=False)
        .first()
        .unstack("metric_id")
    )
    if wide.empty:
        return processed
    wide.columns = [f"{left}__{right}" for left, right in wide.columns]
    wide = wide.reset_index()
    derived: list[dict[str, Any]] = []
    for _, values in wide.iterrows():
        reference = values
        def monetary(metric: str, lag: str = "raw_value_oku_yen") -> float | None:
            value = values.get(f"{lag}__{metric}")
            return None if pd.isna(value) else float(value)

        def native(metric: str, lag: str = "source_value") -> float | None:
            value = values.get(f"{lag}__{metric}")
            return None if pd.isna(value) else float(value)

        software_values: list[float | None] = []
        for lag in (
            "raw_value_oku_yen",
            "raw_lag4_value_oku_yen",
            "raw_lag1_value_oku_yen",
        ):
            including = monetary("capex_including_software", lag)
            excluding = monetary("capex_excluding_software", lag)
            software_values.append(
                including - excluding
                if including is not None and excluding is not None
                else None
            )
        derived.append(
            _make_derived_row(
                reference,
                metric_id="software_capex_derived",
                metric_label_ja="ソフトウェア投資（設備投資差額による逆算）",
                source_unit="億円",
                stock_flow="FLOW",
                current_value=software_values[0],
                lag4_value=software_values[1],
                lag1_value=software_values[2],
            )
        )

        borrowing_metrics = (
            "financial_institution_borrowings_current",
            "other_borrowings_current",
            "financial_institution_borrowings_long_term",
            "other_borrowings_long_term",
        )
        borrowing_values: list[float | None] = []
        for lag in (
            "raw_value_oku_yen",
            "raw_lag4_value_oku_yen",
            "raw_lag1_value_oku_yen",
        ):
            parts = [monetary(metric, lag) for metric in borrowing_metrics]
            borrowing_values.append(sum(parts) if all(part is not None for part in parts) else None)
        derived.append(
            _make_derived_row(
                reference,
                metric_id="total_borrowings_derived",
                metric_label_ja="借入金（短期・長期、金融機関・その他の合計）",
                source_unit="億円",
                stock_flow="STOCK",
                current_value=borrowing_values[0],
                lag4_value=borrowing_values[1],
                lag1_value=borrowing_values[2],
            )
        )

        operating_values = [
            monetary("operating_profit", lag)
            for lag in (
                "raw_value_oku_yen",
                "raw_lag4_value_oku_yen",
                "raw_lag1_value_oku_yen",
            )
        ]
        ordinary_values = [
            monetary("ordinary_profit", lag)
            for lag in (
                "raw_value_oku_yen",
                "raw_lag4_value_oku_yen",
                "raw_lag1_value_oku_yen",
            )
        ]
        profit_gap_values = [
            ordinary - operating if ordinary is not None and operating is not None else None
            for ordinary, operating in zip(ordinary_values, operating_values, strict=True)
        ]
        derived.append(
            _make_derived_row(
                reference,
                metric_id="ordinary_minus_operating",
                metric_label_ja="経常利益−営業利益",
                source_unit="億円",
                stock_flow="FLOW",
                current_value=profit_gap_values[0],
                lag4_value=profit_gap_values[1],
                lag1_value=profit_gap_values[2],
            )
        )

        wage_values = [
            native("employee_wages", lag)
            for lag in ("source_value", "raw_lag4_value", "raw_lag1_value")
        ]
        bonus_values = [
            native("employee_bonuses", lag)
            for lag in ("source_value", "raw_lag4_value", "raw_lag1_value")
        ]
        people_values = [
            native("employee_count", lag)
            for lag in ("source_value", "raw_lag4_value", "raw_lag1_value")
        ]
        pay_per_person = [
            ((wage + bonus) * 100.0 / people)
            if wage is not None and bonus is not None and people not in (None, 0)
            else None
            for wage, bonus, people in zip(wage_values, bonus_values, people_values, strict=True)
        ]
        total_pay_values: list[float | None] = []
        for lag in (
            "raw_value_oku_yen",
            "raw_lag4_value_oku_yen",
            "raw_lag1_value_oku_yen",
        ):
            wages = monetary("employee_wages", lag)
            bonuses = monetary("employee_bonuses", lag)
            total_pay_values.append(
                wages + bonuses
                if wages is not None and bonuses is not None
                else None
            )
        derived.append(
            _make_derived_row(
                reference,
                metric_id="employee_total_pay_derived",
                metric_label_ja="従業員給与・賞与合計",
                source_unit="億円",
                stock_flow="FLOW",
                current_value=total_pay_values[0],
                lag4_value=total_pay_values[1],
                lag1_value=total_pay_values[2],
            )
        )
        derived.append(
            _make_derived_row(
                reference,
                metric_id="employee_pay_per_person_approx",
                metric_label_ja="従業員1人当たり給与総額（四半期・概算）",
                source_unit="万円/人",
                stock_flow="FLOW_PER_PERIOD_END_PERSON",
                current_value=pay_per_person[0],
                lag4_value=pay_per_person[1],
                lag1_value=pay_per_person[2],
                is_monetary=False,
            )
        )
    derived_frame = pd.DataFrame(derived).dropna(axis=1, how="all")
    return pd.concat([processed, derived_frame], ignore_index=True, sort=False)


def build_processed(
    project_root: Path, release: Release
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    raw_root = project_root / "data" / "raw" / release.release_id
    config = release.e_stat_tables
    parsed: list[pd.DataFrame] = []
    issues: list[dict[str, Any]] = []
    for source_key, table_spec in config.items():
        result_path = raw_root / f"{source_key}_values.json"
        query_path = raw_root / f"{source_key}_query.json"
        frame, table_issues = parse_estat_response(
            result_path=result_path,
            query_path=query_path,
            table_spec=table_spec,
            release=release,
        )
        parsed.append(frame)
        issues.extend(table_issues)
    source = pd.concat(parsed, ignore_index=True, sort=False)
    raw = source.loc[source["seasonal_adjustment"].eq("RAW")].copy()
    sa = source.loc[source["seasonal_adjustment"].eq("SA")].copy()
    processed = _add_lagged_raw_columns(raw, release)
    processed = _merge_sa_columns(processed, sa, release)
    processed["official_yoy_pct"] = pd.NA
    published_sa_rates = parse_published_sa_rates(raw_root / "mof_percent.xlsx", release)
    processed = processed.merge(
        published_sa_rates,
        on=["coverage_scope", "industry_bucket", "capital_bucket", "metric_id"],
        how="left",
        validate="many_to_one",
    )
    processed = add_derived_metrics(processed)
    for metric_id, published_rate in release.pdf_reference_checks.get(
        "yoy_pct", {}
    ).items():
        mask = (
            processed["coverage_scope"].eq("EXCL_FINANCE_INSURANCE")
            & processed["source_table_number"].astype(str).eq("1")
            & processed["industry_bucket"].eq("ALL_NONFINANCIAL")
            & processed["capital_bucket"].eq("ALL_CAPITAL")
            & processed["metric_id"].eq(metric_id)
        )
        processed.loc[mask, "official_yoy_pct"] = float(published_rate)
    processed["official_yoy_pct"] = pd.to_numeric(
        processed["official_yoy_pct"], errors="coerce"
    )
    processed = processed.sort_values(
        [
            "coverage_scope",
            "source_table_number",
            "industry_name",
            "capital_size_name",
            "metric_id",
        ],
        kind="stable",
    ).reset_index(drop=True)
    # Keep generated artifacts relocatable: lineage paths are project-relative,
    # while hashes remain the immutable identity of every raw source.
    for column in ("source_path", "published_rate_source_path"):
        if column in processed:
            processed[column] = processed[column].map(
                lambda value: (
                    str(Path(value).resolve().relative_to(project_root.resolve()))
                    if pd.notna(value)
                    else value
                )
            )
    return processed, issues


def oku_to_trillion(oku_yen: float | None) -> float | None:
    return None if oku_yen is None or (isinstance(oku_yen, float) and math.isnan(oku_yen)) else oku_yen / 10_000.0


def detect_profit_transition(previous: float | None, current: float | None) -> str:
    if previous is None or current is None or pd.isna(previous) or pd.isna(current):
        return "NOT_EVALUABLE"
    if previous > 0 and current < 0:
        return "PROFIT_TO_LOSS"
    if previous < 0 and current > 0:
        return "LOSS_TO_PROFIT"
    if previous == 0 or current == 0:
        return "ZERO_BOUNDARY"
    return "NO_SIGN_CHANGE"
