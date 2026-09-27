# 새 세션용 지시문 — 4단계 12개 조합 자동 실행

(전제: 환경에서 `www.quantconnect.com` 네트워크 허용, 환경 변수 `QC_USER_ID`·`QC_API_TOKEN` 설정)

아래를 새 세션 첫 메시지로 붙여 넣기:

```
aidankim3/13f-consensus-screener 저장소의 claude/clever-knuth-9u1vg1 브랜치에서 작업해.
docs/PROGRESS.md, CLAUDE.md, qc_step4/NOTES.md를 먼저 읽고,
tools/qc_batch.py --cost base 를 백그라운드로 실행해서 4단계 12개 조합(전체 기간, 비용 base)을 QuantConnect API로 차례로 돌려.
- API 호출이 실패하면 오류를 읽고 스크립트를 고쳐서 다시 실행해(이미 끝난 조합은 건너뜀).
- 조합 하나가 끝날 때마다 results/step4/<조합>/ 결과를 3단계와 같은 기준([CONFIG]·지문·주문 체결·neg/rej/late·delist·[COST]·adv_over)으로
  점검하고 REVIEW.md를 쓰고 커밋·푸시해.
- 1시간마다 send_later로 스스로 점검을 예약해서, 스크립트가 멈췄으면 다시 실행해.
- 12개가 끝나면 results/step4/SUMMARY_base.md에 비교표를 만들고 PROGRESS.md를 업데이트해. 이어서 --cost low, --cost high도 같은 방식으로 진행해.
```
