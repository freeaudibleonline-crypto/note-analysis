from __future__ import annotations

import base64
import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from .constants import METRIC_RULES, METRIC_SOURCE_ALIASES, Release


ESTAT_ROOT = "https://www.e-stat.go.jp"
USER_AGENT = "corporate-quarterly-pipeline/0.1 (reproducible public-statistics analysis)"


class EStatError(RuntimeError):
    """Raised when e-Stat's public table-view endpoint returns an error."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_new_bytes(path: Path, data: bytes) -> None:
    """Write an immutable raw artifact; refuse accidental replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if sha256_file(path) != sha256_bytes(data):
            raise FileExistsError(
                f"Refusing to overwrite immutable raw artifact with different bytes: {path}"
            )
        return
    path.write_bytes(data)


def _post_json(
    session: requests.Session, url: str, data: dict[str, Any] | None = None
) -> tuple[bytes, dict[str, Any]]:
    response = session.post(url, data=data or {}, timeout=(20, 180))
    response.raise_for_status()
    raw = response.content
    try:
        parsed = response.json()
    except ValueError as exc:  # pragma: no cover - depends on upstream outage
        raise EStatError(f"Response was not JSON: {url}") from exc
    if parsed.get("error"):
        raise EStatError(f"e-Stat error at {url}: {parsed.get('message', parsed)}")
    return raw, parsed


def get_model(session: requests.Session, sid: str) -> tuple[bytes, dict[str, Any]]:
    return _post_json(session, f"{ESTAT_ROOT}/dbview/api_get_model?sid={sid}")


def _compressed_value(value: Any) -> str:
    # e-Stat's public browser client sends each high-cardinality selector as
    # base64(gzip(JSON)). Reproducing that UI request avoids a private API or
    # an e-Stat application key.
    json_bytes = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(gzip.compress(json_bytes)).decode("ascii")


def _find_dimension(model: dict[str, Any], kind: str) -> tuple[str, dict[str, Any]]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    for key, matter in model["matters"].items():
        name = matter["matterName"].replace("　", "")
        if kind == "metric" and "調査項目" in name:
            candidates.append((key, matter))
        elif (
            kind == "industry"
            and "業種" in name
            and "調査項目" not in name
            and "規模" not in name
        ):
            candidates.append((key, matter))
        elif kind == "capital" and "規模" in name:
            candidates.append((key, matter))
        elif kind == "time" and (name.startswith("年期") or name == "年期" or "年期" in name):
            candidates.append((key, matter))
    if len(candidates) != 1:
        raise EStatError(
            f"Could not uniquely identify {kind!r} dimension: {[x[0] for x in candidates]}"
        )
    return candidates[0]


def _canonical_metric_map(metric_matter: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_name = {entry["name"]: entry for entry in metric_matter["listData"].values()}
    selected: dict[str, dict[str, Any]] = {}
    for metric_id, official_name, label in METRIC_RULES:
        aliases = (official_name, *METRIC_SOURCE_ALIASES.get(metric_id, ()))
        entry = next((by_name[name] for name in aliases if name in by_name), None)
        if entry is not None:
            selected[metric_id] = {**entry, "metric_id": metric_id, "metric_label_ja": label}
    return selected


def describe_model(model: dict[str, Any], period_codes: list[str]) -> dict[str, Any]:
    """Return stable, explicit dimension/metric metadata used in the query."""
    metric_key, metric = _find_dimension(model, "metric")
    industry_key, industry = _find_dimension(model, "industry")
    capital_key, capital = _find_dimension(model, "capital")
    time_key, time = _find_dimension(model, "time")
    all_periods = {entry["code"]: entry for entry in time["listData"].values()}
    missing = [code for code in period_codes if code not in all_periods]
    if missing:
        raise EStatError(f"Requested periods are absent from source model: {missing}")
    return {
        "dimension_keys": {
            "metric": metric_key,
            "industry": industry_key,
            "capital": capital_key,
            "time": time_key,
        },
        "metrics": _canonical_metric_map(metric),
        "industry": list(industry["listData"].values()),
        "capital": list(capital["listData"].values()),
        "time": [all_periods[code] for code in period_codes],
    }


def _selector(
    matter: dict[str, Any], entries: list[dict[str, Any]], position_num: int
) -> dict[str, Any]:
    selected_codes = {entry["code"] for entry in entries}
    all_codes = {entry["code"] for entry in matter["listData"].values()}
    return {
        "matterId": matter["matterId"],
        "tableName": matter["tableName"],
        "dispTableName": matter["dispTableName"],
        "positionNum": str(position_num),
        "listData": [
            {
                "name": entry["name"],
                "code": entry["code"],
                "unit": entry.get("unitName"),
                "explanation": entry.get("explanation"),
            }
            for entry in entries
        ],
        "allSelected": int(selected_codes == all_codes),
    }


def build_query_payload(
    model: dict[str, Any], period_codes: list[str]
) -> tuple[dict[str, str | int | None], dict[str, Any]]:
    """Build a table query with all dimensions on rows and metrics in columns.

    This keeps the returned table below e-Stat's display-cell ceiling while
    preserving every requested industry × capital-size × period observation.
    """
    spec = describe_model(model, period_codes)
    keys = spec["dimension_keys"]
    matters = model["matters"]
    metric_entries = list(spec["metrics"].values())
    if not metric_entries:
        raise EStatError("No requested metrics were found in e-Stat model")

    cols = [_selector(matters[keys["metric"]], metric_entries, 1)]
    rows = [
        _selector(matters[keys["industry"]], spec["industry"], 1),
        _selector(matters[keys["capital"]], spec["capital"], 2),
        _selector(matters[keys["time"]], spec["time"], 3),
    ]
    query: dict[str, Any] = {
        "rows": rows,
        "cols": cols,
        "tops": [],
        "apiTops": [],
        "annotationFlg": model.get("annotationFlg", 1),
        "rowNoDataDispFlg": model.get("rowNoDataDispFlg", 0),
        "colNoDataDispFlg": model.get("colNoDataDispFlg", 0),
        "commaType": model.get("commaType", 0),
        "replaceSpChars": model.get("replaceSpChars", 0),
        "graphAxis": model.get("graphAxis", "horizontal"),
        "graphBasis": model.get("graphBasis", "head"),
        "graphSort": model.get("graphSort", "none"),
        "graphTitle": model.get("graphTitle", ""),
        "graphType": model.get("graphType", "barChart"),
        "inputNumberOfCols": 100,
        "inputNumberOfRows": 100000,
        "movementId": 0,
        "leftMoveFlg": 0,
        "rightMoveFlg": 0,
        "underMoveFlg": 0,
        "upMoveFlg": 0,
        "currentCols": None,
        "currentRows": None,
        "mode": "table",
    }
    posted: dict[str, str | int | None] = {}
    for key, value in query.items():
        if key in {"rows", "cols", "tops", "apiTops"}:
            posted[key] = _compressed_value(value)
        elif value is None:
            posted[key] = None
        else:
            posted[key] = value
    return posted, {
        "query": query,
        "dimension_spec": spec,
        "canonical_metric_map": {
            key: {
                "code": value["code"],
                "source_name": value["name"],
                "metric_label_ja": value["metric_label_ja"],
                "source_unit": value.get("unitName"),
            }
            for key, value in spec["metrics"].items()
        },
    }


def get_result(
    session: requests.Session, sid: str, model: dict[str, Any], period_codes: list[str]
) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    payload, query_metadata = build_query_payload(model, period_codes)
    raw, result = _post_json(session, f"{ESTAT_ROOT}/dbview/api_get_result?sid={sid}", payload)
    return raw, result, query_metadata


def _manifest_source(
    *,
    source_id: str,
    role: str,
    provider: str,
    release: Release,
    table_number: str | None,
    title: str,
    url: str,
    raw_path: Path,
    project_root: Path,
    content_type: str,
    coverage_scope: str | None = None,
    seasonal_adjustment: str | None = None,
    sid: str | None = None,
    http_method: str = "GET",
    source_method: str = "DIRECT_DOWNLOAD",
    view_url: str | None = None,
    period_codes: list[str] | None = None,
) -> dict[str, Any]:
    try:
        manifest_path = raw_path.resolve().relative_to(project_root.resolve())
    except ValueError:
        manifest_path = raw_path
    return {
        "source_id": source_id,
        "role": role,
        "provider": provider,
        "release_id": release.release_id,
        "table_number": table_number,
        "table_title": title,
        "estat_sid": sid,
        "url": url,
        "http_method": http_method,
        "source_method": source_method,
        "view_url": view_url,
        "period_codes": period_codes,
        "publication_date": release.publication_date,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "raw_path": str(manifest_path),
        "sha256": sha256_file(raw_path),
        "bytes": raw_path.stat().st_size,
        "content_type": content_type,
        "coverage_scope": coverage_scope,
        "seasonal_adjustment": seasonal_adjustment,
    }


def fetch_release(release: Release, project_root: Path) -> dict[str, Any]:
    """Fetch source bytes once and create a provenance manifest.

    Raw inputs are immutable: a different upstream response must be fetched
    under a new release/vintage rather than overwriting this release's files.
    """
    raw_root = project_root / "data" / "raw" / release.release_id
    raw_root.mkdir(parents=True, exist_ok=True)
    existing_manifest_path = raw_root / "data_manifest.json"
    if existing_manifest_path.exists():
        existing = json.loads(existing_manifest_path.read_text(encoding="utf-8"))
        for source in existing.get("sources", []):
            source_path = Path(source["raw_path"])
            if not source_path.is_absolute():
                source_path = project_root / source_path
            if not source_path.exists():
                fallback = raw_root / Path(source["raw_path"]).name
                if fallback.exists():
                    source_path = fallback
            if not source_path.exists() or sha256_file(source_path) != source["sha256"]:
                raise EStatError(
                    "Existing immutable raw manifest does not match its files; "
                    f"do not overwrite it: {source_path}"
                )
        existing_ids = {source["source_id"] for source in existing.get("sources", [])}
        for source_key, table_spec in release.e_stat_tables.items():
            query_id = f"{source_key}_query"
            if query_id in existing_ids:
                continue
            expected_query_hash = table_spec.get("legacy_frozen_query_sha256")
            query_path = raw_root / f"{source_key}_query.json"
            if (
                not expected_query_hash
                or not query_path.exists()
                or sha256_file(query_path) != expected_query_hash
            ):
                raise EStatError(
                    f"Legacy manifest query metadata is not pinned or has changed: {query_path}"
                )
        return existing
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    sources: list[dict[str, Any]] = []

    for source_key, table_spec in release.e_stat_tables.items():
        sid = table_spec["sid"]
        model_bytes, model = get_model(session, sid)
        model_path = raw_root / f"{source_key}_model.json"
        write_new_bytes(model_path, model_bytes)
        sources.append(
            _manifest_source(
                source_id=f"{source_key}_model",
                role="numeric_authority_metadata",
                provider="e-Stat",
                release=release,
                table_number=table_spec["table_number"],
                title=table_spec["title"],
                url=f"{ESTAT_ROOT}/dbview/api_get_model?sid={sid}",
                raw_path=model_path,
                project_root=project_root,
                content_type="application/json",
                coverage_scope=table_spec["coverage_scope"],
                seasonal_adjustment=table_spec["seasonal_adjustment"],
                sid=sid,
                http_method="POST",
                source_method="ESTAT_DB_VIEW_PUBLIC_UI",
                view_url=f"{ESTAT_ROOT}/dbview?sid={sid}",
                period_codes=release.period_codes,
            )
        )

        result_bytes, result, query_metadata = get_result(
            session, sid, model, release.period_codes
        )
        result_path = raw_root / f"{source_key}_values.json"
        write_new_bytes(result_path, result_bytes)
        query_path = raw_root / f"{source_key}_query.json"
        write_new_bytes(
            query_path, json.dumps(query_metadata, ensure_ascii=False, indent=2).encode("utf-8")
        )
        sources.append(
            _manifest_source(
                source_id=f"{source_key}_query",
                role="request_metadata",
                provider="e-Stat",
                release=release,
                table_number=table_spec["table_number"],
                title=f"{table_spec['title']} query metadata",
                url=f"{ESTAT_ROOT}/dbview/api_get_result?sid={sid}",
                raw_path=query_path,
                project_root=project_root,
                content_type="application/json",
                coverage_scope=table_spec["coverage_scope"],
                seasonal_adjustment=table_spec["seasonal_adjustment"],
                sid=sid,
                http_method="POST",
                source_method="ESTAT_DB_VIEW_PUBLIC_UI",
                view_url=f"{ESTAT_ROOT}/dbview?sid={sid}",
                period_codes=release.period_codes,
            )
        )
        sources.append(
            _manifest_source(
                source_id=source_key,
                role="numeric_authority",
                provider="e-Stat",
                release=release,
                table_number=table_spec["table_number"],
                title=table_spec["title"],
                url=f"{ESTAT_ROOT}/dbview/api_get_result?sid={sid}",
                raw_path=result_path,
                project_root=project_root,
                content_type="application/json",
                coverage_scope=table_spec["coverage_scope"],
                seasonal_adjustment=table_spec["seasonal_adjustment"],
                sid=sid,
                http_method="POST",
                source_method="ESTAT_DB_VIEW_PUBLIC_UI",
                view_url=f"{ESTAT_ROOT}/dbview?sid={sid}",
                period_codes=release.period_codes,
            )
        )

    for source_id, url, filename, title, content_type in (
        (
            "mof_release_pdf",
            release.mof_pdf_url,
            "mof_release.pdf",
            "法人企業統計調査・令和8年1〜3月期結果概要",
            "application/pdf",
        ),
        (
            "mof_published_sa_rates",
            release.mof_percent_excel_url,
            "mof_percent.xlsx",
            "季節調整済前期比増加率",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    ):
        response = session.get(url, timeout=(20, 180))
        response.raise_for_status()
        path = raw_root / filename
        write_new_bytes(path, response.content)
        sources.append(
            _manifest_source(
                source_id=source_id,
                role=(
                    "definition_and_ranking_check"
                    if source_id.endswith("pdf")
                    else "published_rate_check"
                ),
                provider="Ministry of Finance Japan",
                release=release,
                table_number=None,
                title=title,
                url=url,
                raw_path=path,
                project_root=project_root,
                content_type=content_type,
                http_method="GET",
                source_method="MOF_DIRECT_DOWNLOAD",
            )
        )

    manifest = {
        "manifest_version": 2,
        "release_id": release.release_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_policy": {
            "numeric_authority": "e-Stat structured table-view responses",
            "pdf_role": "definitions, notes, and published-ranking cross-check only",
            "raw_mutation": "forbidden; files are written once and hash-checked thereafter",
            "e_stat_transport": (
                "ESTAT_DB_VIEW_PUBLIC_UI structured JSON endpoints; no application key. "
                "Request metadata, response bytes, retrieval time, and SHA-256 are frozen."
            ),
        },
        "sources": sources,
    }
    manifest_path = raw_root / "data_manifest.json"
    write_new_bytes(
        manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    )
    return manifest


def load_raw_manifest(project_root: Path, release: Release) -> dict[str, Any]:
    path = project_root / "data" / "raw" / release.release_id / "data_manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"Raw manifest not found. Run fetch first: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
