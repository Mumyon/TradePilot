import 'package:flutter/material.dart';
import '../domain/workspace_repository.dart';
import 'trading_controller.dart';
import 'chatgpt_analysis_panel.dart';
import 'market_quote_status.dart';
import 'trading_layout_bindings.dart';

class OrderConfirmationPanel extends StatefulWidget {
  const OrderConfirmationPanel({
    super.key,
    required this.controller,
    required this.repository,
    required this.onSubmit,
    required this.onRecheck,
    required this.onBack,
    this.onDefer,
  });
  final TradingController controller;
  final WorkspaceRepository repository;
  final VoidCallback onSubmit, onRecheck, onBack;
  final VoidCallback? onDefer;
  @override
  State<OrderConfirmationPanel> createState() => _OrderConfirmationPanelState();
}

class _OrderConfirmationPanelState extends State<OrderConfirmationPanel> {
  String _aiStatus = 'pending';
  @override
  Widget build(BuildContext context) {
    final c = widget.controller;
    final check = c.check!;
    final draft = c.draft!;
    final expired = !DateTime.now().toUtc().isBefore(check.expiresAt);
    final showAi = c.pilotEnabled || draft.testMode;
    final ready =
        check.allowed &&
        !expired &&
        c.orderQuoteAvailable &&
        (!showAi || draft.testMode || _aiStatus == 'available');
    final issues = (check.analysis['validation_reasons'] as List? ?? []);
    final quote = c.chartDisplayQuote;
    final session = c.accountData?['market_session'] as Map?;
    final quoteLabel = marketQuoteLabel(
      available: quote != null,
      fresh: c.chartQuoteLive || c.quoteFresh,
      session: session,
    );
    final quoteTime = koreanMarketTime(quote?.asOf, seconds: true);
    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 24),
      children: [
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: widget.onBack,
            icon: const Icon(Icons.arrow_back),
            label: const Text('뒤로'),
          ),
        ),
        const Text(
          '주문을 확인해 주세요',
          style: TextStyle(fontSize: 25, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 18),
        Text(c.selectedName, style: const TextStyle(fontSize: 21)),
        Text(
          draft.side.name == 'buy' ? '모의 매수' : '모의 매도',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 12),
        _orderDetail('주문 유형', '지정가'),
        _orderDetail('주문 가격', '${won(draft.limitPriceWon)}원'),
        _orderDetail('주문 수량', '${draft.quantity}주'),
        const Divider(height: 16),
        _orderDetail(
          '주문 금액',
          '${won(draft.quantity * draft.limitPriceWon)}원',
          total: true,
        ),
        const SizedBox(height: 8),
        Text(
          '현재 표시가 · ${quote == null ? '—' : '${won(quote.priceWon)}원'}'
          ' · $quoteLabel${quoteTime == null ? '' : ' ($quoteTime KST)'}',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 16),
        if (!check.allowed) ...[
          const Text(
            '현재 주문을 접수할 수 없습니다.',
            style: TextStyle(color: Color(0xFFE85B5B)),
          ),
          for (final issue in issues) Text('$issue'),
        ],
        if (showAi)
          ChatGPTAnalysisPanel.pretrade(
            key: ValueKey(check.id),
            repository: widget.repository,
            checkId: check.id,
            autoGenerate: !expired,
            currentPrice: quote?.priceWon,
            onStatusChanged: (s) {
              if (mounted) setState(() => _aiStatus = s);
            },
          ),
        if (expired) const Text('주문 점검이 만료됐습니다. 다시 점검해 주세요.'),
        if (draft.testMode && check.allowed)
          for (final message in check.messages)
            if (message.startsWith('테스트 모드:')) Text(message),
        if (!draft.testMode && !c.quoteFresh) ...[
          Text(
            session?['state'] == 'closed' || session?['state'] == 'unavailable'
                ? '${session?['message'] ?? '거래 시간을 확인해 주세요.'}'
                : '주문에 필요한 최신 시세를 기다리는 중입니다.',
          ),
          TextButton(
            onPressed: c.loadSelectedQuote,
            child: const Text('시세 다시 확인'),
          ),
        ],
        const SizedBox(height: 12),
        FilledButton(
          onPressed: ready ? widget.onSubmit : null,
          child: Text('모의 ${draft.side.name == 'buy' ? '매수' : '매도'} 접수하기'),
        ),
        Wrap(
          alignment: WrapAlignment.center,
          children: [
            TextButton(
              onPressed: widget.onRecheck,
              child: const Text('주문 다시 점검'),
            ),
            if (widget.onDefer != null && !expired)
              TextButton(onPressed: widget.onDefer, child: const Text('주문 보류')),
          ],
        ),
      ],
    );
  }

  Widget _orderDetail(String label, String value, {bool total = false}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Expanded(
            child: Text(label, style: Theme.of(context).textTheme.bodySmall),
          ),
          Text(
            value,
            style: total
                ? const TextStyle(fontSize: 20, fontWeight: FontWeight.w600)
                : null,
          ),
        ],
      ),
    );
  }
}
