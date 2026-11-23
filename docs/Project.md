<!-- Documentation note: the self-contained theoretical-to-empirical narrative in
Section 2 of docs/DocumentacaoProjeto.tex was consolidated from the project's
theoretical note, empirical proposal, and issuance-shock methodology. The
consolidated section intentionally does not cite those local files in its prose;
this comment preserves the provenance for collaborators. -->

# FTPL Project Overview

Status da documentação: atualizado após a implementação da Etapa A, o
preenchimento auditável de PAF/reserva de liquidez e a implementação estrutural da
Etapa B para curvas ANBIMA. Na última execução local registrada, em 30/06/2026, a
Etapa B estava preparada para receber dados, mas não continha observações de curva
porque a API exigia credenciais que não estavam configuradas no ambiente.

Atualização de 22/11/2026: (i) corrigido um bug de leitura numérica do SGS/BCB no
notebook de dados (ver "SGS decimal-parsing fix" abaixo) e reexecutada toda a
cadeia; (ii) integrada a base de notícia fiscal Prisma/Focus construída pelo
coautor João (`build_prisma_fiscal_news.py`); (iii) adicionadas variáveis de
resultado de valuation — spread soberano, juros reais e nominais —
a partir do pacote Zenodo de Carvalho Filho (2026) (`build_valuation_outcomes.py`);
(iv) auditada a segunda entrega do João (`DadosJoao/data/`) e estendidos o estoque
e as participações por classe para 2000-02–2026-09 com séries do SGS, emendadas ao
eDPF (`build_stock_history_sgs.py`). Os fatores de curva entregues (β de Svensson
sem λ) não substituem a curva ANBIMA; (v) integradas as curvas diárias da ETTJ
ANBIMA (prefixada, IPCA e inflação implícita, 2006-01-02 a 2025-01-31) enviadas
pelo João (`import_anbima_ettj.py` → `build_anbima_yield_curve_controls.py`), com a
Etapa B e todos os estágios seguintes reexecutados. A extensão da série para antes
de 2006 e depois de jan/2025 foi pedida ao João e chegará em alguns dias; (vi)
criados dois estágios novos: `build_maturity_paf_hist.py` (vencimentos programados
por classe com principal e cupons, janelas de 12 meses, composição e prazo médio do
RMD e gaps do PAF recalculados com as participações longas) e
`build_breakeven_outcomes.py` (inflação implícita mensal como variável de
resultado); (vii) criado `build_issuance_forecasts.py`, com as equações de previsão
de emissão por classe (eq. 19 da nota metodológica) e as inovações \(u_t^j\);
(viii) analisadas as medidas de \(\Delta\mathcal{F}_t\), comparadas com Carvalho Filho
(2026), e criado `build_purged_shocks.py`, com a purga pelo Focus primário e doze
alternativas (DocumentacaoProjeto.tex, seção "Escolha de ΔF e purga fiscal"); (ix)
construídas as revisões Focus com `baseCalculo = 1` (só existem desde 2021-03-31),
usadas como robustez da purga.

## Research Objective

This project studies whether the denomination of Brazilian government debt changes the transmission of fiscal shocks to inflation and valuation variables. The theoretical mechanism comes from the Fiscal Theory of the Price Level: nominal fixed-rate debt can be revalued by inflation, inflation-indexed debt cannot be directly revalued through the price level, and floating-rate debt is intermediate because SELIC-linked payments rise when monetary policy responds to inflation.

The empirical design uses Brazilian Treasury instruments grouped as:

- `N`: nominal fixed-rate debt, mainly `LTN` and `NTN-F`.
- `F`: floating-rate debt, mainly `LFT`.
- `R`: inflation-indexed debt, mainly `NTN-B`.

The core empirical prediction is a ranking of inflation responses to comparable issuance shocks:

```text
Nominal fixed-rate shocks > Floating-rate shocks > Inflation-indexed shocks
```

The more robust primary comparison is nominal fixed-rate versus inflation-indexed debt, because those valuation elasticities are pinned down by contract.

The project is organized around three data stages:

1. the original monthly Treasury and macro-data construction;
2. structural predetermined controls for issuance forecasting (Etapa A);
3. yield-curve controls and PCA alternatives (Etapa B).

The econometric stages that would use these controls, including issuance forecast
residuals, fiscal-backing purging, and local projections, have not yet been
estimated.

## Main Source Files

### `ModeloTeorico.tex`

Standalone theoretical note titled `Debt Denomination and Fiscal Valuation: Nominal, Floating-Rate, and Inflation-Indexed Government Liabilities`.

It develops the valuation equation for a government debt portfolio with three liability classes:

- Nominal fixed-rate liabilities enter in real value as nominal claims divided by the price level.
- Inflation-indexed liabilities enter directly in real terms.
- Floating-rate liabilities are nominal, but future coupons respond to the policy rate.

The key theoretical object is the price-level valuation elasticity:

- `kappa_N = 1` for nominal fixed-rate debt.
- `kappa_R = 0` for inflation-indexed debt.
- `0 < kappa_F < 1` for floating-rate debt under an active monetary regime with partial offset through higher future debt service.

The note derives the ranking `kappa_N > kappa_F > kappa_R`, discusses fiscal inflation incentives, and characterizes when the ranking survives heterogeneous residual fiscal backing.

### `FTPL_test.tex`

This is the current main proposal draft. 

The proposal is titled `Debt Denomination, Fiscal Backing, and Inflation: Evidence from Brazilian Treasury Debt`. It combines the theoretical ranking with an empirical strategy based on survey-purged issuance shocks.

Main elements:

- Defines the empirical setting around Brazilian domestic Treasury securities: `LTN`, `NTN-F`, `LFT`, and `NTN-B`.
- Explains why raw issuance surprises are not sufficient, because debt expansions may be backed by expected future primary surpluses.
- Proposes constructing issuance innovations by debt type and purging them with revisions in fiscal expectations from Prisma Fiscal.
- Uses local projections to estimate responses of inflation, inflation expectations, SELIC, real yields, sovereign spreads, and the exchange rate.
- Prioritizes the nominal-versus-indexed inflation test, then uses the full nominal-floating-indexed ranking as a sharper test.
- Includes planned robustness checks, narrative validation, and an IV-style robustness strategy based on pension-fund regulatory demand for NTN-B securities.

### `ftpl_issuance_shocks_empirical_strategy_with_maturities.pdf`

Methodological note dated June 26, 2026, focused on measurement and identification of debt-issuance shocks.

The central recommendation is to separate three objects:

- Primary-market gross issuance.
- Net market financing flows.
- Accounting changes in the outstanding debt stock.

The PDF argues that gross market issuance by instrument should be the baseline shock object, conditional on scheduled maturities and other debt-management variables. Stock changes should not carry the main identification burden because LFT stocks mechanically accrue SELIC and NTN-B stocks mechanically accrue IPCA indexation and coupons, which would contaminate inflation and interest-rate local projections.

The note also details:

- Construction of scheduled redemptions `M_{t|t-1}` using only information available before the issuance decision.
- Separate treatment of nominal fixed-rate, floating-rate, and inflation-indexed scheduled payments.
- Issuance forecasting equations that condition on maturities, lagged issuance, lagged portfolio shares, macro variables, yield-curve factors, financing needs, market volatility, and debt-management targets.
- Survey purging of fiscal-backing news using Prisma Fiscal or Focus revisions.
- Alternative shock measures: net market flows and stock-based synthetic flows for robustness.
- Baseline local projections and ranking tests.
- Interaction of shocks with outstanding debt shares.
- State-dependent tests against resource-constraint explanations.

### `ftpl_build_data_notebook.ipynb`

Google Colab-style notebook that builds the project data and diagnostic figures.

The notebook:

- Defines output folders under Google Drive.
- Downloads raw Treasury auction data and debt stock data.
- Downloads macro series from BCB/SGS and IPCA data.
- Maps securities to the theoretical groups `N`, `F`, and `R`.
- Parses the Treasury auction workbook, using settlement date for monthly aggregation.
- Constructs gross monthly issuance from `Venda` and `Extra Venda` operations.
- Builds market debt stock by class and class shares from `estoquedpf.csv`.
- Builds a scheduled-maturities proxy using securities observed at `t-1` that mature in `t`.
- Combines issuance, macro variables, stocks, shares, and maturity proxies into a monthly panel.
- Generates diagnostic and motivation figures in `figures/`.
- Adds PIB normalization using BCB SGS series `4380` and writes `ftpl_monthly_panel_with_pib_normalization.csv`.

The notebook currently builds data, diagnostics, and normalized panels. It does not yet implement the Prisma fiscal-backing purge, issuance forecasting residuals, local projections, or formal ranking tests.

### `DocumentacaoProjeto.tex` and `DocumentacaoProjeto.pdf`

These are the consolidated project documentation for collaborators. The PDF is
the shareable version; the `.tex` file is its editable source. Section 2 is
self-contained and connects the FTPL valuation mechanism to the issuance-shock
construction, survey purge, local projections, and ranking restrictions.

### `Nota_EmissoesBrutas.tex` and `Nota_EmissoesBrutas.pdf`

Supplementary note on the measurement choice of gross issuance. It should be read
as methodological background for the original data construction, while the
issuance-shock strategy used for the next econometric stage is documented in
`DocumentacaoProjeto.tex` and implemented by the structural-control scripts.

### `build_structural_controls.py`

Main Etapa A script. It locates the most recent monthly panel, inspects actual
columns, creates lagged issuance, stock, share, maturity, calendar, extraordinary-
operation, PAF, and liquidity-reserve controls, and writes a derived structural
panel without overwriting the original panel.

### `fill_manual_templates_official_sources.py`

Auditable data-entry helper for the PAF and Treasury liquidity-reserve templates.
It reads official Treasury sources, preserves source files, writes audit tables,
and is separate from the main structural-control logic.

### `build_anbima_yield_curve_controls.py`

Main Etapa B script. It supports configured ANBIMA API access, local CSV/XLS/XLSX/
JSON/Parquet files, or a manual template. It standardizes daily curves, interpolates
target vertices without extrapolation, creates monthly `_eom_lag1` and `_avg_lag1`
controls, prepares PCA factors, and merges the result into a new panel.

Status (22/11/2026): populated with the ANBIMA ETTJ imported by
`import_anbima_ettj.py` (still no API credentials; the API path is skipped and the
local file is used). All 72 curve variables (`pre_*`, `ipca_*`, `bei_*` at the
eight vertices plus level/slope/curvature, each `_eom_lag1` and `_avg_lag1`) have
data for 2006-02 to 2025-02 (229 months), and the PCA blocks now exist (36 new
columns: `{pre,ipca,bei}_pc{1,2,3}_{eom,avg}_lag1` and `_expanding` versions; the
expanding ones start after `MIN_PCA_WINDOW = 60` months). Full-sample first
components explain 97% (PRE), 97% (IPCA) and 92% (BEI) of the variance. Checks:
`pre_1y_eom_lag1` in 2006-02 equals the raw 2006-01-31 value and `_avg_lag1` the
January mean; no vertex was interpolated (the ETTJ already has the target
vertices); BEI = PRE − IPCA equals the delivered BEIR exactly. Panel:
`ftpl_monthly_panel_with_yield_curve_controls.csv`, 564 × 300.

Two bugs were fixed on 22/11/2026 before the run:

- `parse_date_series` applied `dayfirst=True` to every string, so an ISO date
  "2006-01-02" became 1 Feb 2006 and ISO dates with day > 12 became NaT. ISO
  dates are now parsed as ISO and other strings day-first.
- `find_local_curve_files` scanned the whole repository for names containing
  "anbima/curva/yield/juros", which picked up `backups/` copies of earlier outputs
  (whose long files have the parser's exact columns) and the raw files in
  `DadosJoao/`. The search is now restricted to `data/raw/anbima/` (and the
  legacy `data/anbima/`), skipping `data/raw/anbima/original/`.

Caveat for users: `ipca_3m`, `ipca_6m`, `bei_3m` and `bei_6m` are unreliable. In
2013–2021 there were often no short NTN-B, so the fitted real curve is
extrapolated at the short end (real 3m up to 64.6%, BEI 3m down to −50%). Use real
and BEI vertices from 1y on; the PCA blocks and the level/slope/curvature features
already use only 1y–10y (and 5y–1y slopes).

### `import_anbima_ettj.py`

Imports an ANBIMA ETTJ workbook into the Etapa B input format. Run before
`build_anbima_yield_curve_controls.py`:
`python3 src/import_anbima_ettj.py [--source PATH]` (default
`DadosJoao/data/data_yields.xlsx`).

- Source: daily ANBIMA zero-coupon curves (ETTJ) exported by coauthor João for
  another project, delivered 22/11/2026. João confirmed the source is the ANBIMA
  ETTJ; the original ANBIMA files will not be delivered. Sheets `yields_nominal`,
  `yields_real`, `BEIR` (vertices 63, 126, 252, 504, 756, 1260, 1764 and 2520
  business days, rates in decimals) and `fatores` (daily Svensson β1–β4, λ1, λ2
  for the nominal and real curves). Coverage 2006-01-02 to 2025-01-31, 4,786
  business days, no gaps or missing values. João will extend the series in both
  directions.
- Preservation: the workbook is copied untouched to
  `data/raw/anbima/original/data_yields__sha256_ebf1e33b96a6.xlsx` (name carries
  the first 12 hex of its SHA-256; an identical file is reused, a different file
  with the same name gets a new name, nothing is overwritten). Only that copy is
  read. `DadosJoao/` stays git-ignored.
- Date trap: 258 date cells (2023-04-10 to 2024-05-27) are text `DD/MM/YYYY`,
  the rest are Excel dates. Read month-first, they produce duplicates, weekend
  dates and out-of-order months; they are parsed day-first.
- Validation (`data/diagnostics/anbima_ettj_import_validation.csv`; the script
  stops on any failure): identical dates in all sheets, strictly increasing, no
  weekends, max gap 5 calendar days, no missing values; BEIR equals nominal −
  real exactly (simple difference, as in the project spec, not Fisher); the
  yields equal the Svensson curve of the delivered parameters with t = du/252
  (max error 0); the 1y nominal vertex matches the ANBIMA 1y LTN rate from
  Ipeadata (Zenodo package) with mean absolute gap 0.026 pp and correlation
  0.9999 over 229 months. Real 5y/10y also match the Tesouro Direto constant-
  maturity real yields (corr. 0.998/0.999, mean |gap| < 0.1 pp; checked during
  the audit, not in the script).
- Output for Etapa B: `data/raw/anbima/anbima_ettj_daily_long.csv` (76,576 rows;
  `date` ISO, `curve_type` PRE/IPCA, `vertex_du`, `yield_pct` in % p.a.,
  `source_document` = preserved file name, `notes` = `ettj` or
  `ettj_real_short_unreliable` for IPCA 3m/6m). It is a derived file, rebuilt on
  each import. BEI is not written because Etapa B computes it as PRE − IPCA.
- Other outputs: `data/intermediate/anbima/anbima_ettj_svensson_params_daily.csv`
  (daily parameters, usable to evaluate any maturity) and
  `data/diagnostics/anbima_ettj_import_audit.csv` (source, preserved copy,
  SHA-256, coverage, meaning of the `notes` codes).
- When the extended series arrives: run the importer with `--source` on the new
  file, then the chain below.

### Stage order (22/11/2026)

`ftpl_build_data_notebook.ipynb` → `build_structural_controls.py` →
`import_anbima_ettj.py` → `build_anbima_yield_curve_controls.py` →
`build_fiscal_expectations_controls.py [--offline | --fetch PREFIX,...]` →
`build_prisma_fiscal_news.py [--offline]` → `build_valuation_outcomes.py` →
`build_stock_history_sgs.py [--offline]` → `build_maturity_paf_hist.py [--offline]`
→ `build_breakeven_outcomes.py` → `build_issuance_forecasts.py [--offline]` → `build_purged_shocks.py`. On 22/11/2026 the chain was rerun from
`import_anbima_ettj.py` on, with `--offline` (no new Focus or SGS pulls). Against
the previous commit, every downstream panel gained the 36 PCA columns and changed
only in the 72 curve columns (previously empty); no other column changed.

### `build_fiscal_expectations_controls.py`

Focus survey fiscal expectations (BCB Olinda API, no key): expected net public
debt (`focus_dlsp_*`) and expected primary balance (`focus_primary_*`), % of GDP,
converted from calendar-year forecasts to fixed 12- and 36-month horizons. Method
adapted from the Carvalho Filho (2026) replication package
(doi:10.5281/zenodo.24206681, stored in `data/raw/zenodo_24206681_fiscal_svar/`).
Reads the latest panel (currently the yield-curve panel) and writes
`data/clean/ftpl_monthly_panel_with_fiscal_expectations.csv`.

Variable roles (also in `data/diagnostics/fiscal_expectations_control_lists.json`):

- `*_eom_lag1`, `*_avg_lag1`, `*_rev_lag1`: predetermined; may enter the issuance
  forecasting equation.
- `*_rev_curr`: fixed-event revision during month t; fiscal-backing news for the
  survey purge only, never a forecasting control.

Coverage 2000-03 onward (36m horizon from 2001-12). Raw API pulls are saved with a
UTC timestamp in `data/raw/focus/`; offline runs (`--offline`) fall back to the newest
saved pull, then to the frozen Zenodo files. `PUBLICATION_LAG_DAYS` (default 0)
can require survey values to be published before month end (tested: levels
correlate 0.9999 with the default, contemporaneous revisions 0.96; kept at 0).

baseCalculo = 1 (added 23/11/2026): `focus_primary_bc1_*` and `focus_dlsp_bc1_*`
(16 columns, same suffixes) use the median of answers from the last 4 business days
instead of the 30-day window of `baseCalculo = 0`. The API has them only from
2021-03-31 (first revision 2021-04), with 8–20 respondents per reference year
(20–60 for baseCalculo = 0): robustness only, the main series stay at baseCalculo
= 0. `--fetch focus_primary_bc1,focus_dlsp_bc1` pulled only these from the API; all
previous columns were unchanged, and the downstream chain was rerun with
`--offline` (every panel from this one on gains the 16 columns). Comparison over
2021-04..2026-11 (`focus_basecalculo_comparison.csv`, figure
`focus_basecalculo_comparison.png`): for the 12m primary, the revision loses its
persistence (AR(1) 0.51 → 0.02, no zero months) and the old revision in t
correlates 0.41 with the new one in t-1 (the 30-day window carries news into the
next month); for the 36m primary and the DLSP the new revisions are noisier, with
negative AR(1) (−0.30 to −0.40) from the small and changing respondent pool.

Event impulse dummies, chosen by documented cause rather than outlier size:
`d_focus_gdprev_2007m04` (IBGE national-accounts revision lowers debt ratios
mechanically) and `d_focus_covid_2020m03` … `d_focus_covid_2020m07`. Each has a
`_lag1` version to pair with `*_rev_lag1`. Remaining |z| > 3 revisions (e.g.
2015-08, 2016-02, 2016-04, 2020-12, 2022-02) are listed in
`data/diagnostics/focus_fiscal_expectations_outliers.csv` but not dummied, since
they may be genuine fiscal news.

### `build_prisma_fiscal_news.py`

Integrates the Prisma Fiscal / Focus fiscal-news dataset delivered by coauthor
João in November 2026 (`DadosJoao/`, report `Relatorio_Series_Fiscais_v1.pdf`).
The delivery is copied once, with SHA-256, to `data/raw/prisma_fiscal_news_joao/`
and only that copy is read. Reads the fiscal-expectations panel and writes
`data/clean/ftpl_monthly_panel_with_fiscal_news.csv`.

Main variables (positive primary revision = higher expected surplus = good news):

- `prisma_primary_{12m,36m}_rev_curr_pib`: Prisma median revision of the Central
  Government primary balance during month t, fixed-event per target year combined
  with the same horizon weights as the Focus script, % of lagged 12-month GDP.
  Contemporaneous: survey purge only, never a forecasting control.
- `prisma_primary_{12m,36m}_rev_lag1_pib`: predetermined versions.
- `prisma_primary_surp_pib_release`: realized minus Prisma median for month t,
  dated at the approximate release month t+1 (exact Treasury release dates still
  to be checked).
- João's original fixed-event columns (`prisma_rev_*`, `focus_rev_*`, R$ mi or
  p.p.) are kept for traceability.

Checks (`data/diagnostics/prisma_fiscal_news_validation.csv`): João's h0–h3
revisions are reproduced to ~1e-11; the Prisma 12m revision correlates 0.95 with
`focus_primary_12m_rev_curr`. Two issues in the delivery are handled in code:
the realized series dates 2020-07 to 2021-12 on days 2–13, which made João's merge
drop 18 surprises (recomputed: 129 months instead of 111); and GDP is taken
from SGS 4380 directly (raw pull saved in `data/raw/bcb/`). Open points for João:
the original Prisma spreadsheets and Focus pulls were not delivered (extraction
not reproducible yet); `baseCalculo = 0` Focus medians are 30-day-window medians
and smooth month-end revisions; Prisma gross debt switches from General
Government (2015–2020) to Central Government (2021–), so it must not be spliced;
his report proposes fiscal news as the LP shock "in place of" issuance
innovations by class, which would change the identification design and needs a
joint decision.

### `build_valuation_outcomes.py`

Adds valuation outcome variables from the frozen monthly files of the Carvalho
Filho (2026) replication package (doi:10.5281/zenodo.24206681, CC-BY-4.0; cite
when used). The package is git-ignored and must be downloaded from Zenodo into
`data/raw/zenodo_24206681_fiscal_svar/`. Writes
`data/clean/ftpl_monthly_panel_with_valuation_outcomes.csv`.

- Main outcomes: `embi_spread_bp` (EMBI+ Brazil to 2024-07, then EMBI Global
  Diversified + 2.5 bp splice gap), `real_yield_5y_pct` and `real_yield_10y_pct`
  (Tesouro Direto NTN-B constant maturity), `ltn_1y_pct` (ANBIMA 1y LTN via
  Ipeadata).
- Robustness: `embi_plus_bp`, `embi_gd_bp`, `embi_gd_rel_bp`, `cds5y_bp`
  (Investing.com, quote convention not stated), `swap_di_pre_360d_pct`.
- Each also as `*_avg_lag1` (predetermined). All are monthly means of daily data,
  so no `_eom_lag1` version exists; no break-even is built because there is no
  nominal and real yield at the same maturity.

### `build_stock_history_sgs.py`

Extends the stock and shares by class back to 2000 (the eDPF-based columns
`stock_*_brl`, `share_*` start only in 2017-09). Reads the latest panel
(`ftpl_monthly_panel_with_valuation_outcomes.csv`) and writes
`data/clean/ftpl_monthly_panel_with_stock_history.csv` (the latest panel, +50
columns, 32 baseline and 18 broad-real robustness; existing columns are untouched). Flag `--offline` reuses the newest
saved pulls.

- Source: BCB SGS, federal securities held by the market ("posição em carteira",
  excluding the BCB portfolio), R$ million, monthly from 2000-02. Raw pulls are
  saved as `data/raw/bcb/sgs_<code>_<UTC timestamp>.csv` and never overwritten:
  10634 LFT (F), 10642 NTN-B (R), 10649 LTN, 10651 total pre-fixed, 10650 small
  pre-fixed residual item (2002-02 to 2005-09, ≤ R$ 0.12 bn, excluded), 10647
  NTN-C (coverage only), 4154 total Treasury securities in the market
  (denominator).
- N = 10651 − 10650 (LTN + NTN-F). NTN-F has no own SGS series; the implied
  value is never negative beyond ±1 rounding and becomes material in 2005-02.
- Splice: eDPF wherever it exists (2017-09 to 2026-04), SGS elsewhere (2000-02
  to 2017-08 and 2026-05 to 2026-09); `stock_hist_source` records the origin.
  Over the 104 common months SGS and eDPF agree to within 0.004% in levels
  (N and F ≈ 0), shares within 0.001 pp, and monthly changes correlate 1.0 at
  lag 0 (SGS dated day 01 = end-of-month stock). The script stops if the level
  gap exceeds 0.5% or NTN-F turns negative; on eDPF months the new shares
  reproduce `share_*` exactly.
- New variables: `stock_{N,F,R,total_NFR}_hist_brl`; `share_{g}_hist` (over
  N+F+R, same definition as `share_{g}`); `share_{g}_hist_mkt` (over the total
  in the market, SGS 4154); `coverage_NFR_over_market`;
  `stock_market_total_sgs_brl`, `stock_ntnc_sgs_brl`; predetermined
  `share_*_hist_lag1`, `share_*_hist_mkt_lag1`, `stock_*_hist_brl_lag1`,
  `stock_*_hist_pib_lag1`, `coverage_NFR_over_market_lag1`; and
  `gross_{g}_over_lag_stock_hist` (same formulas as the eDPF columns).
- Coverage caveat: N+F+R is only 75% of the market stock in 2000-02, 70% at the
  2002-09 trough, 82% in 2005-01 and 99% today (the rest is NTN-C, FX-linked
  bonds and LFT-A/B). NTN-B is zero before 2002-01 and NTN-F before 2005-02, so
  those shares are structurally zero, not missing. Baseline: shares over N+F+R
  (consistent with the panel); robustness: `_mkt` shares and a 2005+ sample.
- Outputs: `data/intermediate/stock_history/stock_history_sgs_monthly.csv`
  (includes LTN and implied NTN-F separately); diagnostics
  `stock_history_sgs_audit.csv` (file, sha256, URL per SGS pull),
  `stock_history_sgs_validation.csv`, `stock_history_sgs_diagnostics.csv`,
  `stock_history_sgs_lists.json`; figure `data/figures/stock_history_sgs.png`.
- Robustness only - broad real block `Ramp` = NTN-B + NTN-C (IGP-M linked):
  NTN-C market sales from the auction file (notebook filter, checked to reproduce
  `gross_R_brl`; R$ 26.7 bn in 2001–2006) plus SGS 10647 stock. 18 extra columns
  (`gross_ntnc_brl`, `gross_Ramp_brl`, `gross_Ramp_brl_over_pib_lag1`,
  `stock_Ramp_hist_brl`, `share_{N,F}_hist_ramp`, `share_Ramp_hist`,
  `share_Ramp_hist_mkt`, their `_lag1`, `stock_Ramp_hist_pib_lag1`,
  `gross_Ramp_over_lag_stock_hist`, ...), listed under
  `robustness_broad_real_block_Ramp` in the lists JSON. It gives R-block issuance
  from 2001 instead of 2005; the baseline R stays NTN-B only. The panel has
  564 × 436 columns after the ETTJ integration (400 before; the earlier "399"
  excluded `month`).
- João's `DadosJoao/data/clean/stock_by_group_bcb_sgs.csv` must not be used. Its
  raw SGS values are identical to ours, but it infers NTN-F from the percentage
  series 4177/4178 (`% pre × LFT / % Selic − LTN`), which gives negative NTN-F in
  57 months of 2000–2004, N errors in every month (up to 11.6%, R$ 7.4 bn) and
  share errors up to 1.7 pp.

### `build_maturity_paf_hist.py`

Builds a long predetermined maturity schedule and recomputes the PAF gaps. Reads
`ftpl_monthly_panel_with_stock_history.csv`, writes
`data/clean/ftpl_monthly_panel_with_maturity_paf_hist.csv` (+93 columns). Source:
the RMD annex already preserved in
`data/raw/liquidity_sources/Anexo RMD_Maio_26.xlsx` (read only; SHA-256 in the
audit), plus IGP-M (SGS 189, saved to `data/raw/bcb/sgs_189_<UTC>.csv`; `--offline`
reuses it). RMD sheets: 2.2 month-end stock by security (2010-01 on), 1.3 realized
redemptions by title (2006-11 on), 3.3 stock maturing in 12 months by indexer
(1999-12 on), 2.4 DPF composition by indexer (2000-12 on), 3.7 DPF average
maturity (2005-12, 2006-11 on).

- `maturity_{g}_sched_brl` (g = N, F, R, C; `Ramp` = R + C; `total_NFR`): debt
  service due in month t, known at the end of t−1. Principal = curve value at the
  end of t−1 of securities maturing in t (same concept as the eDPF proxy);
  coupons = quantity at t−1 × coupon per bond (NTN-F 10% in Jan/Jul; NTN-B 6% and
  NTN-C 6% (12% for the 2031 bond) on VNA built from IPCA/IGP-M of t−2, in the
  maturity month and six months away). Classes follow the eDPF mapping (R = all
  NTN-B variants). Principal and coupons are also kept separately
  (`_sched_principal_brl`, `_sched_coupon_brl`).
- Coverage: schedule from RMD 2.2 for t = 2010-02 to 2026-06; for 2006-11 to
  2010-01 the column uses realized RMD 1.3 redemptions (`maturity_sched_source`).
  No monthly schedule before 2006-11 yet.
- Validation (stops on failure): principal identical to the eDPF proxy in all 59
  proxy months (gap 0); schedule vs realized redemptions 2010-02..2026-05: mean
  |gap| / mean realized = 0.9% (N), 0.9% (F), 2.9% (R), 1.6% (C), 1.2% (N+F+R),
  correlations ≥ 0.9997; RMD 3.3 pre-fixed 12m vs 2.2 principal: corr 0.999.
  `maturity_{g}_realized_rmd_brl` is contemporaneous - validation only.
- 12-month windows from RMD 3.3 at the end of t−1: `maturity12m_{N,F,Ramp,total}_rmd_brl_lag1`
  and `_share_lag1` (share of that block's stock maturing in 12m), from 2000-01;
  `maturity12m_total_rmd_pib_lag1`; `liquidity_reserve_over_maturity12m_rmd_lag1`.
- RMD composition and maturity: `share_{pre,price,float,fx}_dpf_rmd_lag1`,
  `stock_dpf_rmd_brl_lag1`, `avg_maturity_dpf_years_rmd_lag1`.
- PAF gaps (`paf_gap_`, `paf_dist_*_to_lower/upper_`, `paf_*_below/above_band_`)
  for three share definitions: `hist` (N+F+R, `share_{g}_hist_lag1`), `hist_mkt`
  (total market) and `rmd` (DPF composition, RMD 2.4, also FX). Coverage 2003-01 on
  (the old `paf_gap_*_lag1` started 2017-10; `paf_gap_R_hist_lag1` reproduces it
  exactly where both exist). Also `paf_gap_maturing_12m_rmd_lag1` (DPMFi share
  maturing in 12m, RMD 3.3) and `paf_gap_avg_maturity_rmd_lag1` (2006-01 on).
- Recommended PAF version: `rmd`. The PAF bands are written for the DPF
  composition, including external debt and NTN-C. With N+F+R as denominator the
  gaps are badly biased before 2010 (e.g. Selic share above the band in 71% of
  months, mean gap +0.50 in 2003), because FX-linked debt and NTN-C are left out.
- Outputs: `data/intermediate/maturity_paf/` (security stock, schedule, realized
  redemptions), diagnostics `maturity_paf_hist_{audit,validation,diagnostics}.csv`
  and `maturity_paf_hist_lists.json`, figure `data/figures/maturity_paf_hist.png`.

### `build_breakeven_outcomes.py`

Monthly break-even inflation outcomes from the Etapa B daily curves
(`data/intermediate/anbima/anbima_yield_curve_features_daily.csv`). Writes
`data/clean/ftpl_monthly_panel_with_breakeven_outcomes.csv` (+19 columns, the
panel, 564 × 564). For h = 1, 2, 3, 5, 7, 10 years: `bei_{h}_pct` (monthly
mean in t, the main outcome, comparable with the other valuation outcomes),
`bei_{h}_eom_pct` (last business day of t) and `bei_{h}_fisher_pct` (Fisher
version, robustness); `bei_n_days`. 3m/6m excluded (extrapolated real curve).
Checks: BEI = PRE − IPCA daily, and `bei_{h}_pct`(t) = `bei_{h}_avg_lag1`(t+1),
`bei_{h}_eom_pct`(t) = `bei_{h}_eom_lag1`(t+1) (all exact, 229 months). Coverage
2006-01 to 2025-01, until the ETTJ extension arrives. Diagnostics
`breakeven_outcomes_{audit,validation,diagnostics}.csv`,
`breakeven_outcome_lists.json`; figure `data/figures/breakeven_outcomes.png`.

### `build_issuance_forecasts.py`

Issuance forecasting equations (eq. 19 of the methodological note) and issuance
innovations. Reads the break-even panel and writes
`data/clean/ftpl_monthly_panel_with_issuance_innovations.csv` (+119 columns, the
panel, 564 × 683). For j in {N, F, R}, OLS of `g_{j}_pib` (gross issuance
over lagged 12-month GDP) on:

- `maturity_{j}_sched_pib_lag1` (due in t) and `maturity_lead1_{j}_sched_pib_lag1`
  (due in t+1), both known at the end of t-1. The lead is built here from the RMD
  2.2 stock at t-1 (coupons with the index of t-2); before 2010-02 it is proxied by
  the schedule due in t+1 (`maturity_lead1_source`). It correlates ≥ 0.998 with the
  schedule due in t+1;
- issuance lags 1–3 of all three classes; own `stock_{j}_hist_pib_lag1` and
  `share_{j}_hist_lag1`; `maturity12m_total_rmd_pib_lag1`; lagged exchange,
  buyback, extra-sale and extra-purchase values;
- `selic_target_pa_lag1`, `ipca_yoy_pct_lag1` (released around day 10 of t),
  `ibc_br_yoy_pct_lag2` (released ~45 days later), `brl_usd_mom_pct_lag1`;
- PRE and IPCA curve level, slope and curvature (5y, 5y−1y, 1y-5y-10y, eom, t-1);
  `embi_spread_bp_avg_lag1` and `pre_5y_rvol_bp_lag1` (sd of daily changes of the
  5y PRE rate in t-1, bp);
- `focus_primary_12m_eom_lag1`, `focus_dlsp_12m_eom_lag1`;
- `paf_gap_{j}_rmd_lag1` and `paf_gap_maturing_12m_rmd_lag1`;
- calendar-month dummies.

The three equations share one sample (needed for the joint LP); HAC Newey–West
standard errors. Baseline sample 2006-11 to 2025-02 (220 months, 46 parameters,
limited by the ETTJ); R² 0.71 (N), 0.59 (F), 0.67 (R); Ljung–Box(12) p ≥ 0.36.
Due-in-t maturities raise same-class issuance by about 0.09 per real (significant for
N and R, not for F); the t+1 lead is not significant. Residual correlations: N–R 0.24,
N–F and F–R about 0. Preview for the purge: the base innovations are almost
uncorrelated with the contemporaneous Focus and Prisma fiscal revisions (|ρ| ≤ 0.09,
no p < 0.18).

Output columns: `u_{j}_{spec}` (innovation, contemporaneous, never a control) and
`ghat_{j}_{spec}`, plus the derived predetermined regressors. Specs: `base`; `long`
(no curve, to 2026-06, 236 months); `w12` (12-month class windows instead of the
monthly schedule, 2004-03 to 2026-06, 268 months); `pca`; `principal` (2010-02+);
`nolead`; `stock` (issuance and maturities over the lagged class stock); `liq`
(+ liquidity reserve, 2015-02+); `ramp` (`u_Ramp_ramp`, R = NTN-B + NTN-C);
`base_rt` (pseudo-real-time forecast errors, expanding window, from 2014-07). Base
innovations correlate 0.84–1.00 with every spec except `base_rt` (0.39 N, 0.71 F,
0.72 R). Diagnostics `issuance_forecasts_{audit,validation,fit,coefficients,wald,
residual_correlations}.csv`, `issuance_forecast_lists.json`; intermediates in
`data/intermediate/issuance_forecasts/`; figure `data/figures/issuance_forecasts.png`.

### `build_purged_shocks.py`

Survey purge (eq. 21): for each class, OLS of `u_{j}_base` on a constant and the
fiscal news \(\Delta\mathcal{F}_t\) of month t, HAC standard errors; the residual is
the shock `eps_{j}_{uspec}_{purge}`. Writes
`data/clean/ftpl_monthly_panel_with_purged_shocks.csv` (+66 columns, the latest
panel, 564 × 749). The main shock is `eps_{j}_base_fprim`.

| Purge | \(\Delta\mathcal{F}_t\) | Sample |
|---|---|---|
| `fprim` (main) | Focus primary 12m + 36m revisions | 2006-11..2025-02 (220) |
| `fprim_xev` | same, gamma estimated without 2007-04 and 2020-03..07, applied to all months | 220 |
| `fprim_dum` | same + event dummies (eps = 0 in those months) | 220 |
| `fprim16` | Focus primary on the Prisma sample | 2016-03..2025-02 (99) |
| `fprim_bc1` | Focus primary 12m + 36m with baseCalculo = 1 | 2021-04..2025-02 (47) |
| `fprim21` | main Focus primary on the `fprim_bc1` sample | 47 |
| `pprim` / `pprim_surp` | Prisma primary 12m + 36m, without / with the release-dated surprise | 99 |
| `fdlsp` / `fprim_fdlsp` | Focus DLSP 12m + 36m, alone / with the primary | 220 |
| `cfrisk` / `cfrisk_narr` | Carvalho Filho (2026) fiscal-risk shock, sign / narrative restrictions | 220 |
| `fprim_cfrisk` | Focus primary + `cfrisk` | 220 |

The baseline purge is also applied to every forecasting variant (`eps_{j}_{long,
w12,pca,principal,nolead,stock,liq,base_rt}_fprim`, `eps_Ramp_ramp_fprim`). The
Carvalho Filho shocks (posterior medians, + = adverse) are read from the git-ignored
replication package in `data/raw/zenodo_24206681_fiscal_svar/` (SHA-256 in the
audit) and added as `cf_fiscal_risk`, `cf_fiscal_risk_narr`; cite
doi:10.5281/zenodo.24206681 (CC-BY-4.0).

Results: survey revisions (Focus or Prisma, primary or DLSP) explain at most 2.7% of
the innovations; joint tests reject gamma = 0 at 5% only for Prisma in the N
equation (p = 0.045; 0.011 with the surprise; individual t-stats insignificant,
99 months). Purged shocks correlate ≥ 0.98 with the main one. Event dummies raise R²
to 3–4% only by zeroing 2020. The Carvalho Filho shock explains about 10% of
`u_R_base` (t = −5.8; less NTN-B issuance than predicted in adverse fiscal-risk
months), nothing relevant in N and F; those shocks correlate 0.95 with the main R
shock. Its correlation with our candidates: DLSP 12m 0.42, DLSP 36m 0.35, primary
revisions about −0.09. Diagnostics `purged_shocks_{audit,validation,gamma,fit,
correlations}.csv`, `purged_shock_lists.json`; figure `data/figures/purged_shocks.png`.
baseCalculo = 1 purge (47 months): R² 1.7% (N, F) and 15.5% (R; 36m revision
t = 3.2, joint p = 0.003); the main measure on the same months explains 10.7% of
u_R with p = 0.24. Fragile (47 months, noisy 36m revision); shocks correlate 0.99
(N, F) and 0.92 (R) with the main ones. Open: date the Prisma survey and the RTN
release; decide with João whether to purge priced fiscal news too.

#### Other files in `DadosJoao/data/` (audited 22/11/2026)

- `data_yields.xlsx` (delivered later the same day): daily ANBIMA ETTJ yields
  and Svensson parameters, 2006-01 to 2025-01; integrated via
  `import_anbima_ettj.py` (see above). It supersedes the item below.
- `fatores_curva_juros.xlsx`: monthly end-of-month Svensson β1–β4, nominal and
  real, 2010-01 to 2025-12, with no λ1/λ2 (these are the month-end rows of
  `data_yields.xlsx`). Without the λ the vertices and
  break-even cannot be rebuilt; the real-curve βs take extreme offsetting values.
  It does not meet `ANBIMA_data_requirements.md`. João was asked for the daily
  ANBIMA zero-coupon yields (PRE, IPCA, implied inflation) from the start of
  each series (at least 2009-12) to the latest date, optionally with the daily
  Svensson parameters for cross-checking.
- `CDS_Brasil.xlsx`: 5y and 2y CDS, 2008-01 to 2026-06, source not stated,
  apparently point values (corr. with Zenodo `cds5y` 0.98 in levels, 0.72 in
  changes) with 2008-05 to 2008-08 forward-filled. Robustness only; not
  integrated.
- `raw/2026-06-24/prisma/`: raw Prisma spreadsheets for 2015–2023 (partly
  covers the request for João's raw files; 2024+ still only exists as a Qlik
  export that was not preserved).
- Net issuance by indexer (BCB fiscal statistics, 2017–2026) and accrued interest
  by class: possible robustness, not integrated.
- Everything else (`clean/ftpl_monthly_panel.csv`, `main_dataset.csv`,
  `issuance_dataset.csv`, `stock_*`, auctions, RMD annexes) duplicates older
  versions of our own pipeline.

### SGS decimal-parsing fix (22/11/2026)

`fetch_bcb_sgs` in `ftpl_build_data_notebook.ipynb` removed every "." from SGS
values, but the JSON API uses "." as the decimal separator ("638091.1"). Levels
were inflated by a constant factor per series: GDP ×10 (so every `*_pib`
variable was 10× too small), `selic_target_pa` ×100, `brl_usd` ×10⁴, IBC-Br
×10⁵. Growth rates, logs and shares were unaffected. The notebook also
downloaded SGS 24363 (IBC-Br without seasonal adjustment) into `ibc_br_sa`; it now
uses 24364. After the fix the notebook was rerun locally (raw auction and stock
files unchanged, `REFRESH = False`) followed by every stage script; issuance, stock
and maturity columns in R$ are identical to before. Any estimate computed before
this date with `*_pib`, SELIC, FX or IBC-Br levels must be redone. The pre-fix
outputs are in `backups/sgs_decimal_fix_20261122/` (local, git-ignored).

### `ANBIMA_data_requirements.md`

This is the consolidated data specification for Etapa B and the document to
share with a coauthor or with ANBIMA when requesting the required history. It
contains the API reference and authentication variables, the expected daily
long-format schema, standardized curve types (`PRE`, `IPCA`, and `BEI`), target
vertices in business days, interpolation and no-extrapolation rules, BEI
construction, monthly predetermination rules, PCA blocks, manual-template
requirements, output files, audit fields, validation criteria, and the current
no-data status.

The script remains the executable specification, while this Markdown file is
the human-readable data dictionary and acceptance checklist. Since 22/11/2026 the
stage is populated from the ANBIMA ETTJ delivered by João (local-file path; API
credentials are still unavailable). Departures from the spec: coverage is
2006-01-02 to 2025-01-31 instead of the full history (extension requested), the
original ANBIMA file is not available (the coauthor's export is preserved
instead), and the short real vertices are unreliable.

### Auxiliary notebooks and R code

`build_structural_controls.ipynb` and
`build_anbima_yield_curve_controls.ipynb` are thin notebook wrappers around the
Python scripts. The executable logic should remain in the scripts so local and
Google Colab runs use the same implementation. `Código/DadosTesouro.R` is an
earlier or auxiliary R script and is not part of the active Python pipeline.

## Folder Structure

```text
.
├── docs/
│   ├── Project.md
│   ├── DocumentacaoProjeto.tex / .pdf
│   ├── ModeloTeorico.tex / .pdf
│   ├── FTPL_test.tex / .pdf
│   ├── Nota_EmissoesBrutas.tex / .pdf
│   ├── EtapaA.md
│   ├── ANBIMA_data_requirements.md
│   └── ftpl_issuance_shocks_empirical_strategy_with_maturities.pdf
├── src/
│   ├── build_structural_controls.py
│   ├── fill_manual_templates_official_sources.py
│   ├── import_anbima_ettj.py
│   ├── build_anbima_yield_curve_controls.py
│   ├── build_fiscal_expectations_controls.py
│   ├── build_prisma_fiscal_news.py
│   ├── build_valuation_outcomes.py
│   ├── build_stock_history_sgs.py
│   ├── build_maturity_paf_hist.py
│   ├── build_breakeven_outcomes.py
│   ├── build_issuance_forecasts.py
│   └── build_purged_shocks.py
├── notebooks/
│   ├── ftpl_build_data_notebook.ipynb
│   ├── build_structural_controls.ipynb
│   └── build_anbima_yield_curve_controls.ipynb
├── data/
│   ├── raw/                     # manual templates and official source files
│   ├── intermediate/anbima/     # daily/monthly curve transformations
│   ├── clean/                   # Etapa A and Etapa B panels
│   ├── diagnostics/             # audits, missingness, PCA, control lists
│   └── figures/                 # Etapa A and Etapa B figures
├── archive/Código/DadosTesouro.R # legacy/auxiliary R code
└── backups/reorganization_20261104/ # pre-reorganization snapshot
```

The reorganization has now been executed. All active data products use `data/`,
all active Python code uses `src/`, notebooks use `notebooks/`, and project
documentation uses `docs/`. LaTeX build artifacts remain beside their source
documents in `docs/`; they are generated products, not source files.

## Organization Notes

The active structure is now:

```text
docs/                  # documentation and LaTeX sources
src/                   # executable Python pipeline stages
notebooks/             # original notebook and thin wrappers
data/raw/              # immutable downloaded source files and templates
data/intermediate/     # transformations such as ANBIMA daily curves
data/clean/            # analysis-ready panels
data/diagnostics/      # audits, coverage, missingness, PCA diagnostics
data/figures/          # generated figures
archive/               # legacy R code
backups/               # snapshots made before material reorganization
```

Scripts locate the repository root by searching for `.git`, so they can be run
from the repository root or directly from `src/`. Notebook wrappers use paths
relative to `notebooks/`. The original Colab notebook writes to the `data/`
namespace when its `OUTPUT_DIR` is set to the project `data/` directory.

## Data Folders

### `data/raw/`

Original downloaded source files:

- `historico-leiloes-todos.xls`: Treasury auction history workbook, about 5.0 MB.
- `estoquedpf.csv`: Treasury debt stock file, about 11 MB.

### `data/clean/`

Processed datasets generated by the notebook:

- `auction_operations_clean.csv`: 19,604 rows, monthly coverage from 2000-01-01 to 2026-06-01. Cleaned auction operations with instrument, operation type, settlement date, maturity date, accepted amount, debt group, and market-sale indicator.
- `gross_issuance_long.csv`: 891 rows, 2000-01-01 to 2026-06-01. Monthly gross issuance by debt group in long format.
- `gross_issuance_wide.csv`: 318 rows, 2000-01-01 to 2026-06-01. Monthly gross issuance in wide format with `gross_N_brl`, `gross_F_brl`, `gross_R_brl`, and `gross_total_NFR_brl`.
- `macro_monthly.csv`: 564 rows, 1979-12-01 to 2026-11-01. Monthly macro panel with SELIC target, IBC-Br, BRL/USD, IPCA index, inflation rates, activity growth, and exchange-rate changes.
- `debt_stock_monthly.csv`: 104 rows, 2017-09-01 to 2026-04-01. Monthly market debt stock by debt class and portfolio shares.
- `scheduled_maturities_proxy.csv`: 59 rows, 2017-10-01 to 2026-04-01. Proxy for scheduled maturities by class using stock observed at `t-1` for securities maturing in `t`.
- `ftpl_monthly_panel.csv`: 564 rows, 1979-12-01 to 2026-11-01. Combined monthly panel with issuance, macro variables, stocks, shares, maturity proxies, and issuance-over-lagged-stock variables where available.
- `ftpl_monthly_panel_with_pib_normalization.csv`: 564 rows, 1979-12-01 to 2026-11-01. Extended panel with nominal PIB, rolling 12-month PIB, lagged PIB normalization, and short econometric names such as `g_N_pib`, `g_F_pib`, `g_R_pib`, `m_N_pib`, `m_F_pib`, and `m_R_pib`.

### `data/figures/`

Diagnostic and motivation outputs produced by the notebook, saved mostly as both `.png` and `.pdf`:

- Missing-value diagnostic.
- Gross monthly issuance by debt class.
- Rolling 12-month gross issuance by debt class.
- Monthly gross issuance shares.
- Annual gross issuance composition.
- Debt stock by class.
- Debt stock shares.
- Gross issuance versus scheduled maturity proxies for `N`, `F`, and `R`.
- Gross issuance over lagged stock.
- Scatter plot of nominal gross issuance and 12-month IPCA.
- SELIC and IPCA plot.
- Correlation matrix for issuance, composition, and macro variables.
- `annual_gross_issuance_summary_brl_billion.csv`, a summary table of annual gross issuance by class.

### `data/raw/`

Contains manual templates and preserved official source material for the newer
stages. The active manual inputs are:

- `paf_manual_targets.csv`, with backup `paf_manual_targets_backup_20260630.csv`;
- `treasury_liquidity_reserve_manual.csv`, with backup
  `treasury_liquidity_reserve_manual_backup_20260630.csv`;
- `anbima/anbima_yield_curve_manual_template.csv`, still empty (not needed while
  the ETTJ file is available);
- `anbima/original/data_yields__sha256_ebf1e33b96a6.xlsx`, the coauthor's ANBIMA
  ETTJ workbook, preserved untouched, and `anbima/anbima_ettj_daily_long.csv`, its
  conversion to the Etapa B long format (derived, rebuilt by
  `import_anbima_ettj.py`);
- `anbima/README_anbima_manual_template.txt`, short instructions for manual
  curve entry;
- `paf_sources/` and `liquidity_sources/`, containing downloaded official Treasury
  source files used for auditability.

### `data/clean/`

The principal current panels are:

- `ftpl_monthly_panel_structural_controls.csv`: Etapa A panel with 564 monthly
  observations (1979-12 to 2026-11) and 192 columns;
- `ftpl_monthly_panel_with_yield_curve_controls.csv`: 564 × 300, Etapa B curve
  controls and PCA factors from the ANBIMA ETTJ, with data for 2006-02 to 2025-02;
- `ftpl_monthly_panel_with_fiscal_expectations.csv`: 564 × 344 (Focus, incl. 16 baseCalculo = 1 columns);
- `ftpl_monthly_panel_with_fiscal_news.csv`: 564 × 384 (Prisma/Focus news);
- `ftpl_monthly_panel_with_valuation_outcomes.csv`: 564 × 402 (adds sovereign
  spread and yields);
- `ftpl_monthly_panel_with_stock_history.csv`: 564 × 452 (adds stock and shares
  by class from 2000-02, `*_hist`);
- `ftpl_monthly_panel_with_maturity_paf_hist.csv`: 564 × 545 (maturity schedule,
  RMD composition and long PAF gaps);
- `ftpl_monthly_panel_with_breakeven_outcomes.csv`: 564 × 564 (adds monthly
  break-even outcomes);
- `ftpl_monthly_panel_with_issuance_innovations.csv`: 564 × 683 (adds issuance
  forecasts and innovations);
- `ftpl_monthly_panel_with_purged_shocks.csv`: 564 × 749, the latest and most
  complete panel (adds survey-purged shocks and the Carvalho Filho shocks).

Column counts include `month`.

Issuance and auction files still end in 2026-06 and eDPF stocks in 2026-04 because
the raw Treasury files were not re-downloaded in the 22/11/2026 rerun; the
`*_hist` stock columns extend to 2026-09 with SGS.

### `data/intermediate/anbima/`

Contains the canonical daily-long, daily-wide, daily-feature, monthly-feature,
and PCA-factor files generated by the Etapa B script, now populated with the
ANBIMA ETTJ for 2006-01-02 to 2025-01-31, plus
`anbima_ettj_svensson_params_daily.csv` written by `import_anbima_ettj.py`.

The exact input schema, target vertices, transformations, and validation rules
for these files are documented in `docs/ANBIMA_data_requirements.md`.

### `data/diagnostics/` and `data/figures/`

These contain separate audit and diagnostic products for the PAF/liquidity work,
Etapa A structural controls, and Etapa B yield curves. In particular,
`anbima_ettj_import_audit.csv` and `anbima_ettj_import_validation.csv` document
the ETTJ import, `anbima_yield_curve_audit.csv` records the skipped API path and
one row per date and curve read from the local file, while
`yield_curve_control_lists.json` records which curve-control names exist in the
panel.

## Current Project Stage

The project has completed the conceptual design and the data-engineering stages
through the creation of structural controls. It is now ready for the econometric
construction of issuance innovations, but the fiscal-backing and yield-curve data
needed for the full specification are incomplete.

Completed or substantially implemented:

- theoretical FTPL denomination model and consolidated documentation;
- empirical proposal and measurement design for gross issuance shocks;
- original Treasury auction, stock, macro, maturity-proxy, and PIB-normalized panels;
- Etapa A structural controls, including lags, maturity windows, calendar events,
  extraordinary operations, PAF bands, and liquidity-reserve controls;
- audit files and backups for the manually filled PAF and liquidity templates;
- Etapa B parser, interpolation, monthly lagging, PCA framework, audit, and manual
  fallback for ANBIMA curves;
- consolidated ANBIMA data dictionary and acceptance checklist in
  `docs/ANBIMA_data_requirements.md`;
- derived structural and yield-curve panels; the yield-curve controls and PCA
  factors are populated from the ANBIMA ETTJ for 2006-02 to 2025-02
  (`import_anbima_ettj.py`);
- diagnostic and motivation figures for the available data stages.

- Focus fiscal expectations (`build_fiscal_expectations_controls.py`) and Prisma
  Fiscal news (`build_prisma_fiscal_news.py`), providing candidate fiscal-backing
  revision proxies \(\Delta\mathcal{F}_t^P\);
- valuation outcomes: sovereign spread (EMBI spliced, CDS), 5y/10y real yields
  and 1y nominal yields (`build_valuation_outcomes.py`);
- stock and shares by class extended to 2000-02–2026-09 with BCB SGS, spliced
  with eDPF and validated over 2017-09–2026-04 (`build_stock_history_sgs.py`);
- SGS decimal-parsing and IBC-Br series fixes, with full pipeline rerun;
- predetermined maturity schedule (principal + coupons) from 2006-11, 12-month
  maturity windows from 2000-01, and PAF gaps from 2003-01 in three versions
  (`build_maturity_paf_hist.py`);
- monthly break-even outcomes, 2006-01 to 2025-01 (`build_breakeven_outcomes.py`);
- issuance forecasting equations and innovations \(u_t^j\), baseline 2006-11 to
  2025-02 plus nine robustness versions (`build_issuance_forecasts.py`);
- analysis of the \(\Delta\mathcal{F}_t\) candidates and survey-purged shocks
  \(\varepsilon_t^j\), main (Focus primary) and twelve alternatives, including the
  baseCalculo = 1 Focus revisions (2021-04+)
  (`build_purged_shocks.py`).

Not yet implemented or not yet populated:

- confirmation with João of the main \(\Delta\mathcal{F}_t\) and of whether to purge
  priced fiscal news; exact dating of the
  Prisma survey and of the primary-surprise release;
- raw Prisma spreadsheets and Focus pulls behind João's dataset;
- ETTJ extension before 2006-01 and after 2025-01 (requested from João; the
  2005 baseline start currently has no curve controls for 2005-01 to 2006-01);
- monthly maturity schedule before 2006-11 (would need older RMD security-level
  annexes or a reconstruction from auctions and buybacks); NTN-B1 instalments are
  not modelled;
- local projection estimation and formal ranking tests;
- narrative event database and pension-fund regulatory IV robustness.

Recommended order of work:

1. Import João's extended ETTJ (`import_anbima_ettj.py --source ...`) and rerun
   the chain from Etapa B on; audit coverage.
2. Confirm the purge choices with João (main measure, 2020 treatment, priced
   fiscal news).
3. Re-estimate the forecasting equations and the purge when the extended ETTJ
   arrives.
4. Estimate local projections and test the primary `N > R` and sharper `N > F > R`
   restrictions, followed by state-dependence and valuation-outcome robustness.

## Notes And Open Issues

- The original data pipeline remains embedded in a Google Colab/Google Drive
  notebook, but Etapa A and Etapa B now have repository-root Python scripts. The
  stable notebook logic should gradually be moved into scripts or a package-style
  pipeline with explicit stage dependencies.
- `scheduled_maturities_proxy.csv` (eDPF, principal only, 2017-10 on) is superseded by `maturity_{g}_sched_brl` from `build_maturity_paf_hist.py` (principal + coupons, 2006-11 on), whose principal reproduces the proxy exactly. Etapa A columns built from the proxy are kept unchanged.
- The final combined panel extends back to 1979 because macro series are longer than issuance data. The usable empirical sample for issuance-based tests starts in 2000, Stock and share controls now cover 2000-02 onward through `build_stock_history_sgs.py` (`*_hist` columns; the original eDPF columns still start in 2017-09). The eDPF maturity proxy starts in 2017-10 (not 2021 as stated earlier); the new schedule starts in 2006-11 and the 12-month windows in 2000-01.
- The PAF targets cover 2003--2026, while the liquidity-reserve series covers
  2015-01--2026-05. Their shorter coverage is expected and should not be filled by
  interpolation outside the official source period.
- The ANBIMA Etapa B output is populated for 2006-02 to 2025-02 only. Until the
  extension arrives, any estimate using curve controls is restricted to that
  window, and the short real/BEI vertices (3m, 6m) should not be used.
- The root-level `.aux`, `.log`, `.out`, `.toc`, `.bbl`, `.blg`, and `.synctex.gz`
  files are build products. They are useful locally but should generally be ignored
  by Git unless a reproducibility workflow explicitly requires them.
- The repository currently has no formal dependency file or test suite. A future
  cleanup should add a small `requirements.txt` or `environment.yml`, smoke tests
  for panel dimensions/keys, and a single documented command that runs the stages
  in order.
