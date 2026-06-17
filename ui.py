# Panel dashboard — widgets, filters, dynamic sidebar, and FastListTemplate layout
import panel as pn
import data
import visualization as viz

pn.extension("plotly")

# load the full merged dataset once at startup
df = data.get_data()

# precompute all animation frame dates from the full dataset so the Player range is always valid
_anim_dates = sorted(data.compute_cumulative_returns(df)["date_str"].unique())


# --- Global filter widgets (apply to all tabs) ---

date_range = pn.widgets.DateRangeSlider(
    name="Date Range",
    start=df["date"].min().to_pydatetime(),
    end=df["date"].max().to_pydatetime(),
    value=(df["date"].min().to_pydatetime(), df["date"].max().to_pydatetime()),
)
sector_filter = pn.widgets.MultiChoice(
    name="Filter Sectors", options=data.get_sectors(df)
)
ticker_multi = pn.widgets.MultiChoice(
    name="Filter Tickers", options=data.get_tickers(df)
)
min_volume = pn.widgets.IntSlider(
    name="Min Daily Volume (M shares)", start=0, end=200, step=10, value=0
)


# --- Tab-specific widgets ---

# Viz 2 — single stock selector for the candlestick chart
ticker_select = pn.widgets.Select(
    name="Select Stock", options=data.get_tickers(df), value="AAPL"
)

# Viz 4 — rolling window length for the volatility chart
vol_window = pn.widgets.Select(
    name="Rolling Window (days)", options=[7, 14, 20, 30], value=20
)

# Viz 3 — Player widget drives the animation frame index
date_player = pn.widgets.Player(
    name="Animation Player",
    start=0,
    end=len(_anim_dates) - 1,
    value=0,
    step=1,
    interval=600,       # milliseconds between frames
    loop_policy="once",
    show_loop_controls=False,
    show_value=False,
    height=90,
    sizing_mode="stretch_width",
    margin=(10, 10),
)

reset_btn = pn.widgets.Button(name="Reset All Filters", button_type="warning")


# --- Filter logic ---

def apply_filters(sectors, dates, tickers, min_vol_m):
    filtered = df.copy()
    if sectors:
        filtered = filtered[filtered["sector"].isin(sectors)]
    if tickers:
        filtered = filtered[filtered["symbol"].isin(tickers)]
    filtered = data.filter_data(filtered, start_date=dates[0], end_date=dates[1])
    if min_vol_m > 0:
        filtered = filtered[filtered["volume"] >= min_vol_m * 1_000_000]
    return filtered


# --- Chart render functions (called reactively when any bound widget changes) ---

# KPI cards above the tabs
def make_kpi(sectors, dates, tickers, min_vol_m):
    return viz.make_kpi_section(apply_filters(sectors, dates, tickers, min_vol_m))

# Viz 1 — normalized line chart (all tickers indexed to 100)
def make_viz1(sectors, dates, tickers, min_vol_m):
    return viz.make_normalized_line_chart(apply_filters(sectors, dates, tickers, min_vol_m))

# Viz 2 — candlestick + volume + sentiment for one selected stock
def make_viz2(ticker, sectors, dates, tickers, min_vol_m):
    return viz.make_candlestick_chart(apply_filters(sectors, dates, tickers, min_vol_m), ticker)

# Viz 3 — animated risk vs return scatter; frame_idx comes from the Player widget
def make_viz3(sectors, dates, tickers, min_vol_m, frame_idx):
    return viz.make_animated_scatter(apply_filters(sectors, dates, tickers, min_vol_m), frame_idx)

# Viz 4 — rolling volatility lines with configurable window
def make_viz4(sectors, dates, tickers, min_vol_m, window):
    return viz.make_rolling_volatility_chart(apply_filters(sectors, dates, tickers, min_vol_m), window)


def reset(event=None):
    date_range.value     = (df["date"].min().to_pydatetime(), df["date"].max().to_pydatetime())
    sector_filter.value  = []
    ticker_multi.value   = []
    min_volume.value     = 0
    ticker_select.value  = "AAPL"
    vol_window.value     = 20
    date_player.value    = 0


reset_btn.on_click(reset)


# --- Bind widgets to chart views ---
# pn.bind() re-runs the function whenever any of its widget arguments change

kpi_view  = pn.bind(make_kpi,  sector_filter, date_range, ticker_multi, min_volume)
viz1_view = pn.bind(make_viz1, sector_filter, date_range, ticker_multi, min_volume)
viz2_view = pn.bind(make_viz2, ticker_select, sector_filter, date_range, ticker_multi, min_volume)
viz3_view = pn.bind(make_viz3, sector_filter, date_range, ticker_multi, min_volume, date_player)
viz4_view = pn.bind(make_viz4, sector_filter, date_range, ticker_multi, min_volume, vol_window)


# --- Tabs (create before sidebar so we can watch which tab is active) ---

tabs = pn.Tabs(
    ("Viz 1 — Overview",           viz1_view),
    ("Viz 2 — Stock Drill-Down",   viz2_view),
    ("Viz 3 — Risk/Return Anim.",  viz3_view),
    ("Viz 4 — Rolling Volatility", viz4_view),
)


# --- Static sidebar header ---

stats = data.get_summary_stats(df)
info = pn.pane.Markdown(f"""
### S&P 500 Dashboard
**Tickers:** {stats['tickers']} &nbsp;|&nbsp; **Sectors:** {stats['sectors']}
**Date Range:** {stats['date_range']}
**Avg Daily Return:** {stats['avg_daily_return']}

*Prices: EODHD API*
*Sectors: S&P 500 CSV*
*Sentiment: Alpha Vantage*
""")
reset_card = pn.Card(reset_btn, title="Actions", width=320)


# --- Dynamic sidebar — shows different filter cards depending on the active tab ---

def make_sidebar(active):
    if active == 0:     # Viz 1 — Overview: sector + ticker + date filters
        cards = [pn.Card(date_range, sector_filter, ticker_multi,
                         title="Filters", width=320)]
    elif active == 1:   # Viz 2 — Drill-Down: single stock selector + date range
        cards = [
            pn.Card(ticker_select, title="Select Stock", width=320),
            pn.Card(date_range, title="Date Range", width=320),
        ]
    elif active == 2:   # Viz 3 — Animation: filters + Player widget to step through frames
        cards = [
            pn.Card(date_range, sector_filter, ticker_multi,
                    title="Filters", width=320),
            pn.Card(date_player, title="▶  Animation Player", width=320),
        ]
    else:               # Viz 4 — Rolling Volatility: date + ticker + window size
        cards = [pn.Card(date_range, ticker_multi, vol_window,
                         title="Filters", width=320)]

    cards.append(pn.Card(min_volume, title="Volume Filter", width=320))
    return pn.Column(info, *cards, reset_card)


# re-runs make_sidebar every time the active tab changes
sidebar_reactive = pn.bind(make_sidebar, tabs.param.active)


# --- Dashboard layout ---

layout = pn.template.FastListTemplate(
    title="S&P 500 Market Dashboard — Samuel Yao",
    sidebar=[pn.Column(sidebar_reactive)],
    main=[pn.Column(
        pn.pane.Markdown("## Key Metrics", margin=(12, 0, 4, 12)),
        pn.Row(kpi_view, sizing_mode="stretch_width"),  # KPI cards always visible
        pn.layout.Divider(),
        tabs,
        sizing_mode="stretch_width",
    )],
    header_background="#1565C0",
    theme_toggle=False,
).servable()

if __name__ == "__main__":
    layout.show()
