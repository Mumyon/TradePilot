import 'replay_screen.dart';
import 'backtest_screen.dart';
import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/design/design_document.dart';
import '../domain/models.dart';
import '../domain/workspace_repository.dart';
import 'workspace_screen.dart';
import 'market_chart.dart';
import 'risk_confirmation.dart';
import 'journal_screen.dart';
import '../domain/pending_order_store.dart';
import '../domain/trading_repository.dart' as domain;
import 'design_bindings.dart';
import 'trading_controller.dart';

class TradingScreen extends StatefulWidget {
  const TradingScreen({
    super.key,
    required this.repositoryFactory,
    this.onLogout,
    this.pendingOrders,
  });
  final domain.TradingRepository Function() repositoryFactory;
  final Future<void> Function()? onLogout;
  final PendingOrderStore? pendingOrders;
  @override
  State<TradingScreen> createState() => _TradingScreenState();
}

class _TradingScreenState extends State<TradingScreen>
    with WidgetsBindingObserver {
  late final TradingController controller;
  final _search = TextEditingController();
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

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    controller = TradingController(
      widget.repositoryFactory(),
      pendingOrders: widget.pendingOrders,
    );
    controller.addListener(_controllerChanged);
    unawaited(controller.start());
    unawaited(_loadDesign());
  }

  Future<void> _loadDesign() async {
    try {
      final document = await DesignDocument.load();
      if (mounted) setState(() => _document = document);
    } catch (_) {
      if (mounted) setState(() => _loadError = '디자인을 불러오지 못했습니다. 앱을 다시 실행하세요.');
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
    } else if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached) {
      unawaited(controller.pause());
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
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

  DesignNode _boundScreen(int index) {
    final root = _document!.screen(index);
    DesignBindings(
      controller,
      screen: index,
      quantity: _quantity,
      price: _price,
      side: _side,
      query: _search.text.trim(),
      segment: _segments[index] ?? 0,
    ).apply(root);
    return root;
  }

  @override
  Widget build(BuildContext context) => AnnotatedRegion<SystemUiOverlayStyle>(
    value: SystemUiOverlayStyle.light,
    child: ListenableBuilder(
      listenable: controller,
      builder: (context, _) => PopScope(
        canPop: _overlay == null && _screen == 0 && !_locked,
        onPopInvokedWithResult: (didPop, _) {
          if (!didPop && !_locked) {
            if (_overlay != null) {
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
                    SafeArea(child: _page()),
                    if (_overlay != null) _popup(),
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

  Widget _page() {
    final root = _boundScreen(_screen);
    final all = children(root);
    final nav = all.firstWhere((n) => n['name'] == 'Bottom navigation');
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
            final contentScale = contentHeight >= 600
                ? math.min(scale, contentHeight / 707)
                : scale;
            return Column(
              children: [
                Expanded(
                  child: RefreshIndicator(
                    onRefresh: controller.refresh,
                    child: SingleChildScrollView(
                      key: ValueKey('screen:$_screen'),
                      controller: _scroll,
                      physics: const AlwaysScrollableScrollPhysics(),
                      child: Align(
                        alignment: Alignment.topCenter,
                        child: _scaled(
                          content,
                          Size(390, math.max(707, number(root, 'h') - 137)),
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
        replacement: _replacement,
      ),
    ),
  );

  Widget _popup() {
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

  Widget? _replacement(DesignNode node) {
    if (node['name'] == 'Candlestick chart' &&
        controller.repository is WorkspaceRepository) {
      return MarketChart(data: controller.candleData);
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
      _overlay = null;
    });
    if (_scroll.hasClients) _scroll.jumpTo(0);
  }

  Future<void> _onAction(DesignNode node) async {
    if (_locked) return;
    final name = node['name'] as String? ?? '';
    final action = node['action'] as String?;
    final target = node['target'] as int?;
    if (name == 'Tab / 자동매매') {
      final repo = controller.repository;
      if (repo is WorkspaceRepository) {
        await Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => ReplayScreen(
              repository: repo as WorkspaceRepository,
              onLegacy: () {
                if (mounted) _navigate(3);
              },
            ),
          ),
        );
      } else {
        _navigate(3);
        _notify('과거 장세 모의투자는 서버 연결 모드에서 사용할 수 있습니다.');
      }
      return;
    }
    if (action == 'CLOSE') {
      FocusScope.of(context).unfocus();
      setState(() => _overlay = null);
      return;
    }
    if (action == 'WORKSPACE') {
      await _workspace(2);
      return;
    }
    if (action == 'PLANS') {
      await _workspace(3);
      return;
    }
    if (action == 'ACCOUNT') {
      await _account();
      return;
    }
    if (action == 'UNAVAILABLE') {
      await _workspace(1);
      return;
    }
    if (action == 'SELECT_SYMBOL') {
      await controller.select(node['symbol'] as String);
      if (mounted) _navigate(1);
      return;
    }
    if (action == 'SEGMENT') {
      final index = node['index'] as int;
      if (_screen == 3 && index != 0) {
        if (index == 1) {
          await _workspace(3);
        } else {
          final repo = controller.repository;
          if (repo is WorkspaceRepository) {
            await Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) =>
                    BacktestScreen(repository: repo as WorkspaceRepository),
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
      if (_screen == 4) await _journal();
      return;
    }
    if (action == 'EDIT_PRICE' || action == 'EDIT_QUANTITY') {
      await _editNumber(action == 'EDIT_PRICE');
      return;
    }
    if (action == 'PILOT') {
      controller.setPilot(!controller.pilotEnabled);
      return;
    }
    if (action == 'AI_DETAILS') {
      await _aiDetails();
      return;
    }
    if (action == 'CHECK_DETAILS') {
      await _checkDetails();
      return;
    }
    if (action == 'JOURNAL') {
      await _journal();
      return;
    }
    if (action == 'RECOVER') {
      await _recover();
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
      await _prepare();
      return;
    }
    if (name.startsWith('모의 ') &&
        (name.contains('접수') || name.contains('확인'))) {
      await _submit();
      return;
    }
    if (name.startsWith('모의주문 확인으로')) {
      _legacyOrder = true;
      _side = OrderSide.buy;
      _quantity = 10;
      _price = controller.selected?.priceWon ?? 0;
      await _prepare();
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
      await controller.select(target == 8 ? '000660' : '005930');
      if (mounted) _navigate(target!);
      return;
    }
    if (target == 2) {
      if (!controller.canEdit) {
        await _recover();
        return;
      }
      await controller.select('005930');
      if (mounted) _navigate(2);
      return;
    }
    if (target != null && {0, 3, 4, 6}.contains(target)) _navigate(target);
  }

  Future<void> _openOrder(OrderSide side) async {
    if (!controller.canEdit) {
      await _recover();
      return;
    }
    if (!controller.online || !controller.quoteFresh) {
      _notify('최신 시세가 연결된 후 주문할 수 있습니다. 아래로 당겨 새로고침하세요.');
      return;
    }
    controller.resetOrder();
    setState(() {
      _legacyOrder = false;
      _side = side;
      _quantity = 1;
      _price = controller.selected!.priceWon;
      _overlay = _orderBase + 2;
    });
  }

  Future<void> _prepare() async {
    if (!controller.canEdit) {
      await _recover();
      return;
    }
    setState(() => _actionPending = true);
    try {
      String? planId;
      final repo = controller.repository;
      if (repo is WorkspaceRepository) {
        final data = await (repo as WorkspaceRepository).workspaceRequest(
          'GET',
          '/v1/plans',
        );
        if (!mounted) return;
        final plans = (data['items'] as List)
            .where(
              (p) =>
                  p['symbol'] == controller.selectedSymbol &&
                  p['side'] == _side.name,
            )
            .toList();
        if (plans.isNotEmpty) {
          final choice = await showDialog<Map<String, dynamic>>(
            context: context,
            builder: (ctx) => SimpleDialog(
              title: const Text('적용할 매매 계획'),
              children: [
                SimpleDialogOption(
                  onPressed: () => Navigator.pop(ctx, <String, dynamic>{}),
                  child: const Text('계획 없이 점검'),
                ),
                for (final p in plans)
                  SimpleDialogOption(
                    onPressed: () =>
                        Navigator.pop(ctx, p as Map<String, dynamic>),
                    child: Text(
                      '${p['entry_condition']}\n최대 ${p['max_amount_won']}원 · ${p['created_at']}',
                    ),
                  ),
              ],
            ),
          );
          if (choice == null) return;
          planId = choice['id'] as String?;
        }
      }
      await controller.prepare(_side, _quantity, _price, planId: planId);
      if (!mounted) return;
      setState(() => _actionPending = false);
      if (controller.stage == OrderStage.ready) {
        _navigate(_legacyOrder ? 5 : _orderBase + 1);
      } else if (controller.stage == OrderStage.blocked) {
        await _checkDetails();
      } else {
        _notify(controller.error ?? '주문을 점검할 수 없습니다.');
      }
    } catch (_) {
      if (mounted) _notify('매매 계획 또는 주문 점검을 불러오지 못했습니다. 다시 시도하세요.');
    } finally {
      if (mounted) setState(() => _actionPending = false);
    }
  }

  Future<void> _submit() async {
    if (controller.stage != OrderStage.ready &&
        controller.stage != OrderStage.uncertain) {
      await _prepare();
      return;
    }
    if (controller.stage == OrderStage.ready &&
        (controller.check!.requiresAck ||
            controller.repository is WorkspaceRepository)) {
      final activeCheck = controller.check!;
      final repository = controller.repository;
      final answer = await showDialog<Map<String, dynamic>>(
        context: context,
        builder: (_) => RiskConfirmation(
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

  Future<void> _recover() async {
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
    if (retry == true && mounted) await _submit();
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

  Future<void> _aiDetails() async {
    await controller.refreshPrediction();
    if (!mounted) return;
    final p = controller.predictionData;
    if (p == null || p['status'] != 'available') {
      await _message(
        'AI 모델 학습 대기',
        p?['message'] as String? ?? '분석 데이터를 준비하고 있습니다.',
      );
      return;
    }
    String pct(dynamic n) => '${((n as num) * 100).toStringAsFixed(1)}%';
    final e = p['evaluation'] as Map<String, dynamic>;
    final test = e['test'] as Map<String, dynamic>;
    final base = e['baseline'] as Map<String, dynamic>;
    await _message(
      'AI 방향 확률 · 검증 결과',
      '상승 ${pct(p['up'])} / 중립 ${pct(p['neutral'])} / 하락 ${pct(p['down'])}\n'
          '최고 확률 65% 미만은 방향 판단 보류\n'
          '기준 ${p['as_of']}\n대상 ${p['target_at']}\n모델 ${p['model_version']}\n\n'
          '시험 기간 ${test['start']} ~ ${test['end']}\n표본 ${test['samples']}개\n'
          '방향 정확도 ${pct(test['accuracy'])} · 기준모델 ${pct(base['accuracy'])}\n'
          'Macro F1 ${test['macro_f1']} · Brier ${test['brier']}\n판단 보류 비율 ${pct(test['abstention_rate'])}\n\n'
          '지표 요약: ${p['indicators']}\n\n모델 요인: ${p['model_factors']}\n${p['explanation']}',
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

  Future<void> _workspace([int tab = 0]) async {
    final repo = controller.repository;
    if (repo is! WorkspaceRepository) {
      _notify('계좌·설정·체결 관리는 서버 연결 모드에서 사용할 수 있습니다.');
      return;
    }
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => WorkspaceScreen(
          repository: repo as WorkspaceRepository,
          initialTab: tab,
        ),
      ),
    );
    if (mounted) await controller.refresh();
  }

  Future<void> _account() async {
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
                child: const Text('계좌 · 거래 설정 · 관심종목 관리'),
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
            '거래 방식: 모의투자\n시세: ${data['market_data_mode'] == 'demo' ? '테스트 생성 데이터' : '외부 시세 연결 대기'}\n'
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
    if (action == 'workspace') await _workspace();
    if (action == 'refresh') await controller.refresh();
    if (action == 'recover') await _recover();
    if (action == 'logout') await widget.onLogout?.call();
  }

  Future<void> _journal() async {
    if (controller.repository is WorkspaceRepository) {
      await Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => JournalScreen(
            repository: controller.repository as WorkspaceRepository,
          ),
        ),
      );
      if (mounted) await controller.refresh();
      return;
    }
    await controller.refresh();
    if (!mounted) return;
    await showModalBottomSheet<void>(
      context: context,
      useSafeArea: true,
      isScrollControlled: true,
      builder: (context) => SafeArea(
        child: SizedBox(
          height: MediaQuery.sizeOf(context).height * .7,
          child: ListView(
            padding: const EdgeInsets.all(24),
            children: [
              const Text(
                '전체 주문 내역',
                style: TextStyle(fontSize: 23, fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 24),
              if (controller.journal.isEmpty) const Text('아직 주문 내역이 없습니다.'),
              ...controller.journal.map(
                (o) => ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(controller.market[o.symbol]?.name ?? o.symbol),
                  subtitle: Text(o.id),
                  trailing: Text(orderStatus(o.status)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
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
