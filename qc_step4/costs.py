# region imports
from AlgorithmImports import *
# endregion
# 4단계 거래비용(계획서 9장): 비용 = 브로커 수수료 + 반스프레드 (+ 슬리피지), 저·기본·고 시나리오 배수(config.COST_SCENARIOS).
# 반스프레드는 신호일까지의 원주가 일봉(고가·저가·종가)으로 추정한 직전 SPREAD_WINDOW거래일 평균이며 주문 전에 정해진다.
# LEAN에는 수수료 모형으로 넣는다(모든 주문 유형에 같은 방식으로 현금에서 빠짐). 체결가 자체는 공식 종가 그대로다.
import math
from collections import defaultdict

from config import *

CS_K = 3 - 2 * math.sqrt(2)


def abdi_ranaldo(highs, lows, closes):
    """Abdi–Ranaldo(2017) 월 추정치: S² = 4·평균[(c_t − η_t)(c_t − η_{t+1})], c = ln 종가, η = (ln 고가 + ln 저가)/2.
    음수면 0. 반환: 가격 대비 전체 스프레드(0.01 = 1%), 계산할 수 없으면 None."""
    terms = []
    for t in range(len(closes) - 1):
        c = math.log(closes[t])
        eta0 = (math.log(highs[t]) + math.log(lows[t])) / 2
        eta1 = (math.log(highs[t + 1]) + math.log(lows[t + 1])) / 2
        terms.append((c - eta0) * (c - eta1))
    if not terms:
        return None
    return math.sqrt(max(4 * sum(terms) / len(terms), 0.0))


def corwin_schultz(highs, lows):
    """Corwin–Schultz(2012) 2일 추정치의 평균(음수는 0, 야간 조정 없음). 비교 기록용."""
    values = []
    for t in range(len(highs) - 1):
        beta = math.log(highs[t] / lows[t]) ** 2 + math.log(highs[t + 1] / lows[t + 1]) ** 2
        gamma = math.log(max(highs[t], highs[t + 1]) / min(lows[t], lows[t + 1])) ** 2
        alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / CS_K - math.sqrt(gamma / CS_K)
        values.append(max(2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha)), 0.0))
    return sum(values) / len(values) if values else None


def daily_ohlcv(algo, symbols, bar_count, warn):
    """신호일까지의 원주가 일봉 bar_count개. {Symbol: [(고가, 저가, 종가, 거래량), ...]} 오래된 순.
    선택 함수 안에서 부르면 미래 봉은 오지 않는다(universe.raw_daily_bars와 같은 방식)."""
    if not symbols:
        return {}
    try:
        df = algo.history(list(symbols), bar_count, Resolution.DAILY,
                          data_normalization_mode=DataNormalizationMode.RAW)
    except Exception as err:
        warn("cost_history", f"cost history request failed: {err}")
        return {}
    need = ("high", "low", "close", "volume")
    if df is None or df.empty or any(k not in df.columns for k in need):
        return {}
    by_name = {}
    for s in symbols:
        for name in (str(s), s.value, str(s.id)):
            by_name.setdefault(name, s)
    bars = defaultdict(list)
    for index, h, l, c, v in zip(df.index, df["high"], df["low"], df["close"], df["volume"]):
        symbol = by_name.get(str(index[0]))
        if symbol is not None:
            bars[symbol].append((float(h), float(l), float(c), float(v)))
    return bars


class CostModel:
    """시나리오 배수와 종목별 반스프레드(가격 대비). update()는 리밸런싱 계획 때(신호일) 주문·보유 종목에 대해 부른다."""

    def __init__(self, algo, scenario, warn):
        self.algo, self.scenario, self.warn = algo, scenario, warn
        self.multiplier = COST_SCENARIOS[scenario]
        self.half = {}          # Symbol → 반스프레드(가격 대비), 마지막으로 추정한 값
        self.adv = {}           # Symbol → 직전 ADV_DAYS 평균 거래대금

    def update(self, symbols):
        """반환: 이번 추정 통계 dict(n, miss, floor, cap, ar_med, cs_med — bp는 반스프레드 기준)."""
        bars = daily_ohlcv(self.algo, symbols, SPREAD_WINDOW + 1, self.warn)
        stats = {"n": 0, "miss": 0, "floor": 0, "cap": 0}
        ars, css = [], []
        for s in symbols:
            rows = [r for r in bars.get(s, []) if r[0] > 0 and r[1] > 0 and r[2] > 0 and r[0] >= r[1]]
            if len(rows) < 3:
                stats["miss"] += 1
                continue
            highs, lows, closes = [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows]
            ar = abdi_ranaldo(highs, lows, closes)
            cs = corwin_schultz(highs, lows)
            if ar is None:
                stats["miss"] += 1
                continue
            half = ar / 2
            floor = TICK_SIZE / 2 / closes[-1]
            if half < floor:
                half, stats["floor"] = floor, stats["floor"] + 1
            if half > MAX_REL_SPREAD / 2:
                half, stats["cap"] = MAX_REL_SPREAD / 2, stats["cap"] + 1
            self.half[s] = half + SLIPPAGE
            recent = rows[-ADV_DAYS:]
            self.adv[s] = sum(r[2] * r[3] for r in recent) / len(recent)
            stats["n"] += 1
            ars.append(ar / 2)
            if cs is not None:
                css.append(cs / 2)
        stats["ar_med"] = median(ars) * 1e4 if ars else 0.0
        stats["cs_med"] = median(css) * 1e4 if css else 0.0
        return stats

    def half_spread(self, symbol):
        return self.half.get(symbol, DEFAULT_HALF_SPREAD)

    def spread_cost(self, symbol, quantity, price):
        """시나리오 배수를 곱한 반스프레드 비용(달러)."""
        return self.multiplier * self.half_spread(symbol) * abs(quantity) * price

    def adv_ratio(self, symbol, value):
        adv = self.adv.get(symbol)
        return value / adv if adv else None


def median(values):
    ordered = sorted(values)
    n = len(ordered)
    return (ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2) if n else 0.0


class SpreadFeeModel(FeeModel):
    """LEAN IB 수수료 + 반스프레드를 합쳐 시나리오 배수를 곱한 값을 주문 수수료로 낸다(계획서 9장 비용 모형)."""

    def __init__(self, cost_model):
        super().__init__()
        self._ib = InteractiveBrokersFeeModel()
        self._cost = cost_model

    def get_order_fee(self, parameters):
        commission = float(self._ib.get_order_fee(parameters).value.amount)
        security, order = parameters.security, parameters.order
        spread = self._cost.half_spread(security.symbol) * abs(float(order.absolute_quantity)) * float(security.price)
        return OrderFee(CashAmount(self._cost.multiplier * (commission + spread), "USD"))


class CostSecurityInitializer(BrokerageModelSecurityInitializer):
    """브로커 모형 초기화(IB·시드)를 그대로 하고 수수료 모형만 SpreadFeeModel로 바꾼다."""

    def __init__(self, brokerage_model, seeder, fee_model):
        super().__init__(brokerage_model, seeder)
        self._fee_model = fee_model

    def initialize(self, security):
        super().initialize(security)
        security.set_fee_model(self._fee_model)
