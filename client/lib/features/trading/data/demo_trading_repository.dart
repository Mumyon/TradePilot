import 'dart:async';

import '../domain/models.dart';
import '../domain/trading_repository.dart';

/// UI fixtures only. Does not implement a matching engine or risk engine.
class DemoTradingRepository implements TradingRepository {
  final _quotes = StreamController<Quote>.broadcast();
  final _connections = StreamController<ConnectionState>.broadcast();
  final Map<String, OrderReceipt> _receipts = {};
  Timer? _timer;
  int _sequence = 0;
  @override
  bool get isDemo => true;
  @override
  Stream<Quote> get quotes => _quotes.stream;
  @override
  Stream<ConnectionState> get connections => _connections.stream;
  @override
  Future<List<Quote>> snapshot() async => [
    Quote(
      symbol: '005930',
      name: '삼성전자',
      priceWon: 72800 + (_sequence % 5) * 100,
      asOf: DateTime.now().toUtc(),
      sequence: _sequence,
    ),
    Quote(
      symbol: '000660',
      name: 'SK하이닉스',
      priceWon: 173500,
      asOf: DateTime.now().toUtc(),
      sequence: _sequence,
    ),
  ];
  @override
  Future<Prediction?> prediction(String symbol) async => Prediction(
    up: .62,
    neutral: .24,
    down: .14,
    generatedAt: DateTime.now().toUtc(),
    validUntil: DateTime.now().toUtc().add(const Duration(minutes: 5)),
    modelVersion: 'demo-fixture',
  );
  @override
  Future<List<OrderReceipt>> orders() async =>
      _receipts.values.toList().reversed.toList();
  @override
  Future<OrderCheck> check(OrderDraft draft) async => OrderCheck(
    id: 'demo-check',
    allowed: draft.quantity > 0 && draft.quantity <= 10,
    messages: [
      '데모 검사: 1~10주만 허용합니다. 실제 잔액·위험 검사는 서버 연결 후 적용됩니다.',
      if (draft.pilotEnabled) '예시: 급등 추격 가능성 · 주문 계획을 다시 확인하세요.',
    ],
    expiresAt: DateTime.now().toUtc().add(const Duration(seconds: 60)),
  );
  @override
  Future<OrderReceipt> submit(
    OrderDraft draft,
    OrderCheck check,
    String key,
  ) async {
    if (!check.allowed) throw StateError('거절된 주문입니다.');
    return _receipts.putIfAbsent(
      key,
      () => OrderReceipt(
        id: 'demo-${_receipts.length + 1}',
        symbol: draft.symbol,
        status: 'accepted',
      ),
    );
  }

  @override
  Future<void> connect() async {
    if (_timer != null) return;
    _connections.add(ConnectionState.connected);
    _timer = Timer.periodic(const Duration(seconds: 2), (_) async {
      ++_sequence;
      for (final quote in await snapshot()) {
        if (!_quotes.isClosed) _quotes.add(quote);
      }
    });
  }

  @override
  Future<void> pause() async {
    _timer?.cancel();
    _timer = null;
    _connections.add(ConnectionState.paused);
  }

  @override
  Future<void> dispose() async {
    await pause();
    await _quotes.close();
    await _connections.close();
  }
}
