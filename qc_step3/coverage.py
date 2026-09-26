# region imports
from AlgorithmImports import *
# endregion
# 데이터 커버리지 점검 모드(COVERAGE_CHECK): 점검일에만 1단계 선별을 돌려 [COV] 로그를 남긴다. 전략 로직과 무관한 진단.
# 1단계 함수(universe.py)를 그대로 쓰고 팩터·주문은 하지 않는다. 핵심 줄·경고는 main이 만든 diagnostics.Recorder로.
from config import *
from universe import MonthScreen, buffer_members, choose_representatives, scan_securities, screen_stocks


def dollar_volume(f):
    """신호일 하루 거래대금: Fundamental.dollar_volume, 없으면 가격 × 거래량. NOTES.md [M] 확인 필요."""
    for getter in (lambda: f.dollar_volume, lambda: f.price * f.volume):
        try:
            value = float(getter())
        except (AttributeError, TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0.0


class CoverageCheck:
    """점검일(COVERAGE_MONTHS의 신호일)마다: 입력·재무 있음·1단계 적격 수, 재무 없는 종목의 거래대금 분포·상위 목록,
    알려진 대형주 목록의 입력 여부·재무 여부·적격 여부(탈락 사유)·적격 중 시총 순위."""

    def __init__(self, algo, recorder):
        self.algo, self.recorder = algo, recorder
        self.done = []

    def log_config(self):
        months = ",".join(f"{y}-{m:02d}" for y, m in COVERAGE_MONTHS)
        levels = "/".join(f"${v / 1e6:.0f}M" for v in COVERAGE_DV_LEVELS)
        self.recorder.key_log(f"[CONFIG] mode=coverage_check period={BACKTEST_START_DATE}~{BACKTEST_END_DATE} "
                              f"months={months} dv={levels} top={COVERAGE_TOP_N} tickers={len(COVERAGE_TICKERS)} "
                              f"factors=off orders=off rank=among_eligible")

    def run(self, fundamental, signal_date):
        """월말 신호일마다 불린다. 점검일이 아니면 아무것도 하지 않는다. 반환: LEAN 구독(없음)."""
        if (signal_date.year, signal_date.month) not in COVERAGE_MONTHS:
            return Universe.UNCHANGED
        records = list(fundamental)
        tag = f"[COV {signal_date}]"
        if not records:
            self.recorder.warn_once(f"cov_empty:{signal_date}", f"coverage check: empty data sig={signal_date}")
            return Universe.UNCHANGED
        wanted = [t for t in COVERAGE_TICKERS
                  if (signal_date.year, signal_date.month) >= COVERAGE_TICKER_FROM.get(t, (0, 0))]
        found = {f.symbol.value: f.symbol for f in records if f.symbol.value in wanted}
        # 1단계 선별(계획서 6장). 점검 종목을 prev로 넘겨 탈락 사유를 MonthScreen이 기록하게 한다
        screen = MonthScreen(set(found.values()))
        scan_securities(screen, records)
        representatives, _, _, _ = choose_representatives(self.algo, screen.candidates, self.recorder.warn_once)
        screen_stocks(screen, representatives, signal_date, self.recorder)
        ranked, rank, _ = buffer_members(screen.eligible, set())
        total = len(screen.present)
        with_fund = total - screen.funnel["no_fund"]
        cut = screen.eligible[ranked[ENTRY_RANK - 1]].mcap if len(ranked) >= ENTRY_RANK else 0.0
        # 재무 없는 종목(가격 ≥ MIN_PRICE)의 거래대금
        no_fund = sorted(((dollar_volume(f), f) for f in records if not f.has_fundamental_data and f.price >= MIN_PRICE),
                         key=lambda x: (-x[0], str(x[1].symbol.id)))
        levels = [sum(dv >= v for dv, _ in no_fund) for v in COVERAGE_DV_LEVELS]
        level_text = " ".join(f">=${v / 1e6:.0f}M:{n}" for v, n in zip(COVERAGE_DV_LEVELS, levels))
        self.algo.log(f"{tag} total={total} fund={with_fund} eligible={len(screen.eligible)} "
                      f"cut{ENTRY_RANK}=${cut / 1e9:.2f}B | no_fund(price>=${MIN_PRICE:.0f})={len(no_fund)} {level_text}")
        top = " ".join(f"{f.symbol.value}:${f.price:.0f}:{dv / 1e6:.0f}M" for dv, f in no_fund[:COVERAGE_TOP_N])
        self.algo.log(f"{tag} no_fund top{COVERAGE_TOP_N} (ticker:price:dollar_volume): {top or 'none'}")
        # 알려진 대형주: #순위(적격) / 1단계 탈락 사유 / no_fund / missing(입력에 없음)
        status = []
        for ticker in wanted:
            symbol = found.get(ticker)
            if symbol is None:
                status.append(f"{ticker}:missing")
            elif symbol in rank:
                status.append(f"{ticker}:#{rank[symbol]}")
            else:
                status.append(f"{ticker}:{screen.prev_reasons.get(symbol, 'unknown')}")
        half = (len(status) + 1) // 2
        for part, items in (("a", status[:half]), ("b", status[half:])):
            self.algo.log(f"{tag} check{part}: {' '.join(items)}")
        eligible_ok = sum(1 for s in found.values() if s in rank)
        missing = len(wanted) - len(found)
        self.done.append(signal_date)
        self._runtime(f"cov_{signal_date.year}{signal_date.month:02d}",
                      f"tot={total} fund={with_fund} elig={len(screen.eligible)} nf20M={levels[1]} "
                      f"ok={eligible_ok}/{len(wanted)} miss={missing}")
        return []

    def finish(self):
        self.recorder.key_log(f"[COV] done checkpoints={len(self.done)} "
                              f"({','.join(str(d) for d in self.done) or 'none'}) — factors/orders off")

    def _runtime(self, key, value):
        try:
            self.algo.set_runtime_statistic(key, value)
        except Exception as err:
            self.recorder.warn_once("runtime_stat", f"set_runtime_statistic failed: {err}")
