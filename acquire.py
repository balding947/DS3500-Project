import json
import os
import time
from pathlib import Path
import pandas as pd
import requests

ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
SP500_CSV_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/"
    "main/data/constituents.csv"
)

TICKERS = ["AAPL"]
RAW_FOLDER = Path("data/raw")
SAMPLE_FOLDER = Path("data/sample")
RAW_FOLDER.mkdir(parents=True, exist_ok=True)
SAMPLE_FOLDER.mkdir(parents=True, exist_ok=True)

def get_api_key():
    """get alpha vantage api key from env variable"""
    api_key = os.getenv("ALPHAVANTAGE_API_KEY")

    if not api_key:
        raise ValueError(
            "Missing Alpha Vantage API key.\n"
            "Set it in PowerShell using:\n"
            '$env:ALPHAVANTAGE_API_KEY="your_api_key_here"'
        )

    return api_key

def save_json(data, file_path):
    """save dictionary data as a json file"""
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)

    print(f"Saved: {file_path}")

def fetch_daily_stock_prices(symbol):
    """fetch daily stock prices from alpha vantage"""
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "outputsize": "compact",
        "apikey": get_api_key(),
    }

    response = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()

    raw_path = RAW_FOLDER / f"{symbol}_daily_stock_prices_raw.json"
    save_json(data, raw_path)

    return data


def stock_prices_to_dataframe(data):
    """convert alpha vantage daily stock prices json to a dataframe"""
    metadata = data.get("Meta Data", {})
    symbol = metadata.get("2. Symbol")

    time_series = data.get("Time Series (Daily)", {})

    rows = []

    for date, values in time_series.items():
        row = {
            "date": date,
            "symbol": symbol,
            "open": values.get("1. open"),
            "high": values.get("2. high"),
            "low": values.get("3. low"),
            "close": values.get("4. close"),
            "volume": values.get("5. volume"),
        }

        rows.append(row)

    df = pd.DataFrame(rows)

    return df


def fetch_news_sentiment(tickers):
    """fetch news sentiment data for one or more tickers from alpha vantage"""
    ticker_string = ",".join(tickers)

    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": ticker_string,
        "limit": 50,
        "apikey": get_api_key(),
    }

    response = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()

    raw_path = RAW_FOLDER / "news_sentiment_raw.json"
    save_json(data, raw_path)

    return data


def news_sentiment_to_dataframe(data):
    """convert alpha vantage news sentiment json to a df"""

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

    df = pd.DataFrame(rows)

    return df

def fetch_sp500_companies():
    """load the S&P 500 companies static CSV"""
    df = pd.read_csv(SP500_CSV_URL)

    raw_path = RAW_FOLDER / "sp500_companies_raw.csv"
    df.to_csv(raw_path, index=False)

    return df

def acquire_all_sources():
    stock_frames = []

    for ticker in TICKERS:
        print(f"\nFetching daily stock prices for {ticker}...")
        raw_stock_data = fetch_daily_stock_prices(ticker)
        stock_df = stock_prices_to_dataframe(raw_stock_data)

        if not stock_df.empty:
            stock_frames.append(stock_df)

        time.sleep(2)

    if stock_frames:
        all_stock_prices = pd.concat(stock_frames, ignore_index=True)
    else:
        all_stock_prices = pd.DataFrame()

    stock_sample_path = SAMPLE_FOLDER / "daily_stock_prices_sample.csv"
    all_stock_prices.head(100).to_csv(stock_sample_path, index=False)
    print(f"Saved: {stock_sample_path}")

    print("\nFetching news sentiment data...")
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