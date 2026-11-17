#!/usr/bin/env python3
"""Fill manual PAF and liquidity-reserve templates from audited official sources."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import load_workbook


def find_project_root() -> Path:
    """Find the repository root from the script location or current directory."""
    candidates = [Path.cwd(), Path(__file__).resolve().parent]
    candidates.extend(Path(__file__).resolve().parents)
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    return Path(__file__).resolve().parent


ROOT = find_project_root()
RAW = ROOT / "data" / "raw"
DIAG = ROOT / "data" / "diagnostics"
LIQ_SOURCE = RAW / "liquidity_sources" / "Anexo RMD_Maio_26.xlsx"
PAF_TEMPLATE = RAW / "paf_manual_targets.csv"
LIQ_TEMPLATE = RAW / "treasury_liquidity_reserve_manual.csv"
PAF_AUDIT = DIAG / "paf_manual_targets_audit.csv"
LIQ_AUDIT = DIAG / "treasury_liquidity_reserve_audit.csv"

PAF_COLUMNS = [
    "year",
    "publication_date",
    "valid_from",
    "valid_to",
    "paf_prefixado_min",
    "paf_prefixado_max",
    "paf_selic_min",
    "paf_selic_max",
    "paf_price_indexed_min",
    "paf_price_indexed_max",
    "paf_fx_min",
    "paf_fx_max",
    "paf_maturing_12m_min",
    "paf_maturing_12m_max",
    "paf_avg_maturity_min",
    "paf_avg_maturity_max",
    "paf_stock_min_brl",
    "paf_stock_max_brl",
    "paf_strategy_prefixado",
    "paf_strategy_selic",
    "paf_strategy_price_indexed",
    "paf_strategy_fx",
    "source_document",
    "notes",
]

LIQ_COLUMNS = [
    "month",
    "liquidity_reserve_brl",
    "liquidity_reserve_months_of_debt_service",
    "source_document",
    "notes",
]


def as_float(value):
    """Convert Excel scalar values to float or NaN."""
    if value is None or value == "":
        return np.nan
    return float(value)


def parse_paf_sheet_57() -> tuple[list[dict], list[dict]]:
    """Extract PAF bands from official RMD annex sheet 5.7 through 2022."""
    wb = load_workbook(LIQ_SOURCE, read_only=True, data_only=True)
    ws = wb["5.7"]
    rows = list(ws.iter_rows(values_only=True))
    records: dict[int, dict] = {}
    audit: list[dict] = []

    # (header row, min/max row, first data row, last data row)
    blocks = [(5, 6, 8, 19), (23, 24, 26, 36), (40, 41, 43, 53), (56, 57, 59, 69)]
    row_map = {
        "Estoque da DPF em Mercado (R$ Bilhões)": ("paf_stock_min_brl", "paf_stock_max_brl", "R$ bilhões", 1e9),
        "Prazo Médio da DPF (anos)": ("paf_avg_maturity_min", "paf_avg_maturity_max", "anos", 1.0),
        "% Vincendo em 12 meses": ("paf_maturing_12m_min", "paf_maturing_12m_max", "percentual", 0.01),
        "Prefixado": ("paf_prefixado_min", "paf_prefixado_max", "percentual", 0.01),
        "Índice de Preços": ("paf_price_indexed_min", "paf_price_indexed_max", "percentual", 0.01),
        "Taxa Flutuante": ("paf_selic_min", "paf_selic_max", "percentual", 0.01),
        "Selic": ("paf_selic_min", "paf_selic_max", "percentual", 0.01),
        "Câmbio": ("paf_fx_min", "paf_fx_max", "percentual", 0.01),
    }

    for header_row, minmax_row, first_row, last_row in blocks:
        header = rows[header_row - 1]
        minmax = rows[minmax_row - 1]
        year_specs = []
        for col, value in enumerate(header):
            if isinstance(value, str) and value.startswith("PAF ") and "revis" not in value.lower():
                digits = "".join(ch for ch in value if ch.isdigit())
                if len(digits) >= 4:
                    year = int(digits[:4])
                    min_col = None
                    for offset in range(0, 4):
                        if col + offset < len(minmax) and minmax[col + offset] == "Mínimo":
                            min_col = col + offset
                            break
                    if min_col is not None and min_col + 1 < len(minmax) and minmax[min_col + 1] == "Máximo":
                        year_specs.append((year, min_col, min_col + 1))

        for year, min_col, max_col in year_specs:
            rec = records.setdefault(
                year,
                {
                    "year": year,
                    "publication_date": "",
                    "valid_from": f"{year}-01-01",
                    "valid_to": f"{year}-12-31",
                    "paf_strategy_prefixado": "unclear",
                    "paf_strategy_selic": "unclear",
                    "paf_strategy_price_indexed": "unclear",
                    "paf_strategy_fx": "unclear",
                    "source_document": (
                        "Anexo RMD Maio/2026, aba 5.7 - Acompanhamento dos Planos Anuais "
                        "de Financiamento da DPF; URL oficial: "
                        "https://www.tesourotransparente.gov.br/publicacoes/relatorio-mensal-da-divida-rmd/2026/5; "
                        "arquivo: Anexo RMD_Maio_26.xlsx"
                    ),
                    "notes": (
                        "Valores extraídos de tabela estruturada oficial; PAFs revisados aparecem na fonte, "
                        "mas não foram usados por falta de data de validade exata no anexo; percentuais convertidos para proporção; "
                        "estoque convertido de R$ bilhões para reais."
                    ),
                },
            )
            for r in range(first_row - 1, last_row):
                label = rows[r][0]
                if label not in row_map:
                    continue
                min_name, max_name, unit, multiplier = row_map[label]
                min_value = as_float(rows[r][min_col]) * multiplier
                max_value = as_float(rows[r][max_col]) * multiplier
                rec[min_name] = min_value
                rec[max_name] = max_value
                for var, val, src_col in [(min_name, min_value, min_col + 1), (max_name, max_value, max_col + 1)]:
                    audit.append(
                        {
                            "year": year,
                            "variable": var,
                            "value": val,
                            "source_document": "Anexo RMD Maio/2026 - Acompanhamento dos Planos Anuais de Financiamento da DPF",
                            "source_url": "https://www.tesourotransparente.gov.br/publicacoes/relatorio-mensal-da-divida-rmd/2026/5",
                            "source_file": str(LIQ_SOURCE.relative_to(ROOT)),
                            "page_or_table": f"aba 5.7, linha Excel {r + 1}, coluna Excel {src_col}",
                            "extraction_note": f"Unidade original: {unit}; multiplicador aplicado: {multiplier}.",
                            "confidence": "high",
                        }
                    )

    return list(records.values()), audit


def add_recent_paf_pdf_values(records: list[dict], audit: list[dict]) -> tuple[list[dict], list[dict]]:
    """Append PAF values for 2023-2026 extracted from clear tables in official PDFs."""
    pdf_values = {
        2023: {
            "paf_stock_min_brl": 6_400_000_000_000,
            "paf_stock_max_brl": 6_800_000_000_000,
            "paf_prefixado_min": 0.23,
            "paf_prefixado_max": 0.27,
            "paf_price_indexed_min": 0.29,
            "paf_price_indexed_max": 0.33,
            "paf_selic_min": 0.38,
            "paf_selic_max": 0.42,
            "paf_fx_min": 0.03,
            "paf_fx_max": 0.07,
            "paf_maturing_12m_min": 0.19,
            "paf_maturing_12m_max": 0.23,
            "paf_avg_maturity_min": 3.8,
            "paf_avg_maturity_max": 4.2,
            "source_pdf": "data/raw/paf_sources/PAF_2023.pdf",
            "source_url": "https://www.tesourotransparente.gov.br/publicacoes/plano-anual-de-financiamento-paf/2023",
            "table": "Quadro 3 - Limites de Referência para a DPF em 2023",
        },
        2024: {
            "paf_stock_min_brl": 7_000_000_000_000,
            "paf_stock_max_brl": 7_400_000_000_000,
            "paf_prefixado_min": 0.24,
            "paf_prefixado_max": 0.28,
            "paf_price_indexed_min": 0.27,
            "paf_price_indexed_max": 0.31,
            "paf_selic_min": 0.40,
            "paf_selic_max": 0.44,
            "paf_fx_min": 0.03,
            "paf_fx_max": 0.07,
            "paf_maturing_12m_min": 0.17,
            "paf_maturing_12m_max": 0.21,
            "paf_avg_maturity_min": 3.8,
            "paf_avg_maturity_max": 4.2,
            "source_pdf": "data/raw/paf_sources/PAF_2024.pdf",
            "source_url": "https://www.tesourotransparente.gov.br/publicacoes/plano-anual-de-financiamento-paf/2024",
            "table": "Quadro 2 - Limites de Referência para a DPF em 2024",
        },
        2025: {
            "paf_stock_min_brl": 8_100_000_000_000,
            "paf_stock_max_brl": 8_500_000_000_000,
            "paf_prefixado_min": 0.19,
            "paf_prefixado_max": 0.23,
            "paf_price_indexed_min": 0.24,
            "paf_price_indexed_max": 0.28,
            "paf_selic_min": 0.48,
            "paf_selic_max": 0.52,
            "paf_fx_min": 0.03,
            "paf_fx_max": 0.07,
            "paf_maturing_12m_min": 0.16,
            "paf_maturing_12m_max": 0.20,
            "paf_avg_maturity_min": 3.8,
            "paf_avg_maturity_max": 4.2,
            "source_pdf": "data/raw/paf_sources/PAF_2025.pdf",
            "source_url": "https://www.tesourotransparente.gov.br/publicacoes/plano-anual-de-financiamento-paf/2025",
            "table": "Quadro 2 - Limites de Referência para a DPF em 2025",
        },
        2026: {
            "paf_stock_min_brl": 9_700_000_000_000,
            "paf_stock_max_brl": 10_300_000_000_000,
            "paf_prefixado_min": 0.21,
            "paf_prefixado_max": 0.25,
            "paf_price_indexed_min": 0.23,
            "paf_price_indexed_max": 0.27,
            "paf_selic_min": 0.46,
            "paf_selic_max": 0.50,
            "paf_fx_min": 0.03,
            "paf_fx_max": 0.07,
            "paf_maturing_12m_min": 0.18,
            "paf_maturing_12m_max": 0.22,
            "paf_avg_maturity_min": 3.8,
            "paf_avg_maturity_max": 4.2,
            "source_pdf": "data/raw/paf_sources/PAF_2026.pdf",
            "source_url": "https://www.tesourotransparente.gov.br/publicacoes/plano-anual-de-financiamento-paf/2026/114",
            "table": "Quadro 2 - Limites de Referência para a DPF em 2026",
        },
    }
    for year, vals in pdf_values.items():
        rec = {
            "year": year,
            "publication_date": "",
            "valid_from": f"{year}-01-01",
            "valid_to": f"{year}-12-31",
            "paf_strategy_prefixado": "unclear",
            "paf_strategy_selic": "unclear",
            "paf_strategy_price_indexed": "unclear",
            "paf_strategy_fx": "unclear",
            "source_document": (
                f"Plano Anual de Financiamento (PAF) {year}; {vals['source_url']}; "
                f"arquivo: {Path(vals['source_pdf']).name}"
            ),
            "notes": (
                f"Valores extraídos do PDF oficial, {vals['table']}; percentuais convertidos para proporção; "
                "estoque convertido de R$ bilhões para reais; diretrizes qualitativas mantidas como unclear por conservadorismo."
            ),
        }
        for key, val in vals.items():
            if key.startswith("paf_"):
                rec[key] = val
                audit.append(
                    {
                        "year": year,
                        "variable": key,
                        "value": val,
                        "source_document": f"Plano Anual de Financiamento (PAF) {year}",
                        "source_url": vals["source_url"],
                        "source_file": vals["source_pdf"],
                        "page_or_table": vals["table"],
                        "extraction_note": "Extraído de tabela clara no PDF oficial; percentuais em proporção e estoque em reais.",
                        "confidence": "medium",
                    }
                )
        records.append(rec)
    return records, audit


def extract_liquidity() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Extract liquidity reserve from official RMD annex sheet 6.1."""
    wb = load_workbook(LIQ_SOURCE, read_only=True, data_only=True)
    ws = wb["6.1"]
    rows = []
    audit = []
    for excel_row, row in enumerate(ws.iter_rows(min_row=7, values_only=True), 7):
        month, reserve_billion, prudential_billion, index_months = row[:4]
        if month is None:
            continue
        month_ts = pd.Timestamp(month).to_period("M").to_timestamp()
        reserve_brl = float(reserve_billion) * 1e9 if reserve_billion is not None else np.nan
        index_val = float(index_months) if index_months is not None else np.nan
        rows.append(
            {
                "month": month_ts.strftime("%Y-%m-%d"),
                "liquidity_reserve_brl": reserve_brl,
                "liquidity_reserve_months_of_debt_service": index_val,
                "source_document": (
                    "Anexo RMD Maio/2026, aba 6.1 - Reserva de Liquidez; URL oficial: "
                    "https://www.tesourotransparente.gov.br/publicacoes/relatorio-mensal-da-divida-rmd/2026/5; "
                    "arquivo: Anexo RMD_Maio_26.xlsx"
                ),
                "notes": (
                    f"Aba 6.1, linha Excel {excel_row}; Reserva de Liquidez originalmente em R$ bilhões, "
                    "convertida para reais; Índice de Liquidez originalmente em meses."
                ),
            }
        )
        for var, value, unit, conversion in [
            ("liquidity_reserve_brl", reserve_brl, "R$ bilhões", "multiplicar por 1e9"),
            ("liquidity_reserve_months_of_debt_service", index_val, "meses", "sem conversão"),
        ]:
            audit.append(
                {
                    "month": month_ts.strftime("%Y-%m-%d"),
                    "variable": var,
                    "value": value,
                    "source_document": "Anexo RMD Maio/2026 - Reserva de Liquidez",
                    "source_url": "https://www.tesourotransparente.gov.br/publicacoes/relatorio-mensal-da-divida-rmd/2026/5",
                    "source_file": str(LIQ_SOURCE.relative_to(ROOT)),
                    "page_or_table": f"aba 6.1, linha Excel {excel_row}",
                    "unit_original": unit,
                    "conversion_to_brl": conversion,
                    "extraction_note": "Extraído de tabela estruturada oficial do anexo RMD.",
                    "confidence": "high",
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(audit)


def main() -> None:
    """Fill templates and write audit files."""
    DIAG.mkdir(parents=True, exist_ok=True)
    records, paf_audit = parse_paf_sheet_57()
    records, paf_audit = add_recent_paf_pdf_values(records, paf_audit)
    paf = pd.DataFrame(records)
    for col in PAF_COLUMNS:
        if col not in paf.columns:
            paf[col] = np.nan
    paf = paf[PAF_COLUMNS].sort_values(["year", "valid_from"]).reset_index(drop=True)
    paf.to_csv(PAF_TEMPLATE, index=False)
    pd.DataFrame(paf_audit).to_csv(PAF_AUDIT, index=False)

    liquidity, liquidity_audit = extract_liquidity()
    liquidity = liquidity[LIQ_COLUMNS].sort_values("month").reset_index(drop=True)
    liquidity.to_csv(LIQ_TEMPLATE, index=False)
    liquidity_audit.to_csv(LIQ_AUDIT, index=False)

    print(f"PAF rows written: {len(paf)} ({paf['year'].min()}-{paf['year'].max()})")
    print(f"Liquidity rows written: {len(liquidity)} ({liquidity['month'].min()} to {liquidity['month'].max()})")
    print(f"Wrote {PAF_TEMPLATE}")
    print(f"Wrote {LIQ_TEMPLATE}")
    print(f"Wrote {PAF_AUDIT}")
    print(f"Wrote {LIQ_AUDIT}")


if __name__ == "__main__":
    main()
