"""
pytest test suite for the stock-market data pipeline.

Covers the four areas required by Milestone 2:

  1. Data loading & API access  -> acquire.fetch_*, acquire.*_to_dataframe,
                                   pipeline.load_*
  2. Cleaning functions         -> pipeline.clean_*
  3. Merge logic                -> merge.aggregate_sentiment, merge.merge_all
  4. Data validation            -> pipeline.validate_*, merge.validate_merged

Style follows the course testing conventions (see ds3500_sum26/code/
test_api_full.py): @pytest.fixture for shared test data, @patch('requests.get')
from unittest.mock to mock the API, and pytest.approx for float comparisons.

Tests use small synthetic DataFrames with known answers so each assertion is
deterministic and offline.

Run from the project root:  pytest -v
"""

import json
from unittest.mock import patch

import pandas as pd
import pytest
import requests

import acquire
import pipeline
import merge


# Builders

def make_stock_raw(rows):
    """Build a raw stock-price frame with the columns clean_stock_prices expects."""
    cols = ["date", "symbol", "open", "high", "low",
            "close", "adjusted_close", "volume"]
    return pd.DataFrame(rows, columns=cols)


def make_sp500_raw(rows):
    """Build a raw S&P 500 frame with the original (pre-rename) column headers."""
    cols = ["Symbol", "Security", "GICS Sector", "GICS Sub-Industry",
            "Headquarters Location", "Date added", "CIK", "Founded"]
    return pd.DataFrame(rows, columns=cols)


def make_news_clean(rows):
    """Build a cleaned-news frame (post clean_news_sentiment) for aggregation."""
    cols = ["symbol", "date", "url", "overall_sentiment_score",
            "ticker_sentiment_score", "overall_sentiment_label"]
    df = pd.DataFrame(rows, columns=cols)
    df["date"] = pd.to_datetime(df["date"])
    return df


# Fixtures — shared, fixed test data reused across multiple tests

@pytest.fixture
def sample_stock_clean():
    """A clean stock frame that passes validate_stock_prices."""
    return pd.DataFrame({
        "symbol": ["AAPL", "AAPL"],
        "date": pd.to_datetime(["2026-01-22", "2026-01-23"]),
        "open": [249.0, 250.0],
        "high": [251.0, 252.0],
        "low": [248.0, 249.0],
        "close": [248.0, 250.0],
        "volume": [1000, 2000],
    })


@pytest.fixture
def sample_sp500_clean():
    """A cleaned S&P 500 company frame (post clean_sp500_companies)."""
    return pd.DataFrame({
        "symbol": ["AAPL", "MSFT"],
        "company_name": ["Apple Inc.", "Microsoft"],
        "sector": ["Information Technology", "Information Technology"],
        "sub_industry": ["Tech Hardware", "Software"],
    })


# DATA LOADING & API ACCESS

def test_stock_prices_to_dataframe_parses_eodhd_json():
    """acquire parses the EODHD daily-price list into a tidy frame."""
    payload = [
        {"date": "2026-01-22", "open": 249.20, "high": 251.00, "low": 248.15,
         "close": 248.35, "adjusted_close": 247.88, "volume": 39708300},
        {"date": "2026-01-23", "open": 247.32, "high": 249.41, "low": 244.68,
         "close": 248.04, "adjusted_close": 247.58, "volume": 41689000},
    ]
    df = acquire.stock_prices_to_dataframe(payload, "AAPL")
    assert list(df.columns) == ["date", "symbol", "open", "high",
                                "low", "close", "adjusted_close", "volume"]
    assert len(df) == 2
    assert set(df["symbol"]) == {"AAPL"}


@patch("requests.get")
def test_fetch_daily_stock_prices_uses_api_and_returns_json(mock_get):
    """fetch_* calls the HTTP layer once and returns the decoded JSON (mocked)."""
    expected = [
        {"date": "2026-01-22", "open": 249.2, "high": 251.0, "low": 248.1,
         "close": 248.3, "adjusted_close": 247.8, "volume": 39708300},
    ]
    mock_get.return_value.raise_for_status.return_value = None
    mock_get.return_value.json.return_value = expected

    result = acquire.fetch_daily_stock_prices("AAPL")

    assert result == expected
    mock_get.assert_called_once()


@patch("requests.get")
def test_fetch_daily_stock_prices_raises_on_http_error(mock_get):
    """A bad HTTP status must propagate, not be silently swallowed."""
    mock_get.return_value.raise_for_status.side_effect = \
        requests.HTTPError("429 rate limited")

    with pytest.raises(requests.HTTPError):
        acquire.fetch_daily_stock_prices("AAPL")


def test_load_news_sentiment_reads_and_flattens(monkeypatch, tmp_path):
    """pipeline.load_news_sentiment reads the raw JSON file and flattens it."""
    raw = {
        "feed": [{
            "title": "t", "url": "http://x", "time_published": "20260122T120000",
            "source": "src", "overall_sentiment_score": 0.1,
            "overall_sentiment_label": "Neutral",
            "ticker_sentiment": [
                {"ticker": "AAPL", "relevance_score": "0.9",
                 "ticker_sentiment_score": "0.2",
                 "ticker_sentiment_label": "Bullish"},
            ],
        }]
    }
    (tmp_path / "news_sentiment_raw.json").write_text(json.dumps(raw))
    monkeypatch.setattr(pipeline, "RAW_FOLDER", tmp_path)

    df = pipeline.load_news_sentiment()
    assert len(df) == 1
    assert df.loc[0, "symbol"] == "AAPL"


# CLEANING FUNCTIONS

def test_clean_stock_prices_coerces_types():
    """String price/volume columns become numeric and date becomes datetime."""
    raw = make_stock_raw([
        ["2026-01-22", "AAPL", "249.2", "251.0", "248.1", "248.3", "247.8", "39708300"],
    ])
    out = pipeline.clean_stock_prices(raw)
    assert pd.api.types.is_numeric_dtype(out["close"])
    assert pd.api.types.is_numeric_dtype(out["volume"])
    assert pd.api.types.is_datetime64_any_dtype(out["date"])
    assert "daily_return" in out.columns  # derived feature added


def test_clean_stock_prices_removes_duplicate_symbol_date():
    """Duplicate (date, symbol) rows collapse to one, keeping the latest value."""
    raw = make_stock_raw([
        ["2026-01-22", "AAPL", 249, 251, 248, 100, 100, 1000],
        ["2026-01-22", "AAPL", 249, 251, 248, 200, 200, 2000],  # newer / corrected
    ])
    out = pipeline.clean_stock_prices(raw)
    assert len(out) == 1
    assert out.loc[0, "close"] == 200


def test_clean_stock_prices_filters_to_known_tickers():
    """Rows for tickers outside the project universe are dropped."""
    raw = make_stock_raw([
        ["2026-01-22", "AAPL", 249, 251, 248, 248, 248, 1000],
        ["2026-01-22", "FAKE", 10, 11, 9, 10, 10, 500],
    ])
    out = pipeline.clean_stock_prices(raw)
    assert "FAKE" not in set(out["symbol"])
    assert set(out["symbol"]) == {"AAPL"}


def test_clean_stock_prices_drops_negative_volume():
    """Negative volume is invalid and must be removed."""
    raw = make_stock_raw([
        ["2026-01-22", "AAPL", 249, 251, 248, 248, 248, 1000],
        ["2026-01-23", "AAPL", 250, 252, 249, 250, 250, -5],   # bad
    ])
    out = pipeline.clean_stock_prices(raw)
    assert (out["volume"] >= 0).all()
    assert len(out) == 1


def test_clean_sp500_renames_and_filters():
    """GICS headers are renamed and the frame is filtered to project tickers."""
    raw = make_sp500_raw([
        ["AAPL", "Apple Inc.", "Information Technology", "Tech Hardware",
         "Cupertino, CA", "1982-11-30", 320193, "1977"],
        ["MMM", "3M", "Industrials", "Industrial Conglomerates",
         "Saint Paul, MN", "1957-03-04", 66740, "1902"],  # not a project ticker
    ])
    out = pipeline.clean_sp500_companies(raw)
    assert {"symbol", "company_name", "sector", "sub_industry"}.issubset(out.columns)
    assert set(out["symbol"]) == {"AAPL"}


def test_clean_news_sentiment_derives_date_from_timestamp():
    """The (symbol, date) join key is derived from the news timestamp."""
    raw = pd.DataFrame([{
        "title": "t", "url": "http://x", "time_published": "20260122T143000",
        "source": "src", "overall_sentiment_score": "0.4",
        "overall_sentiment_label": "Bullish", "symbol": "AAPL",
        "ticker_relevance_score": "0.9", "ticker_sentiment_score": "0.3",
        "ticker_sentiment_label": "Bullish",
    }])
    out = pipeline.clean_news_sentiment(raw)
    assert out.loc[0, "date"] == pd.Timestamp("2026-01-22")


# MERGE LOGIC

def test_aggregate_sentiment_collapses_to_symbol_date():
    """Multiple articles for the same symbol/day roll up to one row + a count."""
    news = make_news_clean([
        ["AAPL", "2026-01-22", "http://a", 0.2, 0.3, "Bullish"],
        ["AAPL", "2026-01-22", "http://b", 0.4, 0.1, "Neutral"],
        ["AAPL", "2026-01-22", "http://c", 0.0, 0.0, "Neutral"],
    ])
    agg = merge.aggregate_sentiment(news)
    assert len(agg) == 1
    assert agg.loc[0, "article_count"] == 3
    # mean of the three overall_sentiment_score values (float -> use approx)
    assert agg.loc[0, "sentiment_score_mean"] == pytest.approx((0.2 + 0.4 + 0.0) / 3)


def test_merge_all_preserves_every_stock_row(sample_sp500_clean):
    """The left join must keep all stock rows even with no matching news."""
    stock = pd.DataFrame({
        "symbol": ["AAPL", "AAPL", "MSFT"],
        "date": pd.to_datetime(["2026-01-22", "2026-01-23", "2026-01-22"]),
        "close": [248.0, 250.0, 410.0],
    })
    merged = merge.merge_all(stock, sample_sp500_clean, pd.DataFrame())
    assert len(merged) == len(stock)
    assert merged["sector"].notna().all()  # sector join succeeded for all rows


def test_merge_all_leaves_nan_when_no_news_that_day(sample_sp500_clean):
    """A trading day with no article gets NaN sentiment, not a dropped row."""
    stock = pd.DataFrame({
        "symbol": ["AAPL", "AAPL"],
        "date": pd.to_datetime(["2026-01-22", "2026-01-23"]),
        "close": [248.0, 250.0],
    })
    news_agg = merge.aggregate_sentiment(make_news_clean([
        ["AAPL", "2026-01-22", "http://a", 0.2, 0.3, "Bullish"],
    ]))
    merged = merge.merge_all(stock, sample_sp500_clean, news_agg)
    no_news_row = merged[merged["date"] == pd.Timestamp("2026-01-23")].iloc[0]
    assert pd.isna(no_news_row["sentiment_score_mean"])


# DATA VALIDATION

def test_validate_stock_prices_accepts_clean_data(sample_stock_clean):
    """Valid cleaned data passes without raising."""
    pipeline.validate_stock_prices(sample_stock_clean)  # no exception


def test_validate_stock_prices_rejects_high_below_low(sample_stock_clean):
    """A row where high < low is physically impossible and must fail."""
    sample_stock_clean.loc[0, "high"] = 1.0   # high now far below low
    with pytest.raises(AssertionError):
        pipeline.validate_stock_prices(sample_stock_clean)


def test_validate_news_sentiment_rejects_out_of_range_score():
    """Sentiment scores must fall within [-1, 1]."""
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-22"]),
        "symbol": ["AAPL"],
        "url": ["http://a"],
        "overall_sentiment_score": [5.0],   # out of range
        "ticker_sentiment_score": [0.0],
    })
    with pytest.raises(AssertionError):
        pipeline.validate_news_sentiment(df)


def test_validate_merged_rejects_null_sector():
    """A null sector means the company join failed — must be caught."""
    df = pd.DataFrame({
        "symbol": ["AAPL"],
        "date": pd.to_datetime(["2026-01-22"]),
        "close": [248.0],
        "company_name": ["Apple Inc."],
        "sector": [None],            # join miss
        "article_count": [1],
    })
    with pytest.raises(AssertionError):
        merge.validate_merged(df)
