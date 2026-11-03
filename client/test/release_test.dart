import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:tradepilot_client/app/tradepilot_app.dart';
import 'package:tradepilot_client/core/network/api_client.dart';
import 'package:tradepilot_client/core/design/design_document.dart';
import 'package:tradepilot_client/features/trading/data/demo_trading_repository.dart';
import 'package:tradepilot_client/features/trading/domain/models.dart';
import 'package:tradepilot_client/features/trading/domain/workspace_repository.dart';
import 'package:tradepilot_client/features/trading/presentation/trading_controller.dart';
import 'package:tradepilot_client/features/trading/presentation/design_bindings.dart';
import 'package:tradepilot_client/features/trading/presentation/risk_confirmation.dart';
import 'api_client_test.dart' show MemoryTokens;

class ReleaseRepository extends DemoTradingRepository
    implements WorkspaceRepository {
  bool failPrediction = false;
  @override
  Future<Map<String, dynamic>> workspaceRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    if (path == '/v1/account') return {'available_cash_won': '90000'};
    if (path == '/v1/settings') return {'cooldown_seconds': 300};
    if (path == '/v1/journal') throw StateError('journal temporarily down');
    if (path.startsWith('/v1/predictions/')) {
      if (failPrediction) throw StateError('model unavailable');
      return {
        'status': 'available',
        'up': .7,
        'neutral': .2,
        'down': .1,
        'model_version': 'v1',
        'generated_at': DateTime.now().toUtc().toIso8601String(),
        'valid_until': DateTime.now()
            .toUtc()
            .add(const Duration(minutes: 5))
            .toIso8601String(),
      };
    }
    return {'items': []};
  }
}

void main() {
  test(
    'journal failure preserves account; failed refresh clears previous prediction',
    () async {
      final repo = ReleaseRepository();
      final c = TradingController(repo);
      addTearDown(c.dispose);
      await c.refreshPortfolio();
      expect(c.accountData?['available_cash_won'], '90000');
      expect(c.journalData, isNull);
      await c.select('005930');
      expect(c.prediction, isNotNull);
      repo.failPrediction = true;
      await c.refreshPrediction();
      expect(c.prediction, isNull);
      expect(c.predictionData?['status'], 'unavailable');
    },
  );
  testWidgets(
    'server watchlist binds arbitrary symbols and grows without clipping',
    (tester) async {
      final document = await tester.runAsync(DesignDocument.load);
      final c = TradingController(ReleaseRepository());
      addTearDown(c.dispose);
      for (var i = 0; i < 7; i++) {
        final symbol = '12345$i';
        c.market[symbol] = Quote(
          symbol: symbol,
          name: '종목 $i',
          priceWon: 1000,
          asOf: DateTime.now().toUtc(),
          sequence: 1,
          source: 'provider',
        );
      }
      final screen = document!.screen(0);
      DesignBindings(
        c,
        screen: 0,
        quantity: 1,
        price: 1000,
        side: OrderSide.buy,
        query: '',
        segment: 0,
      ).apply(screen);
      final rows = children(
        screen,
      ).where((n) => n['action'] == 'SELECT_SYMBOL').toList();
      expect(rows.length, 7);
      expect(rows.last['symbol'], '123456');
      expect(screen['h'], 1054);
      expect(children(rows.first).any((n) => n['value'] == '종목 0'), isTrue);
    },
  );
  testWidgets(
    'Pilot off permits concise confirmation without mandatory reason',
    (tester) async {
      final check = OrderCheck(
        id: 'x',
        allowed: true,
        messages: const ['위험 규칙 적용'],
        expiresAt: DateTime.now().toUtc().add(const Duration(minutes: 1)),
        analysis: const {
          'behavior': {'enabled': false},
        },
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: RiskConfirmation(check: check)),
        ),
      );
      final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, '확인 후 주문 진행'),
      );
      expect(button.onPressed, isNotNull);
      expect(find.byKey(const ValueKey('warning-ack')), findsNothing);
    },
  );
  testWidgets(
    'signup validates confirmation and returns to login after API success',
    (tester) async {
      final tokens = MemoryTokens()..value = null;
      var sent = 0;
      final api = ApiClient(
        Uri.parse('https://example.test'),
        tokens,
        client: MockClient((r) async {
          expect(r.url.path, '/v1/auth/signup');
          expect(r.headers.containsKey('Authorization'), isFalse);
          expect(
            jsonDecode(r.body)['password_confirmation'],
            'long-password-123',
          );
          sent++;
          return http.Response('{"status":"created"}', 201);
        }),
      );
      await tester.pumpWidget(
        TradePilotApp(repositoryFactory: DemoTradingRepository.new, api: api),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('모의투자 계정 만들기'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.widgetWithText(TextField, '이메일'),
        'new@example.test',
      );
      await tester.enterText(
        find.widgetWithText(TextField, '비밀번호'),
        'long-password-123',
      );
      await tester.enterText(
        find.widgetWithText(TextField, '비밀번호 확인 (12자 이상)'),
        'wrong',
      );
      await tester.ensureVisible(find.text('회원가입 완료'));
      await tester.tap(find.text('회원가입 완료'));
      await tester.pumpAndSettle();
      expect(sent, 0);
      await tester.enterText(
        find.widgetWithText(TextField, '비밀번호 확인 (12자 이상)'),
        'long-password-123',
      );
      await tester.ensureVisible(find.text('회원가입 완료'));
      await tester.tap(find.text('회원가입 완료'));
      await tester.pumpAndSettle();
      expect(sent, 1);
      expect(find.text('가입 완료! 새 계정으로 로그인하세요.'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
