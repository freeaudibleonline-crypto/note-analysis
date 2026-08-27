from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re

import pandas as pd
import pytest

from corporate_quarterly.constants import PROJECT_ROOT
from corporate_quarterly.stage5_audit import snapshot_sha256_tree
from corporate_quarterly.stage5_charts import (
    HEATMAP_TITLE,
    validate_stage5_chart_manifest,
)
from corporate_quarterly.stage5_claims import (
    ARTICLE_TITLE_V3_2,
    DECISION_MARGIN_CLAIM_IDS,
    NEW_2026Q1_CLAIM_IDS,
    validate_claim_units,
    validate_new_claims_against_canonical,
)
from corporate_quarterly.stage5_pipeline import (
    PACKAGE_FILENAME,
    STAGE5_CHARTS,
    STAGE5_REQUIRED_OUTPUTS,
)
from corporate_quarterly.stage5_publication import (
    FIGURE_MARKERS_V3_2,
    validate_article_note_v3_2,
    validate_rendered_article_v3_2,
    visible_article_character_count,
)


ROOT = Path(PROJECT_ROOT).resolve()
FINAL_OUTPUT = ROOT / "outputs" / "2026Q1_v3_2"
V3_1_OUTPUT = ROOT / "outputs" / "2026Q1_v3_1"
CANONICAL = ROOT / "outputs" / "2026Q1_v3" / "main_vs_continuing_sample.csv"


def _release_directory() -> Path | None:
    configured = os.environ.get("CORPORATE_STAGE5_OUTPUT_DIR")
    if configured:
        candidate = Path(configured).resolve()
        allowed_names = {"2026Q1_v3_2", ".2026Q1_v3_2.__building__"}
        assert candidate.parent == ROOT / "outputs"
        assert candidate.name in allowed_names
        assert candidate.is_dir(), f"configured Stage 5 output is missing: {candidate}"
        return candidate
    if FINAL_OUTPUT.exists():
        assert FINAL_OUTPUT.is_dir()
        return FINAL_OUTPUT
    return None


@pytest.fixture(scope="module")
def release() -> Path | None:
    return _release_directory()


def _initial_absence_is_valid(release: Path | None) -> bool:
    if release is not None:
        return False
    assert "CORPORATE_STAGE5_OUTPUT_DIR" not in os.environ
    assert not FINAL_OUTPUT.exists()
    return True


def _json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_generated_00_required_release_members_and_staging_package_rule(
    release: Path | None,
) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    required = set(STAGE5_REQUIRED_OUTPUTS)
    if release.name.startswith("."):
        required.remove(PACKAGE_FILENAME)
    for relative in required:
        assert (release / relative).is_file(), relative
    for filename in STAGE5_CHARTS:
        assert (release / "charts" / filename).is_file(), filename
    if release.name == "2026Q1_v3_2":
        assert (release / PACKAGE_FILENAME).is_file()


def test_generated_01_v31_all_paths_and_sha256_are_immutable(
    release: Path | None,
) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    manifest = _json(release / "v3_1_immutability_manifest.json")
    current = snapshot_sha256_tree(V3_1_OUTPUT)
    recorded = {
        str(row["path"]): str(row["post_build_sha256"])
        for row in manifest["files"]
    }
    assert manifest["exact_path_and_sha256_match"] is True
    assert manifest["summary"] == {
        "matched": len(current),
        "missing": 0,
        "added": 0,
        "changed": 0,
    }
    assert recorded == current
    assert all(row["pre_build_sha256"] == row["post_build_sha256"] for row in manifest["files"])


def test_generated_02_six_new_claims_match_the_v3_canonical_csv(
    release: Path | None,
) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    claims = pd.read_csv(release / "claims_v3_2.csv")
    canonical = pd.read_csv(CANONICAL)
    assert set(NEW_2026Q1_CLAIM_IDS) <= set(claims["claim_id"])
    assert not validate_new_claims_against_canonical(claims, canonical)


def test_generated_03_six_new_claims_are_displayed_and_linked_in_article(
    release: Path | None,
) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    article = (release / "article_note.md").read_text(encoding="utf-8")
    claims = pd.read_csv(release / "claims_v3_2.csv").set_index("claim_id")
    for claim_id in NEW_2026Q1_CLAIM_IDS:
        assert f"<!-- claim: {claim_id} -->" in article
        assert str(claims.loc[claim_id, "display_value"]) in article


def test_generated_04_decision_margin_claim_units_are_percentage_points(
    release: Path | None,
) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    claims = pd.read_csv(release / "claims_v3_2.csv").set_index("claim_id")
    assert claims.loc[list(DECISION_MARGIN_CLAIM_IDS), "unit"].eq(
        "percentage_points"
    ).all()


def test_generated_05_decision_margin_displays_are_points(
    release: Path | None,
) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    claims = pd.read_csv(release / "claims_v3_2.csv").set_index("claim_id")
    assert claims.loc[list(DECISION_MARGIN_CLAIM_IDS), "display_value"].tolist() == [
        "11.3ポイント",
        "9.0ポイント",
        "8.5ポイント",
    ]
    article = (release / "article_note.md").read_text(encoding="utf-8")
    assert all(value in article for value in ("11.3ポイント", "9.0ポイント", "8.5ポイント"))


def test_generated_06_deadband_remains_a_relative_change_rate_in_percent(
    release: Path | None,
) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    deadband = pd.read_csv(release / "deadband_sensitivity.csv")
    assert deadband["unit"].eq("percent").all()
    assert deadband["deadband_threshold_unit"].eq("percent").all()
    assert deadband["unit_definition"].str.contains("相対変化率").all()
    assert deadband["unit_definition"].str.contains("絶対的なパーセントポイント差ではない").all()


def test_generated_07_legacy_decision_margin_pct_column_is_absent(
    release: Path | None,
) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    heat = pd.read_csv(release / "mismatch_heatmap.csv")
    assert "continuing_decision_margin_abs_gap_median_pct" not in heat.columns


def test_generated_08_corrected_decision_margin_pp_column_is_present(
    release: Path | None,
) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    heat = pd.read_csv(release / "mismatch_heatmap.csv")
    assert "continuing_decision_margin_abs_gap_median_pp" in heat.columns
    assert heat["continuing_decision_margin_abs_gap_median_unit"].eq(
        "percentage_points"
    ).all()


def test_generated_09_three_pngs_have_current_manifest_hashes_and_sources(
    release: Path | None,
) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    manifest = _json(release / "chart_manifest_v3_2.json")
    assert len(manifest["charts"]) == 3
    for entry in manifest["charts"]:
        png = release / str(entry["png_path"])
        source = release / str(entry["source_csv"])
        assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert _sha256(png) == entry["png_sha256"]
        assert _sha256(source) == entry["source_csv_sha256"]
        assert entry["numeric_source_role"] == "SOURCE_CSV_NOT_CLAIMS"


def test_generated_10_every_chart_is_marked_regenerated_in_release(
    release: Path | None,
) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    manifest = _json(release / "chart_manifest_v3_2.json")
    assert {entry["chart_id"] for entry in manifest["charts"]} == {
        "mismatch_heatmap",
        "headline_2x2",
        "deadband_sensitivity",
    }
    assert all(entry["regenerated_in_release"] is True for entry in manifest["charts"])


def test_generated_11_heatmap_uses_new_neutral_title_only(
    release: Path | None,
) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    manifest = _json(release / "chart_manifest_v3_2.json")
    heat = next(entry for entry in manifest["charts"] if entry["chart_id"] == "mismatch_heatmap")
    assert heat["title"] == HEATMAP_TITLE
    assert "2016年1～3月期以降：判定の不一致は小規模資本金層に集中" not in json.dumps(
        heat, ensure_ascii=False
    )


def test_generated_12_heatmap_metadata_has_no_percent_label_for_point_gaps(
    release: Path | None,
) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    manifest = _json(release / "chart_manifest_v3_2.json")
    heat = next(entry for entry in manifest["charts"] if entry["chart_id"] == "mismatch_heatmap")
    serialized = json.dumps(heat, ensure_ascii=False)
    assert "11.3％／9.0％／8.5％" not in serialized
    assert heat["units"]["continuing_decision_margin_abs_gap_median_pp"] == "percentage_points"
    assert heat["units"]["cross_series_growth_gap_divergence_median_pp"] == "percentage_points"
    margin = {
        row["capital_tier"]: float(row["value"])
        for row in heat["structured_metadata"]["decision_margin_medians"]
    }
    divergence = {
        row["capital_tier"]: float(row["value"])
        for row in heat["structured_metadata"]["cross_series_divergence_medians"]
    }
    assert margin == pytest.approx({"small": 11.3, "middle": 9.0, "large": 8.5})
    assert {tier: round(value, 2) for tier, value in divergence.items()} == {
        "small": 11.21,
        "middle": 4.07,
        "large": 1.05,
    }


def test_generated_13_new_title_is_exact_in_article_and_audit_expectation(
    release: Path | None,
) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    article = (release / "article_note.md").read_text(encoding="utf-8")
    title = re.search(r"^#\s+(.+?)(?:\s+<!--|$)", article, flags=re.MULTILINE)
    assert title is not None and title.group(1).strip() == ARTICLE_TITLE_V3_2
    changes = pd.read_csv(release / "expected_value_changes_v3_2.csv")
    row = changes.loc[changes["check_id"].eq("article_title_exact_and_small_capital")]
    assert len(row) == 1
    assert row.iloc[0]["after_expected_value"] == ARTICLE_TITLE_V3_2


def test_generated_14_title_expectation_change_is_explicitly_recorded(
    release: Path | None,
) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    changes = pd.read_csv(release / "expected_value_changes_v3_2.csv")
    row = changes.loc[changes["check_id"].eq("article_title_exact_and_small_capital")]
    assert len(row) == 1
    assert row.iloc[0]["status"] == "EXPECTED_VALUE_UPDATED"
    assert row.iloc[0]["before_expected_value"] != row.iloc[0]["after_expected_value"]


def test_generated_15_render_has_zero_html_comments(release: Path | None) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    rendered = (release / "article_note_render.md").read_text(encoding="utf-8")
    assert not re.search(r"<!--.*?-->", rendered, flags=re.DOTALL)


def test_generated_16_render_has_zero_relative_image_links(release: Path | None) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    rendered = (release / "article_note_render.md").read_text(encoding="utf-8")
    assert not re.search(r"!\[[^]]*\]\((?![a-z]+://)[^)]+\)", rendered)


def test_generated_17_render_has_each_figure_marker_once(release: Path | None) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    rendered = (release / "article_note_render.md").read_text(encoding="utf-8")
    assert all(rendered.count(marker) == 1 for marker in FIGURE_MARKERS_V3_2.values())


def test_generated_18_article_bans_pass_without_rejecting_negative_caveat(
    release: Path | None,
) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    article = (release / "article_note.md").read_text(encoding="utf-8")
    rendered = (release / "article_note_render.md").read_text(encoding="utf-8")
    claims = pd.read_csv(release / "claims_v3_2.csv")
    assert "どちらの系列も真実や正解とは呼ばない" in article
    audit = validate_article_note_v3_2(article, claims)
    banned = audit.checks.loc[
        audit.checks["check_id"].eq("article_no_affirmative_banned_expressions")
    ]
    assert len(banned) == 1 and banned.iloc[0]["status"] == "PASS"
    render_audit = validate_rendered_article_v3_2(rendered, article_note=article)
    render_banned = render_audit.checks.loc[
        render_audit.checks["check_id"].eq("render_no_affirmative_banned_expressions")
    ]
    assert len(render_banned) == 1 and render_banned.iloc[0]["status"] == "PASS"


def test_generated_19_article_visible_length_is_2900_to_3300_characters(
    release: Path | None,
) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    article = (release / "article_note.md").read_text(encoding="utf-8")
    assert 2900 <= visible_article_character_count(article) <= 3300


def test_generated_20_units_reconcile_across_claims_article_csv_and_chart_metadata(
    release: Path | None,
) -> None:
    if _initial_absence_is_valid(release):
        return
    assert release is not None
    claims = pd.read_csv(release / "claims_v3_2.csv")
    registry = _json(release / "unit_registry.json")
    manifest = _json(release / "chart_manifest_v3_2.json")
    article = (release / "article_note.md").read_text(encoding="utf-8")
    heat = pd.read_csv(release / "mismatch_heatmap.csv")
    deadband = pd.read_csv(release / "deadband_sensitivity.csv")
    assert not validate_claim_units(claims, registry)
    assert not validate_stage5_chart_manifest(
        manifest,
        unit_registry=registry,
        claims_lineage=claims,
        base_dir=release,
    )
    canonical_units = registry["canonical_unit_by_metric_type"]
    assert canonical_units["difference_between_growth_rates"] == "percentage_points"
    assert canonical_units["deadband_threshold"] == "percent"
    assert heat["continuing_decision_margin_abs_gap_median_unit"].eq(
        "percentage_points"
    ).all()
    assert deadband["deadband_threshold_unit"].eq("percent").all()
    assert all(token in article for token in ("11.3ポイント", "9.0ポイント", "8.5ポイント"))
    assert "利益率の相対変化率（％）" in article
