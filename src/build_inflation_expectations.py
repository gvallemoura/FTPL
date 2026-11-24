"""Focus 12-month-ahead IPCA expectations as a local-projection outcome.

Reads ``data/clean/ftpl_monthly_panel_with_purged_shocks.csv`` and writes
``data/clean/ftpl_monthly_panel_with_inflation_expectations.csv`` with:

- ``focus_ipca12m_pct``: monthly mean of the daily Focus median of IPCA
  inflation over the next 12 months (smoothed series, ``Suavizada = 'S'``,
  ``baseCalculo = 0``), the main outcome, comparable to the other monthly-mean
  valuation outcomes;
- ``focus_ipca12m_eom_pct``: last survey date of the month;
- ``focus_ipca12m_nonsmooth_pct``: non-smoothed series (``Suavizada = 'N'``),
  robustness;
- ``*_lag1`` versions, predetermined, for control sets.

Source: BCB Olinda, ``ExpectativasMercadoInflacao12Meses``. Each API pull is
saved as a new UTC-timestamped raw file and never overwrites earlier pulls;
``--offline`` reads the newest local raw file.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests


def find_project_root() -> Path:
    for candidate in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (candidate / ".git").exists():
            return candidate
    return Path(__file__).resolve().parent


PROJECT_ROOT = find_project_root()
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw" / "focus"
INTERMEDIATE_DIR = DATA_DIR / "intermediate" / "focus"
CLEAN_DIR = DATA_DIR / "clean"
DIAGNOSTICS_DIR = DATA_DIR / "diagnostics"

INPUT_PANEL = CLEAN_DIR / "ftpl_monthly_panel_with_purged_shocks.csv"
OUTPUT_PANEL = CLEAN_DIR / "ftpl_monthly_panel_with_inflation_expectations.csv"
OLINDA_URL = (
    "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
    "ExpectativasMercadoInflacao12Meses"
)
RAW_PREFIX = "focus_ipca12m"


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def fetch(page: int = 10000, tries: int = 3) -> pd.DataFrame:
    rows: list[dict] = []
    skip = 0
    while True:
        params = {
            "$filter": "Indicador eq 'IPCA' and baseCalculo eq 0",
            "$select": "Indicador,Data,Suavizada,Mediana,numeroRespondentes,baseCalculo",
            "$format": "json",
            "$top": str(page),
            "$skip": str(skip),
            "$orderby": "Data asc",
        }
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
        raise RuntimeError("Olinda returned no rows for IPCA 12m")
    return pd.DataFrame(rows)


def load(offline: bool) -> tuple[pd.DataFrame, dict]:
    source, path = None, None
    if not offline:
        try:
            print("Olinda API: IPCA 12 meses (baseCalculo=0)")
            df = fetch()
            path = RAW_DIR / f"{RAW_PREFIX}_{timestamp_utc()}.csv"
            df.to_csv(path, index=False)
            source = "BCB_OLINDA_API"
        except Exception as exc:  # noqa: BLE001
            print(f"   API failed ({exc}); falling back to local file")
    if source is None:
        files = sorted(RAW_DIR.glob(f"{RAW_PREFIX}_*.csv"))
        if not files:
            raise FileNotFoundError("no local Focus IPCA 12m raw file")
        path = files[-1]
        df = pd.read_csv(path)
        source = "BCB_OLINDA_API_SAVED"
    if not (pd.to_numeric(df["baseCalculo"]) == 0).all():
        raise ValueError("raw file mixes baseCalculo values")
    df["Data"] = pd.to_datetime(df["Data"])
    df["Mediana"] = pd.to_numeric(df["Mediana"], errors="coerce")
    meta = {"source": source, "source_url": OLINDA_URL, "source_file": rel(path),
            "n_rows_raw": len(df), "first_survey_date": df["Data"].min().date().isoformat(),
            "last_survey_date": df["Data"].max().date().isoformat(),
            "run_timestamp_utc": timestamp_utc()}
    return df.dropna(subset=["Mediana"]), meta


def monthly(df: pd.DataFrame) -> pd.DataFrame:
    out = {}
    for flag, name in [("S", "focus_ipca12m"), ("N", "focus_ipca12m_nonsmooth")]:
        s = (df[df["Suavizada"] == flag].drop_duplicates("Data")
             .set_index("Data")["Mediana"].sort_index())
        g = s.groupby(s.index.to_period("M"))
        out[f"{name}_pct"] = g.mean()
        out[f"{name}_eom_pct"] = g.last()
    m = pd.DataFrame(out)
    m.index = m.index.to_timestamp()
    m.index.name = "month"
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    for d in (RAW_DIR, INTERMEDIATE_DIR, DIAGNOSTICS_DIR):
        d.mkdir(parents=True, exist_ok=True)

    raw, meta = load(args.offline)
    m = monthly(raw)
    m.to_csv(INTERMEDIATE_DIR / "focus_ipca12m_monthly.csv")

    panel = pd.read_csv(INPUT_PANEL, parse_dates=["month"]).set_index("month")
    new = m.reindex(panel.index)
    for c in list(new.columns):
        new[f"{c}_lag1"] = new[c].shift(1)
    clash = [c for c in new.columns if c in panel.columns]
    if clash:
        raise ValueError(f"columns already in panel: {clash}")
    out = pd.concat([panel, new], axis=1).copy()
    out.reset_index().to_csv(OUTPUT_PANEL, index=False, date_format="%Y-%m-%d")

    s = m["focus_ipca12m_pct"].dropna()
    meta.update({"first_month": s.index.min().strftime("%Y-%m"),
                 "last_month": s.index.max().strftime("%Y-%m"),
                 "n_months": len(s),
                 "corr_smooth_vs_nonsmooth": round(
                     m[["focus_ipca12m_pct", "focus_ipca12m_nonsmooth_pct"]].corr().iloc[0, 1], 4),
                 "output_panel": rel(OUTPUT_PANEL), "output_shape": f"{out.shape[0]}x{out.shape[1] + 1}"})
    pd.DataFrame([meta]).to_csv(DIAGNOSTICS_DIR / "focus_ipca12m_audit.csv", index=False)
    print(pd.Series(meta).to_string())


if __name__ == "__main__":
    main()
