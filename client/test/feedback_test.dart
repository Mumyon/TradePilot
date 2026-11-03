import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot_client/features/trading/domain/models.dart';
import 'package:tradepilot_client/features/trading/domain/workspace_repository.dart';
import 'package:tradepilot_client/features/trading/presentation/feedback_screen.dart';
import 'package:tradepilot_client/features/trading/presentation/risk_confirmation.dart';

class FeedbackFixture implements WorkspaceRepository {
  bool fail = false;
  final paths = <String>[];
  @override
  Future<Map<String, dynamic>> workspaceRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    paths.add(path);
    if (fail) throw StateError('offline');
    if (path.startsWith('/v1/feedback/export')) {
      return {'csv': 'check_id,outcome\nc1,dismissed\n', 'rows': 1};
    }
    const empty = {
      'checks': 0,
      'filled': 0,
      'plan_compliance': null,
      'plan_evaluated': 0,
      'plan_adherent': 0,
      'plan_unregistered': 0,
      'plan_unavailable': 0,
      'decision_samples': 0,
      'mean_decision_seconds': null,
    };
    return {
      'window': {
        'start': '2026-10-01T00:00:00Z',
        'end': '2026-10-20T00:00:00Z',
      },
      'groups': {'on': empty, 'off': empty},
      'compliance_difference_pp': null,
      'warning_types': [
        {
          'title': '급등 추격 매수',
          'detected': 1,
          'presented': 1,
          'defer_rate': 1.0,
          'voluntary_resolved': 1,
          'unobserved': 0,
          'outcomes': {'dismissed': 1},
          'feedback': '사전 진입 가격을 확인하세요.',
        },
      ],
      'items': [],
      'next_offset': null,
      'excluded': {},
      'notes': ['연구 기록 안내'],
    };
  }
}

void main() {
  testWidgets(
    'comparison keeps unknown denominators and exposes outcome breakdown',
    (tester) async {
      final repo = FeedbackFixture();
      await tester.pumpWidget(
        MaterialApp(home: FeedbackScreen(repository: repo)),
      );
      await tester.pumpAndSettle();
      expect(find.text('계획 준수율 평가 기록 없음'), findsNWidgets(2));
      await tester.scrollUntilVisible(find.textContaining('급등 추격 매수 ·'), 200);
      await tester.tap(find.textContaining('급등 추격 매수 ·'));
      await tester.pumpAndSettle();
      expect(find.text('명시적 보류: 1건'), findsOneWidget);
      expect(find.text('사전 진입 가격을 확인하세요.'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'CSV export copies authenticated response and changing period reloads',
    (tester) async {
      final repo = FeedbackFixture();
      String? copied;
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        (call) async {
          if (call.method == 'Clipboard.setData') {
            copied = (call.arguments as Map)['text'] as String;
          }
          return null;
        },
      );
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          SystemChannels.platform,
          null,
        ),
      );
      await tester.pumpWidget(
        MaterialApp(home: FeedbackScreen(repository: repo)),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byType(DropdownButton<int>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('7일').last);
      await tester.pumpAndSettle();
      expect(repo.paths.last, '/v1/feedback?days=7&offset=0');
      await tester.scrollUntilVisible(
        find.byKey(const ValueKey('feedback-export')),
        250,
      );
      await tester.tap(find.byKey(const ValueKey('feedback-export')));
      await tester.pumpAndSettle();
      expect(repo.paths.last, '/v1/feedback/export?days=7');
      expect(copied, 'check_id,outcome\nc1,dismissed\n');
    },
  );

  testWidgets('failed refresh hides outdated comparison and supports retry', (
    tester,
  ) async {
    final repo = FeedbackFixture();
    await tester.pumpWidget(
      MaterialApp(home: FeedbackScreen(repository: repo)),
    );
    await tester.pumpAndSettle();
    repo.fail = true;
    await tester.tap(find.byTooltip('피드백 새로고침'));
    await tester.pumpAndSettle();
    expect(find.text('Pilot ON'), findsNothing);
    expect(find.textContaining('불러오지 못했습니다'), findsOneWidget);
    repo.fail = false;
    await tester.tap(find.text('다시 시도'));
    await tester.pumpAndSettle();
    expect(find.text('Pilot ON'), findsOneWidget);
  });

  testWidgets(
    'panic confirmation shows loss and stop context and records only one presentation',
    (tester) async {
      var presented = 0;
      Map<String, dynamic>? answer;
      final check = OrderCheck(
        id: 'p',
        allowed: true,
        messages: const ['10분 -3%'],
        expiresAt: DateTime.now().add(const Duration(minutes: 1)),
        analysis: const {
          'behavior': {
            'enabled': true,
            'score': 30,
            'requires_ack': true,
            'items': [
              {
                'code': 'panic',
                'status': 'hit',
                'title': '공포매도',
                'points': 30,
                'message': '10분 -3.00%',
              },
            ],
          },
          'context': {
            'position_return_percent': '-3.00',
            'stop_loss_won': 95000,
            'plan_message': '손절 조건 미충족',
          },
        },
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (context) => Scaffold(
              body: TextButton(
                onPressed: () async {
                  answer = await showDialog<Map<String, dynamic>>(
                    context: context,
                    builder: (_) => RiskConfirmation(
                      check: check,
                      onPresented: () => presented++,
                    ),
                  );
                },
                child: const Text('열기'),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('열기'));
      await tester.pumpAndSettle();
      expect(presented, 1);
      expect(find.text('잠깐, 계획된 매도인가요?'), findsOneWidget);
      expect(find.text('보유 평가수익률 -3.00%'), findsOneWidget);
      expect(find.text('저장된 손절가 95000원'), findsOneWidget);
      await tester.enterText(
        find.byKey(const ValueKey('trade-reason')),
        '조건 확인',
      );
      await tester.pump();
      expect(presented, 1);
      await tester.tap(find.text('주문 보류'));
      await tester.pumpAndSettle();
      expect(answer, {'deferred': true, 'reason': '조건 확인'});
      await tester.tap(find.text('열기'));
      await tester.pumpAndSettle();
      await tester.tapAt(const Offset(5, 5));
      await tester.pumpAndSettle();
      expect(
        answer,
        isNull,
      ); // Dismissing the dialog is not an explicit defer choice.
    },
  );
}
