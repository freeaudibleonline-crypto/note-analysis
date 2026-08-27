from __future__ import annotations

import json

import pytest

from corporate_quarterly.estat import write_new_bytes
from corporate_quarterly.estat import sha256_file
from corporate_quarterly.processing import _number_or_none, parse_estat_response


@pytest.mark.parametrize("marker", ["", "-", "―", "…", "X", "NA", "N/A", "＊"])
def test_source_missing_markers_are_never_zero_filled(marker: str) -> None:
    value, status = _number_or_none(marker)
    assert value is None
    assert status == "SOURCE_MISSING_MARKER"


def test_unparseable_source_value_is_missing_and_logged() -> None:
    value, status = _number_or_none("公表待ち")
    assert value is None
    assert status.startswith("UNPARSEABLE_SOURCE_VALUE:")


def test_raw_writer_refuses_overwrite_with_different_bytes(tmp_path) -> None:
    target = tmp_path / "raw.json"
    write_new_bytes(target, b'{"vintage": 1}')
    write_new_bytes(target, b'{"vintage": 1}')

    with pytest.raises(FileExistsError, match="Refusing to overwrite immutable raw artifact"):
        write_new_bytes(target, b'{"vintage": 2}')

    assert target.read_bytes() == b'{"vintage": 1}'


def test_classification_change_and_missing_cell_are_retained_in_quality_log(
    tmp_path, release
) -> None:
    result_path = tmp_path / "values.json"
    query_path = tmp_path / "query.json"
    result_path.write_text(
        json.dumps(
            {
                "table": (
                    "<table><thead><tr>"
                    '<th class="js-dbview-cols" data-unique="m1">売上高</th>'
                    "</tr></thead><tbody><tr>"
                    '<th class="js-dbview-rows" data-unique="20261@c1@i1">行</th>'
                    '<td class="stat-dbview-value">…</td>'
                    "</tr></tbody></table>"
                )
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    query_path.write_text(
        json.dumps(
            {
                "dimension_spec": {
                    "industry": [{"code": "i1", "name": "旧分類（H20年度まで）"}],
                    "capital": [{"code": "c1", "name": "全規模"}],
                    "time": [{"code": "20261", "name": "2026年1～3月"}],
                },
                "canonical_metric_map": {
                    "sales": {
                        "code": "m1",
                        "source_name": "売上高(当期末)",
                        "metric_label_ja": "売上高",
                        "source_unit": "百万円",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    frame, issues = parse_estat_response(
        result_path=result_path,
        query_path=query_path,
        table_spec={
            "coverage_scope": "EXCL_FINANCE_INSURANCE",
            "seasonal_adjustment": "RAW",
            "table_number": "1",
            "sid": "fixture",
        },
        release=release,
    )

    assert frame.loc[0, "source_value"] is None
    assert frame.loc[0, "missing_status"] == "SOURCE_MISSING_MARKER"
    assert {issue["kind"] for issue in issues} == {
        "MISSING_OR_UNPARSEABLE_VALUE",
        "INDUSTRY_CLASSIFICATION_CHANGE",
    }


def test_manifest_records_retrieval_and_table_provenance(project_root) -> None:
    manifest_path = project_root / "data" / "raw" / "2026Q1" / "data_manifest.json"
    assert manifest_path.exists(), "Run `make fetch` before the provenance contract test"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_policy"]["raw_mutation"].startswith("forbidden")
    assert manifest["sources"]
    for source in manifest["sources"]:
        assert source["retrieved_at"]
        assert source["url"].startswith("https://")
        assert source["publication_date"] == "2026-06-01"
        assert len(source["sha256"]) == 64
        if source["provider"] == "e-Stat":
            assert source["table_number"] in {"1", "2", "3", "4"}
            assert source["estat_sid"]


def test_legacy_query_metadata_hashes_are_pinned(project_root, release) -> None:
    raw_root = project_root / "data" / "raw" / release.release_id
    for source_key, table in release.e_stat_tables.items():
        expected = table.get("legacy_frozen_query_sha256")
        assert expected, source_key
        assert sha256_file(raw_root / f"{source_key}_query.json") == expected
