"""Publication charts for the 2026Q1 v3.1 sample-sensitivity note.

The functions in this module deliberately accept already-audited tabular
results.  They do not recompute the statistical tests and they never fill a
missing value with zero.  Exactly three PNGs belong to the public note.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd


STAGE4_CHART_FILENAMES = (
    "mismatch_heatmap.png",
    "headline_2x2.png",
    "deadband_sensitivity.png",
)

CAPITAL_ORDER = ("small", "middle", "large")
CAPITAL_LABELS = {
    "small": "1千万円以上\n1億円未満層",
    "middle": "1億円以上\n10億円未満層",
    "large": "10億円以上層",
}
METRIC_ORDER = ("relative_margin_direction", "operating_profit", "sales")
METRIC_LABELS = {
    "relative_margin_direction": "利益率方向",
    "operating_profit": "営業利益の符号",
    "sales": "売上高の符号",
}

_INK = "#24323D"
_TEAL = "#087E8B"
_GOLD = "#F2A541"
_RED = "#C8553D"
_PALE = "#EDF2F4"
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
            "axes.labelcolor": _INK,
            "axes.titleweight": "bold",
            "xtick.color": _INK,
            "ytick.color": _INK,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )


def _save(fig: Figure, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        path,
        dpi=190,
        bbox_inches="tight",
        metadata={"Software": "corporate-quarterly stage4"},
    )
    plt.close(fig)
    return path


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{name} lacks columns: {sorted(missing)}")


def _finite(series: pd.Series, label: str) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError(f"{label} contains missing/non-finite values; no zero fill")
    return values.astype(float)


def _canonical_heatmap(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.rename(
        columns={
            "capital_code": "capital_tier",
            "comparable_quarters": "comparable_count",
            "census_sample_design_ja": "regular_sampling_note",
            "rotation_note_ja": "rotation_note",
        }
    ).copy()
    if "capital_tier" in frame:
        frame["capital_tier"] = frame["capital_tier"].astype(str).replace(
            {"19": "small", "24": "middle", "25": "large"}
        )
    if "continuing_sampling_note" not in frame:
        frame["continuing_sampling_note"] = "継続回答条件を適用"
    required = {
        "capital_tier",
        "metric_id",
        "mismatch_count",
        "comparable_count",
        "mismatch_rate_pct",
        "regular_sampling_note",
        "continuing_sampling_note",
        "rotation_note",
    }
    _require_columns(frame, required, "mismatch_heatmap")
    data = frame.copy()
    data["capital_tier"] = data["capital_tier"].astype(str)
    data["metric_id"] = data["metric_id"].astype(str)
    if set(data["capital_tier"]) != set(CAPITAL_ORDER):
        raise ValueError("mismatch_heatmap must contain exactly the three capital tiers")
    expected_pairs = {(tier, metric) for tier in CAPITAL_ORDER for metric in METRIC_ORDER}
    observed_pairs = set(zip(data["capital_tier"], data["metric_id"], strict=False))
    if observed_pairs != expected_pairs or len(data) != len(expected_pairs):
        raise ValueError("mismatch_heatmap must contain one row per tier x metric")
    for col in ("mismatch_count", "comparable_count", "mismatch_rate_pct"):
        data[col] = _finite(data[col], f"mismatch_heatmap.{col}")
    if (data["comparable_count"] <= 0).any():
        raise ValueError("mismatch_heatmap denominator must be positive")
    calculated = 100 * data["mismatch_count"] / data["comparable_count"]
    if not np.allclose(calculated, data["mismatch_rate_pct"], atol=0.051, rtol=0):
        raise ValueError("mismatch_heatmap rates do not match counts")
    return data


def _canonical_2x2(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "regular_headline_supported",
        "continuing_headline_supported",
        "quarter_count",
    }
    _require_columns(frame, required, "headline_2x2")
    data = frame.copy()
    for col in ("regular_headline_supported", "continuing_headline_supported"):
        # CSV round-trips turn booleans into strings on some pandas versions.
        mapped = data[col].map(
            lambda value: value
            if isinstance(value, (bool, np.bool_))
            else str(value).strip().lower() in {"true", "1"}
        )
        data[col] = mapped.astype(bool)
    data["quarter_count"] = _finite(data["quarter_count"], "headline_2x2.quarter_count")
    expected = {(a, b) for a in (False, True) for b in (False, True)}
    observed = set(
        zip(
            data["regular_headline_supported"],
            data["continuing_headline_supported"],
            strict=False,
        )
    )
    if len(data) != 4 or observed != expected:
        raise ValueError("headline_2x2 must contain each Boolean cell exactly once")
    if not np.allclose(data["quarter_count"], np.round(data["quarter_count"])):
        raise ValueError("headline_2x2 counts must be integers")
    return data


def _canonical_deadband(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.rename(
        columns={
            "capital_code": "capital_tier",
            "retained_quarters": "retained_count",
        }
    ).copy()
    if "capital_tier" in frame:
        frame["capital_tier"] = frame["capital_tier"].astype(str).replace(
            {"19": "small", "24": "middle", "25": "large"}
        )
    required = {
        "capital_tier",
        "deadband_pct",
        "mismatch_count",
        "retained_count",
        "mismatch_rate_pct",
    }
    _require_columns(frame, required, "deadband_sensitivity")
    data = frame.copy()
    data["capital_tier"] = data["capital_tier"].astype(str)
    for col in ("deadband_pct", "mismatch_count", "retained_count", "mismatch_rate_pct"):
        data[col] = _finite(data[col], f"deadband_sensitivity.{col}")
    if (data["retained_count"] <= 0).any():
        raise ValueError("deadband retained_count must be positive")
    calculated = 100 * data["mismatch_count"] / data["retained_count"]
    if not np.allclose(calculated, data["mismatch_rate_pct"], atol=0.051, rtol=0):
        raise ValueError("deadband rates do not match counts")
    for tier in CAPITAL_ORDER:
        tier_rows = data.loc[data["capital_tier"].eq(tier)]
        if tier_rows.empty or not np.isclose(tier_rows["deadband_pct"], 3.0).any():
            raise ValueError(f"deadband sensitivity lacks the +/-3% row for {tier}")
    return data


def chart_margin_direction_mismatch(
    mismatch_heatmap: pd.DataFrame,
    path: Path,
) -> Path:
    """Render the tier-by-metric heatmap, led by the primary 16/41 cell."""
    _set_style()
    data = _canonical_heatmap(mismatch_heatmap)
    matrix = np.asarray(
        [
            [
                float(
                    data.loc[
                        data["capital_tier"].eq(tier)
                        & data["metric_id"].eq(metric),
                        "mismatch_rate_pct",
                    ].iloc[0]
                )
                for tier in CAPITAL_ORDER
            ]
            for metric in METRIC_ORDER
        ]
    )
    fig, ax = plt.subplots(figsize=(10.8, 7.1))
    im = ax.imshow(matrix, cmap="YlOrRd", vmin=0, vmax=40)
    ax.set_xticks(range(3), [CAPITAL_LABELS[t] for t in CAPITAL_ORDER])
    ax.set_yticks(range(3), [METRIC_LABELS[m] for m in METRIC_ORDER])
    ax.set_title("2016年1～3月期以降：判定の不一致は小規模資本金層に集中")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="不一致率（%）")
    for y, metric in enumerate(METRIC_ORDER):
        for x, tier in enumerate(CAPITAL_ORDER):
            row = data.loc[
                data["capital_tier"].eq(tier) & data["metric_id"].eq(metric)
            ].iloc[0]
            value = float(row["mismatch_rate_pct"])
            ax.text(
                x,
                y,
                f"{int(row['mismatch_count'])}/{int(row['comparable_count'])}\n{value:.1f}%",
                ha="center",
                va="center",
                color="white" if value > 23 else _INK,
                fontsize=11,
                fontweight="bold",
            )
    ax.add_patch(
        Rectangle(
            (-0.49, -0.49),
            0.98,
            0.98,
            fill=False,
            edgecolor="#5B1A18",
            linewidth=3.0,
        )
    )
    confound_text = ""
    margin_col = "continuing_decision_margin_abs_gap_median_pct"
    divergence_col = "cross_series_growth_gap_divergence_median_pp"
    if margin_col in data and divergence_col in data:
        by_tier = data.drop_duplicates("capital_tier").set_index("capital_tier")
        confound_text = (
            "\n判定余裕中央値（小・中堅・大）: "
            + "／".join(
                f"{float(by_tier.loc[t, margin_col]):.1f}%" for t in CAPITAL_ORDER
            )
            + "；系列間乖離中央値: "
            + "／".join(
                f"{float(by_tier.loc[t, divergence_col]):.2f}pt"
                for t in CAPITAL_ORDER
            )
        )
    fig.text(
        0.01,
        0.012,
        "注：2026年1～3月期の結果を確認後、過去41四半期に適用した探索的バックテスト。"
        "利益率方向は売上高と営業利益の前年同期比から推定。利益率水準やポイント差ではない。\n"
        "継続標本は標本数が小さく、営業利益・経常利益の標準誤差率は未算出。出所：財務省、e-Stat。"
        + confound_text,
        fontsize=8.2,
        color="#56636B",
    )
    fig.tight_layout(rect=(0, 0.18 if confound_text else 0.14, 1, 0.96))
    return _save(fig, path)


def chart_headline_2x2(headline_2x2: pd.DataFrame, path: Path) -> Path:
    """Render the four headline-support cells without a probability reading."""
    _set_style()
    data = _canonical_2x2(headline_2x2)
    matrix = np.zeros((2, 2), dtype=int)
    # y: continuing false/true; x: regular false/true
    for row in data.itertuples(index=False):
        matrix[int(bool(row.continuing_headline_supported)), int(bool(row.regular_headline_supported))] = int(
            row.quarter_count
        )
    if matrix.tolist() != [[29, 9], [2, 1]]:
        raise ValueError(f"Canonical headline 2x2 mismatch: {matrix.tolist()}")
    fig, ax = plt.subplots(figsize=(8.5, 6.6))
    ax.imshow(matrix, cmap="YlGnBu", vmin=0, vmax=max(29, int(matrix.max())))
    ax.set_xticks((0, 1), ("不成立", "成立"))
    ax.set_yticks((0, 1), ("不成立", "成立"))
    ax.set_xlabel("通常系列")
    ax.set_ylabel("継続標本系列")
    ax.set_title("規模別見出しの2×2表（41四半期）")
    labels = [["どちらも29", "通常のみ9"], ["継続のみ2", "両方1"]]
    for y in range(2):
        for x in range(2):
            color = "white" if matrix[y, x] >= 15 else _INK
            ax.text(x, y, labels[y][x], ha="center", va="center", fontsize=14, fontweight="bold", color=color)
    ax.add_patch(Rectangle((0.5, -0.5), 1, 2, fill=False, edgecolor=_GOLD, linewidth=2.3))
    fig.text(
        0.5,
        0.115,
        "成立回数：通常系列10回／継続標本系列3回",
        ha="center",
        fontsize=10.5,
        color=_INK,
        fontweight="bold",
    )
    fig.text(
        0.01,
        0.015,
        "注：2026年1‑3月期の結果を確認後に定義し、過去へ適用した探索的バックテスト。"
        "回数は将来の発生を示すものではない。出所：財務省、e-Stat。",
        fontsize=8.2,
        color="#56636B",
    )
    fig.tight_layout(rect=(0, 0.16, 1, 0.96))
    return _save(fig, path)


def chart_deadband_sensitivity(
    deadband_sensitivity: pd.DataFrame,
    path: Path,
) -> Path:
    """Render the tier-level deadband audit in relative-change-rate units."""
    _set_style()
    dead = _canonical_deadband(deadband_sensitivity)
    fig, ax = plt.subplots(figsize=(10.8, 6.6))
    for tier, color, marker in zip(CAPITAL_ORDER, (_RED, _TEAL, "#66717A"), ("o", "s", "^"), strict=True):
        rows = dead.loc[dead["capital_tier"].eq(tier)].sort_values("deadband_pct", kind="stable")
        ax.plot(
            rows["deadband_pct"],
            rows["mismatch_rate_pct"],
            color=color,
            marker=marker,
            linewidth=2.2,
            markersize=7,
            label=CAPITAL_LABELS[tier].replace("\n", ""),
        )
        for row in rows.itertuples(index=False):
            if tier == "small":
                ax.annotate(
                    f"{int(row.mismatch_count)}/{int(row.retained_count)}",
                    (float(row.deadband_pct), float(row.mismatch_rate_pct)),
                    xytext=(0, 9),
                    textcoords="offset points",
                    ha="center",
                    fontsize=8,
                    color=color,
                )
    ax.axvline(3.0, color=_GOLD, linestyle="--", linewidth=1.2)
    ax.set_xlabel("デッドバンド d（相対変化率・%）")
    ax.set_ylabel("残存期の利益率方向不一致率（%）")
    ax.set_title("両系列がともに±d外の四半期に限定した感応度")
    ax.set_ylim(bottom=0)
    ax.xaxis.grid(True, color=_GRID, linewidth=0.6)
    ax.yaxis.grid(True, color=_GRID, linewidth=0.6)
    ax.legend(frameon=False, fontsize=9)
    plus3 = dead.loc[np.isclose(dead["deadband_pct"], 3.0)].set_index("capital_tier")
    if all(tier in plus3.index for tier in CAPITAL_ORDER):
        ax.text(
            0.98,
            0.04,
            "d=3：小規模 "
            f"{int(plus3.loc['small', 'mismatch_count'])}/{int(plus3.loc['small', 'retained_count'])}"
            f"（{float(plus3.loc['small', 'mismatch_rate_pct']):.1f}%）\n"
            f"中堅 {float(plus3.loc['middle', 'mismatch_rate_pct']):.1f}%／"
            f"大規模 {float(plus3.loc['large', 'mismatch_rate_pct']):.1f}%",
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=9,
            bbox={"facecolor": "white", "edgecolor": _GRID, "alpha": 0.9},
        )
    fig.text(
        0.01,
        0.012,
        "注：単位は売上高前年比と営業利益前年比から推定した利益率の相対変化率（%）。"
        "営業利益率の絶対ポイント差ではない。両系列がともに±d外の期だけを残す。\n"
        "継続標本の営業利益・経常利益の標準誤差率は算出されておらず、標本誤差は別途未定量。",
        fontsize=8.1,
        color="#56636B",
    )
    fig.tight_layout(rect=(0, 0.13, 1, 0.96))
    return _save(fig, path)


def build_stage4_charts(
    *,
    headline_2x2: pd.DataFrame,
    mismatch_heatmap: pd.DataFrame,
    deadband_sensitivity: pd.DataFrame,
    output_dir: Path,
) -> Mapping[str, Path]:
    """Write exactly the three v3.1 public PNGs."""
    output_dir = Path(output_dir)
    builders = (
        (
            STAGE4_CHART_FILENAMES[0],
            lambda path: chart_margin_direction_mismatch(mismatch_heatmap, path),
        ),
        (
            STAGE4_CHART_FILENAMES[1],
            lambda path: chart_headline_2x2(headline_2x2, path),
        ),
        (
            STAGE4_CHART_FILENAMES[2],
            lambda path: chart_deadband_sensitivity(deadband_sensitivity, path),
        ),
    )
    result = {name: builder(output_dir / name) for name, builder in builders}
    if tuple(result) != STAGE4_CHART_FILENAMES:
        raise AssertionError("Stage 4 chart registry drifted")
    return result
