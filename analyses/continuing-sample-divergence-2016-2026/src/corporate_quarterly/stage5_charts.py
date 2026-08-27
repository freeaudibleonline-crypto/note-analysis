"""Charts and machine-readable chart lineage for the 2026Q1 v3.2 release.

The three publication charts are always rendered from their tabular source
data.  Claims provide presentation lineage, but are not used as the numeric
source for chart cells, counts, or rates.  The module intentionally has no
facility for copying an earlier PNG.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
import numpy as np
import pandas as pd


STAGE5_RELEASE_ID = "2026Q1_v3_2"
STAGE5_CHART_FILENAMES = (
    "mismatch_heatmap.png",
    "headline_2x2.png",
    "deadband_sensitivity.png",
)

HEATMAP_CHART_ID = "mismatch_heatmap"
HEADLINE_CHART_ID = "headline_2x2"
DEADBAND_CHART_ID = "deadband_sensitivity"

HEATMAP_TITLE = "通常系列と継続標本系列の方向不一致率\n（2016Q1～2026Q1）"
HEADLINE_TITLE = "複合見出し判定の2×2表（41四半期）"
DEADBAND_TITLE = "利益率方向不一致率のdeadband感応度"

CAPITAL_ORDER = ("small", "middle", "large")
CAPITAL_LABELS = {
    "small": "1,000万円以上\n1億円未満層",
    "middle": "1億円以上\n10億円未満層",
    "large": "10億円以上層",
}
CAPITAL_SHORT_LABELS = {
    "small": "小",
    "middle": "中間",
    "large": "大",
}
METRIC_ORDER = ("relative_margin_direction", "operating_profit", "sales")
METRIC_LABELS = {
    "relative_margin_direction": "営業利益率方向",
    "operating_profit": "営業利益の符号",
    "sales": "売上高の符号",
}

REQUIRED_UNIT_REGISTRY: Mapping[str, str] = {
    "yoy_growth_rate": "percent",
    "difference_between_growth_rates": "percentage_points",
    "direction_mismatch_rate": "percent",
    "implied_relative_margin_change": "percent",
    "deadband_threshold": "percent",
    "count": "count",
    "currency": "oku_yen",
}

DECISION_MARGIN_CLAIM_IDS = {
    "small": "V31-SMALL-DECISION-MARGIN-MEDIAN",
    "middle": "V31-MIDDLE-DECISION-MARGIN-MEDIAN",
    "large": "V31-LARGE-DECISION-MARGIN-MEDIAN",
}
DIVERGENCE_CLAIM_IDS = {
    "small": "V31-SMALL-SERIES-DIVERGENCE-MEDIAN",
    "middle": "V31-MIDDLE-SERIES-DIVERGENCE-MEDIAN",
    "large": "V31-LARGE-SERIES-DIVERGENCE-MEDIAN",
}
PRIMARY_MISMATCH_CLAIM_ID = "V31-SMALL-MARGIN-DIRECTION-MISMATCH"

_INK = "#24323D"
_TEAL = "#087E8B"
_GOLD = "#F2A541"
_RED = "#C8553D"
_SLATE = "#66717A"
_GRID = "#D9DEE3"


TabularInput = pd.DataFrame | str | Path
RegistryInput = Mapping[str, Any] | str | Path
ClaimsLineageInput = pd.DataFrame | Mapping[str, Sequence[str]] | str | Path


@dataclass(frozen=True)
class Stage5ChartBuildResult:
    """Paths and JSON-serialisable manifest entries from one fresh render."""

    png_paths: Mapping[str, Path]
    manifest_entries: tuple[dict[str, Any], ...]

    @property
    def charts(self) -> Mapping[str, Path]:
        """Compatibility-friendly alias for callers that name the paths charts."""

        return self.png_paths

    def __iter__(self):
        """Allow ``paths, entries = build_stage5_charts(...)`` unpacking."""

        yield self.png_paths
        yield self.manifest_entries


@dataclass(frozen=True)
class _Source:
    frame: pd.DataFrame
    label: str
    sha256: str
    path: Path | None


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
            "axes.edgecolor": _SLATE,
            "axes.labelcolor": _INK,
            "axes.titleweight": "bold",
            "xtick.color": _INK,
            "ytick.color": _INK,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dataframe_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, lineterminator="\n").encode("utf-8")


def _source_override(
    name: str,
    source_csv_paths: Mapping[str, str | Path] | None,
) -> Path | None:
    if not source_csv_paths:
        return None
    for key in (name, f"{name}.csv"):
        if key in source_csv_paths:
            return Path(source_csv_paths[key])
    return None


def _load_tabular_source(
    source: TabularInput,
    *,
    name: str,
    source_csv_paths: Mapping[str, str | Path] | None = None,
) -> _Source:
    if isinstance(source, pd.DataFrame):
        frame = source.copy()
        override = _source_override(name, source_csv_paths)
        if override is not None:
            if not override.is_file():
                raise ValueError(f"Declared source CSV does not exist: {override}")
            return _Source(frame, str(override), _sha256_file(override), override)
        payload = _dataframe_bytes(frame)
        return _Source(
            frame,
            f"dataframe://{name}.csv",
            sha256(payload).hexdigest(),
            None,
        )

    path = Path(source)
    if not path.is_file():
        raise ValueError(f"Source CSV does not exist: {path}")
    return _Source(pd.read_csv(path), str(path), _sha256_file(path), path)


def _load_json_mapping(source: RegistryInput) -> Mapping[str, Any]:
    if isinstance(source, Mapping):
        return source
    path = Path(source)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("unit registry must be a JSON object")
    return payload


def _normalise_unit(value: Any) -> str:
    text = str(value).strip().lower().replace("-", "_")
    aliases = {
        "%": "percent",
        "pct": "percent",
        "percentage point": "percentage_points",
        "percentage points": "percentage_points",
        "percentage_point": "percentage_points",
        "pp": "percentage_points",
        "pt": "percentage_points",
        "quarters": "count",
        "quarter": "count",
        "件": "count",
        "億円": "oku_yen",
    }
    return aliases.get(text, text)


def _unit_values(entry: Any) -> set[str]:
    if isinstance(entry, str):
        return {_normalise_unit(entry)}
    if isinstance(entry, Sequence) and not isinstance(entry, (str, bytes)):
        return {_normalise_unit(value) for value in entry}
    if isinstance(entry, Mapping):
        for key in (
            "allowed_units",
            "allowed_unit",
            "canonical_unit",
            "unit",
        ):
            if key in entry:
                return _unit_values(entry[key])
    return set()


def canonical_unit_registry(source: RegistryInput) -> dict[str, set[str]]:
    """Return metric-type units from the supported registry layouts."""

    raw = _load_json_mapping(source)
    candidate: Mapping[str, Any] = raw
    for key in (
        "canonical_unit_by_metric_type",
        "metric_types",
        "metrics",
        "registry",
        "allowed_units",
    ):
        nested = raw.get(key)
        if isinstance(nested, Mapping):
            candidate = nested
            break
    return {
        metric_type: _unit_values(candidate.get(metric_type))
        for metric_type in REQUIRED_UNIT_REGISTRY
    }


def validate_stage5_unit_registry(source: RegistryInput) -> tuple[str, ...]:
    """Validate the canonical units needed by the chart layer."""

    units = canonical_unit_registry(source)
    errors: list[str] = []
    for metric_type, expected in REQUIRED_UNIT_REGISTRY.items():
        if expected not in units.get(metric_type, set()):
            errors.append(f"unit_registry:{metric_type}:expected_{expected}")
    if "percent" in units.get("difference_between_growth_rates", set()):
        errors.append(
            "unit_registry:difference_between_growth_rates:percent_is_forbidden"
        )
    return tuple(errors)


def _claims_frame(source: ClaimsLineageInput) -> pd.DataFrame | None:
    if isinstance(source, pd.DataFrame):
        return source.copy()
    if isinstance(source, Mapping):
        return None
    path = Path(source)
    if not path.is_file():
        raise ValueError(f"Claims lineage CSV does not exist: {path}")
    return pd.read_csv(path)


def _split_chart_ids(value: Any) -> set[str]:
    if pd.isna(value):
        return set()
    text = str(value).replace(",", ";")
    return {item.strip() for item in text.split(";") if item.strip()}


def _claim_ids_for_chart(
    claims_lineage: ClaimsLineageInput,
    *,
    chart_id: str,
    filename: str,
) -> list[str]:
    if isinstance(claims_lineage, Mapping):
        values: Sequence[str] | None = None
        for key in (filename, chart_id, Path(filename).stem):
            if key in claims_lineage:
                values = claims_lineage[key]
                break
        if values is None:
            return []
        return sorted({str(value) for value in values if str(value).strip()})

    claims = _claims_frame(claims_lineage)
    if claims is None or "claim_id" not in claims.columns:
        raise ValueError("claims lineage must include claim_id")
    if "chart_ids" not in claims.columns:
        raise ValueError("claims lineage must include chart_ids")
    aliases = {filename, chart_id, Path(filename).stem}
    selected = claims["chart_ids"].map(
        lambda value: bool(_split_chart_ids(value) & aliases)
    )
    ids = set(claims.loc[selected, "claim_id"].dropna().astype(str))
    if chart_id == DEADBAND_CHART_ID and PRIMARY_MISMATCH_CLAIM_ID in set(
        claims["claim_id"].dropna().astype(str)
    ):
        ids.add(PRIMARY_MISMATCH_CLAIM_ID)
    return sorted(ids)


def _require_columns(frame: pd.DataFrame, required: Iterable[str], name: str) -> None:
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"{name} lacks columns: {sorted(missing)}")


def _finite(series: pd.Series, label: str) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError(f"{label} contains missing/non-finite values; no zero fill")
    return values.astype(float)


def _capital_tiers(frame: pd.DataFrame) -> pd.Series:
    if "capital_tier" in frame.columns:
        values = frame["capital_tier"].astype(str)
    elif "capital_code" in frame.columns:
        values = frame["capital_code"].astype(str)
    else:
        raise ValueError("capital tier/code column is missing")
    return values.replace({"19": "small", "24": "middle", "25": "large"})


def _canonical_heatmap(frame: pd.DataFrame) -> pd.DataFrame:
    if "continuing_decision_margin_abs_gap_median_pct" in frame.columns:
        raise ValueError(
            "legacy decision-margin column is forbidden; use "
            "continuing_decision_margin_abs_gap_median_pp"
        )
    required = {
        "metric_id",
        "mismatch_count",
        "mismatch_rate_pct",
        "continuing_decision_margin_abs_gap_median_pp",
        "cross_series_growth_gap_divergence_median_pp",
    }
    _require_columns(frame, required, "mismatch_heatmap")
    data = frame.copy()
    data["capital_tier"] = _capital_tiers(data)
    if "comparable_quarters" in data.columns:
        data["comparable_count"] = data["comparable_quarters"]
    elif "comparable_count" not in data.columns:
        raise ValueError("mismatch_heatmap lacks comparable_quarters/count")
    data["metric_id"] = data["metric_id"].astype(str)
    expected_pairs = {(tier, metric) for tier in CAPITAL_ORDER for metric in METRIC_ORDER}
    observed_pairs = set(zip(data["capital_tier"], data["metric_id"], strict=False))
    if len(data) != len(expected_pairs) or observed_pairs != expected_pairs:
        raise ValueError("mismatch_heatmap must contain one row per tier x metric")
    for column in (
        "mismatch_count",
        "comparable_count",
        "mismatch_rate_pct",
        "continuing_decision_margin_abs_gap_median_pp",
        "cross_series_growth_gap_divergence_median_pp",
    ):
        data[column] = _finite(data[column], f"mismatch_heatmap.{column}")
    if (data["comparable_count"] <= 0).any():
        raise ValueError("mismatch_heatmap denominators must be positive")
    calculated = 100.0 * data["mismatch_count"] / data["comparable_count"]
    if not np.allclose(calculated, data["mismatch_rate_pct"], atol=0.051, rtol=0):
        raise ValueError("mismatch_heatmap rates do not match counts")
    for tier in CAPITAL_ORDER:
        tier_rows = data.loc[data["capital_tier"].eq(tier)]
        for column in (
            "continuing_decision_margin_abs_gap_median_pp",
            "cross_series_growth_gap_divergence_median_pp",
        ):
            if tier_rows[column].nunique(dropna=False) != 1:
                raise ValueError(f"{column} is not constant within tier {tier}")
    return data


def _parse_bool(value: Any, *, label: str) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    raise ValueError(f"{label} contains a non-Boolean value: {value!r}")


def _canonical_2x2(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "regular_headline_supported",
        "continuing_headline_supported",
        "quarter_count",
    }
    _require_columns(frame, required, "headline_2x2")
    data = frame.copy()
    for column in ("regular_headline_supported", "continuing_headline_supported"):
        data[column] = data[column].map(lambda value: _parse_bool(value, label=column))
    data["quarter_count"] = _finite(data["quarter_count"], "headline_2x2.quarter_count")
    if not np.allclose(data["quarter_count"], np.round(data["quarter_count"])):
        raise ValueError("headline_2x2 counts must be integers")
    expected = {(a, b) for a in (False, True) for b in (False, True)}
    observed = set(
        zip(
            data["regular_headline_supported"],
            data["continuing_headline_supported"],
            strict=False,
        )
    )
    if len(data) != 4 or observed != expected:
        raise ValueError("headline_2x2 must contain every Boolean cell exactly once")
    if "cell_id" not in data.columns:
        lookup = {
            (True, False): "REGULAR_ONLY",
            (False, True): "CONTINUING_ONLY",
            (True, True): "BOTH",
            (False, False): "NEITHER",
        }
        data["cell_id"] = [
            lookup[(regular, continuing)]
            for regular, continuing in zip(
                data["regular_headline_supported"],
                data["continuing_headline_supported"],
                strict=False,
            )
        ]
    return data


def _canonical_deadband(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"deadband_pct", "mismatch_count", "mismatch_rate_pct"}
    _require_columns(frame, required, "deadband_sensitivity")
    data = frame.copy()
    data["capital_tier"] = _capital_tiers(data)
    if "retained_quarters" in data.columns:
        data["retained_count"] = data["retained_quarters"]
    elif "retained_count" not in data.columns:
        raise ValueError("deadband_sensitivity lacks retained_quarters/count")
    for column in (
        "deadband_pct",
        "mismatch_count",
        "retained_count",
        "mismatch_rate_pct",
    ):
        data[column] = _finite(data[column], f"deadband_sensitivity.{column}")
    if (data["retained_count"] <= 0).any():
        raise ValueError("deadband denominators must be positive")
    calculated = 100.0 * data["mismatch_count"] / data["retained_count"]
    if not np.allclose(calculated, data["mismatch_rate_pct"], atol=0.051, rtol=0):
        raise ValueError("deadband rates do not match counts")
    required_thresholds = {0.5, 1.0, 2.0, 3.0}
    for tier in CAPITAL_ORDER:
        observed = set(data.loc[data["capital_tier"].eq(tier), "deadband_pct"])
        if not required_thresholds.issubset(observed):
            raise ValueError(f"deadband sensitivity lacks required rows for {tier}")
    if data.duplicated(["capital_tier", "deadband_pct"]).any():
        raise ValueError("deadband sensitivity contains duplicate tier/threshold rows")
    return data


def _with_no_deadband_baseline(
    deadband: pd.DataFrame,
    heatmap: pd.DataFrame,
) -> pd.DataFrame:
    data = deadband.copy()
    existing = data.loc[
        data["capital_tier"].eq("small") & np.isclose(data["deadband_pct"], 0.0)
    ]
    source = heatmap.loc[
        heatmap["capital_tier"].eq("small")
        & heatmap["metric_id"].eq("relative_margin_direction")
    ]
    if len(source) != 1:
        raise ValueError("cannot derive no-deadband baseline from mismatch heatmap")
    source_row = source.iloc[0]
    if not existing.empty:
        if len(existing) != 1:
            raise ValueError("deadband sensitivity has duplicate no-deadband baselines")
        row = existing.iloc[0]
        if (
            int(row["mismatch_count"]) != int(source_row["mismatch_count"])
            or int(row["retained_count"]) != int(source_row["comparable_count"])
        ):
            raise ValueError("no-deadband baseline conflicts with mismatch heatmap")
        data.loc[existing.index, "row_origin"] = "SOURCE_CSV_VALIDATED_AGAINST_HEATMAP"
        return data

    baseline = {column: np.nan for column in data.columns}
    baseline.update(
        {
            "capital_tier": "small",
            "deadband_pct": 0.0,
            "mismatch_count": float(source_row["mismatch_count"]),
            "retained_count": float(source_row["comparable_count"]),
            "mismatch_rate_pct": float(source_row["mismatch_rate_pct"]),
            "row_origin": "DERIVED_FROM_MISMATCH_HEATMAP_SOURCE",
        }
    )
    data["row_origin"] = data.get("row_origin", "SOURCE_CSV")
    data["row_origin"] = data["row_origin"].fillna("SOURCE_CSV")
    return pd.concat([pd.DataFrame([baseline]), data], ignore_index=True)


def _tier_summary(heatmap: pd.DataFrame) -> pd.DataFrame:
    return heatmap.drop_duplicates("capital_tier").set_index("capital_tier")


def _heatmap_footnote(heatmap: pd.DataFrame) -> str:
    tiers = _tier_summary(heatmap)
    margins = "／".join(
        f"{float(tiers.loc[tier, 'continuing_decision_margin_abs_gap_median_pp']):.1f}pt"
        for tier in CAPITAL_ORDER
    )
    divergences = "／".join(
        f"{float(tiers.loc[tier, 'cross_series_growth_gap_divergence_median_pp']):.2f}pt"
        for tier in CAPITAL_ORDER
    )
    return (
        "注：利益率方向は売上高前年比と営業利益前年比から推定した相対変化の方向。"
        "利益率水準のポイント変化ではない。\n"
        f"判定余裕中央値（小・中間・大）：{margins}；"
        f"系列間乖離中央値：{divergences}。出所：財務省、e-Stat。"
    )


def _headline_footnote(headline: pd.DataFrame) -> str:
    regular_total = int(
        headline.loc[headline["regular_headline_supported"], "quarter_count"].sum()
    )
    continuing_total = int(
        headline.loc[headline["continuing_headline_supported"], "quarter_count"].sum()
    )
    return (
        "注：2026Q1の結果を確認後に過去へ適用した探索的な複合見出し判定。"
        f"成立回数は通常系列{regular_total}回、継続標本系列{continuing_total}回。"
        "将来頻度の推計ではない。出所：財務省、e-Stat。"
    )


def _deadband_footnote() -> str:
    return (
        "注：deadbandは、売上高前年比と営業利益前年比から推定した営業利益率の"
        "相対変化率に対する％。営業利益率の絶対的なパーセントポイント差ではない。"
        "両系列がともに±d外の期だけを残す。"
    )


def _save(
    fig: Figure,
    path: Path,
    *,
    title: str,
    footnote: str,
    source_sha256: str,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        path,
        dpi=190,
        bbox_inches="tight",
        metadata={
            "Software": "corporate-quarterly stage5",
            "Title": title.replace("\n", " "),
            "Description": footnote,
            "Source": source_sha256,
        },
    )
    plt.close(fig)
    return path


def chart_mismatch_heatmap(
    mismatch_heatmap: pd.DataFrame,
    path: Path,
    *,
    source_sha256: str = "",
) -> tuple[Path, dict[str, Any]]:
    """Render the neutral tier-by-metric direction-mismatch heatmap."""

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
    footnote = _heatmap_footnote(data)
    fig, ax = plt.subplots(figsize=(10.8, 7.2))
    image = ax.imshow(matrix, cmap="YlGnBu", vmin=0, vmax=40)
    ax.set_xticks(range(3), [CAPITAL_LABELS[tier] for tier in CAPITAL_ORDER])
    ax.set_yticks(range(3), [METRIC_LABELS[metric] for metric in METRIC_ORDER])
    ax.set_xlabel("資本金階層")
    ax.set_ylabel("指標")
    ax.set_title(HEATMAP_TITLE)
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04, label="方向不一致率（%）")
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
                color="white" if value > 24 else _INK,
                fontsize=11,
                fontweight="bold",
            )
    fig.text(0.01, 0.012, footnote, fontsize=8.1, color="#56636B")
    fig.tight_layout(rect=(0, 0.12, 1, 0.96))
    saved = _save(
        fig,
        path,
        title=HEATMAP_TITLE,
        footnote=footnote,
        source_sha256=source_sha256,
    )
    tiers = _tier_summary(data)
    metadata = {
        "cells": [
            {
                "capital_tier": tier,
                "metric_id": metric,
                "numerator": int(
                    data.loc[
                        data["capital_tier"].eq(tier)
                        & data["metric_id"].eq(metric),
                        "mismatch_count",
                    ].iloc[0]
                ),
                "denominator": int(
                    data.loc[
                        data["capital_tier"].eq(tier)
                        & data["metric_id"].eq(metric),
                        "comparable_count",
                    ].iloc[0]
                ),
                "rate_percent": float(
                    data.loc[
                        data["capital_tier"].eq(tier)
                        & data["metric_id"].eq(metric),
                        "mismatch_rate_pct",
                    ].iloc[0]
                ),
            }
            for tier in CAPITAL_ORDER
            for metric in METRIC_ORDER
        ],
        "decision_margin_medians": [
            {
                "capital_tier": tier,
                "value": float(
                    tiers.loc[
                        tier, "continuing_decision_margin_abs_gap_median_pp"
                    ]
                ),
                "unit": "percentage_points",
            }
            for tier in CAPITAL_ORDER
        ],
        "cross_series_divergence_medians": [
            {
                "capital_tier": tier,
                "value": float(
                    tiers.loc[tier, "cross_series_growth_gap_divergence_median_pp"]
                ),
                "unit": "percentage_points",
            }
            for tier in CAPITAL_ORDER
        ],
    }
    return saved, metadata


def chart_headline_2x2(
    headline_2x2: pd.DataFrame,
    path: Path,
    *,
    source_sha256: str = "",
) -> tuple[Path, dict[str, Any]]:
    """Render the four exploratory headline cells from the supplied counts."""

    _set_style()
    data = _canonical_2x2(headline_2x2)
    matrix = np.zeros((2, 2), dtype=int)
    cell_ids = np.empty((2, 2), dtype=object)
    for row in data.itertuples(index=False):
        y = int(bool(row.continuing_headline_supported))
        x = int(bool(row.regular_headline_supported))
        matrix[y, x] = int(row.quarter_count)
        cell_ids[y, x] = str(row.cell_id)
    cell_labels = {
        "REGULAR_ONLY": "通常系列のみ成立",
        "CONTINUING_ONLY": "継続標本系列のみ成立",
        "BOTH": "両方で成立",
        "NEITHER": "どちらも不成立",
    }
    footnote = _headline_footnote(data)
    fig, ax = plt.subplots(figsize=(8.7, 6.7))
    ax.imshow(matrix, cmap="YlGnBu", vmin=0, vmax=max(1, int(matrix.max())))
    ax.set_xticks((0, 1), ("不成立", "成立"))
    ax.set_yticks((0, 1), ("不成立", "成立"))
    ax.set_xlabel("通常系列")
    ax.set_ylabel("継続標本系列")
    ax.set_title(HEADLINE_TITLE)
    for y in range(2):
        for x in range(2):
            count = int(matrix[y, x])
            label = cell_labels[str(cell_ids[y, x])]
            ax.text(
                x,
                y,
                f"{label}\n{count}",
                ha="center",
                va="center",
                fontsize=12.5,
                fontweight="bold",
                color="white" if count > matrix.max() / 2 else _INK,
            )
    fig.text(0.01, 0.015, footnote, fontsize=8.2, color="#56636B")
    fig.tight_layout(rect=(0, 0.10, 1, 0.96))
    saved = _save(
        fig,
        path,
        title=HEADLINE_TITLE,
        footnote=footnote,
        source_sha256=source_sha256,
    )
    metadata = {
        "cells": [
            {
                "cell_id": str(row.cell_id),
                "regular_headline_supported": bool(row.regular_headline_supported),
                "continuing_headline_supported": bool(
                    row.continuing_headline_supported
                ),
                "quarter_count": int(row.quarter_count),
            }
            for row in data.itertuples(index=False)
        ],
        "regular_supported_total": int(
            data.loc[data["regular_headline_supported"], "quarter_count"].sum()
        ),
        "continuing_supported_total": int(
            data.loc[data["continuing_headline_supported"], "quarter_count"].sum()
        ),
    }
    return saved, metadata


def chart_deadband_sensitivity(
    deadband_sensitivity: pd.DataFrame,
    mismatch_heatmap: pd.DataFrame,
    path: Path,
    *,
    source_sha256: str = "",
) -> tuple[Path, dict[str, Any]]:
    """Render the no-band baseline and the four relative-change deadbands."""

    _set_style()
    heatmap = _canonical_heatmap(mismatch_heatmap)
    deadband = _with_no_deadband_baseline(
        _canonical_deadband(deadband_sensitivity), heatmap
    )
    footnote = _deadband_footnote()
    fig, ax = plt.subplots(figsize=(10.8, 6.7))
    for tier, color, marker in zip(
        CAPITAL_ORDER,
        (_RED, _TEAL, _SLATE),
        ("o", "s", "^"),
        strict=True,
    ):
        rows = deadband.loc[deadband["capital_tier"].eq(tier)].sort_values(
            "deadband_pct", kind="stable"
        )
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
    ax.set_xticks((0.0, 0.5, 1.0, 2.0, 3.0), ("なし", "±0.5", "±1", "±2", "±3"))
    ax.set_xlabel("deadband d（営業利益率の推定相対変化率・%）")
    ax.set_ylabel("残存期の利益率方向不一致率（%）")
    ax.set_title(DEADBAND_TITLE)
    ax.set_ylim(bottom=0)
    ax.xaxis.grid(True, color=_GRID, linewidth=0.6)
    ax.yaxis.grid(True, color=_GRID, linewidth=0.6)
    ax.legend(frameon=False, fontsize=9)
    plus3 = deadband.loc[np.isclose(deadband["deadband_pct"], 3.0)].set_index(
        "capital_tier"
    )
    d3_lines = [
        f"{CAPITAL_SHORT_LABELS[tier]}："
        f"{int(plus3.loc[tier, 'mismatch_count'])}/"
        f"{int(plus3.loc[tier, 'retained_count'])}"
        for tier in CAPITAL_ORDER
    ]
    ax.text(
        0.98,
        0.04,
        "d=3  " + "／".join(d3_lines),
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=9,
        bbox={"facecolor": "white", "edgecolor": _GRID, "alpha": 0.9},
    )
    fig.text(0.01, 0.012, footnote, fontsize=8.1, color="#56636B")
    fig.tight_layout(rect=(0, 0.10, 1, 0.96))
    saved = _save(
        fig,
        path,
        title=DEADBAND_TITLE,
        footnote=footnote,
        source_sha256=source_sha256,
    )
    small_rows = deadband.loc[deadband["capital_tier"].eq("small")].sort_values(
        "deadband_pct", kind="stable"
    )
    metadata = {
        "small_capital_series": [
            {
                "deadband_percent": float(row.deadband_pct),
                "deadband_label": (
                    "なし"
                    if np.isclose(float(row.deadband_pct), 0.0)
                    else f"±{float(row.deadband_pct):g}%"
                ),
                "numerator": int(row.mismatch_count),
                "denominator": int(row.retained_count),
                "rate_percent": float(row.mismatch_rate_pct),
                "row_origin": str(getattr(row, "row_origin", "SOURCE_CSV")),
            }
            for row in small_rows.itertuples(index=False)
        ],
        "d3_by_capital_tier": [
            {
                "capital_tier": tier,
                "numerator": int(plus3.loc[tier, "mismatch_count"]),
                "denominator": int(plus3.loc[tier, "retained_count"]),
                "rate_percent": float(plus3.loc[tier, "mismatch_rate_pct"]),
            }
            for tier in CAPITAL_ORDER
        ],
        "deadband_definition": (
            "percent of implied relative operating-margin change; not an "
            "absolute operating-margin percentage-point difference"
        ),
    }
    return saved, metadata


def _validate_claim_units_and_values(
    claims_lineage: ClaimsLineageInput,
    heatmap: pd.DataFrame,
) -> None:
    claims = _claims_frame(claims_lineage)
    if claims is None:
        return
    _require_columns(
        claims,
        {"claim_id", "numeric_value", "unit", "display_value"},
        "claims_lineage",
    )
    indexed = claims.set_index("claim_id", drop=False)
    tiers = _tier_summary(heatmap)
    for tier, claim_id in DECISION_MARGIN_CLAIM_IDS.items():
        if claim_id not in indexed.index:
            raise ValueError(f"claims lineage lacks {claim_id}")
        row = indexed.loc[claim_id]
        if isinstance(row, pd.DataFrame):
            raise ValueError(f"claims lineage duplicates {claim_id}")
        if _normalise_unit(row["unit"]) != "percentage_points":
            raise ValueError(f"{claim_id} must use percentage_points")
        expected = float(
            tiers.loc[tier, "continuing_decision_margin_abs_gap_median_pp"]
        )
        if not np.isclose(float(row["numeric_value"]), expected, atol=1e-9, rtol=0):
            raise ValueError(f"{claim_id} does not match mismatch_heatmap.csv")
        display = str(row["display_value"])
        if "%" in display or "％" in display:
            raise ValueError(f"{claim_id} display_value incorrectly uses percent")
        if "ポイント" not in display and "pt" not in display.lower():
            raise ValueError(f"{claim_id} display_value must show points")
    for tier, claim_id in DIVERGENCE_CLAIM_IDS.items():
        if claim_id not in indexed.index:
            raise ValueError(f"claims lineage lacks {claim_id}")
        row = indexed.loc[claim_id]
        if isinstance(row, pd.DataFrame):
            raise ValueError(f"claims lineage duplicates {claim_id}")
        if _normalise_unit(row["unit"]) != "percentage_points":
            raise ValueError(f"{claim_id} must use percentage_points")
        expected = float(
            tiers.loc[tier, "cross_series_growth_gap_divergence_median_pp"]
        )
        if not np.isclose(float(row["numeric_value"]), expected, atol=1e-9, rtol=0):
            raise ValueError(f"{claim_id} does not match mismatch_heatmap.csv")
        display = str(row["display_value"])
        if "%" in display or "％" in display:
            raise ValueError(f"{claim_id} display_value incorrectly uses percent")
        if "ポイント" not in display and "pt" not in display.lower():
            raise ValueError(f"{claim_id} display_value must show points")


def _manifest_entry(
    *,
    chart_id: str,
    filename: str,
    source: _Source,
    referenced_claim_ids: Sequence[str],
    title: str,
    axis_labels: Sequence[str],
    legend_labels: Sequence[str],
    footnote_text: str,
    units: Mapping[str, str],
    png_path: Path,
    structured_metadata: Mapping[str, Any],
    additional_sources: Sequence[_Source] = (),
) -> dict[str, Any]:
    return {
        "chart_id": chart_id,
        "source_csv": source.label,
        "source_csv_sha256": source.sha256,
        "additional_sources": [
            {"source_csv": item.label, "source_csv_sha256": item.sha256}
            for item in additional_sources
        ],
        "referenced_claim_ids": list(referenced_claim_ids),
        "title": title,
        "axis_labels": list(axis_labels),
        "legend_labels": list(legend_labels),
        "footnote_text": footnote_text,
        "units": dict(units),
        "png_path": str(png_path),
        "png_sha256": _sha256_file(png_path),
        "regenerated_in_release": True,
        "release_id": STAGE5_RELEASE_ID,
        "generated_by": "corporate_quarterly.stage5_charts",
        "numeric_source_role": "SOURCE_CSV_NOT_CLAIMS",
        "structured_metadata": dict(structured_metadata),
    }


def build_stage5_charts(
    *,
    mismatch_heatmap: TabularInput,
    headline_2x2: TabularInput,
    deadband_sensitivity: TabularInput,
    unit_registry: RegistryInput,
    claims_lineage: ClaimsLineageInput,
    output_dir: Path,
    source_csv_paths: Mapping[str, str | Path] | None = None,
) -> Stage5ChartBuildResult:
    """Regenerate all three v3.2 charts and return their lineage metadata.

    Each tabular argument may be a CSV path or a DataFrame.  When DataFrames
    are used, callers may supply ``source_csv_paths`` so the manifest records
    and hashes the frozen CSV rather than a canonical in-memory serialisation.
    """

    registry_errors = validate_stage5_unit_registry(unit_registry)
    if registry_errors:
        raise ValueError("; ".join(registry_errors))

    heat_source = _load_tabular_source(
        mismatch_heatmap,
        name=HEATMAP_CHART_ID,
        source_csv_paths=source_csv_paths,
    )
    headline_source = _load_tabular_source(
        headline_2x2,
        name=HEADLINE_CHART_ID,
        source_csv_paths=source_csv_paths,
    )
    deadband_source = _load_tabular_source(
        deadband_sensitivity,
        name=DEADBAND_CHART_ID,
        source_csv_paths=source_csv_paths,
    )
    heat = _canonical_heatmap(heat_source.frame)
    headline = _canonical_2x2(headline_source.frame)
    deadband = _canonical_deadband(deadband_source.frame)
    _validate_claim_units_and_values(claims_lineage, heat)

    claim_ids = {
        chart_id: _claim_ids_for_chart(
            claims_lineage,
            chart_id=chart_id,
            filename=filename,
        )
        for chart_id, filename in zip(
            (HEATMAP_CHART_ID, HEADLINE_CHART_ID, DEADBAND_CHART_ID),
            STAGE5_CHART_FILENAMES,
            strict=True,
        )
    }
    empty_lineage = [chart_id for chart_id, ids in claim_ids.items() if not ids]
    if empty_lineage:
        raise ValueError(f"charts lack claim lineage: {empty_lineage}")

    output_dir = Path(output_dir)
    heat_path, heat_metadata = chart_mismatch_heatmap(
        heat,
        output_dir / STAGE5_CHART_FILENAMES[0],
        source_sha256=heat_source.sha256,
    )
    headline_path, headline_metadata = chart_headline_2x2(
        headline,
        output_dir / STAGE5_CHART_FILENAMES[1],
        source_sha256=headline_source.sha256,
    )
    deadband_path, deadband_metadata = chart_deadband_sensitivity(
        deadband,
        heat,
        output_dir / STAGE5_CHART_FILENAMES[2],
        source_sha256=deadband_source.sha256,
    )

    png_paths: dict[str, Path] = {
        STAGE5_CHART_FILENAMES[0]: heat_path,
        STAGE5_CHART_FILENAMES[1]: headline_path,
        STAGE5_CHART_FILENAMES[2]: deadband_path,
    }
    entries = (
        _manifest_entry(
            chart_id=HEATMAP_CHART_ID,
            filename=STAGE5_CHART_FILENAMES[0],
            source=heat_source,
            referenced_claim_ids=claim_ids[HEATMAP_CHART_ID],
            title=HEATMAP_TITLE,
            axis_labels=("資本金階層", "指標", "方向不一致率（%）"),
            legend_labels=("方向不一致率",),
            footnote_text=_heatmap_footnote(heat),
            units={
                "mismatch_rate_pct": "percent",
                "mismatch_count": "count",
                "comparable_quarters": "count",
                "continuing_decision_margin_abs_gap_median_pp": "percentage_points",
                "cross_series_growth_gap_divergence_median_pp": "percentage_points",
            },
            png_path=heat_path,
            structured_metadata=heat_metadata,
        ),
        _manifest_entry(
            chart_id=HEADLINE_CHART_ID,
            filename=STAGE5_CHART_FILENAMES[1],
            source=headline_source,
            referenced_claim_ids=claim_ids[HEADLINE_CHART_ID],
            title=HEADLINE_TITLE,
            axis_labels=("通常系列", "継続標本系列"),
            legend_labels=("成立", "不成立"),
            footnote_text=_headline_footnote(headline),
            units={"quarter_count": "count"},
            png_path=headline_path,
            structured_metadata=headline_metadata,
        ),
        _manifest_entry(
            chart_id=DEADBAND_CHART_ID,
            filename=STAGE5_CHART_FILENAMES[2],
            source=deadband_source,
            additional_sources=(heat_source,),
            referenced_claim_ids=claim_ids[DEADBAND_CHART_ID],
            title=DEADBAND_TITLE,
            axis_labels=(
                "deadband d（営業利益率の推定相対変化率・%）",
                "残存期の利益率方向不一致率（%）",
            ),
            legend_labels=tuple(
                CAPITAL_LABELS[tier].replace("\n", "") for tier in CAPITAL_ORDER
            ),
            footnote_text=_deadband_footnote(),
            units={
                "deadband_pct": "percent",
                "mismatch_rate_pct": "percent",
                "mismatch_count": "count",
                "retained_quarters": "count",
                "implied_relative_margin_change": "percent",
            },
            png_path=deadband_path,
            structured_metadata=deadband_metadata,
        ),
    )
    result = Stage5ChartBuildResult(png_paths=png_paths, manifest_entries=entries)
    manifest_errors = validate_stage5_chart_manifest(
        result.manifest_entries,
        unit_registry=unit_registry,
        claims_lineage=claims_lineage,
    )
    if manifest_errors:
        raise ValueError("chart manifest validation failed: " + "; ".join(manifest_errors))
    return result


def chart_manifest_payload(
    result: Stage5ChartBuildResult | Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Wrap chart entries in the release-level JSON structure."""

    entries = (
        result.manifest_entries
        if isinstance(result, Stage5ChartBuildResult)
        else tuple(dict(entry) for entry in result)
    )
    return {
        "release_id": STAGE5_RELEASE_ID,
        "chart_count": len(entries),
        "charts": list(entries),
    }


def _manifest_entries(
    manifest: Mapping[str, Any] | Sequence[Mapping[str, Any]] | str | Path,
) -> list[Mapping[str, Any]]:
    if isinstance(manifest, (str, Path)):
        payload = json.loads(Path(manifest).read_text(encoding="utf-8"))
    else:
        payload = manifest
    if isinstance(payload, Mapping):
        entries = payload.get("charts")
    else:
        entries = payload
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        raise ValueError("chart manifest must contain a charts array")
    return [entry for entry in entries if isinstance(entry, Mapping)]


def _resolve_manifest_path(value: Any, base_dir: Path | None) -> Path:
    path = Path(str(value))
    if path.is_absolute() or base_dir is None:
        return path
    return base_dir / path


def validate_stage5_chart_manifest(
    manifest: Mapping[str, Any] | Sequence[Mapping[str, Any]] | str | Path,
    *,
    unit_registry: RegistryInput,
    claims_lineage: ClaimsLineageInput | None = None,
    base_dir: Path | None = None,
) -> tuple[str, ...]:
    """Audit chart lineage, units, structured values, and current file hashes."""

    errors = list(validate_stage5_unit_registry(unit_registry))
    try:
        entries = _manifest_entries(manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return tuple(errors + [f"chart_manifest:unreadable:{exc}"])
    if len(entries) != 3:
        errors.append(f"chart_manifest:expected_3_entries:observed_{len(entries)}")
    by_id = {str(entry.get("chart_id")): entry for entry in entries}
    expected_ids = {HEATMAP_CHART_ID, HEADLINE_CHART_ID, DEADBAND_CHART_ID}
    if set(by_id) != expected_ids:
        errors.append(f"chart_manifest:chart_ids:{sorted(by_id)}")

    required_fields = {
        "chart_id",
        "source_csv",
        "source_csv_sha256",
        "referenced_claim_ids",
        "title",
        "axis_labels",
        "legend_labels",
        "footnote_text",
        "units",
        "png_path",
        "png_sha256",
        "regenerated_in_release",
        "structured_metadata",
    }
    available_claims: set[str] | None = None
    if claims_lineage is not None:
        claims = _claims_frame(claims_lineage)
        if claims is not None and "claim_id" in claims:
            available_claims = set(claims["claim_id"].dropna().astype(str))

    resolved_sources: dict[str, Path] = {}
    for chart_id, entry in by_id.items():
        missing = required_fields - set(entry)
        if missing:
            errors.append(f"{chart_id}:missing_fields:{sorted(missing)}")
            continue
        if entry.get("regenerated_in_release") is not True:
            errors.append(f"{chart_id}:regenerated_in_release_not_true")
        if entry.get("numeric_source_role") != "SOURCE_CSV_NOT_CLAIMS":
            errors.append(f"{chart_id}:numeric_source_role")
        referenced = entry.get("referenced_claim_ids")
        if not isinstance(referenced, list) or not referenced:
            errors.append(f"{chart_id}:empty_referenced_claim_ids")
        elif available_claims is not None:
            unknown = set(map(str, referenced)) - available_claims
            if unknown:
                errors.append(f"{chart_id}:unknown_claim_ids:{sorted(unknown)}")
            filenames = {
                HEATMAP_CHART_ID: STAGE5_CHART_FILENAMES[0],
                HEADLINE_CHART_ID: STAGE5_CHART_FILENAMES[1],
                DEADBAND_CHART_ID: STAGE5_CHART_FILENAMES[2],
            }
            expected_lineage = _claim_ids_for_chart(
                claims_lineage,
                chart_id=chart_id,
                filename=filenames[chart_id],
            )
            if sorted(map(str, referenced)) != expected_lineage:
                errors.append(f"{chart_id}:claim_lineage_mismatch")

        source_value = entry.get("source_csv")
        if not str(source_value).startswith("dataframe://"):
            source_path = _resolve_manifest_path(source_value, base_dir)
            if not source_path.is_file():
                errors.append(f"{chart_id}:source_csv_missing")
            else:
                resolved_sources[chart_id] = source_path
                if _sha256_file(source_path) != entry.get("source_csv_sha256"):
                    errors.append(f"{chart_id}:source_csv_sha256_mismatch")
        additional_sources = entry.get("additional_sources", [])
        if not isinstance(additional_sources, list):
            errors.append(f"{chart_id}:additional_sources_not_array")
        else:
            for position, item in enumerate(additional_sources):
                if not isinstance(item, Mapping):
                    errors.append(f"{chart_id}:additional_source_{position}:not_object")
                    continue
                value = item.get("source_csv")
                if str(value).startswith("dataframe://"):
                    continue
                extra_path = _resolve_manifest_path(value, base_dir)
                if not extra_path.is_file():
                    errors.append(f"{chart_id}:additional_source_{position}:missing")
                elif _sha256_file(extra_path) != item.get("source_csv_sha256"):
                    errors.append(
                        f"{chart_id}:additional_source_{position}:sha256_mismatch"
                    )
        png_path = _resolve_manifest_path(entry.get("png_path"), base_dir)
        if not png_path.is_file():
            errors.append(f"{chart_id}:png_missing")
        else:
            if not png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
                errors.append(f"{chart_id}:png_signature")
            if _sha256_file(png_path) != entry.get("png_sha256"):
                errors.append(f"{chart_id}:png_sha256_mismatch")

        units = entry.get("units")
        if not isinstance(units, Mapping):
            errors.append(f"{chart_id}:units_not_object")
            continue
        for column, unit in units.items():
            normalised = _normalise_unit(unit)
            if str(column).endswith("_pp") and normalised != "percentage_points":
                errors.append(f"{chart_id}:{column}:must_be_percentage_points")
            if str(column).endswith("_pct") and normalised != "percent":
                errors.append(f"{chart_id}:{column}:must_be_percent")

    heat = by_id.get(HEATMAP_CHART_ID)
    if heat is not None:
        if heat.get("title") != HEATMAP_TITLE:
            errors.append("mismatch_heatmap:title")
        old_title = "2016年1～3月期以降：判定の不一致は" + "小規模資本金層に集中"
        serialised = json.dumps(heat, ensure_ascii=False)
        if old_title in serialised:
            errors.append("mismatch_heatmap:old_title_present")
        for bad in ("11.3％／9.0％／8.5％", "11.3%／9.0%／8.5%"):
            if bad in serialised:
                errors.append("mismatch_heatmap:decision_margin_percent_display")
        units = heat.get("units", {})
        if units.get("continuing_decision_margin_abs_gap_median_pp") != "percentage_points":
            errors.append("mismatch_heatmap:decision_margin_unit")
        if units.get("cross_series_growth_gap_divergence_median_pp") != "percentage_points":
            errors.append("mismatch_heatmap:divergence_unit")
        structured = heat.get("structured_metadata", {})
        margin_rows = structured.get("decision_margin_medians", [])
        divergence_rows = structured.get("cross_series_divergence_medians", [])
        margin_values = {row.get("capital_tier"): row.get("value") for row in margin_rows}
        divergence_values = {
            row.get("capital_tier"): row.get("value") for row in divergence_rows
        }
        expected_margin = {"small": 11.3, "middle": 9.0, "large": 8.5}
        expected_divergence = {"small": 11.21, "middle": 4.07, "large": 1.05}
        for tier, expected in expected_margin.items():
            if tier not in margin_values or not np.isclose(
                float(margin_values[tier]), expected, atol=0.051, rtol=0
            ):
                errors.append(f"mismatch_heatmap:decision_margin:{tier}")
        for tier, expected in expected_divergence.items():
            if tier not in divergence_values or not np.isclose(
                float(divergence_values[tier]), expected, atol=0.0051, rtol=0
            ):
                errors.append(f"mismatch_heatmap:divergence:{tier}")
        if HEATMAP_CHART_ID in resolved_sources:
            try:
                source_heat = _canonical_heatmap(
                    pd.read_csv(resolved_sources[HEATMAP_CHART_ID])
                )
                expected_cells = {
                    (row.capital_tier, row.metric_id): (
                        int(row.mismatch_count),
                        int(row.comparable_count),
                        float(row.mismatch_rate_pct),
                    )
                    for row in source_heat.itertuples(index=False)
                }
                manifest_cells = {
                    (row.get("capital_tier"), row.get("metric_id")): (
                        int(row.get("numerator")),
                        int(row.get("denominator")),
                        float(row.get("rate_percent")),
                    )
                    for row in structured.get("cells", [])
                }
                if set(expected_cells) != set(manifest_cells):
                    errors.append("mismatch_heatmap:source_cell_keys")
                else:
                    for key, expected in expected_cells.items():
                        observed = manifest_cells[key]
                        if expected[:2] != observed[:2] or not np.isclose(
                            expected[2], observed[2], atol=1e-12, rtol=0
                        ):
                            errors.append(f"mismatch_heatmap:source_cell:{key}")
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"mismatch_heatmap:source_parse:{exc}")

    headline = by_id.get(HEADLINE_CHART_ID)
    if headline is not None:
        cells = headline.get("structured_metadata", {}).get("cells", [])
        observed = {row.get("cell_id"): row.get("quarter_count") for row in cells}
        expected = {
            "REGULAR_ONLY": 9,
            "CONTINUING_ONLY": 2,
            "BOTH": 1,
            "NEITHER": 29,
        }
        if observed != expected:
            errors.append(f"headline_2x2:cells:{observed}")
        if HEADLINE_CHART_ID in resolved_sources:
            try:
                source_headline = _canonical_2x2(
                    pd.read_csv(resolved_sources[HEADLINE_CHART_ID])
                )
                source_cells = {
                    str(row.cell_id): int(row.quarter_count)
                    for row in source_headline.itertuples(index=False)
                }
                if observed != source_cells:
                    errors.append("headline_2x2:source_cell_mismatch")
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"headline_2x2:source_parse:{exc}")

    deadband = by_id.get(DEADBAND_CHART_ID)
    if deadband is not None:
        units = deadband.get("units", {})
        if units.get("deadband_pct") != "percent":
            errors.append("deadband_sensitivity:threshold_unit")
        if units.get("implied_relative_margin_change") != "percent":
            errors.append("deadband_sensitivity:relative_change_unit")
        structured = deadband.get("structured_metadata", {})
        small = structured.get("small_capital_series", [])
        observed_small = {
            float(row.get("deadband_percent")): (
                int(row.get("numerator")),
                int(row.get("denominator")),
            )
            for row in small
        }
        expected_small = {
            0.0: (16, 41),
            0.5: (15, 39),
            1.0: (14, 37),
            2.0: (10, 33),
            3.0: (8, 29),
        }
        if observed_small != expected_small:
            errors.append(f"deadband_sensitivity:small_series:{observed_small}")
        d3 = structured.get("d3_by_capital_tier", [])
        observed_d3 = {
            row.get("capital_tier"): (
                int(row.get("numerator")),
                int(row.get("denominator")),
            )
            for row in d3
        }
        if observed_d3.get("middle") != (0, 29):
            errors.append("deadband_sensitivity:d3_middle")
        if observed_d3.get("large") != (0, 33):
            errors.append("deadband_sensitivity:d3_large")
        if (
            DEADBAND_CHART_ID in resolved_sources
            and HEATMAP_CHART_ID in resolved_sources
        ):
            try:
                source_deadband = _canonical_deadband(
                    pd.read_csv(resolved_sources[DEADBAND_CHART_ID])
                )
                source_heat = _canonical_heatmap(
                    pd.read_csv(resolved_sources[HEATMAP_CHART_ID])
                )
                source_deadband = _with_no_deadband_baseline(
                    source_deadband, source_heat
                )
                source_small = source_deadband.loc[
                    source_deadband["capital_tier"].eq("small")
                ]
                expected_source_small = {
                    float(row.deadband_pct): (
                        int(row.mismatch_count),
                        int(row.retained_count),
                    )
                    for row in source_small.itertuples(index=False)
                }
                if observed_small != expected_source_small:
                    errors.append("deadband_sensitivity:source_small_series")
                source_d3 = source_deadband.loc[
                    np.isclose(source_deadband["deadband_pct"], 3.0)
                ]
                expected_source_d3 = {
                    row.capital_tier: (
                        int(row.mismatch_count),
                        int(row.retained_count),
                    )
                    for row in source_d3.itertuples(index=False)
                }
                if observed_d3 != expected_source_d3:
                    errors.append("deadband_sensitivity:source_d3")
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"deadband_sensitivity:source_parse:{exc}")

    return tuple(dict.fromkeys(errors))


def assert_valid_stage5_chart_manifest(
    manifest: Mapping[str, Any] | Sequence[Mapping[str, Any]] | str | Path,
    *,
    unit_registry: RegistryInput,
    claims_lineage: ClaimsLineageInput | None = None,
    base_dir: Path | None = None,
) -> None:
    """Raise when :func:`validate_stage5_chart_manifest` reports any error."""

    errors = validate_stage5_chart_manifest(
        manifest,
        unit_registry=unit_registry,
        claims_lineage=claims_lineage,
        base_dir=base_dir,
    )
    if errors:
        raise ValueError("; ".join(errors))


# Descriptive alias used by release-level audit code.
validate_chart_manifest_v3_2 = validate_stage5_chart_manifest
