import 'dart:math' as math;
import 'package:flutter/material.dart';

class MarketChart extends StatelessWidget {
  const MarketChart({super.key, required this.data});
  final Map<String, dynamic>? data;
  @override
  Widget build(BuildContext context) {
    final rows = (data?['items'] as List? ?? []).cast<Map<String, dynamic>>();
    if (rows.isEmpty) {
      return Center(child: Text(data == null ? '차트 불러오는 중…' : '캔들 데이터가 없습니다.'));
    }
    final visible = rows.skip(math.max(0, rows.length - 40)).toList();
    final last = visible.last;
    final date = DateTime.parse(last['opened_at'] as String).toLocal();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          '${data?['source'] == 'demo' ? '테스트 생성 데이터' : '수신 데이터'} · ${data?['stale'] == true ? '지연' : '갱신됨'}',
          style: const TextStyle(fontSize: 11),
        ),
        const SizedBox(height: 8),
        Expanded(child: CustomPaint(painter: _Candles(visible))),
        const SizedBox(height: 8),
        Text(
          '마지막 봉 ${date.month}/${date.day} ${date.hour.toString().padLeft(2, '0')}:${date.minute.toString().padLeft(2, '0')} · 거래량 ${last['volume']}',
          style: const TextStyle(fontSize: 10),
        ),
      ],
    );
  }
}

class _Candles extends CustomPainter {
  _Candles(this.rows);
  final List<Map<String, dynamic>> rows;
  double price(Map<String, dynamic> row, String field) =>
      double.parse(row[field] as String);
  @override
  void paint(Canvas canvas, Size size) {
    final low = rows.map((r) => price(r, 'low_won')).reduce(math.min);
    final high = rows.map((r) => price(r, 'high_won')).reduce(math.max);
    final range = math.max(1.0, high - low);
    final width = size.width - 62;
    double y(double value) => 8 + (high - value) / range * (size.height - 16);
    for (var i = 0; i < 3; i++) {
      final value = high - range * i / 2;
      final dy = y(value);
      canvas.drawLine(
        Offset(0, dy),
        Offset(width, dy),
        Paint()..color = const Color(0xff303034),
      );
      final label = TextPainter(
        text: TextSpan(
          text: value.round().toString(),
          style: const TextStyle(color: Color(0xffa1a1a6), fontSize: 10),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      label.paint(canvas, Offset(width + 5, dy - 5));
    }
    final step = width / rows.length;
    for (var i = 0; i < rows.length; i++) {
      final row = rows[i];
      final o = price(row, 'open_won'), c = price(row, 'close_won');
      final x = (i + .5) * step;
      final paint = Paint()
        ..color = (c >= o ? const Color(0xfff5f5f2) : const Color(0xff797980));
      canvas.drawLine(
        Offset(x, y(price(row, 'high_won'))),
        Offset(x, y(price(row, 'low_won'))),
        paint,
      );
      canvas.drawRect(
        Rect.fromLTWH(
          x - step * .3,
          math.min(y(o), y(c)),
          step * .6,
          math.max(1, (y(o) - y(c)).abs()),
        ),
        paint,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _Candles oldDelegate) =>
      oldDelegate.rows != rows;
}
