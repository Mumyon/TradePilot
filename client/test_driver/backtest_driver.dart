import 'dart:convert';
import 'dart:io';
import 'package:integration_test/integration_test_driver.dart';

Future<void> main() => integrationDriver(
  responseDataCallback: (data) async {
    final value = data?['screenshot'] as String?;
    if (value == null) throw StateError('Missing backtest screenshot');
    await Directory('docs/backtest-review').create(recursive: true);
    await File(
      'docs/backtest-review/ios-result.png',
    ).writeAsBytes(base64Decode(value));
  },
);
