from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from corporate_quarterly import cli as cli_module
from corporate_quarterly import stage2_pipeline
from corporate_quarterly.stage2_publication import (
    PublicationAudit,
    aggregate_external_status,
    build_external_evidence_ledger,
    build_publication_decisions,
    fetch_external_sources,
    load_external_evidence_config,
    publication_article_required,
    render_candidate_headlines,
    render_decision_markdown,
    render_public_article,
    select_central_candidate,
    validate_external_evidence_config,
    validate_public_article,
    verify_external_manifest,
    write_publication_design_outputs,
)


ACTUAL_PATTERN_DECISIONS = pd.DataFrame(
    [
        {
            "candidate_id": "A",
            "current_indicator_value": 72.0597,
            "pattern_decision": "UNSTABLE_OR_NO_PATTERN",
        },
        {
            "candidate_id": "B",
            "current_indicator_value": 0.227518,
            "pattern_decision": "RECENT_BUT_NOT_ESTABLISHED",
        },
        {
            "candidate_id": "C",
            "current_indicator_value": 0.952770,
            "pattern_decision": "ONE_QUARTER_OUTLIER",
        },
        {
            "candidate_id": "D",
            "current_indicator_value": 37.5368,
            "pattern_decision": "RECENT_BUT_NOT_ESTABLISHED",
        },
        {
            "candidate_id": "E",
            "current_indicator_value": 38.1297,
            "pattern_decision": "UNSTABLE_OR_NO_PATTERN",
        },
    ]
)


def _stage2_config(project_root: Path) -> dict:
    return json.loads(
        (project_root / "config" / "stage2_2026Q1.json").read_text(
            encoding="utf-8"
        )
    )


def _frozen_manifest(config: dict) -> dict:
    return {
        "manifest_version": 1,
        "release_id": "2026Q1",
        "sources": [
            {
                "source_id": source["source_id"],
                "raw_path": f"data/raw/external_2026Q1/{source['raw_filename']}",
                "sha256": "a" * 64,
                "retrieved_at": "2026-08-25T00:00:00+00:00",
            }
            for source in config["sources"]
        ],
    }


def _synthetic_patterns() -> dict[str, str]:
    return {
        "A": "UNSTABLE_OR_NO_PATTERN",
        "B": "PERSISTENT_PATTERN",
        "C": "RECENT_BUT_NOT_ESTABLISHED",
        "D": "ONE_QUARTER_OUTLIER",
        "E": "UNSTABLE_OR_NO_PATTERN",
    }


def _synthetic_researched_config(project_root: Path) -> dict:
    """Activate only synthetic candidate B; the release config stays dormant."""
    config = deepcopy(
        load_external_evidence_config(
            project_root / "config" / "external_evidence_2026Q1.json"
        )
    )
    config["activation_snapshot"] = {
        "phase2_result": "SYNTHETIC_TEST_PERSISTENT_PATTERN",
        "persistent_candidate_ids": ["B"],
        "phase3_status": "ACTIVATED_SYNTHETIC_TEST",
        "raw_acquisition_status": "SYNTHETIC_FROZEN",
        "public_use_status": "SYNTHETIC_TEST_ONLY",
    }
    assessments = {
        "EV-B-001": "SUPPORTS",
        "EV-B-002": "MIXED",
    }
    for row in config["evidence"]:
        if row["evidence_id"] in assessments:
            row["assessment"] = assessments[row["evidence_id"]]
            row["direct_observation"] = (
                f"SYNTHETIC_OBSERVATION_{row['evidence_id']}"
            )
            row["claim_use"] = "SYNTHETIC_TEST_ONLY"
    validate_external_evidence_config(
        config, stage2_config=_stage2_config(project_root)
    )
    return config


def _synthetic_publication(project_root: Path):
    config = _synthetic_researched_config(project_root)
    ledger = build_external_evidence_ledger(
        pattern_decisions=_synthetic_patterns(),
        config=config,
        manifest=_frozen_manifest(config),
    )
    decisions = build_publication_decisions(
        phase0_passed=True,
        pattern_decisions=_synthetic_patterns(),
        evidence_ledger=ledger,
        config=config,
    )
    return config, ledger, decisions


def _summary() -> str:
    summary = (
        "法人企業統計の長期系列を資本金規模別に比べると、売上が増えた"
        "小規模資本金層では営業利益率が低下する一方、大規模資本金層では"
        "上昇する動きがみられた。日銀短観の販売価格判断と仕入価格判断の差も"
        "方向的には整合するが、調査対象と規模区分が異なるため、原因を特定した結果ではない。"
    )
    assert 120 <= len(summary) <= 180
    return summary


def _claims() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "claim_id": "C-001",
                "display_value": "+1.2%",
                "candidate_id": "B",
                "publication_status": "PUBLIC",
                "verification_status": "PASS",
            },
            {
                "claim_id": "C-002",
                "display_value": "9.9兆円",
                "candidate_id": "B",
                "publication_status": "INTERNAL",
                "verification_status": "PASS",
            },
        ]
    )


def _article_text() -> str:
    return render_public_article(
        title="資本金規模別に分かれた営業利益率の長期的な動き",
        summary=_summary(),
        central_candidate_id="B",
        body_sections=[
            {
                "heading": "長期系列の結果",
                "markdown": (
                    "公開する指標値は+1.2%<!-- claim: C-001 -->だった。"
                    "短観の規模別価格判断も方向的に整合するが、因果は識別しない。"
                    "<!-- evidence: EV-B-001 -->"
                ),
            }
        ],
        chart_paths=["charts/capital_margin_history.png"],
    )


def _check_status(audit: PublicationAudit, check_id: str) -> str:
    return next(
        check.status for check in audit.checks if check.check_id == check_id
    )


def test_external_evidence_config_is_official_primary_and_matches_stage2(
    project_root: Path,
) -> None:
    config = load_external_evidence_config(
        project_root / "config" / "external_evidence_2026Q1.json"
    )
    validate_external_evidence_config(
        config, stage2_config=_stage2_config(project_root)
    )
    assert {row["candidate_id"] for row in config["evidence"]} == set("ABCDE")
    assert all(row["causal_inference_allowed"] is False for row in config["evidence"])
    assert all(row["assessment"] == "PENDING_RESEARCH" for row in config["evidence"])
    assert all(row["direct_observation"] == "NOT_ACQUIRED" for row in config["evidence"])
    assert config["activation_snapshot"]["persistent_candidate_ids"] == []
    assert config["activation_snapshot"]["phase3_status"] == "NOT_ACTIVATED"


@pytest.mark.parametrize(
    "mutation", ["unofficial_host", "causal_claim", "dormant_preassessment"]
)
def test_external_evidence_config_fails_closed_on_nonprimary_or_causal_rows(
    project_root: Path, mutation: str
) -> None:
    config = deepcopy(
        load_external_evidence_config(
            project_root / "config" / "external_evidence_2026Q1.json"
        )
    )
    if mutation == "unofficial_host":
        config["sources"][0]["url"] = "https://example.com/commentary.pdf"
    elif mutation == "causal_claim":
        config["evidence"][0]["causal_inference_allowed"] = True
    else:
        config["evidence"][0]["assessment"] = "SUPPORTS"
        config["evidence"][0]["direct_observation"] = "SYNTHETIC_OBSERVATION"
    with pytest.raises(ValueError):
        validate_external_evidence_config(config)


def test_phase3_ledger_activates_only_persistent_candidates(
    project_root: Path,
) -> None:
    config, ledger, decisions = _synthetic_publication(project_root)
    assert set(ledger["candidate_id"]) == set("ABCDE")
    assert ledger.loc[
        ledger["candidate_id"].eq("B"), "evidence_use_status"
    ].eq("ACTIVATED_PERSISTENT_PATTERN").all()
    assert ledger.loc[
        ledger["candidate_id"].ne("B"), "evidence_use_status"
    ].eq("NOT_ACTIVATED_NON_PERSISTENT").all()
    assert aggregate_external_status(ledger, "B") == "MIXED"
    assert aggregate_external_status(ledger, "C") == "NOT_APPLICABLE"
    assert publication_article_required(decisions)
    assert select_central_candidate(decisions) == "B"
    assert config["policy"]["phase3_activation_rule"] == (
        "pattern_status == PERSISTENT_PATTERN"
    )


def test_persistent_candidate_without_frozen_source_requires_research(
    project_root: Path,
) -> None:
    config = load_external_evidence_config(
        project_root / "config" / "external_evidence_2026Q1.json"
    )
    ledger = build_external_evidence_ledger(
        pattern_decisions=_synthetic_patterns(), config=config, manifest=None
    )
    decisions = build_publication_decisions(
        phase0_passed=True,
        pattern_decisions=_synthetic_patterns(),
        evidence_ledger=ledger,
        config=config,
    )
    selected = decisions.loc[decisions["candidate_id"].eq("B")].iloc[0]
    assert selected["external_evidence_status"] == "RESEARCH_REQUIRED"
    assert selected["publication_decision"] == "EXTERNAL_MECHANISM_RESEARCH_REQUIRED"
    assert not publication_article_required(decisions)


def test_frozen_source_with_unassessed_plan_still_requires_research(
    project_root: Path,
) -> None:
    config = load_external_evidence_config(
        project_root / "config" / "external_evidence_2026Q1.json"
    )
    ledger = build_external_evidence_ledger(
        pattern_decisions=_synthetic_patterns(),
        config=config,
        manifest=_frozen_manifest(config),
    )
    selected = ledger.loc[ledger["candidate_id"].eq("B")]
    assert selected["source_retrieval_status"].eq(
        "FROZEN_PENDING_RESEARCH"
    ).all()
    assert selected["assessment"].eq("PENDING_RESEARCH").all()
    assert aggregate_external_status(ledger, "B") == "RESEARCH_REQUIRED"


def test_actual_nonpersistent_decisions_make_evidence_not_applicable_and_no_article(
    project_root: Path, tmp_path: Path
) -> None:
    config = load_external_evidence_config(
        project_root / "config" / "external_evidence_2026Q1.json"
    )
    ledger = build_external_evidence_ledger(
        pattern_decisions=ACTUAL_PATTERN_DECISIONS,
        config=config,
        manifest=_frozen_manifest(config),
    )
    decisions = build_publication_decisions(
        phase0_passed=True,
        pattern_decisions=ACTUAL_PATTERN_DECISIONS,
        evidence_ledger=ledger,
        config=config,
    )
    assert decisions["external_evidence_status"].eq("NOT_APPLICABLE").all()
    assert ledger["evidence_use_status"].eq(
        "NOT_ACTIVATED_NON_PERSISTENT"
    ).all()
    assert ledger["source_retrieval_status"].eq(
        "NOT_REQUESTED_PHASE3_INELIGIBLE"
    ).all()
    assert ledger["assessment"].eq("NOT_APPLICABLE").all()
    assert ledger["raw_path"].eq("").all()
    assert ledger["sha256"].eq("").all()
    assert not publication_article_required(decisions)
    assert select_central_candidate(decisions) is None
    assert list(decisions["current_quarter_strength"]) == pytest.approx(
        [72.0597, 0.227518, 0.952770, 37.5368, 38.1297]
    )
    audit = validate_public_article(
        article_path=tmp_path / "article_public.md",
        publication_decisions=decisions,
        evidence_ledger=ledger,
    )
    assert audit.status == "PASS"


def test_no_persistent_pattern_performs_no_http_and_creates_no_raw_directory(
    project_root: Path,
) -> None:
    class NoNetworkSession:
        headers: dict[str, str] = {}

        def get(self, *args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("Phase 3 gate allowed a forbidden HTTP request")

    raw_root = project_root / "data" / "raw" / "external_2026Q1"
    assert not raw_root.exists()
    receipt = fetch_external_sources(
        phase0_passed=True,
        pattern_decisions=ACTUAL_PATTERN_DECISIONS,
        project_root=project_root,
        session=NoNetworkSession(),
    )
    assert receipt["acquisition_status"] == (
        "NOT_ACTIVATED_NO_PERSISTENT_PATTERN"
    )
    assert receipt["activated_candidate_ids"] == []
    assert receipt["sources"] == []
    assert receipt["generated_at"] is None
    assert not raw_root.exists()


def test_phase0_failure_never_requires_public_article(project_root: Path) -> None:
    config, ledger, _ = _synthetic_publication(project_root)
    decisions = build_publication_decisions(
        phase0_passed=False,
        pattern_decisions=_synthetic_patterns(),
        evidence_ledger=ledger,
        config=config,
    )
    assert decisions["publication_decision"].eq(
        "ARCHIVE_NO_STABLE_HEADLINE"
    ).all()
    assert not publication_article_required(decisions)


def test_decision_markdown_starts_with_required_table(project_root: Path) -> None:
    _, _, decisions = _synthetic_publication(project_root)
    markdown = render_decision_markdown(decisions)
    assert markdown.startswith("| 候補 | Phase 0 | 現四半期の強さ | 長期安定性 | 外部証拠 | 公開判定 |")
    assert "B " in markdown
    assert "PUBLISH_LONGITUDINAL_ARTICLE" in markdown


def test_nonactivated_headlines_do_not_embed_external_findings(
    project_root: Path,
) -> None:
    config = load_external_evidence_config(
        project_root / "config" / "external_evidence_2026Q1.json"
    )
    ledger = build_external_evidence_ledger(
        pattern_decisions=ACTUAL_PATTERN_DECISIONS, config=config
    )
    decisions = build_publication_decisions(
        phase0_passed=True,
        pattern_decisions=ACTUAL_PATTERN_DECISIONS,
        evidence_ledger=ledger,
        config=config,
    )
    headlines = render_candidate_headlines(decisions)
    assert "数量統計は逆方向" not in headlines
    assert "情報通信機械の利益寄与―長期系列で持続性を検証" in headlines


def test_valid_public_article_passes_all_publication_gates(
    project_root: Path, tmp_path: Path
) -> None:
    _, ledger, decisions = _synthetic_publication(project_root)
    article_path = tmp_path / "article_public.md"
    article_path.write_text(_article_text(), encoding="utf-8")
    audit = validate_public_article(
        article_path=article_path,
        publication_decisions=decisions,
        evidence_ledger=ledger,
        claims_v2=_claims(),
    )
    assert audit.status == "PASS", [(c.check_id, c.detail) for c in audit.checks]


@pytest.mark.parametrize(
    ("replacement", "failed_check"),
    [
        (
            "\n【FACT】監査バッジを本文に表示。\n",
            "article_reader_badges_hidden",
        ),
        (
            "\n未登録の9.9兆円を追加。\n",
            "article_no_untracked_numeric_statements",
        ),
        (
            "\n価格転嫁が原因で利益率が上がった。<!-- evidence: EV-B-001 -->\n",
            "article_prohibited_expression_gate",
        ),
        (
            "\n別候補の資料を参照。<!-- evidence: EV-C-001 -->\n",
            "article_external_evidence_activated_and_on_claim",
        ),
        (
            "\n内部用の9.9兆円<!-- claim: C-002 -->。\n",
            "article_claims_v2_exact_match",
        ),
    ],
)
def test_public_article_gate_rejects_policy_or_traceability_violations(
    project_root: Path,
    tmp_path: Path,
    replacement: str,
    failed_check: str,
) -> None:
    _, ledger, decisions = _synthetic_publication(project_root)
    article_path = tmp_path / "article_public.md"
    article_path.write_text(_article_text() + replacement, encoding="utf-8")
    audit = validate_public_article(
        article_path=article_path,
        publication_decisions=decisions,
        evidence_ledger=ledger,
        claims_v2=_claims(),
    )
    assert audit.status == "FAIL"
    assert _check_status(audit, failed_check) == "FAIL"


def test_public_article_gate_rejects_four_chart_references(
    project_root: Path, tmp_path: Path
) -> None:
    _, ledger, decisions = _synthetic_publication(project_root)
    article = _article_text() + "\n".join(
        f"![追加図{i}](charts/extra_{i}.png)" for i in range(2, 5)
    )
    path = tmp_path / "article_public.md"
    path.write_text(article, encoding="utf-8")
    audit = validate_public_article(
        article_path=path,
        publication_decisions=decisions,
        evidence_ledger=ledger,
        claims_v2=_claims(),
    )
    assert _check_status(audit, "article_maximum_three_charts") == "FAIL"


def test_external_manifest_hash_and_source_set_are_verified(tmp_path: Path) -> None:
    raw = tmp_path / "data" / "raw" / "external_2026Q1"
    raw.mkdir(parents=True)
    source_path = raw / "source.bin"
    source_path.write_bytes(b"official-primary-source-bytes")
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    manifest = {
        "sources": [
            {
                "source_id": "official_one",
                "raw_path": "data/raw/external_2026Q1/source.bin",
                "sha256": digest,
            }
        ]
    }
    config = {"sources": [{"source_id": "official_one"}]}
    valid, problems = verify_external_manifest(
        manifest, project_root=tmp_path, config=config
    )
    assert valid
    assert problems == []

    source_path.write_bytes(b"mutated")
    valid, problems = verify_external_manifest(
        manifest, project_root=tmp_path, config=config
    )
    assert not valid
    assert any(problem.startswith("hash_mismatch:") for problem in problems)

    extra_config = {"sources": [{"source_id": "official_one"}, {"source_id": "two"}]}
    valid, problems = verify_external_manifest(
        manifest, project_root=tmp_path, config=extra_config
    )
    assert not valid
    assert any(problem.startswith("source_set_mismatch:") for problem in problems)


def test_writer_refuses_stale_public_article_when_article_is_not_allowed(
    project_root: Path, tmp_path: Path
) -> None:
    config = load_external_evidence_config(
        project_root / "config" / "external_evidence_2026Q1.json"
    )
    ledger = build_external_evidence_ledger(
        pattern_decisions=ACTUAL_PATTERN_DECISIONS,
        config=config,
        manifest=_frozen_manifest(config),
    )
    decisions = build_publication_decisions(
        phase0_passed=True,
        pattern_decisions=ACTUAL_PATTERN_DECISIONS,
        evidence_ledger=ledger,
        config=config,
    )
    output = tmp_path / "outputs"
    output.mkdir()
    (output / "article_public.md").write_text("stale", encoding="utf-8")
    with pytest.raises(RuntimeError, match="stale article_public"):
        write_publication_design_outputs(
            output_dir=output,
            publication_decisions=decisions,
            evidence_ledger=ledger,
            audit=PublicationAudit(),
            article_text=None,
        )


def test_fetch_stage2_sources_forwards_phase0_and_patterns_to_phase3_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: dict[str, object] = {}
    patterns = ACTUAL_PATTERN_DECISIONS.copy()

    monkeypatch.setattr(stage2_pipeline, "load_release", lambda _release: object())
    monkeypatch.setattr(
        stage2_pipeline,
        "build_processed",
        lambda _root, _release: (pd.DataFrame(), []),
    )
    monkeypatch.setattr(
        stage2_pipeline,
        "reproduce_phase0",
        lambda _processed: pd.DataFrame({"status": ["PASS", "PASS"]}),
    )
    monkeypatch.setattr(
        stage2_pipeline,
        "fetch_historical_snapshot",
        lambda _root: {"sources": [{"source_id": "synthetic"}]},
    )
    monkeypatch.setattr(
        stage2_pipeline, "build_historical_quarterly", lambda _root: object()
    )
    monkeypatch.setattr(
        stage2_pipeline, "build_candidate_series", lambda _historical: object()
    )
    monkeypatch.setattr(
        stage2_pipeline,
        "build_pattern_decisions",
        lambda _candidates: patterns,
    )

    def fake_fetch_external_sources(**kwargs):
        calls.update(kwargs)
        return {
            "acquisition_status": "NOT_ACTIVATED_NO_PERSISTENT_PATTERN",
            "sources": [],
        }

    monkeypatch.setattr(
        stage2_pipeline, "fetch_external_sources", fake_fetch_external_sources
    )
    result = stage2_pipeline.fetch_stage2_sources(tmp_path)

    assert calls["phase0_passed"] is True
    assert calls["pattern_decisions"] is patterns
    assert calls["project_root"] == tmp_path
    assert result["external_manifest"] is None
    assert result["external_acquisition"]["acquisition_status"] == (
        "NOT_ACTIVATED_NO_PERSISTENT_PATTERN"
    )


def test_fetch_stage2_cli_reports_nonactivation_without_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        cli_module,
        "fetch_stage2_sources",
        lambda _root: {
            "historical_manifest": {"sources": [{"source_id": "synthetic"}]},
            "external_manifest": None,
            "external_acquisition": {
                "acquisition_status": "NOT_ACTIVATED_NO_PERSISTENT_PATTERN",
                "sources": [],
            },
            "patterns": ACTUAL_PATTERN_DECISIONS.to_dict("records"),
        },
    )

    assert cli_module.main(["fetch-stage2", "--release", "2026Q1"]) == 0
    captured = capsys.readouterr()
    assert "external_activated=False" in captured.out
    assert captured.err == ""
