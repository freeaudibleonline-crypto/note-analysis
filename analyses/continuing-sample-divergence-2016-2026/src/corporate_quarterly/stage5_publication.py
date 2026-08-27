"""Publication-only contracts for the 2026Q1 v3.2 release.

This module deliberately does not read or write release directories.  The
pipeline supplies the already-validated ``claims_v3_2`` registry, receives an
auditable Markdown article, and may then turn that source into a note-ready
render.  Consequently the numerical lineage is always::

    canonical CSV -> claims_v3_2 -> article_note

The render step removes audit annotations; it never reconstructs prose or
numbers independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Mapping, Sequence

import numpy as np
import pandas as pd


ARTICLE_TITLE_V3_2 = (
    "利益率方向の食い違いは小規模資本金層に集中していた"
    "――法人企業統計、二つの推計を41四半期比べる"
)
OLD_ARTICLE_TITLE_V3_1 = (
    "食い違いは小規模資本金層に集中していた"
    "――法人企業統計、二つの推計を41四半期並べる"
)
FORMAL_SMALL_CAPITAL_NAME_V3_2 = "資本金1,000万円以上1億円未満層"

PRIMARY_CLAIM_ID = "V31-SMALL-MARGIN-DIRECTION-MISMATCH"
SUPPLEMENTAL_CLAIM_ID = "V31-COMPOSITE-HEADLINE-MISMATCH"

V32_EXAMPLE_CLAIM_IDS = (
    "V32-2026Q1-SMALL-REGULAR-SALES-YOY",
    "V32-2026Q1-SMALL-REGULAR-OPERATING-PROFIT-YOY",
    "V32-2026Q1-SMALL-CONTINUING-SALES-YOY",
    "V32-2026Q1-SMALL-CONTINUING-OPERATING-PROFIT-YOY",
    "V32-2026Q1-SMALL-SALES-CROSS-SERIES-GAP",
    "V32-2026Q1-SMALL-OPERATING-PROFIT-CROSS-SERIES-GAP",
)

DECISION_MARGIN_CLAIM_IDS = (
    "V31-SMALL-DECISION-MARGIN-MEDIAN",
    "V31-MIDDLE-DECISION-MARGIN-MEDIAN",
    "V31-LARGE-DECISION-MARGIN-MEDIAN",
)

STAGE5_CHART_FILENAMES = (
    "mismatch_heatmap.png",
    "headline_2x2.png",
    "deadband_sensitivity.png",
)
FIGURE_MARKERS_V3_2: Mapping[str, str] = {
    "mismatch_heatmap.png": "【図1：資本金階層・指標別の方向不一致率】",
    "headline_2x2.png": "【図2：複合見出しの2×2表】",
    "deadband_sensitivity.png": "【図3：deadband感応度】",
}

_CLAIM_MARKER = re.compile(r"<!--\s*claim:\s*([^\s]+)\s*-->")
_CENTRAL_MARKER = re.compile(r"<!--\s*central-claim:\s*([^\s]+)\s*-->")
_HTML_COMMENT = re.compile(r"<!--.*?-->", flags=re.DOTALL)
_FIGURE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_STATISTICAL_NUMBER = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:[＋+\-－−±]?\d[\d,]*(?:\.\d+)?/\d[\d,]*(?:\.\d+)?"
    r"(?:\s*(?:％|%|pt|ポイント|件|回|四半期))?"
    r"|[＋+\-－−±]?\d[\d,]*(?:\.\d+)?\s*"
    r"(?:％|%|pt|ポイント|件|回|四半期|万円|億円|兆円))"
)
_ANY_DIGIT = re.compile(r"\d")

_REQUIRED_CLAIMS = frozenset(
    {
        PRIMARY_CLAIM_ID,
        SUPPLEMENTAL_CLAIM_ID,
        *V32_EXAMPLE_CLAIM_IDS,
        *DECISION_MARGIN_CLAIM_IDS,
        "V31-MISMATCH-MIDDLE-MARGIN-DIRECTION",
        "V31-MISMATCH-LARGE-MARGIN-DIRECTION",
        "V31-MISMATCH-SMALL-OPERATING-PROFIT",
        "V31-MISMATCH-MIDDLE-OPERATING-PROFIT",
        "V31-MISMATCH-LARGE-OPERATING-PROFIT",
        "V31-MISMATCH-SMALL-SALES",
        "V31-MISMATCH-MIDDLE-SALES",
        "V31-MISMATCH-LARGE-SALES",
        "V31-SMALL-SERIES-DIVERGENCE-MEDIAN",
        "V31-MIDDLE-SERIES-DIVERGENCE-MEDIAN",
        "V31-LARGE-SERIES-DIVERGENCE-MEDIAN",
        "V31-HEADLINE-2X2-REGULAR-ONLY",
        "V31-HEADLINE-2X2-CONTINUING-ONLY",
        "V31-HEADLINE-2X2-BOTH",
        "V31-HEADLINE-2X2-NEITHER",
        "V31-HEADLINE-REGULAR-TOTAL",
        "V31-HEADLINE-CONTINUING-TOTAL",
        "V31-ROUNDING-HALF-WIDTH",
        "V31-ROUNDING-AMBIGUITY-THRESHOLD",
        "V31-ROUNDING-AMBIGUOUS-COUNT",
        "V31-ROUNDING-MINIMUM-MARGIN",
        "V31-DEADBAND-SMALL-D005",
        "V31-DEADBAND-SMALL-D010",
        "V31-DEADBAND-SMALL-D020",
        "V31-DEADBAND-SMALL-D030",
        "V31-DEADBAND-MIDDLE-D030",
        "V31-DEADBAND-LARGE-D030",
        "V31-EXTREME-YOY-THRESHOLD",
        "V31-EXTREME-YOY-FLAGGED",
        "V31-EXTREME-YOY-MISMATCH",
        "V31-CENSUS-THRESHOLD",
    }
)

_EXPECTED_UNITS: Mapping[str, str] = {
    PRIMARY_CLAIM_ID: "percent",
    SUPPLEMENTAL_CLAIM_ID: "percent",
    "V32-2026Q1-SMALL-REGULAR-SALES-YOY": "percent",
    "V32-2026Q1-SMALL-REGULAR-OPERATING-PROFIT-YOY": "percent",
    "V32-2026Q1-SMALL-CONTINUING-SALES-YOY": "percent",
    "V32-2026Q1-SMALL-CONTINUING-OPERATING-PROFIT-YOY": "percent",
    "V32-2026Q1-SMALL-SALES-CROSS-SERIES-GAP": "percentage_points",
    "V32-2026Q1-SMALL-OPERATING-PROFIT-CROSS-SERIES-GAP": "percentage_points",
    "V31-SMALL-DECISION-MARGIN-MEDIAN": "percentage_points",
    "V31-MIDDLE-DECISION-MARGIN-MEDIAN": "percentage_points",
    "V31-LARGE-DECISION-MARGIN-MEDIAN": "percentage_points",
    "V31-SMALL-SERIES-DIVERGENCE-MEDIAN": "percentage_points",
    "V31-MIDDLE-SERIES-DIVERGENCE-MEDIAN": "percentage_points",
    "V31-LARGE-SERIES-DIVERGENCE-MEDIAN": "percentage_points",
    "V31-ROUNDING-HALF-WIDTH": "percentage_points",
    "V31-ROUNDING-AMBIGUITY-THRESHOLD": "percentage_points",
    "V31-ROUNDING-MINIMUM-MARGIN": "percentage_points",
    "V31-ROUNDING-AMBIGUOUS-COUNT": "count",
    "V31-EXTREME-YOY-THRESHOLD": "percent",
    "V31-EXTREME-YOY-FLAGGED": "count",
    "V31-EXTREME-YOY-MISMATCH": "count",
}

for _claim_id in (
    "V31-MISMATCH-MIDDLE-MARGIN-DIRECTION",
    "V31-MISMATCH-LARGE-MARGIN-DIRECTION",
    "V31-MISMATCH-SMALL-OPERATING-PROFIT",
    "V31-MISMATCH-MIDDLE-OPERATING-PROFIT",
    "V31-MISMATCH-LARGE-OPERATING-PROFIT",
    "V31-MISMATCH-SMALL-SALES",
    "V31-MISMATCH-MIDDLE-SALES",
    "V31-MISMATCH-LARGE-SALES",
    "V31-DEADBAND-SMALL-D005",
    "V31-DEADBAND-SMALL-D010",
    "V31-DEADBAND-SMALL-D020",
    "V31-DEADBAND-SMALL-D030",
    "V31-DEADBAND-MIDDLE-D030",
    "V31-DEADBAND-LARGE-D030",
):
    _EXPECTED_UNITS[_claim_id] = "percent"
for _claim_id in (
    "V31-HEADLINE-2X2-REGULAR-ONLY",
    "V31-HEADLINE-2X2-CONTINUING-ONLY",
    "V31-HEADLINE-2X2-BOTH",
    "V31-HEADLINE-2X2-NEITHER",
    "V31-HEADLINE-REGULAR-TOTAL",
    "V31-HEADLINE-CONTINUING-TOTAL",
):
    _EXPECTED_UNITS[_claim_id] = "count"

_BANNED_LITERAL_EXPRESSIONS = (
    "標本を替えると",
    "継続標本の方が正しい",
    "通常系列が間違っている",
    "真実は継続標本にある",
    "同一企業パネル",
    "統計的に有意",
    "通常系列のバイアス",
    "誤報率",
    "中小企業だけ",
    "調査方式が原因である",
    "外形標準課税",
    "税制上の減資インセンティブ",
    "自己申告区分",
)
_NONOPERATING_TERMS = (
    "営業外損益",
    "受取利息",
    "支払利息",
    "営業外収益",
    "営業外費用",
    "nonoperating",
    "non_operating",
)
_IMPLEMENTATION_LABELS = (
    "NOT_DETERMINED_BY_ROUNDING",
    "NEAR_ZERO_BASE",
    "EXTREME_YOY_RATE_GT_100",
    "central-claim",
    "claim:",
)


@dataclass(frozen=True)
class Stage5PublicationAudit:
    """Machine-readable article validation result."""

    status: str
    checks: pd.DataFrame

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        if self.checks.empty:
            return ()
        return tuple(
            self.checks.loc[self.checks["status"].ne("PASS"), "check_id"].astype(str)
        )


def _result(rows: Sequence[dict[str, str]]) -> Stage5PublicationAudit:
    checks = pd.DataFrame(rows, columns=["check_id", "status", "detail"])
    status = "PASS" if not checks.empty and checks["status"].eq("PASS").all() else "FAIL"
    return Stage5PublicationAudit(status=status, checks=checks)


def _add(rows: list[dict[str, str]], check_id: str, passed: bool, detail: str) -> None:
    rows.append(
        {
            "check_id": check_id,
            "status": "PASS" if bool(passed) else "FAIL",
            "detail": str(detail),
        }
    )


def _strict_bool(value: object) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)) and int(value) in (0, 1):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


class _ClaimBook:
    """Strict scalar access to a unique, verified claims registry."""

    def __init__(self, claims: pd.DataFrame):
        required_columns = {
            "claim_id",
            "numeric_value",
            "unit",
            "verification_status",
            "article_use",
        }
        missing_columns = required_columns - set(claims.columns)
        if missing_columns:
            raise ValueError(f"claims_v3_2 lacks columns: {sorted(missing_columns)}")
        ids = claims["claim_id"].fillna("").astype(str)
        if ids.duplicated().any():
            duplicate_ids = sorted(ids.loc[ids.duplicated(keep=False)].unique())
            raise ValueError(f"duplicate claim IDs: {duplicate_ids}")
        self._claims = claims.set_index(ids, drop=False)
        missing_claims = sorted(_REQUIRED_CLAIMS - set(ids))
        if missing_claims:
            raise ValueError(f"claims_v3_2 lacks required claims: {missing_claims}")
        required_rows = self._claims.loc[sorted(_REQUIRED_CLAIMS)]
        if not required_rows["verification_status"].astype(str).eq("PASS").all():
            raise ValueError("all article claims must have verification_status=PASS")
        if not required_rows["article_use"].map(_strict_bool).all():
            raise ValueError("all article claims must have article_use=true")
        bad_units = {
            claim_id: str(self._claims.loc[claim_id, "unit"])
            for claim_id, expected in _EXPECTED_UNITS.items()
            if str(self._claims.loc[claim_id, "unit"]) != expected
        }
        if bad_units:
            raise ValueError(f"claim unit mismatch: {bad_units}")

    def row(self, claim_id: str) -> pd.Series:
        return self._claims.loc[claim_id]

    def number(self, claim_id: str) -> float:
        value = pd.to_numeric(pd.Series([self.row(claim_id)["numeric_value"]]), errors="coerce").iloc[0]
        if pd.isna(value) or not np.isfinite(float(value)):
            raise ValueError(f"non-finite numeric_value: {claim_id}")
        return float(value)

    def integer(self, claim_id: str, field: str = "numeric_value") -> int:
        value = pd.to_numeric(pd.Series([self.row(claim_id).get(field)]), errors="coerce").iloc[0]
        if pd.isna(value) or not float(value).is_integer():
            raise ValueError(f"{claim_id}.{field} is not an integer")
        return int(value)

    def fraction(self, claim_id: str) -> str:
        return f"{self.integer(claim_id, 'numerator')}/{self.integer(claim_id, 'denominator')}"


def _marker(claim_id: str) -> str:
    return f"<!-- claim: {claim_id} -->"


def _signed_percent(book: _ClaimBook, claim_id: str, digits: int = 1) -> str:
    value = book.number(claim_id)
    sign = "＋" if value >= 0 else "－"
    return f"{sign}{abs(value):.{digits}f}％"


def _percent(book: _ClaimBook, claim_id: str, digits: int = 1) -> str:
    return f"{book.number(claim_id):.{digits}f}％"


def _points(book: _ClaimBook, claim_id: str, digits: int) -> str:
    return f"{book.number(claim_id):.{digits}f}ポイント"


def _display(book: _ClaimBook, claim_id: str) -> str:
    value = book.row(claim_id).get("display_value", "")
    if pd.isna(value) or not str(value).strip():
        raise ValueError(f"{claim_id}.display_value is required")
    return str(value).strip()


def _value_text(book: _ClaimBook, claim_id: str) -> str:
    value = book.row(claim_id).get("value_text", "")
    if pd.isna(value) or not str(value).strip():
        raise ValueError(f"{claim_id}.value_text is required")
    if claim_id == "V31-ROUNDING-MINIMUM-MARGIN":
        # The frozen v3.1 CSV stores the quarter as numeric period code 20182.
        # pandas may surface it as ``20182.0``; format the code without
        # changing the historical artifact.
        period_code = int(float(value))
        year, quarter = divmod(period_code, 10)
        if year < 2000 or quarter not in {1, 2, 3, 4}:
            raise ValueError(f"invalid quarterly period code: {value!r}")
        return f"{year}Q{quarter}"
    return str(value).strip()


def _fraction_with_rate(book: _ClaimBook, claim_id: str) -> str:
    return f"{book.fraction(claim_id)}（{_percent(book, claim_id)}）"


def _count(book: _ClaimBook, claim_id: str, suffix: str) -> str:
    return f"{book.integer(claim_id)}{suffix}"


def _deadband_threshold(book: _ClaimBook, claim_id: str) -> float:
    row = book.row(claim_id)
    for field in ("display_value", "article_tokens"):
        value = row.get(field, "")
        if pd.isna(value):
            continue
        match = re.search(r"±\s*(\d+(?:\.\d+)?)", str(value))
        if match:
            return float(match.group(1))
    raise ValueError(f"deadband threshold is not represented by claim {claim_id}")


def _deadband_summary(book: _ClaimBook, claim_id: str) -> str:
    threshold = _deadband_threshold(book, claim_id)
    return f"±{threshold:g}％で{book.fraction(claim_id)}"


def visible_article_text(markdown: str) -> str:
    """Return approximate reader-visible text for publication length gates."""
    text = _HTML_COMMENT.sub("", markdown)
    text = _FIGURE.sub("", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^```.*?$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\|?\s*:?-{3,}:?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s{0,3}(?:#{1,6}|>|[-+*]|\d+[.)])\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`~|]", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", "", text)


def visible_article_character_count(markdown: str) -> int:
    return len(visible_article_text(markdown))


def origin_section_character_count(markdown: str) -> int:
    """Count only prose below the origin heading and above the next H2."""
    match = re.search(
        r"^## 発端は2026年1～3月期(?:\s*<!--.*?-->)?\s*\n(.*?)(?=^##\s)",
        markdown,
        flags=re.MULTILINE | re.DOTALL,
    )
    return 0 if match is None else visible_article_character_count(match.group(1))


def render_article_note_v3_2(
    *,
    claims_v3_2: pd.DataFrame,
    chart_paths: Sequence[str] | None = None,
) -> str:
    """Build the auditable v3.2 article exclusively from verified claims."""
    book = _ClaimBook(claims_v3_2)
    paths = tuple(chart_paths or (f"charts/{name}" for name in STAGE5_CHART_FILENAMES))
    if (
        len(paths) != len(STAGE5_CHART_FILENAMES)
        or tuple(Path(path).name for path in paths) != STAGE5_CHART_FILENAMES
        or any(Path(path).is_absolute() for path in paths)
    ):
        raise ValueError("article_note must use the three registered relative chart paths")

    rs, ro, cs, co, sg, og = V32_EXAMPLE_CLAIM_IDS
    primary_fraction = book.fraction(PRIMARY_CLAIM_ID)
    supplemental_fraction = book.fraction(SUPPLEMENTAL_CLAIM_ID)
    primary_periods = book.integer(PRIMARY_CLAIM_ID, "denominator")
    article_title = (
        "利益率方向の食い違いは小規模資本金層に集中していた"
        f"――法人企業統計、二つの推計を{primary_periods}四半期比べる"
    )

    article = f"""# {article_title} <!-- central-claim: {PRIMARY_CLAIM_ID} --> <!-- claim: {PRIMARY_CLAIM_ID} -->

## 発端は2026年1～3月期 <!-- claim: {rs} -->

対象は{FORMAL_SMALL_CAPITAL_NAME_V3_2}である。<!-- claim: {rs} -->2026年1～3月期、通常系列は売上高{_signed_percent(book, rs)}<!-- claim: {rs} -->、営業利益{_signed_percent(book, ro)}<!-- claim: {ro} -->、継続標本系列は売上高{_signed_percent(book, cs)}<!-- claim: {cs} -->、営業利益{_signed_percent(book, co)}<!-- claim: {co} -->だった。売上高はいずれの系列でも増加したが、営業利益の増減方向は通常系列で減少、継続標本系列で増加と分かれ、推定する営業利益率の方向も低下と上昇に分かれた。系列間の絶対差は売上高{_points(book, sg, 1)}<!-- claim: {sg} -->、営業利益{_points(book, og, 1)}<!-- claim: {og} -->である。この一例を起点に、比較可能な過去{primary_periods}四半期へ確認を広げた。<!-- claim: {PRIMARY_CLAIM_ID} -->

## 要旨

財務省の法人企業統計には、各期の通常系列と、回答を継続した企業を用いる継続標本系列がある。以後、冒頭で定義した資本金階層を「小規模資本金層」と記す。両系列を並べると、小規模資本金層の営業利益率の上昇・低下方向は{_fraction_with_rate(book, PRIMARY_CLAIM_ID)}で食い違った。<!-- claim: {PRIMARY_CLAIM_ID} -->この記事の主張は、この方向不一致が資本金階層間で均等ではなく、営業利益と利益率方向では小規模資本金層に集中して観察された、という一点である。

ただし、これは将来の頻度を示す評価ではない。{primary_fraction}<!-- claim: {PRIMARY_CLAIM_ID} -->と{supplemental_fraction}<!-- claim: {SUPPLEMENTAL_CLAIM_ID} -->はいずれも、対象期の結果を見た後に過去へ適用した探索的バックテストである。後者は複数条件を組み合わせた見出しの成立可否であり、本文の主数値ではなく補足に置く。

## 何を比べたのか

通常系列と継続標本系列は、単に同じ真値を異なる標本で測った二つの推計とは限らない。標本の入れ替え、継続回答法人への限定、推計用乗率、未回答補完、企業の参入・退出、母集団構成の違いを含み得る。また、増資や減資によって同じ企業が資本金階層間を移る可能性もある。これは分類移動の一般的な説明であり、今回観察した差の原因を特定するものではない。どちらの系列も真実や正解とは呼ばない。片方を基準にもう片方の優劣を決める比較ではなく、見出しの感応度を系列の構成差とともに記述する作業である。

継続標本では営業利益率水準が公表されていない。そこで、売上高前年比と営業利益前年比から推定した利益率の相対変化率（％）の符号だけを使い、上昇・低下の方向判定だけに限定した。「何ポイント変化した」という比較は行っていない。通常系列にも同じ変換を適用し、同じ定義で並べた。

![資本金階層・指標別の方向不一致率]({paths[0]})

最初の図の利益率方向を見ると、不一致は小規模資本金層で{_fraction_with_rate(book, PRIMARY_CLAIM_ID)}<!-- claim: {PRIMARY_CLAIM_ID} -->、中間資本金層で{_fraction_with_rate(book, 'V31-MISMATCH-MIDDLE-MARGIN-DIRECTION')}<!-- claim: V31-MISMATCH-MIDDLE-MARGIN-DIRECTION -->、大規模資本金層で{_fraction_with_rate(book, 'V31-MISMATCH-LARGE-MARGIN-DIRECTION')}<!-- claim: V31-MISMATCH-LARGE-MARGIN-DIRECTION -->だった。

利益率方向だけの現象でもない。営業利益前年比の符号不一致率は、小規模{_percent(book, 'V31-MISMATCH-SMALL-OPERATING-PROFIT')}<!-- claim: V31-MISMATCH-SMALL-OPERATING-PROFIT -->、中間{_percent(book, 'V31-MISMATCH-MIDDLE-OPERATING-PROFIT')}<!-- claim: V31-MISMATCH-MIDDLE-OPERATING-PROFIT -->、大規模{_percent(book, 'V31-MISMATCH-LARGE-OPERATING-PROFIT')}<!-- claim: V31-MISMATCH-LARGE-OPERATING-PROFIT -->だった。売上高前年比の符号不一致率は、小規模{_percent(book, 'V31-MISMATCH-SMALL-SALES')}<!-- claim: V31-MISMATCH-SMALL-SALES -->、中間{_percent(book, 'V31-MISMATCH-MIDDLE-SALES')}<!-- claim: V31-MISMATCH-MIDDLE-SALES -->、大規模{_percent(book, 'V31-MISMATCH-LARGE-SALES')}<!-- claim: V31-MISMATCH-LARGE-SALES -->である。売上高では中間が小規模をわずかに上回る。したがって図全体ではなく、営業利益と利益率方向に限って小規模側への集中を述べる。

## 変化幅だけでは説明できない

大規模資本金層の一致を「変化幅が大きいから」と説明できるかも確認した。継続標本について、判定余裕を営業利益増加率と売上高増加率の差の絶対値と定義すると、中央値は小規模{_points(book, DECISION_MARGIN_CLAIM_IDS[0], 1)}<!-- claim: {DECISION_MARGIN_CLAIM_IDS[0]} -->、中間{_points(book, DECISION_MARGIN_CLAIM_IDS[1], 1)}<!-- claim: {DECISION_MARGIN_CLAIM_IDS[1]} -->、大規模{_points(book, DECISION_MARGIN_CLAIM_IDS[2], 1)}<!-- claim: {DECISION_MARGIN_CLAIM_IDS[2]} -->だった。増加率同士の差なので、単位は％ではなくポイントである。大規模の判定余裕が最大だったわけではない。

両系列の「営業利益前年比－売上高前年比」の差を取り、その絶対値の中央値を見ると、小規模{_points(book, 'V31-SMALL-SERIES-DIVERGENCE-MEDIAN', 2)}<!-- claim: V31-SMALL-SERIES-DIVERGENCE-MEDIAN -->、中間{_points(book, 'V31-MIDDLE-SERIES-DIVERGENCE-MEDIAN', 2)}<!-- claim: V31-MIDDLE-SERIES-DIVERGENCE-MEDIAN -->、大規模{_points(book, 'V31-LARGE-SERIES-DIVERGENCE-MEDIAN', 2)}<!-- claim: V31-LARGE-SERIES-DIVERGENCE-MEDIAN -->だった。系列間の乖離そのものが小規模側で大きい。この結果からは「大企業は変化幅が大きいから一致する」という説明は支持されないが、別の仕組みを原因として特定するものでもない。

通常系列では、非金融法人について資本金{_display(book, 'V31-CENSUS-THRESHOLD')}未満を標本抽出し半数をローテーションする一方、同額以上は全数選定でローテーションしない。<!-- claim: V31-CENSUS-THRESHOLD -->中間資本金層はこの境界をまたぐ。資本金階層別の不一致勾配は調査設計と整合的である。ただし、全数か標本かだけで結果が決まるとはいえない。継続回答条件や乗率、補完、母集団構成、階層間移動も同時に異なり得るからだ。

## 複合見出しの成立区分

![複合見出しの成立区分]({paths[1]})

「大規模資本金層は利益率が改善し、小規模資本金層は悪化する」という複合見出しは、通常系列だけで{_count(book, 'V31-HEADLINE-2X2-REGULAR-ONLY', '回')}<!-- claim: V31-HEADLINE-2X2-REGULAR-ONLY -->、継続標本系列だけで{_count(book, 'V31-HEADLINE-2X2-CONTINUING-ONLY', '回')}<!-- claim: V31-HEADLINE-2X2-CONTINUING-ONLY -->、両方で{_count(book, 'V31-HEADLINE-2X2-BOTH', '回')}<!-- claim: V31-HEADLINE-2X2-BOTH -->成立し、どちらでも成立しなかったのが{_count(book, 'V31-HEADLINE-2X2-NEITHER', '回')}<!-- claim: V31-HEADLINE-2X2-NEITHER -->だった。成立回数を系列別に足すと通常系列{_count(book, 'V31-HEADLINE-REGULAR-TOTAL', '回')}<!-- claim: V31-HEADLINE-REGULAR-TOTAL -->、継続標本系列{_count(book, 'V31-HEADLINE-CONTINUING-TOTAL', '回')}<!-- claim: V31-HEADLINE-CONTINUING-TOTAL -->となる。これは成立区分にみられる非対称の記述であり、通常系列の調査上の失敗を意味しない。

系列間でこの見出しの成立可否が違ったのは{supplemental_fraction}四半期<!-- claim: {SUPPLEMENTAL_CLAIM_ID} -->である。ただし、これは三つの条件を束ねた補足指標だ。異なる尺度を一つの複合数値へ混ぜず、条件を満たしたか否かだけを数えた。主結果はあくまで利益率方向そのものの{primary_fraction}<!-- claim: {PRIMARY_CLAIM_ID} -->である。

## 二つの頑健性確認

第一は公表値の丸めに対する感応度である。継続標本の売上高前年比と営業利益前年比の各公表値に±{_points(book, 'V31-ROUNDING-HALF-WIDTH', 2)}<!-- claim: V31-ROUNDING-HALF-WIDTH -->の区間を置き、両者の差の絶対値が{_points(book, 'V31-ROUNDING-AMBIGUITY-THRESHOLD', 1)}<!-- claim: V31-ROUNDING-AMBIGUITY-THRESHOLD -->以下なら、表示丸めだけでは方向を決められない扱いとした。該当は{_count(book, 'V31-ROUNDING-AMBIGUOUS-COUNT', '件')}<!-- claim: V31-ROUNDING-AMBIGUOUS-COUNT -->で、最小の判定余裕は{_value_text(book, 'V31-ROUNDING-MINIMUM-MARGIN')}の{_points(book, 'V31-ROUNDING-MINIMUM-MARGIN', 1)}<!-- claim: V31-ROUNDING-MINIMUM-MARGIN -->だった。これは表示丸めに限った確認であり、標本誤差は別途未定量である。

第二はdeadbandである。両系列の推定変化がともに±dの外側にある四半期だけを残した。単位は営業利益率の絶対ポイント差ではなく、売上高前年比と営業利益前年比から推定した利益率の相対変化率（％）である。

![deadband感応度]({paths[2]})

小規模資本金層は、{_deadband_summary(book, 'V31-DEADBAND-SMALL-D005')}<!-- claim: V31-DEADBAND-SMALL-D005 -->、{_deadband_summary(book, 'V31-DEADBAND-SMALL-D010')}<!-- claim: V31-DEADBAND-SMALL-D010 -->、{_deadband_summary(book, 'V31-DEADBAND-SMALL-D020')}<!-- claim: V31-DEADBAND-SMALL-D020 -->、{_deadband_summary(book, 'V31-DEADBAND-SMALL-D030')}<!-- claim: V31-DEADBAND-SMALL-D030 -->となった。最後の閾値では不一致率が小規模{_percent(book, 'V31-DEADBAND-SMALL-D030')}<!-- claim: V31-DEADBAND-SMALL-D030 -->、中間{_percent(book, 'V31-DEADBAND-MIDDLE-D030')}<!-- claim: V31-DEADBAND-MIDDLE-D030 -->、大規模{_percent(book, 'V31-DEADBAND-LARGE-D030')}<!-- claim: V31-DEADBAND-LARGE-D030 -->で、小規模側の食い違いが残る。閾値を動かしても階層差が消える形ではなかったが、閾値は分析者が置いた感応度設定である。

さらに、継続標本の営業利益増加率の絶対値が{_percent(book, 'V31-EXTREME-YOY-THRESHOLD', 0)}<!-- claim: V31-EXTREME-YOY-THRESHOLD -->を超えた{_count(book, 'V31-EXTREME-YOY-FLAGGED', '件')}<!-- claim: V31-EXTREME-YOY-FLAGGED -->へ機械的レビュー印を付けた。名称にかかわらず低ベースやゼロ近傍を示す証拠とは扱わず、その全てが方向不一致ではなかった。<!-- claim: V31-EXTREME-YOY-MISMATCH -->歴史窓の分母を{primary_periods}四半期<!-- claim: {PRIMARY_CLAIM_ID} -->に固定した帰属確認では、利益率方向{primary_fraction}<!-- claim: {PRIMARY_CLAIM_ID} -->と複合見出し{supplemental_fraction}<!-- claim: {SUPPLEMENTAL_CLAIM_ID} -->の件数は変わらない。これは分母を減らす完全ケース再推計ではない。

## 読み方の限界

継続標本は通常系列より標本数が小さく、営業利益・経常利益の標準誤差率が算出されていない。このため、ここで示した差について標本誤差を数値化して比較することはできない。丸め感応度で判定不能がなかったことと、未定量の標本誤差とは別問題である。

また、継続標本は固定された企業集合を無条件に追跡する資料ではない。回答の継続、企業の状態変化、集計対象の条件を踏まえる必要がある。通常系列はその時点の母集団を表すための推計であり、継続標本系列は継続回答企業の動きを確認する補助資料である。それぞれの目的が違う以上、系列間の食い違いを一方の欠陥へ置き換えない。

以上から公開記事で採用する主張は一つに限る。法人企業統計の利益率方向の食い違いは、観察した{primary_periods}四半期では小規模資本金層に集中していた。<!-- claim: {PRIMARY_CLAIM_ID} -->これは調査方式による因果を確定する結論ではなく、二つの系列を併記したときに見出しがどこで揺れやすいかを示す記述的な監査結果である。
"""
    audit = validate_article_note_v3_2(article, claims_v3_2)
    if not audit.passed:
        raise ValueError(f"article_note v3.2 validation failed: {audit.failed_check_ids}")
    return article


def _plain(markdown: str) -> str:
    return _HTML_COMMENT.sub("", markdown)


def _negative_context(sentence: str) -> bool:
    return bool(
        re.search(
            r"(?:ない|ではない|とはいえない|とはしない|呼ばない|扱わない|"
            r"意味しない|特定するものではない|確定する結論ではなく)",
            sentence,
        )
    )


def _forbidden_hits(text: str) -> list[str]:
    """Find affirmative prohibited claims without rejecting explicit caveats."""
    hits = [term for term in _BANNED_LITERAL_EXPRESSIONS if term in text]
    sentences = [part for part in re.split(r"[。！？\n]", text) if part]
    contextual_patterns = {
        "AFFIRMATIVE_TRUTH_OR_CORRECTNESS": r"(?:通常系列|継続標本(?:系列)?)[^。\n]{0,35}(?:が真実|が正解|が正しい|の方が正しい)",
        "DESIGN_CAUSAL_ASSERTION": r"調査(?:方式|設計|方法)[^。\n]{0,35}(?:が原因|で決まる|が決定)",
        "CENSUS_SAMPLE_DETERMINES": r"全数[^。\n]{0,15}標本[^。\n]{0,25}(?:で決まる|が決定)",
        "REGULAR_SERIES_FAULT": r"通常系列[^。\n]{0,35}(?:バイアス|誤報|過大推計|間違)",
    }
    for name, pattern in contextual_patterns.items():
        for sentence in sentences:
            if re.search(pattern, sentence) and not _negative_context(sentence):
                hits.append(name)
                break
    return sorted(set(hits))


def _normal_number(value: str) -> str:
    token = (
        value.replace(",", "")
        .replace("＋", "+")
        .replace("－", "-")
        .replace("−", "-")
        .replace("％", "%")
    )
    token = re.sub(r"\s+", "", token)
    match = re.match(r"[+\-±]?\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?", token)
    return match.group(0) if match else token


def _claim_allowed_numbers(row: pd.Series) -> set[str]:
    allowed: set[str] = set()
    claim_id = str(row.get("claim_id", ""))
    # Most displayed values must be derivable from numeric_value (plus its
    # declared rounding), numerator, or denominator.  Deadband thresholds and
    # the census boundary are definitional metadata stored in display fields,
    # so those two explicit claim families may contribute auxiliary numbers.
    if claim_id.startswith("V31-DEADBAND-") or claim_id == "V31-CENSUS-THRESHOLD":
        for field in ("display_value", "article_tokens"):
            value = row.get(field, "")
            if pd.isna(value):
                continue
            for match in _STATISTICAL_NUMBER.finditer(str(value)):
                allowed.add(_normal_number(match.group(0)))
    fraction_parts: list[str] = []
    for field in ("numerator", "denominator"):
        value = pd.to_numeric(pd.Series([row.get(field)]), errors="coerce").iloc[0]
        if not pd.isna(value):
            formatted = str(int(value)) if float(value).is_integer() else str(float(value))
            allowed.add(formatted)
            fraction_parts.append(formatted)
    if len(fraction_parts) == 2:
        allowed.add("/".join(fraction_parts))
    numeric = pd.to_numeric(pd.Series([row.get("numeric_value")]), errors="coerce").iloc[0]
    digits = pd.to_numeric(pd.Series([row.get("rounding_digits")]), errors="coerce").iloc[0]
    if not pd.isna(numeric):
        allowed.update(
            {
                str(float(numeric)).rstrip("0").rstrip("."),
                str(abs(float(numeric))).rstrip("0").rstrip("."),
            }
        )
        for count in ({int(digits)} if not pd.isna(digits) else {0, 1, 2}):
            allowed.add(f"{float(numeric):.{count}f}")
            allowed.add(f"{abs(float(numeric)):.{count}f}")
    return allowed


def _nearest_claim_on_line(article: str, start: int, end: int) -> str | None:
    line_start = article.rfind("\n", 0, start) + 1
    line_end = article.find("\n", end)
    if line_end < 0:
        line_end = len(article)
    line = article[line_start:line_end]
    relative_start = start - line_start
    relative_end = end - line_start
    markers = list(_CLAIM_MARKER.finditer(line))
    if not markers:
        return None
    following = [marker for marker in markers if marker.start() >= relative_end]
    if following:
        return min(following, key=lambda marker: marker.start() - relative_end).group(1)
    preceding = [marker for marker in markers if marker.end() <= relative_start]
    if preceding:
        return min(preceding, key=lambda marker: relative_start - marker.end()).group(1)
    return None


def _numeric_claim_audit(article: str, claims: pd.DataFrame) -> tuple[bool, str]:
    indexed = claims.set_index(claims["claim_id"].astype(str), drop=False)
    failures: list[str] = []
    image_spans = [match.span() for match in _FIGURE.finditer(article)]
    comment_spans = [match.span() for match in _HTML_COMMENT.finditer(article)]

    def inside(spans: Sequence[tuple[int, int]], offset: int) -> bool:
        return any(start <= offset < end for start, end in spans)

    # Every source line containing a digit needs at least one explicit owner.
    offset = 0
    for line_number, line in enumerate(article.splitlines(keepends=True), start=1):
        visible_line = _HTML_COMMENT.sub("", _FIGURE.sub("", line))
        if _ANY_DIGIT.search(visible_line) and not _CLAIM_MARKER.search(line):
            failures.append(f"UNMARKED_NUMERIC_LINE:{line_number}")
        offset += len(line)

    # Statistical values additionally have to match the nearest claim value.
    for match in _STATISTICAL_NUMBER.finditer(article):
        if inside(image_spans, match.start()) or inside(comment_spans, match.start()):
            continue
        shown = match.group(0)
        # Formal capital-bracket labels and survey-design boundaries are
        # metadata.  The numeric-line check still requires an explicit claim
        # owner, while observed values below remain subject to exact matching.
        if shown.strip().endswith(("万円", "億円")) and re.match(
            r"(?:以上|未満)", article[match.end() :]
        ):
            continue
        claim_id = _nearest_claim_on_line(article, match.start(), match.end())
        if claim_id is None:
            failures.append(f"UNLINKED:{shown}")
            continue
        if claim_id not in indexed.index:
            failures.append(f"UNKNOWN:{shown}:{claim_id}")
            continue
        claim = indexed.loc[claim_id]
        observed = _normal_number(shown)
        allowed = _claim_allowed_numbers(claim)
        if observed not in allowed and observed.lstrip("+-±") not in {
            token.lstrip("+-±") for token in allowed
        }:
            failures.append(f"VALUE_MISMATCH:{shown}:{claim_id}")
    return not failures, ";".join(failures) if failures else "all numeric lines and statistical values are claim-linked"


def validate_article_note_v3_2(
    article: str,
    claims_v3_2: pd.DataFrame,
) -> Stage5PublicationAudit:
    """Fail closed on v3.2 title, prose, units, figures, and claim lineage."""
    rows: list[dict[str, str]] = []
    try:
        _ClaimBook(claims_v3_2)
        claim_error = ""
    except ValueError as exc:
        claim_error = str(exc)
    _add(rows, "claims_v3_2_registry_valid", not claim_error, claim_error or "complete")

    plain = _plain(article)
    title_match = re.search(r"^#\s+(.+?)\s*$", plain, flags=re.MULTILINE)
    title = title_match.group(1).strip() if title_match else ""
    _add(
        rows,
        "article_title_exact_and_small_capital_v3_2",
        title == ARTICLE_TITLE_V3_2 and OLD_ARTICLE_TITLE_V3_1 not in plain,
        f"observed={title!r}",
    )
    visible_count = visible_article_character_count(article)
    _add(
        rows,
        "article_visible_character_count_2900_3300",
        2900 <= visible_count <= 3300,
        f"visible_characters={visible_count}",
    )
    origin_count = origin_section_character_count(article)
    _add(
        rows,
        "article_origin_section_180_250_characters",
        180 <= origin_count <= 250,
        f"origin_visible_characters={origin_count}",
    )
    _add(
        rows,
        "article_origin_precedes_comparison_method",
        0 <= plain.find("## 発端は2026年1～3月期") < plain.find("## 何を比べたのか"),
        "origin section must precede method section",
    )

    body = plain[title_match.end() :] if title_match else plain
    formal_index = body.find(FORMAL_SMALL_CAPITAL_NAME_V3_2)
    first_shorthand = body.find("小規模資本金層")
    _add(
        rows,
        "article_formal_small_capital_first_mention_v3_2",
        formal_index >= 0 and (first_shorthand < 0 or formal_index < first_shorthand),
        f"formal_index={formal_index}; shorthand_index={first_shorthand}",
    )
    origin_match = re.search(
        r"^## 発端は2026年1～3月期.*?\n(.*?)(?=^##\s)",
        article,
        flags=re.MULTILINE | re.DOTALL,
    )
    origin = _plain(origin_match.group(1)) if origin_match else ""
    origin_anchors = (
        FORMAL_SMALL_CAPITAL_NAME_V3_2,
        "売上高はいずれの系列でも増加",
        "営業利益の増減方向は通常系列で減少、継続標本系列で増加",
        "営業利益率の方向も低下と上昇に分かれた",
        "比較可能な過去",
        "四半期へ確認を広げた",
    )
    _add(
        rows,
        "article_origin_required_narrative",
        all(anchor in origin for anchor in origin_anchors),
        str([anchor for anchor in origin_anchors if anchor not in origin]),
    )
    for claim_id in V32_EXAMPLE_CLAIM_IDS:
        _add(
            rows,
            f"article_origin_claim_{claim_id.lower()}",
            _marker(claim_id) in origin_match.group(1) if origin_match else False,
            claim_id,
        )

    central = _CENTRAL_MARKER.findall(article)
    _add(
        rows,
        "article_exactly_one_primary_central_claim",
        central == [PRIMARY_CLAIM_ID],
        str(central),
    )
    figures = _FIGURE.findall(article)
    names = tuple(Path(path).name for path in figures)
    _add(
        rows,
        "article_exactly_three_relative_registered_figures",
        names == STAGE5_CHART_FILENAMES
        and all(not Path(path).is_absolute() for path in figures),
        str(figures),
    )
    forbidden = _forbidden_hits(plain)
    _add(rows, "article_no_affirmative_banned_expressions", not forbidden, str(forbidden))
    nonoperating = [term for term in _NONOPERATING_TERMS if term in plain]
    _add(rows, "article_no_nonoperating_or_new_topic", not nonoperating, str(nonoperating))
    required_design = (
        "単に同じ真値を異なる標本で測った二つの推計とは限らない",
        "標本の入れ替え",
        "継続回答法人への限定",
        "推計用乗率",
        "未回答補完",
        "企業の参入・退出",
        "母集団構成",
        "増資や減資によって同じ企業が資本金階層間を移る可能性",
        "調査設計と整合的",
        "どちらの系列も真実や正解とは呼ばない",
        "営業利益・経常利益の標準誤差率が算出されていない",
        "標本誤差は別途未定量",
    )
    _add(
        rows,
        "article_required_design_and_limit_caveats",
        all(term in plain for term in required_design),
        str([term for term in required_design if term not in plain]),
    )
    _add(
        rows,
        "article_deadband_unit_is_relative_percent",
        "売上高前年比と営業利益前年比から推定した利益率の相対変化率（％）" in plain
        and "単位は営業利益率の絶対ポイント差ではなく" in plain,
        "deadband is a relative change rate in percent",
    )
    _add(
        rows,
        "article_continuing_margin_direction_only",
        "継続標本では営業利益率水準が公表されていない" in plain
        and "上昇・低下の方向判定だけに限定" in plain
        and not re.search(
            r"継続標本[^。\n]{0,100}営業利益率[^。\n]{0,40}\d+(?:\.\d+)?(?:ポイント|pt)",
            plain,
        ),
        "no level-point change may be attributed to continuing sample",
    )
    markers = set(_CLAIM_MARKER.findall(article))
    known = set(claims_v3_2.get("claim_id", pd.Series(dtype=str)).astype(str))
    _add(
        rows,
        "article_claim_markers_registered",
        bool(markers) and markers <= known,
        f"unknown={sorted(markers - known)}",
    )
    number_ok, number_detail = _numeric_claim_audit(article, claims_v3_2)
    _add(rows, "article_all_numbers_claim_linked_and_matched", number_ok, number_detail)
    return _result(rows)


def render_article_note_public_v3_2(article_note: str) -> str:
    """Convert audited Markdown into clean note-posting Markdown."""
    rendered = _HTML_COMMENT.sub("", article_note)

    def replace_figure(match: re.Match[str]) -> str:
        filename = Path(match.group(1)).name
        if filename not in FIGURE_MARKERS_V3_2:
            raise ValueError(f"unregistered figure in article_note: {filename}")
        return FIGURE_MARKERS_V3_2[filename]

    rendered = _FIGURE.sub(replace_figure, rendered)
    lines = [re.sub(r"[ \t]{2,}", " ", line).strip() for line in rendered.splitlines()]
    rendered = "\n".join(lines)
    rendered = re.sub(r"\n{3,}", "\n\n", rendered).strip() + "\n"
    audit = validate_rendered_article_v3_2(rendered, article_note=article_note)
    if not audit.passed:
        raise ValueError(f"article_note_render v3.2 validation failed: {audit.failed_check_ids}")
    return rendered


def validate_rendered_article_v3_2(
    rendered: str,
    *,
    article_note: str | None = None,
) -> Stage5PublicationAudit:
    """Validate the note-ready render without requiring audit comments."""
    rows: list[dict[str, str]] = []
    comments = _HTML_COMMENT.findall(rendered)
    relative_images = [
        path for path in _FIGURE.findall(rendered) if not re.match(r"^[a-z]+://", path)
    ]
    _add(rows, "render_html_comment_count_zero", not comments, f"count={len(comments)}")
    _add(
        rows,
        "render_relative_image_link_count_zero",
        not relative_images,
        f"count={len(relative_images)}",
    )
    marker_counts = {marker: rendered.count(marker) for marker in FIGURE_MARKERS_V3_2.values()}
    _add(
        rows,
        "render_three_figure_markers_exactly_once",
        all(count == 1 for count in marker_counts.values()),
        str(marker_counts),
    )
    implementation_hits = [label for label in _IMPLEMENTATION_LABELS if label in rendered]
    _add(
        rows,
        "render_no_claim_ids_or_implementation_labels",
        not implementation_hits and not re.search(r"\bV3[12]-[A-Z0-9-]+\b", rendered),
        str(implementation_hits),
    )
    _add(
        rows,
        "render_whitespace_normalized",
        not re.search(r"[ \t]{2,}|\n{3,}|[ \t]+$", rendered, flags=re.MULTILINE),
        "no repeated horizontal spaces, triple blank lines, or trailing spaces",
    )
    title_match = re.search(r"^#\s+(.+?)\s*$", rendered, flags=re.MULTILINE)
    title = title_match.group(1).strip() if title_match else ""
    _add(rows, "render_title_exact_v3_2", title == ARTICLE_TITLE_V3_2, repr(title))
    _add(
        rows,
        "render_no_affirmative_banned_expressions",
        not _forbidden_hits(rendered),
        str(_forbidden_hits(rendered)),
    )
    if article_note is not None:
        expected = _HTML_COMMENT.sub("", article_note)
        expected = _FIGURE.sub(
            lambda match: FIGURE_MARKERS_V3_2[Path(match.group(1)).name], expected
        )
        expected_lines = [
            re.sub(r"[ \t]{2,}", " ", line).strip() for line in expected.splitlines()
        ]
        expected = re.sub(r"\n{3,}", "\n\n", "\n".join(expected_lines)).strip() + "\n"
        _add(
            rows,
            "render_is_normalized_projection_of_audit_article",
            rendered == expected,
            "only comments/images/whitespace may differ",
        )
        audit_headings = [
            heading.strip()
            for heading in re.findall(
                r"^#{1,6}\s+.+$", _HTML_COMMENT.sub("", article_note), re.MULTILINE
            )
        ]
        render_headings = [
            heading.strip()
            for heading in re.findall(r"^#{1,6}\s+.+$", rendered, re.MULTILINE)
        ]
        _add(
            rows,
            "render_heading_order_preserved",
            audit_headings == render_headings,
            f"audit={audit_headings}; render={render_headings}",
        )
    return _result(rows)


__all__ = [
    "ARTICLE_TITLE_V3_2",
    "DECISION_MARGIN_CLAIM_IDS",
    "FIGURE_MARKERS_V3_2",
    "FORMAL_SMALL_CAPITAL_NAME_V3_2",
    "OLD_ARTICLE_TITLE_V3_1",
    "PRIMARY_CLAIM_ID",
    "STAGE5_CHART_FILENAMES",
    "Stage5PublicationAudit",
    "SUPPLEMENTAL_CLAIM_ID",
    "V32_EXAMPLE_CLAIM_IDS",
    "origin_section_character_count",
    "render_article_note_public_v3_2",
    "render_article_note_v3_2",
    "validate_article_note_v3_2",
    "validate_rendered_article_v3_2",
    "visible_article_character_count",
    "visible_article_text",
]
