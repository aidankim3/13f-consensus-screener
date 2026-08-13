"""13F 컨센서스 스크리너 — Streamlit UI.

Only this module (and others under src/app/) may import streamlit.
All data loading/aggregation logic lives in src/edgar and src/analytics
and is called here, not reimplemented.

Run: streamlit run src/app/main.py
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from src.analytics.backtest import consensus_asof_schedule, simulate_portfolio
from src.analytics.consensus import consensus_holdings, quarter_changes, top_buys, top_sells
from src.analytics.entry_price import with_entry_price_comparison
from src.analytics.investor import investor_portfolio, portfolio_summary
from src.analytics.overlap import jaccard_similarity, pairwise_overlap, similarity_matrix
from src.edgar.build import CACHE_DIR, QUARTERS_TO_FETCH, build_all, load_investors
from src.edgar.client import EdgarClient
from src.edgar.storage import load_holdings_table, save_holdings_table
from src.market.prices import get_current_prices, get_price_history, get_quarterly_avg_prices
from src.market.ticker_map import resolve_tickers

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "holdings.db"
MARKET_DB_PATH = ROOT / "data" / "market.db"
USER_AGENT = "Aidan Kim aidankim3@gmail.com"

st.set_page_config(page_title="13F 컨센서스 스크리너", layout="wide")


@st.cache_data(ttl=300)
def _load_holdings(db_path: str) -> pd.DataFrame:
    df = load_holdings_table(Path(db_path))
    df["is_option"] = df["is_option"].astype(bool)
    df["period_date"] = pd.to_datetime(df["period_date"])
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


def _filter_holdings(df: pd.DataFrame, period_rank: int, include_options: bool) -> pd.DataFrame:
    scoped = df[df["period_rank"] == period_rank]
    if not include_options:
        scoped = scoped[~scoped["is_option"]]
    return scoped


def _render_freshness(current: pd.DataFrame) -> None:
    if current.empty:
        return
    latest_date = current["period_date"].max().date()
    days_old = (date.today() - latest_date).days
    st.caption(f"가장 최신 기준일: **{latest_date}** ({days_old}일 지남)")

    per_manager = (
        current[["manager_name", "period_date"]]
        .drop_duplicates()
        .assign(
            일수_지남=lambda d: (pd.Timestamp(date.today()) - d["period_date"]).dt.days,
            기준일=lambda d: d["period_date"].dt.date,
        )
        .drop(columns=["period_date"])
        .rename(columns={"manager_name": "투자자"})
        .sort_values("일수_지남")
    )
    with st.expander("투자자별 기준일 (제출 시점이 서로 다를 수 있음)"):
        st.dataframe(per_manager, hide_index=True, width="stretch")


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


def _fetch_entry_price_table(held_now: pd.DataFrame, current_period_date: str) -> pd.DataFrame:
    """Resolve tickers + fetch quarterly-avg/current prices for the given
    holdings, then attach the comparison. Network calls (CUSIP->ticker,
    yfinance) are disk-cached in MARKET_DB_PATH, so repeat calls for the
    same cusip/period are cheap after the first fetch.
    """
    cusips_with_names = dict(zip(held_now["cusip"], held_now["name_of_issuer"]))
    tickers = resolve_tickers(cusips_with_names, MARKET_DB_PATH, USER_AGENT)

    resolved_tickers = [t for t in tickers.values() if t]
    entry_prices = get_quarterly_avg_prices(
        [(t, current_period_date) for t in resolved_tickers], MARKET_DB_PATH
    )
    current_prices = get_current_prices(resolved_tickers, MARKET_DB_PATH)

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
    return with_entry_price_comparison(held_now, prices)


def _render_investor_detail(
    holdings: pd.DataFrame,
    previous_all: pd.DataFrame,
    current_all: pd.DataFrame,
    manager_name: str,
    cik: str,
) -> None:
    prev_mgr = previous_all[previous_all["cik"] == cik]
    curr_mgr = current_all[current_all["cik"] == cik]
    # Option weight must reflect the manager's TRUE mix regardless of the
    # global "옵션 포함" toggle, so this reads from unfiltered `holdings`.
    raw_curr_mgr = holdings[(holdings["period_rank"] == 0) & (holdings["cik"] == cik)]

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
        chart_data = (
            held_now.nlargest(15, "curr_weight_pct")
            .set_index("name_of_issuer")["curr_weight_pct"]
            .rename("비중(%)")
        )
        st.bar_chart(chart_data)

    display_df = portfolio[
        ["cusip", "name_of_issuer", "curr_weight_pct", "curr_value_usd", "curr_shares",
         "change_type", "weight_delta_pct"]
    ].copy()
    display_df["change_type"] = display_df["change_type"].map(_CHANGE_TYPE_LABELS)

    st.dataframe(
        display_df,
        hide_index=True,
        width="stretch",
        column_config={
            "cusip": st.column_config.TextColumn("CUSIP"),
            "name_of_issuer": st.column_config.TextColumn("종목명"),
            "curr_weight_pct": st.column_config.NumberColumn("비중(%)", format="%.2f%%"),
            "curr_value_usd": st.column_config.NumberColumn("금액($)", format="$%,.0f"),
            "curr_shares": st.column_config.NumberColumn("주식수", format="%,d"),
            "change_type": st.column_config.TextColumn("변화"),
            "weight_delta_pct": st.column_config.NumberColumn("변화(%p)", format="%.2f%%"),
        },
    )
    st.caption(f"{len(held_now)}개 종목 보유 중 (직전 분기 대비 변화 포함 전체 {len(portfolio)}행)")

    st.divider()
    st.markdown("##### 추정 진입가 vs 현재가")
    st.caption(
        "진입가는 실제 매입가가 아니라 **보유 중인 분기의 평균 주가 근사치**입니다 "
        "(그 분기 첫 거래일 시가와 마지막 거래일 종가의 평균 — 13F는 체결일·체결가를 "
        "공시하지 않으므로 근사치일 수밖에 없습니다). CUSIP→티커 매핑과 가격 조회는 "
        "외부 서비스(OpenFIGI, SEC, Yahoo Finance)를 이용하며 일부 종목은 실패할 수 있습니다."
    )
    if held_now.empty:
        st.info("비교할 보유 종목이 없습니다.")
    elif st.checkbox("현재가 vs 추정 진입가 불러오기 (외부 가격 조회)", key=f"entry_price_{cik}"):
        current_period_date = curr_mgr["period_date"].iloc[0].strftime("%Y-%m-%d")
        with st.spinner("가격 조회 중..."):
            try:
                price_df = _fetch_entry_price_table(held_now, current_period_date)
            except Exception as exc:  # third-party API hiccups must not crash the app
                st.warning(f"가격 조회 중 오류가 발생했습니다: {exc}")
                price_df = None
        if price_df is not None:
            price_df = price_df.copy()
            price_df["change_type"] = price_df["change_type"].map(_CHANGE_TYPE_LABELS)
            n_priced = int(price_df["price_diff_pct"].notna().sum())
            st.dataframe(
                price_df,
                hide_index=True,
                width="stretch",
                column_config={
                    "cusip": st.column_config.TextColumn("CUSIP"),
                    "name_of_issuer": st.column_config.TextColumn("종목명"),
                    "ticker": st.column_config.TextColumn("티커"),
                    "change_type": st.column_config.TextColumn("변화"),
                    "curr_shares": st.column_config.NumberColumn("주식수", format="%,d"),
                    "curr_value_usd": st.column_config.NumberColumn("금액($)", format="$%,.0f"),
                    "curr_weight_pct": st.column_config.NumberColumn("비중(%)", format="%.2f%%"),
                    "entry_price": st.column_config.NumberColumn("추정 진입가($)", format="$%.2f"),
                    "current_price": st.column_config.NumberColumn("현재가($)", format="$%.2f"),
                    "price_diff_pct": st.column_config.NumberColumn("가격 차이(%)", format="%.1f%%"),
                },
            )
            st.caption(
                f"{n_priced}/{len(price_df)}개 종목 가격 조회 성공 "
                "(나머지는 티커 매핑 또는 가격 조회 실패 — '가격 차이' 빈 칸)"
            )


def _render_overlap_analysis(previous_all: pd.DataFrame, current_all: pd.DataFrame) -> None:
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

    display_cols = ["cusip", "name_of_issuer", "a_change_type", "b_change_type", "a_shares", "b_shares"]
    column_config = {
        "cusip": st.column_config.TextColumn("CUSIP"),
        "name_of_issuer": st.column_config.TextColumn("종목명"),
        "a_change_type": st.column_config.TextColumn(f"{manager_a} 변화"),
        "b_change_type": st.column_config.TextColumn(f"{manager_b} 변화"),
        "a_shares": st.column_config.NumberColumn(f"{manager_a} 주식수", format="%,d"),
        "b_shares": st.column_config.NumberColumn(f"{manager_b} 주식수", format="%,d"),
    }

    common = overlap[overlap["relationship"] == "common"]
    only_a = overlap[overlap["relationship"] == "only_a"]
    only_b = overlap[overlap["relationship"] == "only_b"]
    opposite = overlap[overlap["opposite_trade"]]

    st.markdown(f"###### 공통 보유 종목 ({len(common)}개)")
    st.dataframe(common[display_cols], hide_index=True, width="stretch", column_config=column_config)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"###### {manager_a}만 보유 ({len(only_a)}개)")
        st.dataframe(only_a[display_cols], hide_index=True, width="stretch", column_config=column_config)
    with col2:
        st.markdown(f"###### {manager_b}만 보유 ({len(only_b)}개)")
        st.dataframe(only_b[display_cols], hide_index=True, width="stretch", column_config=column_config)

    st.markdown(f"###### 반대 매매 종목 ({len(opposite)}개) — 이번 분기 한쪽은 매수, 한쪽은 매도")
    st.dataframe(opposite[display_cols], hide_index=True, width="stretch", column_config=column_config)

    st.divider()
    st.markdown("##### 전체 투자자 쌍 포트폴리오 유사도 히트맵 (자카드 지수, %)")
    st.caption("현재 보유 종목(옵션 포함 설정 반영) 집합의 자카드 유사도입니다. 대각선은 항상 100%.")
    matrix = similarity_matrix(current_all)
    styled = matrix.style.format("{:.0f}%").background_gradient(cmap="Blues", vmin=0, vmax=100)
    st.dataframe(styled, width="stretch")


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
        {c: name_by_cusip.get(c, c) for c in all_cusips}, MARKET_DB_PATH, USER_AGENT
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


def _render_backtest_tab(all_holdings: pd.DataFrame) -> None:
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
    m1.metric("전략 누적 수익률", f"{strategy_return * 100:.1f}%")
    m2.metric(f"{BENCHMARK_TICKER} 누적 수익률", f"{benchmark_return * 100:.1f}%")
    m3.metric("초과 수익률", f"{(strategy_return - benchmark_return) * 100:.1f}%p")

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
        width="stretch",
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
        "- **생존편향**: 추적 대상 6명은 현재 시점 기준으로 유명한 투자자를 선정한 목록입니다. "
        "과거 시점에 실제로 이 명단을 구성했을 수 있는지, 그때도 이들이 '컨센서스 상위'였는지는 "
        "반영되지 않습니다.\n"
        "- **롱 주식만 반영**: 13F는 미국 롱 주식(및 옵션)만 공시합니다. 숏 포지션, 헤지, "
        "채권·해외자산·현금 등 실제 포트폴리오의 다른 부분은 전혀 반영되지 않습니다.\n"
        "- **근사 가격**: 진입가는 컨센서스가 공개된 날짜(또는 그 이후 첫 거래일)의 종가를 "
        "쓰며, 실제 어느 투자자도 정확히 그 가격에 사고팔지 않았을 것입니다.\n"
        "- **작은 표본(6명)**: 소수 투자자의 컨센서스라 특정 한 명의 쏠린 베팅에 결과가 "
        "쉽게 좌우됩니다 — '스마트 머니 전체의 신호'로 일반화할 수 없습니다.\n"
        "- **거래비용은 가정치**: 리밸런싱 거래비용은 위에서 입력한 고정 bps일 뿐, 실제 "
        "슬리피지·스프레드·시장충격을 반영하지 않습니다."
    )


def main() -> None:
    st.title("13F 컨센서스 스크리너")
    st.caption(
        "선별한 투자자들의 SEC 13F 공시를 교차 비교합니다. "
        "13F는 미국 롱 주식(및 옵션)만 포함하며, 숏 포지션·채권·해외 주식·현금은 "
        "여기 나타나지 않습니다 — 이건 각 투자자의 '전체 포트폴리오'가 아니라 "
        "'13F에 신고된 미국 롱 익스포저'입니다."
    )

    if not DB_PATH.exists():
        st.warning(
            "아직 데이터가 없습니다. SEC EDGAR에서 6명의 투자자의 최근 8개 분기 "
            "13F 공시를 직접 받아와야 합니다 (1~2분 정도 걸립니다)."
        )
        if st.button("지금 EDGAR에서 데이터 가져오기", type="primary"):
            with st.spinner("SEC EDGAR에서 데이터를 가져오는 중... (1~2분 소요)"):
                try:
                    _build_data_inline()
                except Exception as exc:
                    st.error(f"데이터를 가져오는 중 오류가 발생했습니다: {exc}")
                    return
            st.cache_data.clear()
            st.rerun()
        return

    holdings = _load_holdings(str(DB_PATH))

    manager_options = (
        holdings.loc[holdings["period_rank"] == 0, ["cik", "manager_name"]]
        .drop_duplicates()
        .sort_values("manager_name")
    )
    selected_manager = st.sidebar.selectbox("투자자 선택 (상세 탭용)", manager_options["manager_name"])
    selected_cik = manager_options.loc[
        manager_options["manager_name"] == selected_manager, "cik"
    ].iloc[0]

    with st.sidebar.expander("데이터 관리"):
        latest = holdings.loc[holdings["period_rank"] == 0, "period_date"].max()
        st.caption(f"현재 데이터 최신 기준일: {latest.date() if pd.notna(latest) else '알 수 없음'}")
        if st.button("EDGAR에서 최신 데이터 다시 받기 (1~2분 소요)"):
            with st.spinner("SEC EDGAR에서 데이터를 다시 가져오는 중..."):
                try:
                    _build_data_inline()
                except Exception as exc:
                    st.error(f"데이터를 가져오는 중 오류가 발생했습니다: {exc}")
                    st.stop()
            st.cache_data.clear()
            st.rerun()

    top_col1, top_col2, top_col3, top_col4 = st.columns([2, 1.4, 1.6, 0.8])
    with top_col1:
        include_options = st.toggle("옵션(PUT/CALL) 포함", value=False)
    with top_col2:
        weight_mode_label = st.radio(
            "정렬 기준", ["동일가중(보유자 수)", "금액가중($)"], horizontal=True
        )
        weight_mode = "equal" if weight_mode_label.startswith("동일") else "value"
    with top_col3:
        n_managers = holdings.loc[holdings["period_rank"] == 0, "cik"].nunique()
        min_holders = st.slider("최소 보유자/매수자/매도자 수", 1, max(n_managers, 1), 1)
    with top_col4:
        if st.button("새로고침"):
            st.cache_data.clear()
            st.rerun()

    current_all = _filter_holdings(holdings, period_rank=0, include_options=include_options)
    previous_all = _filter_holdings(holdings, period_rank=1, include_options=include_options)

    _render_freshness(current_all)

    tab_consensus, tab_buys, tab_sells, tab_detail, tab_overlap, tab_backtest = st.tabs(
        ["컨센서스", "최다 매수", "최다 매도", "투자자 상세", "겹침 분석", "백테스트"]
    )

    with tab_consensus:
        result = consensus_holdings(current_all)
        result = result[result["holder_count"] >= min_holders]
        result = _sorted_by_weight_mode(result, weight_mode, "holder_count", "total_value_usd")
        st.dataframe(
            result,
            hide_index=True,
            width="stretch",
            column_config={
                "cusip": st.column_config.TextColumn("CUSIP"),
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
            },
        )
        st.caption(f"{len(result)}개 종목 (최소 보유자 수 {min_holders}명 이상)")

    changes = quarter_changes(previous_all, current_all)

    with tab_buys:
        if previous_all.empty:
            st.info("직전 분기 데이터가 없어 변화를 계산할 수 없습니다.")
        else:
            result = top_buys(changes)
            result = result[result["n_new_buyers"] >= min_holders]
            result = _sorted_by_weight_mode(
                result, weight_mode, "n_new_buyers", "total_value_added_usd"
            )
            st.dataframe(
                result,
                hide_index=True,
                width="stretch",
                column_config={
                    "cusip": st.column_config.TextColumn("CUSIP"),
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
            st.dataframe(
                result,
                hide_index=True,
                width="stretch",
                column_config={
                    "cusip": st.column_config.TextColumn("CUSIP"),
                    "name_of_issuer": st.column_config.TextColumn("종목명"),
                    "n_sold_out": st.column_config.NumberColumn("완전 매도 투자자 수", format="%d"),
                    "total_value_reduced_usd": st.column_config.NumberColumn(
                        "합산 감소액($)", format="$%,.0f"
                    ),
                },
            )
            st.caption(f"{len(result)}개 종목 (최소 {min_holders}명 이상 완전 매도/비중 축소)")

    with tab_detail:
        st.subheader(f"{selected_manager} — 포트폴리오 상세")
        _render_investor_detail(holdings, previous_all, current_all, selected_manager, selected_cik)

    with tab_overlap:
        if previous_all.empty:
            st.info("직전 분기 데이터가 없어 변화(반대 매매) 정보가 비어 있을 수 있습니다.")
        _render_overlap_analysis(previous_all, current_all)

    with tab_backtest:
        _render_backtest_tab(holdings)


if __name__ == "__main__":
    main()
