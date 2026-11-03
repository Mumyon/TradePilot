import 'dart:convert';
import 'dart:io';
import 'package:integration_test/integration_test_driver.dart';

Future<void> main() => integrationDriver(
  responseDataCallback: (data) async {
    final captures = data?['captures'] as Map;
    if (captures.length != 2) {
      throw StateError('Missing submission screenshots');
    }
    for (final entry in captures.entries) {
      await File(
        '../output/submission/TradePilot_UIUX_MVP/images/${entry.key}.png',
      ).writeAsBytes(base64Decode(entry.value as String));
    }
  },
);
