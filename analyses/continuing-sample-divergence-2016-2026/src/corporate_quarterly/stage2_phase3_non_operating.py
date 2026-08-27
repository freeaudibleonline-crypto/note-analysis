"""Phase 3 decomposition of the operating-to-ordinary-profit gap.

The Ministry of Finance Table 1 identity is reproduced from six e-Stat cells::

    ordinary profit - operating profit
      = interest and dividend income
      + other non-operating income
      - interest expense
      - other non-operating expense

The four middle items are the analytical components; operating and ordinary
profit are fetched with them as independent identity anchors.  All calculations
are accounting decompositions.  In particular, this module does not infer the
cause of ``other_non_operating_income`` and never replaces missing source cells
with zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Literal, Mapping, Sequence

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

from .constants import PROJECT_ROOT
from .estat import (
    ESTAT_ROOT,
    USER_AGENT,
    EStatError,
    _compressed_value,
    _find_dimension,
    _post_json,
    _selector,
    get_model,
    sha256_file,
    write_new_bytes,
)
from .stage2_phase1 import (
    ALL_CAPITAL_CODE,
    ALL_INDUSTRY_CODE,
    CAPITAL_CODES,
    load_stage2_config,
    taxonomy_definition,
)


PHASE3_VINTAGE_ID = "non_operating_2026Q1"
PHASE3_RAW_ROOT = PROJECT_ROOT / "data" / "raw" / PHASE3_VINTAGE_ID
TABLE1_SID = "0003060191"
TABLE_NUMBER = "1"
TARGET_PERIOD_CODE = "20261"
COMPARABLE_START_PERIOD_CODE = "20092"
AMOUNT_TOLERANCE_OKU_YEN = 0.01
HISTORY_CHUNK_QUARTERS = 16

# Codes and names are frozen to the e-Stat Table 1 model.  Income has a +1
# accounting sign and expense a -1 sign in the operating-to-ordinary gap.
METRIC_DEFINITIONS: tuple[tuple[str, str, str, int | None], ...] = (
    ("081", "operating_profit", "営業利益", None),
    ("082", "interest_and_dividend_income", "受取利息等", 1),
    ("083", "other_non_operating_income", "その他の営業外収益", 1),
    ("084", "interest_expense", "支払利息等", -1),
    ("085", "other_non_operating_expense", "その他の営業外費用", -1),
    ("086", "ordinary_profit", "経常利益", None),
)
METRIC_LABEL_BY_ID = {metric_id: label for _, metric_id, label, _ in METRIC_DEFINITIONS}
COMPONENT_SIGNS = {
    metric_id: int(sign)
    for _, metric_id, _, sign in METRIC_DEFINITIONS
    if sign is not None
}
COMPONENT_IDS = tuple(COMPONENT_SIGNS)
REQUIRED_METRIC_IDS = tuple(metric_id for _, metric_id, _, _ in METRIC_DEFINITIONS)

_MISSING_MARKERS = {"", "-", "―", "…", "X", "x", "NA", "N/A", "＊"}


class Phase3InputError(ValueError):
    """The Phase 3 input or immutable raw vintage violates its contract."""


@dataclass(frozen=True)
class Phase3NonOperatingAnalysis:
    """All pure analytical tables produced from one frozen raw vintage."""

    raw_long: pd.DataFrame
    earliest_complete_period: pd.DataFrame
    decomposition: pd.DataFrame
    current_breakdown: pd.DataFrame
    historical_statistics: pd.DataFrame
    concentration: pd.DataFrame
    identity_checks: pd.DataFrame
    additivity_checks: pd.DataFrame


def _quarter_ordinal(period_code: str) -> int:
    code = str(period_code)
    if not re.fullmatch(r"\d{5}", code) or code[-1] not in "1234":
        raise Phase3InputError(f"Invalid quarterly period code: {period_code!r}")
    return int(code[:4]) * 4 + int(code[-1]) - 1


def _period_end(period_code: str) -> str:
    code = str(period_code)
    year, quarter = int(code[:4]), code[-1]
    suffix = {"1": "03-31", "2": "06-30", "3": "09-30", "4": "12-31"}[quarter]
    return f"{year:04d}-{suffix}"


def _strict_sum(values: Iterable[object]) -> float | None:
    numbers: list[float] = []
    for value in values:
        if value is None or pd.isna(value):
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        numbers.append(number)
    return float(sum(numbers)) if numbers else None


def _difference(left: object, right: object) -> float | None:
    if left is None or right is None or pd.isna(left) or pd.isna(right):
        return None
    return float(left) - float(right)


def _number_or_none(text: str) -> tuple[float | None, str]:
    normalized = (
        text.strip()
        .replace("　", "")
        .replace(",", "")
        .replace("−", "-")
        .replace("△", "-")
        .replace("▲", "-")
    )
    normalized = re.sub(r"[※*†]+$", "", normalized).strip()
    if normalized in _MISSING_MARKERS:
        return None, "SOURCE_MISSING_MARKER"
    try:
        value = float(normalized)
    except ValueError:
        return None, f"UNPARSEABLE_SOURCE_VALUE:{text.strip()}"
    return value, "PRESENT"


def _selected_industry_codes(config: Mapping[str, Any] | None = None) -> list[str]:
    """All aggregate and mutually exclusive industry codes, without duplicates."""
    cfg = dict(config or load_stage2_config())
    ordered = [ALL_INDUSTRY_CODE]
    ordered.extend(taxonomy_definition("major", config=cfg)["industry_code"].astype(str))
    ordered.extend(taxonomy_definition("leaf", config=cfg)["industry_code"].astype(str))
    return list(dict.fromkeys(ordered))


def _model_entries(
    model: Mapping[str, Any], kind: str, codes: Sequence[str]
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    key, matter = _find_dimension(dict(model), kind)
    by_code = {str(entry["code"]): entry for entry in matter["listData"].values()}
    missing = [str(code) for code in codes if str(code) not in by_code]
    if missing:
        raise Phase3InputError(f"Table 1 model lacks {kind} codes: {missing}")
    return key, matter, [by_code[str(code)] for code in codes]


def _available_period_codes(
    model: Mapping[str, Any],
    *,
    start_period_code: str = COMPARABLE_START_PERIOD_CODE,
    end_period_code: str = TARGET_PERIOD_CODE,
) -> list[str]:
    _, _, entries = _model_entries(
        model,
        "time",
        [
            str(entry["code"])
            for entry in _find_dimension(dict(model), "time")[1]["listData"].values()
            if _quarter_ordinal(str(entry["code"])) >= _quarter_ordinal(start_period_code)
            and _quarter_ordinal(str(entry["code"])) <= _quarter_ordinal(end_period_code)
        ],
    )
    return [str(entry["code"]) for entry in sorted(entries, key=lambda x: _quarter_ordinal(str(x["code"])))]


def _query_payload(
    model: dict[str, Any],
    period_codes: Sequence[str],
    *,
    config: Mapping[str, Any] | None = None,
) -> tuple[dict[str, str | int | None], dict[str, Any]]:
    metric_codes = [code for code, _, _, _ in METRIC_DEFINITIONS]
    industry_codes = _selected_industry_codes(config)
    capital_codes = [ALL_CAPITAL_CODE, *CAPITAL_CODES]
    metric_key, metric_matter, metrics = _model_entries(model, "metric", metric_codes)
    industry_key, industry_matter, industries = _model_entries(
        model, "industry", industry_codes
    )
    capital_key, capital_matter, capitals = _model_entries(model, "capital", capital_codes)
    time_key, time_matter, periods = _model_entries(model, "time", list(period_codes))

    expected_names = {
        "081": "営業利益(当期末)",
        "082": "受取利息等(当期末)",
        "083": "その他の営業外収益(当期末)",
        "084": "支払利息等(当期末)",
        "085": "その他の営業外費用(当期末)",
        "086": "経常利益(当期末)",
    }
    drift = {
        str(entry["code"]): entry["name"]
        for entry in metrics
        if entry["name"] != expected_names[str(entry["code"])]
        or entry.get("unitName") != "百万円"
    }
    if drift:
        raise Phase3InputError(f"Table 1 metric label/unit drift: {drift}")

    query: dict[str, Any] = {
        "rows": [
            _selector(industry_matter, industries, 1),
            _selector(capital_matter, capitals, 2),
            _selector(time_matter, periods, 3),
        ],
        "cols": [_selector(metric_matter, metrics, 1)],
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
        else:
            posted[key] = value

    metadata = {
        "query": query,
        "dimension_keys": {
            "metric": metric_key,
            "industry": industry_key,
            "capital": capital_key,
            "time": time_key,
        },
        "dimension_spec": {
            "metric": metrics,
            "industry": industries,
            "capital": capitals,
            "time": periods,
        },
        "metric_map": {
            code: {
                "metric_id": metric_id,
                "metric_label_ja": label,
                "source_name": expected_names[code],
                "source_unit": "百万円",
                "gap_sign": sign,
            }
            for code, metric_id, label, sign in METRIC_DEFINITIONS
        },
        "coverage_scope": "EXCL_FINANCE_INSURANCE",
        "seasonal_adjustment": "RAW",
        "table_number": TABLE_NUMBER,
        "estat_sid": TABLE1_SID,
        "period_codes": list(period_codes),
        "classification_policy": {
            "major_and_leaf_are_separate_taxonomies": True,
            "overlapping_or_h20_legacy_rows_excluded": True,
        },
    }
    return posted, metadata


def _retrieval_time(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()


def _manifest_source(
    *,
    source_id: str,
    role: str,
    path: Path,
    period_codes: Sequence[str],
    retrieved_at: str,
    query_source_id: str | None = None,
) -> dict[str, Any]:
    try:
        stored_path: Path | str = path.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        stored_path = path.resolve()
    return {
        "source_id": source_id,
        "role": role,
        "provider": "e-Stat",
        "release_id": "2026Q1",
        "vintage_id": PHASE3_VINTAGE_ID,
        "publication_date": "2026-06-01",
        "table_number": TABLE_NUMBER,
        "table_title": "金融業、保険業以外の業種（原数値）",
        "estat_sid": TABLE1_SID,
        "url": f"{ESTAT_ROOT}/dbview/api_get_result?sid={TABLE1_SID}"
        if "model" not in role
        else f"{ESTAT_ROOT}/dbview/api_get_model?sid={TABLE1_SID}",
        "view_url": f"{ESTAT_ROOT}/dbview?sid={TABLE1_SID}",
        "http_method": "POST",
        "source_method": "ESTAT_DB_VIEW_PUBLIC_UI",
        "retrieved_at": retrieved_at,
        "period_codes": list(period_codes),
        "coverage_scope": "EXCL_FINANCE_INSURANCE",
        "seasonal_adjustment": "RAW",
        "raw_path": str(stored_path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "content_type": "application/json",
        "query_source_id": query_source_id,
    }


def _verify_existing_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for source in manifest.get("sources", []):
        path = Path(source["raw_path"])
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.exists() or sha256_file(path) != source["sha256"]:
            raise EStatError(
                "Existing immutable Phase 3 manifest does not match its raw file: "
                f"{path}"
            )
    return manifest


def fetch_phase3_non_operating_raw(
    *,
    raw_root: Path = PHASE3_RAW_ROOT,
    history_chunk_quarters: int = HISTORY_CHUNK_QUARTERS,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch and immutably freeze Table 1 components and identity anchors.

    A dedicated current snapshot is frozen in addition to chunked history.  The
    duplicate target-period observations are compared during parsing.  If the
    manifest already exists, this function performs hash verification only and
    makes no network request.
    """
    raw_root = Path(raw_root)
    manifest_path = raw_root / "data_manifest.json"
    if manifest_path.exists():
        return _verify_existing_manifest(manifest_path)
    if history_chunk_quarters < 1:
        raise ValueError("history_chunk_quarters must be positive")

    raw_root.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    model_path = raw_root / "table1_non_operating_model.json"
    if model_path.exists():
        model_bytes = model_path.read_bytes()
        model = json.loads(model_bytes)
    else:
        model_bytes, model = get_model(session, TABLE1_SID)
        write_new_bytes(model_path, model_bytes)
    sources = [
        _manifest_source(
            source_id="phase3_table1_model",
            role="numeric_authority_model",
            path=model_path,
            period_codes=[],
            retrieved_at=_retrieval_time(model_path),
        )
    ]

    periods = _available_period_codes(model)
    if not periods or periods[0] != COMPARABLE_START_PERIOD_CODE or periods[-1] != TARGET_PERIOD_CODE:
        raise Phase3InputError(
            f"Unexpected Phase 3 period coverage: first={periods[:1]}, last={periods[-1:]}"
        )
    query_sets: list[tuple[str, list[str], str]] = [
        ("current", [TARGET_PERIOD_CODE], "numeric_authority_current")
    ]
    for start in range(0, len(periods), history_chunk_quarters):
        chunk = periods[start : start + history_chunk_quarters]
        query_sets.append(
            (
                f"history_{len(query_sets):02d}_{chunk[0]}_{chunk[-1]}",
                chunk,
                "numeric_authority_history_chunk",
            )
        )

    for source_stem, period_codes, values_role in query_sets:
        posted, metadata = _query_payload(model, period_codes, config=config)
        query_path = raw_root / f"{source_stem}_query.json"
        query_bytes = json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8")
        write_new_bytes(query_path, query_bytes)
        query_source_id = f"phase3_{source_stem}_query"
        sources.append(
            _manifest_source(
                source_id=query_source_id,
                role="request_metadata",
                path=query_path,
                period_codes=period_codes,
                retrieved_at=_retrieval_time(query_path),
            )
        )

        values_path = raw_root / f"{source_stem}_values.json"
        if not values_path.exists():
            raw, _ = _post_json(
                session,
                f"{ESTAT_ROOT}/dbview/api_get_result?sid={TABLE1_SID}",
                posted,
            )
            write_new_bytes(values_path, raw)
        sources.append(
            _manifest_source(
                source_id=f"phase3_{source_stem}_values",
                role=values_role,
                path=values_path,
                period_codes=period_codes,
                retrieved_at=_retrieval_time(values_path),
                query_source_id=query_source_id,
            )
        )

    manifest = {
        "manifest_version": 1,
        "release_id": "2026Q1",
        "vintage_id": PHASE3_VINTAGE_ID,
        "generated_at": datetime.now(UTC).isoformat(),
        "publication_date": "2026-06-01",
        "table_number": TABLE_NUMBER,
        "estat_sid": TABLE1_SID,
        "requested_period_start": COMPARABLE_START_PERIOD_CODE,
        "requested_period_end": TARGET_PERIOD_CODE,
        "mechanical_earliest_policy": (
            "Earliest period at or after 2009Q2 with every selected six-metric "
            "industry x capital source cell present; computed from frozen values."
        ),
        "source_policy": {
            "numeric_authority": "e-Stat structured Table 1 response",
            "raw_mutation": "forbidden; write once and verify SHA-256",
            "coverage_scope": "EXCL_FINANCE_INSURANCE",
            "seasonal_adjustment": "RAW",
            "causal_interpretation": "not supplied by this accounting decomposition",
        },
        "required_metrics": [
            {
                "code": code,
                "metric_id": metric_id,
                "label_ja": label,
                "gap_sign": sign,
            }
            for code, metric_id, label, sign in METRIC_DEFINITIONS
        ],
        "sources": sources,
    }
    write_new_bytes(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    return manifest


def _parse_result_file(
    values_path: Path,
    query_path: Path,
    *,
    source_dataset: str,
) -> pd.DataFrame:
    result = json.loads(values_path.read_text(encoding="utf-8"))
    query = json.loads(query_path.read_text(encoding="utf-8"))
    table_html = result.get("table")
    if not table_html:
        raise Phase3InputError(f"e-Stat response has no table HTML: {values_path}")
    spec = query["dimension_spec"]
    maps = {
        dimension: {str(entry["code"]): entry for entry in spec[dimension]}
        for dimension in ("industry", "capital", "time")
    }
    metric_map = query["metric_map"]
    soup = BeautifulSoup(table_html, "lxml")
    column_codes = [
        node.get("data-unique", "").split("@")[-1]
        for node in soup.select("thead .js-dbview-cols")
    ]
    if column_codes != [code for code, _, _, _ in METRIC_DEFINITIONS]:
        raise Phase3InputError(
            f"Unexpected metric column order in {values_path}: {column_codes}"
        )

    source_hash = sha256_file(values_path)
    rows: list[dict[str, Any]] = []
    for html_row in soup.select("tbody tr"):
        headers = html_row.select("th.js-dbview-rows")
        values = html_row.select("td.stat-dbview-value")
        if not headers:
            continue
        key_codes = headers[0].get("data-unique", "").split("@")
        if len(key_codes) != 3:
            raise Phase3InputError(
                f"Expected period@capital@industry row key in {values_path}: {key_codes}"
            )
        period_code, capital_code, industry_code = key_codes
        if len(values) != len(column_codes):
            raise Phase3InputError(
                f"Metric cell count mismatch for {'@'.join(key_codes)} in {values_path}"
            )
        try:
            period = maps["time"][period_code]
            capital = maps["capital"][capital_code]
            industry = maps["industry"][industry_code]
        except KeyError as exc:
            raise Phase3InputError(f"Unknown dimension code {exc} in {values_path}") from exc
        for metric_code, node in zip(column_codes, values, strict=True):
            value, status = _number_or_none(node.get_text(" ", strip=True))
            metric = metric_map[metric_code]
            rows.append(
                {
                    "release_id": "2026Q1",
                    "vintage_id": PHASE3_VINTAGE_ID,
                    "period_code": period_code,
                    "period_label": period["name"],
                    "period_ordinal": _quarter_ordinal(period_code),
                    "period_end": _period_end(period_code),
                    "coverage_scope": "EXCL_FINANCE_INSURANCE",
                    "seasonal_adjustment": "RAW",
                    "industry_code": industry_code,
                    "industry_name": industry["name"],
                    "capital_size_code": capital_code,
                    "capital_size_name": capital["name"],
                    "metric_code": metric_code,
                    "metric_id": metric["metric_id"],
                    "metric_label_ja": metric["metric_label_ja"],
                    "gap_sign": metric["gap_sign"],
                    "source_unit": metric["source_unit"],
                    "source_value_million_yen": value,
                    "value_oku_yen": None if value is None else value / 100.0,
                    "value_status": status,
                    "source_dataset": source_dataset,
                    "source_cell_key": "@".join(
                        [period_code, capital_code, industry_code, metric_code]
                    ),
                    "source_path": str(values_path),
                    "source_sha256": source_hash,
                }
            )
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise Phase3InputError(f"No observations parsed from {values_path}")
    return frame


def parse_phase3_non_operating_raw(
    *,
    raw_root: Path = PHASE3_RAW_ROOT,
    dataset: Literal["historical", "current", "combined"] = "combined",
) -> pd.DataFrame:
    """Parse the frozen raw files, preserving explicit missing-value statuses.

    ``combined`` returns the non-duplicated historical series after independently
    confirming that the dedicated current snapshot equals its historical copy.
    """
    raw_root = Path(raw_root)
    manifest = _verify_existing_manifest(raw_root / "data_manifest.json")
    sources = {source["source_id"]: source for source in manifest["sources"]}
    selected_roles: set[str]
    if dataset == "historical":
        selected_roles = {"numeric_authority_history_chunk"}
    elif dataset == "current":
        selected_roles = {"numeric_authority_current"}
    elif dataset == "combined":
        selected_roles = {
            "numeric_authority_history_chunk",
            "numeric_authority_current",
        }
    else:
        raise ValueError(f"Unknown Phase 3 dataset: {dataset!r}")

    frames: list[pd.DataFrame] = []
    for source in manifest["sources"]:
        if source["role"] not in selected_roles:
            continue
        query_source = sources[source["query_source_id"]]
        values_path = Path(source["raw_path"])
        if not values_path.is_absolute():
            values_path = PROJECT_ROOT / values_path
        query_path = Path(query_source["raw_path"])
        if not query_path.is_absolute():
            query_path = PROJECT_ROOT / query_path
        source_dataset = (
            "current" if source["role"] == "numeric_authority_current" else "historical"
        )
        frames.append(
            _parse_result_file(
                values_path,
                query_path,
                source_dataset=source_dataset,
            )
        )
    if not frames:
        raise Phase3InputError(f"No raw files selected for dataset={dataset!r}")
    combined = pd.concat(frames, ignore_index=True)
    key = ["period_code", "industry_code", "capital_size_code", "metric_id"]

    if dataset == "combined":
        current = combined.loc[combined["source_dataset"].eq("current")].copy()
        historical = combined.loc[combined["source_dataset"].eq("historical")].copy()
        target_history = historical.loc[historical["period_code"].eq(TARGET_PERIOD_CODE)]
        compare = target_history[key + ["value_oku_yen", "value_status"]].merge(
            current[key + ["value_oku_yen", "value_status"]],
            on=key,
            how="outer",
            suffixes=("_history", "_current"),
            indicator=True,
        )
        equal_value = np.isclose(
            compare["value_oku_yen_history"],
            compare["value_oku_yen_current"],
            atol=0.0,
            rtol=0.0,
            equal_nan=True,
        )
        equal_status = compare["value_status_history"].eq(compare["value_status_current"])
        if not compare["_merge"].eq("both").all() or not (equal_value & equal_status).all():
            raise Phase3InputError("Current snapshot differs from target-period history copy")
        combined = historical.copy()
        combined["current_snapshot_verified"] = combined["period_code"].eq(
            TARGET_PERIOD_CODE
        )
    else:
        if combined.duplicated(key).any():
            raise Phase3InputError(f"Duplicate source cells in dataset={dataset!r}")
        combined["current_snapshot_verified"] = dataset == "current"

    return combined.sort_values(
        ["period_ordinal", "industry_code", "capital_size_code", "metric_code"]
    ).reset_index(drop=True)


def mechanical_earliest_complete_period(raw_long: pd.DataFrame) -> pd.DataFrame:
    """Audit completeness by period and mark the mechanically earliest full row set."""
    required = {
        "period_code",
        "period_ordinal",
        "industry_code",
        "capital_size_code",
        "metric_id",
        "value_oku_yen",
        "value_status",
    }
    missing = required - set(raw_long.columns)
    if missing:
        raise Phase3InputError(f"Raw long frame lacks columns: {sorted(missing)}")
    industries = raw_long["industry_code"].astype(str).unique()
    capitals = raw_long["capital_size_code"].astype(str).unique()
    expected = len(industries) * len(capitals) * len(REQUIRED_METRIC_IDS)
    rows = []
    for (period_code, ordinal), group in raw_long.groupby(
        ["period_code", "period_ordinal"], sort=False
    ):
        unique_count = len(
            group.drop_duplicates(
                ["industry_code", "capital_size_code", "metric_id"]
            )
        )
        present = int(
            (group["value_status"].eq("PRESENT") & group["value_oku_yen"].notna()).sum()
        )
        complete = unique_count == expected and present == expected
        rows.append(
            {
                "period_code": str(period_code),
                "period_ordinal": int(ordinal),
                "expected_cells": expected,
                "unique_cells": unique_count,
                "present_cells": present,
                "missing_cells": expected - present,
                "is_complete": complete,
                "status": "COMPLETE" if complete else "INCOMPLETE_SOURCE_CELLS",
            }
        )
    audit = pd.DataFrame(rows).sort_values("period_ordinal").reset_index(drop=True)
    complete_periods = audit.loc[audit["is_complete"], "period_code"]
    earliest = None if complete_periods.empty else str(complete_periods.iloc[0])
    audit["is_mechanical_earliest"] = audit["period_code"].eq(earliest)
    return audit


def _taxonomy_metadata(config: Mapping[str, Any] | None = None) -> pd.DataFrame:
    cfg = dict(config or load_stage2_config())
    major = taxonomy_definition("major", config=cfg)
    leaf = taxonomy_definition("leaf", config=cfg)
    codes = _selected_industry_codes(cfg)
    rows = []
    for code in codes:
        major_row = major.loc[major["industry_code"].eq(code)]
        leaf_row = leaf.loc[leaf["industry_code"].eq(code)]
        parent_code = None
        parent_name = None
        if not leaf_row.empty:
            parent_code = str(leaf_row.iloc[0]["parent_major_code"])
            parent_name = str(leaf_row.iloc[0]["parent_major_name"])
        elif not major_row.empty:
            parent_code = code
            parent_name = str(major_row.iloc[0]["industry_name"])
        memberships = []
        if not major_row.empty:
            memberships.append("major")
        if not leaf_row.empty:
            memberships.append("leaf")
        rows.append(
            {
                "industry_code": code,
                "is_all_industry": code == ALL_INDUSTRY_CODE,
                "is_major_industry": not major_row.empty,
                "is_leaf_industry": not leaf_row.empty,
                "taxonomy_membership": "|".join(memberships) or "all",
                "parent_major_code": parent_code,
                "parent_major_name": parent_name,
            }
        )
    return pd.DataFrame(rows)


def build_non_operating_decomposition(
    raw_long: pd.DataFrame,
    *,
    tolerance_oku_yen: float = AMOUNT_TOLERANCE_OKU_YEN,
    config: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Build row-level current, YoY, and signed profit-impact identities."""
    required = {
        "period_code",
        "period_ordinal",
        "period_label",
        "period_end",
        "industry_code",
        "industry_name",
        "capital_size_code",
        "capital_size_name",
        "metric_id",
        "value_oku_yen",
        "value_status",
    }
    missing = required - set(raw_long.columns)
    if missing:
        raise Phase3InputError(f"Raw long frame lacks columns: {sorted(missing)}")
    unknown = set(raw_long["metric_id"].astype(str)) - set(REQUIRED_METRIC_IDS)
    if unknown:
        raise Phase3InputError(f"Unexpected Phase 3 metrics: {sorted(unknown)}")
    cell_index = ["period_code", "industry_code", "capital_size_code"]
    if raw_long.duplicated([*cell_index, "metric_id"]).any():
        raise Phase3InputError("Duplicate Phase 3 cells before decomposition pivot")
    period_metadata = raw_long[
        ["period_code", "period_ordinal", "period_label", "period_end"]
    ].drop_duplicates("period_code")
    industry_metadata = raw_long[["industry_code", "industry_name"]].drop_duplicates(
        "industry_code"
    )
    capital_metadata = raw_long[
        ["capital_size_code", "capital_size_name"]
    ].drop_duplicates("capital_size_code")
    full_index = pd.MultiIndex.from_product(
        [
            period_metadata["period_code"].astype(str),
            industry_metadata["industry_code"].astype(str),
            capital_metadata["capital_size_code"].astype(str),
        ],
        names=cell_index,
    )
    values = raw_long.pivot(
        index=cell_index, columns="metric_id", values="value_oku_yen"
    ).reindex(full_index)
    statuses = raw_long.pivot(
        index=cell_index, columns="metric_id", values="value_status"
    ).reindex(full_index)
    values = values.reindex(columns=REQUIRED_METRIC_IDS)
    statuses = statuses.reindex(columns=REQUIRED_METRIC_IDS)
    frame = (
        values.reset_index()
        .merge(period_metadata, on="period_code", how="left", validate="many_to_one")
        .merge(industry_metadata, on="industry_code", how="left", validate="many_to_one")
        .merge(capital_metadata, on="capital_size_code", how="left", validate="many_to_one")
    )
    for metric_id in REQUIRED_METRIC_IDS:
        frame.rename(columns={metric_id: f"{metric_id}_oku_yen"}, inplace=True)
        frame[f"{metric_id}_source_status"] = statuses[metric_id].fillna(
            "ABSENT_SOURCE_ROW"
        ).to_numpy()

    frame = frame.merge(_taxonomy_metadata(config), on="industry_code", how="left", validate="many_to_one")
    frame["is_all_capital"] = frame["capital_size_code"].eq(ALL_CAPITAL_CODE)
    frame["is_component_capital"] = frame["capital_size_code"].isin(CAPITAL_CODES)

    frame["anchor_gap_oku_yen"] = frame.apply(
        lambda row: _difference(
            row["ordinary_profit_oku_yen"], row["operating_profit_oku_yen"]
        ),
        axis=1,
    )
    frame["component_gap_oku_yen"] = frame.apply(
        lambda row: _strict_sum(
            COMPONENT_SIGNS[component] * row[f"{component}_oku_yen"]
            for component in COMPONENT_IDS
        ),
        axis=1,
    )
    frame["identity_residual_oku_yen"] = frame.apply(
        lambda row: _difference(
            row["component_gap_oku_yen"], row["anchor_gap_oku_yen"]
        ),
        axis=1,
    )
    frame["identity_status"] = frame["identity_residual_oku_yen"].map(
        lambda value: "MISSING_INPUT"
        if value is None or pd.isna(value)
        else ("PASS" if abs(float(value)) <= tolerance_oku_yen else "FAIL")
    )

    lookup_columns = [
        "period_code",
        "industry_code",
        "capital_size_code",
        *[f"{metric}_oku_yen" for metric in REQUIRED_METRIC_IDS],
        "anchor_gap_oku_yen",
        "component_gap_oku_yen",
    ]
    lag = frame[lookup_columns].copy()
    lag["period_code"] = lag["period_code"].map(
        lambda code: f"{int(str(code)[:4]) + 1:04d}{str(code)[-1]}"
    )
    lag = lag.rename(
        columns={
            column: f"{column.removesuffix('_oku_yen')}_lag4_oku_yen"
            for column in lookup_columns
            if column.endswith("_oku_yen")
        }
    )
    frame = frame.merge(
        lag,
        on=["period_code", "industry_code", "capital_size_code"],
        how="left",
        validate="one_to_one",
    )
    for metric_id in REQUIRED_METRIC_IDS:
        frame[f"{metric_id}_yoy_delta_oku_yen"] = frame.apply(
            lambda row, metric=metric_id: _difference(
                row[f"{metric}_oku_yen"], row[f"{metric}_lag4_oku_yen"]
            ),
            axis=1,
        )
        frame[f"{metric_id}_yoy_status"] = frame.apply(
            lambda row, metric=metric_id: (
                "NO_COMPARABLE_YEAR_AGO_PERIOD"
                if _quarter_ordinal(str(row["period_code"]))
                < _quarter_ordinal(COMPARABLE_START_PERIOD_CODE) + 4
                else (
                    "MISSING_INPUT"
                    if pd.isna(row[f"{metric}_yoy_delta_oku_yen"])
                    else "CALCULABLE"
                )
            ),
            axis=1,
        )

    for component, sign in COMPONENT_SIGNS.items():
        frame[f"{component}_profit_impact_yoy_oku_yen"] = frame[
            f"{component}_yoy_delta_oku_yen"
        ].map(lambda value, multiplier=sign: None if pd.isna(value) else multiplier * float(value))
        frame[f"{component}_profit_impact_sign"] = frame[
            f"{component}_profit_impact_yoy_oku_yen"
        ].map(
            lambda value: "MISSING_INPUT"
            if value is None or pd.isna(value)
            else (
                "INCREASES_PROFIT_CHANGE"
                if float(value) > 0
                else ("REDUCES_PROFIT_CHANGE" if float(value) < 0 else "ZERO")
            )
        )

    frame["anchor_gap_yoy_delta_oku_yen"] = frame.apply(
        lambda row: _difference(
            row["anchor_gap_oku_yen"], row["anchor_gap_lag4_oku_yen"]
        ),
        axis=1,
    )
    frame["component_gap_yoy_delta_oku_yen"] = frame.apply(
        lambda row: _difference(
            row["component_gap_oku_yen"], row["component_gap_lag4_oku_yen"]
        ),
        axis=1,
    )
    frame["profit_impact_sum_yoy_oku_yen"] = frame.apply(
        lambda row: _strict_sum(
            row[f"{component}_profit_impact_yoy_oku_yen"]
            for component in COMPONENT_IDS
        ),
        axis=1,
    )
    frame["yoy_identity_residual_oku_yen"] = frame.apply(
        lambda row: _difference(
            row["profit_impact_sum_yoy_oku_yen"],
            row["anchor_gap_yoy_delta_oku_yen"],
        ),
        axis=1,
    )
    frame["yoy_identity_status"] = frame["yoy_identity_residual_oku_yen"].map(
        lambda value: "NO_COMPARABLE_YEAR_AGO_PERIOD"
        if value is None or pd.isna(value)
        else ("PASS" if abs(float(value)) <= tolerance_oku_yen else "FAIL")
    )
    return frame.sort_values(
        ["period_ordinal", "industry_code", "capital_size_code"]
    ).reset_index(drop=True)


def build_current_breakdown(
    decomposition: pd.DataFrame,
    *,
    period_code: str = TARGET_PERIOD_CODE,
) -> pd.DataFrame:
    """Return a long four-component table with neutral, signed labels."""
    current = decomposition.loc[decomposition["period_code"].eq(period_code)].copy()
    rows: list[dict[str, Any]] = []
    label_by_component = {
        "interest_and_dividend_income": "受取利息等の前年差による利益影響",
        "other_non_operating_income": "その他の営業外収益の前年差による利益影響",
        "interest_expense": "支払利息等の前年差による利益影響",
        "other_non_operating_expense": "その他の営業外費用の前年差による利益影響",
    }
    for _, source in current.iterrows():
        denominator = source["anchor_gap_yoy_delta_oku_yen"]
        for order, component in enumerate(COMPONENT_IDS, start=1):
            impact = source[f"{component}_profit_impact_yoy_oku_yen"]
            share = (
                None
                if pd.isna(impact) or pd.isna(denominator) or float(denominator) == 0
                else float(impact) / float(denominator) * 100.0
            )
            rows.append(
                {
                    "period_code": source["period_code"],
                    "period_label": source["period_label"],
                    "industry_code": source["industry_code"],
                    "industry_name": source["industry_name"],
                    "capital_size_code": source["capital_size_code"],
                    "capital_size_name": source["capital_size_name"],
                    "is_all_industry": source["is_all_industry"],
                    "is_major_industry": source["is_major_industry"],
                    "is_leaf_industry": source["is_leaf_industry"],
                    "parent_major_code": source["parent_major_code"],
                    "component_order": order,
                    "component_id": component,
                    "component_label_ja": METRIC_LABEL_BY_ID[component],
                    "profit_impact_label_ja": label_by_component[component],
                    "accounting_sign": COMPONENT_SIGNS[component],
                    "current_oku_yen": source[f"{component}_oku_yen"],
                    "lag4_oku_yen": source[f"{component}_lag4_oku_yen"],
                    "source_yoy_delta_oku_yen": source[f"{component}_yoy_delta_oku_yen"],
                    "profit_impact_yoy_oku_yen": impact,
                    "profit_impact_sign": source[f"{component}_profit_impact_sign"],
                    "signed_share_of_net_gap_delta_pct": share,
                    "calculation_status": source[f"{component}_yoy_status"],
                    "interpretation_guardrail": (
                        "原因は統計だけでは特定しない"
                        if component == "other_non_operating_income"
                        else "会計的な利益影響であり因果を示さない"
                    ),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["industry_code", "capital_size_code", "component_order"]
    ).reset_index(drop=True)


def build_identity_checks(
    decomposition: pd.DataFrame,
    *,
    tolerance_oku_yen: float = AMOUNT_TOLERANCE_OKU_YEN,
) -> pd.DataFrame:
    """Materialize level and YoY identity gates for every industry-capital cell."""
    rows = []
    for _, source in decomposition.iterrows():
        scope = (
            f"period={source['period_code']};industry={source['industry_code']};"
            f"capital={source['capital_size_code']}"
        )
        for basis, expected_column, actual_column in (
            ("LEVEL", "anchor_gap_oku_yen", "component_gap_oku_yen"),
            (
                "YOY_DELTA",
                "anchor_gap_yoy_delta_oku_yen",
                "profit_impact_sum_yoy_oku_yen",
            ),
        ):
            expected = source[expected_column]
            actual = source[actual_column]
            difference = _difference(actual, expected)
            if difference is None:
                status = (
                    "NO_COMPARABLE_YEAR_AGO_PERIOD"
                    if basis == "YOY_DELTA"
                    and _quarter_ordinal(str(source["period_code"]))
                    < _quarter_ordinal(COMPARABLE_START_PERIOD_CODE) + 4
                    else "MISSING_INPUT"
                )
            else:
                status = "PASS" if abs(difference) <= tolerance_oku_yen else "FAIL"
            rows.append(
                {
                    "check_id": f"non_operating_identity_{basis.lower()}_{source['period_code']}_{source['industry_code']}_{source['capital_size_code']}",
                    "check_type": "NON_OPERATING_IDENTITY",
                    "basis": basis,
                    "scope": scope,
                    "period_code": source["period_code"],
                    "industry_code": source["industry_code"],
                    "capital_size_code": source["capital_size_code"],
                    "expected_oku_yen": expected,
                    "actual_oku_yen": actual,
                    "difference_oku_yen": difference,
                    "tolerance_oku_yen": tolerance_oku_yen,
                    "status": status,
                }
            )
    return pd.DataFrame(rows)


def build_additivity_checks(
    decomposition: pd.DataFrame,
    *,
    taxonomies: Sequence[Literal["major", "leaf"]] = ("major", "leaf"),
    tolerance_oku_yen: float = AMOUNT_TOLERANCE_OKU_YEN,
    config: Mapping[str, Any] | None = None,
    value_columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Check capital, industry, parent-child, row, column, and grand totals."""
    cfg = dict(config or load_stage2_config())
    columns = list(
        value_columns
        or (
            *[f"{metric}_oku_yen" for metric in REQUIRED_METRIC_IDS],
            "anchor_gap_oku_yen",
            "component_gap_oku_yen",
            "anchor_gap_yoy_delta_oku_yen",
            "profit_impact_sum_yoy_oku_yen",
        )
    )
    missing_columns = set(columns) - set(decomposition.columns)
    if missing_columns:
        raise Phase3InputError(
            f"Decomposition lacks additivity columns: {sorted(missing_columns)}"
        )

    def finalize(
        comparison: pd.DataFrame,
        *,
        check_type: str,
        taxonomy: str,
        value_column: str,
        id_columns: Sequence[str],
        scope_columns: Sequence[str],
    ) -> pd.DataFrame:
        result = comparison.copy()
        result["difference_oku_yen"] = result["actual_oku_yen"] - result[
            "expected_oku_yen"
        ]
        missing_input = result[["actual_oku_yen", "expected_oku_yen"]].isna().any(axis=1)
        result["status"] = np.where(
            missing_input,
            "MISSING_INPUT",
            np.where(
                result["difference_oku_yen"].abs().le(tolerance_oku_yen),
                "PASS",
                "FAIL",
            ),
        )
        no_prior = result["period_code"].map(_quarter_ordinal).lt(
            _quarter_ordinal(COMPARABLE_START_PERIOD_CODE) + 4
        )
        is_yoy = bool(re.search(r"yoy|profit_impact", value_column, flags=re.I))
        if is_yoy:
            result.loc[
                result["status"].eq("MISSING_INPUT") & no_prior, "status"
            ] = "NO_COMPARABLE_YEAR_AGO_PERIOD"
        result["check_type"] = check_type
        result["taxonomy"] = taxonomy
        result["value_column"] = value_column
        result["tolerance_oku_yen"] = tolerance_oku_yen
        result["check_id"] = (
            check_type.lower()
            + "_"
            + taxonomy
            + "_"
            + result[id_columns].astype(str).agg("_".join, axis=1)
            + "_"
            + value_column
        )
        result["scope"] = result[scope_columns].astype(str).agg(
            lambda values: ";".join(
                f"{column}={value}" for column, value in zip(scope_columns, values, strict=True)
            ),
            axis=1,
        )
        return result[
            [
                "check_id",
                "check_type",
                "taxonomy",
                "period_code",
                "value_column",
                "scope",
                "expected_oku_yen",
                "actual_oku_yen",
                "difference_oku_yen",
                "tolerance_oku_yen",
                "status",
            ]
        ]

    checks: list[pd.DataFrame] = []
    for taxonomy in taxonomies:
        definition = taxonomy_definition(taxonomy, config=cfg)
        industry_codes = definition["industry_code"].astype(str).tolist()
        industries_with_all = [ALL_INDUSTRY_CODE, *industry_codes]
        for column in columns:
            # Three disjoint capital buckets -> all capital, by industry.
            capital_base = decomposition.loc[
                decomposition["industry_code"].isin(industries_with_all)
            ]
            expected = capital_base.loc[
                capital_base["capital_size_code"].eq(ALL_CAPITAL_CODE),
                ["period_code", "industry_code", column],
            ].rename(columns={column: "expected_oku_yen"})
            actual = (
                capital_base.loc[capital_base["capital_size_code"].isin(CAPITAL_CODES)]
                .groupby(["period_code", "industry_code"], as_index=False)[column]
                .sum(min_count=len(CAPITAL_CODES))
                .rename(columns={column: "actual_oku_yen"})
            )
            comparison = expected.merge(
                actual,
                on=["period_code", "industry_code"],
                how="outer",
                validate="one_to_one",
            )
            checks.append(
                finalize(
                    comparison,
                    check_type="CAPITAL_COMPONENTS_TO_ALL",
                    taxonomy=taxonomy,
                    value_column=column,
                    id_columns=["period_code", "industry_code"],
                    scope_columns=["industry_code"],
                )
            )

            # Mutually exclusive industries -> all industry, by capital.
            expected = decomposition.loc[
                decomposition["industry_code"].eq(ALL_INDUSTRY_CODE),
                ["period_code", "capital_size_code", column],
            ].rename(columns={column: "expected_oku_yen"})
            actual = (
                decomposition.loc[decomposition["industry_code"].isin(industry_codes)]
                .groupby(["period_code", "capital_size_code"], as_index=False)[column]
                .sum(min_count=len(industry_codes))
                .rename(columns={column: "actual_oku_yen"})
            )
            comparison = expected.merge(
                actual,
                on=["period_code", "capital_size_code"],
                how="outer",
                validate="one_to_one",
            )
            checks.append(
                finalize(
                    comparison,
                    check_type="INDUSTRIES_TO_ALL",
                    taxonomy=taxonomy,
                    value_column=column,
                    id_columns=["period_code", "capital_size_code"],
                    scope_columns=["capital_size_code"],
                )
            )

            # Leaf children -> each independently published parent aggregate.
            if taxonomy == "leaf":
                for parent_code, children in definition.groupby("parent_major_code"):
                    child_codes = children["industry_code"].astype(str).tolist()
                    expected = decomposition.loc[
                        decomposition["industry_code"].eq(str(parent_code)),
                        ["period_code", "capital_size_code", column],
                    ].rename(columns={column: "expected_oku_yen"})
                    actual = (
                        decomposition.loc[
                            decomposition["industry_code"].isin(child_codes)
                        ]
                        .groupby(["period_code", "capital_size_code"], as_index=False)[
                            column
                        ]
                        .sum(min_count=len(child_codes))
                        .rename(columns={column: "actual_oku_yen"})
                    )
                    comparison = expected.merge(
                        actual,
                        on=["period_code", "capital_size_code"],
                        how="outer",
                        validate="one_to_one",
                    )
                    comparison["parent_major_code"] = str(parent_code)
                    checks.append(
                        finalize(
                            comparison,
                            check_type="LEAF_TO_PARENT",
                            taxonomy=taxonomy,
                            value_column=column,
                            id_columns=[
                                "period_code",
                                "parent_major_code",
                                "capital_size_code",
                            ],
                            scope_columns=["parent_major_code", "capital_size_code"],
                        )
                    )

            # Every industry x three-capital cell -> grand total.
            expected = decomposition.loc[
                decomposition["industry_code"].eq(ALL_INDUSTRY_CODE)
                & decomposition["capital_size_code"].eq(ALL_CAPITAL_CODE),
                ["period_code", column],
            ].rename(columns={column: "expected_oku_yen"})
            actual = (
                decomposition.loc[
                    decomposition["industry_code"].isin(industry_codes)
                    & decomposition["capital_size_code"].isin(CAPITAL_CODES)
                ]
                .groupby("period_code", as_index=False)[column]
                .sum(min_count=len(industry_codes) * len(CAPITAL_CODES))
                .rename(columns={column: "actual_oku_yen"})
            )
            comparison = expected.merge(
                actual, on="period_code", how="outer", validate="one_to_one"
            )
            comparison["cross_scope"] = "all_industries_x_three_capital_buckets"
            checks.append(
                finalize(
                    comparison,
                    check_type="CROSS_GRAND_TOTAL",
                    taxonomy=taxonomy,
                    value_column=column,
                    id_columns=["period_code"],
                    scope_columns=["cross_scope"],
                )
            )
    return pd.concat(checks, ignore_index=True)


def build_historical_statistics(decomposition: pd.DataFrame) -> pd.DataFrame:
    """Return four-quarter moving sums and within-cell historical ranks."""
    rows: list[dict[str, Any]] = []
    base_columns = [
        "period_code",
        "period_ordinal",
        "period_label",
        "industry_code",
        "industry_name",
        "capital_size_code",
        "capital_size_name",
        "is_all_industry",
        "is_major_industry",
        "is_leaf_industry",
    ]
    for component in COMPONENT_IDS:
        component_frame = decomposition[base_columns].copy()
        component_frame["component_id"] = component
        component_frame["component_label_ja"] = METRIC_LABEL_BY_ID[component]
        component_frame["accounting_sign"] = COMPONENT_SIGNS[component]
        component_frame["source_value_oku_yen"] = decomposition[f"{component}_oku_yen"]
        component_frame["signed_gap_level_oku_yen"] = (
            decomposition[f"{component}_oku_yen"] * COMPONENT_SIGNS[component]
        )
        component_frame["source_yoy_delta_oku_yen"] = decomposition[
            f"{component}_yoy_delta_oku_yen"
        ]
        component_frame["profit_impact_yoy_oku_yen"] = decomposition[
            f"{component}_profit_impact_yoy_oku_yen"
        ]
        rows.extend(component_frame.to_dict("records"))
    history = pd.DataFrame(rows).sort_values(
        ["industry_code", "capital_size_code", "component_id", "period_ordinal"]
    )
    group_keys = ["industry_code", "capital_size_code", "component_id"]
    for source, target in (
        ("source_value_oku_yen", "source_value_trailing4q_oku_yen"),
        ("signed_gap_level_oku_yen", "signed_gap_level_trailing4q_oku_yen"),
        (
            "profit_impact_yoy_oku_yen",
            "profit_impact_yoy_trailing4q_oku_yen",
        ),
    ):
        history[target] = history.groupby(group_keys, sort=False)[source].transform(
            lambda series: series.rolling(4, min_periods=4).sum()
        )
    history["profit_impact_rank_desc"] = history.groupby(group_keys, sort=False)[
        "profit_impact_yoy_oku_yen"
    ].rank(method="min", ascending=False)
    history["profit_impact_abs_rank_desc"] = history.assign(
        _absolute=history["profit_impact_yoy_oku_yen"].abs()
    ).groupby(group_keys, sort=False)["_absolute"].rank(method="min", ascending=False)
    history["historical_observation_count"] = history.groupby(group_keys, sort=False)[
        "profit_impact_yoy_oku_yen"
    ].transform("count")
    history["profit_impact_percentile_inclusive_pct"] = history.groupby(
        group_keys, sort=False
    )["profit_impact_yoy_oku_yen"].transform(
        lambda series: series.rank(method="max", ascending=True, pct=True) * 100.0
    )
    history["profit_impact_percentile_method"] = (
        "INCLUSIVE_EMPIRICAL_CDF:100*count(values<=current)/count(nonmissing)"
    )
    history["history_status"] = np.where(
        history["profit_impact_yoy_oku_yen"].notna(),
        "CALCULABLE",
        "NO_COMPARABLE_YEAR_AGO_PERIOD",
    )
    return history.reset_index(drop=True)


def _concentration_group(
    frame: pd.DataFrame,
    *,
    dimension: str,
    taxonomy: str,
    component_id: str,
    member_code_column: str,
    member_name_column: str,
) -> pd.DataFrame:
    result = frame.copy()
    result = result.rename(
        columns={
            member_code_column: "member_code",
            member_name_column: "member_name",
        }
    )
    impact = result["profit_impact_yoy_oku_yen"]
    net = impact.sum(min_count=len(impact))
    positive_total = impact.clip(lower=0).sum(min_count=len(impact))
    absolute_total = impact.abs().sum(min_count=len(impact))
    result["concentration_dimension"] = dimension
    result["taxonomy"] = taxonomy
    result["component_id"] = component_id
    result["component_label_ja"] = (
        "営業利益外差額の四項目" if component_id == "ALL_COMPONENTS" else METRIC_LABEL_BY_ID[component_id]
    )
    result["signed_share_of_net_pct"] = (
        np.nan if pd.isna(net) or net == 0 else impact / net * 100.0
    )
    result["positive_share_pct"] = np.where(
        impact.gt(0) & pd.notna(positive_total) & (positive_total != 0),
        impact / positive_total * 100.0,
        np.where(impact.notna(), 0.0, np.nan),
    )
    result["absolute_share_pct"] = (
        np.nan if pd.isna(absolute_total) or absolute_total == 0 else impact.abs() / absolute_total * 100.0
    )
    result["rank_desc"] = impact.rank(method="min", ascending=False)
    positive_sorted = impact.loc[impact.gt(0)].sort_values(ascending=False)
    for top_n in (1, 3, 5):
        value = (
            np.nan
            if pd.isna(positive_total) or positive_total == 0
            else float(positive_sorted.head(top_n).sum() / positive_total * 100.0)
        )
        result[f"top{top_n}_positive_concentration_pct"] = value
    result["denominator_status"] = np.where(
        impact.isna().any(),
        "MISSING_INPUT",
        np.where(net == 0, "ZERO_NET_DENOMINATOR", "CALCULABLE"),
    )
    keep = [
        "period_code",
        "concentration_dimension",
        "taxonomy",
        "component_id",
        "component_label_ja",
        "member_code",
        "member_name",
        "profit_impact_yoy_oku_yen",
        "signed_share_of_net_pct",
        "positive_share_pct",
        "absolute_share_pct",
        "rank_desc",
        "top1_positive_concentration_pct",
        "top3_positive_concentration_pct",
        "top5_positive_concentration_pct",
        "denominator_status",
    ]
    return result[keep]


def build_concentration_tables(
    current_breakdown: pd.DataFrame,
    *,
    config: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Build item, capital, and separate major/leaf industry concentration tables."""
    cfg = dict(config or load_stage2_config())
    rows: list[pd.DataFrame] = []
    total = current_breakdown.loc[
        current_breakdown["industry_code"].eq(ALL_INDUSTRY_CODE)
        & current_breakdown["capital_size_code"].eq(ALL_CAPITAL_CODE)
    ].copy()
    item = total.rename(
        columns={"component_id": "item_code", "component_label_ja": "item_name"}
    )
    rows.append(
        _concentration_group(
            item,
            dimension="ITEM",
            taxonomy="four_component_identity",
            component_id="ALL_COMPONENTS",
            member_code_column="item_code",
            member_name_column="item_name",
        )
    )

    # Net four-component gap change by capital bucket.
    capital_total_source = current_breakdown.loc[
        current_breakdown["industry_code"].eq(ALL_INDUSTRY_CODE)
        & current_breakdown["capital_size_code"].isin(CAPITAL_CODES)
    ]
    capital_total = (
        capital_total_source.groupby(
            ["period_code", "capital_size_code", "capital_size_name"],
            as_index=False,
        )["profit_impact_yoy_oku_yen"]
        .sum(min_count=len(COMPONENT_IDS))
    )
    rows.append(
        _concentration_group(
            capital_total,
            dimension="CAPITAL",
            taxonomy="three_disjoint_capital_buckets",
            component_id="ALL_COMPONENTS",
            member_code_column="capital_size_code",
            member_name_column="capital_size_name",
        )
    )

    # Net four-component gap change by industry, with major and leaf kept
    # strictly separate so overlapping published aggregates never mix.
    for taxonomy in ("major", "leaf"):
        definition = taxonomy_definition(taxonomy, config=cfg)
        industry_total_source = current_breakdown.loc[
            current_breakdown["industry_code"].isin(
                definition["industry_code"].astype(str)
            )
            & current_breakdown["capital_size_code"].eq(ALL_CAPITAL_CODE)
        ]
        industry_total = (
            industry_total_source.groupby(
                ["period_code", "industry_code", "industry_name"], as_index=False
            )["profit_impact_yoy_oku_yen"]
            .sum(min_count=len(COMPONENT_IDS))
        )
        rows.append(
            _concentration_group(
                industry_total,
                dimension="INDUSTRY",
                taxonomy=taxonomy,
                component_id="ALL_COMPONENTS",
                member_code_column="industry_code",
                member_name_column="industry_name",
            )
        )

    for component in COMPONENT_IDS:
        capital = current_breakdown.loc[
            current_breakdown["industry_code"].eq(ALL_INDUSTRY_CODE)
            & current_breakdown["capital_size_code"].isin(CAPITAL_CODES)
            & current_breakdown["component_id"].eq(component)
        ].copy()
        rows.append(
            _concentration_group(
                capital,
                dimension="CAPITAL",
                taxonomy="three_disjoint_capital_buckets",
                component_id=component,
                member_code_column="capital_size_code",
                member_name_column="capital_size_name",
            )
        )
        for taxonomy in ("major", "leaf"):
            definition = taxonomy_definition(taxonomy, config=cfg)
            industry = current_breakdown.loc[
                current_breakdown["industry_code"].isin(
                    definition["industry_code"].astype(str)
                )
                & current_breakdown["capital_size_code"].eq(ALL_CAPITAL_CODE)
                & current_breakdown["component_id"].eq(component)
            ].copy()
            rows.append(
                _concentration_group(
                    industry,
                    dimension="INDUSTRY",
                    taxonomy=taxonomy,
                    component_id=component,
                    member_code_column="industry_code",
                    member_name_column="industry_name",
                )
            )
    return pd.concat(rows, ignore_index=True)


def build_phase3_non_operating_analysis(
    raw_long: pd.DataFrame | None = None,
    *,
    raw_root: Path = PHASE3_RAW_ROOT,
    enforce_identity: bool = True,
    enforce_additivity: bool = True,
    tolerance_oku_yen: float = AMOUNT_TOLERANCE_OKU_YEN,
    config: Mapping[str, Any] | None = None,
) -> Phase3NonOperatingAnalysis:
    """Build the complete Phase 3 analysis from frozen raw or a supplied frame."""
    source = (
        parse_phase3_non_operating_raw(raw_root=raw_root, dataset="combined")
        if raw_long is None
        else raw_long.copy()
    )
    earliest = mechanical_earliest_complete_period(source)
    decomposition = build_non_operating_decomposition(
        source, tolerance_oku_yen=tolerance_oku_yen, config=config
    )
    identity = build_identity_checks(
        decomposition, tolerance_oku_yen=tolerance_oku_yen
    )
    additivity = build_additivity_checks(
        decomposition,
        tolerance_oku_yen=tolerance_oku_yen,
        config=config,
    )
    if enforce_identity:
        failures = identity.loc[identity["status"].eq("FAIL")]
        current_not_pass = identity.loc[
            identity["period_code"].eq(TARGET_PERIOD_CODE)
            & identity["status"].ne("PASS")
        ]
        failures = pd.concat([failures, current_not_pass], ignore_index=True).drop_duplicates(
            "check_id"
        )
        if not failures.empty:
            raise Phase3InputError(
                f"Phase 3 identity gate failed: {failures.iloc[0]['check_id']} "
                f"({failures.iloc[0]['status']})"
            )
    if enforce_additivity:
        failures = additivity.loc[additivity["status"].eq("FAIL")]
        current_not_pass = additivity.loc[
            additivity["period_code"].eq(TARGET_PERIOD_CODE)
            & additivity["status"].ne("PASS")
        ]
        failures = pd.concat([failures, current_not_pass], ignore_index=True).drop_duplicates(
            "check_id"
        )
        if not failures.empty:
            raise Phase3InputError(
                f"Phase 3 additivity gate failed: {failures.iloc[0]['check_id']} "
                f"({failures.iloc[0]['status']})"
            )
    current = build_current_breakdown(decomposition)
    history = build_historical_statistics(decomposition)
    concentration = build_concentration_tables(current, config=config)
    return Phase3NonOperatingAnalysis(
        raw_long=source,
        earliest_complete_period=earliest,
        decomposition=decomposition,
        current_breakdown=current,
        historical_statistics=history,
        concentration=concentration,
        identity_checks=identity,
        additivity_checks=additivity,
    )
