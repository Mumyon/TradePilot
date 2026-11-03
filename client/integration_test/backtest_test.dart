import 'dart:convert';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:tradepilot_client/app/tradepilot_app.dart';
import 'package:tradepilot_client/core/network/api_client.dart';
import 'package:tradepilot_client/features/trading/data/remote_trading_repository.dart';
import '../test/api_client_test.dart' show MemoryTokens;

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('iOS saves strategy and executes persisted server backtest', (
    tester,
  ) async {
    final api = ApiClient(Uri.parse('http://127.0.0.1:18080'), MemoryTokens());
    await api.login('integration@example.test', 'integration-only-password');
    final repo = RemoteTradingRepository(api);
    final key = GlobalKey();
    await tester.pumpWidget(
      RepaintBoundary(
        key: key,
        child: TradePilotApp(repositoryFactory: () => repo),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('action:Tab / 자동매매')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('기존 모의계좌 · 전략'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('action:segment:2')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('새 전략 저장'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('새 전략 저장'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('백테스트 실행'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('백테스트 실행'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('거래 내역'),
      150,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('합성 시연 데이터'), findsOneWidget);
    final results = await api.request('GET', '/v1/backtests');
    expect((results['items'] as List).length, 1);
    expect(results['items'][0]['bar_count'], greaterThan(20));
    final boundary =
        key.currentContext!.findRenderObject()! as RenderRepaintBoundary;
    final image = await boundary.toImage(pixelRatio: 2);
    final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
    binding.reportData = {
      'screenshot': base64Encode(bytes!.buffer.asUint8List()),
    };
    image.dispose();
    await tester.pumpWidget(const SizedBox());
    await repo.dispose();
  });
}
