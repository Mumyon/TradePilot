import 'dart:convert';
import 'dart:io';
import 'package:integration_test/integration_test_driver.dart';

Future<void> main() => integrationDriver(
  responseDataCallback: (data) async {
    final captures = data?['captures'] as Map;
    await Directory('docs/replay-review-v2').create(recursive: true);
    for (final entry in captures.entries) {
      await File(
        'docs/replay-review-v2/${entry.key}.png',
      ).writeAsBytes(base64Decode(entry.value as String));
    }
    await File('docs/replay-review-v2/synthetic-results.json').writeAsString(
      const JsonEncoder.withIndent('  ').convert(data?['summary']),
    );
  },
);
