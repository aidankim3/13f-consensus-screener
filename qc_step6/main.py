# region imports
from AlgorithmImports import *
# endregion
# 1세대 프로그램 매매 모델 — 6단계: Q1 불합격(5단계)으로 A0 자리에 ETF(RSP·SPY, 사용자 결정 2026-10-01)를 넣고
# 계획서 7·10장의 M*(주식 + 현금 고정 혼합)·A1(변동성 제어)·B(A1 70 + IEF 15 + GLD 15)를 개발 구간 2005~2015에서 계산한다.
# 실제 주문은 내지 않고 가상 장부로만 계산한다(ETF 몇 개라 LEAN 체결과 차이가 작음, NOTES.md). 출력·확인 항목은 NOTES.md.
from datetime import timedelta

from config import *
from etf import Ledger, ewma_sigma, half_spread, stats


class ProgramTradingEtfStep6(QCAlgorithm):

    def initialize(self):
        if END_DATE > DEV_PERIOD_LAST_DAY:
            raise ValueError(f"개발 구간 밖 날짜: {END_DATE} (허용 ~{DEV_PERIOD_LAST_DAY})")
        self.set_start_date(START_DATE.year, START_DATE.month, START_DATE.day)
        self.set_end_date(END_DATE.year, END_DATE.month, END_DATE.day)
        self.set_cash(INITIAL_CASH)
        self.tickers = tuple(EQUITY_TICKERS) + (BOND_TICKER, GOLD_TICKER)
        self.sym = {t: self.add_equity(t, Resolution.DAILY).symbol for t in self.tickers}   # 조정가(배당 재투자)
        self.set_benchmark(self.sym["SPY"])
        self.rate_symbol = None
        try:
            self.rate_symbol = self.add_data(USTreasuryYieldCurveRate, "USTYCR", Resolution.DAILY).symbol
        except Exception as err:
            self.debug(f"[WARN] treasury yield data unavailable: {err} -> cash rate 0 (fee only)")
        self.rate, self.rates = None, []
        self.bars = {t: [] for t in self.tickers}          # [(날짜, 고가, 저가, 종가)]
        self.last_close = {}
        self.prev_day, self.started = None, False
        grid = [round(k * MSTAR_STEP, 4) for k in range(int(round(1 / MSTAR_STEP)) + 1)]
        self.ledgers = []
        for cost, mult in COST_SCENARIOS.items():
            for e in EQUITY_TICKERS:
                self.ledgers += [Ledger(f"{k}_{e}_{cost}", k, e, mult) for k in ("A0", "A1", "B")]
                self.ledgers += [Ledger(f"M{int(round(w * 100))}_{e}_{cost}", "M", e, mult, w) for w in grid]
        self.cash_ledger = Ledger("CASH", "M", EQUITY_TICKERS[0], 0.0, 0.0)
        self.by_name = {l.name: l for l in self.ledgers}
        self.debug(f"[CONFIG] step=6-etf equity={','.join(EQUITY_TICKERS)} bond={BOND_TICKER} gold={GOLD_TICKER} "
                   f"period={START_DATE}~{END_DATE} first_signal={FIRST_SIGNAL} dd_limit={DD_LIMIT} "
                   f"sigma_target={SIGMA_TARGET} sigma=ewma{SIGMA_HALF_LIFE}/{SIGMA_WINDOW}/min{SIGMA_MIN_OBS} "
                   f"B={B_WEIGHTS} mstar_step={MSTAR_STEP} costs={COST_SCENARIOS} cash=T-bill1m-{CASH_FEE} "
                   f"min_trade=${MIN_TRADE_VALUE:.0f} ledgers={len(self.ledgers)}")

    def on_data(self, data):
        if self.rate_symbol is not None:
            try:
                for item in data.get(USTreasuryYieldCurveRate).values():
                    if item.one_month is not None:
                        self.rate = float(item.one_month)
            except Exception:
                pass
        day, got = None, {}
        for t, s in self.sym.items():
            if data.bars.contains_key(s):
                bar = data.bars[s]
                day = (bar.end_time - timedelta(minutes=1)).date()
                got[t] = (float(bar.high), float(bar.low), float(bar.close))
        if not got or day is None or (self.prev_day is not None and day <= self.prev_day):
            return
        for t, (h, l, c) in got.items():
            self.bars[t].append((day, h, l, c))
            self.last_close[t] = c
        self._process(day)

    def _process(self, day):
        prev = self.prev_day
        if self.started:
            days = (day - prev).days
            rf = ((self.rate or 0.0) / 100 - CASH_FEE) * days / CASH_DAY_COUNT
            for ledger in self.ledgers + [self.cash_ledger]:
                ledger.cash *= 1 + rf
            if self.rate is not None:
                self.rates.append(self.rate)
        if prev is not None and (day.year, day.month) != (prev.year, prev.month) \
                and (prev.year, prev.month) >= FIRST_SIGNAL and all(t in self.last_close for t in self.tickers):
            self._rebalance(prev, day)
        if self.started:
            prices = dict(self.last_close)
            for ledger in self.ledgers + [self.cash_ledger]:
                ledger.daily.append((day, ledger.value(prices)))
        self.prev_day = day

    def _rebalance(self, signal, day):
        """신호일(전 거래일 = 월말)까지의 정보로 목표를 정하고 오늘(다음 거래일) 종가에 체결(계획서 9장 MOC)."""
        upto = {t: [b for b in self.bars[t] if b[0] <= signal] for t in self.tickers}
        sig_prices = {t: upto[t][-1][3] for t in self.tickers}
        exec_prices = dict(self.last_close)
        if not self.started:                                   # 첫 신호일 종가에 전액 현금으로 시작
            self.started = True
            for ledger in self.ledgers + [self.cash_ledger]:
                ledger.daily.append((signal, float(INITIAL_CASH)))
        halves = {t: half_spread([(b[1], b[2], b[3]) for b in upto[t]]) for t in self.tickers}
        sigmas = {e: ewma_sigma([b[3] for b in upto[e]]) for e in EQUITY_TICKERS}
        for ledger in self.ledgers:
            ledger.rebalance(ledger.targets(sigmas[ledger.equity]), sig_prices, exec_prices, halves)
        if (signal.year, signal.month) > FIRST_SIGNAL:
            self._plot(sig_prices)

    def _plot(self, prices):
        """월말 지수(1000에서 시작): 기본 비용 A0·A1·B(주식 ETF별), 현금, IEF·GLD 조정가. 차트 시리즈 9개(한도 10개).
        rebalance 시점에는 daily의 마지막 값이 신호일(월말) 값이다."""
        for name in [f"{k}_{e}_base" for e in EQUITY_TICKERS for k in ("A0", "A1", "B")]:
            self.plot("ETF", name.replace("_base", ""), self.by_name[name].daily[-1][1] / INITIAL_CASH * 1000)
        self.plot("ETF", "CASH", self.cash_ledger.daily[-1][1] / INITIAL_CASH * 1000)
        for t in (BOND_TICKER, GOLD_TICKER):
            self.plot("ETF", t, prices[t])

    def on_end_of_algorithm(self):
        if self.started:
            self._plot(dict(self.last_close))              # 마지막 달(마지막 거래일 = 월말)
        cash = self.cash_ledger.daily
        st = {l.name: stats(l.daily, cash) for l in self.ledgers}
        cs = stats(cash, cash)
        rates = self.rates or [0.0]
        self.debug(f"[CASH] T-bill1m days={len(self.rates)} first={rates[0]:.2f}% last={rates[-1]:.2f}% "
                   f"avg={sum(rates) / len(rates):.2f}% | cash cagr={cs['cagr']:+.2%} months={cs['n']}")
        fmt = lambda s: (f"cagr={s['cagr']:+.2%} vol={s['vol']:.1%} sh={s['sharpe']:.2f} mdd={s['mdd']:.1%} "
                         f"mdd/s={s['mdd_sigma']:.2f} cvar/s={s['cvar_sigma']:.2f} logg={s['loggrowth']:+.2%}")
        for e in EQUITY_TICKERS:
            grid = sorted((l.weight, st[l.name]["mdd"]) for l in self.ledgers
                          if l.kind == "M" and l.equity == e and l.name.endswith("_base"))
            ok = [w for w, mdd in grid if mdd >= -DD_LIMIT]
            wstar = max(ok) if ok else None
            self.debug(f"[MSTAR {e}] w*={wstar} | " + " ".join(f"{int(w * 100)}:{mdd:.0%}" for w, mdd in grid))
            names = [("A0", f"A0_{e}_base"), ("A1", f"A1_{e}_base"), ("B", f"B_{e}_base")]
            if wstar is not None:
                names.insert(1, (f"M*{int(round(wstar * 100))}", f"M{int(round(wstar * 100))}_{e}_base"))
            for label, name in names:
                l = self.by_name[name]
                avg_pv = sum(v for _, v in l.daily) / len(l.daily)
                lev = f" L_avg={sum(l.lever) / len(l.lever):.2f} L_min={min(l.lever):.2f}" if l.lever else ""
                self.debug(f"[CAND {e} {label}] {fmt(st[name])} to={l.traded / avg_pv / st[name]['years'] / 2:.2f} "
                           f"cost={l.costs / avg_pv / st[name]['years']:.2%}/yr{lev}")
            a0, a1, b = st[f"A0_{e}_base"], st[f"A1_{e}_base"], st[f"B_{e}_base"]
            red = (abs(a0["cvar_sigma"]) - abs(a1["cvar_sigma"])) / abs(a0["cvar_sigma"]) if a0["cvar_sigma"] else 0.0
            q2 = [a1["sharpe"] - a0["sharpe"] >= -0.05, red >= 0.10, a1["mdd_sigma"] <= a0["mdd_sigma"]]
            q3 = [b["sharpe"] - a1["sharpe"] >= 0.05, b["mdd_sigma"] <= a1["mdd_sigma"]]
            self.debug(f"[Q2dev {e}] A1-A0 sharpe {a1['sharpe'] - a0['sharpe']:+.2f}(>=-0.05 {q2[0]}) "
                       f"cvar/s reduction {red:+.0%}(>=10% {q2[1]}) mdd/s {a1['mdd_sigma']:.2f} vs {a0['mdd_sigma']:.2f}"
                       f"(not larger {q2[2]}) -> dev {'pass' if all(q2) else 'fail'}")
            self.debug(f"[Q3dev {e}] B-A1 sharpe {b['sharpe'] - a1['sharpe']:+.2f}(>=+0.05 {q3[0]}) "
                       f"mdd/s {b['mdd_sigma']:.2f} vs {a1['mdd_sigma']:.2f}(not larger {q3[1]}) "
                       f"-> dev {'pass' if all(q3) else 'fail'}")
            within = [label for label, name in names if st[name]["mdd"] >= -DD_LIMIT]
            self.debug(f"[Q4dev {e}] within dd {DD_LIMIT:.0%}: {','.join(within) or 'none'} | logg " +
                       " ".join(f"{label}={st[name]['loggrowth']:+.2%}" for label, name in names))
            high = [(label, name.replace("_base", "_high")) for label, name in names]
            self.debug(f"[HIGH {e}] cost x2 logg " + " ".join(f"{label}={st[n]['loggrowth']:+.2%}" for label, n in high)
                       + " | mdd " + " ".join(f"{label}={st[n]['mdd']:.1%}" for label, n in high))
