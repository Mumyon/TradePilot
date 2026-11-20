import 'dart:async';

import 'package:flutter/material.dart';

import '../domain/workspace_repository.dart';
import 'trading_layout_bindings.dart';

class StockBalanceScreen extends StatefulWidget {
  const StockBalanceScreen({
    super.key,
    required this.repository,
    required this.onManage,
    required this.onSelectSymbol,
  });

  final WorkspaceRepository? repository;
  final VoidCallback onManage;
  final ValueChanged<String> onSelectSymbol;

  @override
  State<StockBalanceScreen> createState() => _StockBalanceScreenState();
}

enum _BalanceTab { holdings, profit }

enum _HoldingSort {
  name,
  profit,
  returnRate,
  quantity,
  value,
  averagePrice,
  currentPrice,
}

class _StockBalanceScreenState extends State<StockBalanceScreen> {
  _BalanceTab _tab = _BalanceTab.holdings;
  _HoldingSort _holdingSort = _HoldingSort.value;
  bool _holdingSortAscending = false;
  Map<String, dynamic>? _account, _profit;
  bool _loadingAccount = false, _loadingProfit = false;
  bool _accountError = false, _profitError = false;
  bool _bySymbol = false;
  DateTimeRange? _period;
  String? _symbol;
  int _profitRequest = 0;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    if (widget.repository == null) return;
    unawaited(_loadAccount());
    _timer = Timer.periodic(const Duration(seconds: 5), (timer) {
      if (_tab == _BalanceTab.holdings) {
        unawaited(_loadAccount());
      } else if (timer.tick.isEven && !_loadingProfit) {
        unawaited(_loadProfit());
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _loadAccount() async {
    if (_loadingAccount) return;
    setState(() => _loadingAccount = true);
    try {
      final result = await widget.repository!.workspaceRequest(
        'GET',
        '/v1/account',
      );
      if (!mounted) return;
      setState(() {
        _account = result;
        _accountError = false;
      });
    } catch (_) {
      if (mounted) setState(() => _accountError = true);
    } finally {
      if (mounted) setState(() => _loadingAccount = false);
    }
  }

  Future<void> _loadProfit({bool filterChanged = false}) async {
    final request = ++_profitRequest;
    setState(() {
      _loadingProfit = true;
      _profitError = false;
      if (filterChanged) _profit = null;
    });
    final path = Uri(
      path: '/v1/account/trade-profit',
      queryParameters: {
        'group_by': _bySymbol ? 'symbol' : 'date',
        if (_period case final period?) ...{
          'start_date': _date(period.start),
          'end_date': _date(period.end),
        },
        'symbol': ?_symbol,
      },
    );
    try {
      final result = await widget.repository!.workspaceRequest('GET', '$path');
      if (!mounted || request != _profitRequest) return;
      setState(() => _profit = result);
    } catch (_) {
      if (mounted && request == _profitRequest) {
        setState(() => _profitError = true);
      }
    } finally {
      if (mounted && request == _profitRequest) {
        setState(() => _loadingProfit = false);
      }
    }
  }

  Future<void> _pickPeriod() async {
    final now = DateTime.now().toUtc().add(const Duration(hours: 9));
    final period = await showDateRangePicker(
      context: context,
      firstDate: DateTime(2000),
      lastDate: DateTime(now.year, now.month, now.day),
      initialDateRange: _period,
      helpText: '매매일자 선택',
      saveText: '적용',
    );
    if (period == null || !mounted) return;
    setState(() => _period = period);
    await _loadProfit(filterChanged: true);
  }

  static String _date(DateTime day) => day.toIso8601String().split('T').first;

  int? _integer(Object? value) => int.tryParse('$value');
  String _money(int? amount, {bool signed = false}) => amount == null
      ? '—'
      : '${signed && amount > 0 ? '+' : ''}${won(amount)}원';
  String _shares(int? amount) => amount == null ? '—' : '${won(amount)}주';
  String _return(Object? percent, int? pnl, int? cost) {
    final calculated = num.tryParse('$percent');
    if (calculated != null && calculated.isFinite) {
      return '${calculated > 0 ? '+' : ''}${calculated.toStringAsFixed(2)}%';
    }
    if (pnl == null || cost == null || cost <= 0) return '—';
    final rounded = (pnl / cost * 100).toStringAsFixed(2);
    if (num.parse(rounded) == 0) return '0.00%';
    return '${pnl > 0 ? '+' : ''}$rounded%';
  }

  Color? _pnlColor(int? value) => switch (value ?? 0) {
    > 0 => const Color(0xFFF07878),
    < 0 => const Color(0xFF7EA9FF),
    _ => null,
  };

  Color get _controlFill => Theme.of(context).colorScheme.surface;
  Color get _controlBorder =>
      Theme.of(context).colorScheme.onSurface.withValues(alpha: .16);

  Widget _segmentedPicker<T>({
    required Map<T, String> labels,
    required T selected,
    required ValueChanged<T> onSelected,
  }) {
    final theme = Theme.of(context);
    final foreground = theme.colorScheme.onSurface;
    return Align(
      alignment: Alignment.centerLeft,
      child: Wrap(
        spacing: 18,
        children: [
          for (final entry in labels.entries)
            Semantics(
              selected: selected == entry.key,
              child: DecoratedBox(
                decoration: BoxDecoration(
                  border: Border(
                    bottom: BorderSide(
                      width: 2,
                      color: selected == entry.key
                          ? foreground
                          : Colors.transparent,
                    ),
                  ),
                ),
                child: TextButton(
                  onPressed: () => onSelected(entry.key),
                  style: TextButton.styleFrom(
                    minimumSize: const Size(0, 44),
                    foregroundColor: selected == entry.key
                        ? foreground
                        : theme.colorScheme.onSurfaceVariant,
                    padding: const EdgeInsets.symmetric(horizontal: 3),
                    shape: const RoundedRectangleBorder(),
                  ),
                  child: Text(entry.value),
                ),
              ),
            ),
        ],
      ),
    );
  }

  ButtonStyle get _toolbarButtonStyle => OutlinedButton.styleFrom(
    backgroundColor: _controlFill,
    foregroundColor: Theme.of(context).colorScheme.onSurface,
    side: BorderSide(color: _controlBorder),
    shape: RoundedRectangleBorder(),
    minimumSize: const Size(36, 36),
    padding: const EdgeInsets.symmetric(horizontal: 10),
    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
  );

  Widget _toolbarIcon(String label, IconData icon, VoidCallback? onPressed) =>
      IconButton(
        tooltip: label,
        icon: Icon(icon, size: 18),
        onPressed: onPressed,
      );

  Widget _metric(String label, String value, {int? pnl}) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: theme.textTheme.labelSmall?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          value,
          style: theme.textTheme.titleSmall?.copyWith(
            color: _pnlColor(pnl),
            fontWeight: FontWeight.w700,
          ),
        ),
      ],
    );
  }

  Widget _summary(List<Widget> metrics) => Column(
    children: [
      for (var index = 0; index < metrics.length; index += 2) ...[
        if (index > 0) const SizedBox(height: 14),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: metrics[index]),
            const SizedBox(width: 12),
            Expanded(
              child: index + 1 < metrics.length
                  ? metrics[index + 1]
                  : const SizedBox.shrink(),
            ),
          ],
        ),
      ],
    ],
  );

  Widget _cell(String value, {String? sub, int? pnl, bool numeric = true}) {
    final text = Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: numeric
          ? CrossAxisAlignment.end
          : CrossAxisAlignment.start,
      children: [
        Text(
          value,
          style: TextStyle(fontWeight: FontWeight.w600, color: _pnlColor(pnl)),
        ),
        if (sub != null)
          Text(
            sub,
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: _pnlColor(pnl)),
          ),
      ],
    );
    return Align(
      alignment: numeric ? Alignment.centerRight : Alignment.centerLeft,
      child: text,
    );
  }

  Widget _table(List<String> headers, List<DataRow> rows) => LayoutBuilder(
    builder: (context, constraints) => SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: ConstrainedBox(
        constraints: BoxConstraints(minWidth: constraints.maxWidth),
        child: DataTable(
          horizontalMargin: 8,
          columnSpacing: 14,
          headingRowHeight: 56,
          dataRowMinHeight: 56,
          dataRowMaxHeight: 76,
          headingTextStyle: Theme.of(context).textTheme.labelSmall,
          dataTextStyle: Theme.of(context).textTheme.bodySmall,
          columns: [
            for (final (index, header) in headers.indexed)
              DataColumn(label: Text(header), numeric: index != 0),
          ],
          rows: rows,
        ),
      ),
    ),
  );

  String? _quoteNote(Map<String, dynamic> holding) {
    if (holding['price_won'] == null) return '시세 미확인';
    if (holding['stale'] != true) return null;
    final at = DateTime.tryParse('${holding['quote_as_of']}');
    if (at == null) return '최근 시세';
    final kst = at.toUtc().add(const Duration(hours: 9));
    return '최근 시세 · ${_date(kst).substring(5)} ${kst.toIso8601String().substring(11, 16)}';
  }

  int? _holdingProfit(Map<String, dynamic> holding) {
    if (holding.containsKey('valuation_pnl_won')) {
      return _integer(holding['valuation_pnl_won']);
    }
    final value = _integer(holding['valuation_won']);
    final cost = _integer(holding['cost_won']);
    return value == null || cost == null ? null : value - cost;
  }

  num? _holdingSortValue(Map<String, dynamic> holding) =>
      switch (_holdingSort) {
        _HoldingSort.name => null,
        _HoldingSort.profit => _holdingProfit(holding),
        _HoldingSort.returnRate => num.tryParse(
          _return(
            holding['valuation_return_percent'],
            _holdingProfit(holding),
            _integer(holding['cost_won']),
          ).replaceAll('%', ''),
        ),
        _HoldingSort.quantity => _integer(holding['quantity']),
        _HoldingSort.value => _integer(holding['valuation_won']),
        _HoldingSort.averagePrice => _integer(holding['average_price_won']),
        _HoldingSort.currentPrice => _integer(holding['price_won']),
      };

  int _compareHoldings(Map<String, dynamic> a, Map<String, dynamic> b) {
    final byName = '${a['name']}'.compareTo('${b['name']}');
    if (_holdingSort == _HoldingSort.name) {
      return _holdingSortAscending ? byName : -byName;
    }
    final left = _holdingSortValue(a);
    final right = _holdingSortValue(b);
    if (left == null) return right == null ? byName : 1;
    if (right == null) return -1;
    final order = left.compareTo(right);
    if (order == 0) return byName;
    return _holdingSortAscending ? order : -order;
  }

  Widget _holdingHeader(String label, [_HoldingSort? sort]) {
    final theme = Theme.of(context);
    final selected = sort != null && sort == _holdingSort;
    final content = Padding(
      padding: const EdgeInsets.symmetric(horizontal: 3, vertical: 5),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Flexible(child: Text(label, textAlign: TextAlign.center)),
          if (sort != null)
            Icon(
              selected
                  ? (_holdingSortAscending
                        ? Icons.arrow_drop_up
                        : Icons.arrow_drop_down)
                  : Icons.unfold_more,
              size: 13,
            ),
        ],
      ),
    );
    return DefaultTextStyle(
      style: theme.textTheme.labelSmall!.copyWith(
        fontWeight: FontWeight.w600,
        color: theme.colorScheme.onSurfaceVariant,
      ),
      child: sort == null
          ? content
          : Semantics(
              button: true,
              selected: selected,
              child: InkWell(
                onTap: () => setState(() {
                  _holdingSortAscending = selected
                      ? !_holdingSortAscending
                      : sort == _HoldingSort.name;
                  _holdingSort = sort;
                }),
                child: content,
              ),
            ),
    );
  }

  Widget _holdingCell(
    String top,
    String bottom, {
    bool name = false,
    int? pnl,
    String? quoteNote,
    VoidCallback? onTap,
  }) {
    final theme = Theme.of(context);
    final style = theme.textTheme.bodySmall!.copyWith(
      fontWeight: FontWeight.w600,
      color: _pnlColor(pnl),
    );
    Widget line(String value, TextStyle style) => Container(
      constraints: const BoxConstraints(minHeight: 22),
      alignment: name ? Alignment.centerLeft : Alignment.centerRight,
      child: name
          ? Text(
              value,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: style,
            )
          : FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerRight,
              child: Text(value, maxLines: 1, style: style),
            ),
    );
    final upper = line(top, style);
    final lower = line(
      bottom,
      name ? style.copyWith(color: theme.colorScheme.onSurfaceVariant) : style,
    );
    final content = Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 5),
      child: Column(
        children: [
          name ? Tooltip(message: top, child: upper) : upper,
          quoteNote == null ? lower : Tooltip(message: quoteNote, child: lower),
        ],
      ),
    );
    return onTap == null ? content : InkWell(onTap: onTap, child: content);
  }

  Widget _holdingsTable(List<Map<String, dynamic>> holdings) {
    final theme = Theme.of(context);
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: SizedBox(
          width: constraints.maxWidth < 315 ? 315 : constraints.maxWidth,
          child: Table(
            columnWidths: const {
              0: FlexColumnWidth(1.17),
              1: FlexColumnWidth(1.05),
              2: FlexColumnWidth(1.05),
              3: FlexColumnWidth(1),
            },
            border: TableBorder(
              horizontalInside: BorderSide(
                color: theme.colorScheme.onSurface.withValues(alpha: .10),
              ),
            ),
            children: [
              TableRow(
                children: [
                  Column(
                    children: [
                      _holdingHeader('종목명', _HoldingSort.name),
                      _holdingHeader('구분'),
                    ],
                  ),
                  Column(
                    children: [
                      _holdingHeader('평가손익', _HoldingSort.profit),
                      _holdingHeader('수익률', _HoldingSort.returnRate),
                    ],
                  ),
                  Column(
                    children: [
                      _holdingHeader('잔고수량', _HoldingSort.quantity),
                      _holdingHeader('평가금액', _HoldingSort.value),
                    ],
                  ),
                  Column(
                    children: [
                      _holdingHeader('매입가', _HoldingSort.averagePrice),
                      _holdingHeader('현재가', _HoldingSort.currentPrice),
                    ],
                  ),
                ],
              ),
              for (final holding in holdings) _holdingTableRow(holding),
            ],
          ),
        ),
      ),
    );
  }

  TableRow _holdingTableRow(Map<String, dynamic> holding) {
    final pnl = _holdingProfit(holding);
    final basis = _integer(holding['cost_won']);
    return TableRow(
      children: [
        _holdingCell(
          '${holding['name']}',
          '현금',
          name: true,
          onTap: () => widget.onSelectSymbol(holding['symbol'] as String),
        ),
        _holdingCell(
          _money(pnl, signed: true),
          _return(holding['valuation_return_percent'], pnl, basis),
          pnl: pnl,
        ),
        _holdingCell(
          _shares(_integer(holding['quantity'])),
          _money(_integer(holding['valuation_won'])),
        ),
        _holdingCell(
          _money(_integer(holding['average_price_won'])),
          _money(_integer(holding['price_won'])),
          quoteNote: _quoteNote(holding),
        ),
      ],
    );
  }

  Widget _holdings() {
    final account = _account;
    if (account == null) return _missing(_loadingAccount, _accountError);
    final totals = account['stock_balance'] as Map?;
    final holdings =
        (account['holdings'] as List).cast<Map<String, dynamic>>().toList()
          ..sort(_compareHoldings);
    final cost = _integer(totals?['cost_won']);
    final pnl = _integer(totals?['unrealized_pnl_won']);
    return _list('holdings', [
      if (_accountError) const Text('시세 갱신에 실패했습니다. 이전 조회 결과를 표시합니다.'),
      Text('순자산', style: Theme.of(context).textTheme.labelSmall),
      const SizedBox(height: 3),
      Text(
        _money(_integer(totals?['equity_won'])),
        style: Theme.of(
          context,
        ).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w700),
      ),
      const SizedBox(height: 16),
      _summary([
        _metric('매입금액', _money(cost)),
        _metric('평가손익', _money(pnl, signed: true), pnl: pnl),
        _metric('평가금액', _money(_integer(totals?['market_value_won']))),
        _metric('수익률', _return(totals?['return_percent'], pnl, cost), pnl: pnl),
        _metric('예수금', _money(_integer(account['cash_won']))),
      ]),
      if (totals?['stale'] == true)
        const Padding(
          padding: EdgeInsets.only(top: 8),
          child: Text('일부 종목은 최근 수신한 시세로 평가했습니다. 시각은 한국 시간 기준입니다.'),
        ),
      const SizedBox(height: 20),
      Text(
        '보유 종목 ${holdings.length}',
        style: Theme.of(context).textTheme.titleMedium,
      ),
      const SizedBox(height: 8),
      if (holdings.isEmpty)
        const Text('보유 종목이 없습니다.')
      else
        _holdingsTable(holdings),
      const SizedBox(height: 12),
      Text(
        totals?.containsKey('return_percent') == true
            ? '매입금액에는 매수 수수료가 포함됩니다. 평가손익에는 현재가로 전량 매도할 때의 예상 모의 수수료를 반영합니다.'
            : '매입금액과 평균 매입가에는 매수 수수료가 포함됩니다.',
        style: Theme.of(context).textTheme.bodySmall,
      ),
    ]);
  }

  Widget _tradeProfit() {
    final data = _profit;
    final summary = data?['summary'] as Map?;
    final items = (data?['items'] as List? ?? []).cast<Map>();
    final symbols = (data?['symbols'] as List? ?? []).cast<Map>();
    return _list('trade-profit', [
      _segmentedPicker(
        labels: const {false: '날짜별', true: '종목별'},
        selected: _bySymbol,
        onSelected: (selected) {
          if (selected == _bySymbol) return;
          setState(() => _bySymbol = selected);
          unawaited(_loadProfit(filterChanged: true));
        },
      ),
      const SizedBox(height: 8),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          OutlinedButton.icon(
            style: _toolbarButtonStyle,
            icon: const Icon(Icons.date_range_outlined, size: 16),
            label: Text(
              _period == null
                  ? '전체 기간'
                  : '${_date(_period!.start)} ~ ${_date(_period!.end)}',
            ),
            onPressed: _pickPeriod,
          ),
          if (_period != null)
            OutlinedButton(
              style: _toolbarButtonStyle,
              onPressed: () {
                setState(() => _period = null);
                unawaited(_loadProfit(filterChanged: true));
              },
              child: const Text('기간 초기화'),
            ),
          if (symbols.isNotEmpty)
            PopupMenuButton<String>(
              tooltip: '종목 선택',
              position: PopupMenuPosition.under,
              color: _controlFill,
              surfaceTintColor: Colors.transparent,
              shape: RoundedRectangleBorder(
                side: BorderSide(color: _controlBorder),
              ),
              initialValue: _symbol ?? '',
              onSelected: (value) {
                if (value == (_symbol ?? '')) return;
                setState(() => _symbol = value.isEmpty ? null : value);
                unawaited(_loadProfit(filterChanged: true));
              },
              itemBuilder: (_) => [
                const PopupMenuItem(value: '', child: Text('전체 종목')),
                for (final stock in symbols)
                  PopupMenuItem(
                    value: stock['symbol'] as String,
                    child: Text('${stock['name']}'),
                  ),
              ],
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: _controlFill,
                  border: Border.all(color: _controlBorder),
                ),
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 9,
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        '${symbols.where((stock) => stock['symbol'] == _symbol).firstOrNull?['name'] ?? '전체 종목'}',
                        style: Theme.of(context).textTheme.labelLarge,
                      ),
                      const SizedBox(width: 4),
                      const Icon(Icons.expand_more, size: 16),
                    ],
                  ),
                ),
              ),
            ),
        ],
      ),
      const SizedBox(height: 12),
      if (_profitError) const Text('매매 손익을 갱신하지 못했습니다. 새로고침해 주세요.'),
      if (summary == null && _loadingProfit)
        const Padding(
          padding: EdgeInsets.all(24),
          child: Center(child: CircularProgressIndicator()),
        ),
      if (summary != null && items.isEmpty)
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 24),
          child: Text('선택한 조건에 실현손익이 집계된 매도 내역이 없습니다.'),
        ),
      if (summary != null && items.isNotEmpty) ...[
        _summary([
          _metric(
            '실현손익',
            _money(_integer(summary['realized_pnl_won']), signed: true),
            pnl: _integer(summary['realized_pnl_won']),
          ),
          _metric(
            '실현손익률',
            _return(
              summary['realized_return_percent'],
              _integer(summary['realized_pnl_won']),
              _integer(summary['sell_cost_won']),
            ),
            pnl: _integer(summary['realized_pnl_won']),
          ),
          _metric('매도금액', _money(_integer(summary['sell_amount_won']))),
          _metric('매도 수수료', _money(_integer(summary['fees_won']))),
        ]),
        const SizedBox(height: 16),
        _table(
          [
            _bySymbol ? '종목명\n매매일자' : '매매일자',
            '실현손익\n실현손익률',
            '매도금액\n매입원가',
            '매도수량',
          ],
          items.map((row) {
            final pnl = _integer(row['realized_pnl_won']);
            final date = row['start_date'] == row['end_date']
                ? '${row['start_date']}'
                : '${row['start_date']}\n~ ${row['end_date']}';
            return DataRow(
              cells: [
                DataCell(
                  _cell(
                    _bySymbol ? '${row['name']}' : date,
                    sub: _bySymbol ? date : null,
                    numeric: false,
                  ),
                ),
                DataCell(
                  _cell(
                    _money(pnl, signed: true),
                    sub: _return(
                      row['realized_return_percent'],
                      pnl,
                      _integer(row['sell_cost_won']),
                    ),
                    pnl: pnl,
                  ),
                ),
                DataCell(
                  _cell(
                    _money(_integer(row['sell_amount_won'])),
                    sub: _money(_integer(row['sell_cost_won'])),
                  ),
                ),
                DataCell(_cell(_shares(_integer(row['sell_quantity'])))),
              ],
            );
          }).toList(),
        ),
        const SizedBox(height: 12),
        Text(
          '매도일은 한국 시간 기준입니다. 실현손익률은 실현손익을 매도 수량에 배분된 매입원가로 나눕니다.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ],
    ]);
  }

  Widget _missing(bool loading, bool error) => Center(
    child: loading
        ? const CircularProgressIndicator()
        : Text(error ? '잔고를 불러오지 못했습니다. 새로고침해 주세요.' : '계좌 데이터가 없습니다.'),
  );

  Widget _list(String key, List<Widget> children) => ListView(
    key: PageStorageKey(key),
    padding: const EdgeInsets.fromLTRB(24, 16, 24, 24),
    children: children,
  );

  @override
  Widget build(BuildContext context) {
    final connected = widget.repository != null;
    final holdings = _tab == _BalanceTab.holdings;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(24, 24, 16, 4),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '주식 잔고',
                      style: Theme.of(context).textTheme.headlineMedium,
                    ),
                    Text('모의계좌', style: Theme.of(context).textTheme.bodySmall),
                  ],
                ),
              ),
              if (connected)
                _toolbarIcon(
                  '새로고침',
                  Icons.refresh,
                  (holdings ? _loadingAccount : _loadingProfit)
                      ? null
                      : () => holdings ? _loadAccount() : _loadProfit(),
                ),
              if (connected) const SizedBox(width: 6),
              _toolbarIcon('계좌 관리', Icons.more_horiz, widget.onManage),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: _segmentedPicker(
            labels: const {
              _BalanceTab.holdings: '주식 잔고',
              _BalanceTab.profit: '매매 손익',
            },
            selected: _tab,
            onSelected: (selected) {
              if (selected == _tab) return;
              setState(() => _tab = selected);
              if (!connected) return;
              if (_tab == _BalanceTab.profit) {
                if (!_loadingProfit) unawaited(_loadProfit());
              } else {
                unawaited(_loadAccount());
              }
            },
          ),
        ),
        Expanded(
          child: !connected
              ? const Center(child: Text('서버에 연결하면 모의계좌 잔고와 매매 손익을 볼 수 있습니다.'))
              : holdings
              ? _holdings()
              : _tradeProfit(),
        ),
      ],
    );
  }
}
