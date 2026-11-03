import 'dart:convert';
import '../../../core/design/design_document.dart';
import '../domain/models.dart';
import '../domain/workspace_repository.dart';
import 'trading_controller.dart';

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

/// Bind server-owned facts without presenting prototype balances/returns as real.
class DesignBindings {
  DesignBindings(
    this.controller, {
    required this.screen,
    required this.quantity,
    required this.price,
    required this.side,
    required this.query,
    required this.segment,
  });
  final TradingController controller;
  final int screen, quantity, price, segment;
  final OrderSide side;
  final String query;
  bool get demo => controller.repository.isDemo;
  String get sideLabel => side == OrderSide.buy ? '매수' : '매도';
  String get stockName => controller.selected?.name ?? '종목 미연결';
  String get symbol => controller.selectedSymbol ?? '';
  String get connection => controller.online ? '시세 연결됨' : '시세 연결 대기';
  bool get confirmation =>
      screen == 5 || {11, 14, 17, 20, 23, 26, 29, 32}.contains(screen);
  bool get completion => {10, 13, 16, 19, 22, 25, 28, 31, 34}.contains(screen);
  bool get orderPopup => {12, 15, 18, 21, 24, 27, 30, 33}.contains(screen);

  void apply(DesignNode root) {
    if (screen == 0 && controller.repository is WorkspaceRepository) {
      final nodes = children(root);
      final template = nodes.firstWhere(
        (n) => (n['name'] as String? ?? '').startsWith('Stock / '),
      );
      final rows = <DesignNode>[];
      for (final q in controller.market.values) {
        final domestic = RegExp(r'^\d{6}$').hasMatch(q.symbol);
        if (segment == 1 && !domestic || segment == 2 && domestic) continue;
        final row = jsonDecode(jsonEncode(template)) as DesignNode;
        row['name'] = 'Live stock / ${q.symbol}';
        row['action'] = 'SELECT_SYMBOL';
        row['symbol'] = q.symbol;
        row['y'] = 314 + rows.length * 70;
        final texts = children(row).where((n) => n['type'] == 'text').toList();
        texts[0]['value'] = q.name;
        texts[1]['value'] = q.symbol;
        texts[2]['value'] = won(q.priceWon);
        texts[3]['value'] = q.isFresh(DateTime.now().toUtc())
            ? (q.source == 'demo' ? '테스트 시세' : q.source)
            : '시세 지연';
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
            texts[3]['value'] = q == null ? '시세 준비 중' : '가상 시세';
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
            ? '$connection · 테스트 시세 / 지수는 예시'
            : '$connection · 지수·차트는 예시';
      }
      if (screen == 0 &&
          value == '관심종목의 AI 근거를 확인하고 거래하세요.' &&
          controller.stage == OrderStage.uncertain) {
        n['value'] = '미확인 주문이 있어요. 눌러 결과를 확인하세요.';
        n['action'] = 'RECOVER';
      }
      if (screen == 1 || screen == 8) {
        if (parent.isEmpty && y == 113) n['value'] = stockName;
        if (parent.isEmpty && y == 145) n['value'] = '$symbol · 모의투자';
        if (parent.isEmpty && y == 675) {
          n['value'] =
              '기준 ${controller.selected?.asOf.toLocal().toString().split('.').first ?? '시세 없음'}';
        }
        if (parent.isEmpty && y == 171) {
          n['value'] = controller.selected == null
              ? '—'
              : won(controller.selected!.priceWon);
        }
        if (parent.isEmpty && y == 218) {
          n['value'] =
              '${controller.repository is WorkspaceRepository ? '서버 캔들' : '차트 예시'} · ${['1분', '5분', '15분', '1시간', '1일'][segment]}봉';
        }
        if (parent == 'AI forecast') {
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
                ? '다음 1시간 상승 가능성  ${(p.up * 100).round()}%'
                : controller.predictionData?['reason'] == 'model_not_configured'
                ? 'CSV 학습 데이터와 모델을 준비해 주세요'
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
        if (y == 211) n['value'] = '주문 가능 여부는 서버 점검 후 확인됩니다.';
        if (y == 324) n['value'] = '${won(price * quantity)}원';
        if (y == 495) {
          n['value'] =
              'TradePilot ${controller.pilotEnabled ? 'ON' : 'OFF'} · 행동 점검 전환';
          n['action'] = 'PILOT';
          n['name'] = 'TradePilot 행동 점검';
        }
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
        if (screen == 3 && value == '연속 손실 후 쿨다운') n['value'] = '동일 종목·방향 쿨다운';
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
          if (parent == '1회 주문한도' && number(n, 'x') > 150) {
            n['value'] =
                '${controller.settingsData?['order_limit_won'] ?? '—'}원';
          }
          if (parent == '일 손실한도' && number(n, 'x') > 150) {
            n['value'] =
                '${controller.settingsData?['daily_loss_limit_won'] ?? '—'}원';
          }
          if (parent == '연속 손실 후 쿨다운' && number(n, 'x') > 150) {
            n['value'] =
                '${controller.settingsData?['cooldown_seconds'] ?? '—'}초';
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
