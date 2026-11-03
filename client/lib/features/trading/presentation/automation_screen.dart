import 'dart:async';
import 'package:flutter/material.dart';
import '../domain/workspace_repository.dart';

class AutomationScreen extends StatefulWidget {
  const AutomationScreen({super.key, required this.repository});
  final WorkspaceRepository repository;
  @override
  State<AutomationScreen> createState() => _AutomationScreenState();
}

class _AutomationScreenState extends State<AutomationScreen> {
  final _budget = TextEditingController(text: '500000');
  List<dynamic> _strategies = [], _runs = [], _events = [];
  String? _selected, _eventRun, _error;
  int? _nextOffset;
  bool _busy = false;
  Timer? _timer;
  @override
  void initState() {
    super.initState();
    _perform(_load);
    _timer = Timer.periodic(const Duration(seconds: 5), (_) {
      if (!_busy) _perform(() => _load(refreshEvents: false));
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _budget.dispose();
    super.dispose();
  }

  Future<void> _perform(Future<void> Function() action) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _load({bool refreshEvents = true}) async {
    final strategies = await widget.repository.workspaceRequest(
      'GET',
      '/v1/strategies',
    );
    final runs = await widget.repository.workspaceRequest(
      'GET',
      '/v1/automations',
    );
    if (!mounted) return;
    setState(() {
      _strategies = strategies['items'] as List;
      _runs = runs['items'] as List;
    });
    if (refreshEvents && _eventRun != null) await _loadEvents(_eventRun!);
  }

  Future<void> _loadEvents(String id, {bool more = false}) async {
    final result = await widget.repository.workspaceRequest(
      'GET',
      '/v1/automations/$id/events?offset=${more ? _nextOffset : 0}',
    );
    if (!mounted) return;
    setState(() {
      _eventRun = id;
      _events = more
          ? [..._events, ...result['items'] as List]
          : result['items'] as List;
      _nextOffset = result['next_offset'] as int?;
    });
  }

  Future<void> _start() async {
    final budget = int.tryParse(_budget.text);
    if (budget == null || budget < 10000 || budget > 100000000) {
      setState(() => _error = '예산은 10,000~100,000,000원 사이의 정수로 입력하세요.');
      return;
    }
    // Keep polling from replacing state while the user reviews the start action.
    _timer?.cancel();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('모의 자동매매 시작'),
        content: Text(
          '합성 시세와 가상 자금으로만 실행합니다. 선택 전략의 완료 5분봉 신호에 따라 최대 $budget원(매수 수수료 포함)으로 모의 주문합니다.\n\n앱을 닫아도 서버가 켜져 있으면 계속 실행됩니다. 중지는 미체결 자동 주문을 취소하며 보유 주식은 매도하지 않습니다. 실행 설정은 시작 당시 값으로 고정됩니다.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('모의 실행 시작'),
          ),
        ],
      ),
    );
    if (!mounted) return;
    _timer = Timer.periodic(const Duration(seconds: 5), (_) {
      if (!_busy) _perform(() => _load(refreshEvents: false));
    });
    if (confirmed != true) return;
    await _perform(() async {
      await widget.repository.workspaceRequest(
        'PUT',
        '/v1/strategies/$_selected/automation',
        body: {'enabled': true, 'budget_won': budget},
      );
      await _load();
    });
  }

  String _label(dynamic value) => switch (value) {
    'buy' => '매수',
    'sell' => '매도',
    'wait' => '대기',
    'accepted' => '접수',
    'filled' => '체결',
    'cancelled' => '취소',
    'rejected' => '거절',
    _ => '주문 없음',
  };
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('모의 자동매매'),
      actions: [
        IconButton(
          onPressed: _busy ? null : () => _perform(_load),
          icon: const Icon(Icons.refresh),
          tooltip: '새로고침',
        ),
      ],
    ),
    body: SafeArea(
      child: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text(
            '합성 시세 · 가상 자금',
            style: TextStyle(color: Colors.amber, fontSize: 20),
          ),
          const SizedBox(height: 12),
          const Text(
            '저장된 이동평균 전략을 5분봉마다 평가합니다. 주문한도·손실한도·쿨다운을 적용하며 사용자 확인이 필요한 행동 경고는 건너뜁니다. 실제 증권사 주문은 발생하지 않습니다.',
          ),
          const SizedBox(height: 8),
          const Text(
            '첫 시작은 해당 종목의 보유·미체결이 없어야 합니다. 실행 중 수동 거래가 감지되면 중지합니다. 체결은 기존 모의 주문 규칙(다음 시세, 편도 수수료 0.015%)을 따르므로 백테스트 결과와 다를 수 있습니다.',
          ),
          const SizedBox(height: 16),
          if (_busy) const LinearProgressIndicator(),
          if (_error != null)
            Text(_error!, style: const TextStyle(color: Colors.redAccent)),
          if (_strategies.isEmpty) const Text('백테스트 화면에서 전략을 먼저 저장하세요.'),
          DropdownButtonFormField<String>(
            initialValue: _selected,
            isExpanded: true,
            decoration: const InputDecoration(labelText: '저장된 전략'),
            items: [
              for (final s in _strategies)
                DropdownMenuItem(
                  value: s['id'] as String,
                  child: Text('${s['name']} · ${s['symbol']}'),
                ),
            ],
            onChanged: _busy ? null : (id) => setState(() => _selected = id),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _budget,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(labelText: '매수 예산 (수수료 포함, 원)'),
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _busy || _selected == null ? null : _start,
            child: const Text('선택 전략 시작 / 재개'),
          ),
          const Divider(height: 32),
          for (final r in _runs)
            Card(
              color: const Color(0xFF151516),
              shape: const RoundedRectangleBorder(
                borderRadius: BorderRadius.zero,
                side: BorderSide(color: Color(0xFF303034)),
              ),
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${r['strategy_snapshot']['name']} · ${r['enabled'] == true ? '실행 중' : '중지'}',
                      style: const TextStyle(
                        fontWeight: FontWeight.bold,
                        fontSize: 18,
                      ),
                    ),
                    Text(
                      '${r['symbol']} · ${r['strategy_snapshot']['fast_period']}/${r['strategy_snapshot']['slow_period']} · 예산 ${r['budget_won']}원',
                    ),
                    Text('${r['message']}'),
                    Text('최근 평가 봉: ${r['last_bar'] ?? '대기'}'),
                    Wrap(
                      spacing: 12,
                      children: [
                        OutlinedButton(
                          onPressed: _busy || r['enabled'] != true
                              ? null
                              : () => _perform(() async {
                                  await widget.repository.workspaceRequest(
                                    'PUT',
                                    '/v1/strategies/${r['strategy_id']}/automation',
                                    body: {'enabled': false},
                                  );
                                  await _load();
                                }),
                          child: const Text('중지 · 미체결 취소'),
                        ),
                        TextButton(
                          onPressed: _busy
                              ? null
                              : () => _perform(
                                  () => _loadEvents(r['id'] as String),
                                ),
                          child: const Text('신호·주문 이력'),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          if (_eventRun != null) ...[
            const Divider(),
            const Text('선택 실행의 최근 신호 이력'),
            if (_events.isEmpty) const Text('아직 평가한 완료 봉이 없습니다.'),
            for (final e in _events)
              ListTile(
                title: Text(
                  '${_label(e['signal'])} · ${_label(e['order_status'])}',
                ),
                subtitle: Text('${e['bar_at']}\n평가 당시: ${e['message']}'),
              ),
            if (_nextOffset != null)
              TextButton(
                onPressed: _busy
                    ? null
                    : () => _perform(() => _loadEvents(_eventRun!, more: true)),
                child: const Text('이전 이력 더 보기'),
              ),
          ],
        ],
      ),
    ),
  );
}
