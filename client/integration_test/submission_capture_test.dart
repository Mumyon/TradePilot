import 'dart:convert';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:tradepilot_client/app/tradepilot_app.dart';
import 'package:tradepilot_client/core/network/api_client.dart';
import 'package:tradepilot_client/features/trading/data/remote_trading_repository.dart';
import 'package:tradepilot_client/features/trading/domain/models.dart';
import 'package:tradepilot_client/features/trading/presentation/risk_confirmation.dart';
import '../test/api_client_test.dart' show MemoryTokens;

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'submission screenshots from real API and controlled synthetic warning',
    (tester) async {
      final api = ApiClient(
        Uri.parse('http://127.0.0.1:18080'),
        MemoryTokens(),
      );
      await api.login('integration@example.test', 'integration-only-password');
      final repo = RemoteTradingRepository(api);
      final key = GlobalKey();
      final captures = <String, String>{};
      Future<void> capture(String name) async {
        await tester.pumpAndSettle();
        final img =
            await (key.currentContext!.findRenderObject()!
                    as RenderRepaintBoundary)
                .toImage(pixelRatio: 2);
        final data = await img.toByteData(format: ui.ImageByteFormat.png);
        captures[name] = base64Encode(data!.buffer.asUint8List());
        img.dispose();
      }

      await tester.pumpWidget(
        RepaintBoundary(
          key: key,
          child: TradePilotApp(repositoryFactory: () => repo),
        ),
      );
      await tester.pumpAndSettle();
      await capture('02-watchlist');
      final theme = Theme.of(tester.element(find.byType(Scaffold).first));
      const draft = OrderDraft(
        symbol: '005930',
        side: OrderSide.buy,
        quantity: 2,
        limitPriceWon: 72800,
        pilotEnabled: true,
      );
      final check = await repo.check(draft);
      expect(check.requiresAck, isTrue);
      expect(check.behavior['score'], 30);
      await tester.pumpWidget(const SizedBox());
      await tester.pumpWidget(
        RepaintBoundary(
          key: key,
          child: MaterialApp(
            theme: theme,
            debugShowCheckedModeBanner: false,
            home: Scaffold(
              body: RiskConfirmation(check: check, draft: draft),
            ),
          ),
        ),
      );
      await capture('04-behavior-warning');
      binding.reportData = {'captures': captures};
      await tester.pumpWidget(const SizedBox());
      api.close();
    },
  );
}
