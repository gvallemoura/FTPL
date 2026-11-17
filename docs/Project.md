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

The last documented run found no configured ANBIMA credentials and no usable local
curve file. It therefore created empty but correctly structured curve outputs and
documented the fallback in the audit file. This is an implementation state, not
evidence that the ANBIMA series are economically missing; rerun the script before
assuming that the access situation is unchanged.

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

Event impulse dummies, chosen by documented cause rather than outlier size:
`d_focus_gdprev_2007m04` (IBGE national-accounts revision lowers debt ratios
mechanically) and `d_focus_covid_2020m03` … `d_focus_covid_2020m07`. Each has a
`_lag1` version to pair with `*_rev_lag1`. Remaining |z| > 3 revisions (e.g.
2015-08, 2016-02, 2016-04, 2020-12, 2022-02) are listed in
`data/diagnostics/focus_fiscal_expectations_outliers.csv` but not dummied, since
they may be genuine fiscal news.

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
the human-readable data dictionary and acceptance checklist. The current
implementation does not contain substantive ANBIMA observations: credentials
were unavailable and no usable local history was found in the last documented
run. The manual template and empty structured outputs are therefore deliberate
fallback products, not evidence that the ANBIMA series are economically absent.

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
│   └── build_anbima_yield_curve_controls.py
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
- `macro_monthly.csv`: 559 rows, 1979-12-01 to 2026-06-01. Monthly macro panel with SELIC target, IBC-Br, BRL/USD, IPCA index, inflation rates, activity growth, and exchange-rate changes.
- `debt_stock_monthly.csv`: 104 rows, 2017-09-01 to 2026-04-01. Monthly market debt stock by debt class and portfolio shares.
- `scheduled_maturities_proxy.csv`: 59 rows, 2017-10-01 to 2026-04-01. Proxy for scheduled maturities by class using stock observed at `t-1` for securities maturing in `t`.
- `ftpl_monthly_panel.csv`: 559 rows, 1979-12-01 to 2026-06-01. Combined monthly panel with issuance, macro variables, stocks, shares, maturity proxies, and issuance-over-lagged-stock variables where available.
- `ftpl_monthly_panel_with_pib_normalization.csv`: 559 rows, 1979-12-01 to 2026-06-01. Extended panel with nominal PIB, rolling 12-month PIB, lagged PIB normalization, and short econometric names such as `g_N_pib`, `g_F_pib`, `g_R_pib`, `m_N_pib`, `m_F_pib`, and `m_R_pib`.

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
- `anbima/anbima_yield_curve_manual_template.csv`, empty in the last documented
  run because API credentials and local historical curve files were unavailable;
- `anbima/README_anbima_manual_template.txt`, short instructions for manual
  curve entry;
- `paf_sources/` and `liquidity_sources/`, containing downloaded official Treasury
  source files used for auditability.

### `data/clean/`

The principal current panels are:

- `ftpl_monthly_panel_structural_controls.csv`: Etapa A panel with 559 monthly
  observations and 192 columns;
- `ftpl_monthly_panel_with_yield_curve_controls.csv`: derived panel with 559
  observations and 264 columns. It contains the Etapa B curve columns, currently
  missing because no ANBIMA curve observations were available.

### `data/intermediate/anbima/`

Contains the canonical daily-long, daily-wide, daily-feature, monthly-feature,
and PCA-factor files generated by the Etapa B script. Empty daily files are valid
outputs under the current no-data fallback and should not be interpreted as
successfully downloaded ANBIMA history.

The exact input schema, target vertices, transformations, and validation rules
for these files are documented in `docs/ANBIMA_data_requirements.md`.

### `data/diagnostics/` and `data/figures/`

These contain separate audit and diagnostic products for the PAF/liquidity work,
Etapa A structural controls, and Etapa B yield curves. In particular,
`anbima_yield_curve_audit.csv` records the unavailable API configuration and the
manual-template fallback from the last documented run, while
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
- derived structural and yield-curve panels; in the last documented run, the
  yield-curve variables were all `NaN` because no source observations were loaded;
- diagnostic and motivation figures for the available data stages.

Not yet implemented or not yet populated:

- Prisma Fiscal or Focus fiscal-expectations dataset;
- finite-horizon fiscal-backing revision proxy \(\Delta\mathcal{F}_t^P\);
- issuance forecasting equations and residual innovations \(u_t^j\);
- survey-purged issuance shocks \(\varepsilon_t^j\);
- authenticated ANBIMA history or audited manual curve data;
- PCA factors with actual curve observations;
- sovereign risk/CDS/EMBI, real-yield, nominal-yield, and breakeven outcomes;
- local projection estimation and formal ranking tests;
- narrative event database and pension-fund regulatory IV robustness.

Recommended order of work:

1. Obtain and preserve authenticated ANBIMA curve data, or fill the manual template
   with official files; rerun Etapa B and audit coverage/interpolation.
2. Replace the maturity proxy with predetermined financial redemption values when
   security-level coupons, indexation, and quantities are available.
3. Add fiscal-expectations data and construct \(\Delta\mathcal{F}_t^P\).
4. Estimate the three issuance forecasting equations using the structural and
   yield-curve controls available at `t-1`.
5. Purge `u_t^j` to obtain `epsilon_t^j`, documenting the information set
   and sample loss.
6. Estimate local projections and test the primary `N > R` and sharper `N > F > R`
   restrictions, followed by state-dependence and valuation-outcome robustness.

## Notes And Open Issues

- The original data pipeline remains embedded in a Google Colab/Google Drive
  notebook, but Etapa A and Etapa B now have repository-root Python scripts. The
  stable notebook logic should gradually be moved into scripts or a package-style
  pipeline with explicit stage dependencies.
- The current `scheduled_maturities_proxy.csv` is explicitly a proxy based on market stock values and maturity timing. The PDF recommends a richer predetermined financial redemption measure when the required security-level data are available.
- The final combined panel extends back to 1979 because macro series are longer than issuance data. The usable empirical sample for issuance-based tests starts in 2000, and stock/maturity-share controls are only available from 2017 in the current cleaned files.
- The PAF targets cover 2003--2026, while the liquidity-reserve series covers
  2015-01--2026-05. Their shorter coverage is expected and should not be filled by
  interpolation outside the official source period.
- The ANBIMA Etapa B output is structurally complete but substantively empty in the
  current run. `ftpl_monthly_panel_with_yield_curve_controls.csv` should therefore
  not be used as an econometric input for yield-curve controls until the audit file
  shows actual observations.
- The root-level `.aux`, `.log`, `.out`, `.toc`, `.bbl`, `.blg`, and `.synctex.gz`
  files are build products. They are useful locally but should generally be ignored
  by Git unless a reproducibility workflow explicitly requires them.
- The repository currently has no formal dependency file or test suite. A future
  cleanup should add a small `requirements.txt` or `environment.yml`, smoke tests
  for panel dimensions/keys, and a single documented command that runs the stages
  in order.
