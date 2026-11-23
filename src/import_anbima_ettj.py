#!/usr/bin/env python3
"""Import an ANBIMA ETTJ spreadsheet into the Etapa B input format.

Input: the workbook delivered by coauthor João (default
``DadosJoao/data/data_yields.xlsx``), with daily ANBIMA zero-coupon curves
(ETTJ) exported for another project. The coauthor confirmed the source is the
ANBIMA ETTJ; the original ANBIMA files are not available. Sheets:

- ``yields_nominal`` / ``yields_real`` / ``BEIR``: columns ``ID``, ``DATA`` and
  the vertices 63, 126, 252, 504, 756, 1260, 1764, 2520 business days (headers
  are computed floats such as 125.99999999999999); rates in decimals.
- ``fatores``: daily Svensson parameters (beta1-beta4, lambda1, lambda2) of the
  nominal and real curves.

Steps:

1. Preserve the workbook untouched in ``data/raw/anbima/original/`` as
   ``<stem>__sha256_<first 12 hex>.xlsx`` (never overwritten; an identical copy is
   reused) and read only that copy.
2. Parse dates: most are Excel dates, but 258 cells (2023-04-10 to 2024-05-27 in
   the first delivery) are text ``DD/MM/YYYY``; they are parsed day-first. A
   generic reader would read them month-first (duplicates, weekends, wrong order).
3. Validate: the eight target vertices, identical dates in all sheets, strictly
   increasing business days, no missing values, ``BEIR == nominal - real``,
   Svensson reconstruction of the yields from the parameters (t = du/252), and,
   if the Zenodo package is present, the 1y nominal vertex against the ANBIMA
   1y LTN rate (Ipeadata).
4. Write the PRE and IPCA curves in the Etapa B long format (rates in %) to
   ``data/raw/anbima/anbima_ettj_daily_long.csv`` (derived file, rebuilt on each
   import), which ``build_anbima_yield_curve_controls.py`` reads as a local file.
   BEI is not written: Etapa B computes it as PRE - IPCA, which equals the
   delivered BEIR exactly. The 3m and 6m vertices of the real curve are flagged
   in ``notes``: without short NTN-B they are extrapolations of the fitted curve
   and take extreme values (e.g. 64.6% at 3m) in 2013-2021.
5. Save the daily Svensson parameters to
   ``data/intermediate/anbima/anbima_ettj_svensson_params_daily.csv`` and the audit
   and validation tables to ``data/diagnostics/``.

Run from the project root:  python3 src/import_anbima_ettj.py [--source PATH]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import shutil
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
RAW_DIR = DATA_DIR / "raw" / "anbima"
ORIGINAL_DIR = RAW_DIR / "original"
OUTPUT_LONG = RAW_DIR / "anbima_ettj_daily_long.csv"
INTERMEDIATE_DIR = DATA_DIR / "intermediate" / "anbima"
DIAGNOSTICS_DIR = DATA_DIR / "diagnostics"
ZENODO_LTN12 = DATA_DIR / "raw" / "zenodo_24206681_fiscal_svar" / "fiscal_svar" / "data" / "raw" / "ltn12.csv"
DEFAULT_SOURCE = PROJECT_ROOT / "DadosJoao" / "data" / "data_yields.xlsx"

VERTICES = [63, 126, 252, 504, 756, 1260, 1764, 2520]
CURVE_SHEETS = {"PRE": "yields_nominal", "IPCA": "yields_real"}
SHORT_REAL_VERTICES = [63, 126]
SOURCE_LABEL = ("ANBIMA ETTJ (curva zero-cupom), exportação diária enviada pelo coautor João; "
                "fonte confirmada pelo coautor, arquivo original da ANBIMA indisponível")
MAX_RECONSTRUCTION_ERROR = 1e-10


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preserve(source: Path) -> tuple[Path, str, str]:
    """Copy the workbook once to data/raw/anbima/original/, named by content hash."""
    ORIGINAL_DIR.mkdir(parents=True, exist_ok=True)
    digest = sha256(source)
    target = ORIGINAL_DIR / f"{source.stem}__sha256_{digest[:12]}{source.suffix}"
    if target.exists():
        if sha256(target) != digest:
            raise RuntimeError(f"{rel(target)} exists with different content; refusing to overwrite")
        action = "already preserved (identical sha256); copy reused"
    else:
        shutil.copy2(source, target)
        if sha256(target) != digest:
            raise RuntimeError("copy verification failed")
        action = "copied (sha256 verified)"
    return target, digest, action


def fix_date(value) -> pd.Timestamp:
    if isinstance(value, (dt.datetime, pd.Timestamp)):
        return pd.Timestamp(value).normalize()
    return pd.to_datetime(str(value).strip(), format="%d/%m/%Y")


def read_curve_sheet(path: Path, sheet: str) -> tuple[pd.DataFrame, int]:
    d = pd.read_excel(path, sheet_name=sheet, header=0)
    rename = {}
    for c in d.columns:
        if isinstance(c, (int, float)) and not pd.isna(c) and abs(c - round(c)) < 1e-6 and round(c) in VERTICES:
            rename[c] = int(round(c))
    d = d.rename(columns=rename)
    missing = [v for v in VERTICES if v not in d.columns]
    if missing or "DATA" not in d.columns:
        raise ValueError(f"{sheet}: missing columns {missing or 'DATA'}")
    d = d[d["DATA"].notna()]
    n_text = int(d["DATA"].map(lambda v: isinstance(v, str)).sum())
    d.index = pd.DatetimeIndex(d["DATA"].map(fix_date), name="date")
    return d[VERTICES].astype(float), n_text


def read_params(path: Path) -> pd.DataFrame:
    d = pd.read_excel(path, sheet_name="fatores", header=None, skiprows=2).iloc[:, 1:14]
    d.columns = ["date"] + [f"{c}_{k}" for c in ("pre", "ipca") for k in ("b1", "b2", "b3", "b4", "l1", "l2")]
    d = d[d["date"].notna()]
    d.index = pd.DatetimeIndex(d.pop("date").map(fix_date), name="date")
    return d.astype(float)


def svensson(params: pd.DataFrame, curve: str, du: list[int]) -> pd.DataFrame:
    b1, b2, b3, b4, l1, l2 = (params[f"{curve}_{k}"].to_numpy()[:, None] for k in ("b1", "b2", "b3", "b4", "l1", "l2"))
    t = np.asarray(du, dtype=float)[None, :] / 252
    f1 = (1 - np.exp(-l1 * t)) / (l1 * t)
    y = b1 + b2 * f1 + b3 * (f1 - np.exp(-l1 * t)) + b4 * ((1 - np.exp(-l2 * t)) / (l2 * t) - np.exp(-l2 * t))
    return pd.DataFrame(y, index=params.index, columns=du)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="ETTJ workbook to import")
    args = parser.parse_args()
    for d in (RAW_DIR, INTERMEDIATE_DIR, DIAGNOSTICS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    source = args.source.resolve()
    if not source.exists():
        raise FileNotFoundError(source)

    preserved, digest, action = preserve(source)
    print(f"Original: {rel(source)} -> {rel(preserved)} ({action})")

    curves, n_text = {}, {}
    for curve, sheet in CURVE_SHEETS.items():
        curves[curve], n_text[sheet] = read_curve_sheet(preserved, sheet)
    beir, n_text["BEIR"] = read_curve_sheet(preserved, "BEIR")
    params = read_params(preserved)
    pre, ipca = curves["PRE"], curves["IPCA"]
    idx = pre.index

    checks: list[dict] = []

    def check(name: str, value, ok: bool, note: str = "") -> None:
        checks.append({"check": name, "value": value, "status": "PASS" if ok else "FAIL", "note": note})

    check("text dates parsed day-first (per sheet)", str(n_text), True,
          "Excel dates elsewhere; text cells are DD/MM/YYYY")
    same = all(x.index.equals(idx) for x in (ipca, beir)) and params.index.equals(idx)
    check("identical dates in all sheets", same, same)
    check("dates strictly increasing", bool(idx.is_monotonic_increasing and idx.is_unique),
          bool(idx.is_monotonic_increasing and idx.is_unique))
    n_weekend = int((idx.dayofweek >= 5).sum())
    check("weekend dates", n_weekend, n_weekend == 0)
    max_gap = int(pd.Series(idx).diff().dt.days.max())
    check("max calendar gap between observations (days)", max_gap, max_gap <= 6, "holidays/Carnival give 4-5")
    n_nan = int(pre.isna().sum().sum() + ipca.isna().sum().sum() + params.isna().sum().sum())
    check("missing values in PRE, IPCA and parameters", n_nan, n_nan == 0)
    beir_gap = float((beir - (pre - ipca)).abs().max().max())
    check("max |BEIR - (nominal - real)|", beir_gap, beir_gap < 1e-12,
          "delivered BEIR is the simple difference, as in the project spec")
    for curve, y in (("pre", pre), ("ipca", ipca)):
        err = float((svensson(params, curve, VERTICES) - y).abs().max().max())
        check(f"max |Svensson(params) - {curve} yields| (t = du/252)", err, err < MAX_RECONSTRUCTION_ERROR)
    short = ipca[SHORT_REAL_VERTICES]
    n_extreme = int(((short < -0.03) | (short > 0.20)).sum().sum())
    check("real 3m/6m values outside [-3%, 20%]", n_extreme, True,
          "flagged in notes; use real and BEI vertices from 1y on")
    if ZENODO_LTN12.exists():
        z = pd.read_csv(ZENODO_LTN12)
        z = pd.Series(pd.to_numeric(z.iloc[:, 1], errors="coerce").to_numpy(),
                      index=pd.PeriodIndex(z.iloc[:, 0].astype(str), freq="M"))
        m = (pre[252] * 100).groupby(idx.to_period("M")).mean()
        j = pd.concat([m, z], axis=1, keys=["ettj", "ltn"]).dropna()
        gap = float((j.ettj - j.ltn).abs().mean())
        check("mean |PRE 1y monthly mean - ANBIMA LTN 1y (Ipeadata)| (pp)", round(gap, 4), gap < 0.25,
              f"n={len(j)}, corr={j.corr().iloc[0, 1]:.4f}")
    checks_df = pd.DataFrame(checks)
    checks_df.to_csv(DIAGNOSTICS_DIR / "anbima_ettj_import_validation.csv", index=False)
    if (checks_df.status == "FAIL").any():
        print(checks_df.to_string(index=False))
        raise RuntimeError("ETTJ import validation failed; Etapa B input not written")

    # --- long format for Etapa B ------------------------------------------------
    rows = []
    for curve, y in curves.items():
        long = y.stack().rename("yield_dec").reset_index()
        long.columns = ["date", "vertex_du", "yield_dec"]
        long["curve_type"] = curve
        long["yield_pct"] = long.pop("yield_dec") * 100
        rows.append(long)
    out = pd.concat(rows, ignore_index=True)
    out["source_document"] = preserved.name  # full description in anbima_ettj_import_audit.csv
    out["notes"] = "ettj"
    short_mask = (out.curve_type == "IPCA") & out.vertex_du.isin(SHORT_REAL_VERTICES)
    out.loc[short_mask, "notes"] = "ettj_real_short_unreliable"
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out = out[["date", "curve_type", "vertex_du", "yield_pct", "source_document", "notes"]]
    out = out.sort_values(["date", "curve_type", "vertex_du"])
    out.to_csv(OUTPUT_LONG, index=False)

    p = params.copy()
    p.index = p.index.strftime("%Y-%m-%d")
    p.to_csv(INTERMEDIATE_DIR / "anbima_ettj_svensson_params_daily.csv")

    audit = pd.DataFrame([{
        "source_file": rel(source), "preserved_file": rel(preserved), "sha256": digest, "action": action,
        "source_declared": SOURCE_LABEL, "first_date": idx.min().date(), "last_date": idx.max().date(),
        "n_dates": len(idx), "vertices_du": " ".join(map(str, VERTICES)),
        "output_long": rel(OUTPUT_LONG), "n_rows_long": len(out),
        "notes_codes": "ettj = ETTJ vertex, rate % p.a. (decimal x 100); ettj_real_short_unreliable = IPCA 3m/6m, "
                       "extrapolation of the fitted curve without short NTN-B, do not use",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }])
    audit.to_csv(DIAGNOSTICS_DIR / "anbima_ettj_import_audit.csv", index=False)

    print(f"Wrote {rel(OUTPUT_LONG)} ({len(out)} rows, {idx.min().date()} to {idx.max().date()}, "
          f"{len(idx)} business days)")
    print(checks_df.to_string(index=False))


if __name__ == "__main__":
    main()
