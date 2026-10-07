import 'models.dart';

enum ConnectionState {
  disconnected,
  connecting,
  connected,
  reconnecting,
  paused,
}

abstract interface class TradingRepository {
  bool get isDemo;
  Stream<Quote> get quotes;
  Stream<ConnectionState> get connections;
  Future<List<Quote>> snapshot();
  Future<Prediction?> prediction(String symbol);
  Future<List<OrderReceipt>> orders();
  Future<OrderCheck> check(OrderDraft draft);
  Future<OrderReceipt> submit(OrderDraft draft, OrderCheck check, String key);
  Future<void> connect();
  Future<void> pause();
  Future<void> dispose();
}
