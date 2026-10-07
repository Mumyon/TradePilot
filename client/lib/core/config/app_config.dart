class AppConfig {
  const AppConfig({required this.demo, required this.apiUrl});

  factory AppConfig.fromEnvironment() {
    const demo = bool.fromEnvironment('DEMO_MODE', defaultValue: true);
    const url = String.fromEnvironment('API_BASE_URL');
    if (!demo && url.isEmpty) {
      throw StateError('실서버 모드에는 API_BASE_URL이 필요합니다.');
    }
    final uri = Uri.parse(url.isEmpty ? 'https://localhost.invalid' : url);
    if (uri.scheme != 'https' ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment ||
        (uri.path.isNotEmpty && uri.path != '/')) {
      throw StateError('API_BASE_URL은 경로 없는 HTTPS origin이어야 합니다.');
    }
    return AppConfig(demo: demo, apiUrl: uri);
  }
  final bool demo;
  final Uri apiUrl;
}
