#!/usr/bin/env python3
"""Survey-purged issuance shocks epsilon_t^j (eq. 21 of the methodological note).

For each class j in {N, F, R} and each purge specification p:

    u_t^j = a^j + gamma^j' DeltaF_t^p (+ eta^j' W_t) + epsilon_t^j

u_t^j comes from build_issuance_forecasts.py. The baseline DeltaF is the Focus
primary-balance revision (12m and 36m fixed horizons, fixed-event, month t; positive =
higher expected surplus = good news). Alternatives (all on u_{j}_base):

- ``fprim``        Focus primary 12m + 36m (BASELINE)
- ``fprim_xev``    same, gamma estimated without the event months (2007-04 GDP revision,
                   2020-03..07 COVID) and applied to every month
- ``fprim_dum``    same, plus the event impulse dummies (epsilon = 0 in those months)
- ``fprim16``      baseline measure on the Prisma sample (separates measure from sample)
- ``fprim_bc1``    Focus primary 12m + 36m with baseCalculo = 1 (2021-04+)
- ``fprim21``      baseline measure on the baseCalculo = 1 sample
- ``pprim``        Prisma primary 12m + 36m (Central Government, 2016+)
- ``pprim_surp``   Prisma primary + realized-minus-Prisma surprise (release-dated)
- ``fdlsp``        Focus net-debt (DLSP) 12m + 36m (positive = higher expected debt)
- ``fprim_fdlsp``  primary and DLSP together
- ``cfrisk``       fiscal-risk shock of Carvalho Filho (2026), sign-restricted BVAR,
                   posterior median (positive = adverse)
- ``cfrisk_narr``  same, with narrative restrictions
- ``fprim_cfrisk`` Focus primary + cfrisk

The baseline purge is also applied to every forecasting spec of the previous stage
(long, w12, pca, principal, nolead, stock, liq, ramp, base_rt). Output names:
``eps_{j}_{uspec}_{purge}``; ``eps_{j}_base_fprim`` is the main shock.

The Carvalho Filho shocks are read from the frozen replication package
(doi:10.5281/zenodo.24206681, CC-BY-4.0; git-ignored folder, re-download from Zenodo);
SHA-256 recorded in the audit file. They are estimated with full-sample information
and identified with month-t asset prices: robustness only.

Run from the project root:  python3 src/build_purged_shocks.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_issuance_forecasts as bf  # noqa: E402  (OLS + HAC helpers, paths)

mp = bf.mp
plt = mp.plt
rel = mp.rel
DATA_DIR = mp.DATA_DIR
CLEAN_DIR = DATA_DIR / "clean"
DIAGNOSTICS_DIR = DATA_DIR / "diagnostics"
FIGURES_DIR = DATA_DIR / "figures"
INTERMEDIATE_DIR = DATA_DIR / "intermediate" / "purged_shocks"
INPUT_PANEL = CLEAN_DIR / "ftpl_monthly_panel_with_issuance_innovations.csv"
OUTPUT_PANEL = CLEAN_DIR / "ftpl_monthly_panel_with_purged_shocks.csv"
ZENODO = DATA_DIR / "raw" / "zenodo_24206681_fiscal_svar" / "fiscal_svar" / "results"
CF_FILES = {"cf_fiscal_risk": ZENODO / "baseline" / "shocks.csv",
            "cf_fiscal_risk_narr": ZENODO / "narr_baseline_narrative" / "shocks.csv"}
CLASSES = ["N", "F", "R"]
EVENT_DUMMIES = ["d_focus_gdprev_2007m04"] + [f"d_focus_covid_2020m{m:02d}" for m in range(3, 8)]
FPRIM = ["focus_primary_12m_rev_curr", "focus_primary_36m_rev_curr"]
PPRIM = ["prisma_primary_12m_rev_curr_pib", "prisma_primary_36m_rev_curr_pib"]
FDLSP = ["focus_dlsp_12m_rev_curr", "focus_dlsp_36m_rev_curr"]
FPRIM_BC1 = ["focus_primary_bc1_12m_rev_curr", "focus_primary_bc1_36m_rev_curr"]
SURP = ["prisma_primary_surp_pib_release"]

# purge -> (news regressors, W dummies, gamma estimated without event months, sample from)
PURGES = {
    "fprim": (FPRIM, [], False, None),
    "fprim_xev": (FPRIM, [], True, None),
    "fprim_dum": (FPRIM, EVENT_DUMMIES, False, None),
    "fprim16": (FPRIM, [], False, "pprim"),
    "fprim_bc1": (FPRIM_BC1, [], False, None),
    "fprim21": (FPRIM, [], False, "fprim_bc1"),
    "pprim": (PPRIM, [], False, None),
    "pprim_surp": (PPRIM + SURP, [], False, None),
    "fdlsp": (FDLSP, [], False, None),
    "fprim_fdlsp": (FPRIM + FDLSP, [], False, None),
    "cfrisk": (["cf_fiscal_risk"], [], False, None),
    "cfrisk_narr": (["cf_fiscal_risk_narr"], [], False, None),
    "fprim_cfrisk": (FPRIM + ["cf_fiscal_risk"], [], False, None),
}
USPECS_BASELINE_PURGE = ["long", "w12", "pca", "principal", "nolead", "stock", "liq", "ramp", "base_rt"]


def load_cf(audit: list[dict]) -> pd.DataFrame:
    out = {}
    for name, path in CF_FILES.items():
        if not path.exists():
            raise FileNotFoundError(f"{rel(path)} missing: re-download doi:10.5281/zenodo.24206681")
        s = pd.read_csv(path)
        s["month"] = pd.to_datetime(s["date"].astype(str) + "-01")
        if s["month"].duplicated().any():
            raise ValueError(f"duplicated months in {rel(path)}")
        out[name] = s.set_index("month")["fiscal_risk"]
        audit.append({"item": f"Carvalho Filho (2026) {name} (posterior median, + = adverse)",
                      "file": rel(path), "sha256": mp.sha256(path),
                      "first": str(s.month.min().date()), "last": str(s.month.max().date())})
    return pd.DataFrame(out)


def purge(d: pd.DataFrame, ucol: str, news: list[str], dummies: list[str], xev: bool,
          sample: pd.Index | None) -> tuple[pd.Series, dict, list[str]]:
    cols = [ucol] + news + dummies
    x = d[cols].dropna()
    if sample is not None:
        x = x.loc[x.index.intersection(sample)]
    regs = news + [c for c in dummies if x[c].std() > 0]
    est = x
    if xev:
        ev = d[EVENT_DUMMIES].fillna(0).sum(axis=1) > 0
        est = x.loc[~ev.reindex(x.index).values]
    X = np.column_stack([np.ones(len(est))] + [est[c].values for c in regs])
    res = bf.ols_hac(est[ucol].values, X, bf.nw_lags(len(est)))
    Xall = np.column_stack([np.ones(len(x))] + [x[c].values for c in regs])
    eps = pd.Series(x[ucol].values - Xall @ res["b"], index=x.index)
    res["names"] = ["const"] + regs
    res["n_est"] = len(est)
    return eps, res, regs


def main() -> None:
    for d_ in (CLEAN_DIR, DIAGNOSTICS_DIR, FIGURES_DIR, INTERMEDIATE_DIR):
        d_.mkdir(parents=True, exist_ok=True)
    panel = pd.read_csv(INPUT_PANEL)
    panel["month"] = pd.to_datetime(panel["month"])
    print(f"Input panel: {rel(INPUT_PANEL)} {panel.shape}")
    audit: list[dict] = []
    cf = load_cf(audit)
    p = panel.set_index("month")
    clash = [c for c in cf.columns if c in p.columns]
    if clash:
        raise ValueError(f"columns already in panel: {clash}")
    d = p.join(cf, how="left")
    for c in EVENT_DUMMIES:
        d[c] = d[c].fillna(0.0)

    checks, gam_rows, fit_rows = [], [], []

    def check(name, value, ok, note=""):
        checks.append({"check": name, "value": value, "status": "PASS" if ok else "FAIL", "note": note})

    for name, (news, _, _, _) in PURGES.items():
        bad = [c for c in news if not (c.endswith(("_rev_curr", "_rev_curr_pib", "_release"))
                                       or c.startswith("cf_fiscal_risk"))]
        check(f"{name}: DeltaF regressors are month-t news", len(bad), not bad, ", ".join(bad))
    n_cf = int(d.loc[d["u_N_base"].notna(), "cf_fiscal_risk"].notna().sum())
    check("cf_fiscal_risk covers the base innovation sample", n_cf,
          n_cf == int(d["u_N_base"].notna().sum()))

    eps = pd.DataFrame(index=d.index)
    samples = {}
    # common sample per purge across classes (u_N/F/R_base share one sample already)
    for name, (news, dummies, xev, smp_from) in PURGES.items():
        base_s = d[["u_N_base"] + news].dropna().index
        samples[name] = base_s
    for name, (news, dummies, xev, smp_from) in PURGES.items():
        smp = samples[smp_from] if smp_from else None
        for j in CLASSES:
            ucol = f"u_{j}_base"
            e, res, regs = purge(d, ucol, news, dummies, xev, smp)
            col = f"eps_{j}_base_{name}"
            eps.loc[e.index, col] = e.values
            se = np.sqrt(np.diag(res["V"]))
            for nm, b, s in zip(res["names"], res["b"], se):
                gam_rows.append({"purge": name, "equation": j, "variable": nm, "coef": b, "se_hac": s,
                                 "t": b / s, "p": 2 * (1 - stats.norm.cdf(abs(b / s)))})
            w, df_, pw = bf.wald(res, res["names"], news)
            u = d.loc[e.index, ucol]
            fit_rows.append({"purge": name, "u_spec": "base", "equation": j, "n": len(e), "n_est": res["n_est"],
                             "first": e.index.min().strftime("%Y-%m"), "last": e.index.max().strftime("%Y-%m"),
                             "r2_est": res["r2"], "wald_news": w, "df_news": df_, "p_news": pw,
                             "corr_eps_u": float(np.corrcoef(e, u)[0, 1]),
                             "var_removed_share": float(1 - e.var() / u.var()),
                             "news": ";".join(news), "dummies": ";".join(dummies), "gamma_without_events": xev})
            if not xev:
                Xc = np.column_stack([np.ones(len(e))] + [d.loc[e.index, c].values for c in regs])
                check(f"{name}/{j}: X'eps = 0", float(np.abs(Xc.T @ e.values).max()),
                      np.abs(Xc.T @ e.values).max() < 1e-10)
    ev_months = d.index[d[EVENT_DUMMIES].sum(axis=1) > 0]
    z = eps.loc[eps.index.intersection(ev_months), [f"eps_{j}_base_fprim_dum" for j in CLASSES]].abs().max().max()
    check("fprim_dum: epsilon = 0 in the event months", float(z), z < 1e-12)

    # baseline purge on the other forecasting specs
    for us in USPECS_BASELINE_PURGE:
        for j in CLASSES:
            ucol = f"u_Ramp_ramp" if us == "ramp" else f"u_{j}_{us}"
            if us == "ramp" and j != "R":
                continue
            e, res, _ = purge(d, ucol, FPRIM, [], False, None)
            lab = "Ramp" if us == "ramp" else j
            eps.loc[e.index, f"eps_{lab}_{us}_fprim"] = e.values
            w, df_, pw = bf.wald(res, res["names"], FPRIM)
            u = d.loc[e.index, ucol]
            fit_rows.append({"purge": "fprim", "u_spec": us, "equation": lab, "n": len(e), "n_est": len(e),
                             "first": e.index.min().strftime("%Y-%m"), "last": e.index.max().strftime("%Y-%m"),
                             "r2_est": res["r2"], "wald_news": w, "df_news": df_, "p_news": pw,
                             "corr_eps_u": float(np.corrcoef(e, u)[0, 1]),
                             "var_removed_share": float(1 - e.var() / u.var()),
                             "news": ";".join(FPRIM), "dummies": "", "gamma_without_events": False})

    checks_df = pd.DataFrame(checks)
    checks_df.to_csv(DIAGNOSTICS_DIR / "purged_shocks_validation.csv", index=False)
    if (checks_df.status == "FAIL").any():
        print(checks_df[checks_df.status == "FAIL"].to_string(index=False))
        raise SystemExit("Validation failed; nothing written to the panel.")

    gam = pd.DataFrame(gam_rows)
    fits = pd.DataFrame(fit_rows)
    gam.to_csv(DIAGNOSTICS_DIR / "purged_shocks_gamma.csv", index=False)
    fits.to_csv(DIAGNOSTICS_DIR / "purged_shocks_fit.csv", index=False)

    corr_rows = []
    for j in CLASSES:
        b = eps[f"eps_{j}_base_fprim"]
        for name in PURGES:
            if name == "fprim":
                continue
            x = pd.concat([b, eps[f"eps_{j}_base_{name}"]], axis=1).dropna()
            corr_rows.append({"table": "baseline_vs_purge", "a": b.name, "b": f"eps_{j}_base_{name}",
                              "corr": x.corr().iloc[0, 1], "n": len(x)})
        for us in USPECS_BASELINE_PURGE:
            if us == "ramp" and j != "R":
                continue
            col = f"eps_{'Ramp' if us == 'ramp' else j}_{us}_fprim"
            x = pd.concat([b, eps[col]], axis=1).dropna()
            corr_rows.append({"table": "baseline_vs_uspec", "a": b.name, "b": col,
                              "corr": x.corr().iloc[0, 1], "n": len(x)})
    for a in CLASSES:
        for b_ in CLASSES:
            if CLASSES.index(a) < CLASSES.index(b_):
                x = eps[[f"eps_{a}_base_fprim", f"eps_{b_}_base_fprim"]].dropna()
                corr_rows.append({"table": "cross_class_baseline", "a": f"eps_{a}_base_fprim",
                                  "b": f"eps_{b_}_base_fprim", "corr": x.corr().iloc[0, 1], "n": len(x)})
    corrs = pd.DataFrame(corr_rows)
    corrs.to_csv(DIAGNOSTICS_DIR / "purged_shocks_correlations.csv", index=False)

    out_new = pd.concat([cf, eps], axis=1, sort=True).reindex(p.index).copy()
    merged = panel.merge(out_new.reset_index(), on="month", how="left", validate="1:1")
    assert len(merged) == len(panel)
    merged["month"] = merged["month"].dt.strftime("%Y-%m-%d")
    merged.to_csv(OUTPUT_PANEL, index=False)
    ei = eps.dropna(how="all").copy()
    ei.index = ei.index.strftime("%Y-%m-%d")
    ei.to_csv(INTERMEDIATE_DIR / "purged_shocks_monthly.csv")
    pd.DataFrame(audit).to_csv(DIAGNOSTICS_DIR / "purged_shocks_audit.csv", index=False)

    lists = {
        "shocks_baseline": [f"eps_{j}_base_fprim" for j in CLASSES],
        "shocks_alternative_deltaF": {n: [f"eps_{j}_base_{n}" for j in CLASSES] for n in PURGES if n != "fprim"},
        "shocks_alternative_forecasting_spec": sorted(c for c in eps.columns
                                                      if c.endswith("_fprim") and "_base_" not in c),
        "deltaF_definitions": {n: {"news": v[0], "dummies": v[1], "gamma_without_events": v[2],
                                   "sample_from": v[3]} for n, v in PURGES.items()},
        "external_series_added": list(cf.columns),
        "samples": {n: [s.min().strftime("%Y-%m"), s.max().strftime("%Y-%m"), len(s)] for n, s in samples.items()},
        "notes": [
            "eps_* are contemporaneous shocks (month t) for the local projections; never controls.",
            "Signs: Focus/Prisma primary revisions + = good news; DLSP revisions and cf_fiscal_risk + = adverse.",
            "Units of eps: fraction of lagged 12-month GDP (stock spec: fraction of lagged class stock).",
            "fprim_dum sets epsilon to zero in 2007-04 and 2020-03..07; fprim_xev keeps those months.",
            "cf_fiscal_risk(_narr): Carvalho Filho (2026), doi:10.5281/zenodo.24206681, CC-BY-4.0 - cite; "
            "full-sample estimate identified with month-t asset prices (robustness only).",
        ],
    }
    (DIAGNOSTICS_DIR / "purged_shock_lists.json").write_text(json.dumps(lists, indent=2, ensure_ascii=False),
                                                              encoding="utf-8")

    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
    smp = eps["eps_N_base_fprim"].dropna().index
    for ax, j in zip(axes, CLASSES):
        ax.bar(smp, d.loc[smp, f"u_{j}_base"] * 100, width=25, color="0.75", label="u (inovação)")
        ax.plot(smp, eps.loc[smp, f"eps_{j}_base_fprim"] * 100, lw=0.9, color="C0", label="ε, Focus primário")
        ax.plot(smp, eps.loc[smp, f"eps_{j}_base_cfrisk"] * 100, lw=0.9, color="C3", label="ε, choque Carvalho Filho")
        ax.axhline(0, color="k", lw=0.5)
        ax.set_title(f"{j}: inovação e choques purgados (% do PIB 12m)")
        ax.legend(fontsize=7, ncol=3)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "purged_shocks.png", dpi=150)
    plt.close(fig)

    print(f"Wrote {rel(OUTPUT_PANEL)} {merged.shape} (+{out_new.shape[1]} columns)")
    pd.set_option("display.width", 200)
    print(fits[fits.u_spec == "base"][["purge", "equation", "n", "n_est", "first", "last", "r2_est", "p_news",
                                       "corr_eps_u", "var_removed_share"]].round(3).to_string(index=False))
    print(fits[fits.u_spec != "base"][["u_spec", "equation", "n", "r2_est", "p_news", "corr_eps_u"]]
          .round(3).to_string(index=False))
    g = gam[gam.variable != "const"]
    print(g[g.purge.isin(["fprim", "pprim", "pprim_surp", "fdlsp", "cfrisk", "cfrisk_narr", "fprim_cfrisk"])]
          [["purge", "equation", "variable", "coef", "se_hac", "t"]].round(4).to_string(index=False))
    print(corrs.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
