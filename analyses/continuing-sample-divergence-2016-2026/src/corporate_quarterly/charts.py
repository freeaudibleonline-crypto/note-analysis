from __future__ import annotations

from pathlib import Path
from typing import Iterable

import matplotlib

# The pipeline is also run in headless CI.  Select the backend before importing
# pyplot so chart generation never depends on an interactive display.
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter


CHART_FILENAMES = (
    "operating_profit_industry_contribution.png",
    "operating_profit_capital_contribution.png",
    "profit_margin_and_gap.png",
    "capex_software_bridge.png",
    "allocation_growth.png",
)

_POSITIVE = "#087E8B"
_NEGATIVE = "#D1495B"
_NEUTRAL = "#536878"
_ACCENT = "#F2A541"
_GRID = "#D9DEE3"


def _set_style() -> None:
    """Set all relevant plotting defaults explicitly for reproducible output."""
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": [
                "Hiragino Sans",
                ".Hiragino Kaku Gothic Interface",
                "Yu Gothic",
                "Noto Sans CJK JP",
                "IPAexGothic",
                "DejaVu Sans",
            ],
            "axes.unicode_minus": False,
            "axes.edgecolor": "#66717A",
            "axes.labelcolor": "#263238",
            "axes.titleweight": "bold",
            "axes.titlesize": 14,
            "axes.labelsize": 10,
            "xtick.color": "#263238",
            "ytick.color": "#263238",
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )


def _save(fig: Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        path,
        dpi=180,
        bbox_inches="tight",
        metadata={"Software": "corporate-quarterly 0.1.0"},
    )
    plt.close(fig)
    return path


def _finite_number(value: object, *, label: str) -> float:
    if value is None or pd.isna(value) or not np.isfinite(float(value)):
        raise ValueError(f"Chart input is missing/non-finite; no zero fill: {label}")
    return float(value)


def _headline(processed: pd.DataFrame, metric_id: str) -> pd.Series:
    subset = processed.loc[
        processed["coverage_scope"].eq("EXCL_FINANCE_INSURANCE")
        & processed["source_table_number"].astype(str).eq("1")
        & processed["industry_bucket"].eq("ALL_NONFINANCIAL")
        & processed["capital_bucket"].eq("ALL_CAPITAL")
        & processed["metric_id"].eq(metric_id)
    ]
    if len(subset) != 1:
        raise ValueError(
            f"Expected one non-financial all-industry/all-capital row for {metric_id}; "
            f"found {len(subset)}"
        )
    return subset.iloc[0]


def _annotate_horizontal_bars(ax: Axes, bars: Iterable, values: Iterable[float]) -> None:
    values = list(values)
    span = max(max((abs(value) for value in values), default=0.0), 0.1)
    offset = span * 0.018
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            value + (offset if value >= 0 else -offset),
            bar.get_y() + bar.get_height() / 2,
            f"{value:+.2f}兆円",
            va="center",
            ha="left" if value >= 0 else "right",
            fontsize=8.5,
            color="#263238",
        )


def _pad_horizontal_axis(ax: Axes, values: Iterable[float]) -> None:
    values = list(values)
    low = min([0.0, *values])
    high = max([0.0, *values])
    span = max(high - low, max((abs(value) for value in values), default=0.0), 0.1)
    # A wider negative-side pad keeps annotations separate from long Japanese
    # category labels; the positive pad prevents the leading plus value clipping.
    ax.set_xlim(low - span * 0.16, high + span * 0.13)


def _industry_chart(contributions: pd.DataFrame, path: Path) -> Path:
    data = contributions.loc[
        contributions["metric_id"].eq("operating_profit")
    ].copy()
    if data.empty:
        raise ValueError("No operating-profit industry contribution rows")
    if data["raw_yoy_delta_oku_yen"].isna().any():
        raise ValueError("Industry contribution chart contains missing deltas; no zero fill")
    data["delta_trillion_yen"] = data["raw_yoy_delta_oku_yen"].astype(float) / 10_000.0
    data = data.sort_values("delta_trillion_yen", kind="stable")

    fig, ax = plt.subplots(figsize=(10.8, 6.8))
    values = data["delta_trillion_yen"].tolist()
    colors = [_POSITIVE if value >= 0 else _NEGATIVE for value in values]
    bars = ax.barh(data["industry_name"], values, color=colors, height=0.68)
    ax.axvline(0, color="#263238", linewidth=0.9)
    ax.xaxis.grid(True, color=_GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.set_xlabel("営業利益の前年同期差（兆円）")
    ax.set_title("営業利益の増減はどの業種が作ったか")
    _pad_horizontal_axis(ax, values)
    _annotate_horizontal_bars(ax, bars, values)
    fig.text(
        0.01,
        0.01,
        "注：互いに重複しない公表主要業種の原数値。金融業・保険業を除く。出所：e-Stat。",
        fontsize=8,
        color="#52616B",
    )
    fig.tight_layout(rect=(0, 0.045, 1, 1))
    return _save(fig, path)


def _capital_chart(contributions: pd.DataFrame, path: Path) -> Path:
    data = contributions.loc[
        contributions["metric_id"].eq("operating_profit")
    ].copy()
    if data.empty:
        raise ValueError("No operating-profit capital-size contribution rows")
    if data["raw_yoy_delta_oku_yen"].isna().any():
        raise ValueError("Capital-size contribution chart contains missing deltas; no zero fill")
    data["delta_trillion_yen"] = data["raw_yoy_delta_oku_yen"].astype(float) / 10_000.0
    data = data.sort_values("delta_trillion_yen", kind="stable")

    fig, ax = plt.subplots(figsize=(9.4, 4.8))
    values = data["delta_trillion_yen"].tolist()
    colors = [_POSITIVE if value >= 0 else _NEGATIVE for value in values]
    bars = ax.barh(data["capital_size_name"], values, color=colors, height=0.56)
    ax.axvline(0, color="#263238", linewidth=0.9)
    ax.xaxis.grid(True, color=_GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.set_xlabel("営業利益の前年同期差（兆円）")
    ax.set_title("営業利益の増減を資本金規模別に分解")
    _pad_horizontal_axis(ax, values)
    _annotate_horizontal_bars(ax, bars, values)
    fig.text(
        0.01,
        0.01,
        "注：全規模と一致する互いに重複しない三区分。原数値、金融業・保険業を除く。出所：e-Stat。",
        fontsize=8,
        color="#52616B",
    )
    fig.tight_layout(rect=(0, 0.055, 1, 1))
    return _save(fig, path)


def _profit_margin_chart(processed: pd.DataFrame, path: Path) -> Path:
    sales = _finite_number(_headline(processed, "sales")["raw_value_oku_yen"], label="sales")
    operating = _finite_number(
        _headline(processed, "operating_profit")["raw_value_oku_yen"],
        label="operating_profit",
    )
    ordinary = _finite_number(
        _headline(processed, "ordinary_profit")["raw_value_oku_yen"],
        label="ordinary_profit",
    )
    gap = _finite_number(
        _headline(processed, "ordinary_minus_operating")["raw_value_oku_yen"],
        label="ordinary_minus_operating",
    )
    if sales == 0:
        raise ValueError("Sales are zero; profit margins cannot be calculated")

    margins = [operating / sales * 100.0, ordinary / sales * 100.0]
    profit_levels = [operating / 10_000.0, ordinary / 10_000.0]
    fig, (left, right) = plt.subplots(1, 2, figsize=(10.5, 5.1))

    margin_bars = left.bar(
        ["営業利益率", "経常利益率"], margins, color=[_POSITIVE, _ACCENT], width=0.58
    )
    left.set_ylabel("売上高比（％）")
    left.set_title("売上高に対する利益率")
    left.yaxis.grid(True, color=_GRID, linewidth=0.7)
    left.set_axisbelow(True)
    for bar, value in zip(margin_bars, margins, strict=True):
        left.text(bar.get_x() + bar.get_width() / 2, value, f"{value:.1f}%", ha="center", va="bottom")

    level_bars = right.bar(
        ["営業利益", "経常利益"], profit_levels, color=[_POSITIVE, _ACCENT], width=0.58
    )
    right.set_ylabel("利益額（兆円）")
    right.set_title("利益水準と両者の差")
    right.yaxis.grid(True, color=_GRID, linewidth=0.7)
    right.set_axisbelow(True)
    for bar, value in zip(level_bars, profit_levels, strict=True):
        right.text(
            bar.get_x() + bar.get_width() / 2,
            value,
            f"{value:.1f}兆円",
            ha="center",
            va="bottom",
        )
    right.annotate(
        f"差 {gap / 10_000.0:.1f}兆円",
        xy=(1, profit_levels[1]),
        xytext=(0.15, sum(profit_levels) / 2),
        arrowprops={"arrowstyle": "->", "color": _NEUTRAL},
        color=_NEUTRAL,
        fontsize=10,
    )

    fig.suptitle("営業利益と経常利益は同じ指標ではない", fontsize=15, fontweight="bold")
    fig.text(
        0.01,
        0.01,
        "注：利益率は各利益を売上高で除した計算値。原数値、金融業・保険業を除く。出所：e-Stat。",
        fontsize=8,
        color="#52616B",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.93))
    return _save(fig, path)


def _capex_chart(processed: pd.DataFrame, path: Path) -> Path:
    metric_ids = (
        "capex_including_software",
        "capex_excluding_software",
        "software_capex_derived",
    )
    rows = {metric: _headline(processed, metric) for metric in metric_ids}
    values = [
        _finite_number(rows[metric]["raw_value_oku_yen"], label=metric) / 10_000.0
        for metric in metric_ids
    ]
    yoy = [
        _finite_number(rows[metric]["raw_yoy_pct"], label=f"{metric}.raw_yoy_pct")
        for metric in metric_ids
    ]

    labels = ["ソフト込み", "ソフト除く", "差額（逆算）"]
    fig, ax = plt.subplots(figsize=(9.6, 5.4))
    bars = ax.bar(labels, values, color=[_NEUTRAL, _POSITIVE, _ACCENT], width=0.58)
    ax.set_ylabel("設備投資額（兆円）")
    ax.set_title("設備投資の「ソフト込み」と「除く」の差")
    ax.yaxis.grid(True, color=_GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.set_ylim(0, max(values) * 1.16)
    for bar, value, rate in zip(bars, values, yoy, strict=True):
        rate_decimals = 2 if 0 < abs(rate) < 0.1 else 1
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value,
            f"{value:.1f}兆円\n前年比 {rate:+.{rate_decimals}f}%",
            ha="center",
            va="bottom",
            fontsize=9.5,
        )
    fig.text(
        0.01,
        0.01,
        "注：差額は「ソフトウェア込み−除く」の逆算値で、直接公表値ではない。金融業・保険業を除く。出所：e-Stat。",
        fontsize=8,
        color="#52616B",
    )
    fig.tight_layout(rect=(0, 0.055, 1, 1))
    return _save(fig, path)


def _allocation_chart(processed: pd.DataFrame, path: Path) -> Path:
    operating = _headline(processed, "operating_profit")
    total_pay = _headline(processed, "employee_total_pay_derived")
    people = _headline(processed, "employee_count")
    capex = _headline(processed, "capex_including_software")

    op_rate = _finite_number(operating["raw_yoy_pct"], label="operating_profit.raw_yoy_pct")
    pay_rate = _finite_number(
        total_pay["raw_yoy_pct"], label="employee_total_pay_derived.raw_yoy_pct"
    )
    people_rate = _finite_number(
        people["raw_yoy_pct"], label="employee_count.raw_yoy_pct"
    )
    capex_rate = _finite_number(capex["raw_yoy_pct"], label="capex.raw_yoy_pct")

    labels = ["営業利益", "給与・賞与総額", "従業員数", "設備投資"]
    values = [op_rate, pay_rate, people_rate, capex_rate]
    colors = [_POSITIVE if value >= 0 else _NEGATIVE for value in values]
    fig, ax = plt.subplots(figsize=(9.8, 5.2))
    bars = ax.bar(labels, values, color=colors, width=0.62)
    ax.axhline(0, color="#263238", linewidth=0.9)
    ax.yaxis.grid(True, color=_GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.set_ylabel("前年同期比（％）")
    ax.set_title("利益・給与・人員・設備投資の伸びを比較")
    span = max(max(abs(value) for value in values), 1.0)
    ax.set_ylim(min(0.0, min(values)) - span * 0.10, max(0.0, max(values)) + span * 0.13)
    for bar, value in zip(bars, values, strict=True):
        value_decimals = 2 if 0 < abs(value) < 0.1 else 1
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + (span * 0.025 if value >= 0 else -span * 0.025),
            f"{value:+.{value_decimals}f}%",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=10,
        )
    fig.text(
        0.01,
        0.01,
        "注：給与・賞与総額は従業員給与と従業員賞与の合計。設備投資はソフトウェア込み。原数値、金融業・保険業を除く。出所：e-Stat。",
        fontsize=8,
        color="#52616B",
    )
    fig.tight_layout(rect=(0, 0.065, 1, 1))
    return _save(fig, path)


def validate_chart_claim_inputs(
    processed: pd.DataFrame,
    industry_contributions: pd.DataFrame,
    capital_contributions: pd.DataFrame,
    claims: pd.DataFrame,
) -> int:
    """Prove that every exact value drawn in a chart is present in claims.csv."""
    expected: dict[tuple[str, str], tuple[float, str, str]] = {}
    for row in industry_contributions.loc[
        industry_contributions["metric_id"].eq("operating_profit")
    ].itertuples():
        value = float(row.raw_yoy_delta_oku_yen) / 10_000.0
        expected[("operating_profit_industry_contribution", str(row.industry_name))] = (
            value,
            "兆円",
            f"{value:+.2f}兆円",
        )
    for row in capital_contributions.loc[
        capital_contributions["metric_id"].eq("operating_profit")
    ].itertuples():
        value = float(row.raw_yoy_delta_oku_yen) / 10_000.0
        expected[("operating_profit_capital_contribution", str(row.capital_size_name))] = (
            value,
            "兆円",
            f"{value:+.2f}兆円",
        )

    sales = _finite_number(_headline(processed, "sales")["raw_value_oku_yen"], label="sales")
    operating = _finite_number(
        _headline(processed, "operating_profit")["raw_value_oku_yen"], label="operating"
    )
    ordinary = _finite_number(
        _headline(processed, "ordinary_profit")["raw_value_oku_yen"], label="ordinary"
    )
    gap = _finite_number(
        _headline(processed, "ordinary_minus_operating")["raw_value_oku_yen"], label="gap"
    )
    profit_values = {
        "operating_margin": (operating / sales * 100.0, "%", f"{operating / sales * 100.0:.1f}%"),
        "ordinary_margin": (ordinary / sales * 100.0, "%", f"{ordinary / sales * 100.0:.1f}%"),
        "operating_level": (operating / 10_000.0, "兆円", f"{operating / 10_000.0:.1f}兆円"),
        "ordinary_level": (ordinary / 10_000.0, "兆円", f"{ordinary / 10_000.0:.1f}兆円"),
        "profit_gap": (gap / 10_000.0, "兆円", f"{gap / 10_000.0:.1f}兆円"),
    }
    for series_key, values in profit_values.items():
        expected[("profit_margin_and_gap", series_key)] = values

    for metric_id in (
        "capex_including_software",
        "capex_excluding_software",
        "software_capex_derived",
    ):
        row = _headline(processed, metric_id)
        level = _finite_number(row["raw_value_oku_yen"], label=f"{metric_id}.level") / 10_000.0
        rate = _finite_number(row["raw_yoy_pct"], label=f"{metric_id}.rate")
        rate_decimals = 2 if 0 < abs(rate) < 0.1 else 1
        expected[("capex_software_bridge", f"{metric_id}:level")] = (
            level,
            "兆円",
            f"{level:.1f}兆円",
        )
        expected[("capex_software_bridge", f"{metric_id}:yoy_pct")] = (
            rate,
            "%",
            f"{rate:+.{rate_decimals}f}%",
        )

    for metric_id in (
        "operating_profit",
        "employee_total_pay_derived",
        "employee_count",
        "capex_including_software",
    ):
        rate = _finite_number(
            _headline(processed, metric_id)["raw_yoy_pct"], label=f"{metric_id}.allocation"
        )
        rate_decimals = 2 if 0 < abs(rate) < 0.1 else 1
        expected[("allocation_growth", metric_id)] = (
            rate,
            "%",
            f"{rate:+.{rate_decimals}f}%",
        )

    chart_claims = claims.loc[claims["claim_usage"].eq("CHART_INPUT")]
    actual_keys = set(zip(chart_claims["chart_id"], chart_claims["series_key"], strict=True))
    if actual_keys != set(expected):
        raise ValueError(
            f"Chart claim keys do not match chart inputs; missing={sorted(set(expected) - actual_keys)}, "
            f"extra={sorted(actual_keys - set(expected))}"
        )
    for row in chart_claims.itertuples():
        value, unit, display = expected[(row.chart_id, row.series_key)]
        if not np.isclose(float(row.value), value, rtol=0.0, atol=1e-12):
            raise ValueError(f"Chart claim value mismatch: {row.claim_id}")
        if row.unit != unit or row.display_value != display:
            raise ValueError(f"Chart claim unit/display mismatch: {row.claim_id}")
        if row.verification_status != "PASS":
            raise ValueError(f"Unverified chart claim: {row.claim_id}")
    return len(chart_claims)


def build_charts(
    processed: pd.DataFrame,
    industry_contributions: pd.DataFrame,
    capital_contributions: pd.DataFrame,
    charts_dir: Path,
    *,
    claims: pd.DataFrame,
) -> list[Path]:
    """Create the five article charts and return their paths in article order.

    Missing/non-finite values and non-calculable rates raise ``ValueError``.  In
    particular, charting never converts unavailable observations to zero.
    """
    _set_style()
    validate_chart_claim_inputs(
        processed, industry_contributions, capital_contributions, claims
    )
    charts_dir = Path(charts_dir)
    return [
        _industry_chart(industry_contributions, charts_dir / CHART_FILENAMES[0]),
        _capital_chart(capital_contributions, charts_dir / CHART_FILENAMES[1]),
        _profit_margin_chart(processed, charts_dir / CHART_FILENAMES[2]),
        _capex_chart(processed, charts_dir / CHART_FILENAMES[3]),
        _allocation_chart(processed, charts_dir / CHART_FILENAMES[4]),
    ]
