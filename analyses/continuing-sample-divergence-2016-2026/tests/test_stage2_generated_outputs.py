from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from corporate_quarterly.stage2_charts import STAGE2_CHART_FILENAMES
from corporate_quarterly.stage2_claims import validate_claims_v2
from corporate_quarterly.stage2_pipeline import STAGE2_REQUIRED_OUTPUTS


EXPECTED_DECISIONS = {
    "A": "UNSTABLE_OR_NO_PATTERN",
    "B": "RECENT_BUT_NOT_ESTABLISHED",
    "C": "ONE_QUARTER_OUTLIER",
    "D": "RECENT_BUT_NOT_ESTABLISHED",
    "E": "UNSTABLE_OR_NO_PATTERN",
}


def _output(project_root: Path) -> Path:
    output = project_root / "outputs" / "2026Q1_v2"
    if not output.exists():
        pytest.skip("Run `make build-v2` to execute Stage 2 artifact checks")
    return output


def test_stage2_generated_release_is_complete_and_fail_closed(
    project_root: Path,
) -> None:
    output = _output(project_root)
    missing = [name for name in STAGE2_REQUIRED_OUTPUTS if not (output / name).is_file()]
    assert not missing
    assert not (output / "PHASE0_FAIL.md").exists()
    assert not (output / "article_public.md").exists()

    audit = (output / "audit_v2.md").read_text(encoding="utf-8")
    assert "**STATUS: PASS**" in audit
    assert "| FAIL |" not in audit
    phase0 = (output / "phase0_reproduction.md").read_text(encoding="utf-8")
    assert "**STATUS: PASS**" in phase0
    assert phase0.count("| PASS |") == 32

    charts = output / "charts"
    assert {path.name for path in charts.glob("*.png")} == set(
        STAGE2_CHART_FILENAMES
    )
    assert all((charts / name).stat().st_size > 10_000 for name in STAGE2_CHART_FILENAMES)


def test_stage2_generated_decisions_and_external_nonactivation(
    project_root: Path,
) -> None:
    output = _output(project_root)
    patterns = pd.read_csv(output / "pattern_decisions.csv")
    assert patterns.set_index("candidate_id")["pattern_decision"].to_dict() == (
        EXPECTED_DECISIONS
    )
    assert not patterns["pattern_decision"].eq("PERSISTENT_PATTERN").any()
    assert patterns["criteria_frozen_before_analysis"].eq(True).all()  # noqa: E712
    assert patterns["vintage_status"].eq(
        "CURRENT_VINTAGE_HISTORICAL_SERIES"
    ).all()
    assert patterns["revision_robustness_status"].eq(
        "NOT_TESTED_NO_PRIOR_PUBLICATION_VINTAGES"
    ).all()

    ledger = pd.read_csv(output / "external_evidence_ledger.csv", keep_default_na=False)
    assert ledger["phase3_eligible"].eq(False).all()  # noqa: E712
    assert ledger["evidence_use_status"].eq(
        "NOT_ACTIVATED_NON_PERSISTENT"
    ).all()
    assert ledger["source_retrieval_status"].eq(
        "NOT_REQUESTED_PHASE3_INELIGIBLE"
    ).all()
    assert ledger["assessment"].eq("NOT_APPLICABLE").all()
    assert ledger["raw_path"].eq("").all()
    assert ledger["sha256"].eq("").all()
    assert not (project_root / "data" / "raw" / "external_2026Q1").exists()

    decision = (output / "decision.md").read_text(encoding="utf-8")
    assert decision.startswith(
        "| 候補 | Phase 0 | 現四半期の強さ | 長期安定性 | 外部証拠 | 公開判定 |"
    )
    assert "PUBLISH_LONGITUDINAL_ARTICLE" not in decision
    assert decision.count("PUBLISH_CURRENT_QUARTER_SNAPSHOT_ONLY") == 2


def test_stage2_generated_manifest_claims_and_taxonomy_contracts(
    project_root: Path,
) -> None:
    output = _output(project_root)
    manifest = json.loads((output / "data_manifest_v2.json").read_text(encoding="utf-8"))
    assert manifest["canonical_configuration"]["path"] == (
        "config/release_2026Q1.json"
    )
    assert manifest["canonical_configuration"]["CONFIG_KIND"] == (
        "EXECUTABLE_RELEASE_CONFIGURATION"
    )
    assert manifest["vintage_policy"]["historical"] == (
        "CURRENT_VINTAGE_HISTORICAL_SERIES"
    )
    assert manifest["vintage_policy"]["prior_publication_vintages"] == (
        "NOT_AVAILABLE_NOT_TESTED"
    )
    assert manifest["external_manifest"]["status"] == (
        "NOT_ACTIVATED_NO_PERSISTENT_PATTERN"
    )
    assert manifest["external_manifest"]["source_count"] == 0

    claims = pd.read_csv(output / "claims_v2.csv")
    assert len(claims) == 77
    assert claims["claim_id"].is_unique
    assert claims["verification_status"].eq("PASS").all()
    assert claims["publication_status"].eq("INTERNAL").all()
    claim_units = claims.set_index("metric_id")["unit"]
    assert claim_units.loc["capital_19_sales_yoy_pct"] == "%"
    assert claim_units.loc["software_capital_19_contribution_pct"] == "%"
    assert claim_units.loc["capital_19_operating_margin_delta_pp"] == "ポイント"
    assert validate_claims_v2(claims) == []

    wrong_unit = claims.copy()
    wrong_unit.loc[
        wrong_unit["metric_id"].eq("capital_19_sales_yoy_pct"), "unit"
    ] = "ポイント"
    assert "percent_metric_unit_mismatch" in validate_claims_v2(wrong_unit)

    cross = pd.read_csv(output / "industry_x_capital_contributions.csv")
    assert len(cross.loc[cross["taxonomy"].eq("major")]) == 33
    assert len(cross.loc[cross["taxonomy"].eq("leaf")]) == 135
    major = set(cross.loc[cross["taxonomy"].eq("major"), "industry_code"])
    leaf = set(cross.loc[cross["taxonomy"].eq("leaf"), "industry_code"])
    assert "108" in {str(value) for value in major}
    assert "108" not in {str(value) for value in leaf}

    historical = pd.read_parquet(output / "historical_quarterly.parquet")
    assert historical.shape == (17_550, 52)
    assert historical["vintage_status"].eq(
        "CURRENT_VINTAGE_HISTORICAL_SERIES"
    ).all()
    software_before_definition = historical.loc[
        historical["metric_id"].eq("software_capex_derived")
        & historical["period_code"].astype(str).lt("20013")
    ]
    assert software_before_definition["value"].isna().all()
    assert software_before_definition["missing_status"].eq(
        "PRE_DEFINITION_NOT_COMPARABLE"
    ).all()
