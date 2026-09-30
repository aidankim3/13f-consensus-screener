# region imports
from AlgorithmImports import *
# endregion
# 팩터 점수(계획서 6장): 재무 스냅샷, 공시 시점·만료, TTM, 모멘텀·퀄리티·가치 지표, 섹터 내 순위 점수, z
import math
from collections import Counter, defaultdict, namedtuple
from datetime import datetime, timedelta

from config import *
from universe import filing_usable, to_date

# 월별 신호일에 본 종목의 최신 공시 한 건. flows3·flows12: FLOW_FIELDS 키별 분기·연간 값, ta·tl·eq: 시점 항목
Snapshot = namedtuple("Snapshot", "file_date period_end flows3 flows12 ta tl eq")

QUALITY_KEYS = ("gp_ta", "ni_ta", "tl_ta")
VALUE_KEYS = ("ep", "bp", "fcfp", "sp")
REASONS = ("mom", "qual", "value", "expired", "pit")


class FactorMonth:
    """한 달 팩터 결과. records: 유니버스 종목별 지표·제외 사유, z: 점수 산출 종목의 최종 z."""

    def __init__(self, signal_date):
        self.signal_date = signal_date
        self.records = {}
        self.z = {}
        self.style = {}          # 5단계 단일 팩터 기준선용: {Symbol: (모멘텀, 퀄리티, 가치) 스타일 점수}
        self.reasons = Counter()
        self.ttm = Counter()
        self.checks = Counter()
        self.merges = []
        self.z_mean = self.z_sd = 0.0


# ----------------------------------------------------------------------
# 재무 스냅샷 (계획서 6장 '재무 시점', 8장 시점 기준)
# ----------------------------------------------------------------------
class FundamentalHistory:
    """Symbol별 재무 스냅샷 저장소. 매월 신호일에 본 최신 공시를 쌓아 두고, 신호일마다 '사용 가능한 공시 중
    가장 최근 것'을 고른다. 월 사이에 나왔다가 대체된 공시는 놓칠 수 있다(NOTES.md)."""

    def __init__(self):
        self._rows = defaultdict(list)

    def record(self, symbol, snapshot, signal_date):
        rows = self._rows[symbol]
        if any(r.file_date == snapshot.file_date and r.period_end == snapshot.period_end for r in rows):
            return
        cutoff = signal_date - timedelta(days=SNAPSHOT_KEEP_DAYS)
        self._rows[symbol] = [r for r in rows if time_key(r) >= cutoff] + [snapshot]

    def rows(self, symbol):
        return self._rows.get(symbol, [])


def record_snapshots(history, screen, signal_date, warn):
    """적격 종목 전체의 이번 달 스냅샷 저장(유니버스 진입 전 이력도 TTM·평균 총자산에 쓰도록)."""
    for f, _ in screen.candidates:
        if f.symbol in screen.eligible:
            snapshot = take_snapshot(f, warn)
            if snapshot is not None:
                history.record(f.symbol, snapshot, signal_date)


def take_snapshot(f, warn):
    """Fundamental에서 공시일·기간 종료일·원 항목을 읽는다. 공시일이 없으면 None. NOTES.md [J]."""
    statements = f.financial_statements
    file_date = to_date(read_field(statements, "file_date", warn))
    if file_date is None:
        return None
    period_end = to_date(read_field(statements, PERIOD_END_FIELD, warn))
    flows3, flows12 = {}, {}
    for key, path in FLOW_FIELDS.items():
        field = read_field(statements, path, warn)
        flows3[key] = period_value(field, "three_months")
        flows12[key] = period_value(field, "twelve_months")
    balance = {}
    for key, path in BALANCE_FIELDS.items():
        field = read_field(statements, path, warn)
        value = period_value(field, "three_months")
        balance[key] = value if value is not None else period_value(field, "twelve_months")
    return Snapshot(file_date, period_end, flows3, flows12, balance["ta"], balance["tl"], balance["eq"])


def read_field(root, path, warn):
    """점으로 이은 속성 경로를 읽는다. 속성이 없으면 한 번 경고하고 None(알고리즘을 멈추지 않음)."""
    obj = root
    try:
        for name in path.split("."):
            obj = getattr(obj, name)
    except AttributeError:
        warn("field:" + path, f"field missing: financial_statements.{path}")
        return None
    return obj


def period_value(field, period):
    """다기간 필드의 한 기간 값. 없거나 NaN이면 None. 결측이 0으로 오는지는 NOTES.md [J] 확인 필요."""
    if field is None:
        return None
    try:
        value = float(getattr(field, period, None))
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else value


def time_key(snapshot):
    """스냅샷의 시점: 기간 종료일, 없으면 공시일."""
    return snapshot.period_end or snapshot.file_date


def financial_state(history, symbol, signal_date, calendar):
    """신호일에 쓸 재무 상태. 반환: (상태, 최신 사용 가능 스냅샷, 사용 가능 스냅샷 목록)
      "ok"      : 공시 다음 거래일 규칙을 통과한 공시가 있고 180일 이내
      "expired" : 사용 가능한 마지막 공시가 FILING_EXPIRY_DAYS 초과(계획서 6장 만료)
      "pit"     : 공시는 있으나 아직 사용 불가(공시 다음 거래일 전)
      "none"    : 저장된 공시 없음"""
    rows = history.rows(symbol)
    if not rows:
        return "none", None, []
    usable = [r for r in rows if filing_usable(calendar, r.file_date, signal_date)]
    if not usable:
        return "pit", None, []
    latest = max(usable, key=lambda r: (r.file_date, time_key(r)))
    if (signal_date - latest.file_date).days > FILING_EXPIRY_DAYS:
        return "expired", latest, usable
    return "ok", latest, usable


# ----------------------------------------------------------------------
# TTM·지표 (계획서 6장 퀄리티·가치)
# ----------------------------------------------------------------------
def ttm_values(latest, usable):
    """TTM 흐름 값. 반환: (방식, {키: 값})
      "q4"    : 최신 공시부터 연속 4개 분기(기간 종료일 간격 QUARTER_GAP_MIN~MAX일)의 three_months 합.
                FLOW_FIELDS 전 항목이 네 분기 모두 있을 때만.
      "ttm12" : 그렇지 않으면 최신 공시의 twelve_months(연간 값으로 보임 — NOTES.md [J]).
      "none"  : twelve_months도 모두 없음."""
    chain = []
    if latest.period_end is not None:
        by_period = {}
        for r in usable:
            if r.period_end is not None and r.period_end <= latest.period_end:
                if r.period_end not in by_period or r.file_date > by_period[r.period_end].file_date:
                    by_period[r.period_end] = r
        for period in sorted(by_period, reverse=True):
            if not chain:
                if period != latest.period_end:
                    break
            else:
                gap = (chain[-1].period_end - period).days
                if not QUARTER_GAP_MIN_DAYS <= gap <= QUARTER_GAP_MAX_DAYS:
                    break
            chain.append(by_period[period])
            if len(chain) == TTM_QUARTERS:
                break
    if len(chain) == TTM_QUARTERS:
        sums = {}
        for key in FLOW_FIELDS:
            values = [r.flows3.get(key) for r in chain]
            if any(v is None for v in values):
                break
            sums[key] = sum(values)
        else:
            return "q4", sums
    flows = {key: latest.flows12.get(key) for key in FLOW_FIELDS}
    return ("ttm12" if any(v is not None for v in flows.values()) else "none"), flows


def average_assets(latest, usable):
    """평균 총자산 = (최신 공시 총자산 + 1년 전 공시 총자산) / 2. 1년 전 공시는 최신 공시 기간 종료일에서
    YEAR_AGO_DAYS 전에 가장 가까운 과거 공시(동률이면 나중 공시). 과거 공시가 없으면 최신 값만. 반환: (값, 단독 여부)."""
    if latest.ta is None or latest.ta <= 0:
        return None, False
    key0 = time_key(latest)
    target = key0 - timedelta(days=YEAR_AGO_DAYS)
    past = [r for r in usable if time_key(r) < key0 and r.ta is not None and r.ta > 0]
    if not past:
        return latest.ta, True
    prior = min(past, key=lambda r: (abs((time_key(r) - target).days), -r.file_date.toordinal()))
    return (latest.ta + prior.ta) / 2, False


def stock_metrics(latest, usable, mcap, checks):
    """퀄리티 3개·가치 4개 지표와 [SPOT]용 원 값. 순자산 ≤ 0이면 순자산/시총 결측(계획서 6장)."""
    method, flows = ttm_values(latest, usable)
    avg_ta, single = average_assets(latest, usable)
    rev, gp, ni, ocf, capex = (flows.get(k) for k in ("rev", "gp", "ni", "ocf", "capex"))
    fcf = ocf - abs(capex) if ocf is not None and capex is not None else None
    checks["capex_pos"] += capex is not None and capex > 0
    checks["assets_single"] += single
    checks["rev_zero"] += rev == 0
    has_mcap = mcap is not None and mcap > 0
    return {
        "ttm": method, "file_date": latest.file_date, "rev": rev, "ni": ni, "ta": latest.ta,
        "gp_ta": gp / avg_ta if gp is not None and avg_ta else None,
        "ni_ta": ni / avg_ta if ni is not None and avg_ta else None,
        "tl_ta": latest.tl / latest.ta if latest.tl is not None and latest.ta and latest.ta > 0 else None,
        "ep": ni / mcap if ni is not None and has_mcap else None,
        "bp": latest.eq / mcap if latest.eq is not None and latest.eq > 0 and has_mcap else None,
        "fcfp": fcf / mcap if fcf is not None and has_mcap else None,
        "sp": rev / mcap if rev is not None and has_mcap else None,
    }


# ----------------------------------------------------------------------
# 모멘텀 (계획서 6장: 배당·분할 조정 12-1개월 총수익률, 최소 12개월 관측)
# ----------------------------------------------------------------------
def month_index(day):
    return day.year * 12 + day.month - 1


def momentum_returns(closes, symbols, signal_date):
    """t-12개월 월말 → t-1개월 월말 조정 종가 수익률. 각 달 마지막 종가가 MOM_MIN_MONTHS개 이상이고 양 끝이 있어야 함.
    closes는 adjusted_daily_closes 결과(오래된 순)라 달마다 마지막 종가가 남는다."""
    first = month_index(signal_date) - MOM_LOOKBACK_MONTHS
    last = month_index(signal_date) - MOM_SKIP_MONTHS
    returns = {}
    for s in symbols:
        by_month = {}
        for day, close in closes.get(s, ()):
            by_month[month_index(day)] = close
        series = [by_month.get(m) for m in range(first, last + 1)]
        observed = sum(v is not None for v in series)
        if observed < MOM_MIN_MONTHS or series[0] is None or series[-1] is None or series[0] <= 0:
            returns[s] = None
        else:
            returns[s] = series[-1] / series[0] - 1
    return returns


def history_window(signal_date, need_sigma):
    """조정 일봉 요청 구간 (start, end). 모멘텀용으로 t-12개월 월초부터, σ̂가 필요하면(3단계 역변동성)
    신호일 SIGMA_LOOKBACK_CALENDAR_DAYS 전부터. end는 신호일 다음 날 0시라 신호일 봉까지만 들어온다."""
    first = month_index(signal_date) - MOM_LOOKBACK_MONTHS
    start = datetime(first // 12, first % 12 + 1, 1)
    day = datetime(signal_date.year, signal_date.month, signal_date.day)
    if need_sigma:
        start = min(start, day - timedelta(days=SIGMA_LOOKBACK_CALENDAR_DAYS))
    return start, day + timedelta(days=1)


def adjusted_daily_closes(algo, symbols, start, end, warn):
    """배당·분할 조정 일봉을 종목 묶음 한 번으로 요청해 {Symbol: [(거래일, 종가), ...] 오래된 순}.
    모멘텀과 σ̂(3단계)가 같은 결과를 쓴다. 신호일 이후 봉은 요청하지 않는다. NOTES.md [I]."""
    if not symbols:
        return {}
    try:
        df = algo.history(list(symbols), start, end, Resolution.DAILY,
                          data_normalization_mode=DataNormalizationMode.ADJUSTED)
    except Exception as err:
        warn("history_adjusted", f"adjusted history request failed: {err}")
        return {}
    if df is None or df.empty or "close" not in df.columns:
        return {}
    by_name = {}
    for s in symbols:
        for name in (str(s), s.value, str(s.id)):
            by_name.setdefault(name, s)
    by_day = defaultdict(dict)
    for index, close in zip(df.index, df["close"]):
        symbol = by_name.get(str(index[0]))
        if symbol is not None:
            by_day[symbol][(index[-1] - BAR_END_OFFSET).date()] = float(close)
    return {s: sorted(days.items()) for s, days in by_day.items()}


# ----------------------------------------------------------------------
# 점수 (계획서 6장: 섹터 내 순위 → [-1,1] → 스타일 평균 → 세 스타일 평균 → 표준화 z)
# ----------------------------------------------------------------------
def compute_factors(algo, history, members, eligible, signal_date, calendar, warn, closes=None,
                    score_mode=DEFAULT_SCORE_MODE):
    """유니버스 종목 전체의 지표와 z. 요건: 모멘텀 있음, 재무 'ok', 퀄리티 3/3, 가치 3/4 이상(계획서 6장 재무 결측).
    제외 사유(한 종목이 여러 개일 수 있음): mom, 재무는 expired / pit 중 하나 또는 qual·value.
    closes: 이미 받은 조정 일봉(3단계는 σ̂와 한 번에 요청). 없으면 모멘텀 구간만 요청한다."""
    month = FactorMonth(signal_date)
    if closes is None:
        closes = adjusted_daily_closes(algo, members, *history_window(signal_date, False), warn)
    momentum = momentum_returns(closes, members, signal_date)
    targets = {}
    for s in sorted(members, key=lambda s: str(s.id)):
        record = {"sector": eligible[s].sector, "mcap": eligible[s].mcap, "mom": momentum.get(s)}
        state, latest, usable = financial_state(history, s, signal_date, calendar)
        fail = [] if record["mom"] is not None else ["mom"]
        if state in ("expired", "pit"):
            fail.append(state)
            if latest is not None:
                record["file_date"] = latest.file_date
        else:
            if state == "ok":
                record.update(stock_metrics(latest, usable, record["mcap"], month.checks))
                month.ttm[record["ttm"]] += 1
            if state != "ok" or any(record.get(k) is None for k in QUALITY_KEYS):
                fail.append("qual")
            if state != "ok" or sum(record.get(k) is not None for k in VALUE_KEYS) < VALUE_MIN_METRICS:
                fail.append("value")
        record["fail"] = fail
        month.reasons.update(fail)
        month.records[s] = record
        if not fail:
            targets[s] = record
    score_targets(targets, month, score_mode)
    return month


def score_targets(targets, month, score_mode=DEFAULT_SCORE_MODE):
    """섹터(합친 그룹) 안에서 지표별 순위 점수를 매기고 month.z에 표준화 z를 넣는다.
    score_mode = "global"이면 섹터 구분 없이 점수 대상 전체를 한 그룹으로 순위를 매긴다(계획서 10장 시험 집합)."""
    counts = Counter(r["sector"] for r in targets.values())
    groups = merge_sectors(counts) if score_mode == "sector" else ([sorted(counts)] if counts else [])
    month.merges = ["+".join(SECTOR_LABELS[c] for c in g) + "(" + "+".join(str(counts[c]) for c in g) + ")"
                    for g in groups if len(g) > 1] if score_mode == "sector" else ["global"]
    composite = {}
    for group in groups:
        names = [s for s, r in targets.items() if r["sector"] in group]
        momentum = rank_scores({s: targets[s]["mom"] for s in names})
        quality = [rank_scores({s: targets[s]["gp_ta"] for s in names}),
                   rank_scores({s: targets[s]["ni_ta"] for s in names}),
                   rank_scores({s: -targets[s]["tl_ta"] for s in names})]      # 총부채/총자산은 낮을수록 좋음
        value = [rank_scores({s: targets[s][k] for s in names if targets[s][k] is not None}) for k in VALUE_KEYS]
        for s in names:
            quality_score = sum(scores[s] for scores in quality) / len(quality)
            value_score = sum(scores.get(s, 0.0) for scores in value) / VALUE_METRIC_COUNT   # 결측 1개는 0점
            composite[s] = (momentum[s] + quality_score + value_score) / 3
            month.style[s] = (momentum[s], quality_score, value_score)
    month.z = standardize(composite)
    if month.z:
        month.z_mean, month.z_sd = mean_sd(list(month.z.values()))


def rank_scores(values):
    """{종목: 값} → {종목: [-1, 1] 점수}. 값이 클수록 높음. 동점은 평균 순위. 2(r-1)/(n-1) - 1, n = 1이면 0."""
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    scores = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        average_rank = (i + j) / 2 + 1
        score = 2 * (average_rank - 1) / (n - 1) - 1 if n > 1 else 0.0
        for k in range(i, j + 1):
            scores[items[k][0]] = score
        i = j + 1
    return scores


def merge_sectors(counts):
    """점수 대상이 MIN_SECTOR_SIZE 미만인 섹터를 SECTOR_MERGE_ORDER의 앞·뒤 그룹과 합친다.
    가장 작은 그룹부터, 앞·뒤 중 종목이 적은 쪽(같으면 뒤)과 합치고 모두 기준 이상이거나 한 그룹이 될 때까지 반복."""
    order = list(SECTOR_MERGE_ORDER) + sorted(c for c in counts if c not in SECTOR_MERGE_ORDER)
    groups = [[code] for code in order if counts.get(code, 0) > 0]
    while len(groups) > 1:
        sizes = [sum(counts[c] for c in g) for g in groups]
        small = [i for i, size in enumerate(sizes) if size < MIN_SECTOR_SIZE]
        if not small:
            break
        i = min(small, key=lambda k: (sizes[k], k))
        neighbors = [k for k in (i - 1, i + 1) if 0 <= k < len(groups)]
        k = min(neighbors, key=lambda n: (sizes[n], n < i))
        lo, hi = sorted((i, k))
        groups[lo] = groups[lo] + groups[hi]
        del groups[hi]
    return groups


def standardize(values):
    """횡단면 평균 0·표준편차 1(모표준편차, ddof = 0). 표준편차가 0이면 모두 0."""
    if not values:
        return {}
    mean, sd = mean_sd(list(values.values()))
    return {s: (v - mean) / sd if sd > 0 else 0.0 for s, v in values.items()}


def mean_sd(numbers):
    mean = sum(numbers) / len(numbers)
    return mean, math.sqrt(sum((x - mean) ** 2 for x in numbers) / len(numbers))
