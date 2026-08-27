"""Fail-closed publication contracts for the 2026Q1 v3.1 release.

The module is deliberately independent from the Stage 3 implementation.  It
does not write artifacts and it never mutates the frozen ``outputs/2026Q1_v3``
tree.  A caller takes a SHA-256 snapshot before building v3.1 and supplies that
snapshot to :func:`audit_stage4_release` after the build.

Article numbers are owned by literal ``<!-- claim: CLAIM_ID -->`` markers on
the same source line.  This keeps the relationship inspectable in Markdown and
avoids fuzzy text or claim-ID matching.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


PRIMARY_CLAIM_ID = "V31-SMALL-MARGIN-DIRECTION-MISMATCH"
SUPPLEMENTAL_CLAIM_ID = "V31-COMPOSITE-HEADLINE-MISMATCH"

REQUIRED_TITLE = (
    "食い違いは小規模資本金層に集中していた"
    "――法人企業統計、二つの推計を41四半期並べる"
)
FORMAL_SMALL_CAPITAL_NAME = "資本金1千万円以上1億円未満層"

REQUIRED_STAGE4_CSV_FILENAMES = (
    "headline_2x2.csv",
    "mismatch_heatmap.csv",
    "rounding_sensitivity.csv",
    "deadband_sensitivity.csv",
    "claims_v3_1.csv",
)
REQUIRED_STAGE4_MARKDOWN_FILENAMES = (
    "article_note.md",
    "audit_v3_1.md",
)
REQUIRED_STAGE4_CHART_FILENAMES = (
    "mismatch_heatmap.png",
    "headline_2x2.png",
    "deadband_sensitivity.png",
)

FORBIDDEN_LITERAL_TERMS = (
    "標本を替えると",
    "継続標本の方が正しい",
    "同一企業パネル",
    "統計的に有意",
    "有意",
    "中小企業だけ",
    "事前確率",
    "誤報率",
    "バイアス率",
    "バイアス",
    "誤報",
    "過大推計",
    "確実",
    "調査方式が原因",
    "全数調査か標本調査かで決まる",
)

NONOPERATING_TERMS = (
    "営業外損益",
    "営業利益外差額",
    "受取利息等",
    "その他の営業外収益",
    "支払利息等",
    "その他の営業外費用",
    "nonoperating",
    "non_operating",
)

REQUIRED_CLAIM_COLUMNS = frozenset(
    {
        "claim_id",
        "verification_status",
        "article_use",
        "display_value",
    }
)

_CLAIM_MARKER = re.compile(r"<!--\s*claim:\s*([^\s]+)\s*-->")
_CENTRAL_MARKER = re.compile(r"<!--\s*central-claim:\s*([^\s]+)\s*-->")
_FIGURE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_HTML_COMMENT = re.compile(r"<!--.*?-->", flags=re.DOTALL)

# Statistical values, rather than table/section numbers and file-name version
# numbers.  Ratios are captured without requiring a unit; scalar values require
# a statistical unit.  2026Q1 and 2018Q2 are therefore metadata, not claims.
_STATISTICAL_NUMBER = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:[+\-−±]?\d[\d,]*(?:\.\d+)?/\d[\d,]*(?:\.\d+)?"
    r"(?:\s*(?:％|%|pt|ポイント|件|回|四半期))?"
    r"|[+\-−±]?\d[\d,]*(?:\.\d+)?\s*"
    r"(?:％|%|pt|ポイント|件|回|四半期|万円|億円|兆円))"
)


@dataclass(frozen=True)
class Stage4AuditResult:
    """One immutable audit result; ``PASS`` means every row passed."""

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


def _make_result(rows: Sequence[dict[str, str]]) -> Stage4AuditResult:
    checks = pd.DataFrame(rows, columns=["check_id", "status", "detail"])
    status = "PASS" if not checks.empty and checks["status"].eq("PASS").all() else "FAIL"
    return Stage4AuditResult(status=status, checks=checks)


def _row(rows: list[dict[str, str]], check_id: str, passed: bool, detail: str) -> None:
    rows.append(
        {
            "check_id": check_id,
            "status": "PASS" if bool(passed) else "FAIL",
            "detail": str(detail),
        }
    )


def combine_stage4_audits(*audits: Stage4AuditResult) -> Stage4AuditResult:
    """Combine checks without allowing a caller to override the final status."""
    frames = [audit.checks for audit in audits if not audit.checks.empty]
    if not frames:
        return _make_result([])
    checks = pd.concat(frames, ignore_index=True)
    duplicated = checks["check_id"].duplicated(keep=False)
    if duplicated.any():
        duplicate_ids = sorted(checks.loc[duplicated, "check_id"].unique())
        checks = pd.concat(
            [
                checks,
                pd.DataFrame(
                    [
                        {
                            "check_id": "audit_check_ids_unique",
                            "status": "FAIL",
                            "detail": f"duplicate check IDs: {duplicate_ids}",
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
    return Stage4AuditResult(
        status="PASS" if checks["status"].eq("PASS").all() else "FAIL",
        checks=checks,
    )


def _strict_bool(value: object) -> bool | None:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)) and int(value) in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normal = value.strip().lower()
        if normal in {"true", "1"}:
            return True
        if normal in {"false", "0"}:
            return False
    return None


def audit_stage4_claims(claims: pd.DataFrame) -> Stage4AuditResult:
    """Validate the explicit v3.1 claims registry and its two anchor claims."""
    rows: list[dict[str, str]] = []
    missing = sorted(REQUIRED_CLAIM_COLUMNS - set(claims.columns))
    _row(rows, "claims_required_columns", not missing, f"missing={missing}")
    if missing:
        return _make_result(rows)

    ids = claims["claim_id"].fillna("").astype(str)
    unique_nonempty = ids.ne("").all() and not ids.duplicated().any()
    _row(rows, "claims_ids_unique_and_nonempty", unique_nonempty, f"rows={len(ids)}")
    _row(
        rows,
        "claims_all_verified",
        claims["verification_status"].astype(str).eq("PASS").all(),
        "every registry row must have verification_status=PASS",
    )
    article_flags = claims["article_use"].map(_strict_bool)
    _row(
        rows,
        "claims_article_use_is_boolean",
        article_flags.notna().all(),
        "article_use accepts only true/false or 1/0",
    )
    _row(
        rows,
        "claims_display_values_nonempty",
        claims["display_value"].fillna("").astype(str).str.strip().ne("").all(),
        "all claims require a human-inspectable display_value",
    )
    required_ids = {PRIMARY_CLAIM_ID, SUPPLEMENTAL_CLAIM_ID}
    observed = set(ids)
    _row(
        rows,
        "claims_primary_and_supplemental_present",
        required_ids <= observed,
        f"missing={sorted(required_ids - observed)}",
    )
    nonop_ids = sorted(identifier for identifier in observed if "NONOP" in identifier.upper())
    _row(
        rows,
        "claims_no_nonoperating_candidate",
        not nonop_ids,
        f"nonoperating claim IDs={nonop_ids}",
    )

    if required_ids <= observed and unique_nonempty:
        indexed = claims.set_index("claim_id")
        expected = {
            PRIMARY_CLAIM_ID: (16, 41, "PRIMARY"),
            SUPPLEMENTAL_CLAIM_ID: (11, 41, "SUPPLEMENTAL"),
        }
        bad: list[str] = []
        for claim_id, (numerator, denominator, role) in expected.items():
            claim = indexed.loc[claim_id]
            observed_num = pd.to_numeric(
                pd.Series([claim.get("numerator")]), errors="coerce"
            ).iloc[0]
            observed_den = pd.to_numeric(
                pd.Series([claim.get("denominator")]), errors="coerce"
            ).iloc[0]
            article_use = _strict_bool(claim["article_use"])
            role_ok = (
                "claim_role" not in claims.columns
                or str(claim.get("claim_role", "")).upper() == role
            )
            if (
                pd.isna(observed_num)
                or pd.isna(observed_den)
                or int(float(observed_num)) != numerator
                or int(float(observed_den)) != denominator
                or article_use is not True
                or not role_ok
            ):
                bad.append(claim_id)
        _row(
            rows,
            "claims_anchor_values_and_roles",
            not bad,
            f"invalid={bad}; expected primary=16/41, supplemental=11/41",
        )
    else:
        _row(
            rows,
            "claims_anchor_values_and_roles",
            False,
            "anchor claims unavailable or duplicate",
        )
    return _make_result(rows)


def _strip_comments(text: str) -> str:
    return _HTML_COMMENT.sub("", str(text))


def visible_article_text(article: str) -> str:
    """Approximate rendered prose for the 2,500--3,500 visible-char gate.

    HTML claim markers, image syntax/paths, fenced-code delimiters, Markdown
    control punctuation, and whitespace are excluded.  Link labels and ordinary
    prose punctuation remain because a reader sees them.
    """
    text = _strip_comments(article)
    text = _FIGURE.sub("", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^```.*?$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\|?\s*:?-{3,}:?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s{0,3}(?:#{1,6}|>|[-+*]|\d+[.)])\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`~|]", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", "", text)


def visible_article_character_count(article: str) -> int:
    return len(visible_article_text(article))


def _normal_number(value: str) -> str:
    token = value.replace(",", "").replace("−", "-").replace("％", "%")
    token = re.sub(r"\s+", "", token)
    match = re.match(r"[+\-±]?\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?", token)
    return match.group(0) if match else token


def _claim_allowed_numbers(row: pd.Series) -> set[str]:
    allowed: set[str] = set()
    for field in ("display_value", "article_tokens"):
        value = row.get(field, "")
        if pd.isna(value):
            continue
        for match in _STATISTICAL_NUMBER.finditer(str(value)):
            allowed.add(_normal_number(match.group(0)))
        if field == "article_tokens":
            for token in str(value).split(";"):
                if re.search(r"\d", token):
                    allowed.add(_normal_number(token))
    for field in ("numerator", "denominator"):
        value = pd.to_numeric(pd.Series([row.get(field)]), errors="coerce").iloc[0]
        if not pd.isna(value):
            allowed.add(str(int(float(value))) if float(value).is_integer() else str(float(value)))
    numeric = pd.to_numeric(pd.Series([row.get("numeric_value")]), errors="coerce").iloc[0]
    digits = pd.to_numeric(pd.Series([row.get("rounding_digits")]), errors="coerce").iloc[0]
    if not pd.isna(numeric):
        allowed.add(str(float(numeric)).rstrip("0").rstrip("."))
        allowed.add(str(abs(float(numeric))).rstrip("0").rstrip("."))
        if not pd.isna(digits):
            rounded = round(float(numeric), int(float(digits)))
            allowed.add(f"{rounded:.{int(float(digits))}f}")
            allowed.add(f"{abs(rounded):.{int(float(digits))}f}")
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


def _audit_numeric_claim_links(article: str, claims: pd.DataFrame) -> tuple[bool, str]:
    if "claim_id" not in claims.columns or claims["claim_id"].astype(str).duplicated().any():
        return False, "claim registry lacks unique claim_id"
    indexed = claims.set_index(claims["claim_id"].astype(str), drop=False)
    failures: list[str] = []
    for match in _STATISTICAL_NUMBER.finditer(article):
        # Ignore values inside HTML comments, including versioned claim IDs.
        prefix = article[: match.start()]
        if prefix.rfind("<!--") > prefix.rfind("-->"):
            continue
        # Capital thresholds are definitional metadata rather than observed
        # results.  Their official first-mention wording is audited separately.
        if match.group(0).strip().endswith(("万円", "億円")) and re.match(
            r"(?:以上|未満)", article[match.end() :]
        ):
            continue
        claim_id = _nearest_claim_on_line(article, match.start(), match.end())
        shown = match.group(0)
        if claim_id is None:
            failures.append(f"UNLINKED:{shown}")
            continue
        if claim_id not in indexed.index:
            failures.append(f"UNKNOWN:{shown}:{claim_id}")
            continue
        claim = indexed.loc[claim_id]
        if str(claim["verification_status"]) != "PASS" or _strict_bool(
            claim["article_use"]
        ) is not True:
            failures.append(f"NONPUBLIC_OR_NONPASS:{shown}:{claim_id}")
            continue
        observed = _normal_number(shown)
        allowed = _claim_allowed_numbers(claim)
        if observed not in allowed and observed.lstrip("+−-±") not in {
            token.lstrip("+−-±") for token in allowed
        }:
            failures.append(f"VALUE_MISMATCH:{shown}:{claim_id}")
    return not failures, ";".join(failures) if failures else "all statistical values explicitly linked"


def _paragraphs(article: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", _strip_comments(article)) if part.strip()]


def _contains_negative_truth_caveat(text: str) -> bool:
    return bool(
        re.search(
            r"どちらの系列も[^。\n]{0,50}真実[^。\n]{0,30}正解"
            r"[^。\n]{0,30}(?:呼ばない|扱わない|位置づけない|とはしない)",
            text,
        )
        or re.search(
            r"どちらの系列も[^。\n]{0,50}正解[^。\n]{0,30}真実"
            r"[^。\n]{0,30}(?:呼ばない|扱わない|位置づけない|とはしない)",
            text,
        )
    )


def audit_stage4_article(article: str, claims: pd.DataFrame) -> Stage4AuditResult:
    """Audit the single-claim public article against v3.1 wording contracts."""
    rows: list[dict[str, str]] = []
    plain = _strip_comments(article)
    title_match = re.search(r"^#\s+(.+?)\s*$", plain, flags=re.MULTILINE)
    title = title_match.group(1).strip() if title_match else ""
    _row(
        rows,
        "article_title_exact_and_small_capital",
        title == REQUIRED_TITLE and "中小企業" not in title,
        f"observed={title!r}",
    )

    visible_count = visible_article_character_count(article)
    _row(
        rows,
        "article_visible_character_count_2500_3500",
        2500 <= visible_count <= 3500,
        f"visible_characters={visible_count}",
    )

    central = _CENTRAL_MARKER.findall(article)
    _row(
        rows,
        "article_exactly_one_primary_central_claim",
        central == [PRIMARY_CLAIM_ID],
        f"central_claims={central}",
    )
    figures = _FIGURE.findall(article)
    figure_names = [Path(path).name for path in figures]
    _row(
        rows,
        "article_one_to_three_registered_figures",
        1 <= len(figures) <= 3
        and len(figure_names) == len(set(figure_names))
        and set(figure_names) <= set(REQUIRED_STAGE4_CHART_FILENAMES),
        f"figure_count={len(figures)}; names={figure_names}",
    )

    forbidden = [term for term in FORBIDDEN_LITERAL_TERMS if term in plain]
    causal_patterns = {
        "NORMAL_SERIES_BIAS_OR_MISREPORT": r"通常系列[^。\n]{0,35}(?:バイアス|誤報|過大推計)",
        "DESIGN_CAUSES_RESULT": r"調査(?:方式|設計|方法)[^。\n]{0,25}(?:が原因|で決まる|が決定)",
        "CENSUS_OR_SAMPLE_DETERMINES": r"全数調査か標本調査かで決まる",
        "AFFIRMATIVE_SERIES_TRUTH": r"(?:通常系列|継続標本(?:系列)?)[^。\n]{0,30}(?:が真実|が正解|が正しい|の方が正しい)",
    }
    causal_hits = [name for name, pattern in causal_patterns.items() if re.search(pattern, plain)]
    _row(
        rows,
        "article_forbidden_wording_and_overclaims",
        not forbidden and not causal_hits,
        f"literal={forbidden}; causal={causal_hits}",
    )

    nonoperating = [term for term in NONOPERATING_TERMS if term in plain]
    _row(
        rows,
        "article_no_nonoperating_content",
        not nonoperating,
        f"hits={nonoperating}",
    )

    body = plain[title_match.end() :] if title_match else plain
    formal_index = body.find(FORMAL_SMALL_CAPITAL_NAME)
    before_formal = body[:formal_index] if formal_index >= 0 else body
    early_shorthand = any(
        term in before_formal for term in ("小規模資本金層", "中小企業", "1億円未満層")
    )
    _row(
        rows,
        "article_formal_small_capital_first_mention",
        formal_index >= 0 and not early_shorthand,
        f"formal_index={formal_index}; early_shorthand={early_shorthand}",
    )

    linked_claim_ids = set(_CLAIM_MARKER.findall(article))
    known_claim_ids = (
        set(claims["claim_id"].fillna("").astype(str))
        if "claim_id" in claims.columns
        else set()
    )
    referenced_rows = (
        claims.loc[claims["claim_id"].astype(str).isin(linked_claim_ids)]
        if "claim_id" in claims.columns
        else pd.DataFrame()
    )
    referenced_registry_ok = (
        bool(linked_claim_ids)
        and linked_claim_ids <= known_claim_ids
        and len(referenced_rows) == len(linked_claim_ids)
        and referenced_rows["verification_status"].astype(str).eq("PASS").all()
        and referenced_rows["article_use"].map(_strict_bool).eq(True).all()  # noqa: E712
    )
    _row(
        rows,
        "article_claim_references_explicit_and_verified",
        referenced_registry_ok,
        f"unknown={sorted(linked_claim_ids - known_claim_ids)}",
    )
    _row(
        rows,
        "article_primary_and_supplemental_claims_linked",
        {PRIMARY_CLAIM_ID, SUPPLEMENTAL_CLAIM_ID} <= linked_claim_ids,
        f"missing={sorted({PRIMARY_CLAIM_ID, SUPPLEMENTAL_CLAIM_ID} - linked_claim_ids)}",
    )
    primary_index = plain.find("16/41")
    supplemental_index = plain.find("11/41")
    supplement_near = (
        plain[max(0, supplemental_index - 160) : supplemental_index + 160]
        if supplemental_index >= 0
        else ""
    )
    _row(
        rows,
        "article_primary_16_41_supplemental_11_41",
        primary_index >= 0
        and supplemental_index > primary_index
        and "補足" in supplement_near,
        f"primary_index={primary_index}; supplemental_index={supplemental_index}",
    )

    exploratory_paragraphs = [
        paragraph
        for paragraph in _paragraphs(article)
        if "16/41" in paragraph and "11/41" in paragraph
    ]
    exploratory_ok = any(
        "いずれも" in paragraph
        and "2026Q1" in paragraph
        and re.search(r"結果を(?:見た|確認した)後", paragraph)
        and re.search(r"過去(?:へ|に)適用", paragraph)
        and "探索的バックテスト" in paragraph
        for paragraph in exploratory_paragraphs
    )
    _row(
        rows,
        "article_both_backtests_disclosed_post_hoc_exploratory",
        exploratory_ok,
        "16/41 and 11/41 must share an explicit post-2026Q1 exploratory-backtest disclosure",
    )

    asymmetry = bool(
        re.search(r"通常系列[^。\n]{0,50}10回", plain)
        and re.search(r"継続標本(?:系列)?[^。\n]{0,50}3回", plain)
    )
    _row(
        rows,
        "article_headline_support_asymmetry_10_vs_3",
        asymmetry,
        "requires descriptive counts without probability language",
    )

    design_caveat_terms = {
        "same_truth_not_assumed": bool(
            re.search(r"単に同じ真値を異なる標本で測った[^。\n]{0,25}とは限らない", plain)
        ),
        "entry_exit": bool(re.search(r"参入[・/]退出", plain)),
        "response_continuity": "回答継続条件" in plain,
        "weight": "推計用乗率" in plain,
        "imputation": "未回答補完" in plain,
        "population": "母集団構成" in plain,
        "consistent_not_causal": "調査設計と整合的" in plain,
    }
    _row(
        rows,
        "article_required_design_caveats",
        all(design_caveat_terms.values()),
        str(design_caveat_terms),
    )

    continuing_direction = bool(
        re.search(r"継続標本(?:系列)?[^\n]{0,80}利益率水準[^\n]{0,35}公表.{0,8}ない", plain)
        and re.search(r"継続標本(?:系列)?[^\n]{0,220}方向(?:判定|だけ|に限定)", plain)
    )
    continuing_pp_sentences = [
        sentence
        for sentence in re.split(r"[。！？\n]", plain)
        if "継続標本" in sentence
        and "利益率" in sentence
        and re.search(r"[+\-−]?\d+(?:\.\d+)?\s*(?:pt|ポイント)", sentence)
    ]
    _row(
        rows,
        "article_continuing_margin_direction_only_no_pp",
        continuing_direction and not continuing_pp_sentences,
        f"numeric_pp_sentences={continuing_pp_sentences}",
    )

    deadband_unit = bool(
        re.search(
            r"売上高前年比と営業利益前年比から推定した"
            r"[^。\n]{0,20}利益率の相対変化率（(?:％|%)）",
            plain,
        )
    )
    _row(
        rows,
        "article_deadband_unit_is_relative_rate_pct",
        deadband_unit,
        "deadband must not be described as an absolute margin-point difference",
    )

    se_caveats = {
        "small_sample": bool(
            re.search(r"継続標本[^。\n]{0,45}標本数[^。\n]{0,15}小さ", plain)
        ),
        "profit_se": bool(
            re.search(
                r"営業利益[^。\n]{0,25}経常利益[^。\n]{0,35}標準誤差率"
                r"[^。\n]{0,20}(?:算出されていない|算出していない|未算出)",
                plain,
            )
        ),
        "sample_error_unquantified": bool(
            re.search(r"標本誤差[^。\n]{0,20}(?:別途)?未定量", plain)
        ),
    }
    _row(
        rows,
        "article_sample_and_standard_error_caveats",
        all(se_caveats.values()),
        str(se_caveats),
    )

    _row(
        rows,
        "article_neither_series_called_truth_or_correct",
        _contains_negative_truth_caveat(plain)
        and "継続標本の方が正しい" not in plain,
        "requires an explicit non-ranking caveat",
    )

    extreme_sentences = [
        sentence
        for sentence in re.split(r"[。！？\n]", plain)
        if "EXTREME_YOY_RATE_GT_100" in sentence
    ]
    extreme_neutral = any(
        "低ベース" in sentence
        and "ゼロ近傍" in sentence
        and re.search(
            r"(?:断定しない|断定できない|意味しない|を示さない|証拠とは扱わない)",
            sentence,
        )
        for sentence in extreme_sentences
    )
    _row(
        rows,
        "article_extreme_yoy_flag_not_interpreted_as_base",
        extreme_neutral,
        f"sentences={extreme_sentences}",
    )

    confound_rejection = any(
        "大企業は変化幅が大きいから一致する" in paragraph
        and re.search(r"(?:成立しない|支持されない)", paragraph)
        for paragraph in _paragraphs(article)
    )
    _row(
        rows,
        "article_change_magnitude_confound_rejected_descriptively",
        confound_rejection,
        "the specified alternative explanation must be checked, not causally resolved",
    )

    number_links_ok, number_detail = _audit_numeric_claim_links(article, claims)
    _row(
        rows,
        "article_all_statistical_numbers_claim_linked",
        number_links_ok,
        number_detail,
    )
    return _make_result(rows)


def _required_columns_check(
    rows: list[dict[str, str]], frame: pd.DataFrame, name: str, required: set[str]
) -> bool:
    missing = sorted(required - set(frame.columns))
    _row(rows, f"data_{name}_required_columns", not missing, f"missing={missing}")
    return not missing


def audit_stage4_dataframes(
    *,
    headline_2x2: pd.DataFrame,
    mismatch_heatmap: pd.DataFrame,
    rounding_sensitivity: pd.DataFrame,
    deadband_sensitivity: pd.DataFrame,
) -> Stage4AuditResult:
    """Validate the requested canonical robustness outputs and annotations."""
    rows: list[dict[str, str]] = []

    h_required = {
        "regular_headline_supported",
        "continuing_headline_supported",
        "quarter_count",
        "denominator_quarters",
        "regular_supported_total",
        "continuing_supported_total",
        "exploratory_backtest_status",
    }
    if _required_columns_check(rows, headline_2x2, "headline_2x2", h_required):
        observed_cells: dict[tuple[bool, bool], int] = {}
        bad_bool = False
        for row in headline_2x2.itertuples(index=False):
            regular = _strict_bool(row.regular_headline_supported)
            continuing = _strict_bool(row.continuing_headline_supported)
            if regular is None or continuing is None:
                bad_bool = True
                continue
            observed_cells[(regular, continuing)] = int(row.quarter_count)
        expected_cells = {(True, False): 9, (False, True): 2, (True, True): 1, (False, False): 29}
        totals_ok = (
            len(headline_2x2) == 4
            and pd.to_numeric(headline_2x2["quarter_count"], errors="coerce").sum() == 41
            and pd.to_numeric(headline_2x2["denominator_quarters"], errors="coerce").eq(41).all()
            and pd.to_numeric(headline_2x2["regular_supported_total"], errors="coerce").eq(10).all()
            and pd.to_numeric(headline_2x2["continuing_supported_total"], errors="coerce").eq(3).all()
        )
        exploratory = headline_2x2["exploratory_backtest_status"].astype(str).str.contains(
            "EXPLORATORY", case=False
        ).all()
        _row(
            rows,
            "data_headline_2x2_canonical",
            not bad_bool and observed_cells == expected_cells and totals_ok and exploratory,
            f"observed={observed_cells}; totals_ok={totals_ok}; exploratory={exploratory}",
        )

    heat_required = {
        "capital_code",
        "metric_id",
        "mismatch_count",
        "comparable_quarters",
        "mismatch_rate_pct",
        "census_sample_design_ja",
        "census_threshold_yen",
        "census_threshold_label_ja",
        "rotation_status",
        "rotation_note_ja",
        "design_interpretation_note",
        "continuing_decision_margin_abs_gap_median_pct",
        "cross_series_growth_gap_divergence_median_pp",
    }
    if _required_columns_check(rows, mismatch_heatmap, "mismatch_heatmap", heat_required):
        work = mismatch_heatmap.copy()
        work["capital_code"] = work["capital_code"].astype(str)
        metric_alias = {
            "operating_margin_direction_proxy": "margin",
            "relative_margin_change_direction": "margin",
            "relative_margin_direction": "margin",
            "operating_margin_direction": "margin",
            "operating_profit": "operating_profit",
            "operating_profit_yoy": "operating_profit",
            "sales": "sales",
            "sales_yoy": "sales",
        }
        work["metric_key"] = work["metric_id"].astype(str).map(metric_alias)
        expected_heat = {
            ("19", "margin"): (16, 41, 39.0),
            ("24", "margin"): (6, 41, 14.6),
            ("25", "margin"): (0, 41, 0.0),
            ("19", "operating_profit"): (13, 41, 31.7),
            ("24", "operating_profit"): (4, 41, 9.8),
            ("25", "operating_profit"): (0, 41, 0.0),
            ("19", "sales"): (6, 40, 15.0),
            ("24", "sales"): (7, 41, 17.1),
            ("25", "sales"): (1, 41, 2.4),
        }
        observed_heat: dict[tuple[str, str], tuple[int, int, float]] = {}
        for record in work.itertuples(index=False):
            if pd.notna(record.metric_key):
                observed_heat[(str(record.capital_code), str(record.metric_key))] = (
                    int(record.mismatch_count),
                    int(record.comparable_quarters),
                    round(float(record.mismatch_rate_pct), 1),
                )
        _row(
            rows,
            "data_mismatch_heatmap_canonical",
            observed_heat == expected_heat and len(work) == 9,
            f"observed={observed_heat}",
        )
        annotation_cols = [
            "census_sample_design_ja",
            "census_threshold_label_ja",
            "rotation_status",
            "rotation_note_ja",
            "design_interpretation_note",
        ]
        annotations = all(
            work[column].fillna("").astype(str).str.strip().ne("").all()
            for column in annotation_cols
        )
        threshold = pd.to_numeric(work["census_threshold_yen"], errors="coerce")
        notes = "\n".join(work["design_interpretation_note"].astype(str).unique())
        _row(
            rows,
            "data_heatmap_design_and_rotation_annotations",
            annotations
            and threshold.eq(500_000_000).all()
            and work["census_threshold_label_ja"].astype(str).str.contains("5億円").all()
            and "調査設計と整合的" in notes
            and bool(re.search(r"(?:原因|決まる)[^。\n]{0,35}(?:示さない|断定しない)", notes)),
            f"annotations={annotations}; threshold_values={sorted(threshold.dropna().unique())}",
        )
        medians = {
            "19": (11.3, 11.21),
            "24": (9.0, 4.07),
            "25": (8.5, 1.05),
        }
        bad_medians: list[str] = []
        for code, expected in medians.items():
            group = work.loc[work["capital_code"].eq(code)]
            decision = pd.to_numeric(
                group["continuing_decision_margin_abs_gap_median_pct"], errors="coerce"
            ).dropna().unique()
            divergence = pd.to_numeric(
                group["cross_series_growth_gap_divergence_median_pp"], errors="coerce"
            ).dropna().unique()
            if (
                len(decision) != 1
                or len(divergence) != 1
                or not np.isclose(decision[0], expected[0], atol=0.051)
                or not np.isclose(divergence[0], expected[1], atol=0.006)
            ):
                bad_medians.append(code)
        _row(
            rows,
            "data_decision_margin_and_series_divergence_medians",
            not bad_medians,
            f"invalid_capital_codes={bad_medians}",
        )

    rounding_required = {
        "period_code",
        "capital_code",
        "absolute_decision_margin_pp",
        "rounding_direction_status",
        "is_ambiguous_by_rounding",
        "rounding_half_width_pp",
        "ambiguity_threshold_pp",
        "sample_error_status",
        "extreme_yoy_rate_gt_100",
        "mechanical_flag",
        "relative_margin_direction_reversal",
        "headline_reversal",
        "sensitivity_method",
    }
    if _required_columns_check(rows, rounding_sensitivity, "rounding_sensitivity", rounding_required):
        ambiguous = rounding_sensitivity["is_ambiguous_by_rounding"].map(_strict_bool)
        margins = pd.to_numeric(
            rounding_sensitivity["absolute_decision_margin_pp"], errors="coerce"
        )
        minimum = margins.min()
        minimum_periods = set(
            rounding_sensitivity.loc[np.isclose(margins, minimum), "period_code"].astype(str)
        )
        status_ok = not rounding_sensitivity["rounding_direction_status"].astype(str).eq(
            "NOT_DETERMINED_BY_ROUNDING"
        ).any()
        _row(
            rows,
            "data_rounding_sensitivity_canonical",
            len(rounding_sensitivity) == 41
            and ambiguous.notna().all()
            and not ambiguous.fillna(True).any()
            and np.isclose(minimum, 0.5, atol=1e-9)
            and bool({"20182", "2018Q2"} & minimum_periods)
            and pd.to_numeric(rounding_sensitivity["rounding_half_width_pp"], errors="coerce").eq(0.05).all()
            and pd.to_numeric(rounding_sensitivity["ambiguity_threshold_pp"], errors="coerce").eq(0.1).all()
            and status_ok,
            f"rows={len(rounding_sensitivity)}; ambiguous={ambiguous.fillna(True).sum()}; min={minimum}; periods={minimum_periods}",
        )
        sample_status = rounding_sensitivity["sample_error_status"].astype(str)
        _row(
            rows,
            "data_rounding_separate_from_unquantified_sample_error",
            sample_status.str.contains("NOT", case=False).all()
            and sample_status.str.contains("QUANT", case=False).all(),
            f"statuses={sorted(sample_status.unique())}",
        )
        extreme = rounding_sensitivity["extreme_yoy_rate_gt_100"].map(_strict_bool)
        flagged = rounding_sensitivity.loc[extreme.eq(True)].copy()  # noqa: E712
        flagged_margin = flagged["relative_margin_direction_reversal"].map(_strict_bool)
        flagged_headline = flagged["headline_reversal"].map(_strict_bool)
        flag_names = flagged["mechanical_flag"].astype(str)
        methods = flagged["sensitivity_method"].astype(str)
        _row(
            rows,
            "data_extreme_yoy_mechanical_review_fixed_window",
            extreme.notna().all()
            and int(extreme.sum()) == 3
            and len(flagged) == 3
            and flagged_margin.eq(False).all()  # noqa: E712
            and flagged_headline.eq(False).all()  # noqa: E712
            and flag_names.eq("NEAR_ZERO_BASE").all()
            and methods.eq("FIXED_41_QUARTER_EVENT_ATTRIBUTION_NOT_ROW_DELETION").all(),
            (
                f"flagged={len(flagged)}; margin_reversals={int(flagged_margin.eq(True).sum())}; "
                f"headline_reversals={int(flagged_headline.eq(True).sum())}; "
                f"methods={sorted(methods.unique())}"
            ),
        )

    deadband_required = {
        "capital_code",
        "deadband_pct",
        "retained_quarters",
        "mismatch_count",
        "mismatch_rate_pct",
        "deadband_rule",
        "unit",
        "sample_error_status",
    }
    if _required_columns_check(rows, deadband_sensitivity, "deadband_sensitivity", deadband_required):
        dead = deadband_sensitivity.copy()
        dead["capital_code"] = dead["capital_code"].astype(str)
        dead["deadband_pct"] = pd.to_numeric(dead["deadband_pct"], errors="coerce")
        expected_small = {0.5: (15, 39), 1.0: (14, 37), 2.0: (10, 33), 3.0: (8, 29)}
        observed_small = {
            float(record.deadband_pct): (int(record.mismatch_count), int(record.retained_quarters))
            for record in dead.loc[dead["capital_code"].eq("19")].itertuples(index=False)
        }
        d3 = dead.loc[np.isclose(dead["deadband_pct"], 3.0)].set_index("capital_code")
        d3_rates_ok = (
            {"19", "24", "25"} <= set(d3.index)
            and np.isclose(float(d3.loc["19", "mismatch_rate_pct"]), 8 / 29 * 100, atol=0.051)
            and np.isclose(float(d3.loc["24", "mismatch_rate_pct"]), 0.0, atol=0.001)
            and np.isclose(float(d3.loc["25", "mismatch_rate_pct"]), 0.0, atol=0.001)
        )
        units = dead["unit"].astype(str)
        unit_ok = units.str.contains("relative|相対", case=False, regex=True).all() and units.str.contains(
            "%|％", regex=True
        ).all()
        _row(
            rows,
            "data_deadband_sensitivity_canonical",
            len(dead) == 12 and observed_small == expected_small and d3_rates_ok,
            f"small={observed_small}; d3_rates_ok={d3_rates_ok}",
        )
        _row(
            rows,
            "data_deadband_unit_relative_rate_pct",
            unit_ok,
            f"units={sorted(units.unique())}",
        )
    return _make_result(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_sha256_tree(root: str | Path) -> dict[str, str]:
    """Return SHA-256 for every regular file under a frozen tree."""
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise FileNotFoundError(root_path)
    result: dict[str, str] = {}
    for path in sorted(root_path.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlink is not allowed in a frozen tree: {path}")
        if path.is_file():
            result[path.relative_to(root_path).as_posix()] = _sha256(path)
    if not result:
        raise ValueError(f"frozen tree has no files: {root_path}")
    return result


def audit_frozen_v3_sha256(
    frozen_v3_dir: str | Path,
    expected_sha256: Mapping[str, str],
) -> Stage4AuditResult:
    """Require exact path and content-hash equality with the pre-build snapshot."""
    rows: list[dict[str, str]] = []
    expected = {str(path): str(digest) for path, digest in expected_sha256.items()}
    expected_valid = bool(expected) and all(
        re.fullmatch(r"[0-9a-f]{64}", digest) and not Path(path).is_absolute() and ".." not in Path(path).parts
        for path, digest in expected.items()
    )
    _row(
        rows,
        "frozen_v3_expected_snapshot_valid",
        expected_valid,
        f"expected_files={len(expected)}",
    )
    try:
        observed = snapshot_sha256_tree(frozen_v3_dir)
    except (FileNotFoundError, OSError, ValueError) as exc:
        observed = {}
        scan_error = str(exc)
    else:
        scan_error = ""
    missing = sorted(set(expected) - set(observed))
    added = sorted(set(observed) - set(expected))
    changed = sorted(
        path for path in set(expected) & set(observed) if expected[path] != observed[path]
    )
    _row(
        rows,
        "frozen_v3_sha256_exact_equality",
        expected_valid and not scan_error and not missing and not added and not changed,
        f"scan_error={scan_error!r}; missing={missing}; added={added}; changed={changed}",
    )
    return _make_result(rows)


def audit_stage4_release(
    output_dir: str | Path,
    *,
    frozen_v3_dir: str | Path,
    frozen_v3_sha256: Mapping[str, str],
    require_existing_audit: bool = True,
    required_chart_names: Iterable[str] = REQUIRED_STAGE4_CHART_FILENAMES,
) -> Stage4AuditResult:
    """Audit files, tables, article, claims, charts, and the frozen v3 tree.

    For a two-pass build, call once with ``require_existing_audit=False``, write
    :func:`render_stage4_audit`, then call again with the default and rewrite the
    final audit.  The final status is derived solely from all check rows.
    """
    output = Path(output_dir)
    rows: list[dict[str, str]] = []
    required_files = list(REQUIRED_STAGE4_CSV_FILENAMES) + ["article_note.md"]
    if require_existing_audit:
        required_files.append("audit_v3_1.md")
    missing = [name for name in required_files if not (output / name).is_file()]
    _row(rows, "release_required_files_present", not missing, f"missing={missing}")

    required_charts = tuple(required_chart_names)
    chart_dir = output / "charts"
    observed_charts = sorted(path.name for path in chart_dir.glob("*.png")) if chart_dir.is_dir() else []
    expected_charts = sorted(required_charts)
    signatures_ok = all(
        (chart_dir / name).is_file()
        and (chart_dir / name).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        for name in required_charts
    )
    _row(
        rows,
        "release_required_charts_exact",
        observed_charts == expected_charts and signatures_ok and len(required_charts) <= 3,
        f"expected={expected_charts}; observed={observed_charts}; png_signatures={signatures_ok}",
    )

    audits: list[Stage4AuditResult] = [_make_result(rows)]
    claims_path = output / "claims_v3_1.csv"
    article_path = output / "article_note.md"
    if claims_path.is_file():
        try:
            claims = pd.read_csv(claims_path, keep_default_na=False)
        except Exception as exc:  # parser failures are release failures, not crashes
            audits.append(_make_result([{"check_id": "release_claims_readable", "status": "FAIL", "detail": str(exc)}]))
        else:
            audits.append(audit_stage4_claims(claims))
            if article_path.is_file():
                try:
                    article = article_path.read_text(encoding="utf-8")
                except (OSError, UnicodeError) as exc:
                    audits.append(_make_result([{"check_id": "release_article_readable", "status": "FAIL", "detail": str(exc)}]))
                else:
                    audits.append(audit_stage4_article(article, claims))

    table_paths = {
        "headline_2x2": output / "headline_2x2.csv",
        "mismatch_heatmap": output / "mismatch_heatmap.csv",
        "rounding_sensitivity": output / "rounding_sensitivity.csv",
        "deadband_sensitivity": output / "deadband_sensitivity.csv",
    }
    if all(path.is_file() for path in table_paths.values()):
        try:
            tables = {
                name: pd.read_csv(path, keep_default_na=False)
                for name, path in table_paths.items()
            }
        except Exception as exc:
            audits.append(_make_result([{"check_id": "release_analysis_csvs_readable", "status": "FAIL", "detail": str(exc)}]))
        else:
            audits.append(audit_stage4_dataframes(**tables))

    if require_existing_audit and (output / "audit_v3_1.md").is_file():
        try:
            audit_text = (output / "audit_v3_1.md").read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            passed = False
            detail = str(exc)
        else:
            passed = "**STATUS: PASS**" in audit_text and "| FAIL |" not in audit_text
            detail = "existing audit declares PASS without FAIL rows"
        audits.append(
            _make_result(
                [
                    {
                        "check_id": "release_existing_audit_pass",
                        "status": "PASS" if passed else "FAIL",
                        "detail": detail,
                    }
                ]
            )
        )

    audits.append(audit_frozen_v3_sha256(frozen_v3_dir, frozen_v3_sha256))
    return combine_stage4_audits(*audits)


def render_stage4_audit(audit: Stage4AuditResult) -> str:
    """Render a deterministic Markdown audit; PASS cannot mask a failed row."""
    derived = "PASS" if not audit.checks.empty and audit.checks["status"].eq("PASS").all() else "FAIL"
    if audit.status != derived:
        derived = "FAIL"
    lines = [
        "# 2026Q1 v3.1 公開監査",
        "",
        f"**STATUS: {derived}**",
        "",
        "| check_id | status | detail |",
        "|---|---|---|",
    ]
    for row in audit.checks.itertuples(index=False):
        detail = str(row.detail).replace("|", "／").replace("\n", " ")
        lines.append(f"| {row.check_id} | {row.status} | {detail} |")
    lines.extend(
        [
            "",
            "PASS は全チェックが PASS の場合に限る。FAIL が一件でもあれば公開不可。",
            "",
        ]
    )
    return "\n".join(lines)


# Pipeline-friendly aliases.  The ``audit_*`` names express what these
# functions do; ``validate_*`` mirrors earlier repository APIs.
validate_stage4_claims = audit_stage4_claims
validate_stage4_article = audit_stage4_article
validate_stage4_dataframes = audit_stage4_dataframes
validate_stage4_release = audit_stage4_release
