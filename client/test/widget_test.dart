import 'dart:async';
import 'package:flutter/material.dart';
import 'package:tradepilot_client/features/trading/domain/models.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot_client/app/tradepilot_app.dart';
import 'package:tradepilot_client/core/design/design_document.dart';
import 'package:tradepilot_client/features/trading/data/demo_trading_repository.dart';

Future<void> launch(
  WidgetTester tester, {
  Size size = const Size(390, 844),
  DemoTradingRepository Function()? repositoryFactory,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.runAsync(DesignDocument.load);
  await tester.pumpWidget(
    TradePilotApp(
      repositoryFactory: repositoryFactory ?? DemoTradingRepository.new,
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> tapAction(WidgetTester tester, String name) async {
  final finder = find.byKey(ValueKey('action:$name')).last;
  await tester.ensureVisible(finder);
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

Future<void> finish(WidgetTester tester) async {
  expect(tester.takeException(), isNull);
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('five original tabs, search, checked order and actual journal', (
    tester,
  ) async {
    await launch(tester);
    for (final tab in ['관심종목', '차트', '자동매매', '매매일지', '전체 메뉴']) {
      expect(find.byKey(ValueKey('action:Tab / $tab')), findsOneWidget);
    }
    expect(find.text('MARKET / 시장을 읽다'), findsOneWidget);
    expect(tester.getSize(find.text('관심종목')).width, 78);
    await tapAction(tester, '관심종목 검색');
    await tester.enterText(
      find.byKey(const ValueKey('stock-search')),
      '000660',
    );
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('action:Search result / 삼성전자')),
      findsNothing,
    );
    expect(
      find.byKey(const ValueKey('action:Search result / SK하이닉스')),
      findsOneWidget,
    );
    await tapAction(tester, 'Search result / SK하이닉스');
    expect(find.text('SK하이닉스'), findsOneWidget);
    await tapAction(tester, '매수');
    for (var i = 0; i < 4; i++) {
      await tapAction(tester, 'Quantity / plus');
    }
    expect(find.text('5주'), findsOneWidget);
    expect(find.text('867,500원'), findsOneWidget);
    await tapAction(tester, '매수 주문 확인');
    expect(find.text('주문을 확인해 주세요'), findsOneWidget);
    expect(find.text('모의주문을 접수했어요'), findsNothing);
    await tapAction(tester, '모의 매수 접수하기');
    expect(find.text('모의주문을 접수했어요'), findsOneWidget);
    await tapAction(tester, '매매일지 보기');
    expect(find.text('주문 demo-1'), findsOneWidget);
    await tapAction(tester, 'Tab / 자동매매');
    expect(find.text('나의 자동매매'), findsOneWidget);
    await tapAction(tester, 'Tab / 전체 메뉴');
    expect(find.text('나의 모의투자 계좌'), findsOneWidget);
    await finish(tester);
  });

  testWidgets('blocked order remains in form and never shows success', (
    tester,
  ) async {
    await launch(tester);
    await tapAction(tester, 'Stock / 삼성전자');
    await tapAction(tester, '매수');
    for (var i = 0; i < 10; i++) {
      await tapAction(tester, 'Quantity / plus');
    }
    await tapAction(tester, '매수 주문 확인');
    expect(find.text('주문 점검 결과'), findsOneWidget);
    expect(find.text('모의주문을 접수했어요'), findsNothing);
    await tester.tap(find.text('닫기').last);
    await tester.pumpAndSettle();
    expect(find.text('11주'), findsOneWidget);
    await finish(tester);
  });

  testWidgets('small screen scrolls and popup closes without placing order', (
    tester,
  ) async {
    await launch(tester, size: const Size(320, 568));
    await tapAction(tester, 'Stock / 삼성전자');
    await tapAction(tester, '매도');
    await tapAction(tester, '닫기');
    expect(find.text('매도 주문'), findsNothing);
    await tapAction(tester, 'Tab / 매매일지');
    expect(find.text('주문 demo-1'), findsNothing);
    await finish(tester);
  });
  testWidgets('unknown response retries the same order through account menu', (
    tester,
  ) async {
    final repository = _LostResponseRepository();
    await launch(tester, repositoryFactory: () => repository);
    await tapAction(tester, 'Stock / 삼성전자');
    await tapAction(tester, '매수');
    await tapAction(tester, '매수 주문 확인');
    await tapAction(tester, '모의 매수 접수하기');
    expect(find.text('주문 결과 미확인'), findsOneWidget);
    expect(find.text('모의주문을 접수했어요'), findsNothing);
    await tester.tap(find.text('닫기').last);
    await tester.pumpAndSettle();
    await tapAction(tester, 'Tab / 전체 메뉴');
    await tapAction(tester, 'Paper account');
    await tester.tap(find.text('미확인 주문 복구'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('동일 주문 결과 재확인'));
    await tester.pumpAndSettle();
    expect(find.text('모의주문을 접수했어요'), findsOneWidget);
    expect(repository.keys.length, 2);
    expect(repository.keys.toSet().length, 1);
    expect((await repository.orders()).length, 1);
    await finish(tester);
  });
  testWidgets(
    'server mode has no invented performance and empty search works',
    (tester) async {
      await launch(tester, repositoryFactory: _ServerStyleRepository.new);
      await tapAction(tester, '관심종목 검색');
      await tester.enterText(
        find.byKey(const ValueKey('stock-search')),
        '없는종목',
      );
      await tester.pumpAndSettle();
      expect(find.text('검색 결과가 없습니다.'), findsOneWidget);
      await tapAction(tester, '닫기');
      await tapAction(tester, 'Tab / 자동매매');
      expect(find.text('10,248,600'), findsNothing);
      expect(find.text('순실현손익 —원'), findsOneWidget);
      await tapAction(tester, 'Tab / 매매일지');
      expect(find.text('86%'), findsNothing);
      expect(find.text('아직 주문 내역이 없습니다.'), findsOneWidget);
      await finish(tester);
    },
  );
  testWidgets('search remains usable above the software keyboard', (
    tester,
  ) async {
    await launch(tester, size: const Size(390, 700));
    await tapAction(tester, '관심종목 검색');
    tester.view.viewInsets = const FakeViewPadding(bottom: 300);
    addTearDown(tester.view.resetViewInsets);
    await tester.pumpAndSettle();
    final input = find.byKey(const ValueKey('stock-search'));
    expect(tester.getRect(input).bottom, lessThan(400));
    await tester.enterText(input, '삼성');
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('action:Search result / SK하이닉스')),
      findsNothing,
    );
    await tapAction(tester, '닫기');
    await finish(tester);
  });
}

class _LostResponseRepository extends DemoTradingRepository {
  final keys = <String>[];
  @override
  Future<OrderReceipt> submit(
    OrderDraft draft,
    OrderCheck check,
    String key,
  ) async {
    keys.add(key);
    final receipt = await super.submit(draft, check, key);
    if (keys.length == 1) throw TimeoutException('accepted, response lost');
    return receipt;
  }
}

class _ServerStyleRepository extends DemoTradingRepository {
  @override
  bool get isDemo => false;
}
