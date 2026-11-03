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
  testWidgets('iOS opts into paper automation, receives a signal and stops', (
    tester,
  ) async {
    final api = ApiClient(Uri.parse('http://127.0.0.1:18080'), MemoryTokens());
    final email = 'auto-${DateTime.now().microsecondsSinceEpoch}@example.test';
    await api.request(
      'POST',
      '/v1/auth/signup',
      authenticated: false,
      body: {
        'email': email,
        'password': 'automation-test-password',
        'password_confirmation': 'automation-test-password',
      },
    );
    await api.login(email, 'automation-test-password');
    await api.request(
      'POST',
      '/v1/strategies',
      body: {
        'name': 'iOS 자동 검증',
        'symbol': '005930',
        'fast_period': 2,
        'slow_period': 3,
      },
    );
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
    await tester.tap(find.text('모의 자동매매 관리'));
    await tester.pumpAndSettle();
    await tester.tap(find.byType(DropdownButtonFormField<String>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('iOS 자동 검증 · 005930').last);
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('선택 전략 시작 / 재개'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('선택 전략 시작 / 재개'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('모의 실행 시작'));
    await tester.pumpAndSettle();
    String? runId;
    for (var i = 0; i < 10; i++) {
      final runs = await api.request('GET', '/v1/automations');
      final run = (runs['items'] as List).single;
      runId = run['id'] as String;
      if (run['last_bar'] != null) break;
      await Future<void>.delayed(const Duration(seconds: 1));
    }
    final events = await api.request('GET', '/v1/automations/$runId/events');
    expect(events['items'] as List, isNotEmpty);
    await tester.scrollUntilVisible(
      find.text('중지 · 미체결 취소'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('중지 · 미체결 취소'));
    await tester.pumpAndSettle();
    final stopped = await api.request('GET', '/v1/automations');
    expect(stopped['items'][0]['enabled'], isFalse);
    await tester.tap(find.text('신호·주문 이력'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('선택 실행의 최근 신호 이력'),
      150,
      scrollable: find.byType(Scrollable).first,
    );
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
