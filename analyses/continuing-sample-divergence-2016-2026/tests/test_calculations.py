from __future__ import annotations

import math

import pandas as pd
import pytest

from corporate_quarterly.contributions import (
    _contribution_rate,
    build_capital_contributions,
    build_industry_contributions,
    positive_contribution_concentration,
)
from corporate_quarterly.processing import (
    _add_lagged_raw_columns,
    _merge_sa_columns,
    _period_end,
    _percent_change,
    _to_oku_yen,
    detect_profit_transition,
    oku_to_trillion,
)


def test_period_code_is_parsed_to_quarter_end() -> None:
    assert _period_end("20261") == "2026-03-31"
    assert _period_end("20262") == "2026-06-30"
    assert _period_end("20263") == "2026-09-30"
    assert _period_end("20264") == "2026-12-31"
    assert _period_end("bad") is None


def _processed_row(
    *,
    metric_id: str = "operating_profit",
    industry_name: str,
    industry_bucket: str,
    capital_size_name: str,
    capital_bucket: str,
    current: float,
    previous: float,
) -> dict[str, object]:
    return {
        "release_id": "fixture-release",
        "period_code": "20261",
        "period": "2026年1〜3月",
        "period_end": "2026-03-31",
        "coverage_scope": "EXCL_FINANCE_INSURANCE",
        "source_table_number": "1",
        "seasonal_adjustment": "RAW",
        "metric_id": metric_id,
        "metric_label_ja": "営業利益",
        "industry_code": industry_name,
        "industry_name": industry_name,
        "industry_bucket": industry_bucket,
        "capital_size_code": capital_size_name,
        "capital_size_name": capital_size_name,
        "capital_bucket": capital_bucket,
        "raw_value_oku_yen": current,
        "raw_lag4_value_oku_yen": previous,
        "raw_yoy_delta_oku_yen": current - previous,
        "raw_yoy_pct": (current / previous - 1.0) * 100.0,
        "estat_sid": "fixture",
        "source_path": "fixture.json",
        "source_sha256": "0" * 64,
    }


def test_million_yen_to_oku_and_oku_to_trillion_conversion() -> None:
    assert _to_oku_yen("sales", "百万円", 100.0) == pytest.approx(1.0)
    assert _to_oku_yen("sales", "億円", 12.5) == pytest.approx(12.5)
    assert oku_to_trillion(10_000.0) == pytest.approx(1.0)
    assert oku_to_trillion(25_000.0) == pytest.approx(2.5)
    assert oku_to_trillion(None) is None


def test_non_monetary_metric_is_not_silently_converted() -> None:
    assert _to_oku_yen("employee_count", "人", 100.0) is None


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (10.0, -1.0, "PROFIT_TO_LOSS"),
        (-10.0, 1.0, "LOSS_TO_PROFIT"),
        (10.0, 2.0, "NO_SIGN_CHANGE"),
        (0.0, -1.0, "ZERO_BOUNDARY"),
        (None, -1.0, "NOT_EVALUABLE"),
        (math.nan, -1.0, "NOT_EVALUABLE"),
    ],
)
def test_profit_loss_transition_detection(
    previous: float | None, current: float, expected: str
) -> None:
    assert detect_profit_transition(previous, current) == expected


def test_undefined_rates_are_missing_not_zero() -> None:
    assert _percent_change(None, 10.0) is None
    assert _percent_change(10.0, None) is None
    assert _percent_change(10.0, 0.0) is None
    assert _contribution_rate(5.0, 0.0) is None


def test_raw_yoy_raw_qoq_and_seasonally_adjusted_qoq_are_distinct(release) -> None:
    common = {
        "release_id": release.release_id,
        "coverage_scope": "EXCL_FINANCE_INSURANCE",
        "seasonal_adjustment": "RAW",
        "industry_code": "all",
        "industry_name": "全産業（除く金融・保険）",
        "industry_bucket": "ALL_NONFINANCIAL",
        "capital_size_code": "all",
        "capital_size_name": "全規模",
        "capital_bucket": "ALL_CAPITAL",
        "metric_id": "sales",
        "metric_label_ja": "売上高",
        "source_metric_name": "売上高(当期末)",
        "stock_flow": "FLOW",
        "source_unit": "百万円",
        "missing_status": "PRESENT",
        "source_table_number": "1",
        "estat_sid": "fixture",
        "source_cell_key": "fixture",
        "source_path": "fixture.json",
        "source_sha256": "0" * 64,
    }
    raw = pd.DataFrame(
        [
            {**common, "period_code": release.prior_yoy_period_code, "source_value": 100.0},
            {**common, "period_code": release.prior_qoq_period_code, "source_value": 110.0},
            {**common, "period_code": release.target_period_code, "source_value": 120.0},
        ]
    )
    processed = _add_lagged_raw_columns(raw, release)

    sa_common = {
        "coverage_scope": "EXCL_FINANCE_INSURANCE",
        "industry_bucket": "ALL_NONFINANCIAL",
        "capital_bucket": "ALL_CAPITAL",
        "metric_id": "sales",
        "source_unit": "百万円",
        "source_table_number": "4",
        "estat_sid": "sa-fixture",
        "source_sha256": "1" * 64,
    }
    sa = pd.DataFrame(
        [
            {**sa_common, "period_code": release.prior_qoq_period_code, "source_value": 125.0},
            {**sa_common, "period_code": release.target_period_code, "source_value": 150.0},
        ]
    )
    result = _merge_sa_columns(processed, sa, release).iloc[0]

    assert result["source_value"] == pytest.approx(120.0)
    assert result["raw_yoy_pct"] == pytest.approx(20.0)
    assert result["raw_qoq_pct"] == pytest.approx((120.0 / 110.0 - 1.0) * 100.0)
    assert result["sa_qoq_pct"] == pytest.approx(20.0)
    assert result["raw_qoq_pct"] != pytest.approx(result["sa_qoq_pct"])


def test_negative_prior_profit_rate_is_null_and_transition_is_persisted(release) -> None:
    common = {
        "release_id": release.release_id,
        "coverage_scope": "EXCL_FINANCE_INSURANCE",
        "seasonal_adjustment": "RAW",
        "industry_code": "i",
        "industry_name": "業種",
        "industry_bucket": "業種",
        "capital_size_code": "c",
        "capital_size_name": "全規模",
        "capital_bucket": "ALL_CAPITAL",
        "metric_id": "operating_profit",
        "metric_label_ja": "営業利益",
        "source_metric_name": "営業利益(当期末)",
        "stock_flow": "FLOW",
        "source_unit": "百万円",
        "missing_status": "PRESENT",
        "source_table_number": "1",
        "estat_sid": "fixture",
        "source_cell_key": "fixture",
        "source_path": "fixture.json",
        "source_sha256": "0" * 64,
    }
    raw = pd.DataFrame(
        [
            {**common, "period_code": release.prior_yoy_period_code, "source_value": -10.0},
            {**common, "period_code": release.prior_qoq_period_code, "source_value": -5.0},
            {**common, "period_code": release.target_period_code, "source_value": 20.0},
        ]
    )
    result = _add_lagged_raw_columns(raw, release).iloc[0]
    assert pd.isna(result["raw_yoy_pct"])
    assert result["raw_yoy_rate_status"] == "NEGATIVE_PROFIT_BASE_NOT_CALCULABLE"
    assert result["profit_transition_yoy"] == "LOSS_TO_PROFIT"


def test_industry_components_reconcile_to_total_and_contributions_sum() -> None:
    rows = [
        _processed_row(
            industry_name="全産業（除く金融・保険）",
            industry_bucket="ALL_NONFINANCIAL",
            capital_size_name="全規模",
            capital_bucket="ALL_CAPITAL",
            current=130.0,
            previous=100.0,
        ),
        _processed_row(
            industry_name="製造業",
            industry_bucket="MANUFACTURING",
            capital_size_name="全規模",
            capital_bucket="ALL_CAPITAL",
            current=80.0,
            previous=60.0,
        ),
        _processed_row(
            industry_name="建設業",
            industry_bucket="建設業",
            capital_size_name="全規模",
            capital_bucket="ALL_CAPITAL",
            current=50.0,
            previous=40.0,
        ),
    ]
    result = build_industry_contributions(pd.DataFrame(rows))

    assert result["raw_value_oku_yen"].sum() == pytest.approx(130.0)
    assert result["raw_lag4_value_oku_yen"].sum() == pytest.approx(100.0)
    assert result["raw_yoy_delta_oku_yen"].sum() == pytest.approx(30.0)
    assert result["contribution_pct_to_net_change"].sum() == pytest.approx(100.0)

    concentration = positive_contribution_concentration(result)
    assert concentration.loc[
        concentration["top_n"].eq(1), "share_of_gross_positive_pct"
    ].iloc[0] == pytest.approx(2.0 / 3.0 * 100.0)


def test_capital_components_reconcile_to_total_and_contributions_sum() -> None:
    rows = [
        _processed_row(
            industry_name="全産業（除く金融・保険）",
            industry_bucket="ALL_NONFINANCIAL",
            capital_size_name="全規模",
            capital_bucket="ALL_CAPITAL",
            current=160.0,
            previous=100.0,
        ),
        _processed_row(
            industry_name="全産業（除く金融・保険）",
            industry_bucket="ALL_NONFINANCIAL",
            capital_size_name="10億円以上",
            capital_bucket="10億円以上",
            current=90.0,
            previous=50.0,
        ),
        _processed_row(
            industry_name="全産業（除く金融・保険）",
            industry_bucket="ALL_NONFINANCIAL",
            capital_size_name="1億円以上 - 10億円未満",
            capital_bucket="1億円以上 - 10億円未満",
            current=45.0,
            previous=30.0,
        ),
        _processed_row(
            industry_name="全産業（除く金融・保険）",
            industry_bucket="ALL_NONFINANCIAL",
            capital_size_name="1千万円以上 - 1億円未満",
            capital_bucket="1千万円以上 - 1億円未満",
            current=25.0,
            previous=20.0,
        ),
    ]
    result = build_capital_contributions(pd.DataFrame(rows))

    assert result["raw_value_oku_yen"].sum() == pytest.approx(160.0)
    assert result["raw_lag4_value_oku_yen"].sum() == pytest.approx(100.0)
    assert result["raw_yoy_delta_oku_yen"].sum() == pytest.approx(60.0)
    assert result["contribution_pct_to_net_change"].sum() == pytest.approx(100.0)
