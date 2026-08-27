from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .article import render_article
from .audit import (
    audit_markdown,
    validate_article_claims,
    validate_claim_table,
    validate_data,
    write_quality_log,
)
from .charts import CHART_FILENAMES, build_charts
from .claims import build_claims
from .constants import PROJECT_ROOT, REQUIRED_OUTPUTS, Release, load_release
from .contributions import (
    build_capital_contributions,
    build_industry_contributions,
    positive_contribution_concentration,
)
from .estat import fetch_release, load_raw_manifest, sha256_file
from .processing import build_processed


def _source_path(project_root: Path, raw_path: str, release: Release) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = project_root / path
    if path.exists():
        return path
    fallback = project_root / "data" / "raw" / release.release_id / Path(raw_path).name
    if fallback.exists():
        return fallback
    return path


def normalized_output_manifest(
    raw_manifest: dict[str, Any], project_root: Path, release: Release
) -> dict[str, Any]:
    """Upgrade legacy acquisition manifests without changing any raw bytes."""
    manifest = deepcopy(raw_manifest)
    manifest["manifest_version"] = 2
    manifest["release_id"] = release.release_id
    policy = manifest.setdefault("source_policy", {})
    policy.update(
        {
            "numeric_authority": "e-Stat structured table-view responses",
            "pdf_role": "definitions, notes, published rates and rankings cross-check only",
            "raw_mutation": "forbidden; files are written once and hash-checked thereafter",
            "e_stat_transport": (
                "ESTAT_DB_VIEW_PUBLIC_UI structured JSON endpoints; no application key. "
                "Model, request metadata, response, retrieval time and SHA-256 are frozen."
            ),
        }
    )
    by_id: dict[str, dict[str, Any]] = {}
    for source in manifest.get("sources", []):
        path = _source_path(project_root, source["raw_path"], release)
        source["raw_path"] = str(path.resolve().relative_to(project_root.resolve()))
        if source.get("provider") == "e-Stat":
            sid = source["estat_sid"]
            source.update(
                {
                    "http_method": "POST",
                    "source_method": "ESTAT_DB_VIEW_PUBLIC_UI",
                    "view_url": f"https://www.e-stat.go.jp/dbview?sid={sid}",
                    "period_codes": release.period_codes,
                }
            )
            if not source["source_id"].endswith("_model"):
                source["url"] = (
                    f"https://www.e-stat.go.jp/dbview/api_get_result?sid={sid}"
                )
        else:
            source.update(
                {
                    "http_method": "GET",
                    "source_method": "MOF_DIRECT_DOWNLOAD",
                    "view_url": None,
                    "period_codes": None,
                }
            )
        by_id[source["source_id"]] = source

    for source_key, table in release.e_stat_tables.items():
        query_id = f"{source_key}_query"
        if query_id in by_id:
            continue
        query_path = project_root / "data" / "raw" / release.release_id / f"{source_key}_query.json"
        if not query_path.exists():
            raise FileNotFoundError(f"Missing frozen e-Stat request metadata: {query_path}")
        actual_query_sha256 = sha256_file(query_path)
        frozen_query_sha256 = table.get("legacy_frozen_query_sha256")
        if not frozen_query_sha256:
            raise ValueError(
                f"Legacy manifest omits {query_id}; release config must pin its original SHA-256"
            )
        if actual_query_sha256 != frozen_query_sha256:
            raise ValueError(
                f"Frozen query metadata hash mismatch for {query_id}: "
                f"expected {frozen_query_sha256}, observed {actual_query_sha256}"
            )
        result_source = by_id[source_key]
        entry = {
            "source_id": query_id,
            "role": "request_metadata",
            "provider": "e-Stat",
            "release_id": release.release_id,
            "table_number": table["table_number"],
            "table_title": f"{table['title']} query metadata",
            "estat_sid": table["sid"],
            "url": f"https://www.e-stat.go.jp/dbview/api_get_result?sid={table['sid']}",
            "http_method": "POST",
            "source_method": "ESTAT_DB_VIEW_PUBLIC_UI",
            "view_url": f"https://www.e-stat.go.jp/dbview?sid={table['sid']}",
            "period_codes": release.period_codes,
            "publication_date": release.publication_date,
            "retrieved_at": result_source["retrieved_at"],
            "raw_path": str(query_path.resolve().relative_to(project_root.resolve())),
            "sha256": frozen_query_sha256,
            "bytes": query_path.stat().st_size,
            "content_type": "application/json",
            "coverage_scope": table["coverage_scope"],
            "seasonal_adjustment": table["seasonal_adjustment"],
        }
        manifest["sources"].append(entry)
        by_id[query_id] = entry

    manifest["sources"] = sorted(
        manifest["sources"], key=lambda source: source["source_id"]
    )
    manifest["release_configuration"] = {
        "publication_date": release.publication_date,
        "target_period_code": release.target_period_code,
        "prior_yoy_period_code": release.prior_yoy_period_code,
        "prior_qoq_period_code": release.prior_qoq_period_code,
        "pdf_reference_checks": release.pdf_reference_checks,
        "pdf_reference_method": (
            "Manual transcription from the frozen MOF PDF pages named in the release "
            "configuration, visually double-checked; structured e-Stat remains the numeric authority."
        ),
    }
    return manifest


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_failure_stubs(output_dir: Path, release: Release, reason: str) -> None:
    """Invalidate any prior PASS article before or after an interrupted build."""
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_reason = reason.replace("|", "／")
    (output_dir / "article.md").write_text(
        "\n".join(
            [
                f"# 法人企業統計分析 — {release.release_label_ja}",
                "",
                "**STATUS: FAIL**",
                "",
                "生成または監査が完了していないため、この記事は完成扱いにできない。",
                "",
                f"理由: {safe_reason}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (output_dir / "audit_report.md").write_text(
        "\n".join(
            [
                f"# 監査報告 — {release.release_label_ja}",
                "",
                "**STATUS: FAIL**",
                "",
                f"- BUILD_INCOMPLETE: {safe_reason}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def build_release(
    release_id: str = "2026Q1",
    *,
    project_root: Path = PROJECT_ROOT,
    offline: bool = True,
) -> tuple[Path, str]:
    release = load_release(release_id)
    output_dir = project_root / "outputs" / release.release_id
    charts_dir = output_dir / "charts"
    write_failure_stubs(output_dir, release, "build started; publication gate not yet complete")
    if not offline:
        fetch_release(release, project_root)
    raw_manifest = load_raw_manifest(project_root, release)
    manifest = normalized_output_manifest(raw_manifest, project_root, release)

    processed, parse_issues = build_processed(project_root, release)
    industry = build_industry_contributions(processed)
    capital = build_capital_contributions(processed)
    concentration = positive_contribution_concentration(industry)
    claims = build_claims(processed, industry, capital)

    audit = validate_data(
        processed=processed,
        manifest=manifest,
        parse_issues=parse_issues,
        release=release,
        project_root=project_root,
    )
    validate_claim_table(claims, audit)

    output_dir.mkdir(parents=True, exist_ok=True)
    charts_dir.mkdir(parents=True, exist_ok=True)

    _write_json(output_dir / "data_manifest.json", manifest)
    processed.to_parquet(output_dir / "processed_quarterly.parquet", index=False)
    industry.to_csv(output_dir / "industry_contributions.csv", index=False, encoding="utf-8")
    capital.to_csv(
        output_dir / "capital_size_contributions.csv", index=False, encoding="utf-8"
    )
    concentration.to_csv(
        output_dir / "industry_concentration.csv", index=False, encoding="utf-8"
    )
    claims.to_csv(output_dir / "claims.csv", index=False, encoding="utf-8")
    write_quality_log(output_dir / "data_quality_log.json", audit)

    chart_paths = build_charts(
        processed, industry, capital, charts_dir, claims=claims
    )
    chart_claim_count = int(claims["claim_usage"].eq("CHART_INPUT").sum())
    audit.add(
        "chart_inputs_claim_backed",
        chart_claim_count > 0,
        f"{chart_claim_count} exact plotted values matched to CHART_INPUT rows in claims.csv",
    )
    expected_chart_names = set(CHART_FILENAMES)
    actual_chart_names = {path.name for path in chart_paths if path.is_file()}
    chart_sizes_ok = all(path.stat().st_size > 10_000 for path in chart_paths)
    audit.add(
        "chart_artifacts_complete",
        actual_chart_names == expected_chart_names and chart_sizes_ok,
        f"charts={sorted(actual_chart_names)}, nontrivial_png_bytes={chart_sizes_ok}",
    )

    article_path = output_dir / "article.md"
    article_path.write_text(render_article(claims, release, status="FAIL"), encoding="utf-8")
    validate_article_claims(article_path, claims, audit)

    # Write once so the artifact-completeness check includes the audit itself,
    # then rewrite with the check's final result.
    audit_path = output_dir / "audit_report.md"
    audit_path.write_text(audit_markdown(audit, release), encoding="utf-8")
    missing_outputs = [
        name for name in REQUIRED_OUTPUTS if not (output_dir / name).is_file()
    ]
    audit.add(
        "required_output_artifacts",
        not missing_outputs,
        "All required artifacts generated"
        if not missing_outputs
        else f"Missing outputs: {', '.join(missing_outputs)}",
    )
    if audit.passed:
        article_path.write_text(
            render_article(claims, release, status="PASS"), encoding="utf-8"
        )
    audit_path.write_text(audit_markdown(audit, release), encoding="utf-8")
    return output_dir, audit.status
