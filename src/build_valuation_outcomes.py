#!/usr/bin/env python3
"""Build valuation outcome variables (sovereign spread, real and nominal yields).

Source: replication package of Carvalho Filho (2026), "Fiscal Risk, Real
Interest Rates and the Stock Market: Evidence from Brazil",
doi:10.5281/zenodo.24206681 (CC-BY-4.0), stored in
``data/raw/zenodo_24206681_fiscal_svar/``. All inputs are the package's frozen
monthly files in ``fiscal_svar/data/raw/``; they are read, never modified.

All source series are MONTHLY MEANS of daily data (not end-of-month values).

| panel variable           | package file      | origin                                                        | unit |
|--------------------------|-------------------|---------------------------------------------------------------|------|
| embi_spread_bp           | embi_spliced.csv  | EMBI+ Brazil (Ipeadata JPM366_EMBI366) to 2024-07, then EMBI  | bp   |
|                          |                   | Global Diversified Brazil + mean gap of last 12 overlap months|      |
| embi_plus_bp             | embi.csv          | EMBI+ Brazil, Ipeadata (ends 2024-07)                         | bp   |
| embi_gd_bp               | embi_gd.csv       | EMBI GD Brazil, Banco Central de la Rep. Dominicana           | bp   |
| embi_gd_rel_bp           | embi_gd_rel.csv   | EMBI GD Brazil minus EMBI GD Global composite                 | bp   |
| cds5y_bp                 | cds5y.csv         | Brazil 5y USD CDS, Investing.com (convention not stated)      | bp   |
| real_yield_5y_pct        | ry5.csv           | Tesouro Direto NTN-B/NTN-B Principal, daily linear            | % pa |
| real_yield_10y_pct       | ry10.csv          |   interpolation at 5y / 10y (constant maturity)               | % pa |
| ltn_1y_pct               | ltn12.csv         | ANBIMA 1y LTN rate, Ipeadata ANBIMA366_TJTLN12366             | % pa |
| swap_di_pre_360d_pct     | swap360.csv       | B3 DI x pre swap 360d, Ipeadata BMF12_SWAPDI36012             | % pa |

For each variable ``x`` the panel gets:

- ``x``: monthly mean in month t (OUTCOME for local projections, y_{t+h}-y_{t-1}).
- ``x_avg_lag1``: monthly mean in t-1 (PREDETERMINED; may enter X_{t-1}/Z_{t-1}).

No end-of-month (``_eom_lag1``) version is possible from these files; that would
require the daily series. No break-even is built: there is no nominal and real
yield at the same maturity in this package (ANBIMA curves still needed).

Run from the project root:  python3 src/build_valuation_outcomes.py
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd


def find_project_root() -> Path:
    candidates = [Path.cwd(), Path(__file__).resolve().parent]
    candidates.extend(Path(__file__).resolve().parents)
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    return Path(__file__).resolve().parent


PROJECT_ROOT = find_project_root()
DATA_DIR = PROJECT_ROOT / "data"
os.environ.setdefault("MPLCONFIGDIR", str(DATA_DIR / ".mplconfig"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ZENODO_DIR = DATA_DIR / "raw" / "zenodo_24206681_fiscal_svar"
ZENODO_RAW = ZENODO_DIR / "fiscal_svar" / "data" / "raw"
INTERMEDIATE_DIR = DATA_DIR / "intermediate" / "valuation"
CLEAN_DIR = DATA_DIR / "clean"
DIAGNOSTICS_DIR = DATA_DIR / "diagnostics"
FIGURES_DIR = DATA_DIR / "figures"

DOI = "https://doi.org/10.5281/zenodo.24206681"
# panel name -> (package file, origin, unit, role)
SERIES = {
    "embi_spread_bp": ("embi_spliced.csv", "EMBI+ Brazil (Ipeadata JPM366_EMBI366) to 2024-07, then EMBI GD "
                       "Brazil (BCRD) + 2.5 bp splice gap", "bp", "main"),
    "embi_plus_bp": ("embi.csv", "EMBI+ Brazil, Ipeadata JPM366_EMBI366", "bp", "robustness"),
    "embi_gd_bp": ("embi_gd.csv", "EMBI Global Diversified Brazil, Banco Central de la Republica "
                   "Dominicana", "bp", "robustness"),
    "embi_gd_rel_bp": ("embi_gd_rel.csv", "EMBI GD Brazil minus EMBI GD Global composite", "bp", "robustness"),
    "cds5y_bp": ("cds5y.csv", "Brazil 5y USD CDS close, Investing.com BRGV5YUSAC (from 2009-01)", "bp",
                 "robustness"),
    "real_yield_5y_pct": ("ry5.csv", "Tesouro Direto IPCA-linked bonds, daily linear interpolation at 5y",
                          "% p.a.", "main"),
    "real_yield_10y_pct": ("ry10.csv", "Tesouro Direto IPCA-linked bonds, daily linear interpolation at 10y",
                           "% p.a.", "main"),
    "ltn_1y_pct": ("ltn12.csv", "ANBIMA 1y LTN rate, Ipeadata ANBIMA366_TJTLN12366", "% p.a.", "main"),
    "swap_di_pre_360d_pct": ("swap360.csv", "B3 DI x pre swap 360 days, Ipeadata BMF12_SWAPDI36012",
                             "% p.a.", "robustness"),
}

PANEL_CANDIDATES = [
    CLEAN_DIR / "ftpl_monthly_panel_with_fiscal_news.csv",
    CLEAN_DIR / "ftpl_monthly_panel_with_fiscal_expectations.csv",
    CLEAN_DIR / "ftpl_monthly_panel_with_yield_curve_controls.csv",
]
OUTPUT_PANEL = CLEAN_DIR / "ftpl_monthly_panel_with_valuation_outcomes.csv"


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def find_input_panel() -> Path:
    for path in PANEL_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError("No monthly panel found among: " + ", ".join(rel(p) for p in PANEL_CANDIDATES))


def load_series(file: str) -> pd.Series:
    d = pd.read_csv(ZENODO_RAW / file)
    s = pd.to_numeric(d.iloc[:, 1], errors="coerce")
    s.index = pd.PeriodIndex(d.iloc[:, 0].astype(str), freq="M")
    if s.index.duplicated().any():
        raise ValueError(f"{file}: duplicated months")
    return s.sort_index()


def coverage_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for c in df.columns:
        s = df[c].dropna()
        span = pd.period_range(s.index.min(), s.index.max(), freq="M") if len(s) else []
        rows.append({"variable": c, "n_obs": len(s),
                     "first_month": str(s.index.min()) if len(s) else None,
                     "last_month": str(s.index.max()) if len(s) else None,
                     "internal_gaps": len(span) - len(s) if len(s) else 0,
                     "mean": s.mean(), "sd": s.std(), "min": s.min(), "max": s.max()})
    return pd.DataFrame(rows)


def plot_outputs(df: pd.DataFrame) -> None:
    d = df.loc["2000-01":]
    t = d.index.to_timestamp()
    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
    axes[0].plot(t, d["embi_spread_bp"], label="EMBI emendado", lw=1.2)
    axes[0].plot(t, d["cds5y_bp"], label="CDS 5 anos", lw=1)
    axes[0].axvline(pd.Timestamp("2024-07-01"), color="grey", ls=":", lw=0.8)
    axes[0].set_title("Spread soberano (bp, média mensal); pontilhado = emenda EMBI+ → EMBI GD")
    axes[0].legend(fontsize=8)
    axes[1].plot(t, d["real_yield_5y_pct"], label="Juro real 5a", lw=1)
    axes[1].plot(t, d["real_yield_10y_pct"], label="Juro real 10a", lw=1)
    axes[1].set_title("Juro real NTN-B, prazo constante (% a.a.)")
    axes[1].legend(fontsize=8)
    axes[2].plot(t, d["ltn_1y_pct"], label="LTN 1 ano (ANBIMA)", lw=1)
    axes[2].plot(t, d["swap_di_pre_360d_pct"], label="Swap DI×pré 360d", lw=1)
    axes[2].set_title("Juro nominal de 1 ano (% a.a.)")
    axes[2].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "valuation_outcomes.png", dpi=150)
    plt.close(fig)


def main() -> None:
    for d in (INTERMEDIATE_DIR, CLEAN_DIR, DIAGNOSTICS_DIR, FIGURES_DIR):
        d.mkdir(parents=True, exist_ok=True)

    panel_path = find_input_panel()
    panel = pd.read_csv(panel_path)
    panel["month"] = pd.to_datetime(panel["month"])
    print(f"Input panel: {rel(panel_path)} ({len(panel)} rows)")

    downloaded = (ZENODO_DIR / "DOWNLOADED_AT_UTC.txt").read_text().strip() \
        if (ZENODO_DIR / "DOWNLOADED_AT_UTC.txt").exists() else ""
    audit, levels = [], {}
    for name, (file, origin, unit, role) in SERIES.items():
        path = ZENODO_RAW / file
        levels[name] = load_series(file)
        audit.append({"variable": name, "role": role, "source_file": rel(path),
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "origin": origin, "unit": unit, "frequency": "monthly mean of daily data",
                      "package": DOI, "licence": "CC-BY-4.0", "package_downloaded_utc": downloaded})
    lv = pd.DataFrame(levels)
    lv = lv.reindex(pd.period_range(lv.index.min(), lv.index.max(), freq="M"))

    out = pd.DataFrame(index=lv.index)
    for name in SERIES:
        out[name] = lv[name]
        out[f"{name}_avg_lag1"] = lv[name].shift(1)
    out.index.name = "month"

    # validation: splice continuity and agreement between spread measures
    checks = []
    ov = lv[["embi_plus_bp", "embi_gd_bp"]].dropna()
    checks.append({"check": "corr levels EMBI+ vs EMBI GD (overlap)", "n": len(ov),
                   "value": ov.corr().iloc[0, 1]})
    checks.append({"check": "corr changes EMBI+ vs EMBI GD (overlap)", "n": len(ov) - 1,
                   "value": ov.diff().corr().iloc[0, 1]})
    sp = lv[["embi_spread_bp", "embi_plus_bp"]].dropna()
    checks.append({"check": "max |embi_spread - EMBI+| up to 2024-07 (should be 0)", "n": len(sp),
                   "value": float((sp.embi_spread_bp - sp.embi_plus_bp).abs().max())})
    after = lv.loc["2024-08":, ["embi_spread_bp", "embi_gd_bp"]].dropna()
    checks.append({"check": "mean embi_spread - EMBI GD after 2024-07 (splice gap, bp)", "n": len(after),
                   "value": float((after.embi_spread_bp - after.embi_gd_bp).mean())})
    for a, b in [("embi_spread_bp", "cds5y_bp"), ("ltn_1y_pct", "swap_di_pre_360d_pct"),
                 ("real_yield_5y_pct", "real_yield_10y_pct")]:
        j = lv[[a, b]].dropna()
        checks.append({"check": f"corr levels {a} vs {b}", "n": len(j), "value": j.corr().iloc[0, 1]})
        checks.append({"check": f"corr changes {a} vs {b}", "n": len(j) - 1,
                       "value": j.diff().corr().iloc[0, 1]})
    checks = pd.DataFrame(checks)

    out_file = out.copy()
    out_file.index = out_file.index.to_timestamp().strftime("%Y-%m-%d")
    out_file.to_csv(INTERMEDIATE_DIR / "valuation_outcomes_monthly.csv")

    out_ts = out.copy()
    out_ts.index = out_ts.index.to_timestamp()
    clash = [c for c in out_ts.columns if c in panel.columns]
    if clash:
        raise ValueError(f"Columns already in input panel: {clash}")
    merged = panel.merge(out_ts.reset_index(), on="month", how="left", validate="1:1")
    assert len(merged) == len(panel)
    lost = out_ts.dropna(how="all").index.difference(panel["month"])
    lost = lost[lost > panel["month"].max()]
    merged["month"] = merged["month"].dt.strftime("%Y-%m-%d")
    merged.to_csv(OUTPUT_PANEL, index=False)

    pd.DataFrame(audit).to_csv(DIAGNOSTICS_DIR / "valuation_outcomes_audit.csv", index=False)
    checks.to_csv(DIAGNOSTICS_DIR / "valuation_outcomes_validation.csv", index=False)
    cov = coverage_table(lv)
    cov.to_csv(DIAGNOSTICS_DIR / "valuation_outcomes_diagnostics.csv", index=False)

    main_vars = [n for n, v in SERIES.items() if v[3] == "main"]
    rob_vars = [n for n, v in SERIES.items() if v[3] == "robustness"]
    lists = {
        "outcomes_main": main_vars,
        "outcomes_robustness": rob_vars,
        "predetermined_controls_avg_lag1": [f"{n}_avg_lag1" for n in SERIES],
        "notes": [
            "All series are monthly means of daily data; no end-of-month version available.",
            "embi_spread_bp splices EMBI+ (to 2024-07) with EMBI GD (+ splice gap).",
            "cds5y_bp quote convention (mid/bid/ask) not stated by the source; robustness only.",
            "Source: Carvalho Filho (2026), doi:10.5281/zenodo.24206681, CC-BY-4.0 - cite when used.",
        ],
    }
    (DIAGNOSTICS_DIR / "valuation_outcome_lists.json").write_text(
        json.dumps(lists, indent=2, ensure_ascii=False), encoding="utf-8")

    plot_outputs(lv)

    print(f"\nWrote {rel(OUTPUT_PANEL)} ({len(merged)} rows, +{out.shape[1]} columns)")
    if len(lost):
        print(f"Note: {len(lost)} months after the panel end are only in the intermediate file "
              f"({lost.min():%Y-%m} to {lost.max():%Y-%m}).")
    print("\nCoverage:")
    print(cov[["variable", "first_month", "last_month", "n_obs", "internal_gaps"]].to_string(index=False))
    print("\nValidation:")
    print(checks.to_string(index=False))


if __name__ == "__main__":
    main()
