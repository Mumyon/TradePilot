import 'package:flutter/material.dart';
import '../domain/workspace_repository.dart';
import 'chatgpt_analysis_panel.dart';
import 'market_quote_status.dart';
import 'trading_layout_bindings.dart';
import '../domain/trading_models.dart' show OrderReceipt;

class TradeJournalScreen extends StatefulWidget {
  const TradeJournalScreen({
    super.key,
    this.repository,
    this.localOrders = const [],
    this.stockNames = const {},
  });
  final WorkspaceRepository? repository;
  final List<OrderReceipt> localOrders;
  final Map<String, String> stockNames;
  @override
  State<TradeJournalScreen> createState() => _TradeJournalScreenState();
}

class _TradeJournalScreenState extends State<TradeJournalScreen> {
  Map<String, dynamic>? _data;
  bool _loading = false;
  String? _error;
  int _days = 30;
  String _comparisonFilter = 'all';
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load({bool more = false}) async {
    final repo = widget.repository;
    if (_loading || repo == null) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final offset = more ? (_data?['next_offset'] ?? 0) : 0;
      final result = await repo.workspaceRequest(
        'GET',
        '/v1/journal?days=$_days&offset=$offset&include_pretrade=true',
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
        final earlier = _data!['deferred_checks'] as List? ?? [];
        final seen = earlier.map((row) => row['check_id']).toSet();
        result['deferred_checks'] = [
          ...earlier,
          ...(result['deferred_checks'] as List? ?? []).where(
            (row) => !seen.contains(row['check_id']),
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
    var note = row['review_note'] as String? ?? '';
    final result = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('거래 후 복기 메모'),
        content: TextFormField(
          initialValue: note,
          onChanged: (value) => note = value,
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
            onPressed: () => Navigator.pop(context, note),
            child: const Text('저장'),
          ),
        ],
      ),
    );
    if (result == null || !mounted) return;
    try {
      final saved = await widget.repository!.workspaceRequest(
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

  Future<void> _openAiReview(Map row, {required bool deferred}) {
    final sampleId = row['sample_id'] as String?;
    final target = sampleId != null
        ? 'samples'
        : (deferred ? 'deferred' : 'orders');
    final id = sampleId ?? row[deferred ? 'check_id' : 'order_id'];
    return Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (context) => Scaffold(
          appBar: AppBar(title: const Text('매매일지 AI 복기')),
          body: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text(
                "${row['symbol_name'] ?? row['symbol']} · "
                "${deferred ? '보류' : orderStatus('${row['status']}')}",
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 10),
              ChatGPTAnalysisPanel.decision(
                repository: widget.repository!,
                decisionPath: '/v1/journal/$target/$id/ai-review',
                decisionTitle: sampleId == null ? '거래별 복기와 피드백' : '시세 재현 거래 복기',
                journalConsentMessage: sampleId == null
                    ? null
                    : '선택한 시세 재현 모의 매매 기록을 OpenAI에 전달해 복기를 생성합니다.',
                journalReview: true,
                autoGenerate: false,
              ),
            ],
          ),
        ),
      ),
    );
  }

  String money(Object? value) {
    final amount = int.tryParse('$value');
    return amount == null ? '—' : '${won(amount)}원';
  }

  bool _matchesComparison(Map row) {
    final example = row['sample_id'] != null;
    final comparison = row['advice_comparison'] as Map?;
    return switch (_comparisonFilter) {
      'matched' => !example && comparison?['matched'] == true,
      'different' => !example && comparison?['matched'] == false,
      'wait' =>
        !example &&
            comparison?['matched'] == false &&
            const {'관망', '보류'}.contains(comparison?['advice']) &&
            row['fill'] != null,
      'example' => example,
      _ => true,
    };
  }

  Widget _entry(Map row, {required bool deferred}) {
    final sampleId = row['sample_id'] as String?;
    final plan = row['plan'] as Map?;
    final symbol = '${row['symbol']}';
    final name = row['symbol_name'] ?? widget.stockNames[symbol] ?? symbol;
    final advice = row['pretrade_ai'] as Map?;
    final comparison = row['advice_comparison'] as Map?;
    final fill = row['fill'] as Map?;
    final side = row['side'] == 'buy' ? '매수' : '매도';
    final status = deferred ? '보류' : orderStatus('${row['status']}');
    final actual = deferred
        ? '보류'
        : fill != null
        ? side
        : '체결 없음';
    final date = koreanMarketTime(row[deferred ? 'decided_at' : 'created_at']);
    final judgment = comparison?['advice'];
    final theme = Theme.of(context);
    final grade = switch (comparison?['matched']) {
      true => '일치',
      false => '불일치',
      _ => '비교 제외',
    };
    final memo = row[deferred ? 'reason' : 'review_note'] as String? ?? '';
    final tradeReason = row['trade_reason'] as String? ?? '';
    return ExpansionTile(
      key: ValueKey(sampleId ?? row[deferred ? 'check_id' : 'order_id']),
      tilePadding: EdgeInsets.zero,
      expandedAlignment: Alignment.centerLeft,
      title: Row(
        children: [
          Expanded(child: Text('$name', style: theme.textTheme.titleMedium)),
          const SizedBox(width: 8),
          Text(status, style: theme.textTheme.bodySmall),
        ],
      ),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 5),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${date ?? '시각 미확인'}${sampleId != null ? ' · 시세 재현' : ''} · $side ${row['quantity']}주',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: 4),
            Text(
              '${sampleId == null ? '주문 전 AI' : '재현 AI 판단'} ${judgment ?? (advice?['status'] == 'available' ? '판단 미분류' : '기록 없음')}'
              '  /  ${sampleId == null ? '내 결정' : '재현 결정'} $actual  ·  $grade',
              style: theme.textTheme.bodyMedium,
            ),
          ],
        ),
      ),
      expandedCrossAxisAlignment: CrossAxisAlignment.start,
      childrenPadding: const EdgeInsets.only(bottom: 12),
      children: [
        if (advice?['status'] == 'available') TradeAiEvidence(review: advice!),
        Text('지정가 ${money(row['limit_price_won'])}'),
        if (fill != null)
          Text(
            '체결가 ${money(fill['price_won'])} · 수수료 ${money(fill['fee_won'])}'
            '${side == '매도' ? '\n순실현손익 ${money(fill['realized_pnl_won'])}' : ''}',
          ),
        if (sampleId != null && plan != null)
          Text(
            '계획 진입 범위 ${money(plan['entry_min_won'])}~${money(plan['entry_max_won'])}',
          ),
        if (row['warning'] case final String warning) Text(warning),
        if (row['market_analysis'] case final String analysis)
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: const Text('ChatGPT 주가 분석'),
            subtitle: const Text('당시 토스증권 5분봉 기준'),
            children: [SelectableText(analysis)],
          ),
        if (tradeReason.isNotEmpty) Text('거래 이유 · $tradeReason'),
        if (memo.isNotEmpty) Text('${deferred ? '보류 이유' : '복기 메모'} · $memo'),
        if (widget.repository != null)
          OutlinedButton.icon(
            onPressed: () => _openAiReview(row, deferred: deferred),
            icon: const Icon(Icons.auto_awesome_outlined),
            label: const Text('AI 복기 및 피드백'),
          ),
        if (!deferred && sampleId == null)
          TextButton(
            onPressed: () => _editNote(row as Map<String, dynamic>),
            child: Text(memo.isEmpty ? '복기 메모 쓰기' : '복기 메모 수정'),
          ),
      ],
    );
  }

  Widget _periodPicker() => Wrap(
    spacing: 16,
    children: [
      for (final days in [7, 30, 90])
        Semantics(
          selected: _days == days,
          child: DecoratedBox(
            decoration: BoxDecoration(
              border: Border(
                bottom: BorderSide(
                  width: 2,
                  color: _days == days
                      ? Theme.of(context).colorScheme.onSurface
                      : Colors.transparent,
                ),
              ),
            ),
            child: TextButton(
              style: TextButton.styleFrom(
                minimumSize: const Size(0, 44),
                padding: const EdgeInsets.symmetric(horizontal: 4),
                foregroundColor: _days == days
                    ? Theme.of(context).colorScheme.onSurface
                    : Theme.of(context).colorScheme.onSurfaceVariant,
              ),
              onPressed: _loading
                  ? null
                  : () {
                      if (days == _days) return;
                      setState(() {
                        _days = days;
                        _comparisonFilter = 'all';
                        _data = null;
                      });
                      _load();
                    },
              child: Text('최근 $days일'),
            ),
          ),
        ),
    ],
  );

  @override
  Widget build(BuildContext context) {
    final samples = (_data?['sample_entries'] as List? ?? []).whereType<Map>();
    final summary = _data?['summary'] as Map?;
    final stats = summary?['advice_comparison'] as Map?;
    final deferredStats = summary?['deferred_advice_comparison'] as Map?;
    int count(String key) =>
        (stats?[key] as int? ?? 0) + (deferredStats?[key] as int? ?? 0);
    final matched = count('matched');
    final different = count('different');
    final wait = stats?['traded_after_wait'] as int? ?? 0;
    final compared = matched + different;
    final filters = {
      'all': '전체',
      if (matched > 0) 'matched': '일치 $matched건',
      if (different > 0) 'different': '불일치 $different건',
      if (wait > 0) 'wait': '관망·보류 후 체결 $wait건',
      if (samples.isNotEmpty) 'example': '시세 재현 보기',
    };
    final entries =
        [
          for (final row in samples)
            (
              row: row,
              deferred: row['status'] == 'deferred',
              date: '${row['created_at'] ?? row['decided_at']}',
            ),
          for (final row in (_data?['items'] as List? ?? []).whereType<Map>())
            (row: row, deferred: false, date: '${row['created_at']}'),
          for (final row
              in (_data?['deferred_checks'] as List? ?? []).whereType<Map>())
            (row: row, deferred: true, date: '${row['decided_at']}'),
        ]..sort((a, b) {
          final first =
              DateTime.tryParse(a.date)?.toUtc().toIso8601String() ?? '';
          final second =
              DateTime.tryParse(b.date)?.toUtc().toIso8601String() ?? '';
          return second.compareTo(first);
        });
    final visibleEntries = entries.where(
      (entry) => _matchesComparison(entry.row),
    );
    return Material(
      type: MaterialType.transparency,
      child: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(24),
          children: [
            Text(
              'JOURNAL / 판단을 기록하다',
              style: Theme.of(context).textTheme.labelSmall,
            ),
            const SizedBox(height: 8),
            Text('거래를 돌아보다', style: Theme.of(context).textTheme.headlineMedium),
            if (widget.repository != null) ...[
              const SizedBox(height: 12),
              _periodPicker(),
            ],
            if (_loading) const LinearProgressIndicator(),
            if (_error != null) ...[
              Text(_error!),
              TextButton(onPressed: _load, child: const Text('다시 불러오기')),
            ],
            const SizedBox(height: 20),
            if (summary != null) ...[
              Text('매매 습관', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 6),
              Text(
                '계획 준수 ${summary['plan_adherent']} / '
                "${summary['plan_evaluated']}건 · "
                "계획 미등록 ${summary['plan_unregistered']}건",
              ),
              for (final feedback
                  in (_data?['feedback'] as List? ?? []).whereType<String>())
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text(feedback),
                ),
              const SizedBox(height: 16),
            ],
            if (stats != null) ...[
              const Divider(height: 18),
              Text(
                'AI 조언과 내 매매',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              Text(
                compared == 0
                    ? '아직 비교할 기록이 없어요. 주문 전에 AI 조언을 받은 뒤 체결하거나 보류하면 여기에 표시됩니다.'
                    : '주문 전 AI 조언과 비교한 체결·보류 $compared건 중 $matched건 일치 '
                          '(${(matched * 100 / compared).toStringAsFixed(1)}%)'
                          ' · 비교 제외 ${count('excluded')}건',
              ),
              if (compared > 0) const Text('일치 여부는 거래의 성과와 별개입니다.'),
            ] else if (summary != null && samples.isNotEmpty)
              Text(
                'AI 조언과 내 매매',
                style: Theme.of(context).textTheme.titleMedium,
              ),
            if (stats != null || (summary != null && samples.isNotEmpty))
              Wrap(
                spacing: 8,
                children: [
                  for (final filter in filters.entries)
                    ChoiceChip(
                      label: Text(filter.value),
                      selected: _comparisonFilter == filter.key,
                      onSelected: (_) =>
                          setState(() => _comparisonFilter = filter.key),
                    ),
                ],
              ),
            if (stats != null) const Divider(height: 36),
            const Text(
              '최근 매매',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 8),
            if (entries.isEmpty &&
                (widget.repository != null || widget.localOrders.isEmpty) &&
                !_loading &&
                _error == null)
              const Text('아직 주문 내역이 없습니다.'),
            if (entries.isNotEmpty && visibleEntries.isEmpty)
              Text(
                _data?['next_offset'] != null
                    ? '현재 불러온 기록에 해당 내역이 없습니다. 이전 기록을 더 불러올 수 있어요.'
                    : '이 기간에 해당하는 기록이 없어요.',
              ),
            for (final entry in visibleEntries) ...[
              _entry(entry.row, deferred: entry.deferred),
              const Divider(height: 1),
            ],
            if (widget.repository == null)
              for (final order in widget.localOrders)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(widget.stockNames[order.symbol] ?? order.symbol),
                  subtitle: Text('주문 ${order.id}'),
                  trailing: Text(orderStatus(order.status)),
                ),
            if (_data?['next_offset'] != null)
              TextButton(
                onPressed: _loading ? null : () => _load(more: true),
                child: const Text('이전 기록 더 보기'),
              ),
          ],
        ),
      ),
    );
  }
}
