## Documentation of API Keys, Rate Limits, and Access Restrictions

### Alpha Vantage API Access

Our project uses two Alpha Vantage API endpoints:

1. `TIME_SERIES_DAILY` for daily stock price data
2. `NEWS_SENTIMENT` for financial news and sentiment data

Both Alpha Vantage API sources require an API key. The API key is passed as the `apikey` parameter in each request. 

### Alpha Vantage Rate Limits

Alpha Vantage’s free API plan allows up to **25 API requests per day** for most datasets. 

This affects our project scope because fetching data for many S&P 500 companies could quickly exceed the free API limit. For the final version, we may either:

* use a smaller representative set of S&P 500 companies,
* spread API requests across multiple days,
* cache previously downloaded raw data files, or
* use a paid/premium API key if available.

### Alpha Vantage Access Restrictions

Not every Alpha Vantage endpoint is available with the free API key. We originally considered using `TIME_SERIES_DAILY_ADJUSTED`, but that endpoint returned a premium endpoint message during testing. Because of this, our project uses `TIME_SERIES_DAILY` instead.

The `NEWS_SENTIMENT` endpoint successfully returned news article and ticker sentiment data during testing. 

### Static CSV Access

The S&P 500 company dataset is a static CSV file and does not require an API key. It is loaded directly from a public URL using `pandas.read_csv()`.

This source does not have the same API rate limit issues as Alpha Vantage.             |
