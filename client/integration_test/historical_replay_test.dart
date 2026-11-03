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
    'native historical replay: archived 5m, next-open fill, paired export',
    (tester) async {
      final api = ApiClient(
        Uri.parse('http://127.0.0.1:18080'),
        MemoryTokens(),
      );
      final email =
          'replay-${DateTime.now().microsecondsSinceEpoch}@example.test';
      await api.request(
        'POST',
        '/v1/auth/signup',
        authenticated: false,
        body: {
          'email': email,
          'password': 'replay-test-password',
          'password_confirmation': 'replay-test-password',
        },
      );
      await api.login(email, 'replay-test-password');
      final repo = RemoteTradingRepository(api), boundary = GlobalKey();
      final captures = <String, String>{};
      Future<void> capture(String name) async {
        await tester.pumpAndSettle();
        final image =
            await (boundary.currentContext!.findRenderObject()!
                    as RenderRepaintBoundary)
                .toImage(pixelRatio: 2);
        final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
        captures[name] = base64Encode(bytes!.buffer.asUint8List());
        image.dispose();
      }

      Future<void> tap(Finder finder) async {
        if (find.byType(AlertDialog).evaluate().isEmpty) {
          await tester.scrollUntilVisible(
            finder,
            160,
            scrollable: find.byType(Scrollable).last,
          );
        }
        await tester.ensureVisible(finder);
        await tester.pumpAndSettle();
        await tester.tap(finder);
        await tester.pumpAndSettle();
        await Future<void>.delayed(const Duration(milliseconds: 250));
        await tester.pumpAndSettle();
      }

      await tester.pumpWidget(
        RepaintBoundary(
          key: boundary,
          child: TradePilotApp(repositoryFactory: () => repo),
        ),
      );
      await tester.pumpAndSettle();
      await Future<void>.delayed(const Duration(seconds: 1));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('action:Tab / 자동매매')));
      await tester.pumpAndSettle();
      expect(find.text('모의투자 · 과거 장세 실험'), findsOneWidget);
      final hub = await api.request('GET', '/v1/replay');
      expect((hub['cases'] as List).length, 4);
      expect(find.text('합성 데이터 · 논문의 실제 시장 사례로 사용 불가'), findsNothing);
      final c = (hub['cases'] as List).firstWhere(
        (c) => c['catalog_id'] == 'yahoo-005930-2026-10-13-v1',
      );
      expect(c['model']['quality_gate_passed'], true);
      expect(c.containsKey('daily_cross_check'), false);
      await tester.scrollUntilVisible(
        find.text(c['name']),
        160,
        scrollable: find.byType(Scrollable).last,
      );
      await tester.drag(find.byType(ListView).last, const Offset(0, 70));
      await tester.pumpAndSettle();
      await capture('catalog');
      await tap(find.byKey(ValueKey('replay-start-${c['id']}')));
      await tester.tap(find.text('사전 계획 등록'));
      await tester.pumpAndSettle();
      await tap(find.byKey(const ValueKey('replay-start-confirm')));
      await tester.drag(find.byType(ListView).last, const Offset(0, 2000));
      await tester.pumpAndSettle();
      await capture('session');
      final first = (await api.request('GET', '/v1/replay'))['runs'][0];
      var run = await api.request('GET', '/v1/replay/runs/${first['id']}');
      expect(run['data_kind'], 'historical');
      expect(run['interval'], '5m');
      expect(run['visible_bars'], c['preview']);
      expect(run['prediction']['status'], 'unavailable');
      // A permissive limit tests next observed open execution without assuming today's close.
      await tester.scrollUntilVisible(
        find.byKey(const ValueKey('replay-price')),
        160,
        scrollable: find.byType(Scrollable).last,
      );
      await tester.enterText(
        find.byKey(const ValueKey('replay-price')),
        '500000',
      );
      FocusManager.instance.primaryFocus?.unfocus();
      await tester.pumpAndSettle();
      await tap(find.byKey(const ValueKey('replay-order')));
      await tap(find.text('확인 후 주문 진행'));
      await tester.drag(find.byType(ListView).last, const Offset(0, 3000));
      await tester.pumpAndSettle();
      await tap(find.byKey(const ValueKey('replay-next')));
      run = await api.request('GET', '/v1/replay/runs/${first['id']}');
      expect(run['orders'][0]['status'], 'filled');
      expect(
        run['orders'][0]['fill_price'],
        (run['visible_bars'] as List).last['open_won'],
      );
      expect(run['quantity'], 1);
      await tap(find.byKey(const ValueKey('replay-finish')));
      await tap(find.text('연구 CSV 복사'));
      ScaffoldMessenger.of(
        tester.element(find.text('모의투자 모드')),
      ).hideCurrentSnackBar();
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('연구 관찰 결과'));
      await tester.pumpAndSettle();
      await capture('results');
      final exported = await api.request(
        'GET',
        '/v1/replay/runs/${first['id']}/export',
      );
      expect(exported['evidence']['case']['data_kind'], 'historical');
      expect(exported['evidence']['case']['coverage']['available_bars'], 72);
      expect(exported['evidence']['summary']['filled_orders'], 1);
      await tap(find.text('같은 조건 · 반대 Pilot'));
      await tap(find.byKey(const ValueKey('replay-start-confirm')));
      final paired = (await api.request('GET', '/v1/replay'))['runs'][0];
      expect(paired['pilot_enabled'], false);
      expect(paired['pair_id'], first['pair_id']);
      expect(paired['comparison_key'], first['comparison_key']);
      expect(tester.takeException(), isNull);
      binding.reportData = {
        'captures': captures,
        'summary': {
          'case': c,
          'run': run,
          'paired': paired,
          'evidence': exported['evidence'],
          'purpose': 'software verification, not participant research',
        },
      };
      await tester.pumpWidget(const SizedBox());
      await repo.dispose();
    },
  );
}
