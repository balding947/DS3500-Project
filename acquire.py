import json
import time
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import requests

# URLs
EODHD_URL = "https://eodhd.com/api/eod"
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
SP500_CSV_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/"
    "main/data/constituents.csv"
)

# API keys
EODHD_API_KEY = "6a317af06eb7b9.36941470"
ALPHAVANTAGE_API_KEY = "0GLNRG85M5LFDBXB"

# Settings
TICKERS = [
    "AAPL",   # Apple
    "MSFT",   # Microsoft
    "NVDA",   # Nvidia
    "AMZN",   # Amazon
    "GOOGL",  # Alphabet
    "META",   # Meta
    "TSLA",   # Tesla
    "AVGO",   # Broadcom
    "JPM",    # JPMorgan Chase
    "WMT",    # Walmart
]
START_DATE = "2026-01-22"

RAW_FOLDER = Path("data/raw")
SAMPLE_FOLDER = Path("data/sample")

RAW_FOLDER.mkdir(parents=True, exist_ok=True)
SAMPLE_FOLDER.mkdir(parents=True, exist_ok=True)


def save_json(data, file_path):
    """save dictionary data as a json file"""
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)

    print(f"Saved: {file_path}")


# API 1: EODHD daily stock prices
def fetch_daily_stock_prices(symbol):
    """fetch daily stock prices from EODHD starting Jan 22 2026"""

    eodhd_symbol = f"{symbol}.US"

    params = {
        "api_token": EODHD_API_KEY,
        "fmt": "json",
        "from": START_DATE,
        "to": datetime.now().strftime("%Y-%m-%d"),
    }

    response = requests.get(
        f"{EODHD_URL}/{eodhd_symbol}",
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    return data


def stock_prices_to_dataframe(data, symbol):
    """convert EODHD stock price data to a dataframe"""

    rows = []

    for item in data:
        row = {
            "date": item.get("date"),
            "symbol": symbol,
            "open": item.get("open"),
            "high": item.get("high"),
            "low": item.get("low"),
            "close": item.get("close"),
            "adjusted_close": item.get("adjusted_close"),
            "volume": item.get("volume"),
        }

        rows.append(row)

    return pd.DataFrame(rows)


# API 2: Alpha Vantage news sentiment
def fetch_news_sentiment(tickers):
    """fetch news sentiment data from Alpha Vantage from Jan 22 2026 to today"""

    ticker_string = ",".join(tickers)

    start_date = datetime.strptime("2026-01-22", "%Y-%m-%d")
    end_date = datetime.now()

    all_articles = []
    seen_urls = set()

    current_start = start_date

    while current_start <= end_date:
        current_end = current_start + timedelta(days=13)

        if current_end > end_date:
            current_end = end_date

        time_from = current_start.strftime("%Y%m%dT0000")
        time_to = current_end.strftime("%Y%m%dT2359")

        print(f"Fetching news from {time_from} to {time_to}...")

        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": ticker_string,
            "time_from": time_from,
            "time_to": time_to,
            "sort": "EARLIEST",
            "limit": 1000,
            "apikey": ALPHAVANTAGE_API_KEY,
        }

        response = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()
        feed = data.get("feed", [])

        print(f"Articles returned: {len(feed)}")

        for article in feed:
            article_url = article.get("url")

            if article_url not in seen_urls:
                all_articles.append(article)
                seen_urls.add(article_url)

        current_start = current_end + timedelta(days=1)

        time.sleep(2)

    combined_data = {
        "items": str(len(all_articles)),
        "feed": all_articles,
    }

    raw_path = RAW_FOLDER / "news_sentiment_raw.json"
    save_json(combined_data, raw_path)

    return combined_data


def news_sentiment_to_dataframe(data):
    """convert Alpha Vantage news sentiment json to a dataframe"""

    feed = data.get("feed", [])

    rows = []

    for article in feed:
        article_data = {
            "title": article.get("title"),
            "url": article.get("url"),
            "time_published": article.get("time_published"),
            "authors": article.get("authors"),
            "summary": article.get("summary"),
            "banner_image": article.get("banner_image"),
            "source": article.get("source"),
            "category_within_source": article.get("category_within_source"),
            "source_domain": article.get("source_domain"),
            "overall_sentiment_score": article.get("overall_sentiment_score"),
            "overall_sentiment_label": article.get("overall_sentiment_label"),
        }

        topics = article.get("topics", [])
        article_data["topics"] = [topic.get("topic") for topic in topics]

        ticker_sentiments = article.get("ticker_sentiment", [])

        for ticker_item in ticker_sentiments:
            row = article_data.copy()

            row["symbol"] = ticker_item.get("ticker")
            row["ticker_relevance_score"] = ticker_item.get("relevance_score")
            row["ticker_sentiment_score"] = ticker_item.get(
                "ticker_sentiment_score"
            )
            row["ticker_sentiment_label"] = ticker_item.get(
                "ticker_sentiment_label"
            )

            rows.append(row)

    return pd.DataFrame(rows)


# Static source: S&P 500 companies CSV
def fetch_sp500_companies():
    """load the S&P 500 companies static CSV"""

    df = pd.read_csv(SP500_CSV_URL)

    raw_path = RAW_FOLDER / "sp500_companies_raw.csv"
    df.to_csv(raw_path, index=False)
    print(f"Saved: {raw_path}")

    return df


def acquire_all_sources():
    stock_frames = []

    for ticker in TICKERS:
        print(f"\nFetching daily stock prices from EODHD for {ticker}...")

        raw_stock_data = fetch_daily_stock_prices(ticker)
        stock_df = stock_prices_to_dataframe(raw_stock_data, ticker)

        if not stock_df.empty:
            stock_frames.append(stock_df)

        time.sleep(2)

    if stock_frames:
        all_stock_prices = pd.concat(stock_frames, ignore_index=True)
    else:
        all_stock_prices = pd.DataFrame()

    stock_raw_path = RAW_FOLDER / "daily_stock_prices_raw.csv"
    all_stock_prices.to_csv(stock_raw_path, index=False)
    print(f"Saved: {stock_raw_path}")

    stock_sample_path = SAMPLE_FOLDER / "daily_stock_prices_sample.csv"
    all_stock_prices.head(100).to_csv(stock_sample_path, index=False)
    print(f"Saved: {stock_sample_path}")

    print("\nFetching news sentiment data from Alpha Vantage...")
    raw_news_data = fetch_news_sentiment(TICKERS)
    news_df = news_sentiment_to_dataframe(raw_news_data)

    news_sample_path = SAMPLE_FOLDER / "news_sentiment_sample.csv"
    news_df.head(100).to_csv(news_sample_path, index=False)
    print(f"Saved: {news_sample_path}")

    print("\nFetching S&P 500 company metadata...")
    sp500_df = fetch_sp500_companies()

    sp500_sample_path = SAMPLE_FOLDER / "sp500_companies_sample.csv"
    sp500_df.head(100).to_csv(sp500_sample_path, index=False)
    print(f"Saved: {sp500_sample_path}")


def main():
    acquire_all_sources()


if __name__ == "__main__":
    main()