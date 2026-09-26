# Crying Fluorescent Yellow Baboon — 검토 (2026-09-26)

## 이 실행은 무엇인가
- `[CONFIG]` 3단계 줄: `quick_test=True period=2001-01-01~2004-12-31`, `[COV]` 줄 없음, `[SUMMARY]`·`[PERF]` 있음
- → **커버리지 점검이 아니라 3단계 QUICK_TEST 매매 점검(N=60, equal)**. QC의 `config.py`에서 `COVERAGE_CHECK = True`가 저장되지 않은 상태로 실행된 것으로 보임
- 결과적으로 PROGRESS의 "다음 할 일: QUICK_TEST, N=60, equal로 매매 동작 점검"에 해당하는 결과

## 매매 동작 점검 — 정상
| 항목 | 기대 | 결과 | 판정 |
|---|---|---|---|
| `[CONFIG]` 4줄 (200자 초과, 동시 출력) | 잘림·누락 없음 | 4줄 모두 전체 기록 | ✅ ([H] 확인) |
| `[START]` price_match | 표본 50 | 50/50, filing 48 | ✅ |
| `[FACTOR]` | 점수 첫 두 신호일 | 2000-12, 2001-01 | ✅ (q4=0은 빠른 실행 초반 스냅샷 부족, NOTES 기록과 일치) |
| `[SPOT]` | 1999-12·2007-06·2014-12만 | 없음 | ✅ (구간 밖) |
| 첫 매매 | 2003-01 신호 → 2003-02-03 MOC | 동일, new=60 orders=60 | ✅ |
| 주문 | 전부 MOC, 체결 | 233건 전부 MOC·Filled, 무효 0 | ✅ |
| `[FILL]` | 체결가 = 원주가 종가, 10:00 제출 | 10건 모두 ok, 수수료 $1 | ✅ |
| 매도 사유 | band·universe·expired·adjust | band 44, universe 13, expired 7, adjust 46 | ✅ |
| 최저 매수가 | $5 이상 | $5.09 | ✅ |
| 현금 음수·상폐·거부 | 0 | neg=0 delist=0 rej=0 | ✅ |
| 로그 크기 | 10KB 이하 | 4.9KB | ✅ |
| `set_runtime_statistic` | 결과 화면에 표시 | json runtimeStatistics에 turnover·fee_pct·p_cagr 등 기록 | ✅ ([H] 확인) |

- `[REBAL] #1` 지문: `uni=099d1ab6 zt=116c2e96` → 전체 기간 실행에서 같은 값이 나와야 함

## 관찰 (규칙 변경 아님, 기록)
1. **보유 종목이 소형주 위주**: PEGA($5.5), LEIX($6.0), MTRX($8), MSN($7.4) 등. QC 추정 capacity $70,000(최저 PTC).
   NOTES의 cut900 $0.19B(2003)와 같은 현상 → 대형주가 데이터에서 빠져 순위가 아래로 밀렸을 가능성. **커버리지 점검을 실제로 돌려야 하는 이유**.
2. **현금 비중이 높음**: cash_avg 7.1%(2003 5.4%, 2004 8.6%), 목표 버퍼 1%.
   원인: 정수 주 반올림(첫 매수 unbought $641=3.2%) + $200 미만 조정 생략(종목당 약 $330~650이라 생략이 많음: skip 2003 469건, 2004 580건).
   자본 $20,000·N=60에서 생기는 구조적 현금 끌림 → 4단계 비용 분석이나 Stage 0 운용 예산 결정 때 함께 볼 것.
3. **성과 수치는 판단에 쓰지 않음**: p_cagr +42.5% / SPY +21.9%, 2년·스프레드 미포함·소형주 편중. QC 화면의 CAGR 18.5%·beta 0.19는 2001~2002 현금 구간이 섞인 값.

## 다음
1. QC `config.py`에서 `COVERAGE_CHECK = True` → **Ctrl+S 저장 확인** → 실행. 첫 `[CONFIG]` 줄에 `mode=coverage_check`, 기간 2002-12-01~2015-01-31이 보이면 제대로 켜진 것
2. 끝나면 `False`로 되돌리기
3. 커버리지 결과에 따라 유니버스 문제가 없으면 → QUICK_TEST=False 전체 기간(N=60, equal) → 지문 비교 → 나머지 5개 조합
