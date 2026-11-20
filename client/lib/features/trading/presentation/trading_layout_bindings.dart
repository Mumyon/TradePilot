import 'dart:convert';
import 'dart:math' as math;
import '../../../core/design/design_document.dart';
import '../domain/trading_models.dart';
import '../domain/workspace_repository.dart';
import 'trading_controller.dart';
import 'market_quote_status.dart';

String won(int value) => '$value'.replaceAllMapped(
  RegExp(r'(\d)(?=(\d{3})+(?!\d))'),
  (m) => '${m[1]},',
);
String orderStatus(String status) => switch (status) {
  'accepted' => '접수',
  'filled' => '체결',
  'rejected' => '거절',
  'cancelled' => '취소',
  'partially_filled' => '부분 체결',
  _ => status,
};

String _watchlistSparkline(Iterable<int> samples) {
  final prices = samples.toList();
  if (prices.length < 2) {
    return '<path d="M28 16h8" stroke="#797980" stroke-width="1"/>';
  }
  final low = prices.reduce(math.min);
  final span = prices.reduce(math.max) - low;
  final points = [
    for (final (index, price) in prices.indexed)
      '${(64 * index / (prices.length - 1)).toStringAsFixed(1)},'
          '${(span == 0 ? 16 : 28 - 24 * (price - low) / span).toStringAsFixed(1)}',
  ].join(' ');
  return '<polyline points="$points" fill="none" stroke="#F5F5F2" stroke-width="1.4"/>';
}

Iterable<int> _testWatchlistPrices(String symbol) {
  final random = math.Random(
    symbol.codeUnits.fold<int>(
      0,
      (seed, code) => (seed * 31 + code) & 0x7fffffff,
    ),
  );
  final motif = List.generate(6, (_) => random.nextInt(11));
  return [...motif, ...motif, motif.first];
}

/// Bind server-owned facts without presenting prototype balances/returns as real.
class TradingLayoutBindings {
  static const optionsTab = 35;

  TradingLayoutBindings(
    this.controller, {
    required this.screen,
    required this.quantity,
    required this.price,
    required this.side,
    required this.query,
    required this.segment,
    this.navigationScreen,
  });
  final TradingController controller;
  final int screen, quantity, price, segment;
  final int? navigationScreen;
  final OrderSide side;
  final String query;
  bool get demo => controller.repository.isDemo;
  String get sideLabel => side == OrderSide.buy ? '매수' : '매도';
  String get stockName => controller.selectedName;
  String get symbol => controller.selectedSymbol ?? '';
  String get connection => controller.online ? '시세 연결됨' : '시세 연결 대기';
  String quoteStatus(Quote quote, {bool compact = false, bool live = false}) {
    final session = RegExp(r'^\d{6}$').hasMatch(quote.symbol)
        ? (controller.accountData?['market_session'] as Map?)
        : null;
    final label = quote.source == 'demo'
        ? '테스트 시세'
        : marketQuoteLabel(
            available: true,
            fresh: live || quote.isFresh(DateTime.now().toUtc()),
            session: session,
          );
    final time = koreanMarketTime(quote.asOf, seconds: !compact);
    return '$label · $time';
  }

  bool get confirmation =>
      screen == 5 || {11, 14, 17, 20, 23, 26, 29, 32}.contains(screen);
  bool get completion => {10, 13, 16, 19, 22, 25, 28, 31, 34}.contains(screen);
  bool get orderPopup => {12, 15, 18, 21, 24, 27, 30, 33}.contains(screen);

  static const _pilotAiPredictionRowGap = 16;

  String _pilotAiPredictionStatusText() {
    final prediction = controller.prediction;
    if (prediction != null &&
        DateTime.now().toUtc().isBefore(prediction.validUntil)) {
      String percent(double probability) =>
          '${(100 * probability).toStringAsFixed(1)}%';
      return '1시간 · 상승 ${percent(prediction.up)} · 중립 ${percent(prediction.neutral)}'
          ' · 하락 ${percent(prediction.down)}';
    }
    return switch (controller.predictionReason) {
      'market_close' => '1시간 예측 · 정규장 예측 시간 외',
      'market_hours_unavailable' => '1시간 예측 · 정규장 시간 확인 중',
      'insufficient_bars' => '1시간 예측 · 완료 5분봉 수집 중',
      'stale_data' => '1시간 예측 · 최신 5분봉 대기',
      'training_overlap' => '1시간 예측 · 평가 이후 시세 대기',
      'connection' => '1시간 예측 · 서버 연결 확인',
      'model_not_configured' ||
      'symbol_mismatch' ||
      'synthetic_model' ||
      'quality_gate' ||
      'source_mismatch' ||
      'model_invalid' => '예측 검증 모델 대기',
      _ => '1시간 예측 · 확률 확인 중',
    };
  }

  String _pilotAiFiveMinuteCandleText() {
    final summary = controller.fiveMinuteSummary;
    if (summary == null) return '5분봉 · 완료 봉 대기';
    final closed = DateTime.tryParse('${summary['closed_at']}');
    final stale =
        closed == null ||
        DateTime.now().difference(closed) > const Duration(minutes: 10);
    final prefix = stale ? '5분봉 지연' : '완료 5분봉';
    final parts = <String>[prefix];
    for (final (label, key) in [
      ('15분', 'return_15m_pct'),
      ('1시간', 'return_60m_pct'),
      ('거래량', 'volume_change_15m_pct'),
    ]) {
      if (summary[key] case final num value) {
        parts.add('$label ${value > 0 ? '+' : ''}${value.toStringAsFixed(1)}%');
      }
    }
    if (parts.length == 1) parts.add('연속 봉 부족');
    return parts.join(' · ');
  }

  void apply(DesignNode root) {
    if (controller.repository is WorkspaceRepository) {
      for (final node in children(root)) {
        if (node['name'] == 'Popup panel') {
          children(
            node,
          ).removeWhere((n) => n['type'] == 'text' && n['y'] == 495);
        }
      }
    }

    if (screen == 3) {
      children(root).removeWhere(
        (node) =>
            {
              '1회 주문한도',
              '일 손실한도',
              '연속 손실 후 쿨다운',
              '전체 자동매매 중지',
            }.contains(node['name']) ||
            node['value'] == '위험관리 설정',
      );
    }
    if (screen == 1 || screen == 8) {
      if (controller.repository is WorkspaceRepository) {
        final card = children(
          root,
        ).firstWhere((n) => n['name'] == 'AI forecast');
        card['h'] = 125 + _pilotAiPredictionRowGap;
        children(card).firstWhere((n) => n['type'] == 'rect')['h'] = card['h'];
        children(card).add({
          'type': 'text',
          'value': _pilotAiPredictionStatusText(),
          'x': 14,
          'y': 59 + _pilotAiPredictionRowGap,
          'w': 310,
          'h': 18,
          'size': 12,
          'color': 'fg',
          'weight': 500,
        });
        children(card).add({
          'type': 'text',
          'value': _pilotAiFiveMinuteCandleText(),
          'x': 14,
          'y': 80 + _pilotAiPredictionRowGap,
          'w': 314,
          'h': 18,
          'size': 11,
          'color': 'fg',
          'weight': 500,
        });
      }
      children(root).removeWhere(
        (node) => node['type'] == 'text' && {145, 190, 218}.contains(node['y']),
      );
      children(root).add({
        'type': 'text',
        'name': 'Chart daily change',
        'value': '',
        'x': 24,
        'y': 204,
        'w': 342,
        'h': 24,
        'size': 14,
        'color': 'muted',
        'weight': 500,
      });
    }
    for (final navigation in children(
      root,
    ).where((node) => node['name'] == 'Bottom navigation')) {
      final tabs = children(navigation);
      final options =
          jsonDecode(
                jsonEncode(tabs.firstWhere((n) => n['name'] == 'Tab / 관심종목')),
              )
              as DesignNode;
      options['name'] = 'Tab / 더보기';
      options['target'] = optionsTab;
      tabs.add(options);
      for (final tab in tabs.where((n) => n['type'] == 'group')) {
        final name = tab['name'];
        final (index, label, icon) = switch (name) {
          'Tab / 관심종목' => (0, '메인', 'M3 10L11 3L19 10V19H13V14H9V19H3Z'),
          'Tab / 차트' => (1, '차트', null),
          'Tab / 전체 메뉴' => (
            2,
            '발견',
            'M16 16L20 20M17 10A7 7 0 1 1 3 10A7 7 0 1 1 17 10Z',
          ),
          'Tab / 매매일지' => (3, '매매일지', null),
          'Tab / 자동매매' => (4, '주식 잔고', 'M19 6H4V18H19V6ZM19 9H14V15H19'),
          _ => (5, '더보기', 'M4 6H18M4 11H18M4 16H14'),
        };
        final active = navigationScreen ?? screen;
        final selected =
            tab['target'] == active || (tab['target'] == 1 && active == 8);
        final stroke = selected ? '#F5F5F2' : '#797980';
        tab['name'] = 'Tab / $label';
        tab['x'] = index * 65;
        tab['w'] = 65;
        for (final child in children(tab)) {
          if (child['type'] == 'text') {
            child['value'] = label;
            child['w'] = 65;
            child['color'] = selected ? 'fg' : 'muted';
          }
          if (child['type'] == 'svg') {
            child['x'] = 21.5;
            child['body'] = icon == null
                ? (child['body'] as String).replaceAll(
                    RegExp(r'#[A-Fa-f0-9]{6}'),
                    stroke,
                  )
                : '<path d="$icon" fill="none" stroke="$stroke" stroke-width="1.5"/>';
          }
        }
      }
    }
    if (screen == 0 && controller.repository is WorkspaceRepository) {
      final nodes = children(root);
      final template = nodes.firstWhere(
        (n) => (n['name'] as String? ?? '').startsWith('Stock / '),
      );
      final rows = <DesignNode>[];
      final instruments = controller.testMode
          ? {
              ...controller.watchlistInstruments,
              for (final quote in controller.market.values)
                quote.symbol: quote.name,
            }
          : {
              for (final quote in controller.market.values)
                quote.symbol: quote.name,
            };
      for (final MapEntry(key: symbol, value: name) in instruments.entries) {
        final quote = controller.market[symbol];
        final samples = controller.watchlistPrices(symbol);
        final showTestGraph = controller.testMode && samples.length < 2;
        final domestic = RegExp(r'^\d{6}$').hasMatch(symbol);
        if (segment == 1 && !domestic || segment == 2 && domestic) continue;
        final row = jsonDecode(jsonEncode(template)) as DesignNode;
        row['name'] = 'Live stock / $symbol';
        row['action'] = 'SELECT_SYMBOL';
        row['symbol'] = symbol;
        row['y'] = 314 + rows.length * 70;
        final texts = children(row).where((n) => n['type'] == 'text').toList();
        texts[0]['value'] = name;
        texts[1]['value'] = symbol;
        texts[2]['value'] = quote == null ? '—' : won(quote.priceWon);
        texts[3]['value'] = showTestGraph
            ? '테스트 그래프'
            : quote == null
            ? '시세 연결 대기'
            : quoteStatus(quote, compact: true);
        final sparkline = children(row).firstWhere((n) => n['type'] == 'svg');
        sparkline['body'] = _watchlistSparkline(
          showTestGraph ? _testWatchlistPrices(symbol) : samples,
        );
        rows.add(row);
      }
      nodes.removeWhere(
        (n) => (n['name'] as String? ?? '').startsWith('Stock / '),
      );
      nodes.addAll(rows);
      final insight = nodes.firstWhere((n) => n['name'] == 'Pilot insight');
      insight['y'] = 339 + (rows.length < 4 ? 4 : rows.length) * 70;
      root['h'] = 844 + (rows.length > 4 ? (rows.length - 4) * 70 : 0);
      if (rows.isEmpty) {
        nodes.add({
          'type': 'text',
          'value': '관심종목이 없습니다. 검색에서 추가하세요.',
          'x': 24,
          'y': 330,
          'w': 342,
          'h': 40,
          'size': 13,
          'color': 'muted',
          'weight': 400,
        });
      }
      root['children'] = nodes;
    }
    _walk(children(root), '');
    if (screen == 0) {
      final insight = children(
        root,
      ).firstWhere((node) => node['name'] == 'Pilot insight');
      children(insight).removeWhere((node) => node['type'] == 'rect');
    }
    if (screen == 1 || screen == 8) _styleChart(root);
    if ((screen == 1 || screen == 8) && !controller.pilotEnabled) {
      final nodes = children(root);
      final card = nodes.firstWhere((node) => node['name'] == 'AI forecast');
      final top = number(card, 'y');
      final height = number(card, 'h');
      card['hidden'] = true;
      for (final node in nodes) {
        if (number(node, 'y') >= top + height) {
          node['y'] = number(node, 'y') - height;
        }
      }
      root['h'] = number(root, 'h') - height;
    }
    if ((screen == 1 || screen == 8) &&
        controller.repository is WorkspaceRepository) {
      final nodes = children(root);
      const top = 291.0;
      final body = nodes
          .where(
            (node) =>
                number(node, 'y') >= top && node['name'] != 'Bottom navigation',
          )
          .toList();
      nodes.removeWhere(body.contains);
      for (final node in body) {
        node['y'] = number(node, 'y') - top;
      }
      nodes.add({
        'type': 'group',
        'name': 'Chart tab content',
        'x': 0,
        'y': top,
        'w': 390,
        'h': number(root, 'h') - top - 93,
        'children': body,
      });
    }
    if (screen == 0 &&
        (segment != 0 || controller.repository is WorkspaceRepository)) {
      var row = 0;
      for (final n in children(root).where(
        (n) =>
            (n['name'] as String? ?? '').startsWith('Stock / ') &&
            n['hidden'] != true,
      )) {
        n['y'] = 314 + row++ * 70;
      }
    }
    if (screen == 7 || screen == 9) {
      final panel = children(
        root,
      ).firstWhere((n) => n['name'] == 'Popup panel');
      var row = 0;
      for (final n in children(panel).where(
        (n) =>
            (n['name'] as String? ?? '').startsWith('Search result / ') &&
            n['hidden'] != true,
      )) {
        n['y'] = 194 + row++ * 89;
      }
      if (row == 0) {
        final hint = children(
          panel,
        ).firstWhere((n) => n['type'] == 'text' && number(n, 'y') == 154);
        hint['value'] = '검색 결과가 없습니다.';
      }
    }
  }

  void _styleChart(DesignNode root) {
    final nodes = children(root);
    final live = controller.repository is WorkspaceRepository;
    DesignNode named(String name) => nodes.firstWhere((n) => n['name'] == name);
    DesignNode textAt(int y) =>
        nodes.firstWhere((n) => n['type'] == 'text' && n['y'] == y);
    final status = textAt(675);
    status.addAll({'x': 145, 'y': 55, 'w': 221, 'align': 'right'});
    if (!live) status['value'] = '테스트 시세';
    nodes.add({
      'type': 'text',
      'value': 'TradePilot',
      'x': 24,
      'y': 50,
      'w': 118,
      'h': 24,
      'size': 16,
      'weight': 600,
      'color': 'fg',
    });
    final search = named('Chart / Search field');
    search['y'] = 81;
    final searchNodes = children(search);
    searchNodes.firstWhere((n) => n['type'] == 'rect').addAll({
      'y': 43,
      'h': 1,
      'color': 'line',
    });
    searchNodes.firstWhere((n) => n['type'] == 'svg')['x'] = 0;
    searchNodes.firstWhere((n) => n['type'] == 'text')['x'] = 29;
    textAt(113).addAll({'y': 139, 'size': 20});
    textAt(150).addAll({'y': 167, 'size': 38, 'weight': 600, 'w': 342});
    named('Chart daily change')['y'] = 219;

    final plotHeight = live ? 253 : 236;
    named('Candlestick chart').addAll({'y': 247, 'h': plotHeight});
    final indicators = named('Segment navigation');
    indicators.addAll({'y': 253 + plotHeight, 'h': live ? 30 : 42});
    final pilot = named('AI forecast');
    if (live) {
      nodes.add({
        'type': 'group',
        'name': 'Chart stock details',
        'x': 24,
        'y': 128,
        'w': 342,
        'h': 42,
        'children': <DesignNode>[],
      });
      for (final node in nodes.where(
        (node) =>
            {
              'Candlestick chart',
              'Segment navigation',
              'Chart daily change',
            }.contains(node['name']) ||
            node['type'] == 'text' && {139, 167}.contains(node['y']),
      )) {
        node['y'] = number(node, 'y') + 44;
      }
    }
    final pilotTop = number(indicators, 'y') + number(indicators, 'h') + 12;
    const horizontalPadding = 12.0;
    const verticalPadding = 8.0;
    final cardHeight = (live ? 120 : 92) + 2 * verticalPadding;
    pilot.addAll({'y': pilotTop, 'h': cardHeight});
    final ai = children(pilot);
    ai.removeWhere((n) => n['type'] == 'rect');
    ai[0].addAll({'x': 0, 'y': 0, 'w': 342});
    ai[1].addAll({'x': 0, 'y': 20, 'w': 88});
    ai[2].addAll({'x': 0, 'y': 51, 'w': 342, 'size': 11, 'color': 'muted'});
    ai[2]['maxLines'] = live ? 2 : 1;
    if (live) {
      ai[3].addAll({'x': 186, 'y': 25, 'w': 156, 'align': 'right'});
      ai[4].addAll({'x': 0, 'y': 84, 'w': 342, 'color': 'muted'});
      ai[5].addAll({'x': 0, 'y': 104, 'w': 342, 'color': 'muted'});
    } else {
      ai[3].addAll({'x': 0, 'y': 70, 'w': 342});
    }
    for (final label in ai) {
      final x = number(label, 'x');
      final width = number(label, 'w');
      label.addAll({
        'x': x == 0 ? horizontalPadding : x - horizontalPadding,
        'y': number(label, 'y') + verticalPadding,
        'w': width == 342 ? width - 2 * horizontalPadding : width,
      });
    }
    ai.insert(0, {
      'type': 'rect',
      'x': 0,
      'y': 0,
      'w': 342,
      'h': cardHeight,
      'color': 'line',
      'opacity': 0.18,
      'borderColor': 'line',
    });
    final buttonsTop = pilotTop + number(pilot, 'h') + 8;
    for (final name in ['매수', '매도']) {
      named(name).addAll({'y': buttonsTop, 'centerText': true});
    }
    root['h'] = buttonsTop + 48 + 14 + 93;
  }

  void _walk(List<DesignNode> nodes, String parent) {
    for (final n in nodes) {
      final name = n['name'] as String? ?? '';
      if (name == '관심종목 검색' && controller.repository is WorkspaceRepository) {
        n['action'] = 'WORKSPACE';
      }
      if (n['type'] == 'group') {
        if (name.startsWith('Stock / ')) {
          final stock = name.substring(8);
          final code = {
            '삼성전자': '005930',
            'SK하이닉스': '000660',
            'NAVER': '035420',
            'Apple': 'AAPL',
          }[stock];
          final q = controller.market[code];
          if (controller.repository is WorkspaceRepository && q == null) {
            n['hidden'] = true;
          }
          final texts = children(n).where((v) => v['type'] == 'text').toList();
          if (q != null) texts[2]['value'] = won(q.priceWon);
          if (!demo) {
            texts[2]['value'] = q == null ? '미연결' : won(q.priceWon);
            texts[3]['value'] = q == null
                ? '시세 준비 중'
                : quoteStatus(q, compact: true);
          }
          if (segment == 1 && stock == 'Apple' ||
              segment == 2 && stock != 'Apple') {
            n['hidden'] = true;
          }
        }
        if (name.startsWith('Search result / ')) {
          final stock = name.substring(16);
          final code = stock == '삼성전자' ? '005930' : '000660';
          if (controller.repository is WorkspaceRepository &&
              !controller.market.containsKey(code)) {
            n['hidden'] = true;
          }
          if (query.isNotEmpty &&
              !stock.contains(query) &&
              !code.contains(query)) {
            n['hidden'] = true;
          }
        }
        if (name == 'AI forecast') n['action'] = 'AI_DETAILS';
        if (name == '전체 자동매매 중지') n['action'] = 'UNAVAILABLE';
        if (screen == 3 && name == 'Active strategy') n['action'] = 'PLANS';
        if (name == 'Paper account') n['action'] = 'ACCOUNT';
        if (name == 'Segment navigation') {
          final labels = children(n).where((e) => e['type'] == 'text').toList();
          for (var i = 0; i < labels.length; i++) {
            labels[i]['action'] = 'SEGMENT';
            labels[i]['index'] = i;
            labels[i]['name'] = 'segment:$i';
            labels[i]['color'] = i == segment ? 'fg' : 'muted';
            labels[i]['weight'] = i == segment ? 600 : 400;
          }
          for (final line in children(n).where((e) => e['type'] == 'rect')) {
            line['x'] = segment * number(n, 'w') / labels.length;
          }
        }
        if (name == 'Journal entry' &&
            (!demo || controller.journal.isNotEmpty)) {
          final index = number(n, 'y') < 550 ? 0 : 1;
          final texts = children(n).where((e) => e['type'] == 'text').toList();
          if (index >= controller.journal.length) {
            texts[0]['value'] = index == 0 ? '아직 주문 내역이 없습니다.' : '';
            texts[1]['value'] = index == 0 ? '모의 주문 후 이곳에서 확인하세요.' : '';
            texts[2]['value'] = '';
          } else {
            final order = controller.journal[index];
            texts[0]['value'] =
                controller.market[order.symbol]?.name ?? order.symbol;
            texts[0]['w'] = 240;
            texts[1]['value'] =
                '주문 ${order.id.length > 20 ? order.id.substring(0, 20) : order.id}';
            texts[1]['size'] = 10;
            texts[2]['value'] = orderStatus(order.status);
          }
        }
        _walk(children(n), name);
      }
      if (n['type'] != 'text') continue;
      final value = n['value'] as String;
      final y = number(n, 'y');
      if (value == '샘플 시세 · 실시간 데이터 아님') {
        n['value'] = controller.error != null
            ? '연결 오류 · 아래로 당겨 재시도'
            : controller.repository is WorkspaceRepository
            ? connection
            : '$connection · 데모 주식 시세';
      }
      if (screen == 0 &&
          value == '관심종목의 AI 근거를 확인하고 거래하세요.' &&
          controller.stage == OrderStage.uncertain) {
        n['value'] = '미확인 주문이 있어요. 눌러 결과를 확인하세요.';
        n['action'] = 'RECOVER';
      } else if (screen == 0 &&
          value == '관심종목의 AI 근거를 확인하고 거래하세요.' &&
          !controller.pilotEnabled) {
        n['value'] = 'TradePilot 시스템이 꺼져 있습니다.';
      }
      if (screen == 1 || screen == 8) {
        if (parent.isEmpty && y == 113) n['value'] = stockName;
        if (parent.isEmpty && y == 675) {
          final q = controller.chartDisplayQuote;
          n['value'] = q == null
              ? '시세 확인 중'
              : quoteStatus(q, live: controller.chartQuoteLive);
        }
        if (parent.isEmpty && y == 171) {
          n['y'] = 150;
          final quote = controller.chartDisplayQuote;
          n['value'] = quote == null ? '—' : '${won(quote.priceWon)}원';
        }
        if (parent == 'AI forecast' &&
            controller.repository is WorkspaceRepository) {
          final status = controller.marketAnalysisStatus;
          if (y == 32) {
            n['value'] =
                controller.marketAnalysisJudgment ??
                switch (status) {
                  'pending' || 'generating' => '분석',
                  'available' => '미정',
                  'failed' || 'unavailable' => '대기',
                  _ => '대기',
                };
          }
          if (y == 38) {
            n['value'] = switch (status) {
              'pending' || 'generating' => '현재 시세를 분석하고 있어요',
              'unavailable' || 'failed' =>
                controller.marketAnalysisMessage ?? '상세 화면에서 연결 상태를 확인해 주세요',
              'available' => '현재 시세와 시장 흐름 종합 판단',
              _ => '현재 시세와 시장 흐름 분석',
            };
          }
          if (y == 70) {
            n['y'] = 101 + _pilotAiPredictionRowGap;
            n['value'] = controller.selectedSymbol == null
                ? '종목을 먼저 선택하세요'
                : 'ChatGPT 분석 열기 →';
          }
        } else if (parent == 'AI forecast') {
          final p = controller.prediction;
          final valid =
              p != null && DateTime.now().toUtc().isBefore(p.validUntil);
          if (y == 32) {
            n['value'] = valid
                ? (p.direction == '방향 판단 보류' ? '관망' : p.direction)
                : '대기';
          }
          if (y == 38) {
            n['value'] = valid
                ? '데모 상승 가능성  ${(p.up * 100).round()}%'
                : '현재 AI 분석을 제공할 수 없어요';
          }
          if (y == 70) {
            n['value'] = valid
                ? '상승 ${(p.up * 100).round()} · 중립 ${(p.neutral * 100).round()} · 하락 ${(p.down * 100).round()}% / 상세 →'
                : '학습·분석 상태 보기 →';
          }
        }
      }
      if (screen == 7 || screen == 9) {
        if (value.startsWith('최근 검색')) {
          n['value'] = query.isEmpty ? '최근 검색 · 종목을 선택하세요' : '검색 결과';
        }
        if (value.startsWith('예시 종목')) n['value'] = '관심종목 내 이름 또는 코드로 검색하세요.';
      }
      if (orderPopup && parent == 'Popup panel') {
        if (y == 70) n['value'] = '$stockName  ·  $symbol';
        if (y == 171) {
          n['value'] = '${won(price)}원';
          n['action'] = 'EDIT_PRICE';
          n['name'] = '가격 입력';
        }
        if (y == 250 && number(n, 'x') == 190) {
          n['value'] = '$quantity주';
          n['action'] = 'EDIT_QUANTITY';
          n['name'] = '수량 입력';
        }
        if (y == 324) n['value'] = '${won(price * quantity)}원';
      }
      if (screen == 5) {
        if (parent.isEmpty && y == 143) n['value'] = stockName;
        if (parent.isEmpty && y == 175) {
          n['value'] = '$symbol · KRX / 모의 $sideLabel';
        }
        if (parent.isEmpty && y == 261) n['value'] = won(price * quantity);
        if (parent == '주문 가격' && number(n, 'x') == 198) {
          n['value'] = '${won(price)}원';
        }
        if (parent == '주문 수량' && number(n, 'x') == 198) {
          n['value'] = '$quantity주';
        }
        if (parent == '주문 후 예수금' && number(n, 'x') == 198) {
          final cash = controller.accountData?['available_cash_won'];
          final amount = price * quantity;
          final fee = (amount * 15 + 99999) ~/ 100000;
          n['value'] = cash == null
              ? '잔고 확인 불가'
              : side == OrderSide.buy
              ? '${won(int.parse('$cash') - amount - fee)}원 (예상)'
              : '체결 후 반영';
        }
        if (value == '진입 근거와 위험 한도를 확인했습니다.') {
          n['value'] = '서버 주문 점검 결과를 확인했습니다.';
        }
      }
      if (confirmation && screen != 5) {
        if (parent.isEmpty && y == 146) n['value'] = '$stockName · $sideLabel';
        if (parent.isEmpty && y == 192) {
          n['value'] = '지정가 ${won(price)}원 × $quantity주';
        }
        if (parent.isEmpty && y == 291) {
          n['value'] = '${won(price * quantity)}원';
        }
        if (parent == 'Order check' && y == 50) {
          n['value'] = controller.check?.allowed == true
              ? (controller.check!.behavior['enabled'] == true
                    ? '행동 점수 ${controller.check!.behavior['score']}/100 · ${controller.check!.behavior['partial'] == true ? '일부 판단 불가' : '근거 확인'}'
                    : '서버 주문 점검 통과')
              : '주문 점검 필요';
        }
        if (parent == 'Order check' && y == 80) n['value'] = '점검 내용 보기 →';
        if (parent == 'Order check' && y == 80) {
          n['action'] = 'CHECK_DETAILS';
          n['name'] = '점검 내용';
        }
        if (value.startsWith('실제 거래로')) n['value'] = '실제 자금이 사용되지 않는 모의주문입니다.';
      }
      if (completion) {
        final status = controller.receipt?.status;
        if (parent.isEmpty &&
            y == 76 &&
            status != null &&
            status != 'accepted') {
          n['value'] = '모의주문 ${orderStatus(status)}';
        }
        if (y == 220) n['value'] = '$stockName $sideLabel';
        if (y == 265) n['value'] = '$quantity주 · 지정가 ${won(price)}원';
        if (y == 306) n['value'] = '주문금액  ${won(price * quantity)}원';
        if (y == 375) {
          n['value'] = controller.receipt?.status == 'accepted'
              ? '주문 접수 · 아직 체결되지 않았습니다.'
              : '주문 상태 · ${orderStatus(controller.receipt?.status ?? '미확인')}';
        }
      }
      if (value == '전체 보기 →') {
        n['action'] = 'JOURNAL';
        n['name'] = '전체 주문 보기';
      }
      if (!demo) {
        if (value == '자동매매') n['value'] = '모의투자';
        if (screen == 3 && value == '데모 상태 · 실계좌에 연결되지 않았습니다.') n['y'] = 727;
        if (value == '모의투자 프로토타입  /  v2') n['value'] = '핵심 모의투자 시연  /  v3';
        if (screen == 3) {
          const replacements = {
            '10,248,600': '—',
            '누적 손익  +248,600원  (+2.49%)': '계좌 평가 데이터 연결 대기',
            '운용 중  1': '계좌 현황',
            '전략 목록': '매매 계획',
            '01 / ACTIVE': '01 / 준비 중',
            '2건': '—',
            '+1.82%': '—',
            '전체 자동매매 중지': '자동매매 연결 준비 중',
            '데모 상태 · 실계좌에 연결되지 않았습니다.': '자동매매 엔진은 아직 연결되지 않았습니다.',
            '300,000원': '연결 대기',
            '30분': '연결 대기',
          };
          n['value'] = replacements[n['value']] ?? n['value'];
          if (value == '나의 자동매매') n['value'] = '나의 모의투자';
          if (value == 'AUTOPILOT / 원칙을 실행하다') n['value'] = 'PAPER / 원칙을 지키다';
          if (value == '10,248,600') {
            n['value'] = controller.accountData?['equity_won'] == null
                ? '—'
                : won(
                    int.parse(controller.accountData!['equity_won'] as String),
                  );
          }
          if (value.startsWith('누적 손익')) {
            n['value'] =
                '순실현손익 ${controller.accountData?['realized_pnl_won'] ?? '—'}원';
          }
          if (value == '전체 자동매매 중지') n['value'] = '거래 정지 · 위험한도 설정';
          if (value == '데모 상태 · 실계좌에 연결되지 않았습니다.') {
            n['value'] = '수동 모의주문 · 자동매매는 후속 확장';
          }
          if (parent == 'Active strategy') {
            n['value'] = switch (value) {
              '01 / ACTIVE' => 'MANUAL / 수동 모의주문',
              '추세 추종 · 분할 진입' => '매매 계획 등록 · 확인 →',
              '삼성전자 · SK하이닉스' => '주문 전에 가격 범위와 손절 기준 확인',
              '오늘 주문' => '최근 주문',
              '2건' => '${controller.journal.length}건',
              '전략 수익률' => '자동매매',
              '+1.82%' => '미지원',
              _ => n['value'],
            };
          }
        }
        if (screen == 4) {
          if (parent == 'Segment navigation') {
            n['value'] = switch (value) {
              '이번 주' => '최근 30일',
              '이번 달' => '기간 선택',
              '전체' => '상세 일지',
              _ => n['value'],
            };
          }
          if (value == '지난주 대비') n['value'] = '평가 표본';
          if (parent == 'AI comparison') {
            final stats = controller.journalData?['summary'];
            n['value'] = switch (value) {
              'AI 판단과 나의 거래' => '당시 AI 예측과 실제 가격 변화',
              '동일 기간 · 동일 초기 자금' => '1시간 방향 비교 · 거래 손익과 별도',
              '나의 수익률' => '방향 일치율',
              '+2.49%' =>
                stats?['prediction_accuracy'] == null
                    ? '평가 기록 없음'
                    : '${((stats['prediction_accuracy'] as num) * 100).toStringAsFixed(1)}%',
              'AI 모의전략' => '평가 표본',
              '+3.12%' => '${stats?['prediction_evaluated'] ?? 0}건',
              _ => value,
            };
            continue;
          }
          final replacements = {
            '86%': '—',
            '+12%p':
                '${controller.journalData?['summary']?['plan_evaluated'] ?? 0}건',
            '모의거래 14건 기준': '성과 집계 연결 대기',
            '+2.49%': '—',
            '+3.12%': '—',
            '손절 기준을 주문 전에 정해 두세요.': '피드백 분석 연결 대기',
          };
          n['value'] = replacements[n['value']] ?? n['value'];
          final summary =
              controller.journalData?['summary'] as Map<String, dynamic>?;
          if (value == '86%' && summary?['plan_compliance'] != null) {
            n['value'] =
                '${((summary!['plan_compliance'] as num) * 100).round()}%';
          }
          if (value == '모의거래 14건 기준' && summary != null) {
            n['value'] = '계획 평가 가능 ${summary['plan_evaluated']}건 기준';
          }
          if (value == '손절 기준을 주문 전에 정해 두세요.' &&
              controller.journalData != null) {
            n['value'] = '상세 일지에서 경고와 거래 이유를 복기하세요.';
          }
        }
        if (screen == 6 && value.startsWith('평가금액')) {
          final equity = controller.accountData?['equity_won'];
          n['value'] = equity == null
              ? '평가금액 확인 불가 · 계정 관리 →'
              : '평가금액 ${won(int.parse(equity as String))}원 · 관리 →';
        }
      }
    }
  }
}
