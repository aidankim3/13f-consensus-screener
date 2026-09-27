# region imports
from AlgorithmImports import *
# endregion
# 1세대 프로그램 매매 모델 — 4단계: 3단계(유니버스·팩터·구성·매매) + 거래비용(plan_v4.3.md 9장: 수수료 + 반스프레드,
# 저·기본·고 시나리오)과 전역 점수 옵션(10장 시험 집합). 파일 구성·출력·확인 항목은 NOTES.md 참고.
from datetime import datetime, timedelta

from config import *
from costs import CostModel, CostSecurityInitializer, SpreadFeeModel
from coverage import CoverageCheck
from diagnostics import FieldCollector, Recorder
from factors import FundamentalHistory, adjusted_daily_closes, compute_factors, history_window, record_snapshots
from portfolio import Plan, build_orders, read_parameters, select_holdings, sigma_hat, target_weights
from report import PortfolioReport
from universe import (ExchangeCalendar, MonthScreen, buffer_members, choose_representatives, classify_exits,
                      count_pit, scan_securities, screen_stocks)


class ProgramTradingPortfolioStep4(QCAlgorithm):
    """4단계: 월말 신호로 유니버스·팩터 z를 만들고, 다음 거래일 MOC로 목표 보유 종목을 매매한다. 체결마다 비용 모형 적용."""

    def initialize(self):
        # 계획서 10장·CLAUDE.md 원칙 1: 개발 구간 밖 날짜는 실행 자체를 막는다(QUICK_TEST 구간도 같은 검사)
        if (min(START_DATE, BACKTEST_START_DATE) < DEV_PERIOD_FIRST_DAY
                or max(END_DATE, BACKTEST_END_DATE) > DEV_PERIOD_LAST_DAY or BACKTEST_START_DATE > BACKTEST_END_DATE):
            raise ValueError(f"개발 구간 밖 날짜: {BACKTEST_START_DATE}~{BACKTEST_END_DATE} "
                             f"(허용 {DEV_PERIOD_FIRST_DAY}~{DEV_PERIOD_LAST_DAY})")

        self.set_start_date(BACKTEST_START_DATE.year, BACKTEST_START_DATE.month, BACKTEST_START_DATE.day)
        self.set_end_date(BACKTEST_END_DATE.year, BACKTEST_END_DATE.month, BACKTEST_END_DATE.day)
        self.set_cash(INITIAL_CASH)
        # 사용자 결정: N·가중·점수(섹터 내/전역)·비용 시나리오는 QC 프로젝트 파라미터
        self._n_holdings, self._weighting, self._score_mode, cost_scenario = read_parameters(self)
        self._cost = CostModel(self, cost_scenario, lambda key, message: self._recorder.warn_once(key, message))

        # 계획서 9장·15장: IB 브로커 모형, margin 계좌. 목표 비중 합 ≤ 99%로 레버리지는 쓰지 않음
        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN)
        # 새로 구독한 매수 예정 종목도 첫 일봉 전에 마지막 가격을 갖게 한다(가격 0 주문 거절 방지) — NOTES.md [L].
        # 4단계: 수수료 모형 = (LEAN IB 수수료 + 반스프레드) × 시나리오 배수(costs.SpreadFeeModel, 계획서 9장)
        self.set_security_initializer(CostSecurityInitializer(
            self.brokerage_model, FuncSecuritySeeder(self.get_last_known_prices), SpreadFeeModel(self._cost)))

        # 신호일 T와 '공시 다음 거래일' 계산에 쓸 거래소 달력. SPY는 벤치마크(차트용)이고 매매하지 않음
        calendar_symbol = self.add_equity(CALENDAR_TICKER, Resolution.DAILY).symbol
        self.set_benchmark(calendar_symbol)
        self._calendar_symbol = calendar_symbol
        self._recorder = Recorder(self)
        self._report = PortfolioReport(self, self._recorder)     # 3단계 로그([REBAL]·[FILL]·[PYEAR]·[PERF])
        self._coverage = CoverageCheck(self, self._recorder)     # COVERAGE_CHECK 모드 진단([COV])
        self._calendar = ExchangeCalendar(self.securities[calendar_symbol].exchange.hours, self._recorder.warn_once)

        # 계획서 6장: 월 1회 유니버스. 선택 함수는 매일 불리지만 데이터 날짜가 월말 마지막 거래일일 때만 재구성한다.
        # 매매 종목은 원주가(RAW)로 구독: 수량 계산(신호일 원주가)과 체결가를 같은 기준으로 두고 배당은 현금으로 받음
        self.universe_settings.resolution = Resolution.DAILY
        self.universe_settings.data_normalization_mode = DataNormalizationMode.RAW
        self.universe_settings.leverage = BUYING_POWER_LEVERAGE
        self.add_universe(self._select_universe)
        # 계획서 9장: 체결일 개장 뒤 MOC 주문 제출. 매 거래일 전날 체결 결과(현금 음수 등)도 여기서 점검
        self.schedule.on(self.date_rules.every_day(calendar_symbol),
                         self.time_rules.after_market_open(calendar_symbol, ORDER_MINUTES_AFTER_OPEN), self._on_open)

        # 계획서 8장: 티커가 아닌 영구 식별자(Symbol)로 추적
        self._members = set()
        self._last_signal_date = None
        self._empty_calls = 0
        self._start_deferred = False

        # 계획서 6장 재무 시점: Symbol별 재무 스냅샷과 최근 달의 팩터 점수 z
        self._fund_history = FundamentalHistory()
        self._factor_z = {}

        # 3단계: 보유 종목(체결로 갱신)과 다음 거래일에 낼 주문 계획
        self._held = set()
        self._pending = None

        self._recorder.log_config()
        if COVERAGE_CHECK:
            self._coverage.log_config()
        else:
            self._report.log_config(self._n_holdings, self._weighting, self._score_mode, self._cost)

    def _select_universe(self, fundamental):
        """매 호출에서 데이터 날짜(self.time 기준 직전 거래일)를 구하고, 그날이 그 달 마지막 거래일일 때만
        그날을 신호일 T로 삼아 유니버스·팩터·리밸런싱 계획을 만든다. 같은 신호일로는 두 번 하지 않는다. NOTES.md [F].
        계획서 9장: 신호는 월말 마지막 거래일 종가, 체결은 다음 거래일 종가(MOC).
        계획서 8장: 선택 함수는 그날 존재하던 종목만 받으므로 뒤에 상장폐지된 종목도 당시에는 포함된다.
        반환(LEAN 구독)은 '현재 보유 + 이번 매수 예정'뿐이고 유니버스·z 대상은 코드 안의 집합으로 관리한다."""
        data_date = self._calendar.previous_day(self.time)
        next_trading_day = self._calendar.next_day(data_date)
        month_end = (next_trading_day.year, next_trading_day.month) != (data_date.year, data_date.month)
        if not month_end or data_date == self._last_signal_date:
            return Universe.UNCHANGED
        previous_signal_date, self._last_signal_date = self._last_signal_date, data_date

        signal_date = data_date
        if COVERAGE_CHECK:                                       # 점검 모드: 점검일에만 1단계 선별과 [COV], 팩터·주문 없음
            return self._coverage.run(fundamental, signal_date)
        first_run = not self._recorder.monthly_rows
        prev = self._members
        screen = MonthScreen(prev)
        collector = FieldCollector() if first_run else None

        # 1차: 증권 단위 조건(계획서 6장)
        scan_securities(screen, fundamental, collector)
        if not screen.present:
            # 데이터가 빈 월말 호출: 전달 구성을 그대로 두고(UNCHANGED) 이 신호일을 처리하지 않은 것으로 되돌린다
            # (같은 데이터 날짜로 다시 불리면 재시도). 데이터 시작 전 날짜는 경고 없이 넘어간다. NOTES.md [F]
            self._last_signal_date = previous_signal_date
            self._empty_calls += 1
            if signal_date >= LEAN_DATA_START:
                self._recorder.warn_once(f"empty:{signal_date}",
                                         f"empty month-end data sig={signal_date}, previous universe kept")
            return Universe.UNCHANGED

        # 채택 규칙: 회사당 대표 주식 1개 → 2차: 대표 주식에만 나머지 조건(계획서 6장)
        representatives, multi_groups, adv, adv_missing = choose_representatives(
            self, screen.candidates, self._recorder.warn_once)
        screen_stocks(screen, representatives, signal_date, self._recorder)
        eligible = screen.eligible

        # 계획서 6장 재무 시점: 적격 종목의 이번 달 재무 스냅샷 저장(사용 가능 여부는 점수 계산 때 판정)
        record_snapshots(self._fund_history, screen, signal_date, self._recorder.warn_once)

        # 사용자 지시: 첫 신호일에 가격·재무 데이터가 실제로 있는지 확인. 없으면 첫 재구성을 다음 월말로 한 번 미룬다
        if first_run:
            data_ok, check_text, eligible_short = self._recorder.check_start_data(signal_date, eligible)
            if not data_ok and not self._start_deferred:
                self._start_deferred = True
                self._recorder.log_start_deferred(signal_date, check_text, eligible_short)
                return Universe.UNCHANGED
            self._recorder.log_start_applied(signal_date, check_text, self._start_deferred, data_ok, eligible_short)

        # 계획서 6장: 시총 순위와 진입 900 / 유지 1,100 완충
        ranked, rank, members = buffer_members(eligible, prev)
        entries = members - prev
        exits = prev - members
        exit_reason = classify_exits(exits, screen.present, screen.prev_reasons)
        pit_late, file_date_missing = count_pit(members, eligible, signal_date, self._calendar)

        row = self._recorder.record_month(signal_date, first_run, screen, ranked, rank, members, entries, exits,
                                          exit_reason, pit_late, file_date_missing, multi_groups, adv_missing)
        self._members = members

        if first_run:
            self._recorder.log_diag(signal_date, screen, collector, multi_groups, adv, adv_missing, representatives)

        # 2단계(계획서 6장): 조정 일봉은 모멘텀과 σ̂(역변동성)에 함께 쓰도록 종목 묶음 한 번으로 요청
        closes = adjusted_daily_closes(self, members, *history_window(signal_date, self._weighting == "invvol"),
                                       self._recorder.warn_once)
        factor_month = compute_factors(self, self._fund_history, members, eligible, signal_date, self._calendar,
                                       self._recorder.warn_once, closes=closes, score_mode=self._score_mode)
        self._factor_z = factor_month.z
        self._recorder.log_factor_month(factor_month)

        # 3단계(계획서 6장 구성): 점수가 있고 평가 시작 신호일(사용자 결정 PORTFOLIO_START_SIGNAL) 이후인 달만
        # 리밸런싱 계획. 그 전에는 유니버스·z만 계산하고 주문하지 않는다(현금)
        active = factor_month.z and (signal_date.year, signal_date.month) >= PORTFOLIO_START_SIGNAL
        plan = self._plan_rebalance(signal_date, members, eligible, factor_month, closes) if active else None
        self._recorder.close_month(row, signal_date, len(members), len(eligible), len(entries), len(exits),
                                   factor_month)
        return self._subscription(members, plan)

    def _plan_rebalance(self, signal_date, members, eligible, month, closes):
        """계획서 6장 구성(밴드 규칙) → 목표 비중(동일가중·역변동성, 5% 상한) → 신호일 종가·신호일 포트폴리오 가치로
        정수 주 주문(계획서 9장). 체결은 다음 거래일 MOC(_on_open)."""
        holdings = {s: int(self.portfolio[s].quantity) for s in self._held if int(self.portfolio[s].quantity)}
        sigmas = None
        if self._weighting == "invvol":
            sigmas = {s: sigma_hat(closes.get(s, [])) for s in set(month.z) | set(holdings)}
        selection = select_holdings(set(holdings), members, month, self._n_holdings, sigmas,
                                    first=self._report.rebalances == 0)
        weights, cap_hits = target_weights(selection.final, self._weighting, sigmas, self._n_holdings)
        prices = {s: eligible[s].price if s in eligible else float(self.securities[s].price)
                  for s in set(weights) | set(holdings)}
        pv = float(self.portfolio.total_portfolio_value)
        orders, stats = build_orders(weights, holdings, prices, pv, float(self.portfolio.cash), selection.sells)
        plan = Plan(signal_date, self._calendar.next_day(signal_date), selection, weights, cap_hits, orders, stats, pv)
        self._report.log_rebalance(plan, members, month.z)
        # 4단계(계획서 9장): 주문·보유 종목의 반스프레드를 신호일까지의 일봉으로 추정(체결 비용과 상장폐지 청산에 씀)
        cost_stats = self._cost.update({o.symbol for o in orders} | set(holdings))
        self._report.log_cost(plan, cost_stats)
        self._pending = plan
        return plan

    def _subscription(self, members, plan):
        """LEAN 구독 종목 = 현재 보유 + 이번 매수 예정(SUBSCRIBE_ALL_MEMBERS면 유니버스 전체도).
        매수 예정 종목은 이 선택(신호일 다음 날 0시)에서 구독·시드되어 체결일 개장 뒤 주문 때 가격을 갖는다."""
        symbols = set(self._held)
        if plan is not None:
            symbols |= {o.symbol for o in plan.orders}
        if SUBSCRIBE_ALL_MEMBERS:
            symbols |= members
        return list(symbols)

    def _on_open(self):
        """매 거래일 개장 ORDER_MINUTES_AFTER_OPEN분 뒤: 전날 체결 결과 점검, 체결일이면 매도·매수 MOC 제출(계획서 9장).
        수량은 계획을 만들 때(신호일 종가) 정한 값이다. 매도는 현재 보유보다 많이 내지 않는다."""
        if COVERAGE_CHECK:
            return
        self._report.daily_check(len(self._held), self._calendar.previous_day(self.time),
                                 float(self.securities[self._calendar_symbol].price))
        plan = self._pending
        if plan is None or self.time.date() < plan.exec_date:
            return
        self._pending = None
        late = self.time.date() > plan.exec_date
        for order in plan.orders:
            quantity = order.quantity
            if quantity < 0:
                quantity = -min(-quantity, max(0, int(self.portfolio[order.symbol].quantity)))
            if quantity == 0:
                continue
            ticket = self.market_on_close_order(order.symbol, quantity, tag=order.reason)
            self._report.order_submitted(ticket, self.time, self._report.rebalances, late)

    def on_order_event(self, order_event):
        """체결은 회전율·수수료·보유 목록에 반영, 취소·무효(상장폐지·거래정지 포함)는 LEAN 결과 그대로 두고 센다."""
        status = order_event.status
        if status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
            symbol = order_event.symbol
            quantity, price = float(order_event.fill_quantity), float(order_event.fill_price)
            self._report.record_fill(order_event, float(self.portfolio.total_portfolio_value),
                                     self._cost.spread_cost(symbol, quantity, price),
                                     self._cost.adv_ratio(symbol, abs(quantity * price)))
            # LEAN 상장폐지 자동 청산은 on_data보다 먼저 체결돼 보유 목록에서 빠지므로 여기서 센다(2026-09-27, 전체 실행에서
            # 'Liquidate from delisting' 5건인데 delist=0이던 문제). on_data 쪽 집계는 중복되지 않게 없앴다.
            order = self.transactions.get_order_by_id(order_event.order_id)
            if status == OrderStatus.FILLED and order is not None and "delisting" in str(order.tag).lower():
                self._report.record_delisting()
            if int(self.portfolio[symbol].quantity):
                self._held.add(symbol)
            else:
                self._held.discard(symbol)
        elif status in (OrderStatus.CANCELED, OrderStatus.INVALID):
            self._report.record_unfilled()

    def on_end_of_algorithm(self):
        """마지막 [PYEAR] → [PERF](첫 매매 이후 성과) → [SUMMARY]. 마지막 가치 기준일 = 가장 최근 종가일."""
        if COVERAGE_CHECK:
            self._coverage.finish()
            return
        today = self.time.date()
        is_trading = self._calendar.previous_day(datetime.combine(today + timedelta(days=1), datetime.min.time())) == today
        last_close = today if (self.time.hour >= 16 and is_trading) else self._calendar.previous_day(self.time)
        self._report.finish(self._start_deferred, self._empty_calls, last_close,
                            float(self.securities[self._calendar_symbol].price))
