# 4단계 비용 low(x0.5) 12개 조합 요약 (2026-09-29)

공통: base와 같은 코드, 파라미터 cost=low만 다름(수수료·반스프레드 모두 ×0.5). 결과 폴더: `results/step4/<백테스트 이름>/`.
**#11(80/equal/global)은 데이터 누락으로 무효 → 다시 실행 필요.** 나머지 11개 정상.

## 점검 결과
| # | 조합 (n / 가중 / 점수) | 결과 폴더 | 주문 | 연 비용 평균 (스프레드) | ADV 1% 초과 (최대) | 음수 현금 일수 | 판정 |
|---|---|---|---|---|---|---|---|
| 1 | 60 / equal / sector | focused-tan-salmon | 2,229 | 0.52% (0.37%) | 13 (3.54%) | 0 | 정상 |
| 2 | 60 / invvol / sector | formal-light-brown-horse | 2,412 | 0.51% (0.34%) | 12 (6.19%) | 0 | 정상 |
| 3 | 40 / equal / sector | focused-light-brown-jackal | 1,720 | 0.50% (0.36%) | 10 (2.45%) | 0 | 정상 |
| 4 | 40 / invvol / sector | adaptable-asparagus-salmon | 1,894 | 0.49% (0.34%) | 13 (4.15%) | 22 (2003-07, 최대 −$55) | 정상, 3단계와 같은 현상 |
| 5 | 80 / equal / sector | geeky-brown-flamingo | 2,520 | 0.55% (0.36%) | 11 (2.50%) | 0 | 정상 |
| 6 | 80 / invvol / sector | muscular-violet-frog | 2,660 | 0.52% (0.32%) | 13 (4.16%) | 0 | 정상 |
| 7 | 60 / equal / global | virtual-yellow-kitten | 2,391 | 0.52% (0.36%) | 13 (3.04%) | 0 | 정상 |
| 8 | 60 / invvol / global | casual-red-whale | 2,563 | 0.52% (0.34%) | 17 (4.00%) | 0 | 정상 |
| 9 | 40 / equal / global | casual-brown-hippopotamus | 1,924 | 0.51% (0.37%) | 15 (4.09%) | 0 | 정상 |
| 10 | 40 / invvol / global | retrospective-sky-blue-fish | 2,142 | 0.51% (0.36%) | 19 (4.30%) | 0 | 정상 |
| 11 | 80 / equal / global | square-green-buffalo | 3,247 | 0.64% (0.41%) | 105 (91.9%) | 575 (2010~2015) | **무효 — 재실행** |
| 12 | 80 / invvol / global | dancing-fluorescent-orange-goat | 2,792 | 0.53% (0.32%) | 14 (4.06%) | 0 | 정상 |

공통 확인(#11 제외 11개):
- `[CONFIG]` step=4-costs cost=low x0.5, `[PERF]` costs=low(x0.5), n·weighting·score 표와 일치, quick_test=False.
- `[REBAL] #1` uni=f1a94f20, zt: sector=5ed62ed9 / global=9f45893a (base와 같음).
- `[SUMMARY]` 유니버스 통계 n_min=827 n_avg=971 n_max=1041 short_months=24 — base 12개와 완전히 같음.
- 주문 전부 Filled, rej·late 0, delist 집계 = 상장폐지 청산 수, 로그 7.4~7.9KB, 오류 없음.
- 연 비용 평균 0.49~0.55%로 base(0.98~1.11%)의 약 절반 → 배수가 의도대로 적용됨.

## #11 무효 판정 근거 (square-green-buffalo)
| 항목 | #11 low | 같은 조합 base (determined-brown-pigeon) | 다른 low 11개 |
|---|---|---|---|
| 처리 데이터 포인트 | 78,792,786 | 87,858,892 | 87.6M~88.7M |
| 유니버스 n_min / n_avg | 487 / 817 | 827 / 971 | 827 / 971 |
| short_months (900개 미만 달) | 95 | 24 | 24 |
| 2010-02 리밸런싱 주문 수 | 101 | 14 | — |
| 음수 현금 일수 / 최대 노출 | 575 / 1.10 | 0 / 0.98 | 0~22 / ≤1.002 |

- 2010-01까지는 base와 주문이 거의 같다가, 2010-02부터 유니버스가 줄어 보유 종목을 대거 교체하고 그 뒤 경로가 완전히 갈라짐.
- 유니버스는 비용 설정과 무관하므로(다른 23개 실행 모두 동일), 이 한 번의 실행에서 QC 데이터가 일부 빠진 것으로 판단.
- LEAN 엔진 v18134로 실행됐으나, 같은 버전의 #12(Goat)는 정상이므로 엔진 버전 문제는 아님.
- 조치: 같은 설정(80/equal/global/low)으로 한 번 다시 실행. 코드 변경 없음.
- 재발 확인용 기준: "Processing total of" 데이터 포인트 ≥ 87,000,000, `[SUMMARY]` n_avg=971·short_months=24.

## 비용 시나리오 비교 (CAGR / Sharpe)
| 조합 | 3단계 (수수료만) | low (x0.5) | base (x1.0) | low − base |
|---|---|---|---|---|
| 60 / equal / sector | +13.8% / 0.70 | +13.5% / 0.68 | +12.8% / 0.66 | +0.7%p |
| 60 / invvol / sector | +13.1% / 0.72 | +13.0% / 0.71 | +12.3% / 0.68 | +0.7%p |
| 40 / equal / sector | +12.0% / 0.61 | +11.7% / 0.60 | +11.1% / 0.58 | +0.6%p |
| 40 / invvol / sector | +11.7% / 0.64 | +11.6% / 0.63 | +11.1% / 0.61 | +0.5%p |
| 80 / equal / sector | +13.2% / 0.69 | +13.0% / 0.68 | +12.2% / 0.65 | +0.8%p |
| 80 / invvol / sector | +12.9% / 0.73 | +12.7% / 0.73 | +12.1% / 0.70 | +0.6%p |
| 60 / equal / global | — | +14.0% / 0.69 | +13.4% / 0.67 | +0.6%p |
| 60 / invvol / global | — | +13.3% / 0.70 | +12.8% / 0.68 | +0.5%p |
| 40 / equal / global | — | +12.6% / 0.62 | +12.0% / 0.60 | +0.6%p |
| 40 / invvol / global | — | +12.6% / 0.65 | +12.2% / 0.63 | +0.4%p |
| 80 / equal / global | — | (재실행 대기) | +13.2% / 0.67 | — |
| 80 / invvol / global | — | +13.3% / 0.72 | +12.6% / 0.69 | +0.7%p |
| SPY | +9.1% | | | |

- low − base 차이 +0.4~+0.8%p ≈ 비용 절반(연 0.5%)과 맞음.
- 비용이 절반이 돼도 조합 간 순서는 거의 그대로. invvol이 Sharpe에서 조금 앞서고, global이 CAGR에서 조금 앞서는 경향도 base와 같음.
- 판단용이 아님: 생존편향, 한 번의 경로. 판단은 high까지 끝난 뒤 5단계 기준선 대비로.
