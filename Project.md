# FTPL Project Overview

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

This appears to be the current main proposal draft. The file requested as `FTPL_text.tex` is not present in the repository under that exact name.

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

## Folder Structure

```text
.
├── ModeloTeorico.tex
├── ModeloTeorico.pdf
├── FTPL_test.tex
├── FTPL_test.pdf
├── ftpl_issuance_shocks_empirical_strategy_with_maturities.pdf
├── ftpl_build_data_notebook.ipynb
├── Project.md
├── raw/
├── clean/
├── figures/
└── Código/
```

The root directory also contains LaTeX build artifacts such as `.aux`, `.bbl`, `.blg`, `.log`, `.out`, and `.synctex.gz`.

## Data Folders

### `raw/`

Original downloaded source files:

- `historico-leiloes-todos.xls`: Treasury auction history workbook, about 5.0 MB.
- `estoquedpf.csv`: Treasury debt stock file, about 11 MB.

### `clean/`

Processed datasets generated by the notebook:

- `auction_operations_clean.csv`: 19,604 rows, monthly coverage from 2000-01-01 to 2026-06-01. Cleaned auction operations with instrument, operation type, settlement date, maturity date, accepted amount, debt group, and market-sale indicator.
- `gross_issuance_long.csv`: 891 rows, 2000-01-01 to 2026-06-01. Monthly gross issuance by debt group in long format.
- `gross_issuance_wide.csv`: 318 rows, 2000-01-01 to 2026-06-01. Monthly gross issuance in wide format with `gross_N_brl`, `gross_F_brl`, `gross_R_brl`, and `gross_total_NFR_brl`.
- `macro_monthly.csv`: 559 rows, 1979-12-01 to 2026-06-01. Monthly macro panel with SELIC target, IBC-Br, BRL/USD, IPCA index, inflation rates, activity growth, and exchange-rate changes.
- `debt_stock_monthly.csv`: 104 rows, 2017-09-01 to 2026-04-01. Monthly market debt stock by debt class and portfolio shares.
- `scheduled_maturities_proxy.csv`: 59 rows, 2017-10-01 to 2026-04-01. Proxy for scheduled maturities by class using stock observed at `t-1` for securities maturing in `t`.
- `ftpl_monthly_panel.csv`: 559 rows, 1979-12-01 to 2026-06-01. Combined monthly panel with issuance, macro variables, stocks, shares, maturity proxies, and issuance-over-lagged-stock variables where available.
- `ftpl_monthly_panel_with_pib_normalization.csv`: 559 rows, 1979-12-01 to 2026-06-01. Extended panel with nominal PIB, rolling 12-month PIB, lagged PIB normalization, and short econometric names such as `g_N_pib`, `g_F_pib`, `g_R_pib`, `m_N_pib`, `m_F_pib`, and `m_R_pib`.

### `figures/`

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

### `Código/`

Contains `DadosTesouro.R`, likely an earlier or auxiliary R script for Treasury data work. It has not been integrated into the current notebook-based pipeline.

## Current Project Stage

The project is at the transition from theoretical design and data construction to econometric implementation.

Completed or substantially drafted:

- Theoretical FTPL denomination model.
- Research proposal framing the empirical test.
- Measurement note for constructing issuance shocks with scheduled maturities.
- Raw Treasury data collection.
- Cleaned gross issuance, debt stock, macro, maturity-proxy, and PIB-normalized panels.
- Diagnostic and motivation figures.

Not yet implemented in the files reviewed:

- Prisma Fiscal or Focus fiscal-expectations dataset.
- Construction of fiscal-backing revisions.
- Issuance forecasting equations and residual innovations.
- Survey-purged issuance shocks.
- Yield-curve factors, sovereign risk/CDS/EMBI variables, and real-yield outcomes.
- Local projection estimation.
- Formal nominal-indexed and nominal-floating-indexed ranking tests.
- Narrative event database and pension-fund regulatory IV robustness.

Immediate next steps:

1. Add fiscal-expectations data and construct the finite-horizon fiscal-backing revision proxy.
2. Improve scheduled maturity construction from the current stock-at-maturity proxy toward predetermined financial redemption values, if security-level coupon and indexation data are available.
3. Estimate issuance forecasting equations for `N`, `F`, and `R` using predetermined controls.
4. Purge issuance innovations with fiscal-backing revisions.
5. Build the local projection estimation scripts and ranking-test outputs.
6. Add missing valuation outcomes: real NTN-B yields, nominal yields or inflation compensation, sovereign spreads, and exchange-rate controls.

## Notes And Open Issues

- `FTPL_text.tex` was requested but is not present under that filename. `FTPL_test.tex` appears to be the current main text.
- The data pipeline is currently embedded in a notebook configured for Google Colab/Google Drive. For reproducible research, it would be useful to convert the stable parts into a script or package-style pipeline that can run from the repository root.
- The current `scheduled_maturities_proxy.csv` is explicitly a proxy based on market stock values and maturity timing. The PDF recommends a richer predetermined financial redemption measure when the required security-level data are available.
- The final combined panel extends back to 1979 because macro series are longer than issuance data. The usable empirical sample for issuance-based tests starts in 2000, and stock/maturity-share controls are only available from 2017 in the current cleaned files.
