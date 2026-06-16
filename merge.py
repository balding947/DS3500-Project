"""
Merges cleaned data sources into one analysis-ready dataset saved as zipped CSV.
Run after pipeline.py has saved cleaned files to data/cleaned/.

Join strategy:
  1. stock_prices LEFT JOIN sp500_companies ON symbol
     → every price row gets its sector/industry label
  2. result LEFT JOIN aggregated_sentiment ON (symbol, date)
     → every price row gets that day's sentiment stats (NaN where no news)
"""

from pathlib import Path

import pandas as pd

CLEANED_FOLDER = Path("data/cleaned")
PROCESSED_FOLDER = Path("data/processed")
PROCESSED_FOLDER.mkdir(parents=True, exist_ok=True)

TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
    "META", "TSLA", "AVGO", "JPM", "WMT",
]


# ── Load ──────────────────────────────────────────────────────────────────────

def load_cleaned_data():
    stock_path = CLEANED_FOLDER / "daily_stock_prices_cleaned.csv.gz"
    sp500_path = CLEANED_FOLDER / "sp500_companies_cleaned.csv.gz"
    news_path = CLEANED_FOLDER / "news_sentiment_cleaned.csv.gz"

    assert stock_path.exists(), f"Missing cleaned file: {stock_path} — run pipeline.py first"
    assert sp500_path.exists(), f"Missing cleaned file: {sp500_path} — run pipeline.py first"

    stock_df = pd.read_csv(stock_path, parse_dates=["date"])
    sp500_df = pd.read_csv(sp500_path, parse_dates=["date_added"])
    news_df = pd.read_csv(news_path, parse_dates=["date", "time_published"]) if news_path.exists() else pd.DataFrame()

    return stock_df, sp500_df, news_df


# ── Aggregate ─────────────────────────────────────────────────────────────────

def aggregate_sentiment(news_df: pd.DataFrame) -> pd.DataFrame:
    """Roll article-level sentiment up to daily (symbol, date) granularity."""
    if news_df.empty:
        return pd.DataFrame(columns=[
            "symbol", "date", "sentiment_score_mean", "sentiment_score_std",
            "ticker_sentiment_mean", "article_count", "dominant_sentiment_label",
        ])

    agg = (
        news_df.groupby(["symbol", "date"])
        .agg(
            sentiment_score_mean=("overall_sentiment_score", "mean"),
            sentiment_score_std=("overall_sentiment_score", "std"),
            ticker_sentiment_mean=("ticker_sentiment_score", "mean"),
            article_count=("url", "count"),
            dominant_sentiment_label=(
                "overall_sentiment_label",
                lambda x: x.mode().iloc[0] if not x.empty else None,
            ),
        )
        .reset_index()
    )

    # std is NaN when only one article — fill with 0
    agg["sentiment_score_std"] = agg["sentiment_score_std"].fillna(0.0)

    return agg


# ── Merge ─────────────────────────────────────────────────────────────────────

def merge_all(
    stock_df: pd.DataFrame,
    sp500_df: pd.DataFrame,
    news_agg_df: pd.DataFrame,
) -> pd.DataFrame:
    # Step 1: attach sector / company metadata
    sp500_cols = ["symbol", "company_name", "sector", "sub_industry"]
    merged = stock_df.merge(sp500_df[sp500_cols], on="symbol", how="left")

    # Step 2: attach daily sentiment (left join → NaN when no news that day)
    if not news_agg_df.empty:
        merged = merged.merge(news_agg_df, on=["symbol", "date"], how="left")
    else:
        # Keep schema consistent even with no news data
        for col in [
            "sentiment_score_mean", "sentiment_score_std",
            "ticker_sentiment_mean", "article_count",
        ]:
            merged[col] = float("nan")
        merged["dominant_sentiment_label"] = None

    return merged.sort_values(["symbol", "date"]).reset_index(drop=True)


# ── Validate ──────────────────────────────────────────────────────────────────

def validate_merged(df: pd.DataFrame) -> None:
    assert not df.empty, "Merged DataFrame is empty"
    assert df.duplicated(subset=["symbol", "date"]).sum() == 0, \
        "Duplicate (symbol, date) rows in merged dataset"
    assert set(df["symbol"].unique()).issubset(set(TICKERS)), \
        "Unexpected tickers in merged dataset"
    assert df["sector"].isna().sum() == 0, \
        "Merged dataset has rows with null sector — sector join failed"
    assert df["company_name"].isna().sum() == 0, \
        "Merged dataset has rows with null company_name — sector join failed"
    assert (df["close"] > 0).all(), \
        "Merged dataset has non-positive close prices"

    coverage = df["article_count"].notna().mean()
    print(
        f"  [OK] merged — {len(df)} rows × {len(df.columns)} columns, "
        f"{df['symbol'].nunique()} tickers, "
        f"{df['date'].min().date()} to {df['date'].max().date()}, "
        f"sentiment coverage: {coverage:.1%} of trading days"
    )


# ── Run ───────────────────────────────────────────────────────────────────────

def run_merge():
    print("=== Loading cleaned data ===")
    stock_df, sp500_df, news_df = load_cleaned_data()
    print(f"  stock_prices:    {len(stock_df)} rows")
    print(f"  sp500_companies: {len(sp500_df)} rows")
    print(f"  news_sentiment:  {len(news_df)} rows")

    print("\n=== Aggregating sentiment to daily level ===")
    news_agg = aggregate_sentiment(news_df)
    print(f"  aggregated: {len(news_agg)} (symbol, date) pairs")

    print("\n=== Merging sources ===")
    merged = merge_all(stock_df, sp500_df, news_agg)
    print(f"  result: {len(merged)} rows × {len(merged.columns)} columns")
    print(f"  columns: {list(merged.columns)}")

    print("\n=== Validating merged data ===")
    validate_merged(merged)

    print("\n=== Saving merged dataset (zipped CSV) ===")
    out_path = PROCESSED_FOLDER / "merged_dataset.csv.gz"
    merged.to_csv(out_path, index=False, compression="gzip")
    print(f"  Saved: {out_path}")

    print("\n=== Merge complete ===")
    return merged


if __name__ == "__main__":
    run_merge()
