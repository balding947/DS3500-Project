"""
Data pipeline: loads raw data, cleans each source, validates quality, saves as Parquet.
Run after acquire.py has fetched raw data into data/raw/.
"""

import json
from pathlib import Path

import pandas as pd

RAW_FOLDER = Path("data/raw")
CLEANED_FOLDER = Path("data/cleaned")
CLEANED_FOLDER.mkdir(parents=True, exist_ok=True)

TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
    "META", "TSLA", "AVGO", "JPM", "WMT",
]


# ── Load ──────────────────────────────────────────────────────────────────────

def load_stock_prices() -> pd.DataFrame:
    path = RAW_FOLDER / "daily_stock_prices_raw.csv"
    assert path.exists(), f"Missing raw file: {path}"
    return pd.read_csv(path)


def load_news_sentiment() -> pd.DataFrame:
    path = RAW_FOLDER / "news_sentiment_raw.json"
    assert path.exists(), f"Missing raw file: {path}"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    feed = data.get("feed", [])
    if not feed:
        print("  [warning] news_sentiment_raw.json contains no articles")
        return pd.DataFrame()

    rows = []
    for article in feed:
        base = {
            "title": article.get("title"),
            "url": article.get("url"),
            "time_published": article.get("time_published"),
            "source": article.get("source"),
            "overall_sentiment_score": article.get("overall_sentiment_score"),
            "overall_sentiment_label": article.get("overall_sentiment_label"),
        }
        for ticker_item in article.get("ticker_sentiment", []):
            row = base.copy()
            row["symbol"] = ticker_item.get("ticker")
            row["ticker_relevance_score"] = ticker_item.get("relevance_score")
            row["ticker_sentiment_score"] = ticker_item.get("ticker_sentiment_score")
            row["ticker_sentiment_label"] = ticker_item.get("ticker_sentiment_label")
            rows.append(row)

    return pd.DataFrame(rows)


def load_sp500_companies() -> pd.DataFrame:
    path = RAW_FOLDER / "sp500_companies_raw.csv"
    assert path.exists(), f"Missing raw file: {path}"
    return pd.read_csv(path)


# ── Clean ─────────────────────────────────────────────────────────────────────

def clean_stock_prices(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Types
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ["open", "high", "low", "close", "adjusted_close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df["symbol"] = df["symbol"].str.upper().str.strip()

    # Filter to our tickers
    df = df[df["symbol"].isin(TICKERS)]

    # Remove full duplicates, then keep last per (date, symbol)
    df = df.drop_duplicates()
    df = df.drop_duplicates(subset=["date", "symbol"], keep="last")

    # Sort so ffill is chronological within each ticker
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    # Forward-fill price gaps within each symbol (market holidays that slipped in)
    price_cols = ["open", "high", "low", "close", "adjusted_close"]
    df[price_cols] = df.groupby("symbol")[price_cols].ffill()

    # Drop rows still missing close price (no prior day to fill from)
    df = df.dropna(subset=["close"])

    # Drop rows with missing or negative volume
    df = df.dropna(subset=["volume"])
    df = df[df["volume"] >= 0]

    # Derived feature
    df["daily_return"] = df.groupby("symbol")["adjusted_close"].pct_change()

    return df.reset_index(drop=True)


def clean_news_sentiment(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.copy()

    # Parse timestamp; Alpha Vantage format: 20260122T120000
    df["time_published"] = pd.to_datetime(
        df["time_published"], format="%Y%m%dT%H%M%S", errors="coerce"
    )
    df["date"] = df["time_published"].dt.normalize()

    # Numeric sentiment
    for col in ["overall_sentiment_score", "ticker_relevance_score", "ticker_sentiment_score"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Standardize symbol
    df["symbol"] = df["symbol"].str.upper().str.strip()

    # Filter to our tickers
    df = df[df["symbol"].isin(TICKERS)]

    # Deduplicate on (url, symbol) — same article can mention multiple tickers
    df = df.drop_duplicates(subset=["url", "symbol"])

    # Fill missing sentiment scores with neutral (0 = no signal)
    df["overall_sentiment_score"] = df["overall_sentiment_score"].fillna(0.0)
    df["ticker_sentiment_score"] = df["ticker_sentiment_score"].fillna(0.0)
    df["ticker_relevance_score"] = df["ticker_relevance_score"].fillna(0.0)

    return df.sort_values(["symbol", "date"]).reset_index(drop=True)


def clean_sp500_companies(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df = df.rename(columns={
        "Symbol": "symbol",
        "Security": "company_name",
        "GICS Sector": "sector",
        "GICS Sub-Industry": "sub_industry",
        "Headquarters Location": "headquarters",
        "Date added": "date_added",
        "CIK": "cik",
        "Founded": "founded",
    })

    df["symbol"] = df["symbol"].str.upper().str.strip()

    # Deduplicate: keep first entry per symbol
    df = df.drop_duplicates(subset=["symbol"], keep="first")

    # Filter to our tickers
    df = df[df["symbol"].isin(TICKERS)].reset_index(drop=True)

    df["date_added"] = pd.to_datetime(df["date_added"], errors="coerce")

    return df


# ── Validate ──────────────────────────────────────────────────────────────────

def validate_stock_prices(df: pd.DataFrame) -> None:
    assert not df.empty, "Stock prices DataFrame is empty after cleaning"
    assert df["date"].isna().sum() == 0, "Stock prices has null dates"
    assert df["close"].isna().sum() == 0, "Stock prices has null close prices"
    assert (df["close"] > 0).all(), "Stock prices has non-positive close prices"
    assert (df["volume"] >= 0).all(), "Stock prices has negative volume"
    assert (df["high"] >= df["low"]).all(), "Stock prices: high < low detected"
    assert df.duplicated(subset=["date", "symbol"]).sum() == 0, \
        "Duplicate (date, symbol) rows in stock prices"
    assert set(df["symbol"].unique()).issubset(set(TICKERS)), \
        "Unexpected tickers in stock prices"
    print(
        f"  [OK] stock_prices — {len(df)} rows, "
        f"{df['symbol'].nunique()} tickers, "
        f"{df['date'].min().date()} to {df['date'].max().date()}"
    )


def validate_news_sentiment(df: pd.DataFrame) -> None:
    if df.empty:
        print("  [skip] news_sentiment — empty (no articles fetched)")
        return
    assert df["date"].isna().sum() == 0, "News sentiment has null dates"
    assert df["symbol"].isna().sum() == 0, "News sentiment has null symbols"
    assert df.duplicated(subset=["url", "symbol"]).sum() == 0, \
        "Duplicate (url, symbol) rows in news sentiment"
    assert df["overall_sentiment_score"].between(-1, 1).all(), \
        "Overall sentiment scores outside [-1, 1]"
    assert df["ticker_sentiment_score"].between(-1, 1).all(), \
        "Ticker sentiment scores outside [-1, 1]"
    print(
        f"  [OK] news_sentiment — {len(df)} rows, "
        f"{df['symbol'].nunique()} tickers, "
        f"{df['article_count'] if 'article_count' in df.columns else 'N/A'} articles"
    )


def validate_sp500_companies(df: pd.DataFrame) -> None:
    assert not df.empty, "S&P 500 companies DataFrame is empty after cleaning"
    assert df.duplicated(subset=["symbol"]).sum() == 0, \
        "Duplicate symbols in S&P 500 companies"
    assert df["sector"].isna().sum() == 0, \
        "S&P 500 companies has null sectors"
    assert set(TICKERS).issubset(set(df["symbol"].unique())), \
        f"Missing tickers in S&P 500 data: {set(TICKERS) - set(df['symbol'].unique())}"
    print(f"  [OK] sp500_companies — {len(df)} rows, sectors: {sorted(df['sector'].unique())}")


# ── Run ───────────────────────────────────────────────────────────────────────

def run_pipeline():
    print("=== Loading raw data ===")
    stock_raw = load_stock_prices()
    news_raw = load_news_sentiment()
    sp500_raw = load_sp500_companies()
    print(f"  stock_prices:    {len(stock_raw)} rows")
    print(f"  news_sentiment:  {len(news_raw)} rows")
    print(f"  sp500_companies: {len(sp500_raw)} rows")

    print("\n=== Cleaning data ===")
    stock_clean = clean_stock_prices(stock_raw)
    news_clean = clean_news_sentiment(news_raw)
    sp500_clean = clean_sp500_companies(sp500_raw)
    print(f"  stock_prices:    {len(stock_clean)} rows")
    print(f"  news_sentiment:  {len(news_clean)} rows")
    print(f"  sp500_companies: {len(sp500_clean)} rows")

    print("\n=== Validating cleaned data ===")
    validate_stock_prices(stock_clean)
    validate_news_sentiment(news_clean)
    validate_sp500_companies(sp500_clean)

    print("\n=== Saving cleaned data (zipped CSV) ===")
    stock_out = CLEANED_FOLDER / "daily_stock_prices_cleaned.csv.gz"
    stock_clean.to_csv(stock_out, index=False, compression="gzip")
    print(f"  Saved: {stock_out}")

    sp500_out = CLEANED_FOLDER / "sp500_companies_cleaned.csv.gz"
    sp500_clean.to_csv(sp500_out, index=False, compression="gzip")
    print(f"  Saved: {sp500_out}")

    if not news_clean.empty:
        news_out = CLEANED_FOLDER / "news_sentiment_cleaned.csv.gz"
        news_clean.to_csv(news_out, index=False, compression="gzip")
        print(f"  Saved: {news_out}")
    else:
        print("  Skipped: news_sentiment_cleaned.csv.gz (no data)")

    print("\n=== Pipeline complete ===")
    return stock_clean, news_clean, sp500_clean


if __name__ == "__main__":
    run_pipeline()
