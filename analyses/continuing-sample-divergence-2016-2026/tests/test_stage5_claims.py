from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd
import pytest

from corporate_quarterly.stage5_claims import (
    ARTICLE_TITLE_V3_1,
    ARTICLE_TITLE_V3_2,
    CANONICAL_RELATIVE_PATH,
    CANONICAL_UNIT_BY_METRIC_TYPE,
    DECISION_MARGIN_CLAIM_IDS,
    NEW_2026Q1_CLAIM_IDS,
    V3_1_CLAIMS_RELATIVE_PATH,
    build_claim_corrections_v3_2,
    build_claims_v3_2,
    build_expected_value_changes_v3_2,
    build_stage5_claim_artifacts,
    build_unit_registry,
    extract_2026q1_small_values,
    validate_claim_units,
    validate_current_quarter_reproduction,
    validate_new_claims_against_canonical,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def canonical() -> pd.DataFrame:
    return pd.read_csv(PROJECT_ROOT / CANONICAL_RELATIVE_PATH)


@pytest.fixture(scope="module")
def claims_v3_1() -> pd.DataFrame:
    return pd.read_csv(PROJECT_ROOT / V3_1_CLAIMS_RELATIVE_PATH)


@pytest.fixture(scope="module")
def artifacts():
    return build_stage5_claim_artifacts(PROJECT_ROOT)


def _canonical_target(canonical: pd.DataFrame) -> pd.DataFrame:
    return canonical.loc[
        pd.to_numeric(canonical["period_code"], errors="coerce").eq(20261)
        & canonical["breakdown"].eq("capital_size")
        & pd.to_numeric(canonical["category_code"], errors="coerce").eq(19)
        & canonical["metric_id"].isin(["sales", "operating_profit"])
    ].set_index("metric_id")


def test_six_current_quarter_claims_derive_from_canonical_internal_values(
    canonical: pd.DataFrame,
    artifacts,
) -> None:
    target = _canonical_target(canonical)
    indexed = artifacts.claims_v3_2.set_index("claim_id")
    expected = {
        NEW_2026Q1_CLAIM_IDS[0]: float(target.loc["sales", "regular_yoy_pct"]),
        NEW_2026Q1_CLAIM_IDS[1]: float(
            target.loc["operating_profit", "regular_yoy_pct"]
        ),
        NEW_2026Q1_CLAIM_IDS[2]: float(target.loc["sales", "continuing_yoy_pct"]),
        NEW_2026Q1_CLAIM_IDS[3]: float(
            target.loc["operating_profit", "continuing_yoy_pct"]
        ),
        NEW_2026Q1_CLAIM_IDS[4]: abs(
            float(target.loc["sales", "continuing_yoy_pct"])
            - float(target.loc["sales", "regular_yoy_pct"])
        ),
        NEW_2026Q1_CLAIM_IDS[5]: abs(
            float(target.loc["operating_profit", "continuing_yoy_pct"])
            - float(target.loc["operating_profit", "regular_yoy_pct"])
        ),
    }
    assert set(NEW_2026Q1_CLAIM_IDS).issubset(indexed.index)
    for claim_id, expected_value in expected.items():
        assert indexed.loc[claim_id, "numeric_value"] == pytest.approx(
            expected_value,
            abs=1e-12,
        )
        assert indexed.loc[claim_id, "internal_value"] == pytest.approx(
            expected_value,
            abs=1e-12,
        )
    assert not validate_new_claims_against_canonical(
        artifacts.claims_v3_2,
        canonical,
    )


def test_six_current_quarter_claims_have_expected_display_and_units(artifacts) -> None:
    indexed = artifacts.claims_v3_2.set_index("claim_id")
    expected = {
        NEW_2026Q1_CLAIM_IDS[0]: ("＋2.1％", "percent"),
        NEW_2026Q1_CLAIM_IDS[1]: ("－1.9％", "percent"),
        NEW_2026Q1_CLAIM_IDS[2]: ("＋2.5％", "percent"),
        NEW_2026Q1_CLAIM_IDS[3]: ("＋6.0％", "percent"),
        NEW_2026Q1_CLAIM_IDS[4]: ("0.4ポイント", "percentage_points"),
        NEW_2026Q1_CLAIM_IDS[5]: ("7.9ポイント", "percentage_points"),
    }
    for claim_id, (display, unit) in expected.items():
        assert indexed.loc[claim_id, "display_value"] == display
        assert indexed.loc[claim_id, "unit"] == unit


def test_source_mutation_cannot_be_hidden_by_display_target(
    canonical: pd.DataFrame,
    claims_v3_1: pd.DataFrame,
) -> None:
    changed = canonical.copy()
    mask = (
        pd.to_numeric(changed["period_code"], errors="coerce").eq(20261)
        & changed["breakdown"].eq("capital_size")
        & pd.to_numeric(changed["category_code"], errors="coerce").eq(19)
        & changed["metric_id"].eq("sales")
    )
    row = changed.loc[mask].iloc[0]
    changed.loc[mask, "regular_current_value_oku_yen"] = (
        float(row["regular_prior_value_oku_yen"]) * 1.031
    )
    changed.loc[mask, "regular_yoy_pct"] = 3.1
    changed.loc[mask, "yoy_difference_pp"] = 2.5 - 3.1
    values = extract_2026q1_small_values(changed)
    assert values.regular_sales_yoy == pytest.approx(3.1)
    assert values.sales_cross_series_gap == pytest.approx(0.6)
    assert validate_current_quarter_reproduction(values)
    with pytest.raises(ValueError, match="REPRODUCTION_MISMATCH"):
        build_claims_v3_2(
            claims_v3_1=claims_v3_1,
            canonical_comparison=changed,
        )


def test_cross_series_claims_ignore_no_source_component(canonical: pd.DataFrame) -> None:
    changed = canonical.copy()
    mask = (
        pd.to_numeric(changed["period_code"], errors="coerce").eq(20261)
        & changed["breakdown"].eq("capital_size")
        & pd.to_numeric(changed["category_code"], errors="coerce").eq(19)
        & changed["metric_id"].eq("operating_profit")
    )
    changed.loc[mask, "yoy_difference_pp"] = 999.0
    with pytest.raises(ValueError, match="does not reconcile"):
        extract_2026q1_small_values(changed)


def test_decision_margin_units_and_displays_are_corrected(artifacts) -> None:
    indexed = artifacts.claims_v3_2.set_index("claim_id")
    expected = {
        "V31-SMALL-DECISION-MARGIN-MEDIAN": (11.3, "11.3ポイント"),
        "V31-MIDDLE-DECISION-MARGIN-MEDIAN": (9.0, "9.0ポイント"),
        "V31-LARGE-DECISION-MARGIN-MEDIAN": (8.5, "8.5ポイント"),
    }
    for claim_id, (value, display) in expected.items():
        assert indexed.loc[claim_id, "numeric_value"] == pytest.approx(value)
        assert indexed.loc[claim_id, "unit"] == "percentage_points"
        assert indexed.loc[claim_id, "display_value"] == display


def test_all_v32_claim_units_use_canonical_registry_names(artifacts) -> None:
    claims = artifacts.claims_v3_2
    assert not validate_claim_units(claims, artifacts.unit_registry)
    assert set(claims["unit"]).issubset(
        {"percent", "percentage_points", "count", "yen", "oku_yen"}
    )
    assert set(
        claims.loc[
            claims["metric_id"].eq("deadband_margin_direction_mismatch"),
            "unit",
        ]
    ) == {"percent"}
    assert artifacts.unit_registry["canonical_unit_by_metric_type"] == {
        **CANONICAL_UNIT_BY_METRIC_TYPE
    }


def test_unit_registry_fails_percent_on_growth_rate_difference(artifacts) -> None:
    claims = artifacts.claims_v3_2.copy()
    mask = claims["claim_id"].eq("V31-SMALL-DECISION-MARGIN-MEDIAN")
    claims.loc[mask, "unit"] = "percent"
    errors = validate_claim_units(claims, artifacts.unit_registry)
    assert any(error.startswith("UNIT_MISMATCH:") for error in errors)
    assert any(
        error.startswith("GROWTH_RATE_DIFFERENCE_MUST_USE_PERCENTAGE_POINTS:")
        for error in errors
    )


def test_registry_validates_metric_and_claim_ids(artifacts) -> None:
    registry = artifacts.unit_registry
    assert set(registry["claim_id_registry"]) == set(
        artifacts.claims_v3_2["claim_id"].astype(str)
    )
    assert set(registry["metric_id_registry"]) == set(
        artifacts.claims_v3_2["metric_id"].astype(str)
    )
    altered = artifacts.claims_v3_2.iloc[[0]].copy()
    altered.loc[:, "claim_id"] = "UNREGISTERED"
    assert "UNREGISTERED_CLAIM_ID:UNREGISTERED" in validate_claim_units(
        altered,
        registry,
    )


def test_correction_ledger_has_exactly_six_traceable_rows(
    claims_v3_1: pd.DataFrame,
    artifacts,
) -> None:
    corrections = build_claim_corrections_v3_2(
        claims_v3_1,
        artifacts.claims_v3_2,
    )
    assert len(corrections) == 6
    assert set(corrections["claim_id"]) == set(DECISION_MARGIN_CLAIM_IDS)
    assert set(corrections["field"]) == {"unit", "display_value"}
    assert set(corrections["source_version"]) == {"2026Q1_v3_1"}
    assert set(corrections["target_version"]) == {"2026Q1_v3_2"}
    assert set(corrections.loc[corrections["field"].eq("unit"), "after_value"]) == {
        "percentage_points"
    }


def test_expected_title_change_is_explicitly_recorded() -> None:
    changes = build_expected_value_changes_v3_2()
    assert len(changes) == 1
    row = changes.iloc[0]
    assert row["check_id"] == "article_title_exact_and_small_capital"
    assert row["before_expected_value"] == ARTICLE_TITLE_V3_1
    assert row["after_expected_value"] == ARTICLE_TITLE_V3_2
    assert row["status"] == "EXPECTED_VALUE_UPDATED"


def test_unit_registry_is_plain_json_serialisable(artifacts) -> None:
    import json

    restored = json.loads(json.dumps(artifacts.unit_registry, ensure_ascii=False))
    assert restored == artifacts.unit_registry

