"""cleans and validates each raw source, saves cleaned tables to data/cleaned"""

import json
from pathlib import Path
import pandas as pd


RAW_FOLDER     = Path("data/raw")
CLEANED_FOLDER = Path("data/cleaned")
CLEANED_FOLDER.mkdir(parents=True, exist_ok=True)

TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "WMT"]
PRICE_COLS = ["open", "high", "low", "close", "adjusted_close"]


# Load

def load_stock_prices() -> pd.DataFrame:
    path = RAW_FOLDER / "daily_stock_prices_raw.csv"
    assert path.exists(), f"Missing: {path}"
    return pd.read_csv(path)


def load_news_sentiment() -> pd.DataFrame:
    path = RAW_FOLDER / "news_sentiment_raw.json"
    assert path.exists(), f"Missing: {path}"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    feed = data.get("feed", [])
    if not feed:
        print("  [warning] no articles in news_sentiment_raw.json")
        return pd.DataFrame()

    rows = []
    for article in feed:
        base = {
            "title":                   article.get("title"),
            "url":                     article.get("url"),
            "time_published":          article.get("time_published"),
            "source":                  article.get("source"),
            "overall_sentiment_score": article.get("overall_sentiment_score"),
            "overall_sentiment_label": article.get("overall_sentiment_label"),
        }
        # one article can mention many tickers → create one row per ticker per article
        for t in article.get("ticker_sentiment", []):
            rows.append({**base,
                "symbol":                 t.get("ticker"),
                "ticker_relevance_score": t.get("relevance_score"),
                "ticker_sentiment_score": t.get("ticker_sentiment_score"),
                "ticker_sentiment_label": t.get("ticker_sentiment_label"),
            })

    return pd.DataFrame(rows)


def load_sp500_companies() -> pd.DataFrame:
    path = RAW_FOLDER / "sp500_companies_raw.csv"
    assert path.exists(), f"Missing: {path}"
    return pd.read_csv(path)


# Clean

def clean_stock_prices(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # errors="coerce" turns anything unparseable into NaN instead of crashing
    df["date"]   = pd.to_datetime(df["date"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df["symbol"] = df["symbol"].str.upper().str.strip()
    for col in PRICE_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df[df["symbol"].isin(TICKERS)]       # drop any ticker not in our 10-stock universe
    df = df.drop_duplicates()                  # remove exact duplicate rows
    # if same (date, symbol) appears twice, keep the last — treat it as a data correction
    df = df.drop_duplicates(subset=["date", "symbol"], keep="last")
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    # forward-fill price gaps: carries the last known price forward into missing days
    # grouped by symbol so one stock's prices don't bleed into another's
    df[PRICE_COLS] = df.groupby("symbol")[PRICE_COLS].ffill()

    df = df.dropna(subset=["close", "volume"])  # drop rows still missing after ffill
    df = df[df["volume"] >= 0]                  # negative volume is impossible, drop it

    # daily_return = % change in adjusted_close, computed per ticker (groupby prevents
    # the first row of ticker B from comparing against the last row of ticker A)
    df["daily_return"] = df.groupby("symbol")["adjusted_close"].pct_change()
    return df.reset_index(drop=True)


def clean_news_sentiment(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.copy()
    # Alpha Vantage timestamp format is "20260122T143000" — must specify exact format
    df["time_published"] = pd.to_datetime(df["time_published"], format="%Y%m%dT%H%M%S", errors="coerce")
    # normalize() strips the time component so we get just the date for joining with stock prices
    df["date"]   = df["time_published"].dt.normalize()
    df["symbol"] = df["symbol"].str.upper().str.strip()

    for col in ["overall_sentiment_score", "ticker_relevance_score", "ticker_sentiment_score"]:
        # fillna(0.0) treats missing sentiment as neutral (no signal) rather than dropping the row
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df = df[df["symbol"].isin(TICKERS)]
    df = df.drop_duplicates(subset=["url", "symbol"])  # same article + ticker shouldn't appear twice
    return df.sort_values(["symbol", "date"]).reset_index(drop=True)


def clean_sp500_companies(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # rename raw CSV headers (e.g. "GICS Sector") to snake_case for consistent column names
    df = df.rename(columns={
        "Symbol": "symbol", "Security": "company_name",
        "GICS Sector": "sector", "GICS Sub-Industry": "sub_industry",
        "Headquarters Location": "headquarters", "Date added": "date_added",
        "CIK": "cik", "Founded": "founded",
    })
    df["symbol"]     = df["symbol"].str.upper().str.strip()
    df["date_added"] = pd.to_datetime(df["date_added"], errors="coerce")
    df = df.drop_duplicates(subset=["symbol"], keep="first")
    return df[df["symbol"].isin(TICKERS)].reset_index(drop=True)


# Validate
# All checks use assert → if any check fails the whole pipeline aborts immediately (fail-fast)

def validate_stock_prices(df: pd.DataFrame) -> None:
    assert not df.empty,                                        "Stock prices is empty"
    assert df["date"].isna().sum() == 0,                        "Null dates in stock prices"
    assert df["close"].isna().sum() == 0,                       "Null close prices"
    assert (df["close"] > 0).all(),                             "Non-positive close prices"
    assert (df["volume"] >= 0).all(),                           "Negative volume"
    assert (df["high"] >= df["low"]).all(),                     "high < low detected"  # physically impossible
    assert df.duplicated(subset=["date", "symbol"]).sum() == 0, "Duplicate (date, symbol) rows"
    assert set(df["symbol"].unique()).issubset(set(TICKERS)),    "Unexpected tickers"
    print(f"  [OK] stock_prices — {len(df)} rows, {df['symbol'].nunique()} tickers, "
          f"{df['date'].min().date()} to {df['date'].max().date()}")


def validate_news_sentiment(df: pd.DataFrame) -> None:
    if df.empty:
        print("  [skip] news_sentiment — no articles fetched"); return
    assert df["date"].isna().sum() == 0,                        "Null dates in news sentiment"
    assert df["symbol"].isna().sum() == 0,                      "Null symbols in news sentiment"
    assert df.duplicated(subset=["url", "symbol"]).sum() == 0,  "Duplicate (url, symbol) rows"
    # Alpha Vantage scores are bounded [-1, 1]; outside that range means bad data
    assert df["overall_sentiment_score"].between(-1, 1).all(),  "overall_sentiment_score out of [-1, 1]"
    assert df["ticker_sentiment_score"].between(-1, 1).all(),   "ticker_sentiment_score out of [-1, 1]"
    print(f"  [OK] news_sentiment — {len(df)} rows, {df['symbol'].nunique()} tickers")


def validate_sp500_companies(df: pd.DataFrame) -> None:
    assert not df.empty,                               "S&P 500 companies is empty"
    assert df.duplicated(subset=["symbol"]).sum() == 0, "Duplicate symbols"
    assert df["sector"].isna().sum() == 0,             "Null sectors"
    assert set(TICKERS).issubset(set(df["symbol"].unique())), \
        f"Missing tickers: {set(TICKERS) - set(df['symbol'].unique())}"
    print(f"  [OK] sp500_companies — {len(df)} rows, {df['sector'].nunique()} sectors")


# Run

def run_pipeline():
    print("=== Loading ===")
    stock_raw, news_raw, sp500_raw = load_stock_prices(), load_news_sentiment(), load_sp500_companies()

    print("=== Cleaning ===")
    stock_clean = clean_stock_prices(stock_raw)
    news_clean  = clean_news_sentiment(news_raw)
    sp500_clean = clean_sp500_companies(sp500_raw)

    print("=== Validating ===")
    validate_stock_prices(stock_clean)
    validate_news_sentiment(news_clean)
    validate_sp500_companies(sp500_clean)

    print("=== Saving ===")
    stock_clean.to_csv(CLEANED_FOLDER / "daily_stock_prices_cleaned.csv.gz", index=False, compression="gzip")
    sp500_clean.to_csv(CLEANED_FOLDER / "sp500_companies_cleaned.csv.gz",    index=False, compression="gzip")
    if not news_clean.empty:
        news_clean.to_csv(CLEANED_FOLDER / "news_sentiment_cleaned.csv.gz",  index=False, compression="gzip")
    print("  Done.")

    return stock_clean, news_clean, sp500_clean


if __name__ == "__main__":
    run_pipeline()
