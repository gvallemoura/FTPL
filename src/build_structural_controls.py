#!/usr/bin/env python3
"""Build predetermined structural controls for the FTPL issuance-shock pipeline.

The script reads the latest monthly panel available in the repository, inspects the
actual column names, and creates controls that enter outside the PCA in issuance
forecasting equations. It never overwrites the source panel.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

def find_project_root() -> Path:
    """Find the repository root from the script location or current directory."""
    candidates = [Path.cwd(), Path(__file__).resolve().parent]
    candidates.extend(Path(__file__).resolve().parents)
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    return Path(__file__).resolve().parent


PROJECT_ROOT = find_project_root()
Path(PROJECT_ROOT / "data" / ".mplconfig").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(PROJECT_ROOT / "data" / ".mplconfig"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


N_LAGS_ISSUANCE = 3

EVENT_WINDOWS = {
    "dummy_global_financial_crisis": ("2008-09-01", "2009-06-01"),
    "dummy_taper_tantrum": ("2013-05-01", "2013-12-01"),
    "dummy_domestic_recession_2015_2016": ("2015-01-01", "2016-12-01"),
    "dummy_truckers_strike": ("2018-05-01", "2018-05-01"),
    "dummy_covid": ("2020-03-01", "2021-12-01"),
}

PRESIDENTIAL_ELECTION_YEARS = [2002, 2006, 2010, 2014, 2018, 2022]

PAF_TEMPLATE_COLUMNS = [
    "year",
    "publication_date",
    "valid_from",
    "valid_to",
    "paf_prefixado_min",
    "paf_prefixado_max",
    "paf_selic_min",
    "paf_selic_max",
    "paf_price_indexed_min",
    "paf_price_indexed_max",
    "paf_fx_min",
    "paf_fx_max",
    "paf_maturing_12m_min",
    "paf_maturing_12m_max",
    "paf_avg_maturity_min",
    "paf_avg_maturity_max",
    "paf_stock_min_brl",
    "paf_stock_max_brl",
    "paf_strategy_prefixado",
    "paf_strategy_selic",
    "paf_strategy_price_indexed",
    "paf_strategy_fx",
    "source_document",
    "notes",
]

LIQUIDITY_TEMPLATE_COLUMNS = [
    "month",
    "liquidity_reserve_brl",
    "liquidity_reserve_months_of_debt_service",
    "source_document",
    "notes",
]


def ensure_directories(root: Path) -> dict[str, Path]:
    """Create the derived pipeline folders and return their paths."""
    paths = {
        "data": root / "data",
        "raw": root / "data" / "raw",
        "clean": root / "data" / "clean",
        "diagnostics": root / "data" / "diagnostics",
        "figures": root / "data" / "figures",
        "mplconfig": root / "data" / ".mplconfig",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def find_latest_panel(root: Path) -> Path:
    """Find the preferred monthly panel without assuming a fixed folder layout."""
    candidates = [
        root / "data" / "clean" / "ftpl_monthly_panel_with_pib_normalization.csv",
        root / "data" / "clean" / "ftpl_monthly_panel_with_pib_normalization.csv",
        root / "data" / "clean" / "ftpl_monthly_panel.csv",
        root / "data" / "clean" / "ftpl_monthly_panel.csv",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    matches = sorted(root.glob("**/ftpl_monthly_panel*.csv"))
    if matches:
        return matches[-1]
    raise FileNotFoundError("No monthly panel file matching ftpl_monthly_panel*.csv was found.")


def print_columns(label: str, df: pd.DataFrame) -> None:
    """Print inspected column names before transformations are applied."""
    print(f"\nColumns inspected in {label} ({len(df.columns)} columns):")
    for i, col in enumerate(df.columns, 1):
        print(f"  {i:02d}. {col}")


def existing(columns: Iterable[str], df: pd.DataFrame) -> list[str]:
    """Return only columns that are available in df."""
    return [col for col in columns if col in df.columns]


def forward_window_sum(series: pd.Series, window: int) -> pd.Series:
    """Sum current and future values over a fixed window, preserving all-missing windows."""
    shifted = [series.shift(-k) for k in range(window)]
    return pd.concat(shifted, axis=1).sum(axis=1, min_count=1)


def create_template(path: Path, columns: list[str]) -> None:
    """Create an empty manual template if it does not already exist."""
    if path.exists():
        print(f"Manual template already exists: {path}")
        return
    pd.DataFrame(columns=columns).to_csv(path, index=False)
    print(f"Created manual template: {path}")


def add_lags_and_moving_averages(panel: pd.DataFrame) -> pd.DataFrame:
    """Create predetermined lags, moving averages, stock controls, and maturity windows."""
    out = panel.copy()

    issuance_cols = existing(["g_N_pib", "g_F_pib", "g_R_pib", "g_total_NFR_pib"], out)
    if not issuance_cols:
        fallback = {
            "gross_N_brl_over_pib_lag1": "g_N_pib",
            "gross_F_brl_over_pib_lag1": "g_F_pib",
            "gross_R_brl_over_pib_lag1": "g_R_pib",
            "gross_total_NFR_brl_over_pib_lag1": "g_total_NFR_pib",
        }
        for old, new in fallback.items():
            if old in out.columns and new not in out.columns:
                out[new] = out[old]
        issuance_cols = existing(["g_N_pib", "g_F_pib", "g_R_pib", "g_total_NFR_pib"], out)

    for col in issuance_cols:
        for lag in range(1, N_LAGS_ISSUANCE + 1):
            out[f"{col}_lag{lag}"] = out[col].shift(lag)

    for col in existing(["g_N_pib", "g_F_pib", "g_R_pib"], out):
        out[f"{col}_ma3_lag1"] = out[col].shift(1).rolling(3, min_periods=1).mean()

    for col in existing(["share_N", "share_F", "share_R"], out):
        out[f"{col}_lag1"] = out[col].shift(1)

    share_cols = existing(["share_N", "share_F", "share_R"], out)
    if share_cols:
        out["share_sum_structural_check"] = out[share_cols].sum(axis=1, min_count=len(share_cols))
        out["share_sum_abs_error"] = (out["share_sum_structural_check"] - 1).abs()

    for col in existing(["stock_N_brl", "stock_F_brl", "stock_R_brl"], out):
        out[f"{col}_lag1"] = out[col].shift(1)

    stock_component_cols = existing(["stock_N_brl", "stock_F_brl", "stock_R_brl"], out)
    if stock_component_cols and "stock_total_NFR_brl" not in out.columns:
        out["stock_total_NFR_brl"] = out[stock_component_cols].sum(axis=1, min_count=1)
    if "stock_total_NFR_brl" in out.columns:
        out["stock_total_NFR_brl_lag1"] = out["stock_total_NFR_brl"].shift(1)

    if "pib_12m_lag1_brl" in out.columns:
        for group in ["N", "F", "R"]:
            lag_col = f"stock_{group}_brl_lag1"
            if lag_col in out.columns:
                out[f"stock_{group}_pib_lag1"] = out[lag_col] / out["pib_12m_lag1_brl"]
        if "stock_total_NFR_brl_lag1" in out.columns:
            out["stock_total_NFR_pib_lag1"] = out["stock_total_NFR_brl_lag1"] / out["pib_12m_lag1_brl"]

    maturity_component_cols = existing(["m_N_pib", "m_F_pib", "m_R_pib"], out)
    if maturity_component_cols and "m_total_NFR_pib" not in out.columns:
        out["m_total_NFR_pib"] = out[maturity_component_cols].sum(axis=1, min_count=1)

    maturity_brl_cols = existing(
        [
            "maturity_N_t_given_tminus1_brl",
            "maturity_F_t_given_tminus1_brl",
            "maturity_R_t_given_tminus1_brl",
        ],
        out,
    )
    if maturity_brl_cols and "maturity_total_NFR_t_given_tminus1_brl" not in out.columns:
        out["maturity_total_NFR_t_given_tminus1_brl"] = out[maturity_brl_cols].sum(axis=1, min_count=1)

    if "m_total_NFR_pib" in out.columns:
        out["m_total_NFR_pib_lag0"] = out["m_total_NFR_pib"]
        out["m_total_NFR_pib_lead1"] = out["m_total_NFR_pib"].shift(-1)
        # Forward windows use observed future maturity schedule entries. They are
        # interpretable as predetermined only if that future redemption calendar was
        # known at t-1, as with contractual maturity schedules.
        for window in [3, 6, 12]:
            out[f"m_total_NFR_pib_window_{window}m"] = forward_window_sum(out["m_total_NFR_pib"], window)

    for group_col in existing(["m_N_pib", "m_F_pib", "m_R_pib"], out):
        out[f"{group_col}_window_3m"] = forward_window_sum(out[group_col], 3)

    if "maturity_total_NFR_t_given_tminus1_brl" in out.columns:
        out["maturity_total_NFR_12m_brl"] = forward_window_sum(
            out["maturity_total_NFR_t_given_tminus1_brl"], 12
        )
        out["maturity_total_NFR_12m_brl_lag1"] = out["maturity_total_NFR_12m_brl"].shift(1)

    return out


def add_calendar_and_event_dummies(panel: pd.DataFrame) -> pd.DataFrame:
    """Add calendar variables and configurable episode dummies."""
    out = panel.copy()
    out["year"] = out["month"].dt.year
    out["quarter"] = out["month"].dt.quarter
    out["calendar_month"] = out["month"].dt.month

    for name, (start, end) in EVENT_WINDOWS.items():
        start_dt = pd.Timestamp(start)
        end_dt = pd.Timestamp(end)
        out[name] = ((out["month"] >= start_dt) & (out["month"] <= end_dt)).astype(int)

    out["dummy_election_uncertainty"] = (
        out["year"].isin(PRESIDENTIAL_ELECTION_YEARS) & out["calendar_month"].isin([10, 11, 12])
    ).astype(int)
    return out


def add_extraordinary_operations(panel: pd.DataFrame, root: Path) -> pd.DataFrame:
    """Aggregate extraordinary Treasury auction operations by month and merge controls."""
    out = panel.copy()
    auction_candidates = [
        root / "data" / "clean" / "auction_operations_clean.csv",
        root / "data" / "clean" / "auction_operations_clean.csv",
    ]
    auction_path = next((p for p in auction_candidates if p.exists()), None)
    expected_cols = [
        "dummy_extra_sale",
        "dummy_extra_purchase",
        "dummy_exchange_operation",
        "dummy_buyback_operation",
        "extra_sale_value_brl",
        "extra_purchase_value_brl",
        "buyback_value_brl",
        "exchange_value_brl",
    ]

    if auction_path is None:
        print("auction_operations_clean.csv not found; extraordinary-operation controls set to NaN.")
        for col in expected_cols:
            out[col] = np.nan
            out[f"{col}_lag1"] = np.nan
        return out

    auctions = pd.read_csv(auction_path)
    print_columns(str(auction_path), auctions)
    needed = {"month", "operation", "accepted_amount_brl"}
    if not needed.issubset(auctions.columns):
        missing = sorted(needed - set(auctions.columns))
        print(f"Auction file missing {missing}; extraordinary-operation controls set to NaN.")
        for col in expected_cols:
            out[col] = np.nan
            out[f"{col}_lag1"] = np.nan
        return out

    auctions["month"] = pd.to_datetime(auctions["month"]).dt.to_period("M").dt.to_timestamp()
    auctions["operation_norm"] = auctions["operation"].fillna("").astype(str).str.upper().str.strip()
    auctions["accepted_amount_brl"] = pd.to_numeric(auctions["accepted_amount_brl"], errors="coerce")

    op_masks = {
        "extra_sale": auctions["operation_norm"].eq("EXTRA VENDA"),
        "extra_purchase": auctions["operation_norm"].eq("EXTRA COMPRA"),
        "exchange": auctions["operation_norm"].str.contains("TROCA", na=False),
        "buyback": auctions["operation_norm"].eq("COMPRA")
        | auctions["operation_norm"].str.contains("RECOMPRA|BUYBACK", regex=True, na=False),
    }

    monthly = pd.DataFrame({"month": sorted(auctions["month"].dropna().unique())})
    for key, mask in op_masks.items():
        temp = (
            auctions.loc[mask]
            .groupby("month", as_index=False)["accepted_amount_brl"]
            .sum()
            .rename(columns={"accepted_amount_brl": f"{key}_value_brl"})
        )
        monthly = monthly.merge(temp, on="month", how="left")
        value_col = f"{key}_value_brl"
        monthly[value_col] = monthly[value_col].fillna(0.0)
        dummy_name = {
            "extra_sale": "dummy_extra_sale",
            "extra_purchase": "dummy_extra_purchase",
            "exchange": "dummy_exchange_operation",
            "buyback": "dummy_buyback_operation",
        }[key]
        monthly[dummy_name] = (monthly[value_col] > 0).astype(int)

    monthly = monthly.rename(
        columns={
            "exchange_value_brl": "exchange_value_brl",
            "buyback_value_brl": "buyback_value_brl",
        }
    )
    out = out.merge(monthly, on="month", how="left")

    for col in [
        "dummy_extra_sale",
        "dummy_extra_purchase",
        "dummy_exchange_operation",
        "dummy_buyback_operation",
        "extra_sale_value_brl",
        "extra_purchase_value_brl",
        "exchange_value_brl",
        "buyback_value_brl",
    ]:
        if col in out.columns:
            out[col] = out[col].fillna(0)

    if "pib_12m_lag1_brl" in out.columns:
        for col in existing(
            ["extra_sale_value_brl", "extra_purchase_value_brl", "buyback_value_brl", "exchange_value_brl"],
            out,
        ):
            out[col.replace("_brl", "_pib")] = out[col] / out["pib_12m_lag1_brl"]

    for col in existing(
        [
            "dummy_extra_sale",
            "dummy_extra_purchase",
            "dummy_exchange_operation",
            "dummy_buyback_operation",
            "extra_sale_value_brl",
            "extra_sale_value_pib",
            "extra_purchase_value_brl",
            "extra_purchase_value_pib",
            "buyback_value_brl",
            "buyback_value_pib",
            "exchange_value_brl",
            "exchange_value_pib",
        ],
        out,
    ):
        out[f"{col}_lag1"] = out[col].shift(1)

    return out


def read_nonempty_csv(path: Path, columns: list[str]) -> pd.DataFrame:
    """Read a manual CSV template and guarantee that expected columns exist."""
    df = pd.read_csv(path)
    for col in columns:
        if col not in df.columns:
            df[col] = np.nan
    return df


def merge_paf_targets(panel: pd.DataFrame, paf_path: Path) -> pd.DataFrame:
    """Merge manual PAF targets and construct target, gap, band, and strategy variables."""
    out = panel.copy()
    paf = read_nonempty_csv(paf_path, PAF_TEMPLATE_COLUMNS)
    print_columns(str(paf_path), paf)

    paf_value_cols = [
        col
        for col in PAF_TEMPLATE_COLUMNS
        if col.startswith("paf_") and not col.startswith("paf_strategy")
    ]
    paf_strategy_cols = [
        "paf_strategy_prefixado",
        "paf_strategy_selic",
        "paf_strategy_price_indexed",
        "paf_strategy_fx",
    ]

    for col in paf_value_cols:
        paf[col] = pd.to_numeric(paf[col], errors="coerce")
    for col in ["year"]:
        paf[col] = pd.to_numeric(paf[col], errors="coerce")
    for col in ["publication_date", "valid_from", "valid_to"]:
        paf[col] = pd.to_datetime(paf[col], errors="coerce")

    if paf.dropna(how="all").empty:
        print("PAF manual template is empty; PAF controls will be NaN until it is filled.")
        for col in paf_value_cols + paf_strategy_cols:
            out[col] = np.nan
    else:
        has_valid_window = paf["valid_from"].notna().any() and paf["valid_to"].notna().any()
        if has_valid_window:
            paf_rows = paf[paf["valid_from"].notna() & paf["valid_to"].notna()].copy()
            merged_parts = []
            for _, row in paf_rows.iterrows():
                mask = (out["month"] >= row["valid_from"]) & (out["month"] <= row["valid_to"])
                part = out.loc[mask, ["month"]].copy()
                for col in paf_value_cols + paf_strategy_cols + ["source_document", "notes"]:
                    part[col] = row.get(col, np.nan)
                merged_parts.append(part)
            if merged_parts:
                paf_monthly = pd.concat(merged_parts, ignore_index=True).drop_duplicates("month", keep="last")
                out = out.merge(paf_monthly, on="month", how="left")
        elif "year" in paf.columns:
            merge_cols = ["year"] + paf_value_cols + paf_strategy_cols + ["source_document", "notes"]
            out = out.merge(paf[merge_cols].drop_duplicates("year", keep="last"), on="year", how="left")

    mapping = {
        "N": ("paf_prefixado_min", "paf_prefixado_max", "paf_strategy_prefixado", "share_N_lag1"),
        "F": ("paf_selic_min", "paf_selic_max", "paf_strategy_selic", "share_F_lag1"),
        "R": ("paf_price_indexed_min", "paf_price_indexed_max", "paf_strategy_price_indexed", "share_R_lag1"),
    }
    for group, (lower, upper, strategy_col, share_col) in mapping.items():
        for col in [lower, upper, strategy_col]:
            if col not in out.columns:
                out[col] = np.nan
        out[f"paf_{group}_target"] = (out[lower] + out[upper]) / 2
        out[f"paf_{group}_band_width"] = out[upper] - out[lower]
        if share_col in out.columns:
            out[f"paf_gap_{group}_lag1"] = out[share_col] - out[f"paf_{group}_target"]
            out[f"paf_dist_{group}_to_lower_lag1"] = out[share_col] - out[lower]
            out[f"paf_dist_{group}_to_upper_lag1"] = out[upper] - out[share_col]
            out[f"paf_{group}_below_band_lag1"] = (out[share_col] < out[lower]).where(out[lower].notna()).astype("float")
            out[f"paf_{group}_above_band_lag1"] = (out[share_col] > out[upper]).where(out[upper].notna()).astype("float")

        strategy = out[strategy_col].fillna("unclear").astype(str).str.lower().str.strip()
        strategy = strategy.where(strategy.isin(["increase", "decrease", "stable", "neutral", "unclear"]), "unclear")
        for label in ["increase", "decrease", "stable"]:
            out[f"paf_strategy_{group}_{label}"] = (strategy == label).astype(int).where(out[strategy_col].notna())

    if "paf_maturing_12m_min" in out.columns and "paf_maturing_12m_max" in out.columns:
        out["paf_maturing_12m_target"] = (out["paf_maturing_12m_min"] + out["paf_maturing_12m_max"]) / 2
        if "maturity_total_NFR_12m_brl_lag1" in out.columns and "stock_total_NFR_brl_lag1" in out.columns:
            maturing_share = out["maturity_total_NFR_12m_brl_lag1"] / out["stock_total_NFR_brl_lag1"]
            out["paf_gap_maturing_12m_lag1"] = maturing_share - out["paf_maturing_12m_target"]

    if "paf_avg_maturity_min" in out.columns and "paf_avg_maturity_max" in out.columns:
        out["paf_avg_maturity_target"] = (out["paf_avg_maturity_min"] + out["paf_avg_maturity_max"]) / 2
        # No monthly average-maturity column was found in the inspected panel, so the
        # PAF target is retained but no gap is created unless such a column is added.
        for candidate in ["avg_maturity_lag1", "avg_maturity_years_lag1"]:
            if candidate in out.columns:
                out["paf_gap_avg_maturity_lag1"] = out[candidate] - out["paf_avg_maturity_target"]
                break

    return out


def merge_liquidity_reserve(panel: pd.DataFrame, liquidity_path: Path) -> pd.DataFrame:
    """Merge manual liquidity reserve data and construct lagged normalized controls."""
    out = panel.copy()
    liquidity = read_nonempty_csv(liquidity_path, LIQUIDITY_TEMPLATE_COLUMNS)
    print_columns(str(liquidity_path), liquidity)
    liquidity["month"] = pd.to_datetime(liquidity["month"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    for col in ["liquidity_reserve_brl", "liquidity_reserve_months_of_debt_service"]:
        liquidity[col] = pd.to_numeric(liquidity[col], errors="coerce")

    if liquidity["month"].notna().any():
        out = out.merge(liquidity, on="month", how="left", suffixes=("", "_manual"))
    else:
        print("Liquidity reserve template is empty; liquidity controls will be NaN until it is filled.")
        for col in LIQUIDITY_TEMPLATE_COLUMNS:
            if col != "month":
                out[col] = np.nan

    if "liquidity_reserve_brl" not in out.columns:
        out["liquidity_reserve_brl"] = np.nan

    out["liquidity_reserve_brl_lag1"] = out["liquidity_reserve_brl"].shift(1)
    if "pib_12m_lag1_brl" in out.columns:
        out["liquidity_reserve_pib_lag1"] = out["liquidity_reserve_brl_lag1"] / out["pib_12m_lag1_brl"]
    if "stock_total_NFR_brl_lag1" in out.columns:
        out["liquidity_reserve_over_stock_lag1"] = (
            out["liquidity_reserve_brl_lag1"] / out["stock_total_NFR_brl_lag1"]
        )
    if "maturity_total_NFR_12m_brl_lag1" in out.columns:
        out["liquidity_reserve_over_maturity_12m_lag1"] = (
            out["liquidity_reserve_brl_lag1"] / out["maturity_total_NFR_12m_brl_lag1"]
        )
    elif "m_total_NFR_pib_window_12m" in out.columns and "pib_12m_lag1_brl" in out.columns:
        # Best available proxy when BRL maturity windows are absent.
        proxy_brl = out["m_total_NFR_pib_window_12m"].shift(1) * out["pib_12m_lag1_brl"]
        out["liquidity_reserve_over_maturity_12m_lag1"] = out["liquidity_reserve_brl_lag1"] / proxy_brl

    return out


def build_control_lists(panel: pd.DataFrame) -> tuple[list[str], list[str], list[str]]:
    """Create final structural-control lists and report missing candidates."""
    base_candidates = [
        "g_N_pib_lag1",
        "g_F_pib_lag1",
        "g_R_pib_lag1",
        "share_N_lag1",
        "share_F_lag1",
        "share_R_lag1",
        "paf_gap_N_lag1",
        "paf_gap_F_lag1",
        "paf_gap_R_lag1",
        "liquidity_reserve_pib_lag1",
        "m_total_NFR_pib_window_3m",
    ]

    extended_candidates = base_candidates + [
        f"g_{group}_pib_lag{lag}" for group in ["N", "F", "R"] for lag in [2, 3]
    ] + [
        "g_total_NFR_pib_lag1",
        "g_total_NFR_pib_lag2",
        "g_total_NFR_pib_lag3",
        "g_N_pib_ma3_lag1",
        "g_F_pib_ma3_lag1",
        "g_R_pib_ma3_lag1",
        "dummy_global_financial_crisis",
        "dummy_taper_tantrum",
        "dummy_domestic_recession_2015_2016",
        "dummy_truckers_strike",
        "dummy_covid",
        "dummy_election_uncertainty",
        "dummy_extra_sale_lag1",
        "dummy_extra_purchase_lag1",
        "dummy_exchange_operation_lag1",
        "dummy_buyback_operation_lag1",
        "extra_sale_value_pib_lag1",
        "extra_purchase_value_pib_lag1",
        "buyback_value_pib_lag1",
        "exchange_value_pib_lag1",
        "paf_strategy_N_increase",
        "paf_strategy_N_decrease",
        "paf_strategy_N_stable",
        "paf_strategy_F_increase",
        "paf_strategy_F_decrease",
        "paf_strategy_F_stable",
        "paf_strategy_R_increase",
        "paf_strategy_R_decrease",
        "paf_strategy_R_stable",
        "paf_dist_N_to_lower_lag1",
        "paf_dist_N_to_upper_lag1",
        "paf_dist_F_to_lower_lag1",
        "paf_dist_F_to_upper_lag1",
        "paf_dist_R_to_lower_lag1",
        "paf_dist_R_to_upper_lag1",
        "liquidity_reserve_over_stock_lag1",
        "liquidity_reserve_over_maturity_12m_lag1",
        "m_total_NFR_pib_window_6m",
        "m_total_NFR_pib_window_12m",
        "m_N_pib_window_3m",
        "m_F_pib_window_3m",
        "m_R_pib_window_3m",
    ]

    base = existing(base_candidates, panel)
    extended = existing(dict.fromkeys(extended_candidates).keys(), panel)
    missing = [col for col in dict.fromkeys(base_candidates + extended_candidates) if col not in panel.columns]
    return base, extended, missing


def write_diagnostics(
    panel: pd.DataFrame,
    controls: list[str],
    diagnostics_dir: Path,
    figures_dir: Path,
) -> None:
    """Write required diagnostics and figures for structural controls."""
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    controls = existing(controls, panel)

    if not controls:
        print("No structural controls available for diagnostics.")
        return

    missing_table = (
        panel[controls]
        .isna()
        .sum()
        .rename("n_missing")
        .to_frame()
        .assign(
            n_non_missing=lambda x: len(panel) - x["n_missing"],
            pct_missing=lambda x: x["n_missing"] / len(panel),
        )
        .sort_values(["pct_missing", "n_missing"], ascending=False)
    )
    missing_table.to_csv(diagnostics_dir / "structural_controls_missingness.csv")

    numeric_controls = [col for col in controls if pd.api.types.is_numeric_dtype(panel[col])]
    desc = panel[numeric_controls].describe().T if numeric_controls else pd.DataFrame()
    desc.to_csv(diagnostics_dir / "structural_controls_descriptive_stats.csv")

    main_corr_cols = existing(
        [
            "g_N_pib_lag1",
            "g_F_pib_lag1",
            "g_R_pib_lag1",
            "share_N_lag1",
            "share_F_lag1",
            "share_R_lag1",
            "m_total_NFR_pib_window_3m",
            "liquidity_reserve_pib_lag1",
            "paf_gap_N_lag1",
            "paf_gap_F_lag1",
            "paf_gap_R_lag1",
        ],
        panel,
    )
    if main_corr_cols:
        corr = panel[main_corr_cols].corr()
        corr.to_csv(diagnostics_dir / "structural_controls_main_correlation.csv")
        plt.figure(figsize=(10, 8))
        im = plt.imshow(corr, vmin=-1, vmax=1, cmap="coolwarm")
        plt.xticks(range(len(corr.columns)), corr.columns, rotation=45, ha="right")
        plt.yticks(range(len(corr.columns)), corr.columns)
        plt.colorbar(im, label="Correlation")
        plt.title("Structural controls: main correlation matrix")
        plt.tight_layout()
        plt.savefig(figures_dir / "structural_controls_main_correlation.png", dpi=200)
        plt.close()

    paf_plot_cols = existing(
        [
            "share_N_lag1",
            "share_F_lag1",
            "share_R_lag1",
            "paf_prefixado_min",
            "paf_prefixado_max",
            "paf_selic_min",
            "paf_selic_max",
            "paf_price_indexed_min",
            "paf_price_indexed_max",
        ],
        panel,
    )
    if len(paf_plot_cols) >= 9 and panel[["paf_prefixado_min", "paf_selic_min", "paf_price_indexed_min"]].notna().any().any():
        fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
        plot_specs = [
            ("N", "share_N_lag1", "paf_prefixado_min", "paf_prefixado_max"),
            ("F", "share_F_lag1", "paf_selic_min", "paf_selic_max"),
            ("R", "share_R_lag1", "paf_price_indexed_min", "paf_price_indexed_max"),
        ]
        for ax, (label, share, lower, upper) in zip(axes, plot_specs):
            ax.plot(panel["month"], panel[share], label=f"share {label}, lag1")
            ax.plot(panel["month"], panel[lower], linestyle="--", label="PAF lower")
            ax.plot(panel["month"], panel[upper], linestyle="--", label="PAF upper")
            ax.set_title(f"Effective share versus PAF band: {label}")
            ax.legend()
            ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(figures_dir / "paf_effective_shares_vs_bands.png", dpi=200)
        plt.close()

    if "liquidity_reserve_pib_lag1" in panel.columns and panel["liquidity_reserve_pib_lag1"].notna().any():
        plt.figure(figsize=(11, 5))
        plt.plot(panel["month"], panel["liquidity_reserve_pib_lag1"])
        plt.title("Liquidity reserve over lagged 12-month GDP")
        plt.xlabel("Month")
        plt.ylabel("Ratio")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(figures_dir / "liquidity_reserve_pib_lag1.png", dpi=200)
        plt.close()

    alerts = []
    for col in controls:
        non_missing_share = panel[col].notna().mean()
        if non_missing_share < 0.5:
            alerts.append({"variable": col, "alert": "less_than_50pct_non_missing", "value": non_missing_share})
        if pd.api.types.is_numeric_dtype(panel[col]):
            nunique = panel[col].dropna().nunique()
            if nunique <= 1:
                alerts.append({"variable": col, "alert": "constant_or_all_missing", "value": float(nunique)})
            elif nunique <= 2:
                alerts.append({"variable": col, "alert": "nearly_constant_low_unique_count", "value": float(nunique)})
    pd.DataFrame(alerts).to_csv(diagnostics_dir / "structural_controls_alerts.csv", index=False)


def save_notebook_wrapper(root: Path) -> None:
    """Create a lightweight notebook wrapper that runs the script from Colab or local."""
    notebook_path = root / "notebooks" / "build_structural_controls.ipynb"
    if notebook_path.exists():
        return
    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# Build Structural Controls\n",
                    "\n",
                    "Auxiliary wrapper for `build_structural_controls.py`.\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                    "source": ["%run ../src/build_structural_controls.py\n"],
            },
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "pygments_lexer": "ipython3"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    notebook_path.write_text(json.dumps(notebook, indent=2), encoding="utf-8")
    print(f"Created notebook wrapper: {notebook_path}")


def main() -> None:
    """Run the Etapa A structural-control pipeline."""
    root = PROJECT_ROOT
    paths = ensure_directories(root)

    panel_path = find_latest_panel(root)
    panel = pd.read_csv(panel_path)
    print(f"Using monthly panel: {panel_path}")
    print_columns(str(panel_path), panel)

    if "month" not in panel.columns:
        raise KeyError("The monthly panel must contain a 'month' column.")
    panel["month"] = pd.to_datetime(panel["month"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    panel = panel.sort_values("month").reset_index(drop=True)

    panel_structural = panel.copy()
    panel_structural = add_lags_and_moving_averages(panel_structural)
    panel_structural = add_calendar_and_event_dummies(panel_structural)
    panel_structural = add_extraordinary_operations(panel_structural, root)

    paf_path = paths["raw"] / "paf_manual_targets.csv"
    liquidity_path = paths["raw"] / "treasury_liquidity_reserve_manual.csv"
    create_template(paf_path, PAF_TEMPLATE_COLUMNS)
    create_template(liquidity_path, LIQUIDITY_TEMPLATE_COLUMNS)

    panel_structural = merge_paf_targets(panel_structural, paf_path)
    panel_structural = merge_liquidity_reserve(panel_structural, liquidity_path)

    structural_controls_base, structural_controls_extended, missing_candidates = build_control_lists(panel_structural)
    all_controls = list(dict.fromkeys(structural_controls_base + structural_controls_extended))

    output_path = paths["clean"] / "ftpl_monthly_panel_structural_controls.csv"
    panel_structural.to_csv(output_path, index=False)

    control_lists_path = paths["diagnostics"] / "structural_control_lists.json"
    control_lists_path.write_text(
        json.dumps(
            {
                "structural_controls_base": structural_controls_base,
                "structural_controls_extended": structural_controls_extended,
                "missing_candidates": missing_candidates,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    write_diagnostics(panel_structural, all_controls, paths["diagnostics"], paths["figures"])
    save_notebook_wrapper(root)

    obs_counts = panel_structural[all_controls].notna().sum().sort_values(ascending=False) if all_controls else pd.Series(dtype=int)
    print("\nFinal panel saved:")
    print(f"  {output_path}")
    print(f"Dimensions: {panel_structural.shape[0]} rows x {panel_structural.shape[1]} columns")
    print(f"Sample period: {panel_structural['month'].min().date()} to {panel_structural['month'].max().date()}")

    print("\nstructural_controls_base:")
    print(structural_controls_base)
    print("\nstructural_controls_extended:")
    print(structural_controls_extended)
    print("\nMissing candidate controls:")
    print(missing_candidates)
    print("\nNon-missing observations by included control:")
    print(obs_counts.to_string())

    if "share_sum_abs_error" in panel_structural.columns:
        max_error = panel_structural["share_sum_abs_error"].max(skipna=True)
        print(f"\nShare-sum diagnostic max absolute error: {max_error}")

    print("\nCreated/updated files:")
    for path in [
        output_path,
        paf_path,
        liquidity_path,
        paths["diagnostics"] / "structural_controls_missingness.csv",
        paths["diagnostics"] / "structural_controls_descriptive_stats.csv",
        paths["diagnostics"] / "structural_controls_main_correlation.csv",
        paths["diagnostics"] / "structural_controls_alerts.csv",
        control_lists_path,
    ]:
        print(f"  - {path}")


if __name__ == "__main__":
    main()
