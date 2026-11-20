import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tradepilot_client/features/trading/data/demo_trading_repository.dart';
import 'package:tradepilot_client/features/trading/domain/trading_models.dart';
import 'package:tradepilot_client/features/trading/domain/trading_repository.dart';
import 'package:tradepilot_client/features/trading/domain/workspace_repository.dart';
import 'widget_test.dart' as harness;

class RemoteUI extends DemoTradingRepository
    implements WorkspaceRepository, ChartQuoteRepository {
  final ticks = StreamController<Quote>.broadcast();
  String? chartSymbol;
  int marketAnalysisRequests = 0;
  int candleRequests = 0;
  int fiveMinuteRequests = 0;
  int tradeDetailRequests = 0;
  bool marketAnalysisComplete = false;
  String? chartPrompt;

  @override
  bool get isDemo => false;
  @override
  Stream<Quote> get chartQuotes => ticks.stream;
  @override
  void setChartSymbol(String? symbol) => chartSymbol = symbol;
  @override
  Future<void> dispose() async {
    await ticks.close();
    await super.dispose();
  }

  @override
  Future<Map<String, dynamic>> workspaceRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    if (path == '/v1/market/005930/details/trades') {
      tradeDetailRequests++;
      return {
        'status': 'available',
        'items': [
          {
            'timestamp': '2026-11-16T09:05:01+09:00',
            'price': '198400',
            'volume': '8',
          },
        ],
      };
    }
    if (path == '/v1/ai/prompts/chart') {
      if (method == 'PUT') chartPrompt = body!['text'] as String?;
      return {
        'text': chartPrompt ?? '기본 차트 문구',
        'customized': chartPrompt != null,
        'alternate_default': '차트 전용 기본 문구',
      };
    }
    if (path.contains('/candles?')) candleRequests++;
    if (path.endsWith('/five-minute-analysis')) {
      fiveMinuteRequests++;
      return {
        'status': 'available',
        'summary': {
          'closed_at': DateTime.now().toUtc().toIso8601String(),
          'return_15m_pct': 0.3,
          'return_60m_pct': -0.2,
          'volume_change_15m_pct': 5.0,
        },
      };
    }
    if (path == '/v1/predictions/005930') {
      final at = DateTime.now().toUtc();
      return {
        'status': 'available',
        'up': 0.2,
        'neutral': 0.5,
        'down': 0.3,
        'generated_at': at.toIso8601String(),
        'valid_until': at.add(const Duration(minutes: 5)).toIso8601String(),
        'model_version': 'test-model',
      };
    }
    if (path == '/v1/market/005930/ai-analysis') {
      if (method == 'POST') {
        expect(body, {'consent': true, 'automatic': true});
        marketAnalysisRequests++;
      }
      if (marketAnalysisRequests == 0) return {'status': 'ready'};
      if (!marketAnalysisComplete) return {'status': 'pending'};
      return {
        'status': 'available',
        'result': {
          'kind': 'quant_web',
          'body':
              '## 결론\n\n> **관망** — 다음 실적 발표를 확인하세요.\n\n'
              '## 실적과 기업 가치\n\n최근 공시 실적을 확인했습니다.',
          'judgment': '관망',
        },
        'search': {'completed_calls': 1, 'sources': []},
      };
    }
    if (path.endsWith('/quote')) {
      final symbol = path.split('/')[3];
      final q = (await snapshot()).firstWhere((q) => q.symbol == symbol);
      return {
        'name': q.name,
        'quote': {
          'symbol': q.symbol,
          'name': q.name,
          'price_won': '${q.priceWon}',
          'sequence': q.sequence,
          'as_of': q.asOf.toIso8601String(),
          'source': q.source,
        },
      };
    }
    return {'items': <dynamic>[], 'status': 'unavailable'};
  }
}

void main() {
  testWidgets('chart trades refresh for the selected stock while open', (
    tester,
  ) async {
    final repo = RemoteUI();
    await harness.launch(tester, repositoryFactory: () => repo);
    await harness.tapAction(tester, 'Live stock / 005930');
    expect(
      tester.getTopLeft(find.text('체결')).dy,
      lessThan(tester.getTopLeft(find.text('삼성전자')).dy),
    );
    await tester.tap(find.text('체결'));
    await tester.pumpAndSettle();
    expect(find.text('198,400'), findsOneWidget);
    expect(find.byType(AlertDialog), findsNothing);
    expect(repo.tradeDetailRequests, 1);
    await tester.pump(const Duration(seconds: 5));
    expect(repo.tradeDetailRequests, 2);
    await tester.tap(find.widgetWithText(TextButton, '차트'));
    await tester.pumpAndSettle();
    expect(find.text('198,400'), findsNothing);
    await tester.pump(const Duration(seconds: 5));
    expect(repo.tradeDetailRequests, 2);
    await harness.finish(tester);
  });

  testWidgets('options turns off Pilot and inverts app colors', (tester) async {
    final repo = RemoteUI();
    await harness.launch(tester, repositoryFactory: () => repo);
    final filter = find.byType(ColorFiltered).first;
    final original = tester.widget<ColorFiltered>(filter).colorFilter;
    await harness.tapAction(tester, 'Tab / 더보기');
    await tester.tap(find.text('색반전 모드'));
    await tester.pumpAndSettle();
    expect(tester.widget<ColorFiltered>(filter).colorFilter, isNot(original));
    await tester.tap(find.text('TradePilot 시스템'));
    await tester.pumpAndSettle();
    await harness.tapAction(tester, 'Tab / 메인');
    await harness.tapAction(tester, 'Live stock / 005930');
    expect(repo.marketAnalysisRequests, 0);
    expect(find.text('ChatGPT 분석 열기 →'), findsNothing);
    await harness.tapAction(tester, '매수');
    await harness.tapAction(tester, '매수 주문 확인');
    expect(find.byKey(const ValueKey('ai-review-card')), findsNothing);
    expect(
      tester
          .widget<FilledButton>(find.widgetWithText(FilledButton, '모의 매수 접수하기'))
          .onPressed,
      isNotNull,
    );
    await harness.finish(tester);
  });

  testWidgets('options edits and restores the current chart prompt', (
    tester,
  ) async {
    final repo = RemoteUI();
    await harness.launch(tester, repositoryFactory: () => repo);
    await harness.tapAction(tester, 'Tab / 더보기');
    await tester.tap(find.text('차트 분석 프롬프트'));
    await tester.pumpAndSettle();
    final field = find.byType(TextField);
    expect(tester.widget<TextField>(field).controller?.text, '기본 차트 문구');
    await tester.enterText(field, '새 차트 프롬프트');
    await tester.pump();
    await tester.tap(find.text('저장'));
    await tester.pumpAndSettle();
    expect(repo.chartPrompt, '새 차트 프롬프트');
    expect(find.text('현재 사용 중 · 사용자 설정'), findsOneWidget);
    await tester.tap(find.text('기본값 복원'));
    await tester.pumpAndSettle();
    expect(repo.chartPrompt, isNull);
    expect(tester.widget<TextField>(field).controller?.text, '기본 차트 문구');
    await harness.finish(tester);
  });

  testWidgets('Pilot AI starts on chart entry and polls for the judgment', (
    tester,
  ) async {
    final repo = RemoteUI();
    await harness.launch(tester, repositoryFactory: () => repo);
    expect(repo.marketAnalysisRequests, 0);
    await harness.tapAction(tester, 'Live stock / 005930');
    expect(repo.chartSymbol, '005930');
    repo.ticks.add(
      Quote(
        symbol: '005930',
        name: '삼성전자',
        priceWon: 201234,
        asOf: DateTime.now().toUtc(),
        sequence: 0,
        source: 'toss_kr',
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('201,234원'), findsOneWidget);
    expect(
      find.text('완료 5분봉 · 15분 +0.3% · 1시간 -0.2% · 거래량 +5.0%'),
      findsOneWidget,
    );
    expect(repo.marketAnalysisRequests, 1);
    expect(find.byType(AlertDialog), findsNothing);
    expect(find.text('현재 시세를 분석하고 있어요'), findsOneWidget);
    expect(find.text('1시간 · 상승 20.0% · 중립 50.0% · 하락 30.0%'), findsOneWidget);
    expect(find.text('ChatGPT 분석 열기 →'), findsOneWidget);
    repo.marketAnalysisComplete = true;
    await tester.pump(const Duration(seconds: 3));
    await tester.pumpAndSettle();
    expect(find.text('관망'), findsOneWidget);
    await harness.tapAction(tester, 'AI forecast');
    expect(find.text('ChatGPT 시세 분석'), findsOneWidget);
    expect(find.text('결론', findRichText: true), findsWidgets);
    expect(
      find.textContaining('다음 실적 발표를 확인하세요.', findRichText: true),
      findsWidgets,
    );
    expect(find.text('실적과 기업 가치', findRichText: true), findsWidgets);
    expect(find.text('웹 검색 1회 완료'), findsOneWidget);
    expect(repo.marketAnalysisRequests, 1);
    await tester.tap(find.text('닫기'));
    await tester.pumpAndSettle();
    await harness.tapAction(tester, 'Tab / 메인');
    expect(repo.chartSymbol, isNull);
    await harness.tapAction(tester, 'Tab / 차트');
    expect(find.text('관망'), findsOneWidget);
    expect(repo.marketAnalysisRequests, 1);
    await harness.finish(tester);
  });

  testWidgets(
    'chart refreshes candles and summary every five seconds while visible',
    (tester) async {
      final repo = RemoteUI();
      await harness.launch(tester, repositoryFactory: () => repo);
      await harness.tapAction(tester, 'Live stock / 005930');
      final candles = repo.candleRequests;
      final summary = repo.fiveMinuteRequests;
      await tester.pump(const Duration(seconds: 4));
      expect(repo.candleRequests, candles);
      expect(repo.fiveMinuteRequests, summary);
      await tester.pump(const Duration(seconds: 1));
      expect(repo.candleRequests, candles + 1);
      expect(repo.fiveMinuteRequests, summary + 1);
      await harness.tapAction(tester, 'Tab / 메인');
      await tester.pump(const Duration(seconds: 6));
      expect(repo.candleRequests, candles + 1);
      expect(repo.fiveMinuteRequests, summary + 1);
      await harness.finish(tester);
    },
  );

  testWidgets('confirmation is a popup and back preserves order input', (
    tester,
  ) async {
    await harness.launch(tester, repositoryFactory: RemoteUI.new);
    await harness.tapAction(tester, 'Live stock / 005930');
    await harness.tapAction(tester, '매수');
    await harness.tapAction(tester, 'Quantity / plus');
    await harness.tapAction(tester, 'Quantity / plus');
    expect(find.text('3주'), findsOneWidget);
    await harness.tapAction(tester, '매수 주문 확인');
    expect(find.byType(Dialog), findsOneWidget);
    expect(find.text('주문을 확인해 주세요'), findsOneWidget);
    await tester.tap(find.text('뒤로'));
    await tester.pumpAndSettle();
    expect(find.byType(Dialog), findsNothing);
    expect(find.text('3주'), findsOneWidget);
    await harness.tapAction(tester, '매수 주문 확인');
    expect(find.byType(Dialog), findsOneWidget);
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.byType(Dialog), findsNothing);
    expect(find.text('3주'), findsOneWidget);
    await harness.finish(tester);
  });
}
