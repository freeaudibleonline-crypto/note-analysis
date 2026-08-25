from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_rate(events: pd.Series, denominator: pd.Series, rate: pd.Series, label: str) -> None:
    expected = 100 * events / denominator
    require(np.allclose(expected, rate, atol=0.011, rtol=0), f"rate mismatch: {label}")


def assert_nonnegative_integers(df: pd.DataFrame, columns: list[str], label: str) -> None:
    for column in columns:
        require(pd.api.types.is_integer_dtype(df[column]), f"non-integer count column: {label}.{column}")
        require((df[column] >= 0).all(), f"negative count: {label}.{column}")


def assert_percentages(df: pd.DataFrame, columns: list[str], label: str) -> None:
    for column in columns:
        require(df[column].between(0, 100).all(), f"percentage outside 0-100: {label}.{column}")


def verify_exact_industries() -> None:
    df = pd.read_csv(DATA / "a3" / "exact_industries.csv", dtype={"industry_code": str})
    require(len(df) == 9, "exact_industries.csv must contain 9 industries")
    require(df["industry_code"].is_unique, "industry codes must be unique in exact_industries.csv")
    require(set(df["publication_role"].value_counts().to_dict().items()) == {
        ("main", 2), ("secondary", 2), ("corporate_segment_appendix", 5)
    }, "unexpected publication-role counts")
    require(set(df["transition_analysis_units"]) == {1706}, "transition analysis must use 1,706 units")
    count_columns = [
        "n_units_2021_eq0", "n_units_2021_eq2", "n_down_2_to_le1", "n_units_2021_eq1",
        "n_up_1_to_ge2", "n_units_ge2_2021", "n_units_ge2_2024", "n_down_ge2_to_le1",
        "n_up_le1_to_ge2", "n_units_delta_lt0", "n_units_delta_eq0", "n_units_delta_gt0",
        "transition_analysis_units",
    ]
    assert_nonnegative_integers(df, count_columns, "exact_industries")
    assert_percentages(
        df,
        ["corporate_coverage_pct_2021_all1741", "n_ge2_flip_pct_2021_all1741",
         "down_2_to_le1_pct", "up_1_to_ge2_pct"],
        "exact_industries",
    )
    require(((df["n_units_2021_eq0"] + df["n_units_2021_eq1"] + df["n_units_ge2_2021"])
             == df["transition_analysis_units"]).all(), "2021 state counts must sum to 1,706")
    require((df["n_units_2021_eq2"] <= df["n_units_ge2_2021"]).all(),
            "exact-N=2 count cannot exceed N>=2 count")
    expected_tier = np.where(
        df["corporate_coverage_pct_2021_all1741"] >= 80,
        1,
        np.where(df["corporate_coverage_pct_2021_all1741"] >= 50, 2, 3),
    )
    require(np.array_equal(df["tier"].to_numpy(), expected_tier), "tier/coverage mismatch")
    expected_role = df["tier"].map({1: "main", 2: "secondary", 3: "corporate_segment_appendix"})
    require((df["publication_role"] == expected_role).all(), "tier/publication-role mismatch")

    assert_rate(df["n_down_2_to_le1"], df["n_units_2021_eq2"], df["down_2_to_le1_pct"], "exact down")
    assert_rate(df["n_up_1_to_ge2"], df["n_units_2021_eq1"], df["up_1_to_ge2_pct"], "exact up")

    require((df["net_change_units_ge2"] == df["n_units_ge2_2024"] - df["n_units_ge2_2021"]).all(),
            "net count must equal 2024 minus 2021")
    require((df["net_change_units_ge2"] == df["n_up_le1_to_ge2"] - df["n_down_ge2_to_le1"]).all(),
            "net count must equal upward minus downward crossings")
    require(((df["n_units_delta_lt0"] + df["n_units_delta_eq0"] + df["n_units_delta_gt0"])
             == df["transition_analysis_units"]).all(), "delta-state counts must sum to 1,706")

    funeral = df.loc[df["industry_code"].eq("79A")].iloc[0]
    hospital = df.loc[df["industry_code"].eq("831")].iloc[0]
    require((funeral["n_down_2_to_le1"], funeral["n_units_2021_eq2"]) == (48, 234),
            "funeral example changed")
    require((hospital["n_down_2_to_le1"], hospital["n_units_2021_eq2"]) == (21, 201),
            "hospital example changed")


def verify_retail_scenarios() -> None:
    df = pd.read_csv(DATA / "a3" / "retail_endpoint_scenarios.csv", dtype={"industry_code": str})
    require(len(df) == 4, "retail_endpoint_scenarios.csv must contain 4 industries")
    require(df["industry_code"].is_unique, "retail industry codes must be unique")
    require((df["interval_type"] == "per_industry_marginal_worst_case").all(),
            "unexpected retail interval type")
    require((~df["jointly_satisfiable_across_industries"]).all(),
            "retail endpoint scenarios must not be marked jointly satisfiable")
    assert_nonnegative_integers(
        df,
        [column for column in df.columns if column.startswith("n_")] + ["uncertain_analysis_units"],
        "retail_endpoint_scenarios",
    )
    assert_percentages(
        df,
        [column for column in df.columns if column.endswith("_pct") or column == "uncertain_pct_of_1706"],
        "retail_endpoint_scenarios",
    )
    require(np.allclose(
        df["uncertain_pct_of_1706"],
        100 * df["uncertain_analysis_units"] / 1706,
        atol=0.011,
        rtol=0,
    ), "retail uncertain-unit percentage mismatch")

    for suffix in ("exclude_566", "include_all_566"):
        assert_rate(
            df[f"n_down_2_to_le1_{suffix}"],
            df["n_units_2021_eq2"],
            df[f"down_2_to_le1_{suffix}_pct"],
            f"retail down {suffix}",
        )
        assert_rate(
            df[f"n_up_1_to_ge2_{suffix}"],
            df["n_units_2021_eq1"],
            df[f"up_1_to_ge2_{suffix}_pct"],
            f"retail up {suffix}",
        )
        require(
            (df[f"net_change_units_ge2_{suffix}"]
             == df[f"n_up_le1_to_ge2_{suffix}"] - df[f"n_down_ge2_to_le1_{suffix}"]).all(),
            f"retail net crossing mismatch: {suffix}",
        )
    require((df["n_down_2_to_le1_include_all_566"] <= df["n_down_2_to_le1_exclude_566"]).all(),
            "adding 566 cannot increase exact-N=2 downward events")
    require((df["n_up_1_to_ge2_include_all_566"] >= df["n_up_1_to_ge2_exclude_566"]).all(),
            "adding 566 cannot decrease exact-N=1 upward events")
    require((df["n_down_ge2_to_le1_include_all_566"] <= df["n_down_ge2_to_le1_exclude_566"]).all(),
            "adding 566 cannot increase all-state downward crossings")
    require((df["n_up_le1_to_ge2_include_all_566"] >= df["n_up_le1_to_ge2_exclude_566"]).all(),
            "adding 566 cannot decrease all-state upward crossings")


def verify_scope() -> None:
    scope = pd.read_csv(DATA / "a3" / "analysis_scope.csv", dtype={"industry_code": str})
    exact = pd.read_csv(DATA / "a3" / "exact_industries.csv", dtype={"industry_code": str})
    retail = pd.read_csv(DATA / "a3" / "retail_endpoint_scenarios.csv", dtype={"industry_code": str})
    phase1 = pd.read_csv(DATA / "phase1" / "model_sensitivity.csv", dtype={"industry_code": str})

    require(len(scope) == 15, "analysis_scope.csv must contain 15 industries")
    require(scope["industry_code"].is_unique, "scope industry codes must be unique")
    require(scope["comparison_group"].value_counts().to_dict() == {
        "exact_comparison": 9,
        "retail_endpoint_scenarios": 4,
        "retail_reference": 1,
        "excluded": 1,
    }, "unexpected scope-group counts")
    require(set(scope.loc[scope["comparison_group"].eq("exact_comparison"), "industry_code"])
            == set(exact["industry_code"]), "scope/exact industry-code mismatch")
    require(set(scope.loc[scope["comparison_group"].eq("retail_endpoint_scenarios"), "industry_code"])
            == set(retail["industry_code"]), "scope/retail industry-code mismatch")
    scope_names = dict(zip(scope["industry_code"], scope["industry_name"]))
    phase1_names = dict(zip(phase1["industry_code"], phase1["industry_name"]))
    require(scope_names == phase1_names, "scope/phase-1 industry-name mismatch")


def verify_boundary() -> None:
    df = pd.read_csv(DATA / "a3" / "boundary_sensitivity.csv")
    require(df["metric"].is_unique, "boundary metrics must be unique")
    values = dict(zip(df["metric"], df["value"]))
    expected = {
        "boundary_change_events": 20,
        "unique_pairs": 18,
        "connected_components": 17,
        "affected_analysis_units": 35,
        "component_industry_combinations": 153,
        "mixed_sign_combinations": 23,
        "zero_sum_combinations": 46,
        "mixed_sign_and_zero_sum": 6,
        "max_abs_down_2_to_le1_difference_pt": 0.74,
        "max_abs_up_1_to_ge2_difference_pt": 0.66,
    }
    require(set(values) == set(expected), "unexpected boundary metrics")
    for key, value in expected.items():
        require(np.isclose(values[key], value), f"boundary metric mismatch: {key}")
    expected_units = {
        "boundary_change_events": "events",
        "unique_pairs": "pairs",
        "connected_components": "components",
        "affected_analysis_units": "analysis_units",
        "component_industry_combinations": "combinations",
        "mixed_sign_combinations": "combinations",
        "zero_sum_combinations": "combinations",
        "mixed_sign_and_zero_sum": "combinations",
        "max_abs_down_2_to_le1_difference_pt": "percentage_points",
        "max_abs_up_1_to_ge2_difference_pt": "percentage_points",
    }
    require(dict(zip(df["metric"], df["unit"])) == expected_units, "unexpected boundary units")


def verify_phase1_sensitivity() -> None:
    df = pd.read_csv(DATA / "phase1" / "model_sensitivity.csv", dtype={"industry_code": str})
    diag = pd.read_csv(
        DATA / "phase1" / "binary_logit_monotonicity_diagnostics.csv",
        dtype={"industry_code": str},
    )
    models = {"binary_logit", "ordered_logit", "poisson", "negbin"}

    require(len(df) == 60, "model_sensitivity.csv must contain 60 rows")
    require(df["industry_code"].nunique() == 15, "model sensitivity must contain 15 industries")
    require(set(df["model"]) == models, "unexpected model names")
    require((df.groupby("industry_code")["model"].nunique() == 4).all(),
            "each industry must contain all four models")
    require(set(df["n_obs"]) == {1740}, "phase-1 sensitivity must use 1,740 municipalities")
    require(df["converged"].all(), "all stored model fits must be converged")
    require((df["boot_B"] == df["boot_valid"]).all(), "bootstrap valid count mismatch")
    require((df.loc[df["model"].eq("binary_logit"), "boot_B"] == 500).all(),
            "binary-logit bootstrap count must be 500")
    require((df.loc[~df["model"].eq("binary_logit"), "boot_B"] == 200).all(),
            "non-binary bootstrap count must be 200")
    require(((df["S2"] < df["S3"]) & (df["S3"] < df["S4"]) & (df["S4"] < df["S5"])).all(),
            "S2-S5 thresholds must be strictly increasing")
    require((df["s5_s2_ci_lo"] <= df["s5_s2"]).all()
            and (df["s5_s2"] <= df["s5_s2_ci_hi"]).all(), "point estimate must lie inside interval")
    expected_ratio = (df["S5"] / 5) / (df["S2"] / 2)
    require(np.allclose(df["s5_s2"], expected_ratio, atol=1e-10, rtol=1e-10),
            "normalized S5/S2 ratio mismatch")
    require(df.loc[df["model"].eq("poisson"), "poisson_pearson_chi2_df"].notna().all(),
            "Poisson dispersion diagnostic missing")
    require(df.loc[~df["model"].eq("poisson"), "poisson_pearson_chi2_df"].isna().all(),
            "Poisson dispersion diagnostic appears on another model")
    require(df.loc[df["model"].eq("negbin"), "negbin_alpha_mom"].notna().all(),
            "negative-binomial alpha missing")
    require(df.loc[~df["model"].eq("negbin"), "negbin_alpha_mom"].isna().all(),
            "negative-binomial alpha appears on another model")
    require((df.loc[df["model"].eq("ordered_logit"), "topcode"] == 5).all(),
            "ordered-logit topcode must be 5")
    require(df.loc[~df["model"].eq("ordered_logit"), "topcode"].isna().all(),
            "topcode appears on a model other than ordered logit")

    require(len(diag) == 15 and diag["industry_code"].is_unique,
            "monotonicity diagnostics must contain one row per industry")
    require(set(diag["industry_code"]) == set(df["industry_code"]),
            "sensitivity/diagnostic industry-code mismatch")
    require(set(map(tuple, diag[["industry_code", "industry_name"]].to_numpy()))
            == set(map(tuple, df[["industry_code", "industry_name"]].drop_duplicates().to_numpy())),
            "sensitivity/diagnostic industry-name mismatch")
    require((diag["cross_max_gap"] >= 0).all() and (diag["cross_max_gap"] <= 0.0026).all(),
            "unexpected monotonicity-crossing gap")
    no_cross = diag["cross_municipalities"].eq(0)
    require(diag.loc[no_cross, ["cross_pop_min", "cross_pop_max"]].isna().all().all(),
            "population bounds must be missing when there is no crossing")
    require((diag.loc[no_cross, "cross_max_gap"] == 0).all(),
            "crossing gap must be zero when there is no crossing")
    require(diag.loc[~no_cross, ["cross_pop_min", "cross_pop_max"]].notna().all().all(),
            "population bounds missing for a crossing industry")


def verify_public_schema() -> None:
    forbidden = {"run_id", "crosswalk_version"}
    expected_columns = {
        "a3/exact_industries.csv": [
            "industry_code", "industry_name", "tier", "publication_role",
            "corporate_coverage_pct_2021_all1741", "n_ge2_flip_pct_2021_all1741",
            "n_units_2021_eq0", "n_units_2021_eq2", "n_down_2_to_le1", "down_2_to_le1_pct",
            "n_units_2021_eq1", "n_up_1_to_ge2", "up_1_to_ge2_pct", "n_units_ge2_2021",
            "n_units_ge2_2024", "n_down_ge2_to_le1", "n_up_le1_to_ge2", "net_change_units_ge2",
            "mean_establishment_count_change", "n_units_delta_lt0", "n_units_delta_eq0",
            "n_units_delta_gt0", "transition_analysis_units",
        ],
        "a3/retail_endpoint_scenarios.csv": [
            "industry_code", "industry_name", "scenario_2024_exclude_566",
            "scenario_2024_include_all_566", "uncertain_analysis_units", "uncertain_pct_of_1706",
            "n_units_2021_eq2", "n_down_2_to_le1_exclude_566", "down_2_to_le1_exclude_566_pct",
            "n_down_2_to_le1_include_all_566", "down_2_to_le1_include_all_566_pct",
            "n_units_2021_eq1", "n_up_1_to_ge2_exclude_566", "up_1_to_ge2_exclude_566_pct",
            "n_up_1_to_ge2_include_all_566", "up_1_to_ge2_include_all_566_pct",
            "n_down_ge2_to_le1_exclude_566", "n_up_le1_to_ge2_exclude_566",
            "net_change_units_ge2_exclude_566", "n_down_ge2_to_le1_include_all_566",
            "n_up_le1_to_ge2_include_all_566", "net_change_units_ge2_include_all_566",
            "interval_type", "jointly_satisfiable_across_industries",
        ],
        "a3/analysis_scope.csv": [
            "industry_code", "industry_name", "comparison_group", "comparison_method",
            "publication_role", "reason",
        ],
        "a3/boundary_sensitivity.csv": ["metric", "value", "unit"],
        "phase1/model_sensitivity.csv": [
            "industry_code", "industry_name", "model", "n_obs", "topcode", "converged",
            "S2", "S3", "S4", "S5", "s5_s2", "s5_s2_ci_lo", "s5_s2_ci_hi",
            "boot_B", "boot_valid", "boot_seed", "poisson_pearson_chi2_df", "negbin_alpha_mom",
        ],
        "phase1/binary_logit_monotonicity_diagnostics.csv": [
            "industry_code", "industry_name", "cross_municipalities", "cross_pop_min",
            "cross_pop_max", "cross_max_gap",
        ],
    }
    actual_paths = {path.relative_to(DATA).as_posix() for path in DATA.rglob("*.csv")}
    require(actual_paths == set(expected_columns), "unexpected public CSV file set")
    for relative_path, expected in expected_columns.items():
        columns = list(pd.read_csv(DATA / relative_path, nrows=0).columns)
        require(columns == expected, f"unexpected columns or order: {relative_path}")
        require(not set(columns).intersection(forbidden), f"internal provenance column found: {relative_path}")


def verify_figures(output_dir: Path) -> None:
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
        path = output_dir / name
        require(path.exists(), f"missing figure: {path}")
        with Image.open(path) as image:
            image.load()
            require(image.size == size and image.getbbox() is not None, f"invalid figure: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="公開CSVと、任意で生成済みPNGを検証します。")
    parser.add_argument(
        "--check-figures",
        action="store_true",
        help="output/にあるPNG 8枚の存在・寸法・非空を追加検証します。",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="PNG検証先。相対パスはリポジトリ直下を基準にします。",
    )
    args = parser.parse_args()

    verify_public_schema()
    verify_exact_industries()
    verify_retail_scenarios()
    verify_scope()
    verify_boundary()
    verify_phase1_sensitivity()
    if args.check_figures:
        requested = Path(args.output_dir)
        output_dir = requested if requested.is_absolute() else ROOT / requested
        verify_figures(output_dir)
    print("PASS: public CSV consistency checks completed")


if __name__ == "__main__":
    main()
