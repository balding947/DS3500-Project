import pandas as pd
from pathlib import Path

PROCESSED_PATH = Path("data/processed/merged_dataset.csv.gz")


def get_data():
    df = pd.read_csv(PROCESSED_PATH, parse_dates=["date"])
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    return df


def get_tickers(df):
    return sorted(df["symbol"].unique().tolist())


def get_sectors(df):
    return sorted(df["sector"].dropna().unique().tolist())


def filter_data(df, ticker=None, sector=None, start_date=None, end_date=None):
    filtered = df.copy()
    if ticker and ticker != "All":
        filtered = filtered[filtered["symbol"] == ticker]
    if sector and sector != "All":
        filtered = filtered[filtered["sector"] == sector]
    if start_date:
        filtered = filtered[filtered["date"] >= pd.Timestamp(start_date)]
    if end_date:
        filtered = filtered[filtered["date"] <= pd.Timestamp(end_date)]
    return filtered


def compute_volatility(df):
    """Annualized volatility (std of daily returns * sqrt(252)) per ticker."""
    return (
        df.groupby("symbol")["daily_return"]
        .std()
        .mul(252 ** 0.5)
        .reset_index()
        .rename(columns={"daily_return": "volatility"})
    )


def compute_sector_returns(df):
    """Total return per symbol and mean return per sector over selected period."""
    bounds = (
        df.groupby("symbol")["adjusted_close"]
        .agg(first="first", last="last")
        .reset_index()
    )
    bounds["total_return"] = (bounds["last"] - bounds["first"]) / bounds["first"]
    sector_map = df[["symbol", "sector", "company_name"]].drop_duplicates("symbol")
    bounds = bounds.merge(sector_map, on="symbol", how="left")
    sector_returns = (
        bounds.groupby("sector")["total_return"]
        .mean()
        .reset_index()
        .sort_values("total_return", ascending=False)
    )
    return sector_returns, bounds


def get_summary_stats(df):
    return {
        "tickers": df["symbol"].nunique(),
        "sectors": df["sector"].nunique(),
        "trading_days": df["date"].nunique(),
        "date_range": f"{df['date'].min().date()} – {df['date'].max().date()}",
        "avg_daily_return": f"{df['daily_return'].mean():.3%}",
    }


def compute_cumulative_returns(df):
    """Cumulative return from start of the selected period, sampled every 5 trading days."""
    df = df.copy()
    first_prices = df.groupby("symbol")["adjusted_close"].transform("first")
    df["cumulative_return"] = (df["adjusted_close"] - first_prices) / first_prices

    dates = sorted(df["date"].unique())
    sampled = set(dates[::5])
    if dates:
        sampled.add(dates[-1])

    df = df[df["date"].isin(sampled)].copy()
    df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")
    return df.sort_values(["date_str", "symbol"])


def compute_rolling_volatility(df, window=20):
    """Rolling annualized volatility per ticker."""
    df = df.copy()
    df["rolling_vol"] = (
        df.groupby("symbol")["daily_return"]
        .transform(lambda x: x.rolling(int(window), min_periods=5).std() * (252 ** 0.5))
    )
    return df


if __name__ == "__main__":
    df = get_data()
    print("=" * 50)
    print(f"Rows: {len(df)}")
    print("=" * 50)
    print("\nTickers:", get_tickers(df))
    print("\nSectors:", get_sectors(df))
    print("\nSummary stats:")
    print(get_summary_stats(df))
