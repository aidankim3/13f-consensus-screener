"""QuantConnect API로 qc_step4 조합을 차례로 백테스트하고 결과를 results/step4/에 저장한다.

사용법: python tools/qc_batch.py --cost base [--only 60-equal-sector] [--project-id 123]
필요 환경 변수: QC_USER_ID, QC_API_TOKEN (QuantConnect 계정 → API Access). 선택: QC_PROJECT_ID
네트워크: www.quantconnect.com 접속 허용 필요.

- 조합마다 config.py 기본값(DEFAULT_N_HOLDINGS·DEFAULT_WEIGHTING·DEFAULT_SCORE_MODE·DEFAULT_COST_SCENARIO)과
  QUICK_TEST=False, COVERAGE_CHECK=False를 메모리에서 바꿔 올린다(저장소 파일은 바꾸지 않음).
  프로젝트 파라미터를 쓰지 않으므로 QC 프로젝트에 파라미터가 있으면 지우거나 새 프로젝트를 쓴다.
- 결과: results/step4/<cost>-<n>-<weighting>-<score>/ 에 backtest.json(통계 포함), logs.txt, orders.json.
  이미 logs.txt가 있는 조합은 건너뛴다(다시 실행해도 이어서 진행).
"""
import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

API = "https://www.quantconnect.com/api/v2/"
ROOT = Path(__file__).resolve().parent.parent
CODE = ROOT / "qc_step4"
OUT = ROOT / "results" / "step4"
COMBOS = [(n, w, s) for s in ("sector", "global") for n in (60, 40, 80) for w in ("equal", "invvol")]
POLL_SECONDS = 60
BACKTEST_TIMEOUT = 3 * 3600


def call(endpoint, payload):
    user, token = os.environ["QC_USER_ID"], os.environ["QC_API_TOKEN"]
    stamp = str(int(time.time()))
    hashed = hashlib.sha256(f"{token}:{stamp}".encode()).hexdigest()
    auth = base64.b64encode(f"{user}:{hashed}".encode()).decode()
    req = urllib.request.Request(API + endpoint, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": f"Basic {auth}", "Timestamp": stamp,
                                          "Content-Type": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode())
            break
        except Exception as err:  # 네트워크 일시 오류 재시도
            if attempt == 4:
                raise
            print(f"  retry {endpoint}: {err}", flush=True)
            time.sleep(2 ** attempt * 5)
    if not data.get("success", False):
        raise RuntimeError(f"{endpoint} failed: {data.get('errors') or data}")
    return data


def patched_config(n, weighting, score, cost):
    text = (CODE / "config.py").read_text(encoding="utf-8")
    subs = {r"^QUICK_TEST = \w+": "QUICK_TEST = False",
            r"^COVERAGE_CHECK = \w+": "COVERAGE_CHECK = False",
            r"^DEFAULT_N_HOLDINGS = \d+": f"DEFAULT_N_HOLDINGS = {n}",
            r'^DEFAULT_WEIGHTING = "\w+"': f'DEFAULT_WEIGHTING = "{weighting}"',
            r'^DEFAULT_SCORE_MODE = "\w+"': f'DEFAULT_SCORE_MODE = "{score}"',
            r'^DEFAULT_COST_SCENARIO = "\w+"': f'DEFAULT_COST_SCENARIO = "{cost}"'}
    for pattern, repl in subs.items():
        text, count = re.subn(pattern, repl, text, count=1, flags=re.M)
        if count != 1:
            raise RuntimeError(f"config.py에서 찾지 못함: {pattern}")
    return text


def upload(project_id, name, content):
    try:
        call("files/update", {"projectId": project_id, "name": name, "content": content})
    except RuntimeError:
        call("files/create", {"projectId": project_id, "name": name, "content": content})


def compile_project(project_id):
    compile_id = call("compile/create", {"projectId": project_id})["compileId"]
    for _ in range(60):
        state = call("compile/read", {"projectId": project_id, "compileId": compile_id})
        if state.get("state") == "BuildSuccess":
            return compile_id
        if state.get("state") == "BuildError":
            raise RuntimeError(f"compile error: {state.get('logs')}")
        time.sleep(5)
    raise RuntimeError("compile timeout")


def run_combo(project_id, n, weighting, score, cost):
    tag = f"{cost}-{n}-{weighting}-{score}"
    folder = OUT / tag
    if (folder / "logs.txt").exists():
        print(f"[skip] {tag} (이미 있음)", flush=True)
        return
    print(f"[run] {tag}", flush=True)
    for path in sorted(CODE.glob("*.py")):
        content = patched_config(n, weighting, score, cost) if path.name == "config.py" else path.read_text("utf-8")
        upload(project_id, path.name, content)
    compile_id = compile_project(project_id)
    backtest = call("backtests/create", {"projectId": project_id, "compileId": compile_id,
                                         "backtestName": f"s4-{tag}"})["backtest"]
    backtest_id = backtest["backtestId"]
    started = time.time()
    while True:
        time.sleep(POLL_SECONDS)
        result = call("backtests/read", {"projectId": project_id, "backtestId": backtest_id})["backtest"]
        if result.get("error") or result.get("stacktrace"):
            raise RuntimeError(f"{tag} runtime error: {result.get('error')} {result.get('stacktrace')}")
        if result.get("completed"):
            break
        if time.time() - started > BACKTEST_TIMEOUT:
            raise RuntimeError(f"{tag} timeout (progress {result.get('progress')})")
        print(f"  {tag} progress {float(result.get('progress') or 0) * 100:.0f}%", flush=True)
    logs = call("backtests/read/log", {"projectId": project_id, "backtestId": backtest_id, "format": "json",
                                       "start": 0, "end": 1000, "query": " "})
    orders, start = [], 0
    while True:
        page = call("backtests/orders/read", {"projectId": project_id, "backtestId": backtest_id,
                                              "start": start, "end": start + 100}).get("orders", [])
        orders += page
        if len(page) < 100:
            break
        start += 100
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "backtest.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    (folder / "orders.json").write_text(json.dumps(orders, ensure_ascii=False), encoding="utf-8")
    lines = logs.get("logs") or logs.get("BacktestLogs") or []
    (folder / "logs.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[done] {tag} backtest={backtest_id} orders={len(orders)} log_lines={len(lines)} "
          f"minutes={(time.time() - started) / 60:.0f}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cost", default="base", choices=("low", "base", "high"))
    parser.add_argument("--only", help="예: 60-equal-sector")
    parser.add_argument("--project-id", type=int, default=int(os.environ.get("QC_PROJECT_ID", "0") or 0))
    args = parser.parse_args()
    project_id = args.project_id
    if not project_id:
        project_id = call("projects/create", {"name": "step4-batch", "language": "Py"})["projects"][0]["projectId"]
        print(f"created project {project_id} (다음부터 --project-id {project_id})", flush=True)
    combos = [c for c in COMBOS if not args.only or "-".join(map(str, c)) == args.only]
    for n, weighting, score in combos:
        run_combo(project_id, n, weighting, score, args.cost)
    print("all done", flush=True)


if __name__ == "__main__":
    sys.exit(main())
