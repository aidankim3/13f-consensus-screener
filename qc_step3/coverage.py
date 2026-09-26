# region imports
from AlgorithmImports import *
# endregion
# 데이터 커버리지 점검 모드(COVERAGE_CHECK): 점검일에만 1단계 선별을 돌려 [COV] 로그를 남긴다. 전략 로직과 무관한 진단.
# 1단계 함수(universe.py)를 그대로 쓰고 팩터·주문은 하지 않는다. 핵심 줄·경고는 main이 만든 diagnostics.Recorder로.
from config import *
from universe import (MonthScreen, buffer_members, choose_representatives, months_between, scan_securities,
                      screen_stocks, stock_reason, to_date)


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


def month_text(day):
    return f"{day.year}-{day.month:02d}" if day else "none"


class CoverageCheck:
    """점검일(COVERAGE_MONTHS의 신호일)마다: 입력·재무 있음·1단계 적격 수, 재무 없는 종목의 거래대금 분포·상위 목록,
    알려진 대형주 목록의 입력 여부·재무 여부·적격 여부(탈락 사유)·적격 중 시총 순위,
    탈락 사유 분포·적격 시총 분포, 상장일 모순(listing), 시총 결측(mcap). 끝에 재무 누락 종목의 생존율."""

    def __init__(self, algo, recorder):
        self.algo, self.recorder = algo, recorder
        self.done = []
        self.cohorts = []           # (신호일, {그룹 이름: Symbol 집합}) — 생존율 비교용
        self.last_present = None    # 마지막 점검일 입력 Symbol 집합
        self.last_fund = None       # 마지막 점검일 재무 있는 Symbol 집합

    def log_config(self):
        months = ",".join(f"{y}-{m:02d}" for y, m in COVERAGE_MONTHS)
        levels = "/".join(f"${v / 1e6:.0f}M" for v in COVERAGE_DV_LEVELS)
        self.recorder.key_log(f"[CONFIG] mode=coverage_check period={BACKTEST_START_DATE}~{BACKTEST_END_DATE} "
                              f"months={months} dv={levels} top={COVERAGE_TOP_N} tickers={len(COVERAGE_TICKERS)} "
                              f"etf_list={len(COVERAGE_KNOWN_ETFS)} surv_dv=${COVERAGE_SURVIVAL_DV / 1e6:.0f}M "
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
        dv = {f.symbol: dollar_volume(f) for f in records}
        # 재무 없는 종목(가격 ≥ MIN_PRICE)의 거래대금
        no_fund = sorted(((dv[f.symbol], f) for f in records if not f.has_fundamental_data and f.price >= MIN_PRICE),
                         key=lambda x: (-x[0], str(x[1].symbol.id)))
        levels = [sum(v >= level for v, _ in no_fund) for level in COVERAGE_DV_LEVELS]
        level_text = " ".join(f">=${v / 1e6:.0f}M:{n}" for v, n in zip(COVERAGE_DV_LEVELS, levels))
        self.algo.log(f"{tag} total={total} fund={with_fund} eligible={len(screen.eligible)} "
                      f"cut{ENTRY_RANK}=${cut / 1e9:.2f}B | no_fund(price>=${MIN_PRICE:.0f})={len(no_fund)} {level_text}")
        # 알려진 ETF를 뺀 재무 없는 종목(재무 누락 의심 기업) 거래대금 상위
        no_fund_stock = [(v, f) for v, f in no_fund if f.symbol.value not in COVERAGE_KNOWN_ETFS]
        top = " ".join(f"{f.symbol.value}:${f.price:.0f}:{v / 1e6:.0f}M" for v, f in no_fund_stock[:COVERAGE_TOP_N])
        stock_levels = " ".join(f">=${level / 1e6:.0f}M:{sum(v >= level for v, _ in no_fund_stock)}"
                                for level in COVERAGE_DV_LEVELS[1:])
        self.algo.log(f"{tag} no_fund ex-ETF-list={len(no_fund_stock)} (listed ETFs={len(no_fund) - len(no_fund_stock)}) "
                      f"{stock_levels} top{COVERAGE_TOP_N}: {top or 'none'}")
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
        self._log_funnel(tag, screen)
        self._log_listing_mcap(tag, screen, representatives, signal_date, cut, dv)
        self._store_cohorts(signal_date, records, screen, ranked, dv)
        eligible_ok = sum(1 for s in found.values() if s in rank)
        missing = len(wanted) - len(found)
        self.done.append(signal_date)
        self._runtime(f"cov_{signal_date.year}{signal_date.month:02d}",
                      f"tot={total} fund={with_fund} elig={len(screen.eligible)} nf20M={levels[1]} "
                      f"ok={eligible_ok}/{len(wanted)} miss={missing}")
        return []

    def _log_funnel(self, tag, screen):
        """1단계 탈락 사유 전체 분포(많은 순)와 적격 종목의 시총 구간별 수."""
        reasons = " ".join(f"{k}={n}" for k, n in screen.funnel.most_common() if k != "eligible")
        mcaps = [c.mcap for c in screen.eligible.values()]
        buckets = " ".join(f">=${level / 1e9:g}B:{sum(m >= level for m in mcaps)}" for level in COVERAGE_MCAP_LEVELS)
        self.algo.log(f"{tag} funnel: {reasons} | eligible mcap {buckets}")

    def _log_listing_mcap(self, tag, screen, representatives, signal_date, cut, dv):
        """상장 24개월 조건(listing, Morningstar ipo_date 경로) 탈락을 세 갈래로 나눈다.
          future   : ipo_date가 신호일보다 뒤(당시 존재할 수 없는 날짜 → 현재 시점 값으로 덮어써진 것으로 의심)
          conflict : ipo_date는 신호일 전이지만, LEAN 최초 거래일(SID 날짜)로는 이미 24개월 이상 거래
          recent   : 둘 다 24개월 미만(규칙대로의 탈락)
        future·conflict 중 시총이 cut900 이상인 수(고치면 진입 후보)와 시총 상위를 보인다.
        시총 결측(mcap) 탈락은 거래대금 상위를 보인다."""
        counts = {"future": 0, "conflict": 0, "recent": 0}
        suspect, mcap_missing = [], []
        for f, _ in screen.candidates:
            if f.symbol not in representatives:
                continue
            reason = stock_reason(f, signal_date)[0]
            if reason == "mcap":
                mcap_missing.append((dv.get(f.symbol, 0.0), f))
            if reason != "listing":
                continue
            ipo = to_date(f.security_reference.ipo_date)
            first_trade = to_date(f.symbol.id.date)
            if ipo is not None and ipo > signal_date:
                kind = "future"
            elif first_trade is not None and months_between(min(first_trade, signal_date), signal_date) >= MIN_LISTING_MONTHS:
                kind = "conflict"
            else:
                kind = "recent"
            counts[kind] += 1
            if kind != "recent":
                suspect.append((float(f.market_cap or 0.0), f, ipo, first_trade))
        suspect.sort(key=lambda x: (-x[0], str(x[1].symbol.id)))
        enter = sum(m >= cut for m, _, _, _ in suspect) if cut > 0 else len(suspect)
        top = " ".join(f"{f.symbol.value}:ipo{month_text(ipo)}:sid{month_text(sid)}:${m / 1e9:.1f}B"
                       for m, f, ipo, sid in suspect[:COVERAGE_DETAIL_TOP_N])
        self.algo.log(f"{tag} listing future={counts['future']} conflict={counts['conflict']} recent={counts['recent']} "
                      f"suspect>=cut{ENTRY_RANK}={enter} top: {top or 'none'}")
        mcap_missing.sort(key=lambda x: (-x[0], str(x[1].symbol.id)))
        top = " ".join(f"{f.symbol.value}:${f.price:.0f}:{v / 1e6:.0f}M" for v, f in mcap_missing[:COVERAGE_DETAIL_TOP_N])
        self.algo.log(f"{tag} mcap_missing={len(mcap_missing)} top(dv): {top or 'none'}")

    def _store_cohorts(self, signal_date, records, screen, ranked, dv):
        """생존율 비교 집단(가격 ≥ $5, 거래대금 ≥ COVERAGE_SURVIVAL_DV):
        fund = 재무 있는 보통주 후보(증권 단위 조건 통과), top900 = 적격 시총 상위 ENTRY_RANK,
        no_fund = 재무 없음(알려진 ETF 제외). 마지막 점검일 입력에 남아 있으면 생존으로 본다."""
        def liquid(f):
            return f.price >= MIN_PRICE and dv.get(f.symbol, 0.0) >= COVERAGE_SURVIVAL_DV
        groups = {
            "fund": {f.symbol for f, _ in screen.candidates if liquid(f)},
            f"top{ENTRY_RANK}": set(ranked[:ENTRY_RANK]),
            "no_fund": {f.symbol for f in records if not f.has_fundamental_data and liquid(f)
                        and f.symbol.value not in COVERAGE_KNOWN_ETFS},
        }
        self.cohorts.append((signal_date, groups))
        self.last_present = set(screen.present)
        self.last_fund = {f.symbol for f in records if f.has_fundamental_data}

    def _log_survival(self):
        """점검일별 집단이 마지막 점검일까지 남은 비율. no_fund가 fund보다 크게 낮으면 재무 누락이
        이후 사라진 회사에 몰린 것(생존편향). later_fund = 살아남은 no_fund 중 마지막 점검일에 재무가 있는 수."""
        if len(self.cohorts) < 2 or self.last_present is None:
            return
        last_date = self.cohorts[-1][0]
        for signal_date, groups in self.cohorts[:-1]:
            parts = []
            for name, symbols in groups.items():
                alive = symbols & self.last_present
                share = 100.0 * len(alive) / len(symbols) if symbols else 0.0
                extra = f" later_fund={len(alive & self.last_fund)}" if name == "no_fund" else ""
                parts.append(f"{name} n={len(symbols)} surv={share:.0f}%{extra}")
            self.algo.log(f"[COV survival {month_text(signal_date)}->{month_text(last_date)}] " + " | ".join(parts))

    def finish(self):
        self._log_survival()
        self.recorder.key_log(f"[COV] done checkpoints={len(self.done)} "
                              f"({','.join(str(d) for d in self.done) or 'none'}) — factors/orders off")

    def _runtime(self, key, value):
        try:
            self.algo.set_runtime_statistic(key, value)
        except Exception as err:
            self.recorder.warn_once("runtime_stat", f"set_runtime_statistic failed: {err}")
