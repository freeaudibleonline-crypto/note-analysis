from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from corporate_quarterly.constants import REQUIRED_OUTPUTS


def _output_dir(project_root: Path) -> Path:
    return project_root / "outputs" / "2026Q1"


def test_generated_release_passes_publication_gate(project_root) -> None:
    output = _output_dir(project_root)
    if not output.exists():
        pytest.skip("Run `make build` to execute the generated-artifact integration checks")

    missing = [name for name in REQUIRED_OUTPUTS if not (output / name).is_file()]
    assert not missing
    assert (output / "charts").is_dir()
    assert list((output / "charts").glob("*.png"))

    audit_text = (output / "audit_report.md").read_text(encoding="utf-8")
    article_text = (output / "article.md").read_text(encoding="utf-8")
    assert "**STATUS: PASS**" in audit_text
    assert "**STATUS: PASS**" in article_text


def test_generated_claims_and_processed_schema_contract(project_root) -> None:
    output = _output_dir(project_root)
    claims_path = output / "claims.csv"
    processed_path = output / "processed_quarterly.parquet"
    if not claims_path.exists() or not processed_path.exists():
        pytest.skip("Run `make build` to execute the generated-artifact integration checks")

    claims = pd.read_csv(claims_path)
    numeric = claims[claims["claim_type"].isin(["FACT", "CALC"])]
    assert not numeric.empty
    assert numeric["verification_status"].eq("PASS").all()
    assert numeric["value"].notna().all()
    assert numeric["display_value"].astype(str).str.len().gt(0).all()
    chart_claims = claims[claims["claim_usage"].eq("CHART_INPUT")]
    assert len(chart_claims) == 29
    assert set(chart_claims["chart_id"]) == {
        "operating_profit_industry_contribution",
        "operating_profit_capital_contribution",
        "profit_margin_and_gap",
        "capex_software_bridge",
        "allocation_growth",
    }

    processed = pd.read_parquet(processed_path)
    required_columns = {
        "source_value",
        "raw_lag4_value",
        "raw_yoy_delta",
        "raw_yoy_pct",
        "raw_lag1_value",
        "raw_qoq_pct",
        "sa_value_oku_yen",
        "sa_lag1_value_oku_yen",
        "sa_qoq_pct",
        "official_sa_qoq_pct",
        "coverage_scope",
        "missing_status",
    }
    assert required_columns <= set(processed.columns)
    assert {
        "EXCL_FINANCE_INSURANCE",
        "INCL_FINANCE_INSURANCE",
        "FINANCE_INSURANCE_ONLY",
    } <= set(processed["coverage_scope"])
    per_person = processed.loc[
        processed["metric_id"].eq("employee_pay_per_person_approx"), "stock_flow"
    ]
    assert set(per_person) == {"FLOW_PER_PERIOD_END_PERSON"}


def test_output_manifest_is_a_complete_provenance_copy(project_root) -> None:
    manifest_path = _output_dir(project_root) / "data_manifest.json"
    if not manifest_path.exists():
        pytest.skip("Run `make build` to execute the generated-artifact integration checks")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["release_id"] == "2026Q1"
    assert manifest["manifest_version"] == 2
    assert len(manifest["sources"]) == 14
    assert all(source.get("retrieved_at") for source in manifest["sources"])
    assert all(source.get("url") for source in manifest["sources"])
    assert not any(Path(source["raw_path"]).is_absolute() for source in manifest["sources"])
    query_sources = [
        source for source in manifest["sources"] if source["role"] == "request_metadata"
    ]
    assert len(query_sources) == 4
    assert all(source["source_method"] == "ESTAT_DB_VIEW_PUBLIC_UI" for source in query_sources)
