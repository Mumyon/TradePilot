import 'dart:convert';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../domain/models.dart';
import '../domain/workspace_repository.dart';
import 'dataset_screen.dart';
import 'ai_replay_review.dart';
import 'risk_confirmation.dart';

/// A separate portfolio and virtual clock; live trading state is never changed.
class ReplayScreen extends StatefulWidget {
  const ReplayScreen({super.key, required this.repository, this.onLegacy});
  final WorkspaceRepository repository;
  final VoidCallback? onLegacy;
  @override
  State<ReplayScreen> createState() => _ReplayScreenState();
}

class _ReplayScreenState extends State<ReplayScreen> {
  Map<String, dynamic> _hub = {}, _run = {};
  Map<String, dynamic>? _retryBody;
  String? _error;
  bool _busy = false, _dialogOpen = false, _showSynthetic = false;
  String _side = 'buy';
  final _quantity = TextEditingController(text: '1');
  final _price = TextEditingController();
  String _key() =>
      '${DateTime.now().microsecondsSinceEpoch}-${math.Random.secure().nextInt(1 << 30)}';
  @override
  void initState() {
    super.initState();
    _perform(_load);
  }

  @override
  void dispose() {
    _quantity.dispose();
    _price.dispose();
    super.dispose();
  }

  Future<Map<String, dynamic>> _request(
    String method,
    String path, [
    Map<String, dynamic>? body,
  ]) =>
      widget.repository.workspaceRequest(method, '/v1/replay$path', body: body);
  Future<void> _load() async {
    await _request('POST', '/historical');
    final hub = await _request('GET', '');
    if (mounted) setState(() => _hub = hub);
  }

  Future<T?> _showDialog<T>({
    required BuildContext context,
    required WidgetBuilder builder,
    bool barrierDismissible = true,
  }) async {
    setState(() => _dialogOpen = true);
    try {
      return await showDialog<T>(
        context: context,
        builder: builder,
        barrierDismissible: barrierDismissible,
      );
    } finally {
      if (mounted) setState(() => _dialogOpen = false);
    }
  }

  Future<void> _perform(Future<void> Function() task) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await task();
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _setRun(Map<String, dynamic> run) {
    if (!mounted) return;
    setState(() => _run = run);
    if (_price.text.isEmpty) {
      _price.text = '${(run['visible_bars'] as List).last['close_won']}';
    }
  }

  Future<Map<String, dynamic>> _action(
    String action, [
    Map<String, dynamic> extra = const {},
  ]) async {
    final body = {
      'request_id': _key(),
      'revision': _run['revision'],
      'action': action,
      ...extra,
    };
    _retryBody = body;
    final result = await _request('POST', '/runs/${_run['id']}/actions', body);
    _retryBody = null;
    _setRun(result);
    return Map<String, dynamic>.from(result['action_result'] as Map? ?? {});
  }

  Future<void> _retry() async {
    final body = _retryBody;
    if (body == null) return;
    final result = await _request('POST', '/runs/${_run['id']}/actions', body);
    _retryBody = null;
    _setRun(result);
    // A recovered check is left unsubmitted. The user can inspect a fresh check.
  }

  Future<void> _refresh() async {
    if (_run.isNotEmpty) {
      _setRun(await _request('GET', '/runs/${_run['id']}'));
      _retryBody = null;
      await _load();
    } else {
      await _load();
    }
  }

  String _time(dynamic value) {
    final at = DateTime.tryParse('$value');
    if (at == null) return '$value';
    final kst = at.toUtc().add(const Duration(hours: 9));
    return '${kst.toIso8601String().substring(0, 16).replaceFirst('T', ' ')} KST';
  }

  Widget _text(String value) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 5),
    child: Text(value),
  );
  Widget _button(String label, Future<void> Function() fn, {String? key}) =>
      Padding(
        padding: const EdgeInsets.only(right: 8, bottom: 8),
        child: OutlinedButton(
          key: key == null ? null : ValueKey(key),
          onPressed: _busy ? null : () => _perform(fn),
          child: Text(label),
        ),
      );
  Widget _card(List<Widget> children) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: children,
      ),
    ),
  );

  Future<void> _start(
    Map<String, dynamic> c, {
    Map<String, dynamic>? pair,
  }) async {
    final preview = c['preview'] as List;
    final current = (preview.last['close_won'] as num).toInt();
    final low = TextEditingController(text: '${(current * .98).round()}');
    final high = TextEditingController(text: '${(current * 1.02).round()}');
    final maxAmount = TextEditingController(text: '1000000');
    final stop = TextEditingController();
    bool pilot = pair == null ? true : pair['pilot_enabled'] != true,
        randomizeOrder = false,
        hasPlan = true,
        split = false;
    String planSide = 'buy';
    final form = GlobalKey<FormState>();
    final answer = await _showDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, update) => AlertDialog(
          title: Text(pair == null ? '실험 시작 조건' : '같은 조건 · 반대 Pilot'),
          content: SizedBox(
            width: 360,
            child: SingleChildScrollView(
              child: Form(
                key: form,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      '${c['name']}\n현재 공개 가격 $current원\n초기 현금 1,000만 원 · 보유 0주',
                    ),
                    const Text(
                      'AI 정보는 두 조건에서 동일하게 제공합니다. Pilot 조건은 행동 경고만 바꾸며 실험 중 고정됩니다.',
                    ),
                    if (c['model'] == null)
                      const Text('학습 모델 없음 · 이번 실험에서는 AI 예측을 제공하지 않습니다.'),
                    if (pair == null) ...[
                      SwitchListTile(
                        key: const ValueKey('replay-randomize-order'),
                        title: const Text('Pilot 순서 무작위 배정'),
                        subtitle: const Text(
                          '서버가 ON→OFF 또는 OFF→ON 순서를 정해 실험 기록에 저장합니다.',
                        ),
                        value: randomizeOrder,
                        onChanged: (v) => update(() => randomizeOrder = v),
                      ),
                      if (!randomizeOrder)
                        SwitchListTile(
                          title: const Text('Pilot 행동 피드백'),
                          value: pilot,
                          onChanged: (v) => update(() => pilot = v),
                        ),
                    ] else
                      Text(
                        'Pilot ${pilot ? 'ON' : 'OFF'} · 이전 실험의 계획을 그대로 사용합니다.',
                      ),
                    if (pair == null) ...[
                      SwitchListTile(
                        title: const Text('사전 계획 등록'),
                        value: hasPlan,
                        onChanged: (v) => update(() => hasPlan = v),
                      ),
                      if (hasPlan) ...[
                        DropdownButtonFormField<String>(
                          initialValue: planSide,
                          decoration: const InputDecoration(labelText: '계획 방향'),
                          items: const [
                            DropdownMenuItem(value: 'buy', child: Text('매수')),
                            DropdownMenuItem(value: 'sell', child: Text('매도')),
                          ],
                          onChanged: (v) => update(() => planSide = v!),
                        ),
                        for (final entry in [
                          (low, '최소 가격'),
                          (high, '최대 가격'),
                          (maxAmount, '계획 누적 한도'),
                        ])
                          TextFormField(
                            controller: entry.$1,
                            keyboardType: TextInputType.number,
                            decoration: InputDecoration(
                              labelText: '${entry.$2} (원)',
                            ),
                            validator: (s) {
                              final n = int.tryParse(s ?? '');
                              if (n == null || n <= 0) return '양의 정수를 입력하세요';
                              if (entry.$1 == high &&
                                  n < (int.tryParse(low.text) ?? n)) {
                                return '최소 가격 이상이어야 합니다';
                              }
                              return null;
                            },
                          ),
                        TextFormField(
                          controller: stop,
                          keyboardType: TextInputType.number,
                          decoration: const InputDecoration(
                            labelText: '손절 가격 (선택)',
                          ),
                          validator: (s) =>
                              s!.isNotEmpty && (int.tryParse(s) ?? 0) <= 0
                              ? '양의 정수를 입력하세요'
                              : null,
                        ),
                        SwitchListTile(
                          title: const Text('분할 주문 계획'),
                          value: split,
                          onChanged: (v) => update(() => split = v),
                        ),
                      ],
                    ],
                    const Text(
                      '수수료 편도 0.015% · 다음 봉 시가로 지정가 조건 충족 시 체결. 가격 충격·세금은 반영하지 않습니다.',
                    ),
                  ],
                ),
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('닫기'),
            ),
            FilledButton(
              key: const ValueKey('replay-start-confirm'),
              onPressed: () {
                if (!form.currentState!.validate()) return;
                Navigator.pop(context, <String, dynamic>{
                  'request_id': _key(),
                  if (randomizeOrder) 'randomize_order': true,
                  if (!randomizeOrder) 'pilot_enabled': pilot,
                  if (pair != null) 'paired_run_id': pair['id'],
                  if (pair == null && hasPlan)
                    'plan': {
                      'side': planSide,
                      'entry_min_won': int.parse(low.text),
                      'entry_max_won': int.parse(high.text),
                      'max_amount_won': int.parse(maxAmount.text),
                      'stop_loss_won': int.tryParse(stop.text),
                      'split_order': split,
                    },
                });
              },
              child: const Text('시작'),
            ),
          ],
        ),
      ),
    );
    // Controllers are retained through the route's closing animation.
    await Future<void>.delayed(const Duration(milliseconds: 250));
    low.dispose();
    high.dispose();
    maxAmount.dispose();
    stop.dispose();
    if (answer == null || !mounted) return;
    _price.clear();
    _setRun(await _request('POST', '/cases/${c['id']}/runs', answer));
  }

  Future<void> _import() async {
    final data = await widget.repository.workspaceRequest(
      'GET',
      '/v1/datasets',
    );
    if (!mounted) return;
    final items = data['items'] as List;
    if (items.isEmpty) {
      throw Exception('먼저 CSV 관리에서 5분봉 데이터를 등록하세요.');
    }
    String datasetId = items.first['id'], eventKey = 'custom';
    final name = TextEditingController(text: '${items.first['name']} 재생');
    final start = TextEditingController(), source = TextEditingController();
    final form = GlobalKey<FormState>();
    final result = await _showDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, update) => AlertDialog(
          title: const Text('과거 사례 등록'),
          content: SizedBox(
            width: 360,
            child: SingleChildScrollView(
              child: Form(
                key: form,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    DropdownButtonFormField<String>(
                      initialValue: datasetId,
                      isExpanded: true,
                      decoration: const InputDecoration(labelText: '저장된 CSV'),
                      items: items
                          .map(
                            (e) => DropdownMenuItem<String>(
                              value: e['id'],
                              child: Text(
                                '${e['name']}',
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          )
                          .toList(),
                      onChanged: (v) => update(() => datasetId = v!),
                    ),
                    Text(
                      '데이터 범위: ${items.firstWhere((e) => e['id'] == datasetId)['first_bar']}\n~ ${items.firstWhere((e) => e['id'] == datasetId)['last_bar']}',
                    ),
                    DropdownButtonFormField<String>(
                      initialValue: eventKey,
                      isExpanded: true,
                      decoration: const InputDecoration(labelText: '사건 분류'),
                      items: [
                        const DropdownMenuItem(
                          value: 'custom',
                          child: Text('직접 등록'),
                        ),
                        for (final e in _hub['events'] as List? ?? [])
                          DropdownMenuItem(
                            value: '${e['key']}',
                            child: Text(
                              '${e['name']}',
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                      ],
                      onChanged: (v) => update(() => eventKey = v!),
                    ),
                    TextFormField(
                      controller: name,
                      decoration: const InputDecoration(labelText: '사례 이름'),
                      validator: (v) => v!.trim().isEmpty ? '이름을 입력하세요' : null,
                    ),
                    TextFormField(
                      controller: start,
                      decoration: const InputDecoration(
                        labelText: '첫 공개 봉의 시작 시각',
                        hintText: '2024-08-05T12:00:00+09:00',
                      ),
                      validator: (v) => DateTime.tryParse(v ?? '') == null
                          ? '시간대를 포함한 ISO 시각을 입력하세요'
                          : null,
                    ),
                    TextFormField(
                      controller: source,
                      decoration: const InputDecoration(
                        labelText: '시세 데이터 출처 URL (선택)',
                      ),
                    ),
                    const Text(
                      'CSV는 불변 사본으로 보존합니다. 시작 이전 구간만 AI 학습에 사용합니다. 학습용 최소 240개 라벨 표본과 여러 거래일이 필요합니다. 재생은 최대 500봉입니다.',
                    ),
                  ],
                ),
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('닫기'),
            ),
            FilledButton(
              onPressed: () {
                if (form.currentState!.validate()) {
                  Navigator.pop(context, <String, dynamic>{
                    'dataset_id': datasetId,
                    'name': name.text.trim(),
                    'replay_from': start.text.trim(),
                    'event_key': eventKey,
                    'source_url': source.text.trim(),
                  });
                }
              },
              child: const Text('저장'),
            ),
          ],
        ),
      ),
    );
    await Future<void>.delayed(const Duration(milliseconds: 250));
    name.dispose();
    start.dispose();
    source.dispose();
    if (result != null) {
      await _request('POST', '/cases', result);
      await _load();
    }
  }

  Future<void> _order() async {
    final q = int.tryParse(_quantity.text), p = int.tryParse(_price.text);
    if (q == null || p == null || q <= 0 || p <= 0) {
      throw Exception('수량과 지정가를 양의 정수로 입력하세요.');
    }
    final draft = <String, dynamic>{
      'side': _side,
      'quantity': q,
      'limit_price_won': p,
    };
    final checked = await _action('check', draft);
    if (!mounted) return;
    final check = OrderCheck.fromJson(checked);
    if (!check.allowed) {
      await _showDialog<void>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('접수 불가'),
          content: Text(check.messages.join('\n')),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('닫기'),
            ),
          ],
        ),
      );
      await _action('close', {'check_id': check.id});
      return;
    }
    Future<void>? presentation;
    final answer = await _showDialog<Map<String, dynamic>>(
      context: context,
      barrierDismissible: false,
      builder: (_) => RiskConfirmation(
        check: check,
        draft: OrderDraft(
          symbol: _run['symbol'],
          side: _side == 'buy' ? OrderSide.buy : OrderSide.sell,
          quantity: q,
          limitPriceWon: p,
          pilotEnabled: _run['pilot_enabled'],
        ),
        onPresented: () {
          presentation = _action('presented', {
            'check_id': check.id,
          }).then<void>((_) {});
          // Attach an error handler immediately; the awaited result below still propagates errors.
          presentation!.catchError((Object _) {});
        },
      ),
    );
    await presentation;
    if (answer == null || answer['deferred'] == true) {
      await _action(answer?['deferred'] == true ? 'defer' : 'close', {
        'check_id': check.id,
        'reason': answer?['reason'] ?? '',
      });
    } else {
      await _action('submit', {
        ...draft,
        'check_id': check.id,
        'reason': answer['reason'] ?? '',
        'warning_acknowledged': true,
        'high_risk_acknowledged': answer['high'] == true,
      });
    }
  }

  Future<void> _copy(bool json) async {
    final data = await _request('GET', '/runs/${_run['id']}/export');
    await Clipboard.setData(
      ClipboardData(
        text: json
            ? const JsonEncoder.withIndent('  ').convert(data['evidence'])
            : data['csv'],
      ),
    );
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('${json ? 'JSON 원본을' : '연구 CSV를'} 복사했습니다.'),
          duration: const Duration(seconds: 2),
        ),
      );
    }
  }

  Widget _metrics(Map value) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      _text('체결 ${value['filled_orders']}건 · 접수 ${value['accepted_orders']}건'),
      _text(
        '계획 준수 ${value['plan_compliant_fills']} / 평가 가능 체결 ${value['plan_evaluated_fills']}건',
      ),
      if (value.containsKey('plan_unregistered_fills'))
        _text(
          '계획 미등록 ${value['plan_unregistered_fills']}건 · 평가 불가 ${value['plan_unavailable_fills']}건 (준수율 제외)',
        ),
      _text(
        '규칙 경고 대상 점검 ${value['rule_qualified_checks']}건 · 그중 접수 ${value['rule_qualified_submissions']}건',
      ),
      _text(
        '실제 경고 노출 ${value['warnings_presented']}건 · 경고 후 명시적 보류 ${value['warned_deferrals']}건',
      ),
      _text(
        '판단 소요 평균 ${value['decision_seconds_mean'] == null ? '측정 없음' : '${(value['decision_seconds_mean'] as num).toStringAsFixed(1)}초'} (${value['decision_timed_count']}건)',
      ),
      _text(
        '최종 평가액 ${value['final_equity_won']}원 · 수익률 ${(value['return_percent'] as num).toStringAsFixed(2)}% · 최대 낙폭 ${(value['max_drawdown_percent'] as num).toStringAsFixed(2)}%',
      ),
    ],
  );

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: Text(_run.isEmpty ? '모의투자 · 과거 장세 실험' : '모의투자 모드'),
      actions: [
        IconButton(
          tooltip: '새로고침',
          onPressed: _busy ? null : () => _perform(_refresh),
          icon: const Icon(Icons.refresh),
        ),
      ],
    ),
    body: Column(
      children: [
        if (_busy && !_dialogOpen) const LinearProgressIndicator(),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.all(12),
            child: Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        if (_retryBody != null && !_busy)
          Wrap(
            children: [
              _button('동일 요청 재시도', _retry),
              _button('서버 상태 다시 읽기', _refresh),
            ],
          ),
        Expanded(
          child: ListView(
            key: ValueKey(_run['id'] ?? 'replay-hub'),
            padding: const EdgeInsets.all(12),
            children: _run.isEmpty ? _hubWidgets() : _runWidgets(),
          ),
        ),
      ],
    ),
  );
  List<Widget> _hubWidgets() => [
    _card([
      const Text(
        '과거 장세를 한 봉씩 재생하며 Pilot을 비교합니다.',
        style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
      ),
      _text(
        '실제 국내 5분봉 사례 4개를 기본 제공합니다. 원본 출처와 결측 안내를 확인한 뒤 시작하세요. 이전 합성 실험 기록은 별도로 보존됩니다.',
      ),
      Wrap(
        children: [
          _button('합성 기능테스트 (선택)', () async {
            await _request('POST', '/practice');
            if (mounted) setState(() => _showSynthetic = true);
            await _load();
          }, key: 'replay-practice'),
          _button('CSV 관리', () async {
            await Navigator.push(
              context,
              MaterialPageRoute<void>(
                builder: (_) => DatasetScreen(repository: widget.repository),
              ),
            );
            await _load();
          }),
          _button('CSV로 사례 등록', _import),
          if (widget.onLegacy != null)
            _button('기존 모의계좌 · 전략', () async {
              Navigator.pop(context);
              widget.onLegacy!();
            }),
        ],
      ),
    ]),
    for (final raw in _hub['cases'] as List? ?? [])
      if (raw['data_kind'] != 'synthetic')
        _caseCard(Map<String, dynamic>.from(raw)),
    ExpansionTile(
      title: const Text('2020·2024 사례 · 실제 5분봉 확보 대기'),
      children: [
        for (final e in _hub['events'] as List? ?? [])
          _card([
            Text(
              '${e['name']}',
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
            _text('${e['note']}'),
            SelectableText('${e['source_url']}'),
          ]),
      ],
    ),
    SwitchListTile(
      key: const ValueKey('replay-show-synthetic'),
      title: const Text('이전 합성 테스트 사례 표시'),
      value: _showSynthetic,
      onChanged: _busy ? null : (v) => setState(() => _showSynthetic = v),
    ),
    if (_showSynthetic)
      for (final raw in _hub['cases'] as List? ?? [])
        if (raw['data_kind'] == 'synthetic')
          _caseCard(Map<String, dynamic>.from(raw)),
    _text('저장된 실험 · ON/OFF 결과는 동일 비교 키·같은 쌍끼리 비교하세요.'),
    for (final r in _hub['runs'] as List? ?? [])
      _card([
        Text(
          '${r['name']} · Pilot ${r['pilot_enabled'] == true ? 'ON' : 'OFF'}',
        ),
        _text(
          '${r['finished'] == true ? '완료' : '진행 중'} · 쌍 ${r['pair_id'].toString().substring(0, 8)} · ${r['sequence']}번째',
        ),
        if (r['summary'] != null) _metrics(r['summary']),
        _button(r['finished'] == true ? '결과 열기' : '이어서 실험', () async {
          _price.clear();
          _setRun(await _request('GET', '/runs/${r['id']}'));
        }),
      ]),
  ];
  Widget _caseCard(Map<String, dynamic> c) {
    final model = c['model'] as Map?;
    return _card([
      Text(
        '${c['name']}',
        style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
      ),
      _text(
        c['data_kind'] == 'synthetic'
            ? '합성 데이터 · 논문의 실제 시장 사례로 사용 불가'
            : c['catalog_id'] != null
            ? '실제 5분봉 · Yahoo Finance 원본 보존'
            : '등록된 과거 데이터 · 원 출처 및 가격 정확성 별도 검증 필요',
      ),
      _text('${c['symbol']} · ${c['provider']}\n${_time(c['replay_from'])}부터'),
      if (c['data_notice'] != null) _text('${c['data_notice']}'),
      if (c['source_url'] != null && c['source_url'] != '')
        ExpansionTile(
          title: const Text('원본 출처 보기'),
          children: [SelectableText('${c['source_url']}')],
        ),
      if (model == null)
        _text(
          c['training_status'] == 'unavailable'
              ? '사례 이전 실제 학습 자료가 부족합니다. AI 예측 없이 행동 피드백을 실험합니다.'
              : 'AI 미학습 · 먼저 학습/검증을 실행하세요.',
        )
      else ...[
        _text(
          '다중분류 로지스틱 회귀 · ${model['quality_gate_passed'] == true ? '검증 기준 통과' : '검증 미달: 예측 보류'}',
        ),
        _text(
          '최종 검증 Macro-F1 ${(model['evaluation']['test']['macro_f1'] as num).toStringAsFixed(3)} · 기준선 ${(model['evaluation']['baseline']['macro_f1'] as num).toStringAsFixed(3)}',
        ),
        _text(
          'Brier ${(model['evaluation']['test']['brier'] as num).toStringAsFixed(3)} · 기준선 ${(model['evaluation']['baseline']['brier'] as num).toStringAsFixed(3)}\n학습 자료 종료 ${_time(model['data_end'])}',
        ),
      ],
      Wrap(
        children: [
          if (model == null && c['training_status'] != 'unavailable')
            _button('AI 학습 / 검증', () async {
              await _request('POST', '/cases/${c['id']}/train');
              await _load();
            }),
          _button('실험 시작', () => _start(c), key: 'replay-start-${c['id']}'),
        ],
      ),
    ]);
  }

  String _direction(dynamic value) =>
      {'up': '상승', 'neutral': '보합', 'down': '하락', 'abstain': '판단 보류'}[value] ??
      '—';

  Widget _predictionReview(Map review) {
    final summary = review['summary'] as Map;
    final accuracy = summary['accuracy'] as num?;
    return _card([
      const Text(
        '당시 AI 예측과 1시간 후 결과',
        style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
      ),
      _text(
        '고유 예측 ${summary['unique_predictions']}건 · 방향 평가 ${summary['evaluated']}건 · 일치 ${summary['correct']}건',
      ),
      _text(
        '방향 일치율 ${accuracy == null ? '평가 없음' : '${(accuracy * 100).toStringAsFixed(1)}%'} · 판단 보류 ${summary['abstained']}건',
      ),
      _text(
        '1시간 미도달 ${summary['pending']}건 · 결측 등 평가 불가 ${summary['unavailable']}건 · 예측 없는 점검 ${summary['unavailable_checks']}건',
      ),
      _text(
        '주문 점검 당시 저장된 예측만 복기합니다. 같은 모델·기준 시각은 한 번 집계하고 판단 보류는 일치율에서 제외합니다. 거래 손익 및 모델의 독립 검증 성능과는 다른 지표입니다.',
      ),
      for (final observation in review['observations'] as List)
        ExpansionTile(
          title: Text(
            '${_time(observation['prediction']['as_of'])} · ${_direction(observation['prediction']['direction'])}',
          ),
          subtitle: Text(switch (observation['outcome']['status']) {
            'resolved' =>
              '실제 ${_direction(observation['outcome']['actual_direction'])} · ${observation['outcome']['correct'] == null
                  ? '판단 보류 · 일치율 제외'
                  : observation['outcome']['correct'] == true
                  ? '방향 일치'
                  : '방향 불일치'}',
            'pending' => '실험 종료 시 1시간 미도달',
            _ => '${observation['outcome']['reason'] ?? '평가 불가'}',
          }),
          children: [
            _text('목표 시각 ${_time(observation['outcome']['target_at'])}'),
            _text(
              '모델 ${observation['prediction']['model_version']} · 관련 점검 ${(observation['check_ids'] as List).length}건',
            ),
            if (observation['outcome']['status'] == 'resolved')
              _text(
                '기준 ${observation['outcome']['base_price_won']}원 → 1시간 후 ${observation['outcome']['target_price_won']}원 · ${(observation['outcome']['return_percent'] as num).toStringAsFixed(2)}%',
              ),
          ],
        ),
    ]);
  }

  List<Widget> _runWidgets() {
    final visible = _run['visible_bars'] as List;
    final price = visible.last['close_won'];
    final finished = _run['finished'] == true;
    final prediction = _run['prediction'] as Map;
    final cases = (_hub['cases'] as List? ?? []).where(
      (c) => c['id'] == _run['case_id'],
    );
    final pairs = (_hub['runs'] as List? ?? []).where(
      (r) =>
          r['id'] != _run['id'] &&
          r['pair_id'] == _run['pair_id'] &&
          r['comparison_key'] == _run['comparison_key'] &&
          r['summary'] != null,
    );
    final linkedRuns = (_hub['runs'] as List? ?? []).where(
      (r) => r['id'] != _run['id'] && r['pair_id'] == _run['pair_id'],
    );
    return [
      _card([
        Text(
          '${_run['case_name']} · Pilot ${_run['pilot_enabled'] == true ? 'ON' : 'OFF'} (고정)',
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
        ),
        _text(
          _run['data_kind'] == 'synthetic'
              ? '합성 연습 · 실제 역사적 가격 아님'
              : '실제 과거 5분봉 · ${_run['provenance']}',
        ),
        if (_run['condition_order'] is List)
          _text(
            '${_run['allocation_method'] == 'server_randomized' ? '서버 무작위 배정' : '사용자 선택'} · ${_run['sequence']}번째 조건 / 2 · ${(_run['condition_order'] as List).join(' → ')}',
          ),
        if (_run['data_notice'] != null) _text('${_run['data_notice']}'),
        if (_run['market_notice'] != null) _text('${_run['market_notice']}'),
        _text(
          '가상 시각 ${_time(_run['virtual_at'])}\n진행 ${_run['step']} / ${_run['total_steps']} · 현재가 $price원',
        ),
        SizedBox(
          height: 150,
          child: CustomPaint(
            painter: _ReplayChart(
              visible.map((b) => (b['close_won'] as num).toDouble()).toList(),
              visible
                  .map((b) => DateTime.tryParse('${b['opened_at']}'))
                  .toList(),
            ),
          ),
        ),
        _text('완료 봉 종가 · 관측 순서로 표시하며 장간·결측 구간은 선을 끊습니다.'),
        _text(
          '현금 ${_run['cash_won']}원 · 주문 가능 ${_run['available_cash_won']}원\n보유 ${_run['quantity']}주 · 총 평가액 ${_run['equity_won']}원',
        ),
        if (!finished)
          Wrap(
            children: [
              if (_run['step'] < _run['total_steps'])
                _button('다음 5분봉', () async {
                  await _action('advance');
                }, key: 'replay-next'),
              _button('실험 종료', () async {
                await _action('finish');
                await _load();
              }, key: 'replay-finish'),
            ],
          ),
        _button('사례 목록으로', () async {
          setState(() {
            _run = {};
            _retryBody = null;
          });
          await _load();
        }),
      ]),
      _card([
        const Text(
          'AI · 1시간 방향 참고',
          style: TextStyle(fontWeight: FontWeight.bold),
        ),
        _text('${prediction['message']}'),
        if (prediction['probabilities'] case final Map probabilities) ...[
          _text(
            '상승 ${((probabilities['up'] as num) * 100).toStringAsFixed(1)}% · 보합 ${((probabilities['neutral'] as num) * 100).toStringAsFixed(1)}% · 하락 ${((probabilities['down'] as num) * 100).toStringAsFixed(1)}%',
          ),
          _text(
            '판단: ${{'up': '상승', 'neutral': '보합', 'down': '하락', 'abstain': '보류'}[prediction['direction']]}',
          ),
          _text('${prediction['factors']}'),
        ],
        if (_run['data_kind'] == 'synthetic')
          const Text('합성 자료 학습 결과이며 실제 시장 예측 성능을 의미하지 않습니다.'),
      ]),
      if (!finished)
        _card([
          const Text(
            '모의 지정가 주문',
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
          ),
          _text(
            _run['plan'] == null
                ? '계획 미등록 · 준수율 산정에서 제외'
                : '사전 계획: ${_run['plan']['side'] == 'buy' ? '매수' : '매도'} ${_run['plan']['entry_min_won']}~${_run['plan']['entry_max_won']}원 · 누적 ${_run['plan']['max_amount_won']}원',
          ),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'buy', label: Text('매수')),
              ButtonSegment(value: 'sell', label: Text('매도')),
            ],
            selected: {_side},
            onSelectionChanged: _busy
                ? null
                : (v) => setState(() => _side = v.first),
          ),
          TextField(
            key: const ValueKey('replay-quantity'),
            controller: _quantity,
            enabled: !_busy,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(labelText: '수량 (주)'),
          ),
          TextField(
            key: const ValueKey('replay-price'),
            controller: _price,
            enabled: !_busy,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(labelText: '지정가 (원)'),
          ),
          Wrap(
            children: [
              _button('현재가 입력', () async {
                _price.text = '$price';
              }),
              _button('주문 점검', _order, key: 'replay-order'),
            ],
          ),
          const Text(
            '접수 후 다음 봉으로 진행해야 체결 여부가 결정됩니다. 주문당 100만 원 한도와 5분 쿨다운은 Pilot OFF에도 적용됩니다.',
          ),
        ]),
      for (final o in (_run['orders'] as List).reversed)
        _card([
          Text(
            '${o['side'] == 'buy' ? '매수' : '매도'} ${o['quantity']}주 · 지정가 ${o['price']}원 · ${{'accepted': '접수', 'filled': '체결', 'cancelled': '취소'}[o['status']]}',
          ),
          if (o['fill_price'] != null)
            _text('체결가 ${o['fill_price']}원 · 수수료 ${o['fee']}원'),
          if (o['status'] == 'accepted' && !finished)
            _button('주문 취소', () async {
              await _action('cancel', {'order_id': o['id']});
            }),
        ]),
      if (finished && _run['prediction_review'] is Map)
        _predictionReview(_run['prediction_review'] as Map),
      if (finished)
        if (_run['decisions'] case final List decisions)
          _card([
            ExpansionTile(
              title: Text('판단 기록 · ${decisions.length}건'),
              expandedCrossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  '주문 점검 당시의 선택과 입력 이유입니다. 이유를 입력하지 않은 기록은 추정하지 않습니다.',
                ),
                for (final decision in decisions)
                  ListTile(
                    title: Text(
                      '${_time(decision['virtual_at'])} · ${{'deferred': '주문 보류', 'submitted': '주문 진행', 'closed': '창 닫기', 'expired': '점검 만료', 'unresolved_at_finish': '종료 시 미결', 'pending': '미결'}[decision['decision']] ?? decision['decision']}',
                    ),
                    subtitle: Text(
                      (decision['reason'] as String? ?? '').isEmpty
                          ? '입력한 이유 없음'
                          : '${decision['reason']}',
                    ),
                  ),
              ],
            ),
          ]),
      if (finished)
        _card([
          const Text(
            '연구 관찰 결과',
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
          ),
          _metrics(_run['summary']),
          if ((_run['summary'] as Map)['warning_types'] case final List types)
            ExpansionTile(
              title: const Text('유형별 행동 피드백'),
              expandedCrossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _text(
                  '각 유형에 해당한 점검 횟수입니다. 한 점검이 여러 유형에 포함될 수 있습니다. OFF의 탐지는 종료 후 평가값이며 경고 노출이 아닙니다.',
                ),
                for (final type in types)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('${type['title']} · 탐지 ${type['detected']}회'),
                        _text(
                          '계획 예외 ${type['exempt']}회 · 판단 불가 ${type['unavailable']}회 · 위험 차단 ${type['blocked']}회',
                        ),
                        _text(
                          '경고 표시 ${type['presented']}회 · 표시 후 보류 ${type['deferred_after_presentation']}회 · 진행 ${type['submitted_after_presentation']}회',
                        ),
                        _text(
                          '표시 후 닫기 ${type['closed_after_presentation']}회 · 미결/만료 ${type['unresolved_after_presentation']}회',
                        ),
                        _text(
                          '해당 점검의 접수 ${type['submitted']}건 · 체결 ${type['filled']}건 · 취소 ${type['cancelled']}건',
                        ),
                        if (type['advice'] != null) _text('${type['advice']}'),
                      ],
                    ),
                  ),
              ],
            ),
          _text(
            '경고 대상 여부는 OFF에서도 같은 규칙으로 사후 계산합니다. OFF 실험 중에는 노출하지 않습니다. 닫기·만료는 명시적 보류와 별도로 기록합니다.',
          ),
          for (final pair in pairs) ...[
            _text(
              '같은 실험 쌍 · Pilot ${pair['pilot_enabled'] == true ? 'ON' : 'OFF'} · ${pair['sequence']}번째 결과',
            ),
            _metrics(pair['summary']),
          ],
          _text(
            '반복 점검은 독립 표본이 아닙니다. 같은 장세 재경험에 따른 학습 효과와 ON/OFF 순서 효과를 통제해야 합니다. 수익률만으로 이성적 판단 개선을 결론내리지 마세요.',
          ),
          Wrap(
            children: [
              _button('연구 CSV 복사', () => _copy(false)),
              _button('원본 JSON 복사', () => _copy(true)),
              if (cases.isNotEmpty &&
                  _run['sequence'] == 1 &&
                  linkedRuns.isEmpty)
                _button(
                  '같은 조건 · 반대 Pilot',
                  () => _start(
                    Map<String, dynamic>.from(cases.first),
                    pair: _run,
                  ),
                ),
              if (linkedRuns.isNotEmpty)
                _button('짝 실험 열기', () async {
                  _price.clear();
                  _setRun(
                    await _request('GET', '/runs/${linkedRuns.first['id']}'),
                  );
                }),
            ],
          ),
        ]),
      if (finished)
        AIReplayReview(
          key: ValueKey('ai-review-${_run['id']}'),
          repository: widget.repository,
          runId: _run['id'] as String,
        ),
    ];
  }
}

class _ReplayChart extends CustomPainter {
  _ReplayChart(this.prices, this.times);
  final List<double> prices;
  final List<DateTime?> times;
  @override
  void paint(Canvas canvas, Size size) {
    if (prices.length < 2) return;
    final low = prices.reduce(math.min), high = prices.reduce(math.max);
    final span = math.max(1, high - low);
    final path = Path();
    for (var i = 0; i < prices.length; i++) {
      final x = i * size.width / (prices.length - 1),
          y = 10 + (high - prices[i]) / span * (size.height - 20);
      final connected =
          i > 0 &&
          times[i] != null &&
          times[i - 1] != null &&
          times[i]!.difference(times[i - 1]!) == const Duration(minutes: 5);
      if (!connected) {
        path.moveTo(x, y);
      } else {
        path.lineTo(x, y);
      }
      if (!connected || i == prices.length - 1) {
        canvas.drawCircle(
          Offset(x, y),
          2.5,
          Paint()..color = const Color(0xFF76DDB7),
        );
      }
    }
    canvas.drawPath(
      path,
      Paint()
        ..color = const Color(0xFF76DDB7)
        ..strokeWidth = 2
        ..style = PaintingStyle.stroke,
    );
  }

  @override
  bool shouldRepaint(_ReplayChart oldDelegate) => oldDelegate.prices != prices;
}
