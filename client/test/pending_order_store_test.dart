import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot_client/core/auth/secure_pending_order_store.dart';
import 'package:tradepilot_client/features/trading/domain/models.dart';
import 'package:tradepilot_client/features/trading/domain/pending_order_store.dart';
import 'api_client_test.dart' show MemoryTokens;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test(
    'persisted requests are isolated per account and survive token clearing',
    () async {
      FlutterSecureStorage.setMockInitialValues({});
      final tokens = MemoryTokens();
      final store = SecurePendingOrderStore(tokens);
      final pending = PendingOrder(
        const OrderDraft(
          symbol: '005930',
          side: OrderSide.buy,
          quantity: 1,
          limitPriceWon: 72800,
          pilotEnabled: true,
        ),
        OrderCheck(
          id: 'check-id',
          allowed: true,
          messages: [],
          expiresAt: DateTime.now().toUtc(),
        ),
        'order-key',
      );
      await store.save(pending);
      await tokens.clear();
      expect((await store.load())!.key, 'order-key');
      await tokens.writeSubject('different-user');
      expect(await store.load(), isNull);
      await tokens.writeSubject('test-user');
      expect((await store.load())!.draft.symbol, '005930');
      await store.clear();
      expect(await store.load(), isNull);
    },
  );
}
