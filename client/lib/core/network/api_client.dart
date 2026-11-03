import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../auth/token_store.dart';

class ApiException implements Exception {
  const ApiException(this.message, {this.statusCode});
  final String message;
  final int? statusCode;
  @override
  String toString() => message;
}

class ApiClient {
  ApiClient(this.baseUrl, this.tokens, {http.Client? client})
    : _client = client ?? http.Client();
  final Uri baseUrl;
  final TokenStore tokens;
  final http.Client _client;
  void Function()? onUnauthorized;

  Future<Map<String, dynamic>> request(
    String method,
    String path, {
    Map<String, dynamic>? body,
    String? idempotencyKey,
    bool authenticated = true,
  }) async {
    final token = authenticated ? await tokens.read() : null;
    if (authenticated && token == null) {
      throw const ApiException('로그인이 필요합니다.', statusCode: 401);
    }
    final request = http.Request(method, baseUrl.resolve(path));
    request.headers.addAll({
      'Accept': 'application/json',
      'Content-Type': 'application/json',
      if (token != null) 'Authorization': 'Bearer $token',
      'Idempotency-Key': ?idempotencyKey,
    });
    if (body != null) request.body = jsonEncode(body);
    // No automatic retries: an order may have reached the server.
    final response = await (() async {
      final streamed = await _client.send(request);
      return http.Response.fromStream(streamed);
    })().timeout(const Duration(seconds: 12));
    if (response.statusCode == 401) {
      await tokens.clear();
      onUnauthorized?.call();
      throw const ApiException('세션이 만료되었습니다. 다시 로그인하세요.', statusCode: 401);
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      String? detail;
      try {
        final parsed = jsonDecode(utf8.decode(response.bodyBytes));
        if (parsed is Map && parsed['detail'] is String) {
          detail = parsed['detail'] as String;
        }
      } catch (_) {}
      throw ApiException(
        detail ?? '입력값 또는 서버 연결을 확인하세요. (${response.statusCode})',
        statusCode: response.statusCode,
      );
    }
    return jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
  }

  Future<void> login(String email, String password) async {
    final json = await request(
      'POST',
      '/v1/auth/login',
      authenticated: false,
      body: {'email': email, 'password': password},
    );
    final token = json['access_token'] as String;
    final subject = json['user_id'] as String;
    if (token.isEmpty || subject.isEmpty) {
      throw const ApiException('잘못된 로그인 응답입니다.');
    }
    // Never leave an old token paired with a newly written account identity.
    await tokens.clear();
    await tokens.writeSubject(subject);
    await tokens.write(token);
  }

  void close() => _client.close();
}
