# Panel dashboard — widgets, filters, dynamic sidebar, and FastListTemplate layout
import panel as pn
import data
import visualization as viz

pn.extension("plotly")

df = data.get_data()

# precompute animation dates from the full dataset
_anim_dates = sorted(data.compute_cumulative_returns(df)["date_str"].unique())

# global filter widgets (apply to all vizzes)
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

# viz-specific widgets
ticker_select = pn.widgets.Select(
    name="Select Stock", options=data.get_tickers(df), value="AAPL"
)
vol_window = pn.widgets.Select(
    name="Rolling Window (days)", options=[7, 14, 20, 30], value=20
)
date_player = pn.widgets.Player(
    name="Animation Player",
    start=0,
    end=len(_anim_dates) - 1,
    value=0,
    step=1,
    interval=300,
    loop_policy="loop",
    show_loop_controls=False,
    show_value=False,
    height=90,
    sizing_mode="stretch_width",
    margin=(10, 10),
)

reset_btn = pn.widgets.Button(name="Reset All Filters", button_type="warning")


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


def make_kpi(sectors, dates, tickers, min_vol_m):
    return viz.make_kpi_section(apply_filters(sectors, dates, tickers, min_vol_m))

def make_viz1(sectors, dates, tickers, min_vol_m):
    return viz.make_normalized_line_chart(apply_filters(sectors, dates, tickers, min_vol_m))

def make_viz2(ticker, sectors, dates, tickers, min_vol_m):
    return viz.make_candlestick_chart(apply_filters(sectors, dates, tickers, min_vol_m), ticker)

def make_viz3(sectors, dates, tickers, min_vol_m, frame_idx):
    return viz.make_animated_scatter(apply_filters(sectors, dates, tickers, min_vol_m), frame_idx)

def make_viz4(sectors, dates, tickers, min_vol_m, window):
    return viz.make_rolling_volatility_chart(apply_filters(sectors, dates, tickers, min_vol_m), window)


def reset(event=None):
    date_range.value  = (df["date"].min().to_pydatetime(), df["date"].max().to_pydatetime())
    sector_filter.value = []
    ticker_multi.value  = []
    min_volume.value    = 0
    ticker_select.value = "AAPL"
    vol_window.value    = 20
    date_player.value   = 0


reset_btn.on_click(reset)

# bind widgets to chart views
kpi_view  = pn.bind(make_kpi,  sector_filter, date_range, ticker_multi, min_volume)
viz1_view = pn.bind(make_viz1, sector_filter, date_range, ticker_multi, min_volume)
viz2_view = pn.bind(make_viz2, ticker_select, sector_filter, date_range, ticker_multi, min_volume)
viz3_view = pn.bind(make_viz3, sector_filter, date_range, ticker_multi, min_volume, date_player)
viz4_view = pn.bind(make_viz4, sector_filter, date_range, ticker_multi, min_volume, vol_window)

# create tabs before sidebar so we can watch tabs.param.active
tabs = pn.Tabs(
    ("Viz 1 — Overview",           viz1_view),
    ("Viz 2 — Stock Drill-Down",   viz2_view),
    ("Viz 3 — Risk/Return Anim.",  viz3_view),
    ("Viz 4 — Rolling Volatility", viz4_view),
)

# static sidebar elements
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


# dynamic sidebar — different filters shown per active tab
def make_sidebar(active):
    if active == 0:    # Overview
        cards = [pn.Card(date_range, sector_filter, ticker_multi,
                         title="Filters", width=320)]
    elif active == 1:  # Drill-Down
        cards = [
            pn.Card(ticker_select, title="Select Stock", width=320),
            pn.Card(date_range, title="Date Range", width=320),
        ]
    elif active == 2:  # Animation
        cards = [
            pn.Card(date_range, sector_filter, ticker_multi,
                    title="Filters", width=320),
            pn.Card(date_player, title="▶  Animation Player", width=320),
        ]
    else:              # Rolling Volatility
        cards = [pn.Card(date_range, ticker_multi, vol_window,
                         title="Filters", width=320)]

    cards.append(pn.Card(min_volume, title="Volume Filter", width=320))
    return pn.Column(info, *cards, reset_card)


sidebar_reactive = pn.bind(make_sidebar, tabs.param.active)

# dashboard layout
layout = pn.template.FastListTemplate(
    title="S&P 500 Market Dashboard",
    sidebar=[pn.Column(sidebar_reactive)],
    main=[pn.Column(
        pn.pane.Markdown("## Key Metrics", margin=(12, 0, 4, 12)),
        pn.Row(kpi_view, sizing_mode="stretch_width"),
        pn.layout.Divider(),
        tabs,
        sizing_mode="stretch_width",
    )],
    header_background="#1565C0",
    theme_toggle=False,
).servable()

if __name__ == "__main__":
    layout.show()
