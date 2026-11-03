# HistGradientBoosting·CatBoost 비교 결과

작성일: 2026-11-02

## 결과

기존 비교 도구에 두 트리 모델을 추가하고 보존된 실제 삼성전자 5분봉 4,232개로 실행했다. 신규 외부 데이터 다운로드는 하지 않았다. **이번 고정 설정에서는 앱 연결 기준을 통과한 후보가 없다.** 기존 앱 모델·계좌·주문 설정은 변경하지 않았다.

| 모델 | 검증 Macro-F1 | 시험 Macro-F1 | 시험 Brier↓ | 시험 판단 보류율 | 65% 이상 상승/하락 판단 | 연구 기준 |
|---|---:|---:|---:|---:|---:|---|
| 학습 클래스 비중 기준선 | — | 0.2466 | 0.5787 | 100.00% | 0 | 비교 기준 |
| 기존 로지스틱 회귀 | 0.2537 | 0.2466 | 0.5777 | 92.83% | 0 | 미통과 |
| 클래스 불균형 보정 회귀 | 0.4068 | 0.3421 | 0.6691 | 100.00% | 0 | 미통과 |
| HistGradientBoosting | 0.2495 | 0.3050 | 0.6145 | 99.32% | 0 | 미통과 |
| CatBoost | 0.2528 | 0.2529 | 0.5844 | 93.86% | 0 | 미통과 |

검증 구간에서 선택된 모델은 클래스 불균형 보정 회귀다. 두 트리 모델을 추가해도 이번 설정에서는 검증 성능이 이를 넘지 못했다. 선택 모델은 시험 Brier가 기준선보다 나쁘고 방향 예측이 없어 탈락했다. HistGradientBoosting도 같은 두 조건에서 탈락했고, CatBoost는 여기에 상승 클래스 재현율 0이 추가됐다. 이 결과는 해당 설정·자료에 대한 탐색 결과이며 트리 모델 전반이 열등하다는 결론은 아니다.

## 비교·선정 절차

1. 동일한 8개 가격·거래량 지표를 사용한다. 미래 1시간 방향과 ±0.5% 라벨 정의를 유지한다.
2. 시간순 60/20/20 분할에서 미래 라벨이 다음 구간과 겹치는 학습·검증 표본을 제거한다. 학습 865개, 검증 280개, 시험 293개다.
3. 각 모델의 학습에는 학습 구간만 전달한다. 트리 깊이 3, 120회 등의 작은 고정 설정을 사용하고 CPU 1스레드로 실행한다. HistGradientBoosting의 내부 조기종료를 끄고 CatBoost는 시간순 처리·파일 생성 금지를 지정했다. 시험 자료를 eval_set으로 전달하지 않는다.
4. 확률 온도 보정은 검증 구간만 사용한다. 검증 Macro-F1, 동점 시 Brier 순으로 후보를 선택한 뒤 모든 후보의 시험 성적을 보고용으로 계산한다. 시험 결과로 모델을 다시 선택하거나 교체하지 않는다.
5. 연구용 기준은 기준선 대비 F1 엄격 개선, Brier 비악화, 상승·하락 표본 및 재현율 존재다. 새 schema 2는 여기에 고정된 65% 기준에서 실제 상승/하락 판단이 적어도 1개 있는 조건을 추가한다. 중립 판단과 판단 보류를 구분하며, 판단 표본 0인 정확도는 null이다.
6. 실제 과거 데이터로 선언되고 위 기준을 통과한 검증 선택 모델만 app_connection_candidate에 기록한다. 다른 후보의 시험 결과를 보고 대체 승격하지 않는다. 합성·출처 미확인 자료는 연결 후보에서 제외한다.

이 기준은 탐색 단계의 최소 필터다. 통과하더라도 충분한 표본·안정성·독립 평가를 대체하지 못한다. 이번 app_connection_candidate는 null이고 deployment_approved는 false다. 모델 파일을 내보내거나 서비스 모델을 활성화하지 않는다.

## 구현

- `server/app/ml/candidates.py`: 기존 회귀 및 두 트리 모델 공통 실행, 클래스 순서(up/neutral/down) 정렬, 유한 확률·합 검증, 공통 온도 보정.
- `server/app/ml/experiment.py`: 후보별 검증·시험 성적, 보류·판단 수, 기준별 탈락 이유, 연결 후보 선정, 코드 해시·패키지 버전 기록.
- `server/pyproject.toml`, `server/uv.lock`: model-comparison 선택 의존성과 고정 버전. 일반 서버/Docker에는 트리 의존성을 강제하지 않는다.
- `server/tests/test_ml_candidates.py`, `server/tests/test_ml_experiment.py`: 실제 트리 학습과 비교 보호 검증.

## 검증

선택 의존성을 설치한 상태에서 관련 테스트 **26개 통과, 건너뜀 0개**. 두 트리의 반복 학습 재현성, 파일 미생성, 확률 열 순서와 오류 거절, 시험 정답 변경에도 검증 선택 유지, 탈락 선택 모델을 다른 시험 우수 모델로 교체하지 않음, 합성/출처 미확인 후보 제외, 전부 보류 시 탈락, 기존 학습 및 CSV 회귀를 확인했다. Ruff 검사·포맷 및 uv 잠금 파일 확인도 통과했다. 전체 DB·모바일 통합 테스트는 이번에 다시 실행하지 않았다.

실행 중 기존 Starlette/httpx 사용 중단 예고와 샌드박스의 물리 코어 수 조회 경고가 있었다. 코어 경고는 논리 코어 조회로 대체되었고 비교 연산에는 1스레드 제한을 적용했다.

## 재현

프로젝트 server 디렉터리에서 실행한다. 출력은 매번 새 파일을 지정한다.

```sh
uv sync --frozen --extra model-comparison
.venv/bin/python -m app.ml.experiment \
  --csv output/ai-review-2026-11-02/observed-005930.csv \
  --source yahoo-finance-5m --data-kind historical \
  --output output/ai-tree-comparison-2026-11-02/comparison-rerun.json
```

- 입력 CSV SHA-256: `02436a021e8fc80ab50f78f5f9900a2d05123cd69a6708d1e313fb4fcabfd7a1`. 이전 비교 입력 해시와 동일함을 확인했다.
- 패키지: scikit-learn 1.9.1, CatBoost 1.2.10, NumPy 2.5.4. 전체 버전과 코드 SHA-256은 JSON에 보존한다.
- [전체 비교 JSON](server/output/ai-tree-comparison-2026-11-02/comparison.json)
- [데이터 출처 기록](server/output/ai-review-2026-11-02/provenance.json)
- [실행 안내](server/docs/csv-training.md)

## 한계와 다음 단계

같은 자료를 이미 살펴봤으므로 새로운 독립 홀드아웃이라고 주장할 수 없다. 관측한 59일에 모두 일부 봉 누락이 있고, 한 종목·짧은 기간이며 1시간 라벨이 중첩된 표본도 독립 표본으로 볼 수 없다. 시간순 경계 제거와 별개로 통계적 불확실성·여러 기간 안정성 검증이 필요하다.

다음 단계는 추가 독립 기간·종목 및 사건 이전 학습 자료를 확보한 뒤, 이번 고정 절차나 사전에 정한 새 절차로 평가하는 것이다. 기존 시험 성적을 보며 반복 조정한 결과를 독립 성능으로 보고하지 않는다. 유효 후보가 생기면 추론 어댑터와 모델 설명 방식·버전 보존을 추가하고, 논문 ON/OFF 실험에서는 같은 모델을 양쪽 조건에 고정한다.

구현 참고: [HistGradientBoosting 공식 문서](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html), [CatBoost 공식 매개변수](https://catboost.ai/docs/en/references/training-parameters/common).
