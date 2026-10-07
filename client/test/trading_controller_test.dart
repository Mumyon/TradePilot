import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot_client/features/trading/data/demo_trading_repository.dart';
import 'package:tradepilot_client/features/trading/domain/models.dart';
import 'package:tradepilot_client/features/trading/domain/pending_order_store.dart';
import 'package:tradepilot_client/features/trading/presentation/trading_controller.dart';

class UncertainRepository extends DemoTradingRepository {
  final keys = <String>[];
  bool failOnce = true;
  @override
  Future<OrderReceipt> submit(
    OrderDraft draft,
    OrderCheck check,
    String key,
  ) async {
    keys.add(key);
    final receipt = await super.submit(draft, check, key);
    if (failOnce) {
      failOnce = false;
      throw TimeoutException('Response lost after acceptance');
    }
    return receipt;
  }
}

class StaleRepository extends DemoTradingRepository {
  @override
  Future<List<Quote>> snapshot() async => [
    Quote(
      symbol: '005930',
      name: '삼성전자',
      priceWon: 72800,
      asOf: DateTime.now().subtract(const Duration(minutes: 1)),
      sequence: 0,
    ),
  ];
}

Future<void> settleConnection(TradingController controller) async {
  await controller.start();
  await Future<void>.delayed(Duration.zero);
}

void main() {
  test(
    'pending order survives controller recreation with the same request key',
    () async {
      final store = MemoryPendingOrderStore();
      final firstRepository = UncertainRepository();
      final first = TradingController(firstRepository, pendingOrders: store);
      await settleConnection(first);
      await first.prepare(OrderSide.buy, 1, 72800);
      await first.submit();
      final saved = await store.load();
      expect(saved, isNotNull);
      final restored = PendingOrder.fromJson(saved!.toJson());
      expect(restored.draft.limitPriceWon, 72800);
      first.dispose();
      final nextRepository = UncertainRepository()..failOnce = false;
      final next = TradingController(nextRepository, pendingOrders: store);
      addTearDown(next.dispose);
      await settleConnection(next);
      expect(next.stage, OrderStage.uncertain);
      await next.submit();
      expect(nextRepository.keys.single, firstRepository.keys.single);
      expect(await store.load(), isNull);
    },
  );
  test('62 percent remains undecided, separate from neutral', () async {
    final repository = DemoTradingRepository();
    expect((await repository.prediction('005930'))!.direction, '방향 판단 보류');
    await repository.dispose();
  });

  test(
    'lost order response reuses key and produces exactly one demo receipt',
    () async {
      final repository = UncertainRepository();
      final controller = TradingController(repository);
      addTearDown(controller.dispose);
      await settleConnection(controller);
      await controller.prepare(OrderSide.buy, 1, 72800);
      expect(controller.stage, OrderStage.ready);
      await controller.submit();
      expect(controller.stage, OrderStage.uncertain);
      controller.resetOrder();
      expect(controller.stage, OrderStage.uncertain);
      controller.setPilot(false);
      expect(controller.pilotEnabled, isTrue);
      await controller.submit();
      expect(controller.stage, OrderStage.completed);
      expect(repository.keys.length, 2);
      expect(repository.keys.toSet().length, 1);
      expect((await repository.orders()).length, 1);
    },
  );

  test('pilot OFF still performs mandatory order check', () async {
    final controller = TradingController(DemoTradingRepository());
    addTearDown(controller.dispose);
    await settleConnection(controller);
    controller.setPilot(false);
    await controller.prepare(OrderSide.buy, 11, 72800);
    expect(controller.stage, OrderStage.blocked);
    await controller.submit();
    expect(controller.receipt, isNull);
  });

  test('stale quote cannot prepare order', () async {
    final controller = TradingController(StaleRepository());
    addTearDown(controller.dispose);
    await settleConnection(controller);
    await controller.prepare(OrderSide.buy, 1, 72800);
    expect(controller.check, isNull);
    expect(controller.stage, OrderStage.idle);
  });

  test('pause prevents submission and does not queue orders', () async {
    final controller = TradingController(DemoTradingRepository());
    addTearDown(controller.dispose);
    await settleConnection(controller);
    await controller.prepare(OrderSide.buy, 1, 72800);
    await controller.pause();
    await Future<void>.delayed(Duration.zero);
    await controller.submit();
    expect(controller.receipt, isNull);
    expect(controller.stage, OrderStage.ready);
  });

  test('invalid probability response rejected', () {
    expect(
      () => Prediction.fromJson({'up': .9, 'neutral': .9, 'down': .1}),
      throwsFormatException,
    );
  });
}
