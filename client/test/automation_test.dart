import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot_client/features/trading/domain/workspace_repository.dart';
import 'package:tradepilot_client/features/trading/presentation/automation_screen.dart';

class AutoFixture implements WorkspaceRepository {
  bool? enabled;
  int? budget;
  @override
  Future<Map<String, dynamic>> workspaceRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    const strategy = {
      'id': 's',
      'name': '검증 전략',
      'symbol': '005930',
      'fast_period': 5,
      'slow_period': 20,
    };
    if (path == '/v1/strategies') {
      return {
        'items': [strategy],
      };
    }
    if (method == 'PUT') {
      enabled = body!['enabled'] as bool;
      budget = body['budget_won'] as int?;
      return {};
    }
    if (path == '/v1/automations') {
      return {
        'items': [
          if (enabled != null)
            {
              'id': 'run',
              'strategy_id': 's',
              'symbol': '005930',
              'strategy_snapshot': strategy,
              'budget_won': 500000,
              'enabled': enabled,
              'message': '테스트 상태',
              'last_bar': null,
            },
        ],
      };
    }
    if (path.contains('/events')) {
      return {
        'items': [
          {
            'signal': 'buy',
            'order_status': 'cancelled',
            'bar_at': '2026-10-18',
            'message': '중지되어 취소',
          },
        ],
        'next_offset': null,
      };
    }
    throw StateError(path);
  }
}

void main() {
  testWidgets(
    'start requires explicit confirmation then stop and view events',
    (tester) async {
      final repo = AutoFixture();
      await tester.pumpWidget(
        MaterialApp(home: AutomationScreen(repository: repo)),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byType(DropdownButtonFormField<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('검증 전략 · 005930').last);
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('선택 전략 시작 / 재개'),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.text('선택 전략 시작 / 재개'));
      await tester.pumpAndSettle();
      expect(repo.enabled, isNull);
      await tester.tap(find.text('취소'));
      await tester.pumpAndSettle();
      expect(repo.enabled, isNull);
      await tester.tap(find.text('선택 전략 시작 / 재개'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('모의 실행 시작'));
      await tester.pumpAndSettle();
      expect(repo.enabled, isTrue);
      expect(repo.budget, 500000);
      await tester.scrollUntilVisible(
        find.text('중지 · 미체결 취소'),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.text('중지 · 미체결 취소'));
      await tester.pumpAndSettle();
      expect(repo.enabled, isFalse);
      await tester.tap(find.text('신호·주문 이력'));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('매수 · 취소'),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.text('매수 · 취소'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
