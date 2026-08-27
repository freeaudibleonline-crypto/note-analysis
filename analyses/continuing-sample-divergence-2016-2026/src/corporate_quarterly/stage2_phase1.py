"""Pure Phase 0/1 calculations for the second-stage 2026Q1 analysis.

This module deliberately has no file-writing side effects.  The caller supplies
the existing ``processed_quarterly`` frame and decides where (or whether) to
publish the returned tables.  Missing inputs propagate as null values with an
explicit status; they are never converted to zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
import json
import math
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

import numpy as np
import pandas as pd

from .constants import MAJOR_INDUSTRY_NAMES, PROJECT_ROOT


STAGE2_CONFIG_PATH = PROJECT_ROOT / "config" / "stage2_2026Q1.json"
TaxonomyName = Literal["major", "leaf"]

ALL_INDUSTRY_CODE = "104"
MANUFACTURING_CODE = "108"
ICT_MACHINERY_CODE = "145"
ALL_CAPITAL_CODE = "26"
CAPITAL_CODES = ("19", "24", "25")
CAPITAL_NAMES = {
    "19": "1千万円以上 - 1億円未満",
    "24": "1億円以上 - 10億円未満",
    "25": "10億円以上",
    "26": "全規模",
}
ANALYSIS_METRICS = ("sales", "operating_profit", "ordinary_profit")
ADDITIVITY_METRICS = (
    "sales",
    "operating_profit",
    "ordinary_profit",
    "capex_including_software",
    "capex_excluding_software",
)


class Stage2InputError(ValueError):
    """The supplied processed frame violates a Phase 1 input contract."""


class Phase0ReproductionError(Stage2InputError):
    """At least one frozen Phase 0 target failed its tolerance gate."""

    def __init__(self, checks: pd.DataFrame):
        self.checks = checks.copy()
        failures = checks.loc[checks["status"].ne("PASS"), "check_id"].tolist()
        super().__init__(f"Phase 0 reproduction failed: {', '.join(failures)}")


@dataclass(frozen=True)
class Phase0Target:
    check_id: str
    expected: float
    unit: str
    tolerance_kind: str
    locator: str


@dataclass(frozen=True)
class Phase1Analysis:
    phase0_checks: pd.DataFrame
    major_taxonomy_contributions: pd.DataFrame
    leaf_taxonomy_contributions: pd.DataFrame
    major_industry_x_capital: pd.DataFrame
    leaf_industry_x_capital: pd.DataFrame
    cell_margin_bridge: pd.DataFrame
    capital_margin_bridge: pd.DataFrame
    ordinary_operating_gap: pd.DataFrame
    software_capex_decomposition: pd.DataFrame
    additivity_checks: pd.DataFrame


def load_stage2_config(path: Path | None = None) -> dict[str, Any]:
    """Load and minimally validate the executable Stage 2 configuration."""
    config_path = Path(path or STAGE2_CONFIG_PATH)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("CONFIG_KIND") != "EXECUTABLE_STAGE2_CONFIGURATION":
        raise Stage2InputError(f"Not an executable Stage 2 config: {config_path}")
    required_tolerances = {
        "amount_oku_yen",
        "percentage_point",
        "margin_percentage_point",
    }
    if required_tolerances - set(config.get("phase0_tolerances", {})):
        raise Stage2InputError("Stage 2 config is missing Phase 0 tolerances")
    if not config.get("taxonomy_policy", {}).get("leaf_industry_codes"):
        raise Stage2InputError("Stage 2 config is missing leaf_industry_codes")
    return config


# Parent aggregates are not inferred from row order: the e-Stat dimension lacks a
# usable parentCode.  This explicit map is therefore part of the auditable
# classification policy.  Leaf membership/order itself remains config-owned.
_INDUSTRY_NAME_BY_CODE = {
    "101": "農業、林業",
    "103": "漁業",
    "105": "農林水産業(集約)",
    "106": "鉱業、採石業、砂利採取業",
    "107": "建設業",
    "108": "製造業",
    "109": "食料品製造業",
    "110": "繊維工業",
    "112": "木材・木製品製造業",
    "113": "パルプ・紙・紙加工品製造業",
    "114": "印刷・同関連業",
    "115": "化学工業",
    "116": "石油製品・石炭製品製造業",
    "117": "窯業・土石製品製造業",
    "118": "鉄鋼業",
    "119": "非鉄金属製造業",
    "120": "金属製品製造業",
    "121": "生産用機械器具製造業",
    "122": "電気機械器具製造業",
    "123": "自動車・同附属品製造業",
    "124": "業務用機械器具製造業",
    "125": "その他の輸送用機械器具製造業",
    "126": "その他の製造業",
    "127": "卸売業",
    "128": "小売業",
    "129": "卸売業・小売業(集約)",
    "130": "不動産業",
    "131": "陸運業",
    "132": "水運業",
    "133": "その他の運輸業",
    "134": "運輸業、郵便業(集約)",
    "135": "電気業",
    "136": "ガス・熱供給・水道業",
    "137": "サービス業(集約)",
    "138": "広告業",
    "139": "宿泊業",
    "140": "生活関連サービス業",
    "141": "娯楽業",
    "142": "情報通信業",
    "143": "その他のサービス業",
    "145": "情報通信機械器具製造業",
    "150": "リース業",
    "151": "その他の物品賃貸業",
    "152": "医療、福祉業",
    "153": "教育、学習支援業",
    "154": "はん用機械器具製造業",
    "155": "不動産業、物品賃貸業(集約)",
    "158": "純粋持株会社",
    "159": "その他の学術研究、専門・技術サービス業",
    "160": "職業紹介・労働者派遣業",
}

_MAJOR_CODE_ORDER = ("108", "105", "106", "107", "135", "136", "142", "134", "129", "155", "137")
_LEAF_PARENT_CODE = {
    **{code: "108" for code in ("109", "110", "112", "113", "114", "115", "116", "117", "118", "119", "120", "154", "121", "124", "122", "145", "123", "125", "126")},
    **{code: "105" for code in ("101", "103")},
    "106": "106",
    "107": "107",
    "135": "135",
    "136": "136",
    "142": "142",
    **{code: "134" for code in ("131", "132", "133")},
    **{code: "129" for code in ("127", "128")},
    **{code: "155" for code in ("130", "150", "151")},
    **{code: "137" for code in ("139", "148", "140", "141", "138", "158", "159", "153", "152", "160", "143")},
}
# Codes only needed for names; keeping them separate from membership makes it
# impossible for an aggregate to enter the leaf ranking accidentally.
_INDUSTRY_NAME_BY_CODE.update(
    {
        "148": "飲食サービス業",
    }
)


def taxonomy_definition(
    taxonomy: TaxonomyName, *, config: Mapping[str, Any] | None = None
) -> pd.DataFrame:
    """Return a closed, mutually exclusive taxonomy definition."""
    cfg = dict(config or load_stage2_config())
    if taxonomy == "major":
        codes = list(_MAJOR_CODE_ORDER)
        parents = {code: code for code in codes}
    elif taxonomy == "leaf":
        codes = [str(code) for code in cfg["taxonomy_policy"]["leaf_industry_codes"]]
        parents = _LEAF_PARENT_CODE
        if set(codes) != set(parents):
            raise Stage2InputError(
                "Configured leaf codes and the explicit parent map differ: "
                f"config_only={sorted(set(codes) - set(parents))}, "
                f"map_only={sorted(set(parents) - set(codes))}"
            )
        excluded = {
            str(code)
            for code in cfg["taxonomy_policy"].get(
                "excluded_overlapping_or_legacy_codes", []
            )
        }
        overlap = set(codes) & excluded
        if overlap:
            raise Stage2InputError(f"Leaf taxonomy includes excluded codes: {sorted(overlap)}")
    else:
        raise ValueError(f"Unknown taxonomy: {taxonomy!r}")
    rows = []
    for order, code in enumerate(codes, start=1):
        if code not in _INDUSTRY_NAME_BY_CODE:
            raise Stage2InputError(f"No auditable industry name for code {code}")
        parent = parents[code]
        rows.append(
            {
                "taxonomy": taxonomy,
                "taxonomy_order": order,
                "industry_code": code,
                "industry_name": _INDUSTRY_NAME_BY_CODE[code],
                "parent_major_code": parent,
                "parent_major_name": _INDUSTRY_NAME_BY_CODE[parent],
                "is_parent_aggregate": taxonomy == "major",
                "is_mutually_exclusive": True,
            }
        )
    frame = pd.DataFrame(rows)
    if frame["industry_code"].duplicated().any():
        raise Stage2InputError(f"Duplicate codes in {taxonomy} taxonomy")
    if taxonomy == "major" and tuple(frame["industry_name"]) != MAJOR_INDUSTRY_NAMES:
        raise Stage2InputError("Major taxonomy has drifted from constants.MAJOR_INDUSTRY_NAMES")
    return frame


PHASE0_TARGETS = (
    Phase0Target("all_operating_profit_yoy_delta", 25_970.25, "億円", "amount_oku_yen", "industry=104;capital=26;metric=operating_profit"),
    Phase0Target("all_ordinary_profit_yoy_delta", 41_576.87, "億円", "amount_oku_yen", "industry=104;capital=26;metric=ordinary_profit"),
    Phase0Target("all_gap_yoy_delta", 15_606.62, "億円", "amount_oku_yen", "ordinary_profit delta - operating_profit delta"),
    Phase0Target("all_gap_share_of_ordinary_delta_pct", 37.54, "%", "percentage_point", "all_gap_yoy_delta / all_ordinary_profit_yoy_delta"),
    Phase0Target("capital_25_ordinary_delta", 34_231.10, "億円", "amount_oku_yen", "industry=104;capital=25;metric=ordinary_profit"),
    Phase0Target("capital_25_ordinary_contribution_pct", 82.332, "%", "percentage_point", "capital_25 ordinary delta / all ordinary delta"),
    Phase0Target("capital_24_ordinary_delta", 5_942.97, "億円", "amount_oku_yen", "industry=104;capital=24;metric=ordinary_profit"),
    Phase0Target("capital_24_ordinary_contribution_pct", 14.294, "%", "percentage_point", "capital_24 ordinary delta / all ordinary delta"),
    Phase0Target("capital_19_ordinary_delta", 1_402.80, "億円", "amount_oku_yen", "industry=104;capital=19;metric=ordinary_profit"),
    Phase0Target("capital_19_ordinary_contribution_pct", 3.374, "%", "percentage_point", "capital_19 ordinary delta / all ordinary delta"),
    Phase0Target("manufacturing_ordinary_delta", 38_783.33, "億円", "amount_oku_yen", "industry=108;capital=26;metric=ordinary_profit"),
    Phase0Target("manufacturing_ordinary_contribution_pct", 93.281, "%", "percentage_point", "manufacturing ordinary delta / all ordinary delta"),
    Phase0Target("large_manufacturing_ordinary_delta", 29_960.18, "億円", "amount_oku_yen", "industry=108;capital=25;metric=ordinary_profit"),
    Phase0Target("large_manufacturing_ordinary_contribution_pct", 72.060, "%", "percentage_point", "large manufacturing ordinary delta / all ordinary delta"),
    Phase0Target("small_manufacturing_ordinary_delta", 6_225.36, "億円", "amount_oku_yen", "industry=108;capital=19;metric=ordinary_profit"),
    Phase0Target("small_manufacturing_ordinary_contribution_pct", 14.973, "%", "percentage_point", "small manufacturing ordinary delta / all ordinary delta"),
    Phase0Target("ict_machinery_operating_delta", 11_801.41, "億円", "amount_oku_yen", "industry=145;capital=26;metric=operating_profit"),
    Phase0Target("ict_machinery_ordinary_delta", 15_853.14, "億円", "amount_oku_yen", "industry=145;capital=26;metric=ordinary_profit"),
    Phase0Target("ict_machinery_gap_delta", 4_051.73, "億円", "amount_oku_yen", "ICT ordinary delta - operating delta"),
    Phase0Target("ict_machinery_ordinary_contribution_pct", 38.13, "%", "percentage_point", "ICT ordinary delta / all ordinary delta"),
    Phase0Target("ict_machinery_gap_share_pct", 25.56, "%", "percentage_point", "ICT gap delta / ICT ordinary delta"),
    Phase0Target("capital_25_sales_yoy_pct", 1.6958, "%", "percentage_point", "industry=104;capital=25;metric=sales"),
    Phase0Target("capital_25_operating_yoy_pct", 18.4947, "%", "percentage_point", "industry=104;capital=25;metric=operating_profit"),
    Phase0Target("capital_25_operating_margin_delta_pp", 1.070, "ポイント", "margin_percentage_point", "capital=25 current operating margin - prior margin"),
    Phase0Target("capital_19_sales_yoy_pct", 2.1009, "%", "percentage_point", "industry=104;capital=19;metric=sales"),
    Phase0Target("capital_19_operating_yoy_pct", -1.8902, "%", "percentage_point", "industry=104;capital=19;metric=operating_profit"),
    Phase0Target("capital_19_operating_margin_delta_pp", -0.228, "ポイント", "margin_percentage_point", "capital=19 current operating margin - prior margin"),
    Phase0Target("software_all_delta", 2_431.42, "億円", "amount_oku_yen", "all capex including delta - excluding delta"),
    Phase0Target("software_capital_19_delta", 1_784.11, "億円", "amount_oku_yen", "capital=19 capex including delta - excluding delta"),
    Phase0Target("software_capital_19_contribution_pct", 73.377, "%", "percentage_point", "small-capital software delta / all software delta"),
    Phase0Target("capex_excluding_all_delta", -2_342.64, "億円", "amount_oku_yen", "industry=104;capital=26;metric=capex_excluding_software"),
    Phase0Target("capex_including_all_delta", 88.78, "億円", "amount_oku_yen", "industry=104;capital=26;metric=capex_including_software"),
)


def _source_base(processed: pd.DataFrame) -> pd.DataFrame:
    required = {
        "coverage_scope",
        "source_table_number",
        "industry_code",
        "capital_size_code",
        "metric_id",
        "raw_value_oku_yen",
        "raw_lag4_value_oku_yen",
    }
    missing = required - set(processed.columns)
    if missing:
        raise Stage2InputError(f"Processed frame lacks columns: {sorted(missing)}")
    return processed.loc[
        processed["coverage_scope"].eq("EXCL_FINANCE_INSURANCE")
        & processed["source_table_number"].astype(str).eq("1")
        & processed["metric_id"].isin(
            (*ADDITIVITY_METRICS, "interest_expense", "employee_count")
        )
    ].copy()


def _source_row(
    base: pd.DataFrame, industry_code: str, capital_code: str, metric_id: str
) -> pd.Series:
    subset = base.loc[
        base["industry_code"].astype(str).eq(str(industry_code))
        & base["capital_size_code"].astype(str).eq(str(capital_code))
        & base["metric_id"].eq(metric_id)
    ]
    if len(subset) != 1:
        raise Stage2InputError(
            f"Expected one source row for industry={industry_code}, capital={capital_code}, "
            f"metric={metric_id}; found {len(subset)}"
        )
    return subset.iloc[0]


def _dataset_metadata(base: pd.DataFrame) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "coverage_scope": "EXCL_FINANCE_INSURANCE",
        "source_table_number": "1",
    }
    for column in ("release_id", "period_code", "period", "period_end", "estat_sid"):
        if column not in base.columns:
            continue
        values = base[column].dropna().astype(str).unique().tolist()
        if len(values) != 1:
            raise Stage2InputError(
                f"Expected one {column} in source analysis rows; found {values}"
            )
        metadata[column] = values[0]
    return metadata


def _number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _observation(base: pd.DataFrame, industry: str, capital: str, metric: str) -> dict[str, float | None]:
    row = _source_row(base, industry, capital, metric)
    current = _number(row["raw_value_oku_yen"])
    previous = _number(row["raw_lag4_value_oku_yen"])
    delta = None if current is None or previous is None else current - previous
    return {"current": current, "previous": previous, "delta": delta}


def _safe_ratio(numerator: float | None, denominator: float | None) -> tuple[float | None, str]:
    if numerator is None or denominator is None:
        return None, "MISSING_INPUT"
    if denominator == 0:
        return None, "ZERO_DENOMINATOR_NOT_CALCULABLE"
    return numerator / denominator * 100.0, "CALCULABLE"


def _safe_yoy(metric_id: str, current: float | None, previous: float | None) -> tuple[float | None, str]:
    if current is None or previous is None:
        return None, "MISSING_INPUT"
    if previous == 0:
        return None, "ZERO_BASE_NOT_CALCULABLE"
    if metric_id in {"operating_profit", "ordinary_profit"} and previous < 0:
        return None, "NEGATIVE_PROFIT_BASE_NOT_CALCULABLE"
    return (current / previous - 1.0) * 100.0, "CALCULABLE"


def _margin(
    profit: float | None, sales: float | None
) -> tuple[float | None, str]:
    if profit is None or sales is None:
        return None, "MISSING_INPUT"
    if sales <= 0:
        return None, "NON_POSITIVE_SALES_NOT_CALCULABLE"
    return profit / sales * 100.0, "CALCULABLE"


def _strict_sum(values: Iterable[object]) -> float | None:
    numbers = [_number(value) for value in values]
    if not numbers or any(value is None for value in numbers):
        return None
    return float(sum(value for value in numbers if value is not None))


def _availability_status(value: float | None) -> str:
    return "CALCULABLE" if value is not None else "MISSING_INPUT"


def _phase0_actuals(processed: pd.DataFrame) -> dict[str, tuple[float | None, str]]:
    base = _source_base(processed)
    actual: dict[str, tuple[float | None, str]] = {}
    all_op = _observation(base, "104", "26", "operating_profit")
    all_ord = _observation(base, "104", "26", "ordinary_profit")
    actual["all_operating_profit_yoy_delta"] = (
        all_op["delta"],
        _availability_status(all_op["delta"]),
    )
    actual["all_ordinary_profit_yoy_delta"] = (
        all_ord["delta"],
        _availability_status(all_ord["delta"]),
    )
    all_gap_delta = (
        None
        if all_op["delta"] is None or all_ord["delta"] is None
        else all_ord["delta"] - all_op["delta"]
    )
    actual["all_gap_yoy_delta"] = (all_gap_delta, "CALCULABLE" if all_gap_delta is not None else "MISSING_INPUT")
    actual["all_gap_share_of_ordinary_delta_pct"] = _safe_ratio(all_gap_delta, all_ord["delta"])

    for capital in ("25", "24", "19"):
        ordinary = _observation(base, "104", capital, "ordinary_profit")
        actual[f"capital_{capital}_ordinary_delta"] = (
            ordinary["delta"],
            "CALCULABLE" if ordinary["delta"] is not None else "MISSING_INPUT",
        )
        actual[f"capital_{capital}_ordinary_contribution_pct"] = _safe_ratio(
            ordinary["delta"], all_ord["delta"]
        )

    for label, capital in (("manufacturing", "26"), ("large_manufacturing", "25"), ("small_manufacturing", "19")):
        ordinary = _observation(base, "108", capital, "ordinary_profit")
        actual[f"{label}_ordinary_delta"] = (
            ordinary["delta"],
            "CALCULABLE" if ordinary["delta"] is not None else "MISSING_INPUT",
        )
        actual[f"{label}_ordinary_contribution_pct"] = _safe_ratio(
            ordinary["delta"], all_ord["delta"]
        )

    ict_op = _observation(base, "145", "26", "operating_profit")
    ict_ord = _observation(base, "145", "26", "ordinary_profit")
    ict_gap = (
        None
        if ict_op["delta"] is None or ict_ord["delta"] is None
        else ict_ord["delta"] - ict_op["delta"]
    )
    actual["ict_machinery_operating_delta"] = (
        ict_op["delta"],
        _availability_status(ict_op["delta"]),
    )
    actual["ict_machinery_ordinary_delta"] = (
        ict_ord["delta"],
        _availability_status(ict_ord["delta"]),
    )
    actual["ict_machinery_gap_delta"] = (ict_gap, "CALCULABLE" if ict_gap is not None else "MISSING_INPUT")
    actual["ict_machinery_ordinary_contribution_pct"] = _safe_ratio(
        ict_ord["delta"], all_ord["delta"]
    )
    actual["ict_machinery_gap_share_pct"] = _safe_ratio(ict_gap, ict_ord["delta"])

    for capital in ("25", "19"):
        sales = _observation(base, "104", capital, "sales")
        operating = _observation(base, "104", capital, "operating_profit")
        actual[f"capital_{capital}_sales_yoy_pct"] = _safe_yoy(
            "sales", sales["current"], sales["previous"]
        )
        actual[f"capital_{capital}_operating_yoy_pct"] = _safe_yoy(
            "operating_profit", operating["current"], operating["previous"]
        )
        current_margin, current_status = _margin(operating["current"], sales["current"])
        prior_margin, prior_status = _margin(operating["previous"], sales["previous"])
        if current_status == prior_status == "CALCULABLE":
            actual[f"capital_{capital}_operating_margin_delta_pp"] = (
                current_margin - prior_margin,  # type: ignore[operator]
                "CALCULABLE",
            )
        else:
            actual[f"capital_{capital}_operating_margin_delta_pp"] = (
                None,
                current_status if current_status != "CALCULABLE" else prior_status,
            )

    def software(capital: str) -> dict[str, float | None]:
        including = _observation(base, "104", capital, "capex_including_software")
        excluding = _observation(base, "104", capital, "capex_excluding_software")
        return {
            key: None
            if including[key] is None or excluding[key] is None
            else including[key] - excluding[key]  # type: ignore[operator]
            for key in ("current", "previous", "delta")
        }

    software_all = software("26")
    software_small = software("19")
    actual["software_all_delta"] = (
        software_all["delta"],
        _availability_status(software_all["delta"]),
    )
    actual["software_capital_19_delta"] = (
        software_small["delta"],
        _availability_status(software_small["delta"]),
    )
    actual["software_capital_19_contribution_pct"] = _safe_ratio(
        software_small["delta"], software_all["delta"]
    )
    for metric, key in (
        ("capex_excluding_software", "capex_excluding_all_delta"),
        ("capex_including_software", "capex_including_all_delta"),
    ):
        delta = _observation(base, "104", "26", metric)["delta"]
        actual[key] = (delta, "CALCULABLE" if delta is not None else "MISSING_INPUT")
    return actual


def reproduce_phase0(
    processed: pd.DataFrame,
    *,
    config: Mapping[str, Any] | None = None,
    targets: Sequence[Phase0Target] = PHASE0_TARGETS,
) -> pd.DataFrame:
    """Recalculate every frozen Phase 0 target and apply its configured tolerance."""
    cfg = dict(config or load_stage2_config())
    tolerances = cfg["phase0_tolerances"]
    actuals = _phase0_actuals(processed)
    rows = []
    for target in targets:
        actual, calculation_status = actuals.get(target.check_id, (None, "TARGET_NOT_IMPLEMENTED"))
        tolerance = float(tolerances[target.tolerance_kind])
        difference = None if actual is None else actual - target.expected
        passed = (
            calculation_status == "CALCULABLE"
            and difference is not None
            and abs(difference) <= tolerance
        )
        rows.append(
            {
                "check_id": target.check_id,
                "expected": target.expected,
                "actual": actual,
                "difference": difference,
                "absolute_difference": None if difference is None else abs(difference),
                "tolerance": tolerance,
                "unit": target.unit,
                "locator": target.locator,
                "calculation_status": calculation_status,
                "status": "PASS" if passed else "FAIL",
            }
        )
    return pd.DataFrame(rows)


def require_phase0_pass(checks: pd.DataFrame) -> None:
    if checks.empty or not checks["status"].eq("PASS").all():
        raise Phase0ReproductionError(checks)


def render_phase0_failure(checks: pd.DataFrame) -> str:
    """Return fail-closed ``PHASE0_FAIL.md`` content without writing it."""
    failed = checks.loc[checks["status"].ne("PASS")]
    lines = [
        "# PHASE 0 FAIL",
        "",
        "Phase 0の現在値再現ゲートに不一致があるため、後続分析と記事生成を停止する。",
        "",
        "| check_id | expected | actual | difference | tolerance | target cell / formula | status |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for row in failed.itertuples():
        lines.append(
            f"| {row.check_id} | {row.expected} | {row.actual} | {row.difference} | "
            f"{row.tolerance} | {row.locator} | {row.calculation_status} |"
        )
    lines.extend(
        [
            "",
            "原因候補：rawビンテージ、期間コード、単位変換、表章・業種分類、欠損状態をそれぞれ照合すること。",
            "",
        ]
    )
    return "\n".join(lines)


def _positive_share(
    component_delta: float | None, gross_positive_delta: float | None
) -> tuple[float | None, str]:
    if component_delta is None or gross_positive_delta is None:
        return None, "MISSING_INPUT"
    if gross_positive_delta == 0:
        return None, "ZERO_POSITIVE_DENOMINATOR_NOT_CALCULABLE"
    if component_delta <= 0:
        # This is a defined zero contribution to the positive-only numerator,
        # not missing-value imputation.
        return 0.0, "NON_POSITIVE_COMPONENT"
    return component_delta / gross_positive_delta * 100.0, "CALCULABLE"


def build_taxonomy_contributions(
    processed: pd.DataFrame,
    taxonomy: TaxonomyName,
    *,
    metrics: Sequence[str] = ADDITIVITY_METRICS,
    config: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Build all-capital contribution rows without parent/child mixing."""
    base = _source_base(processed)
    metadata = _dataset_metadata(base)
    definition = taxonomy_definition(taxonomy, config=config)
    total_delta = {
        metric: _observation(base, ALL_INDUSTRY_CODE, ALL_CAPITAL_CODE, metric)["delta"]
        for metric in metrics
    }
    by_metric: dict[str, dict[str, dict[str, float | None]]] = {
        metric: {
            code: _observation(base, code, ALL_CAPITAL_CODE, metric)
            for code in definition["industry_code"]
        }
        for metric in metrics
    }
    gross_positive = {
        metric: _strict_sum(
            max(float(values["delta"]), 0.0)
            if values["delta"] is not None
            else None
            for values in observations.values()
        )
        for metric, observations in by_metric.items()
    }
    rows: list[dict[str, Any]] = []
    for node in definition.itertuples(index=False):
        for metric in metrics:
            values = by_metric[metric][node.industry_code]
            yoy, yoy_status = _safe_yoy(
                metric, values["current"], values["previous"]
            )
            contribution, contribution_status = _safe_ratio(
                values["delta"], total_delta[metric]
            )
            positive, positive_status = _positive_share(
                values["delta"], gross_positive[metric]
            )
            rows.append(
                {
                    **metadata,
                    "taxonomy": taxonomy,
                    "taxonomy_order": node.taxonomy_order,
                    "industry_code": node.industry_code,
                    "industry_name": node.industry_name,
                    "parent_major_code": node.parent_major_code,
                    "parent_major_name": node.parent_major_name,
                    "is_mutually_exclusive": True,
                    "capital_size_code": ALL_CAPITAL_CODE,
                    "capital_size_name": CAPITAL_NAMES[ALL_CAPITAL_CODE],
                    "metric_id": metric,
                    "raw_value_oku_yen": values["current"],
                    "raw_lag4_value_oku_yen": values["previous"],
                    "raw_yoy_delta_oku_yen": values["delta"],
                    "raw_yoy_pct": yoy,
                    "raw_yoy_status": yoy_status,
                    "all_industry_yoy_delta_oku_yen": total_delta[metric],
                    "contribution_pct_to_all_net_change": contribution,
                    "contribution_status": contribution_status,
                    "gross_positive_yoy_delta_oku_yen": gross_positive[metric],
                    "share_of_gross_positive_pct": positive,
                    "positive_share_status": positive_status,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["metric_id", "taxonomy_order"], kind="stable"
    ).reset_index(drop=True)


def build_industry_x_capital(
    processed: pd.DataFrame,
    taxonomy: TaxonomyName = "leaf",
    *,
    config: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Return mutually exclusive industry x three-capital cells in wide form."""
    base = _source_base(processed)
    metadata = _dataset_metadata(base)
    definition = taxonomy_definition(taxonomy, config=config)
    observations: dict[tuple[str, str, str], dict[str, float | None]] = {}
    for code in definition["industry_code"]:
        for capital in CAPITAL_CODES:
            for metric in ANALYSIS_METRICS:
                observations[(code, capital, metric)] = _observation(
                    base, code, capital, metric
                )

    total_delta = {
        metric: _observation(base, ALL_INDUSTRY_CODE, ALL_CAPITAL_CODE, metric)["delta"]
        for metric in ANALYSIS_METRICS
    }
    gross_positive = {}
    for metric in ANALYSIS_METRICS:
        gross_positive[metric] = _strict_sum(
            max(float(observations[(code, capital, metric)]["delta"]), 0.0)
            if observations[(code, capital, metric)]["delta"] is not None
            else None
            for code in definition["industry_code"]
            for capital in CAPITAL_CODES
        )

    rows: list[dict[str, Any]] = []
    for node in definition.itertuples(index=False):
        for capital in CAPITAL_CODES:
            row: dict[str, Any] = {
                **metadata,
                "taxonomy": taxonomy,
                "taxonomy_order": node.taxonomy_order,
                "industry_code": node.industry_code,
                "industry_name": node.industry_name,
                "parent_major_code": node.parent_major_code,
                "parent_major_name": node.parent_major_name,
                "is_mutually_exclusive": True,
                "capital_size_code": capital,
                "capital_size_name": CAPITAL_NAMES[capital],
            }
            for metric in ANALYSIS_METRICS:
                values = observations[(node.industry_code, capital, metric)]
                yoy, yoy_status = _safe_yoy(
                    metric, values["current"], values["previous"]
                )
                contribution, contribution_status = _safe_ratio(
                    values["delta"], total_delta[metric]
                )
                positive, positive_status = _positive_share(
                    values["delta"], gross_positive[metric]
                )
                row.update(
                    {
                        f"{metric}_current_oku_yen": values["current"],
                        f"{metric}_previous_oku_yen": values["previous"],
                        f"{metric}_yoy_delta_oku_yen": values["delta"],
                        f"{metric}_yoy_pct": yoy,
                        f"{metric}_yoy_status": yoy_status,
                        f"{metric}_all_net_change_oku_yen": total_delta[metric],
                        f"{metric}_contribution_pct_to_all_net_change": contribution,
                        f"{metric}_contribution_status": contribution_status,
                        f"{metric}_gross_positive_change_oku_yen": gross_positive[metric],
                        f"{metric}_share_of_gross_positive_pct": positive,
                        f"{metric}_positive_share_status": positive_status,
                    }
                )

            for profit_metric, margin_prefix in (
                ("operating_profit", "operating_margin"),
                ("ordinary_profit", "ordinary_margin"),
            ):
                current_margin, current_status = _margin(
                    row[f"{profit_metric}_current_oku_yen"],
                    row["sales_current_oku_yen"],
                )
                previous_margin, previous_status = _margin(
                    row[f"{profit_metric}_previous_oku_yen"],
                    row["sales_previous_oku_yen"],
                )
                margin_status = (
                    "CALCULABLE"
                    if current_status == previous_status == "CALCULABLE"
                    else current_status
                    if current_status != "CALCULABLE"
                    else previous_status
                )
                row.update(
                    {
                        f"{margin_prefix}_current_pct": current_margin,
                        f"{margin_prefix}_previous_pct": previous_margin,
                        f"{margin_prefix}_delta_pp": (
                            current_margin - previous_margin
                            if margin_status == "CALCULABLE"
                            else None
                        ),
                        f"{margin_prefix}_status": margin_status,
                    }
                )
            current_gap = (
                None
                if row["ordinary_profit_current_oku_yen"] is None
                or row["operating_profit_current_oku_yen"] is None
                else row["ordinary_profit_current_oku_yen"]
                - row["operating_profit_current_oku_yen"]
            )
            previous_gap = (
                None
                if row["ordinary_profit_previous_oku_yen"] is None
                or row["operating_profit_previous_oku_yen"] is None
                else row["ordinary_profit_previous_oku_yen"]
                - row["operating_profit_previous_oku_yen"]
            )
            row.update(
                {
                    "net_non_operating_gap_current_oku_yen": current_gap,
                    "net_non_operating_gap_previous_oku_yen": previous_gap,
                    "net_non_operating_gap_yoy_delta_oku_yen": (
                        current_gap - previous_gap
                        if current_gap is not None and previous_gap is not None
                        else None
                    ),
                }
            )
            rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["taxonomy_order", "capital_size_code"], kind="stable"
    ).reset_index(drop=True)


def _additivity_row(
    *,
    check_id: str,
    taxonomy: str,
    scope: str,
    metric_id: str,
    capital_code: str,
    measure: str,
    expected: float | None,
    actual: float | None,
    tolerance: float,
    parent_major_code: str | None = None,
    industry_code: str | None = None,
) -> dict[str, Any]:
    difference = None if expected is None or actual is None else actual - expected
    if difference is None:
        status = "MISSING_INPUT"
    elif abs(difference) <= tolerance:
        status = "PASS"
    else:
        status = "FAIL"
    return {
        "check_id": check_id,
        "taxonomy": taxonomy,
        "scope": scope,
        "parent_major_code": parent_major_code,
        "industry_code": industry_code,
        "capital_size_code": capital_code,
        "metric_id": metric_id,
        "measure": measure,
        "expected_oku_yen": expected,
        "actual_oku_yen": actual,
        "difference_oku_yen": difference,
        "tolerance_oku_yen": tolerance,
        "status": status,
    }


def validate_taxonomy_additivity(
    processed: pd.DataFrame,
    taxonomy: TaxonomyName,
    *,
    config: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Check child-to-parent and taxonomy-to-total current/prior/delta identities."""
    cfg = dict(config or load_stage2_config())
    tolerance = float(cfg["phase0_tolerances"]["amount_oku_yen"])
    base = _source_base(processed)
    definition = taxonomy_definition(taxonomy, config=cfg)
    measures = {
        "current": "current",
        "previous": "previous",
        "yoy_delta": "delta",
    }
    rows: list[dict[str, Any]] = []
    if taxonomy == "leaf":
        for parent_code, children in definition.groupby("parent_major_code", sort=False):
            codes = children["industry_code"].tolist()
            for capital in (ALL_CAPITAL_CODE, *CAPITAL_CODES):
                for metric in ADDITIVITY_METRICS:
                    child_values = [
                        _observation(base, code, capital, metric) for code in codes
                    ]
                    parent = _observation(base, parent_code, capital, metric)
                    for label, key in measures.items():
                        actual = _strict_sum(value[key] for value in child_values)
                        rows.append(
                            _additivity_row(
                                check_id=f"leaf_parent_{parent_code}_{capital}_{metric}_{label}",
                                taxonomy=taxonomy,
                                scope="CHILDREN_TO_MAJOR_PARENT",
                                parent_major_code=parent_code,
                                metric_id=metric,
                                capital_code=capital,
                                measure=label,
                                expected=parent[key],
                                actual=actual,
                                tolerance=tolerance,
                            )
                        )

    codes = definition["industry_code"].tolist()
    for capital in (ALL_CAPITAL_CODE, *CAPITAL_CODES):
        for metric in ADDITIVITY_METRICS:
            components = [_observation(base, code, capital, metric) for code in codes]
            total = _observation(base, ALL_INDUSTRY_CODE, capital, metric)
            for label, key in measures.items():
                rows.append(
                    _additivity_row(
                        check_id=f"{taxonomy}_grand_{capital}_{metric}_{label}",
                        taxonomy=taxonomy,
                        scope="TAXONOMY_TO_ALL_INDUSTRY",
                        metric_id=metric,
                        capital_code=capital,
                        measure=label,
                        expected=total[key],
                        actual=_strict_sum(value[key] for value in components),
                        tolerance=tolerance,
                    )
                )
    return pd.DataFrame(rows)


def validate_cross_additivity(
    processed: pd.DataFrame,
    cross: pd.DataFrame,
    taxonomy: TaxonomyName,
    *,
    config: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Check industry rows, capital columns, and grand total of a cross table."""
    cfg = dict(config or load_stage2_config())
    tolerance = float(cfg["phase0_tolerances"]["amount_oku_yen"])
    base = _source_base(processed)
    definition = taxonomy_definition(taxonomy, config=cfg)
    rows: list[dict[str, Any]] = []
    measures = {
        "current": "current",
        "previous": "previous",
        "yoy_delta": "delta",
    }
    for node in definition.itertuples(index=False):
        subset = cross.loc[cross["industry_code"].astype(str).eq(node.industry_code)]
        for metric in ANALYSIS_METRICS:
            expected = _observation(base, node.industry_code, ALL_CAPITAL_CODE, metric)
            for label, key in measures.items():
                field = f"{metric}_{label}_oku_yen"
                rows.append(
                    _additivity_row(
                        check_id=f"cross_row_{taxonomy}_{node.industry_code}_{metric}_{label}",
                        taxonomy=taxonomy,
                        scope="CAPITAL_COLUMNS_TO_INDUSTRY",
                        industry_code=node.industry_code,
                        metric_id=metric,
                        capital_code=ALL_CAPITAL_CODE,
                        measure=label,
                        expected=expected[key],
                        actual=_strict_sum(subset[field]),
                        tolerance=tolerance,
                    )
                )
    for capital in CAPITAL_CODES:
        subset = cross.loc[cross["capital_size_code"].astype(str).eq(capital)]
        for metric in ANALYSIS_METRICS:
            expected = _observation(base, ALL_INDUSTRY_CODE, capital, metric)
            for label, key in measures.items():
                field = f"{metric}_{label}_oku_yen"
                rows.append(
                    _additivity_row(
                        check_id=f"cross_column_{taxonomy}_{capital}_{metric}_{label}",
                        taxonomy=taxonomy,
                        scope="INDUSTRY_ROWS_TO_CAPITAL",
                        metric_id=metric,
                        capital_code=capital,
                        measure=label,
                        expected=expected[key],
                        actual=_strict_sum(subset[field]),
                        tolerance=tolerance,
                    )
                )
    for metric in ANALYSIS_METRICS:
        expected = _observation(base, ALL_INDUSTRY_CODE, ALL_CAPITAL_CODE, metric)
        for label, key in measures.items():
            field = f"{metric}_{label}_oku_yen"
            rows.append(
                _additivity_row(
                    check_id=f"cross_grand_{taxonomy}_{metric}_{label}",
                    taxonomy=taxonomy,
                    scope="CROSS_TO_ALL_INDUSTRY_ALL_CAPITAL",
                    metric_id=metric,
                    capital_code=ALL_CAPITAL_CODE,
                    measure=label,
                    expected=expected[key],
                    actual=_strict_sum(cross[field]),
                    tolerance=tolerance,
                )
            )
    return pd.DataFrame(rows)


def build_cell_margin_bridge(cross: pd.DataFrame) -> pd.DataFrame:
    """Two-factor operating-profit bridge for each industry-capital cell.

    The three-term identity is retained verbatim.  The two Shapley factors then
    split the interaction equally, which is the average of the two possible
    factor orders.
    """
    required = {
        "taxonomy",
        "industry_code",
        "industry_name",
        "parent_major_code",
        "parent_major_name",
        "capital_size_code",
        "capital_size_name",
        "sales_current_oku_yen",
        "sales_previous_oku_yen",
        "operating_profit_current_oku_yen",
        "operating_profit_previous_oku_yen",
        "operating_profit_yoy_delta_oku_yen",
    }
    missing = required - set(cross.columns)
    if missing:
        raise Stage2InputError(f"Cross table lacks bridge inputs: {sorted(missing)}")
    rows: list[dict[str, Any]] = []
    for cell in cross.itertuples(index=False):
        metadata = {
            column: getattr(cell, column)
            for column in (
                "release_id",
                "period_code",
                "period",
                "period_end",
                "coverage_scope",
                "source_table_number",
                "estat_sid",
            )
            if hasattr(cell, column)
        }
        output = {
            **metadata,
            "taxonomy": cell.taxonomy,
            "industry_code": str(cell.industry_code),
            "industry_name": cell.industry_name,
            "parent_major_code": str(cell.parent_major_code),
            "parent_major_name": cell.parent_major_name,
            "capital_size_code": str(cell.capital_size_code),
            "capital_size_name": cell.capital_size_name,
            "sales_previous_oku_yen": _number(cell.sales_previous_oku_yen),
            "sales_current_oku_yen": _number(cell.sales_current_oku_yen),
            "operating_profit_previous_oku_yen": _number(
                cell.operating_profit_previous_oku_yen
            ),
            "operating_profit_current_oku_yen": _number(
                cell.operating_profit_current_oku_yen
            ),
            "operating_profit_yoy_delta_oku_yen": _number(
                cell.operating_profit_yoy_delta_oku_yen
            ),
            "operating_margin_previous_pct": None,
            "operating_margin_current_pct": None,
            "sales_change_identity_effect_oku_yen": None,
            "margin_change_identity_effect_oku_yen": None,
            "interaction_identity_effect_oku_yen": None,
            "shapley_sales_effect_oku_yen": None,
            "shapley_margin_effect_oku_yen": None,
            "shapley_reconstructed_delta_oku_yen": None,
            "bridge_residual_oku_yen": None,
            "bridge_status": "MISSING_INPUT",
            "shapley_order_count": 2,
        }
        s0 = output["sales_previous_oku_yen"]
        s1 = output["sales_current_oku_yen"]
        p0 = output["operating_profit_previous_oku_yen"]
        p1 = output["operating_profit_current_oku_yen"]
        reported_delta = output["operating_profit_yoy_delta_oku_yen"]
        if any(value is None for value in (s0, s1, p0, p1, reported_delta)):
            rows.append(output)
            continue
        if float(s0) <= 0 or float(s1) <= 0:
            output["bridge_status"] = "NON_POSITIVE_SALES_NOT_CALCULABLE"
            rows.append(output)
            continue
        margin0 = float(p0) / float(s0)
        margin1 = float(p1) / float(s1)
        delta_sales = float(s1) - float(s0)
        delta_margin = margin1 - margin0
        sales_identity = margin0 * delta_sales
        margin_identity = float(s0) * delta_margin
        interaction = delta_sales * delta_margin
        shapley_sales = sales_identity + interaction / 2.0
        shapley_margin = margin_identity + interaction / 2.0
        reconstructed = shapley_sales + shapley_margin
        output.update(
            {
                "operating_margin_previous_pct": margin0 * 100.0,
                "operating_margin_current_pct": margin1 * 100.0,
                "sales_change_identity_effect_oku_yen": sales_identity,
                "margin_change_identity_effect_oku_yen": margin_identity,
                "interaction_identity_effect_oku_yen": interaction,
                "shapley_sales_effect_oku_yen": shapley_sales,
                "shapley_margin_effect_oku_yen": shapley_margin,
                "shapley_reconstructed_delta_oku_yen": reconstructed,
                "bridge_residual_oku_yen": float(reported_delta) - reconstructed,
                "bridge_status": "CALCULABLE",
            }
        )
        rows.append(output)
    return pd.DataFrame(rows)


def _three_factor_shapley(
    scale0: float,
    scale1: float,
    shares0: np.ndarray,
    shares1: np.ndarray,
    margins0: np.ndarray,
    margins1: np.ndarray,
) -> dict[str, float]:
    factors = ("scale", "composition", "within_margin")

    def value(state: Mapping[str, int]) -> float:
        scale = scale1 if state["scale"] else scale0
        shares = shares1 if state["composition"] else shares0
        margins = margins1 if state["within_margin"] else margins0
        return float(scale * np.dot(shares, margins))

    effects = {factor: 0.0 for factor in factors}
    orders = list(permutations(factors))
    for order in orders:
        state = {factor: 0 for factor in factors}
        before = value(state)
        for factor in order:
            state[factor] = 1
            after = value(state)
            effects[factor] += after - before
            before = after
    return {factor: effect / len(orders) for factor, effect in effects.items()}


def build_capital_margin_bridge(cross: pd.DataFrame) -> pd.DataFrame:
    """Three-factor Shapley bridge by capital size.

    ``scale`` is aggregate sales, ``composition`` is the vector of industry
    sales shares, and ``within_margin`` is the vector of cell margins.  Averaging
    all six orders makes the allocation order-independent and exactly additive.
    A mutually exclusive taxonomy (normally ``leaf``) is mandatory.
    """
    required = {
        "taxonomy",
        "is_mutually_exclusive",
        "industry_code",
        "capital_size_code",
        "capital_size_name",
        "sales_current_oku_yen",
        "sales_previous_oku_yen",
        "operating_profit_current_oku_yen",
        "operating_profit_previous_oku_yen",
        "operating_profit_yoy_delta_oku_yen",
    }
    missing = required - set(cross.columns)
    if missing:
        raise Stage2InputError(f"Cross table lacks aggregate bridge inputs: {sorted(missing)}")
    if cross["taxonomy"].nunique() != 1:
        raise Stage2InputError("Capital bridge requires one taxonomy at a time")
    if not cross["is_mutually_exclusive"].eq(True).all():  # noqa: E712
        raise Stage2InputError("Capital bridge requires a mutually exclusive taxonomy")

    rows: list[dict[str, Any]] = []
    for capital in CAPITAL_CODES:
        group = cross.loc[
            cross["capital_size_code"].astype(str).eq(capital)
        ].sort_values("industry_code", kind="stable")
        metadata = {
            column: group.iloc[0][column]
            for column in (
                "release_id",
                "period_code",
                "period",
                "period_end",
                "coverage_scope",
                "source_table_number",
                "estat_sid",
            )
            if not group.empty and column in group.columns
        }
        output: dict[str, Any] = {
            **metadata,
            "taxonomy": str(cross["taxonomy"].iloc[0]),
            "capital_size_code": capital,
            "capital_size_name": CAPITAL_NAMES[capital],
            "industry_cell_count": len(group),
            "sales_previous_oku_yen": None,
            "sales_current_oku_yen": None,
            "operating_profit_previous_oku_yen": None,
            "operating_profit_current_oku_yen": None,
            "operating_profit_yoy_delta_oku_yen": None,
            "aggregate_sales_scale_effect_oku_yen": None,
            "industry_composition_effect_oku_yen": None,
            "within_industry_margin_effect_oku_yen": None,
            "shapley_reconstructed_delta_oku_yen": None,
            "bridge_residual_oku_yen": None,
            "bridge_status": "MISSING_INPUT",
            "shapley_order_count": 6,
        }
        columns = [
            "sales_previous_oku_yen",
            "sales_current_oku_yen",
            "operating_profit_previous_oku_yen",
            "operating_profit_current_oku_yen",
            "operating_profit_yoy_delta_oku_yen",
        ]
        if group.empty or group[columns].isna().any().any():
            rows.append(output)
            continue
        sales0 = group["sales_previous_oku_yen"].to_numpy(dtype=float)
        sales1 = group["sales_current_oku_yen"].to_numpy(dtype=float)
        profit0 = group["operating_profit_previous_oku_yen"].to_numpy(dtype=float)
        profit1 = group["operating_profit_current_oku_yen"].to_numpy(dtype=float)
        if np.any(sales0 <= 0) or np.any(sales1 <= 0):
            output["bridge_status"] = "NON_POSITIVE_CELL_SALES_NOT_CALCULABLE"
            rows.append(output)
            continue
        scale0 = float(sales0.sum())
        scale1 = float(sales1.sum())
        if scale0 <= 0 or scale1 <= 0:
            output["bridge_status"] = "NON_POSITIVE_TOTAL_SALES_NOT_CALCULABLE"
            rows.append(output)
            continue
        shares0 = sales0 / scale0
        shares1 = sales1 / scale1
        margins0 = profit0 / sales0
        margins1 = profit1 / sales1
        effects = _three_factor_shapley(
            scale0, scale1, shares0, shares1, margins0, margins1
        )
        previous_profit = float(profit0.sum())
        current_profit = float(profit1.sum())
        reported_delta = _strict_sum(group["operating_profit_yoy_delta_oku_yen"])
        reconstructed = sum(effects.values())
        output.update(
            {
                "sales_previous_oku_yen": scale0,
                "sales_current_oku_yen": scale1,
                "operating_profit_previous_oku_yen": previous_profit,
                "operating_profit_current_oku_yen": current_profit,
                "operating_profit_yoy_delta_oku_yen": reported_delta,
                "aggregate_sales_scale_effect_oku_yen": effects["scale"],
                "industry_composition_effect_oku_yen": effects["composition"],
                "within_industry_margin_effect_oku_yen": effects["within_margin"],
                "shapley_reconstructed_delta_oku_yen": reconstructed,
                "bridge_residual_oku_yen": (
                    None
                    if reported_delta is None
                    else reported_delta - reconstructed
                ),
                "bridge_status": "CALCULABLE",
            }
        )
        rows.append(output)
    return pd.DataFrame(rows)


def _analysis_dimensions(
    taxonomy: TaxonomyName, config: Mapping[str, Any] | None = None
) -> list[dict[str, Any]]:
    definition = taxonomy_definition(taxonomy, config=config)
    rows: list[dict[str, Any]] = [
        {
            "aggregation_level": "ALL",
            "industry_code": ALL_INDUSTRY_CODE,
            "industry_name": "全産業（除く金融保険業）",
            "parent_major_code": None,
            "parent_major_name": None,
            "capital_size_code": ALL_CAPITAL_CODE,
            "capital_size_name": CAPITAL_NAMES[ALL_CAPITAL_CODE],
        }
    ]
    rows.extend(
        {
            "aggregation_level": "CAPITAL",
            "industry_code": ALL_INDUSTRY_CODE,
            "industry_name": "全産業（除く金融保険業）",
            "parent_major_code": None,
            "parent_major_name": None,
            "capital_size_code": capital,
            "capital_size_name": CAPITAL_NAMES[capital],
        }
        for capital in CAPITAL_CODES
    )
    for node in definition.itertuples(index=False):
        rows.append(
            {
                "aggregation_level": "INDUSTRY",
                "industry_code": node.industry_code,
                "industry_name": node.industry_name,
                "parent_major_code": node.parent_major_code,
                "parent_major_name": node.parent_major_name,
                "capital_size_code": ALL_CAPITAL_CODE,
                "capital_size_name": CAPITAL_NAMES[ALL_CAPITAL_CODE],
            }
        )
        rows.extend(
            {
                "aggregation_level": "INDUSTRY_X_CAPITAL",
                "industry_code": node.industry_code,
                "industry_name": node.industry_name,
                "parent_major_code": node.parent_major_code,
                "parent_major_name": node.parent_major_name,
                "capital_size_code": capital,
                "capital_size_name": CAPITAL_NAMES[capital],
            }
            for capital in CAPITAL_CODES
        )
    return rows


def _gap_share_status(
    ordinary_previous: float | None,
    ordinary_current: float | None,
    ordinary_delta: float | None,
    gap_delta: float | None,
) -> tuple[float | None, str]:
    if any(
        value is None
        for value in (
            ordinary_previous,
            ordinary_current,
            ordinary_delta,
            gap_delta,
        )
    ):
        return None, "MISSING_INPUT"
    assert ordinary_previous is not None
    assert ordinary_current is not None
    assert ordinary_delta is not None
    assert gap_delta is not None
    if ordinary_previous < 0:
        return None, "NEGATIVE_PRIOR_ORDINARY_PROFIT"
    if ordinary_previous == 0 or ordinary_current == 0:
        return None, "ORDINARY_PROFIT_ZERO_BOUNDARY"
    if ordinary_previous * ordinary_current < 0:
        return None, "ORDINARY_PROFIT_SIGN_TRANSITION"
    if ordinary_delta == 0:
        return None, "ZERO_ORDINARY_PROFIT_CHANGE"
    return gap_delta / ordinary_delta * 100.0, "CALCULABLE"


def build_net_non_operating_gap(
    processed: pd.DataFrame,
    taxonomy: TaxonomyName = "leaf",
    *,
    config: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Calculate ordinary profit minus operating profit at every Phase 1 level.

    The output name intentionally avoids assigning an economic cause.  The gap
    can include net effects of interest, dividends, foreign exchange, equity
    method results, and other non-operating items not separately identified here.
    """
    base = _source_base(processed)
    metadata = _dataset_metadata(base)
    rows: list[dict[str, Any]] = []
    for dimension in _analysis_dimensions(taxonomy, config=config):
        ordinary = _observation(
            base,
            dimension["industry_code"],
            dimension["capital_size_code"],
            "ordinary_profit",
        )
        operating = _observation(
            base,
            dimension["industry_code"],
            dimension["capital_size_code"],
            "operating_profit",
        )
        current_gap = (
            None
            if ordinary["current"] is None or operating["current"] is None
            else ordinary["current"] - operating["current"]
        )
        previous_gap = (
            None
            if ordinary["previous"] is None or operating["previous"] is None
            else ordinary["previous"] - operating["previous"]
        )
        gap_delta = (
            None
            if current_gap is None or previous_gap is None
            else current_gap - previous_gap
        )
        share, share_status = _gap_share_status(
            ordinary["previous"],
            ordinary["current"],
            ordinary["delta"],
            gap_delta,
        )
        if ordinary["previous"] is None or ordinary["current"] is None:
            transition = "NOT_EVALUABLE"
        elif ordinary["previous"] > 0 > ordinary["current"]:
            transition = "PROFIT_TO_LOSS"
        elif ordinary["previous"] < 0 < ordinary["current"]:
            transition = "LOSS_TO_PROFIT"
        elif ordinary["previous"] == 0 or ordinary["current"] == 0:
            transition = "ZERO_BOUNDARY"
        else:
            transition = "NO_SIGN_CHANGE"
        rows.append(
            {
                **metadata,
                "taxonomy": taxonomy,
                **dimension,
                "ordinary_profit_current_oku_yen": ordinary["current"],
                "ordinary_profit_previous_oku_yen": ordinary["previous"],
                "ordinary_profit_yoy_delta_oku_yen": ordinary["delta"],
                "operating_profit_current_oku_yen": operating["current"],
                "operating_profit_previous_oku_yen": operating["previous"],
                "operating_profit_yoy_delta_oku_yen": operating["delta"],
                "net_non_operating_gap_current_oku_yen": current_gap,
                "net_non_operating_gap_previous_oku_yen": previous_gap,
                "net_non_operating_gap_yoy_delta_oku_yen": gap_delta,
                "gap_delta_share_of_ordinary_delta_pct": share,
                "gap_share_status": share_status,
                "ordinary_profit_transition_yoy": transition,
                "interpretation_note": (
                    "ordinary_profit minus operating_profit; may contain net interest, "
                    "dividends, FX, equity-method and other non-operating items"
                ),
            }
        )
    return pd.DataFrame(rows)


def _software_yoy(
    current: float | None, previous: float | None
) -> tuple[float | None, str]:
    if current is None or previous is None:
        return None, "MISSING_INPUT"
    if previous == 0:
        return None, "ZERO_DERIVED_BASE_NOT_CALCULABLE"
    if previous < 0:
        return None, "NEGATIVE_DERIVED_BASE_NOT_CALCULABLE"
    return (current / previous - 1.0) * 100.0, "CALCULABLE"


def build_software_capex_decomposition(
    processed: pd.DataFrame,
    taxonomy: TaxonomyName = "leaf",
    *,
    config: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Derive software capex as including minus excluding software, at all levels."""
    base = _source_base(processed)
    metadata = _dataset_metadata(base)
    rows: list[dict[str, Any]] = []
    for dimension in _analysis_dimensions(taxonomy, config=config):
        including = _observation(
            base,
            dimension["industry_code"],
            dimension["capital_size_code"],
            "capex_including_software",
        )
        excluding = _observation(
            base,
            dimension["industry_code"],
            dimension["capital_size_code"],
            "capex_excluding_software",
        )
        software = {
            key: None
            if including[key] is None or excluding[key] is None
            else including[key] - excluding[key]
            for key in ("current", "previous", "delta")
        }
        yoy, yoy_status = _software_yoy(
            software["current"], software["previous"]
        )
        rows.append(
            {
                **metadata,
                "taxonomy": taxonomy,
                **dimension,
                "capex_including_current_oku_yen": including["current"],
                "capex_including_previous_oku_yen": including["previous"],
                "capex_including_yoy_delta_oku_yen": including["delta"],
                "capex_excluding_current_oku_yen": excluding["current"],
                "capex_excluding_previous_oku_yen": excluding["previous"],
                "capex_excluding_yoy_delta_oku_yen": excluding["delta"],
                "software_capex_current_oku_yen": software["current"],
                "software_capex_previous_oku_yen": software["previous"],
                "software_capex_yoy_delta_oku_yen": software["delta"],
                "software_capex_yoy_pct": yoy,
                "software_capex_yoy_status": yoy_status,
                "prior_base_status": (
                    "MISSING_INPUT"
                    if software["previous"] is None
                    else "ZERO_BASE"
                    if software["previous"] == 0
                    else "NEGATIVE_BASE"
                    if software["previous"] < 0
                    else "POSITIVE_BASE"
                ),
                "is_direct_published_series": False,
                "derivation_method": (
                    "capex_including_software minus capex_excluding_software; "
                    "not a directly published series"
                ),
            }
        )
    result = pd.DataFrame(rows)
    all_row = result.loc[result["aggregation_level"].eq("ALL")].iloc[0]
    all_delta = _number(all_row["software_capex_yoy_delta_oku_yen"])
    all_previous = _number(all_row["software_capex_previous_oku_yen"])
    result["software_contribution_pct_to_all_net_change"] = [
        _safe_ratio(_number(value), all_delta)[0]
        for value in result["software_capex_yoy_delta_oku_yen"]
    ]
    result["software_contribution_status"] = [
        _safe_ratio(_number(value), all_delta)[1]
        for value in result["software_capex_yoy_delta_oku_yen"]
    ]
    result["prior_value_share_of_all_pct"] = [
        _safe_ratio(_number(value), all_previous)[0]
        for value in result["software_capex_previous_oku_yen"]
    ]
    result["prior_value_share_status"] = [
        _safe_ratio(_number(value), all_previous)[1]
        for value in result["software_capex_previous_oku_yen"]
    ]

    result["gross_positive_scope"] = result["aggregation_level"]
    result["gross_positive_yoy_delta_oku_yen"] = np.nan
    result["share_of_gross_positive_pct"] = np.nan
    result["positive_share_status"] = "MISSING_INPUT"
    for level in ("ALL", "CAPITAL", "INDUSTRY", "INDUSTRY_X_CAPITAL"):
        index = result.index[result["aggregation_level"].eq(level)]
        deltas = result.loc[index, "software_capex_yoy_delta_oku_yen"]
        gross = _strict_sum(
            max(float(value), 0.0) if not pd.isna(value) else None
            for value in deltas
        )
        result.loc[index, "gross_positive_yoy_delta_oku_yen"] = gross
        for row_index in index:
            value = _number(result.at[row_index, "software_capex_yoy_delta_oku_yen"])
            share, status = _positive_share(value, gross)
            result.at[row_index, "share_of_gross_positive_pct"] = share
            result.at[row_index, "positive_share_status"] = status
    return result


def validate_decomposition_additivity(
    decomposition: pd.DataFrame,
    value_prefix: Literal["net_non_operating_gap", "software_capex"],
    *,
    config: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Check row, column, and grand-total additivity of a derived decomposition."""
    cfg = dict(config or load_stage2_config())
    tolerance = float(cfg["phase0_tolerances"]["amount_oku_yen"])
    if decomposition["taxonomy"].nunique() != 1:
        raise Stage2InputError("Decomposition additivity requires one taxonomy")
    taxonomy = str(decomposition["taxonomy"].iloc[0])
    fields = {
        "current": f"{value_prefix}_current_oku_yen",
        "previous": f"{value_prefix}_previous_oku_yen",
        "yoy_delta": f"{value_prefix}_yoy_delta_oku_yen",
    }
    missing = set(fields.values()) - set(decomposition.columns)
    if missing:
        raise Stage2InputError(f"Decomposition lacks fields: {sorted(missing)}")
    all_row = decomposition.loc[decomposition["aggregation_level"].eq("ALL")]
    capital_rows = decomposition.loc[decomposition["aggregation_level"].eq("CAPITAL")]
    industry_rows = decomposition.loc[decomposition["aggregation_level"].eq("INDUSTRY")]
    cells = decomposition.loc[
        decomposition["aggregation_level"].eq("INDUSTRY_X_CAPITAL")
    ]
    if len(all_row) != 1:
        raise Stage2InputError("Decomposition requires exactly one ALL row")
    rows: list[dict[str, Any]] = []
    for industry_code, expected_row in industry_rows.groupby("industry_code", sort=False):
        if len(expected_row) != 1:
            raise Stage2InputError(f"Duplicate INDUSTRY row: {industry_code}")
        children = cells.loc[cells["industry_code"].astype(str).eq(str(industry_code))]
        for measure, field in fields.items():
            rows.append(
                _additivity_row(
                    check_id=f"{value_prefix}_row_{industry_code}_{measure}",
                    taxonomy=taxonomy,
                    scope="CAPITAL_COLUMNS_TO_INDUSTRY",
                    industry_code=str(industry_code),
                    metric_id=value_prefix,
                    capital_code=ALL_CAPITAL_CODE,
                    measure=measure,
                    expected=_number(expected_row.iloc[0][field]),
                    actual=_strict_sum(children[field]),
                    tolerance=tolerance,
                )
            )
    for capital_code, expected_row in capital_rows.groupby("capital_size_code", sort=False):
        if len(expected_row) != 1:
            raise Stage2InputError(f"Duplicate CAPITAL row: {capital_code}")
        children = cells.loc[
            cells["capital_size_code"].astype(str).eq(str(capital_code))
        ]
        for measure, field in fields.items():
            rows.append(
                _additivity_row(
                    check_id=f"{value_prefix}_column_{capital_code}_{measure}",
                    taxonomy=taxonomy,
                    scope="INDUSTRY_ROWS_TO_CAPITAL",
                    metric_id=value_prefix,
                    capital_code=str(capital_code),
                    measure=measure,
                    expected=_number(expected_row.iloc[0][field]),
                    actual=_strict_sum(children[field]),
                    tolerance=tolerance,
                )
            )
    for component_scope, components in (
        ("INDUSTRIES_TO_ALL", industry_rows),
        ("CAPITALS_TO_ALL", capital_rows),
        ("CROSS_TO_ALL", cells),
    ):
        for measure, field in fields.items():
            rows.append(
                _additivity_row(
                    check_id=f"{value_prefix}_{component_scope.lower()}_{measure}",
                    taxonomy=taxonomy,
                    scope=component_scope,
                    metric_id=value_prefix,
                    capital_code=ALL_CAPITAL_CODE,
                    measure=measure,
                    expected=_number(all_row.iloc[0][field]),
                    actual=_strict_sum(components[field]),
                    tolerance=tolerance,
                )
            )
    return pd.DataFrame(rows)


def render_phase0_reproduction(checks: pd.DataFrame) -> str:
    """Render a compact PASS/FAIL report; all displayed values come from checks."""
    passed = bool(not checks.empty and checks["status"].eq("PASS").all())
    lines = [
        "# Phase 0 現在値再現ゲート",
        "",
        f"**STATUS: {'PASS' if passed else 'FAIL'}**",
        "",
        "| check_id | expected | actual | difference | tolerance | unit | status |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for row in checks.itertuples():
        lines.append(
            f"| {row.check_id} | {row.expected:.6f} | "
            f"{'NA' if pd.isna(row.actual) else f'{row.actual:.6f}'} | "
            f"{'NA' if pd.isna(row.difference) else f'{row.difference:.6f}'} | "
            f"{row.tolerance:.6f} | {row.unit} | {row.status} |"
        )
    lines.extend(
        [
            "",
            "金額は億円、比率は%、利益率差はポイントで表示した。比率と利益率差の許容誤差はいずれもポイントで評価した。",
            "期待値は監査ターゲットであり、記事の数値ソースではない。",
            "",
        ]
    )
    return "\n".join(lines)


def build_phase1_analysis(
    processed: pd.DataFrame,
    *,
    config: Mapping[str, Any] | None = None,
    enforce_additivity: bool = True,
) -> Phase1Analysis:
    """Run the fail-closed Phase 0 gate and all Phase 1 cross decompositions."""
    cfg = dict(config or load_stage2_config())
    phase0 = reproduce_phase0(processed, config=cfg)
    require_phase0_pass(phase0)

    major_contributions = build_taxonomy_contributions(
        processed, "major", config=cfg
    )
    leaf_contributions = build_taxonomy_contributions(processed, "leaf", config=cfg)
    major_cross = build_industry_x_capital(processed, "major", config=cfg)
    leaf_cross = build_industry_x_capital(processed, "leaf", config=cfg)
    cell_bridge = build_cell_margin_bridge(leaf_cross)
    capital_bridge = build_capital_margin_bridge(leaf_cross)
    gap = build_net_non_operating_gap(processed, "leaf", config=cfg)
    software = build_software_capex_decomposition(processed, "leaf", config=cfg)
    additivity = pd.concat(
        [
            validate_taxonomy_additivity(processed, "major", config=cfg),
            validate_taxonomy_additivity(processed, "leaf", config=cfg),
            validate_cross_additivity(processed, major_cross, "major", config=cfg),
            validate_cross_additivity(processed, leaf_cross, "leaf", config=cfg),
            validate_decomposition_additivity(
                gap, "net_non_operating_gap", config=cfg
            ),
            validate_decomposition_additivity(
                software, "software_capex", config=cfg
            ),
        ],
        ignore_index=True,
        sort=False,
    )
    if enforce_additivity and not additivity["status"].eq("PASS").all():
        failures = additivity.loc[
            additivity["status"].ne("PASS"), "check_id"
        ].tolist()
        raise Stage2InputError(
            "Phase 1 additivity failed or contains missing inputs: "
            + ", ".join(failures[:12])
        )
    return Phase1Analysis(
        phase0_checks=phase0,
        major_taxonomy_contributions=major_contributions,
        leaf_taxonomy_contributions=leaf_contributions,
        major_industry_x_capital=major_cross,
        leaf_industry_x_capital=leaf_cross,
        cell_margin_bridge=cell_bridge,
        capital_margin_bridge=capital_bridge,
        ordinary_operating_gap=gap,
        software_capex_decomposition=software,
        additivity_checks=additivity,
    )
