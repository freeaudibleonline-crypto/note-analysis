"""Current-vintage historical series and pre-registered Phase 2 decisions.

This module is deliberately separate from the one-quarter publication pipeline.
It downloads a narrow, auditable slice of e-Stat table 1 that is sufficient for
the five pre-registered article candidates.  The upstream model, exact POST
request metadata, response bytes and a SHA-256 manifest are frozen under
``data/raw/historical_2026Q1``.

The downloaded history is a *current-vintage historical series*: it is the
history exposed by e-Stat at acquisition time.  It does not establish robustness
to revisions because prior publication vintages were not archived.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import requests

from .constants import PROJECT_ROOT, Release, load_release
from .estat import (
    ESTAT_ROOT,
    USER_AGENT,
    _canonical_metric_map,
    _compressed_value,
    _find_dimension,
    _post_json,
    _selector,
    sha256_file,
    write_new_bytes,
)
from .processing import (
    _period_end,
    _to_oku_yen,
    detect_profit_transition,
    parse_estat_response,
)


STAGE2_CONFIG_NAME = "stage2_2026Q1.json"
HISTORICAL_SID = "0003060191"
HISTORICAL_TABLE_NUMBER = "1"
TARGET_PERIOD_CODE = "20261"
CURRENT_VINTAGE_STATUS = "CURRENT_VINTAGE_HISTORICAL_SERIES"
REVISION_STATUS = "NOT_TESTED_NO_PRIOR_PUBLICATION_VINTAGES"

HISTORICAL_METRICS = (
    "sales",
    "operating_profit",
    "ordinary_profit",
    "capex_including_software",
    "capex_excluding_software",
)

# Only the mutually distinguishable series needed by candidates A--E are
# downloaded.  Codes and names are both checked against the current e-Stat model;
# a code silently changing meaning is therefore a hard failure.
HISTORICAL_INDUSTRIES = {
    "104": "全産業（除く金融保険業）",
    "108": "製造業",
    "145": "情報通信機械器具製造業",
}
HISTORICAL_CAPITAL_SIZES = {
    "26": "全規模",
    "25": "10億円以上",
    "19": "1千万円以上 - 1億円未満",
}

DERIVED_METRICS = {
    "software_capex_derived": {
        "label": "ソフトウェア投資（設備投資二系列の差額）",
        "unit": "億円",
        "inputs": ("capex_including_software", "capex_excluding_software"),
        "definition": "capex_including_software - capex_excluding_software",
    },
    "net_non_operating_gap": {
        "label": "経常利益－営業利益（純差額）",
        "unit": "億円",
        "inputs": ("ordinary_profit", "operating_profit"),
        "definition": "ordinary_profit - operating_profit",
    },
    "operating_margin_pct": {
        "label": "売上高営業利益率",
        "unit": "%",
        "inputs": ("operating_profit", "sales"),
        "definition": "operating_profit / sales * 100",
    },
    "ordinary_margin_pct": {
        "label": "売上高経常利益率",
        "unit": "%",
        "inputs": ("ordinary_profit", "sales"),
        "definition": "ordinary_profit / sales * 100",
    },
}

FLOW_MONEY_METRICS = {
    *HISTORICAL_METRICS,
    "software_capex_derived",
    "net_non_operating_gap",
}
PROFIT_LEVEL_METRICS = {"operating_profit", "ordinary_profit"}
MARGIN_METRICS = {"operating_margin_pct", "ordinary_margin_pct"}


class HistoricalDataError(RuntimeError):
    """Raised when a historical snapshot cannot be used without silent splicing."""


@dataclass(frozen=True)
class PatternEvidence:
    decision: str
    same_direction_last4: int
    same_direction_last8: int
    valid_last4: int
    valid_last8: int
    same_direction_run_length: int
    rolling_4q_same_direction: bool
    historical_percentile: float | None


def load_stage2_config(project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    path = Path(project_root) / "config" / STAGE2_CONFIG_NAME
    if not path.exists():
        raise FileNotFoundError(f"Stage 2 configuration not found: {path}")
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("CONFIG_KIND") != "EXECUTABLE_STAGE2_CONFIGURATION":
        raise HistoricalDataError(f"Not an executable Stage 2 configuration: {path}")
    if not config.get("pattern_rule", {}).get("criteria_frozen_before_analysis"):
        raise HistoricalDataError("Pattern criteria must be frozen before analysis")
    return config


def _raw_root(project_root: Path, config: dict[str, Any]) -> Path:
    return Path(project_root) / "data" / "raw" / config["historical_vintage_id"]


def _ordered_periods(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    periods = [
        entry
        for entry in entries
        if re.fullmatch(r"\d{5}", str(entry.get("code", "")))
        and int(entry["code"]) <= int(TARGET_PERIOD_CODE)
    ]
    periods.sort(key=lambda entry: int(entry["code"]))
    if not periods or periods[-1]["code"] != TARGET_PERIOD_CODE:
        raise HistoricalDataError(
            f"Target period {TARGET_PERIOD_CODE} is absent from the current e-Stat model"
        )
    return periods


def _select_exact(
    matter: dict[str, Any], expected: dict[str, str], *, dimension: str
) -> list[dict[str, Any]]:
    by_code = {str(entry["code"]): entry for entry in matter["listData"].values()}
    selected: list[dict[str, Any]] = []
    failures: list[str] = []
    for code, expected_name in expected.items():
        entry = by_code.get(code)
        if entry is None:
            failures.append(f"missing code {code}")
        elif entry.get("name") != expected_name:
            failures.append(
                f"code {code}: expected {expected_name!r}, observed {entry.get('name')!r}"
            )
        else:
            selected.append(entry)
    if failures:
        raise HistoricalDataError(
            f"{dimension} classification changed; refusing silent connection: "
            + "; ".join(failures)
        )
    return selected


def build_historical_query(
    model: dict[str, Any], *, target_period_code: str = TARGET_PERIOD_CODE
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Build the exact narrow DB-view request used for the frozen history."""
    if target_period_code != TARGET_PERIOD_CODE:
        raise HistoricalDataError(
            "This frozen Stage 2 design is registered for target period 20261 only"
        )
    metric_key, metric_matter = _find_dimension(model, "metric")
    industry_key, industry_matter = _find_dimension(model, "industry")
    capital_key, capital_matter = _find_dimension(model, "capital")
    time_key, time_matter = _find_dimension(model, "time")

    metric_map = _canonical_metric_map(metric_matter)
    missing_metrics = sorted(set(HISTORICAL_METRICS) - set(metric_map))
    if missing_metrics:
        raise HistoricalDataError(
            f"Required metrics disappeared or were renamed: {missing_metrics}"
        )
    metrics = [metric_map[metric_id] for metric_id in HISTORICAL_METRICS]
    industries = _select_exact(
        industry_matter, HISTORICAL_INDUSTRIES, dimension="industry"
    )
    capital_sizes = _select_exact(
        capital_matter, HISTORICAL_CAPITAL_SIZES, dimension="capital size"
    )
    periods = _ordered_periods(time_matter["listData"].values())

    matters = model["matters"]
    query: dict[str, Any] = {
        "rows": [
            _selector(matters[industry_key], industries, 1),
            _selector(matters[capital_key], capital_sizes, 2),
            _selector(matters[time_key], periods, 3),
        ],
        "cols": [_selector(matters[metric_key], metrics, 1)],
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
    posted = {
        key: _compressed_value(value)
        if key in {"rows", "cols", "tops", "apiTops"}
        else value
        for key, value in query.items()
    }
    metadata = {
        "query_schema_version": 1,
        "historical_vintage_id": "historical_2026Q1",
        "vintage_status": CURRENT_VINTAGE_STATUS,
        "revision_robustness_status": REVISION_STATUS,
        "request": {
            "http_method": "POST",
            "url": f"{ESTAT_ROOT}/dbview/api_get_result?sid={HISTORICAL_SID}",
            "form_payload": posted,
        },
        "query": query,
        "dimension_keys": {
            "metric": metric_key,
            "industry": industry_key,
            "capital": capital_key,
            "time": time_key,
        },
        "dimension_spec": {
            "industry": industries,
            "capital": capital_sizes,
            "time": periods,
        },
        "canonical_metric_map": {
            metric_id: {
                "code": metric_map[metric_id]["code"],
                "source_name": metric_map[metric_id]["name"],
                "metric_label_ja": metric_map[metric_id]["metric_label_ja"],
                "source_unit": metric_map[metric_id].get("unitName"),
            }
            for metric_id in HISTORICAL_METRICS
        },
    }
    return posted, metadata, {
        "periods": periods,
        "industries": industries,
        "capital_sizes": capital_sizes,
        "metrics": metrics,
    }


def _relative(path: Path, project_root: Path) -> str:
    return str(path.resolve().relative_to(Path(project_root).resolve()))


def _source_manifest_entry(
    *,
    source_id: str,
    role: str,
    url: str,
    http_method: str,
    path: Path,
    project_root: Path,
    retrieved_at: str,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "role": role,
        "provider": "e-Stat",
        "table_number": HISTORICAL_TABLE_NUMBER,
        "estat_sid": HISTORICAL_SID,
        "url": url,
        "http_method": http_method,
        "retrieved_at": retrieved_at,
        "raw_path": _relative(path, project_root),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "content_type": "application/json",
        "coverage_scope": "EXCL_FINANCE_INSURANCE",
        "seasonal_adjustment": "RAW",
    }


def verify_historical_manifest(
    manifest: dict[str, Any], project_root: Path = PROJECT_ROOT
) -> None:
    failures: list[str] = []
    for source in manifest.get("sources", []):
        path = Path(source["raw_path"])
        if not path.is_absolute():
            path = Path(project_root) / path
        if not path.exists():
            failures.append(f"missing:{path}")
        elif sha256_file(path) != source.get("sha256"):
            failures.append(f"hash_mismatch:{source.get('source_id')}")
    if failures:
        raise HistoricalDataError("Historical raw verification failed: " + ", ".join(failures))


def _parse_historical_paths(
    *, values_path: Path, query_path: Path, release: Release
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    return parse_estat_response(
        result_path=values_path,
        query_path=query_path,
        table_spec={
            "coverage_scope": "EXCL_FINANCE_INSURANCE",
            "seasonal_adjustment": "RAW",
            "table_number": HISTORICAL_TABLE_NUMBER,
            "sid": HISTORICAL_SID,
        },
        release=release,
    )


def summarize_series_availability(
    parsed: pd.DataFrame, period_codes: Iterable[str]
) -> list[dict[str, Any]]:
    """Find first present and internal gaps for every requested direct series."""
    ordered = sorted({str(code) for code in period_codes}, key=int)
    position = {code: index for index, code in enumerate(ordered)}
    rows: list[dict[str, Any]] = []
    keys = ["industry_code", "capital_size_code", "metric_id"]
    grouped = {key: frame for key, frame in parsed.groupby(keys, dropna=False)}
    for industry_code, capital_code, metric_id in product(
        HISTORICAL_INDUSTRIES, HISTORICAL_CAPITAL_SIZES, HISTORICAL_METRICS
    ):
        key = (industry_code, capital_code, metric_id)
        frame = grouped.get(key)
        if frame is None:
            present_codes: list[str] = []
        else:
            present_codes = sorted(
                frame.loc[frame["source_value"].notna(), "period_code"]
                .astype(str)
                .unique(),
                key=int,
            )
        first = present_codes[0] if present_codes else None
        last = present_codes[-1] if present_codes else None
        if first is None:
            internal_missing = []
        else:
            expected = ordered[position[first] : position[last] + 1]
            internal_missing = sorted(set(expected) - set(present_codes), key=int)
        rows.append(
            {
                "series_id": f"i{industry_code}_c{capital_code}_{metric_id}",
                "industry_code": industry_code,
                "industry_name": HISTORICAL_INDUSTRIES[industry_code],
                "capital_size_code": capital_code,
                "capital_size_name": HISTORICAL_CAPITAL_SIZES[capital_code],
                "metric_id": metric_id,
                "source_first_present_period_code": first,
                "source_last_present_period_code": last,
                "present_quarter_count": len(present_codes),
                "internal_missing_count": len(internal_missing),
                "internal_missing_period_codes": internal_missing,
            }
        )
    return rows


def detect_software_definition_start(
    parsed: pd.DataFrame, *, tolerance: float = 0.0
) -> tuple[str, list[dict[str, Any]]]:
    """Detect when the including/excluding capex columns first diverge.

    Prior rows are retained as source history but are not treated as observations
    of software investment.  In the frozen source the two columns are identical
    through 2001Q2 and first differ in 2001Q3.
    """
    keys = ["industry_code", "capital_size_code", "period_code"]
    wide = parsed.loc[
        parsed["metric_id"].isin(
            ("capex_including_software", "capex_excluding_software")
        ),
        keys + ["metric_id", "source_value"],
    ].pivot(index=keys, columns="metric_id", values="source_value")
    if not {
        "capex_including_software",
        "capex_excluding_software",
    } <= set(wide.columns):
        raise HistoricalDataError("Both capex columns are required to detect the definition start")
    wide["difference"] = (
        wide["capex_including_software"] - wide["capex_excluding_software"]
    )
    reference = wide.xs(("104", "26"), level=("industry_code", "capital_size_code"))
    nonzero = reference.loc[reference["difference"].abs().gt(tolerance)]
    if nonzero.empty:
        raise HistoricalDataError("No mechanical software-capex definition break was detected")
    start = str(sorted(nonzero.index.astype(str), key=int)[0])
    events: list[dict[str, Any]] = [
        {
            "kind": "CAPEX_SOFTWARE_DEFINITION_START",
            "severity": "INFO",
            "period_code": start,
            "detail": (
                "The including and excluding capex columns first differ in the "
                "all-industry/all-capital source cell; earlier identical columns "
                "are not interpreted as measured zero software investment."
            ),
        }
    ]
    for (industry_code, capital_code), frame in wide.groupby(
        level=("industry_code", "capital_size_code")
    ):
        frame = frame.reset_index()
        before = frame.loc[frame["period_code"].astype(int).lt(int(start)), "difference"]
        bad_before = before.dropna().abs().gt(tolerance).any()
        if bad_before:
            events.append(
                {
                    "kind": "CAPEX_SOFTWARE_BREAK_CONFLICT",
                    "severity": "FAIL",
                    "industry_code": industry_code,
                    "capital_size_code": capital_code,
                    "detail": f"Non-zero capex difference observed before {start}",
                }
            )
    return start, events


def _historical_manifest(
    *,
    project_root: Path,
    config: dict[str, Any],
    release: Release,
    model_path: Path,
    query_path: Path,
    values_path: Path,
    model_retrieved_at: str,
    values_retrieved_at: str,
    query_created_at: str,
    selection: dict[str, Any],
    availability: list[dict[str, Any]],
    software_start: str,
    structural_events: list[dict[str, Any]],
    parse_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    model_url = f"{ESTAT_ROOT}/dbview/api_get_model?sid={HISTORICAL_SID}"
    values_url = f"{ESTAT_ROOT}/dbview/api_get_result?sid={HISTORICAL_SID}"
    periods = selection["periods"]
    legacy_industries = [
        {"code": entry["code"], "name": entry["name"]}
        for entry in selection.get("model_industries", [])
        if "H20年度まで" in entry.get("name", "")
    ]
    return {
        "manifest_version": 1,
        "historical_vintage_id": config["historical_vintage_id"],
        "base_release_id": release.release_id,
        "publication_date": release.publication_date,
        "generated_at": datetime.now(UTC).isoformat(),
        "vintage_status": CURRENT_VINTAGE_STATUS,
        "historical_vintage_label": config["historical_vintage_label"],
        "revision_robustness_status": REVISION_STATUS,
        "revision_caveat": (
            "This snapshot uses the history returned by e-Stat at acquisition time. "
            "No earlier publication vintages are available, so robustness to revisions "
            "has not been tested."
        ),
        "numeric_authority": "e-Stat table 1 DB-view structured JSON response",
        "raw_mutation_policy": "immutable; refuse overwrite and verify every SHA-256",
        "selection": {
            "metrics": [
                {
                    "metric_id": metric_id,
                    "code": next(
                        entry["code"]
                        for entry in selection["metrics"]
                        if entry["metric_id"] == metric_id
                    ),
                    "source_name": next(
                        entry["name"]
                        for entry in selection["metrics"]
                        if entry["metric_id"] == metric_id
                    ),
                }
                for metric_id in HISTORICAL_METRICS
            ],
            "industries": [
                {"code": entry["code"], "name": entry["name"]}
                for entry in selection["industries"]
            ],
            "capital_sizes": [
                {"code": entry["code"], "name": entry["name"]}
                for entry in selection["capital_sizes"]
            ],
            "model_first_period_code": periods[0]["code"],
            "model_first_period_label": periods[0]["name"],
            "model_last_period_code": periods[-1]["code"],
            "model_last_period_label": periods[-1]["name"],
            "model_period_count": len(periods),
        },
        "mechanical_availability": availability,
        "software_capex_comparable_start_period_code": software_start,
        "quality_log": [*structural_events, *parse_issues],
        "classification_policy": {
            "selected_codes_names_must_match_current_model": True,
            "legacy_model_industries_excluded_from_selected_series": legacy_industries,
            "silent_splicing": "forbidden",
        },
        "sample_replacement_notice": (
            "Quarter code 2 (April-June) is marked as the annual sample-replacement "
            "quarter in the analytical panel; raw quarter-on-quarter comparisons are "
            "not used for the registered tests."
        ),
        "sources": [
            _source_manifest_entry(
                source_id="historical_table1_model",
                role="dimension_and_table_metadata",
                url=model_url,
                http_method="POST",
                path=model_path,
                project_root=project_root,
                retrieved_at=model_retrieved_at,
            ),
            _source_manifest_entry(
                source_id="historical_table1_query",
                role="exact_request_metadata",
                url=values_url,
                http_method="POST",
                path=query_path,
                project_root=project_root,
                retrieved_at=query_created_at,
            ),
            _source_manifest_entry(
                source_id="historical_table1_values",
                role="numeric_authority",
                url=values_url,
                http_method="POST",
                path=values_path,
                project_root=project_root,
                retrieved_at=values_retrieved_at,
            ),
        ],
    }


def fetch_historical_snapshot(
    project_root: Path = PROJECT_ROOT,
    *,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Fetch and freeze the current-vintage historical response.

    If a completed manifest already exists, no network call is made.  Every file
    is hash-verified and a changed byte causes failure rather than replacement.
    """
    project_root = Path(project_root)
    config = load_stage2_config(project_root)
    release = load_release("2026Q1")
    raw_root = _raw_root(project_root, config)
    manifest_path = raw_root / "data_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        verify_historical_manifest(manifest, project_root)
        return manifest

    raw_root.mkdir(parents=True, exist_ok=True)
    client = session or requests.Session()
    client.headers.update({"User-Agent": USER_AGENT})
    model_url = f"{ESTAT_ROOT}/dbview/api_get_model?sid={HISTORICAL_SID}"
    model_bytes, model = _post_json(client, model_url)
    model_retrieved_at = datetime.now(UTC).isoformat()
    model_path = raw_root / "historical_table1_model.json"
    write_new_bytes(model_path, model_bytes)

    posted, query_metadata, selected = build_historical_query(model)
    query_created_at = datetime.now(UTC).isoformat()
    query_metadata["created_at"] = query_created_at
    query_bytes = (
        json.dumps(query_metadata, ensure_ascii=False, indent=2).encode("utf-8")
        + b"\n"
    )
    query_path = raw_root / "historical_table1_query.json"
    write_new_bytes(query_path, query_bytes)

    values_url = f"{ESTAT_ROOT}/dbview/api_get_result?sid={HISTORICAL_SID}"
    values_bytes, result = _post_json(client, values_url, posted)
    if not result.get("table"):
        raise HistoricalDataError("Historical e-Stat response contains no table")
    values_retrieved_at = datetime.now(UTC).isoformat()
    values_path = raw_root / "historical_table1_values.json"
    write_new_bytes(values_path, values_bytes)

    parsed, parse_issues = _parse_historical_paths(
        values_path=values_path, query_path=query_path, release=release
    )
    period_codes = [entry["code"] for entry in selected["periods"]]
    availability = summarize_series_availability(parsed, period_codes)
    missing_series = [
        row["series_id"]
        for row in availability
        if row["source_first_present_period_code"] is None
    ]
    if missing_series:
        raise HistoricalDataError(f"Requested historical series are wholly absent: {missing_series}")
    software_start, structural_events = detect_software_definition_start(parsed)
    fatal_events = [
        event for event in [*structural_events, *parse_issues] if event.get("severity") == "FAIL"
    ]
    if fatal_events:
        raise HistoricalDataError(f"Historical structure audit failed: {fatal_events}")

    # Preserve the full model's legacy-category evidence in the manifest while
    # keeping it out of the selected analytical response.
    _, industry_matter = _find_dimension(model, "industry")
    selected["model_industries"] = list(industry_matter["listData"].values())
    selected["metrics"] = [
        {**entry, "metric_id": metric_id}
        for metric_id, entry in zip(HISTORICAL_METRICS, selected["metrics"], strict=True)
    ]
    manifest = _historical_manifest(
        project_root=project_root,
        config=config,
        release=release,
        model_path=model_path,
        query_path=query_path,
        values_path=values_path,
        model_retrieved_at=model_retrieved_at,
        values_retrieved_at=values_retrieved_at,
        query_created_at=query_created_at,
        selection=selected,
        availability=availability,
        software_start=software_start,
        structural_events=structural_events,
        parse_issues=parse_issues,
    )
    write_new_bytes(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
    )
    return manifest


def load_historical_snapshot(
    project_root: Path = PROJECT_ROOT,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    """Load and verify the frozen historical response and request metadata."""
    project_root = Path(project_root)
    config = load_stage2_config(project_root)
    raw_root = _raw_root(project_root, config)
    manifest_path = raw_root / "data_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Historical snapshot is absent; call fetch_historical_snapshot first: {manifest_path}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verify_historical_manifest(manifest, project_root)
    query_path = raw_root / "historical_table1_query.json"
    values_path = raw_root / "historical_table1_values.json"
    parsed, issues = _parse_historical_paths(
        values_path=values_path,
        query_path=query_path,
        release=load_release("2026Q1"),
    )
    if any(issue.get("severity") == "FAIL" for issue in issues):
        raise HistoricalDataError(f"Historical parse failed: {issues}")
    query_metadata = json.loads(query_path.read_text(encoding="utf-8"))
    return parsed, manifest, query_metadata


def _period_metadata(query_metadata: dict[str, Any]) -> pd.DataFrame:
    frame = pd.DataFrame(query_metadata["dimension_spec"]["time"])[["code", "name"]]
    frame = frame.rename(columns={"code": "period_code", "name": "period"})
    frame["period_code"] = frame["period_code"].astype(str)
    frame["period_ordinal"] = frame["period_code"].map(
        lambda code: int(code[:4]) * 4 + int(code[-1]) - 1
    )
    frame["period_end"] = frame["period_code"].map(_period_end)
    return frame.sort_values("period_ordinal", kind="stable").reset_index(drop=True)


def _comparison_start(
    metric_id: str, source_start: str, software_start: str
) -> str:
    if metric_id in {
        "capex_including_software",
        "capex_excluding_software",
        "software_capex_derived",
    }:
        return str(max(int(source_start), int(software_start)))
    return source_start


def _materialize_direct_panel(
    parsed: pd.DataFrame,
    manifest: dict[str, Any],
    query_metadata: dict[str, Any],
    project_root: Path,
) -> pd.DataFrame:
    periods = _period_metadata(query_metadata)
    period_position = {
        code: index for index, code in enumerate(periods["period_code"].tolist())
    }
    availability = {
        (
            row["industry_code"],
            row["capital_size_code"],
            row["metric_id"],
        ): row
        for row in manifest["mechanical_availability"]
    }
    frames: list[pd.DataFrame] = []
    for key, info in availability.items():
        industry_code, capital_code, metric_id = key
        source_start = info["source_first_present_period_code"]
        if source_start is None:
            continue
        expected_periods = periods.iloc[period_position[source_start] :].copy()
        source = parsed.loc[
            parsed["industry_code"].astype(str).eq(industry_code)
            & parsed["capital_size_code"].astype(str).eq(capital_code)
            & parsed["metric_id"].eq(metric_id)
        ].copy()
        if source.empty:
            raise HistoricalDataError(f"Manifest/source mismatch for {key}")
        template = source.iloc[-1]
        source["period_code"] = source["period_code"].astype(str)
        keep = [
            "period_code",
            "source_value",
            "missing_status",
            "source_cell_key",
        ]
        merged = expected_periods.merge(source[keep], on="period_code", how="left")
        merged["release_id"] = "historical_2026Q1"
        merged["coverage_scope"] = "EXCL_FINANCE_INSURANCE"
        merged["seasonal_adjustment"] = "RAW"
        merged["industry_code"] = industry_code
        merged["industry_name"] = HISTORICAL_INDUSTRIES[industry_code]
        merged["capital_size_code"] = capital_code
        merged["capital_size_name"] = HISTORICAL_CAPITAL_SIZES[capital_code]
        merged["metric_id"] = metric_id
        merged["metric_label_ja"] = template["metric_label_ja"]
        merged["source_metric_name"] = template["source_metric_name"]
        merged["source_unit"] = template["source_unit"]
        merged["source_table_number"] = HISTORICAL_TABLE_NUMBER
        merged["estat_sid"] = HISTORICAL_SID
        merged["source_path"] = _relative(
            Path(template["source_path"]), Path(project_root)
        )
        merged["source_sha256"] = template["source_sha256"]
        merged["metric_origin"] = "DIRECT_ESTAT_CURRENT_VINTAGE"
        merged["is_direct_published_series"] = True
        merged["definition_note"] = "Direct e-Stat table 1 current-vintage value"
        merged["source_first_present_period_code"] = source_start
        merged["comparability_start_period_code"] = merged["metric_id"].map(
            lambda metric: _comparison_start(
                metric,
                source_start,
                manifest["software_capex_comparable_start_period_code"],
            )
        )
        merged["missing_status"] = merged["missing_status"].fillna(
            "SOURCE_MISSING_OR_OMITTED"
        )
        merged["source_cell_key"] = merged["source_cell_key"].fillna(
            merged.apply(
                lambda row: "MISSING@"
                + "@".join(
                    [
                        row["period_code"],
                        capital_code,
                        industry_code,
                        metric_id,
                    ]
                ),
                axis=1,
            )
        )
        frames.append(merged)
    direct = pd.concat(frames, ignore_index=True, sort=False)
    direct["value_oku_yen"] = [
        _to_oku_yen(metric, unit, value)
        for metric, unit, value in zip(
            direct["metric_id"],
            direct["source_unit"],
            direct["source_value"],
            strict=True,
        )
    ]
    # Keep the source number and its published unit untouched in
    # ``source_value``/``source_unit``.  All analytical amount columns use one
    # canonical unit (oku yen); otherwise a ratio combining a direct e-Stat
    # profit series (published in million yen) with a derived gap series (oku
    # yen) is silently off by a factor of 100.
    direct["value"] = direct["value_oku_yen"]
    direct["analytical_unit"] = "億円"
    return direct


def _derived_panel(direct: pd.DataFrame, software_start: str) -> pd.DataFrame:
    id_columns = [
        "period_code",
        "period",
        "period_end",
        "period_ordinal",
        "industry_code",
        "industry_name",
        "capital_size_code",
        "capital_size_name",
    ]
    value_wide = direct.pivot(
        index=id_columns, columns="metric_id", values="value_oku_yen"
    ).reset_index()
    start_map = (
        direct.groupby(["industry_code", "capital_size_code", "metric_id"])[
            "source_first_present_period_code"
        ]
        .first()
        .to_dict()
    )
    source_path = direct["source_path"].dropna().iloc[0]
    source_sha = direct["source_sha256"].dropna().iloc[0]
    rows: list[pd.DataFrame] = []
    for metric_id, spec in DERIVED_METRICS.items():
        left_metric, right_metric = spec["inputs"]
        derived = value_wide[id_columns].copy()
        left = value_wide[left_metric]
        right = value_wide[right_metric]
        complete = left.notna() & right.notna()
        if metric_id in {"software_capex_derived", "net_non_operating_gap"}:
            derived["value"] = (left - right).where(complete)
            derived["value_oku_yen"] = derived["value"]
        else:
            nonzero = complete & right.ne(0)
            derived["value"] = (left / right * 100.0).where(nonzero)
            derived["value_oku_yen"] = np.nan
        derived["release_id"] = "historical_2026Q1"
        derived["coverage_scope"] = "EXCL_FINANCE_INSURANCE"
        derived["seasonal_adjustment"] = "DERIVED_FROM_RAW"
        derived["metric_id"] = metric_id
        derived["metric_label_ja"] = spec["label"]
        derived["source_metric_name"] = "derived"
        derived["source_unit"] = spec["unit"]
        derived["analytical_unit"] = spec["unit"]
        derived["source_value"] = derived["value"]
        derived["source_table_number"] = HISTORICAL_TABLE_NUMBER
        derived["estat_sid"] = HISTORICAL_SID
        derived["source_path"] = source_path
        derived["source_sha256"] = source_sha
        derived["metric_origin"] = "DERIVED_FROM_ESTAT_CURRENT_VINTAGE"
        derived["is_direct_published_series"] = False
        derived["definition_note"] = spec["definition"]
        derived["source_cell_key"] = "DERIVED"
        pre_definition = (
            metric_id == "software_capex_derived"
        ) & derived["period_code"].astype(int).lt(int(software_start))
        # Identical historical capex columns before the detected definition
        # break are not evidence of measured zero software investment.  Keep
        # those periods in the panel, but carry null values and an explicit
        # state rather than manufacturing a long run of zero observations.
        if metric_id == "software_capex_derived":
            derived.loc[
                pre_definition, ["value", "value_oku_yen", "source_value"]
            ] = np.nan
        derived["missing_status"] = np.select(
            [
                pre_definition,
                derived["value"].notna(),
            ],
            ["PRE_DEFINITION_NOT_COMPARABLE", "PRESENT"],
            default="DERIVATION_INPUT_MISSING",
        )
        starts: list[str] = []
        for industry_code, capital_code in zip(
            derived["industry_code"], derived["capital_size_code"], strict=True
        ):
            input_starts = [
                start_map[(industry_code, capital_code, input_metric)]
                for input_metric in spec["inputs"]
            ]
            source_start = str(max(map(int, input_starts)))
            starts.append(source_start)
        derived["source_first_present_period_code"] = starts
        derived["comparability_start_period_code"] = [
            _comparison_start(metric_id, start, software_start) for start in starts
        ]
        rows.append(derived)
    return pd.concat(rows, ignore_index=True, sort=False)


def _rate_status(metric_id: str, current: Any, prior: Any) -> str:
    if pd.isna(current) or pd.isna(prior):
        return "MISSING_INPUT"
    if metric_id in MARGIN_METRICS:
        return "LEVEL_DIFFERENCE_ONLY"
    if float(prior) == 0:
        return "ZERO_BASE_NOT_CALCULABLE"
    if metric_id in PROFIT_LEVEL_METRICS and float(prior) < 0:
        return "NEGATIVE_PROFIT_BASE_NOT_CALCULABLE"
    if metric_id in {"software_capex_derived", "net_non_operating_gap"} and float(prior) < 0:
        return "NEGATIVE_DERIVED_BASE_NOT_INTERPRETABLE"
    return "CALCULABLE"


def _add_time_calculations(panel: pd.DataFrame) -> pd.DataFrame:
    panel = panel.copy()
    group_keys = ["industry_code", "capital_size_code", "metric_id"]
    panel = panel.sort_values([*group_keys, "period_ordinal"], kind="stable")
    calculated: list[pd.DataFrame] = []
    for _, frame in panel.groupby(group_keys, sort=False, dropna=False):
        frame = frame.copy()
        frame["comparison_eligible"] = (
            frame["period_code"].astype(int)
            >= frame["comparability_start_period_code"].astype(int)
        )
        usable = frame["value"].where(
            frame["comparison_eligible"] & frame["missing_status"].eq("PRESENT")
        )
        frame["lag4_value"] = usable.shift(4)
        frame["yoy_delta"] = usable - frame["lag4_value"]
        frame["yoy_rate_status"] = [
            (
                "PRE_COMPARABLE_PERIOD"
                if not eligible
                else _rate_status(metric, current, prior)
            )
            for metric, current, prior, eligible in zip(
                frame["metric_id"],
                usable,
                frame["lag4_value"],
                frame["comparison_eligible"],
                strict=True,
            )
        ]
        frame["yoy_pct"] = [
            (float(current) / float(prior) - 1.0) * 100.0
            if status == "CALCULABLE"
            else np.nan
            for current, prior, status in zip(
                usable, frame["lag4_value"], frame["yoy_rate_status"], strict=True
            )
        ]
        additive = frame["metric_id"].iloc[0] in FLOW_MONEY_METRICS
        if additive:
            frame["rolling_4q_value"] = usable.rolling(4, min_periods=4).sum()
            frame["rolling_4q_lag4_value"] = frame["rolling_4q_value"].shift(4)
            frame["rolling_4q_yoy_delta"] = (
                frame["rolling_4q_value"] - frame["rolling_4q_lag4_value"]
            )
            frame["rolling_4q_yoy_rate_status"] = [
                _rate_status(metric, current, prior)
                for metric, current, prior in zip(
                    frame["metric_id"],
                    frame["rolling_4q_value"],
                    frame["rolling_4q_lag4_value"],
                    strict=True,
                )
            ]
            frame["rolling_4q_yoy_pct"] = [
                (float(current) / float(prior) - 1.0) * 100.0
                if status == "CALCULABLE"
                else np.nan
                for current, prior, status in zip(
                    frame["rolling_4q_value"],
                    frame["rolling_4q_lag4_value"],
                    frame["rolling_4q_yoy_rate_status"],
                    strict=True,
                )
            ]
        else:
            frame["rolling_4q_value"] = np.nan
            frame["rolling_4q_lag4_value"] = np.nan
            frame["rolling_4q_yoy_delta"] = np.nan
            frame["rolling_4q_yoy_pct"] = np.nan
            frame["rolling_4q_yoy_rate_status"] = "NOT_ADDITIVE"
        frame["value_oku_yen"] = frame["value_oku_yen"].where(
            frame["metric_id"].isin(FLOW_MONEY_METRICS)
        )
        frame["lag4_value_oku_yen"] = frame["lag4_value"].where(
            frame["metric_id"].isin(FLOW_MONEY_METRICS)
        )
        frame["yoy_delta_oku_yen"] = frame["yoy_delta"].where(
            frame["metric_id"].isin(FLOW_MONEY_METRICS)
        )
        frame["rolling_4q_value_oku_yen"] = frame["rolling_4q_value"].where(
            frame["metric_id"].isin(FLOW_MONEY_METRICS)
        )
        frame["rolling_4q_yoy_delta_oku_yen"] = frame[
            "rolling_4q_yoy_delta"
        ].where(frame["metric_id"].isin(FLOW_MONEY_METRICS))
        frame["profit_margin_yoy_delta_pp"] = frame["yoy_delta"].where(
            frame["metric_id"].isin(MARGIN_METRICS)
        )
        frame["profit_transition_yoy"] = [
            detect_profit_transition(prior, current)
            if metric in PROFIT_LEVEL_METRICS
            else "NOT_APPLICABLE"
            for metric, prior, current in zip(
                frame["metric_id"], frame["lag4_value"], usable, strict=True
            )
        ]
        calculated.append(frame)
    return pd.concat(calculated, ignore_index=True, sort=False)


def build_historical_quarterly(
    project_root: Path = PROJECT_ROOT,
) -> pd.DataFrame:
    """Build a current-vintage long panel with explicit comparability state."""
    project_root = Path(project_root)
    parsed, manifest, query_metadata = load_historical_snapshot(project_root)
    direct = _materialize_direct_panel(
        parsed, manifest, query_metadata, project_root
    )
    derived = _derived_panel(
        direct, manifest["software_capex_comparable_start_period_code"]
    )
    panel = _add_time_calculations(
        pd.concat([direct, derived], ignore_index=True, sort=False)
    )
    panel["historical_vintage_id"] = manifest["historical_vintage_id"]
    panel["vintage_status"] = CURRENT_VINTAGE_STATUS
    panel["revision_robustness_status"] = REVISION_STATUS
    panel["classification_status"] = "CURRENT_MODEL_CODE_NAME_MATCH"
    panel["classification_note"] = (
        "Current model codes/names only; legacy H20-labelled categories are not spliced"
    )
    panel["sample_replacement_notice"] = np.where(
        panel["period_code"].astype(str).str.endswith("2"),
        "ANNUAL_SAMPLE_REPLACEMENT_CAUTION",
        "NONE",
    )
    panel["comparability_status"] = np.select(
        [
            ~panel["comparison_eligible"],
            panel["missing_status"].ne("PRESENT"),
        ],
        ["PRE_COMPARABLE_PERIOD", "MISSING_WITHIN_COMPARABLE_PERIOD"],
        default="COMPARABLE_CURRENT_CLASSIFICATION",
    )
    panel["quality_flags"] = np.where(
        panel["sample_replacement_notice"].ne("NONE"),
        panel["sample_replacement_notice"],
        "NONE",
    )
    columns = [
        "historical_vintage_id",
        "vintage_status",
        "revision_robustness_status",
        "release_id",
        "period_code",
        "period",
        "period_end",
        "period_ordinal",
        "coverage_scope",
        "industry_code",
        "industry_name",
        "capital_size_code",
        "capital_size_name",
        "metric_id",
        "metric_label_ja",
        "metric_origin",
        "is_direct_published_series",
        "definition_note",
        "source_unit",
        "source_value",
        "analytical_unit",
        "value",
        "value_oku_yen",
        "lag4_value",
        "lag4_value_oku_yen",
        "yoy_delta",
        "yoy_delta_oku_yen",
        "yoy_pct",
        "yoy_rate_status",
        "profit_margin_yoy_delta_pp",
        "rolling_4q_value",
        "rolling_4q_value_oku_yen",
        "rolling_4q_lag4_value",
        "rolling_4q_yoy_delta",
        "rolling_4q_yoy_delta_oku_yen",
        "rolling_4q_yoy_pct",
        "rolling_4q_yoy_rate_status",
        "profit_transition_yoy",
        "source_first_present_period_code",
        "comparability_start_period_code",
        "comparison_eligible",
        "comparability_status",
        "missing_status",
        "classification_status",
        "classification_note",
        "sample_replacement_notice",
        "quality_flags",
        "source_table_number",
        "estat_sid",
        "source_path",
        "source_sha256",
        "source_cell_key",
    ]
    return panel[columns].sort_values(
        ["period_ordinal", "industry_code", "capital_size_code", "metric_id"],
        kind="stable",
    ).reset_index(drop=True)


def _series(
    historical: pd.DataFrame,
    metric_id: str,
    industry_code: str,
    capital_code: str,
    column: str,
) -> pd.Series:
    subset = historical.loc[
        historical["metric_id"].eq(metric_id)
        & historical["industry_code"].astype(str).eq(industry_code)
        & historical["capital_size_code"].astype(str).eq(capital_code),
        ["period_code", column],
    ]
    if subset.empty:
        raise HistoricalDataError(
            f"Series absent: metric={metric_id}, industry={industry_code}, capital={capital_code}"
        )
    if subset["period_code"].duplicated().any():
        raise HistoricalDataError(
            f"Duplicate historical periods: {metric_id}/{industry_code}/{capital_code}"
        )
    return subset.set_index("period_code")[column]


def _safe_profit_share(
    *,
    numerator_delta: Any,
    denominator_delta: Any,
    numerator_current: Any,
    numerator_prior: Any,
    denominator_current: Any,
    denominator_prior: Any,
) -> tuple[float | None, str]:
    values = (
        numerator_delta,
        denominator_delta,
        numerator_current,
        numerator_prior,
        denominator_current,
        denominator_prior,
    )
    if any(pd.isna(value) for value in values):
        return None, "MISSING_INPUT"
    if float(denominator_delta) == 0:
        return None, "DENOMINATOR_ZERO"
    if float(denominator_delta) < 0:
        return None, "DENOMINATOR_NOT_POSITIVE"
    if any(
        float(value) <= 0
        for value in (
            numerator_current,
            numerator_prior,
            denominator_current,
            denominator_prior,
        )
    ):
        return None, "PROFIT_SIGN_NOT_POSITIVE"
    return float(numerator_delta) / float(denominator_delta) * 100.0, "CALCULABLE"


def _safe_positive_contribution(
    numerator_delta: Any, denominator_delta: Any
) -> tuple[float | None, str]:
    if pd.isna(numerator_delta) or pd.isna(denominator_delta):
        return None, "MISSING_INPUT"
    if float(denominator_delta) == 0:
        return None, "DENOMINATOR_ZERO"
    if float(denominator_delta) < 0:
        return None, "DENOMINATOR_NOT_POSITIVE"
    return float(numerator_delta) / float(denominator_delta) * 100.0, "CALCULABLE"


def _profit_share_series(
    historical: pd.DataFrame,
    *,
    numerator_industry: str,
    numerator_capital: str,
    numerator_metric: str,
    denominator_metric: str,
    rolling: bool,
) -> tuple[pd.Series, pd.Series]:
    prefix = "rolling_4q_" if rolling else ""
    value_column = f"{prefix}value"
    prior_column = f"{prefix}lag4_value" if rolling else "lag4_value"
    delta_column = f"{prefix}yoy_delta"
    index = sorted(historical["period_code"].astype(str).unique(), key=int)
    inputs = {
        "nd": _series(
            historical,
            numerator_metric,
            numerator_industry,
            numerator_capital,
            delta_column,
        ).reindex(index),
        "dd": _series(
            historical, denominator_metric, "104", "26", delta_column
        ).reindex(index),
        "nc": _series(
            historical,
            numerator_metric,
            numerator_industry,
            numerator_capital,
            value_column,
        ).reindex(index),
        "np": _series(
            historical,
            numerator_metric,
            numerator_industry,
            numerator_capital,
            prior_column,
        ).reindex(index),
        "dc": _series(
            historical, denominator_metric, "104", "26", value_column
        ).reindex(index),
        "dp": _series(
            historical, denominator_metric, "104", "26", prior_column
        ).reindex(index),
    }
    values: list[float | None] = []
    statuses: list[str] = []
    for row in pd.DataFrame(inputs).itertuples(index=False):
        value, status = _safe_profit_share(
            numerator_delta=row.nd,
            denominator_delta=row.dd,
            numerator_current=row.nc,
            numerator_prior=row.np,
            denominator_current=row.dc,
            denominator_prior=row.dp,
        )
        values.append(value)
        statuses.append(status)
    return pd.Series(values, index=index, dtype="float64"), pd.Series(
        statuses, index=index, dtype="object"
    )


def _gap_share_series(
    historical: pd.DataFrame, *, rolling: bool
) -> tuple[pd.Series, pd.Series]:
    prefix = "rolling_4q_" if rolling else ""
    delta_column = f"{prefix}yoy_delta"
    value_column = f"{prefix}value"
    prior_column = f"{prefix}lag4_value" if rolling else "lag4_value"
    index = sorted(historical["period_code"].astype(str).unique(), key=int)
    gap_delta = _series(
        historical, "net_non_operating_gap", "104", "26", delta_column
    ).reindex(index)
    ordinary_delta = _series(
        historical, "ordinary_profit", "104", "26", delta_column
    ).reindex(index)
    ordinary_current = _series(
        historical, "ordinary_profit", "104", "26", value_column
    ).reindex(index)
    ordinary_prior = _series(
        historical, "ordinary_profit", "104", "26", prior_column
    ).reindex(index)
    values: list[float | None] = []
    statuses: list[str] = []
    for gd, od, current, prior in zip(
        gap_delta, ordinary_delta, ordinary_current, ordinary_prior, strict=True
    ):
        if any(pd.isna(value) for value in (gd, od, current, prior)):
            values.append(None)
            statuses.append("MISSING_INPUT")
        elif float(od) == 0:
            values.append(None)
            statuses.append("DENOMINATOR_ZERO")
        elif float(od) < 0:
            values.append(None)
            statuses.append("DENOMINATOR_NOT_POSITIVE")
        elif float(current) <= 0 or float(prior) <= 0:
            values.append(None)
            statuses.append("PROFIT_SIGN_NOT_POSITIVE")
        else:
            values.append(float(gd) / float(od) * 100.0)
            statuses.append("CALCULABLE")
    return pd.Series(values, index=index, dtype="float64"), pd.Series(
        statuses, index=index, dtype="object"
    )


def _rolling_margin_delta(
    historical: pd.DataFrame, capital_code: str
) -> pd.Series:
    sales = _series(
        historical, "sales", "104", capital_code, "rolling_4q_value"
    )
    sales_prior = _series(
        historical, "sales", "104", capital_code, "rolling_4q_lag4_value"
    )
    profit = _series(
        historical, "operating_profit", "104", capital_code, "rolling_4q_value"
    )
    profit_prior = _series(
        historical,
        "operating_profit",
        "104",
        capital_code,
        "rolling_4q_lag4_value",
    )
    index = sorted(set(sales.index) | set(profit.index), key=int)
    current_margin = profit.reindex(index) / sales.reindex(index) * 100.0
    prior_margin = profit_prior.reindex(index) / sales_prior.reindex(index) * 100.0
    return current_margin - prior_margin


def _composite_min(*values: Any) -> tuple[float | None, str]:
    if any(pd.isna(value) for value in values):
        return None, "MISSING_INPUT"
    return min(float(value) for value in values), "CALCULABLE"


def build_candidate_series(
    historical: pd.DataFrame,
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Build the five explicitly registered candidate indicator histories."""
    config = config or load_stage2_config()
    candidate_rules = config["candidate_rules"]
    periods = (
        historical[["period_code", "period", "period_end", "period_ordinal"]]
        .drop_duplicates()
        .sort_values("period_ordinal", kind="stable")
    )
    index = periods["period_code"].astype(str).tolist()
    meta = periods.set_index("period_code")

    a_value, a_status = _profit_share_series(
        historical,
        numerator_industry="108",
        numerator_capital="25",
        numerator_metric="ordinary_profit",
        denominator_metric="ordinary_profit",
        rolling=False,
    )
    a_roll, a_roll_status = _profit_share_series(
        historical,
        numerator_industry="108",
        numerator_capital="25",
        numerator_metric="ordinary_profit",
        denominator_metric="ordinary_profit",
        rolling=True,
    )

    e_value, e_status = _profit_share_series(
        historical,
        numerator_industry="145",
        numerator_capital="26",
        numerator_metric="ordinary_profit",
        denominator_metric="ordinary_profit",
        rolling=False,
    )
    e_roll, e_roll_status = _profit_share_series(
        historical,
        numerator_industry="145",
        numerator_capital="26",
        numerator_metric="ordinary_profit",
        denominator_metric="ordinary_profit",
        rolling=True,
    )
    d_value, d_status = _gap_share_series(historical, rolling=False)
    d_roll, d_roll_status = _gap_share_series(historical, rolling=True)

    small_sales_yoy = _series(historical, "sales", "104", "19", "yoy_pct").reindex(index)
    small_margin_delta = _series(
        historical, "operating_margin_pct", "104", "19", "yoy_delta"
    ).reindex(index)
    large_margin_delta = _series(
        historical, "operating_margin_pct", "104", "25", "yoy_delta"
    ).reindex(index)
    small_sales_roll_yoy = _series(
        historical, "sales", "104", "19", "rolling_4q_yoy_pct"
    ).reindex(index)
    small_margin_roll_delta = _rolling_margin_delta(historical, "19").reindex(index)
    large_margin_roll_delta = _rolling_margin_delta(historical, "25").reindex(index)

    b_values: list[float | None] = []
    b_statuses: list[str] = []
    b_roll_values: list[float | None] = []
    b_roll_statuses: list[str] = []
    for values in zip(
        small_sales_yoy,
        small_margin_delta,
        large_margin_delta,
        small_sales_roll_yoy,
        small_margin_roll_delta,
        large_margin_roll_delta,
        strict=True,
    ):
        value, status = _composite_min(values[0], -values[1], values[2])
        rolling_value, rolling_status = _composite_min(
            values[3], -values[4], values[5]
        )
        b_values.append(value)
        b_statuses.append(status)
        b_roll_values.append(rolling_value)
        b_roll_statuses.append(rolling_status)

    capex_including_yoy = _series(
        historical, "capex_including_software", "104", "26", "yoy_pct"
    ).reindex(index)
    capex_including_roll_yoy = _series(
        historical,
        "capex_including_software",
        "104",
        "26",
        "rolling_4q_yoy_pct",
    ).reindex(index)
    software_delta = _series(
        historical, "software_capex_derived", "104", "26", "yoy_delta"
    ).reindex(index)
    software_roll_delta = _series(
        historical,
        "software_capex_derived",
        "104",
        "26",
        "rolling_4q_yoy_delta",
    ).reindex(index)
    excluding_delta = _series(
        historical, "capex_excluding_software", "104", "26", "yoy_delta"
    ).reindex(index)
    excluding_roll_delta = _series(
        historical,
        "capex_excluding_software",
        "104",
        "26",
        "rolling_4q_yoy_delta",
    ).reindex(index)
    small_software_delta = _series(
        historical, "software_capex_derived", "104", "19", "yoy_delta"
    ).reindex(index)
    small_software_roll_delta = _series(
        historical,
        "software_capex_derived",
        "104",
        "19",
        "rolling_4q_yoy_delta",
    ).reindex(index)
    flat_threshold = float(
        candidate_rules["C"]["flat_including_capex_abs_yoy_pct_max"]
    )
    c_values: list[float | None] = []
    c_statuses: list[str] = []
    c_roll_values: list[float | None] = []
    c_roll_statuses: list[str] = []
    small_contribution: list[float | None] = []
    small_contribution_status: list[str] = []
    for values in zip(
        capex_including_yoy,
        software_delta,
        excluding_delta,
        capex_including_roll_yoy,
        software_roll_delta,
        excluding_roll_delta,
        small_software_delta,
        small_software_roll_delta,
        strict=True,
    ):
        if any(pd.isna(value) for value in values[:3]):
            c_values.append(None)
            c_statuses.append("MISSING_INPUT")
        else:
            c_values.append(
                min(
                    flat_threshold - abs(float(values[0])),
                    1.0 if float(values[1]) > 0 else (0.0 if float(values[1]) == 0 else -1.0),
                    1.0 if float(values[2]) < 0 else (0.0 if float(values[2]) == 0 else -1.0),
                )
            )
            c_statuses.append("CALCULABLE")
        if any(pd.isna(value) for value in values[3:6]):
            c_roll_values.append(None)
            c_roll_statuses.append("MISSING_INPUT")
        else:
            c_roll_values.append(
                min(
                    flat_threshold - abs(float(values[3])),
                    1.0 if float(values[4]) > 0 else (0.0 if float(values[4]) == 0 else -1.0),
                    1.0 if float(values[5]) < 0 else (0.0 if float(values[5]) == 0 else -1.0),
                )
            )
            c_roll_statuses.append("CALCULABLE")
        contribution, contribution_status = _safe_positive_contribution(
            values[6], values[1]
        )
        small_contribution.append(contribution)
        small_contribution_status.append(contribution_status)

    # Preserve the exact components behind each composite/share.  These are
    # intentionally carried next to the indicator so a downstream claim can be
    # audited without reverse engineering the formula or joining the long
    # panel again.
    component_columns = (
        "numerator_yoy_delta_oku_yen",
        "denominator_yoy_delta_oku_yen",
        "rolling_4q_numerator_yoy_delta_oku_yen",
        "rolling_4q_denominator_yoy_delta_oku_yen",
        "small_sales_yoy_pct",
        "small_operating_margin_yoy_delta_pp",
        "large_operating_margin_yoy_delta_pp",
        "rolling_4q_small_sales_yoy_pct",
        "rolling_4q_small_operating_margin_yoy_delta_pp",
        "rolling_4q_large_operating_margin_yoy_delta_pp",
        "capex_including_yoy_pct",
        "software_capex_yoy_delta_oku_yen",
        "capex_excluding_yoy_delta_oku_yen",
        "rolling_4q_capex_including_yoy_pct",
        "rolling_4q_software_capex_yoy_delta_oku_yen",
        "rolling_4q_capex_excluding_yoy_delta_oku_yen",
    )
    all_ordinary_delta = _series(
        historical, "ordinary_profit", "104", "26", "yoy_delta_oku_yen"
    ).reindex(index)
    all_ordinary_rolling_delta = _series(
        historical,
        "ordinary_profit",
        "104",
        "26",
        "rolling_4q_yoy_delta_oku_yen",
    ).reindex(index)
    component_series: dict[str, dict[str, pd.Series]] = {
        "A": {
            "numerator_yoy_delta_oku_yen": _series(
                historical, "ordinary_profit", "108", "25", "yoy_delta_oku_yen"
            ).reindex(index),
            "denominator_yoy_delta_oku_yen": all_ordinary_delta,
            "rolling_4q_numerator_yoy_delta_oku_yen": _series(
                historical,
                "ordinary_profit",
                "108",
                "25",
                "rolling_4q_yoy_delta_oku_yen",
            ).reindex(index),
            "rolling_4q_denominator_yoy_delta_oku_yen": all_ordinary_rolling_delta,
        },
        "B": {
            "small_sales_yoy_pct": small_sales_yoy,
            "small_operating_margin_yoy_delta_pp": small_margin_delta,
            "large_operating_margin_yoy_delta_pp": large_margin_delta,
            "rolling_4q_small_sales_yoy_pct": small_sales_roll_yoy,
            "rolling_4q_small_operating_margin_yoy_delta_pp": small_margin_roll_delta,
            "rolling_4q_large_operating_margin_yoy_delta_pp": large_margin_roll_delta,
        },
        "C": {
            "capex_including_yoy_pct": capex_including_yoy,
            "software_capex_yoy_delta_oku_yen": software_delta,
            "capex_excluding_yoy_delta_oku_yen": excluding_delta,
            "rolling_4q_capex_including_yoy_pct": capex_including_roll_yoy,
            "rolling_4q_software_capex_yoy_delta_oku_yen": software_roll_delta,
            "rolling_4q_capex_excluding_yoy_delta_oku_yen": excluding_roll_delta,
        },
        "D": {
            "numerator_yoy_delta_oku_yen": _series(
                historical,
                "net_non_operating_gap",
                "104",
                "26",
                "yoy_delta_oku_yen",
            ).reindex(index),
            "denominator_yoy_delta_oku_yen": all_ordinary_delta,
            "rolling_4q_numerator_yoy_delta_oku_yen": _series(
                historical,
                "net_non_operating_gap",
                "104",
                "26",
                "rolling_4q_yoy_delta_oku_yen",
            ).reindex(index),
            "rolling_4q_denominator_yoy_delta_oku_yen": all_ordinary_rolling_delta,
        },
        "E": {
            "numerator_yoy_delta_oku_yen": _series(
                historical, "ordinary_profit", "145", "26", "yoy_delta_oku_yen"
            ).reindex(index),
            "denominator_yoy_delta_oku_yen": all_ordinary_delta,
            "rolling_4q_numerator_yoy_delta_oku_yen": _series(
                historical,
                "ordinary_profit",
                "145",
                "26",
                "rolling_4q_yoy_delta_oku_yen",
            ).reindex(index),
            "rolling_4q_denominator_yoy_delta_oku_yen": all_ordinary_rolling_delta,
        },
    }

    definitions = {
        "A": (
            a_value,
            a_status,
            a_roll,
            a_roll_status,
            "large-cap manufacturing ordinary-profit yoy delta / all-industry ordinary-profit yoy delta",
            "%",
        ),
        "B": (
            pd.Series(b_values, index=index, dtype="float64"),
            pd.Series(b_statuses, index=index),
            pd.Series(b_roll_values, index=index, dtype="float64"),
            pd.Series(b_roll_statuses, index=index),
            "min(small sales yoy, -small operating-margin yoy delta, large operating-margin yoy delta)",
            "composite_percentage_point_score",
        ),
        "C": (
            pd.Series(c_values, index=index, dtype="float64"),
            pd.Series(c_statuses, index=index),
            pd.Series(c_roll_values, index=index, dtype="float64"),
            pd.Series(c_roll_statuses, index=index),
            "min(flat-capex threshold headroom, software-delta sign score, excluding-capex reverse sign score)",
            "pre_registered_composite_score",
        ),
        "D": (
            d_value,
            d_status,
            d_roll,
            d_roll_status,
            "net_non_operating_gap yoy delta / ordinary-profit yoy delta",
            "%",
        ),
        "E": (
            e_value,
            e_status,
            e_roll,
            e_roll_status,
            "ICT-machinery ordinary-profit yoy delta / all-industry ordinary-profit yoy delta",
            "%",
        ),
    }
    records: list[pd.DataFrame] = []
    for candidate_id, definition in definitions.items():
        value, status, rolling_value, rolling_status, formula, unit = definition
        threshold = float(candidate_rules[candidate_id].get("positive_threshold", 0.0))
        candidate = pd.DataFrame(
            {
                "candidate_id": candidate_id,
                "candidate_label_ja": candidate_rules[candidate_id]["label_ja"],
                "indicator_id": candidate_rules[candidate_id]["indicator"],
                "period_code": index,
                "indicator_value": value.reindex(index).to_numpy(),
                "indicator_unit": unit,
                "positive_threshold": threshold,
                "indicator_status": status.reindex(index).to_numpy(),
                "rolling_4q_indicator_value": rolling_value.reindex(index).to_numpy(),
                "rolling_4q_indicator_status": rolling_status.reindex(index).to_numpy(),
                "indicator_definition": formula,
            }
        )
        candidate["pattern_signal_value"] = (
            candidate["indicator_value"] - candidate["positive_threshold"]
        )
        candidate["rolling_4q_pattern_signal_value"] = (
            candidate["rolling_4q_indicator_value"]
            - candidate["positive_threshold"]
        )
        candidate["same_direction"] = (
            candidate["indicator_status"].eq("CALCULABLE")
            & candidate["pattern_signal_value"].gt(0)
        )
        candidate["rolling_4q_same_direction"] = (
            candidate["rolling_4q_indicator_status"].eq("CALCULABLE")
            & candidate["rolling_4q_pattern_signal_value"].gt(0)
        )
        for column in component_columns:
            component = component_series[candidate_id].get(column)
            candidate[column] = (
                component.reindex(index).to_numpy() if component is not None else np.nan
            )
        candidate = candidate.join(meta[["period", "period_end", "period_ordinal"]], on="period_code")
        candidate["vintage_status"] = CURRENT_VINTAGE_STATUS
        candidate["revision_robustness_status"] = REVISION_STATUS
        if candidate_id == "C":
            candidate["small_capital_software_contribution_pct"] = small_contribution
            candidate["small_capital_software_contribution_status"] = (
                small_contribution_status
            )
        else:
            candidate["small_capital_software_contribution_pct"] = np.nan
            candidate["small_capital_software_contribution_status"] = "NOT_APPLICABLE"
        records.append(candidate)
    return pd.concat(records, ignore_index=True, sort=False).sort_values(
        ["candidate_id", "period_ordinal"], kind="stable"
    ).reset_index(drop=True)


def historical_position(values: pd.Series, current: float) -> dict[str, float | int | None]:
    """Return inclusive empirical percentile and robust location/outlier statistics."""
    clean = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if clean.empty or pd.isna(current):
        return {
            "history_n": len(clean),
            "historical_percentile": None,
            "historical_median": None,
            "historical_q1": None,
            "historical_q3": None,
            "historical_iqr": None,
            "historical_mad": None,
            "iqr_outlier_score": None,
            "mad_robust_z": None,
        }
    median = float(clean.median())
    q1 = float(clean.quantile(0.25))
    q3 = float(clean.quantile(0.75))
    iqr = q3 - q1
    mad = float((clean - median).abs().median())
    percentile = float(clean.le(float(current)).mean() * 100.0)
    return {
        "history_n": len(clean),
        "historical_percentile": percentile,
        "historical_median": median,
        "historical_q1": q1,
        "historical_q3": q3,
        "historical_iqr": iqr,
        "historical_mad": mad,
        "iqr_outlier_score": (
            (float(current) - median) / iqr if iqr > 0 else None
        ),
        "mad_robust_z": (
            0.6744897501960817 * (float(current) - median) / mad
            if mad > 0
            else None
        ),
    }


def classify_pre_registered_pattern(
    *,
    same_direction: Iterable[bool],
    rolling_4q_same_direction: bool,
    historical_percentile: float | None,
    rules: dict[str, Any],
) -> PatternEvidence:
    """Apply the frozen pattern rule without inspecting candidate identity."""
    values = [bool(value) for value in same_direction]
    last4 = values[-4:]
    last8 = values[-8:]
    count4 = sum(last4)
    count8 = sum(last8)
    run_length = 0
    for value in reversed(values):
        if not value:
            break
        run_length += 1
    persistent_min = int(rules["persistent_min_same_direction_last4"])
    recent_count = int(rules["recent_same_direction_last4"])
    outlier_threshold = float(rules["outlier_percentile_threshold"])
    if count4 >= persistent_min and rolling_4q_same_direction:
        decision = "PERSISTENT_PATTERN"
    elif count4 == recent_count or rolling_4q_same_direction:
        decision = "RECENT_BUT_NOT_ESTABLISHED"
    elif (
        count4 == 1
        and bool(last4[-1])
        and historical_percentile is not None
        and historical_percentile > outlier_threshold
    ):
        decision = "ONE_QUARTER_OUTLIER"
    else:
        decision = "UNSTABLE_OR_NO_PATTERN"
    return PatternEvidence(
        decision=decision,
        same_direction_last4=count4,
        same_direction_last8=count8,
        valid_last4=len(last4),
        valid_last8=len(last8),
        same_direction_run_length=run_length,
        rolling_4q_same_direction=bool(rolling_4q_same_direction),
        historical_percentile=historical_percentile,
    )


def build_historical_robustness(
    candidate_series: pd.DataFrame,
    config: dict[str, Any] | None = None,
    *,
    target_period_code: str = TARGET_PERIOD_CODE,
) -> pd.DataFrame:
    """Summarise history and assign one frozen decision to every candidate."""
    config = config or load_stage2_config()
    rules = config["pattern_rule"]
    rows: list[dict[str, Any]] = []
    for candidate_id, frame in candidate_series.groupby("candidate_id", sort=True):
        frame = frame.loc[
            frame["period_code"].astype(int).le(int(target_period_code))
        ].sort_values("period_ordinal", kind="stable")
        target = frame.loc[frame["period_code"].eq(target_period_code)]
        if len(target) != 1:
            raise HistoricalDataError(
                f"Expected one target row for candidate {candidate_id}; found {len(target)}"
            )
        target_row = target.iloc[0]
        current_signal = target_row["pattern_signal_value"]
        position = historical_position(frame["pattern_signal_value"], current_signal)
        evidence = classify_pre_registered_pattern(
            same_direction=frame["same_direction"].tolist(),
            rolling_4q_same_direction=bool(target_row["rolling_4q_same_direction"]),
            historical_percentile=position["historical_percentile"],
            rules=rules,
        )
        valid = frame["indicator_status"].eq("CALCULABLE")
        last4_valid = int(valid.tail(4).sum())
        last8_valid = int(valid.tail(8).sum())
        rows.append(
            {
                "candidate_id": candidate_id,
                "candidate_label_ja": target_row["candidate_label_ja"],
                "indicator_id": target_row["indicator_id"],
                "target_period_code": target_period_code,
                "current_indicator_value": target_row["indicator_value"],
                "indicator_unit": target_row["indicator_unit"],
                "positive_threshold": target_row["positive_threshold"],
                "current_pattern_signal_value": current_signal,
                "current_indicator_status": target_row["indicator_status"],
                "current_same_direction": bool(target_row["same_direction"]),
                "rolling_4q_indicator_value": target_row[
                    "rolling_4q_indicator_value"
                ],
                "rolling_4q_indicator_status": target_row[
                    "rolling_4q_indicator_status"
                ],
                "rolling_4q_same_direction": evidence.rolling_4q_same_direction,
                "same_direction_last4": evidence.same_direction_last4,
                "same_direction_last8": evidence.same_direction_last8,
                "valid_observations_last4": last4_valid,
                "valid_observations_last8": last8_valid,
                "same_direction_run_length": evidence.same_direction_run_length,
                **position,
                "pattern_decision": evidence.decision,
                "criteria_frozen_before_analysis": bool(
                    rules["criteria_frozen_before_analysis"]
                ),
                "pattern_rule": json.dumps(rules, ensure_ascii=False, sort_keys=True),
                "vintage_status": CURRENT_VINTAGE_STATUS,
                "revision_robustness_status": REVISION_STATUS,
                "small_capital_software_contribution_pct": target_row[
                    "small_capital_software_contribution_pct"
                ],
                "small_capital_software_contribution_status": target_row[
                    "small_capital_software_contribution_status"
                ],
            }
        )
    return pd.DataFrame(rows).sort_values("candidate_id", kind="stable").reset_index(
        drop=True
    )


def build_pattern_decisions(
    candidate_series: pd.DataFrame,
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Return the compact candidate decision contract used by later phases."""
    robustness = build_historical_robustness(candidate_series, config)
    columns = [
        "candidate_id",
        "candidate_label_ja",
        "indicator_id",
        "target_period_code",
        "current_indicator_value",
        "indicator_unit",
        "positive_threshold",
        "current_same_direction",
        "same_direction_last4",
        "same_direction_last8",
        "same_direction_run_length",
        "rolling_4q_same_direction",
        "historical_percentile",
        "mad_robust_z",
        "pattern_decision",
        "criteria_frozen_before_analysis",
        "vintage_status",
        "revision_robustness_status",
    ]
    return robustness[columns].copy()
