"""Fail-closed release audit for the 2026Q1 v3.2 publication.

Stage 5 is a publication correction, not a new analysis.  The contracts in
this module therefore check four independent lineages:

* the frozen v3.1 tree is byte-for-byte identical to the pre-build snapshot;
* numerical claims reconcile to the frozen v3 canonical comparison CSV;
* charts were regenerated from release CSVs and carry inspectable metadata;
* the audit and note-render articles satisfy their different publication
  contracts.

No function in this module writes release artifacts.  In particular, an audit
cannot repair a failed value, remove a failure marker, or manufacture a clean
ZIP.  Callers may run :func:`audit_stage5_release` in ``pre_audit`` mode before
``audit_v3_2.md`` and the ZIP exist, and again in ``final`` mode when both are
required.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from .stage4_audit import (
    PRIMARY_CLAIM_ID,
    SUPPLEMENTAL_CLAIM_ID,
    _audit_numeric_claim_links,
    _strip_comments,
    visible_article_character_count,
)
from .stage5_claims import (
    ARTICLE_TITLE_V3_1,
    ARTICLE_TITLE_V3_2,
    CANONICAL_RELATIVE_PATH,
    DECISION_MARGIN_CLAIM_IDS,
    NEW_2026Q1_CLAIM_IDS,
    validate_claim_units,
    validate_new_claims_against_canonical,
)
from .stage5_package import PACKAGE_FILENAME, verify_stage5_clean_zip


RELEASE_ID = "2026Q1_v3_2"
FROZEN_RELEASE_ID = "2026Q1_v3_1"
FORMAL_SMALL_CAPITAL_NAME = "資本金1,000万円以上1億円未満層"
ARTICLE_TRIGGER_HEADING = "## 発端は2026年1～3月期"
EXPECTED_HEATMAP_TITLE = (
    "通常系列と継続標本系列の方向不一致率\n"
    "（2016Q1～2026Q1）"
)
OLD_HEATMAP_TITLE = "2016年1～3月期以降：判定の不一致は小規模資本金層に集中"

REQUIRED_CHART_FILENAMES = (
    "mismatch_heatmap.png",
    "headline_2x2.png",
    "deadband_sensitivity.png",
)
REQUIRED_RELEASE_FILES_PRE_AUDIT = (
    "article_note.md",
    "article_note_render.md",
    "claims_v3_2.csv",
    "claim_corrections_v3_2.csv",
    "mismatch_heatmap.csv",
    "headline_2x2.csv",
    "deadband_sensitivity.csv",
    "unit_registry.json",
    "chart_manifest_v3_2.json",
    "expected_value_changes_v3_2.csv",
    "v3_1_immutability_manifest.json",
)
FAILURE_MARKERS = ("IMMUTABILITY_FAIL.md", "FINAL_RELEASE_FAIL.md")

RENDER_MARKERS = (
    "【図1：資本金階層・指標別の方向不一致率】",
    "【図2：複合見出しの2×2表】",
    "【図3：deadband感応度】",
)

_HTML_COMMENT = re.compile(r"<!--.*?-->", flags=re.DOTALL)
_IMAGE_LINK = re.compile(r"!\[[^]]*\]\(([^)]+)\)")
_CLAIM_ID = re.compile(r"\bV(?:31|32)-[A-Z0-9-]+\b")
_CENTRAL_MARKER = re.compile(r"<!--\s*central-claim:\s*([^\s]+)\s*-->")
_CLAIM_MARKER = re.compile(r"<!--\s*claim:\s*([^\s]+)\s*-->")


@dataclass(frozen=True)
class Stage5AuditResult:
    """Immutable collection of check results."""

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
            self.checks.loc[
                self.checks["status"].ne("PASS"), "check_id"
            ].astype(str)
        )


def _result(rows: Sequence[dict[str, str]]) -> Stage5AuditResult:
    checks = pd.DataFrame(rows, columns=["check_id", "status", "detail"])
    passed = not checks.empty and checks["status"].eq("PASS").all()
    return Stage5AuditResult("PASS" if passed else "FAIL", checks)


def _row(
    rows: list[dict[str, str]], check_id: str, passed: object, detail: object
) -> None:
    rows.append(
        {
            "check_id": str(check_id),
            "status": "PASS" if bool(passed) else "FAIL",
            "detail": str(detail),
        }
    )


def combine_stage5_audits(*audits: Stage5AuditResult) -> Stage5AuditResult:
    """Combine audits, failing on duplicate check IDs or an empty collection."""

    frames = [audit.checks for audit in audits if not audit.checks.empty]
    if not frames:
        return _result([])
    checks = pd.concat(frames, ignore_index=True)
    duplicate_ids = sorted(
        checks.loc[checks["check_id"].duplicated(keep=False), "check_id"].unique()
    )
    if duplicate_ids:
        checks = pd.concat(
            [
                checks,
                pd.DataFrame(
                    [
                        {
                            "check_id": "audit_check_ids_unique",
                            "status": "FAIL",
                            "detail": f"duplicate check IDs={duplicate_ids}",
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
    return Stage5AuditResult(
        "PASS" if checks["status"].eq("PASS").all() else "FAIL", checks
    )


def _strict_bool(value: object) -> bool | None:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)) and int(value) in (0, 1):
        return bool(value)
    if isinstance(value, str):
        value = value.strip().lower()
        if value in {"true", "1"}:
            return True
        if value in {"false", "0"}:
            return False
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_sha256_tree(root: str | Path) -> dict[str, str]:
    """Hash every regular file below ``root`` using relative POSIX paths."""

    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise FileNotFoundError(root_path)
    files: dict[str, str] = {}
    for path in sorted(root_path.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlink is not allowed in frozen tree: {path}")
        if path.is_file():
            files[path.relative_to(root_path).as_posix()] = _sha256(path)
    if not files:
        raise ValueError(f"frozen tree contains no files: {root_path}")
    return files


def _safe_relative_path(value: str) -> bool:
    path = Path(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def build_v3_1_immutability_manifest(
    frozen_v3_1_dir: str | Path,
    pre_build_sha256: Mapping[str, str],
) -> dict[str, Any]:
    """Build a before/after v3.1 inventory without hiding mismatches.

    The union of paths is retained so an added or missing file remains visible
    in a failure manifest.  This function does not assert success; the release
    gate performs that decision.
    """

    root = Path(frozen_v3_1_dir).resolve()
    before = {str(path): str(value) for path, value in pre_build_sha256.items()}
    try:
        after = snapshot_sha256_tree(root)
    except (FileNotFoundError, OSError, ValueError):
        after = {}
    rows: list[dict[str, Any]] = []
    counts = {"MATCH": 0, "MISSING": 0, "ADDED": 0, "CHANGED": 0}
    for relative in sorted(set(before) | set(after)):
        pre = before.get(relative)
        post = after.get(relative)
        if pre is None:
            status = "ADDED"
        elif post is None:
            status = "MISSING"
        elif pre != post:
            status = "CHANGED"
        else:
            status = "MATCH"
        counts[status] += 1
        path = root / relative
        rows.append(
            {
                "path": relative,
                "bytes": path.stat().st_size if path.is_file() else None,
                "pre_build_sha256": pre,
                "post_build_sha256": post,
                "status": status,
            }
        )
    exact = (
        bool(before)
        and before == after
        and all(
            _safe_relative_path(path)
            and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
            for path, digest in before.items()
        )
    )
    return {
        "schema_version": "1.0",
        "release": RELEASE_ID,
        "frozen_release": FROZEN_RELEASE_ID,
        "root": "outputs/2026Q1_v3_1",
        "hash_algorithm": "SHA-256",
        "pre_build_file_count": len(before),
        "post_build_file_count": len(after),
        "exact_path_and_sha256_match": exact,
        "summary": {
            "matched": counts["MATCH"],
            "missing": counts["MISSING"],
            "added": counts["ADDED"],
            "changed": counts["CHANGED"],
        },
        "files": rows,
    }


def _load_json_object(value: Mapping[str, Any] | str | Path) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    with Path(value).open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, Mapping):
        raise ValueError("JSON root must be an object")
    return loaded


def audit_v3_1_immutability(
    frozen_v3_1_dir: str | Path,
    pre_build_sha256: Mapping[str, str],
    manifest: Mapping[str, Any] | str | Path,
) -> Stage5AuditResult:
    """Require current tree, pre-build snapshot, and manifest to agree exactly."""

    rows: list[dict[str, str]] = []
    before = {str(path): str(value) for path, value in pre_build_sha256.items()}
    valid_before = bool(before) and all(
        _safe_relative_path(path)
        and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
        for path, digest in before.items()
    )
    _row(
        rows,
        "immutability_pre_build_snapshot_valid",
        valid_before,
        f"pre_build_files={len(before)}",
    )
    try:
        observed = snapshot_sha256_tree(frozen_v3_1_dir)
    except (FileNotFoundError, OSError, ValueError) as exc:
        observed = {}
        scan_error = f"{type(exc).__name__}:{exc}"
    else:
        scan_error = ""
    missing = sorted(set(before) - set(observed))
    added = sorted(set(observed) - set(before))
    changed = sorted(
        path
        for path in set(before) & set(observed)
        if before[path] != observed[path]
    )
    exact = valid_before and not scan_error and before == observed
    _row(
        rows,
        "immutability_v3_1_path_and_sha256_exact",
        exact,
        f"scan_error={scan_error!r}; missing={missing}; added={added}; changed={changed}",
    )

    try:
        payload = _load_json_object(manifest)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        _row(
            rows,
            "immutability_manifest_readable",
            False,
            f"{type(exc).__name__}:{exc}",
        )
        return _result(rows)
    _row(rows, "immutability_manifest_readable", True, "JSON object loaded")
    header_ok = (
        str(payload.get("release")) == RELEASE_ID
        and str(payload.get("frozen_release")) == FROZEN_RELEASE_ID
        and str(payload.get("root")) == "outputs/2026Q1_v3_1"
        and str(payload.get("hash_algorithm", "")).upper() == "SHA-256"
        and _strict_bool(payload.get("exact_path_and_sha256_match")) is True
        and int(payload.get("pre_build_file_count", -1)) == len(before)
        and int(payload.get("post_build_file_count", -1)) == len(observed)
    )
    _row(
        rows,
        "immutability_manifest_header_and_counts",
        header_ok,
        (
            f"release={payload.get('release')}; frozen={payload.get('frozen_release')}; "
            f"pre={payload.get('pre_build_file_count')}; "
            f"post={payload.get('post_build_file_count')}"
        ),
    )
    entries = payload.get("files")
    entries_ok = isinstance(entries, list)
    indexed: dict[str, Mapping[str, Any]] = {}
    duplicate: list[str] = []
    if entries_ok:
        for entry in entries:
            if not isinstance(entry, Mapping):
                entries_ok = False
                continue
            relative = str(entry.get("path", ""))
            if relative in indexed:
                duplicate.append(relative)
            indexed[relative] = entry
            if not _safe_relative_path(relative):
                entries_ok = False
    bad_entries: list[str] = []
    if entries_ok and not duplicate and set(indexed) == set(before) == set(observed):
        root = Path(frozen_v3_1_dir).resolve()
        for relative in sorted(indexed):
            entry = indexed[relative]
            size = entry.get("bytes")
            if (
                str(entry.get("pre_build_sha256")) != before[relative]
                or str(entry.get("post_build_sha256")) != observed[relative]
                or str(entry.get("status")) != "MATCH"
                or not isinstance(size, (int, np.integer))
                or int(size) != (root / relative).stat().st_size
            ):
                bad_entries.append(relative)
    else:
        bad_entries = sorted(set(before) ^ set(indexed))
    summary = payload.get("summary", {})
    summary_ok = isinstance(summary, Mapping) and all(
        int(summary.get(key, -1)) == expected
        for key, expected in {
            "matched": len(before),
            "missing": 0,
            "added": 0,
            "changed": 0,
        }.items()
    )
    _row(
        rows,
        "immutability_manifest_entries_exact",
        entries_ok and not duplicate and not bad_entries and summary_ok and exact,
        f"duplicates={duplicate}; bad_entries={bad_entries}; summary={summary}",
    )
    return _result(rows)


def _required_columns(
    rows: list[dict[str, str]], frame: pd.DataFrame, name: str, columns: set[str]
) -> bool:
    missing = sorted(columns - set(frame.columns))
    _row(rows, f"{name}_required_columns", not missing, f"missing={missing}")
    return not missing


def audit_stage5_claims(
    *,
    claims: pd.DataFrame,
    canonical_comparison: pd.DataFrame,
    unit_registry: Mapping[str, Any],
    corrections: pd.DataFrame,
    expected_value_changes: pd.DataFrame,
) -> Stage5AuditResult:
    """Audit canonical values, unit ownership, and both correction ledgers."""

    rows: list[dict[str, str]] = []
    required = {
        "claim_id",
        "metric_id",
        "metric_type",
        "numeric_value",
        "internal_value",
        "unit",
        "display_value",
        "verification_status",
        "article_use",
    }
    if not _required_columns(rows, claims, "claims", required):
        return _result(rows)
    ids = claims["claim_id"].fillna("").astype(str)
    _row(
        rows,
        "claims_unique_nonempty_and_all_pass",
        ids.ne("").all()
        and not ids.duplicated().any()
        and claims["verification_status"].astype(str).eq("PASS").all(),
        f"rows={len(claims)}; duplicates={sorted(ids[ids.duplicated()].unique())}",
    )
    missing_new = sorted(set(NEW_2026Q1_CLAIM_IDS) - set(ids))
    canonical_errors = validate_new_claims_against_canonical(
        claims, canonical_comparison
    )
    _row(
        rows,
        "claims_six_2026q1_values_match_v3_canonical",
        not missing_new and not canonical_errors,
        f"missing={missing_new}; errors={canonical_errors}",
    )
    indexed = claims.set_index("claim_id")
    new_expected = {
        NEW_2026Q1_CLAIM_IDS[0]: ("＋2.1％", "percent"),
        NEW_2026Q1_CLAIM_IDS[1]: ("－1.9％", "percent"),
        NEW_2026Q1_CLAIM_IDS[2]: ("＋2.5％", "percent"),
        NEW_2026Q1_CLAIM_IDS[3]: ("＋6.0％", "percent"),
        NEW_2026Q1_CLAIM_IDS[4]: ("0.4ポイント", "percentage_points"),
        NEW_2026Q1_CLAIM_IDS[5]: ("7.9ポイント", "percentage_points"),
    }
    bad_display = [
        claim_id
        for claim_id, (display, unit) in new_expected.items()
        if claim_id not in indexed.index
        or str(indexed.loc[claim_id, "display_value"]) != display
        or str(indexed.loc[claim_id, "unit"]) != unit
    ]
    _row(
        rows,
        "claims_six_2026q1_displays_and_units",
        not bad_display,
        f"invalid={bad_display}",
    )

    unit_errors = validate_claim_units(claims, unit_registry)
    _row(
        rows,
        "unit_registry_claim_and_metric_validation",
        not unit_errors,
        f"errors={unit_errors}",
    )
    required_units = {
        "yoy_growth_rate": "percent",
        "difference_between_growth_rates": "percentage_points",
        "direction_mismatch_rate": "percent",
        "implied_relative_margin_change": "percent",
        "deadband_threshold": "percent",
        "count": "count",
        "currency": "oku_yen",
    }
    observed_units = unit_registry.get("canonical_unit_by_metric_type", {})
    registry_ok = isinstance(observed_units, Mapping) and all(
        observed_units.get(metric_type) == unit
        for metric_type, unit in required_units.items()
    )
    _row(
        rows,
        "unit_registry_required_metric_types",
        registry_ok,
        f"observed={observed_units}",
    )
    decision_bad: list[str] = []
    decision_expected = {
        DECISION_MARGIN_CLAIM_IDS[0]: (11.3, "11.3ポイント"),
        DECISION_MARGIN_CLAIM_IDS[1]: (9.0, "9.0ポイント"),
        DECISION_MARGIN_CLAIM_IDS[2]: (8.5, "8.5ポイント"),
    }
    for claim_id, (value, display) in decision_expected.items():
        if claim_id not in indexed.index:
            decision_bad.append(claim_id)
            continue
        row = indexed.loc[claim_id]
        numeric = pd.to_numeric(pd.Series([row["numeric_value"]]), errors="coerce").iloc[0]
        if (
            pd.isna(numeric)
            or not np.isclose(float(numeric), value, rtol=0, atol=1e-12)
            or str(row["unit"]) != "percentage_points"
            or str(row["display_value"]) != display
            or str(row["metric_type"]) != "difference_between_growth_rates"
        ):
            decision_bad.append(claim_id)
    deadband_units = set(
        claims.loc[
            claims["metric_id"].astype(str).eq(
                "deadband_margin_direction_mismatch"
            ),
            "unit",
        ].astype(str)
    )
    mismatch_units = set(
        claims.loc[
            claims["metric_type"].astype(str).eq("direction_mismatch_rate"),
            "unit",
        ].astype(str)
    )
    _row(
        rows,
        "units_decision_margin_pp_deadband_and_mismatch_percent",
        not decision_bad
        and deadband_units == {"percent"}
        and mismatch_units == {"percent"},
        (
            f"decision_invalid={decision_bad}; deadband_units={deadband_units}; "
            f"mismatch_units={mismatch_units}"
        ),
    )

    correction_required = {
        "claim_id",
        "field",
        "before_value",
        "after_value",
        "reason",
        "source_version",
        "target_version",
    }
    if _required_columns(rows, corrections, "corrections", correction_required):
        expected_pairs = {
            (claim_id, field)
            for claim_id in DECISION_MARGIN_CLAIM_IDS
            for field in ("unit", "display_value")
        }
        observed_pairs = set(
            zip(corrections["claim_id"].astype(str), corrections["field"].astype(str))
        )
        unit_rows = corrections.loc[corrections["field"].astype(str).eq("unit")]
        display_rows = corrections.loc[
            corrections["field"].astype(str).eq("display_value")
        ].set_index("claim_id")
        correction_ok = (
            len(corrections) == 6
            and observed_pairs == expected_pairs
            and not corrections.duplicated(["claim_id", "field"]).any()
            and unit_rows["before_value"].astype(str).isin({"%", "percent"}).all()
            and unit_rows["after_value"].astype(str).eq("percentage_points").all()
            and corrections["reason"].fillna("").astype(str).str.strip().ne("").all()
            and corrections["source_version"].astype(str).eq(FROZEN_RELEASE_ID).all()
            and corrections["target_version"].astype(str).eq(RELEASE_ID).all()
            and all(
                str(display_rows.loc[claim_id, "after_value"]) == display
                for claim_id, (_, display) in decision_expected.items()
            )
        )
        _row(
            rows,
            "corrections_exact_six_traceable_unit_and_display_rows",
            correction_ok,
            f"rows={len(corrections)}; pairs={sorted(observed_pairs)}",
        )

    change_required = {
        "check_id",
        "before_expected_value",
        "after_expected_value",
        "change_reason",
        "status",
    }
    if _required_columns(rows, expected_value_changes, "expected_values", change_required):
        title_change = expected_value_changes.loc[
            expected_value_changes["check_id"].astype(str).eq(
                "article_title_exact_and_small_capital"
            )
        ]
        title_change_ok = (
            len(title_change) == 1
            and str(title_change.iloc[0]["before_expected_value"])
            == ARTICLE_TITLE_V3_1
            and str(title_change.iloc[0]["after_expected_value"])
            == ARTICLE_TITLE_V3_2
            and str(title_change.iloc[0]["status"])
            == "EXPECTED_VALUE_UPDATED"
            and bool(str(title_change.iloc[0]["change_reason"]).strip())
        )
        _row(
            rows,
            "expected_title_change_explicitly_recorded",
            title_change_ok,
            f"rows={title_change.to_dict('records')}",
        )
    return _result(rows)


def audit_stage5_dataframes(
    *,
    mismatch_heatmap: pd.DataFrame,
    headline_2x2: pd.DataFrame,
    deadband_sensitivity: pd.DataFrame,
) -> Stage5AuditResult:
    """Validate corrected CSV schema, canonical counts, and units."""

    rows: list[dict[str, str]] = []
    heat_required = {
        "capital_code",
        "metric_id",
        "mismatch_count",
        "comparable_quarters",
        "mismatch_rate_pct",
        "continuing_decision_margin_abs_gap_median_pp",
        "cross_series_growth_gap_divergence_median_pp",
    }
    columns_correct = (
        "continuing_decision_margin_abs_gap_median_pct"
        not in mismatch_heatmap.columns
        and "continuing_decision_margin_abs_gap_median_pp"
        in mismatch_heatmap.columns
    )
    _row(
        rows,
        "data_heatmap_old_pct_column_absent_new_pp_present",
        columns_correct,
        f"columns={list(mismatch_heatmap.columns)}",
    )
    if _required_columns(rows, mismatch_heatmap, "data_heatmap", heat_required):
        heat = mismatch_heatmap.copy()
        heat["capital_code"] = heat["capital_code"].astype(str)
        aliases = {
            "relative_margin_direction": "margin",
            "operating_margin_direction": "margin",
            "operating_margin_direction_proxy": "margin",
            "operating_profit": "operating_profit",
            "operating_profit_yoy": "operating_profit",
            "sales": "sales",
            "sales_yoy": "sales",
        }
        heat["metric_key"] = heat["metric_id"].astype(str).map(aliases)
        expected_cells = {
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
        observed_cells: dict[tuple[str, str], tuple[int, int, float]] = {}
        for record in heat.itertuples(index=False):
            if pd.notna(record.metric_key):
                observed_cells[(str(record.capital_code), str(record.metric_key))] = (
                    int(record.mismatch_count),
                    int(record.comparable_quarters),
                    round(float(record.mismatch_rate_pct), 1),
                )
        medians = {
            "19": (11.3, 11.21),
            "24": (9.0, 4.07),
            "25": (8.5, 1.05),
        }
        bad_medians: list[str] = []
        for code, (decision_expected, divergence_expected) in medians.items():
            group = heat.loc[heat["capital_code"].eq(code)]
            decision = pd.to_numeric(
                group["continuing_decision_margin_abs_gap_median_pp"],
                errors="coerce",
            ).dropna().unique()
            divergence = pd.to_numeric(
                group["cross_series_growth_gap_divergence_median_pp"],
                errors="coerce",
            ).dropna().unique()
            if (
                len(decision) != 1
                or len(divergence) != 1
                or not np.isclose(decision[0], decision_expected, atol=0.051)
                or not np.isclose(divergence[0], divergence_expected, atol=0.006)
            ):
                bad_medians.append(code)
        _row(
            rows,
            "data_heatmap_values_and_pp_medians_canonical",
            len(heat) == 9
            and observed_cells == expected_cells
            and not bad_medians,
            f"cells={observed_cells}; invalid_medians={bad_medians}",
        )

    headline_required = {
        "regular_headline_supported",
        "continuing_headline_supported",
        "quarter_count",
        "denominator_quarters",
        "regular_supported_total",
        "continuing_supported_total",
    }
    if _required_columns(rows, headline_2x2, "data_headline", headline_required):
        cells: dict[tuple[bool, bool], int] = {}
        bool_ok = True
        for record in headline_2x2.itertuples(index=False):
            regular = _strict_bool(record.regular_headline_supported)
            continuing = _strict_bool(record.continuing_headline_supported)
            if regular is None or continuing is None:
                bool_ok = False
                continue
            cells[(regular, continuing)] = int(record.quarter_count)
        expected = {
            (True, False): 9,
            (False, True): 2,
            (True, True): 1,
            (False, False): 29,
        }
        totals_ok = (
            pd.to_numeric(
                headline_2x2["denominator_quarters"], errors="coerce"
            ).eq(41).all()
            and pd.to_numeric(
                headline_2x2["regular_supported_total"], errors="coerce"
            ).eq(10).all()
            and pd.to_numeric(
                headline_2x2["continuing_supported_total"], errors="coerce"
            ).eq(3).all()
        )
        _row(
            rows,
            "data_headline_2x2_canonical",
            len(headline_2x2) == 4
            and bool_ok
            and cells == expected
            and totals_ok,
            f"cells={cells}; totals_ok={totals_ok}",
        )

    dead_required = {
        "capital_code",
        "deadband_pct",
        "retained_quarters",
        "mismatch_count",
        "mismatch_rate_pct",
        "unit",
    }
    if _required_columns(rows, deadband_sensitivity, "data_deadband", dead_required):
        dead = deadband_sensitivity.copy()
        dead["capital_code"] = dead["capital_code"].astype(str)
        dead["deadband_pct"] = pd.to_numeric(dead["deadband_pct"], errors="coerce")
        small_expected = {
            0.5: (15, 39, 38.5),
            1.0: (14, 37, 37.8),
            2.0: (10, 33, 30.3),
            3.0: (8, 29, 27.6),
        }
        observed_small = {
            float(record.deadband_pct): (
                int(record.mismatch_count),
                int(record.retained_quarters),
                round(float(record.mismatch_rate_pct), 1),
            )
            for record in dead.loc[dead["capital_code"].eq("19")].itertuples(
                index=False
            )
        }
        d3 = dead.loc[np.isclose(dead["deadband_pct"], 3.0)].set_index(
            "capital_code"
        )
        d3_ok = (
            {"19", "24", "25"} <= set(d3.index)
            and int(d3.loc["19", "mismatch_count"]) == 8
            and int(d3.loc["19", "retained_quarters"]) == 29
            and int(d3.loc["24", "mismatch_count"]) == 0
            and int(d3.loc["24", "retained_quarters"]) == 29
            and int(d3.loc["25", "mismatch_count"]) == 0
            and int(d3.loc["25", "retained_quarters"]) == 33
        )
        units = set(dead["unit"].astype(str))
        _row(
            rows,
            "data_deadband_canonical_and_percent_not_points",
            len(dead) == 12
            and observed_small == small_expected
            and d3_ok
            and units == {"percent"},
            f"small={observed_small}; d3_ok={d3_ok}; units={units}",
        )
    return _result(rows)


def _section(article: str, heading: str) -> tuple[str, int, int]:
    start = article.find(heading)
    if start < 0:
        return "", -1, -1
    content_start = article.find("\n", start)
    if content_start < 0:
        return "", start, len(article)
    next_heading = re.search(r"^#{1,6}\s+", article[content_start + 1 :], re.MULTILINE)
    end = (
        content_start + 1 + next_heading.start()
        if next_heading is not None
        else len(article)
    )
    return article[content_start + 1 : end].strip(), start, end


def _normalize_prose(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _expected_render_prose(article: str) -> str:
    text = _HTML_COMMENT.sub("", article)
    text = _IMAGE_LINK.sub("", text)
    return _normalize_prose(text)


def _observed_render_prose(render: str) -> str:
    text = render
    for marker in RENDER_MARKERS:
        text = text.replace(marker, "")
    return _normalize_prose(text)


def _contains_negative_truth_caveat(text: str) -> bool:
    return bool(
        re.search(
            r"どちらの系列も[^。\n]{0,60}(?:真実[^。\n]{0,25}正解|正解[^。\n]{0,25}真実)"
            r"[^。\n]{0,35}(?:呼ばない|扱わない|位置づけない|とはしない)",
            text,
        )
    )


def audit_stage5_article(
    article: str, article_render: str, claims: pd.DataFrame
) -> Stage5AuditResult:
    """Audit the traceable Markdown article and its note-ready rendering."""

    rows: list[dict[str, str]] = []
    plain = _strip_comments(article)
    title_match = re.search(r"^#\s+(.+?)\s*$", plain, flags=re.MULTILINE)
    title = title_match.group(1).strip() if title_match else ""
    _row(
        rows,
        "article_title_exact_and_small_capital",
        title == ARTICLE_TITLE_V3_2
        and ARTICLE_TITLE_V3_1 not in plain
        and ARTICLE_TITLE_V3_1 not in article_render,
        f"observed={title!r}",
    )
    visible_count = visible_article_character_count(article)
    _row(
        rows,
        "article_visible_character_count_2900_3300",
        2900 <= visible_count <= 3300,
        f"visible_characters={visible_count}",
    )
    central = _CENTRAL_MARKER.findall(article)
    _row(
        rows,
        "article_exactly_one_unchanged_central_claim",
        central == [PRIMARY_CLAIM_ID],
        f"central_claims={central}",
    )
    body = plain[title_match.end() :] if title_match else plain
    formal_index = body.find(FORMAL_SMALL_CAPITAL_NAME)
    before_formal = body[:formal_index] if formal_index >= 0 else body
    shorthand_before = any(
        token in before_formal
        for token in ("小規模資本金層", "中小企業", "1億円未満層")
    )
    _row(
        rows,
        "article_formal_small_capital_first_body_mention",
        formal_index >= 0 and not shorthand_before,
        f"formal_index={formal_index}; shorthand_before={shorthand_before}",
    )

    trigger, trigger_start, _ = _section(article, ARTICLE_TRIGGER_HEADING)
    compare_start = article.find("## 何を比べたのか")
    trigger_visible = visible_article_character_count(trigger)
    trigger_plain = _strip_comments(trigger)
    trigger_claims = set(_CLAIM_MARKER.findall(trigger))
    trigger_statements = {
        "scope": FORMAL_SMALL_CAPITAL_NAME in trigger_plain,
        "regular_values": "通常系列" in trigger_plain
        and "＋2.1％" in trigger_plain
        and "－1.9％" in trigger_plain,
        "continuing_values": "継続標本系列" in trigger_plain
        and "＋2.5％" in trigger_plain
        and "＋6.0％" in trigger_plain,
        "sales_both_up": bool(
            re.search(r"売上高[^。\n]{0,45}(?:いずれ|両方)[^。\n]{0,25}増加", trigger_plain)
        ),
        "operating_directions_split": bool(
            re.search(
                r"営業利益[^。\n]{0,70}通常系列[^。\n]{0,20}減少"
                r"[^。\n]{0,35}継続標本系列[^。\n]{0,20}増加",
                trigger_plain,
            )
        ),
        "margin_direction_split": "営業利益率の方向" in trigger_plain
        and "低下" in trigger_plain
        and "上昇" in trigger_plain,
        "gaps": "0.4ポイント" in trigger_plain
        and "7.9ポイント" in trigger_plain,
        "expanded_to_41": "41四半期" in trigger_plain
        and re.search(r"過去[^。\n]{0,30}(?:確認|比較)", trigger_plain)
        is not None,
    }
    _row(
        rows,
        "article_trigger_section_position_length_and_content",
        trigger_start >= 0
        and (compare_start < 0 or trigger_start < compare_start)
        and 180 <= trigger_visible <= 250
        and all(trigger_statements.values())
        and set(NEW_2026Q1_CLAIM_IDS) <= trigger_claims,
        (
            f"start={trigger_start}; compare_start={compare_start}; "
            f"visible={trigger_visible}; statements={trigger_statements}; "
            f"missing_claims={sorted(set(NEW_2026Q1_CLAIM_IDS)-trigger_claims)}"
        ),
    )

    linked_claims = set(_CLAIM_MARKER.findall(article))
    known_claims = set(claims["claim_id"].astype(str)) if "claim_id" in claims else set()
    _row(
        rows,
        "article_claim_markers_known_and_new_six_linked",
        bool(linked_claims)
        and linked_claims <= known_claims
        and set(NEW_2026Q1_CLAIM_IDS) <= linked_claims,
        f"unknown={sorted(linked_claims-known_claims)}; missing_new={sorted(set(NEW_2026Q1_CLAIM_IDS)-linked_claims)}",
    )
    numbers_ok, number_detail = _audit_numeric_claim_links(article, claims)
    _row(
        rows,
        "article_all_statistical_numbers_claim_linked",
        numbers_ok,
        number_detail,
    )

    figures = _IMAGE_LINK.findall(article)
    figure_names = [Path(value).name for value in figures]
    _row(
        rows,
        "article_exactly_three_registered_figures",
        len(figures) == 3
        and figure_names == list(REQUIRED_CHART_FILENAMES)
        and all(not Path(value).is_absolute() for value in figures),
        f"paths={figures}",
    )

    forbidden_literals = (
        "標本を替えると",
        "継続標本の方が正しい",
        "通常系列が間違っている",
        "真実は継続標本にある",
        "同一企業パネル",
        "統計的に有意",
        "有意",
        "確率",
        "確実",
        "通常系列のバイアス",
        "バイアス率",
        "誤報率",
        "中小企業だけ",
        "調査方式が原因である",
        "全数か標本かで結果が決まる",
    )
    forbidden_hits = [term for term in forbidden_literals if term in plain]
    overclaim_patterns = {
        "AFFIRMATIVE_TRUTH_OR_CORRECT": (
            r"(?:通常系列|継続標本(?:系列)?)[^。\n]{0,30}"
            r"(?:が真実|が正解|が正しい)"
        ),
        "DESIGN_CAUSAL": (
            r"調査(?:方式|設計|方法)[^。\n]{0,25}"
            r"(?:が原因|で決まる|が決定)"
        ),
        "PROBABILITY_OR_SIGNIFICANCE": r"(?:誤報率|バイアス率|統計的に有意|事前確率)",
    }
    overclaim_hits = [
        name for name, pattern in overclaim_patterns.items() if re.search(pattern, plain)
    ]
    _row(
        rows,
        "article_forbidden_wording_and_overclaims_absent",
        not forbidden_hits and not overclaim_hits,
        f"literal={forbidden_hits}; patterns={overclaim_hits}",
    )
    exclusions = (
        "外形標準課税",
        "税制上の減資インセンティブ",
        "自己申告区分",
        "営業外損益",
        "受取利息等",
        "その他の営業外収益",
        "支払利息等",
        "その他の営業外費用",
        "nonoperating",
        "non_operating",
    )
    exclusion_hits = [term for term in exclusions if term in plain]
    _row(
        rows,
        "article_excluded_topics_absent",
        not exclusion_hits,
        f"hits={exclusion_hits}",
    )

    required_design_terms = (
        "標本の入れ替え",
        "継続回答法人への限定",
        "推計用乗率",
        "未回答補完",
        "企業の参入・退出",
        "母集団構成",
        "資本金階層間の移動",
    )
    missing_design = [
        term
        for term in required_design_terms
        if term not in plain
        and not (
            term == "資本金階層間の移動"
            and re.search(r"資本金階層間(?:の移動|を移る)", plain)
        )
    ]
    movement_general = all(term in plain for term in ("増資", "減資"))
    central_claim_ok = (
        "16/41" in plain
        and re.search(
            r"(?:資本金10億円以上層|大規模資本金層)"
            r"[^。\n]{0,50}(?:不一致(?:が|は)なかった|0/41)",
            plain,
        )
        is not None
        and "調査設計と整合的" in plain
        and re.search(
            r"原因[^。\n]{0,35}(?:識別できない|特定[^。\n]{0,12}ない)",
            plain,
        )
        is not None
    )
    _row(
        rows,
        "article_central_claim_and_design_limit_unchanged",
        central_claim_ok
        and not missing_design
        and movement_general
        and _contains_negative_truth_caveat(plain),
        (
            f"central={central_claim_ok}; missing_design={missing_design}; "
            f"movement_general={movement_general}; "
            f"negative_truth={_contains_negative_truth_caveat(plain)}"
        ),
    )

    continuing_direction_ok = (
        re.search(
            r"継続標本(?:系列)?[^。\n]{0,80}営業利益率[^。\n]{0,30}"
            r"水準[^。\n]{0,25}公表[^。\n]{0,10}ない",
            plain,
        )
        is not None
        and re.search(
            r"方向判定(?:だけ|に限定)|方向(?:だけ|に限定)",
            plain,
        )
        is not None
    )
    invalid_margin_points = [
        sentence
        for sentence in re.split(r"[。！？\n]", plain)
        if "継続標本" in sentence
        and "営業利益率" in sentence
        and re.search(r"\d+(?:\.\d+)?\s*(?:pt|ポイント)", sentence)
    ]
    _row(
        rows,
        "article_continuing_margin_direction_only",
        continuing_direction_ok and not invalid_margin_points,
        f"direction_ok={continuing_direction_ok}; invalid={invalid_margin_points}",
    )
    deadband_ok = (
        re.search(
            r"(?:営業利益率|推定した利益率|利益率)の(?:推定)?相対変化率"
            r"[^。\n]{0,15}(?:％|%)",
            plain,
            flags=re.IGNORECASE,
        )
        is not None
        and re.search(
            r"(?:営業利益率の)?(?:絶対的な|絶対)?"
            r"(?:パーセント)?ポイント差[^。\n]{0,15}"
            r"(?:ではない|ではなく|とは異なる)",
            plain,
        )
        is not None
    )
    _row(
        rows,
        "article_deadband_formula_and_percent_unit",
        deadband_ok,
        "deadband must be relative change percent, not a margin percentage-point difference",
    )

    # Render is audited independently and also compared to the audit article
    # after removal of implementation-only comments and figure links.
    comments = _HTML_COMMENT.findall(article_render)
    relative_images = [
        path
        for path in _IMAGE_LINK.findall(article_render)
        if not Path(path).is_absolute()
        and not re.match(r"https?://", path, flags=re.IGNORECASE)
    ]
    marker_counts = {marker: article_render.count(marker) for marker in RENDER_MARKERS}
    claim_ids = _CLAIM_ID.findall(article_render)
    implementation_labels = [
        token
        for token in ("central-claim", "claim:", "article_tokens", "claim_id")
        if token in article_render
    ]
    _row(
        rows,
        "render_no_comments_relative_images_or_claim_ids",
        not comments
        and not relative_images
        and not claim_ids
        and not implementation_labels,
        (
            f"comments={len(comments)}; relative_images={relative_images}; "
            f"claim_ids={claim_ids}; labels={implementation_labels}"
        ),
    )
    _row(
        rows,
        "render_three_figure_markers_once_each",
        all(count == 1 for count in marker_counts.values())
        and len(re.findall(r"【図\d：", article_render)) == 3,
        f"counts={marker_counts}",
    )
    normalized_same = _expected_render_prose(article) == _observed_render_prose(
        article_render
    )
    _row(
        rows,
        "render_preserves_article_text_and_order",
        normalized_same,
        (
            f"audit_normalized_chars={len(_expected_render_prose(article))}; "
            f"render_normalized_chars={len(_observed_render_prose(article_render))}"
        ),
    )
    return _result(rows)


def _normal_title(value: object) -> str:
    return re.sub(r"\s+", "", str(value))


def _chart_entries(manifest: Mapping[str, Any] | Sequence[Any]) -> list[Mapping[str, Any]]:
    if isinstance(manifest, Mapping):
        raw = manifest.get("charts")
    else:
        raw = manifest
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    return [entry for entry in raw if isinstance(entry, Mapping)]


def _metadata_triplet(
    metadata: Mapping[str, Any], key: str
) -> tuple[dict[str, float], bool]:
    raw = metadata.get(key)
    if not isinstance(raw, list):
        return {}, False
    observed: dict[str, float] = {}
    units_ok = True
    for item in raw:
        if not isinstance(item, Mapping):
            units_ok = False
            continue
        tier = str(
            item.get("capital_code", item.get("capital_tier", item.get("tier", "")))
        )
        aliases = {
            "small": "19",
            "middle": "24",
            "large": "25",
            "小": "19",
            "中堅": "24",
            "大": "25",
            "小規模資本金層": "19",
            "中間資本金層": "24",
            "資本金10億円以上層": "25",
        }
        tier = aliases.get(tier, tier)
        try:
            observed[tier] = float(item.get("value"))
        except (TypeError, ValueError):
            units_ok = False
        if str(item.get("unit")) != "percentage_points":
            units_ok = False
    return observed, units_ok


def audit_stage5_chart_manifest(
    manifest: Mapping[str, Any] | Sequence[Any],
    *,
    output_dir: str | Path,
    claims: pd.DataFrame,
) -> Stage5AuditResult:
    """Audit chart sources, hashes, regeneration flags, and structured metadata."""

    rows: list[dict[str, str]] = []
    output = Path(output_dir).resolve()
    entries = _chart_entries(manifest)
    manifest_header_ok = (
        (not isinstance(manifest, Mapping) or str(manifest.get("release_id")) == RELEASE_ID)
        and (not isinstance(manifest, Mapping) or int(manifest.get("chart_count", -1)) == 3)
        and len(entries) == 3
    )
    _row(
        rows,
        "charts_manifest_header_and_count",
        manifest_header_ok,
        f"entry_count={len(entries)}",
    )
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
    expected_by_png = {
        "mismatch_heatmap.png": "mismatch_heatmap.csv",
        "headline_2x2.png": "headline_2x2.csv",
        "deadband_sensitivity.png": "deadband_sensitivity.csv",
    }
    observed_pngs: set[str] = set()
    known_claims = set(claims["claim_id"].astype(str)) if "claim_id" in claims else set()
    invalid_entries: list[str] = []
    for entry in entries:
        chart_id = str(entry.get("chart_id", "<missing>"))
        missing = required_fields - set(entry)
        png_name = Path(str(entry.get("png_path", ""))).name
        source_name = Path(str(entry.get("source_csv", ""))).name
        observed_pngs.add(png_name)
        referenced = entry.get("referenced_claim_ids")
        if isinstance(referenced, str):
            referenced_ids = [value for value in re.split(r"[;,]", referenced) if value]
        elif isinstance(referenced, list):
            referenced_ids = [str(value) for value in referenced]
        else:
            referenced_ids = []
        source_path = output / source_name
        png_path = output / "charts" / png_name
        hashes_ok = (
            source_name == expected_by_png.get(png_name)
            and source_path.is_file()
            and png_path.is_file()
            and str(entry.get("source_csv_sha256", "")) == _sha256(source_path)
            and str(entry.get("png_sha256", "")) == _sha256(png_path)
            and png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        )
        lineage_ok = (
            bool(referenced_ids)
            and set(referenced_ids) <= known_claims
            and str(entry.get("numeric_source_role")) == "SOURCE_CSV_NOT_CLAIMS"
        )
        if (
            missing
            or _strict_bool(entry.get("regenerated_in_release")) is not True
            or not str(entry.get("title", "")).strip()
            or not hashes_ok
            or not lineage_ok
        ):
            invalid_entries.append(
                f"{chart_id}:missing={sorted(missing)},hashes={hashes_ok},lineage={lineage_ok}"
            )
    chart_files = (
        sorted(path.name for path in (output / "charts").glob("*.png"))
        if (output / "charts").is_dir()
        else []
    )
    _row(
        rows,
        "charts_three_regenerated_source_hashed_pngs",
        not invalid_entries
        and observed_pngs == set(REQUIRED_CHART_FILENAMES)
        and chart_files == sorted(REQUIRED_CHART_FILENAMES),
        f"invalid={invalid_entries}; manifest_pngs={sorted(observed_pngs)}; files={chart_files}",
    )

    heat_entries = [
        entry
        for entry in entries
        if Path(str(entry.get("png_path", ""))).name == "mismatch_heatmap.png"
    ]
    heat_ok = False
    heat_detail = "missing heatmap entry"
    if len(heat_entries) == 1:
        heat = heat_entries[0]
        metadata = heat.get("structured_metadata")
        if isinstance(metadata, Mapping):
            decision, decision_units = _metadata_triplet(
                metadata, "decision_margin_medians"
            )
            divergence, divergence_units = _metadata_triplet(
                metadata, "cross_series_divergence_medians"
            )
        else:
            decision, decision_units = {}, False
            divergence, divergence_units = {}, False
        serialized = json.dumps(heat, ensure_ascii=False, sort_keys=True)
        heat_ok = (
            _normal_title(heat.get("title")) == _normal_title(EXPECTED_HEATMAP_TITLE)
            and OLD_HEATMAP_TITLE not in serialized
            and "11.3％／9.0％／8.5％" not in serialized
            and decision_units
            and divergence_units
            and set(decision) == {"19", "24", "25"}
            and set(divergence) == {"19", "24", "25"}
            and np.isclose(decision["19"], 11.3, atol=1e-12)
            and np.isclose(decision["24"], 9.0, atol=1e-12)
            and np.isclose(decision["25"], 8.5, atol=1e-12)
            # Manifest metadata retains canonical precision; the release
            # target is the two-decimal display, not a rounded internal value.
            and round(divergence["19"], 2) == 11.21
            and round(divergence["24"], 2) == 4.07
            and round(divergence["25"], 2) == 1.05
            and _strict_bool(heat.get("regenerated_in_release")) is True
        )
        heat_detail = (
            f"title={heat.get('title')!r}; decision={decision}; "
            f"divergence={divergence}; units={decision_units}/{divergence_units}"
        )
    _row(
        rows,
        "charts_heatmap_neutral_title_pp_metadata",
        heat_ok,
        heat_detail,
    )

    headline_entries = [
        entry
        for entry in entries
        if Path(str(entry.get("png_path", ""))).name == "headline_2x2.png"
    ]
    headline_ok = False
    if len(headline_entries) == 1:
        metadata = headline_entries[0].get("structured_metadata", {})
        cells = metadata.get("cells", []) if isinstance(metadata, Mapping) else []
        observed_counts: dict[str, int] = {}
        for cell in cells if isinstance(cells, list) else []:
            if isinstance(cell, Mapping):
                key = str(cell.get("cell_id", cell.get("id", "")))
                try:
                    observed_counts[key] = int(
                        cell.get("quarter_count", cell.get("count"))
                    )
                except (TypeError, ValueError):
                    pass
        headline_ok = (
            observed_counts
            == {"REGULAR_ONLY": 9, "CONTINUING_ONLY": 2, "BOTH": 1, "NEITHER": 29}
            and int(metadata.get("regular_supported_total", -1)) == 10
            and int(metadata.get("continuing_supported_total", -1)) == 3
        )
    _row(
        rows,
        "charts_headline_structured_counts",
        headline_ok,
        f"entries={len(headline_entries)}",
    )

    dead_entries = [
        entry
        for entry in entries
        if Path(str(entry.get("png_path", ""))).name
        == "deadband_sensitivity.png"
    ]
    dead_ok = False
    dead_detail = f"entries={len(dead_entries)}"
    if len(dead_entries) == 1:
        dead_entry = dead_entries[0]
        metadata = dead_entry.get("structured_metadata", {})
        serialized = json.dumps(dead_entry, ensure_ascii=False, sort_keys=True)
        series = metadata.get("small_capital_series", []) if isinstance(metadata, Mapping) else []
        observed: dict[float, tuple[int, int, float]] = {}
        for item in series if isinstance(series, list) else []:
            if not isinstance(item, Mapping):
                continue
            try:
                observed[float(item.get("deadband_percent"))] = (
                    int(item.get("numerator")),
                    int(item.get("denominator")),
                    round(float(item.get("rate_percent")), 1),
                )
            except (TypeError, ValueError):
                pass
        expected = {
            0.0: (16, 41, 39.0),
            0.5: (15, 39, 38.5),
            1.0: (14, 37, 37.8),
            2.0: (10, 33, 30.3),
            3.0: (8, 29, 27.6),
        }
        definition = str(metadata.get("deadband_definition", "")) if isinstance(metadata, Mapping) else ""
        dead_ok = (
            observed == expected
            and "percent" in serialized
            and "percentage_points" not in definition
            and ("relative" in definition.lower() or "相対変化率" in definition)
        )
        dead_detail = f"small={observed}; definition={definition!r}"
    _row(rows, "charts_deadband_structured_percent_values", dead_ok, dead_detail)
    return _result(rows)


def _read_text(path: Path) -> tuple[str | None, str]:
    try:
        return path.read_text(encoding="utf-8"), ""
    except (OSError, UnicodeError) as exc:
        return None, f"{type(exc).__name__}:{exc}"


def audit_stage5_release(
    output_dir: str | Path,
    *,
    frozen_v3_1_dir: str | Path,
    frozen_v3_1_sha256: Mapping[str, str],
    project_root: str | Path | None = None,
    phase: str = "final",
    require_existing_audit: bool | None = None,
    require_package: bool | None = None,
) -> Stage5AuditResult:
    """Run the complete v3.2 gate in pre-audit or final mode.

    ``phase='pre_audit'`` permits ``audit_v3_2.md`` and the ZIP to be absent.
    ``phase='final'`` requires both.  The explicit boolean arguments are kept
    for two-pass callers and override the phase defaults.
    """

    if phase not in {"pre_audit", "final"}:
        raise ValueError("phase must be 'pre_audit' or 'final'")
    if require_existing_audit is None:
        require_existing_audit = phase == "final"
    if require_package is None:
        require_package = phase == "final"
    output = Path(output_dir).resolve()
    root = Path(project_root).resolve() if project_root else output.parents[1]
    rows: list[dict[str, str]] = []
    required = list(REQUIRED_RELEASE_FILES_PRE_AUDIT)
    if require_existing_audit:
        required.append("audit_v3_2.md")
    if require_package:
        required.append(PACKAGE_FILENAME)
    missing = [relative for relative in required if not (output / relative).is_file()]
    _row(
        rows,
        "release_required_files_present_for_phase",
        not missing,
        f"phase={phase}; missing={missing}",
    )
    present_markers = [name for name in FAILURE_MARKERS if (output / name).exists()]
    _row(
        rows,
        "release_failure_markers_absent",
        not present_markers,
        f"present={present_markers}",
    )
    audits: list[Stage5AuditResult] = [_result(rows)]

    manifest_path = output / "v3_1_immutability_manifest.json"
    if manifest_path.is_file():
        audits.append(
            audit_v3_1_immutability(
                frozen_v3_1_dir, frozen_v3_1_sha256, manifest_path
            )
        )

    frozen_audit_path = Path(frozen_v3_1_dir) / "audit_v3_1.md"
    frozen_audit, frozen_error = _read_text(frozen_audit_path)
    audits.append(
        _result(
            [
                {
                    "check_id": "release_frozen_v3_1_audit_pass",
                    "status": (
                        "PASS"
                        if frozen_audit is not None
                        and "**STATUS: PASS**" in frozen_audit
                        and "| FAIL |" not in frozen_audit
                        else "FAIL"
                    ),
                    "detail": frozen_error or str(frozen_audit_path),
                }
            ]
        )
    )

    paths = {
        "claims": output / "claims_v3_2.csv",
        "corrections": output / "claim_corrections_v3_2.csv",
        "heatmap": output / "mismatch_heatmap.csv",
        "headline": output / "headline_2x2.csv",
        "deadband": output / "deadband_sensitivity.csv",
        "expected": output / "expected_value_changes_v3_2.csv",
        "registry": output / "unit_registry.json",
        "chart_manifest": output / "chart_manifest_v3_2.json",
        "article": output / "article_note.md",
        "render": output / "article_note_render.md",
    }
    claims: pd.DataFrame | None = None
    try:
        if paths["claims"].is_file():
            claims = pd.read_csv(paths["claims"], keep_default_na=False)
        canonical = pd.read_csv(root / CANONICAL_RELATIVE_PATH)
        corrections = pd.read_csv(paths["corrections"], keep_default_na=False)
        expected = pd.read_csv(paths["expected"], keep_default_na=False)
        with paths["registry"].open(encoding="utf-8") as handle:
            registry = json.load(handle)
        if claims is None:
            raise FileNotFoundError(paths["claims"])
    except Exception as exc:  # release parsing errors are audit rows, not crashes
        audits.append(
            _result(
                [
                    {
                        "check_id": "release_claim_inputs_readable",
                        "status": "FAIL",
                        "detail": f"{type(exc).__name__}:{exc}",
                    }
                ]
            )
        )
    else:
        audits.append(
            audit_stage5_claims(
                claims=claims,
                canonical_comparison=canonical,
                unit_registry=registry,
                corrections=corrections,
                expected_value_changes=expected,
            )
        )

    try:
        heat = pd.read_csv(paths["heatmap"], keep_default_na=False)
        headline = pd.read_csv(paths["headline"], keep_default_na=False)
        deadband = pd.read_csv(paths["deadband"], keep_default_na=False)
    except Exception as exc:
        audits.append(
            _result(
                [
                    {
                        "check_id": "release_analysis_csvs_readable",
                        "status": "FAIL",
                        "detail": f"{type(exc).__name__}:{exc}",
                    }
                ]
            )
        )
    else:
        audits.append(
            audit_stage5_dataframes(
                mismatch_heatmap=heat,
                headline_2x2=headline,
                deadband_sensitivity=deadband,
            )
        )

    article, article_error = _read_text(paths["article"])
    render, render_error = _read_text(paths["render"])
    if article is not None and render is not None and claims is not None:
        audits.append(audit_stage5_article(article, render, claims))
    else:
        audits.append(
            _result(
                [
                    {
                        "check_id": "release_articles_readable",
                        "status": "FAIL",
                        "detail": f"article={article_error}; render={render_error}",
                    }
                ]
            )
        )

    try:
        with paths["chart_manifest"].open(encoding="utf-8") as handle:
            chart_manifest = json.load(handle)
    except Exception as exc:
        audits.append(
            _result(
                [
                    {
                        "check_id": "release_chart_manifest_readable",
                        "status": "FAIL",
                        "detail": f"{type(exc).__name__}:{exc}",
                    }
                ]
            )
        )
    else:
        if claims is not None:
            audits.append(
                audit_stage5_chart_manifest(
                    chart_manifest, output_dir=output, claims=claims
                )
            )

    if require_existing_audit:
        audit_text, audit_error = _read_text(output / "audit_v3_2.md")
        audit_ok = (
            audit_text is not None
            and "**STATUS: PASS**" in audit_text
            and "| FAIL |" not in audit_text
            and ARTICLE_TITLE_V3_1 in audit_text
            and ARTICLE_TITLE_V3_2 in audit_text
            and "EXPECTED_VALUE_UPDATED" in audit_text
            and "変更理由" in audit_text
        )
        audits.append(
            _result(
                [
                    {
                        "check_id": "release_existing_audit_pass_and_title_change_documented",
                        "status": "PASS" if audit_ok else "FAIL",
                        "detail": audit_error or "audit status and expectation-change narrative checked",
                    }
                ]
            )
        )

    if require_package:
        package_result = verify_stage5_clean_zip(output / PACKAGE_FILENAME)
        audits.append(
            _result(
                [
                    {
                        "check_id": "release_clean_package_verified",
                        "status": (
                            "PASS" if package_result.get("status") == "PASS" else "FAIL"
                        ),
                        "detail": json.dumps(
                            package_result, ensure_ascii=False, sort_keys=True
                        ),
                    }
                ]
            )
        )
    return combine_stage5_audits(*audits)


def _escape_markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def render_stage5_audit(audit: Stage5AuditResult) -> str:
    """Render an inspectable audit with the intentional title change exposed."""

    lines = [
        "# 法人企業統計 2026Q1 v3.2 最終公開監査",
        "",
        f"**STATUS: {audit.status}**",
        "",
        "## 監査期待値の変更履歴",
        "",
        f"- 変更前タイトル：{ARTICLE_TITLE_V3_1}",
        f"- 変更後タイトル：{ARTICLE_TITLE_V3_2}",
        "- 変更理由：中心主張を営業利益率方向の不一致に限定し、期間表現を最終公開版に合わせた。",
        "- 監査期待値：`article_title_exact_and_small_capital` を `EXPECTED_VALUE_UPDATED` として更新。",
        "",
        "## フェイルクローズ判定",
        "",
        "| check_id | status | detail |",
        "|---|---|---|",
    ]
    for record in audit.checks.itertuples(index=False):
        lines.append(
            "| "
            + " | ".join(
                _escape_markdown_cell(value)
                for value in (record.check_id, record.status, record.detail)
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "PASSは全チェックがPASSの場合にのみ付与する。"
            "`IMMUTABILITY_FAIL.md`または`FINAL_RELEASE_FAIL.md`が存在する場合はFAILとする。",
            "",
        ]
    )
    return "\n".join(lines)
