from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from corporate_quarterly.constants import PROJECT_ROOT
from corporate_quarterly.stage4_audit import (
    REQUIRED_STAGE4_CHART_FILENAMES,
    audit_stage4_release,
    snapshot_sha256_tree,
    visible_article_character_count,
)
from corporate_quarterly.stage4_pipeline import STAGE4_TOP_LEVEL_OUTPUTS


ROOT = Path(PROJECT_ROOT)
OUTPUT = ROOT / "outputs" / "2026Q1_v3_1"
FROZEN_V3 = ROOT / "outputs" / "2026Q1_v3"


def test_v31_release_has_all_requested_files_and_only_known_sidecars() -> None:
    assert OUTPUT.is_dir()
    observed = {path.name for path in OUTPUT.iterdir() if path.is_file()}
    required = set(STAGE4_TOP_LEVEL_OUTPUTS)
    assert required <= observed
    # A user-created legacy archive may coexist with the frozen release.  It is
    # not a Stage 4 artifact and must remain byte-for-byte untouched.
    assert observed - required <= {"アーカイブ.zip"}
    assert sorted(path.name for path in (OUTPUT / "charts").iterdir()) == sorted(
        REQUIRED_STAGE4_CHART_FILENAMES
    )


def test_v31_final_release_audit_passes_from_csv_roundtrip() -> None:
    frozen = snapshot_sha256_tree(FROZEN_V3)
    audit = audit_stage4_release(
        OUTPUT,
        frozen_v3_dir=FROZEN_V3,
        frozen_v3_sha256=frozen,
        require_existing_audit=True,
    )
    assert audit.passed, audit.checks.loc[audit.checks["status"].ne("PASS")]
    assert "**STATUS: PASS**" in (OUTPUT / "audit_v3_1.md").read_text(
        encoding="utf-8"
    )


def test_v31_article_is_one_claim_three_figures_and_in_length() -> None:
    article = (OUTPUT / "article_note.md").read_text(encoding="utf-8")
    assert 2500 <= visible_article_character_count(article) <= 3500
    assert article.count("<!-- central-claim:") == 1
    assert article.count("![") == 3
    assert "16/41" in article
    assert article.index("16/41") < article.index("11/41")
    assert "営業外損益" not in article


def test_v31_canonical_tables_match_requested_values() -> None:
    headline = pd.read_csv(OUTPUT / "headline_2x2.csv")
    cells = {
        (bool(row.regular_headline_supported), bool(row.continuing_headline_supported)): int(
            row.quarter_count
        )
        for row in headline.itertuples(index=False)
    }
    assert cells == {(True, False): 9, (False, True): 2, (True, True): 1, (False, False): 29}

    heat = pd.read_csv(OUTPUT / "mismatch_heatmap.csv", dtype={"capital_code": str})
    indexed = heat.set_index(["capital_code", "metric_id"])
    expected = {
        ("19", "relative_margin_direction"): (16, 41),
        ("24", "relative_margin_direction"): (6, 41),
        ("25", "relative_margin_direction"): (0, 41),
        ("19", "operating_profit"): (13, 41),
        ("24", "operating_profit"): (4, 41),
        ("25", "operating_profit"): (0, 41),
        ("19", "sales"): (6, 40),
        ("24", "sales"): (7, 41),
        ("25", "sales"): (1, 41),
    }
    for key, counts in expected.items():
        row = indexed.loc[key]
        assert (int(row.mismatch_count), int(row.comparable_quarters)) == counts
        assert np.isclose(row.mismatch_rate_pct, 100 * counts[0] / counts[1])

    dead = pd.read_csv(OUTPUT / "deadband_sensitivity.csv", dtype={"capital_code": str})
    small = dead.loc[dead["capital_code"].eq("19")]
    assert list(zip(small.mismatch_count, small.retained_quarters, strict=True)) == [
        (15, 39),
        (14, 37),
        (10, 33),
        (8, 29),
    ]


def test_v31_rounding_and_extreme_rate_review_are_separate() -> None:
    rounding = pd.read_csv(OUTPUT / "rounding_sensitivity.csv")
    assert int(rounding["is_ambiguous_by_rounding"].sum()) == 0
    minimum = rounding.loc[rounding["absolute_decision_margin_pp"].idxmin()]
    assert str(int(minimum.period_code)) == "20182"
    assert np.isclose(minimum.absolute_decision_margin_pp, 0.5)
    flagged = rounding.loc[rounding["extreme_yoy_rate_gt_100"]]
    assert len(flagged) == 3
    assert not flagged["relative_margin_direction_reversal"].any()
    assert not flagged["headline_reversal"].any()
    assert flagged["fixed_window_denominator_quarters"].eq(41).all()
