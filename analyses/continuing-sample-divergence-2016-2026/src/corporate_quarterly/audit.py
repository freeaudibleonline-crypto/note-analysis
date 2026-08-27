from __future__ import annotations

import json
import math
import re
import calendar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .constants import (
    CAPITAL_COMPONENT_NAMES,
    MAJOR_INDUSTRY_NAMES,
    PRIMARY_ANALYSIS_METRICS,
    PROJECT_ROOT,
    Release,
)
from .estat import sha256_file
from .processing import detect_profit_transition, oku_to_trillion


ADDITIVE_ANALYSIS_METRICS = (
    *PRIMARY_ANALYSIS_METRICS,
    "software_capex_derived",
    "cash_and_deposits",
    "total_borrowings_derived",
    "interest_expense",
    "employee_wages",
    "employee_bonuses",
    "employee_total_pay_derived",
    "employee_count",
    "ordinary_minus_operating",
)


@dataclass
class Check:
    check_id: str
    status: str
    detail: str
    metric_id: str | None = None


@dataclass
class Audit:
    checks: list[Check] = field(default_factory=list)
    quality_log: list[dict[str, Any]] = field(default_factory=list)

    def add(self, check_id: str, passed: bool, detail: str, metric_id: str | None = None) -> None:
        self.checks.append(Check(check_id, "PASS" if passed else "FAIL", detail, metric_id))

    @property
    def passed(self) -> bool:
        return all(check.status != "FAIL" for check in self.checks)

    @property
    def status(self) -> str:
        return "PASS" if self.passed else "FAIL"


def _almost_equal(left: float | None, right: float | None, tolerance: float = 0.01) -> bool:
    if left is None or right is None or pd.isna(left) or pd.isna(right):
        return False
    return math.isclose(float(left), float(right), abs_tol=tolerance, rel_tol=0.0)


def _total_row(processed: pd.DataFrame, metric_id: str) -> pd.Series | None:
    subset = processed.loc[
        processed["coverage_scope"].eq("EXCL_FINANCE_INSURANCE")
        & processed["source_table_number"].astype(str).eq("1")
        & processed["industry_bucket"].eq("ALL_NONFINANCIAL")
        & processed["capital_bucket"].eq("ALL_CAPITAL")
        & processed["metric_id"].eq(metric_id)
    ]
    return None if subset.empty else subset.iloc[0]


def _verify_raw_hashes(
    manifest: dict[str, Any], project_root: Path
) -> tuple[bool, str]:
    failures: list[str] = []
    for source in manifest.get("sources", []):
        path = Path(source["raw_path"])
        if not path.is_absolute():
            path = project_root / path
        if not path.exists():
            fallback = (
                project_root
                / "data"
                / "raw"
                / str(manifest.get("release_id", ""))
                / Path(source["raw_path"]).name
            )
            if fallback.exists():
                path = fallback
        if not path.exists():
            failures.append(f"missing:{path.name}")
        elif sha256_file(path) != source["sha256"]:
            failures.append(f"hash_mismatch:{path.name}")
    return (not failures, ", ".join(failures) if failures else f"{len(manifest.get('sources', []))} source hashes verified")


def _check_capital_sums(processed: pd.DataFrame, audit: Audit) -> None:
    base = processed.loc[
        processed["coverage_scope"].eq("EXCL_FINANCE_INSURANCE")
        & processed["source_table_number"].astype(str).eq("1")
        & processed["industry_bucket"].eq("ALL_NONFINANCIAL")
        & processed["capital_size_name"].isin(CAPITAL_COMPONENT_NAMES)
    ]
    for metric_id in ADDITIVE_ANALYSIS_METRICS:
        total = _total_row(processed, metric_id)
        subset = base.loc[base["metric_id"].eq(metric_id)]
        value_columns = (
            ("source_value", "raw_lag4_value", "raw_yoy_delta")
            if metric_id == "employee_count"
            else (
                "raw_value_oku_yen",
                "raw_lag4_value_oku_yen",
                "raw_yoy_delta_oku_yen",
            )
        )
        observed_names = set(subset["capital_size_name"])
        expected_names = set(CAPITAL_COMPONENT_NAMES)
        structural_ok = (
            len(subset) == len(CAPITAL_COMPONENT_NAMES)
            and observed_names == expected_names
            and not subset[list(value_columns[:2])].isna().any().any()
        )
        audit.add(
            f"capital_components_{metric_id}_completeness",
            bool(structural_ok),
            f"observed={len(subset)}, expected={len(CAPITAL_COMPONENT_NAMES)}, "
            f"missing names={sorted(expected_names - observed_names)}, "
            f"extra names={sorted(observed_names - expected_names)}, "
            f"null cells={int(subset[list(value_columns[:2])].isna().sum().sum())}",
            metric_id,
        )
        for column in value_columns:
            actual = subset[column].sum(min_count=len(CAPITAL_COMPONENT_NAMES))
            expected = None if total is None else total[column]
            audit.add(
                f"capital_components_{metric_id}_{column}",
                _almost_equal(actual, expected),
                f"components={actual:.2f}, total={float(expected):.2f} ({'人' if metric_id == 'employee_count' else '億円'})"
                if expected is not None and not pd.isna(expected)
                else "Missing total or component; not imputed",
                metric_id,
            )


def _check_industry_sums(processed: pd.DataFrame, audit: Audit) -> None:
    base = processed.loc[
        processed["coverage_scope"].eq("EXCL_FINANCE_INSURANCE")
        & processed["source_table_number"].astype(str).eq("1")
        & processed["capital_bucket"].eq("ALL_CAPITAL")
        & processed["industry_name"].isin(MAJOR_INDUSTRY_NAMES)
    ]
    for metric_id in ADDITIVE_ANALYSIS_METRICS:
        total = _total_row(processed, metric_id)
        subset = base.loc[base["metric_id"].eq(metric_id)]
        value_columns = (
            ("source_value", "raw_lag4_value", "raw_yoy_delta")
            if metric_id == "employee_count"
            else (
                "raw_value_oku_yen",
                "raw_lag4_value_oku_yen",
                "raw_yoy_delta_oku_yen",
            )
        )
        observed_names = set(subset["industry_name"])
        expected_names = set(MAJOR_INDUSTRY_NAMES)
        structural_ok = (
            len(subset) == len(MAJOR_INDUSTRY_NAMES)
            and observed_names == expected_names
            and not subset[list(value_columns[:2])].isna().any().any()
        )
        audit.add(
            f"industry_components_{metric_id}_completeness",
            bool(structural_ok),
            f"observed={len(subset)}, expected={len(MAJOR_INDUSTRY_NAMES)}, "
            f"missing names={sorted(expected_names - observed_names)}, "
            f"extra names={sorted(observed_names - expected_names)}, "
            f"null cells={int(subset[list(value_columns[:2])].isna().sum().sum())}",
            metric_id,
        )
        for column in value_columns:
            actual = subset[column].sum(min_count=len(MAJOR_INDUSTRY_NAMES))
            expected = None if total is None else total[column]
            audit.add(
                f"industry_components_{metric_id}_{column}",
                _almost_equal(actual, expected),
                f"published-major-industry sum={actual:.2f}, total={float(expected):.2f} ({'人' if metric_id == 'employee_count' else '億円'})"
                if expected is not None and not pd.isna(expected)
                else "Missing total or component; not imputed",
                metric_id,
            )


def _check_finance_reconciliation(processed: pd.DataFrame, audit: Audit) -> None:
    shared = {
        "ordinary_profit",
        "capex_including_software",
        "capex_excluding_software",
        "employee_count",
        "employee_wages",
        "employee_bonuses",
    }
    for metric_id in shared:
        tables = {}
        for scope in (
            "EXCL_FINANCE_INSURANCE",
            "INCL_FINANCE_INSURANCE",
            "FINANCE_INSURANCE_ONLY",
        ):
            subset = processed.loc[
                processed["coverage_scope"].eq(scope)
                & processed["capital_bucket"].eq("ALL_CAPITAL")
                & processed["metric_id"].eq(metric_id)
                & processed["seasonal_adjustment"].eq("RAW")
            ]
            if scope != "FINANCE_INSURANCE_ONLY":
                subset = subset.loc[
                    subset["industry_bucket"].eq("ALL_NONFINANCIAL")
                ]
            if not subset.empty:
                tables[scope] = subset.iloc[0]
        if len(tables) != 3:
            audit.add(
                f"finance_reconciliation_{metric_id}",
                False,
                "A required finance/non-finance table value is absent; no zero fill was applied",
                metric_id,
            )
            continue
        for column in ("source_value", "raw_lag4_value"):
            inclusive = tables["INCL_FINANCE_INSURANCE"][column]
            summed = (
                tables["EXCL_FINANCE_INSURANCE"][column]
                + tables["FINANCE_INSURANCE_ONLY"][column]
            )
            audit.add(
                f"finance_reconciliation_{metric_id}_{column}",
                _almost_equal(inclusive, summed, tolerance=1.0),
                f"including-finance={inclusive:.0f}, non-finance+finance={summed:.0f} (source unit)",
                metric_id,
            )


def _check_rates(processed: pd.DataFrame, audit: Audit) -> None:
    comparable = processed.loc[
        processed["sa_qoq_pct"].notna() & processed["official_sa_qoq_pct"].notna()
    ].copy()
    if comparable.empty:
        audit.add("published_sa_rate_coverage", False, "No seasonally adjusted rates could be compared")
        return
    comparable["abs_error"] = (
        comparable["sa_qoq_pct"] - comparable["official_sa_qoq_pct"]
    ).abs()
    max_error = comparable["abs_error"].max()
    audit.add(
        "published_sa_rate_error",
        bool(max_error <= 0.05),
        f"{len(comparable)} series compared; max absolute error={max_error:.12f} percentage points",
    )


def _check_pdf_reference_values(
    processed: pd.DataFrame, audit: Audit, release: Release
) -> None:
    populated = 0
    for metric_id, published in release.pdf_reference_checks.get("yoy_pct", {}).items():
        total = _total_row(processed, metric_id)
        computed = None if total is None else total.get("raw_yoy_pct")
        official_column_value = None if total is None else total.get("official_yoy_pct")
        if official_column_value is not None and pd.notna(official_column_value):
            populated += 1
        error = (
            math.nan
            if computed is None or pd.isna(computed)
            else abs(float(computed) - float(published))
        )
        audit.add(
            f"pdf_published_yoy_rate_{metric_id}",
            bool(pd.notna(error) and error <= 0.05 + 1e-12),
            (
                f"computed={float(computed):.6f}%, PDF={float(published):.1f}%, "
                f"absolute error={error:.6f} percentage points"
                if pd.notna(error)
                else "Computed or PDF reference rate is missing"
            ),
            metric_id,
        )
        audit.add(
            f"processed_official_yoy_rate_{metric_id}",
            bool(
                official_column_value is not None
                and pd.notna(official_column_value)
                and _almost_equal(float(official_column_value), float(published), tolerance=1e-12)
            ),
            f"processed official_yoy_pct={official_column_value}, PDF reference={published}",
            metric_id,
        )
    expected_rate_count = len(release.pdf_reference_checks.get("yoy_pct", {}))
    audit.add(
        "processed_official_yoy_rate_coverage",
        populated == expected_rate_count,
        f"populated headline official_yoy_pct rows={populated}, expected={expected_rate_count}",
    )
    for metric_id, reference in release.pdf_reference_checks.get(
        "ranked_amounts", {}
    ).items():
        total = _total_row(processed, metric_id)
        computed = None if total is None else total.get("raw_value_oku_yen")
        amount_matches = (
            computed is not None
            and pd.notna(computed)
            and int(round(float(computed))) == int(reference["amount_oku_yen"])
        )
        audit.add(
            f"pdf_ranked_amount_{metric_id}",
            bool(amount_matches),
            (
                f"structured amount rounds to {int(round(float(computed))):,} 億円; "
                f"PDF page {reference['page']} reports rank {reference['rank']} "
                f"of {reference['history_quarters']} quarters. The rank is a PDF "
                "cross-check, not independently recomputed from the three-period extract."
                if computed is not None and pd.notna(computed)
                else "Structured current amount is missing"
            ),
            metric_id,
        )


def _check_schema_and_missingness(
    processed: pd.DataFrame,
    parse_issues: list[dict[str, Any]],
    audit: Audit,
    release: Release,
) -> None:
    required_columns = {
        "source_value",
        "raw_yoy_delta",
        "raw_yoy_pct",
        "raw_qoq_pct",
        "sa_value_oku_yen",
        "sa_qoq_pct",
        "official_sa_qoq_pct",
        "official_yoy_pct",
    }
    missing_columns = sorted(required_columns - set(processed.columns))
    audit.add(
        "raw_yoy_sa_variables_separate",
        not missing_columns,
        "Raw, year-on-year, raw quarter-on-quarter, and seasonally adjusted variables are separate"
        if not missing_columns
        else f"Missing columns: {', '.join(missing_columns)}",
    )
    quarter_month = {"1": 3, "2": 6, "3": 9, "4": 12}[release.target_period_code[-1]]
    year = int(release.target_period_code[:4])
    expected_period_end = (
        f"{year:04d}-{quarter_month:02d}-{calendar.monthrange(year, quarter_month)[1]:02d}"
    )
    audit.add(
        "target_period_end_parsed",
        bool(processed["period_end"].eq(expected_period_end).all()),
        f"period_end populated for {len(processed):,} target-period rows",
    )
    missing_rows = processed["missing_status"].ne("PRESENT")
    missing_preserved = bool(processed.loc[missing_rows, "source_value"].isna().all())
    audit.add(
        "missing_values_not_zero_imputed",
        missing_preserved,
        f"{int(missing_rows.sum())} missing/derived-missing current values retained as null, never zero-filled",
    )
    key = [
        "coverage_scope",
        "source_table_number",
        "industry_code",
        "capital_size_code",
        "metric_id",
    ]
    duplicate_count = int(processed.duplicated(key, keep=False).sum())
    audit.add(
        "canonical_observation_key_unique",
        duplicate_count == 0,
        f"duplicate rows={duplicate_count}",
    )
    scopes = set(processed["coverage_scope"].dropna())
    expected_scopes = {
        "EXCL_FINANCE_INSURANCE",
        "INCL_FINANCE_INSURANCE",
        "FINANCE_INSURANCE_ONLY",
    }
    audit.add(
        "finance_scope_separation",
        expected_scopes <= scopes,
        f"available scopes={sorted(scopes)}",
    )
    for kind in (
        "MISSING_OR_UNPARSEABLE_VALUE",
        "TABLE_SHAPE",
        "UNKNOWN_DIMENSION_CODE",
        "UNKNOWN_METRIC_CODE",
        "INDUSTRY_CLASSIFICATION_CHANGE",
    ):
        matching = [issue for issue in parse_issues if issue.get("kind") == kind]
        fatal = [issue for issue in matching if issue.get("severity") == "FAIL"]
        audit.add(
            f"quality_log_{kind.lower()}",
            not fatal,
            f"logged events={len(matching)}, fatal={len(fatal)}; values are not imputed",
        )


def _check_required_metrics(processed: pd.DataFrame, audit: Audit) -> None:
    required = (
        *PRIMARY_ANALYSIS_METRICS,
        "software_capex_derived",
        "employee_pay_per_person_approx",
        "employee_total_pay_derived",
        "employee_count",
        "cash_and_deposits",
        "total_borrowings_derived",
        "interest_expense",
        "ordinary_minus_operating",
    )
    for metric_id in required:
        row = _total_row(processed, metric_id)
        available = row is not None and (
            pd.notna(row.get("raw_value_oku_yen"))
            or pd.notna(row.get("source_value"))
        )
        audit.add(
            f"required_metric_{metric_id}",
            bool(available),
            "Available without missing-value imputation" if available else "Required input missing",
            metric_id,
        )


def _check_derived_identities(processed: pd.DataFrame, audit: Audit) -> None:
    base = processed.loc[
        processed["coverage_scope"].eq("EXCL_FINANCE_INSURANCE")
        & processed["source_table_number"].astype(str).eq("1")
    ].copy()
    keys = ["industry_code", "capital_size_code"]

    def check_identity(
        identity: str,
        value_column: str,
        derived_metric: str,
        input_metrics: tuple[str, ...],
        operation: str,
        tolerance: float = 0.01,
    ) -> None:
        selected = base.loc[
            base["metric_id"].isin((*input_metrics, derived_metric)),
            keys + ["metric_id", value_column],
        ]
        wide = selected.pivot(index=keys, columns="metric_id", values=value_column)
        required = [*input_metrics, derived_metric]
        missing_columns = [column for column in required if column not in wide]
        if missing_columns:
            audit.add(
                f"derived_identity_{identity}_{value_column}",
                False,
                f"Missing metric columns: {missing_columns}",
            )
            return
        inputs = wide[list(input_metrics)]
        complete = inputs.notna().all(axis=1)
        if operation == "sum":
            expected = inputs.sum(axis=1, min_count=len(input_metrics))
        elif operation == "subtract":
            expected = inputs.iloc[:, 0] - inputs.iloc[:, 1]
        elif operation == "pay_per_person":
            expected = (inputs.iloc[:, 0] + inputs.iloc[:, 1]) * 100.0 / inputs.iloc[:, 2]
            complete &= inputs.iloc[:, 2].ne(0)
            expected = expected.where(complete)
        else:  # pragma: no cover - internal programming guard
            raise ValueError(operation)
        actual = wide[derived_metric]
        availability_ok = actual.notna().eq(complete).all()
        errors = (actual[complete] - expected[complete]).abs()
        max_error = float(errors.max()) if not errors.empty else 0.0
        audit.add(
            f"derived_identity_{identity}_{value_column}",
            bool(availability_ok and max_error <= tolerance),
            f"rows={len(wide)}, complete inputs={int(complete.sum())}, max absolute error={max_error:.12f}",
        )

    for value_column in ("raw_value_oku_yen", "raw_lag4_value_oku_yen"):
        check_identity(
            "software_bridge",
            value_column,
            "software_capex_derived",
            ("capex_including_software", "capex_excluding_software"),
            "subtract",
        )
        check_identity(
            "borrowings_sum",
            value_column,
            "total_borrowings_derived",
            (
                "financial_institution_borrowings_current",
                "other_borrowings_current",
                "financial_institution_borrowings_long_term",
                "other_borrowings_long_term",
            ),
            "sum",
        )
        check_identity(
            "ordinary_operating_gap",
            value_column,
            "ordinary_minus_operating",
            ("ordinary_profit", "operating_profit"),
            "subtract",
        )
        check_identity(
            "employee_total_pay",
            value_column,
            "employee_total_pay_derived",
            ("employee_wages", "employee_bonuses"),
            "sum",
        )
    for value_column in ("source_value", "raw_lag4_value"):
        check_identity(
            "employee_pay_per_person",
            value_column,
            "employee_pay_per_person_approx",
            ("employee_wages", "employee_bonuses", "employee_count"),
            "pay_per_person",
            tolerance=1e-9,
        )


def _check_transitions(processed: pd.DataFrame, audit: Audit) -> None:
    subset = processed.loc[
        processed["source_table_number"].astype(str).eq("1")
        & processed["seasonal_adjustment"].eq("RAW")
        & processed["metric_id"].isin(("operating_profit", "ordinary_profit"))
    ].copy()
    transitions = [
        detect_profit_transition(previous, current)
        for previous, current in zip(
            subset["raw_lag4_value_oku_yen"], subset["raw_value_oku_yen"], strict=True
        )
    ]
    subset["recomputed_profit_transition"] = transitions
    stored_matches = subset["profit_transition_yoy"].eq(
        subset["recomputed_profit_transition"]
    ).all()
    audit.add(
        "profit_loss_transition_status_persisted",
        bool(stored_matches),
        "Persisted transition statuses match recomputation",
    )
    count = int(
        subset["profit_transition_yoy"].isin(("PROFIT_TO_LOSS", "LOSS_TO_PROFIT")).sum()
    )
    loss_to_profit = subset["profit_transition_yoy"].eq("LOSS_TO_PROFIT")
    invalid_rates_suppressed = subset.loc[loss_to_profit, "raw_yoy_pct"].isna().all()
    audit.add(
        "profit_loss_transition_detection",
        bool(invalid_rates_suppressed),
        f"{count} black/red transitions detected; {int(loss_to_profit.sum())} negative-base rates suppressed",
    )
    for _, row in subset.loc[
        subset["profit_transition_yoy"].isin(("PROFIT_TO_LOSS", "LOSS_TO_PROFIT"))
    ].iterrows():
        audit.quality_log.append(
            {
                "kind": "PROFIT_LOSS_TRANSITION",
                "severity": "INFO",
                "detail": row["profit_transition_yoy"],
                "metric_id": row["metric_id"],
                "industry_name": row["industry_name"],
                "capital_size_name": row["capital_size_name"],
            }
        )


def validate_data(
    *,
    processed: pd.DataFrame,
    manifest: dict[str, Any],
    parse_issues: list[dict[str, Any]],
    release: Release,
    project_root: Path = PROJECT_ROOT,
) -> Audit:
    audit = Audit(quality_log=list(parse_issues))
    hashes_ok, hash_detail = _verify_raw_hashes(manifest, project_root)
    audit.add("raw_manifest_hashes", hashes_ok, hash_detail)
    audit.add(
        "oku_to_trillion_conversion",
        oku_to_trillion(10_000.0) == 1.0,
        "10,000 億円 = 1.0 兆円",
    )
    _check_required_metrics(processed, audit)
    _check_derived_identities(processed, audit)
    _check_capital_sums(processed, audit)
    _check_industry_sums(processed, audit)
    _check_finance_reconciliation(processed, audit)
    _check_rates(processed, audit)
    _check_pdf_reference_values(processed, audit, release)
    _check_schema_and_missingness(processed, parse_issues, audit, release)
    _check_transitions(processed, audit)
    for issue in parse_issues:
        if issue.get("severity") == "FAIL":
            audit.add(
                f"parse_{issue.get('kind', 'unknown')}",
                False,
                issue.get("detail", "Unknown parsing failure"),
            )
    return audit


def validate_claim_table(claims: pd.DataFrame, audit: Audit) -> None:
    duplicate_ids = claims.loc[claims["claim_id"].duplicated(), "claim_id"].tolist()
    audit.add(
        "claims_unique_ids",
        not duplicate_ids,
        "All claim IDs are unique" if not duplicate_ids else f"Duplicates: {duplicate_ids}",
    )
    numeric = claims.loc[claims["claim_type"].isin(("FACT", "CALC"))]
    failed = numeric.loc[numeric["verification_status"].ne("PASS"), "claim_id"].tolist()
    audit.add(
        "claims_all_numeric_verified",
        not failed,
        "Every FACT/CALC claim has finite inputs"
        if not failed
        else f"Unverified numeric claims: {', '.join(failed)}",
    )
    unit_failures: list[str] = []
    for row in numeric.itertuples():
        if not str(row.display_value).endswith(str(row.unit)):
            unit_failures.append(row.claim_id)
            continue
        number_text = str(row.display_value)[: -len(str(row.unit))].replace(",", "")
        try:
            shown = float(number_text)
            decimals = len(number_text.partition(".")[2]) if "." in number_text else 0
            tolerance = 0.5 * 10 ** (-decimals) + 1e-12
            if pd.isna(row.value) or abs(shown - float(row.value)) > tolerance:
                unit_failures.append(row.claim_id)
        except (TypeError, ValueError):
            unit_failures.append(row.claim_id)
    audit.add(
        "claims_value_unit_display_consistency",
        not unit_failures,
        "Exact claim values, units, and rounded displays are consistent"
        if not unit_failures
        else f"Unit/display mismatches: {', '.join(unit_failures)}",
    )
    hypotheses = claims.loc[claims["claim_type"].eq("HYPOTHESIS")]
    hypotheses_ok = bool(
        len(hypotheses) > 0
        and hypotheses["claim_text"].str.contains("【HYPOTHESIS】", regex=False).all()
        and hypotheses["verification_status"].eq("HYPOTHESIS_LABELLED").all()
    )
    audit.add(
        "claims_hypotheses_explicitly_labelled",
        hypotheses_ok,
        f"labelled hypotheses={len(hypotheses)}",
    )


def validate_article_claims(article_path: Path, claims: pd.DataFrame, audit: Audit) -> None:
    text = article_path.read_text(encoding="utf-8")
    narrative_claims = (
        claims.loc[claims["claim_usage"].ne("CHART_INPUT")]
        if "claim_usage" in claims
        else claims
    )
    markers = re.findall(r"<!-- claim: ([A-Z]-\d{3}) -->", text)
    marker_set = set(markers)
    duplicate_markers = len(marker_set) != len(markers)
    audit.add(
        "article_claim_marker_uniqueness",
        not duplicate_markers,
        f"{len(markers)} markers, {len(marker_set)} unique",
    )
    required = narrative_claims.loc[
        narrative_claims["claim_type"].isin(("FACT", "CALC"))
        & narrative_claims["verification_status"].eq("PASS"),
        "claim_id",
    ]
    missing = sorted(set(required) - marker_set)
    audit.add(
        "article_claim_marker_coverage",
        not missing,
        "All verified FACT/CALC claims are marked"
        if not missing
        else f"Missing article claim markers: {', '.join(missing)}",
    )
    hypothesis_ids = set(
        narrative_claims.loc[
            narrative_claims["claim_type"].eq("HYPOTHESIS"), "claim_id"
        ]
    )
    audit.add(
        "article_hypothesis_marker_coverage",
        hypothesis_ids <= marker_set,
        "All hypothesis records are linked from the article"
        if hypothesis_ids <= marker_set
        else f"Missing hypothesis markers: {', '.join(sorted(hypothesis_ids - marker_set))}",
    )
    stale = sorted(marker_set - set(claims["claim_id"]))
    audit.add(
        "article_no_unknown_markers",
        not stale,
        "No unknown claim markers" if not stale else f"Unknown markers: {', '.join(stale)}",
    )
    missing_display = [
        row.claim_id
        for row in narrative_claims.itertuples()
        if row.claim_type in ("FACT", "CALC")
        and row.verification_status == "PASS"
        and f"{row.display_value}<!-- claim: {row.claim_id} -->" not in text
    ]
    audit.add(
        "article_display_value_claim_match",
        not missing_display,
        "All displayed numeric claims exactly match claims.csv"
        if not missing_display
        else f"Missing/mismatched values: {', '.join(missing_display)}",
    )

    numeric_pattern = re.compile(
        r"[+\-−]?\d[\d,]*(?:\.\d+)?\s*(?:万円/人|兆円|億円|万円|人|%|ポイント)"
    )
    unmarked: list[str] = []
    pair_mismatches: list[str] = []
    claim_rows = {str(row.claim_id): row for row in narrative_claims.itertuples()}
    claimed_numeric_spans: list[tuple[int, int]] = []
    for match in numeric_pattern.finditer(text):
        marker_match = re.match(
            r"<!-- claim: ([A-Z]-\d{3}) -->", text[match.end() :]
        )
        if marker_match is None:
            unmarked.append(match.group(0))
            continue
        claim_id = marker_match.group(1)
        row = claim_rows.get(claim_id)
        if row is None or str(row.display_value) != match.group(0):
            pair_mismatches.append(f"{match.group(0)} -> {claim_id}")
            continue
        claimed_numeric_spans.append((match.start(), match.end()))
    audit.add(
        "article_no_unclaimed_numbers",
        not unmarked,
        "No unclaimed numeric-with-unit strings"
        if not unmarked
        else f"Unclaimed numbers: {', '.join(unmarked[:8])}",
    )
    audit.add(
        "article_numeric_claim_pairs_exact",
        not pair_mismatches,
        "Every statistical number is directly followed by its matching claim ID"
        if not pair_mismatches
        else f"Mismatched number/claim pairs: {', '.join(pair_mismatches[:8])}",
    )

    protected_spans = list(claimed_numeric_spans)
    protected_patterns = (
        r"<!-- claim: [A-Z]-\d{3} -->",
        r"```.*?```",
        r"`[^`\n]*`",
        r"令和\d+年\d+〜\d+月期",
        r"\d{4}-\d{2}-\d{2}",
        r"200字",
        r"SHA-256",
    )
    for pattern in protected_patterns:
        protected_spans.extend(
            (match.start(), match.end())
            for match in re.finditer(pattern, text, flags=re.DOTALL)
        )

    def protected(position: int) -> bool:
        return any(start <= position < end for start, end in protected_spans)

    bare_numbers = [
        match.group(0)
        for match in re.finditer(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?", text)
        if not protected(match.start())
    ]
    audit.add(
        "article_no_unclassified_arabic_numbers",
        not bare_numbers,
        "All Arabic numerals are claim-backed statistics or whitelisted provenance/layout metadata"
        if not bare_numbers
        else f"Unclassified Arabic numbers: {', '.join(bare_numbers[:12])}",
    )

    badge_matches = list(
        re.finditer(r"【(FACT|CALC|HYPOTHESIS)】", text)
    )
    badge_failures: list[str] = []
    for marker in re.finditer(r"<!-- claim: ([A-Z]-\d{3}) -->", text):
        claim_id = marker.group(1)
        preceding = [badge for badge in badge_matches if badge.start() < marker.start()]
        badge = preceding[-1].group(1) if preceding else None
        row = claim_rows.get(claim_id)
        expected_badge = None if row is None else row.claim_type
        if badge != expected_badge:
            badge_failures.append(f"{claim_id}: badge={badge}, expected={expected_badge}")
    audit.add(
        "article_claim_type_badges_match",
        not badge_failures,
        "Every narrative claim marker inherits the matching FACT/CALC/HYPOTHESIS badge"
        if not badge_failures
        else " | ".join(badge_failures[:8]),
    )
    prohibited = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if "本業のもうけ" in line:
            prohibited.append(f"line {line_number}: prohibited description of ordinary profit")
        for phrase in ("AI需要", "インバウンド", "人手不足", "価格転嫁"):
            if phrase in line and "HYPOTHESIS" not in line:
                prohibited.append(f"line {line_number}: unlabelled causal phrase {phrase}")
        if "過去最高" in line and not ("名目" in line or "実質" in line):
            prohibited.append(f"line {line_number}: '過去最高' lacks nominal/real qualifier")
    audit.add(
        "article_interpretation_policy",
        not prohibited,
        "Article interpretation policy satisfied"
        if not prohibited
        else " | ".join(prohibited),
    )
    summary_match = re.search(
        r"## 事実だけによる200字要約\s*\n+(.*?)(?=\n## )", text, flags=re.DOTALL
    )
    if summary_match:
        summary = re.sub(r"<!-- claim: [A-Z]-\d{3} -->", "", summary_match.group(1))
        summary = re.sub(r"【(?:FACT|CALC|HYPOTHESIS)】", "", summary)
        summary = summary.replace("\n", "").strip()
        summary_length = len(summary)
    else:
        summary_length = -1
    audit.add(
        "article_fact_summary_200_characters",
        summary_length == 200,
        f"visible fact-summary length={summary_length} characters",
    )


def audit_markdown(audit: Audit, release: Release) -> str:
    lines = [
        f"# 監査報告 — {release.release_label_ja}",
        "",
        f"**STATUS: {audit.status}**",
        "",
        "## 公開ゲート",
        "",
        "| チェック | 状態 | 詳細 |",
        "|---|---|---|",
    ]
    for check in audit.checks:
        lines.append(
            f"| {check.check_id} | {check.status} | {check.detail.replace('|', '／')} |"
        )
    lines.extend(
        [
            "",
            "## データ品質ログ",
            "",
            "欠損・表章変更・業種分類変更は0へ補完せず、以下に保持する。",
            "",
        ]
    )
    if not audit.quality_log:
        lines.append("- 該当なし")
    else:
        for issue in audit.quality_log:
            detail = issue.get("detail", "")
            lines.append(
                f"- [{issue.get('severity', 'INFO')}] {issue.get('kind', 'UNKNOWN')}: {detail}"
            )
    lines.extend(
        [
            "",
            "## 判定規則",
            "",
            "- 数値正本はe-Stat構造化表。PDFは定義・注記・公表ランキングの照合に限る。",
            "- 金融・保険業を除く表1と、金融・保険業を含む表2は別系列として扱う。",
            "- 季節調整済前期比は表4と財務省公表Excelの一致を確認する。業種別・資本金規模別の季調前期比は作成しない。",
            "- 記事本文・表の統計値はclaims.csvと直結照合し、図の描画入力はCHART_INPUT claimと照合する。公開日、表番号、軸目盛などの来歴・レイアウト数値は統計claimと分離する。",
            "- FAILが一つでもあれば、記事は完成扱いにしない。",
            "",
        ]
    )
    return "\n".join(lines)


def write_quality_log(path: Path, audit: Audit) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(audit.quality_log, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
