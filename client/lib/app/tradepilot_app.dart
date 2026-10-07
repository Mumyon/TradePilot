import 'package:flutter/material.dart';

import '../core/network/api_client.dart';
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
    await widget.api?.tokens.clear();
    if (mounted) setState(() => _authenticated = false);
  }

  @override
  void dispose() {
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
      scaffoldBackgroundColor: const Color(0xFF090909),
      colorScheme: ColorScheme.fromSeed(
        seedColor: Colors.white,
        brightness: Brightness.dark,
        primary: Colors.white,
        onPrimary: Colors.black,
        surface: const Color(0xFF151515),
      ),
      inputDecorationTheme: const InputDecorationTheme(
        border: OutlineInputBorder(),
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
  bool _busy = false;
  String? _error;
  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _login() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.api.login(_email.text.trim(), _password.text);
      _password.clear();
      if (mounted) widget.onSuccess();
    } catch (_) {
      if (mounted) setState(() => _error = '로그인에 실패했습니다. 계정과 서버 연결을 확인하세요.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('TradePilot 로그인')),
    body: Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 480),
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.all(24),
          children: [
            const Text('FastAPI 서버 계정으로 로그인합니다.'),
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
            if (_error != null)
              Padding(padding: const EdgeInsets.all(12), child: Text(_error!)),
            const SizedBox(height: 24),
            FilledButton(
              onPressed: _busy ? null : _login,
              child: Text(_busy ? '연결 중' : '로그인'),
            ),
          ],
        ),
      ),
    ),
  );
}
