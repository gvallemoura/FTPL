#!/usr/bin/env python3
"""Monthly break-even inflation outcomes from the ANBIMA ETTJ daily curves.

Input: ``data/intermediate/anbima/anbima_yield_curve_features_daily.csv``
(written by Etapa B from the ANBIMA ETTJ; % p.a., business days). Break-even
inflation is the simple difference PRE - IPCA at the same vertex (project
convention, as in Etapa B and the ETTJ file); a Fisher version
((1+PRE)/(1+IPCA) - 1) is added for robustness.

Horizons: 1, 2, 3, 5, 7 and 10 years. The 3m and 6m vertices are NOT built:
the real curve is extrapolated there when no short NTN-B exists (2013-2021).

For each horizon h the panel gets OUTCOMES for month t (left-hand side of the
local projections, y_{t+h} - y_{t-1}):

- ``bei_{h}_pct``: mean of daily values in month t (comparable with the other
  valuation outcomes, which are monthly means);
- ``bei_{h}_eom_pct``: last business day of month t;
- ``bei_{h}_fisher_pct``: Fisher version, monthly mean (robustness).

The predetermined controls (``bei_{h}_avg_lag1``, ``bei_{h}_eom_lag1``) already
exist from Etapa B; the script checks that ``bei_{h}_pct`` in t equals
``bei_{h}_avg_lag1`` in t+1 and ``bei_{h}_eom_pct`` in t equals
``bei_{h}_eom_lag1`` in t+1.

Run from the project root:  python3 src/build_breakeven_outcomes.py
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

DAILY_FILE = DATA_DIR / "intermediate" / "anbima" / "anbima_yield_curve_features_daily.csv"
INTERMEDIATE_DIR = DATA_DIR / "intermediate" / "breakeven"
CLEAN_DIR = DATA_DIR / "clean"
DIAGNOSTICS_DIR = DATA_DIR / "diagnostics"
FIGURES_DIR = DATA_DIR / "figures"
INPUT_PANEL = CLEAN_DIR / "ftpl_monthly_panel_with_maturity_paf_hist.csv"
OUTPUT_PANEL = CLEAN_DIR / "ftpl_monthly_panel_with_breakeven_outcomes.csv"
HORIZONS = ["1y", "2y", "3y", "5y", "7y", "10y"]
TOL = 1e-9


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def main() -> None:
    for d in (INTERMEDIATE_DIR, CLEAN_DIR, DIAGNOSTICS_DIR, FIGURES_DIR):
        d.mkdir(parents=True, exist_ok=True)
    panel = pd.read_csv(INPUT_PANEL)
    panel["month"] = pd.to_datetime(panel["month"])
    print(f"Input panel: {rel(INPUT_PANEL)} {panel.shape}")

    daily = pd.read_csv(DAILY_FILE, parse_dates=["date"]).set_index("date").sort_index()
    if daily.index.duplicated().any():
        raise ValueError("duplicated dates in the daily curve file")
    daily = daily[[f"{c}_{h}" for c in ("pre", "ipca", "bei") for h in HORIZONS]].dropna(how="all")

    checks = []
    for h in HORIZONS:
        diff = (daily[f"bei_{h}"] - (daily[f"pre_{h}"] - daily[f"ipca_{h}"])).abs().max()
        checks.append({"check": f"daily bei_{h} = pre_{h} - ipca_{h} (max abs diff)", "value": float(diff),
                       "status": "PASS" if diff < TOL else "FAIL"})
        daily[f"bei_{h}_fisher"] = ((1 + daily[f"pre_{h}"] / 100) / (1 + daily[f"ipca_{h}"] / 100) - 1) * 100

    month = daily.index.to_period("M").to_timestamp()
    g = daily.groupby(month)
    out = pd.DataFrame(index=pd.DatetimeIndex(sorted(month.unique()), name="month"))
    for h in HORIZONS:
        out[f"bei_{h}_pct"] = g[f"bei_{h}"].mean()
        out[f"bei_{h}_eom_pct"] = g[f"bei_{h}"].last()
        out[f"bei_{h}_fisher_pct"] = g[f"bei_{h}_fisher"].mean()
    out["bei_n_days"] = g.size()

    p = panel.set_index("month")
    for h in HORIZONS:
        for new, old in [(f"bei_{h}_pct", f"bei_{h}_avg_lag1"), (f"bei_{h}_eom_pct", f"bei_{h}_eom_lag1")]:
            nxt = p[old].copy()
            nxt.index = nxt.index - pd.offsets.MonthBegin(1)
            j = pd.concat([out[new], nxt], axis=1, join="inner").dropna()
            diff = float((j.iloc[:, 0] - j.iloc[:, 1]).abs().max()) if len(j) else np.nan
            checks.append({"check": f"{new}(t) = {old}(t+1) (max abs diff)", "value": diff,
                           "status": "PASS" if len(j) and diff < TOL else "FAIL", "n": len(j)})
    checks = pd.DataFrame(checks)
    checks.to_csv(DIAGNOSTICS_DIR / "breakeven_outcomes_validation.csv", index=False)
    if (checks.status == "FAIL").any():
        print(checks.to_string(index=False))
        raise SystemExit("Validation failed; nothing written to the panel.")

    clash = [c for c in out.columns if c in panel.columns]
    if clash:
        raise ValueError(f"Columns already in input panel: {clash}")
    merged = panel.merge(out.reset_index(), on="month", how="left", validate="1:1")
    assert len(merged) == len(panel)
    merged["month"] = merged["month"].dt.strftime("%Y-%m-%d")
    merged.to_csv(OUTPUT_PANEL, index=False)

    o = out.copy()
    o.index = o.index.strftime("%Y-%m-%d")
    o.to_csv(INTERMEDIATE_DIR / "breakeven_outcomes_monthly.csv")
    cov = pd.DataFrame([{"variable": c, "n_obs": int(out[c].notna().sum()),
                         "first_month": out[c].first_valid_index().strftime("%Y-%m"),
                         "last_month": out[c].last_valid_index().strftime("%Y-%m"),
                         "mean": out[c].mean(), "sd": out[c].std(), "min": out[c].min(), "max": out[c].max()}
                        for c in out.columns])
    cov.to_csv(DIAGNOSTICS_DIR / "breakeven_outcomes_diagnostics.csv", index=False)
    pd.DataFrame([{"item": "ANBIMA ETTJ daily curves (Etapa B output)", "file": rel(DAILY_FILE),
                   "sha256": hashlib.sha256(DAILY_FILE.read_bytes()).hexdigest(),
                   "first": str(daily.index.min().date()), "last": str(daily.index.max().date())}]
                 ).to_csv(DIAGNOSTICS_DIR / "breakeven_outcomes_audit.csv", index=False)
    lists = {
        "outcomes_main": ["bei_1y_pct", "bei_5y_pct", "bei_10y_pct"],
        "outcomes_eom": [f"bei_{h}_eom_pct" for h in HORIZONS],
        "outcomes_robustness": [f"bei_{h}_fisher_pct" for h in HORIZONS]
                               + [f"bei_{h}_pct" for h in ("2y", "3y", "7y")],
        "predetermined_controls_existing": [f"bei_{h}_avg_lag1" for h in HORIZONS]
                                           + [f"bei_{h}_eom_lag1" for h in HORIZONS],
        "notes": [
            "Break-even = PRE - IPCA (simple difference), ANBIMA ETTJ; Fisher version for robustness.",
            "3m and 6m vertices excluded (extrapolated real curve 2013-2021).",
            "Coverage follows the ETTJ received (2006-01..2025-01) until the extension arrives.",
        ],
    }
    (DIAGNOSTICS_DIR / "breakeven_outcome_lists.json").write_text(
        json.dumps(lists, indent=2, ensure_ascii=False), encoding="utf-8")

    fig, ax = plt.subplots(figsize=(10, 4.5))
    for h in ("1y", "5y", "10y"):
        ax.plot(out.index, out[f"bei_{h}_pct"], lw=1, label=f"{h}")
    ax.set_title("Inflação implícita ANBIMA (PRE - IPCA, média mensal, % a.a.)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "breakeven_outcomes.png", dpi=150)
    plt.close(fig)

    print(f"Wrote {rel(OUTPUT_PANEL)} {merged.shape} (+{out.shape[1]} columns)")
    print(checks.to_string(index=False))
    print(cov[["variable", "first_month", "last_month", "n_obs", "mean"]].to_string(index=False))


if __name__ == "__main__":
    main()
