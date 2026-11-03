import 'package:flutter/material.dart';

import '../core/network/api_client.dart';
import '../core/design/design_document.dart';
import '../features/trading/domain/trading_repository.dart';
import '../features/trading/domain/pending_order_store.dart';
import '../features/trading/presentation/trading_screen.dart';

class TradePilotApp extends StatefulWidget {
  const TradePilotApp({
    super.key,
    required this.repositoryFactory,
    this.api,
    this.pendingOrders,
  });
  final TradingRepository Function() repositoryFactory;
  final ApiClient? api;
  final PendingOrderStore? pendingOrders;
  @override
  State<TradePilotApp> createState() => _TradePilotAppState();
}

class _TradePilotAppState extends State<TradePilotApp> {
  bool _authenticated = false, _checking = true;
  @override
  void initState() {
    super.initState();
    widget.api?.onUnauthorized = () {
      if (mounted) setState(() => _authenticated = false);
    };
    _restore();
  }

  Future<void> _restore() async {
    bool authenticated = widget.api == null;
    try {
      authenticated = authenticated || await widget.api!.tokens.read() != null;
    } catch (_) {
      authenticated = false;
    }
    if (mounted) {
      setState(() {
        _authenticated = authenticated;
        _checking = false;
      });
    }
  }

  Future<void> _logout() async {
    try {
      await widget.api?.request('POST', '/v1/auth/logout');
    } catch (_) {}
    await widget.api?.tokens.clear();
    if (mounted) setState(() => _authenticated = false);
  }

  @override
  void dispose() {
    widget.api?.onUnauthorized = null;
    widget.api?.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'TradePilot',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      brightness: Brightness.dark,
      useMaterial3: true,
      fontFamily: designFont,
      scaffoldBackgroundColor: const Color(0xFF0A0A0B),
      colorScheme: ColorScheme.fromSeed(
        seedColor: Colors.white,
        brightness: Brightness.dark,
        primary: const Color(0xFFF5F5F2),
        onPrimary: const Color(0xFF0A0A0B),
        surface: const Color(0xFF151516),
        onSurface: const Color(0xFFF5F5F2),
      ),
      inputDecorationTheme: const InputDecorationTheme(
        filled: true,
        fillColor: Color(0xFF151516),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.zero,
          borderSide: BorderSide(color: Color(0xFF303034)),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.zero,
          borderSide: BorderSide(color: Color(0xFF303034)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.zero,
          borderSide: BorderSide(color: Color(0xFFF5F5F2)),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          shape: const RoundedRectangleBorder(),
          minimumSize: const Size(0, 48),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          shape: const RoundedRectangleBorder(),
          minimumSize: const Size(0, 48),
          side: const BorderSide(color: Color(0xFF303034)),
        ),
      ),
      dialogTheme: const DialogThemeData(
        shape: RoundedRectangleBorder(),
        backgroundColor: Color(0xFF151516),
      ),
      bottomSheetTheme: const BottomSheetThemeData(
        shape: RoundedRectangleBorder(),
        backgroundColor: Color(0xFF151516),
      ),
    ),
    home: _checking
        ? const Scaffold(body: Center(child: CircularProgressIndicator()))
        : _authenticated
        ? TradingScreen(
            repositoryFactory: widget.repositoryFactory,
            pendingOrders: widget.pendingOrders,
            onLogout: widget.api == null ? null : _logout,
          )
        : _Login(
            api: widget.api!,
            onSuccess: () => setState(() => _authenticated = true),
          ),
  );
}

class _Login extends StatefulWidget {
  const _Login({required this.api, required this.onSuccess});
  final ApiClient api;
  final VoidCallback onSuccess;
  @override
  State<_Login> createState() => _LoginState();
}

class _LoginState extends State<_Login> {
  final _email = TextEditingController(), _password = TextEditingController();
  final _confirmation = TextEditingController();
  bool _signup = false;
  bool _busy = false;
  String? _error;
  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _confirmation.dispose();
    super.dispose();
  }

  Future<void> _login() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      if (_signup) {
        if (_password.text.length < 12 ||
            _password.text != _confirmation.text) {
          throw const ApiException('비밀번호는 12자 이상이며 확인 입력과 같아야 합니다.');
        }
        await widget.api.request(
          'POST',
          '/v1/auth/signup',
          authenticated: false,
          body: {
            'email': _email.text.trim(),
            'password': _password.text,
            'password_confirmation': _confirmation.text,
          },
        );
        _password.clear();
        _confirmation.clear();
        if (mounted) {
          setState(() {
            _signup = false;
            _error = '가입 완료! 새 계정으로 로그인하세요.';
          });
        }
        return;
      }
      await widget.api.login(_email.text.trim(), _password.text);
      _password.clear();
      if (mounted) widget.onSuccess();
    } catch (e) {
      if (mounted) {
        setState(
          () => _error = e is ApiException ? e.message : '계정과 서버 연결을 확인하세요.',
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: ListView(
            shrinkWrap: true,
            padding: const EdgeInsets.all(24),
            children: [
              const Text(
                'MARKET / 시장을 읽다',
                style: TextStyle(
                  fontSize: 10,
                  color: Color(0xFFA1A1A6),
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                'TradePilot',
                style: TextStyle(fontSize: 32, fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 24),
              const Text(
                '나의 모의투자 계좌로 로그인',
                style: TextStyle(fontSize: 14, color: Color(0xFFA1A1A6)),
              ),
              const SizedBox(height: 24),
              TextField(
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(labelText: '이메일'),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _password,
                obscureText: true,
                enableSuggestions: false,
                autocorrect: false,
                decoration: const InputDecoration(labelText: '비밀번호'),
              ),
              if (_signup) ...[
                const SizedBox(height: 16),
                TextField(
                  controller: _confirmation,
                  obscureText: true,
                  enableSuggestions: false,
                  autocorrect: false,
                  decoration: const InputDecoration(
                    labelText: '비밀번호 확인 (12자 이상)',
                  ),
                ),
                const Padding(
                  padding: EdgeInsets.only(top: 12),
                  child: Text('모의투자 전용 계정 · 시작 가상 자금 1,000만원'),
                ),
              ],
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text(_error!),
                ),
              const SizedBox(height: 24),
              FilledButton(
                onPressed: _busy ? null : _login,
                child: Text(
                  _busy
                      ? '연결 중'
                      : _signup
                      ? '회원가입 완료'
                      : '로그인',
                ),
              ),
              TextButton(
                onPressed: _busy
                    ? null
                    : () => setState(() {
                        _signup = !_signup;
                        _error = null;
                        _password.clear();
                        _confirmation.clear();
                      }),
                child: Text(_signup ? '로그인으로 돌아가기' : '모의투자 계정 만들기'),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}
