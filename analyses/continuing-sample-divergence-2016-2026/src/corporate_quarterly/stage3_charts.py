"""Stage 3 charts for sample sensitivity and the non-operating bridge.

The public sample-sensitivity article may use the first two charts only.  The
third chart belongs to the mutually exclusive non-operating-bridge candidate.
In particular, the continuing-sample chart shows only a direction inferred
from published sales and operating-profit growth rates; it never fabricates an
operating-margin level or a percentage-point change.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
import numpy as np
import pandas as pd

if TYPE_CHECKING:  # pragma: no cover - imports are for static checking only
    from .stage2_continuing_sample import ContinuingSampleAnalysis
    from .stage2_phase3_non_operating import Phase3NonOperatingAnalysis


STAGE3_CHART_FILENAMES = (
    "current_sample_margin_direction.png",
    "historical_sample_reversal_frequency.png",
    "nonoperating_four_item_bridge.png",
)

PUBLIC_SAMPLE_CHART_FILENAMES = STAGE3_CHART_FILENAMES[:2]

_POSITIVE = "#087E8B"
_NEGATIVE = "#D1495B"
_NEUTRAL = "#52616B"
_ACCENT = "#F2A541"
_GRID = "#D9DEE3"
_CONTINUING_LIMITATION_FOOTNOTE = (
    "継続標本は通常系列より標本数が少なく、"
    "営業利益・経常利益の標準誤差率は未算出。"
)
_CAPITAL_ORDER = ("19", "24", "25")
_CAPITAL_LABELS = {
    "19": "資本金1千万円以上\n1億円未満層",
    "24": "資本金1億円以上\n10億円未満層",
    "25": "資本金10億円以上層",
}


def _set_style() -> None:
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
        metadata={"Software": "corporate-quarterly stage3"},
    )
    plt.close(fig)
    return path


def _finite_number(value: object, label: str) -> float:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number) or not np.isfinite(float(number)):
        raise ValueError(f"Missing/non-finite chart input; no zero fill: {label}")
    return float(number)


def _current_capital_margin_rows(
    analysis: "ContinuingSampleAnalysis",
) -> pd.DataFrame:
    required = {
        "period_code",
        "breakdown",
        "category_code",
        "regular_sales_yoy_pct",
        "regular_operating_profit_yoy_pct",
        "regular_relative_margin_change_direction",
        "continuing_sales_yoy_pct",
        "continuing_operating_profit_yoy_pct",
        "continuing_relative_margin_change_direction",
        "continuing_relative_margin_status",
    }
    missing = required - set(analysis.relative_margin_comparison.columns)
    if missing:
        raise ValueError(f"Relative-margin input lacks columns: {sorted(missing)}")
    data = analysis.relative_margin_comparison.loc[
        analysis.relative_margin_comparison["period_code"].astype(str).eq("20261")
        & analysis.relative_margin_comparison["breakdown"].eq("capital_size")
        & analysis.relative_margin_comparison["category_code"]
        .astype(str)
        .isin(_CAPITAL_ORDER)
    ].copy()
    if data["category_code"].astype(str).duplicated().any() or len(data) != 3:
        raise ValueError("Expected one 2026Q1 relative-margin row for each capital tier")
    data["category_code"] = data["category_code"].astype(str)
    data = data.set_index("category_code").loc[list(_CAPITAL_ORDER)].reset_index()
    allowed = {"UP", "DOWN", "FLAT"}
    for prefix in ("regular", "continuing"):
        directions = set(data[f"{prefix}_relative_margin_change_direction"])
        if not directions <= allowed:
            raise ValueError(f"Unusable {prefix} margin directions: {sorted(directions)}")
    if not data["continuing_relative_margin_status"].eq(
        "PROXY_PROFIT_BASE_SIGN_NOT_PUBLISHED"
    ).all():
        raise ValueError("Continuing-sample margin direction lost its proxy status")
    return data


def chart_current_sample_margin_direction(
    analysis: "ContinuingSampleAnalysis", path: Path
) -> Path:
    """Render a categorical two-sample direction matrix for 2026Q1."""
    _set_style()
    data = _current_capital_margin_rows(analysis)
    fig, ax = plt.subplots(figsize=(12.8, 5.9))
    ax.set_xlim(-0.5, 2.5)
    ax.set_ylim(-0.55, 1.55)
    ax.set_xticks(range(3), [_CAPITAL_LABELS[code] for code in _CAPITAL_ORDER])
    ax.set_yticks((1, 0), ("通常系列", "継続標本系列"))
    ax.tick_params(axis="x", labelsize=10)
    ax.tick_params(axis="y", labelsize=11)
    for spine in ax.spines.values():
        spine.set_visible(False)

    for x, row in enumerate(data.itertuples(index=False)):
        for y, prefix in ((1, "regular"), (0, "continuing")):
            direction = getattr(row, f"{prefix}_relative_margin_change_direction")
            sales = _finite_number(
                getattr(row, f"{prefix}_sales_yoy_pct"), f"{prefix} sales {row.category_code}"
            )
            operating = _finite_number(
                getattr(row, f"{prefix}_operating_profit_yoy_pct"),
                f"{prefix} operating profit {row.category_code}",
            )
            color = _POSITIVE if direction == "UP" else (_NEGATIVE if direction == "DOWN" else _NEUTRAL)
            marker = "↑" if direction == "UP" else ("↓" if direction == "DOWN" else "→")
            qualifier = "（方向代理）" if prefix == "continuing" else ""
            ax.scatter(x, y, s=3000, marker="s", color=color, alpha=0.13, edgecolors=color)
            ax.text(
                x,
                y + 0.075,
                f"{marker}{qualifier}",
                ha="center",
                va="center",
                fontsize=16,
                color=color,
                fontweight="bold",
            )
            ax.text(
                x,
                y - 0.17,
                f"売上 {sales:+.1f}% / 営業利益 {operating:+.1f}%",
                ha="center",
                va="center",
                fontsize=9.2,
                color="#263238",
            )
    ax.set_title("2026年1～3月期：標本の置き方で営業利益率の方向が変わる")
    fig.text(
        0.01,
        0.012,
        "注：金融業・保険業を除く。継続標本は売上高と営業利益の前年同期比から上昇・低下方向だけを判定。利益率水準やポイント差ではない。出所：財務省、e-Stat。\n"
        + _CONTINUING_LIMITATION_FOOTNOTE,
        fontsize=8,
        color=_NEUTRAL,
    )
    fig.tight_layout(rect=(0, 0.11, 1, 0.96))
    return _save(fig, path)


def _historical_frequency_rows(
    analysis: "ContinuingSampleAnalysis",
) -> tuple[dict[str, float | int], dict[str, float | int]]:
    headline = analysis.headline_reversal_frequency
    if len(headline) != 1:
        raise ValueError("Expected one headline-reversal frequency row")
    h = headline.iloc[0]
    margin = analysis.relative_margin_reversal_frequency
    small = margin.loc[
        margin["breakdown"].eq("capital_size")
        & margin["category_code"].astype(str).eq("19")
    ]
    if len(small) != 1:
        raise ValueError("Expected one small-capital margin-reversal row")
    m = small.iloc[0]
    first = {
        "numerator": int(h["headline_reversal_count"]),
        "denominator": int(h["comparable_headline_quarters"]),
        "rate": _finite_number(h["headline_reversal_rate_pct"], "headline reversal rate"),
    }
    second = {
        "numerator": int(m["direction_reversal_count"]),
        "denominator": int(m["comparable_direction_quarters"]),
        "rate": _finite_number(m["direction_reversal_rate_pct"], "margin reversal rate"),
    }
    for record in (first, second):
        expected = record["numerator"] / record["denominator"] * 100.0
        if not np.isclose(record["rate"], expected, rtol=0, atol=1e-10):
            raise ValueError("Frequency rate does not match its explicit denominator")
    return first, second


def chart_historical_sample_reversal_frequency(
    analysis: "ContinuingSampleAnalysis", path: Path
) -> Path:
    """Render the two historical definition-sensitivity frequencies."""
    _set_style()
    headline, margin = _historical_frequency_rows(analysis)
    values = np.asarray([headline["rate"], margin["rate"]], dtype=float)
    labels = (
        "規模別見出しの\n成立可否",
        "1億円未満層の\n利益率方向",
    )
    counts = (headline, margin)
    fig, ax = plt.subplots(figsize=(9.6, 5.7))
    bars = ax.barh(labels, values, color=(_ACCENT, _POSITIVE), height=0.55)
    ax.set_xlim(0, 50)
    ax.xaxis.grid(True, color=_GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.set_xlabel("通常系列と継続標本系列で判定が異なる割合（%）")
    ax.set_title("2016年1～3月期以降、標本を替えると判定が反転した頻度")
    for bar, value, count in zip(bars, values, counts, strict=True):
        ax.text(
            value + 0.8,
            bar.get_y() + bar.get_height() / 2,
            f"{count['numerator']}/{count['denominator']}四半期（{value:.2f}%）",
            va="center",
            ha="left",
            fontsize=10,
        )
    fig.text(
        0.01,
        0.012,
        "注：金融業・保険業を除く。継続標本の利益率は方向代理。全期の比較可能性を分母に反映し、0補完していない。出所：財務省、e-Stat。\n"
        + _CONTINUING_LIMITATION_FOOTNOTE,
        fontsize=8,
        color=_NEUTRAL,
    )
    fig.tight_layout(rect=(0, 0.11, 1, 0.96))
    return _save(fig, path)


def _current_nonoperating_rows(
    analysis: "Phase3NonOperatingAnalysis",
) -> pd.DataFrame:
    required = {
        "period_code",
        "industry_code",
        "capital_size_code",
        "component_order",
        "component_id",
        "component_label_ja",
        "source_yoy_delta_oku_yen",
        "profit_impact_yoy_oku_yen",
        "calculation_status",
    }
    missing = required - set(analysis.current_breakdown.columns)
    if missing:
        raise ValueError(f"Non-operating input lacks columns: {sorted(missing)}")
    data = analysis.current_breakdown.loc[
        analysis.current_breakdown["period_code"].astype(str).eq("20261")
        & analysis.current_breakdown["industry_code"].astype(str).eq("104")
        & analysis.current_breakdown["capital_size_code"].astype(str).eq("26")
    ].sort_values("component_order", kind="stable")
    if len(data) != 4 or not data["calculation_status"].eq("CALCULABLE").all():
        raise ValueError("Expected four calculable all-industry/all-capital bridge rows")
    if data["profit_impact_yoy_oku_yen"].isna().any():
        raise ValueError("Non-operating bridge has missing impact; no zero fill")
    return data.copy()


def chart_nonoperating_four_item_bridge(
    analysis: "Phase3NonOperatingAnalysis", path: Path
) -> Path:
    """Render the complete four-item improvement bridge, including its total."""
    _set_style()
    data = _current_nonoperating_rows(analysis)
    impacts = data["profit_impact_yoy_oku_yen"].astype(float).to_numpy()
    total = float(impacts.sum())
    interest_expense = data.loc[data["component_id"].eq("interest_expense")]
    if len(interest_expense) != 1:
        raise ValueError("Expected exactly one interest-expense bridge row")
    interest_source_delta = _finite_number(
        interest_expense.iloc[0]["source_yoy_delta_oku_yen"],
        "interest expense source delta",
    )
    interest_profit_impact = _finite_number(
        interest_expense.iloc[0]["profit_impact_yoy_oku_yen"],
        "interest expense profit impact",
    )
    labels = [
        "受取利息等",
        "その他の\n営業外収益",
        "支払利息等\n（増加・押下げ）",
        "その他の\n営業外費用",
        "営業利益外\n差額の改善",
    ]
    values = np.r_[impacts, total]
    colors = [(_POSITIVE if value >= 0 else _NEGATIVE) for value in impacts] + [_ACCENT]
    fig, ax = plt.subplots(figsize=(11.4, 6.2))
    bars = ax.bar(labels, values, color=colors, width=0.66)
    ax.axhline(0, color="#263238", linewidth=0.9)
    ax.yaxis.grid(True, color=_GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.set_ylabel("経常利益の前年同期差への影響（億円）")
    ax.set_title("2026年1～3月期：営業利益外差額の4項目分解")
    span = max(float(np.abs(values).max()), 1.0)
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + (span * 0.018 if value >= 0 else -span * 0.018),
            f"{value:+,.2f}",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=9,
        )
    fig.text(
        0.01,
        0.01,
        "注：金融業・保険業を除く原数値。"
        f"支払利息等は前年同期より{interest_source_delta:,.2f}億円増え、"
        f"利益影響は{interest_profit_impact:+,.2f}億円。"
        "「その他」の原因は特定しない。出所：e-Stat表1。\n"
        + _CONTINUING_LIMITATION_FOOTNOTE,
        fontsize=8,
        color=_NEUTRAL,
    )
    fig.tight_layout(rect=(0, 0.125, 1, 0.96))
    return _save(fig, path)


def build_stage3_charts(
    *,
    continuing: "ContinuingSampleAnalysis",
    nonoperating: "Phase3NonOperatingAnalysis",
    output_dir: Path,
) -> dict[str, Path]:
    """Write exactly the three registered Stage 3 charts to ``output_dir``."""
    output_dir = Path(output_dir)
    builders = (
        (STAGE3_CHART_FILENAMES[0], chart_current_sample_margin_direction, continuing),
        (
            STAGE3_CHART_FILENAMES[1],
            chart_historical_sample_reversal_frequency,
            continuing,
        ),
        (STAGE3_CHART_FILENAMES[2], chart_nonoperating_four_item_bridge, nonoperating),
    )
    result: dict[str, Path] = {}
    for filename, builder, analysis in builders:
        result[filename] = builder(analysis, output_dir / filename)
    if tuple(result) != STAGE3_CHART_FILENAMES:
        raise AssertionError("Stage 3 chart registry drifted")
    return result
