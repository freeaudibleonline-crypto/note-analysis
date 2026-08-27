from __future__ import annotations

from pathlib import Path
import re

import pandas as pd
import pytest

from corporate_quarterly.stage5_claims import build_stage5_claim_artifacts
from corporate_quarterly.stage5_publication import (
    ARTICLE_TITLE_V3_2,
    DECISION_MARGIN_CLAIM_IDS,
    FIGURE_MARKERS_V3_2,
    FORMAL_SMALL_CAPITAL_NAME_V3_2,
    OLD_ARTICLE_TITLE_V3_1,
    V32_EXAMPLE_CLAIM_IDS,
    origin_section_character_count,
    render_article_note_public_v3_2,
    render_article_note_v3_2,
    validate_article_note_v3_2,
    validate_rendered_article_v3_2,
    visible_article_character_count,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def claims_v3_2() -> pd.DataFrame:
    return build_stage5_claim_artifacts(PROJECT_ROOT).claims_v3_2


@pytest.fixture(scope="module")
def article_note(claims_v3_2: pd.DataFrame) -> str:
    return render_article_note_v3_2(claims_v3_2=claims_v3_2)


def test_real_canonical_example_claims_drive_opening_section(
    claims_v3_2: pd.DataFrame, article_note: str
) -> None:
    canonical = claims_v3_2.set_index("claim_id")
    expected = (2.1, -1.9, 2.5, 6.0, 0.4, 7.9)
    observed = tuple(
        round(float(canonical.loc[claim_id, "numeric_value"]), 1)
        for claim_id in V32_EXAMPLE_CLAIM_IDS
    )
    assert observed == expected
    for text in ("＋2.1％", "－1.9％", "＋2.5％", "＋6.0％", "0.4ポイント", "7.9ポイント"):
        assert text in article_note
    for claim_id in V32_EXAMPLE_CLAIM_IDS:
        assert f"<!-- claim: {claim_id} -->" in article_note


def test_article_has_exact_title_length_origin_and_formal_first_definition(
    claims_v3_2: pd.DataFrame, article_note: str
) -> None:
    audit = validate_article_note_v3_2(article_note, claims_v3_2)
    assert audit.status == "PASS", audit.checks.loc[audit.checks.status.eq("FAIL")]
    assert article_note.startswith(f"# {ARTICLE_TITLE_V3_2} ")
    assert OLD_ARTICLE_TITLE_V3_1 not in article_note
    assert 2900 <= visible_article_character_count(article_note) <= 3300
    assert 180 <= origin_section_character_count(article_note) <= 250
    plain = re.sub(r"<!--.*?-->", "", article_note, flags=re.DOTALL)
    body = plain.split("\n", 1)[1]
    assert body.find(FORMAL_SMALL_CAPITAL_NAME_V3_2) < body.find("小規模資本金層")
    assert plain.find("## 発端は2026年1～3月期") < plain.find("## 何を比べたのか")


def test_decision_margin_is_points_while_deadband_stays_percent(
    claims_v3_2: pd.DataFrame, article_note: str
) -> None:
    indexed = claims_v3_2.set_index("claim_id")
    assert indexed.loc[list(DECISION_MARGIN_CLAIM_IDS), "unit"].eq(
        "percentage_points"
    ).all()
    assert all(text in article_note for text in ("11.3ポイント", "9.0ポイント", "8.5ポイント"))
    paragraph = next(
        part for part in article_note.split("\n\n") if "判定余裕を営業利益増加率" in part
    )
    assert "11.3％" not in paragraph
    deadband_claims = indexed.loc[
        indexed.index.to_series().str.startswith("V31-DEADBAND-")
    ]
    assert deadband_claims["unit"].eq("percent").all()
    assert "利益率の相対変化率（％）" in article_note
    assert "単位は営業利益率の絶対ポイント差ではなく" in article_note
    assert "2018Q2の0.5ポイント" in article_note
    assert "20182.0" not in article_note


def test_article_numbers_are_input_driven_and_validator_detects_mismatch(
    claims_v3_2: pd.DataFrame, article_note: str
) -> None:
    changed = claims_v3_2.copy()
    claim_id = V32_EXAMPLE_CLAIM_IDS[0]
    changed.loc[changed["claim_id"].eq(claim_id), "numeric_value"] = 2.2
    changed.loc[changed["claim_id"].eq(claim_id), "display_value"] = "＋2.2％"
    changed.loc[changed["claim_id"].eq(claim_id), "article_tokens"] = "＋2.2％"
    regenerated = render_article_note_v3_2(claims_v3_2=changed)
    assert "売上高＋2.2％" in regenerated
    assert "売上高＋2.1％" not in regenerated
    mismatch_audit = validate_article_note_v3_2(article_note, changed)
    assert mismatch_audit.status == "FAIL"
    assert "article_all_numbers_claim_linked_and_matched" in mismatch_audit.failed_check_ids


def test_banned_assertion_fails_but_explicit_negative_caveat_passes(
    claims_v3_2: pd.DataFrame, article_note: str
) -> None:
    assert "どちらの系列も真実や正解とは呼ばない" in article_note
    assert validate_article_note_v3_2(article_note, claims_v3_2).passed
    affirmative = article_note.replace(
        "どちらの系列も真実や正解とは呼ばない",
        "真実は継続標本にある",
        1,
    )
    audit = validate_article_note_v3_2(affirmative, claims_v3_2)
    assert not audit.passed
    assert "article_no_affirmative_banned_expressions" in audit.failed_check_ids


def test_note_render_removes_audit_syntax_and_preserves_order(article_note: str) -> None:
    rendered = render_article_note_public_v3_2(article_note)
    audit = validate_rendered_article_v3_2(rendered, article_note=article_note)
    assert audit.status == "PASS", audit.checks.loc[audit.checks.status.eq("FAIL")]
    assert "<!--" not in rendered
    assert "![" not in rendered
    assert not re.search(r"\bV3[12]-[A-Z0-9-]+\b", rendered)
    assert "NOT_DETERMINED_BY_ROUNDING" not in rendered
    assert "NEAR_ZERO_BASE" not in rendered
    assert "EXTREME_YOY_RATE_GT_100" not in rendered
    for marker in FIGURE_MARKERS_V3_2.values():
        assert rendered.count(marker) == 1
    headings = re.findall(r"^#{1,6}\s+(.+)$", rendered, flags=re.MULTILINE)
    assert headings[:3] == [
        ARTICLE_TITLE_V3_2,
        "発端は2026年1～3月期",
        "要旨",
    ]
    assert not re.search(r"[ \t]{2,}|\n{3,}|[ \t]+$", rendered, flags=re.MULTILINE)


def test_article_validator_fails_old_title_unmarked_number_and_extra_figure(
    claims_v3_2: pd.DataFrame, article_note: str
) -> None:
    old_title = article_note.replace(ARTICLE_TITLE_V3_2, OLD_ARTICLE_TITLE_V3_1, 1)
    assert not validate_article_note_v3_2(old_title, claims_v3_2).passed

    unmarked = article_note + "\n追加値は12.3％である。\n"
    audit = validate_article_note_v3_2(unmarked, claims_v3_2)
    assert "article_all_numbers_claim_linked_and_matched" in audit.failed_check_ids

    extra = article_note + "\n![余分](charts/extra.png)\n"
    audit = validate_article_note_v3_2(extra, claims_v3_2)
    assert "article_exactly_three_relative_registered_figures" in audit.failed_check_ids
