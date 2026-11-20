import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot_client/features/trading/domain/workspace_repository.dart';
import 'package:tradepilot_client/features/trading/presentation/chatgpt_analysis_panel.dart';

class ReviewFixture implements WorkspaceRepository {
  ReviewFixture({
    this.status = 'ready',
    this.fail = false,
    this.journal = false,
  });
  final bool journal;
  String status;
  bool fail;
  int posts = 0;
  @override
  Future<Map<String, dynamic>> workspaceRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    expect(
      path,
      journal
          ? '/v1/orders/check/check1/ai-feedback'
          : '/v1/replay/runs/run1/ai-review',
    );
    if (fail) throw StateError('offline');
    if (method == 'POST') {
      expect(body?['consent'], true);
      if (journal) {
        expect(body, {'consent': true});
      }
      posts++;
      status = 'available';
    }
    return {
      'status': status,
      if (journal) ...{
        'analysis_as_of': '2026-11-13T04:29:00Z',
        'quote_context': {
          'current_price': 100000,
          'quote_as_of': '2026-11-13T04:28:59Z',
        },
        'search': {
          'sources': [
            {'url': 'https://example.test/report', 'title': '공시 원문'},
          ],
        },
      },
      'message': status == 'unavailable'
          ? 'ON/OFF 두 실험을 모두 종료한 뒤 AI 복기를 열 수 있습니다.'
          : null,
      'requested_model': 'test-model',
      'facts': [
        {'fact_id': 'plan', 'text': '계획 평가 가능한 체결 0건.'},
      ],
      'result': status == 'available'
          ? journal
                ? {
                    'kind': 'quant_web',
                    'body': '''
## 데이터 부족

일봉 확보 필요 [출처](https://example.test/report)

| 항목 | 확인값 | 해석 |
| --- | --- | --- |
| 일봉 | 미확보 | 추세 판단 보류 |

**확인 자료 URL:** `https://example.test/report`
''',
                  }
                : {
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
          child: ChatGPTAnalysisPanel(repository: fixture, runId: 'run1'),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
    'pretrade auto feedback uses the check route without another dialog',
    (tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final fixture = ReviewFixture(journal: true);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: ChatGPTAnalysisPanel.pretrade(
                repository: fixture,
                checkId: 'check1',
                autoGenerate: true,
                currentPrice: 100500,
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(fixture.posts, 1);
      expect(find.text('ChatGPT'), findsOneWidget);
      expect(find.text('분석 기준 · 11-13 13:29:00 (KST)'), findsOneWidget);
      expect(
        find.text('AI가 본 시세 · 100,000원 (11-13 13:28:59 KST)'),
        findsOneWidget,
      );
      expect(find.text('현재 표시가 − AI 기준가 · +500원'), findsOneWidget);
      expect(find.byType(AlertDialog), findsNothing);
      expect(find.textContaining('데이터 부족', findRichText: true), findsWidgets);
      expect(find.byType(Table), findsNothing);
      await tester.tap(find.text('AI 상세 분석 보기'));
      await tester.pumpAndSettle();
      expect(find.textContaining('일봉 확보 필요', findRichText: true), findsWidgets);
      expect(find.textContaining('계획 평가'), findsNothing);
      expect(find.byType(Table), findsOneWidget);
      expect(find.textContaining('추세 판단 보류', findRichText: true), findsWidgets);
      expect(find.textContaining('https://', findRichText: true), findsNothing);
      expect(find.text('공시 원문'), findsNothing);
      final sources = find.text('출처 더보기');
      await tester.ensureVisible(sources);
      await tester.tap(sources);
      await tester.pumpAndSettle();
      expect(find.text('공시 원문'), findsOneWidget);
      await tester.tap(sources);
      await tester.pumpAndSettle();
      expect(find.text('공시 원문'), findsNothing);
    },
  );
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
    expect(find.text('AI 연결을 확인한 뒤 다시 분석해 주세요.'), findsOneWidget);
    expect(find.textContaining('AI 해설 ·'), findsNothing);
  });
}
