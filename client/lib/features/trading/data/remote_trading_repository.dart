import '../../../core/network/api_client.dart';
import '../../../core/network/market_socket.dart';
import '../domain/models.dart';
import '../domain/trading_repository.dart';

class RemoteTradingRepository implements TradingRepository {
  RemoteTradingRepository(this.api) : socket = MarketSocket(api);
  final ApiClient api;
  final MarketSocket socket;
  @override
  bool get isDemo => false;
  @override
  Stream<Quote> get quotes => socket.events
      .where((event) => event['type'] == 'quote')
      .map((event) => Quote.fromJson(event['data'] as Map<String, dynamic>));
  @override
  Stream<ConnectionState> get connections => socket.states;
  @override
  Future<List<Quote>> snapshot() async {
    final json = await api.request('GET', '/v1/watchlist');
    return (json['items'] as List)
        .map((item) => Quote.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  @override
  Future<Prediction?> prediction(String symbol) async {
    final json = await api.request(
      'GET',
      '/v1/predictions/${Uri.encodeComponent(symbol)}',
    );
    return json['status'] == 'available' ? Prediction.fromJson(json) : null;
  }

  @override
  Future<List<OrderReceipt>> orders() async {
    final json = await api.request('GET', '/v1/orders');
    return (json['items'] as List)
        .map((item) => OrderReceipt.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  @override
  Future<OrderCheck> check(OrderDraft draft) async => OrderCheck.fromJson(
    await api.request('POST', '/v1/orders/check', body: draft.toJson()),
  );
  @override
  Future<OrderReceipt> submit(
    OrderDraft draft,
    OrderCheck check,
    String key,
  ) async => OrderReceipt.fromJson(
    await api.request(
      'POST',
      '/v1/orders',
      body: {...draft.toJson(), 'check_id': check.id},
      idempotencyKey: key,
    ),
  );
  @override
  Future<void> connect() => socket.start();
  @override
  Future<void> pause() => socket.pause();
  @override
  Future<void> dispose() => socket.dispose();
}
