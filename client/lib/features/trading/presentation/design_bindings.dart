import '../../../core/design/design_document.dart';
import '../domain/models.dart';
import 'trading_controller.dart';

String won(int value) => '$value'.replaceAllMapped(
  RegExp(r'(\d)(?=(\d{3})+(?!\d))'), (m) => '${m[1]},',
);
String orderStatus(String status) => switch (status) {
  'accepted' => '접수', 'filled' => '체결', 'rejected' => '거절',
  'cancelled' => '취소', 'partially_filled' => '부분 체결', _ => status,
};

/// Bind server-owned facts without presenting prototype balances/returns as real.
class DesignBindings {
  DesignBindings(this.controller, {
    required this.screen, required this.quantity, required this.price,
    required this.side, required this.query, required this.segment,
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
  bool get confirmation => screen == 5 || {11,14,17,20,23,26,29,32}.contains(screen);
  bool get completion => {10,13,16,19,22,25,28,31,34}.contains(screen);
  bool get orderPopup => {12,15,18,21,24,27,30,33}.contains(screen);

  void apply(DesignNode root) {
    _walk(children(root), '');
  }

  void _walk(List<DesignNode> nodes, String parent) {
    for (final n in nodes) {
      final name = n['name'] as String? ?? '';
      if (n['type'] == 'group') {
        if (name.startsWith('Stock / ')) {
          final stock = name.substring(8);
          final code = {'삼성전자':'005930','SK하이닉스':'000660','NAVER':'035420','Apple':'AAPL'}[stock];
          final q = controller.market[code];
          final texts = children(n).where((v) => v['type'] == 'text').toList();
          if (q != null) texts[2]['value'] = won(q.priceWon);
          if (!demo) {
            texts[2]['value'] = q == null ? '미연결' : won(q.priceWon);
            texts[3]['value'] = q == null ? '시세 준비 중' : '가상 시세';
          }
          if (segment == 1 && stock == 'Apple' || segment == 2 && stock != 'Apple') n['hidden'] = true;
        }
        if (name.startsWith('Search result / ')) {
          final stock = name.substring(16);
          final code = stock == '삼성전자' ? '005930' : '000660';
          if (query.isNotEmpty && !stock.contains(query) && !code.contains(query)) n['hidden'] = true;
        }
        if (name == '전체 자동매매 중지') n['action'] = 'UNAVAILABLE';
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
        if (name == 'Journal entry' && (!demo || controller.journal.isNotEmpty)) {
          final index = number(n, 'y') < 550 ? 0 : 1;
          final texts = children(n).where((e) => e['type'] == 'text').toList();
          if (index >= controller.journal.length) {
            texts[0]['value'] = index == 0 ? '아직 주문 내역이 없습니다.' : '';
            texts[1]['value'] = index == 0 ? '모의 주문 후 이곳에서 확인하세요.' : '';
            texts[2]['value'] = '';
          } else {
            final order = controller.journal[index];
            texts[0]['value'] = controller.market[order.symbol]?.name ?? order.symbol;
            texts[0]['w'] = 240;
            texts[1]['value'] = '주문 ${order.id.length > 20 ? order.id.substring(0,20) : order.id}';
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
        n['value'] = controller.error != null ? '연결 오류 · 아래로 당겨 재시도' : '$connection · 지수·차트는 예시';
      }
      if (screen == 0 && value == '관심종목의 AI 근거를 확인하고 거래하세요.' && controller.stage == OrderStage.uncertain) {
        n['value'] = '미확인 주문이 있어요. 눌러 결과를 확인하세요.';
        n['action'] = 'RECOVER';
      }
      if (screen == 1 || screen == 8) {
        if (parent.isEmpty && y == 171) n['value'] = controller.selected == null ? '—' : won(controller.selected!.priceWon);
        if (parent.isEmpty && y == 218) n['value'] = '차트 예시 · ${['1분','5분','15분','1시간','1일'][segment]}봉';
        if (parent == 'AI forecast') {
          final p = controller.prediction;
          final valid = p != null && DateTime.now().toUtc().isBefore(p.validUntil);
          if (y == 32) n['value'] = valid ? (p.direction == '방향 판단 보류' ? '관망' : p.direction) : '대기';
          if (y == 38) n['value'] = valid ? '다음 1시간 상승 가능성  ${(p.up * 100).round()}%' : 'AI 분석이 아직 연결되지 않았어요';
          if (y == 70 && !valid) n['value'] = '분석 데이터 연결 후 표시됩니다.';
        }
      }
      if (screen == 7 || screen == 9) {
        if (value.startsWith('최근 검색')) n['value'] = query.isEmpty ? '최근 검색 · 종목을 선택하세요' : '검색 결과';
        if (value.startsWith('예시 종목')) n['value'] = '관심종목 내 이름 또는 코드로 검색하세요.';
      }
      if (orderPopup && parent == 'Popup panel') {
        if (y == 70) n['value'] = '$stockName  ·  $symbol';
        if (y == 171) { n['value'] = '${won(price)}원'; n['action'] = 'EDIT_PRICE'; n['name'] = '가격 입력'; }
        if (y == 250 && number(n, 'x') == 190) { n['value'] = '$quantity주'; n['action'] = 'EDIT_QUANTITY'; n['name'] = '수량 입력'; }
        if (y == 211) n['value'] = '주문 가능 여부는 서버 점검 후 확인됩니다.';
        if (y == 324) n['value'] = '${won(price * quantity)}원';
        if (y == 495) {
          n['value'] = 'TradePilot ${controller.pilotEnabled ? 'ON' : 'OFF'} · 행동 점검 전환';
          n['action'] = 'PILOT'; n['name'] = 'TradePilot 행동 점검';
        }
      }
      if (confirmation && screen != 5) {
        if (parent.isEmpty && y == 146) n['value'] = '$stockName · $sideLabel';
        if (parent.isEmpty && y == 192) n['value'] = '지정가 ${won(price)}원 × $quantity주';
        if (parent.isEmpty && y == 291) n['value'] = '${won(price * quantity)}원';
        if (parent == 'Order check' && y == 50) n['value'] = controller.check?.allowed == true ? '서버 주문 점검 통과' : '주문 점검 필요';
        if (parent == 'Order check' && y == 80) n['value'] = '점검 내용 보기 →';
        if (parent == 'Order check' && y == 80) { n['action'] = 'CHECK_DETAILS'; n['name'] = '점검 내용'; }
        if (value.startsWith('실제 거래로')) n['value'] = '실제 자금이 사용되지 않는 모의주문입니다.';
      }
      if (completion) {
        if (y == 220) n['value'] = '$stockName $sideLabel';
        if (y == 265) n['value'] = '$quantity주 · 지정가 ${won(price)}원';
        if (y == 306) n['value'] = '주문금액  ${won(price * quantity)}원';
        if (y == 375) n['value'] = '주문 ${orderStatus(controller.receipt?.status ?? 'accepted')} · 아직 체결되지 않았습니다.';
      }
      if (value == '전체 보기 →') { n['action'] = 'JOURNAL'; n['name'] = '전체 주문 보기'; }
      if (!demo) {
        if (screen == 3) {
          const replacements = {'10,248,600':'—', '누적 손익  +248,600원  (+2.49%)':'계좌 평가 데이터 연결 대기', '운용 중  1':'운용 중  0', '01 / ACTIVE':'01 / 준비 중', '2건':'—', '+1.82%':'—', '전체 자동매매 중지':'자동매매 연결 준비 중', '데모 상태 · 실계좌에 연결되지 않았습니다.':'자동매매 엔진은 아직 연결되지 않았습니다.', '300,000원':'연결 대기', '30분':'연결 대기'};
          n['value'] = replacements[n['value']] ?? n['value'];
        }
        if (screen == 4) {
          const replacements = {'86%':'—', '+12%p':'—', '모의거래 14건 기준':'성과 집계 연결 대기', '+2.49%':'—', '+3.12%':'—', '손절 기준을 주문 전에 정해 두세요.':'피드백 분석 연결 대기'};
          n['value'] = replacements[n['value']] ?? n['value'];
        }
        if (screen == 6 && value.startsWith('평가금액')) n['value'] = '평가금액 연결 대기 · 계정 관리 →';
      }
    }
  }
}
