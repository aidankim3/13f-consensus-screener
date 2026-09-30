"""results/stepN/*/result.json에서 월말 자산으로 월 수익률을 뽑아 CSV로 저장하고 요약을 출력한다.

사용법: python tools/monthly_returns.py results/step4 [--start 2003-01] [--end 2015-12]
- 월말 자산 = 그 달 마지막 Equity 값(종가). 첫 달 말 값을 기준으로 다음 달부터 수익률 계산.
- 출력: <폴더>/monthly_returns.csv (행=월, 열=cost/n/weighting/score, 마지막 열 SPY)
"""
import argparse
import csv
import datetime as dt
import json
import math
from pathlib import Path


def month_end_values(values, idx):
    out = {}
    for row in values:
        t = dt.datetime.fromtimestamp(row[0], dt.timezone.utc) - dt.timedelta(hours=5)  # 미국 동부 기준
        out[t.strftime("%Y-%m")] = row[idx]
    return out


def returns(me, start, end):
    months = sorted(m for m in me if start <= m <= end)
    return {b: me[b] / me[a] - 1 for a, b in zip(months, months[1:])}


def stats(r):
    x = list(r.values())
    n = len(x)
    mu = sum(x) / n
    sd = math.sqrt(sum((v - mu) ** 2 for v in x) / (n - 1))
    growth = math.prod(1 + v for v in x)
    return dict(months=n, ann_mean=12 * mu, ann_vol=math.sqrt(12) * sd, sharpe0=math.sqrt(12) * mu / sd,
                cagr=growth ** (12 / n) - 1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("folder")
    p.add_argument("--start", default="2003-01")
    p.add_argument("--end", default="2015-12")
    a = p.parse_args()
    cols, spy = {}, None
    for f in sorted(Path(a.folder).glob("*/result.json")):
        js = json.load(open(f))
        par = js.get("algorithmConfiguration", {}).get("parameters") or {}
        if not par.get("cost"):
            continue
        key = f"{par['cost']}/{par['n_holdings']}/{par['weighting']}/{par['score']}"
        eq = js["charts"]["Strategy Equity"]["series"]["Equity"]["values"]
        cols[key] = returns(month_end_values(eq, 4), a.start, a.end)
        if spy is None:
            bm = month_end_values(js["charts"]["Benchmark"]["series"]["Benchmark"]["values"], 1)
            spy = returns(bm, a.start, a.end)  # Benchmark 차트 값은 SPY 가격 수준
    order = sorted(cols, key=lambda k: ({"low": 0, "base": 1, "high": 2}[k.split("/")[0]], k))
    months = sorted(spy)
    with open(Path(a.folder) / "monthly_returns.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["month"] + order + ["SPY"])
        for m in months:
            w.writerow([m] + [f"{cols[k].get(m, float('nan')):.6f}" for k in order] + [f"{spy[m]:.6f}"])
    print(f"{'setting':32} months ann_mean ann_vol sharpe0  cagr")
    for k in order + ["SPY"]:
        s = stats(spy if k == "SPY" else cols[k])
        print(f"{k:32} {s['months']:6} {s['ann_mean']:+8.2%} {s['ann_vol']:7.2%} {s['sharpe0']:7.2f} {s['cagr']:+6.2%}")


if __name__ == "__main__":
    main()
