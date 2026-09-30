"""5단계 개발 구간 통계: 기준선 차트(result.json) + 4단계 월수익률(monthly_returns.csv)로
- A0 − 무작위 평균(base·비용 2배) 월 초과수익: 연율 평균·Newey–West 표준오차(계획서 10장 시차 규칙)
- 12개 설정의 같은 가중 유니버스(equal → EW, invvol → IVW) 대비 초과수익, 선택 규칙 재확인
- DSR(시험 수 12, 보수적 50), PBO(CSCV, 블록 16개)

사용법: python tools/baseline_stats.py results/step5/<폴더>/result.json results/step4/monthly_returns.csv
"""
import csv
import datetime as dt
import itertools
import json
import math
import sys

import numpy as np
from scipy.stats import norm, skew, kurtosis


def chart_returns(js, chart, series):
    vals = js["charts"][chart]["series"][series]["values"]
    out, prev = {}, 1000.0
    for t, v in vals:
        month = (dt.datetime.utcfromtimestamp(t) - dt.timedelta(days=1)).strftime("%Y-%m")
        out[month] = v / prev - 1
        prev = v
    return out


def newey_west_se(x):
    """월 평균의 Newey–West 표준오차(연율 = ×12). 시차 = floor(4·(T/100)^(2/9))."""
    x = np.asarray(x) - np.mean(x)
    t = len(x)
    lag = int(4 * (t / 100) ** (2 / 9))
    s = np.dot(x, x) / t
    for k in range(1, lag + 1):
        s += 2 * (1 - k / (lag + 1)) * np.dot(x[k:], x[:-k]) / t
    return 12 * math.sqrt(s / t), lag


def dsr(returns, sr_trials, n_trials):
    """Bailey–López de Prado Deflated Sharpe(월 단위 SR). sr_trials: 시험 집합의 월 SR 목록(분산 추정)."""
    r = np.asarray(returns)
    sr = r.mean() / r.std(ddof=1)
    var = np.var(sr_trials, ddof=1)
    g = 0.5772156649
    sr0 = math.sqrt(var) * ((1 - g) * norm.ppf(1 - 1 / n_trials) + g * norm.ppf(1 - 1 / (n_trials * math.e)))
    sk, ku = skew(r), kurtosis(r, fisher=False)
    z = (sr - sr0) * math.sqrt(len(r) - 1) / math.sqrt(1 - sk * sr + (ku - 1) / 4 * sr ** 2)
    return norm.cdf(z), sr, sr0


def pbo(matrix, blocks=16):
    """CSCV: 행 = 월, 열 = 설정. 성과 지표 = 평균 초과수익(선택 규칙과 같음). 반환: PBO, λ 중앙값, 조합 수."""
    parts = np.array_split(np.arange(matrix.shape[0]), blocks)
    n = matrix.shape[1]
    lambdas = []
    for combo in itertools.combinations(range(blocks), blocks // 2):
        is_idx = np.concatenate([parts[i] for i in combo])
        oos_idx = np.concatenate([parts[i] for i in range(blocks) if i not in combo])
        best = int(np.argmax(matrix[is_idx].mean(axis=0)))
        oos = matrix[oos_idx].mean(axis=0)
        rank = (oos < oos[best]).sum() + 1                     # 1 = 가장 나쁨
        w = rank / (n + 1)
        lambdas.append(math.log(w / (1 - w)))
    lambdas = np.array(lambdas)
    return float((lambdas <= 0).mean()), float(np.median(lambdas)), len(lambdas)


def main():
    js = json.load(open(sys.argv[1]))
    with open(sys.argv[2]) as fh:
        rows = list(csv.DictReader(fh))
    months = [r["month"] for r in rows]
    base = {k: np.array([float(r[k]) for r in rows]) for k in rows[0] if k.startswith("base/")}
    series = {name: chart_returns(js, chart, name) for chart, names in
              (("Baseline", ("rep_base", "rep_high", "rand_base", "rand_high", "EW", "IVW")),
               ("Bench", ("RSP", "sf_mom", "sf_qual", "sf_value"))) for name in names}
    get = lambda name: np.array([series[name].get(m, np.nan) for m in months])
    a0 = base["base/60/equal/global"]
    print(f"months={len(months)} {months[0]}~{months[-1]}")
    print(f"A0 real vs rep_base: corr={np.corrcoef(a0, get('rep_base'))[0, 1]:.4f} "
          f"mean diff={12 * np.mean(a0 - get('rep_base')):+.2%}/yr")

    print("\n[A0 − 무작위 평균] (개발 구간, 연율, Newey–West)")
    a0_high = get("rep_high")                                   # 비용 2배 A0는 복제 장부(실제 백테스트는 base만)
    for label, a, rand in (("base", a0, get("rand_base")), ("high(x2, A0=replica)", a0_high, get("rand_high"))):
        ex = a - rand
        se, lag = newey_west_se(ex)
        print(f"  {label:22} mean={12 * ex.mean():+.2%} NW_se={se:.2%} t={12 * ex.mean() / se:.2f} lag={lag}")

    print("\n[같은 가중 유니버스 대비 초과수익] (equal → EW, invvol → IVW)")
    ew, ivw = get("EW"), get("IVW")
    excess = {}
    for k, r in base.items():
        bench = ew if "/equal/" in k else ivw
        excess[k] = r - bench
    for k in sorted(excess, key=lambda k: -excess[k].mean()):
        se, _ = newey_west_se(excess[k])
        print(f"  {k:26} excess={12 * excess[k].mean():+.2%} NW_se={se:.2%} raw={12 * base[k].mean():+.2%}")

    keys = sorted(excess)
    matrix = np.column_stack([excess[k] for k in keys])
    srs = [excess[k].mean() / excess[k].std(ddof=1) for k in keys]
    sel = excess["base/60/equal/global"]
    for n_trials in (12, 50):
        p, sr, sr0 = dsr(sel, srs, n_trials)
        print(f"\nDSR(A0, trials={n_trials}) = {p:.3f}  (monthly SR {sr:+.3f}, annual {sr * math.sqrt(12):+.2f}; "
              f"SR0 {sr0:.3f})")
    p, med, count = pbo(matrix)
    print(f"PBO(CSCV, 16 blocks, {count} splits) = {p:.3f}  median logit {med:+.2f}")

    print("\n[기타 기준선] 연율 평균 월수익률")
    for name in ("rand_base", "rand_high", "EW", "IVW", "RSP", "sf_mom", "sf_qual", "sf_value"):
        x = get(name)
        x = x[~np.isnan(x)]
        print(f"  {name:10} n={len(x)} mean={12 * x.mean():+.2%}")
    rsp = get("RSP")
    ok = ~np.isnan(rsp)
    ex = a0[ok] - rsp[ok]
    se, _ = newey_west_se(ex)
    print(f"  A0 − RSP (n={ok.sum()}): mean={12 * ex.mean():+.2%} NW_se={se:.2%}")


if __name__ == "__main__":
    main()
