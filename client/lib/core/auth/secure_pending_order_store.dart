import 'dart:convert';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../../features/trading/domain/pending_order_store.dart';
import 'token_store.dart';

/// Account-scoped recovery survives process death and re-authentication.
class SecurePendingOrderStore implements PendingOrderStore {
  const SecurePendingOrderStore(this.tokens);
  final TokenStore tokens;
  static const _storage = FlutterSecureStorage();
  Future<String> _key() async {
    final subject = await tokens.readSubject();
    if (subject == null || subject.isEmpty) throw StateError('계정 확인이 필요합니다.');
    return 'tradepilot.pending.${Uri.encodeComponent(subject)}';
  }

  @override
  Future<PendingOrder?> load() async {
    final value = await _storage.read(key: await _key());
    return value == null
        ? null
        : PendingOrder.fromJson(jsonDecode(value) as Map<String, dynamic>);
  }

  @override
  Future<void> save(PendingOrder order) async =>
      _storage.write(key: await _key(), value: jsonEncode(order.toJson()));
  @override
  Future<void> clear() async => _storage.delete(key: await _key());
}
