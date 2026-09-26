# 진행 요약 (2026-09-26 기준)

## 작업 방식
- 모든 작업은 `claude/` 안에서만. 기준 문서: `plan_v4.3.md`, 지침: `CLAUDE.md`, 진행 요약: 이 파일.
- 흐름: Claude가 프롬프트 작성 → VS Code Claude 익스텐션이 코드 작성·가짜 QC 시험 → 사용자가 QuantConnect 웹 IDE에 붙여 넣어 실행 → Claude가 로그 점검.
- 단계별 폴더(이전 단계는 백업으로 보존): qc_step1(유니버스), qc_step2(팩터), qc_step3(구성·매매, 작업 예정). test1.py는 분할 전 원본(미사용).
- QC에 올릴 파일: 해당 폴더의 .py 전부(NOTES.md 제외). 같은 이름 탭에 붙여 넣고 Ctrl+S, 맨 위 import 줄로 확인.
  - 실수 사례: factors.py·main.py에 diagnostics.py 내용을 붙여 넣어 circular import / "QCAlgorithm 상속 클래스 없음" 오류.
- "지금까지 내용 정리" 요청 = 이 파일을 업데이트·정리.

## QuantConnect 환경 메모
- 한도: 파일당 32,000자(목표 28,000 이하), 로그 백테스트당 10KB(하루 합계 한도는 불확실), Object Store 쓰기 권한 없음(SAVE_TO_OBJECT_STORE=False).
- self.log는 로그 탭에만, self.debug는 터미널에 나오고 로그 파일에도 기록됨(200자 넘으면 터미널에서 잘림).
- set_runtime_statistic으로 결과 화면 통계 칸에 핵심 숫자 표시 가능.
- 진행률: 파일 탭 줄 오른쪽 ≡ 아이콘 → Backtest Results 목록의 Status(Running: n%).
- "import 문 추가" 창은 Cancel(로컬 파일과 달라지지 않게).
- 서버 일시 오류(Stale file handle 등)는 코드 문제 아님 → 재실행.
- Problems 창의 "not defined" 경고는 `from config import *` 때문에 뜨는 표시일 뿐 실행과 무관.

## 1단계 유니버스 — 완료
- 신호일 = 매월 마지막 거래일(data_date의 다음 거래일이 다른 달일 때만 재구성). first_sig 1998-01-30, 215개월.
- 금융·부동산 0, 상폐 838건 포함(생존편향 없음), 2003년 이후 900~1,039종목, n_avg 968.
- 1998~2002 적격 900 미만(Morningstar 커버리지) → 규칙 유지, 기록만. [START] 확인은 데이터 존재 여부만 봄(적격≥900 조건 제거).
- Morningstar market_cap은 회사 전체 값(BRKA/B 동일) → 클래스 합산 불필요.
- 월말 데이터가 비면 전달 구성 유지 + [WARN].

## 2단계 팩터 — 완료 (전체 기간 QC 실행 확인)
- 모멘텀 12-1, 퀄리티 3개(3/3 필요), 가치 4개(3/4 필요, 결측 1개는 0점), 공시 다음 거래일부터 사용·180일 만료.
- TTM = 분기값 4개 합(twelve_months는 회계연도 연간값이라 대체용으로만).
- 섹터 내 순위 [-1,1] → 스타일 평균 → z(평균0·표준편차1). 20개 미만 섹터는 코드 순서 인접 합침.
- 점수 기간 1999-01~2015-11(203개월): 가격 데이터가 1998-01-02부터라 1998년 점수 없음.
- 결과: 필드 오류 없음, cov_avg 0.93~0.98(1999~), q4 0.88~0.96, IBM·MSFT·XOM 실측 대조 일치(단위 OK).
- 한계: 합병 직후 시총·재무 시점 불일치(예: 1999-12 XOM), history 반복 경고는 의도된 것.
- 관찰: key_log(log+debug) 줄이 로그에 두 번 찍힘 → 3단계에서 debug만 쓰도록 수정.
- 실행 시간 3,370초(데이터 9,100만 건) → 3단계에서 단축 조치.

## 3단계 구성·매매 — 구현 완료, QC 점검 중
- 사용자 결정(결과 보기 전 동결): N=40·60·80 모두, 가중 equal·invvol, 정수 주만, 비용은 3단계=IB 수수료만, 스프레드·저/기본/고 시나리오는 4단계.
- 규칙: 상위 40% 유지 / 상위 20%에서 편입, 유니버스 이탈·점수 결측 보유 종목 매도, 빈자리는 현금, 5% 상한, $200 미만 조정 생략, 다음 거래일 MOC, 수량은 신호일 정보로 계산, 레버리지 없음, 현금 버퍼 1%.
- 파라미터: QC 프로젝트 파라미터 n_holdings·weighting(기본 60·equal).
- 속도 단축: QUICK_TEST(True면 1998~2001), 구독 종목을 보유+매수 예정으로 축소, history 묶음 호출.
- 로그: [REBAL]·[FILL] 처음 두 번, [PYEAR] 연도별, [SUMMARY] + runtime statistic(turnover·fee_pct·avg_hold·cash_avg). [FYEAR] 기본 끔.
- 다음 할 일: 익스텐션 보고 검토 → QUICK_TEST, N=60, equal로 매매 동작 점검 → 전체 기간 → 나머지 5개 조합.
- 3단계 수익률은 스프레드 미포함이라 성과 판단에 쓰지 않음.

### 3단계 중 커버리지 점검 (2026-09-26 추가)
- 목적: 재무 데이터(Morningstar)가 없어 유니버스에서 빠진 대형주가 있는지 확인. 점검일 4번에만 1단계 선별 실행(적격·시총 순위는 당일 데이터만으로 결정되므로 충분).
- QC에 올릴 .py 8개: 새 파일 coverage.py, 바뀐 파일 main.py·config.py, 그대로 universe·factors·portfolio·diagnostics·report.
- coverage.py는 점검 모드가 꺼져 있어도 필수(main.py가 import).
- QC의 config.py에서만 `COVERAGE_CHECK = True`(로컬은 False 유지), 실행 후 반드시 False로 되돌림.
- 판정 기준:
  | 로그 | 정상 | 문제 |
  |---|---|---|
  | 1줄: 재무 없음·가격 $5 이상·거래대금 $100M 이상 종목 수 | 적음(대부분 ETF) | 많음 → 대형주가 재무 없이 누락 |
  | 2줄: 재무 없는 종목 거래대금 상위 20 | SPY·QQQ 등 ETF뿐 | 일반 대형 기업 티커 |
  | 3~4줄: 대형주 30개 상태 | 대부분 #순위(한두 자리) | no_fund·missing 여럿 |
  - 거래대금이 전부 0이면 거래대금 필드 없음 → 별도 보고.
- 상태: 백테스트 "Crying Fluorescent Yellow Baboon"은 **점검 모드가 아니라 QUICK_TEST 매매 점검(N=60, equal)으로 실행됨**(`[COV]` 없음, quick_test=True). QC config.py 저장 누락 추정 → 커버리지 점검은 이후 Alpaca로 재실행 완료(아래). 검토: `results/step3/crying-fluorescent-yellow-baboon/REVIEW.md`.

### 커버리지 점검 결과 (Alert Fluorescent Pink Alpaca, 2026-09-26) — 문제 발견
- 2003-01: 재무 없는 거래대금 상위 20 중 일반 기업 16개. 미국 비금융 대형주 AOL·WYE·VIAB·DD·GM·SGP·BGEN·NVLS 재무 없음. 2007-06: APOL·GM·AA.
  - 공통점: 이후 합병·파산·비상장화로 사라진 회사 → **생존편향 의심**. 2011·2014는 ETF·ADR뿐으로 정상.
- GE: 4개 점검일 모두 `listing` 탈락 → Morningstar ipo_date가 현재 시점 값(미래 날짜)으로 추정.
- DELL: 2003~2011 `mcap` 탈락(시총 없음).
- cut900: 2003 $0.02B(적격 911), 2007 $0.36B, 2011 $0.40B, 2014 $0.82B. NOTES의 2003 $0.19B 기록과 다름 → 확인 필요.
- [M] dollar_volume 확인됨.
- 다음: GE류 ipo_date 영향 수·재무 누락 규모 진단 → 대처 결정(평가 시작 늦춤 / 재무 없는 종목 포함 / 한계로 기록). 상세: `results/step3/alert-fluorescent-pink-alpaca/REVIEW.md`.

### 3단계 QUICK_TEST 매매 점검 결과 (Baboon, N=60 equal, 2001~2004)
- 매매 동작 정상: 첫 매매 2003-02-03 MOC 60종목, 주문 233건 전부 MOC·체결, [FILL] ok, neg·rej·delist 0, 로그 4.9KB.
- [H] 확인: 200자 넘는 [CONFIG]·[SUMMARY] 잘림 없음, runtime statistic 표시됨.
- [REBAL] #1 지문 uni=099d1ab6 zt=116c2e96 → 전체 기간 실행과 비교.
- 관찰: 보유 종목이 소형주 위주(capacity $70k) → 커버리지 문제 가능성. cash_avg 7.1%(정수 주 + $200 생략) → 4단계·운용 예산 때 검토.

## 이후 단계(예정)
- 4단계: 스프레드(Corwin–Schultz 등, 직전 21거래일 추정)·슬리피지, 저/기본/고 비용 시나리오.
- 이후: 기준선(무작위 Top-N 500개, RSP, SPY), IC·â 추정(C안 전제), 검증 프로토콜(10장).

## 남은 Stage 0 결정
- 운용 예산, MDD 판정 기준(제안: 세전 일별), 보유 상한, 브로커·데이터(IBKR 후보, 수수료 요율·소수점·MOC 지원 확인), 손절(−10/−15%/없음)·재진입 5일·익일 MOC(미채택), 세무 조건(미국 시민·한국 거주, kiddie tax 등).
