# region imports
from AlgorithmImports import *
# endregion
# 종목 구성·주문 계획(3단계): 계획서 6장 '구성'·'변동성 σ̂'·'소액 거래', 9장 체결 시간 규칙, 4장 제약(무차입·5% 상한)
import math
from collections import Counter, namedtuple

from config import *

# 신호일 종가 기준으로 정한 주문 한 건. quantity > 0 매수, < 0 매도. reason: buy / adjust / 매도 사유
Order = namedtuple("Order", "symbol quantity reason price")


def read_parameters(algo):
    """QC 프로젝트 파라미터 n_holdings·weighting·score·cost(사용자 결정: 결과 보기 전 동결된 시험 집합만 허용).
    score = 섹터 내/전역 점수(계획서 10장), cost = 저·기본·고 비용 시나리오(계획서 9장)."""
    n_text = algo.get_parameter("n_holdings", str(DEFAULT_N_HOLDINGS))
    text = lambda name, default: (algo.get_parameter(name, default) or default).strip().lower()
    weighting = text("weighting", DEFAULT_WEIGHTING)
    score = text("score", DEFAULT_SCORE_MODE)
    cost = text("cost", DEFAULT_COST_SCENARIO)
    try:
        n_holdings = int(str(n_text).strip() or DEFAULT_N_HOLDINGS)
    except ValueError:
        n_holdings = -1
    if (n_holdings not in N_HOLDINGS_CHOICES or weighting not in WEIGHTING_CHOICES or score not in SCORE_MODES
            or cost not in COST_SCENARIOS):
        raise ValueError(f"파라미터가 시험 집합 밖: n_holdings={n_text} (허용 {N_HOLDINGS_CHOICES}), "
                         f"weighting={weighting} (허용 {WEIGHTING_CHOICES}), score={score} (허용 {SCORE_MODES}), "
                         f"cost={cost} (허용 {tuple(COST_SCENARIOS)})")
    return n_holdings, weighting, score, cost


# ----------------------------------------------------------------------
# 변동성 σ̂ (계획서 6장: 일간 수익률 EWMA, 반감기 60거래일, 최근 252거래일, 최소 126개 관측)
# ----------------------------------------------------------------------
def sigma_hat(closes):
    """closes: 조정 종가 [(거래일, 종가), ...] 오래된 순. 최근 SIGMA_WINDOW개 일간 단순 수익률의 EWMA 표준편차
    (평균 0 가정, 최신 수익률 가중 1, k거래일 전 가중 0.5^(k/반감기)). 관측이 SIGMA_MIN_OBS 미만이거나 0이면 None."""
    prices = [c for _, c in closes][-(SIGMA_WINDOW + 1):]
    returns = [p1 / p0 - 1 for p0, p1 in zip(prices, prices[1:]) if p0 > 0]
    if len(returns) < SIGMA_MIN_OBS:
        return None
    decay = 0.5 ** (1 / SIGMA_HALF_LIFE)
    weights = [decay ** k for k in range(len(returns) - 1, -1, -1)]
    variance = sum(w * r * r for w, r in zip(weights, returns)) / sum(weights)
    return math.sqrt(variance) if variance > 0 else None


# ----------------------------------------------------------------------
# 보유 종목 선택 (계획서 6장 구성: 상위 40% 밖·유니버스 이탈은 매도, 빈자리는 상위 20%에서 점수순)
# ----------------------------------------------------------------------
class Selection:
    """kept: 유지, sells: {Symbol: 매도 사유}, added: 신규(점수순), empty: 채우지 못한 자리, novol: σ̂ 부족으로 뺀 수."""

    def __init__(self):
        self.kept, self.added, self.sells = [], [], {}
        self.empty = self.novol = 0

    @property
    def final(self):
        return self.kept + self.added


def z_ranking(z):
    """z 내림차순, 동점은 SID 문자열(계획서 14.4 동률 처리 고정)."""
    return sorted(z, key=lambda s: (-z[s], str(s.id)))


def select_holdings(holdings, members, month, n_holdings, sigmas, first):
    """holdings: 현재 보유 Symbol, members: 1단계 유니버스(상위 1,100 버퍼), month: 2단계 FactorMonth,
    sigmas: 역변동성일 때 {Symbol: σ̂ 또는 None}(동일가중이면 None), first: 첫 구성이면 z 상위 N.
    매도 사유: universe(유니버스 이탈) / 점수 결측 사유(mom·qual·value·expired·pit) / band(상위 40% 밖) / no_vol."""
    ranked = z_ranking(month.z)
    rank = {s: i + 1 for i, s in enumerate(ranked)}
    n_scored = len(ranked)
    has_vol = (lambda s: True) if sigmas is None else (lambda s: sigmas.get(s) is not None)
    selection = Selection()
    if first:
        for s in ranked:
            if len(selection.added) >= n_holdings:
                break
            if has_vol(s):
                selection.added.append(s)
            else:
                selection.novol += 1
    else:
        for h in sorted(holdings, key=lambda s: str(s.id)):
            if h not in members:
                selection.sells[h] = "universe"
            elif h not in month.z:
                fail = month.records.get(h, {}).get("fail") or ["noscore"]
                selection.sells[h] = fail[0]
            elif rank[h] > KEEP_TOP_FRACTION * n_scored:
                selection.sells[h] = "band"
            elif not has_vol(h):
                selection.sells[h] = "no_vol"
                selection.novol += 1
            else:
                selection.kept.append(h)
        slots = n_holdings - len(selection.kept)
        for s in ranked:
            if len(selection.added) >= slots or rank[s] > FILL_TOP_FRACTION * n_scored:
                break
            if s in holdings:
                continue
            if has_vol(s):
                selection.added.append(s)
            else:
                selection.novol += 1
    selection.empty = max(0, n_holdings - len(selection.final))
    return selection


# ----------------------------------------------------------------------
# 목표 비중 (계획서 6장 구성: 동일가중·역변동성, 4장: 매수 시점 5% 상한)
# ----------------------------------------------------------------------
def target_weights(final, weighting, sigmas, n_holdings):
    """자리당 몫 1/N 기준으로 보유 종목 몫 합 = 보유 수/N(빈자리는 현금). equal은 균등, invvol은 1/σ̂ 비례.
    이후 MAX_WEIGHT 상한을 적용. 반환: ({Symbol: 비중}, 상한 도달 종목 수)."""
    if not final:
        return {}, 0
    raw = {s: 1.0 if weighting == "equal" else 1.0 / sigmas[s] for s in final}
    total = len(final) / n_holdings
    norm = sum(raw.values())
    return cap_weights({s: total * v / norm for s, v in raw.items()})


def cap_weights(weights):
    """상한을 넘는 종목을 MAX_WEIGHT로 자르고 초과분을 상한 아래 종목에 비중 비례로 재분배, 넘는 종목이 없을 때까지 반복.
    모두 상한이면 남는 몫은 현금. 반환: (비중, 상한 도달 종목 수)."""
    weights = dict(weights)
    capped = set()
    while True:
        over = [s for s in weights if s not in capped and weights[s] > MAX_WEIGHT + 1e-12]
        if not over:
            break
        excess = sum(weights[s] - MAX_WEIGHT for s in over)
        for s in over:
            weights[s] = MAX_WEIGHT
            capped.add(s)
        free = [s for s in weights if s not in capped]
        base = sum(weights[s] for s in free)
        if base <= 0:
            break
        for s in free:
            weights[s] += excess * weights[s] / base
    return weights, len(capped)


# ----------------------------------------------------------------------
# 체결·보유 통계 (로그 문구는 diagnostics.Recorder가 만든다)
# ----------------------------------------------------------------------
class TradeBook:
    """연도별·전체 누적: 주문·체결 금액(회전율)·수수료·일별 보유 수·현금 비중·노출·생략·빈자리 등."""

    def __init__(self):
        self.years, self.total, self.submitted = [], Counter(), {}
        self.started = False             # 첫 체결 뒤부터 일별 통계를 쌓음
        self._year, self._c = None, None

    def counter(self, year):
        """그 연도의 누적 Counter와, 연도가 바뀌어 끝난 직전 연도 요약(없으면 None)."""
        finished = self.close_year() if self._year is not None and self._year != year else None
        if self._year is None:
            self._year, self._c = year, Counter()
        return self._c, finished

    def close_year(self):
        """진행 중인 연도를 끝내고 요약을 돌려준다. 편도 회전율 = Σ(체결 금액 / 체결 시점 가치) / 2."""
        if self._year is None:
            return None
        c, days = self._c, self._c["days"]
        avg_pv = c["pv_sum"] / days if days else 0.0
        year = {"year": self._year, "c": c, "turnover": c["traded"] / 2,
                "fee_pct": c["fees"] / avg_pv * 100 if avg_pv else 0.0,
                "spread_pct": c["spread"] / avg_pv * 100 if avg_pv else 0.0,
                "spread_bp": c["spread"] / c["traded_value"] * 1e4 if c["traded_value"] else 0.0,
                "hold": c["hold_sum"] / days if days else 0.0, "cash": c["cash_w_sum"] / days if days else 0.0}
        self.years.append(year)
        self._year = self._c = None
        return year

    def add_day(self, c, n_held, pv, cash):
        """거래일 하루(전날 체결 결과 기준). 반환: 노출 = (가치 − 현금) / 가치."""
        exposure = (pv - cash) / pv if pv > 0 else 0.0
        for acc in (c, self.total):
            acc["days"] += 1
            acc["hold_sum"] += n_held
            acc["cash_w_sum"] += cash / pv if pv > 0 else 0.0
        c["pv_sum"] += pv
        c["neg"] += cash < 0
        self.total["max_expo"] = max(self.total["max_expo"], exposure)
        return exposure

    def add_fill(self, c, value, pv, fee, spread=0.0, adv_ratio=None):
        """fee = 총비용(수수료 + 반스프레드, 시나리오 배수 포함), spread = 그중 반스프레드 몫."""
        self.started = True
        c["traded"] += value / pv if pv > 0 else 0.0
        c["traded_value"] += value
        c["fees"] += fee
        c["spread"] += spread
        if adv_ratio is not None:
            c["adv_max"] = max(c["adv_max"], adv_ratio)
            c["adv_over"] += adv_ratio > IMPACT_ADV_LIMIT

    def summary(self):
        """전체 기간 요약. 연평균 = 연도별 값의 평균(리밸런싱이나 체결이 있던 해만)."""
        years = [y for y in self.years if y["c"]["rebals"] or y["turnover"]]
        if not years:
            return None
        t = self.total
        total = lambda k: sum(y["c"][k] for y in years)
        return {"years": len(years), "turnover": sum(y["turnover"] for y in years) / len(years),
                "fee_pct": sum(y["fee_pct"] for y in years) / len(years),
                "spread_pct": sum(y["spread_pct"] for y in years) / len(years),
                "adv_max": max(y["c"]["adv_max"] for y in years), "adv_over": total("adv_over"),
                "skipped": total("skipped"),
                "neg": total("neg"), "rej": total("rej"), "late": total("late"),
                "hold": t["hold_sum"] / t["days"] if t["days"] else 0.0,
                "cash": t["cash_w_sum"] / t["days"] if t["days"] else 0.0, "max_expo": t["max_expo"]}


def performance(points):
    """첫 매매 이후 성과. points: [(날짜, 포트폴리오 가치, SPY 조정가), ...] 날짜순, 첫 점은 첫 체결 전날 종가(전액 현금).
    CAGR = (끝/처음)^(1/년) − 1, 년 = 달력일 / CALENDAR_DAYS_PER_YEAR. 일간 수익률 표본표준편차 × √252 = 연율 변동성,
    Sharpe = 평균/표준편차 × √252(무위험 0). 최대낙폭 = 일별 가치의 직전 고점 대비 최대 하락. 점이 3개 미만이면 None."""
    if len(points) < 3:
        return None
    dates = [p[0] for p in points]
    years = (dates[-1] - dates[0]).days / CALENDAR_DAYS_PER_YEAR
    result = {"start": dates[0], "end": dates[-1], "years": years}
    for key, values in (("p", [p[1] for p in points]), ("spy", [p[2] for p in points])):
        result[key + "_cagr"] = (values[-1] / values[0]) ** (1 / years) - 1 if years > 0 and values[0] > 0 else None
        result.update({key + "_" + k: v for k, v in drawdown(dates, values).items()})
    values = [p[1] for p in points]
    returns = [b / a - 1 for a, b in zip(values, values[1:])]
    mean = sum(returns) / len(returns)
    sd = math.sqrt(sum((r - mean) ** 2 for r in returns) / (len(returns) - 1))
    result["p_vol"] = sd * math.sqrt(TRADING_DAYS_PER_YEAR)
    result["p_sharpe"] = mean / sd * math.sqrt(TRADING_DAYS_PER_YEAR) if sd > 0 else None
    return result


def drawdown(dates, values):
    """최대낙폭(음수)과 그 고점·저점 날짜, 고점 가치를 다시 넘은 첫 날짜(없으면 None)."""
    peak, peak_date = values[0], dates[0]
    worst, worst_peak, worst_trough, worst_value = 0.0, dates[0], dates[0], values[0]
    for d, v in zip(dates, values):
        if v > peak:
            peak, peak_date = v, d
        if v / peak - 1 < worst:
            worst, worst_peak, worst_trough, worst_value = v / peak - 1, peak_date, d, peak
    recover = next((d for d, v in zip(dates, values) if d > worst_trough and v >= worst_value), None)
    return {"mdd": worst, "peak": worst_peak, "trough": worst_trough, "recover": recover}


# ----------------------------------------------------------------------
# 주문 계획 (계획서 9장: 신호일까지 알 수 있는 정보로 수량, 다음 거래일 MOC)
# ----------------------------------------------------------------------
class Plan:
    """한 번의 리밸런싱 계획. orders는 매도 먼저, 그다음 매수·조정."""

    def __init__(self, signal_date, exec_date, selection, weights, cap_hits, orders, stats, pv):
        self.signal_date, self.exec_date = signal_date, exec_date
        self.selection, self.weights, self.cap_hits = selection, weights, cap_hits
        self.orders, self.stats, self.pv = orders, stats, pv


def build_orders(weights, holdings, prices, pv, cash, sells):
    """weights: 목표 비중, holdings: {Symbol: 현재 수량}, prices: 신호일 종가(원주가), pv·cash: 신호일 종가 기준
    포트폴리오 가치·현금, sells: 매도 사유. 체결일 가격은 쓰지 않는다(계획서 9장).
    - 목표 수량 = floor(비중 × pv × (1 − CASH_BUFFER) / 신호일 종가) — 정수 주 내림
    - 목표에 없는 보유 종목은 전량 매도(금액과 무관하게 실행)
    - 신규 매수 금액(0주 포함)·조정 금액이 MIN_TRADE_VALUE 미만이면 생략(계획서 6장 소액 거래)
    - 못 산 금액(unbought) = Σ max(0, 목표 금액 − 실행 후 보유 금액)
    - 신호일 종가 기준 매수 총액이 (현금 + 매도 대금)을 넘으면 매수를 비례 축소(무차입)
    반환: (주문 목록, 통계 Counter: skipped·skipped_value·unbought·buy_scaled·no_price·werr_max·cash_weight)."""
    investable = pv * (1 - CASH_BUFFER)
    stats = Counter()
    sell_orders, buy_orders, post_value = [], [], {}
    for s in sorted(set(weights) | set(holdings), key=lambda s: str(s.id)):
        current = holdings.get(s, 0)
        price = prices.get(s) or 0.0
        if s not in weights:
            if current:
                sell_orders.append(Order(s, -current, sells.get(s, "exit"), price))
            continue
        if price <= 0:
            stats["no_price"] += 1
            continue
        target_value = weights[s] * investable
        target = math.floor(target_value / price)
        delta = target - current
        if current == 0 and target * price < MIN_TRADE_VALUE:      # 신규 매수 금액이 기준 미만(0주 포함) → 생략
            stats["skipped"] += 1
            stats["skipped_value"] += target_value
            delta = 0
        elif delta and abs(delta) * price < MIN_TRADE_VALUE:        # 조정 금액이 기준 미만 → 생략
            stats["skipped"] += 1
            stats["skipped_value"] += abs(delta) * price
            delta = 0
        stats["unbought"] += max(0.0, target_value - (current + delta) * price)   # 정수 주·생략으로 못 산 금액
        if delta < 0:
            sell_orders.append(Order(s, delta, "adjust", price))
        elif delta > 0:
            buy_orders.append(Order(s, delta, "buy" if current == 0 else "adjust", price))
        post_value[s] = (current + delta) * price
    proceeds = sum(-o.quantity * o.price for o in sell_orders)
    spend = sum(o.quantity * o.price for o in buy_orders)
    if spend > cash + proceeds and spend > 0:
        scale = max(0.0, (cash + proceeds) / spend)
        stats["buy_scaled"] += 1
        scaled = []
        for o in buy_orders:
            quantity = math.floor(o.quantity * scale)
            post_value[o.symbol] -= (o.quantity - quantity) * o.price
            if quantity > 0:
                scaled.append(o._replace(quantity=quantity))
        buy_orders = scaled
    if weights and pv > 0:
        stats["werr_max"] = max(abs(post_value.get(s, 0.0) / pv - w) for s, w in weights.items())
        stats["cash_weight"] = 1 - sum(post_value.values()) / pv
    return sell_orders + buy_orders, stats
