#!/usr/bin/env python3
"""Integrate the Prisma Fiscal / Focus fiscal-news dataset into the FTPL panel.

Source: dataset built by coauthor João (Nov 2026), delivered in
``DadosJoao/Choques_fiscais_Prisma_Focus/`` with the report
``DadosJoao/Relatorio_Series_Fiscais_v1.pdf``. The delivery is copied once,
unchanged, to ``data/raw/prisma_fiscal_news_joao/`` (never overwritten; a
SHA-256 mismatch with an existing copy stops the script). Only the copy is read.

The original Prisma spreadsheets and Focus API pulls used by João's scripts
(``prisma/*.xlsx``, ``focus/*.csv``) were NOT part of the delivery. Those raw
files should be requested and stored under ``data/raw/prisma_fiscal_news_joao/``
to make the extraction reproducible.

Variables added (``month`` = YYYY-MM-01; sign: positive primary = surplus, so a
positive primary revision is GOOD fiscal news):

- ``prisma_primary_{12m,36m}_rev_curr_pib``: Prisma median revision of the
  Central Government primary balance during month t, fixed-event per target
  year, combined with the same horizon weights as the Focus script
  (``x^{12m} = (12-m)/12 E[Y] + m/12 E[Y+1]``; 36m uses Y+2, Y+3), in R$ mi
  divided by ``pib_12m_lag1_brl`` -> percentage points of GDP.
  CONTEMPORANEOUS -> survey purge only, never a forecasting control.
- ``prisma_primary_{12m,36m}_rev_lag1_pib``: same, during t-1. PREDETERMINED.
- ``prisma_primary_surp_pib``: realized minus Prisma median for month t
  (forecast sent in t), % of GDP, dated at the reference month t.
- ``prisma_primary_surp_pib_release``: the same surprise dated at t+1, the
  approximate release month of the realized figure (Tesouro RTN, ~end of t+1).
  Use this one as news; the exact release date still has to be checked.
  The surprise is recomputed from the long files (João's merge lost 2020-07 to
  2021-12 because those realized months are not dated on day 1).
- GDP for normalization: rolling 12m sum of SGS 4380, lagged one month, built
  here (see ``load_pib_12m_lag1``); the panel's ``pib_12m_lag1_brl`` is 10x too
  large because of a decimal-parsing bug in the original data notebook.
- João's original columns (R$ mi or p.p., fixed-event horizons h0..h3) are kept
  under their original names for traceability.

Prisma gross debt revisions are kept separate: General Government (2015-2020)
and Central Government (2021-2026) are different concepts and are NOT spliced.

Run from the project root:  python3 src/build_prisma_fiscal_news.py [--offline]
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
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

DELIVERY_DIR = PROJECT_ROOT / "DadosJoao"
DELIVERY_FILES = [
    *sorted((DELIVERY_DIR / "Choques_fiscais_Prisma_Focus").glob("*")),
    DELIVERY_DIR / "Relatorio_Series_Fiscais_v1.pdf",
]
RAW_DIR = DATA_DIR / "raw" / "prisma_fiscal_news_joao"
INTERMEDIATE_DIR = DATA_DIR / "intermediate" / "prisma"
CLEAN_DIR = DATA_DIR / "clean"
DIAGNOSTICS_DIR = DATA_DIR / "diagnostics"
FIGURES_DIR = DATA_DIR / "figures"

BCB_RAW_DIR = DATA_DIR / "raw" / "bcb"
SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
PIB_SGS_CODE = 4380   # PIB mensal, valores correntes, R$ milhões

PRIMARY_VAR = "Resultado Primário do Governo Central"
HORIZONS = {"12m": 0, "36m": 2}   # same convention as build_fiscal_expectations_controls.py

PANEL_CANDIDATES = [
    CLEAN_DIR / "ftpl_monthly_panel_with_fiscal_expectations.csv",
    CLEAN_DIR / "ftpl_monthly_panel_with_yield_curve_controls.csv",
    CLEAN_DIR / "ftpl_monthly_panel_structural_controls.csv",
]
OUTPUT_PANEL = CLEAN_DIR / "ftpl_monthly_panel_with_fiscal_news.csv"


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_input_panel() -> Path:
    for path in PANEL_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError("No monthly panel found among: " + ", ".join(rel(p) for p in PANEL_CANDIDATES))


def preserve_delivery() -> list[dict]:
    """Copy João's delivery to data/raw once; never overwrite a different file."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    audit = []
    sources = [p for p in DELIVERY_FILES if p.is_file() and p.name != ".DS_Store"]
    if not sources and not any(RAW_DIR.iterdir()):
        raise FileNotFoundError(f"Delivery not found in {rel(DELIVERY_DIR)} and no preserved copy in {rel(RAW_DIR)}")
    for src in sources:
        dst = RAW_DIR / src.name
        if dst.exists():
            if sha256(dst) != sha256(src):
                raise RuntimeError(f"{rel(dst)} exists and differs from {rel(src)}; "
                                   "store the new delivery under a new name/version instead.")
            action = "already_preserved_identical"
        else:
            shutil.copy2(src, dst)
            action = "copied"
        audit.append({"file": rel(dst), "copied_from": rel(src), "sha256": sha256(dst), "action": action,
                      "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    return audit


def load_pib_12m_lag1(offline: bool, audit: list[dict]) -> pd.Series:
    """Rolling 12-month nominal GDP (R$), lagged one month, from SGS 4380.

    Built here instead of using the panel's ``pib_12m_lag1_brl`` because the
    original data notebook parses SGS JSON values by deleting every '.', which
    is the decimal separator in the JSON API ("638091.1" -> 6380911): the panel
    GDP is 10x too large and all its *_pib variables 10x too small. The JSON
    value is parsed here with float(). Raw pulls are saved with a UTC timestamp;
    --offline (or a failed request) uses the newest saved pull.
    """
    BCB_RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw = None
    if not offline:
        try:
            import requests
            rows = []
            for y in range(1995, datetime.now().year + 1, 10):
                r = requests.get(SGS_URL.format(code=PIB_SGS_CODE), timeout=60, params={
                    "formato": "json", "dataInicial": f"01/01/{y}", "dataFinal": f"31/12/{y + 9}"})
                r.raise_for_status()
                rows += r.json()
            raw = pd.DataFrame(rows)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path = BCB_RAW_DIR / f"sgs_{PIB_SGS_CODE}_{ts}.csv"
            raw.to_csv(path, index=False)
            source = "BCB SGS API"
        except Exception as exc:  # noqa: BLE001
            print(f"SGS {PIB_SGS_CODE} download failed ({exc}); using newest saved file")
    if raw is None:
        saved = sorted(BCB_RAW_DIR.glob(f"sgs_{PIB_SGS_CODE}_*.csv"))
        if not saved:
            raise FileNotFoundError(f"No saved SGS {PIB_SGS_CODE} file in {rel(BCB_RAW_DIR)}")
        path, source = saved[-1], "saved SGS pull"
        raw = pd.read_csv(path, dtype=str)
    s = pd.Series(raw["valor"].astype(str).astype(float).to_numpy() * 1e6,
                  index=pd.PeriodIndex(pd.to_datetime(raw["data"], format="%d/%m/%Y"), freq="M"))
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s = s.reindex(pd.period_range(s.index.min(), s.index.max(), freq="M"))
    pib12_lag1 = s.rolling(12, min_periods=12).sum().shift(1)
    audit.append({"file": rel(path), "copied_from": SGS_URL.format(code=PIB_SGS_CODE), "sha256": sha256(path),
                  "action": f"{source}; GDP for normalization (R$ mi * 1e6, 12m sum, lag 1)",
                  "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    return pib12_lag1


def primary_surprise(raw_dir: Path) -> pd.DataFrame:
    """Realized minus Prisma median for the same month (forecast sent in that month).

    Recomputed instead of taken from João's panel: in prisma_realizado_mensal.csv
    the months 2020-07 to 2021-12 are dated on day 2-13 instead of day 1, so his
    merge on ``month`` dropped those 18 surprises.
    """
    real = pd.read_csv(raw_dir / "prisma_realizado_mensal.csv", parse_dates=["month"])
    real["period"] = real["month"].dt.to_period("M")
    assert not real["period"].duplicated().any()
    mon = pd.read_csv(raw_dir / "prisma_monthly_long.csv", parse_dates=["send_month", "target_month"])
    fc = mon[(mon["variable"] == PRIMARY_VAR) & (mon["stat"] == "Mediana")
             & (mon["send_month"] == mon["target_month"])].copy()
    fc["period"] = fc["target_month"].dt.to_period("M")
    fc = fc.groupby("period")["value"].mean()
    d = pd.concat([real.set_index("period")["primario"], fc], axis=1, keys=["realized", "forecast"]).dropna()
    d["surprise_brl_mi"] = d["realized"] - d["forecast"]
    return d


# ----------------------------------------------------------------------------
# construction
# ----------------------------------------------------------------------------
def prisma_event_matrix(annual: pd.DataFrame, variable: str) -> pd.DataFrame:
    """Send month x target year matrix of Prisma medians."""
    d = annual[(annual["variable"] == variable) & (annual["stat"] == "Mediana")]
    m = d.pivot_table(index="send_month", columns="target_year", values="value", aggfunc="mean")
    m.index = pd.PeriodIndex(m.index, freq="M")
    return m.sort_index()


def fixed_event_revisions(m: pd.DataFrame) -> pd.DataFrame:
    """Revision per target year between consecutive monthly sends (NaN if a send is missing)."""
    full = m.reindex(pd.period_range(m.index.min(), m.index.max(), freq="M"))
    return full - full.shift(1)


def horizon_weights(year: int, month: int, ahead: int) -> dict[int, float]:
    return {year + ahead: (12 - month) / 12, year + ahead + 1: month / 12}


def fixed_horizon_revision(rev: pd.DataFrame, ahead: int) -> pd.Series:
    out = {}
    for p, row in rev.iterrows():
        w = horizon_weights(p.year, p.month, ahead)
        vals = [row.get(y, np.nan) for y in w]
        out[p] = np.nan if any(pd.isna(v) for v in vals) else float(sum(a * b for a, b in zip(w.values(), vals)))
    return pd.Series(out, dtype=float)


def check_against_joao(rev: pd.DataFrame, news: pd.DataFrame) -> pd.DataFrame:
    """Recompute João's fixed-event h0..h3 primary revisions from the long file."""
    rows = []
    for h in range(4):
        mine = pd.Series({p: rev.loc[p].get(p.year + h, np.nan) for p in rev.index}, dtype=float)
        theirs = news.set_index("period")[f"prisma_rev_primario_brl_mi_h{h}"]
        j = pd.concat([mine, theirs], axis=1, keys=["recomputed", "joao"]).dropna()
        miss = int(mine.notna().sum() - theirs.notna().sum())
        rows.append({"check": f"prisma_rev_primario_h{h}_recomputed_vs_joao", "n_common": len(j),
                     "max_abs_diff": float((j.recomputed - j.joao).abs().max()) if len(j) else np.nan,
                     "n_obs_difference": miss})
    s = news["realizado_primario"] - news["prisma_fc_primario_m"] - news["prisma_surp_primario_brl_mi"]
    rows.append({"check": "surprise_identity", "n_common": int(s.notna().sum()),
                 "max_abs_diff": float(s.abs().max()), "n_obs_difference": 0})
    return pd.DataFrame(rows)


def coverage_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for c in df.columns:
        s = df[c].dropna()
        rows.append({"variable": c, "n_obs": len(s),
                     "first_month": s.index.min().strftime("%Y-%m") if len(s) else None,
                     "last_month": s.index.max().strftime("%Y-%m") if len(s) else None,
                     "mean": s.mean() if len(s) else np.nan, "sd": s.std() if len(s) else np.nan,
                     "min": s.min() if len(s) else np.nan, "max": s.max() if len(s) else np.nan})
    return pd.DataFrame(rows)


def plot_outputs(df: pd.DataFrame) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    cols = [("prisma_primary_12m_rev_curr_pib", "Prisma (Gov. Central), % PIB"),
            ("focus_primary_12m_rev_curr", "Focus (setor público), % PIB")]
    d = df.loc["2015-12-01":]
    for c, lab in cols:
        if c in d:
            axes[0].plot(d.index, d[c], label=lab, lw=1)
    axes[0].axhline(0, color="grey", lw=0.5)
    axes[0].set_title("Revisão do primário esperado, horizonte fixo de 12 meses (mês t)")
    axes[0].legend(fontsize=8)
    if "prisma_primary_surp_pib_release" in d:
        axes[1].bar(d.index, d["prisma_primary_surp_pib_release"], width=20, color="tab:gray")
    axes[1].axhline(0, color="grey", lw=0.5)
    axes[1].set_title("Surpresa do primário (realizado − Prisma), % PIB, datada no mês de divulgação aprox.")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "prisma_fiscal_news.png", dpi=150)
    plt.close(fig)


# ----------------------------------------------------------------------------
def main() -> None:
    for d in (INTERMEDIATE_DIR, CLEAN_DIR, DIAGNOSTICS_DIR, FIGURES_DIR):
        d.mkdir(parents=True, exist_ok=True)
    audit = preserve_delivery()

    panel_path = find_input_panel()
    panel = pd.read_csv(panel_path)
    panel["month"] = pd.to_datetime(panel["month"])
    print(f"Input panel: {rel(panel_path)} ({len(panel)} rows)")

    news = pd.read_csv(RAW_DIR / "fiscal_news_monthly.csv", parse_dates=["month"])
    news["period"] = news["month"].dt.to_period("M")
    annual = pd.read_csv(RAW_DIR / "prisma_annual_long_corrected.csv", parse_dates=["send_month"])

    rev = fixed_event_revisions(prisma_event_matrix(annual, PRIMARY_VAR))
    checks = check_against_joao(rev, news)

    # full monthly index covering the news data and the panel
    start = min(news["month"].min(), panel["month"].min())
    end = max(news["month"].max(), panel["month"].max())
    idx = pd.period_range(start, end, freq="M")
    pib = load_pib_12m_lag1("--offline" in sys.argv, audit).reindex(idx)
    if "pib_12m_lag1_brl" in panel:
        ratio = (panel.set_index(panel["month"].dt.to_period("M"))["pib_12m_lag1_brl"] / pib).dropna()
        print(f"Panel pib_12m_lag1_brl / SGS-built GDP: median {ratio.median():.3f} "
              f"(10 = known decimal-parsing bug in the data notebook)")
    to_pib = 1e6 / pib * 100          # R$ mi -> % of lagged 12m GDP

    out = pd.DataFrame(index=idx)
    for h, ahead in HORIZONS.items():
        r = fixed_horizon_revision(rev, ahead).reindex(idx)
        out[f"prisma_primary_{h}_rev_curr_brl_mi"] = r
        out[f"prisma_primary_{h}_rev_curr_pib"] = r * to_pib
        out[f"prisma_primary_{h}_rev_lag1_pib"] = (r * to_pib).shift(1)
    sdf = primary_surprise(RAW_DIR)
    j = sdf.join(news.set_index("period")["prisma_surp_primario_brl_mi"], how="inner").dropna()
    checks = pd.concat([checks, pd.DataFrame([{
        "check": "surprise_recomputed_vs_joao (common months)", "n_common": len(j),
        "max_abs_diff": float((j.surprise_brl_mi - j.prisma_surp_primario_brl_mi).abs().max()),
        "n_obs_difference": int(len(sdf) - news["prisma_surp_primario_brl_mi"].notna().sum())}])],
        ignore_index=True)
    surp = sdf["surprise_brl_mi"].reindex(idx)
    out["prisma_primary_surp_brl_mi"] = surp
    out["prisma_primary_surp_pib"] = surp * to_pib
    # release-dated: news about month t arrives in t+1; normalize by GDP known then
    out["prisma_primary_surp_pib_release"] = surp.shift(1) * to_pib

    joao_cols = [c for c in news.columns if c not in ("month", "period", "release_month_approx")]
    out = out.join(news.set_index("period")[joao_cols].reindex(idx))
    out.index = out.index.to_timestamp()
    out.index.name = "month"

    out_file = out.copy()
    out_file.index = out_file.index.strftime("%Y-%m-%d")
    out_file.to_csv(INTERMEDIATE_DIR / "prisma_fiscal_news_monthly.csv")

    # merge: keep every panel row; refuse to overwrite existing columns
    clash = [c for c in out.columns if c in panel.columns]
    if clash:
        raise ValueError(f"Columns already in input panel: {clash}")
    merged = panel.merge(out.reset_index(), on="month", how="left", validate="1:1")
    assert len(merged) == len(panel)
    lost = out.dropna(how="all").index.difference(panel["month"])
    merged["month"] = merged["month"].dt.strftime("%Y-%m-%d")
    merged.to_csv(OUTPUT_PANEL, index=False)

    # validation against the existing Focus fixed-horizon revisions
    val_rows = []
    for a, b in [("prisma_primary_12m_rev_curr_pib", "focus_primary_12m_rev_curr"),
                 ("prisma_primary_36m_rev_curr_pib", "focus_primary_36m_rev_curr"),
                 ("focus_rev_primario_pp_h0", "focus_primary_12m_rev_curr"),
                 ("focus_rev_dlsp_pp_h1", "focus_dlsp_12m_rev_curr")]:
        if a in merged and b in merged:
            j = merged[[a, b]].dropna()
            val_rows.append({"check": f"corr({a}, {b})", "n_common": len(j),
                             "max_abs_diff": np.nan, "n_obs_difference": np.nan,
                             "correlation": j[a].corr(j[b]) if len(j) > 2 else np.nan})
    checks = pd.concat([checks, pd.DataFrame(val_rows)], ignore_index=True)

    pd.DataFrame(audit).to_csv(DIAGNOSTICS_DIR / "prisma_fiscal_news_audit.csv", index=False)
    checks.to_csv(DIAGNOSTICS_DIR / "prisma_fiscal_news_validation.csv", index=False)
    cov = coverage_table(out)
    cov.to_csv(DIAGNOSTICS_DIR / "prisma_fiscal_news_diagnostics.csv", index=False)

    cols = list(out.columns)
    lists = {
        "purge_main_contemporaneous_do_not_use_as_controls": [
            "prisma_primary_12m_rev_curr_pib", "prisma_primary_36m_rev_curr_pib"],
        "purge_surprise_release_dated": ["prisma_primary_surp_pib_release"],
        "predetermined_revisions": [c for c in cols if c.endswith("_rev_lag1_pib")],
        "fixed_event_original_joao_contemporaneous": [c for c in joao_cols if "_rev_" in c],
        "reference_only_not_news": ["realizado_primario", "prisma_fc_primario_m",
                                    "prisma_surp_primario_brl_mi", "prisma_primary_surp_brl_mi",
                                    "prisma_primary_surp_pib",
                                    "prisma_primary_12m_rev_curr_brl_mi", "prisma_primary_36m_rev_curr_brl_mi"],
        "notes": [
            "Positive primary revision = higher expected surplus (good fiscal news); "
            "positive DLSP/DBGG revision = higher expected debt (bad news).",
            "Prisma = Central Government; Focus = consolidated public sector.",
            "prisma_rev_dbgg_gg_pp_* (2015-2020) and prisma_rev_dbgg_gc_pp_* (2021-) are different "
            "concepts; do not splice.",
            "Focus revisions in João's file use baseCalculo=0 (30-day window medians), which smooths "
            "month-end revisions; prefer focus_*_rev_curr from build_fiscal_expectations_controls.py "
            "or rebuild with baseCalculo=1.",
        ],
    }
    (DIAGNOSTICS_DIR / "prisma_fiscal_news_lists.json").write_text(
        json.dumps(lists, indent=2, ensure_ascii=False), encoding="utf-8")

    plot_outputs(merged.assign(month=pd.to_datetime(merged["month"])).set_index("month"))

    print(f"\nWrote {rel(OUTPUT_PANEL)} ({len(merged)} rows, +{out.shape[1]} columns)")
    if len(lost):
        print(f"Note: {len(lost)} months of news fall outside the panel and are only in the "
              f"intermediate file ({lost.min():%Y-%m} to {lost.max():%Y-%m}).")
    print("\nValidation:")
    print(checks.to_string(index=False))
    main_cols = lists["purge_main_contemporaneous_do_not_use_as_controls"] + ["prisma_primary_surp_pib_release"]
    print("\nCoverage of main series:")
    print(cov[cov.variable.isin(main_cols)][["variable", "first_month", "last_month", "n_obs"]].to_string(index=False))


if __name__ == "__main__":
    main()
