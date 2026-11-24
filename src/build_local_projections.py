"""Local projections of outcomes on the purged issuance shocks (eq. 30 of the note).

For outcome y and horizon h = 0..H:

    y_{t+h} - y_{t-1} = a_h + b_h^N e_t^N + b_h^F e_t^F + b_h^R e_t^R
                        + G_h' X_{t-1} + month dummies + v_{t+h},

with the three purged shocks entering jointly. Shocks are scaled so that one
unit is an issuance surprise of 0.1% of lagged 12-month GDP (eps * 1000), the
same value for every class, which is the comparison the valuation ranking
kappa^N > kappa^F > kappa^R refers to. The per-standard-deviation factor of each
shock is reported for reference.

X_{t-1} (all dated t-1 or earlier): p lags of the outcome's monthly change, of
the three shocks, of monthly IPCA inflation, of the change in the Selic target,
of IBC-Br growth and of BRL/USD depreciation; the Selic target, EMBI spread and
Focus 12m IPCA expectation at t-1; the three nominal-curve principal components
(monthly means of t-1). Controls that duplicate the outcome's own lag are
dropped.

Inference: Newey-West HAC with bandwidth max(nw(n), h + 1), increasing in the
horizon. Tests across horizon windows (joint Wald of equality, mean difference
with one-sided p-value, share of horizons with the predicted sign, sup-t
simultaneous bands for the differences) use the joint HAC covariance of the
shock coefficients across horizons, computed from stacked scores on the
window's common sample. Because X_{t-1} does not depend on h, the stacked
covariance only needs the shock rows of (X'X)^{-1} X' e_{t,h}.

Reads  data/clean/ftpl_monthly_panel_with_inflation_expectations.csv.
Writes data/diagnostics/local_projections_{irf,tests,fit,audit}.csv,
       local_projection_lists.json, figures local_projections_*.png.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


def find_project_root() -> Path:
    for candidate in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (candidate / ".git").exists():
            return candidate
    return Path(__file__).resolve().parent


PROJECT_ROOT = find_project_root()
DATA_DIR = PROJECT_ROOT / "data"
os.environ.setdefault("MPLCONFIGDIR", str(DATA_DIR / ".mplconfig"))
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

INPUT_PANEL = DATA_DIR / "clean" / "ftpl_monthly_panel_with_offer_surprises.csv"
DIAG = DATA_DIR / "diagnostics"
FIG = DATA_DIR / "figures"
INTER = DATA_DIR / "intermediate" / "local_projections"

H = 24
SCALE = 1000.0  # eps is a fraction of GDP: 0.001 = 0.1% of GDP
CLASSES = ["N", "F", "R"]
PAIRS = [("N", "R"), ("N", "F"), ("F", "R")]
WINDOWS = {"0-6": range(0, 7), "7-12": range(7, 13), "13-24": range(13, 25), "0-24": range(0, 25)}
SIM_DRAWS = 20000
SEED = 20261123

# outcome -> (source column, transform, label, unit)
OUTCOMES = {
    "p": ("ipca_index", "log100", "Nível de preços (IPCA)", "%"),
    "focus_ipca12m": ("focus_ipca12m_pct", "level", "Expectativa IPCA 12m (Focus)", "p.p."),
    "selic": ("selic_target_pa", "level", "Meta Selic", "p.p."),
    "ltn_1y": ("ltn_1y_pct", "level", "LTN 1 ano", "p.p."),
    "real_5y": ("real_yield_5y_pct", "level", "Juro real 5 anos", "p.p."),
    "real_10y": ("real_yield_10y_pct", "level", "Juro real 10 anos", "p.p."),
    "bei_2y": ("bei_2y_pct", "level", "Inflação implícita 2 anos", "p.p."),
    "bei_5y": ("bei_5y_pct", "level", "Inflação implícita 5 anos", "p.p."),
    "fx": ("brl_usd", "log100", "Câmbio BRL/USD", "%"),
    "embi": ("embi_spread_bp", "level", "EMBI Brasil", "p.b."),
    "ibc": ("ibc_br_sa", "log100", "IBC-Br", "%"),
}
MAIN_OUTCOMES = ["p", "focus_ipca12m", "selic", "real_5y", "bei_2y", "fx", "embi", "ibc"]
INFLATION_OUTCOMES = ["p", "focus_ipca12m", "bei_2y", "bei_5y"]  # predicted sign > 0

# macro block: name -> (column, transform); monthly change enters with p lags
MACRO_DIFF = {
    "infl": ("ipca_index", "log100"),
    "selic": ("selic_target_pa", "level"),
    "ibc": ("ibc_br_sa", "log100"),
    "fx": ("brl_usd", "log100"),
}
MACRO_LEVEL1 = ["selic_target_pa", "embi_spread_bp", "focus_ipca12m_pct"]  # value at t-1
CURVE = ["pre_pc1_avg_lag1", "pre_pc2_avg_lag1", "pre_pc3_avg_lag1"]  # already t-1
CONTEMP = {  # fast variables, monthly change in t (spec ordlast)
    "fx": ("brl_usd", "log100"),
    "embi": ("embi_spread_bp", "level"),
    "real5y": ("real_yield_5y_pct", "level"),
    "ltn1y": ("ltn_1y_pct", "level"),
    "focus": ("focus_ipca12m_pct", "level"),
}
EVENT_DUMMIES = ["d_focus_gdprev_2007m04"] + [f"d_focus_covid_2020m{m:02d}" for m in range(3, 8)]

# spec -> dict(shocks={class: column}, lags, extra options)
def _sh(tag: str, r: str | None = None) -> dict:
    return {"N": f"eps_N_{tag}", "F": f"eps_F_{tag}", "R": r or f"eps_R_{tag}"}


SPECS = {
    "base": {"shocks": _sh("base_fprim"), "lags": 3},
    "lags1": {"shocks": _sh("base_fprim"), "lags": 1},
    "lags6": {"shocks": _sh("base_fprim"), "lags": 6},
    "evdum": {"shocks": _sh("base_fprim"), "lags": 3, "dummies": True},
    "pre2020": {"shocks": _sh("base_fprim"), "lags": 3, "end": "2019-12-01"},
    "nopurge": {"shocks": {j: f"u_{j}_base" for j in CLASSES}, "lags": 3},
    "cfrisk": {"shocks": _sh("base_fprim_cfrisk"), "lags": 3},
    # Prisma sample (2016-03+, 9 missing months): one lag to keep k well below n
    "pprim": {"shocks": _sh("base_pprim"), "lags": 1},
    "fprim16": {"shocks": _sh("base_fprim16"), "lags": 1},
    # issuance ordered last within the month: contemporaneous changes of the
    # fast financial variables enter X (impact of those outcomes is 0 by construction)
    "ordlast": {"shocks": _sh("base_fprim"), "lags": 3, "contemp": True},
    "rt": {"shocks": _sh("base_rt_fprim"), "lags": 3},
    "ramp": {"shocks": _sh("base_fprim", "eps_Ramp_ramp_fprim"), "lags": 3},
    # Proposal 1 (sec:ident): auction-level offer surprises summed by month
    # (build_offer_surprises.py). LP-IV: eps instrumented by the three surprises;
    # rf: reduced form, surprises used directly as shocks (OLS).
    "iv_naive": {"shocks": _sh("base_fprim"), "lags": 3, "iv": "naive"},
    "iv_naive_w": {"shocks": _sh("base_fprim"), "lags": 3, "iv": "naive_w"},
    "iv_pred": {"shocks": _sh("base_fprim"), "lags": 3, "iv": "pred"},
    "iv_naive_sep": {"shocks": _sh("base_fprim"), "lags": 3, "iv": "naive_sep"},
    "rf_naive": {"shocks": {j: f"offsurp_{j}_naive" for j in CLASSES}, "lags": 3},
}
IV_SPECS = [k for k, v in SPECS.items() if "iv" in v] + ["rf_naive"]


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def nw_lags(n: int) -> int:
    return int(np.floor(4 * (n / 100) ** (2 / 9)))


def hac(z: np.ndarray, lags: int) -> np.ndarray:
    """Bartlett long-run covariance of the rows of z (n x m), mean-zero scores."""
    S = z.T @ z
    for L in range(1, lags + 1):
        G = z[L:].T @ z[:-L]
        S += (1 - L / (lags + 1)) * (G + G.T)
    return S


def transform(s: pd.Series, how: str) -> pd.Series:
    return 100 * np.log(s) if how == "log100" else s


# ---------------------------------------------------------------- design
def build_design(d: pd.DataFrame, outcome: str, spec: dict) -> tuple[pd.DataFrame, list[str], pd.Series]:
    """Return (regressor frame indexed by t, shock column names, y level series)."""
    col, how, _, _ = OUTCOMES[outcome]
    y = transform(d[col], how)
    p = spec["lags"]
    X = pd.DataFrame(index=d.index)
    shock_names = []
    for j in CLASSES:
        e = d[spec["shocks"][j]] * SCALE
        X[f"shock_{j}"] = e
        shock_names.append(f"shock_{j}")
        for L in range(1, p + 1):
            X[f"shock_{j}_l{L}"] = e.shift(L)
    dy = y.diff()
    for L in range(1, p + 1):
        X[f"dy_l{L}"] = dy.shift(L)
    for name, (c, h) in MACRO_DIFF.items():
        if c == col:  # duplicates the outcome's own lag
            continue
        dm = transform(d[c], h).diff()
        for L in range(1, p + 1):
            X[f"d{name}_l{L}"] = dm.shift(L)
    for c in MACRO_LEVEL1:
        X[f"{c}_l1"] = d[c].shift(1)
    for c in CURVE:
        X[c] = d[c]
    for m in range(2, 13):
        X[f"month_{m:02d}"] = (d.index.month == m).astype(float)
    if spec.get("contemp"):
        for name, (c, h) in CONTEMP.items():
            X[f"d{name}_t"] = transform(d[c], h).diff()
    if spec.get("dummies"):
        for c in EVENT_DUMMIES:
            X[c] = d[c].fillna(0)
    X.insert(0, "const", 1.0)
    return X, shock_names, y


def sample_mask(X: pd.DataFrame, spec: dict) -> pd.Series:
    ok = X.notna().all(axis=1)
    if "end" in spec:
        ok &= X.index <= pd.Timestamp(spec["end"])
    return ok


def drop_collinear_dummies(X: pd.DataFrame, ok: pd.Series) -> pd.DataFrame:
    """Drop regressors constant on the sample and, if some calendar month never
    occurs (Prisma has no Jan/Feb releases), one month dummy so they do not sum to
    the constant."""
    Xs = X.loc[ok]
    const = [c for c in X.columns if c != "const" and Xs[c].nunique() <= 1]
    X = X.drop(columns=const)
    months = [c for c in X.columns if c.startswith("month_")]
    if months and (Xs[months].sum(axis=1) == 1).all():
        X = X.drop(columns=months[0])
    return X


def lead_change(y: pd.Series, h: int) -> pd.Series:
    return y.shift(-h) - y.shift(1)


# ---------------------------------------------------------------- estimation
def instruments(d: pd.DataFrame, X: pd.DataFrame, shocks: list[str], spec: dict) -> pd.DataFrame | None:
    """Instrument matrix: X with each shock column replaced by its offer surprise."""
    if "iv" not in spec:
        return None
    Z = X.copy()
    for j, s in zip(CLASSES, shocks):
        Z[s] = d[f"offsurp_{j}_{spec['iv']}"] * SCALE
    return Z


def fitted_design(Xm: np.ndarray, Zm: np.ndarray | None, idx: list[int]) -> np.ndarray:
    """2SLS: replace the shock columns by their first-stage fitted values. Since the
    controls are in Z, beta = (Xf'Xf)^-1 Xf'y and the HAC scores use Xf * (y - X beta)."""
    if Zm is None:
        return Xm
    Xf = Xm.copy()
    Xf[:, idx] = Zm @ np.linalg.lstsq(Zm, Xm[:, idx], rcond=None)[0]
    return Xf


def pointwise(X: pd.DataFrame, shocks: list[str], y: pd.Series, base_ok: pd.Series,
              Z: pd.DataFrame | None = None) -> list[dict]:
    rows = []
    idx = [X.columns.get_loc(s) for s in shocks]
    for h in range(H + 1):
        yh = lead_change(y, h)
        ok = base_ok & yh.notna()
        Xm, ym = X.loc[ok].to_numpy(float), yh.loc[ok].to_numpy(float)
        Xf = fitted_design(Xm, None if Z is None else Z.loc[ok].to_numpy(float), idx)
        n, k = Xm.shape
        xtx_inv = np.linalg.pinv(Xf.T @ Xf)
        b = xtx_inv @ Xf.T @ ym
        u = ym - Xm @ b
        lags = max(nw_lags(n), h + 1)
        V = xtx_inv @ hac(Xf * u[:, None], lags) @ xtx_inv * n / (n - k)
        r2 = 1 - (u @ u) / ((ym - ym.mean()) @ (ym - ym.mean()))
        row = {"h": h, "n": n, "k": k, "rank": int(np.linalg.matrix_rank(Xm)), "nw_lags": lags,
               "r2": r2, "first_t": X.index[ok].min().strftime("%Y-%m"),
               "last_t": X.index[ok].max().strftime("%Y-%m")}
        bs, Vs = b[idx], V[np.ix_(idx, idx)]
        for a, j in enumerate(CLASSES):
            se = np.sqrt(Vs[a, a])
            row.update({f"b_{j}": bs[a], f"se_{j}": se, f"p_{j}": 2 * (1 - stats.norm.cdf(abs(bs[a] / se)))})
        for j1, j2 in PAIRS:
            a1, a2 = CLASSES.index(j1), CLASSES.index(j2)
            dlt = bs[a1] - bs[a2]
            se = np.sqrt(Vs[a1, a1] + Vs[a2, a2] - 2 * Vs[a1, a2])
            row.update({f"d_{j1}{j2}": dlt, f"se_d_{j1}{j2}": se,
                        f"p_d_{j1}{j2}": 2 * (1 - stats.norm.cdf(abs(dlt / se))),
                        f"p1_d_{j1}{j2}": 1 - stats.norm.cdf(dlt / se)})
        R =np.array([[1, -1, 0], [0, 1, -1]])
        rb = R @ bs
        w = float(rb @ np.linalg.pinv(R @ Vs @ R.T) @ rb)
        row.update({"wald_equal_NFR": w, "p_equal_NFR": 1 - stats.chi2.cdf(w, 2)})
        rows.append(row)
    return rows


def window_tests(X: pd.DataFrame, shocks: list[str], y: pd.Series, base_ok: pd.Series,
                 rng: np.random.Generator, Z: pd.DataFrame | None = None) -> list[dict]:
    rows = []
    idx = [X.columns.get_loc(s) for s in shocks]
    for wname, hs in WINDOWS.items():
        hs = list(hs)
        Y = pd.concat({h: lead_change(y, h) for h in hs}, axis=1)
        ok = base_ok & Y.notna().all(axis=1)
        Xm = X.loc[ok].to_numpy(float)
        Xf = fitted_design(Xm, None if Z is None else Z.loc[ok].to_numpy(float), idx)
        Ym = Y.loc[ok].to_numpy(float)
        n, k = Xm.shape
        xtx_inv = np.linalg.pinv(Xf.T @ Xf)
        B = xtx_inv @ Xf.T @ Ym              # k x |W|
        U = Ym - Xm @ B
        A = xtx_inv[idx] @ Xf.T              # 3 x n  (shock rows of (Xf'Xf)^-1 Xf')
        # scores for shock coefs at each horizon, stacked: n x (3|W|); V = sum z z'
        S = np.concatenate([(A * U[:, i]).T for i in range(len(hs))], axis=1)
        lags = max(nw_lags(n), max(hs) + 1)
        V = hac(S, lags) * n / (n - k)
        bvec = np.concatenate([B[idx, i] for i in range(len(hs))])
        for j1, j2 in PAIRS:
            a1, a2 = CLASSES.index(j1), CLASSES.index(j2)
            D = np.zeros((len(hs), 3 * len(hs)))
            for i in range(len(hs)):
                D[i, 3 * i + a1], D[i, 3 * i + a2] = 1, -1
            dv = D @ bvec
            Vd = D @ V @ D.T
            sd = np.sqrt(np.diag(Vd))
            w = float(dv @ np.linalg.pinv(Vd) @ dv)
            avg = np.full(len(hs), 1 / len(hs))
            m, se_m = float(avg @ dv), float(np.sqrt(avg @ Vd @ avg))
            corr = Vd / np.outer(sd, sd)
            draws = rng.multivariate_normal(np.zeros(len(hs)), corr, size=SIM_DRAWS, method="eigh")
            crit = float(np.quantile(np.abs(draws).max(axis=1), 0.90))  # noqa: E501
            tstat = dv / sd
            maxdraw = np.abs(draws).max(axis=1)
            p_supt = float((maxdraw >= np.abs(tstat).max()).mean())
            rows.append({"window": wname, "pair": f"{j1}-{j2}", "n": n, "nw_lags": lags,
                         "first_t": X.index[ok].min().strftime("%Y-%m"),
                         "last_t": X.index[ok].max().strftime("%Y-%m"),
                         "wald_equal": w, "df": len(hs), "p_wald_equal": 1 - stats.chi2.cdf(w, len(hs)),
                         "mean_diff": m, "se_mean_diff": se_m,
                         "p1_mean_diff_pos": 1 - stats.norm.cdf(m / se_m),
                         "p2_mean_diff": 2 * (1 - stats.norm.cdf(abs(m / se_m))),
                         "share_h_positive": float((dv > 0).mean()),
                         "sup_t_crit90": crit,
                         "n_h_sup_t_excl0": int((np.abs(tstat) > crit).sum()),
                         "max_abs_t": float(np.abs(tstat).max()), "p_supt_equal": p_supt})
            if wname == "0-24":
                for i, h in enumerate(hs):
                    rows[-1].setdefault("_band", []).append((h, dv[i], sd[i] * crit))
        # strong ordering share N>F>R at each h
        b3 = B[idx]
        rows.append({"window": wname, "pair": "N>F>R", "n": n,
                     "share_h_positive": float(((b3[0] > b3[1]) & (b3[1] > b3[2])).mean())})
    return rows


# ---------------------------------------------------------------- plots
def plot_irfs(irf: pd.DataFrame, spec: str, outcomes: list[str], fname: str) -> None:
    colors = {"N": "#1f4e79", "F": "#7f7f7f", "R": "#c55a11"}
    labels = {"N": "N (prefixados)", "F": "F (LFT)", "R": "R (NTN-B)"}
    ncol = 4
    nrow = int(np.ceil(len(outcomes) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(4.0 * ncol, 3.0 * nrow), squeeze=False)
    for ax, o in zip(axes.flat, outcomes):
        g = irf[(irf.spec == spec) & (irf.outcome == o)]
        for j in CLASSES:
            ax.plot(g.h, g[f"b_{j}"], color=colors[j], lw=1.6, label=labels[j])
            ax.fill_between(g.h, g[f"b_{j}"] - 1.645 * g[f"se_{j}"], g[f"b_{j}"] + 1.645 * g[f"se_{j}"],
                            color=colors[j], alpha=0.12, lw=0)
        ax.axhline(0, color="k", lw=0.6)
        ax.set_title(f"{OUTCOMES[o][2]} ({OUTCOMES[o][3]})", fontsize=9)
        ax.tick_params(labelsize=8)
    for ax in list(axes.flat)[len(outcomes):]:
        ax.axis("off")
    axes[0, 0].legend(fontsize=7, frameon=False)
    fig.suptitle(f"Respostas a choque de emissão de 0,1% do PIB, bandas de 90% (spec {spec})", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIG / fname, dpi=150)
    plt.close(fig)


def plot_diffs(irf: pd.DataFrame, bands: dict, outcomes: list[str]) -> None:
    fig, axes = plt.subplots(len(outcomes), 3, figsize=(11, 2.4 * len(outcomes)), squeeze=False)
    for r, o in enumerate(outcomes):
        g = irf[(irf.spec == "base") & (irf.outcome == o)]
        for c, (j1, j2) in enumerate(PAIRS):
            ax = axes[r, c]
            d, se = g[f"d_{j1}{j2}"], g[f"se_d_{j1}{j2}"]
            ax.plot(g.h, d, color="#1f4e79", lw=1.5)
            ax.fill_between(g.h, d - 1.645 * se, d + 1.645 * se, color="#1f4e79", alpha=0.15, lw=0)
            band = bands.get((o, f"{j1}-{j2}"))
            if band:
                hh, dv, half = zip(*band)
                ax.plot(hh, np.array(dv) - np.array(half), color="#1f4e79", lw=0.7, ls="--")
                ax.plot(hh, np.array(dv) + np.array(half), color="#1f4e79", lw=0.7, ls="--")
            ax.axhline(0, color="k", lw=0.6)
            ax.tick_params(labelsize=7)
            if r == 0:
                ax.set_title(f"β^{j1} − β^{j2}", fontsize=9)
            if c == 0:
                ax.set_ylabel(OUTCOMES[o][2], fontsize=8)
    fig.suptitle("Diferenças entre classes (spec base): banda pontual de 90% e banda sup-t de 90% (tracejada)",
                 fontsize=10)
    fig.tight_layout()
    fig.savefig(FIG / "local_projections_differences.png", dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- main
def main() -> None:
    for p in (DIAG, FIG, INTER):
        p.mkdir(parents=True, exist_ok=True)
    d = pd.read_csv(INPUT_PANEL, parse_dates=["month"]).set_index("month").sort_index()
    rng = np.random.default_rng(SEED)

    irf_rows, test_rows, bands = [], [], {}
    scale_rows = []
    for spec_name, spec in SPECS.items():
        for j in CLASSES:
            s = d[spec["shocks"][j]].dropna() * SCALE
            scale_rows.append({"spec": spec_name, "class": j, "column": spec["shocks"][j],
                               "sd_in_0p1pct_gdp": s.std(), "n": len(s),
                               "first": s.index.min().strftime("%Y-%m"), "last": s.index.max().strftime("%Y-%m")})
        outs = OUTCOMES if spec_name == "base" else MAIN_OUTCOMES
        for o in outs:
            X, shocks, y = build_design(d, o, spec)
            ok = sample_mask(X, spec)
            Z = instruments(d, X, shocks, spec)
            if Z is not None:
                ok &= Z.notna().all(axis=1)
            X = drop_collinear_dummies(X, ok)
            if Z is not None:
                Z = Z[X.columns]
            for r in pointwise(X, shocks, y, ok, Z):
                irf_rows.append({"spec": spec_name, "outcome": o, **r})
            for r in window_tests(X, shocks, y, ok, rng, Z):
                band = r.pop("_band", None)
                if band and spec_name == "base":
                    bands[(o, r["pair"])] = band
                test_rows.append({"spec": spec_name, "outcome": o, **r})
        print(f"spec {spec_name}: done")

    irf = pd.DataFrame(irf_rows)
    tests = pd.DataFrame(test_rows)
    scales = pd.DataFrame(scale_rows)
    irf.to_csv(DIAG / "local_projections_irf.csv", index=False)
    tests.to_csv(DIAG / "local_projections_tests.csv", index=False)
    scales.to_csv(DIAG / "local_projections_shock_scale.csv", index=False)
    pd.DataFrame([{"outcome": o, "pair": p, "h": h, "diff": dv, "sup_t_half_width90": hw}
                  for (o, p), b in bands.items() for h, dv, hw in b]).to_csv(
        INTER / "local_projections_sup_t_bands_base.csv", index=False)

    fit = (irf[irf.h.isin([0, 6, 12, 24])]
           [["spec", "outcome", "h", "n", "k", "rank", "nw_lags", "r2", "first_t", "last_t"]])
    fit.to_csv(DIAG / "local_projections_fit.csv", index=False)

    plot_irfs(irf, "base", MAIN_OUTCOMES, "local_projections_base.png")
    plot_irfs(irf, "base", [o for o in OUTCOMES if o not in MAIN_OUTCOMES] + ["p"],
              "local_projections_base_extra.png")
    plot_diffs(irf, bands, ["p", "focus_ipca12m", "bei_2y", "real_5y", "fx"])
    for s in ["evdum", "pre2020", "cfrisk", "nopurge", "ordlast", "iv_naive", "iv_naive_w", "rf_naive"]:
        plot_irfs(irf, s, MAIN_OUTCOMES, f"local_projections_{s}.png")

    audit = {"run_timestamp_utc": timestamp_utc(), "input_panel": str(INPUT_PANEL.relative_to(PROJECT_ROOT)),
             "horizons": H, "shock_unit": "0.1% of lagged 12-month GDP", "windows": list(WINDOWS),
             "sup_t_draws": SIM_DRAWS, "seed": SEED, "specs": list(SPECS),
             "max_rank_deficit": int((irf.k - irf["rank"]).max())}
    pd.DataFrame([audit]).to_csv(DIAG / "local_projections_audit.csv", index=False)
    lists = {"specs": {k: {kk: vv for kk, vv in v.items()} for k, v in SPECS.items()},
             "outcomes": {k: {"column": v[0], "transform": v[1], "label": v[2], "unit": v[3]}
                          for k, v in OUTCOMES.items()},
             "main_outcomes": MAIN_OUTCOMES, "inflation_outcomes_signed": INFLATION_OUTCOMES,
             "controls": {"macro_diff_lags": MACRO_DIFF, "level_t-1": MACRO_LEVEL1, "curve": CURVE,
                          "event_dummies": EVENT_DUMMIES}}
    (DIAG / "local_projection_lists.json").write_text(json.dumps(lists, indent=2, ensure_ascii=False))

    # console summary
    pd.set_option("display.width", 200)
    b = irf[(irf.spec == "base") & irf.h.isin([0, 3, 6, 12, 18, 24])]
    print(b[["outcome", "h", "n", "b_N", "se_N", "b_F", "se_F", "b_R", "se_R", "p_d_NR"]].round(3).to_string())
    t = tests[(tests.spec == "base") & (tests.pair == "N-R")]
    print(t[["outcome", "window", "mean_diff", "se_mean_diff", "p1_mean_diff_pos", "p_wald_equal", "p_supt_equal",
             "share_h_positive", "n_h_sup_t_excl0"]].round(3).to_string())
    print(scales[scales.spec == "base"].round(3).to_string())
    print("max rank deficit:", audit["max_rank_deficit"])


if __name__ == "__main__":
    main()
