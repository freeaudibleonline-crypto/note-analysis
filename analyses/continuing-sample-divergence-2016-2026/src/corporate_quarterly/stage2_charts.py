"""Phase 2 charts built only from audited Stage 2 tables.

Parent aggregates and leaf industries are never placed on the same chart.  A
residual bar may aggregate unshown rows from one taxonomy, but it is labelled as
a display residual rather than as an industry.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.figure import Figure


STAGE2_CHART_FILENAMES = (
    "ordinary_profit_industry_x_capital_waterfall.png",
    "operating_margin_change_by_capital.png",
    "historical_candidate_position.png",
    "software_capex_industry_x_capital.png",
    "ordinary_operating_gap_decomposition.png",
)

_POSITIVE = "#087E8B"
_NEGATIVE = "#D1495B"
_NEUTRAL = "#536878"
_ACCENT = "#F2A541"
_GRID = "#D9DEE3"


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
        metadata={"Software": "corporate-quarterly stage2"},
    )
    plt.close(fig)
    return path


def _finite(series: pd.Series, label: str) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    if values.isna().any() or not np.isfinite(values.to_numpy()).all():
        raise ValueError(f"Missing/non-finite chart input; no zero fill: {label}")
    return values.astype(float)


def _short_capital(name: str) -> str:
    return {
        "1千万円以上 - 1億円未満": "1億円未満",
        "1億円以上 - 10億円未満": "1〜10億円",
        "10億円以上": "10億円以上",
        "全規模": "全規模",
    }.get(name, name)


def _waterfall(major_cross: pd.DataFrame, path: Path) -> Path:
    data = major_cross.copy()
    if set(data.get("taxonomy", [])) != {"major"}:
        raise ValueError("Waterfall requires the mutually exclusive major taxonomy only")
    data["value"] = _finite(
        data["ordinary_profit_yoy_delta_oku_yen"], "ordinary-profit cross delta"
    ) / 10_000.0
    data["label"] = data["industry_name"].astype(str) + "\n" + data[
        "capital_size_name"
    ].astype(str).map(_short_capital)
    data = data.sort_values("value", ascending=False, kind="stable")
    # Keep the figure legible while preserving the exact total with a residual.
    shown = pd.concat([data.head(11), data.tail(6)]).drop_duplicates().copy()
    residual = float(data.loc[~data.index.isin(shown.index), "value"].sum())
    rows = [*(shown[["label", "value"]].itertuples(index=False, name=None))]
    if abs(residual) > 1e-12:
        rows.append(("その他major×規模\n（表示残差）", residual))
    rows.sort(key=lambda row: row[1], reverse=True)
    labels = [row[0] for row in rows]
    values = np.asarray([row[1] for row in rows], dtype=float)
    cumulative = np.r_[0.0, np.cumsum(values)]
    starts = np.minimum(cumulative[:-1], cumulative[1:])
    heights = np.abs(values)
    colors = [_POSITIVE if value >= 0 else _NEGATIVE for value in values]

    fig, ax = plt.subplots(figsize=(15.5, 7.6))
    positions = np.arange(len(values))
    ax.bar(positions, heights, bottom=starts, color=colors, width=0.72)
    for i in range(len(values) - 1):
        ax.plot([i + 0.36, i + 0.64], [cumulative[i + 1]] * 2, color=_NEUTRAL, lw=0.7)
    total = float(values.sum())
    ax.bar(len(values), total, color=_ACCENT, width=0.8)
    ax.axhline(0, color="#263238", linewidth=0.9)
    ax.yaxis.grid(True, color=_GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.set_xticks([*positions, len(values)])
    ax.set_xticklabels([*labels, "全産業合計"], rotation=64, ha="right", fontsize=7.5)
    ax.set_ylabel("経常利益の前年同期差（兆円）")
    ax.set_title("経常増益を作った業種×資本金規模（major taxonomy）")
    for i, value in enumerate(values):
        ax.text(i, cumulative[i + 1], f"{value:+.2f}", ha="center", va="bottom", fontsize=6.8)
    ax.text(len(values), total, f"{total:+.2f}", ha="center", va="bottom", fontsize=8.5)
    fig.text(
        0.01,
        0.005,
        "注：金融業・保険業を除く原数値。親majorのみを使用し、leaf分類は混在させていない。その他は未表示セルの合計。出所：e-Stat。",
        fontsize=8,
        color="#52616B",
    )
    return _save(fig, path)


def _margin_change(capital_bridge: pd.DataFrame, path: Path) -> Path:
    data = capital_bridge.copy().sort_values("capital_size_code", kind="stable")
    for prefix in ("previous", "current"):
        profit = _finite(
            data[f"operating_profit_{prefix}_oku_yen"], f"operating profit {prefix}"
        )
        sales = _finite(data[f"sales_{prefix}_oku_yen"], f"sales {prefix}")
        if (sales <= 0).any():
            raise ValueError("Non-positive sales in margin chart")
        data[f"margin_{prefix}"] = profit / sales * 100.0
    data["delta"] = data["margin_current"] - data["margin_previous"]
    labels = data["capital_size_name"].astype(str).map(_short_capital)
    values = data["delta"].to_numpy(dtype=float)
    colors = [_POSITIVE if value >= 0 else _NEGATIVE for value in values]

    fig, ax = plt.subplots(figsize=(9.2, 5.6))
    bars = ax.bar(labels, values, color=colors, width=0.58)
    ax.axhline(0, color="#263238", linewidth=0.9)
    ax.yaxis.grid(True, color=_GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.set_ylabel("売上高営業利益率の前年差（ポイント）")
    ax.set_title("資本金規模別に利益率の方向が分かれた")
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value,
            f"{value:+.3f}pt",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=9,
        )
    fig.text(
        0.01,
        0.01,
        "注：資本金区分は法的な大企業・中小企業区分ではない。leaf業種合計から再構成。出所：e-Stat。",
        fontsize=8,
        color="#52616B",
    )
    return _save(fig, path)


def _historical_candidates(
    candidate_series: pd.DataFrame, robustness: pd.DataFrame, path: Path
) -> Path:
    labels = {
        "A": "A 大規模製造業集中",
        "B": "B 規模別利益率差",
        "C": "C ソフト投資交代",
        "D": "D 営業利益外差額",
        "E": "E 情報通信機械寄与",
    }
    fig, axes = plt.subplots(5, 1, figsize=(13.2, 14.8), sharex=True)
    robust = robustness.set_index("candidate_id")
    for ax, candidate_id in zip(axes, labels, strict=True):
        data = candidate_series.loc[
            candidate_series["candidate_id"].eq(candidate_id)
            & candidate_series["indicator_status"].eq("CALCULABLE")
        ].sort_values("period_ordinal", kind="stable")
        if data.empty:
            raise ValueError(f"No historical values for candidate {candidate_id}")
        values = _finite(data["indicator_value"], f"candidate {candidate_id}")
        x = pd.to_datetime(data["period_end"])
        threshold = float(data["positive_threshold"].iloc[-1])
        ax.plot(x, values, color=_NEUTRAL, linewidth=1.0)
        ax.axhline(threshold, color=_ACCENT, linewidth=0.9, linestyle="--")
        current = float(values.iloc[-1])
        ax.scatter(x.iloc[-1], current, s=42, color=_POSITIVE, zorder=5)
        # Ratios can explode when the aggregate denominator approaches zero.
        # A symmetric-log scale keeps every genuine observation without clipping.
        q10, q90 = values.quantile([0.10, 0.90])
        if max(abs(values.min()), abs(values.max())) > max(100.0, 20 * max(abs(q10), abs(q90), 1.0)):
            ax.set_yscale("symlog", linthresh=10)
        row = robust.loc[candidate_id]
        percentile = row.get("historical_percentile")
        decision = row.get("pattern_decision")
        percentile_text = "NA" if pd.isna(percentile) else f"{float(percentile):.1f}%ile"
        ax.set_title(
            f"{labels[candidate_id]}  |  2026Q1={current:.2f}  |  {percentile_text}  |  {decision}",
            loc="left",
            fontsize=10.5,
        )
        ax.yaxis.grid(True, color=_GRID, linewidth=0.6)
        ax.set_axisbelow(True)
    axes[-1].set_xlabel("current-vintage historical series（過去公表時点の改訂頑健性は未検証）")
    fig.suptitle("候補指標の長期推移と2026Q1の歴史的位置", fontsize=15, fontweight="bold", y=0.997)
    fig.text(
        0.01,
        0.002,
        "注：破線は事前固定した正方向の閾値。A・D・Eは分母が小さい期に比率が大きく振れるため、一部軸はsymlog。出所：e-Stat表1。",
        fontsize=8,
        color="#52616B",
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.985))
    return _save(fig, path)


def _software_cross(software: pd.DataFrame, path: Path) -> Path:
    data = software.loc[
        software["taxonomy"].eq("leaf")
        & software["aggregation_level"].eq("INDUSTRY_X_CAPITAL")
    ].copy()
    data["value"] = _finite(
        data["software_capex_yoy_delta_oku_yen"], "software leaf cross delta"
    )
    data["label"] = data["industry_name"].astype(str) + " / " + data[
        "capital_size_name"
    ].astype(str).map(_short_capital)
    top = data.reindex(data["value"].abs().sort_values(ascending=False).index).head(16).copy()
    residual = float(data.loc[~data.index.isin(top.index), "value"].sum())
    if abs(residual) > 1e-12:
        top = pd.concat(
            [top, pd.DataFrame([{"label": "その他leafセル（表示残差）", "value": residual}])],
            ignore_index=True,
        )
    top = top.sort_values("value", kind="stable")
    values = top["value"].to_numpy(dtype=float)
    colors = [_POSITIVE if value >= 0 else _NEGATIVE for value in values]

    fig, ax = plt.subplots(figsize=(11.5, 8.0))
    bars = ax.barh(top["label"], values, color=colors, height=0.68)
    ax.axvline(0, color="#263238", linewidth=0.9)
    ax.xaxis.grid(True, color=_GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.set_xlabel("逆算ソフトウェア投資の前年同期差（億円）")
    ax.set_title("ソフトウェア投資増加の業種×資本金規模分解（leaf taxonomy）")
    span = max(np.max(np.abs(values)), 1.0)
    ax.set_xlim(min(0.0, values.min()) - span * 0.12, max(0.0, values.max()) + span * 0.16)
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            value + np.sign(value or 1.0) * span * 0.012,
            bar.get_y() + bar.get_height() / 2,
            f"{value:+,.0f}",
            va="center",
            ha="left" if value >= 0 else "right",
            fontsize=8,
        )
    fig.text(
        0.01,
        0.005,
        "注：ソフトウェア込み設備投資−除く設備投資の差額で、直接公表系列ではない。leafのみ。出所：e-Stat。",
        fontsize=8,
        color="#52616B",
    )
    return _save(fig, path)


def _gap_decomposition(gap: pd.DataFrame, path: Path) -> Path:
    data = gap.loc[
        gap["aggregation_level"].isin(["ALL", "CAPITAL"])
    ].copy()
    order = {"19": 0, "24": 1, "25": 2, "26": 3}
    data["_order"] = data["capital_size_code"].astype(str).map(order)
    data = data.sort_values("_order", kind="stable")
    op = _finite(data["operating_profit_yoy_delta_oku_yen"], "operating delta") / 10_000.0
    difference = _finite(
        data["net_non_operating_gap_yoy_delta_oku_yen"], "gap delta"
    ) / 10_000.0
    ordinary = _finite(data["ordinary_profit_yoy_delta_oku_yen"], "ordinary delta") / 10_000.0
    if not np.allclose(op + difference, ordinary, atol=1e-9, rtol=0):
        raise ValueError("Gap chart identity failed")
    labels = data["capital_size_name"].astype(str).map(_short_capital)

    fig, ax = plt.subplots(figsize=(10.5, 6.2))
    x = np.arange(len(data))
    ax.bar(x, op, color=_POSITIVE, label="営業利益前年差")
    ax.bar(x, difference, bottom=op, color=_ACCENT, label="純差額の前年差")
    ax.scatter(x, ordinary, color="#263238", s=30, zorder=4, label="経常利益前年差")
    ax.axhline(0, color="#263238", linewidth=0.9)
    ax.yaxis.grid(True, color=_GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.set_xticks(x, labels)
    ax.set_ylabel("前年同期差（兆円）")
    ax.set_title("経常利益前年差＝営業利益前年差＋純差額の前年差")
    ax.legend(frameon=False, ncol=3, loc="upper left")
    for i, value in enumerate(ordinary):
        ax.text(i, value, f"{value:+.2f}", ha="center", va="bottom", fontsize=8.5)
    fig.text(
        0.01,
        0.01,
        "注：純差額は経常利益−営業利益。受取利息・配当、為替、持分法損益、支払利息その他を含み得る。",
        fontsize=8,
        color="#52616B",
    )
    return _save(fig, path)


def build_stage2_charts(
    *,
    major_cross: pd.DataFrame,
    capital_bridge: pd.DataFrame,
    candidate_series: pd.DataFrame,
    robustness: pd.DataFrame,
    software_decomposition: pd.DataFrame,
    ordinary_operating_gap: pd.DataFrame,
    charts_dir: Path,
) -> list[Path]:
    """Generate all five required charts and return their paths in fixed order."""
    _set_style()
    charts_dir.mkdir(parents=True, exist_ok=True)
    builders = (
        _waterfall(major_cross, charts_dir / STAGE2_CHART_FILENAMES[0]),
        _margin_change(capital_bridge, charts_dir / STAGE2_CHART_FILENAMES[1]),
        _historical_candidates(
            candidate_series, robustness, charts_dir / STAGE2_CHART_FILENAMES[2]
        ),
        _software_cross(
            software_decomposition, charts_dir / STAGE2_CHART_FILENAMES[3]
        ),
        _gap_decomposition(
            ordinary_operating_gap, charts_dir / STAGE2_CHART_FILENAMES[4]
        ),
    )
    return list(builders)
