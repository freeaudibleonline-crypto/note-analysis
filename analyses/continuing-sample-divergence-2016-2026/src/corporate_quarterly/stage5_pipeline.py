"""Fail-closed orchestration for the 2026Q1 v3.2 final public release."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Mapping

import pandas as pd

from .constants import PROJECT_ROOT
from .stage5_claims import build_stage5_claim_artifacts
from .stage5_charts import build_stage5_charts, chart_manifest_payload
from .stage5_package import (
    PACKAGE_FILENAME,
    create_stage5_clean_zip,
    verify_stage5_clean_zip,
)
from .stage5_publication import (
    render_article_note_public_v3_2,
    render_article_note_v3_2,
)


STAGE5_CONFIG = "stage5_2026Q1.json"
OUTPUT_ID = "2026Q1_v3_2"
FROZEN_V3_1_ID = "2026Q1_v3_1"
PROTECTED_OUTPUT_IDS = ("2026Q1", "2026Q1_v2", "2026Q1_v3", FROZEN_V3_1_ID)
MINIMUM_EXISTING_TEST_COUNT = 213
STAGE5_REQUIRED_OUTPUTS = (
    "article_note.md",
    "article_note_render.md",
    "claims_v3_2.csv",
    "claim_corrections_v3_2.csv",
    "mismatch_heatmap.csv",
    "headline_2x2.csv",
    "deadband_sensitivity.csv",
    "rounding_sensitivity.csv",
    "unit_registry.json",
    "chart_manifest_v3_2.json",
    "expected_value_changes_v3_2.csv",
    "audit_v3_2.md",
    "v3_1_immutability_manifest.json",
    PACKAGE_FILENAME,
)
STAGE5_CHARTS = (
    "mismatch_heatmap.png",
    "headline_2x2.png",
    "deadband_sensitivity.png",
)


class Stage5BuildError(RuntimeError):
    """A v3.2 data, code, test, or publication contract failed."""


class Stage5ImmutabilityError(Stage5BuildError):
    """A protected prior output changed during the build."""


def load_stage5_config(project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    root = Path(project_root).resolve()
    path = root / "config" / STAGE5_CONFIG
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("CONFIG_KIND") != "EXECUTABLE_STAGE5_FINAL_RELEASE_CONFIGURATION":
        raise Stage5BuildError(f"Not an executable Stage 5 config: {path}")
    if config.get("output_id") != OUTPUT_ID:
        raise Stage5BuildError(f"Stage 5 output_id must remain {OUTPUT_ID}")
    protected = {str(value) for value in config.get("protected_output_directories", [])}
    expected = {f"outputs/{value}" for value in PROTECTED_OUTPUT_IDS}
    if not expected <= protected:
        raise Stage5BuildError(f"Stage 5 protection list is incomplete: {expected-protected}")
    if config.get("offline_only") is not True:
        raise Stage5BuildError("Stage 5 must remain offline-only")
    return config


def _snapshot_tree(root: Path) -> dict[str, str]:
    if not root.is_dir():
        raise Stage5BuildError(f"Protected output directory is missing: {root}")
    from .stage5_audit import snapshot_sha256_tree

    return snapshot_sha256_tree(root)


def _protected_snapshots(output_root: Path) -> dict[str, dict[str, str]]:
    return {
        release_id: _snapshot_tree(output_root / release_id)
        for release_id in PROTECTED_OUTPUT_IDS
    }


def _assert_protected_unchanged(
    output_root: Path,
    expected: Mapping[str, Mapping[str, str]],
) -> None:
    drift: list[str] = []
    for release_id, before in expected.items():
        after = _snapshot_tree(output_root / release_id)
        if dict(before) != after:
            missing = sorted(set(before) - set(after))
            added = sorted(set(after) - set(before))
            changed = sorted(
                path for path in set(before) & set(after) if before[path] != after[path]
            )
            drift.append(
                f"{release_id}:missing={missing};added={added};changed={changed}"
            )
    if drift:
        raise Stage5ImmutabilityError(" | ".join(drift))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def _v32_heatmap(v3_1_dir: Path) -> pd.DataFrame:
    frame = pd.read_csv(
        v3_1_dir / "mismatch_heatmap.csv", dtype={"capital_code": str}
    )
    old = "continuing_decision_margin_abs_gap_median_pct"
    new = "continuing_decision_margin_abs_gap_median_pp"
    if old not in frame or new in frame:
        raise Stage5BuildError(
            f"Expected exactly the legacy decision-margin column before correction: {old}"
        )
    result = frame.rename(columns={old: new})
    result["mismatch_rate_unit"] = "percent"
    result["continuing_decision_margin_abs_gap_median_unit"] = "percentage_points"
    result["cross_series_growth_gap_divergence_median_unit"] = "percentage_points"
    if old in result or new not in result:
        raise Stage5BuildError("Decision-margin column rename failed")
    return result


def _v32_headline(v3_1_dir: Path) -> pd.DataFrame:
    result = pd.read_csv(v3_1_dir / "headline_2x2.csv")
    result["quarter_count_unit"] = "count"
    result["share_unit"] = "percent"
    return result


def _v32_deadband(v3_1_dir: Path) -> pd.DataFrame:
    result = pd.read_csv(v3_1_dir / "deadband_sensitivity.csv")
    result["legacy_unit_v3_1"] = result.get("unit", "")
    result["unit"] = "percent"
    result["deadband_threshold_unit"] = "percent"
    result["mismatch_rate_unit"] = "percent"
    result["unit_definition"] = (
        "営業利益率の推定相対変化率に対する％。"
        "営業利益率の絶対的なパーセントポイント差ではない。"
    )
    return result


def _v32_rounding(v3_1_dir: Path) -> pd.DataFrame:
    result = pd.read_csv(v3_1_dir / "rounding_sensitivity.csv")
    result["yoy_growth_rate_unit"] = "percent"
    result["growth_rate_difference_unit"] = "percentage_points"
    result["rounding_half_width_unit"] = "percentage_points"
    result["ambiguity_threshold_unit"] = "percentage_points"
    return result


def _normalise_chart_manifest_paths(
    payload: dict[str, Any],
    *,
    output_dir: Path,
) -> dict[str, Any]:
    """Make manifest paths portable while keeping hashes from fresh renders."""
    result = json.loads(json.dumps(payload, ensure_ascii=False))
    for entry in result.get("charts", []):
        source = Path(str(entry["source_csv"]))
        entry["source_csv"] = source.name
        for additional in entry.get("additional_sources", []):
            additional["source_csv"] = Path(str(additional["source_csv"])).name
        entry["png_path"] = f"charts/{Path(str(entry['png_path'])).name}"
    result["lineage"] = {
        "numeric_source": "canonical release CSVs",
        "branches": ["claims_v3_2.csv", "charts/*.png", "article_note.md"],
        "prohibited_topology": "claims-only chart generation",
    }
    result["release_output_directory"] = f"outputs/{OUTPUT_ID}"
    return result


def _safe_clear_staging(staging: Path, output_root: Path) -> None:
    staging = staging.resolve()
    output_root = output_root.resolve()
    if staging.parent != output_root or staging.name != f".{OUTPUT_ID}.__building__":
        raise Stage5BuildError(f"Unsafe staging path: {staging}")
    if staging.exists():
        shutil.rmtree(staging)


def _run_full_tests(project_root: Path, output_dir: Path) -> tuple[int, str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = "src"
    environment["CORPORATE_STAGE5_OUTPUT_DIR"] = str(output_dir)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q"],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    combined = result.stdout + "\n" + result.stderr
    matches = re.findall(r"(\d+) passed", combined)
    count = int(matches[-1]) if matches else 0
    if result.returncode != 0 or count < MINIMUM_EXISTING_TEST_COUNT:
        raise Stage5BuildError(
            f"Full pytest failed or regressed below {MINIMUM_EXISTING_TEST_COUNT}: "
            + combined[-4_000:].replace("\n", " ")
        )
    return count, combined


def _audit_text_with_tests(text: str, test_count: int) -> str:
    suffix = (
        "\n## 全テスト\n\n"
        f"- status: PASS\n- passed: {test_count}\n"
        f"- minimum_existing_test_count: {MINIMUM_EXISTING_TEST_COUNT}\n"
    )
    return text.rstrip() + "\n" + suffix


def _assert_exact_outputs(output_dir: Path) -> None:
    files = {
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file()
    }
    expected = set(STAGE5_REQUIRED_OUTPUTS) | {
        f"charts/{name}" for name in STAGE5_CHARTS
    }
    if files != expected:
        raise Stage5BuildError(
            f"Unexpected v3.2 members: missing={sorted(expected-files)}; "
            f"extra={sorted(files-expected)}"
        )


def write_stage5_failure(output_dir: Path, reason: str, *, immutability: bool) -> None:
    """Write the required fail marker and ensure no public ZIP remains."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    package = output / PACKAGE_FILENAME
    if package.is_file():
        package.unlink()
    marker = "IMMUTABILITY_FAIL.md" if immutability else "FINAL_RELEASE_FAIL.md"
    safe = str(reason).replace("|", "／").replace("\n", " ")
    (output / marker).write_text(
        f"# {marker.removesuffix('.md')}\n\n"
        "**STATUS: FAIL**\n\n"
        f"- reason: {safe}\n",
        encoding="utf-8",
    )


def build_stage5(
    project_root: Path = PROJECT_ROOT,
    *,
    offline: bool = True,
    run_tests: bool = True,
) -> tuple[Path, str, int]:
    """Build, test, audit, package, and re-audit the v3.2 final release."""
    if not offline:
        raise Stage5BuildError("Stage 5 is offline-only")
    root = Path(project_root).resolve()
    load_stage5_config(root)
    output_root = root / "outputs"
    output_dir = output_root / OUTPUT_ID
    staging = output_root / f".{OUTPUT_ID}.__building__"
    v3_1_dir = output_root / FROZEN_V3_1_ID
    if output_dir.exists():
        raise Stage5BuildError(f"Refusing to overwrite existing v3.2 output: {output_dir}")

    protected_before = _protected_snapshots(output_root)
    _safe_clear_staging(staging, output_root)
    staging.mkdir(parents=True)
    published = False
    try:
        claim_artifacts = build_stage5_claim_artifacts(root)
        heatmap = _v32_heatmap(v3_1_dir)
        headline = _v32_headline(v3_1_dir)
        deadband = _v32_deadband(v3_1_dir)
        rounding = _v32_rounding(v3_1_dir)

        _write_csv(staging / "mismatch_heatmap.csv", heatmap)
        _write_csv(staging / "headline_2x2.csv", headline)
        _write_csv(staging / "deadband_sensitivity.csv", deadband)
        _write_csv(staging / "rounding_sensitivity.csv", rounding)
        _write_csv(staging / "claims_v3_2.csv", claim_artifacts.claims_v3_2)
        _write_csv(
            staging / "claim_corrections_v3_2.csv",
            claim_artifacts.claim_corrections_v3_2,
        )
        _write_csv(
            staging / "expected_value_changes_v3_2.csv",
            claim_artifacts.expected_value_changes_v3_2,
        )
        _write_json(staging / "unit_registry.json", claim_artifacts.unit_registry)

        charts = build_stage5_charts(
            mismatch_heatmap=staging / "mismatch_heatmap.csv",
            headline_2x2=staging / "headline_2x2.csv",
            deadband_sensitivity=staging / "deadband_sensitivity.csv",
            unit_registry=claim_artifacts.unit_registry,
            claims_lineage=claim_artifacts.claims_v3_2,
            output_dir=staging / "charts",
        )
        chart_manifest = _normalise_chart_manifest_paths(
            chart_manifest_payload(charts), output_dir=staging
        )
        _write_json(staging / "chart_manifest_v3_2.json", chart_manifest)

        article = render_article_note_v3_2(
            claims_v3_2=claim_artifacts.claims_v3_2
        )
        rendered = render_article_note_public_v3_2(article)
        (staging / "article_note.md").write_text(article, encoding="utf-8")
        (staging / "article_note_render.md").write_text(rendered, encoding="utf-8")

        _assert_protected_unchanged(output_root, protected_before)
        from .stage5_audit import (
            audit_stage5_release,
            build_v3_1_immutability_manifest,
            render_stage5_audit,
        )

        immutability_manifest = build_v3_1_immutability_manifest(
            v3_1_dir,
            protected_before[FROZEN_V3_1_ID],
        )
        _write_json(
            staging / "v3_1_immutability_manifest.json", immutability_manifest
        )
        pre_audit = audit_stage5_release(
            staging,
            frozen_v3_1_dir=v3_1_dir,
            frozen_v3_1_sha256=protected_before[FROZEN_V3_1_ID],
            project_root=root,
            phase="pre_audit",
            require_existing_audit=False,
            require_package=False,
        )
        if not pre_audit.passed:
            raise Stage5BuildError(
                f"Pre-release audit failed: {pre_audit.failed_check_ids}"
            )
        (staging / "audit_v3_2.md").write_text(
            render_stage5_audit(pre_audit), encoding="utf-8"
        )

        test_count = 0
        if run_tests:
            test_count, _ = _run_full_tests(root, staging)
        (staging / "audit_v3_2.md").write_text(
            _audit_text_with_tests(
                render_stage5_audit(pre_audit), test_count
            ),
            encoding="utf-8",
        )

        _assert_protected_unchanged(output_root, protected_before)
        staging.rename(output_dir)
        published = True
        create_stage5_clean_zip(
            output_dir / PACKAGE_FILENAME,
            project_root=root,
        )

        final_audit = audit_stage5_release(
            output_dir,
            frozen_v3_1_dir=v3_1_dir,
            frozen_v3_1_sha256=protected_before[FROZEN_V3_1_ID],
            project_root=root,
            phase="final",
            require_existing_audit=True,
            require_package=True,
        )
        if not final_audit.passed:
            raise Stage5BuildError(
                f"Final release audit failed: {final_audit.failed_check_ids}"
            )
        final_text = _audit_text_with_tests(
            render_stage5_audit(final_audit), test_count
        )
        (output_dir / "audit_v3_2.md").write_text(final_text, encoding="utf-8")
        create_stage5_clean_zip(
            output_dir / PACKAGE_FILENAME,
            project_root=root,
            overwrite=True,
        )
        if verify_stage5_clean_zip(output_dir / PACKAGE_FILENAME)["status"] != "PASS":
            raise Stage5BuildError("Final clean ZIP verification failed")
        confirmed = audit_stage5_release(
            output_dir,
            frozen_v3_1_dir=v3_1_dir,
            frozen_v3_1_sha256=protected_before[FROZEN_V3_1_ID],
            project_root=root,
            phase="final",
            require_existing_audit=True,
            require_package=True,
        )
        if not confirmed.passed:
            raise Stage5BuildError(
                f"Post-package audit failed: {confirmed.failed_check_ids}"
            )
        _assert_protected_unchanged(output_root, protected_before)
        _assert_exact_outputs(output_dir)
        return output_dir, "PASS", test_count
    except Stage5ImmutabilityError:
        if not published:
            _safe_clear_staging(staging, output_root)
        write_stage5_failure(output_dir, "protected output SHA-256 mismatch", immutability=True)
        raise
    except Exception as exc:
        if not published:
            _safe_clear_staging(staging, output_root)
        write_stage5_failure(
            output_dir,
            f"{type(exc).__name__}: {exc}",
            immutability=False,
        )
        raise
