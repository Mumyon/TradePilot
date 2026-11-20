import 'package:flutter/material.dart';

import '../core/network/api_client.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, required this.api, required this.onSuccess});
  final ApiClient api;
  final VoidCallback onSuccess;
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen>
    with SingleTickerProviderStateMixin {
  static const _inputFill = Color(0xB3151516);
  late final _transition = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1500),
  );
  late final _formOpacity = Tween(
    begin: 1.0,
    end: 0.0,
  ).animate(_transition.drive(CurveTween(curve: const Interval(0, .23))));
  late final _photoScale = Tween(begin: 1.0, end: 1.85).animate(
    _transition.drive(
      CurveTween(curve: const Interval(.31, 1, curve: Curves.easeInCubic)),
    ),
  );
  late final _exitOpacity = _transition.drive(
    CurveTween(curve: const Interval(.82, 1, curve: Curves.easeIn)),
  );
  final _email = TextEditingController(), _password = TextEditingController();
  final _confirmation = TextEditingController();
  bool _signup = false;
  bool _busy = false;
  bool _leaving = false;
  String? _error;
  @override
  void dispose() {
    _transition.dispose();
    _email.dispose();
    _password.dispose();
    _confirmation.dispose();
    super.dispose();
  }

  Future<void> _submitAuthForm() async {
    if (_busy) return;
    FocusScope.of(context).unfocus();
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
      if (!mounted) return;
      if (!MediaQuery.disableAnimationsOf(context)) {
        setState(() => _leaving = true);
        await _transition.forward().orCancel;
        if (!mounted) return;
      }
      _password.clear();
      widget.onSuccess();
    } on TickerCanceled {
      // The login screen was removed before the transition completed.
    } catch (e) {
      if (mounted) {
        setState(
          () => _error = e is ApiException ? e.message : '계정과 서버 연결을 확인하세요.',
        );
      }
    } finally {
      if (mounted && !_leaving) setState(() => _busy = false);
    }
  }

  void _showPhotoInfo() {
    showDialog<void>(
      context: context,
      builder: (context) => const Dialog(
        alignment: Alignment.bottomLeft,
        insetPadding: EdgeInsets.fromLTRB(16, 16, 16, 62),
        constraints: BoxConstraints(maxWidth: 290),
        child: Padding(
          padding: EdgeInsets.all(16),
          child: Text(
            '푸르고 무성한 침엽수 숲을 지나가는 고요한 길, 생기 넘치는 초록 잔디로 둘러싸인 시골 풍경.',
            style: TextStyle(fontSize: 14, height: 1.45),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final keyboard = MediaQuery.viewInsetsOf(context).bottom;
    return Scaffold(
      resizeToAvoidBottomInset: false,
      body: Stack(
        fit: StackFit.expand,
        children: [
          ScaleTransition(
            key: const ValueKey('login-background-zoom'),
            scale: _photoScale,
            alignment: const Alignment(0, .22),
            child: Image.asset(
              'assets/images/login-forest.jpg',
              fit: BoxFit.cover,
              excludeFromSemantics: true,
            ),
          ),
          FadeTransition(
            opacity: _formOpacity,
            child: const DecoratedBox(
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [
                    Color(0x220A0A0B),
                    Color(0x880A0A0B),
                    Color(0x880A0A0B),
                    Color(0x550A0A0B),
                  ],
                  stops: [0, .34, .65, 1],
                ),
              ),
            ),
          ),
          IgnorePointer(
            ignoring: _leaving,
            child: FadeTransition(
              opacity: _formOpacity,
              child: SafeArea(
                child: Padding(
                  padding: EdgeInsets.only(bottom: keyboard),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Expanded(child: _buildLoginForm()),
                      if (keyboard == 0)
                        Align(
                          alignment: Alignment.centerLeft,
                          child: Padding(
                            padding: const EdgeInsets.only(left: 12),
                            child: TextButton.icon(
                              onPressed: _busy ? null : _showPhotoInfo,
                              icon: const Icon(Icons.help_outline, size: 15),
                              label: const Text('이 사진에 대한 정보'),
                              style: TextButton.styleFrom(
                                foregroundColor: const Color(0xFFF5F5F2),
                                textStyle: const TextStyle(fontSize: 12),
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            ),
          ),
          if (_leaving)
            IgnorePointer(
              child: FadeTransition(
                opacity: _exitOpacity,
                child: ColoredBox(
                  color: Theme.of(context).scaffoldBackgroundColor,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildLoginForm() => Center(
    child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 480),
      child: ListView(
        shrinkWrap: true,
        padding: const EdgeInsets.all(24),
        children: [
          const Text(
            '나만의 주식 전문가',
            style: TextStyle(
              fontSize: 10,
              color: Color(0xFFA1A1A6),
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 8),
          const Text(
            'TradePilot',
            style: TextStyle(fontSize: 35, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 24),
          const Text(
            '어서오세요. 환영합니다.',
            style: TextStyle(fontSize: 14, color: Color(0xFFA1A1A6)),
          ),
          const SizedBox(height: 24),
          TextField(
            controller: _email,
            keyboardType: TextInputType.emailAddress,
            decoration: const InputDecoration(
              labelText: '이메일',
              fillColor: _inputFill,
            ),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _password,
            obscureText: true,
            enableSuggestions: false,
            autocorrect: false,
            decoration: const InputDecoration(
              labelText: '비밀번호',
              fillColor: _inputFill,
            ),
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
                fillColor: _inputFill,
              ),
            ),
          ],
          if (_error != null)
            Padding(padding: const EdgeInsets.all(12), child: Text(_error!)),
          const SizedBox(height: 24),
          FilledButton(
            onPressed: _busy ? null : _submitAuthForm,
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
            child: Text(_signup ? '로그인으로 돌아가기' : '손쉽게 계정 만들기'),
          ),
        ],
      ),
    ),
  );
}
