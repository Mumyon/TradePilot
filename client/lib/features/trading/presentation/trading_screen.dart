import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../domain/models.dart';
import '../domain/pending_order_store.dart';
import '../domain/trading_repository.dart' as domain;
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
  int _tab = 0;
  final _search = TextEditingController();
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    controller = TradingController(
      widget.repositoryFactory(),
      pendingOrders: widget.pendingOrders,
    );
    unawaited(controller.start());
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
    controller.dispose();
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: controller,
    builder: (context, _) => Scaffold(
      appBar: AppBar(
        title: const Text('TradePilot'),
        actions: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: Chip(
              label: Text(
                controller.repository.isDemo ? '데모 · 가상 데이터' : '서버 · 모의투자',
              ),
            ),
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            if (controller.stage == OrderStage.uncertain)
              TextButton(
                onPressed: () => _openOrder(OrderSide.buy),
                child: const Text('미확인 주문 복원됨 · 결과 재확인'),
              ),
            if (controller.recoveryBlocked)
              const Padding(
                padding: EdgeInsets.all(12),
                child: Text(
                  '미확인 주문 기록을 읽을 수 없어 새 주문을 중지했습니다. 저장소를 확인하고 다시 로그인하세요.',
                ),
              ),
            Container(
              width: double.infinity,
              color: const Color(0xFF1C1C1C),
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
              child: Text(_connectionLabel),
            ),
            if (controller.error != null)
              Padding(
                padding: const EdgeInsets.all(12),
                child: Text(
                  controller.error!,
                  style: const TextStyle(color: Colors.amber),
                ),
              ),
            Expanded(
              child: RefreshIndicator(
                onRefresh: controller.refresh,
                child: ListView(
                  padding: const EdgeInsets.all(20),
                  physics: const AlwaysScrollableScrollPhysics(),
                  children: switch (_tab) {
                    0 => _watchlist(),
                    1 => _detail(),
                    2 => _journal(),
                    _ => _settings(),
                  },
                ),
              ),
            ),
          ],
        ),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (index) => setState(() => _tab = index),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.list_alt), label: '관심종목'),
          NavigationDestination(
            icon: Icon(Icons.candlestick_chart),
            label: '종목·AI',
          ),
          NavigationDestination(icon: Icon(Icons.book_outlined), label: '매매일지'),
          NavigationDestination(icon: Icon(Icons.tune), label: '설정'),
        ],
      ),
    ),
  );

  String get _connectionLabel => switch (controller.connection) {
    domain.ConnectionState.connected =>
      controller.repository.isDemo ? '데모 스트림 실행 중 · 실제 시세가 아닙니다' : '시세 연결됨',
    domain.ConnectionState.connecting => '시세 연결 중',
    domain.ConnectionState.reconnecting => '재연결 중 · 신규 주문 대기',
    domain.ConnectionState.paused => '백그라운드 연결 일시중지',
    domain.ConnectionState.disconnected => '연결 끊김 · 신규 주문 대기',
  };

  List<Widget> _watchlist() => [
    Text('나의 관심종목', style: Theme.of(context).textTheme.headlineMedium),
    const SizedBox(height: 20),
    TextField(
      controller: _search,
      onChanged: (_) => setState(() {}),
      decoration: const InputDecoration(
        prefixIcon: Icon(Icons.search),
        labelText: '관심종목 내 이름 또는 코드 검색',
      ),
    ),
    const SizedBox(height: 20),
    if (controller.loading) const LinearProgressIndicator(),
    if (controller.market.isEmpty && !controller.loading)
      const Text('표시할 종목이 없습니다. 아래로 당겨 새로고침하세요.'),
    ...controller.market.values
        .where(
          (q) =>
              q.name.contains(_search.text.trim()) ||
              q.symbol.contains(_search.text.trim()),
        )
        .map(
          (quote) => Card(
            child: ListTile(
              title: Text(quote.name),
              subtitle: Text('${quote.symbol} · ${_time(quote.asOf)}'),
              trailing: Text('${_won(quote.priceWon)}원'),
              onTap: () {
                unawaited(controller.select(quote.symbol));
                setState(() => _tab = 1);
              },
            ),
          ),
        ),
  ];

  List<Widget> _detail() {
    final quote = controller.selected;
    final prediction = controller.prediction;
    final validPrediction =
        prediction != null &&
        DateTime.now().toUtc().isBefore(prediction.validUntil);
    return [
      if (quote == null)
        const Text('관심종목에서 종목을 선택하세요.')
      else ...[
        Text(quote.name, style: Theme.of(context).textTheme.headlineMedium),
        Text('${quote.symbol} · KRX'),
        const SizedBox(height: 16),
        Text(
          '${_won(quote.priceWon)}원',
          style: Theme.of(context).textTheme.displaySmall,
        ),
        Text(
          '기준 ${_time(quote.asOf)} · ${controller.quoteFresh ? '최신' : '지연 시세'}',
        ),
        const SizedBox(height: 24),
        const Card(
          child: Padding(
            padding: EdgeInsets.all(24),
            child: Column(
              children: [
                Icon(Icons.candlestick_chart, size: 48),
                SizedBox(height: 12),
                Text('캔들 차트 연결 영역'),
                Text(
                  'OHLCV API·차트 라이브러리 선정 후 연결합니다. 실제 차트는 아직 없습니다.',
                  textAlign: TextAlign.center,
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('PILOT AI · 다음 1시간'),
                const SizedBox(height: 12),
                Text(
                  validPrediction ? prediction.direction : '분석 불가 / 예측 만료',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                if (validPrediction) ...[
                  const SizedBox(height: 12),
                  Text(
                    '상승 ${(prediction.up * 100).round()}% · 중립 ${(prediction.neutral * 100).round()}% · 하락 ${(prediction.down * 100).round()}%',
                  ),
                  Text(
                    '생성 ${_time(prediction.generatedAt)} · ${prediction.modelVersion}',
                  ),
                  const Text('예측 확률은 과거 검증 성능과 다릅니다.'),
                ],
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        if (controller.stage == OrderStage.uncertain)
          FilledButton(
            onPressed: () => _openOrder(OrderSide.buy),
            child: const Text('미확인 주문 결과 확인'),
          )
        else
          Row(
            children: [
              Expanded(
                child: FilledButton(
                  onPressed: controller.online && controller.quoteFresh
                      ? () => _openOrder(OrderSide.buy)
                      : null,
                  child: const Text('모의 매수'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: OutlinedButton(
                  onPressed: controller.online && controller.quoteFresh
                      ? () => _openOrder(OrderSide.sell)
                      : null,
                  child: const Text('모의 매도'),
                ),
              ),
            ],
          ),
      ],
    ];
  }

  List<Widget> _journal() => [
    Text('매매일지', style: Theme.of(context).textTheme.headlineMedium),
    const SizedBox(height: 12),
    const Text('주문 접수와 체결은 구분됩니다. 아래로 당겨 최신 상태를 확인하세요.'),
    const SizedBox(height: 16),
    if (controller.journal.isEmpty) const Text('아직 주문 내역이 없습니다.'),
    ...controller.journal.map(
      (order) => Card(
        child: ListTile(
          title: Text(order.symbol),
          subtitle: Text(order.id),
          trailing: Text(_status(order.status)),
        ),
      ),
    ),
    const SizedBox(height: 24),
    const Text('거래 이유·경고 이력·성과 피드백은 서버 계약 확장 후 연결할 영역입니다.'),
  ];

  List<Widget> _settings() => [
    Text('설정', style: Theme.of(context).textTheme.headlineMedium),
    const SizedBox(height: 16),
    const ListTile(
      title: Text('모의투자 전용'),
      subtitle: Text('실계좌·자동매매는 초기 범위에 포함하지 않습니다.'),
    ),
    const ListTile(
      title: Text('TradePilot ON/OFF'),
      subtitle: Text('주문 창에서 행동 점검을 설정합니다. 잔액·위험한도 검사는 항상 서버에서 수행합니다.'),
    ),
    const ListTile(
      title: Text('데이터 연결'),
      subtitle: Text('REST: 조회·주문 / WebSocket: 시세 / DB: 서버만 접근'),
    ),
    if (widget.onLogout != null)
      OutlinedButton(
        onPressed: controller.busy ? null : widget.onLogout,
        child: const Text('로그아웃 / 다시 로그인'),
      ),
  ];

  Future<void> _openOrder(OrderSide side) async {
    if (controller.stage != OrderStage.uncertain) controller.resetOrder();
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => _OrderSheet(controller: controller, side: side),
    );
  }
}

class _OrderSheet extends StatefulWidget {
  const _OrderSheet({required this.controller, required this.side});
  final TradingController controller;
  final OrderSide side;
  @override
  State<_OrderSheet> createState() => _OrderSheetState();
}

class _OrderSheetState extends State<_OrderSheet> {
  late final _quantity = TextEditingController(
    text: '${widget.controller.draft?.quantity ?? 1}',
  );
  late final _price = TextEditingController(
    text:
        '${widget.controller.draft?.limitPriceWon ?? widget.controller.selected?.priceWon ?? 0}',
  );
  @override
  void dispose() {
    _quantity.dispose();
    _price.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.controller,
    builder: (context, _) {
      final c = widget.controller;
      return PopScope(
        canPop: !c.busy,
        child: Padding(
          padding: EdgeInsets.only(
            left: 24,
            right: 24,
            top: 24,
            bottom: MediaQuery.viewInsetsOf(context).bottom + 24,
          ),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  '모의 ${((c.draft?.side ?? widget.side) == OrderSide.buy) ? '매수' : '매도'} 주문',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: _price,
                  enabled: c.canEdit,
                  keyboardType: TextInputType.number,
                  inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                  onChanged: (_) => c.resetOrder(),
                  decoration: const InputDecoration(labelText: '지정가 (원)'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _quantity,
                  enabled: c.canEdit,
                  keyboardType: TextInputType.number,
                  inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                  onChanged: (_) => c.resetOrder(),
                  decoration: const InputDecoration(labelText: '수량 (주)'),
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('TradePilot 행동 점검'),
                  subtitle: const Text('OFF여도 필수 위험 검사는 유지됩니다.'),
                  value: c.pilotEnabled,
                  onChanged: c.canEdit ? c.setPilot : null,
                ),
                if (c.draft != null)
                  Text(
                    '주문 금액 ${_won(c.draft!.quantity * c.draft!.limitPriceWon)}원',
                  ),
                if (c.check != null)
                  ...c.check!.messages.map(
                    (m) => Padding(
                      padding: const EdgeInsets.symmetric(vertical: 6),
                      child: Text(m),
                    ),
                  ),
                if (c.error != null)
                  Text(c.error!, style: const TextStyle(color: Colors.amber)),
                if (c.receipt != null)
                  Text('주문 ${_status(c.receipt!.status)} · ${c.receipt!.id}'),
                const SizedBox(height: 16),
                if (c.stage == OrderStage.ready ||
                    c.stage == OrderStage.uncertain)
                  FilledButton(
                    onPressed: c.online ? c.submit : null,
                    child: Text(
                      c.stage == OrderStage.uncertain
                          ? '동일 주문 결과 재확인'
                          : '모의주문 최종 확인',
                    ),
                  )
                else if (c.stage == OrderStage.completed)
                  FilledButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('닫기'),
                  )
                else
                  FilledButton(
                    onPressed: c.busy
                        ? null
                        : () => c.prepare(
                            widget.side,
                            int.tryParse(_quantity.text) ?? 0,
                            int.tryParse(_price.text) ?? 0,
                          ),
                    child: Text(c.busy ? '처리 중' : '주문 점검'),
                  ),
              ],
            ),
          ),
        ),
      );
    },
  );
}

String _time(DateTime time) =>
    time.toLocal().toIso8601String().substring(11, 19);
String _won(int value) => '$value'.replaceAllMapped(
  RegExp(r'(\d)(?=(\d{3})+(?!\d))'),
  (match) => '${match[1]},',
);
String _status(String status) => switch (status) {
  'accepted' => '접수',
  'filled' => '체결',
  'rejected' => '거절',
  'cancelled' => '취소',
  'partially_filled' => '부분 체결',
  _ => status,
};
