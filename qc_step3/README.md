# 3단계 — 포트폴리오 구성·매매 (진행 중)
QC에 올리는 파일 8개: `main.py`, `config.py`, `universe.py`, `factors.py`, `portfolio.py`, `diagnostics.py`, `report.py`, `coverage.py`

8개 모두 이 폴더에 있음 (2026-09-26 버전). 파일별 역할·의존 방향·확인 항목은 [`NOTES.md`](NOTES.md) 참고.

## 주의
- `coverage.py`는 점검 모드를 쓰지 않아도 필요 (main.py가 import)
- 이 저장소의 `config.py`는 항상 `COVERAGE_CHECK = False` (QC에서만 True로 바꿨다가 되돌림)
- `QUICK_TEST = True`면 2001~2004 짧은 실행, 최종 확인 때만 False
- QC 프로젝트 파라미터: `n_holdings`(40·60·80), `weighting`(equal·invvol), 기본 60·equal
