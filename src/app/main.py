"""SuperFolio (13F 컨센서스 스크리너) — Streamlit UI.

Only this module (and others under src/app/) may import streamlit.
All data loading/aggregation logic lives in src/edgar and src/analytics
and is called here, not reimplemented.

Multi-page layout (st.navigation, top position) mirrors Dataroma's own
top-menu structure: Home / Superinvestors / Grand Portfolio /
S&P 500 Grid / 현재가 조회 (RealTime, reinterpreted -- 13F itself is
quarterly + up to 45 days delayed, so "real-time filings" isn't a
meaningful thing to offer; a live price lookup over the tracked universe
is). Commentaries/Articles and a chronological Activity feed are
deliberately left out of this pass.

Run: streamlit run src/app/main.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

# `streamlit run src/app/main.py` (unlike `python -m streamlit run ...`)
# puts this file's own directory on sys.path, not the repo root -- so the
# `from src.xxx import yyy` absolute imports below would fail with
# "ModuleNotFoundError: No module named 'src'" on any host that invokes
# streamlit directly (seen in practice on Render). Fix it before those
# imports run, regardless of how/where this script gets launched.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd
import streamlit as st

from src.analytics.backtest import consensus_asof_schedule, simulate_portfolio
from src.analytics.consensus import (
    activity_summary,
    big_bets,
    consensus_holdings,
    consensus_trend,
    holders_of_cusip,
    quarter_changes,
    top_buys,
    top_sells,
)
from src.analytics.entry_price import with_entry_price_comparison
from src.analytics.insider import insider_buy_summary
from src.analytics.investor import investor_portfolio, investor_trend, portfolio_summary, position_trend
from src.analytics.overlap import jaccard_similarity, pairwise_overlap, similarity_matrix
from src.analytics.sp500_grid import sp500_ownership_summary
from src.edgar.build import CACHE_DIR, QUARTERS_TO_FETCH, build_all, load_investors
from src.edgar.client import EdgarClient
from src.edgar.insider_storage import load_insider_table
from src.edgar.recent_activity import load_recent_activity_table
from src.edgar.storage import load_holdings_table, save_holdings_table
from src.market.prices import get_52week_range, get_current_prices, get_price_history, get_quarterly_avg_prices
from src.market.sector_map import resolve_sectors
from src.market.sp500 import load_sp500
from src.market.ticker_map import resolve_tickers

ROOT = _REPO_ROOT
DB_PATH = ROOT / "data" / "holdings.db"
MARKET_DB_PATH = ROOT / "data" / "market.db"
INSIDER_DB_PATH = ROOT / "data" / "insider.db"
RECENT_ACTIVITY_DB_PATH = ROOT / "data" / "recent_activity.db"
# Matches scripts/build_insider.py's LOOKBACK_DAYS -- both live here rather
# than being imported from the script, since the script isn't meant to be
# imported (its module-level code has side effects if run directly).
INSIDER_LOOKBACK_LABEL = "최근 100일"
# Deliberately separate from MARKET_DB_PATH: a CUSIP->ticker mapping is
# effectively static and safe to pre-build + commit (like holdings.db), but
# MARKET_DB_PATH also holds "current price" snapshots that go stale within
# days -- shipping those as if fresh would be actively misleading. Keeping
# tickers in their own file lets one be committed without the other.
TICKER_DB_PATH = ROOT / "data" / "tickers.db"
SP500_CSV_PATH = ROOT / "data" / "sp500.csv"
USER_AGENT = "Aidan Kim aidankim3@gmail.com"

st.set_page_config(page_title="SuperFolio", layout="wide")

# Status colors (good/warning/critical/neutral), validated for >=3:1 text
# contrast on BOTH the light and dark chart surfaces -- see the dataviz
# skill's references/palette.md status table. Used as-is (same hex) in both
# themes rather than switching per mode, since Styler-baked inline CSS can't
# react to the viewer's live theme choice; bold weight keeps them >=3:1
# "large text" legible on both surfaces.
POS_COLOR = "#0ca30c"   # 매수 우호적 (신규/추가 편입, 비중·가격 상승)
NEG_COLOR = "#d03b3b"   # 매도 우호적 (축소/완전매도, 비중·가격 하락)
NEUTRAL_COLOR = "#898781"  # 변화 없음

# Sequential blue ramp (magnitude), light->dark, from palette.md's
# documented sequential steps -- used for heatmaps instead of an arbitrary
# matplotlib colormap.
_SEQUENTIAL_BLUE_STEPS = [
    "#fcfcfb", "#cde2fb", "#9ec5f4", "#6da7ec",
    "#3987e5", "#2a78d6", "#1c5cab", "#0d366b",
]

_CHANGE_TYPE_STYLE = {
    "신규": f"color: {POS_COLOR}; font-weight: 600",
    "추가": f"color: {POS_COLOR}; font-weight: 600",
    "유지": f"color: {NEUTRAL_COLOR}",
    "축소": f"color: {NEG_COLOR}; font-weight: 600",
    "매도": f"color: {NEG_COLOR}; font-weight: 600",
}


def _style_change_type(val: str) -> str:
    return _CHANGE_TYPE_STYLE.get(val, "")


def _style_signed(val: float) -> str:
    """Color a numeric delta by sign: green=positive, red=negative, gray=0/NaN."""
    if pd.isna(val) or val == 0:
        return f"color: {NEUTRAL_COLOR}"
    return f"color: {POS_COLOR}; font-weight: 600" if val > 0 else f"color: {NEG_COLOR}; font-weight: 600"


def _style_activity_count(sign: str):
    """Color an activity-count cell: neutral at 0, else pos/neg by `sign`."""
    def _style(v):
        if v == 0:
            return f"color: {NEUTRAL_COLOR}"
        return f"color: {POS_COLOR}; font-weight: 600" if sign == "pos" else f"color: {NEG_COLOR}; font-weight: 600"
    return _style


def _sequential_blue_cmap():
    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list("consensus_blue", _SEQUENTIAL_BLUE_STEPS)


@st.cache_data(ttl=300)
def _load_holdings(db_path: str) -> pd.DataFrame:
    df = load_holdings_table(Path(db_path))
    df["is_option"] = df["is_option"].astype(bool)
    df["period_date"] = pd.to_datetime(df["period_date"])
    return df


@st.cache_data(ttl=86400)
def _load_sp500(csv_path: str) -> pd.DataFrame:
    return load_sp500(Path(csv_path))


@st.cache_data(ttl=3600)
def _load_insider_transactions(db_path: str) -> pd.DataFrame:
    """Pre-built Form 4 insider-purchase snapshot (see scripts/build_insider.py)
    -- read-only here, no live SEC fetching on page load. Empty (correctly
    columned) if the build hasn't been run yet.
    """
    df = load_insider_table(Path(db_path))
    if not df.empty:
        df["filing_date"] = pd.to_datetime(df["filing_date"])
        df["transaction_date"] = pd.to_datetime(df["transaction_date"])
    return df


@st.cache_data(ttl=300)
def _load_recent_activity(db_path: str) -> pd.DataFrame:
    """Pre-built cross-form-type filing feed (see
    scripts/build_recent_activity.py) -- read-only here, no live SEC
    fetching on page load. Empty (correctly columned) if the build
    hasn't been run yet.
    """
    df = load_recent_activity_table(Path(db_path))
    if not df.empty:
        df["filing_date"] = pd.to_datetime(df["filing_date"])
    return df


def _build_data_inline() -> None:
    """Fetch fresh 13F data straight from SEC EDGAR and save it, using the
    same pipeline as `python -m src.edgar.build`. Lets a freshly-deployed
    instance (e.g. on Streamlit Community Cloud, which starts with an
    empty filesystem) self-initialize instead of requiring a local
    pre-built data/holdings.db to be shipped with the repo.
    """
    client = EdgarClient(user_agent=USER_AGENT)
    investors = load_investors()
    holdings = build_all(investors, client, cache_dir=CACHE_DIR, n_quarters=QUARTERS_TO_FETCH)
    save_holdings_table(holdings, DB_PATH)


def _available_periods(holdings: pd.DataFrame, years: int = 5) -> list[pd.Timestamp]:
    """Distinct report dates within the last `years` years of whatever the
    data's own latest date is (not wall-clock today, so a stale DB still
    shows a sensible window), most recent first -- the selectable range
    for the as-of period screener.

    Capped by calendar date rather than just taking QUARTERS_TO_FETCH's
    per-manager period_rank window: a manager who stopped filing years ago
    (e.g. converted to a family office, deregistered) still contributes
    their OWN "most recent 20" quarters to the data, which can be a much
    older, disjoint date range -- without this cap those stale dates would
    clutter a dropdown meant to mean "the last 5 years."
    """
    all_dates = holdings["period_date"].dropna().unique()
    if len(all_dates) == 0:
        return []
    cutoff = pd.Timestamp(max(all_dates)) - pd.DateOffset(years=years)
    return sorted((d for d in all_dates if d >= cutoff), reverse=True)


def _filter_by_period(
    df: pd.DataFrame, period: "pd.Timestamp | None", include_options: bool
) -> pd.DataFrame:
    if period is None:
        return df.iloc[0:0]
    scoped = df[df["period_date"] == period]
    if not include_options:
        scoped = scoped[~scoped["is_option"]]
    return scoped


def _sorted_by_weight_mode(
    df: pd.DataFrame, weight_mode: str, count_col: str, value_col: str
) -> pd.DataFrame:
    sort_col = count_col if weight_mode == "equal" else value_col
    return df.sort_values(sort_col, ascending=False).reset_index(drop=True)


_CHANGE_TYPE_LABELS = {
    "new_buy": "신규",
    "add": "추가",
    "trim": "축소",
    "sold_out": "매도",
    "unchanged": "유지",
}


@st.cache_data(ttl=3600, show_spinner="티커 조회 중...")
def _ticker_map(cusips_with_names: dict[str, str]) -> dict[str, str]:
    """CUSIP -> ticker for the display columns used app-wide.

    Cached in-memory for an hour since a ticker mapping is effectively
    static; TICKER_DB_PATH also disk-caches every lookup (including
    "not found"), so a CUSIP already seen in an earlier session is cheap
    even after this cache expires -- only genuinely new CUSIPs hit the
    network (OpenFIGI, rate-limited).
    """
    tickers = resolve_tickers(cusips_with_names, TICKER_DB_PATH, USER_AGENT)
    return {cusip: (ticker or "") for cusip, ticker in tickers.items()}


def _with_ticker_column(df: pd.DataFrame, ticker_map: dict[str, str]) -> pd.DataFrame:
    """Insert a 'ticker' column right after 'cusip' (no-op if there's no
    cusip column, or a ticker column is already present)."""
    if "cusip" not in df.columns or "ticker" in df.columns:
        return df
    out = df.copy()
    out.insert(out.columns.get_loc("cusip") + 1, "ticker", out["cusip"].map(ticker_map).fillna(""))
    return out


def _fetch_price_extras(held_now: pd.DataFrame, current_period_date: str) -> pd.DataFrame:
    """cusip -> ticker/entry_price/current_price/price_diff_pct/52-week
    range, for a single manager's currently-held positions. Network calls
    are disk-cached (ticker resolution in TICKER_DB_PATH, yfinance prices
    in MARKET_DB_PATH), so repeat calls for the same cusip/period are
    cheap after the first fetch -- bounded to one manager's holdings
    (~50-150 tickers), so a cold fetch is a one-time, one-manager cost,
    not a full-universe one.
    """
    cusips_with_names = dict(zip(held_now["cusip"], held_now["name_of_issuer"]))
    tickers = resolve_tickers(cusips_with_names, TICKER_DB_PATH, USER_AGENT)

    resolved_tickers = sorted({t for t in tickers.values() if t})
    entry_prices = get_quarterly_avg_prices(
        [(t, current_period_date) for t in resolved_tickers], MARKET_DB_PATH
    )
    current_prices = get_current_prices(resolved_tickers, MARKET_DB_PATH)
    week52 = get_52week_range(resolved_tickers, MARKET_DB_PATH)

    prices = pd.DataFrame(
        [
            {
                "cusip": cusip,
                "ticker": ticker,
                "entry_price": entry_prices.get((ticker, current_period_date)) if ticker else None,
                "current_price": current_prices.get(ticker) if ticker else None,
            }
            for cusip, ticker in tickers.items()
        ]
    )
    combined = with_entry_price_comparison(held_now, prices)[
        ["cusip", "ticker", "entry_price", "current_price", "price_diff_pct"]
    ].copy()
    combined["week52_low"] = combined["ticker"].map(lambda t: week52.get(t, (None, None))[0] if t else None)
    combined["week52_high"] = combined["ticker"].map(lambda t: week52.get(t, (None, None))[1] if t else None)
    return combined


def _sector_breakdown(held_now: pd.DataFrame, ticker_by_cusip: dict[str, str]) -> pd.DataFrame:
    """Current holdings grouped by sector, as a % of this manager's total
    holdings value. Tickers with no resolved sector (unmapped CUSIP, ETF,
    foreign issuer yfinance doesn't classify, etc.) fall into '미분류'
    rather than being silently dropped from the 100%.
    """
    resolved_tickers = sorted({t for t in ticker_by_cusip.values() if t})
    sectors = resolve_sectors(resolved_tickers, MARKET_DB_PATH)

    df = held_now.copy()
    df["sector"] = df["cusip"].map(ticker_by_cusip).map(lambda t: (sectors.get(t) or (None,))[0] if t else None)
    df["sector"] = df["sector"].fillna("미분류")

    total = df["curr_value_usd"].sum()
    grouped = df.groupby("sector")["curr_value_usd"].sum().reset_index()
    grouped["비중(%)"] = grouped["curr_value_usd"] / total * 100 if total else 0.0
    return grouped.rename(columns={"sector": "섹터"})[["섹터", "비중(%)"]]


def _render_stock_drilldown(
    cusip: str,
    name_of_issuer: str,
    ticker: str,
    current_all: pd.DataFrame,
    previous_all: pd.DataFrame,
    changes: pd.DataFrame,
    trend_window: pd.DataFrame,
) -> None:
    """The "click a stock row" panel shared by Grand Portfolio's 컨센서스
    tab and the S&P 500 Grid page: who holds it now, its 5-year consensus
    trend, its price chart, and who bought/sold it this quarter.
    """
    sel_ticker = f" ({ticker})" if ticker else ""
    holders = holders_of_cusip(current_all, cusip)
    st.divider()
    st.markdown(f"##### {name_of_issuer}{sel_ticker} 보유 투자자 ({len(holders)}명)")
    st.dataframe(
        holders,
        hide_index=True,
        width="stretch", row_height=30,
        column_config={
            "manager_name": st.column_config.TextColumn("투자자"),
            "shares": st.column_config.NumberColumn("주식수", format="%,d"),
            "value_usd": st.column_config.NumberColumn("금액($)", format="$%,.0f"),
            "weight_pct": st.column_config.NumberColumn(
                "이 투자자 포트폴리오 내 비중(%)", format="%.2f%%"
            ),
        },
    )

    st.markdown(f"##### {name_of_issuer}{sel_ticker} 분기별 추이 (최근 5년)")
    stock_trend = consensus_trend(trend_window, cusip)
    if len(stock_trend) < 2:
        st.caption("추이를 그리기엔 분기 데이터가 부족합니다.")
    else:
        trend_indexed = stock_trend.set_index("period_date")
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            st.caption("보유자 수")
            st.line_chart(trend_indexed[["holder_count"]].rename(columns={"holder_count": "보유자 수"}))
        with sc2:
            st.caption("합산 금액($)")
            st.line_chart(trend_indexed[["total_value_usd"]].rename(columns={"total_value_usd": "합산 금액"}))
        with sc3:
            st.caption("평균 비중(%)")
            st.line_chart(trend_indexed[["avg_weight_pct"]].rename(columns={"avg_weight_pct": "평균 비중"}))

    st.markdown(f"##### {name_of_issuer}{sel_ticker} 주가 (최근 5년)")
    if not ticker:
        st.caption("티커를 찾지 못해 주가를 표시할 수 없습니다.")
    else:
        price_start = (date.today() - pd.DateOffset(years=5)).date().isoformat()
        price_series = get_price_history(ticker, price_start, date.today().isoformat(), MARKET_DB_PATH)
        if price_series.empty:
            st.caption("주가 데이터를 가져오지 못했습니다.")
        else:
            st.line_chart(price_series.rename("종가($)"))

    st.markdown(f"##### {name_of_issuer}{sel_ticker} 이번 분기 투자자별 변화")
    stock_changes = changes[changes["cusip"] == cusip].copy()
    if previous_all.empty:
        st.caption("직전 분기 데이터가 없어 변화를 계산할 수 없습니다.")
    elif stock_changes.empty:
        st.caption("이번 분기 이 종목을 매수/매도/비중 조정한 투자자가 없습니다 (전원 유지).")
    else:
        stock_changes["change_type"] = stock_changes["change_type"].map(_CHANGE_TYPE_LABELS)
        stock_changes = stock_changes.sort_values("value_delta_usd", ascending=False)
        styled_changes = stock_changes.style.map(_style_change_type, subset=["change_type"]).map(
            _style_signed, subset=["shares_delta", "value_delta_usd", "weight_delta_pct"]
        )
        st.dataframe(
            styled_changes,
            hide_index=True,
            width="stretch", row_height=30,
            column_config={
                "manager_name": st.column_config.TextColumn("투자자"),
                "change_type": st.column_config.TextColumn("변화"),
                "prev_shares": st.column_config.NumberColumn("이전 주식수", format="%,d"),
                "curr_shares": st.column_config.NumberColumn("현재 주식수", format="%,d"),
                "shares_delta": st.column_config.NumberColumn("주식수 변화", format="%,d"),
                "prev_value_usd": None,
                "curr_value_usd": None,
                "value_delta_usd": st.column_config.NumberColumn("금액 변화($)", format="$%,.0f"),
                "prev_weight_pct": None,
                "curr_weight_pct": None,
                "weight_delta_pct": st.column_config.NumberColumn("비중 변화(%p)", format="%.2f%%"),
                "cik": None,
                "cusip": None,
                "name_of_issuer": None,
            },
        )


def _render_investor_detail(
    holdings: pd.DataFrame,
    previous_all: pd.DataFrame,
    current_all: pd.DataFrame,
    manager_name: str,
    cik: str,
    selected_period: "pd.Timestamp | None",
    period_options: list,
    include_options: bool,
    ticker_map: dict,
) -> None:
    prev_mgr = previous_all[previous_all["cik"] == cik]
    curr_mgr = current_all[current_all["cik"] == cik]
    # Option weight must reflect the manager's TRUE mix regardless of the
    # global "옵션 포함" toggle, so this reads from unfiltered `holdings`.
    raw_curr_mgr = holdings[(holdings["period_date"] == selected_period) & (holdings["cik"] == cik)]

    if prev_mgr.empty and curr_mgr.empty:
        st.info(f"{manager_name}의 보유 내역이 없습니다 (현재 옵션 포함 설정 기준).")
        return

    portfolio = investor_portfolio(prev_mgr, curr_mgr)
    summary = portfolio_summary(portfolio, raw_curr_mgr).iloc[0]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("종목 수", int(summary["n_holdings"]))
    m2.metric("상위 10종목 집중도", f"{summary['top10_concentration_pct']:.1f}%")
    turnover = summary["turnover_pct"]
    m3.metric("대략적 회전율", "N/A (직전 분기 없음)" if pd.isna(turnover) else f"{turnover:.1f}%")
    m4.metric("옵션 비중", f"{summary['option_weight_pct']:.1f}%")

    held_now = portfolio[portfolio["change_type"] != "sold_out"]
    if not held_now.empty:
        chart_data = held_now.nlargest(15, "curr_weight_pct")[["name_of_issuer", "curr_weight_pct"]].rename(
            columns={"name_of_issuer": "종목명", "curr_weight_pct": "비중(%)"}
        )
        # Horizontal so long company names read left-to-right instead of
        # being rotated/cramped as vertical x-axis labels; sorted so the
        # biggest position is the top bar.
        st.bar_chart(chart_data, x="종목명", y="비중(%)", horizontal=True, sort="-비중(%)")

    trend_scope = holdings[(holdings["cik"] == cik) & (holdings["period_date"].isin(period_options))]
    trend_filtered = trend_scope if include_options else trend_scope[~trend_scope["is_option"]]

    display_df = portfolio[
        ["cusip", "name_of_issuer", "curr_weight_pct", "curr_value_usd", "curr_shares",
         "change_type", "weight_delta_pct"]
    ].copy()
    display_df["change_type"] = display_df["change_type"].map(_CHANGE_TYPE_LABELS)
    display_df = _with_ticker_column(display_df, ticker_map)

    price_extras = None
    if not held_now.empty and not curr_mgr.empty:
        current_period_date = curr_mgr["period_date"].iloc[0].strftime("%Y-%m-%d")
        with st.spinner(f"{manager_name}의 가격/52주 데이터 조회 중..."):
            try:
                price_extras = _fetch_price_extras(held_now, current_period_date)
            except Exception as exc:  # third-party API hiccups must not crash the app
                st.warning(f"가격 조회 중 오류가 발생했습니다: {exc}")

    signed_cols = ["weight_delta_pct"]
    if price_extras is not None:
        # price_extras carries its own 'ticker' (resolved from held_now) --
        # drop display_df's ticker_map-derived one first so the merge
        # doesn't collide, then price_extras becomes the single source of
        # truth for ticker/entry/current/diff/52wk together.
        display_df = display_df.drop(columns=["ticker"]).merge(price_extras, on="cusip", how="left")
        signed_cols.append("price_diff_pct")
    display_df = display_df.sort_values("curr_value_usd", ascending=False).reset_index(drop=True)

    styled_df = display_df.style.map(_style_change_type, subset=["change_type"]).map(
        _style_signed, subset=signed_cols
    )

    event = st.dataframe(
        styled_df,
        hide_index=True,
        width="stretch", row_height=30,
        on_select="rerun",
        selection_mode="single-row",
        key=f"investor_table_{cik}",
        column_config={
            "cusip": st.column_config.TextColumn("CUSIP"),
            "ticker": st.column_config.TextColumn("티커"),
            "name_of_issuer": st.column_config.TextColumn("종목명"),
            "curr_weight_pct": st.column_config.NumberColumn("비중(%)", format="%.2f%%"),
            "curr_value_usd": st.column_config.NumberColumn("금액($)", format="$%,.0f"),
            "curr_shares": st.column_config.NumberColumn("주식수", format="%,d"),
            "change_type": st.column_config.TextColumn("변화"),
            "weight_delta_pct": st.column_config.NumberColumn("변화(%p)", format="%.2f%%"),
            "entry_price": st.column_config.NumberColumn("추정 진입가($)", format="$%.2f"),
            "current_price": st.column_config.NumberColumn("현재가($)", format="$%.2f"),
            "price_diff_pct": st.column_config.NumberColumn("가격 차이(%)", format="%.1f%%"),
            "week52_low": st.column_config.NumberColumn("52주 최저($)", format="$%.2f"),
            "week52_high": st.column_config.NumberColumn("52주 최고($)", format="$%.2f"),
        },
    )
    st.caption(
        f"{len(held_now)}개 종목 보유 중 (직전 분기 대비 변화 포함 전체 {len(portfolio)}행). "
        "**진입가**는 실제 매입가가 아니라 보유 중인 분기의 평균 주가 근사치입니다 (13F는 "
        "체결일·체결가를 공시하지 않음). 종목 행을 클릭하면 이 투자자의 해당 종목 보유 "
        "추이가 아래 표시됩니다."
    )

    selected_rows = event["selection"]["rows"] if event and event.get("selection") else []
    if selected_rows:
        sel = display_df.iloc[selected_rows[0]]
        sel_ticker = f" ({sel['ticker']})" if sel.get("ticker") else ""
        st.divider()
        st.markdown(f"##### {manager_name} — {sel['name_of_issuer']}{sel_ticker} 보유 추이 (최근 5년)")
        position = position_trend(trend_filtered, sel["cusip"])
        if len(position) < 2:
            st.caption("추이를 그리기엔 분기 데이터가 부족합니다.")
        else:
            pos_indexed = position.set_index("period_date")
            pc1, pc2, pc3 = st.columns(3)
            with pc1:
                st.caption("주식수")
                st.line_chart(pos_indexed[["shares"]].rename(columns={"shares": "주식수"}))
            with pc2:
                st.caption("금액($)")
                st.line_chart(pos_indexed[["value_usd"]].rename(columns={"value_usd": "금액"}))
            with pc3:
                st.caption("포트폴리오 내 비중(%)")
                st.line_chart(pos_indexed[["weight_pct"]].rename(columns={"weight_pct": "비중"}))

        if sel.get("ticker"):
            price_start = (date.today() - pd.DateOffset(years=5)).date().isoformat()
            price_series = get_price_history(sel["ticker"], price_start, date.today().isoformat(), MARKET_DB_PATH)
            if not price_series.empty:
                st.caption(f"{sel['ticker']} 주가($)")
                st.line_chart(price_series.rename("종가($)"))

    st.divider()
    st.markdown("##### 분기별 변화 추이 (최근 5년)")
    trend = investor_trend(trend_filtered, trend_scope)
    if len(trend) < 2:
        st.caption("추이를 그리기엔 분기 데이터가 부족합니다.")
    else:
        trend_indexed = trend.set_index("period_date")
        tc1, tc2 = st.columns(2)
        with tc1:
            st.caption("종목 수")
            st.line_chart(trend_indexed[["n_holdings"]].rename(columns={"n_holdings": "종목 수"}))
        with tc2:
            st.caption("상위10 집중도 / 회전율 / 옵션 비중 (%)")
            st.line_chart(
                trend_indexed[["top10_concentration_pct", "turnover_pct", "option_weight_pct"]].rename(
                    columns={
                        "top10_concentration_pct": "상위10 집중도",
                        "turnover_pct": "회전율",
                        "option_weight_pct": "옵션 비중",
                    }
                )
            )

    st.divider()
    st.markdown("##### 섹터 비중")
    if held_now.empty:
        st.caption("보유 종목이 없습니다.")
    else:
        held_tickers = {cusip: ticker_map.get(cusip) for cusip in held_now["cusip"]}
        with st.spinner(f"{manager_name}의 섹터 데이터 조회 중..."):
            try:
                sector_df = _sector_breakdown(held_now, held_tickers)
            except Exception as exc:  # third-party API hiccups must not crash the app
                st.warning(f"섹터 조회 중 오류가 발생했습니다: {exc}")
                sector_df = None
        if sector_df is not None and not sector_df.empty:
            st.bar_chart(sector_df, x="섹터", y="비중(%)", horizontal=True, sort="-비중(%)")


def _render_overlap_analysis(
    previous_all: pd.DataFrame, current_all: pd.DataFrame, ticker_map: dict
) -> None:
    manager_names = sorted(current_all["manager_name"].unique())
    if len(manager_names) < 2:
        st.info("비교하려면 최소 2명의 투자자 데이터가 필요합니다.")
        return

    col_a, col_b = st.columns(2)
    with col_a:
        manager_a = st.selectbox("투자자 A", manager_names, index=0, key="overlap_a")
    with col_b:
        manager_b = st.selectbox(
            "투자자 B", manager_names, index=min(1, len(manager_names) - 1), key="overlap_b"
        )

    if manager_a == manager_b:
        st.warning("서로 다른 투자자 2명을 선택하세요.")
        return

    cik_a = current_all.loc[current_all["manager_name"] == manager_a, "cik"].iloc[0]
    cik_b = current_all.loc[current_all["manager_name"] == manager_b, "cik"].iloc[0]

    portfolio_a = investor_portfolio(
        previous_all[previous_all["cik"] == cik_a], current_all[current_all["cik"] == cik_a]
    )
    portfolio_b = investor_portfolio(
        previous_all[previous_all["cik"] == cik_b], current_all[current_all["cik"] == cik_b]
    )

    jaccard = jaccard_similarity(
        current_all[current_all["cik"] == cik_a], current_all[current_all["cik"] == cik_b]
    )
    st.metric(f"{manager_a} ↔ {manager_b} 포트폴리오 유사도 (자카드 지수)", f"{jaccard * 100:.1f}%")

    overlap = pairwise_overlap(portfolio_a, portfolio_b).copy()
    overlap["a_change_type"] = overlap["a_change_type"].map(_CHANGE_TYPE_LABELS)
    overlap["b_change_type"] = overlap["b_change_type"].map(_CHANGE_TYPE_LABELS)

    display_cols = ["cusip", "ticker", "name_of_issuer", "a_change_type", "b_change_type", "a_shares", "b_shares"]
    column_config = {
        "cusip": st.column_config.TextColumn("CUSIP"),
        "ticker": st.column_config.TextColumn("티커"),
        "name_of_issuer": st.column_config.TextColumn("종목명"),
        "a_change_type": st.column_config.TextColumn(f"{manager_a} 변화"),
        "b_change_type": st.column_config.TextColumn(f"{manager_b} 변화"),
        "a_shares": st.column_config.NumberColumn(f"{manager_a} 주식수", format="%,d"),
        "b_shares": st.column_config.NumberColumn(f"{manager_b} 주식수", format="%,d"),
    }
    overlap = _with_ticker_column(overlap, ticker_map)

    common = overlap[overlap["relationship"] == "common"]
    only_a = overlap[overlap["relationship"] == "only_a"]
    only_b = overlap[overlap["relationship"] == "only_b"]
    opposite = overlap[overlap["opposite_trade"]]

    def _styled_overlap(sub: pd.DataFrame):
        return sub[display_cols].style.map(_style_change_type, subset=["a_change_type", "b_change_type"])

    st.markdown(f"###### 공통 보유 종목 ({len(common)}개)")
    st.dataframe(_styled_overlap(common), hide_index=True, width="stretch", row_height=30, column_config=column_config)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"###### {manager_a}만 보유 ({len(only_a)}개)")
        st.dataframe(_styled_overlap(only_a), hide_index=True, width="stretch", row_height=30, column_config=column_config)
    with col2:
        st.markdown(f"###### {manager_b}만 보유 ({len(only_b)}개)")
        st.dataframe(_styled_overlap(only_b), hide_index=True, width="stretch", row_height=30, column_config=column_config)

    st.markdown(f"###### 반대 매매 종목 ({len(opposite)}개) — 이번 분기 한쪽은 매수, 한쪽은 매도")
    st.dataframe(_styled_overlap(opposite), hide_index=True, width="stretch", row_height=30, column_config=column_config)

    st.divider()
    st.markdown("##### 전체 투자자 쌍 포트폴리오 유사도 히트맵 (자카드 지수, %)")
    st.caption("현재 보유 종목(옵션 포함 설정 반영) 집합의 자카드 유사도입니다. 대각선은 항상 100%.")
    matrix = similarity_matrix(current_all)
    styled = matrix.style.format("{:.0f}%").background_gradient(cmap=_sequential_blue_cmap(), vmin=0, vmax=100)
    st.dataframe(styled, width="stretch", row_height=30)


BENCHMARK_TICKER = "SPY"


def _run_backtest(all_holdings: pd.DataFrame, top_n: int, cost_bps: float) -> dict:
    """Orchestrates the full backtest: build the as-of consensus schedule,
    resolve tickers, fetch price history, simulate strategy + benchmark.
    Network calls (ticker map, yfinance) are disk-cached in
    MARKET_DB_PATH. Returns a dict of results for the UI to render.
    """
    stock_only = all_holdings[~all_holdings["is_option"]].copy()
    stock_only["period_date"] = stock_only["period_date"].dt.strftime("%Y-%m-%d")

    schedule = consensus_asof_schedule(stock_only, top_n=top_n)
    if schedule.empty:
        return {"error": "백테스트에 쓸 분기 데이터가 없습니다."}

    late_filings = schedule[schedule["days_after_period_end"] > 45]

    all_cusips = sorted({c for cusips in schedule["cusips"] for c in cusips})
    name_by_cusip = (
        stock_only[stock_only["cusip"].isin(all_cusips)]
        .drop_duplicates("cusip")
        .set_index("cusip")["name_of_issuer"]
        .to_dict()
    )
    tickers_by_cusip = resolve_tickers(
        {c: name_by_cusip.get(c, c) for c in all_cusips}, TICKER_DB_PATH, USER_AGENT
    )
    unresolved = [c for c, t in tickers_by_cusip.items() if not t]

    start = min(schedule["entry_date"])
    end = datetime.today().strftime("%Y-%m-%d")
    tickers_needed = sorted({t for t in tickers_by_cusip.values() if t} | {BENCHMARK_TICKER})

    price_series = {}
    for ticker in tickers_needed:
        series = get_price_history(ticker, start, end, MARKET_DB_PATH)
        if not series.empty:
            price_series[ticker] = series
    if not price_series:
        return {"error": "가격 데이터를 하나도 가져오지 못했습니다."}
    price_history = pd.concat(price_series.values(), axis=1)

    rebalances = [
        {
            "entry_date": row["entry_date"],
            "tickers": [tickers_by_cusip[c] for c in row["cusips"] if tickers_by_cusip.get(c)],
        }
        for _, row in schedule.iterrows()
    ]
    strategy = simulate_portfolio(price_history, rebalances, cost_bps=cost_bps)

    benchmark_rebalances = [{"entry_date": schedule["entry_date"].iloc[0], "tickers": [BENCHMARK_TICKER]}]
    benchmark = simulate_portfolio(price_history, benchmark_rebalances, cost_bps=0)

    return {
        "schedule": schedule,
        "late_filings": late_filings,
        "unresolved_cusips": unresolved,
        "strategy": strategy,
        "benchmark": benchmark,
    }


def _render_backtest_tab(all_holdings: pd.DataFrame, n_managers: int) -> None:
    st.markdown("##### 컨센서스 상위 N종목 동일가중 백테스트")
    st.caption(
        "\"매 분기 컨센서스 상위 N종목을 동일가중으로 보유\"하는 단순 전략을 과거로 "
        "시뮬레이션합니다. 리밸런싱 시점은 분기 기준일이 아니라 **그 분기 컨센서스가 "
        "실제로 전부 공개된 시점**(추적 중인 투자자들 중 가장 늦게 제출한 filing_date)입니다 "
        "— 13F는 기준일로부터 최대 45일 뒤에 제출되므로, 기준일 가격을 쓰면 아직 공개되지 "
        "않은 정보로 거래하는 낙관적 백테스트가 됩니다."
    )

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        top_n = st.slider("상위 N종목", 3, 20, 10, key="backtest_top_n")
    with col2:
        cost_bps = st.number_input("리밸런싱 거래비용 (bps)", 0, 200, 10, key="backtest_cost_bps")
    with col3:
        run = st.button("백테스트 실행", key="backtest_run")

    if not run:
        st.info("실행 버튼을 누르면 시작합니다 (외부 가격 데이터를 다수 조회하므로 시간이 걸릴 수 있습니다).")
        return

    with st.spinner("컨센서스 스케줄 계산 + 가격 조회 중..."):
        try:
            result = _run_backtest(all_holdings, top_n, float(cost_bps))
        except Exception as exc:
            st.error(f"백테스트 실행 중 오류가 발생했습니다: {exc}")
            return

    if "error" in result:
        st.warning(result["error"])
        return

    schedule = result["schedule"]
    strategy = result["strategy"]
    benchmark = result["benchmark"]

    if strategy.empty or benchmark.empty:
        st.warning("가격 데이터가 부족해 시뮬레이션할 수 없습니다.")
        return

    chart_df = pd.DataFrame(
        {
            f"전략 (상위 {top_n}종목)": strategy["value"],
            f"{BENCHMARK_TICKER} 벤치마크": benchmark["value"],
        }
    ).dropna(how="all")
    st.line_chart(chart_df)

    m1, m2, m3 = st.columns(3)
    strategy_return = strategy["value"].iloc[-1] / strategy["value"].iloc[0] - 1
    benchmark_return = benchmark["value"].iloc[-1] / benchmark["value"].iloc[0] - 1
    excess_return = strategy_return - benchmark_return
    m1.metric("전략 누적 수익률", f"{strategy_return * 100:.1f}%", delta=f"{strategy_return * 100:.1f}%")
    m2.metric(
        f"{BENCHMARK_TICKER} 누적 수익률",
        f"{benchmark_return * 100:.1f}%",
        delta=f"{benchmark_return * 100:.1f}%",
    )
    m3.metric("초과 수익률", f"{excess_return * 100:.1f}%p", delta=f"{excess_return * 100:.1f}%p")

    st.markdown("###### 리밸런싱 스케줄 (실제 공개 시점 기준)")
    schedule_display = schedule.copy()
    schedule_display["n_stocks"] = schedule_display["cusips"].apply(len)
    turnover_by_entry = strategy["turnover_pct"].to_dict()
    schedule_display["turnover_pct"] = schedule_display["entry_date"].map(
        lambda d: turnover_by_entry.get(pd.Timestamp(d))
    )
    schedule_display = schedule_display.drop(columns=["cusips"])
    st.dataframe(
        schedule_display,
        hide_index=True,
        width="stretch", row_height=30,
        column_config={
            "period_date": st.column_config.TextColumn("기준일"),
            "entry_date": st.column_config.TextColumn("실제 매매 가능 시점"),
            "days_after_period_end": st.column_config.NumberColumn("기준일 이후 며칠", format="%d일"),
            "n_stocks": st.column_config.NumberColumn("종목 수", format="%d"),
            "turnover_pct": st.column_config.NumberColumn("회전율(%)", format="%.1f%%"),
        },
    )

    if not result["late_filings"].empty:
        st.warning(
            f"{len(result['late_filings'])}개 분기는 마지막 제출이 기준일로부터 45일을 "
            "넘겼습니다 (지연 제출/수정 공시 등 실제 EDGAR 데이터의 특성)."
        )
    if result["unresolved_cusips"]:
        st.caption(
            f"티커 매핑 실패로 백테스트에서 제외된 종목 {len(result['unresolved_cusips'])}개 "
            f"(CUSIP: {', '.join(result['unresolved_cusips'][:10])}"
            f"{' 외' if len(result['unresolved_cusips']) > 10 else ''})"
        )

    st.divider()
    st.markdown("###### 이 백테스트의 한계")
    st.caption(
        f"- **생존편향**: 추적 대상 {n_managers}명은 현재 시점 기준으로 유명한 투자자를 선정한 "
        "목록입니다. 과거 시점에 실제로 이 명단을 구성했을 수 있는지, 그때도 이들이 "
        "'컨센서스 상위'였는지는 반영되지 않습니다.\n"
        "- **롱 주식만 반영**: 13F는 미국 롱 주식(및 옵션)만 공시합니다. 숏 포지션, 헤지, "
        "채권·해외자산·현금 등 실제 포트폴리오의 다른 부분은 전혀 반영되지 않습니다.\n"
        "- **근사 가격**: 진입가는 컨센서스가 공개된 날짜(또는 그 이후 첫 거래일)의 종가를 "
        "쓰며, 실제 어느 투자자도 정확히 그 가격에 사고팔지 않았을 것입니다.\n"
        f"- **표본 편향**: {n_managers}명의 컨센서스라 해도 특정 몇 명의 쏠린 베팅에 결과가 "
        "좌우될 수 있습니다 — '스마트 머니 전체의 신호'로 일반화할 수 없습니다.\n"
        "- **거래비용은 가정치**: 리밸런싱 거래비용은 위에서 입력한 고정 bps일 뿐, 실제 "
        "슬리피지·스프레드·시장충격을 반영하지 않습니다."
    )


def _render_period_and_options(holdings: pd.DataFrame) -> tuple:
    """기준 분기 + 옵션 포함 -- rendered at the top of every data page
    (not a sidebar) with FIXED widget keys, so picking a quarter on one
    page keeps it selected when you switch to another.
    """
    period_options = _available_periods(holdings)
    col1, col2 = st.columns([2, 1])
    with col1:
        selected_period = st.selectbox(
            "기준 분기 (최대 5년치 선택 가능)",
            period_options,
            index=0,
            format_func=lambda d: pd.Timestamp(d).date().isoformat(),
            key="selected_period",
        )
    with col2:
        include_options = st.toggle("옵션(PUT/CALL) 포함", value=False, key="include_options")
    return period_options, selected_period, include_options


def _render_weight_mode() -> str:
    weight_mode_label = st.radio(
        "정렬 기준", ["동일가중(보유자 수)", "금액가중($)"], horizontal=True, key="weight_mode_label"
    )
    return "equal" if weight_mode_label.startswith("동일") else "value"


def _render_min_holders(n_managers: int) -> int:
    return st.slider("최소 보유자/매수자/매도자 수", 1, max(n_managers, 1), 1, key="min_holders")


def _compute_scoped_data(
    holdings: pd.DataFrame, period_options: list, selected_period: "pd.Timestamp | None", include_options: bool
) -> tuple:
    """Everything derived from the period/options filters -- shared by
    every data page after it renders its own (shared-key) filter
    controls, so this logic lives in exactly one place.
    """
    older_periods = [p for p in period_options if p < selected_period]
    previous_period = older_periods[0] if older_periods else None

    current_all = _filter_by_period(holdings, selected_period, include_options)
    previous_all = _filter_by_period(holdings, previous_period, include_options)
    consensus_all = consensus_holdings(current_all)
    changes = quarter_changes(previous_all, current_all)

    ticker_universe = pd.concat([current_all, previous_all])[["cusip", "name_of_issuer"]].drop_duplicates()
    ticker_map = _ticker_map(dict(zip(ticker_universe["cusip"], ticker_universe["name_of_issuer"])))

    trend_window_all = holdings[holdings["period_date"].isin(period_options)]
    trend_window = trend_window_all if include_options else trend_window_all[~trend_window_all["is_option"]]

    return current_all, previous_all, consensus_all, changes, ticker_map, trend_window


def _bullet_rows(df: pd.DataFrame, formatter) -> None:
    """Render each row of `df` as one Dataroma-style bullet line (plain
    text, not an interactive table) -- `formatter(row) -> str` builds the
    line. The Home page's simple-list look uses this everywhere instead
    of st.dataframe.
    """
    if df.empty:
        st.caption("데이터가 없습니다.")
        return
    st.markdown("\n".join(f"- {formatter(row)}" for _, row in df.iterrows()))


def _page_home(
    holdings: pd.DataFrame,
    sp500: pd.DataFrame,
    page_superinvestors,
    page_grand_portfolio,
    page_sp500_grid,
    page_realtime_prices,
) -> None:
    st.title("SuperFolio")
    st.caption(
        "선별한 슈퍼인베스터들의 SEC 공시를 교차 비교하는 한국형 컨센서스 스크리너입니다. "
        "컨센서스·보유 분석은 13F(미국 롱 주식·옵션만 포함) 기준이고, 아래 'Portfolio "
        "Updates'는 13F를 포함한 전체 SEC 공시(13D/13G 등)를 다룹니다 — 13F는 각 투자자의 "
        "'전체 포트폴리오'가 아니라 '13F에 신고된 미국 롱 익스포저'만 보여줍니다."
    )

    period_options = _available_periods(holdings)
    selected_period = period_options[0] if period_options else None
    previous_period = period_options[1] if len(period_options) > 1 else None
    previous_2q_period = period_options[2] if len(period_options) > 2 else None

    current_all = _filter_by_period(holdings, selected_period, include_options=False)
    previous_all = _filter_by_period(holdings, previous_period, include_options=False)
    previous_2q_all = _filter_by_period(holdings, previous_2q_period, include_options=False)

    consensus_latest = consensus_holdings(current_all)
    changes_1q = quarter_changes(previous_all, current_all)
    changes_2q = quarter_changes(previous_2q_all, current_all)
    bets = big_bets(current_all, threshold_pct=5.0)
    insider_df = _load_insider_transactions(str(INSIDER_DB_PATH))
    data_latest_date = current_all["period_date"].max() if not current_all.empty else pd.NaT

    kpi1, kpi2 = st.columns(2)
    kpi1.metric(
        "컨센서스 종목 (2인 이상 공통 보유)",
        f"{int((consensus_latest['holder_count'] >= 2).sum())}개",
    )
    kpi2.metric(
        "데이터 최신 기준일",
        data_latest_date.date().isoformat() if pd.notna(data_latest_date) else "N/A",
    )

    with st.expander("데이터 관리"):
        st.caption(f"현재 데이터 최신 기준일: {data_latest_date.date() if pd.notna(data_latest_date) else '알 수 없음'}")
        if st.button("EDGAR에서 최신 데이터 다시 받기 (수 분 소요)"):
            with st.spinner("SEC EDGAR에서 데이터를 다시 가져오는 중..."):
                try:
                    _build_data_inline()
                except Exception as exc:
                    st.error(f"데이터를 가져오는 중 오류가 발생했습니다: {exc}")
                    st.stop()
            st.cache_data.clear()
            st.rerun()
        if st.button("캐시 새로고침"):
            st.cache_data.clear()
            st.rerun()

    st.divider()

    left, right = st.columns(2, gap="large")

    # ── LEFT: Superinvestor Portfolio Updates + Latest Significant Buys ──
    with left:
        st.markdown("##### Superinvestor Portfolio Updates")
        st.caption(
            "추적 투자자들의 최근 SEC 공시입니다 (13F 보유내역뿐 아니라 13D/13G 등 전체 "
            "공시 유형 포함, 투자자당 최근 3건). 하루 2회(공시 마감 임박 시 3시간마다) "
            "자동 갱신되는 스냅샷 기준입니다."
        )
        activity = _load_recent_activity(str(RECENT_ACTIVITY_DB_PATH)).head(15)
        if activity.empty:
            st.caption("아직 데이터를 받아오지 않았습니다 (scripts/build_recent_activity.py 실행 필요).")
        else:
            _bullet_rows(
                activity,
                lambda row: f"**{row['manager_name']}** — {row['form']} 제출 ({row['filing_date'].date()})",
            )
        st.page_link(page_superinvestors, label="Superinvestors 전체 보기 →")

        st.divider()
        st.markdown("##### Latest Significant Insider Buys")
        st.caption(
            "추적 투자자들이 보유한 종목의 SEC Form 4 기준 임원/이사 장내 매수(코드 'P', "
            f"$50,000 이상)입니다. {INSIDER_LOOKBACK_LABEL} 스냅샷 기준 — 실시간 조회가 "
            "아니라 주기적으로 다시 받아와야 최신 상태가 됩니다."
        )
        sig_buys = insider_df[insider_df["value_usd"] >= 50_000].sort_values(
            "filing_date", ascending=False
        ).head(15)
        if insider_df.empty:
            st.caption("아직 Form 4 데이터를 받아오지 않았습니다 (scripts/build_insider.py 실행 필요).")
        else:
            _bullet_rows(
                sig_buys,
                lambda row: (
                    f"**{row['issuer_name']}** — {row['owner_name']} 매수 "
                    f"${row['value_usd']:,.0f} @ ${row['price_per_share']:.2f} "
                    f"({row['filing_date'].date()})"
                ),
            )

    # ── RIGHT: Superinvestor Portfolio Stats ──
    with right:
        st.markdown("##### Superinvestor Portfolio Stats")

        c1, c2 = st.columns(2)
        with c1:
            st.caption("Top 10 Most Owned Stocks")
            _bullet_rows(
                consensus_latest.sort_values("holder_count", ascending=False).head(10),
                lambda row: f"**{row['name_of_issuer']}** — {int(row['holder_count'])}명 보유",
            )
        with c2:
            st.caption("Top 10 Stocks by %")
            _bullet_rows(
                consensus_latest.sort_values("avg_weight_pct", ascending=False).head(10),
                lambda row: f"**{row['name_of_issuer']}** — 평균 비중 {row['avg_weight_pct']:.2f}%",
            )

        st.caption("Top Big Bets — 포트폴리오 5%+ 집중 베팅 (2인 이상 보유)")
        top_bets = bets[bets["holder_count"] >= 2].head(10)
        _bullet_rows(
            top_bets,
            lambda row: (
                f"**{row['name_of_issuer']}** — {row['max_weight_manager']} "
                f"최대 비중 {row['max_weight_pct']:.1f}% (보유자 {int(row['holder_count'])}명)"
            ),
        )

        st.divider()
        qtr_label = pd.Timestamp(selected_period).date().isoformat() if selected_period is not None else "N/A"
        d1, d2 = st.columns(2)
        with d1:
            st.caption(f"Top 10 Buys Last Qtr ({qtr_label} 기준)")
            _bullet_rows(
                top_buys(changes_1q).sort_values("n_new_buyers", ascending=False).head(10),
                lambda row: f"**{row['name_of_issuer']}** — 신규 편입 {int(row['n_new_buyers'])}명",
            )
        with d2:
            st.caption("Top 10 Buys Last Qtr by %")
            _bullet_rows(
                top_buys(changes_1q).sort_values("avg_weight_change_pct", ascending=False).head(10),
                lambda row: f"**{row['name_of_issuer']}** — 평균 비중 증가 {row['avg_weight_change_pct']:.2f}%p",
            )

        e1, e2 = st.columns(2)
        with e1:
            st.caption("Top 10 Buys Last 2 Qtrs")
            _bullet_rows(
                top_buys(changes_2q).sort_values("n_new_buyers", ascending=False).head(10),
                lambda row: f"**{row['name_of_issuer']}** — 신규 편입 {int(row['n_new_buyers'])}명",
            )
        with e2:
            st.caption("Top 10 Buys Last 2 Qtrs by %")
            _bullet_rows(
                top_buys(changes_2q).sort_values("avg_weight_change_pct", ascending=False).head(10),
                lambda row: f"**{row['name_of_issuer']}** — 평균 비중 증가 {row['avg_weight_change_pct']:.2f}%p",
            )

        st.divider()
        st.caption("5%+ Holdings Near 52-Week Low")
        big_holdings = bets.head(30)
        if big_holdings.empty:
            st.caption("대상 종목이 없습니다.")
        else:
            with st.spinner("52주 가격 데이터 조회 중..."):
                near_low = None
                try:
                    bets_tickers = _ticker_map(
                        dict(zip(big_holdings["cusip"], big_holdings["name_of_issuer"]))
                    )
                    resolved = sorted({t for t in bets_tickers.values() if t})
                    week52 = get_52week_range(resolved, MARKET_DB_PATH)
                    curr_prices = get_current_prices(resolved, MARKET_DB_PATH)

                    near_low = big_holdings.copy()
                    near_low["ticker"] = near_low["cusip"].map(bets_tickers)
                    near_low["현재가"] = near_low["ticker"].map(curr_prices)
                    near_low["52주최저"] = near_low["ticker"].map(lambda t: week52.get(t, (None, None))[0])
                    near_low["52주최고"] = near_low["ticker"].map(lambda t: week52.get(t, (None, None))[1])
                    has_prices = near_low[["현재가", "52주최저", "52주최고"]].notna().all(axis=1)
                    near_low = near_low[has_prices].copy()
                    near_low["저점대비%"] = (near_low["현재가"] - near_low["52주최저"]) / near_low["52주최저"] * 100
                    near_low["고점대비%"] = (near_low["52주최고"] - near_low["현재가"]) / near_low["52주최고"] * 100
                    near_low = near_low.sort_values("저점대비%").head(10)
                except Exception as exc:  # third-party API hiccups must not crash the app
                    st.warning(f"가격 조회 중 오류가 발생했습니다: {exc}")
            if near_low is None:
                pass
            else:
                _bullet_rows(
                    near_low,
                    lambda row: (
                        f"**{row['name_of_issuer']}** — 현재가 ${row['현재가']:.2f}, "
                        f"저점 대비 +{row['저점대비%']:.1f}%, 고점 대비 -{row['고점대비%']:.1f}%"
                    ),
                )

        st.divider()
        st.caption(f"Superinvestor Stocks With Most Insider Buys ({INSIDER_LOOKBACK_LABEL})")
        if insider_df.empty:
            st.caption("아직 Form 4 데이터를 받아오지 않았습니다 (scripts/build_insider.py 실행 필요).")
        else:
            insider_summary = insider_buy_summary(insider_df, min_value_usd=50_000).head(10)
            _bullet_rows(
                insider_summary,
                lambda row: f"**{row['issuer_name']}** — {int(row['n_buys'])}건, 합산 ${row['total_value_usd']:,.0f}",
            )

    st.divider()
    link1, link2 = st.columns(2)
    with link1:
        st.page_link(page_sp500_grid, label=f"S&P 500 Grid — 구성종목 {len(sp500)}개 섹터별 스크리닝")
    with link2:
        st.page_link(page_realtime_prices, label="현재가 조회 — 보유 종목 현재가/52주 최고·최저")


def _page_superinvestors(holdings: pd.DataFrame, manager_options: pd.DataFrame) -> None:
    st.title("Superinvestors")

    period_options, selected_period, include_options = _render_period_and_options(holdings)
    current_all, previous_all, _consensus_all, _changes, ticker_map, _trend_window = _compute_scoped_data(
        holdings, period_options, selected_period, include_options
    )

    st.caption(f"추적 중인 투자자 {len(manager_options)}명 중 한 명을 선택해 포트폴리오 상세를 보거나, 두 투자자를 비교합니다.")
    selected_manager = st.selectbox("투자자 선택", manager_options["manager_name"], key="superinvestor_select")
    selected_cik = manager_options.loc[
        manager_options["manager_name"] == selected_manager, "cik"
    ].iloc[0]

    tab_detail, tab_overlap = st.tabs(["포트폴리오 상세", "겹침 분석"])

    with tab_detail:
        st.subheader(f"{selected_manager} — 포트폴리오 상세")
        _render_investor_detail(
            holdings, previous_all, current_all, selected_manager, selected_cik,
            selected_period, period_options, include_options, ticker_map,
        )

    with tab_overlap:
        if previous_all.empty:
            st.info("직전 분기 데이터가 없어 변화(반대 매매) 정보가 비어 있을 수 있습니다.")
        _render_overlap_analysis(previous_all, current_all, ticker_map)


def _page_grand_portfolio(holdings: pd.DataFrame, n_managers: int) -> None:
    st.title("Grand Portfolio")
    st.caption("추적 중인 모든 투자자의 보유 종목을 하나로 합산한 뷰입니다.")

    period_options, selected_period, include_options = _render_period_and_options(holdings)
    weight_mode = _render_weight_mode()
    min_holders = _render_min_holders(n_managers)
    current_all, previous_all, consensus_all, changes, ticker_map, trend_window = _compute_scoped_data(
        holdings, period_options, selected_period, include_options
    )

    tab_consensus, tab_buys, tab_sells, tab_backtest = st.tabs(
        ["컨센서스", "최다 매수", "최다 매도", "백테스트"]
    )

    with tab_consensus:
        result = consensus_all.copy()
        result = result[result["holder_count"] >= min_holders]
        result = _sorted_by_weight_mode(result, weight_mode, "holder_count", "total_value_usd")
        result = _with_ticker_column(result, ticker_map)

        activity = activity_summary(changes)
        result = result.merge(activity, on="cusip", how="left")
        for col in ("n_new_buy", "n_add", "n_trim", "n_sold_out"):
            result[col] = result[col].fillna(0).astype(int)

        styled = (
            result.style.background_gradient(cmap=_sequential_blue_cmap(), subset=["holder_count"])
            .map(_style_activity_count("pos"), subset=["n_new_buy", "n_add"])
            .map(_style_activity_count("neg"), subset=["n_trim", "n_sold_out"])
        )
        st.caption("종목 행을 클릭하면 그 종목을 누가 보유 중인지, 분기별 추이는 어땠는지 아래에 표시됩니다.")
        event = st.dataframe(
            styled,
            hide_index=True,
            width="stretch", row_height=30,
            on_select="rerun",
            selection_mode="single-row",
            key="consensus_table",
            column_config={
                "cusip": st.column_config.TextColumn("CUSIP"),
                "ticker": st.column_config.TextColumn("티커"),
                "name_of_issuer": st.column_config.TextColumn("종목명"),
                "holder_count": st.column_config.NumberColumn("보유자 수", format="%d"),
                "total_value_usd": st.column_config.NumberColumn("합산 금액($)", format="$%,.0f"),
                "avg_weight_pct": st.column_config.NumberColumn("평균 비중(%)", format="%.2f%%"),
                "equal_weight_score": st.column_config.NumberColumn(
                    "동일가중 점수(%)", format="%.1f%%"
                ),
                "value_weight_score": st.column_config.NumberColumn(
                    "금액가중 점수(%)", format="%.1f%%"
                ),
                "n_new_buy": st.column_config.NumberColumn("신규", format="%d", help="이번 분기 신규 편입"),
                "n_add": st.column_config.NumberColumn("추가", format="%d", help="이번 분기 비중 확대"),
                "n_trim": st.column_config.NumberColumn("축소", format="%d", help="이번 분기 비중 축소"),
                "n_sold_out": st.column_config.NumberColumn("매도", format="%d", help="이번 분기 완전 매도"),
            },
        )
        st.caption(f"{len(result)}개 종목 (최소 보유자 수 {min_holders}명 이상) — 신규/추가/축소/매도는 이번 분기 활동 투자자 수")

        selected_rows = event["selection"]["rows"] if event and event.get("selection") else []
        if selected_rows:
            sel = result.iloc[selected_rows[0]]
            _render_stock_drilldown(
                sel["cusip"], sel["name_of_issuer"], sel.get("ticker", ""),
                current_all, previous_all, changes, trend_window,
            )

    with tab_buys:
        if previous_all.empty:
            st.info("직전 분기 데이터가 없어 변화를 계산할 수 없습니다.")
        else:
            result = top_buys(changes)
            result = result[result["n_new_buyers"] >= min_holders]
            result = _sorted_by_weight_mode(
                result, weight_mode, "n_new_buyers", "total_value_added_usd"
            )
            result = _with_ticker_column(result, ticker_map)
            styled = result.style.background_gradient(
                cmap=_sequential_blue_cmap(), subset=["n_new_buyers"]
            ).map(_style_signed, subset=["avg_weight_change_pct"])
            st.dataframe(
                styled,
                hide_index=True,
                width="stretch", row_height=30,
                column_config={
                    "cusip": st.column_config.TextColumn("CUSIP"),
                    "ticker": st.column_config.TextColumn("티커"),
                    "name_of_issuer": st.column_config.TextColumn("종목명"),
                    "n_new_buyers": st.column_config.NumberColumn("신규 편입 투자자 수", format="%d"),
                    "total_value_added_usd": st.column_config.NumberColumn(
                        "합산 증가액($)", format="$%,.0f"
                    ),
                    "avg_weight_change_pct": st.column_config.NumberColumn(
                        "평균 비중 변화(%p)", format="%.2f%%"
                    ),
                },
            )
            st.caption(f"{len(result)}개 종목 (최소 {min_holders}명 이상 신규 편입/비중 확대)")

    with tab_sells:
        if previous_all.empty:
            st.info("직전 분기 데이터가 없어 변화를 계산할 수 없습니다.")
        else:
            result = top_sells(changes)
            result = result[result["n_sold_out"] >= min_holders]
            result = _sorted_by_weight_mode(
                result, weight_mode, "n_sold_out", "total_value_reduced_usd"
            )
            result = _with_ticker_column(result, ticker_map)
            styled = result.style.map(lambda _: f"color: {NEG_COLOR}; font-weight: 600", subset=["n_sold_out"])
            st.dataframe(
                styled,
                hide_index=True,
                width="stretch", row_height=30,
                column_config={
                    "cusip": st.column_config.TextColumn("CUSIP"),
                    "ticker": st.column_config.TextColumn("티커"),
                    "name_of_issuer": st.column_config.TextColumn("종목명"),
                    "n_sold_out": st.column_config.NumberColumn("완전 매도 투자자 수", format="%d"),
                    "total_value_reduced_usd": st.column_config.NumberColumn(
                        "합산 감소액($)", format="$%,.0f"
                    ),
                },
            )
            st.caption(f"{len(result)}개 종목 (최소 {min_holders}명 이상 완전 매도/비중 축소)")

    with tab_backtest:
        _render_backtest_tab(holdings, n_managers)


def _page_sp500_grid(holdings: pd.DataFrame, sp500: pd.DataFrame) -> None:
    st.title("S&P 500 Grid")
    st.caption(
        "추적 중인 투자자들이 보유한 S&P 500 구성종목만 모아, 보유자 수·평균 비중·섹터로 "
        "스크리닝합니다. 섹터는 S&P 500 공식 GICS 섹터 분류를 그대로 씁니다."
    )

    period_options, selected_period, include_options = _render_period_and_options(holdings)
    n_managers = holdings.loc[holdings["period_rank"] == 0, "cik"].nunique()
    min_holders = _render_min_holders(n_managers)
    current_all, previous_all, _consensus_all, changes, ticker_map, trend_window = _compute_scoped_data(
        holdings, period_options, selected_period, include_options
    )

    if sp500.empty:
        st.warning("S&P 500 구성종목 데이터를 불러오지 못했습니다.")
        return

    grid = sp500_ownership_summary(current_all, sp500, ticker_map)
    if grid.empty:
        st.info("현재 필터 기준으로 추적 투자자가 보유한 S&P 500 종목이 없습니다.")
        return

    sectors = sorted(grid["sector"].dropna().unique())
    selected_sectors = st.multiselect("섹터 필터", sectors, default=sectors)
    filtered = grid[grid["sector"].isin(selected_sectors)]
    filtered = filtered[filtered["holder_count"] >= min_holders]

    if filtered.empty:
        st.info("이 필터 조건에 맞는 종목이 없습니다.")
        return

    styled = filtered.style.background_gradient(cmap=_sequential_blue_cmap(), subset=["holder_count"])
    st.caption("종목 행을 클릭하면 아래에 상세 정보가 표시됩니다.")
    event = st.dataframe(
        styled,
        hide_index=True,
        width="stretch", row_height=30,
        on_select="rerun",
        selection_mode="single-row",
        key="sp500_grid_table",
        column_config={
            "ticker": st.column_config.TextColumn("티커"),
            "name": st.column_config.TextColumn("종목명"),
            "sector": st.column_config.TextColumn("섹터"),
            "cusip": st.column_config.TextColumn("CUSIP"),
            "holder_count": st.column_config.NumberColumn("보유자 수", format="%d"),
            "avg_weight_pct": st.column_config.NumberColumn("평균 비중(%)", format="%.2f%%"),
            "total_value_usd": st.column_config.NumberColumn("합산 금액($)", format="$%,.0f"),
        },
    )
    st.caption(f"{len(filtered)}개 종목 (S&P 500 {len(sp500)}개 구성종목 중 추적 투자자 보유분)")

    selected_rows = event["selection"]["rows"] if event and event.get("selection") else []
    if selected_rows:
        sel = filtered.iloc[selected_rows[0]]
        _render_stock_drilldown(
            sel["cusip"], sel["name"], sel["ticker"],
            current_all, previous_all, changes, trend_window,
        )


def _page_realtime_prices(holdings: pd.DataFrame) -> None:
    st.title("현재가 조회")
    st.caption(
        "추적 중인 투자자들이 보유한 종목의 현재가·52주 최고/최저를 조회합니다. "
        "13F 자체는 분기 단위+최대 45일 지연 공시라 실시간이 아니지만, 여기서는 "
        "가격 데이터만 최신에 가깝게 조회합니다."
    )

    period_options, selected_period, include_options = _render_period_and_options(holdings)
    n_managers = holdings.loc[holdings["period_rank"] == 0, "cik"].nunique()
    min_holders = _render_min_holders(n_managers)
    current_all, _previous_all, consensus_all, _changes, ticker_map, _trend_window = _compute_scoped_data(
        holdings, period_options, selected_period, include_options
    )

    universe = consensus_all[consensus_all["holder_count"] >= min_holders][
        ["cusip", "name_of_issuer", "holder_count"]
    ].copy()
    universe["ticker"] = universe["cusip"].map(ticker_map)
    universe = universe[universe["ticker"].notna() & (universe["ticker"] != "")]

    search = st.text_input("종목명 또는 티커 검색 (비워두면 전체)")
    if search:
        mask = (
            universe["name_of_issuer"].str.contains(search, case=False, na=False)
            | universe["ticker"].str.contains(search, case=False, na=False)
        )
        universe = universe[mask]

    if universe.empty:
        st.info("검색 결과가 없습니다.")
        return

    st.caption(f"조회 대상 {len(universe)}개 종목 (최소 보유자 수 {min_holders}명 이상 필터 반영)")
    if not st.button("현재가 조회", type="primary"):
        st.info("버튼을 누르면 조회를 시작합니다 (종목 수에 따라 시간이 걸릴 수 있습니다).")
        return

    tickers = sorted(universe["ticker"].unique())
    with st.spinner(f"{len(tickers)}개 티커 현재가/52주 데이터 조회 중..."):
        try:
            prices = get_current_prices(tickers, MARKET_DB_PATH)
            week52 = get_52week_range(tickers, MARKET_DB_PATH)
        except Exception as exc:  # third-party API hiccups must not crash the app
            st.error(f"가격 조회 중 오류가 발생했습니다: {exc}")
            return

    universe["현재가($)"] = universe["ticker"].map(prices)
    universe["52주 최저($)"] = universe["ticker"].map(lambda t: week52.get(t, (None, None))[0])
    universe["52주 최고($)"] = universe["ticker"].map(lambda t: week52.get(t, (None, None))[1])
    universe = universe.sort_values("holder_count", ascending=False).drop(columns=["holder_count"])

    st.dataframe(
        universe,
        hide_index=True,
        width="stretch", row_height=30,
        column_config={
            "cusip": st.column_config.TextColumn("CUSIP"),
            "ticker": st.column_config.TextColumn("티커"),
            "name_of_issuer": st.column_config.TextColumn("종목명"),
            "현재가($)": st.column_config.NumberColumn(format="$%.2f"),
            "52주 최저($)": st.column_config.NumberColumn(format="$%.2f"),
            "52주 최고($)": st.column_config.NumberColumn(format="$%.2f"),
        },
    )


def main() -> None:
    if not DB_PATH.exists():
        st.title("SuperFolio")
        n_investors = len(load_investors())
        st.warning(
            f"아직 데이터가 없습니다. SEC EDGAR에서 {n_investors}명의 투자자의 최근 "
            f"{QUARTERS_TO_FETCH}개 분기(최대 약 5년치) 13F 공시를 직접 받아와야 합니다 "
            "(수십 분 이상 걸릴 수 있습니다 — 투자자 수와 분기 수가 많아 SEC 요청 제한 "
            "속도로 순차 처리됩니다)."
        )
        if st.button("지금 EDGAR에서 데이터 가져오기", type="primary"):
            with st.spinner(f"SEC EDGAR에서 {n_investors}명의 데이터를 가져오는 중... 페이지를 닫지 마세요"):
                try:
                    _build_data_inline()
                except Exception as exc:
                    st.error(f"데이터를 가져오는 중 오류가 발생했습니다: {exc}")
                    return
            st.cache_data.clear()
            st.rerun()
        return

    holdings = _load_holdings(str(DB_PATH))
    sp500 = _load_sp500(str(SP500_CSV_PATH))
    n_managers = holdings.loc[holdings["period_rank"] == 0, "cik"].nunique()

    manager_options = (
        holdings.loc[holdings["period_rank"] == 0, ["cik", "manager_name"]]
        .drop_duplicates()
        .sort_values("manager_name")
    )

    page_superinvestors = st.Page(
        lambda: _page_superinvestors(holdings, manager_options),
        title="Superinvestors", icon=":material/groups:", url_path="superinvestors",
    )
    page_grand_portfolio = st.Page(
        lambda: _page_grand_portfolio(holdings, n_managers),
        title="Grand Portfolio", icon=":material/account_balance:", url_path="grand-portfolio",
    )
    page_sp500_grid = st.Page(
        lambda: _page_sp500_grid(holdings, sp500),
        title="S&P 500 Grid", icon=":material/grid_view:", url_path="sp500-grid",
    )
    page_realtime_prices = st.Page(
        lambda: _page_realtime_prices(holdings),
        title="현재가 조회", icon=":material/monitoring:", url_path="realtime-prices",
    )
    page_home = st.Page(
        lambda: _page_home(
            holdings, sp500,
            page_superinvestors, page_grand_portfolio, page_sp500_grid, page_realtime_prices,
        ),
        title="Home", icon=":material/home:", url_path="home", default=True,
    )

    pages = st.navigation(
        [page_home, page_superinvestors, page_grand_portfolio, page_sp500_grid, page_realtime_prices],
        position="top",
    )
    pages.run()


if __name__ == "__main__":
    main()
