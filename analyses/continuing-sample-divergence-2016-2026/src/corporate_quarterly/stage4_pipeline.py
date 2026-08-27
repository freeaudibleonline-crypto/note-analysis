"""Atomic, fail-closed orchestration for the 2026Q1 v3.1 public note.

Stage 4 is deliberately analysis-only.  It reuses the already frozen source
vintages, snapshots every file in ``outputs/2026Q1_v3`` before doing any
work, and publishes only to ``outputs/2026Q1_v3_1``.  No network acquisition
or prior-output mutation is part of this stage.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any

import numpy as np
import pandas as pd

from .constants import PROJECT_ROOT
from .stage2_continuing_sample import (
    LIMITATION_NOTES,
    build_continuing_sample_analysis,
)
from .stage4_analysis import (
    EXPLORATORY_BACKTEST_STATUS,
    SAMPLE_ERROR_STATUS,
    SERIES_COMPARABILITY_NOTE,
    Stage4Analysis,
    build_stage4_analysis,
)
from .stage4_audit import (
    REQUIRED_STAGE4_CHART_FILENAMES,
    audit_stage4_release,
    render_stage4_audit,
    snapshot_sha256_tree,
)
from .stage4_charts import build_stage4_charts
from .stage4_publication import (
    build_claims_v3_1,
    render_article_note,
    validate_article_note,
    validate_claims_v3_1,
)


STAGE4_CONFIG = "stage4_2026Q1.json"
OUTPUT_ID = "2026Q1_v3_1"
FROZEN_INPUT_ID = "2026Q1_v3"
STAGE4_TOP_LEVEL_OUTPUTS = (
    "article_note.md",
    "headline_2x2.csv",
    "mismatch_heatmap.csv",
    "rounding_sensitivity.csv",
    "deadband_sensitivity.csv",
    "claims_v3_1.csv",
    "audit_v3_1.md",
)


class Stage4BuildError(RuntimeError):
    """Raised when the v3.1 publication contract cannot be satisfied."""


def load_stage4_config(project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Load and validate the executable v3.1 publication configuration."""
    root = Path(project_root)
    path = root / "config" / STAGE4_CONFIG
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("CONFIG_KIND") != "EXECUTABLE_STAGE4_PUBLICATION_CONFIGURATION":
        raise Stage4BuildError(f"Not an executable Stage 4 config: {path}")
    if config.get("output_id") != OUTPUT_ID:
        raise Stage4BuildError(f"Stage 4 output_id must remain {OUTPUT_ID}")
    if config.get("input_release") != f"outputs/{FROZEN_INPUT_ID}":
        raise Stage4BuildError(f"Stage 4 input_release must remain outputs/{FROZEN_INPUT_ID}")
    protected = {str(item) for item in config.get("protected_output_directories", [])}
    if f"outputs/{FROZEN_INPUT_ID}" not in protected:
        raise Stage4BuildError("The frozen v3 directory is not protected by config")
    return config


def _with_common_limitations(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach limitations to every published table without altering rows."""
    result = frame.copy()
    result["exploratory_backtest_status"] = EXPLORATORY_BACKTEST_STATUS
    result["series_comparability_limitation"] = SERIES_COMPARABILITY_NOTE
    result["continuing_sample_size_limitation"] = LIMITATION_NOTES["small_sample"]
    result["profit_standard_error_limitation"] = LIMITATION_NOTES[
        "profit_standard_error"
    ]
    result["continuing_margin_interpretation"] = LIMITATION_NOTES[
        "relative_margin_proxy"
    ]
    result["sample_error_status"] = SAMPLE_ERROR_STATUS
    return result


def _enrich_rounding_sensitivity(
    stage4: Stage4Analysis,
    continuing: Any,
) -> pd.DataFrame:
    """Join direction/headline results and the mechanical >100% review flag."""
    rounding = stage4.rounding_sensitivity.copy()
    rounding["period_code"] = rounding["period_code"].astype(str)

    relative = continuing.relative_margin_comparison.copy()
    relative = relative.loc[
        relative["breakdown"].eq("capital_size")
        & relative["category_code"].astype(str).eq("19")
    ].copy()
    relative["period_code"] = relative["period_code"].astype(str)
    relative = relative[
        ["period_code", "relative_margin_direction_reversal"]
    ]

    headline = continuing.capital_headline_history.copy()
    headline["period_code"] = headline["period_code"].astype(str)
    headline = headline[["period_code", "headline_reversal"]]

    result = rounding.merge(relative, on="period_code", how="left", validate="one_to_one")
    result = result.merge(headline, on="period_code", how="left", validate="one_to_one")
    result["relative_margin_direction_reversal"] = pd.array(
        result["relative_margin_direction_reversal"], dtype="boolean"
    )
    result["headline_reversal"] = pd.array(
        result["headline_reversal"], dtype="boolean"
    )
    extreme = result["continuing_operating_profit_yoy_pct"].abs().gt(100.0)
    result["extreme_yoy_rate_gt_100"] = extreme
    result["mechanical_flag"] = np.where(extreme, "NEAR_ZERO_BASE", "NOT_FLAGGED")
    result["mechanical_trigger"] = "abs(continuing_operating_profit_yoy_pct)>100"
    result["sensitivity_method"] = (
        "FIXED_41_QUARTER_EVENT_ATTRIBUTION_NOT_ROW_DELETION"
    )
    result["fixed_window_denominator_quarters"] = 41
    result["row_deletion_denominator_if_applied"] = int(41 - extreme.sum())
    margin_before = int(
        result["relative_margin_direction_reversal"].fillna(False).sum()
    )
    headline_before = int(result["headline_reversal"].fillna(False).sum())
    flagged_margin = int(
        result.loc[extreme, "relative_margin_direction_reversal"].fillna(False).sum()
    )
    flagged_headline = int(
        result.loc[extreme, "headline_reversal"].fillna(False).sum()
    )
    result["margin_reversal_count_fixed_window_before"] = margin_before
    result["margin_reversal_count_fixed_window_after_attribution"] = (
        margin_before - flagged_margin
    )
    result["headline_reversal_count_fixed_window_before"] = headline_before
    result["headline_reversal_count_fixed_window_after_attribution"] = (
        headline_before - flagged_headline
    )
    result["complete_case_reestimation_status"] = (
        "NOT_PERFORMED_DENOMINATOR_WOULD_CHANGE_TO_38"
    )
    result["flag_interpretation_note"] = (
        "NEAR_ZERO_BASE is a mechanical review label. "
        "EXTREME_YOY_RATE_GT_100 alone does not establish a low or near-zero base."
    )
    if int(extreme.sum()) != 3:
        raise Stage4BuildError(
            f"Expected three focus-tier >100% review flags; observed {int(extreme.sum())}"
        )
    if result.loc[extreme, "relative_margin_direction_reversal"].fillna(True).any():
        raise Stage4BuildError("A >100% review row is a margin-direction reversal")
    if result.loc[extreme, "headline_reversal"].fillna(True).any():
        raise Stage4BuildError("A >100% review row is a headline reversal")
    if (margin_before, headline_before) != (16, 11):
        raise Stage4BuildError(
            "Fixed-window reversal counts drifted: "
            f"margin={margin_before}, headline={headline_before}"
        )
    return _with_common_limitations(result)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8")


def _assert_exact_output_members(output_dir: Path) -> None:
    top_level = sorted(path.name for path in output_dir.iterdir() if path.is_file())
    expected_top = sorted(STAGE4_TOP_LEVEL_OUTPUTS)
    if top_level != expected_top:
        raise Stage4BuildError(
            f"Unexpected v3.1 top-level outputs: expected={expected_top}; observed={top_level}"
        )
    chart_dir = output_dir / "charts"
    charts = sorted(path.name for path in chart_dir.iterdir() if path.is_file())
    expected_charts = sorted(REQUIRED_STAGE4_CHART_FILENAMES)
    if charts != expected_charts:
        raise Stage4BuildError(
            f"Unexpected v3.1 charts: expected={expected_charts}; observed={charts}"
        )
    directories = sorted(path.name for path in output_dir.iterdir() if path.is_dir())
    if directories != ["charts"]:
        raise Stage4BuildError(f"Unexpected v3.1 directories: {directories}")


def _safe_clear_staging(staging: Path, output_root: Path) -> None:
    """Remove only the exact private staging directory owned by Stage 4."""
    staging_resolved = staging.resolve()
    output_root_resolved = output_root.resolve()
    if staging_resolved.parent != output_root_resolved:
        raise Stage4BuildError(f"Unsafe staging path: {staging}")
    if staging.name != f".{OUTPUT_ID}.__building__":
        raise Stage4BuildError(f"Unexpected staging directory name: {staging.name}")
    if staging.exists():
        shutil.rmtree(staging)


def write_stage4_failure_stub(output_dir: Path, reason: str) -> None:
    """Write a non-public failure marker only when no completed output exists."""
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        # Never turn a completed or otherwise pre-existing directory into a
        # failure release merely because a later invocation refused overwrite.
        return
    output.mkdir(parents=True, exist_ok=True)
    article = output / "article_note.md"
    if article.exists():
        article.unlink()
    safe = str(reason).replace("|", "／").replace("\n", " ")
    (output / "audit_v3_1.md").write_text(
        "# 2026Q1 v3.1 公開監査\n\n"
        "**STATUS: FAIL**\n\n"
        f"- BUILD_INCOMPLETE: {safe}\n",
        encoding="utf-8",
    )


def build_stage4(
    project_root: Path = PROJECT_ROOT,
    *,
    offline: bool = True,
) -> tuple[Path, str]:
    """Build the v3.1 article and tables atomically from frozen local inputs.

    Stage 4 has no fetch mode.  ``offline=False`` is rejected so that the
    public note cannot silently introduce a new data vintage.
    """
    if not offline:
        raise Stage4BuildError("Stage 4 is offline-only and does not fetch sources")

    root = Path(project_root).resolve()
    load_stage4_config(root)
    output_root = root / "outputs"
    frozen_v3 = output_root / FROZEN_INPUT_ID
    output_dir = output_root / OUTPUT_ID
    staging = output_root / f".{OUTPUT_ID}.__building__"
    if not frozen_v3.is_dir():
        raise Stage4BuildError(f"Frozen input directory is missing: {frozen_v3}")
    if output_dir.exists():
        members = list(output_dir.iterdir())
        prior_audit = output_dir / "audit_v3_1.md"
        recoverable_stub = (
            len(members) == 1
            and members[0] == prior_audit
            and "**STATUS: FAIL**" in prior_audit.read_text(encoding="utf-8")
            and "BUILD_INCOMPLETE" in prior_audit.read_text(encoding="utf-8")
        )
        if recoverable_stub:
            prior_audit.unlink()
            output_dir.rmdir()
        else:
            raise Stage4BuildError(
                f"Refusing to overwrite an existing v3.1 output: {output_dir}"
            )

    frozen_before = snapshot_sha256_tree(frozen_v3)
    _safe_clear_staging(staging, output_root)
    staging.mkdir(parents=True)
    try:
        continuing = build_continuing_sample_analysis(root)
        analysis = build_stage4_analysis(root, continuing=continuing)

        headline = _with_common_limitations(analysis.headline_2x2)
        heatmap = _with_common_limitations(analysis.mismatch_heatmap)
        rounding = _enrich_rounding_sensitivity(analysis, continuing)
        deadband = _with_common_limitations(analysis.deadband_sensitivity)

        claims = build_claims_v3_1(
            headline_2x2=headline,
            mismatch_heatmap=heatmap,
            rounding_sensitivity=rounding,
            deadband_sensitivity=deadband,
            near_zero_base_flags=analysis.near_zero_base_flags,
        )
        claims = _with_common_limitations(claims)
        claim_errors = validate_claims_v3_1(claims)
        if claim_errors:
            raise Stage4BuildError(f"claims_v3_1 failed: {claim_errors}")

        build_stage4_charts(
            headline_2x2=headline,
            mismatch_heatmap=heatmap,
            deadband_sensitivity=deadband,
            output_dir=staging / "charts",
        )
        article = render_article_note(claims_v3_1=claims)
        article_audit = validate_article_note(article, claims)
        if article_audit.status != "PASS":
            raise Stage4BuildError(
                f"publication article failed: {article_audit.failed_check_ids}"
            )

        _write_csv(headline, staging / "headline_2x2.csv")
        _write_csv(heatmap, staging / "mismatch_heatmap.csv")
        _write_csv(rounding, staging / "rounding_sensitivity.csv")
        _write_csv(deadband, staging / "deadband_sensitivity.csv")
        _write_csv(claims, staging / "claims_v3_1.csv")
        (staging / "article_note.md").write_text(article, encoding="utf-8")

        pre_audit = audit_stage4_release(
            staging,
            frozen_v3_dir=frozen_v3,
            frozen_v3_sha256=frozen_before,
            require_existing_audit=False,
        )
        if not pre_audit.passed:
            raise Stage4BuildError(
                f"pre-publication audit failed: {pre_audit.failed_check_ids}"
            )
        (staging / "audit_v3_1.md").write_text(
            render_stage4_audit(pre_audit), encoding="utf-8"
        )
        final_audit = audit_stage4_release(
            staging,
            frozen_v3_dir=frozen_v3,
            frozen_v3_sha256=frozen_before,
            require_existing_audit=True,
        )
        if not final_audit.passed:
            raise Stage4BuildError(
                f"final publication audit failed: {final_audit.failed_check_ids}"
            )
        (staging / "audit_v3_1.md").write_text(
            render_stage4_audit(final_audit), encoding="utf-8"
        )

        # Re-audit the final bytes after the self-contained audit was rewritten.
        confirmed = audit_stage4_release(
            staging,
            frozen_v3_dir=frozen_v3,
            frozen_v3_sha256=frozen_before,
            require_existing_audit=True,
        )
        if not confirmed.passed:
            raise Stage4BuildError(
                f"post-write publication audit failed: {confirmed.failed_check_ids}"
            )
        if snapshot_sha256_tree(frozen_v3) != frozen_before:
            raise Stage4BuildError("Frozen v3 bytes changed during Stage 4")
        _assert_exact_output_members(staging)
        staging.rename(output_dir)
        return output_dir, "PASS"
    except Exception:
        _safe_clear_staging(staging, output_root)
        raise
