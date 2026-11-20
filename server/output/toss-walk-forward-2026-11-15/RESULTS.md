# AI 모델 재검증 결과 — 2026-11-15

삼성전자와 SK하이닉스의 기존 저장 시세를 합쳐 9개 모델을 종목별 33개 기간에서 재검증했다. 기본 성능 기준과 방향 예측 신뢰도 기준을 모두 통과한 모델은 없다.

## 조건과 검증 범위

- 입력 기간은 2025-01-02부터 2026-07-21까지이며 종목별 28,536개 5분봉을 사용했다.
- 예측은 1시간 뒤 상승·중립·하락, 중립 경계는 ±0.5%, 확신 기준은 65%다.
- 각 기간은 학습 26일, 확률 보정 8일, 선택 8일, 테스트 10일이다. 테스트 기간은 서로 겹치지 않는다.
- 종목별 테스트 표본은 9,874개다. 방향 예측 신뢰도 집계에서는 1시간 이내 중복 신호를 제외한다.
- 기본 기준은 기준 모델 대비 macro-F1 개선, Brier 비악화, 상승·하락 재현율 확보, 확신 기준 이상 방향 예측 존재다.
- 기존 방향 신뢰도 기준은 신호 20건 이상 및 거래일 단위 부트스트랩 95% 구간 하한 50% 초과다.
- 이미 검토한 시세를 재사용한 탐색적 검증이다. 새 독립 검증 데이터에 대한 성능을 뜻하지 않는다.

## 결과

| 종목 | 모델 | Macro-F1 | Brier | 기본 기준 | 방향 적중/신호 | 방향 신뢰도 |
|---|---|---:|---:|---|---:|---|
| 005930 | validation-selected | 0.4060 | 0.4909 | 실패 | 14/81 | 실패 |
| 005930 | cross-stock-logistic | 0.4071 | 0.4913 | 실패 | 19/83 | 실패 |
| 005930 | cross-stock-catboost | 0.3775 | 0.4414 | 통과 | 1/2 | 실패 |
| 005930 | historical-neighbors | 0.3274 | 0.4652 | 실패 | 0/0 | 실패 |
| 005930 | rbf-svm | 0.3264 | 0.4533 | 실패 | 0/0 | 실패 |
| 005930 | random-convolution | 0.3697 | 0.5642 | 실패 | 42/212 | 실패 |
| 005930 | move-then-direction | 0.3977 | 0.4778 | 실패 | 13/50 | 실패 |
| 005930 | boosted-quantile-returns | 0.3852 | 0.4487 | 실패 | 6/9 | 실패 |
| 005930 | student-t-return-regression | 0.4244 | 0.4564 | 실패 | 13/41 | 실패 |
| 005930 | soft-vote | 0.3766 | 0.4588 | 실패 | 5/21 | 실패 |
| 000660 | validation-selected | 0.3893 | 0.6012 | 실패 | 27/135 | 실패 |
| 000660 | cross-stock-logistic | 0.3731 | 0.5957 | 실패 | 16/53 | 실패 |
| 000660 | cross-stock-catboost | 0.3659 | 0.5706 | 실패 | 2/8 | 실패 |
| 000660 | historical-neighbors | 0.3135 | 0.5711 | 실패 | 0/0 | 실패 |
| 000660 | rbf-svm | 0.3136 | 0.5684 | 실패 | 0/0 | 실패 |
| 000660 | random-convolution | 0.3626 | 0.6693 | 실패 | 54/297 | 실패 |
| 000660 | move-then-direction | 0.3758 | 0.5858 | 실패 | 7/25 | 실패 |
| 000660 | boosted-quantile-returns | 0.3716 | 0.5754 | 실패 | 0/1 | 실패 |
| 000660 | student-t-return-regression | 0.4009 | 0.5736 | 실패 | 11/41 | 실패 |
| 000660 | soft-vote | 0.3795 | 0.5726 | 실패 | 5/13 | 실패 |

validation-selected는 각 기간의 검증 데이터에서 선택한 모델을 그 다음 테스트 기간에 평가한 결과다. 두 종목 모두 기준 모델보다 확률 오차(Brier)가 높았다. 삼성전자 CatBoost만 기본 기준을 통과했으며 방향 신호는 2건, 적중은 1건이었다.

## 평가 코드 수정과 확인

- 평가 기간에 세 종류 정답이 모두 있어야 포함하던 조건을 제거했다. 학습 데이터의 세 클래스 요구 조건은 유지했다.
- 보정·선택·테스트 기간의 정답 클래스가 하나뿐이어도 기간이 누락되지 않는 회귀 테스트 3개를 추가했다.
- 관련 자동 테스트 27개가 통과했고 Ruff 검사 및 포맷 검사가 통과했다.
- 기존 fresh.json 대상 기간도 재실행했으며 두 종목의 결과가 이전과 완전히 동일했다. 따라서 이번 수정은 해당 기간의 기존 실패를 설명하지 않는다.
- 전체 이력 평가는 594회 모델 학습, 기존 기간 재확인은 54회 모델 학습을 수행했다.

## 결과 파일

- all-history.json에 전체 지표, 기간별 결과, 입력 SHA-256과 평가 코드 SHA-256이 있다.
- previous-period-recheck.json에 기존 기간 재실행 결과가 있다.
- 실행 모델은 cross-stock-logistic, cross-stock-catboost, historical-neighbors, rbf-svm, random-convolution, move-then-direction, boosted-quantile-returns, student-t-return-regression, soft-vote다.

## 재실행

server 폴더에서 다음 명령을 실행한다. 입력 CSV는 아래 임시 폴더에 있으므로 이후 삭제되면 같은 데이터를 다시 준비해야 한다. 출력 파일명은 새 이름을 사용한다.

```sh
.venv/bin/python -m tool.walk_forward_toss_models \
  --data /private/tmp/tradepilot-market-context-20261113 \
         /private/tmp/tradepilot-walk-forward-20261113 \
         /private/tmp/tradepilot-quant-20261113 \
         /private/tmp/tradepilot-model-search-20261113 \
  --output output/toss-walk-forward-2026-11-15/all-history-rerun.json \
  --label corrected-evaluation-all-inspected-history
```
