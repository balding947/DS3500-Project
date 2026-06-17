# DS3500 Project — Stock Prices & News Sentiment

Analyzes daily stock performance, sector trends, volatility, and news sentiment
for ten large-cap U.S. stocks starting 2026-01-22.

## Data Sources

| Source | Provider | Type | Used for |
|---|---|---|---|
| Daily stock prices | [EODHD](https://eodhd.com/) | REST API | OHLC, adjusted close, volume |
| News sentiment | [Alpha Vantage](https://www.alphavantage.co/) | REST API | Per-article and per-ticker sentiment scores |
| S&P 500 companies | [datasets/s-and-p-500-companies](https://github.com/datasets/s-and-p-500-companies) | Static CSV | Company name, GICS sector / sub-industry |

**Tickers:** `AAPL` `MSFT` `NVDA` `AMZN` `GOOGL` `META` `TSLA` `AVGO` `JPM` `WMT`

See [API_DOCUMENTATION.md](API_DOCUMENTATION.md) for API keys and rate limits.

## Project Structure

```
├── acquire.py           # Stage 1 — fetch raw data from all sources → data/raw/
├── pipeline.py          # Stage 2 — clean, validate             → data/cleaned/
├── merge.py             # Stage 3 — aggregate + join            → data/processed/
├── data.py              # Dashboard data helpers
├── visualization.py     # Plotly chart functions
├── ui.py                # Panel dashboard
├── test_pipeline.py     # pytest suite (17 tests)
└── data/
    ├── raw/             # Untouched API responses (CSV / JSON)
    ├── cleaned/         # Per-source cleaned tables (.csv.gz)
    └── processed/       # Final merged dataset (.csv.gz)
```

## Setup

```bash
pip install pandas requests pytest panel plotly
```

## Running the Pipeline

Run in order from the project root:

```bash
python acquire.py    # fetch from APIs  → data/raw/
python pipeline.py   # clean + validate → data/cleaned/
python merge.py      # merge all        → data/processed/merged_dataset.csv.gz
```

Each stage validates its output with assertions and aborts if any check fails.

## Data Cleaning Decisions

All cleaning is in `pipeline.py` (`clean_*` functions). Values that can't be
parsed become `NaN` via `errors="coerce"` and are handled by explicit rules.

**Stock prices (`clean_stock_prices`)**
- Coerce `date` → datetime; price/volume columns → numeric
- Standardize and filter symbols to the 10 project tickers
- Drop exact duplicates; for duplicate `(date, symbol)` keep the last row (treats it as a correction)
- Forward-fill price gaps within each ticker (covers stray non-trading days)
- Drop rows missing `close` or with negative/missing volume
- Add `daily_return` = per-symbol % change of `adjusted_close`

**News sentiment (`clean_news_sentiment`)**
- Parse Alpha Vantage's `time_published` (`YYYYMMDDTHHMMSS`) → datetime; derive `date` as the join key
- Coerce sentiment/relevance scores to numeric; fill missing scores with `0.0` (no signal)
- Filter to project tickers; deduplicate on `(url, symbol)`

**S&P 500 companies (`clean_sp500_companies`)**
- Rename GICS headers to snake_case (`GICS Sector` → `sector`, etc.)
- Deduplicate on `symbol`; filter to the 10 project tickers

## Validation

Each source is validated before saving (`validate_*` in `pipeline.py`, `validate_merged` in `merge.py`):

- **Prices** — no null dates/closes, `close > 0`, `volume ≥ 0`, `high ≥ low`, no duplicate `(date, symbol)`
- **News** — no null dates/symbols, no duplicate `(url, symbol)`, scores within `[-1, 1]`
- **Companies** — no duplicate symbols, no null sectors, all 10 tickers present
- **Merged** — no duplicate `(symbol, date)`, no null `sector`/`company_name`, `close > 0`

## Merge Strategy

`merge.py` joins in two steps:

1. **Aggregate sentiment** — group article rows by `(symbol, date)` into daily stats:
   `sentiment_score_mean`, `sentiment_score_std`, `ticker_sentiment_mean`, `article_count`, `dominant_sentiment_label`

2. **Join:**
   - `stock_prices` **LEFT JOIN** `sp500_companies` on `symbol` → adds sector metadata
   - result **LEFT JOIN** daily sentiment on `(symbol, date)` → adds sentiment (NaN where no news)

Left joins keep every trading day; missing news appears as `NaN`, not a dropped row.

## Output

`data/processed/merged_dataset.csv.gz` — **1,000 rows × 17 columns**

| Column | Source | Description |
|---|---|---|
| `date`, `symbol` | prices | Primary key |
| `open`, `high`, `low`, `close`, `adjusted_close`, `volume` | prices | Daily OHLCV |
| `daily_return` | derived | % change of `adjusted_close` |
| `company_name`, `sector`, `sub_industry` | S&P 500 | Company metadata |
| `sentiment_score_mean`, `sentiment_score_std` | news | Daily sentiment stats |
| `ticker_sentiment_mean`, `article_count`, `dominant_sentiment_label` | news | Per-ticker sentiment |

## Running the Dashboard

Make sure the pipeline has been run first (so `data/processed/merged_dataset.csv.gz` exists), then:

```bash
panel serve ui.py --show
```

This opens the dashboard automatically in your browser at `http://localhost:5006/ui`.

The dashboard has four tabs:
- **Viz 1 — Overview** — all 10 stocks indexed to 100, filterable by sector/ticker/date
- **Viz 2 — Stock Drill-Down** — candlestick chart with volume and sentiment for one stock
- **Viz 3 — Risk/Return Animation** — animated scatter of cumulative return vs volatility (use the Player widget in the sidebar)
- **Viz 4 — Rolling Volatility** — rolling annualized volatility with configurable window

Use the sidebar filters to narrow by date range, sector, ticker, or minimum volume. Click **Reset All Filters** to restore defaults.

## Testing

```bash
pytest -v
```

17 tests in `test_pipeline.py` covering all four areas using small synthetic offline fixtures
(HTTP layer mocked with `unittest.mock`):

| Area | Tests |
|---|---|
| Data loading & API access | 4 |
| Cleaning functions | 6 |
| Merge logic | 3 |
| Data validation | 4 |
