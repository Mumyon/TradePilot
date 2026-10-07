import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot_client/app/tradepilot_app.dart';
import 'package:tradepilot_client/features/trading/data/demo_trading_repository.dart';

void main() {
  testWidgets('demo navigation and checked order flow', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      TradePilotApp(repositoryFactory: DemoTradingRepository.new),
    );
    await tester.pumpAndSettle();
    expect(find.text('데모 · 가상 데이터'), findsOneWidget);
    await tester.tap(find.text('삼성전자'));
    await tester.pumpAndSettle();
    expect(find.text('방향 판단 보류'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('모의 매수'), 200);
    await tester.pumpAndSettle();
    await tester.tap(find.text('모의 매수'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('주문 점검'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('모의주문 최종 확인'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('모의주문 최종 확인'));
    await tester.pumpAndSettle();
    expect(find.textContaining('주문 접수 · demo-1'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpAndSettle();
  });
}
