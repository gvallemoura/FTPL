#!/usr/bin/env python3
"""Extend the debt stock by class (N, F, R) back to 2000 with BCB SGS series.

The panel's stock by class comes from Tesouro's ``estoquedpf.csv`` (eDPF),
which only starts in 2017-09. The BCB SGS publishes the stock of federal
securities held by the market ("posicao em carteira", excluding the BCB
portfolio), by security, monthly since 2000-02 (R$ million):

| SGS   | series                                                        | use          |
|-------|---------------------------------------------------------------|--------------|
| 10634 | Saldos - posicao em carteira - indexado a Selic - LFT         | F            |
| 10642 | Saldos - posicao em carteira - indexado ao IPCA - NTN-B       | R            |
| 10647 | Saldos - posicao em carteira - indexado ao IGP-M - NTN-C      | coverage     |
| 10649 | Saldos - posicao em carteira - pre-fixado - LTN               | N (LTN)      |
| 10650 | small pre-fixed item, 2002-02 to 2005-09, <= R$ 0.12 bn       | excluded     |
| 10651 | Saldos - posicao em carteira - pre-fixado - total             | N            |
| 4154  | Titulos do Tesouro Nacional - posicao em carteira - em mercado| denominator  |

N = 10651 - 10650 (= LTN + NTN-F). NTN-F has no own series; it is the
pre-fixed total minus LTN minus 10650 (non-negative up to +-1 rounding;
NTN-F appears in 2005-02). This replaces João's construction
(``stock_by_group_bcb_sgs.csv``), which inferred NTN-F from the percentage
shares 4177/4178 and produced negative NTN-F in 2000-2004 and N errors of up to
11.6%.

Splice rule: eDPF (panel ``stock_*_brl``) wherever it exists; SGS in every
other month (before 2017-09 and after the last eDPF month). Over the common
period both must agree (max relative gap <= MAX_REL_GAP), otherwise the script
stops. SGS months are dated on day 01 and correspond to the end-of-month stock
of that month (changes correlate 1.0 with eDPF at lag 0).

Outputs (new columns only; existing columns are never modified):

- ``stock_{N,F,R,total_NFR}_hist_brl``: spliced stock (R$); ``stock_hist_source``.
- ``stock_market_total_sgs_brl`` (4154) and ``stock_ntnc_sgs_brl`` (10647).
- ``share_{g}_hist``: share in N+F+R (same definition as ``share_{g}``).
- ``share_{g}_hist_mkt``: share in total market stock (4154).
- ``coverage_NFR_over_market``: (N+F+R) / market total.
- predetermined versions: ``*_lag1``, ``stock_{g}_hist_pib_lag1`` and
  ``gross_{g}_over_lag_stock_hist`` (same formulas as the eDPF columns).

Run from the project root:  python3 src/build_stock_history_sgs.py [--offline]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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

BCB_RAW_DIR = DATA_DIR / "raw" / "bcb"
INTERMEDIATE_DIR = DATA_DIR / "intermediate" / "stock_history"
CLEAN_DIR = DATA_DIR / "clean"
DIAGNOSTICS_DIR = DATA_DIR / "diagnostics"
FIGURES_DIR = DATA_DIR / "figures"

SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
SGS_SERIES = {
    10634: "LFT, posicao em carteira (R$ mi)",
    10642: "NTN-B, posicao em carteira (R$ mi)",
    10647: "NTN-C, posicao em carteira (R$ mi)",
    10649: "LTN, posicao em carteira (R$ mi)",
    10650: "pre-fixado, item residual 2002-2005 (R$ mi)",
    10651: "pre-fixado total, posicao em carteira (R$ mi)",
    4154: "Titulos do Tesouro Nacional, total em mercado (R$ mi)",
}
GROUPS = ["N", "F", "R"]
MAX_REL_GAP = 0.005  # 0.5% tolerance for eDPF vs SGS levels over the common period

PANEL_CANDIDATES = [
    CLEAN_DIR / "ftpl_monthly_panel_with_valuation_outcomes.csv",
    CLEAN_DIR / "ftpl_monthly_panel_with_fiscal_news.csv",
    CLEAN_DIR / "ftpl_monthly_panel_with_fiscal_expectations.csv",
    CLEAN_DIR / "ftpl_monthly_panel_with_yield_curve_controls.csv",
]
OUTPUT_PANEL = CLEAN_DIR / "ftpl_monthly_panel_with_stock_history.csv"


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


def load_sgs(code: int, offline: bool, audit: list[dict]) -> pd.Series:
    """Monthly SGS series (R$ mi). Raw pull saved with UTC timestamp, never overwritten.

    JSON values use '.' as decimal separator and are parsed with float().
    --offline (or a failed request) uses the newest saved pull.
    """
    BCB_RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw, source = None, None
    if not offline:
        try:
            import requests
            r = requests.get(SGS_URL.format(code=code), timeout=90, params={
                "formato": "json", "dataInicial": "01/01/1999",
                "dataFinal": datetime.now().strftime("%d/%m/%Y")})
            r.raise_for_status()
            raw = pd.DataFrame(r.json(), dtype=str)
            if not {"data", "valor"}.issubset(raw.columns) or raw.empty:
                raise ValueError("unexpected SGS response")
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path = BCB_RAW_DIR / f"sgs_{code}_{ts}.csv"
            if path.exists():
                raise RuntimeError(f"{rel(path)} already exists; refusing to overwrite")
            raw.to_csv(path, index=False)
            source = "BCB SGS API"
        except Exception as exc:  # noqa: BLE001
            print(f"SGS {code} download failed ({exc}); using newest saved file")
            raw = None
    if raw is None:
        saved = sorted(BCB_RAW_DIR.glob(f"sgs_{code}_*.csv"))
        if not saved:
            raise FileNotFoundError(f"No saved SGS {code} file in {rel(BCB_RAW_DIR)}")
        path, source = saved[-1], "saved SGS pull"
        raw = pd.read_csv(path, dtype=str)
    s = pd.Series(raw["valor"].astype(str).str.strip().astype(float).to_numpy(),
                  index=pd.PeriodIndex(pd.to_datetime(raw["data"], format="%d/%m/%Y"), freq="M"))
    if s.index.duplicated().any():
        raise ValueError(f"SGS {code}: duplicated months")
    audit.append({"sgs_code": code, "description": SGS_SERIES[code], "file": rel(path), "sha256": sha256(path),
                  "source": source, "url": SGS_URL.format(code=code),
                  "first_month": str(s.index.min()), "last_month": str(s.index.max()), "n_obs": len(s),
                  "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    return s.sort_index()


def coverage_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for c in df.columns:
        s = pd.to_numeric(df[c], errors="coerce").dropna()
        span = pd.period_range(s.index.min(), s.index.max(), freq="M") if len(s) else []
        rows.append({"variable": c, "n_obs": len(s),
                     "first_month": str(s.index.min()) if len(s) else None,
                     "last_month": str(s.index.max()) if len(s) else None,
                     "internal_gaps": len(span) - len(s) if len(s) else 0,
                     "mean": s.mean(), "min": s.min(), "max": s.max()})
    return pd.DataFrame(rows)


def plot_outputs(out: pd.DataFrame, edpf_start: pd.Period, edpf_end: pd.Period) -> None:
    d = out.loc["2000-01":]
    t = d.index.to_timestamp()
    fig, axes = plt.subplots(3, 1, figsize=(10, 10), sharex=True)
    for g in GROUPS:
        axes[0].plot(t, d[f"stock_{g}_hist_brl"] / 1e9, label=g, lw=1.2)
    axes[0].set_title("Estoque em mercado por classe (R$ bi); sombreado = eDPF, fora = SGS")
    axes[0].legend(fontsize=8)
    for g in GROUPS:
        line, = axes[1].plot(t, d[f"share_{g}_hist"], label=f"{g} / (N+F+R)", lw=1.2)
        axes[1].plot(t, d[f"share_{g}_hist_mkt"], ls="--", lw=1, color=line.get_color(),
                     label=f"{g} / total em mercado")
    axes[1].set_title("Participações: sobre N+F+R (contínua) e sobre o total em mercado (tracejada)")
    axes[1].legend(fontsize=7, ncol=3)
    axes[2].plot(t, d["coverage_NFR_over_market"], color="black", lw=1.2)
    axes[2].set_title("Cobertura: (N+F+R) / total de títulos do Tesouro em mercado")
    for ax in axes:
        ax.axvspan(edpf_start.to_timestamp(), edpf_end.to_timestamp(), color="grey", alpha=0.12)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "stock_history_sgs.png", dpi=150)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="use newest saved SGS pulls")
    args = parser.parse_args()
    for d in (INTERMEDIATE_DIR, CLEAN_DIR, DIAGNOSTICS_DIR, FIGURES_DIR):
        d.mkdir(parents=True, exist_ok=True)

    panel_path = find_input_panel()
    panel = pd.read_csv(panel_path)
    panel["month"] = pd.to_datetime(panel["month"])
    print(f"Input panel: {rel(panel_path)} ({len(panel)} rows)")
    p = panel.set_index(panel["month"].dt.to_period("M"))

    audit: list[dict] = []
    sgs = pd.DataFrame({c: load_sgs(c, args.offline, audit) for c in SGS_SERIES})
    sgs = sgs.reindex(pd.period_range(sgs.index.min(), sgs.index.max(), freq="M"))

    # --- SGS stocks by class, R$ ---------------------------------------------
    ntnf = sgs[10651] - sgs[10649] - sgs[10650].fillna(0)
    s_cls = pd.DataFrame({
        "N": (sgs[10651] - sgs[10650].fillna(0)) * 1e6,
        "F": sgs[10634] * 1e6,
        "R": sgs[10642] * 1e6,
    })
    s_cls = s_cls.dropna(how="all")

    # --- eDPF stocks from the panel -----------------------------------------
    e_cls = p[[f"stock_{g}_brl" for g in GROUPS]].rename(columns=lambda c: c.split("_")[1]).dropna(how="any")
    edpf_start, edpf_end = e_cls.index.min(), e_cls.index.max()

    # --- validation over the common period ----------------------------------
    common = e_cls.index.intersection(s_cls.dropna().index)
    checks = []
    for g in GROUPS:
        gap = s_cls.loc[common, g] / e_cls.loc[common, g] - 1
        dcorr = np.corrcoef(s_cls.loc[common, g].diff().dropna(), e_cls.loc[common, g].diff().dropna())[0, 1]
        checks.append({"check": f"{g}: max |SGS/eDPF - 1| (common period)", "n": len(common),
                       "value": float(gap.abs().max()), "worst_month": str(gap.abs().idxmax())})
        checks.append({"check": f"{g}: mean SGS/eDPF - 1", "n": len(common), "value": float(gap.mean()),
                       "worst_month": None})
        checks.append({"check": f"{g}: corr of monthly changes SGS vs eDPF (lag 0)", "n": len(common) - 1,
                       "value": float(dcorr), "worst_month": None})
    sh_s = s_cls.loc[common].div(s_cls.loc[common].sum(axis=1), axis=0)
    sh_e = e_cls.loc[common].div(e_cls.loc[common].sum(axis=1), axis=0)
    for g in GROUPS:
        checks.append({"check": f"share_{g}: max |SGS - eDPF| (pp)", "n": len(common),
                       "value": float((sh_s[g] - sh_e[g]).abs().max() * 100), "worst_month": None})
    neg = ntnf[ntnf < -1.5]
    checks.append({"check": "implied NTN-F < -1.5 R$ mi (rounding tolerance), months", "n": int(ntnf.notna().sum()),
                   "value": float(len(neg)), "worst_month": str(neg.idxmin()) if len(neg) else None})
    checks.append({"check": "first month with NTN-F > R$ 1 bn", "n": None,
                   "value": None, "worst_month": str(ntnf[ntnf > 1000].index.min())})
    checks = pd.DataFrame(checks)
    worst = checks[checks.check.str.contains("max \\|SGS/eDPF")]["value"].max()
    status = "PASS" if worst <= MAX_REL_GAP and len(neg) == 0 else "FAIL"
    checks.loc[len(checks)] = {"check": f"splice status (max level gap <= {MAX_REL_GAP:.1%}, no negative NTN-F)",
                               "n": len(common), "value": None, "worst_month": status}
    checks.to_csv(DIAGNOSTICS_DIR / "stock_history_sgs_validation.csv", index=False)
    if status != "PASS":
        print(checks.to_string(index=False))
        raise RuntimeError("eDPF and SGS stocks disagree beyond tolerance; splice not built")

    # --- splice: eDPF where available, SGS elsewhere --------------------------
    idx = pd.period_range(s_cls.index.min(), max(s_cls.index.max(), edpf_end), freq="M")
    out = pd.DataFrame(index=idx)
    use_e = idx.isin(e_cls.index)
    for g in GROUPS:
        out[f"stock_{g}_hist_brl"] = np.where(use_e, e_cls[g].reindex(idx), s_cls[g].reindex(idx))
    out["stock_total_NFR_hist_brl"] = out[[f"stock_{g}_hist_brl" for g in GROUPS]].sum(axis=1, min_count=3)
    out["stock_hist_source"] = np.where(use_e, "eDPF",
                                        np.where(out["stock_total_NFR_hist_brl"].notna(), "SGS", None))
    out["stock_market_total_sgs_brl"] = sgs[4154].reindex(idx) * 1e6
    out["stock_ntnc_sgs_brl"] = sgs[10647].reindex(idx) * 1e6
    for g in GROUPS:
        out[f"share_{g}_hist"] = out[f"stock_{g}_hist_brl"] / out["stock_total_NFR_hist_brl"]
        out[f"share_{g}_hist_mkt"] = out[f"stock_{g}_hist_brl"] / out["stock_market_total_sgs_brl"]
    out["coverage_NFR_over_market"] = out["stock_total_NFR_hist_brl"] / out["stock_market_total_sgs_brl"]

    # predetermined versions, same formulas as the eDPF columns of the panel
    pib = p["pib_12m_lag1_brl"].reindex(idx)
    gross = p[[f"gross_{g}_brl" for g in GROUPS]].reindex(idx)
    for g in GROUPS:
        out[f"share_{g}_hist_lag1"] = out[f"share_{g}_hist"].shift(1)
        out[f"share_{g}_hist_mkt_lag1"] = out[f"share_{g}_hist_mkt"].shift(1)
    for g in GROUPS + ["total_NFR"]:
        out[f"stock_{g}_hist_brl_lag1"] = out[f"stock_{g}_hist_brl"].shift(1)
        out[f"stock_{g}_hist_pib_lag1"] = out[f"stock_{g}_hist_brl_lag1"] / pib
    for g in GROUPS:
        out[f"gross_{g}_over_lag_stock_hist"] = gross[f"gross_{g}_brl"] / out[f"stock_{g}_hist_brl_lag1"]
    out["coverage_NFR_over_market_lag1"] = out["coverage_NFR_over_market"].shift(1)
    out.index.name = "month"

    # consistency: spliced columns reproduce the panel's eDPF columns exactly
    for g in GROUPS:
        a = out.loc[e_cls.index, f"share_{g}_hist"]
        b = p.loc[e_cls.index, f"share_{g}"]
        assert float((a - b).abs().max()) < 1e-12, f"share_{g}_hist differs from share_{g} on eDPF months"

    # --- write -----------------------------------------------------------------
    inter = pd.DataFrame({"stock_N_sgs_brl": s_cls["N"], "stock_F_sgs_brl": s_cls["F"],
                          "stock_R_sgs_brl": s_cls["R"], "stock_ltn_sgs_brl": sgs[10649] * 1e6,
                          "stock_ntnf_implied_sgs_brl": ntnf * 1e6}).reindex(idx).join(out)
    inter_file = inter.copy()
    inter_file.index = inter_file.index.to_timestamp().strftime("%Y-%m-%d")
    inter_file.to_csv(INTERMEDIATE_DIR / "stock_history_sgs_monthly.csv")

    out_ts = out.copy()
    out_ts.index = out_ts.index.to_timestamp()
    clash = [c for c in out_ts.columns if c in panel.columns]
    if clash:
        raise ValueError(f"Columns already in input panel: {clash}")
    merged = panel.merge(out_ts.reset_index(), on="month", how="left", validate="1:1")
    assert len(merged) == len(panel)
    merged["month"] = merged["month"].dt.strftime("%Y-%m-%d")
    merged.to_csv(OUTPUT_PANEL, index=False)

    pd.DataFrame(audit).to_csv(DIAGNOSTICS_DIR / "stock_history_sgs_audit.csv", index=False)
    cov = coverage_table(out.drop(columns=["stock_hist_source"]))
    src = out["stock_hist_source"].dropna()
    spans = (src.groupby((src != src.shift()).cumsum())
             .agg(lambda s: f"{s.iloc[0]}: {s.index.min()} to {s.index.max()} ({len(s)} months)"))
    cov.to_csv(DIAGNOSTICS_DIR / "stock_history_sgs_diagnostics.csv", index=False)

    lists = {
        "predetermined_controls_main": [f"share_{g}_hist_lag1" for g in GROUPS]
        + [f"stock_{g}_hist_pib_lag1" for g in GROUPS + ["total_NFR"]],
        "predetermined_controls_robustness": [f"share_{g}_hist_mkt_lag1" for g in GROUPS]
        + ["coverage_NFR_over_market_lag1"],
        "dependent_variable_candidates": [f"gross_{g}_over_lag_stock_hist" for g in GROUPS],
        "contemporaneous_not_controls": [f"share_{g}_hist" for g in GROUPS]
        + [f"share_{g}_hist_mkt" for g in GROUPS] + [f"stock_{g}_hist_brl" for g in GROUPS + ["total_NFR"]],
        "splice_segments": spans.tolist(),
        "notes": [
            "eDPF (Tesouro estoquedpf.csv, Mercado) where available; BCB SGS 'posicao em carteira' elsewhere.",
            "N = SGS 10651 - 10650 (LTN + NTN-F); NTN-F has no own SGS series.",
            "Before ~2005 N+F+R covers only 70-82% of the market stock (NTN-C, FX-linked, LFT-A/B); "
            "use the _mkt shares and a 2005+ sample as robustness.",
            "NTN-B is zero before 2002-01 and NTN-F before 2005-02: share_R and share_N(NTN-F part) are "
            "structurally zero there, not missing.",
            "Do not use DadosJoao stock_by_group_bcb_sgs.csv: its NTN-F is inferred from the 4177/4178 "
            "percentages and is negative in 2000-2004.",
        ],
    }
    (DIAGNOSTICS_DIR / "stock_history_sgs_lists.json").write_text(
        json.dumps(lists, indent=2, ensure_ascii=False), encoding="utf-8")

    plot_outputs(out, edpf_start, edpf_end)

    print(f"\nWrote {rel(OUTPUT_PANEL)} ({len(merged)} rows, +{out.shape[1]} columns)")
    print("Splice segments:\n  " + "\n  ".join(spans.tolist()))
    print("\nValidation:")
    print(checks.to_string(index=False))
    print("\nCoverage (main columns):")
    main_cols = [f"share_{g}_hist_lag1" for g in GROUPS] + ["coverage_NFR_over_market",
                                                             "gross_N_over_lag_stock_hist"]
    print(cov[cov.variable.isin(main_cols)][["variable", "first_month", "last_month", "n_obs",
                                             "internal_gaps"]].to_string(index=False))


if __name__ == "__main__":
    main()
