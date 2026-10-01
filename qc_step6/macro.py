# region imports
from AlgorithmImports import *
# endregion
# A2 경기 국면 신호(사용자 확정 2026-10-01, NOTES.md). FRED 값은 QC에서 '관측 날짜 + 1일'에 들어오고 최종 수정값이므로
# 월별 지표는 신호월 M에서 관측월 ≤ M−1(전달 값, 실제 발표는 M 초)만, 일별 지표는 신호일까지만 쓴다(미래 정보 차단).
from datetime import date, timedelta

from config import *


def month_key(d):
    return (d.year, d.month)


class MacroSignals:
    def __init__(self):
        self.obs = {name: {} for name in FRED_SERIES}          # {이름: {관측일: 값}}
        self.month_close = {}                                  # {티커: {(연,월): 월말 조정 종가}}
        self.rows = []                                         # 판정 기록 [(월, econ, sahm, trend, credit, price, usrec)]

    def add(self, name, obs_time, value):
        """obs_time: QC가 넘긴 관측 시각. 관측일 0시(UTC)가 뉴욕 시간으로 바뀌면 전날 19~20시가 되므로(2026-10-01 실행에서
        USREC 날짜가 하나도 맞지 않아 확인) 12시간을 더해 원래 관측일로 되돌린다. 0시 그대로 와도 같은 날짜가 된다."""
        self.obs[name][(obs_time + timedelta(hours=12)).date()] = value

    def add_month_close(self, ticker, d, close):
        self.month_close.setdefault(ticker, {})[month_key(d)] = close

    def _monthly(self, name, signal):
        """관측월 ≤ 신호월 − 1인 월별 값(오래된 순)."""
        limit = month_key(signal)
        items = sorted((month_key(d), v) for d, v in self.obs[name].items() if month_key(d) < limit)
        return [v for _, v in items]

    def _daily_at(self, name, day):
        keys = [d for d in self.obs[name] if d <= day]
        return self.obs[name][max(keys)] if keys else None

    def econ(self, signal):
        """(실업률 > 12개월 평균, Sahm 신호). 자료가 모자라면 (None, None)."""
        u = self._monthly("UNRATE", signal)
        if len(u) < UNRATE_SMA_MONTHS:
            return None, None
        trend = u[-1] > sum(u[-UNRATE_SMA_MONTHS:]) / UNRATE_SMA_MONTHS
        avg3 = [sum(u[i - 2:i + 1]) / 3 for i in range(2, len(u))]
        sahm = None
        if len(avg3) >= SAHM_LOOKBACK + 1:
            sahm = avg3[-1] - min(avg3[-SAHM_LOOKBACK - 1:-1]) >= SAHM_THRESHOLD
        return trend, sahm

    def credit(self, signal):
        """BAA − 10년 국채 스프레드가 6개월 전보다 CREDIT_WIDEN 이상 넓어졌는지(신호일까지 관측)."""
        now = self._daily_at("BAA10Y", signal)
        past = self._daily_at("BAA10Y", signal - timedelta(days=CREDIT_LOOKBACK_DAYS))
        if now is None or past is None:
            return None
        return now - past >= CREDIT_WIDEN

    def price_down(self, ticker, signal):
        """월말 조정 종가가 최근 PRICE_SMA_MONTHS개 월말(신호월 포함) 평균 아래인지."""
        closes = self.month_close.get(ticker, {})
        keys = sorted(k for k in closes if k <= month_key(signal))[-PRICE_SMA_MONTHS:]
        if len(keys) < PRICE_SMA_MONTHS:
            return None
        values = [closes[k] for k in keys]
        return values[-1] < sum(values) / len(values)

    def regime(self, ticker, signal, variant):
        """True = 침체(방어), False = 확장. variant a: 경기(실업률 추세 또는 Sahm) 그리고 가격, b: a의 경기 신호에 신용 확대 추가."""
        trend, sahm = self.econ(signal)
        econ = bool(trend) or bool(sahm)
        if variant == "b":
            econ = econ or bool(self.credit(signal))
        down = self.price_down(ticker, signal)
        return bool(econ and down)

    def record(self, signal):
        """탐지 정확도용: 신호월의 각 신호 상태와 NBER 침체 여부(USREC, 사후 확정 값 — 평가에만 사용)."""
        trend, sahm = self.econ(signal)
        usrec = next((v for d, v in self.obs["USREC"].items() if month_key(d) == month_key(signal)), None)
        self.rows.append((month_key(signal), trend, sahm, self.credit(signal), self.price_down(DETECT_PRICE, signal), usrec))

    def first_dates(self):
        """날짜 보정 확인용: 시리즈별 첫 관측일(월별 시리즈는 1일이어야 정상)."""
        return " ".join(f"{n}={min(v) if v else 'none'}" for n, v in self.obs.items())

    def detection_report(self):
        """신호별: 침체 월 적중률, 비침체 월 오신호율, 침체 에피소드별 첫 신호 지연(개월)."""
        rows = [r for r in self.rows if r[5] is not None and r[1] is not None]
        if not rows:
            return ["no detection rows (USREC/UNRATE missing)"]
        signals = {
            "trend": lambda r: bool(r[1]), "sahm": lambda r: bool(r[2]), "credit": lambda r: bool(r[3]),
            "price": lambda r: bool(r[4]),
            "A2a": lambda r: (bool(r[1]) or bool(r[2])) and bool(r[4]),
            "A2b": lambda r: (bool(r[1]) or bool(r[2]) or bool(r[3])) and bool(r[4]),
        }
        episodes, start = [], None
        for i, r in enumerate(rows):
            if r[5] and start is None:
                start = i
            if not r[5] and start is not None:
                episodes.append((start, i - 1))
                start = None
        if start is not None:
            episodes.append((start, len(rows) - 1))
        rec = sum(1 for r in rows if r[5])
        lines = [f"months={len(rows)} {rows[0][0]}~{rows[-1][0]} recession_months={rec} episodes=" +
                 ",".join(f"{rows[a][0][0]}-{rows[a][0][1]:02d}~{rows[b][0][0]}-{rows[b][0][1]:02d}" for a, b in episodes)]
        for name, f in signals.items():
            hit = sum(1 for r in rows if r[5] and f(r))
            false = sum(1 for r in rows if not r[5] and f(r))
            delays = []
            for a, b in episodes:
                first = next((i for i in range(max(0, a - 12), len(rows)) if f(rows[i]) and i >= a - 12), None)
                delays.append("miss" if first is None or first > b + 6 else str(first - a))
            lines.append(f"{name}: hit={hit}/{rec} false={false}/{len(rows) - rec} delay(mo)={','.join(delays)}")
        return lines
