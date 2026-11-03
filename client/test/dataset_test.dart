import 'backtest_test.dart' show BacktestFixture;
import 'package:tradepilot_client/features/trading/presentation/backtest_screen.dart';
import 'dart:convert';
import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot_client/features/trading/domain/workspace_repository.dart';
import 'package:tradepilot_client/features/trading/presentation/dataset_screen.dart';

class DatasetFixture implements WorkspaceRepository {
  final items = <Map<String, dynamic>>[];
  final calls = <String>[];
  static const summary = {
    'bar_count': 30,
    'longest_contiguous': 30,
    'gap_count': 0,
    'first_bar': '2026-10-16T00:00:00Z',
    'last_bar': '2026-10-16T02:25:00Z',
    'warning': '출처 미검증',
  };
  @override
  Future<Map<String, dynamic>> workspaceRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    calls.add('$method $path');
    if (path.endsWith('/validate')) return summary;
    if (method == 'POST') {
      items.add({'id': 'dataset', ...body!, ...summary});
      return items.last;
    }
    if (method == 'DELETE') {
      items.clear();
      return {'deleted': true};
    }
    return {'items': items};
  }
}

class DatasetBacktestFixture extends BacktestFixture {
  @override
  Future<Map<String, dynamic>> workspaceRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) {
    if (path == '/v1/datasets') {
      return Future.value({
        'items': [
          {
            'id': 'private-id',
            'name': 'selected csv',
            'symbol': '005930',
            'provider': 'fixture',
            'data_kind': 'synthetic',
            ...DatasetFixture.summary,
          },
        ],
      });
    }
    return super.workspaceRequest(method, path, body: body);
  }
}

void main() {
  testWidgets('selected private dataset and dates reach the backtest request', (
    tester,
  ) async {
    final repo = DatasetBacktestFixture();
    await tester.pumpWidget(
      MaterialApp(home: BacktestScreen(repository: repo)),
    );
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('새 전략 저장'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('새 전략 저장'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('CSV 등록 · 내 데이터 선택'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('CSV 등록 · 내 데이터 선택'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('백테스트에서 사용'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('백테스트에서 사용'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('백테스트 실행'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('백테스트 실행'));
    await tester.pumpAndSettle();
    expect(repo.execution!['dataset_id'], 'private-id');
    expect(repo.execution!['start'], '2026-10-16T00:00:00Z');
    expect(
      DateTime.parse(repo.execution!['end'] as String),
      DateTime.utc(2026, 10, 16, 2, 30),
    );
  });

  testWidgets('file validation precedes save; private data can be deleted', (
    tester,
  ) async {
    final repo = DatasetFixture();
    await tester.pumpWidget(
      MaterialApp(
        home: DatasetScreen(
          repository: repo,
          pickFile: () async => XFile.fromData(
            utf8.encode('fixture CSV'),
            name: 'synthetic.csv',
            path: 'synthetic.csv',
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('CSV 파일 선택'));
    await tester.pumpAndSettle();
    expect(find.text('검증한 데이터 저장'), findsNothing);
    await tester.enterText(find.byType(TextField).at(2), 'test generator');
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
    expect(repo.items.single['data_kind'], 'synthetic');
    expect(
      repo.calls.indexOf('POST /v1/datasets/validate'),
      lessThan(repo.calls.indexOf('POST /v1/datasets')),
    );
    await tester.scrollUntilVisible(
      find.text('데이터 삭제'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('데이터 삭제'));
    await tester.pumpAndSettle();
    expect(repo.items, isNotEmpty);
    await tester.tap(find.text('삭제'));
    await tester.pumpAndSettle();
    expect(repo.items, isEmpty);
  });
  testWidgets('cancelled picker does not allow upload', (tester) async {
    final repo = DatasetFixture();
    await tester.pumpWidget(
      MaterialApp(
        home: DatasetScreen(repository: repo, pickFile: () async => null),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('CSV 파일 선택'));
    await tester.pumpAndSettle();
    expect(repo.calls.where((c) => c.startsWith('POST')), isEmpty);
    expect(find.text('검증한 데이터 저장'), findsNothing);
  });
}
