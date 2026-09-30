# 5단계(4단계 + 기준선: 무작위 대조군·단일 팩터·유니버스·RSP·SPY) 설정 상수. 상수를 바꾸면 실행 기록에 남긴다(CLAUDE.md 원칙 5). 배경은 NOTES.md.
from datetime import date, timedelta

# --- 구간·자본 (계획서 10장 기간표, 0장) ---
DEV_PERIOD_FIRST_DAY = date(1998, 1, 1)   # 계획서 10장: 개발 구간 시작
DEV_PERIOD_LAST_DAY = date(2015, 12, 31)  # 계획서 10장: 개발 구간 끝. 2016년 이후(검증·의사 OOS)는 사용 금지
START_DATE = date(1998, 1, 1)
END_DATE = date(2015, 12, 31)
QUICK_TEST = True                         # 점검용 짧은 실행(기본). 최종 확인 때만 False. 개발 구간 검사는 그대로
QUICK_TEST_START_DATE = date(2001, 1, 1)  # 2001~2002는 스냅샷·모멘텀 준비 구간, 2003-01 첫 매매 포함(NOTES.md 기록)
QUICK_TEST_END_DATE = date(2004, 12, 31)
BACKTEST_START_DATE = QUICK_TEST_START_DATE if QUICK_TEST else START_DATE
BACKTEST_END_DATE = QUICK_TEST_END_DATE if QUICK_TEST else END_DATE
# 데이터 커버리지 점검 모드(전략 로직과 무관한 진단): True면 팩터·주문 없이 점검일에만 1단계 선별과 [COV] 로그.
# 과거 종목(특히 대형주)이 QC Morningstar 데이터에서 빠졌는지 확인하려는 것(NOTES.md 기록). QUICK_TEST보다 우선
COVERAGE_CHECK = False
COVERAGE_START_DATE = date(2002, 12, 1)   # 점검 모드 실행 구간(개발 구간 안)
COVERAGE_END_DATE = date(2015, 1, 31)
if COVERAGE_CHECK:
    BACKTEST_START_DATE, BACKTEST_END_DATE = COVERAGE_START_DATE, COVERAGE_END_DATE
COVERAGE_MONTHS = ((2003, 1), (2007, 6), (2011, 6), (2014, 12))   # 점검일 = 이 달들의 신호일(마지막 거래일)
COVERAGE_DV_LEVELS = (5e6, 20e6, 100e6)   # 재무 없는 종목의 일 거래대금 분포 구간($5M·$20M·$100M 이상)
COVERAGE_TOP_N = 20                       # 재무 없는 종목 중 거래대금 상위 표시 수
COVERAGE_TICKERS = ("AAPL", "MSFT", "INTC", "CSCO", "ORCL", "IBM", "HPQ", "DELL", "WMT", "HD", "PG", "KO", "PEP",
                    "JNJ", "PFE", "MRK", "XOM", "CVX", "GE", "BA", "CAT", "MMM", "T", "VZ", "AMZN", "GOOG", "DIS",
                    "MCD", "NKE", "UNH")  # 알려진 대형주 점검 목록(표시용 티커)
COVERAGE_TICKER_FROM = {"GOOG": (2004, 8)}  # 이 (연, 월) 이후 점검일에만 확인(상장 전 제외)
# 커버리지 진단 2차(2026-09-26, Alpaca 결과 후): 탈락 사유 분포·상장일 모순·시총 결측·재무 누락 종목의 생존율
COVERAGE_DETAIL_TOP_N = 6                 # 상장일 모순·시총 결측 종목 표시 수
COVERAGE_LOG_LISTS = False                # 재무 없는 상위 20·대형주 30 줄 출력(결과가 매번 같아 로그 절약용으로 끔)

COVERAGE_SURVIVAL_DV = 20e6               # 생존율 비교 대상: 가격 ≥ $5이고 신호일 거래대금 ≥ 이 값
COVERAGE_MCAP_LEVELS = (10e9, 1e9, 0.5e9, 0.2e9)   # 적격 종목 시총 분포 구간
# 재무 없는 종목 중 ETF(재무 자료가 없어 구분 불가)를 걸러내는 알려진 ETF·HOLDRS 목록. 완전하지 않음(표시용)
COVERAGE_KNOWN_ETFS = frozenset((
    "SPY IVV VOO VTI RSP MDY IJH IJR IWM IWB IWD IWF IWN IWO IWR IWS IWP IWV DIA QQQ QQQQ ONEQ "
    "XLB XLE XLF XLI XLK XLP XLU XLV XLY IYR IYF IYM IYT IYW IYE IYH IYZ IBB XBI SMH SOXX KRE KBE XHB XRT XME XOP "
    "ITB OIH BBH HHH RTH PPH UTH TTH IAH SWH BDH WMH TBH EKH MKH IIH SMH RKH MDY GDX GDXJ SIL "
    "EFA EEM VWO VEA VGK IEMG EZU EWJ EWZ EWT EWY EWG EWH EWC EWA EWW EWU EWS EWM FXI RSX ILF "
    "GLD SLV USO UNG DBC DBA DBO UUP FXE FXY FXA FXC FXB "
    "TLT IEF SHY AGG BND LQD HYG JNK TIP EMB MUB SHV BIL "
    "SSO SDS QLD QID DDM DXD MVV MZZ UWM TWM UYG SKF URE SRS DIG DUG ROM REW USD SSG "
    "UPRO SPXU SPXL SPXS TQQQ SQQQ TNA TZA FAS FAZ ERX ERY TMF TMV TBT UCO SCO AGQ ZSL UGL GLL NUGT DUST "
    "VXX VIXY UVXY SVXY XIV TVIX VXZ "
    "SH PSQ DOG RWM EUM EFZ").split())
# 사용자 결정(수익률과 무관, 2026-09-26): 1998~2002는 Morningstar 커버리지 때문에 적격 종목이 900개 미만이라 유니버스가
# '적격 전체'가 되어 소형·저유동 종목이 섞인다(계획서 6장 대형주 유니버스 전제 불성립). 평가는 이 달 신호일부터 시작하고,
# 그 이전 신호일은 유니버스·z만 계산하고 주문하지 않는다(현금). 1999~2002 결과는 '데이터 한계 구간'으로만 참고
PORTFOLIO_START_SIGNAL = (2003, 1)        # (연, 월): 첫 포트폴리오 = 이 달 신호일의 z 상위 N
TRADING_DAYS_PER_YEAR = 252               # [PERF] 연율화(변동성·Sharpe)
CALENDAR_DAYS_PER_YEAR = 365.25           # [PERF] CAGR 기간(달력일 / 365.25)
INITIAL_CASH = 20_000                     # 계획서 0장: 초기 연구 자본(달러)

# --- 유니버스 (계획서 6장 표 '유니버스') ---
ENTRY_RANK = 900                          # 계획서 6장: 신규 진입은 적격 종목 당시 시총 순위 상위 900
RETAIN_RANK = 1_100                       # 계획서 6장: 기존 유니버스 종목은 상위 1,100까지 유지
MIN_PRICE = 5.0                           # 계획서 6장(4장 제약표): 주가 $5 이상. 월말 원주가 기준
MIN_LISTING_MONTHS = 24                   # 계획서 6장: 상장 24개월 이상(상장일 판정은 universe.listing_info)
MCAP_FILL = False                         # 시총 결측 대체(가격 × 주식 수). 사용 금지(2026-09-27): 주식 수가 이후 분할로 재계산돼 시점 불일치(NOTES 기록)
MCAP_FILL_FIELDS = ("so", "osn", "bas")   # 대체 주식 수 필드 우선순위(universe.SHARE_FIELDS 약어, das=희석 주식 수 제외)
EXCLUDED_SECTOR_CODES = (103, 104)        # 계획서 6장: 금융(103 Financial Services)·부동산(104 Real Estate) 제외
COMMON_STOCK_TYPE = "ST00000001"          # 계획서 6장: 보통주만(우선주·ETF 등 제외). Morningstar 증권 유형 코드 — NOTES.md [C]
# 아래 네 조건은 계획서 6장 '미국 보통주'의 해석으로 사용자가 채택(2026-09-26)
ALLOWED_EXCHANGES = ("NYS", "NAS", "ASE")  # 채택: NYSE·NASDAQ·AMEX 상장만(장외 제외) — 코드값 NOTES.md [C]
ALLOWED_COUNTRIES = ("USA",)              # 채택: 미국 법인만(CRSP 보통주 코드 10·11 관행) — NOTES.md [C]
SHARE_CLASS_ADV_DAYS = 21                 # 채택: 회사당 대표 주식 1개 = 같은 회사(company_id)의 보통주 종류 중
                                          #   직전 21거래일 평균 거래대금(원주가 종가 × 거래량)이 가장 큰 종류.
                                          #   동률이거나 거래대금 자료가 없으면 SID 문자열 순으로 고정.
                                          #   대표를 먼저 고른 뒤 주가·상장 기간 등 나머지 조건은 대표 주식에만 적용한다.
                                          # 채택: 섹터 미분류(SECTOR_LABELS에 없는 코드) 종목 제외 — universe.stock_reason
LEAN_DATA_START = date(1998, 1, 2)        # LEAN 미국 주식 데이터 시작일. 이전 상장 종목의 SID 날짜가 이 값 — NOTES.md [G]
MIN_VALID_YEAR = 1900                     # 이보다 이른 날짜(DateTime.MinValue 등)는 결측으로 본다

# 섹터 표시 약어 (Morningstar Sector Code). 계획서 6장: 섹터 분류는 전 기간 같은 체계(Morningstar)로 쓴다
SECTOR_LABELS = {
    101: "Mat",    # Basic Materials 소재
    102: "CCyc",   # Consumer Cyclical 경기소비재
    103: "Fin",    # Financial Services 금융 (제외)
    104: "RE",     # Real Estate 부동산 (제외)
    205: "CDef",   # Consumer Defensive 필수소비재
    206: "Hlth",   # Healthcare 헬스케어
    207: "Util",   # Utilities 유틸리티
    308: "Comm",   # Communication Services 커뮤니케이션
    309: "Enrg",   # Energy 에너지
    310: "Ind",    # Industrials 산업재
    311: "Tech",   # Technology 기술
}

# --- 시점 기준 (계획서 6장 '재무 시점', 8장 point-in-time 규칙) ---
FILING_LAG_TRADING_DAYS = 1               # 계획서 6장·8장: 재무는 공시 '다음 거래일'부터 사용
APPROX_FILING_LAST_YEAR = 2012            # 계획서 3장·8장·10장: 1998~2012년 공시일은 근사치 → 기록에 따로 표시
APPROX_FILING_EXTRA_LAG_DAYS = 0          # 계획서 8장: 근사 구간 추가 시차. 사용자 결정(2026-09-26)으로 0(추가 시차 없음)

# --- 첫 신호일 데이터 확인 (사용자 지시 2026-09-26, 계획서 8장·9장 취지) ---
# 첫 신호일(1997-12-31)에 가격·재무 데이터가 실제로 없으면 첫 재구성을 한 번만 다음 월말(1998-01 마지막 거래일)로 미룬다
START_CHECK_SAMPLE = 50                   # 확인 표본: 시총 상위 적격 종목 수
START_CHECK_BARS = 5                      # 신호일을 덮도록 요청하는 원주가 일봉 수
START_CHECK_MIN_RATIO = 0.9               # 표본 중 일봉 존재·가격 일치·공시일 존재가 각각 이 비율 이상이어야 통과
PRICE_MATCH_TOLERANCE = 0.005             # Fundamental 가격과 신호일 원주가 종가의 허용 차이(0.5%)
BAR_END_OFFSET = timedelta(minutes=1)     # 일봉 종료 시각(당일 16:00 또는 다음날 00:00)에서 빼서 거래일을 얻는 값

# --- 기록·로그 ---
CALENDAR_TICKER = "SPY"                   # 거래일 달력 참조용 구독. 매매 대상 아님, 유니버스에도 넣지 않음
CHECK_TICKER = "IBM"                      # [DIAG] 표본 종목. 티커는 표시용일 뿐 추적은 Symbol로 한다
CONSOLE_MONTHLY_LOG = False               # True면 매월 [UNIV] 줄 출력(유료 플랜용). 무료 플랜 로그 한도 — NOTES.md [H]
CONSOLE_FIRST_MONTHS = 0                  # 2단계: 로그 한도 때문에 [UNIV] 월별 줄은 끔(LOG_STEP1_YEAR가 True일 때만 적용)
LOG_STEP1_YEAR = False                    # 2단계: 1단계 [YEAR 연도]·[UNIV] 줄 출력(약 4KB). False면 둘 다 끔.
                                          #   연도 합계 계산과 [SUMMARY]의 1단계 요약은 그대로
LOG_STEP2_YEAR = False                    # 3단계: 2단계 [FYEAR 연도] 줄 출력(약 2KB). False면 끔. [SPOT]·[SUMMARY] 팩터 요약은 그대로
SAVE_TO_OBJECT_STORE = False              # 무료 플랜에서 Object Store 저장 시 권한 오류(2026-09-26 실행) → 저장 시도 안 함
SAVE_EVERY_MONTHS = 12                    # 중간 저장 주기(백테스트가 도중에 멈춰도 기록이 남도록)
WARN_MAX_CHARS = 200                      # 경고 로그 최대 길이
OBJECT_STORE_MONTHLY_KEY = "program_trading/step1/universe_monthly.csv"
OBJECT_STORE_CHANGES_KEY = "program_trading/step1/universe_changes.csv"

# --- 팩터 점수 (2단계, 계획서 6장 표: 모멘텀·퀄리티·가치·재무 결측·재무 시점·점수) ---
MOM_LOOKBACK_MONTHS = 12                  # 계획서 6장: 12-1개월 총수익률의 시작 = t-12개월 월말
MOM_SKIP_MONTHS = 1                       # 계획서 6장: 최근 1개월 제외 = t-1개월 월말까지
MOM_MIN_MONTHS = 12                       # 계획서 6장: 최소 12개월 관측 = t-12..t-1 각 달의 월말 조정 종가가 모두 있음(NOTES.md [K])
FILING_EXPIRY_DAYS = 180                  # 계획서 6장: 마지막 사용 가능 공시 후 180일이 지나면 재무 만료(결측)
VALUE_MIN_METRICS = 3                     # 계획서 6장: 가치 4개 중 3개 이상 필요, 1개 결측은 0점
VALUE_METRIC_COUNT = 4                    # 계획서 6장: 가치 점수는 항상 4로 나눔
MIN_SECTOR_SIZE = 20                      # 계획서 6장: 점수 대상이 20개 미만인 섹터는 인접 섹터와 합침
SECTOR_MERGE_ORDER = (101, 102, 205, 206, 207, 308, 309, 310, 311)
                                          # '인접'의 정의(해석, NOTES.md 참고): 이 순서(Morningstar 섹터 코드 순)에서
                                          #   바로 앞·뒤 그룹. 작은 그룹부터, 앞·뒤 중 종목이 적은 쪽과 합침(같으면 뒤)
QUARTER_GAP_MIN_DAYS = 75                 # TTM 분기 합: 연속 분기로 볼 기간 종료일 간격(13·14주 분기 포함)
QUARTER_GAP_MAX_DAYS = 105
TTM_QUARTERS = 4                          # 계획서 6장: 신고서 원 항목으로 TTM = 최근 4개 분기 합
YEAR_AGO_DAYS = 365                       # 평균 총자산: 최근 공시 기간 종료일에서 1년 전에 가장 가까운 과거 공시(NOTES.md)
SNAPSHOT_KEEP_DAYS = 800                  # 재무 스냅샷 보관 기간(4개 분기 합과 1년 전 총자산에 충분)
# Morningstar 필드 경로(financial_statements 아래). 이름·의미는 NOTES.md [J] 확인 필요 — 없으면 [WARN] 후 결측 처리
PERIOD_END_FIELD = "period_ending_date"
FLOW_FIELDS = {                           # 흐름 항목(three_months = 분기, twelve_months = 연간 — NOTES.md [J])
    "rev": "income_statement.total_revenue",          # 매출
    "gp": "income_statement.gross_profit",            # 매출총이익
    "ni": "income_statement.net_income",              # 순이익
    "ocf": "cash_flow_statement.operating_cash_flow",  # 영업현금흐름
    "capex": "cash_flow_statement.capital_expenditure",  # 설비투자(부호와 무관하게 절댓값을 뺌 — 계획서 8장 부호 규칙)
}
BALANCE_FIELDS = {                        # 시점 항목(가장 최근 공시 기준)
    "ta": "balance_sheet.total_assets",                        # 총자산
    "tl": "balance_sheet.total_liabilities_net_minority_interest",  # 총부채(부채총계로 해석 — NOTES.md)
    "eq": "balance_sheet.common_stock_equity",                 # 순자산(보통주 자본)
}
FACTOR_DETAIL_MONTHS = 2                  # [FACTOR] 월별 상세를 남길 달 수: 점수가 처음 나온(scored > 0) 신호일부터
FACTOR_SCORE_START_YEAR = 1999            # 점수 산출 시작 연도(NOTES.md [K]). 런타임 통계 cov_min99의 기준
LOG_STEP1_CHECKS = False                  # 1단계 첫 실행 필드 점검 로그([LEGEND]·[DIAG], 약 1KB). 1단계에서 확인했고
                                          #   무료 플랜 로그 한도(10KB) 때문에 2단계에서는 끔. True면 다시 출력
SPOT_MONTHS = ()                          # [SPOT] 확인 달. 5단계: 기준선 로그 자리를 위해 끔(3·4단계에서 확인 끝)
SPOT_TICKERS = ("IBM", "MSFT", "XOM")     # [SPOT] 확인 종목(표시용 티커)

# --- 종목 구성·매매 (3단계, 계획서 6장 '구성'·'변동성 σ̂'·'소액 거래', 9장 체결 시간 규칙, 4장 제약) ---
# 사용자 결정(결과 보기 전 동결): N ∈ {40, 60, 80}, 가중 ∈ {equal, invvol}. QC 프로젝트 파라미터로 받는다
N_HOLDINGS_CHOICES = (40, 60, 80)         # 계획서 10장 시험 집합의 N
WEIGHTING_CHOICES = ("equal", "invvol")   # 계획서 6장 구성: 동일가중·역변동성
DEFAULT_N_HOLDINGS = 60                   # 파라미터 n_holdings가 없을 때
DEFAULT_WEIGHTING = "equal"               # 파라미터 weighting이 없을 때
SCORE_MODES = ("sector", "global")        # 계획서 10장 시험 집합의 점수: 섹터 내 순위 / 전역 순위(섹터 구분 없음)
DEFAULT_SCORE_MODE = "sector"             # 파라미터 score가 없을 때

# --- 4단계 거래비용 (계획서 9장: 비용 = 브로커 수수료 + 스프레드/2 + 슬리피지, 저·기본·고(2배) 시나리오) ---
COST_SCENARIOS = {"low": 0.5, "base": 1.0, "high": 2.0}   # 사용자 결정(2026-09-27): 총비용(수수료 + 반스프레드)에 곱하는 배수
DEFAULT_COST_SCENARIO = "base"            # 파라미터 cost가 없을 때
SPREAD_WINDOW = 21                        # 계획서 9장: 직전 21거래일 평균 추정치(신호일까지의 일봉만, 주문일 고가·저가 미사용)
SPREAD_ESTIMATOR = "abdi_ranaldo"         # 사용자 결정(2026-09-27): Abdi–Ranaldo(2017) 기본, Corwin–Schultz(2012)는 비교용 기록
TICK_SIZE = 0.01                          # 2001 소수점 호가 이후 최소 호가 단위. 반스프레드 하한 = TICK_SIZE / 2 / 주가
MAX_REL_SPREAD = 0.10                     # 추정 스프레드 상한(가격 대비 10%). 넘으면 잘라내고 cap으로 센다
DEFAULT_HALF_SPREAD = 0.005               # 추정치가 없는 체결(상장폐지 자동 청산 등)의 반스프레드(0.5%, 보수적)
SLIPPAGE = 0.0                            # 반스프레드 외 추가 슬리피지(기본 0: 소액 MOC, 반스프레드를 종가 경매 비용의 대용치로 봄)
ADV_DAYS = 20                             # 주문 규모 점검용 평균 거래대금 일수
IMPACT_ADV_LIMIT = 0.01                   # 계획서 9장: 주문이 20일 평균 거래대금의 1%를 넘으면 시장충격 모형 도입 → 넘는 수만 센다
COST_LOG_COUNT = 2                        # [COST] 상세를 남길 처음 리밸런싱 수
KEEP_TOP_FRACTION = 0.40                  # 계획서 6장: 보유 종목은 점수 상위 40% 안이면 유지(순위 ≤ 0.4 × 점수 대상 수)
FILL_TOP_FRACTION = 0.20                  # 계획서 6장: 빈자리는 상위 20% 안에서 점수순으로 채움
MAX_WEIGHT = 0.05                         # 계획서 4장: 매수 시점 종목 비중 ≤ 5%. 초과분은 나머지에 비례 재분배(반복)
SIGMA_HALF_LIFE = 60                      # 계획서 6장 σ̂: 일간 수익률 EWMA 반감기 60거래일
SIGMA_WINDOW = 252                        # 계획서 6장 σ̂: 최근 252거래일(수익률 252개)
SIGMA_MIN_OBS = 126                       # 계획서 6장 σ̂: 최소 126개 관측. 부족하면 역변동성안에서 제외
SIGMA_LOOKBACK_CALENDAR_DAYS = 400        # σ̂용 조정 일봉 요청 기간(252거래일 + 휴장일 여유). 모멘텀 요청과 한 번에 묶음
MIN_TRADE_VALUE = 200.0                   # 계획서 6장·9장 소액 거래: $200 미만 조정·매수는 생략하고 기록(전량 매도는 실행)
CASH_BUFFER = 0.01                        # 매수 총액이 가용 자금을 넘지 않게 목표 비중 합을 99%로(계획서 4장 무차입)
ORDER_MINUTES_AFTER_OPEN = 30             # 계획서 9장: 체결일 개장 30분 뒤 MOC 주문 제출(MOC 마감 15:50 이전)
BUYING_POWER_LEVERAGE = 2.0               # 주문 검증용 한도(margin 기본). 같은 MOC에서 매도 대금 체결 전 매수가 거절되지
                                          #   않게 함. 실제 노출은 목표 비중 합 ≤ 99%로 1 이하 — 현금 음수일·최대 노출 기록
SUBSCRIBE_ALL_MEMBERS = False             # 속도 단축: False면 LEAN 구독을 '보유 + 이번 매수 예정'으로 줄임(True = 2단계처럼
                                          #   유니버스 전체 구독, 결과 비교용). 유니버스·z 대상은 코드 안의 집합으로 관리
REBAL_LOG_COUNT = 2                       # [REBAL]·[FILL] 상세를 남길 처음 리밸런싱 수
FILL_SAMPLES = 3                          # [FILL] 리밸런싱당 표본 체결 수(4단계: 로그 절약으로 5 → 3)
FILL_CHECK_BARS = 3                       # [FILL] 체결일 원주가 일봉을 찾으려고 다음 날 요청하는 최근 일봉 수
FILL_MATCH_TOLERANCE = 1e-4               # [FILL] 체결가와 체결일 종가가 같다고 볼 상대 오차

# 적격 탈락 사유(첫 번째로 걸린 조건). 월별 CSV의 drop_* 열 순서
FUNNEL_ORDER = (
    ("no_fund", "type", "adr", "exchange", "share_class", "price", "country", "sector_na")
    + tuple("sector_" + SECTOR_LABELS[code] for code in EXCLUDED_SECTOR_CODES)
    + ("reit", "listing", "listing_sid", "mcap")
)

# --- 5단계 기준선 (계획서 6장 '기준선', 10장 시험 집합·무작위 대조군) ---
# 실제 매매는 선택된 A0 하나로 돌리고, 같은 백테스트 안에서 가상 장부로 기준선을 계산한다(baseline.py, NOTES.md 5단계).
BASELINE_MODE = "final"                   # "off" | "calibrate"(AR(1) φ별 회전율 확인, 2026-09-30 완료) | "final"(무작위 500개 본 실행)
A0_SETTING = (60, "equal", "global")      # 사용자 확정(2026-09-30): 개발 구간 선택 규칙 결과. 기준선 실행은 이 파라미터 + cost=base만 허용
RANDOM_SEEDS = 500                        # 계획서 10장: 무작위 점수 Top-N 500개
RANDOM_PHI = 0.913                        # 무작위 점수 AR(1) 계수. 2026-09-30 전체 기간 calibrate(Swimming Yellow Sheep)로 한 번 정해 고정:
                                          # A0 회전율 0.96, φ 0.9→1.04·0.95→0.70 사이 √(1−φ) 보간(선형 보간 0.912와 같은 값)
CALIBRATE_PHIS = (0.0, 0.5, 0.8, 0.9, 0.95, 0.98)   # calibrate에서 시험하는 φ
CALIBRATE_SEEDS = 20                      # calibrate에서 φ마다 돌리는 무작위 장부 수(base 비용만)
RANDOM_SEED_BASE = 20260930               # 난수 씨앗(재현용)
SHADOW_COSTS = ("base", "high")           # 계획서 10장 Q1 ①·②: base와 비용 2배를 같은 난수로 함께 계산
BENCH_TICKERS = ("RSP", "SPY")            # 거래 가능한 투자 대안(RSP, 2003-04 설정)과 시장
IB_FEE_PER_SHARE = 0.005                  # 가상 장부 수수료 = LEAN IB 주식 수수료와 같게: 주당 $0.005, 최소 $1, 최대 거래액의 0.5%
IB_MIN_FEE = 1.0
IB_MAX_FEE_RATE = 0.005
UNIVERSE_CHARTS = False                   # Universe·Universe Flow 차트(시리즈 4개). 무료 계정 한도 10개라 5단계에서는 끔(유니버스 수는 [SUMMARY]에 있음)
