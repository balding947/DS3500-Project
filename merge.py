"""joins stock prices, S&P 500 metadata, and daily sentiment into one merged dataset"""

from pathlib import Path

import pandas as pd

CLEANED_FOLDER   = Path("data/cleaned")
PROCESSED_FOLDER = Path("data/processed")
PROCESSED_FOLDER.mkdir(parents=True, exist_ok=True)

TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "WMT"]


# Load

def load_cleaned_data():
    stock_path = CLEANED_FOLDER / "daily_stock_prices_cleaned.csv.gz"
    sp500_path = CLEANED_FOLDER / "sp500_companies_cleaned.csv.gz"
    news_path  = CLEANED_FOLDER / "news_sentiment_cleaned.csv.gz"

    assert stock_path.exists(), f"Missing {stock_path} — run pipeline.py first"
    assert sp500_path.exists(), f"Missing {sp500_path} — run pipeline.py first"

    stock_df = pd.read_csv(stock_path, parse_dates=["date"])
    sp500_df = pd.read_csv(sp500_path, parse_dates=["date_added"])
    # news file may not exist if Alpha Vantage returned no articles — return empty DataFrame instead of crashing
    news_df  = pd.read_csv(news_path, parse_dates=["date", "time_published"]) \
               if news_path.exists() else pd.DataFrame()

    return stock_df, sp500_df, news_df


# Aggregate sentiment to one row per (symbol, date)
# Needed because Alpha Vantage gives one row per article — multiple articles on the same
# day for the same stock would create duplicate (symbol, date) rows after joining

def aggregate_sentiment(news_df: pd.DataFrame) -> pd.DataFrame:
    if news_df.empty:
        # return empty frame with the right columns so merge_all can still run
        return pd.DataFrame(columns=[
            "symbol", "date", "sentiment_score_mean", "sentiment_score_std",
            "ticker_sentiment_mean", "article_count", "dominant_sentiment_label",
        ])

    agg = (
        news_df.groupby(["symbol", "date"])
        .agg(
            sentiment_score_mean     = ("overall_sentiment_score", "mean"),
            sentiment_score_std      = ("overall_sentiment_score", "std"),
            ticker_sentiment_mean    = ("ticker_sentiment_score",  "mean"),
            article_count            = ("url", "count"),             # how many articles that day
            dominant_sentiment_label = ("overall_sentiment_label",
                                        lambda x: x.mode().iloc[0] if not x.empty else None),  # most common label
        )
        .reset_index()
    )
    # std is NaN when there's only one article — replace with 0 (no variation)
    agg["sentiment_score_std"] = agg["sentiment_score_std"].fillna(0.0)
    return agg


# Merge

def merge_all(stock_df, sp500_df, news_agg_df) -> pd.DataFrame:
    sp500_cols = ["symbol", "company_name", "sector", "sub_industry"]

    # LEFT JOIN: keeps every stock price row even if the ticker isn't in sp500 (shouldn't happen)
    merged = stock_df.merge(sp500_df[sp500_cols], on="symbol", how="left")

    if not news_agg_df.empty:
        # LEFT JOIN on (symbol, date): keeps every trading day; days with no news get NaN sentiment
        merged = merged.merge(news_agg_df, on=["symbol", "date"], how="left")
    else:
        # no sentiment data at all — fill columns with NaN so the schema stays consistent
        for col in ["sentiment_score_mean", "sentiment_score_std", "ticker_sentiment_mean", "article_count"]:
            merged[col] = float("nan")
        merged["dominant_sentiment_label"] = None

    return merged.sort_values(["symbol", "date"]).reset_index(drop=True)


# Validate

def validate_merged(df: pd.DataFrame) -> None:
    assert not df.empty,                                          "Merged DataFrame is empty"
    assert df.duplicated(subset=["symbol", "date"]).sum() == 0,  "Duplicate (symbol, date) rows"
    assert set(df["symbol"].unique()).issubset(set(TICKERS)),     "Unexpected tickers"
    # null sector/company_name means the sp500 left join found no match — data integrity failure
    assert df["sector"].isna().sum() == 0,                        "Null sector — join failed"
    assert df["company_name"].isna().sum() == 0,                  "Null company_name — join failed"
    assert (df["close"] > 0).all(),                               "Non-positive close prices"
    coverage = df["article_count"].notna().mean()  # % of trading days that have at least one news article
    print(f"  [OK] merged — {len(df)} rows × {len(df.columns)} cols, "
          f"{df['date'].min().date()} to {df['date'].max().date()}, "
          f"sentiment coverage: {coverage:.1%}")


# Run

def run_merge():
    print("=== Loading ===")
    stock_df, sp500_df, news_df = load_cleaned_data()

    print("=== Aggregating sentiment ===")
    news_agg = aggregate_sentiment(news_df)

    print("=== Merging ===")
    merged = merge_all(stock_df, sp500_df, news_agg)
    print(f"  {len(merged)} rows × {len(merged.columns)} columns")

    print("=== Validating ===")
    validate_merged(merged)

    print("=== Saving ===")
    out_path = PROCESSED_FOLDER / "merged_dataset.csv.gz"
    merged.to_csv(out_path, index=False, compression="gzip")
    print(f"  Saved: {out_path}")

    return merged


if __name__ == "__main__":
    run_merge()
