import 'dart:convert';
import 'dart:io';
import 'package:integration_test/integration_test_driver.dart';

Future<void> main() => integrationDriver(
  responseDataCallback: (data) async {
    final output = Directory('docs/paper-review');
    await output.create(recursive: true);
    final captures = (data?['captures'] as Map?) ?? {};
    if (captures.length != 8) {
      throw StateError(
        'Expected 8 server-connected screenshots, got ${captures.length}',
      );
    }
    await File('${output.path}/latency.json').writeAsString(
      const JsonEncoder.withIndent('  ').convert(data?['latency']),
    );
    for (final entry in captures.entries) {
      await File(
        '${output.path}/${entry.key}.png',
      ).writeAsBytes(base64Decode(entry.value as String));
    }
  },
);
