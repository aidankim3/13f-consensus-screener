# 4단계 비용 high(x2.0) 12개 조합 요약 + 비용 시나리오 3종 비교 (2026-09-30)

공통: base와 같은 코드, 파라미터 cost=high만 다름(수수료·반스프레드 모두 ×2.0). 결과 폴더: `results/step4/<백테스트 이름>/`.
12개 모두 정상.

## 점검 결과
| # | 조합 (n / 가중 / 점수) | 결과 폴더 | 주문 | 연 비용 평균 (스프레드) | ADV 1% 초과 (최대) | 음수 현금 일수 | 판정 |
|---|---|---|---|---|---|---|---|
| 1 | 60 / equal / sector | formal-red-bat | 2,048 | 2.11% (1.46%) | 12 (3.26%) | 0 | 정상 |
| 2 | 60 / invvol / sector | measured-violet-panda | 2,201 | 2.05% (1.33%) | 12 (5.71%) | 16 (2003-03, 최대 −$11) | 정상 |
| 3 | 40 / equal / sector | calm-black-badger | 1,568 | 1.99% (1.43%) | 10 (2.45%) | 21 (2011-12, 최대 −$83) | 정상 |
| 4 | 40 / invvol / sector | geeky-brown-donkey | 1,735 | 1.95% (1.33%) | 11 (4.06%) | 22 (2003-07, 최대 −$90) | 정상 |
| 5 | 80 / equal / sector | emotional-blue-bull | 2,390 | 2.24% (1.44%) | 10 (2.31%) | 0 | 정상 |
| 6 | 80 / invvol / sector | dancing-orange-beaver | 2,478 | 2.11% (1.25%) | 13 (3.64%) | 0 | 정상 |
| 7 | 60 / equal / global | virtual-fluorescent-yellow-cow | 2,177 | 2.05% (1.41%) | 10 (3.04%) | 0 | 정상 |
| 8 | 60 / invvol / global | geeky-brown-owlet | 2,373 | 2.06% (1.32%) | 14 (4.00%) | 0 | 정상 |
| 9 | 40 / equal / global | energetic-fluorescent-orange-shark | 1,761 | 2.04% (1.47%) | 14 (3.92%) | 0 | 정상 |
| 10 | 40 / invvol / global | calm-light-brown-owlet | 1,963 | 2.04% (1.40%) | 19 (4.30%) | 0 | 정상 |
| 11 | 80 / equal / global | retrospective-asparagus-mule | 2,447 | 2.16% (1.38%) | 13 (5.07%) | 0 | 정상 |
| 12 | 80 / invvol / global | calm-blue-monkey | 2,575 | 2.12% (1.27%) | 14 (3.87%) | 0 | 정상 (QC 사후 분석 오류, 아래) |

공통 확인(12개 모두):
- `[CONFIG]` step=4-costs cost=high x2.0, `[PERF]` costs=high(x2.0), n·weighting·score 표와 일치, quick_test=False.
- `[REBAL] #1` uni=f1a94f20, zt: sector=5ed62ed9 / global=9f45893a (base·low와 같음).
- `[SUMMARY]` 유니버스 통계 n_min=827 n_avg=971 short_months=24, 처리 데이터 포인트 87.6M~88.7M — base·low와 같음.
- 주문 전부 Filled, rej·late 0, delist 집계 = 상장폐지 청산 수, 로그 7.4~7.9KB.
- 연 비용 평균 1.95~2.24%로 base(0.98~1.11%)의 약 2배 → 배수가 의도대로 적용됨. 2008~09년은 연 2.9~4.0%.

## calm-blue-monkey의 Runtime Error
- 오류 위치: `QuantConnect.Lean.Engine.Results.Analysis.Analyses.PortfolioMarginUsageAnalysis`(QC가 백테스트가 끝난 뒤 돌리는 자동 분석, "Research Guide" 제안용). 우리 코드(main.py 등)가 아님.
- 알고리즘은 정상 종료: 로그에 `[PERF]`·`[SUMMARY]`·"completed in 3895 seconds" 출력, 처리 데이터 포인트 88,660,762(같은 조합 base 88,661,115와 같은 수준).
- result.json 통계 27개·주문 2,575건(2003-02-03~2015-12-01)·거래·차트 10개 모두 다른 실행과 같은 구조.
- 이 실행만 LEAN 엔진 v2.5.0.0.18139(나머지 11개는 v18134)로 돌았음 → 새 엔진의 사후 분석 버그로 판단. 결과 사용에 문제 없음.
- Research Guide의 "163 Parameters Detected / Likely Overfitting"은 코드의 숫자 상수 개수를 센 자동 경고라 판단에 쓰지 않음.

## 비용 시나리오 3종 비교 (CAGR / Sharpe)
| 조합 | low (x0.5) | base (x1.0) | high (x2.0) | high − base |
|---|---|---|---|---|
| 60 / equal / sector | +13.5% / 0.68 | +12.8% / 0.66 | +11.5% / 0.60 | −1.3%p |
| 60 / invvol / sector | +13.0% / 0.71 | +12.3% / 0.68 | +11.2% / 0.63 | −1.1%p |
| 40 / equal / sector | +11.7% / 0.60 | +11.1% / 0.58 | +10.0% / 0.54 | −1.1%p |
| 40 / invvol / sector | +11.6% / 0.63 | +11.1% / 0.61 | +10.1% / 0.57 | −1.0%p |
| 80 / equal / sector | +13.0% / 0.68 | +12.2% / 0.65 | +11.3% / 0.61 | −0.9%p |
| 80 / invvol / sector | +12.7% / 0.73 | +12.1% / 0.70 | +10.8% / 0.63 | −1.3%p |
| 60 / equal / global | +14.0% / 0.69 | +13.4% / 0.67 | +12.2% / 0.62 | −1.2%p |
| 60 / invvol / global | +13.3% / 0.70 | +12.8% / 0.68 | +11.7% / 0.63 | −1.1%p |
| 40 / equal / global | +12.6% / 0.62 | +12.0% / 0.60 | +10.7% / 0.55 | −1.3%p |
| 40 / invvol / global | +12.6% / 0.65 | +12.2% / 0.63 | +11.1% / 0.59 | −1.1%p |
| 80 / equal / global | +13.7% / 0.69 | +13.2% / 0.67 | +12.1% / 0.63 | −1.1%p |
| 80 / invvol / global | +13.3% / 0.72 | +12.6% / 0.69 | +11.5% / 0.64 | −1.1%p |
| SPY | +9.1% | | | |

- high − base −0.9~−1.3%p ≈ 추가 비용(연 약 1%)과 맞음. 비용 1%p당 CAGR 약 1.1%p 감소로 3개 시나리오가 거의 직선.
- 비용 2배에서도 12개 모두 CAGR 10.0~12.2%로 SPY(+9.1%)보다 높음. 단 생존편향으로 SPY 대비 절대 수준은 과대 가능성 → 5단계 같은 유니버스 기준선 대비로 판단.
- 조합 간 순서는 세 시나리오에서 거의 같음: 40종목이 CAGR·Sharpe 모두 가장 낮고, invvol이 Sharpe에서, global이 CAGR에서 조금 앞섬. 차이(Sharpe 0.54~0.64)가 작아 한 번의 경로로 우열 판단 불가.

## 관찰
- 음수 현금: high에서 3개 조합(16~22일, 최대 −$90, 노출 ≤ 1.004). 비용이 커질수록 체결가 차이에 수수료·스프레드가 더해져 1% 현금 버퍼 경계에서 잠깐 음수가 됨. IB 마진 계좌라 거부 없음, 크기 작음 → 기록만. 현금 계좌 실거래라면 버퍼 조정 검토(Stage 0).
- ADV 1% 초과 조합당 10~19건으로 base·low와 같음(비용 배수와 무관, 주문 크기 기준).
