# 6단계(Q1 불합격 대체 경로: 주식 부분 = RSP·SPY ETF + 변동성 제어·방어 자산·현금 혼합) 설정 상수. 배경은 NOTES.md.
from datetime import date

# --- 구간 (계획서 10장: RSP 대체 분기의 개발 구간은 2005~2015, B는 GLD 설정 뒤 2004-12부터) ---
DEV_PERIOD_LAST_DAY = date(2015, 12, 31)  # 2016년 이후(검증·의사 OOS)는 Stage 0 동결 전 사용 금지
START_DATE = date(1998, 1, 2)             # A2 탐지 정확도(1999~)·σ̂·스프레드 준비. 장부 평가는 FIRST_SIGNAL 월말부터(이전 결과와 같음)
END_DATE = date(2015, 12, 31)
FIRST_SIGNAL = (2004, 12)                 # 첫 신호 = 2004-12 마지막 거래일, 첫 체결 = 2005-01 첫 거래일
INITIAL_CASH = 20_000                     # 계획서 0장: 초기 자본(달러)

# --- 자산 ---
EQUITY_TICKERS = ("RSP", "SPY")           # 사용자 결정(2026-10-01): 주식 부분 후보 = RSP, SPY(같은 규칙으로 각각 계산)
BOND_TICKER = "IEF"                       # 계획서 7장 B: 중기 국채
GOLD_TICKER = "GLD"                       # 계획서 7장 B: 금(2004-11-18 설정)
CASH_FEE = 0.0009                         # 현금 대용치 = 1개월 T-bill − SGOV 수준 보수(연 0.09%), 계획서 7장
CASH_DAY_COUNT = 365                      # 재무부 CMT(채권 환산 수익률) → 실제 일수/365로 일할

# --- Stage 0 (사용자 확정 2026-10-01, 계획서 제안값) ---
DD_LIMIT = 0.30                           # 계좌 최대 낙폭 한도(세전·일별·달러)
SIGMA_TARGET = 0.10                       # A1 목표 변동성(연)
B_WEIGHTS = (0.70, 0.15, 0.15)            # B = A1 70% + IEF 15% + GLD 15%
MSTAR_STEP = 0.05                         # M* 주식 비중 탐색 간격(5%p)
MSTAR_FROZEN = {"RSP": 0.40, "SPY": 0.45}  # 2026-10-01 개발 구간(Upgraded Blue Anguilline)에서 MDD ≤ 30%인 최대 비중, 동결(계획서 10장)

# --- A1 변동성 예측 (계획서 7장: 포트폴리오 일간 수익률 EWMA, 반감기 20거래일, 월 1회만 배수 변경) ---
SIGMA_HALF_LIFE = 20
SIGMA_WINDOW = 126                        # 최근 126거래일
SIGMA_MIN_OBS = 60
TRADING_DAYS_PER_YEAR = 252

# --- 비용 (계획서 9장: 수수료 + 반스프레드, 저·기본·고 시나리오; 4단계와 같은 추정) ---
COST_SCENARIOS = {"base": 1.0, "high": 2.0}   # 판정은 base, high는 민감도
SPREAD_WINDOW = 21                        # 직전 21거래일 Abdi–Ranaldo 추정(신호일까지)
TICK_SIZE = 0.01
MAX_REL_SPREAD = 0.10
DEFAULT_HALF_SPREAD = 0.0005              # 추정이 없으면 ETF 5bp
IB_FEE_PER_SHARE = 0.005                  # LEAN IB: 주당 $0.005, 최소 $1, 최대 거래액의 0.5%
IB_MIN_FEE = 1.0
IB_MAX_FEE_RATE = 0.005
MIN_TRADE_VALUE = 200.0                   # 계획서 6·9장: $200 미만 조정 생략

# --- A2 경기 국면 배분 (사용자 확정 2026-10-01, 결과 보기 전. NOTES.md) ---
# 침체 = 경기 악화(실업률 > 12개월 평균 또는 Sahm) 그리고 주가 추세 악화(월말 종가 < 10개월 평균). 변형 b는 경기 악화에 신용 확대 추가.
A2_VARIANTS = ("a", "b")
A2_RECESSION_WEIGHTS = {"equity": 0.20, BOND_TICKER: 0.40}   # 나머지 40%는 현금. 확장 국면은 주식 100%
FRED_SERIES = ("UNRATE", "BAA10Y", "USREC")  # USREC(NBER 침체 월)는 탐지 정확도 평가에만 사용
UNRATE_SMA_MONTHS = 12
SAHM_THRESHOLD = 0.5                       # 3개월 평균 − 직전 12개월의 3개월 평균 최저 ≥ 0.5%p
SAHM_LOOKBACK = 12
CREDIT_WIDEN = 1.0                         # BAA10Y가 6개월 전보다 1.0%p 이상 확대
CREDIT_LOOKBACK_DAYS = 182
PRICE_SMA_MONTHS = 10
DETECT_PRICE = "SPY"                       # 탐지 정확도 평가의 가격 신호(1998~ 자료가 있는 SPY)
Q4_ORDER = ("M*", "A1", "B", "A2")       # 사용자 결정(2026-10-01): Q4 단순성 순서(앞이 단순). 다음 후보는 로그 성장률 차 90% CI > 0일 때만
CRISIS_WINDOWS = (("GFC", date(2008, 9, 1), date(2009, 2, 28)),     # 사용자 결정(2026-10-01): 위기 재현 손실 구간
                  ("COVID", date(2020, 2, 1), date(2020, 3, 31)),   # 구간 안 고점 대비 최대 손실이 모두 DD_LIMIT 이내여야 함(Q4)
                  ("RATES", date(2022, 1, 1), date(2022, 10, 31)))  # 개발 구간 실행에서는 GFC만 계산됨
