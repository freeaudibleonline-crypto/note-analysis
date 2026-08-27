from __future__ import annotations

import copy
import json
from pathlib import Path

import pandas as pd

from corporate_quarterly.stage5_audit import (
    ARTICLE_TRIGGER_HEADING,
    EXPECTED_HEATMAP_TITLE,
    build_v3_1_immutability_manifest,
    audit_stage5_article,
    audit_stage5_chart_manifest,
    audit_stage5_claims,
    audit_stage5_dataframes,
    audit_stage5_release,
    audit_v3_1_immutability,
    render_stage5_audit,
    snapshot_sha256_tree,
)
from corporate_quarterly.stage5_charts import (
    build_stage5_charts,
    chart_manifest_payload,
)
from corporate_quarterly.stage5_claims import (
    CANONICAL_RELATIVE_PATH,
    build_stage5_claim_artifacts,
)
from corporate_quarterly.stage5_publication import (
    render_article_note_public_v3_2,
    render_article_note_v3_2,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _claim_artifacts():
    return build_stage5_claim_artifacts(PROJECT_ROOT)


def _frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    source = PROJECT_ROOT / "outputs" / "2026Q1_v3_1"
    heat = pd.read_csv(source / "mismatch_heatmap.csv").rename(
        columns={
            "continuing_decision_margin_abs_gap_median_pct":
                "continuing_decision_margin_abs_gap_median_pp"
        }
    )
    headline = pd.read_csv(source / "headline_2x2.csv")
    deadband = pd.read_csv(source / "deadband_sensitivity.csv")
    deadband["unit"] = "percent"
    return heat, headline, deadband


def _articles():
    artifacts = _claim_artifacts()
    article = render_article_note_v3_2(claims_v3_2=artifacts.claims_v3_2)
    rendered = render_article_note_public_v3_2(article)
    return artifacts, article, rendered


def test_v31_immutability_manifest_requires_exact_path_and_sha(tmp_path: Path) -> None:
    frozen = tmp_path / "outputs" / "2026Q1_v3_1"
    frozen.mkdir(parents=True)
    (frozen / "a.txt").write_text("alpha\n", encoding="utf-8")
    (frozen / "nested").mkdir()
    (frozen / "nested" / "b.bin").write_bytes(b"beta")
    before = snapshot_sha256_tree(frozen)
    manifest = build_v3_1_immutability_manifest(frozen, before)
    audit = audit_v3_1_immutability(frozen, before, manifest)
    assert audit.status == "PASS"
    assert manifest["exact_path_and_sha256_match"] is True
    assert all(row["status"] == "MATCH" for row in manifest["files"])

    (frozen / "a.txt").write_text("changed\n", encoding="utf-8")
    changed_manifest = build_v3_1_immutability_manifest(frozen, before)
    changed = audit_v3_1_immutability(frozen, before, changed_manifest)
    assert changed.status == "FAIL"
    assert "immutability_v3_1_path_and_sha256_exact" in changed.failed_check_ids
    assert changed_manifest["summary"]["changed"] == 1


def test_stage5_claim_unit_and_correction_contracts() -> None:
    artifacts = _claim_artifacts()
    canonical = pd.read_csv(PROJECT_ROOT / CANONICAL_RELATIVE_PATH)
    audit = audit_stage5_claims(
        claims=artifacts.claims_v3_2,
        canonical_comparison=canonical,
        unit_registry=artifacts.unit_registry,
        corrections=artifacts.claim_corrections_v3_2,
        expected_value_changes=artifacts.expected_value_changes_v3_2,
    )
    assert audit.status == "PASS", audit.checks.loc[
        audit.checks["status"].eq("FAIL")
    ].to_dict("records")

    wrong = artifacts.claims_v3_2.copy()
    wrong.loc[
        wrong["claim_id"].eq("V31-SMALL-DECISION-MARGIN-MEDIAN"), "unit"
    ] = "percent"
    failed = audit_stage5_claims(
        claims=wrong,
        canonical_comparison=canonical,
        unit_registry=artifacts.unit_registry,
        corrections=artifacts.claim_corrections_v3_2,
        expected_value_changes=artifacts.expected_value_changes_v3_2,
    )
    assert failed.status == "FAIL"
    assert "unit_registry_claim_and_metric_validation" in failed.failed_check_ids


def test_stage5_dataframes_correct_column_and_units_fail_closed() -> None:
    heat, headline, deadband = _frames()
    audit = audit_stage5_dataframes(
        mismatch_heatmap=heat,
        headline_2x2=headline,
        deadband_sensitivity=deadband,
    )
    assert audit.status == "PASS", audit.checks.loc[
        audit.checks["status"].eq("FAIL")
    ].to_dict("records")

    old_column = heat.rename(
        columns={
            "continuing_decision_margin_abs_gap_median_pp":
                "continuing_decision_margin_abs_gap_median_pct"
        }
    )
    failed = audit_stage5_dataframes(
        mismatch_heatmap=old_column,
        headline_2x2=headline,
        deadband_sensitivity=deadband,
    )
    assert "data_heatmap_old_pct_column_absent_new_pp_present" in failed.failed_check_ids

    wrong_deadband = deadband.copy()
    wrong_deadband["unit"] = "percentage_points"
    failed = audit_stage5_dataframes(
        mismatch_heatmap=heat,
        headline_2x2=headline,
        deadband_sensitivity=wrong_deadband,
    )
    assert "data_deadband_canonical_and_percent_not_points" in failed.failed_check_ids


def test_stage5_article_and_render_positive_contract() -> None:
    artifacts, article, rendered = _articles()
    audit = audit_stage5_article(article, rendered, artifacts.claims_v3_2)
    assert audit.status == "PASS", audit.checks.loc[
        audit.checks["status"].eq("FAIL")
    ].to_dict("records")
    assert ARTICLE_TRIGGER_HEADING in article


def test_stage5_article_six_claim_title_length_and_render_guards() -> None:
    artifacts, article, rendered = _articles()
    missing_claim = article.replace(
        "<!-- claim: V32-2026Q1-SMALL-SALES-CROSS-SERIES-GAP -->", ""
    )
    assert (
        "article_trigger_section_position_length_and_content"
        in audit_stage5_article(
            missing_claim, rendered, artifacts.claims_v3_2
        ).failed_check_ids
    )

    bad_render = rendered + "\n<!-- claim: V32-BAD -->\n![relative](charts/x.png)"
    failed = audit_stage5_article(article, bad_render, artifacts.claims_v3_2)
    assert "render_no_comments_relative_images_or_claim_ids" in failed.failed_check_ids
    assert "render_preserves_article_text_and_order" in failed.failed_check_ids

    short = article.split("## 何を比べたのか", 1)[0]
    failed = audit_stage5_article(
        short, rendered, artifacts.claims_v3_2
    )
    assert "article_visible_character_count_2900_3300" in failed.failed_check_ids


def _build_chart_fixture(release: Path):
    artifacts = _claim_artifacts()
    heat, headline, deadband = _frames()
    release.mkdir(parents=True, exist_ok=True)
    for name, frame in (
        ("mismatch_heatmap.csv", heat),
        ("headline_2x2.csv", headline),
        ("deadband_sensitivity.csv", deadband),
    ):
        frame.to_csv(release / name, index=False)
    result = build_stage5_charts(
        mismatch_heatmap=release / "mismatch_heatmap.csv",
        headline_2x2=release / "headline_2x2.csv",
        deadband_sensitivity=release / "deadband_sensitivity.csv",
        unit_registry=artifacts.unit_registry,
        claims_lineage=artifacts.claims_v3_2,
        output_dir=release / "charts",
    )
    return artifacts, chart_manifest_payload(result)


def test_stage5_chart_manifest_hashes_metadata_and_regeneration(tmp_path: Path) -> None:
    release = tmp_path / "outputs" / "2026Q1_v3_2"
    artifacts, manifest = _build_chart_fixture(release)
    audit = audit_stage5_chart_manifest(
        manifest, output_dir=release, claims=artifacts.claims_v3_2
    )
    assert audit.status == "PASS", audit.checks.loc[
        audit.checks["status"].eq("FAIL")
    ].to_dict("records")
    heat = next(row for row in manifest["charts"] if row["chart_id"] == "mismatch_heatmap")
    assert heat["title"] == EXPECTED_HEATMAP_TITLE
    assert heat["structured_metadata"]["decision_margin_medians"][0]["unit"] == "percentage_points"

    altered = copy.deepcopy(manifest)
    altered["charts"][0]["regenerated_in_release"] = False
    altered["charts"][0]["structured_metadata"]["decision_margin_medians"][0]["unit"] = "percent"
    failed = audit_stage5_chart_manifest(
        altered, output_dir=release, claims=artifacts.claims_v3_2
    )
    assert "charts_three_regenerated_source_hashed_pngs" in failed.failed_check_ids
    assert "charts_heatmap_neutral_title_pp_metadata" in failed.failed_check_ids

    (release / "charts" / "headline_2x2.png").write_bytes(b"not a png")
    failed = audit_stage5_chart_manifest(
        manifest, output_dir=release, claims=artifacts.claims_v3_2
    )
    assert "charts_three_regenerated_source_hashed_pngs" in failed.failed_check_ids


def _minimal_pre_audit_release(tmp_path: Path):
    root = tmp_path
    output = root / "outputs" / "2026Q1_v3_2"
    artifacts, manifest = _build_chart_fixture(output)
    canonical = root / CANONICAL_RELATIVE_PATH
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_bytes((PROJECT_ROOT / CANONICAL_RELATIVE_PATH).read_bytes())

    artifacts.claims_v3_2.to_csv(output / "claims_v3_2.csv", index=False)
    artifacts.claim_corrections_v3_2.to_csv(
        output / "claim_corrections_v3_2.csv", index=False
    )
    artifacts.expected_value_changes_v3_2.to_csv(
        output / "expected_value_changes_v3_2.csv", index=False
    )
    (output / "unit_registry.json").write_text(
        json.dumps(artifacts.unit_registry, ensure_ascii=False), encoding="utf-8"
    )
    (output / "chart_manifest_v3_2.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    article = render_article_note_v3_2(claims_v3_2=artifacts.claims_v3_2)
    (output / "article_note.md").write_text(article, encoding="utf-8")
    (output / "article_note_render.md").write_text(
        render_article_note_public_v3_2(article), encoding="utf-8"
    )

    frozen = root / "outputs" / "2026Q1_v3_1"
    frozen.mkdir(parents=True)
    (frozen / "audit_v3_1.md").write_text(
        "**STATUS: PASS**\n", encoding="utf-8"
    )
    (frozen / "evidence.txt").write_text("frozen\n", encoding="utf-8")
    before = snapshot_sha256_tree(frozen)
    immutability = build_v3_1_immutability_manifest(frozen, before)
    (output / "v3_1_immutability_manifest.json").write_text(
        json.dumps(immutability, ensure_ascii=False), encoding="utf-8"
    )
    return root, output, frozen, before


def test_stage5_release_pre_audit_passes_and_final_requires_audit_and_zip(
    tmp_path: Path,
) -> None:
    root, output, frozen, before = _minimal_pre_audit_release(tmp_path)
    pre = audit_stage5_release(
        output,
        frozen_v3_1_dir=frozen,
        frozen_v3_1_sha256=before,
        project_root=root,
        phase="pre_audit",
    )
    assert pre.status == "PASS", pre.checks.loc[
        pre.checks["status"].eq("FAIL")
    ].to_dict("records")

    final = audit_stage5_release(
        output,
        frozen_v3_1_dir=frozen,
        frozen_v3_1_sha256=before,
        project_root=root,
        phase="final",
    )
    assert final.status == "FAIL"
    assert "release_required_files_present_for_phase" in final.failed_check_ids
    assert "release_existing_audit_pass_and_title_change_documented" in final.failed_check_ids
    assert "release_clean_package_verified" in final.failed_check_ids

    (output / "IMMUTABILITY_FAIL.md").write_text("FAIL\n", encoding="utf-8")
    failed = audit_stage5_release(
        output,
        frozen_v3_1_dir=frozen,
        frozen_v3_1_sha256=before,
        project_root=root,
        phase="pre_audit",
    )
    assert "release_failure_markers_absent" in failed.failed_check_ids


def test_stage5_audit_render_exposes_expected_title_change() -> None:
    artifacts, article, rendered = _articles()
    audit = audit_stage5_article(article, rendered, artifacts.claims_v3_2)
    report = render_stage5_audit(audit)
    assert "**STATUS: PASS**" in report
    assert "変更前タイトル" in report
    assert "変更後タイトル" in report
    assert "変更理由" in report
    assert "EXPECTED_VALUE_UPDATED" in report
