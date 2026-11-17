#!/usr/bin/env python3
"""Build ANBIMA yield-curve controls for the FTPL monthly panel.

The script is intentionally conservative. It never invents yield-curve data:
if the ANBIMA API is not configured and no local historical file is found, it
creates a manual-entry template, audit records, empty derived datasets, and a
monthly panel with the original observations preserved.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import requests


def find_project_root() -> Path:
    """Find the repository root from the script location or current directory."""
    candidates = [Path.cwd(), Path(__file__).resolve().parent]
    candidates.extend(Path(__file__).resolve().parents)
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    return Path(__file__).resolve().parent


PROJECT_ROOT = find_project_root()
DATA_DIR = PROJECT_ROOT / "data"
os.environ.setdefault("MPLCONFIGDIR", str(DATA_DIR / ".mplconfig"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

RAW_DIR = DATA_DIR / "raw" / "anbima"
RAW_API_DIR = RAW_DIR / "api"
INTERMEDIATE_DIR = DATA_DIR / "intermediate" / "anbima"
CLEAN_DIR = DATA_DIR / "clean"
DIAGNOSTICS_DIR = DATA_DIR / "diagnostics"
FIGURES_DIR = DATA_DIR / "figures"

API_DOC_URL = "https://developers.anbima.com.br/pt/apis/feed/precos-indices/titulos-publicos/"
DEFAULT_API_PATH = "/feed/precos-indices/v1/titulos-publicos/curva-intradiaria"

PANEL_CANDIDATES = [
    CLEAN_DIR / "ftpl_monthly_panel_structural_controls.csv",
    CLEAN_DIR / "ftpl_monthly_panel_with_pib_normalization.csv",
    PROJECT_ROOT / "data" / "clean" / "ftpl_monthly_panel_with_pib_normalization.csv",
    PROJECT_ROOT / "data" / "clean" / "ftpl_monthly_panel.csv",
]

TARGET_VERTICES = {
    "3m": 63,
    "6m": 126,
    "1y": 252,
    "2y": 504,
    "3y": 756,
    "5y": 1260,
    "7y": 1764,
    "10y": 2520,
}
CURVE_TYPES = ["PRE", "IPCA", "BEI"]
PCA_BLOCKS = {
    "pre": ["pre_1y", "pre_2y", "pre_3y", "pre_5y", "pre_7y", "pre_10y"],
    "ipca": ["ipca_1y", "ipca_2y", "ipca_3y", "ipca_5y", "ipca_7y", "ipca_10y"],
    "bei": ["bei_1y", "bei_2y", "bei_3y", "bei_5y", "bei_7y", "bei_10y"],
}
PCA_FULL_SAMPLE = True
PCA_EXPANDING_WINDOW = True
MIN_PCA_WINDOW = 60


@dataclass
class SourceResult:
    daily_long: pd.DataFrame
    audit: pd.DataFrame
    messages: list[str]


def ensure_directories() -> None:
    """Create the output directory tree used by this stage."""
    for directory in [RAW_DIR, RAW_API_DIR, INTERMEDIATE_DIR, CLEAN_DIR, DIAGNOSTICS_DIR, FIGURES_DIR]:
        directory.mkdir(parents=True, exist_ok=True)


def timestamp_utc() -> str:
    """Return an ISO UTC timestamp."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def project_path(path: Path | str) -> str:
    """Return a project-relative path when possible."""
    candidate = Path(path)
    try:
        return candidate.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except Exception:
        return candidate.as_posix()


def find_input_panel() -> Path:
    """Locate the most recent monthly panel candidate."""
    for path in PANEL_CANDIDATES:
        if path.exists():
            return path
    candidates = sorted(CLEAN_DIR.glob("*panel*.csv")) + sorted((PROJECT_ROOT / "clean").glob("*panel*.csv"))
    if candidates:
        return candidates[-1]
    raise FileNotFoundError("No monthly panel CSV found in data/clean.")


def standard_empty_daily_long() -> pd.DataFrame:
    """Return an empty daily curve dataset with the canonical columns."""
    return pd.DataFrame(
        columns=[
            "date",
            "curve_type",
            "vertex_du",
            "yield_pct",
            "source",
            "download_timestamp",
            "source_file",
            "interpolated",
        ]
    )


def standard_empty_audit() -> pd.DataFrame:
    """Return an empty audit dataset with the required columns."""
    return pd.DataFrame(
        columns=[
            "date",
            "curve_type",
            "source",
            "source_url",
            "source_file",
            "n_vertices_raw",
            "n_vertices_used",
            "interpolation_used",
            "download_timestamp",
            "notes",
        ]
    )


def normalize_text(value: Any) -> str:
    """Normalize text for loose column matching."""
    text = str(value).strip().lower()
    replacements = {
        "á": "a",
        "à": "a",
        "ã": "a",
        "â": "a",
        "é": "e",
        "ê": "e",
        "í": "i",
        "ó": "o",
        "õ": "o",
        "ô": "o",
        "ú": "u",
        "ç": "c",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def detect_column(columns: Iterable[str], patterns: Iterable[str]) -> str | None:
    """Find the first column whose normalized name matches any pattern."""
    normalized = {col: normalize_text(col) for col in columns}
    for pattern in patterns:
        rx = re.compile(pattern)
        for col, norm in normalized.items():
            if rx.search(norm):
                return col
    return None


def normalize_curve_type(value: Any) -> str | None:
    """Map source curve labels to PRE, IPCA, or BEI."""
    text = normalize_text(value)
    if not text or text == "nan":
        return None
    if any(token in text for token in ["pre", "prefix", "nominal", "ltn", "ntnf", "ntn_f"]):
        return "PRE"
    if any(token in text for token in ["ipca", "real", "ntnb", "ntn_b"]):
        return "IPCA"
    if any(token in text for token in ["bei", "breakeven", "implic", "inflacao"]):
        return "BEI"
    return None


def parse_numeric_series(series: pd.Series) -> pd.Series:
    """Parse numeric values, handling Brazilian decimal commas."""
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    cleaned = (
        series.astype(str)
        .str.strip()
        .str.replace("%", "", regex=False)
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
        .replace({"": np.nan, "nan": np.nan, "None": np.nan})
    )
    return pd.to_numeric(cleaned, errors="coerce")


def parse_date_series(series: pd.Series) -> pd.Series:
    """Parse dates with day-first support."""
    parsed = pd.to_datetime(series, errors="coerce", dayfirst=True)
    if parsed.notna().sum() == 0:
        parsed = pd.to_datetime(series, errors="coerce")
    return parsed.dt.normalize()


def create_manual_template(reason: str) -> Path:
    """Create a manual ANBIMA yield-curve template if it does not exist."""
    template = RAW_DIR / "anbima_yield_curve_manual_template.csv"
    if not template.exists():
        pd.DataFrame(
            columns=["date", "curve_type", "vertex_du", "yield_pct", "source_document", "notes"]
        ).to_csv(template, index=False)
    notes_path = RAW_DIR / "README_anbima_manual_template.txt"
    if not notes_path.exists():
        notes_path.write_text(
            "Template manual para curvas ANBIMA.\n"
            "Preencher uma linha por data, tipo de curva e vertice em dias uteis.\n"
            "curve_type deve ser PRE, IPCA ou BEI; yield_pct deve estar em percentual anual.\n"
            f"Motivo da criacao: {reason}\n",
            encoding="utf-8",
        )
    return template


def get_api_token(messages: list[str]) -> str | None:
    """Return an ANBIMA access token from env or OAuth client credentials."""
    token = os.getenv("ANBIMA_ACCESS_TOKEN")
    if token:
        messages.append("Using ANBIMA_ACCESS_TOKEN from environment.")
        return token
    client_id = os.getenv("ANBIMA_CLIENT_ID")
    client_secret = os.getenv("ANBIMA_CLIENT_SECRET")
    token_url = os.getenv("ANBIMA_TOKEN_URL")
    if not (client_id and client_secret and token_url):
        messages.append(
            "ANBIMA API credentials unavailable: set ANBIMA_ACCESS_TOKEN or "
            "ANBIMA_CLIENT_ID, ANBIMA_CLIENT_SECRET and ANBIMA_TOKEN_URL."
        )
        return None
    response = requests.post(
        token_url,
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    token = payload.get("access_token") or payload.get("token")
    if not token:
        raise ValueError("OAuth response did not contain access_token or token.")
    messages.append("Obtained ANBIMA OAuth token from ANBIMA_TOKEN_URL.")
    return token


def flatten_json_records(payload: Any) -> list[dict[str, Any]]:
    """Flatten common JSON response wrappers into a list of records."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ["data", "dados", "items", "curvas", "result", "results"]:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def parse_records_to_daily_long(records: list[dict[str, Any]], source: str, source_file: str) -> pd.DataFrame:
    """Parse list-of-dict records into canonical daily-long format."""
    if not records:
        return standard_empty_daily_long()
    df = pd.json_normalize(records)
    return parse_tabular_curve_file(df, source=source, source_file=source_file)


def fetch_from_anbima_api() -> SourceResult:
    """Try to fetch curves from the configured ANBIMA Developers API."""
    messages: list[str] = []
    audit = standard_empty_audit()
    downloaded_at = timestamp_utc()
    api_base = os.getenv("ANBIMA_API_BASE")
    api_path = os.getenv("ANBIMA_CURVA_INTRADIARIA_PATH", DEFAULT_API_PATH)
    if not api_base:
        messages.append("ANBIMA_API_BASE not configured; API path skipped.")
        audit.loc[len(audit)] = [
            pd.NaT,
            pd.NA,
            "API ANBIMA",
            API_DOC_URL,
            pd.NA,
            0,
            0,
            False,
            downloaded_at,
            "API not attempted because ANBIMA_API_BASE is not set.",
        ]
        return SourceResult(standard_empty_daily_long(), audit, messages)
    try:
        token = get_api_token(messages)
        if not token:
            audit.loc[len(audit)] = [
                pd.NaT,
                pd.NA,
                "API ANBIMA",
                API_DOC_URL,
                pd.NA,
                0,
                0,
                False,
                downloaded_at,
                "API not attempted because credentials are unavailable.",
            ]
            return SourceResult(standard_empty_daily_long(), audit, messages)
        url = api_base.rstrip("/") + "/" + api_path.lstrip("/")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        response = requests.get(url, headers=headers, timeout=90)
        response.raise_for_status()
        raw_file = RAW_API_DIR / f"curva_intradiaria_{downloaded_at.replace(':', '').replace('+', 'Z')}.json"
        raw_file.write_text(response.text, encoding="utf-8")
        records = flatten_json_records(response.json())
        daily = parse_records_to_daily_long(records, "API ANBIMA", project_path(raw_file))
        for curve_type, group in daily.groupby("curve_type", dropna=False):
            audit.loc[len(audit)] = [
                group["date"].min(),
                curve_type,
                "API ANBIMA",
                url,
                project_path(raw_file),
                group["vertex_du"].nunique(),
                group["vertex_du"].nunique(),
                bool(group.get("interpolated", pd.Series(False)).any()),
                downloaded_at,
                "Downloaded from configured ANBIMA Developers endpoint.",
            ]
        messages.append(f"API returned {len(daily)} parsed observations.")
        return SourceResult(daily, audit, messages)
    except Exception as exc:
        messages.append(f"ANBIMA API failed: {exc}")
        audit.loc[len(audit)] = [
            pd.NaT,
            pd.NA,
            "API ANBIMA",
            API_DOC_URL,
            pd.NA,
            0,
            0,
            False,
            downloaded_at,
            f"API attempt failed: {exc}",
        ]
        return SourceResult(standard_empty_daily_long(), audit, messages)


def find_local_curve_files() -> list[Path]:
    """Find local files that might contain ANBIMA yield curves."""
    search_roots = [RAW_DIR, PROJECT_ROOT / "data" / "anbima", PROJECT_ROOT]
    extensions = {".csv", ".txt", ".xlsx", ".xls", ".json", ".parquet"}
    excluded_dirs = {
        INTERMEDIATE_DIR.resolve(),
        DIAGNOSTICS_DIR.resolve(),
        CLEAN_DIR.resolve(),
        FIGURES_DIR.resolve(),
    }
    files: list[Path] = []
    for root in search_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in extensions:
                continue
            try:
                resolved = path.resolve()
                if any(excluded in resolved.parents for excluded in excluded_dirs):
                    continue
            except OSError:
                pass
            lower = str(path).lower()
            if path.name == "anbima_yield_curve_manual_template.csv":
                files.append(path)
            elif any(token in lower for token in ["anbima", "curva", "yield", "juros"]):
                files.append(path)
    return sorted(set(files))


def read_local_file(path: Path) -> list[tuple[str, pd.DataFrame]]:
    """Read a local tabular file and return one or more dataframes."""
    suffix = path.suffix.lower()
    if suffix in [".csv", ".txt"]:
        for sep in [None, ";", ",", "\t"]:
            try:
                df = pd.read_csv(path, sep=sep, engine="python")
                if len(df.columns) >= 3:
                    return [(path.name, df)]
            except Exception:
                continue
    if suffix in [".xlsx", ".xls"]:
        sheets = pd.read_excel(path, sheet_name=None)
        return [(f"{path.name}:{sheet}", df) for sheet, df in sheets.items()]
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = flatten_json_records(payload)
        return [(path.name, pd.json_normalize(records))]
    if suffix == ".parquet":
            return [(path.name, pd.read_parquet(path))]
    return []


def parse_tabular_curve_file(df: pd.DataFrame, source: str, source_file: str) -> pd.DataFrame:
    """Parse a local/API table into canonical daily-long format."""
    if df.empty:
        return standard_empty_daily_long()
    df = df.copy()
    df.columns = [str(col).strip() for col in df.columns]

    date_col = detect_column(df.columns, [r"(^|_)data($|_)", r"date", r"referencia", r"dt_"])
    curve_col = detect_column(df.columns, [r"curve", r"curva", r"indexador", r"tipo", r"classe", r"titulo"])
    vertex_col = detect_column(df.columns, [r"vert", r"prazo", r"dias?_uteis", r"\bdu\b", r"matur", r"duration"])
    yield_col = detect_column(df.columns, [r"taxa", r"yield", r"juros", r"rate", r"valor"])

    manual_cols = {"date", "curve_type", "vertex_du", "yield_pct"}
    if manual_cols.issubset(set(df.columns)):
        date_col, curve_col, vertex_col, yield_col = "date", "curve_type", "vertex_du", "yield_pct"

    if not (date_col and curve_col and vertex_col and yield_col):
        return standard_empty_daily_long()

    out = pd.DataFrame(
        {
            "date": parse_date_series(df[date_col]),
            "curve_type": df[curve_col].map(normalize_curve_type),
            "vertex_du": parse_numeric_series(df[vertex_col]),
            "yield_pct": parse_numeric_series(df[yield_col]),
            "source": source,
            "download_timestamp": timestamp_utc(),
            "source_file": source_file,
            "interpolated": False,
        }
    )
    out = out.dropna(subset=["date", "curve_type", "vertex_du", "yield_pct"])
    out["vertex_du"] = out["vertex_du"].round().astype(int)
    return out[list(standard_empty_daily_long().columns)]


def load_local_sources() -> SourceResult:
    """Load ANBIMA curves from local files, if available."""
    messages: list[str] = []
    audit = standard_empty_audit()
    frames: list[pd.DataFrame] = []
    files = find_local_curve_files()
    messages.append(f"Found {len(files)} candidate local ANBIMA files.")
    for path in files:
        try:
            for label, table in read_local_file(path):
                parsed = parse_tabular_curve_file(table, "arquivo local", project_path(path))
                if not parsed.empty:
                    frames.append(parsed)
                    for (date, curve_type), group in parsed.groupby(["date", "curve_type"]):
                        audit.loc[len(audit)] = [
                            date,
                            curve_type,
                            "arquivo local",
                            pd.NA,
                            label,
                            group["vertex_du"].nunique(),
                            group["vertex_du"].nunique(),
                            False,
                            group["download_timestamp"].iloc[0],
                            "Parsed from local file with detected columns.",
                        ]
                    messages.append(f"Parsed {len(parsed)} observations from {label}.")
        except Exception as exc:
            audit.loc[len(audit)] = [
                pd.NaT,
                pd.NA,
                "arquivo local",
                pd.NA,
                project_path(path),
                0,
                0,
                False,
                timestamp_utc(),
                f"Failed to parse local file: {exc}",
            ]
            messages.append(f"Failed to parse {path}: {exc}")
    if frames:
        daily = pd.concat(frames, ignore_index=True).drop_duplicates(
            subset=["date", "curve_type", "vertex_du", "yield_pct", "source_file"]
        )
    else:
        daily = standard_empty_daily_long()
    return SourceResult(daily, audit, messages)


def interpolate_to_target_vertices(daily_long: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Interpolate each curve/date to target vertices without extrapolation."""
    rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    if daily_long.empty:
        return standard_empty_daily_long(), standard_empty_audit()

    daily_long = daily_long.copy()
    daily_long["date"] = pd.to_datetime(daily_long["date"])
    for (date, curve_type), group in daily_long.groupby(["date", "curve_type"]):
        group = group.sort_values("vertex_du").drop_duplicates("vertex_du")
        xs = group["vertex_du"].astype(float).to_numpy()
        ys = group["yield_pct"].astype(float).to_numpy()
        min_x, max_x = xs.min(), xs.max()
        used = 0
        interpolation_used = False
        for label, vertex in TARGET_VERTICES.items():
            if vertex < min_x or vertex > max_x:
                continue
            if vertex in set(group["vertex_du"].astype(int)):
                value = float(group.loc[group["vertex_du"].astype(int) == vertex, "yield_pct"].iloc[0])
                interpolated = False
            else:
                value = float(np.interp(vertex, xs, ys))
                interpolated = True
                interpolation_used = True
            used += 1
            rows.append(
                {
                    "date": date,
                    "curve_type": curve_type,
                    "vertex_du": vertex,
                    "yield_pct": value,
                    "source": group["source"].iloc[0],
                    "download_timestamp": group["download_timestamp"].iloc[0],
                    "source_file": group["source_file"].iloc[0],
                    "interpolated": interpolated,
                }
            )
        audit_rows.append(
            {
                "date": date,
                "curve_type": curve_type,
                "source": group["source"].iloc[0],
                "source_url": API_DOC_URL if str(group["source"].iloc[0]).startswith("API") else pd.NA,
                "source_file": group["source_file"].iloc[0],
                "n_vertices_raw": int(group["vertex_du"].nunique()),
                "n_vertices_used": int(used),
                "interpolation_used": bool(interpolation_used),
                "download_timestamp": group["download_timestamp"].iloc[0],
                "notes": "Interpolated to target vertices; no extrapolation beyond available vertices.",
            }
        )
    interpolated_long = pd.DataFrame(rows, columns=standard_empty_daily_long().columns)
    audit = pd.DataFrame(audit_rows, columns=standard_empty_audit().columns)
    return interpolated_long, audit


def build_daily_wide(interpolated_long: pd.DataFrame) -> pd.DataFrame:
    """Build daily wide target-vertex table and BEI from PRE-IPCA."""
    columns = ["date"] + [f"{ct.lower()}_{label}" for ct in CURVE_TYPES for label in TARGET_VERTICES]
    if interpolated_long.empty:
        return pd.DataFrame(columns=columns)
    tmp = interpolated_long.copy()
    label_by_vertex = {v: k for k, v in TARGET_VERTICES.items()}
    tmp["vertex_label"] = tmp["vertex_du"].map(label_by_vertex)
    tmp["variable"] = tmp["curve_type"].str.lower() + "_" + tmp["vertex_label"]
    wide = (
        tmp.pivot_table(index="date", columns="variable", values="yield_pct", aggfunc="last")
        .reset_index()
        .sort_values("date")
    )
    for label in TARGET_VERTICES:
        pre_col, ipca_col, bei_col = f"pre_{label}", f"ipca_{label}", f"bei_{label}"
        if pre_col in wide.columns and ipca_col in wide.columns:
            wide[bei_col] = wide[pre_col] - wide[ipca_col]
    for col in columns:
        if col not in wide.columns:
            wide[col] = np.nan
    return wide[columns]


def add_curve_features(daily_wide: pd.DataFrame) -> pd.DataFrame:
    """Add level, slope, and curvature features to daily wide data."""
    df = daily_wide.copy()
    feature_formulas = {
        "pre_level_5y": ("pre_5y",),
        "pre_slope_5y_1y": ("pre_5y", "pre_1y"),
        "pre_slope_10y_2y": ("pre_10y", "pre_2y"),
        "pre_curvature_1y_5y_10y": ("pre_1y", "pre_5y", "pre_10y"),
        "ipca_level_5y": ("ipca_5y",),
        "ipca_slope_5y_1y": ("ipca_5y", "ipca_1y"),
        "ipca_slope_10y_2y": ("ipca_10y", "ipca_2y"),
        "ipca_curvature_1y_5y_10y": ("ipca_1y", "ipca_5y", "ipca_10y"),
        "bei_level_5y": ("bei_5y",),
        "bei_slope_5y_1y": ("bei_5y", "bei_1y"),
        "bei_slope_10y_2y": ("bei_10y", "bei_2y"),
        "bei_curvature_1y_5y_10y": ("bei_1y", "bei_5y", "bei_10y"),
    }
    for name, cols in feature_formulas.items():
        for col in cols:
            if col not in df.columns:
                df[col] = np.nan
        if len(cols) == 1:
            df[name] = df[cols[0]]
        elif "slope" in name:
            df[name] = df[cols[0]] - df[cols[1]]
        else:
            df[name] = 2 * df[cols[1]] - df[cols[0]] - df[cols[2]]
    return df


def aggregate_monthly(features_daily: pd.DataFrame, panel_months: pd.Series) -> pd.DataFrame:
    """Aggregate daily curve features to lagged monthly EOM and previous-month averages."""
    feature_cols = [col for col in features_daily.columns if col != "date"]
    panel_month = pd.to_datetime(panel_months).dt.to_period("M").dt.to_timestamp()
    monthly = pd.DataFrame({"month": panel_month}).drop_duplicates().sort_values("month")
    if features_daily.empty:
        for col in feature_cols:
            monthly[f"{col}_eom_lag1"] = np.nan
            monthly[f"{col}_avg_lag1"] = np.nan
        return monthly

    df = features_daily.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["obs_month"] = df["date"].dt.to_period("M").dt.to_timestamp()
    last_daily = df.sort_values("date").groupby("obs_month", as_index=False).tail(1)
    eom = last_daily[["obs_month"] + feature_cols].copy()
    avg = df.groupby("obs_month", as_index=False)[feature_cols].mean(numeric_only=True)
    eom["month"] = eom["obs_month"] + pd.offsets.MonthBegin(1)
    avg["month"] = avg["obs_month"] + pd.offsets.MonthBegin(1)
    eom = eom.drop(columns=["obs_month"]).rename(columns={col: f"{col}_eom_lag1" for col in feature_cols})
    avg = avg.drop(columns=["obs_month"]).rename(columns={col: f"{col}_avg_lag1" for col in feature_cols})
    monthly = monthly.merge(eom, on="month", how="left").merge(avg, on="month", how="left")
    return monthly


def pca_svd(matrix: np.ndarray, n_components: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Run PCA with numpy SVD on an already standardized matrix."""
    u, s, vt = np.linalg.svd(matrix, full_matrices=False)
    scores = u[:, :n_components] * s[:n_components]
    loadings = vt[:n_components].T
    denom = max(matrix.shape[0] - 1, 1)
    eigenvalues = (s**2) / denom
    explained = eigenvalues[:n_components] / eigenvalues.sum() if eigenvalues.sum() else np.full(n_components, np.nan)
    return scores, loadings, explained


def standardize_pca_block(df: pd.DataFrame, cols: list[str]) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Select complete rows and standardize a PCA block."""
    block = df[cols].dropna()
    means = block.mean()
    stds = block.std(ddof=0).replace(0, np.nan)
    standardized = (block - means) / stds
    standardized = standardized.dropna()
    return standardized, means, stds


def build_pca_factors(monthly: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    """Build full-sample and expanding-window PCA factors for curve blocks."""
    factors = monthly[["month"]].copy()
    explained_rows: list[dict[str, Any]] = []
    loading_rows: list[dict[str, Any]] = []
    messages: list[str] = []

    for suffix in ["eom_lag1", "avg_lag1"]:
        for block_name, base_cols in PCA_BLOCKS.items():
            cols = [f"{col}_{suffix}" for col in base_cols]
            missing_cols = [col for col in cols if col not in monthly.columns]
            if missing_cols:
                messages.append(f"PCA {block_name}/{suffix}: missing columns {missing_cols}.")
                continue
            complete = monthly[["month"] + cols].dropna()
            n_obs = len(complete)
            n_components = min(3, len(cols), max(n_obs - 1, 0))
            if n_components <= 0:
                messages.append(f"PCA {block_name}/{suffix}: insufficient complete observations.")
                continue
            if PCA_FULL_SAMPLE:
                standardized, _, _ = standardize_pca_block(complete, cols)
                if len(standardized) >= 2:
                    scores, loadings, explained = pca_svd(standardized.to_numpy(), n_components)
                    for idx in range(n_components):
                        pc_col = f"{block_name}_pc{idx + 1}_{suffix}"
                        factors.loc[factors["month"].isin(standardized.index.map(lambda i: complete.loc[i, "month"])), pc_col] = scores[:, idx]
                        explained_rows.append(
                            {
                                "block": block_name,
                                "suffix": suffix,
                                "method": "full_sample",
                                "component": idx + 1,
                                "explained_variance_ratio": explained[idx],
                                "n_observations": len(standardized),
                            }
                        )
                        for var, loading in zip(cols, loadings[:, idx]):
                            loading_rows.append(
                                {
                                    "block": block_name,
                                    "suffix": suffix,
                                    "method": "full_sample",
                                    "component": idx + 1,
                                    "variable": var,
                                    "loading": loading,
                                    "n_observations": len(standardized),
                                }
                            )
                else:
                    messages.append(f"PCA {block_name}/{suffix}: fewer than 2 complete rows.")
            if PCA_EXPANDING_WINDOW:
                recursive_scores = {f"{block_name}_pc{idx + 1}_{suffix}_expanding": [] for idx in range(3)}
                recursive_months: list[pd.Timestamp] = []
                complete_sorted = complete.sort_values("month").reset_index(drop=True)
                for row_idx in range(len(complete_sorted)):
                    if row_idx < MIN_PCA_WINDOW:
                        continue
                    train = complete_sorted.iloc[:row_idx]
                    current = complete_sorted.iloc[[row_idx]]
                    standardized_train, means, stds = standardize_pca_block(train, cols)
                    valid_cols = [col for col in cols if col in standardized_train.columns]
                    if len(standardized_train) < MIN_PCA_WINDOW or len(valid_cols) < 2:
                        continue
                    n_comp_rec = min(3, len(valid_cols), len(standardized_train) - 1)
                    _, loadings, explained = pca_svd(standardized_train[valid_cols].to_numpy(), n_comp_rec)
                    current_std = ((current[valid_cols] - means[valid_cols]) / stds[valid_cols]).to_numpy()
                    score = current_std @ loadings[:, :n_comp_rec]
                    recursive_months.append(current["month"].iloc[0])
                    for idx in range(3):
                        col = f"{block_name}_pc{idx + 1}_{suffix}_expanding"
                        recursive_scores[col].append(score[0, idx] if idx < n_comp_rec else np.nan)
                    for idx in range(n_comp_rec):
                        explained_rows.append(
                            {
                                "block": block_name,
                                "suffix": suffix,
                                "method": "expanding",
                                "component": idx + 1,
                                "explained_variance_ratio": explained[idx],
                                "n_observations": len(standardized_train),
                            }
                        )
                if recursive_months:
                    rec_df = pd.DataFrame({"month": recursive_months, **recursive_scores})
                    factors = factors.merge(rec_df, on="month", how="left")
                else:
                    messages.append(
                        f"PCA {block_name}/{suffix}: expanding window not computed; fewer than {MIN_PCA_WINDOW + 1} complete rows."
                    )
    return factors, pd.DataFrame(explained_rows), pd.DataFrame(loading_rows), messages


def build_control_lists(panel: pd.DataFrame) -> dict[str, list[str]]:
    """Build control-list JSON with variables that exist in the final panel."""
    baseline_candidates = [
        "pre_level_5y_eom_lag1",
        "pre_slope_5y_1y_eom_lag1",
        "ipca_level_5y_eom_lag1",
        "bei_level_5y_eom_lag1",
        "pre_slope_10y_2y_eom_lag1",
        "ipca_slope_5y_1y_eom_lag1",
        "bei_slope_5y_1y_eom_lag1",
    ]
    extended_candidates = [
        f"{prefix}_{feature}_{suffix}"
        for suffix in ["eom_lag1", "avg_lag1"]
        for prefix in ["pre", "ipca", "bei"]
        for feature in [
            "level_5y",
            "slope_5y_1y",
            "slope_10y_2y",
            "curvature_1y_5y_10y",
        ]
    ]
    pca_candidates = [
        f"{prefix}_pc{k}_{suffix}"
        for suffix in ["eom_lag1", "avg_lag1"]
        for prefix in ["pre", "ipca", "bei"]
        for k in [1, 2, 3]
    ]
    lists = {
        "yield_curve_controls_base": [col for col in baseline_candidates if col in panel.columns],
        "yield_curve_controls_extended": [col for col in extended_candidates if col in panel.columns],
        "yield_curve_controls_pca": [col for col in pca_candidates if col in panel.columns],
        "missing_from_base_candidates": [col for col in baseline_candidates if col not in panel.columns],
        "missing_from_pca_candidates": [col for col in pca_candidates if col not in panel.columns],
    }
    return lists


def save_diagnostics(
    raw_daily: pd.DataFrame,
    interpolated_long: pd.DataFrame,
    monthly: pd.DataFrame,
    final_panel: pd.DataFrame,
    pca_explained: pd.DataFrame,
) -> pd.DataFrame:
    """Save coverage, missingness, descriptive, and alert diagnostics."""
    rows: list[dict[str, Any]] = []
    if not interpolated_long.empty:
        for (curve_type, vertex), group in interpolated_long.groupby(["curve_type", "vertex_du"]):
            rows.append(
                {
                    "diagnostic": "coverage_by_curve_vertex",
                    "curve_type": curve_type,
                    "vertex_du": vertex,
                    "start": group["date"].min(),
                    "end": group["date"].max(),
                    "n_observations": len(group),
                    "n_missing": 0,
                    "share_missing": 0.0,
                    "notes": "Target-vertex daily long data.",
                }
            )
    else:
        rows.append(
            {
                "diagnostic": "coverage_by_curve_vertex",
                "curve_type": pd.NA,
                "vertex_du": pd.NA,
                "start": pd.NaT,
                "end": pd.NaT,
                "n_observations": 0,
                "n_missing": pd.NA,
                "share_missing": pd.NA,
                "notes": "No ANBIMA curve data available.",
            }
        )
    monthly_cols = [col for col in monthly.columns if col != "month"]
    for col in monthly_cols:
        rows.append(
            {
                "diagnostic": "monthly_missingness",
                "curve_type": pd.NA,
                "vertex_du": pd.NA,
                "start": monthly["month"].min() if "month" in monthly else pd.NaT,
                "end": monthly["month"].max() if "month" in monthly else pd.NaT,
                "n_observations": int(monthly[col].notna().sum()) if col in monthly else 0,
                "n_missing": int(monthly[col].isna().sum()) if col in monthly else 0,
                "share_missing": float(monthly[col].isna().mean()) if col in monthly and len(monthly) else np.nan,
                "notes": col,
            }
        )
    diag = pd.DataFrame(rows)
    diag.to_csv(DIAGNOSTICS_DIR / "anbima_yield_curve_diagnostics.csv", index=False)

    desc_cols = [col for col in monthly_cols if monthly[col].notna().any()]
    if desc_cols:
        monthly[desc_cols].describe().T.to_csv(DIAGNOSTICS_DIR / "anbima_yield_curve_descriptive_stats.csv")
    else:
        pd.DataFrame(columns=["variable", "note"]).to_csv(
            DIAGNOSTICS_DIR / "anbima_yield_curve_descriptive_stats.csv", index=False
        )

    corr_cols = [
        col
        for col in final_panel.columns
        if (col.endswith("_eom_lag1") and any(col.startswith(prefix) for prefix in ["pre_", "ipca_", "bei_"]))
        or re.match(r"^(pre|ipca|bei)_pc[123]_eom_lag1$", col)
    ]
    corr_cols = [col for col in corr_cols if final_panel[col].notna().any()]
    if len(corr_cols) >= 2:
        final_panel[corr_cols].corr().to_csv(DIAGNOSTICS_DIR / "anbima_yield_curve_correlations.csv")
    else:
        pd.DataFrame(columns=["note"]).to_csv(DIAGNOSTICS_DIR / "anbima_yield_curve_correlations.csv", index=False)
    if not pca_explained.empty:
        pca_explained.to_csv(DIAGNOSTICS_DIR / "anbima_yield_curve_pca_explained_variance.csv", index=False)
    return diag


def plot_outputs(daily_wide: pd.DataFrame, monthly: pd.DataFrame, pca_explained: pd.DataFrame, pca_loadings: pd.DataFrame) -> None:
    """Create requested diagnostic figures when data are available."""
    if not daily_wide.empty:
        for prefix, title, filename in [
            ("pre", "Curva prefixada ANBIMA", "anbima_pre_curves_selected_days.png"),
            ("ipca", "Curva IPCA ANBIMA", "anbima_ipca_curves_selected_days.png"),
        ]:
            cols = [f"{prefix}_{label}" for label in TARGET_VERTICES if f"{prefix}_{label}" in daily_wide.columns]
            sample = daily_wide.dropna(subset=cols, how="all").copy()
            if not sample.empty:
                selected = sample.iloc[np.linspace(0, len(sample) - 1, min(4, len(sample))).astype(int)]
                plt.figure(figsize=(9, 5))
                x = [TARGET_VERTICES[label] for label in TARGET_VERTICES]
                for _, row in selected.iterrows():
                    y = [row.get(f"{prefix}_{label}", np.nan) for label in TARGET_VERTICES]
                    plt.plot(x, y, marker="o", label=pd.to_datetime(row["date"]).date().isoformat())
                plt.title(title)
                plt.xlabel("Dias uteis")
                plt.ylabel("Taxa anual (%)")
                plt.legend()
                plt.tight_layout()
                plt.savefig(FIGURES_DIR / filename, dpi=160)
                plt.close()

    for col, filename, title in [
        ("pre_level_5y_eom_lag1", "anbima_pre_level_5y_eom_lag1.png", "Nivel prefixado 5 anos"),
        ("ipca_level_5y_eom_lag1", "anbima_ipca_level_5y_eom_lag1.png", "Nivel IPCA 5 anos"),
        ("bei_level_5y_eom_lag1", "anbima_bei_level_5y_eom_lag1.png", "Inflacao implicita 5 anos"),
    ]:
        if col in monthly.columns and monthly[col].notna().any():
            plt.figure(figsize=(10, 4))
            plt.plot(pd.to_datetime(monthly["month"]), monthly[col])
            plt.title(title)
            plt.ylabel("p.p. ao ano")
            plt.tight_layout()
            plt.savefig(FIGURES_DIR / filename, dpi=160)
            plt.close()

    slope_cols = [col for col in ["pre_slope_5y_1y_eom_lag1", "ipca_slope_5y_1y_eom_lag1"] if col in monthly.columns]
    if slope_cols and monthly[slope_cols].notna().any().any():
        plt.figure(figsize=(10, 4))
        for col in slope_cols:
            plt.plot(pd.to_datetime(monthly["month"]), monthly[col], label=col)
        plt.title("Inclinacoes prefixada e IPCA")
        plt.ylabel("p.p. ao ano")
        plt.legend()
        plt.tight_layout()
        plt.savefig(FIGURES_DIR / "anbima_pre_ipca_slopes_eom_lag1.png", dpi=160)
        plt.close()

    if not pca_explained.empty:
        full = pca_explained[pca_explained["method"] == "full_sample"].copy()
        if not full.empty:
            labels = full["block"] + "_" + full["suffix"] + "_pc" + full["component"].astype(str)
            plt.figure(figsize=(11, 5))
            plt.bar(labels, full["explained_variance_ratio"])
            plt.xticks(rotation=75, ha="right")
            plt.ylabel("Variancia explicada")
            plt.tight_layout()
            plt.savefig(FIGURES_DIR / "anbima_pca_explained_variance.png", dpi=160)
            plt.close()

    if not pca_loadings.empty:
        full_load = pca_loadings[pca_loadings["method"] == "full_sample"].copy()
        for block in full_load["block"].dropna().unique():
            sub = full_load[(full_load["block"] == block) & (full_load["suffix"] == "eom_lag1")]
            if sub.empty:
                continue
            pivot = sub.pivot_table(index="variable", columns="component", values="loading")
            pivot.plot(kind="bar", figsize=(10, 5))
            plt.title(f"Loadings PCA {block} - eom lag1")
            plt.tight_layout()
            plt.savefig(FIGURES_DIR / f"anbima_pca_loadings_{block}_eom_lag1.png", dpi=160)
            plt.close()


def main() -> None:
    """Run the ANBIMA yield-curve stage end to end."""
    ensure_directories()
    messages: list[str] = []
    input_panel = find_input_panel()
    panel = pd.read_csv(input_panel)
    if "month" not in panel.columns:
        raise ValueError(f"Input panel {input_panel} has no 'month' column.")
    panel["month"] = pd.to_datetime(panel["month"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    messages.append(f"Input panel used: {input_panel}")
    messages.append(f"Panel columns read: {len(panel.columns)}")

    api_result = fetch_from_anbima_api()
    messages.extend(api_result.messages)
    if api_result.daily_long.empty:
        local_result = load_local_sources()
        messages.extend(local_result.messages)
        raw_daily = local_result.daily_long
        audit_initial = pd.concat([api_result.audit, local_result.audit], ignore_index=True)
    else:
        raw_daily = api_result.daily_long
        audit_initial = api_result.audit

    if raw_daily.empty:
        template = create_manual_template("ANBIMA API unavailable/not configured and no local historical curve file parsed.")
        messages.append(f"No ANBIMA data available; manual template created at {template}.")
        audit_initial.loc[len(audit_initial)] = [
            pd.NaT,
            pd.NA,
            "template manual",
            API_DOC_URL,
            project_path(template),
            0,
            0,
            False,
            timestamp_utc(),
            "Fallback manual template created; no yield values filled.",
        ]

    raw_daily.to_csv(INTERMEDIATE_DIR / "anbima_yield_curves_daily_long_raw_detected.csv", index=False)
    interpolated_long, audit_interp = interpolate_to_target_vertices(raw_daily)
    daily_wide = build_daily_wide(interpolated_long)
    features_daily = add_curve_features(daily_wide)
    monthly = aggregate_monthly(features_daily, panel["month"])
    pca_factors, pca_explained, pca_loadings, pca_messages = build_pca_factors(monthly)
    messages.extend(pca_messages)

    panel_yield_curve = panel.merge(monthly, on="month", how="left")
    panel_yield_curve = panel_yield_curve.merge(pca_factors, on="month", how="left", suffixes=("", "_pca"))

    interpolated_long.to_csv(INTERMEDIATE_DIR / "anbima_yield_curves_daily_long.csv", index=False)
    daily_wide.to_csv(INTERMEDIATE_DIR / "anbima_yield_curves_daily_wide.csv", index=False)
    features_daily.to_csv(INTERMEDIATE_DIR / "anbima_yield_curve_features_daily.csv", index=False)
    monthly.to_csv(INTERMEDIATE_DIR / "anbima_yield_curve_features_monthly.csv", index=False)
    pca_factors.to_csv(INTERMEDIATE_DIR / "anbima_yield_curve_pca_factors_monthly.csv", index=False)
    panel_yield_curve.to_csv(CLEAN_DIR / "ftpl_monthly_panel_with_yield_curve_controls.csv", index=False)

    if pca_explained.empty:
        pca_explained = pd.DataFrame(
            columns=["block", "suffix", "method", "component", "explained_variance_ratio", "n_observations"]
        )
    if pca_loadings.empty:
        pca_loadings = pd.DataFrame(
            columns=["block", "suffix", "method", "component", "variable", "loading", "n_observations"]
        )
    pca_explained.to_csv(DIAGNOSTICS_DIR / "anbima_yield_curve_pca_explained_variance.csv", index=False)
    pca_loadings.to_csv(DIAGNOSTICS_DIR / "anbima_yield_curve_pca_loadings.csv", index=False)

    audit = pd.concat([audit_initial, audit_interp], ignore_index=True)
    audit.to_csv(DIAGNOSTICS_DIR / "anbima_yield_curve_audit.csv", index=False)
    diagnostics = save_diagnostics(raw_daily, interpolated_long, monthly, panel_yield_curve, pca_explained)
    plot_outputs(daily_wide, monthly, pca_explained, pca_loadings)

    control_lists = build_control_lists(panel_yield_curve)
    (DIAGNOSTICS_DIR / "yield_curve_control_lists.json").write_text(
        json.dumps(control_lists, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    monthly_created = [col for col in monthly.columns if col != "month"]
    present_nonmissing = [col for col in monthly_created if monthly[col].notna().any()]
    absent = [col for col in monthly_created if not monthly[col].notna().any()]

    coverage = "no curve data"
    if not interpolated_long.empty:
        coverage = f"{interpolated_long['date'].min().date()} to {interpolated_long['date'].max().date()}"

    saved_files = [
        INTERMEDIATE_DIR / "anbima_yield_curves_daily_long.csv",
        INTERMEDIATE_DIR / "anbima_yield_curves_daily_wide.csv",
        INTERMEDIATE_DIR / "anbima_yield_curve_features_daily.csv",
        INTERMEDIATE_DIR / "anbima_yield_curve_features_monthly.csv",
        INTERMEDIATE_DIR / "anbima_yield_curve_pca_factors_monthly.csv",
        CLEAN_DIR / "ftpl_monthly_panel_with_yield_curve_controls.csv",
        DIAGNOSTICS_DIR / "anbima_yield_curve_diagnostics.csv",
        DIAGNOSTICS_DIR / "anbima_yield_curve_audit.csv",
        DIAGNOSTICS_DIR / "yield_curve_control_lists.json",
    ]

    print("\n".join(messages))
    print("\nResumo Etapa B - Curva de juros ANBIMA")
    print(f"1. Painel de entrada usado: {input_panel}")
    print(f"2. Periodo coberto pelas curvas: {coverage}")
    print(f"3. Observacoes diarias alvo: {len(interpolated_long)}; observacoes mensais: {len(monthly)}")
    print(f"4. Variaveis de curva criadas: {len(monthly_created)}; com dados nao ausentes: {len(present_nonmissing)}")
    print(f"5. Variaveis que ficaram ausentes: {absent[:30]}{' ...' if len(absent) > 30 else ''}")
    print("6. Arquivos salvos:")
    for path in saved_files:
        print(f"   - {path}")
    print("7. Proximos passos recomendados:")
    if raw_daily.empty:
        print("   - Baixar curvas historicas oficiais da ANBIMA ou configurar credenciais de API.")
        print("   - Preencher data/raw/anbima/anbima_yield_curve_manual_template.csv se a API nao estiver disponivel.")
    else:
        print("   - Auditar interpolacoes e cobertura por vertice antes da estimacao econometrica.")
    print(f"Diagnosticos gerados: {len(diagnostics)} linhas.")


if __name__ == "__main__":
    main()
