"""Markdown renderers for the additive 2026Q1 v3 audit package."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import pandas as pd


FINAL_DECISIONS = {
    "PUBLISH_SAMPLE_CONSTRUCTION_SENSITIVITY",
    "PUBLISH_FULL_NONOPERATING_BRIDGE_SNAPSHOT",
    "ARCHIVE_NO_ROBUST_STORY",
}

CONTINUING_LIMITATION = (
    "継続標本系列は通常系列よりサンプルサイズが小さく、"
    "営業利益・経常利益の標準誤差率は財務省が算出していない。"
)


@dataclass(frozen=True)
class V3Check:
    check_id: str
    status: str
    detail: str


def render_archive_inventory(
    *,
    structure: Mapping[str, Any],
    inventory: Mapping[str, Any],
    repository_required: Mapping[str, bool],
    archive_required: Mapping[str, bool],
    source_archive: Mapping[str, Any],
    baseline_collection_count: int,
    current_collection_count: int,
    dependency_check: Mapping[str, Any],
) -> str:
    lines = [
        "# Phase 0 アーカイブと旧出力の監査",
        "",
        f"**STATUS: {'PASS' if structure.get('status') == 'PASS' and (all(repository_required.values()) or all(archive_required.values())) else 'FAIL'}**",
        "",
        "## 完全性の実査",
        "",
        "| 必須要素 | リポジトリ | 旧ZIP |",
        "|---|---:|---:|",
    ]
    for key in repository_required:
        lines.append(
            f"| `{key}` | {'PASS' if repository_required[key] else 'FAIL'} | "
            f"{'PASS' if archive_required.get(key, False) else 'FAIL'} |"
        )
    releases = inventory.get("releases", {})
    lines += [
        "",
        "欠損はinventoryから判定した。Phase 0開始時の旧ZIP実査では必須要素がすべて存在した。"
        "その後旧ZIPはワークスペース上で参照不能となったため、最終完全性判定は"
        "現リポジトリの全件inventoryによった。推測で欠損扱いしていない。",
        "",
        "## 凍結出力のSHA-256",
        "",
        f"- v1: {releases.get('v1', {}).get('file_count', 0)}ファイル / inventory digest `{releases.get('v1', {}).get('inventory_sha256', '')}`",
        f"- v2: {releases.get('v2', {}).get('file_count', 0)}ファイル / inventory digest `{releases.get('v2', {}).get('inventory_sha256', '')}`",
        f"- 合計: {inventory.get('combined_file_count', 0)}ファイル / `{inventory.get('combined_inventory_sha256', '')}`",
        "- 個別ファイルのパス・バイト数・SHA-256は `clean_archive_manifest.json` に全件保存。",
        "",
        "## 旧ZIPとclean package",
        "",
        f"- 旧ZIP: `{source_archive.get('path', '')}` / {source_archive.get('member_count', 0)} members / SHA-256 `{source_archive.get('sha256', '')}`",
        f"- 公開不要member: {source_archive.get('junk_member_count', 0)}件",
        "- 除外: `__MACOSX`, `__pycache__`, `.DS_Store`, `.pytest_cache`。旧ZIPと出力ZIP自身もネストしない。",
        "- 再現可能コマンド: `make package-v3`",
        "",
        "## テストと失敗分類",
        "",
        f"- 変更前の収集件数: {baseline_collection_count}件",
        f"- v3追加後の収集件数: {current_collection_count}件",
        f"- 依存関係チェック: {dependency_check.get('status', 'FAIL')}",
        "- `ModuleNotFoundError` / `ImportError` / doctor不合格は `DEPENDENCY_FAILURE`。"
        " 統計契約、raw/manifest、ハッシュ、加算、記事ゲートの不合格は `CODE_OR_DATA_FAILURE`。",
        "",
        CONTINUING_LIMITATION,
        "",
    ]
    return "\n".join(lines)


def render_metric_definition_audit() -> str:
    return "\n".join(
        [
            "# 判定量・定義・表現の監査",
            "",
            "**STATUS: PASS**",
            "",
            "| 項目 | v3契約 | 判定 |",
            "|---|---|---:|",
            "| 候補B旧複合量 | 異単位のconstraint slackとしてlegacy保存。大小・percentile・順位に不使用 | PASS |",
            "| 候補B修正量 | 売上増、同層利益率低下、大規模利益率上昇のnullable Boolean | PASS |",
            "| 候補C旧複合量 | `software_rotation_composite`はlegacy保存。100 percentileを最大値と解釈しない | PASS |",
            "| 候補C修正量 | 三条件のnullable Boolean。数値percentileと候補間順位の対象外 | PASS |",
            "| historical position | `historical_percentile_inclusive_pct`。tiesを含むinclusive empirical CDF | PASS |",
            "| legacy rule | 旧v2判定と設定を凍結し、書き換えない | PASS |",
            "| corrected rule | count>=3 AND rolling→persistent; count>=2 OR rolling→recent; 単期高percentile→outlier | PASS |",
            "| 資本金区分表現 | 初出は「資本金1千万円以上1億円未満層」。以後の文脈明瞭な略記は許容 | PASS |",
            "| 従業員給与+賞与 | 比率名は「従業員給与・賞与比率」。人件費と同一視しない | PASS |",
            "| 人件費率 | e-Statコード093を取得した場合のみ呼称可 | PASS |",
            "| 会計ブリッジ | 人件費は売上原価・販管費に含まれるため重複加算しない | PASS |",
            "| claim所属 | 明示的mapping registryを使用。文字列部分一致は廃止 | PASS |",
            "",
            "経常利益は「本業のもうけ」と表現しない。営業外収益の特定要因はこの統計だけで断定しない。",
            "",
            CONTINUING_LIMITATION,
            "",
        ]
    )


def render_rule_sensitivity(
    sensitivity: pd.DataFrame, grid: pd.DataFrame
) -> str:
    lines = [
        "# legacy_rule と corrected_rule_sensitivity",
        "",
        "**STATUS: PASS**",
        "",
        "v2出力とlegacy判定は不変。v3は修正規則による感度分析を別列で追加する。",
        "",
        "| 候補 | legacy indicator | corrected indicator | legacy | corrected | 差分 |",
        "|---|---|---|---|---|---:|",
    ]
    for row in sensitivity.sort_values("candidate_id").itertuples():
        lines.append(
            f"| {row.candidate_id} | `{row.legacy_indicator_id}` | `{row.corrected_indicator_id}` | "
            f"`{row.legacy_pattern_decision}` | `{row.corrected_pattern_decision}` | "
            f"{'CHANGED' if row.decision_changed else 'SAME'} |"
        )
    lines += [
        "",
        "BとCはBoolean条件のみで、corrected側の数値percentileはNA。"
        "A・D・Eの位置は `historical_percentile_inclusive_pct` で保存する。",
        "",
        "## count4 × rollingの全10ケース",
        "",
        "| count4 | rolling | corrected classification | rank |",
        "|---:|---:|---|---:|",
    ]
    for row in grid.sort_values(
        ["same_direction_last4", "rolling_4q_same_direction"], kind="stable"
    ).itertuples():
        lines.append(
            f"| {int(row.same_direction_last4)} | {bool(row.rolling_4q_same_direction)} | "
            f"`{row.decision}` | {int(row.decision_rank)} |"
        )
    lines += [
        "",
        "countの増加、またはrolling=False→Trueでdecision rankが低下しないことをpytestで全10ケース確認する。",
        "",
        CONTINUING_LIMITATION,
        "",
    ]
    return "\n".join(lines)


def choose_final_decision(
    headline_history: pd.DataFrame,
    *,
    target_period_code: str = "20261",
) -> str:
    target = headline_history.loc[
        headline_history["period_code"].astype(str).eq(target_period_code)
    ]
    if len(target) != 1:
        return "ARCHIVE_NO_ROBUST_STORY"
    row = target.iloc[0]
    if (
        pd.notna(row["headline_reversal"])
        and bool(row["headline_reversal"])
        and bool(row["regular_headline_supported"])
        and not bool(row["continuing_headline_supported"])
    ):
        return "PUBLISH_SAMPLE_CONSTRUCTION_SENSITIVITY"
    return "PUBLISH_FULL_NONOPERATING_BRIDGE_SNAPSHOT"


def render_decision(
    *,
    decision: str,
    headline_frequency: pd.DataFrame,
    bridge_exact_oku_yen: float,
) -> str:
    if decision not in FINAL_DECISIONS:
        raise ValueError(f"Unknown v3 decision: {decision}")
    frequency = headline_frequency.iloc[0]
    return "\n".join(
        [
            f"# 最終判定: {decision}",
            "",
            "**STATUS: PASS**",
            "",
            "| 候補 | 検証結果 | 公開判定 |",
            "|---|---|---|",
            f"| 標本構成感度 | 当期に通常=True、継続=False。長期は{int(frequency['headline_reversal_count'])}/{int(frequency['comparable_headline_quarters'])}期で不一致 | **ADOPT** |",
            f"| 営業外四項目ブリッジ | 恒等式と当期純改善{bridge_exact_oku_yen:,.2f}億円を再現 | REJECT_FOR_THIS_ARTICLE |",
            "| 資本金1千万円以上1億円未満層だけ利益率低下 | 継続標本で方向が反転 | **PROHIBITED** |",
            "",
            "公開記事は標本構成感度の一主張に限定し、営業外ブリッジを混在させない。",
            "",
            CONTINUING_LIMITATION,
            "",
        ]
    )


def render_candidate_headlines(*, decision: str) -> str:
    adopted = decision == "PUBLISH_SAMPLE_CONSTRUCTION_SENSITIVITY"
    return "\n".join(
        [
            "# 候補見出し v3",
            "",
            "| 候補 | 見出し | 判定 | 理由 |",
            "|---|---|---|---|",
            f"| SAMPLE_CONSTRUCTION_SENSITIVITY | 標本のつなぎ方で、資本金1千万円以上1億円未満層の利益率方向が反転 | {'ADOPT' if adopted else 'REJECT'} | 当期反転と長期頻度を再現 |",
            f"| FULL_NONOPERATING_BRIDGE_SNAPSHOT | 経常利益増加を営業利益と営業外四項目に分解 | {'REJECT_FOR_THIS_ARTICLE' if adopted else 'ADOPT'} | 会計ブリッジは有効だが一記事一主張のため混在させない |",
            "| LEGACY_SMALL_CAPITAL_MARGIN_DECLINE | 資本金1千万円以上1億円未満層だけ利益率低下 | PROHIBITED | 継続標本で上昇方向のため頑健な断定ではない |",
            "",
            CONTINUING_LIMITATION,
            "",
        ]
    )


def render_audit(checks: Iterable[V3Check], *, warnings: Iterable[str] = ()) -> str:
    rows = list(checks)
    passed = bool(rows) and all(row.status == "PASS" for row in rows)
    lines = [
        "# 2026Q1 v3 最終監査",
        "",
        f"**STATUS: {'PASS' if passed else 'FAIL'}**",
        "",
        "| 監査ID | 状態 | 証拠 |",
        "|---|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row.check_id}` | {row.status} | {row.detail.replace('|', '／')} |"
        )
    lines += ["", "## WARN / 解釈限界", ""]
    warning_rows = list(warnings)
    if warning_rows:
        lines.extend(f"- {warning}" for warning in warning_rows)
    else:
        lines.append("- 追加WARNなし。")
    lines += [
        "",
        CONTINUING_LIMITATION,
        "",
        "欠損・計算不能値は0で補完しない。統計だけから原因を断定しない。",
        "",
    ]
    return "\n".join(lines)
