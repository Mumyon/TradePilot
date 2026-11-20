import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:tradepilot_client/app/tradepilot_app.dart';
import 'package:tradepilot_client/core/network/api_client.dart';
import 'package:tradepilot_client/core/design/design_document.dart';
import 'package:tradepilot_client/features/trading/data/demo_trading_repository.dart';
import 'package:tradepilot_client/features/trading/domain/trading_models.dart';
import 'package:tradepilot_client/features/trading/domain/workspace_repository.dart';
import 'package:tradepilot_client/features/trading/presentation/trading_controller.dart';
import 'package:tradepilot_client/features/trading/presentation/trading_layout_bindings.dart';
import 'package:tradepilot_client/features/trading/presentation/order_risk_check_dialog.dart';
import 'api_client_test.dart' show MemoryTokens;

class ReleaseRepository extends DemoTradingRepository
    implements WorkspaceRepository {
  bool failMarketAnalysis = false;
  @override
  Future<Map<String, dynamic>> workspaceRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    if (path == '/v1/account') return {'available_cash_won': '90000'};
    if (path == '/v1/settings') return {'cooldown_seconds': 300};
    if (path == '/v1/journal') throw StateError('journal temporarily down');
    if (path.endsWith('/ai-analysis')) {
      if (failMarketAnalysis) throw StateError('analysis unavailable');
      return {'status': 'available'};
    }
    return {'items': []};
  }
}

void main() {
  test(
    'journal failure preserves account and failed chart AI refresh clears ready state',
    () async {
      final repo = ReleaseRepository();
      final c = TradingController(repo);
      addTearDown(c.dispose);
      await c.refreshPortfolio();
      expect(c.accountData?['available_cash_won'], '90000');
      expect(c.journalData, isNull);
      await c.select('005930');
      await c.refreshMarketAnalysis();
      expect(c.marketAnalysisStatus, 'available');
      repo.failMarketAnalysis = true;
      await c.refreshMarketAnalysis();
      expect(c.marketAnalysisStatus, 'unavailable');
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
      TradingLayoutBindings(
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
          home: Scaffold(body: OrderRiskCheckDialog(check: check)),
        ),
      );
      final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, '확인 후 주문 진행'),
      );
      expect(button.onPressed, isNotNull);
      expect(find.byKey(const ValueKey('warning-ack')), findsNothing);
    },
  );
  testWidgets('photo information opens from the bottom of the login screen', (
    tester,
  ) async {
    const description = '푸르고 무성한 침엽수 숲을 지나가는 고요한 길, 생기 넘치는 초록 잔디로 둘러싸인 시골 풍경.';
    final api = ApiClient(
      Uri.parse('https://example.test'),
      MemoryTokens()..value = null,
      client: MockClient((_) async => throw StateError('Unexpected request')),
    );
    await tester.pumpWidget(
      TradePilotApp(repositoryFactory: DemoTradingRepository.new, api: api),
    );
    await tester.pumpAndSettle();

    final info = find.text('이 사진에 대한 정보');
    final login = find.widgetWithText(FilledButton, '로그인');
    expect(tester.getCenter(info).dy, greaterThan(tester.getCenter(login).dy));
    await tester.tap(info);
    await tester.pumpAndSettle();
    expect(find.text(description).hitTestable(), findsOneWidget);
    await tester.tapAt(const Offset(10, 10));
    await tester.pumpAndSettle();
    expect(find.text(description), findsNothing);
    expect(login.hitTestable(), findsOneWidget);
  });

  testWidgets('successful login fades the form before zooming into the photo', (
    tester,
  ) async {
    await tester.runAsync(DesignDocument.load);
    final tokens = MemoryTokens()..value = null;
    var logoutRequests = 0;
    final api = ApiClient(
      Uri.parse('https://example.test'),
      tokens,
      client: MockClient((request) async {
        if (request.url.path == '/v1/auth/logout') {
          logoutRequests++;
          return http.Response('{}', 200);
        }
        expect(request.url.path, '/v1/auth/login');
        return http.Response('{"access_token":"token","user_id":"test"}', 200);
      }),
    );
    var mainScreenStarts = 0;
    await tester.pumpWidget(
      TradePilotApp(
        repositoryFactory: () {
          mainScreenStarts++;
          return DemoTradingRepository();
        },
        api: api,
      ),
    );
    await tester.pumpAndSettle();

    final formFade = find
        .ancestor(
          of: find.byType(TextField).first,
          matching: find.byType(FadeTransition),
        )
        .first;
    final zoom = find.byKey(const ValueKey('login-background-zoom'));
    double opacity() => tester.widget<FadeTransition>(formFade).opacity.value;
    double scale() => tester.widget<ScaleTransition>(zoom).scale.value;

    await tester.tap(find.widgetWithText(FilledButton, '로그인'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 110));
    expect(opacity(), allOf(greaterThan(0), lessThan(1)));
    expect(scale(), 1);
    await tester.pump(const Duration(milliseconds: 290));
    expect(opacity(), 0);
    expect(scale(), 1);
    await tester.pump(const Duration(milliseconds: 1000));
    expect(scale(), greaterThan(1));
    expect(mainScreenStarts, 0);
    await tester.pumpAndSettle();
    expect(mainScreenStarts, 1);
    expect(zoom, findsNothing);
    await tester.tap(find.widgetWithText(TextButton, '로그인 화면으로'));
    await tester.pumpAndSettle();
    expect(logoutRequests, 1);
    expect(tokens.value, isNull);
    expect(find.widgetWithText(FilledButton, '로그인'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

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
      await tester.tap(find.text('손쉽게 계정 만들기'));
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
