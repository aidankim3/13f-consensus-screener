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

## 3단계 구성·매매 — 완료 (6개 조합 전체 기간 실행, 2026-09-27)
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
- 2차 진단 코드 작성(Claude 직접, coverage.py·config.py, 로직 변경 없음, 가짜 QC 시험 통과): 탈락 사유 분포·listing future/conflict·mcap 결측·재무 누락 종목 생존율. QC에서 COVERAGE_CHECK=True로 재실행 필요.
- 다음: 2차 진단 결과로 GE류 ipo_date 영향 수·재무 누락 규모 확인 → 대처 결정(평가 시작 늦춤 / 재무 없는 종목 포함 / 한계로 기록). 상세: `results/step3/alert-fluorescent-pink-alpaca/REVIEW.md`.

### 커버리지 2차 진단 결과 (Fat Fluorescent Yellow Antelope, 2026-09-26)
- **생존편향 확정**: 2003→2014 생존율 fund 84%·top900 88% vs no_fund 30%(2007: 87/95/45%, 2011: 94/100/80%). later_fund=0 → 회사 단위로 재무가 통째로 없음. 2014에도 DD·TWX·CBS·SNDK·CHK·BBBY 등 이후 사라진 대형주 재무 없음 → **전 구간 문제**(Alpaca 검토의 "2011·2014 정상"은 정정).
- **시총 결측**: 재무는 있으나 시총 없는 대표 종목 343~501개(DELL·BRCM·XLNX·EMC·CELG·MON 등 이후 인수된 대형주) → 주식 수 필드로 복구 가능성, 3차 진단 작성.
- **상장일 오류**: ipo_date가 미래(GE 2015-11, D 2014-06, HLX 2026-09)인 종목 21~29개, 900위 안 크기 6~9개 → 제안: 상장일 = min(ipo_date, SID 최초 거래일).
- Morningstar만으로 재무 없는 회사는 복구 불가. 결정 대기: (A) 상장일 수정 (B) 시총 대체 계산(3차 진단 후) (C) 생존편향 처리 방침.
- 2026-09-26 **(A) 상장일 수정 적용**(사용자 결정): 상장일 = min(ipo_date, SID 최초 거래일). universe.py 수정 → 유니버스·[REBAL] 지문이 바뀜.
- Smooth Light Brown Bear 실행은 새 coverage.py가 반영되지 않아 Antelope와 동일(3차 진단 미실행). 3차 진단에 대체 시총 검증 줄(share_check) 추가.
- 상세: `results/step3/fat-fluorescent-yellow-antelope/REVIEW.md`.

### 상장일 수정 확인 + 3차 진단 (Dancing Blue Cat, 2026-09-27)
- (A) 상장일 수정 정상: ipo_ignored 86~192개 중 11~26개가 적격으로 복귀, GE #2(2003)~#7(2014). future·conflict 탈락 0.
- (B) 시총 대체: 결측 355~518개 중 97~98%에 주식 수 있음, 만든 시총 현실적(DELL $61.6B, CELG $89.5B). 그러나 검증 ±10% 안 51~82%로 기준(90%) 미달 → **미적용**. 순위 기준 판정(`rank_check`: 상위 900 겹침 ≥95%·far 적음이면 적용) 진단 추가, 다음 실행에서 판정.
- (C) **결정(2026-09-27)**: 생존편향은 한계로 기록하고 진행. 규칙 유지, 성과 판단은 같은 유니버스 기준선(무작위 Top-N) 중심, SPY 대비 절대 수익률은 과대 가능성 명시, 2011년 이후 구간 확인 분석 추가.
- 평가 시작 시점(현재 2003-01) 재검토: rank_check의 with_fill cut900·시총 구간을 보고 결정.
- 상세: `results/step3/dancing-blue-cat/REVIEW.md`.

### 3단계 전체 기간 N=80 invvol (Logical Violet Anguilline, 2026-09-27) — 정상(관찰 1건) → **3단계 완료**
- 지문 동일, 2,681건 전부 체결, delist 8 = 자동 청산 8, neg·rej·late 0.
- 관찰: 첫 달 80종목 중 29종목이 목표 $200 미만이라 생략(현금 29%), 2003 보유 65.7·현금 12.4%, 2006 이후 정상. 자본 $20k ÷ 80종목 + 역변동성의 구조적 한계.
- 참고 성과(판단 금지): CAGR +12.9%, 변동성 19.0%, MDD −48.4%.
- **6개 조합 요약: `results/step3/SUMMARY.md`**. 다음: 4단계(스프레드·슬리피지, 저/기본/고 비용 시나리오) 설계.

### 3단계 전체 기간 N=80 equal (Sleepy Fluorescent Orange Albatross, 2026-09-27) — 정상
- 지문 동일, 보유 78.6~80.0, 2,526건 전부 체결, delist 8 = 자동 청산 8, neg·rej·late 0. 매도 사유 `mom` 1건(점수 결측 매도, 규칙대로).
- 종목당 약 $250이라 생략 거래 최다(8,808), 수수료 0.38%·현금 5.7%로 가장 높음.
- 참고 성과(판단 금지): CAGR +13.2%, 변동성 21.3%, MDD −53.5%.
- 남은 조합: 80/invvol. 상세: `results/step3/sleepy-fluorescent-orange-albatross/REVIEW.md`.

### 3단계 전체 기간 N=40 invvol (Crawling Fluorescent Pink Donkey, 2026-09-27) — 정상(관찰 1건)
- 지문 동일, 보유 39.1~40.0, 1,908건 전부 체결, delist 3 = 자동 청산 3, rej·late 0, 5% 상한 연 0~29회 작동.
- **관찰**: 2003-07 현금 음수 22일(최대 −$25, 노출 1.001). 신호일 가격으로 수량을 정하고 체결일 가격이 달라 생긴 것(규칙대로), IB 마진 계좌라 거부 안 됨. 기록만 함. 실거래 현금 계좌면 거부 가능 → Stage 0 브로커/4단계에서 검토.
- 참고 성과(판단 금지): CAGR +11.7%, 변동성 20.9%, MDD −50.7%.
- 남은 조합: 80/equal, 80/invvol. 상세: `results/step3/crawling-fluorescent-pink-donkey/REVIEW.md`.

### 3단계 전체 기간 N=40 equal (Determined Magenta Salamander, 2026-09-27) — 정상
- 지문 동일, 보유 39.1~40.0, 1,745건 전부 체결, delist 3 = 자동 청산 3, neg·rej·late·cap 0, 현금 3.6%.
- 참고 성과(판단 금지): CAGR +12.0%, 변동성 22.8%, MDD −54.8%.
- 남은 조합: 40/invvol, 80/equal, 80/invvol. 상세: `results/step3/determined-magenta-salamander/REVIEW.md`.

### 3단계 전체 기간 N=60 invvol (Calculating Asparagus Fly, 2026-09-27) — 정상
- 지문 equal과 동일, delist 집계 수정 확인(5건 = 자동 청산 5건), 2,414건 전부 체결, neg·rej·late 0, novol 0, cap 0.
- equal 대비: 첫 달 7종목이 $200 미만이라 생략(다음 달 매수), 현금 5.6%(4.6%), 수수료 0.35%(0.31%).
- 참고 성과(판단 금지): CAGR +13.1%, 변동성 19.9%, MDD −49.5%.
- 남은 조합: 40/equal, 40/invvol, 80/equal, 80/invvol. 상세: `results/step3/calculating-asparagus-fly/REVIEW.md`.

### 3단계 전체 기간 N=60 equal (Crawling Green Chicken, 2026-09-27) — 정상
- [REBAL] #1 지문이 짧은 실행과 동일(uni=f1a94f20 zt=5ed62ed9), 2003~2004 결과 완전히 같음 → 짧은 실행으로 점검한 결과가 전체 실행에 그대로 이어짐.
- 2,277건 전부 체결, neg·rej·late 0, 보유 58.9~60.0, 회전율 평균 0.95, 수수료 0.31%, 현금 4.6%, 3,732초.
- **수정**: delist 집계가 0인데 LEAN 자동 청산 5건 → main.on_order_event에서 'delisting' 태그 체결로 세도록 변경(로그 전용).
- 참고 성과(판단 금지): CAGR +13.8%, MDD −52.1% / SPY +9.1%, −55.2%.
- 다음: 수정한 main.py 반영 → 나머지 5개 조합(N=40·60·80 × equal·invvol 중 60/equal 제외) 전체 기간.
- 상세: `results/step3/crawling-green-chicken/REVIEW.md`.

### 평가 시작 결정 + 상장일 수정 후 QUICK_TEST (Ugly Tan Shark, 2026-09-27)
- **결정(2026-09-27)**: 평가 시작 2003-01 신호일 유지(원래 기준 '적격 ≥ 900'을 2003부터 만족, 데이터 보고 옮기지 않음). 소형주 비중 문제는 2011년 이후 확인 분석으로 점검.
- QUICK_TEST(N=60 equal) 정상: 244건 전부 MOC 체결, [FILL] ok, neg·rej·delist 0, [START] eligible 907(≥900), short_months 5→1.
- 새 [REBAL] #1 지문: uni=f1a94f20 zt=5ed62ed9 → 전체 기간 실행과 비교.
- 관찰: SEB(주가 $543~608)가 종목당 목표 금액보다 비싸 0주로 내림 → 전량 매도(정수 주 규칙, 자본 $20k/60종목). 운용 예산 결정 때 재검토.
- 다음: QUICK_TEST=False 전체 기간(N=60 equal) → 지문 비교 → 나머지 5개 조합.
- 상세: `results/step3/ugly-tan-shark/REVIEW.md`.

### 시총 대체 최종 판정 (Fat Sky Blue Rhinoceros, 2026-09-27) — 적용 안 함
- far 중 상위 900 안 117~173개(기준 ≤45) → 미달. 원인: 주식 수 필드가 현재까지의 분할로 재계산됨(MSFT ×2, WMT ×3, GE ×1/8, AAPL ×28, GOOG ×40 = 이후 분할 배수). 미래 정보라 신호일에 보정 불가 → `MCAP_FILL = False` 고정.
- 팩터는 주당 값을 쓰지 않아 영향 없음. 시총 결측 대형주는 생존편향 한계에 포함.
- 남은 결정: 평가 시작 시점(현재 2003-01, 900위 시총 2003 $0.03B·2007 $0.37B·2014 $0.85B).
- 상세: `results/step3/fat-sky-blue-rhinoceros/REVIEW.md`.

### 시총 대체 순위 판정 (Crying Orange Flamingo, 2026-09-27)
- rank_check: 상위 900 겹침 96.0~97.3%(2007~2014, 2003은 적격 919개라 무의미), far(0.5~2배 밖) 14~35% → 기준("far 적음") 미달, **미적용 유지**.
- 채웠을 때 cut900: 2003 $0.28B / 2007 $0.92B / 2011 $1.02B / 2014 $1.62B (지금 $0.03/0.37/0.40/0.85B).
- 최종 판정 기준(고정): 2007·2011·2014 모두 far 중 상위 900 안 ≤45개이고 체계적 단위 오류 없으면 MCAP_FILL=True. 진단(far 방향·top·예시) 추가.
- 코드 준비: config.MCAP_FILL(기본 False), universe.effective_mcap.
- 상세: `results/step3/crying-orange-flamingo/REVIEW.md`.

### 3단계 QUICK_TEST 매매 점검 결과 (Baboon, N=60 equal, 2001~2004)
- 매매 동작 정상: 첫 매매 2003-02-03 MOC 60종목, 주문 233건 전부 MOC·체결, [FILL] ok, neg·rej·delist 0, 로그 4.9KB.
- [H] 확인: 200자 넘는 [CONFIG]·[SUMMARY] 잘림 없음, runtime statistic 표시됨.
- [REBAL] #1 지문 uni=099d1ab6 zt=116c2e96 → 전체 기간 실행과 비교.
- 관찰: 보유 종목이 소형주 위주(capacity $70k) → 커버리지 문제 가능성. cash_avg 7.1%(정수 주 + $200 생략) → 4단계·운용 예산 때 검토.

## 4단계 거래비용 — 완료 (36회 전부 정상, 2026-09-30)
- 사용자 결정: 스프레드 Abdi–Ranaldo 기본(CS 비교 기록), 저(×0.5)·기본(×1)·고(×2) 시나리오 **각각 실행**, 전역 점수를 파라미터로 추가 → 12개 조합 × 3 = 36회.
- 비용 = 배수 × (IB 수수료 + 반스프레드). 반스프레드 = 신호일까지 21거래일 AR 추정 / 2, 하한 0.5센트/주가, 상한 5%, 추정 없으면 0.5%, 추가 슬리피지 0. LEAN 수수료 모형으로 적용.
- 시장충격 점검: 주문/20일 ADV 최대값·1% 초과 수 기록.
- 가짜 시험: AR은 합성 일봉에서 50bp·200bp 스프레드를 잘 맞추나 10bp는 약 47bp로 과대(보수적). 수수료 모형·대체값·전역 점수 확인.
- QUICK_TEST 비용 점검(Creative Magenta Caribou) 정상: 지문 동일, 추정 60/60, 총비용 − 반스프레드 = 주문 수 × $1 일치, 2003 총비용 1.30%(반스프레드 0.79%, 45bp)·2004 0.96%. 성과 영향 약 −1.1%p/년.
  - 관찰: AR 하한 적용 30%, 주문 > 20일 ADV 1% 체결 8건(최대 2.24%) → 전체 기간에서 빈도 확인 후 시장충격 모형 여부 결정.
- 자동 실행 스크립트(tools/qc_batch.py, QC API) 작성했으나 **QC API 토큰은 유료 조직만 발급**되어 무료 계정에선 사용 불가 → 수동 실행으로 진행(GPT 프롬프트 `docs/PROMPT_gpt_qc_runs.md`).
- **base 12개 전체 기간 완료·점검 정상 (2026-09-28): `results/step4/SUMMARY_base.md`**
  - 12개 모두 설정 일치, 주문 전부 체결, rej·late 0, delist 집계 = 상장폐지 청산 수, 로그 ≤ 8KB. zt: sector 5ed62ed9(3단계 동일), global 9f45893a.
  - 연 비용 평균 0.98~1.11%(스프레드 0.63~0.75%), 2008~09년 최고(1.5~2.0%). 3단계 대비 CAGR −0.6~−1.0%p로 비용 로그와 일치.
  - ADV 1% 초과 조합당 10~19건(주문의 0.5~1%, 최대 5.8%) → **사용자 결정(2026-09-28): 시장충격 모형(Almgren–Chriss) 추가하지 않음.** 제곱근 근사 추정 영향 연 −0.05%p 안팎으로 스프레드 대비 미미, 보수 쪽은 high(×2) 시나리오로 확인. 운용 예산을 크게 늘릴 때(Stage 0) 재검토.
  - 참고 Sharpe 0.58~0.70(sector)·0.60~0.69(global), 차이 작음. 판단은 low/high와 5단계 기준선 이후.
- **low 12개 전체 기간 완료·점검 정상 (2026-09-29): `results/step4/SUMMARY_low.md`**
  - 12개 모두 설정 일치, 유니버스 통계 base와 완전히 같음(n_avg=971, short_months=24), 처리 데이터 포인트 87.6M~88.7M.
  - 연 비용 0.49~0.55%(base의 약 절반), low − base CAGR +0.4~+0.8%p. 조합 간 순서는 base와 거의 같음.
  - 점검 기준 추가: "Processing total of" ≥ 87,000,000, `[SUMMARY]` n_avg=971·short_months=24.
- **high 12개 전체 기간 완료·점검 정상 (2026-09-30): `results/step4/SUMMARY_high.md`** (3개 시나리오 비교표 포함)
  - 12개 모두 설정 일치, 유니버스 통계·데이터 포인트 base·low와 같음. 연 비용 1.95~2.24%(base의 약 2배), high − base CAGR −0.9~−1.3%p.
  - 비용 2배에서도 CAGR 10.0~12.2%(SPY +9.1%, 생존편향 주의). 조합 간 순서는 3개 시나리오에서 거의 같음(40종목 최하, invvol Sharpe·global CAGR 소폭 우위).
  - calm-blue-monkey: 종료 후 QC 자동 분석(PortfolioMarginUsageAnalysis)에서 Runtime Error. 알고리즘은 정상 종료했고 로그·주문·result.json 모두 완전 → 새 엔진 v18139의 사후 분석 버그, 결과 사용에 문제 없음.
  - 관찰: high에서 음수 현금 3개 조합(16~22일, 최대 −$90, 노출 ≤ 1.004) — 비용이 1% 현금 버퍼를 잠깐 넘는 것, 기록만(현금 계좌면 Stage 0에서 버퍼 검토).

## 5단계 기준선 — final 완료, Q1 ④ 미달 확인 (2026-09-30)
- 사용자 결정: ① A0 = **60 / equal / global**(개발 구간 선택 규칙: base 연평균 월수익률 14.50% 최고(월말 수정 후 14.31%), 2위 80/equal/global 14.21%는 0.5%p 이내라 N=60 우선, 60/equal/sector 13.86%는 0.64%p 차이) ② 무작위 대조군 500개는 한 번의 백테스트 안 가상 장부로 계산, 실제 A0 점수 복제 장부로 검증 ③ 개발 구간만(2016년 이후는 Stage 0 동결 뒤).
- 월수익률 추출: `tools/monthly_returns.py` → `results/step4/monthly_returns.csv`(36개 설정 + SPY, 2003-02~2015-12, 155개월).
- `qc_step5/`: `baseline.py`(새) — 무작위 점수 AR(1) Top-N(500 × base·비용 2배), A0 복제 장부(base·high), 단일 팩터 3개, 유니버스 동일가중·역변동성(비례 비용), RSP·SPY. 로그 `[CONFIG] step=5-baseline`·`[SHADOW]`·`[CAL]`·`[RAND]`·`[SFACT]`·`[BENCH]`·`[SECTOR]`, 차트 `Baseline`·`Bench`(월별 지수).
- 합성 데이터 시험 통과(φ↑ → 회전율↓, 비용 0이면 base = high, 분할 연속).
- 실행 순서: ① QUICK_TEST + calibrate(오류 점검) ② 전체 기간 calibrate → φ 결정 ③ 전체 기간 final. 파라미터는 60/equal/global/base 고정.
- 짧은 실행(Crying Asparagus Whale, 2001~2004 calibrate) 정상: A0 실제 매매가 4단계와 같음, 복제 장부 연평균 34.98% vs 실제 34.80%(월 차이 평균 0.03%p). 실행 뒤 Runtime Error는 엔진 v18139 사후 분석 오류로 추정.
  - 수정(사용자 확인, 전체 기간 calibrate부터 적용): 차트 시리즈 한도 10개 초과 → Universe 차트 끔·A0·SPY 차트 제외 / 마지막 달 누락 → 마지막 거래일까지 체결·평가.
- **전체 기간 calibrate(Swimming Yellow Sheep, 수정 전 코드) 정상: `results/step5/swimming-yellow-sheep/REVIEW.md`** — 실제 A0 = 4단계와 동일, 복제 장부 월 차이 평균 0.067%p, 회전율 0.96 = 실제. φ별 회전율 0.9→1.04, 0.95→0.70 → **RANDOM_PHI = 0.913 고정**, BASELINE_MODE=final로 변경.
- **final(Ugly Magenta Shark) 정상: `results/step5/ugly-magenta-shark/REVIEW.md`** — 복제 장부 월 상관 0.9999, 무작위 회전율 0.96 = A0.
  - 개발 구간 참고: A0 − 무작위 평균 +1.10%p(비용 2배 +1.23%p, NW se 1.37%, 백분위 84), A0 − RSP +2.54%p, A0 − 이론 동일가중 유니버스 −0.45%p. 단일 팩터 퀄리티 +14.34%·가치 +14.28%(A0 +14.31%), 모멘텀 +10.51%. 섹터: 경기소비재 +11.5%p.
  - **계획서 Q1 ④(개발 구간): DSR 0.181(< 0.5), PBO 0.706(> 0.5) → 미달.** 12개 설정 모두 같은 가중 유니버스 대비 음수. 무작위(같은 마찰)는 이론 유니버스보다 −1.55%p.
  - 월수익률 도구 수정: QC 일별 점(0시 = 전날 종가) 월말 하루 밀림 → `tools/monthly_returns.py` 고쳐 `monthly_returns.csv` 다시 생성(A0 연평균 14.50 → 14.31%). 같은 가중 유니버스 대비로 선택 규칙 재계산해도 A0 = 60/equal/global 그대로.
  - 통계 도구: `tools/baseline_stats.py`(NW 표준오차, DSR, PBO-CSCV).
- **사용자 결정(2026-09-30): 계획서대로 Q1 불합격(④ DSR·PBO 미달)으로 기록 → 1세대 A0 자리에 RSP(계획서 10장). 결과를 본 뒤 기준은 바꾸지 않음.**
  진단(다음 버전 계획서의 새 실험 후보, 이번 판정에 쓰지 않음): 무작위 대조군 대비 +1.1%p(비용 2배 +1.2%p), 퀄리티·가치 단독 ≈ 합성 점수, 모멘텀 단독 약함, 이론 유니버스 기준선의 마찰 차이(무작위 −1.55%p), PBO는 12개 설정 간 우열이 우연에 가깝다는 신호.

## 6단계 ETF 대체 경로 — 개발 구간 계산 완료 (2026-10-01)
- 사용자 결정(결과 보기 전): 주식 부분 후보 = RSP·SPY(계획서 2장 개정 기록), Stage 0 = 낙폭 한도 30%(세전·일별·달러)·σ_target 10%·B 70/15/15·현금 SGOV(전 T-bill − 0.09%). RSP vs SPY 최종: 로그 성장률 차 90% CI > 0인 쪽, 아니면 SPY.
- `qc_step6/`(새로 작성, 3개 파일): 가상 장부로 A0·M(0~100%)·A1·B × RSP·SPY × base·high. 로그 `[MSTAR]`·`[CAND]`·`[Q2dev]`·`[Q3dev]`·`[Q4dev]`·`[HIGH]`, 차트 9개. 합성 시험 통과.
- **개발 구간 결과(Upgraded Blue Anguilline): `results/step6/upgraded-blue-anguilline/REVIEW.md`** — 현금 대용치 정상(T-bill 평균 1.26%).
  - RSP / SPY: A0 MDD −59.9% / −54.8%(한도 탈락), M* w* = 40% / 45%(**동결**, config MSTAR_FROZEN), A1 샤프 0.59 / 0.60·MDD −24.8% / −23.1%, B 샤프 0.81 / 0.83·MDD −13.8% / −13.9%.
  - Q2dev·Q3dev 두 ETF 모두 통과. 로그 성장률(개발 점추정) B 6.29/6.21% > A1 5.79/5.69% > M* 4.16/3.99%.
- **A2 경기 국면 배분 추가(사용자 확정 2026-10-01, 결과 보기 전)**: 침체 = (실업률 > 12개월 평균 또는 Sahm) 그리고 ETF < 10개월 평균 → 주식 20%·IEF 40%·현금 40%, 그 외 주식 100%. 변형 b = 신용 확대(BAA10Y 6개월 +1%p) 추가. FRED는 QC에서 관측일+1일·최종 수정값으로 들어오므로 월별 지표는 전달 값까지만 사용. 1999~2015 NBER 침체 탐지 정확도도 출력(`macro.py`, `[DETECT]`). 2세대 후보: 과열(물가) 국면, 개별주 호황기 편입.
- A2 첫 실행(Retrospective Magenta Cobra): USREC를 찾지 못해 탐지 정확도만 비어 있었음. 당시 '미래 정보'로 무효 판단했으나 **오진(정정)** — QC는 FRED 값을 관측일 + 1일로 넘겨 하루 늦을 뿐, A2 수치는 유효(다음 실행과 같음).
- **A2 결과(Focused Apricot Salmon): `results/step6/focused-apricot-salmon/REVIEW.md`**
  - 탐지(1999~2015): A2a 침체 월 25/26 적중, 비침체 월 신호 20/177(상당수 2002~2003 약세장), 첫 신호 −7·−1개월. 신용 확대는 추가 효과 없음(A2b = A2a).
  - 배분(2005~2015, base): A2a RSP CAGR +10.38%·샤프 0.75·MDD −22.9%, SPY +10.05%·0.81·−19.7% — 개발 구간 로그 성장률 최고(A0 대비 +2.2~2.8%p), 한도 안, A0 대비 Q2 기준 통과.
  - 주의: 우위가 거의 2008년 한 해(−6% vs −38~−43%)에서 나옴, 회복 초기 상승 일부 놓침. 침체 1회뿐이라 2016년 이후 평가(2020·2022)가 핵심.
- **사용자 결정(2026-10-01): Q4 단순성 순서 M* < A1 < B < A2**(A2는 외부 데이터 의존으로 가장 복잡, Q2 기준 통과가 후보 조건). 계획서 2장 개정 2·config `Q4_ORDER`.
- **사용자 결정(2026-10-01): 위기 재현 손실 = GFC 2008-09~2009-02·COVID 2020-02~03·RATES 2022-01~10 구간 안 최대 손실 ≤ 30%**(평가 기간 안이라 MDD 조건에 포함, 보고용). `[CRISIS]` 줄 추가.
- **사용자 결정(2026-10-01): 진행 방향 = 1세대는 ETF 경로로 마무리(실제 운용 기본안), 개별 종목 전략은 2세대로 따로 설계.**
  2세대 후보 메모: 개선한 종목 선정(퀄리티·가치 중심), 경기 국면(A2)과 결합, 장중 손절 후 다른 종목으로 교체, 과열(물가) 국면. 1998~2015는 이미 본 구간이라 새 시험 집합을 미리 정하고 아직 보지 않은 자료로 검증.
- **사용자 결정(2026-10-01): 운용안 E** = 주식 ETF **장중 매도 = 고점 대비 −10% 추적 손절**(기준 = 매수·재매수 뒤 최고 종가, 일봉 최저가로 판정, 갭 하락이면 시가 체결). **복귀 = 월초 리밸런싱(조건 없음) + 주초 재매수(직전 종가 > 판 가격, 그달 목표 비중까지)**, 손절 당일 복귀 없음. 국채·금·현금은 월별 규칙 그대로. 계획서 2장 개정 4.
  - 코드: `qc_step6` `ELedger`(etf.py), config `E_TRAIL_STOP`·`E_KINDS`, 로그 `[E 티커 구성]`(월별 버전 대비 차·손절/복귀 횟수·현금 대기 일수·위기 손실).
  - **E 결과(Logical Apricot Koala): `results/step6/logical-apricot-koala/REVIEW.md`** — 8개 조합 모두 월별 버전보다 로그 성장률 −1.4~−5.2%p·샤프 −0.20~−0.53. MDD는 M*·B 비슷, A1·A2a 악화(RSP A2a·SPY M* 한도 초과). 손절 연 2회, 대기 평균 1주, 복귀가 판 가격보다 비싸게 사는 휩소. **권고: E 미채택(월별 유지), 사용자 확인 대기.**
  - `[MSTAR]` 격자에 E 장부가 섞여 보이던 보고 버그 수정(w*는 영향 없음).
- 2세대 설계는 1세대 마무리 뒤 시작(사용자 결정 2026-10-01).
- **사용자 결정(2026-10-01): E 제외하고 1세대 동결 → 최종 평가 코드 `qc_step7/`** (계획서 2장 개정 5, 설계 `qc_step7/NOTES.md`).
  - 2005~2026-09-30 한 번 실행, 구간 DEV 2005~2015·VAL 2016~2021·OOS 2022~. 현금은 2020-07부터 실제 SGOV. A2 = 변형 a.
  - 판정: Q2(A1·A2 vs A0)·Q3(B vs A1) 세 구간 기준, Q4 한도(MDD·위기 손실 30%) + 순차 90% CI(M* < A1 < B < A2), RSP vs SPY(CI > 0이면 RSP, 아니면 SPY).
- **1세대 최종 평가 결과(Measured Light Brown Koala): `results/step7/measured-light-brown-koala/REVIEW.md`** — QC 자료가 2026-07-02까지라 OOS = 2022-01~2026-07(259개월).
  - Q2: A1·A2 모두 RSP·SPY에서 불합격(2016+ 샤프가 A0보다 낮고 CVaR/σ 감소 없음). A2는 COVID에서 −34~−39%(월별 지표가 급락을 못 따라감) → 개발 구간 우위는 2008년 한 번이었음.
  - Q3: B가 RSP·SPY 모두 합격(세 구간 모두 A1보다 샤프 +0.08~0.24).
  - Q4: 생존 M*·B, B − M* 90% CI RSP [+0.01%, +3.05%]·SPY [+0.17%, +3.10%] → 둘 다 B. RSP B − SPY B [−1.56%, +0.02%] → **SPY**.
  - **1세대 최종(잠정) = SPY B**(SPY × L(σ 10%) 70% + IEF 15% + GLD 15% + SGOV): 2005~2026-06 CAGR +7.7%·샤프 0.88·MDD −14.4%, 위기 손실 GFC −9.7%·COVID −14.4%·RATES −12.5%, 비용 2배에서도 로그 성장률 +7.3%.
  - 다음: 전향 기간(2026-10~) 추적, 모의투자 3개월 이상 → 소액 실거래(계획서 10장). Stage 0 운영 항목(브로커·세무·예산) 남음. 그다음 2세대 설계.
- 2세대 후보 추가: **ETF 회전**(섹터·팩터·지역 ETF 중 선택, 시점별 ETF 유니버스 — 신규 ETF는 상장 후 예: 12개월부터 편입).
- 남은 일: 1세대 운영 준비(모의투자·Stage 0 운영 항목), 2세대 설계.
- 이후: DSR·PBO(12개 설정, 같은 가중 유니버스 대비), A0 백분위·섹터·회전율 차이 보고.

## 이후 단계(예정)
- 5단계 이후: IC·â 추정(C안 전제), Stage 0 동결 → 검증·의사 OOS(2016~) 1회 평가(10장 Q1~Q4).

## 남은 Stage 0 결정
- 운용 예산, MDD 판정 기준(제안: 세전 일별), 보유 상한, 브로커·데이터(IBKR 후보, 수수료 요율·소수점·MOC 지원 확인), 손절(−10/−15%/없음)·재진입 5일·익일 MOC(미채택), 세무 조건(미국 시민·한국 거주, kiddie tax 등).
