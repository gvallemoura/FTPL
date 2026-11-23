#!/usr/bin/env python3
"""Build Focus fiscal-expectation variables for the FTPL monthly panel.

Source: Banco Central do Brasil, Focus survey (Olinda OData API, no key),
``ExpectativasMercadoAnuais``, all respondents (``baseCalculo = 0``):

- "Dívida líquida do setor público"  -> expected net public debt, % of GDP;
- "Resultado primário"               -> expected primary balance, % of GDP
                                        (positive = surplus).

Method adapted from the replication package of Carvalho Filho (2026),
"Fiscal Risk, Real Interest Rates and the Stock Market: Evidence from Brazil",
doi:10.5281/zenodo.24206681 (CC-BY-4.0), functions ``focus_annual`` and
``fixed_horizon`` in ``fetch_data.py``. Differences from that code: we keep the
daily survey-date series, take end-of-previous-month values (not the monthly
mean of the current month), and add fixed-event revisions.

Fixed-horizon conversion (survey dated in calendar month m of year Y):

    x^{12m} = (12 - m)/12 * E[Y]     + m/12 * E[Y + 1]
    x^{36m} = (12 - m)/12 * E[Y + 2] + m/12 * E[Y + 3]

Monthly outputs for month t (``month`` = YYYY-MM-01):

- ``*_eom_lag1``: last survey value with availability date <= end of t-1.
  PREDETERMINED -> may enter the issuance-forecasting equation.
- ``*_avg_lag1``: mean of daily survey values in t-1. PREDETERMINED.
- ``*_rev_lag1``: fixed-event revision during t-1 (end of t-1 vs end of t-2),
  weighted with the horizon weights. PREDETERMINED.
- ``*_rev_curr``: the same revision during month t (end of t vs end of t-1).
  CONTEMPORANEOUS -> fiscal-backing news for the survey purge only. It must
  NOT enter the issuance-forecasting equation as a control.

Revisions are computed per reference year (fixed event) and then weighted, so
they do not contain the mechanical change from rolling the horizon forward.

Source priority: (1) live Olinda API, saved to ``data/raw/focus/`` with a UTC
timestamp; (2) the newest previously saved raw file; (3) the frozen file from
the Zenodo replication package. The source used is recorded in the audit file.

baseCalculo = 1 versions (prefixes ``focus_primary_bc1`` and ``focus_dlsp_bc1``): the
median of the latest answers given from the 4th business day before the
calculation date (baseCalculo = 0 uses answers from the previous 30 days), so
month-end revisions are not smoothed by stale answers. The API only has them from
2021-03-31 on, with fewer respondents (about 8-20 against 20-60), so they are a
robustness version on 2021-04+ and do not replace the baseCalculo = 0 series.
Diagnostics compare both versions on the common months.

Run from the project root:  python3 src/build_fiscal_expectations_controls.py
Optional flags: --offline (skip the API and use local files);
--fetch PREFIX[,PREFIX] (call the API only for these prefixes, local files for
the others; e.g. --fetch focus_primary_bc1,focus_dlsp_bc1).
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests


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

RAW_DIR = DATA_DIR / "raw" / "focus"
ZENODO_RAW_DIR = DATA_DIR / "raw" / "zenodo_24206681_fiscal_svar" / "fiscal_svar" / "data" / "raw"
INTERMEDIATE_DIR = DATA_DIR / "intermediate" / "focus"
CLEAN_DIR = DATA_DIR / "clean"
DIAGNOSTICS_DIR = DATA_DIR / "diagnostics"
FIGURES_DIR = DATA_DIR / "figures"

OLINDA_URL = (
    "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
    "ExpectativasMercadoAnuais"
)

# variable prefix -> (Focus indicator name, frozen Zenodo file name, baseCalculo)
INDICATORS = {
    "focus_dlsp": ("Dívida líquida do setor público", "focus_annual_debt.csv", 0),
    "focus_primary": ("Resultado primário", "focus_annual_primary.csv", 0),
    "focus_dlsp_bc1": ("Dívida líquida do setor público", None, 1),
    "focus_primary_bc1": ("Resultado primário", None, 1),
}
MAIN_PREFIXES = ["focus_dlsp", "focus_primary"]  # baseCalculo = 0, full sample
# horizon label -> years ahead of the survey year for the first reference year
HORIZONS = {"12m": 0, "36m": 2}

# Days between the survey reference date ("Data") and the date the value is
# treated as known. 0 follows Carvalho Filho (2026). Set e.g. 3 to require the
# weekly Focus report (Friday data, Monday release) to be out before month end.
PUBLICATION_LAG_DAYS = 0

# Impulse dummies for months whose revisions are driven by documented non-fiscal
# or mechanical events. Chosen by event, not by outlier size: statistical
# outliers without such a documented cause are only flagged in diagnostics,
# because they may be genuine fiscal news that the purge must keep.
# Each dummy is 1 in the event month t (matches *_rev_curr); a *_lag1 version
# is 1 in t+1 (matches *_rev_lag1).
EVENT_DUMMIES = {
    "d_focus_gdprev_2007m04": {
        "months": ["2007-04"],
        "reason": "IBGE national-accounts revision (released 21 Mar 2007) raised nominal GDP "
                  "and lowered debt ratios mechanically; expected net debt 12m fell ~5 pp "
                  "between 28 Mar and 16 Apr 2007 (largest daily drop 9 Apr).",
    },
    **{
        f"d_focus_covid_2020m{m:02d}": {
            "months": [f"2020-{m:02d}"],
            "reason": "COVID-19 shock and emergency fiscal response (state of calamity, "
                      "Decreto Legislativo 6/2020; spending outside fiscal rules).",
        }
        for m in range(3, 8)
    },
}
OUTLIER_Z = 3.0

PANEL_CANDIDATES = [
    CLEAN_DIR / "ftpl_monthly_panel_with_yield_curve_controls.csv",
    CLEAN_DIR / "ftpl_monthly_panel_structural_controls.csv",
    CLEAN_DIR / "ftpl_monthly_panel_with_pib_normalization.csv",
    CLEAN_DIR / "ftpl_monthly_panel.csv",
]
OUTPUT_PANEL = CLEAN_DIR / "ftpl_monthly_panel_with_fiscal_expectations.csv"


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def ensure_directories() -> None:
    for d in (RAW_DIR, INTERMEDIATE_DIR, CLEAN_DIR, DIAGNOSTICS_DIR, FIGURES_DIR):
        d.mkdir(parents=True, exist_ok=True)


def find_input_panel() -> Path:
    for path in PANEL_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError("No monthly panel found among: " + ", ".join(rel(p) for p in PANEL_CANDIDATES))


# ----------------------------------------------------------------------------
# download / load
# ----------------------------------------------------------------------------
def fetch_focus_annual(indicator: str, base_calculo: int = 0, page: int = 10000,
                       tries: int = 3) -> pd.DataFrame:
    """All Focus annual medians for one indicator (all respondents)."""
    rows: list[dict] = []
    skip = 0
    while True:
        params = {
            "$filter": f"Indicador eq '{indicator}' and baseCalculo eq {base_calculo}",
            "$select": "Indicador,Data,DataReferencia,Mediana,numeroRespondentes,baseCalculo",
            "$format": "json",
            "$top": str(page),
            "$skip": str(skip),
            "$orderby": "Data asc",
        }
        # Olinda rejects '+' for spaces: build the query with %20 explicitly.
        query = "&".join(f"{k}={requests.utils.quote(v, safe=chr(39) + ',')}" for k, v in params.items())
        for attempt in range(tries):
            try:
                resp = requests.get(f"{OLINDA_URL}?{query}", timeout=300)
                resp.raise_for_status()
                chunk = resp.json()["value"]
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == tries - 1:
                    raise
                print(f"   retry {attempt + 1} ({exc})")
                time.sleep(3 * (attempt + 1))
        rows += chunk
        if len(chunk) < page:
            break
        skip += page
    if not rows:
        raise RuntimeError(f"Olinda returned no rows for {indicator!r}")
    return pd.DataFrame(rows)


def newest_local_raw(prefix: str) -> Path | None:
    files = sorted(RAW_DIR.glob(f"{prefix}_annual_*.csv"))
    return files[-1] if files else None


def load_indicator(prefix: str, offline: bool, audit: list[dict]) -> pd.DataFrame:
    """Return raw annual medians with columns Data, DataReferencia, Mediana."""
    indicator, zenodo_file, base_calculo = INDICATORS[prefix]
    source, source_file, note = None, None, ""
    df = None

    if not offline:
        try:
            print(f"Olinda API: {indicator} (baseCalculo={base_calculo})")
            df = fetch_focus_annual(indicator, base_calculo)
            out = RAW_DIR / f"{prefix}_annual_{timestamp_utc()}.csv"
            df.to_csv(out, index=False)  # new timestamped file, never overwrites
            source, source_file = "BCB_OLINDA_API", rel(out)
        except Exception as exc:  # noqa: BLE001
            note = f"API failed: {exc}. "
            print(f"   API failed ({exc}); falling back to local files")
            df = None

    if df is None:
        local = newest_local_raw(prefix)
        if local is not None:
            df = pd.read_csv(local)
            source, source_file = "BCB_OLINDA_API_SAVED", rel(local)
        elif zenodo_file and (ZENODO_RAW_DIR / zenodo_file).exists():
            df = pd.read_csv(ZENODO_RAW_DIR / zenodo_file)
            source, source_file = "ZENODO_24206681_FROZEN", rel(ZENODO_RAW_DIR / zenodo_file)
        else:
            raise FileNotFoundError(f"No source available for {indicator!r}")

    if "baseCalculo" in df.columns and not (pd.to_numeric(df["baseCalculo"]) == base_calculo).all():
        raise ValueError(f"{prefix}: raw file mixes baseCalculo values")
    df = df[["Data", "DataReferencia", "Mediana"]].copy()
    df["Data"] = pd.to_datetime(df["Data"])
    df["DataReferencia"] = pd.to_numeric(df["DataReferencia"], errors="coerce")
    df["Mediana"] = pd.to_numeric(df["Mediana"], errors="coerce")
    df = df.dropna()
    df["DataReferencia"] = df["DataReferencia"].astype(int)

    audit.append({
        "variable_prefix": prefix,
        "focus_indicator": indicator,
        "source": source,
        "source_url": OLINDA_URL,
        "source_file": source_file,
        "n_rows_raw": len(df),
        "first_survey_date": df["Data"].min().date().isoformat(),
        "last_survey_date": df["Data"].max().date().isoformat(),
        "publication_lag_days": PUBLICATION_LAG_DAYS,
        "run_timestamp_utc": timestamp_utc(),
        "notes": note + f"Medians, all respondents (baseCalculo={base_calculo}); % of GDP; "
                 "fixed-horizon weights by survey calendar month.",
    })
    return df


# ----------------------------------------------------------------------------
# transformations
# ----------------------------------------------------------------------------
def fixed_event_matrix(raw: pd.DataFrame) -> pd.DataFrame:
    """Survey date x reference year matrix of medians (availability-dated)."""
    m = raw.groupby(["Data", "DataReferencia"])["Mediana"].mean().unstack().sort_index()
    m.index = m.index + pd.Timedelta(days=PUBLICATION_LAG_DAYS)
    m.index.name = "date"
    return m


def horizon_weights(year: int, month: int, ahead: int) -> dict[int, float]:
    return {year + ahead: (12 - month) / 12, year + ahead + 1: month / 12}


def combine(row: pd.Series, weights: dict[int, float]) -> float:
    vals = [row.get(y, np.nan) for y in weights]
    if any(pd.isna(v) for v in vals):
        return np.nan
    return float(sum(w * v for w, v in zip(weights.values(), vals)))


def daily_fixed_horizon(m: pd.DataFrame, prefix: str) -> pd.DataFrame:
    out = pd.DataFrame(index=m.index)
    for h, ahead in HORIZONS.items():
        out[f"{prefix}_{h}"] = [
            combine(m.loc[d], horizon_weights(d.year, d.month, ahead)) for d in m.index
        ]
    return out


def monthly_variables(m: pd.DataFrame, daily: pd.DataFrame, prefix: str,
                      months: pd.DatetimeIndex) -> pd.DataFrame:
    """Lagged levels, lagged and contemporaneous fixed-event revisions."""
    period = m.index.to_period("M")
    eom_event = m.groupby(period).last()          # last survey in each month, per reference year
    eom_fh = daily.groupby(daily.index.to_period("M")).last()
    avg_fh = daily.groupby(daily.index.to_period("M")).mean()

    res = pd.DataFrame(index=months)
    for h, ahead in HORIZONS.items():
        col = f"{prefix}_{h}"
        rev = {}
        for p in eom_event.index:
            prev = p - 1
            if prev not in eom_event.index:
                continue
            w = horizon_weights(p.year, p.month, ahead)
            diff = eom_event.loc[p] - eom_event.loc[prev]
            rev[p] = combine(diff, w)
        rev = pd.Series(rev, dtype=float)

        per = months.to_period("M")
        lag1 = per - 1
        res[f"{col}_eom_lag1"] = eom_fh[col].reindex(lag1).to_numpy()
        res[f"{col}_avg_lag1"] = avg_fh[col].reindex(lag1).to_numpy()
        res[f"{col}_rev_lag1"] = rev.reindex(lag1).to_numpy()
        res[f"{col}_rev_curr"] = rev.reindex(per).to_numpy()
    res.index.name = "month"
    return res


# ----------------------------------------------------------------------------
# diagnostics
# ----------------------------------------------------------------------------
def validate_against_zenodo(daily: pd.DataFrame) -> pd.DataFrame:
    """Compare our monthly mean 12m/36m series with the paper's monthly files."""
    rows = []
    pairs = {"focus_dlsp_12m": "focus_dlsp", "focus_dlsp_36m": "focus_dlsp3",
             "focus_primary_12m": "focus_primary", "focus_primary_36m": "focus_primary3"}
    ours = daily.groupby(daily.index.to_period("M")).mean()
    for col, zname in pairs.items():
        f = ZENODO_RAW_DIR / f"{zname}.csv"
        if not f.exists() or col not in ours:
            continue
        z = pd.read_csv(f, index_col=0).iloc[:, 0]
        z.index = pd.PeriodIndex(z.index, freq="M")
        both = pd.concat([ours[col], z], axis=1, keys=["ours", "zenodo"]).dropna()
        if PUBLICATION_LAG_DAYS:
            note = "publication lag shifts survey dates; small differences expected"
        else:
            note = "same method; differences reflect data vintage only"
        rows.append({
            "variable": col, "zenodo_file": rel(f), "n_common_months": len(both),
            "max_abs_diff": float((both["ours"] - both["zenodo"]).abs().max()) if len(both) else np.nan,
            "correlation": float(both.corr().iloc[0, 1]) if len(both) > 2 else np.nan,
            "note": note,
        })
    return pd.DataFrame(rows)


def coverage_table(monthly: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for c in monthly.columns:
        s = monthly[c].dropna()
        rows.append({
            "variable": c,
            "role": "purge_contemporaneous" if c.endswith("_rev_curr") else "predetermined_control",
            "first_month": s.index.min().strftime("%Y-%m") if len(s) else None,
            "last_month": s.index.max().strftime("%Y-%m") if len(s) else None,
            "n_obs": int(s.size), "n_missing": int(monthly[c].isna().sum()),
            "mean": float(s.mean()) if len(s) else np.nan,
            "std": float(s.std()) if len(s) > 1 else np.nan,
        })
    return pd.DataFrame(rows)


def build_event_dummies(months: pd.DatetimeIndex) -> pd.DataFrame:
    per = months.to_period("M")
    out = pd.DataFrame(index=months)
    for name, spec in EVENT_DUMMIES.items():
        ev = pd.PeriodIndex(spec["months"], freq="M")
        out[name] = per.isin(ev).astype(int)
        out[f"{name}_lag1"] = (per - 1).isin(ev).astype(int)
    out.index.name = "month"
    return out


def outlier_table(monthly: pd.DataFrame, dummies: pd.DataFrame) -> pd.DataFrame:
    """Revision months with |z| > OUTLIER_Z and whether an event dummy covers them."""
    rows = []
    for c in [c for c in monthly.columns if c.endswith(("_rev_curr", "_rev_lag1"))]:
        s = monthly[c].dropna()
        z = (s - s.mean()) / s.std()
        suffix = "_lag1" if c.endswith("_rev_lag1") else ""
        cols = [n + suffix for n in EVENT_DUMMIES]
        for month in z[z.abs() > OUTLIER_Z].index:
            covered = [n for n in cols if dummies.loc[month, n] == 1]
            rows.append({
                "variable": c, "month": month.strftime("%Y-%m"), "revision": round(float(s[month]), 3),
                "z": round(float(z[month]), 2), "covered_by_dummy": ";".join(covered) or "",
            })
    return pd.DataFrame(rows, columns=["variable", "month", "revision", "z", "covered_by_dummy"])


def plot_outputs(monthly: pd.DataFrame) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), sharex=True)
    for j, prefix in enumerate(MAIN_PREFIXES):
        label = "Exp. net debt (% GDP)" if prefix == "focus_dlsp" else "Exp. primary balance (% GDP)"
        ax = axes[0, j]
        for h in HORIZONS:
            ax.plot(monthly.index, monthly[f"{prefix}_{h}_eom_lag1"], label=f"{h} ahead")
        ax.set_title(f"{label}, end of t-1")
        ax.legend(frameon=False)
        ax = axes[1, j]
        ax.bar(monthly.index, monthly[f"{prefix}_12m_rev_curr"], width=25)
        ax.axhline(0, color="black", lw=0.6)
        ax.set_title(f"{label}: 12m revision during t (purge)")
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(FIGURES_DIR / f"focus_fiscal_expectations.{ext}", dpi=150)
    plt.close(fig)


def compare_base_calculo(monthly: pd.DataFrame) -> pd.DataFrame:
    """baseCalculo 0 vs 1 on the common months: levels, revisions, smoothing."""
    rows = []
    for var in ("focus_primary", "focus_dlsp"):
        for h in HORIZONS:
            r0, r1 = monthly[f"{var}_{h}_rev_curr"], monthly[f"{var}_bc1_{h}_rev_curr"]
            l0, l1 = monthly[f"{var}_{h}_eom_lag1"], monthly[f"{var}_bc1_{h}_eom_lag1"]
            j = pd.concat([r0, r1], axis=1, keys=["bc0", "bc1"]).dropna()
            lv = pd.concat([l0, l1], axis=1).dropna()
            rows.append({
                "variable": f"{var}_{h}", "n_common_months": len(j),
                "first_month": j.index.min().strftime("%Y-%m"), "last_month": j.index.max().strftime("%Y-%m"),
                "corr_levels_eom": float(lv.corr().iloc[0, 1]),
                "mean_abs_level_gap": float((lv.iloc[:, 0] - lv.iloc[:, 1]).abs().mean()),
                "corr_rev_same_month": float(j.corr().iloc[0, 1]),
                "corr_bc0_t_bc1_tminus1": float(j["bc0"].corr(j["bc1"].shift(1))),
                "corr_bc0_t_bc1_tplus1": float(j["bc0"].corr(j["bc1"].shift(-1))),
                "sd_rev_bc0": float(j["bc0"].std()), "sd_rev_bc1": float(j["bc1"].std()),
                "ar1_rev_bc0": float(j["bc0"].autocorr(1)), "ar1_rev_bc1": float(j["bc1"].autocorr(1)),
                "share_zero_bc0": float((j["bc0"] == 0).mean()), "share_zero_bc1": float((j["bc1"] == 0).mean()),
            })
    return pd.DataFrame(rows)


def plot_base_calculo(monthly: pd.DataFrame) -> None:
    d = monthly.loc["2021-01-01":]
    fig, axes = plt.subplots(2, 2, figsize=(11, 6.5), sharex=True)
    for i, var in enumerate(("focus_primary", "focus_dlsp")):
        for k, h in enumerate(HORIZONS):
            ax = axes[i, k]
            ax.plot(d.index, d[f"{var}_{h}_rev_curr"], lw=1.0, color="0.5", label="baseCalculo 0 (30 dias)")
            ax.plot(d.index, d[f"{var}_bc1_{h}_rev_curr"], lw=1.0, color="C0", label="baseCalculo 1 (4 dias úteis)")
            ax.axhline(0, color="k", lw=0.5)
            ax.set_title(f"{var} {h}: revisão no mês t (p.p. do PIB)")
            ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "focus_basecalculo_comparison.png", dpi=150)
    plt.close(fig)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main() -> None:
    offline = "--offline" in sys.argv
    fetch_only: set[str] = set()
    if "--fetch" in sys.argv:
        fetch_only = set(sys.argv[sys.argv.index("--fetch") + 1].split(","))
        unknown = fetch_only - set(INDICATORS)
        if unknown:
            raise SystemExit(f"--fetch: unknown prefixes {sorted(unknown)}")
    ensure_directories()

    panel_path = find_input_panel()
    panel = pd.read_csv(panel_path)
    panel["month"] = pd.to_datetime(panel["month"])
    months = pd.DatetimeIndex(panel["month"])
    print(f"Input panel: {rel(panel_path)} ({len(panel)} rows)")

    audit: list[dict] = []
    daily_parts, monthly_parts = [], []
    for prefix in INDICATORS:
        local_only = offline or (bool(fetch_only) and prefix not in fetch_only)
        raw = load_indicator(prefix, local_only, audit)
        m = fixed_event_matrix(raw)
        daily = daily_fixed_horizon(m, prefix)
        daily_parts.append(daily)
        monthly_parts.append(monthly_variables(m, daily, prefix, months))

    daily_all = pd.concat(daily_parts, axis=1).sort_index()
    expectations = pd.concat(monthly_parts, axis=1)
    dummies = build_event_dummies(months)
    monthly_all = pd.concat([expectations, dummies], axis=1)

    daily_all.to_csv(INTERMEDIATE_DIR / "focus_fiscal_expectations_daily.csv")
    monthly_out = monthly_all.copy()
    monthly_out.index = monthly_out.index.strftime("%Y-%m-%d")
    monthly_out.to_csv(INTERMEDIATE_DIR / "focus_fiscal_expectations_monthly.csv")

    # merge: keep every panel row, refuse to overwrite existing columns
    clash = [c for c in monthly_all.columns if c in panel.columns]
    if clash:
        raise ValueError(f"Columns already in input panel: {clash}")
    merged = panel.merge(monthly_all.reset_index(), on="month", how="left", validate="1:1")
    assert len(merged) == len(panel)
    merged["month"] = merged["month"].dt.strftime("%Y-%m-%d")
    merged.to_csv(OUTPUT_PANEL, index=False)

    pd.DataFrame(audit).to_csv(DIAGNOSTICS_DIR / "focus_fiscal_expectations_audit.csv", index=False)
    cov = coverage_table(expectations)
    cov.to_csv(DIAGNOSTICS_DIR / "focus_fiscal_expectations_diagnostics.csv", index=False)
    val = validate_against_zenodo(daily_all)
    val.to_csv(DIAGNOSTICS_DIR / "focus_fiscal_expectations_validation_zenodo.csv", index=False)
    outliers = outlier_table(expectations, dummies)
    outliers.to_csv(DIAGNOSTICS_DIR / "focus_fiscal_expectations_outliers.csv", index=False)
    pd.DataFrame([
        {"dummy": n, "months": ";".join(s["months"]), "reason": s["reason"]}
        for n, s in EVENT_DUMMIES.items()
    ]).to_csv(DIAGNOSTICS_DIR / "focus_fiscal_expectations_event_dummies.csv", index=False)

    allcols = expectations.columns
    cols = [c for c in allcols if "_bc1_" not in c]
    bc1 = [c for c in allcols if "_bc1_" in c]
    lists = {
        "predetermined_controls_main": [c for c in cols if c.endswith("_eom_lag1")],
        "predetermined_controls_alt_avg": [c for c in cols if c.endswith("_avg_lag1")],
        "predetermined_revisions": [c for c in cols if c.endswith("_rev_lag1")],
        "purge_contemporaneous_do_not_use_as_controls": [c for c in cols if c.endswith("_rev_curr")],
        "event_dummies_with_rev_curr": list(EVENT_DUMMIES),
        "event_dummies_with_rev_lag1": [f"{n}_lag1" for n in EVENT_DUMMIES],
        "basecalculo1_predetermined_robustness_2021plus": [c for c in bc1 if not c.endswith("_rev_curr")],
        "basecalculo1_purge_contemporaneous_2021plus": [c for c in bc1 if c.endswith("_rev_curr")],
        "notes": [
            "Main lists use baseCalculo = 0 (30-day window medians), available from 2000.",
            "*_bc1_* use baseCalculo = 1 (answers from the last 4 business days), available only from "
            "2021-03-31 (first revision 2021-04) with fewer respondents: robustness only.",
        ],
    }
    (DIAGNOSTICS_DIR / "fiscal_expectations_control_lists.json").write_text(
        json.dumps(lists, indent=2, ensure_ascii=False), encoding="utf-8")

    comp = compare_base_calculo(expectations)
    comp.to_csv(DIAGNOSTICS_DIR / "focus_basecalculo_comparison.csv", index=False)
    plot_outputs(expectations)
    plot_base_calculo(expectations)
    if not outliers.empty:
        print(f"\nRevision outliers (|z| > {OUTLIER_Z}):")
        print(outliers.to_string(index=False))

    print(f"\nWrote {rel(OUTPUT_PANEL)} ({len(merged)} rows, +{monthly_all.shape[1]} columns)")
    print(cov[["variable", "first_month", "last_month", "n_obs"]].to_string(index=False))
    if not val.empty:
        print("\nValidation against Zenodo monthly files:")
        print(val[["variable", "n_common_months", "max_abs_diff", "correlation"]].to_string(index=False))
    print("\nbaseCalculo 0 vs 1 (common months):")
    print(comp.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
