import 'package:flutter/material.dart';
import '../domain/workspace_repository.dart';
import 'design_bindings.dart';

/// Persistent paper trading tools. Uses the app's existing typography and theme.
class WorkspaceScreen extends StatefulWidget {
  const WorkspaceScreen({
    super.key,
    required this.repository,
    this.initialTab = 0,
  });
  final WorkspaceRepository repository;
  final int initialTab;
  @override
  State<WorkspaceScreen> createState() => _WorkspaceScreenState();
}

class _WorkspaceScreenState extends State<WorkspaceScreen> {
  Map<String, dynamic>? _account, _settings;
  List<dynamic> _symbols = [], _plans = [], _orders = [], _fills = [];
  bool _busy = false;
  String? _error;
  final _limit = TextEditingController(),
      _loss = TextEditingController(),
      _cooldown = TextEditingController(),
      _rules = TextEditingController(),
      _condition = TextEditingController(),
      _stop = TextEditingController(),
      _amount = TextEditingController();
  String? _symbol;
  String _side = 'buy', _query = '';
  final _entryMin = TextEditingController(),
      _entryMax = TextEditingController();
  bool _split = false, _paused = false;
  final _settingsForm = GlobalKey<FormState>(),
      _planForm = GlobalKey<FormState>();

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final c in [
      _entryMin,
      _entryMax,
      _limit,
      _loss,
      _cooldown,
      _rules,
      _condition,
      _stop,
      _amount,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await Future.wait([
        for (final path in [
          'account',
          'settings',
          'symbols',
          'plans',
          'orders',
          'fills',
        ])
          widget.repository.workspaceRequest('GET', '/v1/$path'),
      ]);
      if (!mounted) return;
      setState(() {
        _account = result[0];
        _settings = result[1];
        _symbols = result[2]['items'] as List;
        _plans = result[3]['items'] as List;
        _orders = result[4]['items'] as List;
        _fills = result[5]['items'] as List;
        _symbol ??= _symbols.firstOrNull?['symbol'] as String?;
        _limit.text = '${_settings!['order_limit_won']}';
        _loss.text = '${_settings!['daily_loss_limit_won']}';
        _cooldown.text = '${_settings!['cooldown_seconds']}';
        _rules.text = _settings!['trading_rules'] as String;
        _paused = _settings!['trading_paused'] == true;
      });
    } catch (_) {
      if (mounted) setState(() => _error = '데이터를 불러오지 못했습니다. 다시 시도하세요.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _save(
    String method,
    String path, [
    Map<String, dynamic>? body,
  ]) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.repository.workspaceRequest(method, path, body: body);
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('서버에 반영했습니다.')));
      await _load();
    } catch (_) {
      if (mounted) setState(() => _error = '반영 여부를 확인하지 못했습니다. 새로고침 후 확인하세요.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String money(dynamic value) =>
      value == null ? '확인 불가' : '${won(int.parse('$value'))}원';
  String stamp(dynamic value) => value == null
      ? '—'
      : DateTime.parse('$value').toLocal().toString().split('.').first;
  Widget _line(String title, String value) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 9),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(child: Text(title)),
        const SizedBox(width: 12),
        Flexible(child: Text(value, textAlign: TextAlign.right)),
      ],
    ),
  );
  Widget _number(
    String label,
    TextEditingController controller, {
    bool zero = false,
    bool optional = false,
    int maximum = 1000000000,
  }) => Padding(
    padding: const EdgeInsets.only(bottom: 16),
    child: TextFormField(
      controller: controller,
      keyboardType: TextInputType.number,
      decoration: InputDecoration(labelText: label),
      validator: (text) {
        if (optional && (text ?? '').trim().isEmpty) return null;
        final n = int.tryParse(text ?? '');
        return n == null || n < (zero ? 0 : 1) || n > maximum
            ? '올바른 정수를 입력하세요 (최대 $maximum).'
            : null;
      },
    ),
  );
  Widget _list(List<Widget> children) =>
      ListView(padding: const EdgeInsets.all(24), children: children);

  Widget _accountTab() {
    final a = _account;
    if (a == null) return const Center(child: Text('계좌 데이터가 없습니다.'));
    return _list([
      const Text(
        '모의투자 계좌',
        style: TextStyle(fontSize: 23, fontWeight: FontWeight.w600),
      ),
      _line('예수금', money(a['cash_won'])),
      _line('주문 예약금', money(a['reserved_won'])),
      _line('주문 가능 금액', money(a['available_cash_won'])),
      _line('총 평가금액', money(a['equity_won'])),
      _line(
        '누적 실현손익',
        '${money(a['realized_pnl_won'])}${a['realized_pnl_complete'] == true ? '' : ' · 일부 원가 미확인'}',
      ),
      Text('${a['fee_policy']}', style: const TextStyle(fontSize: 12)),
      Text('조회 ${stamp(a['as_of'])}', style: const TextStyle(fontSize: 12)),
      const Divider(height: 32),
      const Text('보유종목', style: TextStyle(fontSize: 20)),
      if ((a['holdings'] as List).isEmpty) const Text('보유종목이 없습니다.'),
      for (final h in a['holdings'] as List) ...[
        const SizedBox(height: 16),
        Text('${h['name']} · ${h['quantity']}주'),
        _line('매도 가능', '${h['available_quantity']}주'),
        _line('평균 매입가 (수수료 포함)', money(h['average_price_won'])),
        _line('평가손익', money(h['unrealized_pnl_won'])),
        Text(
          h['stale'] == true ? '시세 지연/미연결' : '시세 ${stamp(h['quote_as_of'])}',
          style: const TextStyle(fontSize: 11),
        ),
        const Divider(),
      ],
    ]);
  }

  Widget _settingsTab() => Form(
    key: _settingsForm,
    child: _list([
      const Text('거래 원칙과 위험한도', style: TextStyle(fontSize: 23)),
      const SizedBox(height: 24),
      _number('1회 주문한도 (원)', _limit),
      _number('일일 손실한도 (원)', _loss),
      _number('주문 쿨다운 (초)', _cooldown, zero: true, maximum: 86400),
      TextFormField(
        controller: _rules,
        maxLength: 2000,
        maxLines: 4,
        decoration: const InputDecoration(labelText: '나의 거래 원칙'),
      ),
      const SizedBox(height: 12),
      const Text(
        '주문한도·일일 손실한도·쿨다운은 서버에서 적용합니다. 손실한도 도달 시 매수만 차단합니다. 자유 서술 원칙은 참고용이며 자동 해석하지 않습니다.',
        style: TextStyle(fontSize: 12),
      ),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const Text('신규 모의주문 정지'),
        subtitle: const Text('기존 접수 주문은 계속 체결될 수 있습니다. 필요하면 주문·체결에서 취소하세요.'),
        value: _paused,
        onChanged: _busy ? null : (v) => setState(() => _paused = v),
      ),
      const SizedBox(height: 16),
      FilledButton(
        onPressed: _busy
            ? null
            : () {
                if (_settingsForm.currentState!.validate()) {
                  _save('PUT', '/v1/settings', {
                    'order_limit_won': int.parse(_limit.text),
                    'daily_loss_limit_won': int.parse(_loss.text),
                    'cooldown_seconds': int.parse(_cooldown.text),
                    'trading_rules': _rules.text,
                    'trading_paused': _paused,
                  });
                }
              },
        child: const Text('거래 설정 저장'),
      ),
    ]),
  );

  Widget _watchTab() => _list([
    const Text('관심종목 관리', style: TextStyle(fontSize: 23)),
    const SizedBox(height: 16),
    TextField(
      decoration: const InputDecoration(labelText: '종목명 또는 코드 검색'),
      onChanged: (q) => setState(() => _query = q.trim()),
    ),
    const SizedBox(height: 12),
    const Text('현재 서버에 등록된 종목을 검색합니다.', style: TextStyle(fontSize: 12)),
    for (final row in _symbols.where(
      (s) => '${s['name']} ${s['symbol']}'.contains(_query),
    ))
      ListTile(
        contentPadding: EdgeInsets.zero,
        title: Text('${row['name']}'),
        subtitle: Text('${row['symbol']}'),
        trailing: IconButton(
          tooltip: row['watched'] == true ? '관심종목 삭제' : '관심종목 추가',
          icon: Icon(row['watched'] == true ? Icons.star : Icons.star_border),
          onPressed: _busy
              ? null
              : () => _save(
                  row['watched'] == true ? 'DELETE' : 'PUT',
                  '/v1/watchlist/${row['symbol']}',
                ),
        ),
      ),
    if (_symbols
        .where((s) => '${s['name']} ${s['symbol']}'.contains(_query))
        .isEmpty)
      const Text('검색 결과가 없습니다.'),
  ]);

  Widget _plansTab() => Form(
    key: _planForm,
    child: _list([
      const Text('매매 계획 등록', style: TextStyle(fontSize: 23)),
      const SizedBox(height: 16),
      DropdownButtonFormField<String>(
        initialValue: _symbol,
        decoration: const InputDecoration(labelText: '종목'),
        items: [
          for (final s in _symbols)
            DropdownMenuItem(
              value: s['symbol'] as String,
              child: Text('${s['name']}'),
            ),
        ],
        onChanged: (v) => setState(() => _symbol = v),
        validator: (v) => v == null ? '종목을 선택하세요.' : null,
      ),
      const SizedBox(height: 16),
      DropdownButtonFormField<String>(
        initialValue: _side,
        decoration: const InputDecoration(labelText: '방향'),
        items: const [
          DropdownMenuItem(value: 'buy', child: Text('매수')),
          DropdownMenuItem(value: 'sell', child: Text('매도')),
        ],
        onChanged: (v) => setState(() => _side = v!),
      ),
      const SizedBox(height: 16),
      TextFormField(
        controller: _condition,
        maxLength: 1000,
        maxLines: 3,
        decoration: const InputDecoration(labelText: '진입·청산 조건'),
        validator: (v) => (v ?? '').trim().isEmpty ? '조건을 입력하세요.' : null,
      ),
      _number('계획 가격 하한 (선택, 원)', _entryMin, optional: true),
      _number('계획 가격 상한 (선택, 원)', _entryMax, optional: true),
      _number('손절 기준 가격 (선택, 원)', _stop, optional: true),
      _number('계획 최대 금액 (원)', _amount),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const Text('분할매매 계획'),
        value: _split,
        onChanged: (v) => setState(() => _split = v),
      ),
      const Text(
        '주문 점검 때 이 계획을 선택할 수 있습니다. 가격 범위·손절가·누적 금액을 평가하며, 급등·급락 또는 손실 이후 등록한 계획은 해당 경고를 해제하지 않습니다.',
        style: TextStyle(fontSize: 12),
      ),
      FilledButton(
        onPressed: _busy
            ? null
            : () {
                if (_planForm.currentState!.validate()) {
                  final min = int.tryParse(_entryMin.text),
                      max = int.tryParse(_entryMax.text);
                  if (min != null && max != null && min > max) {
                    setState(() => _error = '계획 하한은 상한보다 클 수 없습니다.');
                    return;
                  }
                  _save('POST', '/v1/plans', {
                    'symbol': _symbol,
                    'side': _side,
                    'entry_condition': _condition.text.trim(),
                    'entry_min_won': int.tryParse(_entryMin.text),
                    'entry_max_won': int.tryParse(_entryMax.text),
                    'stop_loss_won': int.tryParse(_stop.text),
                    'max_amount_won': int.parse(_amount.text),
                    'split_order': _split,
                  });
                }
              },
        child: const Text('새 매매 계획 저장'),
      ),
      const Divider(height: 32),
      const Text('저장된 계획'),
      for (final p in _plans)
        ListTile(
          contentPadding: EdgeInsets.zero,
          title: Text('${p['symbol']} · ${p['side'] == 'buy' ? '매수' : '매도'}'),
          subtitle: Text(
            '${p['entry_condition']}\n한도 ${money(p['max_amount_won'])} · 손절 ${money(p['stop_loss_won'])}\n${stamp(p['created_at'])}',
          ),
        ),
    ]),
  );

  Widget _ordersTab() => _list([
    const Text('모의주문 · 체결 내역', style: TextStyle(fontSize: 23)),
    const Text(
      '접수 후 새 시세가 지정가에 도달하면 전량 체결됩니다. 실제 증권사 주문은 전송하지 않습니다.',
      style: TextStyle(fontSize: 12),
    ),
    const SizedBox(height: 16),
    if (_orders.isEmpty) const Text('주문 내역이 없습니다.'),
    for (final o in _orders)
      ListTile(
        contentPadding: EdgeInsets.zero,
        title: Text('${o['symbol']} · ${orderStatus(o['status'] as String)}'),
        subtitle: Text(
          '${o['order_id']}${o['reason'] == null ? '' : '\n${o['reason']}'}',
        ),
        trailing: o['status'] == 'accepted'
            ? TextButton(
                onPressed: _busy
                    ? null
                    : () => _save('POST', '/v1/orders/${o['order_id']}/cancel'),
                child: const Text('취소'),
              )
            : null,
      ),
    const Divider(height: 32),
    const Text('체결 장부 (최근 200건)'),
    for (final f in _fills)
      ListTile(
        contentPadding: EdgeInsets.zero,
        title: Text(
          '${f['symbol']} · ${f['side'] == 'buy' ? '매수' : '매도'} ${f['quantity']}주',
        ),
        subtitle: Text(
          '체결가 ${money(f['price_won'])} · 수수료 ${money(f['fee_won'])}\n${f['side'] == 'sell' ? '실현손익 ${money(f['realized_pnl_won'])}\n' : ''}${stamp(f['created_at'])} · ${f['source'] == 'demo' ? '테스트 시세' : f['source']}',
        ),
      ),
  ]);

  @override
  Widget build(BuildContext context) => DefaultTabController(
    length: 5,
    initialIndex: widget.initialTab,
    child: Scaffold(
      appBar: AppBar(
        title: const Text('모의투자 관리'),
        actions: [
          IconButton(
            tooltip: '새로고침',
            onPressed: _busy ? null : _load,
            icon: const Icon(Icons.refresh),
          ),
        ],
        bottom: const TabBar(
          isScrollable: true,
          tabs: [
            Tab(text: '계좌'),
            Tab(text: '거래 설정'),
            Tab(text: '관심종목'),
            Tab(text: '매매 계획'),
            Tab(text: '주문·체결'),
          ],
        ),
      ),
      body: Column(
        children: [
          if (_busy) const LinearProgressIndicator(),
          if (_error != null)
            Padding(padding: const EdgeInsets.all(16), child: Text(_error!)),
          Expanded(
            child: TabBarView(
              children: [
                _accountTab(),
                _settingsTab(),
                _watchTab(),
                _plansTab(),
                _ordersTab(),
              ],
            ),
          ),
        ],
      ),
    ),
  );
}
