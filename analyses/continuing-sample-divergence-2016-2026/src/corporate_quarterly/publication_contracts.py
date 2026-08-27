"""Explicit claim ownership and Japanese statistical wording contracts.

The registry is additive: it documents corrected ownership for the frozen v2
claims without rewriting ``outputs/2026Q1_v2/claims_v2.csv``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Iterable, Mapping

import pandas as pd


VALID_CANDIDATE_IDS = frozenset("ABCDE")

# Every frozen v2 claim ID has one explicit owner.  In particular, V-005--010,
# V-023 and V-026 replace the blank heuristic mappings in the immutable file.
CLAIM_CANDIDATE_REGISTRY_V2: dict[str, str] = {
    "V-001": "D",
    "V-002": "D",
    "V-003": "D",
    "V-004": "D",
    "V-005": "A",
    "V-006": "A",
    "V-007": "A",
    "V-008": "A",
    "V-009": "A",
    "V-010": "A",
    "V-011": "A",
    "V-012": "A",
    "V-013": "A",
    "V-014": "A",
    "V-015": "A",
    "V-016": "A",
    "V-017": "E",
    "V-018": "E",
    "V-019": "E",
    "V-020": "E",
    "V-021": "E",
    "V-022": "B",
    "V-023": "B",
    "V-024": "B",
    "V-025": "B",
    "V-026": "B",
    "V-027": "B",
    "V-028": "C",
    "V-029": "C",
    "V-030": "C",
    "V-031": "C",
    "V-032": "C",
    "V-033": "A",
    "V-034": "A",
    "V-035": "A",
    "V-036": "A",
    "V-037": "A",
    "V-038": "A",
    "V-039": "B",
    "V-040": "B",
    "V-041": "B",
    "V-042": "B",
    "V-043": "B",
    "V-044": "B",
    "V-045": "C",
    "V-046": "C",
    "V-047": "C",
    "V-048": "C",
    "V-049": "C",
    "V-050": "C",
    "V-051": "C",
    "V-052": "D",
    "V-053": "D",
    "V-054": "D",
    "V-055": "D",
    "V-056": "D",
    "V-057": "D",
    "V-058": "E",
    "V-059": "E",
    "V-060": "E",
    "V-061": "E",
    "V-062": "E",
    "V-063": "E",
    "V-064": "B",
    "V-065": "B",
    "V-066": "B",
    "V-067": "B",
    "V-068": "B",
    "V-069": "B",
    "V-070": "B",
    "V-071": "B",
    "V-072": "B",
    "V-073": "A",
    "V-074": "B",
    "V-075": "C",
    "V-076": "D",
    "V-077": "E",
}

FROZEN_V2_KNOWN_MAPPING_CORRECTIONS = frozenset(
    {"V-005", "V-006", "V-007", "V-008", "V-009", "V-010", "V-023", "V-026"}
)

OFFICIAL_CAPITAL_SIZE_NAMES: dict[str, str] = {
    "19": "1千万円以上 - 1億円未満",
    "24": "1億円以上 - 10億円未満",
    "25": "10億円以上",
    "26": "全規模",
}


@dataclass(frozen=True)
class ContractIssue:
    severity: str
    code: str
    location: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def validate_claim_candidate_registry(
    claims: pd.DataFrame,
    registry: Mapping[str, str] = CLAIM_CANDIDATE_REGISTRY_V2,
) -> list[ContractIssue]:
    """Validate one complete, explicit candidate owner for every claim ID."""
    issues: list[ContractIssue] = []
    if "claim_id" not in claims.columns:
        return [
            ContractIssue("FAIL", "MISSING_CLAIM_ID_COLUMN", "claims", "claim_id is required")
        ]
    claim_ids = claims["claim_id"].astype(str)
    if claim_ids.duplicated().any():
        issues.append(
            ContractIssue(
                "FAIL",
                "DUPLICATE_CLAIM_ID",
                "claims.claim_id",
                str(sorted(claim_ids.loc[claim_ids.duplicated()].unique())),
            )
        )
    observed = set(claim_ids)
    registered = set(registry)
    if observed - registered:
        issues.append(
            ContractIssue(
                "FAIL",
                "UNREGISTERED_CLAIM_ID",
                "claims.claim_id",
                str(sorted(observed - registered)),
            )
        )
    if registered - observed:
        issues.append(
            ContractIssue(
                "FAIL",
                "REGISTERED_CLAIM_ABSENT",
                "registry",
                str(sorted(registered - observed)),
            )
        )
    invalid = {
        claim_id: candidate_id
        for claim_id, candidate_id in registry.items()
        if candidate_id not in VALID_CANDIDATE_IDS
    }
    if invalid:
        issues.append(
            ContractIssue(
                "FAIL",
                "INVALID_REGISTERED_CANDIDATE_ID",
                "registry",
                str(invalid),
            )
        )
    return issues


def apply_claim_candidate_registry(
    claims: pd.DataFrame,
    registry: Mapping[str, str] = CLAIM_CANDIDATE_REGISTRY_V2,
) -> pd.DataFrame:
    """Return a corrected copy; never mutate the frozen claims DataFrame."""
    issues = validate_claim_candidate_registry(claims, registry)
    if issues:
        raise ValueError([issue.to_dict() for issue in issues])
    corrected = claims.copy(deep=True)
    if "candidate_id" in corrected.columns:
        corrected["frozen_v2_candidate_id"] = corrected["candidate_id"].astype(str)
    else:
        corrected["frozen_v2_candidate_id"] = ""
    corrected["candidate_id"] = corrected["claim_id"].map(registry)
    corrected["candidate_mapping_registry"] = (
        "CLAIM_CANDIDATE_REGISTRY_V2_EXPLICIT"
    )
    corrected["candidate_mapping_changed_from_frozen_v2"] = (
        corrected["candidate_id"] != corrected["frozen_v2_candidate_id"]
    )
    corrected["frozen_v2_mutation"] = "NONE"
    return corrected


def audit_capital_size_names(
    frame: pd.DataFrame,
    *,
    code_column: str = "capital_size_code",
    name_column: str = "capital_size_name",
) -> list[ContractIssue]:
    """Require exact Ministry table labels for every known capital-size code."""
    issues: list[ContractIssue] = []
    missing = {code_column, name_column} - set(frame.columns)
    if missing:
        return [
            ContractIssue(
                "FAIL",
                "MISSING_CAPITAL_LABEL_COLUMNS",
                "capital_size_frame",
                str(sorted(missing)),
            )
        ]
    for index, row in frame.iterrows():
        code = str(row[code_column])
        expected = OFFICIAL_CAPITAL_SIZE_NAMES.get(code)
        if expected is None:
            issues.append(
                ContractIssue(
                    "FAIL",
                    "UNKNOWN_CAPITAL_SIZE_CODE",
                    f"row={index}",
                    code,
                )
            )
        elif str(row[name_column]) != expected:
            issues.append(
                ContractIssue(
                    "FAIL",
                    "NON_OFFICIAL_CAPITAL_SIZE_NAME",
                    f"row={index};code={code}",
                    f"expected={expected!r}; observed={row[name_column]!r}",
                )
            )
    return issues


PUBLIC_CAPITAL_FIRST_MENTIONS = {
    "small": "資本金1千万円以上1億円未満層",
    "middle": "資本金1億円以上10億円未満層",
    "large": "資本金10億円以上層",
}

PUBLIC_CAPITAL_REFERENCE_PATTERNS = {
    "small": r"(?:資本金)?(?:1千万円以上(?:\s*[-–—]〜∼?\s*)?)?1億円未満(?:層)?",
    "middle": r"(?:資本金)?(?:1億円以上(?:\s*[-–—〜∼]\s*)?|1(?:〜|∼|-))10億円(?:未満)?(?:層)?",
    "large": r"(?:資本金)?10億円以上(?:層)?",
}


def _audit_public_capital_first_mentions(
    text: str, *, location: str
) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    any_explicit = False
    for bucket in ("small", "middle", "large"):
        match = re.search(PUBLIC_CAPITAL_REFERENCE_PATTERNS[bucket], text)
        if match is None:
            continue
        any_explicit = True
        required = PUBLIC_CAPITAL_FIRST_MENTIONS[bucket]
        if match.group(0) != required:
            issues.append(
                ContractIssue(
                    "FAIL",
                    "CAPITAL_FIRST_MENTION_NOT_EXACT",
                    location,
                    f"bucket={bucket}; required first mention={required!r}; "
                    f"observed={match.group(0)!r}",
                )
            )
    if "同層" in text and not any_explicit:
        issues.append(
            ContractIssue(
                "FAIL",
                "CAPITAL_SAME_GROUP_WITHOUT_FIRST_MENTION",
                location,
                "「同層」の前に厳密な資本金区分名を一度示す。",
            )
        )
    return issues


def audit_statistical_wording(
    text: str,
    *,
    location: str = "text",
    acquired_metric_codes: Iterable[str] = (),
) -> list[ContractIssue]:
    """Audit public wording without treating pay+bonus as personnel expenses."""
    issues: list[ContractIssue] = []
    text = str(text)
    issues.extend(_audit_public_capital_first_mentions(text, location=location))
    ambiguous_pay = re.search(r"(?<!賞与)給与総額", text)
    if ambiguous_pay:
        issues.append(
            ContractIssue(
                "FAIL",
                "PAY_TOTAL_OMITS_BONUS_IN_LABEL",
                location,
                "Use 従業員給与・従業員賞与合計 when both components are used.",
            )
        )
    if re.search(
        r"(?:給与[^\n。]{0,12}賞与|賞与[^\n。]{0,12}給与)"
        r"[^\n。]{0,12}(?:=人件費|を人件費|は人件費)",
        text,
    ) or re.search(r"人件費[（(]給与・?賞与[）)]", text):
        issues.append(
            ContractIssue(
                "FAIL",
                "PAY_BONUS_EQUATED_WITH_PERSONNEL_EXPENSE",
                location,
                "従業員給与+従業員賞与は人件費全体と同一ではない。",
            )
        )
    pay_bonus_ratio = re.search(
        r"(?:従業員)?給与・(?:従業員)?賞与"
        r"[^\n。]{0,16}(?:比率|前年同期比|前年比|増加率)",
        text,
    )
    if pay_bonus_ratio and "従業員給与・賞与比率" not in text:
        issues.append(
            ContractIssue(
                "FAIL",
                "PAY_BONUS_RATIO_LABEL_NOT_EXACT",
                location,
                "比率の正式ラベルは「従業員給与・賞与比率」。",
            )
        )
    if "人件費率" in text and "093" not in {str(code) for code in acquired_metric_codes}:
        issues.append(
            ContractIssue(
                "FAIL",
                "PERSONNEL_EXPENSE_RATIO_REQUIRES_CODE_093",
                location,
                "「人件費率」は調査項目コード093を取得した場合のみ使用可。",
            )
        )
    return issues


def audit_claim_wording(claims: pd.DataFrame) -> list[ContractIssue]:
    """Require pay-and-bonus labels for the two derived employee-pay metrics."""
    issues: list[ContractIssue] = []
    required = {"claim_id", "metric_id", "claim_text"}
    missing = required - set(claims.columns)
    if missing:
        return [
            ContractIssue(
                "FAIL", "MISSING_CLAIM_WORDING_COLUMNS", "claims", str(sorted(missing))
            )
        ]
    pay_metrics = {
        "employee_total_pay_derived",
        "employee_pay_per_person_approx",
    }
    selected = claims.loc[claims["metric_id"].isin(pay_metrics)]
    for row in selected.itertuples():
        wording = str(row.claim_text)
        if "給与" not in wording or "賞与" not in wording:
            issues.append(
                ContractIssue(
                    "FAIL",
                    "PAY_BONUS_COMPONENT_LABEL_INCOMPLETE",
                    f"claim_id={row.claim_id}",
                    "Derived employee pay must explicitly say 従業員給与・従業員賞与合計.",
                )
            )
        if "人件費" in wording:
            issues.append(
                ContractIssue(
                    "FAIL",
                    "PAY_BONUS_MISLABELED_AS_PERSONNEL_EXPENSE",
                    f"claim_id={row.claim_id}",
                    "The derived metric is not total personnel expense.",
                )
            )
        ratio_context = str(getattr(row, "unit", "")) == "%" or bool(
            re.search(r"比率|前年同期比|前年比|増加率", wording)
        )
        if (
            row.metric_id == "employee_total_pay_derived"
            and ratio_context
            and "従業員給与・賞与比率" not in wording
        ):
            issues.append(
                ContractIssue(
                    "FAIL",
                    "PAY_BONUS_RATIO_LABEL_NOT_EXACT",
                    f"claim_id={row.claim_id}",
                    "従業員給与+従業員賞与の比率は「従業員給与・賞与比率」と表示する。",
                )
            )
        issues.extend(
            audit_statistical_wording(wording, location=f"claim_id={row.claim_id}")
        )
    return issues
