import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:tradepilot_client/core/auth/token_store.dart';
import 'package:tradepilot_client/core/network/api_client.dart';

class MemoryTokens implements TokenStore {
  String? value = 'test-token';
  String? subject = 'test-user';
  @override
  Future<String?> readSubject() async => subject;
  @override
  Future<void> writeSubject(String subject) async {
    this.subject = subject;
  }

  @override
  Future<String?> read() async => value;
  @override
  Future<void> write(String token) async {
    value = token;
  }

  @override
  Future<void> clear() async {
    value = null;
  }
}

void main() {
  test('login replaces account identity and token together', () async {
    final tokens = MemoryTokens();
    final api = ApiClient(
      Uri.parse('https://example.test'),
      tokens,
      client: MockClient((request) async {
        expect(request.headers.containsKey('Authorization'), isFalse);
        return http.Response(
          '{"access_token":"new-token","user_id":"new-user"}',
          200,
        );
      }),
    );
    addTearDown(api.close);
    await api.login('user@example.test', 'password');
    expect(await tokens.read(), 'new-token');
    expect(await tokens.readSubject(), 'new-user');
  });
  test(
    'authenticated requests carry idempotency key and exact integer money string',
    () async {
      late http.Request request;
      final api = ApiClient(
        Uri.parse('https://example.test'),
        MemoryTokens(),
        client: MockClient((r) async {
          request = r;
          return http.Response('{}', 200);
        }),
      );
      addTearDown(api.close);
      await api.request(
        'POST',
        '/v1/orders',
        idempotencyKey: 'same-key',
        body: {'limit_price_won': '72800'},
      );
      expect(request.headers['Authorization'], 'Bearer test-token');
      expect(request.headers['Idempotency-Key'], 'same-key');
      expect(jsonDecode(request.body)['limit_price_won'], '72800');
    },
  );
  test('401 clears session and never retries request automatically', () async {
    final tokens = MemoryTokens();
    var attempts = 0;
    final api = ApiClient(
      Uri.parse('https://example.test'),
      tokens,
      client: MockClient((_) async {
        attempts++;
        return http.Response('{}', 401);
      }),
    );
    addTearDown(api.close);
    await expectLater(
      api.request('POST', '/v1/orders'),
      throwsA(isA<ApiException>()),
    );
    expect(await tokens.read(), isNull);
    expect(attempts, 1);
  });
}
