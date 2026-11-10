"""
International Cost of Capital App
Compares a project's cost of equity, cost of debt and WACC in USD and in the
currency of a selected country.

Data sources (fetched live, cached, refreshable):
  - Industry unlevered betas ........ Aswath Damodaran (NYU Stern), betas.xls
  - USD BBB (Baa2) default spread ... Aswath Damodaran, ratings.html (large non-financial firms)
  - Statutory corporate tax rates ... OECD Corporate Tax Statistics (combined statutory CIT rate)
  - 10-year government bond yields .. Trading Economics, /bonds
"""

import io
import re
import datetime as dt

import numpy as np
import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------------------
BETAS_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls"
RATINGS_URL = "https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html"
OECD_PAGE_URL = (
    "https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/"
    "full-report/statutory-corporate-income-tax-rates_440f9286.html"
)
OECD_API_URL = (
    "https://sdmx.oecd.org/public/rest/data/OECD.CTP.TPS,DSD_TAX_CIT@DF_CIT,/all"
    "?startPeriod=2018&dimensionAtObservation=AllDimensions&format=csvfilewithlabels"
)
TE_URL = "https://tradingeconomics.com/bonds"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_INDUSTRY = "Software (System & Application)"
DEFAULT_COUNTRY = "United States"
DEFAULT_ERP = 6.5      # percent
DEFAULT_DEBT = 30.0    # percent

# Trading Economics country name -> ISO3 (used to join with OECD tax data)
TE_TO_ISO3 = {
    "United States": "USA", "United Kingdom": "GBR", "Japan": "JPN", "Australia": "AUS",
    "Germany": "DEU", "Brazil": "BRA", "Russia": "RUS", "India": "IND", "Canada": "CAN",
    "Italy": "ITA", "France": "FRA", "South Africa": "ZAF", "China": "CHN",
    "Switzerland": "CHE", "Mexico": "MEX", "Netherlands": "NLD", "New Zealand": "NZL",
    "Portugal": "PRT", "South Korea": "KOR", "Spain": "ESP", "Greece": "GRC",
    "Turkey": "TUR", "Finland": "FIN", "Lithuania": "LTU", "Norway": "NOR",
    "Poland": "POL", "Romania": "ROU", "Slovakia": "SVK", "Slovenia": "SVN",
    "Sweden": "SWE", "Hungary": "HUN", "Iceland": "ISL", "Ireland": "IRL",
    "Austria": "AUT", "Belgium": "BEL", "Croatia": "HRV", "Czech Republic": "CZE",
    "Denmark": "DNK", "Peru": "PER", "Chile": "CHL", "Colombia": "COL",
    "Singapore": "SGP", "Taiwan": "TWN", "Thailand": "THA", "Vietnam": "VNM",
    "Hong Kong": "HKG", "Indonesia": "IDN", "Israel": "ISR", "Malaysia": "MYS",
    "Pakistan": "PAK", "Philippines": "PHL", "Kenya": "KEN", "Nigeria": "NGA",
    "Zambia": "ZMB", "Luxembourg": "LUX", "Latvia": "LVA", "Estonia": "EST",
    "Bulgaria": "BGR", "Serbia": "SRB", "Cyprus": "CYP", "Malta": "MLT",
    "Egypt": "EGY", "Morocco": "MAR", "Argentina": "ARG", "Bangladesh": "BGD",
    "Sri Lanka": "LKA", "Qatar": "QAT", "Saudi Arabia": "SAU",
    "United Arab Emirates": "ARE", "Kazakhstan": "KAZ", "Ukraine": "UKR",
    "Uganda": "UGA", "Namibia": "NAM", "Botswana": "BWA", "Mauritius": "MUS",
    "Bahrain": "BHR", "Jordan": "JOR", "Uruguay": "URY", "Costa Rica": "CRI",
    "Dominican Republic": "DOM", "Ecuador": "ECU", "Panama": "PAN",
}

EURO = {"DEU", "ITA", "FRA", "NLD", "PRT", "ESP", "GRC", "FIN", "LTU", "SVK", "SVN", "IRL",
        "AUT", "BEL", "HRV", "LUX", "LVA", "EST", "CYP", "MLT", "BGR"}
CURRENCY = {
    "USA": "USD", "GBR": "GBP", "JPN": "JPY", "AUS": "AUD", "BRA": "BRL", "RUS": "RUB",
    "IND": "INR", "CAN": "CAD", "ZAF": "ZAR", "CHN": "CNY", "CHE": "CHF", "MEX": "MXN",
    "NZL": "NZD", "KOR": "KRW", "TUR": "TRY", "NOR": "NOK", "POL": "PLN", "ROU": "RON",
    "SWE": "SEK", "HUN": "HUF", "ISL": "ISK", "CZE": "CZK", "DNK": "DKK", "PER": "PEN",
    "CHL": "CLP", "COL": "COP", "SGP": "SGD", "TWN": "TWD", "THA": "THB", "VNM": "VND",
    "HKG": "HKD", "IDN": "IDR", "ISR": "ILS", "MYS": "MYR", "PAK": "PKR", "PHL": "PHP",
    "KEN": "KES", "NGA": "NGN", "ZMB": "ZMW", "SRB": "RSD", "EGY": "EGP", "MAR": "MAD",
    "ARG": "ARS", "BGD": "BDT", "LKA": "LKR", "QAT": "QAR", "SAU": "SAR", "ARE": "AED",
    "KAZ": "KZT", "UKR": "UAH", "UGA": "UGX", "NAM": "NAD", "BWA": "BWP", "MUS": "MUR",
    "BHR": "BHD", "JOR": "JOD", "URY": "UYU", "CRI": "CRC", "DOM": "DOP", "ECU": "USD",
    "PAN": "USD",
}
CURRENCY.update({c: "EUR" for c in EURO})

# Fallback only: combined statutory CIT rates (%), 2024, as published in OECD
# Corporate Tax Statistics 2024. Used ONLY if the OECD API cannot be reached; the app
# labels the value as a fallback so it is never mistaken for a live fetch.
OECD_FALLBACK_2024 = {
    "USA": 25.8, "GBR": 25.0, "DEU": 29.9, "FRA": 25.8, "ITA": 27.8, "ESP": 25.0,
    "NLD": 25.8, "BEL": 25.0, "AUT": 23.0, "CHE": 19.6, "SWE": 20.6, "NOR": 22.0,
    "DNK": 22.0, "FIN": 20.0, "IRL": 12.5, "PRT": 31.5, "GRC": 22.0, "POL": 19.0,
    "CZE": 21.0, "HUN": 9.0, "SVK": 21.0, "SVN": 22.0, "LTU": 15.0, "HRV": 18.0,
    "ROU": 16.0, "ISL": 21.0, "TUR": 25.0, "JPN": 29.7, "KOR": 26.4, "CHN": 25.0,
    "IND": 25.2, "SGP": 17.0, "HKG": 16.5, "THA": 20.0, "VNM": 20.0, "IDN": 22.0,
    "MYS": 24.0, "PHL": 25.0, "PAK": 29.0, "ISR": 23.0, "AUS": 30.0, "NZL": 28.0,
    "CAN": 26.1, "MEX": 30.0, "BRA": 34.0, "CHL": 27.0, "COL": 35.0, "PER": 29.5,
    "ZAF": 27.0, "KEN": 30.0, "NGA": 30.0, "ZMB": 30.0, "RUS": 20.0, "LUX": 24.9,
    "LVA": 20.0, "EST": 20.0,
}

# Fallback only: Trading Economics 10Y yields snapshot (%), captured 10 Nov 2026.
TE_FALLBACK = {
    "United States": 4.8730, "United Kingdom": 5.1308, "Japan": 2.6930, "Australia": 4.9950,
    "Germany": 3.2654, "Brazil": 15.1640, "Russia": 16.6690, "India": 7.1780,
    "Canada": 3.6580, "Italy": 4.3070, "France": 4.7450, "South Africa": 8.4100,
    "China": 1.5983, "Switzerland": 0.4570, "Mexico": 9.0850, "Netherlands": 3.3540,
    "New Zealand": 4.6300, "Portugal": 3.6920, "South Korea": 3.8620, "Spain": 3.8210,
    "Greece": 4.0900, "Turkey": 35.9150, "Finland": 3.6510, "Lithuania": 4.2420,
    "Norway": 4.3170, "Poland": 6.1680, "Romania": 7.0700, "Slovakia": 4.1800,
    "Slovenia": 3.7780, "Sweden": 2.9450, "Hungary": 5.3450, "Iceland": 6.8410,
    "Ireland": 3.4120, "Austria": 3.5090, "Belgium": 4.2190, "Croatia": 3.8470,
    "Czech Republic": 5.1050, "Denmark": 3.0740, "Peru": 6.2214, "Chile": 5.9300,
    "Colombia": 12.7910, "Singapore": 2.1410, "Taiwan": 1.9100, "Thailand": 1.9830,
    "Vietnam": 4.5740, "Hong Kong": 3.6770, "Indonesia": 7.6930, "Israel": 4.1320,
    "Malaysia": 3.8512, "Pakistan": 12.6810, "Philippines": 8.0060, "Kenya": 12.4760,
    "Nigeria": 16.8460, "Zambia": 14.7500,
}
TE_FALLBACK_DATE = "2026-11-10 snapshot"


# --------------------------------------------------------------------------------------
# Core calculations (pure functions; no Streamlit, so they can be tested directly)
# All rates are decimals (0.065 = 6.5%).
# --------------------------------------------------------------------------------------
def relever_beta(beta_u: float, tax: float, debt_share: float) -> float:
    """Hamada: beta_L = beta_U * [1 + (1 - t) * D/E], with D/E = w / (1 - w)."""
    de = debt_share / (1.0 - debt_share)
    return beta_u * (1.0 + (1.0 - tax) * de)


def to_foreign(rate_usd: float, y_us: float, y_fc: float, method: str = "exact") -> float:
    """Convert a USD required return into foreign-currency terms.

    exact    : (1 + r_FC) = (1 + r_USD) * (1 + y_FC) / (1 + y_US)   (relative yield / Fisher parity)
    additive : r_FC = r_USD + (y_FC - y_US)                          (linear approximation)
    """
    if method == "additive":
        return rate_usd + (y_fc - y_us)
    return (1.0 + rate_usd) * (1.0 + y_fc) / (1.0 + y_us) - 1.0


def cost_of_capital(beta_u, tax, debt_share, erp, y_us, y_fc, spread_usd,
                    spread_fc_override=None, method="exact"):
    """Return a dict with every intermediate value for USD and foreign currency (FC)."""
    beta_l = relever_beta(beta_u, tax, debt_share)
    w_e = 1.0 - debt_share

    # USD
    ke_usd = y_us + beta_l * erp
    kd_usd = y_us + spread_usd
    kd_usd_at = kd_usd * (1.0 - tax)
    wacc_usd = w_e * ke_usd + debt_share * kd_usd_at

    # Foreign currency
    ke_fc = to_foreign(ke_usd, y_us, y_fc, method)
    kd_fc_auto = to_foreign(kd_usd, y_us, y_fc, method)
    spread_fc_auto = kd_fc_auto - y_fc
    spread_fc = spread_fc_auto if spread_fc_override is None else spread_fc_override
    kd_fc = y_fc + spread_fc
    kd_fc_at = kd_fc * (1.0 - tax)
    wacc_fc = w_e * ke_fc + debt_share * kd_fc_at

    return {
        "beta_u": beta_u, "beta_l": beta_l, "tax": tax, "debt_share": debt_share,
        "equity_share": w_e, "erp": erp, "y_us": y_us, "y_fc": y_fc,
        "spread_usd": spread_usd, "spread_fc_auto": spread_fc_auto, "spread_fc": spread_fc,
        "spread_fc_overridden": spread_fc_override is not None,
        "ke_usd": ke_usd, "kd_usd": kd_usd, "kd_usd_at": kd_usd_at, "wacc_usd": wacc_usd,
        "ke_fc": ke_fc, "kd_fc": kd_fc, "kd_fc_at": kd_fc_at, "wacc_fc": wacc_fc,
    }


# --------------------------------------------------------------------------------------
# Parsers (separate from network so they can be tested on saved pages)
# --------------------------------------------------------------------------------------
def parse_betas(content: bytes):
    """Parse Damodaran betas.xls -> (DataFrame[Industry, Unlevered beta, ...], date string)."""
    raw = None
    for engine in ("xlrd", "openpyxl", None):
        try:
            raw = pd.read_excel(io.BytesIO(content), sheet_name="Industry Averages",
                                header=None, engine=engine)
            break
        except Exception:
            continue
    if raw is None:
        raise ValueError("Could not read the 'Industry Averages' sheet")

    hdr_idx = None
    for i in range(min(len(raw), 40)):
        if str(raw.iat[i, 0]).strip().lower() == "industry name":
            hdr_idx = i
            break
    if hdr_idx is None:
        raise ValueError("Header row 'Industry Name' not found")

    # Date: look above the header for a cell mentioning 'date' and take the next value
    as_of = None
    for i in range(hdr_idx):
        row = list(raw.iloc[i].values)
        for j, v in enumerate(row):
            if isinstance(v, str) and "date" in v.lower():
                rest = [x for x in row[j + 1:] if pd.notna(x) and str(x).strip()]
                if rest:
                    x = rest[0]
                    as_of = x.strftime("%B %Y") if hasattr(x, "strftime") else str(x).strip()
                else:
                    m = re.search(r"date[^:]*:\s*(.+)", v, re.I)
                    as_of = m.group(1).strip() if m else None
            elif hasattr(v, "strftime") and as_of is None:
                as_of = v.strftime("%B %Y")
        if as_of:
            break

    df = raw.iloc[hdr_idx + 1:].copy()
    df.columns = [str(c).strip() for c in raw.iloc[hdr_idx].values]
    col_ub = next((c for c in df.columns if c.lower() == "unlevered beta"), None)
    if col_ub is None:
        raise ValueError("Column 'Unlevered beta' not found")
    keep = ["Industry Name", col_ub]
    for extra in ("Number of firms", "Beta", "D/E Ratio", "Effective Tax rate"):
        if extra in df.columns:
            keep.append(extra)
    df = df[keep].rename(columns={"Industry Name": "Industry", col_ub: "Unlevered beta"})
    df["Unlevered beta"] = pd.to_numeric(df["Unlevered beta"], errors="coerce")
    df = df.dropna(subset=["Industry", "Unlevered beta"])
    df["Industry"] = df["Industry"].astype(str).str.strip()
    df = df[df["Industry"] != ""].reset_index(drop=True)
    return df, as_of


def parse_ratings(html: str):
    """Return (BBB spread as decimal, as-of string) for large non-financial firms."""
    soup = BeautifulSoup(html, "lxml")
    spread = None
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if "Baa2/BBB" in cells:
            k = cells.index("Baa2/BBB")  # first occurrence = large non-financial table
            m = re.search(r"(-?\d+(?:\.\d+)?)\s*%", " ".join(cells[k + 1:k + 3]))
            if m:
                spread = float(m.group(1)) / 100.0
                break
    if spread is None:
        raise ValueError("Baa2/BBB row not found")
    text = soup.get_text(" ", strip=True)
    m = re.search(r"Data used is as of\s+([A-Za-z]+\s+\d{4})", text)
    return spread, (m.group(1) if m else None)


def parse_te_bonds(html: str) -> pd.DataFrame:
    """Return DataFrame[Country, Yield (%), Date] from tradingeconomics.com/bonds."""
    tables = pd.read_html(io.StringIO(html))
    known = {"Yield", "Chg", "Weekly", "Monthly", "YTD", "YoY", "Date"}
    frames = []
    for t in tables:
        cols = [str(c) for c in t.columns]
        t.columns = cols
        if "Yield" not in cols:
            continue
        ccol = None
        for c in cols:
            if c in known:
                continue
            s = t[c]
            if not pd.api.types.is_numeric_dtype(s) and s.notna().mean() > 0.8:
                ccol = c
                break
        if ccol is None:
            continue
        f = pd.DataFrame({
            "Country": t[ccol].astype(str).str.strip(),
            "Yield (%)": pd.to_numeric(t["Yield"], errors="coerce"),
            "Date": t["Date"].astype(str) if "Date" in cols else "",
        })
        frames.append(f)
    if not frames:
        raise ValueError("No yield tables found")
    out = pd.concat(frames).dropna(subset=["Yield (%)"])
    out = out.drop_duplicates("Country").sort_values("Country").reset_index(drop=True)
    return out


def parse_oecd_csv(text: str):
    """Return (dict ISO3 -> combined statutory CIT rate decimal, dict ISO3 -> year, labels)."""
    df = pd.read_csv(io.StringIO(text), low_memory=False)
    if "OBS_VALUE" not in df.columns or "REF_AREA" not in df.columns:
        raise ValueError("Unexpected OECD CSV layout")
    labcols = [c for c in df.columns
               if not pd.api.types.is_numeric_dtype(df[c]) and c != "REF_AREA"]
    blob = df[labcols].astype(str).agg(" | ".join, axis=1).str.lower()
    mask = blob.str.contains("combined") & ~blob.str.contains("targeted|small business")
    sub = df[mask].copy()
    if sub.empty:
        raise ValueError("Combined CIT rate series not found")
    sub["OBS_VALUE"] = pd.to_numeric(sub["OBS_VALUE"], errors="coerce")
    sub["TIME_PERIOD"] = pd.to_numeric(sub["TIME_PERIOD"], errors="coerce")
    sub = sub.dropna(subset=["OBS_VALUE", "TIME_PERIOD"])
    sub = sub.sort_values("TIME_PERIOD").groupby("REF_AREA").tail(1)
    rates = {r.REF_AREA: r.OBS_VALUE / 100.0 for r in sub.itertuples()}
    years = {r.REF_AREA: int(r.TIME_PERIOD) for r in sub.itertuples()}
    name_col = "Reference area" if "Reference area" in sub.columns else None
    labels = {r["REF_AREA"]: r[name_col] for _, r in sub.iterrows()} if name_col else {}
    return rates, years, labels


# --------------------------------------------------------------------------------------
# Fetchers (cached; the Refresh button clears the cache)
# --------------------------------------------------------------------------------------
def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_betas():
    try:
        r = requests.get(BETAS_URL, headers=HEADERS, timeout=40)
        r.raise_for_status()
        df, as_of = parse_betas(r.content)
        return {"ok": True, "df": df, "as_of": as_of or "see file", "fetched": _now()}
    except Exception as e:
        return {"ok": False, "error": str(e), "fetched": _now()}


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_spread():
    try:
        r = requests.get(RATINGS_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        spread, as_of = parse_ratings(r.text)
        return {"ok": True, "spread": spread, "as_of": as_of or "see page", "fetched": _now()}
    except Exception as e:
        return {"ok": False, "error": str(e), "fetched": _now()}


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def fetch_tax():
    try:
        r = requests.get(OECD_API_URL, headers=HEADERS, timeout=60)
        r.raise_for_status()
        rates, years, labels = parse_oecd_csv(r.text)
        return {"ok": True, "rates": rates, "years": years, "fetched": _now(),
                "source": "OECD API (DF_CIT, combined statutory CIT rate)"}
    except Exception as e:
        return {"ok": False, "error": str(e), "fetched": _now(),
                "rates": {k: v / 100 for k, v in OECD_FALLBACK_2024.items()},
                "years": {k: 2024 for k in OECD_FALLBACK_2024},
                "source": "Fallback: OECD Corporate Tax Statistics 2024 table (built in)"}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_yields():
    try:
        r = requests.get(TE_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        df = parse_te_bonds(r.text)
        return {"ok": True, "df": df, "fetched": _now()}
    except Exception as e:
        df = pd.DataFrame({"Country": list(TE_FALLBACK),
                           "Yield (%)": list(TE_FALLBACK.values()),
                           "Date": TE_FALLBACK_DATE}).sort_values("Country")
        return {"ok": False, "error": str(e), "df": df.reset_index(drop=True),
                "fetched": _now()}


# --------------------------------------------------------------------------------------
# Helpers for the UI
# --------------------------------------------------------------------------------------
def pct(x, d=2):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:.{d}f}%"


def override_input(label, auto_value, key, help_text=None, is_pct=True, fmt="%.3f"):
    """Checkbox + number input. Returns the value in decimal form (if pct) and a flag."""
    use = st.checkbox(f"Override {label}", key=f"ov_{key}", help=help_text)
    shown = (auto_value * 100 if is_pct else auto_value) if auto_value is not None else 0.0
    val = st.number_input(
        f"{label}{' (%)' if is_pct else ''}", value=float(round(shown, 4)), step=0.05 if is_pct else 0.01,
        format=fmt, key=f"val_{key}", disabled=not use,
    )
    if use:
        return (val / 100 if is_pct else val), True
    return auto_value, False


# --------------------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="International Cost of Capital", page_icon="🌐", layout="wide")
    st.title("International Cost of Capital")
    st.caption("Cost of equity, cost of debt and WACC for a project in USD and in the "
               "currency of a selected country.")

    # ---------------- data ----------------
    with st.sidebar:
        if st.button("🔄 Refresh data", width="stretch",
                     help="Clear the cache and fetch all sources again"):
            st.cache_data.clear()
            st.rerun()

    with st.spinner("Fetching data…"):
        betas, spread, tax, ylds = fetch_betas(), fetch_spread(), fetch_tax(), fetch_yields()

    betas_df = betas["df"] if betas["ok"] else None
    if betas_df is None:
        st.warning(f"Could not fetch Damodaran betas ({betas['error']}). Upload betas.xls "
                   "below or use the manual unlevered beta override.")
        up = st.file_uploader("Upload Damodaran betas.xls", type=["xls", "xlsx"])
        if up is not None:
            try:
                betas_df, as_of = parse_betas(up.read())
                betas = {"ok": True, "df": betas_df, "as_of": as_of or "uploaded file",
                         "fetched": "uploaded"}
            except Exception as e:
                st.error(f"Could not parse the uploaded file: {e}")

    yld_df = ylds["df"]
    countries = yld_df["Country"].tolist()
    if DEFAULT_COUNTRY not in countries:
        countries = [DEFAULT_COUNTRY] + countries
    yld_map = dict(zip(yld_df["Country"], yld_df["Yield (%)"] / 100.0))
    yld_date = dict(zip(yld_df["Country"], yld_df["Date"]))

    # ---------------- sidebar inputs ----------------
    with st.sidebar:
        st.header("Project inputs")
        if betas_df is not None:
            inds = betas_df["Industry"].tolist()
            idx = inds.index(DEFAULT_INDUSTRY) if DEFAULT_INDUSTRY in inds else 0
            industry = st.selectbox("Industry", inds, index=idx)
            beta_auto = float(betas_df.loc[betas_df["Industry"] == industry,
                                           "Unlevered beta"].iloc[0])
        else:
            industry, beta_auto = "(manual beta)", None

        country = st.selectbox("Target country", countries,
                               index=countries.index(DEFAULT_COUNTRY))
        iso = TE_TO_ISO3.get(country)
        ccy = CURRENCY.get(iso, "LCY")
        fc = ccy if ccy != "USD" else f"USD ({country})"  # column label for the foreign side

        erp = st.number_input("Equity risk premium (%)", 0.0, 20.0, DEFAULT_ERP, 0.1) / 100
        debt_share = st.slider("Target debt share D/(D+E) (%)", 0.0, 90.0,
                               DEFAULT_DEBT, 1.0) / 100

        tax_basis = st.radio("Project tax rate", ["U.S.", "Selected country"],
                             horizontal=True, key="tax_basis",
                             help="The same tax rate is applied to both currency calculations.")

        with st.expander("Advanced: FX conversion method"):
            method_label = st.radio(
                "Convert USD rates to foreign currency with",
                ["Exact parity (multiplicative)", "Additive approximation"],
                help="Exact: (1+r_FC) = (1+r_USD)(1+y_FC)/(1+y_US). "
                     "Additive: r_FC = r_USD + (y_FC − y_US).")
            method = "exact" if method_label.startswith("Exact") else "additive"

        st.header("Manual overrides")
        st.caption("Tick a box to replace the fetched value.")
        tax_us_auto = tax["rates"].get("USA")
        tax_fc_auto = tax["rates"].get(iso) if iso else None
        y_us_auto = yld_map.get("United States")
        y_fc_auto = yld_map.get(country)
        spread_auto = spread["spread"] if spread["ok"] else None

        beta_u, ov_beta = override_input("Unlevered beta", beta_auto, "beta", is_pct=False)
        if beta_u is None:
            st.error("No beta available: tick the beta override and enter a value.")
            st.stop()
        tax_us, ov_tus = override_input("U.S. corporate tax rate", tax_us_auto, "tax_us")
        tax_fc, ov_tfc = override_input(f"{country} corporate tax rate", tax_fc_auto, "tax_fc")
        spread_usd, ov_spr = override_input("USD BBB spread", spread_auto, "spread")
        y_us, ov_yus = override_input("U.S. 10Y government yield", y_us_auto, "y_us")
        y_fc, ov_yfc = override_input(f"{country} 10Y government yield", y_fc_auto, "y_fc")

        missing = [n for n, v in [("U.S. tax rate", tax_us), ("USD BBB spread", spread_usd),
                                  ("U.S. yield", y_us), (f"{country} yield", y_fc)] if v is None]
        if tax_basis == "Selected country" and tax_fc is None:
            missing.append(f"{country} tax rate")
        if missing:
            st.error("Missing inputs: " + ", ".join(missing) + ". Use the overrides above.")
            st.stop()

        # preview auto foreign spread for the override widget
        t_proj = tax_us if tax_basis == "U.S." else tax_fc
        preview = cost_of_capital(beta_u, t_proj, debt_share, erp, y_us, y_fc, spread_usd,
                                  None, method)
        use_sfc = st.checkbox(f"Override {ccy} BBB spread", key="ov_sfc",
                              help="Off = implied spread from the USD BBB cost of debt "
                                   "converted at the yield differential.")
        sfc_val = st.number_input(f"{ccy} BBB spread (%)",
                                  value=float(round(preview["spread_fc_auto"] * 100, 4)),
                                  step=0.05, format="%.3f", key="val_sfc", disabled=not use_sfc)
        if not use_sfc:
            st.caption(f"Auto-calculated {ccy} spread: **{pct(preview['spread_fc_auto'], 3)}**")
        spread_fc_override = sfc_val / 100 if use_sfc else None

    # ---------------- calculation ----------------
    res = cost_of_capital(beta_u, t_proj, debt_share, erp, y_us, y_fc, spread_usd,
                          spread_fc_override, method)

    # ---------------- data sources ----------------
    def status(ok, overridden):
        return "Manual override" if overridden else ("Live" if ok else "Fallback")

    src = pd.DataFrame([
        ["Unlevered beta", industry, f"{beta_u:.3f}" if beta_u is not None else "n/a",
         "Damodaran, betas.xls (Industry Averages, Unlevered beta)",
         betas.get("as_of", "n/a"), status(betas["ok"], ov_beta), BETAS_URL],
        ["USD BBB spread", "Baa2/BBB, large non-financial", pct(spread_usd, 3),
         "Damodaran, ratings.html", spread.get("as_of", "n/a"),
         status(spread["ok"], ov_spr), RATINGS_URL],
        ["Corporate tax rate", "United States", pct(tax_us),
         tax["source"], str(tax["years"].get("USA", "n/a")), status(tax["ok"], ov_tus),
         OECD_PAGE_URL],
        ["Corporate tax rate", country, pct(tax_fc),
         tax["source"], str(tax["years"].get(iso, "n/a")) if iso else "n/a",
         status(tax["ok"] and tax_fc_auto is not None, ov_tfc), OECD_PAGE_URL],
        ["10Y government yield", "United States", pct(y_us, 3), "Trading Economics /bonds",
         yld_date.get("United States", "n/a"), status(ylds["ok"], ov_yus), TE_URL],
        ["10Y government yield", country, pct(y_fc, 3), "Trading Economics /bonds",
         yld_date.get(country, "n/a"), status(ylds["ok"], ov_yfc), TE_URL],
    ], columns=["Input", "Item", "Value used", "Source", "Data date", "Status", "Link"])

    with st.expander("📚 Data sources, dates and fetch status", expanded=False):
        st.dataframe(src, hide_index=True, width="stretch",
                     column_config={"Link": st.column_config.LinkColumn("Link")})
        st.caption(
            f"Fetched: betas {betas.get('fetched')}, spread {spread.get('fetched')}, "
            f"tax {tax.get('fetched')}, yields {ylds.get('fetched')}. "
            "Trading Economics shows month/day of each quote.")
        for name, d in [("Betas", betas), ("BBB spread", spread), ("Tax", tax), ("Yields", ylds)]:
            if not d["ok"] and "error" in d:
                st.warning(f"{name}: live fetch failed ({d['error']}). "
                           "Using fallback/manual values as labelled above.")

    tabs = st.tabs(["Results", "All-industry comparison", "Assumptions & method",
                    "Verification checks"])

    # ---------------- Results ----------------
    with tabs[0]:
        st.subheader(f"{industry} · project in {country} ({ccy})")
        st.caption(f"Tax rate applied: {pct(t_proj)} ({tax_basis}) · Debt share "
                   f"{pct(debt_share, 0)} · ERP {pct(erp)} · Levered beta {res['beta_l']:.3f}")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### USD")
            m = st.columns(3)
            m[0].metric("Cost of equity", pct(res["ke_usd"]))
            m[1].metric("Cost of debt (after tax)", pct(res["kd_usd_at"]))
            m[2].metric("WACC", pct(res["wacc_usd"]))
        with c2:
            st.markdown(f"#### {fc}")
            m = st.columns(3)
            m[0].metric("Cost of equity", pct(res["ke_fc"]),
                        delta=f"{(res['ke_fc'] - res['ke_usd']) * 1e4:+.0f} bp vs USD",
                        delta_color="off")
            m[1].metric("Cost of debt (after tax)", pct(res["kd_fc_at"]),
                        delta=f"{(res['kd_fc_at'] - res['kd_usd_at']) * 1e4:+.0f} bp vs USD",
                        delta_color="off")
            m[2].metric("WACC", pct(res["wacc_fc"]),
                        delta=f"{(res['wacc_fc'] - res['wacc_usd']) * 1e4:+.0f} bp vs USD",
                        delta_color="off")

        table = pd.DataFrame({
            "Component": ["10Y government yield", "Unlevered beta", "Levered beta",
                          "Equity risk premium", "Cost of equity", "BBB spread",
                          "Pre-tax cost of debt", "Tax rate", "After-tax cost of debt",
                          "Equity weight", "Debt weight", "WACC"],
            "USD": [pct(res["y_us"], 3), f"{res['beta_u']:.3f}", f"{res['beta_l']:.3f}",
                    pct(erp), pct(res["ke_usd"], 3), pct(res["spread_usd"], 3),
                    pct(res["kd_usd"], 3), pct(t_proj), pct(res["kd_usd_at"], 3),
                    pct(res["equity_share"], 1), pct(debt_share, 1), pct(res["wacc_usd"], 3)],
            fc: [
                pct(res["y_fc"], 3), f"{res['beta_u']:.3f}", f"{res['beta_l']:.3f}",
                pct(erp) + " (USD basis)", pct(res["ke_fc"], 3),
                pct(res["spread_fc"], 3) + (" (override)" if res["spread_fc_overridden"]
                                            else " (implied)"),
                pct(res["kd_fc"], 3), pct(t_proj), pct(res["kd_fc_at"], 3),
                pct(res["equity_share"], 1), pct(debt_share, 1), pct(res["wacc_fc"], 3)],
        })
        st.dataframe(table, hide_index=True, width="stretch")

        chart = pd.DataFrame(
            {"USD": [res["ke_usd"], res["kd_usd_at"], res["wacc_usd"]],
             fc: [res["ke_fc"], res["kd_fc_at"], res["wacc_fc"]]},
            index=["Cost of equity", "After-tax cost of debt", "WACC"]) * 100
        st.bar_chart(chart, stack=False, y_label="%")

        inputs_df = pd.DataFrame({
            "Parameter": ["Industry", "Country", "Currency", "Tax basis", "Tax rate",
                          "Debt share", "ERP", "Unlevered beta", "USD BBB spread",
                          f"{ccy} BBB spread", "Spread override", "U.S. 10Y yield",
                          f"{country} 10Y yield", "FX conversion method", "Generated"],
            "Value": [industry, country, ccy, tax_basis, t_proj, debt_share, erp, beta_u,
                      spread_usd, res["spread_fc"], res["spread_fc_overridden"], y_us, y_fc,
                      method, _now()],
        })
        results_df = pd.DataFrame({
            "Metric": ["Levered beta", "Cost of equity", "Pre-tax cost of debt",
                       "After-tax cost of debt", "WACC"],
            "USD": [res["beta_l"], res["ke_usd"], res["kd_usd"], res["kd_usd_at"],
                    res["wacc_usd"]],
            fc: [res["beta_l"], res["ke_fc"], res["kd_fc"], res["kd_fc_at"], res["wacc_fc"]],
        })
        st.session_state["_export"] = (inputs_df, results_df, src)

        d1, d2 = st.columns(2)
        d1.download_button("⬇️ Download results (CSV)",
                           pd.concat([inputs_df.astype(str),
                                      results_df.astype(str).rename(columns={"Metric": "Parameter"})],
                                     ignore_index=True).to_csv(index=False).encode(),
                           file_name="cost_of_capital_results.csv", mime="text/csv",
                           width="stretch")

    # ---------------- All industries ----------------
    with tabs[1]:
        if betas_df is None:
            st.info("All-industry comparison needs the Damodaran beta table.")
            all_df = None
        else:
            rows = []
            for r in betas_df.itertuples(index=False):
                o = cost_of_capital(r[1], t_proj, debt_share, erp, y_us, y_fc, spread_usd,
                                    spread_fc_override, method)
                rows.append([r[0], r[1], o["beta_l"], o["ke_usd"], o["ke_fc"],
                             o["wacc_usd"], o["wacc_fc"]])
            all_df = pd.DataFrame(rows, columns=[
                "Industry", "Unlevered beta", "Levered beta", "Cost of equity USD",
                f"Cost of equity {fc}", "WACC USD", f"WACC {fc}"])
            st.caption(f"Same inputs for every industry: {country}, tax {pct(t_proj)}, "
                       f"debt {pct(debt_share, 0)}, ERP {pct(erp)}. Uses fetched betas "
                       "(the manual beta override applies only to the selected industry).")
            show = all_df.copy()
            for c in show.columns[3:]:
                show[c] = show[c] * 100
            st.dataframe(
                show, hide_index=True, width="stretch", height=480,
                column_config={c: st.column_config.NumberColumn(format="%.2f%%")
                               for c in show.columns[3:]} | {
                    "Unlevered beta": st.column_config.NumberColumn(format="%.3f"),
                    "Levered beta": st.column_config.NumberColumn(format="%.3f")})
            top = show.sort_values(f"WACC {fc}", ascending=False).set_index("Industry")
            st.markdown(f"**WACC by industry ({ccy})**, highest to lowest")
            st.bar_chart(top[[f"WACC {fc}"]], y_label="%", height=420)
            st.download_button("⬇️ Download all-industry table (CSV)",
                               all_df.to_csv(index=False).encode(),
                               file_name="all_industry_cost_of_capital.csv", mime="text/csv")

    # Excel with everything
    with tabs[0]:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as xw:
            inputs_df.to_excel(xw, sheet_name="Inputs", index=False)
            results_df.to_excel(xw, sheet_name="Results", index=False)
            src.to_excel(xw, sheet_name="Sources", index=False)
            if all_df is not None:
                all_df.to_excel(xw, sheet_name="All industries", index=False)
        d2.download_button("⬇️ Download full workbook (Excel)", buf.getvalue(),
                           file_name="cost_of_capital.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           width="stretch")

    # ---------------- Assumptions ----------------
    with tabs[2]:
        st.markdown(f"""
**Approach.** The project is valued as a U.S.-style CAPM project: all risk is priced in USD
first, then translated into {ccy} using the difference in 10-year government yields as the
expected inflation / depreciation differential.

1. **Relever the beta** (Hamada), using the project tax rate and target capital structure:
   β<sub>L</sub> = β<sub>U</sub> × [1 + (1 − t) × D/E], with D/E = w<sub>D</sub> / (1 − w<sub>D</sub>).
2. **USD cost of equity**: k<sub>E,USD</sub> = y<sub>US</sub> + β<sub>L</sub> × ERP.
3. **USD cost of debt**: k<sub>D,USD</sub> = y<sub>US</sub> + BBB spread; after tax × (1 − t).
4. **Translate to {ccy}** (exact parity by default):
   (1 + k<sub>{ccy}</sub>) = (1 + k<sub>USD</sub>) × (1 + y<sub>{ccy}</sub>) / (1 + y<sub>US</sub>).
   The additive option uses k<sub>{ccy}</sub> = k<sub>USD</sub> + (y<sub>{ccy}</sub> − y<sub>US</sub>).
5. **{ccy} cost of debt** = y<sub>{ccy}</sub> + {ccy} BBB spread. When the spread override is
   off, the spread is implied by translating the USD pre-tax cost of debt (step 4) and
   subtracting y<sub>{ccy}</sub>. When it is on, the entered spread is used and USD results
   are unaffected.
6. **WACC** = w<sub>E</sub> × k<sub>E</sub> + w<sub>D</sub> × k<sub>D</sub> × (1 − t), using one
   project tax rate (U.S. or selected country) for both currencies.

**Key assumptions and caveats**
- Damodaran's unlevered betas are U.S. industry averages; the project is assumed to carry the
  same business risk abroad. No separate country risk premium is added beyond what the yield
  differential carries.
- The 10-year government yield is the risk-free rate in each currency. For countries whose
  sovereign is not default-free, the local yield includes default risk, so the {ccy} rates are
  an upper bound on a pure inflation translation.
- The ERP is entered on a USD basis and is not changed by the currency translation except
  through the multiplicative parity term.
- The BBB spread is Damodaran's synthetic-rating spread for large non-financial firms and
  is assumed to describe the project's borrowing cost.
- Tax rates are OECD combined (central + sub-central) statutory CIT rates.
""", unsafe_allow_html=True)

    # ---------------- Verification ----------------
    with tabs[3]:
        st.markdown("These checks rerun the model with the current inputs and confirm the "
                    "properties the assignment asks for.")
        tol = 1e-12
        eq = cost_of_capital(beta_u, t_proj, debt_share, erp, y_us, y_us, spread_usd, None, method)
        z = cost_of_capital(beta_u, t_proj, 0.0, erp, y_us, y_fc, spread_usd,
                            spread_fc_override, method)
        base = cost_of_capital(beta_u, t_proj, debt_share, erp, y_us, y_fc, spread_usd,
                               None, method)
        ov = cost_of_capital(beta_u, t_proj, debt_share, erp, y_us, y_fc, spread_usd,
                             base["spread_fc_auto"] + 0.02, method)
        checks = pd.DataFrame([
            ["Equal yields (y_FC = y_US, spread override off) → equal results",
             max(abs(eq["ke_usd"] - eq["ke_fc"]), abs(eq["kd_usd"] - eq["kd_fc"]),
                 abs(eq["wacc_usd"] - eq["wacc_fc"]))],
            ["Zero debt → WACC = cost of equity (USD)", abs(z["wacc_usd"] - z["ke_usd"])],
            [f"Zero debt → WACC = cost of equity ({ccy})", abs(z["wacc_fc"] - z["ke_fc"])],
            [f"Overriding {ccy} spread (+2pp) leaves USD results unchanged",
             max(abs(base["ke_usd"] - ov["ke_usd"]), abs(base["kd_usd"] - ov["kd_usd"]),
                 abs(base["wacc_usd"] - ov["wacc_usd"]))],
        ], columns=["Check", "Max absolute difference"])
        checks["Result"] = np.where(checks["Max absolute difference"] < tol, "✅ Pass", "❌ Fail")
        st.dataframe(checks, hide_index=True, width="stretch")

        st.markdown("#### Hand-check worksheet (current inputs)")
        de = debt_share / (1 - debt_share) if debt_share < 1 else np.nan
        steps = pd.DataFrame([
            ["D/E", f"{debt_share:.4f} / {1 - debt_share:.4f}", f"{de:.6f}"],
            ["Levered beta", f"{beta_u:.4f} × [1 + (1 − {t_proj:.4f}) × {de:.6f}]",
             f"{res['beta_l']:.6f}"],
            ["k_E USD", f"{y_us:.6f} + {res['beta_l']:.6f} × {erp:.4f}", f"{res['ke_usd']:.6f}"],
            ["k_D USD pre-tax", f"{y_us:.6f} + {spread_usd:.6f}", f"{res['kd_usd']:.6f}"],
            ["WACC USD", f"{1 - debt_share:.4f} × {res['ke_usd']:.6f} + {debt_share:.4f} × "
             f"{res['kd_usd']:.6f} × (1 − {t_proj:.4f})", f"{res['wacc_usd']:.6f}"],
            [f"k_E {ccy}", (f"(1 + {res['ke_usd']:.6f}) × (1 + {y_fc:.6f}) / (1 + {y_us:.6f}) − 1"
                            if method == "exact" else
                            f"{res['ke_usd']:.6f} + ({y_fc:.6f} − {y_us:.6f})"),
             f"{res['ke_fc']:.6f}"],
            [f"k_D {ccy} pre-tax", f"{y_fc:.6f} + {res['spread_fc']:.6f}", f"{res['kd_fc']:.6f}"],
            [f"WACC {ccy}", f"{1 - debt_share:.4f} × {res['ke_fc']:.6f} + {debt_share:.4f} × "
             f"{res['kd_fc']:.6f} × (1 − {t_proj:.4f})", f"{res['wacc_fc']:.6f}"],
        ], columns=["Step", "Formula with numbers", "Result (decimal)"])
        st.dataframe(steps, hide_index=True, width="stretch")


if __name__ == "__main__":
    main()
