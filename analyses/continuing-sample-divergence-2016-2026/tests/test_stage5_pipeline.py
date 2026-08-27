from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from corporate_quarterly.constants import PROJECT_ROOT
from corporate_quarterly import stage5_pipeline
from corporate_quarterly.stage5_pipeline import (
    FROZEN_V3_1_ID,
    OUTPUT_ID,
    PROTECTED_OUTPUT_IDS,
    STAGE5_CHARTS,
    STAGE5_REQUIRED_OUTPUTS,
    Stage5BuildError,
    Stage5ImmutabilityError,
    _assert_protected_unchanged,
    _safe_clear_staging,
    _v32_deadband,
    _v32_heatmap,
    build_stage5,
    load_stage5_config,
)


ROOT = Path(PROJECT_ROOT)
V3_1 = ROOT / "outputs" / FROZEN_V3_1_ID


def test_stage5_config_is_offline_and_protects_every_prior_release() -> None:
    config = load_stage5_config(ROOT)
    assert config["offline_only"] is True
    assert config["output_id"] == OUTPUT_ID
    protected = set(config["protected_output_directories"])
    assert {f"outputs/{release_id}" for release_id in PROTECTED_OUTPUT_IDS} <= protected


def test_stage5_config_rejects_network_enabled_release(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config = json.loads(
        (ROOT / "config" / "stage5_2026Q1.json").read_text(encoding="utf-8")
    )
    config["offline_only"] = False
    (config_dir / "stage5_2026Q1.json").write_text(
        json.dumps(config, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(Stage5BuildError, match="offline-only"):
        load_stage5_config(tmp_path)


def test_heatmap_conversion_replaces_only_the_legacy_unit_column() -> None:
    before = pd.read_csv(V3_1 / "mismatch_heatmap.csv", dtype={"capital_code": str})
    after = _v32_heatmap(V3_1)
    old = "continuing_decision_margin_abs_gap_median_pct"
    new = "continuing_decision_margin_abs_gap_median_pp"
    assert old in before.columns
    assert old not in after.columns
    assert new in after.columns
    pd.testing.assert_series_equal(
        before[old], after[new], check_names=False, check_dtype=False
    )
    assert after["continuing_decision_margin_abs_gap_median_unit"].eq(
        "percentage_points"
    ).all()
    assert after["cross_series_growth_gap_divergence_median_unit"].eq(
        "percentage_points"
    ).all()


def test_heatmap_conversion_fails_closed_if_input_was_already_relabelled(
    tmp_path: Path,
) -> None:
    frame = pd.read_csv(V3_1 / "mismatch_heatmap.csv")
    frame = frame.rename(
        columns={
            "continuing_decision_margin_abs_gap_median_pct":
            "continuing_decision_margin_abs_gap_median_pp"
        }
    )
    frame.to_csv(tmp_path / "mismatch_heatmap.csv", index=False)
    with pytest.raises(Stage5BuildError, match="legacy decision-margin column"):
        _v32_heatmap(tmp_path)


def test_deadband_conversion_keeps_relative_change_thresholds_in_percent() -> None:
    before = pd.read_csv(V3_1 / "deadband_sensitivity.csv")
    after = _v32_deadband(V3_1)
    pd.testing.assert_series_equal(
        before["deadband_pct"], after["deadband_pct"], check_names=False
    )
    assert after["unit"].eq("percent").all()
    assert after["deadband_threshold_unit"].eq("percent").all()
    assert after["mismatch_rate_unit"].eq("percent").all()
    assert after["unit_definition"].str.contains("相対変化率").all()
    assert after["unit_definition"].str.contains("絶対的なパーセントポイント差ではない").all()


@pytest.mark.parametrize("drift_kind", ["missing", "added", "changed"])
def test_protected_snapshot_gate_detects_every_path_or_hash_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    drift_kind: str,
) -> None:
    output_root = tmp_path / "outputs"
    output_root.mkdir()
    expected = {
        release_id: {"kept.txt": "a" * 64} for release_id in PROTECTED_OUTPUT_IDS
    }
    observed = {release_id: dict(files) for release_id, files in expected.items()}
    target = observed[FROZEN_V3_1_ID]
    if drift_kind == "missing":
        target.pop("kept.txt")
    elif drift_kind == "added":
        target["added.txt"] = "b" * 64
    else:
        target["kept.txt"] = "c" * 64

    monkeypatch.setattr(
        stage5_pipeline,
        "_snapshot_tree",
        lambda path: observed[Path(path).name],
    )
    with pytest.raises(Stage5ImmutabilityError, match=drift_kind):
        _assert_protected_unchanged(output_root, expected)


def test_protected_snapshot_gate_accepts_exact_match(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "outputs"
    output_root.mkdir()
    expected = {
        release_id: {"kept.txt": "a" * 64} for release_id in PROTECTED_OUTPUT_IDS
    }
    monkeypatch.setattr(
        stage5_pipeline,
        "_snapshot_tree",
        lambda path: dict(expected[Path(path).name]),
    )
    _assert_protected_unchanged(output_root, expected)


def test_staging_cleanup_is_narrow_and_preserves_every_other_directory(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    staging = outputs / f".{OUTPUT_ID}.__building__"
    staging.mkdir()
    (staging / "temporary.txt").write_text("temporary", encoding="utf-8")
    protected = outputs / FROZEN_V3_1_ID
    protected.mkdir()
    marker = protected / "keep.txt"
    marker.write_text("frozen", encoding="utf-8")

    _safe_clear_staging(staging, outputs)

    assert not staging.exists()
    assert marker.read_text(encoding="utf-8") == "frozen"


@pytest.mark.parametrize(
    "relative",
    [FROZEN_V3_1_ID, OUTPUT_ID, f".{OUTPUT_ID}.__building__/nested"],
)
def test_staging_cleanup_refuses_wrong_or_nested_targets(
    tmp_path: Path,
    relative: str,
) -> None:
    outputs = tmp_path / "outputs"
    target = outputs / relative
    target.mkdir(parents=True)
    marker = target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(Stage5BuildError, match="Unsafe staging path"):
        _safe_clear_staging(target, outputs)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_required_output_contract_contains_publication_audit_and_three_charts() -> None:
    assert len(STAGE5_REQUIRED_OUTPUTS) == len(set(STAGE5_REQUIRED_OUTPUTS))
    assert len(STAGE5_CHARTS) == len(set(STAGE5_CHARTS)) == 3
    assert {
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
        "audit_v3_2.md",
        "v3_1_immutability_manifest.json",
        "corporate_quarterly_2026Q1_v3_2_clean.zip",
    } <= set(STAGE5_REQUIRED_OUTPUTS)
    assert set(STAGE5_CHARTS) == {
        "mismatch_heatmap.png",
        "headline_2x2.png",
        "deadband_sensitivity.png",
    }


def test_public_build_cannot_enable_network() -> None:
    with pytest.raises(Stage5BuildError, match="offline-only"):
        build_stage5(ROOT, offline=False, run_tests=False)

