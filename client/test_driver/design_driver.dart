import 'dart:convert';
import 'dart:io';
import 'package:integration_test/integration_test_driver.dart';

Future<void> main() => integrationDriver(
  responseDataCallback: (data) async {
    final output = Directory('docs/design-review');
    await output.create(recursive: true);
    final captures = (data?['captures'] as Map?) ?? {};
    if (captures.length != 44) {
      throw StateError(
        'Expected 35 artboards + 9 app screenshots, got ${captures.length}',
      );
    }
    for (final entry in captures.entries) {
      await File(
        '${output.path}/${entry.key}.png',
      ).writeAsBytes(base64Decode(entry.value as String));
    }
  },
);
