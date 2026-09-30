# region imports
from AlgorithmImports import *
# endregion
# 5단계 기준선(계획서 6장 '기준선', 10장 시험 집합·무작위 대조군). 실제 매매(A0)와 같은 백테스트 안에서 가상 장부로 계산한다.
# - 무작위 점수 Top-N: A0와 같은 N·가중·밴드·정수 주·최소 주문액·현금 버퍼·비용 모형, 점수만 AR(1) 난수(전역 순위)
# - A0 복제 장부: 실제 A0 점수로 같은 가상 장부를 돌려 실제 LEAN 결과를 재현하는지 확인(가상 장부 검증)
# - 단일 팩터 Top-N(모멘텀·퀄리티·가치), 적격 유니버스 동일가중·역변동성(비례 비용만, 이론 진단), RSP·SPY
# 가상 장부는 월말 신호일 T에 한 번씩: 직전 계획을 체결일 E 종가로 체결 → T 종가로 평가 → 새 계획(신호일 원주가·가치).
# 보유 가치는 같은 요청 안의 조정 종가 비율로 굴린다(분할·배당 반영, 요청마다 조정 기준이 달라도 비율은 같음).
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import numpy as np

from config import *
from costs import abdi_ranaldo
from portfolio import cap_weights, sigma_hat


def ib_fee(shares, value):
    """LEAN IB 주식 수수료(주당·최소·최대 비율). 최소보다 작으면 최소, 아니면 최대 비율로 자른다."""
    fee = IB_FEE_PER_SHARE * shares
    if fee < IB_MIN_FEE:
        return IB_MIN_FEE
    return min(fee, IB_MAX_FEE_RATE * value)


def window_bars(algo, symbols, start, end, warn):
    """원주가 일봉 {Symbol: {거래일: (고가, 저가, 종가)}}과 조정 종가 {Symbol: {거래일: 종가}}. 신호일 이후 봉은 없다."""
    raw, adj = defaultdict(dict), defaultdict(dict)
    if not symbols:
        return raw, adj
    by_name = {}
    for s in symbols:
        for name in (str(s), s.value, str(s.id)):
            by_name.setdefault(name, s)
    for mode, out in ((DataNormalizationMode.RAW, raw), (DataNormalizationMode.ADJUSTED, adj)):
        try:
            df = algo.history(list(symbols), start, end, Resolution.DAILY, data_normalization_mode=mode)
        except Exception as err:
            warn(f"base_hist_{mode}", f"baseline history failed: {err}")
            continue
        if df is None or df.empty or any(k not in df.columns for k in ("high", "low", "close")):
            continue
        if out is raw:
            for index, h, l, c in zip(df.index, df["high"], df["low"], df["close"]):
                s = by_name.get(str(index[0]))
                if s is not None:
                    out[s][(index[-1] - BAR_END_OFFSET).date()] = (float(h), float(l), float(c))
        else:
            for index, c in zip(df.index, df["close"]):
                s = by_name.get(str(index[0]))
                if s is not None:
                    out[s][(index[-1] - BAR_END_OFFSET).date()] = float(c)
    return raw, adj


def last_on_or_before(days, day):
    best = None
    for d in days:
        if d <= day and (best is None or d > best):
            best = d
    return best


class Ledger:
    """가상 계좌 하나. pos: {종목 번호: 달러 가치(마지막 평가일 기준)}, pending: 직전 신호일에 정한 주문."""
    __slots__ = ("name", "mult", "group", "row", "pos", "cash", "pending", "first", "values", "turn", "sector")

    def __init__(self, name, cost, group=None, row=0, sector=False):
        self.name, self.mult, self.group, self.row = name, COST_SCENARIOS[cost], group, row
        self.pos, self.cash, self.pending, self.first = {}, float(INITIAL_CASH), [], True
        self.values = [float(INITIAL_CASH)]
        self.turn = Counter()                     # 연도별 Σ체결 금액 / 계획 시점 가치
        self.sector = Counter() if sector else None

    def settle(self, m, year):
        """직전 계획을 체결일 E 종가로 체결하고 신호일 T 종가로 평가한다. 반환: T의 계좌 가치."""
        pos, mult = self.pos, self.mult
        for i in pos:
            pos[i] *= m.g_e.get(i, 1.0)
        plan_pv = self.values[-1]
        traded = 0.0
        for i, qty, full, half in self.pending:                  # 매도 먼저, 그다음 매수(계획 순서)
            if qty < 0:
                value = pos.get(i)
                if value is None:
                    continue
                price = m.raw_e_last.get(i)
                if full or not price:
                    shares = value / price if price else 0.0
                    del pos[i]
                else:
                    shares = -qty
                    value = min(shares * price, value)
                    pos[i] -= value
                    if pos[i] <= 1e-9:
                        del pos[i]
                self.cash += value - mult * (ib_fee(shares, value) + half * value)
            else:
                price = m.raw_e.get(i)
                if not price:                                    # 체결일에 거래가 없으면(정지·상장폐지) 미체결
                    continue
                value = qty * price
                pos[i] = pos.get(i, 0.0) + value
                self.cash -= value + mult * (ib_fee(qty, value) + half * value)
            traded += value
        self.pending = []
        if traded and plan_pv > 0:
            self.turn[year] += traded / plan_pv
        for i in pos:
            pos[i] *= m.g_t.get(i, 1.0)
        pv = sum(pos.values()) + self.cash
        if self.sector is not None and pv > 0:
            for i, v in pos.items():
                self.sector[m.sector.get(i)] += v / pv
            self.sector["_months"] += 1
        return pv

    def plan(self, final, m, pv, n_holdings):
        """portfolio.build_orders와 같은 규칙(동일가중, 정수 주 내림, $200 미만 생략, 매수 총액 > 가용 자금이면 비례 축소)."""
        self.first = False
        investable = pv * (1 - CASH_BUFFER)
        final_set = set(final)
        current = {}
        for i, v in self.pos.items():
            price = m.raw_t.get(i)
            current[i] = int(round(v / price)) if price else 0
        sells, buys = [], []
        for i, v in self.pos.items():
            if i not in final_set:
                sells.append((i, -current[i], True, m.half.get(i, DEFAULT_HALF_SPREAD)))
        target_value = investable / n_holdings
        for i in final:
            price = m.raw_t.get(i)
            if not price:
                continue
            cur = current.get(i, 0)
            target = math.floor(target_value / price)
            delta = target - cur
            if cur == 0 and target * price < MIN_TRADE_VALUE:
                continue
            if delta and abs(delta) * price < MIN_TRADE_VALUE:
                continue
            half = m.half.get(i, DEFAULT_HALF_SPREAD)
            if delta < 0:
                sells.append((i, delta, False, half))
            elif delta > 0:
                buys.append((i, delta, False, half))
        proceeds = sum(-q * (m.raw_t.get(i) or 0.0) for i, q, _, _ in sells)
        spend = sum(q * m.raw_t[i] for i, q, _, _ in buys)
        if spend > self.cash + proceeds and spend > 0:
            scale = max(0.0, (self.cash + proceeds) / spend)
            buys = [(i, math.floor(q * scale), f, h) for i, q, f, h in buys if math.floor(q * scale) > 0]
        self.pending = sells + buys


class RandomGroup:
    """AR(1) 무작위 점수: 지난달에도 점수 대상이던 종목은 φ·이전 + √(1−φ²)·ε, 새로 들어온 종목은 새로 뽑는다(계획서 10장)."""

    def __init__(self, phi, seeds, seed):
        self.phi, self.seeds = phi, seeds
        self.rng = np.random.default_rng(seed)
        self.scores = np.full((seeds, 0), np.nan)
        self.order = self.rank = None

    def step(self, scored_idx, capacity):
        if self.scores.shape[1] < capacity:
            self.scores = np.pad(self.scores, ((0, 0), (0, capacity - self.scores.shape[1])), constant_values=np.nan)
        prev = self.scores[:, scored_idx]
        eps = self.rng.standard_normal(prev.shape)
        new = np.where(np.isnan(prev), eps, self.phi * prev + math.sqrt(1 - self.phi ** 2) * eps)
        self.scores[:] = np.nan
        self.scores[:, scored_idx] = new
        self.order = np.argsort(-new, axis=1, kind="stable")
        self.rank = np.empty_like(self.order)
        np.put_along_axis(self.rank, self.order, np.arange(new.shape[1])[None, :].repeat(new.shape[0], 0), axis=1)


class Month:
    """한 신호일의 가격·비율·반스프레드(종목 번호 기준)."""
    __slots__ = ("g_e", "g_t", "raw_e", "raw_e_last", "raw_t", "half", "sector", "ret")


class Baselines:
    def __init__(self, algo, recorder, n_holdings, mode):
        self.algo, self.rec, self.n, self.mode = algo, recorder, n_holdings, mode
        self.ids, self.symbols, self.sector = {}, [], {}
        self.prev_signal = self.prev_exec = None
        self.prev_members = []
        self.groups, self.ledgers = [], []
        if mode == "calibrate":
            for k, phi in enumerate(CALIBRATE_PHIS):
                group = RandomGroup(phi, CALIBRATE_SEEDS, RANDOM_SEED_BASE + k)
                self.groups.append(group)
                self.ledgers += [Ledger(f"cal{phi}", "base", group, r) for r in range(CALIBRATE_SEEDS)]
        else:
            group = RandomGroup(RANDOM_PHI, RANDOM_SEEDS, RANDOM_SEED_BASE)
            self.groups.append(group)
            for cost in SHADOW_COSTS:
                self.ledgers += [Ledger(f"rand_{cost}", cost, group, r, sector=cost == "base")
                                 for r in range(RANDOM_SEEDS)]
            self.ledgers += [Ledger(f"sf_{k}", "base") for k in ("mom", "qual", "value")]
        self.ledgers += [Ledger(f"rep_{c}", c, sector=c == "base") for c in SHADOW_COSTS]
        self.real = [float(INITIAL_CASH)]
        self.bench = {k: [] for k in ("EW", "IVW", "RSP", "SPY")}
        self.univ_w = {"EW": {}, "IVW": {}}
        self.bench_symbols = {t: algo.add_equity(t, Resolution.DAILY).symbol for t in BENCH_TICKERS}
        self.index = defaultdict(lambda: 1000.0)
        algo.debug(f"[CONFIG] step=5-baseline mode={mode} phi={RANDOM_PHI if mode == 'final' else CALIBRATE_PHIS} "
                   f"seeds={RANDOM_SEEDS if mode == 'final' else CALIBRATE_SEEDS} costs={','.join(SHADOW_COSTS)} "
                   f"a0={A0_SETTING} ledgers={len(self.ledgers)} bench={','.join(BENCH_TICKERS)}")

    def _id(self, s):
        i = self.ids.get(s)
        if i is None:
            i = self.ids[s] = len(self.symbols)
            self.symbols.append(s)
        return i

    def on_signal(self, signal_date, members, eligible, month, closes, real_pv, z_ranked):
        """월말 신호일마다(첫 매매 달부터) 호출. month: FactorMonth(z·style·records), z_ranked: A0 z 순위 목록."""
        exec_date = self.algo._calendar.next_day(signal_date)
        member_ids = {self._id(s) for s in members}
        for s in members:
            self.sector[self.ids[s]] = month.records.get(s, {}).get("sector")
        first = self.prev_signal is None
        m, adj = self._advance(signal_date, members, eligible, real_pv)

        # 점수 대상(종목 번호, SID 순으로 고정)과 순위
        scored = sorted(month.z, key=lambda s: str(s.id))
        scored_idx = np.array([self._id(s) for s in scored], dtype=int)
        pos_in = {int(i): j for j, i in enumerate(scored_idx)}
        n_scored = len(scored)
        keep_cut, fill_cut = KEEP_TOP_FRACTION * n_scored, FILL_TOP_FRACTION * n_scored
        for group in self.groups:
            group.step(scored_idx, len(self.symbols))
        fixed = {"rep": [pos_in[self.ids[s]] for s in z_ranked if self.ids.get(s) in pos_in]}
        style = getattr(month, "style", {})
        for k, key in (("mom", 0), ("qual", 1), ("value", 2)):
            ranked = sorted(scored, key=lambda s: (-style[s][key], str(s.id))) if style else []
            fixed[k] = [pos_in[self.ids[s]] for s in ranked]
        fixed_rank = {k: {j: r for r, j in enumerate(v)} for k, v in fixed.items()}

        for ledger in self.ledgers:
            if ledger.group is not None:
                order = ledger.group.order[ledger.row]
                rank_of = ledger.group.rank[ledger.row]
            else:
                key = ledger.name.split("_")[1] if ledger.name.startswith("sf_") else "rep"
                order, rank_of = fixed[key], fixed_rank[key]
            final = self._select(ledger, order, rank_of, pos_in, scored_idx, member_ids, keep_cut, fill_cut)
            ledger.plan(final, m, ledger.values[-1], self.n)
        self._set_universe_weights(members, closes, m)
        self.prev_signal, self.prev_exec = signal_date, exec_date
        self.prev_members = sorted(member_ids)
        if not first:
            self._plot()

    def _advance(self, day, members, eligible, real_pv):
        """직전 신호일 이후 가격을 받아 직전 계획을 체결하고 day 종가로 평가(첫 호출은 가격만). 반환: (Month, 조정 종가)."""
        held = set()
        for ledger in self.ledgers:
            held.update(ledger.pos)
            held.update(i for i, _, _, _ in ledger.pending)
        wanted = (set(members) | {self.symbols[i] for i in held | set(self.prev_members)}
                  | set(self.bench_symbols.values()))
        start = datetime.combine(day - timedelta(days=45), datetime.min.time())
        if self.prev_signal is not None:
            start = min(start, datetime.combine(self.prev_signal, datetime.min.time()))
        raw, adj = window_bars(self.algo, wanted, start, datetime.combine(day + timedelta(days=1), datetime.min.time()),
                               self.rec.warn_once)
        m = self._month(raw, adj, eligible, day)
        if self.prev_signal is not None:
            year = self.prev_exec.year
            self.real.append(real_pv)
            for ledger in self.ledgers:
                ledger.values.append(ledger.settle(m, year))
            self._benchmarks(adj, day)
        return m, adj

    def _select(self, ledger, order, rank_of, pos_in, scored_idx, member_ids, keep_cut, fill_cut):
        """portfolio.select_holdings와 같은 밴드 규칙(동일가중이라 σ̂ 조건 없음)."""
        n = self.n
        if ledger.first:
            return [int(scored_idx[j]) for j in list(order[:n])]
        kept = []
        for i in ledger.pos:
            j = pos_in.get(i)
            if i in member_ids and j is not None and rank_of[j] + 1 <= keep_cut:
                kept.append(i)
        slots, added = n - len(kept), []
        for r, j in enumerate(list(order[:int(fill_cut) + 1])):
            if len(added) >= slots or r + 1 > fill_cut:
                break
            i = int(scored_idx[j])
            if i not in ledger.pos:
                added.append(i)
        return kept + added

    def _month(self, raw, adj, eligible, signal_date):
        m = Month()
        m.g_e, m.g_t, m.raw_e, m.raw_e_last, m.raw_t, m.half = {}, {}, {}, {}, {}, {}
        m.sector = self.sector
        prev_t, exec_d = self.prev_signal, self.prev_exec
        for s, days in adj.items():
            i = self._id(s)
            d_t = last_on_or_before(days, signal_date)
            if prev_t is not None:
                d_0, d_e = last_on_or_before(days, prev_t), last_on_or_before(days, exec_d)
                if d_0 and d_e:
                    m.g_e[i] = days[d_e] / days[d_0]
                if d_e and d_t:
                    m.g_t[i] = days[d_t] / days[d_e]
        for s, days in raw.items():
            i = self._id(s)
            if exec_d is not None:
                if exec_d in days:
                    m.raw_e[i] = days[exec_d][2]
                d_e = last_on_or_before(days, exec_d)
                if d_e:
                    m.raw_e_last[i] = days[d_e][2]
            d_t = last_on_or_before(days, signal_date)
            if d_t:
                m.raw_t[i] = days[d_t][2]
            rows = [days[d] for d in sorted(d for d in days if d <= signal_date)][-(SPREAD_WINDOW + 1):]
            rows = [r for r in rows if r[0] > 0 and r[1] > 0 and r[2] > 0 and r[0] >= r[1]]
            if len(rows) >= 3:
                ar = abdi_ranaldo([r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows])
                if ar is not None:
                    m.half[i] = min(max(ar / 2, TICK_SIZE / 2 / rows[-1][2]), MAX_REL_SPREAD / 2) + SLIPPAGE
        for s, c in eligible.items():                             # 계획 가격은 신호일 원주가(실제 A0와 같음)
            if s in self.ids and c.price > 0:
                m.raw_t[self.ids[s]] = float(c.price)
        return m

    def _benchmarks(self, adj, signal_date):
        """직전 신호일 → 이번 신호일 수익률: 유니버스 동일가중·역변동성(비례 비용 차감), RSP·SPY."""
        def ratio(s):
            days = adj.get(s)
            if not days or self.prev_signal is None:
                return None
            d0, d1 = last_on_or_before(days, self.prev_signal), last_on_or_before(days, signal_date)
            return days[d1] / days[d0] if d0 and d1 else None
        for key, weights in self.univ_w.items():
            if not weights:
                continue
            gross, drift = 0.0, {}
            for i, w in weights.items():
                g = ratio(self.symbols[i]) or 1.0
                drift[i] = w * g
                gross += w * g
            self.bench[key].append(gross - 1)
            self.univ_w[key] = {i: v / gross for i, v in drift.items()} if gross > 0 else {}
        for t, s in self.bench_symbols.items():
            if self.prev_signal is not None:
                g = ratio(s)
                self.bench[t].append(g - 1 if g else None)

    def _set_universe_weights(self, members, closes, m):
        """새 유니버스 목표 비중으로 바꾸고, 이동한 비중 × 반스프레드 × base 배수를 이번 달 수익률에서 뺀다."""
        mult = COST_SCENARIOS["base"]
        ids = [self.ids[s] for s in members]
        targets = {"EW": {i: 1 / len(ids) for i in ids} if ids else {}}
        inv = {}
        for s in members:
            sigma = sigma_hat(closes.get(s, [])) if closes else None
            if sigma:
                inv[self.ids[s]] = 1 / sigma
        total = sum(inv.values())
        targets["IVW"] = cap_weights({i: v / total for i, v in inv.items()})[0] if total else {}
        for key, target in targets.items():
            old = self.univ_w[key]
            moved = sum(abs(target.get(i, 0.0) - old.get(i, 0.0)) * m.half.get(i, DEFAULT_HALF_SPREAD)
                        for i in set(target) | set(old))
            if self.bench[key] and old:
                self.bench[key][-1] = (1 + self.bench[key][-1]) * (1 - mult * moved) - 1
            self.univ_w[key] = target

    def _plot(self):
        """월별 지수(1000에서 시작)를 차트로 남긴다(result.json에 저장되어 사후 분석에 씀)."""
        def mean_ret(name):
            rs = [l.values[-1] / l.values[-2] - 1 for l in self.ledgers if l.name == name and l.values[-2] > 0]
            return sum(rs) / len(rs) if rs else None
        points = {}
        for name in sorted({l.name for l in self.ledgers}):
            points[name] = mean_ret(name)
        for key, values in self.bench.items():
            if key != "SPY" and values and values[-1] is not None:
                points[key] = values[-1]
        for name, r in points.items():
            if r is None:
                continue
            self.index[name] *= 1 + r
            chart = "Bench" if name == "RSP" or name.startswith("sf_") else "Baseline"
            if self.mode == "final" or not name.startswith("cal"):
                self.algo.plot(chart, name, self.index[name])

    # ------------------------------------------------------------------
    def finish(self, last_day, real_pv):
        """마지막 신호일 뒤 계획을 마지막 거래일(last_day) 종가까지 체결·평가한 뒤(4단계 월말 자산과 같은 끝) 요약 로그
        ([BASE]·[SHADOW]·[RAND]·[SFACT]·[BENCH]·[SECTOR] 또는 [CAL])."""
        if self.prev_signal is not None and last_day > self.prev_signal:
            self._advance(last_day, [], {}, real_pv)
            self._plot()
        def stats(values):
            rs = [b / a - 1 for a, b in zip(values, values[1:]) if a > 0]
            if len(rs) < 2:
                return None
            mu = sum(rs) / len(rs)
            sd = math.sqrt(sum((r - mu) ** 2 for r in rs) / (len(rs) - 1))
            return {"mean": 12 * mu, "vol": math.sqrt(12) * sd, "cagr": (values[-1] / values[0]) ** (12 / len(rs)) - 1,
                    "rs": rs}
        def turnover(ledger):
            years = [v for v in ledger.turn.values() if v]
            return sum(years) / len(years) / 2 if years else 0.0
        def pct(xs, q):
            return float(np.percentile(xs, q)) * 100
        debug = self.algo.debug
        real = stats(self.real)
        n_months = len(self.real) - 1
        debug(f"[BASE] mode={self.mode} phi={RANDOM_PHI if self.mode == 'final' else CALIBRATE_PHIS} "
              f"seeds={RANDOM_SEEDS if self.mode == 'final' else CALIBRATE_SEEDS} costs={','.join(SHADOW_COSTS)} "
              f"a0={A0_SETTING} months={n_months} symbols={len(self.symbols)} ledgers={len(self.ledgers)}")
        by_name = defaultdict(list)
        for ledger in self.ledgers:
            by_name[ledger.name].append(ledger)
        rep = by_name["rep_base"][0]
        rs = stats(rep.values)
        if real and rs:
            diffs = [abs(a - b) for a, b in zip(real["rs"], rs["rs"])]
            debug(f"[SHADOW] A0 real vs replica(base): mean {real['mean']:+.2%} vs {rs['mean']:+.2%} "
                  f"cagr {real['cagr']:+.2%} vs {rs['cagr']:+.2%} | monthly diff max {max(diffs):.2%} "
                  f"avg {sum(diffs) / len(diffs):.3%} | replica to={turnover(rep):.2f}")
        if self.mode == "calibrate":
            parts = []
            for phi in CALIBRATE_PHIS:
                ls = by_name[f"cal{phi}"]
                tos = [turnover(l) for l in ls]
                means = [stats(l.values)["mean"] for l in ls]
                parts.append(f"{phi}:to={sum(tos) / len(tos):.2f}(sd{np.std(tos):.2f}) mean={np.mean(means):+.1%}")
            debug(f"[CAL] target_to(replica)={turnover(rep):.2f} | " + " | ".join(parts))
            return
        for cost in SHADOW_COSTS:
            ls = by_name[f"rand_{cost}"]
            means = [stats(l.values)["mean"] for l in ls]
            tos = [turnover(l) for l in ls]
            a0 = real if cost == "base" else stats(by_name[f"rep_{cost}"][0].values)
            a0_pct = sum(x < a0["mean"] for x in means) / len(means) * 100
            debug(f"[RAND {cost}] mean: avg {np.mean(means):+.2%} sd {np.std(means, ddof=1):.2%} "
                  f"p5/25/50/75/95 {pct(means, 5):+.1f}/{pct(means, 25):+.1f}/{pct(means, 50):+.1f}/"
                  f"{pct(means, 75):+.1f}/{pct(means, 95):+.1f}% | A0 {a0['mean']:+.2%} pct={a0_pct:.1f} "
                  f"excess={a0['mean'] - np.mean(means):+.2%} | to avg {np.mean(tos):.2f} (replica "
                  f"{turnover(by_name[f'rep_{cost}'][0]):.2f})")
        parts = []
        for k in ("mom", "qual", "value"):
            l = by_name[f"sf_{k}"][0]
            s = stats(l.values)
            parts.append(f"{k} mean={s['mean']:+.2%} cagr={s['cagr']:+.2%} vol={s['vol']:.1%} to={turnover(l):.2f}")
        debug("[SFACT] base " + " | ".join(parts))
        parts = []
        for key, values in self.bench.items():
            rs_b = [r for r in values if r is not None]
            if len(rs_b) > 1:
                mu = sum(rs_b) / len(rs_b)
                g = math.prod(1 + r for r in rs_b) ** (12 / len(rs_b)) - 1
                parts.append(f"{key} n={len(rs_b)} mean={12 * mu:+.2%} cagr={g:+.2%}")
        debug("[BENCH] " + " | ".join(parts) + f" | A0 mean={real['mean']:+.2%}")
        rand_sector = Counter()
        rand_months = 0
        for l in by_name["rand_base"]:
            rand_months += l.sector["_months"]
            for k, v in l.sector.items():
                if k != "_months":
                    rand_sector[k] += v
        rep_months = rep.sector["_months"] or 1
        diff = {k: rep.sector.get(k, 0.0) / rep_months - rand_sector.get(k, 0.0) / max(rand_months, 1)
                for k in set(rep.sector) | set(rand_sector) if k != "_months"}
        top = sorted(diff.items(), key=lambda kv: -abs(kv[1]))[:6]
        debug("[SECTOR] A0(replica) - random avg weight: " +
              " ".join(f"{SECTOR_LABELS.get(k, k)}{v:+.1%}" for k, v in top))
