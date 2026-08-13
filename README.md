# 13F 컨센서스 스크리너

SEC EDGAR의 13F-HR 공시를 파싱해 유명 투자자들의 포트폴리오를 교차 비교하는
개인용 로컬 스크리너. "이들이 가장 많이 겹쳐서 들고 있는 종목 / 가장 많이 산
종목 / 가장 많이 판 종목"을 보유자 수·합산 금액·평균 비중 순으로 본다.

## 아키텍처

```
data/        # 다운로드/캐시된 원본, SQLite (git에는 커밋되지 않음)
             #   holdings.db - 13F 보유 데이터, market.db - 티커/가격 캐시
config/      # 투자자 이름 -> CIK 매핑 등 설정 파일
src/edgar/   # EDGAR 다운로드 + 13F 파싱 (순수 함수, Streamlit 의존성 없음)
src/market/  # CUSIP->티커, 가격 조회 (SEC 외부 소스: OpenFIGI/Yahoo Finance,
             #   Streamlit 의존성 없음)
src/analytics/ # 집계·컨센서스·랭킹 로직 (순수 pandas 함수, DataFrame in/out)
src/app/     # Streamlit UI (여기서만 streamlit import)
scripts/     # 수동으로 돌리는 1회성 검증/유틸 스크립트
tests/       # 파싱·집계 단위테스트
```

`src/edgar`, `src/market`, `src/analytics`는 Streamlit을 몰라야 한다 —
나중에 FastAPI 등 다른 서비스로 옮길 수 있게 하기 위함이다.

## 데이터 한계 (UI에도 명시할 것)

13F는 **미국 롱 주식(및 옵션)만** 담는다. 숏 포지션, 채권, 해외 주식, 현금은
13F에 나타나지 않는다 — 이 스크리너가 보여주는 건 "각 투자자의 전체 포트폴리오"가
아니라 "13F에 신고된 미국 롱 익스포저"다.

## 현재까지 구현된 것

### 1단계 — EDGAR 클라이언트 기초

- `src/edgar/client.py`
  - `build_headers()`: SEC가 요구하는 `이름 이메일` 형식의 User-Agent 강제
  - `RateLimiter`: 초당 최대 요청 수를 제한 (기본 8회/초, SEC 한도 10회/초 아래)
  - `EdgarClient.get_submissions(cik)`: `data.sec.gov/submissions/CIK##########.json` 조회
  - `EdgarClient.get_filing_index(cik, accession)` / `get_filing_document(...)`:
    개별 공시 디렉토리(index.json)와 그 안의 문서를 조회
  - `list_13f_filings()`: 제출 목록에서 13F-HR / 13F-HR/A만 추출 (순수 함수)
  - `normalize_cik()`, `filing_archive_dir_url()`: CIK 정규화, Archives 디렉토리 URL 조립

### 2단계 — 최신 13F 보유 내역 수집·정규화·저장

- `config/investors.yaml`: 투자자 6명 (버핏, 애크먼, 버리, 클라만/Baupost,
  테퍼/Appaloosa, 스미스/Fundsmith) — 각 CIK를 EDGAR에서 실조회로 확정하고
  근거를 파일 내 주석으로 남김 (`scripts/verify_investor_ciks.py`로 재검증 가능)
- `src/edgar/fetch.py`
  - `resolve_latest_filings(filings, n)`: 가장 최근 n개 기준일(period)의 공시를
    고르되, 각 기준일마다 더 나중에 제출된 13F-HR/A가 있으면 그것으로 대체
    (amendment 규칙). `resolve_latest_filing()`은 n=1 래퍼로 유지
  - `identify_information_table_filename()`: 공시 디렉토리에서 information
    table XML을 표지 문서(primary_doc.xml)와의 소거법으로 식별 — 파일명이
    `infotable.xml`, `53405.xml`, `Form13FInfoTable.xml` 등 제출대행사마다
    제각각이라 고정 이름을 가정하지 않음
  - `fetch_filing_documents()`: 표지 문서 + information table을 내려받아
    `data/raw/{cik10}/{accession}/`에 캐싱 (manifest.json + 원본 XML). 캐시가
    있으면 재다운로드하지 않음
- `src/edgar/parse.py`
  - `parse_information_table()`: information table XML → DataFrame (원시 단위)
  - `detect_value_unit()`: 금액 단위(천 달러/달러) 탐지. 1차로 표지의
    `<schemaVersion>`을 보되(X01=천 달러, X02+=달러), **실제 종목당 내재
    주가(value/shares)의 중앙값이 비상식적이면(<$1 또는 >$1,000,000) 스키마
    선언을 무시하고 대안 단위로 정정 + 경고 로그**. 이건 이론이 아니라 실제
    발견한 문제다 — Baupost의 2026-03-31 공시는 스키마상 X0202(달러)라고
    선언했지만 실제 값은 여전히 천 달러 단위였고(제출대행사 버그로 추정),
    그대로 믿었으면 알파벳 주식이 주당 $0.29로 계산되는 오류가 났을 것이다.
    (재현 테스트: `tests/test_parse.py::TestDetectValueUnit`)
  - `build_holdings_frame()`: 위 둘을 합쳐 최종 정규화 테이블 생성. PUT/CALL은
    대소문자가 제출자마다 다르므로(`"PUT"` vs `"Put"`) 대소문자 무시 비교로
    `is_option` 플래그를 만들고, `put_call` 컬럼은 대문자로 통일
- `src/edgar/storage.py`: `save_holdings_table()` / `load_holdings_table()` —
  `data/holdings.db`의 `holdings` 테이블에 SQLite로 저장/조회 (매 실행마다 전체 교체)
- `src/analytics/summary.py`: `summarize_by_manager()` — 투자자별 보유 종목 수
  (옵션 제외, distinct CUSIP)·합산 금액·옵션 포지션 수 집계 (순수 DataFrame in/out)
- `src/edgar/build.py`: 전체 파이프라인 CLI 진입점 (아래 실행법 참고). 각
  투자자의 최근 2개 분기를 받아 `period_rank`(0=최신, 1=직전) 컬럼을 붙여
  `holdings` 테이블 하나에 저장 — 분기 비교(quarter_changes)를 위해 필요

### 3단계 — 컨센서스/변화 집계 + Streamlit 화면

- `src/analytics/consensus.py` (순수 pandas, Streamlit 의존성 없음)
  - `consensus_holdings(holdings)`: 종목(cusip)별 `holder_count`(보유자 수),
    `total_value_usd`(합산 금액), `avg_weight_pct`(각자 포트폴리오 내 비중의
    평균), `equal_weight_score`(보유자 수 / 전체 투자자 수 %), `value_weight_score`
    (합산 금액 / 전체 합산 금액 %)
  - `quarter_changes(previous, current)`: 매니저별로 직전·최신 분기를 비교해
    `new_buy`/`add`/`trim`/`sold_out` 4종으로 분류. **가격 변동과 투자 결정을
    분리하기 위해 금액이 아니라 보유 주식수(shares) 변화로 판정**한다 (가격만
    올라서 금액이 늘어난 걸 "매수"로 오판하지 않도록)
  - `top_buys(changes)` / `top_sells(changes)`: 종목 단위로 재집계해 순위표 생성
  - **실제 데이터에서 발견한 버그**: Berkshire 같은 매니저는 같은 종목(같은
    cusip)을 여러 줄로 나눠 신고한다 (보험 자회사별로 투자재량이 분리된 계좌
    — 예: American Express가 한 분기에 3개 행으로 신고됨). 이걸 그대로
    cik+cusip 기준 outer merge하면 3행×3행=9개의 허깨비 "변화"가 생기고
    수치도 크게 부풀려진다. `_consolidate_by_manager()`가 집계 전에 매니저·
    종목별로 먼저 합산해 이 문제를 막는다 (재현 테스트:
    `tests/test_consensus.py`의 `test_split_sub_account_rows_*`)
- `src/app/main.py`: Streamlit 화면 (`streamlit run src/app/main.py`)
  - 탭 3개: 컨센서스 / 최다 매수 / 최다 매도 (표는 `st.dataframe`이라 컬럼
    클릭으로 정렬 가능)
  - 옵션(PUT/CALL) 포함 토글 (기본 제외), 동일가중/금액가중 토글(각 표의 정렬
    기준 컬럼을 보유자수 계열 ↔ 금액 계열로 전환), 최소 보유자/매수자/매도자
    수 슬라이더
  - 상단에 가장 최신 기준일과 "며칠 지남", 투자자별 기준일이 서로 다를 수
    있다는 걸 펼침 표로 표시 (예: Michael Burry는 다른 투자자보다 최신 분기
    공시가 없어 뒤처져 있을 수 있음)
  - 데이터 없을 때(= `build.py`를 아직 안 돌렸을 때) 안내 메시지 표시

### 4단계 — 개별 투자자 상세 화면

- `src/analytics/consensus.py`: `quarter_changes()`의 merge/분류 로직을
  `_build_change_table()`로 추출 (unchanged 행도 포함해서 반환) — `quarter_changes()`는
  거기서 unchanged만 걸러내도록 리팩터링, 동작은 그대로 유지 (기존 테스트로 확인)
- `src/analytics/investor.py` (순수 pandas)
  - `investor_portfolio(previous, current)`: 단일 매니저(cik 1개)의 전체
    포트폴리오. `_build_change_table()`을 재사용하되 `quarter_changes()`와
    달리 **unchanged 행도 유지**하고 **sold_out 행도 금액 0으로 남겨서** "이번
    분기에 이 종목을 팔았다"는 게 표에서 사라지지 않고 보이게 함
  - `portfolio_summary(portfolio, current_holdings_with_options)`: 종목 수
    (sold_out 제외), 상위 10종목 집중도(%), 대략적 회전율(%), 옵션 비중(%).
    **옵션 비중은 옵션 포함 토글과 무관하게 항상 원본 데이터로 계산** —
    그래야 "옵션 제외" 상태에서도 이 매니저가 실제로 옵션을 얼마나 쓰는지
    알 수 있음 (예: Michael Burry는 이 지표가 95%대로 나옴 — 실제로 옵션
    비중이 매우 높은 스타일이라 실데이터로 검증됨)
  - 회전율은 정식 금액가중 turnover가 아니라 "종목 교체 비율"의 근사치임을
    독스트링에 명시 (`(신규+매도 건수) / (직전 보유 + 현재 보유 건수) * 100`),
    직전 분기 데이터가 없으면 NaN
- `src/app/main.py`: 사이드바에 투자자 선택 selectbox 추가, 4번째 탭
  "투자자 상세" 추가 — 요약 지표 4개(`st.metric`), 비중 상위 15종목
  막대그래프(`st.bar_chart`), 전체 포트폴리오 표(종목/비중/금액/주식수/
  변화(신규·추가·축소·매도·유지)/변화%p)

### 5단계 — 진입가 추정 + 겹침/유사도 분석

- `src/market/` (SEC EDGAR 전용이 아닌 시장 데이터 계층 — Streamlit 의존성 없음,
  네트워크+디스크 캐싱이 있다는 점에서 `src/edgar/fetch.py`와 성격이 같음)
  - `ticker_map.py`: **CUSIP→티커 매핑**. 1차로 [OpenFIGI](https://www.openfigi.com/api)
    무료 매핑 API(API 키 불필요, 배치 10개/요청·분당 약 23회로 레이트리밋)를
    사용 — 같은 종목의 여러 상장(exchCode)이 반환되면 "US"(복합 상장)를
    우선 선택. 실패한 CUSIP은 SEC `company_tickers.json`(전체 등록 회사의
    공식 티커 목록) 기준 정규화된 회사명 정확매칭으로 폴백. 결과는
    `data/market.db`의 `cusip_ticker_map` 테이블에 **영구 캐싱**(같은 CUSIP은
    다시 조회 안 함). 실제 CUSIP 4개(AAPL/GOOGL/GOOG/AMZN)와 폴백 경로
    모두 실네트워크로 검증 완료
  - `prices.py`: yfinance로 (1) **추정 진입가** = 보유 분기의 첫 거래일 시가와
    마지막 거래일 종가의 평균, (2) **현재가** = 최근 종가. 둘 다 실패해도
    예외를 던지지 않고 `None` 반환 — 존재하지 않는 티커로 실네트워크
    검증 완료. 분기 가격은 영구 캐싱(과거 분기 가격은 안 바뀜), 현재가는
    1시간 TTL로 캐싱
- `src/analytics/entry_price.py`: `with_entry_price_comparison(portfolio, prices)` —
  포트폴리오 표에 티커/진입가/현재가/차이(%)를 붙이는 순수 함수(가격이 없는
  종목도 행을 지우지 않고 차이는 NaN으로 둠). **이 추정은 실제 매입가가
  아니라 근사치라는 점을 UI에 명시**
- `src/analytics/overlap.py` (순수 pandas)
  - `pairwise_overlap(portfolio_a, portfolio_b)`: 두 매니저의 종목별 관계를
    `common`(공통 보유)/`only_a`/`only_b`로 분류하고, 이번 분기에 한쪽은
    매수(신규·추가)·한쪽은 매도(축소·매도)한 경우를 `opposite_trade` 플래그로
    별도 표시 (관계 분류와 독립적 — 한쪽이 완전 매도해서 더 이상 "공통 보유"가
    아니어도 반대매매였다는 사실은 남겨야 하므로)
  - `jaccard_similarity(holdings_a, holdings_b)`: 두 매니저의 현재 보유
    종목 집합의 자카드 지수(교집합/합집합, 0~1)
  - `similarity_matrix(current_holdings)`: 전체 매니저 쌍에 대한 N×N 자카드
    유사도(%) 행렬, 대각선은 100
- `src/app/main.py`
  - "투자자 상세" 탭에 "현재가 vs 추정 진입가" 섹션 추가 — 체크박스로만
    켜짐(불필요한 외부 API 호출 방지), 현재 보유 종목만 온디맨드로 조회
  - 새 탭 "겹침 분석": 투자자 2명 선택 → 자카드 유사도 지표, 공통/한쪽만
    보유/반대매매 표 4개, 그리고 전체 투자자 쌍 자카드 히트맵
    (`pandas.Styler.background_gradient` — matplotlib 필요)

### 6단계 (마지막) — 신규 공시 알림 + 정직한 백테스트

- `src/edgar/client.py`
  - `list_13f_filings()`을 일반화한 `list_filings(submissions, form_types)` 추가
  - `list_activist_filings()`: 13D/13G(+수정) 필터링. **실데이터로 확인한 사실**:
    EDGAR는 같은 폼을 시대에 따라 두 가지로 표기한다 — 2025년 이후는
    `SCHEDULE 13D`/`SCHEDULE 13G(/A)`, 그 이전은 `SC 13D`/`SC 13G(/A)`
    (Appaloosa LP의 실제 제출 이력에서 둘 다 확인). 둘 다 포함
- `src/edgar/seen_store.py`: 어떤 공시를 이미 알림 보냈는지 SQLite로 추적
  (`data/seen_filings.db`). **최초 실행은 그 시점까지의 모든 과거 공시를
  베이스라인으로만 기록하고 알림을 보내지 않는다** — 안 그러면 몇 년치
  공시 이력이 전부 "신규"로 쏟아진다. 두 번째 실행부터 진짜 신규만 감지.
  13F와 13D/13G는 `{cik}:13F` / `{cik}:13D-G`로 독립적으로 추적
- `src/jobs/refresh.py`: `python -m src.jobs.refresh` — 투자자별 13F +
  13D/13G를 확인해 콘솔 출력 + `data/logs/refresh_{시각}.log` 파일 로그.
  `SMTP_HOST`/`ALERT_EMAIL_TO` 환경변수가 설정된 경우에만 이메일 발송(기본
  비활성, 실전송은 자격증명이 없어 테스트하지 않음 — 발송 실패해도 잡 자체는
  안 죽음). **실제 검증**: 최초 실행 후 seen_filings.db에서 Berkshire의
  최신 13F-HR 레코드를 지워 "신규 공시"를 인위 재현 → 재실행 시 정확히
  그 1건만 알림으로 잡히고, 그다음 실행에선 다시 안 잡히는 것까지 확인함
- `src/edgar/build.py`: 수집 범위를 2→8분기로 확장 (백테스트에 여러
  리밸런싱 시점이 필요해서). **실제 데이터에서 발견한 세 번째 버그**:
  Berkshire의 2025-03-31 13F-HR/A는 `amendmentType=NEW HOLDINGS`로,
  기밀취급 신청이 만료되어 뒤늦게 공개된 포지션 4건만 담고 있었다 —
  분기 전체 재제출이 아니다. 최신 amendment로 무조건 대체하던 기존 로직은
  이걸 "이번 분기 전체 보유"로 오인해 114개 종목을 4개로 축소시켰다
  (Bill Ackman의 2024-12-31 분기도 동일 문제, 11개→1개). `parse.py`에
  `is_partial_amendment()`(schemaVersion처럼 cover page의
  `<amendmentType>`를 확인)와 `combine_raw_tables()`를 추가해, 이런
  amendment를 만나면 같은 분기의 원본 13F-HR과 자동으로 병합하도록 수정
  (재현 테스트: `tests/test_parse.py::TestIsPartialAmendment`,
  `TestCombineRawTablesAndBuildFromRaw`) — 수정 후 재실행해 114개/11개로
  정상 복구됐음을 확인
- `src/market/prices.py`: `get_price_history()` — 일별 종가 시계열 조회 +
  SQLite 캐싱 (요청 구간의 90% 이상이 이미 캐시에 있으면 재조회 안 함).
  SPY 실데이터로 검증
- `src/analytics/backtest.py` (순수 pandas, 네트워크 없음 — 가격은 호출부가
  미리 받아서 넘김)
  - `consensus_asof_schedule(holdings, top_n)`: 분기마다 컨센서스 상위
    N종목과, **그 분기 정보가 실제로 전부 공개된 시점**(추적 중인
    투자자들 중 가장 늦게 제출한 `filing_date`)을 계산. 이게 바로
    "낙관적 백테스트를 만들지 말라"는 요구사항을 지키는 핵심 로직 —
    기준일이 아니라 이 시점부터 가격을 사용
  - `simulate_portfolio(price_history, rebalances, cost_bps)`: 동일가중
    리밸런싱 포트폴리오 시뮬레이션. 회전율은 `investor.portfolio_summary()`
    와 같은 "종목 교체 비율" 정의를 재사용해 앱 전체에서 일관성 유지.
    거래비용은 리밸런싱마다 회전율에 비례한 1회성 차감으로 근사
  - 합성 데이터로 13개 단위테스트 (턴오버 계산, 복리 체인 등을 직접
    손으로 계산해 검증)
- `src/app/main.py`: 새 탭 "백테스트" — 상위 N종목/거래비용(bps) 입력 →
  실행 버튼(온디맨드, 외부 가격 다수 조회라 시간 소요) → 누적 수익률
  그래프(전략 vs SPY), 리밸런싱별 회전율 표, 45일 초과 지연 제출 경고,
  한계(생존편향·롱 전용·근사 가격·소규모 표본·거래비용 가정) 명시

**실행 결과 검증**: 실제로 백테스트를 돌려본 결과(2024-02~2026-05, 상위
10종목, 거래비용 10bps) 전략 누적수익률 65.4% vs SPY 60.5% (10회
리밸런싱). 45일 지연 경고가 정확히 위에서 고친 두 NEW HOLDINGS 분기
(106일, 136일 — 기밀취급 만료로 인한 정당한 지연)에서만 뜬 것도 확인해
로직이 실제로 의도대로 작동함을 재확인했다.

**교차검증 (Dataroma)**: Berkshire Hathaway 2026-03-31 데이터를
[Dataroma](https://www.dataroma.com/m/holdings.php?m=BRK)와 대조 —
종목 수(29), 총 포트폴리오 가치($263.1B), AMEX/AAPL/KO/BAC/CVX 각각의
주식수·비중이 전부 일치함을 확인 (금액은 Dataroma가 천 달러 단위로
반올림 표시하는 차이만 있음). AMEX의 경우 원본 SEC XML에 3개 자회사
계좌로 분할 신고된 주식수(1,149,942 + 149,061,045 + 1,399,713)의 합이
Dataroma가 보여주는 151,610,700주와 정확히 일치함도 직접 확인했다.

## 실행 순서

전체 흐름은 **데이터 빌드 → 앱 실행 → (주기적으로) 새로고침 잡** 이다.

```powershell
# ── 최초 설치 (1회) ──────────────────────────────────────────
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# investors.yaml의 CIK가 실제 EDGAR 데이터와 일치하는지 확인
# (네트워크 필요, investors.yaml을 수정했을 때만 다시 실행)
.\.venv\Scripts\python.exe scripts\verify_investor_ciks.py

# 단위테스트 (네트워크 불필요 — tests/fixtures/*.xml에 캡처된 실제
# EDGAR 데이터로 검증)
.\.venv\Scripts\python.exe -m pytest tests/ -v


# ── 1. 데이터 빌드 ───────────────────────────────────────────
# 투자자별 최근 8개 분기 13F를 받아 data/holdings.db에 저장 (네트워크
# 필요, data/raw/에 캐시되어 있으면 재다운로드 안 함). 컨센서스·변화
# 분석은 최신 2개 분기, 백테스트는 8개 분기 전부를 사용한다.
.\.venv\Scripts\python.exe -m src.edgar.build


# ── 2. 앱 실행 ──────────────────────────────────────────────
# 위 빌드가 최소 1번은 끝나 있어야 함 (data/holdings.db 필요)
.\.venv\Scripts\python.exe -m streamlit run src\app\main.py
# 브라우저에서 http://localhost:8501 로 열림
# "투자자 상세" 탭의 진입가 비교, "백테스트" 탭은 최초 실행 시 티커
# 매핑(OpenFIGI/SEC)과 가격(Yahoo Finance)을 추가로 조회하며,
# data/market.db에 캐싱되어 이후 실행은 빨라진다


# ── 3. 새로고침 잡 (신규 공시 알림) ──────────────────────────
# 13F(분기 공시) + 13D/13G(근실시간 활동주의/5%+ 지분 공시)를 확인해
# 새 공시가 있으면 콘솔 + data/logs/refresh_*.log 에 남긴다.
# 최초 실행은 알림 없이 베이스라인만 기록하니, 반드시 한 번 먼저
# 돌려둘 것.
.\.venv\Scripts\python.exe -m src.jobs.refresh

# 주기적으로 돌리려면 OS 스케줄러에 위 명령을 등록한다. Windows
# 작업 스케줄러 예시 (매일 오전 8시, PowerShell에서 실행):
#   schtasks /create /tn "13F Refresh" /sc daily /st 08:00 /tr "'C:\Users\aidan\projects\13f-consensus-screener\.venv\Scripts\python.exe' -m src.jobs.refresh"

# (선택) 이메일 알림을 받으려면 실행 전 환경변수를 설정한다:
#   $env:SMTP_HOST = "smtp.example.com"
#   $env:SMTP_USER = "you@example.com"
#   $env:SMTP_PASSWORD = "..."
#   $env:ALERT_EMAIL_TO = "you@example.com"
# 설정하지 않으면 이메일 없이 콘솔/파일 로그만 남는다 (기본값).
```

## 배포

**실제 배포된 사이트**: https://one3f-consensus-screener.onrender.com
(Render.com 무료 티어 — 일정 시간 요청이 없으면 슬립 상태가 되고, 다음
접속 시 깨어나는 데 30~60초 정도 걸릴 수 있다)

GitHub: https://github.com/aidankim3/13f-consensus-screener

data/holdings.db 같은 로컬 캐시는 `.gitignore`로 제외되어 저장소에 없다 —
배포된 인스턴스는 처음 열릴 때 (또는 사이드바 "데이터 관리"에서 언제든)
"지금 EDGAR에서 데이터 가져오기" 버튼으로 직접 SEC EDGAR/OpenFIGI/Yahoo
Finance에서 데이터를 받아 스스로 초기화한다 (`src/app/main.py`의
`_build_data_inline()`이 `src/edgar/build.py`의 파이프라인을 그대로 재사용).

### Render.com (현재 사용 중)

Render API로 생성한 웹 서비스 설정:
- Runtime: Python, Region: Oregon, Plan: Free
- Build command: `pip install -r requirements.txt`
- Start command: `streamlit run src/app/main.py --server.port $PORT --server.address 0.0.0.0`
- `main` 브랜치에 푸시하면 자동 재배포(`autoDeploy: yes`)

관리 대시보드: https://dashboard.render.com/web/srv-d9utfinqj5pc738fk63g

### Streamlit Community Cloud (대안, 무료·슬립 없음)

1. https://share.streamlit.io 에서 GitHub 계정으로 로그인
2. "Create app" → 저장소 `aidankim3/13f-consensus-screener`, 브랜치 `main`,
   Main file path `src/app/main.py` 선택 후 "Deploy"
3. 배포된 사이트에서 최초 1회 "지금 EDGAR에서 데이터 가져오기" 버튼 클릭
   (1~2분 소요)

`src/jobs/refresh.py`(신규 공시 알림 잡)는 Streamlit Community Cloud가
지속적인 백그라운드 크론을 지원하지 않으므로 별도 서버나 로컬 스케줄러
(작업 스케줄러/cron)에서 돌려야 한다 — 위 "실행 순서" 참고.

## SEC EDGAR 사용 시 규칙 (반드시 준수)

- 모든 요청에 `이름 이메일` 형식의 User-Agent 필수 (`build_headers()`가 강제).
- 초당 10요청을 넘기지 않는다 (`RateLimiter` 기본 8요청/초).
- CIK로 투자자를 식별하며, 이름→CIK 매핑은 `config/investors.yaml`에서 관리.
  새 투자자를 추가하면 반드시 `scripts/verify_investor_ciks.py`로 검증할 것 —
  이름만 보고 CIK를 추측해 넣지 않는다.
