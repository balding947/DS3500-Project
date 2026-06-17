import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import panel as pn
import data


def _no_data_fig(title):
    fig = go.Figure()
    fig.add_annotation(
        text="No data for selected filters",
        showarrow=False, font=dict(size=16),
        xref="paper", yref="paper", x=0.5, y=0.5,
    )
    fig.update_layout(height=500, title=title)
    return pn.pane.Plotly(fig)


# viz 1 — high-level overview: all stocks indexed to 100
def make_normalized_line_chart(df):
    if df.empty:
        return _no_data_fig("Relative Stock Performance")

    d = df.copy()
    d["indexed"] = d.groupby("symbol")["adjusted_close"].transform(
        lambda x: x / x.iloc[0] * 100
    )

    fig = px.line(
        d,
        x="date",
        y="indexed",
        color="symbol",
        hover_data=["company_name", "sector"],
        labels={"indexed": "Indexed Price (Start = 100)", "date": "Date", "symbol": "Ticker"},
        title="Relative Stock Performance — All Tickers (Indexed to 100)",
        color_discrete_sequence=px.colors.qualitative.Bold,
    )
    fig.add_hline(y=100, line_dash="dash", line_color="gray", opacity=0.4,
                  annotation_text="Baseline (100)")
    fig.update_layout(height=520, hovermode="x unified", legend_title="Ticker")
    return pn.pane.Plotly(fig)


# viz 2 — drill-down: candlestick + volume + sentiment for one stock
def make_candlestick_chart(df, ticker):
    d = df[df["symbol"] == ticker].copy()

    if d.empty:
        return _no_data_fig(f"Candlestick — {ticker}")

    has_sentiment = not d["ticker_sentiment_mean"].isna().all()
    rows = 3 if has_sentiment else 2
    row_heights = [0.6, 0.2, 0.2] if has_sentiment else [0.7, 0.3]
    subplot_titles = (ticker, "Volume", "Ticker Sentiment") if has_sentiment else (ticker, "Volume")

    fig = make_subplots(
        rows=rows, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=row_heights,
        subplot_titles=subplot_titles,
    )

    fig.add_trace(go.Candlestick(
        x=d["date"], open=d["open"], high=d["high"],
        low=d["low"], close=d["close"],
        name=ticker,
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
    ), row=1, col=1)

    bar_colors = ["#26a69a" if r >= 0 else "#ef5350" for r in d["daily_return"].fillna(0)]
    fig.add_trace(go.Bar(
        x=d["date"], y=d["volume"],
        name="Volume", marker_color=bar_colors, showlegend=False,
    ), row=2, col=1)

    if has_sentiment:
        fig.add_trace(go.Scatter(
            x=d["date"], y=d["ticker_sentiment_mean"],
            mode="lines+markers", name="Ticker Sentiment",
            line=dict(color="#ff9800", width=2), marker=dict(size=5),
            connectgaps=True,
        ), row=3, col=1)
        fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.4, row=3, col=1)

    fig.update_layout(
        height=620,
        title=f"{ticker} — {d['company_name'].iloc[0]}",
        xaxis_rangeslider_visible=False,
        showlegend=False,
    )
    return pn.pane.Plotly(fig)


# viz 3 — animated: risk vs return scatter (Panel Player drives animation)
def make_animated_scatter(df, frame_idx):
    cum = data.compute_cumulative_returns(df)

    if cum.empty:
        return _no_data_fig("Risk vs Return — Animated")

    dates = sorted(cum["date_str"].unique())
    date = dates[min(int(frame_idx), len(dates) - 1)]

    frame_data = cum[cum["date_str"] == date][
        ["symbol", "cumulative_return", "sector", "company_name"]
    ].copy()

    vol_to_date = data.compute_volatility(df[df["date"] <= pd.Timestamp(date)])
    frame_data = frame_data.merge(vol_to_date, on="symbol", how="left")

    # fixed axis ranges so animation doesn't jump
    all_cum = cum["cumulative_return"]
    all_vol = data.compute_volatility(df)["volatility"]

    fig = px.scatter(
        frame_data,
        x="cumulative_return",
        y="volatility",
        color="sector",
        text="symbol",
        hover_data=["company_name"],
        labels={
            "cumulative_return": "Cumulative Return",
            "volatility": "Annualized Volatility",
        },
        title=f"Risk vs Return — {date}",
        color_discrete_sequence=px.colors.qualitative.Bold,
    )
    fig.update_traces(textposition="top center", marker=dict(size=18))
    fig.add_vline(x=0, line_dash="dash", line_color="gray", opacity=0.4,
                  annotation_text="Break-even")
    fig.add_hline(y=all_vol.mean(), line_dash="dot", line_color="gray", opacity=0.4,
                  annotation_text="Avg Vol")
    fig.update_xaxes(range=[all_cum.min() - 0.05, all_cum.max() + 0.05])
    fig.update_yaxes(range=[0, all_vol.max() + 0.1])
    fig.update_layout(height=520)
    return pn.pane.Plotly(fig)


# viz 4 — rolling volatility over time
def make_rolling_volatility_chart(df, window):
    d = data.compute_rolling_volatility(df, int(window)).dropna(subset=["rolling_vol"])

    if d.empty:
        return _no_data_fig(f"Rolling Volatility — {window}-Day")

    fig = px.line(
        d,
        x="date",
        y="rolling_vol",
        color="symbol",
        labels={
            "rolling_vol": f"{window}-Day Rolling Volatility",
            "date": "Date",
            "symbol": "Ticker",
        },
        title=f"Rolling Volatility — {window}-Day Window",
        color_discrete_sequence=px.colors.qualitative.Bold,
    )
    fig.update_layout(height=520, hovermode="x unified")
    return pn.pane.Plotly(fig)


# kpi row — reactive numeric metric cards shown above the tabs
def make_kpi_section(df):
    if df.empty:
        return pn.pane.Markdown("*No data for selected filters*")

    _, stock_returns = data.compute_sector_returns(df)
    vol = data.compute_volatility(df)

    best  = stock_returns.loc[stock_returns["total_return"].idxmax()]
    worst = stock_returns.loc[stock_returns["total_return"].idxmin()]
    most_vol = vol.loc[vol["volatility"].idxmax()]
    avg_ret = df["daily_return"].mean()

    def card(label, value_str, color):
        return pn.pane.HTML(f"""
        <div style="background:#ffffff;border-radius:10px;padding:14px 18px;
                    text-align:center;min-width:150px;
                    border-top:4px solid {color};
                    box-shadow:0 1px 4px rgba(0,0,0,0.08)">
          <div style="font-size:11px;color:#888;text-transform:uppercase;
                      letter-spacing:0.6px;margin-bottom:6px">{label}</div>
          <div style="font-size:26px;font-weight:700;color:{color}">{value_str}</div>
        </div>
        """, height=90)

    best_color  = "#2ecc71" if best["total_return"]  >= 0 else "#e74c3c"
    worst_color = "#e74c3c" if worst["total_return"] <= 0 else "#2ecc71"

    return pn.Row(
        card(f"Best Return · {best['symbol']}",   f"{best['total_return']:+.1%}",  best_color),
        card(f"Worst Return · {worst['symbol']}", f"{worst['total_return']:+.1%}", worst_color),
        card(f"Most Volatile · {most_vol['symbol']}", f"{most_vol['volatility']:.1%}", "#e67e22"),
        card("Avg Daily Return", f"{avg_ret:+.3%}", "#3498db"),
        card("Trading Days", str(df["date"].nunique()), "#9b59b6"),
        sizing_mode="stretch_width",
    )
