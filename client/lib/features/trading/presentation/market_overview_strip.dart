import 'package:flutter/material.dart';

import '../../../core/design/design_document.dart';

class MarketOverviewStrip extends StatelessWidget {
  const MarketOverviewStrip({
    super.key,
    required this.design,
    required this.items,
    required this.connected,
    required this.loading,
  });

  final DesignDocument design;
  final Map<String, Map<String, dynamic>> items;
  final bool connected;
  final bool loading;

  static const _labels = {
    'kospi': '코스피',
    'nasdaq': '나스닥 종합',
    'kosdaq': '코스닥',
    'sp500': 'S&P 500',
    'bok_rate': '한국 기준금리',
    'treasury': '미국 10년 국채 금리',
    'oil': 'WTI 원유 선물',
    'usdkrw': '달러/원',
    'vix': 'VIX',
  };

  String _status(Map<String, dynamic> item) {
    final asOf = DateTime.tryParse('${item['as_of']}');
    if (asOf == null) return '기준 시각 미확인';
    if (item['kind'] == 'policy') return '${item['as_of']} 시행';
    final kst = asOf.toUtc().add(const Duration(hours: 9)).toIso8601String();
    final timestamp = '${kst.substring(5, 10)} ${kst.substring(11, 16)}';
    final delay = item['delay_minutes'];
    final age = DateTime.now().toUtc().difference(asOf);
    final status = age > const Duration(minutes: 45)
        ? '최근 시세'
        : delay == 0
        ? '장중'
        : delay is num && delay > 0
        ? '${delay.toInt()}분 지연'
        : '조회 시세';
    return '$status · $timestamp';
  }

  String _value(Map<String, dynamic>? item) {
    final value = item?['value'];
    if (value is! num) return '—';
    final parts = value
        .toStringAsFixed(item?['id'] == 'treasury' ? 3 : 2)
        .split('.');
    final integer = parts.first.replaceAllMapped(
      RegExp(r'(\d)(?=(\d{3})+(?!\d))'),
      (match) => '${match[1]},',
    );
    final formatted = '$integer.${parts.last}';
    return switch (item?['unit']) {
      '%' => '$formatted%',
      'USD' => '\$$formatted',
      'KRW' => '$formatted원',
      _ => formatted,
    };
  }

  String get _overviewStatus {
    final timestamps =
        items.values
            .where((item) => item['kind'] != 'policy')
            .map((item) => DateTime.tryParse('${item['as_of']}'))
            .nonNulls
            .toList()
          ..sort();
    if (timestamps.isEmpty) {
      if (!connected) return '서버 연결 필요';
      return loading ? '조회 중' : '시세 조회 불가';
    }
    final kst = timestamps.last.toUtc().add(const Duration(hours: 9));
    final stamp = kst.toIso8601String();
    return '최근 ${stamp.substring(5, 10)} ${stamp.substring(11, 16)}';
  }

  Widget _quote(MapEntry<String, String> entry, TextStyle typography) {
    final item = items[entry.key];
    final change = item?['change'] as num?;
    final muted = design.color('muted');
    return Tooltip(
      message: item == null
          ? _overviewStatus
          : '${item['source']} · ${_status(item)} (한국 시간)',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            entry.value,
            style: typography.copyWith(fontSize: 11, color: muted),
          ),
          const SizedBox(height: 3),
          Text(
            _value(item),
            style: typography.copyWith(
              fontSize: 20,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 3),
          Text(
            change == null
                ? '—'
                : '${change > 0 ? '+' : ''}${change.toStringAsFixed(2)}${item?['change_unit'] ?? ''}',
            style: typography.copyWith(
              fontSize: 11,
              color: change != null && change > 0
                  ? const Color(0xFFF07878)
                  : change != null && change < 0
                  ? const Color(0xFF7EA9FF)
                  : muted,
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final typography = TextStyle(
      fontFamily: designFont,
      fontFamilyFallback: const ['Noto Sans KR'],
      color: design.color('fg'),
      height: 1.18,
    );
    final entries = _labels.entries.toList();
    final muted = typography.copyWith(
      fontSize: 11,
      color: design.color('muted'),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SizedBox(
          height: 40,
          child: Row(
            children: [
              Text('시장 지수', style: muted),
              const Spacer(),
              Text(_overviewStatus, style: muted),
              TextButton(
                style: TextButton.styleFrom(
                  padding: const EdgeInsets.only(left: 12),
                  minimumSize: const Size(0, 40),
                  textStyle: muted,
                ),
                onPressed: () => showModalBottomSheet<void>(
                  context: context,
                  showDragHandle: true,
                  isScrollControlled: true,
                  builder: (context) => SafeArea(
                    child: FractionallySizedBox(
                      heightFactor: .72,
                      child: ListView.separated(
                        padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
                        itemCount: entries.length + 1,
                        separatorBuilder: (_, _) => const SizedBox(height: 16),
                        itemBuilder: (context, index) => index == 0
                            ? Text(
                                '전체 시장 지수',
                                style: Theme.of(context).textTheme.titleLarge,
                              )
                            : _quote(entries[index - 1], typography),
                      ),
                    ),
                  ),
                ),
                child: const Text('전체 지수 ›'),
              ),
            ],
          ),
        ),
        for (var row = 0; row < 2; row++) ...[
          if (row > 0) const SizedBox(height: 10),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: _quote(entries[row * 2], typography)),
              const SizedBox(width: 12),
              Expanded(child: _quote(entries[row * 2 + 1], typography)),
            ],
          ),
        ],
      ],
    );
  }
}
