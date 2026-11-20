import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot_client/features/trading/data/demo_trading_repository.dart';
import 'package:tradepilot_client/features/trading/domain/trading_models.dart';
import 'package:tradepilot_client/features/trading/domain/workspace_repository.dart';
import 'package:tradepilot_client/features/trading/presentation/paper_trading_management_screen.dart';
import 'package:tradepilot_client/features/trading/presentation/stock_price_chart.dart';
import 'package:tradepilot_client/features/trading/presentation/stock_balance_screen.dart';
import 'package:tradepilot_client/features/trading/presentation/stock_discovery_screen.dart';
import 'package:tradepilot_client/features/trading/presentation/trading_controller.dart';

class FixtureWorkspace implements WorkspaceRepository {
  final calls = <String>[];
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
      home: PaperTradingManagementScreen(repository: repo, initialTab: tab),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('discovery sort opens below its button and reorders stocks', (
    tester,
  ) async {
    final controller = TradingController(DemoTradingRepository())
      ..discoveryData = {
        'items': [
          {'name': '삼성전자', 'turnover_won': 200, 'volume': 10},
          {'name': 'SK하이닉스', 'turnover_won': 100, 'volume': 20},
        ],
      };
    addTearDown(controller.dispose);
    var sortBy = 'turnover';
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: StatefulBuilder(
            builder: (context, setState) => StockDiscoveryScreen(
              controller: controller,
              sortBy: sortBy,
              onSortChanged: (value) => setState(() => sortBy = value),
              onSelectSymbol: (_) {},
            ),
          ),
        ),
      ),
    );

    final button = find.byTooltip('종목 정렬 기준');
    final samsung = find.text('삼성전자');
    final hynix = find.text('SK하이닉스');
    expect(
      tester.getTopLeft(samsung).dy,
      lessThan(tester.getTopLeft(hynix).dy),
    );
    expect(find.text('거래량'), findsNothing);
    final buttonBottom = tester.getBottomLeft(button).dy;
    await tester.tap(button);
    await tester.pumpAndSettle();
    expect(tester.getTopLeft(find.text('거래량')).dy, greaterThan(buttonBottom));
    expect(find.text('상승률'), findsOneWidget);
    expect(find.text('하락률'), findsOneWidget);
    await tester.tap(find.widgetWithText(CheckedPopupMenuItem<String>, '거래량'));
    await tester.pumpAndSettle();
    expect(
      find.descendant(of: button, matching: find.text('거래량')),
      findsOneWidget,
    );
    expect(
      tester.getTopLeft(hynix).dy,
      lessThan(tester.getTopLeft(samsung).dy),
    );
  });

  testWidgets(
    'stock balance switches from holdings to date and symbol profit',
    (tester) async {
      final repo = _BalanceFixture();
      String? selected;
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: StockBalanceScreen(
              repository: repo,
              onManage: () {},
              onSelectSymbol: (symbol) => selected = symbol,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('순자산'), findsOneWidget);
      expect(find.text('+9.98%'), findsNWidgets(2));
      expect(find.text('+9,983원'), findsNWidgets(2));
      expect(
        tester.getTopLeft(find.text('매입금액')).dy,
        tester.getTopLeft(find.text('평가손익').first).dy,
      );
      await tester.tap(find.text('삼성전자'));
      expect(selected, '005930');

      await tester.tap(find.text('매매 손익'));
      await tester.pumpAndSettle();
      expect(find.text('2026-10-19'), findsOneWidget);
      expect(find.text('+9.00%'), findsNWidgets(2));
      await tester.tap(find.text('종목별'));
      await tester.pumpAndSettle();
      expect(find.text('삼성전자'), findsOneWidget);
      expect(
        repo.calls,
        contains('GET /v1/account/trade-profit?group_by=symbol'),
      );
      await tester.tap(find.byTooltip('종목 선택'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('삼성전자').last);
      await tester.pumpAndSettle();
      expect(
        repo.calls,
        contains('GET /v1/account/trade-profit?group_by=symbol&symbol=005930'),
      );
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  testWidgets('account has four tabs and never requests removed preferences', (
    tester,
  ) async {
    final repo = FixtureWorkspace();
    await launch(tester, repo, 0);
    expect(find.byType(Tab), findsNWidgets(4));
    for (final text in [
      '거래 설정',
      '1회 주문한도 (원)',
      '일일 손실한도 (원)',
      '주문 쿨다운 (초)',
      '나의 거래 원칙',
      '신규 모의주문 정지',
    ]) {
      expect(find.text(text), findsNothing);
    }
    expect(repo.calls.any((call) => call.contains('/v1/settings')), isFalse);
    expect(find.text('모의투자 계좌'), findsOneWidget);
  });
  testWidgets('watchlist remove add and search', (tester) async {
    final repo = FixtureWorkspace();
    await launch(tester, repo, 1);
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
      await launch(tester, repo, 2);
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
      await launch(tester, repo, 3);
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
          child: StockPriceChart(
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
      const MaterialApp(home: StockPriceChart(data: {'items': []})),
    );
    expect(find.text('캔들 데이터가 없습니다.'), findsOneWidget);
  });

  testWidgets(
    'chart changes style, calculates indicators and opens the interval menu',
    (tester) async {
      final start = DateTime.utc(2026, 11, 12);
      final bars = List.generate(45, (index) {
        final price = 70000 + index * 10;
        return {
          'opened_at': start
              .add(Duration(minutes: 5 * index))
              .toIso8601String(),
          'open_won': '$price',
          'high_won': '${price + 10}',
          'low_won': '${price - 10}',
          'close_won': '${price + 5}',
          'volume': 1000,
        };
      });
      String? selected;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Align(
              alignment: Alignment.topLeft,
              child: SizedBox(
                width: 342,
                child: Column(
                  children: [
                    SizedBox(
                      height: 312,
                      child: StockPriceChart(
                        interactive: true,
                        data: {'items': bars},
                        interval: '5m',
                        onIntervalChanged: (interval) => selected = interval,
                      ),
                    ),
                    ChartVolatilityIndex(
                      volatilityIndex: {
                        'close': 18.7,
                        'change': 1.21,
                        'as_of': '2026-11-12',
                      },
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.byTooltip('그래프 종류'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('영역'));
      await tester.pumpAndSettle();
      expect(find.text('영역'), findsOneWidget);
      await tester.tap(find.byTooltip('보조지표'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('MACD'));
      await tester.pumpAndSettle();
      expect(find.text('MACD 70.00 · 시그널 70.00'), findsOneWidget);
      await tester.tap(find.byTooltip('보조지표'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('RSI'));
      await tester.pumpAndSettle();
      expect(find.text('RSI(14)  100.00'), findsOneWidget);
      expect(find.textContaining('VIX 18.70'), findsOneWidget);
      final intervalMenu = find.byTooltip('시간 단위');
      expect(
        tester.getCenter(intervalMenu).dy,
        tester.getCenter(find.byTooltip('보조지표')).dy,
      );
      await tester.tap(intervalMenu);
      await tester.pumpAndSettle();
      await tester.tap(find.text('30분'));
      await tester.pumpAndSettle();
      expect(selected, '30m');
      await tester.tap(find.byTooltip('봉 종류'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('년봉'));
      expect(selected, '1y');
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('chart time axis identifies both Korean trading dates', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 342,
            height: 312,
            child: StockPriceChart(
              interactive: true,
              interval: '5m',
              data: {
                'items': [
                  for (final stamp in [
                    '2026-11-12T05:55:00Z',
                    '2026-11-13T00:00:00Z',
                  ])
                    {
                      'opened_at': stamp,
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
      ),
    );
    final chart = find.descendant(
      of: find.byType(StockPriceChart),
      matching: find.byWidgetPredicate(
        (widget) =>
            widget is CustomPaint && widget.painter?.semanticsBuilder != null,
      ),
    );
    final painter = tester.widget<CustomPaint>(chart).painter!;
    final axis = painter.semanticsBuilder!(tester.getSize(chart)).single;
    expect(
      axis.properties.label,
      '차트 기간 2026.11.12 14:55 ~ 2026.11.13 09:00 · 한국 시간',
    );
    expect(find.textContaining('마지막 봉 2026.11.13 09:00'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'chart shows live and selected prices and pinches between intervals',
    (tester) async {
      final start = DateTime.utc(2026, 11, 12);
      final data = {
        'source': 'toss_kr',
        'items': [
          for (var i = 0; i < 40; i++)
            {
              'opened_at': start
                  .add(Duration(minutes: 5 * i))
                  .toIso8601String(),
              'open_won': '72000',
              'high_won': '73000',
              'low_won': '71000',
              'close_won': '72500',
              'volume': 1234,
            },
        ],
      };
      final intervals = <String>[];
      Future<void> showChart(int price) => tester.pumpWidget(
        MaterialApp(
          home: Material(
            child: Center(
              child: SizedBox(
                width: 342,
                height: 312,
                child: StockPriceChart(
                  data: data,
                  interactive: true,
                  interval: '5m',
                  onIntervalChanged: intervals.add,
                  liveQuote: Quote(
                    symbol: '005930',
                    name: '삼성전자',
                    priceWon: price,
                    asOf: start.add(
                      Duration(minutes: 201, seconds: price % 60),
                    ),
                    sequence: price,
                    source: 'toss_kr',
                  ),
                ),
              ),
            ),
          ),
        ),
      );

      await showChart(73450);
      expect(find.textContaining('73,450원'), findsOneWidget);
      await showChart(73480);
      expect(find.textContaining('73,480원'), findsOneWidget);
      final plot = find
          .descendant(
            of: find.byType(StockPriceChart),
            matching: find.byType(CustomPaint),
          )
          .last;
      final center = tester.getCenter(plot);
      await tester.tapAt(center);
      await tester.pump();
      expect(find.textContaining('종가 72,500원'), findsOneWidget);
      expect(find.text('최신'), findsNothing);

      String visibleRange() {
        final painter = tester.widget<CustomPaint>(plot).painter!;
        return painter
            .semanticsBuilder!(tester.getSize(plot))
            .single
            .properties
            .label!;
      }

      final initialRange = visibleRange();
      Future<void> wheel(double dy) async {
        await tester.sendEventToBinding(
          PointerScrollEvent(position: center, scrollDelta: Offset(0, dy)),
        );
        await tester.pump();
      }

      await wheel(-120);
      expect(visibleRange(), isNot(initialRange));
      await wheel(120);
      expect(visibleRange(), initialRange);

      await tester.sendEventToBinding(
        PointerScaleEvent(position: center, scale: 2),
      );
      await tester.pump();
      expect(visibleRange(), isNot(initialRange));
      await tester.sendEventToBinding(
        PointerScaleEvent(position: center, scale: .5),
      );
      await tester.pump();
      expect(visibleRange(), initialRange);

      final trackpad = await tester.startGesture(
        center,
        kind: PointerDeviceKind.trackpad,
      );
      await trackpad.panZoomUpdate(center, scale: 1.5);
      await trackpad.panZoomUpdate(center, scale: 1.8);
      await trackpad.panZoomEnd();
      await tester.pump();
      expect(visibleRange(), isNot(initialRange));
      expect(intervals, isEmpty);

      final left = await tester.startGesture(
        center - const Offset(36, 0),
        pointer: 1,
      );
      final right = await tester.startGesture(
        center + const Offset(36, 0),
        pointer: 2,
      );
      await left.moveBy(const Offset(-36, 0));
      await right.moveBy(const Offset(36, 0));
      await tester.pump();
      await left.up();
      await right.up();
      await tester.pump();
      expect(intervals, ['3m']);

      final outerLeft = await tester.startGesture(
        center - const Offset(100, 0),
        pointer: 3,
      );
      final outerRight = await tester.startGesture(
        center + const Offset(100, 0),
        pointer: 4,
      );
      await outerLeft.moveBy(const Offset(55, 0));
      await outerRight.moveBy(const Offset(-55, 0));
      await tester.pump();
      await outerLeft.up();
      await outerRight.up();
      await tester.pump();
      expect(intervals, ['3m', '10m']);
      expect(tester.takeException(), isNull);
    },
  );
}

class _BalanceFixture extends FixtureWorkspace {
  @override
  Future<Map<String, dynamic>> workspaceRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    calls.add('$method $path');
    if (path == '/v1/account') {
      return {
        'stock_balance': {
          'cost_won': '100000',
          'market_value_won': '110000',
          'unrealized_pnl_won': '9983',
          'return_percent': '9.98',
          'equity_won': '10010000',
          'stale': true,
        },
        'holdings': [
          {
            'symbol': '005930',
            'name': '삼성전자',
            'cost_won': '100000',
            'price_won': '55000',
            'valuation_won': '110000',
            'valuation_pnl_won': '9983',
            'valuation_return_percent': '9.98',
            'average_price_won': '50000',
            'quantity': 2,
            'quote_as_of': '2026-10-19T06:30:00Z',
            'stale': true,
          },
        ],
      };
    }
    final grouped = Uri.parse(path).queryParameters['group_by'] == 'symbol';
    const amounts = {
      'realized_pnl_won': '9000',
      'sell_cost_won': '100000',
      'fees_won': '1000',
      'sell_amount_won': '110000',
      'sell_quantity': 2,
    };
    return {
      'summary': amounts,
      'symbols': [
        {'symbol': '005930', 'name': '삼성전자'},
      ],
      'items': [
        {
          ...amounts,
          'start_date': '2026-10-19',
          'end_date': '2026-10-19',
          if (grouped) 'name': '삼성전자',
        },
      ],
    };
  }
}
