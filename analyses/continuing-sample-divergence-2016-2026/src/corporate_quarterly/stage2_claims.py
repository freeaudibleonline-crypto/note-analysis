"""Auditable claims table for Stage 2 decisions and potential publication."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


def _display(value: float, unit: str) -> str:
    if unit == "億円":
        return f"{value:,.2f}億円"
    if unit in {"percentage_point", "%", "ポイント"}:
        return f"{value:.3f}%" if unit == "%" else f"{value:.3f}ポイント"
    if unit == "quarters":
        return f"{int(round(value))}四半期"
    if unit == "percentile":
        return f"{value:.1f}パーセンタイル"
    if unit == "robust_z":
        return f"{value:.3f}"
    return f"{value:.6f}"


def build_claims_v2(
    *,
    phase0_checks: pd.DataFrame,
    robustness: pd.DataFrame,
    publication_decisions: pd.DataFrame,
    capital_margin_bridge: pd.DataFrame,
) -> pd.DataFrame:
    """Build claims directly from audited tables; no expected target becomes an article fact."""
    rows: list[dict[str, Any]] = []
    serial = 1

    def add(
        *,
        candidate_id: str,
        claim_usage: str,
        metric_id: str,
        value: float,
        unit: str,
        formula: str,
        source_row_key: str,
        claim_type: str = "CALC",
    ) -> None:
        nonlocal serial
        finite = value is not None and math.isfinite(float(value))
        rows.append(
            {
                "claim_id": f"V-{serial:03d}",
                "candidate_id": candidate_id,
                "claim_type": claim_type,
                "claim_usage": claim_usage,
                "metric_id": metric_id,
                "value": float(value) if finite else None,
                "unit": unit,
                "display_value": _display(float(value), unit) if finite else "",
                "formula": formula,
                "source_row_key": source_row_key,
                "source_authority": "e-Stat structured table 1 / audited Stage 2 calculation",
                "verification_status": "PASS" if finite else "FAIL",
            }
        )
        serial += 1

    # These claims use recalculated actuals.  The frozen expected values remain
    # visible only in phase0_reproduction.md as audit targets.
    for row in phase0_checks.itertuples():
        if pd.isna(row.actual):
            continue
        candidate_id = ""
        name = str(row.check_id)
        if "manufacturing" in name and "ict" not in name:
            candidate_id = "A"
        elif "capital_25_sales" in name or "capital_19_sales" in name or "margin" in name:
            candidate_id = "B"
        elif "software" in name or "capex_" in name:
            candidate_id = "C"
        elif name.startswith("all_") and ("gap" in name or "ordinary" in name or "operating" in name):
            candidate_id = "D"
        elif "ict_machinery" in name:
            candidate_id = "E"
        add(
            candidate_id=candidate_id,
            claim_usage="PHASE0_REPRODUCTION_ACTUAL",
            metric_id=name,
            value=float(row.actual),
            unit=str(row.unit),
            formula=str(row.locator),
            source_row_key=name,
        )

    for row in robustness.sort_values("candidate_id").itertuples():
        cid = str(row.candidate_id)
        measures = (
            (
                "current_indicator_value",
                row.current_indicator_value,
                "%" if str(row.indicator_unit) == "%" else str(row.indicator_unit),
            ),
            ("historical_percentile", row.historical_percentile, "percentile"),
            ("mad_robust_z", row.mad_robust_z, "robust_z"),
            ("same_direction_last4", row.same_direction_last4, "quarters"),
            ("same_direction_last8", row.same_direction_last8, "quarters"),
            ("same_direction_run_length", row.same_direction_run_length, "quarters"),
        )
        for metric_id, value, unit in measures:
            if pd.isna(value):
                continue
            add(
                candidate_id=cid,
                claim_usage="HISTORICAL_ROBUSTNESS",
                metric_id=metric_id,
                value=float(value),
                unit=unit,
                formula=f"pre-registered candidate {cid} historical calculation",
                source_row_key=f"candidate={cid};metric={metric_id};period=20261",
            )
        if cid == "C" and pd.notna(row.small_capital_software_contribution_pct):
            add(
                candidate_id="C",
                claim_usage="HISTORICAL_ROBUSTNESS",
                metric_id="small_capital_software_contribution_pct",
                value=float(row.small_capital_software_contribution_pct),
                unit="%",
                formula="small-capital software yoy delta / all-capital software yoy delta",
                source_row_key="candidate=C;period=20261",
            )

    for row in capital_margin_bridge.sort_values("capital_size_code").itertuples():
        for metric_id in (
            "aggregate_sales_scale_effect_oku_yen",
            "industry_composition_effect_oku_yen",
            "within_industry_margin_effect_oku_yen",
        ):
            value = getattr(row, metric_id)
            if pd.isna(value):
                continue
            add(
                candidate_id="B",
                claim_usage="MARGIN_BRIDGE",
                metric_id=metric_id,
                value=float(value),
                unit="億円",
                formula="three-factor Shapley average over all six factor orders",
                source_row_key=f"capital={row.capital_size_code};metric={metric_id}",
            )

    decision_map = publication_decisions.set_index("candidate_id")
    for cid in sorted(decision_map.index):
        rows.append(
            {
                "claim_id": f"V-{serial:03d}",
                "candidate_id": cid,
                "claim_type": "CALC",
                "claim_usage": "PUBLICATION_DECISION",
                "metric_id": "pattern_decision",
                "value": None,
                "unit": "status_code",
                "display_value": str(decision_map.loc[cid, "pattern_status"]),
                "formula": "frozen Phase 2 pattern rule",
                "source_row_key": f"candidate={cid}",
                "source_authority": "current-vintage historical series",
                "verification_status": "PASS",
            }
        )
        serial += 1

    claims = pd.DataFrame(rows)
    if claims["claim_id"].duplicated().any():
        raise ValueError("claims_v2 contains duplicate claim IDs")
    return claims


def validate_claims_v2(claims: pd.DataFrame) -> list[str]:
    problems: list[str] = []
    required = {
        "claim_id",
        "candidate_id",
        "claim_type",
        "claim_usage",
        "metric_id",
        "value",
        "unit",
        "display_value",
        "formula",
        "source_row_key",
        "source_authority",
        "verification_status",
    }
    missing = required - set(claims.columns)
    if missing:
        problems.append(f"missing_columns={sorted(missing)}")
        return problems
    if claims["claim_id"].duplicated().any():
        problems.append("duplicate_claim_ids")
    if not claims["verification_status"].eq("PASS").all():
        problems.append("non_pass_claim")
    numeric = claims["unit"].ne("status_code")
    values = pd.to_numeric(claims.loc[numeric, "value"], errors="coerce")
    if values.isna().any() or not np_isfinite(values):
        problems.append("non_finite_numeric_claim")
    if claims["display_value"].astype(str).str.len().eq(0).any():
        problems.append("empty_display_value")
    metric_ids = claims["metric_id"].astype(str)
    percent_metrics = metric_ids.str.endswith("_pct")
    if not claims.loc[percent_metrics, "unit"].eq("%").all():
        problems.append("percent_metric_unit_mismatch")
    point_metrics = metric_ids.str.endswith("_delta_pp")
    if not claims.loc[point_metrics, "unit"].eq("ポイント").all():
        problems.append("percentage_point_metric_unit_mismatch")
    return problems


def np_isfinite(values: pd.Series) -> bool:
    """Small local helper avoids adding an implicit zero-fill during validation."""
    return all(math.isfinite(float(value)) for value in values)
