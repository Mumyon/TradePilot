import 'dart:math' as math;
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart' show SemanticsProperties;

import '../domain/trading_models.dart';
import 'trading_layout_bindings.dart' show won;

Color _candleColor(num open, num close, {required bool invertedColors}) {
  if (close == open) return const Color(0xFFA1A1A6);
  final color = close > open
      ? const Color(0xFFE85B5B)
      : const Color(0xFF5E8EFF);
  // Compensate for the app-wide filter so candle colors keep their meaning.
  return invertedColors
      ? Color.from(
          alpha: 1,
          red: 1 - color.r,
          green: 1 - color.g,
          blue: 1 - color.b,
        )
      : color;
}

class DiscoveryCandle extends StatelessWidget {
  const DiscoveryCandle({
    super.key,
    required this.data,
    this.invertedColors = false,
  });

  final Map? data;
  final bool invertedColors;

  @override
  Widget build(BuildContext context) {
    final open = data?['open_won'];
    final high = data?['high_won'];
    final low = data?['low_won'];
    final close = data?['close_won'];
    final colors = Theme.of(context).colorScheme;
    if (open is! num ||
        high is! num ||
        low is! num ||
        close is! num ||
        ![
          open,
          high,
          low,
          close,
        ].every((price) => price.isFinite && price > 0) ||
        low > math.min(open, close) ||
        high < math.max(open, close)) {
      return Tooltip(
        message: '최근 일봉 데이터 없음',
        child: SizedBox(
          width: 22,
          height: 34,
          child: Icon(Icons.remove, size: 16, color: colors.onSurfaceVariant),
        ),
      );
    }
    final direction = close > open
        ? '양봉'
        : close < open
        ? '음봉'
        : '보합';
    return Tooltip(
      message: '최근 일봉 · $direction',
      child: CustomPaint(
        size: const Size(22, 34),
        painter: _DiscoveryCandlePainter(
          open,
          high,
          low,
          close,
          _candleColor(open, close, invertedColors: invertedColors),
        ),
      ),
    );
  }
}

class _DiscoveryCandlePainter extends CustomPainter {
  const _DiscoveryCandlePainter(
    this.open,
    this.high,
    this.low,
    this.close,
    this.color,
  );

  final num open, high, low, close;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    const padding = 7.0;
    final range = high - low;
    double y(num price) => range == 0
        ? size.height / 2
        : padding + (high - price) / range * (size.height - 2 * padding);
    final x = size.width / 2;
    final paint = Paint()
      ..color = color
      ..strokeWidth = 1.5;
    canvas.drawLine(Offset(x, y(high)), Offset(x, y(low)), paint);
    final bodyHeight = math.max(2.0, (y(open) - y(close)).abs());
    final bodyTop = (y(open) + y(close) - bodyHeight) / 2;
    canvas.drawRect(Rect.fromLTWH(x - 3, bodyTop, 6, bodyHeight), paint);
  }

  @override
  bool shouldRepaint(covariant _DiscoveryCandlePainter oldDelegate) =>
      oldDelegate.open != open ||
      oldDelegate.high != high ||
      oldDelegate.low != low ||
      oldDelegate.close != close ||
      oldDelegate.color != color;
}

enum ChartStyle { candle, line, area, ohlc }

enum ChartIndicator { volume, macd, rsi }

class ChartVolatilityIndex extends StatelessWidget {
  const ChartVolatilityIndex({super.key, required this.volatilityIndex});
  final Map<String, dynamic>? volatilityIndex;

  @override
  Widget build(BuildContext context) {
    final close = volatilityIndex?['close'] as num?;
    final change = volatilityIndex?['change'] as num?;
    final date = volatilityIndex?['as_of'];
    final status = volatilityIndex?['stale'] == true ? ' · 지연' : '';
    final details = change == null
        ? ''
        : '  ${change >= 0 ? '+' : ''}${change.toStringAsFixed(2)}';
    return Tooltip(
      message: 'Cboe VIX · S&P 500 옵션에 반영된 향후 30일 예상 변동성',
      child: Text(
        close == null
            ? volatilityIndex == null
                  ? 'VIX 공포지수 · 조회 중'
                  : 'VIX 공포지수 · 데이터 없음'
            : 'VIX ${close.toStringAsFixed(2)}$details · Cboe 일봉 $date$status',
        maxLines: 2,
        style: const TextStyle(fontSize: 11, color: Color(0xffa1a1a6)),
      ),
    );
  }
}

class StockPriceChart extends StatefulWidget {
  static const _intervals = {
    '1m': '1분',
    '3m': '3분',
    '5m': '5분',
    '10m': '10분',
    '15m': '15분',
    '30m': '30분',
    '1h': '1시간',
    '1d': '일봉',
    '1w': '주봉',
    '1mo': '월봉',
    '1y': '년봉',
  };
  static const _minutes = ['1m', '5m', '15m', '30m', '1h'];
  static const _periods = {'1d': '일봉', '1w': '주봉', '1y': '년봉'};

  const StockPriceChart({
    super.key,
    required this.data,
    this.interactive = false,
    this.seriesKey,
    this.interval = '15m',
    this.liveQuote,
    this.onIntervalChanged,
    this.invertedColors = false,
  });

  final Map<String, dynamic>? data;
  final bool interactive;
  final String? seriesKey;
  final String interval;
  final Quote? liveQuote;
  final ValueChanged<String>? onIntervalChanged;
  final bool invertedColors;

  @override
  State<StockPriceChart> createState() => _StockPriceChartState();
}

class _StockPriceChartState extends State<StockPriceChart> {
  static const _priceAxisWidth = 62.0;
  String _minuteInterval = '15m';
  ChartStyle _style = ChartStyle.candle;
  ChartIndicator _indicator = ChartIndicator.volume;
  bool _averages = false;
  int _window = 40;
  int _offset = 0;
  DateTime? _cursor;
  _Bar? _liveBar;
  DateTime? _lastTradeAt;
  double _drag = 0;
  int _initialWindow = 40;
  double _lastScale = 1;
  bool _pinching = false;
  bool _trackpadGesture = false;
  int _trackpadWindow = 40;
  List<_Bar> _bars = [];
  _Indicators _indicators = _Indicators([]);

  @override
  void initState() {
    super.initState();
    _updateBars();
    _applyTrade();
  }

  @override
  void didUpdateWidget(covariant StockPriceChart oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.seriesKey != widget.seriesKey ||
        oldWidget.interval != widget.interval) {
      _offset = 0;
      _cursor = null;
      _liveBar = null;
      _lastTradeAt = null;
      _window = 40;
    }
    if (oldWidget.data != widget.data) _updateBars();
    if (_liveBar != null &&
        _bars.isNotEmpty &&
        (_liveBar!.date.isBefore(_bars.last.date) ||
            (_liveBar!.date == _bars.last.date && _bars.last.complete))) {
      _liveBar = null;
    }
    _applyTrade();
  }

  void _updateBars() {
    _bars = (widget.data?['items'] as List? ?? [])
        .whereType<Map>()
        .map(_Bar.parse)
        .nonNulls
        .toList();
    _indicators = _Indicators(_bars);
    _offset = math.min(_offset, math.max(0, _bars.length - _window));
  }

  void _applyTrade() {
    final quote = widget.liveQuote;
    if (quote == null ||
        quote.priceWon <= 0 ||
        (_lastTradeAt != null && quote.asOf.isBefore(_lastTradeAt!))) {
      return;
    }
    final opened = _tradeBucket(quote.asOf, widget.interval);
    final tail = _bars.lastOrNull;
    if (tail != null &&
        (opened.isBefore(tail.date) ||
            (opened == tail.date && tail.complete))) {
      return;
    }
    final price = quote.priceWon.toDouble();
    final previous = _liveBar?.date == opened ? _liveBar : null;
    final snapshot = tail?.date == opened ? tail : null;
    _liveBar = _Bar(
      opened,
      snapshot?.open ?? previous?.open ?? price,
      math.max(
        math.max(previous?.high ?? price, snapshot?.high ?? price),
        price,
      ),
      math.min(math.min(previous?.low ?? price, snapshot?.low ?? price), price),
      price,
      snapshot?.volume ?? 0,
      complete: false,
    );
    _lastTradeAt = quote.asOf;
  }

  @override
  Widget build(BuildContext context) {
    final data = widget.data;
    final liveBar = _liveBar;
    final bars = [
      for (final bar in _bars)
        if (bar.date != liveBar?.date) bar,
      ?liveBar,
    ];
    final end = bars.length - _offset;
    final start = math.max(0, end - _window);
    final cursor = bars.indexWhere((bar) => bar.date == _cursor);
    final selected = cursor >= start && cursor < end;
    final index = selected ? cursor : end - 1;
    final bar = index < 0 ? null : bars[index];
    final isTradeBar = bar != null && identical(bar, liveBar);
    final inProgress = bar?.complete == false;
    final stamp = isTradeBar ? _lastTradeAt : bar?.date;
    final date = stamp == null ? null : _marketTime(stamp);
    final focus = isTradeBar
        ? '마지막 체결'
        : selected
        ? '선택한 봉'
        : inProgress
        ? '진행 중인 봉'
        : '마지막 봉';
    final detail = bar == null
        ? ''
        : inProgress
        ? '${won(bar.close.round())}원'
        : '${selected ? '종가 ${won(bar.close.round())}원 · ' : ''}거래량 ${bar.volume.round()}';
    final seriesStatus =
        liveBar != null && end == bars.length && widget.liveQuote != null
        ? '실시간 체결 · 진행 중인 봉'
        : '${data?['source'] == 'demo' ? '테스트 생성 데이터' : '수신 데이터'} · ${data?['stale'] == true || (liveBar != null && widget.liveQuote == null) ? '지연' : '갱신됨'}';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (widget.interactive) _controls(),
        if (bars.isEmpty)
          Expanded(
            child: Center(
              child: Text(data == null ? '차트 불러오는 중…' : '캔들 데이터가 없습니다.'),
            ),
          )
        else ...[
          Text(
            widget.interactive
                ? '${StockPriceChart._intervals[widget.interval] ?? widget.interval} · $seriesStatus'
                : seriesStatus,
            style: const TextStyle(fontSize: 11),
          ),
          if (widget.interactive && _bars.isNotEmpty)
            Text(
              _indicators.caption(
                _indicator,
                math.min(index, _bars.length - 1),
              ),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 10, color: Color(0xffa1a1a6)),
            ),
          const SizedBox(height: 4),
          Expanded(
            child: _plot(
              bars,
              start,
              end,
              selected ? cursor : null,
              liveBar != null,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            '$focus ${_chartDate(date!, showYear: true)}${inProgress || _isIntraday(widget.interval) ? ' ${_chartTime(date)}' : ''}'
            ' · $detail',
            style: const TextStyle(fontSize: 10),
          ),
        ],
      ],
    );
  }

  Widget _controls() => SizedBox(
    height: 43,
    child: ListView(
      scrollDirection: Axis.horizontal,
      children: [
        PopupMenuButton<ChartStyle>(
          tooltip: '그래프 종류',
          position: PopupMenuPosition.under,
          initialValue: _style,
          onSelected: (value) => setState(() => _style = value),
          itemBuilder: (_) => [
            for (final value in ChartStyle.values)
              PopupMenuItem(value: value, child: Text(_styleName(value))),
          ],
          child: _menuLabel(_styleName(_style)),
        ),
        PopupMenuButton<ChartIndicator>(
          tooltip: '보조지표',
          position: PopupMenuPosition.under,
          initialValue: _indicator,
          onSelected: (value) => setState(() => _indicator = value),
          itemBuilder: (_) => [
            for (final value in ChartIndicator.values)
              PopupMenuItem(value: value, child: Text(_indicatorName(value))),
          ],
          child: _menuLabel(_indicatorName(_indicator)),
        ),
        if (widget.onIntervalChanged != null)
          PopupMenuButton<String>(
            tooltip: '봉 종류',
            position: PopupMenuPosition.under,
            initialValue: _isIntraday(widget.interval)
                ? 'intraday'
                : widget.interval,
            onSelected: (period) {
              if (_isIntraday(widget.interval)) {
                _minuteInterval = widget.interval;
              }
              final interval = period == 'intraday' ? _minuteInterval : period;
              if (interval != widget.interval) {
                widget.onIntervalChanged!(interval);
              }
            },
            itemBuilder: (_) => [
              const PopupMenuItem(value: 'intraday', child: Text('분봉')),
              for (final entry in StockPriceChart._periods.entries)
                PopupMenuItem(value: entry.key, child: Text(entry.value)),
            ],
            child: _menuLabel(
              _isIntraday(widget.interval)
                  ? '분봉'
                  : StockPriceChart._intervals[widget.interval] ??
                        widget.interval,
            ),
          ),
        if (widget.onIntervalChanged != null && _isIntraday(widget.interval))
          PopupMenuButton<String>(
            tooltip: '시간 단위',
            position: PopupMenuPosition.under,
            initialValue: widget.interval,
            onSelected: (interval) {
              if (interval != widget.interval) {
                widget.onIntervalChanged!(interval);
              }
            },
            itemBuilder: (_) => [
              for (final interval in StockPriceChart._minutes)
                PopupMenuItem(
                  value: interval,
                  child: Text(StockPriceChart._intervals[interval]!),
                ),
            ],
            child: _menuLabel(
              StockPriceChart._intervals[widget.interval] ?? widget.interval,
            ),
          ),
        Semantics(
          selected: _averages,
          child: TextButton(
            style: TextButton.styleFrom(
              padding: const EdgeInsets.symmetric(horizontal: 9),
              foregroundColor: _averages
                  ? Theme.of(context).colorScheme.onSurface
                  : Theme.of(context).colorScheme.onSurfaceVariant,
            ),
            onPressed: () => setState(() => _averages = !_averages),
            child: Text(
              '이평선',
              style: TextStyle(
                decoration: _averages ? TextDecoration.underline : null,
              ),
            ),
          ),
        ),
        if (_offset > 0)
          IconButton(
            tooltip: '현재가로 이동',
            onPressed: () => setState(() {
              _offset = 0;
              _cursor = null;
            }),
            icon: const Icon(Icons.last_page),
          ),
      ],
    ),
  );

  Widget _menuLabel(String title) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: 7),
    child: Row(
      children: [Text(title), const Icon(Icons.expand_more, size: 16)],
    ),
  );

  void _zoomTo(int window, int barCount, {double? anchor}) {
    if (barCount < 2) return;
    final minimum = math.min(12, math.max(2, barCount ~/ 3));
    final nextWindow = math.max(minimum, math.min(window, barCount));
    final visible = math.min(_window, barCount - _offset);
    if (nextWindow == visible) return;
    // When following live data, keep the latest candle at the right edge.
    final nextOffset = _offset == 0 || anchor == null
        ? _offset
        : _offset + ((visible - nextWindow) * (1 - anchor)).round();
    setState(() {
      _window = nextWindow;
      _offset = nextOffset.clamp(0, barCount - nextWindow);
      _cursor = null;
    });
  }

  Widget _plot(
    List<_Bar> bars,
    int start,
    int end,
    int? cursor,
    bool hasLiveBar,
  ) => LayoutBuilder(
    builder: (context, box) {
      final plot = CustomPaint(
        painter: _ChartPainter(
          bars: bars,
          start: start,
          end: end,
          style: _style,
          indicator: widget.interactive ? _indicator : null,
          indicators: _indicators,
          averages: _averages,
          cursor: cursor,
          liveIndex: hasLiveBar && end == bars.length ? end - 1 : null,
          fresh: widget.liveQuote != null,
          interval: widget.interval,
          invertedColors: widget.invertedColors,
        ),
        child: const SizedBox.expand(),
      );
      if (!widget.interactive) return plot;
      final width = math.max(1.0, box.maxWidth - _priceAxisWidth);
      DateTime selectedAt(double x) =>
          bars[start +
                  (x / width * (end - start)).floor().clamp(0, end - start - 1)]
              .date;
      return Listener(
        behavior: HitTestBehavior.opaque,
        onPointerDown: (_) => _trackpadGesture = false,
        onPointerPanZoomStart: (_) {
          _trackpadGesture = true;
          _trackpadWindow = end - start;
        },
        onPointerPanZoomUpdate: (event) {
          if (!event.scale.isFinite || event.scale <= 0) return;
          _zoomTo(
            (_trackpadWindow / event.scale).round(),
            bars.length,
            anchor: (event.localPosition.dx / width).clamp(0.0, 1.0),
          );
        },
        onPointerSignal: (event) {
          if (bars.length < 2) return;
          final factor = switch (event) {
            PointerScaleEvent(:final scale) when scale.isFinite && scale > 0 =>
              1 / scale,
            PointerScrollEvent(:final scrollDelta)
                when scrollDelta.dy != 0 &&
                    scrollDelta.dy.abs() >= scrollDelta.dx.abs() =>
              math.exp(scrollDelta.dy.clamp(-180.0, 180.0) / 480),
            _ => 1.0,
          };
          if (factor == 1) return;
          GestureBinding.instance.pointerSignalResolver.register(event, (_) {
            final visible = math.min(_window, bars.length - _offset);
            final scaled = (visible * factor).round();
            final next = scaled == visible
                ? visible + (factor > 1 ? 1 : -1)
                : scaled;
            final anchor = (event.localPosition.dx / width).clamp(0.0, 1.0);
            _zoomTo(next, bars.length, anchor: anchor);
          });
        },
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTapUp: (details) =>
              setState(() => _cursor = selectedAt(details.localPosition.dx)),
          onLongPressStart: (details) =>
              setState(() => _cursor = selectedAt(details.localPosition.dx)),
          onLongPressMoveUpdate: (details) =>
              setState(() => _cursor = selectedAt(details.localPosition.dx)),
          onScaleStart: (_) {
            _drag = 0;
            _initialWindow = end - start;
            _lastScale = 1;
            _pinching = false;
          },
          onScaleUpdate: (details) {
            if (details.pointerCount > 1 || (details.scale - 1).abs() > .02) {
              _pinching = true;
              if (_trackpadGesture) return;
              final scale = details.scale;
              if (scale <= 0 || (scale - _lastScale).abs() < .02) return;
              _lastScale = scale;
              _zoomTo((_initialWindow / scale).round(), bars.length);
            } else if (!_pinching) {
              _drag += details.focalPointDelta.dx;
              final step = width / (end - start);
              final moved = (_drag / step).truncate();
              if (moved == 0) return;
              _drag -= moved * step;
              setState(() {
                _offset = (_offset + moved).clamp(
                  0,
                  math.max(0, bars.length - _window),
                );
                _cursor = null;
              });
            }
          },
          onScaleEnd: (_) {
            if (!_pinching || _trackpadGesture) return;
            final intervals = StockPriceChart._intervals.keys.toList();
            final index = intervals.indexOf(widget.interval);
            if (index < 0) return;
            final change = _lastScale >= 1.25
                ? -1
                : _lastScale <= .8
                ? 1
                : 0;
            final next = (index + change).clamp(0, intervals.length - 1);
            if (next != index) widget.onIntervalChanged?.call(intervals[next]);
          },
          child: plot,
        ),
      );
    },
  );
}

DateTime _marketTime(DateTime at) => at.toUtc().add(const Duration(hours: 9));

bool _isIntraday(String interval) =>
    !{'1d', '1w', '1mo', '1y'}.contains(interval);

String _chartDate(DateTime date, {bool showYear = false}) =>
    '${showYear ? '${date.year}.' : ''}${date.month.toString().padLeft(2, '0')}.'
    '${date.day.toString().padLeft(2, '0')}';

String _chartTime(DateTime date) =>
    '${date.hour.toString().padLeft(2, '0')}:${date.minute.toString().padLeft(2, '0')}';

DateTime _tradeBucket(DateTime at, String interval) {
  final local = _marketTime(at);
  final midnight = DateTime.utc(local.year, local.month, local.day);
  final days = switch (interval) {
    '1y' => DateTime.utc(local.year),
    '1mo' => DateTime.utc(local.year, local.month),
    '1w' => midnight.subtract(Duration(days: local.weekday - 1)),
    '1d' => midnight,
    _ => null,
  };
  if (days != null) return days.subtract(const Duration(hours: 9));
  final minutes = interval == '1h'
      ? 60
      : int.tryParse(interval.replaceAll('m', '')) ?? 15;
  final epoch = at.millisecondsSinceEpoch;
  final width = minutes * 60000;
  return DateTime.fromMillisecondsSinceEpoch(
    epoch - epoch % width,
    isUtc: true,
  );
}

String _styleName(ChartStyle style) => switch (style) {
  ChartStyle.candle => '캔들',
  ChartStyle.line => '라인',
  ChartStyle.area => '영역',
  ChartStyle.ohlc => 'OHLC 바',
};

String _indicatorName(ChartIndicator indicator) => switch (indicator) {
  ChartIndicator.volume => '거래량',
  ChartIndicator.macd => 'MACD',
  ChartIndicator.rsi => 'RSI',
};

class _Bar {
  const _Bar(
    this.date,
    this.open,
    this.high,
    this.low,
    this.close,
    this.volume, {
    this.complete = true,
  });
  final DateTime date;
  final double open, high, low, close, volume;
  final bool complete;

  static _Bar? parse(Map row) {
    final date = DateTime.tryParse('${row['opened_at']}');
    final values = [
      for (final field in [
        'open_won',
        'high_won',
        'low_won',
        'close_won',
        'volume',
      ])
        double.tryParse('${row[field]}'),
    ];
    if (date == null ||
        values.any((value) => value == null || !value.isFinite)) {
      return null;
    }
    final [open, high, low, close, volume] = values.nonNulls.toList();
    if (low <= 0 ||
        low > math.min(open, close) ||
        high < math.max(open, close) ||
        volume < 0) {
      return null;
    }
    return _Bar(
      date,
      open,
      high,
      low,
      close,
      volume,
      complete: row['complete'] != false,
    );
  }
}

class _Indicators {
  _Indicators(List<_Bar> bars) : closes = [for (final bar in bars) bar.close] {
    ma5 = _sma(5);
    ma20 = _sma(20);
    final fast = _ema(closes, 12);
    final slow = _ema(closes, 26);
    macd = List.generate(
      closes.length,
      (i) => fast[i] == null || slow[i] == null ? null : fast[i]! - slow[i]!,
    );
    signal = _ema(macd, 9);
    rsi = _rsi();
  }

  final List<double> closes;
  late final List<double?> ma5, ma20, macd, signal, rsi;

  List<double?> _sma(int period) {
    var sum = 0.0;
    return List.generate(closes.length, (i) {
      sum += closes[i];
      if (i >= period) sum -= closes[i - period];
      return i + 1 < period ? null : sum / period;
    });
  }

  static List<double?> _ema(List<double?> values, int period) {
    var sum = 0.0, count = 0;
    double? previous;
    return values.map((value) {
      if (value == null) return null;
      if (previous case final last?) {
        return previous = last + (value - last) * 2 / (period + 1);
      }
      sum += value;
      return ++count < period ? null : previous = sum / period;
    }).toList();
  }

  List<double?> _rsi() {
    const period = 14;
    var gain = 0.0, loss = 0.0;
    return List.generate(closes.length, (i) {
      if (i == 0) return null;
      final change = closes[i] - closes[i - 1];
      final up = math.max(0.0, change), down = math.max(0.0, -change);
      if (i <= period) {
        gain += up / period;
        loss += down / period;
      } else {
        gain = (gain * (period - 1) + up) / period;
        loss = (loss * (period - 1) + down) / period;
      }
      if (i < period) return null;
      return gain + loss == 0 ? 50.0 : 100 * gain / (gain + loss);
    });
  }

  String caption(ChartIndicator indicator, int i) {
    String format(double? value) => value?.toStringAsFixed(2) ?? '—';
    return switch (indicator) {
      ChartIndicator.volume => '거래량',
      ChartIndicator.macd =>
        macd[i] == null
            ? 'MACD(12, 26, 9) · 완료 봉 26개부터'
            : 'MACD ${format(macd[i])} · 시그널 ${format(signal[i])}',
      ChartIndicator.rsi =>
        rsi[i] == null ? 'RSI(14) · 완료 봉 15개부터' : 'RSI(14)  ${format(rsi[i])}',
    };
  }
}

class _ChartPainter extends CustomPainter {
  _ChartPainter({
    required this.bars,
    required this.start,
    required this.end,
    required this.style,
    required this.indicator,
    required this.indicators,
    required this.averages,
    required this.cursor,
    required this.liveIndex,
    required this.fresh,
    required this.interval,
    required this.invertedColors,
  });

  final List<_Bar> bars;
  final int start, end;
  final ChartStyle style;
  final ChartIndicator? indicator;
  final _Indicators indicators;
  final bool averages;
  final int? cursor;
  final int? liveIndex;
  final bool fresh;
  final String interval;
  final bool invertedColors;
  static const _grid = Color(0xff303034);
  static const _blue = Color(0xff5e8eff);
  static const _gold = Color(0xffffbe68);
  static const _purple = Color(0xffb7a3ff);
  static const _axisColor = Color(0xffa1a1a6);
  static const _axisRow = 13.0;

  List<int> _evenTicks() {
    final count = math.min(4, end - start);
    if (count == 1) return [start];
    return List.generate(
      count,
      (i) => start + (i * (end - start - 1) / (count - 1)).round(),
    );
  }

  List<int> _dayStarts() => [
    start,
    for (var i = start + 1; i < end; i++)
      if (!DateUtils.isSameDay(
        _marketTime(bars[i - 1].date),
        _marketTime(bars[i].date),
      ))
        i,
  ];

  @override
  void paint(Canvas canvas, Size size) {
    final width = size.width - 62;
    if (width <= 0 || size.height <= 48) return;
    final intraday = _isIntraday(interval);
    final plotBottom = size.height - (intraday ? 2 : 1) * _axisRow - 3;
    final indicatorHeight = indicator == null
        ? 0.0
        : math.min(59.0, plotBottom * .29);
    final priceBottom = plotBottom - indicatorHeight - 8;
    final visible = bars.sublist(start, end);
    final bounds = [
      for (final bar in visible) ...[bar.high, bar.low],
      if (averages)
        for (var i = start; i < math.min(end, indicators.closes.length); i++)
          ...[indicators.ma5[i], indicators.ma20[i]].nonNulls,
    ];
    final low = bounds.reduce(math.min);
    final high = math.max(low + 1, bounds.reduce(math.max));
    final step = width / (end - start);
    double x(int i) => (i - start + .5) * step;
    double y(double price) =>
        7 + (high - price) / (high - low) * (priceBottom - 7);
    if (intraday) {
      for (final index in _dayStarts().skip(1)) {
        final boundary = x(index) - step / 2;
        canvas.drawLine(
          Offset(boundary, 7),
          Offset(boundary, plotBottom),
          Paint()..color = _axisColor.withValues(alpha: .4),
        );
      }
    }
    for (var i = 0; i < 3; i++) {
      final price = high - (high - low) * i / 2;
      final dy = y(price);
      _horizontal(canvas, width, dy);
      _label(canvas, price.round().toString(), Offset(width + 5, dy - 6));
    }
    if (style == ChartStyle.line || style == ChartStyle.area) {
      if (style == ChartStyle.area && end - start > 1) {
        final area = Path()..moveTo(x(start), priceBottom);
        for (var i = start; i < end; i++) {
          area.lineTo(x(i), y(bars[i].close));
        }
        area.lineTo(x(end - 1), priceBottom);
        area.close();
        canvas.drawPath(area, Paint()..color = _blue.withValues(alpha: .24));
      }
      _series(canvas, (i) => bars[i].close, x, y, _blue);
    } else {
      for (var i = start; i < end; i++) {
        final bar = bars[i];
        final paint = Paint()
          ..color = _candleColor(
            bar.open,
            bar.close,
            invertedColors: invertedColors,
          )
          ..strokeWidth = 1.4;
        final center = x(i), open = y(bar.open), close = y(bar.close);
        canvas.drawLine(
          Offset(center, y(bar.high)),
          Offset(center, y(bar.low)),
          paint,
        );
        if (style == ChartStyle.ohlc) {
          canvas.drawLine(
            Offset(center - step * .32, open),
            Offset(center, open),
            paint,
          );
          canvas.drawLine(
            Offset(center, close),
            Offset(center + step * .32, close),
            paint,
          );
        } else {
          canvas.drawRect(
            Rect.fromLTWH(
              center - step * .3,
              math.min(open, close),
              step * .6,
              math.max(1, (open - close).abs()),
            ),
            paint,
          );
        }
      }
    }
    if (averages) {
      _series(canvas, (i) => indicators.ma5.elementAtOrNull(i), x, y, _gold);
      _series(canvas, (i) => indicators.ma20.elementAtOrNull(i), x, y, _purple);
      _label(canvas, 'MA5', const Offset(2, 1), color: _gold);
      _label(canvas, 'MA20', const Offset(28, 1), color: _purple);
    }
    if (indicator != null) {
      _paintIndicator(canvas, width, priceBottom + 6, plotBottom - 3, step, x);
    }
    final tail = end - 1;
    if (indicator != null) {
      final tailColor = liveIndex == tail && fresh
          ? _candleColor(
              tail > 0 ? bars[tail - 1].close : bars[tail].open,
              bars[tail].close,
              invertedColors: invertedColors,
            )
          : _blue;
      final position = Offset(x(tail), y(bars[tail].close));
      if (liveIndex == tail && fresh) {
        canvas.drawCircle(
          position,
          7,
          Paint()..color = tailColor.withValues(alpha: .25),
        );
      }
      canvas.drawCircle(position, 4, Paint()..color = tailColor);
      if (cursor == null) {
        _priceMarker(canvas, size.width, position, bars[tail].close, tailColor);
      }
    }
    if (cursor case final i? when i >= start && i < end) {
      final paint = Paint()
        ..color = const Color(0xffa1a1a6)
        ..strokeWidth = .8;
      canvas.drawLine(Offset(x(i), 3), Offset(x(i), plotBottom), paint);
      canvas.drawCircle(Offset(x(i), y(bars[i].close)), 3, paint);
      _priceMarker(
        canvas,
        size.width,
        Offset(x(i), y(bars[i].close)),
        bars[i].close,
        _blue,
      );
    }
    _paintTimeAxis(canvas, width, plotBottom, step, x, intraday);
  }

  void _paintTimeAxis(
    Canvas canvas,
    double width,
    double top,
    double step,
    double Function(int) x,
    bool intraday,
  ) {
    _horizontal(canvas, width, top);
    final first = _marketTime(bars[start].date);
    final last = _marketTime(bars[end - 1].date);
    final showYear = first.year != last.year;
    if (intraday) {
      final halfHourTicks = <(double, String)>[];
      final tickPaint = Paint()..color = _axisColor.withValues(alpha: .55);
      for (var i = start; i < end; i++) {
        final time = _marketTime(bars[i].date);
        if (time.minute % 30 != 0) continue;
        final position = x(i);
        canvas.drawLine(
          Offset(position, top - 3),
          Offset(position, top),
          tickPaint,
        );
        halfHourTicks.add((position, _chartTime(time)));
      }
      _axisLabels(canvas, width, top + 2, halfHourTicks);
      _axisLabels(canvas, width, top + _axisRow + 2, [
        for (final i in _dayStarts())
          (
            x(i) - step / 2,
            _chartDate(_marketTime(bars[i].date), showYear: showYear),
          ),
      ], alignLeft: true);
      return;
    }
    _axisLabels(canvas, width, top + 2, [
      for (final i in _evenTicks())
        (
          x(i),
          interval == '1y'
              ? '${_marketTime(bars[i].date).year}년'
              : _chartDate(
                  _marketTime(bars[i].date),
                  showYear: showYear || interval == '1mo',
                ),
        ),
    ]);
  }

  void _axisLabels(
    Canvas canvas,
    double width,
    double y,
    List<(double, String)> ticks, {
    bool alignLeft = false,
  }) {
    if (ticks.isEmpty) return;
    final occupied = <(double, double)>[];
    // Keep the start and end dates visible when a zoomed-out view has many sessions.
    for (final index in [
      0,
      if (ticks.length > 1) ticks.length - 1,
      for (var i = 1; i < ticks.length - 1; i++) i,
    ]) {
      final (x, value) = ticks[index];
      final label = TextPainter(
        text: TextSpan(
          text: value,
          style: const TextStyle(color: _axisColor, fontSize: 9),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      final left = (x - (alignLeft ? 0 : label.width / 2))
          .clamp(0.0, math.max(0.0, width - label.width))
          .toDouble();
      final right = left + label.width;
      if (right <= width &&
          !occupied.any((span) => left < span.$2 + 4 && right + 4 > span.$1)) {
        label.paint(canvas, Offset(left, y));
        occupied.add((left, right));
      }
      label.dispose();
    }
  }

  @override
  SemanticsBuilderCallback get semanticsBuilder => (size) {
    final first = _marketTime(bars[start].date);
    final last = _marketTime(bars[end - 1].date);
    String label(DateTime date) =>
        '${_chartDate(date, showYear: true)}${_isIntraday(interval) ? ' ${_chartTime(date)}' : ''}';
    return [
      CustomPainterSemantics(
        rect: Rect.fromLTWH(
          0,
          math.max(0.0, size.height - 2 * _axisRow),
          size.width,
          math.min(2 * _axisRow, size.height),
        ),
        properties: SemanticsProperties(
          label: '차트 기간 ${label(first)} ~ ${label(last)} · 한국 시간',
          textDirection: TextDirection.ltr,
        ),
      ),
    ];
  };

  void _paintIndicator(
    Canvas canvas,
    double width,
    double top,
    double bottom,
    double step,
    double Function(int) x,
  ) {
    _horizontal(canvas, width, top);
    if (indicator == ChartIndicator.volume) {
      final maxVolume = math.max(
        1.0,
        bars.sublist(start, end).map((bar) => bar.volume).reduce(math.max),
      );
      for (var i = start; i < end; i++) {
        final bar = bars[i];
        final height = bar.volume / maxVolume * (bottom - top);
        canvas.drawRect(
          Rect.fromLTWH(x(i) - step * .28, bottom - height, step * .56, height),
          Paint()
            ..color = _candleColor(
              bar.open,
              bar.close,
              invertedColors: invertedColors,
            ).withValues(alpha: .7),
        );
      }
      _label(canvas, '거래량', Offset(width + 5, top + 4));
    } else if (indicator == ChartIndicator.rsi) {
      double y(double value) => bottom - value / 100 * (bottom - top);
      for (final level in [30.0, 70.0]) {
        _horizontal(canvas, width, y(level));
        _label(
          canvas,
          level.round().toString(),
          Offset(width + 5, y(level) - 6),
        );
      }
      _series(canvas, (i) => indicators.rsi.elementAtOrNull(i), x, y, _purple);
    } else {
      final bounds = [
        .001,
        for (var i = start; i < math.min(end, indicators.closes.length); i++)
          ...[
            indicators.macd[i],
            indicators.signal[i],
            if (indicators.macd[i] != null && indicators.signal[i] != null)
              indicators.macd[i]! - indicators.signal[i]!,
          ].nonNulls.map((v) => v.abs()),
      ];
      final maxValue = bounds.reduce(math.max);
      double y(double value) =>
          bottom - (value + maxValue) / (2 * maxValue) * (bottom - top);
      _horizontal(canvas, width, y(0));
      _label(canvas, '0', Offset(width + 5, y(0) - 6));
      for (var i = start; i < math.min(end, indicators.closes.length); i++) {
        final macd = indicators.macd[i], signal = indicators.signal[i];
        if (macd == null || signal == null) continue;
        final value = macd - signal;
        final dy = y(value);
        canvas.drawRect(
          Rect.fromLTWH(
            x(i) - step * .28,
            math.min(dy, y(0)),
            step * .56,
            (dy - y(0)).abs(),
          ),
          Paint()
            ..color = _candleColor(
              0,
              value,
              invertedColors: invertedColors,
            ).withValues(alpha: .65),
        );
      }
      _series(canvas, (i) => indicators.macd.elementAtOrNull(i), x, y, _blue);
      _series(canvas, (i) => indicators.signal.elementAtOrNull(i), x, y, _gold);
    }
  }

  void _series(
    Canvas canvas,
    double? Function(int) value,
    double Function(int) x,
    double Function(double) y,
    Color color,
  ) {
    final path = Path();
    var started = false;
    for (var i = start; i < end; i++) {
      final v = value(i);
      if (v == null) {
        started = false;
      } else if (started) {
        path.lineTo(x(i), y(v));
      } else {
        path.moveTo(x(i), y(v));
        canvas.drawCircle(Offset(x(i), y(v)), 1, Paint()..color = color);
        started = true;
      }
    }
    canvas.drawPath(
      path,
      Paint()
        ..color = color
        ..strokeWidth = 1.4
        ..style = PaintingStyle.stroke,
    );
  }

  void _horizontal(Canvas canvas, double width, double y) =>
      canvas.drawLine(Offset(0, y), Offset(width, y), Paint()..color = _grid);

  void _priceMarker(
    Canvas canvas,
    double width,
    Offset point,
    double price,
    Color color,
  ) {
    final label = TextPainter(
      text: TextSpan(
        text: '${won(price.round())}원',
        style: const TextStyle(
          color: Colors.white,
          fontSize: 9,
          fontWeight: FontWeight.w600,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    final left = width - label.width - 10;
    final rect = Rect.fromLTWH(left, point.dy - 8, label.width + 10, 16);
    canvas.drawLine(
      point,
      Offset(left, point.dy),
      Paint()..color = color.withValues(alpha: .55),
    );
    canvas.drawRRect(
      RRect.fromRectAndRadius(rect, const Radius.circular(4)),
      Paint()..color = color.withValues(alpha: 1),
    );
    label.paint(canvas, Offset(left + 5, point.dy - label.height / 2));
    label.dispose();
  }

  void _label(
    Canvas canvas,
    String value,
    Offset position, {
    Color color = const Color(0xffa1a1a6),
  }) {
    final label = TextPainter(
      text: TextSpan(
        text: value,
        style: TextStyle(color: color, fontSize: 9),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    label.paint(canvas, position);
    label.dispose();
  }

  @override
  bool shouldRepaint(covariant _ChartPainter oldDelegate) =>
      oldDelegate.bars != bars ||
      oldDelegate.start != start ||
      oldDelegate.end != end ||
      oldDelegate.style != style ||
      oldDelegate.indicator != indicator ||
      oldDelegate.averages != averages ||
      oldDelegate.cursor != cursor ||
      oldDelegate.liveIndex != liveIndex ||
      oldDelegate.fresh != fresh ||
      oldDelegate.interval != interval ||
      oldDelegate.invertedColors != invertedColors;
}
