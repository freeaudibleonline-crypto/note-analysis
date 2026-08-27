from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from corporate_quarterly.estat import _find_dimension, sha256_file
from corporate_quarterly.stage2_continuing_sample import (
    CAPITAL_EXPLICIT_MAPPING,
    CONTINUING_VINTAGE_ID,
    CURRENT_VINTAGE_STATUS,
    EXPECTED_CONTINUING_ROWS,
    LIMITATION_NOTES,
    PDF_URL,
    REVISION_STATUS,
    ContinuingSampleError,
    _extract_quarter_rows,
    _regular_rate_status,
    _relative_margin_values,
    build_capital_headline_history,
    build_continuing_regular_comparison,
    build_continuing_sample_analysis,
    build_headline_reversal_frequency,
    build_regular_query,
    build_regular_yoy_series,
    build_relative_margin_comparison,
    build_relative_margin_reversal_frequency,
    build_sign_reversal_frequency,
    fetch_continuing_sample_snapshot,
    load_continuing_sample_snapshot,
    parse_keizoku_pdf,
    verify_continuing_sample_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = PROJECT_ROOT / "data" / "raw" / CONTINUING_VINTAGE_ID


@pytest.fixture(scope="module")
def snapshot():
    return load_continuing_sample_snapshot(PROJECT_ROOT)


@pytest.fixture(scope="module")
def pdf_tables(snapshot):
    return snapshot[0]


@pytest.fixture(scope="module")
def regular(snapshot) -> pd.DataFrame:
    return build_regular_yoy_series(snapshot[1])


@pytest.fixture(scope="module")
def comparison(pdf_tables, regular) -> pd.DataFrame:
    return build_continuing_regular_comparison(pdf_tables.yoy_rates, regular)


@pytest.fixture(scope="module")
def relative(comparison) -> pd.DataFrame:
    return build_relative_margin_comparison(comparison)


def _current_values(frame: pd.DataFrame, value_column: str) -> dict[tuple[str, str, str], float]:
    current = frame.loc[frame["period_code"].eq("20261")]
    return {
        (row.breakdown, str(row.category_code), row.metric_id): getattr(
            row, value_column
        )
        for row in current.itertuples(index=False)
    }


def test_manifest_freezes_official_pdf_and_matching_estat_sources(snapshot) -> None:
    _, parsed, manifest, query = snapshot
    verify_continuing_sample_manifest(manifest, PROJECT_ROOT)

    assert parsed.shape == (2160, 24)
    assert set(parsed["missing_status"]) == {"PRESENT"}
    assert manifest["target_period_code"] == "20261"
    assert manifest["publication_date"] == "2026-06-01"
    assert manifest["continuing_period"] == {
        "first_period_code": "20161",
        "last_period_code": "20261",
        "quarter_count": 41,
        "structured_row_count": 984,
    }
    assert manifest["regular_period"]["source_first_period_code"] == "20151"
    assert manifest["regular_period"]["source_quarter_count"] == 45
    assert manifest["regular_period"]["source_missing_count"] == 0
    assert manifest["selection"]["capital_pdf_to_estat_mapping"] == CAPITAL_EXPLICIT_MAPPING
    assert manifest["selection"]["regular_capex_definition"].startswith(
        "software_including"
    )

    sources = {source["source_id"]: source for source in manifest["sources"]}
    assert set(sources) == {
        "keizoku_pdf",
        "regular_table1_model",
        "regular_table1_query",
        "regular_table1_values",
    }
    assert sources["keizoku_pdf"]["url"] == PDF_URL
    assert sources["keizoku_pdf"]["sha256"] == (
        "0aa38ecb0dd6509bce70123955c2d9585e0143fab14ecd63be0dbc8cf7d996f6"
    )
    for source in sources.values():
        assert source["retrieved_at"]
        assert source["target_period_code"] == "20261"
        path = PROJECT_ROOT / source["raw_path"]
        assert path.exists()
        assert sha256_file(path) == source["sha256"]
        assert path.stat().st_size == source["bytes"]

    assert len(query["dimension_spec"]["time"]) == 45
    assert query["dimension_spec"]["time"][0]["code"] == "20151"
    assert query["dimension_spec"]["time"][-1]["code"] == "20261"
    assert query["analysis_mapping"]["capex_definition"].startswith(
        "software_including"
    )


def test_manifest_records_full_page_and_target_table_visual_qa(snapshot) -> None:
    manifest = snapshot[2]
    validation = manifest["pdf_validation"]
    assert validation["page_count"] == 1
    assert validation["detected_table_count"] == 4
    assert validation["industry_numeric_cell_count"] == 492
    assert validation["capital_numeric_cell_count"] == 492
    assert validation["response_count_cells"] == 3
    assert validation["published_standard_error_cells"] == 6
    assert validation["profit_standard_error_null_cells"] == 6
    assert validation["visual_qa"]["status"] == "PASS"
    assert validation["visual_qa"]["all_pages_rendered"] is True
    assert validation["visual_qa"]["rendered_page_count"] == 1


def test_existing_snapshot_fetch_is_strictly_offline() -> None:
    class NoNetworkSession:
        headers: dict[str, str] = {}

        def get(self, *args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("existing frozen snapshot must not use network")

        def post(self, *args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("existing frozen snapshot must not use network")

    manifest = fetch_continuing_sample_snapshot(
        PROJECT_ROOT, session=NoNetworkSession()
    )
    assert manifest["continuing_vintage_id"] == CONTINUING_VINTAGE_ID


def test_regular_query_uses_exact_codes_names_and_yoy_lag_period() -> None:
    model = json.loads((RAW_ROOT / "regular_table1_model.json").read_text())
    posted, metadata, selection = build_regular_query(model)
    assert [entry["code"] for entry in selection["industries"]] == [
        "104",
        "108",
        "144",
    ]
    assert [entry["code"] for entry in selection["capital_sizes"]] == [
        "26",
        "25",
        "24",
        "19",
    ]
    assert [entry["metric_id"] for entry in selection["metrics"]] == [
        "sales",
        "operating_profit",
        "ordinary_profit",
        "capex_including_software",
    ]
    assert len(selection["periods"]) == 45
    assert selection["periods"][0]["code"] == "20151"
    assert metadata["request"]["form_payload"] == posted
    assert metadata["request"]["url"].endswith("sid=0003060191")


def test_regular_query_rejects_code_name_reassignment() -> None:
    model = deepcopy(
        json.loads((RAW_ROOT / "regular_table1_model.json").read_text())
    )
    _, capital = _find_dimension(model, "capital")
    next(
        entry for entry in capital["listData"].values() if entry["code"] == "24"
    )["name"] = "changed bracket"
    with pytest.raises(ContinuingSampleError, match="classification changed"):
        build_regular_query(model)


def test_pdf_extracts_41_quarters_and_every_published_rate(pdf_tables) -> None:
    yoy = pdf_tables.yoy_rates
    assert yoy.shape[0] == EXPECTED_CONTINUING_ROWS
    assert yoy["period_code"].nunique() == 41
    assert yoy["period_code"].min() == "20161"
    assert yoy["period_code"].max() == "20261"
    assert yoy.groupby("period_code").size().eq(24).all()
    assert yoy.groupby("breakdown").size().to_dict() == {
        "capital_size": 492,
        "industry": 492,
    }
    assert not yoy.duplicated(
        ["period_code", "breakdown", "category_code", "metric_id"]
    ).any()
    assert yoy["yoy_pct"].notna().all()
    assert (
        yoy.loc[yoy["breakdown"].eq("capital_size"), "category_mapping_note"]
        .str.contains("not a legal")
        .all()
    )


def test_pdf_reproduces_all_2026q1_industry_and_capital_values(pdf_tables) -> None:
    actual = _current_values(pdf_tables.yoy_rates, "yoy_pct")
    expected = {
        ("industry", "104", "sales"): 2.4,
        ("industry", "108", "sales"): 5.4,
        ("industry", "144", "sales"): 1.2,
        ("industry", "104", "operating_profit"): 15.6,
        ("industry", "108", "operating_profit"): 42.9,
        ("industry", "144", "operating_profit"): 6.1,
        ("industry", "104", "ordinary_profit"): 19.0,
        ("industry", "108", "ordinary_profit"): 37.7,
        ("industry", "144", "ordinary_profit"): 10.0,
        ("industry", "104", "capex_including_software"): -0.6,
        ("industry", "108", "capex_including_software"): -1.7,
        ("industry", "144", "capex_including_software"): -0.1,
        ("capital_size", "25", "sales"): 2.6,
        ("capital_size", "24", "sales"): 2.0,
        ("capital_size", "19", "sales"): 2.5,
        ("capital_size", "25", "operating_profit"): 20.0,
        ("capital_size", "24", "operating_profit"): 22.4,
        ("capital_size", "19", "operating_profit"): 6.0,
        ("capital_size", "25", "ordinary_profit"): 26.0,
        ("capital_size", "24", "ordinary_profit"): 19.3,
        ("capital_size", "19", "ordinary_profit"): 8.6,
        ("capital_size", "25", "capex_including_software"): 1.1,
        ("capital_size", "24", "capex_including_software"): -3.8,
        ("capital_size", "19", "capex_including_software"): -2.9,
    }
    assert actual == expected
    historic_outlier = pdf_tables.yoy_rates.loc[
        pdf_tables.yoy_rates["period_code"].eq("20212")
        & pdf_tables.yoy_rates["breakdown"].eq("capital_size")
        & pdf_tables.yoy_rates["category_code"].eq("19")
        & pdf_tables.yoy_rates["metric_id"].eq("operating_profit"),
        "yoy_pct",
    ].item()
    assert historic_outlier == 3785.3


def test_response_counts_and_profit_standard_errors_are_not_zero_filled(
    pdf_tables,
) -> None:
    counts = pdf_tables.response_counts.set_index("category_code")
    assert counts["response_corporation_count"].to_dict() == {
        "104": 11908,
        "108": 3760,
        "144": 8148,
    }
    standard_errors = pdf_tables.standard_error_rates
    published = standard_errors.loc[
        standard_errors["standard_error_status"].eq("DIRECT_PUBLISHED_RATE")
    ]
    assert len(published) == 6
    expected = {
        ("sales", "104"): 2.0,
        ("sales", "108"): 1.8,
        ("sales", "144"): 2.7,
        ("capex_including_software", "104"): 2.2,
        ("capex_including_software", "108"): 2.1,
        ("capex_including_software", "144"): 3.1,
    }
    assert {
        (row.metric_id, str(row.category_code)): row.standard_error_rate_pct
        for row in published.itertuples(index=False)
    } == expected
    profits = standard_errors.loc[
        standard_errors["metric_id"].isin(
            ("operating_profit", "ordinary_profit")
        )
    ]
    assert len(profits) == 6
    assert profits["standard_error_rate_pct"].isna().all()
    assert set(profits["standard_error_status"]) == {"NOT_CALCULATED_BY_MOF"}
    assert "算出は行っていない" in pdf_tables.notes[
        "profit_standard_error"
    ]
    assert "サンプルサイズが小さく" in pdf_tables.notes["small_sample"]


def test_pdf_parser_fails_closed_on_missing_quarter() -> None:
    lines = [
        "2016 1～3月 " + " ".join(["1.0"] * 12),
        "2016 7～9月 " + " ".join(["1.0"] * 12),
    ]
    with pytest.raises(ContinuingSampleError, match="quarter sequence changed"):
        _extract_quarter_rows(lines, 0, len(lines))


def test_regular_series_reproduces_current_values_and_uses_software_including_capex(
    regular,
) -> None:
    assert regular.shape[0] == 984
    assert regular["period_code"].nunique() == 41
    assert set(regular["vintage_status"]) == {CURRENT_VINTAGE_STATUS}
    assert set(regular["revision_robustness_status"]) == {REVISION_STATUS}
    assert set(regular["yoy_rate_status"]) == {"CALCULABLE"}
    current = _current_values(regular, "yoy_pct")
    assert current[("capital_size", "25", "sales")] == pytest.approx(
        1.695835, abs=1e-6
    )
    assert current[("capital_size", "25", "operating_profit")] == pytest.approx(
        18.494685, abs=1e-6
    )
    assert current[("capital_size", "19", "sales")] == pytest.approx(
        2.100851, abs=1e-6
    )
    assert current[("capital_size", "19", "operating_profit")] == pytest.approx(
        -1.890184, abs=1e-6
    )
    assert current[("industry", "104", "ordinary_profit")] == pytest.approx(
        14.604056, abs=1e-6
    )
    capex = regular.loc[regular["metric_id"].eq("capex_including_software")]
    assert set(capex["capex_definition"]) == {
        "SOFTWARE_INCLUDING_ESTAT_METRIC_040"
    }


@pytest.mark.parametrize(
    ("metric", "current", "prior", "expected"),
    [
        ("sales", np.nan, 1.0, "MISSING_INPUT"),
        ("sales", 1.0, 0.0, "ZERO_BASE_NOT_CALCULABLE"),
        (
            "operating_profit",
            1.0,
            -1.0,
            "NEGATIVE_PROFIT_BASE_NOT_INTERPRETABLE",
        ),
        (
            "ordinary_profit",
            -1.0,
            1.0,
            "PROFIT_SIGN_TRANSITION_NOT_INTERPRETABLE",
        ),
        ("operating_profit", 2.0, 1.0, "CALCULABLE"),
    ],
)
def test_regular_profit_rate_status_is_sign_aware(
    metric: str, current: float, prior: float, expected: str
) -> None:
    assert _regular_rate_status(metric, current, prior) == expected


def test_comparison_marks_current_sign_reversals_without_treating_zero_as_sign(
    comparison,
) -> None:
    assert comparison.shape[0] == 984
    current = comparison.loc[comparison["period_code"].eq("20261")].set_index(
        ["breakdown", "category_code", "metric_id"]
    )
    small_operating = current.loc[
        ("capital_size", "19", "operating_profit")
    ]
    assert small_operating["continuing_yoy_pct"] == 6.0
    assert small_operating["regular_yoy_pct"] == pytest.approx(-1.890184, abs=1e-6)
    assert small_operating["continuing_sign"] == "POSITIVE"
    assert small_operating["regular_sign"] == "NEGATIVE"
    assert small_operating["sign_reversal"] == True
    nonmanufacturing_sales = current.loc[("industry", "144", "sales")]
    assert nonmanufacturing_sales["sign_reversal"] == True
    zeros = comparison.loc[
        comparison["sign_comparison_status"].eq("ZERO_INVOLVED_NO_DIRECTION")
    ]
    assert len(zeros) == 2
    assert zeros["sign_reversal"].isna().all()


def test_sign_reversal_frequency_uses_nonzero_comparable_denominator(
    comparison,
) -> None:
    frequency = build_sign_reversal_frequency(comparison).set_index(
        ["breakdown", "category_code", "metric_id"]
    )
    small_operating = frequency.loc[
        ("capital_size", "19", "operating_profit")
    ]
    assert small_operating["total_quarters"] == 41
    assert small_operating["comparable_nonzero_sign_quarters"] == 41
    assert small_operating["sign_reversal_count"] == 13
    assert small_operating["sign_reversal_rate_pct"] == pytest.approx(
        31.707317, abs=1e-6
    )
    large_operating = frequency.loc[
        ("capital_size", "25", "operating_profit")
    ]
    assert large_operating["sign_reversal_count"] == 0


def test_relative_margin_direction_is_explicitly_proxy_for_continuing_sample(
    relative,
) -> None:
    current = relative.loc[relative["period_code"].eq("20261")].set_index(
        ["breakdown", "category_code"]
    )
    small = current.loc[("capital_size", "19")]
    assert small["continuing_relative_growth_gap_pp"] == 3.5
    assert small["continuing_implied_relative_margin_change_pct"] == pytest.approx(
        3.414634, abs=1e-6
    )
    assert small["continuing_relative_margin_change_direction"] == "UP"
    assert (
        small["continuing_relative_margin_status"]
        == "PROXY_PROFIT_BASE_SIGN_NOT_PUBLISHED"
    )
    assert small["regular_relative_margin_change_direction"] == "DOWN"
    assert small["relative_margin_direction_reversal"] == True

    large = current.loc[("capital_size", "25")]
    assert large["continuing_relative_margin_change_direction"] == "UP"
    assert large["regular_relative_margin_change_direction"] == "UP"
    assert large["relative_margin_direction_reversal"] == False
    nonmanufacturing = current.loc[("industry", "144")]
    assert nonmanufacturing["relative_margin_direction_reversal"] == True
    assert relative["interpretation_note"].eq(
        LIMITATION_NOTES["relative_margin_proxy"]
    ).all()


@pytest.mark.parametrize(
    ("kwargs", "expected_status"),
    [
        (
            {"sales_yoy": np.nan, "operating_yoy": 1.0, "source": "continuing"},
            "MISSING_RATE_INPUT",
        ),
        (
            {"sales_yoy": -100.0, "operating_yoy": 1.0, "source": "continuing"},
            "SALES_GROWTH_DENOMINATOR_NOT_POSITIVE",
        ),
        (
            {
                "sales_yoy": 1.0,
                "operating_yoy": 2.0,
                "source": "regular",
                "regular_current_profit": -1.0,
                "regular_prior_profit": 1.0,
            },
            "PROFIT_LEVEL_SIGN_NOT_POSITIVE",
        ),
    ],
)
def test_relative_margin_invalid_inputs_remain_null(
    kwargs: dict[str, object], expected_status: str
) -> None:
    gap, implied, direction, status = _relative_margin_values(**kwargs)
    assert gap is None
    assert implied is None
    assert direction == "NOT_CALCULABLE"
    assert status == expected_status


def test_relative_margin_reversal_frequency(relative) -> None:
    frequency = build_relative_margin_reversal_frequency(relative).set_index(
        ["breakdown", "category_code"]
    )
    small = frequency.loc[("capital_size", "19")]
    assert small["comparable_direction_quarters"] == 41
    assert small["direction_reversal_count"] == 16
    assert small["direction_reversal_rate_pct"] == pytest.approx(
        39.024390, abs=1e-6
    )
    assert frequency.loc[("capital_size", "25"), "direction_reversal_count"] == 0


def test_capital_headline_reverses_in_2026q1_and_frequency_is_auditable(
    relative,
) -> None:
    history = build_capital_headline_history(relative)
    current = history.loc[history["period_code"].eq("20261")].iloc[0]
    assert current["continuing_small_sales_yoy_pct"] == 2.5
    assert current["continuing_small_margin_direction"] == "UP"
    assert current["continuing_large_margin_direction"] == "UP"
    assert current["continuing_headline_supported"] == False
    assert current["regular_small_margin_direction"] == "DOWN"
    assert current["regular_large_margin_direction"] == "UP"
    assert current["regular_headline_supported"] == True
    assert current["headline_reversal"] == True
    assert current["headline_comparison_status"] == "OPPOSITE_HEADLINE_RESULT"

    frequency = build_headline_reversal_frequency(history).iloc[0]
    assert frequency["total_quarters"] == 41
    assert frequency["comparable_headline_quarters"] == 41
    assert frequency["headline_reversal_count"] == 11
    assert frequency["headline_reversal_rate_pct"] == pytest.approx(
        26.829268, abs=1e-6
    )
    assert frequency["regular_only_support_count"] == 9
    assert frequency["continuing_only_support_count"] == 2
    assert frequency["both_support_count"] == 1
    assert frequency["neither_support_count"] == 29


def test_analysis_bundle_preserves_every_table() -> None:
    analysis = build_continuing_sample_analysis(PROJECT_ROOT)
    assert analysis.continuing_yoy.shape[0] == 984
    assert analysis.regular_yoy.shape[0] == 984
    assert analysis.comparison.shape[0] == 984
    assert analysis.relative_margin_comparison.shape[0] == 246
    assert analysis.sign_reversal_frequency.shape[0] == 24
    assert analysis.relative_margin_reversal_frequency.shape[0] == 6
    assert analysis.capital_headline_history.shape[0] == 41
    assert analysis.headline_reversal_frequency.shape[0] == 1
    assert analysis.response_counts.shape[0] == 3
    assert analysis.standard_error_rates.shape[0] == 12
    assert analysis.limitations == LIMITATION_NOTES


def test_pdf_dependency_is_reproducibly_pinned() -> None:
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (PROJECT_ROOT / "requirements.lock").read_text(encoding="utf-8")
    assert '"pypdf>=6.16"' in pyproject
    assert "pypdf==6.16.1" in lock
