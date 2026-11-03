import 'dart:convert';
import 'package:tradepilot_client/features/trading/presentation/journal_screen.dart';
import 'package:tradepilot_client/features/trading/presentation/risk_confirmation.dart';
import 'dart:ui' as ui;
import 'package:flutter/rendering.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:tradepilot_client/app/tradepilot_app.dart';
import 'package:tradepilot_client/core/network/api_client.dart';
import 'package:tradepilot_client/features/trading/data/remote_trading_repository.dart';
import 'package:tradepilot_client/features/trading/domain/models.dart';
import '../test/api_client_test.dart' show MemoryTokens;

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('iOS real FastAPI account, candles, plans and paper fill', (
    tester,
  ) async {
    final captures = <String, String>{};
    final boundaryKey = GlobalKey();
    Future<void> capture(String name) async {
      await tester.pumpAndSettle();
      final boundary =
          boundaryKey.currentContext!.findRenderObject()!
              as RenderRepaintBoundary;
      final image = await boundary.toImage(pixelRatio: 2);
      final data = await image.toByteData(format: ui.ImageByteFormat.png);
      captures[name] = base64Encode(data!.buffer.asUint8List());
      image.dispose();
    }

    // Loopback test server has a disposable DB; production config still requires HTTPS.
    final api = ApiClient(Uri.parse('http://127.0.0.1:18080'), MemoryTokens());
    await api.login('integration@example.test', 'integration-only-password');
    final repo = RemoteTradingRepository(api);
    await repo.snapshot();
    final latencyMs = <int>[];
    final updates = repo.quotes.listen((quote) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        latencyMs.add(
          DateTime.now().toUtc().difference(quote.asOf).inMilliseconds,
        );
      });
    });
    final original = await api.request('GET', '/v1/account');
    final checkDraft = OrderDraft(
      symbol: '005930',
      side: OrderSide.buy,
      quantity: 2,
      limitPriceWon: 72800,
      pilotEnabled: true,
    );
    final check = await repo.check(checkDraft);
    expect(check.allowed, isTrue);
    final key = 'ios-${DateTime.now().microsecondsSinceEpoch}';
    final receipt = await repo.submit(checkDraft, check, key);
    expect(receipt.status, 'accepted');
    List<OrderReceipt> orders = [];
    for (var i = 0; i < 10; i++) {
      await Future<void>.delayed(const Duration(seconds: 1));
      orders = await repo.orders();
      if (orders.any((o) => o.id == receipt.id && o.status == 'filled')) break;
    }
    expect(
      orders.any((o) => o.id == receipt.id && o.status == 'filled'),
      isTrue,
    );
    final replay = await repo.submit(checkDraft, check, key);
    expect(replay.id, receipt.id);
    expect(replay.status, 'filled');
    final account = await api.request('GET', '/v1/account');
    expect(
      int.parse(account['cash_won'] as String),
      lessThan(int.parse(original['cash_won'] as String)),
    );
    expect(account['reserved_won'], '0');
    final candles = await api.request(
      'GET',
      '/v1/market/005930/candles?interval=5m',
    );
    expect((candles['items'] as List).length, 120);
    await tester.pumpWidget(
      RepaintBoundary(
        key: boundaryKey,
        child: TradePilotApp(repositoryFactory: () => repo),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('action:Tab / 차트')));
    await tester.pumpAndSettle();
    // Allow network candle request to return on device.
    await Future<void>.delayed(const Duration(seconds: 1));
    await tester.pumpAndSettle();
    expect(find.textContaining('테스트 생성 데이터'), findsOneWidget);
    await capture('server-chart');
    final appTheme = Theme.of(tester.element(find.byType(Scaffold).first));
    expect(tester.takeException(), isNull);
    await tester.tap(find.byKey(const ValueKey('action:Tab / 자동매매')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('기존 모의계좌 · 전략'));
    await tester.pumpAndSettle();
    expect(find.text('나의 모의투자'), findsOneWidget);
    await capture('server-dashboard');
    await tester.tap(find.byKey(const ValueKey('action:Tab / 매매일지')));
    await tester.pumpAndSettle();
    expect(find.text('당시 AI 예측과 실제 가격 변화'), findsOneWidget);
    await capture('server-journal-summary');
    await tester.tap(find.byKey(const ValueKey('action:Tab / 전체 메뉴')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('action:Paper account')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('계좌 · 거래 설정 · 관심종목 관리'));
    await tester.pumpAndSettle();
    await Future<void>.delayed(const Duration(seconds: 1));
    await tester.pumpAndSettle();
    expect(find.text('주문 가능 금액'), findsOneWidget);
    await capture('server-account');
    await tester.tap(find.text('거래 설정'));
    await tester.pumpAndSettle();
    await capture('server-settings');
    await tester.enterText(
      find.widgetWithText(TextFormField, '1회 주문한도 (원)'),
      '900000',
    );
    FocusManager.instance.primaryFocus?.unfocus();
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('거래 설정 저장'),
      150,
      scrollable: find
          .descendant(
            of: find.byType(ListView).hitTestable(),
            matching: find.byType(Scrollable),
          )
          .first,
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('거래 설정 저장'));
    await Future<void>.delayed(const Duration(seconds: 1));
    await tester.pumpAndSettle();
    expect(
      (await api.request('GET', '/v1/settings'))['order_limit_won'],
      900000,
    );
    await tester.tap(find.text('주문·체결'));
    await tester.pumpAndSettle();
    await capture('server-fills');
    final journal = await api.request('GET', '/v1/journal');
    expect(journal['summary']['filled_orders'], 1);
    expect(journal['items'][0]['prediction']['status'], 'unavailable');
    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(
      RepaintBoundary(
        key: boundaryKey,
        child: MaterialApp(
          theme: appTheme,
          debugShowCheckedModeBanner: false,
          home: JournalScreen(repository: repo),
        ),
      ),
    );
    await Future<void>.delayed(const Duration(seconds: 1));
    await tester.pumpAndSettle();
    expect(find.textContaining('AI 방향 일치율 평가 기록 없음'), findsOneWidget);
    await tester.tap(find.byType(ExpansionTile).first);
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('복기 메모 작성·수정'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('복기 메모 작성·수정'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '시연 복기: 계획과 실제 결과 확인');
    await tester.tap(find.text('저장'));
    await Future<void>.delayed(const Duration(milliseconds: 300));
    await tester.pumpAndSettle();
    expect(
      (await api.request('GET', '/v1/journal'))['items'][0]['review_note'],
      '시연 복기: 계획과 실제 결과 확인',
    );
    await capture('server-journal');
    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(
      RepaintBoundary(
        key: boundaryKey,
        child: MaterialApp(
          theme: appTheme,
          debugShowCheckedModeBanner: false,
          home: Scaffold(
            body: RiskConfirmation(check: check, draft: checkDraft),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('trade-reason')), findsOneWidget);
    await capture('server-confirmation');
    await updates.cancel();
    final samples = latencyMs.where((v) => v >= 0).toList();
    expect(samples.length, greaterThanOrEqualTo(2));
    final mean = samples.reduce((a, b) => a + b) / samples.length;
    expect(mean, lessThan(2000));
    binding.reportData = {
      'captures': captures,
      'latency': {
        'samples': samples.length,
        'mean_ms': mean,
        'max_ms': samples.reduce((a, b) => a > b ? a : b),
        'scope':
            'Local synthetic quote timestamp to next Flutter frame; not live exchange latency',
      },
    };
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    api.close();
  });
}
