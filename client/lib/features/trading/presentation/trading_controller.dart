import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';

import '../domain/models.dart';
import '../domain/workspace_repository.dart';
import '../domain/pending_order_store.dart';
import '../domain/trading_repository.dart';

enum OrderStage {
  idle,
  checking,
  ready,
  blocked,
  sending,
  uncertain,
  completed,
}

class TradingController extends ChangeNotifier {
  TradingController(this.repository, {PendingOrderStore? pendingOrders})
    : pendingOrders = pendingOrders ?? MemoryPendingOrderStore();
  final TradingRepository repository;
  final PendingOrderStore pendingOrders;
  bool recoveryBlocked = false;
  final Map<String, Quote> market = {};
  List<OrderReceipt> journal = [];
  Prediction? prediction;
  Map<String, dynamic>? accountData,
      candleData,
      predictionData,
      journalData,
      settingsData;
  String candleInterval = '15m';
  int _candleGeneration = 0;
  Timer? _portfolioTimer;
  bool _portfolioLoading = false;
  Set<String>? _watchedSymbols;

  Future<void> refreshPortfolio() async {
    final repo = repository;
    if (repo is! WorkspaceRepository || _portfolioLoading || _disposed) return;
    _portfolioLoading = true;
    try {
      final data = await (repo as WorkspaceRepository).workspaceRequest(
        'GET',
        '/v1/account',
      );
      final rows = await repository.orders();

      if (!_disposed) {
        accountData = data;

        journal = rows;
        if (receipt != null) {
          receipt =
              rows.where((row) => row.id == receipt!.id).firstOrNull ?? receipt;
        }
      }
    } catch (_) {
      if (!_disposed) accountData = null;
    }
    try {
      final report = await (repo as WorkspaceRepository).workspaceRequest(
        'GET',
        '/v1/journal',
      );
      if (!_disposed) journalData = report;
    } catch (_) {
      if (!_disposed) journalData = null;
    }
    try {
      final prefs = await (repo as WorkspaceRepository).workspaceRequest(
        'GET',
        '/v1/settings',
      );
      if (!_disposed) settingsData = prefs;
    } catch (_) {
      if (!_disposed) settingsData = null;
    }
    if (!_disposed) {
      _portfolioLoading = false;
      _notify();
    }
  }

  Future<void> loadCandles([String? interval, bool retainData = false]) async {
    if (interval != null) candleInterval = interval;
    final repo = repository;
    final symbol = selectedSymbol;
    final generation = ++_candleGeneration;
    if (!retainData) candleData = null;
    _notify();
    if (repo is! WorkspaceRepository || symbol == null) return;
    try {
      final data = await (repo as WorkspaceRepository).workspaceRequest(
        'GET',
        '/v1/market/${Uri.encodeComponent(symbol)}/candles?interval=$candleInterval',
      );
      if (!_disposed && generation == _candleGeneration) candleData = data;
    } catch (_) {
      if (!_disposed && generation == _candleGeneration) {
        candleData = {'status': 'unavailable', 'items': []};
      }
    }
    _notify();
  }

  String? selectedSymbol, error;
  ConnectionState connection = ConnectionState.disconnected;
  bool loading = false, pilotEnabled = true;
  OrderStage stage = OrderStage.idle;
  OrderDraft? draft;
  OrderCheck? check;
  OrderReceipt? receipt;
  String? _idempotencyKey;
  bool _disposed = false, _refreshing = false;
  int _predictionGeneration = 0;
  Timer? _clock;
  StreamSubscription<Quote>? _quotes;
  StreamSubscription<ConnectionState>? _connections;

  Quote? get selected => market[selectedSymbol];
  bool get online => connection == ConnectionState.connected;
  bool get quoteFresh => selected?.isFresh(DateTime.now().toUtc()) ?? false;
  bool get busy => stage == OrderStage.checking || stage == OrderStage.sending;
  bool get canEdit =>
      !busy && stage != OrderStage.uncertain && !recoveryBlocked;

  Future<void> start() async {
    try {
      final pending = await pendingOrders.load();
      if (pending != null) {
        draft = pending.draft;
        check = pending.check;
        _idempotencyKey = pending.key;
        pilotEnabled = draft!.pilotEnabled;
        selectedSymbol = draft!.symbol;
        stage = OrderStage.uncertain;
      }
    } catch (_) {
      recoveryBlocked = true;
    }
    if (_disposed) return;
    _quotes = repository.quotes.listen(
      _acceptQuote,
      onError: (Object _) {
        error = '시세 메시지 형식을 확인할 수 없습니다.';
        _notify();
      },
    );
    _connections = repository.connections.listen((state) {
      connection = state;
      if (state == ConnectionState.connected) unawaited(refresh());
      _notify();
    });
    _clock = Timer.periodic(const Duration(seconds: 1), (_) => _notify());
    await refresh();
    if (!_disposed) {
      await repository.connect();
      _portfolioTimer ??= Timer.periodic(const Duration(seconds: 5), (_) {
        if (online) {
          unawaited(refreshPortfolio());
          if (_portfolioTimer!.tick % 6 == 0) {
            unawaited(loadCandles(null, true));
            unawaited(refreshPrediction());
          }
        }
      });
    }
  }

  void _acceptQuote(Quote quote) {
    if (repository is WorkspaceRepository &&
        _watchedSymbols != null &&
        !_watchedSymbols!.contains(quote.symbol)) {
      return;
    }
    final previous = market[quote.symbol];
    if (previous != null && quote.sequence <= previous.sequence) return;
    market[quote.symbol] = quote;
    selectedSymbol ??= quote.symbol;
    _notify();
  }

  Future<void> refresh() async {
    if (_refreshing || _disposed) return;
    _refreshing = true;
    loading = true;
    error = null;
    _notify();
    try {
      final quotes = await repository.snapshot();
      if (_disposed) return;
      _watchedSymbols = quotes.map((q) => q.symbol).toSet();
      market.removeWhere((symbol, _) => !quotes.any((q) => q.symbol == symbol));
      if (!market.containsKey(selectedSymbol) && canEdit) selectedSymbol = null;
      for (final quote in quotes) {
        final previous = market[quote.symbol];
        if (previous == null || quote.sequence >= previous.sequence) {
          market[quote.symbol] = quote;
        }
      }
      selectedSymbol ??= quotes.firstOrNull?.symbol;
      journal = await repository.orders();
      await refreshPortfolio();
      if (selectedSymbol != null) await select(selectedSymbol!);
    } catch (_) {
      error = '데이터를 불러오지 못했습니다. 연결 및 로그인 상태를 확인하세요.';
    } finally {
      _refreshing = false;
      loading = false;
      _notify();
    }
  }

  Future<void> select(String symbol) async {
    selectedSymbol = symbol;
    unawaited(loadCandles());
    await refreshPrediction();
  }

  Future<void> refreshPrediction() async {
    final symbol = selectedSymbol;
    if (symbol == null || _disposed) return;
    prediction = null;
    predictionData = null;
    final generation = ++_predictionGeneration;
    _notify();
    try {
      Prediction? result;
      Map<String, dynamic>? raw;
      if (repository is WorkspaceRepository) {
        raw = await (repository as WorkspaceRepository).workspaceRequest(
          'GET',
          '/v1/predictions/${Uri.encodeComponent(symbol)}',
        );
        result = raw['status'] == 'available' ? Prediction.fromJson(raw) : null;
      } else {
        result = await repository.prediction(symbol);
      }
      if (!_disposed && generation == _predictionGeneration) {
        prediction = result;
        predictionData = raw;
      }
    } catch (_) {
      if (!_disposed && generation == _predictionGeneration) {
        prediction = null;
        predictionData = {
          'status': 'unavailable',
          'message': '분석 요청 실패 · 다시 시도하세요.',
        };
      }
    }
    _notify();
  }

  void setPilot(bool enabled) {
    if (!canEdit) return;
    pilotEnabled = enabled;
    resetOrder();
  }

  void resetOrder() {
    if (!canEdit) return;
    stage = OrderStage.idle;
    draft = null;
    check = null;
    receipt = null;
    _idempotencyKey = null;
    _notify();
  }

  Future<void> prepare(
    OrderSide side,
    int quantity,
    int priceWon, {
    String? planId,
  }) async {
    if (!canEdit) return;
    resetOrder();
    if (!online ||
        !quoteFresh ||
        selected == null ||
        quantity <= 0 ||
        priceWon <= 0) {
      error = '최신 시세 연결과 올바른 가격·수량이 필요합니다.';
      _notify();
      return;
    }
    error = null;
    stage = OrderStage.checking;
    final nextDraft = OrderDraft(
      symbol: selectedSymbol!,
      side: side,
      quantity: quantity,
      limitPriceWon: priceWon,
      pilotEnabled: pilotEnabled,
      planId: planId,
    );
    draft = nextDraft;
    _notify();
    try {
      check = await repository.check(nextDraft);
      stage = check!.allowed ? OrderStage.ready : OrderStage.blocked;
      _idempotencyKey = const Uuid().v4();
    } catch (_) {
      stage = OrderStage.idle;
      error = '주문 점검에 실패했습니다. 다시 점검하세요.';
    }
    _notify();
  }

  void acknowledgeWarning(String reason, bool high) {
    if (stage != OrderStage.ready) return;
    check = check?.acknowledge(reason, high);
    _notify();
  }

  Future<void> submit() async {
    if (stage != OrderStage.ready && stage != OrderStage.uncertain) return;
    if (stage == OrderStage.ready &&
        check!.requiresAck &&
        (!check!.warningAcknowledged ||
            check!.tradeReason.trim().length < 3 ||
            (check!.requiresHighAck && !check!.highRiskAcknowledged))) {
      error = '행동 경고와 거래 이유를 확인하세요.';
      _notify();
      return;
    }
    if (!online) {
      error = '연결 복구 후 다시 시도하세요. 주문은 자동 재전송하지 않습니다.';
      _notify();
      return;
    }
    if (stage == OrderStage.ready &&
        (!quoteFresh || !DateTime.now().toUtc().isBefore(check!.expiresAt))) {
      resetOrder();
      error = '시세 또는 점검 결과가 만료되었습니다. 다시 점검하세요.';
      _notify();
      return;
    }
    stage = OrderStage.sending;
    error = null;
    _notify();
    try {
      await pendingOrders.save(PendingOrder(draft!, check!, _idempotencyKey!));
    } catch (_) {
      stage = OrderStage.uncertain;
      error = '주문 복구 정보를 저장하지 못해 전송하지 않았습니다. 저장소와 계정 상태를 확인하세요.';
      _notify();
      return;
    }
    try {
      receipt = await repository.submit(draft!, check!, _idempotencyKey!);
      stage = OrderStage.completed;
      try {
        await pendingOrders.clear();
      } catch (_) {
        // Keep editing locked until the same key has been safely acknowledged.
        stage = OrderStage.uncertain;
        error = '주문 응답을 받았지만 복구 기록 정리에 실패했습니다. 동일 주문을 재확인하세요.';
      }
      // A journal refresh failure must not turn an acknowledged order uncertain.
      try {
        journal = await repository.orders();
      } catch (_) {
        error = '주문 응답을 받았지만 내역 갱신에 실패했습니다. 새로고침하세요.';
      }
    } catch (_) {
      stage = OrderStage.uncertain;
      error = '주문 결과 미확인. 새 주문을 만들지 않고 동일 식별자로 결과를 재확인합니다.';
    }
    _notify();
  }

  Future<void> pause() => repository.pause();
  Future<void> resume() async {
    await refresh();
    if (!_disposed) await repository.connect();
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _clock?.cancel();
    _portfolioTimer?.cancel();
    unawaited(_quotes?.cancel());
    unawaited(_connections?.cancel());
    unawaited(repository.dispose());
    super.dispose();
  }
}
