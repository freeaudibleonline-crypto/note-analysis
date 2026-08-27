"""Public claims and article contracts for the 2026Q1 v3.1 release."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .stage4_charts import (
    CAPITAL_ORDER,
    METRIC_ORDER,
    STAGE4_CHART_FILENAMES,
    _canonical_2x2,
    _canonical_deadband,
    _canonical_heatmap,
)


ARTICLE_TITLE_V3_1 = (
    "食い違いは小規模資本金層に集中していた"
    "――法人企業統計、二つの推計を41四半期並べる"
)
PRIMARY_CLAIM_ID = "V31-SMALL-MARGIN-DIRECTION-MISMATCH"
SUPPLEMENTAL_HEADLINE_CLAIM_ID = "V31-COMPOSITE-HEADLINE-MISMATCH"
BANNED_ARTICLE_EXPRESSIONS = (
    "標本を替えると",
    "継続標本の方が正しい",
    "同一企業パネル",
    "統計的に有意",
    "中小企業だけ",
    "事前確率",
    "誤報率",
    "バイアス率",
    "営業外損益",
)
_TIER_ID = {"small": "SMALL", "middle": "MIDDLE", "large": "LARGE"}
_METRIC_ID = {
    "relative_margin_direction": "MARGIN-DIRECTION",
    "operating_profit": "OPERATING-PROFIT",
    "sales": "SALES",
}


@dataclass(frozen=True)
class Stage4PublicationAudit:
    status: str
    checks: pd.DataFrame

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(
            self.checks.loc[self.checks["status"].eq("FAIL"), "check_id"].astype(str)
        )


def _truthy(value: object) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _claim(
    claim_id: str,
    *,
    role: str,
    metric_id: str,
    scope: str,
    value: float,
    unit: str,
    display: str,
    tokens: Sequence[str],
    numerator: int | None = None,
    denominator: int | None = None,
    value_text: str = "",
    digits: int | None = None,
    charts: Sequence[str] = (),
    calculation: str,
    note: str = "",
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "claim_role": role,
        "claim_class": "CALC",
        "metric_id": metric_id,
        "scope": scope,
        "numeric_value": value,
        "value_text": value_text,
        "unit": unit,
        "numerator": numerator,
        "denominator": denominator,
        "display_value": display,
        "rounding_digits": digits,
        "verification_status": "PASS",
        "article_use": True,
        "chart_ids": ";".join(charts),
        "article_tokens": ";".join(tokens),
        "calculation": calculation,
        "source": "e-Stat表1・財務省「継続標本のみを用いた計数」",
        "note": note,
    }


def _headline_cells(frame: pd.DataFrame) -> dict[str, int]:
    data = _canonical_2x2(frame)
    result: dict[str, int] = {}
    for row in data.itertuples(index=False):
        regular = bool(row.regular_headline_supported)
        continuing = bool(row.continuing_headline_supported)
        key = (
            "both"
            if regular and continuing
            else "regular_only"
            if regular
            else "continuing_only"
            if continuing
            else "neither"
        )
        result[key] = int(row.quarter_count)
    return result


def _rounding_summary(frame: pd.DataFrame) -> dict[str, Any]:
    required = {"period_code", "absolute_decision_margin_pp", "is_ambiguous_by_rounding"}
    missing = required - set(frame)
    if missing:
        raise ValueError(f"rounding_sensitivity lacks columns: {sorted(missing)}")
    data = frame.copy()
    data["absolute_decision_margin_pp"] = pd.to_numeric(
        data["absolute_decision_margin_pp"], errors="coerce"
    )
    if data["absolute_decision_margin_pp"].isna().any():
        raise ValueError("rounding margins contain missing values")
    data["_ambiguous"] = data["is_ambiguous_by_rounding"].map(_truthy)
    idx = data["absolute_decision_margin_pp"].idxmin()
    return {
        "ambiguous": int(data["_ambiguous"].sum()),
        "total": int(len(data)),
        "minimum": float(data.loc[idx, "absolute_decision_margin_pp"]),
        "period": str(data.loc[idx, "period_code"]),
    }


def _extreme_summary(frame: pd.DataFrame) -> dict[str, int]:
    data = frame.copy()
    if "extreme_yoy_rate_gt_100" in data:
        data = data.loc[data["extreme_yoy_rate_gt_100"].map(_truthy)]
    elif "mechanical_trigger" in data:
        data = data.loc[
            data["mechanical_trigger"].astype(str).eq("EXTREME_YOY_RATE_GT_100")
        ]
    else:
        raise ValueError("near_zero_base_flags lacks its mechanical trigger")
    reversal_column = next(
        (
            col
            for col in (
                "relative_margin_direction_reversal",
                "is_margin_direction_mismatch",
                "margin_direction_mismatch",
            )
            if col in data
        ),
        None,
    )
    if reversal_column is None:
        raise ValueError("near_zero_base_flags lacks margin reversal")
    return {
        "flagged": int(len(data)),
        "reversals": int(data[reversal_column].map(_truthy).sum()),
    }


def build_claims_v3_1(
    *,
    headline_2x2: pd.DataFrame,
    mismatch_heatmap: pd.DataFrame,
    rounding_sensitivity: pd.DataFrame,
    deadband_sensitivity: pd.DataFrame,
    near_zero_base_flags: pd.DataFrame,
) -> pd.DataFrame:
    """Create every public number from the prepared v3.1 audit tables."""
    cells = _headline_cells(headline_2x2)
    heat = _canonical_heatmap(mismatch_heatmap)
    dead = _canonical_deadband(deadband_sensitivity)
    rounding = _rounding_summary(rounding_sensitivity)
    extreme = _extreme_summary(near_zero_base_flags)
    indexed = heat.set_index(["capital_tier", "metric_id"])
    primary = indexed.loc[("small", "relative_margin_direction")]
    rows = [
        _claim(
            PRIMARY_CLAIM_ID,
            role="PRIMARY",
            metric_id="relative_margin_direction_mismatch",
            scope="資本金1千万円以上1億円未満層、2016Q1–2026Q1",
            value=float(primary["mismatch_rate_pct"]),
            unit="%",
            numerator=int(primary["mismatch_count"]),
            denominator=int(primary["comparable_count"]),
            display=(
                f"{int(primary['mismatch_count'])}/{int(primary['comparable_count'])}"
                f"（{float(primary['mismatch_rate_pct']):.1f}％）"
            ),
            tokens=("16/41", "39.0％", "41四半期"),
            digits=1,
            charts=(STAGE4_CHART_FILENAMES[0],),
            calculation="100*mismatch_count/comparable_quarters",
            note="2026Q1確認後に過去へ適用した探索的バックテスト。",
        )
    ]
    denominator = sum(cells.values())
    headline_mismatch = cells["regular_only"] + cells["continuing_only"]
    rows.append(
        _claim(
            SUPPLEMENTAL_HEADLINE_CLAIM_ID,
            role="SUPPLEMENTAL",
            metric_id="composite_headline_support_mismatch",
            scope="規模別複合見出し、2016Q1–2026Q1",
            value=100 * headline_mismatch / denominator,
            unit="%",
            numerator=headline_mismatch,
            denominator=denominator,
            display=f"{headline_mismatch}/{denominator}",
            tokens=("11/41",),
            digits=2,
            charts=(STAGE4_CHART_FILENAMES[1],),
            calculation="regular_only + continuing_only",
            note="補足。2026Q1確認後に過去へ適用した探索的バックテスト。",
        )
    )
    cell_specs = (
        ("REGULAR-ONLY", "regular_only"),
        ("CONTINUING-ONLY", "continuing_only"),
        ("BOTH", "both"),
        ("NEITHER", "neither"),
    )
    for suffix, key in cell_specs:
        value = cells[key]
        rows.append(
            _claim(
                f"V31-HEADLINE-2X2-{suffix}",
                role="SUPPORTING",
                metric_id=f"headline_2x2_{key}",
                scope="規模別複合見出し、2016Q1–2026Q1",
                value=float(value),
                unit="quarters",
                display=f"{value}回",
                tokens=(str(value),),
                digits=0,
                charts=(STAGE4_CHART_FILENAMES[1],),
                calculation="count(Boolean support cell)",
            )
        )
    for suffix, value in (
        ("REGULAR-TOTAL", cells["regular_only"] + cells["both"]),
        ("CONTINUING-TOTAL", cells["continuing_only"] + cells["both"]),
    ):
        rows.append(
            _claim(
                f"V31-HEADLINE-{suffix}",
                role="SUPPORTING",
                metric_id=suffix.lower(),
                scope="規模別複合見出し、2016Q1–2026Q1",
                value=float(value),
                unit="quarters",
                display=f"{value}回",
                tokens=(f"{value}回",),
                digits=0,
                charts=(STAGE4_CHART_FILENAMES[1],),
                calculation="sum(supported cells)",
            )
        )
    for tier in CAPITAL_ORDER:
        for metric in METRIC_ORDER:
            if (tier, metric) == ("small", "relative_margin_direction"):
                continue
            item = indexed.loc[(tier, metric)]
            rows.append(
                _claim(
                    f"V31-MISMATCH-{_TIER_ID[tier]}-{_METRIC_ID[metric]}",
                    role="SUPPORTING",
                    metric_id=f"{metric}_mismatch",
                    scope=tier,
                    value=float(item["mismatch_rate_pct"]),
                    unit="%",
                    numerator=int(item["mismatch_count"]),
                    denominator=int(item["comparable_count"]),
                    display=(
                        f"{int(item['mismatch_count'])}/{int(item['comparable_count'])}"
                        f"（{float(item['mismatch_rate_pct']):.1f}％）"
                    ),
                    tokens=(f"{float(item['mismatch_rate_pct']):.1f}％",),
                    digits=1,
                    charts=(STAGE4_CHART_FILENAMES[0],),
                    calculation="100*mismatch_count/comparable_quarters",
                )
            )
    tiers = heat.drop_duplicates("capital_tier").set_index("capital_tier")
    margin_col = "continuing_decision_margin_abs_gap_median_pct"
    gap_col = "cross_series_growth_gap_divergence_median_pp"
    if margin_col not in tiers or gap_col not in tiers:
        raise ValueError("mismatch_heatmap lacks the two confound-check medians")
    for tier in CAPITAL_ORDER:
        for suffix, column, unit, digits, formula in (
            (
                "DECISION-MARGIN-MEDIAN",
                margin_col,
                "%",
                1,
                "median(abs(continuing operating YoY-sales YoY))",
            ),
            (
                "SERIES-DIVERGENCE-MEDIAN",
                gap_col,
                "pt",
                2,
                "median(abs((regular op-sales)-(continuing op-sales)))",
            ),
        ):
            value = float(tiers.loc[tier, column])
            rows.append(
                _claim(
                    f"V31-{_TIER_ID[tier]}-{suffix}",
                    role="SUPPORTING",
                    metric_id=suffix.lower(),
                    scope=tier,
                    value=value,
                    unit=unit,
                    display=f"{value:.{digits}f}{unit}",
                    tokens=(f"{value:.{digits}f}",),
                    digits=digits,
                    charts=(STAGE4_CHART_FILENAMES[0],),
                    calculation=formula,
                )
            )
    rows.extend(
        [
            _claim(
                "V31-ROUNDING-AMBIGUOUS-COUNT",
                role="ROBUSTNESS",
                metric_id="rounding_ambiguous_count",
                scope="資本金1千万円以上1億円未満層",
                value=float(rounding["ambiguous"]),
                unit="quarters",
                numerator=rounding["ambiguous"],
                denominator=rounding["total"],
                display=f"{rounding['ambiguous']}件",
                tokens=(f"{rounding['ambiguous']}件",),
                digits=0,
                calculation="count(NOT_DETERMINED_BY_ROUNDING)",
            ),
            _claim(
                "V31-ROUNDING-MINIMUM-MARGIN",
                role="ROBUSTNESS",
                metric_id="minimum_rounding_decision_margin",
                scope=rounding["period"],
                value=rounding["minimum"],
                value_text=rounding["period"],
                unit="pt",
                display=f"{rounding['minimum']:.1f}pt",
                tokens=(f"{rounding['minimum']:.1f}pt", "2018Q2"),
                digits=1,
                calculation="min(abs(continuing operating YoY-sales YoY))",
            ),
        ]
    )
    dead = dead.sort_values(["capital_tier", "deadband_pct"], kind="stable")
    for item in dead.itertuples(index=False):
        tier = str(item.capital_tier)
        d = float(item.deadband_pct)
        rows.append(
            _claim(
                f"V31-DEADBAND-{_TIER_ID[tier]}-D{int(round(d * 10)):03d}",
                role="ROBUSTNESS",
                metric_id="deadband_margin_direction_mismatch",
                scope=tier,
                value=float(item.mismatch_rate_pct),
                unit="%",
                numerator=int(item.mismatch_count),
                denominator=int(item.retained_count),
                display=(
                    f"±{d:g}%: {int(item.mismatch_count)}/{int(item.retained_count)}"
                    f"（{float(item.mismatch_rate_pct):.1f}％）"
                ),
                tokens=(
                    f"±{d:g}％",
                    f"{int(item.mismatch_count)}/{int(item.retained_count)}",
                    f"{float(item.mismatch_rate_pct):.1f}％",
                ),
                digits=1,
                charts=(STAGE4_CHART_FILENAMES[2],),
                calculation="retain only quarters where both estimates lie outside +/-d",
                note="単位は利益率の相対変化率（%）。絶対ポイント差ではない。",
            )
        )
    rows.extend(
        [
            _claim(
                "V31-EXTREME-YOY-FLAGGED",
                role="ROBUSTNESS",
                metric_id="extreme_yoy_rate_gt_100_count",
                scope="資本金1千万円以上1億円未満層",
                value=float(extreme["flagged"]),
                unit="quarters",
                display=f"{extreme['flagged']}件",
                tokens=(f"{extreme['flagged']}件",),
                digits=0,
                calculation="count(abs(continuing operating-profit YoY)>100%)",
                note="機械的レビュー印。低ベース又はゼロ近傍を立証しない。",
            ),
            _claim(
                "V31-EXTREME-YOY-MISMATCH",
                role="ROBUSTNESS",
                metric_id="extreme_yoy_flagged_mismatch_count",
                scope="資本金1千万円以上1億円未満層",
                value=float(extreme["reversals"]),
                unit="quarters",
                display=f"{extreme['reversals']}件",
                tokens=(f"{extreme['reversals']}件",),
                digits=0,
                calculation="count(flagged AND direction mismatch)",
            ),
            _claim(
                "V31-ROUNDING-HALF-WIDTH",
                role="DEFINITION",
                metric_id="published_rounding_half_width",
                scope="継続標本の公表増減率",
                value=0.05,
                unit="pt",
                display="±0.05pt",
                tokens=("±0.05ポイント",),
                digits=2,
                calculation="published one-decimal rate half-unit",
            ),
            _claim(
                "V31-ROUNDING-AMBIGUITY-THRESHOLD",
                role="DEFINITION",
                metric_id="rounding_ambiguity_threshold",
                scope="継続標本の利益率方向",
                value=0.1,
                unit="pt",
                display="0.1pt",
                tokens=("0.1ポイント",),
                digits=1,
                calculation="two published rates each have +/-0.05pt interval",
            ),
            _claim(
                "V31-EXTREME-YOY-THRESHOLD",
                role="DEFINITION",
                metric_id="extreme_yoy_review_threshold",
                scope="継続標本の営業利益前年比",
                value=100.0,
                unit="%",
                display="100%",
                tokens=("100％",),
                digits=0,
                calculation="mechanical review threshold only",
                note="低ベース又はゼロ近傍を立証しない。",
            ),
            _claim(
                "V31-CENSUS-THRESHOLD",
                role="DEFINITION",
                metric_id="regular_series_census_threshold",
                scope="非金融法人の通常系列",
                value=500_000_000.0,
                unit="yen",
                display="5億円",
                tokens=("5億円",),
                digits=0,
                charts=(STAGE4_CHART_FILENAMES[0],),
                calculation="official survey-design boundary",
            ),
        ]
    )
    claims = pd.DataFrame(rows).sort_values("claim_id", kind="stable").reset_index(drop=True)
    errors = validate_claims_v3_1(claims)
    if errors:
        raise ValueError(f"claims_v3_1 validation failed: {errors}")
    return claims


def validate_claims_v3_1(claims: pd.DataFrame) -> list[str]:
    """Validate in-memory or CSV-round-tripped claims."""
    required = {
        "claim_id",
        "claim_role",
        "claim_class",
        "numeric_value",
        "display_value",
        "verification_status",
        "article_use",
        "chart_ids",
        "article_tokens",
        "numerator",
        "denominator",
    }
    missing = required - set(claims)
    if missing:
        return [f"MISSING_COLUMNS:{','.join(sorted(missing))}"]
    errors: list[str] = []
    ids = claims["claim_id"].astype(str)
    if ids.duplicated().any():
        errors.append("DUPLICATE_CLAIM_IDS")
    indexed = claims.set_index(ids)
    expected_core = {
        "V31-HEADLINE-2X2-REGULAR-ONLY": 9,
        "V31-HEADLINE-2X2-CONTINUING-ONLY": 2,
        "V31-HEADLINE-2X2-BOTH": 1,
        "V31-HEADLINE-2X2-NEITHER": 29,
        "V31-HEADLINE-REGULAR-TOTAL": 10,
        "V31-HEADLINE-CONTINUING-TOTAL": 3,
        "V31-ROUNDING-AMBIGUOUS-COUNT": 0,
        "V31-ROUNDING-MINIMUM-MARGIN": 0.5,
        "V31-EXTREME-YOY-FLAGGED": 3,
        "V31-EXTREME-YOY-MISMATCH": 0,
    }
    for claim_id, expected in expected_core.items():
        if claim_id not in indexed.index:
            errors.append(f"CANONICAL_VALUE_MISSING:{claim_id}")
        elif not np.isclose(float(indexed.loc[claim_id, "numeric_value"]), expected):
            errors.append(f"CANONICAL_VALUE_MISMATCH:{claim_id}")
    for claim_id, numerator, denominator in (
        (PRIMARY_CLAIM_ID, 16, 41),
        (SUPPLEMENTAL_HEADLINE_CLAIM_ID, 11, 41),
        ("V31-DEADBAND-SMALL-D005", 15, 39),
        ("V31-DEADBAND-SMALL-D010", 14, 37),
        ("V31-DEADBAND-SMALL-D020", 10, 33),
        ("V31-DEADBAND-SMALL-D030", 8, 29),
    ):
        if claim_id not in indexed.index:
            errors.append(f"COUNT_CLAIM_MISSING:{claim_id}")
            continue
        row = indexed.loc[claim_id]
        try:
            valid = (
                int(float(row["numerator"])) == numerator
                and int(float(row["denominator"])) == denominator
            )
        except (TypeError, ValueError):
            valid = False
        if not valid:
            errors.append(f"COUNT_CLAIM_MISMATCH:{claim_id}")
    if PRIMARY_CLAIM_ID in indexed.index and str(
        indexed.loc[PRIMARY_CLAIM_ID, "claim_role"]
    ) != "PRIMARY":
        errors.append("PRIMARY_ROLE_MISMATCH")
    numeric = pd.to_numeric(claims["numeric_value"], errors="coerce")
    if numeric.isna().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        errors.append("NONFINITE_NUMERIC_VALUE")
    if not claims["verification_status"].astype(str).eq("PASS").all():
        errors.append("NON_PASS_CLAIM")
    if not claims["article_use"].map(_truthy).any():
        errors.append("NO_ARTICLE_CLAIMS")
    chart_ids = {
        chart
        for value in claims["chart_ids"].fillna("").astype(str)
        for chart in value.split(";")
        if chart
    }
    if chart_ids != set(STAGE4_CHART_FILENAMES):
        errors.append("CHART_CLAIM_COVERAGE_MISMATCH")
    return errors


def _visible_text(markdown: str) -> str:
    text = re.sub(r"<!--.*?-->", "", markdown, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"[#>*_\[\]()|:-]", "", text)
    return re.sub(r"\s+", "", text)


def render_article_note(
    *,
    claims_v3_1: pd.DataFrame,
    chart_paths: Sequence[str] | None = None,
) -> str:
    """Render the single-claim, three-figure public note."""
    errors = validate_claims_v3_1(claims_v3_1)
    if errors:
        raise ValueError(f"Cannot render from invalid claims: {errors}")
    paths = tuple(
        chart_paths or (f"charts/{name}" for name in STAGE4_CHART_FILENAMES)
    )
    if (
        len(paths) != 3
        or tuple(str(path).split("/")[-1] for path in paths)
        != STAGE4_CHART_FILENAMES
    ):
        raise ValueError("Article must use exactly the registered three charts")
    article = f"""# {ARTICLE_TITLE_V3_1} <!-- central-claim: {PRIMARY_CLAIM_ID} --> <!-- claim: {PRIMARY_CLAIM_ID} -->

## 要旨

財務省の法人企業統計には、各期の通常系列と、回答を継続した企業を用いる継続標本系列がある。本稿では資本金1千万円以上1億円未満層を扱い、以下「小規模資本金層」と記す。両系列を2016年1～3月期から2026年1～3月期まで並べると<!-- claim: {PRIMARY_CLAIM_ID} -->、小規模資本金層の営業利益率の上昇・低下方向は16/41四半期、39.0％<!-- claim: {PRIMARY_CLAIM_ID} -->で食い違った。この記事の主張は、この不一致が資本金階層間で均等ではなく、小規模資本金層に集中して観察された、という一点である。

ただし、これは将来の頻度を示す評価ではない。16/41<!-- claim: {PRIMARY_CLAIM_ID} -->と11/41<!-- claim: {SUPPLEMENTAL_HEADLINE_CLAIM_ID} -->はいずれも、2026Q1の結果を見た後に過去へ適用した探索的バックテストである。後者は複数条件を組み合わせた見出しの成立可否であり、本文の主数値ではなく補足に置く。

## 何を比べたのか

通常系列と継続標本系列は、単に同じ真値を異なる標本で測った二つの推計とは限らない。企業の参入・退出、回答継続条件、推計用乗率、未回答補完、母集団構成の違いを含み得る。どちらの系列も真実や正解とは呼ばない。片方を基準にもう片方の優劣を決める比較ではなく、見出しの感応度を系列の構成差とともに記述する作業である。

継続標本では営業利益率水準が公表されていない。そこで、売上高前年比と営業利益前年比から推定した利益率の相対変化率（％）の符号だけを使い、上昇・低下の方向判定だけに限定した。「何ポイント変化した」という比較は行っていない。通常系列にも同じ変換を適用し、同じ定義で並べた。

![資本金階層と指標別の不一致率]({paths[0]})

図1の最上段が主結果である。利益率方向の不一致は小規模資本金層で16/41（39.0％）<!-- claim: {PRIMARY_CLAIM_ID} -->、中堅資本金層で6/41（14.6％）<!-- claim: V31-MISMATCH-MIDDLE-MARGIN-DIRECTION -->、大規模資本金層で0/41（0.0％）<!-- claim: V31-MISMATCH-LARGE-MARGIN-DIRECTION -->だった。

利益率方向だけの現象でもない。営業利益前年比の符号は小規模31.7％<!-- claim: V31-MISMATCH-SMALL-OPERATING-PROFIT -->、中堅9.8％<!-- claim: V31-MISMATCH-MIDDLE-OPERATING-PROFIT -->、大規模0.0％<!-- claim: V31-MISMATCH-LARGE-OPERATING-PROFIT -->で不一致だった。売上高前年比の符号は小規模15.0％<!-- claim: V31-MISMATCH-SMALL-SALES -->、中堅17.1％<!-- claim: V31-MISMATCH-MIDDLE-SALES -->、大規模2.4％<!-- claim: V31-MISMATCH-LARGE-SALES -->である。指標によって細部は違うが、営業利益と利益率方向では小さい資本金階層ほど食い違いが多い。

## 変化幅だけでは説明できない

大規模資本金層の一致を「変化幅が大きいから」と説明できるかも確認した。継続標本について、判定余裕を営業利益増加率と売上高増加率の差の絶対値と定義すると、中央値は小規模11.3％<!-- claim: V31-SMALL-DECISION-MARGIN-MEDIAN -->、中堅9.0％<!-- claim: V31-MIDDLE-DECISION-MARGIN-MEDIAN -->、大規模8.5％<!-- claim: V31-LARGE-DECISION-MARGIN-MEDIAN -->だった。大規模の判定余裕が最大だったわけではない。

両系列の「営業利益前年比－売上高前年比」の差を取り、その絶対値の中央値を見ると、小規模11.21ポイント<!-- claim: V31-SMALL-SERIES-DIVERGENCE-MEDIAN -->、中堅4.07ポイント<!-- claim: V31-MIDDLE-SERIES-DIVERGENCE-MEDIAN -->、大規模1.05ポイント<!-- claim: V31-LARGE-SERIES-DIVERGENCE-MEDIAN -->だった。系列間の乖離そのものが小規模側で大きい。この結果からは「大企業は変化幅が大きいから一致する」という説明は支持されないが、別の仕組みを原因として特定するものでもない。

通常系列では、非金融法人について資本金5億円未満を標本抽出し半数をローテーションする一方、5億円以上は全数選定でローテーションしない<!-- claim: V31-CENSUS-THRESHOLD -->。資本金1億円以上10億円未満層はこの境界をまたぐ。資本金階層別の不一致勾配は調査設計と整合的である。ただし、全数か標本かだけで結果が決まるとはいえない。継続回答条件や乗率、補完、母集団構成も同時に異なり得るからだ。

## 複合見出しの2×2表

![複合見出しの2×2表]({paths[1]})

「大規模資本金層は利益率が改善し、小規模資本金層は悪化する」という複合見出しは、通常系列だけで9回<!-- claim: V31-HEADLINE-2X2-REGULAR-ONLY -->、継続標本系列だけで2回<!-- claim: V31-HEADLINE-2X2-CONTINUING-ONLY -->、両方で1回<!-- claim: V31-HEADLINE-2X2-BOTH -->成立し、どちらでも成立しなかったのが29回<!-- claim: V31-HEADLINE-2X2-NEITHER -->だった。成立回数を系列別に足すと通常系列10回<!-- claim: V31-HEADLINE-REGULAR-TOTAL -->、継続標本系列3回<!-- claim: V31-HEADLINE-CONTINUING-TOTAL -->となる。これは2×2表にみられる非対称の記述であり、通常系列の調査上の失敗を意味しない。

系列間でこの見出しの成立可否が違ったのは11/41四半期<!-- claim: {SUPPLEMENTAL_HEADLINE_CLAIM_ID} -->である。ただし、これは三つの条件を束ねた補足指標だ。異なる尺度を一つの複合数値へ混ぜず、条件を満たしたか否かだけを数えた。主結果はあくまで利益率方向そのものの16/41<!-- claim: {PRIMARY_CLAIM_ID} -->である。

## 二つの頑健性確認

第一は公表値の丸めに対する感応度である。継続標本の売上高前年比と営業利益前年比の各公表値に±0.05ポイント<!-- claim: V31-ROUNDING-HALF-WIDTH -->の区間を置き、両者の差の絶対値が0.1ポイント<!-- claim: V31-ROUNDING-AMBIGUITY-THRESHOLD -->以下なら NOT_DETERMINED_BY_ROUNDING とした。該当は0件<!-- claim: V31-ROUNDING-AMBIGUOUS-COUNT -->で、最小の判定余裕は2018Q2の0.5ポイント<!-- claim: V31-ROUNDING-MINIMUM-MARGIN -->だった。これは表示丸めに限った確認であり、標本誤差は別途未定量である。

第二はデッドバンドである。両系列の推定変化がともに±dの外側にある四半期だけを残した。単位は営業利益率の絶対ポイント差ではなく、売上高前年比と営業利益前年比から推定した利益率の相対変化率（％）である。

![デッドバンド感応度]({paths[2]})

小規模資本金層は、±0.5％で15/39<!-- claim: V31-DEADBAND-SMALL-D005 -->、±1％で14/37<!-- claim: V31-DEADBAND-SMALL-D010 -->、±2％で10/33<!-- claim: V31-DEADBAND-SMALL-D020 -->、±3％で8/29<!-- claim: V31-DEADBAND-SMALL-D030 -->となった。±3％では不一致率が小規模27.6％<!-- claim: V31-DEADBAND-SMALL-D030 -->、中堅0.0％<!-- claim: V31-DEADBAND-MIDDLE-D030 -->、大規模0.0％<!-- claim: V31-DEADBAND-LARGE-D030 -->で、小規模側の食い違いが残る。閾値を動かしても階層差が消える形ではなかったが、閾値は分析者が置いた感応度設定である。

さらに、継続標本の営業利益増加率の絶対値が100％<!-- claim: V31-EXTREME-YOY-THRESHOLD -->を超えた3件<!-- claim: V31-EXTREME-YOY-FLAGGED -->へ、NEAR_ZERO_BASE欄の機械的レビュー印 EXTREME_YOY_RATE_GT_100 を付けたが、名称にかかわらず低ベースやゼロ近傍を示す証拠とは扱わない。その全てが方向不一致ではなかった<!-- claim: V31-EXTREME-YOY-MISMATCH -->。歴史窓の分母を41四半期<!-- claim: {PRIMARY_CLAIM_ID} -->に固定した帰属確認では、利益率方向16/41<!-- claim: {PRIMARY_CLAIM_ID} -->と複合見出し11/41<!-- claim: {SUPPLEMENTAL_HEADLINE_CLAIM_ID} -->の件数は変わらない。これは分母を減らす完全ケース再推計ではない。

## 読み方の限界

継続標本は通常系列より標本数が小さく、営業利益・経常利益の標準誤差率が算出されていない。このため、ここで示した差について標本誤差を数値化して比較することはできない。丸め感応度で判定不能がなかったことと、未定量の標本誤差とは別問題である。

また、継続標本は固定された企業集合を無条件に追跡する資料ではない。回答の継続、企業の状態変化、集計対象の条件を踏まえる必要がある。通常系列はその時点の母集団を表すための推計であり、継続標本系列は継続回答企業の動きを確認する補助資料である。それぞれの目的が違う以上、系列間の食い違いを一方の欠陥へ置き換えない。

以上から公開記事で採用する主張は一つに限る。法人企業統計の利益率方向の食い違いは、観察した41四半期では小規模資本金層に集中していた。これは調査方式による因果を確定する結論ではなく、二つの系列を併記したときに見出しがどこで揺れやすいかを示す記述的な監査結果である。<!-- claim: {PRIMARY_CLAIM_ID} -->
"""
    audit = validate_article_note(article, claims_v3_1)
    if audit.status != "PASS":
        raise ValueError(f"article_note validation failed: {audit.failed_check_ids}")
    return article


def validate_article_note(article: str, claims: pd.DataFrame) -> Stage4PublicationAudit:
    """Fail closed on length, scope, language, figures, and claim linkage."""
    checks: list[dict[str, str]] = []

    def add(check_id: str, condition: bool, detail: str) -> None:
        checks.append(
            {
                "check_id": check_id,
                "status": "PASS" if condition else "FAIL",
                "detail": detail,
            }
        )

    claim_errors = validate_claims_v3_1(claims)
    add("claims_registry_valid", not claim_errors, ";".join(claim_errors) or "complete")
    add("title_exact", article.startswith(f"# {ARTICLE_TITLE_V3_1} "), ARTICLE_TITLE_V3_1)
    count = len(_visible_text(article))
    add("article_length_2500_3500", 2500 <= count <= 3500, f"visible_chars={count}")
    add(
        "single_central_claim",
        article.count(f"<!-- central-claim: {PRIMARY_CLAIM_ID} -->") == 1,
        "one primary marker required",
    )
    figures = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", article)
    add(
        "exactly_three_registered_figures",
        len(figures) == 3
        and tuple(path.split("/")[-1] for path in figures) == STAGE4_CHART_FILENAMES,
        str(figures),
    )
    found_banned = [term for term in BANNED_ARTICLE_EXPRESSIONS if term in article]
    if "有意" in article and "統計的に有意" not in found_banned:
        found_banned.append("有意")
    add("no_banned_expressions", not found_banned, str(found_banned))
    add(
        "no_nonoperating_bridge",
        not any(
            term in article
            for term in ("受取利息", "支払利息", "営業外収益", "営業外費用")
        ),
        "sample sensitivity only",
    )
    anchors = (
        "16/41と11/41はいずれも、2026Q1の結果を見た後に過去へ適用した探索的バックテスト",
        "売上高前年比と営業利益前年比から推定した利益率の相対変化率（％）",
        "単に同じ真値を異なる標本で測った二つの推計とは限らない",
        "企業の参入・退出",
        "回答継続条件",
        "推計用乗率",
        "未回答補完",
        "母集団構成",
        "調査設計と整合的",
        "標本誤差は別途未定量",
        "営業利益・経常利益の標準誤差率が算出されていない",
    )
    article_without_markers = re.sub(r"<!--.*?-->", "", article, flags=re.S)
    missing_anchors = [
        anchor for anchor in anchors if anchor not in article_without_markers
    ]
    add("required_interpretation_caveats", not missing_anchors, str(missing_anchors))
    add(
        "formal_small_capital_definition",
        "本稿では資本金1千万円以上1億円未満層を扱い、以下「小規模資本金層」と記す"
        in article,
        "formal first-body definition",
    )
    add(
        "primary_precedes_supplemental",
        article.find("16/41") < article.find("11/41"),
        "primary 16/41 must appear first",
    )
    markers = set(re.findall(r"<!-- claim: ([A-Z0-9-]+) -->", article))
    known = set(claims["claim_id"].astype(str))
    add("article_claim_markers_registered", markers <= known, str(sorted(markers - known)))
    used = claims.loc[claims["claim_id"].astype(str).isin(markers)]
    add(
        "article_claims_pass",
        not used.empty and used["verification_status"].astype(str).eq("PASS").all(),
        f"used={len(used)}",
    )
    table = pd.DataFrame(checks)
    return Stage4PublicationAudit(
        status="PASS" if table["status"].eq("PASS").all() else "FAIL",
        checks=table,
    )
