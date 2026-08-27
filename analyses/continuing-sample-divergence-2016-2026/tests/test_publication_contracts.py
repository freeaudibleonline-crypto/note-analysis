from __future__ import annotations

from pathlib import Path

import pandas as pd

from corporate_quarterly.publication_contracts import (
    CLAIM_CANDIDATE_REGISTRY_V2,
    FROZEN_V2_KNOWN_MAPPING_CORRECTIONS,
    OFFICIAL_CAPITAL_SIZE_NAMES,
    apply_claim_candidate_registry,
    audit_capital_size_names,
    audit_claim_wording,
    audit_statistical_wording,
    validate_claim_candidate_registry,
)


def test_explicit_claim_candidate_registry_covers_every_frozen_v2_claim(
    project_root: Path,
) -> None:
    claims = pd.read_csv(
        project_root / "outputs" / "2026Q1_v2" / "claims_v2.csv",
        keep_default_na=False,
    )
    assert len(CLAIM_CANDIDATE_REGISTRY_V2) == 77
    assert set(CLAIM_CANDIDATE_REGISTRY_V2) == set(claims["claim_id"])
    assert set(CLAIM_CANDIDATE_REGISTRY_V2.values()) == set("ABCDE")
    assert validate_claim_candidate_registry(claims) == []


def test_registry_correction_is_copy_only_and_makes_all_owners_explicit(
    project_root: Path,
) -> None:
    claims = pd.read_csv(
        project_root / "outputs" / "2026Q1_v2" / "claims_v2.csv",
        keep_default_na=False,
    )
    frozen = claims.copy(deep=True)
    corrected = apply_claim_candidate_registry(claims)
    assert claims.equals(frozen)
    assert corrected["candidate_id"].isin(set("ABCDE")).all()
    changed = set(
        corrected.loc[
            corrected["candidate_mapping_changed_from_frozen_v2"], "claim_id"
        ]
    )
    assert changed == set(FROZEN_V2_KNOWN_MAPPING_CORRECTIONS)
    assert corrected["frozen_v2_mutation"].eq("NONE").all()


def test_registry_rejects_unregistered_claim_id(project_root: Path) -> None:
    claims = pd.read_csv(
        project_root / "outputs" / "2026Q1_v2" / "claims_v2.csv",
        keep_default_na=False,
    )
    claims.loc[len(claims)] = claims.iloc[0]
    claims.loc[len(claims) - 1, "claim_id"] = "V-999"
    codes = {issue.code for issue in validate_claim_candidate_registry(claims)}
    assert "UNREGISTERED_CLAIM_ID" in codes


def test_exact_official_capital_size_names_are_required() -> None:
    valid = pd.DataFrame(
        [
            {"capital_size_code": code, "capital_size_name": name}
            for code, name in OFFICIAL_CAPITAL_SIZE_NAMES.items()
        ]
    )
    assert audit_capital_size_names(valid) == []

    invalid = valid.copy()
    invalid.loc[invalid["capital_size_code"].eq("19"), "capital_size_name"] = (
        "1億円未満"
    )
    issues = audit_capital_size_names(invalid)
    assert {issue.code for issue in issues} == {"NON_OFFICIAL_CAPITAL_SIZE_NAME"}


def test_text_audit_distinguishes_formal_labels_and_abbreviations() -> None:
    formal = (
        "資本金1千万円以上1億円未満層と"
        "資本金1億円以上10億円未満層を比較する。"
        "以後は1億円未満層と同層と略記する。"
    )
    assert audit_statistical_wording(formal) == []
    abbreviated = audit_statistical_wording(
        "1億円未満層と1〜10億円層を比較する。"
    )
    codes = {issue.code for issue in abbreviated}
    assert codes == {"CAPITAL_FIRST_MENTION_NOT_EXACT"}


def test_pay_bonus_wording_is_not_equated_with_personnel_expense() -> None:
    assert audit_statistical_wording(
        "従業員給与・従業員賞与合計の1人当たり概算。"
    ) == []
    ambiguous = audit_statistical_wording("従業員1人当たり給与総額の概算。")
    assert "PAY_TOTAL_OMITS_BONUS_IN_LABEL" in {
        issue.code for issue in ambiguous
    }
    conflated = audit_statistical_wording("給与・賞与を人件費として集計した。")
    assert "PAY_BONUS_EQUATED_WITH_PERSONNEL_EXPENSE" in {
        issue.code for issue in conflated
    }
    assert audit_statistical_wording("従業員給与・賞与比率は2%。") == []
    bad_ratio = audit_statistical_wording("給与・賞与合計の前年同期比は2%。")
    assert "PAY_BONUS_RATIO_LABEL_NOT_EXACT" in {
        issue.code for issue in bad_ratio
    }
    assert "PERSONNEL_EXPENSE_RATIO_REQUIRES_CODE_093" in {
        issue.code for issue in audit_statistical_wording("人件費率は5%。")
    }
    assert audit_statistical_wording(
        "人件費率は5%。", acquired_metric_codes={"093"}
    ) == []


def test_claim_wording_audit_exposes_legacy_ambiguous_pay_labels(
    project_root: Path,
) -> None:
    claims = pd.read_csv(
        project_root / "outputs" / "2026Q1" / "claims.csv",
        keep_default_na=False,
    )
    issues = audit_claim_wording(claims)
    locations = {issue.location for issue in issues}
    assert "claim_id=C-031" in locations
    assert "claim_id=C-035" in locations
    assert "claim_id=C-064" in locations

    amount_claim = pd.DataFrame(
        [
            {
                "claim_id": "SYNTHETIC-AMOUNT",
                "metric_id": "employee_total_pay_derived",
                "claim_text": "従業員給与・従業員賞与合計",
                "unit": "億円",
            }
        ]
    )
    assert audit_claim_wording(amount_claim) == []
