# ChatGPT(크롬 익스텐션 에이전트)용 프롬프트 — 4단계 low(×0.5) 12개 조합

GPT는 파라미터 변경과 실행만 한다. 다운로드는 사용자가 직접 한다(보고의 백테스트 이름으로 조합 구분).
코드는 base 실행 때 이미 붙여 넣었으므로 바꾸지 않는다. ``` 안 전체를 붙여 넣는다.
high 실행 때는 `low`를 전부 `high`로, `x0.5`를 전부 `x2.0`으로 바꿔 쓴다(1-3과 1-4 두 군데).

```
지금 열려 있는 크롬에서 내 QuantConnect 프로젝트의 백테스트를 대신 돌려 줘.
네 일은 파라미터를 바꾸고 백테스트를 실행하는 것뿐이다.
- 코드 파일은 절대 수정하지 않는다. 바꾸는 것은 Project Parameters 값뿐이다.
- 결과 다운로드는 하지 않는다(내가 직접 한다).

## 0. 시작 전 확인 (처음 한 번)
0-1. QuantConnect에서 지난번 4단계 백테스트를 돌린 프로젝트를 연다(파일 목록에 costs.py가 있어야 한다. 없으면 멈추고 알린다).
0-2. config.py를 열어 아래 두 줄만 눈으로 확인한다(수정하지 않음).
     - "QUICK_TEST = False"
     - "COVERAGE_CHECK = False"
     다르면 멈추고 알린다. 확인 후 config.py 탭은 닫는다.

## 1. 조합마다 반복 (아래 표 순서대로, 한 번에 하나씩)
1-1. Project → Parameters에서 네 값을 표대로 맞추고 저장한다.
     - n_holdings = 표의 값
     - weighting = 표의 값
     - score = 표의 값
     - cost = low   (12개 모두 low)
1-2. Backtest를 실행하고 시작 시각을 적어 둔다.
     터미널에 "Received backtest '<이름>' request" 줄이 나온다. 이 <이름>(예: 'Pensive Fluorescent Orange Cat')이 백테스트 이름이니 적어 둔다.
1-3. 약 10~40초 뒤 "Launching analysis for ..." 아래에 [CONFIG] 줄 다섯 개가 나온다. 이 중 두 줄을 확인한다.
     터미널은 긴 줄 끝을 "..."로 자르므로 줄 앞부분만 보면 된다. 하나라도 다르면 즉시 Stop하고 알린다.
     - "[CONFIG] step=4-costs cost=low x0.5 spread=... score=<표의 score> impact_check=..."
       (지난 base 실행 때는 "cost=base x1.0"이었다. base가 보이면 파라미터가 안 바뀐 것이니 Stop.)
     - "[CONFIG] step=3-portfolio n=<표의 n_holdings> weighting=<표의 weighting> quick_test=False ..."
     이어서 "[START] sig=1998-01-30 ..." 줄이 나오면 정상 진행이다.
1-4. 약 55~70분 걸린다. 1-3 확인 뒤에는 실행 시작 후 1시간이 될 때까지 확인하지 말고 기다린다.
     1시간이 되면 처음 확인하고, 아직 안 끝났으면 그 후로는 10분마다 확인한다.
     기다리는 동안 코드 파일을 열거나 클릭·저장하지 않는다.
     끝나면 터미널 끝에 아래 순서로 줄이 나온다. "Algorithm Id:(...) completed in ... seconds"가 보이면 끝난 것이다.
       Algorithm '<id>' completed
       ... [PERF] costs=low(x0.5) ...
       ... [SUMMARY] ...
       ... Algorithm Id:(<id>) completed in 3300 seconds ...
     [PERF] 줄에 "costs=low(x0.5)"가 있는지 확인한다(base면 멈추고 알림).
     끝나기 전에는 다음 조합으로 넘어가거나 다른 백테스트를 돌리지 않는다.
     시작 후 2시간이 지나도 끝나지 않으면 멈추고 알린다.
1-5. 끝나면 바로 표의 다음 조합으로 넘어가 1-1부터 반복한다.

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

## 정상 메시지 (멈추지 말 것)
아래 줄은 매번 나오는 정상 메시지다. 이것 때문에 멈추지 않는다.
- "Warning: when performing history requests, the start date will be adjusted ..."(시작 때 2줄)
- "[START] ... eligible<900 (NOTES 기록 참고)"
- "Warning: history() has been called 30+ consecutive times ..."(2000-08 무렵)
- "Built project '...' in Cloud ..."(여러 번 나와도 됨)
- "Due to numerical precision issues in the factor file ... [SPY, 1/1/1998]", "The starting dates ... [SPY, 1998-01-02]"(끝날 때)

## 2. 멈춰야 하는 경우
- 빌드·런타임 오류(Traceback, Runtime Error 등): 오류 전문을 기록하고 멈춘 뒤 알린다. 코드를 고치지 않는다.
- "Stale file handle" 같은 서버 일시 오류: 한 번만 다시 실행한다. 또 나면 멈추고 알린다.
- 로그인 만료, "Verify your account", 카드 등록, 결제·요금·플랜 업그레이드 화면: 창만 닫아 보고, 계속 막히면 멈추고 알린다. 카드·결제 정보 입력이나 계정 설정 변경은 절대 하지 않는다.

## 3. 보고
조합마다 한 줄:
"#번호 n/weighting/score | 백테스트 이름 | 완료 여부 | 시작 시각 | 실행 시간"
12개가 끝나면 전체 목록을 다시 한 번 정리해 준다.
```
