"""Auction take-up diagnostics: how much of monthly issuance is set by supply.

Reads the Treasury auction history (``data/raw/historico-leiloes-todos.xls``,
column "Oferta" = quantity tendered by the Treasury, "Venda" = quantity
accepted) and the latest panel. For first-round sale auctions (1.a volta) of
LTN/NTN-F (N), LFT (F) and NTN-B/NTN-B Principal (R).

Unit = lot. The file has one row per bond, and when several maturities of a
title share one lot the lot is repeated on each row. A group of bonds of the
same title, on the same day, with the same "Oferta" is treated as one joint
lot when their sales add up to at most the lot (sum = lot: clearly joint;
sum < lot: ambiguous, joint by default, separate in the robustness variant);
when the sales exceed the lot they are separate lots. Per-bond take-up
(sold/offer) understates the take-up of joint lots, so all statistics are
computed per lot. Statistics:

- take-up ratio = accepted / offered quantity, share of fully allotted
  auctions (ratio >= 0.999) and of auctions with nothing sold;
- monthly offered value (offer x unit price of the same auction) against
  accepted value;
- correlation of the monthly take-up ratio with same-month changes of asset
  prices (real 5y, LTN 1y, break-even 2y, BRL/USD, EMBI, Focus IPCA 12m);
- binding auctions (whole lot sold, offer is the active constraint): correlation
  of the monthly share of binding auctions with the same price changes, and
  persistence of the binding state across consecutive auctions of the same bond
  (title + maturity), i.e. whether it is predictable before the edital.

Writes data/diagnostics/auction_takeup_{by_class,by_year,monthly_corr,binding,
       lot_vs_bond,lot_types}.csv and
data/intermediate/auction_takeup/auction_takeup_monthly.csv. Exploratory; feeds
the identification discussion in DocumentacaoProjeto.tex (sec:ident).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def find_project_root() -> Path:
    for candidate in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (candidate / ".git").exists():
            return candidate
    return Path(__file__).resolve().parent


ROOT = find_project_root()
RAW = ROOT / "data" / "raw" / "historico-leiloes-todos.xls"
PANEL = ROOT / "data" / "clean" / "ftpl_monthly_panel_with_inflation_expectations.csv"
DIAG = ROOT / "data" / "diagnostics"
INTER = ROOT / "data" / "intermediate" / "auction_takeup"
COLS = ["date", "title", "type", "round", "settle", "maturity", "offer", "rate_avg",
        "rate_cut", "sold", "value_brl", "sold_bcb", "value_bcb_brl", "ref"]
CLASS = {"LTN": "N", "NTN-F": "N", "LFT": "F", "NTN-B": "R", "NTN-B Principal": "R"}
PRICES = {"real_5y": "real_yield_5y_pct", "ltn_1y": "ltn_1y_pct", "bei_2y": "bei_2y_pct",
          "fx_log": "brl_usd", "embi": "embi_spread_bp", "focus_ipca12m": "focus_ipca12m_pct"}


def load_auctions() -> pd.DataFrame:
    xl = pd.ExcelFile(RAW)
    frames = []
    for sh in xl.sheet_names:  # header in rows 6-7 (PT/EN); data from row 8
        d = xl.parse(sh, header=None, skiprows=7).iloc[:, 1:15]
        d.columns = COLS[: d.shape[1]]
        frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    d = d[d["type"].astype(str).str.strip().str.upper() == "VENDA"].copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    for c in ["offer", "sold", "value_brl"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["class"] = d["title"].astype(str).str.strip().map(CLASS)
    d = d[d["class"].notna() & d["date"].notna()]
    d = d[d["round"].astype(str).str.strip().str.startswith("1") & (d["offer"] > 0)].copy()
    d["takeup"] = d["sold"] / d["offer"]
    d["unit_price"] = d["value_brl"] / d["sold"]
    d["offer_brl"] = d["offer"] * d["unit_price"]
    return d


def load_lots(ambiguous_joint: bool = True, a: pd.DataFrame | None = None) -> pd.DataFrame:
    """Collapse bond rows into lots (see module docstring)."""
    a = load_auctions() if a is None else a
    a = a.copy()
    a["title"] = a["title"].astype(str).str.strip()
    a["maturity"] = pd.to_datetime(a["maturity"], errors="coerce")
    a["bond"] = a["title"] + "|" + a["maturity"].dt.strftime("%Y-%m-%d")
    key = ["date", "title", "offer"]
    grp = a.groupby(key)
    a["n_same_offer"] = grp["bond"].transform("size")
    a["sold_same_offer"] = grp["sold"].transform("sum")
    ratio = a["sold_same_offer"] / a["offer"]
    clear = (a["n_same_offer"] >= 2) & (ratio >= 0.999) & (ratio <= 1.001)
    ambiguous = (a["n_same_offer"] >= 2) & (ratio < 0.999)
    a["lot_type"] = np.select([clear, ambiguous], ["joint_clear", "joint_ambiguous"], "single")
    joint = clear | (ambiguous if ambiguous_joint else False)
    a["lot_id"] = np.where(joint, a["date"].dt.strftime("%Y%m%d") + "|" + a["title"] + "|"
                           + a["offer"].astype(str), a["date"].dt.strftime("%Y%m%d") + "|" + a["bond"])
    lots = (a.groupby("lot_id", sort=False)
            .agg(date=("date", "first"), title=("title", "first"), **{"class": ("class", "first")},
                 lot_type=("lot_type", "first"), n_bonds=("bond", "size"),
                 bonds=("bond", lambda x: ";".join(sorted(x))), offer=("offer", "first"),
                 sold=("sold", "sum"), value_brl=("value_brl", "sum"),
                 maturity=("maturity", "mean"))
            .reset_index())
    if not ambiguous_joint:
        lots.loc[lots["lot_type"] == "joint_ambiguous", "lot_type"] = "single"
    lots["takeup"] = lots["sold"] / lots["offer"]
    lots["unit_price"] = lots["value_brl"] / lots["sold"].where(lots["sold"] > 0)
    lots["offer_brl"] = lots["offer"] * lots["unit_price"]
    lots["binding"] = (lots["takeup"] >= 0.999).astype(float)
    lots["lot_key"] = lots["title"] + "|" + lots["bonds"]
    return lots.sort_values(["date", "lot_id"]).reset_index(drop=True)


def main() -> None:
    DIAG.mkdir(parents=True, exist_ok=True)
    INTER.mkdir(parents=True, exist_ok=True)
    bonds = load_auctions()
    a = load_lots(True, bonds)
    a_sep = load_lots(False, bonds)

    # bond-level vs lot-level take-up (the bond-level view understates joint lots)
    cmp_rows = []
    for name, df, col in [("bond_rows", bonds, "takeup"), ("lots_ambiguous_joint", a, "takeup"),
                          ("lots_ambiguous_separate", a_sep, "takeup")]:
        dd = df[df["date"] >= "2006-11-01"]
        for c in "NFR":
            x = dd.loc[dd["class"] == c, col]
            cmp_rows.append({"unit": name, "class": c, "n": len(x), "share_full": (x >= 0.999).mean(),
                             "takeup_median": x.median(), "takeup_mean": x.mean()})
    lt = a[a["date"] >= "2006-11-01"].groupby(["class", "lot_type"]).size().unstack(fill_value=0)
    pd.DataFrame(cmp_rows).to_csv(DIAG / "auction_takeup_lot_vs_bond.csv", index=False)
    lt.to_csv(DIAG / "auction_takeup_lot_types.csv")

    by_class = a.groupby("class").agg(
        n_auctions=("takeup", "size"), first=("date", "min"), last=("date", "max"),
        takeup_mean=("takeup", "mean"), takeup_median=("takeup", "median"),
        share_full=("takeup", lambda r: (r >= 0.999).mean()),
        share_zero=("takeup", lambda r: (r <= 0.001).mean()),
        share_above1=("takeup", lambda r: (r > 1.001).mean()))
    a2 = a[a["date"] >= "2006-11-01"]
    sub = a2.groupby("class").agg(takeup_median_2006m11=("takeup", "median"),
                                  share_full_2006m11=("takeup", lambda r: (r >= 0.999).mean()))
    by_class = by_class.join(sub)
    by_class.to_csv(DIAG / "auction_takeup_by_class.csv")

    a["year"] = a["date"].dt.year
    by_year = (a.groupby(["year", "class"])
               .agg(n=("takeup", "size"), takeup_median=("takeup", "median"),
                    share_full=("takeup", lambda r: (r >= 0.999).mean()))
               .unstack("class"))
    by_year.columns = [f"{s}_{c}" for s, c in by_year.columns]
    by_year.to_csv(DIAG / "auction_takeup_by_year.csv")

    m = (a.assign(month=a["date"].dt.to_period("M").dt.to_timestamp())
         .groupby(["month", "class"])[["offer_brl", "value_brl"]].sum().unstack("class"))
    m.columns = [f"{s}_{c}" for s, c in m.columns]
    for c in "NFR":
        m[f"takeup_value_{c}"] = m[f"value_brl_{c}"] / m[f"offer_brl_{c}"]
    m.to_csv(INTER / "auction_takeup_monthly.csv")

    p = pd.read_csv(PANEL, parse_dates=["month"]).set_index("month")
    dp = pd.DataFrame({k: (100 * np.log(p[v]) if k == "fx_log" else p[v]).diff()
                       for k, v in PRICES.items()})
    rows = []
    for c in "NFR":
        j = pd.concat([m[[f"takeup_value_{c}", f"offer_brl_{c}", f"value_brl_{c}"]], dp], axis=1)
        j = j.loc["2006-11-01":"2025-02-01"]
        ok = j[[f"offer_brl_{c}", f"value_brl_{c}"]].notna().all(axis=1)
        row = {"class": c, "months": int(ok.sum()),
               "corr_offer_value_vs_sold_value": j.loc[ok, f"offer_brl_{c}"].corr(j.loc[ok, f"value_brl_{c}"]),
               "sold_over_offer_value": j.loc[ok, f"value_brl_{c}"].sum() / j.loc[ok, f"offer_brl_{c}"].sum()}
        for k in PRICES:
            row[f"corr_takeup_d_{k}"] = j[f"takeup_value_{c}"].corr(j[k])
        for k in PRICES:
            row[f"corr_offer_value_d_{k}"] = (j[f"offer_brl_{c}"] / p["pib_12m_lag1_brl"]).corr(j[k])
        rows.append(row)
    corr = pd.DataFrame(rows)
    corr.to_csv(DIAG / "auction_takeup_monthly_corr.csv", index=False)

    # binding auctions: selection on market conditions and predictability
    b = a[a["date"] >= "2006-11-01"].copy()
    b["binding"] = (b["takeup"] >= 0.999).astype(float)
    b["month"] = b["date"].dt.to_period("M").dt.to_timestamp()
    b = b.sort_values(["date"])
    b["binding_prev"] = b.groupby("lot_key")["binding"].shift()
    brows = []
    for c in "NFR":
        bc = b[b["class"] == c]
        share = bc.groupby("month")["binding"].mean().rename("share_binding")
        j = pd.concat([share, dp], axis=1).dropna().loc[:"2025-02-01"]
        prev = bc[bc["binding_prev"].notna()]
        row = {"class": c, "n_auctions": len(bc), "share_binding": bc["binding"].mean(),
               "months": len(j),
               "p_bind_given_prev_bind": prev.loc[prev["binding_prev"] == 1, "binding"].mean(),
               "p_bind_given_prev_not": prev.loc[prev["binding_prev"] == 0, "binding"].mean(),
               "n_with_prev": len(prev)}
        for k in PRICES:
            row[f"corr_share_binding_d_{k}"] = j["share_binding"].corr(j[k])
        brows.append(row)
    binding = pd.DataFrame(brows)
    binding.to_csv(DIAG / "auction_takeup_binding.csv", index=False)

    pd.set_option("display.width", 200)
    print(pd.DataFrame(cmp_rows).round(3).to_string(index=False))
    print(lt.to_string())
    print(by_class.round(3).to_string())
    print(corr.round(3).to_string(index=False))
    print(binding.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
