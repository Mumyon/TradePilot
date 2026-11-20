import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot_client/features/trading/data/demo_trading_repository.dart';
import 'package:tradepilot_client/features/trading/domain/trading_models.dart';
import 'package:tradepilot_client/features/trading/domain/workspace_repository.dart';
import 'package:tradepilot_client/features/trading/presentation/trading_controller.dart';
import 'package:tradepilot_client/features/trading/presentation/order_confirmation_panel.dart';

class FeedbackRepo implements WorkspaceRepository {
  FeedbackRepo({this.status = 'available'});
  final String status;
  int posts = 0;
  @override
  Future<Map<String, dynamic>> workspaceRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    if (path.endsWith('/presented')) return {};
    if (method == 'POST') {
      posts++;
      expect(body?['consent'], true);
    }
    return {
      'status': status,
      'facts': [
        {'fact_id': 'order', 'text': '주문 사실'},
      ],
      'result': {'kind': 'quant_web', 'body': '## 관망\n반등 확인이 필요합니다.'},
    };
  }
}

TradingController controller({bool allowed = true, bool expired = false}) {
  final c = TradingController(DemoTradingRepository());
  c.selectedSymbol = '005930';
  c.market['005930'] = Quote(
    symbol: '005930',
    name: '삼성전자',
    priceWon: 100,
    asOf: DateTime.now().toUtc(),
    sequence: 1,
  );
  c.draft = const OrderDraft(
    symbol: '005930',
    side: OrderSide.buy,
    quantity: 1,
    limitPriceWon: 100,
    pilotEnabled: true,
  );
  c.check = OrderCheck(
    id: 'check',
    allowed: allowed,
    messages: ['주문 불가 근거'],
    expiresAt: DateTime.now().toUtc().add(Duration(seconds: expired ? -1 : 60)),
  );
  c.stage = allowed ? OrderStage.ready : OrderStage.blocked;
  return c;
}

void main() {
  testWidgets(
    'quant analysis always starts automatically without legacy risk controls',
    (tester) async {
      final c = controller();
      addTearDown(c.dispose);
      final repo = FeedbackRepo();
      int submitted = 0;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: OrderConfirmationPanel(
              controller: c,
              repository: repo,
              onSubmit: () => submitted++,
              onRecheck: () {},
              onBack: () {},
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(repo.posts, 1);
      expect(find.text('주문을 확인해 주세요'), findsOneWidget);
      expect(find.byType(CheckboxListTile), findsNothing);
      expect(repo.posts, 1);
      expect(find.textContaining('관망', findRichText: true), findsWidgets);
      expect(find.text('행동점수'), findsNothing);
      expect(find.byType(DropdownButtonFormField<String>), findsNothing);
      expect(find.text('투자 예정 기간'), findsNothing);
      expect(find.text('투자 성향'), findsNothing);
      expect(find.text('과매매'), findsNothing);
      expect(find.text('계획 위반'), findsNothing);
      final button = find.text('모의 매수 접수하기');
      await tester.scrollUntilVisible(
        button,
        250,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(button);
      expect(submitted, 1);
      expect(find.byType(AlertDialog), findsNothing);
    },
  );
  for (final mode in ['blocked', 'expired', 'ai-failed']) {
    testWidgets('$mode check cannot submit', (tester) async {
      final c = controller(
        allowed: mode != 'blocked',
        expired: mode == 'expired',
      );
      addTearDown(c.dispose);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: OrderConfirmationPanel(
              controller: c,
              repository: FeedbackRepo(
                status: mode == 'ai-failed' ? 'failed' : 'available',
              ),
              onSubmit: () => fail('Invalid submit'),
              onRecheck: () {},
              onBack: () {},
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.byType(FilledButton),
        250,
        scrollable: find.byType(Scrollable).first,
      );
      expect(
        tester.widget<FilledButton>(find.byType(FilledButton)).onPressed,
        isNull,
      );
      expect(find.byType(AlertDialog), findsNothing);
    });
  }
}
