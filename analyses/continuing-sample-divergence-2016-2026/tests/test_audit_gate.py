from __future__ import annotations

import pandas as pd

from corporate_quarterly.audit import Audit, _check_rates, validate_article_claims


def _status(audit: Audit, check_id: str) -> str:
    return next(check.status for check in audit.checks if check.check_id == check_id)


def test_official_rate_tolerance_passes_below_five_hundredths_of_a_point() -> None:
    processed = pd.DataFrame(
        {
            "sa_qoq_pct": [1.0, -2.0],
            "official_sa_qoq_pct": [1.049, -2.049],
        }
    )
    audit = Audit()
    _check_rates(processed, audit)
    assert _status(audit, "published_sa_rate_error") == "PASS"


def test_official_rate_tolerance_fails_above_five_hundredths_of_a_point() -> None:
    processed = pd.DataFrame(
        {
            "sa_qoq_pct": [1.0],
            "official_sa_qoq_pct": [1.051],
        }
    )
    audit = Audit()
    _check_rates(processed, audit)
    assert _status(audit, "published_sa_rate_error") == "FAIL"
    assert audit.status == "FAIL"


def _claims() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "claim_id": "C-001",
                "claim_type": "FACT",
                "verification_status": "PASS",
                "display_value": "12.3兆円",
            },
            {
                "claim_id": "C-002",
                "claim_type": "CALC",
                "verification_status": "PASS",
                "display_value": "+4.5%",
            },
        ]
    )


def test_article_gate_accepts_only_exact_claim_backed_numbers(tmp_path) -> None:
    article = tmp_path / "article.md"
    summary = (
        "【FACT】水準は12.3兆円<!-- claim: C-001 -->、"
        "【CALC】前年同期比は+4.5%<!-- claim: C-002 -->である。"
    )
    visible = summary.replace("【FACT】", "").replace("【CALC】", "")
    visible = visible.replace("<!-- claim: C-001 -->", "")
    visible = visible.replace("<!-- claim: C-002 -->", "")
    summary += "事" * (200 - len(visible))
    article.write_text(
        "\n".join(
            [
                "# 記事",
                "## 事実だけによる200字要約",
                summary,
                "## 本文",
                "ここから本文。",
            ]
        ),
        encoding="utf-8",
    )
    audit = Audit()
    validate_article_claims(article, _claims(), audit)

    assert audit.status == "PASS"
    assert all(check.status == "PASS" for check in audit.checks)


def test_article_gate_fails_unclaimed_number_and_unlabelled_causal_assertion(
    tmp_path,
) -> None:
    article = tmp_path / "article.md"
    article.write_text(
        "\n".join(
            [
                "# 記事",
                "【FACT】水準は12.3兆円<!-- claim: C-001 -->。",
                "【CALC】前年同期比は+4.5%<!-- claim: C-002 -->。",
                "その他は9.9兆円。",
                "AI需要が原因である。",
            ]
        ),
        encoding="utf-8",
    )
    audit = Audit()
    validate_article_claims(article, _claims(), audit)

    assert audit.status == "FAIL"
    assert _status(audit, "article_no_unclaimed_numbers") == "FAIL"
    assert _status(audit, "article_interpretation_policy") == "FAIL"


def test_article_gate_fails_unit_or_display_mismatch(tmp_path) -> None:
    article = tmp_path / "article.md"
    article.write_text(
        "\n".join(
            [
                "# 記事",
                "【FACT】水準は12.3億円<!-- claim: C-001 -->。",
                "【CALC】前年同期比は+4.5%<!-- claim: C-002 -->。",
            ]
        ),
        encoding="utf-8",
    )
    audit = Audit()
    validate_article_claims(article, _claims(), audit)

    assert _status(audit, "article_display_value_claim_match") == "FAIL"


def test_article_gate_rejects_number_piggybacking_on_later_claim_marker(tmp_path) -> None:
    article = tmp_path / "article.md"
    article.write_text(
        "\n".join(
            [
                "# 記事",
                "【FACT】未登録値9.9兆円と登録値12.3兆円<!-- claim: C-001 -->。",
                "【CALC】前年同期比+4.5%<!-- claim: C-002 -->。",
            ]
        ),
        encoding="utf-8",
    )
    audit = Audit()
    validate_article_claims(article, _claims(), audit)
    assert _status(audit, "article_no_unclaimed_numbers") == "FAIL"
