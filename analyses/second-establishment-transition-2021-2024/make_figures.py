from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np
import pandas as pd
from PIL import Image


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "output"
DATA = ROOT / "data"
FONT_PATH = ROOT / "fonts" / "NotoSansJP-Regular.ttf"

font_manager.fontManager.addfont(str(FONT_PATH))
FONT = font_manager.FontProperties(fname=str(FONT_PATH))
FONT_BOLD = font_manager.FontProperties(fname=str(FONT_PATH), weight="bold")

BG = "#FBFBF8"
PAPER = "#FFFFFF"
INK = "#18212A"
MUTED = "#65717C"
GRID = "#DDE2E5"
BLUE = "#2678C9"
LIGHT_BLUE = "#C7DEF2"
ORANGE = "#E66A3A"
LIGHT_ORANGE = "#F7D8C9"
GREEN = "#168B70"
LIGHT_GREEN = "#D8EEE8"
RED = "#C54E47"
PURPLE = "#7A68A6"
GRAY = "#94A0AA"
PALE = "#EEF3F6"

MODEL_LABELS = {
    "binary_logit": "独立二値ロジット",
    "ordered_logit": "順序ロジット",
    "poisson": "ポアソン",
    "negbin": "負の二項",
}
MODEL_COLORS = {
    "binary_logit": BLUE,
    "ordered_logit": GREEN,
    "poisson": ORANGE,
    "negbin": PURPLE,
}
MODEL_MARKERS = {
    "binary_logit": "o",
    "ordered_logit": "s",
    "poisson": "^",
    "negbin": "D",
}


def apply_style() -> None:
    plt.rcParams.update(
        {
            "font.family": FONT.get_name(),
            "axes.unicode_minus": False,
            "figure.facecolor": BG,
            "axes.facecolor": BG,
            "savefig.facecolor": BG,
            "text.color": INK,
            "axes.labelcolor": INK,
            "xtick.color": MUTED,
            "ytick.color": INK,
        }
    )


def save(fig: plt.Figure, filename: str, expected_size: tuple[int, int]) -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    path = ASSETS / filename
    tmp = path.with_name(f".{path.stem}.part{path.suffix}")
    try:
        fig.canvas.draw()
        fig.savefig(tmp, dpi=100, facecolor=fig.get_facecolor())
        with Image.open(tmp) as im:
            im.load()
            if im.size != expected_size or im.getbbox() is None:
                raise AssertionError(f"invalid image {filename}: {im.size}")
        tmp.replace(path)
    finally:
        plt.close(fig)
        if tmp.exists():
            tmp.unlink()


def title_block(fig: plt.Figure, title: str, subtitle: str, title_size: float = 33) -> None:
    fig.text(0.055, 0.962, title, ha="left", va="top", fontproperties=FONT_BOLD,
             fontsize=title_size, color=INK)
    fig.text(0.055, 0.905, subtitle, ha="left", va="top", fontproperties=FONT,
             fontsize=18.5, color=MUTED)


def footer(fig: plt.Figure, text: str, y: float = 0.025, size: float = 14.5) -> None:
    fig.text(0.055, y, text, ha="left", va="bottom", fontproperties=FONT,
             fontsize=size, color=MUTED)


def rounded_box(ax, xy, width, height, face=PAPER, edge=GRID, radius=0.02, lw=1.3):
    box = FancyBboxPatch(
        xy,
        width,
        height,
        boxstyle=f"round,pad=0.012,rounding_size={radius}",
        linewidth=lw,
        edgecolor=edge,
        facecolor=face,
        transform=ax.transAxes,
    )
    ax.add_patch(box)
    return box


def make_cover() -> None:
    scope = pd.read_csv(DATA / "a3" / "analysis_scope.csv")
    exact = pd.read_csv(DATA / "a3" / "exact_industries.csv")
    boundary = pd.read_csv(DATA / "a3" / "boundary_sensitivity.csv")
    total_industries = len(scope)
    main_industries = int(exact["publication_role"].eq("main").sum())
    n_markets = int(exact["transition_analysis_units"].unique().item())
    affected = int(boundary.loc[boundary["metric"].eq("affected_analysis_units"), "value"].item())

    fig = plt.figure(figsize=(12.8, 6.7), facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")

    ax.add_patch(FancyBboxPatch((0.03, 0.06), 0.94, 0.88,
                                boxstyle="round,pad=0.018,rounding_size=0.035",
                                facecolor=PAPER, edgecolor=GRID, linewidth=1.3))
    fig.text(0.075, 0.83, "人口何人の町に「2軒目」はあるのか、その後",
             fontproperties=FONT_BOLD, fontsize=29, color=INK, va="top")
    fig.text(0.075, 0.69, "「2軒以上ある町」は、3年でどう変わったか",
             fontproperties=FONT_BOLD, fontsize=39, color=INK, va="top")
    fig.text(0.077, 0.55, f"2021 → 2024　境界変更{affected}地域を除く{n_markets:,}分析単位",
             fontproperties=FONT, fontsize=21, color=MUTED, va="top")

    for x, y, label, face, color in [
        (0.10, 0.20, "2", LIGHT_ORANGE, ORANGE),
        (0.33, 0.20, "1以下", PALE, INK),
        (0.59, 0.20, "1", LIGHT_BLUE, BLUE),
        (0.82, 0.20, "2以上", LIGHT_GREEN, GREEN),
    ]:
        ax.add_patch(FancyBboxPatch((x - 0.065, y - 0.055), 0.13, 0.11,
                                    boxstyle="round,pad=0.012,rounding_size=0.024",
                                    facecolor=face, edgecolor="none"))
        fig.text(x, y, label, ha="center", va="center", fontproperties=FONT_BOLD,
                 fontsize=25, color=color)
    for start, end, color in [((0.18, 0.20), (0.255, 0.20), ORANGE),
                              ((0.67, 0.20), (0.745, 0.20), GREEN)]:
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=22,
                                    linewidth=2.2, color=color, transform=ax.transAxes))
    fig.text(0.075, 0.10, f"比較可能性と法人カバー率を守ると、{total_industries}業種の主結果は{main_industries}業種になった。",
             fontproperties=FONT, fontsize=18, color=MUTED)
    save(fig, "cover_sequel_second_establishment.png", (1280, 670))


def make_scope_flow() -> None:
    scope = pd.read_csv(DATA / "a3" / "analysis_scope.csv")
    exact = pd.read_csv(DATA / "a3" / "exact_industries.csv")
    group_counts = scope["comparison_group"].value_counts()
    total_industries = len(scope)
    exact_count = int(group_counts["exact_comparison"])
    endpoint_count = int(group_counts["retail_endpoint_scenarios"])
    reference_count = int(group_counts["retail_reference"])
    excluded_count = int(group_counts["excluded"])
    role_counts = exact["publication_role"].value_counts()

    fig = plt.figure(figsize=(10.8, 15.0), facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    title_block(fig, f"{total_industries}業種から、産業分類上の点比較は{exact_count}業種", "分類整合と2021年法人カバー率で、公開上の位置づけを分けた")

    rounded_box(ax, (0.32, 0.785), 0.36, 0.085, face=INK, edge=INK)
    fig.text(0.50, 0.838, f"前稿の{total_industries}業種", ha="center", va="center",
             fontproperties=FONT_BOLD, fontsize=26, color=PAPER)
    fig.text(0.50, 0.805, "2021年 → 2024年", ha="center", va="center",
             fontproperties=FONT, fontsize=17, color="#DDE4EA")

    branch_y = 0.61
    branches = [
        (0.055, 0.29, f"分類上の点比較 {exact_count}", "公式定義を接続", LIGHT_GREEN, GREEN),
        (0.36, 0.24, f"端点シナリオ {endpoint_count}", f"小売{endpoint_count}業種", LIGHT_BLUE, BLUE),
        (0.615, 0.16, f"参考 {reference_count}", "医薬品・化粧品", "#ECE8F4", PURPLE),
        (0.79, 0.155, f"除外 {excluded_count}", "百貨店・総合スーパー", "#F1F2F3", GRAY),
    ]
    for x, w, heading, body, face, color in branches:
        rounded_box(ax, (x, branch_y), w, 0.105, face=face, edge=color, lw=1.5)
        fig.text(x + w / 2, branch_y + 0.070, heading, ha="center", va="center",
                 fontproperties=FONT_BOLD, fontsize=22, color=color)
        fig.text(x + w / 2, branch_y + 0.031, body, ha="center", va="center",
                 fontproperties=FONT, fontsize=13.5, color=INK)
        ax.add_patch(FancyArrowPatch((0.50, 0.785), (x + w / 2, branch_y + 0.105),
                                    arrowstyle="-|>", mutation_scale=15, linewidth=1.5,
                                    color=GRID, transform=ax.transAxes))

    fig.text(0.055, 0.545, f"点比較{exact_count}業種を、2021年法人比でさらに分ける", ha="left",
             fontproperties=FONT_BOLD, fontsize=18, color=INK)
    exact_groups = [
        (0.055, 0.425, 0.29, 0.10, f"主結果 {int(role_counts['main'])}", "葬儀業・病院", "2021年法人比80%以上", LIGHT_ORANGE, ORANGE),
        (0.055, 0.290, 0.29, 0.10, f"副次結果 {int(role_counts['secondary'])}", "普通洗濯・一般診療所", "2021年法人比50〜80%", LIGHT_BLUE, BLUE),
        (0.055, 0.125, 0.29, 0.135, f"法人セグメント {int(role_counts['corporate_segment_appendix'])}", "理容・美容・学習塾\n歯科・自動車整備", "2021年法人比50%未満", "#F1F2F3", GRAY),
    ]
    for x, y, w, h, heading, body, sub, face, color in exact_groups:
        rounded_box(ax, (x, y), w, h, face=face, edge=color)
        fig.text(x + 0.02, y + h - 0.022, heading, ha="left", va="top",
                 fontproperties=FONT_BOLD, fontsize=20, color=color)
        fig.text(x + 0.02, y + h - 0.052, body, ha="left", va="top",
                 fontproperties=FONT, fontsize=14.5, color=INK, linespacing=1.3)
        fig.text(x + w - 0.018, y + 0.014, sub, ha="right", va="bottom",
                 fontproperties=FONT, fontsize=11.5, color=MUTED)
        ax.add_patch(FancyArrowPatch((0.20, branch_y), (x + w / 2, y + h),
                                    arrowstyle="-|>", mutation_scale=13, linewidth=1.3,
                                    color=GRID, transform=ax.transAxes))

    rounded_box(ax, (0.39, 0.39), 0.55, 0.13, face=PAPER, edge=GRID)
    fig.text(0.42, 0.482, "小売4業種は、一つの点にしない", fontproperties=FONT_BOLD,
             fontsize=21, color=INK)
    fig.text(0.42, 0.444, "均一価格店5661の流出元が特定できないため、\n業種別の端点シナリオで幅を示す。",
             fontproperties=FONT, fontsize=15, color=MUTED, va="top", linespacing=1.45)

    rounded_box(ax, (0.39, 0.21), 0.55, 0.13, face=PAPER, edge=GRID)
    fig.text(0.42, 0.302, "603は参考、561は除外", fontproperties=FONT_BOLD,
             fontsize=21, color=INK)
    fig.text(0.42, 0.264, "区間が狭くても同一定義とは限らない。\n比較可能性は、数値の近さではなく公式定義で判定した。",
             fontproperties=FONT, fontsize=15, color=MUTED, va="top", linespacing=1.45)

    footer(fig, "出所：公式産業分類新旧対照表・内容定義を用いた分類整合監査。")
    save(fig, "fig01_analysis_scope.png", (1080, 1500))


def make_definition_card() -> None:
    exact = pd.read_csv(DATA / "a3" / "exact_industries.csv")
    example_row = exact.loc[exact["industry_name"].eq("葬儀業")].iloc[0]
    down_example = f"例：{int(example_row['n_down_2_to_le1'])}/{int(example_row['n_units_2021_eq2'])}"
    up_example = f"例：{int(example_row['n_up_1_to_ge2'])}/{int(example_row['n_units_2021_eq1'])}"

    fig = plt.figure(figsize=(10.8, 10.5), facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    title_block(fig, "今回測るのは、境界をまたいだ集計状態", "個別事業所を追跡していないため、参入・退出とは呼ばない")

    cards = [
        (0.06, 0.54, 0.41, 0.25, LIGHT_ORANGE, ORANGE,
         "閾値下向き遷移", "2021年：2", "2024年：0 または 1", down_example),
        (0.53, 0.54, 0.41, 0.25, LIGHT_BLUE, BLUE,
         "閾値上向き遷移", "2021年：1", "2024年：2以上", up_example),
    ]
    for x, y, w, h, face, color, heading, start, end, example in cards:
        rounded_box(ax, (x, y), w, h, face=face, edge=color, lw=1.6)
        fig.text(x + 0.025, y + h - 0.045, heading, fontproperties=FONT_BOLD,
                 fontsize=22, color=color, va="top")
        fig.text(x + w / 2, y + 0.135, start, ha="center", va="center",
                 fontproperties=FONT_BOLD, fontsize=24, color=INK)
        ax.add_patch(FancyArrowPatch((x + w / 2, y + 0.112), (x + w / 2, y + 0.085),
                                    arrowstyle="-|>", mutation_scale=16, linewidth=2,
                                    color=color, transform=ax.transAxes))
        fig.text(x + w / 2, y + 0.058, end, ha="center", va="center",
                 fontproperties=FONT_BOLD, fontsize=21, color=INK)
        fig.text(x + w - 0.02, y + 0.018, example, ha="right", va="bottom",
                 fontproperties=FONT, fontsize=14, color=MUTED)

    rounded_box(ax, (0.06, 0.22), 0.88, 0.22, face=PAPER, edge=GRID)
    fig.text(0.09, 0.385, "x/nを必ず併記", fontproperties=FONT_BOLD, fontsize=22, color=INK)
    fig.text(0.09, 0.342,
             "二つの割合は、2021年に「2」だった地域と「1」だった地域という別々の分母を持つ。\n"
             "割合の差を、そのまま純減数とは読まない。純横断は全状態の行列から別に数える。",
             fontproperties=FONT, fontsize=16, color=MUTED, va="top", linespacing=1.55)
    fig.text(0.09, 0.255, "× 閉店率　× 退出率　× 参入率　× 因果効果",
             fontproperties=FONT_BOLD, fontsize=19, color=RED)

    footer(fig, "対象は2021年6月1日と2024年6月1日の法人事業所数。途中の変動は観測しない。")
    save(fig, "eq01_transition_definitions.png", (1080, 1050))


def make_transition_rates() -> None:
    df = pd.read_csv(DATA / "a3" / "exact_industries.csv")
    order = ["葬儀業", "病院", "普通洗濯業", "一般診療所", "学習塾", "理容業", "美容業", "自動車整備業", "歯科診療所"]
    df = df.set_index("industry_name").loc[order].reset_index()

    fig = plt.figure(figsize=(10.8, 18.0), facecolor=BG)
    ax = fig.add_axes([0.30, 0.11, 0.62, 0.72])
    y = np.arange(len(df))[::-1]

    for yi, tier in zip(y, df["tier"]):
        color = {1: LIGHT_ORANGE, 2: LIGHT_BLUE, 3: "#F0F2F3"}[int(tier)]
        ax.axhspan(yi - 0.43, yi + 0.43, color=color, alpha=0.58, zorder=0)

    for yi, row in zip(y, df.itertuples(index=False)):
        y_minus, y_plus = yi + 0.12, yi - 0.12
        ax.scatter(row.down_2_to_le1_pct, y_minus, s=85, color=ORANGE, marker="o", zorder=3)
        ax.scatter(row.up_1_to_ge2_pct, y_plus, s=78, color=BLUE, marker="s", zorder=3)
        ax.text(48.0, yi + 0.12, f"↓ {row.n_down_2_to_le1}/{row.n_units_2021_eq2}",
                fontproperties=FONT_BOLD, fontsize=13.5, color=ORANGE, va="center")
        ax.text(48.0, yi - 0.18, f"↑ {row.n_up_1_to_ge2}/{row.n_units_2021_eq1}",
                fontproperties=FONT, fontsize=13.5, color=BLUE, va="center")

    ax.set_yticks(y)
    ax.set_yticklabels([f"{n}\n2021年法人比 {c:.1f}%" for n, c in zip(df["industry_name"], df["corporate_coverage_pct_2021_all1741"])],
                       fontproperties=FONT, fontsize=17)
    ax.set_xlim(0, 61)
    ax.set_xticks([0, 10, 20, 30, 40])
    ax.set_xticklabels(["0%", "10%", "20%", "30%", "40%"], fontproperties=FONT, fontsize=14)
    ax.grid(axis="x", color=GRID, linewidth=1)
    ax.tick_params(axis="y", length=0, pad=12)
    for s in ax.spines.values():
        s.set_visible(False)

    title_block(fig, "瀬戸際の地域は、両方向に動いた", "橙＝2→1以下、青＝1→2以上。別々の分母を持つ独立指標")
    fig.text(0.055, 0.852,
             "背景：橙＝主結果（2021年法人比80%以上）　青＝副次（50〜80%）　灰＝法人セグメント参考（50%未満）",
             fontproperties=FONT, fontsize=14.2, color=MUTED)
    footer(fig, "主分析1,706地域。割合の分母は異なるため、橙−青を純減とは解釈しない。")
    save(fig, "fig02_transition_rates_exact9.png", (1080, 1800))


def make_mean_vs_net() -> None:
    df = pd.read_csv(DATA / "a3" / "exact_industries.csv")
    role_colors = {"main": ORANGE, "secondary": BLUE, "corporate_segment_appendix": GRAY}
    role_sizes = {"main": 145, "secondary": 125, "corporate_segment_appendix": 90}

    fig = plt.figure(figsize=(10.8, 13.5), facecolor=BG)
    ax = fig.add_axes([0.15, 0.20, 0.78, 0.59])
    ax.axvspan(0, 1.08, ymin=0, ymax=72 / 89, color=LIGHT_ORANGE, alpha=0.35, zorder=0)
    ax.axhline(0, color=INK, lw=1.25)
    ax.axvline(0, color=INK, lw=1.25)
    ax.grid(color=GRID, linewidth=0.8, zorder=0)

    offsets = {
        "葬儀業": (8, -19), "病院": (-48, 9), "普通洗濯業": (8, 8),
        "一般診療所": (-113, -18), "理容業": (8, -18), "美容業": (8, 8),
        "学習塾": (8, -19), "歯科診療所": (-112, 8), "自動車整備業": (8, 8),
    }
    for row in df.itertuples(index=False):
        color = role_colors[row.publication_role]
        ax.scatter(row.mean_establishment_count_change, row.net_change_units_ge2,
                   s=role_sizes[row.publication_role], color=color, edgecolor=PAPER,
                   linewidth=1.2, zorder=3)
        dx, dy = offsets[row.industry_name]
        ax.annotate(row.industry_name, (row.mean_establishment_count_change, row.net_change_units_ge2),
                    xytext=(dx, dy), textcoords="offset points", fontproperties=FONT,
                    fontsize=13.5, color=INK)

    ax.set_xlim(-2.15, 1.15)
    ax.set_ylim(-72, 17)
    ax.set_xlabel("1地域あたり法人事業所数の平均変化", fontproperties=FONT, fontsize=16, labelpad=13)
    ax.set_ylabel("「2以上」地域の純増減（地域）", fontproperties=FONT, fontsize=16, labelpad=12)
    ax.tick_params(labelsize=13)
    for s in ax.spines.values():
        s.set_visible(False)

    title_block(fig, "平均が増えても、「2以上」の地域は減り得る", "横軸＝事業所数の平均差、縦軸＝2以上境界の上向き−下向き純横断")
    fig.text(0.55, 0.265, "平均増・複数性減", fontproperties=FONT_BOLD,
             fontsize=18, color=ORANGE)
    handles = [
        Line2D([], [], marker="o", linestyle="", color=ORANGE, markersize=9, label="主結果"),
        Line2D([], [], marker="o", linestyle="", color=BLUE, markersize=9, label="副次"),
        Line2D([], [], marker="o", linestyle="", color=GRAY, markersize=9, label="法人セグメント参考"),
    ]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.0, -0.13), ncol=3,
              frameon=False, prop=FONT, fontsize=13, handletextpad=0.4, columnspacing=1.5)
    footer(fig, "葬儀業・一般診療所などで二つの指標の符号が逆。集中の原因までは識別しない。", y=0.035)
    save(fig, "fig03_mean_change_vs_net_crossing.png", (1080, 1350))


def make_retail_bounds() -> None:
    df = pd.read_csv(DATA / "a3" / "retail_endpoint_scenarios.csv")
    df["p_minus_lower_pct"] = df[["down_2_to_le1_exclude_566_pct", "down_2_to_le1_include_all_566_pct"]].min(axis=1)
    df["p_minus_upper_pct"] = df[["down_2_to_le1_exclude_566_pct", "down_2_to_le1_include_all_566_pct"]].max(axis=1)
    df["p_minus_width_pt"] = df["p_minus_upper_pct"] - df["p_minus_lower_pct"]
    order = ["燃料小売業", "各種食料品小売業", "書籍・文房具小売業", "鮮魚小売業"]
    df = df.set_index("industry_name").loc[order].reset_index()

    fig = plt.figure(figsize=(10.8, 12.5), facecolor=BG)
    ax = fig.add_axes([0.28, 0.20, 0.62, 0.56])
    y = np.arange(len(df))[::-1]
    widths = df["p_minus_width_pt"]
    colors = [BLUE] * len(df)
    for yi, row, color in zip(y, df.itertuples(index=False), colors):
        ax.plot([row.p_minus_lower_pct, row.p_minus_upper_pct], [yi, yi],
                lw=10, color=color, solid_capstyle="round")
        ax.scatter([row.p_minus_lower_pct, row.p_minus_upper_pct], [yi, yi],
                   s=54, color=PAPER, edgecolor=color, linewidth=2, zorder=3)
        ax.text(row.p_minus_lower_pct - 0.8, yi + 0.22, f"{row.p_minus_lower_pct:.2f}%",
                ha="right", fontproperties=FONT, fontsize=13, color=color)
        ax.text(row.p_minus_upper_pct + 0.8, yi + 0.22, f"{row.p_minus_upper_pct:.2f}%",
                ha="left", fontproperties=FONT, fontsize=13, color=color)
        ax.text(38.0, yi - 0.18, f"不確定 {row.uncertain_analysis_units}地域",
                ha="left", fontproperties=FONT, fontsize=13, color=MUTED)

    ax.set_yticks(y)
    ax.set_yticklabels(df["industry_name"], fontproperties=FONT, fontsize=17)
    ax.set_xlim(0, 52)
    ax.set_xticks([0, 10, 20, 30, 40])
    ax.set_xticklabels(["0%", "10%", "20%", "30%", "40%"], fontproperties=FONT, fontsize=14)
    ax.grid(axis="x", color=GRID)
    ax.tick_params(axis="y", length=0, pad=10)
    for s in ax.spines.values():
        s.set_visible(False)

    title_block(fig, "小売4業種は、一つの率にできなかった", "2→1以下率の業種別・周辺的最悪ケース範囲")
    note_ax = fig.add_axes([0.055, 0.075, 0.89, 0.09])
    note_ax.axis("off")
    rounded_box(note_ax, (0, 0), 1, 1, face=PAPER, edge=GRID)
    fig.text(0.08, 0.133, "重要", fontproperties=FONT_BOLD, fontsize=16, color=RED)
    fig.text(0.16, 0.136,
             "各業種のシナリオUは同時に成立しない。合算・交差・業種ランキングは禁止。",
             fontproperties=FONT, fontsize=14.5, color=INK, va="center")
    fig.text(0.16, 0.102,
             "下向き率ではUが下端、Lが上端。これは95%信頼区間ではない。",
             fontproperties=FONT, fontsize=14.5, color=MUTED, va="center")
    save(fig, "fig04_retail_partial_identification.png", (1080, 1250))


def make_boundary_card() -> None:
    boundary = pd.read_csv(DATA / "a3" / "boundary_sensitivity.csv")
    values = dict(zip(boundary["metric"], boundary["value"]))
    affected = int(values["affected_analysis_units"])
    transfer_like = int(values["mixed_sign_and_zero_sum"])
    max_difference = float(values["max_abs_down_2_to_le1_difference_pt"])
    events = int(values["boundary_change_events"])
    pairs = int(values["unique_pairs"])
    components = int(values["connected_components"])

    fig = plt.figure(figsize=(10.8, 9.5), facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    title_block(fig, "自治体コードが同じでも、境界は動く", "2021年6月から2024年6月の境界変更を全地域で監査")
    cards = [
        (0.055, 0.48, 0.27, 0.25, f"{affected}", "影響地域", "主分析から除外", BLUE),
        (0.365, 0.48, 0.27, 0.25, f"{transfer_like}組合せ", "移管整合型", "成分×業種", ORANGE),
        (0.675, 0.48, 0.27, 0.25, f"{max_difference:.2f}pt", "最大感度", "下向き率の最大差", GREEN),
    ]
    for x, y, w, h, number, heading, body, color in cards:
        rounded_box(ax, (x, y), w, h, face=PAPER, edge=color, lw=1.7)
        fig.text(x + w / 2, y + 0.165, number, ha="center", va="center",
                 fontproperties=FONT_BOLD, fontsize=40, color=color)
        fig.text(x + w / 2, y + 0.100, heading, ha="center", va="center",
                 fontproperties=FONT_BOLD, fontsize=18, color=INK)
        fig.text(x + w / 2, y + 0.045, body, ha="center", va="center",
                 fontproperties=FONT, fontsize=13.5, color=MUTED)

    rounded_box(ax, (0.055, 0.20), 0.89, 0.17, face=PALE, edge=GRID)
    fig.text(0.085, 0.322, "なぜ除外するのか", fontproperties=FONT_BOLD, fontsize=20, color=INK)
    fig.text(0.085, 0.279,
             "土地の移管で、事業所の自治体帰属が付け替わることがある。\n"
             "この集計上の振替を、閉店・開業のように誤読しないため除外する。",
             fontproperties=FONT, fontsize=15, color=MUTED, va="top", linespacing=1.5)
    footer(fig, f"{events}イベントを{pairs}ペア・{components}連結成分に整理。全1,741地域を含む結果も感度分析として確認。")
    save(fig, "table01_boundary_change_sensitivity.png", (1080, 950))


def make_appendix_ratio() -> None:
    raw = pd.read_csv(DATA / "phase1" / "model_sensitivity.csv")
    models = list(MODEL_LABELS)
    if len(raw) != 60 or set(raw["model"]) != set(models):
        raise AssertionError("unexpected model-sensitivity input")

    order = (raw[raw.model.eq("binary_logit")]
             .sort_values("s5_s2", ascending=True)["industry_name"].tolist())
    robust = {}
    for name, g in raw.groupby("industry_name"):
        g = g.set_index("model").loc[models]
        robust[name] = bool((g["s5_s2_ci_lo"] > 1).all())

    fig = plt.figure(figsize=(10.8, 19.0), facecolor=BG)
    title_block(fig, "正規化境界比 s5/s2：4仕様の比較",
                "点と線は各仕様の推定値・95%区間。✓は4仕様すべてで区間が1を上回る業種")
    gs = fig.add_gridspec(1, 3, left=0.055, right=0.975, bottom=0.10, top=0.84,
                          width_ratios=[2.60, 3.25, 1.60], wspace=0.02)
    ax_lab, ax, ax_val = (fig.add_subplot(gs[0, i]) for i in range(3))
    y = np.arange(len(order))
    offsets = {"binary_logit": 0.24, "ordered_logit": 0.08,
               "poisson": -0.08, "negbin": -0.24}
    for model in models:
        g = raw[raw.model.eq(model)].set_index("industry_name").loc[order]
        yy = y + offsets[model]
        xerr = np.vstack([g["s5_s2"] - g["s5_s2_ci_lo"],
                          g["s5_s2_ci_hi"] - g["s5_s2"]])
        ax.errorbar(g["s5_s2"], yy, xerr=xerr, fmt=MODEL_MARKERS[model],
                    color=MODEL_COLORS[model], ecolor=MODEL_COLORS[model], alpha=0.92,
                    elinewidth=1.0, capsize=2.3, markersize=5.8,
                    label=MODEL_LABELS[model])
    ax.axvline(1, color=INK, linestyle="--", linewidth=1.5)
    ax.axvline(1.11, color=ORANGE, linestyle=":", linewidth=1.4)
    ax.set_xlim(0.72, 2.82)
    ax.set_ylim(-0.72, len(order) - 0.28)
    ax.set_yticks([])
    ax.set_xticks([0.75, 1.0, 1.5, 2.0, 2.5])
    ax.tick_params(axis="x", labelsize=16)
    ax.grid(axis="x", color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    for side in (ax_lab, ax_val):
        side.set_xlim(0, 1)
        side.set_ylim(-0.72, len(order) - 0.28)
        side.set_axis_off()
    for i, name in enumerate(order):
        label = name.replace("，", "・")
        ax_lab.text(0.98, i, label, ha="right", va="center",
                    fontproperties=FONT, fontsize=18.5, color=INK)
        g = raw[raw.industry_name.eq(name)]
        ax_val.text(0.02, i, f"{g.s5_s2.min():.2f}–{g.s5_s2.max():.2f}",
                    ha="left", va="center", fontproperties=FONT,
                    fontsize=16.5, color=MUTED)
        if robust[name]:
            ax_val.text(0.86, i, "✓", ha="center", va="center",
                        fontproperties=FONT_BOLD, fontsize=19, color=GREEN)
    handles = [Line2D([0], [0], marker=MODEL_MARKERS[m], color=MODEL_COLORS[m],
                      linestyle="none", markersize=7, label=MODEL_LABELS[m])
               for m in models]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.09, 0.885),
               ncol=2, frameon=False, prop=FONT, fontsize=14.5,
               columnspacing=1.6, handletextpad=0.5)
    fig.text(0.785, 0.855, "4仕様の\n点推定レンジ", ha="left", va="top",
             fontproperties=FONT_BOLD, fontsize=13.5, color=MUTED, linespacing=1.2)
    fig.text(0.055, 0.052,
             "95%区間は自治体再標本化のパーセンタイル・ブートストラップ（二値500回、他3仕様200回）。",
             ha="left", va="bottom", fontproperties=FONT, fontsize=12.8, color=MUTED)
    fig.text(0.055, 0.028,
             "1.00は記述的参照線。1.11は単純ポアソンの参考値。右列は信頼区間ではない。競争の強さは識別しない。",
             ha="left", va="bottom", fontproperties=FONT, fontsize=12.8, color=MUTED)
    save(fig, "appendix_phase1_s5s2_4models.png", (1080, 1900))


def validate_assets() -> None:
    expected = {
        "cover_sequel_second_establishment.png": (1280, 670),
        "fig01_analysis_scope.png": (1080, 1500),
        "eq01_transition_definitions.png": (1080, 1050),
        "fig02_transition_rates_exact9.png": (1080, 1800),
        "fig03_mean_change_vs_net_crossing.png": (1080, 1350),
        "fig04_retail_partial_identification.png": (1080, 1250),
        "table01_boundary_change_sensitivity.png": (1080, 950),
        "appendix_phase1_s5s2_4models.png": (1080, 1900),
    }
    for name, size in expected.items():
        path = ASSETS / name
        with Image.open(path) as im:
            im.load()
            if im.size != size or im.getbbox() is None:
                raise AssertionError(f"invalid image {name}: {im.size}")


def main() -> None:
    global ASSETS
    parser = argparse.ArgumentParser(
        description="集計済みCSVからnote続編用のPNG図表8枚を再生成します。"
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="出力先。相対パスはリポジトリ直下を基準にします（既定: output）。",
    )
    args = parser.parse_args()
    requested_output = Path(args.output_dir)
    ASSETS = requested_output if requested_output.is_absolute() else ROOT / requested_output

    apply_style()
    make_cover()
    make_scope_flow()
    make_definition_card()
    make_transition_rates()
    make_mean_vs_net()
    make_retail_bounds()
    make_boundary_card()
    make_appendix_ratio()
    validate_assets()
    print(f"created and validated 8 PNG assets in {ASSETS}")


if __name__ == "__main__":
    main()
