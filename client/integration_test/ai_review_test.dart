import 'dart:convert';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:tradepilot_client/core/network/api_client.dart';
import 'package:tradepilot_client/features/trading/data/remote_trading_repository.dart';
import 'package:tradepilot_client/features/trading/presentation/ai_replay_review.dart';
import '../test/api_client_test.dart' show MemoryTokens;

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'native consent, queued AI review, frozen evidence and cached retrieval',
    (tester) async {
      final api = ApiClient(
        Uri.parse('http://127.0.0.1:18080'),
        MemoryTokens(),
      );
      final email = 'ai-${DateTime.now().microsecondsSinceEpoch}@example.test';
      await api.request(
        'POST',
        '/v1/auth/signup',
        authenticated: false,
        body: {
          'email': email,
          'password': 'ai-integration-password',
          'password_confirmation': 'ai-integration-password',
        },
      );
      await api.login(email, 'ai-integration-password');
      final c = await api.request('POST', '/v1/replay/practice');
      final first = await api.request(
        'POST',
        '/v1/replay/cases/${c['id']}/runs',
        body: {'request_id': 'first-native', 'pilot_enabled': true},
      );
      Future<Map<String, dynamic>> finish(Map<String, dynamic> run) =>
          api.request(
            'POST',
            '/v1/replay/runs/${run['id']}/actions',
            body: {
              'request_id': 'finish-${run['id']}',
              'revision': run['revision'],
              'action': 'finish',
            },
          );
      await finish(first);
      final path = '/v1/replay/runs/${first['id']}/ai-review';
      expect((await api.request('GET', path))['reason'], 'pair_incomplete');
      final second = await api.request(
        'POST',
        '/v1/replay/cases/${c['id']}/runs',
        body: {
          'request_id': 'second-native',
          'pilot_enabled': false,
          'paired_run_id': first['id'],
        },
      );
      await finish(second);
      expect((await api.request('GET', path))['status'], 'ready');
      final boundary = GlobalKey();
      final captures = <String, String>{};
      Future<void> capture(String name) async {
        final image =
            await (boundary.currentContext!.findRenderObject()!
                    as RenderRepaintBoundary)
                .toImage(pixelRatio: 2);
        final data = await image.toByteData(format: ui.ImageByteFormat.png);
        captures[name] = base64Encode(data!.buffer.asUint8List());
        image.dispose();
      }

      await tester.pumpWidget(
        RepaintBoundary(
          key: boundary,
          child: MaterialApp(
            theme: ThemeData.dark(),
            home: Scaffold(
              appBar: AppBar(title: const Text('자동검증 · 합성 · AI 응답 대역')),
              body: SingleChildScrollView(
                child: AIReplayReview(
                  repository: RemoteTradingRepository(api),
                  runId: first['id'] as String,
                ),
              ),
            ),
          ),
        ),
      );
      await Future<void>.delayed(const Duration(seconds: 1));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('ai-review-generate')));
      await tester.pumpAndSettle();
      await capture('consent');
      expect((await api.request('GET', '/__test__/stats'))['mock_requests'], 0);
      await tester.tap(find.text('동의하고 생성'));
      await tester.pumpAndSettle();
      for (
        var i = 0;
        i < 15 && find.textContaining('AI 해설 ·').evaluate().isEmpty;
        i++
      ) {
        await Future<void>.delayed(const Duration(seconds: 1));
        await tester.pump(const Duration(seconds: 1));
        await tester.pumpAndSettle();
      }
      expect(find.text('AI 해설 · 계획과 실제 주문 판단을 나란히 확인해 보세요.'), findsOneWidget);
      await capture('review');
      final result = await api.request('GET', path);
      expect(result['status'], 'available');
      await api.request('POST', path, body: {'consent': true});
      expect((await api.request('GET', '/__test__/stats'))['mock_requests'], 1);
      final exported = await api.request(
        'GET',
        '/v1/replay/runs/${first['id']}/export',
      );
      expect(exported['evidence']['ai_review']['result'], result['result']);
      expect(tester.takeException(), isNull);
      binding.reportData = {
        'captures': captures,
        'summary': {
          'synthetic': true,
          'provider_transport_mock': true,
          'external_api_calls': 0,
          'single_request_and_cache': true,
          'pair_completion_gate': true,
          'response_id': result['response_id'],
          'prompt_version': result['prompt_version'],
        },
      };
      await tester.pumpWidget(const SizedBox());
      api.close();
    },
  );
}
