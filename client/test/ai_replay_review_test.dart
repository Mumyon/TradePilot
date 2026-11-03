import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot_client/features/trading/domain/workspace_repository.dart';
import 'package:tradepilot_client/features/trading/presentation/ai_replay_review.dart';

class ReviewFixture implements WorkspaceRepository {
  ReviewFixture({this.status = 'ready', this.fail = false});
  String status;
  bool fail;
  int posts = 0;
  @override
  Future<Map<String, dynamic>> workspaceRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    expect(path, '/v1/replay/runs/run1/ai-review');
    if (fail) throw StateError('offline');
    if (method == 'POST') {
      expect(body, {'consent': true});
      posts++;
      status = 'available';
    }
    return {
      'status': status,
      'message': status == 'unavailable'
          ? 'ON/OFF 두 실험을 모두 종료한 뒤 AI 복기를 열 수 있습니다.'
          : null,
      'requested_model': 'test-model',
      'facts': [
        {'fact_id': 'plan', 'text': '계획 평가 가능한 체결 0건.'},
      ],
      'result': status == 'available'
          ? {
              'observations': [
                {
                  'fact_id': 'plan',
                  'interpretation': '계획 평가에 필요한 기록을 확인해 보세요.',
                  'reflection_question': '진입 조건을 미리 정했나요?',
                },
              ],
              'limitation': '관찰만으로 효과를 확정할 수 없습니다.',
            }
          : null,
    };
  }
}

Future<void> show(WidgetTester tester, ReviewFixture fixture) async {
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: AIReplayReview(repository: fixture, runId: 'run1'),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
    'explicit consent gates generation and cached refresh makes no new request',
    (tester) async {
      final fixture = ReviewFixture();
      await show(tester, fixture);
      expect(fixture.posts, 0);
      await tester.tap(find.byKey(const ValueKey('ai-review-generate')));
      await tester.pumpAndSettle();
      expect(find.text('ChatGPT로 AI 복기 생성'), findsOneWidget);
      expect(fixture.posts, 0);
      await tester.tap(find.text('닫기'));
      await tester.pumpAndSettle();
      expect(fixture.posts, 0);
      await tester.tap(find.byKey(const ValueKey('ai-review-generate')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('동의하고 생성'));
      await tester.pumpAndSettle();
      expect(fixture.posts, 1);
      expect(find.text('서버 집계 · 계획 평가 가능한 체결 0건.'), findsOneWidget);
      expect(find.text('AI 해설 · 계획 평가에 필요한 기록을 확인해 보세요.'), findsOneWidget);
      await tester.ensureVisible(
        find.byKey(const ValueKey('ai-review-refresh')),
      );
      await tester.tap(find.byKey(const ValueKey('ai-review-refresh')));
      await tester.pumpAndSettle();
      expect(fixture.posts, 1);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('incomplete pair has no generate button', (tester) async {
    final fixture = ReviewFixture(status: 'unavailable');
    await show(tester, fixture);
    expect(find.text('ON/OFF 두 실험을 모두 종료한 뒤 AI 복기를 열 수 있습니다.'), findsOneWidget);
    expect(find.byKey(const ValueKey('ai-review-generate')), findsNothing);
    expect(fixture.posts, 0);
  });

  testWidgets('provider error is explicit and does not synthesize a review', (
    tester,
  ) async {
    await show(tester, ReviewFixture(fail: true));
    expect(
      find.text('AI 복기 연결을 확인해 주세요. 기존 행동 피드백은 계속 볼 수 있습니다.'),
      findsOneWidget,
    );
    expect(find.textContaining('AI 해설 ·'), findsNothing);
  });
}
