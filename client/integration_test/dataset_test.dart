import 'dart:convert';
import 'dart:ui' as ui;
import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:tradepilot_client/app/tradepilot_app.dart';
import 'package:tradepilot_client/core/network/api_client.dart';
import 'package:tradepilot_client/features/trading/data/remote_trading_repository.dart';
import 'package:tradepilot_client/features/trading/presentation/dataset_screen.dart';
import '../test/api_client_test.dart' show MemoryTokens;

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('iOS validates and saves private CSV through real API', (
    tester,
  ) async {
    final api = ApiClient(Uri.parse('http://127.0.0.1:18080'), MemoryTokens());
    await api.login('integration@example.test', 'integration-only-password');
    final repo = RemoteTradingRepository(api);
    await tester.pumpWidget(TradePilotApp(repositoryFactory: () => repo));
    await tester.pumpAndSettle();
    final theme = Theme.of(tester.element(find.byType(Scaffold).first));
    final key = GlobalKey();
    final lines = ['opened_at,open_won,high_won,low_won,close_won,volume'];
    for (var i = 0; i < 30; i++) {
      final at = DateTime.utc(2026, 10, 16).add(Duration(minutes: i * 5));
      final price = 70000 + i * 10;
      lines.add(
        '${at.toIso8601String()},$price,${price + 50},${price - 50},$price,1000',
      );
    }
    // Deterministic picker result; native OS document picker itself is not automated here.
    await tester.pumpWidget(
      RepaintBoundary(
        key: key,
        child: MaterialApp(
          theme: theme,
          home: DatasetScreen(
            repository: repo,
            pickFile: () async => XFile.fromData(
              utf8.encode(lines.join('\n')),
              name: 'synthetic-ios.csv',
              path: 'synthetic-ios.csv',
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('CSV 파일 선택'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byType(TextField).at(2),
      'integration synthetic generator',
    );
    FocusManager.instance.primaryFocus?.unfocus();
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('등록 전 검증'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('등록 전 검증'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('검증한 데이터 저장'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('검증한 데이터 저장'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('백테스트에서 사용'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    final items = await api.request('GET', '/v1/datasets');
    final dataset = (items['items'] as List).single;
    expect(dataset['bar_count'], 30);
    final strategy = await api.request(
      'POST',
      '/v1/strategies',
      body: {'name': 'csv integration', 'symbol': '005930'},
    );
    final result = await api.request(
      'POST',
      '/v1/strategies/${strategy['id']}/backtests',
      body: {
        'source': 'private_csv',
        'dataset_id': dataset['id'],
        'start': '2026-10-16T00:00:00Z',
        'end': '2026-10-16T03:00:00Z',
      },
    );
    expect(result['data_label'], '합성 CSV 데이터');
    expect(result['bar_count'], 30);
    final image =
        await (key.currentContext!.findRenderObject()! as RenderRepaintBoundary)
            .toImage(pixelRatio: 2);
    final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
    binding.reportData = {
      'screenshot': base64Encode(bytes!.buffer.asUint8List()),
    };
    image.dispose();
    await tester.pumpWidget(const SizedBox());
    await repo.dispose();
  });
}
