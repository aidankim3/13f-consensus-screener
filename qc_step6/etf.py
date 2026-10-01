# region imports
from AlgorithmImports import *
# endregion
# 6단계 가상 장부와 지표. ETF 보유는 조정 종가(배당 재투자) 기준 소수 주, 남는 돈은 현금 대용치(1개월 T-bill − 보수)로 굴린다.
# 리밸런싱: 월말 신호일 P까지의 정보로 목표 비중·수량을 정하고 다음 거래일 종가에 체결(계획서 9장 MOC). 비용은 4단계와 같은 식.
import math

from config import *


def abdi_ranaldo(highs, lows, closes):
    """Abdi–Ranaldo(2017) 스프레드 추정(가격 대비 전체 스프레드). 4단계 costs.py와 같은 식."""
    terms = []
    for t in range(len(closes) - 1):
        c = math.log(closes[t])
        eta0 = (math.log(highs[t]) + math.log(lows[t])) / 2
        eta1 = (math.log(highs[t + 1]) + math.log(lows[t + 1])) / 2
        terms.append((c - eta0) * (c - eta1))
    return math.sqrt(max(4 * sum(terms) / len(terms), 0.0)) if terms else None


def half_spread(bars):
    """bars: [(고가, 저가, 종가), ...] 신호일까지. 하한 tick/2/가격, 상한 MAX_REL_SPREAD/2, 없으면 기본값."""
    rows = [b for b in bars[-(SPREAD_WINDOW + 1):] if b[0] > 0 and b[1] > 0 and b[2] > 0 and b[0] >= b[1]]
    if len(rows) < 3:
        return DEFAULT_HALF_SPREAD
    ar = abdi_ranaldo([r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows])
    if ar is None:
        return DEFAULT_HALF_SPREAD
    return min(max(ar / 2, TICK_SIZE / 2 / rows[-1][2]), MAX_REL_SPREAD / 2)


def ewma_sigma(closes):
    """최근 SIGMA_WINDOW개 일간 수익률의 EWMA 표준편차(평균 0, 반감기 SIGMA_HALF_LIFE) × √252. 관측 부족이면 None."""
    prices = closes[-(SIGMA_WINDOW + 1):]
    rets = [b / a - 1 for a, b in zip(prices, prices[1:]) if a > 0]
    if len(rets) < SIGMA_MIN_OBS:
        return None
    decay = 0.5 ** (1 / SIGMA_HALF_LIFE)
    w = [decay ** k for k in range(len(rets) - 1, -1, -1)]
    var = sum(wi * r * r for wi, r in zip(w, rets)) / sum(w)
    return math.sqrt(var * TRADING_DAYS_PER_YEAR) if var > 0 else None


def ib_fee(shares, value):
    fee = IB_FEE_PER_SHARE * shares
    return IB_MIN_FEE if fee < IB_MIN_FEE else min(fee, IB_MAX_FEE_RATE * value)


class Ledger:
    """한 후보 × 비용 시나리오. shares: {티커: 소수 주(조정가 기준)}, cash: 현금 대용치 잔액."""

    def __init__(self, name, kind, equity, mult, weight=None):
        self.name, self.kind, self.equity, self.mult, self.weight = name, kind, equity, mult, weight
        self.shares, self.cash = {}, float(INITIAL_CASH)
        self.daily = []                     # [(날짜, 가치)]
        self.traded = self.costs = 0.0
        self.lever = []                     # A1·B의 월별 배수 L

    def value(self, prices):
        return self.cash + sum(q * prices[t] for t, q in self.shares.items())

    def targets(self, sigma):
        """목표 비중 {티커: w}. 나머지는 현금. sigma = 주식 ETF의 EWMA σ̂(연)."""
        e = self.equity
        if self.kind == "A0":
            return {e: 1.0}
        if self.kind == "M":
            return {e: self.weight}
        lev = min(1.0, SIGMA_TARGET / sigma) if sigma else 1.0
        self.lever.append(lev)
        if self.kind == "A1":
            return {e: lev}
        we, wb, wg = B_WEIGHTS
        return {e: we * lev, BOND_TICKER: wb, GOLD_TICKER: wg}

    def rebalance(self, weights, sig_prices, exec_prices, halves):
        """신호일 가격·가치로 수량을 정하고 체결일 종가로 체결. 매도 먼저, 매수가 현금을 넘으면 비례 축소(무차입)."""
        pv = self.value(sig_prices)
        orders = []
        for t in sorted(set(weights) | set(self.shares)):
            current = self.shares.get(t, 0.0) * sig_prices[t]
            delta = weights.get(t, 0.0) * pv - current
            if abs(delta) >= MIN_TRADE_VALUE or (t not in weights and current > 0):
                orders.append((t, delta / sig_prices[t]))
        sells = [(t, q) for t, q in orders if q < 0]
        buys = [(t, q) for t, q in orders if q > 0]
        for t, q in sells:
            q = max(q, -self.shares.get(t, 0.0))
            self._fill(t, q, exec_prices[t], halves.get(t, DEFAULT_HALF_SPREAD))
        spend = sum(q * exec_prices[t] for t, q in buys)
        scale = min(1.0, self.cash / spend) if spend > 0 else 1.0
        for t, q in buys:
            self._fill(t, q * max(scale, 0.0), exec_prices[t], halves.get(t, DEFAULT_HALF_SPREAD))

    def _fill(self, t, q, price, half):
        if not q:
            return
        value = abs(q) * price
        cost = self.mult * (ib_fee(abs(q), value) + half * value)
        self.shares[t] = self.shares.get(t, 0.0) + q
        if abs(self.shares[t]) < 1e-9:
            del self.shares[t]
        self.cash -= q * price + cost
        self.traded += value
        self.costs += cost


def month_end_series(daily):
    """[(날짜, 가치)] → [(YYYY-MM, 그 달 마지막 값)] 날짜순."""
    out = {}
    for d, v in daily:
        out[(d.year, d.month)] = v
    return [out[k] for k in sorted(out)]


def stats(daily, cash_daily):
    """개발 구간 지표. 월수익률(월말 → 월말), 초과수익 = 자기 현금 대용치 수익률 차감(계획서 10장)."""
    v = month_end_series(daily)
    c = month_end_series(cash_daily)
    r = [b / a - 1 for a, b in zip(v, v[1:])]
    rc = [b / a - 1 for a, b in zip(c, c[1:])]
    ex = [x - y for x, y in zip(r, rc)]
    n = len(r)
    mu, mue = sum(r) / n, sum(ex) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in r) / (n - 1))
    sde = math.sqrt(sum((x - mue) ** 2 for x in ex) / (n - 1))
    tail = sorted(ex)[:max(1, int(round(0.05 * n)))]
    cvar = sum(tail) / len(tail)
    peak, mdd = daily[0][1], 0.0
    for _, val in daily:
        peak = max(peak, val)
        mdd = min(mdd, val / peak - 1)
    years = (daily[-1][0] - daily[0][0]).days / 365.25
    return {"n": n, "cagr": (v[-1] / v[0]) ** (12 / n) - 1, "vol": sd * math.sqrt(12),
            "sharpe": mue / sde * math.sqrt(12) if sde > 0 else 0.0,
            "mdd": mdd, "mdd_sigma": abs(mdd) / (sde * math.sqrt(12)) if sde > 0 else 0.0,
            "cvar_sigma": cvar / sde if sde > 0 else 0.0,
            "loggrowth": 12 * sum(math.log(1 + x) for x in r) / n, "years": years}
