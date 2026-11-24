"""Auction-level offer surprises (Proposal 1 of DocumentacaoProjeto.tex, sec:ident).

Unit k: auction day of one title (LTN, NTN-F, LFT, NTN-B, NTN-B Principal),
first round. Bond rows are first collapsed into lots (joint lots shared by
several maturities counted once; diagnose_auction_takeup.load_lots, ambiguous
groups joint by default, separate in the ``sep`` variant). The Treasury's
supply decision on day k is the value offered,
    OV_k = sum over lots of lot quantity x P_ref,
with P_ref the mean, over the lot's bonds, of each bond's last auction unit
price before day k (title mean as fallback), so no same-day price enters.
The edital date is not in the data; it is assumed to be the business day
before the auction, so the pre-edital information set is dated k - 2 business
days.

Surprise, two versions:
- ``naive``: OV_k - OV_prev, with OV_prev the value offered on the previous
  auction day of the same title;
- ``pred``: OV_k - OV_prev * exp(x_k' b), where log(OV_k / OV_prev) is forecast by
  a recursive (expanding-window, re-estimated each month, per class) OLS on
  pre-edital information x_k: changes of PRE 1y, PRE 5y and IPCA 5y zero yields
  (ANBIMA ETTJ) between the previous auction day of the title and k - 2,
  whether the previous day was binding (whole value sold), its take-up, the mean
  take-up of the title's last four days, log days since the previous day and
  the mean log years to maturity of the lots.

Binding probability: pi_k = Pr(day k sells the whole value offered | x_k), a
recursive logit per class on the same x_k. Weighted surprises multiply the surprise by
pi_k. Binding auctions are never selected on (binding is an auction outcome).

Monthly instruments: sum over auctions of class j in month t, divided by lagged
12-month GDP (same units as eps), columns ``offsurp_{j}_{naive,pred}[_w]``.

Diagnostics:
- lot-forecast and logit fit (recursive out-of-sample R2, Brier, AUC);
- anticipation test: day-level regression of value sold (over OV_prev) on the
  surprise (over OV_prev) by bins of pi_k. Under an exogenous lot, sold =
  min(O_k, D_k) with D_k independent of the lot, so the slope is ~1 on days
  expected to bind and ~0 on days expected not to bind; a positive slope in the
  latter means the lot anticipates demand (or that demand responds to the lot);
- monthly first stage of eps_j on the three instruments with the LP controls
  (HAC partial F and Sanderson-Windmeijer F);
- correlation of the monthly instruments with same-month and previous-month
  asset-price changes, next to the same correlations for eps.

Reads  data/clean/ftpl_monthly_panel_with_inflation_expectations.csv,
       data/raw/historico-leiloes-todos.xls,
       data/intermediate/anbima/anbima_yield_curve_features_daily.csv.
Writes data/clean/ftpl_monthly_panel_with_offer_surprises.csv,
       data/intermediate/offer_surprises/offer_surprises_auctions.csv,
       data/diagnostics/offer_surprises_{audit,forecast_fit,anticipation,
       first_stage,exogeneity}.csv, data/figures/offer_surprises.png.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
import diagnose_auction_takeup as dt  # noqa: E402
import build_local_projections as lp  # noqa: E402

ROOT = dt.ROOT
DATA = ROOT / "data"
os.environ.setdefault("MPLCONFIGDIR", str(DATA / ".mplconfig"))
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

INPUT_PANEL = DATA / "clean" / "ftpl_monthly_panel_with_inflation_expectations.csv"
OUTPUT_PANEL = DATA / "clean" / "ftpl_monthly_panel_with_offer_surprises.csv"
CURVES = DATA / "intermediate" / "anbima" / "anbima_yield_curve_features_daily.csv"
DIAG = DATA / "diagnostics"
INTER = DATA / "intermediate" / "offer_surprises"
FIG = DATA / "figures"

START = pd.Timestamp("2006-02-01")   # ETTJ daily starts 2006-01-02
MIN_TRAIN = 80                       # auctions per class before recursive fits start
CURVE_VARS = ["pre_1y", "pre_5y", "ipca_5y"]
X_VARS = [f"d_{c}" for c in CURVE_VARS] + ["bind_prev", "takeup_prev", "takeup_mean4",
                                            "log_days_prev", "log_years_mat"]
CLASSES = ["N", "F", "R"]
PI_BINS = [(0.0, 0.3, "baixa (<0,3)"), (0.3, 0.7, "média"), (0.7, 1.01, "alta (>=0,7)")]


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------- auction data
def auctions(ambiguous_joint: bool = True) -> pd.DataFrame:
    """Day x title units built from lots, with predetermined reference prices."""
    bonds = dt.load_auctions()
    bonds["title"] = bonds["title"].astype(str).str.strip()
    bonds["maturity"] = pd.to_datetime(bonds["maturity"], errors="coerce")
    bonds["bond"] = bonds["title"] + "|" + bonds["maturity"].dt.strftime("%Y-%m-%d")
    lots = dt.load_lots(ambiguous_joint, bonds)

    # bond price history (auction unit prices) -> last price strictly before each day
    px = (bonds[bonds["sold"] > 0].assign(p=lambda x: x["value_brl"] / x["sold"])
          .groupby(["bond", "date"])["p"].mean().reset_index().sort_values("date"))
    px_title = px.assign(title=px["bond"].str.split("|").str[0])

    def last_price(bond: str, day: pd.Timestamp) -> float:
        h = hist.get(bond)
        if h is None:
            return np.nan
        i = h.index.searchsorted(day, side="left") - 1
        return float(h.iloc[i]) if i >= 0 else np.nan

    hist = {b: g.set_index("date")["p"] for b, g in px.groupby("bond")}
    title_hist = {t: g.groupby("date")["p"].mean() for t, g in px_title.groupby("title")}
    p_ref = []
    for _, r in lots.iterrows():
        vals = [last_price(b, r["date"]) for b in r["bonds"].split(";")]
        vals = [v for v in vals if np.isfinite(v)]
        if not vals:  # new bonds: mean last price of the title
            h = title_hist.get(r["title"])
            i = -1 if h is None else h.index.searchsorted(r["date"], side="left") - 1
            vals = [float(h.iloc[i])] if h is not None and i >= 0 else []
        p_ref.append(np.mean(vals) if vals else np.nan)
    lots["p_ref"] = p_ref
    lots["years_mat"] = ((lots["maturity"] - lots["date"]).dt.days / 365.25).clip(lower=0.05)

    lots["ov"] = lots["offer"] * lots["p_ref"]
    lots["sv_ref"] = lots["sold"] * lots["p_ref"]
    a = (lots.groupby(["date", "title"])
         .agg(cls=("class", "first"), n_lots=("lot_id", "size"), ov=("ov", "sum"),
              sv_ref=("sv_ref", "sum"), value_brl=("value_brl", "sum"),
              p_missing=("p_ref", lambda x: x.isna().any()),
              log_years_mat=("years_mat", lambda x: np.log(x).mean()))
         .reset_index().rename(columns={"cls": "class"}))
    a.loc[a["p_missing"], ["ov", "sv_ref"]] = np.nan
    a["takeup"] = a["sv_ref"] / a["ov"]
    a["binding"] = (a["takeup"] >= 0.999).astype(float).where(a["takeup"].notna())
    a = a.sort_values(["date", "title"]).reset_index(drop=True)
    g = a.groupby("title")
    a["ov_prev"] = g["ov"].shift()
    a["date_prev"] = g["date"].shift()
    a["bind_prev"] = g["binding"].shift()
    a["takeup_prev"] = g["takeup"].shift()
    a["takeup_mean4"] = g["takeup"].transform(lambda x: x.shift().rolling(4, min_periods=1).mean())
    a["log_days_prev"] = np.log((a["date"] - a["date_prev"]).dt.days.clip(lower=1))
    return a


def add_curve_changes(a: pd.DataFrame) -> pd.DataFrame:
    """Yield changes between the previous auction of the bond and tau_k - 2 business days."""
    c = pd.read_csv(CURVES, parse_dates=["date"]).set_index("date").sort_index()[CURVE_VARS]
    days = c.index

    def at_or_before(dates: pd.Series, lag: int) -> pd.Series:
        pos = days.searchsorted(dates.to_numpy(), side="left") - lag  # first day >= date, minus lag
        pos = np.where(dates.isna(), -1, pos)
        out = pd.Series(pd.NaT, index=dates.index, dtype="datetime64[ns]")
        ok = (pos >= 0) & (dates.notna().to_numpy()) & (dates.to_numpy() <= days[-1] + pd.Timedelta(days=3))
        out[ok] = days[pos[ok]]
        return out

    a["info_date"] = at_or_before(a["date"], 2)        # tau_k - 2 business days
    a["prev_info_date"] = at_or_before(a["date_prev"], 1)  # close before the previous auction
    for v in CURVE_VARS:
        a[f"d_{v}"] = (c[v].reindex(a["info_date"]).to_numpy()
                       - c[v].reindex(a["prev_info_date"]).to_numpy())
    return a


# ---------------------------------------------------------------- recursive models
def logit_fit(X: np.ndarray, y: np.ndarray, ridge: float = 1e-4, it: int = 50) -> np.ndarray:
    b = np.zeros(X.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-X @ b))
        W = p * (1 - p)
        H = X.T @ (X * W[:, None]) + ridge * np.eye(X.shape[1])
        step = np.linalg.solve(H, X.T @ (y - p) - ridge * b)
        b += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return b


def recursive_models(a: pd.DataFrame) -> pd.DataFrame:
    a = a.copy()
    a["month"] = a["date"].dt.to_period("M").dt.to_timestamp()
    a["dlog_offer"] = np.log(a["ov"] / a["ov_prev"])
    a["x_ok"] = (a[X_VARS].notna().all(axis=1) & (a["date"] >= START) & np.isfinite(a["dlog_offer"])
                 & a["binding"].notna())
    a["dlog_offer_hat"] = np.nan
    a["pi_hat"] = np.nan
    a["recursive"] = False
    for c in CLASSES:
        ac = a[a["class"] == c]
        for m in sorted(ac["month"].unique()):
            train = ac[(ac["month"] < m) & ac["x_ok"]]
            test_idx = ac.index[(ac["month"] == m) & ac["x_ok"]]
            if len(test_idx) == 0 or len(train) < MIN_TRAIN:
                continue
            X = np.column_stack([np.ones(len(train)), train[X_VARS].to_numpy(float)])
            mu, sd = X[:, 1:].mean(0), X[:, 1:].std(0)
            sd[sd == 0] = 1
            Xs = X.copy()
            Xs[:, 1:] = (X[:, 1:] - mu) / sd
            b_ols = np.linalg.lstsq(Xs, train["dlog_offer"].to_numpy(float), rcond=None)[0]
            b_log = logit_fit(Xs, train["binding"].to_numpy(float))
            T = a.loc[test_idx, X_VARS].to_numpy(float)
            Ts = np.column_stack([np.ones(len(T)), (T - mu) / sd])
            a.loc[test_idx, "dlog_offer_hat"] = Ts @ b_ols
            a.loc[test_idx, "pi_hat"] = 1 / (1 + np.exp(-Ts @ b_log))
            a.loc[test_idx, "recursive"] = True
    return a


def surprises(a: pd.DataFrame) -> pd.DataFrame:
    has_prev = a["ov_prev"].notna() & a["ov"].notna()
    a["surp_naive_brl"] = np.where(has_prev, a["ov"] - a["ov_prev"], 0.0)
    pred = a["ov_prev"] * np.exp(a["dlog_offer_hat"])
    a["surp_pred_brl"] = np.where(has_prev & a["recursive"], a["ov"] - pred, np.nan)
    # no basis (first day of a title, or no reference price): zero surprise in every version
    a.loc[~has_prev, "surp_pred_brl"] = 0.0
    a["surp_naive_w_brl"] = np.where(~has_prev, 0.0, a["surp_naive_brl"] * a["pi_hat"])
    a["surp_pred_w_brl"] = np.where(~has_prev, 0.0, a["surp_pred_brl"] * a["pi_hat"])
    # model-based versions only exist once the ETTJ (and the recursive fits) exist
    pre = a["date"] < START
    a.loc[pre, ["surp_pred_brl", "surp_naive_w_brl", "surp_pred_w_brl"]] = np.nan
    a["no_basis"] = ~has_prev
    return a


def monthly(a: pd.DataFrame, pib: pd.Series) -> pd.DataFrame:
    out = {}
    for c in CLASSES:
        ac = a[a["class"] == c]
        g = ac.groupby("month")
        for v in ["naive", "pred", "naive_w", "pred_w"]:
            col = f"surp_{v}_brl"
            s = g[col].sum(min_count=1)
            if v != "naive":  # a month is missing if any auction lacks the recursive forecast
                s[g[col].apply(lambda x: x.isna().any())] = np.nan
            out[f"offsurp_{c}_{v}"] = s
        out[f"offsurp_{c}_n_auctions"] = g.size().astype(float)
    m = pd.DataFrame(out)
    m.index.name = "month"
    m = m.reindex(pib.index)
    for c in CLASSES:
        for v in ["naive", "pred", "naive_w", "pred_w"]:
            m[f"offsurp_{c}_{v}"] = m[f"offsurp_{c}_{v}"] / pib
        # months without auctions of the class: zero surprise inside the auction sample
        inside = (m.index >= a["month"].min()) & (m.index <= a["month"].max())
        for v in ["naive"]:
            m.loc[inside & m[f"offsurp_{c}_{v}"].isna() & m[f"offsurp_{c}_n_auctions"].isna(),
                  f"offsurp_{c}_{v}"] = 0.0
        m[f"offsurp_{c}_n_auctions"] = m[f"offsurp_{c}_n_auctions"].where(~inside, m[f"offsurp_{c}_n_auctions"].fillna(0))
    return m


# ---------------------------------------------------------------- diagnostics
def auc(y: np.ndarray, p: np.ndarray) -> float:
    r = stats.rankdata(p)
    n1 = y.sum()
    n0 = len(y) - n1
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 and n0 else np.nan


def forecast_fit(a: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for c in CLASSES:
        r = a[(a["class"] == c) & a["recursive"]]
        y, yh = r["dlog_offer"].to_numpy(float), r["dlog_offer_hat"].to_numpy(float)
        bnd, pi = r["binding"].to_numpy(float), r["pi_hat"].to_numpy(float)
        prev = r["bind_prev"].to_numpy(float)
        rows.append({
            "class": c, "n_units": int((a["class"] == c).sum()),
            "n_recursive": len(r), "first_recursive": r["date"].min().date().isoformat(),
            "n_days_title": int((a["class"] == c).sum()),
            "share_no_basis": float(a.loc[a["class"] == c, "no_basis"].mean()),
            "share_lot_unchanged": float((r["dlog_offer"] == 0).mean()),
            "sd_dlog_offer": float(np.std(y)),
            "oos_r2_lot_vs_naive": float(1 - np.sum((y - yh) ** 2) / np.sum(y ** 2)),
            "binding_rate": float(bnd.mean()),
            "brier_logit": float(np.mean((bnd - pi) ** 2)),
            "brier_prev_state": float(np.mean((bnd - prev) ** 2)),
            "brier_constant": float(np.mean((bnd - bnd.mean()) ** 2)),
            "auc_logit": auc(bnd, pi),
        })
    return pd.DataFrame(rows)


def cluster_ols(y: np.ndarray, X: np.ndarray, cl: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    xtx = np.linalg.pinv(X.T @ X)
    b = xtx @ X.T @ y
    u = y - X @ b
    S = np.zeros((X.shape[1], X.shape[1]))
    for g in np.unique(cl):
        s = (X[cl == g] * u[cl == g, None]).sum(0)
        S += np.outer(s, s)
    G, n, k = len(np.unique(cl)), len(y), X.shape[1]
    V = xtx @ S @ xtx * G / (G - 1) * (n - 1) / (n - k)
    return b, np.sqrt(np.diag(V))


def anticipation(a: pd.DataFrame) -> pd.DataFrame:
    """Slope of sold/O_prev on the lot surprise/O_prev, by expected binding probability."""
    rows = []
    r = a[a["recursive"] & a["ov_prev"].notna() & a["ov"].notna()].copy()
    r["sold_rel"] = r["sv_ref"] / r["ov_prev"]
    for v in ["naive", "pred"]:
        lot_hat = r["ov_prev"] if v == "naive" else r["ov_prev"] * np.exp(r["dlog_offer_hat"])
        r[f"s_rel_{v}"] = (r["ov"] - lot_hat) / r["ov_prev"]
        r[f"lot_hat_rel_{v}"] = lot_hat / r["ov_prev"]
    for c in CLASSES:
        for lo, hi, lab in PI_BINS:
            rb = r[(r["class"] == c) & (r["pi_hat"] >= lo) & (r["pi_hat"] < hi)]
            rb = rb[np.isfinite(rb["sold_rel"]) & (rb["sold_rel"] < rb["sold_rel"].quantile(0.995))]
            for v in ["naive", "pred"]:
                if len(rb) < 30:
                    continue
                X = np.column_stack([np.ones(len(rb)), rb[f"s_rel_{v}"], rb[f"lot_hat_rel_{v}"],
                                     rb[[f"d_{x}" for x in CURVE_VARS]].to_numpy(float)])
                b, se = cluster_ols(rb["sold_rel"].to_numpy(float), X,
                                    rb["month"].dt.strftime("%Y%m").astype(int).to_numpy())
                rows.append({"class": c, "pi_bin": lab, "version": v, "n": len(rb),
                             "binding_rate": float(rb["binding"].mean()),
                             "mean_pi_hat": float(rb["pi_hat"].mean()),
                             "slope": b[1], "se_cluster_month": se[1], "t": b[1] / se[1]})
    return pd.DataFrame(rows)


def first_stage(d: pd.DataFrame, inst: str) -> list[dict]:
    """eps_j on the three monthly instruments + LP controls (price-level outcome design)."""
    spec = dict(lp.SPECS["base"])
    X, shocks, _ = lp.build_design(d, "p", spec)
    Z = pd.DataFrame({f"z_{j}": d[f"offsurp_{j}_{inst}"] * lp.SCALE for j in CLASSES})
    ok = lp.sample_mask(X, spec) & Z.notna().all(axis=1)
    X = lp.drop_collinear_dummies(X, ok)
    E = X.loc[ok, shocks].to_numpy(float)
    C = X.loc[ok].drop(columns=shocks).to_numpy(float)
    Zm = Z.loc[ok].to_numpy(float)
    n = len(E)
    lags = lp.nw_lags(n)
    W = np.column_stack([Zm, C])
    rows = []
    wfit = W @ np.linalg.pinv(W.T @ W) @ W.T @ E  # first-stage fitted values of all endogenous
    for a_, j in enumerate(CLASSES):
        y = E[:, a_]
        xtx = np.linalg.pinv(W.T @ W)
        b = xtx @ W.T @ y
        u = y - W @ b
        V = xtx @ lp.hac(W * u[:, None], lags) @ xtx * n / (n - W.shape[1])
        Vz = V[:3, :3]
        wald = float(b[:3] @ np.linalg.pinv(Vz) @ b[:3])
        # Sanderson-Windmeijer: purge the other endogenous (2SLS) and test Z on the residual
        others = [k for k in range(3) if k != a_]
        D = np.column_stack([wfit[:, others], C])
        g = np.linalg.pinv(D.T @ D) @ D.T @ y
        e = y - np.column_stack([E[:, others], C]) @ g
        bb = xtx @ W.T @ e
        uu = e - W @ bb
        VV = xtx @ lp.hac(W * uu[:, None], lags) @ xtx * n / (n - W.shape[1])
        sw = float(bb[:3] @ np.linalg.pinv(VV[:3, :3]) @ bb[:3]) / (3 - 2)
        row = {"instrument": inst, "class": j, "n": n, "first": X.index[ok].min().strftime("%Y-%m"),
               "last": X.index[ok].max().strftime("%Y-%m"), "hac_lags": lags,
               "partial_F_hac": wald / 3, "SW_F_hac": sw,
               "partial_r2": float(1 - (u @ u) / ((y - C @ np.linalg.lstsq(C, y, rcond=None)[0]) @
                                                 (y - C @ np.linalg.lstsq(C, y, rcond=None)[0])))}
        for k, jj in enumerate(CLASSES):
            row[f"coef_z_{jj}"] = b[k]
            row[f"t_z_{jj}"] = b[k] / np.sqrt(V[k, k])
        rows.append(row)
    return rows


def exogeneity(d: pd.DataFrame) -> pd.DataFrame:
    prices = {"real_5y": d["real_yield_5y_pct"], "ltn_1y": d["ltn_1y_pct"],
              "bei_2y": d["bei_2y_pct"], "fx": 100 * np.log(d["brl_usd"]),
              "embi": d["embi_spread_bp"], "focus_ipca12m": d["focus_ipca12m_pct"]}
    dp = pd.DataFrame({k: v.diff() for k, v in prices.items()})
    rows = []
    for j in CLASSES:
        series = {"eps": d[f"eps_{j}_base_fprim"]}
        series.update({v: d[f"offsurp_{j}_{v}"] for v in ["naive", "pred", "naive_w", "pred_w", "naive_sep"]})
        for name, s in series.items():
            jj = pd.concat([s.rename("s"), dp], axis=1).loc["2007-02-01":"2025-02-01"].dropna()
            row = {"class": j, "series": name, "months": len(jj)}
            for k in prices:
                row[f"corr_d_{k}_t"] = jj["s"].corr(jj[k])
                row[f"corr_d_{k}_tm1"] = jj["s"].corr(dp[k].shift(1).reindex(jj.index))
            rows.append(row)
    return pd.DataFrame(rows)


def plot(d: pd.DataFrame) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(10, 7.5), sharex=True)
    smp = slice("2006-11-01", "2025-02-01")
    for ax, j in zip(axes, CLASSES):
        ax.plot(d.loc[smp].index, d.loc[smp, f"eps_{j}_base_fprim"] * 100, color="0.6", lw=0.9,
                label="choque purgado ε (% PIB)")
        ax.plot(d.loc[smp].index, d.loc[smp, f"offsurp_{j}_pred"] * 100, color="#1f4e79", lw=1.1,
                label="surpresa de oferta (pred)")
        ax.plot(d.loc[smp].index, d.loc[smp, f"offsurp_{j}_pred_w"] * 100, color="#c55a11", lw=0.9,
                label="surpresa ponderada por π̂")
        ax.axhline(0, color="k", lw=0.5)
        ax.set_title(j, fontsize=9, loc="left")
        ax.tick_params(labelsize=8)
    axes[0].legend(fontsize=7, frameon=False, ncol=3)
    fig.suptitle("Surpresas de oferta por leilão, somadas no mês, e choques purgados", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIG / "offer_surprises.png", dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- main
def main() -> None:
    for p in (DIAG, INTER, FIG):
        p.mkdir(parents=True, exist_ok=True)
    panel = pd.read_csv(INPUT_PANEL, parse_dates=["month"]).set_index("month").sort_index()

    a = add_curve_changes(auctions())
    a = surprises(recursive_models(a))
    a.to_csv(INTER / "offer_surprises_auctions.csv", index=False, date_format="%Y-%m-%d")

    m = monthly(a, panel["pib_12m_lag1_brl"])
    # robustness: ambiguous same-offer groups treated as separate lots (naive surprise)
    b = auctions(ambiguous_joint=False)
    b["month"] = b["date"].dt.to_period("M").dt.to_timestamp()
    b["s"] = np.where(b["ov_prev"].notna() & b["ov"].notna(), b["ov"] - b["ov_prev"], 0.0)
    for c in CLASSES:
        ms = b[b["class"] == c].groupby("month")["s"].sum().reindex(m.index)
        inside = (m.index >= b["month"].min()) & (m.index <= b["month"].max())
        m[f"offsurp_{c}_naive_sep"] = (ms / panel["pib_12m_lag1_brl"]).where(~inside | ms.notna(), 0.0)
        m.loc[inside & ms.isna(), f"offsurp_{c}_naive_sep"] = 0.0
    clash = [c for c in m.columns if c in panel.columns]
    if clash:
        raise ValueError(f"columns already in panel: {clash}")
    d = pd.concat([panel, m], axis=1).copy()
    d.reset_index().to_csv(OUTPUT_PANEL, index=False, date_format="%Y-%m-%d")

    fit = forecast_fit(a)
    ant = anticipation(a)
    fs = pd.DataFrame([r for v in ["naive", "pred", "naive_w", "pred_w", "naive_sep"] for r in first_stage(d, v)])
    exo = exogeneity(d)
    fit.to_csv(DIAG / "offer_surprises_forecast_fit.csv", index=False)
    ant.to_csv(DIAG / "offer_surprises_anticipation.csv", index=False)
    fs.to_csv(DIAG / "offer_surprises_first_stage.csv", index=False)
    exo.to_csv(DIAG / "offer_surprises_exogeneity.csv", index=False)
    plot(d)

    cov = {f"offsurp_{j}_{v}": f"{m[f'offsurp_{j}_{v}'].first_valid_index():%Y-%m}.."
           f"{m[f'offsurp_{j}_{v}'].last_valid_index():%Y-%m} ({m[f'offsurp_{j}_{v}'].notna().sum()})"
           for j in CLASSES for v in ["naive", "pred", "naive_w", "pred_w"]}
    audit = {"run_timestamp_utc": timestamp_utc(), "input_panel": str(INPUT_PANEL.relative_to(ROOT)),
             "auction_file": str(dt.RAW.relative_to(ROOT)), "curve_file": str(CURVES.relative_to(ROOT)),
             "n_auctions_first_round": len(a), "edital_assumption": "edital on tau-1; info set tau-2",
             "min_train_auctions": MIN_TRAIN, "x_vars": ";".join(X_VARS),
             "output_panel": str(OUTPUT_PANEL.relative_to(ROOT)),
             "output_shape": f"{d.shape[0]}x{d.shape[1] + 1}", **cov}
    pd.DataFrame([audit]).to_csv(DIAG / "offer_surprises_audit.csv", index=False)

    pd.set_option("display.width", 220)
    print(fit.round(3).to_string(index=False))
    print(ant.round(3).to_string(index=False))
    print(fs[["instrument", "class", "n", "partial_F_hac", "SW_F_hac", "partial_r2",
              "coef_z_N", "t_z_N", "coef_z_F", "t_z_F", "coef_z_R", "t_z_R"]].round(2).to_string(index=False))
    print(exo[["class", "series", "months", "corr_d_real_5y_t", "corr_d_ltn_1y_t", "corr_d_fx_t",
               "corr_d_embi_t", "corr_d_real_5y_tm1", "corr_d_fx_tm1"]].round(2).to_string(index=False))
    print(pd.Series(audit).to_string())


if __name__ == "__main__":
    main()
