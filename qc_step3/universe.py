# region imports
from AlgorithmImports import *
# endregion
# 유니버스 규칙: 적격 조건, 대표 주식 선정, 완충 순위, 탈락 사유 분류, 시점 규칙(계획서 6장·8장)
from collections import Counter, defaultdict, namedtuple
from datetime import date, datetime, timedelta

from config import *

# 적격 종목의 이번 달 값
Candidate = namedtuple("Candidate", "mcap sector file_date price")


class MonthScreen:
    """한 달 선별 상태: 탈락 사유 집계, 직전 유니버스 종목의 탈락 사유, 1차 후보, 적격 종목."""

    def __init__(self, prev):
        self.prev = prev
        self.present = set()
        self.funnel = Counter()
        self.prev_reasons = {}      # 직전 유니버스 종목이 이번 달 적격 조건에서 걸린 사유
        self.candidates = []        # (Fundamental, 회사 키)
        self.eligible = {}          # Symbol -> Candidate
        self.listing_presample = 0
        self.listing_sid_pass = 0

    def reject(self, symbol, reason):
        self.funnel[reason] += 1
        if symbol in self.prev:
            self.prev_reasons[symbol] = reason


# ----------------------------------------------------------------------
# 적격 조건 (계획서 6장)
# ----------------------------------------------------------------------
def scan_securities(screen, fundamental, collector=None):
    """1차: 증권 단위 조건(계획서 6장 ETF·ADR·우선주 제외, 채택: 미국 거래소) → 회사별 보통주 후보."""
    for f in fundamental:
        symbol = f.symbol
        screen.present.add(symbol)
        if collector is not None:
            collector.observe(f)
        reason = security_reason(f)
        if reason:
            screen.reject(symbol, reason)
        else:
            screen.candidates.append((f, company_key(f)))


def screen_stocks(screen, representatives, signal_date, recorder):
    """2차: 대표 주식에만 나머지 조건(계획서 6장)."""
    for f, _ in screen.candidates:
        symbol = f.symbol
        if symbol not in representatives:
            screen.reject(symbol, "share_class")
            continue
        reason, sector, listing_source = stock_reason(f, signal_date)
        screen.listing_presample += listing_source == "presample"
        screen.listing_sid_pass += listing_source == "sid" and reason != "listing_sid"
        if reason:
            screen.reject(symbol, reason)
            continue
        screen.funnel["eligible"] += 1
        screen.eligible[symbol] = Candidate(
            float(f.market_cap), sector, latest_file_date(f, recorder), float(f.price))


def security_reason(f):
    """증권 단위 조건(대표 주식 선정 전). 통과하면 None, 아니면 탈락 사유."""
    if not f.has_fundamental_data:
        return "no_fund"                    # 재무가 없는 증권(ETF 등) — 계획서 6장 ETF 제외
    sec = f.security_reference
    if sec.security_type != COMMON_STOCK_TYPE:
        return "type"                       # 우선주·ETF·유닛 등 — 계획서 6장
    if sec.is_depositary_receipt:
        return "adr"                        # ADR — 계획서 6장
    if sec.exchange_id not in ALLOWED_EXCHANGES:
        return "exchange"                   # 채택: 미국 거래소 상장
    return None


def stock_reason(f, signal_date):
    """대표 주식에 적용하는 나머지 조건(계획서 6장). (탈락 사유 또는 None, 섹터 코드, 상장일 판정 경로)."""
    if f.price < MIN_PRICE:
        return "price", None, None          # 계획서 6장: 주가 $5 이상
    company = f.company_reference
    if company.country_id not in ALLOWED_COUNTRIES:
        return "country", None, None        # 채택: 미국 법인
    sector = f.asset_classification.morningstar_sector_code
    if sector not in SECTOR_LABELS:
        return "sector_na", None, None      # 채택: 섹터 미분류 제외
    if sector in EXCLUDED_SECTOR_CODES:
        return "sector_" + SECTOR_LABELS[sector], sector, None   # 계획서 6장: 금융·부동산 제외
    if company.is_reit:
        return "reit", sector, None         # 계획서 6장: 리츠 포함 제외(부동산 외 섹터로 분류된 REIT 대비)
    source, listing_date = listing_info(f)
    if source != "presample" and (
            listing_date is None or months_between(listing_date, signal_date) < MIN_LISTING_MONTHS):
        return ("listing_sid" if source == "sid" else "listing"), sector, source   # 계획서 6장: 상장 24개월
    if not f.market_cap or f.market_cap <= 0:
        return "mcap", sector, source
    return None, sector, source


def listing_info(f):
    """상장일 판정 경로(계획서 6장 '상장 24개월 이상', 사용자 결정 2026-09-26). NOTES.md [C][G].
      "ipo"       : Morningstar IPO 날짜가 있고 LEAN 최초 거래일(SID 날짜)보다 늦지 않으면 그날부터 24개월을 센다.
      "presample" : IPO 날짜가 없거나 믿을 수 없고, 최초 거래일이 데이터 시작일이면 데이터 시작 전부터 상장으로 보고 통과.
      "sid"       : IPO 날짜가 없거나 믿을 수 없고, 최초 거래일이 데이터 시작일보다 뒤면 그날부터 24개월을 센다.
    IPO 날짜가 최초 거래일보다 뒤면 믿지 않는다(사용자 결정 2026-09-26, 커버리지 점검: GE ipo 2015-11·HLX 2026-09 등
    현재 시점 값으로 덮어써진 날짜). 결과적으로 상장일 = min(IPO 날짜, 최초 거래일)."""
    ipo = to_date(f.security_reference.ipo_date)
    first_trade = to_date(f.symbol.id.date)
    if ipo is not None and (first_trade is None or ipo <= first_trade):
        return "ipo", ipo
    if first_trade is not None and first_trade <= LEAN_DATA_START:
        return "presample", first_trade
    return "sid", first_trade


def company_key(f):
    """대표 주식 선정용 회사 식별자. company_id가 없으면 증권 자체를 한 회사로 본다. NOTES.md [C]."""
    company_id = f.company_reference.company_id
    return company_id if company_id else str(f.symbol.id)


def latest_file_date(f, recorder):
    """최신 재무제표 공시일(시점 점검용). 처음 본 값의 형식을 recorder에 남긴다. NOTES.md [D]."""
    try:
        raw = f.financial_statements.file_date
    except AttributeError:
        raw = None
    if recorder.file_date_type is None:
        recorder.file_date_type = type(raw).__name__
    return to_date(raw)


# ----------------------------------------------------------------------
# 대표 주식 선정 (채택 규칙: config.SHARE_CLASS_ADV_DAYS 주석)
# ----------------------------------------------------------------------
def choose_representatives(algo, candidates, warn):
    """회사당 대표 주식 1개.
    반환: (대표 Symbol 집합, 복수 종류 회사별 Symbol 목록, 평균 거래대금 dict, 거래대금 자료가 없는 종류 수)"""
    groups = defaultdict(list)
    for f, key in candidates:
        groups[key].append(f.symbol)
    multi_groups = [symbols for symbols in groups.values() if len(symbols) > 1]
    adv = average_dollar_volume(algo, [s for symbols in multi_groups for s in symbols], warn)
    representatives = {symbols[0] for symbols in groups.values() if len(symbols) == 1}
    for symbols in multi_groups:
        representatives.add(min(symbols, key=lambda s: (-adv.get(s, 0.0), str(s.id))))
    adv_missing = sum(s not in adv for symbols in multi_groups for s in symbols)
    return representatives, multi_groups, adv, adv_missing


def average_dollar_volume(algo, symbols, warn):
    """직전 SHARE_CLASS_ADV_DAYS 거래일 평균 거래대금(원주가 종가 × 거래량). 받은 일봉만으로 평균."""
    bars = raw_daily_bars(algo, symbols, SHARE_CLASS_ADV_DAYS, warn)
    return {s: sum(close * volume for _, close, volume in rows) / len(rows) for s, rows in bars.items() if rows}


def raw_daily_bars(algo, symbols, bar_count, warn):
    """현재 시각 이전의 원주가 일봉 bar_count개. {Symbol: [(거래일, 종가, 거래량), ...]}.
    선택 함수 안에서 부르면 신호일 T까지의 봉만 온다(미래 봉 없음). NOTES.md [I]."""
    if not symbols:
        return {}
    try:
        df = algo.history(list(symbols), bar_count, Resolution.DAILY,
                          data_normalization_mode=DataNormalizationMode.RAW)
    except Exception as err:
        warn("history", f"history request failed: {err}")
        return {}
    if df is None or df.empty or "close" not in df.columns or "volume" not in df.columns:
        return {}
    by_name = {}
    for s in symbols:
        for name in (str(s), s.value, str(s.id)):
            by_name.setdefault(name, s)
    bars = defaultdict(list)
    for index, close, volume in zip(df.index, df["close"], df["volume"]):
        symbol = by_name.get(str(index[0]))
        if symbol is not None:
            # 일봉 time 색인은 봉 종료 시각이라 조금 빼서 그 봉의 거래일로 바꾼다
            bars[symbol].append(((index[-1] - BAR_END_OFFSET).date(), float(close), float(volume)))
    return bars


# ----------------------------------------------------------------------
# 완충 순위·탈락 사유 (계획서 6장)
# ----------------------------------------------------------------------
def buffer_members(eligible, prev):
    """반환: (시총 순 적격 Symbol 목록, 순위 dict, 새 유니버스 집합)."""
    # 계획서 6장: 적격 종목의 당시 시총 순위. 동률은 SID 문자열로 고정(계획서 14.4: 동률 처리 고정)
    ranked = sorted(eligible, key=lambda s: (-eligible[s].mcap, str(s.id)))
    rank = {s: i + 1 for i, s in enumerate(ranked)}
    # 계획서 6장 완충: 신규 진입은 상위 ENTRY_RANK, 기존 유니버스 종목은 상위 RETAIN_RANK까지 유지
    members = {s for s, r in rank.items() if r <= ENTRY_RANK or (s in prev and r <= RETAIN_RANK)}
    return ranked, rank, members


def classify_exits(exits, present, prev_reasons):
    """탈락 종목별 사유: gone / filt:<조건> / rank."""
    exit_reason = {}
    for s in exits:
        if s not in present:
            exit_reason[s] = "gone"                      # 데이터에서 사라짐(상장폐지·합병 등)
        elif s in prev_reasons:
            exit_reason[s] = "filt:" + prev_reasons[s]   # 적격 조건 이탈(예: 주가 $5 미만)
        else:
            exit_reason[s] = "rank"                      # 적격이지만 순위가 RETAIN_RANK 밖
    return exit_reason


# ----------------------------------------------------------------------
# 시점 규칙 (계획서 6장 '재무 시점', 8장 point-in-time)
# ----------------------------------------------------------------------
def count_pit(members, eligible, signal_date, calendar):
    """최신 공시가 신호일 기준 아직 사용 불가한 유니버스 종목 수와 공시일 결측 수. NOTES.md [E]."""
    pit_late = file_date_missing = 0
    for s in members:
        file_date = eligible[s].file_date
        if file_date is None:
            file_date_missing += 1
        elif not filing_usable(calendar, file_date, signal_date):
            pit_late += 1
    return pit_late, file_date_missing


def filing_usable(calendar, file_date, signal_date):
    """재무는 공시 다음 거래일부터 사용한다.
    신호일 T(거래일) 종가로 판단할 때 공시일 F의 자료는 '사용 가능 첫 거래일 <= T'일 때만 쓸 수 있다.
    FILING_LAG_TRADING_DAYS = 1이면 F < T와 같다(신호일 당일 공시는 그달 신호에 쓰지 않음).
    1998~2012년 근사 공시일에는 추가 시차를 먼저 더한다(사용자 결정으로 0)."""
    usable = file_date
    if file_date.year <= APPROX_FILING_LAST_YEAR:
        usable += timedelta(days=APPROX_FILING_EXTRA_LAG_DAYS)
    for _ in range(FILING_LAG_TRADING_DAYS):
        usable = calendar.next_day(usable)
    return usable <= signal_date


class ExchangeCalendar:
    """거래소 달력(LEAN 내장 TradingCalendar와 이름이 겹치지 않게 함). NOTES.md [F]: API가 실패하면
    주말만 건너뛰는 근사(휴장일 무시)로 대체하고 경고."""

    def __init__(self, exchange_hours, warn):
        self._hours = exchange_hours
        self._warn = warn
        self._next_cache = {}

    def previous_day(self, moment):
        """moment 직전 거래일."""
        try:
            result = to_date(self._hours.get_previous_trading_day(moment))
        except Exception as err:
            self._warn("calendar", f"exchange calendar API failed, weekday approximation used: {err}")
            result = None
        if result is None:
            result = moment.date() - timedelta(days=1)
            while result.weekday() >= 5:
                result -= timedelta(days=1)
        return result

    def next_day(self, day):
        """day 다음 거래일."""
        if day not in self._next_cache:
            try:
                result = to_date(self._hours.get_next_trading_day(datetime(day.year, day.month, day.day)))
            except Exception as err:
                self._warn("calendar", f"exchange calendar API failed, weekday approximation used: {err}")
                result = None
            if result is None:
                result = day + timedelta(days=1)
                while result.weekday() >= 5:
                    result += timedelta(days=1)
            self._next_cache[day] = result
        return self._next_cache[day]


# ----------------------------------------------------------------------
# 날짜 보조 함수
# ----------------------------------------------------------------------
def months_between(start, end):
    """start부터 end까지 꽉 찬 개월 수."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    return months - 1 if end.day < start.day else months


def to_date(value):
    """LEAN/.NET 날짜 값을 date로 바꾼다. 결측(None, DateTime.MinValue 등)은 None.
    반환 형식이 확실하지 않은 필드에 대비해 다기간 필드(.value)와 .NET DateTime(.Year)도 처리한다."""
    if value is None:
        return None
    if not isinstance(value, date) and hasattr(value, "value"):
        value = value.value
    if isinstance(value, datetime):
        value = value.date()
    elif value is not None and not isinstance(value, date) and hasattr(value, "Year"):
        value = date(value.Year, value.Month, value.Day)
    if not isinstance(value, date) or value.year < MIN_VALID_YEAR:
        return None
    return value
