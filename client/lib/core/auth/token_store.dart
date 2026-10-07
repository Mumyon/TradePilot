import 'package:flutter_secure_storage/flutter_secure_storage.dart';

abstract interface class TokenStore {
  Future<String?> read();
  Future<void> write(String token);
  Future<void> clear();
  Future<String?> readSubject();
  Future<void> writeSubject(String subject);
}

class SecureTokenStore implements TokenStore {
  const SecureTokenStore();
  static const _storage = FlutterSecureStorage();
  static const _key = 'tradepilot.access_token';
  @override
  Future<String?> read() => _storage.read(key: _key);
  @override
  Future<void> write(String token) => _storage.write(key: _key, value: token);
  @override
  Future<void> clear() => _storage.delete(key: _key);
  @override
  Future<String?> readSubject() => _storage.read(key: 'tradepilot.user_id');
  @override
  Future<void> writeSubject(String subject) =>
      _storage.write(key: 'tradepilot.user_id', value: subject);
}
