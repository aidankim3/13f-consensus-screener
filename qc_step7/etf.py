# region imports
from AlgorithmImports import *
# endregion
# 7단계(최종 평가) 가상 장부와 지표. 6단계 etf.py에서 운용안 E 제거, 구간별 지표·로그 성장률 차 CI 추가. ETF 보유는 조정 종가(배당 재투자) 기준 소수 주, 남는 돈은 현금 대용치(1개월 T-bill − 보수)로 굴린다.
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

    def targets(self, sigma, recession=False):
        """목표 비중 {티커: w}. 나머지는 현금. sigma = 주식 ETF의 EWMA σ̂(연), recession = A2 침체 판정."""
        e = self.equity
        if self.kind == "A2":
            self.lever.append(1.0 if recession else 0.0)       # A2는 침체 판정 기록(1 = 침체)
            if not recession:
                return {e: 1.0}
            return {(e if k == "equity" else k): w for k, w in A2_RECESSION_WEIGHTS.items()}
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


def window_mdd(daily, start, end):
    """위기 재현 손실: start~end 안의 일별 가치만으로 계산한 최대 낙폭(구간 안 고점 대비). 구간에 자료가 없으면 None."""
    values = [v for d, v in daily if start <= d <= end]
    if len(values) < 2:
        return None
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst


def month_end_series(daily):
    """[(날짜, 가치)] → [((연, 월), 그 달 마지막 날짜, 값)] 날짜순."""
    out = {}
    for d, v in daily:
        out[(d.year, d.month)] = (d, v)
    return [(k, out[k][0], out[k][1]) for k in sorted(out)]


def _in(k, start, end):
    return (start is None or k >= (start.year, start.month)) and (end is None or k <= (end.year, end.month))


def nw_se(x):
    """월 평균의 Newey–West 표준오차(월 단위). 시차 = floor(4·(T/100)^(2/9)), Bartlett 가중(계획서 10장)."""
    t = len(x)
    if t < 2:
        return float("nan")
    mu = sum(x) / t
    d = [v - mu for v in x]
    lag = int(4 * (t / 100) ** (2 / 9))
    s = sum(v * v for v in d) / t
    for k in range(1, lag + 1):
        s += 2 * (1 - k / (lag + 1)) * sum(d[i] * d[i - k] for i in range(k, t)) / t
    return math.sqrt(max(s, 0.0) / t)


def logdiff_ci(daily_a, daily_b, start=None, end=None, z=1.645):
    """월 달러 로그수익률 차(a − b) 평균의 연율과 90% CI(Newey–West). 반환 (차, 하한, 상한, 개월 수)."""
    va, vb = month_end_series(daily_a), month_end_series(daily_b)
    ra = {k1: math.log(y / x) for (k0, _, x), (k1, _, y) in zip(va, va[1:]) if _in(k1, start, end)}
    rb = {k1: math.log(y / x) for (k0, _, x), (k1, _, y) in zip(vb, vb[1:]) if _in(k1, start, end)}
    diff = [ra[k] - rb[k] for k in sorted(set(ra) & set(rb))]
    if len(diff) < 2:
        return float("nan"), float("nan"), float("nan"), len(diff)
    m, se = 12 * sum(diff) / len(diff), 12 * nw_se(diff)
    return m, m - z * se, m + z * se, len(diff)


def stats(daily, cash_daily, start=None, end=None):
    """월수익률(월말 → 월말) 지표. start·end를 주면 끝나는 달이 그 구간 안인 월수익률만, MDD는 구간 직전 월말부터의 일별 가치.
    초과수익 = 자기 현금 대용치 수익률 차감(계획서 10장)."""
    v = month_end_series(daily)
    c = {k: x for k, _, x in month_end_series(cash_daily)}
    rows = [(k0, d0, a, k1, b) for (k0, d0, a), (k1, _, b) in zip(v, v[1:]) if _in(k1, start, end) and k0 in c and k1 in c]
    n = len(rows)
    if n < 3:
        return None
    r = [b / a - 1 for _, _, a, _, b in rows]
    rc = [c[k1] / c[k0] - 1 for k0, _, _, k1, _ in rows]
    ex = [x - y for x, y in zip(r, rc)]
    mu, mue = sum(r) / n, sum(ex) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in r) / (n - 1))
    sde = math.sqrt(sum((x - mue) ** 2 for x in ex) / (n - 1))
    tail = sorted(ex)[:max(1, int(round(0.05 * n)))]
    cvar = sum(tail) / len(tail)
    first_day = rows[0][1]
    last_day = end if end is not None else daily[-1][0]
    window = [(d, x) for d, x in daily if first_day <= d <= last_day]
    peak, mdd = window[0][1], 0.0
    for _, val in window:
        peak = max(peak, val)
        mdd = min(mdd, val / peak - 1)
    years = (window[-1][0] - window[0][0]).days / 365.25
    growth = 1.0
    for x in r:
        growth *= 1 + x
    return {"n": n, "cagr": growth ** (12 / n) - 1, "vol": sd * math.sqrt(12),
            "sharpe": mue / sde * math.sqrt(12) if sde > 0 else 0.0,
            "mdd": mdd, "mdd_sigma": abs(mdd) / (sde * math.sqrt(12)) if sde > 0 else 0.0,
            "cvar_sigma": cvar / sde if sde > 0 else 0.0,
            "loggrowth": 12 * sum(math.log(1 + x) for x in r) / n, "years": years}
