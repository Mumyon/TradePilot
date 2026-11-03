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
  testWidgets(
    'native order warning is displayed, explicitly deferred and reflected in feedback',
    (tester) async {
      final api = ApiClient(
        Uri.parse('http://127.0.0.1:18080'),
        MemoryTokens(),
      );
      final email =
          'feedback-${DateTime.now().microsecondsSinceEpoch}@example.test';
      await api.request(
        'POST',
        '/v1/auth/signup',
        authenticated: false,
        body: {
          'email': email,
          'password': 'feedback-test-password',
          'password_confirmation': 'feedback-test-password',
        },
      );
      await api.login(email, 'feedback-test-password');
      final repo = RemoteTradingRepository(api);
      final key = GlobalKey();
      final captures = <String, String>{};
      Future<void> capture(String name) async {
        await tester.pumpAndSettle();
        final image =
            await (key.currentContext!.findRenderObject()!
                    as RenderRepaintBoundary)
                .toImage(pixelRatio: 2);
        final data = await image.toByteData(format: ui.ImageByteFormat.png);
        captures[name] = base64Encode(data!.buffer.asUint8List());
        image.dispose();
      }

      await tester.pumpWidget(
        RepaintBoundary(
          key: key,
          child: TradePilotApp(repositoryFactory: () => repo),
        ),
      );
      await tester.pumpAndSettle();
      await Future<void>.delayed(const Duration(seconds: 1));
      await tester.pumpAndSettle();
      await tester.tap(
        find.byKey(const ValueKey('action:Live stock / 005930')),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('action:매수')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('action:매수 주문 확인')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('action:모의 매수 접수하기')));
      await tester.pumpAndSettle();
      await Future<void>.delayed(const Duration(milliseconds: 300));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('warning-ack')), findsOneWidget);
      expect(find.text('행동 점수 30/100'), findsOneWidget);
      await capture('warning');
      const reason = '급등 이전 계획 가격을 확인하려고 보류';
      await tester.enterText(
        find.byKey(const ValueKey('trade-reason')),
        reason,
      );
      FocusManager.instance.primaryFocus?.unfocus();
      await tester.pumpAndSettle();
      await tester.tap(find.text('주문 보류'));
      await tester.pumpAndSettle();
      await Future<void>.delayed(const Duration(milliseconds: 300));
      final report = await api.request('GET', '/v1/feedback');
      expect(report['total_checks'], 1);
      expect(report['items'][0]['outcome'], 'dismissed');
      expect(report['items'][0]['decision_reason'], reason);
      expect(report['items'][0]['presented_at'], isNotNull);
      expect(report['warning_types'][0]['defer_rate'], 1.0);
      expect((await api.request('GET', '/v1/orders'))['items'], isEmpty);
      await tester.tap(find.byKey(const ValueKey('action:Tab / 매매일지')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('action:segment:1')));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('피드백 효과 기록 · ON/OFF 비교'),
        150,
        scrollable: find.byType(Scrollable).last,
      );
      await tester.tap(find.text('피드백 효과 기록 · ON/OFF 비교'));
      await tester.pumpAndSettle();
      expect(find.text('Pilot ON'), findsOneWidget);
      await capture('comparison');
      await tester.scrollUntilVisible(
        find.textContaining('급등 추격 매수 ·'),
        150,
        scrollable: find.byType(Scrollable).last,
      );
      await tester.tap(find.textContaining('급등 추격 매수 ·'));
      await tester.pumpAndSettle();
      expect(find.text('명시적 보류: 1건'), findsOneWidget);
      await capture('responses');
      final record = find.textContaining('005930 · Pilot ON ·');
      await tester.scrollUntilVisible(
        record,
        150,
        scrollable: find.byType(Scrollable).last,
      );
      await tester.ensureVisible(record);
      await tester.tap(record);
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('보류 이유: $reason'),
        100,
        scrollable: find.byType(Scrollable).last,
      );
      expect(find.text('보류 이유: $reason'), findsOneWidget);
      await capture('deferral-reason');
      final exported = await api.request('GET', '/v1/feedback/export');
      expect(exported['rows'], 1);
      expect(exported['csv'], contains('dismissed'));
      expect(exported['csv'], isNot(contains(reason)));
      expect(exported['csv'], contains('defer_reason_recorded'));
      expect(tester.takeException(), isNull);
      binding.reportData = {'captures': captures, 'summary': report};
      await tester.pumpWidget(const SizedBox());
      await repo.dispose();
    },
  );
}
