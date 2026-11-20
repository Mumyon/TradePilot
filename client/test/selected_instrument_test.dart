import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot_client/features/trading/data/demo_trading_repository.dart';
import 'package:tradepilot_client/features/trading/domain/trading_models.dart';
import 'package:tradepilot_client/features/trading/domain/workspace_repository.dart';
import 'package:tradepilot_client/features/trading/presentation/trading_controller.dart';

class BrowseRepository extends DemoTradingRepository
    implements WorkspaceRepository {
  @override
  Future<List<Quote>> snapshot() async => [];

  @override
  Future<Map<String, dynamic>> workspaceRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    if (path.endsWith('/quote')) {
      final symbol = path.split('/')[3];
      return {
        'symbol': symbol,
        'name': '탐색 종목 $symbol',
        'quote': {
          'symbol': symbol,
          'name': '탐색 종목 $symbol',
          'price_won': '190000',
          'as_of': DateTime.now().toUtc().toIso8601String(),
          'sequence': 1,
          'source': 'toss_kr',
        },
      };
    }
    return {};
  }
}

void main() {
  test(
    'browsed stock has identity and quote without joining the watchlist',
    () async {
      final controller = TradingController(BrowseRepository());
      addTearDown(controller.dispose);
      await controller.select('005930');
      expect(controller.selectedName, '탐색 종목 005930');
      expect(controller.selected?.priceWon, 190000);
      expect(controller.market, isEmpty);
      await controller.refresh();
      expect(controller.selectedSymbol, '005930');
      expect(controller.selected?.priceWon, 190000);
      expect(controller.market, isEmpty);
      await controller.select('000660');
      expect(controller.selected?.symbol, '000660');
      expect(controller.selectedName, '탐색 종목 000660');
    },
  );
}
