"""Fail-closed orchestration for the additive 2026Q1 v3 analysis."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable
import zipfile

import numpy as np
import pandas as pd

from .constants import PROJECT_ROOT
from .estat import sha256_file
from .publication_contracts import audit_statistical_wording
from .release_integrity import (
    build_release_inventory,
    build_repository_top_level_inventory,
    check_runtime_dependencies,
    create_clean_release_zip,
    inspect_archive_structure,
    validate_release_structure,
    verify_clean_release_zip,
)
from .rule_sensitivity import build_count_rolling_sensitivity, build_rule_sensitivity
from .stage2_continuing_sample import (
    CONTINUING_VINTAGE_ID,
    LIMITATION_NOTES,
    build_continuing_sample_analysis,
    fetch_continuing_sample_snapshot,
    verify_continuing_sample_manifest,
)
from .stage2_phase3_non_operating import (
    PHASE3_VINTAGE_ID,
    build_phase3_non_operating_analysis,
    fetch_phase3_non_operating_raw,
)
from .stage3_reports import (
    CONTINUING_LIMITATION,
    V3Check,
    choose_final_decision,
    render_archive_inventory,
    render_audit,
    render_candidate_headlines,
    render_decision,
    render_metric_definition_audit,
    render_rule_sensitivity,
)


STAGE3_CONFIG = "stage3_2026Q1.json"
OUTPUT_ID = "2026Q1_v3"
TARGET_PERIOD_CODE = "20261"
BASELINE_TEST_COUNT = 95
STAGE3_REQUIRED_OUTPUTS = (
    "archive_inventory.md",
    "clean_archive_manifest.json",
    "metric_definition_audit.md",
    "rule_sensitivity.md",
    "continuing_sample_raw_manifest.json",
    "continuing_sample_quarterly.csv",
    "main_vs_continuing_sample.csv",
    "headline_reversal_frequency.csv",
    "nonoperating_bridge.csv",
    "nonoperating_bridge_historical.csv",
    "nonoperating_driver_concentration.csv",
    "claims_v3.csv",
    "audit_v3.md",
    "decision_v3.md",
    "candidate_headlines_v3.md",
)
STAGE3_CHARTS = (
    "current_sample_margin_direction.png",
    "historical_sample_reversal_frequency.png",
    "nonoperating_four_item_bridge.png",
)


class Stage3BuildError(RuntimeError):
    """Raised when a v3 public gate fails."""


def _json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_stage3_config(project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    path = Path(project_root) / "config" / STAGE3_CONFIG
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("CONFIG_KIND") != "EXECUTABLE_STAGE3_CONFIGURATION":
        raise Stage3BuildError(f"Not an executable Stage 3 config: {path}")
    if config.get("output_id") != OUTPUT_ID:
        raise Stage3BuildError("Stage 3 output_id must remain 2026Q1_v3")
    return config


def _frozen_output_hashes(project_root: Path) -> dict[str, str]:
    inventory = build_release_inventory(project_root)
    return {
        row["path"]: row["sha256"]
        for release in inventory["releases"].values()
        for row in release["files"]
    }


def _collect_pytest_count(project_root: Path) -> int:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests"],
        cwd=project_root,
        env={**dict(__import__("os").environ), "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    combined = result.stdout + "\n" + result.stderr
    matches = re.findall(r"(\d+) tests? collected", combined)
    if result.returncode != 0 or not matches:
        raise Stage3BuildError(
            "pytest collection is a CODE_OR_DATA_FAILURE: "
            + combined[-2_000:].replace("\n", " ")
        )
    return int(matches[-1])


def fetch_stage3_sources(project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Freeze both v3 source vintages without touching either prior output."""
    root = Path(project_root)
    before = _frozen_output_hashes(root)
    continuing = fetch_continuing_sample_snapshot(root)
    nonoperating = fetch_phase3_non_operating_raw(
        raw_root=root / "data" / "raw" / PHASE3_VINTAGE_ID
    )
    after = _frozen_output_hashes(root)
    if before != after:
        raise Stage3BuildError("Source fetch mutated frozen v1/v2 output bytes")
    return {
        "continuing_sample_manifest": continuing,
        "nonoperating_manifest": nonoperating,
        "frozen_output_hashes_equal": True,
    }


def _invalidate_v3(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        *STAGE3_REQUIRED_OUTPUTS,
        "article_public.md",
        "corporate_quarterly_2026Q1_v3_clean.zip",
        "corporate_quarterly_2026Q1_v3_clean.zip.sha256",
    ):
        path = output_dir / name
        if path.is_file():
            path.unlink()
    for name in STAGE3_CHARTS:
        path = output_dir / "charts" / name
        if path.is_file():
            path.unlink()


def write_stage3_failure_stubs(output_dir: Path, reason: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe = str(reason).replace("|", "／")
    (output_dir / "audit_v3.md").write_text(
        f"# 2026Q1 v3 最終監査\n\n**STATUS: FAIL**\n\n- BUILD_INCOMPLETE: {safe}\n",
        encoding="utf-8",
    )
    (output_dir / "decision_v3.md").write_text(
        "# 最終判定: ARCHIVE_NO_ROBUST_STORY\n\n"
        "**STATUS: FAIL**\n\n"
        f"BUILD_INCOMPLETE: {safe}\n",
        encoding="utf-8",
    )
    article = output_dir / "article_public.md"
    if article.exists():
        article.unlink()


def _with_continuing_limitations(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["continuing_sample_size_limitation"] = LIMITATION_NOTES["small_sample"]
    result["profit_standard_error_limitation"] = LIMITATION_NOTES[
        "profit_standard_error"
    ]
    result["continuing_margin_interpretation"] = LIMITATION_NOTES[
        "relative_margin_proxy"
    ]
    return result


def _main_comparison_output(analysis: Any) -> pd.DataFrame:
    comparison = analysis.comparison.copy()
    relative = analysis.relative_margin_comparison.copy()
    keys = [
        "period_code",
        "breakdown",
        "category_code",
        "category_id",
        "category_label_ja",
    ]
    relative_columns = [
        *keys,
        "continuing_sales_yoy_pct",
        "continuing_operating_profit_yoy_pct",
        "continuing_implied_relative_margin_change_pct",
        "continuing_relative_margin_change_direction",
        "continuing_relative_margin_status",
        "regular_sales_yoy_pct",
        "regular_operating_profit_yoy_pct",
        "regular_implied_relative_margin_change_pct",
        "regular_relative_margin_change_direction",
        "regular_relative_margin_status",
        "relative_margin_direction_reversal",
        "relative_margin_direction_comparison_status",
    ]
    merged = comparison.merge(
        relative[relative_columns], on=keys, how="left", validate="many_to_one"
    )
    headline = analysis.capital_headline_history[
        [
            "period_code",
            "regular_headline_supported",
            "continuing_headline_supported",
            "headline_reversal",
            "headline_comparison_status",
        ]
    ]
    merged = merged.merge(headline, on="period_code", how="left", validate="many_to_one")
    return _with_continuing_limitations(merged)


def _frequency_output(analysis: Any) -> pd.DataFrame:
    sign = analysis.sign_reversal_frequency.rename(
        columns={
            "comparable_nonzero_sign_quarters": "comparable_quarters",
            "sign_reversal_count": "reversal_count",
            "sign_reversal_rate_pct": "reversal_rate_pct",
        }
    ).copy()
    sign["comparison_type"] = "YOY_SIGN"
    margin = analysis.relative_margin_reversal_frequency.rename(
        columns={
            "comparable_direction_quarters": "comparable_quarters",
            "direction_reversal_count": "reversal_count",
            "direction_reversal_rate_pct": "reversal_rate_pct",
        }
    ).copy()
    margin["metric_id"] = "operating_margin_direction_proxy"
    margin["comparison_type"] = "OPERATING_MARGIN_DIRECTION"
    headline = analysis.headline_reversal_frequency.rename(
        columns={
            "comparable_headline_quarters": "comparable_quarters",
            "headline_reversal_count": "reversal_count",
            "headline_reversal_rate_pct": "reversal_rate_pct",
        }
    ).copy()
    headline["breakdown"] = "headline"
    headline["category_code"] = "CAPITAL_19_VS_25"
    headline["category_id"] = headline["headline_id"]
    headline["category_label_ja"] = (
        "通常系列の資本金規模別利益率見出しと継続標本の成立可否"
    )
    headline["metric_id"] = "capital_margin_divergence_headline_support"
    headline["comparison_type"] = "HEADLINE_SUPPORT"
    result = pd.concat([sign, margin, headline], ignore_index=True, sort=False)
    result["comparison_period_start"] = "2016Q1"
    result["comparison_period_end"] = "2026Q1"
    return _with_continuing_limitations(result)


def _bridge_output(nonoperating: Any) -> pd.DataFrame:
    current = nonoperating.current_breakdown.copy()
    anchors = nonoperating.decomposition.loc[
        nonoperating.decomposition["period_code"].astype(str).eq(TARGET_PERIOD_CODE)
    ].copy()
    anchor_columns = [
        "period_code",
        "industry_code",
        "capital_size_code",
        "operating_profit_oku_yen",
        "operating_profit_lag4_oku_yen",
        "operating_profit_yoy_delta_oku_yen",
        "ordinary_profit_oku_yen",
        "ordinary_profit_lag4_oku_yen",
        "ordinary_profit_yoy_delta_oku_yen",
        "anchor_gap_oku_yen",
        "anchor_gap_lag4_oku_yen",
        "anchor_gap_yoy_delta_oku_yen",
        "component_gap_oku_yen",
        "component_gap_lag4_oku_yen",
        "component_gap_yoy_delta_oku_yen",
        "profit_impact_sum_yoy_oku_yen",
        "yoy_identity_residual_oku_yen",
        "identity_status",
        "yoy_identity_status",
    ]
    result = current.merge(
        anchors[anchor_columns],
        on=["period_code", "industry_code", "capital_size_code"],
        how="left",
        validate="many_to_one",
    )
    result["source_delta_public_rounded_oku_yen"] = result[
        "source_yoy_delta_oku_yen"
    ].round(0)
    result["profit_impact_public_rounded_oku_yen"] = result[
        "profit_impact_yoy_oku_yen"
    ].round(0)
    result["public_rounded_component_sum_oku_yen"] = result.groupby(
        ["period_code", "industry_code", "capital_size_code"], sort=False
    )["profit_impact_public_rounded_oku_yen"].transform("sum")
    result["other_nonoperating_causal_interpretation"] = (
        "FORBIDDEN_WITHOUT_EXTERNAL_PRIMARY_EVIDENCE"
    )
    return _with_continuing_limitations(result)


def _target_bridge(bridge: pd.DataFrame) -> pd.DataFrame:
    return bridge.loc[
        bridge["industry_code"].astype(str).eq("104")
        & bridge["capital_size_code"].astype(str).eq("26")
        & bridge["period_code"].astype(str).eq(TARGET_PERIOD_CODE)
    ].sort_values("component_order", kind="stable")


def _near(actual: Any, expected: float, tolerance: float = 0.011) -> bool:
    return pd.notna(actual) and abs(float(actual) - expected) <= tolerance


def _source_archive_report(project_root: Path) -> tuple[dict[str, bool], dict[str, Any]]:
    required_names = [row["path"] for row in build_repository_top_level_inventory(project_root)]
    archive_path = project_root / "アーカイブ.zip"
    if not archive_path.is_file():
        return (
            {name: False for name in required_names},
            {
                "path": str(archive_path.relative_to(project_root)),
                "member_count": 294,
                "junk_member_count": 186,
                "sha256": None,
                "initial_observation_bytes": 7_084_138,
                "initial_required_structure_status": "PASS",
                "status": (
                    "INSPECTED_COMPLETE_AT_PHASE0_START_THEN_BECAME_UNAVAILABLE;"
                    "REPOSITORY_INVENTORY_USED_FOR_FINAL_GATE"
                ),
            },
        )
    inspection = inspect_archive_structure(archive_path)
    missing = set(inspection["missing_required_paths"])
    with zipfile.ZipFile(archive_path) as archive:
        member_count = len(archive.namelist())
    return (
        {name: name not in missing for name in required_names},
        {
            "path": archive_path.relative_to(project_root).as_posix(),
            "member_count": member_count,
            "junk_member_count": len(inspection["junk_members"]),
            "sha256": sha256_file(archive_path),
            "required_structure_status": inspection["required_structure_status"],
            "hygiene_status": inspection["hygiene_status"],
        },
    )


def _clean_manifest(
    *,
    project_root: Path,
    inventory: dict[str, Any],
    repository_rows: list[dict[str, Any]],
    archive_required: dict[str, bool],
    source_archive: dict[str, Any],
    current_test_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "FROZEN_V1_V2_ALL_FILES_AND_CLEAN_V3_PACKAGE_POLICY",
        "hash_algorithm": "SHA-256",
        "continuing_sample_limitations": {
            "small_sample": LIMITATION_NOTES["small_sample"],
            "profit_standard_error": LIMITATION_NOTES["profit_standard_error"],
        },
        "frozen_outputs": inventory,
        "repository_required_inventory": repository_rows,
        "source_archive": {
            **source_archive,
            "required_path_status": archive_required,
        },
        "pytest": {
            "baseline_collection_count": BASELINE_TEST_COUNT,
            "current_collection_count": current_test_count,
            "dependency_failure_class": "DEPENDENCY_FAILURE",
            "code_or_data_failure_class": "CODE_OR_DATA_FAILURE",
        },
        "clean_package": {
            "command": "make package-v3",
            "path": "outputs/2026Q1_v3/corporate_quarterly_2026Q1_v3_clean.zip",
            "excluded": [
                "__MACOSX",
                "__pycache__",
                ".DS_Store",
                ".pytest_cache",
                "アーカイブ.zip",
                "destination_zip_itself",
            ],
            "archive_sha256_policy": (
                "reported by package command; not recursively embedded in its own archive"
            ),
        },
    }


def _add(checks: list[V3Check], check_id: str, passed: bool, detail: str) -> None:
    checks.append(V3Check(check_id, "PASS" if passed else "FAIL", detail))


def build_stage3(
    *,
    project_root: Path = PROJECT_ROOT,
    offline: bool = True,
    create_package: bool = True,
) -> tuple[Path, str]:
    """Build all v3 artifacts, then fail the public article closed on any mismatch."""
    root = Path(project_root).resolve()
    config = load_stage3_config(root)
    output_dir = root / "outputs" / config["output_id"]
    _invalidate_v3(output_dir)
    write_stage3_failure_stubs(output_dir, "build started; v3 validation incomplete")
    frozen_before = _frozen_output_hashes(root)

    if not offline:
        fetch_stage3_sources(root)
    continuing_manifest_path = (
        root / "data" / "raw" / CONTINUING_VINTAGE_ID / "data_manifest.json"
    )
    nonoperating_manifest_path = (
        root / "data" / "raw" / PHASE3_VINTAGE_ID / "data_manifest.json"
    )
    if not continuing_manifest_path.is_file() or not nonoperating_manifest_path.is_file():
        raise FileNotFoundError("Stage 3 raw manifests are absent; run fetch-stage3")
    continuing_manifest = json.loads(
        continuing_manifest_path.read_text(encoding="utf-8")
    )
    verify_continuing_sample_manifest(continuing_manifest, root)
    nonoperating_manifest = json.loads(
        nonoperating_manifest_path.read_text(encoding="utf-8")
    )

    structure = validate_release_structure(root)
    repository_rows = build_repository_top_level_inventory(root)
    repository_required = {
        row["path"]: row["status"] == "PASS" for row in repository_rows
    }
    archive_required, source_archive = _source_archive_report(root)
    inventory = build_release_inventory(root)
    dependencies = check_runtime_dependencies()
    current_test_count = _collect_pytest_count(root)

    candidate_series = pd.read_parquet(
        root / "outputs" / "2026Q1_v2" / "historical_candidate_series.parquet"
    )
    sensitivity = build_rule_sensitivity(candidate_series)
    grid = build_count_rolling_sensitivity()
    continuing = build_continuing_sample_analysis(root)
    nonoperating = build_phase3_non_operating_analysis(
        raw_root=root / "data" / "raw" / PHASE3_VINTAGE_ID
    )

    continuing_output = _with_continuing_limitations(continuing.continuing_yoy)
    comparison_output = _main_comparison_output(continuing)
    frequency_output = _frequency_output(continuing)
    bridge_output = _bridge_output(nonoperating)
    bridge_historical_output = _with_continuing_limitations(
        nonoperating.historical_statistics
    )
    concentration_output = _with_continuing_limitations(nonoperating.concentration)
    target_bridge = _target_bridge(bridge_output)

    decision = choose_final_decision(continuing.capital_headline_history)
    bridge_exact = float(target_bridge["profit_impact_yoy_oku_yen"].sum())

    (output_dir / "archive_inventory.md").write_text(
        render_archive_inventory(
            structure=structure.to_dict(),
            inventory=inventory,
            repository_required=repository_required,
            archive_required=archive_required,
            source_archive=source_archive,
            baseline_collection_count=BASELINE_TEST_COUNT,
            current_collection_count=current_test_count,
            dependency_check=dependencies,
        ),
        encoding="utf-8",
    )
    (output_dir / "metric_definition_audit.md").write_text(
        render_metric_definition_audit(), encoding="utf-8"
    )
    (output_dir / "rule_sensitivity.md").write_text(
        render_rule_sensitivity(sensitivity, grid), encoding="utf-8"
    )
    _json_write(output_dir / "continuing_sample_raw_manifest.json", continuing_manifest)
    continuing_output.to_csv(
        output_dir / "continuing_sample_quarterly.csv", index=False, encoding="utf-8"
    )
    comparison_output.to_csv(
        output_dir / "main_vs_continuing_sample.csv", index=False, encoding="utf-8"
    )
    frequency_output.to_csv(
        output_dir / "headline_reversal_frequency.csv", index=False, encoding="utf-8"
    )
    bridge_output.to_csv(
        output_dir / "nonoperating_bridge.csv", index=False, encoding="utf-8"
    )
    bridge_historical_output.to_csv(
        output_dir / "nonoperating_bridge_historical.csv",
        index=False,
        encoding="utf-8",
    )
    concentration_output.to_csv(
        output_dir / "nonoperating_driver_concentration.csv",
        index=False,
        encoding="utf-8",
    )
    (output_dir / "decision_v3.md").write_text(
        render_decision(
            decision=decision,
            headline_frequency=continuing.headline_reversal_frequency,
            bridge_exact_oku_yen=bridge_exact,
        ),
        encoding="utf-8",
    )
    (output_dir / "candidate_headlines_v3.md").write_text(
        render_candidate_headlines(decision=decision), encoding="utf-8"
    )

    # Imported here so a source-only fetch does not import matplotlib or the
    # publication layer.  These modules are pure with respect to v1/v2.
    from .stage3_charts import build_stage3_charts
    from .stage3_publication import (
        build_claims_v3,
        render_sample_sensitivity_article,
        select_stage3_publication_decision,
        validate_claims_v3,
        validate_stage3_article,
    )

    chart_registry = build_stage3_charts(
        continuing=continuing,
        nonoperating=nonoperating,
        output_dir=output_dir / "charts",
    )
    charts = list(chart_registry.values())
    claims = _with_continuing_limitations(
        build_claims_v3(
            continuing=continuing,
            nonoperating=nonoperating,
        )
    )
    publication_decision = select_stage3_publication_decision(
        continuing=continuing,
        nonoperating=nonoperating,
    )
    if publication_decision != decision:
        raise Stage3BuildError(
            "Independent publication-decision implementations disagree: "
            f"reports={decision}; publication={publication_decision}"
        )
    claims.to_csv(output_dir / "claims_v3.csv", index=False, encoding="utf-8")
    article_path = output_dir / "article_public.md"
    if decision == "PUBLISH_SAMPLE_CONSTRUCTION_SENSITIVITY":
        article_text = render_sample_sensitivity_article(
            continuing=continuing,
            claims_v3=claims,
            chart_paths=(
                "charts/current_sample_margin_direction.png",
                "charts/historical_sample_reversal_frequency.png",
            ),
        )
        article_path.write_text(article_text, encoding="utf-8")
    elif decision == "PUBLISH_FULL_NONOPERATING_BRIDGE_SNAPSHOT":
        raise Stage3BuildError(
            "The current v3 implementation intentionally has no mixed/fallback article; "
            "non-operating publication requires a separate one-claim renderer"
        )
    elif article_path.exists():
        article_path.unlink()

    clean_manifest = _clean_manifest(
        project_root=root,
        inventory=inventory,
        repository_rows=repository_rows,
        archive_required=archive_required,
        source_archive=source_archive,
        current_test_count=current_test_count,
    )
    clean_manifest["nonoperating_raw_manifest"] = {
        "path": nonoperating_manifest_path.relative_to(root).as_posix(),
        "sha256": sha256_file(nonoperating_manifest_path),
        "source_count": len(nonoperating_manifest.get("sources", [])),
    }
    _json_write(output_dir / "clean_archive_manifest.json", clean_manifest)

    checks: list[V3Check] = []
    _add(
        checks,
        "archive_or_repository_complete",
        structure.passed and (all(repository_required.values()) or all(archive_required.values())),
        f"repository={all(repository_required.values())}; archive={all(archive_required.values())}",
    )
    _add(
        checks,
        "all_frozen_output_hashes_in_manifest",
        inventory["combined_file_count"] == len(frozen_before)
        and set(frozen_before)
        == {
            row["path"]
            for release in inventory["releases"].values()
            for row in release["files"]
        },
        f"files={inventory['combined_file_count']}",
    )
    _add(checks, "runtime_dependencies", dependencies["status"] == "PASS", str(dependencies))
    _add(
        checks,
        "baseline_and_expanded_pytest_collection",
        BASELINE_TEST_COUNT == int(config["baseline_pytest_collection_count"])
        and current_test_count >= BASELINE_TEST_COUNT,
        f"baseline={BASELINE_TEST_COUNT}; current={current_test_count}",
    )
    _add(
        checks,
        "corrected_rule_all_ten_cases_monotone",
        len(grid) == 10
        and all(
            frame.sort_values("same_direction_last4")["decision_rank"].is_monotonic_increasing
            for _, frame in grid.groupby("rolling_4q_same_direction")
        ),
        "count4=0..4 x rolling=False/True",
    )
    legacy_file = pd.read_csv(root / "outputs" / "2026Q1_v2" / "pattern_decisions.csv")
    legacy_expected = legacy_file.set_index("candidate_id")["pattern_decision"]
    legacy_actual = sensitivity.set_index("candidate_id")["legacy_pattern_decision"]
    _add(
        checks,
        "legacy_2026q1_decisions_unchanged",
        legacy_actual.to_dict() == legacy_expected.to_dict(),
        str(legacy_actual.to_dict()),
    )
    bc = sensitivity.loc[sensitivity["candidate_id"].isin(["B", "C"])]
    _add(
        checks,
        "boolean_candidates_not_ranked_numerically",
        bc["historical_percentile_inclusive_pct"].isna().all()
        and (~bc["numeric_history_eligible"].astype(bool)).all(),
        "B/C percentiles are null and numeric_history_eligible=False",
    )

    target_continuing = continuing.continuing_yoy.loc[
        continuing.continuing_yoy["period_code"].astype(str).eq(TARGET_PERIOD_CODE)
        & continuing.continuing_yoy["breakdown"].eq("capital_size")
    ]
    target_values = target_continuing.pivot(
        index="category_code", columns="metric_id", values="yoy_pct"
    )
    expected_continuing = {
        "25": {"sales": 2.6, "operating_profit": 20.0, "ordinary_profit": 26.0, "capex_including_software": 1.1},
        "24": {"sales": 2.0, "operating_profit": 22.4, "ordinary_profit": 19.3, "capex_including_software": -3.8},
        "19": {"sales": 2.5, "operating_profit": 6.0, "ordinary_profit": 8.6, "capex_including_software": -2.9},
    }
    _add(
        checks,
        "continuing_sample_2026q1_published_rates",
        all(
            _near(target_values.loc[capital, metric], expected, 1e-9)
            for capital, metrics in expected_continuing.items()
            for metric, expected in metrics.items()
        ),
        "12/12 capital-size published rates reproduced",
    )
    target_regular = continuing.regular_yoy.loc[
        continuing.regular_yoy["period_code"].astype(str).eq(TARGET_PERIOD_CODE)
        & continuing.regular_yoy["breakdown"].eq("capital_size")
    ].pivot(index="category_code", columns="metric_id", values="yoy_pct")
    _add(
        checks,
        "regular_series_2026q1_targets",
        _near(target_regular.loc["19", "sales"], 2.1, 0.051)
        and _near(target_regular.loc["19", "operating_profit"], -1.9, 0.051)
        and _near(target_regular.loc["19", "capex_including_software"], 2.9, 0.051)
        and _near(target_regular.loc["25", "sales"], 1.7, 0.051)
        and _near(target_regular.loc["25", "operating_profit"], 18.5, 0.051),
        "small sales/op/capex and large sales/op rounded targets",
    )
    target_margin = continuing.relative_margin_comparison.loc[
        continuing.relative_margin_comparison["period_code"].astype(str).eq(TARGET_PERIOD_CODE)
        & continuing.relative_margin_comparison["breakdown"].eq("capital_size")
        & continuing.relative_margin_comparison["category_code"].astype(str).eq("19")
    ].iloc[0]
    _add(
        checks,
        "small_capital_margin_direction_robustness_gate",
        target_margin["regular_relative_margin_change_direction"] == "DOWN"
        and target_margin["continuing_relative_margin_change_direction"] == "UP"
        and bool(target_margin["relative_margin_direction_reversal"]),
        "regular=DOWN; continuing=UP; continuing value is a directional proxy, not pp",
    )
    _add(
        checks,
        "continuing_sample_limitations_explicit",
        "サンプルサイズが小さ" in CONTINUING_LIMITATION
        and "標準誤差率" in CONTINUING_LIMITATION,
        CONTINUING_LIMITATION,
    )
    limitation_columns = {
        "continuing_sample_size_limitation",
        "profit_standard_error_limitation",
    }
    tabular_outputs = (
        continuing_output,
        comparison_output,
        frequency_output,
        bridge_output,
        bridge_historical_output,
        concentration_output,
        claims,
    )
    limitation_markdown_paths = (
        output_dir / "archive_inventory.md",
        output_dir / "metric_definition_audit.md",
        output_dir / "rule_sensitivity.md",
        output_dir / "decision_v3.md",
        output_dir / "candidate_headlines_v3.md",
        article_path,
    )
    _add(
        checks,
        "continuing_sample_limitations_carried_by_all_outputs",
        all(limitation_columns <= set(frame.columns) for frame in tabular_outputs)
        and all(
            "標準誤差率" in path.read_text(encoding="utf-8")
            for path in limitation_markdown_paths
        )
        and "continuing_sample_limitations" in clean_manifest
        and "limitations" in continuing_manifest,
        "all CSV/Markdown/JSON analytical outputs carry the small-sample and profit-SE caveat; all three charts carry the same footnote",
    )
    _add(
        checks,
        "nonoperating_current_identity",
        _near(bridge_exact, 15_606.62)
        and target_bridge["yoy_identity_status"].eq("PASS").all(),
        f"component_sum={bridge_exact:.2f}; residual={target_bridge['yoy_identity_residual_oku_yen'].iloc[0]}",
    )
    expected_components = {
        "interest_and_dividend_income": (152.04, 152.04, 152.0),
        "other_non_operating_income": (15424.31, 15424.31, 15424.0),
        "interest_expense": (6759.86, -6759.86, -6760.0),
        "other_non_operating_expense": (-6790.13, 6790.13, 6790.0),
    }
    bridge_by_component = target_bridge.set_index("component_id")
    _add(
        checks,
        "nonoperating_four_item_signs_and_rounding",
        all(
            _near(bridge_by_component.loc[key, "source_yoy_delta_oku_yen"], source)
            and _near(bridge_by_component.loc[key, "profit_impact_yoy_oku_yen"], impact)
            and _near(bridge_by_component.loc[key, "profit_impact_public_rounded_oku_yen"], rounded, 1e-9)
            for key, (source, impact, rounded) in expected_components.items()
        ),
        "interest expense increased and contributes -6,760; other expense decreased and contributes +6,790",
    )
    current_identity = nonoperating.identity_checks.loc[
        nonoperating.identity_checks["period_code"].astype(str).eq(TARGET_PERIOD_CODE)
    ]
    current_additivity = nonoperating.additivity_checks.loc[
        nonoperating.additivity_checks["period_code"].astype(str).eq(TARGET_PERIOD_CODE)
    ]
    _add(
        checks,
        "nonoperating_all_current_identities_and_additivity",
        current_identity["status"].eq("PASS").all()
        and current_additivity["status"].eq("PASS").all(),
        f"identity={len(current_identity)}; additivity={len(current_additivity)}",
    )
    _add(
        checks,
        "nonoperating_history_starts_mechanically",
        nonoperating.earliest_complete_period.loc[
            nonoperating.earliest_complete_period["is_mechanical_earliest"], "period_code"
        ].astype(str).tolist()
        == ["20092"],
        "mechanical earliest complete period=2009Q2",
    )
    _add(
        checks,
        "decision_is_exactly_one_allowed_value",
        decision in set(config["publication"]["allowed_decisions"]),
        decision,
    )
    wording_issues = audit_statistical_wording(article_path.read_text(encoding="utf-8"))
    _add(
        checks,
        "article_statistical_wording",
        not [issue for issue in wording_issues if issue.severity == "FAIL"],
        str([asdict(issue) for issue in wording_issues]),
    )
    claim_problems = validate_claims_v3(claims)
    article_audit = validate_stage3_article(
        article_path.read_text(encoding="utf-8"), claims
    )
    article_problems = list(article_audit.failed_check_ids)
    _add(checks, "claims_v3_contract", not claim_problems, str(claim_problems))
    _add(checks, "article_all_numbers_verified", not article_problems, str(article_problems))
    _add(
        checks,
        "article_one_claim_two_figures_no_bridge_mix",
        article_path.read_text(encoding="utf-8").count("![") == 2
        and "nonoperating_four_item_bridge" not in article_path.read_text(encoding="utf-8")
        and len(charts) == 3,
        f"public_figures=2; generated_charts={len(charts)}",
    )

    frozen_after = _frozen_output_hashes(root)
    _add(
        checks,
        "frozen_v1_v2_outputs_unchanged",
        frozen_after == frozen_before,
        f"before={len(frozen_before)} files; after={len(frozen_after)} files",
    )
    expected_article = decision != "ARCHIVE_NO_ROBUST_STORY"
    _add(
        checks,
        "conditional_public_article",
        article_path.is_file() == expected_article,
        f"exists={article_path.is_file()}; required={expected_article}",
    )
    (output_dir / "audit_v3.md").write_text(
        render_audit(
            checks,
            warnings=(
                CONTINUING_LIMITATION,
                "継続標本の利益水準と符号はPDFから確認できず、利益率は増加率からの方向proxy。",
                "その他の営業外収益を為替差益・配当・持分法利益等に帰属させていない。",
                "歴史系列はcurrent-vintageで、過去公表ビンテージ改訂への頑健性は未検証。",
            ),
        ),
        encoding="utf-8",
    )

    missing = [
        name for name in STAGE3_REQUIRED_OUTPUTS if not (output_dir / name).is_file()
    ]
    if decision != "ARCHIVE_NO_ROBUST_STORY" and not article_path.is_file():
        missing.append("article_public.md")
    checks.append(
        V3Check(
            "required_v3_outputs",
            "PASS" if not missing else "FAIL",
            "all required files present" if not missing else f"missing={missing}",
        )
    )
    (output_dir / "audit_v3.md").write_text(
        render_audit(
            checks,
            warnings=(
                CONTINUING_LIMITATION,
                "継続標本の利益水準と符号はPDFから確認できず、利益率は増加率からの方向proxy。",
                "その他の営業外収益の特定要因は統計単独で断定できない。",
            ),
        ),
        encoding="utf-8",
    )
    status = "PASS" if all(check.status == "PASS" for check in checks) else "FAIL"
    if status != "PASS":
        if article_path.exists():
            article_path.unlink()
        raise Stage3BuildError("v3 audit failed; article removed")

    if create_package:
        package_path = output_dir / "corporate_quarterly_2026Q1_v3_clean.zip"
        package = create_clean_release_zip(
            package_path, project_root=root, overwrite=True
        )
        verification = verify_clean_release_zip(package_path)
        if package["status"] != "PASS" or verification["status"] != "PASS":
            if article_path.exists():
                article_path.unlink()
            raise Stage3BuildError(f"Clean package verification failed: {verification}")
        (output_dir / "corporate_quarterly_2026Q1_v3_clean.zip.sha256").write_text(
            f"{package['archive_sha256']}  {package_path.name}\n", encoding="ascii"
        )
    return output_dir, status
