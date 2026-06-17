"""
================================================================================
pytest suite for the data pipeline  —  17 tests, all offline, ~0.3s
================================================================================
Covers the four areas the rubric requires:
    1. Data loading & API access   2. Cleaning   3. Merge logic   4. Validation

THE DESIGN IN THREE IDEAS (this is the "why" for the whole file):
  1. TEST THE REAL CODE — every test imports and calls our actual acquire /
     pipeline / merge functions (not copies), so a broken change fails a test.
  2. SYNTHETIC DATA WITH KNOWN ANSWERS — tiny hand-made tables with a *planted*
     problem (a duplicate, a bad value) let each assertion check an exact result.
  3. MOCK THE NETWORK — the fetch tests fake requests.get, so the suite runs
     offline, fast, and never uses our API rate limit.

VOCAB (say these precisely):
  - mock      = fake stand-in for a DEPENDENCY (here, requests.get)
  - fixture   = reusable test data, injected by naming it as a test argument
  - builder   = a function that builds custom test data from rows you pass in
  - @patch    = replaces a callable (the API) with a fake for one test
  - monkeypatch = swaps an attribute/path (used with tmp_path for the file test)

Run from the project root:   pytest test_pipeline.py -v
================================================================================
"""

import json
from unittest.mock import patch   # used to FAKE requests.get in the API tests

import pandas as pd
import pytest
import requests                   # only needed to reference requests.HTTPError

# The REAL modules under test (not copies). If the pipeline regresses, a test fails.
import acquire
import pipeline
import merge


# ═════════════════════════════════════════════════════════════════════════════
# BUILDERS  —  templates that build a fake INPUT table from the rows passed in.
#
# Used when each test needs a DIFFERENT scenario, so the test supplies its own
# numbers in one line instead of repeating the column list every time.
# ═════════════════════════════════════════════════════════════════════════════

def make_stock_raw(rows):
    """Build a RAW stock-price frame (pre-cleaning). Feeds clean_stock_prices().

    USED BY the 4 cleaning tests: coerces_types, removes_duplicate_symbol_date,
    filters_to_known_tickers, drops_negative_volume."""
    cols = ["date", "symbol", "open", "high", "low",
            "close", "adjusted_close", "volume"]
    return pd.DataFrame(rows, columns=cols)



def make_sp500_raw(rows):
    """Build a RAW S&P 500 frame with the original GICS headers (pre-rename).

    USED BY 1 cleaning test: test_clean_sp500_renames_and_filters."""
    cols = ["Symbol", "Security", "GICS Sector", "GICS Sub-Industry",
            "Headquarters Location", "Date added", "CIK", "Founded"]
    return pd.DataFrame(rows, columns=cols)


def make_news_clean(rows):
    """Build an ALREADY-CLEANED news frame. Feeds the merge step (aggregate).

    USED BY the 2 merge tests: aggregate_sentiment_collapses_to_symbol_date,
    merge_all_leaves_nan_when_no_news_that_day."""
    cols = ["symbol", "date", "url", "overall_sentiment_score",
            "ticker_sentiment_score", "overall_sentiment_label"]
    df = pd.DataFrame(rows, columns=cols)
    df["date"] = pd.to_datetime(df["date"])
    return df


# ═════════════════════════════════════════════════════════════════════════════
# FIXTURES  —  pre-made tables with values BAKED IN, reused unchanged by several
# tests. pytest auto-injects a fixture when a test names it as a parameter.
#
# Rule of thumb:  shared/identical data -> fixture.   per-test variation -> builder.
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def sample_stock_clean():
    """A clean stock frame that PASSES validate_stock_prices (the good baseline).

    USED BY the 2 validation tests: validate_stock_prices_accepts_clean_data
    (uses it as-is) and validate_stock_prices_rejects_high_below_low (breaks
    ONE field). Starting from a known-good frame proves the failure came from
    exactly that defect."""
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
    """A cleaned S&P 500 company frame (post clean_sp500_companies).

    USED BY the 2 merge tests: merge_all_preserves_every_stock_row and
    merge_all_leaves_nan_when_no_news_that_day (provides the company/sector
    side of the join)."""
    return pd.DataFrame({
        "symbol": ["AAPL", "MSFT"],
        "company_name": ["Apple Inc.", "Microsoft"],
        "sector": ["Information Technology", "Information Technology"],
        "sub_industry": ["Tech Hardware", "Software"],
    })


# ═════════════════════════════════════════════════════════════════════════════
# 1. DATA LOADING & API ACCESS
# ═════════════════════════════════════════════════════════════════════════════

def test_stock_prices_to_dataframe_parses_eodhd_json():
    """Verifies that acquire.stock_prices_to_dataframe() correctly converts the
    raw JSON price list from the EODHD API into a pandas DataFrame with the
    columns we expect."""
    payload = [
        {"date": "2026-01-22", "open": 249.20, "high": 251.00, "low": 248.15,
         "close": 248.35, "adjusted_close": 247.88, "volume": 39708300},
        {"date": "2026-01-23", "open": 247.32, "high": 249.41, "low": 244.68,
         "close": 248.04, "adjusted_close": 247.58, "volume": 41689000},
    ]
    df = acquire.stock_prices_to_dataframe(payload, "AAPL")
    # We expect: the right columns, the right row count, and the symbol tagged on.
    assert list(df.columns) == ["date", "symbol", "open", "high",
                                "low", "close", "adjusted_close", "volume"]
    assert len(df) == 2
    assert set(df["symbol"]) == {"AAPL"}


@patch("requests.get")   # replaces requests.get with a fake "mock_get" for this test
def test_fetch_daily_stock_prices_uses_api_and_returns_json(mock_get):
    """Verifies that acquire.fetch_daily_stock_prices() calls the API once and
    returns the decoded JSON — using a FAKE (mocked) API so no real network
    request is made."""
    expected = [
        {"date": "2026-01-22", "open": 249.2, "high": 251.0, "low": 248.1,
         "close": 248.3, "adjusted_close": 247.8, "volume": 39708300},
    ]
    # Program the fake response: no HTTP error, and .json() hands back our payload.
    mock_get.return_value.raise_for_status.return_value = None
    mock_get.return_value.json.return_value = expected

    result = acquire.fetch_daily_stock_prices("AAPL")

    assert result == expected
    mock_get.assert_called_once()   # proves our code actually hit the HTTP layer


@patch("requests.get")
def test_fetch_daily_stock_prices_raises_on_http_error(mock_get):
    """Verifies that acquire.fetch_daily_stock_prices() raises an error when the
    API returns a bad status, instead of silently continuing with no data."""
    # side_effect = raise this exception when raise_for_status() is called.
    mock_get.return_value.raise_for_status.side_effect = \
        requests.HTTPError("429 rate limited")

    # pytest.raises asserts the error bubbles up out of fetch (we don't hide it).
    with pytest.raises(requests.HTTPError):
        acquire.fetch_daily_stock_prices("AAPL")


def test_load_news_sentiment_reads_and_flattens(monkeypatch, tmp_path):
    """Verifies that pipeline.load_news_sentiment() reads the raw news JSON file
    from disk and flattens its nested ticker data into a flat table.

    tmp_path            = a throwaway temp folder pytest provides.
    monkeypatch.setattr = point pipeline.RAW_FOLDER at that temp folder, so we
                          test the real loader without touching our real data/.
    """
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


# ═════════════════════════════════════════════════════════════════════════════
# 2. CLEANING FUNCTIONS
#    Each test plants ONE problem (wrong type, duplicate, bad ticker, bad volume)
#    and checks the cleaning function fixes exactly that. Builders supply the input.
# ═════════════════════════════════════════════════════════════════════════════

def test_clean_stock_prices_coerces_types():
    """Verifies that pipeline.clean_stock_prices() converts text values into
    proper numeric and datetime types (and adds the derived daily_return column)."""
    raw = make_stock_raw([
        ["2026-01-22", "AAPL", "249.2", "251.0", "248.1", "248.3", "247.8", "39708300"],
    ])
    out = pipeline.clean_stock_prices(raw)
    assert pd.api.types.is_numeric_dtype(out["close"])
    assert pd.api.types.is_numeric_dtype(out["volume"])
    assert pd.api.types.is_datetime64_any_dtype(out["date"])
    assert "daily_return" in out.columns


def test_clean_stock_prices_removes_duplicate_symbol_date():
    """Verifies that pipeline.clean_stock_prices() removes duplicate rows for the
    same stock on the same date, keeping the most recent value.

    We plant two AAPL rows on the same date; cleaning keeps the LATEST (close=200)."""
    raw = make_stock_raw([
        ["2026-01-22", "AAPL", 249, 251, 248, 100, 100, 1000],
        ["2026-01-22", "AAPL", 249, 251, 248, 200, 200, 2000],  # newer / corrected
    ])
    out = pipeline.clean_stock_prices(raw)
    assert len(out) == 1
    assert out.loc[0, "close"] == 200


def test_clean_stock_prices_filters_to_known_tickers():
    """Verifies that pipeline.clean_stock_prices() drops rows whose ticker is not
    one of our project's chosen stocks (we plant a 'FAKE' ticker)."""
    raw = make_stock_raw([
        ["2026-01-22", "AAPL", 249, 251, 248, 248, 248, 1000],
        ["2026-01-22", "FAKE", 10, 11, 9, 10, 10, 500],   # not one of our tickers
    ])
    out = pipeline.clean_stock_prices(raw)
    assert "FAKE" not in set(out["symbol"])
    assert set(out["symbol"]) == {"AAPL"}


def test_clean_stock_prices_drops_negative_volume():
    """Verifies that pipeline.clean_stock_prices() removes rows with a negative
    trading volume, since volume can never be negative."""
    raw = make_stock_raw([
        ["2026-01-22", "AAPL", 249, 251, 248, 248, 248, 1000],
        ["2026-01-23", "AAPL", 250, 252, 249, 250, 250, -5],   # bad volume
    ])
    out = pipeline.clean_stock_prices(raw)
    assert (out["volume"] >= 0).all()
    assert len(out) == 1


def test_clean_sp500_renames_and_filters():
    """Verifies that pipeline.clean_sp500_companies() renames the raw GICS column
    headers to our names (e.g. 'GICS Sector' -> 'sector') and keeps only our
    project's stocks."""
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
    """Verifies that pipeline.clean_news_sentiment() builds a 'date' column from
    the article's timestamp — the key later used to join news to stock prices."""
    raw = pd.DataFrame([{
        "title": "t", "url": "http://x", "time_published": "20260122T143000",
        "source": "src", "overall_sentiment_score": "0.4",
        "overall_sentiment_label": "Bullish", "symbol": "AAPL",
        "ticker_relevance_score": "0.9", "ticker_sentiment_score": "0.3",
        "ticker_sentiment_label": "Bullish",
    }])
    out = pipeline.clean_news_sentiment(raw)
    # "20260122T143000" -> keep just the date part -> 2026-01-22.
    assert out.loc[0, "date"] == pd.Timestamp("2026-01-22")


# ═════════════════════════════════════════════════════════════════════════════
# 3. MERGE LOGIC
#    Sentiment is rolled up to one row per (symbol, date), then LEFT-joined onto
#    the stock prices so every trading day survives even with no news.
# ═════════════════════════════════════════════════════════════════════════════

def test_aggregate_sentiment_collapses_to_symbol_date():
    """Verifies that merge.aggregate_sentiment() combines all of a stock's
    articles for a given day into ONE row, with an article count and the average
    sentiment score."""
    news = make_news_clean([
        ["AAPL", "2026-01-22", "http://a", 0.2, 0.3, "Bullish"],
        ["AAPL", "2026-01-22", "http://b", 0.4, 0.1, "Neutral"],
        ["AAPL", "2026-01-22", "http://c", 0.0, 0.0, "Neutral"],
    ])
    agg = merge.aggregate_sentiment(news)
    assert len(agg) == 1
    assert agg.loc[0, "article_count"] == 3
    # approx() because floating-point math isn't exact: (0.2 + 0.4 + 0.0) / 3.
    assert agg.loc[0, "sentiment_score_mean"] == pytest.approx((0.2 + 0.4 + 0.0) / 3)


def test_merge_all_preserves_every_stock_row(sample_sp500_clean):
    """Verifies that merge.merge_all() keeps EVERY stock-price row when it joins
    in company info (a left join), and attaches a sector to each row.

    3 stock rows in -> 3 merged rows out, all with a sector."""
    stock = pd.DataFrame({
        "symbol": ["AAPL", "AAPL", "MSFT"],
        "date": pd.to_datetime(["2026-01-22", "2026-01-23", "2026-01-22"]),
        "close": [248.0, 250.0, 410.0],
    })
    merged = merge.merge_all(stock, sample_sp500_clean, pd.DataFrame())
    assert len(merged) == len(stock)
    assert merged["sector"].notna().all()


def test_merge_all_leaves_nan_when_no_news_that_day(sample_sp500_clean):
    """Verifies that merge.merge_all() keeps a stock row that has no news that
    day, leaving the sentiment columns blank (NaN) instead of dropping the row."""
    stock = pd.DataFrame({
        "symbol": ["AAPL", "AAPL"],
        "date": pd.to_datetime(["2026-01-22", "2026-01-23"]),
        "close": [248.0, 250.0],
    })
    # News only exists for the 22nd, so the 23rd should come back with NaN sentiment.
    news_agg = merge.aggregate_sentiment(make_news_clean([
        ["AAPL", "2026-01-22", "http://a", 0.2, 0.3, "Bullish"],
    ]))
    merged = merge.merge_all(stock, sample_sp500_clean, news_agg)
    no_news_row = merged[merged["date"] == pd.Timestamp("2026-01-23")].iloc[0]
    assert pd.isna(no_news_row["sentiment_score_mean"])


# ═════════════════════════════════════════════════════════════════════════════
# 4. DATA VALIDATION
#    The validators use assert statements, so bad data raises AssertionError.
#    We test BOTH directions: clean data passes, broken data raises.
# ═════════════════════════════════════════════════════════════════════════════

def test_validate_stock_prices_accepts_clean_data(sample_stock_clean):
    """Verifies that pipeline.validate_stock_prices() accepts valid data without
    raising — the positive control that confirms it doesn't reject good data."""
    pipeline.validate_stock_prices(sample_stock_clean)  # would raise if it failed


def test_validate_stock_prices_rejects_high_below_low(sample_stock_clean):
    """Verifies that pipeline.validate_stock_prices() raises an error when a row's
    high price is below its low price, which is impossible.

    Starting from the clean fixture and corrupting ONE field proves the failure
    came from exactly that defect, nothing else."""
    sample_stock_clean.loc[0, "high"] = 1.0   # high now far below low
    with pytest.raises(AssertionError):
        pipeline.validate_stock_prices(sample_stock_clean)


def test_validate_news_sentiment_rejects_out_of_range_score():
    """Verifies that pipeline.validate_news_sentiment() raises an error when a
    sentiment score falls outside the valid -1 to 1 range (we feed it 5.0)."""
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
    """Verifies that merge.validate_merged() raises an error when a row is missing
    its sector, which would mean the company join silently failed."""
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
