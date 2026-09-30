# 5단계 — 기준선(무작위 대조군·단일 팩터·유니버스·RSP·SPY), 개발 구간만
QC에 올리는 파일 10개: 4단계 9개(`main.py`, `config.py`, `universe.py`, `factors.py`, `portfolio.py`, `diagnostics.py`, `report.py`, `coverage.py`, `costs.py`) + 새 파일 `baseline.py`.
바뀐 파일: `main.py`, `config.py`, `factors.py`(스타일 점수 저장만), `baseline.py`(새). 그대로: 나머지 6개.

설계·출력·확인 항목은 [`NOTES.md`](NOTES.md)의 "5단계" 절 참고.

## 실행 순서 (파라미터는 항상 n_holdings=60, weighting=equal, score=global, cost=base)
1. `QUICK_TEST = True`(기본), `BASELINE_MODE = "calibrate"`(기본) → 오류 없이 끝나는지 점검(약 10~20분)
2. `QUICK_TEST = False`, `BASELINE_MODE = "calibrate"` → 완료(2026-09-30, φ = 0.913, `results/step5/swimming-yellow-sheep`)
3. `QUICK_TEST = False`, `BASELINE_MODE = "final"`(현재 기본값) → 무작위 500개 × (base, 비용 2배) 본 실행
