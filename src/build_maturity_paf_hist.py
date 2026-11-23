#!/usr/bin/env python3
"""Predetermined maturity schedule, RMD composition and PAF gaps over 2000-2026.

The maturity proxy of the original notebook (``scheduled_maturities_proxy.csv``)
uses the eDPF stock, so it only exists from 2017-10 and carries principal only.
This stage builds a longer, predetermined debt-service schedule by class from
Tesouro's Relatorio Mensal da Divida (RMD) annex
``data/raw/liquidity_sources/Anexo RMD_Maio_26.xlsx`` (read, never modified),
and recomputes the PAF gaps with the long share series.

RMD sheets used (market holdings, R$):

| sheet | content                                                        | coverage          |
|-------|----------------------------------------------------------------|-------------------|
| 2.2   | month-end stock by security (quantity, curve value, maturity)  | 2010-01..2026-05  |
| 1.3   | realized redemptions at maturity by title (principal + coupons)| 2006-11..2026-05  |
| 3.3   | month-end stock maturing in the next 12 months, by indexer     | 1999-12..2026-05  |
| 2.4   | DPF composition by indexer (the PAF's own metric)              | 2000-12..2026-05  |
| 3.7   | DPF average maturity (years)                                   | 2005-12, 2006-11..|

Monthly schedule ``maturity_{g}_sched_brl`` (debt service due in month t, known
at the end of t-1), classes N = LTN + NTN-F, F = LFT, R = all NTN-B variants
(as in the eDPF mapping), C = NTN-C (broad real block ``Ramp`` = R + C):

* principal: curve value at the end of t-1 (RMD 2.2) of securities maturing in t
  (same concept as the eDPF proxy);
* coupons: quantity at the end of t-1 times the coupon per bond paid in t:
  NTN-F 1000 * (1.10^0.5 - 1) in January and July; NTN-B VNA * (1.06^0.5 - 1)
  and NTN-C VNA * ((1+c)^0.5 - 1), c = 12% for the 2031 NTN-C and 6% otherwise,
  in the maturity month and six months away. VNA = 1000 * I(t-2) / I(base),
  with IPCA (panel ``ipca_index``, base 2000-06) for NTN-B and IGP-M (SGS 189,
  base 2000-06) for NTN-C. I(t-2) keeps the value predetermined (the index of
  t-1 is only released in t); the error is one month of inflation on a coupon.
  NTN-B Principal has no coupons; NTN-B1 (Renda+/Educa+) instalments are not
  modelled (none fall due before 2026 except small Educa+ amounts).

The schedule from 2.2 covers t = 2010-02..2026-06. For t = 2006-11..2010-01 the
column uses the realized redemptions of RMD 1.3 (``maturity_sched_source`` says
which). The script validates the schedule against 1.3 and the principal against
the eDPF proxy in the overlaps.

12-month windows ``maturity12m_{N,F,Ramp,total}_rmd_brl_lag1`` come from RMD 3.3
(stock at the end of t-1 maturing within 12 months, including intermediate
payments; Indices de precos = NTN-B + NTN-C, Total = all DPMFi in market).

PAF gaps (all predetermined, ``_lag1``) against the targets already in the panel
(``paf_{g}_target`` = mid-band, ``paf_*_min/max``), for three share definitions:

* ``hist``: ``share_{g}_hist_lag1`` (over N+F+R; SGS before 2017-09);
* ``hist_mkt``: ``share_{g}_hist_mkt_lag1`` (over all market DPMFi);
* ``rmd``: DPF composition by indexer from RMD 2.4 - the metric the PAF bands are
  written in (DPF, includes external debt; price-index includes NTN-C). Also FX.

plus ``paf_gap_maturing_12m_rmd_lag1`` (RMD 3.3 total share maturing in 12m;
DPMFi instead of DPF) and ``paf_gap_avg_maturity_rmd_lag1`` (RMD 3.7 DPF).

Run from the project root:  python3 src/build_maturity_paf_hist.py [--offline]
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

RMD_FILE = DATA_DIR / "raw" / "liquidity_sources" / "Anexo RMD_Maio_26.xlsx"
BCB_RAW_DIR = DATA_DIR / "raw" / "bcb"
INTERMEDIATE_DIR = DATA_DIR / "intermediate" / "maturity_paf"
CLEAN_DIR = DATA_DIR / "clean"
DIAGNOSTICS_DIR = DATA_DIR / "diagnostics"
FIGURES_DIR = DATA_DIR / "figures"
INPUT_PANEL = CLEAN_DIR / "ftpl_monthly_panel_with_stock_history.csv"
OUTPUT_PANEL = CLEAN_DIR / "ftpl_monthly_panel_with_maturity_paf_hist.csv"
PROXY_FILE = CLEAN_DIR / "scheduled_maturities_proxy.csv"

SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
IGPM_SGS = 189
PT_MONTHS = {"Jan": 1, "Fev": 2, "Mar": 3, "Abr": 4, "Mai": 5, "Jun": 6,
             "Jul": 7, "Ago": 8, "Set": 9, "Out": 10, "Nov": 11, "Dez": 12}
GROUPS = ["N", "F", "R", "C"]
VNA_BASE = pd.Timestamp("2000-06-01")  # NTN-B base 15/07/2000, NTN-C base 01/07/2000
NTNF_COUPON = 1000 * (1.10 ** 0.5 - 1)
NTNB_RATE = 1.06 ** 0.5 - 1
# Tolerances for the validation (relative to realized RMD 1.3 redemptions)
MAX_ABS_REL_GAP_TOTAL = 0.05     # mean |gap| / mean realized, N+F+R, 2010-02 on
MAX_PROXY_REL_GAP = 0.01         # max |2.2 principal - eDPF proxy| / proxy, per month/class


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pt_month(label) -> pd.Timestamp | None:
    """'Jan/10' -> 2010-01-01; anything else (annual totals, blanks) -> None."""
    if not isinstance(label, str) or "/" not in label:
        return None
    mon, yy = label.strip().split("/")
    if mon not in PT_MONTHS or not yy.isdigit():
        return None
    year = int(yy)
    return pd.Timestamp(2000 + year if year < 80 else 1900 + year, PT_MONTHS[mon], 1)


def group_of(title: str) -> str | None:
    t = str(title).strip()
    if t in ("LTN", "NTN-F"):
        return "N"
    if t.startswith("LFT"):
        return "F"
    if t.startswith("NTN-B"):
        return "R"
    if t == "NTN-C":
        return "C"
    return None


# ---------------------------------------------------------------- RMD readers
def read_security_stock(xls: pd.ExcelFile) -> pd.DataFrame:
    """RMD 2.2: one row per security and month-end (quantity in units, value in R$)."""
    d = xls.parse("2.2", header=None)
    header_row = d.index[d.iloc[:, 3].astype(str).str.strip().eq("Estoque")][0]
    months, kinds = d.iloc[header_row + 1], d.iloc[header_row + 2]
    cols, current = [], None
    for j in range(3, d.shape[1]):
        m = pt_month(months[j])
        if m is not None:
            current = m
        kind = str(kinds[j])
        if current is not None and ("Quant" in kind or "Financ" in kind):
            cols.append((j, current, "qty" if "Quant" in kind else "value"))
    is_row = d.iloc[:, 1].map(lambda v: isinstance(v, (pd.Timestamp, datetime)))
    recs = []
    for _, r in d[is_row].iterrows():
        for j, m, k in cols:
            if pd.notna(r[j]):
                recs.append((str(r[0]).strip(), pd.Timestamp(r[1]), r[2], m, k, float(r[j])))
    long = pd.DataFrame(recs, columns=["title", "maturity", "isin", "month", "kind", "v"])
    out = long.pivot_table(index=["title", "maturity", "isin", "month"], columns="kind",
                           values="v", aggfunc="sum").reset_index()
    # Two source cells are blank where the other measure is zero (LTN 2032 in
    # 2024-01, NTN-B 2033 in 2018-07): treat as zero; any other gap is an error.
    for a, b in (("qty", "value"), ("value", "qty")):
        fill = out[a].isna() & out[b].eq(0)
        out.loc[fill, a] = 0.0
    if out[["qty", "value"]].isna().any().any():
        raise ValueError("RMD 2.2: missing quantity or value with a non-zero counterpart")
    out["qty"] = out["qty"] * 1e3        # thousand units -> units
    out["value"] = out["value"] * 1e9    # R$ bn -> R$
    out["group"] = out["title"].map(group_of)
    if out["group"].isna().any():
        raise ValueError(f"RMD 2.2: unmapped titles {sorted(out.loc[out.group.isna(), 'title'].unique())}")
    return out


def read_realized_redemptions(xls: pd.ExcelFile) -> pd.DataFrame:
    """RMD 1.3 'Resgates - Vencimentos' by title (R$), month t (realized, contemporaneous)."""
    d = xls.parse("1.3", header=None)
    labels = d.iloc[:, 0].fillna("").astype(str).str.strip()
    start = labels[labels.eq("II - RESGATES")].index[0]
    venc = labels[(labels.index > start) & labels.eq("Vencimentos")].index[0]
    rows = []
    i = venc + 1
    while i < len(d) and labels[i] not in ("nan", ""):
        rows.append(i)
        i += 1
    months = [pt_month(v) for v in d.iloc[4, 1:]]
    keep = [j + 1 for j, m in enumerate(months) if m is not None]
    out = d.loc[rows, keep].T.astype(float) * 1e6
    out.columns = labels[rows].values
    out.index = pd.DatetimeIndex([months[j - 1] for j in keep], name="month")
    res = pd.DataFrame(index=out.index)
    res["N"] = out["LTN"] + out["NTN-F"]
    res["F"] = out["LFT"]
    res["R"] = out["NTN-B"]
    res["C"] = out["NTN-C"]
    res["other"] = out.drop(columns=["LTN", "NTN-F", "LFT", "NTN-B", "NTN-C"]).sum(axis=1)
    return res.sort_index()


def read_indexer_table(xls: pd.ExcelFile, sheet: str) -> pd.DataFrame:
    """RMD 3.3 / 2.4: month rows, value (R$ bn) and share for each indexer."""
    d = xls.parse(sheet, header=None)
    names = {1: "pre", 3: "price", 5: "float", 7: "fx", 9: "other", 11: "total"}
    is_row = d.iloc[:, 0].map(lambda v: isinstance(v, (pd.Timestamp, datetime)))
    t = d[is_row]
    out = pd.DataFrame(index=pd.DatetimeIndex(pd.to_datetime(t.iloc[:, 0]).values, name="month"))
    for j, n in names.items():
        out[f"{n}_brl"] = pd.to_numeric(t.iloc[:, j], errors="coerce").values * 1e9
        out[f"{n}_share"] = pd.to_numeric(t.iloc[:, j + 1], errors="coerce").values
    if out.index.duplicated().any():
        raise ValueError(f"RMD {sheet}: duplicated months")
    return out.sort_index()


def read_avg_maturity(xls: pd.ExcelFile) -> pd.Series:
    """RMD 3.7: DPF average maturity in years (row 'DPF')."""
    d = xls.parse("3.7", header=None)
    hdr_row = d.index[d.iloc[:, 1].map(lambda v: pt_month(v) is not None)][0]
    row = d.index[d.iloc[:, 0].astype(str).str.strip().eq("DPF")][0]
    vals = {}
    for j in range(1, d.shape[1]):
        m = pt_month(d.iat[hdr_row, j])
        if m is not None:
            vals[m] = pd.to_numeric(d.iat[row, j], errors="coerce")
    s = pd.Series(vals, name="avg_maturity_dpf_years_rmd").sort_index()
    s.index.name = "month"
    return s


# ---------------------------------------------------------------- IGP-M
def load_igpm(offline: bool, audit: list[dict]) -> pd.Series:
    """SGS 189 (IGP-M, % m/m). Raw pull saved with UTC timestamp, never overwritten."""
    BCB_RAW_DIR.mkdir(parents=True, exist_ok=True)
    saved = sorted(BCB_RAW_DIR.glob(f"sgs_{IGPM_SGS}_*.csv"))
    if offline:
        if not saved:
            raise FileNotFoundError(f"--offline but no saved SGS {IGPM_SGS} pull in {rel(BCB_RAW_DIR)}")
        path = saved[-1]
    else:
        import requests

        r = requests.get(SGS_URL.format(code=IGPM_SGS), params={"formato": "json"}, timeout=60)
        r.raise_for_status()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = BCB_RAW_DIR / f"sgs_{IGPM_SGS}_{stamp}.csv"
        pd.DataFrame(r.json()).to_csv(path, index=False)
    raw = pd.read_csv(path, dtype=str)
    s = pd.Series(pd.to_numeric(raw["valor"].str.replace(",", ".", regex=False), errors="coerce").values,
                  index=pd.to_datetime(raw["data"], format="%d/%m/%Y"), name="igpm_mom_pct")
    audit.append({"item": f"SGS {IGPM_SGS} IGP-M % m/m", "file": rel(path), "sha256": sha256(path),
                  "first": str(s.index.min().date()), "last": str(s.index.max().date())})
    return s.sort_index()


def index_from_changes(pct: pd.Series) -> pd.Series:
    return (1 + pct / 100).cumprod()


# ---------------------------------------------------------------- schedule
def coupon_months(maturity: pd.Timestamp) -> set[int]:
    m = maturity.month
    return {m, (m + 6 - 1) % 12 + 1}


def build_schedule(sec: pd.DataFrame, ipca_idx: pd.Series, igpm_idx: pd.Series) -> pd.DataFrame:
    """Debt service due in t from the stock at the end of t-1 (R$), by class."""
    s = sec.copy()
    s["due_month"] = s["month"] + pd.offsets.MonthBegin(1)
    s["mat_month"] = s["maturity"].dt.to_period("M").dt.to_timestamp()
    s = s[s["mat_month"] >= s["due_month"]]  # still outstanding in t

    s["principal"] = np.where(s["mat_month"].eq(s["due_month"]), s["value"], 0.0)

    lag2 = s["due_month"] - pd.DateOffset(months=2)
    vna_b = 1000 * ipca_idx.reindex(lag2).values / ipca_idx.loc[VNA_BASE]
    vna_c = 1000 * igpm_idx.reindex(lag2).values / igpm_idx.loc[VNA_BASE]
    pays = np.array([d.month in coupon_months(m) for d, m in zip(s["due_month"], s["maturity"])])
    per_bond = np.zeros(len(s))
    is_f = s["title"].eq("NTN-F").values
    is_b = s["title"].eq("NTN-B").values
    is_c = s["title"].eq("NTN-C").values
    jan_jul = s["due_month"].dt.month.isin([1, 7]).values
    per_bond[is_f & jan_jul] = NTNF_COUPON
    per_bond[is_b & pays] = vna_b[is_b & pays] * NTNB_RATE
    c_rate = np.where(s["maturity"].dt.year.eq(2031), 1.12 ** 0.5 - 1, 1.06 ** 0.5 - 1)
    per_bond[is_c & pays] = vna_c[is_c & pays] * c_rate[is_c & pays]
    s["coupon"] = s["qty"].values * per_bond
    if s["coupon"].isna().any():
        raise ValueError("Missing VNA for coupon computation (index series too short?)")

    months = pd.DatetimeIndex(sorted(s["due_month"].unique()), name="month")
    prin = s.pivot_table(index="due_month", columns="group", values="principal", aggfunc="sum")
    coup = s.pivot_table(index="due_month", columns="group", values="coupon", aggfunc="sum")
    out = pd.DataFrame(index=months)
    for g in GROUPS:
        out[f"principal_{g}"] = prin.get(g, pd.Series(dtype=float)).reindex(months).fillna(0.0)
        out[f"coupon_{g}"] = coup.get(g, pd.Series(dtype=float)).reindex(months).fillna(0.0)
        out[f"total_{g}"] = out[f"principal_{g}"] + out[f"coupon_{g}"]
    return out


# ---------------------------------------------------------------- helpers
def coverage_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for c in df.columns:
        s = pd.to_numeric(df[c], errors="coerce").dropna()
        rows.append({"variable": c, "n_obs": len(s),
                     "first_month": s.index.min().strftime("%Y-%m") if len(s) else None,
                     "last_month": s.index.max().strftime("%Y-%m") if len(s) else None,
                     "mean": s.mean() if len(s) else np.nan, "min": s.min() if len(s) else np.nan,
                     "max": s.max() if len(s) else np.nan})
    return pd.DataFrame(rows)


def plot_outputs(out: pd.DataFrame, realized: pd.DataFrame) -> None:
    d = out.loc["2006-01":]
    fig, axes = plt.subplots(3, 1, figsize=(10, 10), sharex=True)
    for g, lab in [("N", "N"), ("F", "F"), ("R", "R")]:
        axes[0].plot(d.index, d[f"maturity_{g}_sched_brl"] / 1e9, lw=0.9, label=lab)
    axes[0].axvline(pd.Timestamp("2010-02-01"), color="grey", ls=":", lw=0.8)
    axes[0].set_title("Vencimentos programados em t (principal + cupons, R$ bi); "
                      "antes da linha: realizados RMD 1.3")
    axes[0].legend(fontsize=8)
    r = realized.loc["2010-02":]
    tot_s = d.loc["2010-02":, ["maturity_N_sched_brl", "maturity_F_sched_brl", "maturity_R_sched_brl"]].sum(axis=1, min_count=3)
    axes[1].plot(r.index, r[["N", "F", "R"]].sum(axis=1) / 1e9, lw=1.6, color="0.7", label="realizado (RMD 1.3)")
    axes[1].plot(tot_s.index, tot_s / 1e9, lw=0.8, color="C3", label="programado em t-1 (RMD 2.2)")
    axes[1].set_title("N+F+R: programado versus realizado (R$ bi)")
    axes[1].legend(fontsize=8)
    for v, lab in [("rmd", "composição DPF (RMD 2.4)"), ("hist", "N+F+R"), ("hist_mkt", "total em mercado")]:
        axes[2].plot(d.index, d[f"paf_gap_R_{v}_lag1"], lw=0.9, label=lab)
    axes[2].axhline(0, color="k", lw=0.5)
    axes[2].set_title("Gap do PAF, índices de preços (participação em t-1 menos centro da banda)")
    axes[2].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "maturity_paf_hist.png", dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- main
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="use newest saved SGS 189 pull")
    args = parser.parse_args()
    for d in (INTERMEDIATE_DIR, CLEAN_DIR, DIAGNOSTICS_DIR, FIGURES_DIR):
        d.mkdir(parents=True, exist_ok=True)

    panel = pd.read_csv(INPUT_PANEL)
    panel["month"] = pd.to_datetime(panel["month"])
    print(f"Input panel: {rel(INPUT_PANEL)} {panel.shape}")
    audit = [{"item": "RMD annex (May 2026)", "file": rel(RMD_FILE), "sha256": sha256(RMD_FILE),
              "first": "", "last": ""}]

    xls = pd.ExcelFile(RMD_FILE)
    sec = read_security_stock(xls)
    realized = read_realized_redemptions(xls)
    mat12 = read_indexer_table(xls, "3.3")
    comp = read_indexer_table(xls, "2.4")
    avgmat = read_avg_maturity(xls)

    ipca_idx = panel.set_index("month")["ipca_index"].dropna()
    igpm_idx = index_from_changes(load_igpm(args.offline, audit))
    sched = build_schedule(sec, ipca_idx, igpm_idx)

    # ---------------- validation
    checks = []

    def check(name, value, ok, note=""):
        checks.append({"check": name, "value": value, "status": "PASS" if ok else "FAIL", "note": note})

    ov = sched.index.intersection(realized.index)
    for g in GROUPS:
        a, b = sched.loc[ov, f"total_{g}"], realized.loc[ov, g]
        check(f"schedule vs realized 1.3, class {g}: corr", round(float(a.corr(b)), 4), True,
              f"n={len(ov)}, {ov.min():%Y-%m}..{ov.max():%Y-%m}")
        check(f"schedule vs realized 1.3, class {g}: mean |gap| / mean realized",
              round(float((a - b).abs().mean() / b.mean()), 4), True)
    tot_a = sched.loc[ov, ["total_N", "total_F", "total_R"]].sum(axis=1)
    tot_b = realized.loc[ov, ["N", "F", "R"]].sum(axis=1)
    rg = float((tot_a - tot_b).abs().mean() / tot_b.mean())
    check("schedule vs realized 1.3, N+F+R: mean |gap| / mean realized", round(rg, 4),
          rg <= MAX_ABS_REL_GAP_TOTAL, f"tolerance {MAX_ABS_REL_GAP_TOTAL}")
    check("schedule vs realized 1.3, N+F+R: corr", round(float(tot_a.corr(tot_b)), 4), True)
    ltn = sec[sec.title.eq("LTN")].copy()
    ltn["due"] = ltn["month"] + pd.offsets.MonthBegin(1)
    ltn = ltn[ltn["maturity"].dt.to_period("M").dt.to_timestamp().eq(ltn["due"])].groupby("due")["value"].sum()

    proxy = pd.read_csv(PROXY_FILE, parse_dates=["month"]).set_index("month")
    pv = proxy.index.intersection(sched.index)
    worst = 0.0
    for g in ["N", "F", "R"]:
        p = proxy.loc[pv, f"maturity_{g}_t_given_tminus1_brl"]
        q = sched.loc[pv, f"principal_{g}"]
        m = p > 0
        gap = float(((q[m] - p[m]).abs() / p[m]).max()) if m.any() else 0.0
        zero_mismatch = int(((p == 0) != (q.abs() < 1)).sum())
        worst = max(worst, gap)
        check(f"principal (RMD 2.2) vs eDPF proxy, class {g}: max rel gap", round(gap, 5),
              gap <= MAX_PROXY_REL_GAP and zero_mismatch == 0,
              f"n={len(pv)} proxy months; months with maturity in one source only: {zero_mismatch}")
    s33 = mat12.loc["2010-01":, "pre_brl"]
    s22 = []
    for m in s33.index:
        x = sec[(sec.month == m) & (sec.group == "N")]
        s22.append(x.loc[x.maturity <= m + pd.DateOffset(months=12), "value"].sum())
    s22 = pd.Series(s22, index=s33.index)
    check("RMD 3.3 pre-fixed 12m vs principal maturing in 12m from 2.2: corr",
          round(float(s33.corr(s22)), 4), True, "3.3 also includes NTN-F coupons")

    checks_df = pd.DataFrame(checks)
    checks_df.to_csv(DIAGNOSTICS_DIR / "maturity_paf_hist_validation.csv", index=False)
    if (checks_df.status == "FAIL").any():
        print(checks_df.to_string(index=False))
        raise SystemExit("Validation failed; nothing written to the panel.")

    # ---------------- monthly output frame
    months = pd.DatetimeIndex(panel["month"])
    out = pd.DataFrame(index=months)
    out.index.name = "month"
    sched_r = sched.reindex(months)
    real_r = realized.reindex(months)
    use_real = (months >= realized.index.min()) & (months < sched.index.min())
    for g in GROUPS:
        col = f"maturity_{g}_sched_brl"
        out[col] = sched_r[f"total_{g}"]
        out.loc[use_real, col] = real_r.loc[use_real, g]
        out[f"maturity_{g}_sched_principal_brl"] = sched_r[f"principal_{g}"]
        out[f"maturity_{g}_sched_coupon_brl"] = sched_r[f"coupon_{g}"]
        out[f"maturity_{g}_realized_rmd_brl"] = real_r[g]
    out["maturity_Ramp_sched_brl"] = out["maturity_R_sched_brl"] + out["maturity_C_sched_brl"]
    out["maturity_total_NFR_sched_brl"] = out[[f"maturity_{g}_sched_brl" for g in "NFR"]].sum(axis=1, min_count=3)
    out["maturity_sched_source"] = np.select(
        [months.isin(sched.index), use_real], ["rmd_2.2_predetermined", "rmd_1.3_realized"], default="")

    pib = panel.set_index("month")["pib_12m_lag1_brl"].reindex(months)
    for g in ["N", "F", "R", "Ramp", "total_NFR"]:
        out[f"maturity_{g}_sched_pib_lag1"] = out[f"maturity_{g}_sched_brl"] / pib

    m12 = mat12.reindex(months - pd.offsets.MonthBegin(1))
    m12.index = months
    for src, g in [("pre", "N"), ("float", "F"), ("price", "Ramp"), ("total", "total")]:
        out[f"maturity12m_{g}_rmd_brl_lag1"] = m12[f"{src}_brl"]
        out[f"maturity12m_{g}_rmd_share_lag1"] = m12[f"{src}_share"]
    out["maturity12m_NFRamp_rmd_brl_lag1"] = out[[f"maturity12m_{g}_rmd_brl_lag1" for g in ["N", "F", "Ramp"]]].sum(
        axis=1, min_count=3)
    out["maturity12m_total_rmd_pib_lag1"] = out["maturity12m_total_rmd_brl_lag1"] / pib

    c = comp.reindex(months - pd.offsets.MonthBegin(1))
    c.index = months
    for src, n in [("pre", "pre"), ("price", "price"), ("float", "float"), ("fx", "fx")]:
        out[f"share_{n}_dpf_rmd_lag1"] = c[f"{src}_share"]
    out["stock_dpf_rmd_brl_lag1"] = c["total_brl"]

    am = avgmat.reindex(months - pd.offsets.MonthBegin(1))
    out["avg_maturity_dpf_years_rmd_lag1"] = am.values

    p = panel.set_index("month").reindex(months)
    out["liquidity_reserve_over_maturity12m_rmd_lag1"] = (
        p["liquidity_reserve_brl_lag1"] / out["maturity12m_total_rmd_brl_lag1"])

    # ---------------- PAF gaps
    bands = {"N": ("paf_prefixado_min", "paf_prefixado_max"),
             "F": ("paf_selic_min", "paf_selic_max"),
             "R": ("paf_price_indexed_min", "paf_price_indexed_max"),
             "FX": ("paf_fx_min", "paf_fx_max")}
    shares = {
        "hist": {g: p[f"share_{g}_hist_lag1"] for g in "NFR"},
        "hist_mkt": {g: p[f"share_{g}_hist_mkt_lag1"] for g in "NFR"},
        "rmd": {"N": out["share_pre_dpf_rmd_lag1"], "F": out["share_float_dpf_rmd_lag1"],
                "R": out["share_price_dpf_rmd_lag1"], "FX": out["share_fx_dpf_rmd_lag1"]},
    }
    for v, by_g in shares.items():
        for g, sh in by_g.items():
            lo, hi = p[bands[g][0]], p[bands[g][1]]
            target = (lo + hi) / 2
            out[f"paf_gap_{g}_{v}_lag1"] = sh - target
            out[f"paf_dist_{g}_to_lower_{v}_lag1"] = sh - lo
            out[f"paf_dist_{g}_to_upper_{v}_lag1"] = hi - sh
            out[f"paf_{g}_below_band_{v}_lag1"] = (sh < lo).astype(float).where(lo.notna() & sh.notna())
            out[f"paf_{g}_above_band_{v}_lag1"] = (sh > hi).astype(float).where(hi.notna() & sh.notna())
    out["paf_gap_maturing_12m_rmd_lag1"] = out["maturity12m_total_rmd_share_lag1"] - p["paf_maturing_12m_target"]
    out["paf_gap_avg_maturity_rmd_lag1"] = out["avg_maturity_dpf_years_rmd_lag1"] - p["paf_avg_maturity_target"]

    # Old-vs-new PAF gap consistency in the eDPF period (hist == eDPF shares there)
    both = p[["paf_gap_R_lag1"]].join(out[["paf_gap_R_hist_lag1"]]).dropna()
    d_old = float((both.iloc[:, 0] - both.iloc[:, 1]).abs().max()) if len(both) else np.nan
    checks_df = pd.concat([checks_df, pd.DataFrame([{
        "check": "paf_gap_R_hist_lag1 equals existing paf_gap_R_lag1 where both exist (max abs diff)",
        "value": d_old, "status": "PASS" if (np.isnan(d_old) or d_old < 1e-9) else "FAIL",
        "note": f"n={len(both)}"}])], ignore_index=True)
    checks_df.to_csv(DIAGNOSTICS_DIR / "maturity_paf_hist_validation.csv", index=False)
    if (checks_df.status == "FAIL").any():
        print(checks_df.to_string(index=False))
        raise SystemExit("Validation failed; nothing written to the panel.")

    # ---------------- write
    clash = [col for col in out.columns if col in panel.columns]
    if clash:
        raise ValueError(f"Columns already in input panel: {clash}")
    merged = panel.merge(out.reset_index(), on="month", how="left", validate="1:1")
    assert len(merged) == len(panel)
    merged["month"] = merged["month"].dt.strftime("%Y-%m-%d")
    merged.to_csv(OUTPUT_PANEL, index=False)

    sec_out = sec.copy()
    sec_out["month"] = sec_out["month"].dt.strftime("%Y-%m-%d")
    sec_out["maturity"] = sec_out["maturity"].dt.strftime("%Y-%m-%d")
    sec_out.to_csv(INTERMEDIATE_DIR / "rmd_security_stock_monthly.csv", index=False)
    sch = sched.copy()
    sch.index = sch.index.strftime("%Y-%m-%d")
    sch.to_csv(INTERMEDIATE_DIR / "maturity_schedule_rmd_monthly.csv", index_label="month")
    rl = realized.copy()
    rl.index = rl.index.strftime("%Y-%m-%d")
    rl.to_csv(INTERMEDIATE_DIR / "realized_redemptions_rmd_monthly.csv", index_label="month")

    num = out.drop(columns=["maturity_sched_source"])
    cov = coverage_table(num)
    cov.to_csv(DIAGNOSTICS_DIR / "maturity_paf_hist_diagnostics.csv", index=False)
    pd.DataFrame(audit).to_csv(DIAGNOSTICS_DIR / "maturity_paf_hist_audit.csv", index=False)
    lists = {
        "maturity_controls_base": ["maturity_N_sched_pib_lag1", "maturity_F_sched_pib_lag1",
                                   "maturity_R_sched_pib_lag1", "maturity12m_total_rmd_pib_lag1"],
        "maturity_controls_robustness_Ramp": ["maturity_Ramp_sched_pib_lag1"],
        "paf_controls_base_rmd": ["paf_gap_N_rmd_lag1", "paf_gap_F_rmd_lag1", "paf_gap_R_rmd_lag1",
                                  "paf_gap_maturing_12m_rmd_lag1", "paf_gap_avg_maturity_rmd_lag1"],
        "paf_controls_hist": [f"paf_gap_{g}_hist_lag1" for g in "NFR"],
        "paf_controls_hist_mkt": [f"paf_gap_{g}_hist_mkt_lag1" for g in "NFR"],
        "notes": [
            "maturity_{g}_sched_brl is due in t and known at the end of t-1 (predetermined); "
            "2006-11..2010-01 uses realized RMD 1.3 redemptions (maturity_sched_source).",
            "maturity_{g}_realized_rmd_brl is realized in t (contemporaneous) - validation only.",
            "PAF bands are written for the DPF composition (RMD 2.4); the rmd version is the "
            "conceptually matching one, hist/hist_mkt are robustness.",
            "paf_gap_maturing_12m_rmd uses the DPMFi share maturing in 12m (RMD 3.3), not DPF.",
        ],
    }
    (DIAGNOSTICS_DIR / "maturity_paf_hist_lists.json").write_text(
        json.dumps(lists, indent=2, ensure_ascii=False), encoding="utf-8")
    plot_outputs(out, realized)

    print(f"Wrote {rel(OUTPUT_PANEL)} {merged.shape} (+{out.shape[1]} columns)")
    print("\nValidation:")
    print(checks_df.to_string(index=False))
    print("\nCoverage (selected):")
    sel = cov[cov.variable.str.match(r"maturity_(N|F|R)_sched_brl|maturity12m_total|paf_gap_.*_(rmd|hist)_lag1|avg_mat")]
    print(sel[["variable", "first_month", "last_month", "n_obs"]].to_string(index=False))


if __name__ == "__main__":
    main()
