import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot_client/features/trading/domain/workspace_repository.dart';
import 'package:tradepilot_client/features/trading/presentation/backtest_screen.dart';

class BacktestFixture implements WorkspaceRepository {
  final strategies = <Map<String, dynamic>>[];
  Map<String, dynamic>? execution;
  @override
  Future<Map<String, dynamic>> workspaceRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    if (path == '/v1/strategies') {
      if (method == 'POST') {
        strategies.add({'id': 'saved', ...body!});
        return strategies.last;
      }
      return {'items': strategies};
    }
    if (path == '/v1/backtests') return {'items': [], 'next_offset': null};
    if (path.endsWith('/backtests')) {
      execution = body;
      return {
        'data_label': '합성 시연 데이터',
        'return_pct': 0,
        'max_drawdown_pct': 0,
        'final_equity_won': 10000000,
        'fee_won': 0,
        'round_trips': 0,
        'wins': 0,
        'losses': 0,
        'flat': 0,
        'win_rate_pct': null,
        'realized_pnl_won': 0,
        'unrealized_pnl_won': 0,
        'open_quantity': 0,
        'bar_count': 120,
        'first_bar': 'start',
        'last_bar': 'end',
        'end_policy': '종가 평가',
        'trades': [],
      };
    }
    throw Exception('unexpected $method $path');
  }
}

void main() {
  testWidgets(
    'save then execute selected strategy and disclose synthetic result',
    (tester) async {
      final repo = BacktestFixture();
      await tester.pumpWidget(
        MaterialApp(home: BacktestScreen(repository: repo)),
      );
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('새 전략 저장'),
        250,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.text('새 전략 저장'));
      await tester.pumpAndSettle();
      expect(repo.strategies.single['slow_period'], 20);
      await tester.scrollUntilVisible(
        find.text('백테스트 실행'),
        250,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.text('백테스트 실행'));
      await tester.pumpAndSettle();
      expect(repo.execution!['source'], 'demo');
      expect(repo.execution!['initial_cash_won'], 10000000);
      await tester.scrollUntilVisible(
        find.text('합성 시연 데이터'),
        150,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.text('합성 시연 데이터'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
