import 'package:flutter/material.dart';

import 'trading_layout_bindings.dart' show won;
import 'stock_price_chart.dart' show DiscoveryCandle;
import 'trading_controller.dart';
import 'market_quote_status.dart';

class StockDiscoveryScreen extends StatelessWidget {
  const StockDiscoveryScreen({
    super.key,
    required this.controller,
    required this.sortBy,
    required this.onSortChanged,
    required this.onSelectSymbol,
    this.invertedColors = false,
  });

  final TradingController controller;
  final String sortBy;
  final ValueChanged<String> onSortChanged;
  final ValueChanged<String> onSelectSymbol;
  final bool invertedColors;

  static const _sortLabels = {
    'turnover': '거래대금',
    'volume': '거래량',
    'up': '상승률',
    'down': '하락률',
  };

  @override
  Widget build(BuildContext context) {
    final data = controller.discoveryData;
    final items = ((data?['items'] as List?) ?? const [])
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
    final valueKey = switch (sortBy) {
      'volume' => 'volume',
      'up' || 'down' => 'change_percent',
      _ => 'turnover_won',
    };
    items.sort((a, b) {
      final left = (a[valueKey] as num?)?.toDouble() ?? 0;
      final right = (b[valueKey] as num?)?.toDouble() ?? 0;
      return sortBy == 'down' ? left.compareTo(right) : right.compareTo(left);
    });
    final colors = Theme.of(context).colorScheme;
    final now = DateTime.now().toUtc();
    final latestTrade = items
        .map((item) => DateTime.tryParse('${item['last_trade_at']}'))
        .nonNulls
        .fold<DateTime?>(
          null,
          (latest, time) =>
              latest == null || time.isAfter(latest) ? time : latest,
        );
    final age = latestTrade == null ? null : now.difference(latestTrade);
    final quoteLabel = marketQuoteLabel(
      available: items.isNotEmpty,
      fresh:
          age != null &&
          age >= Duration.zero &&
          age <= const Duration(seconds: 30),
      session: controller.accountData?['market_session'] as Map?,
      now: now,
    );
    final checkedAt = koreanMarketTime(data?['checked_at']);
    return RefreshIndicator(
      onRefresh: () => controller.loadDiscovery(force: true),
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(24, 24, 24, 24),
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '발견',
                  style: Theme.of(context).textTheme.headlineMedium,
                ),
              ),
              Flexible(
                child: Text(
                  '$quoteLabel${checkedAt == null ? '' : ' · 조회 $checkedAt'}',
                  textAlign: TextAlign.end,
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: colors.onSurfaceVariant,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Align(
            alignment: Alignment.centerLeft,
            child: PopupMenuButton<String>(
              tooltip: '종목 정렬 기준',
              position: PopupMenuPosition.under,
              initialValue: sortBy,
              onSelected: onSortChanged,
              itemBuilder: (_) => [
                for (final entry in _sortLabels.entries)
                  CheckedPopupMenuItem(
                    value: entry.key,
                    checked: sortBy == entry.key,
                    child: Text(entry.value),
                  ),
              ],
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 14),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(_sortLabels[sortBy] ?? _sortLabels['turnover']!),
                    const Icon(Icons.expand_more, size: 18),
                  ],
                ),
              ),
            ),
          ),
          const SizedBox(height: 4),
          if (controller.discoveryLoading && data == null)
            const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: CircularProgressIndicator()),
            )
          else if (controller.discoveryError != null && items.isEmpty)
            _discoveryEmpty(controller.discoveryError!)
          else if (items.isEmpty)
            _discoveryEmpty('표시할 종목이 없습니다.')
          else ...[
            for (final item in items) _buildStockRow(context, item, colors),
          ],
        ],
      ),
    );
  }

  Widget _discoveryEmpty(String message) => Container(
    padding: const EdgeInsets.symmetric(vertical: 32, horizontal: 18),
    alignment: Alignment.center,
    child: Column(
      children: [
        const Icon(Icons.query_stats_outlined, size: 34),
        const SizedBox(height: 10),
        Text(message, textAlign: TextAlign.center),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          onPressed: () => controller.loadDiscovery(force: true),
          icon: const Icon(Icons.refresh),
          label: const Text('다시 불러오기'),
        ),
      ],
    ),
  );

  Widget _buildStockRow(
    BuildContext context,
    Map<String, dynamic> item,
    ColorScheme colors,
  ) {
    final symbol = item['symbol'] as String? ?? '';
    final stockName = (item['name'] as String? ?? '').trim();
    final change = (item['change_percent'] as num?)?.toDouble() ?? 0;
    final changeColor = change > 0
        ? const Color(0xFFE85B5B)
        : change < 0
        ? const Color(0xFF5E8EFF)
        : colors.onSurfaceVariant;
    final price = (item['price_won'] as num?)?.toInt() ?? 0;
    final turnover = (item['turnover_won'] as num?)?.toInt() ?? 0;
    final text = Theme.of(context).textTheme;
    final secondary = text.bodySmall?.copyWith(color: colors.onSurfaceVariant);
    return DecoratedBox(
      decoration: BoxDecoration(
        border: Border(
          bottom: BorderSide(color: colors.onSurface.withValues(alpha: .10)),
        ),
      ),
      child: InkWell(
        onTap: symbol.isEmpty ? null : () => onSelectSymbol(symbol),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 13),
          child: Row(
            children: [
              DiscoveryCandle(
                data: item['candle'] as Map?,
                invertedColors: invertedColors,
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Text(
                  stockName.isNotEmpty ? stockName : symbol,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: text.titleMedium?.copyWith(
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      '${won(price)}원',
                      textAlign: TextAlign.end,
                      style: text.titleLarge?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text.rich(
                      TextSpan(
                        children: [
                          TextSpan(
                            text:
                                '${change > 0 ? '+' : ''}${change.toStringAsFixed(2)}%',
                            style: TextStyle(
                              color: changeColor,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                          TextSpan(text: '  거래대금 ${_compactWon(turnover)}'),
                        ],
                      ),
                      textAlign: TextAlign.end,
                      style: secondary,
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _compactWon(int value) {
    if (value >= 1000000000000) {
      return '${(value / 1000000000000).toStringAsFixed(1)}조';
    }
    if (value >= 100000000) {
      return '${(value / 100000000).toStringAsFixed(1)}억';
    }
    if (value >= 10000) return '${(value / 10000).toStringAsFixed(0)}만';
    return '${won(value)}원';
  }
}
