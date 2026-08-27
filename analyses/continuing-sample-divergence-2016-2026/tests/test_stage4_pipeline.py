from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from corporate_quarterly.constants import PROJECT_ROOT
from corporate_quarterly.stage2_continuing_sample import (
    build_continuing_sample_analysis,
)
from corporate_quarterly.stage4_analysis import build_stage4_analysis
from corporate_quarterly.stage4_pipeline import (
    OUTPUT_ID,
    Stage4BuildError,
    _enrich_rounding_sensitivity,
    _safe_clear_staging,
    _with_common_limitations,
    load_stage4_config,
    write_stage4_failure_stub,
)


@pytest.fixture(scope="module")
def enriched_rounding() -> pd.DataFrame:
    root = Path(PROJECT_ROOT)
    continuing = build_continuing_sample_analysis(root)
    stage4 = build_stage4_analysis(root, continuing=continuing)
    return _enrich_rounding_sensitivity(stage4, continuing)


def test_stage4_config_freezes_v3_and_targets_v31() -> None:
    config = load_stage4_config(Path(PROJECT_ROOT))
    assert config["input_release"] == "outputs/2026Q1_v3"
    assert config["output_id"] == OUTPUT_ID
    assert "outputs/2026Q1_v3" in config["protected_output_directories"]


def test_rounding_output_contains_three_neutral_review_flags(
    enriched_rounding: pd.DataFrame,
) -> None:
    flagged = enriched_rounding.loc[enriched_rounding["extreme_yoy_rate_gt_100"]]
    assert len(enriched_rounding) == 41
    assert len(flagged) == 3
    assert flagged["mechanical_flag"].eq("NEAR_ZERO_BASE").all()
    assert not flagged["relative_margin_direction_reversal"].any()
    assert not flagged["headline_reversal"].any()
    assert flagged["sensitivity_method"].eq(
        "FIXED_41_QUARTER_EVENT_ATTRIBUTION_NOT_ROW_DELETION"
    ).all()
    assert enriched_rounding["row_deletion_denominator_if_applied"].eq(38).all()
    assert enriched_rounding[
        "margin_reversal_count_fixed_window_before"
    ].eq(16).all()
    assert enriched_rounding[
        "margin_reversal_count_fixed_window_after_attribution"
    ].eq(16).all()
    assert enriched_rounding[
        "headline_reversal_count_fixed_window_before"
    ].eq(11).all()
    assert enriched_rounding[
        "headline_reversal_count_fixed_window_after_attribution"
    ].eq(11).all()
    assert enriched_rounding["flag_interpretation_note"].str.contains(
        "does not establish"
    ).all()


def test_all_published_tables_receive_limitations() -> None:
    output = _with_common_limitations(pd.DataFrame({"value": [1]}))
    required = {
        "exploratory_backtest_status",
        "series_comparability_limitation",
        "continuing_sample_size_limitation",
        "profit_standard_error_limitation",
        "continuing_margin_interpretation",
        "sample_error_status",
    }
    assert required <= set(output)
    assert output[list(required)].notna().all().all()


def test_staging_cleanup_refuses_any_other_target(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    wrong = outputs / "2026Q1_v3"
    wrong.mkdir()
    marker = wrong / "keep.txt"
    marker.write_text("frozen", encoding="utf-8")
    with pytest.raises(Stage4BuildError, match="Unexpected staging"):
        _safe_clear_staging(wrong, outputs)
    assert marker.read_text(encoding="utf-8") == "frozen"


def test_failure_stub_never_mutates_completed_output(tmp_path: Path) -> None:
    output = tmp_path / OUTPUT_ID
    output.mkdir()
    article = output / "article_note.md"
    article.write_text("published", encoding="utf-8")
    write_stage4_failure_stub(output, "later invocation failed")
    assert article.read_text(encoding="utf-8") == "published"
    assert not (output / "audit_v3_1.md").exists()
