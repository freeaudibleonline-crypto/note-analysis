from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Release:
    CONFIG_KIND: str
    release_id: str
    release_label_ja: str
    target_period_code: str
    target_period_label: str
    prior_yoy_period_code: str
    prior_qoq_period_code: str
    publication_date: str
    e_stat_tables: dict
    mof_pdf_url: str
    mof_percent_excel_url: str
    mof_results_url: str
    pdf_reference_checks: dict

    @property
    def period_codes(self) -> list[str]:
        return [self.prior_yoy_period_code, self.prior_qoq_period_code, self.target_period_code]


def load_release(release_id: str) -> Release:
    path = PROJECT_ROOT / "config" / f"release_{release_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Release configuration not found: {path}")
    return Release(**json.loads(path.read_text(encoding="utf-8")))


MONETARY_METRICS = {
    "cash_and_deposits",
    "financial_institution_borrowings_current",
    "other_borrowings_current",
    "financial_institution_borrowings_long_term",
    "other_borrowings_long_term",
    "capex_including_software",
    "capex_excluding_software",
    "sales",
    "operating_profit",
    "interest_expense",
    "ordinary_profit",
    "employee_wages",
    "employee_bonuses",
}


METRIC_RULES: tuple[tuple[str, str, str], ...] = (
    ("cash_and_deposits", "現金・預金(当期末流動資産)", "現預金"),
    ("financial_institution_borrowings_current", "金融機関借入金(当期末流動負債)", "金融機関借入金（流動）"),
    ("other_borrowings_current", "その他の借入金(当期末流動負債)", "その他借入金（流動）"),
    ("financial_institution_borrowings_long_term", "金融機関借入金(当期末固定負債)", "金融機関借入金（固定）"),
    ("other_borrowings_long_term", "その他の借入金(当期末固定負債)", "その他借入金（固定）"),
    ("capex_including_software", "設備投資(当期末新設固定資産合計)", "設備投資（ソフトウェア込み）"),
    ("capex_excluding_software", "ソフトウェアを除く設備投資(当期末新設固定資産)", "設備投資（ソフトウェア除く）"),
    ("sales", "売上高(当期末)", "売上高"),
    ("operating_profit", "営業利益(当期末)", "営業利益"),
    ("interest_expense", "支払利息等(当期末)", "支払利息等"),
    ("ordinary_profit", "経常利益(当期末)", "経常利益"),
    ("employee_count", "従業員数(当期末)", "従業員数"),
    ("employee_wages", "従業員給与(当期末)", "従業員給与"),
    ("employee_bonuses", "従業員賞与(当期末)", "従業員賞与"),
)

# Table 4 uses shorter labels than raw Tables 1–3.  Keep aliases explicit so
# a label change cannot silently map to a different statistic.
METRIC_SOURCE_ALIASES = {
    "capex_including_software": (
        "設備投資(当期末新設固定資産合計)",
        "ソフトウェアを含む設備投資(当期末)",
    ),
    "capex_excluding_software": (
        "ソフトウェアを除く設備投資(当期末新設固定資産)",
        "ソフトウェアを除く設備投資(当期末)",
    ),
}


PRIMARY_ANALYSIS_METRICS = (
    "sales",
    "operating_profit",
    "ordinary_profit",
    "capex_including_software",
    "capex_excluding_software",
)


METRIC_STOCK_FLOW = {
    "cash_and_deposits": "STOCK",
    "financial_institution_borrowings_current": "STOCK",
    "other_borrowings_current": "STOCK",
    "financial_institution_borrowings_long_term": "STOCK",
    "other_borrowings_long_term": "STOCK",
    "employee_count": "PERIOD_END_STOCK",
    "sales": "FLOW",
    "operating_profit": "FLOW",
    "ordinary_profit": "FLOW",
    "interest_expense": "FLOW",
    "capex_including_software": "FLOW",
    "capex_excluding_software": "FLOW",
    "employee_wages": "FLOW",
    "employee_bonuses": "FLOW",
    "employee_total_pay_derived": "FLOW",
    "employee_pay_per_person_approx": "FLOW_PER_PERIOD_END_PERSON",
}


# Mutually exclusive published aggregates.  They intentionally avoid detailed rows
# that would double count a parent aggregate in contribution rankings.
MAJOR_INDUSTRY_NAMES = (
    "製造業",
    "農林水産業(集約)",
    "鉱業、採石業、砂利採取業",
    "建設業",
    "電気業",
    "ガス・熱供給・水道業",
    "情報通信業",
    "運輸業、郵便業(集約)",
    "卸売業・小売業(集約)",
    "不動産業、物品賃貸業(集約)",
    "サービス業(集約)",
)


CAPITAL_COMPONENT_NAMES = (
    "10億円以上",
    "1億円以上 - 10億円未満",
    "1千万円以上 - 1億円未満",
)


REQUIRED_OUTPUTS = (
    "data_manifest.json",
    "processed_quarterly.parquet",
    "industry_contributions.csv",
    "capital_size_contributions.csv",
    "claims.csv",
    "audit_report.md",
    "article.md",
)
