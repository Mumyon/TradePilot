import 'dart:async';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../domain/workspace_repository.dart';
import 'market_quote_status.dart';
import 'trading_layout_bindings.dart';

enum ChartDetail {
  chart('차트', false),
  orderbook('호가', true),
  trades('체결', true),
  news('뉴스', false),
  company('기업정보', false),
  financials('재무제표', false);

  const ChartDetail(this.label, this.refreshes);
  final String label;
  final bool refreshes;
}

class ChartStockDetails extends StatefulWidget {
  const ChartStockDetails({
    super.key,
    required this.repository,
    required this.symbol,
    required this.initial,
  });

  final WorkspaceRepository repository;
  final String symbol;
  final ChartDetail initial;

  @override
  State<ChartStockDetails> createState() => _ChartStockDetailsState();
}

class _ChartStockDetailsState extends State<ChartStockDetails> {
  late ChartDetail _section;
  Map<String, dynamic>? _data;
  Timer? _timer;
  int _request = 0;
  bool _loading = false, _failed = false;

  @override
  void initState() {
    super.initState();
    _select(widget.initial);
  }

  int get _refreshSeconds => _section == ChartDetail.orderbook ? 1 : 5;

  void _select(ChartDetail section) {
    _timer?.cancel();
    _request++;
    setState(() {
      _section = section;
      _data = null;
      _loading = false;
      _failed = false;
    });
    unawaited(_load());
    if (section.refreshes) {
      _timer = Timer.periodic(
        Duration(seconds: _refreshSeconds),
        (_) => _load(),
      );
    }
  }

  Future<void> _load() async {
    if (_loading) return;
    final request = ++_request;
    setState(() => _loading = true);
    try {
      final data = await widget.repository.workspaceRequest(
        'GET',
        '/v1/market/${Uri.encodeComponent(widget.symbol)}/details/${_section.name}',
      );
      if (!mounted || request != _request) return;
      setState(() {
        _data = data;
        _failed = false;
        _loading = false;
      });
    } catch (_) {
      if (!mounted || request != _request) return;
      setState(() {
        _failed = true;
        _loading = false;
      });
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  List<Map> _rows(String key) =>
      (_data?[key] as List? ?? []).whereType<Map>().toList();

  String _number(Object? value) {
    final raw = '${value ?? ''}';
    if (raw.isEmpty) return '—';
    final integer = int.tryParse(raw.replaceAll(',', ''));
    return integer == null ? raw : won(integer);
  }

  Widget _link(String label, Object? target) {
    final url = Uri.tryParse('${target ?? ''}');
    if (url == null ||
        !const {'http', 'https'}.contains(url.scheme) ||
        !url.hasAuthority ||
        url.userInfo.isNotEmpty) {
      return const SizedBox.shrink();
    }
    return TextButton(
      onPressed: () => launchUrl(url, mode: LaunchMode.externalApplication),
      child: Text(label),
    );
  }

  Widget _row(List<String> values, {Color? color}) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 9),
    child: Row(
      children: [
        for (final (index, value) in values.indexed)
          Expanded(
            child: Text(
              value,
              textAlign: index == 0 ? TextAlign.start : TextAlign.end,
              style: TextStyle(color: color, fontSize: 13),
            ),
          ),
      ],
    ),
  );

  Widget _book() {
    final asks = _rows('asks');
    final bids = _rows('bids');
    if (asks.isEmpty && bids.isEmpty) return const Text('표시할 호가가 없습니다.');
    int volume(Map row) =>
        int.tryParse('${row['volume']}'.replaceAll(',', '')) ?? 0;
    final maxVolume = [
      ...asks,
      ...bids,
    ].map(volume).fold(1, (a, b) => a > b ? a : b);
    Widget depthRow(Map row, {required bool ask}) {
      final color = ask ? const Color(0xFF7195F5) : const Color(0xFFF17979);
      final quantity = volume(row);
      final bar = LayoutBuilder(
        builder: (context, constraints) => Stack(
          alignment: ask ? Alignment.centerRight : Alignment.centerLeft,
          children: [
            SizedBox(width: constraints.maxWidth, height: 28),
            AnimatedContainer(
              duration: MediaQuery.disableAnimationsOf(context)
                  ? Duration.zero
                  : const Duration(milliseconds: 220),
              curve: Curves.easeOut,
              width: constraints.maxWidth * (quantity / maxVolume).clamp(0, 1),
              height: 28,
              color: color.withValues(alpha: .24),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 6),
              child: Text(
                _number(row['volume']),
                style: TextStyle(color: color, fontSize: 12),
              ),
            ),
          ],
        ),
      );
      return Row(
        key: ValueKey((ask, row['price'])),
        children: [
          Expanded(child: ask ? bar : const SizedBox.shrink()),
          Expanded(
            child: Text(
              _number(row['price']),
              textAlign: TextAlign.center,
              style: TextStyle(color: color, fontWeight: FontWeight.w600),
            ),
          ),
          Expanded(child: ask ? const SizedBox.shrink() : bar),
        ],
      );
    }

    return Column(
      children: [
        _row(['매도 잔량', '호가 (원)', '매수 잔량']),
        for (final row in asks.reversed) depthRow(row, ask: true),
        const Divider(height: 9),
        for (final row in bids) depthRow(row, ask: false),
        const SizedBox(height: 8),
        if (koreanMarketTime(_data?['as_of'], seconds: true)
            case final String stamp)
          Text('토스증권 · $stamp', style: Theme.of(context).textTheme.bodySmall),
      ],
    );
  }

  Widget _trades() {
    final rows = _rows('items');
    if (rows.isEmpty) return const Text('표시할 체결 내역이 없습니다.');
    return Column(
      children: [
        _row(['체결 시각', '체결가 (원)', '수량 (주)']),
        const Divider(height: 1),
        for (final row in rows)
          _row([
            koreanMarketTime(row['timestamp'], seconds: true) ?? '—',
            _number(row['price']),
            _number(row['volume']),
          ]),
      ],
    );
  }

  Widget _news() {
    final rows = _rows('items');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (_data?['status'] == 'not_configured')
          const Text('앱 내 뉴스 목록은 네이버 뉴스 API 연결 후 표시됩니다.')
        else if (rows.isEmpty)
          const Text('검색된 뉴스가 없습니다.'),
        for (final row in rows) ...[
          _link('${row['title']}', row['url']),
          if (row['published_at'] case final String date)
            Text(date, style: Theme.of(context).textTheme.bodySmall),
          const Divider(height: 1),
        ],
        _link('네이버에서 종목 뉴스 보기 ↗', _data?['search_url']),
      ],
    );
  }

  Widget _company() {
    final data = _data?['company'] as Map?;
    if (data == null) return const Text('종목 정보를 찾을 수 없습니다.');
    return Column(
      children: [
        for (final entry in const {
          '종목명': 'name',
          '영문명': 'englishName',
          '거래시장': 'market',
          '상장일': 'listDate',
          '발행주식수': 'sharesOutstanding',
          '통화': 'currency',
          'ISIN': 'isinCode',
        }.entries)
          _row([
            entry.key,
            entry.value == 'sharesOutstanding'
                ? _number(data[entry.value])
                : '${data[entry.value] ?? '—'}',
          ]),
      ],
    );
  }

  String _financialAmount(Object? value, Object? currency) {
    final amount = int.tryParse('${value ?? ''}'.replaceAll(',', '').trim());
    if (amount == null) return _number(value);
    final unit = '${currency ?? ''}'.trim().toUpperCase();
    if ((unit.isNotEmpty && unit != 'KRW') || amount.abs() < 100000000) {
      return won(amount);
    }
    final hundredths = (amount.abs() + 500000) ~/ 1000000;
    final fraction = (hundredths % 100)
        .toString()
        .padLeft(2, '0')
        .replaceFirst(RegExp(r'0+$'), '');
    final decimals = fraction.isEmpty ? '' : '.$fraction';
    return '${amount < 0 ? '-' : ''}${won(hundredths ~/ 100)}$decimals억';
  }

  Widget _financialRow(
    String account,
    String current,
    String previous, {
    bool header = false,
  }) {
    final theme = Theme.of(context);
    final style = theme.textTheme.bodySmall;
    final muted = style?.copyWith(color: theme.colorScheme.onSurfaceVariant);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            flex: 4,
            child: Text(account, style: header ? muted : style),
          ),
          const SizedBox(width: 8),
          Expanded(
            flex: 3,
            child: Text(
              current,
              textAlign: TextAlign.end,
              style: header
                  ? muted
                  : style?.copyWith(fontWeight: FontWeight.w600),
            ),
          ),
          const SizedBox(width: 6),
          Expanded(
            flex: 3,
            child: Text(previous, textAlign: TextAlign.end, style: muted),
          ),
        ],
      ),
    );
  }

  Widget _financials() {
    if (_data?['status'] == 'not_configured') {
      return const Text('OpenDART 인증키를 연결하면 연간 재무제표가 표시됩니다.');
    }
    final rows = _rows('items');
    if (rows.isEmpty) return const Text('조회 가능한 연간 재무제표가 없습니다.');
    String? section;
    final widgets = <Widget>[
      Text(
        "${_data!['year']}년 · ${_data!['scope'] == 'CFS' ? '연결' : '별도'} · OpenDART",
      ),
      _link('공시 원문 보기 ↗', _data?['filing_url']),
    ];
    for (final row in rows) {
      if (section != row['section']) {
        section = row['section'] as String?;
        widgets.addAll([
          const Divider(),
          Text(
            section ?? '재무제표',
            style: Theme.of(context).textTheme.titleSmall,
          ),
          _financialRow('계정', '당기', '전기', header: true),
        ]);
      }
      final currency = row['currency'];
      final detail = row['detail'] as String?;
      widgets.add(
        _financialRow(
          "${row['account']}${detail != null && detail != '-' && detail.isNotEmpty ? '\n$detail' : ''}${currency != null ? '\n($currency)' : ''}",
          _financialAmount(row['current'], currency),
          _financialAmount(row['previous'], currency),
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: widgets,
    );
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      if (_section == ChartDetail.trades && _data != null)
        Text(
          '토스증권 · $_refreshSeconds초마다 조회',
          style: Theme.of(context).textTheme.bodySmall,
        ),
      if (_failed)
        TextButton(
          onPressed: _load,
          child: Text(_data == null ? '불러오기 실패 · 다시 시도' : '갱신 실패 · 다시 시도'),
        ),
      if (_data == null && _loading) const LinearProgressIndicator(),
      if (_data != null)
        Expanded(
          child: ListView(
            primary: false,
            padding: const EdgeInsets.only(top: 12),
            children: [
              if (_data!['status'] == 'unsupported')
                const Text('현재 시세 제공처에서 이 항목을 지원하지 않습니다.')
              else
                switch (_section) {
                  ChartDetail.chart => const SizedBox.shrink(),
                  ChartDetail.orderbook => _book(),
                  ChartDetail.trades => _trades(),
                  ChartDetail.news => _news(),
                  ChartDetail.company => _company(),
                  ChartDetail.financials => _financials(),
                },
            ],
          ),
        ),
    ],
  );
}
