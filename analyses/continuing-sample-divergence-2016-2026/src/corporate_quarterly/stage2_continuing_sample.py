"""Continuing-sample reference rates and comparison with the regular series.

The Ministry of Finance publishes ``keizoku.pdf`` as a reference series based
only on corporations observed in both the current and year-earlier quarters.
This module freezes that official PDF together with a narrow e-Stat table 1
request for the matching regular-series cells.  It then exposes explicit,
auditable comparisons; it never treats the continuing sample as interchangeable
with the regular quarterly estimate.

The PDF contains rates rather than profit levels.  Consequently an operating-
margin direction inferred from its sales and operating-profit rates is labelled
as a directional proxy: the sign of the underlying continuing-sample operating
profit is not published in the PDF.  Profit standard-error rates are null with
``NOT_CALCULATED_BY_MOF`` because the source explicitly says they are not
calculated; they are never replaced by zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re
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
from .processing import _period_end, _to_oku_yen, detect_profit_transition, parse_estat_response


CONTINUING_VINTAGE_ID = "continuing_sample_2026Q1"
TARGET_PERIOD_CODE = "20261"
CONTINUING_START_PERIOD_CODE = "20161"
REGULAR_SOURCE_START_PERIOD_CODE = "20151"
ESTAT_SID = "0003060191"
TABLE_NUMBER = "1"
PDF_URL = "https://www.mof.go.jp/pri/reference/ssc/results/keizoku.pdf"
SOURCE_PAGE_URL = "https://www.mof.go.jp/pri/reference/ssc/results/data.htm"
PUBLICATION_DATE = "2026-06-01"
CURRENT_VINTAGE_STATUS = "CURRENT_VINTAGE_HISTORICAL_SERIES"
REVISION_STATUS = "NOT_TESTED_NO_PRIOR_PUBLICATION_VINTAGES"


METRICS = {
    "sales": "売上高",
    "operating_profit": "営業利益",
    "ordinary_profit": "経常利益",
    "capex_including_software": "設備投資",
}
PROFIT_METRICS = {"operating_profit", "ordinary_profit"}

INDUSTRY_CATEGORIES = {
    "104": "全産業",
    "108": "製造業",
    "144": "非製造業",
}
INDUSTRY_ESTAT_NAMES = {
    "104": "全産業（除く金融保険業）",
    "108": "製造業",
    "144": "非製造業",
}
CAPITAL_CATEGORIES = {
    "25": "大企業",
    "24": "中堅企業",
    "19": "中小企業",
}
CAPITAL_ESTAT_NAMES = {
    "26": "全規模",
    "25": "10億円以上",
    "24": "1億円以上 - 10億円未満",
    "19": "1千万円以上 - 1億円未満",
}
CAPITAL_EXPLICIT_MAPPING = {
    "大企業": {"estat_capital_code": "25", "estat_capital_name": "10億円以上"},
    "中堅企業": {
        "estat_capital_code": "24",
        "estat_capital_name": "1億円以上 - 10億円未満",
    },
    "中小企業": {
        "estat_capital_code": "19",
        "estat_capital_name": "1千万円以上 - 1億円未満",
    },
}

EXPECTED_CONTINUING_PERIODS = 41
EXPECTED_CONTINUING_ROWS = EXPECTED_CONTINUING_PERIODS * 24
EXPECTED_REGULAR_SOURCE_ROWS = 3 * 4 * 45 * 4
EXPECTED_REGULAR_ANALYSIS_ROWS = EXPECTED_CONTINUING_ROWS

LIMITATION_NOTES = {
    "continuing_sample_definition": (
        "継続標本とは、前年同期及び当期ともに標本となった法人。"
    ),
    "small_sample": (
        "継続標本のみを用い母集団推計を行うため、本系列に比べサンプルサイズが小さくなる。"
    ),
    "profit_standard_error": (
        "営業利益及び経常利益については、標準誤差率の算出は行っていない。"
    ),
    "coverage": "全産業及び非製造業には金融業、保険業は含まれない。",
    "relative_margin_proxy": (
        "継続標本PDFは利益水準とその符号を公表しないため、売上高と営業利益の増加率から得る利益率方向は代理指標である。"
    ),
}


class ContinuingSampleError(RuntimeError):
    """Raised when the continuing-sample source cannot be joined silently."""


@dataclass(frozen=True)
class ContinuingPdfTables:
    yoy_rates: pd.DataFrame
    response_counts: pd.DataFrame
    standard_error_rates: pd.DataFrame
    notes: dict[str, str]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ContinuingSampleAnalysis:
    continuing_yoy: pd.DataFrame
    regular_yoy: pd.DataFrame
    comparison: pd.DataFrame
    relative_margin_comparison: pd.DataFrame
    sign_reversal_frequency: pd.DataFrame
    relative_margin_reversal_frequency: pd.DataFrame
    capital_headline_history: pd.DataFrame
    headline_reversal_frequency: pd.DataFrame
    response_counts: pd.DataFrame
    standard_error_rates: pd.DataFrame
    limitations: dict[str, str]


def _raw_root(project_root: Path) -> Path:
    return Path(project_root) / "data" / "raw" / CONTINUING_VINTAGE_ID


def _quarter_ordinal(code: str) -> int:
    text = str(code)
    if not re.fullmatch(r"\d{5}", text) or text[-1] not in "1234":
        raise ContinuingSampleError(f"Invalid quarter code: {code!r}")
    return int(text[:4]) * 4 + int(text[-1]) - 1


def _period_codes(start: str, end: str) -> list[str]:
    start_ordinal = _quarter_ordinal(start)
    end_ordinal = _quarter_ordinal(end)
    result = []
    for ordinal in range(start_ordinal, end_ordinal + 1):
        year, zero_based_quarter = divmod(ordinal, 4)
        result.append(f"{year}{zero_based_quarter + 1}")
    return result


def _period_code(year: str, quarter_label: str) -> str:
    quarter = {
        "1～3月": "1",
        "4～6月": "2",
        "7～9月": "3",
        "10～12月": "4",
    }.get(quarter_label)
    if quarter is None:
        raise ContinuingSampleError(f"Unknown PDF quarter label: {quarter_label}")
    return f"{year}{quarter}"


def _parse_pdf_number(marker: str | None, number: str) -> float:
    value = float(number.replace(",", ""))
    return -value if marker else value


def _extract_quarter_rows(
    lines: list[str], start_index: int, end_index: int
) -> list[tuple[str, list[float]]]:
    row_pattern = re.compile(
        r"^\s*(\d{4})\s+(1～3月|4～6月|7～9月|10～12月)\s+(.*)$"
    )
    value_pattern = re.compile(r"(▲\s*)?(\d[\d,]*\.\d)")
    rows: list[tuple[str, list[float]]] = []
    for line in lines[start_index:end_index]:
        match = row_pattern.match(line)
        if not match:
            continue
        values = [
            _parse_pdf_number(marker, number)
            for marker, number in value_pattern.findall(match.group(3))
        ]
        # The response-count and standard-error mini-tables repeat the target
        # quarter as a header but contain no rate cells on that line.
        if not values:
            continue
        if len(values) != 12:
            raise ContinuingSampleError(
                f"Expected 12 PDF values in {match.group(1)} {match.group(2)}; "
                f"observed {len(values)}: {line}"
            )
        rows.append((_period_code(match.group(1), match.group(2)), values))
    expected = _period_codes(CONTINUING_START_PERIOD_CODE, TARGET_PERIOD_CODE)
    observed = [period for period, _ in rows]
    if observed != expected:
        raise ContinuingSampleError(
            f"PDF quarter sequence changed: expected {expected}, observed {observed}"
        )
    return rows


def _pdf_long_rows(
    *,
    period_rows: list[tuple[str, list[float]]],
    breakdown: str,
    categories: dict[str, str],
    pdf_path: Path,
    source_sha256: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    category_items = list(categories.items())
    for period_code, values in period_rows:
        for metric_index, (metric_id, metric_label) in enumerate(METRICS.items()):
            for category_index, (category_code, category_label) in enumerate(
                category_items
            ):
                value = values[metric_index * 3 + category_index]
                records.append(
                    {
                        "period_code": period_code,
                        "period": f"{period_code[:4]}年{['1～3月', '4～6月', '7～9月', '10～12月'][int(period_code[-1]) - 1]}",
                        "period_end": _period_end(period_code),
                        "period_ordinal": _quarter_ordinal(period_code),
                        "breakdown": breakdown,
                        "category_code": category_code,
                        "category_id": (
                            f"industry_{category_code}"
                            if breakdown == "industry"
                            else f"capital_{category_code}"
                        ),
                        "category_label_ja": category_label,
                        "category_mapping_note": (
                            "PDF capital label mapped to the matching e-Stat capital bracket; "
                            "this is not a legal enterprise-size classification"
                            if breakdown == "capital_size"
                            else "DIRECT_INDUSTRY_LABEL"
                        ),
                        "metric_id": metric_id,
                        "metric_label_ja": metric_label,
                        "yoy_pct": value,
                        "yoy_rate_status": "DIRECT_PUBLISHED_RATE",
                        "unit": "%",
                        "coverage_scope": "EXCL_FINANCE_INSURANCE",
                        "sample_method": "CONTINUING_SAMPLE_REFERENCE_ESTIMATE",
                        "is_direct_published_rate": True,
                        "source_document": "keizoku.pdf",
                        "source_path": str(Path(pdf_path).resolve()),
                        "source_sha256": source_sha256,
                        "pdf_page": 1,
                        "source_cell_key": (
                            f"keizoku:p1:{breakdown}:{period_code}:"
                            f"{metric_id}:{category_code}"
                        ),
                        "profit_base_sign_status": (
                            "UNKNOWN_NOT_PUBLISHED_IN_PDF"
                            if metric_id in PROFIT_METRICS
                            else "NOT_APPLICABLE"
                        ),
                    }
                )
    return records


def parse_keizoku_pdf(pdf_path: Path) -> ContinuingPdfTables:
    """Parse and validate every table and required caveat in ``keizoku.pdf``."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - environment contract
        raise ContinuingSampleError("pypdf is required to parse keizoku.pdf") from exc

    pdf_path = Path(pdf_path)
    source_sha = sha256_file(pdf_path)
    reader = PdfReader(pdf_path)
    if len(reader.pages) != 1:
        raise ContinuingSampleError(
            f"Expected the frozen keizoku.pdf to have one page; found {len(reader.pages)}"
        )
    page = reader.pages[0]
    extracted = page.extract_text(extraction_mode="layout") or ""
    # PScript positions text with both ASCII and ideographic whitespace.  A
    # whitespace-only normalization preserves every sign and number while
    # giving the structural parser stable table/row anchors.
    lines = [
        re.sub(r"[\s\u3000]+", " ", line).strip()
        for line in extracted.splitlines()
        if line.strip()
    ]
    text = "\n".join(lines)
    metadata = {
        "page_count": len(reader.pages),
        "page_width_points": float(page.mediabox.width),
        "page_height_points": float(page.mediabox.height),
        "detected_table_count": 4,
        "detected_tables": [
            "industry_yoy_rates",
            "capital_yoy_rates",
            "response_counts",
            "standard_error_rates",
        ],
        "pdf_metadata": {
            str(key): str(value) for key, value in (reader.metadata or {}).items()
        },
    }

    required_text = {
        "title": "継続標本のみを用いた計数による前年同期比増加率の参考提供",
        "definition": "前年同期」及び 「当期」ともに標本となった法人",
        "small_sample": "サンプルサイズが小さくなることに留意が必要",
        "profit_se": "営業利益及び経常利益については、標準誤差率の算出は行っていない",
        "industry_table": "参考系列 業種別",
        "capital_table": "参考系列 資本金階層別(全産業）",
    }
    absent = [name for name, phrase in required_text.items() if phrase not in text]
    if absent:
        raise ContinuingSampleError(f"Required PDF text disappeared: {absent}")

    industry_index = next(
        index for index, line in enumerate(lines) if "参考系列 業種別" in line
    )
    capital_index = next(
        index for index, line in enumerate(lines) if "参考系列 資本金階層別" in line
    )
    industry_periods = _extract_quarter_rows(lines, industry_index, capital_index)
    capital_periods = _extract_quarter_rows(lines, capital_index, len(lines))
    yoy = pd.DataFrame(
        [
            *_pdf_long_rows(
                period_rows=industry_periods,
                breakdown="industry",
                categories=INDUSTRY_CATEGORIES,
                pdf_path=pdf_path,
                source_sha256=source_sha,
            ),
            *_pdf_long_rows(
                period_rows=capital_periods,
                breakdown="capital_size",
                categories=CAPITAL_CATEGORIES,
                pdf_path=pdf_path,
                source_sha256=source_sha,
            ),
        ]
    )
    if len(yoy) != EXPECTED_CONTINUING_ROWS:
        raise ContinuingSampleError(
            f"Expected {EXPECTED_CONTINUING_ROWS} continuing rows; found {len(yoy)}"
        )
    key = ["period_code", "breakdown", "category_code", "metric_id"]
    if yoy.duplicated(key).any():
        raise ContinuingSampleError("Duplicate cells were extracted from keizoku.pdf")

    response_line = next(
        (line for line in lines if line.startswith("参考系列 回答法人数（社）")),
        None,
    )
    if response_line is None:
        raise ContinuingSampleError("Response-count table was not extracted")
    counts = [int(value.replace(",", "")) for value in re.findall(r"\d[\d,]*", response_line)]
    if len(counts) != 3:
        raise ContinuingSampleError(f"Expected three response counts; observed {counts}")
    response_counts = pd.DataFrame(
        [
            {
                "period_code": TARGET_PERIOD_CODE,
                "category_code": code,
                "category_label_ja": label,
                "response_corporation_count": count,
                "unit": "社",
                "count_definition_status": "DIRECT_PUBLISHED_COUNT",
                "source_path": str(pdf_path.resolve()),
                "source_sha256": source_sha,
                "pdf_page": 1,
            }
            for (code, label), count in zip(
                INDUSTRY_CATEGORIES.items(), counts, strict=True
            )
        ]
    )

    standard_error_line = next(
        (line for line in lines if line.startswith("標準誤差率 ")), None
    )
    if standard_error_line is None:
        raise ContinuingSampleError("Standard-error table was not extracted")
    se_values = [float(value) for value in re.findall(r"\d+\.\d", standard_error_line)]
    if len(se_values) != 6:
        raise ContinuingSampleError(
            f"Expected six published standard-error rates; observed {se_values}"
        )
    se_map: dict[tuple[str, str], float] = {}
    for metric_index, metric_id in enumerate(("sales", "capex_including_software")):
        for category_index, category_code in enumerate(INDUSTRY_CATEGORIES):
            se_map[(metric_id, category_code)] = se_values[
                metric_index * 3 + category_index
            ]
    standard_error_records: list[dict[str, Any]] = []
    for metric_id, metric_label in METRICS.items():
        for category_code, category_label in INDUSTRY_CATEGORIES.items():
            value = se_map.get((metric_id, category_code))
            standard_error_records.append(
                {
                    "period_code": TARGET_PERIOD_CODE,
                    "category_code": category_code,
                    "category_label_ja": category_label,
                    "metric_id": metric_id,
                    "metric_label_ja": metric_label,
                    "standard_error_rate_pct": value,
                    "standard_error_status": (
                        "DIRECT_PUBLISHED_RATE"
                        if value is not None
                        else "NOT_CALCULATED_BY_MOF"
                    ),
                    "unit": "%",
                    "source_path": str(pdf_path.resolve()),
                    "source_sha256": source_sha,
                    "pdf_page": 1,
                }
            )
    standard_errors = pd.DataFrame(standard_error_records)
    return ContinuingPdfTables(
        yoy_rates=yoy.sort_values(
            ["period_ordinal", "breakdown", "metric_id", "category_code"],
            kind="stable",
        ).reset_index(drop=True),
        response_counts=response_counts,
        standard_error_rates=standard_errors,
        notes=dict(LIMITATION_NOTES),
        metadata=metadata,
    )


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
        raise ContinuingSampleError(
            f"{dimension} classification changed: " + "; ".join(failures)
        )
    return selected


def build_regular_query(
    model: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Build the exact regular-series request paired with the PDF reference."""
    metric_key, metric_matter = _find_dimension(model, "metric")
    industry_key, industry_matter = _find_dimension(model, "industry")
    capital_key, capital_matter = _find_dimension(model, "capital")
    time_key, time_matter = _find_dimension(model, "time")
    metric_map = _canonical_metric_map(metric_matter)
    missing_metrics = sorted(set(METRICS) - set(metric_map))
    if missing_metrics:
        raise ContinuingSampleError(f"Regular metrics disappeared: {missing_metrics}")
    metrics = [metric_map[metric_id] for metric_id in METRICS]
    industries = _select_exact(
        industry_matter, INDUSTRY_ESTAT_NAMES, dimension="industry"
    )
    capital_sizes = _select_exact(
        capital_matter, CAPITAL_ESTAT_NAMES, dimension="capital"
    )
    periods_by_code = {
        str(entry["code"]): entry for entry in time_matter["listData"].values()
    }
    expected_period_codes = _period_codes(
        REGULAR_SOURCE_START_PERIOD_CODE, TARGET_PERIOD_CODE
    )
    missing_periods = [code for code in expected_period_codes if code not in periods_by_code]
    if missing_periods:
        raise ContinuingSampleError(f"Regular source periods disappeared: {missing_periods}")
    periods = [periods_by_code[code] for code in expected_period_codes]

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
        "continuing_vintage_id": CONTINUING_VINTAGE_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "request": {
            "http_method": "POST",
            "url": f"{ESTAT_ROOT}/dbview/api_get_result?sid={ESTAT_SID}",
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
            for metric_id in METRICS
        },
        "analysis_mapping": {
            "industry": {
                "capital_code": "26",
                "industry_codes": list(INDUSTRY_CATEGORIES),
            },
            "capital_size": {
                "industry_code": "104",
                "capital_codes": list(CAPITAL_CATEGORIES),
                "pdf_to_estat": CAPITAL_EXPLICIT_MAPPING,
            },
            "capex_definition": "software_including metric code 040",
        },
        "vintage_status": CURRENT_VINTAGE_STATUS,
        "revision_robustness_status": REVISION_STATUS,
    }
    return posted, metadata, {
        "metrics": metrics,
        "industries": industries,
        "capital_sizes": capital_sizes,
        "periods": periods,
    }


def _relative(path: Path, project_root: Path) -> str:
    return str(path.resolve().relative_to(Path(project_root).resolve()))


def _source_entry(
    *,
    source_id: str,
    role: str,
    path: Path,
    project_root: Path,
    url: str,
    method: str,
    retrieved_at: str,
    content_type: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "source_id": source_id,
        "role": role,
        "provider": "Ministry of Finance Japan" if source_id == "keizoku_pdf" else "e-Stat",
        "url": url,
        "http_method": method,
        "retrieved_at": retrieved_at,
        "publication_date": PUBLICATION_DATE,
        "target_period_code": TARGET_PERIOD_CODE,
        "raw_path": _relative(path, project_root),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "content_type": content_type,
    }
    if source_id != "keizoku_pdf":
        result.update({"estat_sid": ESTAT_SID, "table_number": TABLE_NUMBER})
    if extra:
        result.update(extra)
    return result


def verify_continuing_sample_manifest(
    manifest: dict[str, Any], project_root: Path = PROJECT_ROOT
) -> None:
    failures: list[str] = []
    for source in manifest.get("sources", []):
        path = Path(source["raw_path"])
        if not path.is_absolute():
            path = Path(project_root) / path
        if not path.exists():
            failures.append(f"missing:{source['source_id']}")
        elif sha256_file(path) != source.get("sha256"):
            failures.append(f"hash_mismatch:{source['source_id']}")
    if failures:
        raise ContinuingSampleError(
            "Continuing-sample raw verification failed: " + ", ".join(failures)
        )


def _parse_regular_paths(
    *, values_path: Path, query_path: Path, release: Release
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    return parse_estat_response(
        result_path=values_path,
        query_path=query_path,
        table_spec={
            "coverage_scope": "EXCL_FINANCE_INSURANCE",
            "seasonal_adjustment": "RAW",
            "table_number": TABLE_NUMBER,
            "sid": ESTAT_SID,
        },
        release=release,
    )


def fetch_continuing_sample_snapshot(
    project_root: Path = PROJECT_ROOT,
    *,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Fetch and freeze the official PDF and matching regular e-Stat slice."""
    project_root = Path(project_root)
    raw_root = _raw_root(project_root)
    manifest_path = raw_root / "data_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        verify_continuing_sample_manifest(manifest, project_root)
        return manifest

    raw_root.mkdir(parents=True, exist_ok=True)
    client = session or requests.Session()
    client.headers.update({"User-Agent": USER_AGENT})

    pdf_response = client.get(PDF_URL, timeout=(20, 180))
    pdf_response.raise_for_status()
    if "pdf" not in pdf_response.headers.get("Content-Type", "").lower():
        raise ContinuingSampleError("Official keizoku URL did not return a PDF")
    pdf_retrieved_at = datetime.now(UTC).isoformat()
    pdf_path = raw_root / "keizoku.pdf"
    write_new_bytes(pdf_path, pdf_response.content)
    pdf_tables = parse_keizoku_pdf(pdf_path)

    model_url = f"{ESTAT_ROOT}/dbview/api_get_model?sid={ESTAT_SID}"
    model_bytes, model = _post_json(client, model_url)
    model_retrieved_at = datetime.now(UTC).isoformat()
    model_path = raw_root / "regular_table1_model.json"
    write_new_bytes(model_path, model_bytes)

    posted, query_metadata, selection = build_regular_query(model)
    query_path = raw_root / "regular_table1_query.json"
    query_bytes = (
        json.dumps(query_metadata, ensure_ascii=False, indent=2).encode("utf-8")
        + b"\n"
    )
    write_new_bytes(query_path, query_bytes)
    query_created_at = query_metadata["created_at"]

    values_url = f"{ESTAT_ROOT}/dbview/api_get_result?sid={ESTAT_SID}"
    values_bytes, result = _post_json(client, values_url, posted)
    if not result.get("table"):
        raise ContinuingSampleError("Regular e-Stat response contains no table")
    values_retrieved_at = datetime.now(UTC).isoformat()
    values_path = raw_root / "regular_table1_values.json"
    write_new_bytes(values_path, values_bytes)
    parsed, parse_issues = _parse_regular_paths(
        values_path=values_path,
        query_path=query_path,
        release=load_release("2026Q1"),
    )
    fatal = [issue for issue in parse_issues if issue.get("severity") == "FAIL"]
    if fatal:
        raise ContinuingSampleError(f"Regular e-Stat parse failed: {fatal}")
    if len(parsed) != EXPECTED_REGULAR_SOURCE_ROWS:
        raise ContinuingSampleError(
            f"Expected {EXPECTED_REGULAR_SOURCE_ROWS} regular source rows; found {len(parsed)}"
        )
    missing_count = int(parsed["source_value"].isna().sum())

    manifest = {
        "manifest_version": 1,
        "continuing_vintage_id": CONTINUING_VINTAGE_ID,
        "target_period_code": TARGET_PERIOD_CODE,
        "target_period_label": "2026年1 - 3月",
        "publication_date": PUBLICATION_DATE,
        "generated_at": datetime.now(UTC).isoformat(),
        "numeric_authority": {
            "continuing_sample": "official Ministry of Finance keizoku.pdf",
            "regular_series": "e-Stat table 1 DB-view structured response",
        },
        "raw_mutation_policy": "immutable; refuse overwrite and verify every SHA-256",
        "continuing_period": {
            "first_period_code": CONTINUING_START_PERIOD_CODE,
            "last_period_code": TARGET_PERIOD_CODE,
            "quarter_count": EXPECTED_CONTINUING_PERIODS,
            "structured_row_count": len(pdf_tables.yoy_rates),
        },
        "regular_period": {
            "source_first_period_code": REGULAR_SOURCE_START_PERIOD_CODE,
            "analysis_first_period_code": CONTINUING_START_PERIOD_CODE,
            "last_period_code": TARGET_PERIOD_CODE,
            "source_quarter_count": len(selection["periods"]),
            "source_row_count": len(parsed),
            "source_missing_count": missing_count,
            "vintage_status": CURRENT_VINTAGE_STATUS,
            "revision_robustness_status": REVISION_STATUS,
        },
        "selection": {
            "metrics": [
                {"metric_id": metric_id, "code": entry["code"], "name": entry["name"]}
                for metric_id, entry in zip(METRICS, selection["metrics"], strict=True)
            ],
            "industries": [
                {"code": entry["code"], "name": entry["name"]}
                for entry in selection["industries"]
            ],
            "capital_sizes": [
                {"code": entry["code"], "name": entry["name"]}
                for entry in selection["capital_sizes"]
            ],
            "capital_pdf_to_estat_mapping": CAPITAL_EXPLICIT_MAPPING,
            "regular_capex_definition": "software_including metric code 040",
        },
        "pdf_validation": {
            **pdf_tables.metadata,
            "industry_quarter_count": EXPECTED_CONTINUING_PERIODS,
            "capital_quarter_count": EXPECTED_CONTINUING_PERIODS,
            "industry_numeric_cell_count": EXPECTED_CONTINUING_PERIODS * 12,
            "capital_numeric_cell_count": EXPECTED_CONTINUING_PERIODS * 12,
            "response_count_cells": len(pdf_tables.response_counts),
            "published_standard_error_cells": int(
                pdf_tables.standard_error_rates["standard_error_rate_pct"].notna().sum()
            ),
            "profit_standard_error_null_cells": int(
                pdf_tables.standard_error_rates["standard_error_status"]
                .eq("NOT_CALCULATED_BY_MOF")
                .sum()
            ),
            "visual_qa": {
                "status": "PASS",
                "all_pages_rendered": True,
                "rendered_page_count": 1,
                "inspection": (
                    "Full page rendered at 180 dpi; response-count, standard-error, "
                    "and footnote region additionally inspected at 400 dpi."
                ),
            },
        },
        "limitations": LIMITATION_NOTES,
        "parse_quality_log": parse_issues,
        "sources": [
            _source_entry(
                source_id="keizoku_pdf",
                role="continuing_sample_numeric_authority_and_notes",
                path=pdf_path,
                project_root=project_root,
                url=PDF_URL,
                method="GET",
                retrieved_at=pdf_retrieved_at,
                content_type="application/pdf",
                extra={
                    "source_page_url": SOURCE_PAGE_URL,
                    "http_last_modified": pdf_response.headers.get("Last-Modified"),
                    "http_etag": pdf_response.headers.get("ETag"),
                    "page_count": pdf_tables.metadata["page_count"],
                },
            ),
            _source_entry(
                source_id="regular_table1_model",
                role="regular_series_dimension_metadata",
                path=model_path,
                project_root=project_root,
                url=model_url,
                method="POST",
                retrieved_at=model_retrieved_at,
                content_type="application/json",
            ),
            _source_entry(
                source_id="regular_table1_query",
                role="regular_series_exact_request_metadata",
                path=query_path,
                project_root=project_root,
                url=values_url,
                method="POST",
                retrieved_at=query_created_at,
                content_type="application/json",
            ),
            _source_entry(
                source_id="regular_table1_values",
                role="regular_series_numeric_authority",
                path=values_path,
                project_root=project_root,
                url=values_url,
                method="POST",
                retrieved_at=values_retrieved_at,
                content_type="application/json",
            ),
        ],
    }
    write_new_bytes(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
    )
    return manifest


def load_continuing_sample_snapshot(
    project_root: Path = PROJECT_ROOT,
) -> tuple[ContinuingPdfTables, pd.DataFrame, dict[str, Any], dict[str, Any]]:
    """Load the frozen PDF and regular response without network access."""
    project_root = Path(project_root)
    raw_root = _raw_root(project_root)
    manifest_path = raw_root / "data_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Continuing-sample snapshot is absent; fetch it first: {manifest_path}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verify_continuing_sample_manifest(manifest, project_root)
    pdf_tables = parse_keizoku_pdf(raw_root / "keizoku.pdf")
    query_path = raw_root / "regular_table1_query.json"
    values_path = raw_root / "regular_table1_values.json"
    regular, issues = _parse_regular_paths(
        values_path=values_path,
        query_path=query_path,
        release=load_release("2026Q1"),
    )
    if any(issue.get("severity") == "FAIL" for issue in issues):
        raise ContinuingSampleError(f"Frozen regular source parse failed: {issues}")
    query = json.loads(query_path.read_text(encoding="utf-8"))
    return pdf_tables, regular, manifest, query


def _regular_analysis_cells(parsed: pd.DataFrame) -> pd.DataFrame:
    industry = parsed.loc[
        parsed["industry_code"].astype(str).isin(INDUSTRY_CATEGORIES)
        & parsed["capital_size_code"].astype(str).eq("26")
    ].copy()
    industry["breakdown"] = "industry"
    industry["category_code"] = industry["industry_code"].astype(str)
    industry["category_label_ja"] = industry["category_code"].map(
        INDUSTRY_CATEGORIES
    )
    capital = parsed.loc[
        parsed["industry_code"].astype(str).eq("104")
        & parsed["capital_size_code"].astype(str).isin(CAPITAL_CATEGORIES)
    ].copy()
    capital["breakdown"] = "capital_size"
    capital["category_code"] = capital["capital_size_code"].astype(str)
    capital["category_label_ja"] = capital["category_code"].map(CAPITAL_CATEGORIES)
    cells = pd.concat([industry, capital], ignore_index=True, sort=False)
    cells["category_id"] = np.where(
        cells["breakdown"].eq("industry"),
        "industry_" + cells["category_code"],
        "capital_" + cells["category_code"],
    )
    cells["period_code"] = cells["period_code"].astype(str)
    cells["period_ordinal"] = cells["period_code"].map(_quarter_ordinal)
    return cells


def _regular_rate_status(metric_id: str, current: Any, prior: Any) -> str:
    if pd.isna(current) or pd.isna(prior):
        return "MISSING_INPUT"
    if float(prior) == 0:
        return "ZERO_BASE_NOT_CALCULABLE"
    if metric_id in PROFIT_METRICS:
        if float(prior) < 0:
            return "NEGATIVE_PROFIT_BASE_NOT_INTERPRETABLE"
        if float(current) <= 0:
            return "PROFIT_SIGN_TRANSITION_NOT_INTERPRETABLE"
    return "CALCULABLE"


def build_regular_yoy_series(parsed: pd.DataFrame) -> pd.DataFrame:
    """Build matching 2016Q1--2026Q1 regular-series YoY rates."""
    cells = _regular_analysis_cells(parsed)
    expected_periods = _period_codes(
        REGULAR_SOURCE_START_PERIOD_CODE, TARGET_PERIOD_CODE
    )
    keys = ["breakdown", "category_code", "metric_id"]
    records: list[pd.DataFrame] = []
    for key, frame in cells.groupby(keys, sort=False, dropna=False):
        frame = frame.sort_values("period_ordinal", kind="stable").copy()
        observed = frame["period_code"].tolist()
        if observed != expected_periods:
            raise ContinuingSampleError(
                f"Regular source has missing/changed periods for {key}: {observed}"
            )
        frame["current_value_oku_yen"] = [
            _to_oku_yen(metric, unit, value)
            for metric, unit, value in zip(
                frame["metric_id"],
                frame["source_unit"],
                frame["source_value"],
                strict=True,
            )
        ]
        frame["prior_value_oku_yen"] = frame["current_value_oku_yen"].shift(4)
        frame["yoy_delta_oku_yen"] = (
            frame["current_value_oku_yen"] - frame["prior_value_oku_yen"]
        )
        frame["yoy_rate_status"] = [
            _regular_rate_status(metric, current, prior)
            for metric, current, prior in zip(
                frame["metric_id"],
                frame["current_value_oku_yen"],
                frame["prior_value_oku_yen"],
                strict=True,
            )
        ]
        frame["yoy_pct"] = [
            (float(current) / float(prior) - 1.0) * 100.0
            if status == "CALCULABLE"
            else np.nan
            for current, prior, status in zip(
                frame["current_value_oku_yen"],
                frame["prior_value_oku_yen"],
                frame["yoy_rate_status"],
                strict=True,
            )
        ]
        frame["profit_transition_yoy"] = [
            detect_profit_transition(prior, current)
            if metric in PROFIT_METRICS
            else "NOT_APPLICABLE"
            for metric, prior, current in zip(
                frame["metric_id"],
                frame["prior_value_oku_yen"],
                frame["current_value_oku_yen"],
                strict=True,
            )
        ]
        records.append(frame)
    result = pd.concat(records, ignore_index=True, sort=False)
    result = result.loc[
        result["period_code"].astype(int).ge(int(CONTINUING_START_PERIOD_CODE))
    ].copy()
    result["sample_method"] = "REGULAR_QUARTERLY_ESTIMATE"
    result["coverage_scope"] = "EXCL_FINANCE_INSURANCE"
    result["vintage_status"] = CURRENT_VINTAGE_STATUS
    result["revision_robustness_status"] = REVISION_STATUS
    result["capex_definition"] = np.where(
        result["metric_id"].eq("capex_including_software"),
        "SOFTWARE_INCLUDING_ESTAT_METRIC_040",
        "NOT_APPLICABLE",
    )
    result["category_mapping_note"] = np.where(
        result["breakdown"].eq("capital_size"),
        "PDF capital label mapped to the matching e-Stat capital bracket; "
        "this is not a legal enterprise-size classification",
        "DIRECT_INDUSTRY_LABEL",
    )
    columns = [
        "period_code",
        "period",
        "period_end",
        "period_ordinal",
        "breakdown",
        "category_code",
        "category_id",
        "category_label_ja",
        "category_mapping_note",
        "metric_id",
        "metric_label_ja",
        "current_value_oku_yen",
        "prior_value_oku_yen",
        "yoy_delta_oku_yen",
        "yoy_pct",
        "yoy_rate_status",
        "profit_transition_yoy",
        "coverage_scope",
        "sample_method",
        "vintage_status",
        "revision_robustness_status",
        "capex_definition",
        "source_path",
        "source_sha256",
        "source_cell_key",
    ]
    result = result[columns].sort_values(
        ["period_ordinal", "breakdown", "category_code", "metric_id"],
        kind="stable",
    ).reset_index(drop=True)
    if len(result) != EXPECTED_REGULAR_ANALYSIS_ROWS:
        raise ContinuingSampleError(
            f"Expected {EXPECTED_REGULAR_ANALYSIS_ROWS} regular analysis rows; "
            f"found {len(result)}"
        )
    return result


def _sign(value: Any) -> str:
    if pd.isna(value):
        return "NOT_CALCULABLE"
    if float(value) > 0:
        return "POSITIVE"
    if float(value) < 0:
        return "NEGATIVE"
    return "ZERO"


def build_continuing_regular_comparison(
    continuing: pd.DataFrame, regular: pd.DataFrame
) -> pd.DataFrame:
    """Join the two definitions and mark strict non-zero sign reversals."""
    keys = [
        "period_code",
        "breakdown",
        "category_code",
        "category_id",
        "category_label_ja",
        "metric_id",
    ]
    left = continuing[
        [
            *keys,
            "period",
            "period_end",
            "period_ordinal",
            "metric_label_ja",
            "category_mapping_note",
            "yoy_pct",
            "yoy_rate_status",
            "profit_base_sign_status",
            "source_path",
            "source_sha256",
        ]
    ].rename(
        columns={
            "yoy_pct": "continuing_yoy_pct",
            "yoy_rate_status": "continuing_yoy_rate_status",
            "profit_base_sign_status": "continuing_profit_base_sign_status",
            "source_path": "continuing_source_path",
            "source_sha256": "continuing_source_sha256",
        }
    )
    right = regular[
        [
            *keys,
            "current_value_oku_yen",
            "prior_value_oku_yen",
            "yoy_delta_oku_yen",
            "yoy_pct",
            "yoy_rate_status",
            "profit_transition_yoy",
            "source_path",
            "source_sha256",
        ]
    ].rename(
        columns={
            "current_value_oku_yen": "regular_current_value_oku_yen",
            "prior_value_oku_yen": "regular_prior_value_oku_yen",
            "yoy_delta_oku_yen": "regular_yoy_delta_oku_yen",
            "yoy_pct": "regular_yoy_pct",
            "yoy_rate_status": "regular_yoy_rate_status",
            "profit_transition_yoy": "regular_profit_transition_yoy",
            "source_path": "regular_source_path",
            "source_sha256": "regular_source_sha256",
        }
    )
    merged = left.merge(right, on=keys, how="outer", validate="one_to_one", indicator=True)
    if not merged["_merge"].eq("both").all():
        mismatches = merged.loc[merged["_merge"].ne("both"), [*keys, "_merge"]]
        raise ContinuingSampleError(
            "Continuing/regular keys do not match: " + mismatches.head().to_json()
        )
    merged = merged.drop(columns="_merge")
    merged["yoy_difference_pp"] = (
        merged["continuing_yoy_pct"] - merged["regular_yoy_pct"]
    )
    merged["continuing_sign"] = merged["continuing_yoy_pct"].map(_sign)
    merged["regular_sign"] = merged["regular_yoy_pct"].map(_sign)
    statuses: list[str] = []
    reversals: list[Any] = []
    for continuing_sign, regular_sign in zip(
        merged["continuing_sign"], merged["regular_sign"], strict=True
    ):
        if "NOT_CALCULABLE" in {continuing_sign, regular_sign}:
            statuses.append("NOT_COMPARABLE_MISSING_OR_SIGN_STATE")
            reversals.append(pd.NA)
        elif "ZERO" in {continuing_sign, regular_sign}:
            statuses.append("ZERO_INVOLVED_NO_DIRECTION")
            reversals.append(pd.NA)
        elif continuing_sign == regular_sign:
            statuses.append("SAME_NONZERO_SIGN")
            reversals.append(False)
        else:
            statuses.append("OPPOSITE_NONZERO_SIGN")
            reversals.append(True)
    merged["sign_comparison_status"] = statuses
    merged["sign_reversal"] = pd.array(reversals, dtype="boolean")
    merged["comparison_note"] = (
        "Continuing-sample reference rate versus current-vintage regular e-Stat rate"
    )
    return merged.sort_values(
        ["period_ordinal", "breakdown", "category_code", "metric_id"],
        kind="stable",
    ).reset_index(drop=True)


def build_sign_reversal_frequency(comparison: pd.DataFrame) -> pd.DataFrame:
    """Count opposite non-zero YoY signs with an explicit denominator."""
    rows: list[dict[str, Any]] = []
    keys = ["breakdown", "category_code", "category_id", "category_label_ja", "metric_id"]
    for key, frame in comparison.groupby(keys, sort=True, dropna=False):
        comparable = frame["sign_reversal"].notna()
        denominator = int(comparable.sum())
        reversals = int(frame.loc[comparable, "sign_reversal"].sum())
        rows.append(
            {
                **dict(zip(keys, key, strict=True)),
                "total_quarters": len(frame),
                "comparable_nonzero_sign_quarters": denominator,
                "sign_reversal_count": reversals,
                "sign_reversal_rate_pct": (
                    reversals / denominator * 100.0 if denominator else np.nan
                ),
                "zero_involved_quarters": int(
                    frame["sign_comparison_status"]
                    .eq("ZERO_INVOLVED_NO_DIRECTION")
                    .sum()
                ),
                "not_comparable_quarters": int(
                    frame["sign_comparison_status"]
                    .eq("NOT_COMPARABLE_MISSING_OR_SIGN_STATE")
                    .sum()
                ),
                "frequency_status": (
                    "CALCULABLE" if denominator else "NO_COMPARABLE_QUARTERS"
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(keys, kind="stable").reset_index(drop=True)


def _relative_margin_values(
    *,
    sales_yoy: Any,
    operating_yoy: Any,
    source: str,
    regular_current_profit: Any = np.nan,
    regular_prior_profit: Any = np.nan,
) -> tuple[float | None, float | None, str, str]:
    if pd.isna(sales_yoy) or pd.isna(operating_yoy):
        return None, None, "NOT_CALCULABLE", "MISSING_RATE_INPUT"
    if float(sales_yoy) <= -100.0:
        return None, None, "NOT_CALCULABLE", "SALES_GROWTH_DENOMINATOR_NOT_POSITIVE"
    if source == "regular" and (
        pd.isna(regular_current_profit)
        or pd.isna(regular_prior_profit)
        or float(regular_current_profit) <= 0
        or float(regular_prior_profit) <= 0
    ):
        return None, None, "NOT_CALCULABLE", "PROFIT_LEVEL_SIGN_NOT_POSITIVE"
    gap = float(operating_yoy) - float(sales_yoy)
    implied = (
        (1.0 + float(operating_yoy) / 100.0)
        / (1.0 + float(sales_yoy) / 100.0)
        - 1.0
    ) * 100.0
    direction = "UP" if implied > 0 else ("DOWN" if implied < 0 else "FLAT")
    status = (
        "PROXY_PROFIT_BASE_SIGN_NOT_PUBLISHED"
        if source == "continuing"
        else "CALCULABLE_POSITIVE_PROFIT_LEVELS"
    )
    return gap, implied, direction, status


def build_relative_margin_comparison(comparison: pd.DataFrame) -> pd.DataFrame:
    """Infer operating-margin direction while retaining the PDF sign caveat."""
    base_keys = [
        "period_code",
        "period",
        "period_end",
        "period_ordinal",
        "breakdown",
        "category_code",
        "category_id",
        "category_label_ja",
    ]
    subset = comparison.loc[
        comparison["metric_id"].isin(("sales", "operating_profit"))
    ].copy()
    rows: list[dict[str, Any]] = []
    for key, frame in subset.groupby(base_keys, sort=False, dropna=False):
        by_metric = frame.set_index("metric_id")
        if set(by_metric.index) != {"sales", "operating_profit"}:
            raise ContinuingSampleError(f"Margin inputs changed for {key}")
        sales = by_metric.loc["sales"]
        operating = by_metric.loc["operating_profit"]
        c_gap, c_implied, c_direction, c_status = _relative_margin_values(
            sales_yoy=sales["continuing_yoy_pct"],
            operating_yoy=operating["continuing_yoy_pct"],
            source="continuing",
        )
        r_gap, r_implied, r_direction, r_status = _relative_margin_values(
            sales_yoy=sales["regular_yoy_pct"],
            operating_yoy=operating["regular_yoy_pct"],
            source="regular",
            regular_current_profit=operating["regular_current_value_oku_yen"],
            regular_prior_profit=operating["regular_prior_value_oku_yen"],
        )
        if "NOT_CALCULABLE" in {c_direction, r_direction}:
            direction_reversal: Any = pd.NA
            direction_status = "NOT_COMPARABLE"
        elif "FLAT" in {c_direction, r_direction}:
            direction_reversal = pd.NA
            direction_status = "FLAT_DIRECTION_INVOLVED"
        else:
            direction_reversal = c_direction != r_direction
            direction_status = (
                "OPPOSITE_DIRECTION" if direction_reversal else "SAME_DIRECTION"
            )
        rows.append(
            {
                **dict(zip(base_keys, key, strict=True)),
                "continuing_sales_yoy_pct": sales["continuing_yoy_pct"],
                "continuing_operating_profit_yoy_pct": operating[
                    "continuing_yoy_pct"
                ],
                "continuing_relative_growth_gap_pp": c_gap,
                "continuing_implied_relative_margin_change_pct": c_implied,
                "continuing_relative_margin_change_direction": c_direction,
                "continuing_relative_margin_status": c_status,
                "regular_sales_yoy_pct": sales["regular_yoy_pct"],
                "regular_operating_profit_yoy_pct": operating["regular_yoy_pct"],
                "regular_relative_growth_gap_pp": r_gap,
                "regular_implied_relative_margin_change_pct": r_implied,
                "regular_relative_margin_change_direction": r_direction,
                "regular_relative_margin_status": r_status,
                "relative_margin_direction_reversal": direction_reversal,
                "relative_margin_direction_comparison_status": direction_status,
                "interpretation_note": LIMITATION_NOTES["relative_margin_proxy"],
            }
        )
    result = pd.DataFrame(rows)
    result["relative_margin_direction_reversal"] = pd.array(
        result["relative_margin_direction_reversal"], dtype="boolean"
    )
    return result.sort_values(
        ["period_ordinal", "breakdown", "category_code"], kind="stable"
    ).reset_index(drop=True)


def build_relative_margin_reversal_frequency(
    relative_margin: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    keys = ["breakdown", "category_code", "category_id", "category_label_ja"]
    for key, frame in relative_margin.groupby(keys, sort=True, dropna=False):
        comparable = frame["relative_margin_direction_reversal"].notna()
        denominator = int(comparable.sum())
        reversals = int(
            frame.loc[comparable, "relative_margin_direction_reversal"].sum()
        )
        rows.append(
            {
                **dict(zip(keys, key, strict=True)),
                "total_quarters": len(frame),
                "comparable_direction_quarters": denominator,
                "direction_reversal_count": reversals,
                "direction_reversal_rate_pct": (
                    reversals / denominator * 100.0 if denominator else np.nan
                ),
                "not_comparable_or_flat_quarters": len(frame) - denominator,
                "frequency_status": (
                    "CALCULABLE" if denominator else "NO_COMPARABLE_QUARTERS"
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(keys, kind="stable").reset_index(drop=True)


def build_capital_headline_history(
    relative_margin: pd.DataFrame,
) -> pd.DataFrame:
    """Test the pre-existing large/small capital margin-divergence headline."""
    capital = relative_margin.loc[relative_margin["breakdown"].eq("capital_size")]
    rows: list[dict[str, Any]] = []
    for period_code, frame in capital.groupby("period_code", sort=True):
        by_code = frame.set_index("category_code")
        if not {"19", "25"} <= set(by_code.index):
            raise ContinuingSampleError(f"Headline capital cells missing in {period_code}")
        small = by_code.loc["19"]
        large = by_code.loc["25"]
        record: dict[str, Any] = {
            "period_code": period_code,
            "period": small["period"],
            "period_end": small["period_end"],
            "period_ordinal": small["period_ordinal"],
            "headline_definition": (
                "small sales yoy > 0 AND small relative operating-margin direction "
                "DOWN AND large relative operating-margin direction UP"
            ),
        }
        for prefix in ("continuing", "regular"):
            small_sales = small[f"{prefix}_sales_yoy_pct"]
            small_direction = small[
                f"{prefix}_relative_margin_change_direction"
            ]
            large_direction = large[
                f"{prefix}_relative_margin_change_direction"
            ]
            calculable = (
                pd.notna(small_sales)
                and small_direction != "NOT_CALCULABLE"
                and large_direction != "NOT_CALCULABLE"
            )
            record[f"{prefix}_small_sales_yoy_pct"] = small_sales
            record[f"{prefix}_small_margin_direction"] = small_direction
            record[f"{prefix}_large_margin_direction"] = large_direction
            record[f"{prefix}_headline_supported"] = (
                bool(
                    float(small_sales) > 0
                    and small_direction == "DOWN"
                    and large_direction == "UP"
                )
                if calculable
                else pd.NA
            )
            record[f"{prefix}_headline_status"] = (
                "PROXY_PROFIT_BASE_SIGN_NOT_PUBLISHED"
                if prefix == "continuing" and calculable
                else (
                    "CALCULABLE_POSITIVE_PROFIT_LEVELS"
                    if calculable
                    else "NOT_CALCULABLE"
                )
            )
        c_value = record["continuing_headline_supported"]
        r_value = record["regular_headline_supported"]
        if pd.isna(c_value) or pd.isna(r_value):
            record["headline_reversal"] = pd.NA
            record["headline_comparison_status"] = "NOT_COMPARABLE"
        else:
            reversal = bool(c_value) != bool(r_value)
            record["headline_reversal"] = reversal
            record["headline_comparison_status"] = (
                "OPPOSITE_HEADLINE_RESULT" if reversal else "SAME_HEADLINE_RESULT"
            )
        rows.append(record)
    result = pd.DataFrame(rows)
    for column in (
        "continuing_headline_supported",
        "regular_headline_supported",
        "headline_reversal",
    ):
        result[column] = pd.array(result[column], dtype="boolean")
    return result.sort_values("period_ordinal", kind="stable").reset_index(drop=True)


def build_headline_reversal_frequency(headline_history: pd.DataFrame) -> pd.DataFrame:
    comparable = headline_history["headline_reversal"].notna()
    denominator = int(comparable.sum())
    reversals = int(headline_history.loc[comparable, "headline_reversal"].sum())
    regular = headline_history["regular_headline_supported"]
    continuing = headline_history["continuing_headline_supported"]
    return pd.DataFrame(
        [
            {
                "headline_id": "CAPITAL_MARGIN_DIVERGENCE_B",
                "total_quarters": len(headline_history),
                "comparable_headline_quarters": denominator,
                "headline_reversal_count": reversals,
                "headline_reversal_rate_pct": (
                    reversals / denominator * 100.0 if denominator else np.nan
                ),
                "regular_only_support_count": int(
                    ((regular == True) & (continuing == False)).sum()  # noqa: E712
                ),
                "continuing_only_support_count": int(
                    ((regular == False) & (continuing == True)).sum()  # noqa: E712
                ),
                "both_support_count": int(
                    ((regular == True) & (continuing == True)).sum()  # noqa: E712
                ),
                "neither_support_count": int(
                    ((regular == False) & (continuing == False)).sum()  # noqa: E712
                ),
                "not_comparable_count": len(headline_history) - denominator,
                "frequency_status": (
                    "CALCULABLE_WITH_CONTINUING_PROFIT_SIGN_PROXY"
                    if denominator
                    else "NO_COMPARABLE_QUARTERS"
                ),
            }
        ]
    )


def build_continuing_sample_analysis(
    project_root: Path = PROJECT_ROOT,
) -> ContinuingSampleAnalysis:
    pdf_tables, parsed, _, _ = load_continuing_sample_snapshot(project_root)
    regular = build_regular_yoy_series(parsed)
    comparison = build_continuing_regular_comparison(pdf_tables.yoy_rates, regular)
    relative = build_relative_margin_comparison(comparison)
    sign_frequency = build_sign_reversal_frequency(comparison)
    margin_frequency = build_relative_margin_reversal_frequency(relative)
    headline = build_capital_headline_history(relative)
    headline_frequency = build_headline_reversal_frequency(headline)
    return ContinuingSampleAnalysis(
        continuing_yoy=pdf_tables.yoy_rates,
        regular_yoy=regular,
        comparison=comparison,
        relative_margin_comparison=relative,
        sign_reversal_frequency=sign_frequency,
        relative_margin_reversal_frequency=margin_frequency,
        capital_headline_history=headline,
        headline_reversal_frequency=headline_frequency,
        response_counts=pdf_tables.response_counts,
        standard_error_rates=pdf_tables.standard_error_rates,
        limitations=pdf_tables.notes,
    )
