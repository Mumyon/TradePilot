import 'dart:convert';
import 'dart:io';
import 'package:integration_test/integration_test_driver.dart';

Future<void> main() => integrationDriver(
  responseDataCallback: (data) async {
    final captures = data?['captures'] as Map;
    await Directory('docs/manual-deferral-review').create(recursive: true);
    for (final entry in captures.entries) {
      await File(
        'docs/manual-deferral-review/${entry.key}.png',
      ).writeAsBytes(base64Decode(entry.value as String));
    }
    await File('docs/manual-deferral-review/synthetic-results.json').writeAsString(
      const JsonEncoder.withIndent('  ').convert(data?['summary']),
    );
  },
);
