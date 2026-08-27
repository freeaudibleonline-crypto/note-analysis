from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd
import requests

from .constants import PROJECT_ROOT
from .estat import sha256_file, write_new_bytes


CANDIDATE_IDS = ("A", "B", "C", "D", "E")
PATTERN_STATUSES = {
    "PERSISTENT_PATTERN",
    "RECENT_BUT_NOT_ESTABLISHED",
    "ONE_QUARTER_OUTLIER",
    "UNSTABLE_OR_NO_PATTERN",
}
EVIDENCE_ASSESSMENTS = {"SUPPORTS", "CONTRADICTS", "MIXED"}
CONFIG_EVIDENCE_ASSESSMENTS = EVIDENCE_ASSESSMENTS | {"PENDING_RESEARCH"}
PUBLICATION_DECISIONS = {
    "PUBLISH_LONGITUDINAL_ARTICLE",
    "PUBLISH_CURRENT_QUARTER_SNAPSHOT_ONLY",
    "EXTERNAL_MECHANISM_RESEARCH_REQUIRED",
    "INTERNAL_ONLY_ONE_QUARTER_NOISE",
    "ARCHIVE_NO_STABLE_HEADLINE",
}
PRIMARY_SOURCE_CLASSES = {
    "OFFICIAL_STATISTICS",
    "CENTRAL_BANK_PRIMARY_SURVEY",
    "CENTRAL_BANK_OFFICIAL_STATISTICS",
    "OFFICIAL_PROGRAM_ADMINISTRATION",
    "COMPANY_PRIMARY_DISCLOSURE",
}
OFFICIAL_HOSTS = {
    "www.meti.go.jp",
    "www.customs.go.jp",
    "www.boj.or.jp",
    "it-shien.smrj.go.jp",
}


@dataclass(frozen=True)
class PublicationCheck:
    check_id: str
    status: str
    detail: str


@dataclass
class PublicationAudit:
    checks: list[PublicationCheck] = field(default_factory=list)

    def add(self, check_id: str, passed: bool, detail: str) -> None:
        self.checks.append(
            PublicationCheck(check_id, "PASS" if passed else "FAIL", detail)
        )

    @property
    def passed(self) -> bool:
        return all(check.status == "PASS" for check in self.checks)

    @property
    def status(self) -> str:
        return "PASS" if self.passed else "FAIL"


def load_external_evidence_config(
    path: Path | None = None,
) -> dict[str, Any]:
    config_path = path or PROJECT_ROOT / "config" / "external_evidence_2026Q1.json"
    return json.loads(config_path.read_text(encoding="utf-8"))


def _host(url: str) -> str:
    match = re.match(r"https://([^/]+)/", url)
    return "" if match is None else match.group(1).lower()


def validate_external_evidence_config(
    config: Mapping[str, Any],
    *,
    stage2_config: Mapping[str, Any] | None = None,
) -> None:
    """Fail closed when the pre-registered primary-source ledger is malformed."""
    candidates = list(config.get("candidates", []))
    candidate_ids = [str(row.get("candidate_id")) for row in candidates]
    if tuple(sorted(candidate_ids)) != CANDIDATE_IDS or len(set(candidate_ids)) != 5:
        raise ValueError("External evidence config must define candidates A-E exactly once")

    source_rows = list(config.get("sources", []))
    source_ids = [str(row.get("source_id")) for row in source_rows]
    if not source_rows or len(source_ids) != len(set(source_ids)):
        raise ValueError("External evidence source IDs must be present and unique")
    for source in source_rows:
        if source.get("source_class") not in PRIMARY_SOURCE_CLASSES:
            raise ValueError(
                f"Non-primary source class for {source.get('source_id')}: "
                f"{source.get('source_class')}"
            )
        if _host(str(source.get("url", ""))) not in OFFICIAL_HOSTS:
            raise ValueError(
                f"Source is not on the primary-source allowlist: {source.get('url')}"
            )
        for required in (
            "document_title",
            "publication_date",
            "reference_period",
            "raw_filename",
            "content_type",
        ):
            if not source.get(required):
                raise ValueError(
                    f"Missing {required} for external source {source.get('source_id')}"
                )
        raw_filename = Path(str(source["raw_filename"]))
        if raw_filename.is_absolute() or raw_filename.name != str(
            source["raw_filename"]
        ):
            raise ValueError(
                f"raw_filename must be a basename for {source.get('source_id')}: "
                f"{source.get('raw_filename')!r}"
            )

    evidence_rows = list(config.get("evidence", []))
    evidence_ids = [str(row.get("evidence_id")) for row in evidence_rows]
    if not evidence_rows or len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("Evidence IDs must be present and unique")
    represented = {str(row.get("candidate_id")) for row in evidence_rows}
    if represented != set(CANDIDATE_IDS):
        raise ValueError("Every candidate A-E must have a pre-registered evidence row")
    for row in evidence_rows:
        if row.get("candidate_id") not in CANDIDATE_IDS:
            raise ValueError(f"Unknown candidate in evidence row: {row}")
        if row.get("source_id") not in source_ids:
            raise ValueError(f"Unknown source in evidence row: {row}")
        if row.get("assessment") not in CONFIG_EVIDENCE_ASSESSMENTS:
            raise ValueError(f"Unknown evidence assessment: {row}")
        if row.get("causal_inference_allowed") is not False:
            raise ValueError(
                "External evidence is directional/contextual; causal_inference_allowed "
                f"must be false ({row.get('evidence_id')})"
            )
        for required in ("direct_observation", "limitation", "claim_use"):
            if not row.get(required):
                raise ValueError(
                    f"Missing {required} for evidence {row.get('evidence_id')}"
                )
        if row.get("assessment") == "PENDING_RESEARCH" and row.get(
            "direct_observation"
        ) != "NOT_ACQUIRED":
            raise ValueError(
                "PENDING_RESEARCH evidence must not contain an observation: "
                f"{row.get('evidence_id')}"
            )
        if row.get("assessment") in EVIDENCE_ASSESSMENTS and row.get(
            "direct_observation"
        ) == "NOT_ACQUIRED":
            raise ValueError(
                "Assessed evidence requires an acquired observation: "
                f"{row.get('evidence_id')}"
            )

    activation = config.get("activation_snapshot", {})
    if activation.get("phase3_status") == "NOT_ACTIVATED":
        preassessed = [
            str(row.get("evidence_id"))
            for row in evidence_rows
            if row.get("assessment") != "PENDING_RESEARCH"
            or row.get("direct_observation") != "NOT_ACQUIRED"
        ]
        if preassessed:
            raise ValueError(
                "Non-activated Phase 3 config cannot contain acquired observations: "
                f"{preassessed}"
            )

    if stage2_config is not None:
        registered = stage2_config.get("candidate_rules", {})
        labels = {row["candidate_id"]: row["label_ja"] for row in candidates}
        for candidate_id in CANDIDATE_IDS:
            expected = registered.get(candidate_id, {}).get("label_ja")
            if expected != labels[candidate_id]:
                raise ValueError(
                    f"Candidate label mismatch for {candidate_id}: "
                    f"external={labels[candidate_id]!r}, stage2={expected!r}"
                )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolve_manifest_path(project_root: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else project_root / path


def verify_external_manifest(
    manifest: Mapping[str, Any],
    *,
    project_root: Path = PROJECT_ROOT,
    config: Mapping[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    problems: list[str] = []
    sources = list(manifest.get("sources", []))
    source_ids = [str(source.get("source_id", "")) for source in sources]
    if not sources:
        problems.append("manifest_has_no_sources")
    if len(source_ids) != len(set(source_ids)):
        problems.append("duplicate_source_ids")
    if config is not None:
        expected_ids = {str(source["source_id"]) for source in config["sources"]}
        observed_ids = set(source_ids)
        if observed_ids != expected_ids:
            problems.append(
                "source_set_mismatch:"
                f"missing={sorted(expected_ids - observed_ids)}:"
                f"extra={sorted(observed_ids - expected_ids)}"
            )
        expected_by_id = {
            str(source["source_id"]): source for source in config["sources"]
        }
        for source in sources:
            expected = expected_by_id.get(str(source.get("source_id")))
            if expected is None:
                continue
            for key in (
                "url",
                "document_title",
                "publication_date",
                "reference_period",
                "content_type",
            ):
                if key in expected and source.get(key) != expected.get(key):
                    problems.append(
                        f"source_metadata_mismatch:{source.get('source_id')}:{key}"
                    )
    for source in sources:
        if not source.get("raw_path"):
            problems.append(f"missing_raw_path:{source.get('source_id')}")
            continue
        if Path(str(source["raw_path"])).is_absolute():
            problems.append(f"absolute_raw_path:{source.get('source_id')}")
        path = _resolve_manifest_path(project_root, str(source.get("raw_path", "")))
        if not path.is_file():
            problems.append(f"missing:{source.get('source_id')}:{path}")
            continue
        expected = source.get("sha256")
        actual = sha256_file(path)
        if actual != expected:
            problems.append(f"hash_mismatch:{source.get('source_id')}:{path}")
    return not problems, problems


def fetch_external_sources(
    *,
    phase0_passed: bool,
    pattern_decisions: pd.DataFrame | Mapping[str, str],
    project_root: Path = PROJECT_ROOT,
    config_path: Path | None = None,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Conditionally freeze primary-source bytes after the Phase 2 gate.

    The function performs no HTTP request and creates no directory unless Phase
    0 passed and at least one candidate is ``PERSISTENT_PATTERN``.  When the gate
    opens, only sources referenced by persistent candidates are acquired.  A
    repeated activated invocation validates and returns the existing vintage;
    it never silently refreshes a mutable upstream URL.
    """
    effective_config_path = config_path or (
        project_root / "config" / "external_evidence_2026Q1.json"
    )
    config = load_external_evidence_config(effective_config_path)
    stage2_path = project_root / str(config["stage2_config"])
    stage2 = json.loads(stage2_path.read_text(encoding="utf-8"))
    validate_external_evidence_config(config, stage2_config=stage2)
    decisions = _normalise_pattern_decisions(pattern_decisions)
    persistent_ids = decisions.loc[
        decisions["pattern_status"].eq("PERSISTENT_PATTERN"), "candidate_id"
    ].tolist()
    if not phase0_passed or not persistent_ids:
        reason = (
            "NOT_ACTIVATED_PHASE0_FAIL"
            if not phase0_passed
            else "NOT_ACTIVATED_NO_PERSISTENT_PATTERN"
        )
        return {
            "manifest_version": 1,
            "dataset": "stage2_external_primary_evidence",
            "release_id": config["release_id"],
            "acquisition_status": reason,
            "generated_at": None,
            "activated_candidate_ids": [],
            "source_policy": {
                "authority": "official primary sources only",
                "raw_mutation": "forbidden",
                "causal_inference": "not identified by this evidence ledger",
                "phase3_activation": "PERSISTENT_PATTERN candidates only",
            },
            "sources": [],
        }

    active_source_ids = {
        str(evidence["source_id"])
        for evidence in config["evidence"]
        if evidence["candidate_id"] in persistent_ids
    }
    active_sources = [
        source
        for source in config["sources"]
        if source["source_id"] in active_source_ids
    ]
    manifest_config = {**config, "sources": active_sources}

    raw_root = project_root / "data" / "raw" / f"external_{config['release_id']}"
    raw_root.mkdir(parents=True, exist_ok=True)
    manifest_path = raw_root / "data_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        valid, problems = verify_external_manifest(
            manifest, project_root=project_root, config=manifest_config
        )
        if not valid:
            raise RuntimeError(
                "External raw vintage is immutable but failed verification: "
                + "; ".join(problems)
            )
        return manifest

    http = session or requests.Session()
    http.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/134 Safari/537.36 "
                "corporate-quarterly-stage2/0.1"
            )
        }
    )
    retrieved_sources: list[dict[str, Any]] = []
    for source in active_sources:
        landing = source.get("landing_page_url")
        request_headers = dict(source.get("request_headers", {}))
        if landing:
            # Some official sites require a same-site landing request before a
            # document request.  The landing bytes are not used as evidence.
            warmup = http.get(landing, timeout=(20, 120))
            warmup.raise_for_status()
        response = http.get(
            source["url"], headers=request_headers, timeout=(20, 180)
        )
        response.raise_for_status()
        payload = response.content
        if not payload:
            raise RuntimeError(f"Empty external source response: {source['source_id']}")
        expected_type = str(source["content_type"])
        actual_type = response.headers.get("Content-Type", "").split(";", 1)[0]
        if expected_type == "application/pdf" and not payload.startswith(b"%PDF"):
            raise RuntimeError(
                f"Expected PDF bytes for {source['source_id']}; got {actual_type!r}"
            )
        if expected_type == "application/zip" and not payload.startswith(b"PK"):
            raise RuntimeError(
                f"Expected ZIP bytes for {source['source_id']}; got {actual_type!r}"
            )

        target = raw_root / source["raw_filename"]
        write_new_bytes(target, payload)
        retrieved_at = datetime.now(UTC).isoformat()
        retrieved_sources.append(
            {
                "source_id": source["source_id"],
                "provider": source["provider"],
                "source_class": source["source_class"],
                "document_title": source["document_title"],
                "url": source["url"],
                "landing_page_url": source.get("landing_page_url", ""),
                "publication_date": source["publication_date"],
                "reference_period": source["reference_period"],
                "content_type": source["content_type"],
                "retrieved_at": retrieved_at,
                "final_url": response.url,
                "http_status": response.status_code,
                "response_content_type": actual_type,
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "raw_path": target.relative_to(project_root).as_posix(),
                "bytes": len(payload),
                "sha256": _sha256_bytes(payload),
            }
        )

    manifest = {
        "manifest_version": 1,
        "dataset": "stage2_external_primary_evidence",
        "release_id": config["release_id"],
        "acquisition_status": "ACQUIRED_PERSISTENT_PATTERN_ONLY",
        "generated_at": datetime.now(UTC).isoformat(),
        "activated_candidate_ids": persistent_ids,
        "source_policy": {
            "authority": "official primary sources only",
            "raw_mutation": "forbidden",
            "causal_inference": "not identified by this evidence ledger",
            "phase3_activation": "PERSISTENT_PATTERN candidates only",
        },
        "sources": retrieved_sources,
    }
    write_new_bytes(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    return manifest


def _normalise_pattern_decisions(
    pattern_decisions: pd.DataFrame | Mapping[str, str],
) -> pd.DataFrame:
    if isinstance(pattern_decisions, Mapping):
        frame = pd.DataFrame(
            [
                {"candidate_id": candidate_id, "pattern_status": status}
                for candidate_id, status in pattern_decisions.items()
            ]
        )
    else:
        frame = pattern_decisions.copy()

    id_column = next(
        (name for name in ("candidate_id", "candidate", "candidate_code") if name in frame),
        None,
    )
    status_column = next(
        (
            name
            for name in ("pattern_status", "pattern_decision", "robustness_status")
            if name in frame
        ),
        None,
    )
    if id_column is None or status_column is None:
        raise ValueError(
            "pattern_decisions requires candidate_id and pattern_status (or supported aliases)"
        )
    frame = frame.rename(
        columns={id_column: "candidate_id", status_column: "pattern_status"}
    )
    frame["candidate_id"] = frame["candidate_id"].astype(str).str.strip().str.upper()
    frame["pattern_status"] = frame["pattern_status"].astype(str).str.strip()
    frame = frame.loc[frame["candidate_id"].isin(CANDIDATE_IDS)].copy()
    duplicates = frame.loc[frame["candidate_id"].duplicated(), "candidate_id"].tolist()
    if duplicates:
        raise ValueError(f"Duplicate candidate decisions: {duplicates}")
    missing = sorted(set(CANDIDATE_IDS) - set(frame["candidate_id"]))
    if missing:
        raise ValueError(f"Missing candidate decisions: {missing}")
    invalid = frame.loc[
        ~frame["pattern_status"].isin(PATTERN_STATUSES),
        ["candidate_id", "pattern_status"],
    ]
    if not invalid.empty:
        raise ValueError(f"Invalid pattern statuses: {invalid.to_dict('records')}")
    return frame.sort_values("candidate_id", kind="stable").reset_index(drop=True)


def build_external_evidence_ledger(
    *,
    pattern_decisions: pd.DataFrame | Mapping[str, str],
    config: Mapping[str, Any] | None = None,
    manifest: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Build all-candidate ledger while activating Phase 3 only for persistent rows."""
    evidence_config = dict(config or load_external_evidence_config())
    validate_external_evidence_config(evidence_config)
    decisions = _normalise_pattern_decisions(pattern_decisions)
    decision_map = decisions.set_index("candidate_id")["pattern_status"].to_dict()
    candidates = {
        row["candidate_id"]: row for row in evidence_config["candidates"]
    }
    sources = {row["source_id"]: row for row in evidence_config["sources"]}
    frozen = {
        row["source_id"]: row for row in (manifest or {}).get("sources", [])
    }
    rows: list[dict[str, Any]] = []
    for evidence in evidence_config["evidence"]:
        candidate_id = evidence["candidate_id"]
        pattern_status = decision_map[candidate_id]
        eligible = pattern_status == "PERSISTENT_PATTERN"
        source = sources[evidence["source_id"]]
        raw = frozen.get(evidence["source_id"], {})
        source_frozen = eligible and bool(raw.get("raw_path") and raw.get("sha256"))
        research_complete = (
            evidence["assessment"] in EVIDENCE_ASSESSMENTS
            and evidence["direct_observation"] != "NOT_ACQUIRED"
        )
        if not eligible:
            use_status = "NOT_ACTIVATED_NON_PERSISTENT"
            retrieval_status = "NOT_REQUESTED_PHASE3_INELIGIBLE"
            assessment = "NOT_APPLICABLE"
            direct_observation = "未取得（PERSISTENT_PATTERNに該当しないためPhase 3非発動）"
            limitation = "外部資料の取得・評価を実行していない。"
            claim_use = "PUBLIC_USE_PROHIBITED"
        elif source_frozen and research_complete:
            use_status = "ACTIVATED_PERSISTENT_PATTERN"
            retrieval_status = "FROZEN_AND_HASHED"
            assessment = evidence["assessment"]
            direct_observation = evidence["direct_observation"]
            limitation = evidence["limitation"]
            claim_use = evidence["claim_use"]
        elif source_frozen:
            use_status = "RESEARCH_REQUIRED_EVIDENCE_NOT_ASSESSED"
            retrieval_status = "FROZEN_PENDING_RESEARCH"
            assessment = "PENDING_RESEARCH"
            direct_observation = "NOT_ACQUIRED"
            limitation = "取得済みrawの読解・方向評価が未完了。"
            claim_use = "PUBLIC_USE_PROHIBITED"
        else:
            use_status = "RESEARCH_REQUIRED_SOURCE_NOT_FROZEN"
            retrieval_status = "NOT_RETRIEVED"
            assessment = "NOT_ASSESSED"
            direct_observation = "未取得（外部一次資料の凍結が必要）"
            limitation = "未取得のため方向評価はできない。"
            claim_use = "PUBLIC_USE_PROHIBITED"
        rows.append(
            {
                "evidence_id": evidence["evidence_id"],
                "candidate_id": candidate_id,
                "candidate_label_ja": candidates[candidate_id]["label_ja"],
                "pattern_status": pattern_status,
                "phase3_eligible": eligible,
                "source_frozen": source_frozen,
                "source_retrieval_status": retrieval_status,
                "evidence_use_status": use_status,
                "assessment": assessment,
                "source_id": source["source_id"],
                "provider": source["provider"],
                "source_class": source["source_class"],
                "document_title": source["document_title"],
                "url": source["url"],
                "landing_page_url": source.get("landing_page_url", ""),
                "publication_date": source["publication_date"],
                "reference_period": source["reference_period"],
                "direct_observation": direct_observation,
                "limitation": limitation,
                "claim_use": claim_use,
                "causal_inference_allowed": False,
                "raw_path": raw.get("raw_path", "") if eligible else "",
                "sha256": raw.get("sha256", "") if eligible else "",
                "retrieved_at": raw.get("retrieved_at", "") if eligible else "",
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["candidate_id", "evidence_id"], kind="stable"
    ).reset_index(drop=True)


def aggregate_external_status(
    ledger: pd.DataFrame, candidate_id: str
) -> str:
    candidate_rows = ledger.loc[ledger["candidate_id"].eq(candidate_id)]
    if candidate_rows.empty:
        return "RESEARCH_REQUIRED"
    if not candidate_rows["phase3_eligible"].eq(True).any():  # noqa: E712
        return "NOT_APPLICABLE"
    active = candidate_rows.loc[
        candidate_rows["evidence_use_status"].eq(
            "ACTIVATED_PERSISTENT_PATTERN"
        )
    ]
    if active.empty:
        return "RESEARCH_REQUIRED"
    assessments = set(active["assessment"])
    if not assessments or not assessments <= EVIDENCE_ASSESSMENTS:
        return "RESEARCH_REQUIRED"
    if "MIXED" in assessments or {
        "SUPPORTS",
        "CONTRADICTS",
    } <= assessments:
        return "MIXED"
    if assessments == {"SUPPORTS"}:
        return "SUPPORTS"
    if assessments == {"CONTRADICTS"}:
        return "CONTRADICTS"
    return "MIXED"


def build_publication_decisions(
    *,
    phase0_passed: bool,
    pattern_decisions: pd.DataFrame | Mapping[str, str],
    evidence_ledger: pd.DataFrame,
    config: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    evidence_config = dict(config or load_external_evidence_config())
    decisions = _normalise_pattern_decisions(pattern_decisions)
    candidate_config = {
        row["candidate_id"]: row for row in evidence_config["candidates"]
    }
    rows: list[dict[str, Any]] = []
    for decision in decisions.to_dict("records"):
        candidate_id = decision["candidate_id"]
        pattern_status = decision["pattern_status"]
        external_status = aggregate_external_status(evidence_ledger, candidate_id)
        if not phase0_passed:
            publication_decision = "ARCHIVE_NO_STABLE_HEADLINE"
        elif pattern_status == "PERSISTENT_PATTERN":
            publication_decision = (
                "PUBLISH_LONGITUDINAL_ARTICLE"
                if external_status in EVIDENCE_ASSESSMENTS
                else "EXTERNAL_MECHANISM_RESEARCH_REQUIRED"
            )
        elif pattern_status == "RECENT_BUT_NOT_ESTABLISHED":
            publication_decision = "PUBLISH_CURRENT_QUARTER_SNAPSHOT_ONLY"
        elif pattern_status == "ONE_QUARTER_OUTLIER":
            publication_decision = "INTERNAL_ONLY_ONE_QUARTER_NOISE"
        else:
            publication_decision = "ARCHIVE_NO_STABLE_HEADLINE"

        strength = next(
            (
                decision[column]
                for column in (
                    "current_quarter_strength",
                    "current_indicator_value",
                    "current_value",
                    "indicator_value",
                )
                if column in decision and pd.notna(decision[column])
            ),
            "",
        )
        rows.append(
            {
                "candidate_id": candidate_id,
                "candidate_label_ja": candidate_config[candidate_id]["label_ja"],
                "phase0_status": "PASS" if phase0_passed else "FAIL",
                "current_quarter_strength": strength,
                "indicator_unit": decision.get("indicator_unit", ""),
                "pattern_status": pattern_status,
                "external_evidence_status": external_status,
                "publication_decision": publication_decision,
                "publication_priority": candidate_config[candidate_id][
                    "publication_priority"
                ],
            }
        )
    result = pd.DataFrame(rows)
    invalid = set(result["publication_decision"]) - PUBLICATION_DECISIONS
    if invalid:  # pragma: no cover - defensive enum check
        raise AssertionError(f"Invalid publication decisions: {sorted(invalid)}")
    return result.sort_values("candidate_id", kind="stable").reset_index(drop=True)


def publication_article_required(publication_decisions: pd.DataFrame) -> bool:
    """Return whether all upstream gates permit ``article_public.md``.

    A persistent pattern is necessary but not sufficient: Phase 0 must pass and
    the corresponding primary-source material must have been frozen.  A
    persistent candidate without frozen evidence remains at
    ``EXTERNAL_MECHANISM_RESEARCH_REQUIRED`` and cannot produce a public article.
    """
    return bool(
        publication_decisions["pattern_status"].eq("PERSISTENT_PATTERN")
        .mul(publication_decisions["phase0_status"].eq("PASS"))
        .mul(
            publication_decisions["publication_decision"].eq(
                "PUBLISH_LONGITUDINAL_ARTICLE"
            )
        )
        .any()
    )


def select_central_candidate(publication_decisions: pd.DataFrame) -> str | None:
    eligible = publication_decisions.loc[
        publication_decisions["pattern_status"].eq("PERSISTENT_PATTERN")
    ].copy()
    if eligible.empty:
        return None
    external_rank = {"SUPPORTS": 3, "MIXED": 2, "CONTRADICTS": 1}
    eligible["_external_rank"] = eligible["external_evidence_status"].map(
        external_rank
    ).fillna(0)
    strength = pd.to_numeric(
        eligible["current_quarter_strength"], errors="coerce"
    ).abs()
    eligible["_strength"] = strength.fillna(-math.inf)
    eligible = eligible.sort_values(
        ["_external_rank", "_strength", "publication_priority", "candidate_id"],
        ascending=[False, False, True, True],
        kind="stable",
    )
    return str(eligible.iloc[0]["candidate_id"])


def render_decision_markdown(publication_decisions: pd.DataFrame) -> str:
    """Render the required decision table as the first content in decision.md."""
    lines = [
        "| 候補 | Phase 0 | 現四半期の強さ | 長期安定性 | 外部証拠 | 公開判定 |",
        "|---|---|---:|---|---|---|",
    ]
    for row in publication_decisions.sort_values("candidate_id").itertuples():
        if row.current_quarter_strength in (None, ""):
            strength = "—"
        else:
            value = float(row.current_quarter_strength)
            unit = str(getattr(row, "indicator_unit", ""))
            if unit == "%":
                strength = f"{value:.2f}%"
            elif "score" in unit:
                strength = f"{value:+.3f}（複合スコア）"
            else:
                strength = f"{value:.3f}"
        lines.append(
            f"| {row.candidate_id} {row.candidate_label_ja} | {row.phase0_status} | "
            f"{strength} | {row.pattern_status} | {row.external_evidence_status} | "
            f"{row.publication_decision} |"
        )
    selected = select_central_candidate(publication_decisions)
    lines.extend(
        [
            "",
            "## 判定の読み方",
            "",
            (
                f"- 公開記事の中心候補: {selected}"
                if selected is not None
                else "- PERSISTENT_PATTERNがないためarticle_public.mdは生成しない。"
            ),
            "- 外部証拠のSUPPORTSは方向的な整合であり、因果効果の識別ではない。",
            "- MIXEDは数量・価格・金額または集計期間が異なる証拠を併記する判定である。",
            "",
        ]
    )
    return "\n".join(lines)


HEADLINE_TEMPLATES = {
    "A": "経常増益は資本金十億円以上の製造業に集中―長期系列で持続性を検証",
    "B": "売上増でも利益率は二方向―資本金規模別にみる格差",
    "C": "設備投資の中身が交代―ソフトウェア増、その他投資減",
    "D": "経常利益の増加、営業利益との差額が示すもの",
    "E": "情報通信機械の利益寄与―長期系列で持続性を検証",
}


def render_candidate_headlines(publication_decisions: pd.DataFrame) -> str:
    selected = select_central_candidate(publication_decisions)
    lines = ["# 候補見出し", ""]
    for row in publication_decisions.sort_values("candidate_id").itertuples():
        if row.candidate_id == selected:
            disposition = "SELECTED_PUBLIC_CLAIM"
        elif row.pattern_status == "PERSISTENT_PATTERN":
            disposition = "ALTERNATE_PERSISTENT_NOT_SELECTED"
        elif row.publication_decision == "PUBLISH_CURRENT_QUARTER_SNAPSHOT_ONLY":
            disposition = "SNAPSHOT_ONLY_NOT_LONGITUDINAL"
        else:
            disposition = f"REJECTED_{row.pattern_status}"
        lines.extend(
            [
                f"## {row.candidate_id}. {HEADLINE_TEMPLATES[row.candidate_id]}",
                "",
                f"- 扱い: `{disposition}`",
                f"- 理由: 長期判定は`{row.pattern_status}`、外部証拠は`{row.external_evidence_status}`。",
                "",
            ]
        )
    return "\n".join(lines)


def prepare_claims_v2(
    base_claims: pd.DataFrame,
    *,
    central_candidate_id: str | None,
    public_claim_ids: Iterable[str] = (),
) -> pd.DataFrame:
    claims = base_claims.copy()
    if "claim_id" not in claims:
        raise ValueError("claims_v2 requires claim_id")
    if claims["claim_id"].duplicated().any():
        raise ValueError("claims_v2 claim IDs must be unique")
    public_ids = set(public_claim_ids)
    unknown = public_ids - set(claims["claim_id"])
    if unknown:
        raise ValueError(f"Unknown public claim IDs: {sorted(unknown)}")
    claims["candidate_id"] = claims.get("candidate_id", "")
    claims["publication_status"] = claims["claim_id"].map(
        lambda claim_id: "PUBLIC" if claim_id in public_ids else "INTERNAL"
    )
    claims["central_candidate_id"] = central_candidate_id or ""
    return claims


def _visible_summary(text: str) -> str:
    without_markers = re.sub(
        r"<!--\s*(?:claim|evidence|central-claim|article-mode):.*?-->",
        "",
        text,
    )
    without_markdown = re.sub(r"[*_`>#\[\]()]", "", without_markers)
    return "".join(without_markdown.split())


def _article_summary(article: str) -> str | None:
    match = re.search(
        r"##\s*(?:要約|120〜180字要約)\s*\n+(.*?)(?=\n##\s|\Z)",
        article,
        flags=re.DOTALL,
    )
    return None if match is None else match.group(1).strip()


def _public_claim_rows(claims_v2: pd.DataFrame | None) -> pd.DataFrame:
    if claims_v2 is None or claims_v2.empty:
        return pd.DataFrame()
    if "publication_status" in claims_v2:
        result = claims_v2.loc[claims_v2["publication_status"].eq("PUBLIC")]
    else:
        result = claims_v2.loc[
            claims_v2.get("verification_status", pd.Series(index=claims_v2.index)).eq(
                "PASS"
            )
        ]
    return result.copy()


def validate_public_article(
    *,
    article_path: Path,
    publication_decisions: pd.DataFrame,
    evidence_ledger: pd.DataFrame,
    claims_v2: pd.DataFrame | None = None,
    audit: PublicationAudit | None = None,
) -> PublicationAudit:
    result = audit or PublicationAudit()
    required = publication_article_required(publication_decisions)
    exists = article_path.is_file()
    result.add(
        "article_presence_matches_persistent_pattern",
        exists == required,
        f"article_exists={exists}, persistent_candidate_exists={required}",
    )
    if not exists:
        return result

    text = article_path.read_text(encoding="utf-8")
    central_markers = re.findall(r"<!--\s*central-claim:\s*([A-E])\s*-->", text)
    persistent_ids = set(
        publication_decisions.loc[
            publication_decisions["pattern_status"].eq("PERSISTENT_PATTERN"),
            "candidate_id",
        ]
    )
    selected_candidate = select_central_candidate(publication_decisions)
    central_ok = (
        len(central_markers) == 1
        and central_markers[0] in persistent_ids
        and central_markers[0] == selected_candidate
    )
    result.add(
        "article_exactly_one_persistent_central_claim",
        central_ok,
        (
            f"central_claim_markers={central_markers}, "
            f"selected={selected_candidate}, persistent={sorted(persistent_ids)}"
        ),
    )

    summary = _article_summary(text)
    summary_length = -1 if summary is None else len(_visible_summary(summary))
    result.add(
        "article_summary_120_to_180_characters",
        120 <= summary_length <= 180,
        f"visible_summary_length={summary_length}",
    )

    charts = re.findall(r"!\[[^\]]*\]\(([^)]+\.png)\)", text)
    result.add(
        "article_maximum_three_charts",
        len(charts) <= 3,
        f"chart_references={len(charts)}, unique_charts={len(set(charts))}",
    )
    badges = [
        badge
        for badge in ("【FACT】", "【CALC】", "【HYPOTHESIS】")
        if badge in text
    ]
    result.add(
        "article_reader_badges_hidden",
        not badges,
        "No reader-facing audit badges" if not badges else f"Visible badges={badges}",
    )

    prohibited: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if "本業のもうけ" in line:
            prohibited.append(f"line {line_number}: ordinary profit described as core profit")
        if "構造的格差" in line:
            prohibited.append(f"line {line_number}: one-quarter structural-gap assertion")
        if re.search(r"資本金.{0,18}(?:法的な)?(?:大企業|中小企業)", line):
            prohibited.append(f"line {line_number}: capital bucket relabelled as legal size class")
        if re.search(r"(?:営業利益外|営業外|差額).{0,30}(?:為替益|投資益)", line):
            prohibited.append(f"line {line_number}: net gap assigned to a single component")
        if "過去最高" in line and "名目" not in line:
            prohibited.append(f"line {line_number}: record claim lacks nominal qualifier")
        if "過去最高" in line and "名目" in line and "数量" in line:
            prohibited.append(f"line {line_number}: nominal record recast as quantity record")
        for phrase in ("AI需要", "価格転嫁", "人手不足", "インバウンド"):
            if phrase not in line:
                continue
            has_evidence = "<!-- evidence:" in line
            hedged = any(
                word in line
                for word in ("整合的", "可能性", "仮説", "検証が必要", "断定できない")
            )
            causal = bool(
                re.search(rf"{re.escape(phrase)}.{0,20}(?:が原因|による|が押し上げ|の効果)", line)
            )
            if not has_evidence or not hedged or causal:
                prohibited.append(
                    f"line {line_number}: unverified or causal use of {phrase}"
                )
    result.add(
        "article_prohibited_expression_gate",
        not prohibited,
        "No prohibited assertions"
        if not prohibited
        else " | ".join(prohibited[:12]),
    )

    evidence_markers = re.findall(r"<!--\s*evidence:\s*([A-Z0-9-]+)\s*-->", text)
    ledger_index = evidence_ledger.set_index("evidence_id", drop=False)
    unknown_evidence = sorted(set(evidence_markers) - set(ledger_index.index))
    inactive_evidence = sorted(
        evidence_id
        for evidence_id in set(evidence_markers) & set(ledger_index.index)
        if str(ledger_index.loc[evidence_id, "evidence_use_status"])
        != "ACTIVATED_PERSISTENT_PATTERN"
    )
    wrong_candidate: list[str] = []
    if len(central_markers) == 1:
        wrong_candidate = sorted(
            evidence_id
            for evidence_id in set(evidence_markers) & set(ledger_index.index)
            if str(ledger_index.loc[evidence_id, "candidate_id"])
            != central_markers[0]
        )
    result.add(
        "article_external_evidence_activated_and_on_claim",
        bool(evidence_markers)
        and not unknown_evidence
        and not inactive_evidence
        and not wrong_candidate,
        (
            "All evidence markers are activated for the central claim"
            if evidence_markers
            and not unknown_evidence
            and not inactive_evidence
            and not wrong_candidate
            else (
                f"markers={evidence_markers}, unknown={unknown_evidence}, "
                f"inactive={inactive_evidence}, wrong_candidate={wrong_candidate}"
            )
        ),
    )

    claim_markers = re.findall(r"<!--\s*claim:\s*([A-Z]+-\d{3})\s*-->", text)
    required_claim_columns = {
        "claim_id",
        "display_value",
        "candidate_id",
        "publication_status",
        "verification_status",
    }
    claims_schema_ok = (
        claims_v2 is not None
        and required_claim_columns <= set(claims_v2.columns)
        and not claims_v2["claim_id"].duplicated().any()
    )
    public_claims = (
        _public_claim_rows(claims_v2) if claims_schema_ok else pd.DataFrame()
    )
    unknown_claims: list[str] = []
    nonpublic_claims: list[str] = []
    missing_claims: list[str] = []
    duplicate_claims: list[str] = []
    mismatched_claims: list[str] = []
    unverified_claims: list[str] = []
    wrong_claim_candidate: list[str] = []
    if claims_schema_ok and claims_v2 is not None:
        known = set(claims_v2["claim_id"])
        public_ids = set(public_claims["claim_id"])
        unknown_claims = sorted(set(claim_markers) - known)
        nonpublic_claims = sorted(set(claim_markers) - public_ids - set(unknown_claims))
        missing_claims = sorted(public_ids - set(claim_markers))
        duplicate_claims = sorted(
            claim_id
            for claim_id in set(claim_markers)
            if claim_markers.count(claim_id) != 1
        )
        for row in public_claims.itertuples():
            display = str(getattr(row, "display_value", ""))
            if f"{display}<!-- claim: {row.claim_id} -->" not in text:
                mismatched_claims.append(row.claim_id)
            candidate = str(getattr(row, "candidate_id", ""))
            if central_markers and candidate and candidate != central_markers[0]:
                wrong_claim_candidate.append(row.claim_id)
            if str(getattr(row, "verification_status", "")) != "PASS":
                unverified_claims.append(row.claim_id)
    result.add(
        "article_claims_v2_exact_match",
        claims_schema_ok
        and not public_claims.empty
        and not unknown_claims
        and not nonpublic_claims
        and not missing_claims
        and not duplicate_claims
        and not mismatched_claims
        and not unverified_claims
        and not wrong_claim_candidate,
        (
            "Public claims_v2 values and markers match the central claim"
            if claims_schema_ok
            and not public_claims.empty
            and not unknown_claims
            and not nonpublic_claims
            and not missing_claims
            and not duplicate_claims
            and not mismatched_claims
            and not unverified_claims
            and not wrong_claim_candidate
            else (
                f"schema_ok={claims_schema_ok}, public_rows={len(public_claims)}, "
                f"unknown={unknown_claims}, "
                f"nonpublic={nonpublic_claims}, missing={missing_claims}, "
                f"duplicate={duplicate_claims}, mismatched={mismatched_claims}, "
                f"unverified={unverified_claims}, "
                f"wrong_candidate={wrong_claim_candidate}"
            )
        ),
    )

    numeric_pattern = re.compile(
        r"[-+−△▲]?[0-9][0-9,]*(?:\.[0-9]+)?\s*"
        r"(?:兆円|億円|万円|円|万人|人|件|社|%|ポイント)"
    )
    text_without_tracked_claims = text
    if claims_schema_ok:
        for row in public_claims.itertuples():
            token = f"{row.display_value}<!-- claim: {row.claim_id} -->"
            text_without_tracked_claims = text_without_tracked_claims.replace(
                token, "", 1
            )
    untracked = [
        match.group(0)
        for match in numeric_pattern.finditer(text_without_tracked_claims)
    ]
    result.add(
        "article_no_untracked_numeric_statements",
        claims_schema_ok and not untracked,
        "Every numeric statement is linked exactly once to a public PASS claim"
        if not untracked
        else f"Untracked numeric statements={untracked[:10]}",
    )

    article_mode = re.findall(r"<!--\s*article-mode:\s*([A-Z_]+)\s*-->", text)
    if "CURRENT_QUARTER_SNAPSHOT" in article_mode:
        first_part = "\n".join(text.splitlines()[:12])
        snapshot_labelled = "2026年1〜3月期の断面" in first_part
    else:
        snapshot_labelled = True
    result.add(
        "article_snapshot_mode_explicitly_labelled",
        snapshot_labelled,
        "Snapshot mode is absent or labelled in title/opening",
    )
    return result


def render_public_article(
    *,
    title: str,
    summary: str,
    central_candidate_id: str,
    body_sections: Sequence[Mapping[str, str]],
    chart_paths: Sequence[str] = (),
    article_mode: str = "LONGITUDINAL",
) -> str:
    """Render a reader-facing shell; all supplied prose remains caller-owned."""
    if central_candidate_id not in CANDIDATE_IDS:
        raise ValueError(f"Unknown central candidate: {central_candidate_id}")
    if article_mode not in {"LONGITUDINAL", "CURRENT_QUARTER_SNAPSHOT"}:
        raise ValueError(f"Unknown article mode: {article_mode}")
    if not 120 <= len(_visible_summary(summary)) <= 180:
        raise ValueError("Public article summary must be 120-180 visible characters")
    if len(set(chart_paths)) > 3:
        raise ValueError("Public article may contain no more than three charts")
    if "【FACT】" in summary or "【CALC】" in summary:
        raise ValueError("Reader-facing FACT/CALC badges are prohibited")
    lines = [
        f"# {title}",
        "",
        f"<!-- central-claim: {central_candidate_id} -->",
        f"<!-- article-mode: {article_mode} -->",
        "",
        "## 要約",
        "",
        summary,
        "",
    ]
    for section in body_sections:
        lines.extend(
            [
                f"## {section['heading']}",
                "",
                section["markdown"],
                "",
            ]
        )
    if chart_paths:
        lines.extend(["## 図表", ""])
        for index, chart in enumerate(dict.fromkeys(chart_paths), start=1):
            lines.extend([f"![図{index}]({chart})", ""])
    return "\n".join(lines).rstrip() + "\n"


def render_publication_audit(audit: PublicationAudit) -> str:
    lines = [
        "# 第2段階公開監査",
        "",
        f"**STATUS: {audit.status}**",
        "",
        "| チェック | 状態 | 詳細 |",
        "|---|---|---|",
    ]
    for check in audit.checks:
        lines.append(
            f"| {check.check_id} | {check.status} | {check.detail.replace('|', '／')} |"
        )
    lines.extend(
        [
            "",
            "FAILが1件でもあればarticle_public.mdは完成扱いにしない。",
            "",
        ]
    )
    return "\n".join(lines)


def write_publication_design_outputs(
    *,
    output_dir: Path,
    publication_decisions: pd.DataFrame,
    evidence_ledger: pd.DataFrame,
    audit: PublicationAudit,
    article_text: str | None = None,
) -> None:
    """Write only Phase-3/publication-design outputs for pipeline integration."""
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_ledger.to_csv(
        output_dir / "external_evidence_ledger.csv", index=False, encoding="utf-8"
    )
    (output_dir / "decision.md").write_text(
        render_decision_markdown(publication_decisions), encoding="utf-8"
    )
    (output_dir / "candidate_headlines.md").write_text(
        render_candidate_headlines(publication_decisions), encoding="utf-8"
    )
    (output_dir / "audit_v2.md").write_text(
        render_publication_audit(audit), encoding="utf-8"
    )
    article_path = output_dir / "article_public.md"
    if article_text is not None:
        article_path.write_text(article_text, encoding="utf-8")
    elif article_path.exists():
        raise RuntimeError(
            "Refusing to leave a stale article_public.md when no persistent article is allowed"
        )
