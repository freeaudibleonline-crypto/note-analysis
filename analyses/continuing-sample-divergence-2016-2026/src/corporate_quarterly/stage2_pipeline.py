"""Fail-closed orchestration for the additive second-stage analysis."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .constants import PROJECT_ROOT, load_release
from .estat import sha256_file
from .processing import build_processed
from .stage2_charts import STAGE2_CHART_FILENAMES, build_stage2_charts
from .stage2_claims import build_claims_v2, validate_claims_v2
from .stage2_historical import (
    build_candidate_series,
    build_historical_quarterly,
    build_historical_robustness,
    build_pattern_decisions,
    fetch_historical_snapshot,
    load_stage2_config,
    verify_historical_manifest,
)
from .stage2_phase1 import (
    Phase0ReproductionError,
    build_phase1_analysis,
    render_phase0_failure,
    render_phase0_reproduction,
    reproduce_phase0,
)
from .stage2_publication import (
    PublicationAudit,
    build_external_evidence_ledger,
    build_publication_decisions,
    fetch_external_sources,
    load_external_evidence_config,
    prepare_claims_v2,
    publication_article_required,
    render_candidate_headlines,
    render_decision_markdown,
    render_publication_audit,
    validate_external_evidence_config,
    validate_public_article,
    verify_external_manifest,
)


STAGE2_REQUIRED_OUTPUTS = (
    "phase0_reproduction.md",
    "industry_leaf_contributions.csv",
    "industry_x_capital_contributions.csv",
    "capital_margin_bridge.csv",
    "ordinary_operating_gap.csv",
    "software_capex_decomposition.csv",
    "historical_quarterly.parquet",
    "historical_robustness.csv",
    "pattern_decisions.csv",
    "external_evidence_ledger.csv",
    "claims_v2.csv",
    "audit_v2.md",
    "decision.md",
    "candidate_headlines.md",
)

STAGE2_EXTRA_OUTPUTS = (
    "industry_major_contributions.csv",
    "cell_margin_bridge.csv",
    "phase1_additivity_checks.csv",
    "historical_candidate_series.parquet",
    "data_manifest_v2.json",
)


def _json_write(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _v1_hashes(project_root: Path) -> dict[str, str]:
    output = project_root / "outputs" / "2026Q1"
    return {
        path.relative_to(project_root).as_posix(): sha256_file(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }


def _invalidate_stage2_outputs(output_dir: Path) -> None:
    """Remove only known generated v2 artifacts so a stale PASS cannot survive."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        *STAGE2_REQUIRED_OUTPUTS,
        *STAGE2_EXTRA_OUTPUTS,
        "article_public.md",
        "PHASE0_FAIL.md",
    ):
        path = output_dir / name
        if path.is_file():
            path.unlink()
    charts_dir = output_dir / "charts"
    for name in STAGE2_CHART_FILENAMES:
        path = charts_dir / name
        if path.is_file():
            path.unlink()


def write_stage2_failure_stubs(
    output_dir: Path, *, reason: str, keep_phase0_failure: bool = True
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe = reason.replace("|", "／")
    (output_dir / "audit_v2.md").write_text(
        "\n".join(
            [
                "# 第2段階公開監査",
                "",
                "**STATUS: FAIL**",
                "",
                f"- BUILD_INCOMPLETE: {safe}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (output_dir / "decision.md").write_text(
        "\n".join(
            [
                "| 候補 | Phase 0 | 現四半期の強さ | 長期安定性 | 外部証拠 | 公開判定 |",
                "|---|---|---:|---|---|---|",
                "| A–E | FAIL | — | NOT_EVALUATED | NOT_EVALUATED | ARCHIVE_NO_STABLE_HEADLINE |",
                "",
                f"BUILD_INCOMPLETE: {safe}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    article = output_dir / "article_public.md"
    if article.exists():
        article.unlink()
    if not keep_phase0_failure:
        failure = output_dir / "PHASE0_FAIL.md"
        if failure.exists():
            failure.unlink()


def _combined_manifest(
    *,
    project_root: Path,
    stage2_config: dict[str, Any],
    historical_manifest: dict[str, Any],
    external_manifest: dict[str, Any] | None,
    patterns: pd.DataFrame,
) -> dict[str, Any]:
    canonical = project_root / "config" / "release_2026Q1.json"
    stage2_path = project_root / "config" / "stage2_2026Q1.json"
    historical_path = (
        project_root
        / "data"
        / "raw"
        / stage2_config["historical_vintage_id"]
        / "data_manifest.json"
    )
    external_path = project_root / "data" / "raw" / "external_2026Q1" / "data_manifest.json"
    return {
        "manifest_version": 2,
        "dataset": "corporate_quarterly_stage2",
        "release_id": "2026Q1",
        "output_id": stage2_config["output_id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "canonical_configuration": {
            "path": canonical.relative_to(project_root).as_posix(),
            "CONFIG_KIND": "EXECUTABLE_RELEASE_CONFIGURATION",
            "sha256": sha256_file(canonical),
            "stage2_path": stage2_path.relative_to(project_root).as_posix(),
            "stage2_CONFIG_KIND": stage2_config["CONFIG_KIND"],
            "stage2_sha256": sha256_file(stage2_path),
            "input_stub": "../corporate_quarterly/config/release_input_minimal.json",
        },
        "vintage_policy": {
            "historical": "CURRENT_VINTAGE_HISTORICAL_SERIES",
            "prior_publication_vintages": "NOT_AVAILABLE_NOT_TESTED",
            "raw_mutation": "FORBIDDEN",
        },
        "historical_manifest": {
            "path": historical_path.relative_to(project_root).as_posix(),
            "sha256": sha256_file(historical_path),
            "source_count": len(historical_manifest.get("sources", [])),
            "model_period_count": historical_manifest["selection"]["model_period_count"],
            "software_comparable_start_period_code": historical_manifest[
                "software_capex_comparable_start_period_code"
            ],
        },
        "external_manifest": (
            {
                "activation": "PERSISTENT_PATTERN_ONLY",
                "status": "FROZEN",
                "path": external_path.relative_to(project_root).as_posix(),
                "sha256": sha256_file(external_path),
                "source_count": len(external_manifest.get("sources", [])),
            }
            if external_manifest is not None
            else {
                "activation": "PERSISTENT_PATTERN_ONLY",
                "status": "NOT_ACTIVATED_NO_PERSISTENT_PATTERN",
                "path": None,
                "sha256": None,
                "source_count": 0,
            }
        ),
        "pattern_decisions": patterns[
            ["candidate_id", "pattern_decision"]
        ].to_dict("records"),
    }


def _add_core_audit_checks(
    *,
    audit: PublicationAudit,
    project_root: Path,
    output_dir: Path,
    phase1: Any,
    historical: pd.DataFrame,
    historical_manifest: dict[str, Any],
    robustness: pd.DataFrame,
    patterns: pd.DataFrame,
    ledger: pd.DataFrame,
    claims: pd.DataFrame,
    charts: list[Path],
    v1_before: dict[str, str],
) -> None:
    canonical = project_root / "config" / "release_2026Q1.json"
    canonical_json = json.loads(canonical.read_text(encoding="utf-8"))
    sibling = project_root.parent / "corporate_quarterly" / "config"
    old_stub = sibling / "release_2026Q1.json"
    renamed_stub = sibling / "release_input_minimal.json"
    stub_ok = not old_stub.exists()
    stub_detail = "legacy simplified executable-name config is absent"
    if sibling.exists():
        stub_ok = stub_ok and renamed_stub.is_file()
        if renamed_stub.is_file():
            stub = json.loads(renamed_stub.read_text(encoding="utf-8"))
            stub_ok = stub_ok and stub.get("CONFIG_KIND") == "INPUT_STUB_NOT_EXECUTABLE"
        stub_detail += f"; renamed_stub_exists={renamed_stub.is_file()}"
    audit.add(
        "canonical_configuration_resolved",
        canonical_json.get("CONFIG_KIND") == "EXECUTABLE_RELEASE_CONFIGURATION"
        and stub_ok,
        f"canonical={canonical.relative_to(project_root)}; {stub_detail}",
    )
    audit.add(
        "phase0_all_targets_reproduced",
        len(phase1.phase0_checks) == 32
        and phase1.phase0_checks["status"].eq("PASS").all(),
        f"pass={int(phase1.phase0_checks['status'].eq('PASS').sum())}/32",
    )
    audit.add(
        "major_leaf_taxonomies_separate",
        len(phase1.major_taxonomy_contributions["industry_code"].unique()) == 11
        and len(phase1.leaf_taxonomy_contributions["industry_code"].unique()) == 45
        and set(phase1.major_taxonomy_contributions["taxonomy"]) == {"major"}
        and set(phase1.leaf_taxonomy_contributions["taxonomy"]) == {"leaf"},
        "major=11 mutually exclusive categories; leaf=45 mutually exclusive categories",
    )
    audit.add(
        "industry_x_capital_cell_contract",
        len(phase1.major_industry_x_capital) == 33
        and len(phase1.leaf_industry_x_capital) == 135,
        f"major={len(phase1.major_industry_x_capital)}, leaf={len(phase1.leaf_industry_x_capital)}",
    )
    additivity = phase1.additivity_checks
    audit.add(
        "all_parent_child_cross_additivity",
        len(additivity) > 0 and additivity["status"].eq("PASS").all(),
        f"pass={int(additivity['status'].eq('PASS').sum())}/{len(additivity)}",
    )
    cell_residual = pd.to_numeric(
        phase1.cell_margin_bridge["bridge_residual_oku_yen"], errors="coerce"
    ).abs()
    capital_residual = pd.to_numeric(
        phase1.capital_margin_bridge["bridge_residual_oku_yen"], errors="coerce"
    ).abs()
    bridge_ok = (
        phase1.cell_margin_bridge["bridge_status"].eq("CALCULABLE").all()
        and phase1.capital_margin_bridge["bridge_status"].eq("CALCULABLE").all()
        and cell_residual.max() <= 0.01
        and capital_residual.max() <= 0.01
    )
    audit.add(
        "shapley_bridge_identities",
        bool(bridge_ok),
        f"cell max residual={cell_residual.max():.12g}億円; capital max residual={capital_residual.max():.12g}億円",
    )
    gap = phase1.ordinary_operating_gap
    gap_identity = (
        pd.to_numeric(gap["ordinary_profit_yoy_delta_oku_yen"], errors="coerce")
        - pd.to_numeric(gap["operating_profit_yoy_delta_oku_yen"], errors="coerce")
        - pd.to_numeric(gap["net_non_operating_gap_yoy_delta_oku_yen"], errors="coerce")
    ).abs()
    audit.add(
        "net_non_operating_gap_identity_and_naming",
        gap_identity.max() <= 0.01
        and gap["interpretation_note"].str.contains("ordinary_profit minus operating_profit").all(),
        f"rows={len(gap)}; max residual={gap_identity.max():.12g}億円",
    )
    software = phase1.software_capex_decomposition
    software_identity = (
        pd.to_numeric(software["capex_including_yoy_delta_oku_yen"], errors="coerce")
        - pd.to_numeric(software["capex_excluding_yoy_delta_oku_yen"], errors="coerce")
        - pd.to_numeric(software["software_capex_yoy_delta_oku_yen"], errors="coerce")
    ).abs()
    audit.add(
        "software_capex_derived_not_direct",
        software_identity.max() <= 0.01
        and software["is_direct_published_series"].eq(False).all(),  # noqa: E712
        f"rows={len(software)}; max residual={software_identity.max():.12g}億円",
    )
    try:
        verify_historical_manifest(historical_manifest, project_root)
        historical_hash_ok = True
        historical_hash_detail = "model/query/values SHA-256 verified"
    except Exception as exc:  # pragma: no cover - corruption path
        historical_hash_ok = False
        historical_hash_detail = str(exc)
    audit.add("historical_raw_manifest_hashes", historical_hash_ok, historical_hash_detail)
    period_count = historical["period_code"].nunique()
    historical_contract = (
        period_count == 288
        and historical["period_code"].astype(str).max() == "20261"
        and historical["vintage_status"].eq("CURRENT_VINTAGE_HISTORICAL_SERIES").all()
        and historical["revision_robustness_status"]
        .eq("NOT_TESTED_NO_PRIOR_PUBLICATION_VINTAGES")
        .all()
    )
    audit.add(
        "historical_current_vintage_contract",
        historical_contract,
        f"rows={len(historical)}, periods={period_count}, 1954Q2-2026Q1; prior publication vintages unavailable",
    )
    audit.add(
        "historical_structure_and_software_start",
        historical_manifest.get("software_capex_comparable_start_period_code")
        == "20013"
        and bool(historical_manifest.get("classification_policy")),
        "software comparison starts 2001Q3; legacy H20 categories are not spliced",
    )
    audit.add(
        "pre_registered_pattern_decisions_complete",
        len(patterns) == 5
        and set(patterns["candidate_id"]) == set("ABCDE")
        and patterns["criteria_frozen_before_analysis"].eq(True).all(),  # noqa: E712
        ", ".join(
            f"{row.candidate_id}={row.pattern_decision}"
            for row in patterns.sort_values("candidate_id").itertuples()
        ),
    )
    persistent = set(
        patterns.loc[
            patterns["pattern_decision"].eq("PERSISTENT_PATTERN"), "candidate_id"
        ]
    )
    activated = set(ledger.loc[ledger["phase3_eligible"].eq(True), "candidate_id"])  # noqa: E712
    audit.add(
        "external_phase3_persistent_only",
        persistent == activated,
        f"persistent={sorted(persistent)}, activated={sorted(activated)}",
    )
    if persistent:
        nonactivation_ok = True
        nonactivation_detail = "not applicable; persistent candidates activate Phase 3"
    else:
        external_raw = project_root / "data" / "raw" / "external_2026Q1"
        nonactivation_ok = (
            not external_raw.exists()
            and ledger["phase3_eligible"].eq(False).all()  # noqa: E712
            and ledger["source_frozen"].eq(False).all()  # noqa: E712
            and ledger["source_retrieval_status"]
            .eq("NOT_REQUESTED_PHASE3_INELIGIBLE")
            .all()
            and ledger["evidence_use_status"]
            .eq("NOT_ACTIVATED_NON_PERSISTENT")
            .all()
            and ledger["assessment"].eq("NOT_APPLICABLE").all()
            and ledger["raw_path"].fillna("").eq("").all()
            and ledger["sha256"].fillna("").eq("").all()
            and ledger["retrieved_at"].fillna("").eq("").all()
        )
        nonactivation_detail = (
            f"external_raw_exists={external_raw.exists()}; "
            f"ledger_rows={len(ledger)}; observations/raw/hash not activated"
        )
    audit.add(
        "external_phase3_nonactivation_is_clean",
        bool(nonactivation_ok),
        nonactivation_detail,
    )
    claim_problems = validate_claims_v2(claims)
    audit.add(
        "claims_v2_verified",
        not claim_problems,
        f"claims={len(claims)}; problems={claim_problems}",
    )
    chart_ok = (
        {path.name for path in charts} == set(STAGE2_CHART_FILENAMES)
        and all(path.is_file() and path.stat().st_size > 10_000 for path in charts)
    )
    audit.add(
        "required_stage2_charts",
        chart_ok,
        f"charts={sorted(path.name for path in charts)}",
    )
    v1_after = _v1_hashes(project_root)
    audit.add(
        "stage1_outputs_untouched",
        v1_before == v1_after,
        f"before_files={len(v1_before)}, after_files={len(v1_after)}, hashes_equal={v1_before == v1_after}",
    )
    decision_first = (output_dir / "decision.md").read_text(encoding="utf-8").splitlines()[0]
    audit.add(
        "decision_table_is_first_content",
        decision_first.startswith("| 候補 | Phase 0 |"),
        f"first_line={decision_first}",
    )


def fetch_stage2_sources(
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    """Freeze historical raw and activate external downloads only if persistent."""
    project_root = Path(project_root)
    release = load_release("2026Q1")
    processed, _parse_issues = build_processed(project_root, release)
    phase0 = reproduce_phase0(processed)
    phase0_passed = bool(phase0["status"].eq("PASS").all())
    historical_manifest = fetch_historical_snapshot(project_root)
    historical = build_historical_quarterly(project_root)
    candidates = build_candidate_series(historical)
    patterns = build_pattern_decisions(candidates)
    external_acquisition = fetch_external_sources(
        phase0_passed=phase0_passed,
        pattern_decisions=patterns,
        project_root=project_root,
    )
    external_manifest = (
        external_acquisition
        if external_acquisition.get("acquisition_status")
        == "ACQUIRED_PERSISTENT_PATTERN_ONLY"
        else None
    )
    return {
        "historical_manifest": historical_manifest,
        "external_manifest": external_manifest,
        "external_acquisition": external_acquisition,
        "phase0_passed": phase0_passed,
        "patterns": patterns.to_dict("records"),
    }


def build_stage2(
    *,
    project_root: Path = PROJECT_ROOT,
    offline: bool = True,
) -> tuple[Path, str]:
    project_root = Path(project_root)
    stage2_config = load_stage2_config(project_root)
    output_dir = project_root / "outputs" / stage2_config["output_id"]
    _invalidate_stage2_outputs(output_dir)
    write_stage2_failure_stubs(
        output_dir, reason="build started; Stage 2 publication gate is incomplete"
    )
    v1_before = _v1_hashes(project_root)

    release = load_release("2026Q1")
    if release.CONFIG_KIND != "EXECUTABLE_RELEASE_CONFIGURATION":
        raise ValueError("config/release_2026Q1.json is not the executable canonical config")
    processed, _parse_issues = build_processed(project_root, release)
    phase0 = reproduce_phase0(processed)
    (output_dir / "phase0_reproduction.md").write_text(
        render_phase0_reproduction(phase0), encoding="utf-8"
    )
    if not phase0["status"].eq("PASS").all():
        (output_dir / "PHASE0_FAIL.md").write_text(
            render_phase0_failure(phase0), encoding="utf-8"
        )
        raise Phase0ReproductionError(phase0)
    phase1 = build_phase1_analysis(processed)

    if not offline:
        fetch_historical_snapshot(project_root)
    historical = build_historical_quarterly(project_root)
    historical_manifest_path = (
        project_root
        / "data"
        / "raw"
        / stage2_config["historical_vintage_id"]
        / "data_manifest.json"
    )
    historical_manifest = json.loads(
        historical_manifest_path.read_text(encoding="utf-8")
    )
    candidate_series = build_candidate_series(historical, stage2_config)
    robustness = build_historical_robustness(candidate_series, stage2_config)
    patterns = build_pattern_decisions(candidate_series, stage2_config)

    persistent_exists = patterns["pattern_decision"].eq("PERSISTENT_PATTERN").any()
    external_config = load_external_evidence_config(
        project_root / "config" / "external_evidence_2026Q1.json"
    )
    validate_external_evidence_config(external_config, stage2_config=stage2_config)
    external_manifest: dict[str, Any] | None = None
    if not offline:
        external_acquisition = fetch_external_sources(
            phase0_passed=True,
            pattern_decisions=patterns,
            project_root=project_root,
        )
        if (
            external_acquisition.get("acquisition_status")
            == "ACQUIRED_PERSISTENT_PATTERN_ONLY"
        ):
            external_manifest = external_acquisition
    elif persistent_exists:
        external_manifest_path = (
            project_root / "data" / "raw" / "external_2026Q1" / "data_manifest.json"
        )
        if external_manifest_path.is_file():
            external_manifest = json.loads(
                external_manifest_path.read_text(encoding="utf-8")
            )
            valid, problems = verify_external_manifest(
                external_manifest, project_root=project_root
            )
            if not valid:
                raise RuntimeError(f"External manifest failed: {problems}")
        else:
            raise FileNotFoundError(
                "A persistent pattern requires frozen external primary sources"
            )
    ledger = build_external_evidence_ledger(
        pattern_decisions=patterns,
        config=external_config,
        manifest=external_manifest,
    )
    publication = build_publication_decisions(
        phase0_passed=True,
        pattern_decisions=patterns,
        evidence_ledger=ledger,
        config=external_config,
    )

    phase1.leaf_taxonomy_contributions.to_csv(
        output_dir / "industry_leaf_contributions.csv", index=False, encoding="utf-8"
    )
    phase1.major_taxonomy_contributions.to_csv(
        output_dir / "industry_major_contributions.csv", index=False, encoding="utf-8"
    )
    pd.concat(
        [phase1.major_industry_x_capital, phase1.leaf_industry_x_capital],
        ignore_index=True,
        sort=False,
    ).to_csv(
        output_dir / "industry_x_capital_contributions.csv",
        index=False,
        encoding="utf-8",
    )
    phase1.cell_margin_bridge.to_csv(
        output_dir / "cell_margin_bridge.csv", index=False, encoding="utf-8"
    )
    phase1.capital_margin_bridge.to_csv(
        output_dir / "capital_margin_bridge.csv", index=False, encoding="utf-8"
    )
    phase1.ordinary_operating_gap.to_csv(
        output_dir / "ordinary_operating_gap.csv", index=False, encoding="utf-8"
    )
    phase1.software_capex_decomposition.to_csv(
        output_dir / "software_capex_decomposition.csv", index=False, encoding="utf-8"
    )
    phase1.additivity_checks.to_csv(
        output_dir / "phase1_additivity_checks.csv", index=False, encoding="utf-8"
    )
    historical.to_parquet(output_dir / "historical_quarterly.parquet", index=False)
    candidate_series.to_parquet(
        output_dir / "historical_candidate_series.parquet", index=False
    )
    robustness.to_csv(
        output_dir / "historical_robustness.csv", index=False, encoding="utf-8"
    )
    patterns.to_csv(
        output_dir / "pattern_decisions.csv", index=False, encoding="utf-8"
    )
    ledger.to_csv(
        output_dir / "external_evidence_ledger.csv", index=False, encoding="utf-8"
    )
    (output_dir / "decision.md").write_text(
        render_decision_markdown(publication), encoding="utf-8"
    )
    (output_dir / "candidate_headlines.md").write_text(
        render_candidate_headlines(publication), encoding="utf-8"
    )

    base_claims = build_claims_v2(
        phase0_checks=phase1.phase0_checks,
        robustness=robustness,
        publication_decisions=publication,
        capital_margin_bridge=phase1.capital_margin_bridge,
    )
    claims = prepare_claims_v2(
        base_claims,
        central_candidate_id=None,
        public_claim_ids=(),
    )
    claims.to_csv(output_dir / "claims_v2.csv", index=False, encoding="utf-8")

    combined_manifest = _combined_manifest(
        project_root=project_root,
        stage2_config=stage2_config,
        historical_manifest=historical_manifest,
        external_manifest=external_manifest,
        patterns=patterns,
    )
    _json_write(output_dir / "data_manifest_v2.json", combined_manifest)

    charts = build_stage2_charts(
        major_cross=phase1.major_industry_x_capital,
        capital_bridge=phase1.capital_margin_bridge,
        candidate_series=candidate_series,
        robustness=robustness,
        software_decomposition=phase1.software_capex_decomposition,
        ordinary_operating_gap=phase1.ordinary_operating_gap,
        charts_dir=output_dir / "charts",
    )

    article_path = output_dir / "article_public.md"
    if article_path.exists():
        article_path.unlink()
    audit = PublicationAudit()
    _add_core_audit_checks(
        audit=audit,
        project_root=project_root,
        output_dir=output_dir,
        phase1=phase1,
        historical=historical,
        historical_manifest=historical_manifest,
        robustness=robustness,
        patterns=patterns,
        ledger=ledger,
        claims=claims,
        charts=charts,
        v1_before=v1_before,
    )
    validate_public_article(
        article_path=article_path,
        publication_decisions=publication,
        evidence_ledger=ledger,
        claims_v2=claims,
        audit=audit,
    )
    (output_dir / "audit_v2.md").write_text(
        render_publication_audit(audit), encoding="utf-8"
    )
    missing = [
        name for name in STAGE2_REQUIRED_OUTPUTS if not (output_dir / name).is_file()
    ]
    audit.add(
        "required_stage2_outputs",
        not missing,
        "All unconditional Stage 2 artifacts generated"
        if not missing
        else f"missing={missing}",
    )
    audit.add(
        "article_public_conditional_output",
        article_path.is_file() == publication_article_required(publication),
        f"article_exists={article_path.is_file()}, required={publication_article_required(publication)}",
    )
    (output_dir / "audit_v2.md").write_text(
        render_publication_audit(audit), encoding="utf-8"
    )
    return output_dir, audit.status
