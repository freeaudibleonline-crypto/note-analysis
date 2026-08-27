from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import pandas as pd
import pytest

from corporate_quarterly.release_integrity import verify_clean_release_zip
from corporate_quarterly.stage3_charts import STAGE3_CHART_FILENAMES
from corporate_quarterly.stage3_pipeline import STAGE3_REQUIRED_OUTPUTS
from corporate_quarterly.stage3_publication import (
    validate_claims_v3,
    validate_stage3_article,
)


def _output(project_root: Path) -> Path:
    output = project_root / "outputs" / "2026Q1_v3"
    if not output.exists():
        pytest.skip("Run `make build-v3` to execute Stage 3 artifact checks")
    return output


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_stage3_generated_release_is_complete_and_publishable(
    project_root: Path,
) -> None:
    output = _output(project_root)
    missing = [name for name in STAGE3_REQUIRED_OUTPUTS if not (output / name).is_file()]
    assert not missing
    assert (output / "article_public.md").is_file()

    audit = (output / "audit_v3.md").read_text(encoding="utf-8")
    assert "**STATUS: PASS**" in audit
    assert "| FAIL |" not in audit
    decision = (output / "decision_v3.md").read_text(encoding="utf-8")
    assert decision.startswith(
        "# 最終判定: PUBLISH_SAMPLE_CONSTRUCTION_SENSITIVITY"
    )

    charts = output / "charts"
    assert {path.name for path in charts.glob("*.png")} == set(
        STAGE3_CHART_FILENAMES
    )
    assert all((charts / name).stat().st_size > 10_000 for name in STAGE3_CHART_FILENAMES)

    limitation_columns = {
        "continuing_sample_size_limitation",
        "profit_standard_error_limitation",
    }
    for path in output.glob("*.csv"):
        assert limitation_columns <= set(pd.read_csv(path, nrows=1).columns), path.name
    for path in output.glob("*.md"):
        assert "標準誤差率" in path.read_text(encoding="utf-8"), path.name


def test_stage3_generated_claims_and_two_candidate_isolation(
    project_root: Path,
) -> None:
    output = _output(project_root)
    claims = pd.read_csv(output / "claims_v3.csv", keep_default_na=False)
    assert len(claims) == 28
    assert validate_claims_v3(claims) == []

    article = (output / "article_public.md").read_text(encoding="utf-8")
    assert validate_stage3_article(article, claims).status == "PASS"
    assert article.count("![") == 2
    assert "nonoperating_four_item_bridge" not in article
    assert "営業外損益" not in article
    assert "支払利息等" not in article
    assert "資本金1千万円以上1億円未満層" in article


def test_stage3_generated_reversal_and_nonoperating_bridge_values(
    project_root: Path,
) -> None:
    output = _output(project_root)
    comparison = pd.read_csv(output / "main_vs_continuing_sample.csv")
    small = comparison.loc[
        comparison["period_code"].astype(str).eq("20261")
        & comparison["breakdown"].eq("capital_size")
        & comparison["category_code"].astype(str).eq("19")
    ].iloc[0]
    assert small["regular_relative_margin_change_direction"] == "DOWN"
    assert small["continuing_relative_margin_change_direction"] == "UP"
    assert bool(small["relative_margin_direction_reversal"])

    bridge = pd.read_csv(output / "nonoperating_bridge.csv")
    current = bridge.loc[
        bridge["period_code"].astype(str).eq("20261")
        & bridge["industry_code"].astype(str).eq("104")
        & bridge["capital_size_code"].astype(str).eq("26")
    ].set_index("component_id")
    expected = {
        "interest_and_dividend_income": (152.04, 152.04),
        "other_non_operating_income": (15_424.31, 15_424.31),
        "interest_expense": (6_759.86, -6_759.86),
        "other_non_operating_expense": (-6_790.13, 6_790.13),
    }
    for component, (source_delta, profit_impact) in expected.items():
        assert current.loc[component, "source_yoy_delta_oku_yen"] == pytest.approx(
            source_delta, abs=0.011
        )
        assert current.loc[component, "profit_impact_yoy_oku_yen"] == pytest.approx(
            profit_impact, abs=0.011
        )
    assert current["profit_impact_yoy_oku_yen"].sum() == pytest.approx(
        15_606.62, abs=0.011
    )


def test_stage3_manifest_hashes_and_clean_package(project_root: Path) -> None:
    output = _output(project_root)
    manifest = json.loads(
        (output / "clean_archive_manifest.json").read_text(encoding="utf-8")
    )
    assert set(manifest["continuing_sample_limitations"]) == {
        "small_sample",
        "profit_standard_error",
    }
    rows = [
        row
        for release in manifest["frozen_outputs"]["releases"].values()
        for row in release["files"]
    ]
    assert len(rows) == 38
    assert all(_sha256(project_root / row["path"]) == row["sha256"] for row in rows)

    package = output / "corporate_quarterly_2026Q1_v3_clean.zip"
    assert verify_clean_release_zip(package)["status"] == "PASS"
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
    banned_parts = {"__MACOSX", "__pycache__", ".pytest_cache"}
    assert not any(banned_parts.intersection(Path(name).parts) for name in names)
    assert not any(Path(name).name == ".DS_Store" for name in names)
    assert not any(Path(name).name == "アーカイブ.zip" for name in names)
