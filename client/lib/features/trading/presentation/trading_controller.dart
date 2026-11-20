import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';

import '../domain/trading_models.dart';
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
  TradingController(
    this.repository, {
    PendingOrderStore? pendingOrders,
    this.pilotEnabled = true,
  }) : pendingOrders = pendingOrders ?? MemoryPendingOrderStore();
  final TradingRepository repository;
  final PendingOrderStore pendingOrders;
  bool recoveryBlocked = false;
  final Map<String, Quote> market = {};
  Map<String, String> watchlistInstruments = const {};
  final Map<String, List<Quote>> _watchlistQuotes = {};

  Iterable<int> watchlistPrices(String symbol) =>
      (_watchlistQuotes[symbol] ?? const <Quote>[]).map(
        (quote) => quote.priceWon,
      );

  void _recordMarketQuote(Quote quote) {
    market[quote.symbol] = quote;
    final history = _watchlistQuotes.putIfAbsent(quote.symbol, () => []);
    final last = history.lastOrNull;
    if (last != null && !quote.asOf.isAfter(last.asOf)) return;
    history.add(quote);
    if (history.length > 24) history.removeAt(0);
  }

  List<OrderReceipt> journal = [];
  Prediction? prediction;
  String? predictionReason;
  Map<String, dynamic>? fiveMinuteSummary;
  Map<String, dynamic>? volatilityIndex;
  DateTime? _lastVolatilityRequest;
  static const _chartRefreshInterval = Duration(seconds: 5);
  Timer? _chartRefreshTimer;
  bool _chartRefreshing = false;
  int? _fiveMinuteLoadingGeneration;
  Map<String, dynamic>? accountData, candleData, journalData, discoveryData;
  String? marketAnalysisStatus;
  String? marketAnalysisJudgment;
  String? marketAnalysisMessage;
  bool _chartAnalysisVisible = false;
  int _marketAnalysisGeneration = 0;
  Future<void>? _marketAnalysisRequest;
  Timer? _marketAnalysisPoll;
  String? discoveryError;
  bool _discoveryLoading = false;
  String candleInterval = '15m';
  int _candleGeneration = 0;
  bool _candleLoading = false;
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
    if (!_disposed) {
      _portfolioLoading = false;
      _notify();
    }
  }

  Future<void> loadCandles([String? interval, bool retainData = false]) async {
    if (interval != null) candleInterval = interval;
    final repo = repository;
    final symbol = selectedSymbol;
    if (repo is! WorkspaceRepository || symbol == null || _disposed) return;
    if (retainData && _candleLoading) return;
    final generation = ++_candleGeneration;
    _candleLoading = true;
    if (!retainData) candleData = null;
    _notify();
    try {
      final data = await (repo as WorkspaceRepository).workspaceRequest(
        'GET',
        '/v1/market/${Uri.encodeComponent(symbol)}/candles?interval=$candleInterval',
      );
      if (!_disposed && generation == _candleGeneration) candleData = data;
    } catch (_) {
      if (!_disposed && generation == _candleGeneration) {
        candleData = {...?candleData, 'stale': true, 'status': 'unavailable'};
      }
    } finally {
      if (generation == _candleGeneration) _candleLoading = false;
    }
    _notify();
  }

  Future<void> loadDiscovery({bool force = false}) async {
    final repo = repository;
    if (repo is! WorkspaceRepository || _discoveryLoading || _disposed) return;
    if (!force && discoveryData != null) return;
    _discoveryLoading = true;
    discoveryError = null;
    _notify();
    try {
      discoveryData = await (repo as WorkspaceRepository).workspaceRequest(
        'GET',
        '/v1/market/discover',
      );
      discoveryError = null;
    } catch (_) {
      discoveryError = '실제 시세를 불러오지 못했습니다. API 설정과 연결 상태를 확인하세요.';
    } finally {
      _discoveryLoading = false;
      _notify();
    }
  }

  String? selectedSymbol, error;
  ConnectionState connection = ConnectionState.disconnected;
  bool loading = false;
  bool pilotEnabled;
  OrderStage stage = OrderStage.idle;
  OrderDraft? draft;
  OrderCheck? check;
  OrderReceipt? receipt;
  String? _idempotencyKey;
  bool _disposed = false, _refreshing = false;
  int _predictionGeneration = 0;
  Timer? _clock;
  StreamSubscription<Quote>? _quotes;
  StreamSubscription<Quote>? _chartQuotes;
  StreamSubscription<ConnectionState>? _connections;

  Quote? _selectedQuote;
  Quote? _chartTrade;
  String? _selectedName;
  int? previousCloseWon;
  Quote? get selected => _selectedQuote?.symbol == selectedSymbol
      ? _selectedQuote
      : market[selectedSymbol];
  Quote? get chartTrade => _chartTrade;
  Quote? get chartDisplayQuote => chartQuoteLive ? _chartTrade : selected;
  // Toss admits a small clock skew when it receives an actual trade.
  // Keep the original timestamp and use that tolerance only for chart display.
  bool get chartQuoteLive {
    final trade = _chartTrade;
    if (trade == null) return false;
    final age = DateTime.now().toUtc().difference(trade.asOf);
    return age >= const Duration(seconds: -2) &&
        age <= const Duration(seconds: 15);
  }

  String get selectedName =>
      selected?.name ?? _selectedName ?? selectedSymbol ?? '종목을 선택하세요';

  Future<void> loadSelectedQuote() async {
    final repo = repository;
    final symbol = selectedSymbol;
    if (repo is! WorkspaceRepository || symbol == null || _disposed) return;
    try {
      final data = await (repo as WorkspaceRepository).workspaceRequest(
        'GET',
        '/v1/market/${Uri.encodeComponent(symbol)}/quote',
      );
      if (_disposed || selectedSymbol != symbol) return;
      _selectedName = data['name'] as String?;
      previousCloseWon = int.tryParse('${data['previous_close_won']}');
      final raw = data['quote'];
      if (raw is Map<String, dynamic>) {
        _updateSelectedQuote(Quote.fromJson(raw));
      }
      final execution = data['execution_quote'];
      if (execution is Map<String, dynamic>) {
        _updateChartTrade(Quote.fromJson(execution));
      }
    } catch (_) {
      // Keep the instrument identity and last timestamped quote during outages.
    }
    _notify();
  }

  bool get online => connection == ConnectionState.connected;
  bool get discoveryLoading => _discoveryLoading;
  bool _testMode = false;
  bool get testMode => _testMode;
  bool get orderQuoteAvailable =>
      testMode ? selectedSymbol != null : quoteFresh;

  void setTestMode(bool enabled) {
    if (!canEdit || _testMode == enabled) return;
    _testMode = enabled;
    resetOrder();
  }

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
    final chartRepo = repository;
    if (chartRepo is ChartQuoteRepository) {
      _chartQuotes = (chartRepo as ChartQuoteRepository).chartQuotes.listen((
        quote,
      ) {
        if (_chartAnalysisVisible && _updateChartTrade(quote)) {
          _notify();
        }
      }, onError: (Object _) {});
    }
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
          if (!_chartAnalysisVisible) unawaited(loadSelectedQuote());
          unawaited(refreshPortfolio());
          if (_portfolioTimer!.tick % 6 == 0) {
            if (_chartAnalysisVisible || repository is! WorkspaceRepository) {
              unawaited(refreshPrediction());
            }
          }
        }
      });
    }
  }

  void _acceptQuote(Quote quote) {
    final updatedSelected = _updateSelectedQuote(quote);
    if (repository is WorkspaceRepository &&
        _watchedSymbols != null &&
        !_watchedSymbols!.contains(quote.symbol)) {
      if (updatedSelected) _notify();
      return;
    }
    final previous = market[quote.symbol];
    if (previous != null && quote.sequence <= previous.sequence) {
      if (updatedSelected) _notify();
      return;
    }
    _recordMarketQuote(quote);
    if (selectedSymbol == null) {
      selectedSymbol = quote.symbol;
      if (_chartAnalysisVisible) {
        _subscribeToChart();
        unawaited(refreshMarketAnalysis(automatic: true));
        if (repository is WorkspaceRepository) unawaited(refreshPrediction());
      }
    }
    _notify();
  }

  bool _updateChartTrade(Quote quote) {
    if (quote.symbol != selectedSymbol ||
        (_chartTrade != null && quote.asOf.isBefore(_chartTrade!.asOf))) {
      return false;
    }
    _chartTrade = quote;
    _updateSelectedQuote(quote);
    return true;
  }

  bool _updateSelectedQuote(Quote quote) {
    if (quote.symbol != selectedSymbol) return false;
    final previous = _selectedQuote ?? market[quote.symbol];
    if (previous != null &&
        (quote.asOf.isBefore(previous.asOf) ||
            (quote.asOf == previous.asOf &&
                _chartTrade?.asOf == quote.asOf &&
                !identical(quote, _chartTrade)))) {
      return false;
    }
    _selectedQuote = quote;
    return true;
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
      final source = repository;
      watchlistInstruments = {
        if (source is WatchlistInstrumentRepository)
          ...(source as WatchlistInstrumentRepository).watchlistInstruments,
        for (final quote in quotes) quote.symbol: quote.name,
      };
      _watchedSymbols = watchlistInstruments.keys.toSet();
      market.removeWhere((symbol, _) => !_watchedSymbols!.contains(symbol));
      _watchlistQuotes.removeWhere(
        (symbol, _) => !_watchedSymbols!.contains(symbol),
      );
      for (final quote in quotes) {
        final previous = market[quote.symbol];
        if (previous == null || quote.sequence >= previous.sequence) {
          _recordMarketQuote(quote);
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
    final changed = selectedSymbol != symbol;
    if (changed) {
      _selectedQuote = null;
      _chartTrade = null;
      fiveMinuteSummary = null;
      _selectedName = null;
      previousCloseWon = null;
      prediction = null;
      predictionReason = null;
      _predictionGeneration++;
      marketAnalysisStatus = null;
      marketAnalysisJudgment = null;
      marketAnalysisMessage = null;
      _marketAnalysisGeneration++;
      _marketAnalysisRequest = null;
      _marketAnalysisPoll?.cancel();
    }
    selectedSymbol = symbol;
    _selectedName ??= market[symbol]?.name;
    unawaited(loadCandles());
    if (_chartAnalysisVisible && (changed || marketAnalysisStatus == null)) {
      _subscribeToChart();
      unawaited(refreshMarketAnalysis(automatic: true));
      if (repository is WorkspaceRepository) unawaited(refreshPrediction());
    }
    await Future.wait([
      loadSelectedQuote(),
      if (repository is! WorkspaceRepository) refreshPrediction(),
    ]);
  }

  void setChartAnalysisVisible(bool visible) {
    if (_chartAnalysisVisible == visible) return;
    _chartAnalysisVisible = visible;
    _subscribeToChart();
    if (visible) {
      unawaited(refreshMarketAnalysis(automatic: true));
      unawaited(loadVolatilityIndex());
      if (repository is WorkspaceRepository) unawaited(refreshPrediction());
    } else {
      _marketAnalysisPoll?.cancel();
    }
  }

  Future<void> loadVolatilityIndex({bool force = false}) async {
    final repo = repository;
    if (repo is! WorkspaceRepository || _disposed) return;
    final at = DateTime.now();
    if (!force &&
        _lastVolatilityRequest != null &&
        at.difference(_lastVolatilityRequest!) < const Duration(minutes: 15)) {
      return;
    }
    _lastVolatilityRequest = at;
    try {
      final data = await (repo as WorkspaceRepository).workspaceRequest(
        'GET',
        '/v1/market/volatility-index',
      );
      if (!_disposed) volatilityIndex = data;
    } catch (_) {
      if (!_disposed && volatilityIndex == null) {
        volatilityIndex = {'status': 'unavailable'};
      }
    }
    _notify();
  }

  void _subscribeToChart() {
    final repo = repository;
    if (repo is ChartQuoteRepository) {
      (repo as ChartQuoteRepository).setChartSymbol(
        _chartAnalysisVisible ? selectedSymbol : null,
      );
    }
    _chartRefreshTimer?.cancel();
    if (_chartAnalysisVisible &&
        selectedSymbol != null &&
        repo is WorkspaceRepository) {
      unawaited(refreshFiveMinuteAnalysis());
      _chartRefreshTimer = Timer.periodic(
        _chartRefreshInterval,
        (_) => unawaited(_refreshChart()),
      );
    }
  }

  Future<void> _refreshChart() async {
    if (_chartRefreshing || _disposed) return;
    _chartRefreshing = true;
    try {
      await Future.wait([
        loadSelectedQuote(),
        loadCandles(null, true),
        refreshFiveMinuteAnalysis(),
      ]);
    } finally {
      _chartRefreshing = false;
    }
  }

  Future<void> refreshFiveMinuteAnalysis() async {
    final repo = repository;
    final symbol = selectedSymbol;
    if (repo is! WorkspaceRepository || symbol == null || _disposed) return;
    final generation = _marketAnalysisGeneration;
    if (_fiveMinuteLoadingGeneration == generation) return;
    _fiveMinuteLoadingGeneration = generation;
    try {
      final data = await (repo as WorkspaceRepository).workspaceRequest(
        'GET',
        '/v1/market/${Uri.encodeComponent(symbol)}/five-minute-analysis',
      );
      if (!_disposed && generation == _marketAnalysisGeneration) {
        fiveMinuteSummary = data['summary'] as Map<String, dynamic>?;
        _notify();
      }
    } catch (_) {
      // Keep the last observed summary with its original timestamp.
    } finally {
      if (_fiveMinuteLoadingGeneration == generation) {
        _fiveMinuteLoadingGeneration = null;
      }
    }
  }

  Future<void> refreshMarketAnalysis({bool automatic = false}) {
    final repo = repository;
    final symbol = selectedSymbol;
    if (!pilotEnabled ||
        repo is! WorkspaceRepository ||
        symbol == null ||
        _disposed) {
      return Future.value();
    }
    return _marketAnalysisRequest ??= _loadMarketAnalysis(
      repo as WorkspaceRepository,
      symbol,
      automatic: automatic,
    );
  }

  Future<void> _loadMarketAnalysis(
    WorkspaceRepository repo,
    String symbol, {
    required bool automatic,
  }) async {
    final generation = _marketAnalysisGeneration;
    final path = '/v1/market/${Uri.encodeComponent(symbol)}/ai-analysis';
    _marketAnalysisPoll?.cancel();
    String? status, judgment, message;
    try {
      var data = await repo.workspaceRequest('GET', path);
      if (automatic &&
          _chartAnalysisVisible &&
          !_disposed &&
          generation == _marketAnalysisGeneration &&
          data['status'] == 'ready') {
        data = await repo.workspaceRequest(
          'POST',
          path,
          body: {'consent': true, 'automatic': true},
        );
      }
      status = data['status'] as String?;
      message = data['message'] as String?;
      final value = (data['result'] as Map?)?['judgment'];
      if (status == 'available' && {'매수', '매도', '보류', '관망'}.contains(value)) {
        judgment = value as String;
      }
    } catch (_) {
      status = 'unavailable';
    }
    if (!_disposed && generation == _marketAnalysisGeneration) {
      _marketAnalysisRequest = null;
      marketAnalysisStatus = status;
      marketAnalysisJudgment = judgment;
      marketAnalysisMessage = message;
      if (_chartAnalysisVisible && {'pending', 'generating'}.contains(status)) {
        _marketAnalysisPoll = Timer(const Duration(seconds: 3), () {
          unawaited(refreshMarketAnalysis());
        });
      }
      _notify();
    }
  }

  Future<void> refreshPrediction() async {
    final symbol = selectedSymbol;
    if (!pilotEnabled || symbol == null || _disposed) return;
    final generation = ++_predictionGeneration;
    try {
      final repo = repository;
      final data = repo is WorkspaceRepository
          ? await (repo as WorkspaceRepository).workspaceRequest(
              'GET',
              '/v1/predictions/${Uri.encodeComponent(symbol)}',
            )
          : null;
      final result = data == null
          ? await repository.prediction(symbol)
          : data['status'] == 'available'
          ? Prediction.fromJson(data)
          : null;
      if (!_disposed && generation == _predictionGeneration) {
        prediction = result;
        predictionReason = data?['reason'] as String?;
      }
    } catch (_) {
      if (!_disposed && generation == _predictionGeneration) {
        prediction = null;
        predictionReason = 'connection';
      }
    }
    _notify();
  }

  void setPilot(bool enabled) {
    if (!canEdit || pilotEnabled == enabled) return;
    pilotEnabled = enabled;
    _marketAnalysisGeneration++;
    _marketAnalysisRequest = null;
    _marketAnalysisPoll?.cancel();
    marketAnalysisStatus = null;
    marketAnalysisJudgment = null;
    marketAnalysisMessage = null;
    _predictionGeneration++;
    prediction = null;
    predictionReason = null;
    resetOrder();
    if (enabled && _chartAnalysisVisible) {
      unawaited(refreshMarketAnalysis(automatic: true));
      unawaited(refreshPrediction());
    }
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
    if ((!online && !testMode) ||
        !orderQuoteAvailable ||
        selectedSymbol == null ||
        quantity <= 0 ||
        priceWon <= 0) {
      error = testMode
          ? '종목을 선택하고 올바른 지정가와 수량을 입력하세요.'
          : '최신 시세 연결과 올바른 가격·수량이 필요합니다.';
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
      pilotEnabled: repository is WorkspaceRepository ? false : pilotEnabled,
      planId: planId,
      testMode: testMode,
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
    if (!online && draft?.testMode != true) {
      error = '연결 복구 후 다시 시도하세요. 주문은 자동 재전송하지 않습니다.';
      _notify();
      return;
    }
    if (stage == OrderStage.ready &&
        (!orderQuoteAvailable ||
            !DateTime.now().toUtc().isBefore(check!.expiresAt))) {
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

  Future<void> pause() {
    _chartRefreshTimer?.cancel();
    return repository.pause();
  }

  Future<void> resume() async {
    await refresh();
    if (!_disposed) {
      _subscribeToChart();
      await repository.connect();
    }
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _clock?.cancel();
    _portfolioTimer?.cancel();
    _marketAnalysisPoll?.cancel();
    _chartRefreshTimer?.cancel();
    unawaited(_quotes?.cancel());
    unawaited(_chartQuotes?.cancel());
    unawaited(_connections?.cancel());
    unawaited(repository.dispose());
    super.dispose();
  }
}
