from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
import pytest

from corporate_quarterly.stage5_charts import (
    HEATMAP_TITLE,
    STAGE5_CHART_FILENAMES,
    assert_valid_stage5_chart_manifest,
    build_stage5_charts,
    chart_manifest_payload,
    validate_stage5_chart_manifest,
    validate_stage5_unit_registry,
)
from corporate_quarterly.stage5_claims import build_stage5_claim_artifacts


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def unit_registry() -> dict[str, dict[str, str]]:
    return {
        "metric_types": {
            "yoy_growth_rate": {"unit": "percent"},
            "difference_between_growth_rates": {
                "unit": "percentage_points"
            },
            "direction_mismatch_rate": {"unit": "percent"},
            "implied_relative_margin_change": {"unit": "percent"},
            "deadband_threshold": {"unit": "percent"},
            "count": {"unit": "count"},
            "currency": {"unit": "oku_yen"},
        }
    }


@pytest.fixture
def mismatch_heatmap() -> pd.DataFrame:
    counts = {
        ("19", "relative_margin_direction"): (16, 41),
        ("19", "operating_profit"): (13, 41),
        ("19", "sales"): (6, 40),
        ("24", "relative_margin_direction"): (6, 41),
        ("24", "operating_profit"): (4, 41),
        ("24", "sales"): (7, 41),
        ("25", "relative_margin_direction"): (0, 41),
        ("25", "operating_profit"): (0, 41),
        ("25", "sales"): (1, 41),
    }
    medians = {
        "19": (11.3, 11.208695),
        "24": (9.0, 4.070024),
        "25": (8.5, 1.050023),
    }
    rows = []
    for (capital_code, metric_id), (numerator, denominator) in counts.items():
        margin, divergence = medians[capital_code]
        rows.append(
            {
                "capital_code": capital_code,
                "metric_id": metric_id,
                "mismatch_count": numerator,
                "comparable_quarters": denominator,
                "mismatch_rate_pct": 100 * numerator / denominator,
                "continuing_decision_margin_abs_gap_median_pp": margin,
                "cross_series_growth_gap_divergence_median_pp": divergence,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture
def headline_2x2() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cell_id": "REGULAR_ONLY",
                "regular_headline_supported": True,
                "continuing_headline_supported": False,
                "quarter_count": 9,
            },
            {
                "cell_id": "CONTINUING_ONLY",
                "regular_headline_supported": False,
                "continuing_headline_supported": True,
                "quarter_count": 2,
            },
            {
                "cell_id": "BOTH",
                "regular_headline_supported": True,
                "continuing_headline_supported": True,
                "quarter_count": 1,
            },
            {
                "cell_id": "NEITHER",
                "regular_headline_supported": False,
                "continuing_headline_supported": False,
                "quarter_count": 29,
            },
        ]
    )


@pytest.fixture
def deadband_sensitivity() -> pd.DataFrame:
    counts = {
        "19": [(0.5, 15, 39), (1.0, 14, 37), (2.0, 10, 33), (3.0, 8, 29)],
        "24": [(0.5, 3, 38), (1.0, 2, 36), (2.0, 1, 32), (3.0, 0, 29)],
        "25": [(0.5, 0, 41), (1.0, 0, 41), (2.0, 0, 36), (3.0, 0, 33)],
    }
    return pd.DataFrame(
        [
            {
                "capital_code": capital_code,
                "deadband_pct": deadband,
                "mismatch_count": numerator,
                "retained_quarters": denominator,
                "mismatch_rate_pct": 100 * numerator / denominator,
            }
            for capital_code, tier_rows in counts.items()
            for deadband, numerator, denominator in tier_rows
        ]
    )


@pytest.fixture
def claims_lineage() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "claim_id": "V31-SMALL-DECISION-MARGIN-MEDIAN",
                "numeric_value": 11.3,
                "unit": "percentage_points",
                "display_value": "11.3ポイント",
                "chart_ids": "mismatch_heatmap.png",
            },
            {
                "claim_id": "V31-MIDDLE-DECISION-MARGIN-MEDIAN",
                "numeric_value": 9.0,
                "unit": "percentage_points",
                "display_value": "9.0ポイント",
                "chart_ids": "mismatch_heatmap.png",
            },
            {
                "claim_id": "V31-LARGE-DECISION-MARGIN-MEDIAN",
                "numeric_value": 8.5,
                "unit": "percentage_points",
                "display_value": "8.5ポイント",
                "chart_ids": "mismatch_heatmap.png",
            },
            {
                "claim_id": "V31-SMALL-SERIES-DIVERGENCE-MEDIAN",
                "numeric_value": 11.208695,
                "unit": "percentage_points",
                "display_value": "11.21pt",
                "chart_ids": "mismatch_heatmap.png",
            },
            {
                "claim_id": "V31-MIDDLE-SERIES-DIVERGENCE-MEDIAN",
                "numeric_value": 4.070024,
                "unit": "percentage_points",
                "display_value": "4.07pt",
                "chart_ids": "mismatch_heatmap.png",
            },
            {
                "claim_id": "V31-LARGE-SERIES-DIVERGENCE-MEDIAN",
                "numeric_value": 1.050023,
                "unit": "percentage_points",
                "display_value": "1.05pt",
                "chart_ids": "mismatch_heatmap.png",
            },
            {
                "claim_id": "V31-SMALL-MARGIN-DIRECTION-MISMATCH",
                "numeric_value": 100 * 16 / 41,
                "unit": "percent",
                "display_value": "16/41（39.0％）",
                "chart_ids": "mismatch_heatmap.png",
            },
            {
                "claim_id": "V31-COMPOSITE-HEADLINE-MISMATCH",
                "numeric_value": 100 * 11 / 41,
                "unit": "percent",
                "display_value": "11/41",
                "chart_ids": "headline_2x2.png",
            },
            {
                "claim_id": "V31-DEADBAND-SMALL-D030",
                "numeric_value": 100 * 8 / 29,
                "unit": "percent",
                "display_value": "±3%: 8/29（27.6％）",
                "chart_ids": "deadband_sensitivity.png",
            },
        ]
    )


def _build(
    tmp_path: Path,
    *,
    mismatch_heatmap: pd.DataFrame,
    headline_2x2: pd.DataFrame,
    deadband_sensitivity: pd.DataFrame,
    unit_registry,
    claims_lineage,
):
    return build_stage5_charts(
        mismatch_heatmap=mismatch_heatmap,
        headline_2x2=headline_2x2,
        deadband_sensitivity=deadband_sensitivity,
        unit_registry=unit_registry,
        claims_lineage=claims_lineage,
        output_dir=tmp_path / "charts",
    )


def test_build_regenerates_exact_three_pngs_and_complete_manifest(
    tmp_path,
    mismatch_heatmap,
    headline_2x2,
    deadband_sensitivity,
    unit_registry,
    claims_lineage,
) -> None:
    result = _build(
        tmp_path,
        mismatch_heatmap=mismatch_heatmap,
        headline_2x2=headline_2x2,
        deadband_sensitivity=deadband_sensitivity,
        unit_registry=unit_registry,
        claims_lineage=claims_lineage,
    )
    assert tuple(result.png_paths) == STAGE5_CHART_FILENAMES
    assert len(result.manifest_entries) == 3
    for filename, path in result.png_paths.items():
        assert path.name == filename
        assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert path.stat().st_size > 20_000
    required = {
        "chart_id",
        "source_csv",
        "source_csv_sha256",
        "referenced_claim_ids",
        "title",
        "axis_labels",
        "legend_labels",
        "footnote_text",
        "units",
        "png_path",
        "png_sha256",
        "regenerated_in_release",
    }
    assert all(required <= set(entry) for entry in result.manifest_entries)
    assert all(entry["regenerated_in_release"] is True for entry in result.manifest_entries)
    assert all(entry["numeric_source_role"] == "SOURCE_CSV_NOT_CLAIMS" for entry in result.manifest_entries)


def test_manifest_reproduces_heatmap_units_values_and_neutral_title(
    tmp_path,
    mismatch_heatmap,
    headline_2x2,
    deadband_sensitivity,
    unit_registry,
    claims_lineage,
) -> None:
    result = _build(
        tmp_path,
        mismatch_heatmap=mismatch_heatmap,
        headline_2x2=headline_2x2,
        deadband_sensitivity=deadband_sensitivity,
        unit_registry=unit_registry,
        claims_lineage=claims_lineage,
    )
    heat = result.manifest_entries[0]
    assert heat["title"] == HEATMAP_TITLE
    assert "小規模資本金層に集中" not in heat["title"]
    assert heat["units"]["continuing_decision_margin_abs_gap_median_pp"] == "percentage_points"
    assert heat["units"]["cross_series_growth_gap_divergence_median_pp"] == "percentage_points"
    assert "11.3pt／9.0pt／8.5pt" in heat["footnote_text"]
    assert "11.21pt／4.07pt／1.05pt" in heat["footnote_text"]
    assert "11.3％／9.0％／8.5％" not in json.dumps(heat, ensure_ascii=False)


def test_manifest_reproduces_2x2_and_deadband_baseline_from_sources(
    tmp_path,
    mismatch_heatmap,
    headline_2x2,
    deadband_sensitivity,
    unit_registry,
    claims_lineage,
) -> None:
    result = _build(
        tmp_path,
        mismatch_heatmap=mismatch_heatmap,
        headline_2x2=headline_2x2,
        deadband_sensitivity=deadband_sensitivity,
        unit_registry=unit_registry,
        claims_lineage=claims_lineage,
    )
    headline = result.manifest_entries[1]["structured_metadata"]
    assert {row["cell_id"]: row["quarter_count"] for row in headline["cells"]} == {
        "REGULAR_ONLY": 9,
        "CONTINUING_ONLY": 2,
        "BOTH": 1,
        "NEITHER": 29,
    }
    dead = result.manifest_entries[2]
    small = dead["structured_metadata"]["small_capital_series"]
    assert [
        (row["deadband_percent"], row["numerator"], row["denominator"])
        for row in small
    ] == [
        (0.0, 16, 41),
        (0.5, 15, 39),
        (1.0, 14, 37),
        (2.0, 10, 33),
        (3.0, 8, 29),
    ]
    assert small[0]["row_origin"] == "DERIVED_FROM_MISMATCH_HEATMAP_SOURCE"
    assert dead["units"]["deadband_pct"] == "percent"
    assert "絶対的なパーセントポイント差ではない" in dead["footnote_text"]


def test_csv_inputs_are_hashed_as_numeric_sources(
    tmp_path,
    mismatch_heatmap,
    headline_2x2,
    deadband_sensitivity,
    unit_registry,
    claims_lineage,
) -> None:
    paths = {}
    for name, frame in {
        "mismatch_heatmap": mismatch_heatmap,
        "headline_2x2": headline_2x2,
        "deadband_sensitivity": deadband_sensitivity,
    }.items():
        path = tmp_path / f"{name}.csv"
        frame.to_csv(path, index=False)
        paths[name] = path
    result = build_stage5_charts(
        mismatch_heatmap=paths["mismatch_heatmap"],
        headline_2x2=paths["headline_2x2"],
        deadband_sensitivity=paths["deadband_sensitivity"],
        unit_registry=unit_registry,
        claims_lineage=claims_lineage,
        output_dir=tmp_path / "charts",
    )
    for entry in result.manifest_entries:
        path = Path(entry["source_csv"])
        assert entry["source_csv_sha256"] == sha256(path.read_bytes()).hexdigest()


def test_manifest_validator_passes_and_detects_png_tampering(
    tmp_path,
    mismatch_heatmap,
    headline_2x2,
    deadband_sensitivity,
    unit_registry,
    claims_lineage,
) -> None:
    result = _build(
        tmp_path,
        mismatch_heatmap=mismatch_heatmap,
        headline_2x2=headline_2x2,
        deadband_sensitivity=deadband_sensitivity,
        unit_registry=unit_registry,
        claims_lineage=claims_lineage,
    )
    payload = chart_manifest_payload(result)
    assert not validate_stage5_chart_manifest(
        payload, unit_registry=unit_registry, claims_lineage=claims_lineage
    )
    assert_valid_stage5_chart_manifest(
        payload, unit_registry=unit_registry, claims_lineage=claims_lineage
    )
    result.png_paths["headline_2x2.png"].write_bytes(b"not a png")
    errors = validate_stage5_chart_manifest(
        payload, unit_registry=unit_registry, claims_lineage=claims_lineage
    )
    assert "headline_2x2:png_signature" in errors
    assert "headline_2x2:png_sha256_mismatch" in errors


def test_legacy_decision_margin_pct_column_is_rejected(
    tmp_path,
    mismatch_heatmap,
    headline_2x2,
    deadband_sensitivity,
    unit_registry,
    claims_lineage,
) -> None:
    legacy = mismatch_heatmap.rename(
        columns={
            "continuing_decision_margin_abs_gap_median_pp":
                "continuing_decision_margin_abs_gap_median_pct"
        }
    )
    with pytest.raises(ValueError, match="legacy decision-margin column"):
        _build(
            tmp_path,
            mismatch_heatmap=legacy,
            headline_2x2=headline_2x2,
            deadband_sensitivity=deadband_sensitivity,
            unit_registry=unit_registry,
            claims_lineage=claims_lineage,
        )


def test_decision_margin_claim_unit_and_display_are_fail_closed(
    tmp_path,
    mismatch_heatmap,
    headline_2x2,
    deadband_sensitivity,
    unit_registry,
    claims_lineage,
) -> None:
    bad = claims_lineage.copy()
    selected = bad["claim_id"].eq("V31-SMALL-DECISION-MARGIN-MEDIAN")
    bad.loc[selected, "unit"] = "percent"
    bad.loc[selected, "display_value"] = "11.3%"
    with pytest.raises(ValueError, match="must use percentage_points"):
        _build(
            tmp_path,
            mismatch_heatmap=mismatch_heatmap,
            headline_2x2=headline_2x2,
            deadband_sensitivity=deadband_sensitivity,
            unit_registry=unit_registry,
            claims_lineage=bad,
        )
    assert not (tmp_path / "charts").exists()


def test_unit_registry_rejects_percent_for_growth_rate_difference(unit_registry) -> None:
    bad = json.loads(json.dumps(unit_registry))
    bad["metric_types"]["difference_between_growth_rates"]["unit"] = "percent"
    errors = validate_stage5_unit_registry(bad)
    assert "unit_registry:difference_between_growth_rates:expected_percentage_points" in errors
    assert "unit_registry:difference_between_growth_rates:percent_is_forbidden" in errors


def test_accepts_actual_stage5_claim_artifact_registry() -> None:
    artifacts = build_stage5_claim_artifacts(PROJECT_ROOT)
    assert not validate_stage5_unit_registry(artifacts.unit_registry)
