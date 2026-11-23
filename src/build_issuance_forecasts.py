#!/usr/bin/env python3
"""Issuance forecasting equations and issuance innovations u_t^j (eq. 19 of the
methodological note ``ftpl_issuance_shocks_empirical_strategy_with_maturities.pdf``).

For each debt class j in {N, F, R}:

    g_t^j = a^j + d0^j m^j_{t|t-1} + d1^j m^j_{t+1|t-1} + L^j' Z_{t-1} + mu^j_{m(t)} + u_t^j

- g_t^j: gross market issuance in t over lagged 12-month GDP (``g_{j}_pib``).
- m^j_{t|t-1}: debt service (principal + coupons) due in t, known at the end of t-1
  (``maturity_{j}_sched_pib_lag1``, from build_maturity_paf_hist.py).
- m^j_{t+1|t-1}: debt service due in t+1 computed HERE from the RMD security stock at
  the end of t-1 (principal = value at t-1 of securities maturing in t+1; coupons with
  the VNA from the IPCA/IGP-M index of t-2, the latest published at the end of t-1).
  For t <= 2010-01 (no security-level stock at t-1) it is proxied by the schedule due
  in t+1 (flag ``maturity_lead1_source``).
- Z_{t-1}: issuance lags (all classes, 1-3), own stock and share, 12m refinancing
  window, debt operations, macro (SELIC, IPCA, IBC-Br, FX), nominal and real curve
  level/slope/curvature, EMBI and realized volatility of the 5y PRE rate, Focus
  fiscal expectations, own PAF gap and the PAF 12m-maturity gap. All are known before
  the auctions of month t; calendar-month dummies complete the equation.

The three equations are estimated by OLS on the SAME sample (needed for the joint
local projections); HAC (Newey-West) standard errors are reported. The residual is the
issuance innovation; it is NOT yet a fiscal shock (survey purge is the next stage).

Specifications: ``base`` (main), ``long`` (no curve, 2006-11..2026-06), ``w12`` (12m
class windows instead of m_t, m_{t+1}; from 2003), ``pca`` (curve PCA), ``principal``
(principal-only maturities), ``nolead`` (without m_{t+1}), ``stock`` (issuance and
maturities over the lagged class stock), ``liq`` (+ liquidity reserve, 2015+), ``ramp``
(R block = NTN-B + NTN-C, R equation only) and ``base_rt`` (pseudo-real-time: forecast
errors from expanding-window estimates through t-1).

Run from the project root:  python3 src/build_issuance_forecasts.py [--offline]
(``--offline`` is passed to the IGP-M loader; the saved SGS 189 pull is then reused).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_maturity_paf_hist as mp  # noqa: E402  (constants, IGP-M loader, coupon rules)

plt = mp.plt
PROJECT_ROOT = mp.PROJECT_ROOT
DATA_DIR = mp.DATA_DIR
CLEAN_DIR = DATA_DIR / "clean"
DIAGNOSTICS_DIR = DATA_DIR / "diagnostics"
FIGURES_DIR = DATA_DIR / "figures"
INTERMEDIATE_DIR = DATA_DIR / "intermediate" / "issuance_forecasts"
INPUT_PANEL = CLEAN_DIR / "ftpl_monthly_panel_with_breakeven_outcomes.csv"
OUTPUT_PANEL = CLEAN_DIR / "ftpl_monthly_panel_with_issuance_innovations.csv"
SEC_STOCK = DATA_DIR / "intermediate" / "maturity_paf" / "rmd_security_stock_monthly.csv"
DAILY_CURVE = DATA_DIR / "intermediate" / "anbima" / "anbima_yield_curve_features_daily.csv"
CLASSES = ["N", "F", "R"]
FIRST_SEC_LEAD = pd.Timestamp("2010-02-01")  # first t with security stock at t-1
RT_MIN_FACTOR = 2  # pseudo-real-time: start when training obs >= 2 * regressors
rel = mp.rel


# ---------------------------------------------------------------- lead schedule
def lead_schedule(sec: pd.DataFrame, ipca_idx: pd.Series, igpm_idx: pd.Series) -> pd.DataFrame:
    """Debt service due in t+1 from the stock at the end of t-1 (R$), indexed by t."""
    s = sec.copy()
    s["t"] = s["month"] + pd.offsets.MonthBegin(1)
    s["due_month"] = s["month"] + pd.offsets.MonthBegin(2)
    s["mat_month"] = s["maturity"].dt.to_period("M").dt.to_timestamp()
    s = s[s["mat_month"] >= s["due_month"]]
    s["principal"] = np.where(s["mat_month"].eq(s["due_month"]), s["value"], 0.0)
    idx_month = s["due_month"] - pd.DateOffset(months=3)  # = t-2, published by end of t-1
    vna_b = 1000 * ipca_idx.reindex(idx_month).values / ipca_idx.loc[mp.VNA_BASE]
    vna_c = 1000 * igpm_idx.reindex(idx_month).values / igpm_idx.loc[mp.VNA_BASE]
    pays = np.array([d.month in mp.coupon_months(m) for d, m in zip(s["due_month"], s["maturity"])])
    per_bond = np.zeros(len(s))
    is_f, is_b, is_c = (s["title"].eq(x).values for x in ("NTN-F", "NTN-B", "NTN-C"))
    jan_jul = s["due_month"].dt.month.isin([1, 7]).values
    per_bond[is_f & jan_jul] = mp.NTNF_COUPON
    per_bond[is_b & pays] = vna_b[is_b & pays] * mp.NTNB_RATE
    c_rate = np.where(s["maturity"].dt.year.eq(2031), 1.12 ** 0.5 - 1, 1.06 ** 0.5 - 1)
    per_bond[is_c & pays] = vna_c[is_c & pays] * c_rate[is_c & pays]
    s["coupon"] = s["qty"].values * per_bond
    if s["coupon"].isna().any():
        raise ValueError("Missing VNA for lead coupon computation")
    months = pd.DatetimeIndex(sorted(s["t"].unique()), name="month")
    out = pd.DataFrame(index=months)
    for kind in ("principal", "coupon"):
        pv = s.pivot_table(index="t", columns="group", values=kind, aggfunc="sum")
        for g in mp.GROUPS:
            out[f"{kind}_{g}"] = pv.get(g, pd.Series(dtype=float)).reindex(months).fillna(0.0)
    for g in mp.GROUPS:
        out[f"total_{g}"] = out[f"principal_{g}"] + out[f"coupon_{g}"]
    return out


# ---------------------------------------------------------------- OLS + HAC
def nw_lags(n: int) -> int:
    return int(np.floor(4 * (n / 100) ** (2 / 9)))


def ols_hac(y: np.ndarray, X: np.ndarray, lags: int) -> dict:
    n, k = X.shape
    xtx_inv = np.linalg.pinv(X.T @ X)
    b = xtx_inv @ X.T @ y
    u = y - X @ b
    xu = X * u[:, None]
    S = xu.T @ xu
    for L in range(1, lags + 1):
        w = 1 - L / (lags + 1)
        G = xu[L:].T @ xu[:-L]
        S += w * (G + G.T)
    V = xtx_inv @ S @ xtx_inv * n / (n - k)
    r2 = 1 - (u @ u) / ((y - y.mean()) @ (y - y.mean()))
    return {"b": b, "V": V, "u": u, "fitted": X @ b, "r2": r2,
            "adj_r2": 1 - (1 - r2) * (n - 1) / (n - k), "n": n, "k": k,
            "rank": int(np.linalg.matrix_rank(X))}


def ljung_box(u: np.ndarray, lags: int = 12) -> tuple[float, float]:
    u = u - u.mean()
    n = len(u)
    acf = np.array([(u[L:] @ u[:-L]) / (u @ u) for L in range(1, lags + 1)])
    q = n * (n + 2) * np.sum(acf ** 2 / (n - np.arange(1, lags + 1)))
    return float(q), float(1 - stats.chi2.cdf(q, lags))


def wald(res: dict, names: list[str], subset: list[str]) -> tuple[float, int, float]:
    idx = [names.index(s) for s in subset if s in names]
    if not idx:
        return np.nan, 0, np.nan
    b = res["b"][idx]
    V = res["V"][np.ix_(idx, idx)]
    w = float(b @ np.linalg.pinv(V) @ b)
    return w, len(idx), float(1 - stats.chi2.cdf(w, len(idx)))


# ---------------------------------------------------------------- data prep
def add_derived(p: pd.DataFrame, lead: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Derived predetermined regressors. Returns (new columns, lead diagnostics)."""
    new = pd.DataFrame(index=p.index)
    pib = p["pib_12m_lag1_brl"]

    # m_{t+1|t-1}: security-level from t = 2010-02, proxy before
    for g in ["N", "F", "R", "C"]:
        for kind, sched in (("total", f"maturity_{g}_sched_brl"),
                            ("principal", f"maturity_{g}_sched_principal_brl")):
            proxy = p[sched].shift(-1)
            sec = lead[f"{kind}_{g}"].reindex(p.index)
            v = sec.where(p.index >= FIRST_SEC_LEAD, proxy)
            v = v.where(p.index >= p[sched].first_valid_index())
            name = "brl" if kind == "total" else "principal_brl"
            new[f"maturity_lead1_{g}_sched_{name}"] = v
    new["maturity_lead1_Ramp_sched_brl"] = new["maturity_lead1_R_sched_brl"] + new["maturity_lead1_C_sched_brl"]
    new["maturity_lead1_Ramp_sched_principal_brl"] = (new["maturity_lead1_R_sched_principal_brl"]
                                                      + new["maturity_lead1_C_sched_principal_brl"])
    src = pd.Series(np.where(p.index >= FIRST_SEC_LEAD, "rmd_2.2_stock_t-1", "proxy_schedule_t+1"),
                    index=p.index)
    new["maturity_lead1_source"] = src.where(new["maturity_lead1_N_sched_brl"].notna())

    for g in ["N", "F", "R", "Ramp"]:
        new[f"maturity_lead1_{g}_sched_pib_lag1"] = new[f"maturity_lead1_{g}_sched_brl"] / pib
        new[f"maturity_lead1_{g}_sched_principal_pib_lag1"] = new[f"maturity_lead1_{g}_sched_principal_brl"] / pib
        # current-month principal-only and stock-normalized maturities
        prin_t = (p[f"maturity_{g}_sched_principal_brl"] if g != "Ramp"
                  else p["maturity_R_sched_principal_brl"] + p["maturity_C_sched_principal_brl"])
        new[f"maturity_{g}_sched_principal_pib_lag1"] = prin_t / pib
        stock = p[f"stock_{g}_hist_brl_lag1"]
        new[f"maturity_{g}_sched_over_lag_stock"] = p[f"maturity_{g}_sched_brl"] / stock
        new[f"maturity_lead1_{g}_sched_over_lag_stock"] = new[f"maturity_lead1_{g}_sched_brl"] / stock
    for g, w in (("N", "N"), ("F", "F"), ("R", "Ramp"), ("Ramp", "Ramp")):
        new[f"maturity12m_{g}_rmd_pib_lag1"] = p[f"maturity12m_{w}_rmd_brl_lag1"] / pib

    # issuance lags for Ramp and for the stock normalization
    for j in ["Ramp"]:
        for L in (1, 2, 3):
            new[f"g_{j}_pib_lag{L}"] = p["gross_Ramp_brl_over_pib_lag1"].shift(L)
    for j in ["N", "F", "R", "Ramp"]:
        for L in (1, 2, 3):
            new[f"gross_{j}_over_lag_stock_hist_lag{L}"] = p[f"gross_{j}_over_lag_stock_hist"].shift(L)

    # macro (publication-aware): SELIC target and FX known at end of t-1; IPCA of t-1
    # released ~day 10 of t (before most auctions); IBC-Br released ~45 days later -> lag 2
    new["selic_target_pa_lag1"] = p["selic_target_pa"].shift(1)
    new["ipca_yoy_pct_lag1"] = p["ipca_yoy_pct"].shift(1)
    new["brl_usd_mom_pct_lag1"] = p["brl_usd_mom_pct"].shift(1)
    new["ibc_br_yoy_pct_lag2"] = (np.log(p["ibc_br_sa"]).diff(12) * 100).shift(2)

    # realized volatility of the 5y PRE rate in t-1 (sd of daily changes, bp)
    d = pd.read_csv(DAILY_CURVE, usecols=["date", "pre_5y"], parse_dates=["date"]).set_index("date").sort_index()
    dd = d["pre_5y"].diff() * 100
    rv = dd.groupby(dd.index.to_period("M").to_timestamp()).std()
    new["pre_5y_rvol_bp_lag1"] = rv.reindex(p.index - pd.offsets.MonthBegin(1)).values

    for m in range(2, 13):
        new[f"month_{m:02d}"] = (p["calendar_month"] == m).astype(float)

    # lead diagnostics: security-level lead in t vs schedule due in t+1 (stock at t)
    rows = []
    for g in ["N", "F", "R", "C"]:
        a = lead[f"total_{g}"].reindex(p.index)
        b = p[f"maturity_{g}_sched_brl"].shift(-1)
        j = pd.concat([a, b], axis=1).loc[FIRST_SEC_LEAD:].dropna()
        ap = lead[f"principal_{g}"].reindex(p.index)
        bp = p[f"maturity_{g}_sched_principal_brl"].shift(-1)
        jp = pd.concat([ap, bp], axis=1).loc[FIRST_SEC_LEAD:].dropna()
        jp = jp[jp.iloc[:, 1] > 0]
        rows.append({"class": g, "n": len(j), "corr_total": j.corr().iloc[0, 1],
                     "mean_abs_gap_over_mean": (j.iloc[:, 0] - j.iloc[:, 1]).abs().mean() / j.iloc[:, 1].mean(),
                     "principal_ratio_median": float((jp.iloc[:, 0] / jp.iloc[:, 1]).median()),
                     "principal_ratio_min": float((jp.iloc[:, 0] / jp.iloc[:, 1]).min()),
                     "principal_ratio_max": float((jp.iloc[:, 0] / jp.iloc[:, 1]).max())})
    return new, pd.DataFrame(rows)


def regressors(spec: str, j: str) -> tuple[str, list[str], dict[str, list[str]]]:
    """Dependent variable, regressor list and named blocks for Wald tests."""
    jj = "Ramp" if spec == "ramp" else j
    issue_lags = [f"g_{c}_pib_lag{L}" for c in CLASSES for L in (1, 2, 3)]
    if spec == "ramp":
        issue_lags = [f"g_{c}_pib_lag{L}" for c in ("N", "F", "Ramp") for L in (1, 2, 3)]
    dep = f"g_{j}_pib" if spec != "ramp" else "gross_Ramp_brl_over_pib_lag1"
    mat = [f"maturity_{jj}_sched_pib_lag1", f"maturity_lead1_{jj}_sched_pib_lag1"]
    if spec == "principal":
        mat = [f"maturity_{jj}_sched_principal_pib_lag1", f"maturity_lead1_{jj}_sched_principal_pib_lag1"]
    elif spec == "nolead":
        mat = mat[:1]
    elif spec == "w12":
        mat = [f"maturity12m_{jj}_rmd_pib_lag1"]
    elif spec == "stock":
        dep = f"gross_{j}_over_lag_stock_hist"
        mat = [f"maturity_{j}_sched_over_lag_stock", f"maturity_lead1_{j}_sched_over_lag_stock"]
        issue_lags = [f"gross_{c}_over_lag_stock_hist_lag{L}" for c in CLASSES for L in (1, 2, 3)]
    exposure = [f"stock_{jj}_hist_pib_lag1", f"share_{jj}_hist_lag1"]
    refin = ["maturity12m_total_rmd_pib_lag1"]
    ops = ["exchange_value_pib_lag1", "buyback_value_pib_lag1",
           "extra_sale_value_pib_lag1", "extra_purchase_value_pib_lag1"]
    macro = ["selic_target_pa_lag1", "ipca_yoy_pct_lag1", "ibc_br_yoy_pct_lag2", "brl_usd_mom_pct_lag1"]
    curve = ["pre_level_5y_eom_lag1", "pre_slope_5y_1y_eom_lag1", "pre_curvature_1y_5y_10y_eom_lag1",
             "ipca_level_5y_eom_lag1", "ipca_slope_5y_1y_eom_lag1", "ipca_curvature_1y_5y_10y_eom_lag1"]
    if spec == "pca":
        curve = [f"{c}_pc{k}_eom_lag1" for c in ("pre", "ipca") for k in (1, 2, 3)]
    risk = ["embi_spread_bp_avg_lag1", "pre_5y_rvol_bp_lag1"]
    if spec in ("long", "w12"):
        curve, risk = [], ["embi_spread_bp_avg_lag1"]
    fiscal = ["focus_primary_12m_eom_lag1", "focus_dlsp_12m_eom_lag1"]
    paf = [f"paf_gap_{j}_rmd_lag1", "paf_gap_maturing_12m_rmd_lag1"]
    extra = ["liquidity_reserve_pib_lag1", "liquidity_reserve_over_maturity12m_rmd_lag1"] if spec == "liq" else []
    months = [f"month_{m:02d}" for m in range(2, 13)]
    blocks = {"maturities": mat, "issuance_lags": issue_lags, "exposure": exposure, "refinancing_12m": refin,
              "debt_operations": ops, "macro": macro, "curve": curve, "risk": risk, "fiscal_expectations": fiscal,
              "paf": paf, "liquidity": extra, "calendar_month": months}
    xs = [c for b in blocks.values() for c in b]
    return dep, xs, blocks


SPECS = ["base", "long", "w12", "pca", "principal", "nolead", "stock", "liq", "ramp"]


def is_predetermined(name: str) -> bool:
    return (name.endswith(("_lag1", "_lag2", "_lag3")) or name.startswith("month_")
            or name.endswith("_over_lag_stock"))


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true", help="reuse the newest saved SGS 189 pull")
    args = ap.parse_args()
    for d in (CLEAN_DIR, DIAGNOSTICS_DIR, FIGURES_DIR, INTERMEDIATE_DIR):
        d.mkdir(parents=True, exist_ok=True)

    panel = pd.read_csv(INPUT_PANEL)
    panel["month"] = pd.to_datetime(panel["month"])
    print(f"Input panel: {rel(INPUT_PANEL)} {panel.shape}")
    p = panel.set_index("month")

    audit: list[dict] = []
    sec = pd.read_csv(SEC_STOCK, parse_dates=["month", "maturity"])
    audit.append({"item": "RMD 2.2 security stock (build_maturity_paf_hist output)", "file": rel(SEC_STOCK),
                  "sha256": mp.sha256(SEC_STOCK), "first": str(sec.month.min().date()),
                  "last": str(sec.month.max().date())})
    audit.append({"item": "ANBIMA ETTJ daily curves (Etapa B output)", "file": rel(DAILY_CURVE),
                  "sha256": mp.sha256(DAILY_CURVE), "first": "", "last": ""})
    ipca_idx = p["ipca_index"].dropna()
    igpm_idx = mp.index_from_changes(mp.load_igpm(True if args.offline else False, audit))
    igpm_idx.index = igpm_idx.index.to_period("M").to_timestamp()
    lead = lead_schedule(sec, ipca_idx, igpm_idx)
    lead.index.name = "month"
    new, lead_diag = add_derived(p, lead)
    clash = [c for c in new.columns if c in p.columns]
    if clash:
        raise ValueError(f"Derived columns already in panel: {clash}")
    d = pd.concat([p, new], axis=1)

    checks: list[dict] = []

    def check(name, value, ok, note=""):
        checks.append({"check": name, "value": value, "status": "PASS" if ok else "FAIL", "note": note})

    for _, r in lead_diag.iterrows():
        check(f"lead schedule {r['class']} vs schedule due t+1 (stock t): corr", float(r["corr_total"]),
              r["class"] == "C" or r["corr_total"] > 0.98,
              f"n={r['n']}, mean|gap|/mean={r['mean_abs_gap_over_mean']:.4f}")

    coef_rows, fit_rows, wald_rows = [], [], []
    resid = pd.DataFrame(index=d.index)
    samples = {}
    for spec in SPECS:
        eqs = ["R"] if spec == "ramp" else CLASSES
        defs = {j: regressors(spec, j) for j in eqs}
        for j, (dep, xs, _) in defs.items():
            bad = [x for x in xs if not is_predetermined(x)]
            check(f"{spec}/{j}: all regressors predetermined", len(bad), not bad, ", ".join(bad))
            missing = [x for x in xs + [dep] if x not in d.columns]
            if missing:
                raise KeyError(f"{spec}/{j}: missing columns {missing}")
        # common sample across the three equations
        allcols = sorted({c for dep, xs, _ in defs.values() for c in xs + [dep]})
        smp = d[allcols].dropna().index
        smp = smp[(smp >= "2003-01-01")]
        samples[spec] = smp
        for j, (dep, xs, blocks) in defs.items():
            Z = d.loc[smp, xs]
            keep = [c for c in xs if Z[c].std() > 0]
            dropped = [c for c in xs if c not in keep]
            X = np.column_stack([np.ones(len(smp)), Z[keep].values])
            names = ["const"] + keep
            y = d.loc[smp, dep].values
            res = ols_hac(y, X, nw_lags(len(smp)))
            lab = "Ramp" if spec == "ramp" else j
            check(f"{spec}/{lab}: full column rank", res["rank"], res["rank"] == X.shape[1],
                  f"dropped zero-variance: {dropped}" if dropped else "")
            check(f"{spec}/{lab}: X'u = 0", float(np.abs(X.T @ res["u"]).max()),
                  np.abs(X.T @ res["u"]).max() < 1e-8 * max(1, np.abs(X).max()))
            se = np.sqrt(np.diag(res["V"]))
            for nm, b, s in zip(names, res["b"], se):
                coef_rows.append({"spec": spec, "equation": lab, "variable": nm, "coef": b, "se_hac": s,
                                  "t": b / s if s > 0 else np.nan,
                                  "p": 2 * (1 - stats.norm.cdf(abs(b / s))) if s > 0 else np.nan})
            q, qp = ljung_box(res["u"])
            fit_rows.append({"spec": spec, "equation": lab, "dependent": dep, "n": res["n"], "k": res["k"],
                             "first": smp.min().strftime("%Y-%m"), "last": smp.max().strftime("%Y-%m"),
                             "r2": res["r2"], "adj_r2": res["adj_r2"], "sd_dep": y.std(ddof=1),
                             "sd_resid": res["u"].std(ddof=res["k"]), "nw_lags": nw_lags(len(smp)),
                             "ljung_box_q12": q, "ljung_box_p": qp, "dropped": ";".join(dropped)})
            for bname, bvars in blocks.items():
                w, df_, pw = wald(res, names, bvars)
                if df_:
                    wald_rows.append({"spec": spec, "equation": lab, "block": bname, "wald": w,
                                      "df": df_, "p": pw})
            resid.loc[smp, f"u_{lab}_{spec}"] = res["u"]
            resid.loc[smp, f"ghat_{lab}_{spec}"] = res["fitted"]

            # pseudo-real-time forecast errors for the baseline
            if spec == "base":
                k = X.shape[1]
                rt = pd.Series(np.nan, index=smp)
                for i in range(RT_MIN_FACTOR * k, len(smp)):
                    Xi, yi = X[:i], y[:i]
                    bi = np.linalg.lstsq(Xi, yi, rcond=None)[0]
                    rt.iloc[i] = y[i] - X[i] @ bi
                resid.loc[smp, f"u_{j}_base_rt"] = rt.values

    checks_df = pd.DataFrame(checks)
    checks_df.to_csv(DIAGNOSTICS_DIR / "issuance_forecasts_validation.csv", index=False)
    if (checks_df.status == "FAIL").any():
        print(checks_df[checks_df.status == "FAIL"].to_string(index=False))
        raise SystemExit("Validation failed; nothing written to the panel.")

    coefs = pd.DataFrame(coef_rows)
    fits = pd.DataFrame(fit_rows)
    walds = pd.DataFrame(wald_rows)
    coefs.to_csv(DIAGNOSTICS_DIR / "issuance_forecasts_coefficients.csv", index=False)
    fits.to_csv(DIAGNOSTICS_DIR / "issuance_forecasts_fit.csv", index=False)
    walds.to_csv(DIAGNOSTICS_DIR / "issuance_forecasts_wald.csv", index=False)

    # residual diagnostics
    base_u = resid[[f"u_{j}_base" for j in CLASSES]].dropna()
    corr_rows = []
    for a in CLASSES:
        for b in CLASSES:
            corr_rows.append({"table": "cross_class_base", "a": f"u_{a}_base", "b": f"u_{b}_base",
                              "corr": base_u[f"u_{a}_base"].corr(base_u[f"u_{b}_base"]), "n": len(base_u)})
    for j in CLASSES:
        for spec in SPECS[1:] + ["base_rt"]:
            col = f"u_{j}_{spec}" if spec != "ramp" else ("u_Ramp_ramp" if j == "R" else None)
            if col is None:
                continue
            x = resid[[f"u_{j}_base", col]].dropna()
            corr_rows.append({"table": "base_vs_spec", "a": f"u_{j}_base", "b": col,
                              "corr": x.corr().iloc[0, 1], "n": len(x)})
        for fn in ["focus_primary_12m_rev_curr", "focus_primary_36m_rev_curr", "focus_dlsp_12m_rev_curr",
                   "prisma_primary_12m_rev_curr_pib", "prisma_primary_36m_rev_curr_pib"]:
            x = pd.concat([resid[f"u_{j}_base"], d[fn]], axis=1).dropna()
            r = x.corr().iloc[0, 1]
            corr_rows.append({"table": "base_vs_fiscal_news_preview", "a": f"u_{j}_base", "b": fn, "corr": r,
                              "n": len(x),
                              "p": 2 * (1 - stats.t.cdf(abs(r) * np.sqrt((len(x) - 2) / (1 - r ** 2)), len(x) - 2))})
    corrs = pd.DataFrame(corr_rows)
    corrs.to_csv(DIAGNOSTICS_DIR / "issuance_forecasts_residual_correlations.csv", index=False)

    # write panel: derived regressors + innovations + fitted values
    out_new = pd.concat([new, resid.copy()], axis=1).copy()
    clash = [c for c in out_new.columns if c in panel.columns]
    if clash:
        raise ValueError(f"Columns already in input panel: {clash}")
    o = out_new.reset_index()
    merged = panel.merge(o, on="month", how="left", validate="1:1")
    assert len(merged) == len(panel)
    merged["month"] = merged["month"].dt.strftime("%Y-%m-%d")
    merged.to_csv(OUTPUT_PANEL, index=False)

    lt = lead.copy()
    lt.index = lt.index.strftime("%Y-%m-%d")
    lt.to_csv(INTERMEDIATE_DIR / "maturity_lead1_schedule_monthly.csv")
    ri = resid.dropna(how="all").copy()
    ri.index = ri.index.strftime("%Y-%m-%d")
    ri.to_csv(INTERMEDIATE_DIR / "issuance_innovations_monthly.csv")
    pd.DataFrame(audit).to_csv(DIAGNOSTICS_DIR / "issuance_forecasts_audit.csv", index=False)

    lists = {
        "innovations_base": [f"u_{j}_base" for j in CLASSES],
        "innovations_robustness": sorted(c for c in resid.columns if c.startswith("u_") and not c.endswith("_base")),
        "fitted_values": sorted(c for c in resid.columns if c.startswith("ghat_")),
        "regressors_base": {j: regressors("base", j)[1] for j in CLASSES},
        "derived_predetermined_regressors": [c for c in new.columns if c != "maturity_lead1_source"],
        "samples": {s: [v.min().strftime("%Y-%m"), v.max().strftime("%Y-%m"), len(v)] for s, v in samples.items()},
        "notes": [
            "u_{j}_{spec} is the residual of the issuance equation in month t (contemporaneous): it is the "
            "issuance innovation to be purged of fiscal news, never a control.",
            "All three equations of a spec share the same sample (needed for the joint LP).",
            "Units: fraction of lagged 12-month GDP (stock spec: fraction of lagged class stock).",
            "maturity_lead1_*: debt service due in t+1 known at the end of t-1; security-level from 2010-02, "
            "proxied by the schedule due in t+1 before (maturity_lead1_source).",
            "IPCA of t-1 enters at lag 1 (released around day 10 of t); IBC-Br at lag 2 (released ~45 days later).",
            "base_rt: pseudo-real-time forecast errors, coefficients estimated through t-1, from the month in "
            "which the training sample reaches twice the number of regressors.",
            "The ramp spec replaces R by NTN-B + NTN-C (R equation only).",
        ],
    }
    (DIAGNOSTICS_DIR / "issuance_forecast_lists.json").write_text(json.dumps(lists, indent=2, ensure_ascii=False),
                                                                   encoding="utf-8")

    # figure
    fig, axes = plt.subplots(3, 2, figsize=(12, 9), sharex=True)
    smp = samples["base"]
    for i, j in enumerate(CLASSES):
        ax = axes[i, 0]
        ax.plot(smp, d.loc[smp, f"g_{j}_pib"] * 100, lw=1.0, color="0.55", label="observada")
        ax.plot(smp, resid.loc[smp, f"ghat_{j}_base"] * 100, lw=1.0, color="C0", label="prevista")
        ax.set_title(f"{j}: emissão bruta (% do PIB 12m)")
        ax.legend(fontsize=7)
        ax = axes[i, 1]
        ax.bar(smp, resid.loc[smp, f"u_{j}_base"] * 100, width=25, color="C3")
        ax.axhline(0, color="k", lw=0.5)
        ax.set_title(f"{j}: inovação u (base, % do PIB 12m)")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "issuance_forecasts.png", dpi=150)
    plt.close(fig)

    print(f"Wrote {rel(OUTPUT_PANEL)} {merged.shape} (+{out_new.shape[1]} columns)")
    print(lead_diag.to_string(index=False))
    print(fits[["spec", "equation", "n", "k", "first", "last", "r2", "adj_r2", "ljung_box_p"]].to_string(index=False))
    w = walds[walds.spec == "base"].pivot(index="block", columns="equation", values="p")
    print("Base Wald p-values by block:\n", w.round(3).to_string())
    print(corrs[corrs.table != "base_vs_spec"].round(3).to_string(index=False))
    print(corrs[corrs.table == "base_vs_spec"].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
