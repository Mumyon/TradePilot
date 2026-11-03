import 'dataset_screen.dart';
import 'automation_screen.dart';
import 'package:flutter/material.dart';
import '../domain/workspace_repository.dart';

class BacktestScreen extends StatefulWidget {
  const BacktestScreen({super.key, required this.repository});
  final WorkspaceRepository repository;
  @override
  State<BacktestScreen> createState() => _BacktestScreenState();
}

class _BacktestScreenState extends State<BacktestScreen> {
  final _name = TextEditingController(text: '이동평균 전략');
  final _symbol = TextEditingController(text: '005930');
  final _fast = TextEditingController(text: '5');
  final _slow = TextEditingController(text: '20');
  final _source = TextEditingController(text: 'demo');
  final _cash = TextEditingController(text: '10000000');
  final _fee = TextEditingController(text: '2');
  final _slip = TextEditingController(text: '5');
  late final _start = TextEditingController(
    text: DateTime.now()
        .toUtc()
        .subtract(const Duration(days: 7))
        .toIso8601String(),
  );
  late final _end = TextEditingController(
    text: DateTime.now().toUtc().toIso8601String(),
  );
  final _form = GlobalKey<FormState>();
  List<dynamic> _strategies = [], _results = [];
  String? _selected, _error;
  Map<String, dynamic>? _result, _dataset;
  bool _busy = false;
  int? _nextOffset;

  @override
  void initState() {
    super.initState();
    _perform(_load);
  }

  @override
  void dispose() {
    for (final c in [
      _name,
      _symbol,
      _fast,
      _slow,
      _source,
      _cash,
      _fee,
      _slip,
      _start,
      _end,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _perform(Future<void> Function() action) async {
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

  Future<void> _load() async {
    final s = await widget.repository.workspaceRequest('GET', '/v1/strategies');
    final r = await widget.repository.workspaceRequest('GET', '/v1/backtests');
    if (!mounted) return;
    setState(() {
      _strategies = s['items'] as List;
      _results = r['items'] as List;
      _nextOffset = r['next_offset'] as int?;
    });
  }

  Map<String, dynamic> _config() => {
    'name': _name.text.trim(),
    'symbol': _symbol.text.trim(),
    'fast_period': int.parse(_fast.text),
    'slow_period': int.parse(_slow.text),
    'enabled': true,
  };
  Widget _field(String label, TextEditingController c, {bool number = false}) =>
      Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: TextFormField(
          controller: c,
          decoration: InputDecoration(labelText: label),
          keyboardType: number ? TextInputType.number : TextInputType.text,
          validator: (v) =>
              v == null ||
                  v.trim().isEmpty ||
                  (number && int.tryParse(v) == null)
              ? '값을 확인하세요.'
              : null,
        ),
      );
  String _pct(dynamic value) =>
      value == null ? '평가 없음' : '${(value as num).toStringAsFixed(2)}%';
  void _select(Map<String, dynamic> s) {
    setState(() {
      _selected = s['id'] as String;
      _name.text = s['name'] as String;
      _symbol.text = s['symbol'] as String;
      _fast.text = '${s['fast_period']}';
      _slow.text = '${s['slow_period']}';
    });
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('전략 · 백테스트')),
    body: SafeArea(
      child: Form(
        key: _form,
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            OutlinedButton(
              onPressed: _busy
                  ? null
                  : () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) =>
                            AutomationScreen(repository: widget.repository),
                      ),
                    ),
              child: const Text('모의 자동매매 관리'),
            ),
            const Text(
              '5분봉 이동평균 전략',
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            const Text(
              '단기 평균 > 장기 평균이면 매수, 이하이면 매도합니다. 완료 봉 신호 → 다음 연속 봉 시가 체결. 정수 주식·전액 투자·수수료 및 슬리피지 반영. 실제 주문은 발생하지 않습니다.',
            ),
            const SizedBox(height: 16),
            if (_busy) const LinearProgressIndicator(),
            if (_error != null)
              Text(_error!, style: const TextStyle(color: Colors.redAccent)),
            for (final raw in _strategies)
              Builder(
                builder: (_) {
                  final s = Map<String, dynamic>.from(raw as Map);
                  return ListTile(
                    title: Text('${s['name']} · ${s['symbol']}'),
                    subtitle: Text(
                      '${s['fast_period']} / ${s['slow_period']} · ${s['enabled'] == true ? "활성" : "비활성"}',
                    ),
                    selected: _selected == s['id'],
                    onTap: _busy ? null : () => _select(s),
                    trailing: Switch(
                      value: s['enabled'] == true,
                      onChanged: _busy
                          ? null
                          : (value) => _perform(() async {
                              await widget.repository.workspaceRequest(
                                'PUT',
                                '/v1/strategies/${s['id']}',
                                body: {...s..remove('id'), 'enabled': value},
                              );
                              await _load();
                            }),
                    ),
                  );
                },
              ),
            _field('전략명', _name),
            _field('종목 코드', _symbol),
            _field('단기 평균 기간 (2~100)', _fast, number: true),
            _field('장기 평균 기간 (3~200)', _slow, number: true),
            Wrap(
              spacing: 12,
              children: [
                FilledButton(
                  onPressed: _busy
                      ? null
                      : () => _perform(() async {
                          if (!_form.currentState!.validate()) return;
                          final s = await widget.repository.workspaceRequest(
                            'POST',
                            '/v1/strategies',
                            body: _config(),
                          );
                          _selected = s['id'] as String;
                          await _load();
                        }),
                  child: const Text('새 전략 저장'),
                ),
                OutlinedButton(
                  onPressed: _busy || _selected == null
                      ? null
                      : () => _perform(() async {
                          if (!_form.currentState!.validate()) return;
                          final existing = _strategies.firstWhere(
                            (s) => s['id'] == _selected,
                          );
                          await widget.repository.workspaceRequest(
                            'PUT',
                            '/v1/strategies/$_selected',
                            body: {
                              ..._config(),
                              'enabled': existing['enabled'],
                            },
                          );
                          await _load();
                        }),
                  child: const Text('선택 전략 수정'),
                ),
              ],
            ),
            const Divider(height: 32),
            const Text('실행은 저장된 선택 전략을 사용합니다. 입력만 바꾼 경우 먼저 수정 버튼을 누르세요.'),
            const Text(
              'demo = 합성 시연 데이터. CSV 사용 시 입력할 때 지정한 source를 적으세요. 구간 공백은 지표를 초기화하며 종료 시 잔여 주식은 종가로 평가합니다. 세금·부분 체결·거래량 제한은 반영하지 않습니다.',
            ),
            const SizedBox(height: 12),
            OutlinedButton(
              onPressed: _busy
                  ? null
                  : () async {
                      final data = await Navigator.of(context)
                          .push<Map<String, dynamic>>(
                            MaterialPageRoute(
                              builder: (_) =>
                                  DatasetScreen(repository: widget.repository),
                            ),
                          );
                      if (data != null && mounted) {
                        setState(() {
                          _dataset = data;
                          _source.text = 'private_csv';
                          _start.text = data['first_bar'] as String;
                          _end.text = DateTime.parse(
                            data['last_bar'] as String,
                          ).add(const Duration(minutes: 5)).toIso8601String();
                        });
                      }
                    },
              child: const Text('CSV 등록 · 내 데이터 선택'),
            ),
            if (_dataset != null) ...[
              Text(
                '선택: ${_dataset!['name']} · ${_dataset!['symbol']} (저장 전략의 종목과 같아야 합니다)',
              ),
              TextButton(
                onPressed: _busy
                    ? null
                    : () => setState(() {
                        _dataset = null;
                        _source.text = 'demo';
                        _start.text = DateTime.now()
                            .toUtc()
                            .subtract(const Duration(days: 7))
                            .toIso8601String();
                        _end.text = DateTime.now().toUtc().toIso8601String();
                      }),
                child: const Text('합성 시연 데이터로 전환'),
              ),
            ] else
              _field('데이터 source', _source),
            _field('시작 (ISO 8601, 시간대 포함)', _start),
            _field('종료 (ISO 8601, 시간대 포함)', _end),
            _field('초기 자금 (원)', _cash, number: true),
            _field('편도 수수료 (bp, 1bp=0.01%)', _fee, number: true),
            _field('편도 슬리피지 (bp)', _slip, number: true),
            FilledButton(
              onPressed: _busy || _selected == null
                  ? null
                  : () => _perform(() async {
                      if (!_form.currentState!.validate()) return;
                      final r = await widget.repository.workspaceRequest(
                        'POST',
                        '/v1/strategies/$_selected/backtests',
                        body: {
                          'source': _source.text.trim(),
                          if (_dataset != null) 'dataset_id': _dataset!['id'],
                          'start': _start.text,
                          'end': _end.text,
                          'initial_cash_won': int.parse(_cash.text),
                          'fee_bps': int.parse(_fee.text),
                          'slippage_bps': int.parse(_slip.text),
                        },
                      );
                      if (mounted) setState(() => _result = r);
                      await _load();
                    }),
              child: const Text('백테스트 실행'),
            ),
            if (_result case final r?) ...[
              const Divider(height: 32),
              Text(
                '${r['data_label']}',
                style: const TextStyle(color: Colors.amber),
              ),
              Text(
                '수익률 ${_pct(r['return_pct'])} · 최대 낙폭 ${_pct(r['max_drawdown_pct'])}',
              ),
              Text('최종 평가 ${r['final_equity_won']}원 · 수수료 ${r['fee_won']}원'),
              Text(
                '완료 거래 ${r['round_trips']} · 승 ${r['wins']} / 패 ${r['losses']} / 보합 ${r['flat']} · 승률 ${_pct(r['win_rate_pct'])}',
              ),
              Text(
                '실현 ${r['realized_pnl_won']}원 · 미실현 ${r['unrealized_pnl_won']}원 · 보유 ${r['open_quantity']}주',
              ),
              Text(
                '${r['bar_count']}개 봉 · ${r['first_bar']} ~ ${r['last_bar']}',
              ),
              Text('${r['end_policy']} · 과거 성과는 미래 성과를 보장하지 않습니다.'),
              ExpansionTile(
                title: const Text('거래 내역'),
                children: [
                  for (final t in r['trades'] as List)
                    ListTile(
                      title: Text(
                        '${t['side'] == 'buy' ? '매수' : '매도'} ${t['quantity']}주 · ${t['price_won']}원',
                      ),
                      subtitle: Text(
                        '${t['at']}\n수수료 ${t['fee_won']}원 · 실현손익 ${t['realized_pnl_won'] ?? "—"}',
                      ),
                    ),
                ],
              ),
            ],
            const Divider(height: 32),
            const Text('저장된 결과'),
            if (_results.isEmpty) const Text('아직 실행한 결과가 없습니다.'),
            for (final r in _results)
              ListTile(
                title: Text(
                  '${r['strategy_snapshot']['name']} · ${_pct(r['return_pct'])}',
                ),
                subtitle: Text('${r['data_label']} · ${r['created_at']}'),
                onTap: _busy
                    ? null
                    : () => _perform(() async {
                        final result = await widget.repository.workspaceRequest(
                          'GET',
                          '/v1/backtests/${r['id']}',
                        );
                        if (mounted) setState(() => _result = result);
                      }),
              ),
            if (_nextOffset != null)
              TextButton(
                onPressed: _busy
                    ? null
                    : () => _perform(() async {
                        final page = await widget.repository.workspaceRequest(
                          'GET',
                          '/v1/backtests?offset=$_nextOffset',
                        );
                        if (mounted) {
                          setState(() {
                            _results.addAll(page['items'] as List);
                            _nextOffset = page['next_offset'] as int?;
                          });
                        }
                      }),
                child: const Text('이전 결과 더 보기'),
              ),
          ],
        ),
      ),
    ),
  );
}
