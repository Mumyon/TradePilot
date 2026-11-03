import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot_client/features/trading/presentation/replay_screen.dart';
import 'replay_test.dart' show ReplayFixture;

class FinishedFixture extends ReplayFixture {
  @override
  Map<String, dynamic> run() => {
    ...super.run(),
    'finished': true,
    'decisions': [
      {
        'virtual_at': '2024-01-26T03:05:00Z',
        'decision': 'deferred',
        'reason': '진입 가격을 벗어나 보류',
      },
    ],
    'summary': {
      'filled_orders': 0,
      'accepted_orders': 0,
      'plan_compliant_fills': 0,
      'plan_evaluated_fills': 0,
      'plan_unregistered_fills': 0,
      'plan_unavailable_fills': 0,
      'rule_qualified_checks': 1,
      'rule_qualified_submissions': 0,
      'warnings_presented': 1,
      'warned_deferrals': 1,
      'decision_seconds_mean': null,
      'decision_timed_count': 0,
      'final_equity_won': 10000000,
      'return_percent': 0,
      'max_drawdown_percent': 0,
      'warning_types': [
        {
          'title': '급등 추격 매수',
          'detected': 1,
          'exempt': 0,
          'unavailable': 0,
          'blocked': 0,
          'presented': 1,
          'deferred_after_presentation': 1,
          'submitted_after_presentation': 0,
          'closed_after_presentation': 0,
          'unresolved_after_presentation': 0,
          'submitted': 0,
          'filled': 0,
          'cancelled': 0,
          'advice': '다음 매수 전에 진입 가격 범위를 확인하세요.',
        },
      ],
    },
    'prediction_review': {
      'summary': {
        'unique_predictions': 1,
        'evaluated': 0,
        'correct': 0,
        'accuracy': null,
        'abstained': 1,
        'pending': 0,
        'unavailable': 0,
        'unavailable_checks': 0,
      },
      'observations': [
        {
          'check_ids': ['a', 'b'],
          'prediction': {
            'as_of': '2024-01-26T03:05:00Z',
            'direction': 'abstain',
            'model_version': 'frozen-v1',
          },
          'outcome': {
            'status': 'resolved',
            'actual_direction': 'up',
            'correct': null,
            'target_at': '2024-01-26T04:05:00Z',
            'base_price_won': 10000,
            'target_price_won': 10100,
            'return_percent': 1,
          },
        },
      ],
    },
  };
}

void main() {
  testWidgets(
    'finished replay separates abstention, outcomes and behavior feedback',
    (tester) async {
      await tester.pumpWidget(
        MaterialApp(home: ReplayScreen(repository: FinishedFixture())),
      );
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.text('이어서 실험'), 250);
      await tester.tap(find.text('이어서 실험'));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.text('당시 AI 예측과 1시간 후 결과'), 200);
      expect(find.text('방향 일치율 평가 없음 · 판단 보류 1건'), findsOneWidget);
      await tester.scrollUntilVisible(find.text('실제 상승 · 판단 보류 · 일치율 제외'), 100);
      await Scrollable.ensureVisible(
        tester.element(find.text('실제 상승 · 판단 보류 · 일치율 제외')),
        alignment: 0.5,
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('실제 상승 · 판단 보류 · 일치율 제외'));
      await tester.pumpAndSettle();
      expect(find.text('모델 frozen-v1 · 관련 점검 2건'), findsOneWidget);
      await tester.scrollUntilVisible(find.text('판단 기록 · 1건'), 100);
      await Scrollable.ensureVisible(
        tester.element(find.text('판단 기록 · 1건')),
        alignment: 0.5,
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('판단 기록 · 1건'));
      await tester.pumpAndSettle();
      expect(find.text('진입 가격을 벗어나 보류'), findsOneWidget);
      await tester.scrollUntilVisible(find.text('유형별 행동 피드백'), 200);
      await Scrollable.ensureVisible(
        tester.element(find.text('유형별 행동 피드백')),
        alignment: 0.5,
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('유형별 행동 피드백'));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.text('급등 추격 매수 · 탐지 1회'), 100);
      expect(find.text('경고 표시 1회 · 표시 후 보류 1회 · 진행 0회'), findsOneWidget);
      expect(find.text('다음 매수 전에 진입 가격 범위를 확인하세요.'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
