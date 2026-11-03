import 'package:flutter/material.dart';
import '../domain/workspace_repository.dart';
import 'design_bindings.dart';
import 'feedback_screen.dart';

class JournalScreen extends StatefulWidget {
  const JournalScreen({super.key, required this.repository});
  final WorkspaceRepository repository;
  @override
  State<JournalScreen> createState() => _JournalScreenState();
}

class _JournalScreenState extends State<JournalScreen> {
  Map<String, dynamic>? _data;
  bool _loading = false;
  String? _error;
  int _days = 30;
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load({bool more = false}) async {
    if (_loading) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final offset = more ? (_data?['next_offset'] ?? 0) : 0;
      final result = await widget.repository.workspaceRequest(
        'GET',
        '/v1/journal?days=$_days&offset=$offset',
      );
      if (!mounted) return;
      if (more && _data != null) {
        final previous = (_data!['items'] as List);
        final ids = previous.map((v) => v['order_id']).toSet();
        result['items'] = [
          ...previous,
          ...(result['items'] as List).where(
            (v) => !ids.contains(v['order_id']),
          ),
        ];
      }
      setState(() => _data = result);
    } catch (_) {
      if (mounted) setState(() => _error = '매매일지를 불러오지 못했습니다. 다시 시도하세요.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _editNote(Map<String, dynamic> row) async {
    final input = TextEditingController(
      text: row['review_note'] as String? ?? '',
    );
    final result = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('거래 후 복기 메모'),
        content: TextField(
          controller: input,
          maxLength: 2000,
          maxLines: 5,
          decoration: const InputDecoration(hintText: '주문 당시 이유는 변경하지 않습니다.'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, input.text),
            child: const Text('저장'),
          ),
        ],
      ),
    );
    // The dialog may still be animating when its future completes.
    if (result == null || !mounted) return;
    try {
      final saved = await widget.repository.workspaceRequest(
        'PUT',
        '/v1/orders/${row['order_id']}/note',
        body: {'text': result},
      );
      if (mounted) {
        setState(() {
          row['review_note'] = saved['text'];
          row['review_updated_at'] = saved['updated_at'];
        });
      }
    } catch (_) {
      if (mounted) setState(() => _error = '메모 저장에 실패했습니다. 다시 시도하세요.');
    }
  }

  String percent(dynamic n) =>
      n == null ? '평가 기록 없음' : '${((n as num) * 100).toStringAsFixed(1)}%';
  String money(dynamic n) => n == null ? '확인 불가' : '${won(int.parse('$n'))}원';
  String time(dynamic s) => s == null
      ? '—'
      : DateTime.parse('$s').toLocal().toString().split('.').first;
  String direction(dynamic v) => switch (v) {
    'up' => '상승',
    'neutral' => '중립',
    'down' => '하락',
    'abstain' => '판단 보류',
    _ => '평가 대기',
  };
  static const warningNames = {
    'fomo': '급등 추격',
    'panic': '공포매도',
    'revenge': '복수매매',
    'overtrading': '과매매',
    'plan': '계획 위반',
  };
  Widget text(String value) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 6),
    child: Text(value),
  );
  Widget _entry(Map<String, dynamic> row) {
    final p = row['prediction'] as Map<String, dynamic>? ?? {};
    final b = row['behavior'] as Map<String, dynamic>? ?? {};
    final fill = row['fill'] as Map<String, dynamic>?;
    final outcome = row['prediction_outcome'] as Map<String, dynamic>? ?? {};
    final plan = row['plan'] as Map<String, dynamic>?;
    return ExpansionTile(
      tilePadding: EdgeInsets.zero,
      title: Text(
        '${row['symbol']} · ${row['side'] == 'buy' ? '매수' : '매도'} ${row['quantity']}주 · ${orderStatus(row['status'] as String)}',
      ),
      subtitle: Text(
        '${time(row['created_at'])}\n지정가 ${money(row['limit_price_won'])}',
      ),
      expandedCrossAxisAlignment: CrossAxisAlignment.start,
      children: [
        text(
          '거래 이유: ${(row['trade_reason'] as String? ?? '').isEmpty ? '미입력' : row['trade_reason']}',
        ),
        text('복기 메모: ${row['review_note'] ?? ''}'),
        TextButton(
          onPressed: () => _editNote(row),
          child: const Text('복기 메모 작성·수정'),
        ),
        text(
          plan == null
              ? '당시 계획: 미등록'
              : '당시 계획: ${plan['entry_condition']}\n금액 한도 ${money(plan['max_amount_won'])} · 손절 ${money(plan['stop_loss_won'])}',
        ),
        text(
          b['enabled'] == true
              ? '당시 행동 점수 ${b['score']}/100${b['partial'] == true ? ' · 일부 판단 불가' : ''}'
              : '당시 행동 분석 꺼짐 / 이전 기록',
        ),
        for (final i in b['items'] as List? ?? [])
          if (i['status'] != 'not_applicable')
            text('${i['title']} (+${i['points']}): ${i['message']}'),
        for (final reason in row['blocking_reasons'] as List? ?? [])
          text('차단: $reason'),
        if (p['status'] == 'available') ...[
          text(
            '당시 AI: 상승 ${percent(p['up'])} · 중립 ${percent(p['neutral'])} · 하락 ${percent(p['down'])}',
          ),
          text(
            '모델 ${p['model_version']}\n대상 ${time(p['as_of'])} → ${time(p['target_at'])}',
          ),
          text(
            outcome['status'] == 'resolved'
                ? '1시간 실제 방향: ${direction(outcome['actual_direction'])}\n실제 가격 변화 ${double.parse('${outcome['return_percent']}').toStringAsFixed(2)}% · ${outcome['correct'] == null
                      ? '판단 보류로 적중 평가 제외'
                      : outcome['correct'] == true
                      ? '방향 일치'
                      : '방향 불일치'}'
                : '1시간 결과: 대상 시점 데이터 대기',
          ),
        ] else
          text('당시 AI: ${p['message'] ?? '학습/분석 데이터 대기'}'),
        text(
          fill == null
              ? '체결 없음 · 손익 계산 제외'
              : '체결가 ${money(fill['price_won'])} · 수수료 ${money(fill['fee_won'])}\n${row['side'] == 'sell' ? '순실현손익 ${money(fill['realized_pnl_won'])}' : '매수 원가에 수수료 포함'}',
        ),
        const Divider(),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final summary = _data?['summary'] as Map<String, dynamic>? ?? {};
    final decisions =
        summary['warning_decisions'] as Map<String, dynamic>? ?? {};
    return Scaffold(
      appBar: AppBar(
        title: const Text('매매일지 · 피드백'),
        actions: [
          DropdownButton<int>(
            value: _days,
            items: [
              for (final d in [7, 30, 90])
                DropdownMenuItem(value: d, child: Text('$d일')),
            ],
            onChanged: _loading
                ? null
                : (v) {
                    setState(() => _days = v!);
                    _load();
                  },
          ),
          IconButton(
            tooltip: '일지 새로고침',
            onPressed: _loading ? null : () => _load(),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => _load(),
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            if (_loading) const LinearProgressIndicator(),
            if (_error != null) text(_error!),
            if (_data != null) ...[
              text('최근 $_days일 · 체결 ${summary['filled_orders']}건'),
              text(
                '순실현손익 ${money(summary['realized_pnl_won'])}${summary['pnl_complete'] == true ? '' : ' · 일부 원가 미확인'}',
              ),
              text('계획 준수율 ${percent(summary['plan_compliance'])}'),
              text(
                '평가 가능 ${summary['plan_evaluated']}건 / 준수 ${summary['plan_adherent']}건\n계획 미등록 ${summary['plan_unregistered']}건 · 판단 불가 ${summary['plan_unavailable']}건',
              ),
              text(
                'AI 방향 일치율 ${percent(summary['prediction_accuracy'])}\n평가 ${summary['prediction_evaluated']}건 · 판단 보류 ${summary['prediction_abstained']}건 · 결과 대기 ${summary['prediction_pending']}건',
              ),
              const Divider(height: 32),
              const Text('반복 경고와 피드백', style: TextStyle(fontSize: 22)),
              OutlinedButton.icon(
                icon: const Icon(Icons.insights),
                label: const Text('피드백 효과 기록 · ON/OFF 비교'),
                onPressed: () => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) =>
                        FeedbackScreen(repository: widget.repository),
                  ),
                ),
              ),
              for (final e
                  in (summary['warning_counts'] as Map<String, dynamic>? ?? {})
                      .entries)
                text('${warningNames[e.key] ?? e.key}: ${e.value}회'),
              text(
                '경고 후 제출 시도 ${decisions['submitted'] ?? 0} · 보류 ${decisions['dismissed'] ?? 0} · 미결정 ${decisions['pending'] ?? 0}',
              ),
              for (final f in _data!['feedback'] as List) text('$f'),
              const Divider(height: 32),
              const Text('주문 당시 기록', style: TextStyle(fontSize: 22)),
              if ((_data!['items'] as List).isEmpty) text('아직 주문 기록이 없습니다.'),
              for (final row in _data!['items'] as List)
                _entry(row as Map<String, dynamic>),
              if (_data!['next_offset'] != null)
                OutlinedButton(
                  onPressed: _loading ? null : () => _load(more: true),
                  child: const Text('이전 기록 더 보기'),
                ),
              const Divider(height: 32),
              for (final note in _data!['notes'] as List) text('$note'),
            ],
          ],
        ),
      ),
    );
  }
}
