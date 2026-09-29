# region imports
from AlgorithmImports import *
# endregion
# 3단계 기록·로그: [CONFIG](3단계)/[REBAL]/[FILL]/[PYEAR]/[PERF], [SUMMARY] 끝의 portfolio 요약과 런타임 통계.
# 핵심 줄·경고·[SUMMARY] 출력은 diagnostics.Recorder를 통한다. 누적 계산은 portfolio.TradeBook·performance
import zlib
from collections import Counter

from config import *
from portfolio import TradeBook, performance
from universe import raw_daily_bars


class PortfolioReport:
    """3단계 기록(계획서 6장 구성·9장 체결). recorder: diagnostics.Recorder(key_log·warn_once·summary)."""

    def __init__(self, algo, recorder):
        self.algo, self.recorder = algo, recorder
        self.rebalances = 0             # 만든 리밸런싱 계획 수
        self.book = TradeBook()         # 연도별·전체 체결·보유 통계
        self._fill_samples = []         # [FILL] 확인 대기 표본
        self._sampled = Counter()       # 리밸런싱 번호 → 표본 수
        self._perf = []                 # [PERF]용 (가치 기준일, 포트폴리오 가치, SPY 조정가). 첫 체결 전날 종가부터
        self._last_open = None          # 오늘 개장 뒤 점검 때 본 (전날 종가 기준일, 가치, SPY)
        self._first_fill = None

    def log_config(self, n_holdings, weighting):
        """3단계 설정(CLAUDE.md 원칙 5). 평가 시작 신호일과 이유(사용자 결정, NOTES.md 기록)를 함께 남긴다."""
        y, m = PORTFOLIO_START_SIGNAL
        self.recorder.key_log(
            f"[CONFIG] step=3-portfolio n={n_holdings} weighting={weighting} quick_test={QUICK_TEST} "
            f"period={BACKTEST_START_DATE}~{BACKTEST_END_DATE} portfolio_start={y}-{m:02d}"
            f"(reason:1998-2002 eligible<900 so not large-cap; 1999-2002 data-limited reference) "
            f"keep={KEEP_TOP_FRACTION} fill={FILL_TOP_FRACTION} cap={MAX_WEIGHT} "
            f"sigma=ewma{SIGMA_HALF_LIFE}/{SIGMA_WINDOW}/min{SIGMA_MIN_OBS} min_trade=${MIN_TRADE_VALUE:.0f} "
            f"cash_buffer={CASH_BUFFER} moc=open+{ORDER_MINUTES_AFTER_OPEN}m brokerage=IB/margin "
            f"lev_check={BUYING_POWER_LEVERAGE} fee=LEAN-IB costs=fee_only norm=raw "
            f"subscribe={'all' if SUBSCRIBE_ALL_MEMBERS else 'holdings+buys'}")

    def _port(self):
        """진행 중인 연도의 누적. 연도가 바뀌면 직전 연도 [PYEAR]를 먼저 남긴다."""
        c, finished = self.book.counter(self.algo.time.year)
        if finished:
            self._log_pyear(finished)
        return c

    def log_rebalance(self, plan, members, z):
        """리밸런싱 계획 기록. 처음 REBAL_LOG_COUNT번은 [REBAL] 상세. 첫 줄 끝의 uni·zt는 그 신호일 유니버스·z의
        CRC32 지문(빠른 실행과 전체 실행의 첫 포트폴리오 입력이 같은지 QC에서 비교하는 용도)."""
        self.rebalances += 1
        sel, st = plan.selection, plan.stats
        c = self._port()
        c["rebals"] += 1
        c["skipped"] += st["skipped"]
        c["empty"] += sel.empty
        c["cap"] += plan.cap_hits
        c["novol"] += sel.novol
        if self.rebalances <= REBAL_LOG_COUNT:
            sells = ",".join(f"{k}:{v}" for k, v in sorted(Counter(sel.sells.values()).items()))
            prints = ""
            if self.rebalances == 1:
                uni = zlib.crc32("\n".join(sorted(str(s.id) for s in members)).encode())
                zt = zlib.crc32("\n".join(sorted(f"{s.id}:{v:.10f}" for s, v in z.items())).encode())
                prints = f" uni={uni:08x} zt={zt:08x}"
            self.algo.log(f"[REBAL] #{self.rebalances} sig={plan.signal_date} exec={plan.exec_date} keep={len(sel.kept)} "
                          f"sell={len(sel.sells)}({sells}) new={len(sel.added)} empty={sel.empty} novol={sel.novol} "
                          f"orders={len(plan.orders)} skip={st['skipped']}(${st['skipped_value']:.0f}) "
                          f"unbought=${st['unbought']:.0f} werr_max={st['werr_max']:.4f} "
                          f"cash={st['cash_weight'] * 100:.1f}% cap={plan.cap_hits} scaled={st['buy_scaled']} "
                          f"pv=${plan.pv:.0f}{prints}")

    def order_submitted(self, ticket, submit_time, plan_no, late):
        c = self._port()
        c["orders"] += 1
        c["late"] += late
        self.book.submitted[ticket.order_id] = (submit_time, plan_no)

    def record_fill(self, event, pv):
        """체결: 회전율·수수료 누적, 처음 리밸런싱들의 [FILL] 표본. 첫 체결이면 그날 개장 뒤 본 가치(전날 종가, 전액
        현금)를 [PERF] 출발점으로 둔다."""
        if not self.book.started and self._last_open is not None:
            self._perf.append(self._last_open)
            self._first_fill = self.algo.time.date()
        fee = abs(float(event.order_fee.value.amount))
        quantity, price = float(event.fill_quantity), float(event.fill_price)
        self.book.add_fill(self._port(), abs(quantity * price), pv, fee)
        info = self.book.submitted.get(event.order_id)
        if info and info[1] <= REBAL_LOG_COUNT and self._sampled[info[1]] < FILL_SAMPLES:
            self._sampled[info[1]] += 1
            self._fill_samples.append((event.symbol, quantity, price, fee, info[0], self.algo.time))

    def record_unfilled(self):
        """체결되지 않은 주문(취소·무효, 상장폐지·거래정지 포함). LEAN 처리 결과를 그대로 두고 센다."""
        self._port()["rej"] += 1

    def record_delisting(self):
        self._port()["delist"] += 1

    def daily_check(self, n_held, value_date, spy_price):
        """매 거래일 주문 전: [FILL] 표본 확인, 전날 종가(value_date) 기준 가치·SPY를 [PERF]에 쌓고,
        현금 음수·노출·현금 비중·보유 수를 누적."""
        self._verify_fill_samples()
        pv = float(self.algo.portfolio.total_portfolio_value)
        cash = float(self.algo.portfolio.cash)
        self._last_open = (value_date, pv, spy_price)
        if not self.book.started:
            return
        self._perf.append(self._last_open)
        exposure = self.book.add_day(self._port(), n_held, pv, cash)
        if cash < 0:
            self.recorder.warn_once("neg_cash", f"negative cash {cash:.2f} on {self.algo.time:%Y-%m-%d} "
                                                f"exposure={exposure:.3f}")

    def _verify_fill_samples(self):
        """체결 다음 날, 표본의 체결가를 체결일 원주가 일봉 종가와 비교([FILL], 같아야 함)."""
        today = self.algo.time.date()
        ready = [x for x in self._fill_samples if x[5].date() < today]
        if not ready:
            return
        self._fill_samples = [x for x in self._fill_samples if x[5].date() >= today]
        bars = raw_daily_bars(self.algo, list({x[0] for x in ready}), FILL_CHECK_BARS, self.recorder.warn_once)
        for symbol, quantity, price, fee, submitted, filled in ready:
            close = next((c for d, c, _ in bars.get(symbol, []) if d == filled.date()), None)
            ok = close is not None and abs(price / close - 1) <= FILL_MATCH_TOLERANCE
            self.algo.log(f"[FILL] {symbol.value} qty={quantity:+.0f} fill=${price:.2f} "
                          f"close={'na' if close is None else f'${close:.2f}'} {'ok' if ok else 'MISMATCH'} "
                          f"submit={submitted:%Y-%m-%d %H:%M} filled={filled:%Y-%m-%d %H:%M} fee=${fee:.2f}")

    def _log_pyear(self, y):
        c = y["c"]
        self.algo.log(f"[PYEAR {y['year']}] hold={y['hold']:.1f} to={y['turnover']:.2f} orders={c['orders']} "
                      f"fee=${c['fees']:.0f}({y['fee_pct']:.2f}%) skip={c['skipped']} empty={c['empty']} "
                      f"cash={y['cash'] * 100:.1f}% cap={c['cap']} delist={c['delist']} rej={c['rej']} neg={c['neg']}"
                      + (f" novol={c['novol']}" if c["novol"] else ""))

    # ------------------------------------------------------------------
    # 종료: 마지막 [PYEAR] → [PERF] → [SUMMARY](diagnostics) + 런타임 통계
    # ------------------------------------------------------------------
    def finish(self, start_deferred, empty_calls, last_close, spy_price):
        finished = self.book.close_year()
        if finished:
            self._log_pyear(finished)
        if self._perf and last_close > self._perf[-1][0]:
            self._perf.append((last_close, float(self.algo.portfolio.total_portfolio_value), spy_price))
        perf = performance(self._perf)
        if perf is not None:
            self.recorder.key_log(self._perf_line(perf))
        text, stats = self._summary_parts(self.book.summary(), perf)
        self.recorder.summary(start_deferred, empty_calls, text, stats)

    def _perf_line(self, p):
        """첫 매매 이후 성과(스프레드 미포함이라 성과 판단용 아님 → costs=fee_only). base = 첫 체결 전날 종가(전액 현금)."""
        pct = lambda v: "na" if v is None else f"{v * 100:+.1f}%"
        sharpe = "na" if p["p_sharpe"] is None else f"{p['p_sharpe']:.2f}"
        return (f"[PERF] costs=fee_only base={p['start']} first_fill={self._first_fill} end={p['end']} "
                f"yrs={p['years']:.2f} cagr={pct(p['p_cagr'])} vol={p['p_vol'] * 100:.1f}% sharpe={sharpe} "
                f"mdd={p['p_mdd'] * 100:.1f}%({p['p_peak']}>{p['p_trough']},rec {p['p_recover'] or 'none'}) "
                f"| SPY cagr={pct(p['spy_cagr'])} mdd={p['spy_mdd'] * 100:.1f}%")

    @staticmethod
    def _summary_parts(p, perf):
        """[SUMMARY] 끝의 portfolio 요약과 런타임 통계(연평균 회전율·수수료 %, 평균 보유 수·현금 비중, [PERF])."""
        if p is None:
            return " | portfolio: none", {}
        text = (f" | portfolio: years={p['years']} turnover_avg={p['turnover']:.2f} fee_avg={p['fee_pct']:.2f}% "
                f"skipped={p['skipped']} neg_cash_days={p['neg']} rej={p['rej']} late={p['late']} "
                f"avg_hold={p['hold']:.1f} cash_avg={p['cash'] * 100:.1f}% max_expo={p['max_expo']:.3f}")
        stats = {"turnover": f"{p['turnover']:.2f}", "fee_pct": f"{p['fee_pct']:.2f}",
                 "avg_hold": f"{p['hold']:.1f}", "cash_avg": f"{p['cash'] * 100:.1f}"}
        if perf is not None:
            fmt = lambda v: "na" if v is None else f"{v * 100:.1f}"
            stats.update({"p_cagr": fmt(perf["p_cagr"]), "p_vol": fmt(perf["p_vol"]), "p_mdd": fmt(perf["p_mdd"]),
                          "p_sharpe": "na" if perf["p_sharpe"] is None else f"{perf['p_sharpe']:.2f}",
                          "spy_cagr": fmt(perf["spy_cagr"]), "spy_mdd": fmt(perf["spy_mdd"])})
        return text, stats
