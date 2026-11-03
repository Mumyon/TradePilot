import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot_client/features/trading/domain/workspace_repository.dart';
import 'package:tradepilot_client/features/trading/presentation/workspace_screen.dart';
import 'package:tradepilot_client/features/trading/presentation/market_chart.dart';

class FixtureWorkspace implements WorkspaceRepository {
  final calls = <String>[];
  Map<String, dynamic> settings = {
    'order_limit_won': 1000000,
    'daily_loss_limit_won': 100000,
    'cooldown_seconds': 300,
    'trading_rules': '분할 매수',
  };
  bool watched = true;
  String status = 'accepted';
  final plans = <Map<String, dynamic>>[];
  @override
  Future<Map<String, dynamic>> workspaceRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    calls.add('$method $path');
    if (path == '/v1/settings') {
      if (method == 'PUT') settings = body!;
      return settings;
    }
    if (path == '/v1/plans') {
      if (method == 'POST') {
        plans.add({
          ...body!,
          'id': 'plan',
          'created_at': '2026-10-18T00:00:00Z',
        });
      }
      return {'items': plans};
    }
    if (path.startsWith('/v1/watchlist/')) {
      watched = method == 'PUT';
      return {};
    }
    if (path.endsWith('/cancel')) {
      status = 'cancelled';
      return {};
    }
    return switch (path) {
      '/v1/account' => {
        'cash_won': '10000000',
        'reserved_won': '72811',
        'available_cash_won': '9927189',
        'equity_won': null,
        'realized_pnl_won': '0',
        'realized_pnl_complete': false,
        'holdings': [],
        'as_of': '2026-10-18T00:00:00Z',
        'fee_policy': '모의 수수료',
      },
      '/v1/symbols' => {
        'items': [
          {'symbol': '005930', 'name': '삼성전자', 'watched': watched},
        ],
      },
      '/v1/orders' => {
        'items': [
          {'order_id': 'order', 'symbol': '005930', 'status': status},
        ],
      },
      '/v1/fills' => {
        'items': [
          {
            'symbol': '005930',
            'side': 'sell',
            'quantity': 1,
            'price_won': '73000',
            'fee_won': '11',
            'realized_pnl_won': null,
            'created_at': '2026-10-18T00:00:00Z',
            'source': 'demo',
          },
        ],
      },
      _ => throw StateError(path),
    };
  }
}

Future<void> launch(WidgetTester tester, FixtureWorkspace repo, int tab) async {
  tester.view.physicalSize = const Size(1000, 1800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      theme: ThemeData.dark(),
      home: WorkspaceScreen(repository: repo, initialTab: tab),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('settings validation persists only valid values', (tester) async {
    final repo = FixtureWorkspace();
    await launch(tester, repo, 1);
    final limit = find.widgetWithText(TextFormField, '1회 주문한도 (원)');
    await tester.enterText(limit, '-1');
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
    await tester.pumpAndSettle();
    expect(repo.calls.contains('PUT /v1/settings'), isFalse);
    await tester.enterText(limit, '500000');
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
    await tester.pumpAndSettle();
    expect(repo.settings['order_limit_won'], 500000);
    expect(tester.takeException(), isNull);
  });
  testWidgets('watchlist remove add and search', (tester) async {
    final repo = FixtureWorkspace();
    await launch(tester, repo, 2);
    await tester.tap(find.byTooltip('관심종목 삭제'));
    await tester.pumpAndSettle();
    expect(repo.watched, isFalse);
    await tester.tap(find.byTooltip('관심종목 추가'));
    await tester.pumpAndSettle();
    expect(repo.watched, isTrue);
    await tester.enterText(find.byType(TextField), '없는종목');
    await tester.pumpAndSettle();
    expect(find.text('검색 결과가 없습니다.'), findsOneWidget);
  });
  testWidgets(
    'plan stores explicit conditions and cancellation changes state',
    (tester) async {
      final repo = FixtureWorkspace();
      await launch(tester, repo, 3);
      await tester.enterText(
        find.widgetWithText(TextFormField, '진입·청산 조건'),
        '72000원 이하 매수',
      );
      await tester.enterText(
        find.widgetWithText(TextFormField, '계획 최대 금액 (원)'),
        '300000',
      );
      await tester.scrollUntilVisible(
        find.text('새 매매 계획 저장'),
        150,
        scrollable: find
            .descendant(
              of: find.byType(ListView).hitTestable(),
              matching: find.byType(Scrollable),
            )
            .first,
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('새 매매 계획 저장'));
      await tester.pumpAndSettle();
      expect(repo.plans.single['entry_condition'], '72000원 이하 매수');
      await tester.pumpWidget(const SizedBox());
      await launch(tester, repo, 4);
      await tester.tap(find.text('취소'));
      await tester.pumpAndSettle();
      expect(repo.status, 'cancelled');
      expect(find.textContaining('실현손익 확인 불가'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('candles render source, stale and empty states', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: SizedBox(
          width: 342,
          height: 236,
          child: MarketChart(
            data: {
              'source': 'demo',
              'stale': true,
              'items': [
                {
                  'opened_at': '2026-10-18T00:00:00Z',
                  'open_won': '72000',
                  'high_won': '73000',
                  'low_won': '71000',
                  'close_won': '72500',
                  'volume': 1234,
                },
              ],
            },
          ),
        ),
      ),
    );
    expect(find.text('테스트 생성 데이터 · 지연'), findsOneWidget);
    expect(find.textContaining('거래량 1234'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(
      const MaterialApp(home: MarketChart(data: {'items': []})),
    );
    expect(find.text('캔들 데이터가 없습니다.'), findsOneWidget);
  });
}
