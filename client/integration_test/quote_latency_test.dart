import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:tradepilot_client/app/tradepilot_app.dart';
import 'package:tradepilot_client/core/network/api_client.dart';
import 'package:tradepilot_client/features/trading/data/remote_trading_repository.dart';
import 'package:tradepilot_client/features/trading/presentation/design_bindings.dart';
import '../test/api_client_test.dart' show MemoryTokens;

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('F-01 changing WebSocket quote to completed Flutter frame latency', (
    tester,
  ) async {
    final api = ApiClient(Uri.parse('http://127.0.0.1:18080'), MemoryTokens());
    await api.login('integration@example.test', 'integration-only-password');
    final repo = RemoteTradingRepository(api);
    final pending = <Map<String, dynamic>>[];
    final samples = <Map<String, dynamic>>[];
    final missed = <int>[];
    var measuring = false;
    final subscription = repo.socket.events.listen((event) {
      if (!measuring || event['type'] != 'quote') return;
      final data = event['data'] as Map;
      if (data['symbol'] != '005930') return;
      pending.add({
        'clock': Stopwatch()..start(),
        'price': int.parse(data['price_won'] as String),
        'sequence': data['sequence'],
      });
    });
    try {
      await tester.pumpWidget(TradePilotApp(repositoryFactory: () => repo));
      await tester.pumpAndSettle();
      await Future<void>.delayed(const Duration(seconds: 5));
      await tester.pumpAndSettle();
      measuring = true;
      final deadline = Stopwatch()..start();
      while (samples.length + missed.length < 20 &&
          deadline.elapsed.inSeconds < 65) {
        await Future<void>.delayed(const Duration(milliseconds: 20));
        // pump completes framework layout and paint; wall clock is monotonic.
        await tester.pump();
        for (final sample in List<Map<String, dynamic>>.from(pending)) {
          final timer = sample['clock'] as Stopwatch;
          if (find.text(won(sample['price'] as int)).evaluate().isNotEmpty) {
            timer.stop();
            samples.add({
              'sequence': sample['sequence'],
              'price_won': sample['price'],
              'milliseconds': timer.elapsedMicroseconds / 1000,
            });
            pending.remove(sample);
          } else if (timer.elapsed.inSeconds >= 3) {
            missed.add(sample['sequence'] as int);
            pending.remove(sample);
          }
        }
      }
      measuring = false;
      final times = samples.map((s) => s['milliseconds'] as double).toList()
        ..sort();
      final average = times.isEmpty
          ? null
          : times.reduce((a, b) => a + b) / times.length;
      binding.reportData = {
        'schema': 'client-quote-latency-v1',
        'measurement':
            'decoded WebSocket event delivery to Flutter framework layout/paint completion',
        'environment':
            'iPhone 17 iOS simulator, debug build, local FastAPI and temporary PostgreSQL',
        'data_kind': 'synthetic_changing_test_prices',
        'warmup_seconds': 5,
        'requested_samples': 20,
        'rendered_samples': samples.length,
        'missed_sequences': missed,
        'unresolved_events': pending.length,
        'mean_ms': average,
        'p95_ms': times.isEmpty ? null : times[(times.length * .95).ceil() - 1],
        'max_ms': times.isEmpty ? null : times.last,
        'target_mean_ms': 2000,
        'passed': samples.length == 20 && missed.isEmpty && average! <= 2000,
        'samples': samples,
        'limits':
            'Does not measure exchange/network ingress, physical display scanout, AI inference, or real device performance.',
      };
      expect(
        samples.length,
        20,
        reason: 'Missing updates must not silently leave the denominator',
      );
      expect(missed, isEmpty);
      expect(
        samples.map((s) => s['price_won']).toSet().length,
        20,
        reason:
            'Constant prices cannot prove a newly received update was rendered',
      );
      expect(average, lessThanOrEqualTo(2000));
      expect(tester.takeException(), isNull);
    } finally {
      await subscription.cancel();
      await tester.pumpWidget(const SizedBox());
      await repo.dispose();
      api.close();
    }
  });
}
