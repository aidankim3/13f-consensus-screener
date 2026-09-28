# ChatGPT(크롬 익스텐션 에이전트)용 프롬프트 — 4단계 low(×0.5) 12개 조합

코드는 base 실행 때 이미 붙여 넣었으므로 바꾸지 않는다. ``` 안 전체를 붙여 넣는다.
high 실행 때는 이 파일의 `low`를 `high`로, `x0.5`를 `x2.0`으로 바꿔 쓴다.

```
지금 열려 있는 크롬에서 내 QuantConnect 프로젝트의 백테스트를 대신 돌려 줘.
원칙: 코드 파일은 절대 수정하지 않는다. 바꾸는 것은 Project Parameters 값뿐이다.

## 0. 시작 전 확인 (처음 한 번)
0-1. QuantConnect에서 지난번 4단계 백테스트를 돌린 프로젝트를 연다(파일 목록에 costs.py가 있어야 한다. 없으면 멈추고 알린다).
0-2. config.py를 열어 아래 두 줄만 눈으로 확인한다(수정하지 않음).
     - "QUICK_TEST = False"
     - "COVERAGE_CHECK = False"
     다르면 멈추고 알린다.

## 1. 조합마다 반복 (아래 표 순서대로, 한 번에 하나씩)
1-1. Project → Parameters에서 네 값을 표대로 맞추고 저장한다.
     - n_holdings = 표의 값
     - weighting = 표의 값
     - score = 표의 값
     - cost = low   (12개 모두 low)
1-2. Backtest를 실행한다.
1-3. 시작 직후 터미널(Console)에 아래 두 줄이 맞게 나오는지 확인한다. 하나라도 다르면 즉시 Stop하고 알린다.
     - "[CONFIG] step=4-costs cost=low x0.5 ... score=<표의 score> ..."
     - "[CONFIG] step=3-portfolio n=<표의 n_holdings> weighting=<표의 weighting> quick_test=False ..."
1-4. 약 1시간 걸린다. 10분마다 확인한다. 아래 중 하나가 보이면 끝난 것이다.
     - 터미널 끝부분에 "Algorithm Id:(...) completed in ... seconds" 줄
     - 결과 화면 또는 Backtest 목록의 상태가 "Completed"(진행률 100%)
     끝나기 전에는 다음 조합으로 넘어가거나 다른 백테스트를 돌리지 않는다.
     2시간이 지나도 끝나지 않으면 멈추고 알린다.
1-5. 끝나면 결과 화면에서 네 가지를 다운로드한다: Logs, Orders, Trades, 결과 JSON(Overview/Report의 다운로드).
     가능하면 파일 이름 앞에 "low_번호_n_weighting_score_"를 붙인다. 예: low_01_60_equal_sector_logs.txt
     이름을 바꿀 수 없으면 그대로 두고, 백테스트 이름(예: "Calm Green Hamster")을 보고에 적는다.
1-6. 로그 끝의 "[PERF]" 줄과 "[SUMMARY]" 줄을 그대로 복사해 둔다.

| # | n_holdings | weighting | score |
|---|---|---|---|
| 1 | 60 | equal | sector |
| 2 | 60 | invvol | sector |
| 3 | 40 | equal | sector |
| 4 | 40 | invvol | sector |
| 5 | 80 | equal | sector |
| 6 | 80 | invvol | sector |
| 7 | 60 | equal | global |
| 8 | 60 | invvol | global |
| 9 | 40 | equal | global |
| 10 | 40 | invvol | global |
| 11 | 80 | equal | global |
| 12 | 80 | invvol | global |

## 2. 멈춰야 하는 경우
- 빌드·런타임 오류(Traceback, Runtime Error 등): 오류 전문을 기록하고 멈춘 뒤 알린다. 코드를 고치지 않는다.
- "Stale file handle" 같은 서버 일시 오류: 한 번만 다시 실행한다. 또 나면 멈추고 알린다.
- 로그인 만료, "Verify your account", 카드 등록, 결제·요금·플랜 업그레이드 화면: 창만 닫아 보고, 계속 막히면 멈추고 알린다. 카드·결제 정보 입력이나 계정 설정 변경은 절대 하지 않는다.

## 3. 보고
조합마다 한 줄:
"#번호 n/weighting/score | 백테스트 이름 | 완료 여부 | 실행 시간 | [PERF] 줄 | [SUMMARY]의 portfolio 부분 | 다운로드한 파일 이름"
12개가 끝나면 전체 목록을 다시 한 번 정리해 준다.
```
