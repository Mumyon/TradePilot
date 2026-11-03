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
    'native F-05 replay review: frozen forecast, behavior feedback and paired navigation',
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
      await tap(find.byKey(const ValueKey('replay-practice')));
      final hub = await api.request('GET', '/v1/replay');
      final c = (hub['cases'] as List).firstWhere(
        (c) => c['data_kind'] == 'synthetic',
      );
      expect(c['model']['quality_gate_passed'], true);
      await tap(find.byKey(ValueKey('replay-start-${c['id']}')));
      await tester.tap(find.text('사전 계획 등록'));
      await tester.pumpAndSettle();
      await tap(find.byKey(const ValueKey('replay-start-confirm')));
      await tester.drag(find.byType(ListView).last, const Offset(0, 2000));
      await tester.pumpAndSettle();
      await capture('session');
      for (var i = 0; i < 5; i++) {
        await tap(find.byKey(const ValueKey('replay-next')));
      }
      await tap(find.text('현재가 입력'));
      await tap(find.byKey(const ValueKey('replay-order')));
      expect(find.text('행동 점수 30/100'), findsOneWidget);
      await capture('warning');
      await tester.enterText(
        find.byKey(const ValueKey('trade-reason')),
        '급등 후 진입 조건을 다시 확인하려고 보류',
      );
      FocusManager.instance.primaryFocus?.unfocus();
      await tester.pumpAndSettle();
      await tester.tap(find.text('주문 보류'));
      await tester.pumpAndSettle();
      await Future<void>.delayed(const Duration(milliseconds: 250));
      await tester.pumpAndSettle();
      await tester.drag(find.byType(ListView).last, const Offset(0, 2000));
      await tester.pumpAndSettle();
      for (var i = 0; i < 12; i++) {
        await tap(find.byKey(const ValueKey('replay-next')));
      }
      await tap(find.byKey(const ValueKey('replay-finish')));
      await tap(find.text('당시 AI 예측과 1시간 후 결과'));
      await capture('prediction-review');
      await tap(find.text('판단 기록 · 1건'));
      expect(find.text('급등 후 진입 조건을 다시 확인하려고 보류'), findsOneWidget);
      await tester.ensureVisible(find.text('판단 기록 · 1건'));
      await tester.pumpAndSettle();
      await capture('decision-reason');
      await tap(find.text('유형별 행동 피드백'));
      expect(find.text('급등 추격 매수 · 탐지 1회'), findsOneWidget);
      await tester.ensureVisible(find.text('유형별 행동 피드백'));
      await tester.pumpAndSettle();
      await capture('behavior-review');
      await tap(find.text('연구 CSV 복사'));
      final report = await api.request('GET', '/v1/replay');
      final first = report['runs'][0];
      expect(first['summary']['warned_deferrals'], 1);
      ScaffoldMessenger.of(
        tester.element(find.text('모의투자 모드')),
      ).hideCurrentSnackBar();
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('연구 관찰 결과'));
      await tester.pumpAndSettle();
      await capture('results');
      await tap(find.text('같은 조건 · 반대 Pilot'));
      await tap(find.byKey(const ValueKey('replay-start-confirm')));
      final paired = (await api.request('GET', '/v1/replay'))['runs'][0];
      expect(paired['pilot_enabled'], false);
      expect(paired['pair_id'], first['pair_id']);
      expect(paired['comparison_key'], first['comparison_key']);
      final exported = await api.request(
        'GET',
        '/v1/replay/runs/${first['id']}/export',
      );
      expect(exported['csv'], contains('deferred'));
      expect(exported['csv'], contains('급등 후 진입 조건을 다시 확인하려고 보류'));
      expect(exported['csv'], contains('prediction_actual_direction'));
      final review = exported['evidence']['prediction_review'];
      expect(review['summary']['unique_predictions'], 1);
      expect(review['summary']['resolved'], 1);
      expect(
        first['summary']['warning_types'][0]['deferred_after_presentation'],
        1,
      );
      // Completing the second run allows navigation back, never a third run.
      await tester.drag(find.byType(ListView).last, const Offset(0, 4000));
      await tester.pumpAndSettle();
      await tap(find.byKey(const ValueKey('replay-finish')));
      expect(find.text('같은 조건 · 반대 Pilot'), findsNothing);
      await tap(find.text('짝 실험 열기'));
      expect(find.textContaining('Pilot ON (고정)'), findsOneWidget);
      expect(tester.takeException(), isNull);
      binding.reportData = {
        'captures': captures,
        'summary': {
          'case': c,
          'run': first,
          'paired': paired,
          'evidence': exported['evidence'],
          'purpose':
              'synthetic software verification; not participant research',
        },
      };
      await tester.pumpWidget(const SizedBox());
      await repo.dispose();
    },
  );
}
