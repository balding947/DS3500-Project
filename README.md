# DS3500 Project — Stock Prices & News Sentiment

A reproducible data pipeline that assembles a single analysis-ready dataset
linking **daily stock prices**, **financial-news sentiment**, and **company
metadata** for ten large-cap U.S. stocks, covering 2026-01-22 onward.

The final output is one row per (ticker, trading day) enriched with that day's
aggregated news sentiment and the company's S&P 500 sector classification.

## Data sources

| Source | Provider | Type | Used for |
| --- | --- | --- | --- |
| Daily stock prices | [EODHD](https://eodhd.com/) `/api/eod` | REST API | OHLC, adjusted close, volume |
| News sentiment | [Alpha Vantage](https://www.alphavantage.co/) `NEWS_SENTIMENT` | REST API | Article-level + per-ticker sentiment scores |
| S&P 500 companies | [datasets/s-and-p-500-companies](https://github.com/datasets/s-and-p-500-companies) | Static CSV | Company name, GICS sector / sub-industry |

See [API_DOCUMENTATION.md](API_DOCUMENTATION.md) for API keys, rate limits, and
access restrictions.

**Ticker universe** (10 stocks): `AAPL`, `MSFT`, `NVDA`, `AMZN`, `GOOGL`,
`META`, `TSLA`, `AVGO`, `JPM`, `WMT`.

## Project structure

```
.
├── acquire.py            # Stage 1 — fetch raw data from APIs into data/raw/
├── pipeline.py           # Stage 2 — load, clean, validate -> data/cleaned/
├── merge.py              # Stage 3 — aggregate + join -> data/processed/
├── test_pipeline.py      # pytest suite for stages 1–3
├── API_DOCUMENTATION.md  # API keys, rate limits, access notes
└── data/
    ├── raw/              # Untouched API responses (CSV / JSON)
    ├── sample/           # First 100 rows of each source (for quick inspection)
    ├── cleaned/          # Per-source cleaned & validated tables (.csv.gz)
    └── processed/        # Final merged dataset (.csv.gz)
```

## Setup

Requires Python 3.10+ and the following packages:

```bash
pip install pandas requests pytest
```

API keys are currently set at the top of [acquire.py](acquire.py). The EODHD and
Alpha Vantage free tiers are rate-limited (Alpha Vantage allows ~25 requests/day),
so `acquire.py` **caches raw responses** and skips an API call whenever the
corresponding file already exists in `data/raw/`. Delete a raw file to force a
re-fetch.

## Running the pipeline

Run the three stages in order from the project root:

```bash
python acquire.py     # Stage 1: APIs        -> data/raw/  + data/sample/
python pipeline.py    # Stage 2: clean        -> data/cleaned/
python merge.py       # Stage 3: merge        -> data/processed/merged_dataset.csv.gz
```

```
acquire.py  ─▶  data/raw/        ─▶  pipeline.py  ─▶  data/cleaned/   ─▶  merge.py  ─▶  data/processed/
 (fetch)        raw CSV / JSON       (clean +          per-source          (aggregate     merged_dataset
                                      validate)         .csv.gz tables       + join)        .csv.gz
```

Each stage prints a progress report and runs assertion-based validation; the run
aborts loudly if any quality check fails.

## Data cleaning decisions

All cleaning lives in `pipeline.py` (`clean_*` functions). Type coercion uses
`errors="coerce"` throughout so malformed values become `NaN` and are handled by
explicit rules rather than crashing the parse.

### Stock prices (`clean_stock_prices`)

- **Type coercion** — `date` → datetime; `open/high/low/close/adjusted_close` and
  `volume` → numeric.
- **Symbol standardization** — uppercased and stripped, then filtered to the 10
  project tickers.
- **Deduplication** — drop exact-duplicate rows, then for any remaining duplicate
  `(date, symbol)` keep the **last** occurrence (treats a later row as a
  correction/restatement of an earlier one).
- **Forward-fill price gaps** — sorted chronologically within each symbol, then
  `ffill` on the price columns to cover stray non-trading days. Rows still missing
  `close` (no prior day to fill from) are dropped.
- **Volume rules** — drop rows with missing volume or negative volume (invalid).
- **Derived feature** — `daily_return`, the per-symbol percentage change of
  `adjusted_close`.

### News sentiment (`clean_news_sentiment`)

- **Timestamp parsing** — Alpha Vantage's `time_published` (`YYYYMMDDTHHMMSS`) is
  parsed to datetime; a normalized `date` column is derived as the join key to the
  price data.
- **Numeric sentiment** — sentiment and relevance scores coerced to numeric.
- **Symbol standardization + ticker filter** — same as prices.
- **Deduplication** — on `(url, symbol)`, because one article can reference
  multiple tickers and should produce one row per ticker it mentions.
- **Missing scores → neutral** — missing `overall`/`ticker` sentiment and relevance
  scores are filled with `0.0` (treated as "no signal" rather than dropped).

### S&P 500 companies (`clean_sp500_companies`)

- **Column rename** — GICS headers → snake_case (`Symbol` → `symbol`,
  `GICS Sector` → `sector`, etc.).
- **Symbol standardization**, then **deduplication** on `symbol` (keep first),
  then filter to the 10 project tickers.
- **Type coercion** — `date_added` → datetime.

### Validation (assertions, fail-fast)

Each cleaned source is checked before it is saved (`validate_*` in `pipeline.py`,
`validate_merged` in `merge.py`):

- **Prices** — non-empty; no null `date`/`close`; `close > 0`; `volume ≥ 0`;
  `high ≥ low`; no duplicate `(date, symbol)`; only known tickers.
- **News** — no null `date`/`symbol`; no duplicate `(url, symbol)`; sentiment
  scores within `[-1, 1]`.
- **Companies** — non-empty; no duplicate symbols; no null sector; all 10 project
  tickers present.
- **Merged** — non-empty; no duplicate `(symbol, date)`; only known tickers; no
  null `sector`/`company_name` (a null would mean the company join failed);
  `close > 0`.

## Merge strategy

`merge.py` produces the final dataset in two steps:

1. **Aggregate sentiment to daily granularity** (`aggregate_sentiment`) — article
   rows are grouped by `(symbol, date)` into `sentiment_score_mean`,
   `sentiment_score_std` (filled `0.0` when a day has a single article),
   `ticker_sentiment_mean`, `article_count`, and `dominant_sentiment_label` (the
   modal label).
2. **Join** (`merge_all`):
   - stock prices `LEFT JOIN` company metadata `ON symbol` — every price row gets
     its sector/sub-industry.
   - result `LEFT JOIN` daily sentiment `ON (symbol, date)` — every price row is
     preserved; days with no news get `NaN` sentiment columns.

Left joins are deliberate: trading days are the backbone, and missing news is
represented as `NaN`, never as a dropped row.

## Output

`data/processed/merged_dataset.csv.gz` — **1,000 rows × 17 columns**, 10 tickers,
covering **2026-01-22 → 2026-06-15**, with news-sentiment coverage on **~83% of
trading days**.

| Column | Source | Description |
| --- | --- | --- |
| `date`, `symbol` | prices | Primary key (trading day × ticker) |
| `open`, `high`, `low`, `close`, `adjusted_close`, `volume` | prices | Daily OHLCV |
| `daily_return` | derived | Per-symbol % change of `adjusted_close` |
| `company_name`, `sector`, `sub_industry` | S&P 500 | Company metadata |
| `sentiment_score_mean`, `sentiment_score_std` | news | Daily overall-sentiment stats |
| `ticker_sentiment_mean` | news | Daily mean ticker-specific sentiment |
| `article_count` | news | Number of articles that day (`NaN` = no news) |
| `dominant_sentiment_label` | news | Modal sentiment label that day |

## Testing

```bash
pytest -v
```

`test_pipeline.py` covers all four areas with small synthetic, offline fixtures
(the HTTP layer is mocked with `unittest.mock`): data loading & API access,
cleaning functions, merge logic, and data validation.
