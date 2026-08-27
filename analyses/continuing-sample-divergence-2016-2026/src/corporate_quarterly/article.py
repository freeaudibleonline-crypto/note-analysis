from __future__ import annotations

from itertools import product
import re

import pandas as pd

from .constants import Release


_CLAIM_MARKER_RE = re.compile(r"<!-- claim: ([A-Z]-\d{3}) -->")
_CLAIM_BADGE_RE = re.compile(r"【(?:FACT|CALC|HYPOTHESIS)】")


def _visible_summary(text: str) -> str:
    return _CLAIM_BADGE_RE.sub("", _CLAIM_MARKER_RE.sub("", text)).replace("\n", "").strip()


def _claim_token(row: pd.Series) -> str:
    display = str(row["display_value"]).strip()
    if not display:
        display = "計算不能"
    return f"{display}<!-- claim: {row['claim_id']} -->"


def _anchor_rows(claims: pd.DataFrame, anchor: str) -> list[pd.Series]:
    return [row for _, row in claims.loc[claims["article_anchor"].eq(anchor)].iterrows()]


def _one(rows: list[pd.Series], metric_id: str, phrase: str | None = None) -> pd.Series:
    matches = [
        row
        for row in rows
        if row["metric_id"] == metric_id
        and (phrase is None or phrase in str(row["claim_text"]))
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one article claim for metric={metric_id!r}, phrase={phrase!r}; "
            f"found {len(matches)}"
        )
    return matches[0]


def _summary_200(rows: list[pd.Series]) -> str:
    """Render an exactly 200-character visible summary for the configured release.

    Claim markers are HTML comments and the FACT label is a classification badge;
    both are excluded from the editorial character count, matching the audit gate.
    A small set of semantically equivalent wording variants absorbs ordinary
    changes in the width of released figures while keeping all twelve claims once.
    """
    expected = {
        "sales": ("売上高",),
        "operating_profit": ("営業利益",),
        "ordinary_profit": ("経常利益",),
        "capex_including_software": ("設備投資（ソフトウェア込み）",),
    }
    if len(rows) != 12:
        raise ValueError(f"fact_summary must contain 12 claims; found {len(rows)}")

    grouped: dict[str, dict[str, pd.Series]] = {}
    for metric_id in expected:
        metric_rows = [row for row in rows if row["metric_id"] == metric_id]
        if len(metric_rows) != 3:
            raise ValueError(f"Summary metric {metric_id} must have level/delta/rate claims")
        grouped[metric_id] = {
            "level": next(row for row in metric_rows if "当期水準" in str(row["claim_text"])),
            "delta": next(row for row in metric_rows if "前年同期差" in str(row["claim_text"])),
            "rate": next(row for row in metric_rows if "前年同期比" in str(row["claim_text"])),
        }

    labels = {
        "sales": "売上高",
        "operating_profit": "営業利益",
        "ordinary_profit": "経常利益",
        "capex_including_software": "設備投資（ソフトウェア込み）",
    }
    metric_order = list(labels)
    suffixes = (
        "全て原数値である。",
        "すべて原数値である。",
        "いずれも原数値である。",
        "金額は全て原数値である。",
        "金額はいずれも原数値である。",
        "各金額は季節調整前の原数値である。",
        "原数値の前年同期比較であり、金額はすべて季節調整前の名目値である。",
        "増減率は前年同期との比較で、金額はすべて季節調整前の名目値である。",
        "増減率は前年同期との比較であり、金額は全て季節調整前の名目値である。",
        "増減率は前年同期との比較であり、金額はすべて季節調整前の名目値である。",
        (
            "増減率は前年同期との比較であり、各金額は全て季節調整前の名目値で、"
            "対象値はいずれも全規模合計の母集団推計値である。"
        ),
    )
    # The first rate spells out the comparison.  Later references can use either
    # "same" or the full label without changing meaning.
    for later_rate_labels in product(("同", "前年同期比"), repeat=3):
        rate_labels = ("前年同期比", *later_rate_labels)
        sentences: list[str] = ["【FACT】主系列は金融業・保険業を除く。"]
        for metric_id, rate_label in zip(metric_order, rate_labels, strict=True):
            item = grouped[metric_id]
            sentences.append(
                f"【FACT】{labels[metric_id]}は{_claim_token(item['level'])}。"
                f"【CALC】前年差{_claim_token(item['delta'])}、"
                f"{rate_label}{_claim_token(item['rate'])}。"
            )
        prefix = "".join(sentences)
        for suffix in suffixes:
            candidate = prefix + suffix
            visible = _visible_summary(candidate)
            if len(visible) == 200:
                return candidate
    lengths = sorted(
        {
            len(
                _visible_summary("".join(sentences) + suffix)
            )
            for suffix in suffixes
        }
    )
    raise ValueError(
        "Could not render an exact 200-character summary with the current values; "
        f"candidate lengths were {lengths}"
    )


def _kanji_capital_label(claim_text: str) -> str:
    label = claim_text.split("の営業利益前年差", 1)[0]
    replacements = (
        ("1千万円", "一千万円"),
        ("10億円", "十億円"),
        ("1億円", "一億円"),
    )
    for old, new in replacements:
        label = label.replace(old, new)
    return label


def render_article(claims: pd.DataFrame, release: Release, *, status: str = "PASS") -> str:
    """Render ``article.md`` solely from traceable claim values.

    Every narrative claim receives exactly one HTML marker. Chart-input claims are
    validated against the PNG generator separately and therefore do not create
    invisible duplicate markers in the prose.
    """
    if status not in {"PASS", "FAIL"}:
        raise ValueError("Article status must be PASS or FAIL")
    if claims["claim_id"].duplicated().any():
        duplicates = claims.loc[claims["claim_id"].duplicated(), "claim_id"].tolist()
        raise ValueError(f"Duplicate claim IDs: {duplicates}")

    if "claim_usage" in claims:
        article_claims = claims.loc[claims["claim_usage"].ne("CHART_INPUT")]
    else:
        article_claims = claims
    anchors = {
        anchor: _anchor_rows(article_claims, anchor)
        for anchor in (
            "scope",
            "fact_summary",
            "seasonal",
            "finding_concentration",
            "finding_capital",
            "finding_profit_gap",
            "margin",
            "software",
            "allocation",
            "hypotheses",
        )
    }
    summary = _summary_200(anchors["fact_summary"])

    scope = _one(anchors["scope"], "ordinary_profit")

    seasonal = {row["metric_id"]: row for row in anchors["seasonal"]}
    if len(seasonal) != 5:
        raise ValueError("seasonal anchor must contain five distinct metric claims")

    concentration = anchors["finding_concentration"]
    top_industry_delta = next(row for row in concentration if "前年差" in str(row["claim_text"]) and "寄与率" not in str(row["claim_text"]))
    top_industry_rate = next(row for row in concentration if "寄与率" in str(row["claim_text"]))
    concentration_rows = {
        int(re.search(r"上位(\d+)業種", str(row["claim_text"])).group(1)): row
        for row in concentration
        if re.search(r"上位(\d+)業種", str(row["claim_text"]))
    }
    if set(concentration_rows) != {1, 3, 5}:
        raise ValueError("Concentration claims must contain top-1, top-3 and top-5")
    top_industry_name = str(top_industry_delta["claim_text"]).split("の営業利益前年差", 1)[0]

    capital_rows = anchors["finding_capital"]
    capital_delta = next(row for row in capital_rows if "寄与率" not in str(row["claim_text"]))
    capital_rate = next(row for row in capital_rows if "寄与率" in str(row["claim_text"]))
    capital_label = _kanji_capital_label(str(capital_delta["claim_text"]))

    gap_current = _one(anchors["finding_profit_gap"], "ordinary_minus_operating", "水準差")
    gap_delta = _one(anchors["finding_profit_gap"], "ordinary_minus_operating", "前年差")
    operating_margin = _one(anchors["margin"], "operating_profit")
    ordinary_margin = _one(anchors["margin"], "ordinary_profit")
    software_value = next(
        row
        for row in anchors["software"]
        if row["metric_id"] == "software_capex_derived"
        and "前年同期比" not in str(row["claim_text"])
    )
    software_rate = _one(anchors["software"], "software_capex_derived", "前年同期比")
    allocation = {row["metric_id"]: row for row in anchors["allocation"]}
    allocation_growth_claims = ""
    if "employee_total_pay_derived" in allocation and "employee_count" in allocation:
        allocation_growth_claims = (
            "【CALC】給与・賞与総額の前年同期比は"
            f"{_claim_token(allocation['employee_total_pay_derived'])}、従業員数の前年同期比は"
            f"{_claim_token(allocation['employee_count'])}。"
        )

    lines = [
        f"# 法人企業統計から読む企業部門の増益と配分 — {release.release_label_ja}",
        "",
        f"**STATUS: {status}**",
        "",
        (
            "【FACT】調査対象は、日本に本店を持つ資本金・出資金・基金が一千万円以上の営利法人等を"
            "母集団とする標本調査である。本文の主系列は金融業・保険業を除く全規模・全産業。"
            "金融業・保険業込みの全産業系列は別表として扱い、その経常利益は"
            f"{_claim_token(scope)}である。"
        ),
        "",
        "表記は【FACT】が構造化データまたは公表注記、【CALC】がそれらからの計算、【HYPOTHESIS】が外部一次資料による追加検証を要する解釈を示す。",
        "",
        "## 事実だけによる200字要約",
        "",
        summary,
        "",
        "## 最も重要な独自発見三点",
        "",
        (
            f"- 【CALC】営業利益の最大の押し上げは{top_industry_name}で、前年差は"
            f"{_claim_token(top_industry_delta)}、全体の純増への寄与率は"
            f"{_claim_token(top_industry_rate)}。正の増益寄与に占める集中度は、上位一業種"
            f"{_claim_token(concentration_rows[1])}、上位三業種{_claim_token(concentration_rows[3])}、"
            f"上位五業種{_claim_token(concentration_rows[5])}だった。最大業種の寄与が全体純増を"
            "上回るのは、他業種の減益が一部を相殺したためである。"
        ),
        "",
        (
            f"- 【CALC】資本金規模別では{capital_label}区分の営業利益前年差が"
            f"{_claim_token(capital_delta)}で、全規模の純増に対する寄与率は"
            f"{_claim_token(capital_rate)}。増益は規模別に均等ではない。"
        ),
        "",
        (
            "- 【CALC】経常利益と営業利益の水準差は"
            f"{_claim_token(gap_current)}、両利益の前年差の差は{_claim_token(gap_delta)}。"
            "営業外損益等を含む経常利益と営業利益を分けて読む必要がある。"
        ),
        "",
        "## 図表でみる増減額と集中",
        "",
        "![営業利益の業種別前年差](charts/operating_profit_industry_contribution.png)",
        "",
        "業種別寄与率は各業種の前年差を全産業の純増減で除した値である。純増が小さい場合や、増益業種と減益業種が相殺する場合は、寄与率が直感より大きくなる。",
        "",
        "![営業利益の資本金規模別前年差](charts/operating_profit_capital_contribution.png)",
        "",
        "## 営業利益と経常利益",
        "",
        (
            "【CALC】売上高営業利益率は"
            f"{_claim_token(operating_margin)}、売上高経常利益率は{_claim_token(ordinary_margin)}。"
            "後者には営業外損益等が入るため、両者の差は本業だけの説明には使えない。"
        ),
        "",
        "![利益率と営業利益・経常利益の差](charts/profit_margin_and_gap.png)",
        "",
        "## ソフトウェア込み・除く設備投資",
        "",
        (
            "【CALC】ソフトウェア投資額の逆算値は"
            f"{_claim_token(software_value)}、前年同期比は{_claim_token(software_rate)}。"
            "これは設備投資のソフトウェア込み系列から除く系列を差し引いた値で、独立した直接公表系列ではない。"
        ),
        "",
        "![設備投資のソフトウェア込み・除く・差額](charts/capex_software_bridge.png)",
        "",
        "季節調整済み前期比は原数値の前年同期比とは別系列である。",
        "",
        "| 項目 | 【CALC】季節調整済み前期比 |",
        "|---|---:|",
        f"| 売上高 | {_claim_token(seasonal['sales'])} |",
        f"| 営業利益 | {_claim_token(seasonal['operating_profit'])} |",
        f"| 経常利益 | {_claim_token(seasonal['ordinary_profit'])} |",
        f"| 設備投資（ソフトウェア除く） | {_claim_token(seasonal['capex_excluding_software'])} |",
        f"| 設備投資（ソフトウェア込み） | {_claim_token(seasonal['capex_including_software'])} |",
        "",
        "## 利益・給与・人員・設備投資の配分",
        "",
        "![利益・給与・人員・設備投資の前年比](charts/allocation_growth.png)",
        "",
        allocation_growth_claims,
        "" if allocation_growth_claims else "",
        (
            "【CALC】従業員一人当たり給与総額の四半期概算は"
            f"{_claim_token(allocation['employee_pay_per_person_approx'])}。"
            "同じ企業部門の資金面では、現預金の前年差が"
            f"{_claim_token(allocation['cash_and_deposits'])}、借入金合計の前年差が"
            f"{_claim_token(allocation['total_borrowings_derived'])}、支払利息等の前年差が"
            f"{_claim_token(allocation['interest_expense'])}だった。"
        ),
        "",
        "図は営業利益、給与・賞与総額、従業員数、ソフトウェア込み設備投資の前年同期比を同じ尺度に置く。伸び率の差は配分の同時変化を示すが、企業ごとの配分判断や因果を直接示すものではない。",
        "",
        "## 解釈上の限界",
        "",
        "- 金額は名目値であり、物価変動を除いた実質値ではない。「過去最高」の判定は本分析では行わない。",
        "",
        "- 標本調査から母集団を推計した四半期の仮決算計数であり、後日の改訂、標本誤差、季節性の影響を受ける。",
        "",
        "- 業種・規模別寄与は算術的な分解であり、需要、価格、為替、コストなどの原因を識別しない。純増減がゼロに近いと寄与率は不安定になる。",
        "",
        "- 上位業種の集中度は、重複しない公表主要業種の区分粒度に依存し、製造業は大区分のまま扱う。",
        "",
        "- ソフトウェア投資は二系列の差額による逆算で、公表値の丸めや表章変更の影響を受ける。欠損時は計算せず、ゼロで補完しない。",
        "",
        "- 一人当たり給与総額は四半期の給与・賞与総額を期末従業員数で除した概算で、個人の月給や可処分所得ではない。",
        "",
        "- 金融業・保険業込み表と除く表では利用できる項目が異なる。本文の売上高、営業利益、寄与分析に両範囲を混在させていない。",
        "",
        "## 使用データと再現方法",
        "",
        f"対象公表は財務省「四半期別法人企業統計調査」{release.release_label_ja}、公開日は {release.publication_date}。数値の正本は e-Stat の構造化データ、公表 PDF は定義・注記・ランキングの照合、財務省 Excel は公表増減率の照合に使った。",
        "",
        "取得 URL、取得日時、表番号、公開日、SHA-256 は `data_manifest.json` に保存している。raw ファイルは取得時のバイト列を変更せず、処理後データと記事は次のコマンドで再生成できる。",
        "",
        "```bash",
        f"make run RELEASE={release.release_id}",
        "```",
        "",
        "計算式、フィルター、出所、表示値は `claims.csv`、検証結果と表章・分類・欠損ログは `audit_report.md` を参照されたい。",
        "",
        "## 外部資料で追加検証すべき仮説",
        "",
    ]
    for row in anchors["hypotheses"]:
        lines.extend([f"- {row['claim_text']}<!-- claim: {row['claim_id']} -->", ""])

    article = "\n".join(lines).rstrip() + "\n"
    markers = _CLAIM_MARKER_RE.findall(article)
    expected_ids = article_claims["claim_id"].astype(str).tolist()
    if len(markers) != len(set(markers)):
        raise ValueError("Article renderer produced duplicate claim markers")
    if set(markers) != set(expected_ids):
        missing = sorted(set(expected_ids) - set(markers))
        extra = sorted(set(markers) - set(expected_ids))
        raise ValueError(f"Article claim mismatch; missing={missing}, extra={extra}")
    return article
