import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../domain/workspace_repository.dart';

class FeedbackScreen extends StatefulWidget {
  const FeedbackScreen({super.key, required this.repository});
  final WorkspaceRepository repository;

  @override
  State<FeedbackScreen> createState() => _FeedbackScreenState();
}

class _FeedbackScreenState extends State<FeedbackScreen> {
  Map<String, dynamic>? _data;
  bool _loading = false, _exporting = false;
  String? _error;
  int _days = 30;
  static const states = {
    'blocked': '위험 규칙 차단',
    'dismissed': '명시적 보류',
    'rejected': '제출 후 거절',
    'accepted': '접수·미체결',
    'filled': '체결',
    'cancelled': '접수 후 취소',
    'pending': '미결정',
    'expired': '만료·결정 미확인',
  };

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load({bool more = false}) async {
    if (_loading) return;
    final previous = _data;
    final offset = more ? (_data?['next_offset'] ?? 0) : 0;
    setState(() {
      _loading = true;
      _error = null;
      if (!more) _data = null;
    });
    try {
      final data = await widget.repository.workspaceRequest(
        'GET',
        '/v1/feedback?days=$_days&offset=$offset',
      );
      if (!mounted) return;
      if (more && previous != null) {
        final items = previous['items'] as List;
        final ids = items.map((e) => e['check_id']).toSet();
        data['items'] = [
          ...items,
          ...(data['items'] as List).where((e) => !ids.contains(e['check_id'])),
        ];
      }
      setState(() => _data = data);
    } catch (_) {
      if (mounted) setState(() => _error = '피드백 기록을 불러오지 못했습니다. 다시 시도하세요.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _export() async {
    setState(() => _exporting = true);
    try {
      final result = await widget.repository.workspaceRequest(
        'GET',
        '/v1/feedback/export?days=$_days',
      );
      if (!mounted) return;
      await Clipboard.setData(ClipboardData(text: result['csv'] as String));
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              '${result['rows']}건 CSV를 복사했습니다. 텍스트 파일에 붙여 넣어 .csv로 저장하세요.',
            ),
          ),
        );
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('CSV 복사에 실패했습니다. 다시 시도하세요.')),
        );
      }
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  String percent(dynamic value) => value == null
      ? '평가 기록 없음'
      : '${((value as num) * 100).toStringAsFixed(1)}%';
  String time(dynamic value) => value == null
      ? '기록 없음'
      : DateTime.parse('$value').toLocal().toString().split('.').first;
  Widget line(String text) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 5),
    child: Text(text),
  );

  Widget _group(String label, Map group) => Card(
    color: Theme.of(context).colorScheme.surface,
    shape: const RoundedRectangleBorder(
      side: BorderSide(color: Color(0xFF303034)),
    ),
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Pilot $label', style: Theme.of(context).textTheme.titleLarge),
          line('수동 점검 ${group['checks']}건 · 체결 ${group['filled']}건'),
          line('계획 준수율 ${percent(group['plan_compliance'])}'),
          line(
            '평가 ${group['plan_evaluated']}건 중 준수 ${group['plan_adherent']}건\n'
            '계획 미등록 ${group['plan_unregistered']} · 판단 불가 ${group['plan_unavailable']}',
          ),
          line(
            '확인 시간 ${group['mean_decision_seconds'] == null ? '측정 기록 없음' : '${(group['mean_decision_seconds'] as num).toStringAsFixed(1)}초'}'
            ' · ${group['decision_samples']}건',
          ),
        ],
      ),
    ),
  );

  Widget _warning(Map row) => ExpansionTile(
    tilePadding: EdgeInsets.zero,
    title: Text('${row['title']} · 조건 해당 ${row['detected']}회'),
    subtitle: Text(
      '표시 기록 ${row['presented']}회 · 자발적 보류율 ${percent(row['defer_rate'])}',
    ),
    expandedCrossAxisAlignment: CrossAxisAlignment.start,
    children: [
      line(
        '보류율 분모 ${row['voluntary_resolved']}건 · 표시 미기록/차단 ${row['unobserved']}건',
      ),
      for (final entry in (row['outcomes'] as Map).entries)
        line('${states[entry.key] ?? entry.key}: ${entry.value}건'),
      if (row['feedback'] != null) line('${row['feedback']}'),
    ],
  );

  Widget _record(Map row) => ExpansionTile(
    tilePadding: EdgeInsets.zero,
    title: Text(
      '${row['symbol']} · Pilot ${row['pilot_enabled'] == true ? 'ON' : 'OFF'} · ${states[row['outcome']] ?? row['outcome']}',
    ),
    subtitle: Text(
      '${time(row['created_at'])}\n${row['side'] == 'buy' ? '매수' : '매도'} ${row['quantity']}주',
    ),
    expandedCrossAxisAlignment: CrossAxisAlignment.start,
    children: [
      line('화면 표시 ${time(row['presented_at'])}\n결정 ${time(row['decided_at'])}'),
      line(
        row['pilot_enabled'] == true
            ? '당시 점수 ${row['score'] ?? '확인 불가'}${row['partial'] == true ? ' · 일부 판단 불가' : ''}'
            : '행동 경고 OFF · 위험 없음이라는 의미가 아닙니다.',
      ),
      for (final item in row['rule_items'] as List? ?? [])
        if (item['status'] != 'not_applicable')
          line('${item['title']}: ${item['message']}'),
      line(
        '규칙 버전 ${row['rule_version'] ?? '미기록'} · 시세 출처 ${row['source'] ?? '미확인'}',
      ),
      line('점검 ID ${row['check_id']}'),
      if (row['decision'] == 'dismissed')
        line(
          (row['decision_reason'] as String? ?? '').isEmpty
              ? '보류 이유: 입력한 이유 없음'
              : '보류 이유: ${row['decision_reason']}',
        ),
    ],
  );

  @override
  Widget build(BuildContext context) {
    final data = _data;
    return Scaffold(
      appBar: AppBar(
        backgroundColor: Theme.of(context).colorScheme.surface,
        surfaceTintColor: Colors.transparent,
        title: const Text('피드백 효과 기록'),
        actions: [
          DropdownButton<int>(
            value: _days,
            items: [
              for (final d in [7, 30, 90])
                DropdownMenuItem(value: d, child: Text('$d일')),
            ],
            onChanged: _loading || _exporting
                ? null
                : (value) {
                    setState(() => _days = value!);
                    _load();
                  },
          ),
          IconButton(
            tooltip: '피드백 새로고침',
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
            line('같은 계정의 모의투자 기록을 비교합니다.\nON/OFF 차이가 방지 효과를 입증하지는 않습니다.'),
            if (_loading) const LinearProgressIndicator(),
            if (_error != null) ...[
              line(_error!),
              OutlinedButton(
                onPressed: _loading ? null : () => _load(),
                child: const Text('다시 시도'),
              ),
            ],
            if (data != null) ...[
              line(
                '조회 ${time(data['window']['start'])} ~ ${time(data['window']['end'])}',
              ),
              _group('ON', data['groups']['on'] as Map),
              _group('OFF', data['groups']['off'] as Map),
              line(
                data['compliance_difference_pp'] == null
                    ? 'ON/OFF 차이: 양쪽에 평가 가능한 체결 기록이 필요합니다.'
                    : '계획 준수율 차이 (ON − OFF): ${(data['compliance_difference_pp'] as num).toStringAsFixed(1)}%p',
              ),
              const Divider(height: 32),
              const Text('경고 후 선택과 다음 거래 원칙', style: TextStyle(fontSize: 20)),
              for (final row in data['warning_types'] as List)
                _warning(row as Map),
              const Divider(height: 32),
              const Text('점검·보류·주문 처리 이력', style: TextStyle(fontSize: 20)),
              if ((data['items'] as List).isEmpty) line('새로 기록한 수동 점검이 없습니다.'),
              for (final row in data['items'] as List) _record(row as Map),
              if (data['next_offset'] != null)
                OutlinedButton(
                  onPressed: _loading ? null : () => _load(more: true),
                  child: const Text('이전 점검 더 보기'),
                ),
              const Divider(height: 32),
              OutlinedButton.icon(
                key: const ValueKey('feedback-export'),
                onPressed: _exporting || _loading ? null : _export,
                icon: const Icon(Icons.copy),
                label: Text(_exporting ? '복사 중…' : '연구 기록 CSV 복사'),
              ),
              line('이름·이메일·거래 이유·복기 메모 본문은 내보내지 않습니다. 종목·시각·점검 ID는 포함됩니다.'),
              line(
                '비교 제외: 자동매매 ${data['excluded']['automation'] ?? 0}건 · 도입 전 ${data['excluded']['legacy'] ?? 0}건',
              ),
              for (final note in data['notes'] as List) line('$note'),
            ],
          ],
        ),
      ),
    );
  }
}
