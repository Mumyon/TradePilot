import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot_client/features/trading/domain/models.dart';
import 'package:tradepilot_client/features/trading/domain/pending_order_store.dart';
import 'package:tradepilot_client/features/trading/domain/workspace_repository.dart';
import 'package:tradepilot_client/features/trading/presentation/risk_confirmation.dart';
import 'package:tradepilot_client/features/trading/presentation/journal_screen.dart';

OrderCheck check() => OrderCheck(
  id: 'check',
  allowed: true,
  messages: const ['위험 근거'],
  expiresAt: DateTime.now().toUtc().add(const Duration(minutes: 1)),
  analysis: const {
    'behavior': {'requires_ack': true, 'requires_high_ack': true},
  },
);

class EmptyJournal implements WorkspaceRepository {
  @override
  Future<Map<String, dynamic>> workspaceRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async => {
    'summary': {
      'filled_orders': 0,
      'realized_pnl_won': '0',
      'pnl_complete': true,
      'plan_evaluated': 0,
      'plan_adherent': 0,
      'plan_unregistered': 0,
      'plan_unavailable': 0,
      'prediction_evaluated': 0,
      'prediction_abstained': 0,
      'prediction_pending': 0,
    },
    'items': [],
    'feedback': ['평가 대기'],
    'notes': [],
  };
}

void main() {
  test(
    'uncertain submission recovery preserves exact confirmations and plan',
    () {
      final original = PendingOrder(
        const OrderDraft(
          symbol: '005930',
          side: OrderSide.buy,
          quantity: 1,
          limitPriceWon: 70000,
          pilotEnabled: true,
          planId: 'plan',
        ),
        check().acknowledge('저장한 분할 계획', true),
        'same-key',
      );
      final restored = PendingOrder.fromJson(
        jsonDecode(jsonEncode(original.toJson())) as Map<String, dynamic>,
      );
      expect(restored.toJson(), original.toJson());
    },
  );
  testWidgets('high warning requires reason and both acknowledgments', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: RiskConfirmation(check: check())),
      ),
    );
    FilledButton button() => tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, '확인 후 주문 진행'),
    );
    expect(button().onPressed, isNull);
    await tester.enterText(
      find.byKey(const ValueKey('trade-reason')),
      '계획대로 매수',
    );
    await tester.tap(find.byKey(const ValueKey('warning-ack')));
    await tester.pump();
    expect(button().onPressed, isNull);
    await tester.ensureVisible(find.byKey(const ValueKey('high-risk-ack')));
    await tester.tap(find.byKey(const ValueKey('high-risk-ack')));
    await tester.pump();
    expect(button().onPressed, isNotNull);
    await tester.enterText(find.byKey(const ValueKey('trade-reason')), '  ');
    await tester.pump();
    expect(button().onPressed, isNull);
  });
  testWidgets('empty journal does not invent compliance or AI accuracy', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(home: JournalScreen(repository: EmptyJournal())),
    );
    await tester.pumpAndSettle();
    expect(find.text('계획 준수율 평가 기록 없음'), findsOneWidget);
    expect(find.textContaining('AI 방향 일치율 평가 기록 없음'), findsOneWidget);
    expect(find.textContaining('100.0%'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
