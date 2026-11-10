# International Cost of Capital App

A Streamlit app that compares a project's cost of equity, cost of debt and WACC in USD and in the currency of a selected country.

## Data sources (fetched live, cached, refreshable)

| Input | Source | Notes |
|---|---|---|
| Industry unlevered beta | [Damodaran, betas.xls](https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls) | "Industry Averages" sheet, *Unlevered beta* column |
| USD BBB spread | [Damodaran, ratings.html](https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html) | Baa2/BBB row, large non-financial service firms |
| Corporate tax rates | [OECD Corporate Tax Statistics](https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/full-report/statutory-corporate-income-tax-rates_440f9286.html) | Combined statutory CIT rate, latest year, read from the OECD SDMX API (dataflow `DSD_TAX_CIT@DF_CIT`) |
| 10-year government yields | [Trading Economics /bonds](https://tradingeconomics.com/bonds) | Scraped from the public page, no API key |

Each source shows its value, data date, fetch time and status (Live / Fallback / Manual override). The **Refresh data** button clears the cache and fetches everything again. If OECD or Trading Economics cannot be reached, the app uses a clearly labelled built-in fallback (OECD 2024 table; Trading Economics snapshot of 10 Nov 2026). If Damodaran's beta file cannot be reached, you can upload `betas.xls` or override the beta.

## Features

- Select industry and target country; adjust equity risk premium and target debt share
- Switch the project tax rate between the U.S. and the selected country (one rate used for both currencies)
- Manual overrides for unlevered beta, both tax rates, USD BBB spread and both 10Y yields
- Foreign-currency BBB spread: auto-implied by default, with an optional manual override
- Side-by-side USD and foreign-currency results, all-industry comparison, CSV and Excel downloads
- Built-in verification tab and a hand-check worksheet showing each formula with numbers

Defaults on open: Software (System & Application), United States, U.S. tax rate, 6.5% ERP, 30% debt.

## Method

1. Relever beta (Hamada): βL = βU × [1 + (1 − t) × D/E], D/E = wD / (1 − wD)
2. USD cost of equity: kE = y_US + βL × ERP
3. USD pre-tax cost of debt: kD = y_US + BBB spread
4. Translate to foreign currency: (1 + k_FC) = (1 + k_USD) × (1 + y_FC) / (1 + y_US). An additive option, k_FC = k_USD + (y_FC − y_US), is available under *Advanced*.
5. Foreign cost of debt = y_FC + FC spread, where the auto spread = translated USD cost of debt − y_FC
6. WACC = wE × kE + wD × kD × (1 − t)

These are standard textbook formulas. Check them against the formulas given in class and adjust `cost_of_capital()` in `app.py` if they differ.

## Verification properties

- Equal government yields and no FC spread override → identical USD and FC results
- Zero debt → WACC equals cost of equity
- Overriding the FC spread changes only the FC results

The *Verification checks* tab tests all three live with the current inputs.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy

1. Create a GitHub repository and upload `app.py`, `requirements.txt` and `README.md`.
2. At [share.streamlit.io](https://share.streamlit.io), choose **New app**, pick the repository, branch `main` and file `app.py`, then **Deploy**.
