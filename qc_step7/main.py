# region imports
from AlgorithmImports import *
# endregion
# 1세대 프로그램 매매 모델 — 7단계(최종 평가, 사용자 동결 2026-10-01): 6단계 규칙(RSP·SPY × M*·A1·B·A2, 운용안 E 제외)을
# 2005~동결 직전(2026-09-30)으로 한 번 계산하고 계획서 10장 판정(Q2·Q3 세 구간, Q4 한도·위기 손실·90% CI, RSP vs SPY)을 출력한다.
# 실제 주문은 내지 않고 가상 장부로만 계산한다. 출력·확인 항목은 NOTES.md.
from datetime import timedelta

from config import *
from etf import Ledger, ewma_sigma, half_spread, logdiff_ci, stats, window_mdd
from macro import MacroSignals


class ProgramTradingEtfStep7(QCAlgorithm):

    def initialize(self):
        if END_DATE >= FREEZE_DATE:
            raise ValueError(f"동결일 이후 날짜: {END_DATE} (동결 {FREEZE_DATE})")
        self.set_start_date(START_DATE.year, START_DATE.month, START_DATE.day)
        self.set_end_date(END_DATE.year, END_DATE.month, END_DATE.day)
        self.set_cash(INITIAL_CASH)
        self.tickers = tuple(EQUITY_TICKERS) + (BOND_TICKER, GOLD_TICKER)
        self.sym = {t: self.add_equity(t, Resolution.DAILY).symbol for t in self.tickers}   # 조정가(배당 재투자)
        self.set_benchmark(self.sym["SPY"])
        self.cash_sym = self.add_equity(CASH_TICKER, Resolution.DAILY).symbol
        self.sgov, self.sgov_days = {}, 0                 # {날짜: SGOV 조정 종가}
        self.rate_symbol = None
        try:
            self.rate_symbol = self.add_data(USTreasuryYieldCurveRate, "USTYCR", Resolution.DAILY).symbol
        except Exception as err:
            self.debug(f"[WARN] treasury yield data unavailable: {err} -> cash rate 0 (fee only)")
        self.rate, self.rates = None, []
        self.macro = MacroSignals()
        self.fred = {}
        for name in FRED_SERIES:
            try:
                self.fred[self.add_data(Fred, name, Resolution.DAILY).symbol] = name
            except Exception as err:
                self.debug(f"[WARN] FRED {name} unavailable: {err}")
        self.bars = {t: [] for t in self.tickers}          # [(날짜, 고가, 저가, 종가)]
        self.last_close = {}
        self.prev_day, self.started = None, False
        grid = [round(k * MSTAR_STEP, 4) for k in range(int(round(1 / MSTAR_STEP)) + 1)]
        self.ledgers = []
        for cost, mult in COST_SCENARIOS.items():
            for e in EQUITY_TICKERS:
                self.ledgers += [Ledger(f"{k}_{e}_{cost}", k, e, mult) for k in ("A0", "A1", "B")]
                self.ledgers += [Ledger(f"M{int(round(w * 100))}_{e}_{cost}", "M", e, mult, w) for w in grid]
                self.ledgers += [Ledger(f"A2{v}_{e}_{cost}", "A2", e, mult, v) for v in A2_VARIANTS]
        self.cash_ledger = Ledger("CASH", "M", EQUITY_TICKERS[0], 0.0, 0.0)
        self.by_name = {l.name: l for l in self.ledgers}
        self.debug(f"[CONFIG] step=7-final equity={','.join(EQUITY_TICKERS)} bond={BOND_TICKER} gold={GOLD_TICKER} "
                   f"period={START_DATE}~{END_DATE} first_signal={FIRST_SIGNAL} dd_limit={DD_LIMIT} "
                   f"sigma_target={SIGMA_TARGET} sigma=ewma{SIGMA_HALF_LIFE}/{SIGMA_WINDOW}/min{SIGMA_MIN_OBS} "
                   f"B={B_WEIGHTS} mstar_step={MSTAR_STEP} costs={COST_SCENARIOS} cash=T-bill1m-{CASH_FEE}->{CASH_TICKER}@{CASH_SGOV_FROM} "
                   f"mstar={MSTAR_FROZEN} q4={Q4_ORDER} periods={[p[0] for p in PERIODS]} "
                   f"min_trade=${MIN_TRADE_VALUE:.0f} ledgers={len(self.ledgers)}")

    def on_data(self, data):
        if self.rate_symbol is not None:
            try:
                for item in data.get(USTreasuryYieldCurveRate).values():
                    if item.one_month is not None:
                        self.rate = float(item.one_month)
            except Exception:
                pass
        if self.fred:
            try:
                for item in data.get(Fred).values():
                    name = self.fred.get(item.symbol)
                    if name:
                        self.macro.add(name, item.time, float(item.value))
            except Exception:
                pass
        day, got = None, {}
        for t, s in self.sym.items():
            if data.bars.contains_key(s):
                bar = data.bars[s]
                day = (bar.end_time - timedelta(minutes=1)).date()
                got[t] = (float(bar.high), float(bar.low), float(bar.close))
        if data.bars.contains_key(self.cash_sym):
            cb = data.bars[self.cash_sym]
            self.sgov[(cb.end_time - timedelta(minutes=1)).date()] = float(cb.close)
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
            if day >= CASH_SGOV_FROM and self.sgov.get(day) and self.sgov.get(prev):
                rf = self.sgov[day] / self.sgov[prev] - 1       # 현금 = SGOV(계획서 10장)
                self.sgov_days += 1
            for ledger in self.ledgers + [self.cash_ledger]:
                ledger.cash *= 1 + rf
            if self.rate is not None:
                self.rates.append(self.rate)
        new_month = prev is not None and (day.year, day.month) != (prev.year, prev.month)
        if new_month:                                          # 월말(prev) 종가 기록과 A2 탐지 기록(1999~)
            for t in self.tickers:
                closes = [b for b in self.bars[t] if b[0] <= prev]
                if closes:
                    self.macro.add_month_close(t, prev, closes[-1][3])
            self.macro.record(prev)
        if new_month and (prev.year, prev.month) >= FIRST_SIGNAL and all(t in self.last_close for t in self.tickers):
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
        recession = {(e, v): self.macro.regime(e, signal, v) for e in EQUITY_TICKERS for v in A2_VARIANTS}
        for ledger in self.ledgers:
            rec = recession.get((ledger.equity, ledger.weight)) if ledger.kind == "A2" else False
            ledger.rebalance(ledger.targets(sigmas[ledger.equity], rec), sig_prices, exec_prices, halves)
        if (signal.year, signal.month) > FIRST_SIGNAL:
            self._plot(sig_prices)

    def _plot(self, prices):
        """월말 지수(1000에서 시작): 기본 비용 A0·A1·B·A2a(주식 ETF별), 현금. 차트 시리즈 9개(한도 10개).
        rebalance 시점에는 daily의 마지막 값이 신호일(월말) 값이다."""
        for name in [f"{k}_{e}_base" for e in EQUITY_TICKERS for k in ("A0", "A1", "B", "A2a")]:
            self.plot("ETF", name.replace("_base", ""), self.by_name[name].daily[-1][1] / INITIAL_CASH * 1000)
        self.plot("ETF", "CASH", self.cash_ledger.daily[-1][1] / INITIAL_CASH * 1000)


    def on_end_of_algorithm(self):
        counts = " ".join(f"{n}={len(v)}" for n, v in self.macro.obs.items())
        self.debug(f"[MACRO] fred obs {counts} | first {self.macro.first_dates()} | detection (lag: monthly <= M-1, daily <= signal)")
        for line in self.macro.detection_report():
            self.debug(f"[DETECT] {line}")
        if self.started:
            self._plot(dict(self.last_close))              # 마지막 달
        cash = self.cash_ledger.daily
        cs = stats(cash, cash)
        rates = self.rates or [0.0]
        self.debug(f"[CASH] T-bill1m days={len(self.rates)} first={rates[0]:.2f}% last={rates[-1]:.2f}% "
                   f"avg={sum(rates) / len(rates):.2f}% | {CASH_TICKER} days={self.sgov_days} (from {CASH_SGOV_FROM}, "
                   f"first bar {min(self.sgov) if self.sgov else 'none'}) | cash cagr={cs['cagr']:+.2%} months={cs['n']} "
                   f"last day={cash[-1][0]}")
        pnames = [p[0] for p in PERIODS]
        short = lambda s: f"{s['cagr']:+.1%}/{s['sharpe']:.2f}/{s['mdd']:.0%}" if s else "na"
        red = lambda a, b: ((abs(a["cvar_sigma"]) - abs(b["cvar_sigma"])) / abs(a["cvar_sigma"])
                            if a and b and a["cvar_sigma"] else float("nan"))
        final, final_keys = {}, {}
        for e in EQUITY_TICKERS:
            keys = {"A0": f"A0_{e}", "M*": f"M{int(round(MSTAR_FROZEN[e] * 100))}_{e}", "A1": f"A1_{e}",
                    "B": f"B_{e}", "A2": f"A2a_{e}"}
            daily = lambda k, cost="base": self.by_name[f"{keys[k]}_{cost}"].daily
            full = {k: stats(daily(k), cash) for k in keys}
            per = {k: {p: stats(daily(k), cash, s0, s1) for p, s0, s1 in PERIODS} for k in keys}
            comb = {k: stats(daily(k), cash, COMBINED_START, END_DATE) for k in keys}
            for k in keys:
                s = full[k]
                self.debug(f"[PERIOD {e} {k}] ALL cagr={s['cagr']:+.2%} sh={s['sharpe']:.2f} mdd={s['mdd']:.1%} "
                           f"logg={s['loggrowth']:+.2%} | cagr/sh/mdd " + " ".join(f"{p}={short(per[k][p])}" for p in pnames)
                           + f" 16+={short(comb[k])}")

            def q2(k):                                         # 계획서 10장 Q2(A2도 같은 기준, 개정 2)
                a0, x = comb["A0"], comb[k]
                r = red(a0, x)
                c = [x["sharpe"] - a0["sharpe"] >= Q2_SHARPE_MIN, r >= Q2_CVAR_RED and x["mdd_sigma"] <= a0["mdd_sigma"]]
                reds = [red(per["A0"][p], per[k][p]) for p in pnames]
                c.append(sum(1 for v in reds if v >= Q2_CVAR_RED) >= Q2_PERIODS_MIN)
                self.debug(f"[Q2 {e} {k}] 16+ sh {x['sharpe'] - a0['sharpe']:+.2f}(>={Q2_SHARPE_MIN} {c[0]}) "
                           f"cvar/s red {r:+.0%} mdd/s {x['mdd_sigma']:.2f} vs {a0['mdd_sigma']:.2f}({c[1]}) | red by period "
                           + " ".join(f"{p}={v:+.0%}" for p, v in zip(pnames, reds)) + f"({c[2]}) -> {'PASS' if all(c) else 'FAIL'}")
                return all(c)

            pass_a1, pass_a2 = q2("A1"), q2("A2")
            b, a1 = comb["B"], comb["A1"]
            diffs = [per["B"][p]["sharpe"] - per["A1"][p]["sharpe"] for p in pnames]
            c3 = [b["sharpe"] - a1["sharpe"] >= Q3_SHARPE_MIN, b["mdd_sigma"] <= a1["mdd_sigma"],
                  sum(1 for d in diffs if d >= Q3_SHARPE_MIN) >= 2]
            pass_b = all(c3)
            self.debug(f"[Q3 {e} B] 16+ sh {b['sharpe'] - a1['sharpe']:+.2f}(>=+{Q3_SHARPE_MIN} {c3[0]}) "
                       f"mdd/s {b['mdd_sigma']:.2f} vs {a1['mdd_sigma']:.2f}({c3[1]}) | sh diff by period "
                       + " ".join(f"{p}={d:+.2f}" for p, d in zip(pnames, diffs)) + f"({c3[2]}) -> {'PASS' if pass_b else 'FAIL'}")

            eligible = {"A0": True, "M*": True, "A1": pass_a1, "B": pass_b, "A2": pass_a2}
            parts, survivors = [], []
            for k in ("A0",) + tuple(Q4_ORDER):
                losses = [window_mdd(daily(k), s0, s1) for _, s0, s1 in CRISIS_WINDOWS]
                within = full[k]["mdd"] >= -DD_LIMIT and all(x is None or x >= -DD_LIMIT for x in losses)
                if k != "A0" and within and eligible[k]:
                    survivors.append(k)
                parts.append(f"{k}:mdd={full[k]['mdd']:.1%} " + "/".join(
                    f"{w}={x:.1%}" if x is not None else f"{w}=na" for (w, _, _), x in zip(CRISIS_WINDOWS, losses))
                    + f" q={'ok' if eligible[k] else 'fail'} lim={'ok' if within else 'over'}")
            self.debug(f"[Q4 {e}] limit {DD_LIMIT:.0%} | " + " | ".join(parts))
            if not survivors:
                grid = sorted((l.weight, stats(l.daily, cash)["mdd"], [window_mdd(l.daily, s0, s1) for _, s0, s1 in CRISIS_WINDOWS])
                              for l in self.ledgers if l.kind == "M" and l.equity == e and l.name.endswith("_base"))
                ok = [w for w, m, ls in grid if m >= -DD_LIMIT and all(x is None or x >= -DD_LIMIT for x in ls)]
                self.debug(f"[Q4 {e}] no candidate within limit -> hold auto execution | fallback max equity weight "
                           f"{max(ok) if ok else 'none'} | " + " ".join(f"{int(w * 100)}:{m:.0%}" for w, m, _ in grid))
                continue
            current = survivors[0]
            steps = []
            for nxt in survivors[1:]:
                d, lo, hi, n = logdiff_ci(daily(nxt), daily(current), Q4_CI_START, END_DATE, CI_Z)
                move = lo > 0
                steps.append(f"{nxt}-{current} {d:+.2%} [{lo:+.2%},{hi:+.2%}] n={n} -> {'move' if move else 'stay'}")
                if move:
                    current = nxt
            final[e], final_keys[e] = current, keys[current]
            self.debug(f"[Q4 {e}] survivors={','.join(survivors)} | " + " | ".join(steps or ["single"]) + f" => FINAL {current}")
            self.debug(f"[HIGH {e}] cost x2 logg " + " ".join(f"{k}={stats(daily(k, 'high'), cash)['loggrowth']:+.2%}" for k in keys)
                       + " | mdd " + " ".join(f"{k}={stats(daily(k, 'high'), cash)['mdd']:.1%}" for k in keys))
        if len(final) == 2:
            d, lo, hi, n = logdiff_ci(self.by_name[f"{final_keys['RSP']}_base"].daily,
                                      self.by_name[f"{final_keys['SPY']}_base"].daily, Q4_CI_START, END_DATE, CI_Z)
            pick = "RSP" if lo > 0 else "SPY"
            self.debug(f"[FINAL] RSP {final['RSP']} vs SPY {final['SPY']}: logg diff {d:+.2%} 90%CI [{lo:+.2%},{hi:+.2%}] "
                       f"n={n} -> {pick} {final[pick]} (rule: RSP only if CI > 0)")
        else:
            self.debug(f"[FINAL] finals={final or 'none'} -> " + (f"{list(final)[0]} {list(final.values())[0]}" if final else
                       "no candidate: hold auto execution (plan ch.10 fallback)"))
