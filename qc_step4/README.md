# 4단계 — 거래비용 반영 (진행 중)
QC에 올리는 파일 9개: 3단계 8개(`main.py`, `config.py`, `universe.py`, `factors.py`, `portfolio.py`, `diagnostics.py`, `report.py`, `coverage.py`) + 새 파일 `costs.py`.
바뀐 파일: `main.py`, `config.py`, `factors.py`, `portfolio.py`, `report.py`, `costs.py`(새). 그대로: `universe.py`, `diagnostics.py`, `coverage.py`.

비용 모형·파라미터·출력은 [`NOTES.md`](NOTES.md)의 "4단계" 절 참고.

## 실행 순서
1. QUICK_TEST(기본 True) + 파라미터 기본값(60·equal·sector·base)으로 한 번 → 비용이 제대로 빠지는지 점검
2. `QUICK_TEST = False`로 12개 조합 × `cost=base`
3. 12개 조합 × `cost=low`, `cost=high`
