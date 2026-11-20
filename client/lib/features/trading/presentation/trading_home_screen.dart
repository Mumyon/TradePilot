import 'strategy_backtest_screen.dart';
import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/design/design_document.dart';
import '../domain/trading_models.dart';
import '../domain/workspace_repository.dart';
import 'paper_trading_management_screen.dart';
import 'stock_balance_screen.dart';
import 'stock_discovery_screen.dart';
import 'market_overview_strip.dart';
import 'stock_price_chart.dart';
import 'chart_stock_details.dart';
import 'order_risk_check_dialog.dart';
import 'order_confirmation_panel.dart';
import 'chatgpt_analysis_panel.dart';
import 'chatgpt_prompt_screen.dart';
import 'trade_journal_screen.dart';
import '../domain/pending_order_store.dart';
import '../domain/trading_repository.dart' as domain;
import 'trading_layout_bindings.dart';
import 'trading_controller.dart';

class TradingHomeScreen extends StatefulWidget {
  const TradingHomeScreen({
    super.key,
    required this.repositoryFactory,
    this.onLogout,
    this.pendingOrders,
    this.pilotEnabled = true,
    this.onPilotChanged,
    this.invertedColors = false,
    this.onInvertedColorsChanged,
  });
  final domain.TradingRepository Function() repositoryFactory;
  final Future<void> Function()? onLogout;
  final PendingOrderStore? pendingOrders;
  final bool pilotEnabled;
  final ValueChanged<bool>? onPilotChanged;
  final bool invertedColors;
  final ValueChanged<bool>? onInvertedColorsChanged;
  @override
  State<TradingHomeScreen> createState() => _TradingHomeScreenState();
}

class _TradingHomeScreenState extends State<TradingHomeScreen>
    with WidgetsBindingObserver {
  late final TradingController controller;
  final _search = TextEditingController();
  ChartDetail _chartDetail = ChartDetail.chart;
  final _scroll = ScrollController();
  DesignDocument? _document;
  String? _loadError;
  int _screen = 0;
  int? _overlay;
  int _quantity = 1, _price = 0;
  OrderSide _side = OrderSide.buy;
  final Map<int, int> _segments = {1: 2, 8: 2};
  bool _actionPending = false;
  bool _legacyOrder = false;
  String? _lastError;
  String _discoverySort = 'turnover';
  Timer? _discoveryTimer;
  Timer? _marketOverviewTimer;
  bool _marketOverviewLoading = false;
  final Map<String, Map<String, dynamic>> _marketOverview = {};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    controller = TradingController(
      widget.repositoryFactory(),
      pendingOrders: widget.pendingOrders,
      pilotEnabled: widget.pilotEnabled,
    );
    controller.addListener(_controllerChanged);
    unawaited(controller.start());
    unawaited(_loadDesign());
    _discoveryTimer = Timer.periodic(const Duration(seconds: 15), (_) {
      if (_screen == 6) unawaited(controller.loadDiscovery(force: true));
    });
    _startMarketOverview();
  }

  void _startMarketOverview() {
    if (controller.repository is! WorkspaceRepository) return;
    _marketOverviewTimer?.cancel();
    if (_screen == 0) unawaited(_loadMarketOverview());
    _marketOverviewTimer = Timer.periodic(const Duration(seconds: 45), (_) {
      if (_screen == 0) unawaited(_loadMarketOverview());
    });
  }

  Future<void> _loadMarketOverview() async {
    final repo = controller.repository;
    if (repo is! WorkspaceRepository || _marketOverviewLoading) return;
    setState(() => _marketOverviewLoading = true);
    try {
      final data = await (repo as WorkspaceRepository).workspaceRequest(
        'GET',
        '/v1/market/overview',
      );
      if (!mounted) return;
      setState(() {
        for (final item in (data['items'] as List? ?? []).whereType<Map>()) {
          if (item['id'] case final String id) {
            _marketOverview[id] = Map<String, dynamic>.from(item);
          }
        }
      });
    } catch (_) {
      // Keep prior observations and their original timestamps.
    } finally {
      if (mounted) setState(() => _marketOverviewLoading = false);
    }
  }

  Future<void> _loadDesign() async {
    try {
      final document = await DesignDocument.load();
      if (mounted) setState(() => _document = document);
    } catch (_) {
      if (mounted) setState(() => _loadError = '데이터를 불러오지 못했습니다. 앱을 다시 실행하세요.');
    }
  }

  void _controllerChanged() {
    if (!mounted) return;
    if (controller.error != null && controller.error != _lastError) {
      final message = controller.error!;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _notify(message);
      });
    }
    _lastError = controller.error;
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      unawaited(controller.resume());
      _startMarketOverview();
    } else if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached) {
      unawaited(controller.pause());
      _marketOverviewTimer?.cancel();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _discoveryTimer?.cancel();
    _marketOverviewTimer?.cancel();
    controller.removeListener(_controllerChanged);
    controller.dispose();
    _search.dispose();
    _scroll.dispose();
    super.dispose();
  }

  int get _chart => controller.selectedSymbol == '000660' ? 8 : 1;
  int get _orderBase =>
      (_chart == 8 ? 22 : 10) +
      (_side == OrderSide.sell ? 6 : 0) +
      (_quantity == 5 ? 3 : 0);
  bool get _locked => _actionPending || controller.busy;

  DesignNode _boundScreen(int index, {int? navigationScreen}) {
    final root = _document!.screen(index);
    TradingLayoutBindings(
      controller,
      screen: index,
      quantity: _quantity,
      price: _price,
      side: _side,
      query: _search.text.trim(),
      segment: _segments[index] ?? 0,
      navigationScreen: navigationScreen,
    ).apply(root);
    return root;
  }

  @override
  Widget build(BuildContext context) => AnnotatedRegion<SystemUiOverlayStyle>(
    value: widget.invertedColors
        ? SystemUiOverlayStyle.dark
        : SystemUiOverlayStyle.light,
    child: ListenableBuilder(
      listenable: controller,
      builder: (context, _) => PopScope(
        canPop: _overlay == null && _screen == 0 && !_locked,
        onPopInvokedWithResult: (didPop, _) {
          if (!didPop && !_locked) {
            if (_showPretrade) {
              _backToOrder();
            } else if (_overlay != null) {
              setState(() => _overlay = null);
            } else {
              _navigate(0);
            }
          }
        },
        child: Scaffold(
          resizeToAvoidBottomInset: false,
          body: _document == null
              ? Center(
                  child: _loadError == null
                      ? const CircularProgressIndicator()
                      : Text(_loadError!),
                )
              : Stack(
                  children: [
                    SafeArea(child: _buildActiveTab()),
                    if (_overlay != null) _buildOrderEntryPopup(),
                    if (_showPretrade) _buildOrderConfirmationPopup(),
                    if (_locked)
                      Positioned.fill(
                        child: ColoredBox(
                          color: Colors.black.withValues(alpha: .32),
                          child: const Center(
                            child: CircularProgressIndicator(),
                          ),
                        ),
                      ),
                  ],
                ),
        ),
      ),
    ),
  );

  bool get _pretradeLocation =>
      controller.repository is WorkspaceRepository &&
      (_screen == 5 || _screen == _orderBase + 1);
  bool get _showPretrade =>
      _pretradeLocation &&
      controller.check != null &&
      controller.draft != null &&
      {OrderStage.ready, OrderStage.blocked}.contains(controller.stage);

  void _backToOrder() {
    if (_locked) return;
    controller.resetOrder();
    setState(() {
      _screen = _chart;
      _overlay = _orderBase + 2;
    });
    controller.setChartAnalysisVisible(true);
  }

  Future<void> _deferOrder() async {
    if (_locked || !_showPretrade) return;
    final checkId = controller.check!.id;
    var reason = '';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('모의주문 보류'),
        content: TextField(
          maxLength: 1000,
          onChanged: (value) => reason = value,
          decoration: const InputDecoration(hintText: '보류 이유 (선택)'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('닫기'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('보류 기록'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted || controller.check?.id != checkId) {
      return;
    }
    setState(() => _actionPending = true);
    try {
      await (controller.repository as WorkspaceRepository).workspaceRequest(
        'POST',
        '/v1/orders/check/$checkId/dismiss',
        body: {'reason': reason.trim()},
      );
      if (!mounted) return;
      controller.resetOrder();
      _navigate(_chart);
      _notify('보류 기록을 매매일지에 저장했어요.');
    } catch (_) {
      if (mounted) _notify('보류 기록을 저장하지 못했습니다. 다시 시도하세요.');
    } finally {
      if (mounted) setState(() => _actionPending = false);
    }
  }

  Widget _buildOrderConfirmationPopup() {
    final content = OrderConfirmationPanel(
      key: ValueKey(controller.check!.id),
      controller: controller,
      repository: controller.repository as WorkspaceRepository,
      onSubmit: () => _submitOrder(inlineConfirmed: true),
      onRecheck: _checkOrderBeforeConfirmation,
      onBack: _backToOrder,
      onDefer: _deferOrder,
    );
    return Positioned.fill(
      child: BlockSemantics(
        child: Stack(
          children: [
            ModalBarrier(
              color: Colors.black54,
              dismissible: true,
              onDismiss: _backToOrder,
            ),
            SafeArea(
              child: Dialog(
                insetPadding: const EdgeInsets.symmetric(
                  horizontal: 16,
                  vertical: 24,
                ),
                alignment: Alignment.bottomCenter,
                shape: const RoundedRectangleBorder(),
                child: SizedBox(
                  width: 480,
                  height: MediaQuery.sizeOf(context).height * .82,
                  child: content,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildActiveTab() {
    final root = _boundScreen(
      _screen == TradingLayoutBindings.optionsTab
          ? 0
          : _pretradeLocation
          ? _chart
          : _screen,
      navigationScreen: _screen == TradingLayoutBindings.optionsTab
          ? _screen
          : null,
    );
    final all = children(root);
    final nav = all.firstWhere((n) => n['name'] == 'Bottom navigation');
    if (_screen == 0) {
      final header = all.firstWhere((n) => n['value'] == 'MARKET / 시장을 읽다');
      header.addAll({
        'name': 'Login return',
        'type': 'group',
        'x': 244,
        'y': 46,
        'w': 122,
        'h': 44,
      });
      all.firstWhere((n) => n['value'] == 'TradePilot').addAll({
        'y': 46,
        'w': 208,
      });
      all.removeWhere((n) => n['value'] == '모의');
      final overview = all.firstWhere((n) => n['name'] == 'Market indices');
      overview.addAll({'y': 99, 'h': 170});
      for (final node in all.where((n) => n != nav && number(n, 'y') >= 217)) {
        node['y'] = number(node, 'y') + 67;
      }
      final watchlistTools = all.firstWhere(
        (n) => n['name'] == 'Watchlist tools',
      );
      watchlistTools['y'] = 276;
      all.firstWhere((n) => n['name'] == 'Segment navigation')['y'] = 325;
      children(watchlistTools).first.addAll({
        'value': '관심종목',
        'color': 'fg',
        'size': 15,
        'weight': 600,
        'h': 24,
      });
      for (final row in all.where((n) {
        final name = n['name'] as String? ?? '';
        return name.startsWith('Stock / ') || name.startsWith('Live stock / ');
      })) {
        final texts = children(row).where((node) => node['type'] == 'text');
        for (final price in texts.skip(2)) {
          price['align'] = 'right';
        }
      }
      final insight = all.firstWhere((n) => n['name'] == 'Pilot insight');
      final insightText = children(insight).where((n) => n['type'] == 'text');
      final feedback = children(
        _document!.screen(4),
      ).firstWhere((n) => n['name'] == 'Feedback');
      final [rule, label, body] = children(feedback);
      final [title, message, status] = insightText.toList();
      insight['children'] = [
        rule,
        {...label, 'value': title['value'], 'w': 328},
        {...message, ...body, 'value': message['value']},
        {...status, 'x': 14, 'y': 47, 'w': 328},
      ];
      root['h'] = number(root, 'h') + 67;
    }
    final content = all.where((n) => number(n, 'y') >= 44 && n != nav).toList();
    for (final n in content) {
      n['y'] = number(n, 'y') - 44;
    }
    final navNodes = children(nav).where((n) => number(n, 'y') < 70).toList();
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: LayoutBuilder(
          builder: (context, constraints) {
            final scale = constraints.maxWidth / 390;
            // Keep the complete 390pt composition visible on modern phones with
            // taller system safe areas; smaller windows retain natural scrolling.
            final contentHeight = constraints.maxHeight - 70 * scale;
            final designHeight = math.max(707.0, number(root, 'h') - 137);
            final chart =
                (_screen == 1 || _screen == 8 || _pretradeLocation) &&
                controller.repository is WorkspaceRepository;
            final contentScale = contentHeight >= 600
                ? (chart || _screen == 0
                      ? scale
                      : math.min(scale, contentHeight / 707))
                : scale;
            return Column(
              children: [
                Expanded(
                  child: _screen == TradingLayoutBindings.optionsTab
                      ? _buildOptionsTab()
                      : _screen == 3
                      ? _buildStockBalanceTab()
                      : _screen == 4
                      ? TradeJournalScreen(
                          repository:
                              controller.repository is WorkspaceRepository
                              ? controller.repository as WorkspaceRepository
                              : null,
                          localOrders: controller.journal,
                          stockNames: {
                            for (final quote in controller.market.values)
                              quote.symbol: quote.name,
                          },
                        )
                      : _screen == 6
                      ? StockDiscoveryScreen(
                          controller: controller,
                          sortBy: _discoverySort,
                          onSortChanged: (sortBy) =>
                              setState(() => _discoverySort = sortBy),
                          onSelectSymbol: _openStockChart,
                          invertedColors: widget.invertedColors,
                        )
                      : RefreshIndicator(
                          onRefresh: () async {
                            await Future.wait([
                              controller.refresh(),
                              if (_screen == 0) _loadMarketOverview(),
                              if (chart)
                                controller.loadVolatilityIndex(force: true),
                            ]);
                          },
                          child: SingleChildScrollView(
                            key: ValueKey('screen:$_screen'),
                            controller: _scroll,
                            physics: const AlwaysScrollableScrollPhysics(),
                            child: Align(
                              alignment: Alignment.topCenter,
                              child: _scaled(
                                content,
                                Size(390, designHeight),
                                contentScale,
                              ),
                            ),
                          ),
                        ),
                ),
                _scaled(navNodes, const Size(390, 70), scale),
              ],
            );
          },
        ),
      ),
    );
  }

  Future<void> _changeTestMode(bool enabled) async {
    if (!enabled) {
      controller.setTestMode(false);
      return;
    }
    try {
      final status = await (controller.repository as WorkspaceRepository)
          .workspaceRequest('GET', '/v1/system/status');
      if (!mounted) return;
      if (status['test_mode_available'] == true) {
        controller.setTestMode(true);
      } else {
        _notify('테스트 모드는 서버에서 허용한 날의 장 시작 전에 사용할 수 있습니다.');
      }
    } catch (_) {
      if (mounted) _notify('테스트 모드 사용 가능 여부를 확인하지 못했습니다.');
    }
  }

  Widget _buildOptionsTab() {
    final repo = controller.repository;
    return ListView(
      padding: const EdgeInsets.fromLTRB(24, 24, 24, 24),
      children: [
        Text('더보기', style: Theme.of(context).textTheme.headlineMedium),
        const SizedBox(height: 16),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('TradePilot 시스템'),
          subtitle: const Text('차트 분석 및 주문 전 AI 피드백'),
          value: controller.pilotEnabled,
          onChanged: controller.canEdit ? _changePilot : null,
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('색반전 모드'),
          value: widget.invertedColors,
          onChanged: widget.onInvertedColorsChanged,
        ),
        if (repo is WorkspaceRepository)
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('테스트 모드'),
            subtitle: const Text('장 시작 전 모의 매매 · 입력한 지정가로 체결'),
            value: controller.testMode,
            onChanged: controller.canEdit ? _changeTestMode : null,
          ),
        const Divider(height: 1),
        ListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('모의계좌 관리'),
          subtitle: const Text('모의계좌 및 주문 내역'),
          trailing: const Icon(Icons.chevron_right),
          onTap: _openPaperTradingManagement,
        ),
        ListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('ChatGPT 연결'),
          subtitle: const Text('연결 상태 확인'),
          trailing: const Icon(Icons.chevron_right),
          onTap: () {
            if (repo is! WorkspaceRepository) {
              _notify('서버 연결 모드에서 ChatGPT 연결을 확인할 수 있습니다.');
              return;
            }
            showDialog<void>(
              context: context,
              builder: (context) => AlertDialog(
                title: const Text('ChatGPT 연결'),
                content: SingleChildScrollView(
                  child: ChatGPTConnectionGuide(
                    repository: repo as WorkspaceRepository,
                  ),
                ),
                actions: [
                  TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('닫기'),
                  ),
                ],
              ),
            );
          },
        ),
        const Divider(height: 16),
        for (final target in ChatGPTPromptTarget.values) ...[
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text('${target.label} 프롬프트'),
            subtitle: const Text('현재 프롬프트 보기 및 편집'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () {
              if (repo is! WorkspaceRepository) {
                _notify('서버 연결 모드에서 프롬프트를 설정할 수 있습니다.');
                return;
              }
              Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => ChatGPTPromptScreen(
                    repository: repo as WorkspaceRepository,
                    target: target,
                  ),
                ),
              );
            },
          ),
        ],
      ],
    );
  }

  void _changePilot(bool enabled) {
    if (!controller.canEdit) return;
    controller.setPilot(enabled);
    widget.onPilotChanged?.call(enabled);
  }

  Future<void> _openChatGPTStockAnalysis() async {
    final repo = controller.repository;
    final symbol = controller.selectedSymbol;
    if (!controller.pilotEnabled ||
        repo is! WorkspaceRepository ||
        symbol == null) {
      return;
    }
    if (controller.marketAnalysisStatus == null) {
      await controller.refreshMarketAnalysis();
      if (!mounted ||
          !controller.pilotEnabled ||
          controller.selectedSymbol != symbol) {
        return;
      }
    }
    final name = controller.selectedName;
    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(name),
        insetPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 24),
        contentPadding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
        content: SizedBox(
          width: 440,
          child: SingleChildScrollView(
            child: ChatGPTAnalysisPanel.decision(
              repository: repo as WorkspaceRepository,
              decisionPath:
                  '/v1/market/${Uri.encodeComponent(symbol)}/ai-analysis',
              decisionTitle: 'ChatGPT 시세 분석',
              autoGenerate: false,
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('닫기'),
          ),
        ],
      ),
    );
    if (mounted && controller.selectedSymbol == symbol) {
      await controller.refreshMarketAnalysis();
    }
  }

  Widget _buildStockBalanceTab() {
    final repo = controller.repository;
    return StockBalanceScreen(
      repository: repo is WorkspaceRepository
          ? repo as WorkspaceRepository
          : null,
      onManage: _showPaperAccountSummary,
      onSelectSymbol: _openStockChart,
    );
  }

  void _openStockChart(String symbol) {
    unawaited(controller.select(symbol));
    _navigate(symbol == '000660' ? 8 : 1);
  }

  Widget _scaled(List<DesignNode> nodes, Size size, double scale) => SizedBox(
    width: size.width * scale,
    height: size.height * scale,
    child: FittedBox(
      alignment: Alignment.topLeft,
      fit: BoxFit.fill,
      child: DesignCanvas(
        document: _document!,
        nodes: nodes,
        size: size,
        onAction: _onAction,
        replacement: _replaceChartAndSearchWidgets,
      ),
    ),
  );

  Widget _buildOrderEntryPopup() {
    final root = _boundScreen(_overlay!);
    final panel = children(root).firstWhere((n) => n['name'] == 'Popup panel');
    return Positioned.fill(
      child: Stack(
        children: [
          Positioned.fill(
            child: GestureDetector(
              key: const ValueKey('close-overlay'),
              onTap: _locked ? null : () => setState(() => _overlay = null),
              child: ColoredBox(
                color: const Color(0xFF0A0A0B).withValues(alpha: .76),
              ),
            ),
          ),
          SafeArea(
            top: true,
            bottom: false,
            child: Align(
              alignment: Alignment.bottomCenter,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 520),
                child: LayoutBuilder(
                  builder: (context, constraints) {
                    final scale = constraints.maxWidth / 390;
                    final keyboard = MediaQuery.viewInsetsOf(context).bottom;
                    final height = number(panel, 'h');
                    return Padding(
                      padding: EdgeInsets.only(bottom: keyboard),
                      child: Container(
                        color: _document!.color('panel'),
                        height: math.min(
                          height * scale,
                          constraints.maxHeight - keyboard,
                        ),
                        child: SingleChildScrollView(
                          child: _scaled(
                            children(panel),
                            Size(390, height),
                            scale,
                          ),
                        ),
                      ),
                    );
                  },
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget? _replaceChartAndSearchWidgets(DesignNode node) {
    if (node['name'] == 'Login return') {
      final logout = widget.onLogout;
      if (logout == null) return const SizedBox.shrink();
      return Align(
        alignment: Alignment.centerRight,
        child: TextButton(
          onPressed: _locked
              ? null
              : () async {
                  setState(() => _actionPending = true);
                  try {
                    await logout();
                  } finally {
                    if (mounted) setState(() => _actionPending = false);
                  }
                },
          style: TextButton.styleFrom(
            padding: EdgeInsets.zero,
            textStyle: const TextStyle(fontSize: 11),
            foregroundColor: _document!.color('muted'),
          ),
          child: const Text('로그인 화면으로'),
        ),
      );
    }
    if (node['name'] == 'Market indices') {
      return MarketOverviewStrip(
        design: _document!,
        items: _marketOverview,
        connected: controller.repository is WorkspaceRepository,
        loading: _marketOverviewLoading,
      );
    }
    if (node['name'] == 'Chart stock details') {
      return ListView(
        scrollDirection: Axis.horizontal,
        children: [
          for (final section in ChartDetail.values)
            Semantics(
              selected: section == _chartDetail,
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 150),
                margin: EdgeInsets.only(
                  top: section == _chartDetail ? 0 : 7,
                  right: 2,
                ),
                decoration: BoxDecoration(
                  color: section == _chartDetail
                      ? _document!.color('panel')
                      : Colors.transparent,
                  borderRadius: const BorderRadius.vertical(
                    top: Radius.circular(7),
                  ),
                ),
                child: TextButton(
                  style: TextButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    minimumSize: const Size(44, 42),
                    foregroundColor: _document!.color(
                      section == _chartDetail ? 'fg' : 'muted',
                    ),
                    textStyle: const TextStyle(fontSize: 12),
                  ),
                  onPressed: () {
                    if (section != _chartDetail) {
                      setState(() => _chartDetail = section);
                    }
                  },
                  child: Text(section.label),
                ),
              ),
            ),
        ],
      );
    }
    if (node['name'] == 'Chart tab content') {
      final symbol = controller.selectedSymbol;
      final repository = controller.repository;
      final content = _chartDetail == ChartDetail.chart
          ? DesignCanvas(
              document: _document!,
              nodes: children(node),
              size: Size(number(node, 'w'), number(node, 'h')),
              onAction: _onAction,
              replacement: _replaceChartAndSearchWidgets,
            )
          : Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24),
              child: symbol == null || repository is! WorkspaceRepository
                  ? const Text('종목을 선택해 주세요.')
                  : ChartStockDetails(
                      key: ValueKey((symbol, _chartDetail)),
                      repository: repository as WorkspaceRepository,
                      symbol: symbol,
                      initial: _chartDetail,
                    ),
            );
      return TweenAnimationBuilder<double>(
        key: ValueKey(_chartDetail),
        tween: Tween(begin: 0.15, end: 1),
        duration: MediaQuery.disableAnimationsOf(context)
            ? Duration.zero
            : const Duration(milliseconds: 170),
        child: content,
        builder: (context, opacity, child) =>
            Opacity(opacity: opacity, child: child),
      );
    }
    if (node['name'] == 'Chart daily change') {
      final current = controller.chartDisplayQuote?.priceWon;
      final previous = controller.previousCloseWon;
      if (current == null || previous == null || previous <= 0) {
        return const SizedBox.shrink();
      }
      final delta = current - previous;
      final color = delta > 0
          ? const Color(0xFFE85B5B)
          : delta < 0
          ? const Color(0xFF5E8EFF)
          : const Color(0xFFA1A1A6);
      final sign = delta > 0
          ? '+'
          : delta < 0
          ? '-'
          : '';
      return Text.rich(
        TextSpan(
          children: [
            const TextSpan(
              text: '전일 대비 ',
              style: TextStyle(color: Color(0xFFA1A1A6)),
            ),
            TextSpan(
              text:
                  '$sign${won(delta.abs())}원 ($sign${(delta.abs() / previous * 100).toStringAsFixed(2)}%)',
              style: TextStyle(color: color, fontWeight: FontWeight.w600),
            ),
          ],
        ),
        style: const TextStyle(fontSize: 14),
      );
    }
    if (node['name'] == 'Candlestick chart' &&
        controller.repository is WorkspaceRepository) {
      return StockPriceChart(
        data: controller.candleData,
        seriesKey: controller.selectedSymbol,
        interval: controller.candleInterval,
        liveQuote: controller.chartQuoteLive ? controller.chartTrade : null,
        onIntervalChanged: (interval) =>
            unawaited(controller.loadCandles(interval)),
        interactive: true,
        invertedColors: widget.invertedColors,
      );
    }
    if (node['name'] == 'Segment navigation' &&
        (_screen == 1 || _screen == 8 || _pretradeLocation) &&
        controller.repository is WorkspaceRepository) {
      return ChartVolatilityIndex(volatilityIndex: controller.volatilityIndex);
    }
    if (node['name'] != 'Search field') return null;
    final decorations = children(
      node,
    ).where((n) => n['type'] != 'text').toList();
    return Stack(
      children: [
        DesignCanvas(
          document: _document!,
          nodes: decorations,
          size: Size(number(node, 'w'), number(node, 'h')),
          onAction: (_) {},
        ),
        Positioned(
          left: 43,
          right: 12,
          top: 0,
          bottom: 0,
          child: Center(
            child: TextField(
              key: const ValueKey('stock-search'),
              controller: _search,
              style: TextStyle(
                fontFamily: designFont,
                fontSize: 14,
                color: _document!.color('fg'),
              ),
              decoration: const InputDecoration(
                hintText: '종목명 또는 코드',
                filled: false,
                border: InputBorder.none,
                enabledBorder: InputBorder.none,
                focusedBorder: InputBorder.none,
                contentPadding: EdgeInsets.zero,
                isDense: true,
              ),
              textAlignVertical: TextAlignVertical.center,
              onChanged: (_) => setState(() {}),
              onSubmitted: (_) => FocusScope.of(context).unfocus(),
            ),
          ),
        ),
      ],
    );
  }

  void _notify(String message) {
    ScaffoldMessenger.of(context).hideCurrentSnackBar();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        behavior: SnackBarBehavior.floating,
        margin: EdgeInsets.fromLTRB(
          16,
          16,
          16,
          MediaQuery.paddingOf(context).bottom + 82,
        ),
      ),
    );
  }

  void _navigate(int index) {
    FocusScope.of(context).unfocus();
    setState(() {
      _screen = index;
      _chartDetail = ChartDetail.chart;
      _overlay = null;
    });
    controller.setChartAnalysisVisible(index == 1 || index == 8);
    if (_scroll.hasClients) _scroll.jumpTo(0);
    if (index == 6) unawaited(controller.loadDiscovery(force: true));
    if (index == 0) unawaited(_loadMarketOverview());
  }

  Future<void> _onAction(DesignNode node) async {
    if (_locked) return;
    final name = node['name'] as String? ?? '';
    final action = node['action'] as String?;
    final target = node['target'] as int?;
    if (name == 'Tab / 발견') {
      _navigate(6);
      return;
    }
    if (action == 'CLOSE') {
      FocusScope.of(context).unfocus();
      setState(() => _overlay = null);
      return;
    }
    if (action == 'WORKSPACE') {
      await _openPaperTradingManagement(1);
      return;
    }
    if (action == 'PLANS') {
      await _openPaperTradingManagement(2);
      return;
    }
    if (action == 'ACCOUNT') {
      await _showPaperAccountSummary();
      return;
    }
    if (action == 'UNAVAILABLE') {
      await _openPaperTradingManagement();
      return;
    }
    if (action == 'SELECT_SYMBOL') {
      final symbol = node['symbol'] as String;
      unawaited(controller.select(symbol));
      _navigate(symbol == '000660' ? 8 : 1);
      return;
    }
    if (action == 'SEGMENT') {
      final index = node['index'] as int;
      if (_screen == 3 && index != 0) {
        if (index == 1) {
          await _openPaperTradingManagement(2);
        } else {
          final repo = controller.repository;
          if (repo is WorkspaceRepository) {
            await Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => StrategyBacktestScreen(
                  repository: repo as WorkspaceRepository,
                ),
              ),
            );
          } else {
            _notify('전략·백테스트는 서버 연결 모드에서 사용할 수 있습니다.');
          }
        }
        return;
      }
      setState(() => _segments[_screen] = index);
      if (_screen == 1 || _screen == 8) {
        await controller.loadCandles(['1m', '5m', '15m', '1h', '1d'][index]);
      }
      return;
    }
    if (action == 'EDIT_PRICE' || action == 'EDIT_QUANTITY') {
      await _editNumber(action == 'EDIT_PRICE');
      return;
    }
    if (action == 'PILOT') {
      _changePilot(!controller.pilotEnabled);
      return;
    }
    if (action == 'AI_DETAILS') {
      if (!controller.pilotEnabled) return;
      if (controller.repository is WorkspaceRepository) {
        await _openChatGPTStockAnalysis();
      } else {
        await _openPilotAiDetails();
      }
      return;
    }
    if (action == 'CHECK_DETAILS') {
      await _checkDetails();
      return;
    }
    if (action == 'JOURNAL') {
      _navigate(4);
      return;
    }
    if (action == 'RECOVER') {
      await _recoverPendingOrder();
      return;
    }
    if (name.startsWith('Quantity / ')) {
      if (!controller.canEdit) return;
      controller.resetOrder();
      setState(
        () =>
            _quantity = (name.endsWith('plus') ? _quantity + 1 : _quantity - 1)
                .clamp(1, 1000000),
      );
      return;
    }
    if (name == '매수' || name == '매도') {
      await _openOrder(name == '매수' ? OrderSide.buy : OrderSide.sell);
      return;
    }
    if (name == '매수 주문 확인' || name == '매도 주문 확인') {
      await _checkOrderBeforeConfirmation();
      return;
    }
    if (name.startsWith('모의 ') &&
        (name.contains('접수') || name.contains('확인'))) {
      await _submitOrder();
      return;
    }
    if (name.startsWith('모의주문 확인으로')) {
      _legacyOrder = true;
      _side = OrderSide.buy;
      _quantity = 10;
      _price = controller.selected?.priceWon ?? 0;
      await _checkOrderBeforeConfirmation();
      return;
    }
    if (target == 7 || target == 9) {
      _search.clear();
      setState(() => _overlay = 7);
      return;
    }
    if (target == 1 || target == 8) {
      if (name == 'Tab / 차트' || name == 'Back' || name == '차트로 돌아가기') {
        _navigate(_chart);
        return;
      }
      unawaited(controller.select(target == 8 ? '000660' : '005930'));
      _navigate(target!);
      return;
    }
    if (target == 2) {
      if (!controller.canEdit) {
        await _recoverPendingOrder();
        return;
      }
      await controller.select('005930');
      if (mounted) _navigate(2);
      return;
    }
    if (target != null &&
        {0, 3, 4, 6, TradingLayoutBindings.optionsTab}.contains(target)) {
      _navigate(target);
    }
  }

  Future<void> _openOrder(OrderSide side) async {
    if (!controller.canEdit) {
      await _recoverPendingOrder();
      return;
    }
    if ((!controller.online && !controller.testMode) ||
        !controller.orderQuoteAvailable) {
      _notify('최신 시세가 연결된 후 주문할 수 있습니다. 아래로 당겨 새로고침하세요.');
      return;
    }
    controller.resetOrder();
    setState(() {
      _legacyOrder = false;
      _side = side;
      _quantity = 1;
      _price = controller.selected?.priceWon ?? 0;
      _overlay = _orderBase + 2;
    });
  }

  Future<void> _checkOrderBeforeConfirmation() async {
    if (!controller.canEdit) {
      await _recoverPendingOrder();
      return;
    }
    setState(() => _actionPending = true);
    try {
      await controller.prepare(_side, _quantity, _price);
      if (!mounted) return;
      setState(() => _actionPending = false);
      if (controller.stage == OrderStage.ready) {
        _navigate(_legacyOrder ? 5 : _orderBase + 1);
      } else if (controller.stage == OrderStage.blocked) {
        if (controller.repository is WorkspaceRepository) {
          _navigate(_legacyOrder ? 5 : _orderBase + 1);
        } else {
          await _checkDetails();
        }
      } else {
        _notify(controller.error ?? '주문을 점검할 수 없습니다.');
      }
    } catch (_) {
      if (mounted) _notify('주문 확인을 불러오지 못했습니다. 다시 시도하세요.');
    } finally {
      if (mounted) setState(() => _actionPending = false);
    }
  }

  Future<void> _submitOrder({bool inlineConfirmed = false}) async {
    if (controller.stage != OrderStage.ready &&
        controller.stage != OrderStage.uncertain) {
      await _checkOrderBeforeConfirmation();
      return;
    }
    if (!inlineConfirmed &&
        controller.stage == OrderStage.ready &&
        (controller.check!.requiresAck ||
            controller.repository is WorkspaceRepository)) {
      final activeCheck = controller.check!;
      final repository = controller.repository;
      final answer = await showDialog<Map<String, dynamic>>(
        context: context,
        builder: (_) => OrderRiskCheckDialog(
          check: activeCheck,
          draft: controller.draft,
          onPresented: repository is WorkspaceRepository
              ? () {
                  unawaited(
                    (repository as WorkspaceRepository)
                        .workspaceRequest(
                          'POST',
                          '/v1/orders/check/${activeCheck.id}/presented',
                        )
                        .then<void>((_) {})
                        .catchError((Object _) {
                          if (mounted) {
                            _notify(
                              '화면 표시 기록을 저장하지 못했습니다. 확인 시간 집계에서 제외될 수 있습니다.',
                            );
                          }
                        }),
                  );
                }
              : null,
        ),
      );
      if (!mounted) return;
      if (answer == null || answer['deferred'] == true) {
        final repo = controller.repository;
        if (answer?['deferred'] == true && repo is WorkspaceRepository) {
          try {
            await (repo as WorkspaceRepository).workspaceRequest(
              'POST',
              '/v1/orders/check/${controller.check!.id}/dismiss',
              body: {'reason': answer?['reason'] ?? ''},
            );
          } catch (_) {
            if (mounted) _notify('보류 기록 저장을 확인하지 못했습니다.');
          }
        }
        controller.resetOrder();
        return;
      }
      controller.acknowledgeWarning(
        answer['reason'] as String,
        answer['high'] as bool,
      );
    }
    setState(() => _actionPending = true);
    try {
      await controller.submit();
      if (!mounted) return;
      setState(() => _actionPending = false);
      if (controller.stage == OrderStage.completed) {
        _navigate(_legacyOrder ? 34 : _orderBase);
        if (controller.receipt?.status == 'rejected' &&
            controller.receipt?.reason != null) {
          await _message('주문 차단 사유', controller.receipt!.reason!);
        }
      } else if (controller.stage == OrderStage.uncertain) {
        await _message(
          '주문 결과 미확인',
          controller.error ?? '계정 메뉴에서 동일 주문의 결과를 재확인하세요.',
        );
      }
    } finally {
      if (mounted) setState(() => _actionPending = false);
    }
  }

  Future<void> _recoverPendingOrder() async {
    if (controller.recoveryBlocked) {
      await _message(
        '주문 복구 필요',
        '저장된 주문 기록을 읽을 수 없어 새 주문이 잠겨 있습니다. 저장소와 로그인 계정을 확인하세요.',
      );
      return;
    }
    final draft = controller.draft;
    if (controller.stage != OrderStage.uncertain || draft == null) return;
    _side = draft.side;
    _quantity = draft.quantity;
    _price = draft.limitPriceWon;
    await controller.select(draft.symbol);
    if (!mounted) return;
    final retry = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('미확인 주문 복구'),
        content: Text('${draft.symbol} · $_quantity주\n기존 주문 식별자로 결과를 재확인합니다.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('닫기'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('동일 주문 결과 재확인'),
          ),
        ],
      ),
    );
    if (retry == true && mounted) await _submitOrder();
  }

  Future<void> _editNumber(bool price) async {
    if (!controller.canEdit) return;
    final value = await showDialog<int>(
      context: context,
      builder: (context) =>
          _NumberInputDialog(price: price, initial: price ? _price : _quantity),
    );
    if (value != null && mounted) {
      controller.resetOrder();
      setState(() {
        if (price) {
          _price = value;
        } else {
          _quantity = value;
        }
      });
    }
  }

  Future<void> _openPilotAiDetails() async {
    await controller.refreshPrediction();
    if (!mounted) return;
    final p = controller.prediction;
    String pct(double n) => '${(n * 100).toStringAsFixed(1)}%';
    await _message(
      'PILOT AI · 데모',
      p == null
          ? 'ChatGPT 시세 분석은 서버 연결 모드에서 사용할 수 있습니다.'
          : '데모 예시\n상승 ${pct(p.up)} · 중립 ${pct(p.neutral)} · 하락 ${pct(p.down)}',
    );
  }

  Future<void> _checkDetails() => _message(
    controller.check?.allowed == true ? '주문 점검 통과' : '주문 점검 결과',
    controller.check?.messages.join('\n\n') ?? '점검 결과가 없습니다.',
  );

  Future<void> _message(String title, String message) => showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(title),
      content: SingleChildScrollView(child: Text(message)),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('닫기'),
        ),
      ],
    ),
  );

  Future<void> _openPaperTradingManagement([int tab = 0]) async {
    final repo = controller.repository;
    if (repo is! WorkspaceRepository) {
      _notify('계좌·체결 관리는 서버 연결 모드에서 사용할 수 있습니다.');
      return;
    }
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => PaperTradingManagementScreen(
          repository: repo as WorkspaceRepository,
          initialTab: tab,
        ),
      ),
    );
    if (mounted) await controller.refresh();
  }

  Future<void> _showPaperAccountSummary() async {
    final action = await showModalBottomSheet<String>(
      context: context,
      useSafeArea: true,
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                '나의 모의투자 계좌',
                style: TextStyle(fontSize: 23, fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 16),
              Text(controller.online ? '시세 연결됨 · 모의투자' : '시세 연결 대기'),
              OutlinedButton(
                onPressed: () => Navigator.pop(context, 'workspace'),
                child: const Text('계좌 · 관심종목 · 매매 계획 · 주문 관리'),
              ),
              const SizedBox(height: 16),
              OutlinedButton(
                onPressed: () => Navigator.pop(context, 'refresh'),
                child: const Text('데이터 새로고침'),
              ),
              if (controller.repository is WorkspaceRepository)
                OutlinedButton(
                  onPressed: () => Navigator.pop(context, 'status'),
                  child: const Text('서버 · 데이터 연결 상태'),
                ),
              if (controller.stage == OrderStage.uncertain ||
                  controller.recoveryBlocked)
                OutlinedButton(
                  onPressed: () => Navigator.pop(context, 'recover'),
                  child: const Text('미확인 주문 복구'),
                ),
              if (widget.onLogout != null)
                OutlinedButton(
                  onPressed: () => Navigator.pop(context, 'logout'),
                  child: const Text('로그아웃 / 다시 로그인'),
                ),
            ],
          ),
        ),
      ),
    );
    if (!mounted) return;
    if (action == 'status') {
      try {
        final data = await (controller.repository as WorkspaceRepository)
            .workspaceRequest('GET', '/v1/system/status');
        if (mounted) {
          await _message(
            '서버 · 데이터 상태',
            '거래 방식: 모의투자\n시세: ${data['market_data_mode'] == 'demo'
                    ? '테스트 생성 데이터'
                    : data['market_data_mode'] == 'toss'
                    ? '토스증권 Open API · ${data['market_feed']?['message'] ?? '연결 대기'}'
                    : data['market_data_mode'] == 'namuh'
                    ? '나무 PLUG KRX · ${data['market_feed']?['message'] ?? '연결 대기'}'
                    : data['market_data_mode'] == 'kis'
                    ? '한국투자증권 KRX · ${data['market_feed']?['message'] ?? '연결 대기'}'
                    : '외부 시세 연결 대기'}\n'
                '체결 워커: ${data['worker_enabled'] == true ? '사용 설정됨' : '꺼짐'}\n'
                '서버 주문 정지: ${data['orders_halted'] == true ? '정지' : '해제'}\n'
                'AI 모델: ${data['model_configured'] == true ? '설정됨 · 종목별 품질/시세 검사 필요' : 'CSV 학습 대기'}\n'
                '실계좌 연결: 미연결',
          );
        }
      } catch (_) {
        if (mounted) _notify('서버 상태를 확인하지 못했습니다.');
      }
    }
    if (action == 'workspace') await _openPaperTradingManagement();
    if (action == 'refresh') await controller.refresh();
    if (action == 'recover') await _recoverPendingOrder();
    if (action == 'logout') await widget.onLogout?.call();
  }
}

class _NumberInputDialog extends StatefulWidget {
  const _NumberInputDialog({required this.price, required this.initial});
  final bool price;
  final int initial;
  @override
  State<_NumberInputDialog> createState() => _NumberInputDialogState();
}

class _NumberInputDialogState extends State<_NumberInputDialog> {
  late final _input = TextEditingController(text: '${widget.initial}');
  String? _error;
  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  void _accept() {
    final value = int.tryParse(_input.text);
    final maximum = widget.price ? 1000000000 : 1000000;
    if (value == null || value <= 0 || value > maximum) {
      setState(() => _error = '1~${won(maximum)} 사이의 정수를 입력하세요.');
      return;
    }
    Navigator.pop(context, value);
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text(widget.price ? '지정가 (원)' : '수량 (주)'),
    content: TextField(
      controller: _input,
      autofocus: true,
      keyboardType: TextInputType.number,
      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
      decoration: InputDecoration(errorText: _error),
      onSubmitted: (_) => _accept(),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('취소'),
      ),
      TextButton(onPressed: _accept, child: const Text('적용')),
    ],
  );
}
