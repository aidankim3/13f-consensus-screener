# ChatGPT(크롬 익스텐션 에이전트)용 프롬프트 — 4단계 12개 조합 실행

실행할 비용 시나리오: base 완료(2026-09-28) → 다음은 **low**, 그다음 **high**. 아래 프롬프트의 `<COST>`를 low 또는 high로 바꿔 붙여 넣는다.
이미 코드가 붙어 있는 프로젝트면 0단계는 건너뛰라고 덧붙여도 된다(첫 줄 확인만).

코드는 GitHub Raw 페이지에서 복사/붙여넣기만 한다(타이핑 금지). ``` 안 전체를 붙여 넣는다.

```
지금 열려 있는 크롬에서 내 QuantConnect 프로젝트의 백테스트를 대신 돌려 줘.
원칙: 코드는 절대 직접 타이핑하거나 고치지 않는다. 복사(Ctrl+C)·붙여넣기(Ctrl+V)만 한다. 유일한 예외는 0-3의 config.py 한 줄.

## 0. 코드 붙여 넣기 (처음 한 번)
0-1. QuantConnect에서 내가 쓰던 프로젝트를 연다(파일: main.py, config.py, universe.py, factors.py, portfolio.py, diagnostics.py, report.py, coverage.py).

0-2. 아래 6개 파일마다:
  a. 새 탭에서 해당 Raw 주소를 연다.
  b. Ctrl+A → Ctrl+C로 전체 복사한다.
  c. QuantConnect 프로젝트의 같은 이름 탭을 열고 Ctrl+A → Ctrl+V로 전체 교체한 뒤 Ctrl+S로 저장한다.
     - costs.py는 프로젝트에 없으니 새 파일 "costs.py"를 만든 뒤 붙여 넣는다.
     - "import 문 추가" 같은 제안 창이 뜨면 Cancel.
  d. 붙여 넣은 탭의 첫 줄이 "# region imports"이고, 마지막 줄이 Raw 페이지의 마지막 줄과 같은지 확인한다.

  https://raw.githubusercontent.com/aidankim3/13f-consensus-screener/claude/clever-knuth-9u1vg1/qc_step4/costs.py
  https://raw.githubusercontent.com/aidankim3/13f-consensus-screener/claude/clever-knuth-9u1vg1/qc_step4/main.py
  https://raw.githubusercontent.com/aidankim3/13f-consensus-screener/claude/clever-knuth-9u1vg1/qc_step4/config.py
  https://raw.githubusercontent.com/aidankim3/13f-consensus-screener/claude/clever-knuth-9u1vg1/qc_step4/factors.py
  https://raw.githubusercontent.com/aidankim3/13f-consensus-screener/claude/clever-knuth-9u1vg1/qc_step4/portfolio.py
  https://raw.githubusercontent.com/aidankim3/13f-consensus-screener/claude/clever-knuth-9u1vg1/qc_step4/report.py

  Raw 주소가 404이면: 같은 파일의 일반 GitHub 페이지
  (https://github.com/aidankim3/13f-consensus-screener/blob/claude/clever-knuth-9u1vg1/qc_step4/<파일명>)를 열고
  코드 영역 오른쪽 위 "Copy raw file" 버튼으로 복사한다.
  universe.py, diagnostics.py, coverage.py는 건드리지 않는다.

0-3. config.py에서 딱 한 줄만 바꾼다: "QUICK_TEST = True" → "QUICK_TEST = False", Ctrl+S.
     "COVERAGE_CHECK = False"인지 확인만 한다(바꾸지 않음).

0-4. 프로젝트를 한 번 빌드(Build/Compile)해서 오류가 없는지 확인한다. 오류가 있으면 멈추고 오류 전문을 알려 준다.

## 1. 조합마다 반복 (아래 표 순서대로, 한 번에 하나씩)
1-1. Project → Parameters에서 n_holdings, weighting, score, cost 네 개를 표의 값으로 맞추고 저장한다.
     파라미터가 없으면 새로 추가한다. cost는 항상 <COST>.
1-2. Backtest를 실행한다.
1-3. 시작 직후 터미널에 아래 두 줄이 맞게 나오는지 확인한다. 하나라도 다르면 즉시 Stop하고 알린다.
     - "[CONFIG] step=4-costs cost=<COST> x0.5(low) 또는 x2.0(high) ... score=<표의 score>"
     - "[CONFIG] step=3-portfolio n=<표의 n_holdings> weighting=<표의 weighting> quick_test=False period=1998-01-01~2015-12-31"
1-4. 약 1시간 걸린다. 10분마다 진행 상황을 확인한다. 아래 중 하나가 보이면 끝난 것이다.
     - 터미널 마지막 부분에 "Algorithm Id:(...) completed in ... seconds" 줄
     - 결과 화면 또는 Backtest Results 목록의 상태가 "Completed"(진행률 100%)
     끝나기 전에는 다음 조합으로 넘어가거나 다른 백테스트를 돌리지 않는다.
     2시간이 지나도 끝나지 않으면 멈추고 알린다.
1-5. 끝나면 결과 화면에서 Logs와 Orders를 다운로드한다(가능하면 Trades와 결과 JSON도).
     파일 이름을 구분할 수 있으면 앞에 "<COST>_#번호_n_weighting_score_"를 붙인다(예: low_01_60_equal_sector_logs.txt).
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
- 빌드·런타임 오류(Traceback, "QCAlgorithm 상속 클래스 없음", circular import 등): 오류 전문을 기록하고 멈춘 뒤 알린다. 코드를 고치지 않는다.
- "Stale file handle" 같은 서버 일시 오류: 한 번만 다시 실행한다. 또 나면 멈추고 알린다.
- 로그인 만료·결제·요금·플랜 업그레이드 화면: 멈추고 알린다. 결제나 계정 설정 변경은 절대 하지 않는다.

## 3. 보고
조합마다 한 줄:
"#번호 n/weighting/score | 완료 여부 | 실행 시간 | [PERF] 줄 | [SUMMARY]의 portfolio 부분 | 다운로드한 파일 이름"
12개가 끝나면 전체 목록을 다시 한 번 정리해 준다.
```
