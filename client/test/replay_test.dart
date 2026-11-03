import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot_client/features/trading/domain/workspace_repository.dart';
import 'package:tradepilot_client/features/trading/presentation/replay_screen.dart';

class ReplayFixture implements WorkspaceRepository {
  final actions = <Map<String, dynamic>>[];
  Map<String, dynamic>? startBody;
  bool failNext = true;
  int revision = 0;
  final caseData = <String, dynamic>{
    'id': 'case1',
    'name': '합성 연습',
    'data_kind': 'synthetic',
    'symbol': '005930',
    'provider': 'fixture',
    'replay_from': '2024-01-26T03:00:00Z',
    'model': null,
    'preview': [
      {'close_won': 70000},
    ],
  };
  Map<String, dynamic> run() => {
    'id': 'run1',
    'case_id': 'case1',
    'case_name': '합성 연습',
    'symbol': '005930',
    'revision': revision,
    'virtual_at': '2024-01-26T03:05:00Z',
    'pilot_enabled': true,
    'data_kind': 'synthetic',
    'step': revision,
    'total_steps': 20,
    'finished': false,
    'cash_won': 10000000,
    'available_cash_won': 10000000,
    'quantity': 0,
    'equity_won': 10000000,
    'plan': null,
    'prediction': {'status': 'unavailable', 'message': '모델 없음'},
    'visible_bars': [
      {'close_won': 70000},
      {'close_won': 71000},
    ],
    'orders': [],
  };
  @override
  Future<Map<String, dynamic>> workspaceRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    if (path.endsWith('/actions')) {
      actions.add(Map.from(body!));
      if (failNext) {
        failNext = false;
        throw StateError('응답 유실');
      }
      revision++;
      return {...run(), 'action_result': <String, dynamic>{}};
    }
    if (path.endsWith('/runs') && method == 'POST') {
      startBody = Map.from(body!);
      return {
        ...run(),
        'pilot_enabled': false,
        'allocation_method': 'server_randomized',
        'condition_order': ['OFF', 'ON'],
        'sequence': 1,
      };
    }
    if (path.endsWith('/runs/run1')) return run();
    return {
      'events': [],
      'cases': [caseData],
      'runs': [
        {
          'id': 'run1',
          'name': '합성 연습',
          'pilot_enabled': true,
          'finished': false,
          'pair_id': '12345678-abcd',
          'sequence': 1,
          'summary': null,
        },
      ],
    };
  }
}

void main() {
  testWidgets(
    'synthetic data and untrained model are explicit; resume loads private run',
    (tester) async {
      final repo = ReplayFixture();
      await tester.pumpWidget(
        MaterialApp(home: ReplayScreen(repository: repo)),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('replay-show-synthetic')));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('AI 미학습 · 먼저 학습/검증을 실행하세요.'),
        200,
      );
      expect(find.text('합성 데이터 · 논문의 실제 시장 사례로 사용 불가'), findsOneWidget);
      await tester.scrollUntilVisible(find.text('이어서 실험'), 200);
      await tester.tap(find.text('이어서 실험'));
      await tester.pumpAndSettle();
      // List retains its scroll offset after entering a run; explicitly return to top.
      await tester.drag(find.byType(ListView), const Offset(0, 1800));
      await tester.pumpAndSettle();
      expect(find.text('모의투자 모드'), findsOneWidget);
      expect(find.text('합성 연습 · 실제 역사적 가격 아님'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('start dialog hides the background loading animation', (
    tester,
  ) async {
    final repo = ReplayFixture();
    await tester.pumpWidget(MaterialApp(home: ReplayScreen(repository: repo)));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('replay-show-synthetic')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.byKey(const ValueKey('replay-start-case1')),
      200,
    );
    await tester.tap(find.byKey(const ValueKey('replay-start-case1')));
    await tester.pumpAndSettle();
    expect(find.text('실험 시작 조건'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsNothing);
    await tester.tap(find.text('닫기'));
    await tester.pumpAndSettle();
    expect(find.byType(AlertDialog), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('randomized condition order is requested and shown in the run', (
    tester,
  ) async {
    final repo = ReplayFixture();
    await tester.pumpWidget(MaterialApp(home: ReplayScreen(repository: repo)));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('replay-show-synthetic')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.byKey(const ValueKey('replay-start-case1')),
      200,
    );
    await tester.tap(find.byKey(const ValueKey('replay-start-case1')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(
      find.byKey(const ValueKey('replay-randomize-order')),
    );
    await tester.tap(find.byKey(const ValueKey('replay-randomize-order')));
    await tester.pumpAndSettle();
    expect(find.text('Pilot 행동 피드백'), findsNothing);
    await tester.ensureVisible(
      find.byKey(const ValueKey('replay-start-confirm')),
    );
    await tester.tap(find.byKey(const ValueKey('replay-start-confirm')));
    await tester.pumpAndSettle();
    expect(repo.startBody?['randomize_order'], isTrue);
    expect(repo.startBody?.containsKey('pilot_enabled'), isFalse);
    expect(
      find.textContaining('서버 무작위 배정 · 1번째 조건 / 2 · OFF → ON'),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('network recovery reuses the original action key and revision', (
    tester,
  ) async {
    final repo = ReplayFixture();
    await tester.pumpWidget(MaterialApp(home: ReplayScreen(repository: repo)));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('이어서 실험'), 250);
    await tester.tap(find.text('이어서 실험'));
    await tester.pumpAndSettle();
    await tester.drag(find.byType(ListView), const Offset(0, 1800));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.byKey(const ValueKey('replay-next')),
      150,
    );
    await tester.tap(find.byKey(const ValueKey('replay-next')));
    await tester.pumpAndSettle();
    expect(find.text('동일 요청 재시도'), findsOneWidget);
    await tester.tap(find.text('동일 요청 재시도'));
    await tester.pumpAndSettle();
    expect(repo.actions.length, 2);
    expect(repo.actions[0], repo.actions[1]);
    expect(tester.takeException(), isNull);
  });
}
