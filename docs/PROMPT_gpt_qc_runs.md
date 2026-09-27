# ChatGPT(브라우저 조작 가능한 에이전트 모드)용 프롬프트 — 4단계 12개 조합 실행

첨부: qc_step4의 costs.py, main.py, config.py, factors.py, portfolio.py, report.py (6개)

```
너는 내 QuantConnect 웹 IDE(브라우저)에서 백테스트를 대신 돌려 주는 역할이야. 코드는 절대 고치지 말고, 아래 순서만 정확히 따라 줘.

## 0. 준비 (처음 한 번)
1. quantconnect.com에 로그인된 브라우저에서 내가 쓰던 프로젝트를 연다(파일: main.py, config.py, universe.py, factors.py, portfolio.py, diagnostics.py, report.py, coverage.py).
2. 첨부한 6개 파일을 같은 이름 탭에 전체 교체로 붙여 넣고 각각 Ctrl+S로 저장한다.
   - costs.py는 프로젝트에 없으니 새 파일(costs.py)을 만들어 붙여 넣는다.
   - universe.py, diagnostics.py, coverage.py는 건드리지 않는다.
   - "import 문 추가" 같은 제안 창이 뜨면 Cancel.
3. config.py에서 딱 한 줄만 바꾼다: `QUICK_TEST = True` → `QUICK_TEST = False`, 저장.
   `COVERAGE_CHECK = False`인지 확인만 한다(바꾸지 않음).
4. 붙여 넣은 뒤 각 파일 맨 위 줄이 `# region imports`로 시작하는지 확인한다.

## 1. 조합마다 반복 (아래 표 순서대로, 한 번에 하나씩)
프로젝트 파라미터(Project → Parameters)를 표의 값으로 맞춘다. 파라미터 이름은 정확히 n_holdings, weighting, score, cost 네 개이고, cost는 항상 base.

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

각 조합에서:
1. 파라미터 저장 → Backtest 실행.
2. 실행 직후 아래 터미널에서 두 줄을 확인한다. 하나라도 다르면 즉시 중단(Stop)하고 파라미터·config를 다시 확인한다.
   - `[CONFIG] step=4-costs cost=base x1.0 ... score=<표의 score>`
   - `[CONFIG] step=3-portfolio n=<표의 n> weighting=<표의 weighting> quick_test=False period=1998-01-01~2015-12-31`
3. 약 1시간 걸린다. 끝날 때까지 기다린다(다른 백테스트를 동시에 돌리지 않는다).
4. 끝나면 결과 화면에서 Logs와 Orders를 다운로드한다(가능하면 Trades, 결과 JSON도). 파일 이름 앞에 `#번호_n_weighting_score_`를 붙여 구분한다. 예: `01_60_equal_sector_logs.txt`.
5. 로그 끝부분의 `[PERF]` 줄과 `[SUMMARY]` 줄을 그대로 복사해 둔다.

## 2. 멈춰야 하는 경우
- 빌드/런타임 오류(빨간 오류, Traceback, "QCAlgorithm 상속 클래스 없음", circular import): 실행을 멈추고 오류 전문을 기록한 뒤 나에게 알린다. 코드를 고치지 않는다.
- "Stale file handle" 같은 서버 일시 오류: 한 번만 다시 실행한다.
- 로그인 만료·결제·요금 관련 화면: 멈추고 알린다. 절대 결제하거나 계정 설정을 바꾸지 않는다.

## 3. 보고 형식 (조합마다 한 줄 + 끝에 전체)
`#번호 n/weighting/score | 완료 여부 | 실행 시간 | [PERF] 줄 | [SUMMARY]의 portfolio 부분 | 다운로드한 파일 이름`
```
