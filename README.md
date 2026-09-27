# 미국 주식 멀티팩터 프로그램 매매

QuantConnect(LEAN)에서 미국 대형주를 대상으로 **모멘텀·퀄리티·가치** 멀티팩터 전략을 단계별로 만들고 검증하는 저장소입니다.
기준 문서는 [`docs/plan_v4.3.md`](docs/plan_v4.3.md), 진행 기록은 [`docs/PROGRESS.md`](docs/PROGRESS.md)입니다.

## 전략 요약
- **유니버스**: 매월 마지막 거래일 기준 시가총액 상위 약 1,000종목(금융·부동산 제외, 상장폐지 종목 포함으로 생존편향 제거)
- **팩터**: 모멘텀 12-1, 퀄리티 3개, 가치 4개 → 섹터 내 순위 → 스타일 평균 → z점수
- **구성·매매**: 상위 N(40·60·80)종목, 동일가중 / 역변동성 가중, 상위 20% 편입·상위 40% 유지, 다음 거래일 MOC 주문
- **검증 기간**: 1998~2015 (이후 구간은 검증 프로토콜에 따라 별도 사용)

## 진행 상황
| 단계 | 폴더 | 내용 | 상태 |
|---|---|---|---|
| 1 | `qc_step1/` | 유니버스 구성 | 완료 |
| 2 | `qc_step2/` | 팩터 점수 | 완료 |
| 3 | `qc_step3/` | 포트폴리오 구성·매매 (+커버리지 점검), 6개 조합 전체 기간 실행 | 완료 |
| 4 | – | 스프레드·슬리피지, 비용 시나리오 | 다음 |
| 5 | – | 기준선(무작위 Top-N, RSP, SPY)·IC 추정·검증 | 예정 |

## 폴더 구조
```
docs/            계획서·진행 기록
qc_step1~3/      단계별 QuantConnect 코드 (이전 단계는 백업으로 보존)
results/         백테스트 로그·결과 파일 (단계별 하위 폴더)
tools/           업로드 전 점검 스크립트
```

## 작업 흐름
1. Claude가 다음 단계 구현 프롬프트 작성
2. VS Code Claude 익스텐션이 `qc_stepN/` 코드 작성 + 가짜 QC 환경에서 시험
3. `python tools/check_qc.py qc_stepN`으로 글자 수·main.py·중복 붙여넣기 점검
4. QuantConnect 웹 IDE의 같은 이름 탭에 붙여 넣고 Ctrl+S → 백테스트 실행
5. 로그·결과 파일을 `results/stepN/`에 올리고 Claude가 점검 → `docs/PROGRESS.md` 업데이트

## QuantConnect 제약 (요약)
- 파일당 32,000자 (목표 28,000자 이하)
- 로그는 백테스트당 10KB, 터미널에는 `self.debug`만 출력
- Object Store 쓰기 불가 → `SAVE_TO_OBJECT_STORE = False`

자세한 내용은 [`docs/PROGRESS.md`](docs/PROGRESS.md)의 "QuantConnect 환경 메모"를 참고하세요.
