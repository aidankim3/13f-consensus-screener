# region imports
from AlgorithmImports import *
# endregion
# 1·2단계 기록·로그: [CONFIG](1·2단계)/[START]/[DIAG]/[UNIV]/[YEAR]/[FACTOR]/[SPOT]/[FYEAR]/[SUMMARY]/[WARN],
# 월별 CSV·Object Store 저장, 차트, 런타임 통계. 3단계 로그([REBAL]/[FILL]/[PYEAR]/[PERF])는 report.py
from collections import Counter

from config import *
from factors import QUALITY_KEYS, REASONS, VALUE_KEYS
from universe import raw_daily_bars, to_date


class FieldCollector:
    """첫 재구성 전까지 Morningstar 필드 값 분포를 모은다([DIAG]용). NOTES.md [C]."""

    def __init__(self):
        self.type_counts, self.exchange_counts, self.country_counts = Counter(), Counter(), Counter()
        self.sample_text = f"{CHECK_TICKER} not found"

    def observe(self, f):
        if f.has_fundamental_data:
            sec = f.security_reference
            self.type_counts[sec.security_type] += 1
            if sec.security_type == COMMON_STOCK_TYPE:
                self.exchange_counts[sec.exchange_id] += 1
                self.country_counts[f.company_reference.country_id] += 1
        if f.symbol.value == CHECK_TICKER:
            self.sample_text = (f"{CHECK_TICKER} price={f.price} mcap={f.market_cap / 1e9:.2f}B "
                                f"ipo={to_date(f.security_reference.ipo_date)}")


class Recorder:
    """월별 기록(계획서 8장 버전 관리)과 로그. 로그 한도 때문에 요약만 남긴다(NOTES.md [H])."""

    YEAR_SUM_KEYS = ("entries", "exits", "exit_rank", "exit_filtered", "exit_gone", "pit_late")

    def __init__(self, algo):
        self.algo = algo
        self.monthly_rows = []
        self.change_rows = []
        self.file_date_type = None
        self.factor_rows = []           # 월별 팩터 요약(점수 산출 비율·제외 사유) — [SUMMARY]용
        self._factor_detail_logged = 0  # [FACTOR] 상세를 남긴 달 수(점수가 나온 달만 셈)
        self._year_acc = None
        self._factor_year = None
        self._warned = set()

    def key_log(self, message):
        """핵심 줄([CONFIG]·[START]·[SUMMARY]·[WARN])은 debug로만(debug도 로그 파일에 기록돼 log와 쓰면 중복). NOTES.md [H]."""
        self.algo.debug(message)

    def warn_once(self, key, message):
        if key not in self._warned:
            self._warned.add(key)
            self.key_log("[WARN] " + message[:WARN_MAX_CHARS])

    def log_config(self):
        """1·2단계 실행 설정 기록(CLAUDE.md 원칙 5, 계획서 8장). 로그 스위치 값으로 올라간 파일 버전 확인(미정의는 n/a)."""
        self.key_log(f"[CONFIG] step=1-universe period={START_DATE}~{END_DATE} cash={INITIAL_CASH} "
                     f"entry={ENTRY_RANK} retain={RETAIN_RANK} min_price={MIN_PRICE} "
                     f"min_listing_months={MIN_LISTING_MONTHS} excluded_sectors={list(EXCLUDED_SECTOR_CODES)} "
                     f"reit_excluded=True type={COMMON_STOCK_TYPE} exchanges={list(ALLOWED_EXCHANGES)} "
                     f"countries={list(ALLOWED_COUNTRIES)} share_class=max_adv_{SHARE_CLASS_ADV_DAYS}d "
                     f"sector_na_excluded=True lean_data_start={LEAN_DATA_START}")
        self.key_log(f"[CONFIG] filing_lag_trading_days={FILING_LAG_TRADING_DAYS} "
                     f"approx_filing_last_year={APPROX_FILING_LAST_YEAR} "
                     f"approx_extra_lag_days={APPROX_FILING_EXTRA_LAG_DAYS} "
                     f"start_check=sample{START_CHECK_SAMPLE}/ratio{START_CHECK_MIN_RATIO}/tol{PRICE_MATCH_TOLERANCE} "
                     f"data=QC US Equities + Morningstar US Fundamentals (feed switched 2026-09-23)")
        self.key_log(f"[CONFIG] step=2-factors mom={MOM_LOOKBACK_MONTHS}-{MOM_SKIP_MONTHS}m "
                     f"min_months={MOM_MIN_MONTHS} expiry={FILING_EXPIRY_DAYS}d quality=3/3 "
                     f"value={VALUE_MIN_METRICS}/{VALUE_METRIC_COUNT} min_sector={MIN_SECTOR_SIZE} "
                     f"merge_order={','.join(str(c) for c in SECTOR_MERGE_ORDER)} ttm=q{TTM_QUARTERS}|twelve_months "
                     f"qgap={QUARTER_GAP_MIN_DAYS}-{QUARTER_GAP_MAX_DAYS}d z=ddof0 "
                     f"spot=mom%|q:gp/ta,ni/ta,tl/ta|v:e/p,b/p,fcf/p,s/p|$B:mcap,rev,ni,ta "
                     f"log_step1_year={LOG_STEP1_YEAR} log_step2_year={globals().get('LOG_STEP2_YEAR', 'n/a')}")
        if LOG_STEP1_CHECKS:
            self.algo.log("[LEGEND] " + " ".join(f"{code}={label}" for code, label in SECTOR_LABELS.items()))

    # ------------------------------------------------------------------
    # 첫 신호일 데이터 확인 (사용자 지시 2026-09-26)
    # ------------------------------------------------------------------
    def check_start_data(self, signal_date, eligible):
        """시총 상위 표본의 신호일 원주가 일봉 존재(bar), Fundamental 가격 = 그 종가(match, NOTES.md [A][B]),
        신호일 이전 공시일 존재(filing)가 각각 START_CHECK_MIN_RATIO 이상이면 통과. 적격 수는 조건 아님(NOTES.md 기록).
        반환: (통과, 문구, 적격 < ENTRY_RANK 여부)."""
        sample = sorted(eligible, key=lambda s: (-eligible[s].mcap, str(s.id)))[:START_CHECK_SAMPLE]
        bars = raw_daily_bars(self.algo, sample, START_CHECK_BARS, self.warn_once)
        with_bar = matched = with_filing = 0
        for s in sample:
            close = next((c for day, c, _ in bars.get(s, []) if day == signal_date), None)
            if close:
                with_bar += 1
                matched += abs(eligible[s].price / close - 1) <= PRICE_MATCH_TOLERANCE
            file_date = eligible[s].file_date
            with_filing += file_date is not None and file_date <= signal_date
        need = START_CHECK_MIN_RATIO * len(sample)
        data_ok = bool(sample) and min(with_bar, matched, with_filing) >= need
        text = (f"check: eligible={len(eligible)} sample={len(sample)} bar_at_sig={with_bar} "
                f"price_match={matched} filing={with_filing}")
        return data_ok, text, len(eligible) < ENTRY_RANK

    def log_start_deferred(self, signal_date, check_text, eligible_short):
        self.key_log(f"[START] sig={signal_date} {check_text} -> data missing, first rebuild deferred to next month-end"
                     f"{self._eligible_tail(eligible_short)}")

    def log_start_applied(self, signal_date, check_text, deferred, data_ok, eligible_short):
        mode = "deferred" if deferred else "on_schedule"
        note = "" if data_ok else " WARN check failed again, proceeding"
        self.key_log(f"[START] sig={signal_date} {check_text} -> first rebuild applied ({mode}){note}"
                     f"{self._eligible_tail(eligible_short)}")

    @staticmethod
    def _eligible_tail(eligible_short):
        """적격 종목이 ENTRY_RANK 미만일 때 [START] 줄 끝 표시(보류 사유 아님)."""
        return f" eligible<{ENTRY_RANK} (NOTES 기록 참고)" if eligible_short else ""

    # ------------------------------------------------------------------
    # 월별 기록
    # ------------------------------------------------------------------
    def record_month(self, signal_date, first_run, screen, ranked, rank, members, entries, exits, exit_reason,
                     pit_late, file_date_missing, multi_groups, adv_missing):
        """월별 CSV 한 줄과 진입·탈락 기록(계획서 8장 재현성)을 쌓고 그 줄을 돌려준다."""
        eligible = screen.eligible
        exit_gone = sum(r == "gone" for r in exit_reason.values())
        exit_filtered = sum(r.startswith("filt:") for r in exit_reason.values())
        sector_counts = Counter(SECTOR_LABELS[eligible[s].sector] for s in members)
        cut_entry = eligible[ranked[ENTRY_RANK - 1]].mcap if len(ranked) >= ENTRY_RANK else 0.0
        cut_retain = eligible[ranked[RETAIN_RANK - 1]].mcap if len(ranked) >= RETAIN_RANK else 0.0

        row = {
            "run_date": self.algo.time.date().isoformat(),
            "signal_date": signal_date.isoformat(),
            "n": len(members),
            "entries": len(entries),
            "exits": len(exits),
            "exit_rank": len(exits) - exit_gone - exit_filtered,
            "exit_filtered": exit_filtered,
            "exit_gone": exit_gone,
            "eligible": len(eligible),
            "total": len(screen.present),
            "cut_entry_mcap": round(cut_entry),
            "cut_retain_mcap": round(cut_retain),
            "pit_late": pit_late,
            "file_date_missing": file_date_missing,
            "multi_class_companies": len(multi_groups),
            "adv_missing": adv_missing,
            "listing_presample": screen.listing_presample,
            "listing_sid_pass": screen.listing_sid_pass,
            "approx_filing_period": int(signal_date.year <= APPROX_FILING_LAST_YEAR),
        }
        row.update({f"sec_{label}": sector_counts.get(label, 0) for label in SECTOR_LABELS.values()})
        row.update({f"drop_{key}": screen.funnel.get(key, 0) for key in FUNNEL_ORDER})
        self.monthly_rows.append(row)

        for s in sorted(entries, key=lambda s: rank[s]):
            self.change_rows.append(
                f"{signal_date},IN,{'init' if first_run else 'entry'},{rank[s]},{s.value},{s.id}")
        for s in sorted(exits, key=lambda s: str(s.id)):
            self.change_rows.append(
                f"{signal_date},OUT,{exit_reason[s]},{rank.get(s, '')},{s.value},{s.id}")
        return row

    def log_diag(self, signal_date, screen, collector, multi_groups, adv, adv_missing, representatives):
        """첫 재구성 필드 점검. NOTES.md [C][D][G][I]. 2단계에서는 LOG_STEP1_CHECKS가 True일 때만."""
        if not LOG_STEP1_CHECKS:
            return
        funnel = screen.funnel
        funnel_text = " ".join(f"{k}={funnel.get(k, 0)}" for k in FUNNEL_ORDER)
        self.algo.log(f"[DIAG] run={self.algo.time:%Y-%m-%d} sig={signal_date} total={len(screen.present)} "
                      f"drop: {funnel_text} -> eligible={len(screen.eligible)} | ipo_missing: "
                      f"presample_pass={screen.listing_presample} sid_pass={screen.listing_sid_pass} "
                      f"sid_fail={funnel.get('listing_sid', 0)} "
                      f"| multi_class={len(multi_groups)} adv_missing={adv_missing}")
        self.algo.log(f"[DIAG] security_type {self._top(collector.type_counts, 4)} "
                      f"| exchange {self._top(collector.exchange_counts, 5)} "
                      f"| country {self._top(collector.country_counts, 4)} | file_date_type={self.file_date_type}")
        self.algo.log(f"[DIAG] sample {collector.sample_text} | share_class "
                      f"{self._share_class_text(multi_groups, adv, representatives, screen.candidates)}")

    # ------------------------------------------------------------------
    # 팩터 기록 (2단계, 계획서 6장)
    # ------------------------------------------------------------------
    def log_factor_month(self, month):
        """점수가 처음 나온(scored > 0) FACTOR_DETAIL_MONTHS달은 [FACTOR] 상세, SPOT_MONTHS에는 [SPOT] 확인 줄."""
        sig = month.signal_date
        if month.z and self._factor_detail_logged < FACTOR_DETAIL_MONTHS:
            self._factor_detail_logged += 1
            merges = ";".join(month.merges) or "none"
            self.algo.log(f"[FACTOR] sig={sig} targets={len(month.records)} scored={len(month.z)} "
                          f"ex:{self._reason_text(month.reasons)} ttm:q4={month.ttm['q4']},"
                          f"ttm12={month.ttm['ttm12']},none={month.ttm['none']} merge={merges} "
                          f"z:mean={month.z_mean:.3f},sd={month.z_sd:.3f} chk:capex_pos={month.checks['capex_pos']},"
                          f"assets_single={month.checks['assets_single']},rev_zero={month.checks['rev_zero']}")
        if (sig.year, sig.month) in SPOT_MONTHS:
            by_ticker = {s.value: s for s in month.records}
            for ticker in SPOT_TICKERS:
                symbol = by_ticker.get(ticker)
                if symbol is None:
                    self.algo.log(f"[SPOT {sig} {ticker}] not in universe")
                else:
                    self.algo.log(self._spot_line(sig, ticker, month.records[symbol], month.z.get(symbol)))

    @staticmethod
    def _spot_line(sig, ticker, r, z):
        """원 지표값과 z. 항목 순서는 [CONFIG] spot= 범례(비율은 배수, mom은 %, 금액은 십억 달러)."""
        ratio = lambda v: "na" if v is None else f"{v:.3f}"
        usd = lambda v: "na" if v is None else f"{v / 1e9:.1f}"
        mom = "na" if r.get("mom") is None else f"{r['mom'] * 100:+.1f}%"
        quality = ",".join(ratio(r.get(k)) for k in QUALITY_KEYS)
        value = ",".join(ratio(r.get(k)) for k in VALUE_KEYS)
        amounts = ",".join(usd(r.get(k)) for k in ("mcap", "rev", "ni", "ta"))
        result = f"z={z:+.2f}" if z is not None else "excluded=" + ",".join(r["fail"])
        return (f"[SPOT {sig} {ticker}] mom={mom} q={quality} v={value} $B={amounts} "
                f"fd={r.get('file_date', 'na')} ttm={r.get('ttm', 'na')} {result}")

    def close_month(self, row, signal_date, n_members, n_eligible, n_entries, n_exits, factor_month):
        """월별 콘솔 줄(LOG_STEP1_YEAR일 때 처음 몇 달만), 연도 합계(유니버스·팩터), 차트, 중간 저장."""
        if LOG_STEP1_YEAR and (CONSOLE_MONTHLY_LOG or len(self.monthly_rows) <= CONSOLE_FIRST_MONTHS):
            self._log_month(row)
        self._accumulate_year(row, signal_date)
        self._accumulate_factor_year(factor_month, signal_date)

        self.algo.plot("Universe", "Members", n_members)
        self.algo.plot("Universe", "Eligible", n_eligible)
        self.algo.plot("Universe Flow", "Entries", n_entries)
        self.algo.plot("Universe Flow", "Exits", n_exits)

        if len(self.monthly_rows) % SAVE_EVERY_MONTHS == 0:
            self.save_records()

    def summary(self, start_deferred, empty_calls, extra_text="", extra_stats=None):
        """종료 요약, 런타임 통계, 최종 저장. extra_text·extra_stats는 3단계 요약(report.py)."""
        self._flush_year()
        rows = self.monthly_rows
        if not rows:
            self.key_log("[SUMMARY] universe never built - check selection function and data")
            return
        sizes = [r["n"] for r in rows]
        self.key_log(f"[SUMMARY] start={'deferred' if start_deferred else 'on_schedule'} months={len(rows)} "
                     f"first_sig={rows[0]['signal_date']} last_sig={rows[-1]['signal_date']} "
                     f"n_min={min(sizes)} n_avg={sum(sizes) / len(sizes):.0f} n_max={max(sizes)} "
                     f"entries_after_init={sum(r['entries'] for r in rows[1:])} "
                     f"exits={sum(r['exits'] for r in rows)} gone={sum(r['exit_gone'] for r in rows)} "
                     f"short_months={sum(r['n'] < ENTRY_RANK for r in rows)} "
                     f"pit_late_months={sum(r['pit_late'] > 0 for r in rows)} "
                     f"pit_late_max={max(r['pit_late'] for r in rows)} empty_calls={empty_calls}"
                     f"{self._factor_summary_text()}{extra_text}")
        self._set_runtime_statistics(rows, sizes, extra_stats)
        self.save_records()

    def _set_runtime_statistics(self, rows, sizes, extra_stats):
        """전체 기간 핵심 숫자를 런타임 통계로도 표시(로그 한도와 무관). 키 설명은 NOTES.md 출력 절."""
        scored = [f["coverage"] for f in self.factor_rows if f["signal_date"].year >= FACTOR_SCORE_START_YEAR]
        coverage = [f["coverage"] for f in self.factor_rows]
        ttm = Counter()
        for f in self.factor_rows:
            ttm.update(f["ttm"])
        ttm_total = sum(ttm.values())
        stats = {
            "months": str(len(rows)),
            "first_sig": str(rows[0]["signal_date"]),
            "n_avg": f"{sum(sizes) / len(sizes):.0f}",
            "gone": str(sum(r["exit_gone"] for r in rows)),
            "cov_avg": f"{sum(coverage) / len(coverage):.3f}" if coverage else "na",
            "cov_min99": f"{min(scored):.3f}" if scored else "na",
            "q4": f"{ttm['q4'] / ttm_total:.2f}" if ttm_total else "na",
        }
        stats.update(extra_stats or {})                 # 3단계(report.py): 회전율·수수료·보유·현금·[PERF]
        for key, value in stats.items():
            try:
                self.algo.set_runtime_statistic(key, value)
            except Exception as err:
                self.warn_once("runtime_stat", f"set_runtime_statistic failed: {err}")
                return

    def _factor_summary_text(self):
        """[SUMMARY] 끝에 붙는 전체 기간 팩터 요약: 점수 산출 비율 평균·최소, 가장 흔한 제외 사유."""
        if not self.factor_rows:
            return " | factors: none"
        coverage = [f["coverage"] for f in self.factor_rows]
        reasons = Counter()
        for f in self.factor_rows:
            reasons.update(f["reasons"])
        top = reasons.most_common(1)
        top_text = f"{top[0][0]}({top[0][1]})" if top else "none"
        return (f" | factors: months={len(coverage)} cov_avg={sum(coverage) / len(coverage):.3f} "
                f"cov_min={min(coverage):.3f} top_ex={top_text}")

    def save_records(self):
        """월별·진입탈락 기록을 Object Store에 저장(SAVE_TO_OBJECT_STORE가 False면 안 함, 실패하면 경고). NOTES.md [H]."""
        if not SAVE_TO_OBJECT_STORE or not self.monthly_rows:
            return
        monthly = "\n".join([",".join(self.monthly_rows[0].keys())]
                            + [",".join(str(v) for v in r.values()) for r in self.monthly_rows])
        changes = "\n".join(["signal_date,action,reason,rank,ticker,sid"] + self.change_rows)
        try:
            self.algo.object_store.save(OBJECT_STORE_MONTHLY_KEY, monthly)
            self.algo.object_store.save(OBJECT_STORE_CHANGES_KEY, changes)
        except Exception as err:
            self.warn_once("store", f"object store save failed: {err}")

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------
    def _log_month(self, row):
        approx = " APPROX_FD" if row["approx_filing_period"] else ""
        self.algo.log(f"[UNIV] run={row['run_date']} sig={row['signal_date']} n={row['n']} in={row['entries']} "
                      f"out={row['exits']}(rank={row['exit_rank']},filt={row['exit_filtered']},"
                      f"gone={row['exit_gone']}) elig={row['eligible']} "
                      f"cut{ENTRY_RANK}={row['cut_entry_mcap'] / 1e9:.2f}B pit_late={row['pit_late']} "
                      f"fd_na={row['file_date_missing']}{approx} | {self._sector_text(row)}")

    def _accumulate_year(self, row, signal_date):
        """신호일 연도별 합계. 연도가 바뀌면 직전 연도 [YEAR] 줄을 남긴다."""
        if self._year_acc is not None and self._year_acc["year"] != signal_date.year:
            self._flush_year()
        if self._year_acc is None:
            self._year_acc = {"year": signal_date.year, "months": 0, "n_min": row["n"], "n_max": row["n"],
                              "short": 0, **{k: 0 for k in self.YEAR_SUM_KEYS}}
        acc = self._year_acc
        acc["months"] += 1
        acc["n_min"] = min(acc["n_min"], row["n"])
        acc["n_max"] = max(acc["n_max"], row["n"])
        acc["short"] += int(row["n"] < ENTRY_RANK)
        for k in self.YEAR_SUM_KEYS:
            acc[k] += row[k]
        acc["last"] = row

    def _flush_year(self):
        acc = self._year_acc
        if acc is None:
            return
        last = acc["last"]
        if LOG_STEP1_YEAR:
            self.algo.log(f"[YEAR {acc['year']}] months={acc['months']} n_end={last['n']} n_min={acc['n_min']} "
                          f"n_max={acc['n_max']} in={acc['entries']} out={acc['exits']}(rank={acc['exit_rank']},"
                          f"filt={acc['exit_filtered']},gone={acc['exit_gone']}) short={acc['short']} "
                          f"pit_late={acc['pit_late']} elig_end={last['eligible']} "
                          f"cut{ENTRY_RANK}={last['cut_entry_mcap'] / 1e9:.2f}B | {self._sector_text(last)}")
        self._year_acc = None
        self._flush_factor_year()

    def _accumulate_factor_year(self, month, signal_date):
        """팩터 월 요약을 쌓는다. 연도 전환 시 [FYEAR]는 _flush_year가 [YEAR] 바로 뒤에 남긴다."""
        coverage = len(month.z) / len(month.records) if month.records else 0.0
        self.factor_rows.append({"signal_date": signal_date, "coverage": coverage, "reasons": month.reasons,
                                 "ttm": month.ttm})
        if self._factor_year is None:
            self._factor_year = {"year": signal_date.year, "coverage": [], "reasons": Counter(), "ttm": Counter(),
                                 "merge_months": 0}
        acc = self._factor_year
        acc["coverage"].append(coverage)
        acc["reasons"].update(month.reasons)
        acc["ttm"].update(month.ttm)
        acc["merge_months"] += bool(month.merges)

    def _flush_factor_year(self):
        acc = self._factor_year
        if acc is None:
            return
        coverage = acc["coverage"]
        ttm_total = sum(acc["ttm"].values())
        q4_share = acc["ttm"]["q4"] / ttm_total if ttm_total else 0.0
        if LOG_STEP2_YEAR:
            self.algo.log(f"[FYEAR {acc['year']}] m={len(coverage)} cov_avg={sum(coverage) / len(coverage):.3f} "
                          f"cov_min={min(coverage):.3f} ex:{self._reason_text(acc['reasons'])} "
                          f"q4={q4_share:.2f} merge_m={acc['merge_months']}")
        self._factor_year = None

    @staticmethod
    def _reason_text(reasons):
        return ",".join(f"{r}={reasons.get(r, 0)}" for r in REASONS)

    @staticmethod
    def _share_class_text(multi_groups, adv, representatives, candidates):
        """[DIAG]용: 시총이 가장 큰 복수 종류 회사의 종류별 거래대금·시총. *가 대표 주식."""
        if not multi_groups:
            return "none"
        by_symbol = {f.symbol: f for f, _ in candidates}
        group = max(multi_groups, key=lambda symbols: max(by_symbol[s].market_cap for s in symbols))
        return " ".join(f"{'*' if s in representatives else ''}{s.value}(adv={adv.get(s, 0.0) / 1e6:.1f}M,"
                        f"mcap={by_symbol[s].market_cap / 1e9:.1f}B)" for s in group)

    @staticmethod
    def _sector_text(row):
        return " ".join(f"{label}={row['sec_' + label]}" for label in SECTOR_LABELS.values())

    @staticmethod
    def _top(counter, k):
        return " ".join(f"{key}:{count}" for key, count in counter.most_common(k))
