from __future__ import annotations

from io import StringIO
from pathlib import Path
import re

import pandas as pd
import pytest

from corporate_quarterly.stage2_continuing_sample import (
    build_continuing_sample_analysis,
)
from corporate_quarterly.stage4_analysis import build_stage4_analysis
from corporate_quarterly.stage4_audit import audit_stage4_article
from corporate_quarterly.stage4_charts import (
    STAGE4_CHART_FILENAMES,
    build_stage4_charts,
)
from corporate_quarterly.stage4_publication import (
    ARTICLE_TITLE_V3_1,
    PRIMARY_CLAIM_ID,
    SUPPLEMENTAL_HEADLINE_CLAIM_ID,
    _visible_text,
    build_claims_v3_1,
    render_article_note,
    validate_article_note,
    validate_claims_v3_1,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def stage4():
    continuing = build_continuing_sample_analysis(PROJECT_ROOT)
    return build_stage4_analysis(PROJECT_ROOT, continuing=continuing)


@pytest.fixture(scope="module")
def claims(stage4):
    return build_claims_v3_1(
        headline_2x2=stage4.headline_2x2,
        mismatch_heatmap=stage4.mismatch_heatmap,
        rounding_sensitivity=stage4.rounding_sensitivity,
        deadband_sensitivity=stage4.deadband_sensitivity,
        near_zero_base_flags=stage4.near_zero_base_flags,
    )


def test_claims_make_16_of_41_primary_and_11_of_41_supplemental(claims) -> None:
    indexed = claims.set_index("claim_id")
    primary = indexed.loc[PRIMARY_CLAIM_ID]
    supplemental = indexed.loc[SUPPLEMENTAL_HEADLINE_CLAIM_ID]
    assert primary["claim_role"] == "PRIMARY"
    assert (primary["numerator"], primary["denominator"]) == (16, 41)
    assert primary["numeric_value"] == pytest.approx(16 / 41 * 100)
    assert supplemental["claim_role"] == "SUPPLEMENTAL"
    assert (supplemental["numerator"], supplemental["denominator"]) == (11, 41)
    assert not validate_claims_v3_1(claims)


def test_claims_validator_survives_csv_roundtrip(claims) -> None:
    restored = pd.read_csv(StringIO(claims.to_csv(index=False)))
    assert not validate_claims_v3_1(restored)
    assert {
        chart
        for value in restored["chart_ids"].fillna("").astype(str)
        for chart in value.split(";")
        if chart
    } == set(STAGE4_CHART_FILENAMES)


def test_article_contract_title_length_language_scope_and_three_figures(claims) -> None:
    article = render_article_note(claims_v3_1=claims)
    audit = validate_article_note(article, claims)
    assert audit.status == "PASS"
    assert audit_stage4_article(article, claims).status == "PASS"
    assert article.startswith(f"# {ARTICLE_TITLE_V3_1} ")
    assert 2500 <= len(_visible_text(article)) <= 3500
    assert article.count("<!-- central-claim:") == 1
    assert article.count("![") == 3
    plain = re.sub(r"<!--.*?-->", "", article, flags=re.S)
    assert "16/41と11/41はいずれも、2026Q1の結果を見た後に過去へ適用した探索的バックテスト" in plain
    assert "単に同じ真値を異なる標本で測った二つの推計とは限らない" in article
    assert "標本誤差は別途未定量" in article
    assert "営業外損益" not in article


def test_article_validator_fails_banned_word_and_extra_figure(claims) -> None:
    article = render_article_note(claims_v3_1=claims)
    banned = article.replace("系列の構成差", "標本を替えるときの構成差", 1)
    assert validate_article_note(banned, claims).status == "FAIL"
    extra = article + "\n![余分](charts/extra.png)\n"
    audit = validate_article_note(extra, claims)
    assert audit.status == "FAIL"
    assert "exactly_three_registered_figures" in audit.failed_check_ids


def test_chart_builder_writes_exactly_three_registered_pngs(stage4, tmp_path) -> None:
    charts = build_stage4_charts(
        headline_2x2=stage4.headline_2x2,
        mismatch_heatmap=stage4.mismatch_heatmap,
        deadband_sensitivity=stage4.deadband_sensitivity,
        output_dir=tmp_path,
    )
    assert tuple(charts) == STAGE4_CHART_FILENAMES
    assert {path.name for path in tmp_path.iterdir()} == set(STAGE4_CHART_FILENAMES)
    for path in charts.values():
        assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert path.stat().st_size > 20_000
