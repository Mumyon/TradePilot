import 'dart:convert';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:tradepilot_client/core/design/design_document.dart';
import 'package:tradepilot_client/app/tradepilot_app.dart';
import 'package:tradepilot_client/features/trading/data/demo_trading_repository.dart';

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('iOS original artboards and working screens', (tester) async {
    final captures = <String, String>{};
    final key = GlobalKey();
    final document = await DesignDocument.load();
    for (final weight in [FontWeight.w400, FontWeight.w500, FontWeight.w600]) {
      final painter = TextPainter(
        text: TextSpan(
          text: 'TradePilot',
          style: TextStyle(
            fontFamily: designFont,
            fontWeight: weight,
            fontSize: 27,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      debugPrint('FONT_METRICS=$designFont/$weight/${painter.width}');
      painter.dispose();
    }

    Future<void> capture(String name) async {
      await tester.pumpAndSettle();
      final boundary =
          key.currentContext!.findRenderObject()! as RenderRepaintBoundary;
      final image = await boundary.toImage(pixelRatio: 2);
      final data = await image.toByteData(format: ui.ImageByteFormat.png);
      captures[name] = base64Encode(data!.buffer.asUint8List());
      image.dispose();
    }

    for (var i = 0; i < document.screens.length; i++) {
      final screen = document.screen(i);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            backgroundColor: document.color('bg'),
            body: Center(
              child: RepaintBoundary(
                key: key,
                child: ColoredBox(
                  color: document.color('bg'),
                  child: SizedBox(
                    width: 390,
                    height: 844,
                    child: Stack(
                      children: [
                        if (screen['previewBase'] != null)
                          DesignCanvas(
                            document: document,
                            nodes: children(
                              document.screen(screen['previewBase'] as int),
                            ),
                            size: const Size(390, 844),
                            onAction: (_) {},
                          ),
                        DesignCanvas(
                          document: document,
                          nodes: children(screen),
                          size: const Size(390, 844),
                          onAction: (_) {},
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      );
      await capture('reference-${i + 1}');
      expect(tester.takeException(), isNull);
    }
    await tester.pumpWidget(
      RepaintBoundary(
        key: key,
        child: TradePilotApp(repositoryFactory: DemoTradingRepository.new),
      ),
    );
    await capture('app-watchlist');
    Future<void> tap(String name) async {
      final f = find.byKey(ValueKey('action:$name')).last;
      await tester.ensureVisible(f);
      await tester.tap(f);
      await tester.pumpAndSettle();
    }

    await tap('Stock / 삼성전자');
    await capture('app-chart');
    await tap('매수');
    await capture('app-order');
    await tap('매수 주문 확인');
    await capture('app-confirm');
    await tap('모의 매수 접수하기');
    await capture('app-complete');
    await tap('Tab / 자동매매');
    await capture('app-autopilot');
    await tap('Tab / 매매일지');
    await capture('app-journal');
    await tap('Tab / 전체 메뉴');
    await capture('app-menu');
    await tap('Menu / 종목 검색');
    await capture('app-search');
    expect(tester.takeException(), isNull);
    // Path contains no credentials; used to retrieve simulator screenshots.
    binding.reportData = {'captures': captures};
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpAndSettle();
  });
}
