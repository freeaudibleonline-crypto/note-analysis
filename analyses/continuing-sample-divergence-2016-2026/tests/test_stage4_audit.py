from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from corporate_quarterly.stage4_audit import (
    PRIMARY_CLAIM_ID,
    REQUIRED_STAGE4_CHART_FILENAMES,
    REQUIRED_TITLE,
    SUPPLEMENTAL_CLAIM_ID,
    audit_frozen_v3_sha256,
    audit_stage4_article,
    audit_stage4_claims,
    audit_stage4_dataframes,
    audit_stage4_release,
    render_stage4_audit,
    snapshot_sha256_tree,
    visible_article_character_count,
)


def _claims() -> pd.DataFrame:
    rows = [
        {
            "claim_id": PRIMARY_CLAIM_ID,
            "claim_role": "PRIMARY",
            "verification_status": "PASS",
            "article_use": True,
            "display_value": "16/41四半期（39.0％）",
            "numeric_value": 16 / 41 * 100,
            "rounding_digits": 1,
            "numerator": 16,
            "denominator": 41,
            "article_tokens": "16/41;39.0;41",
        },
        {
            "claim_id": SUPPLEMENTAL_CLAIM_ID,
            "claim_role": "SUPPLEMENTAL",
            "verification_status": "PASS",
            "article_use": True,
            "display_value": "11/41四半期（26.8％）",
            "numeric_value": 11 / 41 * 100,
            "rounding_digits": 1,
            "numerator": 11,
            "denominator": 41,
            "article_tokens": "11/41;26.8",
        },
    ]
    extra = {
        "V31-CAPITAL-DEFINITION": ("資本金1千万円以上1億円未満層", "1"),
        "V31-HEADLINE-2X2": ("9回、2回、1回、29回、10回、3回", "9;2;1;29;10;3"),
        "V31-DECISION-MEDIANS": ("11.3％、9.0％、8.5％", "11.3;9.0;8.5"),
        "V31-DIVERGENCE-MEDIANS": ("11.21pt、4.07pt、1.05pt", "11.21;4.07;1.05"),
        "V31-DESIGN-BOUNDARY": ("5億円", "5"),
        "V31-ROUNDING": ("±0.05pt、0.1pt、0件、0.5pt", "0.05;0.1;0;0.5"),
        "V31-DEADBAND": (
            "15/39、14/37、10/33、8/29、±3％、27.6％",
            "15/39;14/37;10/33;8/29;3;27.6",
        ),
        "V31-EXTREME": ("100％、3件", "100;3"),
    }
    for claim_id, (display, tokens) in extra.items():
        rows.append(
            {
                "claim_id": claim_id,
                "claim_role": "SUPPORTING",
                "verification_status": "PASS",
                "article_use": True,
                "display_value": display,
                "numeric_value": np.nan,
                "rounding_digits": np.nan,
                "numerator": np.nan,
                "denominator": np.nan,
                "article_tokens": tokens,
            }
        )
    return pd.DataFrame(rows)


def _article() -> str:
    article = f"""# {REQUIRED_TITLE}<!-- claim: {PRIMARY_CLAIM_ID} -->

<!-- central-claim: {PRIMARY_CLAIM_ID} -->

調査対象は金融業・保険業を除く法人企業である。本文でいう資本金1千万円以上1億円未満層<!-- claim: V31-CAPITAL-DEFINITION -->を、以下では小規模資本金層と略記する。

主数値は利益率方向の不一致16/41四半期（39.0％）<!-- claim: {PRIMARY_CLAIM_ID} -->である。補足の複合見出しは11/41四半期（26.8％）<!-- claim: {SUPPLEMENTAL_CLAIM_ID} -->だった。16/41<!-- claim: {PRIMARY_CLAIM_ID} -->と11/41<!-- claim: {SUPPLEMENTAL_CLAIM_ID} -->はいずれも、2026Q1の結果を見た後に過去へ適用した探索的バックテストである。

見出しの二つの判定を組み合わせると、通常系列のみ9回、継続標本のみ2回、両方1回、どちらも29回<!-- claim: V31-HEADLINE-2X2 -->だった。したがって通常系列で見出しが成立したのは10回、継続標本系列では3回<!-- claim: V31-HEADLINE-2X2 -->である。この非対称は回数の記述にとどめる。

判定余裕の中央値は小規模資本金層11.3％、中堅資本金層9.0％、大規模資本金層8.5％<!-- claim: V31-DECISION-MEDIANS -->だった。系列間乖離の中央値は順に11.21pt、4.07pt、1.05pt<!-- claim: V31-DIVERGENCE-MEDIANS -->だった。このため「大企業は変化幅が大きいから一致する」説は成立しない。資本金5億円<!-- claim: V31-DESIGN-BOUNDARY -->を境とする全数・標本の別やローテーションの注記と合わせると、不一致勾配は調査設計と整合的だが、原因を識別したものではない。

丸め感応度では公表値に±0.05ptの区間を置き、判定余裕0.1pt以下を保留とした。該当は0件で、最小余裕は0.5pt<!-- claim: V31-ROUNDING -->だった。これは丸めだけの点検で、標本誤差は別途未定量である。

deadbandは、売上高前年比と営業利益前年比から推定した利益率の相対変化率（％）を単位とする。小規模資本金層は15/39、14/37、10/33、8/29となり、±3％では27.6％<!-- claim: V31-DEADBAND -->が残った。これは営業利益率水準の絶対ポイント差ではない。

継続標本系列は利益率水準を公表していないため、記述は上昇・低下の方向判定に限定する。継続標本は標本数が小さく、営業利益・経常利益の標準誤差率は算出されていない。どちらの系列も真実や正解とは呼ばない。

継続標本の営業利益増加率の絶対値が100％を超えた3件<!-- claim: V31-EXTREME -->には、機械的にEXTREME_YOY_RATE_GT_100を付けた。EXTREME_YOY_RATE_GT_100は低ベース又はゼロ近傍を意味しない。

通常系列と継続標本系列は、単に同じ真値を異なる標本で測った二つの推計とは限らない。企業の参入・退出、回答継続条件、推計用乗率、未回答補完、母集団構成の違いを含み得るからである。

![階層別の不一致率](charts/mismatch_heatmap.png)

![見出し判定の組合せ](charts/headline_2x2.png)

![deadband感応度](charts/deadband_sensitivity.png)
"""
    filler = (
        "ここで示した比較は、各四半期について同じ機械的な判定手順を適用し、"
        "観測された組合せを記述するものである。数表と図の対応を確認し、"
        "欠損をゼロで置き換えず、比較できない状態を区別して扱った。"
    )
    while visible_article_character_count(article) < 2600:
        article += "\n\n" + filler
    return article


def _headline_2x2() -> pd.DataFrame:
    cells = [
        ("REGULAR_ONLY", True, False, 9),
        ("CONTINUING_ONLY", False, True, 2),
        ("BOTH", True, True, 1),
        ("NEITHER", False, False, 29),
    ]
    return pd.DataFrame(
        [
            {
                "cell_id": name,
                "regular_headline_supported": regular,
                "continuing_headline_supported": continuing,
                "quarter_count": count,
                "denominator_quarters": 41,
                "share_pct": count / 41 * 100,
                "regular_supported_total": 10,
                "continuing_supported_total": 3,
                "exploratory_backtest_status": "POST_HOC_EXPLORATORY_BACKTEST_RULE_DEFINED_AFTER_2026Q1",
                "comparison_status": "COMPARABLE_BOOLEAN_PAIR",
            }
            for name, regular, continuing, count in cells
        ]
    )


def _heatmap() -> pd.DataFrame:
    values = {
        ("19", "relative_margin_direction"): (16, 41, 39.0),
        ("24", "relative_margin_direction"): (6, 41, 14.6),
        ("25", "relative_margin_direction"): (0, 41, 0.0),
        ("19", "operating_profit"): (13, 41, 31.7),
        ("24", "operating_profit"): (4, 41, 9.8),
        ("25", "operating_profit"): (0, 41, 0.0),
        ("19", "sales"): (6, 40, 15.0),
        ("24", "sales"): (7, 41, 17.1),
        ("25", "sales"): (1, 41, 2.4),
    }
    medians = {"19": (11.3, 11.21), "24": (9.0, 4.07), "25": (8.5, 1.05)}
    rows = []
    for (capital, metric), (count, denominator, rate) in values.items():
        decision, divergence = medians[capital]
        rows.append(
            {
                "capital_code": capital,
                "capital_scope_ja": capital,
                "metric_id": metric,
                "metric_label_ja": metric,
                "mismatch_count": count,
                "comparable_quarters": denominator,
                "total_quarters": 41,
                "mismatch_rate_pct": rate,
                "noncomparable_quarters": 41 - denominator,
                "census_sample_design_ja": "標本、混在又は全数",
                "census_threshold_yen": 500_000_000,
                "census_threshold_label_ja": "資本金5億円以上",
                "rotation_status": "YES" if capital == "19" else "PARTIAL" if capital == "24" else "NO",
                "rotation_note_ja": "抽出替えの有無を明示",
                "design_interpretation_note": (
                    "資本金階層別の不一致勾配は調査設計と整合的だが、"
                    "調査方式が原因であること又は全数・標本の別で決まることを示さない。"
                ),
                "continuing_decision_margin_abs_gap_median_pct": decision,
                "cross_series_growth_gap_divergence_median_pp": divergence,
            }
        )
    return pd.DataFrame(rows)


def _rounding() -> pd.DataFrame:
    periods = [f"{year}{quarter}" for year in range(2016, 2026) for quarter in range(1, 5)] + ["20261"]
    rows = []
    flagged_periods = {"20171", "20191", "20211"}
    for period in periods:
        flagged = period in flagged_periods
        rows.append(
            {
                "period_code": period,
                "capital_code": "19",
                "absolute_decision_margin_pp": 0.5 if period == "20182" else 1.0,
                "rounding_direction_status": "DETERMINED_UP_BY_ROUNDING_INTERVAL",
                "is_ambiguous_by_rounding": False,
                "rounding_half_width_pp": 0.05,
                "ambiguity_threshold_pp": 0.1,
                "sample_error_status": "NOT_QUANTIFIED",
                "extreme_yoy_rate_gt_100": flagged,
                "mechanical_flag": "NEAR_ZERO_BASE" if flagged else "",
                "relative_margin_direction_reversal": False if flagged else False,
                "headline_reversal": False if flagged else False,
                "sensitivity_method": (
                    "FIXED_41_QUARTER_EVENT_ATTRIBUTION_NOT_ROW_DELETION" if flagged else ""
                ),
            }
        )
    return pd.DataFrame(rows)


def _deadband() -> pd.DataFrame:
    small = {0.5: (15, 39), 1.0: (14, 37), 2.0: (10, 33), 3.0: (8, 29)}
    rows = []
    for capital in ("19", "24", "25"):
        for deadband in (0.5, 1.0, 2.0, 3.0):
            mismatch, retained = small[deadband] if capital == "19" else (0, 30)
            rows.append(
                {
                    "capital_code": capital,
                    "capital_scope_ja": capital,
                    "deadband_pct": deadband,
                    "total_quarters": 41,
                    "retained_quarters": retained,
                    "mismatch_count": mismatch,
                    "mismatch_rate_pct": mismatch / retained * 100,
                    "deadband_rule": "both inferred relative changes outside d",
                    "unit": "estimated_relative_margin_change_pct (%) - not margin points",
                    "sample_error_status": "NOT_QUANTIFIED",
                }
            )
    return pd.DataFrame(rows)


def _data_audit():
    return audit_stage4_dataframes(
        headline_2x2=_headline_2x2(),
        mismatch_heatmap=_heatmap(),
        rounding_sensitivity=_rounding(),
        deadband_sensitivity=_deadband(),
    )


def test_stage4_claims_and_article_positive_contract() -> None:
    claims = _claims()
    article = _article()
    assert audit_stage4_claims(claims).status == "PASS"
    assert 2500 <= visible_article_character_count(article) <= 3500
    audit = audit_stage4_article(article, claims)
    assert audit.status == "PASS", audit.checks.loc[audit.checks["status"].eq("FAIL")].to_dict("records")


@pytest.mark.parametrize(
    "forbidden",
    [
        "標本を替えると",
        "継続標本の方が正しい",
        "同一企業パネル",
        "統計的に有意",
        "中小企業だけ",
        "事前確率",
        "誤報率",
        "バイアス",
        "過大推計",
        "確実",
        "調査方式が原因",
        "全数調査か標本調査かで決まる",
    ],
)
def test_stage4_article_forbidden_terms_fail_closed(forbidden: str) -> None:
    audit = audit_stage4_article(_article() + f"\n\n{forbidden}。", _claims())
    assert audit.status == "FAIL"
    assert "article_forbidden_wording_and_overclaims" in audit.failed_check_ids


def test_stage4_article_length_claim_figure_and_nonoperating_fail_closed() -> None:
    claims = _claims()
    short = _article().split("ここで示した比較", 1)[0]
    assert "article_visible_character_count_2500_3500" in audit_stage4_article(short, claims).failed_check_ids

    duplicate_central = _article() + f"\n<!-- central-claim: {PRIMARY_CLAIM_ID} -->"
    assert "article_exactly_one_primary_central_claim" in audit_stage4_article(duplicate_central, claims).failed_check_ids

    fourth_figure = _article() + "\n![余分](charts/extra.png)"
    assert "article_one_to_three_registered_figures" in audit_stage4_article(fourth_figure, claims).failed_check_ids

    bridge = _article() + "\n営業外損益の分解。"
    assert "article_no_nonoperating_content" in audit_stage4_article(bridge, claims).failed_check_ids

    unlinked = _article() + "\n追加の値は7.7％だった。"
    assert "article_all_statistical_numbers_claim_linked" in audit_stage4_article(unlinked, claims).failed_check_ids


def test_stage4_article_caveat_and_direction_guards_fail_closed() -> None:
    claims = _claims()
    missing_exploratory = _article().replace("探索的バックテスト", "履歴集計")
    assert "article_both_backtests_disclosed_post_hoc_exploratory" in audit_stage4_article(missing_exploratory, claims).failed_check_ids

    bad_points = _article() + "\n継続標本の利益率は2ポイント上昇した<!-- claim: V31-HEADLINE-2X2 -->。"
    assert "article_continuing_margin_direction_only_no_pp" in audit_stage4_article(bad_points, claims).failed_check_ids

    bad_unit = _article().replace("利益率の相対変化率（％）", "営業利益率のポイント差")
    assert "article_deadband_unit_is_relative_rate_pct" in audit_stage4_article(bad_unit, claims).failed_check_ids

    ranked = _article().replace("どちらの系列も真実や正解とは呼ばない", "通常系列が真実である")
    ranked_audit = audit_stage4_article(ranked, claims)
    assert "article_neither_series_called_truth_or_correct" in ranked_audit.failed_check_ids
    assert "article_forbidden_wording_and_overclaims" in ranked_audit.failed_check_ids


def test_stage4_dataframe_contracts_and_canonical_values() -> None:
    audit = _data_audit()
    assert audit.status == "PASS", audit.checks.loc[audit.checks["status"].eq("FAIL")].to_dict("records")

    headline = _headline_2x2()
    headline.loc[0, "quarter_count"] = 8
    audit = audit_stage4_dataframes(
        headline_2x2=headline,
        mismatch_heatmap=_heatmap(),
        rounding_sensitivity=_rounding(),
        deadband_sensitivity=_deadband(),
    )
    assert "data_headline_2x2_canonical" in audit.failed_check_ids

    heatmap = _heatmap()
    heatmap.loc[
        heatmap["capital_code"].eq("25") & heatmap["metric_id"].eq("relative_margin_direction"),
        "mismatch_rate_pct",
    ] = 1.0
    audit = audit_stage4_dataframes(
        headline_2x2=_headline_2x2(),
        mismatch_heatmap=heatmap,
        rounding_sensitivity=_rounding(),
        deadband_sensitivity=_deadband(),
    )
    assert "data_mismatch_heatmap_canonical" in audit.failed_check_ids


def test_stage4_rounding_deadband_and_extreme_review_fail_closed() -> None:
    rounding = _rounding()
    rounding.loc[0, "is_ambiguous_by_rounding"] = True
    audit = audit_stage4_dataframes(
        headline_2x2=_headline_2x2(),
        mismatch_heatmap=_heatmap(),
        rounding_sensitivity=rounding,
        deadband_sensitivity=_deadband(),
    )
    assert "data_rounding_sensitivity_canonical" in audit.failed_check_ids

    rounding = _rounding()
    first_flag = rounding.index[rounding["extreme_yoy_rate_gt_100"]][0]
    rounding.loc[first_flag, "headline_reversal"] = True
    audit = audit_stage4_dataframes(
        headline_2x2=_headline_2x2(),
        mismatch_heatmap=_heatmap(),
        rounding_sensitivity=rounding,
        deadband_sensitivity=_deadband(),
    )
    assert "data_extreme_yoy_mechanical_review_fixed_window" in audit.failed_check_ids

    deadband = _deadband()
    deadband.loc[deadband["capital_code"].eq("19") & deadband["deadband_pct"].eq(3.0), "mismatch_count"] = 9
    audit = audit_stage4_dataframes(
        headline_2x2=_headline_2x2(),
        mismatch_heatmap=_heatmap(),
        rounding_sensitivity=_rounding(),
        deadband_sensitivity=deadband,
    )
    assert "data_deadband_sensitivity_canonical" in audit.failed_check_ids


def _write_release(output: Path, frozen: Path) -> dict[str, str]:
    output.mkdir(parents=True)
    frozen.mkdir(parents=True)
    (frozen / "frozen.txt").write_text("immutable", encoding="utf-8")
    snapshot = snapshot_sha256_tree(frozen)
    _claims().to_csv(output / "claims_v3_1.csv", index=False)
    _headline_2x2().to_csv(output / "headline_2x2.csv", index=False)
    _heatmap().to_csv(output / "mismatch_heatmap.csv", index=False)
    _rounding().to_csv(output / "rounding_sensitivity.csv", index=False)
    _deadband().to_csv(output / "deadband_sensitivity.csv", index=False)
    (output / "article_note.md").write_text(_article(), encoding="utf-8")
    charts = output / "charts"
    charts.mkdir()
    for name in REQUIRED_STAGE4_CHART_FILENAMES:
        (charts / name).write_bytes(b"\x89PNG\r\n\x1a\n" + b"test")
    (output / "audit_v3_1.md").write_text("**STATUS: PASS**\n", encoding="utf-8")
    return snapshot


def test_stage4_release_and_frozen_v3_hash_contract(tmp_path: Path) -> None:
    output = tmp_path / "v31"
    frozen = tmp_path / "v3"
    snapshot = _write_release(output, frozen)
    assert audit_frozen_v3_sha256(frozen, snapshot).status == "PASS"
    audit = audit_stage4_release(
        output,
        frozen_v3_dir=frozen,
        frozen_v3_sha256=snapshot,
    )
    assert audit.status == "PASS", audit.checks.loc[audit.checks["status"].eq("FAIL")].to_dict("records")

    (frozen / "frozen.txt").write_text("mutated", encoding="utf-8")
    changed = audit_stage4_release(
        output,
        frozen_v3_dir=frozen,
        frozen_v3_sha256=snapshot,
    )
    assert changed.status == "FAIL"
    assert "frozen_v3_sha256_exact_equality" in changed.failed_check_ids


def test_stage4_release_missing_chart_and_failed_audit_do_not_pass(tmp_path: Path) -> None:
    output = tmp_path / "v31"
    frozen = tmp_path / "v3"
    snapshot = _write_release(output, frozen)
    (output / "charts" / REQUIRED_STAGE4_CHART_FILENAMES[0]).unlink()
    (output / "audit_v3_1.md").write_text("**STATUS: FAIL**\n| x | FAIL | y |", encoding="utf-8")
    audit = audit_stage4_release(
        output,
        frozen_v3_dir=frozen,
        frozen_v3_sha256=snapshot,
    )
    assert audit.status == "FAIL"
    assert "release_required_charts_exact" in audit.failed_check_ids
    assert "release_existing_audit_pass" in audit.failed_check_ids
    rendered = render_stage4_audit(audit)
    assert "**STATUS: FAIL**" in rendered
    assert "| release_required_charts_exact | FAIL |" in rendered

