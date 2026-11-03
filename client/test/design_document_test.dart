import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot_client/core/design/design_document.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('bundled design is byte-identical to user source', () {
    expect(
      File('assets/design/tradepilot.json').readAsStringSync(),
      File(
        '../UI_figma/output/TradePilot-Figma-UI/design.json',
      ).readAsStringSync(),
    );
  });
  testWidgets('all 35 original artboards and vector slots render', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final document = (await tester.runAsync(DesignDocument.load))!;
    expect(document.screens.length, 35);
    for (var i = 0; i < 35; i++) {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            backgroundColor: document.color('bg'),
            body: DesignCanvas(
              document: document,
              nodes: children(document.screen(i)),
              size: const Size(390, 844),
              onAction: (_) {},
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull, reason: 'screen $i');
    }
  });
}
